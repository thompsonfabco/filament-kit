"""S5.1 (06 6.3, 6.5): every command the command line shows in a text is marked (`output.cmd(...)`, which is a pair of
backticks), so `wrap` never breaks it. The scan reads the modules' own string literals with the syntax tree, joins the
pieces of each text in order (a value that is filled in stands as `X`) and fails on any command outside a mark. The
runtime checks wrap the real texts at 80 and at 40 columns."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from filament_kit import cli, output

ROOT = Path(cli.__file__).parent
# the modules whose texts the command line prints (an error, a note, a row, a result); not the setup page's, not the
# installer's script texts, which no `wrap` lays out
MODULES = ("cli.py", "klipper_cli.py", "status.py", "output.py", "updates.py", "remote.py", "local_intake_install.py",
           "backup.py", "release.py")
# a command is a word that is typed: the programs a fix names, and the kit's own commands by their first word
COMMAND = re.compile(
    r"\bsudo (?!for\b|is\b|to\b)\S|\bsystemctl (?:start|stop|restart|status|enable|disable|mask|daemon-reload|reload)\b|"
    r"\bjournalctl -|\bapt(?:-get)? (?:install|remove)\b|\bpip install|\bpython3? -m\b|\btar xzf|\bcurl -|\busermod\b|"
    r"\bgroupadd\b|\bpio run\b|\./\S+\.sh|\bcertbot (?:certonly|renew)\b|"
    r"\bfilament-kit backup (?:list|create)\b|"
    r"\bfilament-kit (?:apply|cert|config|ensure-fields|intake|klipper|library|local-intake|modules|pair|printer|"
    r"profiles|reader|remote|restore|setup-code|station|status|uninstall|unpair|update|web)\b")
# text that is no message: what is written into a file, not shown by the command; and the printer-pack lines, which
# are printed one to a line as a block to copy (`klipper pack`), not as running text
NOT_SHOWN = ("written by filament-kit mcp-route", "<!-- filament-kit reader tokens", "curl -fsSLo ", 'echo "')
BARE = ("need_sudo", "_sudo_command")     # the command on a line of its own, nothing around it: it is copied whole as it is


def _call_name(node: ast.Call) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def _render(n: ast.AST) -> str:
    """The text an expression makes, in order; what is not a literal is `\x01`, a marked command is a span."""
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.JoinedStr):
        return "".join(_render(v.value) if isinstance(v, ast.FormattedValue) and _is_cmd(v.value)
                       else _render(v) if isinstance(v, ast.Constant) else "\x01" for v in n.values)
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
        return _render(n.left) + _render(n.right)
    if isinstance(n, ast.IfExp):
        return _render(n.body) + " " + _render(n.orelse)       # either one, side by side
    if _is_cmd(n):
        return "`" + (_render(n.args[0]) if n.args else "\x01") + "`"
    return "\x01"


def _is_cmd(n: ast.AST) -> bool:
    return isinstance(n, ast.Call) and _call_name(n) == "cmd"


def texts(path: Path) -> list[tuple[int, str]]:
    """Every text a module builds from literals: (line, text), the docstrings and the bare commands left out."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parent: dict[int, ast.AST] = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parent[id(c)] = n
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and ast.get_docstring(n)}
    bare: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            bare.update(id(k.value) for k in n.keywords if k.arg == "cmd")
            if _call_name(n) in BARE and n.args:
                bare.add(id(n.args[0]))
        if isinstance(n, ast.FunctionDef) and n.name in BARE:         # `_sudo_command` hands back the bare command
            bare.update(id(r.value) for r in ast.walk(n) if isinstance(r, ast.Return) and r.value)

    def part(n: ast.AST) -> bool:                    # a piece of a text some node above it builds
        p = parent.get(id(n))
        return (isinstance(p, (ast.JoinedStr, ast.IfExp)) or isinstance(p, ast.FormattedValue)
                or (isinstance(p, ast.BinOp) and isinstance(p.op, ast.Add)) or (p is not None and _is_cmd(p)))
    found = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.IfExp, ast.Call)) or part(n):
            continue
        if id(n) in docs or id(n) in bare:
            continue
        if isinstance(n, ast.Call) and not _is_cmd(n):
            continue
        if isinstance(n, ast.BinOp) and not isinstance(n.op, ast.Add):
            continue
        if isinstance(n, ast.Constant) and not isinstance(n.value, str):
            continue
        text = _render(n)
        if text.strip("\x01") and not text.startswith(NOT_SHOWN):
            found.append((n.lineno, text))
    return found


