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
| `_meta["cogno-mcp/needs_confirmation"] = true` | `ToolResult.needs_confirmation` (the EGO **holds** the call) |
| `_meta["cogno-mcp/confirm_arguments"]` | `MCPToolResult.confirm_arguments` (what to add on confirmation) |

## A tool that asks before it commits

The EGO has three confirmation gates. Gate A masks writes when the *user* sounded tentative;
gate B holds a tool the host declared destructive, **by name, before it runs**; gate C is the
tool itself saying, about **this call** and what it just **read**, *"I did not commit — ask
first"*. Only gate C can tell the user *which* row it is about to delete, and of what value,
because only it has read.

A server raises it from the `_meta` of its result — or of one of its content blocks, which is
the placement the Python SDK's server side can actually fill:

```python
from mcp.types import TextContent
from cogno_mcp import META_CONFIRM_ARGUMENTS, META_NEEDS_CONFIRMATION

@mcp.tool(annotations={"readOnlyHint": False})          # mutating, NOT destructiveHint
def remove_entry(query: str, confirm_tx_id: str = ""):
    if confirm_tx_id:
        return commit(confirm_tx_id)
    row = read_one(query)
    return TextContent(
        type="text",
        text=f"Would delete {row.desc} {row.amount} of {row.date}. Confirm?",
        _meta={META_NEEDS_CONFIRMATION: True,
               META_CONFIRM_ARGUMENTS: {"confirm_tx_id": row.id}},
    )
```

Three things decide whether this works, and each has cost someone a turn:

* **Do not declare the tool `destructiveHint`.** Gate B resolves per *name*, before anything
  runs, so it holds the call and the tool never reads — the user gets "this is destructive"
  instead of "this row, this amount". A tool whose danger is per *call* has to be allowed to
  run in order to say so.
* **`true`, the boolean.** The flag is a promise that nothing was committed, and the EGO
  records the call `ok=False, side_effect=False` on the strength of it. A truthy `"false"` is
  not that promise, so it is not read as one.
* **Answer the question you were asked.** `confirm_arguments` is optional and names what *this
  tool* needs in order to act on a "yes" — an id, not a boolean, if a row can move in between.
  The host owns the consent; the tool owns what consent means to it. The core never invents an
  argument name.

`_meta` and not `structuredContent`: the latter is the tool's business payload, validated
against its `outputSchema`, and returning a dict makes the *text* a JSON dump of that dict —
replacing the grounded sentence that is the whole point. And not `isError`, which already means
a recoverable failure the EGO feeds back for self-correction; a proposal is not a failure.

## Skills + MCP + native together

Each source is a `ToolDispatcher`; merge them per persona:

```python
from cogno_anima.tools import CompositeDispatcher
dispatcher = CompositeDispatcher([cortex_dispatcher, mcp_dispatcher, native_dispatcher])
```

The `ToolDispatcher` contract is the unifier — skill / MCP / native are just sources.

## The Cogno ecosystem

`cogno-mcp` is one organ of **[Cogno](https://github.com/sudoers-ai)** — a family of
small, composable, Apache-2.0 libraries that together form a complete
conversational-agent platform. Each library owns a single concern and stays
infra-agnostic; a **host** assembles them into a running agent:

![The Cogno ecosystem](docs/assets/cogno-ecosystem.svg)

The open-source libraries are the organs; the **host is the body** that joins
them. Our reference host — `cogno-host`, with its `cogno-ui` dashboard — is the
private product layer, but it holds no special powers: everything it does rides
on the public seams documented in each library's `docs/HOST_INTEGRATION.md`, so
you can assemble a body of your own.

## Development

```bash
pip install -e ".[dev]"
pytest tests/unit -q            # SDK-free dispatcher logic against fakes
pytest tests/integration -q     # MCPDispatcher vs a real FastMCP server over stdio
ruff check cogno_mcp tests && mypy cogno_mcp
python examples/host_min.py     # spawns a local MCP server and calls a tool
```

Apache-2.0.
