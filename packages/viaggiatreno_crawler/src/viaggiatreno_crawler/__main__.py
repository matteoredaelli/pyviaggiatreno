# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""CLI: `viaggiatreno-crawler eventi [opzioni]` e `viaggiatreno-crawler manutenzione`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from viaggiatreno_crawler import storage, viste
from viaggiatreno_crawler.config import ConfigEventi
from viaggiatreno_crawler.eventi import run_eventi
from viaggiatreno_crawler.poller import run_stazioni, run_tratte


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
        "--ricava-destinazione",
        action="store_true",
        help="valorizza treni.cod_destinazione dall'ultima fermata non soppressa",
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
    p_tr = sub.add_parser(
        "tratte",
        help="Carica una tantum i segmenti della rete da elencoTratte (default: regioni 0-22)",
    )
    p_tr.add_argument("--db-path", default="data/eventi.db")
    p_tr.add_argument(
        "--regione",
        type=int,
        action="append",
        help="solo questa regione, 0 = Italia (ripetibile); se omesso 0-22",
    )
    p_tr.add_argument("--richieste-al-secondo", type=float, default=1.0)
    p_tr.add_argument("--proxy", default=None)
    p_er = sub.add_parser(
        "errori",
        help="Mostra gli ultimi errori registrati dal crawler (sola lettura, anche a crawler acceso)",
    )
    p_er.add_argument("--db-path", default="data/eventi.db")
    p_er.add_argument("--ultimi", type=int, default=20, metavar="N", help="quanti mostrare")
    p_vi = sub.add_parser(
        "viste",
        help="(Ri)crea le viste SQL per dashboard e wiki; non tocca i dati (si puo' lanciare a crawler acceso)",
    )
    p_vi.add_argument("--db-path", default="data/eventi.db")
    p_vi.add_argument(
        "--forza", action="store_true", help="ricrea anche se la versione e' invariata"
    )
    p_st = sub.add_parser(
        "stazioni",
        help="Carica una tantum le stazioni da elencoStazioni (default: tutta Italia, regioni 1-22)",
    )
    p_st.add_argument("--db-path", default="data/eventi.db")
    p_st.add_argument(
        "--regione",
        type=int,
        action="append",
        help="solo questa regione (ripetibile); se omesso tutte le 22",
    )
    p_st.add_argument("--richieste-al-secondo", type=float, default=1.0)
    p_st.add_argument("--proxy", default=None)
    p_ev = sub.add_parser(
        "eventi",
        help="Crawler a eventi: coda di lavori con scadenza (stazioni, capolinea, treni)",
    )
    p_ev.add_argument("--db-path", default="data/eventi.db")
    p_ev.add_argument(
        "--modalita",
        choices=("statistiche", "orario"),
        default="statistiche",
        help="statistiche = monitora ritardi e binari; orario = estrae l'orario programmato "
        "(un treno per numero/origine/tipo di giorno, record con scadenza 6-14 giorni)",
    )
    p_ev.add_argument("--orario-giorni-min", type=int, default=6)
    p_ev.add_argument("--orario-giorni-max", type=int, default=14)
    p_ev.add_argument("--orario-ora-min", type=int, default=8)
    p_ev.add_argument("--orario-ora-max", type=int, default=15)
    p_ev.add_argument("--regione", type=int, default=1, help="regione di partenza (0 = tutte)")
    p_ev.add_argument(
        "--richieste-al-secondo",
        type=float,
        default=1.0,
        help="limite globale di richieste al secondo (0 = nessun limite)",
    )
    p_ev.add_argument("--workers", type=int, default=4, help="lavori eseguiti in parallelo")
    p_ev.add_argument("--sonda-intervallo", type=int, default=4500, help="secondi tra due sonde")
    p_ev.add_argument("--sonda-margine", type=int, default=600, help="secondi di sovrapposizione")
    p_ev.add_argument("--ricensimento", type=int, default=86_400, help="secondi, non capolinea")
    p_ev.add_argument("--verifica-anticipo", type=int, default=600)
    p_ev.add_argument("--verifica-margine-arrivo", type=int, default=600)
    p_ev.add_argument("--verifica-retry", type=int, default=300)
    p_ev.add_argument("--verifica-scadenza-max", type=int, default=21_600)
    p_ev.add_argument("--soglia-204", type=int, default=5)
    p_ev.add_argument("--errore-attesa", type=int, default=300)
    p_ev.add_argument("--dimensioni-ttl", type=int, default=86_400)
    p_ev.add_argument("--raw-json-completo", action="store_true")
    p_ev.add_argument("--log-stats", type=int, default=60, help="secondi tra due righe di stato")
    p_ev.add_argument(
        "--intervallo-tratte",
        type=int,
        default=0,
        help="secondi; >0 abilita la scoperta per segmenti (elencoTratte/dettagliTratta) e "
        "salva tratte, tratte_osservazioni, avvistamenti_tratta (0 = off)",
    )
    p_ev.add_argument("--categorie", default="ES*,IC,EXP,EC,EN,REG")
    p_ev.add_argument("--zoomlevel", type=int, default=6)
    p_ev.add_argument(
        "--intervallo-scan",
        type=int,
        default=0,
        help="secondi; >0 abilita lo scan dei numeri treno attorno ai noti (0 = off)",
    )
    p_ev.add_argument("--scan-finestra", type=int, default=5)
    p_ev.add_argument("--scan-max-chiamate", type=int, default=300)
    p_ev.add_argument("--rete-max-tentativi", type=int, default=3)
    p_ev.add_argument("--proxy", default=None)
    p_ev.add_argument("--rete-pausa-blocco", type=float, default=60.0)
    p_ev.add_argument("--rete-pausa-blocco-max", type=float, default=600.0)
    return parser