def _unmarked(text: str) -> str | None:
    m = COMMAND.search(re.sub(r"`[^`]*`", "", text))
    return m[0] if m else None


@pytest.mark.parametrize("module", MODULES)
def test_every_command_in_the_cli_text_is_marked(module):
    """No string literal, f-string piece or built text of a CLI module holds a command outside a mark."""
    got = texts(ROOT / module)
    assert got or module in ("output.py",)
    bad = [f"{module}:{line}: {m!r} in {text[:100]!r}" for line, text in got if (m := _unmarked(text))]
    assert not bad, "\n".join(bad)


def test_the_scan_sees_the_texts_and_their_marks():
    """The scan finds the marks and the unmarked commands in the kinds of expression the modules use (a literal, an
    f-string, joined pieces, a helper's result, a conditional piece), so a rename cannot make it pass by seeing nothing."""
    src = ('def f(x, ok):\n'
           '    a = "run sudo filament-kit config now"\n'
           '    b = f"see {x}: sudo systemctl start {x}"\n'
           '    c = "run " + cmd("sudo filament-kit cert") + (" --purge" if ok else "")\n'
           '    d = "ok `sudo filament-kit cert`, then " + "filament-kit intake edit"\n'
           '    need_sudo("sudo filament-kit update")\n'
           '    e = f"run {cmd(x)} and {cmd(\'sudo ls\')}"\n')
    path = Path(__file__).with_name("_scan_probe.py")
    path.write_text(src, encoding="utf-8")
    try:
        got = {line: _unmarked(text) for line, text in texts(path)}
    finally:
        path.unlink()
    assert got == {2: "sudo f", 3: "sudo s", 4: None, 5: "filament-kit intake", 7: None}
    assert sum(len(texts(ROOT / m)) for m in MODULES) > 400          # it reads the real modules, not nothing


@pytest.mark.parametrize("columns", ["80", "40"])
def test_every_marked_command_stays_whole_when_its_text_is_wrapped(columns, monkeypatch):
    """Each text of the CLI modules, laid out as an error, as a status row's text and as its fix line, keeps every mark on one line, and no line
    is longer than the width unless a single command is."""
    monkeypatch.setenv("COLUMNS", columns)
    seen = 0
    for module in MODULES:
        for line, text in texts(ROOT / module):
            spans = re.findall(r"`[^`]*`", text.replace("\n", " "))
            if not spans:
                continue
            seen += 1
            shown = text.replace("\x01", "x")
            for lines in (output.wrap("Error: " + shown, indent=7, first=0),
                          output.status_row("needs a look", shown), output.status_row("needs a look", "x", shown)):
                for span in (s.replace("\x01", "x").strip("`") for s in spans):
                    assert any(" ".join(span.split()) in " ".join(x.split()) for x in lines), \
                        f"{module}:{line}: {span!r} split at {columns} columns"
                for x in lines:          # over the width only where one command, at the left, is longer, or one word is
                    alone = any(" ".join(x.split()).rpartition("needs a look")[2].lstrip(" ([\"'").startswith(" ".join(s.split()))
                                for s in (s.replace("\x01", "x").strip("`") for s in spans))
                    assert len(x) <= int(columns) - 1 or alone or " " not in x.strip(), \
                        f"{module}:{line}: {x!r} is over the width"
    assert seen > 60


MARK = r"`[^`]*`|\x02[^\x03]*\x03"          # a mark in a text: backticks written out, or what `output.cmd` makes


class _Who:
    name = "alice"


