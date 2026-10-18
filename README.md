# pyviaggiatreno

Python library + MCP server for ViaggiaTreno APIs (Italian Railways)

## 📦 Packages

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

1. Install: `pip install viaggiatreno-mcp`
2. Start: `viaggiatreno-mcp`
3. Configure your AI tool (Claude, pi, etc.) to connect to the MCP server

---

## 🛠️ Development

```bash
# Clone repo
git clone https://github.com/matteoredaelli/pyviaggiatreno.git
cd pyviaggiatreno

# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Run MCP server
python -m viaggiatreno_mcp.server
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

Both `viaggiatreno` and `viaggiatreno-mcp` will be published to PyPI with the same version.

---
