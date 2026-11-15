# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Profilo di un treno ricavato da `andamentoTreno`: itinerario, fermate, archi.

Da una sola risposta di `andamentoTreno` (tutte le fermate, con orari teorici e reali di
arrivo e partenza, ritardi e binari) si ricavano:

- l'**itinerario**: la sequenza dei codici stazione, indipendente dal verso (`Itinerario`),
  con le fermate soppresse incluse perche' descrive il percorso *programmato*;
- le **fermate** (`FermataTreno`), nell'ordine di marcia, con tutti i dati di ciascuna;
- gli **archi** (`Arco`): una coppia di fermate consecutive, con tempo di percorrenza
  programmato ed effettivo, ritardo accumulato e sosta;
- il **collegamento** programmato (origine -> ultima fermata della lista) ed effettivo
  (origine -> destinazione dichiarata dall'API, che tiene conto delle soppressioni).

Una "linea" non si ricava da un solo treno: nasce raggruppando piu' itinerari.
`ProfiloTreno.itinerario.chiave` e' l'aggancio.

Cose da sapere sui dati di `andamentoTreno`:

- Il `progressivo` ha dei buchi (mancano i nodi non passeggeri) e **non e' affidabile per
  ordinare**: in 58 treni su 10.328 e' ripetuto o non crescente (tipico: un treno che unisce
  due tratti, come Merano-Bolzano-Brennero). Le fermate restano nell'ordine dell'API. Un arco
  collega due fermate consecutive *nell'elenco*, non necessariamente adiacenti sulla rete.
- Il `ritardo`/`ritardoArrivo`/`ritardoPartenza` dell'API e' un intero arrotondato; gli orari
  reali hanno una risoluzione di 30 secondi. Qui i ritardi si ricalcolano dai millisecondi
  (reale - teorico), in minuti con decimali, e quelli dell'API restano nelle fermate come
  `ritardo_api_*`.
