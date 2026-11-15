# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dal DB del crawler ai profili: devono coincidere con quelli ricavati dall'API."""

import sqlite3

import pytest
from viaggiatreno import TrainStatus
from viaggiatreno.insights import ProfiloTreno, StatoTreno
from viaggiatreno_crawler import storage
from viaggiatreno_crawler.poller import persisti_andamento
from viaggiatreno_sito.db import apri_copia, carica_profili, coordinate_stazioni, iter_profili

GIORNO = 1_799_971_200_000  # 2027-01-15 00:00 UTC
MIN = 60_000


def _f(sid, tipo, prog, att=1, **kw):
    return {
        "stazione": sid.upper(),
        "id": sid,
        "tipoFermata": tipo,
        "progressivo": prog,
        "actualFermataType": att,
        **kw,
    }


def _status(numero=10, fermate=None, **extra) -> TrainStatus:
    base = GIORNO + 8 * 60 * MIN
    fermate = fermate or [
        _f(
            "S1",
            "P",
            1,
            programmata=base,
            partenza_teorica=base,
            binarioProgrammatoPartenzaDescrizione="3",
        ),
        _f(
            "S2",
            "F",
            2,
            programmata=base + 10 * MIN,
            arrivo_teorico=base + 10 * MIN,
            partenza_teorica=base + 12 * MIN,
            binarioProgrammatoArrivoDescrizione="1",
            binarioEffettivoArrivoDescrizione="2",
        ),
        _f("S3", "A", 3, programmata=base + 30 * MIN, arrivo_teorico=base + 30 * MIN),
    ]
    dati = {
        "numeroTreno": numero,
        "tipoTreno": "PG",
        "provvedimento": 0,
        "categoria": "REG",
        "origine": "S1",
        "destinazione": "S3",
        "idOrigine": "S1",
        "idDestinazione": "S3",
        "dataPartenzaTreno": GIORNO,
        "dataPartenzaTrenoAsDate": "2027-01-15",
        "arrivato": True,
        "codiceCliente": 63,
        "fermate": fermate,
        **extra,
    }
    return TrainStatus.model_validate(dati)


def _db(tmp_path, status, *, completo=False, cod_origine="S1"):
    conn = storage.connect(tmp_path / "e.db")
    for f in status.fermate:
        storage.upsert_stop(conn, f.id, f.stazione, 45.0, 9.0)
    storage.upsert_treno(
        conn, numero_treno=status.numeroTreno, cod_origine=cod_origine, data_partenza_treno=GIORNO
    )
    row = conn.execute("SELECT * FROM treni").fetchone()
    from viaggiatreno_crawler.poller import raw_json_per

    persisti_andamento(conn, row, status, None, completo)
    assert raw_json_per  # (importato per chiarezza: e' cio' che salva persisti_andamento)
    conn.commit()
    return conn


def _campi(p: ProfiloTreno):
    return (
        p.numero,
        p.categoria,
        p.operatore,
        p.data,
        p.stato,
        p.avanzamento,
        p.itinerario,
        p.verso,
        p.collegamento_programmato,
        p.collegamento_effettivo,
        p.arrivato,
        [(f.codice, f.nome, f.stato, f.binari, f.programmata) for f in p.fermate],
        [(a.durata_programmata, a.distanza_km) for a in p.archi],
    )


def test_profilo_dal_db_coincide_con_quello_dell_api(tmp_path):
    status = _status()
    conn = _db(tmp_path, status)
    ((_, dal_db),) = iter_profili(conn, coordinate=coordinate_stazioni(conn))
    atteso = ProfiloTreno.da_status(status, coordinate=coordinate_stazioni(conn))
    assert _campi(dal_db) == _campi(atteso)
    assert dal_db.archi[0].durata_programmata == 10.0  # da S1 a S2
    assert dal_db.archi[1].durata_programmata == 18.0  # da S2 (partenza 12') a S3 (arrivo 30')


def test_un_treno_parzialmente_soppresso_resta_tale_dal_raw_json(tmp_path):
    """Un PP senza fermate soppresse e' un'anomalia: il crawler ne salva il raw_json completo, e da
    li' vengono tipo di treno e destinazione effettiva (senza, risulterebbe `regolare`)."""
    status = _status(tipoTreno="PP", idDestinazione="S2", destinazione="S2")
    conn = _db(tmp_path, status)
    assert "tipoTreno" in conn.execute("SELECT raw_json FROM treni").fetchone()[0]
    ((_, dal_db),) = iter_profili(conn)
    atteso = ProfiloTreno.da_status(status)
    assert dal_db.stato is atteso.stato is StatoTreno.PARZIALMENTE_SOPPRESSO
    assert dal_db.collegamento_effettivo == atteso.collegamento_effettivo
    assert dal_db.collegamento_effettivo.destinazione_codice == "S2"  # type: ignore[union-attr]


