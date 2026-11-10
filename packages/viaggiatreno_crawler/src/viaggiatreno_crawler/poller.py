# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Logica di scoperta/arricchimento/persistenza dei treni in circolazione.

Cicli indipendenti, pensati per girare a frequenze diverse (vedi
CrawlerConfig):

- `scopri_treni`: polling frequente (5-10 min) di elenco_tratte/dettagli_tratta
  per trovare i numeri di treno attualmente in circolazione nella regione.
- `verifica_treni_attivi`: polling meno frequente (15-30 min) di
  andamento_treno sui treni già noti, per registrare fermate/binari e capire
  quando sono arrivati (o soppressi/non più disponibili).
- `scopri_da_tabelloni` / `scan_range_numeri`: cicli di scoperta opzionali.

Riavvio: tutto lo stato "vero" è su SQLite (upsert idempotenti), quindi un
riavvio non perde dati. In più i cicli di scoperta salvano un checkpoint
(tabella `crawler_stato`) del punto raggiunto e `carica_dimensioni` viene
ripetuto solo se i dati anagrafici sono più vecchi di un TTL: così dopo uno
stop si riprende da dove ci si era fermati invece di rifare il lavoro.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sqlite3
import time
from datetime import datetime

from viaggiatreno import REGIONS, ViaggiaTrenoClient

from viaggiatreno_crawler import storage
from viaggiatreno_crawler.config import CrawlerConfig

logger = logging.getLogger(__name__)

# Chiavi usate nella tabella crawler_stato.
_K_DIMENSIONI_TS = "dimensioni_ultimo_caricamento_ms"
_K_CHECKPOINT_TABELLONI = "checkpoint_tabelloni_idx"
_K_CHECKPOINT_SCAN = "checkpoint_scan_idx"
_K_CHECKPOINT_VERIFICA = "checkpoint_verifica_id"


async def carica_dimensioni(
    conn: sqlite3.Connection,
    client: ViaggiaTrenoClient,
    regione: int,
    ttl_sec: int = 86_400,
) -> None:
    """Popola/aggiorna le tabelle di dimensione `regioni`/`stops`.

    I dati anagrafici delle stazioni cambiano raramente: viene eseguito solo
    se l'ultimo caricamento è più vecchio di `ttl_sec` (default 24h). Così un
    riavvio frequente non ripaga ogni volta il costo pieno (fino a 22 chiamate
    a elenco_stazioni). Passare `ttl_sec=0` forza il ricaricamento.

    Nota: `elenco_stazioni(0)` **non** restituisce l'elenco completo delle
    stazioni italiane, ma solo le "stazioni principali" (comportamento
    documentato in VIAGGIATRENO.md, mai completamente verificato dal vivo).
    Se `regione=0` (monitoraggio nazionale in `scopri_treni`), qui iteriamo
    su tutte le regioni 1-22 per avere una dimensione `stops` completa,
    altrimenti molte fermate di `andamento_treno` fuori regione resterebbero
    senza nome/coordinate nei JOIN.
    """
    ora_ms = int(time.time() * 1000)
    ultimo = storage.get_stato(conn, _K_DIMENSIONI_TS)
    if ttl_sec > 0 and ultimo is not None:
        try:
            eta_sec = (ora_ms - int(ultimo)) / 1000
        except ValueError:
            eta_sec = None
        if eta_sec is not None and eta_sec < ttl_sec:
            logger.info(
                "Dimensioni già caricate %.0f min fa (< TTL %.0f min), salto",
                eta_sec / 60,
                ttl_sec / 60,
            )
            return

    for codice, nome in REGIONS.items():
        storage.upsert_regione(conn, codice, nome)

    regioni_da_caricare = range(1, 23) if regione == 0 else [regione]
    totale = 0
    for cod_regione in regioni_da_caricare:
        stazioni = await client.elenco_stazioni(cod_regione)
        for s in stazioni:
            storage.upsert_stop(
                conn,
                stop_id=s.codiceStazione,
                stop_name=s.localita.nomeLungo if s.localita else None,
                stop_lat=s.lat,
                stop_lon=s.lon,
                regione_codice=s.codReg,
                citta=s.nomeCitta,
            )
        totale += len(stazioni)
    storage.set_stato(conn, _K_DIMENSIONI_TS, str(ora_ms))
    conn.commit()
    logger.info("Dimensioni caricate: %d stazioni (regioni %s)", totale, list(regioni_da_caricare))


