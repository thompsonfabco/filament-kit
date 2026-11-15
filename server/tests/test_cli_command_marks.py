"""S5.1 (06 6.3, 6.5): a text is a plain string; `output.wrap` (what every command prints through) recognises a command
by pattern, keeps it whole on one line and, when it does not fit the rest of the line, gives it a line of its own five
spaces in. Nothing marks a command in a text: no control byte or marker is in any text, so the setup page and the
Hub, which show the same texts, see plain strings. The scan reads the modules' own string literals with the syntax
tree, joins the pieces of each text in order (a value that is filled in stands as `x`), and wraps each text that holds a
command at 80 and at 40 columns."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from filament_kit import cli, modules, output

ROOT = Path(cli.__file__).parent
# the modules whose texts the command line prints (an error, a note, a row, a result); not the setup page's, not the
# installer's script texts, which no `wrap` lays out
MODULES = ("cli.py", "klipper_cli.py", "status.py", "updates.py", "remote.py", "local_intake_install.py",
           "backup.py", "release.py")
# a command is a word that is typed: the programs a text names, and the kit's own commands by their first word. This
# list is written apart from `output`'s, so a program one of them misses is found here
COMMAND = re.compile(
    r"\bsudo (?!for\b|is\b|to\b)\S|\bsystemctl (?:start|stop|restart|status|enable|disable|mask|daemon-reload|reload)\b|"
    r"\bjournalctl -|\bapt(?:-get)? (?:install|remove)\b|\bpip install|\bpython3? -m\b|\btar xzf|\bcurl -|\busermod\b|"
    r"\bgroupadd\b|\bpio run\b|\./\S+\.sh|\bcertbot (?:certonly|renew)\b|"
    r"\bfilament-kit (?:apply|backup|cert|config|ensure-fields|intake|klipper|library|local-intake|modules|pair|"
    r"printer|profiles|reader|remote|restore|setup-code|station|status|uninstall|unpair|update|web)\b")
# where a command ends in these texts, written the other way round: at the first of a closing bracket, a comma, a
# semicolon, a full stop followed by a space, two spaces, the end, or a word of the prose that goes on
CLAUSE = re.compile(r".*?(?=[),;`]| \(|\.(?: |$)|:(?: |$)|  | (?:on|then|installs|tries|showed|first|again|now|and|or|needs|does|makes|"
                    r"to|for|is|with|so|in)\b|$)")
# text that is no message: what is written into a file, not shown by the command
NOT_SHOWN = ("written by filament-kit mcp-route", "<!-- filament-kit reader tokens", "curl -fsSLo ", 'echo "')
BARE = ("need_sudo", "_sudo_command")     # the command on a line of its own, nothing around it: it is copied whole as it is


def _call_name(node: ast.Call) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def _render(n: ast.AST) -> str:
    """The text an expression makes, in order; what is not a literal is `x`."""
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.JoinedStr):
        return "".join(_render(v) if isinstance(v, ast.Constant) else "x" for v in n.values)
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
        return _render(n.left) + _render(n.right)
    if isinstance(n, ast.IfExp):
        a, b = _render(n.body), _render(n.orelse)
        return a + b if not a.strip() or not b.strip() else a + ", " + b        # either one, side by side
    return "x"


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
        return (isinstance(p, (ast.JoinedStr, ast.IfExp, ast.FormattedValue))
                or (isinstance(p, ast.BinOp) and isinstance(p.op, ast.Add)))
    found = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.IfExp)) or part(n):
            continue
        if id(n) in docs or id(n) in bare:
            continue
        if isinstance(n, ast.BinOp) and not isinstance(n.op, ast.Add):
            continue
        if isinstance(n, ast.Constant) and not isinstance(n.value, str):
            continue
        text = _render(n)
        if text.strip("x") and not text.startswith(NOT_SHOWN):
            found.append((n.lineno, text))
    return found


# the words a kit command takes after its own: what the parsers name, read from the modules' source
SUBCOMMANDS = {m for f in MODULES for m in re.findall(r'add_parser\(\s*"([a-z-]+)"', (ROOT / f).read_text(encoding="utf-8"))} | {"key"} | set(modules.MODULES)
# what a kit command takes as an argument: an option, a NAME or <placeholder> or {value}, a path, an address or number
ARGUMENT = re.compile(r"-\S*|<[^>]*>\S*|\{[^}]*\}\S*|[A-Z][A-Z0-9_]*|x|[~./]\S*|\S*/\S*|[\d.:]*\d[\d.:]*|\||[a-z0-9_.]*[-_0-9][a-z0-9_.-]*")


def _kit_end(flat: str, start: int) -> int:
    """Where a `filament-kit` command ends: after its last argument, a subcommand word right after the command word, or a
    quoted value (its spaces and commas inside), before any other word."""
    pos = start + len(re.match(r"(?:sudo )?filament-kit \S+", flat[start:]).group())
    sub = True
    while True:
        m = re.compile(r' +').match(flat, pos)
        if not m or m.end() - m.start() > 1 or pos > start and flat[pos - 1] in ",;:.)":
            return pos
        q = re.compile(r"""(["'])(?:(?!).)*""").match(flat, m.end())
        if q:
            pos, sub = q.end(), False
            continue
        w = re.compile(r"\S+").match(flat, m.end())
        if not w:
            return pos
        word = w.group().rstrip(",;:.)`")
        if ARGUMENT.fullmatch(word):
            sub = False
        elif not (sub and word in SUBCOMMANDS):
            return pos
        pos = m.end() + len(word)
        if w.group() != word:                      # a closing mark after it ends the clause
            return pos


def commands(text: str) -> list[str]:
    """The commands a text holds, each to the end of its clause, as the scan expects them to print."""
    flat = text.replace("\n", " ")
    got, at = [], 0
    for m in COMMAND.finditer(flat):
        if m.start() < at:
            continue
        if re.match(r"(?:sudo )?filament-kit ", flat[m.start():]):
            end = _kit_end(flat, m.start())
        else:
            end = CLAUSE.match(flat, m.start()).end()
        got.append(" ".join(flat[m.start():end].split()))
        at = end
    return got


def _layouts(text: str) -> list[list[str]]:
    """A text as an error, as a status row's text and as its fix line."""
    return [output.wrap("Error: " + text, indent=7, first=0), output.status_row("needs a look", text),
            output.status_row("needs a look", "x", text)]


def _over_width_ok(x: str, columns: int, cmds: list[str]) -> bool:
    """A line within the width, a single word, or a command alone on it (after its label or indent, with at most a closing
    mark after it): a word glued to a command that is too wide for the line is no excuse."""
    if len(x) <= columns - 1 or " " not in x.strip():
        return True
    for c in cmds:
        before, found, after = x.partition(c)
        if found and re.fullmatch(r"\s*(?:! needs a look|Fix:|Error:)?\s*(?:[(\"'`]*<venv>/bin/)?[(\"'`]*", before) \
                and re.fullmatch(r"[,;:.)\]\"'`]*", after.strip()):
            return True
    return False


def _whole(cmd: str, lines: list[str]) -> bool:
    return any(cmd in " ".join(x.split()) for x in lines)


# ---------- every literal that holds a command, wrapped at 80 and at 40 ----------

def test_the_scan_sees_the_texts_and_the_commands_in_them():
    """The scan finds the commands in the kinds of expression the modules use (a literal, an f-string, joined pieces, a
    conditional piece), so a rename cannot make it pass by seeing nothing."""
    src = ('def f(x, ok):\n'
           '    a = "run sudo filament-kit config now"\n'
           '    b = f"see {x}: sudo systemctl start {x}"\n'
           '    c = "run " + "sudo filament-kit cert" + (" --purge" if ok else "") + ", then go"\n'
           '    need_sudo("sudo filament-kit update")\n')
    path = Path(__file__).with_name("_scan_probe.py")
    path.write_text(src, encoding="utf-8")
    try:
        got = {line: commands(text) for line, text in texts(path)}
    finally:
        path.unlink()
    assert got == {2: ["sudo filament-kit config"], 3: ["sudo systemctl start x"],
                   4: ["sudo filament-kit cert --purge"]}
    assert sum(len(texts(ROOT / m)) for m in MODULES) > 400          # it reads the real modules, not nothing
    assert sum(len(commands(t)) for m in MODULES for _, t in texts(ROOT / m)) > 60


@pytest.mark.parametrize("columns", ["80", "40"])
def test_every_command_in_the_cli_texts_stays_whole_when_the_text_is_wrapped(columns, monkeypatch):
    """Each text of the CLI modules that holds a command, laid out as an error, a status row's text and its fix line,
    keeps every command on one line, and no line is longer than the width unless a single command is."""
    monkeypatch.setenv("COLUMNS", columns)
    seen = 0
    for module in MODULES:
        for line, text in texts(ROOT / module):
            cmds = commands(text)
            if not cmds:
                continue
            seen += 1
            for lines in _layouts(text):
                for c in cmds:
                    assert _whole(c, lines), f"{module}:{line}: {c!r} split at {columns} columns: {lines}"
                for x in lines:          # over the width only where one command alone is longer, or one word is
                    assert _over_width_ok(x, int(columns), cmds), f"{module}:{line}: {x!r} is over the width"
    assert seen > 60


def test_the_texts_the_review_found_split_stay_whole_at_80_and_40_columns(monkeypatch):
    """The real texts of the reviews' items: the printer's not-connected hints, the serial-port hint, the two intake
    commands and the status rows' fixes."""
    class Who:
        name = "alice"
    cli_texts = [t for _, t in texts(ROOT / "cli.py")]
    status = [t for _, t in texts(ROOT / "status.py")]
    shown = {
        "wrong_code": cli.NOT_CONNECTED["wrong_code"],
        "cert_changed": cli.NOT_CONNECTED["cert_changed"],
        "port": "could not flash" + cli._port_hint(Who()),
        "intake": next(t for t in cli_texts if "intake edit" in t),
        "local-intake": next(t for t in cli_texts if "local-intake status" in t),
        "web": next(t for t in status if "filament-kit-web" in t and "journalctl" in t),
        "config": next(t for t in status if "option 4" in t and "internet" in t),
    }
    for columns in ("80", "40"):
        monkeypatch.setenv("COLUMNS", columns)
        for name, text in shown.items():
            cmds = commands(text)
            assert cmds, f"{name} has no command"
            for lines in _layouts(text):
                for c in cmds:
                    assert _whole(c, lines), f"{name}: {c!r} split at {columns} columns: {lines}"
    monkeypatch.setenv("COLUMNS", "80")
    lines = output.status_row("needs a look", "a row", shown["web"])       # no 94-character line after a lone `Fix:`
    assert all(len(x) <= 79 for x in lines), lines


# ---------- a command that does not fit goes on its own line (06 6.5) ----------

def test_06_6_5_example_is_reproduced_at_80_columns(monkeypatch):
    """`Fix: check ... test it:` and the command on a line of its own, five spaces in, no quotes or braces added."""
    monkeypatch.setenv("COLUMNS", "80")
    command = 'sudo spoolwarden printer test "Study A1 mini"'
    fix = "check that it is switched on and on the network, then test it: " + command
    assert output.wrap("Fix: " + fix, indent=5, first=0) == [
        "Fix: check that it is switched on and on the network, then test it:", "     " + command]


def test_a_command_that_fits_stays_on_the_line_and_one_that_does_not_goes_to_its_own(monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    assert output.wrap("Fix: run sudo filament-kit update again", indent=5, first=0) == [
        "Fix: run sudo filament-kit update again"]
    got = output.wrap("Error: it failed, so go on and then sudo filament-kit profiles apply-updates --all --dry-run now",
                      indent=7, first=0)
    assert got == ["Error: it failed, so go on and then",
                   "     sudo filament-kit profiles apply-updates --all --dry-run now"]
    rows = output.status_row("needs a look", "a row",
                             "check it, then: sudo journalctl -u filament-kit -n 50 --no-pager --output cat")
    assert rows[-1].startswith(" " * 23 + "sudo journalctl") and rows[-2].rstrip().endswith("then:")


@pytest.mark.parametrize("text, command", [
    ("go on (sudo filament-kit update installs it), then stop", "sudo filament-kit update"),
    ("Paste the link from sudo filament-kit pair --station on the server: ", "sudo filament-kit pair --station"),
    ("it is gone; run sudo systemctl daemon-reload && sudo systemctl restart nginx. Then wait",
     "sudo systemctl daemon-reload && sudo systemctl restart nginx"),
    ("add it: sudo usermod -aG dialout alice, then log in again", "sudo usermod -aG dialout alice"),
    ("or: python3 -m pip install --user platformio. Or leave out --source", "python3 -m pip install --user platformio"),
    ("a clone: curl -fsSL <get.sh url> | sudo bash -s -- --version 1.2.3", "curl -fsSL <get.sh url> | sudo bash -s -- --version 1.2.3"),
    ("then in its folder run: sudo ./uninstall.sh --purge)", "sudo ./uninstall.sh --purge"),
])
def test_where_a_command_ends(text, command, monkeypatch):
    """Commands are cut at the end of their clause, wherever they sit in a sentence, at two widths."""
    assert commands(text) == [command]
    for columns in ("80", "40"):
        monkeypatch.setenv("COLUMNS", columns)
        assert _whole(command, output.wrap(text)), output.wrap(text)


def test_a_program_name_in_ordinary_prose_is_no_command(monkeypatch):
    monkeypatch.setenv("COLUMNS", "20")
    got = output.wrap("run it with sudo to be sure; the filament-kit server is up")
    assert got == ["run it with sudo to", "be sure; the", "filament-kit server", "is up"]     # no line of its own


# ---------- user text and backticks ----------

def test_a_backtick_in_a_text_is_printed_as_it_is(monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    assert output.wrap("no printer named a`b here") == ["no printer named a`b here"]
    assert output.wrap("name `x here") == ["name `x here"]
    assert output.wrap("Printer Shop `A B` X1, and `odd") == ["Printer Shop `A B` X1, and `odd"]
    assert output.wrap("see: `sudo filament-kit status` now") == ["see: `sudo filament-kit status` now"]
    monkeypatch.setenv("COLUMNS", "25")
    got = output.wrap("a `sudo filament-kit config`, Printers) and more")        # the backticks are part of the words
    assert got == ["a", "     `sudo filament-kit config`,", "Printers) and more"], got


# ---------- no marker in any text ----------

CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f]")        # not tab, newline, carriage return, escape


def _plain(text: str, where: str) -> None:
    assert not CONTROL.search(text), f"{where}: a control byte in {text!r}"


@pytest.mark.parametrize("module", MODULES + ("output.py", "setup_console/overview.py"))
def test_no_module_builds_a_marker_into_a_text(module):
    src = (ROOT / module).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) > 1:     # a text, not a one-character test
            _plain(n.value, f"{module}:{n.lineno}")
        if isinstance(n, ast.Call) and _call_name(n) == "cmd" and isinstance(n.func, ast.Attribute):
            raise AssertionError(f"{module}:{n.lineno}: a call that marks a command")
    assert not hasattr(output, "cmd")


def test_the_status_rows_and_their_fixes_are_plain_strings(monkeypatch):
    """The setup page's Overview sends each row's text and fix as they are."""
    from filament_kit import status
    for _, text in texts(ROOT / "status.py"):
        _plain(text, "status.py")
    for r in (status.Row("fail", "x", "run: sudo filament-kit cert"), ):
        assert r.fix == "run: sudo filament-kit cert"


def test_the_texts_other_places_print_hold_no_marker(monkeypatch, tmp_path):
    """The firewall text, the library line, the local reader's plan, and the station's pair prompts."""
    from unittest import mock

    from filament_kit import local_intake_install as lii
    from filament_kit import remote
    with mock.patch.object(remote, "sandbox_text", lambda r, lan: "x"):
        t = remote.firewall_text({"hostname": "h.example.com", "route": "r", "lan": ["192.168.1.0/24"], "email": "",
                                  "window": ""}, tmp_path)
    _plain(t, "firewall_text")
    assert "sudo filament-kit remote issue" in t and "sudo systemctl daemon-reload" in t
    _plain(cli._library_line({"source": "none", "local": 2}), "library status")
    assert "(run: filament-kit library update)" in cli._library_line({"source": "none", "local": 2})
    p = {"version": "1.0", "tier": "cpu", "installed": "2.0", "installed_tier": "cpu", "downgrade": True,
         "upgrade": False, "same": False, "tiers": {"cpu": {"download_mb": 1, "disk_mb": 2, "minutes": 1, "fetched_at_install": ""}},
         "asked_tier": None}
    for line in lii.plan_text(p):
        _plain(line, "plan")
    assert any("filament-kit local-intake install --version 1.0" in x for x in lii.plan_text(p))
    seen: list[str] = []

    def ask(prompt):
        seen.append(prompt)
        raise EOFError
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0, raising=False)
    cli.cmd_station_pair(ask=ask)
    assert seen and all("sudo filament-kit pair --station" in s for s in seen)
    for s in seen:
        _plain(s, "pair prompt")


