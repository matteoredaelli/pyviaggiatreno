# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ripresa dopo un riavvio: si ricorda l'ultimo giro e l'ultima chiamata per elemento."""

import sqlite3

from viaggiatreno_crawler import storage

ORA = 1_800_000_000_000
SEC = 1000


# ================================================== quanto aspettare dopo un riavvio


# ================================================== il ciclo salva l'ultimo giro


# ================================================== verifica: treno controllato da poco


# nessun return: restituisce None, cioe' una risposta 204


# ================================================== tabelloni: stazione richiesta da poco


# ================================================== schema e CLI


def test_connect_migra_le_colonne_di_ripresa(tmp_path):
    percorso = tmp_path / "vecchio.db"
    v = sqlite3.connect(percorso)
    v.executescript(
        """CREATE TABLE treni (id INTEGER PRIMARY KEY AUTOINCREMENT, numero_treno INTEGER NOT NULL,
           cod_origine TEXT NOT NULL, data_partenza_treno INTEGER NOT NULL, categoria TEXT,
           cod_destinazione TEXT, origine TEXT, destinazione TEXT, codice_cliente INTEGER,
           stato TEXT NOT NULL DEFAULT 'in_corso', ritardo_corrente INTEGER, ritardo_finale INTEGER,
           tentativi_204 INTEGER NOT NULL DEFAULT 0, primo_avvistamento INTEGER NOT NULL,
           ultimo_aggiornamento INTEGER NOT NULL, raw_json TEXT, route_id TEXT, trip_id TEXT,
           UNIQUE (numero_treno, cod_origine, data_partenza_treno));
           CREATE TABLE stops (stop_id TEXT PRIMARY KEY, stop_name TEXT, stop_lat REAL, stop_lon REAL,
           stop_url TEXT, regione_codice INTEGER, citta TEXT, fonte TEXT NOT NULL DEFAULT 'viaggiatreno',
           ultimo_aggiornamento INTEGER);"""
    )
    v.commit()
    v.close()
    conn = storage.connect(percorso)
    treni = {r[1] for r in conn.execute("PRAGMA table_info(treni)")}
    stops = {r[1] for r in conn.execute("PRAGMA table_info(stops)")}
    assert {"orario_partenza", "chiusura_motivo", "ultima_verifica"} <= treni
    assert "ultimo_tabellone" in stops
    storage.connect(percorso).close()  # idempotente


# ================================================== registro delle richieste di tabellone


def test_connect_crea_il_registro_anche_su_db_esistente(tmp_path):
    percorso = tmp_path / "vecchio.db"
    conn = storage.connect(percorso)
    conn.execute("DROP TABLE tabelloni_richieste")
    conn.commit()
    conn.close()
    conn = storage.connect(percorso)  # un DB di prima della tabella: viene ricreata
    assert conn.execute("SELECT COUNT(*) FROM tabelloni_richieste").fetchone()[0] == 0
