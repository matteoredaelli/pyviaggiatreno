"""Modelli Pydantic per treni, corse, fermate e tabelloni."""

from typing import Any

from pydantic import Field

from viaggiatreno.models.common import (
    CLIENT_COMPANIES,
    TRAIN_STATUS_DESCRIPTIONS,
    ViaggiaTrenoBaseModel,
)


class TrainAutocompleteItem(ViaggiaTrenoBaseModel):
    """Corsa di un treno restituita dall'autocompletamento numero treno."""

    raw: str = Field(..., description="Stringa grezza restituita dall'API")
    numero_treno: int = Field(..., description="Numero del treno")
    stazione_origine: str = Field(..., description="Nome della stazione di origine")
    codice_stazione_origine: str = Field(..., description="Codice stazione di origine (es. S00219)")
    millis_data_partenza: int = Field(
        ..., description="Timestamp mezzanotte del giorno di partenza in millisecondi"
    )
    data: str | None = Field(None, description="Data di partenza (se presente, es. 04/10/26)")


class TrainSearchResult(ViaggiaTrenoBaseModel):
    """Risultato sintetico della corsa corrente di un treno."""

    numeroTreno: str = Field(..., description="Numero del treno")
    codLocOrig: str = Field(..., description="Codice stazione di origine (es. S00219)")
    descLocOrig: str = Field(..., description="Nome stazione di origine")
    dataPartenza: str = Field(..., description="Data di partenza YYYY-MM-DD")
    millisDataPartenza: str = Field(..., description="Mezzanotte in ms da passare a andamentoTreno")
    corsa: str | None = Field(None, description="Identificativo corsa")
    h24: bool | None = Field(None, description="Flag servizio h24")
    tipo: str | None = Field(None, description="Stato/tipo del treno (es. PG)")
    formatDataPartenza: str | None = Field(None, description="Formato data alternativo")


class Fermata(ViaggiaTrenoBaseModel):
    """Singola fermata lungo l'itinerario del treno."""

    stazione: str = Field(..., description="Nome della stazione")
    id: str = Field(..., description="Codice stazione (es. S01700)")
    tipoFermata: str = Field(
        ...,
        description="'P' per Partenza/Origine, 'F' per Fermata intermedia, 'A' per Arrivo/Destinazione",
    )
    progressivo: int | None = Field(None, description="Numero progressivo fermata nell'itinerario")
    programmata: int | None = Field(None, description="Orario programmato in millisecondi")
    effettiva: int | None = Field(
        None, description="Orario effettivo in millisecondi (se rilevato)"
    )
    ritardo: int | None = Field(None, description="Ritardo complessivo alla fermata in minuti")
    ritardoPartenza: int | None = Field(None, description="Ritardo in partenza in minuti")
    ritardoArrivo: int | None = Field(None, description="Ritardo in arrivo in minuti")
    partenza_teorica: int | None = Field(
        None, description="Orario teorico di partenza in millisecondi"
    )
    arrivo_teorico: int | None = Field(None, description="Orario teorico di arrivo in millisecondi")
    partenzaReale: int | None = Field(None, description="Orario reale di partenza in millisecondi")
    arrivoReale: int | None = Field(None, description="Orario reale di arrivo in millisecondi")
    binarioEffettivoPartenzaDescrizione: str | None = Field(
        None, description="Binario effettivo di partenza"
    )
    binarioProgrammatoPartenzaDescrizione: str | None = Field(
        None, description="Binario programmato di partenza"
    )
    binarioEffettivoArrivoDescrizione: str | None = Field(
        None, description="Binario effettivo di arrivo"
    )
    binarioProgrammatoArrivoDescrizione: str | None = Field(
        None, description="Binario programmato di arrivo"
    )
    actualFermataType: int | None = Field(
        None,
        description="Stato fermata: 1=effettuata/regolare, 0=non ancora arrivato, 2=non prevista, 3=soppressa",
    )
    visualizzaPrevista: bool | None = Field(
        None, description="Flag visualizzazione orario previsto"
    )


