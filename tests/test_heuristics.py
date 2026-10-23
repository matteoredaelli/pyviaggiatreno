"""Test unitari per l'euristica del predecessore (senza chiamate di rete)."""

from viaggiatreno import TrainBoardItem, TrainStatus
from viaggiatreno.heuristics import trova_predecessore, verifica_predecessore


class ClientFinto:
    """Stub minimale compatibile con l'interfaccia usata da rotazione.py."""

    def __init__(self, status_per_numero: dict[int, TrainStatus], arrivi: list[TrainBoardItem]):
        self._status = status_per_numero
        self._arrivi = arrivi

    async def andamento_treno(self, codice_stazione_origine, numero_treno, data_partenza):
        return self._status.get(numero_treno)

    async def arrivi(self, codice_stazione, data_ora=None):
        return self._arrivi


def _status(
    numero,
    origine,
    id_origine,
    orario_partenza,
    destinazione=None,
    categoria="REG",
    codice_cliente=63,
    tipo_treno="PG",
):
    return TrainStatus.model_validate(
        {
            "numeroTreno": numero,
            "origine": origine,
            "idOrigine": id_origine,
            "orarioPartenza": orario_partenza,
            "destinazione": destinazione,
            "categoria": categoria,
            "codiceCliente": codice_cliente,
            "tipoTreno": tipo_treno,
            "fermate": [],
        }
    )


def _arrivo(
    numero, origine, orario_arrivo, ritardo=0, categoria="REG", codice_cliente=63, arrivato=False
):
    return TrainBoardItem.model_validate(
        {
            "numeroTreno": numero,
            "origine": origine,
            "orarioArrivo": orario_arrivo,
            "ritardo": ritardo,
            "categoria": categoria,
            "codiceCliente": codice_cliente,
            "arrivato": arrivato,
        }
    )


async def test_trova_predecessore_sceglie_arrivo_piu_recente_entro_finestra(tmp_path=None):
    # Riproduce il pattern osservato dal vivo a Lecco: arrivo @17:24 (24858),
    # partenza successiva @17:36 (24867) -> turnaround 12 minuti.
    partenza = 1_000_000_000
    status_24867 = _status(
        24867, "LECCO", "S01520", orario_partenza=partenza, destinazione="MILANO PORTA GARIBALDI"
    )
    arrivi = [
        _arrivo(24856, "MILANO PORTA GARIBALDI", partenza - 42 * 60_000, ritardo=1, arrivato=True),
        _arrivo(24858, "MILANO PORTA GARIBALDI", partenza - 12 * 60_000, ritardo=5),
        _arrivo(
            24860, "MILANO PORTA GARIBALDI", partenza + 18 * 60_000, ritardo=4
        ),  # dopo la partenza, va escluso
    ]
    client = ClientFinto({24867: status_24867}, arrivi)

    risultato = await trova_predecessore(client, "S01520", 24867, partenza, finestra_minuti=60)

    assert risultato is not None
    assert risultato.predecessore_numero == 24858
    assert risultato.predecessore_ritardo_attuale == 5
    assert round(risultato.minuti_turnaround) == 12


async def test_trova_predecessore_nessun_candidato_entro_finestra(tmp_path=None):
    base = 1_000_000_000
    status = _status(
        1, "LECCO", "S01520", orario_partenza=base, destinazione="MILANO PORTA GARIBALDI"
    )
    arrivi = [
        _arrivo(2, "MILANO PORTA GARIBALDI", base - 120 * 60_000)
    ]  # 2 ore prima: fuori finestra
    client = ClientFinto({1: status}, arrivi)

    risultato = await trova_predecessore(client, "S01520", 1, base, finestra_minuti=60)
    assert risultato is None


async def test_trova_predecessore_filtra_per_operatore(tmp_path=None):
    base = 1_000_000_000
    status = _status(
        1,
        "LECCO",
        "S01520",
        orario_partenza=base,
        destinazione="MILANO PORTA GARIBALDI",
        codice_cliente=63,
    )
    arrivi = [
        _arrivo(
            2, "MILANO PORTA GARIBALDI", base - 12 * 60_000, codice_cliente=999
        ),  # altro operatore
    ]
    client = ClientFinto({1: status}, arrivi)

    risultato = await trova_predecessore(client, "S01520", 1, base, finestra_minuti=60)
    assert risultato is None


async def test_verifica_predecessore_arricchisce_con_andamento_treno(tmp_path=None):
    base = 1_000_000_000
    status_1 = _status(
        1, "LECCO", "S01520", orario_partenza=base, destinazione="MILANO PORTA GARIBALDI"
    )
    status_pred = _status(
        2, "MILANO PORTA GARIBALDI", "S01701", orario_partenza=base - 20 * 60_000, tipo_treno="ST"
    )
    arrivi = [_arrivo(2, "MILANO PORTA GARIBALDI", base - 12 * 60_000, ritardo=30)]
    client = ClientFinto({1: status_1, 2: status_pred}, arrivi)

    risultato = await verifica_predecessore(client, "S01520", 1, base, finestra_minuti=60)
    assert risultato is not None
    assert risultato.predecessore_numero == 2
    assert risultato.predecessore_stato_treno == "ST"


async def test_trova_predecessore_evita_linea_sbagliata_in_nodo_interscambio(tmp_path=None):
    """Riproduce il bug trovato dal vivo a Milano Porta Garibaldi: un treno
    per Como non deve scegliere come predecessore un arrivo da Lecco solo
    perché più vicino nel tempo (stesso operatore, stazione di interscambio
    con più linee)."""
    partenza = 1_000_000_000
    status_25064 = _status(
        25064,
        "MILANO PORTA GARIBALDI",
        "S01645",
        orario_partenza=partenza,
        destinazione="COMO S.GIOVANNI",
    )
    arrivi = [
        _arrivo(
            24863, "LECCO", partenza - 1 * 60_000, ritardo=0
        ),  # linea sbagliata, più vicino nel tempo
        _arrivo(25061, "COMO S.GIOVANNI", partenza - 18 * 60_000, ritardo=5),  # linea giusta
    ]
    client = ClientFinto({25064: status_25064}, arrivi)

    risultato = await trova_predecessore(client, "S01645", 25064, partenza, finestra_minuti=60)

    assert risultato is not None
    assert risultato.predecessore_numero == 25061  # non 24863
    assert round(risultato.minuti_turnaround) == 18
