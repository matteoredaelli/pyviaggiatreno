# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Coordinate valide e regione "geografica" delle stazioni.

Il `codReg` di ViaggiaTreno non e' geografico: indica la regione di competenza, che per alcune
stazioni non coincide con quella dove si trovano (es. Roma Termini ha il codice dell'Abruzzo, Bari
Centrale quello dell'Abruzzo, Perugia quello della Toscana). Senza poligoni delle regioni, la
regione di una stazione si ricava dalle stazioni vicine: se la maggioranza dei vicini piu' prossimi
ha un'altra regione, e il codice originale non compare quasi mai tra loro, vince la maggioranza.
Le stazioni senza coordinate valide mantengono il codice originale.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping

# riquadro che contiene l'Italia (isole comprese); fuori da qui le coordinate sono errate
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 35.0, 48.0, 6.0, 19.0
VICINI = 7
MAGGIORANZA_MIN = 5  # vicini (su VICINI) con la stessa regione per scavalcare l'originale
PASSATE = 3
ORIGINALE_MAX = 1  # il codice originale puo' comparire al massimo tra questi vicini


def coordinate_valide(lat: float | None, lon: float | None) -> bool:
    return (
        lat is not None
        and lon is not None
        and LAT_MIN <= lat <= LAT_MAX
        and LON_MIN <= lon <= LON_MAX
    )


def regioni_geografiche(
    stazioni: Mapping[str, tuple[float | None, float | None, int | None]],
) -> dict[str, int | None]:
    """codice -> regione corretta dai vicini. `stazioni`: codice -> (lat, lon, codReg originale)."""
    valide: dict[str, tuple[float, float, int]] = {
        c: (lat, lon, reg)
        for c, (lat, lon, reg) in stazioni.items()
        if reg is not None and lat is not None and lon is not None and coordinate_valide(lat, lon)
    }
    celle: dict[tuple[int, int], list[str]] = defaultdict(list)
    for c, (lat, lon, _) in valide.items():
        celle[(math.floor(lat), math.floor(lon))].append(c)

    def vicini(c: str) -> list[str]:
        lat, lon, _ = valide[c]
        for raggio in (1, 2, 4, 8):
            cand = [
                x
                for dy in range(-raggio, raggio + 1)
                for dx in range(-raggio, raggio + 1)
                for x in celle.get((math.floor(lat) + dy, math.floor(lon) + dx), ())
                if x != c
            ]
            if len(cand) >= VICINI * 3:
                break
        cos = math.cos(math.radians(lat))

        def dist(x: str) -> float:
            return (valide[x][0] - lat) ** 2 + ((valide[x][1] - lon) * cos) ** 2

        return sorted(cand, key=dist)[:VICINI]

    vic = {c: vicini(c) for c in valide}
    out: dict[str, int | None] = {c: v[2] for c, v in stazioni.items()}
    # piu' passate: una stazione corretta aiuta a correggere (o a confermare) le vicine
    for _ in range(PASSATE):
        nuovo = dict(out)
        for c in valide:
            voti = Counter(out[x] for x in vic[c])
            if not voti:
                continue
            migliore, n = voti.most_common(1)[0]
            if migliore != out[c] and n >= MAGGIORANZA_MIN and voti[out[c]] <= ORIGINALE_MAX:
                nuovo[c] = migliore
        if nuovo == out:
            break
        out = nuovo
    return out


__all__ = ["coordinate_valide", "regioni_geografiche"]
