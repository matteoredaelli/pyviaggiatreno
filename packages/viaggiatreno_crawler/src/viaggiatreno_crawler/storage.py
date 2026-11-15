# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistenza SQLite per il crawler: schema, upsert e query di aggregazione.

Schema a stella: `regioni`/`stops` sono dimensioni (poco variabili nel
tempo), `treni`/`fermate` sono fatti che crescono ogni giorno. `fermate` è la
tabella chiave per i KPI a livello di stazione/binario (quali stazioni hanno
più traffico, quali binari usa più spesso una stazione): non è ottenibile da
`elencoTratte`/`dettagliTratta` (solo origine/destinazione), serve il
dettaglio completo di `andamentoTreno`.

Compatibilità con il GTFS Trenord (vedi TRENORD.md): la tabella `stops` usa
la stessa chiave e gli stessi nomi di colonna di `stops.txt` (`stop_id`,
`stop_name`, `stop_lat`, `stop_lon`, `stop_url`), perché i codici stazione
ViaggiaTreno (`S01700`) sono identici agli `stop_id` del GTFS Trenord: puoi
importare `stops.txt` direttamente in questa tabella con `importa_stops_gtfs`
e fare join tra dati real-time e pianificazione statica senza conversioni.

`treni`/`fermate` **non** sono invece traducibili 1:1 in `trips.txt`/
`stop_times.txt`: quelle tabelle GTFS descrivono l'orario pianificato teorico
(valido per una stagione), mentre `treni`/`fermate` sono osservazioni
real-time di istanze specifiche (un treno, un giorno, un ritardo misurato).
Sono entità concettualmente diverse; GTFS non ha un concetto di "ritardo
osservato". Un collegamento (`route_id`/`trip_id`) è possibile come fase
futura di correlazione, non come semplice rinomina di colonne.
"""

from __future__ import annotations

import csv
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from viaggiatreno.insights import data_di_servizio, tipo_giorno

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS regioni (
    codice INTEGER PRIMARY KEY,
    nome TEXT NOT NULL
);

-- Dimensione stazioni, compatibile con stops.txt del GTFS Trenord (stessa
-- chiave stop_id = codice stazione ViaggiaTreno). Campi extra non-GTFS
-- (regione_codice, citta, fonte) aggiunti in coda, non interferiscono con
-- un import diretto del CSV GTFS.
CREATE TABLE IF NOT EXISTS stops (
    stop_id TEXT PRIMARY KEY,
    stop_name TEXT,
    stop_lat REAL,
    stop_lon REAL,
    stop_url TEXT,
    regione_codice INTEGER REFERENCES regioni(codice),
    citta TEXT,
    -- Da dove arriva la stazione (le provenienze si accumulano con '+'):
    -- 'viaggiatreno' = elencoStazioni; 'gtfs_trenord' = stops.txt; 'tabellone' = origine o
    -- destinazione di una riga di partenze/arrivi; 'itinerario' = fermata di andamentoTreno;
    -- 'tratte' = origine/destinazione di un treno trovato per segmento.
    fonte TEXT NOT NULL DEFAULT 'viaggiatreno',
    ultimo_aggiornamento INTEGER,
    -- Ultima volta (ms) che il tabellone delle partenze di questa stazione e' stato
    -- richiesto con successo: evita di richiamarlo troppo presto (es. dopo un riavvio).
    ultimo_tabellone INTEGER,
    -- Crawler a eventi: quando va sondata la stazione (ms; NULL = non programmata) e
    -- se risulta capolinea: origine di almeno un treno / destinazione di almeno uno.
    prossima_sonda INTEGER,
    e_origine INTEGER NOT NULL DEFAULT 0,
    e_destinazione INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS treni (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_treno INTEGER NOT NULL,
    cod_origine TEXT NOT NULL,
    data_partenza_treno INTEGER NOT NULL,
    categoria TEXT,
    cod_destinazione TEXT,
    origine TEXT,
    destinazione TEXT,
    codice_cliente INTEGER,
    stato TEXT NOT NULL DEFAULT 'in_corso',
    ritardo_corrente INTEGER,
    ritardo_finale INTEGER,
    tentativi_204 INTEGER NOT NULL DEFAULT 0,
    primo_avvistamento INTEGER NOT NULL,
    ultimo_aggiornamento INTEGER NOT NULL,
    raw_json TEXT,
    route_id TEXT,  -- riservato per futura correlazione con GTFS trips.txt
    trip_id TEXT,   -- riservato per futura correlazione con GTFS trips.txt
    -- Orario di partenza programmato dall'origine (ms). Serve a non verificare
    -- con andamentoTreno un treno molto prima che parta. NULL se non noto.
    orario_partenza INTEGER,
    -- Perche' un treno e' stato chiuso come 'non_disponibile': '204' (soglia di
    -- risposte vuote raggiunta) o 'giornata_passata' (chiuso in blocco all'avvio).
    -- NULL per arrivato/soppresso/in_corso e per le righe precedenti alla colonna.
    chiusura_motivo TEXT,
    -- Ultima volta (ms) che andamentoTreno e' stato chiamato per questo treno (con
    -- esito qualsiasi, anche 204). Non e' `ultimo_aggiornamento`, che cambia anche
    -- quando il treno viene solo rivisto da una scoperta.
    ultima_verifica INTEGER,
    -- Crawler a eventi: quando va richiamato andamentoTreno (ms; NULL = non programmato)
    -- e arrivo previsto a capolinea (ultima fermata programmata + ritardo), in ms.
    prossima_verifica INTEGER,
    arrivo_previsto INTEGER,
    -- 'feriale' | 'sabato' | 'festivo' del giorno di servizio (da data_partenza_treno)
    tipo_giorno TEXT,
    -- Modalita' "orario": fino a quando (ms) questo record vale per i giorni dello stesso tipo.
    -- NULL per le corse scoperte in modalita' "statistiche".
    scade_orario INTEGER,
    UNIQUE (numero_treno, cod_origine, data_partenza_treno)
);

CREATE INDEX IF NOT EXISTS idx_treni_stato ON treni(stato);

CREATE TABLE IF NOT EXISTS fermate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    treno_id INTEGER NOT NULL REFERENCES treni(id) ON DELETE CASCADE,
    stop_id TEXT NOT NULL REFERENCES stops(stop_id),
    progressivo INTEGER,
    tipo_fermata TEXT,
    orario_programmato INTEGER,
    orario_effettivo INTEGER,
    ritardo INTEGER,
    binario_programmato TEXT,
    binario_effettivo TEXT,
    actual_fermata_type INTEGER,
    -- Orari programmati (ms) di arrivo e di partenza: `orario_programmato` e' uno solo (la
    -- partenza alla prima fermata, l'arrivo alle altre), quindi senza queste due colonne la
    -- partenza da una fermata intermedia e la durata di un tratto non si ricavano.
    -- NULL alla prima (arrivo) e all'ultima (partenza) e per le righe precedenti alle colonne.
    arrivo_teorico INTEGER,
    partenza_teorica INTEGER
);

CREATE INDEX IF NOT EXISTS idx_fermate_stop ON fermate(stop_id);
CREATE INDEX IF NOT EXISTS idx_fermate_treno ON fermate(treno_id);

-- Segmenti della rete (elencoTratte). Chiave composita perché trattaAB/trattaBA
-- sono numerati per regione, non sono ID globali (vedi VIAGGIATRENO.md:
-- lo stesso trattaAB/trattaBA puo' indicare segmenti fisicamente diversi a
-- seconda della regione usata nella chiamata).
CREATE TABLE IF NOT EXISTS tratte (
    regione_codice INTEGER NOT NULL,
    tratta_ab INTEGER NOT NULL,
    tratta_ba INTEGER NOT NULL,
    nodo_a TEXT,
    nodo_b TEXT,
    lat_a REAL,
    lon_a REAL,
    lat_b REAL,
    lon_b REAL,
    parent_ab INTEGER,
    parent_ba INTEGER,
    ultimo_aggiornamento INTEGER,
    PRIMARY KEY (regione_codice, tratta_ab, tratta_ba)
);

-- Serie storica di occupazione: un record per ogni poll di elencoTratte,
-- per poter analizzare in futuro la congestione nel tempo (non solo lo
-- stato attuale, che e' tutto cio' che l'API offre nativamente).
CREATE TABLE IF NOT EXISTS tratte_osservazioni (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    regione_codice INTEGER NOT NULL,
    tratta_ab INTEGER NOT NULL,
    tratta_ba INTEGER NOT NULL,
    ts_poll INTEGER NOT NULL,
    occupata INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tratte_oss_segmento
    ON tratte_osservazioni(regione_codice, tratta_ab, tratta_ba);

-- Collegamento treno <-> segmento su cui e' stato avvistato (da dettagliTratta),
-- per poter ricostruire in futuro "questo treno e' passato di qui alle X"
-- senza dover rifare query su andamentoTreno.
CREATE TABLE IF NOT EXISTS avvistamenti_tratta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    treno_id INTEGER NOT NULL REFERENCES treni(id) ON DELETE CASCADE,
    regione_codice INTEGER NOT NULL,
    tratta_ab INTEGER NOT NULL,
    tratta_ba INTEGER NOT NULL,
    ts_poll INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_avvistamenti_tratta_treno ON avvistamenti_tratta(treno_id);

-- Stato del crawler (chiave/valore): timestamp ultimo caricamento dimensioni
-- e checkpoint di avanzamento dei cicli di scoperta, per riprendere dopo un
-- riavvio da dove ci si era fermati invece di ricominciare da capo.
CREATE TABLE IF NOT EXISTS crawler_stato (
    chiave TEXT PRIMARY KEY,
    valore TEXT
);

-- Registro delle richieste di tabellone (partenze/arrivi di una stazione): una
-- riga per richiesta, anche se fallita. Serve a misurare quanto "in avanti" e
-- "indietro" arriva la finestra di un tabellone (orario_min/orario_max rispetto
-- a ts_richiesta) e quanti treni contiene, per decidere quando richiamarlo.
-- Non influenza cosa chiede il crawler. Cresce poco (una riga per richiesta).
-- Errori dei lavori del crawler (tabelloni e lavori falliti), per `viaggiatreno-crawler errori`.
-- Non contiene i blocchi HTTP 403/429 della rete (solo nel log).
CREATE TABLE IF NOT EXISTS errori (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,         -- ms
    fonte TEXT NOT NULL,         -- 'tabellone partenze', 'tabellone arrivi', o il tipo di lavoro
    chiave TEXT,                 -- stazione o id treno
    messaggio TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_errori_ts ON errori(ts);

CREATE TABLE IF NOT EXISTS tabelloni_richieste (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_richiesta INTEGER NOT NULL,
    stop_id TEXT NOT NULL,
    tipo TEXT NOT NULL,          -- 'partenze' | 'arrivi'
    esito TEXT NOT NULL,         -- 'ok' | 'errore'
    n_righe INTEGER,             -- treni nel tabellone; NULL se errore
    orario_min INTEGER,          -- primo orario (ms) tra le righe, partenza o arrivo secondo `tipo`
    orario_max INTEGER,          -- ultimo orario (ms)
    n_senza_orario INTEGER       -- righe senza un orario utilizzabile
);

CREATE INDEX IF NOT EXISTS idx_tab_richieste_stop ON tabelloni_richieste(stop_id, ts_richiesta);
"""