# the setup page's own pattern (setup_static/setup_overview.js FIX_COMMAND), ported
FIX_COMMAND = re.compile(r"^(?:run: )?((?:sudo|filament-kit) .+)$")


def test_the_setup_pages_pattern_matches_every_status_fix_that_is_a_command():
    src = (ROOT / "setup_static" / "setup_overview.js").read_text(encoding="utf-8")
    assert "const FIX_COMMAND = /^(?:run: )?((?:sudo|filament-kit) .+)$/;" in src      # the port is of this one
    seen = 0
    for line, text in texts(ROOT / "status.py"):
        if not (text.startswith("run: ") or re.match(r"(?:sudo|filament-kit|systemctl|journalctl) ", text))                 or not COMMAND.search(text):
            continue                                   # not a fix that is a command
        seen += 1
        m = FIX_COMMAND.match(text)
        assert m and m[1].startswith(("sudo", "filament-kit")), f"status.py:{line}: {text!r}"
        _plain(text, f"status.py:{line}")
    assert seen >= 8


# ---------- where a command ends: its arguments, not the clause (refuter-23) ----------

@pytest.mark.parametrize("columns", ["80", "40", "30"])
def test_a_quoted_argument_with_prose_words_or_a_comma_belongs_to_the_command(columns, monkeypatch):
    monkeypatch.setenv("COLUMNS", columns)
    for text, command in (('Fix: run sudo filament-kit printer test "Bench by the door"', 'sudo filament-kit printer test "Bench by the door"'),
                          ('Fix: run sudo filament-kit printer test "Bench, by the door", then wait',
                           'sudo filament-kit printer test "Bench, by the door",')):
        lines = output.wrap(text, indent=5, first=0)
        assert _whole(command, lines), lines
        assert all(len(x) <= int(columns) - 1 or " " not in x.strip() or x.strip() == command for x in lines), lines


