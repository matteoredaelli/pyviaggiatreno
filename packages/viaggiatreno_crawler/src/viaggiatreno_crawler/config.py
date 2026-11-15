# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Configurazione del crawler (parametri da CLI)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfigEventi:
    """Parametri del crawler a eventi (coda di lavori con scadenza). Vedi eventi.py."""

    regione: int = 1  # 0 = tutta Italia; altrimenti solo le stazioni di quella regione
    # "statistiche": monitora ogni corsa (ritardi, binari) senza fine.
    # "orario": estrae l'orario programmato. Un treno si scarica una volta per (numero, origine,
    # tipo di giorno) e il record vale `orario_giorni_min`-`orario_giorni_max` giorni; una
    # stazione di transito si rilegge con la stessa scadenza, un capolinea ogni finestra.
    modalita: str = "statistiche"
    orario_giorni_min: int = 6
    orario_giorni_max: int = 14
    orario_ora_min: int = 8  # le scadenze cadono a un'ora locale casuale in [min, max)
    orario_ora_max: int = 15
    # Sonda dei capolinea in modalita' "orario": il tabellone copre ~1,4-1,7 h (misurato), si
    # richiama a 79 minuti (p10 della finestra) e, se un tabellone pieno e' piu' corto, 5 minuti
    # prima della sua fine.
    orario_sonda_sec: int = 4740
    orario_sonda_margine_sec: int = 300
    # Se i tabelloni di un capolinea sono vuoti (di notte, l'85-95% fra mezzanotte e le 3) si
    # richiama un po' piu' tardi. Un tabellone vuoto non dice nulla oltre la sua finestra
    # (da -15 minuti a +84-102 minuti, misurata), quindi oltre ~99 minuti si perderebbero le
    # partenze fra la fine della finestra e la lettura successiva: 90 minuti e' il massimo sicuro.
    orario_sonda_vuota_sec: int = 5400
    db_path: str = "data/eventi.db"

    # Limiti di carico. `richieste_al_secondo` e' il vero freno contro i 403 (distanzia
    # gli inizi delle richieste); `workers` limita solo quante sono in volo insieme.
    richieste_al_secondo: float = 1.0
    workers: int = 4

    # Sonda di un capolinea: il tabellone copre ~1,45-1,7 ore in avanti (misurato), quindi
    # lo si richiama a 75 minuti. Se un tabellone denso (>=15 righe) mostra una finestra
    # piu' corta, l'intervallo si accorcia (finestra osservata - margine). Il jitter
    # anticipa soltanto, per non sincronizzare le stazioni.
    sonda_intervallo_sec: int = 4500
    sonda_margine_sec: int = 600
    sonda_jitter: float = 0.1
    # Una stazione non capolinea si risonda solo ogni tanto, per scoprire nuove origini.
    ricensimento_sec: int = 86_400

    # Verifica del treno: una chiamata poco prima della partenza (itinerario, binari,
    # orari) e una dopo l'arrivo previsto a capolinea (esito, ritardo finale).
    verifica_anticipo_sec: int = 600
    verifica_margine_arrivo_sec: int = 600
    verifica_retry_sec: int = 300  # nuovo tentativo dopo un 204 o un treno non ancora arrivato
    verifica_scadenza_max_sec: int = 21_600  # oltre arrivo programmato + 6 h si rinuncia
    soglia_204: int = 5

    errore_attesa_sec: int = 300  # nuovo tentativo dopo un errore di rete
    dimensioni_ttl_sec: int = 86_400
    raw_json_completo: bool = False
    log_stats_sec: int = 60

    # Lavori periodici opzionali (0 = spenti), che alimentano le tabelle per tratta:
    # - `scopri_tratte`: elencoTratte + dettagliTratta -> tratte, tratte_osservazioni,
    #   avvistamenti_tratta, e treni circolanti (anche quelli senza tabellone).
    # - `scan_numeri`: cerca_numero_treno attorno ai numeri noti -> treni nuovi.
    tratte_intervallo_sec: int = 0
    categorie: str = "ES*,IC,EXP,EC,EN,REG"
    zoomlevel: int = 6
    scan_intervallo_sec: int = 0
    scan_finestra: int = 5
    scan_max_chiamate: int = 300

    rete_max_tentativi: int = 3
    rete_proxy: str | None = None
    rete_pausa_blocco_sec: float = 60.0
    rete_pausa_blocco_max_sec: float = 600.0
