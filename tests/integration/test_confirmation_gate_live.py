"""End-to-end: a tool on a REAL MCP server raises gate C, and the REAL EGO holds it.

A field that travels is not a feature. This suite exists because the confirmation channel
could otherwise be landed, be correct, and be reachable by nobody — the same shape as the
defect it repairs, one layer up. So nothing here is a double: a FastMCP server runs in its own
process over stdio, ``MCPDispatcher`` maps its reply, and ``cogno_anima.EgoStage`` — the actual
stage, not a stand-in — decides what to do with it. The only test double is the model.

What is pinned, in order of what each would cost if it broke:

  1. the EGO HOLDS the call: nothing executed, nothing recorded as written, and
     ``committed_this_turn`` says so;
  2. the PROPOSAL TEXT survives to the trace — the sentence the tool wrote after reading, which
     is the entire reason gate C is worth more than gate B;
  3. the round trip CLOSES: replayed with the argument the tool itself named, the write lands.
     Its twin — the same replay WITHOUT that argument — is red on purpose: it shows the wiring
     is load-bearing rather than decorative, and it is the exact failure a host that forgets
     the return trip would ship;
  4. a tool the server declares ``destructiveHint`` never reaches gate C at all, because gate B
     holds it by NAME first. Measured here rather than reasoned about, because it decides how a
     server must annotate a tool of this shape — and the ecosystem's first producer
     (cogno-praxis' ``remove_by_search``) is annotated the other way today.

Each test opens its OWN session instead of sharing a fixture. Two reasons, both load-bearing:
an async-generator fixture enters the transport's cancel scope in one task and leaves it in
another, which anyio refuses outright; and a fresh server process means a fresh ledger, so a
test that deletes a row cannot decide what its neighbour measures.
"""

import json
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("mcp.server.fastmcp", reason="mcp SDK not installed")

from cogno_anima import metakeys as mk                                        # noqa: E402
from cogno_anima.stages.ego import EgoStage                                   # noqa: E402
from cogno_anima.types import (                                               # noqa: E402
    IntentResult, NoumenoResult, PipelineContext, StageMetrics, committed_this_turn)
from cogno_synapse.base import ToolCallingBackend                             # noqa: E402

from cogno_mcp import MCPDispatcher, stdio_session                            # noqa: E402
from tests.integration.conftest import SERVER                                 # noqa: E402

SYS = "You are an executor. Use the tools to manage the ledger."


@asynccontextmanager
async def live(python, env, **kwargs):
    async with stdio_session(python, args=[SERVER], env=env) as session:
        yield await MCPDispatcher.create(session, **kwargs)


class ScriptedTextBackend:
    """A text-only model: ``generate`` + ``model``, so it never satisfies ``ToolCallingBackend``.

    Deliberate — it puts the EGO on the ``<TOOL_CALL>`` fallback path, the one the default
    ``OllamaBackend`` and the distilled student actually run. The gate must not depend on
    native function calling being available.
    """

    model = "scripted"

    def __init__(self, turns):
        self.turns = list(turns)

    async def generate(self, system, prompt):
        turn = self.turns.pop(0) if self.turns else {"content": "done"}
        text = turn.get("content", "")
        for name, args in turn.get("calls", []):
            text += f'\n<TOOL_CALL>{{"tool": "{name}", "args": {json.dumps(args)}}}</TOOL_CALL>'
        return text, 5, 3


def _m(stage):
    return StageMetrics(stage=stage, elapsed_ms=0.0, tokens_in=0, tokens_out=0, model="stub")


def _ctx(user="remove the internet entry", **meta):
    ctx = PipelineContext(
        user_input=user,
        noumeno=NoumenoResult(
            original=user, rewritten=user, context_turn="", language="en", drift_score=0.0,
            drift_tag="PASS_THROUGH", changed=False, confidence=0.9, change_subject=False,
            subject_similarity=1.0, context_used=False, preserved_terms=[],
            rewrite_warnings=[], metrics=_m("noumeno")),
        intent=IntentResult(
            intent_class="ACTION_REQUEST", sentiment="NEUTRAL", confidence=0.9,
            temporal_class="PRESENT", triad_signal="EGO", goal="remove a ledger entry",
            domains=["FINANCE"], entities_objects=["entry"], metrics=_m("ner")),
    )
    ctx.metadata.update(meta)
    return ctx


def test_the_fallback_path_is_the_one_under_test():
    """Pin the premise: a text-only backend must not be taken for a function-calling one."""
    assert not isinstance(ScriptedTextBackend([]), ToolCallingBackend)


@pytest.mark.asyncio
async def test_the_ego_holds_a_proposal_from_a_real_mcp_server(python, ref_server_env):
    async with live(python, ref_server_env) as disp:
        backend = ScriptedTextBackend([{"calls": [("remove_entry", {"query": "internet"})]}])
        ctx = await EgoStage().process(_ctx(), backend, disp, system_prompt=SYS)

        res = ctx.ego_result
        assert res is not None
        # (1) HELD — one call, and the loop stopped on it instead of carrying on.
        assert [h.tool for h in res.pending_confirmation] == ["remove_entry"]
        held = res.pending_confirmation[0]
        assert held.ok is False and held.side_effect is False
        # (2) the PROSE the tool wrote after reading, not a serialised payload
        assert "NOT REMOVED" in held.result and "120.00" in held.result
        assert "other row(s) also match" in held.result   # what only a reader could have said
        # nothing may read as a write, on any source the predicate unions
        assert committed_this_turn(ctx) is False
        assert res.has_side_effects is False

        # and the row is still there: asking again re-proposes the same one
        again = await disp.execute("remove_entry", {"query": "internet"})
        assert again.needs_confirmation is True
        assert again.confirm_arguments == {"confirm_tx_id": "tx-1"}


