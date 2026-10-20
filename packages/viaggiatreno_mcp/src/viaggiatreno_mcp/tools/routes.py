"""Tool MCP per le tratte ferroviarie e il monitoraggio della rete."""

from fastmcp import FastMCP
from viaggiatreno import DettaglioTratta, TrattaSegment, ViaggiaTrenoClient


def register_route_tools(mcp: FastMCP, client: ViaggiaTrenoClient) -> None:
    """Registra i tool relativi a tratte e rete ferroviaria sul server FastMCP."""

    @mcp.tool(
        name="elenco_tratte_ferroviarie",
        description=(
            "Restituisce i segmenti della rete ferroviaria (coppie di nodi ferroviari con coordinate geografiche) "
            "e l'indicazione se ciascun segmento è attualmente occupato da almeno un treno in viaggio. "
            "Le categorie filtrabili (separate da virgola) includono: 'ES*,IC,EXP,EC,EN,REG'. "
            "id_regione filtra i segmenti per area geografica (0=tutta Italia, 1-22=singola regione, stesso codice "
            "di elenco_stazioni/regione): attenzione, filtra i segmenti non i treni, quindi un segmento di confine "
            "regionale può comunque restituire treni di lunga percorrenza che solo transitano in quell'area. "
            "Gli ID tratta_ab/tratta_ba restituiti sono numerati per regione: vanno riusati con lo stesso id_regione "
            "in treni_su_tratta, altrimenti si ottengono i treni di un segmento fisicamente diverso."
        ),
    )
    async def elenco_tratte_ferroviarie(
        categorie: str = "ES*,IC,EXP,EC,EN,REG",
        id_regione: int = 0,
    ) -> list[TrattaSegment]:
        return await client.elenco_tratte(categorie=categorie, id_regione=id_regione)

    @mcp.tool(
        name="treni_su_tratta",
        description=(
            "Restituisce i treni attualmente in circolazione su uno specifico segmento di tratta ferroviaria. "
            "Richiede gli identificativi numerici nei due sensi (tratta_ab e tratta_ba) e lo stesso id_regione usati "
            "nella chiamata a elenco_tratte_ferroviarie che li ha prodotti: gli ID sono numerati per regione, non sono "
            "identificativi globali della rete."
        ),
    )
    async def treni_su_tratta(
        tratta_ab: int,
        tratta_ba: int,
        categorie: str = "ES*,IC,EXP,EC,EN,REG",
        id_regione: int = 0,
    ) -> list[DettaglioTratta]:
        return await client.dettagli_tratta(
            tratta_ab=tratta_ab,
            tratta_ba=tratta_ba,
            categorie=categorie,
            id_regione=id_regione,
        )