def _verifica_schema_compatibile(conn: sqlite3.Connection) -> None:
    """Rileva un DB creato con uno schema incompatibile e dà un errore chiaro.

    Lo SCHEMA usa `CREATE TABLE/INDEX IF NOT EXISTS`, che non migra tabelle
    già esistenti con colonne diverse: su un DB vecchio `executescript`
    fallirebbe con un criptico "no such column". Qui controlliamo prima le
    colonne delle tabelle chiave e, se incompatibili, solleviamo un errore
    esplicito con l'indicazione di cosa fare.
    """
    attese = {
        "fermate": "stop_id",  # vecchio schema: stazione_codice
    }
    for tabella, colonna in attese.items():
        esiste = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabella,)
        ).fetchone()
        if esiste is None:
            continue  # tabella non ancora creata: DB nuovo, nessun conflitto
        colonne = {r[1] for r in conn.execute(f"PRAGMA table_info({tabella})").fetchall()}
        if colonna not in colonne:
            raise RuntimeError(
                f"Il database ha uno schema incompatibile: la tabella '{tabella}' "
                f"non ha la colonna '{colonna}' (creato con una versione precedente "
                f"del crawler). Rinomina o elimina il file e verrà ricreato, "
                f"oppure migralo manualmente."
            )


# Colonne aggiunte dopo la prima versione dello schema: `CREATE TABLE IF NOT
# EXISTS` non le aggiunge a una tabella già esistente, quindi le si aggiunge qui.
_COLONNE_AGGIUNTE = {
    "treni": [
        ("orario_partenza", "INTEGER"),
        ("chiusura_motivo", "TEXT"),
        ("ultima_verifica", "INTEGER"),
        ("prossima_verifica", "INTEGER"),
        ("arrivo_previsto", "INTEGER"),
        ("tipo_giorno", "TEXT"),
        ("scade_orario", "INTEGER"),
    ],
    "fermate": [
        ("arrivo_teorico", "INTEGER"),
        ("partenza_teorica", "INTEGER"),
    ],
    "stops": [
        ("ultimo_tabellone", "INTEGER"),
        ("prossima_sonda", "INTEGER"),
        ("e_origine", "INTEGER NOT NULL DEFAULT 0"),
        ("e_destinazione", "INTEGER NOT NULL DEFAULT 0"),
    ],
}