@pytest.mark.asyncio
async def test_the_confirmed_replay_commits_when_it_carries_what_the_tool_named(
        python, ref_server_env):
    """The VOLTA. The host holds the CONSENT; only the tool knows what it needs to act on it."""
    async with live(python, ref_server_env) as disp:
        proposal = await disp.execute("remove_entry", {"query": "internet"})
        assert proposal.needs_confirmation is True
        # What a host captures off the dispatcher's own reply. It cannot be taken from the
        # EGO's held ``ToolExecution``: that carries tool/arguments/result and nothing else, so
        # the argument the tool asked for is dropped at the stage boundary — which is exactly
        # why the return trip has to be wired where the result is still whole.
        confirmed_args = {"query": "internet", **proposal.confirm_arguments}

        ctx = await EgoStage().process(
            _ctx(**{mk.EGO_CONFIRMED: ["remove_entry"],
                    mk.EGO_CONFIRMED_CALLS: [{"tool": "remove_entry",
                                              "arguments": confirmed_args}]}),
            ScriptedTextBackend([{"content": "Removed."}]), disp, system_prompt=SYS)

        done = ctx.ego_result.tools_executed
        assert [t.tool for t in done] == ["remove_entry"]
        assert done[0].ok is True and done[0].side_effect is True
        assert "Removed internet 120.00" in done[0].result
        assert committed_this_turn(ctx) is True
        # gone for real, on the server, in the other process: the next proposal names the SIBLING
        assert (await disp.execute("remove_entry", {"query": "internet"})
                ).confirm_arguments == {"confirm_tx_id": "tx-2"}


@pytest.mark.asyncio
async def test_a_confirmed_replay_without_it_fails_loudly_instead_of_reporting_done(
        python, ref_server_env):
    """The twin that makes the one above mean something.

    Replay the held call with the STALE arguments — exactly what a host that stamps the confirm
    turn without the return trip sends today. The tool asks again, because from its side nothing
    has changed; ``EgoStage._refuse_if_still_asking`` then refuses to let the turn report a
    write that never happened. A silent success here would be the whole gate inverted: a
    promise of safety spent to ship "done" over an empty turn.
    """
    async with live(python, ref_server_env) as disp:
        ctx = await EgoStage().process(
            _ctx(**{mk.EGO_CONFIRMED: ["remove_entry"],
                    mk.EGO_CONFIRMED_CALLS: [{"tool": "remove_entry",
                                              "arguments": {"query": "internet"}}]}),
            ScriptedTextBackend([{"content": "Removed."}]), disp, system_prompt=SYS)

        done = ctx.ego_result.tools_executed
        assert [t.tool for t in done] == ["remove_entry"]
        assert done[0].ok is False and done[0].side_effect is False
        assert "did not receive the confirmation" in (done[0].error or "")
        assert committed_this_turn(ctx) is False
        # and the ledger is untouched — the refusal is not a label stuck on a write that happened
        assert (await disp.execute("remove_entry", {"query": "internet"})
                ).confirm_arguments == {"confirm_tx_id": "tx-1"}


@pytest.mark.asyncio
async def test_gate_b_pre_empts_gate_c_by_annotation(python, ref_server_env):
    """``destructiveHint=True`` on the NAME means the grounded question is never asked.

    ``purge_entry`` is byte-identical to ``remove_entry`` in behaviour and differs only in its
    annotation. Gate B resolves per NAME, BEFORE anything runs, so the tool never executes, never
    reads, and the EGO holds it with its own generic text — "is destructive and was NOT
    executed" — instead of "would delete internet 120.00 of 2026-08-03; 1 other row also
    matches". Both are safe. Only one of them tells the user which row.

    This is why a tool that proposes from what it READ must NOT be declared destructive, and it
    is a live finding rather than a design note: cogno-praxis' ``remove_by_search`` — the first
    producer this channel was built for — is annotated ``destructiveHint=True`` today, so wiring
    the channel alone would not reach it.
    """
    async with live(python, ref_server_env) as disp:
        assert disp.requires_confirmation("purge_entry") is True     # gate B owns this name
        assert disp.requires_confirmation("remove_entry") is False   # gate C's road is clear

        backend = ScriptedTextBackend([{"calls": [("purge_entry", {"query": "internet"})]}])
        ctx = await EgoStage().process(_ctx(), backend, disp, system_prompt=SYS)

        held = ctx.ego_result.pending_confirmation
        assert [h.tool for h in held] == ["purge_entry"]
        assert "is destructive and was NOT executed" in held[0].result
        assert "120.00" not in held[0].result       # nothing was read, so nothing can be quoted
        # …and the tool genuinely did not run: its ledger row is untouched
        assert (await disp.execute("remove_entry", {"query": "internet"})
                ).confirm_arguments == {"confirm_tx_id": "tx-1"}


@pytest.mark.asyncio
async def test_a_distrusted_server_loses_gate_c_to_gate_b(python, ref_server_env):
    """``trust_annotations=False`` makes every mutating tool gate-B destructive — including this
    one. The hold still happens (that is the point of distrust); what is lost is the grounded
    question, which is the price of not believing the server's own hints."""
    async with live(python, ref_server_env, trust_annotations=False) as disp:
        assert disp.requires_confirmation("remove_entry") is True
        backend = ScriptedTextBackend([{"calls": [("remove_entry", {"query": "internet"})]}])
        ctx = await EgoStage().process(_ctx(), backend, disp, system_prompt=SYS)
        held = ctx.ego_result.pending_confirmation
        assert [h.tool for h in held] == ["remove_entry"]
        assert "is destructive and was NOT executed" in held[0].result
