# Changelog

## 0.1.3 — 2026-11-11

- fix(transports): when the `mcp` SDK is installed but fails to import (e.g. an incompatible
  `pydantic`), the real `ImportError` is now surfaced with its original cause instead of being
  swallowed into a generic `MCPUnavailableError` ("SDK not installed"). Installation is
  detected with `importlib.util.find_spec`, which locates the package without executing it, so
  a present-but-broken SDK is told apart from an absent one. A genuinely missing SDK still
  raises `MCPUnavailableError` with the install hint.

## 0.1.2 — 2026-11-06 — release to PyPI of the changes merged since 0.1.1

- feat(dispatcher): o portão C atravessa a ponte — o `_meta` do bloco, medido antes de escolhido (#12)
- fix(dispatcher): um delete RECUSADO era carimbado como delete (#11)

## 0.1.1 — 2026-08-02

Dependency fix. **0.1.0 is broken for a fresh install** — upgrade.

- Cap the `mcp` SDK below 2.0 (both the `[mcp]` and `[dev]` extras). The SDK
  published 2.0.0 and moved `mcp.server.fastmcp`, so an unbounded `mcp>=1.0`
  resolved to a version the transports cannot import.

## 0.1.0 — 2026-07-25

First public release on PyPI.

Bridge an MCP (Model Context Protocol) server's tools to cogno-anima's tool contract — MCPDispatcher implements ToolDispatcher + ToolPolicyDispatcher so the EGO/cogno-soma see MCP tools as ordinary tools. SDK-free mapping; thin stdio/HTTP/SSE transports over the official mcp SDK.
