"""cogno-mcp — expose an MCP server's tools as a cogno-anima ToolDispatcher.

The third tool source (alongside in-process skills via ``cogno-cortex`` and the
host's native functions): ``MCPDispatcher`` bridges any MCP server to cogno-anima's
``ToolDispatcher`` contract, so the EGO / cogno-soma see MCP tools as ordinary
tools. The mapping logic is SDK-free; the thin transport helpers (stdio/HTTP/SSE)
use the official ``mcp`` SDK. Merge with other sources via
``cogno_anima.tools.CompositeDispatcher``.

A server raises cogno-anima's third confirmation gate — "I ran, I READ, I did not commit, ask
first about THIS call" — by putting :data:`META_NEEDS_CONFIRMATION` in the ``_meta`` of its
result (or of one of its content blocks), and may name what it needs back under
:data:`META_CONFIRM_ARGUMENTS`. See ``cogno_mcp.dispatcher`` for why that field and not
``isError`` / ``structuredContent`` / the tool annotations.
"""

from cogno_mcp.dispatcher import (
    META_CONFIRM_ARGUMENTS, META_NEEDS_CONFIRMATION, MCPDispatcher, MCPToolResult)
from cogno_mcp.errors import MCPDispatchError, MCPError, MCPUnavailableError
from cogno_mcp.transports import http_session, sse_session, stdio_session

__all__ = [
    "MCPDispatcher",
    "MCPToolResult",
    "META_NEEDS_CONFIRMATION",
    "META_CONFIRM_ARGUMENTS",
    "stdio_session",
    "http_session",
    "sse_session",
    "MCPError",
    "MCPUnavailableError",
    "MCPDispatchError",
]

__version__ = "0.1.0"
