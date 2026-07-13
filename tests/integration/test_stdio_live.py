"""Integration: MCPDispatcher against a REAL MCP server over stdio.

Spawns the reference FastMCP server (``ref_server.py``) as a subprocess via the
stdio transport, then exercises the full chain: list_tools → tools_schema, the
policy mapping from real server annotations, and call_tool → ToolResult. Requires
the ``mcp`` SDK (auto-skips otherwise); no network.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp.server.fastmcp", reason="mcp SDK not installed")

from cogno_mcp import MCPDispatcher, stdio_session  # noqa: E402

SERVER = str(Path(__file__).resolve().parent / "ref_server.py")


@pytest.mark.asyncio
async def test_dispatcher_over_real_stdio_server():
    async with stdio_session(sys.executable, args=[SERVER]) as session:
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


@pytest.mark.asyncio
async def test_role_gate_over_real_stdio_server():
    """Over a REAL MCP round-trip: a role gate HIDES a tool from a caller whose role can't call it
    (the model never sees it) and refuses it at execute (defence in depth); an allowed role sees +
    runs it."""
    from cogno_mcp.dispatcher import role_gate_from_map
    gate = role_gate_from_map({"wipe": {"ADMIN"}})
    async with stdio_session(sys.executable, args=[SERVER]) as session:
        guest = await MCPDispatcher.create(session, caller_role="GUEST", role_gate=gate)
        gnames = {s["function"]["name"] for s in guest.tools_schema()}
        assert "wipe" not in gnames and "add" in gnames        # hidden from GUEST, read stays
        res = await guest.execute("wipe", {"target": "x"})     # defence in depth
        assert res.ok is False and "may not call" in (res.error or "")

        admin = await MCPDispatcher.create(session, caller_role="ADMIN", role_gate=gate)
        assert "wipe" in {s["function"]["name"] for s in admin.tools_schema()}
        res2 = await admin.execute("wipe", {"target": "x"})
        assert res2.ok is True and "wiped x" in res2.output
