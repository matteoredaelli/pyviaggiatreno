# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Analisi ("insight") sui dati restituiti dalle API: cosa si puo' dire di una stazione.

A differenza di `viaggiatreno.api` e `viaggiatreno.models` (wrapper degli endpoint), qui ci
sono solo calcoli su dati gia' scaricati: nessuna dipendenza da rete, MCP o database. Le
funzioni lavorano su `Corsa`, non sul modello grezzo dell'API, quindi valgono anche per dati
letti da altrove.

Vocabolario:

- **Corsa**: un treno sul tabellone di una stazione (partenza o arrivo);
- **Collegamento**: origine -> destinazione di un verso (dai tabelloni);
- **Itinerario**: la sequenza ordinata delle fermate di un treno, indipendente dal verso
  (da `andamentoTreno`);
- **Arco**: due fermate consecutive di un treno e il tratto tra loro (`ProfiloTreno`);
- **Tratta**: un segmento della rete, come nelle API `elencoTratte`/`dettagliTratta`.

- **Linea**: i treni che collegano gli stessi due estremi, in qualunque verso, con le varianti
  del loro itinerario (`costruisci_linee`). E' un raggruppamento calcolato, non una linea
  commerciale (R23, S8): questa non esiste nei dati.
"""

from viaggiatreno.insights.calendario import (
    TipoGiorno,
    data_di_servizio,
    data_locale,
    e_festivo_nazionale,
    offset_italia_ms,
    ora_locale_ms,
    pasqua,
    tipo_giorno,
)
from viaggiatreno.insights.collegamento import Collegamento
from viaggiatreno.insights.corsa import Corsa, TipoCorsa, da_tabellone, normalizza_nome
from viaggiatreno.insights.itinerario import Itinerario, Verso
from viaggiatreno.insights.linea import (
    Linea,
    RapportoItinerario,
    StatisticheArco,
    VarianteLinea,
    aggrega_archi,
    costruisci_linee,
    e_sottosequenza,
)
from viaggiatreno.insights.stazione import (
    BinarioStazione,
    CollegamentoStazione,
    Frequenza,
    ParametriProfilo,
    ProfiloStazione,
    Ruolo,
    RuoloTreno,
    TrenoInStazione,
    accoppia,
    calcola_frequenza,
    calcola_ruolo,
    finestra_comune,
    profilo_stazione,
    scarica_dettaglio,
    unisci_corse,
)
from viaggiatreno.insights.treno import (
    Arco,
    Avanzamento,
    FermataTreno,
    ProfiloTreno,
    StatoFermata,
    StatoTreno,
    avanzamento_di,
    distanza_km,
    ha_anomalie,
    profilo_treno,
)

__all__ = [
    "Arco",
    "Avanzamento",
    "BinarioStazione",
    "Collegamento",
    "CollegamentoStazione",
    "Corsa",
    "FermataTreno",
    "Frequenza",
    "Itinerario",
    "Linea",
    "ParametriProfilo",
    "ProfiloStazione",
    "ProfiloTreno",
    "RapportoItinerario",
    "Ruolo",
    "RuoloTreno",
    "StatisticheArco",
    "StatoFermata",
    "StatoTreno",
    "TipoCorsa",
    "TipoGiorno",
    "TrenoInStazione",
    "VarianteLinea",
    "Verso",
    "accoppia",
    "aggrega_archi",
    "avanzamento_di",
    "calcola_frequenza",
    "calcola_ruolo",
    "costruisci_linee",
    "da_tabellone",
    "data_di_servizio",
    "data_locale",
    "distanza_km",
    "e_festivo_nazionale",
    "e_sottosequenza",
    "finestra_comune",
    "ha_anomalie",
    "normalizza_nome",
    "offset_italia_ms",
    "ora_locale_ms",
    "pasqua",
    "profilo_stazione",
    "profilo_treno",
    "scarica_dettaglio",
    "tipo_giorno",
    "unisci_corse",
]
