# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modello delle stazioni: definizioni, giorni, ora locale e accordo con le viste SQL."""

from datetime import UTC, datetime

import pytest
from viaggiatreno import TrainStatus
from viaggiatreno_crawler import storage, viste
from viaggiatreno_crawler.poller import persisti_andamento
from viaggiatreno_sito.modello import costruisci_modello, giorni_completi

MIN = 60_000
H = 60 * MIN


def _ms(anno, mese, giorno, ora=0, minuto=0):
    return int(datetime(anno, mese, giorno, ora, minuto, tzinfo=UTC).timestamp() * 1000)


def _mezzanotte(anno, mese, giorno):
    """Mezzanotte *locale italiana* in ms (inverno: 23:00 UTC del giorno prima)."""
    return _ms(anno, mese, giorno) - H


class Db:
    def __init__(self, tmp_path):
        self.conn = storage.connect(tmp_path / "e.db")
        self.n = 0

    def stazione(self, sid, nome=None, lat=45.0, lon=9.0):
        storage.upsert_stop(self.conn, sid, nome or sid, lat, lon, regione_codice=1, citta="X")

    def treno(self, codici, giorno=(2026, 11, 11), ora=8, tipo="PG", soppresse=(), binari=None):
        """Una corsa con le fermate `codici` (un minuto di sosta, 10 minuti tra una e l'altra)."""
        self.n += 1
        mezz = _mezzanotte(*giorno)
        base = mezz + ora * H
        fermate = []
        for i, c in enumerate(codici):
            t = base + i * 10 * MIN
            f = {
                "stazione": c,
                "id": c,
                "tipoFermata": "P" if i == 0 else ("A" if i == len(codici) - 1 else "F"),
                "progressivo": i + 1,
                "programmata": t,
                "actualFermataType": 3 if c in soppresse else 1,
            }
            if i > 0:
                f["arrivo_teorico"] = t
            if i < len(codici) - 1:
                f["partenza_teorica"] = t + MIN
            if binari and c in binari:
                f["binarioProgrammatoArrivoDescrizione"] = binari[c]
            fermate.append(f)
        validi = [c for c in codici if c not in soppresse]
        status = TrainStatus.model_validate(
            {
                "numeroTreno": 1000 + self.n,
                "tipoTreno": tipo,
                "provvedimento": 0,
                "categoria": "REG",
                "origine": validi[0],
                "destinazione": validi[-1],
                "idOrigine": validi[0],
                "idDestinazione": validi[-1],
                "dataPartenzaTreno": mezz,
                "dataPartenzaTrenoAsDate": f"{giorno[0]:04d}-{giorno[1]:02d}-{giorno[2]:02d}",
                "arrivato": True,
                "fermate": fermate,
            }
        )
        for c in codici:
            self.stazione(c)
        storage.upsert_treno(
            self.conn,
            numero_treno=status.numeroTreno,
            cod_origine=codici[0],
            data_partenza_treno=mezz,
        )
        row = self.conn.execute(
            "SELECT * FROM treni WHERE numero_treno = ?", (status.numeroTreno,)
        ).fetchone()
        persisti_andamento(self.conn, row, status)
        self.conn.commit()


@pytest.fixture
def db(tmp_path):
    return Db(tmp_path)


# ------------------------------------------------------------------ definizioni


def test_capolinea_e_transito_possono_valere_insieme(db):
    db.treno(["A", "B", "C"])  # B: transito
    db.treno(["B", "C"])  # B: capolinea (nasce)
    m = costruisci_modello(db.conn)
    b = m.stazioni["B"]
    assert b.capolinea and b.transito
    assert (b.n_nascono, b.n_finiscono, b.n_passano) == (1, 0, 1)
    assert m.stazioni["A"].capolinea and not m.stazioni["A"].transito
    assert m.stazioni["C"].n_finiscono == 2


def test_un_treno_parzialmente_soppresso_e_incerto_agli_estremi(db):
    db.treno(["A", "B", "C", "D"], soppresse=("D",))  # finisce davvero a C
    m = costruisci_modello(db.conn)
    assert (m.stazioni["A"].n_nascono, m.stazioni["A"].n_incerti) == (0, 1)
    assert (m.stazioni["C"].n_finiscono, m.stazioni["C"].n_incerti) == (0, 1)
    assert not m.stazioni["A"].capolinea and not m.stazioni["C"].capolinea
    assert m.stazioni["B"].n_passano == 1
    assert m.stazioni["D"].n_corse == 0  # la fermata soppressa non conta


