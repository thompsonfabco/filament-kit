import pytest

from filament_kit import config
from filament_kit.modules import (
    LEGACY, MODES, MODULES, ModuleError, dependents, enabled, mode_of, set_mode, validate,
)


def test_missing_modules_is_server_mode():
    assert enabled({}) == LEGACY == MODES["server"] | {"ai_intake", "library"}  # the kit as it was had AI intake and the library timer
    assert enabled({"modules": None}) == LEGACY
    assert mode_of(enabled({})) == "server"


def test_registry_order_and_modes():
    assert list(MODULES) == ["spoolman", "server", "ai_intake", "printers",
                             "presets", "library", "backup", "station", "web", "remote", "orders",
                             "updates"]
    assert MODES["station"] == frozenset({"station"})
    assert MODES["all-in-one"] == frozenset(MODULES) - {"ai_intake", "web", "remote", "orders", "library",
                                                        "updates"}
    assert MODES["server"] == frozenset(MODULES) - {"station", "ai_intake", "web", "remote", "orders", "library",
                                                    "updates"}


def test_mode_of_custom():
    assert mode_of(MODES["server"] - {"printers"}) == "custom"


def test_set_mode_all_in_one_points_station_at_localhost():
    cfg = set_mode({"port": 1}, "all-in-one")
    assert cfg["station"]["url"] == "http://127.0.0.1:5003"
    assert cfg["station"]["allow"] == ["127.0.0.1"]
    assert enabled(cfg) == MODES["all-in-one"] | {"ai_intake", "library"}  # a filled config without modules: legacy, both kept
    assert mode_of(enabled(cfg)) == "all-in-one"


def test_set_mode_returns_copy():
    base = {"modules": {"server": True}}
    set_mode(base, "station")
    assert base == {"modules": {"server": True}}


def test_set_mode_unknown():
    with pytest.raises(ModuleError):
        set_mode({}, "bogus")


def test_validate_dependency_off():
    cfg = {"modules": {"presets": True, "server": False, "spoolman": True}}
    with pytest.raises(ModuleError, match="presets needs server"):
        validate(cfg)


def test_validate_remote_spoolman_required():
    mods = {"server": True, "spoolman": False}
    with pytest.raises(ModuleError, match="spoolman_url"):
        validate({"modules": mods, "spoolman_url": "http://127.0.0.1:7912"})
    validate({"modules": mods, "spoolman_url": "http://spoolman.home.arpa:7912"})


def test_validate_unknown_module():
    with pytest.raises(ModuleError, match="nope"):
        validate({"modules": {"nope": True}})


@pytest.mark.parametrize("bad", ["192.168.1.0/24", "0.0.0.0", "::", "*"])
def test_station_allow_rejects_ranges(bad):
    with pytest.raises(ModuleError, match="station.allow"):
        validate({"station": {"allow": ["127.0.0.1", bad]}})


@pytest.mark.parametrize("ok", ["192.0.2.10", "spoolman.home.arpa"])
def test_station_allow_accepts_single_hosts(ok):
    validate({"station": {"allow": [ok]}})


def test_default_config_validates():
    validate(config.DEFAULTS)
    assert "modules" not in config.DEFAULTS
    assert config.DEFAULTS["station"]["port"] == 5003


def test_dependents():
    assert dependents("server", LEGACY) == ["ai_intake", "printers", "presets"]
    assert dependents("server", frozenset({"server"})) == []


def test_station_without_server_needs_non_loopback_allow():
    cfg = {"modules": {"station": True}, "station": {"allow": ["127.0.0.1"]}}
    with pytest.raises(ModuleError, match="--server"):
        validate(cfg)
    cfg["station"]["allow"] = ["127.0.0.1", "192.0.2.10"]
    validate(cfg)


@pytest.mark.parametrize("mode", ["server", "station"])
def test_leaving_all_in_one_drops_the_local_station_link(mode):
    # spec section 3: without a local station beside the server the url is unset (409 module_off)
    cfg = set_mode(set_mode({}, "all-in-one"), mode)
    assert cfg["station"].get("url") is None


def test_set_mode_keeps_a_remote_station_url():
    cfg = set_mode({"station": {"url": "http://station.example:5003"}}, "server")
    assert cfg["station"]["url"] == "http://station.example:5003"


# ---------- merge-ops Task 0: web / remote / orders ----------

NEW = frozenset({"web", "remote", "orders"})


def test_new_modules_registered():
    assert MODULES["web"].units == ("filament-kit-web.service",)
    assert MODULES["web"].depends == ("server",) and MODULES["web"].apt == ()
    assert MODULES["remote"].depends == ("web",) and MODULES["remote"].units == ()
    assert MODULES["remote"].apt == ("nginx", "certbot")
    assert MODULES["orders"].depends == ("ai_intake",)


def test_new_modules_off_by_default():
    for name, members in MODES.items():
        assert not members & NEW, name
    assert not enabled({}) & NEW
    cfg = set_mode({}, "all-in-one")
    assert cfg["modules"]["web"] is False and mode_of(enabled(cfg)) == "all-in-one"


