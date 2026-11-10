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
from viaggiatreno_crawler.rete import crea_client_http

logger = logging.getLogger(__name__)

# Chiavi usate nella tabella crawler_stato.
_K_DIMENSIONI_TS = "dimensioni_ultimo_caricamento_ms"
_K_CHECKPOINT_TABELLONI_RARE = "checkpoint_tabelloni_rare_idx"
_K_CHECKPOINT_SCAN = "checkpoint_scan_idx"
_K_CHECKPOINT_VERIFICA = "checkpoint_verifica_id"
# Ora (ms) dell'ultimo giro *concluso* di ogni ciclo: dopo un riavvio si aspetta
# solo il tempo che manca all'intervallo, invece di ripartire subito.
_K_ULTIMO_GIRO = "ultimo_giro_"  # + nome del ciclo


def _orario_int(valore) -> int | None:
    """Orario in ms se e' davvero un timestamp; altrimenti None.

    `dettagliTratta` restituisce `orarioPartenza` come stringa "YYYY-MM-DD"
    (solo la data): non e' un orario utilizzabile e si scarta.
    """
    return valore if isinstance(valore, int) and not isinstance(valore, bool) else None


def _ha_anomalie(status) -> bool:
    """True se la risposta di andamentoTreno segnala qualcosa oltre la marcia regolare.

    Cancellazioni totali o parziali, deviazioni, riprogrammazioni, variazioni di
    origine/destinazione, cambi di numero, note sulla circolazione, fermate non
    effettuate: e' quello che serve conservare per intero per capire a posteriori.
    """
    if (status.tipoTreno or "PG") != "PG":
        return True
    if (status.provvedimento or 0) != 0:
        return True
    if (status.riprogrammazione or "N") == "Y":
        return True
    if status.subTitle:
        return True
    if status.fermateSoppresse:
        return True
    if status.cambiNumero or status.anormalita or status.provvedimenti:
        return True
    return any(f.actualFermataType in (2, 3) for f in status.fermate)


def _raw_json_status(status, config: CrawlerConfig) -> str:
    """JSON da salvare in `treni.raw_json` per una risposta di andamentoTreno.

    Completo (con le `fermate`) se ci sono anomalie o se `raw_json_completo`;
    altrimenti compatto, senza `fermate`: sono gia' righe in `fermate`, e valgono
    circa l'83% del peso del JSON. Il riepilogo non perde nulla di quel che e'
    gia' nelle colonne, e le anomalie restano documentate per intero.
    """
    dati = status.model_dump(mode="json")
    if config.raw_json_completo or _ha_anomalie(status):
        return json.dumps(dati)
    dati.pop("fermate", None)
    return json.dumps(dati, separators=(",", ":"))


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
    n_errori = 0
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
        try:
            gruppi = await client.dettagli_tratta(
                seg.trattaAB, seg.trattaBA, categorie=config.categorie, id_regione=config.regione
            )
        except Exception:
            # Un errore su un segmento non deve interrompere il giro: si salta
            # e si prosegue (il retry/backoff e' gia' nel trasporto HTTP).
            logger.exception(
                "Scoperta: errore su dettagli_tratta %d/%d, segmento saltato",
                seg.trattaAB,
                seg.trattaBA,
            )
            n_errori += 1
            continue
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
                    orario_partenza=_orario_int(treno.orarioPartenza),
                )
                storage.registra_avvistamento_tratta(
                    conn, treno_id, config.regione, seg.trattaAB, seg.trattaBA
                )
                n_visti += 1
    conn.commit()
    logger.info(
        "Scoperta: %d segmenti occupati, %d treni visti, %d segmenti in errore",
        sum(1 for s in segmenti if s.occupata),
        n_visti,
        n_errori,
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
        orario_partenza=_orario_int(treno.orarioPartenza),
    )
    return True


