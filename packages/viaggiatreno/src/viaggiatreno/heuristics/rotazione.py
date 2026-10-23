"""Euristica per trovare il "predecessore" di un treno su una linea a spola
(stesso materiale rotabile che fa avanti/indietro, es. Lecco <-> Milano
Porta Garibaldi sulla S8).

Nessuna API di ViaggiaTreno espone un collegamento esplicito tra una corsa e
il "giro precedente" dello stesso treno fisico (concetto diverso dal "cambio
numero" documentato in VIAGGIATRENO.md, che riguarda una singola corsa che
cambia numero a meta' percorso, non la rotazione ai capolinea). Il
predecessore viene quindi stimato per prossimita' temporale: l'arrivo più
recente alla stazione di origine di questo treno, stesso operatore, entro
una finestra di turnaround configurabile.

Verificato dal vivo (23/10/2026, Lecco): gli arrivi da Milano Porta Garibaldi
(24856@16:54, 24858@17:24, ...) precedono sistematicamente le partenze verso
Milano Porta Garibaldi (24865@17:06, 24867@17:36, ...) di 12 minuti esatti,
confermando che l'euristica per tempo e' affidabile per questa linea.
"""

from __future__ import annotations

from dataclasses import dataclass

from viaggiatreno.api.client import ViaggiaTrenoClient
from viaggiatreno.models.train import TrainBoardItem, TrainStatus


@dataclass(frozen=True)
class Predecessore:
    """Esito della ricerca del probabile predecessore di un treno."""

    treno_numero: int
    treno_origine: str | None
    treno_orario_partenza_programmato: int | None
    predecessore_numero: int
    predecessore_origine: str | None
    predecessore_orario_arrivo_programmato: int | None
    minuti_turnaround: float
    predecessore_ritardo_attuale: int | None
    predecessore_arrivato: bool | None
    predecessore_stato_treno: str | None


async def _candidati_predecessori(
    client: ViaggiaTrenoClient, stazione: str, categoria: str | None, codice_cliente: int | None
) -> list[TrainBoardItem]:
    arrivi = await client.arrivi(stazione)
    return [
        t
        for t in arrivi
        if t.orarioArrivo is not None
        and (codice_cliente is None or t.codiceCliente == codice_cliente)
        and (categoria is None or t.categoria == categoria)
    ]


async def trova_predecessore(
    client: ViaggiaTrenoClient,
    cod_origine: str,
    numero_treno: int,
    data_partenza: int | str,
    finestra_minuti: int = 60,
    richiedi_stessa_linea: bool = True,
) -> Predecessore | None:
    """Trova il probabile predecessore (stesso materiale rotabile) di un treno.

    Cerca, tra gli arrivi alla stazione di origine di `numero_treno`, quello
    con l'orario di arrivo programmato più vicino (ma precedente) all'orario
    di partenza di `numero_treno`, entro `finestra_minuti`. Restituisce
    `None` se non trova candidati plausibili (nessun arrivo recente dello
    stesso operatore in quella finestra) o se il treno non esiste/è soppresso
    (`andamento_treno` risponde 204).

    `richiedi_stessa_linea=True` (default) impone che il candidato arrivi
    **dalla stessa stazione verso cui `numero_treno` sta partendo**: è
    l'ipotesi che sia lo stesso convoglio che torna indietro sulla stessa
    rotta (spola). **Necessario nei nodi di interscambio con più linee**:
    verificato dal vivo che senza questo filtro, a Milano Porta Garibaldi
    (dove convergono sia la linea per Lecco sia quella per Como/Chiasso),
    l'euristica sceglieva un treno della linea sbagliata (un arrivo da Lecco
    invece che da Como, solo perché più vicino nel tempo). Disattivarlo solo
    per stazioni capolinea di una singola linea, dove non serve e un vincolo
    di destinazione esatta potrebbe escludere varianti di nome stazione.
    """
    status: TrainStatus | None = await client.andamento_treno(cod_origine, numero_treno, data_partenza)
    if status is None or status.orarioPartenza is None or not isinstance(status.orarioPartenza, int):
        return None

    stazione_origine = status.idOrigine or cod_origine
    candidati = await _candidati_predecessori(
        client, stazione_origine, status.categoria, status.codiceCliente
    )

    finestra_ms = finestra_minuti * 60 * 1000
    migliori = [
        t
        for t in candidati
        if t.orarioArrivo is not None
        and t.orarioArrivo < status.orarioPartenza
        and (status.orarioPartenza - t.orarioArrivo) <= finestra_ms
        and t.numeroTreno != numero_treno
        and (
            not richiedi_stessa_linea
            or (
                status.destinazione is not None
                and t.origine is not None
                and status.destinazione.strip().upper() == t.origine.strip().upper()
            )
        )
    ]
    if not migliori:
        return None

    predecessore = max(migliori, key=lambda t: t.orarioArrivo or 0)
    turnaround_min = (status.orarioPartenza - (predecessore.orarioArrivo or 0)) / 60000

    return Predecessore(
        treno_numero=numero_treno,
        treno_origine=status.origine,
        treno_orario_partenza_programmato=status.orarioPartenza,
        predecessore_numero=predecessore.numeroTreno,
        predecessore_origine=predecessore.origine,
        predecessore_orario_arrivo_programmato=predecessore.orarioArrivo,
        minuti_turnaround=turnaround_min,
        predecessore_ritardo_attuale=predecessore.ritardo,
        predecessore_arrivato=predecessore.arrivato,
        predecessore_stato_treno=None,
    )


async def verifica_predecessore(
    client: ViaggiaTrenoClient,
    cod_origine: str,
    numero_treno: int,
    data_partenza: int | str,
    finestra_minuti: int = 60,
    richiedi_stessa_linea: bool = True,
) -> Predecessore | None:
    """Come `trova_predecessore`, ma arricchisce il risultato interrogando
    `andamento_treno` sul predecessore per avere lo stato di circolazione
    più preciso (es. 'PG' regolare, 'ST' soppresso) oltre al semplice ritardo
    del tabellone arrivi.
    """
    predecessore = await trova_predecessore(
        client, cod_origine, numero_treno, data_partenza, finestra_minuti, richiedi_stessa_linea
    )
    if predecessore is None:
        return None

    status_predecessore = await client.andamento_treno(
        cod_origine, predecessore.predecessore_numero, data_partenza
    )
    if status_predecessore is None:
        return predecessore

    return Predecessore(
        **{
            **predecessore.__dict__,
            "predecessore_ritardo_attuale": status_predecessore.ritardo,
            "predecessore_arrivato": status_predecessore.arrivato,
            "predecessore_stato_treno": status_predecessore.tipoTreno,
        }
    )
