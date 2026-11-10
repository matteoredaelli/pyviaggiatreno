# INDICE GENERALE - Documentazione Ferroviaria

## Riepilogo Repository

Questo repository contiene documentazione **completa e integrata** su:
- **GTFS Trenord** (Pianificazione ferroviaria regionale Lombardia)
- **ViaggiaTreno API** (Dati real-time circolazione nazionale)
- **Infrastruttura RFI** (Tabelloni stazioni, tratte, topologia rete)
- **Modello Dati** (Entità, relazioni, schema ER)
- **Terminologia** (Glossario ferroviario + tecnico)

---

## 📚 Documenti

### 1. **GTFS TRENORD** → [`TRENORD.md`](./TRENORD.md)
**Cosa contiene**: Documentazione completa del dataset GTFS Trenord scaricato da dati.lombardia.it

#### Sezioni:
- ✅ Fonte ufficiale e metadata
- ✅ 7 file CSV: agency.txt, stops.txt, routes.txt, trips.txt, stop_times.txt, calendar_dates.txt, feed_info.txt
- ✅ Per ogni file: struttura, campi, esempi, statistiche
- ✅ Dimensioni dati (21 MB totali, 10M+ righe)
- ✅ Correlazione con ViaggiaTreno (stop_id identici: `S01700` ecc.)
- ✅ 6 Casi d'uso (pianificazione, analisi, integrazione, validazione, prenotazioni)
- ✅ Parsing code (Python, JavaScript, SQL)
- ✅ 10 Insidie note

#### Quando usare:
- Pianificazione **offline** di viaggio
- Analisi della **rete regionale** Trenord
- **Integrazione** con navigatori / mappe
- **Validazione** dati real-time
- Dataset per **ricerca / machine learning**

---

### 2. **VIAGGIATRENO API** → [`VIAGGIATRENO.md`](./VIAGGIATRENO.md)
**Cosa contiene**: Documentazione API non ufficiali ViaggiaTreno (scoperte dalla community)

#### Sezioni:
- ✅ API base endpoint HTTP GET (20+ endpoint)
- ✅ Stazioni: autocompletaStazione, cercaStazione, dettaglioStazione, elencoStazioni
- ✅ Partenze/Arrivi: `partenze`, `arrivi` (orari pianificati + real-time)
- ✅ Treni: cercaNumeroTreno, andamentoTreno (percorso completo con ritardi/binari)
- ✅ Tratte: elencoTratte, dettagliTratta (segmenti rete + treni in transito)
- ✅ Infomobilità: RSS notizie, segnalazioni, lavori
- ✅ Metadata: statistiche, meteo, lingue (9 lingue: it, en, de, fr, es, ro, ja, zh, ru)
- ✅ Tabelloni RFI (iechub.rfi.it): visualizzazione web real-time
- ✅ Tabelle di riferimento (codici regione, operatori, stati treno)
- ✅ 12 Insidie note (HTTP 204, Content-Type bugiardo, orari > 24:00, cancellazioni parziali)

#### Quando usare:
- **Real-time** monitoraggio treni (ritardi, binari, stato)
- **Tabelloni** di stazione (elenco partenze/arrivi)
- Ricerca **numero treno** e percorso completo
- **Correzioni** automatiche binario/ritardo
- Notizie **infomobilità** (scioperi, lavori)

#### Rate Limiting:
- ❌ Non documentato ufficialmente
- ⚠️ Uso moderato consigliato (non bombardare)
- 📞 Contatta RFI/Trenitalia per accesso dati ufficiale

---

### 3. **TABELLONI RFI** → Sezione in VIAGGIATRENO.md
**URL**: https://iechub.rfi.it/ArriviPartenze/ArrivalsDepartures/Monitor

**Parametri**:
- `Arrivals`: true/false (arrivi o partenze)
- `Search`: nome stazione (opzionale)
- `PlaceId`: ID stazione (es. `1728` = Milano Centrale)

**Note**:
- HTML5 interattivo con aggiornamenti real-time
- PlaceId diverso da codice ViaggiaTreno (`S*`)
- Replica esattamente i tabelloni di stazione
- Mapping PlaceId non documentato → scarsa automatizzazione

