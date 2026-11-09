"""v0.3.0 installer batch (INST): masked secret prompts, `pair` without sudo, the app and pairing QR codes at the end
of an install, apt never reading the terminal, and the piped `curl | sudo bash` form of get.sh."""
import io
import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

from filament_kit import apply, cli, config, modules, pairing, secret_input

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt", "bk"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_BACKUPS", str(tmp_path / "bk"))
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    return tmp_path


def _stdin(monkeypatch, text, tty=False):
    s = io.StringIO(text)
    s.isatty = lambda: tty
    monkeypatch.setattr(sys, "stdin", s)


def _save(on, **extra):
    cfg = config.load()
    cfg["modules"] = {n: n in on for n in modules.MODULES}
    cfg.update(extra)
    config.save(cfg)


# ---------- 5: masked secret input ----------

def _typed(keys: str) -> tuple[str, str]:
    line, echo = secret_input.Line(), ""
    for ch in keys:
        echo += line.key(ch)
        if line.done:
            break
    return line.text, echo


def test_each_character_echoes_a_star_and_enter_ends():
    text, echo = _typed("s3crét\r")
    assert text == "s3crét"
    assert echo == "******\n"


def test_backspace_removes_the_last_character_and_its_star():
    text, echo = _typed("abc\x7f\x7fd\b\x7f\x7fxy\n")
    assert text == "xy"
    assert echo == "***" + "\b \b" * 2 + "*" + "\b \b" * 2 + "**\n"   # the extra Backspace on an empty line: nothing


def test_ctrl_u_clears_and_other_control_keys_are_ignored():
    text, echo = _typed("abc\x15\x01\tz\r")
    assert text == "z" and echo == "***" + "\b \b" * 3 + "*\n"


def test_ctrl_c_interrupts():
    with pytest.raises(KeyboardInterrupt):
        _typed("ab\x03")


def test_without_a_terminal_it_falls_back_to_getpass(monkeypatch):
    _stdin(monkeypatch, "", tty=False)
    asked = []
    monkeypatch.setattr(secret_input.getpass, "getpass", lambda prompt="": asked.append(prompt) or "tok")
    assert secret_input.ask("Token: ") == "tok" and asked == ["Token: "]


def test_a_fake_tty_without_a_file_descriptor_falls_back_to_getpass(monkeypatch):
    _stdin(monkeypatch, "", tty=True)                 # StringIO.fileno() raises
    monkeypatch.setattr(secret_input.getpass, "getpass", lambda prompt="": "tok")
    assert secret_input.ask("Token: ") == "tok"


def test_no_getpass_left_in_the_cli_and_apply():
    for f in ("cli.py", "apply.py"):
        text = (ROOT / "server" / "filament_kit" / f).read_text(encoding="utf-8")
        assert "getpass" not in text, f
        assert "secret_input.ask(" in text, f


def test_access_code_goes_through_the_masked_prompt(monkeypatch, capsys):
    asked = []
    monkeypatch.setattr(secret_input, "ask", lambda prompt: asked.append(prompt) or "ACCESS1234")
    _stdin(monkeypatch, "5\n2\nH2D\n192.0.2.20\n0948ZZ0A0000001\n\n0\n0\n")
    cli.main(["config"])
    assert any("Access Code" in p for p in asked)
    assert "ACCESS1234" not in capsys.readouterr().out


def test_anthropic_key_in_config_goes_through_the_masked_prompt(monkeypatch, capsys):
    asked = []
    monkeypatch.setattr(secret_input, "ask", lambda prompt: asked.append(prompt) or "sk-ant-EXAMPLE")
    _stdin(monkeypatch, "4\n0\n")
    assert cli.main(["config"]) == 0
    assert any("Anthropic" in p for p in asked)
    assert "sk-ant-EXAMPLE" not in capsys.readouterr().out


def test_web_passphrase_asks_twice_through_the_masked_prompt(monkeypatch):
    pytest.importorskip("mcp")  # cmd_web_passphrase imports the web extra
    asked = []
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(cli.shutil, "chown", lambda *a, **k: None)
    monkeypatch.setattr(secret_input, "ask", lambda prompt: asked.append(prompt) or "a long example passphrase")
    assert cli.main(["web", "passphrase"]) == 0
    assert len(asked) == 2


def test_install_key_question_goes_through_the_masked_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "cmd_cert", lambda: 0)
    monkeypatch.setattr(apply, "_tty", lambda: True)
    config.paths().etc.mkdir(parents=True, exist_ok=True)
    _save(modules.MODES["server"], server_name="x")
    asked = []
    monkeypatch.setattr(secret_input, "ask", lambda prompt: asked.append(prompt) or "sk-test")
    res = tmp_path / "res"
    (res / "avahi").mkdir(parents=True)
    (res / "avahi" / "filament-kit.service").write_text("<port>8710</port>", encoding="utf-8")
    apply.execute([apply.Action("server_setup", "key")], run=lambda cmd: None, resources=res, root=tmp_path / "r")
    assert len(asked) == 1 and "Anthropic" in asked[0]


