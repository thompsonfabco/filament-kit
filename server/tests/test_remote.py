"""Remote module (spec 4.4): plan, executor, issue command; the kit never changes a firewall."""
import datetime
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
    cfg = _cfg(hostname="FK.Example.org", acme_window="03:10 America/New_York")
    acts = _plan(cfg)
    assert _of(acts, "remote_install") == ["fk.example.org"]
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
    assert not any(t.startswith("openssl") for t in texts)      # the placeholder is made in process, tested below
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
    ours.write_text(f'# MCP server "filament" ({remote.MARK})\n')
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
    monkeypatch.setattr(apply, "_web_state", lambda ex: None)     # needs the real filament-kit-web user
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


def test_cli_remote_firewall_only_prints(capsys, tmp_path, monkeypatch):
    opt = tmp_path / "opt"
    shutil.copytree(INSTALL / "remote", opt / "resources" / "remote")   # where an install puts them
    monkeypatch.setenv("FK_OPT", str(opt))
    config.save(_cfg(acme_window="03:10"))
    assert cli.main(["remote", "firewall"]) == 0
    assert "443" in capsys.readouterr().out


def test_wrapper_runs_remote_as_root():
    text = (INSTALL / "filament-kit-cli.sh").read_text()
    assert "config | cert | modules | remote | migrate-ops | migrate-scanner | update | uninstall | station | setup-code)" in text


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


# ---- fix round 1 ----

def test_router_conf_has_no_http2_directive():
    text = (INSTALL / "remote" / "mcp-router.conf").read_text()
    assert "http2" not in text  # nginx 1.24 rejects `http2 on`; newer nginx warns about `listen ... http2`


def test_hostname_and_public_url_host_must_agree():
    with pytest.raises(ModuleError) as e:
        _plan(_cfg(hostname="other.example.org"))
    assert "other.example.org" in str(e.value) and "fk.example.org" in str(e.value)
    _plan(_cfg(hostname="FK.example.org"))  # same host, other case: fine


def test_timer_dropin_is_not_persistent():
    assert "Persistent=false" in remote.timer_dropin("03:10")


def test_unset_window_removes_the_kit_timer_dropin(tmp_path, capsys):
    acts = _plan(_cfg())
    assert _of(acts, "remote_unpin") == [""]
    root = tmp_path / "root"
    f = root / "etc/systemd/system/certbot.timer.d/acme-window.conf"
    f.parent.mkdir(parents=True)
    f.write_text("[Timer]\n")
    apply.execute([Action("remote_unpin")], run=Rec(), resources=INSTALL, root=root)
    assert not f.exists()
    assert not _of(_plan(_cfg(acme_window="03:10")), "remote_unpin")


def test_changed_route_name_removes_the_kits_old_route(tmp_path):
    root, run = tmp_path / "root", Rec()
    book = root / "etc/mcp-router/kit-routes"
    book.parent.mkdir(parents=True)
    book.write_text("oldname\n")
    apply.execute([Action("remote_route", ("filament", 8101))], run=run, resources=INSTALL, root=root)
    assert run.texts() == ["/usr/local/sbin/mcp-route rm oldname", "/usr/local/sbin/mcp-route add filament 8101"]
    assert book.read_text() == "filament\n"
    run2 = Rec()  # same name again: nothing to remove
    apply.execute([Action("remote_route", ("filament", 9000))], run=run2, resources=INSTALL, root=root)
    assert run2.texts() == ["/usr/local/sbin/mcp-route add filament 9000"]


def test_mcp_route_restores_state_when_nginx_rejects_the_route():
    text = (INSTALL / "remote" / "mcp-route").read_text()
    assert ".conf.old" in text and "restored the previous state" in text


def test_deploy_hook_double_registration_is_explained():
    src = Path(apply.__file__).read_text(encoding="utf-8")
    assert "renewal-hooks/deploy" in src and "--expand" in src


def test_firewall_command_without_resources_prints_a_fix(monkeypatch, capsys):
    def boom(*a, **k):
        raise FileNotFoundError("no remote dir")
    monkeypatch.setattr(remote, "firewall_text", boom)
    assert remote.firewall(_cfg()) == 1
    out = capsys.readouterr().out
    assert "error:" in out and "fix:" in out


