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
