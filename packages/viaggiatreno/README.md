# viaggiatreno

Client Python per le API non ufficiali di [ViaggiaTreno](http://www.viaggiatreno.it),
il sistema informativo in tempo reale della rete ferroviaria italiana.

La libreria fornisce:

- **`ViaggiaTrenoClient`** — client HTTP asincrono (basato su `httpx`) per tutti
  gli endpoint REST di ViaggiaTreno (stazioni, partenze/arrivi, andamento treni,
  tratte, infomobilità, meteo, statistiche).
- **Modelli dati tipizzati** (pydantic): `StationDetail`, `TrainBoardItem`,
  `TrainStatus`, `DettaglioTratta`, `Statistics`, e altri.
- **Parser** per le risposte non-JSON (RSS infomobilità, autocomplete testuali).

## Installazione

```bash
pip install viaggiatreno
```

## Esempio

```python
import asyncio
from viaggiatreno import ViaggiaTrenoClient


async def main() -> None:
    async with ViaggiaTrenoClient() as client:
        stazioni = await client.autocompleta_stazione("Milano")
        for s in stazioni:
            print(s)


asyncio.run(main())
```

## Analisi di una stazione (`viaggiatreno.insights`)

Calcoli su dati già scaricati. `profilo_stazione` chiede all'API solo ciò che non gli passi:

```python
from viaggiatreno import ViaggiaTrenoClient
from viaggiatreno.insights import profilo_stazione

async with ViaggiaTrenoClient() as client:
    p = await profilo_stazione(client, "S08409")  # Roma Termini: partenze, arrivi, dettaglio
    # oppure, con dati già in mano (nessuna richiesta):
    # p = await profilo_stazione(client, "S08409", partenze=P, arrivi=A, dettaglio=D)

print(p.nome, p.citta, p.tipo_stazione)  # ROMA TERMINI Roma 1
print(p.frequenza.treni_ora, p.n_binari)  # 41.8 treni/h, 29 binari
print(p.ruolo.capolinea, p.ruolo.transito)  # True True
for c in p.elenco_collegamenti:  # origine -> destinazione, senza duplicati
    print(c.etichetta)
for b in p.binari_programmati:  # binario -> collegamenti e frequentazione
    print(b.binario, b.n_treni, b.frequenza.treni_ora, b.elenco_collegamenti)
```

Senza client: `ProfiloStazione.da_tabelloni(codice, partenze, arrivi, dettaglio=...)`.
`con_dettaglio=False` evita le due richieste del dettaglio (`regione` + `dettaglioStazione`).

### Vocabolario

**Corsa**: un treno sul tabellone di una stazione (partenza o arrivo). **Collegamento**:
origine → destinazione di un verso, senza fermate intermedie (A→B e B→A sono distinti).
**Itinerario**: le fermate ordinate di un treno, uguale nei due versi (da `andamentoTreno`).
**Arco**: due fermate consecutive di un treno e il tratto tra loro. Una "linea" in senso comune
è la `Linea` (sezione "Linee e archi aggregati").

### Anagrafica

`nome`, `citta`, `regione_codice`, `regione_nome`, `lat`, `lon`, `tipo_stazione` (1 principale,
3 regolare) vengono da `dettaglioStazione`. Il nome della stazione **non** è nelle righe dei
suoi tabelloni (le righe portano il nome dell'altra stazione): senza dettaglio né parametro
`nome` è `None` e i collegamenti si leggono con il solo codice. Se il dettaglio non è
disponibile (errore di rete, `403`) il profilo si costruisce lo stesso, con un avviso nel log.
La città `A` è un segnaposto dell'API e viene letta come assente.

### Ruolo: capolinea e transito

Due proprietà indipendenti, senza soglie: `p.ruolo.capolinea` è vero se **almeno un treno**
nasce o finisce nella stazione; `p.ruolo.transito` se almeno uno vi passa (arriva e riparte
con origine e destinazione altrove). Una stazione può essere entrambe: Roma Termini è
capolinea per i regionali di Fiumicino e di transito per le Frecce Torino–Napoli.

La destinazione di un treno è dichiarata nelle **partenze**; gli **arrivi** la riportano `null`.
Un treno visto solo in arrivo e che non riparte è quindi un *terminale dedotto*: una stima,
contata a parte (`n_termina_dedotti`; `capolinea_certo` non la usa). Un arrivo a meno di 15
minuti dalla fine del tabellone delle partenze è *incerto* (potrebbe ripartire dopo) e non
conta. I treni parzialmente soppressi non contano come capolinea, perché potrebbero nascere o
finire lì a causa della soppressione.

**Stazioni di testa e di passaggio.** In una stazione di testa (Milano Centrale, Roma Termini)
i treni arrivano, si fermano e ripartono nel verso opposto; in una di passaggio (Bologna) si
fermano poco e proseguono. La sosta programmata dei treni con lo stesso numero in arrivo e
partenza lo conferma: Bologna 3 min (33 treni), Roma Termini 15 (12), Milano Centrale 10 (3, pochi
dati). Il tempo tra un arrivo e la partenza successiva *sullo stesso binario* è più lungo nelle
stazioni di testa (23–24 min a Milano e Termini, 10 a Bologna), ma include l'attesa fino al
treno seguente, quindi non è l'occupazione del binario. Il profilo non calcola la sosta.

Verifica sui dati reali (itinerari del crawler, 3 stazioni): i terminali dedotti erano corretti
in 27 casi su 27 a Roma Termini e in 27 su 28 a Milano Centrale (un treno proseguiva per
Bologna). Alzare il margine da 15 a 30 minuti non migliora: trasforma in incerti dei treni che
finivano davvero lì (da 5 a 12 a Milano) e lascia l'errore dov'era. `ParametriProfilo(
deduci_termine=False)` disattiva la deduzione.

### Binari

Ogni corsa ha un binario *programmato* e uno *effettivo* (quello reale); possono differire
(17% delle fermate nei nostri dati). Il numero di binari della stazione (`p.n_binari`,
`p.elenco_binari`) è l'**unione** dei due. La relazione binario → collegamenti è in due liste:
`p.binari_programmati` (con `collegamenti_per_binario_programmato()`) e `p.binari_reali` (con
`collegamenti_per_binario_reale()`). Una corsa con entrambi compare in tutte e due, anche su
binari diversi; `n_cambiati` conta quelle in cui differiscono, quindi la somma dei treni delle
due liste non è il numero di treni della stazione (usa `n_treni`).

I nomi dei binari non sono solo numeri: a Bologna Centrale ci sono `1 OVEST`, `2 EST`,
`16 AV`, `AV` (senza numero), `III-EST`; l'ordine è "naturale" (1, 2, 10, poi gli altri).

Il binario compare solo per alcuni treni: a Roma Termini 28 treni su 84 non ne hanno nessuno,
e l'effettivo c'è soprattutto per quelli vicini all'ora della richiesta. I binari sono quelli
*osservati* in una finestra di circa -12 min / +1,5 h: un limite inferiore (a Termini 24
programmati, 18 reali, 29 nell'unione). `unisci_corse` somma più osservazioni.

### Frequenza e frequentazione

`frequenza` indica quanto è frequentata la stazione o un binario: **ogni treno conta una
volta**, anche se arriva e riparte. Si legge con `treni_ora` e `intervallo_medio_min` (60 /
`treni_ora`). Il percorso non conta: due collegamenti sullo stesso binario si sommano. Servono
almeno 2 treni (un solo intervallo, `regolare` è `None`).

**Finestra comune.** Le frequenze si calcolano solo nella fascia coperta *sia* dalle partenze
*sia* dagli arrivi (`p.finestra_frequenze_ms`); i treni fuori fascia restano in `n_treni` e nei
binari, ma non nella cadenza (`n_fuori_finestra`). Serve perché un tabellone può contenere
orari isolati lontani dagli altri: a Bologna Centrale cinque treni locali in ritardo non
registrato erano nel tabellone degli arrivi da ore prima delle partenze, e la finestra intera
(4,9 ore) dava 17,0 treni/h contro 40,5 sulla fascia comune. Si disattiva con
`ParametriProfilo(usa_finestra_comune=False)`. Un treno a cavallo del bordo usa il proprio
orario di riferimento (la partenza, altrimenti l'arrivo).

Valori misurati su ~2 ore di un pomeriggio feriale:

| Stazione | Treni | Fascia delle frequenze | Treni/h | Uno ogni |
|---|---|---|---|---|
| Olgiate-Calco-Brivio | 7 | 11:56–13:32 | 3,3 | 18 min |
| Monza | 41 | 12:16–14:13 | 20,0 | 3,0 min |
| Milano Centrale | 69 | 13:10–15:00 | 36,0 | 1,7 min |
| Bologna Centrale | 84 | 13:32–15:26 | 40,5 | 1,5 min |
| Roma Termini | 84 | 13:18–15:10 | 42,9 | 1,4 min |

Il numero dipende dalla fascia oraria: per confrontare stazioni usa la stessa fascia, o unisci
più osservazioni. `regolare` ha senso per un collegamento o un binario con un solo flusso, non
per una stazione, dove è quasi sempre falso. Nelle grandi stazioni la frequenza per binario è
rumorosa (a Termini solo 4 binari su 24 hanno almeno 3 treni).

**Effettiva e teorica.** `frequenza*` conta i treni che circolano; `frequenza_teorica*` include
anche i cancellati (`provvedimento` 1), cioè la cadenza programmata. La differenza dice quanto
servizio è stato tolto (`n_soppressi`, `quota_soppressi`). Un cancellato di solito non ha
binario: si assegna a un binario programmato solo se ne ha uno proprio o se il suo collegamento
ne usa uno solo, altrimenti conta nelle frequenze di stazione e di collegamento ma non in
quelle dei binari (`n_soppressi_non_assegnati`). Non vale per i binari reali.

## Analisi di un treno (`ProfiloTreno`)

Da una sola risposta di `andamentoTreno` (tutte le fermate, con orari teorici e reali di arrivo
e partenza, ritardi e binari) si ricava il profilo del treno:

```python
from viaggiatreno.insights import ProfiloTreno, profilo_treno

p = await profilo_treno(client, "S01520", 24845, 1794438000000)   # una richiesta; None se 204
# oppure, con la risposta già in mano (nessuna richiesta):
p = ProfiloTreno.da_status(status, coordinate={"S01520": (45.856, 9.393), ...})  # opzionali

print(p.stato, p.itinerario.nome, p.verso)         # parzialmente_soppresso LECCO - MILANO P.G. diretto
print(p.collegamento_programmato.etichetta)        # LECCO -> MILANO PORTA GARIBALDI
print(p.collegamento_effettivo.etichetta)          # LECCO -> CARNATE USMATE
for a in p.archi:                                  # coppie di fermate consecutive
    print(a.da.nome, a.a.nome, a.durata_programmata, a.durata_effettiva, a.ritardo_accumulato)
```

| Campo | Contenuto |
|---|---|
| `itinerario`, `verso` | codici delle fermate in forma canonica (uguale nei due versi), soppresse incluse; `diretto` o `inverso` per questo treno |
| `fermate` | `FermataTreno` in ordine di marcia, con orari, binari e stato |
| `archi` | `Arco` tra fermate consecutive, in ordine di marcia |
| `collegamento_programmato` | origine → ultima fermata della lista |
| `collegamento_effettivo` | origine → destinazione dichiarata dall'API (tiene conto delle soppressioni) |
| `stato` | `regolare`, `parzialmente_soppresso`, `cancellato` |
| totali | `durata_programmata`, `ritardo_massimo`, `ritardo_finale`, `distanza_km`, `ultima_effettuata`, `fermate_soppresse` |
| `arrivo_previsto` | quando la corsa effettiva arriva a destinazione, in ms: orario programmato dell'ultima fermata non soppressa più il ritardo attuale (un ritardo negativo non anticipa); ripiega sull'arrivo programmato del treno |
| `fermata_origine_effettiva`, `fermata_destinazione_effettiva` | prima e ultima fermata non soppressa: dove il treno parte e finisce davvero |
| `avanzamento` | `in_corso`, `arrivato`, `soppresso` (solo `tipoTreno` ST): se la corsa va ancora seguita. `arrivato` vince su tutto; un treno parzialmente soppresso resta `in_corso` |
| `ha_anomalie` | cancellazioni, deviazioni, riprogrammazioni, note, cambi di numero, fermate non previste o soppresse: la risposta conviene conservarla per intero |

**Fermata** (`FermataTreno`): orari teorici e reali di arrivo e di partenza, ritardi, binario
programmato ed effettivo di arrivo e di partenza (`binari` li unisce, `binario_cambiato`), sosta
programmata ed effettiva, e uno stato (`effettuata`, `attesa`, `non_prevista`, `soppressa`).

**Arco** (`Arco`): `durata_programmata` (arrivo teorico di `a` meno partenza teorica di `da`),
`durata_effettiva`, `ritardo_accumulato` (positivo se il ritardo cresce nel tratto, negativo se lo
recupera), `soppresso`, e con le coordinate `distanza_km` e `velocita_programmata_kmh`. `coppia`
è la stessa nei due versi: serve ad aggregare treni che percorrono il tratto in sensi opposti.

Cose da sapere sui dati:

- **Ritardi dai millisecondi.** Il ritardo dell'API è un intero arrotondato, gli orari reali
  hanno una risoluzione di 30 secondi. I ritardi si ricalcolano (reale − teorico) in minuti con
  decimali; quelli dell'API restano in `ritardo_api_*`. Nel treno di esempio una fermata risulta
  6 minuti per l'API e 5,5 dai millisecondi.
- **Treno parzialmente soppresso.** L'API riporta come destinazione quella *effettiva* (l'ultima
  fermata non soppressa): per questo `collegamento_effettivo` e `collegamento_programmato`
  differiscono. L'itinerario è sempre quello programmato, fermate soppresse comprese, così lo
  stesso treno non cambia identità quando una fermata salta.
- **Arco verso la destinazione effettiva.** L'API non dà la partenza teorica dell'ultima fermata
  effettuata, quindi l'arco che parte da lì ha `durata_programmata = None`. Non viene inventata.
- **Il `progressivo` non è affidabile per ordinare.** Ha dei buchi (mancano i nodi non
  passeggeri) e in 58 treni su 10.328 è ripetuto o non crescente: tipico di un treno che unisce
  due tratti (Merano–Bolzano–Brennero, dove riparte da 1 a Bolzano). Ordinando per progressivo
  gli orari tornavano indietro in 54 treni contro 4 dell'ordine dell'API. Le fermate restano
  quindi nell'ordine dell'API. Un arco collega due fermate consecutive *nell'elenco*, non
  necessariamente adiacenti sulla rete.
- **Distanze** in linea d'aria (sottostimano il percorso, quindi la velocità). Con coordinate
  parziali non si dà un totale. Le coordinate si passano a parte perché `andamentoTreno` non le
  contiene (si possono prendere da `elencoStazioni`).
- **Prima della partenza** `andamentoTreno` risponde spesso 204 (`profilo_treno` ritorna `None`).

## Linee e archi aggregati

Un treno ha un itinerario, non una linea: la linea nasce raggruppando più treni.

```python
from viaggiatreno.insights import costruisci_linee, aggrega_archi

linee = costruisci_linee(profili)  # profili: lista di ProfiloTreno
for l in linee[:3]:
    print(l.nome, l.n_treni, l.n_varianti, l.categorie)
    for v in l.varianti:  # la più completa per prima
        print("  ", v.itinerario.n_fermate, v.n_treni, v.rapporto.value)

for a in aggrega_archi(profili, min_treni=10):  # una riga per coppia di stazioni
    print(a.nome_a, a.nome_b, a.durata_programmata_mediana, a.scarto_mediano)
```

**Linea.** Treni con gli **stessi due estremi**, in qualunque verso (`chiave` = `A|B`, con
`A <= B`). È un raggruppamento calcolato, non una linea commerciale (R23, S8), che nei dati non
esiste. Le fermate intermedie possono differire, e la differenza si descrive nelle `varianti`:
`completo` (l'itinerario con più fermate), `salta_fermate` (sottosequenza del completo: un
regionale veloce) e `alternativo` (ha fermate che il completo non ha). Un treno parzialmente
soppresso resta sulla sua linea, perché l'itinerario è quello programmato. Due servizi diversi
con gli stessi estremi (regionale e Intercity) finiscono nella stessa linea: la categoria è in
`categorie`.

Sui 10.328 treni del DB del crawler: **929 linee, 2.142 itinerari**. 486 linee hanno un solo
itinerario; 3.797 treni stanno in linee con più varianti, di cui 2.988 saltano fermate e 809
sono alternativi. Lecco–Milano P.G. è una linea sola, 76 treni (39 in un verso, 37 nell'altro)
con un solo itinerario di 13 fermate.

**Archi aggregati** (`StatisticheArco`). Una riga per *coppia di stazioni consecutive*, con i
due versi sommati: durata programmata ed effettiva **mediane** (robuste ai valori anomali),
`scarto_mediano` (effettiva − programmata: negativo = più veloce del previsto),
`ritardo_accumulato_medio` (una media: positivo se il ritardo cresce nel tratto), distanza e
velocità se i profili hanno le coordinate. Gli archi con una fermata soppressa contano in
`n_treni` e `n_soppressi` ma non nelle durate.

Limiti da conoscere:

- Un treno che **salta una fermata** genera un arco più lungo (S1–S3), diverso da S1–S2 e S2–S3:
  non sono confrontabili tra loro.
- Con **un solo giorno di dati** una durata "tipica" è una fotografia; per dire che un tratto è
  lento servono più giorni. `min_treni` scarta le coppie viste da pochi treni.
- Le coordinate non sono in `andamentoTreno`: si passano a `ProfiloTreno.da_status`.
- Gli orari reali hanno risoluzione di 30 secondi: le durate sono multipli di mezzo minuto.

## Licenza

Vedi il file `LICENSE` nel repository.

Repository: https://github.com/matteoredaelli/pyviaggiatreno