async def scopri_da_tabelloni(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> int:
    """Scopre treni interrogando i tabelloni delle stazioni note.

    Due fasce di stazioni: le `tabelloni_max_stazioni` principali (da cui
    nascono più treni) ad ogni giro, tutte le altre a rotazione, a gruppi di
    `tabelloni_rare_per_giro` per giro, così l'intero elenco viene coperto
    prima o poi senza moltiplicare le chiamate.

    Di default solo le partenze (`config.tabelloni_arrivi=False`): ogni treno
    compare nella partenza della sua stazione di origine, e nelle stazioni di
    transito i due tabelloni elencano gli stessi treni. Gli arrivi si attivano
    solo se serve intercettare treni che nascono fuori dalle stazioni sondate.

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
    tutte = storage.stazioni_per_origine(conn, config.regione)
    principali = tutte[: config.tabelloni_max_stazioni]
    secondarie = tutte[config.tabelloni_max_stazioni :]

    # Secondarie: finestra a rotazione di `tabelloni_rare_per_giro` stazioni,
    # ripresa dal checkpoint (sopravvive ai riavvii). L'indice e' relativo alla
    # lista corrente: se cambia dimensione lo riallineo con un modulo (best effort).
    start = 0
    del_giro: list[str] = []
    if secondarie and config.tabelloni_rare_per_giro > 0:
        ckpt = storage.get_stato(conn, _K_CHECKPOINT_TABELLONI_RARE)
        try:
            start = int(ckpt) % len(secondarie) if ckpt is not None else 0
        except ValueError:
            start = 0
        n = min(config.tabelloni_rare_per_giro, len(secondarie))
        del_giro = [secondarie[(start + i) % len(secondarie)] for i in range(n)]

    metodi = (client.partenze, client.arrivi) if config.tabelloni_arrivi else (client.partenze,)

    # Stazioni il cui tabellone e' stato richiesto da poco (es. giro precedente
    # interrotto da un riavvio): non si richiamano prima del minimo.
    ora_ms = int(time.time() * 1000)
    recenti: set[str] = set()
    if config.tabellone_min_intervallo_sec > 0:
        recenti = storage.tabelloni_recenti(
            conn, ora_ms - config.tabellone_min_intervallo_sec * 1000
        )
    n_saltate = 0

    async def sonda(stop_id: str) -> int:
        nonlocal n_saltate
        if stop_id in recenti:
            n_saltate += 1
            return 0
        registrati = 0
        riuscito = True
        for metodo in metodi:
            try:
                board = await metodo(stop_id)
            except Exception:
                logger.exception("Errore su tabellone %s di %s", metodo.__name__, stop_id)
                riuscito = False
                continue
            for treno in board:
                if _registra_board_item(conn, treno):
                    registrati += 1
        if riuscito:  # un errore non conta come richiesta fatta: si riprova al giro dopo
            storage.segna_tabellone(conn, stop_id, ora_ms)
        return registrati

    n_registrati = 0
    for stop_id in principali:
        n_registrati += await sonda(stop_id)
    for i, stop_id in enumerate(del_giro, start=1):
        n_registrati += await sonda(stop_id)
        storage.set_stato(conn, _K_CHECKPOINT_TABELLONI_RARE, str((start + i) % len(secondarie)))
    conn.commit()

    giri_rotazione = -(-len(secondarie) // len(del_giro)) if del_giro else 0
    logger.info(
        "Scoperta tabelloni: %d principali + %d secondarie (da idx %d di %d; "
        "rotazione completa in %s giri), %d già richieste da poco e saltate, "
        "%d righe treno registrate",
        len(principali),
        len(del_giro),
        start,
        len(secondarie),
        giri_rotazione or "-",
        n_saltate,
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
        esito = storage.registra_204(conn, row["id"], soglia=config.soglia_204)
        if esito == "chiuso":
            logger.info(
                "Verifica: treno %s (id=%d) chiuso dopo %d risposte vuote",
                row["numero_treno"],
                row["id"],
                config.soglia_204,
            )
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
        raw_json=_raw_json_status(status, config),
        orario_partenza=_orario_int(status.orarioPartenza),
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
    # Non si verifica un treno molto prima che parta: la chiamata e' quasi sempre
    # inutile (e un 204 e' normale). Negativo = nessun filtro, come prima.
    ora_ms = int(time.time() * 1000)
    fino_a = (
        None if config.verifica_anticipo_sec < 0 else ora_ms + config.verifica_anticipo_sec * 1000
    )
    # Ne' uno gia' controllato da poco: dopo un riavvio, o se piu' cicli lo
    # toccano, non si rifa' subito la stessa chiamata. 0 = nessun minimo.
    da_prima_di = (
        ora_ms - config.verifica_min_intervallo_sec * 1000
        if config.verifica_min_intervallo_sec > 0
        else None
    )
    in_corso = storage.conta_treni_attivi(conn)
    totale_attivi = storage.conta_treni_attivi(conn, fino_a, da_prima_di)
    cap = config.verifica_max_per_giro
    if cap and cap > 0 and totale_attivi > cap:
        dopo = int(storage.get_stato(conn, _K_CHECKPOINT_VERIFICA) or 0)
        attivi = storage.treni_attivi_da(conn, dopo, cap, fino_a, da_prima_di)
        if not attivi:  # arrivati in fondo: riparti dall'inizio
            attivi = storage.treni_attivi_da(conn, 0, cap, fino_a, da_prima_di)
        logger.info(
            "Verifica: %d treni da controllare su %d in_corso, controllo %d (cap, da id>%d)",
            totale_attivi,
            in_corso,
            len(attivi),
            dopo,
        )
    else:
        attivi = storage.treni_attivi(conn, fino_a, da_prima_di)
        logger.info(
            "Verifica: %d treni da controllare su %d in_corso (%d non ancora in partenza)",
            len(attivi),
            in_corso,
            in_corso - len(attivi),
        )

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
        # Annotata dopo la chiamata riuscita (anche se la risposta e' 204): un
        # errore di rete non conta come controllo fatto, al giro dopo si riprova.
        storage.segna_verifica(conn, row["id"], ora_ms)

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


def secondi_all_prossimo_giro(
    ultimo_giro_ms: str | None, intervallo_sec: float, ora_ms: int | None = None
) -> float:
    """Quanto aspettare prima del prossimo giro di un ciclo, dato l'ultimo concluso.

    0 se non c'e' un ultimo giro noto (primo avvio), se il valore non e' leggibile
    o se l'intervallo e' gia' trascorso. Un orologio che va all'indietro (ultimo
    giro "nel futuro") non deve bloccare il ciclo oltre un intervallo.
    """
    if ultimo_giro_ms is None:
        return 0.0
    try:
        ultimo = int(ultimo_giro_ms)
    except ValueError:
        return 0.0
    ora = ora_ms if ora_ms is not None else int(time.time() * 1000)
    trascorso = (ora - ultimo) / 1000
    if trascorso < 0:
        return 0.0
    return max(0.0, min(intervallo_sec, intervallo_sec - trascorso))


async def _ciclo(
    nome: str,
    conn: sqlite3.Connection,
    lavoro,
    intervallo_sec: int,
) -> None:
    """Esegue `lavoro` ogni `intervallo_sec`, ricordando l'ultimo giro su DB.

    Al riavvio il primo giro attende il tempo residuo dall'ultimo concluso (se
    meno di un intervallo e' passato) invece di partire subito: un stop-and-go
    del crawler non ripete subito chiamate appena fatte. Il giro viene
    registrato solo se *concluso*: un errore (eccezione) non lo segna come fatto,
    cosi' al giro successivo si riprova.
    """
    chiave = _K_ULTIMO_GIRO + nome
    attesa = secondi_all_prossimo_giro(storage.get_stato(conn, chiave), intervallo_sec)
    if attesa > 0:
        logger.info(
            "Ciclo %s: ultimo giro %.0fs fa, riparto tra %.0fs",
            nome,
            intervallo_sec - attesa,
            attesa,
        )
        await asyncio.sleep(attesa)
    while True:
        try:
            await lavoro()
        except Exception:
            logger.exception("Errore nel ciclo %s", nome)
        else:
            storage.set_stato(conn, chiave, str(int(time.time() * 1000)))
            conn.commit()
        await asyncio.sleep(intervallo_sec)


async def loop_scoperta(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> None:
    await _ciclo(
        "scoperta", conn, lambda: scopri_treni(conn, client, config), config.intervallo_scoperta_sec
    )


async def loop_verifica(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> None:
    await _ciclo(
        "verifica",
        conn,
        lambda: verifica_treni_attivi(conn, client, config),
        config.intervallo_verifica_sec,
    )


async def loop_tabelloni(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> None:
    await _ciclo(
        "tabelloni",
        conn,
        lambda: scopri_da_tabelloni(conn, client, config),
        config.intervallo_tabelloni_sec,
    )


async def loop_scan(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> None:
    await _ciclo(
        "scan", conn, lambda: scan_range_numeri(conn, client, config), config.intervallo_scan_sec
    )


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

    http = crea_client_http(
        max_tentativi=config.rete_max_tentativi,
        pausa_blocco_sec=config.rete_pausa_blocco_sec,
        pausa_blocco_max_sec=config.rete_pausa_blocco_max_sec,
        proxy=config.rete_proxy,
    )
    async with ViaggiaTrenoClient(client=http) as client:
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

    await http.aclose()  # ViaggiaTrenoClient non chiude un client httpx passato da fuori
    conn.commit()
    conn.close()
    logger.info("Crawler arrestato, stato salvato.")
