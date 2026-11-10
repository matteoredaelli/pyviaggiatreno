# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test unitari per lo schema SQLite e le query di aggregazione del crawler."""

from viaggiatreno_crawler import storage


def test_connect_crea_schema(tmp_path):
    conn = storage.connect(tmp_path / "test.db")
    tabelle = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "regioni",
        "stops",
        "treni",
        "fermate",
        "tratte",
        "tratte_osservazioni",
        "avvistamenti_tratta",
    } <= tabelle


def test_upsert_treno_e_dedup(tmp_path):
    conn = storage.connect(tmp_path / "test.db")
    id1 = storage.upsert_treno(
        conn,
        numero_treno=9611,
        cod_origine="S00219",
        data_partenza_treno=1791064800000,
        categoria="",
        ritardo_corrente=5,
    )
    id2 = storage.upsert_treno(
        conn,
        numero_treno=9611,
        cod_origine="S00219",
        data_partenza_treno=1791064800000,
        categoria="",
        ritardo_corrente=7,
    )
    assert id1 == id2  # stesso treno (stessa terna) -> stesso id, nessun duplicato
    n = conn.execute("SELECT COUNT(*) AS n FROM treni").fetchone()["n"]
    assert n == 1
    row = conn.execute("SELECT ritardo_corrente FROM treni WHERE id = ?", (id1,)).fetchone()
    assert row["ritardo_corrente"] == 7  # aggiornato dal secondo upsert


def test_fermate_e_kpi_binari(tmp_path):
    conn = storage.connect(tmp_path / "test.db")
    storage.upsert_stop(
        conn, "S01700", "MILANO CENTRALE", 45.48, 9.20, regione_codice=1, citta="Milano"
    )
    treno_id = storage.upsert_treno(
        conn,
        numero_treno=9611,
        cod_origine="S00219",
        data_partenza_treno=1791064800000,
        stato="arrivato",
        ritardo_finale=7,
    )
    storage.sostituisci_fermate(
        conn,
        treno_id,
        [
            {"stop_id": "S01700", "binario_effettivo": "11", "progressivo": 20},
        ],
    )
    binari = storage.binari_per_stazione(conn, "S01700")
    assert len(binari) == 1
    assert binari[0]["binario_effettivo"] == "11"

    traffico = storage.stazioni_per_traffico(conn)
    assert traffico[0]["stop_id"] == "S01700"
    assert traffico[0]["n_treni"] == 1


def test_kpi_giornata_e_mediana(tmp_path):
    conn = storage.connect(tmp_path / "test.db")
    storage.upsert_treno(
        conn,
        numero_treno=1,
        cod_origine="S00219",
        data_partenza_treno=1000,
        stato="arrivato",
        ritardo_finale=10,
    )
    storage.upsert_treno(
        conn,
        numero_treno=2,
        cod_origine="S00219",
        data_partenza_treno=1000,
        stato="arrivato",
        ritardo_finale=0,
    )
    kpi = storage.kpi_giornata(conn, 1000)
    assert kpi["n_treni"] == 2
    assert kpi["n_arrivati"] == 2
    assert kpi["ritardo_medio"] == 5.0

    ritardi = storage.ritardi_arrivati(conn, 1000)
    assert sorted(ritardi) == [0, 10]


