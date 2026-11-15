# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Funzioni di scoperta e persistenza usate dal crawler a eventi (vedi `eventi.py`).

- `carica_dimensioni`: regioni e stazioni da `elencoStazioni` (con TTL).
- `scopri_treni`: `elencoTratte` + `dettagliTratta`; salva segmenti, occupazione per
  segmento, avvistamenti e treni in circolazione.
- `scan_range_numeri`: `cercaNumeroTreno` attorno ai numeri gia' noti.
- `persisti_andamento`: scrive l'esito di un `andamentoTreno` (treno + fermate).

Sono funzioni "di una passata": quando e quanto spesso girano lo decide lo scheduler.
Tutto lo stato vero e' su SQLite (upsert idempotenti), quindi un riavvio non perde nulla.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time

from viaggiatreno import REGIONS, ViaggiaTrenoClient
from viaggiatreno.insights import ProfiloTreno, ha_anomalie

from viaggiatreno_crawler import storage
from viaggiatreno_crawler.config import ConfigEventi

logger = logging.getLogger(__name__)

# Chiavi usate nella tabella crawler_stato.
_K_DIMENSIONI_TS = "dimensioni_ultimo_caricamento_ms"
_K_CHECKPOINT_SCAN = "checkpoint_scan_idx"


def _orario_int(valore) -> int | None:
    """Orario in ms se e' davvero un timestamp; altrimenti None.

    `dettagliTratta` restituisce `orarioPartenza` come stringa "YYYY-MM-DD"
    (solo la data): non e' un orario utilizzabile e si scarta.
    """
    return valore if isinstance(valore, int) and not isinstance(valore, bool) else None


def raw_json_per(status, completo: bool, anomalie: bool | None = None) -> str:
    """`raw_json` da salvare: completo se richiesto o se ci sono anomalie, altrimenti compatto.

    `anomalie` e' `ProfiloTreno.ha_anomalie`; se non e' dato si calcola da `status`.
    """
    dati = status.model_dump(mode="json")
    if anomalie is None:
        anomalie = ha_anomalie(status)
    if completo or anomalie:
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


async def carica_stazioni(
    conn: sqlite3.Connection,
    client: ViaggiaTrenoClient,
    regioni: list[int] | None = None,
) -> dict[int, int | str]:
    """Carica da `elencoStazioni` le stazioni delle regioni indicate (default: 1-22).

    Pensata per un caricamento una tantum (goal `make stazioni`). A differenza di
    `carica_dimensioni`, committa dopo ogni regione e, se una fallisce, prosegue con le
    altre: l'esito per regione e' nel risultato (numero di stazioni, oppure il testo
    dell'errore). Le stazioni gia' note vengono aggiornate; `stops.fonte` accumula la
    provenienza. Le regioni 1-22 coprono tutta Italia: la 0 e' solo "stazioni principali".
    """
    if regioni is None:
        regioni = list(range(1, 23))
    for codice, nome in REGIONS.items():
        storage.upsert_regione(conn, codice, nome)
    conn.commit()

    esito: dict[int, int | str] = {}
    for cod in regioni:
        try:
            stazioni = await client.elenco_stazioni(cod)
        except Exception as exc:  # noqa: BLE001 - una regione che fallisce non ferma le altre
            logger.warning("elencoStazioni/%d fallito: %s", cod, exc)
            esito[cod] = f"errore: {exc}"
            continue
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
        conn.commit()
        esito[cod] = len(stazioni)
        logger.info("Regione %d (%s): %d stazioni", cod, REGIONS.get(cod, "?"), len(stazioni))
    if any(isinstance(v, int) for v in esito.values()):
        storage.set_stato(conn, _K_DIMENSIONI_TS, str(int(time.time() * 1000)))
        conn.commit()
    return esito


async def run_stazioni(
    db_path: str,
    regioni: list[int] | None = None,
    *,
    richieste_al_secondo: float = 1.0,
    proxy: str | None = None,
) -> int:
    """Apre DB e client, carica le stazioni, stampa il riepilogo. Restituisce il n. di errori."""
    from viaggiatreno_crawler.rete import LimitatoreRichieste, crea_client_http

    conn = storage.connect(db_path)
    prima = conn.execute("SELECT COUNT(*) FROM stops").fetchone()[0]
    http = crea_client_http(proxy=proxy, limitatore=LimitatoreRichieste(richieste_al_secondo))
    try:
        async with ViaggiaTrenoClient(client=http) as client:
            esito = await carica_stazioni(conn, client, regioni)
    finally:
        await http.aclose()
    dopo = conn.execute("SELECT COUNT(*) FROM stops").fetchone()[0]
    errori = [c for c, v in esito.items() if isinstance(v, str)]
    print(f"Regioni lette: {len(esito) - len(errori)}/{len(esito)}")
    for c in errori:
        print(f"  regione {c} ({REGIONS.get(c, '?')}): {esito[c]}")
    print(f"Stazioni in stops: {prima} -> {dopo} (+{dopo - prima} nuove)")
    conn.close()
    return len(errori)


