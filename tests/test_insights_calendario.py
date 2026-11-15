# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test del tipo di giorno (`TipoGiorno`), con date verificate a mano sul calendario."""

from datetime import date

import pytest
from viaggiatreno.insights import TipoGiorno, e_festivo_nazionale, pasqua, tipo_giorno


@pytest.mark.parametrize(
    ("anno", "atteso"),
    [
        (2024, date(2024, 3, 31)),
        (2025, date(2025, 4, 20)),
        (2026, date(2026, 4, 5)),
        (2027, date(2027, 3, 28)),
        (2038, date(2038, 4, 25)),  # il limite alto delle date di Pasqua
        (2285, date(2285, 3, 22)),  # il limite basso
    ],
)
def test_pasqua(anno, atteso):
    assert pasqua(anno) == atteso


def test_giorni_della_settimana():
    # 9-15 novembre 2026: lunedi' ... domenica
    assert [tipo_giorno(date(2026, 11, d)) for d in range(9, 16)] == [
        TipoGiorno.FERIALE,
        TipoGiorno.FERIALE,
        TipoGiorno.FERIALE,
        TipoGiorno.FERIALE,
        TipoGiorno.FERIALE,
        TipoGiorno.SABATO,
        TipoGiorno.FESTIVO,
    ]


@pytest.mark.parametrize(
    "giorno",
    [
        date(2026, 1, 1),
        date(2026, 1, 6),
        date(2026, 4, 6),  # lunedi' dell'Angelo (Pasqua 5 aprile)
        date(2026, 4, 25),  # sabato: il festivo vince sul sabato
        date(2026, 5, 1),
        date(2026, 6, 2),
        date(2026, 8, 15),
        date(2026, 11, 1),  # domenica e Ognissanti
        date(2026, 12, 8),
        date(2026, 12, 25),
        date(2026, 12, 26),  # sabato
    ],
)
def test_festivi_nazionali(giorno):
    assert tipo_giorno(giorno) is TipoGiorno.FESTIVO


def test_il_festivo_che_cade_di_sabato_e_festivo_non_sabato():
    assert date(2026, 4, 25).weekday() == 5
    assert tipo_giorno(date(2026, 4, 25)) is TipoGiorno.FESTIVO


def test_la_pasqua_e_festiva_e_il_venerdi_santo_no():
    assert tipo_giorno(date(2026, 4, 5)) is TipoGiorno.FESTIVO  # Pasqua (domenica)
    assert tipo_giorno(date(2026, 4, 3)) is TipoGiorno.FERIALE  # venerdi' santo: non festivo
    assert tipo_giorno(date(2026, 4, 6)) is TipoGiorno.FESTIVO  # lunedi' dell'Angelo


def test_e_festivo_nazionale_non_conta_le_domeniche():
    assert e_festivo_nazionale(date(2026, 12, 25)) and e_festivo_nazionale(date(2026, 4, 6))
    assert not e_festivo_nazionale(date(2026, 11, 12))
    assert not e_festivo_nazionale(date(2026, 11, 15))  # domenica qualunque: non e' nell'elenco
    assert tipo_giorno(date(2026, 11, 15)) is TipoGiorno.FESTIVO  # ma tipo_giorno la vede


def test_ferragosto_in_giorni_diversi():
    assert tipo_giorno(date(2025, 8, 15)) is TipoGiorno.FESTIVO  # venerdi'
    assert tipo_giorno(date(2026, 8, 15)) is TipoGiorno.FESTIVO  # sabato


# ------------------------------------------------------------------ fuso orario italiano

from datetime import UTC, datetime, timedelta

from viaggiatreno.insights import (
    data_di_servizio,
    data_locale,
    offset_italia_ms,
    ora_locale_ms,
)

ORA_MS = 3_600_000


def _ms(anno, mese, giorno, ora=0, minuto=0):
    return int(datetime(anno, mese, giorno, ora, minuto, tzinfo=UTC).timestamp() * 1000)


