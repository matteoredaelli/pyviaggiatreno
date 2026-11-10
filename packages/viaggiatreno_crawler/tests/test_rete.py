# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test del trasporto HTTP resiliente (nessuna rete, tempo simulato)."""

import httpx
import pytest
from viaggiatreno_crawler.rete import TransportResiliente


class Orologio:
    """Tempo finto: sleep() lo fa avanzare senza aspettare davvero."""

    def __init__(self):
        self.t = 1000.0
        self.attese: list[float] = []

    def ora(self) -> float:
        return self.t

    async def sleep(self, secondi: float) -> None:
        self.attese.append(secondi)
        self.t += secondi


class Server(httpx.AsyncBaseTransport):
    """Risponde con la sequenza di codici data, poi sempre 200."""

    def __init__(self, codici, headers=None):
        self.codici = list(codici)
        self.headers = headers or {}
        self.richieste = 0

    async def handle_async_request(self, request):
        self.richieste += 1
        if self.codici:
            codice = self.codici.pop(0)
            if isinstance(codice, Exception):
                raise codice
            return httpx.Response(codice, headers=self.headers, text="x")
        return httpx.Response(200, text="ok")


def _client(server, orologio, **kw):
    t = TransportResiliente(server, sleep=orologio.sleep, orologio=orologio.ora, jitter=0.0, **kw)
    return httpx.AsyncClient(transport=t), t


@pytest.mark.asyncio
async def test_successo_non_attende_ne_riprova():
    o, s = Orologio(), Server([])
    c, _ = _client(s, o)
    r = await c.get("http://x/a")
    assert r.status_code == 200 and s.richieste == 1 and o.attese == []


@pytest.mark.asyncio
async def test_403_attende_poi_riprova_con_successo():
    o, s = Orologio(), Server([403])
    c, _ = _client(s, o, pausa_blocco_sec=60)
    r = await c.get("http://x/a")
    assert r.status_code == 200
    assert s.richieste == 2
    assert o.attese == [60.0]  # una pausa, poi il retry


@pytest.mark.asyncio
async def test_403_ripetuto_raddoppia_la_pausa_fino_al_tetto():
    o, s = Orologio(), Server([403, 403, 403, 403])  # 4 blocchi, il 5o tentativo riesce
    c, _ = _client(s, o, max_tentativi=5, pausa_blocco_sec=60, pausa_blocco_max_sec=200)
    r = await c.get("http://x/a")
    assert r.status_code == 200
    assert o.attese == [60.0, 120.0, 200.0, 200.0]  # il 3o e 4o sarebbero 240 e 480: limitati a 200


@pytest.mark.asyncio
async def test_esauriti_i_tentativi_restituisce_il_403():
    o, s = Orologio(), Server([403, 403, 403])
    c, _ = _client(s, o, max_tentativi=3)
    r = await c.get("http://x/a")
    assert r.status_code == 403  # il client sollevera' HTTPStatusError come prima
    assert s.richieste == 3


@pytest.mark.asyncio
async def test_il_successo_azzera_il_contatore_dei_blocchi():
    o, s = Orologio(), Server([403, 200, 403])
    c, t = _client(s, o, pausa_blocco_sec=60)
    await c.get("http://x/a")  # 403 -> pausa 60 -> 200
    await c.get("http://x/b")  # 403 -> pausa 60 (non 120) -> 200
    assert o.attese == [60.0, 60.0]
    assert t._blocchi_consecutivi == 0


@pytest.mark.asyncio
async def test_retry_after_in_secondi_e_rispettato():
    o, s = Orologio(), Server([429], headers={"Retry-After": "90"})
    c, _ = _client(s, o, pausa_blocco_sec=10)
    await c.get("http://x/a")
    assert o.attese == [90.0]


@pytest.mark.asyncio
async def test_500_ritenta_con_backoff_esponenziale_non_pausa_globale():
    o, s = Orologio(), Server([503, 502])
    c, t = _client(s, o, max_tentativi=3, backoff_base_sec=1.0)
    r = await c.get("http://x/a")
    assert r.status_code == 200 and s.richieste == 3
    assert o.attese == [1.0, 2.0]  # backoff 1s, 2s
    assert t._pausa_fino == 0.0  # un 5xx non blocca le altre richieste


@pytest.mark.asyncio
async def test_errore_di_rete_viene_ritentato():
    o = Orologio()
    s = Server([httpx.ConnectTimeout("t"), 200])
    c, _ = _client(s, o, max_tentativi=3)
    assert (await c.get("http://x/a")).status_code == 200 and s.richieste == 2


@pytest.mark.asyncio
async def test_errore_di_rete_all_ultimo_tentativo_viene_sollevato():
    o = Orologio()
    s = Server([httpx.ConnectTimeout("t")] * 3)
    c, _ = _client(s, o, max_tentativi=3)
    with pytest.raises(httpx.ConnectTimeout):
        await c.get("http://x/a")


@pytest.mark.asyncio
async def test_404_non_viene_ritentato():
    o, s = Orologio(), Server([404])
    c, _ = _client(s, o)
    assert (await c.get("http://x/a")).status_code == 404 and s.richieste == 1


