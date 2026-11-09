"""Klipper discovery (mDNS + on-demand scan) and the `filament-kit klipper` commands."""
import ipaddress
import json
from pathlib import Path

import pytest

from filament_kit import klipper_cli
from filament_kit.bridge import registry
from filament_kit.bridge.klipper import discovery
from filament_kit.bridge.klipper import hardware as kh

DATA = Path(__file__).parent / "data" / "klipper"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    kh._reset_cache()
    yield
    kh._reset_cache()


def test_scan_finds_fake_on_localhost(moonraker):
    found = discovery.scan(ipaddress.ip_network("127.0.0.1/32"), port=moonraker.port, timeout=0.5)
    assert found == [("127.0.0.1", moonraker.port)]


def test_scan_skips_a_port_that_is_not_moonraker(moonraker):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    try:
        assert discovery.scan(ipaddress.ip_network("127.0.0.1/32"), port=s.getsockname()[1], timeout=0.5) == []
    finally:
        s.close()


def test_scan_refuses_big_subnet():
    with pytest.raises(ValueError, match="at most a /24"):
        discovery.scan(ipaddress.ip_network("10.0.0.0/16"))


def test_own_subnet_is_a_24():
    n = discovery.own_subnet()
    assert n is None or n.prefixlen == 24


def test_detected_klipper_records_once():
    a = registry.detected_klipper("printer.home.arpa", 7125, "SV08MAX")
    b = registry.detected_klipper("printer.home.arpa", 7125, "SV08MAX")
    assert a.serial == b.serial and len(registry.load()) == 1
    p = registry.load()[a.serial]
    assert (p.family, p.configured, p.host) == ("klipper", False, "printer.home.arpa")
    c = registry.add_klipper("Mine", "other.home.arpa")
    assert registry.detected_klipper("other.home.arpa", 7125, "x").serial == c.serial    # known: not duplicated
    assert registry.load()[c.serial].configured is True


def test_browser_callback_records_detected():
    class Info:
        server = "sv08max.local."
        port = 7125

        def parsed_addresses(self):
            return ["192.0.2.10"]
    seen = []
    b = discovery.Browser(lambda host, port, name: seen.append((host, port, name)))
    b._found(Info(), "SV08MAX._moonraker._tcp.local.")
    assert seen == [("192.0.2.10", 7125, "SV08MAX")]


def test_cli_add_and_detect(moonraker, capsys):
    moonraker.objects = json.loads((DATA / "SV08-MAX" / "objects.json").read_text())["objects"]
    moonraker.hostname = "SV08MAX"
    assert klipper_cli.main(["add", "SV08 MAX", moonraker.host, "--port", str(moonraker.port)]) == 0
    out = capsys.readouterr().out
    assert "Sovol SV08 MAX" in out and "sv08-max" in out
    assert registry.load()["sv08-max"].family == "klipper"
    moonraker.objects = ["print_stats", "gcode_macro FK_UNVERIFIED_M1D"]
    assert klipper_cli.main(["detect", "sv08-max"]) == 0
    assert "unverified" in capsys.readouterr().out


def test_cli_add_offline_still_adds(capsys):
    assert klipper_cli.main(["add", "Gone", "127.0.0.1", "--port", "9"]) == 0
    assert "not answering" in capsys.readouterr().out
    assert "gone" in registry.load()


def test_cli_api_key_not_echoed(capsys, monkeypatch):
    registry.add_klipper("P", "h")
    monkeypatch.setattr(klipper_cli, "getpass", lambda prompt="": "s3cretkey")
    assert klipper_cli.main(["api-key", "p"]) == 0
    assert "s3cretkey" not in capsys.readouterr().out
    assert registry.load()["p"].api_key == "s3cretkey"


def test_cli_set_lane_data(capsys):
    registry.add_klipper("P", "h")
    assert klipper_cli.main(["set", "p", "--lane-data", "on"]) == 0
    assert registry.load()["p"].lane_data == "on"
    assert klipper_cli.main(["set", "nope", "--lane-data", "on"]) == 1


def test_cli_scan(moonraker, capsys, monkeypatch):
    monkeypatch.setattr(discovery, "DEFAULT_PORT", moonraker.port)
    monkeypatch.setattr(discovery.scan, "__defaults__", (None, 64, 5.0))   # what the command does, not how fast a crowd lets it
    assert klipper_cli.main(["scan", "--subnet", "127.0.0.1/32"]) == 0
    assert "127.0.0.1" in capsys.readouterr().out
    assert any(p.host == "127.0.0.1" and not p.configured for p in registry.load().values())
