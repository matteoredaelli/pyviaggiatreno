# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""`Linea`: i treni che collegano gli stessi due estremi, e le statistiche dei loro tratti.

Un treno ha un `Itinerario`, non una linea: la linea nasce raggruppando piu' treni. Qui il
raggruppamento e' il piu' semplice possibile: **stessi due estremi, indipendente dal verso**.
Le fermate intermedie possono differire, e la differenza si descrive invece di nasconderla:

- un itinerario **salta fermate** se le sue fermate sono una sottosequenza di quello piu'
  completo (un regionale veloce rispetto al regionale);
- un itinerario e' **alternativo** se passa per fermate che l'altro non ha (un'altra strada
  tra gli stessi estremi, o una fermata aggiunta).

Sui dati reali (10.328 treni): 929 linee, 2.142 itinerari; 3.797 treni su 10.328 appartengono a
linee con piu' itinerari, di cui 2.991 saltano fermate e 806 sono alternativi. Una linea con un
solo itinerario e' il caso piu' frequente (486 su 929).

Limiti:

- Gli estremi sono quelli dell'itinerario *programmato*: un treno parzialmente soppresso resta
  sulla sua linea (`ProfiloTreno.itinerario` comprende le fermate soppresse).
- Due servizi diversi con gli stessi estremi (es. un regionale e un Intercity) finiscono nella
  stessa linea: la categoria si legge in `categorie`.
- La "linea" commerciale (R23, S8) non esiste nei dati: questo e' un raggruppamento calcolato.
- Gli archi si aggregano per *coppia di stazioni consecutive nell'elenco*: un treno che salta
  una fermata genera un arco piu' lungo, e non e' confrontabile con l'arco fra le due fermate
  intermedie. Vedi `aggrega_archi`.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from viaggiatreno.insights.collegamento import Collegamento
from viaggiatreno.insights.itinerario import Itinerario
from viaggiatreno.insights.treno import ProfiloTreno


class RapportoItinerario(StrEnum):
    """Come un itinerario sta rispetto a quello piu' completo della sua linea."""

    COMPLETO = "completo"  # e' l'itinerario piu' completo
    SALTA_FERMATE = "salta_fermate"  # sottosequenza del completo
    ALTERNATIVO = "alternativo"  # ha fermate che il completo non ha


def e_sottosequenza(piccola: tuple[str, ...], grande: tuple[str, ...]) -> bool:
    """True se tutte le fermate di `piccola` compaiono in `grande` nello stesso ordine."""
    it = iter(grande)
    return all(x in it for x in piccola)


@dataclass(frozen=True)
class VarianteLinea:
    """Un itinerario di una linea, con quanti treni lo percorrono."""

    itinerario: Itinerario
    n_treni: int
    rapporto: RapportoItinerario
    categorie: tuple[tuple[str, int], ...]  # (categoria, n. treni), piu' frequenti prima
    n_verso_diretto: int  # treni che lo percorrono nell'ordine canonico
    n_verso_inverso: int


@dataclass(frozen=True)
class Linea:
    """Treni con gli stessi due estremi, in qualunque verso."""

    estremo_a: str
    estremo_b: str
    nome: str
    n_treni: int
    varianti: tuple[VarianteLinea, ...]  # la piu' completa per prima, poi per n. treni
    categorie: tuple[tuple[str, int], ...]
    operatori: tuple[tuple[str, int], ...]

    @property
    def chiave(self) -> str:
        """Identificativo stabile, indipendente dal verso: `A|B` con A <= B."""
        return f"{self.estremo_a}|{self.estremo_b}"

    @property
    def completa(self) -> VarianteLinea:
        """L'itinerario piu' completo."""
        return self.varianti[0]

    @property
    def n_varianti(self) -> int:
        return len(self.varianti)

    @property
    def stazioni(self) -> tuple[str, ...]:
        """Tutte le stazioni della linea, nell'ordine del suo itinerario piu' completo."""
        return self.completa.itinerario.codici

    @property
    def collegamento(self) -> Collegamento:
        """Origine -> destinazione nel verso canonico."""
        return self.completa.itinerario.collegamento()


def _nome(itinerario: Itinerario) -> str:
    return itinerario.nome