def test_remote_off_removes_the_kits_router_conf_and_deploy_hook(tmp_path, capsys):
    """Ruling AF: off removes the kit's own router conf (a default_server on 443 that would block any other
    router) and its certbot deploy hook; nginx, certbot, the certificate and other routes stay."""
    root = tmp_path / "root"
    conf = root / "etc/nginx/conf.d/filament-kit-router.conf"
    hook = root / "etc/letsencrypt/renewal-hooks/deploy/filament-kit"
    other_conf = root / "etc/nginx/conf.d/other.conf"
    other_hook = root / "etc/letsencrypt/renewal-hooks/deploy/someone-else"
    cert = root / "etc/mcp-router/tls/fullchain.pem"
    for f in (conf, hook, other_conf, other_hook, cert):     # no other route in mcp.d (C-I2: else the conf stays)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x\n")
    run = Rec()
    apply.execute([Action("remote_off", "filament")], run=run, resources=INSTALL, root=root)
    assert not conf.exists() and not hook.exists()
    assert other_conf.exists() and other_hook.exists() and cert.exists()
    assert "nginx -t" in run.texts()
    assert not any("apt" in t or "remove" in t for t in run.texts())
    assert "router" in capsys.readouterr().out


def test_remote_off_with_nothing_installed_is_quiet(tmp_path):
    run = Rec()
    apply.execute([Action("remote_off", "filament")], run=run, resources=INSTALL, root=tmp_path / "root")
    assert "nginx -t" not in run.texts()


# ---------- final review fixes ----------

def test_remote_off_keeps_the_router_conf_while_other_routes_need_it(tmp_path, capsys):
    """C-I2: on the owner's VM the kit's router conf is the only server block including /etc/nginx/mcp.d. While a
    route file the kit did not add is there (amazon, h2d), turning remote off keeps the router conf and says so;
    the kit's own route and deploy hook still go."""
    root = tmp_path / "root"
    conf = root / "etc/nginx/conf.d/filament-kit-router.conf"
    hook = root / "etc/letsencrypt/renewal-hooks/deploy/filament-kit"
    ours = root / "etc/nginx/mcp.d/filament.conf"
    amazon = root / "etc/nginx/mcp.d/amazon.conf"
    book = root / "etc/mcp-router/kit-routes"
    for f in (conf, hook, amazon, book, ours):
        f.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text("x\n")
    hook.write_text("x\n")
    ours.write_text('# MCP server "filament" (written by mcp-route)\n')
    amazon.write_text('# MCP server "amazon" (written by mcp-route)\n')
    book.write_text("filament\n")
    run = Rec()
    apply.execute([Action("remote_off", "filament")], run=run, resources=INSTALL, root=root)
    assert conf.exists() and amazon.exists()
    assert not ours.exists() and not hook.exists()
    out = capsys.readouterr().out
    assert "kept the kit's router conf" in out and "amazon" in out
    assert "nginx -t" in run.texts()


def test_uninstall_keeps_the_router_conf_while_other_routes_need_it():
    """C-I2, uninstall.sh: the same rule as `remote` off (run for real on WSL)."""
    text = (INSTALL / "uninstall.sh").read_text(encoding="utf-8")
    block = text[text.index("# remote:"):text.index("rm -rf /opt/filament-kit")]
    assert "OTHER_ROUTES" in block and "/etc/nginx/mcp.d/" in block
    assert "kept the kit's router conf" in block


