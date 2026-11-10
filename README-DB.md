# README-DB: schema del database del crawler

Il crawler (`viaggiatreno-crawler`) salva tutto in un unico file SQLite (default `data/treni.db`, modalità WAL). Questo documento descrive le tabelle, come si collegano e che aspetto hanno i dati.

**Tratta di riferimento per gli esempi: Lecco → Calolziocorte → Carnate → Monza → Milano Porta Garibaldi (S8).** I valori sono righe reali del DB del 4 novembre 2026: treno `REG 24825` Lecco → Milano Porta Garibaldi, partenza prevista alle 07:06, arrivato alle 08:12.

Convenzioni:
- Tutti i timestamp sono **millisecondi Unix (UTC)**. Negli esempi ho aggiunto l'ora locale (Europe/Rome) tra parentesi.
- `data_partenza_treno` è la mezzanotte italiana del giorno di partenza, in ms. Per il 4/11/2026 vale `1793746800000`.
- Un treno è identificato dalla terna `(numero_treno, cod_origine, data_partenza_treno)`. Il solo numero non è univoco.

## Mappa delle tabelle

```
regioni ──< stops >──────────────┐
                                 │ stop_id
treni ──< fermate >──────────────┘
  │
  └──< avvistamenti_tratta >── (regione_codice, tratta_ab, tratta_ba) ──> tratte
                                                                             ^
tratte_osservazioni ─────── (regione_codice, tratta_ab, tratta_ba) ─────────┘

crawler_stato   (chiave/valore, indipendente)
```

| Tabella | Tipo | Cosa contiene | Chi la scrive |
|---|---|---|---|
| `regioni` | dimensione | Codici regione ViaggiaTreno | caricamento dimensioni |
| `stops` | dimensione | Stazioni, con coordinate | caricamento dimensioni (ogni 24h) |
| `treni` | fatto | Una riga per corsa (treno + giorno) | scoperta, tabelloni, scan, verifica |
| `fermate` | fatto | Le fermate di ogni treno, con orari e binari | verifica (`andamentoTreno`) |
| `tratte` | dimensione | Segmenti di rete tra due nodi | scoperta |
| `tratte_osservazioni` | serie storica | Segmento occupato o libero, a ogni scansione | scoperta |
| `avvistamenti_tratta` | serie storica | Quale treno è stato visto su quale segmento | scoperta |
| `crawler_stato` | tecnica | Checkpoint per riprendere dopo un riavvio | tutti i cicli |

---

## `regioni`

Codici regione ViaggiaTreno, caricati dalla costante `REGIONS` della libreria.

| Colonna | Tipo | Note |
|---|---|---|
| `codice` | INTEGER PK | 0 = Italia, 1 = Lombardia, ... 22 |
| `nome` | TEXT | |

```
codice  nome
------  ----------------------------
     0  Italia (stazioni principali)
     1  Lombardia
     2  Liguria
```

## `stops`

Stazioni. La chiave e i nomi delle colonne coincidono con `stops.txt` del GTFS Trenord, perché i codici stazione ViaggiaTreno (`S01700`) sono identici agli `stop_id` del GTFS.

| Colonna | Tipo | Note |
|---|---|---|
| `stop_id` | TEXT PK | Codice stazione, `S` + 5 cifre |
| `stop_name` | TEXT | Nome in maiuscolo |
| `stop_lat`, `stop_lon` | REAL | Coordinate WGS84 |
| `stop_url` | TEXT | Solo da GTFS, altrimenti NULL |
| `regione_codice` | INTEGER | FK → `regioni` |
| `citta` | TEXT | Città come la dà l'API (vedi note) |
| `fonte` | TEXT | `viaggiatreno`, `gtfs_trenord` o `viaggiatreno+gtfs_trenord` |
| `ultimo_aggiornamento` | INTEGER | ms |

```
stop_id  stop_name               stop_lat   stop_lon  stop_url  regione_codice  citta           fonte
S01520   LECCO                   45.856471  9.393638  NULL      1               Lecco           viaggiatreno
S01511   CARNATE USMATE          45.653072  9.375089  NULL      1               Carnate Usmate  viaggiatreno
S01645   MILANO PORTA GARIBALDI  45.484917  9.187683  NULL      1               A               viaggiatreno
```

Note:
- `citta = 'A'` è un segnaposto dell'API (nessuna città), non un dato vero. Succede per Porta Garibaldi.
- Oggi `fonte` vale sempre `viaggiatreno`: nessun `stops.txt` di Trenord è stato importato.

### Import del GTFS Trenord

```python
from viaggiatreno_crawler import storage

conn = storage.connect("data/treni.db")
storage.importa_stops_gtfs(conn, "trenord_gtfs/stops.txt")
```

