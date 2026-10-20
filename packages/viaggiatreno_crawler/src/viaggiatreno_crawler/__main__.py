"""CLI minimale: `viaggiatreno-crawler run [opzioni]`."""

from __future__ import annotations

import argparse
import asyncio
import logging

from viaggiatreno_crawler.config import CrawlerConfig
from viaggiatreno_crawler.poller import run


def parse_args(argv: list[str] | None = None) -> CrawlerConfig:
    parser = argparse.ArgumentParser(prog="viaggiatreno-crawler")
    sub = parser.add_subparsers(dest="comando", required=True)
    p_run = sub.add_parser("run", help="Avvia i cicli di scoperta e verifica")
    p_run.add_argument("--regione", type=int, default=1)
    p_run.add_argument("--categorie", default="ES*,IC,EXP,EC,EN,REG")
    p_run.add_argument("--db-path", default="data/treni.db")
    p_run.add_argument("--intervallo-scoperta", type=int, default=300, help="secondi")
    p_run.add_argument("--intervallo-verifica", type=int, default=900, help="secondi")
    p_run.add_argument("--soglia-204", type=int, default=5)
    args = parser.parse_args(argv)
    return CrawlerConfig(
        regione=args.regione,
        categorie=args.categorie,
        db_path=args.db_path,
        intervallo_scoperta_sec=args.intervallo_scoperta,
        intervallo_verifica_sec=args.intervallo_verifica,
        soglia_204=args.soglia_204,
    )


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = parse_args(argv)
    asyncio.run(run(config))


if __name__ == "__main__":
    main()
