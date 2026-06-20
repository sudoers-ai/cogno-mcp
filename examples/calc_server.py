"""A minimal MCP server (FastMCP) used by host_min.py. Run indirectly via stdio."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("calc")


@mcp.tool(annotations={"readOnlyHint": True})
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


if __name__ == "__main__":
    mcp.run()