def test_il_raw_json_compatto_conserva_operatore_e_destinazione(tmp_path):
    """Solo i treni regolari hanno il raw_json compatto (senza fermate): operatore e destinazione
    ci sono lo stesso."""
    status = _status(impresaFerroviaria="Trenord")
    conn = _db(tmp_path, status)
    assert '"fermate"' not in conn.execute("SELECT raw_json FROM treni").fetchone()[0]
    ((_, p),) = iter_profili(conn)
    assert p.operatore == "Trenord" and p.stato is StatoTreno.REGOLARE
    assert p.collegamento_effettivo.destinazione_codice == "S3"  # type: ignore[union-attr]


def test_un_treno_soppresso_e_cancellato(tmp_path):
    status = _status(tipoTreno="ST", provvedimento=1, arrivato=False)
    conn = _db(tmp_path, status)
    ((_, p),) = iter_profili(conn)
    assert p.stato is StatoTreno.CANCELLATO


def test_l_ordine_delle_fermate_e_quello_dell_inserimento_non_il_progressivo(tmp_path):
    base = GIORNO
    fermate = [
        _f("S1", "P", 5, programmata=base, partenza_teorica=base),
        _f(
            "S2",
            "F",
            2,
            programmata=base + MIN,
            arrivo_teorico=base + MIN,
            partenza_teorica=base + MIN,
        ),
        _f("S3", "A", 9, programmata=base + 5 * MIN, arrivo_teorico=base + 5 * MIN),
    ]
    conn = _db(tmp_path, _status(fermate=fermate))
    ((_, p),) = iter_profili(conn)
    assert [f.codice for f in p.fermate] == ["S1", "S2", "S3"]


def test_senza_orari_teorici_si_usa_l_unico_orario_noto(tmp_path):
    """DB scritto prima delle colonne teoriche: la durata dalla prima fermata e' esatta, le altre
    sono None, mai inventate."""
    status = _status()
    conn = _db(tmp_path, status)
    conn.execute("UPDATE fermate SET arrivo_teorico = NULL, partenza_teorica = NULL")
    ((_, p),) = iter_profili(conn)
    assert p.archi[0].durata_programmata == 10.0  # prima fermata: partenza = orario_programmato
    assert p.archi[1].durata_programmata is None


def test_un_db_senza_le_colonne_teoriche_si_legge(tmp_path):
    conn = _db(tmp_path, _status())
    conn.close()
    c = sqlite3.connect(tmp_path / "e.db")
    c.execute("ALTER TABLE fermate DROP COLUMN arrivo_teorico")
    c.execute("ALTER TABLE fermate DROP COLUMN partenza_teorica")
    c.commit()
    c.close()
    vecchio = sqlite3.connect(tmp_path / "e.db")
    vecchio.row_factory = sqlite3.Row
    assert len(carica_profili(vecchio)) == 1


def test_senza_raw_json_di_andamento_si_ricostruisce_il_minimo(tmp_path):
    status = _status()
    conn = _db(tmp_path, status)
    conn.execute("UPDATE treni SET raw_json = '{\"numeroTreno\": 10}'")  # riga di tabellone
    ((_, p),) = iter_profili(conn)
    assert p.stato is StatoTreno.REGOLARE
    assert p.itinerario is not None and p.itinerario.codici == ("S1", "S2", "S3")


def test_le_corse_senza_fermate_sono_saltate(tmp_path):
    conn = _db(tmp_path, _status())
    storage.upsert_treno(conn, numero_treno=99, cod_origine="S1", data_partenza_treno=GIORNO)
    assert [p.numero for p in carica_profili(conn)] == [10]  # la 99 non ha fermate


def test_una_corsa_non_disponibile_con_le_fermate_ha_un_itinerario(tmp_path):
    """Letta prima della partenza, poi il sito non ha piu' risposto: l'itinerario e' valido e le
    viste SQL la contano (307 corse sul DB reale)."""
    conn = _db(tmp_path, _status())
    conn.execute("UPDATE treni SET stato = 'non_disponibile', raw_json = NULL")
    ((_, p),) = iter_profili(conn)
    assert p.itinerario is not None and p.itinerario.codici == ("S1", "S2", "S3")


def test_apri_copia_e_in_sola_lettura_e_non_crea_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        apri_copia(str(tmp_path / "no.db"))
    assert not (tmp_path / "no.db").exists()
    _db(tmp_path, _status()).close()
    prima = (tmp_path / "e.db").read_bytes()
    copia = apri_copia(str(tmp_path / "e.db"))
    copia.execute("DELETE FROM treni")  # la copia e' in memoria: il file non cambia
    assert (tmp_path / "e.db").read_bytes() == prima
    assert (
        apri_copia(str(tmp_path / "e.db")).execute("SELECT COUNT(*) FROM treni").fetchone()[0] == 1
    )


def test_senza_raw_json_un_treno_soppresso_e_cancellato(tmp_path):
    conn = _db(tmp_path, _status())
    conn.execute("UPDATE treni SET raw_json = NULL, stato = 'soppresso'")
    ((_, p),) = iter_profili(conn)
    assert p.stato is StatoTreno.CANCELLATO
