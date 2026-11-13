"""The station's client for the button flow (station/server_api.py): the pairing link, the pairing files, and the
three calls over pinned TLS against the real kit API."""
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fakes.claude_fake import FakeClaude

from conftest import free_port
from filament_kit import cli, config, inventory, modules, pairing
from filament_kit.api import create_app
from filament_kit.spoolman import Spoolman
from filament_kit.station import server_api
from step_lines import sentences

UID = "a:b:c:d:e:f:1"
FP = "ab" * 32
ITEM = {"photos": [0], "existing_filament_id": None, "vendor": "OVERTURE", "name": "PETG Black",
        "material": "PETG", "color_hex": "111111", "net": 1000, "tare": 155, "density": 1.27, "count": 1,
        "nozzle": 240, "bed": 75, "nozzle_range": "230-250", "bed_range": "70-80", "lot": None, "note": "",
        "estimates": [], "sealed": False, "sealed_reason": "bare spool", "line": "PETG"}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", ["127.0.0.1"], tmp_path / "etc")
    config.save({"placement": {"box_count": 2}})
    monkeypatch.setattr(inventory, "_record_lines", lambda items: None)
    monkeypatch.setattr(inventory, "_check_parents", lambda items: None)


def test_parse_link():
    link = server_api.parse_link(f"fkit://pair?h=srv.local&p=8710&t={'x' * 43}&fp={FP}&ip=192.0.2.5&ip=192.0.2.6")
    assert (link.host, link.port, link.fp, link.ips) == ("srv.local", 8710, FP, ["192.0.2.5", "192.0.2.6"])
    for bad in ("https://example.com", f"fkit://pair?h=a&p=0&t={'x' * 43}&fp={FP}",
                f"fkit://pair?h=a&p=1&t=short&fp={FP}", f"fkit://pair?h=a&p=1&t={'x' * 43}&fp=zz"):
        with pytest.raises(ValueError):
            server_api.parse_link(bad)


def test_save_pairing_writes_the_files(tmp_path):
    link = server_api.parse_link(f"fkit://pair?h=srv.local&p=8710&t={'y' * 43}&fp={FP}&ip=192.0.2.5")
    server_api.save_pairing(link, owner=None)
    cfg = json.loads(server_api.server_file().read_text())
    assert cfg == {"ips": ["192.0.2.5"], "port": 8710, "fp": FP, "host": "srv.local"}
    assert server_api.token_file().read_text().strip() == "y" * 43
    if sys.platform != "win32":
        assert (os.stat(server_api.token_file()).st_mode & 0o777) == 0o600
    api = server_api.ServerApi()
    assert api.paired and api.ips == ["192.0.2.5"]


def test_not_paired_answers_without_a_call():
    status, body = server_api.ServerApi().tag_lookup(UID)
    assert status == 0 and body["error"] == "not_paired" and body["display"][0] == "Not paired"


@pytest.fixture
def server(spoolman_url, tmp_path):
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    from fakes import serving
    etc = tmp_path / "etc"
    running = serving.start(create_app(sm=sm, claude=FakeClaude({"questions": [], "items": [ITEM]})),
                            ssl_certfile=str(etc / "cert.pem"), ssl_keyfile=str(etc / "key.pem"))
    yield running.port, sm
    running.stop(5)


def _pair(port) -> None:
    fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
    tok = pairing.redeem_code(pairing.issue("station").code)
    server_api.save_pairing(server_api.Link("fkhost.local", port, tok, fp, ["127.0.0.1"]), owner=None)


def test_the_flow_over_pinned_tls(server):
    port, sm = server
    _pair(port)
    api = server_api.ServerApi(timeout=10)
    status, body = api.tag_lookup(UID)
    assert status == 200 and body["known"] is False
    status, body = api.recognize(b"\xff\xd8\xff\xe0" + b"x" * 100, UID)
    assert status == 200 and body["source"] == "claude", body
    status, body = api.save({"uid": UID, "gross_g": 900, "item": body["item"]})
    assert status == 200 and body["created"] and body["remaining_g"] == 745
    status, body = api.tag_lookup(UID)
    assert status == 200 and body["known"] is True


def test_a_changed_certificate_is_refused_before_sending(server):
    port, _ = server
    _pair(port)
    cfg = json.loads(server_api.server_file().read_text())
    server_api.server_file().write_text(json.dumps({**cfg, "fp": FP}))
    status, body = server_api.ServerApi(timeout=10).tag_lookup(UID)
    assert status == 0 and body["error"] == "cert_changed" and body["display"][0] == "Server changed"


def test_unreachable_server(server):
    port, _ = server
    _pair(port)
    cfg = json.loads(server_api.server_file().read_text())
    server_api.server_file().write_text(json.dumps({**cfg, "port": free_port()}))
    status, body = server_api.ServerApi(timeout=3).tag_lookup(UID)
    assert status == 0 and body["error"] == "unreachable" and body["display"] == server_api.UNREACHABLE


