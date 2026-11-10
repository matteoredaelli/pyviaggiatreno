# GLOSSARIO FERROVIARIO E TECNICO

## Terminologia Ferroviaria

### Stazione / Fermata / Nodo

| Termine | Definizione | Codice | Fonte |
|---------|-----------|--------|-------|
| **Stazione** | Struttura fissa dove i treni si fermano, con servizi passeggeri (biglietteria, bar, WC) | `S01700` | stops.txt |
| **Fermata** | Passaggio di un treno in una stazione (potrebbe non fermarsi veramente) | `StopTime` | stop_times.txt |
| **Nodo** | Punto sulla rete ferroviaria (tecnico); può essere una stazione o un bivio | `S00000`, `S99999` | API elencoTratte |
| **Bivio** | Nodo tecnico dove la rete si dirama | GTFS NTS: `830006048` | autocompletaStazioneNTS |

### Linea / Rotta / Tratta

| Termine | Definizione | Esempio | Fonte |
|---------|-----------|---------|-------|
| **Linea ferroviaria** | Percorso fisso fra 2+ stazioni servito regolarmente | `R23` Domodossola-Arona-Gallarate-Milano | routes.txt |
| **Rotta / Route** | Sinonimo di linea nel contesto GTFS | `route_id: RE_4` | routes.txt |
| **Tratta / Segmento** | Singolo arco fra 2 stazioni (nodoA → nodoB) | Segmento Milano-Monza | elencoTratte API |
| **Tratto / Percorso** | Sequenza di stazioni per una corsa | Intero percorso R23 da Domodossola a Milano | Stop_times.txt |

### Treno / Corsa / Servizio

| Termine | Definizione | Esempio | Fonte |
|---------|-----------|---------|-------|
| **Treno** (pianificato) | Corsa pianificata su una linea (GTFS `TRIP`) | R23 ore 06:35 da Domodossola | trips.txt |
| **Corsa / Trip** | Istanza di un treno in una data | `trip_id: 1001A-2025-12-14-2026-12-12` | trips.txt |
| **Servizio / Service** | Calendario di giorni in cui una corsa è attiva | `service_id` (100+ giorni) | calendar_dates.txt |
| **Treno** (real-time) | Istanza effettiva circolante in un momento (terna univoca) | REG 2452 24/10/26 origine Parma | API partenze/arrivi |
| **Numero treno** | Identificativo della corsa (non univoco!) | `2452`, `9611` | numeroTreno campo |

### Binario / Piattaforma

| Termine | Definizione | Esempio | Fonte |
|---------|-----------|---------|-------|
| **Binario programmato** | Piattaforma indicata in orario | Binario 9 Milano Centrale | stop_times.txt, API |
| **Binario effettivo** | Piattaforma reale dove il treno staziona | Binario 11 (comunicato al tabellone) | API andamentoTreno |
| **Cambio binario** | Il treno non è al binario programmato | Ritardo → cambio binario | binarioEffettivo* API |

### Categoria Treno

