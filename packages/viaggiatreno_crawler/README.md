# viaggiatreno-crawler

Poller/crawler che usa [`viaggiatreno`](../viaggiatreno) per raccogliere nel
tempo dati storici sui treni (numeri, ritardi, binari, fermate) e popolare un
database SQLite locale, utile per KPI giornalieri (treni partiti/arrivati,
ritardo medio/mediano, binari più usati per stazione, stazioni con più
traffico, ecc.) che le API ViaggiaTreno non espongono (nessuna delle API è
storica: tutto è "stato attuale").

## Architettura

Un **unico processo** `asyncio` con una **coda di lavori con scadenza**: ogni stazione
e ogni treno ha un "prossimo istante utile" e viene richiamato solo allora, invece di
rifare tutto a intervalli fissi. Un pool di worker (`--workers`, default 4) esegue i
lavori scaduti; un limitatore globale (`--richieste-al-secondo`, default 1) distanzia le
richieste verso il sito, perché è il ritmo (non quante sono in volo) a provocare i `403`.

| Lavoro | Cosa fa | Quando si ripete |
|---|---|---|
| `censisci_stazione` | partenze di una stazione nuova o non capolinea: scopre treni, origini e destinazioni | dopo `--ricensimento` (24 h) |
| `sonda_stazione` | partenze e arrivi di un **capolinea** (origine o destinazione di almeno un treno) | a 75 min (`--sonda-intervallo`), prima se un tabellone pieno ha una finestra più corta |
| `verifica_treno` | `andamentoTreno`: una volta poco prima della partenza (itinerario, orari, binari) e una dopo l'arrivo previsto (esito, ritardo finale) | non prima |
| `scopri_tratte` (opz.) | `elencoTratte` + `dettagliTratta`: segmenti, occupazione, avvistamenti, treni in circolazione | `--intervallo-tratte` |
| `scan_numeri` (opz.) | `cercaNumeroTreno` attorno ai numeri già noti (la numerazione è densa solo localmente) | `--intervallo-scan` |

Un tabellone copre da circa -12 minuti a +1,5 ore (misurato: 1,45–1,7 h in avanti), quindi
un capolinea non va richiamato prima. L'arrivo previsto di un treno è la sua ultima
fermata non soppressa più il ritardo attuale; se a quel punto non risulta arrivato si
ripianifica sul nuovo arrivo previsto, senza martellare. Queste regole (arrivo previsto, se la
corsa è in corso, arrivata o soppressa, se ha anomalie) non sono del crawler: stanno nella
libreria, in `viaggiatreno.insights.ProfiloTreno`, e il crawler le usa.

**Stazioni nuove.** Oltre a `elencoStazioni`, ogni stazione vista altrove viene censita
nella stessa tabella `stops` (con codice e nome), e parte subito un `censisci_stazione`.
La colonna `stops.fonte` dice da dove arriva (le provenienze si accumulano con `+`):
`viaggiatreno` (elencoStazioni), `gtfs_trenord`, `tabellone` (origine o destinazione di
una riga di partenze/arrivi), `itinerario` (fermata di `andamentoTreno`), `tratte`
(origine/destinazione di un treno trovato per segmento). Le stazioni scoperte da altre
API non hanno coordinate né regione finché non compaiono in `elencoStazioni`.

**Persistenza e riavvio.** Le scadenze stanno nel DB (`stops.prossima_sonda`,
`treni.prossima_verifica`): la coda in memoria si ricostruisce all'avvio, senza ricordare
nulla. Anche i lavori periodici (tratte, scan) riprendono dall'ora dell'ultimo giro. I
treni che superano di 6 ore l'arrivo previsto senza risultare arrivati si chiudono come
`scaduto`. Ogni richiesta di tabellone è registrata in `tabelloni_richieste` (utile per
misurare le finestre). La chiusura su Ctrl-C/SIGTERM è pulita.

Un treno esce dal tracking quando `arrivato=true`, `tipoTreno` indica soppressione, dopo
troppi `204` dalla partenza in poi (`--soglia-204`) o per scadenza. Un `204` *prima*
della partenza è normale e non conta.

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
make crawler-eventi
```

oppure `--proxy http://proxy.azienda.it:3128`, che ha la precedenza
sull'ambiente. Nota: le maiuscole e le minuscole (`http_proxy`) sono equivalenti;
`ALL_PROXY` vale per tutto. Il traffico passa dal proxy anche per retry e pause
sui `403`. (Con un trasporto proprio httpx non legge più le variabili da solo:
lo fa `rete.py`.)

### Spazio su disco

`raw_json` pesava circa il 70% del DB. Ora, per i treni regolari, la verifica
salva una versione compatta senza `fermate` (già nella tabella `fermate`); resta
completo per i treni con anomalie (cancellazioni parziali, deviazioni,
riprogrammazioni, note, cambi di numero, fermate non effettuate), o con
`--raw-json-completo`. Per ripulire un DB già popolato:

```bash
# FERMARE prima il crawler. Fa un backup, poi: cod_destinazione, orario_partenza, pulizia
# avvistamenti (>7 giorni), raw_json compatto, VACUUM.
make crawler-manutenzione
```

## Viste per dashboard e wiki

