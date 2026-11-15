# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dal database del crawler ai `ProfiloTreno` della libreria.

La libreria costruisce i profili da una risposta di `andamentoTreno`; qui si ricostruisce una
risposta equivalente dalle tabelle `treni` e `fermate` e si passa dalla stessa `da_status`, cosi'
itinerario, stato e archi si calcolano con le stesse regole di sempre (nessuna logica duplicata).

Base della risposta: `treni.raw_json`. Anche quello "compatto" (senza fermate) conserva
`tipoTreno`, `idOrigine`, `idDestinazione`, `impresaFerroviaria`..., quindi stato e collegamenti
sono quelli veri. Le fermate vengono dalla tabella `fermate`. Senza `raw_json` utilizzabile (corse
scoperte solo da un tabellone, che non ha `tipoTreno`) si ricostruisce il minimo dai campi di `treni`.

Cosa la tabella `fermate` non conserva e quindi **non** si ricostruisce:

- gli orari reali di arrivo e di partenza (c'e' solo `orario_effettivo`, ambiguo): niente ritardi;
- il binario di arrivo distinto da quello di partenza: ne e' salvato uno solo per tipo
  (programmato, effettivo), la partenza se c'e', altrimenti l'arrivo. Il binario perso e' quello di
  arrivo quando differisce da quello di partenza: su 557 corse confrontate, 12 (2%) perdono un
  binario. Le viste SQL hanno lo stesso limite.