def test_remote_install_restores_the_previous_router_conf_when_nginx_test_fails(tmp_path, capsys):
    """C-I4: a router conf that fails `nginx -t` must not stay (every later nginx start would fail): the previous
    one comes back, or none, and the step fails."""
    root = tmp_path / "root"
    conf = root / "etc/nginx/conf.d/filament-kit-router.conf"
    proxy = root / "etc/nginx/mcp-proxy.conf"

    def run(cmd):
        if cmd[:2] == ["nginx", "-t"]:
            raise subprocess.CalledProcessError(1, cmd)

    with pytest.raises(apply.ApplyError):
        apply.execute([Action("remote_install", "fk.example.org")], run=run, resources=INSTALL, root=root)
    assert not conf.exists() and not proxy.exists()
    assert f"removed {remote.ROUTER_CONF}, {remote.PROXY_CONF} again" in capsys.readouterr().out
    conf.write_text("OLD ROUTER\n")
    proxy.write_text("OLD PROXY\n")
    with pytest.raises(apply.ApplyError):
        apply.execute([Action("remote_install", "fk.example.org")], run=run, resources=INSTALL, root=root)
    assert conf.read_text() == "OLD ROUTER\n" and proxy.read_text() == "OLD PROXY\n"
    assert f"put back the previous {remote.ROUTER_CONF}, {remote.PROXY_CONF}" in capsys.readouterr().out


def test_remote_install_writes_the_nginx_start_check_and_reloads_systemd_after_it(tmp_path):
    root = tmp_path / "root"
    ran = []
    apply.execute([Action("remote_install", "fk.example.org")], run=ran.append, resources=INSTALL, root=root)
    drop = root / remote.NGINX_DROPIN.lstrip("/")
    assert f"ExecStartPre=-{remote.HOOK} check" in drop.read_text()
    assert ["systemctl", "daemon-reload"] in ran
    assert ran.index(["systemctl", "daemon-reload"]) < ran.index(["nginx", "-t"])


def test_the_nginx_start_check_is_listed_before_the_distro_nginx_test():
    """The distro's unit runs `nginx -t` first and a failure stops the start; a drop-in only appends, so the list is
    cleared and ours goes first, then the test again (systemd runs ExecStartPre in the order given)."""
    pre = [l.split("=", 1)[1] for l in remote.NGINX_DROPIN_TEXT.splitlines() if l.startswith("ExecStartPre=")]
    assert pre[0] == ""                                  # reset: the unit's own lines are dropped
    assert pre[1] == f"-{remote.HOOK} check"             # the check, which may fail without stopping the start
    assert pre[2].startswith("/usr/sbin/nginx -t") and len(pre) == 3


def test_an_expired_served_certificate_warns_and_names_how_to_renew():
    """`web status` shows this as a failing row; it is what tells the owner the start check served an expired pair."""
    now = datetime.datetime(2026, 11, 12, tzinfo=datetime.timezone.utc)
    expired, text, fix = remote.certificate_warning(
        {"self_signed": False, "not_after": now - datetime.timedelta(days=3)}, now)
    assert expired and "ended on 2026-11-09" in text and "sudo certbot renew" in fix
    expired, text, fix = remote.certificate_warning(
        {"self_signed": True, "not_after": now - datetime.timedelta(days=3)}, now)
    assert expired and "sudo filament-kit modules apply" in fix


# ---- v0.3.0: the kit's own route marker (the ops router writes "written by mcp-route" too) ----

OPS_FIRST_LINE = ('# MCP server "@NAME@" -> 127.0.0.1:@PORT@   (written by mcp-route; public base '
                  'https://@HOST@/@NAME@)')


def _ops_route(name="filament", port=8790, host="mcp.example.com"):
    return OPS_FIRST_LINE.replace("@NAME@", name).replace("@PORT@", str(port)).replace("@HOST@", host) + "\n"


def test_kit_template_has_its_own_marker():
    first = (INSTALL / "remote" / "route.template").read_text(encoding="utf-8").splitlines()[0]
    assert remote.MARK in first and remote.OLD_MARK not in first
    assert remote.MARK != remote.OLD_MARK and remote.OLD_MARK not in remote.MARK
    assert remote.MARK in (INSTALL / "remote" / "mcp-route").read_text(encoding="utf-8")


def test_is_kit_route():
    assert remote.is_kit_route(f"# x ({remote.MARK}; public base y)\n", "filament", [])
    assert not remote.is_kit_route(_ops_route(), "filament", [])                 # the ops router's file
    assert remote.is_kit_route(_ops_route(), "filament", ["filament"])           # an older kit wrote it
    assert not remote.is_kit_route(_ops_route(), "filament", ["other"])
    assert not remote.is_kit_route("# hand-written\n", "filament", ["filament"])


