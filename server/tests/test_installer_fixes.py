"""v0.3.0 installer fixes: pairing on a station, `modules enable web` asking for its address, the passphrase line of
`web status`, quiet probes during an apply, and `filament-kit uninstall`."""
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from filament_kit import apply, cli, config, modules, release, updates
from filament_kit.apply import Action

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


# ---------- B2: pair on a station-only install ----------

@pytest.mark.parametrize("args", [["pair"], ["pair", "--pc"]])
def test_pair_on_a_station_says_pairing_runs_on_the_server(capsys, args):
    _save({"station"}, station={"allow": ["kit.example.lan"], "url": None})
    assert cli.main(args) == 1
    err = capsys.readouterr().err
    assert "no server certificate" not in err
    assert "pairing runs on the kit server" in err and "kit.example.lan" in err
    assert f"sudo filament-kit {' '.join(args)}" in err


def test_pair_on_a_station_without_a_known_server(capsys):
    _save({"station"}, station={"allow": ["127.0.0.1"], "url": None})
    assert cli.main(["pair"]) == 1
    err = capsys.readouterr().err
    assert "pairing runs on the kit server" in err and "station.allow" in err


# ---------- B3: modules enable web asks for web.public_url at a terminal ----------

@pytest.fixture
def applied(monkeypatch):
    calls = []
    monkeypatch.setattr(apply, "plan", lambda cfg, **kw: calls.append(cfg) or [])
    monkeypatch.setattr(apply, "execute", lambda actions, **kw: None)
    monkeypatch.setattr(apply, "finish", lambda cfg, **kw: None)
    return calls


def test_enable_web_asks_for_the_public_url_at_a_terminal(applied, monkeypatch, capsys):
    _save(modules.MODES["server"])
    _stdin(monkeypatch, "http://nope\nhttps://kit.example.com/filament\n", tty=True)
    assert cli.main(["modules", "enable", "web"]) == 0
    out = capsys.readouterr().out
    assert "web needs its public https address" in out and "Give the https address" in out
    cfg = config.load()
    assert cfg["modules"]["web"] is True and cfg["web"]["public_url"] == "https://kit.example.com/filament"


def test_enable_web_blank_answer_changes_nothing(applied, monkeypatch, capsys):
    _save(modules.MODES["server"])
    _stdin(monkeypatch, "\n", tty=True)
    assert cli.main(["modules", "enable", "web"]) == 1
    assert "left blank" in capsys.readouterr().err
    assert config.load()["modules"]["web"] is False and applied == []


def test_enable_web_without_a_terminal_keeps_the_error(applied, monkeypatch, capsys):
    _save(modules.MODES["server"])
    _stdin(monkeypatch, "https://kit.example.com/filament\n", tty=False)
    assert cli.main(["modules", "enable", "web"]) == 1
    assert "web needs web.public_url" in capsys.readouterr().err
    assert config.load()["modules"]["web"] is False


def test_enable_orders_asks_for_its_file(applied, monkeypatch):
    _save(modules.MODES["server"] | {"ai_intake"})
    _stdin(monkeypatch, "/srv/orders.json\n", tty=True)
    assert cli.main(["modules", "enable", "orders"]) == 0
    assert config.load()["orders"]["file"] == "/srv/orders.json"


def test_enable_with_a_missing_dependency_refused_at_the_prompt_asks_no_address(applied, monkeypatch, capsys):
    _save({"spoolman"})
    _stdin(monkeypatch, "", tty=True)
    assert cli.main(["modules", "enable", "remote"]) == 1
    cap = capsys.readouterr()
    assert "remote needs server, web" in cap.err and "public https address" not in cap.out


# ---------- B4: web status and the passphrase ----------

def test_web_status_without_passphrase_is_not_a_failure(monkeypatch, capsys):
    _save(modules.MODES["server"] | {"web"}, web={"public_url": "https://kit.example.com/filament",
                                                  "lan": ["192.168.1.0/24"]})
    monkeypatch.setattr(cli, "_web_health", lambda port: (True, "ok"))
    assert cli.main(["web", "status"]) == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out
    line = next(ln for ln in out.splitlines() if "passphrase" in ln)
    assert line.startswith("--") and "Claude connector" in line
    assert "sudo filament-kit web passphrase" in out


