"""Logica di scoperta/arricchimento/persistenza dei treni in circolazione.

Due cicli indipendenti, pensati per girare a frequenze diverse (vedi
CrawlerConfig):

- `scopri_treni`: polling frequente (5-10 min) di elenco_tratte/dettagli_tratta
  per trovare i numeri di treno attualmente in circolazione nella regione.
- `verifica_treni_attivi`: polling meno frequente (15-30 min) di
  andamento_treno sui treni già noti, per registrare fermate/binari e capire
  quando sono arrivati (o soppressi/non più disponibili).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3

from viaggiatreno import REGIONS, ViaggiaTrenoClient

from viaggiatreno_crawler import storage
from viaggiatreno_crawler.config import CrawlerConfig

logger = logging.getLogger(__name__)


async def carica_dimensioni(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, regione: int
) -> None:
    """Popola/aggiorna le tabelle di dimensione `regioni`/`stazioni`.

    Da chiamare una volta all'avvio (e periodicamente, es. una volta al
    giorno): i dati anagrafici delle stazioni cambiano raramente.

    Nota: `elenco_stazioni(0)` **non** restituisce l'elenco completo delle
    stazioni italiane, ma solo le "stazioni principali" (comportamento
    documentato in VIAGGIATRENO.md, mai completamente verificato dal vivo).
    Se `regione=0` (monitoraggio nazionale in `scopri_treni`), qui iteriamo
    su tutte le regioni 1-22 per avere una dimensione `stazioni` completa,
    altrimenti molte fermate di `andamento_treno` fuori regione resterebbero
    senza nome/coordinate nei JOIN.
    """
    for codice, nome in REGIONS.items():
        storage.upsert_regione(conn, codice, nome)

    regioni_da_caricare = range(1, 23) if regione == 0 else [regione]
    totale = 0
    for cod_regione in regioni_da_caricare:
        stazioni = await client.elenco_stazioni(cod_regione)
        for s in stazioni:
            storage.upsert_stazione(
                conn,
                codice=s.codiceStazione,
                nome=s.localita.nomeLungo if s.localita else None,
                lat=s.lat,
                lon=s.lon,
                regione_codice=s.codReg,
                citta=s.nomeCitta,
            )
        totale += len(stazioni)
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
    logger.info("Scoperta: %d segmenti occupati, %d treni visti", sum(1 for s in segmenti if s.occupata), n_visti)
    return n_visti


def _stato_da_train_status(status) -> str:  # noqa: ANN001 - TrainStatus, evitare import ciclico in type hints
    if status.arrivato:
        return "arrivato"
    if status.tipoTreno == "ST":
        return "soppresso"
    return "in_corso"


def _fermate_per_storage(status) -> list[dict]:  # noqa: ANN001
    return [
        {
            "stazione_codice": f.id,
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


async def verifica_treni_attivi(
    conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig
) -> None:
    """Richiama andamento_treno per ogni treno 'in_corso' e aggiorna stato/fermate."""
    attivi = storage.treni_attivi(conn)
    logger.info("Verifica: %d treni attivi da controllare", len(attivi))
    for row in attivi:
        status = await client.andamento_treno(
            row["cod_origine"], row["numero_treno"], row["data_partenza_treno"]
        )
        if status is None:
            storage.registra_204(conn, row["id"], soglia=config.soglia_204)
            continue

        stato = _stato_da_train_status(status)
        ritardo_finale = None
        if stato == "arrivato" and status.fermate:
            ultima = status.fermate[-1]
            ritardo_finale = ultima.ritardoArrivo if ultima.ritardoArrivo is not None else ultima.ritardo

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
    conn.commit()


async def loop_scoperta(conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig) -> None:
    while True:
        try:
            await scopri_treni(conn, client, config)
        except Exception:
            logger.exception("Errore nel ciclo di scoperta")
        await asyncio.sleep(config.intervallo_scoperta_sec)


async def loop_verifica(conn: sqlite3.Connection, client: ViaggiaTrenoClient, config: CrawlerConfig) -> None:
    while True:
        try:
            await verifica_treni_attivi(conn, client, config)
        except Exception:
            logger.exception("Errore nel ciclo di verifica")
        await asyncio.sleep(config.intervallo_verifica_sec)


async def run(config: CrawlerConfig) -> None:
    conn = storage.connect(config.db_path)
    async with ViaggiaTrenoClient() as client:
        await carica_dimensioni(conn, client, config.regione)
        await asyncio.gather(
            loop_scoperta(conn, client, config),
            loop_verifica(conn, client, config),
        )
