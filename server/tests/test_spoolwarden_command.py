"""S5.9: the command is `spoolwarden` (06 section 2). `filament-kit` is a small wrapper that prints one Note line on
standard error and runs `spoolwarden` with the same arguments, standard input, standard output and exit code."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from fakes.shells import git_bash
from filament_kit import __version__, cli

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "server" / "filament_kit"
NOTE = "Note: filament-kit is now called spoolwarden; the old name will be removed."
BASH = git_bash()
needs_bash = pytest.mark.skipif(not BASH, reason="needs bash")


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _tools(tmp_path: Path, spoolwarden_body: str) -> dict:
    """A folder with a stand-in `spoolwarden` and the wrapper, which is changed to run the stand-in."""
    (tmp_path / "spoolwarden").write_text(f"#!/usr/bin/env bash\n{spoolwarden_body}\n", encoding="utf-8", newline="\n")
    wrapper = _text("install/filament-kit-wrapper.sh")
    assert "exec /usr/local/bin/spoolwarden" in wrapper
    wrapper = wrapper.replace("exec /usr/local/bin/spoolwarden", f"exec bash {(tmp_path / 'spoolwarden').as_posix()}")
    (tmp_path / "filament-kit").write_text(wrapper, encoding="utf-8", newline="\n")
    return {"spoolwarden": tmp_path / "spoolwarden", "filament-kit": tmp_path / "filament-kit"}


def _run(path: Path, *args, stdin="", env=None):
    return subprocess.run([BASH, path.as_posix(), *args], input=stdin, capture_output=True, text=True, timeout=60,
                          env={**os.environ, **(env or {})})


@needs_bash
@pytest.mark.parametrize("flags", [[], ["--json"], ["--quiet"], ["-q", "--json"]])
def test_the_wrapper_prints_the_note_on_stderr_only_and_passes_everything_else_through(tmp_path, flags):
    body = 'echo "out $*"; cat; echo "err" >&2; exit 7'
    tools = _tools(tmp_path, body)
    direct = _run(tools["spoolwarden"], *flags, "backup", "create", stdin="from stdin\n")
    wrapped = _run(tools["filament-kit"], *flags, "backup", "create", stdin="from stdin\n")
    assert wrapped.stdout == direct.stdout == f"out {' '.join(flags + ['backup', 'create'])}\nfrom stdin\n"
    assert wrapped.returncode == direct.returncode == 7
    assert direct.stderr == "err\n"
    assert wrapped.stderr == NOTE + "\n" + "err\n"                       # the one line first, on standard error
    assert NOTE not in wrapped.stdout


@needs_bash
def test_the_wrapper_keeps_each_argument_whole_spaces_and_empty_ones_included(tmp_path):
    body = 'printf "%s|" "$#" "$@"; echo'
    tools = _tools(tmp_path, body)
    args = ["printer", "test", "Bench by the door", ""]
    direct = _run(tools["spoolwarden"], *args)
    wrapped = _run(tools["filament-kit"], *args)
    assert direct.stdout == wrapped.stdout == "4|printer|test|Bench by the door||\n"


@needs_bash
def test_the_wrapper_note_is_one_line_and_the_command_script_has_none(tmp_path):
    assert _text("install/filament-kit-wrapper.sh").count("is now called spoolwarden") == 1
    assert "is now called" not in _text("install/spoolwarden-cli.sh")
    assert "is now called" not in " ".join(p.read_text(encoding="utf-8") for p in SRC.glob("*.py"))


def _stub_over_the_program(tmp_path: Path) -> dict:
    """`spoolwarden` runs the real command line in this checkout (state kept in the temp folder)."""
    py = Path(sys.executable).as_posix()
    body = f'export PYTHONPATH="{(ROOT / "server").as_posix()}"\nexec "{py}" -I -c \'import sys; sys.path.insert(0, "{(ROOT / "server").as_posix()}"); from filament_kit import cli; sys.exit(cli.main())\' "$@"'
    return _tools(tmp_path, body)


def _env(tmp_path: Path) -> dict:
    return {"COLUMNS": "80", "NO_COLOR": "1", "TERM": "dumb", "PYTHONIOENCODING": "utf-8"}


@needs_bash
def test_aut9_through_each_name_plain_help_holds_80_columns_and_no_escapes(tmp_path):
    """AUT-9 (07 CLI-1, CLI-2, CLI-10): `--plain` help has no ESC or CR and no line over 79 characters, under both
    names; the output is the same, and the old name adds only the Note on standard error."""
    tools = _stub_over_the_program(tmp_path)
    got = {}
    for name, path in tools.items():
        r = _run(path, "--plain", "-h", env=_env(tmp_path))
        assert r.returncode == 0, r.stderr
        assert "\x1b" not in r.stdout + r.stderr and "\r" not in r.stdout
        assert max(len(line) for line in r.stdout.splitlines()) <= 79
        got[name] = r
    assert got["spoolwarden"].stdout == got["filament-kit"].stdout
    assert got["spoolwarden"].stdout.startswith("Spoolwarden on this Hub.")
    assert not _OLD_COMMAND.search(got["spoolwarden"].stdout)
    assert got["filament-kit"].stderr == NOTE + "\n" and got["spoolwarden"].stderr == ""


@needs_bash
def test_aut9_through_each_name_a_failing_command_has_empty_stdout_and_an_error_on_stderr(tmp_path):
    tools = _stub_over_the_program(tmp_path)
    got = {}
    for name, path in tools.items():
        r = _run(path, "--plain", "no-such-command", env=_env(tmp_path))
        assert r.returncode == 2 and r.stdout == ""
        got[name] = r
    assert got["spoolwarden"].stderr.startswith("Error: ")
    assert got["filament-kit"].stderr == NOTE + "\n" + got["spoolwarden"].stderr          # the Note, then the same error
    assert "spoolwarden -h" in got["spoolwarden"].stderr and "filament-kit" not in got["spoolwarden"].stderr


@needs_bash
def test_json_stays_parseable_through_the_old_name(tmp_path):
    import json
    tools = _stub_over_the_program(tmp_path)
    for name, path in tools.items():
        r = _run(path, "--json", "no-such-command", env=_env(tmp_path))
        assert r.returncode == 2
        doc = json.loads(r.stdout)                                      # the Note is on standard error, never in here
        assert doc["error"]
        assert (NOTE in r.stderr) == (name == "filament-kit")


def test_version_prints_the_product_name_and_the_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out == f"Spoolwarden {__version__}\n"


def test_help_usage_and_errors_name_spoolwarden(capsys):
    cli.main([])
    out = capsys.readouterr().out
    assert "Usage: spoolwarden <command> [options]    More: spoolwarden <command> -h" in out
    with pytest.raises(SystemExit):
        cli.main(["status", "--bogus"])
    err = capsys.readouterr().err
    assert "Fix: see what it takes with: spoolwarden -h" in err or "spoolwarden status -h" in err


def test_the_python_package_has_both_console_scripts():
    text = _text("server/pyproject.toml")
    assert re.search(r'^spoolwarden = "filament_kit\.cli:main"', text, re.M)
    assert re.search(r'^filament-kit = "filament_kit\.cli:main"', text, re.M)


def test_the_programs_internal_callers_run_spoolwarden():
    from filament_kit import apply, backup, setup_helper
    assert apply.WRAPPER == backup.WRAPPER == setup_helper.WRAPPER == "/usr/local/bin/spoolwarden"


def test_install_puts_both_files_and_uninstall_removes_both():
    inst, unin = _text("install/install.sh"), _text("install/uninstall.sh")
    assert 'install -m 755 "$RES/spoolwarden-cli.sh" /usr/local/bin/spoolwarden' in inst
    assert 'install -m 755 "$RES/filament-kit-wrapper.sh" /usr/local/bin/filament-kit' in inst
    assert re.search(r"^rm -f /usr/local/bin/spoolwarden /usr/local/bin/filament-kit$", unin, re.M)
    make = _text("tools/make_release.sh")
    assert "install/spoolwarden-cli.sh" in make and "install/filament-kit-wrapper.sh" in make


_OLD_COMMAND = re.compile(r"\bsudo filament-kit\b|(?<![\w./-])filament-kit (?:status|pair|config|cert|modules|features|"
                          r"remote|update|uninstall|station|weigh-station|setup-code|logs|spoolman|catalog|library|"
                          r"backup|restore|web|reader|local-intake|printer|klipper|recent|tag-reader|presets|"
                          r"ensure-fields|devices|unpair|intake|label-reader|profiles|apply|help)\b")
# Hub page and setup-console texts belong to their own steps (they still work: the old name is a wrapper).
_NOT_THIS_STEP = ("setup_page.py", "setup_helper.py", "setup_console", "shared_static", "setup_static", "web")


# data and protocol text that happen to read like a command: the pairing hashes, the backup's own name, a file's marker
_DATA = ("sha256(", "not a filament-kit backup", "<!-- filament-kit")


def test_no_command_text_in_the_program_says_filament_kit():
    bad = []
    for p in sorted(SRC.rglob("*.py")):
        rel = p.relative_to(SRC).as_posix()
        if any(rel == n or rel.startswith(n + "/") or rel.startswith(n) and n.endswith(".py") for n in _NOT_THIS_STEP):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _OLD_COMMAND.search(line) and not any(k in line for k in _DATA):
                bad.append(f"{rel}:{i}: {line.strip()[:90]}")
    assert not bad, "\n".join(bad)