---

### 4. **MODELLO DATI INTEGRATO** → [`ENTITA.md`](./ENTITA.md)
**Cosa contiene**: Analisi completa delle 27 entità dal sistema ferroviario

#### Sezioni:
- ✅ Diagramma ER visuale (ASCII art)
- ✅ 6 Layer di dati:
  1. **Infrastruttura statica** (Stazione, Linea, Tratta, Regione)
  2. **Pianificazione** (Corsa, Orario Fermata, Calendario)
  3. **Real-time** (Treno istanza, Stato, Fermata Reale, Ritardo, Binario, Cambio numero)
  4. **Comunicazioni** (Infomobilità, Segnalazione, Categoria, Materiale, Corrispondenza)
  5. **Metadata** (Agenzia, Feed GTFS, Lingua)
  6. **Applicativo** (Utente, Viaggio, Prenotazione, Allarmi) - ❌ Non implementato
- ✅ Tabella entità dettagliata (27 righe, PK/UK, campi, fonte)
- ✅ Relazioni N:N critiche
- ✅ Chiavi naturali vs surrogate
- ✅ Foreign key mapping
- ✅ Indici consigliati per performance
- ✅ Query tipiche (SQL examples)
- ✅ Normalizzazione (3NF)
- ✅ Vincoli integrità
- ✅ Dimensioni stimate
- ✅ MVP essenziale vs nice-to-have

#### Entità Principali:
| # | Entità | Fonte | Cardinalità |
|---|--------|-------|-------------|
| 1 | **Stazione** | GTFS stops.txt | ~3,000 |
| 2 | **Linea** | GTFS routes.txt | ~250-300 |
| 3 | **Corsa (Trip)** | GTFS trips.txt | ~40,000 |
| 4 | **Orario Fermata** | GTFS stop_times.txt | ~2,000,000 |
| 5 | **Calendario** | GTFS calendar_dates.txt | ~10,000,000+ |
| 6 | **Treno (Real-time)** | API partenze/arrivi | ~600 circolanti |
| 7 | **Fermata Reale** | API andamentoTreno | 6-100 per treno |
| 8 | **Ritardo** | API partenze/arrivi | Per ogni fermata |

**Assenti**:
- ❌ Prenotazione (senza backend)
- ❌ Utente/Account (senza DB)
- ❌ Tariffe/Prezzi (non pubblicati)
- ❌ Allarmi utente (senza notifiche)

---

### 5. **GLOSSARIO** → [`GLOSSARIO.md`](./GLOSSARIO.md)
**Cosa contiene**: Terminologia completa ferroviaria + tecnica

#### Sezioni:
- ✅ Terminologia ferroviaria (Stazione, Fermata, Nodo, Linea, Tratta, Treno, Binario...)
- ✅ Categorie treno (FR, IC, EC, REG, S, EN con colori e velocità)
- ✅ Stati treno (PG, ST, PP, SF, DV... con provvedimenti 0-3)
- ✅ Tipi fermata (1=ok, 0=non disponibile, 2=non prevista, 3=soppressa)
- ✅ Ritardi e timing
- ✅ Terminologia GTFS (Agency, Route, Trip, Stop, StopTime, Service, Feed)
- ✅ Terminologia ViaggiaTreno (Andamento, Infomobilità, Orientamento, Cambio numero...)
- ✅ Identificatori chiave (Codici stazione S*, RICS, PlaceId; Numero treno; Trip ID; Service ID)
- ✅ Concetti temporali (Timestamp ms, orari > 24:00, timezone CET/CEST)
- ✅ Concetti geografici (WGS84, coordinate Italia, distanza Haversine)
- ✅ Pianificazione (Periodi invernale/estiva, frequenza, ore punta)
- ✅ Operatori ferroviari (Codici cliente 1, 2, 4, 18, 63, 64, 910...)
- ✅ Unità di misura (minuti, ms, km/h, km)
- ✅ Abbreviazioni (PK, FK, GTFS, API, REST, JSON, UTC...)
- ✅ 6 Errori comuni + 12 Best practices

---

## 🎯 Guida Rapida per Caso d'Uso

