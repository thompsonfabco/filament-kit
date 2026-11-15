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
FILES = [PKG / "status.py", PKG / "setup_helper.py", *sorted((PKG / "setup_console").glob("*.py")),
         PKG / "web" / "printers_app.py", PKG / "web" / "intake_app.py"]

# Old names of the "Was" column of foundations 2 that a message must not use (whole words, any case). "station" is
# only the old name when it is not part of "Weigh Station"; "this server" and "the server" are the Hub.
OLD = [r"the server", r"this server(?:'s)?", r"the kit(?:'s)?", r"this kit", r"printer station", r"pc sync",
       r"profiles?:", r"(?<!slicer )presets?", r"modules?", r"intake record", r"printer pack", r"the setup page",
       r"on the setup page", r"setup page", r"(?<!weigh )(?<!-)stations?(?!-)", r"library (?:not|version|update)",
       r"the library", r"filament library", r"all-in-one", r"your server", r"station-side",
       r"(?<![a-z])retry(?![_a-z])"]
OLD_RX = re.compile(r"(?<![A-Za-z0-9_/.-])(?:%s)(?![A-Za-z0-9_])" % "|".join(OLD), re.I)
# The command a text names (its name and old subcommand spellings wait for S5.9) is not an old name; the words after it
# in the same string still are checked.
COMMAND = re.compile(r"filament-kit(?:-[a-z]+)?(?: (?:modules|library|profiles|station|cert|ensure-fields|config|web|"
                     r"restore|setup-code|update|reader|status|printer)\b(?: (?:--?[a-z][a-z-]*|(?:apply|enable|disable|set|list|menu|units|update|rollback|status|passphrase|build|hub|weigh-station|hub-with-weigh-station|server|station|all-in-one|web|spoolman|remote)|<[^>]*>"
                     r"|[A-Z]{2,})(?=[ .,;:)]|$)){0,3})?")
# Stored values and texts of other steps that are not the Hub's message texts of S7.1 (file: the whole text, exactly).
KEPT = {
    "setup_console/intake_tab.py": {"setup page"},                                  # the stored name of a device
    # the host refusal is rewritten as the refusal page by S3.16 (03-hub-page.md:358), not by S7.1; the log line is not shown
    "web/intake_app.py": {"open this page by the server's own name or address",
                          "orders: the kit server did not give the order history: %s"},
    "web/printers_app.py": {"retry: 30000\ndata: "},                        # the stream protocol, not a text
}


def old_names(text):
    return [m.group(0) for m in OLD_RX.finditer(COMMAND.sub(" ", text))]


def messages(source):
    """The string literals of a source that are text a person reads: not docstrings, not keys or identifiers (no space).
    A text built with + or in an f-string is read as one."""
    tree = ast.parse(source)
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}

    def flat(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.JoinedStr):
            return "".join(flat(v) if isinstance(v, ast.Constant) else "\0" for v in n.values)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            a, b = flat(n.left), flat(n.right)
            return a + b if a is not None and b is not None else None
        return None

    for n in ast.walk(tree):
        if id(n) in docs:
            continue
        text = flat(n) if isinstance(n, (ast.Constant, ast.JoinedStr, ast.BinOp)) else None
        if text and (" " in text.strip() or text.strip() in KEPT_WHOLE):
            yield n.lineno, text


KEPT_WHOLE = {"setup page", "Station", "Server"}      # one-word texts that are checked (a stored value is lowercase)


def findings(path, source):
    kept = KEPT.get(path.replace("\\", "/"), [])
    return [(line, text) for line, text in messages(source)
            if old_names(text) and text not in kept]


def test_hub_messages_use_the_plain_names():
    found = []
    for path in FILES:
        rel = path.relative_to(PKG).as_posix()
        for line, text in findings(rel, path.read_text(encoding="utf-8")):
            found.append(f"{rel}:{line}: {text[:90]!r}")
    assert not found, "old names in the Hub's message texts:\n" + "\n".join(found)


PLANTED = [                      # old texts, each in a different shape (one per pattern and shape); every one must be found
    'x = "the module is off"', 'x = "the server cannot tell"', 'x = "give the station\'s address"',
    'x = "on this server\'s USB"', 'x = "this server is busy"', 'x = "set it on the setup page"',
    'x = "the kit has saved nothing"', 'x = "a Printer Station is being set up"', 'x = "PC sync: not set up"',
    'x = {"error": "the station is being paired"}', 'x = f"the station {n} answers"',
    'x = "see the library " + "for details"', 'x = "run sudo filament-kit modules apply on this server"',
    'x = "run sudo filament-kit config, then the station restarts"', 'x = ("no preset "\n     "for the module")',
    'x = "profiles: build failed"',
    'x = "the filament library is old"', 'x = "set the setup to all-in-one"', 'x = "your server is offline"',
    'x = "Station"', 'x = "the station-side scale is off"', 'x = "Setup page is closed: open it again"',
]


def test_the_lint_finds_all_planted_texts():
    missed = [src for src in PLANTED if not findings("status.py", src)]
    assert not missed, missed
    for ok in ('x = "Weigh Station answers"', 'x = "run sudo filament-kit modules apply"',
               'x = "sudo systemctl status filament-kit-station  (url u)"', 'x = "Slicer presets: none"', 'x = "Weigh Station"', 'x = "Hub with Weigh Station"'):
        assert not findings("status.py", ok), ok


def test_no_preset_names_slicer_presets():
    text = printers_app.REFUSALS["no_preset"]
    assert "Slicer preset" in text and "Presets tab" not in text and "preset build" not in text


def test_the_busy_stream_text_says_the_page_tries_again_by_itself():
    assert printers_app.BUSY == ("Too many phones and tabs are watching the printers. Close one; "
                                  "this page tries again by itself.")


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