def test_offset_come_zoneinfo_su_ogni_ora_di_cinque_anni():
    zoneinfo = pytest.importorskip("zoneinfo")
    try:
        roma = zoneinfo.ZoneInfo("Europe/Rome")
    except zoneinfo.ZoneInfoNotFoundError:  # pragma: no cover - sistema senza database dei fusi
        pytest.skip("database dei fusi non disponibile")
    t = datetime(2024, 1, 1, tzinfo=UTC)
    fine = datetime(2029, 1, 1, tzinfo=UTC)
    sbagliati = []
    while t < fine:
        atteso = int(t.astimezone(roma).utcoffset().total_seconds() * 1000)  # type: ignore[union-attr]
        if offset_italia_ms(int(t.timestamp() * 1000)) != atteso:
            sbagliati.append(t)
        t += timedelta(hours=1)
    assert sbagliati == []


def test_cambi_di_ora_2026():
    # ora legale dal 29/03/2026 alle 01:00 UTC, solare dal 25/10/2026 alle 01:00 UTC
    assert offset_italia_ms(_ms(2026, 3, 29, 0, 59)) == ORA_MS
    assert offset_italia_ms(_ms(2026, 3, 29, 1, 0)) == 2 * ORA_MS
    assert offset_italia_ms(_ms(2026, 10, 25, 0, 59)) == 2 * ORA_MS
    assert offset_italia_ms(_ms(2026, 10, 25, 1, 0)) == ORA_MS


def test_data_locale_a_cavallo_della_mezzanotte():
    assert data_locale(_ms(2026, 10, 24, 22, 30)) == date(2026, 10, 25)  # 00:30 legale
    assert data_locale(_ms(2026, 11, 12, 22, 30)) == date(2026, 11, 12)  # 23:30 solare
    assert data_locale(_ms(2026, 11, 12, 23, 0)) == date(2026, 11, 13)  # 00:00 solare


def test_ora_locale_in_inverno_e_in_estate():
    assert ora_locale_ms(date(2026, 11, 12), 8) == _ms(2026, 11, 12, 7)  # CET: 8 -> 7 UTC
    assert ora_locale_ms(date(2026, 7, 1), 8) == _ms(2026, 7, 1, 6)  # CEST: 8 -> 6 UTC
    assert ora_locale_ms(date(2026, 7, 1), 15, 30) == _ms(2026, 7, 1, 13, 30)


def test_ora_locale_e_data_locale_sono_inverse_nelle_ore_di_lavoro():
    zoneinfo = pytest.importorskip("zoneinfo")
    giorno = date(2026, 1, 1)
    for _ in range(730):
        for ora in (0, 4, 8, 12, 15, 23):
            ms = ora_locale_ms(giorno, ora, 7)
            assert data_locale(ms) == giorno
            ora_vista = datetime.fromtimestamp(ms / 1000, UTC) + timedelta(
                milliseconds=offset_italia_ms(ms)
            )
            assert (ora_vista.hour, ora_vista.minute) == (ora, 7)
        giorno += timedelta(days=1)
    assert zoneinfo  # solo per usare il modulo importato


def test_ora_inesistente_o_ripetuta_non_rompe():
    salto = ora_locale_ms(date(2026, 3, 29), 2, 30)  # 02:30 non esiste: va avanti a 03:30
    assert salto == _ms(2026, 3, 29, 1, 30)
    ripetuta = ora_locale_ms(date(2026, 10, 25), 2, 30)  # esiste due volte: la prima (legale)
    assert ripetuta == _ms(2026, 10, 25, 0, 30)


def test_data_di_servizio_dalla_mezzanotte_locale():
    # mezzanotte locale del 12/11/2026 (solare) e del 12/07/2026 (legale)
    assert data_di_servizio(_ms(2026, 11, 11, 23)) == date(2026, 11, 12)
    assert data_di_servizio(_ms(2026, 7, 11, 22)) == date(2026, 7, 12)
    # un valore a mezzanotte UTC (come nei test del crawler) cade lo stesso nel giorno giusto
    assert data_di_servizio(_ms(2027, 1, 15, 0)) == date(2027, 1, 15)