def test_station_pair_command(server, monkeypatch):
    port, _ = server
    if hasattr(os, "geteuid"):
        monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(server_api, "save_pairing", lambda link, owner="x", first=None, _real=server_api.save_pairing:
                        _real(link, owner=None, first=first))
    pr = pairing.issue("station")
    # an address the station can't reach comes first (a container bridge): pairing skips it and remembers the good one
    link = pr.qr.split("&ip=")[0] + "&ip=127.0.0.2&ip=127.0.0.1"
    link = link.replace(f"p={config.load()['port']}", f"p={port}")
    answers = iter([link, "y"])
    assert cli.cmd_station_pair(ask=lambda prompt: next(answers)) == 0
    api = server_api.ServerApi(timeout=10)
    assert api.paired and api.ips[0] == "127.0.0.1"
    assert api.tag_lookup(UID)[0] == 200
    answers = iter([link, "n"])
    assert cli.cmd_station_pair(ask=lambda prompt: next(answers)) == 1


def _local_pair(server, monkeypatch, on=("server", "station")):
    port, _ = server
    if hasattr(os, "geteuid"):
        monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(server_api, "save_pairing", lambda link, owner="x", first=None, _real=server_api.save_pairing:
                        _real(link, owner=None, first=first))
    cfg = config.load()
    cfg["port"] = port
    cfg["modules"] = {n: n in on for n in modules.MODULES}
    config.save(cfg)
    monkeypatch.setattr("filament_kit.apply.refresh_station", lambda cfg: "restarted")


def test_station_pair_local_needs_no_link_and_no_answer(server, monkeypatch, capsys):
    _local_pair(server, monkeypatch)
    assert cli.main(["station", "pair", "--local"]) == 0
    out = capsys.readouterr()
    assert "Paired." in out.out
    api = server_api.ServerApi(timeout=10)
    assert api.paired and api.ips[0] == "127.0.0.1" and api.tag_lookup(UID)[0] == 200
    assert api.token not in out.out + out.err           # the output goes to the page's job log


def test_station_pair_local_writes_its_three_steps(server, monkeypatch, capsys):
    _local_pair(server, monkeypatch)
    assert cli.main(["station", "pair", "--local"]) == 0
    assert sentences(capsys.readouterr().out, 3) == [
        "Asking the Hub", "Saving the pairing", "Restarting the Weigh Station service"]


def test_station_pair_local_with_the_station_off_stops_after_saving(server, monkeypatch, capsys):
    _local_pair(server, monkeypatch, on=("server",))
    assert cli.main(["station", "pair", "--local"]) == 0
    assert sentences(capsys.readouterr().out, 3, whole=False) == ["Asking the Hub", "Saving the pairing"]


def test_station_pair_local_refuses_with_no_server_here(server, monkeypatch, capsys):
    _local_pair(server, monkeypatch, on=("station",))
    assert cli.main(["station", "pair", "--local"]) == 1
    assert "pair --station" in capsys.readouterr().err
    assert not server_api.ServerApi(timeout=10).paired


def test_pairing_files_live_in_the_stations_own_folder(tmp_path):
    """Not /etc/filament-kit (root:filament-kit 2750, closed to the station's service user)."""
    link = server_api.parse_link(f"fkit://pair?h=srv.local&p=8710&t={'y' * 43}&fp={FP}&ip=192.0.2.5")
    server_api.save_pairing(link, owner=None)
    d = server_api.pairing_dir()
    assert d == config.paths().etc.parent / f"{config.paths().etc.name}-station"
    assert server_api.server_file().parent == d and server_api.token_file().parent == d
    assert not (config.paths().etc / "station_token").exists()
    if sys.platform != "win32":
        assert (os.stat(d).st_mode & 0o777) == 0o750


def test_uninstall_purge_removes_the_station_pairing_folder():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "install" / "uninstall.sh").read_text(encoding="utf-8")
    assert "rm -rf /etc/filament-kit /etc/filament-kit-station " in text


# ---------- the station's network allow-list follows the pairing (fix round 1, I1) ----------

def _paired(ips):
    link = server_api.parse_link(f"fkit://pair?h=kit.example.com&p=8710&t={'z' * 43}&fp={FP}"
                                 + "".join(f"&ip={i}" for i in ips))
    server_api.save_pairing(link, owner=None)


def _allow_line(text: str) -> str:
    return next(ln for ln in text.splitlines() if ln.startswith("IPAddressAllow="))


def test_station_mode_dropin_allows_the_paired_servers_addresses():
    from filament_kit import apply, modules
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "station")
    cfg["station"]["allow"] = ["192.0.2.10"]
    assert _allow_line(apply.station_dropin(cfg, ["192.0.2.10"])) == "IPAddressAllow=localhost 192.0.2.10"
    _paired(["192.0.2.10", "198.51.100.7"])
    text = apply.station_dropin(cfg, ["192.0.2.10"])
    assert _allow_line(text) == "IPAddressAllow=localhost 192.0.2.10 198.51.100.7"
    assert '"STATION_ALLOW=127.0.0.1 192.0.2.10"' in text  # the HTTP answers are not widened


def test_all_in_one_dropin_allows_the_paired_lan_address():
    from filament_kit import apply, modules
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "all-in-one")
    _paired(["127.0.0.1", "192.0.2.5"])  # the server's LAN address from its link, loopback first
    assert _allow_line(apply.station_dropin(cfg, ["127.0.0.1"])) == "IPAddressAllow=localhost 127.0.0.1 192.0.2.5"