def test_new_modules_dependencies():
    with pytest.raises(ModuleError, match="web needs server"):
        validate({"modules": {"web": True}, "spoolman_url": "http://sm.lan:7912"})
    with pytest.raises(ModuleError, match="orders needs ai_intake"):
        validate({"modules": {"server": True, "orders": True}, "spoolman_url": "http://sm.lan:7912",
                  "orders": {"file": "/x"}})


def test_remote_needs_https_public_url():
    cfg = config._merge(config.DEFAULTS, {})
    cfg["modules"] = {"spoolman": True, "server": True, "web": True, "remote": True}
    for url in (None, "", "http://x.example/", "not a url"):
        cfg["web"]["public_url"] = url
        with pytest.raises(ModuleError, match="web.public_url"):
            validate(cfg)
    cfg["web"]["public_url"] = "https://kit.example.com"
    validate(cfg)
    cfg["modules"]["remote"] = False
    cfg["modules"]["web"] = False
    cfg["web"]["public_url"] = None
    validate(cfg)                                    # neither web nor remote: no URL needed


def test_web_needs_https_public_url():
    # Ruling AA: the web unit is the OAuth issuer, so it needs its public address even without remote
    cfg = config._merge(config.DEFAULTS, {})
    cfg["modules"] = {"spoolman": True, "server": True, "web": True}
    for url in (None, "", "http://x.example/", "not a url", "https://"):
        cfg["web"]["public_url"] = url
        with pytest.raises(ModuleError, match="web needs web.public_url"):
            validate(cfg)
    cfg["web"]["public_url"] = "https://kit.example.com/filament"
    validate(cfg)


def test_orders_needs_file():
    cfg = config._merge(config.DEFAULTS, {})
    cfg["modules"] = {"spoolman": True, "server": True, "ai_intake": True, "orders": True}
    with pytest.raises(ModuleError, match="orders.file"):
        validate(cfg)
    cfg["orders"]["file"] = "/var/lib/filament-kit/orders.json"
    validate(cfg)


def test_new_config_defaults():
    d = config.DEFAULTS
    assert d["web"]["port"] == 8101 and d["web"]["public_url"] is None
    assert d["web"]["lan"] == ["192.168.0.0/16", "10.0.0.0/8"]   # A-M6: no 172.16/12 (Docker bridges)
    assert d["remote"] == {"hostname": None, "acme_window": None, "email": None}
    assert d["orders"] == {"file": None}
    assert d["tag_sources"] == [] and d["slot_service"] is None and d["slicer_printers"] == []
    assert d["presets_orca"] is False and d["web_instructions"] is None
    assert d["intake"] == {"tare_hints": {}, "model": None}


# ---------- C-I3: a mode change keeps the opt-in modules switched on by hand ----------

def _with_opt_in(**on):
    cfg = set_mode({}, "server")
    cfg["modules"].update(on)
    return cfg


def test_set_mode_keeps_hand_enabled_opt_in_modules():
    hand = {"ai_intake", "web", "remote", "orders"}
    cfg = set_mode(_with_opt_in(ai_intake=True, web=True, remote=True, orders=True), "all-in-one",
                   say=lambda m: None)
    assert hand <= enabled(cfg)
    assert enabled(cfg) - hand == MODES["all-in-one"]
    again = set_mode(cfg, "server", say=lambda m: None)
    assert hand <= enabled(again)


def test_set_mode_drops_opt_in_modules_whose_dependencies_go_and_says_so():
    said = []
    cfg = set_mode(_with_opt_in(web=True, remote=True, orders=True), "station", say=said.append)
    assert enabled(cfg) == MODES["station"]
    assert len(said) == 1 and all(n in said[0] for n in ("web", "remote", "orders"))
    validate(dict(cfg, station={"allow": ["10.0.0.5"]}))


def test_set_mode_never_turns_opt_in_modules_on():
    said = []
    assert enabled(set_mode({}, "all-in-one", say=said.append)) == MODES["all-in-one"]
    assert enabled(set_mode(_with_opt_in(web=False), "server", say=said.append)) == MODES["server"]
    assert said == []


def test_validate_checks_web_lan_entries_are_networks():
    """A-M5: a bad web.lan entry is a ModuleError now, not a web unit that crashes on start (a restart loop)."""
    cfg = set_mode({}, "server", say=None)
    cfg["modules"]["web"] = True
    cfg["web"] = {"public_url": "https://mcp.example.com/filament", "lan": ["192.168.1.0/24", "10.0.0.0/8"]}
    validate(cfg)
    for bad in (["192.168.1.0/33"], ["home"], "192.168.1.0/24", [None]):
        cfg["web"]["lan"] = bad
        with pytest.raises(ModuleError, match="web.lan"):
            validate(cfg)
    cfg["modules"]["web"] = False
    validate(cfg)                               # only checked while web is on


# ---------- checklist menu (R2) ----------