def test_tratte_upsert_e_osservazioni(tmp_path):
    conn = storage.connect(tmp_path / "test.db")
    storage.upsert_tratta(
        conn,
        regione_codice=1,
        tratta_ab=5,
        tratta_ba=87,
        nodo_a="S01322",
        nodo_b="S01700",
        lat_a=45.5,
        lon_a=9.1,
        lat_b=45.48,
        lon_b=9.20,
        parent_ab=5,
        parent_ba=87,
    )
    # upsert idempotente: nessun duplicato sulla chiave (regione, trattaAB, trattaBA)
    storage.upsert_tratta(
        conn,
        regione_codice=1,
        tratta_ab=5,
        tratta_ba=87,
        nodo_a="S01322",
        nodo_b="S01700",
        lat_a=45.5,
        lon_a=9.1,
        lat_b=45.48,
        lon_b=9.20,
        parent_ab=5,
        parent_ba=87,
    )
    n = conn.execute("SELECT COUNT(*) AS n FROM tratte").fetchone()["n"]
    assert n == 1

    storage.registra_osservazione_tratta(conn, 1, 5, 87, True)
    storage.registra_osservazione_tratta(conn, 1, 5, 87, False)
    congestione = storage.segmenti_piu_congestionati(conn, regione_codice=1)
    assert len(congestione) == 1
    assert congestione[0]["n_osservazioni"] == 2
    assert congestione[0]["pct_occupata"] == 0.5


def test_avvistamenti_tratta_collega_treno_a_segmento(tmp_path):
    conn = storage.connect(tmp_path / "test.db")
    treno_id = storage.upsert_treno(
        conn,
        numero_treno=9611,
        cod_origine="S00219",
        data_partenza_treno=1791064800000,
    )
    storage.registra_avvistamento_tratta(conn, treno_id, 1, 5, 87)
    row = conn.execute(
        "SELECT * FROM avvistamenti_tratta WHERE treno_id = ?", (treno_id,)
    ).fetchone()
    assert row["regione_codice"] == 1
    assert row["tratta_ab"] == 5
    assert row["tratta_ba"] == 87


def test_importa_stops_gtfs_e_compatibile_e_fa_merge(tmp_path):
    """La tabella `stops` deve accettare un vero file stops.txt del GTFS
    Trenord (stessi nomi colonna) e fare merge con una stazione già nota
    da ViaggiaTreno tramite lo stesso stop_id (vedi TRENORD.md)."""
    conn = storage.connect(tmp_path / "test.db")
    storage.upsert_stop(
        conn, "S01700", "MILANO CENTRALE", 45.486, 9.204, regione_codice=1, fonte="viaggiatreno"
    )

    csv_path = tmp_path / "stops.txt"
    csv_path.write_text(
        "stop_id,stop_name,stop_lat,stop_lon,stop_url\n"
        "S01700,MILANO CENTRALE,45.486347,9.204528,https://trenord.it/stazioni/S01700\n"
        "S01511,CARNATE USMATE,45.653072,9.375089,\n",
        encoding="utf-8",
    )
    n = storage.importa_stops_gtfs(conn, csv_path)
    assert n == 2

    milano = conn.execute("SELECT * FROM stops WHERE stop_id = 'S01700'").fetchone()
    assert milano["stop_url"] == "https://trenord.it/stazioni/S01700"
    assert milano["fonte"] == "viaggiatreno+gtfs_trenord"  # merge delle due fonti
    assert (
        milano["regione_codice"] == 1
    )  # preservato: il GTFS non lo fornisce, non viene sovrascritto a null

    carnate = conn.execute("SELECT * FROM stops WHERE stop_id = 'S01511'").fetchone()
    assert carnate["stop_name"] == "CARNATE USMATE"


def test_riscoperta_non_riapre_un_treno_arrivato(tmp_path):
    """Regressione: scoperta/tabelloni/scan non passano `stato` e scrivevano
    'in_corso' + ritardo_finale NULL sopra l'esito registrato dalla verifica."""
    conn = storage.connect(tmp_path / "test.db")
    k = {"numero_treno": 24825, "cod_origine": "S01520", "data_partenza_treno": 1793746800000}
    storage.upsert_treno(
        conn, **k, stato="arrivato", ritardo_corrente=4, ritardo_finale=4, raw_json="verifica"
    )
    storage.upsert_treno(conn, **k, ritardo_corrente=9, raw_json="tabellone")  # riscoperta

    riga = conn.execute("SELECT * FROM treni").fetchone()
    assert riga["stato"] == "arrivato"
    assert riga["ritardo_finale"] == 4
    assert riga["ritardo_corrente"] == 4
    assert riga["raw_json"] == "verifica"
    assert storage.conta_treni_attivi(conn) == 0