def parse_args_eventi(argv: list[str] | None = None) -> ConfigEventi:
    args = _parser().parse_args(argv)
    return ConfigEventi(
        regione=args.regione,
        db_path=args.db_path,
        modalita=args.modalita,
        orario_giorni_min=args.orario_giorni_min,
        orario_giorni_max=args.orario_giorni_max,
        orario_ora_min=args.orario_ora_min,
        orario_ora_max=args.orario_ora_max,
        richieste_al_secondo=args.richieste_al_secondo,
        workers=args.workers,
        sonda_intervallo_sec=args.sonda_intervallo,
        sonda_margine_sec=args.sonda_margine,
        ricensimento_sec=args.ricensimento,
        verifica_anticipo_sec=args.verifica_anticipo,
        verifica_margine_arrivo_sec=args.verifica_margine_arrivo,
        verifica_retry_sec=args.verifica_retry,
        verifica_scadenza_max_sec=args.verifica_scadenza_max,
        soglia_204=args.soglia_204,
        errore_attesa_sec=args.errore_attesa,
        dimensioni_ttl_sec=args.dimensioni_ttl,
        raw_json_completo=args.raw_json_completo,
        log_stats_sec=args.log_stats,
        tratte_intervallo_sec=args.intervallo_tratte,
        categorie=args.categorie,
        zoomlevel=args.zoomlevel,
        scan_intervallo_sec=args.intervallo_scan,
        scan_finestra=args.scan_finestra,
        scan_max_chiamate=args.scan_max_chiamate,
        rete_max_tentativi=args.rete_max_tentativi,
        rete_proxy=args.proxy,
        rete_pausa_blocco_sec=args.rete_pausa_blocco,
        rete_pausa_blocco_max_sec=args.rete_pausa_blocco_max,
    )


def manutenzione(args: argparse.Namespace) -> None:
    """Esegue le operazioni di manutenzione richieste, nell'ordine sicuro."""
    import os

    if not os.path.exists(args.db_path):
        raise SystemExit(f"DB non trovato: {args.db_path}")
    fatto = False
    conn = storage.connect(args.db_path)
    try:
        if args.ricava_destinazione:
            n = storage.ricava_destinazione(conn)
            m = storage.ricava_capolinea(conn)
            print(f"cod_destinazione: {n} treni valorizzati; capolinea: {m} stazioni aggiornate")
            fatto = True
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


def mostra_errori(db_path: str, n: int) -> int:
    """Stampa gli ultimi `n` errori e un riepilogo per fonte. Apre il DB in sola lettura."""
    import os
    import sqlite3
    from datetime import UTC, datetime

    from viaggiatreno.insights import offset_italia_ms

    if not os.path.exists(db_path):
        print(f"DB non trovato: {db_path}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        esiste = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='errori'"
        ).fetchone()
        if esiste is None:
            print("Nessuna tabella `errori`: il crawler nuovo non ha ancora girato su questo DB.")
            return 0
        totali = conn.execute(
            "SELECT fonte, COUNT(*) n, MAX(ts) ultimo FROM errori GROUP BY fonte ORDER BY n DESC"
        ).fetchall()
        righe = storage.ultimi_errori(conn, max(n, 0))
    finally:
        conn.close()

    def quando(ms: int) -> str:
        t = datetime.fromtimestamp((ms + offset_italia_ms(ms)) / 1000, UTC)
        return t.strftime("%Y-%m-%d %H:%M:%S")

    if not totali:
        print("Nessun errore registrato.")
        return 0
    print("Riepilogo (ora italiana): " + " | ".join(f"{t['fonte']}: {t['n']}" for t in totali))
    print(f"\nUltimi {len(righe)} errori, dal piu' recente:")
    for r in righe:
        print(f"{quando(r['ts'])}  {r['fonte']:<20} {r['chiave'] or '-':<10} {r['messaggio']}")
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    if args.comando == "manutenzione":
        manutenzione(args)
        return
    if args.comando == "errori":
        raise SystemExit(mostra_errori(args.db_path, args.ultimi))
    if args.comando == "viste":
        import os

        if not os.path.exists(args.db_path):
            raise SystemExit(f"DB non trovato: {args.db_path}")
        conn = storage.connect(args.db_path)
        try:
            scritte = viste.aggiorna_viste(conn, forza=args.forza)
        finally:
            conn.close()
        print(
            f"viste {'ricreate' if scritte else 'gia aggiornate'} (versione {viste.versione()}): "
            + ", ".join(viste.VISTE)
        )
        return
    if args.comando == "tratte":
        errori = asyncio.run(
            run_tratte(
                args.db_path,
                args.regione,
                richieste_al_secondo=args.richieste_al_secondo,
                proxy=args.proxy,
            )
        )
        raise SystemExit(1 if errori else 0)
    if args.comando == "stazioni":
        errori = asyncio.run(
            run_stazioni(
                args.db_path,
                args.regione,
                richieste_al_secondo=args.richieste_al_secondo,
                proxy=args.proxy,
            )
        )
        raise SystemExit(1 if errori else 0)
    asyncio.run(run_eventi(parse_args_eventi(argv)))


if __name__ == "__main__":
    main()
