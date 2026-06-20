"""A tiny reference MCP server (FastMCP) for the integration test.

Spawned over stdio by ``test_stdio_live.py``. Exposes one read-only tool and one
tool annotated destructive, so the dispatcher's schema + policy mapping can be
verified against a real MCP server (not a fake).
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("cogno-mcp-ref")


@mcp.tool(annotations={"readOnlyHint": True})
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def wipe(target: str) -> str:
    """Pretend to delete something (destructive)."""
    return f"wiped {target}"


if __name__ == "__main__":
    mcp.run()