class TrainBoardItem(ViaggiaTrenoBaseModel):
    """Riga del tabellone partenze/arrivi di stazione o di tratta."""

    numeroTreno: int = Field(..., description="Numero del treno")
    categoria: str | None = Field(
        None, description="Sigla categoria (es. REG, IC, EC, '' per Frecce)"
    )
    categoriaDescrizione: str | None = Field(
        None, description="Descrizione categoria (es. ' FR', 'REG')"
    )
    compNumeroTreno: str | None = Field(
        None, description="Etichetta completa del treno (es. 'FR 9611')"
    )
    origine: str | None = Field(None, description="Stazione di origine (popolata negli arrivi)")
    destinazione: str | None = Field(
        None, description="Stazione di destinazione (popolata nelle partenze)"
    )
    codOrigine: str | None = Field(None, description="Codice stazione di origine (es. S00219)")
    codDestinazione: str | None = Field(None, description="Codice stazione di destinazione")
    dataPartenzaTreno: int | None = Field(None, description="Data di partenza (mezzanotte ms)")
    dataPartenzaTrenoAsDate: str | None = Field(None, description="Data di partenza YYYY-MM-DD")
    millisDataPartenza: str | None = Field(None, description="Mezzanotte in ms come stringa")
    partenzaTreno: int | None = Field(
        None, description="Orario di partenza reale dall'origine in ms"
    )
    orarioPartenza: int | str | None = Field(
        None, description="Orario programmato di partenza (ms o stringa data)"
    )
    orarioArrivo: int | str | None = Field(
        None, description="Orario programmato di arrivo (ms o stringa data)"
    )
    compOrarioPartenza: str | None = Field(None, description="Orario di partenza formattato HH:MM")
    compOrarioArrivo: str | None = Field(None, description="Orario di arrivo formattato HH:MM")
    ritardo: int | None = Field(None, description="Ritardo in minuti")
    compRitardo: list[str | None] | None = Field(
        None,
        description="Testo del ritardo multilingua (elementi possono essere null, osservato dal vivo)",
    )
    binarioEffettivoPartenzaDescrizione: str | None = Field(
        None, description="Binario effettivo di partenza"
    )
    binarioProgrammatoPartenzaDescrizione: str | None = Field(
        None, description="Binario programmato di partenza"
    )
    binarioEffettivoArrivoDescrizione: str | None = Field(
        None, description="Binario effettivo di arrivo"
    )
    binarioProgrammatoArrivoDescrizione: str | None = Field(
        None, description="Binario programmato di arrivo"
    )
    circolante: bool | None = Field(None, description="True se il treno è in viaggio")
    inStazione: bool | None = Field(
        None, description="True se il treno è fermo nella stazione richiesta"
    )
    nonPartito: bool | None = Field(None, description="True se non è ancora partito dall'origine")
    arrivato: bool | None = Field(
        None, description="True se è già arrivato alla stazione richiesta"
    )
    provvedimento: int | None = Field(
        None, description="0=regolare, 1=cancellato, 2=parzialmente soppresso/deviato"
    )
    riprogrammazione: str | None = Field(None, description="'Y' se riprogrammato, 'N' altrimenti")
    codiceCliente: int | None = Field(None, description="Codice numerico dell'impresa ferroviaria")
    impresaFerroviaria: str | None = Field(None, description="Nome dell'impresa ferroviaria")
    ultimoRilev: int | None = Field(None, description="Timestamp dell'ultimo rilevamento in ms")
    compDurata: str | None = Field(None, description="Durata del tragitto HH:MM")

    def model_post_init(self, context: Any, /) -> None:
        if self.codiceCliente is not None and self.impresaFerroviaria is None:
            self.impresaFerroviaria = CLIENT_COMPANIES.get(self.codiceCliente)


