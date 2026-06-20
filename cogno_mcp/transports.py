"""Transport helpers — establish an MCP ``ClientSession`` over stdio / HTTP / SSE.

These are the only place the optional ``mcp`` SDK is imported (lazily), so the
``MCPDispatcher`` stays SDK-free. Each is an async context manager that connects,
initializes the session, and yields it; the host owns the lifecycle:

    async with stdio_session("python", args=["server.py"]) as session:
        dispatcher = await MCPDispatcher.create(session)
        await pipe.run_turn(ctx, cfg, dispatcher=dispatcher)

The connection (and the server subprocess, for stdio) is torn down on exit.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Sequence

from cogno_mcp.errors import MCPUnavailableError


def _imports():
    try:
        from mcp import ClientSession  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised via the unit guard
        raise MCPUnavailableError(
            'the "mcp" SDK is required for transport: pip install "cogno-mcp[mcp]"') from exc
    return ClientSession


@asynccontextmanager
async def stdio_session(
    command: str, *, args: Optional[Sequence[str]] = None,
    env: Optional[dict] = None,
) -> AsyncIterator:
    """Spawn an MCP server as a subprocess (stdio transport) and yield a session."""
    ClientSession = _imports()
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(command=command, args=list(args or []), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def http_session(url: str, *, headers: Optional[dict] = None) -> AsyncIterator:
    """Connect to an MCP server over Streamable HTTP and yield a session."""
    ClientSession = _imports()
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def sse_session(url: str, *, headers: Optional[dict] = None) -> AsyncIterator:
    """Connect to an MCP server over SSE (legacy transport) and yield a session."""
    ClientSession = _imports()
    from mcp.client.sse import sse_client

    async with sse_client(url, headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
