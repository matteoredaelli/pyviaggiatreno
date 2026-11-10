# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Configurazione del crawler (parametri da CLI/env)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CrawlerConfig:
    regione: int = 1  # 0 = tutta Italia, 1 = Lombardia, ecc.
    categorie: str = "ES*,IC,EXP,EC,EN,REG"
    db_path: str = "data/treni.db"
    intervallo_scoperta_sec: int = 300  # 5 minuti: scansione elencoTratte/dettagliTratta
    intervallo_verifica_sec: int = 900  # 15 minuti: controllo andamentoTreno sui treni noti
    soglia_204: int = 5  # tentativi falliti prima di segnare un treno "non_disponibile"
    zoomlevel: int = 6  # valore verificato come il più completo (vedi VIAGGIATRENO.md)

    # Verifica: quante chiamate andamento_treno tenere in volo insieme. La
    # verifica scorre tutti i treni attivi in sequenza; con molti treni un
    # giro può sforare l'intervallo. La concorrenza limitata (Semaphore)
    # accelera ~Nx mantenendo il carico sull'API sotto controllo. 1 = seriale.
    verifica_concorrenza: int = 5
    # Tetto di treni verificati per giro: se gli attivi superano questo valore
    # se ne controllano al massimo N a giro (ripresi dal checkpoint), così un
    # giro non sfora mai l'intervallo a prescindere dal volume. 0 = nessun cap.
    verifica_max_per_giro: int = 0

    # TTL del caricamento dimensioni (regioni/stops): rieseguito solo se più
    # vecchio di questo valore, per non pagarne il costo a ogni riavvio.
    dimensioni_ttl_sec: int = 86_400  # 24h

    # Scoperta via tabelloni partenze/arrivi delle stazioni note (vedi
    # scopri_da_tabelloni): trova treni che elencoTratte/dettagliTratta non
    # vede (es. in sosta in stazione, o categorie/segmenti non coperti) e ne
    # ricava direttamente numero+origine+data, pronti per andamentoTreno.
    # 0 disabilita questo ciclo.
    intervallo_tabelloni_sec: int = 0
    # Quante stazioni sondare per ciclo, ordinate per traffico osservato
    # (le più trafficate hanno più probabilità di scoprire treni nuovi).
    # Evita di martellare tutte le ~3000 stazioni ad ogni giro.
    tabelloni_max_stazioni: int = 50

    # Scan-range (vedi scan_range_numeri): sonda una finestra +/-scan_finestra
    # ATTORNO a ciascun numero treno gia' noto (non tra coppie di numeri). I
    # test dal vivo mostrano densita' locale 50-70% in queste finestre, mentre
    # il range globale e' quasi tutto vuoto. Usa cerca_numero_treno come filtro
    # (fornisce origine+data) prima di andamentoTreno. 0 disabilita il ciclo.
    intervallo_scan_sec: int = 0
    scan_finestra: int = 5  # +/- numeri da sondare attorno a ogni numero noto
    scan_max_chiamate: int = 300  # tetto di cerca_numero_treno per ciclo
