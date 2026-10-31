# viaggiatreno-crawler

Poller/crawler che usa [`viaggiatreno`](../viaggiatreno) per raccogliere nel
tempo dati storici sui treni (numeri, ritardi, binari, fermate) e popolare un
database SQLite locale, utile per KPI giornalieri (treni partiti/arrivati,
ritardo medio/mediano, binari più usati per stazione, stazioni con più
traffico, ecc.) che le API ViaggiaTreno non espongono (nessuna delle API è
storica: tutto è "stato attuale").

## Architettura

Il crawler è **un unico processo** con un event loop `asyncio`: non ci sono
script separati. Avvia più cicli *concorrenti* (non paralleli: un solo thread,
le attività si alternano sfruttando i tempi di attesa della rete). Ogni ciclo
si attiva col proprio intervallo in secondi; intervallo `0` = ciclo spento.

1. **Scoperta** (`--intervallo-scoperta`, sempre attivo): polling di
   `elenco_tratte`/`dettagli_tratta` per la regione per trovare i treni
   attualmente in circolazione.
2. **Verifica** (`--intervallo-verifica`, sempre attivo): per ogni treno noto
   `andamento_treno` per ottenere l'intero percorso (`fermate[]`, con stazione
   e binario per ciascuna). Le chiamate sono concorrenti con limite
   (`--verifica-concorrenza`, default 5).
3. **Tabelloni** (`--intervallo-tabelloni`, opt-in): `partenze`/`arrivi` sulle
   stazioni note. Intercetta treni che la scoperta per segmenti non vede e ne
   ricava direttamente numero+origine+data. Sonda le stazioni più trafficate
   per prime (`--tabelloni-max-stazioni`).
4. **Scan-range** (`--intervallo-scan`, opt-in): sonda una finestra
   `±--scan-finestra` di numeri treno *attorno* a quelli già noti (non tra
   coppie: la numerazione è densa solo localmente) usando `cerca_numero_treno`
   come filtro, con tetto di chiamate per ciclo (`--scan-max-chiamate`).

**Persistenza**: upsert in SQLite (`treni`, `fermate`), dimensioni
`stops`/`regioni` popolate separatamente (poco variabili, ricaricate solo se
più vecchie di `--dimensioni-ttl`, default 24h).

Un treno viene rimosso dal tracking quando `arrivato=true`, `tipoTreno` indica
soppressione, o dopo troppi `204` consecutivi (`--soglia-204`).

### Riavvio e throughput

- **Riavvio**: lo stato è su SQLite (upsert idempotenti) e i cicli salvano un
  checkpoint di avanzamento (tabella `crawler_stato`), quindi fermare e
  rilanciare riprende da dove si era interrotti invece di rifare il lavoro.
  La chiusura su Ctrl-C/SIGTERM è pulita (commit finale). All'avvio i treni
  rimasti `in_corso` da giornate passate (crawler fermato a metà giornata e
  rilanciato più tardi) vengono chiusi subito, senza sprecare chiamate di
  verifica su treni ormai vecchi.
- **Throughput**: con molti treni attivi la verifica potrebbe non stare nel
  suo intervallo. Due difese: `--verifica-concorrenza` (parallelizza le
  chiamate HTTP, ~4-5× più veloce) e `--verifica-max-per-giro` (tetto di treni
  per giro, ripresi via checkpoint, così un giro non sfora mai l'intervallo).
  Se un giro sfora comunque, un warning lo segnala (i dati perdono freschezza
  ma non si accumula una coda illimitata).

## Schema

Vedi `storage.py` per lo schema SQL completo (tabelle `regioni`, `stops`,
`treni`, `fermate`, `tratte`, `tratte_osservazioni`, `avvistamenti_tratta`,
`crawler_stato`). Quest'ultima (chiave/valore) tiene il timestamp
dell'ultimo caricamento dimensioni e i checkpoint di avanzamento dei cicli,
per riprendere dopo un riavvio.

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

Solo scoperta + verifica (comportamento base):

```bash
uv run viaggiatreno-crawler run --regione 1 --db-path data/treni.db
```

Tutti i cicli attivi, con throughput ottimizzato:

```bash
uv run viaggiatreno-crawler run \
  --regione 1 --db-path data/treni.db \
  --intervallo-scoperta 300 --intervallo-verifica 900 \
  --verifica-concorrenza 5 --verifica-max-per-giro 0 \
  --intervallo-tabelloni 600 --tabelloni-max-stazioni 50 \
  --intervallo-scan 1800 --scan-finestra 5 --scan-max-chiamate 300
```

Dalla root del repo è più comodo usare il `Makefile` (vedi `make help`):

```bash
make crawler              # base: scoperta + verifica
make crawler-tabelloni    # + tabelloni partenze/arrivi
make crawler-scan         # + scan-range (include tabelloni)
make crawler-full         # tutti e 4 i cicli
make crawler-nazionale    # come full ma REGIONE=0 (tutta Italia)

# parametri sovrascrivibili, es:
make crawler-full REGIONE=10 DB=data/lazio.db VERIFICA_CONCORRENZA=8
```

`viaggiatreno-crawler run --help` elenca tutti i flag.

## Perché un package separato

La libreria core `viaggiatreno` resta un client HTTP puro (nessuna
dipendenza da SQLite); questo package contiene solo la logica applicativa
di raccolta/persistenza, non è pensato come libreria riusabile da altri.
