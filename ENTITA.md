# SCHEMA ENTITY-RELATIONSHIP (ER) COMPLETO

## Diagramma ER Normalizzato

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ SCHEMA GTFS + VIAGGIATRENO - ENTITY RELATIONSHIP DIAGRAM (ERD)                 │
└──────────────────────────────────────────────────────────────────────────────────┘

╔═══════════════════╗
║    AGENCY         ║
╠═══════════════════╣
║ PK agency_id      ║ (1, 2, 4, 18, 63...)
║    name           ║ (Trenord, Trenitalia...)
║    url            ║
║    timezone       ║
║    codiceCliente  ║
╚═════════╤═════════╝
          │ 1:N
          │
┌─────────▼──────────┐
│   ROUTE/LINEA      │
├────────────────────┤
│ PK route_id        │ (R23, RE_4, S11...)
│    agency_id FK ──┼──► AGENCY
│    short_name      │ (R23, RE4)
│    long_name       │ (Domodossola-Milano)
│    color           │ (94C120)
│    route_type      │ (3)
│    url             │
└────────┬───────────┘
         │ 1:N
         │
    ┌────▼─────────┐         ┌──────────────────┐
    │ TRIP/CORSA   │ 1:N   N │ SERVICE/CALENDAR │
    ├──────────────┤────────┤├──────────────────┤
    │PK trip_id    │◄───────┼┤PK service_id     │
    │  route_id FK ├──────┐ ││  date (YYYYMMDD)│
    │  service_id  │      │ ││  exception_type  │
    │  short_name  │      │ │└──────────────────┘
    └────┬─────────┘      │
         │ 1:N          │ N
         │              │ (many dates/service)
    ┌────▼──────────────┐
    │ STOP_TIMES        │
    ├───────────────────┤
    │PK trip_id         │ (FK)
    │   stop_sequence   │
    │   stop_id FK ────┐│
    │   arrival_time   ││
    │   departure_time ││
    │   binario_prog   ││
    └─────────┬────────┘│
              │         │
    ┌─────────▼─────────▼┐
    │  STOPS/STAZIONI    │
    ├────────────────────┤
    │PK stop_id (S*)     │ (S01700=Milano, S00023=Novara...)
    │   name             │ (MILANO CENTRALE)
    │   lat              │ (45.486347)
    │   lon              │ (9.204528)
    │   url              │
    │   tipoStazione     │ (1, 3, 4)
    │   nomeCitta        │
    │   cod_regione FK ──┼──► REGION
    └────────────────────┘
                         (N:N - una stazione in 1+ tratte)
                              ▲
                              │ 1:N
    ┌─────────────────────────┼───────────────────┐
    │                         │                   │
    │  ┌──────────────────┐   │   ┌──────────────┐│
    │  │  TRATTA/SEGMENTO │   │   │  REGION      ││
    │  ├──────────────────┤   │   ├──────────────┤│
    │  │PK trattaAB       │   │   │PK codReg (1-22)
    │  │   trattaBA       │   │   │   nomeLungo  ││
    │  │   nodoA FK ──────┼───┼───┤              ││
    │  │   nodoB FK ──────┼───┘   └──────────────┘│
    │  │   occupata       │
    │  │   latA, lonA     │
    │  │   latB, lonB     │
    │  └──────────────────┘
    │
    └──────────────────────► N STOPS


