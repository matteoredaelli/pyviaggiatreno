# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crawler a eventi: una coda di lavori con scadenza invece di cicli a intervallo fisso.

Tre tipi di lavoro (vedi `Motore._esegui`):

- `censisci_stazione`: stazione nuova o non capolinea. Una sola richiesta di partenze
  per capire se e' l'origine di qualche treno e scoprire treni; poi si richiama solo
  ogni `ricensimento_sec`. Se risulta capolinea passa a `sonda_stazione`.
- `sonda_stazione`: capolinea (origine o destinazione di almeno un treno). Partenze e
  arrivi, ripetuti quando la finestra del tabellone e' coperta (non prima).
- `verifica_treno`: `andamentoTreno`, una volta alla partenza (itinerario, capolinea,
  orari) e una dopo l'arrivo previsto (esito e ritardo finale), non di piu'.

Lo stato vero e' nel DB (`stops.prossima_sonda`, `treni.prossima_verifica`): la coda in
memoria si ricostruisce all'avvio con `Motore.ricostruisci`, senza ricordare nulla.
Il ritmo verso il sito lo limita `rete.LimitatoreRichieste`, non il numero di worker.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import random
import signal
import sqlite3
import time
from collections.abc import Callable
from datetime import timedelta

from viaggiatreno import ViaggiaTrenoClient
from viaggiatreno.insights import ProfiloTreno, data_locale, ora_locale_ms

from viaggiatreno_crawler import storage, viste
from viaggiatreno_crawler.config import ConfigEventi
from viaggiatreno_crawler.poller import (
    _orario_int,
    carica_dimensioni,
    persisti_andamento,
    scan_range_numeri,
    scopri_treni,
)
from viaggiatreno_crawler.rete import LimitatoreRichieste, crea_client_http
from viaggiatreno_crawler.scheduler import Pianificatore

logger = logging.getLogger(__name__)

CENSISCI = "censisci_stazione"
SONDA = "sonda_stazione"
VERIFICA = "verifica_treno"
TRATTE = "scopri_tratte"
SCAN = "scan_numeri"

_K_ULTIMO_TRATTE = "ultimo_giro_eventi_tratte"
_K_ULTIMO_SCAN = "ultimo_giro_eventi_scan"

# Un tabellone con almeno tante righe e' "pieno": la sua ultima riga e' il limite della
# finestra, non l'ultimo treno che passa. Sotto questa soglia la finestra e' ignota.
_RIGHE_TABELLONE_PIENO = 8
_SONDA_MINIMA_SEC = 600
_VERIFICA_SENZA_ARRIVO_SEC = 1800
_MS = 1000