class TrainStatus(ViaggiaTrenoBaseModel):
    """Stato in tempo reale completo di un treno con relative fermate (andamentoTreno)."""

    numeroTreno: int = Field(..., description="Numero del treno")
    tipoTreno: str | None = Field(
        None, description="Codice tipo treno (es. PG regolare, ST soppresso, PP/SI/SF)"
    )
    categoria: str | None = Field(None, description="Sigla categoria")
    categoriaDescrizione: str | None = Field(None, description="Descrizione categoria")
    compNumeroTreno: str | None = Field(None, description="Etichetta completa del treno")
    origine: str | None = Field(None, description="Nome stazione di origine")
    destinazione: str | None = Field(None, description="Nome stazione di destinazione")
    idOrigine: str | None = Field(None, description="Codice stazione di origine")
    idDestinazione: str | None = Field(None, description="Codice stazione di destinazione")
    dataPartenzaTrenoAsDate: str | None = Field(None, description="Data di partenza YYYY-MM-DD")
    dataPartenzaTreno: int | None = Field(None, description="Data di partenza (mezzanotte ms)")
    orarioPartenza: int | str | None = Field(
        None, description="Orario programmato di partenza dall'origine"
    )
    orarioArrivo: int | str | None = Field(
        None, description="Orario programmato di arrivo a destinazione"
    )
    compOrarioPartenza: str | None = Field(None, description="Orario partenza HH:MM")
    compOrarioArrivo: str | None = Field(None, description="Orario arrivo HH:MM")
    ritardo: int | None = Field(None, description="Ritardo attuale in minuti")
    compRitardo: list[str | None] | None = Field(
        None, description="Testo del ritardo multilingua (elementi possono essere null)"
    )
    compRitardoAndamento: list[str | None] | None = Field(
        None, description="Descrizione estesa ritardo multilingua (elementi possono essere null)"
    )
    circolante: bool | None = Field(None, description="True se in viaggio")
    inStazione: bool | None = Field(None, description="True se fermo in stazione")
    nonPartito: bool | None = Field(None, description="True se non ancora partito")
    arrivato: bool | None = Field(None, description="True se giunto a destinazione finale")
    provvedimento: int | None = Field(
        None, description="0=regolare, 1=soppresso, 2=parzialmente soppresso, 3=deviato"
    )
    statoDescrizione: str | None = Field(
        None, description="Descrizione testuale dello stato di circolazione"
    )
    riprogrammazione: str | None = Field(None, description="Stato riprogrammazione")
    oraUltimoRilevamento: int | None = Field(None, description="Orario ultimo rilevamento in ms")
    compOraUltimoRilevamento: str | None = Field(
        None, description="Orario ultimo rilevamento HH:MM"
    )
    stazioneUltimoRilevamento: str | None = Field(
        None, description="Stazione/posto di movimento dell'ultimo rilevamento"
    )
    subTitle: str | None = Field(None, description="Sottotitolo o note su soppressioni parziali")
    codiceCliente: int | None = Field(None, description="Codice dell'impresa ferroviaria")
    impresaFerroviaria: str | None = Field(None, description="Nome dell'impresa ferroviaria")
    fermate: list[Fermata] = Field(
        default_factory=list,
        description="Lista ordinata delle fermate commerciali con orari e binari",
    )
    fermateSoppresse: list[dict[str, Any]] | None = Field(
        default=None, description="Eventuali fermate soppresse"
    )

    def model_post_init(self, context: Any, /) -> None:
        if self.codiceCliente is not None and self.impresaFerroviaria is None:
            self.impresaFerroviaria = CLIENT_COMPANIES.get(self.codiceCliente)
        if self.tipoTreno is not None and self.statoDescrizione is None:
            self.statoDescrizione = TRAIN_STATUS_DESCRIPTIONS.get(
                self.tipoTreno, f"Tipo: {self.tipoTreno}"
            )


class TrattaCanvasItem(ViaggiaTrenoBaseModel):
    """Elemento del percorso visuale ad albero (tratteCanvas)."""

    id: str = Field(..., description="Codice stazione")
    stazione: str = Field(..., description="Nome stazione")
    first: bool = Field(..., description="True se è la stazione di partenza iniziale")
    last: bool = Field(..., description="True se è la stazione di arrivo finale")
    stazioneCorrente: bool = Field(..., description="True se il treno si trova in questa stazione")
    partenzaReale: bool = Field(..., description="True se la partenza è già avvenuta")
    arrivoReale: bool = Field(..., description="True se l'arrivo è già avvenuto")
    fermata: Fermata = Field(..., description="Dati dettagliati della fermata")
    orientamento: list[str | None] | None = Field(
        None, description="Orientamento carrozze multilingua (elementi possono essere null)"
    )
    actualFermataType: int | None = Field(None, description="Codice stato fermata")
    trattaType: int | None = Field(None, description="Tipo di segmento")
    previousTrattaType: int | None = Field(None, description="Tipo di segmento precedente")
    nextTrattaType: int | None = Field(None, description="Tipo di segmento successivo")