╔════════════════════════════════════════════════════════════════════════════════╗
║ REAL-TIME LAYER (ViaggiaTreno API)                                            ║
╚════════════════════════════════════════════════════════════════════════════════╝

    TRAIN (ISTANZA REALE)
    ═════════════════════════════════════════════════════════════════════════════
    PK: (numeroTreno, codOrigine, dataPartenzaTreno) - TERNA UNIVOCA
    
    ┌────────────────────────────────────────────────────────────────────────┐
    │ TRAIN                                                                  │
    ├────────────────────────────────────────────────────────────────────────┤
    │ PK numeroTreno                                                         │
    │ PK codOrigine FK ─────────────► STOPS                                 │
    │ PK dataPartenzaTreno                                                   │
    │                                                                        │
    │ categoria (REG, IC, EC, FR)                                            │
    │ codiceCliente FK ─────────────► AGENCY                               │
    │ destinazione                                                           │
    │ partenzaTreno (ms reale)                                               │
    │ orarioPartenza (ms programmato)                                        │
    │ orarioArrivo (ms programmato)                                          │
    │ ultimoRilev (ms GPS)                                                   │
    │ materiale_label                                                        │
    │ orientamento                                                           │
    └────────────────────────────────────────────────────────────────────────┘
            │ 1:1            │ 1:N            │ 1:N
            │                │                │
        ┌───▼────────┐  ┌────▼──────────┐  ┌─▼──────────────────┐
        │TRAIN_STATUS│  │FERMATA_REALE[]│  │CORRISPONDENZA[]    │
        ├────────────┤  ├───────────────┤  ├────────────────────┤
        │tipoTreno   │  │stazione (S*) FK│  │treno_connesso      │
        │provvedimento│  │programmata(ms)│  │tempo_attesa        │
        │circolante  │  │effettiva(ms)  │  │stazione            │
        │inStazione  │  │ritardo(min)   │  │binario             │
        │nonPartito  │  │actualFermataTyp  └────────────────────┘
        │arrivato    │  │stop_sequence  │
        │            │  │binario_prog   │
        │            │  │binario_eff    │
        └────────────┘  │               │
                        │   ┌───────────▼──────────┐
                        │   │ RITARDO               │
                        │   ├──────────────────────┤
                        │   │ minuti               │
                        │   │ compRitardo[]        │ 9 lingue
                        │   │ compRitardoAndamento │
                        └───┤                      │
                            │ ┌──────────────────┐ │
                            │ │ BINARIO/PLATFORM │◄┘
                            │ ├──────────────────┤
                            │ │programmato       │
                            │ │effettivo         │
                            │ │codice numerico   │
                            │ │tipo              │
                            └─┴──────────────────┘

    ┌────────────────────────────────────────┐
    │ CAMBIO_NUMERO                          │
    ├────────────────────────────────────────┤
    │ numeroTreno (FK)                       │
    │ haCambiNumero (bool)                   │
    │ numeroTrenoSucc (numero successivo)    │
    └────────────────────────────────────────┘

╔════════════════════════════════════════════════════════════════════════════════╗
║ COMMUNICATIONS LAYER                                                           ║
╚════════════════════════════════════════════════════════════════════════════════╝

    ┌──────────────────────────┐     ┌──────────────────────┐
    │ INFOMOBILITÀ/INFOTRAFFIC │     │ SEGNALAZIONE/ALERT   │
    ├──────────────────────────┤     ├──────────────────────┤
    │ titolo                   │     │ numeroTreno (FK)     │
    │ data                     │     │ provvedimento        │
    │ testo                    │     │ riprogrammazione     │
    │ treni_coinvolti          │     │ fermate_soppresse[]  │
    │ categoria                │     └──────────────────────┘
    └──────────────────────────┘

    ┌───────────────────────┐    ┌────────────────────┐
    │ CATEGORIA_TRENO       │    │ MATERIALE_ROTABILE │
    ├───────────────────────┤    ├────────────────────┤
    │ categoria             │    │ materiale_label    │
    │ categoriaDescrizione  │    │ orientamento       │
    │ compNumeroTreno       │    │ descOrientamento[] │
    └───────────────────────┘    └────────────────────┘

    ┌────────────────────────┐
    │ SERVIZI_A_BORDO        │
    ├────────────────────────┤
    │ numeroTreno (FK)       │
    │ servizi[]              │
    │ (WiFi, biciclette...)  │
    └────────────────────────┘

╔════════════════════════════════════════════════════════════════════════════════╗
║ METADATA & CONFIGURATION LAYER                                                 ║
╚════════════════════════════════════════════════════════════════════════════════╝

    ┌────────────────────┐    ┌────────────────────┐
    │ FEED_GTFS          │    │ LINGUA             │
    ├────────────────────┤    ├────────────────────┤
    │publisher_name      │    │idLingua (it,en...) │
    │publisher_url       │    │traduzioni[]        │
    │feed_lang           │    │(242+ chiavi)       │
    └────────────────────┘    └────────────────────┘
```

---

## Entità Mancanti (Applicativo Layer - Non Implementate)

```
┌─────────────────────────────────┐
│ UTENTE (User)                   │
├─────────────────────────────────┤
│PK user_id                       │
│   email                         │
│   stazioni_favorite[]           │
│   notifiche_abilitate           │
│   preferenze_lingua             │
└──────────┬──────────────────────┘
           │ 1:N
           │
    ┌──────▼────────────────────────────────────┐
    │ VIAGGIO (Journey)                          │
    ├─────────────────────────────────────────┤ │
    │PK journey_id                            │ │
    │   user_id FK ─────────────────────────┐ │ │
    │   stazione_partenza FK (stops)        │ │ │
    │   stazione_arrivo FK (stops)          │ │ │
    │   data_partenza                       │ │ │
    │   ora_partenza (preferita)            │ │ │
    │   treni_candidati[] (N risultati)     │ │ │
    └───────┬────────────────────────────────┘ │ │
            │ 1:N                              │ │
            │                                  │ │
    ┌───────▼──────────────────────┐          │ │
    │ PRENOTAZIONE (Booking)       │          │ │
    ├──────────────────────────────┤          │ │
    │PK booking_id                 │          │ │
    │   user_id FK (UTENTE)        │◄─────────┘ │
    │   trip_id FK (TRIPS)         │            │
    │   numeroTreno FK (TRAIN)     │            │
    │   data_viaggio               │            │
    │   classe                     │            │
    │   posto / vagone             │            │
    │   stato (confirmed, used...) │            │
    │   prezzo                     │            │
    │   data_prenotazione          │            │
    └──────────┬───────────────────┘            │
               │ 1:N                           │
               │                               │
        ┌──────▼────────────────────────┐     │
        │ ALLARME/NOTIFICA (Alert)      │     │
        ├───────────────────────────────┤     │
        │PK alert_id                    │     │
        │   user_id FK (UTENTE)         │◄────┘
        │   booking_id FK (optional)    │
        │   numeroTreno FK (TRAIN)      │
        │   tipo (delay, cancellation..)│
        │   threshold (es: >10 min)     │
        │   stato (sent, read, acted)   │
        │   created_at                  │
        │   triggered_at                │
        └───────────────────────────────┘
