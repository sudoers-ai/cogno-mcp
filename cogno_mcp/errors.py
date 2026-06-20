"""Errors for the MCP adapter.

``MCPDispatchError`` is re-exported from cogno-anima so a transport/infra fault
raised here matches the EGO's fatal-error contract (the EGO propagates it, vs.
wrapping a stray exception in ``ToolExecutionError``). ``MCPUnavailableError`` is
raised when the optional ``mcp`` SDK is not installed.
"""

from __future__ import annotations

from cogno_anima.errors import MCPDispatchError

__all__ = ["MCPError", "MCPUnavailableError", "MCPDispatchError"]


class MCPError(RuntimeError):
    """Base class for cogno-mcp errors that are not the anima dispatch fault."""


class MCPUnavailableError(MCPError):
    """The ``mcp`` SDK is required for transport but is not installed.

    Install it with ``pip install "cogno-mcp[mcp]"``.
    """