@pytest.mark.asyncio
async def test_la_pausa_e_condivisa_tra_richieste_concorrenti():
    """Un 403 su una richiesta mette in pausa TUTTE: nessuna parte durante l'attesa."""
    import asyncio

    class ServerOrdinato(httpx.AsyncBaseTransport):
        def __init__(self, orologio):
            self.o, self.log, self.primo = orologio, [], True

        async def handle_async_request(self, request):
            self.log.append((self.o.t, request.url.path))
            if self.primo and request.url.path == "/a":
                self.primo = False
                return httpx.Response(403, text="x")
            return httpx.Response(200, text="ok")

    o = Orologio()
    s = ServerOrdinato(o)
    t = TransportResiliente(s, sleep=o.sleep, orologio=o.ora, jitter=0.0, pausa_blocco_sec=60)
    c = httpx.AsyncClient(transport=t)
    await c.get("http://x/a")  # 403 a t=1000, pausa fino a 1060, poi retry
    await asyncio.gather(c.get("http://x/b"), c.get("http://x/c"))
    tempi = {path: ts for ts, path in s.log}
    # le richieste successive non sono partite prima della fine della pausa
    assert tempi["/b"] >= 1060.0 and tempi["/c"] >= 1060.0


@pytest.mark.asyncio
async def test_integrazione_con_il_client_della_libreria():
    """ViaggiaTrenoClient + trasporto resiliente: 403 poi 200 -> nessuna eccezione."""
    from viaggiatreno import ViaggiaTrenoClient

    class ServerStatistiche(httpx.AsyncBaseTransport):
        def __init__(self):
            self.n = 0

        async def handle_async_request(self, request):
            self.n += 1
            if self.n == 1:
                return httpx.Response(403, text="Access Denied")
            return httpx.Response(
                200,
                json={"treniGiorno": 10, "ultimoAggiornamento": 1, "treniCircolanti": 3},
            )

    o, s = Orologio(), ServerStatistiche()
    http = httpx.AsyncClient(
        transport=TransportResiliente(
            s, sleep=o.sleep, orologio=o.ora, jitter=0.0, pausa_blocco_sec=30
        )
    )
    async with ViaggiaTrenoClient(base_url="http://x/v", client=http) as c:
        stat = await c.statistiche()
    assert stat is not None and stat.treniCircolanti == 3
    assert s.n == 2 and o.attese == [30.0]


# ============================================================ proxy


_VARIABILI_PROXY = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


@pytest.fixture
def senza_proxy(monkeypatch):
    for v in _VARIABILI_PROXY:
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


def _pool(client):
    return client._transport._inner._pool


def test_senza_variabili_connessione_diretta(senza_proxy):
    from viaggiatreno_crawler.rete import crea_client_http

    assert type(_pool(crea_client_http())).__name__ == "AsyncConnectionPool"


def test_http_proxy_dall_ambiente_viene_usata(senza_proxy):
    """Con un trasporto custom httpx NON legge le variabili: dobbiamo leggerle noi."""
    from viaggiatreno_crawler.rete import crea_client_http

    senza_proxy.setenv("HTTP_PROXY", "http://proxy.finto:3128")
    pool = _pool(crea_client_http())
    assert type(pool).__name__ == "AsyncHTTPProxy"
    assert pool._proxy_url.host == b"proxy.finto" and pool._proxy_url.port == 3128


def test_minuscole_e_all_proxy_sono_accettate(senza_proxy):
    from viaggiatreno_crawler.rete import crea_client_http

    senza_proxy.setenv("http_proxy", "http://minuscolo:8080")
    assert _pool(crea_client_http())._proxy_url.host == b"minuscolo"
    senza_proxy.delenv("http_proxy")
    senza_proxy.setenv("ALL_PROXY", "http://tutti:9090")
    assert _pool(crea_client_http())._proxy_url.host == b"tutti"


def test_il_sito_e_http_quindi_vale_http_proxy_non_solo_https_proxy(senza_proxy):
    """Il sito si chiama con http://: una sola HTTPS_PROXY impostata non basta a httpx
    per instradare una richiesta http://, ma la prendiamo come ripiego."""
    from viaggiatreno_crawler.rete import crea_client_http

    senza_proxy.setenv("HTTPS_PROXY", "http://solo-https:3128")
    assert _pool(crea_client_http())._proxy_url.host == b"solo-https"


def test_proxy_esplicito_ha_la_precedenza_sull_ambiente(senza_proxy):
    from viaggiatreno_crawler.rete import crea_client_http

    senza_proxy.setenv("HTTP_PROXY", "http://dallambiente:3128")
    pool = _pool(crea_client_http(proxy="http://esplicito:8888"))
    assert pool._proxy_url.host == b"esplicito" and pool._proxy_url.port == 8888


def test_proxy_con_credenziali(senza_proxy):
    from viaggiatreno_crawler.rete import crea_client_http

    pool = _pool(crea_client_http(proxy="http://utente:segreto@proxy:3128"))
    assert pool._proxy_url.host == b"proxy"
    assert pool._proxy_headers  # Proxy-Authorization presente


def test_trust_env_falso_ignora_l_ambiente(senza_proxy):
    from viaggiatreno_crawler.rete import crea_client_http

    senza_proxy.setenv("HTTP_PROXY", "http://dallambiente:3128")
    assert type(_pool(crea_client_http(trust_env=False))).__name__ == "AsyncConnectionPool"


def test_il_proxy_non_rompe_retry_e_pausa_sul_403(senza_proxy):
    """Il trasporto resiliente resta in cima: il 403 attiva ancora la pausa."""
    from viaggiatreno_crawler.rete import crea_client_http

    assert type(crea_client_http(proxy="http://p:1")._transport).__name__ == "TransportResiliente"


def test_flag_cli_proxy():
    from viaggiatreno_crawler.__main__ import parse_args

    assert parse_args(["run"]).rete_proxy is None
    assert parse_args(["run", "--proxy", "http://p:3128"]).rete_proxy == "http://p:3128"