def test_a_broken_pairing_file_does_not_stop_the_dropin():
    from filament_kit import apply, modules
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "all-in-one")
    server_api.pairing_dir().mkdir(parents=True, exist_ok=True)
    server_api.server_file().write_text("{not json", encoding="utf-8")
    assert _allow_line(apply.station_dropin(cfg, ["127.0.0.1"])) == "IPAddressAllow=localhost 127.0.0.1"
    server_api.server_file().write_text(json.dumps({"ips": ["10.0.0.1; rm -rf /", "192.0.2.9"]}), encoding="utf-8")
    assert _allow_line(apply.station_dropin(cfg, ["127.0.0.1"])) == "IPAddressAllow=localhost 127.0.0.1 192.0.2.9"


def test_refresh_station_rewrites_the_dropin_and_restarts(tmp_path, monkeypatch):
    from filament_kit import apply, modules
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "all-in-one")
    _paired(["127.0.0.1", "192.0.2.5"])
    ran = []
    assert apply.refresh_station(cfg, run=ran.append, root=tmp_path / "root") == "restarted"
    dropin = (tmp_path / "root" / apply.DROPIN.lstrip("/")).read_text(encoding="utf-8")
    assert "192.0.2.5" in _allow_line(dropin)
    assert ran == [["systemctl", "daemon-reload"], ["systemctl", "restart", apply.STATION_UNIT]]


def test_refresh_station_leaves_the_station_alone_when_the_dropin_is_the_same(tmp_path, monkeypatch):
    """A restart costs the reader about 6 s and resets the panel; the running flow picks up new pairing files itself."""
    from filament_kit import apply, modules
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "all-in-one")
    _paired(["127.0.0.1", "192.0.2.5"])
    root = tmp_path / "root"
    apply.refresh_station(cfg, run=lambda cmd: None, root=root)
    installed = root / apply.DROPIN.lstrip("/")
    before = installed.stat().st_mtime_ns
    ran = []
    assert apply.refresh_station(cfg, run=ran.append, root=root) == "unchanged"
    assert ran == [["systemctl", "is-active", "--quiet", apply.STATION_UNIT]]  # running: only asked
    assert installed.stat().st_mtime_ns == before
    ran.clear()
    _paired(["127.0.0.1", "198.51.100.7"])  # a new address: the unit's filter has to change, so it does restart
    assert apply.refresh_station(cfg, run=ran.append, root=root) == "restarted"
    assert ran == [["systemctl", "daemon-reload"], ["systemctl", "restart", apply.STATION_UNIT]]
    assert "198.51.100.7" in _allow_line(installed.read_text(encoding="utf-8"))


def test_refresh_station_starts_a_stopped_station_when_the_dropin_is_the_same(tmp_path, monkeypatch):
    """Pairing a station someone stopped still leaves it running: started, not restarted, and no reload."""
    from filament_kit import apply, modules
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "all-in-one")
    _paired(["127.0.0.1", "192.0.2.5"])
    root = tmp_path / "root"
    apply.refresh_station(cfg, run=lambda cmd: None, root=root)
    ran = []

    def stopped(cmd):
        ran.append(cmd)
        if "is-active" in cmd:
            raise subprocess.CalledProcessError(3, cmd)
    assert apply.refresh_station(cfg, run=stopped, root=root) == "started"
    assert ran == [["systemctl", "is-active", "--quiet", apply.STATION_UNIT],
                   ["systemctl", "start", apply.STATION_UNIT]]


def _pair_cli(monkeypatch, mode, link_ips, refresh):
    from filament_kit import modules
    if hasattr(os, "geteuid"):
        monkeypatch.setattr(os, "geteuid", lambda: 0)
    cfg = modules.set_mode({"placement": {"box_count": 2}}, mode, say=None)
    if mode == "station":
        cfg.setdefault("station", {})["allow"] = ["192.0.2.10"]
    config.save(cfg)
    probed = []
    monkeypatch.setattr(server_api, "peer_fingerprint", lambda ip, port, timeout=10: probed.append(ip) or FP)
    monkeypatch.setattr(server_api.ServerApi, "hello", lambda self: (200, {"ok": True}))  # no server here
    monkeypatch.setattr(server_api, "save_pairing", lambda link, owner="x", first=None, _real=server_api.save_pairing:
                        _real(link, owner=None, first=first))
    from filament_kit import apply
    monkeypatch.setattr(apply, "refresh_station", refresh)
    link = f"fkit://pair?h=kit.example.com&p=8710&t={'q' * 43}&fp={FP}" + "".join(f"&ip={i}" for i in link_ips)
    answers = iter([link, "y"])
    return cli.cmd_station_pair(ask=lambda prompt: next(answers)), probed


def test_station_pair_on_the_servers_machine_uses_loopback_first_and_refreshes(monkeypatch, capsys):
    refreshed = []
    code, probed = _pair_cli(monkeypatch, "all-in-one", ["192.0.2.5"], lambda cfg, **kw: refreshed.append(cfg) or "restarted")
    assert code == 0 and probed == ["127.0.0.1"]
    assert server_api.ServerApi().ips == ["127.0.0.1", "192.0.2.5"]
    assert len(refreshed) == 1 and "restarted" in capsys.readouterr().out


