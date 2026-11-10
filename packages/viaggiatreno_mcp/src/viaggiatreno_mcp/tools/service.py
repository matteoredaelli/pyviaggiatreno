# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tool MCP per informazioni di servizio: statistiche, infomobilità, meteo e dizionario lingue."""

from fastmcp import FastMCP
from viaggiatreno import (
    InfomobilitaNews,
    InfomobilitaNewsHeadline,
    StationWeather,
    Statistics,
    ViaggiaTrenoClient,
)


def register_service_tools(mcp: FastMCP, client: ViaggiaTrenoClient) -> None:
    """Registra i tool per informazioni di servizio e infomobilità sul server FastMCP."""

    @mcp.tool(
        name="statistiche_servizio",
        description=(
            "Restituisce le statistiche della rete ferroviaria nazionale in tempo reale: "
            "numero complessivo di treni programmati per la data odierna e numero di treni attualmente in circolazione."
        ),
    )
    async def statistiche_servizio() -> Statistics | None:
        return await client.statistiche()

    @mcp.tool(
        name="notizie_infomobilita",
        description=(
            "Restituisce le notizie dettagliate di infomobilità in tempo reale: avvisi sulla circolazione, "
            "ritardi eccezionali, guasti, modifiche di percorso o scioperi. "
            "Impostare solo_lavori=True per ottenere l'elenco dei lavori programmati."
        ),
    )
    async def notizie_infomobilita(
        solo_lavori: bool = False,
    ) -> list[InfomobilitaNews]:
        return await client.infomobilita_rss(is_info_lavori=solo_lavori)

    @mcp.tool(
        name="titoli_infomobilita",
        description=(
            "Restituisce i soli titoli sintetici degli avvisi di infomobilità o dei lavori programmati "
            "(versione compatta per panoramica rapida)."
        ),
    )
    async def titoli_infomobilita(
        solo_lavori: bool = False,
    ) -> list[InfomobilitaNewsHeadline]:
        return await client.infomobilita_rss_box(is_info_lavori=solo_lavori)

    @mcp.tool(
        name="ticker_infomobilita",
        description=(
            "Restituisce gli avvisi brevi scorrevoli della striscia informativa del portale ViaggiaTreno."
        ),
    )
    async def ticker_infomobilita() -> list[str]:
        return await client.infomobilita_ticker()

    @mcp.tool(
        name="meteo_stazioni",
        description=(
            "Restituisce le previsioni meteo per le stazioni di una specifica regione (es. 1=Lombardia, 13=Toscana). "
            "Nota: l'API ufficiale potrebbe restituire un insieme vuoto per alcune regioni se il dato non è disponibile."
        ),
    )
    async def meteo_stazioni(
        codice_regione: int,
    ) -> dict[str, StationWeather]:
        return await client.datimeteo(codice_regione)

    @mcp.tool(
        name="dizionario_lingua",
        description=(
            "Restituisce il dizionario delle traduzioni delle stringhe dell'interfaccia ViaggiaTreno. "
            "Lingue supportate: 'it', 'en', 'de', 'fr', 'sp', 'ro', 'jp', 'zh', 'ru'."
        ),
    )
    async def dizionario_lingua(
        id_lingua: str = "it",
    ) -> dict[str, str]:
        return await client.language(id_lingua)
