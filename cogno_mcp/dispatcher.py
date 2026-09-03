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

# ── The confirmation channel: how an MCP server raises cogno-anima's THIRD gate ──────────
#
# cogno-anima's EGO has three confirmation gates. Gate A masks writes when the USER was
# tentative; gate B holds a tool the host DECLARED destructive, by NAME, before it runs; gate C
# is the tool itself saying, about THIS call and what it just READ, "I did not commit — ask
# first". Only gate C can know that *this* entry is the one a substring search matched, of that
# value and that date, because only it has read.
#
# cogno-cortex has carried gate C since it was built (``SkillResult.needs_confirmation`` →
# ``ToolResult.needs_confirmation``). This bridge did not, so a skill reached over MCP could
# not raise it at all: measured 2026-09-02, ``grep -rn needs_confirmation`` in this repository
# returned ZERO hits, and cogno-praxis' two-step ledger removal — which proposes with the row
# it read and commits only on a second call — arrives at the EGO as ordinary tool TEXT.
#
# **Which channel, measured against the SDK this repo pins** (``mcp>=1.0,<2``, measured on
# 1.16.0), because three looked plausible and two are not usable:
#
#   ``isError``            already taken, and it would be a lie: a proposal is not a failure.
#                          It maps to a RECOVERABLE error the EGO feeds back for self-correction.
#   ``annotations``        per tool NAME, resolved before the call. That is gate B, which
#                          already reads them. A per-CALL fact cannot be expressed there by
#                          construction.
#   ``CallToolResult._meta`` the MCP spec's designated general-purpose extension field — but
#                          **the SDK's server side cannot fill it**: both the low-level
#                          ``Server.call_tool`` handler and FastMCP construct the result
#                          themselves (``CallToolResult(content=..., structuredContent=...,
#                          isError=False)``) with no pass-through. Measured: a tool returning a
#                          ``CallToolResult`` gets it JSON-serialised into the text instead.
#                          Still READ here — a non-Python server can set it, and the client
#                          parses it.
#   ``structuredContent``  reachable, and it survives the round trip typed. But it is the
#                          tool's business payload, validated against its ``outputSchema``, and
#                          with FastMCP a dict return makes the TEXT a JSON dump of that dict —
#                          which would replace the grounded prose that is the entire reason
#                          gate C is worth more than gate B.
#   **a content block's own ``_meta``**  reachable (measured: a ``TextContent`` returned by a
#                          FastMCP tool passes through verbatim, ``_meta`` included), leaves
#                          ``outputSchema`` untouched, and keeps the proposal PROSE as the
#                          text. This is the one.
#
# So: ONE key, in the field the spec designates for exactly this, read at BOTH placements the
# protocol offers. A text convention ("the output starts with NOT REMOVED") was never a
# candidate — that is a lexicon pretending to be a contract, and it breaks on the first
# rewording, in the silent direction.
META_NEEDS_CONFIRMATION = "cogno-mcp/needs_confirmation"

# The arguments the TOOL asks to be added to this same call when the user agrees. Optional, and
# it exists because the confirmation a real skill needs is not always a yes/no: cogno-praxis'
# ledger removal confirms with ``confirm_tx_id=<row id>`` precisely so a new entry landing
# between the proposal and the "go ahead" cannot move the target. The host holds the CONSENT;
# only the tool knows what it needs in order to act on it.
#
# The core never invents an argument name — and it still does not: the name here is the TOOL'S,
# stated by the tool, in its own reply. What the host decides is WHETHER (the user confirmed
# this call), never WHAT.
META_CONFIRM_ARGUMENTS = "cogno-mcp/confirm_arguments"


def _meta_of(obj: Any) -> Any:
    """The ``_meta`` mapping of a result or a content block, whatever the client models it as.

    The SDK exposes it as ``.meta`` (aliased ``_meta`` on the wire); a fake or a hand-rolled
    client may keep the wire name. Read both rather than pinning one — this dispatcher is
    deliberately SDK-free and works against anything that quacks.
    """
    meta = getattr(obj, "meta", None)
    if meta is None:
        meta = getattr(obj, "_meta", None)
    return meta if isinstance(meta, dict) else None