def test_station_pair_says_the_command_when_the_refresh_fails(monkeypatch, capsys):
    from filament_kit import apply

    def boom(cfg, **kw):
        raise apply.ApplyError("install_file: read-only")
    code, probed = _pair_cli(monkeypatch, "station", ["192.0.2.5"], boom)
    assert code == 0 and probed == ["192.0.2.5"]  # no local server: the link's address only
    out = capsys.readouterr()
    assert "sudo filament-kit modules apply" in out.out + out.err


def test_save_pairing_server_file_is_world_readable_whatever_the_umask():
    if sys.platform == "win32":
        pytest.skip("POSIX modes")
    old = os.umask(0o077)
    try:
        _paired(["192.0.2.5"])
    finally:
        os.umask(old)
    assert (os.stat(server_api.server_file()).st_mode & 0o777) == 0o644


# ---------- final fix wave I4: a request that went out is never sent again to the next address ----------

class _FakeConn:
    """Stands in for _Pinned: per address, connect() fails (refused) or works, and the request then times out
    or answers 200."""
    plan: dict = {}
    seen: list = []

    def __init__(self, host, port, fp, timeout):
        self.host = host
        self.status = 200

    def connect(self):
        if self.plan[self.host] == "refused":
            raise ConnectionRefusedError(111, "Connection refused")

    def request(self, method, path, body=None, headers=None):
        self.seen.append((self.host, method, path))
        if self.plan[self.host] == "timeout":
            raise TimeoutError("The read operation timed out")

    def getresponse(self):
        conn = self

        class R:
            status = conn.status

            @staticmethod
            def read():
                return b'{"known": false}'
        return R()

    def close(self):
        pass


def _fake_api(monkeypatch, plan):
    _FakeConn.plan, _FakeConn.seen = plan, []
    monkeypatch.setattr(server_api, "_Pinned", _FakeConn)
    _paired(list(plan))
    return server_api.ServerApi(timeout=3)


def test_a_timeout_after_sending_is_final_and_not_resent(monkeypatch):
    api = _fake_api(monkeypatch, {"192.0.2.1": "timeout", "192.0.2.2": "ok"})
    status, body = api.save({"uid": UID, "gross_g": 900})
    assert status == 0 and body["error"] == "timeout" and body["display"]
    assert [s[0] for s in _FakeConn.seen] == ["192.0.2.1"]  # the second address saw no request


def test_a_failed_connect_moves_on_to_the_next_address(monkeypatch):
    api = _fake_api(monkeypatch, {"192.0.2.1": "refused", "192.0.2.2": "ok"})
    status, body = api.tag_lookup(UID)
    assert status == 200 and body == {"known": False}
    assert [s[0] for s in _FakeConn.seen] == ["192.0.2.2"]


def test_every_connect_failing_is_unreachable(monkeypatch):
    api = _fake_api(monkeypatch, {"192.0.2.1": "refused", "192.0.2.2": "refused"})
    status, body = api.tag_lookup(UID)
    assert status == 0 and body["error"] == "unreachable" and _FakeConn.seen == []


# ---------- final fix wave I1: `station pair` claims the token at once; M3: the station token's scope ----------

def _later(monkeypatch, seconds):
    """pairing's clock moved on (the server's devices.json ages; the TLS stack keeps the real clock)."""
    import types
    real = time.time
    monkeypatch.setattr(pairing, "time", types.SimpleNamespace(time=lambda: real() + seconds))


def _station_link(port, pr):
    link = pr.qr.split("&ip=")[0] + "&ip=127.0.0.1"
    return link.replace(f"p={config.load()['port']}", f"p={port}")


def _as_root(monkeypatch):
    if hasattr(os, "geteuid"):
        monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(server_api, "save_pairing", lambda link, owner="x", first=None, _real=server_api.save_pairing:
                        _real(link, owner=None, first=first))


def test_station_pair_claims_the_token_so_a_tap_next_day_works(server, monkeypatch, capsys):
    port, _ = server
    _as_root(monkeypatch)
    answers = iter([_station_link(port, pairing.issue("station")), "y"])
    assert cli.cmd_station_pair(ask=lambda prompt: next(answers)) == 0
    assert "Paired" in capsys.readouterr().out
    _later(monkeypatch, pairing.TOKEN_TTL + 3600)  # the first spool is tapped long after the link's 10 minutes
    assert server_api.ServerApi(timeout=10).tag_lookup(UID)[0] == 200


def test_station_pair_with_an_expired_link_does_not_say_paired(server, monkeypatch, capsys):
    port, _ = server
    _as_root(monkeypatch)
    link = _station_link(port, pairing.issue("station"))
    _later(monkeypatch, pairing.TOKEN_TTL + 1)
    answers = iter([link, "y"])
    assert cli.cmd_station_pair(ask=lambda prompt: next(answers)) == 1
    out = capsys.readouterr()
    assert "Paired" not in out.out
    assert "10 minutes" in out.err and "sudo filament-kit pair --station" in out.err


def test_the_station_token_reaches_only_the_station_routes(server):
    port, _ = server
    _pair(port)
    api = server_api.ServerApi(timeout=10)
    assert api.tag_lookup(UID)[0] == 200
    assert api._call("GET", "/api/info")[0] == 200
    for path in ("/api/spools", "/api/tags/" + UID, "/api/locations", "/api/station", "/api/printers"):
        status, body = api._call("GET", path)
        assert status == 403 and body["error"] == "forbidden", path
    phone = pairing.redeem_code(pairing.issue().code)  # a phone's token is not limited
    api.token = phone
    assert api._call("GET", "/api/locations")[0] == 200