def _pty_ok():
    return sys.platform != "win32" and hasattr(os, "fork")


@pytest.mark.skipif(not _pty_ok(), reason="needs a pty (Linux)")
def test_real_terminal_shows_stars_never_the_secret(tmp_path):
    """In a pty: the screen shows a star per character and the Backspace erase, never the characters."""
    import pty
    result = tmp_path / "result"
    pid, master = pty.fork()
    if pid == 0:
        os.execve(sys.executable, [sys.executable, "-c",
                                   "import sys; from filament_kit import secret_input; "
                                   "s = secret_input.ask('Token: '); "
                                   f"open({str(result)!r}, 'w').write(s)"], dict(os.environ))
    screen = b""
    end = time.time() + 15
    while b"Token: " not in screen and time.time() < end:
        if select.select([master], [], [], 0.2)[0]:
            screen += os.read(master, 4096)
    for k in (b"q", b"w", b"Z", b"\x7f", b"e", b"\x1b[D", b"\r"):  # \x1b[D: the Left key, ignored
        os.write(master, k)
        time.sleep(0.1)
    end = time.time() + 15
    while time.time() < end:
        r = select.select([master], [], [], 0.2)[0]
        if r:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            screen += chunk
    _, status = os.waitpid(pid, 0)
    os.close(master)
    assert os.waitstatus_to_exitcode(status) == 0, screen
    assert result.read_text() == "qwe"
    after = screen.split(b"Token: ", 1)[1]
    assert after.startswith(b"***\b \b*"), after
    assert not re.search(rb"[qwZe]", after), after


@pytest.mark.skipif(not _pty_ok(), reason="needs termios (Linux)")
def test_the_prompt_comes_after_the_terminal_is_set_so_no_key_after_it_is_lost(monkeypatch):
    """Setting the mode throws away what was typed so far (TCSAFLUSH): keys typed once the prompt shows must survive it."""
    import termios
    events = []

    class Out:
        def write(self, text):
            events.append(("write", text))

        def flush(self):
            pass
    monkeypatch.setattr(secret_input, "_out", lambda: Out())
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: [0, 0, 0, 0, 0, 0, [0] * 32])
    monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, attrs: events.append(("set", when)))
    monkeypatch.setattr(secret_input.os, "read", lambda fd, n: b"\r")
    assert secret_input._posix("Token: ", 0) == ""
    assert events.index(("set", termios.TCSAFLUSH)) < events.index(("write", "Token: "))


# ---------- 4: `filament-kit pair` without sudo ----------

def test_pair_with_an_unreadable_certificate_says_use_sudo(monkeypatch, capsys):
    _save(modules.MODES["server"])
    real = Path.read_bytes

    def read_bytes(self):
        if self.name == "cert.pem":
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    assert cli.main(["pair"]) == 1
    err = capsys.readouterr().err
    assert "run it with sudo: sudo filament-kit pair" in err
    assert "create it first" not in err


def test_pair_with_an_unreadable_config_says_use_sudo(monkeypatch, capsys):
    def load():
        raise PermissionError(13, "Permission denied", "/etc/filament-kit/config.json")
    monkeypatch.setattr(config, "load", load)
    assert cli.main(["pair", "--pc"]) == 1
    assert "run it with sudo: sudo filament-kit pair --pc" in capsys.readouterr().err


def test_pair_without_a_certificate_as_a_user_says_use_sudo(monkeypatch, capsys):
    _save(modules.MODES["server"])
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert cli.main(["pair"]) == 1
    assert "run it with sudo: sudo filament-kit pair" in capsys.readouterr().err


def test_pair_without_a_certificate_as_root_says_create_it(monkeypatch, capsys):
    _save(modules.MODES["server"])
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    assert cli.main(["pair"]) == 1
    err = capsys.readouterr().err
    assert "create it first" in err and "with sudo" not in err


def test_pair_text_prints_the_link_not_a_qr_code(monkeypatch, capsys):
    _save(modules.MODES["server"])
    pairing.make_cert("fk-test", ["192.0.2.5"], config.paths().etc)
    monkeypatch.setattr(cli, "_qr_text", lambda payload: pytest.fail("no QR code with --text"))
    assert cli.main(["pair", "--text"]) == 0
    out = capsys.readouterr().out
    assert "fkit://pair?" in out and "Pairing code:" in out


# ---------- 3: the app and pairing QR codes at the end of an install ----------

