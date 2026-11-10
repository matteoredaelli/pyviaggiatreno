# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tool MCP per la gestione e ricerca delle stazioni ferroviarie."""

from fastmcp import FastMCP
from viaggiatreno import (
    StationAutocompleteItem,
    StationDetail,
    StationNTSAutocompleteItem,
    StationSearchResult,
    ViaggiaTrenoClient,
)


def register_station_tools(mcp: FastMCP, client: ViaggiaTrenoClient) -> None:
    """Registra i tool relativi alle stazioni sul server FastMCP."""

    @mcp.tool(
        name="autocompleta_stazione",
        description=(
            "Suggerisce stazioni ferroviarie per prefisso del nome (es. 'firenze', 'milano'). "
            "Restituisce nome esteso e codice stazione (es. S01700 per Milano Centrale). "
            "È l'endpoint consigliato per ottenere i codici stazione da usare nei tabelloni e nei dettagli."
        ),
    )
    async def autocompleta_stazione(prefisso: str) -> list[StationAutocompleteItem]:
        return await client.autocompleta_stazione(prefisso)

    @mcp.tool(
        name="cerca_stazione",
        description=(
            "Cerca stazioni il cui nome inizia con la stringa specificata. "
            "Restituisce informazioni anagrafiche strutturate (id stazione, nome lungo, nome breve, etichetta/città)."
        ),
    )
    async def cerca_stazione(prefisso: str) -> list[StationSearchResult]:
        return await client.cerca_stazione(prefisso)

    @mcp.tool(
        name="dettaglio_stazione",
        description=(
            "Restituisce i dettagli completi di una stazione ferroviaria: coordinate geografiche (latitudine/longitudine), "
            "città, regione e tipologia. Se codice_regione non viene fornito, viene recuperato automaticamente."
        ),
    )
    async def dettaglio_stazione(
        codice_stazione: str,
        codice_regione: int | None = None,
    ) -> StationDetail | None:
        if codice_regione is None:
            codice_regione = await client.regione(codice_stazione)
            if codice_regione is None:
                codice_regione = 1  # Fallback predefinito se non determinabile
        return await client.dettaglio_stazione(codice_stazione, codice_regione)

    @mcp.tool(
        name="elenco_stazioni_regione",
        description=(
            "Restituisce l'elenco di tutte le stazioni ferroviarie appartenenti a una specifica regione "
            "(1=Lombardia, 2=Liguria, 3=Piemonte, 5=Lazio, 8=Emilia Romagna, 13=Toscana, 0=Stazioni principali italiane, ecc.) "
            "con le relative coordinate geografiche."
        ),
    )
    async def elenco_stazioni_regione(codice_regione: int) -> list[StationDetail]:
        return await client.elenco_stazioni(codice_regione)

    @mcp.tool(
        name="codice_regione_stazione",
        description=(
            "Restituisce il codice numerico di regione associato a una determinata stazione (es. 'S01700' -> 1 Lombardia)."
        ),
    )
    async def codice_regione_stazione(codice_stazione: str) -> int | None:
        return await client.regione(codice_stazione)

    @mcp.tool(
        name="autocompleta_stazione_nts",
        description=(
            "Autocompletamento di stazioni e nodi tecnici ferroviari (bivi BIVIO, deviazioni DEV., posti di comunicazione PC) "
            "con codici RICS a 9-11 cifre (iniziano con 83...). "
            "Nota: questi codici NTS non vanno usati con gli altri endpoint ordinari."
        ),
    )
    async def autocompleta_stazione_nts(
        prefisso: str,
    ) -> list[StationNTSAutocompleteItem]:
        return await client.autocompleta_stazione_nts(prefisso)