Le righe si fondono (upsert) con quelle già presenti sulla stessa chiave: restano `regione_codice` e `citta` di ViaggiaTreno, si aggiunge `stop_url` dal GTFS e `fonte` diventa `viaggiatreno+gtfs_trenord`.

`treni` e `fermate` **non** sono traducibili in `trips.txt` e `stop_times.txt`: il GTFS descrive l'orario pianificato di una stagione, queste tabelle contengono osservazioni reali di singole corse, con ritardi misurati. Le colonne `treni.route_id` e `treni.trip_id` sono riservate a una futura correlazione e oggi sono sempre NULL.

## `treni`

Una riga per ogni corsa vista dal crawler.

| Colonna | Tipo | Note |
|---|---|---|
| `id` | INTEGER PK | Autoincrement, usato dalle FK |
| `numero_treno` | INTEGER | |
| `cod_origine` | TEXT | Stazione di origine (`stops.stop_id`) |
| `data_partenza_treno` | INTEGER | Mezzanotte italiana del giorno di partenza, ms |
| `categoria` | TEXT | `REG`, `IC`, `EC`, ... Per le Frecce è vuota |
| `cod_destinazione`, `origine`, `destinazione` | TEXT | Codice e nomi |
| `codice_cliente` | INTEGER | Impresa: 63 = Trenord, 1 = Trenitalia AV, ... |
| `stato` | TEXT | `in_corso`, `arrivato`, `soppresso`, `non_disponibile` |
| `ritardo_corrente` | INTEGER | Minuti, all'ultimo rilevamento |
| `ritardo_finale` | INTEGER | Minuti all'arrivo. NULL finché non è `arrivato` |
| `tentativi_204` | INTEGER | Risposte vuote consecutive di `andamentoTreno` |
| `primo_avvistamento`, `ultimo_aggiornamento` | INTEGER | ms |
| `raw_json` | TEXT | Ultima risposta dell'API, per ricalcoli futuri |
| `route_id`, `trip_id` | TEXT | Riservate, sempre NULL |

Vincolo: `UNIQUE (numero_treno, cod_origine, data_partenza_treno)`.

```
id=1038001  numero_treno=24825  cod_origine=S01520  data_partenza_treno=1793746800000 (04/11/2026 00:00)
categoria=REG  cod_destinazione=S01645  origine=LECCO  destinazione=MILANO PORTA GARIBALDI
codice_cliente=63  stato=arrivato  ritardo_corrente=4  ritardo_finale=4  tentativi_204=0
primo_avvistamento=1793776975714 (08:22:55)  ultimo_aggiornamento=1793778313292 (08:45:13)
route_id=NULL  trip_id=NULL  raw_json=<8758 caratteri>
```

Ciclo di vita di `stato`:
- Alla scoperta (segmenti, tabelloni o scan) il treno nasce `in_corso`.
- La verifica interroga `andamentoTreno` e lo porta a `arrivato` (con `ritardo_finale`) o `soppresso`.
- Dopo `--soglia-204` risposte vuote di fila diventa `non_disponibile`. Succede anche all'avvio ai treni `in_corso` di giornate passate.

## `fermate`

Le fermate commerciali di un treno, ricavate da `andamentoTreno`. A ogni verifica le righe del treno vengono rimpiazzate.

| Colonna | Tipo | Note |
|---|---|---|
| `id` | INTEGER PK | |
| `treno_id` | INTEGER | FK → `treni.id` (cancellazione a cascata) |
| `stop_id` | TEXT | FK → `stops.stop_id` |
| `progressivo` | INTEGER | Posizione nell'itinerario completo |
| `tipo_fermata` | TEXT | `P` origine, `F` intermedia, `A` destinazione |
| `orario_programmato`, `orario_effettivo` | INTEGER | ms. L'effettivo è NULL se non ancora rilevato |
| `ritardo` | INTEGER | Minuti |
| `binario_programmato`, `binario_effettivo` | TEXT | Di partenza, o di arrivo se manca |
| `actual_fermata_type` | INTEGER | 1 effettuata, 0 non ancora, 2 non prevista, 3 soppressa |

Fermate di `24825` (`treno_id = 1038001`):

