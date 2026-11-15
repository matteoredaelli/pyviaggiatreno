# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tipo di giorno di servizio: feriale, sabato, domenica/festivo.

L'orario dei treni cambia con il tipo di giorno (una linea ogni 30 minuti da lunedi' a venerdi'
puo' essere ogni ora la domenica) e lo stesso numero di treno puo' avere fermate diverse. Per
questo un orario va riferito a un `TipoGiorno` e non a una data.

Si considera festivo come la domenica:

- le domeniche;
- i festivi nazionali: 1 gennaio, 6 gennaio, Pasqua e lunedi' dell'Angelo, 25 aprile, 1 maggio,
  2 giugno, 15 agosto, 1 novembre, 8 dicembre, 25 e 26 dicembre.

Non sono considerati: il patrono locale, i ponti, gli scioperi e i calendari scolastici, che
cambiano il servizio ma non si ricavano dalla data. Chi analizza i dati deve sapere che un
giorno "feriale" puo' avere un orario ridotto per queste cause.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum


class TipoGiorno(StrEnum):
    FERIALE = "feriale"
    SABATO = "sabato"
    FESTIVO = "festivo"  # domenica e festivi nazionali


# (mese, giorno) dei festivi a data fissa
_FISSI = frozenset(
    {(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)}
)


def pasqua(anno: int) -> date:
    """Domenica di Pasqua (calendario gregoriano), con l'algoritmo anonimo di Meeus/Jones/Butcher."""
    a = anno % 19
    b, c = divmod(anno, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    mese, giorno = divmod(h + ll - 7 * m + 114, 31)
    return date(anno, mese, giorno + 1)


def e_festivo_nazionale(giorno: date) -> bool:
    """True per i festivi nazionali, domeniche escluse (la domenica non e' una data fissa)."""
    if (giorno.month, giorno.day) in _FISSI:
        return True
    p = pasqua(giorno.year)
    return giorno in (p, p + timedelta(days=1))


def tipo_giorno(giorno: date) -> TipoGiorno:
    """`festivo` per domeniche e festivi nazionali, `sabato`, altrimenti `feriale`.

    Un festivo che cade di sabato e' `festivo`.
    """
    if giorno.weekday() == 6 or e_festivo_nazionale(giorno):
        return TipoGiorno.FESTIVO
    if giorno.weekday() == 5:
        return TipoGiorno.SABATO
    return TipoGiorno.FERIALE


# --------------------------------------------------------------------------- fuso orario italiano
#
# Europe/Rome senza dipendere dal database dei fusi del sistema (su Windows manca): ora legale
# dall'ultima domenica di marzo alle 01:00 UTC all'ultima di ottobre alle 01:00 UTC. Le prove
# confrontano la funzione con `zoneinfo` su ogni ora del 2024-2028.

_UN_ORA_MS = 3_600_000


def _ultima_domenica(anno: int, mese: int) -> date:
    ultimo = date(anno, mese, 31)  # marzo e ottobre hanno 31 giorni
    return ultimo - timedelta(days=(ultimo.weekday() + 1) % 7)


def offset_italia_ms(utc_ms: int) -> int:
    """Scarto dell'ora italiana da UTC in ms: 1 ora d'inverno, 2 d'estate."""
    t = datetime.fromtimestamp(utc_ms / 1000, UTC)
    inizio = datetime.combine(_ultima_domenica(t.year, 3), time(1), UTC)
    fine = datetime.combine(_ultima_domenica(t.year, 10), time(1), UTC)
    return 2 * _UN_ORA_MS if inizio <= t < fine else _UN_ORA_MS


def data_locale(utc_ms: int) -> date:
    """La data, in ora italiana, di un istante (ms da epoca)."""
    return datetime.fromtimestamp((utc_ms + offset_italia_ms(utc_ms)) / 1000, UTC).date()


def ora_locale_ms(giorno: date, ora: int = 0, minuto: int = 0) -> int:
    """L'istante (ms da epoca) di un'ora italiana. Un'ora inesistente (il salto di marzo,
    02:00-03:00) viene portata avanti; una ripetuta (ottobre) vale la prima volta."""
    locale = datetime.combine(giorno, time(ora, minuto), UTC)
    locale_ms = int(locale.timestamp() * 1000)
    estate = locale_ms - 2 * _UN_ORA_MS
    if offset_italia_ms(estate) == 2 * _UN_ORA_MS:
        return estate
    return locale_ms - _UN_ORA_MS


def data_di_servizio(data_partenza_treno_ms: int) -> date:
    """Il giorno di servizio di un treno, da `dataPartenzaTreno` (la sua mezzanotte locale in ms).

    Come nelle viste SQL (`giorno`): +12 ore e data in UTC, che da' il giorno giusto sia in orario
    solare sia legale.
    """
    return datetime.fromtimestamp((data_partenza_treno_ms + 12 * _UN_ORA_MS) / 1000, UTC).date()


__all__ = [
    "TipoGiorno",
    "data_di_servizio",
    "data_locale",
    "e_festivo_nazionale",
    "offset_italia_ms",
    "ora_locale_ms",
    "pasqua",
    "tipo_giorno",
]
