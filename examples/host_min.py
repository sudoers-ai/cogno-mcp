"""Minimal host wiring for cogno-mcp (offline — spawns a local MCP server).

Connects to the bundled ``calc_server.py`` over stdio, bridges its tools to
cogno-anima via MCPDispatcher, inspects the schema + policy, and calls a tool —
the same dispatcher you would hand to cogno-soma's EGO (merge with skills/native
via cogno_anima.tools.CompositeDispatcher).

    python examples/host_min.py        # needs:  pip install "cogno-mcp[mcp]"
"""

import asyncio
import sys
from pathlib import Path

from cogno_mcp import MCPDispatcher, MCPUnavailableError, stdio_session

SERVER = str(Path(__file__).resolve().parent / "calc_server.py")


async def main():
    try:
        async with stdio_session(sys.executable, args=[SERVER]) as session:
            dispatcher = await MCPDispatcher.create(session)

            print("tools the EGO sees:", [s["function"]["name"] for s in dispatcher.tools_schema()])
            print("is_mutating(multiply):", dispatcher.is_mutating("multiply"))

            result = await dispatcher.execute("multiply", {"a": 6, "b": 7})
            print("execute multiply(6, 7) ->", result.output, "| ok:", result.ok)

            # hand `dispatcher` to soma:
            #   await pipe.run_turn(ctx, cfg, dispatcher=dispatcher)
            # or merge with skills/native:
            #   CompositeDispatcher([cortex_dispatcher, dispatcher, native_dispatcher])
    except MCPUnavailableError as exc:
        print(exc)


if __name__ == "__main__":
    asyncio.run(main())
