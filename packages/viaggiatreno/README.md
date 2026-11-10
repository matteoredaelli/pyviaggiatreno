# viaggiatreno

Client Python per le API non ufficiali di [ViaggiaTreno](http://www.viaggiatreno.it),
il sistema informativo in tempo reale della rete ferroviaria italiana.

La libreria fornisce:

- **`ViaggiaTrenoClient`** — client HTTP asincrono (basato su `httpx`) per tutti
  gli endpoint REST di ViaggiaTreno (stazioni, partenze/arrivi, andamento treni,
  tratte, infomobilità, meteo, statistiche).
- **Modelli dati tipizzati** (pydantic): `StationDetail`, `TrainBoardItem`,
  `TrainStatus`, `DettaglioTratta`, `Statistics`, e altri.
- **Parser** per le risposte non-JSON (RSS infomobilità, autocomplete testuali).

## Installazione

```bash
pip install viaggiatreno
```

## Esempio

```python
import asyncio
from viaggiatreno import ViaggiaTrenoClient


async def main() -> None:
    async with ViaggiaTrenoClient() as client:
        stazioni = await client.autocompleta_stazione("Milano")
        for s in stazioni:
            print(s)


asyncio.run(main())
```

## Licenza

Vedi il file `LICENSE` nel repository.

Repository: https://github.com/matteoredaelli/pyviaggiatreno