| Categoria | Descrizione | Colore | Operatore | Velocità |
|-----------|-------------|--------|-----------|----------|
| **FR / Freccia** | Alata Velocità nazionale | Rosso (#C60C30) | Trenitalia | 200-360 km/h |
| **EC / EuroCity** | Internazionale | Bordeaux (#A71640) | Trenitalia | 160 km/h |
| **IC / InterCity** | Interregionale | Arancione (#E8A200) | Trenitalia | 150 km/h |
| **REG / Regionale** | Connessione urbana/regionale | Verde (#006633) | Trenord, Trenitalia | 80-120 km/h |
| **S** / **R** | Suburbano / Rapido regionale | Vari | Trenord | 100-150 km/h |
| **EN / Euronight** | Notturno internazionale | Azzurro | Trenitalia, ÖBB | 120 km/h |

**Nota**: Nella categoria GTFS Trenord, tutte le linee hanno `route_type: 3` (autobus regionale), indipendentemente dal tipo reale.

### Stato Treno

| Codice | Nome | Significato |
|--------|------|-------------|
| **PG** | Programmato / In Orario | Regolare, circolante |
| **ST** | Soppresso Totale | Cancellato completamente |
| **PP** | Parzialmente Programmato / Soppresso Parziale (inizio) | Fermate iniziali cancellate |
| **SF** | Soppresso Finale | Fermate finali cancellate |
| **SI** | Soppresso Iniziale | Stesso di PP |
| **DV** | Deviato | Percorso diverso da programmato |
| **VD** | Variazione Destinazione | Destinazione cambiata |
| **VO** | Variazione Origine | Origine cambiata |
| **SM** | Cambio Treno con Cancellazione | Cancellato in una tratta, cambia numero |

**Provvedimento**:
- `0` = Regolare
- `1` = Cancellato
- `2` = Parzialmente cancellato / deviato
- `3` = Deviato

### Ritardo

| Valore | Significato |
|--------|-------------|
| `0` | In orario |
| `> 0` | Ritardo (minuti) |
| `< 0` | Anticipo (raro) |
| Null | Non ancora rilevato / previsto |

### Fermata Reale (Status)

| Tipo | Significato |
|------|-------------|
| `1` | Fermata già effettuata / regolare |
| `0` | Dato non disponibile (treno non ancora arrivato) |
| `2` | Fermata non prevista (aggiunta) |
| `3` | Fermata soppressa (cancellata) |

---

## Terminologia GTFS

| Termine | Definizione | Esempio |
|---------|-----------|---------|
| **Agency** | Operatore di trasporto | Trenord |
| **Route** | Linea di trasporto | R23, RE_4 |
| **Trip** | Singola corsa su una rotta | trip_id: 1001A-2025-12-14-2026-12-12 |
| **Stop** | Fermata fisica | S01700 (Milano Centrale) |
| **Stop Time** | Orario di una fermata in una corsa | Arrivo 07:45, Partenza 07:48 |
| **Service / Calendar** | Calendari di operazione | Date specifiche: 20261026 |
| **Exception Type** | Tipo di eccezione calendario | 1 = aggiunto, 2 = rimosso |
| **Feed** | Dataset GTFS completo | trenord_gtfs.zip |

---

## Terminologia ViaggiaTreno API

| Termine | Definizione | Campo API |
|---------|-----------|-----------|
| **Andamento Treno** | Stato completo di un treno con fermate | `GET /andamentoTreno/{...}` |
| **Infomobilità** | Notizie su circolazione, lavori, segnalazioni | `GET /infomobilitaRSS` |
| **Ultimo Rilevamento** | Ultima posizione GPS nota del treno | `ultimoRilev` (ms timestamp) |
| **Corrispondenza** | Connessione con altri treni | `corrispondenze[]` array |
| **Orientamento** | Posizione della prima classe/executive nel treno | `orientamento`, `descOrientamento[]` |
| **Riprogrammazione** | Segnala se orari sono stati cambiati | `riprogrammazione: "Y"/"N"` |
| **Cambio Numero** | Treno che cambia numero lungo la corsa | `haCambiNumero: true/false` |
| **Materiale** | Composizione delle carrozze | `materiale_label` (es. "Ale501") |

---

## Identificatori Chiave

### Codici Stazione

| Formato | Descrizione | Esempio | Lunghezza | Fonte |
|---------|------------|---------|----------|-------|
| **ViaggiaTreno** | `S` + 5 cifre | `S01700` | 6 char | stops.txt, API |
| **RICS (NTS)** | `83` + 7-9 cifre | `830006421` | 9-11 char | autocompletaStazioneNTS |
| **RFI (iechub)** | `PlaceId` numerico | `1728` | Variabile | iechub.rfi.it |

**Nota**: Usa sempre i codici `S*` per ViaggiaTreno e GTFS. I RICS e PlaceId richiedono mapping separato.

### Numero Treno

| Aspetto | Dettaglio |
|---------|-----------|
| **Univocità** | ❌ NON univoco (stesso numero, giorni diversi, stazioni diverse) |
| **Identificatore vero** | ✅ Terna: (numeroTreno, codOrigine, dataPartenzaTreno) |
| **Formato** | Numerico, tipicamente 4-5 cifre |
| **Esempio** | 2452 (REG), 9611 (FR), 15 (S-bahn) |
| **Cambio numero** | Un treno può cambiare numero durante la corsa (`haCambiNumero`) |

### Trip ID (GTFS)

| Aspetto | Dettaglio |
|---------|-----------|
| **Formato** | Stringa codificata con date di validità |
| **Esempio** | `1001A-2025-12-14-2026-12-12` |
| **Parsing** | Parsare cautamente; il formato è stato modificato nel tempo |
| **Corrispondenza** | Mappa a numeroTreno via `trip_short_name` |

### Service ID (GTFS)

| Aspetto | Dettaglio |
|---------|-----------|
| **Uso** | Chiave per lookup in `calendar_dates.txt` |
| **Formato** | Uguale a trip_id o variante |
| **Validità** | Permette di sapere se una corsa circola il giorno X |
| **Cardinalità** | 1 service → 100+ date |

---

## Concetti Temporali

### Timestamp

| Campo | Tipo | Descrizione | Esempio |
|-------|------|-------------|---------|
| **Orario in ms** | INT (ms from epoch) | Millisecondi da 1/1/1970 UTC | `1791094320000` |
| **Mezzanotte** | INT | Inizio giorno italiano (00:00 CEST) | `1791064800000` (4 ott 2026) |
| **String Date** | `YYYY-MM-DD` | Data in formato ISO | `2026-10-04` |
| **String DateTime** | `YYYY-MM-DD HH:MM:SS.f` | Data con ora e millisecondi | `2026-10-04 08:15:32.100` |
| **YYYYMMDD** | INT | Data in formato GTFS | `20261004` |

### Orario Notturno

| Orario | Significato | Giorno |
|--------|-------------|--------|
| `23:45:00` | 23:45 stesso giorno | Corrente |
| `24:15:00` | 00:15 giorno successivo | Successivo |
| `25:30:00` | 01:30 giorno successivo | Successivo |

**Nota**: Stop_times.txt di GTFS usa ore > 24 per indicare corse che arrivano il giorno dopo. Necessaria conversione al parsing.

### Fuso Orario

| Fuso | Standard | Ora Legale | IANA |
|------|----------|-----------|------|
| **CET** | UTC+1 | Novembre-Marzo | Europe/Rome |
| **CEST** | UTC+2 | Marzo-Novembre | Europe/Rome |

Tutti i timestamp di ViaggiaTreno e GTFS sono in fuso `Europe/Rome`.

---

## Concetti Geografici

### Coordinate

| Sistema | Codice | Precisione | Range | Fonte |
|---------|--------|-----------|-------|-------|
| **WGS84** | EPSG:4326 | Decimali (6 cifre = ~0.1 m) | lat: ±90°, lon: ±180° | stops.txt, API |
| **UTM** | EPSG:32632/33N | Meters | Specifica per Italia | Raro (conversione richiesta) |

**Coordinate Italia**:
- Latitudine: 36.7° - 47.1° N
- Longitudine: 6.6° - 18.5° E

### Distanza / Geometria

| Concetto | Uso | Nota |
|----------|-----|------|
| **Haversine** | Distanza fra 2 coordinate (tratta) | Usare libreria geografica |
| **Geometria Linea** | Forma della linea sulla mappa | Non fornita da GTFS (solo fermate) |
| **Buffer** | Area attorno a una stazione | Utile per ricerche "nelle vicinanze" |

---

## Concetti di Pianificazione

### Pianificazione Semestrale

| Periodo | Inizio | Fine | Note |
|---------|--------|------|------|
| **Invernale** | Novembre | Marzo | Orari ridotti, meno affluenza |
| **Estiva** | Marzo | Ottobre | Orari completi, picchi turistici |
| **Ponte** | Vacanze | Vacanze | Orari speciali (Natale, Pasqua) |

### Frequenza Servizio

| Termine | Significato | Esempio |
|---------|-------------|---------|
| **Ora di punta** | Massima densità (06:00-09:00, 17:00-20:00) | 5-10 treni/ora per linea |
| **Off-peak** | Bassa densità (notturno, pomeriggio) | 1-3 treni/ora |
| **Weekend** | Sabato, domenica (pattern diverso) | Ridotto vs feriale |
| **Festivo** | Giorno festivo nazionale | Pattern speciale in `calendar_dates` |

---

## Operatori Ferroviari (Codici Cliente)

| Codice | Nome | Abbreviazione | Regione | Tipo |
|--------|------|---------------|--------|------|
| **1** | Trenitalia (Alta Velocità) | AV | Nazionale | Freccia, Intercity |
| **2** | Trenitalia (Regionali) | TR | Nazionale | Regionali |
| **4** | Trenitalia (InterCity) | IC | Nazionale | InterCity |
| **18** | Trenitalia Tper | TP | Emilia-Romagna | Regionali |
| **63** | Trenord | TN | Lombardia | Regionali, S-Bahn |
| **64** | TILO | TL | Ticino/Como | Regionali internazionali |
| **910** | Ferrovie del Sud Est | FSE | Puglia | Regionali |

---

## Unità di Misura

| Metrica | Unità | Conversione | Esempio |
|---------|-------|------------|---------|
| **Tempo** | Minuti | 60 sec = 1 min | Ritardo: 6 min |
| **Timestamp** | Millisecondi | 1000 ms = 1 sec | 1791094320000 |
| **Velocità** | km/h | 1 km = 1000 m | Freccia: 320 km/h |
| **Distanza** | km | Calcolata da coordinate | Milano-Como: ~40 km |
| **Latenza GPS** | Secondi | Tipicamente 30-120 sec | ultimoRilev lag |

---

## Abbreviazioni Comuni

| Abbreviazione | Significato | Contesto |
|---------------|-------------|----------|
| **PK** | Primary Key | Database |
| **FK** | Foreign Key | Database |
| **1:N** | One-to-Many | Relazioni entità |
| **N:N** | Many-to-Many | Relazioni entità |
| **GTFS** | General Transit Feed Specification | Standard Google |
| **API** | Application Programming Interface | ViaggiaTreno |
| **REST** | Representational State Transfer | Stile API |
| **JSON** | JavaScript Object Notation | Formato risposta |
| **CSV** | Comma-Separated Values | Formato GTFS |
| **HTML** | HyperText Markup Language | Infomobilità |
| **UTC** | Coordinated Universal Time | Fuso assoluto |
| **CET/CEST** | Central European Time / Summer Time | Fuso Italia |
| **WGS84** | World Geodetic System 84 | Coordinate geografiche |
| **RFI** | Rete Ferroviaria Italiana | Infrastruttura nazionale |
| **FS** | Ferrovie dello Stato | Holding Trenitalia |
| **RICS** | Registro Internazionale Codici Stazioni | Sistema GTFS NTS |

---

## Riferimenti Incrociati

- **GTFS Standard**: https://gtfs.org/
- **ViaggiaTreno**: VIAGGIATRENO.md (questo repo)
- **TRENORD GTFS**: TRENORD.md (questo repo)
- **Modello Dati**: ENTITA.md (questo repo)
- **Tabelloni RFI**: https://iechub.rfi.it/
- **Dati Lombardia**: https://www.dati.lombardia.it/

---

## Errori Comuni

| Errore | Causa | Soluzione |
|--------|-------|----------|
| numero_treno non univoco | Stesso numero su più treni | Usa terna (numero, origine, data) |
| Orario > 24:00 non riconosciuto | Parsing orario rigido | Permettere ore fino a 25+ |
| Stop non trovato | Codice RICS usato invece di S* | Usa sempre codici `S*` per GTFS/API |
| PlaceId iechub non funziona | Confuso con S-code | Mapping separato (tabella mapping) |
| Service_id non univoco | Condiviso da più trip | Join con calendar_dates per date |
| Coordinate WGS84 rifiutate | Sistema di riferimento diverso | Verificare EPSG:4326 |
| API 204 No Content | Treno soppresso/dato non disponibile | Gestire come errore soft, non hard |
| Content-Type bugiardo | regione API dichiara JSON, restituisce testo | Leggere come TEXT, poi parsare numero |
| Ritardo nella predizione | Dati real-time non sempre accurati | Aggiornare da API, non cache locale |

---

## Best Practices

✅ **DO**:
- Usa terna (numeroTreno, codOrigine, dataPartenzaTreno) come ID univoco treno
- Scarica GTFS periodicamente (almeno mensile per aggiornamenti pianificazione)
- Cache locale di stops.txt, routes.txt per ricerche offline
- Gestisci orari > 24:00 per corse notturne
- Usa coordinate WGS84 (EPSG:4326) per mappe
- Mappi stop_id S* ↔ PlaceId iechub per integrazione
- Fai query moderate a ViaggiaTreno API (non bombardare)
- Caccia 204 No Content come "dato non disponibile"

❌ **DON'T**:
- Usa numeroTreno come chiave primaria (non univoco!)
- Assumi che PlaceId iechub = codice S ViaggiaTreno (diversi!)
- Fai scraping massiccio di ViaggiaTreno (limitato, contatta per accesso)
- Ignora exception_type in calendar_dates (crittico per validità giorni)
- Assumi che binario effettivo = binario programmato (cambia spesso)
- Cache orari > 24 mesi (pianificazione diventa meno accurata)
- Tratta Content-Type dichiarato da API come gospel (verifica sempre!)

