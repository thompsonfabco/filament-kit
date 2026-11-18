"""AF1: install.sh's new parts (R82 sections 1 and 3): the first question, the port decision and its questions, the
port written at a first install, the first-run file; and apply's Guided Setup ending and addresses. The shell pieces are
cut out of install.sh and run with bash (a pseudo-terminal where a terminal is the point); Linux only."""
import io
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from filament_kit import apply, config, firstrun, hubport, modules, setup_code

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
BASH = shutil.which("bash")
linux = pytest.mark.skipif(os.name == "nt" or not BASH, reason="bash and a pseudo-terminal (Linux)")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt", "bk"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_BACKUPS", str(tmp_path / "bk"))
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.delenv("FK_GUIDED", raising=False)
    return tmp_path


def between(start: str, end: str) -> str:
    a = TEXT.index(start)
    return TEXT[a:TEXT.index(end, a)]


def run_tty(script: str, answers: str = "", extra_env: dict | None = None) -> tuple[int, str]:
    """Run bash on `script` with a terminal as standard input, the answers typed; (exit status, all its output)."""
    import pty
    master, slave = pty.openpty()
    p = subprocess.Popen([BASH, "-c", script], stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         env={**os.environ, **(extra_env or {})})
    os.close(slave)
    os.write(master, answers.encode())
    out = p.communicate(timeout=60)[0].decode()
    os.close(master)
    return p.returncode, out


def run_plain(script: str, extra_env: dict | None = None) -> tuple[int, str]:
    p = subprocess.run([BASH, "-c", script], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
                       env={**os.environ, **(extra_env or {})})
    return p.returncode, p.stdout + p.stderr


def fake_venv(tmp: Path, check_reply: str = "", check_ok: bool = True) -> Path:
    """A $VENV whose python answers `hubport check <typed>` the way the real one would for a few ports."""
    (tmp / "venv" / "bin").mkdir(parents=True)
    py = tmp / "venv" / "bin" / "python"
    py.write_text('#!/bin/bash\n[ "$4" = check ] || exit 2\n'
                  'case "$5" in 9000) echo "Port 9000 is already in use on this machine." >&2; exit 1 ;;\n'
                  '  80) echo "Port 80 is not allowed: use 1024 to 65535." >&2; exit 1 ;;\n'
                  '  *) echo "$5" ;; esac\n')
    py.chmod(0o755)
    return tmp / "venv"


PICK = between("pick_port() {", "HUB_HERE=0;")


# ---- the file itself

@linux
def test_install_sh_is_valid_bash():
    assert subprocess.run([BASH, "-n", str(ROOT / "install" / "install.sh")], capture_output=True).returncode == 0


# ---- the first question

GUIDED_BLOCK = between("# The first question (R82 section 3)", '    ASKED="features"').rsplit("\nif [ -z", 1)[0] + "\n"


def guided(answers: str, default: str = "y", first=1, pre: str = "") -> tuple[str, str]:
    script = (f'MODE=""; CUSTOM=""; SETS=""; SERVER_ADDR=""; FIRST_INSTALL={first}; GUIDED=0; GUIDED_DEFAULT={default}; '
              f'AGAIN=again\n{pre}\n'
              'die() { echo "die: $*"; exit 1; }\n' + GUIDED_BLOCK + 'echo "RESULT MODE=$MODE GUIDED=$GUIDED"\n')
    rc, out = run_tty(script, answers)
    return out, (re.search(r"RESULT (.*)", out) or [None, "none"])[1]


@linux
def test_the_first_question_text_and_its_default_yes():
    out, result = guided("\n")
    assert "y: the Hub is installed with the usual choices; its page takes you through the rest." in out
    assert "n: answer the questions here. Also the way to install only a Weigh Station." in out
    assert "Finish setting up in your browser (Guided Setup)? [Y/n]" in out
    assert result == "MODE=server GUIDED=1"


@linux
def test_the_first_question_no_goes_on_to_the_mode_question():
    assert guided("n\n")[1] == "MODE= GUIDED=0"
    assert guided("y\n")[1] == "MODE=server GUIDED=1"


