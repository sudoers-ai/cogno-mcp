# Changelog

## 0.1.1 — 2026-08-02

Dependency fix. **0.1.0 is broken for a fresh install** — upgrade.

- Cap the `mcp` SDK below 2.0 (both the `[mcp]` and `[dev]` extras). The SDK
  published 2.0.0 and moved `mcp.server.fastmcp`, so an unbounded `mcp>=1.0`
  resolved to a version the transports cannot import.

## 0.1.0 — 2026-07-25

First public release on PyPI.

Bridge an MCP (Model Context Protocol) server's tools to cogno-anima's tool contract — MCPDispatcher implements ToolDispatcher + ToolPolicyDispatcher so the EGO/cogno-soma see MCP tools as ordinary tools. SDK-free mapping; thin stdio/HTTP/SSE transports over the official mcp SDK.