def test_riscoperta_non_riapre_un_treno_soppresso(tmp_path):
    conn = storage.connect(tmp_path / "test.db")
    k = {"numero_treno": 1, "cod_origine": "S00001", "data_partenza_treno": 1000}
    storage.upsert_treno(conn, **k, stato="soppresso")
    storage.upsert_treno(conn, **k)
    assert conn.execute("SELECT stato FROM treni").fetchone()["stato"] == "soppresso"


def test_riscoperta_continua_ad_aggiornare_un_treno_in_corso(tmp_path):
    conn = storage.connect(tmp_path / "test.db")
    k = {"numero_treno": 1, "cod_origine": "S00001", "data_partenza_treno": 1000}
    storage.upsert_treno(conn, **k, ritardo_corrente=2)
    storage.upsert_treno(conn, **k, ritardo_corrente=7)
    assert conn.execute("SELECT ritardo_corrente FROM treni").fetchone()[0] == 7


def test_verifica_puo_ancora_chiudere_un_treno_in_corso(tmp_path):
    conn = storage.connect(tmp_path / "test.db")
    k = {"numero_treno": 1, "cod_origine": "S00001", "data_partenza_treno": 1000}
    storage.upsert_treno(conn, **k)
    storage.upsert_treno(conn, **k, stato="arrivato", ritardo_finale=3)
    riga = conn.execute("SELECT stato, ritardo_finale FROM treni").fetchone()
    assert (riga["stato"], riga["ritardo_finale"]) == ("arrivato", 3)


def test_ripara_arrivi_persi_ricostruisce_stato_e_ritardo_dalle_fermate(tmp_path):
    conn = storage.connect(tmp_path / "test.db")
    storage.upsert_stop(conn, "S01645", "MILANO PORTA GARIBALDI", 45.48, 9.18)
    persi = storage.upsert_treno(
        conn, numero_treno=1, cod_origine="S01520", data_partenza_treno=1000
    )  # riaperto: in_corso, ritardo_finale NULL
    storage.sostituisci_fermate(
        conn,
        persi,
        [
            {
                "stop_id": "S01645",
                "tipo_fermata": "A",
                "progressivo": 15,
                "orario_effettivo": 5,
                "ritardo": 4,
                "actual_fermata_type": 1,
            },
        ],
    )
    in_viaggio = storage.upsert_treno(
        conn, numero_treno=2, cod_origine="S01520", data_partenza_treno=1000
    )
    storage.sostituisci_fermate(
        conn,
        in_viaggio,
        [{"stop_id": "S01645", "tipo_fermata": "A", "progressivo": 15, "actual_fermata_type": 0}],
    )
    soppresso = storage.upsert_treno(
        conn, numero_treno=3, cod_origine="S01520", data_partenza_treno=1000, stato="soppresso"
    )
    storage.sostituisci_fermate(
        conn,
        soppresso,
        [
            {
                "stop_id": "S01645",
                "tipo_fermata": "A",
                "progressivo": 15,
                "orario_effettivo": 5,
                "ritardo": 1,
                "actual_fermata_type": 1,
            }
        ],
    )

    assert storage.ripara_arrivi_persi(conn) == 1

    def stato(i):
        r = conn.execute("SELECT stato, ritardo_finale FROM treni WHERE id=?", (i,)).fetchone()
        return r["stato"], r["ritardo_finale"]

    assert stato(persi) == ("arrivato", 4)
    assert stato(in_viaggio) == ("in_corso", None)  # ultima fermata non ancora effettuata
    assert stato(soppresso) == ("soppresso", None)  # i soppressi non si toccano
    assert storage.ripara_arrivi_persi(conn) == 0  # idempotente
