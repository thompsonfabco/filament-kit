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
    rows = {line.split()[0]: line.split()[1] for line in out.strip().splitlines()[:-1]}
    assert rows["spoolman"] == "on" and rows["station"] == "off"
    assert out.strip().splitlines()[-1] == "mode: server"


def test_modules_set_all_in_one_saves_and_applies(applied):
    assert cli.main(["modules", "set", "all-in-one"]) == 0
    cfg = config.load()
    assert cfg["modules"] == {n: n not in modules.OPT_IN or n in ("ai_intake", "library") for n in modules.MODULES
                              if n not in modules.NEWER}  # legacy cfg: AI kept; klipper never named stays out
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
    assert "fix: disable presets, printers, ai_intake first" in err
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
    assert mods["spoolman"] is True and set(mods) == set(modules.MODULES) - set(modules.NEWER)


def _deep():
    """Server, with what hangs off it two and three levels down."""
    cfg = config.load()
    cfg["spoolman_url"] = "http://spoolman.example:7912"
    for n in ("ai_intake", "orders", "web", "remote"):
        cfg.setdefault("modules", {n2: n2 in modules.MODES["server"] for n2 in modules.MODULES})[n] = True
    cfg["web"] = {**cfg["web"], "public_url": "https://printer.example.com/filament"}
    cfg["orders"] = {"file": None}
    config.save(cfg)


def test_disable_names_the_whole_set_before_asking(applied, capsys, monkeypatch):
    _deep()
    _stdin(monkeypatch, "")
    assert cli.main(["modules", "disable", "server"]) == 1
    err = capsys.readouterr().err
    for n in ("ai_intake", "orders", "printers", "presets", "web", "remote"):
        assert n in err.split("fix:")[1], n


def test_disable_after_a_yes_does_what_it_said(applied, capsys, monkeypatch):
    _deep()
    asked = []
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: asked.append(q) or True)
    assert cli.main(["modules", "disable", "server"]) == 0
    mods = config.load()["modules"]
    for n in ("server", "ai_intake", "orders", "printers", "presets", "web", "remote"):
        assert mods[n] is False, n
    for n in ("orders", "remote"):
        assert n in asked[0], n


def test_enable_at_a_terminal_offers_what_it_needs_all_the_way_down(applied, monkeypatch):
    config.save(modules.set_mode(config.load(), "station"))
    cfg = config.load()
    cfg["spoolman_url"] = "http://spoolman.example:7912"
    config.save(cfg)
    asked = []
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: asked.append(q) or True)
    assert cli.main(["modules", "enable", "printers"]) == 0
    assert "server" in asked[0] and config.load()["modules"]["server"] is True


def _terminal(monkeypatch, *answers):
    """A terminal that says yes to the offer and gives these answers to the settings; returns what was asked."""
    asked, left = [], list(answers)
    monkeypatch.setattr(cli.apply, "_tty", lambda: True)
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: True)
    monkeypatch.setattr(cli, "_ask", lambda q: asked.append(q) or (left.pop(0) if left else None))
    return asked


def test_the_offer_goes_on_to_ask_for_what_the_new_set_needs(applied, capsys, monkeypatch):
    cfg = config.load()
    cfg.setdefault("web", {}).pop("public_url", None)
    config.save(cfg)
    asked = _terminal(monkeypatch, "https://printer.example.com/filament")
    assert cli.main(["modules", "enable", "remote"]) == 0, capsys.readouterr().err
    after = config.load()
    assert after["modules"]["remote"] is True and after["modules"]["web"] is True
    assert after["web"]["public_url"] == "https://printer.example.com/filament" and "public" in asked[0]
    assert "now on too" in capsys.readouterr().out


def test_the_offer_asks_for_the_order_file_too(applied, capsys, monkeypatch):
    asked = _terminal(monkeypatch, "/data/orders.csv")
    assert cli.main(["modules", "enable", "orders"]) == 0, capsys.readouterr().err
    after = config.load()
    assert after["modules"]["orders"] is True and after["modules"]["ai_intake"] is True
    assert after["orders"]["file"] == "/data/orders.csv" and "order" in asked[0]


def test_the_offer_on_a_station_asks_for_the_spoolman_to_use(applied, capsys, monkeypatch):
    cfg = modules.set_mode(config.load(), "station")
    cfg["station"]["allow"] = ["printer.example.com"]
    cfg.pop("spoolman_url", None)
    config.save(cfg)
    asked = _terminal(monkeypatch, "not an address", "http://spoolman.example:7912")
    assert cli.main(["modules", "enable", "printers"]) == 0, capsys.readouterr().err
    after = config.load()
    assert after["modules"]["printers"] is True and after["modules"]["server"] is True
    assert after["spoolman_url"] == "http://spoolman.example:7912" and "Spoolman" in asked[0] and len(asked) == 2