@linux
def test_open_point_5_changes_the_default_in_one_place():
    out, result = guided("\n", default="n")
    assert "[y/N]" in out and result == "MODE= GUIDED=0"


@linux
def test_an_explicit_flag_skips_the_question_and_keeps_its_value():
    for pre in ('SERVER_ADDR=hub.example.lan', 'SETS="set station.allow=x"', 'MODE=server', 'CUSTOM=,server'):
        out, result = guided("y\n", pre=pre)
        assert "Guided Setup" not in out, pre
        assert "GUIDED=0" in result
    out, result = guided("y\n", pre="SERVER_ADDR=hub.example.lan")
    assert "SERVER_ADDR" not in result            # the block never touches it
    script = ('MODE=""; CUSTOM=""; SETS=""; SERVER_ADDR=hub.example.lan; FIRST_INSTALL=1; GUIDED=0; GUIDED_DEFAULT=y\n'
              + GUIDED_BLOCK + 'echo "RESULT $SERVER_ADDR $MODE"\n')
    assert run_tty(script, "y\n")[1].strip().endswith("RESULT hub.example.lan")


@linux
def test_the_first_question_is_not_asked_with_a_mode_modules_or_on_an_upgrade():
    for pre in ('MODE=station', 'CUSTOM=,station'):
        script = ('MODE=""; CUSTOM=""; FIRST_INSTALL=1; GUIDED=0; GUIDED_DEFAULT=y\n' + pre + '\n' + GUIDED_BLOCK
                  + 'echo "RESULT $GUIDED"\n')
        assert "Guided Setup" not in run_tty(script, "y\n")[1]
    assert "Guided Setup" not in guided("y\n", first=0)[0]
    # no terminal: no question
    script = 'MODE=""; CUSTOM=""; FIRST_INSTALL=1; GUIDED=0; GUIDED_DEFAULT=y\n' + GUIDED_BLOCK + 'echo "RESULT $GUIDED"\n'
    assert run_plain(script)[1].strip() == "RESULT 0"


# ---- the port question

def pick(tmp, kind, offered, answers=None, who="Hub", guided_on=0):
    script = (f'VENV={fake_venv(tmp)}; GUIDED={guided_on}\n' + PICK
              + f'port=$(pick_port "{who}" {kind} {offered})\necho "PORT=$port"\n')
    rc, out = run_tty(script, answers) if answers is not None else run_plain(script)
    return out, re.search(r"PORT=(\d+)", out).group(1)


@linux
def test_taken_at_a_terminal_asks_and_enter_takes_the_offer(tmp_path):
    out, port = pick(tmp_path, "taken", 8710, "\n")
    assert "Port 443 is already in use on this machine." in out and "Remote access" not in out
    assert "Port for the Hub [8710]:" in out and port == "8710"


@linux
def test_remote_access_gives_its_reason(tmp_path):
    out, port = pick(tmp_path, "remote", 8710, "\n")
    assert "Port 443 is already in use on this machine. Remote access uses it for the public address." in out
    assert port == "8710"


@linux
def test_a_typed_port_is_checked_and_the_question_repeats(tmp_path):
    out, port = pick(tmp_path, "taken", 8710, "80\n9000\n9100\n")
    assert "Port 80 is not allowed: use 1024 to 65535." in out
    assert "Port 9000 is already in use on this machine." in out
    assert port == "9100" and out.count("Port for the Hub [8710]:") == 3


@linux
def test_an_unsure_test_asks_too(tmp_path):
    out, port = pick(tmp_path, "unsure", 8710, "\n")
    assert "could not be checked" in out and "Port for the Hub [8710]:" in out


@linux
def test_without_a_terminal_the_hub_takes_the_offer_and_says_so(tmp_path):
    out, port = pick(tmp_path, "taken", 8711)
    assert "Port 443 is in use on this machine, so the Hub uses port 8711." in out and "Port for the" not in out
    assert port == "8711"


@linux
def test_guided_setup_asks_nothing_even_at_a_terminal(tmp_path):
    out, port = pick(tmp_path, "taken", 8710, "", guided_on=1)
    assert "Port 443 is in use on this machine, so the Hub uses port 8710." in out and "Port for the" not in out