# ---------- final fix wave I2: an unpaired station says so (status, the install's finish, the OLED) ----------

PAIR_STEPS = ("sudo filament-kit pair --station", "sudo filament-kit station pair")


def _station_mode(monkeypatch):
    from filament_kit import modules
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    cfg = modules.set_mode({"placement": {"box_count": 2}}, "station", say=None)
    cfg.setdefault("station", {})["allow"] = ["192.0.2.10"]
    config.save(cfg)


def test_status_on_a_station_says_the_button_flow_is_not_paired(monkeypatch, capsys):
    _station_mode(monkeypatch)
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "not paired" in out and all(c in out for c in PAIR_STEPS)
    _paired(["192.0.2.10"])
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "station paired with the kit server" in out and PAIR_STEPS[1] not in out


def test_finish_on_an_unpaired_station_names_both_pairing_steps(monkeypatch, capsys):
    from filament_kit import apply
    _station_mode(monkeypatch)
    apply.finish(config.load(), run=lambda cmd: None)
    out = capsys.readouterr().out
    assert "not paired" in out and all(c in out for c in PAIR_STEPS)
    _paired(["192.0.2.10"])
    apply.finish(config.load(), run=lambda cmd: None)
    assert PAIR_STEPS[1] not in capsys.readouterr().out


class _Unreadable:
    """The token as the service user `filament-kit` meets it: the folder is closed to that user."""

    @staticmethod
    def read_bytes():
        raise PermissionError(13, "Permission denied")


def test_pairing_state_is_one_line_without_the_token(monkeypatch):
    assert server_api.pairing_state() == "unpaired"
    _paired(["192.0.2.10"])
    state = server_api.pairing_state()
    assert state == "paired 192.0.2.10:8710"
    assert "z" * 43 not in state
    monkeypatch.setattr(server_api, "token_file", _Unreadable)
    assert server_api.pairing_state() == "unchecked"


def test_pairing_lines_show_the_state_root_passed_in(monkeypatch):
    """The state comes from root (the wrapper, the console's helper); the reader needs no access to the pairing."""
    monkeypatch.setattr(server_api, "token_file", _Unreadable)
    assert server_api.pairing_lines("paired 192.0.2.10:8710") == [
        "OK   station paired with the kit server (192.0.2.10:8710)"]
    lines = server_api.pairing_lines("unpaired")
    assert "not paired" in lines[0] and all(c in lines[1] for c in PAIR_STEPS)
    assert "run it with sudo" in server_api.pairing_lines("unchecked")[0]
    for broken in ("failed", "paired", "", "paired a b"):
        lines = server_api.pairing_lines(broken)
        assert "could not be checked" in lines[0] and "sudo" not in lines[0].split(":")[0], broken
    assert "run it with sudo" in server_api.pairing_lines()[0]  # asked with no state, it looks for itself


def test_status_prints_the_state_passed_in_even_when_the_files_are_closed(monkeypatch, capsys):
    """What `sudo filament-kit status` runs: the wrapper's root check, then status as the service user."""
    _station_mode(monkeypatch)
    monkeypatch.setattr(server_api, "token_file", _Unreadable)
    cli.main(["status", "--station-pairing=paired 192.0.2.10:8710"])
    out = capsys.readouterr().out
    assert "OK   station paired with the kit server (192.0.2.10:8710)" in out and "run it with sudo" not in out
    cli.main(["status", "--station-pairing=unpaired"])
    assert PAIR_STEPS[1] in capsys.readouterr().out
    cli.main(["status"])  # no sudo: the wrapper passes nothing, and "run it with sudo" is the true advice
    assert "run it with sudo" in capsys.readouterr().out


def test_station_pairing_state_command_prints_the_state(capsys):
    assert cli.main(["station", "pairing-state"]) == 0
    assert capsys.readouterr().out.strip() == "unpaired"
    _paired(["192.0.2.10"])
    assert cli.main(["station", "pairing-state"]) == 0
    assert capsys.readouterr().out.strip() == "paired 192.0.2.10:8710"


# ---------- item 27: `station pair` with no terminal, and the part without prompts for the console's helper ----------

def _no_terminal(prompt):
    raise EOFError


def _nothing_saved() -> bool:
    return not server_api.server_file().exists() and not server_api.token_file().exists()


def _link(ips=("192.0.2.5",), fp=FP) -> "server_api.Link":
    return server_api.parse_link(f"fkit://pair?h=kit.example.com&p=8710&t={'q' * 43}&fp={fp}"
                                 + "".join(f"&ip={i}" for i in ips))


def test_station_pair_with_no_terminal_at_the_link_prompt(monkeypatch, capsys):
    _as_root(monkeypatch)
    assert cli.cmd_station_pair(ask=_no_terminal) == 1
    err = capsys.readouterr().err
    assert "terminal" in err and err.startswith("error:")
    assert _nothing_saved()


class _BadStdin(io.StringIO):
    """`sudo ... <&-`: Python has a stdin object, and reading it fails."""

    def readline(self, *a):
        raise OSError(9, "Bad file descriptor")