- Un treno parzialmente soppresso (`tipoTreno` PP, SI, SF) riporta come destinazione quella
  *effettiva* (l'ultima fermata non soppressa). L'itinerario e' invece quello programmato.
- Le fermate soppresse hanno `actualFermataType` 3, nessun orario reale e `tipoFermata` vuoto.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Protocol

from viaggiatreno.insights.collegamento import Collegamento
from viaggiatreno.insights.corsa import orario_ms
from viaggiatreno.insights.itinerario import Itinerario, Verso
from viaggiatreno.models.train import Fermata, TrainStatus

_MS_MINUTO = 60_000
_RAGGIO_TERRA_KM = 6371.0


class StatoFermata(StrEnum):
    """Cosa e' successo (o sta per succedere) in una fermata."""

    EFFETTUATA = "effettuata"  # actualFermataType 1
    ATTESA = "attesa"  # 0: il treno non ci e' ancora arrivato
    NON_PREVISTA = "non_prevista"  # 2
    SOPPRESSA = "soppressa"  # 3
    SCONOSCIUTA = "sconosciuta"

    @classmethod
    def da_codice(cls, codice: int | None) -> StatoFermata:
        return {
            1: cls.EFFETTUATA,
            0: cls.ATTESA,
            2: cls.NON_PREVISTA,
            3: cls.SOPPRESSA,
        }.get(codice if codice is not None else -1, cls.SCONOSCIUTA)


class StatoTreno(StrEnum):
    REGOLARE = "regolare"
    PARZIALMENTE_SOPPRESSO = "parzialmente_soppresso"
    CANCELLATO = "cancellato"


class Avanzamento(StrEnum):
    """Dove e' arrivata la corsa: serve a decidere se continuare a seguirla."""

    IN_CORSO = "in_corso"
    ARRIVATO = "arrivato"
    SOPPRESSO = "soppresso"  # tipoTreno ST: cancellato per intero


def avanzamento_di(status: TrainStatus) -> Avanzamento:
    """`arrivato` se l'API lo dice, `soppresso` se e' ST, altrimenti `in_corso`.

    `arrivato` vince su tutto. Un treno parzialmente soppresso (PP, SI, SF) o con
    `provvedimento` 1 ma tipo diverso da ST resta `in_corso`: e' la regola con cui il crawler
    chiude le corse, e non va cambiata senza rivedere i dati gia' raccolti.
    """
    if status.arrivato:
        return Avanzamento.ARRIVATO
    if status.tipoTreno == "ST":
        return Avanzamento.SOPPRESSO
    return Avanzamento.IN_CORSO


def ha_anomalie(status: TrainStatus) -> bool:
    """True se la risposta segnala qualcosa oltre la marcia regolare.

    Cancellazioni totali o parziali, deviazioni, riprogrammazioni, variazioni di origine o
    destinazione, cambi di numero, note sulla circolazione, fermate non effettuate o non
    previste: e' quello che conviene conservare per intero per capire a posteriori.
    """
    if (status.tipoTreno or "PG") != "PG":
        return True
    if (status.provvedimento or 0) != 0:
        return True
    if (status.riprogrammazione or "N") == "Y":
        return True
    if status.subTitle:
        return True
    if status.fermateSoppresse:
        return True
    if status.cambiNumero or status.anormalita or status.provvedimenti:
        return True
    return any(f.actualFermataType in (2, 3) for f in status.fermate)


def _diff_min(reale: int | None, teorico: int | None) -> float | None:
    """Differenza reale - teorico in minuti; `None` se manca uno dei due."""
    if reale is None or teorico is None:
        return None
    return (reale - teorico) / _MS_MINUTO


def _testo(valore: str | None) -> str | None:
    if valore is None:
        return None
    pulito = valore.strip()
    return pulito or None


@dataclass(frozen=True)
class FermataTreno:
    """Una fermata del treno, con orari e binari di arrivo e di partenza."""

    posizione: int  # 0-based nell'elenco dell'API (il `progressivo` ha buchi e doppioni)
    codice: str
    nome: str
    stato: StatoFermata
    prima: bool  # e' la prima della lista
    ultima: bool  # e' l'ultima della lista (anche se soppressa)
    programmata: int | None  # ms: la partenza se e' la prima, altrimenti l'arrivo (come dall'API)
    arrivo_teorico: int | None  # ms; None alla prima fermata
    partenza_teorica: int | None  # ms; None all'ultima
    arrivo_reale: int | None
    partenza_reale: int | None
    binario_arrivo_programmato: str | None
    binario_arrivo_effettivo: str | None
    binario_partenza_programmato: str | None
    binario_partenza_effettivo: str | None
    ritardo_api_arrivo: int | None
    ritardo_api_partenza: int | None

    @property
    def ritardo_arrivo(self) -> float | None:
        """Minuti di ritardo in arrivo, dai millisecondi (negativo = anticipo)."""
        return _diff_min(self.arrivo_reale, self.arrivo_teorico)

    @property
    def ritardo_partenza(self) -> float | None:
        return _diff_min(self.partenza_reale, self.partenza_teorica)

    @property
    def sosta_programmata(self) -> float | None:
        """Minuti di sosta previsti dall'orario (partenza - arrivo teorici)."""
        return _diff_min(self.partenza_teorica, self.arrivo_teorico)

    @property
    def sosta_effettiva(self) -> float | None:
        return _diff_min(self.partenza_reale, self.arrivo_reale)

    @property
    def binari(self) -> tuple[str, ...]:
        """Tutti i binari noti della fermata (programmati ed effettivi), senza duplicati."""
        visti = [
            b
            for b in (
                self.binario_arrivo_programmato,
                self.binario_partenza_programmato,
                self.binario_arrivo_effettivo,
                self.binario_partenza_effettivo,
            )
            if b
        ]
        return tuple(dict.fromkeys(visti))

    @property
    def binario_cambiato(self) -> bool:
        """True se un binario effettivo differisce dal programmato (arrivo o partenza)."""
        for prog, eff in (
            (self.binario_arrivo_programmato, self.binario_arrivo_effettivo),
            (self.binario_partenza_programmato, self.binario_partenza_effettivo),
        ):
            if prog and eff and prog != eff:
                return True
        return False

    @property
    def soppressa(self) -> bool:
        return self.stato is StatoFermata.SOPPRESSA


@dataclass(frozen=True)
class Arco:
    """Due fermate consecutive del treno e il tratto tra loro.

    Il verso e' quello di marcia del treno. `coppia` e' la stessa nei due versi, e serve ad
    aggregare treni che percorrono il tratto in sensi opposti.
    """

    da: FermataTreno
    a: FermataTreno
    distanza_km: float | None = None  # in linea d'aria, solo con le coordinate

    @property
    def coppia(self) -> tuple[str, str]:
        x, y = self.da.codice, self.a.codice
        return (x, y) if x <= y else (y, x)

    @property
    def soppresso(self) -> bool:
        """True se almeno una delle due fermate e' soppressa."""
        return self.da.soppressa or self.a.soppressa

    @property
    def durata_programmata(self) -> float | None:
        """Minuti di marcia previsti: arrivo teorico in `a` meno partenza teorica da `da`."""
        return _diff_min(self.a.arrivo_teorico, self.da.partenza_teorica)

    @property
    def durata_effettiva(self) -> float | None:
        """Minuti di marcia reali; `None` se il treno non ha percorso il tratto."""
        return _diff_min(self.a.arrivo_reale, self.da.partenza_reale)

    @property
    def ritardo_accumulato(self) -> float | None:
        """Quanto ritardo si guadagna (+) o si recupera (-) lungo il tratto, in minuti."""
        if self.da.ritardo_partenza is None or self.a.ritardo_arrivo is None:
            return None
        return self.a.ritardo_arrivo - self.da.ritardo_partenza

    @property
    def velocita_programmata_kmh(self) -> float | None:
        """Velocita' commerciale prevista (km in linea d'aria / ora); sottostima il vero."""
        d = self.durata_programmata
        if self.distanza_km is None or d is None or d <= 0:
            return None
        return self.distanza_km / (d / 60)

    @property
    def effettuato(self) -> bool:
        return self.durata_effettiva is not None


def distanza_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distanza in linea d'aria (haversine) tra due punti (lat, lon) in gradi, in km."""
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    x = (
        math.sin((la2 - la1) * p / 2) ** 2
        + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    )
    return 2 * _RAGGIO_TERRA_KM * math.asin(math.sqrt(x))


def _fermata(i: int, n: int, f: Fermata) -> FermataTreno:
    return FermataTreno(
        posizione=i,
        codice=f.id,
        nome=f.stazione,
        stato=StatoFermata.da_codice(f.actualFermataType),
        prima=i == 0,
        ultima=i == n - 1,
        programmata=f.programmata,
        arrivo_teorico=f.arrivo_teorico,
        partenza_teorica=f.partenza_teorica,
        arrivo_reale=f.arrivoReale,
        partenza_reale=f.partenzaReale,
        binario_arrivo_programmato=_testo(f.binarioProgrammatoArrivoDescrizione),
        binario_arrivo_effettivo=_testo(f.binarioEffettivoArrivoDescrizione),
        binario_partenza_programmato=_testo(f.binarioProgrammatoPartenzaDescrizione),
        binario_partenza_effettivo=_testo(f.binarioEffettivoPartenzaDescrizione),
        ritardo_api_arrivo=f.ritardoArrivo,
        ritardo_api_partenza=f.ritardoPartenza,
    )


def _stato_treno(status: TrainStatus, fermate: list[FermataTreno]) -> StatoTreno:
    if status.tipoTreno == "ST" or status.provvedimento == 1 or not fermate:
        return StatoTreno.CANCELLATO
    if any(f.soppressa for f in fermate) or status.tipoTreno in ("PP", "SI", "SF"):
        return StatoTreno.PARZIALMENTE_SOPPRESSO
    return StatoTreno.REGOLARE


@dataclass(frozen=True)
class ProfiloTreno:
    """Fotografia di un treno ricavata da `andamentoTreno`."""

    numero: int
    categoria: str | None
    operatore: str | None
    data: str | None  # YYYY-MM-DD del giorno di partenza
    stato: StatoTreno
    avanzamento: Avanzamento
    ha_anomalie: bool
    orario_arrivo_programmato: (
        int | None
    )  # ms, come riportato dal treno (ripiego di arrivo_previsto)
    itinerario: Itinerario | None  # None se il treno ha meno di due fermate (cancellato)
    verso: Verso | None
    fermate: tuple[FermataTreno, ...]  # in ordine di marcia
    archi: tuple[Arco, ...]  # in ordine di marcia
    collegamento_programmato: Collegamento | None
    collegamento_effettivo: Collegamento | None
    ritardo_attuale: int | None  # minuti, come riportato dall'API
    arrivato: bool | None
    stazione_ultimo_rilevamento: str | None

    @property
    def fermate_valide(self) -> tuple[FermataTreno, ...]:
        """Le fermate non soppresse, in ordine di marcia."""
        return tuple(f for f in self.fermate if not f.soppressa)

    @property
    def fermata_origine_effettiva(self) -> FermataTreno | None:
        """La prima fermata non soppressa: da dove il treno parte davvero."""
        valide = self.fermate_valide
        return valide[0] if valide else None

    @property
    def fermata_destinazione_effettiva(self) -> FermataTreno | None:
        """L'ultima fermata non soppressa: dove il treno finisce davvero."""
        valide = self.fermate_valide
        return valide[-1] if valide else None

    @property
    def arrivo_previsto(self) -> int | None:
        """Quando il treno arriva alla fine della corsa effettiva, in ms.

        L'orario programmato dell'ultima fermata non soppressa piu' il ritardo attuale
        (quello intero riportato dall'API). Un ritardo negativo non anticipa: un treno in
        anticipo non arriva prima dell'orario. In mancanza di fermate si usa l'arrivo
        programmato del treno; senza nemmeno quello, `None`.
        """
        ultima = self.fermata_destinazione_effettiva
        base = ultima.programmata if ultima is not None else None
        if base is None:
            base = self.orario_arrivo_programmato
        if base is None:
            return None
        return base + max(0, self.ritardo_attuale or 0) * _MS_MINUTO

    @property
    def fermate_soppresse(self) -> tuple[FermataTreno, ...]:
        return tuple(f for f in self.fermate if f.soppressa)

    @property
    def fermate_effettuate(self) -> tuple[FermataTreno, ...]:
        return tuple(f for f in self.fermate if f.stato is StatoFermata.EFFETTUATA)

    @property
    def ultima_effettuata(self) -> FermataTreno | None:
        """L'ultima fermata gia' raggiunta, o `None` se il treno non e' partito."""
        eff = self.fermate_effettuate
        return eff[-1] if eff else None

    @property
    def archi_effettuati(self) -> tuple[Arco, ...]:
        return tuple(a for a in self.archi if a.effettuato)

    @property
    def durata_programmata(self) -> float | None:
        """Minuti dalla prima partenza all'ultimo arrivo previsti dall'orario."""
        if len(self.fermate) < 2:
            return None
        return _diff_min(self.fermate[-1].arrivo_teorico, self.fermate[0].partenza_teorica)

    @property
    def ritardo_massimo(self) -> float | None:
        """Il ritardo piu' alto misurato su una fermata effettuata, in minuti."""
        valori = [
            r
            for f in self.fermate_effettuate
            for r in (f.ritardo_arrivo, f.ritardo_partenza)
            if r is not None
        ]
        return max(valori) if valori else None

    @property
    def ritardo_finale(self) -> float | None:
        """Ritardo all'ultima fermata effettuata (in arrivo se c'e', altrimenti in partenza)."""
        f = self.ultima_effettuata
        if f is None:
            return None
        return f.ritardo_arrivo if f.ritardo_arrivo is not None else f.ritardo_partenza

    @property
    def distanza_km(self) -> float | None:
        """Somma delle distanze degli archi; `None` se manca anche una sola distanza."""
        if not self.archi or any(a.distanza_km is None for a in self.archi):
            return None
        return sum(a.distanza_km for a in self.archi if a.distanza_km is not None)

    @classmethod
    def da_status(
        cls,
        status: TrainStatus,
        *,
        coordinate: Mapping[str, tuple[float, float]] | None = None,
    ) -> ProfiloTreno:
        """Profilo da una risposta di `andamentoTreno`.

        `coordinate` (codice -> (lat, lon)) e' opzionale: serve solo per distanze e velocita'.
        Le fermate restano nell'ordine in cui l'API le elenca: il `progressivo` non e' affidabile
        per ordinare (in 58 treni su 10.328 e' ripetuto o non crescente, e ordinando per quello
        gli orari tornano indietro in 54 treni contro 4 dell'ordine dell'API).
        """
        grezze = list(status.fermate or [])
        fermate = [_fermata(i, len(grezze), f) for i, f in enumerate(grezze)]
        stato = _stato_treno(status, fermate)

        archi: list[Arco] = []
        for da, a in pairwise(fermate):
            dist = None
            if coordinate and da.codice in coordinate and a.codice in coordinate:
                dist = distanza_km(coordinate[da.codice], coordinate[a.codice])
            archi.append(Arco(da, a, dist))

        itin_verso = Itinerario.da_status(status) if len(fermate) >= 2 else None
        itinerario, verso = itin_verso if itin_verso else (None, None)

        programmato = None
        if len(fermate) >= 2:
            programmato = Collegamento(
                fermate[0].codice, fermate[-1].codice, fermate[0].nome, fermate[-1].nome
            )
        effettivo = None
        if len(fermate) >= 2 and status.idOrigine and status.idDestinazione:
            effettivo = Collegamento(
                status.idOrigine,
                status.idDestinazione,
                _testo(status.origine),
                _testo(status.destinazione),
            )
        else:
            # senza idOrigine/idDestinazione: prima e ultima fermata non soppressa (non quelle
            # della lista, che per un treno parzialmente soppresso sono la destinazione programmata)
            validi = [f for f in fermate if not f.soppressa]
            if len(validi) >= 2:
                effettivo = Collegamento(
                    validi[0].codice, validi[-1].codice, validi[0].nome, validi[-1].nome
                )

        return cls(
            numero=status.numeroTreno,
            categoria=_testo(status.categoria),
            operatore=_testo(status.impresaFerroviaria),
            data=status.dataPartenzaTrenoAsDate,
            stato=stato,
            avanzamento=avanzamento_di(status),
            ha_anomalie=ha_anomalie(status),
            orario_arrivo_programmato=orario_ms(status.orarioArrivo),
            itinerario=itinerario,
            verso=verso,
            fermate=tuple(fermate),
            archi=tuple(archi),
            collegamento_programmato=programmato,
            collegamento_effettivo=effettivo,
            ritardo_attuale=status.ritardo,
            arrivato=status.arrivato,
            stazione_ultimo_rilevamento=_testo(status.stazioneUltimoRilevamento),
        )


class _ClienteTreno(Protocol):
    """Quanto serve del client (anche uno stub di test); i nomi combaciano con quelli reali."""

    async def andamento_treno(
        self, codice_stazione_origine: str, numero_treno: int | str, data_partenza: int | str
    ) -> TrainStatus | None: ...


async def profilo_treno(
    client: _ClienteTreno,
    codice_origine: str,
    numero: int | str,
    data_partenza: int | str,
    *,
    coordinate: Mapping[str, tuple[float, float]] | None = None,
) -> ProfiloTreno | None:
    """Scarica `andamentoTreno` (una richiesta) e ne ricava il profilo.

    `None` se l'API non ha il treno (204): e' normale prima della partenza e dopo il reset
    notturno. `data_partenza` e' la mezzanotte del giorno di partenza in ms.
    """
    status = await client.andamento_treno(codice_origine, numero, data_partenza)
    if status is None:
        return None
    return ProfiloTreno.da_status(status, coordinate=coordinate)


__all__ = [
    "Arco",
    "Avanzamento",
    "FermataTreno",
    "ProfiloTreno",
    "StatoFermata",
    "StatoTreno",
    "avanzamento_di",
    "distanza_km",
    "ha_anomalie",
    "profilo_treno",
]