### Caso 1: "Voglio un'app di pianificazione OFFLINE"
**Usa**: TRENORD.md + ENTITA.md  
**Dati**: Scarica GTFS, importa in SQLite/DB locale  
**Entità**: Stazione, Linea, Corsa, OrarioFermata, Calendario  
**Query**: Trova treni A→B domani da stops.txt + stop_times.txt  
**Tempo setup**: 2-4 ore  

### Caso 2: "Voglio monitorare RITARDI in tempo reale"
**Usa**: VIAGGIATRENO.md + ENTITA.md  
**Dati**: Polling API andamentoTreno ogni 30-60 sec  
**Entità**: Treno, FermataReale, Ritardo, Binario, TrainStatus  
**API**: GET /andamentoTreno/{codOrigine}/{numeroTreno}/{dataPart}  
**Tempo setup**: 1-2 ore  

### Caso 3: "Voglio i TABELLONI di stazione"
**Usa**: VIAGGIATRENO.md (sezione Tabelloni RFI)  
**Dati**: Accedi a https://iechub.rfi.it/...  
**Entità**: Stazione, Treno, FermataReale, Ritardo, Binario  
**HTML**: Real-time JavaScript (display nativo)  
**Tempo setup**: <30 min  

### Caso 4: "Voglio ANALIZZARE la rete regionale"
**Usa**: TRENORD.md + ENTITA.md + GLOSSARIO.md  
**Dati**: GTFS completo, query aggregazioni  
**Entità**: Linea, Stazione, Corsa, Frequenza  
**Query SQL**: Densità servizio per linea, copertura geografica, orari punta  
**Tempo setup**: 3-5 ore  

### Caso 5: "Voglio INTEGRARE con Google Maps"
**Usa**: TRENORD.md + VIAGGIATRENO.md  
**Dati**: GTFS (pianificazione) + API (real-time)  
**Entità**: Stazione (coordinate WGS84), Linea (geometry da stops), Treno (posizione GPS)  
**API Google**: Polyline encoding, marker clustering  
**Tempo setup**: 4-6 ore  

### Caso 6: "Voglio un CHATBOT ferroviario"
**Usa**: VIAGGIATRENO.md + GLOSSARIO.md  
**Dati**: API ViaggiaTreno (domande NLP → endpoint)  
**Entità**: Stazione (autocompletamento), Treno (search), Andamento  
**NLP**: Entity extraction (stazioni), intent classification (info/horari/real-time)  
**Tempo setup**: 8-12 ore  

---

## 🗂️ Struttura dei File

```
.
├── README.md                    (Overview del monorepo + quick start)
├── AGENTS.md                    (Guida sintetica per agenti AI/contributori)
├── RELEASE.md                   (Processo di release su PyPI)
├── VIAGGIATRENO.md              (API rest, 50+ endpoint, 3k righe)
├── TRENORD.md                   (GTFS, 7 file, pianificazione, 400 righe)
├── ENTITA.md                    (Schema ER, 27 entità, 600+ righe)
├── GLOSSARIO.md                 (Terminologia, best practices, 700+ righe)
├── COPERTURA_GEOGRAFICA.md      (Copertura GTFS Trenord vs API ViaggiaTreno)
├── INDICE.md (questo file)      (Guida navigazione, 400+ righe)
├── Makefile                     (lint / test / build / publish)
├── pyproject.toml               (Workspace uv, 3 pacchetti)
├── probe_viaggiatreno.py        (Script probe dati live - opzionale)
├── data/
│   └── treni.db                 (DB SQLite prodotto dal crawler)
├── samples/                     (Risposte API di esempio)
├── tests/                       (Test del workspace)
└── packages/
    ├── viaggiatreno/            (Libreria client HTTP async - core)
    ├── viaggiatreno_mcp/        (Server MCP)
    └── viaggiatreno_crawler/    (Poller → SQLite)
```

---

## 📊 Statistiche Dati

### GTFS Trenord (Ottobre 2026)
| Aspetto | Valore |
|---------|--------|
| **Agenzie** | 1 |
| **Regioni** | 22 |
| **Stazioni** | ~3,000 |
| **Linee** | ~250-300 |
| **Corse (6 mesi)** | ~40,000 |
| **Orari Fermate** | ~2,000,000 |
| **Calendari** | ~10,000,000+ |
| **Dimensione ZIP** | ~21 MB |
| **Dimensione Extract** | ~25-30 MB |