def _migra_colonne(conn: sqlite3.Connection) -> None:
    """Aggiunge ai DB esistenti le colonne introdotte dopo (idempotente)."""
    for tabella, colonne in _COLONNE_AGGIUNTE.items():
        esiste = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabella,)
        ).fetchone()
        if esiste is None:
            continue
        presenti = {r[1] for r in conn.execute(f"PRAGMA table_info({tabella})").fetchall()}
        for nome, tipo in colonne:
            if nome not in presenti:
                conn.execute(f"ALTER TABLE {tabella} ADD COLUMN {nome} {tipo}")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Apre (creando se necessario) il database e applica lo schema."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _verifica_schema_compatibile(conn)
    _migra_colonne(conn)
    conn.executescript(SCHEMA)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_treni_orario "
        "ON treni(numero_treno, cod_origine, tipo_giorno, scade_orario)"
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Stato del crawler (chiave/valore): checkpoint e timestamp
# ---------------------------------------------------------------------------


def get_stato(conn: sqlite3.Connection, chiave: str) -> str | None:
    """Legge un valore di stato del crawler, None se mai impostato."""
    row = conn.execute("SELECT valore FROM crawler_stato WHERE chiave = ?", (chiave,)).fetchone()
    return None if row is None else row["valore"]


def set_stato(conn: sqlite3.Connection, chiave: str, valore: str) -> None:
    """Scrive (upsert) un valore di stato del crawler."""
    conn.execute(
        "INSERT INTO crawler_stato (chiave, valore) VALUES (?, ?) "
        "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore",
        (chiave, valore),
    )


# ---------------------------------------------------------------------------
# Dimensioni
# ---------------------------------------------------------------------------


def upsert_regione(conn: sqlite3.Connection, codice: int, nome: str) -> None:
    conn.execute(
        "INSERT INTO regioni (codice, nome) VALUES (?, ?) "
        "ON CONFLICT(codice) DO UPDATE SET nome = excluded.nome",
        (codice, nome),
    )


def upsert_stop(
    conn: sqlite3.Connection,
    stop_id: str,
    stop_name: str | None,
    stop_lat: float | None,
    stop_lon: float | None,
    regione_codice: int | None = None,
    citta: str | None = None,
    stop_url: str | None = None,
    fonte: str = "viaggiatreno",
) -> None:
    """Inserisce/aggiorna una stazione nella tabella `stops` (compatibile GTFS stops.txt)."""
    conn.execute(
        """
        INSERT INTO stops (stop_id, stop_name, stop_lat, stop_lon, stop_url, regione_codice, citta, fonte, ultimo_aggiornamento)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stop_id) DO UPDATE SET
            stop_name = excluded.stop_name,
            stop_lat = excluded.stop_lat,
            stop_lon = excluded.stop_lon,
            stop_url = COALESCE(excluded.stop_url, stops.stop_url),
            regione_codice = COALESCE(excluded.regione_codice, stops.regione_codice),
            citta = COALESCE(excluded.citta, stops.citta),
            -- `fonte` accumula le provenienze (es. 'tabellone+viaggiatreno'), senza duplicati
            fonte = CASE WHEN instr('+' || stops.fonte || '+', '+' || excluded.fonte || '+') > 0
                         THEN stops.fonte ELSE stops.fonte || '+' || excluded.fonte END,
            ultimo_aggiornamento = excluded.ultimo_aggiornamento
        """,
        (
            stop_id,
            stop_name,
            stop_lat,
            stop_lon,
            stop_url,
            regione_codice,
            citta,
            fonte,
            int(time.time() * 1000),
        ),
    )


def importa_stops_gtfs(conn: sqlite3.Connection, csv_path: str | Path) -> int:
    """Importa un file `stops.txt` del GTFS Trenord direttamente nella tabella `stops`.

    Poiché gli `stop_id` del GTFS Trenord coincidono con i codici stazione
    ViaggiaTreno (vedi TRENORD.md), le righe si fondono (upsert) con quelle
    già presenti: una stazione già vista da ViaggiaTreno viene aggiornata
    con i campi del GTFS (es. `stop_url`, che ViaggiaTreno non fornisce),
    mantenendo `fonte='gtfs_trenord'` per distinguerne la provenienza.
    Restituisce il numero di righe importate.
    """
    n = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            upsert_stop(
                conn,
                stop_id=row["stop_id"],
                stop_name=row.get("stop_name"),
                stop_lat=float(row["stop_lat"]) if row.get("stop_lat") else None,
                stop_lon=float(row["stop_lon"]) if row.get("stop_lon") else None,
                stop_url=row.get("stop_url"),
                fonte="gtfs_trenord",
            )
            n += 1
    conn.commit()
    return n


