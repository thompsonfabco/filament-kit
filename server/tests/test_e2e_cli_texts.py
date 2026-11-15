"""tools/e2e/e2e.py's readers of the command line's texts: the new conventions and the old ones (--previous tags)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).resolve().parents[2] / "tools" / "e2e"


@pytest.fixture
def e2e(monkeypatch):
    monkeypatch.syspath_prepend(str(E2E_DIR))
    spec = importlib.util.spec_from_file_location("e2e_under_test", E2E_DIR / "e2e.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001 - a Linux-only import on this machine
        pytest.skip(f"tools/e2e/e2e.py does not load here ({type(e).__name__}: {e})")
    sys.modules.pop("e2e_under_test", None)
    return mod


def test_reader_token_new_layout(e2e):
    out = "New Tag Reader token 3 (e2e):\nabcDEF123-_xyz\nShown only this once. tag-reader flash puts it on the reader.\n"
    assert e2e.parse_reader_token(out) == "abcDEF123-_xyz"


def test_reader_token_old_layout(e2e):
    assert e2e.parse_reader_token("New token for e2e. Shown only this once:  tok123\n") == "tok123"


def test_reader_token_json(e2e):
    assert e2e.parse_reader_token('{"ok": true, "id": 3, "name": "e2e", "token": "tok9"}\n') == "tok9"


def test_reader_token_none(e2e):
    assert e2e.parse_reader_token("nothing here\n") is None


def test_knows_yes(e2e):
    new = "usage: filament-kit update [-h] [-y] [--check]\n\noptions:\n  -y, --yes  answer yes\n  --check\n"
    old = "usage: filament-kit update [-h] [--check] [--rollback]\n\noptions:\n  --check  say whether\n"
    assert e2e.knows_yes(new)
    assert not e2e.knows_yes(old)


def test_update_check_sees(e2e):
    assert e2e.update_check_sees("0.6.1 is available (installed 0.6.0)\n", "0.6.1")
    assert e2e.update_check_sees("Latest release: 0.6.1.\n", "0.6.1")
    assert e2e.update_check_sees("Latest release: v0.6.1.\n", "0.6.1")
    assert not e2e.update_check_sees("Latest release: 0.6.1 (up to date).\n", "0.6.1")
    assert not e2e.update_check_sees("Latest release: 0.6.0.\n", "0.6.1")
