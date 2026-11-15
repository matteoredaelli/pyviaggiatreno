# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modalita' "orario": un treno per (numero, origine, tipo di giorno), record con scadenza."""

import random
from datetime import UTC, datetime

import pytest
from test_eventi import (
    CENSISCI,
    GIORNO,
    MIN,
    ORA,
    SONDA,
    VERIFICA,
    _motore,
    _riga,
    _stazione,
)
from viaggiatreno.insights import data_locale, offset_italia_ms
from viaggiatreno_crawler import storage
from viaggiatreno_crawler.config import ConfigEventi
from viaggiatreno_crawler.eventi import scadenza_orario_ms

GIORNO_MS = 86_400_000
# ORA = 2027-01-15 08:00 UTC = 09:00 italiane, un venerdi'; GIORNO ne e' la mezzanotte UTC


def _motore_orario(tmp_path, seme=1, **kw):
    m, c, clock = _motore(tmp_path, modalita="orario", **kw)
    m._rng = random.Random(seme)
    return m, c, clock


# ------------------------------------------------------------------ la scadenza casuale


def _ora_locale(ms: int) -> tuple[int, int]:
    t = datetime.fromtimestamp((ms + offset_italia_ms(ms)) / 1000, UTC)
    return t.hour, t.minute


def test_la_scadenza_cade_tra_6_e_14_giorni_e_tra_le_8_e_le_15():
    cfg = ConfigEventi()
    rng = random.Random(7)
    giorni, ore = set(), set()
    for _ in range(3000):
        s = scadenza_orario_ms(ORA, cfg, rng)
        giorni.add((data_locale(s) - data_locale(ORA)).days)
        ora, minuto = _ora_locale(s)
        assert 8 <= ora < 15, (ora, minuto)
        ore.add(ora)
    assert giorni == set(range(6, 15))  # tutti e soli: 6..14
    assert ore == set(range(8, 15))


def test_la_scadenza_rispetta_l_ora_locale_anche_con_l_ora_legale():
    cfg = ConfigEventi()
    estate = int(datetime(2026, 7, 1, 10, tzinfo=UTC).timestamp() * 1000)
    rng = random.Random(3)
    for _ in range(500):
        assert 8 <= _ora_locale(scadenza_orario_ms(estate, cfg, rng))[0] < 15


def test_la_scadenza_e_deterministica_con_lo_stesso_seme():
    cfg = ConfigEventi()
    assert scadenza_orario_ms(ORA, cfg, random.Random(5)) == scadenza_orario_ms(
        ORA, cfg, random.Random(5)
    )


def test_la_scadenza_usa_i_parametri_della_configurazione():
    cfg = ConfigEventi(
        orario_giorni_min=3, orario_giorni_max=3, orario_ora_min=20, orario_ora_max=21
    )
    rng = random.Random(1)
    for _ in range(50):
        s = scadenza_orario_ms(ORA, cfg, rng)
        assert (data_locale(s) - data_locale(ORA)).days == 3 and _ora_locale(s)[0] == 20


# ------------------------------------------------------------------ treni


async def test_un_treno_nuovo_riceve_tipo_di_giorno_e_scadenza(tmp_path):
    m, c, _ = _motore_orario(tmp_path)
    _stazione(m, "S1")
    c.board[("partenze", "S1")] = [_riga(100, "S1", "S9", ORA + 30 * MIN)]
    await m._esegui(CENSISCI, "S1")
    t = m.conn.execute("SELECT * FROM treni").fetchone()
    assert t["tipo_giorno"] == "feriale"
    assert ORA + 5 * GIORNO_MS < t["scade_orario"] < ORA + 15 * GIORNO_MS
    # la verifica resta a 10 minuti dalla partenza: niente chiamata anticipata
    assert t["prossima_verifica"] == ORA + 20 * MIN
    assert ("andamento", 100) not in c.chiamate