```
stop_id  stop_name               prog  tipo  programmato (ora)  effettivo (ora)  rit  bin_prog  bin_eff
S01520   LECCO                      1   P     07:06              07:08              2  3         3
S01522   LECCO MAGGIANICO           2   F     07:10              07:14              3  1         1
S01524   CALOLZIOCORTE OLGINATE     4   F     07:15              07:20              4  2         2
S01515   AIRUNO                     5   F     07:21              07:25              4  1         1
S01514   OLGIATE-CALCO-BRIVIO       6   F     07:25              07:29              3  2         2
S01513   CERNUSCO-MERATE            7   F     07:30              07:33              2  1         1
S01512   OSNAGO                     8   F     07:34              07:36              2  1         1
S01511   CARNATE USMATE             9   F     07:39              07:43              3  3         3
S01510   ARCORE                    10   F     07:44              07:49              4  2         2
S01322   MONZA                     11   F     07:51              07:56              5  5         5
S01325   SESTO S.GIOVANNI          12   F     07:56              08:03              6  2         2
S01326   MILANO GRECO PIRELLI      13   F     08:01              08:07              6  2         2
S01645   MILANO PORTA GARIBALDI    15   A     08:08              08:12              4  17        20
```

Note:
- `progressivo` ha dei salti (3 e 14 mancano): conta anche le località non commerciali, che qui non compaiono.
- Il binario di Porta Garibaldi è cambiato (17 programmato, 20 effettivo).
- Il `ritardo` dell'ultima fermata è il ritardo all'arrivo: il crawler lo copia in `treni.ritardo_finale`.

## `tratte`

I segmenti della rete restituiti da `elencoTratte`, cioè coppie di nodi consecutivi.

| Colonna | Tipo | Note |
|---|---|---|
| `regione_codice` | INTEGER | Parametro `idRegione` usato nella chiamata |
| `tratta_ab`, `tratta_ba` | INTEGER | ID del segmento nei due sensi |
| `nodo_a`, `nodo_b` | TEXT | Codici dei nodi agli estremi |
| `lat_a`, `lon_a`, `lat_b`, `lon_b` | REAL | Coordinate degli estremi |
| `parent_ab`, `parent_ba` | INTEGER | Segmento padre, spesso NULL |
| `ultimo_aggiornamento` | INTEGER | ms |

Chiave primaria: `(regione_codice, tratta_ab, tratta_ba)`. La chiave include la regione perché gli ID dei segmenti sono numerati **per regione**: lo stesso `tratta_ab` può indicare tratti diversi con `idRegione` diverso.

I quattro segmenti della linea (`regione_codice = 1`):

```
tratta_ab  tratta_ba  nodo_a  nodo_b  (stazioni)                          lat_a      lon_a     lat_b      lon_b
43         125        S01520  S01524  Lecco → Calolziocorte Olginate      45.856471  9.393638  45.801619  9.42698
44         126        S01524  S01511  Calolziocorte Olginate → Carnate    45.801619  9.42698   45.653072  9.375089
45         127        S01511  S01322  Carnate Usmate → Monza              45.653072  9.375089  45.577789  9.273253
5          87         S01322  S01700  Monza → Milano Centrale             45.577789  9.273253  45.486347  9.204528
```

Il grafo della Lombardia termina a **Milano Centrale** (`S01700`): i treni per Porta Garibaldi compaiono comunque sul segmento `5/87`, ma con la destinazione reale scritta nel treno.

## `tratte_osservazioni`

Un record per segmento a ogni scansione di `elencoTratte`, anche quando il segmento è libero. Serve a calcolare quanto un segmento è occupato nel tempo.

| Colonna | Tipo | Note |
|---|---|---|
| `id` | INTEGER PK | |
| `regione_codice`, `tratta_ab`, `tratta_ba` | INTEGER | → `tratte` |
| `ts_poll` | INTEGER | ms |
| `occupata` | INTEGER | 1 se almeno un treno era presente, 0 altrimenti |

```
id     regione_codice  tratta_ab  tratta_ba  ts_poll                      occupata
44587  1               45         127        1793778875218 (04/11 08:54)  1
44488  1               45         127        1793778635318 (04/11 08:50)  1
44389  1               45         127        1793778328431 (04/11 08:45)  1
```

## `avvistamenti_tratta`

Collega un treno al segmento su cui `dettagliTratta` lo ha trovato.

| Colonna | Tipo | Note |
|---|---|---|
| `id` | INTEGER PK | |
| `treno_id` | INTEGER | FK → `treni.id` (cascata) |
| `regione_codice`, `tratta_ab`, `tratta_ba` | INTEGER | → `tratte` |
| `ts_poll` | INTEGER | ms |

Avvistamenti di `24825`:

```
id      treno_id  regione_codice  tratta_ab  tratta_ba  ts_poll
322938  1038001   1               5          87         1793776975714 (08:22:55)
323191  1038001   1               5          87         1793777280761 (08:28:00)
323439  1038001   1               5          87         1793778020427 (08:40:20)
```

## `crawler_stato`

Chiave/valore, per riprendere i cicli dopo un riavvio.

| Chiave | Significato |
|---|---|
| `dimensioni_ultimo_caricamento_ms` | Quando sono state ricaricate `regioni` e `stops` |
| `checkpoint_tabelloni_idx` | Avanzamento del ciclo tabelloni |
| `checkpoint_scan_idx` | Avanzamento dello scan-range |
| `checkpoint_verifica_id` | Ultimo `treni.id` verificato |

