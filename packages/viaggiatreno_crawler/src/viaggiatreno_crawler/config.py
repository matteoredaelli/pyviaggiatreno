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

    # Verifica anticipata: un treno si controlla con andamentoTreno solo a partire
    # da `verifica_anticipo_sec` prima della partenza programmata. Prima di allora
    # la chiamata e' quasi sempre inutile (e un 204 e' normale). 0 = solo dalla
    # partenza in poi; un valore negativo disattiva il filtro (verifica sempre).
    verifica_anticipo_sec: int = 900

    # Intervalli minimi tra due chiamate allo STESSO elemento, indipendenti dal ciclo
    # che le richiede: dopo un riavvio (o con piu' cicli che toccano lo stesso treno)
    # evitano di richiamare subito cio' che e' appena stato letto. 0 = nessun minimo.
    verifica_min_intervallo_sec: int = 300  # andamentoTreno sullo stesso treno
    tabellone_min_intervallo_sec: int = 1800  # partenze della stessa stazione

    # Rete: retry/backoff sugli errori transitori e pausa globale dopo un blocco
    # (403/429) del sito. Vedi rete.py.
    rete_max_tentativi: int = 3
    # Proxy HTTP esplicito (es. "http://utente:password@proxy:3128"). Se None si
    # usano le variabili d'ambiente standard (HTTP_PROXY, HTTPS_PROXY, ALL_PROXY,
    # NO_PROXY).
    rete_proxy: str | None = None
    rete_pausa_blocco_sec: float = 60.0
    rete_pausa_blocco_max_sec: float = 600.0

    # raw_json: di default salvato per intero solo per i treni con anomalie
    # (cancellazioni parziali, deviazioni, riprogrammazioni, ...). Per gli altri
    # resta la versione compatta, senza `fermate` (gia' nella tabella `fermate`).
    raw_json_completo: bool = False

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
    # Stazioni "secondarie" (oltre le prime `tabelloni_max_stazioni`): non si
    # sondano ad ogni giro ma a rotazione, `tabelloni_rare_per_giro` per giro,
    # cosi' prima o poi si copre l'intero elenco senza moltiplicare le chiamate.
    # Una rotazione completa dura ceil(secondarie / N) giri. 0 = non sondarle mai.
    tabelloni_rare_per_giro: int = 10
    # Se True interroga anche gli arrivi di ogni stazione. Di default solo le
    # partenze: ogni treno compare nella partenza della sua stazione di origine,
    # e nelle stazioni di transito arrivi e partenze elencano gli stessi treni
    # (misurato dal vivo), quindi la seconda chiamata non aggiunge scoperte.
    tabelloni_arrivi: bool = False

    # Scan-range (vedi scan_range_numeri): sonda una finestra +/-scan_finestra
    # ATTORNO a ciascun numero treno gia' noto (non tra coppie di numeri). I
    # test dal vivo mostrano densita' locale 50-70% in queste finestre, mentre
    # il range globale e' quasi tutto vuoto. Usa cerca_numero_treno come filtro
    # (fornisce origine+data) prima di andamentoTreno. 0 disabilita il ciclo.
    intervallo_scan_sec: int = 0
    scan_finestra: int = 5  # +/- numeri da sondare attorno a ogni numero noto
    scan_max_chiamate: int = 300  # tetto di cerca_numero_treno per ciclo
