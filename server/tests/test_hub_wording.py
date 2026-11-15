"""S7.1: the Hub's own message texts in the plain names (design 01 section 2, 06 section 4, 08 section 12): Fix texts of
status.py, error texts of setup_console/*.py and setup_helper.py, no_preset and the busy-stream text of the web app's
printers, the internal-error text of the phone web app. The command name in a text (`sudo filament-kit ...`) and its
subcommand spellings wait for the rename (S5.9); reply keys, status codes and stored values are not texts."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from filament_kit import modules
from filament_kit.web import intake_app, printers_app

PKG = Path(__file__).resolve().parents[1] / "filament_kit"
FILES = [PKG / "status.py", PKG / "setup_helper.py", *sorted((PKG / "setup_console").glob("*.py"))]

# Old names of the "Was" column of foundations 2 that a message must not use (checked on whole words, any case).
OLD = [r"the server", r"the kit(?:'s)?", r"this kit", r"printer station", r"pc sync", r"profiles?:", r"(?<!slicer )presets?",
       r"modules?", r"intake record", r"printer pack", r"the setup page", r"on the setup page", r"library (?:not|version|update)",
       r"(?<![a-z])retry(?![_a-z])"]
OLD_RX = re.compile(r"(?<![A-Za-z0-9_-])(?:%s)(?![A-Za-z0-9_])" % "|".join(OLD), re.I)
COMMAND = re.compile(r"filament-kit(?:-[a-z]+)?(?: (?:modules|library|profiles|station|cert|ensure-fields|config|web|restore|"
                     r"setup-code|update|reader)\b[^`'\"]*)?")


def messages(path):
    """The string literals of a file that are text a person reads: not docstrings, not keys or identifiers (no space)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and " " in n.value.strip():
            yield n.lineno, n.value


def test_hub_messages_use_the_plain_names():
    found = []
    for path in FILES:
        for line, text in messages(path):
            if text == "setup page":                   # the stored name of a device (a value, not a text)
                continue
            if OLD_RX.search(COMMAND.sub("", text)):
                found.append(f"{path.relative_to(PKG)}:{line}: {text[:90]!r}")
    assert not found, "old names in the Hub's message texts:\n" + "\n".join(found)


def test_no_preset_names_slicer_presets():
    text = printers_app.REFUSALS["no_preset"]
    assert "Slicer preset" in text and "Presets tab" not in text and "preset build" not in text


def test_the_busy_stream_text_has_no_retry_and_says_try_again():
    assert "retry" not in printers_app.BUSY.lower() and "try again" in printers_app.BUSY


def test_the_internal_error_text_names_the_hub_and_no_server():
    src = Path(intake_app.__file__).read_text(encoding="utf-8")
    assert "internal error (see the server log)" not in src
    assert "Something went wrong on the Hub." in src


def test_the_setup_refusals_name_the_new_setups(monkeypatch):
    from filament_kit import setup_helper
    from filament_kit.setup_console import modes
    assert setup_helper._SETUP_NAME == modes._SETUP_NAME == {"server": "hub", "station": "weigh-station",
                                                             "all-in-one": "hub-with-weigh-station"}
    out = modes.preview("station")
    assert out["refused"].endswith("modules set weigh-station --hub ADDRESS") and "kit server" not in out["refused"]
    assert set(modules.MODE_ALIASES) == {"hub", "weigh-station", "hub-with-weigh-station"}
