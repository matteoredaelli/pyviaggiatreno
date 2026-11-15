# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""`Collegamento`: origine -> destinazione di un *verso*, senza fermate intermedie.

E' quello che un tabellone permette di ricavare ("Lecco -> Milano Porta Garibaldi"). Non dice
per dove passa il treno: per questo serve l'`Itinerario` (da `andamentoTreno`).

Due collegamenti opposti (A->B e B->A) sono distinti; `coppia` li riunisce.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from viaggiatreno.insights.corsa import normalizza_nome


def _id(codice: str | None, nome: str | None) -> str:
    """Identita' di un estremo: il codice, altrimenti il nome normalizzato."""
    ident = codice or normalizza_nome(nome)
    if not ident:
        raise ValueError("un estremo del collegamento richiede un codice o un nome")
    return ident


@dataclass(frozen=True, eq=False)
class Collegamento:
    """Origine -> destinazione. L'uguaglianza usa il codice (o, in mancanza, il nome)."""

    origine_codice: str | None
    destinazione_codice: str | None
    origine_nome: str | None = field(default=None)
    destinazione_nome: str | None = field(default=None)

    def __post_init__(self) -> None:
        _id(self.origine_codice, self.origine_nome)
        _id(self.destinazione_codice, self.destinazione_nome)

    @property
    def chiave(self) -> tuple[str, str]:
        return (
            _id(self.origine_codice, self.origine_nome),
            _id(self.destinazione_codice, self.destinazione_nome),
        )

    @property
    def coppia(self) -> tuple[str, str]:
        """Chiave indipendente dal verso: A->B e B->A hanno la stessa coppia."""
        a, b = self.chiave
        return (a, b) if a <= b else (b, a)

    def inverso(self) -> Collegamento:
        return Collegamento(
            origine_codice=self.destinazione_codice,
            destinazione_codice=self.origine_codice,
            origine_nome=self.destinazione_nome,
            destinazione_nome=self.origine_nome,
        )

    @property
    def etichetta(self) -> str:
        o = self.origine_nome or self.origine_codice
        d = self.destinazione_nome or self.destinazione_codice
        return f"{o} -> {d}"

    def __eq__(self, altro: object) -> bool:
        return isinstance(altro, Collegamento) and self.chiave == altro.chiave

    def __hash__(self) -> int:
        return hash(self.chiave)