def prossima_sonda_ms(
    ora_ms: int,
    finestre: list[tuple[int, int | None]],
    cfg: ConfigEventi,
    rng: Callable[[], float] = random.random,
) -> int:
    """Quando richiamare un capolinea, dato (n_righe, ultimo_orario) di ogni tabellone letto.

    Normalmente `sonda_intervallo_sec`. Se un tabellone pieno mostra una finestra piu'
    corta, si richiama a (fine finestra - margine), mai sotto 10 minuti. Il jitter
    anticipa soltanto (mai oltre la fine della finestra).
    """
    intervallo = cfg.sonda_intervallo_sec * _MS
    for n_righe, fine in finestre:
        if n_righe >= _RIGHE_TABELLONE_PIENO and fine is not None and fine > ora_ms:
            copre = fine - ora_ms - cfg.sonda_margine_sec * _MS
            intervallo = min(intervallo, max(copre, _SONDA_MINIMA_SEC * _MS))
    intervallo = int(intervallo * (1 - cfg.sonda_jitter * rng()))
    return ora_ms + max(intervallo, _SONDA_MINIMA_SEC * _MS // 2)


def scadenza_orario_ms(ora_ms: int, cfg: ConfigEventi, rng: random.Random) -> int:
    """Scadenza casuale di un record d'orario: tra `orario_giorni_min` e `_max` giorni da ora,
    a un'ora locale casuale in [`orario_ora_min`, `orario_ora_max`).

    Il caso distribuisce le riletture sull'arco della giornata e dei giorni, invece di farle
    cadere tutte insieme (e sempre nello stesso giorno della settimana).
    """
    giorni = rng.randint(cfg.orario_giorni_min, cfg.orario_giorni_max)
    minuti = rng.randrange((cfg.orario_ora_max - cfg.orario_ora_min) * 60)
    ora, minuto = divmod(cfg.orario_ora_min * 60 + minuti, 60)
    return ora_locale_ms(data_locale(ora_ms) + timedelta(days=giorni), ora, minuto)


class Motore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        client: ViaggiaTrenoClient,
        config: ConfigEventi,
        *,
        orologio_ms: Callable[[], float] = lambda: time.time() * 1000,
        rng: random.Random | None = None,
    ) -> None:
        self.conn = conn
        self.client = client
        self.cfg = config
        self._rng = rng or random.Random()
        self._orario = config.modalita == "orario"
        # Parametri della sonda: in modalita' "orario" intervallo e margine sono i suoi.
        self._cfg_sonda = (
            dataclasses.replace(
                config,
                sonda_intervallo_sec=config.orario_sonda_sec,
                sonda_margine_sec=config.orario_sonda_margine_sec,
            )
            if self._orario
            else config
        )
        self._ora_f = orologio_ms
        self.pian = Pianificatore(
            self._esegui,
            workers=config.workers,
            ritardo_errore_ms=config.errore_attesa_sec * _MS,
            orologio_ms=orologio_ms,
            su_errore=self._registra_errore,
        )

    def ora(self) -> int:
        return int(self._ora_f())

    def _registra_errore(self, fonte: str, chiave: str | None, exc: BaseException) -> None:
        storage.registra_errore(self.conn, self.ora(), fonte, chiave, exc)
        self.conn.commit()

    # ------------------------------------------------------------------ avvio

    def ricostruisci(self) -> tuple[int, int]:
        """Rimette in coda stazioni e treni dalle scadenze salvate. Restituisce (stazioni, treni)."""
        ora = self.ora()
        chiusi = storage.chiudi_scaduti(self.conn, ora, self.cfg.verifica_scadenza_max_sec * _MS)
        if chiusi:
            logger.info("Avvio: chiusi %d treni scaduti", chiusi)
        storage.ricava_capolinea(self.conn)
        storage.ricava_tipo_giorno(self.conn)
        self.conn.commit()

        n_staz = 0
        for r in self.conn.execute(
            "SELECT stop_id, prossima_sonda, e_origine, e_destinazione FROM stops"
        ).fetchall():
            tipo = SONDA if (r["e_origine"] or r["e_destinazione"]) else CENSISCI
            quando = r["prossima_sonda"] if r["prossima_sonda"] is not None else ora
            self.pian.pianifica(tipo, r["stop_id"], quando)
            n_staz += 1

        # Lavori periodici: riprendono da dove erano, senza ripartire subito a ogni riavvio.
        if self.cfg.tratte_intervallo_sec > 0:
            self._riprendi_periodico(TRATTE, _K_ULTIMO_TRATTE, self.cfg.tratte_intervallo_sec, ora)
        if self.cfg.scan_intervallo_sec > 0:
            self._riprendi_periodico(SCAN, _K_ULTIMO_SCAN, self.cfg.scan_intervallo_sec, ora)

        n_treni = 0
        for r in self.conn.execute(
            "SELECT id, orario_partenza, prossima_verifica FROM treni WHERE stato = 'in_corso'"
        ).fetchall():
            quando = r["prossima_verifica"]
            if quando is None:
                quando = self._quando_prima_verifica(r["orario_partenza"], ora)
            self.pian.pianifica(VERIFICA, str(r["id"]), quando)
            n_treni += 1
        return n_staz, n_treni

    def _riprendi_periodico(self, tipo: str, chiave_stato: str, intervallo_sec: int, ora: int):
        ultimo = storage.get_stato(self.conn, chiave_stato)
        try:
            quando = int(ultimo) + intervallo_sec * _MS if ultimo is not None else ora
        except ValueError:
            quando = ora
        self.pian.pianifica(tipo, tipo, min(max(quando, ora), ora + intervallo_sec * _MS))

    def _quando_prima_verifica(self, orario_partenza: int | None, ora: int) -> int:
        if orario_partenza is None:
            return ora
        return max(ora, orario_partenza - self.cfg.verifica_anticipo_sec * _MS)

    # ------------------------------------------------------------------ dispatch

    async def _esegui(self, tipo: str, chiave: str) -> None:
        if tipo in (CENSISCI, SONDA):
            await self._stazione(chiave, tipo)
        elif tipo == VERIFICA:
            await self._verifica(int(chiave))
        elif tipo == TRATTE:
            await self._tratte()
        elif tipo == SCAN:
            await self._scan()
        else:  # pragma: no cover
            raise ValueError(f"tipo di lavoro sconosciuto: {tipo}")

    # ------------------------------------------------------------------ stazioni

    def _e_capolinea(self, stop_id: str) -> bool:
        r = self.conn.execute(
            "SELECT e_origine, e_destinazione FROM stops WHERE stop_id = ?", (stop_id,)
        ).fetchone()
        return bool(r and (r["e_origine"] or r["e_destinazione"]))

    def _programma_stazione(self, tipo: str, stop_id: str, quando: int) -> None:
        self.pian.pianifica(tipo, stop_id, quando)
        storage.imposta_scadenza_stazione(self.conn, stop_id, quando)

    def _stazione_vista(self, stop_id: str, nome: str | None, fonte: str) -> None:
        """Registra una stazione; se e' nuova la mette subito in censimento."""
        if storage.registra_stop_se_nuovo(self.conn, stop_id, nome, fonte):
            logger.info("Nuova stazione %s (%s) da %s", stop_id, nome, fonte)
            self._programma_stazione(CENSISCI, stop_id, self.ora())

    def _capolinea(
        self, stop_id: str, nome: str | None, fonte: str, *, origine: bool, destinazione: bool
    ) -> None:
        self._stazione_vista(stop_id, nome, fonte)
        if storage.segna_capolinea(self.conn, stop_id, origine=origine, destinazione=destinazione):
            ora = self.ora()
            logger.info("Capolinea: %s", stop_id)
            self.pian.annulla(CENSISCI, stop_id)
            attuale = self.pian.scadenza(SONDA, stop_id)
            if attuale is None or attuale > ora:
                self._programma_stazione(SONDA, stop_id, ora)

    async def _tabellone(self, stop_id: str, tipo: str) -> list | None:
        """Una richiesta di tabellone, registrata in `tabelloni_richieste`. None se fallita."""
        ts = self.ora()
        metodo = self.client.partenze if tipo == "partenze" else self.client.arrivi
        try:
            board = await metodo(stop_id)
        except Exception as exc:  # noqa: BLE001 - un tabellone che fallisce non ferma il lavoro
            logger.warning("Tabellone %s di %s fallito: %s", tipo, stop_id, exc)
            storage.registra_errore(self.conn, ts, f"tabellone {tipo}", stop_id, exc)
            storage.registra_richiesta_tabellone(
                self.conn, stop_id=stop_id, tipo=tipo, esito="errore", ts_ms=ts
            )
            return None
        orari = [
            _orario_int(r.orarioPartenza if tipo == "partenze" else r.orarioArrivo) for r in board
        ]
        validi = [o for o in orari if o is not None]
        storage.registra_richiesta_tabellone(
            self.conn,
            stop_id=stop_id,
            tipo=tipo,
            esito="ok",
            ts_ms=ts,
            n_righe=len(board),
            orario_min=min(validi) if validi else None,
            orario_max=max(validi) if validi else None,
            n_senza_orario=len(orari) - len(validi),
        )
        return board

    def _riga_tabellone(self, riga, stop_id: str, tipo: str) -> None:
        """Una riga di tabellone: stazioni di origine/destinazione, e il treno se e' nuovo."""
        if riga.codOrigine is None or riga.dataPartenzaTreno is None:
            return
        self._capolinea(
            riga.codOrigine, riga.origine, "tabellone", origine=True, destinazione=False
        )
        if riga.codDestinazione:
            self._capolinea(
                riga.codDestinazione,
                riga.destinazione,
                "tabellone",
                origine=False,
                destinazione=True,
            )

        # L'orario di una riga e' quello nella stazione del tabellone: coincide con la
        # partenza dall'origine solo se il tabellone e' quello dell'origine. Altrimenti
        # (stazioni di transito) e' piu' tardi, anche di ore: non va salvato come tale.
        orario = None
        if tipo == "partenze" and riga.codOrigine == stop_id:
            orario = _orario_int(riga.orarioPartenza)

        esiste = self.conn.execute(
            "SELECT id, orario_partenza FROM treni "
            "WHERE numero_treno = ? AND cod_origine = ? AND data_partenza_treno = ?",
            (riga.numeroTreno, riga.codOrigine, riga.dataPartenzaTreno),
        ).fetchone()
        if esiste is not None:
            if orario is not None and esiste["orario_partenza"] is None:
                self.conn.execute(
                    "UPDATE treni SET orario_partenza = ? WHERE id = ?", (orario, esiste["id"])
                )
            return

        scade = None
        if self._orario:
            # Un treno si scarica una volta per (numero, origine, tipo di giorno) finche' il
            # record vale: le altre corse dello stesso tipo non servono (stesso orario).
            if storage.orario_valido(
                self.conn,
                riga.numeroTreno,
                riga.codOrigine,
                storage.tipo_giorno_di(riga.dataPartenzaTreno),
                self.ora(),
            ):
                return
            scade = scadenza_orario_ms(self.ora(), self.cfg, self._rng)

        treno_id = storage.upsert_treno(
            self.conn,
            numero_treno=riga.numeroTreno,
            cod_origine=riga.codOrigine,
            data_partenza_treno=riga.dataPartenzaTreno,
            categoria=riga.categoria,
            cod_destinazione=riga.codDestinazione,
            origine=riga.origine,
            destinazione=riga.destinazione,
            codice_cliente=riga.codiceCliente,
            ritardo_corrente=riga.ritardo,
            raw_json=riga.model_dump_json(),
            orario_partenza=orario,
        )
        if scade is not None:
            storage.imposta_scade_orario(self.conn, treno_id, scade)
        quando = self._quando_prima_verifica(orario, self.ora())
        storage.imposta_scadenza_treno(self.conn, treno_id, quando)
        self.pian.pianifica(VERIFICA, str(treno_id), quando)

    async def _stazione(self, stop_id: str, tipo: str) -> None:
        # Modalita' "orario": anche una stazione nuova si legge in partenze e arrivi.
        richieste = (
            ["partenze"] if tipo == CENSISCI and not self._orario else ["partenze", "arrivi"]
        )
        ora = self.ora()
        riuscito = True
        finestre: list[tuple[int, int | None]] = []
        for t in richieste:
            board = await self._tabellone(stop_id, t)
            if board is None:
                riuscito = False
                continue
            for riga in board:
                self._riga_tabellone(riga, stop_id, t)
            orari = [
                _orario_int(r.orarioPartenza if t == "partenze" else r.orarioArrivo) for r in board
            ]
            validi = [o for o in orari if o is not None]
            finestre.append((len(board), max(validi) if validi else None))
            self.conn.commit()
        if riuscito:
            storage.segna_tabellone(self.conn, stop_id, ora)

        # Si rilegge se e' capolinea *dopo* le righe: puo' essere diventato tale adesso.
        if not riuscito:
            self._programma_stazione(tipo, stop_id, ora + self.cfg.errore_attesa_sec * _MS)
        elif self._e_capolinea(stop_id):
            # Appena scoperto con le sole partenze: gli arrivi mancano, si fanno subito.
            if tipo == CENSISCI and len(richieste) == 1:
                quando = ora
            elif self._orario and all(n == 0 for n, _ in finestre):
                quando = ora + self.cfg.orario_sonda_vuota_sec * _MS
            else:
                quando = prossima_sonda_ms(ora, finestre, self._cfg_sonda, self._rng.random)
            self._programma_stazione(SONDA, stop_id, quando)
        elif self._orario:
            quando = scadenza_orario_ms(ora, self.cfg, self._rng)
            self._programma_stazione(CENSISCI, stop_id, quando)
        else:
            self._programma_stazione(CENSISCI, stop_id, ora + self.cfg.ricensimento_sec * _MS)
        self.conn.commit()

    # ------------------------------------------------------------------ treni

    def _applica_itinerario(self, profilo: ProfiloTreno) -> None:
        """Stazioni nuove e capolinea (prima e ultima fermata non soppressa) di un itinerario."""
        for f in profilo.fermate:
            self._stazione_vista(f.codice, f.nome, "itinerario")
        prima = profilo.fermata_origine_effettiva
        ultima = profilo.fermata_destinazione_effettiva
        if prima is None or ultima is None:
            return
        self._capolinea(prima.codice, prima.nome, "itinerario", origine=True, destinazione=False)
        if ultima.codice != prima.codice:
            self._capolinea(
                ultima.codice, ultima.nome, "itinerario", origine=False, destinazione=True
            )

    def _chiudi_verifica(self, treno_id: int, arrivo: int | None = None) -> None:
        """Il treno non va piu' verificato: azzera la scadenza nel DB e toglie il lavoro dalla coda."""
        storage.imposta_scadenza_treno(self.conn, treno_id, None, arrivo)
        self.pian.annulla(VERIFICA, str(treno_id))

    def _rinvia_verifica(self, treno_id: int, quando: int, arrivo: int | None = None) -> None:
        storage.imposta_scadenza_treno(self.conn, treno_id, quando, arrivo)
        self.pian.pianifica(VERIFICA, str(treno_id), quando)

    async def _verifica(self, treno_id: int) -> None:
        cfg = self.cfg
        row = self.conn.execute("SELECT * FROM treni WHERE id = ?", (treno_id,)).fetchone()
        if row is None:
            return
        if row["stato"] != "in_corso":
            self._chiudi_verifica(treno_id)
            self.conn.commit()
            return

        status = await self.client.andamento_treno(
            row["cod_origine"], row["numero_treno"], row["data_partenza_treno"]
        )
        ora = self.ora()
        storage.segna_verifica(self.conn, treno_id, ora)

        if status is None:
            esito = storage.registra_204(self.conn, treno_id, cfg.soglia_204, ora)
            if esito == "chiuso":
                logger.info(
                    "Treno %s (id=%d) chiuso: risposte vuote", row["numero_treno"], treno_id
                )
                self._chiudi_verifica(treno_id)
            else:
                quando = ora + cfg.verifica_retry_sec * _MS
                if esito == "atteso" and row["orario_partenza"] is not None:
                    quando = max(quando, row["orario_partenza"] - cfg.verifica_anticipo_sec * _MS)
                self._rinvia_verifica(treno_id, quando)
            self.conn.commit()
            return

        profilo = ProfiloTreno.da_status(status)
        _, stato = persisti_andamento(self.conn, row, status, profilo, cfg.raw_json_completo)
        self._applica_itinerario(profilo)
        if stato != "in_corso":
            self._chiudi_verifica(treno_id, profilo.arrivo_previsto)
            self.conn.commit()
            return

        arrivo = profilo.arrivo_previsto
        if arrivo is None:
            quando = ora + _VERIFICA_SENZA_ARRIVO_SEC * _MS
        elif ora > arrivo + cfg.verifica_scadenza_max_sec * _MS:
            self.conn.execute(
                "UPDATE treni SET stato = 'non_disponibile', chiusura_motivo = 'scaduto', "
                "prossima_verifica = NULL, arrivo_previsto = ? WHERE id = ?",
                (arrivo, treno_id),
            )
            self.pian.annulla(VERIFICA, str(treno_id))
            self.conn.commit()
            return
        else:
            quando = max(
                arrivo + cfg.verifica_margine_arrivo_sec * _MS, ora + cfg.verifica_retry_sec * _MS
            )
        self._rinvia_verifica(treno_id, quando, arrivo)
        self.conn.commit()

    # ------------------------------------------------------------------ tratte e scan

    def _accogli_treni_nuovi(self) -> int:
        """Mette in coda i treni 'in_corso' trovati da tratte/scan e le loro stazioni capolinea."""
        nuovi = 0
        for r in self.conn.execute(
            "SELECT id, cod_origine, origine, cod_destinazione, destinazione, orario_partenza "
            "FROM treni WHERE stato = 'in_corso' AND prossima_verifica IS NULL "
            "AND cod_origine != ''"
        ).fetchall():
            if self.pian.programmato(VERIFICA, str(r["id"])):
                continue
            if r["cod_origine"]:
                self._capolinea(
                    r["cod_origine"], r["origine"], "tratte", origine=True, destinazione=False
                )
            if r["cod_destinazione"]:
                self._capolinea(
                    r["cod_destinazione"],
                    r["destinazione"],
                    "tratte",
                    origine=False,
                    destinazione=True,
                )
            self._rinvia_verifica(
                r["id"], self._quando_prima_verifica(r["orario_partenza"], self.ora())
            )
            nuovi += 1
        self.conn.commit()
        return nuovi

    async def _tratte(self) -> None:
        try:
            await scopri_treni(self.conn, self.client, self.cfg)
        finally:
            ora = self.ora()
            storage.set_stato(self.conn, _K_ULTIMO_TRATTE, str(ora))
            self.conn.commit()
        n = self._accogli_treni_nuovi()
        logger.info("Tratte: %d treni nuovi messi in coda", n)
        self.pian.pianifica(TRATTE, TRATTE, self.ora() + self.cfg.tratte_intervallo_sec * _MS)

    async def _scan(self) -> None:
        try:
            await scan_range_numeri(self.conn, self.client, self.cfg)
        finally:
            storage.set_stato(self.conn, _K_ULTIMO_SCAN, str(self.ora()))
            self.conn.commit()
        n = self._accogli_treni_nuovi()
        logger.info("Scan numeri: %d treni nuovi messi in coda", n)
        self.pian.pianifica(SCAN, SCAN, self.ora() + self.cfg.scan_intervallo_sec * _MS)

    # ------------------------------------------------------------------ servizio

    def statistiche(self) -> str:
        n = self.conn.execute("SELECT COUNT(*) FROM treni WHERE stato = 'in_corso'").fetchone()[0]
        cap = self.conn.execute(
            "SELECT COUNT(*) FROM stops WHERE e_origine = 1 OR e_destinazione = 1"
        ).fetchone()[0]
        tot = self.conn.execute("SELECT COUNT(*) FROM stops").fetchone()[0]
        return (
            f"in coda {self.pian.n_programmati} | eseguiti {dict(self.pian.eseguiti)} | "
            f"errori {dict(self.pian.errori)} | treni in corso {n} | "
            f"stazioni {tot} (capolinea {cap})"
        )

    async def servizio(self) -> None:
        """Log periodico e chiusura dei treni scaduti."""
        ultima_pulizia = 0
        while True:
            await asyncio.sleep(self.cfg.log_stats_sec)
            logger.info(self.statistiche())
            if self.ora() - ultima_pulizia > 3_600_000:
                ultima_pulizia = self.ora()
                chiusi = storage.chiudi_scaduti(
                    self.conn, self.ora(), self.cfg.verifica_scadenza_max_sec * _MS
                )
                if chiusi:
                    logger.info("Chiusi %d treni scaduti", chiusi)


