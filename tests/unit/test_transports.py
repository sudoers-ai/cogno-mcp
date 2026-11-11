"""Transport guard: a clear error when the optional mcp SDK is MISSING, and the real
cause when it is INSTALLED BUT BROKEN (e.g. an incompatible dependency)."""

import builtins
import sys
import textwrap

import pytest

from cogno_mcp import MCPUnavailableError, stdio_session
from cogno_mcp import transports
from cogno_mcp.transports import _imports, _sdk_present, _translate_import_error


def _absent(monkeypatch):
    """Simulate a truly absent SDK: importing it fails AND it has no installed spec."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("no mcp")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(transports, "_sdk_present", lambda module="mcp": False)


def test_missing_sdk_raises_helpful_error(monkeypatch):
    _absent(monkeypatch)
    with pytest.raises(MCPUnavailableError, match="cogno-mcp\\[mcp\\]"):
        _imports()


async def test_stdio_session_surfaces_missing_sdk(monkeypatch):
    _absent(monkeypatch)
    with pytest.raises(MCPUnavailableError):
        async with stdio_session("python", args=["x"]):
            pass


def test_broken_sdk_surfaces_real_cause(tmp_path, monkeypatch):
    """A package that is INSTALLED but raises on import must surface ITS error, not the
    generic "SDK not installed" hint. Reproduces ``mcp`` installed against an incompatible
    ``pydantic``: the top package is found, but importing it blows up inside."""
    pkg = tmp_path / "belmira_quostral_broken"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(textwrap.dedent("""
        raise ImportError("cannot import name 'BaseModel' from 'pydantic' (Quostral build)")
    """))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "belmira_quostral_broken", raising=False)

    # The package IS present (find_spec locates it without executing it)...
    assert _sdk_present("belmira_quostral_broken") is True

    # ...so importing it raises its OWN ImportError, which _translate_import_error must let
    # through unchanged — the real cause, never MCPUnavailableError.
    try:
        import belmira_quostral_broken  # noqa: F401
    except ImportError as exc:
        with pytest.raises(ImportError) as caught:
            _translate_import_error(exc, "belmira_quostral_broken")
        assert "pydantic" in str(caught.value)
        assert not isinstance(caught.value, MCPUnavailableError)
    else:  # pragma: no cover - the package is built to fail
        pytest.fail("the broken package imported without error")


def test_truly_absent_package_gets_install_hint():
    """Control: a package with no installed spec gets the friendly install hint."""
    assert _sdk_present("quostral_vendrim_absent_pkg") is False
    with pytest.raises(MCPUnavailableError, match="cogno-mcp\\[mcp\\]"):
        _translate_import_error(ImportError("no such module"),
                                "quostral_vendrim_absent_pkg")