def test_a_blank_answer_changes_nothing_and_says_nothing_was_turned_on(applied, capsys, monkeypatch):
    before = config.load()
    _terminal(monkeypatch)
    assert cli.main(["modules", "enable", "orders"]) == 1
    out = capsys.readouterr()
    assert "Turned on" not in out.out and "nothing was changed" in out.err
    assert config.load() == before and applied == []


def test_a_change_the_plan_refuses_never_says_it_happened(applied, capsys, monkeypatch):
    _deep()
    before = config.load()
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: True)
    monkeypatch.setattr(cli, "_plan_error", lambda cfg: "name does not resolve")
    assert cli.main(["modules", "disable", "server"]) == 1
    out = capsys.readouterr()
    assert "Turned off" not in out.out and "Nothing was changed" in out.err
    assert config.load() == before and applied == []


def test_the_fix_line_can_be_followed_in_the_order_it_gives(applied, capsys, monkeypatch):
    _deep()
    _stdin(monkeypatch, "")
    assert cli.main(["modules", "disable", "server"]) == 1
    listed = capsys.readouterr().err.split("fix: disable ")[1].split(" first")[0].split(", ")
    assert listed.index("orders") < listed.index("ai_intake") and listed.index("remote") < listed.index("web")


def test_enable_at_a_terminal_refused_changes_nothing(applied, capsys, monkeypatch):
    config.save(modules.set_mode(config.load(), "station"))
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: False)
    assert cli.main(["modules", "enable", "printers"]) == 1
    assert "fix: enable server first" in capsys.readouterr().err and applied == []


def test_every_way_of_switching_says_it_in_the_same_words(applied, capsys, monkeypatch):
    _deep()
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: True)
    before = modules.enabled(config.load())
    _new, notes = modules.toggle(before, "server")
    assert cli.main(["modules", "disable", "server"]) == 0
    assert notes[0] in capsys.readouterr().out


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
    # 6 Modules, 4 = printers (server mode has it on), Enter applies the checklist, 0 save and exit
    _stdin(monkeypatch, "6\n4\n\n0\n")
    assert cli.main(["config"]) == 0
    assert config.load()["modules"]["printers"] is False
    assert set(config.load()["modules"]) == set(modules.MODULES) - set(modules.NEWER)
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
    _stdin(monkeypatch, "6\n8\n\n192.168.1.0/24\n192.168.1.5\n0\n")
    assert cli.main(["config"]) == 0
    out = capsys.readouterr().out
    assert "single address" in out
    cfg = config.load()
    assert cfg["modules"]["station"] is True
    assert cfg["station"]["allow"] == ["192.168.1.5"]


def test_config_menu_choose_mode(applied, monkeypatch):
    _stdin(monkeypatch, "6\na\n\n0\n")  # a = all-in-one preset
    cli.main(["config"])
    assert config.load()["modules"] == {n: n not in modules.OPT_IN or n in ("ai_intake", "library") for n in modules.MODULES
                              if n not in modules.NEWER}  # legacy cfg: AI kept; klipper never named stays out
    assert config.load()["station"]["url"] == "http://127.0.0.1:5003"


def test_modules_menu_raw_prints_choice_only_on_stdout(monkeypatch, capsys):
    _stdin(monkeypatch, "t\n1\n\n192.168.1.5\n")   # station preset, spoolman on, Enter, the server's address
    assert cli.main(["modules", "menu", "--raw"]) == 0
    cap = capsys.readouterr()
    assert cap.out.splitlines() == ["spoolman,station", "set station.allow=192.168.1.5"]
    assert "[x]" in cap.err and "OPTIONAL AI" in cap.err
    assert "modules" not in config.load()          # --raw changes nothing


def test_modules_menu_raw_cancel(monkeypatch, capsys):
    _stdin(monkeypatch, "q\n")
    assert cli.main(["modules", "menu", "--raw"]) == 1
    assert capsys.readouterr().out == ""


def test_config_menu_turning_on_remote_pulls_web_and_says_so(applied, monkeypatch, capsys):
    cfg = config.load()
    cfg["web"] = {"public_url": "https://mcp.example.com/filament", "lan": ["192.168.1.0/24"]}
    config.save(cfg)
    n = list(modules.MODULES).index("remote") + 1
    _stdin(monkeypatch, f"6\n{n}\n\n0\n")
    assert cli.main(["config"]) == 0
    assert "now on too" in capsys.readouterr().out
    assert config.load()["modules"]["web"] is True and config.load()["modules"]["remote"] is True


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
    assert cli.main(["modules", "set", "station", "--server", "kit.example.lan"]) == 0
    cfg = config.load()
    assert cfg["station"]["allow"] == ["kit.example.lan"]
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
    _stdin(monkeypatch, "6\ns\n\n0\n")  # s = server preset
    assert cli.main(["config"]) == 0
    assert config.load()["station"].get("url") is None


