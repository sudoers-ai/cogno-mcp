# Logging in cogno-mcp

This library follows the Cogno house rule: **libraries emit, the host configures.**

- Any module that logs does `logger = logging.getLogger(__name__)` and emits lazy
  `key=value` messages. The library installs **no** handlers/formatters and never
  calls `basicConfig`.
- The host attaches its handler and sets the level per package, e.g.
  `logging.getLogger("cogno_mcp").setLevel(logging.INFO)`.

## Level policy
- **ERROR** — never emitted. A transport/protocol fault becomes a raised
  `MCPDispatchError` (the EGO propagates it); a tool-level error becomes a
  recoverable `ToolResult(ok=False)`; a missing SDK raises `MCPUnavailableError`.
  The host decides how to surface failures.
- **WARNING / INFO / DEBUG** — none from cogno-mcp itself. The underlying `mcp`
  SDK does its own logging under the `mcp` logger namespace (configure it
  separately if you want it).

## What gets logged
- `cogno_mcp.*` — nothing. Outcomes travel as return values / exceptions, not logs.

Tool arguments, results, and server URLs are **never** logged by cogno-mcp. Token
usage is not applicable here (MCP tools execute on the server; metering is the
host's via `cogno-meter`).