def _metas(result: Any) -> "list[dict]":
    """Every ``_meta`` this result carries: the result's own, then each content block's.

    Two placements, ONE key. The result level is what a non-Python server sets (and what the
    spec points at first); the block level is the one the Python SDK's server side can actually
    reach — measured, see ``META_NEEDS_CONFIRMATION``. Reading only the first would define a
    channel no server in this ecosystem can use; reading only the second would ignore the
    protocol's own answer.
    """
    out: list[dict] = []
    top = _meta_of(result)
    if top is not None:
        out.append(top)
    for block in getattr(result, "content", None) or []:
        blk = _meta_of(block)
        if blk is not None:
            out.append(blk)
    return out


def _asks_confirmation(result: Any) -> bool:
    """Did the tool say "I ran, I read, I did not commit — ask first"?

    ``is True`` and not truthiness, because this flag is a PROMISE that nothing was committed,
    and the cost of hearing one that was not made is not symmetric. A raised gate records the
    call ``ok=False, side_effect=False``, i.e. the pipeline asserts that this turn wrote
    nothing; grant that to a server that sent the string ``"false"`` (truthy) or a stray ``1``
    and the pipeline says "nothing was written" about a write that happened — which is the
    exact false record `committed_this_turn` exists to prevent. A malformed value is a
    malformed server; making its promise up on its behalf is worse than not hearing it.

    ANY carrier suffices — the flag is about the CALL, and a server puts it on the block that
    carries the proposal.
    """
    return any(m.get(META_NEEDS_CONFIRMATION) is True for m in _metas(result))


def _confirm_arguments(result: Any) -> "dict[str, Any]":
    """The arguments the tool asks to have added when the user agrees (may be empty).

    First carrier wins; a non-mapping is ignored rather than coerced, for the reason above —
    a confirmation channel that guesses is not one.
    """
    for m in _metas(result):
        args = m.get(META_CONFIRM_ARGUMENTS)
        if isinstance(args, dict) and args:
            return dict(args)
    return {}


class MCPToolResult(ToolResult):
    """A ``ToolResult`` that also carries what the TOOL asked for on confirmation.

    A subclass and not a new type: every existing consumer (the EGO, the host's wrapper chain,
    `committed_this_turn`) reads the declared fields and is untouched, while a host that wants
    to close the round trip can read this one off the object the chain already passes through
    unchanged. ``cogno_anima.ToolResult`` deliberately has no such field — what a skill needs in
    order to commit is the skill's business, not the pipeline's — so the carrier belongs to the
    bridge that speaks that skill's protocol.
    """

    confirm_arguments: dict[str, Any] = {}


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
        # Pure transport: the tool's promise travels, this layer decides nothing about it —
        # the same shape ``CortexDispatcher.execute`` takes for skills. What it decides is
        # nothing; what it must not do is CONTRADICT the promise in the next field along.
        asks = _asks_confirmation(result)
        confirm_args = _confirm_arguments(result) if asks else {}
        if getattr(result, "isError", False):
            # A tool-level error is a recoverable business failure — and it reports NO side
            # effect. ``mutating`` comes from the tool's annotations, read per NAME before the
            # call, so copying it here would say "this write happened" about a write the server
            # rejected. The per-name question keeps its own answer (``is_mutating``); what stops
            # is the RESULT claiming it.
            return MCPToolResult(output="", ok=False, error=text or "tool error",
                                 side_effect=False, needs_confirmation=asks,
                                 confirm_arguments=confirm_args)
        # ``and not asks`` — a PROPOSAL committed nothing, and ``side_effect`` means "did THIS
        # call write?" (cogno-anima narrowed it from the per-NAME fact on 2026-09-01;
        # ``ToolExecution.tool_mutating`` carries that one now). Stamping both would put a
        # contradiction inside one object: "I did not commit" beside "this call wrote".
        #
        # Not a style point — it has a named victim. The host's ``CommitRecordingDispatcher``
        # records a commit from the RAW result on ``ok and side_effect``, and its own module
        # note calls this exact combination out as theoretical *because no producer emitted it*
        # ("Nenhum produtor o faz hoje"): a proposal reaching it as ok+side_effect makes the
        # turn declare a write that never happened, and since host#489 that declaration routes
        # the turn to a human. This bridge would have been that first producer. cogno-cortex
        # still stamps ``side_effect=mutating`` on an asking call — flagged to its owner rather
        # than fixed from here; it is another repository and another review.
        return MCPToolResult(output=text, ok=True, side_effect=mutating and not asks,
                             needs_confirmation=asks, confirm_arguments=confirm_args)

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
