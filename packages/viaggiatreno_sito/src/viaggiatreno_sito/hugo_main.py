# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""`viaggiatreno-sito-hugo`: aggiunge le pagine delle stazioni a un sito Hugo esistente."""

from __future__ import annotations

import argparse
import sys

from viaggiatreno_sito import db
from viaggiatreno_sito.hugo import render_hugo
from viaggiatreno_sito.modello import costruisci_modello


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="viaggiatreno-sito-hugo",
        description="Scrive le pagine markdown delle stazioni in content/<sezione>/ di un sito "
        "Hugo esistente (nessun layout: si usa il tema del sito).",
    )
    p.add_argument("--db-path", default="data/eventi.db", help="DB del crawler (non viene toccato)")
    p.add_argument(
        "--content-dir",
        required=True,
        help="cartella content/ del sito Hugo, es. ~/siti/miosito/content",
    )
    p.add_argument("--sezione", default="trains", help="sottocartella di content/ (default trains)")
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
    esito = render_hugo(modello, args.content_dir, sezione=args.sezione, solo=solo)
    print(f"{esito.n_stazioni} stazioni in {esito.n_regioni} regioni: scritte in {esito.cartella}/")


if __name__ == "__main__":
    main()
