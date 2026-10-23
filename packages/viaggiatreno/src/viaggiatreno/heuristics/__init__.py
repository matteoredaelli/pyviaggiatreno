"""Euristiche di interpretazione derivate dai dati ViaggiaTreno.

A differenza di `viaggiatreno.api`/`viaggiatreno.models` (wrapper diretto
degli endpoint), questo sottopacchetto contiene logica che combina più
chiamate e assunzioni (es. correlazioni temporali) per inferire informazioni
che l'API non fornisce esplicitamente. Sono stime, non dati certi: ogni
funzione documenta le proprie assunzioni e i limiti noti.
"""

from viaggiatreno.heuristics.rotazione import (
    Predecessore,
    trova_predecessore,
    verifica_predecessore,
)

__all__ = ["Predecessore", "trova_predecessore", "verifica_predecessore"]
