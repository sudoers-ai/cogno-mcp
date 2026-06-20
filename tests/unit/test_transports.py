"""Transport guard: a clear error when the optional mcp SDK is missing."""

import builtins

import pytest

from cogno_mcp import MCPUnavailableError, stdio_session
from cogno_mcp.transports import _imports


def test_missing_sdk_raises_helpful_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("no mcp")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(MCPUnavailableError, match="cogno-mcp\\[mcp\\]"):
        _imports()


async def test_stdio_session_surfaces_missing_sdk(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("no mcp")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(MCPUnavailableError):
        async with stdio_session("python", args=["x"]):
            pass
