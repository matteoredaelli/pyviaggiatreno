# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dal modello alle pagine HTML statiche.

Un file per stazione (`stazioni/<codice>.html`, il codice e' unico: 5 nomi sono duplicati), una
pagina indice e `dati/stazioni.json` per la ricerca e le mappe. Nessuna pagina per treno: le linee
a cui una stazione appartiene sono elencate nella sua pagina.

Le pagine usano solo percorsi **relativi**, quindi funzionano aperte da file e da qualunque
sottocartella (GitHub Pages incluso). Nessun JavaScript e' necessario: il filtro dell'indice e'
un piccolo extra. `mappa.html` usa Leaflet (da CDN) e le tile Esri (senza chiave API), quindi richiede rete.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from viaggiatreno_sito.modello import Modello, Stazione

_ETICHETTE_GIORNO = {
    "feriale": "Weekday (Mon–Fri)",
    "sabato": "Saturday",
    "festivo": "Sunday and holidays",
}


_RUOLI = {
    "capolinea": "terminus",
    "intermedia": "intermediate",
    "solo in alcune varianti": "only in some variants",
}


def _ambiente() -> Environment:
    env = Environment(
        loader=PackageLoader("viaggiatreno_sito", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["minuti"] = _minuti
    env.filters["km"] = _km
    env.filters["ruolo"] = lambda r: _RUOLI.get(r, r)
    env.globals["etichetta_giorno"] = lambda t: _ETICHETTE_GIORNO.get(t, t)
    return env


def _minuti(v: float | None) -> str:
    return "–" if v is None else f"{v:.0f} min"


def _km(v: float | None) -> str:
    return "–" if v is None else f"{v:.1f} km"


def _dati_mappa(stazioni: list[Stazione]) -> dict:
    """Stazioni con coordinate e archi (tratte note + stazioni vicine osservate), senza doppioni.

    `s`: [codice, nome, lat, lon, ha_dati]; `t`: coppie di indici in `s`.
    """
    con_coord = [s for s in stazioni if s.lat is not None and s.lon is not None]
    indice = {s.codice: i for i, s in enumerate(con_coord)}
    archi: set[tuple[int, int]] = set()
    for s in con_coord:
        altri = [t.altro_nodo for t in s.tratte] + [v.codice for v in s.vicini]
        for altro in altri:
            j = indice.get(altro)
            if j is not None and j != indice[s.codice]:
                archi.add((min(indice[s.codice], j), max(indice[s.codice], j)))
    return {
        "s": [
            [s.codice, s.nome or s.codice, round(s.lat, 5), round(s.lon, 5), int(s.ha_dati)]
            for s in con_coord
            if s.lat is not None and s.lon is not None
        ],
        "t": sorted(archi),
    }


@dataclass
class Esito:
    cartella: Path
    n_stazioni: int
    file: list[Path]


def pagina_stazione_path(codice: str) -> str:
    return f"stazioni/{codice}.html"


def render_sito(modello: Modello, cartella: str | Path, *, solo: set[str] | None = None) -> Esito:
    """Scrive il sito in `cartella` (creata se manca). Con `solo` solo quelle stazioni."""
    out = Path(cartella)
    (out / "stazioni").mkdir(parents=True, exist_ok=True)
    (out / "dati").mkdir(parents=True, exist_ok=True)
    env = _ambiente()
    scritti: list[Path] = []

    def scrivi(rel: str, contenuto: str) -> None:
        p = out / rel
        p.write_text(contenuto, encoding="utf-8")
        scritti.append(p)

    scrivi(
        "stile.css", (Path(__file__).parent / "templates" / "stile.css").read_text(encoding="utf-8")
    )

    stazioni = [s for s in modello.stazioni.values() if solo is None or s.codice in solo]
    esistono = {s.codice for s in stazioni}
    tmpl = env.get_template("stazione.html")
    for s in stazioni:
        scrivi(
            pagina_stazione_path(s.codice),
            tmpl.render(s=s, giorni=modello.giorni, esistono=esistono, radice="../"),
        )

    per_regione: dict[str, list[Stazione]] = defaultdict(list)
    for s in stazioni:
        per_regione[s.regione_nome or "Unknown region"].append(s)
    regioni = [
        (nome, sorted(lista, key=lambda x: (x.nome or x.codice, x.codice)))
        for nome, lista in sorted(per_regione.items())
    ]
    scrivi(
        "index.html",
        env.get_template("index.html").render(
            regioni=regioni,
            n_stazioni=len(stazioni),
            n_con_dati=sum(1 for s in stazioni if s.ha_dati),
            n_linee=modello.n_linee,
            giorni=modello.giorni,
            radice="",
        ),
    )
    dati_mappa = _dati_mappa(stazioni)
    # i dati sono incorporati nella pagina: fetch() di un file locale e' bloccato dai browser
    scrivi(
        "mappa.html",
        env.get_template("mappa.html").render(
            radice="", n_stazioni=len(dati_mappa["s"]), dati=dati_mappa
        ),
    )
    indice = [r for r in modello.indice() if solo is None or r["codice"] in solo]
    scrivi("dati/stazioni.json", json.dumps(indice, ensure_ascii=False, separators=(",", ":")))
    return Esito(out, len(stazioni), scritti)


__all__ = ["Esito", "pagina_stazione_path", "render_sito"]
