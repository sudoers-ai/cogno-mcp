"""Unit tests for MCPDispatcher — the SDK-free mapping logic, against fakes."""

import pytest

from cogno_anima.tools import ToolDispatcher, ToolPolicyDispatcher

from cogno_mcp import MCPDispatcher, MCPDispatchError
from tests.conftest import (
    FakeAnnotations, FakeCallResult, FakeImageBlock, FakeSession, FakeTextBlock, FakeTool)


def _disp(tools, **session_kw):
    return MCPDispatcher(FakeSession(tools, **session_kw), tools)


def test_satisfies_anima_protocols(tools):
    disp = _disp(tools)
    assert isinstance(disp, ToolDispatcher)
    assert isinstance(disp, ToolPolicyDispatcher)


async def test_create_lists_tools(tools):
    session = FakeSession(tools)
    disp = await MCPDispatcher.create(session)
    assert {s["function"]["name"] for s in disp.tools_schema()} == {
        "get_weather", "delete_file", "write_note"}


def test_tools_schema_carries_input_schema(tools):
    disp = _disp(tools)
    wx = next(s for s in disp.tools_schema() if s["function"]["name"] == "get_weather")
    assert wx["function"]["parameters"]["required"] == ["city"]
    assert wx["function"]["description"] == "Get the weather."


def test_tools_schema_default_params_when_missing(tools):
    disp = _disp(tools)
    note = next(s for s in disp.tools_schema() if s["function"]["name"] == "write_note")
    assert note["function"]["parameters"] == {"type": "object", "properties": {}}


def test_names_filter(tools):
    disp = MCPDispatcher(FakeSession(tools), tools, names=["get_weather"])
    assert [s["function"]["name"] for s in disp.tools_schema()] == ["get_weather"]


def test_names_filter_skips_unknown(tools):
    disp = MCPDispatcher(FakeSession(tools), tools, names=["get_weather", "ghost"])
    # an exposed name with no matching tool is skipped in the schema
    assert [s["function"]["name"] for s in disp.tools_schema()] == ["get_weather"]


async def test_execute_success(tools):
    session = FakeSession(tools, results={
        "get_weather": FakeCallResult(content=[FakeTextBlock("Sunny, 25C")])})
    disp = MCPDispatcher(session, tools)
    res = await disp.execute("get_weather", {"city": "Rio"})
    assert res.ok is True
    assert res.output == "Sunny, 25C"
    assert session.calls == [("get_weather", {"city": "Rio"})]


async def test_execute_joins_text_blocks(tools):
    session = FakeSession(tools, results={
        "write_note": FakeCallResult(content=[FakeTextBlock("line1"), FakeTextBlock("line2")])})
    res = await MCPDispatcher(session, tools).execute("write_note", {})
    assert res.output == "line1\nline2"


async def test_execute_non_text_block_noted(tools):
    session = FakeSession(tools, results={
        "write_note": FakeCallResult(content=[FakeImageBlock()])})
    res = await MCPDispatcher(session, tools).execute("write_note", {})
    assert res.output == "[image]"


async def test_execute_structured_fallback(tools):
    session = FakeSession(tools, results={
        "write_note": FakeCallResult(content=[], structuredContent={"saved": True})})
    res = await MCPDispatcher(session, tools).execute("write_note", {})
    assert "saved" in res.output


async def test_execute_tool_error_is_recoverable(tools):
    session = FakeSession(tools, results={
        "delete_file": FakeCallResult(content=[FakeTextBlock("permission denied")], isError=True)})
    res = await MCPDispatcher(session, tools).execute("delete_file", {})
    assert res.ok is False
    assert res.error == "permission denied"


async def test_execute_unknown_tool_is_recoverable(tools):
    res = await _disp(tools).execute("ghost", {})
    assert res.ok is False
    assert "unknown tool" in (res.error or "")


async def test_transport_fault_raises_dispatch_error(tools):
    disp = _disp(tools, raise_on={"get_weather"})
    with pytest.raises(MCPDispatchError, match="failed") as ei:
        await disp.execute("get_weather", {"city": "Rio"})
    assert ei.value.tool == "get_weather"


async def test_side_effect_reflects_mutating(tools):
    session = FakeSession(tools)
    disp = MCPDispatcher(session, tools)
    read_res = await disp.execute("get_weather", {"city": "Rio"})
    write_res = await disp.execute("delete_file", {})
    assert read_res.side_effect is False     # readOnlyHint=True
    assert write_res.side_effect is True     # readOnlyHint=False


def test_policy_from_annotations(tools):
    disp = _disp(tools)
    assert disp.is_mutating("get_weather") is False        # readOnlyHint True
    assert disp.is_mutating("delete_file") is True         # readOnlyHint False
    assert disp.is_mutating("write_note") is True          # no annotations → conservative
    assert disp.requires_confirmation("delete_file") is True   # destructiveHint True
    assert disp.requires_confirmation("get_weather") is False  # read-only never confirms
    # no annotations → mutating + destructiveHint DEFAULTS true (MCP spec) → confirm (fail-safe;
    # was False, which let a spec-compliant destructive tool that omitted the hint bypass gate B).
    assert disp.requires_confirmation("write_note") is True


def test_explicitly_additive_write_does_not_confirm():
    # a mutating tool the server marks destructiveHint=False (additive: create/append) skips the gate
    additive = FakeTool("append_log", "Append a line.",
                        annotations=FakeAnnotations(readOnlyHint=False, destructiveHint=False))
    disp = MCPDispatcher(FakeSession([additive]), [additive])
    assert disp.is_mutating("append_log") is True
    assert disp.requires_confirmation("append_log") is False


def test_policy_unknown_name_conservative(tools):
    disp = _disp(tools)
    assert disp.is_mutating("ghost") is True
    assert disp.requires_confirmation("ghost") is True     # conservative: unknown → confirm


def test_untrusted_server_ignores_annotations(tools):
    # a less-trusted server's readOnlyHint=True must NOT let a tool bypass the gates
    disp = MCPDispatcher(FakeSession(tools), tools, trust_annotations=False)
    assert disp.is_mutating("get_weather") is True             # readOnlyHint=True ignored
    assert disp.requires_confirmation("get_weather") is True   # always confirm under distrust


async def test_hung_server_times_out_to_fatal():
    # a call that never returns must not pin the worker forever → fatal MCPDispatchError
    import asyncio

    class HangingSession(FakeSession):
        async def call_tool(self, name, arguments):
            await asyncio.sleep(10)   # never returns within the timeout

    tool = FakeTool("slow", "Slow tool.", annotations=FakeAnnotations(readOnlyHint=True))
    disp = MCPDispatcher(HangingSession([tool]), [tool], call_timeout=0.05)
    with pytest.raises(MCPDispatchError):
        await disp.execute("slow", {})


def test_description_is_capped_in_schema():
    big = FakeTool("verbose", "x" * 10_000, annotations=FakeAnnotations(readOnlyHint=True))
    disp = MCPDispatcher(FakeSession([big]), [big], max_description_chars=100)
    schema = disp.tools_schema()[0]
    assert len(schema["function"]["description"]) == 100


async def test_structured_content_serialized_as_json():
    tool = FakeTool("s", "s", annotations=FakeAnnotations(readOnlyHint=True))
    session = FakeSession([tool], results={"s": FakeCallResult(structuredContent={"saved": True})})
    disp = MCPDispatcher(session, [tool])
    res = await disp.execute("s", {})
    assert res.output == '{"saved": true}'   # JSON, not Python repr {'saved': True}
