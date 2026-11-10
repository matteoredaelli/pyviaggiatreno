# ⚠️ AVVISO CRITICO: Copertura Geografica GTFS vs API

## Problema

Hai correttamente identificato che:
- **GTFS Trenord** = Solo Lombardia (~3,000 stazioni)
- **ViaggiaTreno API** = Tutta Italia (~7,000-8,000 stazioni)

Questa è una **limitazione critica** che cambia il design dell'architettura dati.

---

## Tabella Comparativa

| Aspetto | GTFS Trenord | ViaggiaTreno API |
|---------|--------------|------------------|
| **Copertura** | 🔴 **Solo Lombardia** | 🟢 **Tutta Italia** |
| **Stazioni** | ~3,000 Trenord | ~7,000-8,000 |
| **Per Regione** | NO (tutto insieme) | 🟢 **Sì** (/elencoStazioni/{region}) |
| **Granularità** | Regionale | Nazionale |
| **Operatori** | Trenord + piccoli | Trenitalia + tutti |
| **Tipo** | Pianificazione (offline) | Real-time |
| **Aggiornamento** | Mensile | Continuo |
| **Uso** | Backend DB | Frontend/API |

---

## Implicazioni Architetturali

### Se Serve Multi-Regione (Non Solo Lombardia)

❌ **NON puoi usare GTFS Trenord da solo**

```
GTFS Trenord (Lombardia)
       ↓
   Pianificazione
   3k stazioni
   Only Trenord
   
   ❌ Problema: Altre regioni NON coperte!
```

✅ **Devi integrare API ViaggiaTreno**:

```
API /elencoStazioni/1   (Lombardia)      + GTFS Trenord (pianificazione)
API /elencoStazioni/3   (Piemonte)       + GTFS Trenitalia?
API /elencoStazioni/5   (Lazio)          + GTFS Trenitalia?
API /elencoStazioni/13  (Toscana)        + GTFS Trenitalia?
...
   ↓ ↓ ↓ ↓
   7k-8k stazioni
   Tutte le regioni
   Real-time sempre
```

---

## Strategie per Regione

### Scenario 1: App Solo Lombardia ✅

```
✓ GTFS Trenord (stops.txt)          → 3,000 stazioni
✓ API /elencoStazioni/1              → stesse 3k (backup/real-time)
✓ Pianificazione: GTFS               → DB locale
✓ Real-time: API ViaggiaTreno        → Polling
✓ Setup: 2-4 ore
✓ Complessità: BASSA
```

**Architettura**:
```
GTFS Trenord
    ↓
SQLite (stops, routes, trips, stop_times)
    ↓
Query pianificazione (Milano → Como?)
    ↓
Estrai numero/origine/data
    ↓
ViaggiaTreno API /andamentoTreno
    ↓
Merge programmato + effettivo
```

### Scenario 2: App Multi-Regione (Italia) ⚠️

```
❌ GTFS Trenord           → Lombardia only
❌ Non ha pianificazione per altre regioni
✓ Devi usare GTFS multipli (Trenitalia, FSE, Trenitero...)
✓ Oppure: Real-time only via API (no pianificazione offline)
✓ Setup: 8-20 ore
✓ Complessità: ALTA
```

**Opzione A: Real-time Only** (Easiest)
```
API /elencoStazioni/1   → 345 stazioni Lombardia
API /elencoStazioni/3   → 400 stazioni Piemonte
API /elencoStazioni/5   → 350 stazioni Lazio
...
    ↓ Cache locale
    ↓
Pianificazione offline: NON disponibile
Real-time: Sempre disponibile via API
```

**Opzione B: Full Stack** (Complex)
```
GTFS Trenord            → Lombardia (21 MB)
GTFS Trenitalia         → Nazionali (100+ MB)
GTFS FSE / Trenitero    → Sud Italia (~50 MB)
    ↓
SQLite centralizzato (1000+ MB DB)
    ↓
Queries: SELECT * FROM stops WHERE region = 5
    ↓
Real-time: API ViaggiaTreno
```

---

## Come Accedere a Stazioni per Regione (API)

### Method 1: `/elencoStazioni/{region}`