async def test_lo_stesso_treno_dello_stesso_tipo_di_giorno_non_si_riscarica(tmp_path):
    m, c, _ = _motore_orario(tmp_path)
    _stazione(m, "S1")
    c.board[("partenze", "S1")] = [_riga(100, "S1", "S9", ORA + 30 * MIN)]
    await m._esegui(CENSISCI, "S1")
    # il giorno dopo (sabato) e' un altro tipo: si scarica. Poi un'altra corsa feriale: no.
    riga_feriale = _riga(100, "S1", "S9", ORA + 30 * MIN)
    riga_feriale.dataPartenzaTreno = GIORNO + 4 * GIORNO_MS  # martedi' 19/01
    c.board[("partenze", "S1")] = [riga_feriale]
    await m._esegui(SONDA, "S1")
    assert m.conn.execute("SELECT COUNT(*) FROM treni").fetchone()[0] == 1
    assert m.pian.scadenza(VERIFICA, "2") is None


async def test_lo_stesso_numero_di_sabato_e_di_domenica_si_scarica_per_ciascuno(tmp_path):
    m, c, _ = _motore_orario(tmp_path)
    _stazione(m, "S1")
    righe = []
    for giorni in (0, 1, 2, 3):  # ven 15, sab 16, dom 17, lun 18 gennaio 2027
        r = _riga(100, "S1", "S9", ORA + 30 * MIN)
        r.dataPartenzaTreno = GIORNO + giorni * GIORNO_MS
        righe.append(r)
    c.board[("partenze", "S1")] = righe
    await m._esegui(CENSISCI, "S1")
    tipi = [
        r[0] for r in m.conn.execute("SELECT tipo_giorno FROM treni ORDER BY data_partenza_treno")
    ]
    # venerdi', sabato, domenica: tre; il lunedi' ripete il venerdi' e non e' salvato
    assert tipi == ["feriale", "sabato", "festivo"]


async def test_un_record_scaduto_si_riscarica(tmp_path):
    m, c, clock = _motore_orario(tmp_path)
    _stazione(m, "S1")
    c.board[("partenze", "S1")] = [_riga(100, "S1", "S9", ORA + 30 * MIN)]
    await m._esegui(CENSISCI, "S1")
    scade = m.conn.execute("SELECT scade_orario FROM treni").fetchone()[0]
    clock.t = scade + MIN  # il record e' scaduto
    nuova = _riga(100, "S1", "S9", clock.t + 30 * MIN)
    nuova.dataPartenzaTreno = GIORNO + 7 * GIORNO_MS  # venerdi' 22/01
    c.board[("partenze", "S1")] = [nuova]
    await m._esegui(SONDA, "S1")
    assert m.conn.execute("SELECT COUNT(*) FROM treni").fetchone()[0] == 2


async def test_un_treno_fallito_non_blocca_i_giorni_successivi(tmp_path):
    m, c, _ = _motore_orario(tmp_path)
    _stazione(m, "S1")
    c.board[("partenze", "S1")] = [_riga(100, "S1", "S9", ORA + 30 * MIN)]
    await m._esegui(CENSISCI, "S1")
    m.conn.execute("UPDATE treni SET stato = 'non_disponibile'")
    assert not storage.orario_valido(m.conn, 100, "S1", "feriale", ORA)
    m.conn.execute("UPDATE treni SET stato = 'soppresso'")
    assert not storage.orario_valido(m.conn, 100, "S1", "feriale", ORA)
    m.conn.execute("UPDATE treni SET stato = 'arrivato'")
    assert storage.orario_valido(m.conn, 100, "S1", "feriale", ORA)
    assert not storage.orario_valido(m.conn, 100, "S1", "sabato", ORA)  # altro tipo di giorno
    assert not storage.orario_valido(m.conn, 101, "S1", "feriale", ORA)  # altro numero
    assert not storage.orario_valido(m.conn, 100, "S2", "feriale", ORA)  # altra origine


async def test_la_modalita_statistiche_non_cambia(tmp_path):
    m, c, _ = _motore(tmp_path)  # modalita' predefinita
    _stazione(m, "S1")
    c.board[("partenze", "S1")] = [_riga(100, "S1", "S9", ORA + 30 * MIN)]
    await m._esegui(CENSISCI, "S1")
    r = m.conn.execute("SELECT scade_orario, tipo_giorno FROM treni").fetchone()
    assert r["scade_orario"] is None and r["tipo_giorno"] == "feriale"
    assert c.chiamate == [("partenze", "S1")]  # una sola richiesta, come prima


# ------------------------------------------------------------------ stazioni


async def test_una_stazione_nuova_legge_partenze_e_arrivi(tmp_path):
    m, c, _ = _motore_orario(tmp_path)
    _stazione(m, "S5")
    await m._esegui(CENSISCI, "S5")
    assert c.chiamate == [("partenze", "S5"), ("arrivi", "S5")]


