"""Crawler per raccogliere dati storici da ViaggiaTreno in SQLite."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("viaggiatreno-crawler")
except PackageNotFoundError:  # pragma: no cover - solo in dev non installato
    __version__ = "0.0.0"

__all__ = ["__version__"]
