# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Package tools per ViaggiaTreno MCP."""

from fastmcp import FastMCP
from viaggiatreno import ViaggiaTrenoClient

from viaggiatreno_mcp.tools.departures_arrivals import register_departure_arrival_tools
from viaggiatreno_mcp.tools.routes import register_route_tools
from viaggiatreno_mcp.tools.service import register_service_tools
from viaggiatreno_mcp.tools.stations import register_station_tools
from viaggiatreno_mcp.tools.trains import register_train_tools


def register_all_tools(mcp: FastMCP, client: ViaggiaTrenoClient) -> None:
    """Registra tutti i tool MCP modulari sull'istanza del server FastMCP."""
    register_station_tools(mcp, client)
    register_departure_arrival_tools(mcp, client)
    register_train_tools(mcp, client)
    register_route_tools(mcp, client)
    register_service_tools(mcp, client)


__all__ = [
    "register_all_tools",
    "register_departure_arrival_tools",
    "register_route_tools",
    "register_service_tools",
    "register_station_tools",
    "register_train_tools",
]
