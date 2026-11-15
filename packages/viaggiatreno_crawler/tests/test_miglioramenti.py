# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test: verifica anticipata, 204, raw_json compatto, pulizia, errori per segmento."""

import json
import sqlite3
from types import SimpleNamespace
from typing import cast

import pytest
from viaggiatreno import TrainStatus, ViaggiaTrenoClient
from viaggiatreno.insights import ha_anomalie
from viaggiatreno_crawler import storage
from viaggiatreno_crawler.__main__ import parse_args_eventi
from viaggiatreno_crawler.config import ConfigEventi
from viaggiatreno_crawler.poller import (
    _orario_int,
    raw_json_per,
    scopri_treni,
)

ORA = 1_800_000_000_000  # istante di riferimento fisso, in ms
MIN = 60_000


def _treno(conn, numero, partenza, **kw):
    return storage.upsert_treno(
        conn,
        numero_treno=numero,
        cod_origine="S00001",
        data_partenza_treno=1,
        orario_partenza=partenza,
        **kw,
    )


# ============================================================ 2) verifica anticipata


def test_orario_int_scarta_le_stringhe_di_dettagli_tratta():
    assert _orario_int(1793746800000) == 1793746800000
    assert _orario_int("2026-11-04") is None  # dettagliTratta: solo la data
    assert _orario_int(None) is None
    assert _orario_int(True) is None


# ============================================================ 4) i 204