# ---------------------------------------------------------------------------
# Fatti: treni e fermate
# ---------------------------------------------------------------------------


def upsert_tratta(
    conn: sqlite3.Connection,
    *,
    regione_codice: int,
    tratta_ab: int,
    tratta_ba: int,
    nodo_a: str | None,
    nodo_b: str | None,
    lat_a: float | None,
    lon_a: float | None,
    lat_b: float | None,
    lon_b: float | None,
    parent_ab: int | None,
    parent_ba: int | None,
) -> None:
    """Inserisce/aggiorna un segmento della rete (dimensione `tratte`)."""
    conn.execute(
        """
        INSERT INTO tratte (
            regione_codice, tratta_ab, tratta_ba, nodo_a, nodo_b,
            lat_a, lon_a, lat_b, lon_b, parent_ab, parent_ba, ultimo_aggiornamento
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(regione_codice, tratta_ab, tratta_ba) DO UPDATE SET
            nodo_a = excluded.nodo_a,
            nodo_b = excluded.nodo_b,
            lat_a = excluded.lat_a,
            lon_a = excluded.lon_a,
            lat_b = excluded.lat_b,
            lon_b = excluded.lon_b,
            parent_ab = excluded.parent_ab,
            parent_ba = excluded.parent_ba,
            ultimo_aggiornamento = excluded.ultimo_aggiornamento
        """,
        (
            regione_codice,
            tratta_ab,
            tratta_ba,
            nodo_a,
            nodo_b,
            lat_a,
            lon_a,
            lat_b,
            lon_b,
            parent_ab,
            parent_ba,
            int(time.time() * 1000),
        ),
    )


def registra_osservazione_tratta(
    conn: sqlite3.Connection, regione_codice: int, tratta_ab: int, tratta_ba: int, occupata: bool
) -> None:
    """Appende un record alla serie storica di occupazione di un segmento."""
    conn.execute(
        "INSERT INTO tratte_osservazioni (regione_codice, tratta_ab, tratta_ba, ts_poll, occupata) "
        "VALUES (?, ?, ?, ?, ?)",
        (regione_codice, tratta_ab, tratta_ba, int(time.time() * 1000), int(occupata)),
    )


def registra_avvistamento_tratta(
    conn: sqlite3.Connection, treno_id: int, regione_codice: int, tratta_ab: int, tratta_ba: int
) -> None:
    """Collega un treno al segmento su cui e' stato trovato (da dettagliTratta)."""
    conn.execute(
        "INSERT INTO avvistamenti_tratta (treno_id, regione_codice, tratta_ab, tratta_ba, ts_poll) "
        "VALUES (?, ?, ?, ?, ?)",
        (treno_id, regione_codice, tratta_ab, tratta_ba, int(time.time() * 1000)),
    )


def upsert_treno(
    conn: sqlite3.Connection,
    *,
    numero_treno: int,
    cod_origine: str,
    data_partenza_treno: int,
    categoria: str | None = None,
    cod_destinazione: str | None = None,
    origine: str | None = None,
    destinazione: str | None = None,
    codice_cliente: int | None = None,
    stato: str = "in_corso",
    ritardo_corrente: int | None = None,
    ritardo_finale: int | None = None,
    raw_json: str | None = None,
    orario_partenza: int | None = None,
) -> int:
    """Inserisce o aggiorna un treno (chiave: numero_treno+cod_origine+data_partenza_treno).

    Restituisce l'id interno (rowid) del treno.
    """
    now = int(time.time() * 1000)
    conn.execute(
        """
        INSERT INTO treni (
            numero_treno, cod_origine, data_partenza_treno, categoria,
            cod_destinazione, origine, destinazione, codice_cliente,
            stato, ritardo_corrente, ritardo_finale,
            primo_avvistamento, ultimo_aggiornamento, raw_json, orario_partenza, tipo_giorno
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(numero_treno, cod_origine, data_partenza_treno) DO UPDATE SET
            categoria = excluded.categoria,
            -- come l'orario: il codice noto non si perde se una riscoperta non lo porta
            -- (i tabelloni delle partenze danno solo il nome della destinazione)
            cod_destinazione = COALESCE(excluded.cod_destinazione, treni.cod_destinazione),
            origine = excluded.origine,
            destinazione = excluded.destinazione,
            codice_cliente = excluded.codice_cliente,
            -- Un treno già chiuso (arrivato/soppresso) non va riaperto da una
            -- riscoperta (tabelloni, scan, segmenti): queste non conoscono lo
            -- stato e scrivono 'in_corso' con ritardo_finale NULL, cancellando
            -- l'esito registrato dalla verifica. Solo la verifica può
            -- cambiare uno stato chiuso (e non lo fa: verifica solo 'in_corso').
            stato = CASE WHEN treni.stato IN ('arrivato', 'soppresso')
                          AND excluded.stato = 'in_corso'
                         THEN treni.stato ELSE excluded.stato END,
            ritardo_corrente = CASE WHEN treni.stato IN ('arrivato', 'soppresso')
                          AND excluded.stato = 'in_corso'
                         THEN treni.ritardo_corrente ELSE excluded.ritardo_corrente END,
            ritardo_finale = CASE WHEN treni.stato IN ('arrivato', 'soppresso')
                          AND excluded.stato = 'in_corso'
                         THEN treni.ritardo_finale ELSE excluded.ritardo_finale END,
            raw_json = CASE WHEN treni.stato IN ('arrivato', 'soppresso')
                          AND excluded.stato = 'in_corso'
                         THEN treni.raw_json ELSE excluded.raw_json END,
            -- l'orario noto non si perde se una riscoperta non lo porta
            orario_partenza = COALESCE(excluded.orario_partenza, treni.orario_partenza),
            tentativi_204 = 0,
            ultimo_aggiornamento = excluded.ultimo_aggiornamento
        """,
        (
            numero_treno,
            cod_origine,
            data_partenza_treno,
            categoria,
            cod_destinazione,
            origine,
            destinazione,
            codice_cliente,
            stato,
            ritardo_corrente,
            ritardo_finale,
            now,
            now,
            raw_json,
            orario_partenza,
            tipo_giorno_di(data_partenza_treno),
        ),
    )
    row = conn.execute(
        "SELECT id FROM treni WHERE numero_treno = ? AND cod_origine = ? AND data_partenza_treno = ?",
        (numero_treno, cod_origine, data_partenza_treno),
    ).fetchone()
    return int(row["id"])


