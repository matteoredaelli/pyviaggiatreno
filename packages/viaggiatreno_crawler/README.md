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
3. **Tabelloni** (`--intervallo-tabelloni`, opt-in): `partenze` delle stazioni
   note (con `--tabelloni-arrivi` anche gli `arrivi`: di default no, perché nelle
   stazioni di transito i due tabelloni elencano gli stessi treni). Intercetta
   treni che la scoperta per segmenti non vede e ne ricava direttamente
   numero+origine+data. Due fasce di stazioni, ordinate per numero di treni che
   *nascono* lì (i capolinea per primi, non i nodi di transito): le
   `--tabelloni-max-stazioni` principali (default 50) ad ogni ciclo, tutte le
   altre a rotazione, `--tabelloni-rare-per-giro` (default 10) per ciclo, così
   l'intero elenco viene coperto senza moltiplicare le chiamate. Con 345
   stazioni in Lombardia e un ciclo ogni 10 minuti la rotazione completa dura
   circa 5 ore.
4. **Scan-range** (`--intervallo-scan`, opt-in): sonda una finestra
   `±--scan-finestra` di numeri treno *attorno* a quelli già noti (non tra
   coppie: la numerazione è densa solo localmente) usando `cerca_numero_treno`
   come filtro, con tetto di chiamate per ciclo (`--scan-max-chiamate`).

**Persistenza**: upsert in SQLite (`treni`, `fermate`), dimensioni
`stops`/`regioni` popolate separatamente (poco variabili, ricaricate solo se
più vecchie di `--dimensioni-ttl`, default 24h).

Un treno viene rimosso dal tracking quando `arrivato=true`, `tipoTreno` indica
soppressione, o dopo troppi `204` consecutivi (`--soglia-204`).

### Rete: blocchi, retry e backoff

Il sito risponde `403 Forbidden` quando riceve troppe richieste ravvicinate. Le
chiamate passano da un trasporto HTTP resiliente (`rete.py`):

- su `403`/`429` **tutte** le richieste in volo si fermano per una pausa comune
  (`--rete-pausa-blocco`, default 60 s), che raddoppia a ogni blocco consecutivo
  fino a `--rete-pausa-blocco-max` (default 600 s) e si azzera al primo successo;
  se c'è un `Retry-After` in secondi viene rispettato;
- su `500/502/503/504` e su errori di rete: retry con backoff esponenziale;
- dopo `--rete-max-tentativi` (default 3) la richiesta fallisce e il ciclo
  **salta quell'elemento** e prosegue (prima un errore su un segmento
  interrompeva l'intero giro di scoperta).

#### Proxy

Dietro un proxy aziendale imposta le variabili d'ambiente standard prima di
lanciare il crawler (il sito si chiama in `http://`, quindi conta `HTTP_PROXY`):

```bash
export HTTP_PROXY=http://proxy.azienda.it:3128
export HTTPS_PROXY=http://proxy.azienda.it:3128   # ripiego se manca HTTP_PROXY
export NO_PROXY=localhost,127.0.0.1                # host da raggiungere senza proxy
# con credenziali: http://utente:password@proxy.azienda.it:3128
make crawler-tabelloni
```

oppure `--proxy http://proxy.azienda.it:3128`, che ha la precedenza
sull'ambiente. Nota: le maiuscole e le minuscole (`http_proxy`) sono equivalenti;
`ALL_PROXY` vale per tutto. Il traffico passa dal proxy anche per retry e pause
sui `403`. (Con un trasporto proprio httpx non legge più le variabili da solo:
lo fa `rete.py`.)

### Verifica: non prima della partenza

Un treno si controlla con `andamentoTreno` solo a partire da
`--verifica-anticipo` secondi prima della partenza programmata (default 900).
Prima la chiamata è quasi sempre inutile, e un `204` è normale. Un `204`
ricevuto *prima* della partenza non conta verso `--soglia-204`. I treni di cui
non si conosce l'orario di partenza si verificano sempre. Con un valore negativo
il filtro è disattivato (comportamento precedente).

### Spazio su disco

`raw_json` pesava circa il 70% del DB. Ora, per i treni regolari, la verifica
salva una versione compatta senza `fermate` (già nella tabella `fermate`); resta
completo per i treni con anomalie (cancellazioni parziali, deviazioni,
riprogrammazioni, note, cambi di numero, fermate non effettuate), o con
`--raw-json-completo`. Per ripulire un DB già popolato:

```bash
# FERMARE prima il crawler. Fa un backup, poi: orario_partenza, pulizia
# avvistamenti (>7 giorni), raw_json compatto, VACUUM.
make crawler-manutenzione
```

### Riavvio e throughput

- **Riavvio**: lo stato è su SQLite (upsert idempotenti) e i cicli salvano un
  checkpoint di avanzamento (tabella `crawler_stato`), quindi fermare e
  rilanciare riprende da dove si era interrotti invece di rifare il lavoro.
  Ogni ciclo ricorda anche l'**ora dell'ultimo giro concluso**: al riavvio
  aspetta solo il tempo che manca all'intervallo, invece di ripartire subito
  (un giro finito in errore non conta come fatto e si riprova). In più,
  indipendentemente dal ciclo che la richiede, **non si richiama la stessa
  risorsa troppo presto**: `andamentoTreno` sullo stesso treno non prima di
  `--verifica-min-intervallo` (default 300 s) e le partenze della stessa
  stazione non prima di `--tabellone-min-intervallo` (default 1800 s); 0 disattiva
  il minimo. Una richiesta fallita non conta come fatta.
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

## Schema del database

Tabelle, relazioni, esempi di contenuto (su una linea reale), query utili e
compatibilità con il GTFS Trenord sono in [README-DB.md](../../README-DB.md).

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
make crawler-tabelloni    # + tabelloni delle partenze
make crawler-full         # tutti e 4 i cicli (+ tabelloni + scan-range)
make crawler-nazionale    # come full ma REGIONE=0 (tutta Italia)

# parametri sovrascrivibili, es:
make crawler-full REGIONE=10 DB=data/lazio.db VERIFICA_CONCORRENZA=8
```

`viaggiatreno-crawler run --help` elenca tutti i flag.

## Perché un package separato

La libreria core `viaggiatreno` resta un client HTTP puro (nessuna
dipendenza da SQLite); questo package contiene solo la logica applicativa
di raccolta/persistenza, non è pensato come libreria riusabile da altri.