async def scopri_treni(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> int:
    """Scansiona elenco_tratte/dettagli_tratta e registra i treni trovati come 'in_corso'.

    Oltre ai treni, persiste anche i segmenti (`tratte`), la serie storica di
    occupazione (`tratte_osservazioni`, su TUTTI i segmenti, non solo quelli
    occupati, per poter calcolare correttamente una % nel tempo) e il
    collegamento treno<->segmento (`avvistamenti_tratta`), utile per analisi
    future di dettaglio senza dover richiamare l'API.

    Restituisce il numero di treni (nuovi o già noti) visti in questa scansione.
    """
    segmenti = await client.elenco_tratte(
        categorie=config.categorie, id_regione=config.regione, zoomlevel=config.zoomlevel
    )
    n_visti = 0
    for seg in segmenti:
        storage.upsert_tratta(
            conn,
            regione_codice=config.regione,
            tratta_ab=seg.trattaAB,
            tratta_ba=seg.trattaBA,
            nodo_a=seg.nodoA,
            nodo_b=seg.nodoB,
            lat_a=seg.latitudineA,
            lon_a=seg.longitudineA,
            lat_b=seg.latitudineB,
            lon_b=seg.longitudineB,
            parent_ab=seg.parentAB,
            parent_ba=seg.parentBA,
        )
        storage.registra_osservazione_tratta(
            conn, config.regione, seg.trattaAB, seg.trattaBA, seg.occupata
        )
        if not seg.occupata:
            continue
        gruppi = await client.dettagli_tratta(
            seg.trattaAB, seg.trattaBA, categorie=config.categorie, id_regione=config.regione
        )
        for gruppo in gruppi:
            for treno in gruppo.treni:
                treno_id = storage.upsert_treno(
                    conn,
                    numero_treno=treno.numeroTreno,
                    cod_origine=treno.codOrigine or "",
                    data_partenza_treno=treno.dataPartenzaTreno or 0,
                    categoria=treno.categoria,
                    cod_destinazione=treno.codDestinazione,
                    origine=treno.origine,
                    destinazione=treno.destinazione,
                    codice_cliente=treno.codiceCliente,
                    ritardo_corrente=treno.ritardo,
                    raw_json=treno.model_dump_json(),
                )
                storage.registra_avvistamento_tratta(
                    conn, treno_id, config.regione, seg.trattaAB, seg.trattaBA
                )
                n_visti += 1
    conn.commit()
    logger.info(
        "Scoperta: %d segmenti occupati, %d treni visti",
        sum(1 for s in segmenti if s.occupata),
        n_visti,
    )
    return n_visti


def _registra_board_item(conn: sqlite3.Connection, treno) -> bool:
    """Registra un treno visto su un tabellone, se ha i parametri per andamentoTreno.

    Richiede numero+origine+data: senza questi tre campi non è richiamabile
    con `andamento_treno`, quindi lo si scarta (succede, raramente, su righe
    di tabellone incomplete osservate dal vivo). Restituisce True se è stato
    registrato (nuovo o già noto).
    """
    if treno.codOrigine is None or treno.dataPartenzaTreno is None:
        return False
    storage.upsert_treno(
        conn,
        numero_treno=treno.numeroTreno,
        cod_origine=treno.codOrigine,
        data_partenza_treno=treno.dataPartenzaTreno,
        categoria=treno.categoria,
        cod_destinazione=treno.codDestinazione,
        origine=treno.origine,
        destinazione=treno.destinazione,
        codice_cliente=treno.codiceCliente,
        ritardo_corrente=treno.ritardo,
        raw_json=treno.model_dump_json(),
    )
    return True


async def scopri_da_tabelloni(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> int:
    """Scopre treni interrogando partenze/arrivi delle stazioni note.

    Complementare a `scopri_treni` (che usa elencoTratte/dettagliTratta): i
    tabelloni di stazione restituiscono direttamente numero+codOrigine+
    dataPartenzaTreno, cioè i tre parametri di `andamento_treno`, senza
    bisogno di indovinare nulla. Intercetta treni che la scoperta per
    segmenti non vede (fermi in stazione, o su segmenti/categorie non coperti).

    I treni trovati vengono registrati come 'in_corso': sarà poi
    `verifica_treni_attivi` ad arricchirli con fermate/binari via
    andamentoTreno, riusando la pipeline esistente.

    Restituisce il numero di righe di tabellone registrate (con duplicati tra
    stazioni: lo stesso treno appare in più tabelloni).
    """
    stazioni = storage.stazioni_da_sondare(conn, config.regione, config.tabelloni_max_stazioni)
    # Checkpoint: riprendi dalla stazione dopo l'ultima completata nel giro
    # precedente, così un riavvio non ricomincia sempre dalle stesse (le più
    # trafficate) lasciando indietro la coda della lista. L'indice è relativo
    # alla lista corrente: se la lista cambia dimensione lo riallineo con un
    # modulo, senza pretendere continuità perfetta (best effort).
    start = 0
    ckpt = storage.get_stato(conn, _K_CHECKPOINT_TABELLONI)
    if ckpt is not None:
        try:
            start = int(ckpt) % len(stazioni) if stazioni else 0
        except ValueError:
            start = 0
    ordinate = stazioni[start:] + stazioni[:start]
    n_registrati = 0
    n_fatte = 0
    for stop_id in ordinate:
        for metodo in (client.partenze, client.arrivi):
            try:
                board = await metodo(stop_id)
            except Exception:
                logger.exception("Errore su tabellone %s di %s", metodo.__name__, stop_id)
                continue
            for treno in board:
                if _registra_board_item(conn, treno):
                    n_registrati += 1
        n_fatte += 1
        storage.set_stato(conn, _K_CHECKPOINT_TABELLONI, str((start + n_fatte) % len(stazioni)))
    conn.commit()
    logger.info(
        "Scoperta tabelloni: %d stazioni sondate (da idx %d), %d righe treno registrate",
        len(ordinate),
        start,
        n_registrati,
    )
    return n_registrati


async def scan_range_numeri(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> int:
    """Sonda una finestra di numeri treno attorno a quelli gia' noti.

    Validato dai test dal vivo: la numerazione e' densa *localmente* (50-70%
    dei vicini entro +/-5 di un numero reale esistono davvero), ma sparsa sul
    range globale. Quindi si sonda +/-config.scan_finestra ATTORNO a ciascun
    numero noto, non l'intervallo tra coppie di numeri (che e' quasi tutto
    vuoto).

    `cerca_numero_treno` fa da filtro economico: una sola chiamata dice se il
    numero esiste e, se si', fornisce codLocOrig+millisDataPartenza da passare
    poi ad andamentoTreno (via il ciclo di verifica). Guardrail: tetto di
    chiamate per ciclo (`scan_max_chiamate`).

    Restituisce il numero di treni nuovi registrati.
    """
    noti = set(storage.numeri_treno_noti(conn))
    if not noti:
        logger.info("Scan-range: nessun numero noto, salto (serve prima una scoperta)")
        return 0

    candidati: set[int] = set()
    for n in noti:
        for cand in range(n - config.scan_finestra, n + config.scan_finestra + 1):
            if cand > 0 and cand not in noti:
                candidati.add(cand)

    ordinati = sorted(candidati)
    # Checkpoint: riparti dal candidato dopo l'ultimo sondato nel giro
    # precedente (il tetto scan_max_chiamate taglia la lista, quindi senza
    # checkpoint si rifarebbero sempre solo i primi candidati). L'indice cicla
    # sulla lista corrente.
    start = 0
    ckpt = storage.get_stato(conn, _K_CHECKPOINT_SCAN)
    if ckpt is not None:
        try:
            start = int(ckpt) % len(ordinati) if ordinati else 0
        except ValueError:
            start = 0
    sequenza = ordinati[start:] + ordinati[:start]

    chiamate = 0
    nuovi = 0
    idx = start
    for cand in sequenza:
        if chiamate >= config.scan_max_chiamate:
            logger.info("Scan-range: raggiunto tetto di %d chiamate", config.scan_max_chiamate)
            break
        chiamate += 1
        idx = (idx + 1) % len(ordinati)
        try:
            res = await client.cerca_numero_treno(cand)
        except Exception:
            logger.exception("Scan-range: errore su cerca_numero_treno(%d)", cand)
            continue
        if res is None:
            continue
        try:
            numero = int(res.numeroTreno)
            data_partenza = int(res.millisDataPartenza)
        except (TypeError, ValueError):
            continue
        prima = conn.execute(
            "SELECT 1 FROM treni WHERE numero_treno=? AND cod_origine=? AND data_partenza_treno=?",
            (numero, res.codLocOrig, data_partenza),
        ).fetchone()
        storage.upsert_treno(
            conn,
            numero_treno=numero,
            cod_origine=res.codLocOrig,
            data_partenza_treno=data_partenza,
            origine=res.descLocOrig,
        )
        if prima is None:
            nuovi += 1
    storage.set_stato(conn, _K_CHECKPOINT_SCAN, str(idx))
    conn.commit()
    logger.info(
        "Scan-range: %d candidati, %d chiamate (da idx %d), %d treni nuovi",
        len(candidati),
        chiamate,
        start,
        nuovi,
    )
    return nuovi


def _stato_da_train_status(status) -> str:
    if status.arrivato:
        return "arrivato"
    if status.tipoTreno == "ST":
        return "soppresso"
    return "in_corso"


def _fermate_per_storage(status) -> list[dict]:
    return [
        {
            "stop_id": f.id,
            "progressivo": f.progressivo,
            "tipo_fermata": f.tipoFermata,
            "orario_programmato": f.programmata,
            "orario_effettivo": f.effettiva,
            "ritardo": f.ritardo,
            "binario_programmato": (
                f.binarioProgrammatoPartenzaDescrizione or f.binarioProgrammatoArrivoDescrizione
            ),
            "binario_effettivo": (
                f.binarioEffettivoPartenzaDescrizione or f.binarioEffettivoArrivoDescrizione
            ),
            "actual_fermata_type": f.actualFermataType,
        }
        for f in status.fermate
    ]


def _persisti_status(
    conn: sqlite3.Connection, row: sqlite3.Row, status, config: CrawlerConfig
) -> None:
    """Scrive su DB l'esito di una verifica (chiamata in modo seriale)."""
    if status is None:
        storage.registra_204(conn, row["id"], soglia=config.soglia_204)
        return

    stato = _stato_da_train_status(status)
    ritardo_finale = None
    if stato == "arrivato" and status.fermate:
        ultima = status.fermate[-1]
        ritardo_finale = (
            ultima.ritardoArrivo if ultima.ritardoArrivo is not None else ultima.ritardo
        )

    storage.upsert_treno(
        conn,
        numero_treno=row["numero_treno"],
        cod_origine=row["cod_origine"],
        data_partenza_treno=row["data_partenza_treno"],
        categoria=status.categoria or row["categoria"],
        cod_destinazione=row["cod_destinazione"],
        origine=status.origine or row["origine"],
        destinazione=status.destinazione or row["destinazione"],
        codice_cliente=status.codiceCliente or row["codice_cliente"],
        stato=stato,
        ritardo_corrente=status.ritardo,
        ritardo_finale=ritardo_finale,
        raw_json=json.dumps(status.model_dump(mode="json")),
    )
    treno_id = conn.execute(
        "SELECT id FROM treni WHERE numero_treno=? AND cod_origine=? AND data_partenza_treno=?",
        (row["numero_treno"], row["cod_origine"], row["data_partenza_treno"]),
    ).fetchone()["id"]
    storage.sostituisci_fermate(conn, treno_id, _fermate_per_storage(status))


async def verifica_treni_attivi(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> None:
    """Richiama andamento_treno sui treni 'in_corso' e aggiorna stato/fermate.

    Le chiamate HTTP sono eseguite con concorrenza limitata (Semaphore), così
    con molti treni un giro resta rapido senza martellare l'API; la scrittura
    su SQLite avviene poi in modo seriale (connessione monothread, nessun
    lock necessario).

    Cap per giro (`verifica_max_per_giro`): se gli attivi superano il tetto se
    ne controllano al massimo N a giro, ripresi dall'ultimo id tramite
    checkpoint, ciclando quando si arriva in fondo. Garantisce che un giro non
    sfori mai l'intervallo a prescindere dal volume.

    Backpressure: se il giro dura più di `intervallo_verifica_sec` viene
    loggato un warning (i dati degradano in freschezza ma non si accumula una
    coda illimitata: il giro dopo parte semplicemente in ritardo).
    """
    totale_attivi = storage.conta_treni_attivi(conn)
    cap = config.verifica_max_per_giro
    if cap and cap > 0 and totale_attivi > cap:
        dopo = int(storage.get_stato(conn, _K_CHECKPOINT_VERIFICA) or 0)
        attivi = storage.treni_attivi_da(conn, dopo, cap)
        if not attivi:  # arrivati in fondo: riparti dall'inizio
            attivi = storage.treni_attivi_da(conn, 0, cap)
        logger.info(
            "Verifica: %d treni attivi, controllo %d (cap, da id>%d)",
            totale_attivi,
            len(attivi),
            dopo,
        )
    else:
        attivi = storage.treni_attivi(conn)
        logger.info("Verifica: %d treni attivi da controllare", len(attivi))

    if not attivi:
        return

    t0 = time.monotonic()
    sem = asyncio.Semaphore(max(1, config.verifica_concorrenza))

    async def fetch(row: sqlite3.Row):
        async with sem:
            try:
                status = await client.andamento_treno(
                    row["cod_origine"], row["numero_treno"], row["data_partenza_treno"]
                )
            except Exception:
                logger.exception("Verifica: errore su andamento_treno treno id=%d", row["id"])
                return row, None, True  # errore: non toccare lo stato (né 204 né update)
            return row, status, False

    risultati = await asyncio.gather(*(fetch(r) for r in attivi))

    for row, status, errore in risultati:
        if errore:
            continue
        _persisti_status(conn, row, status, config)

    # Checkpoint: avanza all'ultimo id controllato (max degli id del batch).
    storage.set_stato(conn, _K_CHECKPOINT_VERIFICA, str(max(r["id"] for r in attivi)))
    conn.commit()

    durata = time.monotonic() - t0
    if durata > config.intervallo_verifica_sec:
        logger.warning(
            "Verifica in ritardo: giro durato %.0fs > intervallo %ds "
            "(%d treni attivi). Valuta --verifica-concorrenza più alta, "
            "--verifica-max-per-giro, o intervallo più lungo.",
            durata,
            config.intervallo_verifica_sec,
            totale_attivi,
        )


async def loop_scoperta(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> None:
    while True:
        try:
            await scopri_treni(conn, client, config)
        except Exception:
            logger.exception("Errore nel ciclo di scoperta")
        await asyncio.sleep(config.intervallo_scoperta_sec)


async def loop_verifica(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> None:
    while True:
        try:
            await verifica_treni_attivi(conn, client, config)
        except Exception:
            logger.exception("Errore nel ciclo di verifica")
        await asyncio.sleep(config.intervallo_verifica_sec)


async def loop_tabelloni(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> None:
    while True:
        try:
            await scopri_da_tabelloni(conn, client, config)
        except Exception:
            logger.exception("Errore nel ciclo di scoperta da tabelloni")
        await asyncio.sleep(config.intervallo_tabelloni_sec)


async def loop_scan(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> None:
    while True:
        try:
            await scan_range_numeri(conn, client, config)
        except Exception:
            logger.exception("Errore nel ciclo di scan-range")
        await asyncio.sleep(config.intervallo_scan_sec)


async def run(config: CrawlerConfig) -> None:
    conn = storage.connect(config.db_path)
    stop = asyncio.Event()

    # Chiusura pulita su SIGINT/SIGTERM: segnala ai loop di fermarsi, poi
    # commit finale e chiusura connessione. Con WAL i commit già fatti sono
    # al sicuro; questo evita solo di morire a metà di un ciclo.
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # add_signal_handler non è disponibile su alcune piattaforme (es. Windows).
            signal.signal(sig, lambda *_: stop.set())

    async with ViaggiaTrenoClient() as client:
        await carica_dimensioni(conn, client, config.regione, ttl_sec=config.dimensioni_ttl_sec)

        # Chiude i treni rimasti 'in_corso' da giornate passate (es. crawler
        # fermato a metà giornata e rilanciato il giorno dopo): evita di
        # sprecare chiamate di verifica su treni ormai vecchi.
        mezzanotte_oggi = (
            datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        )
        chiusi = storage.chiudi_treni_obsoleti(conn, int(mezzanotte_oggi.timestamp() * 1000))
        if chiusi:
            logger.info("Avvio: chiusi %d treni 'in_corso' di giornate passate", chiusi)
        cicli = [
            loop_scoperta(conn, client, config),
            loop_verifica(conn, client, config),
        ]
        if config.intervallo_tabelloni_sec > 0:
            cicli.append(loop_tabelloni(conn, client, config))
        if config.intervallo_scan_sec > 0:
            cicli.append(loop_scan(conn, client, config))

        tasks = [asyncio.create_task(c) for c in cicli]
        await stop.wait()
        logger.info("Segnale di arresto ricevuto, chiusura in corso…")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    conn.commit()
    conn.close()
    logger.info("Crawler arrestato, stato salvato.")
