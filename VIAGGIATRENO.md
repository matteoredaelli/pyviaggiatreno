# API ViaggiaTreno: riferimento endpoint

API non ufficiali e non documentate del portale [ViaggiaTreno](http://www.viaggiatreno.it). Questo documento riunisce gli endpoint trovati in:

| Sigla | Fonte |
|---|---|
| **[DLT]** | https://github.com/dltmtt/viaggiatreno-api (README + JSON Schema, il più completo e recente) |
| **[MB]** | https://github.com/MarcoBuster/railway-opendata/blob/master/docs/VIAGGIATRENO.md (marzo 2023) |
| **[TM]** | https://github.com/roughconsensusandrunningcode/TrainMonitor/wiki/API-del-sistema-Viaggiatreno (archiviata nel 2025) |
| **[GT]** | https://github.com/Geek-Tek/trenitalia-open-api/blob/main/src/functions.ts (codice TypeScript, unica fonte per `elencoTratte` e `dettagliTratta`) |
| **[MC]** | https://github.com/marcocot/trenitalia-api (solo README: il sorgente non era leggibile, quindi nessun endpoint extra da lì) |
| **[LIVE]** | Chiamate reali eseguite il **4 ottobre 2026** (~08:12 CEST) con `probe_viaggiatreno.py`; gli esempi marcati *[LIVE]* sono estratti da lì |

> **Sull'origine degli esempi.** Tutti gli endpoint sono stati verificati con chiamate reali il 4 ottobre 2026, tranne `dettaglioStazione` con prefisso `F`. Gli esempi marcati *[LIVE]* sono risposte vere, ridotte per leggibilità: dove indicato sono stati **omessi i campi `null`** e **troncati gli array multilingua** (9 lingue: it, en, de, fr, es, ro, ja, zh, ru) a due elementi più `"…"`. Gli esempi marcati con una fonte ([DLT], [MB]) sono ripresi da quei repository. Per rigenerare i campioni: `python probe_viaggiatreno.py`.

## Indice

- [Convenzioni generali](#convenzioni-generali)
- [Stazioni](#stazioni): `autocompletaStazione`, `autocompletaStazioneImpostaViaggio`, `autocompletaStazioneNTS`, `cercaStazione`, `regione`, `dettaglioStazione`, `elencoStazioni`
- [Partenze e arrivi](#partenze-e-arrivi): `partenze`, `arrivi`
- [Treni](#treni): `cercaNumeroTrenoTrenoAutocomplete`, `cercaNumeroTreno`, `andamentoTreno`, `tratteCanvas`
- [Tratte e rete](#tratte-e-rete): `elencoTratte`, `dettagliTratta`
- [Informazioni di servizio](#informazioni-di-servizio): `statistiche`, `datimeteo`, `infomobilitaRSS`, `infomobilitaRSSBox`, `infomobilitaTicker`, `language`
- [Tabelloni RFI (iechub.rfi.it)](#tabelloni-rfi-iechubrlrit): visualizzazione web real-time dei tabelloni di stazione
- [Pianificazione viaggio e altri endpoint minori](#pianificazione-viaggio-e-altri-endpoint-minori): `dettaglioViaggio`, `property`, `elencoStazioniCitta`, `getCoordinateStazione`, `coordinateCitta`, `news`
- [Endpoint dismessi](#endpoint-dismessi)
- [Tabelle di riferimento](#tabelle-di-riferimento)
- [Insidie note](#insidie-note)

---

## Convenzioni generali

- **Base URL**: `http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/`
- **Metodo**: sempre `GET`. Nessuna autenticazione.
- **Elenco completo degli endpoint**: lo script del sito, <http://www.viaggiatreno.it/infomobilita/rest-jsapi> (`rest-api.js`), li elenca tutti; non tutti sono usati dal sito [DLT].
- **Codice stazione**: `S` + 5 cifre (`^S\d{5}$`), ad es. `S01700` = Milano Centrale. `dettaglioStazione` accetta anche il prefisso `F` (`^(S|F)\d{5}$`) [DLT]. Gli endpoint che iniziano con `autocompletaStazioneNTS` usano invece codici RICS a 9-11 cifre (`83...`) e **non** vanno passati agli altri endpoint.
- **Timestamp**: millisecondi dalla Unix Epoch. Il "giorno" di un treno è la mezzanotte italiana di quel giorno, espressa in ms (es. `1753135200000` = 22/07/2025 00:00 CEST) [DLT, MB].
- **Identità di un treno**: il numero NON è univoco. La terna `(data, stazione di partenza, numero)` lo è [MB].
- **Formato risposta**: JSON per gran parte degli endpoint, ma alcuni restituiscono `text/plain` in formato proprietario o frammenti HTML (indicato per ciascuno).
- **HTTP 204**: alcuni endpoint rispondono `204 No Content` (corpo vuoto) invece di un errore quando il dato non esiste.
- **User-Agent obbligatorio** *[LIVE, verificato 2026]*: senza un header `User-Agent` da browser, l'edge/WAF (Akamai) risponde `Access Denied` (pagina HTML, non JSON) anche per richieste altrimenti valide. Impostare un `User-Agent` tipo Chrome/Firefox desktop risolve il problema. Non è mai stato segnalato nelle fonti precedenti ([DLT], [MB], ecc.), probabilmente perché i loro client usavano già un UA di default plausibile.

---

## Stazioni

### `autocompletaStazione`

Suggerimenti di stazioni per prefisso del nome. È l'endpoint usato dal sito per l'autocompletamento [DLT].

`GET /autocompletaStazione/{prefisso}`

| Input | Tipo | Descrizione |
|---|---|---|
| `prefisso` | string (path) | Prefisso del nome, case insensitive, anche parziale |

**Output**: `text/plain`, una stazione per riga, formato `NOME_MAIUSCOLO|CODICE`. Righe separate da `\n`.

**Esempio** *[LIVE]*: `GET /autocompletaStazione/firenze` (200, `text/plain`)

```
FIRENZE SANTA MARIA NOVELLA|S06421
FIRENZE CAMPO MARTE|S06900
FIRENZE CASTELLO|S06419
FIRENZE RIFREDI|S06420
FIRENZE ROVEZZANO|S06901
FIRENZE STATUTO|S06430
```

**Note**: è l'endpoint consigliato per ottenere i codici stazione da usare altrove [DLT].

---

### `autocompletaStazioneImpostaViaggio`

`GET /autocompletaStazioneImpostaViaggio/{prefisso}`

Input e output identici a `autocompletaStazione`, con un risultato in meno: manca `PIAZZALE EST TIBURTINA|S08226` [DLT]. *[LIVE]*: per `firenze` la risposta è identica a quella di `autocompletaStazione` (200, `text/plain`).

---

### `autocompletaStazioneNTS`

Come `autocompletaStazione` ma con codici RICS e molte più località tecniche (bivi `BIVIO`, deviazioni `DEV.`, posti di comunicazione `PC`) [DLT].

`GET /autocompletaStazioneNTS/{prefisso}`

| Input | Tipo | Descrizione |
|---|---|---|
| `prefisso` | string (path) | Prefisso del nome, case insensitive |

**Output**: `text/plain`, `NOME|CODICE_NTS`. Il codice NTS ha 9 o 11 cifre, inizia con `83` (codice RICS di FS) seguito dal codice stazione con zeri di padding. Di solito la parte finale coincide col codice di `autocompletaStazione`, ma non sempre.

**Esempio** *[LIVE]*: `GET /autocompletaStazioneNTS/firenze` (200, `text/plain`)

```
FIRENZE BINARIO S.MARCO VECCHIO|830006950
FIRENZE CAMPO MARTE|830006900
FIRENZE CASCINE|830006515
FIRENZE CASTELLO|830006419
FIRENZE RIFREDI|830006420
FIRENZE RIFREDI DEV. OLMATELLO|830006048
FIRENZE ROVEZZANO|830006901
FIRENZE S.MARIA NOVELLA|830006421
FIRENZE STATUTO|830006430
FIRENZE P.PRATO|830006518
FIRENZE STATUTO INT.|830006427
FIRENZE TUTTE STAZ|830006998
```

**Note**: esistono stazioni con stesso nome e codice diverso (e viceversa), tipicamente grafie alternative (`MALPENSA AEROPORTO T2` / `... TERMINAL 2`). Per gli altri endpoint usare sempre i codici di `autocompletaStazione` [DLT].

---

### `cercaStazione`

Stazioni il cui nome inizia con la stringa (anche un solo carattere). Restituisce JSON, a differenza dell'autocompletamento [DLT, MB].

`GET /cercaStazione/{prefisso}`

| Input | Tipo | Descrizione |
|---|---|---|
| `prefisso` | string (path) | Prefisso del nome (URL-encode degli spazi: `MILANO%20P`) |

**Output**: `application/json`, array di:

| Campo | Tipo | Descrizione |
|---|---|---|
| `id` | string | Codice stazione |
| `nomeLungo` | string | Nome esteso in maiuscolo |
| `nomeBreve` | string | Nome abbreviato (grafia incoerente tra stazioni) |
| `label` | string \| null | Etichetta (spesso la città), può essere `null` |

**Esempio** *[LIVE]*: `GET /cercaStazione/apice` (200, `application/json`, risposta compatta su una riga)

```json
[
  {
    "id": "S09314",
    "label": "Apice",
    "nomeBreve": "Apice S.A.B.",
    "nomeLungo": "APICE S.ARCANGELO BONITO"
  }
]
```

**Note**: non restituisce tutte le stazioni. Esempio: Arcene (`S01608`) non compare mai, il suo ID si trova solo nelle fermate di un treno in corsa [MB].

---

### `regione`

Codice della regione di una stazione, necessario per `dettaglioStazione`.

`GET /regione/{codiceStazione}`

| Input | Tipo | Descrizione |
|---|---|---|
| `codiceStazione` | string (path) | Es. `S01700` |

**Output**: `text/plain` con un intero (il codice regione; vedi [tabella](#codici-regione)).

**Esempio** *[LIVE]*: `GET /regione/S01700` → 200, `Content-Type: application/json`, corpo `1\n` (Lombardia). Per [DLT] `GET /regione/S06421` → `13` (Toscana).

**Note**:
- Il `Content-Type` dichiarato è `application/json` ma il corpo è un intero con a capo finale (`1\n`): va letto come testo [MB, LIVE].
- Per alcune stazioni (es. AIELLO, `S08550`) risponde `204`: non c'è modo di ottenerne i dettagli [MB].

---

### `dettaglioStazione`

Dettagli di una stazione, comprese le coordinate.

`GET /dettaglioStazione/{codiceStazione}/{codiceRegione}`

| Input | Tipo | Descrizione |
|---|---|---|
| `codiceStazione` | string (path) | `^(S\|F)\d{5}$` [DLT] (il prefisso `F` non è stato verificato dal vivo) |
| `codiceRegione` | int (path) | Ottenibile da `regione` |

**Output**: `application/json`, un oggetto con la stessa forma di un elemento di [`elencoStazioni`](#elencostazioni). Campi:

| Campo | Descrizione |
|---|---|
| `key` | `"{codice}_{regione}"`, es. `S01700_1` |
| `codiceStazione`, `codStazione` | Codice stazione (uguali) |
| `codReg` | Codice regione |
| `lat`, `lon` | Coordinate WGS84 |
| `localita` | `{nomeLungo, nomeBreve, label, id}` |
| `nomeCitta` | Città |
| `tipoStazione` | `1` per Milano Centrale; vedi `elencoStazioni` |
| `dettZoomStaz` | Livelli di zoom della mappa. A differenza di `elencoStazioni`, qui `codiceRegione` è valorizzato (non `null`) |
| `pstaz`, `mappaCitta`, `latMappaCitta`, `lonMappaCitta`, `esterno`, `offsetX`, `offsetY` | Dati di rendering della mappa |

**Esempio** *[LIVE]*: `GET /dettaglioStazione/S01700/1` (200, `application/json`)

```json
{
  "key": "S01700_1",
  "codReg": 1,
  "tipoStazione": 1,
  "dettZoomStaz": [
    {
      "key": "S01700_1",
      "codiceStazione": "S01700",
      "zoomStartRange": 8,
      "zoomStopRange": 9,
      "pinpointVisibile": true,
      "pinpointVisible": true,
      "labelVisibile": true,
      "labelVisible": true,
      "codiceRegione": 1
    },
    {
      "key": "S01700_1",
      "codiceStazione": "S01700",
      "zoomStartRange": 10,
      "zoomStopRange": 11,
      "pinpointVisibile": true,
      "pinpointVisible": true,
      "labelVisibile": true,
      "labelVisible": true,
      "codiceRegione": 1
    }
  ],
  "pstaz": [],
  "mappaCitta": {
    "urlImagePinpoint": "",
    "urlImageBaloon": ""
  },
  "codiceStazione": "S01700",
  "codStazione": "S01700",
  "lat": 45.486347,
  "lon": 9.204528,
  "latMappaCitta": 0.0,
  "lonMappaCitta": 0.0,
  "localita": {
    "nomeLungo": "MILANO CENTRALE",
    "nomeBreve": "MILANO CENTRALE",
    "label": "Milano",
    "id": "S01700"
  },
  "esterno": false,
  "offsetX": 0,
  "offsetY": 0,
  "nomeCitta": "Milano"
}
```

---

### `elencoStazioni`

Elenco delle stazioni di una regione, con coordinate e dati di visualizzazione sulla mappa.

`GET /elencoStazioni/{codiceRegione}`

| Input | Tipo | Descrizione |
|---|---|---|
| `codiceRegione` | int (path) | `0` = stazioni principali italiane (usato da [GT] per l'elenco nazionale, non verificato dal vivo); 1-22 = regioni |

**Output**: `application/json`, array di oggetti (stessa forma di `dettaglioStazione`). *[LIVE]*: `GET /elencoStazioni/1` restituisce **345** stazioni; `tipoStazione` vale 3 per 328, 4 per 16, 1 per 1; `dettZoomStaz` è vuoto per 272 stazioni e ha 2 elementi per le restanti 73; `nomeCitta` vale `"A"` per 272 stazioni.

| Campo | Tipo | Descrizione |
|---|---|---|
| `key` | string | `"{codice}_{regione}"` |
| `codiceStazione` / `codStazione` | string | Codice stazione (uguali nei casi osservati) |
| `codReg` | int | Codice regione |
| `lat`, `lon` | number | Coordinate WGS84 |
| `localita` | object | `{nomeLungo, nomeBreve, label, id}`, stessa forma di `cercaStazione` |
| `nomeCitta` | string \| null | Può essere `"A"` (nessuna città) |
| `tipoStazione` | int | `3` regolare, `1` principale (?), `4` placeholder da ignorare [MB] |
| `dettZoomStaz` | array | Livelli di zoom a cui la stazione è visibile sulla mappa; vuoto se la stazione non ha coordinate di mappa corrette [GT] |
| `esterno`, `offsetX`, `offsetY`, `pstaz`, `mappaCitta`, `latMappaCitta`, `lonMappaCitta` | varie | Dati di rendering della mappa |

**Esempio** *[LIVE]*: un elemento dell'array restituito da `GET /elencoStazioni/1` (stazione con `dettZoomStaz` valorizzato)

```json
{
  "key": "S01511_1",
  "codReg": 1,
  "tipoStazione": 3,
  "dettZoomStaz": [
    {
      "key": "S01511_1",
      "codiceStazione": "S01511",
      "zoomStartRange": 8,
      "zoomStopRange": 9,
      "pinpointVisibile": true,
      "pinpointVisible": true,
      "labelVisibile": false,
      "labelVisible": false,
      "codiceRegione": 1
    },
    {
      "key": "S01511_1",
      "codiceStazione": "S01511",
      "zoomStartRange": 10,
      "zoomStopRange": 11,
      "pinpointVisibile": true,
      "pinpointVisible": true,
      "labelVisibile": true,
      "labelVisible": true,
      "codiceRegione": 1
    }
  ],
  "pstaz": [],
  "mappaCitta": {
    "urlImagePinpoint": "",
    "urlImageBaloon": ""
  },
  "codiceStazione": "S01511",
  "codStazione": "S01511",
  "lat": 45.653072,
  "lon": 9.375089,
  "latMappaCitta": 0.0,
  "lonMappaCitta": 0.0,
  "localita": {
    "nomeLungo": "CARNATE USMATE",
    "nomeBreve": "CARNATE USMATE",
    "label": "Carnate",
    "id": "S01511"
  },
  "esterno": false,
  "offsetX": 0,
  "offsetY": 0,
  "nomeCitta": "Carnate Usmate"
}
```

**Note**: non contiene tutte le stazioni. Una stazione può comparire in più regioni (Casalmaggiore `S01850` è in Lombardia e in Emilia-Romagna): per la regione "vera" usare `regione` [MB]. Le regioni `21` e `22` (province autonome) coincidono con la `9` (Trentino-Alto Adige) [MB].

---

## Partenze e arrivi

### `partenze`

Treni in partenza da una stazione in un dato momento.

`GET /partenze/{codiceStazione}/{dataOra}`

| Input | Tipo | Descrizione |
|---|---|---|
| `codiceStazione` | string (path) | `^S\d{5}$` |
| `dataOra` | string (path) | Data/ora in formato simile a `Date.toString()` di JavaScript. Va URL-encoded |

Formati accettati [DLT, MB]:

```
Fri Aug 2 2025 20:00:00
Fri, Aug 2 2025 13:20:00 GMT+0100 (Central European Time)
Wed Mar 08 2023 17:04:00 GMT+0100
```

*[LIVE]*: funziona anche senza il nome del fuso tra parentesi, con il `+` codificato `%2B`: `Sun%20Oct%2004%202026%2008%3A12%3A27%20GMT%2B0200` (generato da `strftime("%a %b %d %Y %H:%M:%S GMT%z")`). Il client [GT] passa `new Date()` convertito in stringa. Orari lontani da "adesso" possono dare risultati parziali o errori [MB].

**Output**: `application/json`, array di treni. *[LIVE]*: `GET /partenze/S01700/…` ha restituito **33** treni (`categoria`: {'(vuota)': 8, 'REG': 21, 'IC': 2, 'EC': 2}; tutti con `provvedimento: 0`). Ogni elemento ha **74 campi**, gli stessi di `arrivi`, `dettagliTratta` e (più altri) `andamentoTreno`. Campi più utili:

| Campo | Tipo | Descrizione |
|---|---|---|
| `numeroTreno` | int | Numero del treno |
| `codOrigine` | string | Codice stazione di **origine** del treno. Con `numeroTreno` e `dataPartenzaTreno` forma gli argomenti di `andamentoTreno` |
| `dataPartenzaTreno` | int | Mezzanotte del giorno di partenza in ms; è il terzo argomento di `andamentoTreno` |
| `dataPartenzaTrenoAsDate` | string | Stessa data in formato `YYYY-MM-DD` |
| `partenzaTreno` | int \| null | Orario effettivo di partenza dall'origine, ms |
| `millisDataPartenza` | string \| null | Valorizzato nelle partenze, `null` negli arrivi |
| `categoria`, `categoriaDescrizione` | string | Es. `REG`, `IC`, `EC`. Per le Frecce `categoria` è `""` e `categoriaDescrizione` è `" FR"` (spazio iniziale) |
| `compNumeroTreno` | string | Etichetta pronta, es. `" FR 9611"`, `"REG 2452"` |
| `destinazione` / `origine` | string \| null | Nome della destinazione (partenze) o dell'origine (arrivi); l'altro è `null` |
| `orarioPartenza` / `orarioArrivo` | int \| null | Orario programmato in ms (partenza o arrivo a questa stazione) |
| `compOrarioPartenza` / `compOrarioArrivo` | string \| null | `HH:MM` |
| `ritardo` | int | Ritardo in minuti |
| `compRitardo`, `compRitardoAndamento` | string[9] | Testo del ritardo in 9 lingue |
| `binarioProgrammatoPartenzaDescrizione`, `binarioEffettivoPartenzaDescrizione` | string \| null | Binario programmato / effettivo (partenze) |
| `arrivato` | bool | Il treno è arrivato **in questa stazione** |
| `circolante` | bool | In circolazione |
| `inStazione` | bool | È fermo in questa stazione |
| `nonPartito` | bool | Non è ancora partito dall'origine |
| `compInStazionePartenza`, `compInStazioneArrivo` | string[9] | Testo `Partito`/`Arrivato` in 9 lingue quando applicabile; stringhe vuote altrimenti |
| `haCambiNumero` | bool | Cambia numero lungo la corsa |
| `provvedimento` | int | `0` regolare, `1` cancellato, `2` parzialmente cancellato/deviato/riprogrammato [MB] |
| `riprogrammazione` | `"Y"`/`"N"` | |
| `codiceCliente` | int | Impresa ferroviaria, vedi [tabella](#codici-cliente) |
| `ultimoRilev` | int | Ultimo rilevamento, ms |
| `compDurata` | string | Durata `HH:MM`, spesso `""` |

Campi sempre `null` in questo campione: `origine`, `codDestinazione`, `origineEstera`, `destinazioneEstera`, `oraPartenzaEstera`, `oraArrivoEstera`, `origineZero`, `destinazioneZero`, `orarioPartenzaZero`, `orarioArrivoZero`, `subTitle`, `statoTreno`, `stazionePartenza`, `stazioneArrivo`, `materiale_label`, `iconTreno`, `binario*Arrivo*` [LIVE, DLT].

**Esempio** *[LIVE]*: un elemento (FR 9611, già in stazione a Milano Centrale; campi `null` omessi, array multilingua troncati)

```json
{
  "arrivato": true,
  "dataPartenzaTrenoAsDate": "2026-10-04",
  "dataPartenzaTreno": 1791064800000,
  "partenzaTreno": 1791089520000,
  "millisDataPartenza": "1791064800000",
  "numeroTreno": 9611,
  "categoria": "",
  "categoriaDescrizione": " FR",
  "codOrigine": "S00219",
  "destinazione": "NAPOLI CENTRALE",
  "tratta": 0,
  "regione": 0,
  "circolante": true,
  "codiceCliente": 1,
  "binarioEffettivoPartenzaCodice": "3484",
  "binarioEffettivoPartenzaDescrizione": "11",
  "binarioEffettivoPartenzaTipo": "0",
  "binarioProgrammatoPartenzaDescrizione": "9",
  "orientamento": "B",
  "inStazione": true,
  "haCambiNumero": false,
  "nonPartito": false,
  "provvedimento": 0,
  "riprogrammazione": "N",
  "orarioPartenza": 1791093600000,
  "corrispondenze": [],
  "servizi": [],
  "ritardo": 6,
  "tipoProdotto": "100",
  "compOrarioPartenzaZeroEffettivo": "08:00",
  "compOrarioPartenzaZero": "08:00",
  "compOrarioPartenza": "08:00",
  "compNumeroTreno": " FR 9611",
  "compOrientamento": [
    "Executive in testa",
    "Executive in the head",
    "…"
  ],
  "compTipologiaTreno": "nazionale",
  "compClassRitardoTxt": "",
  "compClassRitardoLine": "regolare_line",
  "compImgRitardo2": "/vt_static/img/legenda/icone_legenda/regolare.png",
  "compImgRitardo": "/vt_static/img/legenda/icone_legenda/regolare.png",
  "compRitardo": [
    "ritardo 6 min.",
    "delay 6 min.",
    "…"
  ],
  "compRitardoAndamento": [
    "con un ritardo di 6 min.",
    "6 minutes late",
    "…"
  ],
  "compInStazionePartenza": [
    "Partito",
    "Departed",
    "…"
  ],
  "compInStazioneArrivo": [
    "Arrivato",
    "Arrived",
    "…"
  ],
  "compDurata": "",
  "compImgCambiNumerazione": "&nbsp;&nbsp;",
  "ultimoRilev": 1791094320000
}
```

**Note**: se `provvedimento` è `2` o `riprogrammazione` è `"Y"`, il treno potrebbe essere parzialmente cancellato, e in tal caso `andamentoTreno` può rispondere `204` [MB]. Il client [GT] segnala `iechub.rfi.it` come alternativa con più treni e più dettagli, ma con ritardi arrotondati e tempi lunghi (non documentato qui).

---

### `arrivi`

`GET /arrivi/{codiceStazione}/{dataOra}`

Input identici a `partenze`. *[LIVE]*: `GET /arrivi/S01700/…` ha restituito **32** treni; l'insieme dei campi è **identico** a quello di `partenze` (74 campi). Cambia quali sono valorizzati: `origine` e `codOrigine` (nome e codice della stazione da cui il treno proviene), `orarioArrivo`, `compOrarioArrivo`, `binario*Arrivo*Descrizione`; `destinazione`, `orarioPartenza`, `compOrarioPartenza` e `millisDataPartenza` sono `null`. Per i treni arrivati compare il testo in 9 lingue in `compInStazioneArrivo` (`"Arrivato"`, `"Arrived"`, …). Schema: `schemas/arrivi.schema.json` in [DLT].

**Esempio** *[LIVE]*: un elemento (REG 2452 Parma → Milano Centrale; campi `null` omessi, array multilingua troncati)

```json
{
  "arrivato": true,
  "dataPartenzaTrenoAsDate": "2026-10-04",
  "dataPartenzaTreno": 1791064800000,
  "partenzaTreno": 1791087060000,
  "numeroTreno": 2452,
  "categoria": "REG",
  "categoriaDescrizione": "REG",
  "origine": "PARMA",
  "codOrigine": "S05014",
  "tratta": 0,
  "regione": 0,
  "circolante": true,
  "codiceCliente": 18,
  "binarioEffettivoArrivoCodice": "1999",
  "binarioEffettivoArrivoDescrizione": "22",
  "binarioEffettivoArrivoTipo": "0",
  "binarioProgrammatoArrivoDescrizione": "22",
  "inStazione": true,
  "haCambiNumero": false,
  "nonPartito": false,
  "provvedimento": 0,
  "riprogrammazione": "N",
  "orarioArrivo": 1791092700000,
  "corrispondenze": [],
  "servizi": [],
  "ritardo": 6,
  "tipoProdotto": "0",
  "compOrarioArrivo": "07:45",
  "compNumeroTreno": "REG 2452",
  "compOrientamento": [
    "--",
    "--",
    "…"
  ],
  "compTipologiaTreno": "regionale",
  "compClassRitardoTxt": "ritardo01_txt",
  "compClassRitardoLine": "ritardo01_line",
  "compImgRitardo2": "/vt_static/img/legenda/icone_legenda/ritardo01.png",
  "compImgRitardo": "/vt_static/img/legenda/icone_legenda/ritardo01.png",
  "compRitardo": [
    "ritardo 6 min.",
    "delay 6 min.",
    "…"
  ],
  "compRitardoAndamento": [
    "con un ritardo di 6 min.",
    "6 minutes late",
    "…"
  ],
  "compInStazionePartenza": [
    "Partito",
    "Departed",
    "…"
  ],
  "compInStazioneArrivo": [
    "Arrivato",
    "Arrived",
    "…"
  ],
  "compOrarioEffettivoArrivo": "/vt_static/img/legenda/icone_legenda/regolare.png07:51",
  "compDurata": "",
  "compImgCambiNumerazione": "&nbsp;&nbsp;",
  "ultimoRilev": 1791093030000
}
```

**Nota**: in questo elemento `codOrigine` è la stazione di origine (`S05014` Parma), quindi si può usare direttamente per `andamentoTreno`.

---

## Treni

### `cercaNumeroTrenoTrenoAutocomplete`

Tutte le corse attive che hanno quel numero, con origine e data. Serve per disambiguare e ottenere gli argomenti di `andamentoTreno`/`tratteCanvas`.

`GET /cercaNumeroTrenoTrenoAutocomplete/{numeroTreno}`

| Input | Tipo | Descrizione |
|---|---|---|
| `numeroTreno` | int (path) | Numero del treno |

**Output**: `text/plain`, una corsa per riga.

Formato attuale (confermato dal vivo) [DLT, LIVE]: `^(\d+) - ([^|]+) - (\d{2}/\d{2}/\d{2})\|(\d+)-(S\d{5})-(\d+)$`, cioè

```
{numero} - {NOME STAZIONE ORIGINE} - {dd/mm/yy}|{numero}-{codiceStazioneOrigine}-{timestampMs}
```

Nel 2023 il formato non aveva la data testuale (`2107 - TORINO PORTA NUOVA|2107-S00219-1678230000000`) [MB]. Parsare in modo tollerante: dividere su `|`, poi su `-` la seconda parte.

**Esempio** *[LIVE]*: `GET /cercaNumeroTrenoTrenoAutocomplete/9611` (200, `text/plain`)

```
9611 - TORINO PORTA NUOVA - 04/10/26|9611-S00219-1791064800000
```

**Esempio con più corse** (reale, fonte [DLT], 22 luglio 2025): `GET /cercaNumeroTrenoTrenoAutocomplete/770`

```
770 - TRIESTE CENTRALE - 21/07/25|770-S03317-1753048800000
770 - CAMNAGO-LENTATE - 22/07/25|770-S01316-1753135200000
770 - TRIESTE CENTRALE - 22/07/25|770-S03317-1753135200000
```

---

### `cercaNumeroTreno`

Come sopra ma restituisce **una sola** corsa (quella corrente) in JSON [DLT].

`GET /cercaNumeroTreno/{numeroTreno}`

| Input | Tipo | Descrizione |
|---|---|---|
| `numeroTreno` | int (path) | Numero del treno |

**Output**: `application/json`

| Campo | Tipo | Descrizione |
|---|---|---|
| `numeroTreno` | string | |
| `codLocOrig` | string | Codice stazione di origine |
| `descLocOrig` | string | Nome stazione di origine |
| `dataPartenza` | string | `YYYY-MM-DD` |
| `millisDataPartenza` | string | Mezzanotte in ms (stringa) da passare a `andamentoTreno` |
| `corsa` | string | Codice corsa |
| `h24` | bool | |
| `tipo` | string | Stato, es. `PG` |
| `formatDataPartenza` | string \| null | `" dd/mm/yy"` (nullo nell'esempio live) |

**Esempio** *[LIVE]*: `GET /cercaNumeroTreno/9611` (200, `application/json`)

```json
{
  "numeroTreno": "9611",
  "codLocOrig": "S00219",
  "descLocOrig": "TORINO PORTA NUOVA",
  "dataPartenza": "2026-10-04",
  "corsa": "09611A",
  "h24": false,
  "tipo": "PG",
  "millisDataPartenza": "1791064800000",
  "formatDataPartenza": null
}
```

---

### `andamentoTreno`

Stato dettagliato di un treno con le fermate, i ritardi e i binari. Contiene tutto ciò che mostra la scheda treno di ViaggiaTreno. La risposta contiene tutti i campi di una riga di `partenze`/`arrivi` (e altri).

`GET /andamentoTreno/{codiceStazioneOrigine}/{numeroTreno}/{dataPartenza}`

| Input | Tipo | Descrizione |
|---|---|---|
| `codiceStazioneOrigine` | string (path) | Stazione di origine del treno (`^S\d{5}$`) |
| `numeroTreno` | int (path) | |
| `dataPartenza` | int (path) | Mezzanotte del giorno di partenza in ms. *[LIVE]*: funziona con `millisDataPartenza` di `cercaNumeroTreno` (`1791064800000`). Il client [GT] passa invece `Date.now()` e riporta che funziona, ma non è stato verificato |

Per ottenere i tre argomenti: da `cercaNumeroTreno` (`codLocOrig`, `numeroTreno`, `millisDataPartenza`) oppure da una riga di `partenze`/`arrivi` (`codOrigine`, `numeroTreno`, `dataPartenzaTreno`).

**Output**: `application/json`. Campi di primo livello che **non** sono in `partenze`/`arrivi` *[LIVE]*:

| Campo | Descrizione |
|---|---|
| `fermate` | Array delle fermate (sotto) |
| `tipoTreno`, `provvedimento` | Stato del treno (tabella sotto) |
| `idOrigine`, `idDestinazione` | Codici stazioni di origine e destinazione |
| `oraUltimoRilevamento`, `compOraUltimoRilevamento`, `stazioneUltimoRilevamento` | Ultimo rilevamento (ms, `HH:MM`, nome). `null` e `"--"` se non partito o soppresso [TM]. **La stazione dell'ultimo rilevamento può non essere tra le fermate**: nell'esempio è `MILANO LAMBRATE`, che non è una fermata dell'FR 9611 |
| `fermateSoppresse` | Fermate soppresse (array, vuoto se regolare) |
| `dataPartenza` | `"2026-10-04 00:00:00.0"` |
| `anormalita`, `provvedimenti`, `segnalazioni`, `cambiNumero` | Array (vuoti nel campione) |
| `hasProvvedimenti` | bool |
| `motivoRitardoPrevalente`, `descrizioneVCO` | `null` / `""` nel campione |
| `descOrientamento` | string[9], composizione del treno in 9 lingue |

Nella risposta `subTitle` è `""` (stringa vuota) nel campione, ma [DLT] segnala che può essere `null` (il sito si blocca in quel caso) e che per treni parzialmente soppressi contiene la descrizione della tratta cancellata.

Stato del treno, `tipoTreno` + `provvedimento` [TM, DLT]:

| `tipoTreno` | `provvedimento` | Significato |
|---|---|---|
| `PG` | 0 | Regolare (confermato dal vivo) |
| `ST` | 1 | Soppresso (`fermate` è vuoto) |
| `PP`, `SI`, `SF` | 0 o 2 | Parzialmente soppresso (`SI` = fermate iniziali, `SF` = finali); fermate con `actualFermataType` 3 |
| `DV` | 3 | Deviato |
| `SM` | | Cancellato in una tratta con cambio treno |
| `VD` | | Variazione di destinazione |
| `VO` | | Variazione di origine |

Elementi di `fermate` *[LIVE]* (tutti con le stesse chiavi):

| Campo | Descrizione |
|---|---|
| `id`, `stazione` | Codice e nome stazione |
| `tipoFermata` | `P` origine, `F` intermedia, `A` destinazione |
| `progressivo` | Posizione nell'itinerario completo: nell'esempio 1, 6, 20, 41, 96, 117 |
| `programmata` | Orario programmato (partenza se `P`, altrimenti arrivo), ms |
| `effettiva` | Orario effettivo, ms; `null` se non ancora rilevato |
| `partenza_teorica`, `arrivo_teorico` | Orari teorici, ms (`null` in origine per l'arrivo e a destinazione per la partenza) |
| `partenzaReale`, `arrivoReale` | Orari effettivi, ms (`null` se non rilevati) |
| `ritardo`, `ritardoPartenza`, `ritardoArrivo` | Ritardi in minuti (`ritardo` = partenza se `P`, arrivo altrimenti) |
| `binarioProgrammatoPartenzaDescrizione`, `binarioEffettivoPartenzaDescrizione` | Binari di partenza |
| `binarioProgrammatoArrivoDescrizione`, `binarioEffettivoArrivoDescrizione` | Binari di arrivo |
| `binarioEffettivo*Codice`, `binarioEffettivo*Tipo` | Codice numerico e tipo del binario effettivo |
| `actualFermataType` | `1` fermata già effettuata / regolare, `0` dato non disponibile (treno non ancora arrivato), `2` non prevista, `3` soppressa |
| `programmataZero`, `partenzaTeoricaZero`, `arrivoTeoricoZero` | Valorizzati solo per orari riprogrammati |
| `orientamento`, `kcNumTreno`, `codLocOrig`, `listaCorrispondenze`, `isNextChanged`, `nextChanged`, `nextTrattaType`, `visualizzaPrevista`, `materiale_label` | Altri campi di servizio |

**Esempio** *[LIVE]*: `GET /andamentoTreno/S00219/9611/1791064800000` (200, `application/json`; FR 9611 Torino Porta Nuova → Napoli Centrale, ore 08:10, 7 minuti di ritardo). Campi `null` omessi e array multilingua troncati. Le `fermate` sono 6: qui ne mostro tre (origine, intermedia, destinazione).

```json
{
  "tipoTreno": "PG",
  "orientamento": "B",
  "codiceCliente": 1,
  "fermateSoppresse": [],
  "dataPartenza": "2026-10-04 00:00:00.0",
  "anormalita": [],
  "provvedimenti": [],
  "segnalazioni": [],
  "oraUltimoRilevamento": 1791094230000,
  "stazioneUltimoRilevamento": "MILANO LAMBRATE",
  "idDestinazione": "S09218",
  "idOrigine": "S00219",
  "cambiNumero": [],
  "hasProvvedimenti": false,
  "descOrientamento": [
    "Executive in testa",
    "Executive in the head",
    "…"
  ],
  "compOraUltimoRilevamento": "08:10",
  "descrizioneVCO": "",
  "arrivato": false,
  "dataPartenzaTrenoAsDate": "2026-10-04",
  "dataPartenzaTreno": 1791064800000,
  "numeroTreno": 9611,
  "categoria": "",
  "origine": "TORINO PORTA NUOVA",
  "destinazione": "NAPOLI CENTRALE",
  "tratta": 0,
  "regione": 0,
  "origineZero": "TORINO PORTA NUOVA",
  "destinazioneZero": "NAPOLI CENTRALE",
  "orarioPartenzaZero": 1791089400000,
  "orarioArrivoZero": 1791110580000,
  "circolante": true,
  "subTitle": "",
  "esisteCorsaZero": "0",
  "inStazione": false,
  "haCambiNumero": false,
  "nonPartito": false,
  "provvedimento": 0,
  "orarioPartenza": 1791089400000,
  "orarioArrivo": 1791110580000,
  "corrispondenze": [],
  "servizi": [],
  "ritardo": 7,
  "tipoProdotto": "100",
  "compOrarioPartenzaZeroEffettivo": "06:57",
  "compOrarioArrivoZeroEffettivo": "12:50",
  "compOrarioPartenzaZero": "06:50",
  "compOrarioArrivoZero": "12:43",
  "compOrarioArrivo": "12:43",
  "compOrarioPartenza": "06:50",
  "compNumeroTreno": " FR 9611",
  "compOrientamento": [
    "Executive in testa",
    "Executive in the head",
    "…"
  ],
  "compTipologiaTreno": "nazionale",
  "compClassRitardoTxt": "",
  "compClassRitardoLine": "regolare_line",
  "compImgRitardo2": "/vt_static/img/legenda/icone_legenda/regolare.png",
  "compImgRitardo": "/vt_static/img/legenda/icone_legenda/regolare.png",
  "compRitardo": [
    "ritardo 7 min.",
    "delay 7 min.",
    "…"
  ],
  "compRitardoAndamento": [
    "con un ritardo di 7 min.",
    "7 minutes late",
    "…"
  ],
  "compInStazionePartenza": [
    "",
    "",
    "…"
  ],
  "compInStazioneArrivo": [
    "",
    "",
    "…"
  ],
  "compOrarioEffettivoArrivo": "/vt_static/img/legenda/icone_legenda/regolare.png12:50",
  "compDurata": "5:53",
  "compImgCambiNumerazione": "&nbsp;&nbsp;",
  "ultimoRilev": 1791094230000,
  "fermate": [
    {
      "orientamento": "A",
      "stazione": "TORINO PORTA NUOVA",
      "codLocOrig": "S00219",
      "id": "S00219",
      "listaCorrispondenze": [],
      "programmata": 1791089400000,
      "effettiva": 1791089520000,
      "ritardo": 2,
      "partenza_teorica": 1791089400000,
      "isNextChanged": false,
      "partenzaReale": 1791089520000,
      "ritardoPartenza": 2,
      "ritardoArrivo": 0,
      "progressivo": 1,
      "binarioEffettivoPartenzaCodice": "171",
      "binarioEffettivoPartenzaTipo": "0",
      "binarioEffettivoPartenzaDescrizione": "16",
      "binarioProgrammatoPartenzaDescrizione": "16",
      "tipoFermata": "P",
      "visualizzaPrevista": true,
      "nextChanged": false,
      "nextTrattaType": 0,
      "actualFermataType": 1
    },
    {
      "orientamento": "B",
      "stazione": "MILANO CENTRALE",
      "codLocOrig": "S00219",
      "id": "S01700",
      "listaCorrispondenze": [],
      "programmata": 1791093000000,
      "effettiva": 1791093900000,
      "ritardo": 5,
      "partenza_teorica": 1791093600000,
      "arrivo_teorico": 1791093000000,
      "isNextChanged": false,
      "partenzaReale": 1791093900000,
      "arrivoReale": 1791093150000,
      "ritardoPartenza": 5,
      "ritardoArrivo": 3,
      "progressivo": 20,
      "binarioEffettivoArrivoCodice": "1988",
      "binarioEffettivoArrivoTipo": "0",
      "binarioEffettivoArrivoDescrizione": "11",
      "binarioProgrammatoArrivoDescrizione": "9",
      "binarioEffettivoPartenzaCodice": "3484",
      "binarioEffettivoPartenzaTipo": "0",
      "binarioEffettivoPartenzaDescrizione": "11",
      "binarioProgrammatoPartenzaDescrizione": "9",
      "tipoFermata": "F",
      "visualizzaPrevista": true,
      "nextChanged": false,
      "nextTrattaType": 1,
      "actualFermataType": 1
    },
    {
      "orientamento": "A",
      "stazione": "NAPOLI CENTRALE",
      "codLocOrig": "S00219",
      "id": "S09218",
      "listaCorrispondenze": [],
      "programmata": 1791110580000,
      "ritardo": 0,
      "arrivo_teorico": 1791110580000,
      "isNextChanged": false,
      "ritardoPartenza": 0,
      "ritardoArrivo": 0,
      "progressivo": 117,
      "binarioProgrammatoArrivoDescrizione": "18",
      "tipoFermata": "A",
      "visualizzaPrevista": true,
      "nextChanged": false,
      "nextTrattaType": 2,
      "actualFermataType": 0
    }
  ]
}
```

**Note**:
- `fermate` contiene solo le fermate commerciali del treno (6 per questa Freccia), non tutte le stazioni attraversate.
- Può rispondere **`204`** anche per treni esistenti e già elencati da `partenze`, tipicamente cancellati o riprogrammati: i dettagli non sono disponibili [MB].
- Il sito web va in caricamento infinito se `subTitle` è `null` [DLT]: gestire il caso nel client.

---

### `tratteCanvas`

Itinerario del treno in forma "ad albero" per il disegno della tratta sul sito. Contiene le stesse fermate di `andamentoTreno`, ciascuna avvolta in un oggetto con alcuni campi di disegno.

`GET /tratteCanvas/{codiceStazioneOrigine}/{numeroTreno}/{dataPartenza}`

| Input | Tipo | Descrizione |
|---|---|---|
| `codiceStazioneOrigine` | string (path) | Es. `S00219` |
| `numeroTreno` | int (path) | Es. `9611` |
| `dataPartenza` | int (path) | Mezzanotte del giorno di partenza in ms |

**Output**: `application/json`, array con un elemento per fermata (*[LIVE]*: 6 elementi per l'FR 9611, gli stessi di `andamentoTreno.fermate`):

| Campo | Descrizione |
|---|---|
| `id`, `stazione` | Codice e nome della stazione |
| `fermata` | Oggetto **identico** a un elemento di `andamentoTreno.fermate` |
| `first`, `last` | bool, prima/ultima fermata |
| `stazioneCorrente` | bool, il treno è in questa stazione |
| `partenzaReale`, `arrivoReale` | **bool** (non timestamp): partenza/arrivo già rilevati. Il timestamp è dentro `fermata` |
| `orientamento` | string[9], posizione della carrozza di testa in 9 lingue |
| `actualFermataType`, `trattaType`, `previousTrattaType`, `nextTrattaType` | Codici per il disegno della linea |

Esempio d'uso citato in [TM]: `/tratteCanvas/S04203/2102/1620770400000`.

**Esempio** *[LIVE]*: `GET /tratteCanvas/S00219/9611/1791064800000`, primo elemento (campi `null` di `fermata` omessi, array multilingua troncati)

```json
{
  "last": false,
  "stazioneCorrente": false,
  "id": "S00219",
  "stazione": "TORINO PORTA NUOVA",
  "fermata": {
    "orientamento": "A",
    "stazione": "TORINO PORTA NUOVA",
    "codLocOrig": "S00219",
    "id": "S00219",
    "listaCorrispondenze": [],
    "programmata": 1791089400000,
    "effettiva": 1791089520000,
    "ritardo": 2,
    "partenza_teorica": 1791089400000,
    "isNextChanged": false,
    "partenzaReale": 1791089520000,
    "ritardoPartenza": 2,
    "ritardoArrivo": 0,
    "progressivo": 1,
    "binarioEffettivoPartenzaCodice": "171",
    "binarioEffettivoPartenzaTipo": "0",
    "binarioEffettivoPartenzaDescrizione": "16",
    "binarioProgrammatoPartenzaDescrizione": "16",
    "tipoFermata": "P",
    "visualizzaPrevista": true,
    "nextChanged": false,
    "nextTrattaType": 0,
    "actualFermataType": 1
  },
  "partenzaReale": true,
  "arrivoReale": true,
  "first": true,
  "orientamento": [
    "Executive in coda",
    "Executive at the rear",
    "…"
  ],
  "nextTrattaType": 1,
  "actualFermataType": 1,
  "trattaType": 0
}
```

---

## Tratte e rete

Questi due endpoint non compaiono in [DLT]. Sono documentati solo dal codice di [GT] e servono per ottenere in blocco **tutti i treni in circolazione**. Il nome dei parametri (`idRegione`, `zoomlevel`, `categoriaTreni`, `catAV`) è stato confermato dalla segnatura reale dell'endpoint e il loro comportamento è stato verificato dal vivo (vedi sotto).

### `elencoTratte`

Elenco dei segmenti ferroviari della rete (coppie di nodi), con indicazione se sono occupati da treni. Non compare in [DLT]; documentato da [GT] e verificato dal vivo.

`GET /elencoTratte/{idRegione}/{zoomlevel}/{categoriaTreni}/{catAV}/{timestamp}`

> Nomi dei parametri confermati dalla segnatura reale dell'endpoint (coerenti con tutte le verifiche dal vivo sotto): `idRegione`, `zoomlevel`, `categoriaTreni`, `catAV`, `timestamp`. In precedenza erano indicati come `p1`-`p4` perché non comparivano in nessuna fonte disponibile.

Chiamata usata da [GT] e dallo script di probe: `/elencoTratte/0/6/ES*,IC,EXP,EC,EN,REG/null/{Date.now()}`

| Input | Descrizione |
|---|---|
| `idRegione` | **Codice regione** [LIVE, verificato variando il parametro]. `0` = tutta Italia (135 segmenti); `1` = Lombardia (99 segmenti); `9` = Trentino-Alto Adige (9 segmenti, regione piccola); valori provati 1-22 restituiscono sottoinsiemi di dimensione plausibile. Stesso codice usato da `elencoStazioni`/`regione`/`datimeteo` (vedi [tabella](#codici-regione)) |
| `zoomlevel` | **Livello di zoom della mappa** [LIVE, confermato dal nome reale del parametro]. Non è una finestra temporale come ipotizzato in una prima analisi: test su `zoomlevel=0..14` (p1=0, stesso istante) danno `85` segmenti occupati per `0-5` e per `12-14`, ma **`123-124`** per `6-11`. Il range `6-11` coincide con i livelli di zoom usati altrove nell'API per decidere la visibilità di una stazione sulla mappa (`dettZoomStaz[].zoomStartRange/zoomStopRange` in `elencoStazioni`/`dettaglioStazione` usa valori `8-9` e `10-11`). Ipotesi: per i livelli di zoom effettivamente usati dalla mappa interattiva del sito, il server calcola `occupata` in modo più "aggregato" (forse sui segmenti padre `parentAB`/`parentBA`, che in 49 segmenti su 135 differiscono da `trattaAB`/`trattaBA`), mentre fuori da quel range usa un calcolo di base più conservativo. **Consigliato `zoomlevel=6`** (o qualunque valore 6-11) per il quadro più completo |
| `categoriaTreni` | Filtro categorie separato da virgola: `ES*` (Frecce), `IC`, `EXP`, `EC`, `EN`, `REG`. L'asterisco è un wildcard. Riduce anche il conteggio di `occupata` se restringi le categorie [LIVE] |
| `catAV` = `null` | Il testo `null` letterale; probabilmente un filtro specifico per i treni Alta Velocità (da qui il nome), forse pensato per accettare una stringa di categoria (es. `"AV"`) analoga a `categoriaTreni`. **Fragile** [LIVE]: `null` e `0` danno risultati normali, ma qualsiasi altro intero (`1`, `5`, `10`, `60`) azzera silenziosamente `occupata` per **tutti** i segmenti (risposta `200` valida, nessun errore, solo dati sbagliati) — coerente con un parser che si aspetta una stringa/categoria e si comporta in modo imprevisto con un numero; un valore non numerico a caso (es. `abc`) causa `HTTP 500`. **Non modificare, lasciare sempre `null`** |
| `timestamp` | Timestamp corrente in ms (probabilmente anti-cache) |

**Output**: `application/json`, array di segmenti. *[LIVE]*: **135** segmenti nazionali, di cui **122** con `occupata: true` (con `p1=0, p2=6`).

| Campo | Descrizione |
|---|---|
| `nodoA`, `nodoB` | Codici dei nodi agli estremi (codici stazione `S…`; vedi nota) |
| `trattaAB`, `trattaBA` | ID numerici del segmento nei due sensi (usati da `dettagliTratta`) |
| `parentAB`, `parentBA` | ID del segmento "padre"; in 49 segmenti su 135 diverso da `trattaAB`/`trattaBA` |
| `latitudineA`, `longitudineA`, `latitudineB`, `longitudineB` | Coordinate degli estremi |
| `occupata` | bool, almeno un treno presente. [GT] avverte che a volte molte tratte risultano libere per un malfunzionamento di ViaggiaTreno |

**Esempio** *[LIVE]*: primo elemento dell'array

```json
{
  "nodoA": "S00000",
  "nodoB": "S99999",
  "trattaAB": 510,
  "trattaBA": 511,
  "parentAB": 510,
  "parentBA": 511,
  "latitudineA": 44.398467,
  "longitudineA": 10.942383,
  "latitudineB": 44.040219,
  "longitudineB": 10.854492,
  "occupata": true
}
```

**Note**:
- Nel primo elemento `nodoA` è `S00000` e `nodoB` è `S99999`: sembrano codici segnaposto di nodi non-stazione, non codici stazione validi.
- `nodoA`/`nodoB` non sono sempre stazioni passeggeri: esistono nodi tecnici (bivi/diramazioni) con coordinate valide ma senza nome, senza `localita` e senza `codReg` (es. `S01002`, `S01021`, `S01139`, `S01789`, trovati filtrando per regione `1`): `dettaglioStazione` risponde `200` ma con quasi tutti i campi `null`, e non compaiono in **nessun** `elencoStazioni/{regione}` da 1 a 22 [LIVE]. Da escludere quando si mappano i segmenti a stazioni "vere".
- **Il filtro `idRegione` filtra i *segmenti* per posizione geografica, non i *treni*** [LIVE]. Un segmento vicino al confine regionale (es. Milano-Piacenza, filtrato con `idRegione=1` Lombardia) può restituire treni di lunghissima percorrenza che non hanno nulla a che fare con la regione se non il fatto di transitarci in quel momento: nel campione, sul segmento Milano Centrale sono comparsi treni `LECCE -> MILANO CENTRALE` e `VENEZIA S.LUCIA -> MILANO CENTRALE`. Il campo `regione` dentro ogni treno **non è una proprietà della corsa**: è semplicemente l'eco del parametro `idRegione` usato nella query (vale `1` per quei treni solo perché la query usava `idRegione=1`, non perché il treno sia "lombardo"). Per un filtro "treni che partono/arrivano davvero in questa regione" bisogna confrontare `codOrigine`/`codDestinazione` con l'elenco stazioni della regione, non fidarsi del campo `regione`.
- Una stazione di confine può comparire nell'`elencoStazioni` di più regioni (es. Piacenza `S05000` compare sia in regione 1 - Lombardia - sia in regione 8 - Emilia-Romagna, dove è davvero di competenza) [MB, LIVE].

---

### `dettagliTratta`

Treni attualmente presenti su un segmento. Non compare in [DLT]; documentato da [GT] e verificato dal vivo.

`GET /dettagliTratta/{idRegione}/{trattaAB}/{trattaBA}/{categoriaTreni}/{catAV}`

> Parametri rinominati per coerenza con la segnatura reale confermata per `elencoTratte` (stessa famiglia di nomi, [vedi sopra](#elencotratte)); indicati prima come `p1`/`p5` in assenza di fonti.

Chiamata usata da [GT] e dallo script di probe: `/dettagliTratta/0/{trattaAB}/{trattaBA}/ES*,IC,EXP,EC,EN,REG/null`

| Input | Descrizione |
|---|---|
| `idRegione` | **Deve essere lo stesso codice regione usato nella chiamata a `elencoTratte` che ha prodotto `trattaAB`/`trattaBA`** [LIVE, scoperta critica]. Non è un parametro cosmetico: gli ID `trattaAB`/`trattaBA` sono numerati **per regione**, non sono identificatori globali della rete. Esempio verificato: `trattaAB=10, trattaBA=92` con `idRegione=0` restituisce il treno `PISA CENTRALE -> GROSSETO` (Toscana), mentre lo **stesso** `trattaAB=10, trattaBA=92` con `idRegione=1` restituisce `MILANO GRECO PIRELLI -> PIACENZA` (Lombardia): sono due segmenti fisicamente diversi che condividono per coincidenza lo stesso ID in numerazioni regionali diverse. Mischiare un `idRegione` preso da una chiamata `elencoTratte` con un `idRegione` diverso in `dettagliTratta` dà **treni completamente sbagliati senza nessun errore** (risposta `200` valida) |
| `trattaAB`, `trattaBA` | ID dei due sensi, da `elencoTratte` (con lo stesso `idRegione`) |
| `categoriaTreni` | Come in `elencoTratte` |
| `catAV` = `null` | Testo `null` letterale, come `catAV` in `elencoTratte` |

**Output**: `application/json`, array di oggetti `{ "tratta": <nome o null>, "treni": [...] }`. *[LIVE]*: per `trattaAB=510`, `trattaBA=511` ha restituito **2** oggetti, con 5, 4 treni, quindi un oggetto per senso di marcia. In un'altra chiamata (`trattaAB=10`, `trattaBA=92`, `p1=1`), il campo `tratta` del wrapper **non era `null` ma il nome leggibile del segmento** nel verso corrispondente (`"Codogno - Piacenza"` / `"Piacenza - Codogno"`): sembra quindi valorizzato quando il segmento ha un nome noto, `null` altrimenti (es. per i nodi segnaposto `S00000`/`S99999`). Ogni treno ha **gli stessi 74 campi** di una riga di `partenze`/`arrivi`, con una differenza: `orarioPartenza` e `orarioArrivo` sono **stringhe** `"YYYY-MM-DD"` (solo la data) e non timestamp in ms. L'orario va letto da `compOrarioPartenza`/`compOrarioArrivo` (`HH:MM`). Il campo `tratta` **dentro il treno** (da non confondere con quello del wrapper) è invece l'ID numerico del segmento in quel senso (es. `10`).

**Nota sul campo `regione` del treno**: non riflette la provenienza/competenza reale del treno, ma semplicemente il valore di `idRegione` passato nella query (verificato: lo stesso treno Milano↔Piacenza riporta `regione: 1` se interrogato con `idRegione=1`). Per capire se un treno è davvero "della regione" bisogna guardare `codOrigine`/`codDestinazione` rispetto all'elenco stazioni della regione, non questo campo.

**Esempio** *[LIVE]*: `GET /dettagliTratta/1/10/92/ES*,IC,EXP,EC,EN,REG/null` (segmento Codogno↔Piacenza, regione Lombardia), risposta completa con i due sensi di marcia; campi `null` omessi, array multilingua troncati

```json
[
  {
    "tratta": "Codogno - Piacenza",
    "treni": [
      {
        "arrivato": true,
        "dataPartenzaTrenoAsDate": "2026-10-19",
        "dataPartenzaTreno": 1792360800000,
        "numeroTreno": 10885,
        "categoria": "REG",
        "origine": "MILANO GRECO PIRELLI",
        "codOrigine": "S01326",
        "destinazione": "PIACENZA",
        "codDestinazione": "S05000",
        "tratta": 10,
        "regione": 1,
        "circolante": true,
        "codiceCliente": 63,
        "inStazione": false,
        "provvedimento": 0,
        "riprogrammazione": "N",
        "orarioPartenza": "2026-10-19",
        "orarioArrivo": "2026-10-19",
        "ritardo": 6,
        "compOrarioPartenza": "21:10",
        "compOrarioArrivo": "22:26",
        "compNumeroTreno": "REG 10885",
        "compTipologiaTreno": "regionale",
        "compRitardo": [
          "ritardo 6 min.",
          "delay 6 min.",
          "…"
        ],
        "compDurata": "1:16",
        "ultimoRilev": 1792441890000
      }
    ]
  },
  {
    "tratta": "Piacenza - Codogno",
    "treni": [
      {
        "arrivato": false,
        "dataPartenzaTrenoAsDate": "2026-10-19",
        "dataPartenzaTreno": 1792360800000,
        "numeroTreno": 614,
        "categoria": "IC",
        "origine": "LECCE",
        "codOrigine": "S11145",
        "destinazione": "MILANO CENTRALE",
        "codDestinazione": "S01700",
        "tratta": 92,
        "regione": 1,
        "circolante": true,
        "codiceCliente": 4,
        "inStazione": false,
        "provvedimento": 0,
        "riprogrammazione": "N",
        "orarioPartenza": "2026-10-19",
        "orarioArrivo": "2026-10-19",
        "ritardo": 9,
        "compOrarioPartenza": "11:54",
        "compOrarioArrivo": "23:40",
        "compNumeroTreno": "IC 614",
        "compTipologiaTreno": "nazionale",
        "compRitardo": [
          "ritardo 9 min.",
          "delay 9 min.",
          "…"
        ],
        "compDurata": "11:46",
        "ultimoRilev": 1792443000000
      }
    ]
  }
]
```

Questo esempio mostra bene il punto delle Note sopra: `IC 614 Lecce → Milano Centrale`, un treno di lunghissima percorrenza senza alcuna relazione "logica" con la Lombardia, compare semplicemente perché nell'istante della chiamata transitava sul segmento Piacenza-Codogno, con `regione: 1` solo perché la query usava `p1=1`.

**Note**:
- Per non sovraccaricare il server, [GT] chiama `dettagliTratta` solo per i segmenti con `trattaAB`/`trattaBA` distinti e deduplica i treni per `(numeroTreno, regione)`, perché lo stesso numero può esistere in regioni diverse. Dato che il campo `regione` è solo l'eco di `idRegione` (vedi sopra), la deduplica robusta è `(numeroTreno, codOrigine, dataPartenzaTreno)` come ovunque nell'API.
- Per un inventario "tutti i treni circolanti in una regione": usare `elencoTratte/{regione}/6/{categorie}/null/{ts}`, filtrare i segmenti con `occupata: true`, chiamare `dettagliTratta/{stessa regione}/{trattaAB}/{trattaBA}/{categorie}/null` per ciascuno. Il risultato includerà anche treni di lunga percorrenza solo in transito (es. Lecce→Milano): se serve restringere ai treni realmente originati/destinati nella regione, filtrare a valle su `codOrigine`/`codDestinazione`.

---

## Informazioni di servizio

### `statistiche`

`GET /statistiche/{timestamp}`

| Input | Descrizione |
|---|---|
| `timestamp` | Obbligatorio ma può essere qualsiasi valore, anche una stringa [DLT]. *[LIVE]*: è stato passato il timestamp corrente in ms |

**Output**: `application/json`

**Esempio** *[LIVE]*: `GET /statistiche/1791094347462` (4 ottobre 2026, ~08:12)

```json
{
  "treniGiorno": 615,
  "ultimoAggiornamento": 1791094357220,
  "treniCircolanti": 579
}
```

---

### `datimeteo`

Previsioni meteo (oggi/domani, per fascia oraria) per le stazioni di una regione.

`GET /datimeteo/{codiceRegione}`

| Input | Descrizione |
|---|---|
| `codiceRegione` | 0-22. Con `9` restituisce `{}`: usare `21` o `22` per le province autonome [DLT] |

**Output**: `application/json`, oggetto indicizzato per codice stazione. I valori `*Tempo*` sono codici numerici di condizione meteo (significato non documentato).

**Esempio** *[LIVE]*: `GET /datimeteo/1` (Lombardia), con due comportamenti osservati in momenti diversi:

- Il 4 ottobre 2026 ha risposto `200`, `application/json`, corpo `{}` (nessuna stazione).
- Il 19 ottobre 2026 ha risposto `200` con **11 stazioni popolate** (es. `S01700`, `S01430`, `S02336`...), formato completo come sotto.

**Il servizio è quindi intermittente/poco affidabile**, non permanentemente vuoto come ipotizzato in una prima analisi: il client deve comunque gestire `{}` come caso valido ("nessun dato in questo momento"), ma non deve assumere che il servizio sia definitivamente fuori uso se lo vede vuoto una volta. Formato di un elemento popolato (reale, *[LIVE]*, 19 ottobre 2026):

```json
{
  "S01700": {
    "codStazione": "S01700",
    "oggiTemperatura": 16,
    "oggiTemperaturaMattino": 16,
    "oggiTemperaturaPomeriggio": 16,
    "oggiTemperaturaSera": 17,
    "oggiTempo": 10,
    "oggiTempoMattino": 10,
    "oggiTempoPomeriggio": 10,
    "oggiTempoSera": 110,
    "domaniTemperatura": 17,
    "domaniTemperaturaMattino": 17,
    "domaniTemperaturaPomeriggio": 13,
    "domaniTemperaturaSera": 12,
    "domaniTempo": 1,
    "domaniTempoMattino": 10,
    "domaniTempoPomeriggio": 1,
    "domaniTempoSera": 101
  }
}
```

In precedenza (fonte [DLT], 2025) il formato era identico, solo con valori diversi (es. `oggiTemperatura: 37`).

```json
{
  "S01700": {
    "codStazione": "S01700",
    "oggiTemperatura": 37,
    "oggiTemperaturaMattino": 30,
    "oggiTemperaturaPomeriggio": 37,
    "oggiTemperaturaSera": 32,
    "oggiTempo": 1,
    "oggiTempoMattino": 2,
    "oggiTempoPomeriggio": 2,
    "oggiTempoSera": 101,
    "domaniTemperatura": 36,
    "domaniTemperaturaMattino": 29,
    "domaniTemperaturaPomeriggio": 37,
    "domaniTemperaturaSera": 29,
    "domaniTempo": 5,
    "domaniTempoMattino": 2,
    "domaniTempoPomeriggio": 2,
    "domaniTempoSera": 105
  }
}
```

---

### `infomobilitaRSS`

Notizie di infomobilità (scioperi, interruzioni) o lavori programmati, con il testo completo.

`GET /infomobilitaRSS/{isInfoLavori}`

| Input | Descrizione |
|---|---|
| `isInfoLavori` | `false`: notizie sulla circolazione; `true`: lavori e modifiche programmate |

**Output**: `text/plain` con un frammento **HTML**: `<ul id="accordionGenericInfomob">` con un `<li>` per notizia (titolo in `<a>`, data in `<h4>`, testo in `div.info-text`; le notizie in evidenza hanno la classe `inEvidenza`). *[LIVE]*: `GET /infomobilitaRSS/false` ha restituito 4 notizie (circolazione regolare, infotreni Intercity/Eurocity, trasporto regionale, ecc.). Il testo è spesso bilingue (italiano e inglese nello stesso blocco) e i treni citati sono link a `http://www.viaggiatreno.it/infomobilitamobile/pages/cercaTreno/cercaTreno.jsp?treno={numero}&origine={codStazione}&datapartenza={ms}`, da cui si possono estrarre gli argomenti per `andamentoTreno`.

**Esempio** *[LIVE]*: `GET /infomobilitaRSS/false`, solo la prima notizia delle 4

```html
<ul id="accordionGenericInfomob"><li class="editModeCollapsibleElement">
	<a href="#" id="headingNewsAccordion0" onclick="infoCollapse('headingNewsAccordion0')" class="headingNewsAccordion inEvidenza" id="CIRCOLAZIONE REGOLARE">CIRCOLAZIONE REGOLARE</a>
	<div class="boxAcc" >
		<div>
			<div class="textComponent">
				<h4>04.10.2026</h4>
				<div class="info-text  inEvidenza">
				<p><b>In questo momento la circolazione si svolge regolarmente su tutta la rete ferroviaria nazionale.</b></p>
<p>Eventuali ritardi registrati si riferiscono a precedenti inconvenienti già risolti.</p>
<p><i><b>REGULAR RAILWAY TRAFFIC</b></i></p>
<p><i><b>At the moment, the railway traffic is regular on the whole national network.</b></i></p>
<p><i>Possible registered delays refer to previous service inconveniences that have been already solved.</i></p>
				</div>
			</div>
		</div>
		<br>
	</div>
</li></ul>
```

---

### `infomobilitaRSSBox`

`GET /infomobilitaRSSBox/{isInfoLavori}`

Stesso input di `infomobilitaRSS`. Restituisce il frammento HTML con **solo i titoli** (nessun testo esteso), pensato per il box Infotraffico [DLT]. Il client [GT] ne estrae i titoli con uno split sul testo. *[LIVE]*: 4 titoli, `text/plain`. Gli avvisi di linea (come interruzioni per lavori o ordigni bellici) compaiono come titoli lunghi in questo elenco.

**Esempio** *[LIVE]*: `GET /infomobilitaRSSBox/false`

```html
<ul id="accordionGenericInfomob"><li class="editModeCollapsibleElement">
	<a href="#" id="headingNewsAccordion0" onclick="infoBox('headingNewsAccordion')" class="headingNewsAccordionBox inEvidenza" id="CIRCOLAZIONE REGOLARE">CIRCOLAZIONE REGOLARE</a>
</li><li class="editModeCollapsibleElement">
	<a href="#" id="headingNewsAccordion1" onclick="infoBox('headingNewsAccordion')" class="headingNewsAccordionBox " id="INFOTRENI INTERCITY - EUROCITY">INFOTRENI INTERCITY - EUROCITY</a>
</li><li class="editModeCollapsibleElement">
	<a href="#" id="headingNewsAccordion2" onclick="infoBox('headingNewsAccordion')" class="headingNewsAccordionBox " id="INFORMAZIONI SUL TRASPORTO REGIONALE">INFORMAZIONI SUL TRASPORTO REGIONALE</a>
</li><li class="editModeCollapsibleElement">
	<a href="#" id="headingNewsAccordion3" onclick="infoBox('headingNewsAccordion')" class="headingNewsAccordionBox " id="Linea Roma - Pisa: domenica 4 ottobre dalle ore 9:00 alle ore 14:00 circolazione sospesa tra Grosseto e Orbetello per la rimozione di un ordigno bellico">Linea Roma - Pisa: domenica 4 ottobre dalle ore 9:00 alle ore 14:00 circolazione sospesa tra Grosseto e Orbetello per la rimozione di un ordigno bellico</a>
</li></ul>
```

---

### `infomobilitaTicker`

`GET /infomobilitaTicker`, nessun input.

**Output**: `text/plain` con HTML `<ul><li>…</li></ul>`: avvisi brevi per la striscia scorrevole del sito [DLT].

**Esempio** *[LIVE]* (200, `text/plain`):

```html
<ul><li>CIRCOLAZIONE REGOLARE</li></ul>
```

---

### `language`

Dizionario di traduzione delle stringhe dell'interfaccia.

`GET /language/{idLingua}`

| Input | Descrizione |
|---|---|
| `idLingua` | `it`, `en`, `de`, `fr`, `sp`, `ro`, `jp`, `zh`, `ru` [DLT]. Un codice non valido restituisce `en` |

**Output**: `application/json`, oggetto piatto chiave → stringa tradotta. *[LIVE]*: `GET /language/en` ha restituito **242** chiavi.

**Esempio** *[LIVE]* (tre chiavi su 242):

```json
{
  "treno_in_testa_AA_coda_BB_fr": "Carriages A in the head, Executive middle - Carriages B in the queue, Executive middle",
  "cercaTreno.da.label": "From",
  "statistica_attuale": "Currently, {{treniCircolanti}} trains are in transit."
}
```

---

## Tabelloni RFI (iechub.rfi.it)

Servizio web gestito da RFI che mostra i treni in arrivo e partenza da una stazione nel formato dei tabelloni fisici presenti in stazione. Alternativa interattiva al polling di `partenze`/`arrivi` di ViaggiaTreno per applicazioni che hanno bisogno di visualizzazione real-time.

### URL base

`GET https://iechub.rfi.it/ArriviPartenze/ArrivalsDepartures/Monitor`

### Parametri

| Parametro | Tipo | Descrizione |
|---|---|---|
| `Arrivals` | bool | `true` per mostrare gli arrivi, `false` per le partenze |
| `Search` | string | Campo di ricerca della stazione (opzionale; se vuoto, viene usato `PlaceId`) |
| `PlaceId` | int | ID della stazione nel sistema RFI (vedi tabella PlaceId sotto) |

### Risposta

`text/html`, pagina HTML5 con tabellone interattivo. Il rendering è aggiornato in tempo reale via JavaScript/AJAX/WebSocket. Contiene:

- Numero del treno
- Orario programmato e effettivo (con evidenziazione ritardo)
- Destinazione (partenze) o origine (arrivi)
- Binario programmato e effettivo
- Stato del treno (in orario, in ritardo, cancellato, ecc.)
- Categoria (Freccia, IC, EC, REG, ecc.)

### Esempi

**Partenze da Milano Centrale:**
```
https://iechub.rfi.it/ArriviPartenze/ArrivalsDepartures/Monitor?Arrivals=False&Search=&PlaceId=1728
```

**Arrivi a Milano Centrale:**
```
https://iechub.rfi.it/ArriviPartenze/ArrivalsDepartures/Monitor?Arrivals=True&Search=&PlaceId=1728
```

### PlaceId comuni

| PlaceId | Stazione | Codice ViaggiaTreno | Regione |
|---|---|---|---|
| 1728 | Milano Centrale | S01700 | Lombardia |
| 1714 | Milano Porta Garibaldi | S01701 | Lombardia |
| 1813 | Torino Porta Nuova | S00219 | Piemonte |
| 1840 | Firenze Santa Maria Novella | S06421 | Toscana |
| 1925 | Roma Termini | S08000 | Lazio |
| 2104 | Napoli Centrale | S09218 | Campania |

**Nota**: questa tabella è **incompleta**. Per trovare il PlaceId di una stazione:
1. Andare su https://iechub.rfi.it/ArriviPartenze/ArrivalsDepartures/Monitor
2. Cercare la stazione nel campo `Search`
3. Cliccare sul risultato
4. Il `PlaceId` è visibile nell'URL della pagina risultante

### Vantaggi vs ViaggiaTreno API

- **Visualizzazione nativa**: replica esattamente i tabelloni di stazione
- **Real-time**: aggiornamenti automatici senza polling manuale
- **Dati arrotondati**: i ritardi sono visibili immediatamente
- **Interfaccia familiare**: gli utenti riconoscono il formato

### Svantaggi

- **Non è una API JSON**: il dato è HTML/JavaScript, richiede parsing
- **Rate limiting non documentato**: usare con moderazione
- **Meno dettagli**: non fornisce il percorso completo del treno (tutte le fermate)
- **PlaceId diverso da codice ViaggiaTreno**: mapping non ovvio

### Confronto con `partenze`/`arrivi` di ViaggiaTreno

| Aspetto | iechub.rfi.it | ViaggiaTreno API |
|---|---|---|
| Formato | HTML5 interattivo | JSON strutturato |
| Fermate complete | No | Sì (`andamentoTreno`) |
| Parsing | Richiede browser/scraper | Facile |
| Dati programmatici | Difficili | Facili |
| Aggiornamento | Real-time (browser) | Manuale (polling) |
| Uso consigliato | Visualizzazione web | Integrazione programmatica |

### Note

- I PlaceId di RFI **non corrispondono** ai codici `S*` di ViaggiaTreno; è necessario un mapping esplicito.
- Il servizio è ospitato su infrastruttura RFI ed è ufficiale; non è una API non documentata come ViaggiaTreno.
- Per scraping massivo, contattare RFI direttamente anziché fare scraping del sito.
- Se l'applicazione ha bisogno di dati strutturati e dell'intero percorso del treno, usare le API ViaggiaTreno (`andamentoTreno` + `partenze`/`arrivi`).

---

## Pianificazione viaggio e altri endpoint minori

Endpoint trovati elencando per intero lo script ufficiale del sito, <http://www.viaggiatreno.it/infomobilita/rest-jsapi> (`rest-api.js`), che contiene i commenti `// GET /resteasy/viaggiatreno/{endpoint}` per **tutti** gli endpoint realmente usati dal client web. È la fonte più autorevole possibile (codice del sito stesso) e permette di distinguere con certezza gli endpoint reali da quelli mai esistiti o rimossi.

### `dettaglioViaggio`

**Funzionante e non censito prima di questa verifica.** Restituisce i treni **diretti** (senza cambi) tra due stazioni nella giornata corrente — è di fatto l'endpoint che avrebbe dovuto fornire `soluzioniViaggioNew` (dismesso, vedi sotto), ma realmente operativo.

`GET /dettaglioViaggio/{idStazioneDa}/{idStazioneA}`

| Input | Tipo | Descrizione |
|---|---|---|
| `idStazioneDa` | string (path) | Codice stazione di partenza (`^S\d{5}$`) |
| `idStazioneA` | string (path) | Codice stazione di arrivo |

**Output**: `application/json`, array di treni con lo stesso schema a 74+ campi di `partenze`/`arrivi`/`dettagliTratta` (`numeroTreno`, `ritardo`, binari, orari, ecc.), senza bisogno di specificare una data/ora (sembra sempre riferirsi alla giornata corrente).

**Esempio** *[LIVE]*: `GET /dettaglioViaggio/S01700/S06421` (Milano Centrale → Firenze S.M.N.) ha restituito **3** treni diretti:

```
9303 FR 05:50 -> 08:50
9515 FR 07:10 -> 09:04
9519 FR 08:10 -> 10:04
```

**Note**: non supporta interscambi (treni con cambio); per percorsi che richiedono un cambio non c'è alternativa nelle API ViaggiaTreno [DLT] (stesso limite già segnalato per `soluzioniViaggioNew`).

### `property`

`GET /resteasy/viaggiatreno/property/{name}`

L'endpoint **esiste** (non risponde `404`) ma ha risposto **`204 No Content`** con tutti i nomi plausibili provati dal vivo (`version`, `app.version`, `buildNumber`, `release`, `environment`, `env`, `application.name`, ecc.). Probabilmente serve per leggere proprietà di configurazione interne del backend con nomi noti solo al codice del sito stesso; nessun nome valido individuato finora.

### `elencoStazioniCitta`

`GET /resteasy/viaggiatreno/elencoStazioniCitta/{stazione}`

L'endpoint **esiste** (risponde `200`, `application/json`) ma ha restituito **sempre `[]`** nei test dal vivo, con vari input (`Milano`, `MILANO`, `Firenze`). Non è chiaro se richieda un formato diverso (es. un ID città invece del nome) o se sia semplicemente senza dati popolati, come osservato per `datimeteo`.

### `getCoordinateStazione` / `coordinateCitta`

Varianti semplificate di `dettaglioStazione`, trovate nello stesso script, utili quando serve solo la posizione e non si vuole passare il codice regione:

```
GET /getCoordinateStazione/{codiceStazione}  -> stessa forma di dettaglioStazione, con quasi tutti i campi null tranne lat/lon
GET /coordinateCitta/{codiceStazione}        -> {"latitudine": ..., "longitudine": ...}
```

**Esempio** *[LIVE]*: `GET /coordinateCitta/S01700` → `{"latitudine":45.486347,"longitudine":9.204528}`.

### `news`

Alternativa a `infomobilitaRSS`, in formato JSON invece di HTML.

`GET /news/{codRegione}/{lingua}`

**Esempio** *[LIVE]*: `GET /news/0/it` ha restituito una notizia, ma **datata dicembre 2019** (`"data":1575887696000`), a differenza di `infomobilitaRSS` che nello stesso momento mostrava notizie aggiornate al giorno corrente. Sembra un servizio poco mantenuto/con dati non aggiornati: non affidabile per infomobilità corrente, preferire `infomobilitaRSS`/`infomobilitaRSSBox`.

---

## Endpoint dismessi

- `soluzioniViaggioNew`: serviva per le soluzioni di viaggio tra due stazioni. Prima restituiva una lista vuota, ora `404`. Non c'è alternativa diretta, ma vedi `dettaglioViaggio` sopra per i soli treni diretti senza cambio.
- `dettaglioProgrammaOrario/{dataDa}/{dataA}/{idStazionePartenza}/{idStazioneArrivo}`: **non esiste più** — `HTTP 404` *[LIVE]* e non compare nello script ufficiale `rest-jsapi`.
- `cercaProgrammaOrarioDestinazioneAutocomplete/{idStazionePartenza}`: **non esiste più** — `HTTP 404` *[LIVE]*, non compare nello script ufficiale.
- `cercaProgrammaOrarioOrigineAutocomplete/{idStazioneArrivo}`: **non esiste più** — `HTTP 404` *[LIVE]*, non compare nello script ufficiale.

---

## Tabelle di riferimento

### Codici regione

Da [DLT] (endpoint `regione`, `elencoStazioni`, `datimeteo`).

| Codice | Regione | Codice | Regione |
|---|---|---|---|
| 0 | Italia | 12 | Veneto |
| 1 | Lombardia | 13 | Toscana |
| 2 | Liguria | 14 | Sicilia |
| 3 | Piemonte | 15 | Basilicata |
| 4 | Valle d'Aosta | 16 | Puglia |
| 5 | Lazio | 17 | Calabria |
| 6 | Umbria | 18 | Campania |
| 7 | Molise | 19 | Abruzzo |
| 8 | Emilia Romagna | 20 | Sardegna |
| 9 | Trentino-Alto Adige | 21 | Provincia autonoma di Trento |
| 10 | Friuli-Venezia Giulia | 22 | Provincia autonoma di Bolzano |
| 11 | Marche | | |

### Codici cliente

Campo `codiceCliente` (codice RFI dell'impresa ferroviaria); tabella possibilmente non esaustiva [DLT].

| Codice | Impresa |
|---|---|
| 1 | Trenitalia (alta velocità) |
| 2 | Trenitalia (regionali) |
| 4 | Trenitalia (InterCity) |
| 18 | Trenitalia Tper |
| 63 | Trenord |
| 64 | TILO |
| 910 | Ferrovie del Sud Est |

---

## Insidie note

1. **HTTP 204 invece di errori** su `regione`, `andamentoTreno` e probabilmente altri; il corpo è vuoto, non JSON. Il client deve distinguerlo da un errore.
2. **`Content-Type` bugiardo**: `regione` dichiara JSON ma restituisce un intero in testo con a capo finale [MB, LIVE]. Gli endpoint `autocompleta*`, `cercaNumeroTrenoTrenoAutocomplete` e `infomobilita*` restituiscono testo/HTML, non JSON.
3. **Il formato di `cercaNumeroTrenoTrenoAutocomplete` è cambiato** tra il 2023 e il 2025 (aggiunta della data `dd/mm/yy`).
4. **Il numero di treno non è un ID**: usare sempre la terna (data, stazione di origine, numero) [MB].
5. **Formato data di `partenze`/`arrivi`**: stringa in stile JavaScript, va URL-encoded; fusi orari e nomi (`Central European Time`) accettati [DLT].
6. **Cancellazioni parziali**: `partenze` può mostrare il treno con `provvedimento: 2` e `riprogrammazione: "Y"` mentre `andamentoTreno` risponde `204` [MB].
7. **`datimeteo` intermittente**: può restituire `{}` (nessuna stazione) in alcuni momenti e dati popolati in altri per la stessa regione (verificato: `{}` il 4 ottobre 2026, 11 stazioni popolate il 19 ottobre 2026 per `codiceRegione=1`). Trattare sia `{}` sia le risposte popolate come esiti normali, non assumere che il servizio sia permanentemente fuori uso.
8. **`orarioPartenza`/`orarioArrivo` cambiano tipo**: sono timestamp in ms in `partenze`/`arrivi`/`andamentoTreno`, ma stringhe `"YYYY-MM-DD"` in `dettagliTratta` [LIVE].
9. **`subTitle`**: stringa vuota in `andamentoTreno` regolare, ma può essere `null` e rompe il sito ufficiale; il client deve gestirlo [DLT].
10. **Elenchi stazioni incompleti**: né `cercaStazione` né `elencoStazioni` contengono tutte le stazioni; alcune compaiono solo come fermate di treni in corsa [MB].
11. **`occupata` in `elencoTratte` inaffidabile**: a volte molte tratte risultano libere per un malfunzionamento del servizio [GT].
12. **Rate limiting**: non documentato, ma i progetti che interrogano in massa (es. [GT] con `dettagliTratta` per ogni segmento) deduplicano le richieste. Usare richieste moderate [fonti varie].
13. **Protocollo**: tutte le chiamate dal vivo e le fonti usano `http://`; `https://` non è stato verificato.
14. **Accesso negato senza User-Agent** [LIVE]: senza un header `User-Agent` plausibile (browser), l'edge/WAF risponde `Access Denied` (HTML) invece dei dati, su qualsiasi endpoint. Impostare sempre uno User-Agent da browser desktop.
15. **`elencoTratte`/`dettagliTratta`: il parametro `idRegione` è il codice regione** e filtra i *segmenti*, non i treni: un segmento al confine regionale può restituire treni di lunga percorrenza del tutto estranei alla regione (es. Lecce→Milano su un segmento "Lombardia") [LIVE]. Il campo `regione` del treno in questi endpoint è solo l'eco di `idRegione`, non una proprietà della corsa.
16. **`trattaAB`/`trattaBA` non sono ID globali**: sono numerati per regione. Usare `dettagliTratta` con un `idRegione` diverso da quello usato per ottenere quegli ID da `elencoTratte` restituisce treni di un segmento completamente diverso, senza errore [LIVE].
17. **`elencoTratte`: il parametro `zoomlevel` non è cosmetico**: fuori dal range `6-11` (livelli di zoom usati dalla mappa interattiva) il conteggio dei segmenti `occupata` scende sensibilmente (85 invece di 123-124 su un campione nazionale) [LIVE]. Usare un valore in quel range per non sottostimare i treni in circolazione.
18. **`elencoTratte`: il parametro `catAV` è fragile**: solo `null` o `0` funzionano come previsto; qualsiasi altro intero azzera silenziosamente tutti i flag `occupata` (falsi negativi su tutta la risposta, senza errore); un valore non numerico causa `HTTP 500` [LIVE].
18. **Nodi tecnici in `elencoTratte`**: `nodoA`/`nodoB` possono essere bivi/diramazioni senza nome né dati di stazione (`dettaglioStazione` risponde 200 con quasi tutti i campi `null`) e non compaiono in nessun `elencoStazioni` [LIVE].
