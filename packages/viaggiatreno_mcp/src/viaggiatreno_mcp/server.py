# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Server MCP FastMCP per ViaggiaTreno."""

import sys

from fastmcp import FastMCP
from viaggiatreno import ViaggiaTrenoClient

from viaggiatreno_mcp.tools import register_all_tools


def create_server(client: ViaggiaTrenoClient | None = None) -> FastMCP:
    """Inizializza e configura l'istanza FastMCP con tutti i tool ViaggiaTreno."""
    mcp = FastMCP(
        name="ViaggiaTreno MCP",
        instructions=(
            "Server MCP per l'interrogazione in tempo reale della rete ferroviaria italiana "
            "tramite le API non ufficiali di ViaggiaTreno. Permette di cercare stazioni, consultare "
            "tabelloni partenze e arrivi in tempo reale, monitorare l'andamento e i ritardi dei treni, "
            "controllare lo stato delle tratte e leggere le notizie di infomobilità."
        ),
    )
    api_client = client or ViaggiaTrenoClient()
    register_all_tools(mcp, api_client)
    return mcp


# Istanza predefinita del server
mcp = create_server()


def main() -> None:
    """Punto di ingresso CLI per eseguire il server MCP."""
    try:
        mcp.run()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
