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

import importlib.util
from contextlib import asynccontextmanager
from typing import AsyncIterator, NoReturn, Optional, Sequence

from cogno_mcp.errors import MCPUnavailableError


def _sdk_present(module: str = "mcp") -> bool:
    """Whether the top-level SDK package is INSTALLED, independent of whether importing it
    succeeds. ``find_spec`` locates a top-level package without executing it, so a package
    that is installed but raises on import (the real case: ``mcp`` installed against an
    incompatible ``pydantic``) still reads as present — and its real failure is surfaced
    rather than masked as "not installed". A missing package has no spec, and a parent that
    itself fails to import (or a name with no spec) cannot be confirmed, so both read absent
    and get the install hint."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _translate_import_error(exc: ImportError, module: str = "mcp") -> NoReturn:
    """Turn an ImportError from loading the SDK into the RIGHT error.

    If the SDK is genuinely absent → the friendly ``MCPUnavailableError`` with the install
    hint. If it is installed but broke on import (an incompatible dependency, a partial
    install) → re-raise the ORIGINAL error so its real cause and message reach the caller,
    instead of a generic "SDK not installed" that sends them to reinstall a package that is
    already there."""
    if _sdk_present(module):
        raise exc   # installed but broken — keep the original cause/chain intact
    raise MCPUnavailableError(
        'the "mcp" SDK is required for transport: pip install "cogno-mcp[mcp]"') from exc


def _imports():
    try:
        from mcp import ClientSession  # noqa: F401
    except ImportError as exc:
        _translate_import_error(exc, "mcp")
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
