"""AF1: the Hub's port (R82 section 1): first-install offer, the taken test, the capability drop-in, the refusals,
and the port change."""
import socket

import pytest

from filament_kit import apply, config, hubport, modules


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt", "bk", "root"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_BACKUPS", str(tmp_path / "bk"))
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    return tmp_path


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def states(**by_port):
    return lambda p: by_port.get(f"p{p}", hubport.FREE)


# ---- is a port taken (real sockets)

def test_a_free_port_is_free():
    assert hubport.port_state(free_port()) == hubport.FREE


def test_a_listener_on_any_address_makes_the_port_taken():
    for addr in ("0.0.0.0", "127.0.0.1"):
        s = socket.socket()
        s.bind((addr, 0))
        s.listen()
        try:
            assert hubport.port_state(s.getsockname()[1]) == hubport.TAKEN, addr
        finally:
            s.close()


@pytest.mark.skipif(not socket.has_ipv6, reason="no IPv6")
def test_an_ipv6_only_listener_makes_the_port_taken():
    s = socket.socket(socket.AF_INET6)
    s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    try:
        s.bind(("::1", 0))
    except OSError:
        pytest.skip("no IPv6 loopback")
    s.listen()
    try:
        assert hubport.port_state(s.getsockname()[1]) == hubport.TAKEN
    finally:
        s.close()


def test_the_table_alone_finds_a_listener(tmp_path, monkeypatch):
    (tmp_path / "net").mkdir()
    (tmp_path / "net" / "tcp").write_text(
        "  sl  local_address rem_address   st\n   0: 0100007F:01BB 00000000:0000 0A 0\n"
        "   1: 0100007F:0050 00000000:0000 01 0\n")
    monkeypatch.setattr(hubport, "PROC_NET", str(tmp_path / "net"))
    assert hubport.listening(443) is True
    assert hubport.listening(80) is False          # connected (01), not listening
    monkeypatch.setattr(hubport, "PROC_NET", str(tmp_path / "none"))
    assert hubport.listening(443) is None


def test_unsure_when_nothing_can_say(monkeypatch):
    monkeypatch.setattr(hubport, "PROC_NET", "/nonexistent")
    monkeypatch.setattr(hubport, "_probe", lambda family, port: "denied")
    assert hubport.port_state(443) == hubport.UNSURE
    monkeypatch.setattr(hubport, "_probe", lambda family, port: "ok")
    assert hubport.port_state(443) == hubport.FREE


# ---- offer

def test_443_free_is_taken_without_a_question():
    assert hubport.offer(False, state=states()) == ("free", 443)


def test_443_taken_offers_8710_and_says_why():
    assert hubport.offer(False, state=states(p443=hubport.TAKEN)) == ("taken", 8710)
    assert hubport.offer(False, state=states(p443=hubport.UNSURE)) == ("unsure", 8710)


def test_remote_access_gets_8710_even_when_443_is_free():
    assert hubport.offer(True, state=states()) == ("remote", 8710)


def test_8710_taken_too_offers_the_next_free_port():
    assert hubport.offer(False, state=states(p443=hubport.TAKEN, p8710=hubport.TAKEN)) == ("taken", 8711)


def test_open_point_1_switch(monkeypatch):
    monkeypatch.setattr(hubport, "REMOTE_EXCLUDES_HUB_443", False)
    assert hubport.offer(True, state=states()) == ("free", 443)
    assert hubport.remote_conflict({"port": 443}) is None


def test_station_offer():
    assert hubport.station_offer(True, state=states(p443=hubport.TAKEN)) == ("beside", 5003)
    assert hubport.station_offer(False, state=states()) == ("free", 443)
    assert hubport.station_offer(False, state=states(p443=hubport.TAKEN)) == ("taken", 5003)


# ---- a typed port

def test_a_typed_port_is_checked():
    t = states(p9000=hubport.TAKEN, p9001=hubport.UNSURE)
    assert hubport.check_port("9100", state=t) == (9100, "")
    assert hubport.check_port("abc", state=t)[0] is None
    assert "1024 to 65535" in hubport.check_port("80", state=t)[1]
    assert "1024 to 65535" in hubport.check_port("443", state=t)[1]      # the installer's question offers 443 itself
    assert hubport.check_port("443", allow_443=True, state=t)[0] == 443
    assert "use 443, or 1024" in hubport.check_port("80", allow_443=True, state=t)[1]
    assert "already in use" in hubport.check_port("9000", state=t)[1]
    assert "could not be checked" in hubport.check_port("9001", state=t)[1]
    assert hubport.check_port("9000", current=9000, state=t) == (9000, "")      # the Hub's own port


# ---- the drop-in and the address

