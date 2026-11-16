# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tool MCP per le analisi (`viaggiatreno.insights`): profilo di una stazione e di un treno."""

from fastmcp import FastMCP
from viaggiatreno import ViaggiaTrenoClient
from viaggiatreno.insights import ProfiloStazione, ProfiloTreno, profilo_stazione, profilo_treno


def register_insights_tools(mcp: FastMCP, client: ViaggiaTrenoClient) -> None:
    """Registra i tool di analisi sul server FastMCP."""

    @mcp.tool(
        name="profilo_stazione",
        description=(
            "Analisi di una stazione dai tabelloni di partenze e arrivi di adesso (o di data_ora, "
            "formato ISO): anagrafica (nome, citta', regione, coordinate), ruolo (capolinea, "
            "transito, mista), numero di treni e cancellati, frequenza (treni all'ora, intervalli, "
            "regolarita'), binari programmati ed effettivi con i collegamenti che vi passano, "
            "e i collegamenti origine -> destinazione con la loro frequenza. "
            "E' una fotografia della finestra dei tabelloni (poche ore), non uno storico. "
            "Fa 4 richieste (partenze, arrivi, regione, dettaglio); con con_dettaglio=false 2."
        ),
    )
    async def profilo_stazione_tool(
        codice_stazione: str,
        data_ora: str | None = None,
        con_dettaglio: bool = True,
    ) -> ProfiloStazione:
        return await profilo_stazione(
            client, codice_stazione, data_ora=data_ora, con_dettaglio=con_dettaglio
        )

    @mcp.tool(
        name="profilo_treno",
        description=(
            "Analisi di un treno da andamentoTreno: stato (regolare, soppresso, parziale), "
            "avanzamento, itinerario programmato, fermate nell'ordine di marcia con orari e binari "
            "programmati/effettivi, archi tra fermate consecutive (tempi di percorrenza, ritardo "
            "accumulato, soste), collegamento programmato ed effettivo e anomalie. "
            "Se codice_stazione_origine e data_partenza mancano si ricavano dal numero di treno. "
            "Restituisce null se l'API non ha il treno (prima della partenza o dopo il reset notturno)."
        ),
    )
    async def profilo_treno_tool(
        numero_treno: int,
        codice_stazione_origine: str | None = None,
        data_partenza: int | None = None,
    ) -> ProfiloTreno | None:
        if not codice_stazione_origine or not data_partenza:
            info = await client.cerca_numero_treno(numero_treno)
            if info is not None:
                codice_stazione_origine = info.codLocOrig
                try:
                    data_partenza = int(info.millisDataPartenza)
                except (ValueError, TypeError):
                    pass
            else:
                corse = await client.cerca_numero_treno_autocomplete(numero_treno)
                if corse:
                    codice_stazione_origine = corse[0].codice_stazione_origine
                    data_partenza = corse[0].millis_data_partenza
        if not codice_stazione_origine or not data_partenza:
            return None
        return await profilo_treno(client, codice_stazione_origine, numero_treno, data_partenza)
