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


# ------------------------------------------------------------------ cod_destinazione e ordine delle fermate


def _fermata(stop, tipo, att=1, orario=None, eff=None, rit=0):
    return {
        "stop_id": stop,
        "tipo_fermata": tipo,
        "actual_fermata_type": att,
        "orario_programmato": orario,
        "orario_effettivo": eff,
        "ritardo": rit,
    }


def test_riscoperta_senza_codice_non_cancella_cod_destinazione(tmp_path):
    """Un tabellone delle partenze da' solo il nome della destinazione: il codice noto resta."""
    conn = storage.connect(tmp_path / "t.db")
    k = {"numero_treno": 7, "cod_origine": "S1", "data_partenza_treno": 1000}
    storage.upsert_treno(conn, **k, cod_destinazione="S9", destinazione="NOVE")
    storage.upsert_treno(conn, **k, destinazione="NOVE")  # riscoperta: codice assente
    assert conn.execute("SELECT cod_destinazione FROM treni").fetchone()[0] == "S9"


def test_un_codice_nuovo_sostituisce_quello_vecchio(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    k = {"numero_treno": 7, "cod_origine": "S1", "data_partenza_treno": 1000}
    storage.upsert_treno(conn, **k, cod_destinazione="S9")
    storage.upsert_treno(conn, **k, cod_destinazione="S5")  # es. treno limitato a una fermata prima
    assert conn.execute("SELECT cod_destinazione FROM treni").fetchone()[0] == "S5"


def test_ricava_destinazione_usa_l_ultima_fermata_non_soppressa(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    for s in ("S1", "S2", "S3"):
        storage.upsert_stop(conn, s, f"STAZ {s}", 45.0, 9.0)
    tid = storage.upsert_treno(conn, numero_treno=1, cod_origine="S1", data_partenza_treno=1000)
    storage.sostituisci_fermate(
        conn,
        tid,
        [_fermata("S1", "P"), _fermata("S2", "F"), _fermata("S3", "", att=3)],  # S3 soppressa
    )
    assert storage.ricava_destinazione(conn) == 1
    assert conn.execute("SELECT cod_destinazione FROM treni").fetchone()[0] == "S2"


def test_ricava_destinazione_non_tocca_i_valori_presenti_ne_i_treni_senza_fermate(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.upsert_stop(conn, "S2", "DUE", 45.0, 9.0)
    a = storage.upsert_treno(
        conn, numero_treno=1, cod_origine="S1", data_partenza_treno=1, cod_destinazione="S7"
    )
    storage.sostituisci_fermate(conn, a, [_fermata("S1", "P"), _fermata("S2", "A")])
    storage.upsert_treno(
        conn, numero_treno=2, cod_origine="S1", data_partenza_treno=1
    )  # senza fermate
    assert storage.ricava_destinazione(conn) == 0
    righe = dict(conn.execute("SELECT numero_treno, cod_destinazione FROM treni").fetchall())
    assert righe == {1: "S7", 2: None}


def test_ricava_destinazione_e_idempotente(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.upsert_stop(conn, "S2", "DUE", 45.0, 9.0)
    tid = storage.upsert_treno(conn, numero_treno=1, cod_origine="S1", data_partenza_treno=1)
    storage.sostituisci_fermate(conn, tid, [_fermata("S1", "P"), _fermata("S2", "A")])
    assert storage.ricava_destinazione(conn) == 1
    assert storage.ricava_destinazione(conn) == 0


def test_ripara_arrivi_persi_non_dipende_dal_progressivo(tmp_path):
    """Il progressivo e' ripetuto o non crescente in alcuni treni: vale l'ordine di inserimento."""
    conn = storage.connect(tmp_path / "t.db")
    for s in ("S1", "S2"):
        storage.upsert_stop(conn, s, s, 45.0, 9.0)
    tid = storage.upsert_treno(conn, numero_treno=1, cod_origine="S1", data_partenza_treno=1)
    conn.execute(
        "INSERT INTO fermate (treno_id, stop_id, progressivo, tipo_fermata, orario_effettivo, "
        "ritardo, actual_fermata_type) VALUES (?, ?, ?, ?, ?, ?, 1)",
        (tid, "S1", 9, "A", 1000, 3),  # prima, progressivo alto
    )
    conn.execute(
        "INSERT INTO fermate (treno_id, stop_id, progressivo, tipo_fermata, orario_effettivo, "
        "ritardo, actual_fermata_type) VALUES (?, ?, ?, ?, ?, ?, 1)",
        (tid, "S2", 1, "A", 2000, 8),  # dopo, progressivo basso: e' l'ultima inserita
    )
    storage.ripara_arrivi_persi(conn)
    assert conn.execute("SELECT ritardo_finale FROM treni").fetchone()[0] == 8


def test_ricava_orario_partenza_non_dipende_dal_progressivo(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.upsert_stop(conn, "S1", "UNO", 45.0, 9.0)
    tid = storage.upsert_treno(conn, numero_treno=1, cod_origine="S1", data_partenza_treno=1)
    conn.execute(
        "INSERT INTO fermate (treno_id, stop_id, progressivo, tipo_fermata, orario_programmato) "
        "VALUES (?, 'S1', 9, 'P', 500)",
        (tid,),
    )
    conn.execute(
        "INSERT INTO fermate (treno_id, stop_id, progressivo, tipo_fermata, orario_programmato) "
        "VALUES (?, 'S1', 1, 'P', 900)",
        (tid,),
    )
    storage.ricava_orario_partenza(conn)
    assert (
        conn.execute("SELECT orario_partenza FROM treni").fetchone()[0] == 500
    )  # la prima inserita


def test_le_fermate_conservano_arrivo_e_partenza_teorici(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    tid = storage.upsert_treno(
        conn, numero_treno=1, cod_origine="S1", data_partenza_treno=1791064800000
    )
    storage.sostituisci_fermate(
        conn,
        tid,
        [
            {"stop_id": "S1", "orario_programmato": 100, "partenza_teorica": 100},
            {
                "stop_id": "S2",
                "orario_programmato": 200,
                "arrivo_teorico": 200,
                "partenza_teorica": 260,
            },
            {"stop_id": "S3", "orario_programmato": 400, "arrivo_teorico": 400},
        ],
    )
    righe = conn.execute(
        "SELECT stop_id, arrivo_teorico, partenza_teorica FROM fermate ORDER BY id"
    ).fetchall()
    assert [tuple(r) for r in righe] == [("S1", None, 100), ("S2", 200, 260), ("S3", 400, None)]


def test_un_db_senza_le_colonne_teoriche_le_riceve_all_apertura(tmp_path):
    import sqlite3

    db = tmp_path / "vecchio.db"
    storage.connect(db).close()
    c = sqlite3.connect(db)
    c.execute("ALTER TABLE fermate DROP COLUMN arrivo_teorico")
    c.execute("ALTER TABLE fermate DROP COLUMN partenza_teorica")
    c.commit()
    c.close()
    conn = storage.connect(db)
    colonne = {r[1] for r in conn.execute("PRAGMA table_info(fermate)")}
    assert {"arrivo_teorico", "partenza_teorica"} <= colonne


def test_persisti_andamento_salva_gli_orari_teorici_delle_fermate(tmp_path):
    from viaggiatreno import TrainStatus
    from viaggiatreno_crawler.poller import persisti_andamento

    conn = storage.connect(tmp_path / "t.db")
    for s in ("S1", "S2", "S3"):
        storage.registra_stop_se_nuovo(conn, s, s, "test")
    storage.upsert_treno(conn, numero_treno=7, cod_origine="S1", data_partenza_treno=1000)
    row = conn.execute("SELECT * FROM treni").fetchone()

    def f(sid, tipo, prog, **kw):
        return {"stazione": sid, "id": sid, "tipoFermata": tipo, "progressivo": prog, **kw}

    status = TrainStatus.model_validate(
        {
            "numeroTreno": 7,
            "tipoTreno": "PG",
            "provvedimento": 0,
            "fermate": [
                f("S1", "P", 1, programmata=100, partenza_teorica=100),
                f("S2", "F", 2, programmata=200, arrivo_teorico=200, partenza_teorica=260),
                f("S3", "A", 3, programmata=400, arrivo_teorico=400),
            ],
        }
    )
    persisti_andamento(conn, row, status)
    righe = conn.execute(
        "SELECT stop_id, arrivo_teorico, partenza_teorica FROM fermate ORDER BY id"
    ).fetchall()
    assert [tuple(r) for r in righe] == [("S1", None, 100), ("S2", 200, 260), ("S3", 400, None)]
