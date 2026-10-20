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
