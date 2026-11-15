"""filament-kit modules list/set/enable/disable and the Features checklist (spec sections 3-4; 06 8.5)."""
import io
import re
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


def test_features_lists_the_setup_and_every_feature_with_its_key_state_and_needs(capsys, monkeypatch):
    monkeypatch.setenv("SPOOLWARDEN_GLYPHS", "unicode")
    assert cli.main(["features"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0] == "Setup: Hub" and lines[1] == ""
    assert lines[2].split() == ["FEATURE", "KEY", "STATE", "NEEDS"]
    cells = [re.split(r"\s{2,}", ln.strip()) for ln in lines[3:17]]
    rows = {c[0]: c for c in cells}
    assert rows["Spoolman"][:3] == ["Spoolman", "spoolman", "● on"]
    assert rows["Hub service"] == ["Hub service", "hub", "● on", "Spoolman"]
    assert rows["Label Reader: Cloud (Claude)"][1:3] == ["label-reader", "● on"]          # an older install keeps it
    assert rows["Label Reader: On this Hub"][1:3] == ["label-reader-local", "○ off"]
    assert rows["Weigh Station"][1:3] == ["weigh-station", "○ off"]
    assert [c[1] for c in cells] == list(cli._FEATURE_KEYS)                                     # the order of 06 9.6
    assert out.rstrip().endswith("Uses AI: Label Reader: Cloud (Claude), Label Reader: On this Hub.")


def test_modules_list_is_features_under_its_old_name_and_shows_the_same(capsys):
    assert cli.main(["modules", "list"]) == 0
    old = capsys.readouterr().out
    assert cli.main(["features", "list"]) == 0
    assert capsys.readouterr().out == old
    assert cli.main(["features"]) == 0
    assert capsys.readouterr().out == old


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
    assert cli.main(["modules", "disable", "server"]) == 2
    err = capsys.readouterr().err
    assert "Fix: add --yes to accept the cascade, or switch the others first." in err
    assert applied == []
    assert "modules" not in config.load()


def test_json_stops_with_exit_2_where_it_would_ask(applied, capsys, monkeypatch):
    # at a terminal this asks; --json never asks: exit 2, nothing changed (06 6.8)
    _stdin(monkeypatch, "y\n", tty=True)
    assert cli.main(["modules", "disable", "server", "--json"]) == 2
    assert "needs a yes" in capsys.readouterr().out
    assert applied == [] and "modules" not in config.load()
    config.save(modules.set_mode(config.load(), "station"))
    assert cli.main(["modules", "enable", "printers", "--json"]) == 2     # the offer to turn on server too
    assert "needs a yes" in capsys.readouterr().out


def test_disable_with_dependents_tty_asks(applied, monkeypatch):
    # server-less needs a remote Spoolman (validate)
    cfg = config.load()
    cfg["spoolman_url"] = "http://spoolman.example:7912"
    config.save(cfg)
    _stdin(monkeypatch, "y\n" * 5, tty=True)          # one question for each Feature that goes with it
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
    assert cli.main(["modules", "disable", "server"]) == 2
    err = " ".join(capsys.readouterr().err.split("Fix:")[0].split())
    for n in ("ai_intake", "orders", "printers", "presets", "web", "remote"):
        assert modules.MODULES[n].title in err, n


def test_disable_after_a_yes_does_what_it_said(applied, capsys, monkeypatch):
    _deep()
    asked = []
    monkeypatch.setattr(cli.apply, "_tty", lambda: True)
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: asked.append(q) or True)
    assert cli.main(["modules", "disable", "server"]) == 0
    mods = config.load()["modules"]
    for n in ("server", "ai_intake", "orders", "printers", "presets", "web", "remote"):
        assert mods[n] is False, n
    assert len(asked) == 6 and asked[0].startswith("Also turn off ")
    for n in ("orders", "remote"):
        assert any(modules.MODULES[n].title in q for q in asked), n


