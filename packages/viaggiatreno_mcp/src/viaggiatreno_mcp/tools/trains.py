"""Tool MCP per lo stato, la ricerca e l'itinerario dei treni."""

from fastmcp import FastMCP
from viaggiatreno import (
    Predecessore,
    TrainAutocompleteItem,
    TrainSearchResult,
    TrainStatus,
    TrattaCanvasItem,
    ViaggiaTrenoClient,
    verifica_predecessore,
)


def register_train_tools(mcp: FastMCP, client: ViaggiaTrenoClient) -> None:
    """Registra i tool relativi ai treni sul server FastMCP."""

    @mcp.tool(
        name="cerca_numero_treno",
        description=(
            "Cerca le corse attive associate a un numero di treno (es. 9611). "
            "Restituisce i dati identificativi essenziali: stazione di origine, data di partenza "
            "e millisecondi da passare a stato_treno o itinerario_treno_canvas."
        ),
    )
    async def cerca_numero_treno(
        numero_treno: int,
    ) -> list[TrainAutocompleteItem] | TrainSearchResult | None:
        # Tenta prima la ricerca strutturata con singola corsa
        single = await client.cerca_numero_treno(numero_treno)
        if single is not None:
            return single
        # In alternativa, elenca tutte le corse (es. per disambiguare)
        multiple = await client.cerca_numero_treno_autocomplete(numero_treno)
        return multiple if multiple else None

    @mcp.tool(
        name="stato_treno",
        description=(
            "Restituisce lo andamento e lo stato in tempo reale di un treno: ritardo attuale, "
            "ultimo rilevamento con stazione e orario, stato di marcia (regolare, soppresso, parzialmente soppresso), "
            "e l'elenco completo di tutte le fermate commerciali con orario programmato, orario effettivo e binari. "
            "Se codice_stazione_origine e data_partenza non vengono forniti, vengono determinati automaticamente "
            "tramite il numero di treno."
        ),
    )
    async def stato_treno(
        numero_treno: int,
        codice_stazione_origine: str | None = None,
        data_partenza: int | None = None,
    ) -> TrainStatus | None:
        # Se mancano stazione di origine o timestamp di mezzanotte, li risolviamo automaticamente
        if not codice_stazione_origine or not data_partenza:
            info = await client.cerca_numero_treno(numero_treno)
            if info is not None:
                codice_stazione_origine = info.codLocOrig
                try:
                    data_partenza = int(info.millisDataPartenza)
                except (ValueError, TypeError):
                    pass
            else:
                # Prova con l'autocompletamento corse
                corse = await client.cerca_numero_treno_autocomplete(numero_treno)
                if corse:
                    codice_stazione_origine = corse[0].codice_stazione_origine
                    data_partenza = corse[0].millis_data_partenza

        if not codice_stazione_origine or not data_partenza:
            return None

        return await client.andamento_treno(
            codice_stazione_origine=codice_stazione_origine,
            numero_treno=numero_treno,
            data_partenza=data_partenza,
        )

    @mcp.tool(
        name="itinerario_treno_canvas",
        description=(
            "Restituisce la rappresentazione visuale ad albero (tratteCanvas) dell'itinerario del treno, "
            "indicando fermata per fermata se la partenza o l'arrivo sono già avvenuti e se il treno è fermo in stazione."
        ),
    )
    async def itinerario_treno_canvas(
        codice_stazione_origine: str,
        numero_treno: int,
        data_partenza: int,
    ) -> list[TrattaCanvasItem]:
        return await client.tratte_canvas(
            codice_stazione_origine=codice_stazione_origine,
            numero_treno=numero_treno,
            data_partenza=data_partenza,
        )

    @mcp.tool(
        name="predecessore_treno",
        description=(
            "Stima il treno 'predecessore' su una linea a spola/suburbana (stesso materiale rotabile che fa "
            "avanti e indietro, es. linee S): se il predecessore è in ritardo, è probabile che questo treno "
            "lo sarà anch'esso, prima ancora che il sito mandi un avviso. ATTENZIONE: è una stima per prossimità "
            "temporale (arrivo più recente alla stessa stazione, stesso operatore, stessa linea), non un dato "
            "certo dell'API. Funziona bene su linee a spola ad alta frequenza (verificato su S8 Lecco-Milano "
            "Porta Garibaldi e sulla Como/Chiasso-Milano Porta Garibaldi); NON è adatta a linee regionali a "
            "lunga percorrenza con poche corse al giorno (es. Milano Centrale-Tirano), dove restituirà `null` "
            "o un risultato poco significativo. Se codice_stazione_origine e data_partenza non vengono forniti, "
            "vengono determinati automaticamente tramite il numero di treno."
        ),
    )
    async def predecessore_treno(
        numero_treno: int,
        codice_stazione_origine: str | None = None,
        data_partenza: int | None = None,
        finestra_minuti: int = 60,
    ) -> Predecessore | None:
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

        return await verifica_predecessore(
            client, codice_stazione_origine, numero_treno, data_partenza, finestra_minuti
        )
