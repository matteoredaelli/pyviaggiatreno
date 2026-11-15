# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test delle viste SQL (`viste.py`) con un DB piccolo e valori calcolati a mano."""

import sqlite3

import pytest
from viaggiatreno_crawler import storage, viste

# Mezzanotte locale del 12/11/2026 (CET, UTC+1) e del 13/11/2026, come le da' l'API
G1 = 1_794_438_000_000
G2 = G1 + 86_400_000


def _db(tmp_path):
    conn = storage.connect(tmp_path / "v.db")
    for s, nome in (
        ("S1", "UNO"),
        ("S2", "DUE"),
        ("S3", "TRE"),
        ("S4", "QUATTRO"),
        ("S5", "CINQUE"),
    ):
        storage.upsert_stop(conn, s, nome, 45.0, 9.0, regione_codice=1)
    conn.execute("INSERT OR IGNORE INTO regioni (codice, nome) VALUES (1, 'Lombardia')")
    return conn


def _treno(conn, numero, fermate, *, giorno=G1, cat="REG", cod=63):
    """`fermate`: lista di (stop, tipo_att, bin_prog, bin_eff). tipo_att 3 = soppressa."""
    tid = storage.upsert_treno(
        conn,
        numero_treno=numero,
        cod_origine=fermate[0][0],
        data_partenza_treno=giorno,
        categoria=cat,
        codice_cliente=cod,
    )
    storage.sostituisci_fermate(
        conn,
        tid,
        [
            {
                "stop_id": s,
                "progressivo": 1,  # volutamente uguale: non deve influire sull'ordine
                "actual_fermata_type": att,
                "binario_programmato": bp,
                "binario_effettivo": be,
            }
            for s, att, bp, be in fermate
        ],
    )
    conn.commit()
    return tid


def _vista(conn, sql, *args):
    conn.row_factory = sqlite3.Row
    return conn.execute(sql, args).fetchall()


def _stop(conn, sid):
    return _vista(conn, "SELECT * FROM v_stops WHERE stop_id = ?", sid)[0]


# ------------------------------------------------------------------ creazione


def test_le_viste_si_creano_su_un_db_vuoto_e_si_interrogano(tmp_path):
    conn = _db(tmp_path)
    assert viste.aggiorna_viste(conn) is True
    for nome in viste.VISTE:
        conn.execute(f"SELECT * FROM {nome}").fetchall()
    r = _stop(conn, "S1")
    assert (r["n_corse"], r["n_binari"], r["capolinea"], r["transito"]) == (0, 0, 0, 0)


def test_aggiorna_viste_non_riscrive_se_la_versione_e_invariata(tmp_path):
    conn = _db(tmp_path)
    assert viste.aggiorna_viste(conn) is True
    assert viste.aggiorna_viste(conn) is False
    assert viste.aggiorna_viste(conn, forza=True) is True


def test_se_una_vista_manca_vengono_ricreate_tutte(tmp_path):
    conn = _db(tmp_path)
    viste.aggiorna_viste(conn)
    conn.execute("DROP VIEW v_stop_binari")
    assert viste.aggiorna_viste(conn) is True
    conn.execute("SELECT * FROM v_stop_binari").fetchall()


