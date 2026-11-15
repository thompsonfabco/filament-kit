"""The product is called Spoolwarden wherever a person reads it: the catalogue, the Hub page, the installer's messages and
the updater's messages (design 09 open point 12). `filament-kit` stays only where it names something else: the command
(`sudo filament-kit update`, `filament-kit apply`), a path, a unit, a user, a package or a URL. The test reads every
visible text of those files and fails on a `filament-kit` that is none of these. Release notes and the changelog are
history and are not read."""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "server" / "filament_kit"

# Also the command or an identifier: `sudo ` and `sudo|` before it, a user or group (`-u`, `-g`, `root:`), and a string
# that is only the name (a unit or user prefix, a file name part).
# Subcommands of the `filament-kit` command: `filament-kit <one of these>` names the command, not the product.
SUBCOMMANDS = ("apply", "backup", "config", "library", "logs", "mcp-route", "modules", "presets", "reader", "restore",
               "rollback", "setup-code", "station", "update", "--plain")
NAME = re.compile(r"(?<![\w/.\-`])filament-kit(?!\.?[\w/\-])")
COMMAND = re.compile(r"(?:%s)(?![\w-])" % "|".join(re.escape(s) for s in SUBCOMMANDS))
SHELL_TEXT = re.compile(r"\b(?:echo|printf|say|die|warn)\b")


def product_name_uses(text):
    """The `filament-kit` in `text` that is used as the product name, as the text around each."""
    found = []
    for m in NAME.finditer(text):
        before, after = text[:m.start()], text[m.end():]
        if before.endswith(("sudo ", "sudo|", "-u ", "-g ", ":")) or text == "filament-kit" or COMMAND.match(after.lstrip(" ") if after.startswith(" ") else "\0"):
            continue
        found.append(text[max(0, m.start() - 20):m.end() + 20])
    return found


def _py_texts(path):
    """Every string of a Python file except the docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def _script_lines(path):
    """The lines of a page script that are not comments."""
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith(("//", "*", "/*"))]


def _shell_messages(path):
    return [ln for ln in path.read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("#") and SHELL_TEXT.search(ln)]


def sources():
    """(name, texts) of every visible text the rule covers."""
    out = [("strings/en.json", [v for k, v in json.loads((ROOT / "strings" / "en.json").read_text("utf-8")).items()
                                if isinstance(v, str) and k != "command_name"])]
    for p in (PKG / "setup_static", ROOT / "web-shared"):
        for f in sorted(p.iterdir()):
            if f.suffix in (".js", ".css", ".html"):
                out.append((f.relative_to(ROOT).as_posix(), _script_lines(f)))
    for f in ("setup_page.py", "updates.py"):
        out.append((f"server/filament_kit/{f}", _py_texts(PKG / f)))
    for f in sorted((ROOT / "install").rglob("*.sh")):
        out.append((f.relative_to(ROOT).as_posix(), _shell_messages(f)))
    return out


def findings(srcs):
    return [f"{name}: ...{use}..." for name, texts in srcs for t in texts for use in product_name_uses(t)]


def test_the_product_is_spoolwarden_in_every_visible_text():
    assert json.loads((ROOT / "strings" / "en.json").read_text("utf-8"))["app_name"] == "Spoolwarden"
    assert findings(sources()) == []


def test_the_rule_tells_the_product_from_the_command():
    for ok in ("sudo filament-kit update", "run: filament-kit apply", "/etc/filament-kit", "filament-kit-setup.socket",
               "github.com/thompsonfabco/filament-kit/releases", "`filament-kit backup create`", "filament-kit.apk"):
        assert product_name_uses(ok) == [], ok
    for bad in ("Installing filament-kit 1.2", "filament-kit: the saved certificate", "filament-kit is not installed",
                "removed filament-kit.", "Welcome to filament-kit"):
        assert len(product_name_uses(bad)) == 1, bad


def test_a_planted_product_name_fails():
    planted = sources() + [("planted", ['say "Installing filament-kit ($v)"'])]
    assert [f.split(":")[0] for f in findings(planted)] == ["planted"]
