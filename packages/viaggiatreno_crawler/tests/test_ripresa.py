# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ripresa dopo un riavvio: si ricorda l'ultimo giro e l'ultima chiamata per elemento."""

import asyncio
import sqlite3
import time
from typing import cast

import pytest
from viaggiatreno import ViaggiaTrenoClient
from viaggiatreno_crawler import poller, storage
from viaggiatreno_crawler.__main__ import parse_args
from viaggiatreno_crawler.config import CrawlerConfig
from viaggiatreno_crawler.poller import (
    _ciclo,
    scopri_da_tabelloni,
    secondi_all_prossimo_giro,
    verifica_treni_attivi,
)

ORA = 1_800_000_000_000
SEC = 1000


# ================================================== quanto aspettare dopo un riavvio


def test_primo_avvio_parte_subito():
    assert secondi_all_prossimo_giro(None, 300) == 0.0


def test_giro_appena_concluso_attende_il_resto_dell_intervallo():
    assert secondi_all_prossimo_giro(str(ORA - 100 * SEC), 300, ORA) == 200.0


def test_intervallo_gia_trascorso_parte_subito():
    assert secondi_all_prossimo_giro(str(ORA - 400 * SEC), 300, ORA) == 0.0
    assert secondi_all_prossimo_giro(str(ORA - 300 * SEC), 300, ORA) == 0.0


def test_valore_illeggibile_non_blocca_il_ciclo():
    assert secondi_all_prossimo_giro("non-un-numero", 300, ORA) == 0.0


def test_orologio_all_indietro_non_blocca_oltre_un_intervallo():
    # ultimo giro "nel futuro": non si resta in attesa di ore
    assert secondi_all_prossimo_giro(str(ORA + 3600 * SEC), 300, ORA) == 0.0


# ================================================== il ciclo salva l'ultimo giro


class Orologio:
    """sleep finto che ferma il ciclo dopo il primo giro eseguito.

    Lo stop si lega al *lavoro* (un giro completato), non all'ordine degli sleep:
    `lavoro_eseguito` va impostato dal lavoro di prova. Le attese registrate
    includono quella iniziale (solo se deve recuperare tempo) e quella dopo il giro.
    """

    def __init__(self):
        self.attese: list[float] = []
        self.giri = 0

    async def sleep(self, secondi):
        self.attese.append(secondi)
        if self.giri >= 1:
            raise asyncio.CancelledError


async def _niente():
    """Lavoro che non fa nulla e non dorme (lo sleep finto registrerebbe un'attesa)."""


async def _esegui_ciclo(conn, lavoro, intervallo, monkeypatch):
    o = Orologio()

    async def lavoro_contato():
        o.giri += 1
        await lavoro()

    monkeypatch.setattr(poller.asyncio, "sleep", o.sleep)
    with pytest.raises(asyncio.CancelledError):
        await _ciclo("prova", conn, lavoro_contato, intervallo)
    return o.attese


