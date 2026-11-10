# Copyright 2026 Matteo Redaelli
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modelli comuni ed enumerazioni per ViaggiaTreno MCP."""

from pydantic import BaseModel, ConfigDict


class ViaggiaTrenoBaseModel(BaseModel):
    """Classe base per tutti i modelli con configurazione permissiva."""

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
    )


# Mappatura dei codici regione (da VIAGGIATRENO.md)
REGIONS: dict[int, str] = {
    0: "Italia (stazioni principali)",
    1: "Lombardia",
    2: "Liguria",
    3: "Piemonte",
    4: "Valle d'Aosta",
    5: "Lazio",
    6: "Umbria",
    7: "Molise",
    8: "Emilia Romagna",
    9: "Trentino-Alto Adige",
    10: "Friuli-Venezia Giulia",
    11: "Marche",
    12: "Veneto",
    13: "Toscana",
    14: "Sicilia",
    15: "Basilicata",
    16: "Puglia",
    17: "Calabria",
    18: "Campania",
    19: "Abruzzo",
    20: "Sardegna",
    21: "Provincia autonoma di Trento",
    22: "Provincia autonoma di Bolzano",
}

# Mappatura delle imprese ferroviarie (codiceCliente)
CLIENT_COMPANIES: dict[int, str] = {
    1: "Trenitalia (alta velocità)",
    2: "Trenitalia (regionali)",
    4: "Trenitalia (InterCity)",
    18: "Trenitalia Tper",
    63: "Trenord",
    64: "TILO",
    910: "Ferrovie del Sud Est",
}

# Significato stato treno (tipoTreno + provvedimento)
TRAIN_STATUS_DESCRIPTIONS: dict[str, str] = {
    "PG": "Regolare",
    "ST": "Soppresso",
    "PP": "Parzialmente soppresso",
    "SI": "Parzialmente soppresso (fermate iniziali cancellate)",
    "SF": "Parzialmente soppresso (fermate finali cancellate)",
    "DV": "Deviato",
    "SM": "Cancellato in tratta con cambio treno",
    "VD": "Variazione di destinazione",
    "VO": "Variazione di origine",
}