@pytest.mark.parametrize("stdin", [io.StringIO(""), None, _BadStdin()], ids=["end-of-file", "lost", "bad-fd"])
def test_station_pair_from_the_command_line_with_no_input(monkeypatch, capsys, stdin):
    """The real `input`: `< /dev/null` is an EOFError; `<&-` is a RuntimeError with no sys.stdin, or an OSError with
    one whose descriptor is gone (seen under sudo)."""
    _as_root(monkeypatch)
    monkeypatch.setattr(sys, "stdin", stdin)
    assert cli.main(["station", "pair"]) == 1
    assert "terminal" in capsys.readouterr().err
    assert _nothing_saved()


def _pair_fakes(monkeypatch, fp=FP):
    """No server here: `calls` records the claim of the token."""
    calls = []
    monkeypatch.setattr(server_api, "peer_fingerprint", lambda ip, port, timeout=10: fp)
    monkeypatch.setattr(server_api.ServerApi, "hello", lambda self: calls.append(self.ips) or (200, {"ok": True}))
    return calls


def test_a_closed_fingerprint_prompt_counts_as_no(monkeypatch, capsys):
    _as_root(monkeypatch)
    calls = _pair_fakes(monkeypatch)
    _paired(["198.51.100.7"])
    before = (server_api.server_file().read_bytes(), server_api.token_file().read_bytes())
    answers = iter([f"fkit://pair?h=kit.example.com&p=8710&t={'q' * 43}&fp={FP}&ip=192.0.2.5"])

    def ask(prompt):
        for a in answers:
            return a
        raise EOFError
    assert cli.cmd_station_pair(ask=ask) == 1
    out = capsys.readouterr()
    assert "terminal" in out.err and "Paired" not in out.out
    assert calls == []  # the token was not claimed
    assert (server_api.server_file().read_bytes(), server_api.token_file().read_bytes()) == before


def test_pair_with_link_needs_no_prompt(monkeypatch):
    """What the console's helper job calls: the link's fingerprint against what the server presents is the check."""
    _as_root(monkeypatch)
    calls = _pair_fakes(monkeypatch)
    monkeypatch.setattr("builtins.input", _no_terminal)
    from filament_kit import apply, modules
    refreshed = []
    monkeypatch.setattr(apply, "refresh_station", lambda cfg, **kw: refreshed.append(cfg) or "restarted")
    config.save(modules.set_mode({"placement": {"box_count": 2}}, "all-in-one", say=None))
    result = server_api.pair_with_link(_link())
    assert result.status == "paired" and "restarted" in result.message
    assert server_api.ServerApi().ips == ["127.0.0.1", "192.0.2.5"]
    assert server_api.token_file().read_text().strip() == "q" * 43
    assert len(calls) == 1 and len(refreshed) == 1
    assert "q" * 43 not in result.message


@pytest.mark.parametrize("outcome, message", [
    ("restarted", "Paired. The station was restarted and uses the server now."),
    ("started", "Paired. The station was started and uses the server now."),
    ("unchanged", "Paired. The station uses the server now; no restart was needed."),
])
def test_pair_with_link_says_what_happened_to_the_station(monkeypatch, outcome, message):
    from filament_kit import apply, modules
    _as_root(monkeypatch)
    _pair_fakes(monkeypatch)
    monkeypatch.setattr(apply, "refresh_station", lambda cfg, **kw: outcome)
    config.save(modules.set_mode({"placement": {"box_count": 2}}, "all-in-one", say=None))
    result = server_api.pair_with_link(_link())
    assert result.status == "paired" and result.message == message


def test_pair_with_link_says_when_the_module_is_off(monkeypatch):
    _as_root(monkeypatch)
    _pair_fakes(monkeypatch)
    result = server_api.pair_with_link(_link())
    assert result.status == "paired" and "modules enable station" in result.message


def test_pair_with_link_refuses_another_certificate_and_saves_nothing(monkeypatch):
    _as_root(monkeypatch)
    calls = _pair_fakes(monkeypatch, fp="cd" * 32)
    result = server_api.pair_with_link(_link())
    assert result.status == "failed" and "different certificate" in result.message
    assert calls == [] and _nothing_saved()


def test_pair_with_link_asks_confirm_with_the_fingerprint_seen(monkeypatch):
    _as_root(monkeypatch)
    calls = _pair_fakes(monkeypatch)
    seen = []
    result = server_api.pair_with_link(_link(), confirm=lambda fp: seen.append(fp) or False)
    assert seen == [FP] and result.status == "declined"
    assert calls == [] and _nothing_saved()


def test_pair_with_link_reports_an_unreachable_server(monkeypatch):
    _as_root(monkeypatch)

    def refused(ip, port, timeout=10):
        raise ConnectionRefusedError(111, "Connection refused")
    monkeypatch.setattr(server_api, "peer_fingerprint", refused)
    result = server_api.pair_with_link(_link())
    assert result.status == "failed" and "not reachable" in result.message and "192.0.2.5" in result.message
    assert _nothing_saved()


def test_pair_with_link_says_when_the_restart_failed(monkeypatch):
    from filament_kit import apply, modules
    _as_root(monkeypatch)
    _pair_fakes(monkeypatch)
    config.save(modules.set_mode({"placement": {"box_count": 2}}, "all-in-one", say=None))

    def boom(cfg, **kw):
        raise apply.ApplyError("install_file: read-only")
    monkeypatch.setattr(apply, "refresh_station", boom)
    result = server_api.pair_with_link(_link())
    assert result.status == "paired_not_restarted" and "sudo filament-kit modules apply" in result.message
    assert server_api.ServerApi().paired


