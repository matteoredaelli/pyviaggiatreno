# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""`Corsa`: una riga di tabellone (partenza o arrivo) di *una* stazione, normalizzata.

`TrainBoardItem` e' il record grezzo dell'API: e' lo stesso modello per `partenze` e `arrivi`,
non dice da quale dei due viene e ha campi diversi a seconda dell'endpoint (binario di
partenza o di arrivo, origine o destinazione, orario di partenza o di arrivo). `Corsa` li
riduce a un solo schema, cosi' le funzioni di analisi non devono conoscere l'API e possono
lavorare anche su dati letti da altrove (es. un database).

Termini usati nel pacchetto `insights`:

- **Corsa**: un treno visto sul tabellone di una stazione (questa classe);
- **Collegamento**: origine -> destinazione di un verso (`insights.collegamento`);
- **Itinerario**: la sequenza ordinata delle fermate di un treno (`insights.itinerario`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from viaggiatreno.models.train import TrainBoardItem


class TipoCorsa(StrEnum):
    """Da quale tabellone viene la corsa."""

    PARTENZA = "partenza"
    ARRIVO = "arrivo"


def normalizza_nome(nome: str | None) -> str | None:
    """Nome di stazione confrontabile: maiuscolo, spazi compattati. `None` se vuoto."""
    if nome is None:
        return None
    pulito = " ".join(nome.upper().split())
    return pulito or None


def _testo(valore: str | None) -> str | None:
    if valore is None:
        return None
    pulito = valore.strip()
    return pulito or None


def orario_ms(valore: int | str | None) -> int | None:
    """Orario in ms. In alcuni endpoint l'API da' una stringa data: non e' un orario."""
    return valore if isinstance(valore, int) and not isinstance(valore, bool) else None


@dataclass(frozen=True)
class Corsa:
    """Un treno sul tabellone di `stazione`, come partenza o come arrivo."""

    stazione: str
    tipo: TipoCorsa
    numero: int
    data: int | None  # `dataPartenzaTreno`: mezzanotte del giorno di partenza, ms
    origine_codice: str | None
    origine_nome: str | None
    destinazione_codice: str | None
    destinazione_nome: str | None
    orario: int | None  # programmato: partenza o arrivo a `stazione`, ms
    binario_programmato: str | None
    binario_effettivo: str | None
    categoria: str
    codice_cliente: int | None = None
    ritardo: int | None = None
    soppressa: bool = False  # provvedimento 1: cancellato
    parziale: bool = False  # provvedimento 2: parzialmente soppresso, deviato o riprogrammato

    @property
    def binari(self) -> tuple[str, ...]:
        """I binari noti di questa corsa (programmato ed effettivo), senza duplicati.

        Non c'e' un "binario della corsa": il programmato dice come la stazione e' organizzata,
        l'effettivo cosa e' successo. Chi analizza sceglie quale usare, o li usa entrambi.
        """
        visti = [b for b in (self.binario_programmato, self.binario_effettivo) if b]
        return tuple(dict.fromkeys(visti))

    @property
    def binario_cambiato(self) -> bool:
        """True se il binario effettivo e' noto e diverso dal programmato (cambio di binario)."""
        return (
            self.binario_effettivo is not None
            and self.binario_programmato is not None
            and self.binario_effettivo != self.binario_programmato
        )

    @property
    def chiave(self) -> tuple[int, str | None, int | None]:
        """Identita' del treno: lo stesso numero puo' esistere con origini e giorni diversi."""
        return (self.numero, self.origine_codice, self.data)


def da_tabellone(items: Iterable[TrainBoardItem], stazione: str, tipo: TipoCorsa) -> list[Corsa]:
    """Converte le righe di un tabellone di `stazione` in `Corsa`.

    `tipo` dice se `items` viene da `partenze` o da `arrivi`. Nelle partenze l'API da' la
    destinazione (di solito solo il nome, il codice e' spesso assente) e il codice di origine;
    negli arrivi da' l'origine (nome e codice) e, stando alla documentazione, destinazione
    `null`: se invece c'e', viene letta.
    """
    corse: list[Corsa] = []
    for it in items:
        if tipo is TipoCorsa.PARTENZA:
            orario = orario_ms(it.orarioPartenza)
            prog = _testo(it.binarioProgrammatoPartenzaDescrizione)
            eff = _testo(it.binarioEffettivoPartenzaDescrizione)
            dest_cod, dest_nome = _testo(it.codDestinazione), _testo(it.destinazione)
        else:
            orario = orario_ms(it.orarioArrivo)
            prog = _testo(it.binarioProgrammatoArrivoDescrizione)
            eff = _testo(it.binarioEffettivoArrivoDescrizione)
            # la documentazione la da' `null` negli arrivi (campione di Milano Centrale):
            # se un giorno l'API la fornisce, la si usa
            dest_cod, dest_nome = _testo(it.codDestinazione), _testo(it.destinazione)
        corse.append(
            Corsa(
                stazione=stazione,
                tipo=tipo,
                numero=it.numeroTreno,
                data=it.dataPartenzaTreno,
                origine_codice=_testo(it.codOrigine),
                origine_nome=_testo(it.origine),
                destinazione_codice=dest_cod,
                destinazione_nome=dest_nome,
                orario=orario,
                binario_programmato=prog,
                binario_effettivo=eff,
                categoria=_testo(it.categoria) or _testo(it.categoriaDescrizione) or "",
                codice_cliente=it.codiceCliente,
                ritardo=it.ritardo,
                soppressa=it.provvedimento == 1,
                parziale=it.provvedimento == 2,
            )
        )
    return corse