def test_enable_at_a_terminal_offers_what_it_needs_all_the_way_down(applied, monkeypatch):
    config.save(modules.set_mode(config.load(), "station"))
    cfg = config.load()
    cfg["spoolman_url"] = "http://spoolman.example:7912"
    config.save(cfg)
    asked = []
    monkeypatch.setattr(cli.apply, "_tty", lambda: True)
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: asked.append(q) or True)
    assert cli.main(["modules", "enable", "printers"]) == 0
    assert asked == ["Also turn on Hub service? Bambu Lab printers needs it. [y/N] "]
    assert config.load()["modules"]["server"] is True


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
    assert after["web"]["public_url"] == "https://printer.example.com/filament" and "Public" in asked[0]
    assert "Turns on: Web access (Remote access needs it), Remote access." in " ".join(capsys.readouterr().out.split())


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
    monkeypatch.setattr(cli.apply, "_tty", lambda: True)
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: True)
    monkeypatch.setattr(cli, "_plan_error", lambda cfg: "name does not resolve")
    assert cli.main(["modules", "disable", "server"]) == 1
    out = capsys.readouterr()
    assert "Turned off" not in out.out and "Nothing was changed" in out.err
    assert config.load() == before and applied == []


def test_the_fix_line_can_be_followed_switching_the_others_off_first(applied, capsys, monkeypatch):
    _deep()
    _stdin(monkeypatch, "")
    assert cli.main(["features", "off", "server"]) == 2
    assert "Fix: add --yes to accept the cascade, or switch the others first." in capsys.readouterr().err
    for key in ("orders", "remote", "web", "presets", "printers", "label-reader", "hub"):      # the others, then it
        assert cli.main(["features", "off", key]) == 0, key
    assert config.load()["modules"]["server"] is False


def test_enable_at_a_terminal_refused_changes_nothing(applied, capsys, monkeypatch):
    config.save(modules.set_mode(config.load(), "station"))
    monkeypatch.setattr(cli.apply, "_tty", lambda: True)
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: False)
    assert cli.main(["modules", "enable", "printers"]) == 5          # a no: Nothing changed (06 7)
    assert capsys.readouterr().out.strip().endswith("Nothing changed.") and applied == []
    assert "server" not in modules.enabled(config.load())