def test_una_definizione_cambiata_ricrea_le_viste(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    viste.aggiorna_viste(conn)
    vecchia = viste.versione()
    monkeypatch.setitem(viste.VISTE, "v_treno", viste.VISTE["v_treno"] + "\n-- modificata")
    assert viste.versione() != vecchia
    assert viste.aggiorna_viste(conn) is True


def test_crea_viste_e_atomica_se_una_fallisce(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    viste.aggiorna_viste(conn)
    monkeypatch.setitem(
        viste.VISTE, "v_stops", "CREATE VIEW v_stops AS SELEC 1"
    )  # errore di sintassi
    with pytest.raises(sqlite3.OperationalError):
        viste.crea_viste(conn)
    # la transazione e' annullata: le viste di prima ci sono ancora
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")} == set(
        viste.VISTE
    )


def test_le_viste_non_scrivono_sui_dati(tmp_path):
    conn = _db(tmp_path)
    _treno(conn, 1, [("S1", 1, "1", None), ("S2", 1, "2", None)])
    prima = (
        conn.execute("SELECT COUNT(*) FROM treni").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM fermate").fetchone()[0],
    )
    viste.aggiorna_viste(conn)
    for nome in viste.VISTE:
        conn.execute(f"SELECT * FROM {nome}").fetchall()
    assert (
        conn.execute("SELECT COUNT(*) FROM treni").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM fermate").fetchone()[0],
    ) == prima


# ------------------------------------------------------------------ v_treno


def test_v_treno_origine_e_destinazione_effettive_saltano_le_soppresse(tmp_path):
    conn = _db(tmp_path)
    _treno(conn, 1, [("S1", 1, None, None), ("S2", 1, None, None), ("S3", 3, None, None)])
    viste.aggiorna_viste(conn)
    (r,) = _vista(conn, "SELECT * FROM v_treno")
    assert (r["origine_effettiva"], r["destinazione_effettiva"]) == ("S1", "S2")
    assert (r["n_fermate"], r["n_soppresse"], r["parziale"]) == (3, 1, 1)


def test_v_treno_usa_l_ordine_di_inserimento_non_il_progressivo(tmp_path):
    conn = _db(tmp_path)
    tid = _treno(conn, 1, [("S1", 1, None, None), ("S2", 1, None, None), ("S3", 1, None, None)])
    conn.execute("UPDATE fermate SET progressivo = 9 WHERE stop_id = 'S1'")  # S1 prima ma 9
    conn.execute("UPDATE fermate SET progressivo = 1 WHERE stop_id = 'S3'")
    viste.aggiorna_viste(conn)
    (r,) = _vista(conn, "SELECT * FROM v_treno WHERE treno_id = ?", tid)
    assert (r["origine_effettiva"], r["destinazione_effettiva"]) == ("S1", "S3")


def test_v_treno_senza_fermate_ha_origine_e_destinazione_null(tmp_path):
    conn = _db(tmp_path)
    storage.upsert_treno(conn, numero_treno=9, cod_origine="S1", data_partenza_treno=G1)
    conn.commit()
    viste.aggiorna_viste(conn)
    (r,) = _vista(conn, "SELECT * FROM v_treno")
    assert (r["origine_effettiva"], r["destinazione_effettiva"], r["n_fermate"]) == (None, None, 0)


def test_il_giorno_e_la_data_locale_della_mezzanotte_locale(tmp_path):
    conn = _db(tmp_path)
    # 12/11 in orario solare (UTC+1): mezzanotte locale = 11/11 23:00 UTC
    _treno(conn, 1, [("S1", 1, None, None), ("S2", 1, None, None)], giorno=G1)
    # 12/07 in orario legale (UTC+2): mezzanotte locale = 11/07 22:00 UTC
    legale = 1_783_634_400_000
    _treno(conn, 2, [("S1", 1, None, None), ("S2", 1, None, None)], giorno=legale)
    viste.aggiorna_viste(conn)
    giorni = dict(conn.execute("SELECT numero_treno, giorno FROM v_treno").fetchall())
    assert giorni == {1: "2026-11-12", 2: "2026-07-10"}


# ------------------------------------------------------------------ v_stops: ruoli, corse, destinazioni


def _scenario(tmp_path):
    """S1 -> S2 -> S3 (due treni, uno per verso) e S1 -> S2 -> S4 (un treno): S2 e' di transito."""
    conn = _db(tmp_path)
    _treno(conn, 1, [("S1", 1, "1", None), ("S2", 1, "2", "2"), ("S3", 1, "3", None)])
    _treno(conn, 2, [("S3", 1, "1", None), ("S2", 1, "1", "4"), ("S1", 1, "2", None)])
    _treno(conn, 3, [("S1", 1, "1", None), ("S2", 1, "2", None), ("S4", 1, "5", None)], giorno=G2)
    viste.aggiorna_viste(conn)
    return conn


def test_v_stops_capolinea_e_transito(tmp_path):
    conn = _scenario(tmp_path)
    s1, s2, s3 = (_stop(conn, x) for x in ("S1", "S2", "S3"))
    # S1: nasce (1, 3) e finisce (2) -> capolinea, non transito
    assert (s1["n_nascono"], s1["n_finiscono"], s1["n_passano"]) == (2, 1, 0)
    assert (s1["capolinea"], s1["transito"]) == (1, 0)
    # S2: passano tutti e 3
    assert (s2["n_nascono"], s2["n_finiscono"], s2["n_passano"]) == (0, 0, 3)
    assert (s2["capolinea"], s2["transito"]) == (0, 1)
    # S3: nasce (2) e finisce (1)
    assert (s3["n_nascono"], s3["n_finiscono"]) == (1, 1)


def test_v_stops_una_stazione_puo_essere_capolinea_e_di_transito(tmp_path):
    conn = _db(tmp_path)
    _treno(conn, 1, [("S1", 1, None, None), ("S2", 1, None, None)])  # nasce a S1
    _treno(conn, 2, [("S5", 1, None, None), ("S1", 1, None, None), ("S2", 1, None, None)])  # passa
    viste.aggiorna_viste(conn)
    s1 = _stop(conn, "S1")
    assert (s1["capolinea"], s1["transito"]) == (1, 1)


def test_v_stops_corse_numeri_e_destinazioni(tmp_path):
    conn = _scenario(tmp_path)
    s2 = _stop(conn, "S2")
    assert (s2["n_corse"], s2["n_numeri"], s2["n_giorni"]) == (3, 3, 2)
    # destinazioni finali dei treni che passano da S2: S3, S1, S4
    assert s2["n_destinazioni"] == 3 and s2["n_origini"] == 2  # origini: S1 e S3
    assert (s2["primo_giorno"], s2["ultimo_giorno"]) == ("2026-11-12", "2026-11-13")


def test_v_stops_la_destinazione_della_stazione_stessa_non_conta(tmp_path):
    conn = _scenario(tmp_path)
    s3 = _stop(conn, "S3")
    # per S3 i treni che toccano sono 1 (finisce qui) e 2 (nasce qui, va a S1)
    assert s3["n_destinazioni"] == 1  # solo S1: il treno 1 finisce a S3, non e' una destinazione


def test_v_stops_stesso_numero_in_giorni_diversi_conta_una_volta_tra_i_numeri(tmp_path):
    conn = _db(tmp_path)
    _treno(conn, 7, [("S1", 1, None, None), ("S2", 1, None, None)], giorno=G1)
    _treno(conn, 7, [("S1", 1, None, None), ("S2", 1, None, None)], giorno=G2)
    viste.aggiorna_viste(conn)
    s1 = _stop(conn, "S1")
    assert (s1["n_corse"], s1["n_numeri"], s1["n_giorni"]) == (2, 1, 2)


def test_v_stops_un_treno_parzialmente_soppresso_non_rende_capolinea(tmp_path):
    conn = _db(tmp_path)
    # S1 -> S2 -> S3, con S3 soppressa: il treno finisce a S2 per la soppressione
    _treno(conn, 1, [("S1", 1, None, None), ("S2", 1, None, None), ("S3", 3, None, None)])
    viste.aggiorna_viste(conn)
    s1, s2, s3 = (_stop(conn, x) for x in ("S1", "S2", "S3"))
    assert (s1["capolinea"], s2["capolinea"]) == (0, 0)
    assert (s1["n_incerti"], s2["n_incerti"]) == (1, 1)
    assert s3["n_corse"] == 0 and s3["n_corse_soppresse"] == 1  # soppressa: non e' una corsa


def test_v_stops_conta_le_corse_soppresse_a_parte(tmp_path):
    conn = _db(tmp_path)
    _treno(conn, 1, [("S1", 1, None, None), ("S2", 3, None, None), ("S3", 1, None, None)])
    viste.aggiorna_viste(conn)
    s2 = _stop(conn, "S2")
    assert (s2["n_corse"], s2["n_corse_soppresse"]) == (0, 1)


def test_v_stops_stazione_senza_treni_ha_zeri_e_anagrafica(tmp_path):
    conn = _scenario(tmp_path)
    r = _stop(conn, "S5")
    assert (r["stop_name"], r["regione_nome"], r["n_corse"], r["n_binari"]) == (
        "CINQUE",
        "Lombardia",
        0,
        0,
    )
    assert r["primo_giorno"] is None


# ------------------------------------------------------------------ binari


def test_v_stops_binari_sono_l_unione_di_programmati_ed_effettivi(tmp_path):
    conn = _scenario(tmp_path)
    s2 = _stop(conn, "S2")
    # programmati: 2, 1, 2 -> {1, 2}; effettivi: 2, 4 -> {2, 4}; unione {1, 2, 4}
    assert (s2["n_binari_programmati"], s2["n_binari_effettivi"], s2["n_binari"]) == (2, 2, 3)


def test_v_stop_binari_conta_le_corse_per_binario(tmp_path):
    conn = _scenario(tmp_path)
    righe = {
        r["binario"]: r for r in _vista(conn, "SELECT * FROM v_stop_binari WHERE stop_id = 'S2'")
    }
    assert set(righe) == {"1", "2", "4"}
    assert (righe["2"]["n_corse"], righe["2"]["n_programmato"], righe["2"]["n_reale"]) == (2, 2, 1)
    # il treno 2 era previsto sul 1 ed e' andato sul 4: cambiato
    assert righe["1"]["n_cambiati"] == 1 and righe["4"]["n_cambiati"] == 1
    assert righe["2"]["n_cambiati"] == 0


def test_v_stop_binari_un_binario_uguale_programmato_ed_effettivo_conta_una_volta(tmp_path):
    conn = _db(tmp_path)
    _treno(conn, 1, [("S1", 1, "3", "3"), ("S2", 1, None, None)])
    viste.aggiorna_viste(conn)
    (r,) = _vista(conn, "SELECT * FROM v_stop_binari WHERE stop_id = 'S1'")
    assert (r["binario"], r["n_corse"], r["n_programmato"], r["n_reale"], r["n_cambiati"]) == (
        "3",
        1,
        1,
        1,
        0,
    )
    assert _stop(conn, "S1")["n_binari"] == 1


def test_le_fermate_soppresse_non_danno_binari(tmp_path):
    conn = _db(tmp_path)
    _treno(conn, 1, [("S1", 1, "1", None), ("S2", 3, "7", None), ("S3", 1, "2", None)])
    viste.aggiorna_viste(conn)
    assert _stop(conn, "S2")["n_binari"] == 0
    assert _vista(conn, "SELECT * FROM v_stop_binari WHERE stop_id = 'S2'") == []


# ------------------------------------------------------------------ v_stops_giorno


def test_v_stops_giorno_separa_i_giorni(tmp_path):
    conn = _scenario(tmp_path)
    r = {x["giorno"]: x for x in _vista(conn, "SELECT * FROM v_stops_giorno WHERE stop_id = 'S2'")}
    assert set(r) == {"2026-11-12", "2026-11-13"}
    assert (r["2026-11-12"]["n_corse"], r["2026-11-13"]["n_corse"]) == (2, 1)
    assert r["2026-11-12"]["n_binari"] == 3 and r["2026-11-13"]["n_binari"] == 1  # {1,2,4} e {2}
    assert r["2026-11-12"]["n_destinazioni"] == 2  # S3 e S1
    assert sum(x["n_corse"] for x in r.values()) == _stop(conn, "S2")["n_corse"]


# ------------------------------------------------------------------ v_fermata


def test_v_fermata_ruolo_e_binario_cambiato(tmp_path):
    conn = _scenario(tmp_path)
    ruoli = {
        (r["numero_treno"], r["stop_id"]): r["ruolo"]
        for r in _vista(conn, "SELECT * FROM v_fermata")
    }
    assert (
        ruoli[(1, "S1")] == "origina"
        and ruoli[(1, "S2")] == "passa"
        and ruoli[(1, "S3")] == "termina"
    )
    cambiato = {
        r["numero_treno"]: r["binario_cambiato"]
        for r in _vista(conn, "SELECT * FROM v_fermata WHERE stop_id = 'S2'")
    }
    assert cambiato == {1: 0, 2: 1, 3: 0}


def test_v_fermata_marca_le_soppresse(tmp_path):
    conn = _db(tmp_path)
    _treno(conn, 1, [("S1", 1, None, None), ("S2", 3, None, None), ("S3", 1, None, None)])
    viste.aggiorna_viste(conn)
    ruoli = {
        r["stop_id"]: (r["soppressa"], r["ruolo"]) for r in _vista(conn, "SELECT * FROM v_fermata")
    }
    assert ruoli["S2"] == (1, "soppressa") and ruoli["S1"] == (0, "origina")
