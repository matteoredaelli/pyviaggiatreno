# Release Guide - pyviaggiatreno

Guida per rilasciare nuove versioni dei pacchetti su PyPI.

## 📋 Prerequisiti

Il publish usa **Trusted Publishing (OIDC)**: nessun token da gestire o ruotare.
Va configurato **una sola volta** su PyPI, per **ciascuno** dei due pacchetti
(`viaggiatreno` e `viaggiatreno-mcp`).

1. **Configura il Trusted Publisher su PyPI** (per ogni pacchetto):
   - Progetto già esistente: *Manage → Publishing → Add a new publisher*
   - Prima pubblicazione: *Account → Publishing → Add a pending publisher*
   - Valori:
     - **Owner**: `matteoredaelli`
     - **Repository name**: `pyviaggiatreno`
     - **Workflow name**: `publish-pypi.yml`
     - **Environment name**: `pypi`

2. **Crea l'environment GitHub** `pypi`:
   - Settings → Environments → New environment → `pypi`
   - (Opzionale) aggiungi un *required reviewer* per approvare ogni publish.

> Non serve alcun `PYPI_TOKEN`: se ne avevi uno nei secrets, puoi rimuoverlo.

## 🔄 Flusso di Release

### Step 1: Test Build (Optional but Recommended)

Prima di rilasciare, verifica che la build funzioni:

```bash
# Localmente (dalla root del repo)
uv build --package viaggiatreno
uv build --package viaggiatreno-mcp

# Oppure: Trigger il workflow test-build.yml manualmente su GitHub
```

### Step 2: Crea un Tag

Il tag triggerato automaticamente il workflow di pubblicazione. Usa semantic versioning.

```bash
# Versione locale (non rilasciare)
git tag -a v0.1.0 -m "Release version 0.1.0"

# Oppure: Usa GitHub UI
# Releases → Draft a new release → Choose tag → v0.1.0
```

### Step 3: Push Tag

```bash
git push origin v0.1.0
```

### Step 4: Guarda la Pipeline

1. Vai a GitHub → Actions
2. Seleziona workflow "Publish to PyPI"
3. Osserva i job:
   - `build` (costruisce entrambi i pacchetti)
   - `publish` (pubblica su PyPI via OIDC)
   - `release` (crea GitHub Release)

### Step 5: Verifica su PyPI

```bash
# Attendi ~2 minuti per PyPI
pip index versions viaggiatreno
pip index versions viaggiatreno-mcp

# Dovrebbe mostrare la nuova versione
```

---

## 📦 Pacchetti Pubblicati

Quando fai un tag `v0.1.0`, entrambi i pacchetti vengono pubblicati:

| Pacchetto | URL | Versione |
|-----------|-----|----------|
| **viaggiatreno** | https://pypi.org/project/viaggiatreno/ | v0.1.0 |
| **viaggiatreno-mcp** | https://pypi.org/project/viaggiatreno-mcp/ | v0.1.0 |

Sempre con la **stessa versione** (monorepo).

---

## 🔄 Tag Versioning

I tag seguono [Semantic Versioning](https://semver.org/):

```
v{MAJOR}.{MINOR}.{PATCH}[-{PRERELEASE}]

v0.1.0         # Release stabile
v0.1.0-rc1     # Release Candidate
v0.1.0-alpha   # Alpha
v0.1.0-beta.1  # Beta
```

### Esempi

```bash
# Versione stabile
git tag v0.1.0

# Versione pre-release (non va in "Latest", ma pubblicata)
git tag v0.2.0-rc1

# Versione beta
git tag v0.2.0-beta
```

---

## 🧪 Workflow Automatici

### 1. **tests.yml** - Sempre (ogni commit main/dev)
- Ruff linting
- Pyright type checking
- Pytest unit tests

### 2. **test-build.yml** - Ogni commit su packages/
- Build entrambi i pacchetti
- Testa installazione wheel
- Upload artifacts (3 giorni)

### 3. **publish-pypi.yml** - Trigger: tag push
- Build entrambi i pacchetti
- Pubblica su PyPI
- Crea GitHub Release

---

## ⚠️ Troubleshooting

### ❌ Build fallisce

```
Controlla:
1. packages/viaggiatreno/pyproject.toml syntax
2. packages/viaggiatreno_mcp/pyproject.toml syntax
3. Imports corretti (viaggiatreno_mcp → from viaggiatreno import ...)
4. pytest tests/ passa localmente
```

### ❌ Non pubblica su PyPI

```
Verifica:
1. Il Trusted Publisher è configurato su PyPI per ENTRAMBI i pacchetti
   (owner matteoredaelli, repo pyviaggiatreno, workflow publish-pypi.yml, environment pypi)
2. L'environment "pypi" esiste in GitHub (Settings → Environments)
3. Il job publish ha permissions: id-token: write (già nel workflow)
4. Nessun conflitto di versione su PyPI (impossibile overwrite)
5. Email PyPI account è verificata
```

### ❌ Tag non pubblica

```
Verifica:
1. Il tag esiste: git tag | grep vX.X.X
2. Il tag è pushato: git push origin vX.X.X
3. Il workflow è attivo (non disabilitato)
4. Actions è abilitato nel repo
```

---

## 🚀 Manual Publishing (Emergency)

Il publishing automatico è via OIDC e non richiede token. Se devi pubblicare
manualmente (es. workflow non disponibile), serve un token PyPI **temporaneo**
generato al momento da https://pypi.org/manage/account/token/ (revocalo dopo):

```bash
# Build (dalla root del repo)
uv build --package viaggiatreno
uv build --package viaggiatreno-mcp

# Pubblica con un token temporaneo (NON committarlo mai)
uv publish --token pypi-...
```

---

## 📝 Checklist Pre-Release

- [ ] Tutti i test passano (`pytest tests/`)
- [ ] Lint passa (`ruff check packages/`)
- [ ] Type check passa (`pyright packages/`)
- [ ] README.md aggiornato
- [ ] CHANGELOG aggiornato (opzionale)
- [ ] Versione in `packages/viaggiatreno/src/viaggiatreno/__init__.py` (version string, se presente)
- [ ] Versione coerente in entrambi i `pyproject.toml`
- [ ] Commit pushato a main
- [ ] Tag creato e pushato

---

## 🎯 Workflow Finale

```
1. Make changes
   ↓
2. Run tests locally: pytest tests/
   ↓
3. Commit & push to main
   ↓
4. Create tag: git tag v0.2.0
   ↓
5. Push tag: git push origin v0.2.0
   ↓
6. GitHub Actions automaticamente:
   - Build entrambi i pacchetti
   - Pubblica su PyPI
   - Crea GitHub Release
   ↓
7. Verifica su PyPI (2-5 minuti)
```

---

## 📚 Riferimenti

- [PyPI Documentation](https://packaging.python.org/)
- [GitHub Actions](https://docs.github.com/en/actions)
- [Semantic Versioning](https://semver.org/)
- [uv publish docs](https://docs.astral.sh/uv/reference/cli/#uv-publish)
