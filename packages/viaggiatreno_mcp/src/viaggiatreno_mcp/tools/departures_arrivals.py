"""Tool MCP per tabelloni partenze e arrivi nelle stazioni."""

from fastmcp import FastMCP
from viaggiatreno import TrainBoardItem, ViaggiaTrenoClient


def register_departure_arrival_tools(mcp: FastMCP, client: ViaggiaTrenoClient) -> None:
    """Registra i tool relativi a partenze e arrivi sul server FastMCP."""

    @mcp.tool(
        name="tabellone_partenze",
        description=(
            "Restituisce il tabellone delle partenze in tempo reale per una stazione ferroviaria "
            "(es. 'S01700' per Milano Centrale, 'S08409' per Roma Termini). "
            "Fornisce: treni in partenza, destinazione, orario programmato, ritardo in minuti, binario programmato ed effettivo, "
            "stato di circolazione e codice origine/data per ulteriori approfondimenti."
        ),
    )
    async def tabellone_partenze(
        codice_stazione: str,
        data_ora: str | None = None,
    ) -> list[TrainBoardItem]:
        return await client.partenze(codice_stazione, data_ora)

    @mcp.tool(
        name="tabellone_arrivi",
        description=(
            "Restituisce il tabellone degli arrivi in tempo reale per una stazione ferroviaria "
            "(es. 'S01700' per Milano Centrale). "
            "Fornisce: treni in arrivo, stazione di provenienza, orario programmato, ritardo in minuti, binario programmato ed effettivo, "
            "e se il treno è già giunto in stazione."
        ),
    )
    async def tabellone_arrivi(
        codice_stazione: str,
        data_ora: str | None = None,
    ) -> list[TrainBoardItem]:
        return await client.arrivi(codice_stazione, data_ora)

    @mcp.tool(
        name="treni_diretti_tra_stazioni",
        description=(
            "Restituisce i treni DIRETTI (senza cambi) tra due stazioni nella giornata corrente "
            "(es. da 'S01700' Milano Centrale a 'S06421' Firenze Santa Maria Novella). "
            "Non gestisce percorsi che richiedono un interscambio: in tal caso la lista può risultare vuota "
            "anche se un collegamento con cambio esiste. Endpoint non documentato nelle fonti note, trovato "
            "nello script ufficiale del sito ViaggiaTreno e verificato dal vivo."
        ),
    )
    async def treni_diretti_tra_stazioni(
        id_stazione_da: str,
        id_stazione_a: str,
    ) -> list[TrainBoardItem]:
        return await client.dettaglio_viaggio(id_stazione_da, id_stazione_a)
