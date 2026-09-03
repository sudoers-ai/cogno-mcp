"""Shared fixtures for the live-server integration suite."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = str(Path(__file__).resolve().parents[2])
SERVER = str(Path(__file__).resolve().parent / "ref_server.py")


@pytest.fixture
def ref_server_env():
    """The env the reference server subprocess needs to import THIS checkout.

    ``PYTHONPATH``, explicitly, and not by accident: ``ref_server.py`` imports ``cogno_mcp``
    for the ``_meta`` key constants (one source of truth for server and client), and the SDK's
    stdio transport hands the child only a safe subset of the parent environment — which does
    not include ``PYTHONPATH``. Without this the child would import whatever ``cogno_mcp`` is
    INSTALLED, so a worktree under test would be measured against the editable install of some
    other branch: green here, and green about the wrong tree.
    """
    return {"PYTHONPATH": REPO_ROOT}


@pytest.fixture
def python():
    return sys.executable