async def run_eventi(config: ConfigEventi) -> None:
    conn = storage.connect(config.db_path)
    if viste.aggiorna_viste(conn):
        logger.info("Viste SQL create o aggiornate (versione %s)", viste.versione())
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop.set())

    limitatore = LimitatoreRichieste(config.richieste_al_secondo)
    http = crea_client_http(
        max_tentativi=config.rete_max_tentativi,
        pausa_blocco_sec=config.rete_pausa_blocco_sec,
        pausa_blocco_max_sec=config.rete_pausa_blocco_max_sec,
        proxy=config.rete_proxy,
        limitatore=limitatore,
    )
    async with ViaggiaTrenoClient(client=http) as client:
        await carica_dimensioni(conn, client, config.regione, ttl_sec=config.dimensioni_ttl_sec)
        motore = Motore(conn, client, config)
        n_staz, n_treni = motore.ricostruisci()
        logger.info(
            "Coda ricostruita: %d stazioni, %d treni | %.2f richieste/s, %d worker",
            n_staz,
            n_treni,
            config.richieste_al_secondo,
            config.workers,
        )
        tasks = [
            asyncio.create_task(motore.pian.esegui()),
            asyncio.create_task(motore.servizio()),
        ]
        await stop.wait()
        logger.info("Segnale di arresto ricevuto, chiusura in corso…")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("%s | richieste HTTP %d", motore.statistiche(), limitatore.n_richieste)

    await http.aclose()
    conn.commit()
    conn.close()
    logger.info("Crawler arrestato, stato salvato.")