async def test_una_stazione_di_transito_scade_tra_6_e_14_giorni(tmp_path):
    m, c, _ = _motore_orario(tmp_path)
    _stazione(m, "S5")
    c.board[("partenze", "S5")] = [_riga(200, "S1", "S9", ORA + 60 * MIN)]  # origine altrove
    await m._esegui(CENSISCI, "S5")
    quando = m.pian.scadenza(CENSISCI, "S5")
    assert quando is not None and ORA + 5 * GIORNO_MS < quando < ORA + 15 * GIORNO_MS
    assert 8 <= _ora_locale(int(quando))[0] < 15
    assert m.pian.scadenza(SONDA, "S5") is None
    assert (
        m.conn.execute("SELECT prossima_sonda FROM stops WHERE stop_id='S5'").fetchone()[0]
        == quando
    )


def _righe_piene(n, ultimo_min):
    return [_riga(300 + i, "S1", "S9", ORA + int((i + 1) * ultimo_min / n * MIN)) for i in range(n)]


async def test_un_capolinea_si_rilegge_a_79_minuti(tmp_path):
    m, c, _ = _motore_orario(tmp_path)
    _stazione(m, "S1", origine=True)
    c.board[("partenze", "S1")] = [_riga(100, "S1", "S9", ORA + 30 * MIN)]  # tabellone rado
    await m._esegui(SONDA, "S1")
    assert m.pian.scadenza(SONDA, "S1") == pytest.approx(ORA + 79 * MIN, abs=1)


async def test_con_un_tabellone_pieno_corto_si_rilegge_5_minuti_prima_della_fine(tmp_path):
    m, c, _ = _motore_orario(tmp_path)
    _stazione(m, "S1", origine=True)
    c.board[("partenze", "S1")] = _righe_piene(20, 60)  # l'ultimo treno a +60 minuti
    await m._esegui(SONDA, "S1")
    assert m.pian.scadenza(SONDA, "S1") == ORA + 55 * MIN


async def test_il_tabellone_lungo_non_allunga_oltre_i_79_minuti(tmp_path):
    m, c, _ = _motore_orario(tmp_path)
    _stazione(m, "S1", origine=True)
    c.board[("partenze", "S1")] = _righe_piene(20, 95)
    await m._esegui(SONDA, "S1")
    assert m.pian.scadenza(SONDA, "S1") == ORA + 79 * MIN


async def test_tabelloni_vuoti_si_rileggono_a_90_minuti(tmp_path):
    m, _c, _ = _motore_orario(tmp_path)
    _stazione(m, "S1", origine=True)
    await m._esegui(SONDA, "S1")  # partenze e arrivi vuoti
    assert m.pian.scadenza(SONDA, "S1") == ORA + 90 * MIN


async def test_un_tabellone_vuoto_e_uno_pieno_non_si_confondono(tmp_path):
    m, c, _ = _motore_orario(tmp_path)
    _stazione(m, "S1", origine=True)
    c.board[("arrivi", "S1")] = [_riga(100, "S9", "S1", ORA + 30 * MIN)]
    await m._esegui(SONDA, "S1")
    assert m.pian.scadenza(SONDA, "S1") == ORA + 79 * MIN  # basta un tabellone non vuoto


# ------------------------------------------------------------------ avvio


async def test_al_riavvio_si_ricava_il_tipo_di_giorno_delle_corse_vecchie(tmp_path):
    m, _c, _ = _motore_orario(tmp_path)
    storage.upsert_treno(
        m.conn, numero_treno=1, cod_origine="S1", data_partenza_treno=GIORNO + 2 * GIORNO_MS
    )
    m.conn.execute("UPDATE treni SET tipo_giorno = NULL")
    m.ricostruisci()
    assert m.conn.execute("SELECT tipo_giorno FROM treni").fetchone()[0] == "festivo"  # domenica


def test_la_cli_accetta_la_modalita():
    from viaggiatreno_crawler.__main__ import parse_args_eventi

    assert parse_args_eventi(["eventi"]).modalita == "statistiche"
    cfg = parse_args_eventi(["eventi", "--modalita", "orario", "--orario-giorni-max", "10"])
    assert cfg.modalita == "orario" and cfg.orario_giorni_max == 10
