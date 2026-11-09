"""Klipper discovery (mDNS + on-demand scan) and the `filament-kit klipper` commands."""
import ipaddress
import json
import socket
from pathlib import Path

import pytest

from filament_kit import config, klipper_cli
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


# ---------- detect(p) (the web console's data; console-printers stage) and the CLI's output, pinned ----------

def _detect_cli(moonraker, capsys, *argv):
    rc = klipper_cli.main(list(argv))
    out, err = capsys.readouterr()
    return rc, out.replace(str(moonraker.port), "PORT"), err


def test_cli_detect_output_is_unchanged(moonraker, capsys):
    """The exact text `klipper add` / `detect` printed before detect(p) existed (snapshot, 2026-11-08)."""
    moonraker.objects = json.loads((DATA / "SV08-MAX" / "objects.json").read_text())["objects"]
    moonraker.hostname = "SV08MAX"
    assert _detect_cli(moonraker, capsys, "add", "SV08 MAX", moonraker.host, "--port", str(moonraker.port)) == (
        0, "added SV08 MAX as sv08-max (127.0.0.1:PORT)\n  model: Sovol SV08 MAX (SOVOL-SV08-MAX)\n"
           "  filament system: single; slots: T0\n    object gcode_macro DEMON_START\n    hostname SV08MAX*\n", "")
    moonraker.objects = ["print_stats", "gcode_macro FK_UNVERIFIED_M1D"]
    assert _detect_cli(moonraker, capsys, "detect", "sv08-max") == (
        0, "SV08 MAX (127.0.0.1:PORT)\n  model: Sovol M1D (sovol-m1d) - unverified entry\n"
           "  filament system: tool-macros; slots: L, C1, C2, C3, C4, C5, C6\n"
           "    object gcode_macro FK_UNVERIFIED_M1D\n", "")
    moonraker.objects = ["print_stats", "AFC", "AFC_stepper lane1"]
    assert _detect_cli(moonraker, capsys, "detect", "sv08-max") == (
        0, "SV08 MAX (127.0.0.1:PORT)\n  model: Klipper printer (generic)\n  filament system: afc; slots: from the "
           "printer\n    no model entry matched: generic Klipper printer\n    filament system afc (object AFC)\n", "")
    moonraker.api_key = "k"
    assert _detect_cli(moonraker, capsys, "detect", "sv08-max") == (
        0, "SV08 MAX (127.0.0.1:PORT)\n  127.0.0.1:PORT wants a Moonraker API key: run "
           "`filament-kit klipper api-key sv08-max`\n", "")


