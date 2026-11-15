# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Caricamento una tantum dei segmenti della rete (`make tratte`)."""

from types import SimpleNamespace
from typing import cast

import pytest
from viaggiatreno import ViaggiaTrenoClient
from viaggiatreno_crawler import storage
from viaggiatreno_crawler.__main__ import main
from viaggiatreno_crawler.poller import carica_tratte


def _seg(ab, a="S1", b="S2"):
    return SimpleNamespace(
        trattaAB=ab,
        trattaBA=ab + 1,
        nodoA=a,
        nodoB=b,
        latitudineA=45.0,
        longitudineA=9.0,
        latitudineB=45.1,
        longitudineB=9.1,
        parentAB=ab,
        parentBA=ab + 1,
        occupata=True,
    )


class ClientTratte:
    def __init__(self, per_regione, falliscono=()):
        self.per_regione = per_regione
        self.falliscono = set(falliscono)
        self.chiamate: list[int] = []
        self.dettagli = 0

    async def elenco_tratte(self, categorie, id_regione, zoomlevel):
        self.chiamate.append(id_regione)
        if id_regione in self.falliscono:
            raise RuntimeError("403")
        return self.per_regione.get(id_regione, [])

    async def dettagli_tratta(self, *a, **k):  # non deve mai essere chiamata
        self.dettagli += 1
        return []


def _c(c):
    return cast(ViaggiaTrenoClient, c)


async def test_default_sono_le_regioni_da_0_a_22(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    c = ClientTratte({})
    await carica_tratte(conn, _c(c))
    assert c.chiamate == list(range(23))


async def test_stesso_id_in_regioni_diverse_sono_segmenti_diversi(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    c = ClientTratte({0: [_seg(10, "S1", "S2")], 1: [_seg(10, "S8", "S9")]})
    esito = await carica_tratte(conn, _c(c), [0, 1])
    assert esito == {0: 1, 1: 1}
    righe = conn.execute(
        "SELECT regione_codice, nodo_a FROM tratte ORDER BY regione_codice"
    ).fetchall()
    assert [tuple(r) for r in righe] == [(0, "S1"), (1, "S8")]


async def test_non_scarica_i_treni_ne_scrive_osservazioni(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    c = ClientTratte({1: [_seg(1), _seg(3)]})
    await carica_tratte(conn, _c(c), [1])
    assert c.dettagli == 0
    for tabella in ("treni", "tratte_osservazioni", "avvistamenti_tratta"):
        assert conn.execute(f"SELECT COUNT(*) FROM {tabella}").fetchone()[0] == 0


async def test_una_regione_che_fallisce_non_ferma_le_altre(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    c = ClientTratte({0: [_seg(1)], 2: [_seg(5)]}, falliscono={1})
    esito = await carica_tratte(conn, _c(c), [0, 1, 2])
    assert esito[0] == 1 and esito[2] == 1 and esito[1] == "errore: 403"
    assert conn.execute("SELECT COUNT(*) FROM tratte").fetchone()[0] == 2


async def test_rilanciarlo_aggiorna_senza_duplicare(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    await carica_tratte(conn, _c(ClientTratte({1: [_seg(1, "S1", "S2")]})), [1])
    await carica_tratte(conn, _c(ClientTratte({1: [_seg(1, "S1", "S7")]})), [1])
    righe = conn.execute("SELECT nodo_b FROM tratte").fetchall()
    assert [r[0] for r in righe] == ["S7"]


async def test_i_segmenti_sono_salvati_per_regione_anche_se_un_giro_poi_fallisce(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    c = ClientTratte({0: [_seg(1)]}, falliscono={1})
    await carica_tratte(conn, _c(c), [0, 1])
    conn.rollback()  # cio' che non e' stato committato sparisce: la regione 0 deve restare
    assert conn.execute("SELECT COUNT(*) FROM tratte").fetchone()[0] == 1


def test_la_cli_ha_il_sottocomando(tmp_path, monkeypatch):
    visto = {}

    async def finto(db_path, regioni, **kw):
        visto.update(db_path=db_path, regioni=regioni, **kw)
        return 0

    monkeypatch.setattr("viaggiatreno_crawler.__main__.run_tratte", finto)
    with pytest.raises(SystemExit) as e:
        main(["tratte", "--db-path", "x.db", "--regione", "0", "--regione", "5"])
    assert e.value.code == 0
    assert visto["regioni"] == [0, 5] and visto["db_path"] == "x.db"


def test_la_cli_esce_con_1_se_una_regione_fallisce(monkeypatch):
    async def finto(*a, **kw):
        return 2

    monkeypatch.setattr("viaggiatreno_crawler.__main__.run_tratte", finto)
    with pytest.raises(SystemExit) as e:
        main(["tratte"])
    assert e.value.code == 1