def test_disable_station_keeps_remote_url(applied):
    cfg = config.load()
    cfg["station"]["url"] = "http://station.example.lan:5003"
    config.save(cfg)
    assert cli.main(["modules", "disable", "library"]) == 0
    assert config.load()["station"]["url"] == "http://station.example.lan:5003"


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
    _stdin(monkeypatch, "6\nt\n\nbadname\n0\n")  # t = station preset, server "badname"
    assert cli.main(["config"]) == 1
    assert "fix:" in capsys.readouterr().err
    assert (config.paths().etc / "config.json").read_bytes() == before and ran == []


def test_modules_menu_raw_revalidates_and_reshows(monkeypatch, capsys):
    # default server mode: 1 = spoolman off leaves a server with no Spoolman -> error, menu again, 1 back on
    _stdin(monkeypatch, "1\n\n1\n\n")
    assert cli.main(["modules", "menu", "--raw"]) == 0
    cap = capsys.readouterr()
    assert "spoolman_url" in cap.err
    assert "spoolman" in cap.out.split(",")


def _n(name):
    return list(modules.MODULES).index(name) + 1


def test_raw_menu_asks_web_and_orders_settings(monkeypatch, capsys):
    # web: a non-https answer is refused, then accepted; orders: the file path
    _stdin(monkeypatch, f"{_n('web')} {_n('orders')}\n\nhttp://x\nhttps://mcp.example.com/filament\n/srv/orders.json\n")
    assert cli.main(["modules", "menu", "--raw"]) == 0
    cap = capsys.readouterr()
    lines = cap.out.splitlines()
    assert "web" in lines[0].split(",") and "orders" in lines[0].split(",")
    assert "set web.public_url=https://mcp.example.com/filament" in lines
    assert "set orders.file=/srv/orders.json" in lines
    assert "https address" in cap.err
    assert "modules" not in config.load()


def test_raw_menu_blank_setting_returns_to_checklist(monkeypatch, capsys):
    # web on, blank url -> back to the checklist; web off again, Enter -> no settings lines
    _stdin(monkeypatch, f"{_n('web')}\n\n\n{_n('web')}\n\n")
    assert cli.main(["modules", "menu", "--raw"]) == 0
    cap = capsys.readouterr()
    assert "left blank" in cap.err
    assert not any(ln.startswith("set ") for ln in cap.out.splitlines())


def test_config_menu_web_and_orders_ask_settings_and_store_them(applied, monkeypatch):
    _stdin(monkeypatch, f"6\n{_n('web')} {_n('orders')}\n\nhttps://mcp.example.com/filament\n/srv/orders.json\n0\n")
    assert cli.main(["config"]) == 0
    cfg = config.load()
    assert cfg["modules"]["web"] and cfg["modules"]["orders"]
    assert cfg["web"]["public_url"] == "https://mcp.example.com/filament"
    assert cfg["orders"]["file"] == "/srv/orders.json"


def test_raw_menu_first_install_starts_without_ai_and_library(monkeypatch, capsys):
    _stdin(monkeypatch, "\n")                        # no config file at all: Enter on the untouched list
    assert cli.main(["modules", "menu", "--raw"]) == 0
    cap = capsys.readouterr()
    chosen = set(cap.out.splitlines()[0].split(","))
    assert chosen == modules.MODES["server"] and not {"ai_intake", "library"} & chosen
    assert "[ ]  3 ai_intake" in cap.err and "[ ]  6 library" in cap.err


def test_raw_menu_existing_legacy_config_keeps_legacy_set_and_station_preset_drops_library(monkeypatch, capsys):
    config.save(config.load())                       # a config file without `modules`: a legacy install
    _stdin(monkeypatch, "\n")
    assert cli.main(["modules", "menu", "--raw"]) == 0
    assert {"ai_intake", "library"} <= set(capsys.readouterr().out.splitlines()[0].split(","))
    _stdin(monkeypatch, "t\n\n192.168.1.5\n")
    assert cli.main(["modules", "menu", "--raw"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "station"


def test_enable_station_at_a_terminal_asks_for_the_server_address(applied, monkeypatch):
    cfg = config.load()
    cfg["modules"] = {n: n == "backup" for n in modules.MODULES}
    config.save(cfg)
    asked = _terminal(monkeypatch, "10.0.0.5")
    assert cli.main(["modules", "enable", "station"]) == 0
    assert any("Server address" in q for q in asked)
    assert config.load()["station"]["allow"] == ["10.0.0.5"]