def test_cli_detect_offline_output_is_unchanged(capsys):
    registry.add_klipper("Gone", "127.0.0.1", 9)
    rc = klipper_cli.main(["detect", "gone"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("Gone (127.0.0.1:9)\n  Moonraker at 127.0.0.1:9 is not answering (")
    assert out.endswith("); the server keeps trying once it runs\n") and out.count("\n") == 2


def test_detect_returns_what_the_cli_prints(moonraker):
    moonraker.objects = ["print_stats", "AFC", "AFC_stepper lane1"]
    p = registry.add_klipper("Box", moonraker.host, moonraker.port)
    d = klipper_cli.detect(p, kit_spoolman="http://spoolman.example.com:7912")
    assert d == {"ok": True, "problem": None, "message": "", "id": "box", "host": moonraker.host,
                 "port": moonraker.port, "model_key": "generic", "model": "Klipper printer", "verified": True,
                 "system": "afc", "slots": [],
                 "reasons": ["no model entry matched: generic Klipper printer", "filament system afc (object AFC)"],
                 "hostname": moonraker.hostname or "",
                 "spoolman": {"server": "spoolman.example.com:7912", "same_as_kit": True, "match": "same",
                              "connected": True, "warning": None}}


def test_detect_spoolman_another_or_none(moonraker):
    p = registry.add_klipper("Box", moonraker.host, moonraker.port)
    d = klipper_cli.detect(p, kit_spoolman="http://other.example.com:7912")
    assert d["spoolman"]["match"] in ("different", "unknown") and d["spoolman"]["same_as_kit"] is False
    assert d["spoolman"]["server"] == "spoolman.example.com:7912"
    moonraker.server_config = {}
    d = klipper_cli.detect(p, kit_spoolman="http://other.example.com:7912")
    assert d["spoolman"] == {"server": None, "same_as_kit": False, "match": None, "connected": True,
                             "warning": "Moonraker does not report usage to Spoolman (no [spoolman] section)"}
    moonraker.server_config = {"spoolman": {"server": "http://user:pw@spoolman.example.com:7912"}}
    d = klipper_cli.detect(p, kit_spoolman="http://spoolman.example.com:7912")
    assert d["spoolman"]["server"] == "spoolman.example.com:7912" and "pw" not in json.dumps(d)


@pytest.mark.parametrize("server, address", [
    ("http://fkuser:hunter/w@spoolman.example.com:7912", "spoolman.example.com:7912"),
    ("http://fkuser:hunter#w@spoolman.example.com:7912", "spoolman.example.com:7912"),
    ("http://fkuser:hunter?w@spoolman.example.com:7912", "spoolman.example.com:7912"),
    ("http://fkuser:hunter@w@spoolman.example.com:7912", "spoolman.example.com:7912"),
    ("http://fkuser:hunter@spoolman.example.com:notaport", None),
    ("fkuser:hunter@spoolman.example.com:7912", None),
    ("http://fkuser:hunter@[bad:7912", None),
    # an @ after a / ? or # where what comes before reads as host:port: a path or a password? Can't tell, so unreadable
    ("http://fkuser:123/hunter@spoolman.example.com:7912", None),
    ("http://spoolman.example.com:7912/hunter@b", None),
    ("http://spoolman.example.com:7912/?token=hunter@ret", None),
    ("http://fkuser:hunter@spoolman.example.com:7912/hunter@b", None),
    # all before the first /: everything up to the last @ is credentials, as a URL parser reads it
    ("http://fkuser:hunter@spoolman.example.com:7912@notport", "notport:80"),
    # a host getaddrinfo can't even encode: shown as it is, never an exception
    ("http://a..b:7912", "a..b:7912"),
    (f"http://{'a' * 70}.example.com:7912", f"{'a' * 70}.example.com:7912"),
])
def test_detect_never_returns_a_spoolman_password(moonraker, server, address, monkeypatch):
    real = socket.getaddrinfo     # only the fake printer's own address resolves: no real lookups of these names

    def lookup(host, *a, **kw):
        if host in ("127.0.0.1", socket.gethostname()):
            return real(host, *a, **kw)
        if host == "a..b" or len(host) > 63:
            raise UnicodeError("label")
        return [(0, 0, 0, "", ("192.0.2." + str(30 if host == "other.example.com" else 40), 0))]
    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    moonraker.server_config = {"spoolman": {"server": server}}
    p = registry.add_klipper("Box", moonraker.host, moonraker.port)
    d = klipper_cli.detect(p, kit_spoolman="http://other.example.com:7912")
    text = json.dumps(d)
    assert "hunter" not in text and "fkuser" not in text
    assert d["spoolman"]["server"] == address
    if address is None:
        assert d["spoolman"]["warning"] == ("Moonraker's [spoolman] server address cannot be read; usage may not "
                                            "reach this Spoolman")
    else:
        assert address in d["spoolman"]["warning"]


def test_detect_spoolman_not_connected(moonraker):
    moonraker.spoolman["spoolman_connected"] = False
    p = registry.add_klipper("Box", moonraker.host, moonraker.port)
    s = klipper_cli.detect(p, kit_spoolman="http://spoolman.example.com:7912")["spoolman"]
    assert s["connected"] is False and s["match"] == "same"
    assert s["warning"] == "Moonraker cannot reach its Spoolman: usage is not getting there"


def test_detect_brackets_an_ipv6_spoolman(moonraker):
    moonraker.server_config = {"spoolman": {"server": "http://[fd00::1]:7912"}}
    p = registry.add_klipper("Box", moonraker.host, moonraker.port)
    s = klipper_cli.detect(p, kit_spoolman="http://[fd00::2]:7912")["spoolman"]
    assert s["server"] == "[fd00::1]:7912" and s["same_as_kit"] is False
    assert s["warning"] == "usage goes to another Spoolman: [fd00::1]:7912"


ODD_CONFIGS = [{"spoolman": "x"}, {"spoolman": ["a"]}, "abc", ["a"], 5]


@pytest.mark.parametrize("answer", ODD_CONFIGS)
def test_detect_odd_server_config_is_not_known(moonraker, answer):
    moonraker.server_config = answer
    p = registry.add_klipper("Box", moonraker.host, moonraker.port)
    d = klipper_cli.detect(p, kit_spoolman="http://other.example.com:7912")
    assert d["ok"] is True and d["problem"] is None and d["spoolman"] is None


def test_detect_unreadable_config_is_not_known(moonraker):
    (config.paths().etc / "config.json").write_text("{not json", encoding="utf-8")
    p = registry.add_klipper("Box", moonraker.host, moonraker.port)
    d = klipper_cli.detect(p)
    assert d["ok"] is True and d["problem"] is None and d["spoolman"] is None


def test_detect_without_spoolman_asks_nothing_about_it(moonraker, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("the Spoolman lookup ran")
    monkeypatch.setattr(klipper_cli.Moonraker, "server_config", boom)
    monkeypatch.setattr(klipper_cli.config, "load", boom)
    p = registry.add_klipper("Box", moonraker.host, moonraker.port)
    d = klipper_cli.detect(p, spoolman=False)
    assert d["ok"] is True and d["spoolman"] is None


@pytest.mark.parametrize("answer", ODD_CONFIGS)
def test_cli_add_and_detect_do_not_care_about_the_spoolman(moonraker, capsys, answer):
    """`klipper add` / `detect` print the model only; a broken config.json or /server/config must not stop them."""
    moonraker.server_config = answer
    (config.paths().etc / "config.json").write_text("{not json", encoding="utf-8")
    moonraker.objects = ["print_stats", "AFC", "AFC_stepper lane1"]
    want = "  model: Klipper printer (generic)\n  filament system: afc; slots: from the printer\n" \
           "    no model entry matched: generic Klipper printer\n    filament system afc (object AFC)\n"
    assert _detect_cli(moonraker, capsys, "add", "Box", moonraker.host, "--port", str(moonraker.port)) == (
        0, f"added Box as box (127.0.0.1:PORT)\n{want}", "")
    assert _detect_cli(moonraker, capsys, "detect", "box") == (0, f"Box (127.0.0.1:PORT)\n{want}", "")


def test_detect_problems(moonraker):
    moonraker.api_key = "MOONRAKER-KEY-EXAMPLE"
    p = registry.add_klipper("Box", moonraker.host, moonraker.port)
    d = klipper_cli.detect(p)
    assert (d["ok"], d["problem"]) == (False, "api_key") and "klipper api-key box" in d["message"]
    registry.set_api_key("box", "MOONRAKER-KEY-EXAMPLE")
    d = klipper_cli.detect(registry.load()["box"])
    assert d["ok"] is True and "MOONRAKER-KEY-EXAMPLE" not in json.dumps(d)
    gone = registry.add_klipper("Gone", "127.0.0.1", 9)
    d = klipper_cli.detect(gone)
    assert (d["ok"], d["problem"]) == (False, "offline") and "not answering" in d["message"]
    assert d["model_key"] is None and d["spoolman"] is None


def test_klipper_add_cli_says_it_is_already_added(capsys):
    registry.add_klipper("Voron", "voron.home.arpa")
    args = type("A", (), {"klipper_cmd": "add", "name": "Again", "host": "voron.home.arpa", "port": 7125})
    assert klipper_cli.run(args) == 1
    assert "Voron" in capsys.readouterr().err