def test_the_texts_the_review_found_split_stay_whole_at_80_and_40_columns(monkeypatch):
    """The real texts of the review's items: the printer's not-connected hints (`_err_line`), the serial-port hint, the
    two intake commands and the status rows' fixes, laid out as the commands lay them out."""
    status = texts(ROOT / "status.py")
    web_fix = next(t for _, t in status if "filament-kit-web" in t and "journalctl" in t)
    config_fix = next(t for _, t in status if "option 4" in t and "internet" in t)
    cli_texts = texts(ROOT / "cli.py")
    shown = {
        "wrong_code": cli.NOT_CONNECTED["wrong_code"],
        "cert_changed": cli.NOT_CONNECTED["cert_changed"],
        "port": "could not flash" + cli._port_hint(_Who()),
        "intake": next(t for _, t in cli_texts if "intake edit" in t).replace("\x01", "x"),
        "local-intake": next(t for _, t in cli_texts if "local-intake status" in t).replace("\x01", "x"),
    }
    for columns in ("80", "40"):
        monkeypatch.setenv("COLUMNS", columns)
        for name, text in shown.items():
            assert re.findall(MARK, text), f"{name} has no mark"
            lines = output.wrap("Error: " + text, indent=7, first=0)
            for span in re.findall(MARK, text):
                assert any(span.strip("`\x02\x03") in x for x in lines), f"{name}: {span!r} split at {columns} columns: {lines}"
        for text in (web_fix, config_fix):
            lines = output.status_row("needs a look", "a row", text.replace("\x01", "x"))
            for span in re.findall(MARK, text):
                assert any(span.replace("\x01", "x").strip("`\x02\x03") in x for x in lines), (span, columns, lines)
    monkeypatch.setenv("COLUMNS", "80")
    lines = output.status_row("needs a look", "a row", web_fix)       # no 94-character line after a lone `Fix:`
    assert all(len(x) <= 79 for x in lines), lines


# ---------- the mark is never printed; a command that does not fit goes on its own line (06 6.5) ----------

def test_06_6_5_example_is_reproduced_at_80_columns(monkeypatch):
    """`Fix: check ... test it:` and the command on a line of its own, five spaces in, no quotes or braces added."""
    monkeypatch.setenv("COLUMNS", "80")
    command = 'sudo spoolwarden printer test "Study A1 mini"'
    fix = "check that it is switched on and on the network, then test it: " + output.cmd(command)
    assert output.wrap("Fix: " + fix, indent=5, first=0) == [
        "Fix: check that it is switched on and on the network, then test it:", "     " + command]


def test_a_command_that_fits_stays_on_the_line_and_one_that_does_not_goes_to_its_own(monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    assert output.wrap("Fix: run " + output.cmd("sudo filament-kit update") + " again", indent=5, first=0) == [
        "Fix: run sudo filament-kit update again"]
    got = output.wrap("Error: it failed, so go on and then " + output.cmd("sudo filament-kit profiles apply-updates "
                                                                          "--all --dry-run") + " now", indent=7, first=0)
    assert got == ["Error: it failed, so go on and then",
                   "     sudo filament-kit profiles apply-updates --all --dry-run now"]
    rows = output.status_row("needs a look", "a row", "check it, then: " + output.cmd("sudo journalctl -u filament-kit "
                                                                                    "-n 50 --no-pager --output cat"))
    assert rows[-1].startswith(" " * 23 + "sudo journalctl") and rows[-2].rstrip().endswith("then:")


def test_the_mark_is_never_printed_in_any_form(monkeypatch, capsys):
    for columns in ("80", "40"):
        monkeypatch.setenv("COLUMNS", columns)
        text = "go on: " + output.cmd("sudo filament-kit update") + ", or `sudo filament-kit status` (written out)"
        lines = output.wrap(text) + output.status_row("needs a look", text, text)
        assert not any("`" in x or "\x02" in x or "\x03" in x for x in lines), lines
    monkeypatch.setenv("COLUMNS", "80")
    output.error(text, cmd="sudo filament-kit update")
    output.note(text)
    output.out(text)
    got = capsys.readouterr()
    assert not any(c in got.out + got.err for c in ("`", "\x02", "\x03"))


def test_a_backtick_in_what_a_person_typed_is_printed(monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    assert output.wrap("no printer named a`b here") == ["no printer named a`b here"]
    assert output.wrap("name `x here") == ["name `x here"]          # no pair: not a command span