def test_menu_lines_generic_and_marks_needs():
    from filament_kit import modules
    lines = modules.menu_lines({})
    assert len(lines) == len(MODULES)
    for i, (n, m) in enumerate(MODULES.items(), 1):
        ln = lines[i - 1]
        assert f" {i} {n}" in ln and m.description in ln
        assert ("[x]" in ln) == (n in modules.enabled({}))
        for d in m.depends:
            assert d in ln.split("needs:", 1)[1]
        if m.needs_text:
            assert m.needs_text in ln
        assert ("OPTIONAL AI" in ln) == m.optional_ai
    assert any("OPTIONAL AI" in ln for ln in lines)


def test_toggle_on_pulls_needs_and_says_so():
    from filament_kit import modules
    on, notes = modules.toggle(frozenset(), "remote")
    assert on == {"remote", "web", "server"}
    assert "web" in notes[0] and "server" in notes[0]


def test_toggle_off_lists_transitive_dependents():
    from filament_kit import modules
    on, notes = modules.toggle(MODES["server"] | {"web", "remote"}, "server")
    assert not ({"server", "web", "remote", "ai_intake", "printers", "presets"} & on)
    assert "web" in notes[0] and "remote" in notes[0]


def test_toggle_unknown():
    from filament_kit import modules
    with pytest.raises(ModuleError):
        modules.toggle(frozenset(), "nope")


def test_preset_keeps_opt_ins():
    from filament_kit import modules
    on, _ = modules.preset(MODES["server"] | {"web"}, "server")
    assert "web" in on
    on, _ = modules.preset(MODES["server"] | {"web"}, "station")
    assert on == {"station"}


def test_run_checklist_toggle_preset_apply():
    from filament_kit import modules
    answers = iter(["t", "1 2", "", ])
    out = []
    got = modules.run_checklist(frozenset(), lambda p: next(answers), out.append)
    assert got == {"station", "spoolman", "server"}
    assert any("Preset station" in o for o in out)


def test_run_checklist_cancel_and_unknown():
    from filament_kit import modules
    answers = iter(["99", "q"])
    out = []
    assert modules.run_checklist(frozenset({"server"}), lambda p: next(answers), out.append) is None
    assert any("Unknown choice" in o for o in out)
    assert modules.run_checklist(frozenset(), lambda p: None, lambda s: None) is None


def test_close_selection():
    from filament_kit import modules
    on, notes = modules.close_selection(["spoolman", "printers"])
    assert on == {"spoolman", "printers", "server"} and notes
    with pytest.raises(ModuleError):
        modules.close_selection(["x"])


def test_missing_and_collect_settings():
    from filament_kit import config, modules
    cfg = config.DEFAULTS
    assert modules.missing_settings(frozenset({"server"}), cfg) == []
    assert modules.missing_settings(frozenset({"web", "orders", "station"}), cfg) == [
        "web.public_url", "orders.file", "station.allow"]
    assert modules.missing_settings(frozenset({"web", "station", "server"}), cfg) == ["web.public_url"]
    answers = iter(["ftp://x", "https://a.example.com/f"])
    said = []
    got = modules.collect_settings(frozenset({"web"}), cfg, lambda p: next(answers), said.append)
    assert got == {"web.public_url": "https://a.example.com/f"} and said
    assert modules.collect_settings(frozenset({"web"}), cfg, lambda p: "", print) is None
    assert modules.check_setting("station.allow", "127.0.0.1")
    assert modules.check_setting("station.allow", "10.0.0.0/8")
    assert modules.check_setting("station.allow", "srv.localdomain") is None
# ---------- R1: AI optional ----------

def test_modes_leave_ai_intake_off():
    """A new install's modes never switch AI label reading on: it needs an Anthropic key the owner opts into."""
    for mode in ("server", "all-in-one"):
        assert "ai_intake" not in MODES[mode]
        assert "ai_intake" not in enabled(set_mode({}, mode, say=None))


def test_config_without_modules_keeps_ai_intake():
    """An install from before modules (no `modules` key) had AI intake; it keeps it and is still the server mode."""
    assert "ai_intake" in enabled({})
    assert mode_of(enabled({})) == "server"
    assert mode_of(MODES["server"] | {"ai_intake"}) == "server"
    assert mode_of(MODES["all-in-one"] | {"ai_intake"}) == "all-in-one"


def test_set_mode_keeps_ai_intake_that_was_on():
    legacy = {"server_name": "fk"}                      # an existing install's config, no modules key
    assert "ai_intake" in enabled(set_mode(legacy, "all-in-one", say=None))
    cfg = set_mode({}, "server", say=None)
    cfg["modules"]["ai_intake"] = True
    assert "ai_intake" in enabled(set_mode(cfg, "all-in-one", say=None))
    cfg["modules"]["ai_intake"] = False
    assert "ai_intake" not in enabled(set_mode(cfg, "server", say=None))
    assert "ai_intake" not in enabled(set_mode(legacy, "station", say=None))  # station has no server