def test_un_204_prima_della_partenza_non_conta(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    tid = _treno(conn, 1, ORA + 60 * MIN)
    for _ in range(20):
        assert storage.registra_204(conn, tid, soglia=5, ora_ms=ORA) == "atteso"
    r = conn.execute("SELECT stato, tentativi_204, chiusura_motivo FROM treni").fetchone()
    assert (r["stato"], r["tentativi_204"], r["chiusura_motivo"]) == ("in_corso", 0, None)


def test_i_204_dopo_la_partenza_chiudono_alla_soglia_con_motivo(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    tid = _treno(conn, 1, ORA - 30 * MIN)
    esiti = [storage.registra_204(conn, tid, soglia=3, ora_ms=ORA) for _ in range(3)]
    assert esiti == ["contato", "contato", "chiuso"]
    r = conn.execute("SELECT stato, tentativi_204, chiusura_motivo FROM treni").fetchone()
    assert (r["stato"], r["tentativi_204"], r["chiusura_motivo"]) == ("non_disponibile", 3, "204")


def test_senza_orario_noto_il_204_si_conta_come_prima(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    tid = _treno(conn, 1, None)
    assert storage.registra_204(conn, tid, soglia=2, ora_ms=ORA) == "contato"
    assert storage.registra_204(conn, tid, soglia=2, ora_ms=ORA) == "chiuso"


def test_un_nuovo_orario_dalla_riscoperta_non_viene_perso_ne_azzerato(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    tid = _treno(conn, 1, 12345)
    storage.upsert_treno(conn, numero_treno=1, cod_origine="S00001", data_partenza_treno=1)
    assert (
        conn.execute("SELECT orario_partenza FROM treni WHERE id=?", (tid,)).fetchone()[0] == 12345
    )


# ============================================================ 3) raw_json compatto


def _status(**extra) -> TrainStatus:
    base = {
        "numeroTreno": 1,
        "tipoTreno": "PG",
        "provvedimento": 0,
        "orarioPartenza": 100,
        "fermate": [
            {
                "stazione": "A",
                "id": "S1",
                "tipoFermata": "P",
                "progressivo": 1,
                "actualFermataType": 1,
            },
            {
                "stazione": "B",
                "id": "S2",
                "tipoFermata": "A",
                "progressivo": 2,
                "actualFermataType": 1,
            },
        ],
    }
    return TrainStatus.model_validate({**base, **extra})


def test_treno_regolare_raw_json_senza_fermate_ed_e_piu_piccolo():
    s = _status()
    assert ha_anomalie(s) is False
    compatto = json.loads(raw_json_per(s, False))
    assert "fermate" not in compatto
    assert compatto["numeroTreno"] == 1
    assert len(raw_json_per(s, False)) < len(json.dumps(s.model_dump(mode="json")))


@pytest.mark.parametrize(
    "extra",
    [
        {"tipoTreno": "PP"},
        {"tipoTreno": "DV"},
        {"provvedimento": 2},
        {"riprogrammazione": "Y"},
        {"subTitle": "Treno limitato a Monza"},
        {"fermateSoppresse": [{"id": "S2"}]},
        {"cambiNumero": [{"numero": 2}]},
    ],
)
def test_le_anomalie_conservano_il_raw_json_completo(extra):
    s = _status(**extra)
    assert ha_anomalie(s) is True
    assert "fermate" in json.loads(raw_json_per(s, False))


def test_fermata_soppressa_e_un_anomalia():
    s = _status(fermate=[{"stazione": "A", "id": "S1", "tipoFermata": "P", "actualFermataType": 3}])
    assert ha_anomalie(s) is True


def test_flag_raw_json_completo_salva_sempre_tutto():
    assert "fermate" in json.loads(raw_json_per(_status(), True))
    assert parse_args_eventi(["eventi", "--raw-json-completo"]).raw_json_completo is True
    assert parse_args_eventi(["eventi"]).raw_json_completo is False


def test_compatta_raw_json_storico_tocca_solo_i_regolari_arrivati(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    pieno = json.dumps(_status().model_dump(mode="json"))
    anomalo = json.dumps(_status(tipoTreno="PP").model_dump(mode="json"))
    a = _treno(conn, 1, None, stato="arrivato", raw_json=pieno)
    b = _treno(conn, 2, None, stato="arrivato", raw_json=anomalo)
    c = _treno(conn, 3, None, stato="in_corso", raw_json=pieno)
    d = _treno(conn, 4, None, stato="arrivato", raw_json=pieno)
    storage.sostituisci_fermate(  # una fermata non effettuata rende anomalo anche il "regolare"
        conn, d, [{"stop_id": "S1", "actual_fermata_type": 3}]
    )
    n, _ = storage.compatta_raw_json(conn)
    assert n == 1
    raw = {
        r["id"]: json.loads(r["raw_json"]) for r in conn.execute("SELECT id, raw_json FROM treni")
    }
    assert "fermate" not in raw[a]
    assert "fermate" in raw[b] and "fermate" in raw[c] and "fermate" in raw[d]
    assert storage.compatta_raw_json(conn)[0] == 0  # idempotente


# ============================================================ 5) pulizia avvistamenti


def test_pulisci_avvistamenti_cancella_solo_i_vecchi(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    tid = _treno(conn, 1, None)
    giorno = 86_400_000
    for eta_giorni in (1, 6, 8, 30):
        conn.execute(
            "INSERT INTO avvistamenti_tratta (treno_id, regione_codice, tratta_ab, tratta_ba, ts_poll)"
            " VALUES (?, 1, 5, 87, ?)",
            (tid, ORA - eta_giorni * giorno),
        )
    cancellate = storage.pulisci_avvistamenti_tratta(conn, giorni_da_tenere=7, ora_ms=ORA)
    assert cancellate == 2
    assert conn.execute("SELECT COUNT(*) FROM avvistamenti_tratta").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM treni").fetchone()[0] == 1  # i treni non si toccano


# ============================================================ migrazione DB esistente


def test_connect_aggiunge_le_colonne_nuove_a_un_db_vecchio(tmp_path):
    percorso = tmp_path / "vecchio.db"
    vecchio = sqlite3.connect(percorso)
    vecchio.executescript(
        """CREATE TABLE treni (id INTEGER PRIMARY KEY AUTOINCREMENT, numero_treno INTEGER NOT NULL,
           cod_origine TEXT NOT NULL, data_partenza_treno INTEGER NOT NULL, categoria TEXT,
           cod_destinazione TEXT, origine TEXT, destinazione TEXT, codice_cliente INTEGER,
           stato TEXT NOT NULL DEFAULT 'in_corso', ritardo_corrente INTEGER, ritardo_finale INTEGER,
           tentativi_204 INTEGER NOT NULL DEFAULT 0, primo_avvistamento INTEGER NOT NULL,
           ultimo_aggiornamento INTEGER NOT NULL, raw_json TEXT, route_id TEXT, trip_id TEXT,
           UNIQUE (numero_treno, cod_origine, data_partenza_treno));
           INSERT INTO treni (numero_treno, cod_origine, data_partenza_treno, primo_avvistamento,
                              ultimo_aggiornamento) VALUES (7, 'S1', 1, 0, 0);"""
    )
    vecchio.commit()
    vecchio.close()
    conn = storage.connect(percorso)
    colonne = {r[1] for r in conn.execute("PRAGMA table_info(treni)")}
    assert {"orario_partenza", "chiusura_motivo"} <= colonne
    assert conn.execute("SELECT numero_treno, orario_partenza FROM treni").fetchone()[:] == (
        7,
        None,
    )
    storage.connect(percorso).close()  # idempotente: una seconda apertura non fallisce


def test_ricava_orario_partenza_da_fermate_e_da_tabellone(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    verificato = _treno(conn, 1, None)
    storage.sostituisci_fermate(
        conn,
        verificato,
        [{"stop_id": "S1", "tipo_fermata": "P", "orario_programmato": 555, "progressivo": 1}],
    )
    da_tabellone = _treno(conn, 2, None, raw_json=json.dumps({"orarioPartenza": 777}))
    solo_data = _treno(conn, 3, None, raw_json=json.dumps({"orarioPartenza": "2026-11-04"}))
    assert storage.ricava_orario_partenza(conn) == 2  # non 3: la terza e' solo una data
    val = {
        r["id"]: r["orario_partenza"] for r in conn.execute("SELECT id, orario_partenza FROM treni")
    }
    assert val == {verificato: 555, da_tabellone: 777, solo_data: None}
    assert storage.ricava_orario_partenza(conn) == 0  # idempotente


# ============================================================ 1) errore su un segmento


class ClientTratte:
    """Tre segmenti occupati: il secondo fallisce con un errore (es. 403 dopo i retry)."""

    async def elenco_tratte(self, **kw):
        return [
            SimpleNamespace(
                trattaAB=i,
                trattaBA=i + 100,
                nodoA="A",
                nodoB="B",
                latitudineA=0,
                longitudineA=0,
                latitudineB=0,
                longitudineB=0,
                parentAB=None,
                parentBA=None,
                occupata=True,
            )
            for i in (1, 2, 3)
        ]

    async def dettagli_tratta(self, ab, ba, **kw):
        if ab == 2:
            raise RuntimeError("403 Forbidden")
        treno = SimpleNamespace(
            numeroTreno=ab * 10,
            codOrigine="S00001",
            dataPartenzaTreno=1,
            categoria="REG",
            codDestinazione=None,
            origine=None,
            destinazione=None,
            codiceCliente=63,
            ritardo=0,
            orarioPartenza="2026-11-04",
            model_dump_json=lambda: "{}",
        )
        return [SimpleNamespace(treni=[treno], tratta=None)]


@pytest.mark.asyncio
async def test_un_errore_su_un_segmento_non_interrompe_il_giro(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    n = await scopri_treni(conn, cast(ViaggiaTrenoClient, ClientTratte()), ConfigEventi())
    assert n == 2  # i segmenti 1 e 3 sono stati letti nonostante l'errore sul 2
    assert {r[0] for r in conn.execute("SELECT numero_treno FROM treni")} == {10, 30}
    # tutti e tre i segmenti hanno comunque la loro osservazione di occupazione
    assert conn.execute("SELECT COUNT(*) FROM tratte_osservazioni").fetchone()[0] == 3