def test_the_idle_screen_says_not_paired_without_a_pairing():
    from filament_kit.station import flow
    from filament_kit.station import state as st
    with st.lock:
        flow.reset()
    flow.go("idle")
    assert flow.screen()[0] == "Not paired"
    _paired(["192.0.2.10"])
    assert flow.screen()[0] == "Ready"


# ---------- final fix wave M2: a reinstall gives the kept pairing to the station user it has now ----------

def _station_plan():
    from filament_kit import apply, modules
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "all-in-one", say=None)
    return apply.plan(cfg, resolve=lambda h: [h])


def test_apply_gives_a_kept_pairing_to_the_current_station_user(tmp_path, monkeypatch):
    from filament_kit import apply
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    kinds = [a.kind for a in _station_plan()]
    assert kinds.index("user") < kinds.index("station_pairing_owner") < kinds.index("enable")
    ran = []
    act = [a for a in _station_plan() if a.kind == "station_pairing_owner"]
    apply.execute(act, run=ran.append, root=tmp_path / "root")
    assert ran == []  # nothing paired yet: nothing to hand over
    _paired(["192.0.2.5"])
    apply.execute(act, run=ran.append, root=tmp_path / "root")
    d, srv, tok = (str(p) for p in (server_api.pairing_dir(), server_api.server_file(), server_api.token_file()))
    assert ran == [["chown", "root:filament-kit-station", d], ["chown", "root:filament-kit-station", srv],
                   ["chown", "filament-kit-station:filament-kit-station", tok]]


def test_a_failed_re_pair_keeps_the_working_pairing(server, monkeypatch, capsys):
    """The new link is checked before anything is saved: an expired re-pair leaves the station's pairing as it was."""
    port, _ = server
    _as_root(monkeypatch)
    answers = iter([_station_link(port, pairing.issue("station")), "y"])
    assert cli.cmd_station_pair(ask=lambda prompt: next(answers)) == 0
    before = (server_api.server_file().read_bytes(), server_api.token_file().read_bytes())
    stale = _station_link(port, pairing.issue("station"))
    _later(monkeypatch, pairing.TOKEN_TTL + 1)
    answers = iter([stale, "y"])
    assert cli.cmd_station_pair(ask=lambda prompt: next(answers)) == 1
    assert (server_api.server_file().read_bytes(), server_api.token_file().read_bytes()) == before
    assert server_api.ServerApi(timeout=10).tag_lookup(UID)[0] == 200


def test_a_station_device_from_before_scopes_is_scoped(server):
    """A device named "station" with no stored scope (paired by an earlier build) reaches only the station routes."""
    port, _ = server
    _pair(port)
    devs = json.loads((config.paths().state / "devices.json").read_text())
    for d in devs:
        d.pop("scope", None)
    (config.paths().state / "devices.json").write_text(json.dumps(devs))
    api = server_api.ServerApi(timeout=10)
    assert api.tag_lookup(UID)[0] == 200
    assert api._call("GET", "/api/spools")[0] == 403


# ---------------------------------------------------------------- reverse pairing, the station side (protocol v2)

def _approve_when_asked(approve=True, seen=None):
    from filament_kit import station_requests

    def run():
        for _ in range(200):
            rows = station_requests.pending()
            if rows:
                if seen is not None:
                    seen.append(rows[0]["code"])
                station_requests.decide(rows[0]["id"], approve)
                return
            time.sleep(0.05)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_the_station_asks_shows_the_kits_code_and_its_pairing_is_saved_as_root(server, tmp_path, monkeypatch):
    from filament_kit.station import pair_apply, pair_request
    port, _ = server
    seen, shown = [], []
    t = _approve_when_asked(seen=seen)
    result = pair_request.run_once("127.0.0.1", port, "Bench", on_code=shown.append, folder=tmp_path / "pair",
                                   sleep=lambda s: time.sleep(0.05))
    t.join(5)
    assert result == "approved" and shown == seen and len(shown[0]) == 6     # the station's digits are the page's
    drop = tmp_path / "pair" / pair_request.REQUEST_FILE
    assert drop.exists() and (sys.platform == "win32" or (os.stat(drop).st_mode & 0o777) == 0o600)
    cfg = config.load()
    cfg["station"] = {**cfg.get("station", {}), "allow": ["127.0.0.1"]}
    cfg["modules"] = {"station": True}
    config.save(cfg)
    refreshed = []
    assert pair_apply.apply_drop(drop, refresh=refreshed.append) == "saved"
    assert not drop.exists() and len(refreshed) == 1
    api = server_api.ServerApi(timeout=10)
    assert api.paired and api.ips == ["127.0.0.1"] and api.hello()[0] == 200


def test_a_refused_station_writes_nothing(server, tmp_path):
    from filament_kit.station import pair_request
    port, _ = server
    t = _approve_when_asked(approve=False)
    assert pair_request.run_once("127.0.0.1", port, "x", folder=tmp_path / "pair",
                                 sleep=lambda s: time.sleep(0.05)) == "refused"
    t.join(5)
    assert not (tmp_path / "pair" / pair_request.REQUEST_FILE).exists()