```
chiave                            valore
dimensioni_ultimo_caricamento_ms  1793776975120
checkpoint_tabelloni_idx          0
checkpoint_scan_idx               3690
checkpoint_verifica_id            1039536
```

---

## Query di esempio (sulla stessa linea)

Ritardo medio per fermata, sui treni Lecco → Porta Garibaldi arrivati:

```sql
SELECT s.stop_name, ROUND(AVG(f.ritardo), 1) AS rit_medio, COUNT(*) AS n
FROM fermate f
JOIN treni t ON t.id = f.treno_id
JOIN stops s ON s.stop_id = f.stop_id
WHERE t.cod_origine = 'S01520' AND t.cod_destinazione = 'S01645' AND t.stato = 'arrivato'
GROUP BY f.stop_id
ORDER BY MIN(f.progressivo);
```
```
stop_name               rit_medio  n
LECCO                   2.7        62
LECCO MAGGIANICO        3.5        62
CALOLZIOCORTE OLGINATE  3.3        62
AIRUNO                  3.0        62
...
```

Binari usati a Monza dai treni della linea:

```sql
SELECT f.binario_effettivo, COUNT(*) AS n
FROM fermate f JOIN treni t ON t.id = f.treno_id
WHERE f.stop_id = 'S01322' AND t.cod_origine = 'S01520' AND t.cod_destinazione = 'S01645'
  AND f.binario_effettivo IS NOT NULL
GROUP BY 1 ORDER BY n DESC;
```
```
binario_effettivo  n
5                  67
```

KPI di una giornata (3/11/2026) per la linea:

```sql
SELECT COUNT(*) AS treni,
       SUM(stato = 'arrivato') AS arrivati,
       ROUND(AVG(CASE WHEN stato = 'arrivato' THEN ritardo_finale END), 2) AS rit_medio,
       ROUND(100.0 * SUM(stato = 'arrivato' AND ritardo_finale > 5)
             / NULLIF(SUM(stato = 'arrivato'), 0), 1) AS pct_oltre_5min
FROM treni
WHERE cod_origine = 'S01520' AND cod_destinazione = 'S01645'
  AND data_partenza_treno = 1793660400000;
```
```
treni  arrivati  rit_medio  pct_oltre_5min
21     20        2.65       15.0
```

SQLite non ha `MEDIAN`: per la mediana si leggono i `ritardo_finale` e si calcola in Python (`storage.ritardi_arrivati()`).

---

## Cose da sapere leggendo i dati

Osservate sul DB reale, non dedotte dal codice.

1. **`stato` non è sempre affidabile per i treni già conclusi.** Nel DB ci sono 405 treni non `arrivato` (344 `non_disponibile` e 61 `in_corso`) la cui ultima fermata risulta già effettuata ma con `ritardo_finale` NULL. Per i `non_disponibile` la causa probabile è che l'API abbia smesso di rispondere prima che il crawler registrasse l'arrivo (non l'ho verificato); i 61 `in_corso` sono del giorno corrente e probabilmente non ancora riverificati. Per un KPI di puntualità conta solo `stato = 'arrivato'` e tieni presente che il campione è un sottoinsieme.
2. **`raw_json` ha due forme.** Se l'ultimo aggiornamento viene dalla verifica (`andamentoTreno`) contiene l'intero itinerario, con `tipoTreno` e `fermate`. Se il treno è stato solo scoperto (segmenti, tabelloni) contiene la riga di tabellone, senza fermate.
3. **`regione_codice = 0` e `1` sono due grafi diversi.** `tratte` contiene 91 segmenti per la regione 0 e 99 per la regione 1, con ID che non si corrispondono. Nel DB, la tratta `104/213` della regione 0 è Como–Chiasso, mentre oggi la stessa chiamata la restituisce come Milano Centrale–Como. Per analizzare una linea lombarda usa `regione_codice = 1`. Il dato 0 vale solo come fotografia del momento in cui è stato scritto.
4. **I treni compaiono sui segmenti solo mentre transitano.** `avvistamenti_tratta` e `tratte_osservazioni` descrivono ciò che il crawler ha visto a ogni scansione, non tutti i passaggi. Per sapere quali treni hanno circolato in un giorno usa `treni`.
5. **Le tabelle crescono in fretta.** `avvistamenti_tratta` e `fermate` sono le più grandi (circa 325 mila e 272 mila righe nel DB attuale, che pesa oltre 200 MB). Se serve spazio, `avvistamenti_tratta` è la prima candidata alla pulizia, perché serve solo alle analisi per segmento e nessuna delle query qui sopra la usa.