### ViaggiaTreno Real-time (istante)
| Aspetto | Valore |
|---------|--------|
| **Treni Circolanti** | ~600-650 |
| **Partenze/Arrivi (stazione/ora)** | 10-50 |
| **Fermate per Treno** | 6-100 |
| **Campi per Treno** | 74 |
| **Lingue** | 9 |
| **Response Size** | 50-200 KB |
| **Latenza API** | 200-500 ms |

---

## 🔄 Flusso di Integrazione Consigliato

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. CARICA GTFS IN DB (Setup iniziale, once)                        │
│    Download: dati.lombardia.it → Unzip → CSV Parse                 │
│    Inserisci in: stops, routes, trips, stop_times, calendar_dates  │
│    Tempo: 1-2 ore                                                   │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 2. QUERY GTFS PER PIANIFICAZIONE (Ricerca offline)                 │
│    "Quali treni da Milano a Como domani 08:00-09:00?"              │
│    Query: stops + stop_times + calendar_dates con JOIN              │
│    Risultato: N corse candidate con orari programmati              │
│    Tempo: <100 ms                                                   │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 3. ARRICCHISCI CON REAL-TIME (Per ognuna delle candidate)          │
│    Estrai: numeroTreno, codOrigine, dataPartenzaTreno da GTFS      │
│    Chiama: GET /andamentoTreno/{codOrigine}/{numero}/{data}        │
│    Estrai: orari effettivi, ritardi, binari, stato                 │
│    Tempo: N × 300-500 ms (parallelize!)                            │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 4. MOSTRA RISULTATO INTEGRATO                                       │
│    Programato: Milano 08:10 → Como 08:52 (Linea R23)               │
│    Reale:     Milano 08:15 (+5 min) | Binario 11 | Ritardo 5 min   │
│    Stato:     REG • In orario • Circolante • Non partito           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## ✅ Checklist Implementazione MVP

- [ ] **Setup DB**: SQLite con GTFS tables (stops, routes, trips, stop_times, calendar_dates)
- [ ] **Queries GTFS**: Test SELECT per stazioni, linee, orari
- [ ] **API ViaggiaTreno**: Test 3 endpoint (autocompletaStazione, partenze, andamentoTreno)
- [ ] **Mapping S* ↔ ViaggiaTreno**: Validare stop_id (es: `S01700` = Milano Centrale)
- [ ] **Infomobilità**: Parse RSS da infomobilitaRSS
- [ ] **Errorhandling**: HTTP 204, null fields, Content-Type bugs
- [ ] **Multilingua**: Supporto 9 lingue da API language
- [ ] **Caching**: GTFS in RAM, API with TTL 1-5 min
- [ ] **Testing**: Probe dati live, validare esempi da doc
- [ ] **UI**: Visualizzazione treni con ritardi/binari
- [ ] **Monitoring**: Alerting su cancellazioni/soppressioni
- [ ] **Deployment**: Cloud (AWS, Heroku, etc.)

---

## 🚀 Performance & Scalability

### Ottimizzazioni GTFS
- **Index**: stop_id, route_id, trip_id, (trip_id, stop_sequence), date
- **Partitioning**: calendar_dates per mese (10M righe → N × 1M)
- **Cache**: stops.txt, routes.txt in RAM (piccoli, riusati)
- **Compression**: ZIP per archivio (21 MB → ricordare di decomprimere)

### Ottimizzazioni ViaggiaTreno API
- **Parallelizzazione**: Chamata N andamentoTreno in parallelo (thread pool)
- **Timeout**: 5 sec per request (protegge da hang)
- **Retry**: Exponential backoff su 429/503
- **Cache**: Risultati con TTL 1 min (cambiano in tempo reale)
- **Rate Limiting**: Max 10 req/sec (stima, non ufficiale)

