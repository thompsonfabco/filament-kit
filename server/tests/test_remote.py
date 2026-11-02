"""Remote module (spec 4.4): plan, executor, issue command; the kit never changes a firewall."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from filament_kit import apply, cli, config, modules, remote
from filament_kit.apply import Action
from filament_kit.modules import ModuleError

INSTALL = Path(__file__).resolve().parents[2] / "install"
FORBIDDEN = re.compile(r"\b(nft|nftables|ufw|iptables|ip6tables|pfsense|firewall-cmd)\b", re.I)


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc-fk"))
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(list(cmd))

    def texts(self):
        return [" ".join(c) for c in self.calls]


def _cfg(url="https://fk.example.org/filament", **remote_over):
    cfg = modules.set_mode(config.load(), "all-in-one")
    cfg["modules"]["web"] = True
    cfg["modules"]["remote"] = True
    cfg["web"] = {**cfg["web"], "public_url": url}
    cfg["remote"] = {**cfg["remote"], **remote_over}
    return cfg


def _plan(cfg):
    return apply.plan(cfg, resolve=lambda h: [h])


def _of(acts, kind):
    return [a.arg for a in acts if a.kind == kind]


def test_plan_remote_actions():
    acts = _plan(_cfg())
    assert {"nginx", "certbot"} <= set(_of(acts, "apt"))
    assert _of(acts, "remote_install") == ["fk.example.org"]
    assert _of(acts, "remote_route") == [("filament", 8101)]
    assert _of(acts, "remote_print")
    kinds = [a.kind for a in acts]
    # files before the reload, nginx running before the route is added, the rules printed last
    assert kinds.index("remote_install") < kinds.index("daemon_reload") < kinds.index("remote_route")
    assert kinds.index("remote_route") < kinds.index("remote_print")
    assert "nginx.service" in _of(acts, "enable")
    assert not _of(acts, "remote_off")


def test_route_name_from_public_url_path_and_default():
    assert _of(_plan(_cfg("https://fk.example.org/mykit")), "remote_route") == [("mykit", 8101)]
    assert _of(_plan(_cfg("https://fk.example.org")), "remote_route") == [("filament", 8101)]
    cfg = _cfg()
    cfg["web"]["port"] = 9300
    assert _of(_plan(cfg), "remote_route") == [("filament", 9300)]


def test_hostname_setting_wins_and_window_adds_timer_dropin():
    cfg = _cfg(hostname="Kit.Example.org", acme_window="03:10 America/New_York")
    acts = _plan(cfg)
    assert _of(acts, "remote_install") == ["kit.example.org"]
    (dest, text, mode, owner), = [a.arg for a in acts if a.kind == "install_file" and "certbot.timer.d" in a.arg[0]]
    assert "OnCalendar=*-*-* 03:10:00 America/New_York" in text
    assert "certbot.timer" in _of(acts, "enable")


@pytest.mark.parametrize("over", [{"acme_window": "soon"}, {"acme_window": "25:99"}, {"hostname": "bad host;rm"},
                                  {"email": "not-an-email"}])
def test_bad_settings_stop_the_plan(over):
    with pytest.raises(ModuleError):
        _plan(_cfg(**over))


def test_bad_route_name_stops_the_plan():
    with pytest.raises(ModuleError):
        _plan(_cfg("https://fk.example.org/Bad_Name"))


def test_remote_off_removes_only_the_route():
    cfg = _cfg()
    cfg["modules"]["remote"] = False
    acts = _plan(cfg)
    assert _of(acts, "remote_off") == ["filament"]
    assert not {"remote_install", "remote_route", "remote_print"} & {a.kind for a in acts}
    assert not any(a.kind == "remove_pkg" and a.arg in ("nginx", "certbot") for a in acts)


def test_never_configured_remote_is_not_mentioned():
    assert not _of(apply.plan({}), "remote_off")  # a legacy config has no `modules` key at all


def test_execute_installs_router_files(tmp_path):
    run, root = Rec(), tmp_path / "root"
    acts = [a for a in _plan(_cfg(acme_window="03:10")) if a.kind.startswith("remote") or a.kind == "install_file"]
    apply.execute(acts, run=run, resources=INSTALL, root=root)
    conf = (root / "etc/nginx/conf.d/filament-kit-router.conf").read_text()
    assert "server_name fk.example.org;" in conf and "@" not in conf
    assert (root / "etc/mcp-router/host").read_text().strip() == "fk.example.org"
    assert (root / "etc/mcp-router/route.template").exists()
    assert (root / "etc/nginx/mcp-proxy.conf").exists()
    if os.name != "nt":  # Windows has no exec bit
        assert (root / "usr/local/sbin/mcp-route").stat().st_mode & 0o100
    assert (root / "usr/local/sbin/filament-kit-acme-hook").exists()
    texts = run.texts()
    assert any(t.startswith("openssl req -x509") and "fk.example.org" in t for t in texts)  # placeholder cert
    assert "/usr/local/sbin/mcp-route add filament 8101" in texts
    assert "nginx -t" in texts


def test_placeholder_cert_never_replaces_a_real_one(tmp_path):
    run, root = Rec(), tmp_path / "root"
    tls = root / "etc/mcp-router/tls"
    tls.mkdir(parents=True)
    (tls / "fullchain.pem").write_text("REAL")
    apply.execute([Action("remote_install", "fk.example.org")], run=run, resources=INSTALL, root=root)
    assert (tls / "fullchain.pem").read_text() == "REAL"
    assert not any(t.startswith("openssl") for t in run.texts())


def test_remote_print_names_ports_window_and_sandbox(tmp_path, capsys):
    cfg = _cfg(acme_window="03:10 America/New_York")
    cfg["web"]["lan"] = ["192.168.5.0/24"]
    acts = [a for a in _plan(cfg) if a.kind == "remote_print"]
    run = Rec()
    apply.execute(acts, run=run, resources=INSTALL, root=tmp_path / "root")
    out = capsys.readouterr().out
    assert run.calls == []  # printing runs nothing
    assert "443" in out and "80" in out and "03:10 America/New_York" in out
    assert "IPAddressAllow=127.0.0.0/8 ::1 160.79.104.0/21 2607:6bc0::/48 192.168.5.0/24" in out
    assert "certbot" in out and "filament-kit remote issue" in out
    assert "will not change" in out  # says plainly that the kit does not apply it


def test_remote_off_executor_removes_only_marked_route(tmp_path):
    root = tmp_path / "root"
    d = root / "etc/nginx/mcp.d"
    d.mkdir(parents=True)
    ours = d / "filament.conf"
    ours.write_text('# MCP server "filament" (written by mcp-route)\n')
    other = d / "amazon.conf"
    other.write_text("# hand-written\n")
    run = Rec()
    apply.execute([Action("remote_off", "filament")], run=run, resources=INSTALL, root=root)
    assert not ours.exists() and other.exists()
    assert "nginx -t" in run.texts()
    assert not any("apt" in t or "remove" in t for t in run.texts())


def test_remote_off_leaves_a_foreign_file_with_our_name(tmp_path, capsys):
    root = tmp_path / "root"
    d = root / "etc/nginx/mcp.d"
    d.mkdir(parents=True)
    f = d / "filament.conf"
    f.write_text("# hand-written\n")
    apply.execute([Action("remote_off", "filament")], run=Rec(), resources=INSTALL, root=root)
    assert f.exists()
    assert "not written by the kit" in capsys.readouterr().out


def test_full_remote_run_issues_no_firewall_command(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "cmd_cert", lambda: 0)
    monkeypatch.setattr(apply, "_tty", lambda: False)
    monkeypatch.setattr(apply, "_http_ok", lambda url: True)
    monkeypatch.setattr(apply.time, "sleep", lambda s: None)
    run = Rec()
    apply.execute(_plan(_cfg(acme_window="03:10")), run=run, resources=INSTALL, root=tmp_path / "root")
    assert not [t for t in run.texts() if FORBIDDEN.search(t)]
    assert "systemctl enable nginx.service" in run.texts()


def test_issue_runs_certbot_standalone_with_hooks(monkeypatch, capsys):
    run = Rec()
    monkeypatch.setattr(remote, "_is_root", lambda: True)
    assert remote.issue(_cfg(email="me@example.org"), run=run) == 0
    (cmd,) = run.calls
    text = " ".join(cmd)
    assert cmd[0] == "certbot" and "certonly" in cmd and "--standalone" in cmd
    assert cmd[cmd.index("-d") + 1] == "fk.example.org" and "--cert-name" in cmd
    assert "me@example.org" in text and "--agree-tos" in cmd
    for hook, arg in (("--pre-hook", "pre"), ("--post-hook", "post"), ("--deploy-hook", "deploy")):
        assert cmd[cmd.index(hook) + 1] == f"{remote.HOOK} {arg}"
    assert "port 80" in capsys.readouterr().out  # the owner opens it; we only say so
    assert not FORBIDDEN.search(text)


def test_issue_without_email_registers_without_one(monkeypatch):
    run = Rec()
    monkeypatch.setattr(remote, "_is_root", lambda: True)
    remote.issue(_cfg(), run=run)
    assert "--register-unsafely-without-email" in run.calls[0]


def test_issue_needs_root_and_the_module(monkeypatch):
    monkeypatch.setattr(remote, "_is_root", lambda: False)
    run = Rec()
    assert remote.issue(_cfg(), run=run) == 1 and run.calls == []
    monkeypatch.setattr(remote, "_is_root", lambda: True)
    cfg = _cfg()
    cfg["modules"]["remote"] = False
    assert remote.issue(cfg, run=run) == 1 and run.calls == []


def test_cli_remote_issue_wired(monkeypatch):
    seen = []
    monkeypatch.setattr(remote, "issue", lambda cfg, **k: seen.append(cfg) or 0)
    assert cli.main(["remote", "issue"]) == 0
    assert seen


def test_cli_remote_firewall_only_prints(capsys):
    config.save(_cfg(acme_window="03:10"))
    assert cli.main(["remote", "firewall"]) == 0
    assert "443" in capsys.readouterr().out


def test_wrapper_runs_remote_as_root():
    assert "config | cert | modules | remote)" in (INSTALL / "filament-kit-cli.sh").read_text()


def test_no_firewall_command_anywhere_in_the_remote_code_or_files():
    files = [*(INSTALL / "remote").iterdir(), Path(remote.__file__)]
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            assert not FORBIDDEN.search(line), f"{f.name}:{n}: {line}"


@pytest.mark.parametrize("name", ["mcp-route", "acme-hooks.sh"])
def test_shell_scripts_parse(name):
    sh = shutil.which("bash") or shutil.which("sh")
    if not sh:
        pytest.skip("no shell")
    subprocess.run([sh, "-n", str(INSTALL / "remote" / name)], check=True)


def test_release_files_include_remote():
    assert "install/remote" in (INSTALL.parent / "tools/make_release.sh").read_text()
    assert "$RES/remote" in (INSTALL / "install.sh").read_text()