@pytest.mark.parametrize("text, command, rest", [
    ("sudo filament-kit status before you start,", "sudo filament-kit status", "before you start,"),
    ("run sudo filament-kit config when ready", "sudo filament-kit config", "when ready"),
    ("run sudo filament-kit station pair here", "sudo filament-kit station pair", "here"),
    ("run sudo filament-kit klipper add NAME 192.168.1.50 first", "sudo filament-kit klipper add NAME 192.168.1.50", "first"),
    ("run sudo filament-kit reader token --name printer-station now", "sudo filament-kit reader token --name printer-station", "now"),
    ("run filament-kit printer map --manual <serial> soon", "filament-kit printer map --manual <serial>", "soon"),
    ("run sudo filament-kit local-intake install --version 1.2.3 and wait", "sudo filament-kit local-intake install --version 1.2.3", "and wait"),
])
def test_a_command_ends_at_the_first_word_that_is_not_an_argument(text, command, rest, monkeypatch):
    """A word that is not in the prose list is not glued on: only an option, a quoted value, a NAME or placeholder, a
    path, an address, a number, or a subcommand word right after the command word belongs to the command."""
    monkeypatch.setenv("COLUMNS", "80")
    units = output._units(text)
    assert [u for u, is_cmd in units if is_cmd] == [command]
    assert " ".join(u for u, is_cmd in units if not is_cmd)[-len(rest):] == rest
    monkeypatch.setenv("COLUMNS", "34")
    lines = output.wrap(text)
    assert _whole(command, lines) and not any(command + " " + rest.split()[0] in " ".join(x.split()) and len(x) > 33 for x in lines), lines


def test_no_line_has_a_trailing_space_after_a_double_space_at_a_break(monkeypatch):
    monkeypatch.setenv("COLUMNS", "40")
    lines = output.wrap("Fix: run: sudo filament-kit config  and then more words follow here", indent=5, first=0)
    assert all(x == x.rstrip() for x in lines), lines
    assert all(x == x.rstrip() for x in output.wrap("Fix: run: sudo filament-kit config  ", indent=5, first=0))


def test_the_width_check_also_fails_on_a_command_glued_to_a_word_and_too_wide(monkeypatch):
    """The scan's over-width test accepts a long line only when the command is alone on it: a word after it fails."""
    monkeypatch.setenv("COLUMNS", "40")
    cmd = "sudo filament-kit klipper add NAME 192.168.1.50"
    assert not _over_width_ok("Fix: " + cmd + " before", 40, [cmd])
    assert _over_width_ok("     " + cmd, 40, [cmd])
    assert _over_width_ok("Fix: " + cmd, 40, [cmd])
    assert _over_width_ok("short line", 40, [cmd])