```

**NOTA**: Queste entità sono POTENZIALI - richiedono backend/database custom (non fornite da GTFS/API)

---

## Chiavi Esterne (Foreign Key Mapping)

| Tabella | Colonna | Riferisce a | Tipo |
|---------|---------|------------|------|
| routes.txt | agency_id | agency.txt::agency_id | 1:N |
| trips.txt | route_id | routes.txt::route_id | 1:N |
| trips.txt | service_id | calendar_dates.txt::service_id | 1:N |
| stop_times.txt | trip_id | trips.txt::trip_id | 1:N |
| stop_times.txt | stop_id | stops.txt::stop_id | 1:N |
| stops.txt | (implica) | regione (codReg) | N:1 |
| TRAIN (API) | codOrigine | stops.txt::stop_id | N:1 |
| TRAIN (API) | codiceCliente | agency.txt::agency_id | N:1 |
| FERMATA_REALE (API) | stazione | stops.txt::stop_id | N:1 |
| CORRISPONDENZA (API) | treno_connesso | TRAIN (numeroTreno, codOrigine, dataPart) | N:1 |
| TRATTA (API) | nodoA | stops.txt::stop_id | N:1 |
| TRATTA (API) | nodoB | stops.txt::stop_id | N:1 |

---

## Indici Consigliati per Performance

| Tabella | Colonna(e) | Tipo | Motivo |
|---------|-----------|------|--------|
| stops.txt | stop_id | PRIMARY | Lookup stazioni |
| stops.txt | stop_name | UNIQUE | Ricerca per nome |
| stops.txt | (lat, lon) | SPATIAL | Query geografiche |
| routes.txt | route_id | PRIMARY | Lookup linee |
| routes.txt | agency_id | FOREIGN | Join con agency |
| trips.txt | trip_id | PRIMARY | Lookup corse |
| trips.txt | route_id | FOREIGN | Join con routes |
| trips.txt | service_id | FOREIGN | Join con calendar |
| stop_times.txt | (trip_id, stop_sequence) | PRIMARY COMPOSITE | Lookup fermate |
| stop_times.txt | stop_id | FOREIGN | Reverse lookup |
| calendar_dates.txt | (service_id, date) | PRIMARY COMPOSITE | Lookup date |
| calendar_dates.txt | date | INDEX | Query per data |
| TRAIN (API) | (numeroTreno, codOrigine, dataPartenzaTreno) | UNIQUE COMPOSITE | Terna univoca |
| TRAIN (API) | codOrigine | INDEX | Partenze/arrivi |
| FERMATA_REALE (API) | (numeroTreno, stop_id) | INDEX | Lookups complesse |

---

## Query Tipiche e Pattern di Accesso

### 1. Pianificazione Offline: Orari completi Milano-Como domani
```sql
SELECT st.arrival_time, st.departure_time, t.trip_short_name, r.route_short_name
FROM stop_times st
JOIN trips t ON st.trip_id = t.trip_id
JOIN routes r ON t.route_id = r.route_id
JOIN calendar_dates cd ON t.service_id = cd.service_id
WHERE st.stop_id = 'S01700'  -- Milano Centrale
  AND cd.date = '20261105'   -- Tomorrow
  AND cd.exception_type = 1  -- Service active
