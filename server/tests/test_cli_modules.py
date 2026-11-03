"""filament-kit modules list/set/enable/disable and the config Modules menu (spec sections 3-4)."""
import io
import sys

import pytest

from filament_kit import apply, cli, config, modules


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_BACKUPS", str(tmp_path / "bk"))
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    (tmp_path / "etc").mkdir()
    (tmp_path / "state").mkdir()
    return tmp_path


@pytest.fixture
def applied(monkeypatch):
    """Patch plan/execute/finish; `applied` collects (cfg, pairing) per apply."""
    calls = []
    monkeypatch.setattr(apply, "plan", lambda cfg, **kw: calls.append(cfg) or [])
    monkeypatch.setattr(apply, "execute", lambda actions, **kw: None)
    monkeypatch.setattr(apply, "finish", lambda cfg, **kw: calls.append(("finish", kw.get("pairing", True))))
    return calls


def _stdin(monkeypatch, text, tty=False):
    s = io.StringIO(text)
    s.isatty = lambda: tty
    monkeypatch.setattr(sys, "stdin", s)


def test_modules_list_shows_mode(capsys):
    assert cli.main(["modules", "list"]) == 0
    out = capsys.readouterr().out
    assert "spoolman" in out and "on" in out and "station" in out and "off" in out
    assert out.strip().splitlines()[-1] == "mode: server"


def test_modules_set_all_in_one_saves_and_applies(applied):
    assert cli.main(["modules", "set", "all-in-one"]) == 0
    cfg = config.load()
    assert cfg["modules"] == {n: n not in modules.OPT_IN or n == "ai_intake" for n in modules.MODULES}  # legacy cfg: AI kept
    assert cfg["station"]["url"] == "http://127.0.0.1:5003"
    assert cfg["station"]["allow"] == ["127.0.0.1"]
    assert applied[0]["modules"]["station"] is True
    assert ("finish", False) in applied  # Ruling H: no pairing QR


def test_modules_apply_keeps_pairing(applied):
    assert cli.main(["modules", "apply"]) == 0
    assert ("finish", True) in applied


def test_disable_with_dependents_noninteractive_fails(applied, capsys, monkeypatch):
    _stdin(monkeypatch, "")
    assert cli.main(["modules", "disable", "server"]) == 1
    err = capsys.readouterr().err
    assert "fix: disable ai_intake, printers, presets first" in err
    assert applied == []
    assert "modules" not in config.load()


def test_disable_with_dependents_tty_asks(applied, monkeypatch):
    # server-less needs a remote Spoolman (validate)
    cfg = config.load()
    cfg["spoolman_url"] = "http://spoolman.example:7912"
    config.save(cfg)
    _stdin(monkeypatch, "y\n", tty=True)
    assert cli.main(["modules", "disable", "server"]) == 0
    mods = config.load()["modules"]
    assert mods["server"] is False and mods["printers"] is False and mods["ai_intake"] is False
    assert mods["spoolman"] is True and len(mods) == len(modules.MODULES)


def test_enable_with_dependency_off_fails(applied, capsys, monkeypatch):
    _stdin(monkeypatch, "")
    config.save(modules.set_mode(config.load(), "station"))
    assert cli.main(["modules", "enable", "printers"]) == 1
    assert "fix: enable server first" in capsys.readouterr().err


def test_enable_station_with_server_on_links_locally(applied):
    assert cli.main(["modules", "enable", "station"]) == 0
    cfg = config.load()
    assert cfg["modules"]["station"] is True
    assert cfg["station"]["url"] == "http://127.0.0.1:5003"
    assert cfg["station"]["allow"] == ["127.0.0.1"]


def test_unknown_module_fails(applied, capsys):
    assert cli.main(["modules", "enable", "nope"]) == 1
    assert "unknown module" in capsys.readouterr().err


def test_config_menu_toggle_printers_then_apply(applied, monkeypatch):
    # 6 Modules, 4 = printers (server mode has it on), 0 back, 0 save and exit
    _stdin(monkeypatch, "6\n4\n0\n0\n")
    assert cli.main(["config"]) == 0
    assert config.load()["modules"]["printers"] is False
    assert len(config.load()["modules"]) == len(modules.MODULES)
    assert applied[0]["modules"]["printers"] is False
    assert ("finish", False) in applied


def test_config_menu_no_module_change_does_not_apply(applied, monkeypatch):
    _stdin(monkeypatch, "6\n0\n0\n")
    cli.main(["config"])
    assert applied == []
    assert "modules" not in config.load()


def test_config_menu_station_on_asks_address_and_refuses_range(applied, monkeypatch, capsys):
    config.save(modules.set_mode(config.load(), "station"))
    # custom: station on, server off -> turn spoolman on (1) is irrelevant; use station-only then toggle backup
    cfg = config.load()
    cfg["modules"]["station"] = False
    cfg["modules"]["backup"] = True
    config.save(cfg)
    # 8 = station: range refused, then a single address accepted
    _stdin(monkeypatch, "6\n8\n192.168.1.0/24\n192.168.1.5\n0\n0\n")
    assert cli.main(["config"]) == 0
    out = capsys.readouterr().out
    assert "single address" in out
    cfg = config.load()
    assert cfg["modules"]["station"] is True
    assert cfg["station"]["allow"] == ["192.168.1.5"]


