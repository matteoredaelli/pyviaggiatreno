# pyviaggiatreno

Monorepo Python (workspace `uv`) basato sulle API non ufficiali di
[ViaggiaTreno](http://www.viaggiatreno.it) (treni in Italia): libreria client,
server MCP e crawler che salva dati storici in SQLite.

## 📦 Packages

| Package | Ruolo | PyPI |
|---------|-------|------|
| [`viaggiatreno`](./packages/viaggiatreno) | Libreria client HTTP async (core, nessuna dipendenza MCP) | `viaggiatreno` |
| [`viaggiatreno-mcp`](./packages/viaggiatreno_mcp) | Server MCP per agenti AI (Claude, Kiro, Cursor, …) | `viaggiatreno-mcp` |
| [`viaggiatreno-crawler`](./packages/viaggiatreno_crawler) | Poller che interroga le API nel tempo e salva in SQLite | `viaggiatreno-crawler` |

> Non esiste un pacchetto CLI generico separato: gli unici comandi da riga di
> comando sono gli entry point `viaggiatreno-mcp` (server MCP) e
> `viaggiatreno-crawler` (crawler).

### `viaggiatreno` - Core Library ⭐

Pure Python client library for ViaggiaTreno APIs. No MCP dependencies.

```bash
pip install viaggiatreno
```

**Usage**:
```python
from viaggiatreno import ViaggiaTrenoClient
import asyncio


async def main():
    client = ViaggiaTrenoClient()

    # Get station suggestions
    stations = await client.autocompleta_stazione("milano")
    print(stations)

    # Get departures
    departures = await client.partenze("S01700", datetime.now())
    for train in departures:
        print(f"{train.compNumeroTreno} → {train.destinazione} ({train.ritardo} min delay)")


asyncio.run(main())
```

### `viaggiatreno-mcp` - MCP Server

Model Context Protocol server for Claude, pi, and other AI agents.

```bash
pip install viaggiatreno-mcp
```

**Start server**:
```bash
viaggiatreno-mcp
```

Configure in Claude, pi, or other AI tools to use these tools:
- `autocompleta_stazione` - Station autocomplete
- `cerca_stazione` - Search stations
- `dettaglio_stazione` - Station details
- `partenze` - Departures board
- `arrivi` - Arrivals board
- `stato_treno` - Train status & full route
- E altri...

### `viaggiatreno-crawler` - Crawler → SQLite

Poller che usa la libreria core per raccogliere nel tempo dati storici sui
treni (numeri, ritardi, binari, fermate) in un database SQLite locale — utile
per KPI che le API ViaggiaTreno non espongono (sono solo "stato attuale", non
storiche).

```bash
pip install viaggiatreno-crawler
```

**Avvio**:
```bash
viaggiatreno-crawler run \
  --regione 1 \
  --categorie "ES*,IC,EXP,EC,EN,REG" \
  --db-path data/treni.db \
  --intervallo-scoperta 300 \
  --intervallo-verifica 900
```

Flusso: scoperta treni in circolazione (`elenco_tratte`/`dettagli_tratta`) →
arricchimento percorso (`andamento_treno`) → upsert in SQLite. Lo schema della
tabella `stops` è compatibile con `stops.txt` del GTFS Trenord. Dettagli in
[packages/viaggiatreno_crawler/README.md](./packages/viaggiatreno_crawler/README.md).

---

## ✨ Features

### Core Library
- 🚄 Async/await HTTP client with `httpx`
- 📊 Strongly-typed Pydantic models
- 🔄 Intelligent parsing (JSON, plain text, HTML fragments)
- ⚡ Handles ViaggiaTreno quirks (204 No Content, JS date formats, etc.)
- 🇮🇹 Full coverage of Italian railways

### MCP Server
- 🤖 AI-ready tool registration
- 🔗 Automatic parameter resolution (derive trip details from train number)
- 📱 Works with Claude, pi, and other MCP clients
- 🧵 Async concurrent tool execution

---

## 📚 Documentation

See main documentation files:
- [VIAGGIATRENO.md](./VIAGGIATRENO.md) - API reference (20+ endpoints)
- [TRENORD.md](./TRENORD.md) - GTFS Trenord structure
- [ENTITA.md](./ENTITA.md) - Data model & schema
- [GLOSSARIO.md](./GLOSSARIO.md) - Railway terminology
- [COPERTURA_GEOGRAFICA.md](./COPERTURA_GEOGRAFICA.md) - Geographic coverage

---

## 🚀 Quick Start

### Installation

```bash
# Core library only
pip install viaggiatreno

# With MCP server
pip install viaggiatreno-mcp

# With crawler (SQLite poller)
pip install viaggiatreno-crawler
```

### Using the Library

```python
from viaggiatreno import ViaggiaTrenoClient
from datetime import datetime

client = ViaggiaTrenoClient()

# Get train departures from Milano Centrale
trains = await client.partenze("S01700", datetime.now())

for train in trains:
    print(
        f"{train.numeroTreno}: {train.destinazione} at {train.compOrarioPartenza} (delay: {train.ritardo}m)"
    )
```

### Using MCP Server

Il modo consigliato è `uvx` (richiede [uv](https://docs.astral.sh/uv/)), che
esegue il server in un ambiente isolato senza installarlo a mano.

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`
su macOS, `%APPDATA%\Claude\claude_desktop_config.json` su Windows):

```json
{
  "mcpServers": {
    "viaggiatreno": {
      "command": "uvx",
      "args": ["viaggiatreno-mcp"]
    }
  }
}
```

**Kiro** (`~/.kiro/settings/mcp.json`) e altri client con lo stesso formato
(Cursor, Windsurf, VS Code MCP):

```json
{
  "mcpServers": {
    "viaggiatreno": {
      "command": "uvx",
      "args": ["viaggiatreno-mcp"],
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

In alternativa, se hai già fatto `pip install viaggiatreno-mcp`, usa
`"command": "viaggiatreno-mcp"` (o `"command": "python", "args": ["-m", "viaggiatreno_mcp"]`).
Riavvia il client dopo aver salvato la configurazione.

Dettagli completi in [packages/viaggiatreno_mcp/README.md](./packages/viaggiatreno_mcp/README.md).

---

## 🛠️ Development

Il repo è un workspace `uv` con 3 pacchetti sotto `packages/`.

```bash
# Clone repo
git clone https://github.com/matteoredaelli/pyviaggiatreno.git
cd pyviaggiatreno

# Install workspace + dev deps (editable)
uv sync

# Lint + type check + format check
make lint          # ruff format --check + ruff check + pyright

# Run tests
make pytest        # oppure: uv run pytest

# Run MCP server
make run           # oppure: uv run viaggiatreno-mcp

# Run crawler
uv run viaggiatreno-crawler run --db-path data/treni.db

# Build all packages
make build         # oppure: uv build
```

---

## 📄 License

MIT

---

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repo
2. Create a feature branch
3. Submit a PR

---

## 📞 Support

- 🐛 [Bug reports](https://github.com/matteoredaelli/pyviaggiatreno/issues)
- 💬 [Discussions](https://github.com/matteoredaelli/pyviaggiatreno/discussions)
- 📧 Email: matteo.redaelli@gmail.com

---

## 🔄 GitHub Actions Workflow

La repo ha 3 workflow automatici:

### 1. **Tests & Linting** (`tests.yml`)
- ✅ Ruff linting
- ✅ Pyright type checking  
- ✅ Pytest unit tests
- 🔄 Trigger: Ogni commit su `main`/`dev` e PR
- 🎯 Purpose: Verifica codice quality

### 2. **Test Build** (`test-build.yml`)
- ✅ Build entrambi i pacchetti
- ✅ Testa installazione wheel
- 🔄 Trigger: Commit su `packages/` o workflow_dispatch
- 🎯 Purpose: Verifica che la build funzioni (senza pubblicare)

### 3. **Publish to PyPI** (`publish-pypi.yml`)
- ✅ Build entrambi i pacchetti
- ✅ Pubblica su PyPI
- ✅ Crea GitHub Release con artifacts
- 🔄 Trigger: Tag push (e.g. `git push origin v0.1.0`)
- 🎯 Purpose: Pubblica su PyPI (una sola volta)

**Vedi [RELEASE.md](./RELEASE.md) per istruzioni dettagliate.**

---

## 📦 Publishing to PyPI

### Prerequisites

Il publish usa **Trusted Publishing (OIDC)** — nessun token da gestire. Configurazione una tantum:

1. PyPI account (https://pypi.org)
2. Per **ciascun** pacchetto (`viaggiatreno`, `viaggiatreno-mcp`), aggiungi un Trusted Publisher:
   owner `matteoredaelli`, repo `pyviaggiatreno`, workflow `publish-pypi.yml`, environment `pypi`
3. Crea l'environment `pypi` in GitHub (Settings → Environments)

### Release Process
```bash
# 1. Commit & push
git add .
git commit -m "feature: add X"
git push origin main

# 2. Create tag (triggers publish workflow)
git tag v0.2.0
git push origin v0.2.0

# 3. GitHub Actions automatically publishes both packages
```

Both `viaggiatreno` and `viaggiatreno-mcp` (e `viaggiatreno-crawler`) will be published to PyPI with the same version.

---
