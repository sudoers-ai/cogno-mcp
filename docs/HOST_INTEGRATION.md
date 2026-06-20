# Host integration — cogno-mcp

cogno-mcp turns an MCP server into a `ToolDispatcher` the EGO can use. This guide
maps the seams.

## 1. Connect → build → use

```python
import sys
from cogno_mcp import MCPDispatcher, stdio_session

async with stdio_session(sys.executable, args=["server.py"]) as session:
    dispatcher = await MCPDispatcher.create(session, names=None)   # None → all tools
    await pipe.run_turn(ctx, cfg, dispatcher=dispatcher)
```

The session context manager owns the connection lifecycle (and, for stdio, the
server subprocess). Keep it open for the duration of the turn(s) that use the
dispatcher; it tears down on exit.

## 2. Transports

| Helper | Transport | Use |
|---|---|---|
| `stdio_session(command, *, args, env)` | stdio (subprocess) | local servers / CLIs |
| `http_session(url, *, headers)` | Streamable HTTP | remote servers |
| `sse_session(url, *, headers)` | SSE (legacy) | older remote servers |

All need the `mcp` SDK (`pip install "cogno-mcp[mcp]"`); without it they raise
`MCPUnavailableError`. `headers` is where you put auth (bearer tokens, etc.) — auth,
retries and reconnection are host concerns (the SDK + your config), not cogno-mcp's.

## 3. What the EGO sees (mapping)

- `tools_schema()` — the server's tools as OpenAI function defs (cached from
  `list_tools()` at `create()` time; pass `names=[...]` to expose a subset).
- `execute(name, args)` — `call_tool`; text content → `ToolResult.output`;
  `isError=True` → recoverable `ToolResult(ok=False)`; an unknown name → recoverable
  `ToolResult(ok=False)`; a transport/protocol exception → raises `MCPDispatchError`
  (fatal — the EGO propagates it instead of feeding it back).
- `is_mutating(name)` / `requires_confirmation(name)` — from the tool's
  `annotations.readOnlyHint` / `destructiveHint`, so the EGO read-only mask and
  confirmation gate apply to MCP tools (absent hints → conservative: assumed
  mutating, no confirmation).

## 4. Working with a session you already manage

`MCPDispatcher` is SDK-free: if your host already holds an `mcp.ClientSession` (or
anything that exposes `await list_tools()` / `await call_tool(name, args)`), build
the dispatcher directly — no transport helper needed:

```python
dispatcher = await MCPDispatcher.create(my_session)
```

## 5. Composing with skills / native tools

A persona's `allowed_modules` may mix sources. Each is a `ToolDispatcher`; merge:

```python
from cogno_anima.tools import CompositeDispatcher
dispatcher = CompositeDispatcher([cortex_dispatcher, mcp_dispatcher, native_dispatcher])
```

The persona declares modules **by name**; the host resolves each to a source and
composes. The `ToolDispatcher` contract is the unifier.

## 6. What stays yours

The MCP servers themselves (the verticals / product — `cogno-praxis`), auth + key
rotation, connection pooling/reconnection policy, persona selection, metering
(`cogno-meter`). cogno-mcp is the adapter; you bring the servers and the policy.