def test_config_menu_choose_mode(applied, monkeypatch):
    _stdin(monkeypatch, "6\nm\n3\n0\n0\n")  # 3 = all-in-one
    cli.main(["config"])
    assert config.load()["modules"] == {n: n not in modules.OPT_IN or n == "ai_intake" for n in modules.MODULES}  # legacy cfg: AI kept
    assert config.load()["station"]["url"] == "http://127.0.0.1:5003"


def test_non_root_changes_nothing(applied, monkeypatch, capsys):
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000, raising=False)
    for argv in (["modules", "set", "all-in-one"], ["modules", "enable", "station"],
                 ["modules", "disable", "library"]):
        assert cli.main(argv) == 1
        assert "run as root" in capsys.readouterr().err
    assert "modules" not in config.load()
    assert applied == []


def test_set_station_without_address_fails(applied, capsys):
    assert cli.main(["modules", "set", "station"]) == 1
    err = capsys.readouterr().err
    assert "fix:" in err and "--server" in err
    assert "modules" not in config.load() and applied == []


def test_set_station_with_server(applied):
    assert cli.main(["modules", "set", "station", "--server", "kit.localdomain"]) == 0
    cfg = config.load()
    assert cfg["station"]["allow"] == ["kit.localdomain"]
    assert cfg["modules"]["station"] is True and cfg["modules"]["server"] is False


def test_set_station_refuses_range(applied, capsys):
    assert cli.main(["modules", "set", "station", "--server", "10.0.0.0/24"]) == 1
    assert "single address" in capsys.readouterr().err


def test_enable_station_with_existing_allow(applied):
    cfg = config.load()
    cfg["modules"] = {n: n in ("backup",) for n in modules.MODULES}
    cfg["station"]["allow"] = ["192.0.2.10"]
    config.save(cfg)
    assert cli.main(["modules", "enable", "station"]) == 0
    assert config.load()["station"]["allow"] == ["192.0.2.10"]


def test_enable_station_server_off_needs_address(applied, capsys):
    cfg = config.load()
    cfg["modules"] = {n: n == "backup" for n in modules.MODULES}
    config.save(cfg)
    assert cli.main(["modules", "enable", "station"]) == 1
    assert cli.main(["modules", "enable", "station", "--server", "10.0.0.5"]) == 0
    assert config.load()["station"]["allow"] == ["10.0.0.5"]


def test_disable_station_after_all_in_one_drops_local_url(applied):
    config.save(modules.set_mode(config.load(), "all-in-one"))
    assert cli.main(["modules", "disable", "station"]) == 0
    assert config.load()["station"].get("url") is None


def test_config_menu_mode_server_after_all_in_one_drops_local_url(applied, monkeypatch):
    config.save(modules.set_mode(config.load(), "all-in-one"))
    _stdin(monkeypatch, "6\nm\n1\n0\n0\n")  # 1 = server
    assert cli.main(["config"]) == 0
    assert config.load()["station"].get("url") is None


def test_disable_station_keeps_remote_url(applied):
    cfg = config.load()
    cfg["station"]["url"] = "http://station.localdomain:5003"
    config.save(cfg)
    assert cli.main(["modules", "disable", "library"]) == 0
    assert config.load()["station"]["url"] == "http://station.localdomain:5003"


def _real_plan_fake_apply(monkeypatch):
    """Real plan (validate + resolve); execute/finish recorded; name resolution always fails."""
    import socket
    def nope(*a, **kw):
        raise socket.gaierror(-2, "Name or service not known")
    monkeypatch.setattr(apply.socket, "getaddrinfo", nope)
    ran = []
    monkeypatch.setattr(apply, "execute", lambda actions, **kw: ran.append(actions))
    monkeypatch.setattr(apply, "finish", lambda cfg, **kw: None)
    return ran


def test_set_refused_by_plan_leaves_config_untouched(monkeypatch, capsys):
    ran = _real_plan_fake_apply(monkeypatch)
    before = (config.paths().etc / "config.json").read_bytes() if (config.paths().etc / "config.json").exists() else None
    assert cli.main(["modules", "set", "station", "--server", "badname"]) == 1
    err = capsys.readouterr().err
    assert "cannot resolve" in err and "fix:" in err
    after = (config.paths().etc / "config.json").read_bytes() if (config.paths().etc / "config.json").exists() else None
    assert after == before and ran == []


def test_enable_refused_by_plan_leaves_config_untouched(monkeypatch, capsys):
    cfg = config.load()
    cfg["modules"] = {n: n == "backup" for n in modules.MODULES}
    config.save(cfg)
    before = (config.paths().etc / "config.json").read_bytes()
    ran = _real_plan_fake_apply(monkeypatch)
    assert cli.main(["modules", "enable", "station", "--server", "badname"]) == 1
    assert "fix:" in capsys.readouterr().err
    assert (config.paths().etc / "config.json").read_bytes() == before and ran == []


def test_config_menu_refused_by_plan_leaves_config_untouched(monkeypatch, capsys):
    config.save(config.load())
    before = (config.paths().etc / "config.json").read_bytes()
    ran = _real_plan_fake_apply(monkeypatch)
    _stdin(monkeypatch, "6\nm\n2\nbadname\n0\n0\n")  # 2 = station mode, server "badname"
    assert cli.main(["config"]) == 1
    assert "fix:" in capsys.readouterr().err
    assert (config.paths().etc / "config.json").read_bytes() == before and ran == []
