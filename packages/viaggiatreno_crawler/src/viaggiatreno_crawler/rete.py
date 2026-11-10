# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Trasporto HTTP resiliente per il crawler: retry, backoff e pausa dopo un blocco.

ViaggiaTreno risponde `403 Forbidden` (pagina "Access Denied" dell'edge) quando
riceve troppe richieste ravvicinate. Il client della libreria non ha retry: un
403 o un 5xx diventa un'eccezione e, nei cicli del crawler, poteva interrompere
l'intero giro. Qui la gestione sta a livello di trasporto httpx, quindi vale per
*tutte* le chiamate del crawler senza toccare i punti di chiamata.

Comportamento:
- 403/429 (blocco): pausa **globale**, condivisa da tutte le richieste in volo
  (le chiamate concorrenti della verifica aspettano insieme, non martellano).
  La pausa raddoppia a ogni blocco consecutivo (fino a un massimo) e si azzera
  al primo successo. Rispetta `Retry-After` se espresso in secondi.
- 500/502/503/504 ed errori di rete/timeout: retry con backoff esponenziale e
  jitter, solo per la richiesta interessata.
- Esauriti i tentativi la risposta di errore viene restituita così com'è
  (il client solleva `HTTPStatusError` come prima) e i cicli saltano l'elemento.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

_BLOCCO = frozenset({403, 429})
_TRANSITORI = frozenset({500, 502, 503, 504})


class TransportResiliente(httpx.AsyncBaseTransport):
    """Avvolge un trasporto httpx aggiungendo retry, backoff e pausa su blocco."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport | None = None,
        *,
        max_tentativi: int = 3,
        pausa_blocco_sec: float = 60.0,
        pausa_blocco_max_sec: float = 600.0,
        backoff_base_sec: float = 1.0,
        jitter: float = 0.25,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        orologio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner if inner is not None else httpx.AsyncHTTPTransport()
        self._max_tentativi = max(1, max_tentativi)
        self._pausa_iniziale = pausa_blocco_sec
        self._pausa_max = max(pausa_blocco_sec, pausa_blocco_max_sec)
        self._backoff_base = backoff_base_sec
        self._jitter = jitter
        self._sleep = sleep
        self._orologio = orologio
        self._pausa_fino = 0.0
        self._blocchi_consecutivi = 0

    # -- stato condiviso -----------------------------------------------------

    async def _attendi_pausa(self) -> None:
        while True:
            resto = self._pausa_fino - self._orologio()
            if resto <= 0:
                return
            await self._sleep(resto)

    def _registra_blocco(self, richiesta: httpx.Request, risposta: httpx.Response) -> None:
        # Più richieste concorrenti vedono lo stesso blocco: è un solo evento.
        # Se la pausa è già attiva, non la allungo né faccio salire il contatore.
        if self._orologio() < self._pausa_fino:
            return
        self._blocchi_consecutivi += 1
        pausa = min(self._pausa_max, self._pausa_iniziale * 2 ** (self._blocchi_consecutivi - 1))
        retry_after = _retry_after_sec(risposta)
        if retry_after is not None:
            pausa = min(self._pausa_max, max(pausa, retry_after))
        self._pausa_fino = self._orologio() + pausa
        logger.warning(
            "HTTP %d da %s: pausa di %.0fs (blocchi consecutivi: %d)",
            risposta.status_code,
            richiesta.url.host,  # non risposta.request: a questo livello non e' ancora impostata
            pausa,
            self._blocchi_consecutivi,
        )

    def _registra_successo(self) -> None:
        if self._blocchi_consecutivi:
            logger.info("Connessione ripristinata dopo %d blocchi", self._blocchi_consecutivi)
            self._blocchi_consecutivi = 0

    def _backoff(self, tentativo: int) -> float:
        base = self._backoff_base * 2 ** (tentativo - 1)
        return base + random.uniform(0, self._jitter * base)

    # -- httpx ---------------------------------------------------------------

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        for tentativo in range(1, self._max_tentativi + 1):
            await self._attendi_pausa()
            ultimo = tentativo == self._max_tentativi
            try:
                risposta = await self._inner.handle_async_request(request)
            except httpx.TransportError:
                if ultimo:
                    raise
                await self._sleep(self._backoff(tentativo))
                continue

            codice = risposta.status_code
            if codice in _BLOCCO:
                self._registra_blocco(request, risposta)
                if ultimo:
                    return risposta
                await risposta.aclose()
                continue
            if codice in _TRANSITORI:
                if ultimo:
                    return risposta
                await risposta.aclose()
                await self._sleep(self._backoff(tentativo))
                continue

            self._registra_successo()
            return risposta
        raise RuntimeError("non raggiungibile")  # pragma: no cover

    async def aclose(self) -> None:
        await self._inner.aclose()


def _retry_after_sec(risposta: httpx.Response) -> float | None:
    valore = risposta.headers.get("retry-after")
    if valore is None:
        return None
    try:
        return max(0.0, float(valore))
    except ValueError:
        return None  # formato data HTTP: non gestito, si usa il backoff


def _trasporto_base(proxy: str | None, trust_env: bool) -> httpx.AsyncHTTPTransport:
    """Trasporto httpx di base con il proxy, se c'e'.

    Quando a `httpx.AsyncClient` si passa un trasporto proprio, httpx **non**
    legge piu' le variabili d'ambiente del proxy (`allow_env_proxies = trust_env
    and transport is None`). Qui le si legge a mano, così `HTTPS_PROXY`/`HTTP_PROXY`
    /`ALL_PROXY`/`NO_PROXY` funzionano come per un client normale.

    Priorita': `proxy` esplicito (opzione `--proxy`) > variabili d'ambiente.
    """
    if proxy:
        return httpx.AsyncHTTPTransport(proxy=proxy)
    if trust_env:
        # Il sito e' http:// (vedi DEFAULT_BASE_URL): conta HTTP_PROXY, con ALL_PROXY
        # come ripiego. NO_PROXY e' rispettato da get_environment_proxies().
        from httpx._utils import get_environment_proxies

        mappa = get_environment_proxies()
        for schema in ("http://", "https://", "all://"):
            url = mappa.get(schema)
            if url:
                return httpx.AsyncHTTPTransport(proxy=url)
    return httpx.AsyncHTTPTransport()


def crea_client_http(
    *,
    max_tentativi: int = 3,
    pausa_blocco_sec: float = 60.0,
    pausa_blocco_max_sec: float = 600.0,
    timeout: float = 20.0,
    proxy: str | None = None,
    trust_env: bool = True,
) -> httpx.AsyncClient:
    """`httpx.AsyncClient` con il trasporto resiliente, da passare a `ViaggiaTrenoClient`.

    Proxy: se `proxy` e' dato lo usa; altrimenti, con `trust_env`, legge le variabili
    d'ambiente standard (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`).
    """
    from viaggiatreno.api.client import DEFAULT_USER_AGENT

    return httpx.AsyncClient(
        transport=TransportResiliente(
            _trasporto_base(proxy, trust_env),
            max_tentativi=max_tentativi,
            pausa_blocco_sec=pausa_blocco_sec,
            pausa_blocco_max_sec=pausa_blocco_max_sec,
        ),
        timeout=timeout,
        headers={"User-Agent": DEFAULT_USER_AGENT},
        follow_redirects=True,
    )
