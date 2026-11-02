"""Apply executor (spec section 4): actions -> commands, run through a fake `run`, files under tmp_path."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from filament_kit import apply, cli, config, modules
from filament_kit.apply import Action

INSTALL = Path(__file__).resolve().parents[2] / "install"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc-fk"))
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    monkeypatch.setattr(apply.time, "sleep", lambda s: None)
    return tmp_path


class Recorder:
    """Fake `run`: records commands; a command whose text contains a key of `fail` raises."""

    def __init__(self, fail=(), fail_at=None):
        self.calls: list[list[str]] = []
        self.fail = tuple(fail)
        self.fail_at = fail_at

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        text = " ".join(cmd)
        if len(self.calls) == self.fail_at or any(f in text for f in self.fail):
            raise subprocess.CalledProcessError(1, cmd)

    def texts(self):
        return [" ".join(c) for c in self.calls]


def _res(tmp_path):
    res = tmp_path / "res"
    (res / "systemd").mkdir(parents=True)
    (res / "avahi").mkdir()
    for u in ("filament-kit.service", "filament-kit-backup.timer", "filament-kit-station.service"):
        (res / "systemd" / u).write_text(f"[Unit]\nDescription={u}\n", encoding="utf-8")
    (res / "avahi" / "filament-kit.service").write_text("<port>8710</port>\n", encoding="utf-8")
    return res


def test_execute_runs_in_order_and_stops_on_failure(tmp_path, capsys):
    run = Recorder(fail_at=3)
    acts = [Action("daemon_reload"), Action("enable", "a.service"), Action("enable", "b.timer")]
    with pytest.raises(apply.ApplyError):
        apply.execute(acts, run=run, resources=_res(tmp_path), root=tmp_path / "root")
    assert run.texts() == ["systemctl daemon-reload", "systemctl enable a.service", "systemctl restart a.service"]
    out = capsys.readouterr().out
    assert "FAIL enable a.service" in out
    assert "fix:" in out


def test_install_file_writes_with_mode(tmp_path, monkeypatch):
    modes = {}
    real_chmod = os.chmod
    monkeypatch.setattr(apply.os, "chmod", lambda p, m: (modes.__setitem__(str(p), m), real_chmod(p, m)))
    run = Recorder()
    root = tmp_path / "root"
    apply.execute([Action("install_file", (apply.DROPIN, "[Service]\nX=1\n", "0644", "root:root"))],
                  run=run, resources=_res(tmp_path), root=root)
    dest = root / apply.DROPIN.lstrip("/")
    assert dest.read_text(encoding="utf-8") == "[Service]\nX=1\n"
    assert modes[str(dest)] == 0o644
    if os.name != "nt":
        assert dest.stat().st_mode & 0o777 == 0o644
    assert ["chown", "root:root", str(dest)] in run.calls


def test_no_systemd_prints_instead_of_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    run = Recorder()
    acts = [Action("apt", "unzip"), Action("enable", "x.service"), Action("udev_reload"),
            Action("wait_http", apply.SPOOLMAN_INFO)]
    apply.execute(acts, run=run, resources=_res(tmp_path), root=tmp_path / "root")
    assert run.calls == []
    out = capsys.readouterr().out
    assert "apt-get -o DPkg::Lock::Timeout=300 install -y -q unzip" in out
    assert "systemctl enable x.service" in out
    assert "udevadm control --reload" in out


def test_apt_batched_once(tmp_path):
    run = Recorder()
    apply.execute([Action("apt", "unzip"), Action("apt", "ffmpeg"), Action("daemon_reload")],
                  run=run, resources=_res(tmp_path), root=tmp_path)
    assert run.texts() == ["apt-get -o DPkg::Lock::Timeout=300 install -y -q unzip ffmpeg", "systemctl daemon-reload"]


def test_enable_kinds(tmp_path):
    run = Recorder()
    apply.execute([Action("enable", "a.timer"), Action("enable", "b.path")],
                  run=run, resources=_res(tmp_path), root=tmp_path)
    assert run.texts() == ["systemctl enable a.timer", "systemctl start a.timer",
                           "systemctl enable b.path", "systemctl restart b.path"]


def test_disable_missing_unit_runs_nothing(tmp_path):
    # final review: systemd prints "Failed to disable unit ... does not exist" on every server-mode apply
    run = Recorder()
    apply.execute([Action("disable", "gone.service"), Action("daemon_reload")],
                  run=run, resources=_res(tmp_path), root=tmp_path)
    assert run.texts() == ["systemctl daemon-reload"]


def test_disable_present_unit_runs_and_failure_is_harmless(tmp_path):
    unit = tmp_path / "etc/systemd/system/old.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("[Unit]\n", encoding="utf-8")
    run = Recorder(fail=("disable",))
    apply.execute([Action("disable", "old.service"), Action("daemon_reload")],
                  run=run, resources=_res(tmp_path), root=tmp_path)
    assert run.texts() == ["systemctl disable --now old.service", "systemctl daemon-reload"]


def test_user_created_only_when_missing(tmp_path):
    run = Recorder(fail=("id -u filament-kit-station",))
    apply.execute([Action("user", "spoolman"), Action("user", ("filament-kit-station", "dialout,audio"))],
                  run=run, resources=_res(tmp_path), root=tmp_path)
    assert run.texts() == [
        "id -u spoolman",
        "id -u filament-kit-station",
        "useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin"
        " --groups dialout,audio filament-kit-station"]


def test_probed_station_actions(tmp_path):
    # brltty not installed, ModemManager enabled
    run = Recorder(fail=("dpkg -s brltty",))
    apply.execute([Action("remove_pkg", "brltty"), Action("disable_ext", "ModemManager"), Action("mask_sleep")],
                  run=run, resources=_res(tmp_path), root=tmp_path)
    assert run.texts() == [
        "dpkg -s brltty",
        "systemctl is-enabled ModemManager",
        "systemctl disable --now ModemManager",
        "systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target"]


def test_alsa_unmute_ignores_failures(tmp_path):
    root = tmp_path / "root"
    (root / "proc" / "asound").mkdir(parents=True)
    (root / "proc" / "asound" / "cards").write_text(
        " 0 [PCH            ]: HDA-Intel - HDA Intel PCH\n                      HDA Intel PCH at 0xf\n"
        " 1 [Device         ]: USB-Audio - USB Audio Device\n", encoding="utf-8")
    run = Recorder(fail=("amixer",))
    apply.execute([Action("alsa_unmute")], run=run, resources=_res(tmp_path), root=root)
    texts = run.texts()
    assert "amixer -q -c 0 sset Master 80% unmute" in texts
    assert "amixer -q -c 1 sset PCM 80% unmute" in texts
    assert len([t for t in texts if t.startswith("amixer")]) == 8
    assert texts[-1] == "alsactl store"


def test_install_unit_copies_resource(tmp_path):
    root = tmp_path / "root"
    apply.execute([Action("install_unit", "filament-kit-backup.timer")],
                  run=Recorder(), resources=_res(tmp_path), root=root)
    dest = root / "etc/systemd/system/filament-kit-backup.timer"
    assert dest.read_text(encoding="utf-8") == "[Unit]\nDescription=filament-kit-backup.timer\n"


def test_spoolman_fetch_runs_script(tmp_path):
    run = Recorder()
    res = _res(tmp_path)
    apply.execute([Action("spoolman_fetch")], run=run, resources=res, root=tmp_path)
    assert run.calls == [["bash", str(res / "spoolman.sh")]]


def test_wait_http_gives_up_with_fix(tmp_path, monkeypatch, capsys):
    tries = []
    monkeypatch.setattr(apply, "_http_ok", lambda url: tries.append(url) or False)
    with pytest.raises(apply.ApplyError):
        apply.execute([Action("wait_http", apply.SPOOLMAN_INFO)], run=Recorder(),
                      resources=_res(tmp_path), root=tmp_path)
    assert len(tries) == 90
    out = capsys.readouterr().out
    assert "FAIL" in out and "journalctl -u spoolman" in out


def test_first_build_never_fatal(tmp_path):
    run = Recorder(fail=("profiles build",))
    apply.execute([Action("first_build"), Action("daemon_reload")],
                  run=run, resources=_res(tmp_path), root=tmp_path)
    assert run.texts() == ["/usr/local/bin/filament-kit profiles build", "systemctl daemon-reload"]


def test_ensure_fields_through_wrapper(tmp_path):
    run = Recorder()
    apply.execute([Action("ensure_fields")], run=run, resources=_res(tmp_path), root=tmp_path)
    assert run.texts() == ["/usr/local/bin/filament-kit ensure-fields"]


def test_server_setup_no_tty_writes_avahi_and_cert(tmp_path, monkeypatch):
    certs = []
    monkeypatch.setattr(cli, "cmd_cert", lambda: certs.append(1) or 0)
    monkeypatch.setattr(apply, "_tty", lambda: False)
    config.paths().etc.mkdir(parents=True)
    (config.paths().etc / "config.json").write_text(json.dumps({"port": 9000}), encoding="utf-8")
    root = tmp_path / "root"
    run = Recorder()
    apply.execute([Action("server_setup", "key")], run=run, resources=_res(tmp_path), root=root)
    assert certs == [1]
    avahi = root / "etc/avahi/services/filament-kit.service"
    assert avahi.read_text(encoding="utf-8") == "<port>9000</port>\n"
    texts = run.texts()
    assert "systemctl enable --now avahi-daemon" in texts
    assert "systemctl reload avahi-daemon" in texts
    # no TTY: nothing asked; the default name is saved so a later TTY apply asks no first-run questions
    raw = json.loads((config.paths().etc / "config.json").read_text(encoding="utf-8"))
    assert raw["server_name"] == apply.socket.gethostname()
    assert raw["port"] == 9000
    assert not (config.paths().etc / "anthropic_key").exists()


def test_server_setup_first_run_questions_on_tty(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "cmd_cert", lambda: 0)
    monkeypatch.setattr(apply, "_tty", lambda: True)
    answers = iter(["Workshop\n", "y\n"])
    monkeypatch.setattr(apply.sys, "stdin", type("S", (), {"readline": lambda self: next(answers)})())
    keys = []
    monkeypatch.setattr(apply.getpass, "getpass", lambda prompt: keys.append(prompt) or "")
    apply.execute([Action("server_setup", "")], run=Recorder(), resources=_res(tmp_path), root=tmp_path / "r")
    raw = json.loads((config.paths().etc / "config.json").read_text(encoding="utf-8"))
    assert raw["server_name"] == "Workshop"
    assert keys == []  # arg "" (ai_intake off): never asks for the key


def test_server_setup_key_question_only_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "cmd_cert", lambda: 0)
    monkeypatch.setattr(apply, "_tty", lambda: True)
    config.paths().etc.mkdir(parents=True)
    (config.paths().etc / "config.json").write_text(json.dumps({"server_name": "x"}), encoding="utf-8")
    monkeypatch.setattr(apply.getpass, "getpass", lambda prompt: "sk-test")
    res = _res(tmp_path)
    apply.execute([Action("server_setup", "key")], run=Recorder(), resources=res, root=tmp_path / "r")
    assert (config.paths().etc / "anthropic_key").read_text(encoding="utf-8").strip() == "sk-test"
    asked = []
    monkeypatch.setattr(apply.getpass, "getpass", lambda prompt: asked.append(1) or "other")
    apply.execute([Action("server_setup", "key")], run=Recorder(), resources=res, root=tmp_path / "r")
    assert asked == []


def test_station_off_notice_once(tmp_path, capsys):
    root = tmp_path / "root"
    rule = root / apply.UDEV_RULE.lstrip("/")
    rule.parent.mkdir(parents=True)
    rule.write_text("x", encoding="utf-8")
    acts = [Action("disable", apply.STATION_UNIT), Action("daemon_reload")]
    apply.execute(acts, run=Recorder(), resources=_res(tmp_path), root=root)
    out = capsys.readouterr().out
    assert out.count("left as they are") == 1
    assert "brltty" in out and "ModemManager" in out


def test_no_station_notice_without_rule(tmp_path, capsys):
    apply.execute([Action("disable", apply.STATION_UNIT)], run=Recorder(),
                  resources=_res(tmp_path), root=tmp_path / "root")
    assert "left as they are" not in capsys.readouterr().out


def test_full_plan_runs_with_fakes(tmp_path, monkeypatch):
    """Every action kind the planner emits has an executor branch; the real install/ files are the resources."""
    monkeypatch.setattr(cli, "cmd_cert", lambda: 0)
    monkeypatch.setattr(apply, "_tty", lambda: False)
    monkeypatch.setattr(apply, "_http_ok", lambda url: True)
    cfg = modules.set_mode(config.load(), "all-in-one")
    acts = apply.plan(cfg, resolve=lambda h: [h])
    run = Recorder()
    root = tmp_path / "root"
    apply.execute(acts, run=run, resources=INSTALL, root=root)
    texts = run.texts()
    for unit in ("filament-kit-station.service", "filament-kit-build.service", "spoolman.service"):
        if unit != "spoolman.service":  # spoolman.sh installs its own unit
            assert (root / "etc/systemd/system" / unit).exists(), unit
    assert texts.index("systemctl daemon-reload") < texts.index("systemctl enable spoolman.service")
    assert "systemctl enable filament-kit-station.service" in texts


def test_cli_modules_units(capsys):
    assert cli.main(["modules", "units"]) == 0
    units = capsys.readouterr().out.split()
    assert units[0] == "spoolman.service"
    for u in ("filament-kit.service", "filament-kit-build.path", "filament-kit-build.service",
              "filament-kit-library.timer", "filament-kit-library.service", "filament-kit-backup.timer",
              "filament-kit-backup.service", "filament-kit-station.service"):
        assert u in units
    assert len(units) == len(set(units)) == 9


def test_cli_modules_apply_dry(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setattr(cli, "cmd_cert", lambda: 0)
    monkeypatch.setattr(apply, "_tty", lambda: False)
    calls = []
    monkeypatch.setattr(apply, "execute", lambda acts, **kw: calls.append(acts))
    monkeypatch.setattr(apply, "finish", lambda cfg, **kw: None)
    assert cli.main(["modules", "apply"]) == 0
    assert calls and calls[0][-1].kind == "first_build"


def test_cli_modules_apply_invalid_config(monkeypatch, capsys):
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    config.paths().etc.mkdir(parents=True)
    (config.paths().etc / "config.json").write_text(
        json.dumps({"modules": {"server": True, "spoolman": False}}), encoding="utf-8")
    assert cli.main(["modules", "apply"]) == 1
    assert "error:" in capsys.readouterr().err


def test_prints_reach_the_output_before_each_command(tmp_path, monkeypatch):
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)  # a dry run would print instead of calling run
    # Piped to a file (install.sh > log) stdout is block-buffered; the "==>" lines must still come
    # before the output of the command they announce.
    class Buffered:
        def __init__(self):
            self.pending, self.flushed = "", ""

        def write(self, s):
            self.pending += s
            return len(s)

        def flush(self):
            self.flushed += self.pending
            self.pending = ""

    out = Buffered()
    monkeypatch.setattr(apply.sys, "stdout", out)
    seen = []
    apply.execute([Action("first_build")], run=lambda cmd: seen.append(out.flushed),
                  resources=_res(tmp_path), root=tmp_path)
    assert "==> Building presets" in seen[0]