def test_the_capability_drop_in_is_for_ports_below_1024_only():
    t = hubport.dropin_text(443)
    assert t == "[Service]\nCapabilityBoundingSet=CAP_NET_BIND_SERVICE\nAmbientCapabilities=CAP_NET_BIND_SERVICE\n"
    assert hubport.dropin_text(8710) is None and hubport.capability_lines(1024) == ""


def test_the_address_has_no_port_for_443():
    assert hubport.url_port(443) == "" and hubport.url_port(8710) == ":8710"


def test_remote_access_is_refused_while_the_hub_holds_443():
    cfg = config.load()
    cfg["port"] = 443
    cfg["modules"] = {n: n in {"server", "spoolman", "web", "remote"} for n in modules.MODULES}
    cfg["web"]["public_url"] = "https://x.example.com/f"
    with pytest.raises(modules.ModuleError) as e:
        modules.validate(cfg)
    assert "Remote access needs port 443, and the Hub is using it" in str(e.value)
    assert "sudo spoolwarden port 8710" in str(e.value)
    cfg["port"] = 8710
    modules.validate(cfg)


def test_the_firewall_names_the_real_port():
    assert hubport.firewall_ports({"port": 443}) == ["443/tcp", "5353/udp"]
    assert hubport.firewall_ports({}) == ["8710/tcp", "5353/udp"]


# ---- the drop-ins written by apply

def _ex(env):
    res = env / "res" / "avahi"
    res.mkdir(parents=True)
    (res / "filament-kit.service").write_text("<port>8710</port><port>8710</port>")
    return apply._Exec(lambda cmd: None, env / "res", env / "root")


def test_apply_writes_and_removes_the_hub_drop_in(env):
    ex = _ex(env)
    apply.write_hub_dropin(ex, 443)
    f = env / "root" / hubport.HUB_DROPIN.lstrip("/")
    assert f.read_text() == hubport.dropin_text(443)
    apply.write_hub_dropin(ex, 8710)
    assert not f.exists() and not f.parent.exists()
    apply.write_hub_dropin(ex, 8710)            # nothing to remove: no error


def test_the_station_drop_in_gets_the_capability_for_a_low_port():
    cfg = config.load()
    assert "CAP_NET_BIND_SERVICE" not in apply.station_dropin(cfg, ["127.0.0.1"])
    cfg["station"] = {"port": 443}
    assert apply.station_dropin(cfg, ["127.0.0.1"]).endswith(hubport.capability_lines(443))


# ---- the port change

def _hub(port=8710, modules_on=("server", "spoolman")):
    cfg = config.load()
    cfg["port"] = port
    cfg["modules"] = {n: n in modules_on for n in modules.MODULES}
    config.save(cfg)


def test_change_port_writes_everything_and_restarts(env, monkeypatch):
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(apply.shutil, "which", lambda name: None)       # no ufw note
    _hub()
    ran = []
    res = env / "opt" / "resources" / "avahi"
    res.mkdir(parents=True)
    (res / "filament-kit.service").write_text("<port>8710</port>")
    out = hubport.change_port("443", run=ran.append, root=env / "root", state=states())
    assert config.load()["port"] == 443
    assert (env / "root" / hubport.HUB_DROPIN.lstrip("/")).read_text() == hubport.dropin_text(443)
    assert ["systemctl", "restart", "filament-kit.service"] in ran or ["systemctl", "restart", "filament-kit.service"] \
        in [c for c in ran]
    assert "<port>443</port>" in (env / "root" / "etc/avahi/services/filament-kit.service").read_text()
    assert out[0] == "The Hub now uses port 443." and "Pair your phones" in out[1]


def test_change_port_refuses_before_changing_anything(env):
    _hub()
    with pytest.raises(hubport.PortError) as e:
        hubport.change_port("80", run=lambda c: pytest.fail("ran"), root=env / "root", state=states())
    assert "use 443, or 1024" in str(e.value)
    with pytest.raises(hubport.PortError):
        hubport.change_port("9000", run=lambda c: pytest.fail("ran"), root=env / "root",
                            state=states(p9000=hubport.TAKEN))
    assert config.load()["port"] == 8710


def test_change_port_to_443_is_refused_with_remote_access_on(env):
    _hub(modules_on=("server", "spoolman", "web", "remote"))
    cfg = config.load()
    cfg["web"]["public_url"] = "https://x.example.com/f"
    config.save(cfg)
    with pytest.raises(hubport.PortError) as e:
        hubport.change_port("443", run=lambda c: pytest.fail("ran"), root=env / "root", state=states())
    assert "Remote access" in str(e.value) and e.value.fix
    assert config.load()["port"] == 8710