Gli orari teorici (`arrivo_teorico`, `partenza_teorica`) ci sono solo per le corse registrate dal
crawler dopo l'aggiunta delle colonne. Per le altre si usa l'unico orario noto (`orario_programmato`:
la partenza alla prima fermata, l'arrivo alle altre): le durate sono esatte solo per i tratti che
partono dalla prima fermata, altrove restano `None`. Nessun valore viene inventato.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from itertools import groupby

from viaggiatreno import TrainStatus
from viaggiatreno.insights import ProfiloTreno, data_di_servizio


def apri_copia(db_path: str) -> sqlite3.Connection:
    """Una copia **in memoria** del database, letta con l'API di backup di SQLite.

    E' consistente anche se il crawler sta scrivendo (WAL) e non modifica i dati. Il file e' aperto
    con `mode=ro`: se non esiste, solleva `FileNotFoundError` senza crearlo.

    Limite: il DB del crawler e' in modalita' WAL, e per leggerlo SQLite crea il file `-shm` accanto.
    Una cartella non scrivibile (es. un volume montato in sola lettura) da' `OperationalError`;
    `immutable=1` la aggirerebbe ma ignora il WAL e leggerebbe dati vecchi, quindi non si usa. In
    quel caso copiare prima il DB con `sqlite3 db ".backup copia.db"`.
    """
    import os

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DB non trovato: {db_path}")
    sorgente = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        copia = sqlite3.connect(":memory:")
        sorgente.backup(copia)
    finally:
        sorgente.close()
    copia.row_factory = sqlite3.Row
    return copia


def _fermata(f: sqlite3.Row, prima: bool) -> dict:
    binario_prog = f["binario_programmato"]
    binario_eff = f["binario_effettivo"]
    arrivo, partenza = f["arrivo_teorico"], f["partenza_teorica"]
    if arrivo is None and partenza is None and f["orario_programmato"] is not None:
        # corsa senza orari teorici: l'unico orario noto e' la partenza (prima) o l'arrivo
        if prima:
            partenza = f["orario_programmato"]
        else:
            arrivo = f["orario_programmato"]
    # lato del binario: la prima fermata ha solo la partenza, le altre l'arrivo
    lato = "Partenza" if prima else "Arrivo"
    d = {
        "stazione": f["stop_name"] or f["stop_id"],
        "id": f["stop_id"],
        "tipoFermata": f["tipo_fermata"] or "F",
        "progressivo": f["progressivo"],
        "programmata": f["orario_programmato"],
        "arrivo_teorico": arrivo,
        "partenza_teorica": partenza,
        "actualFermataType": f["actual_fermata_type"],
        f"binarioProgrammato{lato}Descrizione": binario_prog,
        f"binarioEffettivo{lato}Descrizione": binario_eff,
    }
    return d


def _base_da_raw_json(t: sqlite3.Row) -> dict | None:
    """La risposta salvata in `raw_json`, se e' di un `andamentoTreno` (ha `tipoTreno`)."""
    if not t["raw_json"]:
        return None
    try:
        dati = json.loads(t["raw_json"])
    except ValueError:
        return None
    if not isinstance(dati, dict) or "tipoTreno" not in dati:
        return None
    return dati


def _status(t: sqlite3.Row, fermate: list[sqlite3.Row]) -> TrainStatus:
    elenco = [_fermata(f, i == 0) for i, f in enumerate(fermate)]
    base = _base_da_raw_json(t)
    if base is not None:
        base["fermate"] = elenco
        # l'itinerario e' quello salvato nelle fermate: i campi che lo descrivono sono da `treni`
        return TrainStatus.model_validate(base)
    soppresso = t["stato"] == "soppresso"
    return TrainStatus.model_validate(
        {
            "numeroTreno": t["numero_treno"],
            "tipoTreno": "ST" if soppresso else "PG",
            "provvedimento": 1 if soppresso else 0,
            "categoria": t["categoria"],
            "origine": t["origine"],
            "destinazione": t["destinazione"],
            "idOrigine": t["cod_origine"] or None,
            "idDestinazione": t["cod_destinazione"],
            "dataPartenzaTreno": t["data_partenza_treno"],
            "dataPartenzaTrenoAsDate": data_di_servizio(t["data_partenza_treno"]).isoformat(),
            "codiceCliente": t["codice_cliente"],
            "arrivato": t["stato"] == "arrivato",
            "ritardo": t["ritardo_corrente"],
            "fermate": elenco,
        }
    )


def coordinate_stazioni(conn: sqlite3.Connection) -> dict[str, tuple[float, float]]:
    """codice -> (lat, lon) per le stazioni che hanno le coordinate."""
    return {
        r["stop_id"]: (r["stop_lat"], r["stop_lon"])
        for r in conn.execute(
            "SELECT stop_id, stop_lat, stop_lon FROM stops "
            "WHERE stop_lat IS NOT NULL AND stop_lon IS NOT NULL"
        )
    }


def iter_profili(
    conn: sqlite3.Connection,
    *,
    coordinate: dict[str, tuple[float, float]] | None = None,
) -> Iterator[tuple[int, ProfiloTreno]]:
    """`(treno_id, profilo)` per ogni corsa con almeno una fermata salvata, in ordine di id.

    Le corse senza fermate (mai verificate) non hanno un itinerario e si saltano. Una corsa
    `non_disponibile` che ha le fermate (letta prima della partenza, poi il sito non ha piu'
    risposto) ha un itinerario valido e si tiene: sul DB reale sono 307 su 19.847. L'ordine delle fermate e' quello dell'inserimento (`fermate.id`), mai `progressivo`.
    """
    treni = {r["id"]: r for r in conn.execute("SELECT * FROM treni")}
    # un DB scritto dal crawler precedente non ha le colonne degli orari teorici: si leggono NULL
    colonne = {r[1] for r in conn.execute("PRAGMA table_info(fermate)")}
    teorici = ", ".join(
        f"f.{c}" if c in colonne else f"NULL AS {c}" for c in ("arrivo_teorico", "partenza_teorica")
    )
    righe = conn.execute(
        f"SELECT f.id, f.treno_id, f.stop_id, f.progressivo, f.tipo_fermata, "
        f"f.orario_programmato, f.actual_fermata_type, f.binario_programmato, "
        f"f.binario_effettivo, {teorici}, s.stop_name "
        "FROM fermate f LEFT JOIN stops s ON s.stop_id = f.stop_id "
        "ORDER BY f.treno_id, f.id"
    )
    for treno_id, gruppo in groupby(righe, key=lambda r: r["treno_id"]):
        t = treni.get(treno_id)
        if t is None:
            continue
        yield treno_id, ProfiloTreno.da_status(_status(t, list(gruppo)), coordinate=coordinate)


def carica_profili(
    conn: sqlite3.Connection,
    *,
    coordinate: dict[str, tuple[float, float]] | None = None,
) -> list[ProfiloTreno]:
    return [p for _, p in iter_profili(conn, coordinate=coordinate)]