def test_every_way_of_switching_says_it_in_the_same_words(applied, capsys, monkeypatch):
    _deep()
    monkeypatch.setattr(cli.apply, "_tty", lambda: True)
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: True)
    before = modules.enabled(config.load())
    new, _notes = modules.toggle(before, "server")
    assert cli.main(["modules", "disable", "server"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert cli._feature_plan(before, new, {"server"})[0] in out and "Features applied: " in out


def test_enable_with_dependency_off_fails(applied, capsys, monkeypatch):
    _stdin(monkeypatch, "")
    config.save(modules.set_mode(config.load(), "station"))
    assert cli.main(["modules", "enable", "printers"]) == 2
    assert "Fix: add --yes to accept the cascade, or switch the others first." in capsys.readouterr().err


def test_enable_station_with_server_on_links_locally(applied):
    assert cli.main(["modules", "enable", "station"]) == 0
    cfg = config.load()
    assert cfg["modules"]["station"] is True
    assert cfg["station"]["url"] == "http://127.0.0.1:5003"
    assert cfg["station"]["allow"] == ["127.0.0.1"]


def test_unknown_module_fails(applied, capsys):
    assert cli.main(["modules", "enable", "nope"]) == 2
    err = capsys.readouterr().err
    assert 'Error: "nope" is not a Feature.' in err and "filament-kit features" in err
    assert cli.main(["features", "on", "label-reader-local", "--yes"]) == 0           # a key, an old name or a title
    assert cli.main(["features", "off", "local_intake"]) == 0


def _features(monkeypatch, script, *args):
    """`config --numbered` with `script`: 11 opens the Features checklist."""
    _stdin(monkeypatch, script)
    return cli.main(["config", "--numbered", *args])


def test_config_menu_toggle_printers_then_apply(applied, monkeypatch):
    # 11 Features, 4 = printers (server mode has it on), s applies the checklist, q leaves config
    assert _features(monkeypatch, "11\n4\ns\nq\n") == 0
    assert config.load()["modules"]["printers"] is False
    assert set(config.load()["modules"]) == set(modules.MODULES) - set(modules.NEWER)
    assert applied[0]["modules"]["printers"] is False
    assert ("finish", False) in applied


def test_config_menu_no_module_change_does_not_apply(applied, monkeypatch):
    assert _features(monkeypatch, "11\nq\nq\n") == 0
    assert applied == []
    assert "modules" not in config.load()


def test_config_menu_station_on_asks_address_and_refuses_range(applied, monkeypatch, capsys):
    config.save(modules.set_mode(config.load(), "station"))
    # custom: station on, server off -> turn spoolman on (1) is irrelevant; use station-only then toggle backup
    cfg = config.load()
    cfg["modules"]["station"] = False
    cfg["modules"]["backup"] = True
    config.save(cfg)
    # 8 = station: s applies; the Hub's address: a range is refused, then a single address accepted
    assert _features(monkeypatch, "11\n8\ns\n192.168.1.0/24\n192.168.1.5\nq\n") == 0
    cap = capsys.readouterr()
    assert "Weigh Station only needs the Hub's address." in cap.out
    assert "Error: enter one address or name, not a range or wildcard." in cap.err
    cfg = config.load()
    assert cfg["modules"]["station"] is True
    assert cfg["station"]["allow"] == ["192.168.1.5"]


def test_config_menu_choose_mode(applied, monkeypatch):
    assert _features(monkeypatch, "11\nb\ns\nq\n") == 0      # b = Hub with Weigh Station (all-in-one)
    assert config.load()["modules"] == {n: n not in modules.OPT_IN or n in ("ai_intake", "library") for n in modules.MODULES
                              if n not in modules.NEWER}  # legacy cfg: AI kept; klipper never named stays out
    assert config.load()["station"]["url"] == "http://127.0.0.1:5003"


def test_modules_menu_raw_prints_choice_only_on_stdout(monkeypatch, capsys):
    _stdin(monkeypatch, "w\n1\ns\n192.168.1.5\n")   # Weigh Station setup, spoolman on, apply, the Hub's address
    assert cli.main(["modules", "menu", "--raw", "--numbered"]) == 0
    cap = capsys.readouterr()
    assert cap.out.splitlines() == ["spoolman,station", "set station.allow=192.168.1.5"]
    assert "[x]" in cap.err and "needs: Hub service" in cap.err
    assert "modules" not in config.load()          # --raw changes nothing


def test_modules_menu_raw_cancel(monkeypatch, capsys):
    _stdin(monkeypatch, "q\n")
    assert cli.main(["modules", "menu", "--raw", "--numbered"]) == 1
    assert capsys.readouterr().out == ""


def test_config_menu_turning_on_remote_pulls_web_and_says_so(applied, monkeypatch, capsys):
    cfg = config.load()
    cfg["web"] = {"public_url": "https://mcp.example.com/filament", "lan": ["192.168.1.0/24"]}
    config.save(cfg)
    n = list(modules.MODULES).index("remote") + 1
    assert _features(monkeypatch, f"11\n{n}\ns\nq\n") == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "now on too" in out and "Turns on: Web access (Remote access needs it), Remote access." in out
    assert config.load()["modules"]["web"] is True and config.load()["modules"]["remote"] is True


def test_non_root_changes_nothing(applied, monkeypatch, capsys):
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000, raising=False)
    for argv in (["modules", "set", "all-in-one"], ["modules", "enable", "station"],
                 ["modules", "disable", "library"]):
        assert cli.main(argv) == 3
        assert "administrator rights" in capsys.readouterr().err
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
    assert _features(monkeypatch, "11\nh\ns\nq\n") == 0      # h = Hub setup
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
    assert _features(monkeypatch, "11\nw\ns\nbadname\nq\n") == 1     # w = Weigh Station only, the Hub's address
    assert "fix:" in capsys.readouterr().err
    assert (config.paths().etc / "config.json").read_bytes() == before and ran == []


def test_modules_menu_raw_revalidates_and_reshows(monkeypatch, capsys):
    # default server mode: 1 = spoolman off leaves a server with no Spoolman: its address is asked, an empty answer
    # goes back to the checklist, 1 switches it on again, s applies
    _stdin(monkeypatch, "1\ns\n\n1\ns\n")
    assert cli.main(["modules", "menu", "--raw", "--numbered"]) == 0
    cap = capsys.readouterr()
    assert "The Hub service needs a Spoolman: none runs on this machine." in cap.err
    assert "Not applied: Hub service needs that setting." in cap.err
    assert "spoolman" in cap.out.split(",")


def _n(name):
    return list(modules.MODULES).index(name) + 1


def test_raw_menu_asks_web_and_orders_settings(monkeypatch, capsys):
    # web: a non-https answer is refused, then accepted; orders: the file path
    _stdin(monkeypatch, f"{_n('web')} {_n('orders')}\ns\nhttp://x\nhttps://mcp.example.com/filament\n/srv/orders.json\n")
    assert cli.main(["modules", "menu", "--raw", "--numbered"]) == 0
    cap = capsys.readouterr()
    lines = cap.out.splitlines()
    assert "web" in lines[0].split(",") and "orders" in lines[0].split(",")
    assert "set web.public_url=https://mcp.example.com/filament" in lines
    assert "set orders.file=/srv/orders.json" in lines
    assert "Error: give the https address people use, e.g. https://hub.example/filament." in cap.err
    assert "modules" not in config.load()


def test_raw_menu_blank_setting_returns_to_checklist(monkeypatch, capsys):
    # web on, blank url -> back to the checklist; web off again, s -> no settings lines
    _stdin(monkeypatch, f"{_n('web')}\ns\n\n{_n('web')}\ns\n")
    assert cli.main(["modules", "menu", "--raw", "--numbered"]) == 0
    cap = capsys.readouterr()
    assert "Not applied: Web access needs that setting." in cap.err
    assert not any(ln.startswith("set ") for ln in cap.out.splitlines())


def test_config_menu_web_and_orders_ask_settings_and_store_them(applied, monkeypatch):
    assert _features(monkeypatch, f"11\n{_n('web')} {_n('orders')}\ns\nhttps://mcp.example.com/filament\n"
                                  "/srv/orders.json\nq\n") == 0
    cfg = config.load()
    assert cfg["modules"]["web"] and cfg["modules"]["orders"]
    assert cfg["web"]["public_url"] == "https://mcp.example.com/filament"
    assert cfg["orders"]["file"] == "/srv/orders.json"


def test_raw_menu_first_install_starts_without_ai_and_library(monkeypatch, capsys):
    _stdin(monkeypatch, "s\n")                      # no config file at all: apply the untouched list
    assert cli.main(["modules", "menu", "--raw", "--numbered"]) == 0
    cap = capsys.readouterr()
    chosen = set(cap.out.splitlines()[0].split(","))
    assert chosen == modules.MODES["server"] and not {"ai_intake", "library"} & chosen
    assert "[ ] Label Reader: Cloud (Claude)" in cap.err and "[ ] Filament Catalog" in cap.err


def test_raw_menu_existing_legacy_config_keeps_legacy_set_and_station_preset_drops_library(monkeypatch, capsys):
    config.save(config.load())                       # a config file without `modules`: a legacy install
    _stdin(monkeypatch, "s\n")
    assert cli.main(["modules", "menu", "--raw", "--numbered"]) == 0
    assert {"ai_intake", "library"} <= set(capsys.readouterr().out.splitlines()[0].split(","))
    _stdin(monkeypatch, "w\ns\n192.168.1.5\n")
    assert cli.main(["modules", "menu", "--raw", "--numbered"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "station"


def test_enable_station_at_a_terminal_asks_for_the_server_address(applied, monkeypatch):
    cfg = config.load()
    cfg["modules"] = {n: n == "backup" for n in modules.MODULES}
    config.save(cfg)
    asked = _terminal(monkeypatch, "10.0.0.5")
    assert cli.main(["modules", "enable", "station"]) == 0
    assert any("The Hub's address (IP address or name): " == q for q in asked)
    assert config.load()["station"]["allow"] == ["10.0.0.5"]
