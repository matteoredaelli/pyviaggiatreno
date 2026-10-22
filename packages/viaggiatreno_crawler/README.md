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
   `stops`/`regioni` popolate separatamente (poco variabili nel tempo).
4. Un treno viene rimosso dal tracking quando `arrivato=true`, `tipoTreno`
   indica soppressione, o dopo troppi `204` consecutivi.

## Schema

Vedi `storage.py` per lo schema SQL completo (tabelle `regioni`, `stops`,
`treni`, `fermate`, `tratte`, `tratte_osservazioni`, `avvistamenti_tratta`).

### Compatibilità con il GTFS Trenord

La tabella `stops` usa gli stessi nomi di colonna del file `stops.txt` del
GTFS Trenord (`stop_id`, `stop_name`, `stop_lat`, `stop_lon`, `stop_url`),
perché i codici stazione ViaggiaTreno sono identici agli `stop_id` GTFS
(vedi [TRENORD.md](../../TRENORD.md)). Puoi importare il file Trenord
direttamente:

```python
from viaggiatreno_crawler import storage

conn = storage.connect("data/treni.db")
storage.importa_stops_gtfs(conn, "trenord_gtfs/stops.txt")
```

Le righe si fondono (upsert) con quelle già presenti da ViaggiaTreno sulla
stessa chiave: ottieni una dimensione stazioni unica, con la copertura
nazionale di ViaggiaTreno più i campi aggiuntivi del GTFS (es. `stop_url`).

`treni`/`fermate` **non** sono invece traducibili 1:1 in `trips.txt`/
`stop_times.txt` del GTFS: quelle tabelle descrivono l'orario pianificato
teorico (stagionale), mentre `treni`/`fermate` sono osservazioni real-time
di istanze specifiche (un treno, un giorno, un ritardo misurato) — un
concetto che il GTFS statico non ha. Le colonne `route_id`/`trip_id` in
`treni` sono riservate per una futura correlazione, non popolate ora.

## Uso

```bash
uv run viaggiatreno-crawler run --regione 1 --intervallo-scoperta 300 --intervallo-verifica 900 --db-path data/treni.db
```

## Perché un package separato

La libreria core `viaggiatreno` resta un client HTTP puro (nessuna
dipendenza da SQLite); questo package contiene solo la logica applicativa
di raccolta/persistenza, non è pensato come libreria riusabile da altri.
