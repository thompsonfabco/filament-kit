"""install/filament-kit-cli.sh: which commands run as root and which as the service user (FA-105).

A copy of the wrapper runs under bash with `id` saying root, and stub `runuser` and program that print what they were
given, so each command's route is read off the output.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "install" / "filament-kit-cli.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None or os.name == "nt", reason="the wrapper is a bash script for the Hub")

ROOT_COMMANDS = [
    ["config", "show"], ["cert", "status"], ["modules", "apply"], ["modules", "set", "full"], ["update"],
    ["uninstall"], ["station", "pair"], ["setup-code"], ["backup", "create"], ["restore", "x.zip"],
    ["web", "passphrase"], ["reader", "token", "a"], ["reader", "revoke", "a"], ["reader", "setup"],
    ["local-intake", "install", "--yes", "--planned"], ["local-intake", "remove", "--yes"],
    ["local-intake", "token"], ["local-intake", "plan"],
]
USER_COMMANDS = [
    ["local-intake", "status"], ["local-intake", "test", "a.jpg"], ["web", "status"], ["reader", "tokens"],
    ["printer", "list"], ["recent"],
]


def _route(tmp_path, args):
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    for name, body in (("id", 'echo 0'), ("runuser", 'shift 3; echo "AS-USER $*"'),
                       ("systemctl", "exit 1"), ("pgrep", "exit 1"), ("fk", 'echo "AS-ROOT $*"')):
        p = stubs / name
        p.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8", newline="\n")
        p.chmod(0o755)
    text = WRAPPER.read_text(encoding="utf-8")
    text = text.replace("BIN=/opt/filament-kit/venv/bin/filament-kit", f"BIN={stubs / 'fk'}")
    text = text.replace("STATION_DIR=/etc/filament-kit-station", f"STATION_DIR={tmp_path / 'no-station'}")
    text = text.replace("KIT_OPT=/opt/filament-kit", f"KIT_OPT={tmp_path / 'no-opt'}")
    script = tmp_path / "wrapper.sh"
    script.write_text(text, encoding="utf-8", newline="\n")
    env = {**os.environ, "PATH": f"{stubs}:{os.environ.get('PATH', '')}"}
    r = subprocess.run([BASH, str(script), *args], capture_output=True, text=True, env=env, timeout=30)
    return r.stdout.strip()


def test_the_wrapper_is_patched_where_the_test_expects():
    text = WRAPPER.read_text(encoding="utf-8")
    for line in ("BIN=/opt/filament-kit/venv/bin/filament-kit", "STATION_DIR=/etc/filament-kit-station",
                 "KIT_OPT=/opt/filament-kit"):
        assert line in text, line


@pytest.mark.parametrize("args", ROOT_COMMANDS, ids=" ".join)
def test_root_commands_run_as_root(tmp_path, args):
    assert _route(tmp_path, args) == "AS-ROOT " + " ".join(args)


@pytest.mark.parametrize("args", USER_COMMANDS, ids=" ".join)
def test_other_commands_run_as_the_service_user(tmp_path, args):
    assert _route(tmp_path, args).startswith("AS-USER ")
