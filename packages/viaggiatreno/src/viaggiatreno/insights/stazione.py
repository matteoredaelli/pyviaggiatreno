# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Profilo di una stazione ricavato dai suoi tabelloni (partenze e arrivi).

Dalle `Corsa` di *una* stazione si ricavano:

- i **binari** usati: il loro numero e' l'unione di binari programmati ed effettivi; la
  relazione binario -> collegamenti e' data in due liste, una per binario programmato e una
  per binario reale (effettivo);
- la **frequenza** dei treni (N treni all'ora, un treno ogni M minuti, regolare o no);
- il **ruolo** della stazione, in due proprieta' indipendenti: *capolinea* (almeno un treno vi
  nasce o vi finisce) e *transito* (almeno un treno vi passa: arriva e riparte con origine e
  destinazione altrove). Una stazione puo' essere entrambe; non ci sono soglie;
- i **collegamenti** (origine -> destinazione) che la servono.

Cosa un tabellone NON dice, e quindi cosa questi numeri NON sono:

- Un tabellone copre una finestra di circa -12 minuti / +1,5 ore: i binari sono quelli
  *osservati in quella finestra* (un limite inferiore, non l'elenco dei binari della
  stazione), e di notte il tabellone e' quasi vuoto. Per un quadro completo si uniscono piu'
  osservazioni con `unisci_corse`.
- La destinazione di un treno e' dichiarata nelle *partenze* (di solito solo il nome, non il
  codice). Gli *arrivi* la riportano `null` (campione documentato di Milano Centrale): un
  treno visto solo negli arrivi ha destinazione ignota. Si assume allora che finisca qui, ma
  e' una **deduzione** (`TERMINA_DEDOTTO`, contata a parte): il treno potrebbe ripartire dopo
  la fine del tabellone delle partenze, quindi gli arrivi a ridosso di quella fine sono
  *incerti* e non contano. `ParametriProfilo(deduci_termine=False)` la disattiva.
- Un treno parzialmente soppresso (`provvedimento` 2) puo' nascere o finire qui *a causa* della
  soppressione: non conta come capolinea. I treni cancellati (`provvedimento` 1) sono esclusi.
- Un treno che arriva con un numero e riparte con un altro (materiale a spola) compare come
  due treni: uno che finisce e uno che nasce. Per la stazione e' un capolinea, ed e' giusto.
- Il codice della destinazione e' spesso assente nelle partenze: si completa dal nome quando
  lo stesso nome compare con il codice nelle altre righe; altrimenti il collegamento e'
  identificato dal nome normalizzato.
"""

from __future__ import annotations

import logging
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from typing import Protocol

import httpx

from viaggiatreno.insights.collegamento import Collegamento
from viaggiatreno.insights.corsa import Corsa, TipoCorsa, da_tabellone, normalizza_nome
from viaggiatreno.models.station import StationDetail
from viaggiatreno.models.train import TrainBoardItem

logger = logging.getLogger(__name__)

_MS_MINUTO = 60_000


# --------------------------------------------------------------------------- parametri


@dataclass(frozen=True)
class ParametriProfilo:
    """Soglie dell'analisi. I default sono ipotesi, da calibrare sui dati."""

    deduci_termine: bool = True  # senza destinazione, un arrivo che non riparte finisce qui
    margine_fine_finestra_min: float = 15.0  # ...se non e' troppo vicino alla fine delle partenze
    fine_finestra_partenze: int | None = None  # ms; se None e' l'ultimo orario delle partenze
    tolleranza_regolarita: float = 0.2  # scarto massimo dalla mediana (frazione) per "regolare"
    tolleranza_minima_min: float = 2.0  # ...ma mai meno di tanti minuti
    min_treni_frequenza: int = 2  # sotto questo numero non si stimano gli intervalli
    # Le frequenze si calcolano solo nella fascia coperta sia dalle partenze sia dagli arrivi.
    # Senza, un tabellone con orari isolati lontani dagli altri (es. 5 arrivi di ore prima)
    # allunga la finestra e abbassa i treni all'ora (Bologna: 17,0 invece di 40,5).
    usa_finestra_comune: bool = True

    def __post_init__(self) -> None:
        if self.min_treni_frequenza < 2:
            raise ValueError("min_treni_frequenza deve essere almeno 2")


# --------------------------------------------------------------------------- frequenza


@dataclass(frozen=True)
class Frequenza:
    """Cadenza dei treni. I campi sugli intervalli sono `None` con pochi treni.

    Per "quanti treni all'ora" e "un treno ogni N minuti" usare `treni_ora` e
    `intervallo_medio_min` (60 / treni_ora): sono coerenti tra loro. L'intervallo *mediano*
    descrive il caso tipico ma, con treni che arrivano a gruppi, puo' differire molto dalla
    media (a Monza: mediana 4 min, media 3 min). `regolare` ha senso per un servizio con una
    cadenza (un collegamento, un binario con un solo flusso), non per una stazione con molti
    flussi sovrapposti, dove e' quasi sempre falso.
    """

    n_treni: int
    primo_ms: int | None
    ultimo_ms: int | None
    intervallo_medio_min: float | None
    intervallo_mediano_min: float | None
    intervallo_min_min: float | None
    intervallo_max_min: float | None
    treni_ora: float | None
    regolare: bool | None  # True se tutti gli intervalli stanno vicino alla mediana


