"""Modelli Pydantic per tratte ferroviarie e segmenti di rete."""

from pydantic import Field

from viaggiatreno.models.common import ViaggiaTrenoBaseModel
from viaggiatreno.models.train import TrainBoardItem


class TrattaSegment(ViaggiaTrenoBaseModel):
    """Segmento della rete ferroviaria tra due nodi (elencoTratte).

    Nota: ``trattaAB``/``trattaBA`` sono numerati **per regione**: lo stesso ID
    può indicare segmenti fisicamente diversi secondo l'``id_regione`` usato
    nella chiamata a ``elenco_tratte``. Vanno passati a ``dettagli_tratta``
    insieme allo stesso ``id_regione`` con cui sono stati ottenuti, altrimenti
    si rischia di leggere i treni di un segmento completamente diverso senza
    nessun errore (verificato dal vivo, vedi VIAGGIATRENO.md).
    """

    nodoA: str = Field(..., description="Codice nodo o stazione estremo A")
    nodoB: str = Field(..., description="Codice nodo o stazione estremo B")
    trattaAB: int = Field(
        ..., description="Identificativo numerico del segmento in direzione A -> B (scoped per regione)"
    )
    trattaBA: int = Field(
        ..., description="Identificativo numerico del segmento in direzione B -> A (scoped per regione)"
    )
    parentAB: int | None = Field(None, description="ID del segmento padre A -> B")
    parentBA: int | None = Field(None, description="ID del segmento padre B -> A")
    latitudineA: float | None = Field(None, description="Latitudine dell'estremo A")
    longitudineA: float | None = Field(None, description="Longitudine dell'estremo A")
    latitudineB: float | None = Field(None, description="Latitudine dell'estremo B")
    longitudineB: float | None = Field(None, description="Longitudine dell'estremo B")
    occupata: bool = Field(..., description="True se almeno un treno è presente su questo segmento")


class DettaglioTratta(ViaggiaTrenoBaseModel):
    """Gruppo di treni presenti su un senso di marcia di una tratta (dettagliTratta)."""

    tratta: int | str | None = Field(
        None,
        description=(
            "ID numerico o nome leggibile del segmento (es. 'Codogno - Piacenza'); "
            "può essere null per i nodi senza nome (es. segnaposto S00000/S99999). "
            "Verificato dal vivo: con id_regione=0 è spesso null, con id_regione>0 "
            "può contenere il nome del segmento."
        ),
    )
    treni: list[TrainBoardItem] = Field(
        default_factory=list, description="Lista dei treni attualmente sul segmento"
    )