@linux
def test_the_station_asks_with_its_own_name(tmp_path):
    out, port = pick(tmp_path, "taken", 5003, "\n", who="Weigh Station")
    assert "Port for the Weigh Station [5003]:" in out and port == "5003"


# ---- the port written at a first install

def config_block() -> str:
    a = TEXT.index("FK_MODE=\"$MODE\"")
    a = TEXT.index("'", a) + 1
    return TEXT[a:TEXT.index("\n'\n", a)]


def write_config(tmp, mode="server", hub_port="", station_port="", server=""):
    code = config_block()
    e = {**os.environ, "FK_MODE": mode, "FK_MODULES": "", "FK_AI": "", "FK_SETS": "", "FK_SERVER": server,
         "FK_HUB_PORT": hub_port, "FK_STATION_PORT": station_port, "FK_ETC": str(tmp / "etc"),
         "PYTHONPATH": str(ROOT / "server")}
    r = subprocess.run([sys.executable, "-c", code], env=e, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    import json
    return json.loads((tmp / "etc" / "config.json").read_text())


def test_a_first_install_writes_the_port_into_the_config_file(env):
    assert write_config(env, hub_port="443")["port"] == 443


def test_a_first_install_without_a_decision_writes_no_port(env):       # an old Hub's file never gets one
    assert "port" not in write_config(env)


def test_a_new_station_install_writes_its_port(env):
    cfg = write_config(env, mode="station", station_port="443", server="hub.example.lan")
    assert cfg["station"]["port"] == 443 and "port" not in cfg


def test_only_a_first_install_decides_a_port():
    assert re.search(r'FIRST_INSTALL" -eq 1 \] && \[ "\$HUB_HERE" -eq 1', TEXT)
    assert re.search(r'FIRST_INSTALL" -eq 1 \] && \[ "\$STATION_HERE" -eq 1', TEXT)
    assert hubport.__file__


def test_the_first_run_file_is_made_by_the_first_install_only():
    assert 'if [ "$FIRST_INSTALL" -eq 1 ] && [ "$HUB_HERE" -eq 1 ]; then\n    # shellcheck disable=SC2086\n' \
           '    "$VENV/bin/python" -I -m filament_kit.firstrun new $ASKED' in TEXT


def test_the_program_install_sh_calls_answers(capsys):
    assert hubport._main(["offer", "plain"]) == 0
    assert capsys.readouterr().out.split()[0] in ("free", "taken", "unsure")
    assert hubport._main(["check", "70000"]) == 1
    assert hubport._main(["bogus"]) == 2
    assert firstrun._main(["new", "name"]) == 0 and firstrun.load().answered == {"name"}
    assert firstrun._main(["new", "bogus"]) == 2


# ---- apply: Guided Setup and the address without a port

def _cfg(port):
    cfg = config.load()
    cfg["port"] = port
    cfg["modules"] = {n: n in {"server", "spoolman"} for n in modules.MODULES}
    return cfg


def test_addresses_have_no_port_on_443():
    assert setup_code.page_url({"port": 443}).endswith(".local/setup")
    assert ":8710/setup" in setup_code.page_url({"port": 8710}) and ":8710/setup" in setup_code.page_url({})
    assert setup_code.base_url({"port": 443}).endswith(".local/")
    assert apply.app_url({"port": 443}).endswith(".local/app.apk") or "/app.apk" in apply.app_url({"port": 443})
    assert ":443" not in apply.app_url({"port": 443})
    assert apply.app_url({"port": 8710}).endswith(":8710/app.apk")


def test_the_firewall_line_names_the_real_port(monkeypatch, capsys):
    monkeypatch.setattr(apply.shutil, "which", lambda n: "/usr/sbin/ufw")
    monkeypatch.setattr(apply.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "Status: active\n"))
    apply._firewall_note(_cfg(443), {"server"})
    assert "sudo ufw allow 443/tcp" in capsys.readouterr().out