def test_a_server_that_does_not_answer_is_failed(tmp_path):
    from filament_kit.station import pair_request
    assert pair_request.run_once("127.0.0.1", free_port(), "x", folder=tmp_path) == "failed"


def _drop(tmp_path, body) -> Path:
    d = tmp_path / "pair"
    d.mkdir(exist_ok=True)
    f = d / "request.json"
    f.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return f


GOOD = {"fp": "ab" * 32, "token": "t" * 43, "port": 8710}


@pytest.mark.parametrize("body", [{**GOOD, "fp": "zz"}, {**GOOD, "token": "x"}, {**GOOD, "port": 0},
                                  {**GOOD, "port": "8710"}, [1], "not json", "x" * 5000])
def test_the_root_side_refuses_a_bad_drop_and_removes_it(tmp_path, body):
    from filament_kit.station import pair_apply
    f = _drop(tmp_path, body)
    with pytest.raises(pair_apply.DropError):
        pair_apply.read_drop(f)
    assert not f.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX links")
def test_the_root_side_never_follows_a_link_or_a_second_name(tmp_path):
    from filament_kit.station import pair_apply
    secret = tmp_path / "secret"
    secret.write_text(json.dumps(GOOD))
    d = tmp_path / "pair"
    d.mkdir()
    (d / "request.json").symlink_to(secret)
    with pytest.raises(pair_apply.DropError):
        pair_apply.read_drop(d / "request.json")
    os.link(secret, d / "request.json")
    with pytest.raises(pair_apply.DropError):
        pair_apply.read_drop(d / "request.json")
    assert secret.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX links")
def test_the_root_side_never_reads_or_removes_through_a_linked_pair_folder(tmp_path):
    from filament_kit.station import pair_apply
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "request.json").write_text(json.dumps(GOOD))
    state = tmp_path / "station-state"
    state.mkdir()
    (state / "pair").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(pair_apply.DropError, match="link"):
        pair_apply.read_drop(state / "pair" / "request.json")
    assert (elsewhere / "request.json").exists()            # neither read nor removed through the link
    assert not os.path.lexists(state / "pair")              # the link itself is gone, so the path unit stops


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX unlink of a folder")
def test_a_folder_in_place_of_the_drop_file_is_refused_and_removed(tmp_path):
    from filament_kit.station import pair_apply
    d = tmp_path / "pair" / "request.json"
    d.mkdir(parents=True)
    (d / "inside").write_text("x")
    with pytest.raises(pair_apply.DropError, match="plain file"):
        pair_apply.read_drop(d)
    assert not d.exists() and (tmp_path / "pair").is_dir()


def test_the_root_side_takes_the_address_from_station_allow_only(tmp_path):
    from filament_kit.station import pair_apply
    cfg = config.load()
    cfg["station"] = {**cfg.get("station", {}), "allow": []}
    config.save(cfg)
    f = _drop(tmp_path, {**GOOD, "host": "evil.example"})
    with pytest.raises(pair_apply.DropError, match="station.allow names no server"):
        pair_apply.apply_drop(f, refresh=lambda cfg: None)


def test_the_root_side_saves_nothing_when_the_token_does_not_answer(server, tmp_path):
    from filament_kit.station import pair_apply
    port, _ = server
    cfg = config.load()
    cfg["station"] = {**cfg.get("station", {}), "allow": ["127.0.0.1"]}
    config.save(cfg)
    fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
    f = _drop(tmp_path, {"fp": fp, "token": "n" * 43, "port": port})
    with pytest.raises(pair_apply.DropError, match="did not accept"):
        pair_apply.apply_drop(f, refresh=lambda cfg: None)
    assert not server_api.server_file().exists()


def test_the_units_and_the_drop_in():
    from filament_kit import apply, modules
    root = Path(__file__).resolve().parents[2] / "install" / "systemd"
    assert "PathExists=/var/lib/filament-kit-station/pair/request.json" in (root / "filament-kit-station-pair.path").read_text()
    assert "-m filament_kit.station.pair_apply" in (root / "filament-kit-station-pair.service").read_text()
    assert "StateDirectory=filament-kit-station" in (root / "filament-kit-station.service").read_text()
    assert "filament-kit-station-pair.path" in modules.MODULES["station"].units
    assert apply._unit_files("filament-kit-station-pair.path") == ["filament-kit-station-pair.path",
                                                                    "filament-kit-station-pair.service"]
    cfg = config.load()
    cfg["station"] = {**cfg.get("station", {}), "allow": ["kit.local"]}
    text = apply.station_dropin(cfg, ["192.0.2.5"])
    assert "STATION_SERVER=kit.local" in text and "STATION_SERVER_PORT=" in text


def test_the_screen_shows_the_code_and_the_idle_hint(monkeypatch):
    from filament_kit.station import flow, pair_request
    monkeypatch.setattr(flow, "api", lambda: type("A", (), {"paired": False})())
    monkeypatch.setitem(pair_request.status, "code", "123456")
    monkeypatch.setitem(flow.flow, "step", "pairing")
    rows = flow.screen()
    assert rows[0] == "Pair code" and rows[1] == "123 456" and "Devices" in rows[3]
    monkeypatch.setitem(flow.flow, "step", "idle")
    assert flow.screen()[1] == "Hold yellow to ask"
