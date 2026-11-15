# viaggiatreno-sito

Genera un **sito statico** con una pagina per stazione, dai dati del crawler
(`viaggiatreno-crawler`). Non c'è una pagina per treno: la pagina di una stazione elenca le linee
(percorsi con gli stessi due capolinea) e le tratte a cui appartiene.

```bash
make sito                       # tutte le stazioni, in sito/
make sito STAZIONE=S01322       # solo Monza
make sito DB=data/orario.db SITO_OUT=/tmp/sito
```

Si apre `sito/index.html` anche da file: i link sono relativi e non serve JavaScript (il filtro
dell'indice è solo un extra). Legge una **copia in memoria** del DB (API di backup di SQLite,
consistente anche col crawler acceso) e non modifica il file. Su un DB di 20.000 treni: 3.150
pagine, 18 MB, circa 3 secondi.

## Come è fatto

| Modulo | Cosa fa |
|---|---|
| `db.py` | Dal DB ai `ProfiloTreno` della libreria: ricostruisce una risposta di `andamentoTreno` da `treni.raw_json` e `fermate` e passa da `ProfiloTreno.da_status`, quindi itinerari e stati seguono le regole di sempre |
| `modello.py` | Per ogni stazione tutto ciò che la pagina mostra (ruolo, binari, linee, vicini, tratte, frequenze per tipo di giorno e ora locale), **senza HTML**. Si può scrivere in JSON |
| `render.py` + `templates/` | Il modello in pagine HTML (Jinja2, autoescape) più `dati/stazioni.json` |

Il modello è separato dal rendering di proposito: i conteggi si provano senza guardare le pagine
e il sito si può rigenerare con un altro strumento (per esempio Hugo) senza rifare i calcoli.

## Definizioni

Sono quelle delle viste SQL del crawler (`v_stops`), e un test verifica che coincidano:

- **origine/destinazione effettive**: prima e ultima fermata *non soppressa* del treno;
- **capolinea**: almeno un treno vi nasce o vi finisce; **transito**: almeno un treno vi passa.
  Possono valere insieme;
- un treno con una fermata soppressa è *parziale*: dove nasce e finisce è incerto (`n_incerti`);
- **frequenza**: corse medie *per giorno*, per tipo di giorno (`feriale`, `sabato`, `festivo`), sui
  soli giorni *completi*. Un giorno con meno del 50% delle corse del giorno più ricco è parziale
  (il crawler partito o fermo a metà) ed è escluso dalle medie, con un avviso nella pagina.

## Limiti

- **Durata dei tratti**: si ricava dagli orari teorici di arrivo e di partenza, salvati dal
  crawler solo dopo l'aggiunta delle colonne `fermate.arrivo_teorico`/`partenza_teorica`. Sulle
  corse precedenti la durata è nota solo per i tratti che partono dalla prima fermata; altrove la
  pagina mostra «–». Non si inventano valori.
- **Binari**: il crawler salva un solo binario per tipo (programmato, effettivo), non quello di
  arrivo distinto da quello di partenza. Su 557 corse confrontate con l'API, 12 (2%) ne perdono uno.
- **Ritardi**: non ci sono (la tabella `fermate` non ha gli orari reali di arrivo e di partenza).
- **Tipi di giorno**: sabato e festivo hanno dati solo dopo che il crawler ha girato in quei giorni.
- **Tratte**: solo le regioni caricate con `make tratte`; la maggior parte delle stazioni non ne ha.
- **Pubblicazione**: non verificato se sia permesso pubblicare dati delle API non ufficiali di
  ViaggiaTreno. Da decidere prima di mettere il sito online.