def test_una_corsa_conta_una_volta_per_stazione(db):
    db.treno(["A", "B", "A", "C"])  # un'andata e ritorno: A compare due volte
    assert costruisci_modello(db.conn).stazioni["A"].n_corse == 1


def test_destinazioni_e_origini_sono_nomi_ordinati_per_frequenza(db):
    for _ in range(2):
        db.treno(["A", "B", "C"])
    db.treno(["A", "B", "D"])
    a = costruisci_modello(db.conn).stazioni["A"]
    assert a.destinazioni == ["C", "D"]


def test_binari_unione_in_ordine_naturale(db):
    db.treno(["A", "B", "C"], binari={"B": "10"})
    db.treno(["A", "B", "C"], binari={"B": "2"})
    db.treno(["A", "B", "C"], binari={"B": "V"})
    assert costruisci_modello(db.conn).stazioni["B"].binari == ["2", "10", "V"]


def test_una_stazione_senza_treni_ha_la_pagina_ma_senza_dati(db):
    db.treno(["A", "B"])
    db.stazione("Z", "ZETA", lat=None, lon=None)
    z = costruisci_modello(db.conn).stazioni["Z"]
    assert not z.ha_dati and z.linee == [] and z.vicini == [] and z.binari == []
    assert not z.capolinea and not z.transito and z.lat is None


# ------------------------------------------------------------------ linee, vicini, tratte


def test_linee_con_il_ruolo_della_stazione(db):
    db.treno(["A", "B", "C"])
    db.treno(["C", "B", "A"])  # stesso percorso nel verso opposto: stessa linea
    db.treno(["A", "B", "D"])  # altra linea, B in mezzo
    b = costruisci_modello(db.conn).stazioni["B"]
    per_nome = {line.chiave: line for line in b.linee}
    assert set(per_nome) == {"A|C", "A|D"}
    assert per_nome["A|C"].n_treni == 2 and per_nome["A|C"].ruolo == "intermedia"
    a = costruisci_modello(db.conn).stazioni["A"]
    assert {line.ruolo for line in a.linee} == {"capolinea"}


def test_vicini_con_durata_e_numero_di_treni(db):
    db.treno(["A", "B", "C"])
    db.treno(["C", "B", "A"])
    b = costruisci_modello(db.conn).stazioni["B"]
    per_codice = {v.codice: v for v in b.vicini}
    assert set(per_codice) == {"A", "C"}
    assert per_codice["C"].n_treni == 2
    assert per_codice["C"].durata_minuti == 9.0  # partenza da B (+1 min di sosta) fino a C


def test_le_tratte_sono_associate_ai_due_estremi(db):
    db.treno(["A", "B"])
    storage.upsert_tratta(
        db.conn,
        regione_codice=1,
        tratta_ab=4,
        tratta_ba=5,
        nodo_a="A",
        nodo_b="B",
        lat_a=None,
        lon_a=None,
        lat_b=None,
        lon_b=None,
        parent_ab=None,
        parent_ba=None,
    )
    m = costruisci_modello(db.conn)
    assert [(t.altro_nodo, t.tratta_ab) for t in m.stazioni["A"].tratte] == [("B", 4)]
    assert [(t.altro_nodo, t.tratta_ab) for t in m.stazioni["B"].tratte] == [("A", 4)]


def test_senza_la_tabella_tratte_il_modello_funziona(db):
    db.treno(["A", "B"])
    db.conn.execute("DROP TABLE tratte")
    assert costruisci_modello(db.conn).stazioni["A"].tratte == []


# ------------------------------------------------------------------ giorni e ora locale