async def carica_tratte(
    conn: sqlite3.Connection,
    client: ViaggiaTrenoClient,
    regioni: list[int] | None = None,
    *,
    categorie: str = "ES*,IC,EXP,EC,EN,REG",
    zoomlevel: int = 6,
) -> dict[int, int | str]:
    """Carica da `elencoTratte` i segmenti della rete (tabella `tratte`), senza i treni.

    Pensata per un caricamento una tantum (goal `make tratte`): la rete cambia di rado. Default
    le regioni 0-22: la 0 (Italia, 135 segmenti) e la 1 (Lombardia, 99) sono **grafi diversi**
    (solo 1 coppia di nodi su 99 in comune, misurato), quindi non basta una sola chiamata.
    Non chiama `dettagliTratta` e non scrive `tratte_osservazioni`: l'occupazione di un solo
    istante non e' una serie. Una regione che fallisce non ferma le altre; l'esito per regione
    e' il numero di segmenti oppure il testo dell'errore.
    """
    if regioni is None:
        regioni = list(range(23))
    esito: dict[int, int | str] = {}
    for cod in regioni:
        try:
            segmenti = await client.elenco_tratte(
                categorie=categorie, id_regione=cod, zoomlevel=zoomlevel
            )
        except Exception as exc:  # noqa: BLE001 - una regione che fallisce non ferma le altre
            logger.warning("elencoTratte/%d fallito: %s", cod, exc)
            esito[cod] = f"errore: {exc}"
            continue
        for seg in segmenti:
            storage.upsert_tratta(
                conn,
                regione_codice=cod,
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
        conn.commit()
        esito[cod] = len(segmenti)
        logger.info("Regione %d: %d segmenti", cod, len(segmenti))
    return esito


async def run_tratte(
    db_path: str,
    regioni: list[int] | None = None,
    *,
    richieste_al_secondo: float = 1.0,
    proxy: str | None = None,
) -> int:
    """Apre DB e client, carica i segmenti, stampa il riepilogo. Restituisce il n. di errori."""
    from viaggiatreno_crawler.rete import LimitatoreRichieste, crea_client_http

    conn = storage.connect(db_path)
    prima = conn.execute("SELECT COUNT(*) FROM tratte").fetchone()[0]
    http = crea_client_http(proxy=proxy, limitatore=LimitatoreRichieste(richieste_al_secondo))
    try:
        async with ViaggiaTrenoClient(client=http) as client:
            esito = await carica_tratte(conn, client, regioni)
    finally:
        await http.aclose()
    dopo = conn.execute("SELECT COUNT(*) FROM tratte").fetchone()[0]
    errori = [c for c, v in esito.items() if isinstance(v, str)]
    print(f"Regioni lette: {len(esito) - len(errori)}/{len(esito)}")
    for c in errori:
        print(f"  regione {c}: {esito[c]}")
    print(f"Segmenti in tratte: {prima} -> {dopo} (+{dopo - prima} nuovi)")
    conn.close()
    return len(errori)


async def scopri_treni(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: ConfigEventi
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


async def scan_range_numeri(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: ConfigEventi
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
            "arrivo_teorico": f.arrivo_teorico,
            "partenza_teorica": f.partenza_teorica,
        }
        for f in status.fermate
    ]


def persisti_andamento(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    status,
    profilo: ProfiloTreno | None = None,
    raw_json_completo: bool = False,
) -> tuple[int, str]:
    """Scrive l'esito di un andamentoTreno (treno + fermate). Restituisce (id, stato).

    Lo stato e le anomalie vengono dal `ProfiloTreno` (che si costruisce qui se non e' dato).
    """
    if profilo is None:
        profilo = ProfiloTreno.da_status(status)
    stato = profilo.avanzamento.value
    ritardo_finale = None
    if stato == "arrivato" and status.fermate:
        ultima = status.fermate[-1]
        ritardo_finale = (
            ultima.ritardoArrivo if ultima.ritardoArrivo is not None else ultima.ritardo
        )

    # La destinazione viene dall'andamento (e' l'ultima fermata non soppressa, quindi tiene conto
    # delle soppressioni); il valore gia' in tabella (da un tabellone) resta solo come ripiego.
    effettivo = profilo.collegamento_effettivo
    treno_id = storage.upsert_treno(
        conn,
        numero_treno=row["numero_treno"],
        cod_origine=row["cod_origine"],
        data_partenza_treno=row["data_partenza_treno"],
        categoria=status.categoria or row["categoria"],
        cod_destinazione=(effettivo.destinazione_codice if effettivo else None)
        or row["cod_destinazione"],
        origine=status.origine or row["origine"],
        destinazione=status.destinazione or row["destinazione"],
        codice_cliente=status.codiceCliente or row["codice_cliente"],
        stato=stato,
        ritardo_corrente=status.ritardo,
        ritardo_finale=ritardo_finale,
        raw_json=raw_json_per(status, raw_json_completo, profilo.ha_anomalie),
        orario_partenza=_orario_int(status.orarioPartenza),
    )
    storage.sostituisci_fermate(conn, treno_id, _fermate_per_storage(status))
    return treno_id, stato