@pytest.mark.asyncio
async def test_primo_avvio_esegue_subito_e_registra_l_ora(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    chiamate = []

    async def lavoro():
        chiamate.append(1)

    attese = await _esegui_ciclo(conn, lavoro, 300, monkeypatch)
    assert chiamate == [1]
    assert attese == [300]  # nessuna attesa iniziale, solo l'intervallo dopo il giro
    salvato = storage.get_stato(conn, "ultimo_giro_prova")
    assert salvato is not None
    ultimo = int(salvato)
    assert abs(ultimo - time.time() * 1000) < 5000


@pytest.mark.asyncio
async def test_riavvio_ravvicinato_attende_il_tempo_residuo(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    storage.set_stato(conn, "ultimo_giro_prova", str(int(time.time() * 1000) - 100 * SEC))
    attese = await _esegui_ciclo(conn, _niente, 300, monkeypatch)
    assert 195 <= attese[0] <= 200  # circa 200 s mancanti, prima del primo giro


@pytest.mark.asyncio
async def test_riavvio_dopo_molto_tempo_parte_subito(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    storage.set_stato(conn, "ultimo_giro_prova", str(int(time.time() * 1000) - 900 * SEC))
    attese = await _esegui_ciclo(conn, _niente, 300, monkeypatch)
    assert attese == [300]  # nessuna attesa iniziale


@pytest.mark.asyncio
async def test_un_giro_in_errore_non_viene_segnato_come_fatto(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")

    async def lavoro():
        raise RuntimeError("403")

    await _esegui_ciclo(conn, lavoro, 300, monkeypatch)
    assert storage.get_stato(conn, "ultimo_giro_prova") is None  # al riavvio si riprova subito


# ================================================== verifica: treno controllato da poco


def _treno(conn, numero, partenza=None):
    return storage.upsert_treno(
        conn,
        numero_treno=numero,
        cod_origine="S00001",
        data_partenza_treno=1,
        orario_partenza=partenza,
    )


def test_filtro_controllati_da_poco(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    mai = _treno(conn, 1)
    vecchio = _treno(conn, 2)
    recente = _treno(conn, 3)
    storage.segna_verifica(conn, vecchio, ORA - 1000 * SEC)
    storage.segna_verifica(conn, recente, ORA - 60 * SEC)
    soglia = ORA - 300 * SEC
    ids = {r["id"] for r in storage.treni_attivi(conn, None, soglia)}
    assert ids == {mai, vecchio}  # il treno controllato 60 s fa e' escluso
    assert storage.conta_treni_attivi(conn, None, soglia) == 2
    assert {r["id"] for r in storage.treni_attivi_da(conn, 0, 10, None, soglia)} == {mai, vecchio}
    # senza il filtro: tutti
    assert len(storage.treni_attivi(conn)) == 3


def test_i_due_filtri_si_combinano(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    lontano = _treno(conn, 1, ORA + 3600 * SEC)
    pronto = _treno(conn, 2, ORA - 60 * SEC)
    recente = _treno(conn, 3, ORA - 60 * SEC)
    storage.segna_verifica(conn, recente, ORA - 30 * SEC)
    ids = {r["id"] for r in storage.treni_attivi(conn, ORA, ORA - 300 * SEC)}
    assert ids == {pronto}
    assert lontano not in ids and recente not in ids


class ClientVerifica:
    def __init__(self):
        self.chiamate: list[int] = []

    async def andamento_treno(self, cod, numero, data):
        self.chiamate.append(numero)
        # nessun return: restituisce None, cioe' una risposta 204


@pytest.mark.asyncio
async def test_la_verifica_annota_l_ora_e_non_rifa_la_chiamata(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: ORA / 1000)
    conn = storage.connect(tmp_path / "t.db")
    _treno(conn, 1, ORA - 5 * 60 * SEC)
    client = ClientVerifica()
    cfg = CrawlerConfig(verifica_min_intervallo_sec=300)
    await verifica_treni_attivi(conn, cast(ViaggiaTrenoClient, client), cfg)
    assert client.chiamate == [1]
    assert conn.execute("SELECT ultima_verifica FROM treni").fetchone()[0] == ORA
    # secondo giro subito dopo (es. riavvio): il treno e' stato appena controllato
    await verifica_treni_attivi(conn, cast(ViaggiaTrenoClient, client), cfg)
    assert client.chiamate == [1]
    # passati 301 secondi si ricontrolla
    monkeypatch.setattr(time, "time", lambda: (ORA + 301 * SEC) / 1000)
    await verifica_treni_attivi(conn, cast(ViaggiaTrenoClient, client), cfg)
    assert client.chiamate == [1, 1]


@pytest.mark.asyncio
async def test_minimo_zero_disattiva_il_filtro(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: ORA / 1000)
    conn = storage.connect(tmp_path / "t.db")
    _treno(conn, 1, ORA - 5 * 60 * SEC)
    client = ClientVerifica()
    cfg = CrawlerConfig(verifica_min_intervallo_sec=0)
    for _ in range(3):
        await verifica_treni_attivi(conn, cast(ViaggiaTrenoClient, client), cfg)
    assert client.chiamate == [1, 1, 1]


@pytest.mark.asyncio
async def test_un_errore_di_rete_non_conta_come_controllo_fatto(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: ORA / 1000)
    conn = storage.connect(tmp_path / "t.db")
    _treno(conn, 1, ORA - 5 * 60 * SEC)

    class ClientRotto:
        async def andamento_treno(self, *a):
            raise RuntimeError("403")

    await verifica_treni_attivi(conn, cast(ViaggiaTrenoClient, ClientRotto()), CrawlerConfig())
    assert conn.execute("SELECT ultima_verifica FROM treni").fetchone()[0] is None


# ================================================== tabelloni: stazione richiesta da poco


class ClientTabelloni:
    def __init__(self, falliscono=()):
        self.viste: list[str] = []
        self.falliscono = set(falliscono)

    async def partenze(self, stop_id):
        self.viste.append(stop_id)
        if stop_id in self.falliscono:
            raise RuntimeError("403")
        return []

    async def arrivi(self, stop_id):
        return []


def _db(tmp_path, n=4):
    conn = storage.connect(tmp_path / "t.db")
    for i in range(n):
        storage.upsert_stop(conn, f"S{i:05d}", f"ST{i}", 45.0, 9.0, regione_codice=1)
    return conn


@pytest.mark.asyncio
async def test_stazione_richiesta_da_poco_non_viene_richiamata(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: ORA / 1000)
    conn = _db(tmp_path)
    cfg = CrawlerConfig(
        regione=1,
        tabelloni_max_stazioni=50,
        tabelloni_rare_per_giro=0,
        tabellone_min_intervallo_sec=1800,
    )
    c1 = ClientTabelloni()
    await scopri_da_tabelloni(conn, cast(ViaggiaTrenoClient, c1), cfg)
    assert len(c1.viste) == 4
    # riavvio dopo 2 minuti: nessuna richiesta, sono tutte fresche
    monkeypatch.setattr(time, "time", lambda: (ORA + 120 * SEC) / 1000)
    c2 = ClientTabelloni()
    await scopri_da_tabelloni(conn, cast(ViaggiaTrenoClient, c2), cfg)
    assert c2.viste == []
    # dopo 31 minuti si richiedono di nuovo
    monkeypatch.setattr(time, "time", lambda: (ORA + 1860 * SEC) / 1000)
    c3 = ClientTabelloni()
    await scopri_da_tabelloni(conn, cast(ViaggiaTrenoClient, c3), cfg)
    assert len(c3.viste) == 4


@pytest.mark.asyncio
async def test_una_stazione_in_errore_si_riprova_al_giro_dopo(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: ORA / 1000)
    conn = _db(tmp_path)
    cfg = CrawlerConfig(regione=1, tabelloni_max_stazioni=50, tabelloni_rare_per_giro=0)
    c1 = ClientTabelloni(falliscono={"S00001"})
    await scopri_da_tabelloni(conn, cast(ViaggiaTrenoClient, c1), cfg)
    monkeypatch.setattr(time, "time", lambda: (ORA + 60 * SEC) / 1000)
    c2 = ClientTabelloni()
    await scopri_da_tabelloni(conn, cast(ViaggiaTrenoClient, c2), cfg)
    assert c2.viste == ["S00001"]  # solo quella andata male


@pytest.mark.asyncio
async def test_minimo_tabellone_zero_richiede_sempre(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: ORA / 1000)
    conn = _db(tmp_path)
    cfg = CrawlerConfig(
        regione=1,
        tabelloni_max_stazioni=50,
        tabelloni_rare_per_giro=0,
        tabellone_min_intervallo_sec=0,
    )
    for _ in range(2):
        c = ClientTabelloni()
        await scopri_da_tabelloni(conn, cast(ViaggiaTrenoClient, c), cfg)
        assert len(c.viste) == 4


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


def test_default_e_flag_cli():
    cfg = CrawlerConfig()
    assert cfg.verifica_min_intervallo_sec == 300 and cfg.tabellone_min_intervallo_sec == 1800
    a = parse_args(["run"])
    assert (a.verifica_min_intervallo_sec, a.tabellone_min_intervallo_sec) == (300, 1800)
    b = parse_args(["run", "--verifica-min-intervallo", "60", "--tabellone-min-intervallo", "0"])
    assert (b.verifica_min_intervallo_sec, b.tabellone_min_intervallo_sec) == (60, 0)


def test_conteggio_attivi_coerente_con_la_selezione(tmp_path):
    """`conta_treni_attivi` e `treni_attivi` devono contare gli stessi treni."""
    conn = storage.connect(tmp_path / "t.db")
    for n in range(1, 8):
        tid = _treno(conn, n, ORA + (n - 4) * 600 * SEC)  # alcuni lontani, alcuni vicini
        if n % 2:
            storage.segna_verifica(conn, tid, ORA - 30 * SEC)
    for fino_a in (None, ORA, ORA + 900 * SEC):
        for prima_di in (None, ORA - 300 * SEC):
            assert storage.conta_treni_attivi(conn, fino_a, prima_di) == len(
                storage.treni_attivi(conn, fino_a, prima_di)
            )
