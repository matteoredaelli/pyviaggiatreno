# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Il ciclo tabelloni deve interrogare solo le partenze, salvo --tabelloni-arrivi."""

from types import SimpleNamespace
from typing import cast

import pytest
from viaggiatreno import ViaggiaTrenoClient
from viaggiatreno_crawler import storage
from viaggiatreno_crawler.__main__ import parse_args
from viaggiatreno_crawler.config import CrawlerConfig
from viaggiatreno_crawler.poller import scopri_da_tabelloni


class ClientFinto:
    """Registra quali tabelloni vengono chiesti e per quale stazione."""

    def __init__(self):
        self.chiamate: list[tuple[str, str]] = []

    async def partenze(self, stop_id):
        self.chiamate.append(("partenze", stop_id))
        return [_riga(100, stop_id)]

    async def arrivi(self, stop_id):
        self.chiamate.append(("arrivi", stop_id))
        return [_riga(200, "S09999")]


def _riga(numero, origine):
    return SimpleNamespace(
        numeroTreno=numero,
        codOrigine=origine,
        dataPartenzaTreno=1000,
        categoria="REG",
        codDestinazione=None,
        origine=None,
        destinazione=None,
        codiceCliente=63,
        ritardo=0,
        orarioPartenza=None,
        model_dump_json=lambda: "{}",
    )


def _come_client(stub: object) -> ViaggiaTrenoClient:
    """Lo stub espone solo partenze/arrivi: per pyright lo si tratta come il client."""
    return cast(ViaggiaTrenoClient, stub)


