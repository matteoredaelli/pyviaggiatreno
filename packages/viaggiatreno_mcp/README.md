# viaggiatreno-mcp

Server [MCP](https://modelcontextprotocol.io) (Model Context Protocol) per
interrogare in tempo reale la rete ferroviaria italiana tramite le API di
ViaggiaTreno.

Il server è un adattatore sottile: espone come tool MCP le funzionalità della
libreria [`viaggiatreno`](https://pypi.org/project/viaggiatreno/), senza
conoscere i dettagli delle API sottostanti. Permette ad assistenti come Claude
di cercare stazioni, consultare tabelloni partenze/arrivi, monitorare ritardi e
andamento dei treni, controllare le tratte e leggere le notizie di infomobilità.

## Installazione

```bash
pip install viaggiatreno-mcp
```

## Avvio

```bash
# tramite lo script console
viaggiatreno-mcp

# oppure come modulo
python -m viaggiatreno_mcp
```

Il server usa il trasporto **stdio**: viene avviato dal client MCP, non va
lanciato a mano quando lo si configura in Claude/Kiro/ecc.

## Configurazione nei client MCP

Il modo consigliato è `uvx`, che scarica ed esegue il pacchetto in un ambiente
isolato senza installazione manuale (richiede [uv](https://docs.astral.sh/uv/)).

### Claude Desktop

File di configurazione:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

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

### Kiro (e client con lo stesso formato: Cursor, Windsurf, VS Code MCP, ecc.)

In `~/.kiro/settings/mcp.json` (globale) o `.kiro/settings/mcp.json` (per workspace):

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

### Alternativa senza uvx (pacchetto già installato con pip)

Se hai fatto `pip install viaggiatreno-mcp`, punta direttamente al comando.
Usa un percorso assoluto se il client non eredita il tuo `PATH`:

```json
{
  "mcpServers": {
    "viaggiatreno": {
      "command": "viaggiatreno-mcp",
      "args": []
    }
  }
}
```

Oppure, per essere indipendenti dal `PATH`, via interprete Python:

```json
{
  "mcpServers": {
    "viaggiatreno": {
      "command": "python",
      "args": ["-m", "viaggiatreno_mcp"]
    }
  }
}
```

Dopo aver salvato la configurazione, riavvia il client MCP.

## Dipendenze

- [`viaggiatreno`](https://pypi.org/project/viaggiatreno/) — libreria client core
- [`fastmcp`](https://pypi.org/project/fastmcp/) — framework MCP

## Licenza

Vedi il file `LICENSE` nel repository.

Repository: https://github.com/matteoredaelli/pyviaggiatreno