ORDER BY st.departure_time;
```

### 2. Real-time: Treni da Milano Centrale adesso
```
GET /partenze/S01700/Sun%20Oct%2004%202026%2008%3A12%3A27%20GMT%2B0200
Response: Array[TRAIN] con 33 elementi
```

### 3. Corsa completa: Orari e fermate di un treno
```
GET /andamentoTreno/S00219/9611/1791064800000
Response: TRAIN + FERMATA_REALE[] (6 fermate) + RITARDO per ognuna
```

### 4. Cercata linea R23: Tutte le stazioni toccate
```sql
SELECT DISTINCT s.stop_id, s.stop_name, s.stop_lat, s.stop_lon
FROM stops s
JOIN stop_times st ON s.stop_id = st.stop_id
JOIN trips t ON st.trip_id = t.trip_id
JOIN routes r ON t.route_id = r.route_id
WHERE r.route_id = 'R23'
ORDER BY st.stop_sequence;
```

### 5. Infomobilità: Quali treni sono coinvolti in segnalazioni?
```
GET /infomobilitaRSS/false
Parse HTML: Estrai treni (numeroTreno, codOrigine) per ogni news
```

---

## Normalizzazione

**Grado di normalizzazione**: 3NF (terza forma normale)

- **1NF**: Tutti gli attributi atomici ✅
- **2NF**: No dipendenze parziali da chiave composta ✅
- **3NF**: No dipendenze transitive ✅

**Eccezioni (denormalizzazione controllata)**:
- `routes.codiceCliente`: Ridondante con `agency_id` ma presente per performance query real-time ViaggiaTreno
- `TRAIN.categoria`, `TRAIN.codiceCliente`: Presenti su ogni istanza per velocità lookup, non per normalizzazione
- `FERMATA_REALE` in `TRAIN`: Nested (array), non normalizzato, ma riflette struttura API ViaggiaTreno

---

## Vincoli di Integrità

| Vincolo | Tipo | Descrizione |
|---------|------|-------------|
| stop_id (`^S\d{5}$`) | CHECK | Formato codice stazione |
| route_type ∈ {2,3} | CHECK | Tipo trasporto valido |
| arrival_time ≤ 24:59:59 o 25+ | CHECK | Orario possibile (notturne) |
| departure_time ≤ 24:59:59 o 25+ | CHECK | Orario possibile (notturne) |
| exception_type ∈ {1,2} | CHECK | Tipo calendario valido |
| tipoTreno ∈ {PG,ST,PP,SF,SI,DV,SM,VD,VO} | CHECK | Stato treno valido |
| provvedimento ∈ {0,1,2,3} | CHECK | Provvedimento valido |
| (numeroTreno, codOrigine, dataPartenzaTreno) UNIQUE | UNIQUE | Terna treno |
| (trip_id, stop_sequence) UNIQUE | UNIQUE | Fermata per trip |
| (service_id, date) UNIQUE | UNIQUE | Data per servizio |
| lat ∈ [-90, 90], lon ∈ [-180, 180] | CHECK | Coordinate WGS84 valide |

---

## Tabelle Riepilogative Secondarie

### Codici Regione (1-22)
```sql
INSERT INTO region (codReg, nomeLungo, label) VALUES
(1, 'Lombardia', 'Lombardia'),
(2, 'Liguria', 'Liguria'),
...
(22, 'Provincia autonoma di Bolzano', 'Bolzano-Bozen');
```

### Codici Cliente/Agenzia
```sql
INSERT INTO agency (agency_id, agency_name, codiceCliente) VALUES
(1, 'Trenitalia (Alta Velocità)', 1),
(2, 'Trenitalia (Regionali)', 2),
(3, 'Trenitalia (InterCity)', 4),
(4, 'Trenitalia Tper', 18),
(5, 'Trenord', 63),
(6, 'TILO', 64),
...;
```

### Categorie Treno
```sql
INSERT INTO train_category (categoria, categoriaDescrizione, colore) VALUES
('REG', 'Regionale', '#006633'),
('IC', 'InterCity', '#E8A200'),
('EC', 'EuroCity', '#A71640'),
('FR', 'Freccia', '#C60C30'),
(..., '...', ...);
```

### Tipi Fermata
```
1 = Già effettuata / Regolare
0 = Dato non disponibile (treno non ancora arrivato)
2 = Non prevista
3 = Soppressa
```

### Tipi Stazione
```
1 = Principale
3 = Regolare
4 = Placeholder (ignorare)
```

---

## Cardinalità Stimate (Dati Reali Oct 2026)

| Entità | Cardinalità | Nota |
|--------|-------------|------|
| Agenzie | 1 | Solo Trenord in GTFS |
| Regioni | 22 | 1-22 |
| Stazioni | ~3,000 | stops.txt |
| Linee | ~250-300 | routes.txt |
| Corse (6 mesi) | ~40,000 | trips.txt |
| Orari di Fermata | ~2,000,000 | stop_times.txt |
| Calendari | ~10,000,000+ | calendar_dates.txt |
| Tratte/Segmenti | ~135 | elencoTratte API |
| Treni Circolanti (istante) | ~600 | statistiche API |
| Treni Partenza/Arrivo (stazione/ora) | ~10-50 | partenze/arrivi API |

