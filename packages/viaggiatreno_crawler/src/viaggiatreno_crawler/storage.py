"""Persistenza SQLite per il crawler: schema, upsert e query di aggregazione.

Schema a stella: `regioni`/`stazioni` sono dimensioni (poco variabili nel
tempo), `treni`/`fermate` sono fatti che crescono ogni giorno. `fermate` è la
tabella chiave per i KPI a livello di stazione/binario (quali stazioni hanno
più traffico, quali binari usa più spesso una stazione): non è ottenibile da
`elencoTratte`/`dettagliTratta` (solo origine/destinazione), serve il
dettaglio completo di `andamentoTreno`.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS regioni (
    codice INTEGER PRIMARY KEY,
    nome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stazioni (
    codice TEXT PRIMARY KEY,
    nome TEXT,
    lat REAL,
    lon REAL,
    regione_codice INTEGER REFERENCES regioni(codice),
    citta TEXT,
    ultimo_aggiornamento INTEGER
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
    UNIQUE (numero_treno, cod_origine, data_partenza_treno)
);

CREATE INDEX IF NOT EXISTS idx_treni_stato ON treni(stato);

CREATE TABLE IF NOT EXISTS fermate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    treno_id INTEGER NOT NULL REFERENCES treni(id) ON DELETE CASCADE,
    stazione_codice TEXT NOT NULL REFERENCES stazioni(codice),
    progressivo INTEGER,
    tipo_fermata TEXT,
    orario_programmato INTEGER,
    orario_effettivo INTEGER,
    ritardo INTEGER,
    binario_programmato TEXT,
    binario_effettivo TEXT,
    actual_fermata_type INTEGER
);

CREATE INDEX IF NOT EXISTS idx_fermate_stazione ON fermate(stazione_codice);
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
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Apre (creando se necessario) il database e applica lo schema."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Dimensioni
# ---------------------------------------------------------------------------


def upsert_regione(conn: sqlite3.Connection, codice: int, nome: str) -> None:
    conn.execute(
        "INSERT INTO regioni (codice, nome) VALUES (?, ?) "
        "ON CONFLICT(codice) DO UPDATE SET nome = excluded.nome",
        (codice, nome),
    )


def upsert_stazione(
    conn: sqlite3.Connection,
    codice: str,
    nome: str | None,
    lat: float | None,
    lon: float | None,
    regione_codice: int | None,
    citta: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO stazioni (codice, nome, lat, lon, regione_codice, citta, ultimo_aggiornamento)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(codice) DO UPDATE SET
            nome = excluded.nome,
            lat = excluded.lat,
            lon = excluded.lon,
            regione_codice = excluded.regione_codice,
            citta = excluded.citta,
            ultimo_aggiornamento = excluded.ultimo_aggiornamento
        """,
        (codice, nome, lat, lon, regione_codice, citta, int(time.time() * 1000)),
    )


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
            primo_avvistamento, ultimo_aggiornamento, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(numero_treno, cod_origine, data_partenza_treno) DO UPDATE SET
            categoria = excluded.categoria,
            cod_destinazione = excluded.cod_destinazione,
            origine = excluded.origine,
            destinazione = excluded.destinazione,
            codice_cliente = excluded.codice_cliente,
            stato = excluded.stato,
            ritardo_corrente = excluded.ritardo_corrente,
            ritardo_finale = excluded.ritardo_finale,
            tentativi_204 = 0,
            ultimo_aggiornamento = excluded.ultimo_aggiornamento,
            raw_json = excluded.raw_json
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
        ),
    )
    row = conn.execute(
        "SELECT id FROM treni WHERE numero_treno = ? AND cod_origine = ? AND data_partenza_treno = ?",
        (numero_treno, cod_origine, data_partenza_treno),
    ).fetchone()
    return int(row["id"])


def registra_204(conn: sqlite3.Connection, treno_id: int, soglia: int = 5) -> None:
    """Incrementa il contatore di 204 consecutivi; oltre `soglia` marca il treno come non disponibile."""
    conn.execute(
        """
        UPDATE treni SET tentativi_204 = tentativi_204 + 1,
            stato = CASE WHEN tentativi_204 + 1 >= ? THEN 'non_disponibile' ELSE stato END,
            ultimo_aggiornamento = ?
        WHERE id = ?
        """,
        (soglia, int(time.time() * 1000), treno_id),
    )


def sostituisci_fermate(conn: sqlite3.Connection, treno_id: int, fermate: Iterable[dict[str, Any]]) -> None:
    """Rimpiazza tutte le fermate note di un treno con quelle fornite (da andamentoTreno)."""
    conn.execute("DELETE FROM fermate WHERE treno_id = ?", (treno_id,))
    conn.executemany(
        """
        INSERT INTO fermate (
            treno_id, stazione_codice, progressivo, tipo_fermata,
            orario_programmato, orario_effettivo, ritardo,
            binario_programmato, binario_effettivo, actual_fermata_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                treno_id,
                f["stazione_codice"],
                f.get("progressivo"),
                f.get("tipo_fermata"),
                f.get("orario_programmato"),
                f.get("orario_effettivo"),
                f.get("ritardo"),
                f.get("binario_programmato"),
                f.get("binario_effettivo"),
                f.get("actual_fermata_type"),
            )
            for f in fermate
        ],
    )


def treni_attivi(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Treni ancora da verificare (non arrivati/soppressi/non_disponibile)."""
    return conn.execute("SELECT * FROM treni WHERE stato = 'in_corso'").fetchall()


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


def binari_per_stazione(conn: sqlite3.Connection, stazione_codice: str) -> list[sqlite3.Row]:
    """Binari effettivi osservati per una stazione, ordinati per frequenza."""
    return conn.execute(
        """
        SELECT binario_effettivo, COUNT(*) AS n
        FROM fermate
        WHERE stazione_codice = ? AND binario_effettivo IS NOT NULL
        GROUP BY binario_effettivo
        ORDER BY n DESC
        """,
        (stazione_codice,),
    ).fetchall()


def stazioni_per_traffico(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    """Stazioni con più treni distinti transitati (per traffico osservato)."""
    return conn.execute(
        """
        SELECT f.stazione_codice, s.nome, COUNT(DISTINCT f.treno_id) AS n_treni
        FROM fermate f
        LEFT JOIN stazioni s ON s.codice = f.stazione_codice
        GROUP BY f.stazione_codice
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
