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

import asyncio
import json
from typing import Any, Optional, Sequence

from cogno_anima.types import ToolResult

from cogno_mcp.errors import MCPDispatchError

# Default cap on the server-supplied tool ``description`` rendered into the EGO prompt: a
# compromised/verbose MCP server could otherwise inject an unbounded blob (prompt injection +
# num_ctx starvation). The host can raise/lower it per dispatcher.
DEFAULT_MAX_DESCRIPTION_CHARS = 2048


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
    if structured is None:
        return ""
    # JSON so the model consuming this sees valid syntax, not Python repr ({'a': True}).
    try:
        return json.dumps(structured, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(structured)


class MCPDispatcher:
    """A cogno-anima ``ToolDispatcher`` (+ ``ToolPolicyDispatcher``) over one MCP session."""

    def __init__(self, session: Any, tools: Sequence[Any], *,
                 names: Optional[Sequence[str]] = None,
                 call_timeout: Optional[float] = 30.0,
                 trust_annotations: bool = True,
                 max_description_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS) -> None:
        """
        Args:
            session: an established MCP client session (``initialize()`` already called).
            tools:   the server's tools (from ``list_tools()``), cached for sync schema access.
            names:   the subset of tool names to expose; ``None`` → expose all.
            call_timeout: seconds to wait for a tool call / list before treating the server as
                hung (→ fatal ``MCPDispatchError``). ``None`` disables the timeout (wait forever).
            trust_annotations: when ``False``, IGNORE the server's ``readOnlyHint``/
                ``destructiveHint`` — every tool is treated as mutating AND confirmation-requiring.
                Set it for a less-trusted third-party server: the MCP SDK warns that clients must
                not make tool-safety decisions from an untrusted server's own annotations.
            max_description_chars: cap on the tool ``description`` rendered into the EGO prompt.
        """
        self._session = session
        self._tools: dict[str, Any] = {t.name: t for t in tools}
        self._names = list(names) if names is not None else list(self._tools)
        self._call_timeout = call_timeout
        self._trust_annotations = trust_annotations
        self._max_description_chars = max_description_chars

    @classmethod
    async def create(cls, session: Any, *, names: Optional[Sequence[str]] = None,
                     call_timeout: Optional[float] = 30.0,
                     trust_annotations: bool = True,
                     max_description_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS) -> "MCPDispatcher":
        """Connect to the session's tool list and build a dispatcher."""
        try:
            resp = await asyncio.wait_for(session.list_tools(), timeout=call_timeout)
        except asyncio.TimeoutError as exc:
            raise MCPDispatchError("list_tools", {}, exc) from exc
        return cls(session, resp.tools, names=names, call_timeout=call_timeout,
                   trust_annotations=trust_annotations, max_description_chars=max_description_chars)

    def tools_schema(self) -> list[dict]:
        schemas: list[dict] = []
        for name in self._names:
            tool = self._tools.get(name)
            if tool is None:
                continue
            desc = (getattr(tool, "description", "") or "")[:self._max_description_chars]
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": desc,
                    "parameters": getattr(tool, "inputSchema", None) or {
                        "type": "object", "properties": {}},
                },
            })
        return schemas

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        if name not in self._tools:
            # hallucinated / unknown name → recoverable, the EGO self-corrects
            return ToolResult(output="", ok=False, error=f"unknown tool: {name}")
        mutating = self.is_mutating(name)
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(name, arguments), timeout=self._call_timeout)
        except asyncio.TimeoutError as exc:  # hung server → fatal, don't pin the EGO worker forever
            raise MCPDispatchError(name, arguments, exc) from exc
        except Exception as exc:  # transport/protocol fault → fatal, EGO propagates
            raise MCPDispatchError(name, arguments, exc) from exc
        text = _content_to_text(result)
        if getattr(result, "isError", False):
            # A tool-level error is a recoverable business failure — and it reports NO side
            # effect. ``mutating`` comes from the tool's annotations, read per NAME before the
            # call, so copying it here would say "this write happened" about a write the server
            # rejected. The per-name question keeps its own answer (``is_mutating``); what stops
            # is the RESULT claiming it.
            return ToolResult(output="", ok=False, error=text or "tool error",
                              side_effect=False)
        return ToolResult(output=text, ok=True, side_effect=mutating)

    # ── ToolPolicyDispatcher ──────────────────────────────────────────────
    def is_mutating(self, name: str) -> bool:
        if not self._trust_annotations:
            return True                       # untrusted server → assume every tool mutates
        ann = getattr(self._tools.get(name), "annotations", None)
        # read-only hint True → not mutating; otherwise conservative (assume mutating)
        return getattr(ann, "readOnlyHint", None) is not True

    def requires_confirmation(self, name: str) -> bool:
        # Confirm a tool the server EXPLICITLY marks destructive (``destructiveHint=True``). The
        # convention across the ecosystem's own servers is that additive writes set only
        # ``readOnlyHint=False`` (no destructiveHint) and are NOT auto-confirmed — the host layer
        # (e.g. its ConfirmingDispatcher) decides which additive commits need an OK. Do NOT treat a
        # missing destructiveHint as destructive: it would gate-B-hold every additive write
        # (add_income, update_status, …) that the host expects to commit / confirm via prompt.
        # For a LESS-TRUSTED server the host opts into ``trust_annotations=False`` → confirm every
        # mutating tool (the SDK warns not to trust an untrusted server's own safety hints).
        if not self.is_mutating(name):
            return False
        if not self._trust_annotations:
            return True                       # untrusted server → always confirm a mutating tool
        ann = getattr(self._tools.get(name), "annotations", None)
        return getattr(ann, "destructiveHint", None) is True