### Database
- **Rows**: GTFS 2M+ rows → SQLite ok, PostgreSQL migliore per scale
- **Indexes**: 10-15 indici critici → ~500 MB disk
- **Queries**: 95th percentile <100 ms (con indici buoni)

---

## 📖 Riferimenti

### Documentazione Ufficiale
- **GTFS**: https://gtfs.org/
- **Trenord**: https://www.trenord.it/
- **RFI**: https://www.rfi.it/
- **Dati Lombardia**: https://www.dati.lombardia.it/
- **ViaggiaTreno**: http://www.viaggiatreno.it/

### Fonti Interne (repo)
- **DLT**: https://github.com/dltmtt/viaggiatreno-api (JSON Schema, ricerca)
- **MB**: https://github.com/MarcoBuster/railway-opendata (Wiki 2023)
- **GT**: https://github.com/Geek-Tek/trenitalia-open-api (TypeScript, elencoTratte)
- **TM**: https://github.com/roughconsensusandrunningcode/TrainMonitor/wiki (Archived 2025)
- **MC**: https://github.com/marcocot/trenitalia-api (README only)

### Comunità
- **GitHub Issues**: Discussioni su API instabilità
- **Gists**: Parsing examples
- **Reddit**: r/italy ferrovie (informal)

---

## 📝 Note Finali

### Cosa Funziona Bene ✅
- ✅ GTFS Trenord: Completo, aggiornato, standardizzato
- ✅ ViaggiaTreno API: Ricco di dettagli, coprisce tutte le operazioni
- ✅ Identificatori: stop_id coerenti fra GTFS e API
- ✅ Coordinate: WGS84 precise, usi GIS possibili
- ✅ Multilingua: 9 lingue complete

### Cosa è Limitato ⚠️
- ⚠️ Tariffe: Non pubblicate da nessuno (contattare Trenitalia)
- ⚠️ Prenotazioni: Non disponibili via API (servizio web Trenitalia only)
- ⚠️ Cambio numero: Non esplicito in GTFS (tripID può cambiare)
- ⚠️ Cancellazioni parziali: Difficili da tracciare (can return HTTP 204)
- ⚠️ Rate limiting ViaggiaTreno: Non documentato ufficialmente

### Cosa Manca ❌
- ❌ Infrastruttura rete (topologia binari in stazione)
- ❌ Composizione materiale (solo label generico)
- ❌ Velocità massima per tratta
- ❌ Dati idoneità accessibilità
- ❌ Storici ritardi (per ML/analytics)
- ❌ API ufficiale (solo reverse-engineering)

### Evoluzione Consigliata
- 📈 Monitorare https://www.dati.lombardia.it/ per aggiornamenti GTFS
- 📈 Cache/Mirror ViaggiaTreno per affidabilità
- 📈 Proporre API ufficiale a Trenitalia/RFI
- 📈 Contatti con comunità dev (GitHub, gists, forum)
- 📈 Contribute improvements back to open sources

---

**Versione**: 1.0  
**Data**: Ottobre 2026  
**Ultimo Aggiornamento**: 2026-10-04  
**Licenza**: CC-BY 4.0 (come GTFS Trenord)  
**Autore**: Community documentation


---

## 🚨 AVVISO CRITICO: Copertura Geografica

**GTFS Trenord contiene SOLO Lombardia (~3,000 stazioni)**

Se hai bisogno di stazioni di altre regioni italiane, devi usare le **API ViaggiaTreno** che coprono ~7,000-8,000 stazioni per tutta Italia.

**Leggi** [COPERTURA_GEOGRAFICA.md](./COPERTURA_GEOGRAFICA.md) **prima di iniziare il design!**

| Aspetto | GTFS Trenord | API ViaggiaTreno |
|---------|--------------|------------------|
| Copertura | 🔴 Solo Lombardia | 🟢 Tutta Italia |
| Stazioni | 3,000 | 7,000-8,000 |
| Per Regione | NO | 🟢 Sì (/elencoStazioni/{region}) |
| Tipo | Pianificazione | Real-time |

**Impatto su MVP**:
- Solo Lombardia? → Usa GTFS Trenord (2-4 ore)
- Multi-regione? → Usa API /elencoStazioni (1-2 ore) oppure multi-GTFS (20 ore)