def calcola_frequenza(
    orari_ms: Iterable[int | None], parametri: ParametriProfilo | None = None
) -> Frequenza:
    """Frequenza da una lista di orari (ms). Gli orari assenti sono ignorati.

    `treni_ora` e' 60 / intervallo medio: se tra il primo e l'ultimo treno passano 120 minuti
    e i treni sono 5, gli intervalli sono 4 e valgono in media 30 minuti, quindi 2 treni
    all'ora. Non si divide il numero di treni per la durata della finestra, che darebbe un
    valore troppo alto (conterebbe un intervallo in piu' di quelli osservati).
    """
    p = parametri or ParametriProfilo()
    orari = sorted(o for o in orari_ms if o is not None)
    n = len(orari)
    vuoto = Frequenza(
        n,
        orari[0] if orari else None,
        orari[-1] if orari else None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    if n < p.min_treni_frequenza:
        return vuoto
    intervalli = [(b - a) / _MS_MINUTO for a, b in pairwise(orari)]
    medio = sum(intervalli) / len(intervalli)
    mediano = statistics.median(intervalli)
    tolleranza = max(p.tolleranza_regolarita * mediano, p.tolleranza_minima_min)
    return Frequenza(
        n_treni=n,
        primo_ms=orari[0],
        ultimo_ms=orari[-1],
        intervallo_medio_min=medio,
        intervallo_mediano_min=mediano,
        intervallo_min_min=min(intervalli),
        intervallo_max_min=max(intervalli),
        treni_ora=60 / medio if medio > 0 else None,
        # con un solo intervallo (2 treni) la regolarita' non e' valutabile
        regolare=(
            all(abs(i - mediano) <= tolleranza for i in intervalli) if len(intervalli) > 1 else None
        ),
    )


def finestra_comune(
    orari_partenze: Iterable[int | None], orari_arrivi: Iterable[int | None]
) -> tuple[int, int] | None:
    """Fascia oraria (ms) coperta sia dalle partenze sia dagli arrivi.

    `None` se manca uno dei due tabelloni o se le fasce non si sovrappongono: in quel caso non
    c'e' una fascia comune e non si filtra nulla.
    """
    p = [o for o in orari_partenze if o is not None]
    a = [o for o in orari_arrivi if o is not None]
    if not p or not a:
        return None
    lo, hi = max(min(p), min(a)), min(max(p), max(a))
    return (lo, hi) if lo <= hi else None


# --------------------------------------------------------------------------- un treno


class RuoloTreno(StrEnum):
    """Cosa fa un treno in questa stazione."""

    ORIGINA = "origina"  # parte da qui: e' la sua origine
    TERMINA = "termina"  # la sua destinazione, dichiarata dall'API, e' questa stazione
    TERMINA_DEDOTTO = "termina_dedotto"  # solo in arrivo e non riparte: stima, non dato
    PASSAGGIO = "passaggio"  # la sua destinazione e' un'altra stazione (e non nasce qui)
    INCERTO = "incerto"  # destinazione ignota e non deducibile (vedi `_ruolo_treno`)


@dataclass(frozen=True)
class TrenoInStazione:
    """Le corse di uno stesso treno (stesso numero, origine e giorno) in questa stazione."""

    chiave: tuple[int, str | None, int | None]
    arrivo: Corsa | None
    partenza: Corsa | None

    @property
    def corse(self) -> list[Corsa]:
        return [c for c in (self.arrivo, self.partenza) if c is not None]

    @property
    def soppresso(self) -> bool:
        return any(c.soppressa for c in self.corse)

    @property
    def orario(self) -> int | None:
        """Orario di riferimento: la partenza, altrimenti l'arrivo."""
        for c in (self.partenza, self.arrivo):
            if c is not None and c.orario is not None:
                return c.orario
        return None

    @property
    def categoria(self) -> str:
        for c in (self.partenza, self.arrivo):
            if c is not None and c.categoria:
                return c.categoria
        return ""


def unisci_corse(*osservazioni: Iterable[Corsa]) -> list[Corsa]:
    """Unisce piu' osservazioni della stessa stazione, senza duplicati.

    Una corsa e' la stessa se hanno uguali treno (numero, origine, giorno) e tipo. Se compare
    piu' volte vale l'ultima passata: e' la piu' recente, con il binario piu' aggiornato.
    Serve a far crescere il numero di binari osservati oltre una sola finestra di tabellone.
    """
    viste: dict[tuple[tuple[int, str | None, int | None], TipoCorsa], Corsa] = {}
    for gruppo in osservazioni:
        for c in gruppo:
            viste[(c.chiave, c.tipo)] = c
    return list(viste.values())


def _raggruppa(corse: Iterable[Corsa]) -> list[TrenoInStazione]:
    arrivi: dict[tuple[int, str | None, int | None], Corsa] = {}
    partenze: dict[tuple[int, str | None, int | None], Corsa] = {}
    for c in corse:
        (arrivi if c.tipo is TipoCorsa.ARRIVO else partenze)[c.chiave] = c
    return [
        TrenoInStazione(k, arrivi.get(k), partenze.get(k))
        for k in dict.fromkeys([*arrivi, *partenze])
    ]


def _destinazione_e_questa(t: TrenoInStazione, stazione: str, nome: str | None) -> bool | None:
    """True/False se la destinazione del treno e' (non e') questa stazione; None se ignota.

    Il confronto e' per codice; se il codice manca (nelle partenze di solito c'e' solo il nome)
    per nome normalizzato, quindi `nome` deve essere scritto come lo scrive l'API.
    """
    nome_n = normalizza_nome(nome)
    for c in (t.partenza, t.arrivo):
        if c is None:
            continue
        if c.destinazione_codice is not None:
            return c.destinazione_codice == stazione
        d = normalizza_nome(c.destinazione_nome)
        if d is not None and nome_n is not None:
            return d == nome_n
    return None


def _ruolo_treno(
    t: TrenoInStazione,
    stazione: str,
    nome: str | None,
    fine_partenze: int | None,
    p: ParametriProfilo,
) -> RuoloTreno:
    """Ruolo del treno, in quest'ordine:

    1. origina qui, se la sua origine e' questa stazione;
    2. termina qui, se la sua destinazione e' questa stazione (dichiarata dall'API);
       passaggio, se la destinazione e' un'altra;
    3. destinazione ignota (i tabelloni di arrivo non la riportano): un treno che compare
       anche nelle partenze e' di passaggio; uno solo in arrivo, se `deduci_termine`, termina
       qui salvo che il suo arrivo sia a ridosso della fine del tabellone delle partenze
       (potrebbe ripartire dopo): in quel caso e' incerto. La deduzione e' una stima, non un
       dato: `Ruolo.n_termina_dedotti` dice quanti terminali vengono da qui.
    """
    ruolo = _ruolo_treno_grezzo(t, stazione, nome, fine_partenze, p)
    # un treno parzialmente soppresso puo' nascere o finire qui *a causa* della soppressione:
    # non e' un capolinea vero, quindi non lo si conta come tale
    if ruolo in (RuoloTreno.ORIGINA, RuoloTreno.TERMINA, RuoloTreno.TERMINA_DEDOTTO) and any(
        c.parziale for c in t.corse
    ):
        return RuoloTreno.INCERTO
    return ruolo


def _ruolo_treno_grezzo(
    t: TrenoInStazione,
    stazione: str,
    nome: str | None,
    fine_partenze: int | None,
    p: ParametriProfilo,
) -> RuoloTreno:
    if t.partenza is not None and t.partenza.origine_codice == stazione:
        return RuoloTreno.ORIGINA
    qui = _destinazione_e_questa(t, stazione, nome)
    if qui is True:
        return RuoloTreno.TERMINA
    if qui is False:
        # destinazione altrove: e' di passaggio, salvo non sapere se nasce qui
        if t.arrivo is None and (t.partenza is None or t.partenza.origine_codice is None):
            return RuoloTreno.INCERTO
        return RuoloTreno.PASSAGGIO
    if t.partenza is not None:
        # destinazione ignota ma riparte da qui: non finisce qui
        if t.arrivo is not None or t.partenza.origine_codice is not None:
            return RuoloTreno.PASSAGGIO
        return RuoloTreno.INCERTO
    orario = t.arrivo.orario if t.arrivo else None
    margine = p.margine_fine_finestra_min * _MS_MINUTO
    if not p.deduci_termine or orario is None or fine_partenze is None:
        return RuoloTreno.INCERTO
    return RuoloTreno.INCERTO if orario > fine_partenze - margine else RuoloTreno.TERMINA_DEDOTTO


# --------------------------------------------------------------------------- ruolo stazione


@dataclass(frozen=True)
class Ruolo:
    """Cosa fa la stazione per i treni osservati. Due proprieta' indipendenti.

    - **capolinea**: almeno un treno nasce qui o finisce qui (esclusi i parzialmente soppressi);
    - **transito**: almeno un treno passa di qui (arriva e riparte, con origine e destinazione
      altrove).

    Una stazione puo' essere entrambe le cose (es. Lecco: vi nascono treni per Milano e vi
    passano quelli per Colico). Non ci sono soglie: basta un treno. Per questo un solo treno
    classificato male cambia il risultato, ed e' il motivo per cui i casi dedotti sono contati
    a parte (`n_termina_dedotti`) e `capolinea_certo` li esclude.
    """

    n_origina: int
    n_termina: int  # destinazione dichiarata dall'API = questa stazione
    n_termina_dedotti: int  # solo in arrivo e non riparte: stima
    n_passaggio: int
    n_incerti: int

    @property
    def capolinea(self) -> bool:
        return self.n_origina + self.n_termina + self.n_termina_dedotti > 0

    @property
    def capolinea_certo(self) -> bool:
        """Capolinea senza contare le deduzioni."""
        return self.n_origina + self.n_termina > 0

    @property
    def transito(self) -> bool:
        return self.n_passaggio > 0

    @property
    def e_origine(self) -> bool:
        """Almeno un treno nasce qui."""
        return self.n_origina > 0

    @property
    def e_destinazione(self) -> bool:
        """Almeno un treno finisce qui (dichiarato o dedotto)."""
        return self.n_termina + self.n_termina_dedotti > 0

    @property
    def n_certi(self) -> int:
        return self.n_origina + self.n_termina + self.n_termina_dedotti + self.n_passaggio


def calcola_ruolo(conteggi: Counter[RuoloTreno]) -> Ruolo:
    """Ruolo della stazione dai ruoli dei suoi treni."""
    return Ruolo(
        n_origina=conteggi[RuoloTreno.ORIGINA],
        n_termina=conteggi[RuoloTreno.TERMINA],
        n_termina_dedotti=conteggi[RuoloTreno.TERMINA_DEDOTTO],
        n_passaggio=conteggi[RuoloTreno.PASSAGGIO],
        n_incerti=conteggi[RuoloTreno.INCERTO],
    )


# --------------------------------------------------------------------------- binari


def _chiave_binario(b: str) -> tuple[int, int, str]:
    """Ordine naturale: 1, 2, 10, poi i binari non numerici ("1 EST", "Tronco")."""
    m = re.match(r"\d+", b)
    return (0, int(m.group()), b) if m else (1, 0, b)


@dataclass(frozen=True)
class BinarioStazione:
    """Uso di un binario nella finestra osservata."""

    binario: str
    n_treni: int
    n_partenze: int
    n_arrivi: int
    n_cambiati: int  # corse di questo binario il cui binario programmato e reale differiscono
    collegamenti: tuple[tuple[Collegamento, int], ...]  # (collegamento, n. treni), piu' usati prima
    # Quanto e' frequentato il binario: ogni treno conta UNA volta (alla partenza, altrimenti
    # all'arrivo), anche se vi compare sia in arrivo sia in partenza. E' il dato da usare per
    # "quanti treni all'ora" e "un treno ogni N minuti"; `frequenza_teorica` include i cancellati.
    frequenza: Frequenza
    frequenza_teorica: Frequenza
    frequenza_partenze: Frequenza  # cadenza delle sole partenze da questo binario
    frequenza_arrivi: Frequenza  # cadenza degli arrivi su questo binario
    # come sopra, ma con i treni cancellati assegnati a questo binario (vedi `ProfiloStazione`).
    # Solo per i binari programmati: un treno cancellato non usa nessun binario reale, quindi
    # per i binari reali coincidono con le frequenze effettive e `n_soppressi` e' 0.
    frequenza_teorica_partenze: Frequenza
    frequenza_teorica_arrivi: Frequenza
    n_soppressi: int  # treni cancellati assegnati a questo binario

    @property
    def elenco_collegamenti(self) -> tuple[Collegamento, ...]:
        """I collegamenti del binario, senza duplicati e senza conteggi."""
        return tuple(c for c, _ in self.collegamenti)


# --------------------------------------------------------------------------- collegamenti


@dataclass(frozen=True)
class CollegamentoStazione:
    """Un collegamento visto da questa stazione, con le sue statistiche."""

    collegamento: Collegamento
    n_treni: int
    categorie: tuple[tuple[str, int], ...]  # (categoria, n. treni), piu' frequenti prima
    binari_programmati: tuple[str, ...]
    binari_reali: tuple[str, ...]
    frequenza: Frequenza
    n_incerti: int  # treni solo in arrivo, di cui non si sa se finiscono qui
    frequenza_teorica: Frequenza  # come `frequenza`, con i treni cancellati di questo collegamento
    n_soppressi: int


def accoppia(
    collegamenti: Sequence[Collegamento],
) -> list[tuple[Collegamento, Collegamento | None]]:
    """Riunisce i due versi dello stesso collegamento (A->B con B->A).

    Pensata per la presentazione: nei dati i versi restano separati, perche' binari e
    frequenze cambiano da un verso all'altro. Il secondo elemento e' `None` se il verso
    opposto non c'e'.
    """
    per_coppia: dict[tuple[str, str], list[Collegamento]] = defaultdict(list)
    for c in collegamenti:
        per_coppia[c.coppia].append(c)
    out: list[tuple[Collegamento, Collegamento | None]] = []
    for gruppo in per_coppia.values():
        primo = gruppo[0]
        opposto = next((c for c in gruppo[1:] if c != primo), None)
        out.append((primo, opposto))
    return out


class _Risolutore:
    """Completa codici e nomi delle stazioni usando le altre righe dello stesso tabellone."""

    def __init__(self, corse: Iterable[Corsa], stazione: str, nome: str | None) -> None:
        nome_a_codici: dict[str, set[str]] = defaultdict(set)
        self.codice_a_nome: dict[str, str] = {}
        coppie: list[tuple[str | None, str | None]] = [(stazione, nome)]
        for c in corse:
            coppie.append((c.origine_codice, c.origine_nome))
            coppie.append((c.destinazione_codice, c.destinazione_nome))
        for codice, n in coppie:
            nn = normalizza_nome(n)
            if codice and nn:
                nome_a_codici[nn].add(codice)
                self.codice_a_nome.setdefault(codice, n.strip() if n else nn)
        # un nome che corrisponde a due codici e' ambiguo: non si usa
        self.nome_a_codice = {n: next(iter(c)) for n, c in nome_a_codici.items() if len(c) == 1}

    def risolvi(self, codice: str | None, nome: str | None) -> tuple[str | None, str | None]:
        nn = normalizza_nome(nome)
        if codice is None and nn is not None:
            codice = self.nome_a_codice.get(nn)
        if nome is None and codice is not None:
            nome = self.codice_a_nome.get(codice)
        return codice, nome


def _collegamento(
    t: TrenoInStazione, stazione: str, r: _Risolutore, *, ammetti_dedotto: bool = False
) -> Collegamento | None:
    """Origine -> destinazione del treno, o `None` se non si conosce.

    Un treno solo in arrivo non ha destinazione dichiarata: il collegamento "origine -> questa
    stazione" si crea solo con `ammetti_dedotto` (il treno e' un terminale dedotto). Un treno
    incerto o cancellato che si vede solo negli arrivi non genera un collegamento inventato.
    """
    p, a = t.partenza, t.arrivo
    o_cod = (p.origine_codice if p else None) or (a.origine_codice if a else None)
    o_nom = (p.origine_nome if p else None) or (a.origine_nome if a else None)
    if p is not None:
        d_cod, d_nom = p.destinazione_codice, p.destinazione_nome
    elif a is not None and (a.destinazione_codice or a.destinazione_nome):
        d_cod, d_nom = a.destinazione_codice, a.destinazione_nome
    elif ammetti_dedotto:
        d_cod, d_nom = stazione, None  # solo in arrivo, finisce qui (dedotto)
    else:
        return None
    o_cod, o_nom = r.risolvi(o_cod, o_nom)
    d_cod, d_nom = r.risolvi(d_cod, d_nom)
    if (o_cod is None and normalizza_nome(o_nom) is None) or (
        d_cod is None and normalizza_nome(d_nom) is None
    ):
        return None
    return Collegamento(o_cod, d_cod, o_nom, d_nom)


# --------------------------------------------------------------------------- il profilo


def _nome_dettaglio(dettaglio: StationDetail | None) -> str | None:
    """Nome della stazione da `dettaglioStazione` (`localita.nomeLungo`), se c'e'."""
    if dettaglio is None or dettaglio.localita is None:
        return None
    return (dettaglio.localita.nomeLungo or "").strip() or None


def _citta_dettaglio(dettaglio: StationDetail | None) -> str | None:
    """Citta' da `dettaglioStazione`. L'API usa "A" come segnaposto quando non ce n'e' una."""
    if dettaglio is None or dettaglio.nomeCitta is None:
        return None
    citta = dettaglio.nomeCitta.strip()
    return None if citta in ("", "A") else citta


@dataclass(frozen=True)
class ProfiloStazione:
    """Fotografia di una stazione ricavata da un insieme di corse dei suoi tabelloni."""

    codice: str
    nome: str | None
    nome_fonte: str | None  # "parametro", "dettaglio" o None se il nome e' ignoto
    # Anagrafica da `dettaglioStazione` (tutti None se il dettaglio non c'e')
    citta: str | None
    regione_codice: int | None
    regione_nome: str | None
    lat: float | None
    lon: float | None
    tipo_stazione: int | None  # 1 principale, 3 regolare, 4 segnaposto da ignorare
    n_corse: int
    n_treni: int  # treni distinti non soppressi
    n_soppressi: int
    n_senza_collegamento: int  # treni di cui manca origine o destinazione
    n_senza_binario: int  # treni senza alcun binario noto
    finestra_ms: tuple[int, int] | None  # primo e ultimo orario osservati
    # Fascia su cui sono calcolate le frequenze (vedi `ParametriProfilo.usa_finestra_comune`);
    # `None` se non applicabile. I treni fuori fascia restano in `n_treni`, ma non nelle frequenze.
    finestra_frequenze_ms: tuple[int, int] | None
    n_fuori_finestra: (
        int  # treni il cui orario di riferimento (partenza, altrimenti arrivo) e' fuori
    )
    # Relazione binario -> collegamenti, in due liste. Una corsa compare nella lista dei
    # programmati se ha un binario programmato, in quella dei reali se ne ha uno effettivo;
    # se ha entrambi (anche diversi) compare in entrambe.
    binari_programmati: tuple[BinarioStazione, ...]
    binari_reali: tuple[BinarioStazione, ...]
    elenco_binari: tuple[str, ...]  # unione dei due, in ordine naturale
    frequenza: Frequenza  # tutti i treni
    frequenza_partenze: Frequenza
    frequenza_arrivi: Frequenza
    # Frequenza *teorica*: quella programmata, con i treni cancellati (`provvedimento` 1) dentro.
    # Le frequenze sopra sono quelle *effettive* (solo i treni che circolano). La differenza tra
    # le due dice quanto servizio e' stato tolto.
    frequenza_teorica: Frequenza
    frequenza_teorica_partenze: Frequenza
    frequenza_teorica_arrivi: Frequenza
    n_soppressi_non_assegnati: int  # cancellati di cui non si sa il binario (vedi sotto)
    ruolo: Ruolo
    collegamenti: tuple[CollegamentoStazione, ...]

    @property
    def quota_soppressi(self) -> float | None:
        """Treni cancellati / treni programmati; `None` se non c'e' nessun treno."""
        tot = self.n_treni + self.n_soppressi
        return self.n_soppressi / tot if tot else None

    @property
    def n_binari(self) -> int:
        """Binari *osservati*, programmati ed effettivi insieme: un limite inferiore."""
        return len(self.elenco_binari)

    @property
    def finestra_min(self) -> float | None:
        if self.finestra_ms is None:
            return None
        return (self.finestra_ms[1] - self.finestra_ms[0]) / _MS_MINUTO

    @property
    def elenco_collegamenti(self) -> tuple[Collegamento, ...]:
        """Le coppie origine -> destinazione della stazione, senza duplicati, piu' frequenti prima.

        I due versi (A -> B e B -> A) sono voci distinte. Per i dettagli (treni, categorie,
        binari, frequenza) di ciascuna c'e' `collegamenti`.
        """
        return tuple(c.collegamento for c in self.collegamenti)

    def collegamenti_per_binario_programmato(
        self,
    ) -> dict[str, tuple[tuple[Collegamento, int], ...]]:
        """Per ogni binario *programmato*, i collegamenti previsti (con il numero di treni)."""
        return {b.binario: b.collegamenti for b in self.binari_programmati}

    def collegamenti_per_binario_reale(self) -> dict[str, tuple[tuple[Collegamento, int], ...]]:
        """Per ogni binario *reale* (effettivo), i collegamenti che vi sono passati."""
        return {b.binario: b.collegamenti for b in self.binari_reali}

    @classmethod
    def da_corse(
        cls,
        codice: str,
        corse: Iterable[Corsa],
        *,
        nome: str | None = None,
        dettaglio: StationDetail | None = None,
        parametri: ParametriProfilo | None = None,
    ) -> ProfiloStazione:
        p = parametri or ParametriProfilo()
        lista = list(corse)
        altre = {c.stazione for c in lista if c.stazione != codice}
        if altre:
            raise ValueError(
                f"corse di altre stazioni nel profilo di {codice}: {sorted(altre)[:3]}"
            )
        treni_tutti = _raggruppa(lista)
        treni = [t for t in treni_tutti if not t.soppresso]
        soppressi = [t for t in treni_tutti if t.soppresso]
        n_soppressi = len(soppressi)

        partenze_ok = [t.partenza for t in treni if t.partenza is not None]
        fine = p.fine_finestra_partenze
        if fine is None:
            orari_p = [c.orario for c in partenze_ok if c.orario is not None]
            fine = max(orari_p) if orari_p else None

        nome_dettaglio = _nome_dettaglio(dettaglio)
        # Il nome non e' nelle righe dei tabelloni della stazione stessa (le righe portano il nome
        # dell'altra stazione): viene dal parametro o dal dettaglio, altrimenti e' ignoto.
        nome_stazione = nome or nome_dettaglio
        res = _Risolutore(lista, codice, nome_stazione)

        finestra = (
            finestra_comune(
                (t.partenza.orario for t in treni if t.partenza is not None),
                (t.arrivo.orario for t in treni if t.arrivo is not None),
            )
            if p.usa_finestra_comune
            else None
        )

        def freq_finestra(orari: Iterable[int | None], parametri: ParametriProfilo) -> Frequenza:
            """Frequenza dei soli orari nella fascia comune a partenze e arrivi.

            Ogni serie e' filtrata sui propri orari: le frequenze di partenze e di arrivi
            usano gli orari delle rispettive corse, quelle di un treno il suo orario di
            riferimento (la partenza, altrimenti l'arrivo). Un treno a cavallo del bordo puo'
            quindi contare in una serie e non nell'altra.
            """
            return calcola_frequenza(
                (
                    o
                    for o in orari
                    if finestra is None or (o is not None and finestra[0] <= o <= finestra[1])
                ),
                parametri,
            )

        nome_fonte = "parametro" if nome else ("dettaglio" if nome_dettaglio else None)
        ruoli_per_treno = {t.chiave: _ruolo_treno(t, codice, nome_stazione, fine, p) for t in treni}
        ruoli = Counter(ruoli_per_treno.values())

        # ---- collegamenti e binari
        coll_treni: dict[Collegamento, list[TrenoInStazione]] = defaultdict(list)
        n_senza_coll = 0
        coll_di: dict[tuple[int, str | None, int | None], Collegamento] = {}
        for t in treni:
            c = _collegamento(
                t,
                codice,
                res,
                ammetti_dedotto=ruoli_per_treno[t.chiave] is RuoloTreno.TERMINA_DEDOTTO,
            )
            if c is None:
                n_senza_coll += 1
                continue
            coll_treni[c].append(t)
            coll_di[t.chiave] = c

        coll_soppressi: dict[Collegamento, list[TrenoInStazione]] = defaultdict(list)
        for t in soppressi:
            cs = _collegamento(t, codice, res)
            if cs is not None:
                coll_soppressi[cs].append(t)

        collegamenti: list[CollegamentoStazione] = []
        for c, ts in coll_treni.items():
            categorie = Counter(t.categoria for t in ts)
            con_soppressi = ts + coll_soppressi.get(c, [])
            prog_c = {b for t in ts for cc in t.corse if (b := cc.binario_programmato)}
            reali_c = {b for t in ts for cc in t.corse if (b := cc.binario_effettivo)}
            collegamenti.append(
                CollegamentoStazione(
                    collegamento=c,
                    n_treni=len(ts),
                    categorie=tuple(categorie.most_common()),
                    binari_programmati=tuple(sorted(prog_c, key=_chiave_binario)),
                    binari_reali=tuple(sorted(reali_c, key=_chiave_binario)),
                    frequenza=freq_finestra((t.orario for t in ts), p),
                    n_incerti=sum(1 for t in ts if ruoli_per_treno[t.chiave] is RuoloTreno.INCERTO),
                    frequenza_teorica=freq_finestra((t.orario for t in con_soppressi), p),
                    n_soppressi=len(coll_soppressi.get(c, [])),
                )
            )
        collegamenti.sort(key=lambda x: (-x.n_treni, x.collegamento.etichetta))

        n_senza_binario = sum(1 for t in treni if not any(cc.binari for cc in t.corse))

        def orari_treni(coppie: list[tuple[TrenoInStazione, Corsa]]) -> list[int]:
            """Un orario per treno: la partenza se c'e' tra le corse date, altrimenti l'arrivo."""
            scelti: dict[tuple[int, str | None, int | None], tuple[bool, int]] = {}
            for t, cc in coppie:
                if cc.orario is None:
                    continue
                e_partenza = cc.tipo is TipoCorsa.PARTENZA
                if t.chiave not in scelti or (e_partenza and not scelti[t.chiave][0]):
                    scelti[t.chiave] = (e_partenza, cc.orario)
            return [o for _, o in scelti.values()]

        def costruisci(
            selettore: Callable[[Corsa], str | None], *, con_soppressi: bool
        ) -> tuple[tuple[BinarioStazione, ...], int]:
            """Lista dei binari secondo `selettore`; e n. di cancellati senza binario."""
            per_binario: dict[str, list[tuple[TrenoInStazione, Corsa]]] = defaultdict(list)
            for t in treni:
                for cc in t.corse:
                    if b := selettore(cc):
                        per_binario[b].append((t, cc))

            # Binario dei treni cancellati. Il tabellone di solito non glielo da': si assegnano
            # solo quando e' certo (binario proprio) o quando il loro collegamento usa un unico
            # binario. Altrimenti restano fuori e si contano in `n_soppressi_non_assegnati`.
            righe_soppresse: dict[str, list[tuple[TrenoInStazione, Corsa]]] = defaultdict(list)
            non_assegnati = 0
            if con_soppressi:
                del_collegamento: dict[Collegamento, set[str]] = defaultdict(set)
                for b, righe in per_binario.items():
                    for t, _ in righe:
                        if t.chiave in coll_di:
                            del_collegamento[coll_di[t.chiave]].add(b)
                for t in soppressi:
                    propri = {b for cc in t.corse if (b := selettore(cc))} & set(per_binario)
                    cs = _collegamento(t, codice, res)
                    dedotti = del_collegamento.get(cs, set()) if cs is not None else set()
                    if propri:
                        for b in propri:
                            righe_soppresse[b].extend(
                                (t, cc) for cc in t.corse if selettore(cc) == b
                            )
                    elif len(dedotti) == 1:
                        (b,) = dedotti
                        righe_soppresse[b].extend((t, cc) for cc in t.corse)
                    else:
                        non_assegnati += 1

            out: list[BinarioStazione] = []
            for b, righe in per_binario.items():
                treni_b = {t.chiave: t for t, _ in righe}
                teoriche = righe + righe_soppresse.get(b, [])
                conta = Counter(coll_di[k] for k in treni_b if k in coll_di)
                out.append(
                    BinarioStazione(
                        binario=b,
                        n_treni=len(treni_b),
                        n_partenze=sum(1 for _, cc in righe if cc.tipo is TipoCorsa.PARTENZA),
                        n_arrivi=sum(1 for _, cc in righe if cc.tipo is TipoCorsa.ARRIVO),
                        n_cambiati=sum(1 for _, cc in righe if cc.binario_cambiato),
                        collegamenti=tuple(conta.most_common()),
                        frequenza=freq_finestra(orari_treni(righe), p),
                        frequenza_teorica=freq_finestra(orari_treni(teoriche), p),
                        frequenza_partenze=freq_finestra(
                            (cc.orario for _, cc in righe if cc.tipo is TipoCorsa.PARTENZA), p
                        ),
                        frequenza_arrivi=freq_finestra(
                            (cc.orario for _, cc in righe if cc.tipo is TipoCorsa.ARRIVO), p
                        ),
                        frequenza_teorica_partenze=freq_finestra(
                            (cc.orario for _, cc in teoriche if cc.tipo is TipoCorsa.PARTENZA), p
                        ),
                        frequenza_teorica_arrivi=freq_finestra(
                            (cc.orario for _, cc in teoriche if cc.tipo is TipoCorsa.ARRIVO), p
                        ),
                        n_soppressi=len({t.chiave for t, _ in righe_soppresse.get(b, [])}),
                    )
                )
            out.sort(key=lambda x: _chiave_binario(x.binario))
            return tuple(out), non_assegnati

        binari_programmati, non_assegnati = costruisci(
            lambda cc: cc.binario_programmato, con_soppressi=True
        )
        binari_reali, _ = costruisci(lambda cc: cc.binario_effettivo, con_soppressi=False)
        elenco_binari = tuple(
            sorted(
                {b for t in treni for cc in t.corse for b in cc.binari},
                key=_chiave_binario,
            )
        )

        orari = [o for t in treni if (o := t.orario) is not None]
        return cls(
            codice=codice,
            nome=nome_stazione,
            nome_fonte=nome_fonte,
            citta=_citta_dettaglio(dettaglio),
            regione_codice=dettaglio.codReg if dettaglio else None,
            regione_nome=dettaglio.nomeRegione if dettaglio else None,
            lat=dettaglio.lat if dettaglio else None,
            lon=dettaglio.lon if dettaglio else None,
            tipo_stazione=dettaglio.tipoStazione if dettaglio else None,
            n_corse=len(lista),
            n_treni=len(treni),
            n_soppressi=n_soppressi,
            n_senza_collegamento=n_senza_coll,
            n_senza_binario=n_senza_binario,
            finestra_ms=(min(orari), max(orari)) if orari else None,
            finestra_frequenze_ms=finestra,
            n_fuori_finestra=(
                sum(1 for o in orari if not finestra[0] <= o <= finestra[1]) if finestra else 0
            ),
            binari_programmati=binari_programmati,
            binari_reali=binari_reali,
            elenco_binari=elenco_binari,
            frequenza=freq_finestra(orari, p),
            frequenza_partenze=freq_finestra((c.orario for c in partenze_ok), p),
            frequenza_arrivi=freq_finestra(
                (t.arrivo.orario for t in treni if t.arrivo is not None), p
            ),
            frequenza_teorica=freq_finestra((t.orario for t in treni_tutti), p),
            frequenza_teorica_partenze=freq_finestra(
                (t.partenza.orario for t in treni_tutti if t.partenza is not None), p
            ),
            frequenza_teorica_arrivi=freq_finestra(
                (t.arrivo.orario for t in treni_tutti if t.arrivo is not None), p
            ),
            n_soppressi_non_assegnati=non_assegnati,
            ruolo=calcola_ruolo(ruoli),
            collegamenti=tuple(collegamenti),
        )

    @classmethod
    def da_tabelloni(
        cls,
        codice: str,
        partenze: Iterable[TrainBoardItem],
        arrivi: Iterable[TrainBoardItem],
        *,
        nome: str | None = None,
        dettaglio: StationDetail | None = None,
        parametri: ParametriProfilo | None = None,
    ) -> ProfiloStazione:
        corse = [
            *da_tabellone(partenze, codice, TipoCorsa.PARTENZA),
            *da_tabellone(arrivi, codice, TipoCorsa.ARRIVO),
        ]
        return cls.da_corse(codice, corse, nome=nome, dettaglio=dettaglio, parametri=parametri)


# --------------------------------------------------------------------------- versione live


class _ClienteStazione(Protocol):
    """Quanto serve del client (anche uno stub di test); i nomi combaciano con quelli reali."""

    async def partenze(
        self, codice_stazione: str, data_ora: datetime | str | None = None
    ) -> list[TrainBoardItem]: ...

    async def arrivi(
        self, codice_stazione: str, data_ora: datetime | str | None = None
    ) -> list[TrainBoardItem]: ...

    async def regione(self, codice_stazione: str) -> int | None: ...

    async def dettaglio_stazione(
        self, codice_stazione: str, codice_regione: int
    ) -> StationDetail | None: ...


async def scarica_dettaglio(client: _ClienteStazione, codice: str) -> StationDetail | None:
    """`dettaglioStazione` di una stazione: 2 richieste (`regione` per il codice, poi il dettaglio).

    Ritorna `None` se non si ottiene: e' un arricchimento, un errore non deve far fallire il
    profilo. (L'autocompletamento non serve: cerca per prefisso del *nome*, e con un codice
    risponde vuoto.)
    """
    try:
        regione = await client.regione(codice)
        if regione is None:
            return None
        return await client.dettaglio_stazione(codice, regione)
    except (httpx.HTTPError, ValueError) as exc:  # ValueError: JSON o modello non validi
        logger.warning("dettaglioStazione di %s non disponibile: %s", codice, exc)
        return None


async def profilo_stazione(
    client: _ClienteStazione,
    codice: str,
    *,
    partenze: Iterable[TrainBoardItem] | None = None,
    arrivi: Iterable[TrainBoardItem] | None = None,
    dettaglio: StationDetail | None = None,
    con_dettaglio: bool = True,
    data_ora: datetime | str | None = None,
    nome: str | None = None,
    parametri: ParametriProfilo | None = None,
) -> ProfiloStazione:
    """Profilo di una stazione; cio' che non si passa viene chiesto all'API, in sequenza.

    - `partenze`, `arrivi`: se `None`, una richiesta ciascuno (`data_ora` o adesso);
    - `dettaglio`: se `None` e `con_dettaglio`, due richieste (`regione` + `dettaglioStazione`).
      Da' nome, citta', regione, coordinate e tipo. Senza, il nome e' ignoto (non e' nelle righe
      dei tabelloni della stazione) e i collegamenti si leggono "S01700 None -> ...".

    Con tutto passato, nessuna richiesta. `con_dettaglio=False` evita le due del dettaglio.
    """
    if partenze is None:
        partenze = await client.partenze(codice, data_ora)
    if arrivi is None:
        arrivi = await client.arrivi(codice, data_ora)
    if dettaglio is None and con_dettaglio:
        dettaglio = await scarica_dettaglio(client, codice)
    return ProfiloStazione.da_tabelloni(
        codice, partenze, arrivi, nome=nome, dettaglio=dettaglio, parametri=parametri
    )