def costruisci_linee(profili: Iterable[ProfiloTreno]) -> tuple[Linea, ...]:
    """Raggruppa i profili per estremi dell'itinerario. Ignora i treni senza itinerario.

    L'ordine del risultato e' per numero di treni decrescente, poi per chiave.
    """
    per_linea: dict[tuple[str, str], list[ProfiloTreno]] = defaultdict(list)
    for p in profili:
        if p.itinerario is None:
            continue
        per_linea[(p.itinerario.estremo_a, p.itinerario.estremo_b)].append(p)

    linee: list[Linea] = []
    for (a, b), treni in per_linea.items():
        per_itin: dict[Itinerario, list[ProfiloTreno]] = defaultdict(list)
        for p in treni:
            assert p.itinerario is not None
            per_itin[p.itinerario].append(p)
        # il piu' completo: piu' fermate, a parita' piu' treni, poi ordine stabile per chiave
        completo = min(per_itin, key=lambda i: (-i.n_fermate, -len(per_itin[i]), i.chiave))
        varianti: list[VarianteLinea] = []
        for itin, gruppo in per_itin.items():
            if itin == completo:
                rapporto = RapportoItinerario.COMPLETO
            elif e_sottosequenza(itin.codici, completo.codici):
                rapporto = RapportoItinerario.SALTA_FERMATE
            else:
                rapporto = RapportoItinerario.ALTERNATIVO
            categorie = Counter(p.categoria or "" for p in gruppo)
            varianti.append(
                VarianteLinea(
                    itinerario=itin,
                    n_treni=len(gruppo),
                    rapporto=rapporto,
                    categorie=tuple(categorie.most_common()),
                    n_verso_diretto=sum(
                        1 for p in gruppo if p.verso is not None and p.verso.value == "diretto"
                    ),
                    n_verso_inverso=sum(
                        1 for p in gruppo if p.verso is not None and p.verso.value == "inverso"
                    ),
                )
            )
        varianti.sort(
            key=lambda v: (
                v.rapporto is not RapportoItinerario.COMPLETO,
                -v.n_treni,
                v.itinerario.chiave,
            )
        )
        linee.append(
            Linea(
                estremo_a=a,
                estremo_b=b,
                nome=_nome(completo),
                n_treni=len(treni),
                varianti=tuple(varianti),
                categorie=tuple(Counter(p.categoria or "" for p in treni).most_common()),
                operatori=tuple(Counter(p.operatore or "" for p in treni).most_common()),
            )
        )
    linee.sort(key=lambda x: (-x.n_treni, x.chiave))
    return tuple(linee)


# --------------------------------------------------------------------------- archi aggregati


@dataclass(frozen=True)
class StatisticheArco:
    """Il tratto fra due stazioni consecutive, aggregato su piu' treni e nei due versi."""

    coppia: tuple[str, str]  # ordinata: la stessa nei due versi
    nome_a: str | None
    nome_b: str | None
    n_treni: int  # treni che lo percorrono (programmati, anche se poi soppressi)
    n_soppressi: int  # treni per cui una delle due fermate e' soppressa
    n_percorsi: int  # treni che lo hanno percorso davvero (hanno la durata effettiva)
    durata_programmata_mediana: float | None  # minuti
    durata_effettiva_mediana: float | None
    scarto_mediano: (
        float | None
    )  # effettiva - programmata, mediano: negativo = piu' veloce del previsto
    ritardo_accumulato_medio: float | None  # + se il ritardo cresce nel tratto, - se si recupera
    distanza_km: float | None
    velocita_programmata_kmh: float | None
    categorie: tuple[tuple[str, int], ...]


def _mediana(valori: list[float]) -> float | None:
    return statistics.median(valori) if valori else None


def aggrega_archi(
    profili: Iterable[ProfiloTreno], *, min_treni: int = 1
) -> tuple[StatisticheArco, ...]:
    """Statistiche per coppia di stazioni consecutive, sui profili dati.

    I due versi si sommano (`Arco.coppia`). Le durate sono mediane (robuste ai pochi valori
    anomali); il ritardo accumulato e' una media. Un arco con una fermata soppressa conta in
    `n_treni` e `n_soppressi` ma non nelle durate effettive. `min_treni` scarta le coppie viste
    da meno treni. Un solo giorno di dati non basta per parlare di un tratto "tipicamente lento".
    """
    prog: dict[tuple[str, str], list[float]] = defaultdict(list)
    eff: dict[tuple[str, str], list[float]] = defaultdict(list)
    scarti: dict[tuple[str, str], list[float]] = defaultdict(list)
    acc: dict[tuple[str, str], list[float]] = defaultdict(list)
    dist: dict[tuple[str, str], float] = {}
    n_treni: Counter[tuple[str, str]] = Counter()
    n_sopp: Counter[tuple[str, str]] = Counter()
    categorie: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    nomi: dict[str, str] = {}

    for p in profili:
        for a in p.archi:
            k = a.coppia
            n_treni[k] += 1
            categorie[k][p.categoria or ""] += 1
            nomi.setdefault(a.da.codice, a.da.nome)
            nomi.setdefault(a.a.codice, a.a.nome)
            if a.distanza_km is not None:
                dist[k] = a.distanza_km
            if a.soppresso:
                n_sopp[k] += 1
                continue
            dp, de = a.durata_programmata, a.durata_effettiva
            if dp is not None:
                prog[k].append(dp)
            if de is not None:
                eff[k].append(de)
                if dp is not None:
                    scarti[k].append(de - dp)
            if a.ritardo_accumulato is not None:
                acc[k].append(a.ritardo_accumulato)

    out: list[StatisticheArco] = []
    for k, n in n_treni.items():
        if n < min_treni:
            continue
        mp = _mediana(prog[k])
        d = dist.get(k)
        out.append(
            StatisticheArco(
                coppia=k,
                nome_a=nomi.get(k[0]),
                nome_b=nomi.get(k[1]),
                n_treni=n,
                n_soppressi=n_sopp[k],
                n_percorsi=len(eff[k]),
                durata_programmata_mediana=mp,
                durata_effettiva_mediana=_mediana(eff[k]),
                scarto_mediano=_mediana(scarti[k]),
                ritardo_accumulato_medio=statistics.fmean(acc[k]) if acc[k] else None,
                distanza_km=d,
                velocita_programmata_kmh=(d / (mp / 60)) if d is not None and mp else None,
                categorie=tuple(categorie[k].most_common()),
            )
        )
    out.sort(key=lambda s: (-s.n_treni, s.coppia))
    return tuple(out)
