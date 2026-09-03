"""Integration: MCPDispatcher against a REAL MCP server over stdio.

Spawns the reference FastMCP server (``ref_server.py``) as a subprocess via the
stdio transport, then exercises the full chain: list_tools → tools_schema, the
policy mapping from real server annotations, and call_tool → ToolResult. Requires
the ``mcp`` SDK (auto-skips otherwise); no network.
"""

import pytest

pytest.importorskip("mcp.server.fastmcp", reason="mcp SDK not installed")

from cogno_mcp import MCPDispatcher, stdio_session  # noqa: E402
from tests.integration.conftest import SERVER      # noqa: E402


@pytest.mark.asyncio
async def test_dispatcher_over_real_stdio_server(python, ref_server_env):
    async with stdio_session(python, args=[SERVER], env=ref_server_env) as session:
        disp = await MCPDispatcher.create(session)

        names = {s["function"]["name"] for s in disp.tools_schema()}
        assert {"add", "wipe"} <= names

        # input schema came from the real server
        add = next(s for s in disp.tools_schema() if s["function"]["name"] == "add")
        assert "a" in add["function"]["parameters"]["properties"]

        # policy from the server's real annotations
        assert disp.is_mutating("add") is False
        assert disp.is_mutating("wipe") is True
        assert disp.requires_confirmation("wipe") is True
        assert disp.requires_confirmation("add") is False

        # call a tool end-to-end
        res = await disp.execute("add", {"a": 2, "b": 3})
        assert res.ok is True
        assert "5" in res.output
        assert res.side_effect is False
