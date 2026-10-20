# viaggiatreno-crawler

Poller/crawler che usa [`viaggiatreno`](../viaggiatreno) per raccogliere nel
tempo dati storici sui treni (numeri, ritardi, binari, fermate) e popolare un
database SQLite locale, utile per KPI giornalieri (treni partiti/arrivati,
ritardo medio/mediano, binari più usati per stazione, stazioni con più
traffico, ecc.) che le API ViaggiaTreno non espongono (nessuna delle API è
storica: tutto è "stato attuale").

## Architettura

1. **Scoperta**: polling periodico di `elenco_tratte`/`dettagli_tratta` (per
   regione) per trovare i numeri di treno attualmente in circolazione.
2. **Arricchimento**: per ogni treno scoperto, `andamento_treno` per ottenere
   l'intero percorso (`fermate[]`, con stazione e binario per ciascuna).
3. **Persistenza**: upsert in SQLite (`treni`, `fermate`), dimensioni
   `stazioni`/`regioni` popolate separatamente (poco variabili nel tempo).
4. Un treno viene rimosso dal tracking quando `arrivato=true`, `tipoTreno`
   indica soppressione, o dopo troppi `204` consecutivi.

## Schema

Vedi `storage.py` per lo schema SQL completo (tabelle `regioni`, `stazioni`,
`treni`, `fermate`).

## Uso

```bash
uv run viaggiatreno-crawler run --regione 1 --intervallo-scoperta 300 --intervallo-verifica 900 --db-path data/treni.db
```

## Perché un package separato

La libreria core `viaggiatreno` resta un client HTTP puro (nessuna
dipendenza da SQLite); questo package contiene solo la logica applicativa
di raccolta/persistenza, non è pensato come libreria riusabile da altri.