def _db(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.upsert_stop(conn, "S01520", "LECCO", 45.8, 9.3, regione_codice=1)
    storage.upsert_stop(conn, "S01322", "MONZA", 45.5, 9.2, regione_codice=1)
    return conn


def test_default_solo_partenze():
    assert CrawlerConfig().tabelloni_arrivi is False


@pytest.mark.asyncio
async def test_default_chiede_solo_le_partenze(tmp_path):
    conn, client = _db(tmp_path), ClientFinto()
    cfg = CrawlerConfig(regione=1, tabelloni_max_stazioni=10)
    await scopri_da_tabelloni(conn, _come_client(client), cfg)
    assert {m for m, _ in client.chiamate} == {"partenze"}
    assert {s for _, s in client.chiamate} == {"S01520", "S01322"}
    # i treni scoperti dalle partenze sono stati registrati
    assert conn.execute("SELECT COUNT(*) FROM treni").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_con_flag_chiede_anche_gli_arrivi(tmp_path):
    conn, client = _db(tmp_path), ClientFinto()
    cfg = CrawlerConfig(regione=1, tabelloni_max_stazioni=10, tabelloni_arrivi=True)
    await scopri_da_tabelloni(conn, _come_client(client), cfg)
    assert {m for m, _ in client.chiamate} == {"partenze", "arrivi"}
    assert len(client.chiamate) == 4  # 2 stazioni x 2 tabelloni


def test_flag_cli():
    assert parse_args(["run"]).tabelloni_arrivi is False
    assert parse_args(["run", "--tabelloni-arrivi"]).tabelloni_arrivi is True


def test_flag_cli_rare_per_giro():
    assert parse_args(["run"]).tabelloni_rare_per_giro == 10
    assert parse_args(["run", "--tabelloni-rare-per-giro", "3"]).tabelloni_rare_per_giro == 3


# --------------------------------------------------------------------------
# Ordinamento: capolinea (treni che nascono qui) prima, non i nodi di transito
# --------------------------------------------------------------------------


def test_ordina_per_treni_che_nascono_non_per_fermate(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    for sid in ("S_CAPO", "S_TRANSITO", "S_VUOTA"):
        storage.upsert_stop(conn, sid, sid, 45.0, 9.0, regione_codice=1)
    # CAPOLINEA: 3 treni nascono qui, poche fermate osservate
    for n in (1, 2, 3):
        t = storage.upsert_treno(conn, numero_treno=n, cod_origine="S_CAPO", data_partenza_treno=1)
        storage.sostituisci_fermate(conn, t, [{"stop_id": "S_CAPO"}])
    # TRANSITO: nessun treno nasce qui ma ci passano tutti (molte fermate)
    for n in (1, 2, 3):
        t = conn.execute("SELECT id FROM treni WHERE numero_treno=?", (n,)).fetchone()["id"]
        storage.sostituisci_fermate(conn, t, [{"stop_id": "S_CAPO"}, {"stop_id": "S_TRANSITO"}])
    ordine = storage.stazioni_per_origine(conn, 1)
    assert ordine == ["S_CAPO", "S_TRANSITO", "S_VUOTA"]


def test_ordine_include_tutte_le_stazioni_della_regione(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.upsert_stop(conn, "S1", "A", 45.0, 9.0, regione_codice=1)
    storage.upsert_stop(conn, "S2", "B", 45.0, 9.0, regione_codice=2)  # altra regione
    storage.upsert_stop(conn, "S3", "C", 45.0, 9.0)  # regione ignota (es. da GTFS)
    assert set(storage.stazioni_per_origine(conn, 1)) == {"S1", "S3"}
    assert set(storage.stazioni_per_origine(conn, 0)) == {"S1", "S2", "S3"}


# --------------------------------------------------------------------------
# Copertura: le secondarie vengono sondate a rotazione, nessuna resta fuori
# --------------------------------------------------------------------------


def _db_con_stazioni(tmp_path, n):
    conn = storage.connect(tmp_path / "t.db")
    for i in range(n):
        storage.upsert_stop(conn, f"S{i:05d}", f"ST{i}", 45.0, 9.0, regione_codice=1)
    return conn


class ClientVuoto:
    def __init__(self):
        self.viste: list[str] = []

    async def partenze(self, stop_id):
        self.viste.append(stop_id)
        return []

    async def arrivi(self, stop_id):
        return []


@pytest.mark.asyncio
async def test_le_secondarie_si_coprono_a_rotazione(tmp_path):
    conn = _db_con_stazioni(tmp_path, 120)
    client = ClientVuoto()
    cfg = CrawlerConfig(
        regione=1,
        tabelloni_max_stazioni=50,
        tabelloni_rare_per_giro=10,
        tabellone_min_intervallo_sec=0,
    )
    # 70 secondarie / 10 per giro = 7 giri per una rotazione completa
    viste = set()
    for _ in range(7):
        client.viste.clear()
        await scopri_da_tabelloni(conn, _come_client(client), cfg)
        assert len(client.viste) == 60  # 50 principali + 10 secondarie
        viste |= set(client.viste)
    assert len(viste) == 120  # nessuna stazione rimasta fuori (prima: 70 mai sondate)


@pytest.mark.asyncio
async def test_principali_sempre_secondarie_a_turno(tmp_path):
    conn = _db_con_stazioni(tmp_path, 60)
    client = ClientVuoto()
    cfg = CrawlerConfig(
        regione=1,
        tabelloni_max_stazioni=50,
        tabelloni_rare_per_giro=5,
        tabellone_min_intervallo_sec=0,
    )
    principali = set(storage.stazioni_per_origine(conn, 1)[:50])
    giri = []
    for _ in range(2):
        client.viste.clear()
        await scopri_da_tabelloni(conn, _come_client(client), cfg)
        giri.append(set(client.viste))
    assert principali <= giri[0] and principali <= giri[1]  # sempre
    assert (giri[0] - principali).isdisjoint(giri[1] - principali)  # secondarie diverse


@pytest.mark.asyncio
async def test_rare_per_giro_zero_non_sonda_le_secondarie(tmp_path):
    conn = _db_con_stazioni(tmp_path, 60)
    client = ClientVuoto()
    cfg = CrawlerConfig(regione=1, tabelloni_max_stazioni=50, tabelloni_rare_per_giro=0)
    await scopri_da_tabelloni(conn, _come_client(client), cfg)
    assert len(client.viste) == 50


@pytest.mark.asyncio
async def test_il_checkpoint_delle_secondarie_sopravvive_al_riavvio(tmp_path):
    conn = _db_con_stazioni(tmp_path, 60)
    cfg = CrawlerConfig(
        regione=1,
        tabelloni_max_stazioni=50,
        tabelloni_rare_per_giro=4,
        tabellone_min_intervallo_sec=0,
    )
    primo = ClientVuoto()
    await scopri_da_tabelloni(conn, _come_client(primo), cfg)
    # "riavvio": stessa connessione/DB, nuovo client
    secondo = ClientVuoto()
    await scopri_da_tabelloni(conn, _come_client(secondo), cfg)
    sec1 = [s for s in primo.viste if s not in storage.stazioni_per_origine(conn, 1)[:50]]
    sec2 = [s for s in secondo.viste if s not in storage.stazioni_per_origine(conn, 1)[:50]]
    assert len(sec1) == 4 and len(sec2) == 4  # 10 secondarie: due giri da 4, non gli stessi
    assert set(sec1).isdisjoint(sec2)


@pytest.mark.asyncio
async def test_meno_stazioni_del_limite_non_va_in_errore(tmp_path):
    conn = _db_con_stazioni(tmp_path, 3)
    client = ClientVuoto()
    cfg = CrawlerConfig(
        regione=1,
        tabelloni_max_stazioni=50,
        tabelloni_rare_per_giro=10,
        tabellone_min_intervallo_sec=0,
    )
    await scopri_da_tabelloni(conn, _come_client(client), cfg)
    assert len(client.viste) == 3
