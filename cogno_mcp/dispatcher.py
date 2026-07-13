"""``MCPDispatcher`` — expose an MCP server's tools as a cogno-anima ToolDispatcher.

This is the bridge (symmetric to cogno-cortex's ``CortexDispatcher``): the EGO /
cogno-soma see an MCP server's tools as ordinary tools and never speak MCP. It
implements cogno-anima's ``ToolDispatcher`` + ``ToolPolicyDispatcher``.

Deliberately **SDK-free**: it works against any *session* object that quacks like
``mcp.ClientSession`` (``await list_tools()`` / ``await call_tool(name, args)``) and
any *tool* that quacks like ``mcp.types.Tool`` (``.name`` / ``.description`` /
``.inputSchema`` / ``.annotations``). Only the transport helpers in
``cogno_mcp.transports`` import the ``mcp`` SDK — so the valuable mapping logic
(schema conversion, ``CallToolResult`` → ``ToolResult``, policy from annotations)
is fully unit-testable with fakes, and the transport is the official SDK's job.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from cogno_anima.types import ToolResult

from cogno_mcp.errors import MCPDispatchError


def _content_to_text(result: Any) -> str:
    """Flatten an MCP ``CallToolResult`` into a single text payload.

    Joins text content blocks; non-text blocks are noted by type. Falls back to the
    structured content when there is no textual content.
    """
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            parts.append(getattr(block, "text", ""))
        elif btype:
            parts.append(f"[{btype}]")
    if parts:
        return "\n".join(p for p in parts if p)
    structured = getattr(result, "structuredContent", None)
    return "" if structured is None else str(structured)


class MCPDispatcher:
    """A cogno-anima ``ToolDispatcher`` (+ ``ToolPolicyDispatcher``) over one MCP session."""

    def __init__(self, session: Any, tools: Sequence[Any], *,
                 names: Optional[Sequence[str]] = None) -> None:
        """
        Args:
            session: an established MCP client session (``initialize()`` already called).
            tools:   the server's tools (from ``list_tools()``), cached for sync schema access.
            names:   the subset of tool names to expose; ``None`` → expose all.
        """
        self._session = session
        self._tools: dict[str, Any] = {t.name: t for t in tools}
        self._names = list(names) if names is not None else list(self._tools)

    @classmethod
    async def create(cls, session: Any, *, names: Optional[Sequence[str]] = None) -> "MCPDispatcher":
        """Connect to the session's tool list and build a dispatcher."""
        resp = await session.list_tools()
        return cls(session, resp.tools, names=names)

    def tools_schema(self) -> list[dict]:
        schemas: list[dict] = []
        for name in self._names:
            tool = self._tools.get(name)
            if tool is None:
                continue
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": getattr(tool, "description", "") or "",
                    "parameters": getattr(tool, "inputSchema", None) or {
                        "type": "object", "properties": {}},
                },
            })
        return schemas

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        if name not in self._tools:
            # hallucinated / unknown name → recoverable, the EGO self-corrects
            return ToolResult(output="", ok=False, error=f"unknown tool: {name}")
        side_effect = self.is_mutating(name)
        try:
            result = await self._session.call_tool(name, arguments)
        except Exception as exc:  # transport/protocol fault → fatal, EGO propagates
            raise MCPDispatchError(name, arguments, exc) from exc
        text = _content_to_text(result)
        if getattr(result, "isError", False):
            # a tool-level error is a recoverable business failure
            return ToolResult(output="", ok=False, error=text or "tool error",
                              side_effect=side_effect)
        return ToolResult(output=text, ok=True, side_effect=side_effect)

    # ── ToolPolicyDispatcher ──────────────────────────────────────────────
    def is_mutating(self, name: str) -> bool:
        ann = getattr(self._tools.get(name), "annotations", None)
        # read-only hint True → not mutating; otherwise conservative (assume mutating)
        return getattr(ann, "readOnlyHint", None) is not True

    def requires_confirmation(self, name: str) -> bool:
        ann = getattr(self._tools.get(name), "annotations", None)
        # only gate when the server explicitly marks the tool destructive
        return getattr(ann, "destructiveHint", None) is True