```bash
# Get tutte le stazioni della Lombardia (regione 1)
curl http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/elencoStazioni/1

# Response: JSON array con ~345 stazioni

# Get Lazio (regione 5)
curl http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/elencoStazioni/5
# Response: ~350 stazioni
```

### Method 2: Get Regione di una Stazione

```bash
# Se hai stop_id, scopri la regione
curl http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/regione/S06421

# Response: 13 (Toscana)
```

### Method 3: Autocompletamento Prefix

```bash
# Cerca stazioni di una città (qualsiasi regione)
curl http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/autocompletaStazione/roma

# Response: text/plain
# ROMA TERMINI|S08000
# ROMA TIBURTINA|S08227
# ROMA OSTIENSE|S08214
# ... (tutte le Roma d'Italia)
```

---

## Cache Strategy (Consigliato per Performance)

```python
# SETUP (call once per mese)
stations_by_region = {}

for region_id in range(1, 23):
    try:
        stations_by_region[region_id] = GET(f"/elencoStazioni/{region_id}")
        print(f"Region {region_id}: {len(stations_by_region[region_id])} stations")
    except:
        pass

# QUERIES (istantanee, no API call)
lombardy_stations = stations_by_region[1]  # 345 stazioni
lazio_stations = stations_by_region[5]  # 350 stazioni
toscana_stations = stations_by_region[13]  # 200 stazioni

# Search in cache
milano_centrale = next(s for s in lombardy_stations if s["stop_id"] == "S01700")
```

---

## Cardinalità Corretta per Entità "Stazione"

| Contesto | Cardinalità | Fonte |
|----------|------------|-------|
| **GTFS Trenord** | ~3,000 | stops.txt (Lombardia) |
| **API /elencoStazioni/1** | ~345 | ViaggiaTreno (Lombardia) |
| **API /elencoStazioni/** (all) | ~7,000-8,000 | ViaggiaTreno (Italia) |
| **API autocompletaStazione** | ~7,000-8,000 | ViaggiaTreno (Italia) |

**Scelta dipende dal tuo caso d'uso**:
- Solo Lombardia? → 3k (GTFS Trenord)
- Italia? → 7k-8k (API ViaggiaTreno)

---

## Impatto sulla Documentazione

### Documenti da Aggiornare

1. ✅ **TRENORD.md**
   - Aggiunto warning: "Solo Lombardia"
   - Aggiunto capitolo: "Accesso stazioni per regione via API"
   - Link a /elencoStazioni

2. ⚠️ **ENTITA.md**
   - Stazione: Mostra cardinalità doppia (3k GTFS, 7k-8k API)
   - Nota sulla copertura geografica

3. 📌 **VIAGGIATRENO.md**
   - Enfatizzare /elencoStazioni come alternativa a GTFS per multi-regione
   - Aggiungere sezione: "Trovare stazioni per regione"

4. 📝 **GLOSSARIO.md**
   - Chiarire differenza tra GTFS (pianificazione, regionale) e API (real-time, nazionale)

5. 🎯 **INDICE.md**
   - Update MVP: Stazioni (3k vs 7k a seconda del scope)

---

## Raccomandazione Finale

### Se Inizi Progetto Nuovo: **Scegli Base su Scope**

```
┌─────────────────────────────┐
│ Domanda: Multi-regione?     │
└──────────────┬──────────────┘
               │
      ┌────────┴────────┐
      │                 │
   NO │                 │ YES
      │                 │
  (Lombardia)      (Italia+)
      ↓                 ↓
┌───────────┐     ┌────────────────┐
│GTFS+API   │     │API Only (Easy) │
│Mixed      │     │oppure          │
│2-4 h      │     │Multi-GTFS      │
└───────────┘     │8-20 h          │
                  └────────────────┘
```

---

## Prossimi Step

1. ✅ Chiarito in TRENORD.md: Copertura Lombardia
2. ⚠️ Update ENTITA.md: Cardinalità stazioni (3k vs 7k-8k)
3. 📌 Nota in INDICE.md: MVP dipende da scope geografico
4. 🎯 Sezione nuova in GLOSSARIO.md: "GTFS vs API - quale usare?"