def registra_204(
    conn: sqlite3.Connection, treno_id: int, soglia: int = 5, ora_ms: int | None = None
) -> str:
    """Registra una risposta vuota (204) di `andamentoTreno` e dice cosa e' successo.

    Un 204 *prima* dell'orario di partenza programmato e' normale (il treno non
    e' ancora nel sistema): non si conta e non puo' chiudere il treno. Dopo la
    partenza ogni 204 si somma e, alla `soglia`, il treno diventa
    `non_disponibile` con `chiusura_motivo='204'`.

    Restituisce `'atteso'` (prima della partenza, ignorato), `'contato'` o
    `'chiuso'`.
    """
    ora = ora_ms if ora_ms is not None else int(time.time() * 1000)
    riga = conn.execute(
        "SELECT orario_partenza, tentativi_204 FROM treni WHERE id = ?", (treno_id,)
    ).fetchone()
    if riga is None:
        return "contato"
    if riga["orario_partenza"] is not None and ora < riga["orario_partenza"]:
        return "atteso"
    tentativi = int(riga["tentativi_204"]) + 1
    if tentativi >= soglia:
        conn.execute(
            "UPDATE treni SET tentativi_204 = ?, stato = 'non_disponibile', "
            "chiusura_motivo = '204', ultimo_aggiornamento = ? WHERE id = ?",
            (tentativi, ora, treno_id),
        )
        return "chiuso"
    conn.execute(
        "UPDATE treni SET tentativi_204 = ?, ultimo_aggiornamento = ? WHERE id = ?",
        (tentativi, ora, treno_id),
    )
    return "contato"


