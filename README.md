# cogno-mcp

**Bridge an MCP server's tools to the Cogno tool contract.**

The third tool source for the Cogno stack — alongside in-process skills
([`cogno-cortex`](https://github.com/sudoers-ai/cogno-cortex)) and the host's native
functions. `MCPDispatcher` exposes any [MCP](https://modelcontextprotocol.io) server's
tools as a `cogno-anima` `ToolDispatcher`, so the EGO / `cogno-soma` see MCP tools as
ordinary tools and never speak the protocol.

The valuable part — schema conversion, `CallToolResult → ToolResult` mapping, and
policy (read-only / destructive) from MCP tool annotations — is **SDK-free** and
fully tested with fakes. The thin transport helpers (stdio / HTTP / SSE) are the
only place the official `mcp` SDK is used; transport is the SDK's job, not ours.

```
MCP server ──(stdio/HTTP/SSE)──▶ MCPDispatcher ──▶ ToolDispatcher ──▶ EGO / cogno-soma
                                  (implements cogno-anima's contract)
```

## Install

```bash
pip install "cogno-mcp[mcp]"     # [mcp] pulls the official MCP SDK (for transport)
```

> `cogno-anima` (the contract) is a runtime dep not yet on PyPI — install it from
> git first; see `.github/workflows/ci.yml`. Without the `[mcp]` extra the
> `MCPDispatcher` still works against any session you provide; the transport
> helpers raise a clear `MCPUnavailableError`.

## Use

```python
import sys
from cogno_mcp import MCPDispatcher, stdio_session

async with stdio_session(sys.executable, args=["my_server.py"]) as session:
    dispatcher = await MCPDispatcher.create(session)          # lists + caches tools

    dispatcher.tools_schema()            # OpenAI tool defs the EGO offers
    dispatcher.is_mutating("wipe")       # from the tool's readOnlyHint
    dispatcher.requires_confirmation("wipe")   # from its destructiveHint

    await pipe.run_turn(ctx, cfg, dispatcher=dispatcher)      # cogno-soma
```

Transports: `stdio_session(command, args=...)` (subprocess), `http_session(url)`
(Streamable HTTP), `sse_session(url)` (legacy SSE). Each is an async context manager
that connects, `initialize()`s, and tears down on exit — the host owns the lifecycle.

## Mapping

| MCP | → cogno-anima |
|---|---|
| `Tool.name/description/inputSchema` | `tools_schema()` OpenAI function def |
| `CallToolResult.content` (text blocks) | `ToolResult.output` |
| `CallToolResult.isError = True` | recoverable `ToolResult(ok=False)` |
| transport / protocol exception | raises `MCPDispatchError` (EGO propagates) |
| unknown tool name | recoverable `ToolResult(ok=False)` |
| `annotations.readOnlyHint` | `is_mutating` (absent/false → conservative true) |
| `annotations.destructiveHint = True` | `requires_confirmation` (drives the EGO gate) |

## Skills + MCP + native together

Each source is a `ToolDispatcher`; merge them per persona:

```python
from cogno_anima.tools import CompositeDispatcher
dispatcher = CompositeDispatcher([cortex_dispatcher, mcp_dispatcher, native_dispatcher])
```

The `ToolDispatcher` contract is the unifier — skill / MCP / native are just sources.

## Development

```bash
pip install -e ".[dev]"
pytest tests/unit -q            # SDK-free dispatcher logic against fakes
pytest tests/integration -q     # MCPDispatcher vs a real FastMCP server over stdio
ruff check cogno_mcp tests && mypy cogno_mcp
python examples/host_min.py     # spawns a local MCP server and calls a tool
```

Apache-2.0.
