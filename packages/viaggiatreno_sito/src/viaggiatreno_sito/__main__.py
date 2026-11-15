# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""`viaggiatreno-sito`: genera il sito statico da una copia del DB del crawler."""

from __future__ import annotations

import argparse
import sys

from viaggiatreno_sito import db
from viaggiatreno_sito.modello import costruisci_modello
from viaggiatreno_sito.render import render_sito


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="viaggiatreno-sito",
        description="Genera il sito statico (stazioni e linee) da una copia del DB del crawler.",
    )
    p.add_argument("--db-path", default="data/eventi.db", help="DB del crawler (non viene toccato)")
    p.add_argument("--out", default="sito", help="cartella di output (creata se manca)")
    p.add_argument(
        "--stazione",
        action="append",
        metavar="CODICE",
        help="genera solo questa stazione (ripetibile), es. S01322 per Monza",
    )
    p.add_argument(
        "--soglia-giorno",
        type=float,
        default=0.5,
        help="un giorno con meno di questa quota delle corse del giorno piu' ricco e' parziale",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        conn = db.apri_copia(args.db_path)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(2) from exc
    solo = set(args.stazione) if args.stazione else None
    modello = costruisci_modello(conn, soglia_giorno=args.soglia_giorno, solo=solo)
    if solo is not None and (mancanti := solo - set(modello.stazioni)):
        print(f"Stazioni non trovate: {', '.join(sorted(mancanti))}", file=sys.stderr)
        raise SystemExit(2)
    esito = render_sito(modello, args.out, solo=solo)
    con_dati = sum(1 for s in modello.stazioni.values() if s.ha_dati)
    print(f"{esito.n_stazioni} stazioni ({con_dati} con treni), {modello.n_linee} linee")
    print(
        f"giorni completi: {modello.giorni.completi or 'nessuno'} · parziali: {modello.giorni.parziali or 'nessuno'}"
    )
    print(
        f"scritto in {esito.cartella}/ ({len(esito.file)} file): apri {esito.cartella}/index.html"
    )


if __name__ == "__main__":
    main()
