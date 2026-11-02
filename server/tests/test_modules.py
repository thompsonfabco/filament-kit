import pytest

from filament_kit import config
from filament_kit.modules import (
    MODES, MODULES, ModuleError, dependents, enabled, mode_of, set_mode, validate,
)


def test_missing_modules_is_server_mode():
    assert enabled({}) == MODES["server"]
    assert enabled({"modules": None}) == MODES["server"]
    assert mode_of(enabled({})) == "server"


def test_registry_order_and_modes():
    assert list(MODULES) == ["spoolman", "server", "ai_intake", "printers",
                             "presets", "library", "backup", "station"]
    assert MODES["station"] == frozenset({"station"})
    assert MODES["all-in-one"] == frozenset(MODULES)
    assert MODES["server"] == frozenset(MODULES) - {"station"}


def test_mode_of_custom():
    assert mode_of(MODES["server"] - {"printers"}) == "custom"


def test_set_mode_all_in_one_points_station_at_localhost():
    cfg = set_mode({"port": 1}, "all-in-one")
    assert cfg["station"]["url"] == "http://127.0.0.1:5003"
    assert cfg["station"]["allow"] == ["127.0.0.1"]
    assert enabled(cfg) == frozenset(MODULES)
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
    assert dependents("server", MODES["server"]) == ["ai_intake", "printers", "presets"]
    assert dependents("server", frozenset({"server"})) == []


def test_station_without_server_needs_non_loopback_allow():
    cfg = {"modules": {"station": True}, "station": {"allow": ["127.0.0.1"]}}
    with pytest.raises(ModuleError, match="--server"):
        validate(cfg)
    cfg["station"]["allow"] = ["127.0.0.1", "192.0.2.10"]
    validate(cfg)