# ---------- B5: quiet probes and the Spoolman fields line ----------

def test_probes_print_nothing(tmp_path, monkeypatch):
    """`id -u spoolman` printed `id: 'spoolman': no such user` on a first install and the uid (`997`) later."""
    seen = []

    def fake_run(cmd, **kw):
        seen.append((list(cmd), kw.get("stdout"), kw.get("stderr")))
        if cmd[:2] == ["id", "-u"]:
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(apply.subprocess, "run", fake_run)
    monkeypatch.delenv("FK_NO_SYSTEMD")
    apply.execute([Action("user", "spoolman")], resources=tmp_path, root=tmp_path)
    probe = next(s for s in seen if s[0][:2] == ["id", "-u"])
    assert probe[1] is subprocess.DEVNULL and probe[2] is subprocess.DEVNULL
    useradd = next(s for s in seen if s[0][0] == "useradd")
    assert useradd[1] is None                       # real commands keep their output


def test_ensure_fields_says_what_it_checked(capsys, spoolman_url):
    cfg = config.load()
    cfg["spoolman_url"] = spoolman_url
    config.save(cfg)
    assert cli.main(["ensure-fields"]) == 0
    assert cli.main(["ensure-fields"]) == 0
    out = capsys.readouterr().out
    assert "fields already present" not in out
    assert "Spoolman: added the kit's extra fields" in out and "Spoolman: the kit's extra fields are in place" in out


# ---------- B6: filament-kit uninstall ----------

def _kept(tmp_path, version, *, body="echo uninstall \"$@\"\n"):
    d = updates.store() / version
    d.mkdir(parents=True)
    (d / release.tarball_name(version)).write_bytes(b"x")
    return body


@pytest.fixture
def fake_release(monkeypatch, tmp_path):
    """verify_dir accepts any folder holding the tarball; extract writes an uninstall.sh."""
    def verify(folder, version, pubkey_b64=None):
        t = Path(folder) / release.tarball_name(version)
        if not t.is_file():
            raise release.ReleaseError(f"{t} is missing")
        return t

    def extract(tarball, version, dest):
        root = Path(dest) / f"filament-kit-{version}"
        root.mkdir(parents=True)
        (root / "install.sh").write_text("")
        (root / "uninstall.sh").write_text(f"# {version}\n")
        return root
    monkeypatch.setattr(release, "verify_dir", verify)
    monkeypatch.setattr(release, "extract", extract)
    monkeypatch.setattr(updates, "current_version", lambda: "1.2.0")


def test_uninstall_runs_the_kept_releases_uninstall_sh(tmp_path, fake_release):
    _kept(tmp_path, "1.2.0")
    _kept(tmp_path, "1.1.0")
    ran = []
    assert cli.cmd_uninstall(purge=True, run=lambda cmd: ran.append(
        (cmd, Path(cmd[1]).read_text())) or 0) == 0
    (cmd, text), = ran
    assert cmd[0] == "bash" and Path(cmd[1]).name == "uninstall.sh" and cmd[2:] == ["--purge"]
    assert text == "# 1.2.0\n"                       # the running version's copy
    assert not Path(cmd[1]).exists()                 # its temporary folder is gone again
    assert str(updates.store()) not in cmd[1]        # run from outside /opt, which it removes


def test_uninstall_falls_back_to_the_newest_kept_release_and_says_so(tmp_path, fake_release, capsys):
    _kept(tmp_path, "1.0.0")
    _kept(tmp_path, "1.1.0")
    ran = []
    assert cli.cmd_uninstall(purge=False, run=lambda cmd: ran.append(Path(cmd[1]).read_text()) or 3) == 3
    assert ran == ["# 1.1.0\n"]
    out = capsys.readouterr().out
    assert "no kept copy of 1.2.0" in out and "uninstall.sh of 1.1.0" in out


def test_uninstall_with_the_running_versions_copy_says_nothing_extra(tmp_path, fake_release, capsys):
    _kept(tmp_path, "1.2.0")
    assert cli.cmd_uninstall(purge=False, run=lambda cmd: 0) == 0
    assert capsys.readouterr().out == ""