def sostituisci_fermate(
    conn: sqlite3.Connection, treno_id: int, fermate: Iterable[dict[str, Any]]
) -> None:
    """Rimpiazza tutte le fermate note di un treno con quelle fornite (da andamentoTreno)."""
    conn.execute("DELETE FROM fermate WHERE treno_id = ?", (treno_id,))
    conn.executemany(
        """
        INSERT INTO fermate (
            treno_id, stop_id, progressivo, tipo_fermata,
            orario_programmato, orario_effettivo, ritardo,
            binario_programmato, binario_effettivo, actual_fermata_type,
            arrivo_teorico, partenza_teorica
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                treno_id,
                f["stop_id"],
                f.get("progressivo"),
                f.get("tipo_fermata"),
                f.get("orario_programmato"),
                f.get("orario_effettivo"),
                f.get("ritardo"),
                f.get("binario_programmato"),
                f.get("binario_effettivo"),
                f.get("actual_fermata_type"),
                f.get("arrivo_teorico"),
                f.get("partenza_teorica"),
            )
            for f in fermate
        ],
    )


def ripara_arrivi_persi(conn: sqlite3.Connection) -> int:
    """Recupera i treni arrivati ma non registrati come tali (una tantum).

    Prima della correzione di `upsert_treno`, una riscoperta poteva riaprire un
    treno `arrivato` (stato `in_corso`, `ritardo_finale` NULL). Le `fermate`
    restavano però intatte: se l'ultima fermata (`tipo_fermata='A'`) risulta
    effettuata (`actual_fermata_type=1`, con orario effettivo) il treno e'
    arrivato, e il suo ritardo all'arrivo e' `fermate.ritardo` di quella riga.

    Tocca solo `in_corso` e `non_disponibile`: non riapre i `soppresso`.
    Restituisce il numero di treni corretti.
    """
    cur = conn.execute(
        """
        UPDATE treni SET
            stato = 'arrivato',
            chiusura_motivo = NULL,
            ritardo_finale = (
                SELECT f.ritardo FROM fermate f
                WHERE f.treno_id = treni.id AND f.tipo_fermata = 'A'
                  AND f.actual_fermata_type = 1 AND f.orario_effettivo IS NOT NULL
                ORDER BY f.id DESC LIMIT 1
            )
        WHERE stato IN ('in_corso', 'non_disponibile')
          AND EXISTS (
            SELECT 1 FROM fermate f
            WHERE f.treno_id = treni.id AND f.tipo_fermata = 'A'
              AND f.actual_fermata_type = 1 AND f.orario_effettivo IS NOT NULL
          )
        """
    )
    conn.commit()
    return cur.rowcount


def segna_verifica(conn: sqlite3.Connection, treno_id: int, ora_ms: int | None = None) -> None:
    """Registra che `andamentoTreno` e' stato chiamato ora per questo treno."""
    conn.execute(
        "UPDATE treni SET ultima_verifica = ? WHERE id = ?",
        (ora_ms if ora_ms is not None else int(time.time() * 1000), treno_id),
    )


def segna_tabellone(conn: sqlite3.Connection, stop_id: str, ora_ms: int | None = None) -> None:
    """Registra che il tabellone di questa stazione e' stato richiesto con successo ora."""
    conn.execute(
        "UPDATE stops SET ultimo_tabellone = ? WHERE stop_id = ?",
        (ora_ms if ora_ms is not None else int(time.time() * 1000), stop_id),
    )


def numeri_treno_noti(conn: sqlite3.Connection) -> list[int]:
    """Numeri treno distinti già osservati, per guidare lo scan-range.

    Lo scan sonda una finestra attorno a questi numeri (non tra coppie):
    i dati dal vivo mostrano che la numerazione è densa *localmente*
    (grappoli), non uniformemente distribuita nel range globale.
    """
    rows = conn.execute("SELECT DISTINCT numero_treno FROM treni ORDER BY numero_treno").fetchall()
    return [int(r["numero_treno"]) for r in rows]


# ---------------------------------------------------------------------------
# Query di aggregazione (KPI)
# ---------------------------------------------------------------------------


def kpi_giornata(conn: sqlite3.Connection, data_partenza_treno: int) -> sqlite3.Row:
    """N treni, ritardo medio, % in ritardo, % soppressi.

    SQLite non ha una funzione MEDIAN nativa: per la mediana usare
    `ritardi_arrivati()` e `statistics.median()` in Python (il volume di
    dati di questo progetto è comunque piccolo, nessun bisogno di calcolarla
    in SQL).
    """
    return conn.execute(
        """
        SELECT
            COUNT(*) AS n_treni,
            SUM(CASE WHEN stato = 'arrivato' THEN 1 ELSE 0 END) AS n_arrivati,
            SUM(CASE WHEN stato = 'soppresso' THEN 1 ELSE 0 END) AS n_soppressi,
            AVG(CASE WHEN stato = 'arrivato' THEN ritardo_finale END) AS ritardo_medio,
            SUM(CASE WHEN stato = 'arrivato' AND ritardo_finale > 5 THEN 1 ELSE 0 END) * 1.0
                / NULLIF(SUM(CASE WHEN stato = 'arrivato' THEN 1 ELSE 0 END), 0) AS pct_in_ritardo
        FROM treni
        WHERE data_partenza_treno = ?
        """,
        (data_partenza_treno,),
    ).fetchone()


def ritardi_arrivati(conn: sqlite3.Connection, data_partenza_treno: int) -> list[int]:
    """Lista dei ritardi finali dei treni arrivati in una giornata, per calcolare la mediana in Python."""
    rows = conn.execute(
        "SELECT ritardo_finale FROM treni WHERE data_partenza_treno = ? AND stato = 'arrivato' "
        "AND ritardo_finale IS NOT NULL",
        (data_partenza_treno,),
    ).fetchall()
    return [int(r["ritardo_finale"]) for r in rows]


def binari_per_stazione(conn: sqlite3.Connection, stop_id: str) -> list[sqlite3.Row]:
    """Binari effettivi osservati per una stazione, ordinati per frequenza."""
    return conn.execute(
        """
        SELECT binario_effettivo, COUNT(*) AS n
        FROM fermate
        WHERE stop_id = ? AND binario_effettivo IS NOT NULL
        GROUP BY binario_effettivo
        ORDER BY n DESC
        """,
        (stop_id,),
    ).fetchall()


def stazioni_per_traffico(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    """Stazioni con più treni distinti transitati (per traffico osservato)."""
    return conn.execute(
        """
        SELECT f.stop_id, s.stop_name, COUNT(DISTINCT f.treno_id) AS n_treni
        FROM fermate f
        LEFT JOIN stops s ON s.stop_id = f.stop_id
        GROUP BY f.stop_id
        ORDER BY n_treni DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def segmenti_piu_congestionati(
    conn: sqlite3.Connection, regione_codice: int, limit: int = 20
) -> list[sqlite3.Row]:
    """Segmenti con la % di osservazioni "occupata" più alta nella serie storica.

    Richiede che `registra_osservazione_tratta` sia stata chiamata ad ogni
    poll (non solo sui segmenti occupati): la % è sul totale dei poll, non
    sulle sole osservazioni positive.
    """
    return conn.execute(
        """
        SELECT
            o.tratta_ab, o.tratta_ba, t.nodo_a, t.nodo_b,
            COUNT(*) AS n_osservazioni,
            SUM(o.occupata) AS n_occupata,
            SUM(o.occupata) * 1.0 / COUNT(*) AS pct_occupata
        FROM tratte_osservazioni o
        LEFT JOIN tratte t
            ON t.regione_codice = o.regione_codice
           AND t.tratta_ab = o.tratta_ab AND t.tratta_ba = o.tratta_ba
        WHERE o.regione_codice = ?
        GROUP BY o.tratta_ab, o.tratta_ba
        ORDER BY pct_occupata DESC
        LIMIT ?
        """,
        (regione_codice, limit),
    ).fetchall()


# ---------------------------------------------------------------------------
# Manutenzione
# ---------------------------------------------------------------------------


def pulisci_avvistamenti_tratta(
    conn: sqlite3.Connection, giorni_da_tenere: int = 7, ora_ms: int | None = None
) -> int:
    """Cancella gli avvistamenti treno<->segmento piu' vecchi di `giorni_da_tenere`.

    `avvistamenti_tratta` e' la tabella che cresce piu' in fretta (un record per
    treno per segmento per scansione) ed e' usata solo per analisi sulla singola
    tratta; `treni`, `fermate` e `tratte_osservazioni` non ne dipendono. Va tenuto
    uno storico recente, non tutto. Restituisce il numero di righe cancellate.
    """
    ora = ora_ms if ora_ms is not None else int(time.time() * 1000)
    limite = ora - giorni_da_tenere * 86_400_000
    cur = conn.execute("DELETE FROM avvistamenti_tratta WHERE ts_poll < ?", (limite,))
    conn.commit()
    return cur.rowcount


def compatta_raw_json(conn: sqlite3.Connection) -> tuple[int, int]:
    """Riduce i `raw_json` pesanti dei treni regolari gia' chiusi (una tantum).

    Toglie `fermate` dal JSON dei treni `arrivato` senza anomalie: sono gia' righe
    di `fermate`. Le anomalie (tipo diverso da PG, provvedimenti, riprogrammazione,
    note, cambi di numero, fermate non effettuate) restano per intero.
    Restituisce (righe_compattate, byte_risparmiati). Il file SQLite non si
    rimpicciolisce da solo: serve un `VACUUM` (richiede spazio libero pari al DB),
    che non lancio qui.
    """
    anomalo = """(
        coalesce(json_extract(raw_json,'$.tipoTreno'),'PG') <> 'PG'
        OR coalesce(json_extract(raw_json,'$.provvedimento'),0) <> 0
        OR coalesce(json_extract(raw_json,'$.riprogrammazione'),'N') = 'Y'
        OR coalesce(json_extract(raw_json,'$.subTitle'),'') <> ''
        OR json_array_length(coalesce(json_extract(raw_json,'$.fermateSoppresse'),'[]')) > 0
        OR json_array_length(coalesce(json_extract(raw_json,'$.cambiNumero'),'[]')) > 0
        OR json_array_length(coalesce(json_extract(raw_json,'$.anormalita'),'[]')) > 0
        OR json_array_length(coalesce(json_extract(raw_json,'$.provvedimenti'),'[]')) > 0
        OR EXISTS (SELECT 1 FROM fermate f WHERE f.treno_id = treni.id
                   AND f.actual_fermata_type IN (2, 3))
    )"""
    da_compattare = (
        "stato = 'arrivato' AND json_valid(raw_json) "
        f"AND json_type(raw_json, '$.fermate') = 'array' AND NOT {anomalo}"
    )
    n, byte_prima = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(length(raw_json)), 0) FROM treni WHERE {da_compattare}"
    ).fetchone()
    conn.execute(
        f"UPDATE treni SET raw_json = json_remove(raw_json, '$.fermate') WHERE {da_compattare}"
    )
    conn.commit()
    return int(n), int(byte_prima)  # byte_prima: peso complessivo prima, indicativo del risparmio


def ricava_orario_partenza(conn: sqlite3.Connection) -> int:
    """Valorizza `treni.orario_partenza` dai dati gia' presenti (una tantum).

    Per i treni verificati prende la fermata di origine (`tipo_fermata='P'`);
    per gli altri l'`orarioPartenza` del tabellone in `raw_json`, se e' un
    timestamp. Non tocca le righe che hanno gia' un valore.
    """
    prima = conn.execute("SELECT COUNT(*) FROM treni WHERE orario_partenza IS NOT NULL").fetchone()[
        0
    ]
    conn.execute(
        """UPDATE treni SET orario_partenza = (
               SELECT f.orario_programmato FROM fermate f
               WHERE f.treno_id = treni.id AND f.tipo_fermata = 'P'
                 AND f.orario_programmato IS NOT NULL
               ORDER BY f.id LIMIT 1)
           WHERE orario_partenza IS NULL"""
    )
    conn.execute(
        """UPDATE treni SET orario_partenza = json_extract(raw_json, '$.orarioPartenza')
           WHERE orario_partenza IS NULL AND json_valid(raw_json)
             AND json_type(raw_json, '$.orarioPartenza') = 'integer'"""
    )
    conn.commit()
    # `rowcount` di un UPDATE conta le righe esaminate, non quelle cambiate (un
    # SET che produce NULL su una riga NULL conta lo stesso): si confronta il
    # numero di righe valorizzate prima e dopo.
    dopo = conn.execute("SELECT COUNT(*) FROM treni WHERE orario_partenza IS NOT NULL").fetchone()[
        0
    ]
    return int(dopo - prima)


def registra_errore(
    conn: sqlite3.Connection, ts_ms: int, fonte: str, chiave: str | None, exc: BaseException
) -> None:
    """Salva un errore (senza commit: lo fa chi scrive). Il messaggio e' tipo + testo, max 500."""
    messaggio = f"{type(exc).__name__}: {exc}"[:500]
    conn.execute(
        "INSERT INTO errori (ts, fonte, chiave, messaggio) VALUES (?, ?, ?, ?)",
        (ts_ms, fonte, chiave, messaggio),
    )


def ultimi_errori(conn: sqlite3.Connection, n: int) -> list[sqlite3.Row]:
    """Gli ultimi `n` errori, dal piu' recente."""
    return conn.execute(
        "SELECT ts, fonte, chiave, messaggio FROM errori ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()


def registra_richiesta_tabellone(
    conn: sqlite3.Connection,
    *,
    stop_id: str,
    tipo: str,
    esito: str,
    ts_ms: int,
    n_righe: int | None = None,
    orario_min: int | None = None,
    orario_max: int | None = None,
    n_senza_orario: int | None = None,
) -> None:
    """Aggiunge una riga al registro delle richieste di tabellone (vedi lo schema)."""
    conn.execute(
        "INSERT INTO tabelloni_richieste (ts_richiesta, stop_id, tipo, esito, n_righe, "
        "orario_min, orario_max, n_senza_orario) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ts_ms, stop_id, tipo, esito, n_righe, orario_min, orario_max, n_senza_orario),
    )


# ---------------------------------------------------------------------------
# Crawler a eventi: scadenze persistenti e capolinea
# ---------------------------------------------------------------------------


def registra_stop_se_nuovo(
    conn: sqlite3.Connection, stop_id: str, nome: str | None, fonte: str
) -> bool:
    """Inserisce una stazione se manca (solo codice e nome). True se e' nuova.

    Una stazione gia' presente non viene toccata, salvo il nome se era vuoto.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO stops (stop_id, stop_name, fonte, ultimo_aggiornamento) "
        "VALUES (?, ?, ?, ?)",
        (stop_id, nome, fonte, int(time.time() * 1000)),
    )
    if cur.rowcount == 0 and nome:
        conn.execute(
            "UPDATE stops SET stop_name = ? WHERE stop_id = ? AND stop_name IS NULL",
            (nome, stop_id),
        )
    return cur.rowcount > 0


def segna_capolinea(
    conn: sqlite3.Connection, stop_id: str, *, origine: bool = False, destinazione: bool = False
) -> bool:
    """Marca la stazione come origine e/o destinazione di un treno.

    Restituisce True solo quando la stazione *diventa* capolinea (prima non lo era).
    """
    riga = conn.execute(
        "SELECT e_origine, e_destinazione FROM stops WHERE stop_id = ?", (stop_id,)
    ).fetchone()
    if riga is None:
        return False
    era = bool(riga["e_origine"] or riga["e_destinazione"])
    nuova_o = int(bool(riga["e_origine"]) or origine)
    nuova_d = int(bool(riga["e_destinazione"]) or destinazione)
    if (nuova_o, nuova_d) != (riga["e_origine"], riga["e_destinazione"]):
        conn.execute(
            "UPDATE stops SET e_origine = ?, e_destinazione = ? WHERE stop_id = ?",
            (nuova_o, nuova_d, stop_id),
        )
    return bool(nuova_o or nuova_d) and not era


def ricava_destinazione(conn: sqlite3.Connection) -> int:
    """Valorizza `treni.cod_destinazione` dall'ultima fermata non soppressa (una tantum).

    I tabelloni delle partenze danno solo il nome della destinazione, non il codice, e in passato
    la verifica non lo aggiornava. Per i treni che hanno gia' le fermate la destinazione effettiva
    e' l'ultima fermata con `actual_fermata_type != 3` (tiene conto delle soppressioni), in ordine
    di inserimento: il `progressivo` non e' affidabile. Non tocca i valori gia' presenti.
    Restituisce quanti treni valorizza.
    """
    prima = conn.execute(
        "SELECT COUNT(*) FROM treni WHERE cod_destinazione IS NOT NULL"
    ).fetchone()[0]
    conn.execute(
        """UPDATE treni SET cod_destinazione = (
               SELECT f.stop_id FROM fermate f
               WHERE f.treno_id = treni.id AND COALESCE(f.actual_fermata_type, -1) != 3
               ORDER BY f.id DESC LIMIT 1)
           WHERE cod_destinazione IS NULL"""
    )
    conn.commit()
    dopo = conn.execute("SELECT COUNT(*) FROM treni WHERE cod_destinazione IS NOT NULL").fetchone()[
        0
    ]
    return int(dopo - prima)


def ricava_capolinea(conn: sqlite3.Connection) -> int:
    """Segna come capolinea le stazioni che lo risultano dai dati gia' raccolti.

    Origine = `treni.cod_origine`; destinazione = `treni.cod_destinazione` o ultima
    fermata ('A') di un itinerario. Idempotente. Restituisce quante righe cambia.
    """
    n = conn.execute(
        "UPDATE stops SET e_origine = 1 WHERE e_origine = 0 "
        "AND stop_id IN (SELECT DISTINCT cod_origine FROM treni)"
    ).rowcount
    n += conn.execute(
        "UPDATE stops SET e_destinazione = 1 WHERE e_destinazione = 0 AND ("
        "stop_id IN (SELECT DISTINCT cod_destinazione FROM treni WHERE cod_destinazione IS NOT NULL) "
        "OR stop_id IN (SELECT DISTINCT stop_id FROM fermate WHERE tipo_fermata = 'A'))"
    ).rowcount
    return n


def imposta_scadenza_stazione(
    conn: sqlite3.Connection, stop_id: str, quando_ms: int | None, *, solo_se_prima: bool = False
) -> None:
    """Scrive `stops.prossima_sonda`. Con `solo_se_prima` non la sposta in avanti."""
    if solo_se_prima and quando_ms is not None:
        conn.execute(
            "UPDATE stops SET prossima_sonda = ? WHERE stop_id = ? "
            "AND (prossima_sonda IS NULL OR prossima_sonda > ?)",
            (quando_ms, stop_id, quando_ms),
        )
    else:
        conn.execute("UPDATE stops SET prossima_sonda = ? WHERE stop_id = ?", (quando_ms, stop_id))


def tipo_giorno_di(data_partenza_treno: int) -> str:
    """'feriale' | 'sabato' | 'festivo' del giorno di servizio di un treno."""
    return tipo_giorno(data_di_servizio(data_partenza_treno)).value


def ricava_tipo_giorno(conn: sqlite3.Connection) -> int:
    """Valorizza `tipo_giorno` nelle corse che non l'hanno (DB precedenti). Restituisce quante."""
    giorni = conn.execute(
        "SELECT DISTINCT data_partenza_treno FROM treni WHERE tipo_giorno IS NULL"
    ).fetchall()
    n = 0
    for (data,) in giorni:
        n += conn.execute(
            "UPDATE treni SET tipo_giorno = ? WHERE data_partenza_treno = ? AND tipo_giorno IS NULL",
            (tipo_giorno_di(data), data),
        ).rowcount
    return n


def imposta_scade_orario(conn: sqlite3.Connection, treno_id: int, scade_ms: int | None) -> None:
    conn.execute("UPDATE treni SET scade_orario = ? WHERE id = ?", (scade_ms, treno_id))


def orario_valido(
    conn: sqlite3.Connection, numero_treno: int, cod_origine: str, tipo: str, ora_ms: int
) -> bool:
    """C'e' gia' un record non scaduto dello stesso treno per lo stesso tipo di giorno?

    Non conta una corsa senza itinerario utile (`non_disponibile`, `scaduto`) o soppressa: la
    prossima occasione la riprova.
    """
    return (
        conn.execute(
            "SELECT 1 FROM treni WHERE numero_treno = ? AND cod_origine = ? AND tipo_giorno = ? "
            "AND scade_orario > ? AND stato NOT IN ('non_disponibile', 'scaduto', 'soppresso') "
            "LIMIT 1",
            (numero_treno, cod_origine, tipo, ora_ms),
        ).fetchone()
        is not None
    )


def imposta_scadenza_treno(
    conn: sqlite3.Connection,
    treno_id: int,
    quando_ms: int | None,
    arrivo_previsto: int | None = None,
) -> None:
    """Scrive `treni.prossima_verifica` (e, se dato, `arrivo_previsto`)."""
    if arrivo_previsto is None:
        conn.execute("UPDATE treni SET prossima_verifica = ? WHERE id = ?", (quando_ms, treno_id))
    else:
        conn.execute(
            "UPDATE treni SET prossima_verifica = ?, arrivo_previsto = ? WHERE id = ?",
            (quando_ms, arrivo_previsto, treno_id),
        )


def chiudi_scaduti(conn: sqlite3.Connection, ora_ms: int, oltre_ms: int) -> int:
    """Chiude i treni 'in_corso' il cui arrivo previsto e' passato da piu' di `oltre_ms`.

    Se l'arrivo non e' noto si ripiega sull'orario di partenza + 24 h o, in mancanza,
    sulla fine della giornata del treno: un treno notturno partito ieri sera non viene
    toccato (a differenza di `chiudi_treni_obsoleti`, che guarda solo la data).
    """
    cur = conn.execute(
        "UPDATE treni SET stato = 'non_disponibile', chiusura_motivo = 'scaduto', "
        "prossima_verifica = NULL, ultimo_aggiornamento = ? "
        "WHERE stato = 'in_corso' AND "
        "COALESCE(arrivo_previsto, orario_partenza + 86400000, data_partenza_treno + 86400000) "
        "+ ? < ?",
        (ora_ms, oltre_ms, ora_ms),
    )
    conn.commit()
    return cur.rowcount
