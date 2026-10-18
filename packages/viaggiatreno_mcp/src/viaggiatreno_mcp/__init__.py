"""ViaggiaTreno MCP Server."""

from importlib.metadata import PackageNotFoundError, version

from viaggiatreno import ViaggiaTrenoClient

from viaggiatreno_mcp.server import create_server, mcp

try:
    # Generated at build time by hatch-vcs from the Git tag.
    from viaggiatreno_mcp._version import (
        __version__,  # type: ignore[import-not-found,unused-ignore]
    )
except ImportError:  # pragma: no cover - only when running from an unbuilt tree
    try:
        __version__ = version("viaggiatreno-mcp")
    except PackageNotFoundError:
        __version__ = "0.0.0.dev0"

__all__ = [
    "ViaggiaTrenoClient",
    "__version__",
    "create_server",
    "mcp",
]
