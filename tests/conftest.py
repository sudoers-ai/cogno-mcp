"""Test doubles: a fake MCP session + tool/result objects (no SDK needed)."""

from dataclasses import dataclass, field
from typing import Any, Optional

import pytest


@dataclass
class FakeAnnotations:
    readOnlyHint: Optional[bool] = None
    destructiveHint: Optional[bool] = None


@dataclass
class FakeTool:
    name: str
    description: str = ""
    inputSchema: dict = field(default_factory=dict)
    annotations: Optional[FakeAnnotations] = None


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeImageBlock:
    type: str = "image"


@dataclass
class FakeCallResult:
    content: list = field(default_factory=list)
    isError: bool = False
    structuredContent: Any = None


@dataclass
class _ListToolsResp:
    tools: list


class FakeSession:
    """Quacks like mcp.ClientSession for the dispatcher's purposes."""

    def __init__(self, tools, *, results=None, raise_on=None):
        self._tools = tools
        self._results = results or {}          # name -> FakeCallResult
        self._raise_on = raise_on or set()     # names that raise on call_tool
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self):
        return _ListToolsResp(tools=self._tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if name in self._raise_on:
            raise ConnectionError("transport down")
        return self._results.get(name, FakeCallResult(content=[FakeTextBlock(f"{name} ok")]))


@pytest.fixture
def tools():
    return [
        FakeTool("get_weather", "Get the weather.",
                 inputSchema={"type": "object", "properties": {"city": {"type": "string"}},
                              "required": ["city"]},
                 annotations=FakeAnnotations(readOnlyHint=True)),
        FakeTool("delete_file", "Delete a file.",
                 annotations=FakeAnnotations(readOnlyHint=False, destructiveHint=True)),
        FakeTool("write_note", "Write a note."),   # no annotations
    ]