def finish_output(monkeypatch, capsys, guided_on, port=443, code="12345678"):
    monkeypatch.setattr(apply, "_wait_for_server", lambda p: None)
    monkeypatch.setattr(apply, "_can_ask", lambda: True)
    monkeypatch.setattr(setup_code, "read", lambda: code)
    monkeypatch.setattr(apply, "_firewall_note", lambda cfg, on: print("FIREWALL"))
    monkeypatch.setattr(apply, "_show_app", lambda cfg, tty: pytest.fail("the app step ran"))
    monkeypatch.delenv("FK_NO_SYSTEMD")
    if guided_on:
        monkeypatch.setenv("FK_GUIDED", "1")
    apply.finish(_cfg(port), run=lambda cmd: None)
    return capsys.readouterr().out


def test_guided_setup_ends_with_the_address_and_the_code_then_the_firewall(monkeypatch, capsys):
    out = finish_output(monkeypatch, capsys, True)
    assert re.search(r"Open https://[^/\s]+\.local/  \(setup code: 1234-5678\)\nGuided Setup starts there\.", out)
    assert "Spoolman:" not in out and "Pair another phone" not in out
    assert out.index("Guided Setup starts there.") < out.index("FIREWALL")


def test_the_other_path_keeps_its_closing_lines_with_the_address_without_a_port(monkeypatch, capsys):
    monkeypatch.setattr(apply, "_show_app", lambda cfg, tty: True)
    monkeypatch.setattr(apply, "_wait_for_server", lambda p: None)
    monkeypatch.setattr(apply, "_can_ask", lambda: True)
    monkeypatch.setattr(setup_code, "read", lambda: "12345678")
    monkeypatch.setattr(apply, "_firewall_note", lambda cfg, on: None)
    apply.finish(_cfg(443), run=lambda cmd: None)
    out = capsys.readouterr().out
    assert "Spoolman: http://" in out and "Pair another phone: sudo spoolwarden pair" in out
    assert re.search(r"Open https://[^/\s]+\.local/setup  \(setup code: 1234-5678\)", out)
    assert "Guided Setup starts" not in out


def test_guided_setup_asks_no_first_run_question(env, monkeypatch):
    monkeypatch.setenv("FK_GUIDED", "1")
    monkeypatch.setattr(apply, "_can_ask", lambda: True)
    monkeypatch.setattr(apply, "_ask", lambda prompt: pytest.fail(f"asked: {prompt}"))
    monkeypatch.setattr(apply.secret_input, "ask", lambda prompt: pytest.fail("asked for the key"))
    from filament_kit import cli
    monkeypatch.setattr(cli, "cmd_cert", lambda: 0)
    monkeypatch.setattr(setup_code, "ensure", lambda: None)
    (env / "opt" / "resources" / "avahi").mkdir(parents=True)
    (env / "opt" / "resources" / "avahi" / "filament-kit.service").write_text("<port>8710</port>")
    monkeypatch.setattr(apply, "write_hub_dropin", lambda ex, port: None)
    monkeypatch.setattr(apply, "write_avahi", lambda ex, port: None)
    ex = apply._Exec(lambda cmd: None, env / "opt" / "resources", env)
    apply._server_setup(ex, "key")
    assert config.load()["server_name"]


def test_the_terminal_questions_mark_the_first_run_steps(env, monkeypatch):
    firstrun.install_first(["features"])
    answers = iter(["My Hub", "y"])
    monkeypatch.setattr(apply, "_can_ask", lambda: True)
    monkeypatch.setattr(apply, "_ask", lambda prompt: next(answers))
    from filament_kit import cli
    monkeypatch.setattr(cli, "cmd_cert", lambda: 0)
    monkeypatch.setattr(setup_code, "ensure", lambda: None)
    monkeypatch.setattr(apply, "write_hub_dropin", lambda ex, port: None)
    monkeypatch.setattr(apply, "write_avahi", lambda ex, port: None)
    ex = apply._Exec(lambda cmd: None, env / "opt" / "resources", env)
    apply._server_setup(ex, "")
    assert firstrun.load().answered == {"features", "name", "storage"} and config.load()["server_name"] == "My Hub"
