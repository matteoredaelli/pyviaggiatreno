# Dati GTFS Trenord: riferimento formato

Dati ufficiali di pianificazione ferroviaria regionale della Lombardia, pubblicati sul portale open data regionale [dati.lombardia.it](https://www.dati.lombardia.it/Mobilit-e-trasporti/Orario-Ferroviario-Regionale-Gtfs/3z4k-mxz9/about_data).

## Fonte

| Aspetto | Dettaglio |
|---|---|
| **Dataset** | Orario Ferroviario Regionale GTFS |
| **URL** | https://www.dati.lombardia.it/Mobilit-e-trasporti/Orario-Ferroviario-Regionale-Gtfs/3z4k-mxz9/about_data |
| **Ente** | Regione Lombardia - Mobilità e Trasporti |
| **Formato** | GTFS (General Transit Feed Specification) |
| **Operatore** | Trenord |
| **Copertura** | Rete ferroviaria regionale Lombardia |
| **Aggiornamento** | Semestrale/annuale (pianificazione) |
| **Disponibilità** | ZIP con file .txt separati (CSV-like) |
| **Licenza** | CC-BY 4.0 (verificare sul portale) |

---

## Caratteristiche generali

- **Dati pianificati, non real-time**: contiene orari e corse previste, non ritardi/cancelazioni attuali
- **Copertura temporale**: tipicamente 6-12 mesi a partire dalla pubblicazione
- **Completezza**: tutte le linee Trenord (ferrovie regionali + autobus sostitutivi)
- **Aggiornamento**: scarica periodicamente dal portale per i dati più recenti
- **Identificatori univoci**: gli `stop_id` coincidono con i codici stazione di ViaggiaTreno (`S*`)

---

## ⚠️ LIMITAZIONE CRITICA: Copertura Solo Lombardia

**GTFS Trenord contiene SOLO dati della Lombardia** (~3,000 stazioni Trenord). Se hai bisogno di stazioni di altre regioni italiane, **devi usare le API ViaggiaTreno**.

### Stazioni Disponibili

| Fonte | Copertura | Stazioni | Tipo |
|-------|-----------|----------|------|
| **GTFS Trenord** | Lombardia | ~3,000 | Pianificazione (offline) |
| **API /elencoStazioni** | Per regione (1-22) | ~350 per regione | Real-time |
| **API ViaggiaTreno** | Tutta Italia | ~7,000-8,000 | Real-time |

### Come Accedere a Stazioni per Regione (Non in GTFS)

Le API ViaggiaTreno espongono stazioni per regione tramite:

```bash
# Get tutte le stazioni di una regione
GET /elencoStazioni/1           # Lombardia (345 stazioni)
GET /elencoStazioni/5           # Lazio (~350 stazioni)
GET /elencoStazioni/13          # Toscana (~200 stazioni)
# Codici regione 1-22, vedi tabella sotto

# Get regione di una stazione
GET /regione/S06421             # Risposta: 13 (Toscana)
```

### Codici Regione (1-22)

```
 1 = Lombardia           5 = Lazio
 2 = Liguria             6 = Umbria
 3 = Piemonte            7 = Molise
 4 = Valle d'Aosta       8 = Emilia Romagna
 9 = Trentino-Alto Adige 10 = Friuli-Venezia Giulia
11 = Marche             12 = Veneto
13 = Toscana            14 = Sicilia
15 = Basilicata         16 = Puglia
17 = Calabria           18 = Campania
19 = Abruzzo            20 = Sardegna
21 = Prov. Autonoma Trento
22 = Prov. Autonoma Bolzano
```

### Strategie per Multi-Regione

**Opzione A**: Solo real-time (no pianificazione)
- Usa API ViaggiaTreno /elencoStazioni per ogni regione
- Covri tutte le stazioni italiane (~7k-8k)
- Setup: <2 ore

**Opzione B**: Pianificazione + real-time
- Scarica GTFS Trenord (Lombardia)
- Scarica GTFS Trenitalia + altri operatori (altre regioni)
- Merge in DB locale
- Setup: 12-20 ore

**Opzione C**: Cache API stazioni (Consigliato)
```python
# Setup iniziale (call once per mese)
for region in range(1, 23):
    stations[region] = API("/elencoStazioni/" + str(region))

# Queries (locale, velocissimo)
stations_lazio = stations[5]  # ~350 stazioni in RAM
```

---

## Indice

- [Fonte](#fonte)
- [Caratteristiche generali](#caratteristiche-generali)
- [Struttura file](#struttura-file)
  - [agency.txt](#agencytxt-agenzia)
  - [stops.txt](#stopstxt-fermatestazioni)
  - [routes.txt](#routestxt-linee-ferroviarie)
  - [trips.txt](#tripstxt-corsservizi)
  - [stop_times.txt](#stop_timestxt-orari-nelle-fermate)
  - [calendar_dates.txt](#calendar_datestxt-calendario-eccezioni)
  - [feed_info.txt](#feed_infotxt-metadati-feed)
- [Dimensioni dati](#dimensioni-dati)
- [Correlazione con ViaggiaTreno](#correlazione-con-viaggiatreno)
- [Casi d'uso](#casi-duso)
- [Parsing e utilizzo](#parsing-e-utilizzo)
- [Insidie note](#insidie-note)

---

## Struttura file

### agency.txt (Agenzia)

Metadati dell'operatore di trasporto.

| Campo | Tipo | Descrizione |
|---|---|---|
| `agency_id` | string | Identificatore univoco dell'agenzia (es. `1` per Trenord) |
| `agency_name` | string | Nome completo (es. `Trenord`) |
| `agency_url` | string | URL ufficiale (es. `http://www.trenord.it/`) |
| `agency_timezone` | string | Fuso orario IANA (es. `Europe/Rome`) |

**Esempio** (una sola riga dati):

```
agency_id,agency_name,agency_url,agency_timezone
1,Trenord,http://www.trenord.it/?utm_source=google_maps&utm_medium=transit&utm_campaign=gtfs_brand&utm_content=agency_main,Europe/Rome
```

**Note**:
- Solitamente un solo record (una sola agenzia = Trenord)
- Usare `agency_id` come chiave esterna in `routes.txt`

---

### stops.txt (Fermate/Stazioni)

Elenco completo delle fermate della rete Trenord con coordinate geografiche.

| Campo | Tipo | Descrizione |
|---|---|---|
| `stop_id` | string | Codice stazione (`^S\d{5}$`, es. `S01700` = Milano Centrale). **Identico a ViaggiaTreno** |
| `stop_name` | string | Nome della stazione in maiuscolo (es. `MILANO CENTRALE`) |
| `stop_lat` | float | Latitudine WGS84 |
| `stop_lon` | float | Longitudine WGS84 |
| `stop_url` | string | URL della stazione su trenord.it |

**Esempio** (prime 4 righe):

```
stop_id,stop_name,stop_lat,stop_lon,stop_url
S00023,Novara Nord,45.452101749106006,8.625791037822637,https://www.trenord.it/linee-e-orari/circolazione/stazione/?mir-code=S00023&no_cache=1&utm_source=google_maps&utm_medium=transit&utm_campaign=gtfs_stops&utm_content=stop_S00023
S00030,Garbagna,45.385638,8.666421,https://www.trenord.it/linee-e-orari/circolazione/stazione/?mir-code=S00030&no_cache=1&utm_source=google_maps&utm_medium=transit&utm_campaign=gtfs_stops&utm_content=stop_S00030
S00031,Vespolate,45.351425,8.671866,https://www.trenord.it/linee-e-orari/circolazione/stazione/?mir-code=S00031&no_cache=1&utm_source=google_maps&utm_medium=transit&utm_campaign=gtfs_stops&utm_content=stop_S00031
S00032,Borgo Lavezzaro,45.318727,8.703082,https://www.trenord.it/linee-e-orari/circolazione/stazione/?mir-code=S00032&no_cache=1&utm_source=google_maps&utm_medium=transit&utm_campaign=gtfs_stops&utm_content=stop_S00032
```

**Statistiche** *[estimate]*:
- **~3000** fermate totali (include minori, bivi, deviazioni)
- Coordinate verificate e precise (derivate da dati RFI ufficiali)

**Note**:
- Il formato del `stop_id` è coerente con ViaggiaTreno: è possibile fare join diretto
- Sono incluse tutte le fermate commerciali e tecniche (bivi, deviazioni)
- URL traccia il codice della stazione per analytics

---

### routes.txt (Linee ferroviarie)

Definizione di tutte le linee servite da Trenord.

| Campo | Tipo | Descrizione |
|---|---|---|
| `route_id` | string | Identificatore univoco della linea (es. `R23`, `RE_4`) |
| `agency_id` | string | Riferimento a `agency.txt` (es. `1` = Trenord) |
| `route_short_name` | string | Numero/sigla breve (es. `R23`, `RE4`, `S11`) |
| `route_long_name` | string | Nome lungo con capolinee (es. `Domodossola-Arona-Gallarate-Milano`) |
| `route_type` | int | Tipo di trasporto: `3` = autobus regionale (anche per treni in GTFS Trenord) |
| `route_color` | string | Colore esadecimale della linea (es. `94C120` = verde) |
| `route_text_color` | string | Colore testo per il contrasto (es. `FFFFFF` = bianco) |
| `route_url` | string | URL della linea su trenord.it |

**Esempio** (prime 5 linee):

```
route_id,agency_id,route_short_name,route_long_name,route_color,route_text_color,route_type,route_url
TN_Unspecified_Line,1,Trenord (linea non specificata),Trenord (linea non specificata),006633,FFFFFF,2,
TN_Bus,1,TN Bus,TN Bus sostitutivi,006633,FFFFFF,3,
R23,1,R23,Domodossola-Arona-Gallarate-Milano,94C120,FFFFFF,3,https://www.trenord.it/linee-e-orari/circolazione/le-nostre-linee/domodossola-arona-gallarate-milano/?code=R23&utm_source=google_maps&utm_medium=transit&utm_campaign=gtfs_routes&utm_content=route_R23
RE_4,1,RE4,Domodossola-Milano,E40314,FFFFFF,3,https://www.trenord.it/linee-e-orari/circolazione/le-nostre-linee/domodossola-milano/?code=RE_4&utm_source=google_maps&utm_medium=transit&utm_campaign=gtfs_routes&utm_content=route_RE_4
S11,1,S11,Como San Giovanni-Milano,FF6B00,FFFFFF,3,https://www.trenord.it/linee-e-orari/circolazione/le-nostre-linee/como-san-giovanni-milano/?code=S11&utm_source=google_maps&utm_medium=transit&utm_campaign=gtfs_routes&utm_content=route_S11
```

**Statistiche** *[stimate]*:
- **~200-300** linee totali
- Include ferrovie regionali e autobus sostitutivi

**Note**:
- `route_id` può contenere underscore (es. `RE_4`) o no (es. `R23`)
- `route_short_name` è quello visibile sui tabelloni/mappe
- Il `route_type` è sempre `3` in questo dataset (autobus regionale, anche per treni)
- I colori sono usati per visualizzazione su mappe (codice hex standard)

---

### trips.txt (Corse/Servizi)

Definizione di ogni singola corsa/servizio (un treno in una fascia oraria su una linea).

| Campo | Tipo | Descrizione |
|---|---|---|
| `trip_id` | string | Identificatore univoco della corsa (es. `1001A-2025-12-14-2026-12-12`) |
| `route_id` | string | Riferimento a `routes.txt` (es. `R23`) |
| `trip_short_name` | string | Numero breve della corsa (es. `1001A`, numero del treno) |
| `service_id` | string | Riferimento a `calendar_dates.txt` (calendar/schedule ID) |

**Esempio** (prime 4 corse):

```
trip_id,route_id,trip_short_name,service_id
1001A-2025-12-14-2026-12-12,TN_Bus,1001A,1001A-2025-12-14-2026-12-12
1006A-2026-07-06-2026-07-26,TN_Bus,1006A,1006A-2026-07-06-2026-07-26
1007A-2026-07-20-2026-07-26,TN_Bus,1007A,1007A-2026-07-20-2026-07-26
1009A-2025-12-15-2026-12-12,TN_Bus,1009A,1009A-2025-12-15-2026-12-12
```

**Statistiche** *[stimate]*:
- **~40,000-50,000** corse totali nel periodo di pianificazione

**Note**:
- Il `trip_id` spesso codifica date di validità (es. `1001A-2025-12-14-2026-12-12` = valido dal 14/12/2025 al 12/12/2026)
- `service_id` permette di filtrare per giorni specifici (vedi `calendar_dates.txt`)
- Ogni corsa è collegata a **una sola linea** e **una sola schedula temporale**

---

### stop_times.txt (Orari nelle fermate)

**File più grande**: orario di passaggio (arrivo/partenza) di ogni corsa in ogni fermata.

| Campo | Tipo | Descrizione |
|---|---|---|
| `trip_id` | string | Riferimento a `trips.txt` |
| `arrival_time` | string | Orario di arrivo in formato `HH:MM:SS` (può essere `>24:00:00` per corse nottirne che arrivano il giorno dopo) |
| `departure_time` | string | Orario di partenza in formato `HH:MM:SS` |
| `stop_id` | string | Riferimento a `stops.txt` (codice stazione) |
| `stop_sequence` | int | Ordine della fermata nella corsa (1, 2, 3, …) |

**Esempio** (prime 4 fermate di una corsa):

```
trip_id,arrival_time,departure_time,stop_id,stop_sequence
1001A-2025-12-14-2026-12-12,23:50:00,23:50:00,S01933,1
1001A-2025-12-14-2026-12-12,23:53:00,23:54:00,S01724,2
1001A-2025-12-14-2026-12-12,23:57:00,23:58:00,S01725,3
1001A-2025-12-14-2026-12-12,24:00:00,24:00:00,S01726,4
```

**Statistiche** *[stimate]*:
- **~2,000,000** righe (record più voluminoso)
- Dimensione file: **~5 MB** non compresso

**Note**:
- Se `arrival_time == departure_time`, il treno **non ferma**, passa solo per conteggio
- Orari `>24:00:00` (es. `24:30:00`, `25:15:00`) indicano corse nottirne che **arrivano il giorno successivo**
- Per le stazioni di origine (prima fermata), `arrival_time` è spesso uguale a `departure_time`
- Per le stazioni di destinazione (ultima fermata), `departure_time` è spesso nullo nel GTFS standard, qui valorizzato

---

### calendar_dates.txt (Calendario eccezioni)

**File gigantesco**: specifica ogni giorno in cui ogni servizio è attivo o soppresso.

| Campo | Tipo | Descrizione |
|---|---|---|
| `service_id` | string | Riferimento a `trips.txt` |
| `date` | string | Data in formato `YYYYMMDD` (es. `20260726` = 26 luglio 2026) |
| `exception_type` | int | `1` = servizio attivo (added), `2` = servizio cancellato (removed) |

**Esempio** (prime 5 righe):

```
service_id,date,exception_type
1001A-2025-12-14-2026-12-12,20260726,1
1001A-2025-12-14-2026-12-12,20260727,1
1001A-2025-12-14-2026-12-12,20260728,1
1001A-2025-12-14-2026-12-12,20260729,1
```

**Statistiche** *[stimate]*:
- **~10,000,000+** righe
- Dimensione file: **~15 MB** non compresso
- Per ogni servizio, una riga per ogni giorno della validità

**Note**:
- Questo file è il "motore" della pianificazione temporale
- Permette di rispondere: "Quali treni circolano il 26 luglio 2026?"
- Include giorni feriali, festivi, periodi di sospensione stagionale
- `exception_type: 1` significa "il servizio è operativo quel giorno"
- `exception_type: 2` significa "il servizio è cancellato quel giorno" (eccezione: sospensione temporanea)

---

### feed_info.txt (Metadati feed)

Metadati globali del feed GTFS.

| Campo | Tipo | Descrizione |
|---|---|---|
| `feed_publisher_name` | string | Nome dell'ente che pubblica il dataset |
| `feed_publisher_url` | string | URL del feed/dataset |
| `feed_lang` | string | Lingua principale (codice IETF, es. `it-IT`) |

**Esempio**:

```
feed_publisher_name,feed_publisher_url,feed_lang
Trenord,https://trenord.it/,it-IT
```

**Note**:
- Una sola riga
- Metadati di utilità per validatori/parser GTFS

---

## Dimensioni dati

| File | Dimensione | Righe | Contenuto | Compressione |
|---|---|---|---|---|
| **agency.txt** | ~0.2 KB | 1 | Agenzia Trenord | Minima |
| **feed_info.txt** | ~0.1 KB | 1 | Metadati feed | Minima |
| **stops.txt** | ~128 KB | ~3,000 | Tutte le fermate | Media |
| **routes.txt** | ~15 KB | ~250-300 | Tutte le linee | Minima |
| **trips.txt** | ~616 KB | ~40,000 | Tutte le corse | Media |
| **stop_times.txt** | **~5 MB** | **~2,000,000** | Orari in fermate | **Alto** (molte righe) |
| **calendar_dates.txt** | **~15 MB** | **~10,000,000+** | Giorni operativi | **Alto** (molte righe) |
| **TOTAL (ZIP)** | **~21 MB** | - | Tutto insieme | Compresso ZIP |

**Note**:
- I file più grandi (`stop_times.txt`, `calendar_dates.txt`) beneficiano molto della compressione ZIP
- Quando decompresso, il dataset cresce fino a **~25-30 MB**
- Il volume è gestibile per database moderni (importabile in SQLite, PostgreSQL, MySQL)

---

## Correlazione con ViaggiaTreno

I dati GTFS Trenord e le API ViaggiaTreno sono **complementari**:

| Aspetto | GTFS Trenord | ViaggiaTreno API |
|---|---|---|
| **Dati** | Pianificazione (orari previsti) | Real-time + pianificazione |
| **stop_id** | `S01700` (Milano Centrale) | Stesso codice `S01700` |
| **Frequenza** | Semestrale/annuale | Aggiornamento continuo |
| **Dettagli** | Linee, corse, orari | Ritardi, binari, stato |
| **Formato** | CSV strutturato | JSON REST API |
| **Uso** | Analisi, pianificazione app | Monitoraggio, notifiche |

### Join e correlazione

Poiché gli `stop_id` sono **identici**, è possibile:

1. **Importare GTFS in DB**: caricare tutti gli orari programmati
2. **Chiamare ViaggiaTreno per orario X**: ottenere dati real-time
3. **Confrontare**: pianificato vs effettivo per calcolare ritardi attesi

**Esempio workflow**:
```python
# 1. Leggi GTFS Trenord: trovare tutti i treni da Milano alle 08:00
corse_programmate = query_stops_times(stop_id="S01700", departure_time="08:00:00")

# 2. Per ogni corsa, chiama ViaggiaTreno per dati real-time
for corsa in corse_programmate:
    trip_id = corsa["trip_id"]
    numero_treno = extract_numero(trip_id)
    dati_reali = api_viaggiatreno.andamentoTreno(numero_treno=numero_treno, codStazione="S01700")

    # 3. Confronta
    print(f"Programmato: {corsa['departure_time']}, Reale: {dati_reali['orarioPartenza']}")
```

---

## Casi d'uso

### 1. **Pianificazione viaggio fuori linea**
- Scarica GTFS, carica in app
- Offline: "Quali treni da A a B domani?"
- Utile per aree con scarsa/nulla connessione

### 2. **Analisi della rete regionale**
- Densità oraria di servizio per linea
- Copertura geografica (coordinate fermate)
- Orari di punta vs off-peak

### 3. **Integrazione con navigatori**
- Google Maps, OSM, mappe custom
- Visualizzazione linee su mappa (geometry da coordinate fermate)
- Tempo di viaggio calcolato da GTFS

### 4. **Validazione dati real-time**
- Comparare pianificazione vs dati ViaggiaTreno
- Rilevare anomalie (treno cancellato inaspettatamente)
- Calcoli di affidabilità della rete

### 5. **Dataset per ricerca/open data**
- Mobilità urbana
- Analisi sostenibilità trasporti
- Machine learning per predizione orari

### 6. **Prenotazione/notifiche proattive**
- Pre-caricate GTFS: "Il tuo treno di domani mattina"
- Allarme se rimosso da `calendar_dates`
- Avviso prima della partenza da API ViaggiaTreno

---

## Parsing e utilizzo

### Download

```bash
# Da dati.lombardia.it
curl -L "https://www.dati.lombardia.it/api/views/3z4k-mxz9/rows.csv?accessType=DOWNLOAD" \
  -o trenord_gtfs.zip

# Oppure manuale dal portale web
```

### Decompressione

```bash
unzip trenord_gtfs.zip
# Estrae: agency.txt, stops.txt, routes.txt, trips.txt, stop_times.txt, calendar_dates.txt, feed_info.txt
```

### Parsing CSV

**Python** (pandas):
```python
import pandas as pd

stops = pd.read_csv("stops.txt")
stop_times = pd.read_csv("stop_times.txt")
trips = pd.read_csv("trips.txt")
routes = pd.read_csv("routes.txt")
calendar = pd.read_csv("calendar_dates.txt")

# Query: treni da Milano Centrale il 26 luglio 2026
milano = stops[stops["stop_id"] == "S01700"]
print(milano)
```

**JavaScript** (parse CSV):
```javascript
const csv = require('csv-parse/sync');
const fs = require('fs');

const stops = csv.parse(fs.readFileSync('stops.txt'), {
  columns: true
});

const milano = stops.filter(s => s.stop_id === 'S01700');
console.log(milano);
```

### Database (SQLite)

```sql
-- Crea tabelle
CREATE TABLE stops (
  stop_id TEXT PRIMARY KEY,
  stop_name TEXT,
  stop_lat REAL,
  stop_lon REAL,
  stop_url TEXT
);

CREATE TABLE stop_times (
  trip_id TEXT,
  arrival_time TEXT,
  departure_time TEXT,
  stop_id TEXT,
  stop_sequence INT,
  FOREIGN KEY(trip_id) REFERENCES trips(trip_id),
  FOREIGN KEY(stop_id) REFERENCES stops(stop_id)
);

CREATE TABLE trips (
  trip_id TEXT PRIMARY KEY,
  route_id TEXT,
  trip_short_name TEXT,
  service_id TEXT,
  FOREIGN KEY(route_id) REFERENCES routes(route_id)
);

CREATE TABLE calendar_dates (
  service_id TEXT,
  date TEXT,
  exception_type INT
);

-- Importa CSV
.mode csv
.import stops.txt stops
.import stop_times.txt stop_times
.import trips.txt trips
.import calendar_dates.txt calendar_dates

-- Query: treni da Milano (S01700) il 26 luglio 2026 alle 08:xx
SELECT DISTINCT
  t.trip_short_name,
  st.departure_time,
  r.route_short_name
FROM stop_times st
JOIN trips t ON st.trip_id = t.trip_id
JOIN routes r ON t.route_id = r.route_id
JOIN calendar_dates cd ON t.service_id = cd.service_id
WHERE st.stop_id = 'S01700'
  AND cd.date = '20260726'
  AND cd.exception_type = 1
  AND time(st.departure_time) >= '08:00:00'
  AND time(st.departure_time) < '09:00:00'
ORDER BY st.departure_time;
```

---

## Insidie note

1. **Orari notturni > 24:00:00**: corse che superano mezzanotte. Esempio: `24:30:00` = 00:30 del giorno successivo. Gestire la conversione al parsing.

2. **service_id complessi**: il campo `service_id` in `trips.txt` spesso codifica date di validità (es. `1001A-2025-12-14-2026-12-12`). Non è una chiave semplice di calendario, va usato con `calendar_dates.txt` per determinare giorni effettivi.

3. **stop_sequence non univoca**: lo stesso `stop_id` può comparire più volte nella stessa corsa (stazioni di cambio/interconnessione). Usare `stop_sequence` per determinare ordine.

4. **route_type standardizzato ma generico**: tutti i "treni" hanno `route_type = 3` (autobus). Non riflette se è metro, tram, treno. Usare `route_short_name` o `route_long_name` per tipologia reale.

5. **Dati pianificati, non real-time**: cancellazioni, ritardi, binari e altri dettagli operativi **non sono in GTFS**. Usare ViaggiaTreno API per dati live.

6. **Compressione ZIP**: il file `.zip` contiene i 7 file `.txt`. Non tutti i tool decomprimono automaticamente; potrebbe essere necessario `unzip` o libreria dedicata.

7. **Aggiornamento**portale**: i dati sul portale dati.lombardia.it potrebbero non essere sempre aggiornati alla data attuale. Verificare date in `calendar_dates.txt` prima di affidarsi a orari futuri.

8. **Assenza di cambio numero**: il GTFS non contiene informazioni su cambio numero del treno (campo `haCambiNumero` di ViaggiaTreno). Se un treno cambia numero lungo la corsa, comparirà come due `trip_id` diversi (solitamente sul portale si vede solo uno).

9. **Coordinate WGS84**: le coordinate in `stops.txt` sono sempre in WGS84 (EPSG:4326). Se usi un altro sistema (es. UTM), ricorda di trasformare.

10. **Dataset pubblico ma proprietà RFI**: i dati sono licenza CC-BY ma derivano da dati RFI. Un'eventuale rivendita o integrazione in prodotto a pagamento potrebbe richiedere verifica legale.

---

## Glossario GTFS

| Termine | Significato |
|---|---|
| **Agency** | Operatore (Trenord) |
| **Route** | Linea ferroviaria (es. R23, RE4) |
| **Trip** | Singola corsa/servizio (es. R23 delle 08:15) |
| **Stop** | Fermata/stazione |
| **Stop Time** | Orario di fermata (arrivo/partenza) |
| **Service** | Identificatore di calendarioCalendar (quale giorni opera) |
| **GTFS** | General Transit Feed Specification (standard Google) |

---

## Riferimenti

- **Portale dati.lombardia.it**: https://www.dati.lombardia.it/Mobilit-e-trasporti/Orario-Ferroviario-Regionale-Gtfs/3z4k-mxz9/about_data
- **GTFS Standard**: https://gtfs.org/ (Google Transit Feed Specification)
- **Trenord**: https://www.trenord.it/
- **ViaggiaTreno API**: vedi `VIAGGIATRENO.md`
