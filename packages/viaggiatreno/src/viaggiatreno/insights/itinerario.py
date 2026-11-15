# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""`Itinerario`: la sequenza ordinata delle fermate di un treno, indipendente dal verso.

Si ricava da `andamentoTreno` (`TrainStatus.fermate`), non dai tabelloni. Le fermate
soppresse sono incluse di default: l'itinerario descrive il percorso *programmato*, quindi
uno stesso treno non cambia identita' quando una fermata viene soppressa.

Due treni dei due versi della stessa linea hanno lo stesso itinerario. Per questo l'itinerario
e' memorizzato in forma **canonica** (la piu' piccola, in ordine alfabetico dei codici, tra la
sequenza e la sua inversa) e il verso del singolo treno e' un dato a parte (`Verso`).

La forma canonica e' solo una convenzione per scegliere un estremo: non ha significato
geografico. Un itinerario palindromo (identico alla sua inversa) non ha verso determinabile:
sarebbe `Verso.DIRETTO`, ma sulla rete reale non e' mai stato osservato.

Un itinerario e' piu' preciso di una "linea" in senso comune: un regionale e un regionale
veloce sullo stesso asse hanno itinerari diversi, perche' saltano fermate diverse.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from viaggiatreno.insights.collegamento import Collegamento
from viaggiatreno.models.train import TrainStatus

SEPARATORE = ">"


class Verso(StrEnum):
    """Se un treno percorre l'itinerario nell'ordine canonico o al contrario."""

    DIRETTO = "diretto"
    INVERSO = "inverso"


@dataclass(frozen=True)
class Itinerario:
    """Fermate in ordine canonico. Costruirlo con `da_fermate`, `da_status` o `da_chiave`."""

    codici: tuple[str, ...]
    nomi: tuple[str | None, ...] = field(default=(), compare=False)

    def __post_init__(self) -> None:
        if len(self.codici) < 2:
            raise ValueError("un itinerario ha almeno due fermate")
        if self.nomi and len(self.nomi) != len(self.codici):
            raise ValueError("nomi e codici devono avere la stessa lunghezza")
        if self.codici > self.codici[::-1]:
            raise ValueError("forma non canonica: usare Itinerario.da_fermate()")

    @classmethod
    def da_fermate(
        cls, codici: Sequence[str], nomi: Sequence[str | None] | None = None
    ) -> tuple[Itinerario, Verso]:
        """Itinerario canonico e verso con cui la sequenza data lo percorre."""
        diretta = tuple(codici)
        if len(diretta) < 2:
            raise ValueError("un itinerario ha almeno due fermate")
        n = tuple(nomi) if nomi is not None else ()
        if n and len(n) != len(diretta):
            raise ValueError("nomi e codici devono avere la stessa lunghezza")
        if diretta <= diretta[::-1]:
            return cls(diretta, n), Verso.DIRETTO
        return cls(diretta[::-1], n[::-1]), Verso.INVERSO

    @classmethod
    def da_status(
        cls, status: TrainStatus, *, includi_soppresse: bool = True
    ) -> tuple[Itinerario, Verso] | None:
        """Itinerario di un treno. `None` se ha meno di due fermate (es. treno soppresso)."""
        # L'ordine dell'API, non il `progressivo`: in 58 treni su 10.328 il progressivo e' ripetuto
        # o non crescente e ordinare per quello mescola i tratti (orari che tornano indietro).
        fermate = list(status.fermate or [])
        if not includi_soppresse:
            fermate = [f for f in fermate if f.actualFermataType != 3]
        if len(fermate) < 2:
            return None
        return cls.da_fermate([f.id for f in fermate], [f.stazione for f in fermate])

    @classmethod
    def da_chiave(cls, chiave: str) -> Itinerario:
        """Inverso di `chiave`. I nomi non sono nella chiave."""
        itin, verso = cls.da_fermate(chiave.split(SEPARATORE))
        if verso is not Verso.DIRETTO:
            raise ValueError("chiave non canonica")
        return itin

    @property
    def chiave(self) -> str:
        """Identificativo stabile, es. `S01520>S01524>S01511`. Indipendente dal verso."""
        return SEPARATORE.join(self.codici)

    @property
    def estremo_a(self) -> str:
        return self.codici[0]

    @property
    def estremo_b(self) -> str:
        return self.codici[-1]

    @property
    def n_fermate(self) -> int:
        return len(self.codici)

    @property
    def nome(self) -> str:
        """Es. `LECCO - MILANO PORTA GARIBALDI`, altrimenti i codici degli estremi."""
        a = (self.nomi[0] if self.nomi else None) or self.estremo_a
        b = (self.nomi[-1] if self.nomi else None) or self.estremo_b
        return f"{a} - {b}"

    def __contains__(self, codice: object) -> bool:
        return codice in self.codici

    def collegamento(self, verso: Verso = Verso.DIRETTO) -> Collegamento:
        """Origine -> destinazione dell'itinerario nel verso indicato."""
        nome_a = self.nomi[0] if self.nomi else None
        nome_b = self.nomi[-1] if self.nomi else None
        if verso is Verso.DIRETTO:
            return Collegamento(self.estremo_a, self.estremo_b, nome_a, nome_b)
        return Collegamento(self.estremo_b, self.estremo_a, nome_b, nome_a)