@pytest.fixture
def finish_env(monkeypatch):
    _save(modules.MODES["server"])
    monkeypatch.setattr(apply, "_https_local_ok", lambda url: True)
    monkeypatch.setattr(apply.pairing, "local_ips", lambda: ["192.0.2.5"])
    monkeypatch.setattr(apply.pairing, "short_hostname", lambda: "kit")
    monkeypatch.setattr(cli, "_qr_text", lambda payload: f"[QR {payload}]")
    calls = []

    def run(cmd):
        calls.append(list(cmd))
        print("$ " + " ".join(cmd))
    monkeypatch.delenv("FK_NO_SYSTEMD")
    return calls, run


def _apk():
    f = config.paths().opt / "app" / "filament-kit.apk"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"PK\x03\x04 example")


def test_finish_shows_the_app_qr_then_waits_then_pairs(finish_env, monkeypatch, capsys):
    calls, run = finish_env
    _apk()
    _stdin(monkeypatch, "\n", tty=True)
    apply.finish(config.load(), run=run)
    out = capsys.readouterr().out
    url = "https://192.0.2.5:8710/app.apk"
    assert f"[QR {url}]" in out
    i_app, i_wait = out.index(f"[QR {url}]"), out.index("Press Enter when the app is installed")
    i_pair = out.index("$ /usr/local/bin/filament-kit pair")
    assert i_app < i_wait < i_pair
    assert "Android app" in out[:i_app]
    assert "or s to skip" in out
    assert [c for c in calls if c[-1] == "pair" or "pair" in c] == [[apply.WRAPPER, "pair"]]


def test_finish_s_skips_the_pairing_code(finish_env, monkeypatch, capsys):
    calls, run = finish_env
    _apk()
    _stdin(monkeypatch, "s\n", tty=True)
    apply.finish(config.load(), run=run)
    out = capsys.readouterr().out
    assert not any("pair" in c for c in calls)
    assert "sudo filament-kit pair" in out


def test_finish_without_a_terminal_prints_the_app_link_and_no_pairing_token(finish_env, monkeypatch, capsys):
    """No terminal (the updater, a provisioning script): the output ends up in a log, so the app link is printed but
    no pairing link or code is issued; nothing waits."""
    calls, run = finish_env
    _apk()
    _stdin(monkeypatch, "", tty=False)
    apply.finish(config.load(), run=run)
    out = capsys.readouterr().out
    assert "https://192.0.2.5:8710/app.apk" in out and "[QR " not in out
    assert "Press Enter" not in out
    assert not [c for c in calls if c[:2] == [apply.WRAPPER, "pair"]]
    assert "sudo filament-kit pair" in out and "fkit://" not in out


def test_finish_without_an_apk_goes_straight_to_pairing(finish_env, monkeypatch, capsys):
    calls, run = finish_env
    _stdin(monkeypatch, "", tty=True)
    apply.finish(config.load(), run=run)
    out = capsys.readouterr().out
    assert "app.apk" not in out and "Press Enter" not in out
    assert [apply.WRAPPER, "pair"] in calls


def test_app_url_falls_back_to_the_local_name_without_an_address(monkeypatch):
    monkeypatch.setattr(apply.pairing, "local_ips", lambda: [])
    monkeypatch.setattr(apply.pairing, "short_hostname", lambda: "kit")
    assert apply.app_url({"port": 8710}) == "https://kit.local:8710/app.apk"


def test_finish_without_pairing_shows_no_app_qr(finish_env, monkeypatch, capsys):
    calls, run = finish_env
    _apk()
    _stdin(monkeypatch, "", tty=True)
    apply.finish(config.load(), run=run, pairing=False)
    assert "app.apk" not in capsys.readouterr().out


# ---------- 1: apt never reads the terminal ----------

def test_apply_runs_apt_with_stdin_from_dev_null(monkeypatch):
    seen = []
    monkeypatch.setattr(apply.subprocess, "run", lambda cmd, **kw: seen.append((cmd[0], kw.get("stdin"))))
    apply.run_checked([*apply.APT, "install", "-y", "qrencode"])
    apply.run_checked(["systemctl", "daemon-reload"])
    assert seen == [("apt-get", subprocess.DEVNULL), ("systemctl", None)]


def test_install_sh_apt_lines_read_dev_null():
    lines = [ln.strip() for ln in (ROOT / "install" / "install.sh").read_text(encoding="utf-8").splitlines()
             if ln.strip().startswith("apt-get")]
    assert lines and all(ln.endswith("</dev/null") for ln in lines), lines


def test_get_sh_makes_the_installer_the_foreground_job():
    text = (ROOT / "get.sh").read_text(encoding="utf-8")
    assert "tcsetpgrp" in text
    # both forms are documented
    head = text.split("set -euo pipefail", 1)[0]
    assert "| sudo bash" in head and "sudo bash get.sh" in head
