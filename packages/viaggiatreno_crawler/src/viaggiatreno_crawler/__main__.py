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
    p_run.add_argument(
        "--intervallo-tabelloni",
        type=int,
        default=0,
        help="secondi; >0 abilita la scoperta via partenze/arrivi delle stazioni (0 = off)",
    )
    p_run.add_argument(
        "--tabelloni-max-stazioni",
        type=int,
        default=50,
        help="n. stazioni da sondare per ciclo (le più trafficate prima)",
    )
    p_run.add_argument(
        "--intervallo-scan",
        type=int,
        default=0,
        help="secondi; >0 abilita lo scan-range attorno ai numeri noti (0 = off)",
    )
    p_run.add_argument(
        "--scan-finestra",
        type=int,
        default=5,
        help="+/- numeri da sondare attorno a ogni numero treno noto",
    )
    p_run.add_argument(
        "--scan-max-chiamate",
        type=int,
        default=300,
        help="tetto di chiamate cerca_numero_treno per ciclo di scan",
    )
    p_run.add_argument("--soglia-204", type=int, default=5)
    p_run.add_argument(
        "--verifica-concorrenza",
        type=int,
        default=5,
        help="n. chiamate andamento_treno concorrenti nella verifica (1 = seriale)",
    )
    p_run.add_argument(
        "--verifica-max-per-giro",
        type=int,
        default=0,
        help="max treni verificati per giro se gli attivi superano la soglia (0 = nessun cap)",
    )
    p_run.add_argument(
        "--dimensioni-ttl",
        type=int,
        default=86_400,
        help="secondi; ricarica regioni/stops solo se più vecchi di questo (default 24h)",
    )
    args = parser.parse_args(argv)
    return CrawlerConfig(
        regione=args.regione,
        categorie=args.categorie,
        db_path=args.db_path,
        intervallo_scoperta_sec=args.intervallo_scoperta,
        intervallo_verifica_sec=args.intervallo_verifica,
        intervallo_tabelloni_sec=args.intervallo_tabelloni,
        tabelloni_max_stazioni=args.tabelloni_max_stazioni,
        intervallo_scan_sec=args.intervallo_scan,
        scan_finestra=args.scan_finestra,
        scan_max_chiamate=args.scan_max_chiamate,
        soglia_204=args.soglia_204,
        verifica_concorrenza=args.verifica_concorrenza,
        verifica_max_per_giro=args.verifica_max_per_giro,
        dimensioni_ttl_sec=args.dimensioni_ttl,
    )


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = parse_args(argv)
    asyncio.run(run(config))


if __name__ == "__main__":
    main()