def test_uninstall_without_a_kept_release_says_how_to_get_one(tmp_path, fake_release, capsys):
    assert cli.cmd_uninstall(purge=False, run=lambda cmd: 0) == 1
    err = capsys.readouterr().err
    assert "no kept copy" in err and "filament-kit-1.2.0.tar.gz" in err and "./uninstall.sh" in err


def _verify_fails_for(monkeypatch, *versions):
    real = release.verify_dir

    def verify(folder, version, pubkey_b64=None):
        if version in versions:
            raise release.ReleaseError(f"{version}: the signature does not match")
        return real(folder, version, pubkey_b64)
    monkeypatch.setattr(release, "verify_dir", verify)


def test_uninstall_skips_a_kept_copy_that_does_not_verify_and_uses_the_next(tmp_path, fake_release, monkeypatch, capsys):
    _kept(tmp_path, "1.2.0")
    _kept(tmp_path, "1.1.0")
    _kept(tmp_path, "1.0.0")
    _verify_fails_for(monkeypatch, "1.2.0")                   # the running version's copy was tampered with
    ran = []
    assert cli.cmd_uninstall(purge=False, run=lambda cmd: ran.append(Path(cmd[1]).read_text()) or 0) == 0
    assert ran == ["# 1.1.0\n"]                              # never the tampered one, not the older one either
    assert "uninstall.sh of 1.1.0" in capsys.readouterr().out


def test_uninstall_runs_nothing_when_no_kept_copy_verifies(tmp_path, fake_release, monkeypatch, capsys):
    _kept(tmp_path, "1.2.0")
    _kept(tmp_path, "1.1.0")
    _verify_fails_for(monkeypatch, "1.2.0", "1.1.0")
    assert cli.cmd_uninstall(purge=True, run=lambda cmd: pytest.fail("ran an unverified uninstall.sh")) == 1
    assert "no kept copy" in capsys.readouterr().err


def test_uninstall_refuses_when_not_root(tmp_path, fake_release, monkeypatch, capsys):
    _kept(tmp_path, "1.2.0")
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert cli.cmd_uninstall(purge=False, run=lambda cmd: pytest.fail("ran uninstall.sh as a normal user")) == 1
    assert "run as root" in capsys.readouterr().err


def test_uninstall_is_a_cli_command_run_as_root():
    wrapper = (ROOT / "install" / "filament-kit-cli.sh").read_text(encoding="utf-8")
    assert "| update | uninstall | station | setup-code)" in wrapper
    with pytest.raises(SystemExit):
        cli.main(["uninstall", "--bogus"])


def test_uninstall_sh_keeps_its_purge_confirmation():
    text = (ROOT / "install" / "uninstall.sh").read_text(encoding="utf-8")
    assert "Type 'purge' to confirm: " in text


def test_install_sh_removes_the_040_setup_apply_unit(tmp_path):
    """0.4.0's filament-kit-setup-apply.service has no apply-run behind it any more: an upgrade deletes the file."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("needs bash")
    text = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
    start = text.index("OLD_APPLY_UNIT=")
    block = text[start:text.index("\nfi\n", start) + 4]
    assert "daemon-reload" in block
    unit = tmp_path / "filament-kit-setup-apply.service"
    other = tmp_path / "filament-kit-web.service"
    unit.write_text("[Service]\n")
    other.write_text("[Service]\n")
    for _ in range(2):      # the second run: nothing there, nothing fails
        done = subprocess.run([bash, "-c", "set -eu\n" + block], env={**os.environ, "FK_SYSTEMD_DIR": str(tmp_path),
                                                                      "FK_NO_SYSTEMD": "1"}, capture_output=True)
        assert done.returncode == 0, done.stderr
        assert not unit.exists() and other.exists()


def test_passphrase_docstrings_name_only_the_claude_connector():
    """The phone web app has no sign-in: the passphrase only approves Claude's connector on /login."""
    pytest.importorskip("mcp")  # the web extra
    from filament_kit.web import auth
    if cli.cmd_web_passphrase.__doc__ is None:
        pytest.skip("docstrings are stripped (python -OO)")
    doc = " ".join(cli.cmd_web_passphrase.__doc__.split())
    assert "and the phone app" not in doc and "has no sign-in" in doc and "connector" in doc
    first = auth.__doc__.splitlines()[0]
    assert "cookie sessions" not in first
