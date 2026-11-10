# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""CLI minimale: `viaggiatreno-crawler run [opzioni]`."""

from __future__ import annotations

import argparse
import asyncio
import logging

from viaggiatreno_crawler import storage
from viaggiatreno_crawler.config import CrawlerConfig
from viaggiatreno_crawler.poller import run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="viaggiatreno-crawler")
    sub = parser.add_subparsers(dest="comando", required=True)
    p_man = sub.add_parser(
        "manutenzione",
        help="Operazioni una tantum sul DB (da lanciare a crawler FERMO)",
    )
    p_man.add_argument("--db-path", default="data/treni.db")
    p_man.add_argument(
        "--pulisci-avvistamenti",
        type=int,
        metavar="GIORNI",
        help="cancella gli avvistamenti_tratta piu' vecchi di GIORNI giorni",
    )
    p_man.add_argument(
        "--compatta-raw-json",
        action="store_true",
        help="toglie le fermate dal raw_json dei treni regolari arrivati (restano in `fermate`)",
    )
    p_man.add_argument(
        "--ricava-orario-partenza",
        action="store_true",
        help="valorizza treni.orario_partenza dai dati gia' presenti",
    )
    p_man.add_argument(
        "--vacuum",
        action="store_true",
        help="VACUUM finale per restituire spazio al filesystem (serve spazio libero pari al DB)",
    )
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
        help="secondi; >0 abilita la scoperta via tabelloni delle stazioni (0 = off)",
    )
    p_run.add_argument(
        "--tabelloni-max-stazioni",
        type=int,
        default=50,
        help="n. stazioni principali (da cui nascono più treni) sondate ad ogni ciclo",
    )
    p_run.add_argument(
        "--tabelloni-rare-per-giro",
        type=int,
        default=10,
        help="n. stazioni secondarie sondate a rotazione ad ogni ciclo (0 = mai)",
    )
    p_run.add_argument(
        "--tabelloni-arrivi",
        action="store_true",
        help="interroga anche gli arrivi delle stazioni (default: solo partenze)",
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
        "--verifica-anticipo",
        type=int,
        default=900,
        help="secondi prima della partenza programmata da cui si verifica un treno "
        "(default 900; negativo = verifica sempre, come prima)",
    )
    p_run.add_argument(
        "--verifica-min-intervallo",
        type=int,
        default=300,
        help="secondi minimi tra due chiamate andamentoTreno sullo stesso treno (0 = nessun minimo)",
    )
    p_run.add_argument(
        "--tabellone-min-intervallo",
        type=int,
        default=1800,
        help="secondi minimi tra due richieste delle partenze della stessa stazione (0 = nessun minimo)",
    )
    p_run.add_argument(
        "--raw-json-completo",
        action="store_true",
        help="salva sempre l'intero raw_json (default: completo solo per i treni con anomalie)",
    )
    p_run.add_argument(
        "--rete-max-tentativi",
        type=int,
        default=3,
        help="tentativi per richiesta HTTP su errori transitori/blocchi (1 = nessun retry)",
    )
    p_run.add_argument(
        "--proxy",
        default=None,
        help="proxy HTTP (es. http://proxy:3128); se omesso si usano HTTP_PROXY/HTTPS_PROXY/"
        "ALL_PROXY/NO_PROXY dall'ambiente",
    )
    p_run.add_argument(
        "--rete-pausa-blocco",
        type=float,
        default=60.0,
        help="secondi di pausa globale dopo un 403/429, raddoppia a ogni blocco consecutivo",
    )
    p_run.add_argument(
        "--rete-pausa-blocco-max",
        type=float,
        default=600.0,
        help="tetto in secondi della pausa dopo blocchi consecutivi",
    )
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
    return parser


def parse_args(argv: list[str] | None = None) -> CrawlerConfig:
    args = _parser().parse_args(argv)
    return CrawlerConfig(
        regione=args.regione,
        categorie=args.categorie,
        db_path=args.db_path,
        intervallo_scoperta_sec=args.intervallo_scoperta,
        intervallo_verifica_sec=args.intervallo_verifica,
        intervallo_tabelloni_sec=args.intervallo_tabelloni,
        tabelloni_max_stazioni=args.tabelloni_max_stazioni,
        tabelloni_rare_per_giro=args.tabelloni_rare_per_giro,
        tabelloni_arrivi=args.tabelloni_arrivi,
        intervallo_scan_sec=args.intervallo_scan,
        scan_finestra=args.scan_finestra,
        scan_max_chiamate=args.scan_max_chiamate,
        soglia_204=args.soglia_204,
        verifica_anticipo_sec=args.verifica_anticipo,
        raw_json_completo=args.raw_json_completo,
        verifica_min_intervallo_sec=args.verifica_min_intervallo,
        tabellone_min_intervallo_sec=args.tabellone_min_intervallo,
        rete_max_tentativi=args.rete_max_tentativi,
        rete_proxy=args.proxy,
        rete_pausa_blocco_sec=args.rete_pausa_blocco,
        rete_pausa_blocco_max_sec=args.rete_pausa_blocco_max,
        verifica_concorrenza=args.verifica_concorrenza,
        verifica_max_per_giro=args.verifica_max_per_giro,
        dimensioni_ttl_sec=args.dimensioni_ttl,
    )


def manutenzione(args: argparse.Namespace) -> None:
    """Esegue le operazioni di manutenzione richieste, nell'ordine sicuro."""
    import os

    if not os.path.exists(args.db_path):
        raise SystemExit(f"DB non trovato: {args.db_path}")
    fatto = False
    conn = storage.connect(args.db_path)
    try:
        if args.ricava_orario_partenza:
            n = storage.ricava_orario_partenza(conn)
            print(f"orario_partenza: {n} aggiornamenti")
            fatto = True
        if args.pulisci_avvistamenti is not None:
            n = storage.pulisci_avvistamenti_tratta(conn, args.pulisci_avvistamenti)
            print(
                f"avvistamenti_tratta: {n} righe cancellate (tenuti {args.pulisci_avvistamenti} giorni)"
            )
            fatto = True
        if args.compatta_raw_json:
            n, byte = storage.compatta_raw_json(conn)
            print(f"raw_json: {n} righe compattate (pesavano {byte / 1e6:.1f} MB prima)")
            fatto = True
        if args.vacuum:
            print("VACUUM in corso...")
            conn.execute("VACUUM")
            fatto = True
        if not fatto:
            print("Nessuna operazione richiesta: vedi `manutenzione --help`.")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    if args.comando == "manutenzione":
        manutenzione(args)
        return
    asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    main()