def test_tipi_di_giorno_e_giorni_parziali(db):
    for giorno in ((2026, 11, 11), (2026, 11, 12), (2026, 11, 14)):  # mer, gio, sab
        for _ in range(10):
            db.treno(["A", "B"], giorno=giorno)
    db.treno(["A", "B"], giorno=(2026, 11, 13))  # 1 corsa su 10: giorno parziale
    m = costruisci_modello(db.conn)
    assert m.giorni.completi == {"feriale": ["2026-11-11", "2026-11-12"], "sabato": ["2026-11-14"]}
    assert m.giorni.parziali == ["2026-11-13"]
    a = m.stazioni["A"]
    per_tipo = {f.tipo_giorno: f for f in a.frequenze}
    assert per_tipo["feriale"].corse_per_giorno == 10.0  # media per giorno, non somma
    assert per_tipo["sabato"].corse_per_giorno == 10.0
    assert per_tipo["festivo"].corse_per_giorno is None and per_tipo["festivo"].n_giorni == 0


def test_il_giorno_parziale_non_entra_nelle_medie(db):
    for _ in range(10):
        db.treno(["A", "B"], giorno=(2026, 11, 11))
    db.treno(["A", "B"], giorno=(2026, 11, 12))
    a = costruisci_modello(db.conn).stazioni["A"]
    assert a.n_corse == 11  # il totale le conta tutte
    assert {f.tipo_giorno: f.corse_per_giorno for f in a.frequenze}["feriale"] == 10.0


def test_il_profilo_orario_e_in_ora_locale(db):
    # 08:00 locali = 07:00 UTC in inverno; alla prima fermata A l'orario e' la partenza (08:01)
    db.treno(["A", "B"], ora=8)
    a = costruisci_modello(db.conn).stazioni["A"]
    feriale = next(f for f in a.frequenze if f.tipo_giorno == "feriale")
    assert feriale.per_ora[8] == 1.0 and sum(feriale.per_ora) == 1.0


def test_il_profilo_orario_in_estate_usa_l_ora_legale(db):
    # mezzanotte locale estiva = 22:00 UTC del giorno prima
    mezz = _ms(2026, 7, 14, 0) - 2 * H
    db.treno(
        ["A", "B"], giorno=(2026, 7, 15)
    )  # costruisce con mezzanotte invernale: lo sovrascrivo
    db.conn.execute(
        "UPDATE fermate SET arrivo_teorico = NULL, orario_programmato = ?, partenza_teorica = ?",
        (mezz + 9 * H, mezz + 9 * H),
    )
    a = costruisci_modello(db.conn).stazioni["A"]
    feriale = next(f for f in a.frequenze if f.tipo_giorno == "feriale")
    assert feriale.per_ora[9] == 1.0  # 09:00 locali estive = 07:00 UTC


def test_giorni_completi_senza_profili():
    assert giorni_completi([], 0.5).completi == {}


# ------------------------------------------------------------------ accordo con le viste SQL


def test_il_modello_coincide_con_le_viste_sql(db):
    db.treno(["A", "B", "C", "D"], binari={"B": "1"})
    db.treno(["D", "C", "B", "A"], binari={"C": "2"})
    db.treno(["A", "B", "C"], giorno=(2026, 11, 12), binari={"B": "3"})
    db.treno(["B", "C", "E"], soppresse=("E",))
    db.treno(["A", "B", "A", "C"])
    viste.crea_viste(db.conn)
    m = costruisci_modello(db.conn)
    righe = db.conn.execute("SELECT * FROM v_stops WHERE n_corse > 0").fetchall()
    # A, B, C, D; E non ha corse: e' soppressa in tutte
    assert {r["stop_id"] for r in righe} == {"A", "B", "C", "D"}
    for r in righe:
        s = m.stazioni[r["stop_id"]]
        assert (s.n_corse, s.n_nascono, s.n_finiscono, s.n_passano, s.n_incerti) == (
            r["n_corse"],
            r["n_nascono"],
            r["n_finiscono"],
            r["n_passano"],
            r["n_incerti"],
        ), r["stop_id"]
        assert (s.capolinea, s.transito) == (bool(r["capolinea"]), bool(r["transito"]))
        assert len(s.binari) == r["n_binari"]


def test_indice_e_dizionario(db):
    db.treno(["A", "B"])
    m = costruisci_modello(db.conn)
    assert [r["codice"] for r in m.indice()] == ["A", "B"]
    d = m.stazioni["A"].a_dict()
    assert d["codice"] == "A" and isinstance(d["frequenze"], list)


def test_solo_limita_le_stazioni(db):
    db.treno(["A", "B", "C"])
    assert set(costruisci_modello(db.conn, solo={"B"}).stazioni) == {"B"}
