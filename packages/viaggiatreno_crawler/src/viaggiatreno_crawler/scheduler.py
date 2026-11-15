# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Coda di lavori con scadenza e pool di worker a concorrenza limitata.

Un solo scheduler tiene tutti i lavori in una coda ordinata per scadenza (ms). Ogni
lavoro e' identificato da `(tipo, chiave)` e ne esiste uno solo per chiave: pianificarlo
di nuovo ne sposta la scadenza. Un dispatcher porta in una coda limitata i lavori
scaduti e `workers` task li eseguono. Lo scheduler non conosce il database: lo stato
vero (le scadenze) sta nelle tabelle e al riavvio si ricostruisce da li'.

Non e' lo scheduler a limitare le richieste al secondo: quello e' il compito di
`rete.LimitatoreRichieste`, perche' il blocco del sito dipende dal ritmo e non dal
numero di richieste in volo.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
import time
from collections import Counter
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

Chiave = tuple[str, str]


class Pianificatore:
    def __init__(
        self,
        esegui: Callable[[str, str], Awaitable[None]],
        *,
        workers: int = 4,
        ritardo_errore_ms: float = 300_000,
        orologio_ms: Callable[[], float] = lambda: time.time() * 1000,
        su_errore: Callable[[str, str, BaseException], None] | None = None,
    ) -> None:
        self._esegui = esegui
        self._su_errore = su_errore
        self._workers = max(1, workers)
        self._ritardo_errore = ritardo_errore_ms
        self._ora = orologio_ms
        self._heap: list[tuple[float, int, str, str]] = []
        self._due: dict[Chiave, tuple[float, int]] = {}  # scadenza e numero d'ordine vigenti
        self._in_volo: set[Chiave] = set()  # estratti dalla coda (in attesa o in esecuzione)
        self._seq = itertools.count()
        self._sveglia = asyncio.Event()
        self._coda: asyncio.Queue[Chiave] = asyncio.Queue(maxsize=self._workers)
        self.eseguiti: Counter[str] = Counter()
        self.errori: Counter[str] = Counter()

    # -- stato ---------------------------------------------------------------

    @property
    def n_programmati(self) -> int:
        return len(self._due)

    @property
    def inattivo(self) -> bool:
        return not self._due and not self._in_volo

    def programmato(self, tipo: str, chiave: str) -> bool:
        """True se il lavoro e' in coda o e' in esecuzione adesso."""
        return (tipo, chiave) in self._due or (tipo, chiave) in self._in_volo

    def scadenza(self, tipo: str, chiave: str) -> float | None:
        """Scadenza (ms) del lavoro programmato, o None se non lo e'."""
        voce = self._due.get((tipo, chiave))
        return voce[0] if voce else None

    def prossima_scadenza_ms(self) -> float | None:
        return min((s for s, _ in self._due.values()), default=None)

    # -- pianificazione ------------------------------------------------------

    def pianifica(
        self, tipo: str, chiave: str, scadenza_ms: float, *, solo_se_prima: bool = False
    ) -> None:
        """Programma (o sposta) il lavoro. Con `solo_se_prima` non lo rimanda in avanti."""
        k = (tipo, chiave)
        attuale = self._due.get(k)
        if solo_se_prima and attuale is not None and attuale[0] <= scadenza_ms:
            return
        n = next(self._seq)
        self._due[k] = (scadenza_ms, n)
        heapq.heappush(self._heap, (scadenza_ms, n, tipo, chiave))
        self._sveglia.set()

    def annulla(self, tipo: str, chiave: str) -> None:
        self._due.pop((tipo, chiave), None)

    # -- esecuzione ----------------------------------------------------------

    def _valido(self, voce: tuple[float, int, str, str]) -> bool:
        scad, n, tipo, chiave = voce
        return self._due.get((tipo, chiave)) == (scad, n)

    async def _distribuisci(self) -> None:
        while True:
            self._sveglia.clear()
            while self._heap and not self._valido(self._heap[0]):
                heapq.heappop(self._heap)
            if not self._heap:
                await self._sveglia.wait()
                continue
            scad = self._heap[0][0]
            resto = scad - self._ora()
            if resto > 0:
                try:
                    await asyncio.wait_for(self._sveglia.wait(), resto / 1000)
                except TimeoutError:
                    pass
                continue
            _, _, tipo, chiave = heapq.heappop(self._heap)
            k = (tipo, chiave)
            if k in self._in_volo:
                # stesso lavoro ancora in corso: mai due insieme, si riprova fra poco
                self.pianifica(tipo, chiave, self._ora() + 1000)
                continue
            del self._due[k]
            self._in_volo.add(k)
            await self._coda.put(k)

    async def _lavora(self) -> None:
        while True:
            tipo, chiave = await self._coda.get()
            try:
                await self._esegui(tipo, chiave)
                self.eseguiti[tipo] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errori[tipo] += 1
                logger.exception("Lavoro %s %s fallito", tipo, chiave)
                if self._su_errore is not None:
                    try:
                        self._su_errore(tipo, chiave, exc)
                    except Exception:
                        logger.exception("Impossibile registrare l'errore di %s %s", tipo, chiave)
                if (tipo, chiave) not in self._due:  # rete di sicurezza: si riprova
                    self.pianifica(tipo, chiave, self._ora() + self._ritardo_errore)
            finally:
                self._in_volo.discard((tipo, chiave))
                self._coda.task_done()

    async def esegui(self) -> None:
        """Gira finche' non viene cancellato."""
        compiti = [asyncio.create_task(self._distribuisci())]
        compiti += [asyncio.create_task(self._lavora()) for _ in range(self._workers)]
        try:
            await asyncio.gather(*compiti)
        finally:
            for t in compiti:
                t.cancel()
            await asyncio.gather(*compiti, return_exceptions=True)
