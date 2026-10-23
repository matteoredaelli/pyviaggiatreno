# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test di integrazione per i tool MCP registrati su FastMCP."""

import pytest
from fastmcp import FastMCP


@pytest.mark.asyncio
async def test_tools_stations(mock_server: FastMCP):
    # Autocompleta stazione
    res = await mock_server.call_tool("autocompleta_stazione", {"prefisso": "firenze"})
    assert not res.is_error

    # Cerca stazione
    res = await mock_server.call_tool("cerca_stazione", {"prefisso": "apice"})
    assert not res.is_error

    # Dettaglio stazione con auto-recupero regione
    res = await mock_server.call_tool("dettaglio_stazione", {"codice_stazione": "S01700"})
    assert not res.is_error

    # Elenco stazioni
    res = await mock_server.call_tool("elenco_stazioni_regione", {"codice_regione": 1})
    assert not res.is_error

    # Codice regione
    res = await mock_server.call_tool("codice_regione_stazione", {"codice_stazione": "S01700"})
    assert not res.is_error

    # Autocompleta NTS
    res = await mock_server.call_tool("autocompleta_stazione_nts", {"prefisso": "firenze"})
    assert not res.is_error


@pytest.mark.asyncio
async def test_tools_departures_arrivals(mock_server: FastMCP):
    partenze = await mock_server.call_tool("tabellone_partenze", {"codice_stazione": "S01700"})
    assert not partenze.is_error

    arrivi = await mock_server.call_tool("tabellone_arrivi", {"codice_stazione": "S01700"})
    assert not arrivi.is_error


@pytest.mark.asyncio
async def test_tools_trains(mock_server: FastMCP):
    # Cerca numero treno
    cerca = await mock_server.call_tool("cerca_numero_treno", {"numero_treno": 9611})
    assert not cerca.is_error

    # Stato treno con auto-risoluzione di origine e dataPartenza
    stato = await mock_server.call_tool("stato_treno", {"numero_treno": 9611})
    assert not stato.is_error

    # Itinerario canvas
    canvas = await mock_server.call_tool(
        "itinerario_treno_canvas",
        {
            "codice_stazione_origine": "S00219",
            "numero_treno": 9611,
            "data_partenza": 1791064800000,
        },
    )
    assert not canvas.is_error

    # Predecessore treno (euristica): non deve fallire anche se l'arrivo/partenza
    # mock non e' quella di una vera linea a spola (ci si aspetta risultato null)
    predecessore = await mock_server.call_tool("predecessore_treno", {"numero_treno": 9611})
    assert not predecessore.is_error


@pytest.mark.asyncio
async def test_tools_routes(mock_server: FastMCP):
    tratte = await mock_server.call_tool("elenco_tratte_ferroviarie", {})
    assert not tratte.is_error

    treni = await mock_server.call_tool(
        "treni_su_tratta",
        {"tratta_ab": 510, "tratta_ba": 511},
    )
    assert not treni.is_error


@pytest.mark.asyncio
async def test_tools_service(mock_server: FastMCP):
    stats = await mock_server.call_tool("statistiche_servizio", {})
    assert not stats.is_error

    notizie = await mock_server.call_tool("notizie_infomobilita", {"solo_lavori": False})
    assert not notizie.is_error

    titoli = await mock_server.call_tool("titoli_infomobilita", {"solo_lavori": False})
    assert not titoli.is_error

    ticker = await mock_server.call_tool("ticker_infomobilita", {})
    assert not ticker.is_error

    meteo = await mock_server.call_tool("meteo_stazioni", {"codice_regione": 1})
    assert not meteo.is_error

    lingua = await mock_server.call_tool("dizionario_lingua", {"id_lingua": "it"})
    assert not lingua.is_error
