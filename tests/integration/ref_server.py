"""A tiny reference MCP server (FastMCP) for the integration test.

Spawned over stdio by ``test_stdio_live.py``. Exposes one read-only tool, one tool annotated
destructive, and one that PROPOSES before it commits — so the dispatcher's schema mapping, its
policy mapping and its confirmation channel can each be verified against a real MCP server
(not a fake), over the real transport, with the real SDK.

``remove_entry`` is modelled on the shape the ecosystem actually ships (cogno-praxis' ledger
removal): it READS, proposes the exact row it would delete, and commits only when called again
with the id of that row. The confirmation is an id and not a yes/no on purpose — a new entry
landing between the proposal and the go-ahead must not be able to move the target.
"""

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from cogno_mcp import META_CONFIRM_ARGUMENTS, META_NEEDS_CONFIRMATION

mcp = FastMCP("cogno-mcp-ref")

# A two-row ledger, so a substring search can match more than one and the proposal has
# something to be grounded IN.
LEDGER: "dict[str, dict[str, str]]" = {
    "tx-1": {"date": "2026-08-03", "desc": "internet", "amount": "120.00"},
    "tx-2": {"date": "2026-09-03", "desc": "internet extra", "amount": "40.00"},
}


@mcp.tool(annotations={"readOnlyHint": True})
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def wipe(target: str) -> str:
    """Pretend to delete something (destructive)."""
    return f"wiped {target}"


def _propose_or_remove(query: str, confirm_tx_id: str):
    """Read the ledger, then either propose the row or delete the one named."""
    matches = {k: v for k, v in LEDGER.items() if query.lower() in v["desc"].lower()}
    if confirm_tx_id:
        row = LEDGER.pop(confirm_tx_id, None)
        return f"Removed {row['desc']} {row['amount']}" if row else "no such entry"
    if not matches:
        return "no match"
    tx_id, row = sorted(matches.items())[0]
    # The proposal is PROSE — grounded in what was just read — and the machine-readable half
    # rides in the block's ``_meta`` beside it. That is the whole point of choosing ``_meta``
    # over ``structuredContent``: the EGO's trace and the SUPEREGO's voicing get the sentence,
    # not a JSON dump of it.
    return TextContent(
        type="text",
        text=(f"NOT REMOVED yet. Would delete {row['desc']} {row['amount']} of {row['date']}"
              f"; {len(matches) - 1} other row(s) also match '{query}'. Confirm?"),
        _meta={META_NEEDS_CONFIRMATION: True,
               META_CONFIRM_ARGUMENTS: {"confirm_tx_id": tx_id}},
    )


# Mutating, and NOT declared destructive — which is the annotation a tool of this shape wants,
# and the reason is the whole distinction between the two gates. ``destructiveHint`` is a claim
# about the NAME, resolved before anything runs; the EGO's gate B holds on it and the tool then
# never executes, so the grounded question it was going to ask is never asked. A tool whose
# danger is per-CALL — this row, this amount, these two siblings the same search caught — has
# to be allowed to RUN in order to say so. See ``test_gate_b_pre_empts_gate_c_by_annotation``.
@mcp.tool(annotations={"readOnlyHint": False})
def remove_entry(query: str, confirm_tx_id: str = ""):
    """Remove a ledger entry. The first call READS and proposes; call again with confirm_tx_id."""
    return _propose_or_remove(query, confirm_tx_id)


# The SAME behaviour under a ``destructiveHint`` — kept only so the pre-emption above can be
# measured rather than asserted in prose.
@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def purge_entry(query: str, confirm_tx_id: str = ""):
    """Same as remove_entry, but the server declares the NAME destructive."""
    return _propose_or_remove(query, confirm_tx_id)


if __name__ == "__main__":
    mcp.run()
