"""cogno-mcp — expose an MCP server's tools as a cogno-anima ToolDispatcher.

The third tool source (alongside in-process skills via ``cogno-cortex`` and the
host's native functions): ``MCPDispatcher`` bridges any MCP server to cogno-anima's
``ToolDispatcher`` contract, so the EGO / cogno-soma see MCP tools as ordinary
tools. The mapping logic is SDK-free; the thin transport helpers (stdio/HTTP/SSE)
use the official ``mcp`` SDK. Merge with other sources via
``cogno_anima.tools.CompositeDispatcher``.
"""

from cogno_mcp.dispatcher import MCPDispatcher
from cogno_mcp.errors import MCPDispatchError, MCPError, MCPUnavailableError
from cogno_mcp.transports import http_session, sse_session, stdio_session

__all__ = [
    "MCPDispatcher",
    "stdio_session",
    "http_session",
    "sse_session",
    "MCPError",
    "MCPUnavailableError",
    "MCPDispatchError",
]

__version__ = "0.1.0"
