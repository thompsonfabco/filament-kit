import itertools

import pytest

from filament_kit import apply, config, modules
from filament_kit.modules import ModuleError, set_mode


def _cfg(**over):
    return config._merge(config.DEFAULTS, over)


def _mode(mode):
    """A mode's config; station-only needs the server's address (validate)."""
    cfg = set_mode(_cfg(), mode)
    if mode == "station":
        cfg["station"]["allow"] = ["spoolman.home.arpa"]
    return cfg


def _of(actions, kind):
    return [a.arg for a in actions if a.kind == kind]


def test_legacy_config_plans_todays_install():
    acts = apply.plan({})
    assert _of(acts, "enable") == [
        "spoolman.service", "filament-kit.service", "filament-kit-build.path",
        "filament-kit-library.timer", "filament-kit-backup.timer"]
    kinds = {a.kind for a in acts}
    assert not kinds & {"remove_pkg", "mask_sleep", "alsa_unmute", "udev_reload"}
    assert _of(acts, "disable") == ["filament-kit-station.service"]
    assert "filament-kit-station.service" not in _of(acts, "install_unit")


def test_all_in_one_station_localhost_only():
    cfg = set_mode(_cfg(), "all-in-one")
    acts = apply.plan(cfg, resolve=lambda h: [h])
    (dest, content, mode, owner), = [
        a.arg for a in acts if a.kind == "install_file" and a.arg[0].endswith("kit.conf")]
    assert dest == "/etc/systemd/system/filament-kit-station.service.d/kit.conf"
    assert "STATION_ALLOW=127.0.0.1" in content
    assert "IPAddressAllow=localhost 127.0.0.1" in content
    assert "/" not in content


def test_station_mode_resolves_server_name():
    cfg = set_mode(_cfg(), "station")
    cfg["station"]["allow"] = ["spoolman.home.arpa"]
    acts = apply.plan(cfg, resolve=lambda h: {"spoolman.home.arpa": ["192.0.2.10"]}[h])
    content = [a.arg[1] for a in acts if a.kind == "install_file"
               and a.arg[0].endswith("kit.conf")][0]
    assert "IPAddressAllow=localhost 192.0.2.10" in content
    assert "STATION_ALLOW=127.0.0.1 192.0.2.10" in content
    dis = _of(acts, "disable")
    assert "spoolman.service" in dis and "filament-kit.service" in dis
    assert not any(a.kind == "server_setup" for a in acts)
    assert "avahi-daemon" not in _of(acts, "apt")
    assert "filament-kit-station.service" in _of(acts, "enable")


def test_station_unresolvable_server_fails_before_writing():
    cfg = set_mode(_cfg(), "station")
    cfg["station"]["allow"] = ["nope.localdomain"]

    def boom(host):
        raise OSError("no such host")

    with pytest.raises(ModuleError) as e:
        apply.plan(cfg, resolve=boom)
    assert "nope.localdomain" in str(e.value) and "fix:" in str(e.value)


def test_validation_error_propagates():
    with pytest.raises(ModuleError):
        apply.plan({"modules": {"server": True, "spoolman": False}})


@pytest.mark.parametrize("a,b", list(itertools.permutations(modules.MODES, 2)))
def test_switch_never_removes_data(a, b):
    for mode in (a, b):
        acts = apply.plan(_mode(mode), resolve=lambda h: [h])
        for p in _of(acts, "remove_file"):
            assert not p.startswith(("/var/lib", "/etc/filament-kit", "/var/backups"))


def test_daemon_reload_once_before_enable():
    for mode in modules.MODES:
        acts = apply.plan(_mode(mode), resolve=lambda h: [h])
        kinds = [a.kind for a in acts]
        assert kinds.count("daemon_reload") == 1
        assert kinds.index("daemon_reload") < kinds.index("enable")
        # unit files must be on disk before the reload
        assert max(i for i, k in enumerate(kinds) if k == "install_unit") < kinds.index("daemon_reload")


def test_ai_intake_key_question_follows_module():
    on = apply.plan({})
    assert _of(on, "server_setup") == ["key"]
    cfg = _cfg(modules={n: n not in ("ai_intake", "station") for n in modules.MODULES})
    assert _of(apply.plan(cfg), "server_setup") == [""]


def test_station_actions_and_first_build_last():
    acts = apply.plan(set_mode(_cfg(), "all-in-one"), resolve=lambda h: [h])
    kinds = [a.kind for a in acts]
    for k in ("remove_pkg", "disable_ext", "mask_sleep", "alsa_unmute", "udev_reload"):
        assert k in kinds
    assert ("user", ("filament-kit-station", "dialout,audio")) in [(a.kind, a.arg) for a in acts]
    assert kinds[-1] == "first_build"
    assert kinds.index("wait_http") < kinds.index("ensure_fields")
    rules = [a.arg for a in acts if a.kind == "install_file" and "udev" in a.arg[0]][0]
    assert 'ATTRS{idVendor}=="0922"' in rules[1]


def test_remote_spoolman_server():
    cfg = _cfg(spoolman_url="http://spoolman.home.arpa:7912",
               modules={"server": True})
    acts = apply.plan(cfg)
    assert "ensure_fields" in [a.kind for a in acts]
    assert "wait_http" not in [a.kind for a in acts]
    assert "first_build" not in [a.kind for a in acts]


def test_dropin_beep_device_and_off():
    cfg = _cfg()
    cfg["station"].update(beep=False, beep_device="plughw:1,0")
    text = apply.station_dropin(cfg, ["127.0.0.1"])
    assert text.startswith("[Service]\n")
    assert "STATION_BEEP=0" in text and "STATION_BEEP_DEVICE=plughw:1,0" in text
    assert "STATION_BEEP_DEVICE" not in apply.station_dropin(_cfg(), ["127.0.0.1"])