Il crawler crea all'avvio le viste SQL riassuntive (`v_stops`, `v_treno`, `v_stops_giorno`,
`v_stop_binari`, ...): stazioni con più binari, più treni, più destinazioni, ruolo di capolinea
o di transito. Per un DB già esistente o dopo un cambio delle definizioni: `make viste`. Non
scrivono dati e si possono creare anche a crawler acceso. Definizioni e limiti in
[README-DB.md](../../README-DB.md). Per un'analisi o un sito statico **leggere una copia** del
DB (`sqlite3 db ".backup copia.db"`), non il file in uso.

## Modalità `orario`: estrarre l'orario programmato

`make crawler-orario` (`--modalita orario`) non accumula ritardi: raccoglie l'**orario
programmato** (itinerario, fermate, tempi di percorrenza). Il motore è lo stesso; cambia
quando si richiama un lavoro. Per girare su tutta Italia: `make crawler-orario REGIONE=0`
(prima `make stazioni`).

| Oggetto | Regola |
|---|---|
| Treno nuovo | `andamentoTreno` come in `statistiche`: 10 minuti prima della partenza e dopo l'arrivo. Nessuna chiamata anticipata |
| Record del treno | uno per **(numero, origine, tipo di giorno)**, con `scade_orario` a 6-14 giorni (`--orario-giorni-min/max`) a un'ora locale casuale tra le 8 e le 15 (`--orario-ora-min/max`). Finché è valido le altre corse dello stesso tipo non si salvano né si verificano |
| Tipo di giorno | `feriale`, `sabato`, `festivo` (domeniche e festivi nazionali; `viaggiatreno.insights.tipo_giorno`). Non sono noti patroni locali, ponti, scioperi |
| Stazione nuova | partenze **e** arrivi |
| Stazione di transito | si rilegge alla scadenza casuale 6-14 giorni |
| Capolinea | partenze e arrivi ogni 79 minuti, o 5 minuti prima della fine di un tabellone pieno (≥ 8 righe) più corto; 90 minuti se i tabelloni sono vuoti |

La finestra dei tabelloni è stata misurata su 38.345 richieste di giorni feriali: 1,5-1,6 h in
avanti, uguale tra stazioni piccole e grandi e tra partenze e arrivi (scarto mediano 2 minuti), e
costante nell'arco del giorno; sotto 1,4 h il 2,3 % dei casi, da cui i 79 minuti. **Sabato e
domenica non sono misurati**: la prova di due settimane dirà se cambia.

`stops.fonte`, `treni` e le viste restano quelle della modalità `statistiche`; i record si
distinguono da `treni.scade_orario IS NOT NULL`. Per confrontare i tipi di giorno:
`SELECT tipo_giorno, COUNT(*) FROM treni GROUP BY 1`.

## Schema del database

Tabelle, relazioni, esempi di contenuto (su una linea reale), query utili e
compatibilità con il GTFS Trenord sono in [README-DB.md](../../README-DB.md).

## Uso

Dalla root del repo (vedi `make help`); si lancia **uno solo** dei tre, sullo stesso DB:

```bash
make crawler-eventi         # stazioni + capolinea + treni: il caso normale
make crawler-orario         # estrae l'orario programmato (vedi sotto)
make tratte                 # una tantum: i segmenti della rete (elencoTratte, regioni 0-22)
make errors N=50           # ultimi N errori (tabella `errori`; sola lettura, anche a crawler acceso)
make crawler-eventi-tratte  # + scoperta per segmenti (tratte, avvistamenti_tratta)
make crawler-eventi-full    # + scan dei numeri treno attorno ai noti

# parametri sovrascrivibili, es:
make crawler-eventi REGIONE=10 DB=data/lazio.db RICHIESTE_AL_SECONDO=0.5 WORKERS=2
```

Caricamento una tantum delle stazioni di tutta Italia (22 chiamate a `elencoStazioni`,
regioni 1-22; la 0 darebbe solo le "principali"). Si può lanciare anche a crawler acceso:
committa una regione alla volta e una regione che fallisce non ferma le altre.

```bash
make stazioni                                    # tutta Italia
make stazioni REGIONI_STAZIONI="--regione 1 --regione 5"
```

Anche i **segmenti della rete** (`tratte`: coppie di nodi, coordinate) cambiano di rado e si
caricano una tantum, senza treni né osservazioni: `make tratte` (23 chiamate a `elencoTratte`,
regioni 0-22). Le regioni 0 (Italia, 135 segmenti) e 1 (Lombardia, 99) sono **grafi diversi**: solo
1 coppia di nodi su 99 in comune (misurato), quindi non basta una sola regione. Lo scoprire i
treni attraverso i segmenti (`--intervallo-tratte`) è un'altra cosa, un giro ogni pochi minuti, e
serve solo alla modalità `statistiche`.

Oppure direttamente: `uv run viaggiatreno-crawler eventi --help` elenca tutti i flag.
`--regione 0` censisce le stazioni di tutte le regioni.

## Perché un package separato

La libreria core `viaggiatreno` resta un client HTTP puro (nessuna
dipendenza da SQLite); questo package contiene solo la logica applicativa
di raccolta/persistenza, non è pensato come libreria riusabile da altri.