def test_remote_off_never_removes_the_ops_route(tmp_path, capsys):
    """The live cut-over: `remote` off deleted the ops `filament` route, whose header the kit's matched."""
    root = tmp_path / "root"
    f = root / "etc/nginx/mcp.d/filament.conf"
    f.parent.mkdir(parents=True)
    f.write_text(_ops_route())
    apply.execute([Action("remote_off", "filament")], run=Rec(), resources=INSTALL, root=root)
    assert f.read_text() == _ops_route()
    assert "not written by the kit" in capsys.readouterr().out


def test_remote_off_removes_an_older_kit_route_listed_in_kit_routes(tmp_path):
    root = tmp_path / "root"
    f = root / "etc/nginx/mcp.d/filament.conf"
    f.parent.mkdir(parents=True)
    f.write_text(_ops_route(port=8101))
    book = root / "etc/mcp-router/kit-routes"
    book.parent.mkdir(parents=True)
    book.write_text("filament\n")
    apply.execute([Action("remote_off", "filament")], run=Rec(), resources=INSTALL, root=root)
    assert not f.exists()


def _mcp_route(tmp_path):
    """install/remote/mcp-route with its /etc paths under tmp_path, nginx and systemctl stubbed."""
    sh = shutil.which("bash")
    if not sh:
        pytest.skip("no bash")
    root = tmp_path / "r"
    (root / "etc/mcp-router").mkdir(parents=True)
    (root / "etc/nginx/mcp.d").mkdir(parents=True)
    (root / "etc/mcp-router/host").write_text("mcp.example.com\n")
    shutil.copy(INSTALL / "remote" / "route.template", root / "etc/mcp-router/route.template")
    text = (INSTALL / "remote" / "mcp-route").read_text(encoding="utf-8").replace("/etc/", f"{root.as_posix()}/etc/")
    script = tmp_path / "mcp-route"
    script.write_text(text, encoding="utf-8", newline="\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, rc in (("nginx", 0), ("systemctl", 1)):
        (bin_ / name).write_text(f"#!/bin/sh\nexit {rc}\n", newline="\n")
        os.chmod(bin_ / name, 0o755)
    env = dict(os.environ, PATH=f"{bin_.as_posix()}{os.pathsep}{os.environ['PATH']}")

    def run(*args):
        return subprocess.run([sh, script.as_posix(), *args], capture_output=True, text=True, env=env)
    return root, run


def test_mcp_route_leaves_the_ops_route_alone(tmp_path):
    root, run = _mcp_route(tmp_path)
    f = root / "etc/nginx/mcp.d/filament.conf"
    f.write_text(_ops_route())
    r = run("rm", "filament")
    assert r.returncode == 2 and "not ours" in r.stdout and f.read_text() == _ops_route()
    hand = root / "etc/nginx/mcp.d/mine.conf"
    hand.write_text("# hand-written\n")
    r = run("add", "mine", "8102")
    assert r.returncode == 2 and "not ours" in r.stdout and hand.read_text() == "# hand-written\n"


def test_mcp_route_add_takes_over_the_ops_route_as_the_cut_over_does(tmp_path):
    """migrate-from-filament-ops 1.5: `modules enable remote` replaces the ops `filament` route (saved first in
    /root/ops-router) with the kit's; from then on it is the kit's (marker, kit-routes) and remote off removes it."""
    root, run = _mcp_route(tmp_path)
    f = root / "etc/nginx/mcp.d/filament.conf"
    f.write_text(_ops_route())
    r = run("add", "filament", "8101")
    assert r.returncode == 0, r.stdout + r.stderr
    assert remote.MARK in f.read_text().splitlines()[0]


def test_mcp_route_takes_over_an_older_kit_route_and_writes_its_marker(tmp_path):
    root, run = _mcp_route(tmp_path)
    f = root / "etc/nginx/mcp.d/filament.conf"
    f.write_text(_ops_route(port=8101))
    (root / "etc/mcp-router/kit-routes").write_text("filament\n")
    r = run("add", "filament", "8101")
    assert r.returncode == 0, r.stdout + r.stderr
    assert remote.MARK in f.read_text().splitlines()[0]
    r = run("rm", "filament")
    assert r.returncode == 0 and not f.exists()


# ---- fix round 1: a stale kit-routes entry must not make a restored ops route the kit's ----

def _book(root):
    return root / "etc/mcp-router/kit-routes"


def test_remote_off_drops_the_name_from_kit_routes_then_leaves_a_restored_ops_route(tmp_path, capsys):
    root = tmp_path / "root"
    f = root / "etc/nginx/mcp.d/filament.conf"
    f.parent.mkdir(parents=True)
    f.write_text(f'# MCP server "filament" ({remote.MARK})\n')
    _book(root).parent.mkdir(parents=True)
    _book(root).write_text("filament\nother\n")
    apply.execute([Action("remote_off", "filament")], run=Rec(), resources=INSTALL, root=root)
    assert not f.exists() and _book(root).read_text().split() == ["other"]
    f.write_text(_ops_route())                       # the owner puts the ops route back (runbook 1.5 rollback)
    apply.execute([Action("remote_off", "filament")], run=Rec(), resources=INSTALL, root=root)
    assert f.read_text() == _ops_route()


def test_remote_off_drops_the_name_even_when_it_leaves_a_foreign_file(tmp_path):
    root = tmp_path / "root"
    f = root / "etc/nginx/mcp.d/filament.conf"
    f.parent.mkdir(parents=True)
    f.write_text("# hand-written\n")
    _book(root).parent.mkdir(parents=True)
    _book(root).write_text("filament\n")
    apply.execute([Action("remote_off", "filament")], run=Rec(), resources=INSTALL, root=root)
    assert f.exists() and _book(root).read_text().split() == []


def test_mcp_route_rm_drops_the_name_then_leaves_a_restored_ops_route(tmp_path):
    root, run = _mcp_route(tmp_path)
    f = root / "etc/nginx/mcp.d/filament.conf"
    f.write_text(_ops_route(port=8101))
    _book(root).write_text("filament\namazon\n")
    r = run("rm", "filament")                        # an older kit's route, listed: removed
    assert r.returncode == 0 and not f.exists(), r.stdout + r.stderr
    assert _book(root).read_text().split() == ["amazon"]
    f.write_text(_ops_route())
    r = run("rm", "filament")
    assert r.returncode == 2 and f.read_text() == _ops_route()


def _uninstall_remote_block(tmp_path):
    """The remote block of install/uninstall.sh, its /etc paths under tmp_path, nginx and systemctl stubbed."""
    sh = shutil.which("bash")
    if not sh:
        pytest.skip("no bash")
    root = tmp_path / "r"
    (root / "etc/mcp-router").mkdir(parents=True)
    (root / "etc/nginx/mcp.d").mkdir(parents=True)
    text = (INSTALL / "uninstall.sh").read_text(encoding="utf-8")
    block = text[text.index("# remote:"):text.index("rm -rf /opt/filament-kit")]
    script = tmp_path / "block.sh"
    script.write_text("set -euo pipefail\n" + block.replace("/etc/", f"{root.as_posix()}/etc/"), encoding="utf-8",
                      newline="\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name in ("nginx", "systemctl"):
        (bin_ / name).write_text("#!/bin/sh\nexit 1\n", newline="\n")
        os.chmod(bin_ / name, 0o755)
    env = dict(os.environ, PATH=f"{bin_.as_posix()}{os.pathsep}{os.environ['PATH']}")
    return root, lambda: subprocess.run([sh, script.as_posix()], capture_output=True, text=True, env=env)


def test_uninstall_leaves_a_listed_name_whose_file_is_not_the_kits(tmp_path):
    root, run = _uninstall_remote_block(tmp_path)
    d = root / "etc/nginx/mcp.d"
    (d / "filament.conf").write_text(_ops_route())          # stale listing + the restored ops route
    (d / "mine.conf").write_text("# hand-written\n")
    (d / "kit.conf").write_text(f'# MCP server "kit" ({remote.MARK})\n')
    _book(root).write_text("filament\nmine\nkit\n")
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (d / "filament.conf").read_text() == _ops_route() and (d / "mine.conf").exists()
    assert not (d / "kit.conf").exists()
