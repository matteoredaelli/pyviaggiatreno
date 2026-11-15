# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pagine markdown delle stazioni per un sito Hugo *esistente*.

Scrive solo contenuto (nessun layout, CSS o JavaScript): il tema del sito ospitante resta quello
originale. Struttura, sotto `<content>/<sezione>/` (default `trains`):

    _index.md                        la sezione ("Italian trains")
    <regione>/_index.md              una sottosezione per regione
    <regione>/<codice>.md            una pagina per stazione, con `url: /<sezione>/stations/<codice>/`

L'URL di una stazione non dipende dalla regione, quindi i link tra stazioni sono stabili. La
cartella della sezione e' *interamente gestita* da questo modulo: a ogni esecuzione viene
svuotata e riscritta (solo se e' vuota o contiene il file marcatore `.viaggiatreno-sito`).
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from viaggiatreno_sito.modello import Modello, Stazione
from viaggiatreno_sito.render import _ETICHETTE_GIORNO, _RUOLI

MARCATORE = ".viaggiatreno-sito"
_SPECIALI = re.compile(r"([\\`*_\[\]<>|#&])")


@dataclass
class EsitoHugo:
    cartella: Path
    n_stazioni: int
    n_regioni: int


def _md(testo: str | None) -> str:
    """Testo letterale in markdown (nomi di stazione, citta')."""
    return _SPECIALI.sub(r"\\\1", testo or "")


def _slug(testo: str) -> str:
    s = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "unknown"


def _front(**campi: object) -> str:
    righe = [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in campi.items()]
    return "---\n" + "\n".join(righe) + "\n---\n"


def _url_stazione(sezione: str, codice: str) -> str:
    return f"/{sezione}/stations/{codice.lower()}/"


def _numero(v: float) -> str:
    return f"{v:g}"


def _corpo(s: Stazione, modello: Modello, sezione: str, esistono: set[str]) -> str:
    def link(codice: str, nome: str | None) -> str:
        etichetta = _md(nome or codice)
        return (
            f"[{etichetta}]({_url_stazione(sezione, codice)})" if codice in esistono else etichetta
        )

    out: list[str] = []
    dove = [x for x in (s.citta if s.citta and s.citta != "A" else None, s.regione_nome) if x]
    riga = " · ".join([_md(x) for x in dove] + [f"code {s.codice}"])
    if s.lat is not None and s.lon is not None:
        riga += (
            f" · [map](https://www.openstreetmap.org/?mlat={s.lat}&mlon={s.lon}"
            f"#map=15/{s.lat}/{s.lon})"
        )
    out.append(riga)
    etichette = [t for t, c in (("terminus", s.capolinea), ("through station", s.transito)) if c]
    if etichette:
        out.append("**" + " · ".join(etichette) + "**")

    if not s.ha_dati:
        out.append(
            "> We have not observed any train at this station yet: it may be poorly served, "
            "or not yet reached by the data collection."
        )
        return "\n\n".join(out) + "\n"

    out.append(
        "## Overview\n\n"
        f"- Observed trips: **{s.n_corse}**\n"
        f"- Start here: **{s.n_nascono}**\n"
        f"- End here: **{s.n_finiscono}**\n"
        f"- Pass through: **{s.n_passano}**"
        + (
            f"\n- Partially cancelled (uncertain start or end): **{s.n_incerti}**"
            if s.n_incerti
            else ""
        )
    )

    righe = ["## Trains per day"]
    for f in s.frequenze:
        etichetta = _ETICHETTE_GIORNO.get(f.tipo_giorno, f.tipo_giorno)
        if f.corse_per_giorno is None:
            righe.append(f"**{etichetta}**: no data.")
            continue
        giorni = f"{f.n_giorni} day" + ("" if f.n_giorni == 1 else "s")
        riga = f"**{etichetta}**: {_numero(f.corse_per_giorno)} trips per day on average ({giorni} observed)."
        picchi = sorted(range(24), key=lambda h: (-f.per_ora[h], h))[:3]
        picchi = [h for h in picchi if f.per_ora[h] > 0]
        if picchi:
            riga += (
                " Busiest hours: "
                + ", ".join(f"{h:02d}:00 ({_numero(f.per_ora[h])})" for h in sorted(picchi))
                + "."
            )
        righe.append(riga)
    if modello.giorni.parziali:
        righe.append(
            "*Days with incomplete data, excluded from the averages: "
            + ", ".join(modello.giorni.parziali)
            + ".*"
        )
    out.append("\n\n".join(righe))

    if s.binari:
        out.append("## Platforms\n\n" + ", ".join(_md(b) for b in s.binari))
    if s.collegamenti:
        out.append(
            "## Connections\n\nWhere trains starting here go, and where trains ending here "
            "come from.\n\n" + " · ".join(_md(c) for c in s.collegamenti)
        )
    if s.linee:
        righe = [
            f"## Lines ({len(s.linee)})",
            "| Line | Here | Trains | Stops |\n|---|---|--:|--:|",
        ]
        righe[1] += "".join(
            f"\n| {_md(x.nome)} | {_RUOLI.get(x.ruolo, x.ruolo)} | {x.n_treni} | {x.n_fermate} |"
            for x in s.linee
        )
        out.append("\n\n".join(righe))
    if s.vicini:
        corpo = "".join(
            f"\n| {link(v.codice, v.nome)} | {v.n_treni} | "
            f"{'–' if v.durata_minuti is None else f'{v.durata_minuti:.0f} min'} | "
            f"{'–' if v.distanza_km is None else f'{v.distanza_km:.1f} km'} |"
            for v in s.vicini
        )
        out.append(
            "## Nearby stations\n\nPrevious and next stops of trains, with the median scheduled "
            "travel time.\n\n| Station | Trains | Duration | Distance |\n|---|--:|--:|--:|" + corpo
        )
    if s.tratte:
        voci = "\n".join(
            f"- towards {link(t.altro_nodo, t.altro_nome)} "
            f"(section {t.tratta_ab}/{t.tratta_ba}, region {t.regione_codice})"
            for t in s.tratte
        )
        out.append("## Track sections\n\n" + voci)
    return "\n\n".join(out) + "\n"


def _prepara_cartella(sez: Path) -> None:
    if sez.exists():
        if any(sez.iterdir()) and not (sez / MARCATORE).exists():
            raise SystemExit(
                f"{sez} esiste e non e' stata creata da viaggiatreno-sito-hugo "
                f"(manca {MARCATORE}): non la tocco"
            )
        shutil.rmtree(sez)
    sez.mkdir(parents=True)
    (sez / MARCATORE).write_text("Cartella generata da viaggiatreno-sito-hugo: non modificare.\n")


def render_hugo(
    modello: Modello,
    content_dir: str | Path,
    *,
    sezione: str = "trains",
    solo: set[str] | None = None,
    data: date | None = None,
) -> EsitoHugo:
    """Scrive le pagine in `<content_dir>/<sezione>/` (svuotata prima, vedi docstring)."""
    data = data or datetime.now(tz=UTC).date()
    sez = Path(content_dir) / sezione
    _prepara_cartella(sez)
    stazioni = [s for s in modello.stazioni.values() if solo is None or s.codice in solo]
    esistono = {s.codice for s in stazioni}

    (sez / "_index.md").write_text(
        _front(
            title="Italian trains",
            description="Stations of the Italian railway network: observed trains, lines, platforms",
            date=data.isoformat(),
        )
        + "\nData collected from the unofficial ViaggiaTreno APIs. It may be incomplete or wrong; "
        "this is not an official service.\n",
        encoding="utf-8",
    )
    regioni: dict[str, list[Stazione]] = {}
    for s in stazioni:
        regioni.setdefault(s.regione_nome or "Unknown region", []).append(s)
    for peso, (nome, lista) in enumerate(sorted(regioni.items()), start=1):
        cartella = sez / _slug(nome)
        cartella.mkdir(exist_ok=True)
        (cartella / "_index.md").write_text(
            _front(title=nome, date=data.isoformat(), weight=peso), encoding="utf-8"
        )
        for i, s in enumerate(sorted(lista, key=lambda x: (x.nome or x.codice, x.codice)), 1):
            testo = _front(
                title=s.nome or s.codice,
                description=f"{s.nome or s.codice} ({s.regione_nome or 'Unknown region'}): "
                "observed trains, lines and platforms",
                date=data.isoformat(),
                weight=i,
                url=_url_stazione(sezione, s.codice),
                showDate=False,
                showShare=False,
            )
            (cartella / f"{s.codice.lower()}.md").write_text(
                testo + "\n" + _corpo(s, modello, sezione, esistono), encoding="utf-8"
            )
    return EsitoHugo(sez, len(stazioni), len(regioni))


__all__ = ["EsitoHugo", "render_hugo"]
