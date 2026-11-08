import itertools

import pytest

from filament_kit import apply, config, modules
from filament_kit.modules import ModuleError, set_mode
from filament_kit.station import voice


def _cfg(**over):
    return config._merge(config.DEFAULTS, over)


def _mode(mode):
    """A mode's config; station-only needs the server's address (validate)."""
    cfg = set_mode(_cfg(), mode)
    if mode == "station":
        cfg["station"]["allow"] = ["spoolman.example.lan"]
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
    opt = config.paths().opt.as_posix()
    assert "/" not in (content.replace(f"{opt}/resources/panel/intake-panel.bin", "")
                       .replace(f"{opt}/resources/voice/{voice.DEFAULT}.onnx", ""))  # no CIDR ranges


def test_station_mode_resolves_server_name():
    cfg = set_mode(_cfg(), "station")
    cfg["station"]["allow"] = ["spoolman.example.lan"]
    acts = apply.plan(cfg, resolve=lambda h: {"spoolman.example.lan": ["192.0.2.10"]}[h])
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
    cfg["station"]["allow"] = ["nope.example.lan"]

    def boom(host):
        raise OSError("no such host")

    with pytest.raises(ModuleError) as e:
        apply.plan(cfg, resolve=boom)
    assert "nope.example.lan" in str(e.value) and "fix:" in str(e.value)


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
    cfg = _cfg(modules={n: n not in ("ai_intake", "station") and n not in modules.OPT_IN for n in modules.MODULES})
    assert _of(apply.plan(cfg), "server_setup") == [""]


def test_station_actions_and_first_build_last():
    acts = apply.plan(set_mode(_cfg(), "all-in-one"), resolve=lambda h: [h])
    kinds = [a.kind for a in acts]
    for k in ("remove_pkg", "disable_ext", "mask_sleep", "alsa_unmute", "udev_reload"):
        assert k in kinds
    assert ("user", ("filament-kit-station", "dialout,audio,video")) in [(a.kind, a.arg) for a in acts]
    assert kinds[-1] == "first_build"
    assert kinds.index("wait_http") < kinds.index("ensure_fields")
    rules = [a.arg for a in acts if a.kind == "install_file" and "udev" in a.arg[0]][0]
    assert 'ATTRS{idVendor}=="0922"' in rules[1]


def test_station_udev_rule_sorts_after_the_ops_rule_and_replaces_the_old_name():
    """C-I1: udev applies rules in file-name order and the last GROUP= wins: the kit's rule must sort after the
    ops `99-intake-station.rules`; the kit's old name is removed before the new rule goes in."""
    acts = apply.plan(set_mode(_cfg(), "all-in-one"), resolve=lambda h: [h])
    name = apply.UDEV_RULE.rsplit("/", 1)[1]
    assert name > "99-intake-station.rules" and name > "99-filament-kit-station.rules"
    assert apply.UDEV_RULE.startswith("/etc/udev/rules.d/")
    pairs = [(a.kind, a.arg if isinstance(a.arg, (str, type(None))) else a.arg[0]) for a in acts]
    gone = pairs.index(("remove_file", "/etc/udev/rules.d/99-filament-kit-station.rules"))
    kinds = [k for k, _ in pairs]
    assert gone < pairs.index(("install_file", apply.UDEV_RULE)) < kinds.index("udev_reload")


def test_remote_spoolman_server():
    cfg = _cfg(spoolman_url="http://spoolman.example.lan:7912",
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


def test_dropin_speech_and_camera():
    text = apply.station_dropin(_cfg(), ["127.0.0.1"])
    assert "STATION_SPEECH=1" in text and "STATION_CAMERA=auto" in text
    cfg = _cfg()
    cfg["station"].update(speech=False, camera="/dev/video2")
    text = apply.station_dropin(cfg, ["127.0.0.1"])
    assert "STATION_SPEECH=0" in text and "STATION_CAMERA=/dev/video2" in text
    cfg["station"]["camera"] = "off"
    assert "STATION_CAMERA=off" in apply.station_dropin(cfg, ["127.0.0.1"])


def test_station_apt_speech_and_camera_without_recommends():
    acts = apply.plan(_mode("station"), resolve=lambda h: [h])
    assert "alsa-utils" in _of(acts, "apt")
    assert _of(acts, "apt_lean") == ["espeak-ng", "ffmpeg"]


def test_lean_apt_skips_what_is_installed_in_full_anyway():
    acts = apply.plan(set_mode(_cfg(), "all-in-one"), resolve=lambda h: [h])
    assert "ffmpeg" in _of(acts, "apt")  # the printers module wants the full package
    assert _of(acts, "apt_lean") == ["espeak-ng"]


def test_dropin_panel_firmware_and_flash_switch(monkeypatch):
    monkeypatch.setenv("FK_OPT", "/opt/filament-kit")
    text = apply.station_dropin(_cfg(), ["127.0.0.1"])
    assert "STATION_PANEL_FW=/opt/filament-kit/resources/panel/intake-panel.bin" in text
    assert "STATION_PANEL_FLASH=1" in text
    cfg = _cfg()
    cfg["station"]["panel_flash"] = False
    assert "STATION_PANEL_FLASH=0" in apply.station_dropin(cfg, ["127.0.0.1"])


def test_dropin_escapes_percent_and_rejects_line_breaks():
    cfg = _cfg()
    cfg["station"]["beep_device"] = "plughw:100%,0"
    assert "STATION_BEEP_DEVICE=plughw:100%%,0" in apply.station_dropin(cfg, ["127.0.0.1"])
    cfg["station"]["beep_device"] = "a b%\"c"
    assert '"STATION_BEEP_DEVICE=a b%%\\"c"' in apply.station_dropin(cfg, ["127.0.0.1"])
    for bad in ("a\nExecStart=/bin/sh", "a\rb"):
        cfg["station"]["camera"] = bad
        with pytest.raises(ModuleError, match="fix:"):
            apply.station_dropin(cfg, ["127.0.0.1"])


def test_bad_host_name_is_a_module_error_not_a_traceback():
    # 'a..b' makes the idna codec raise UnicodeError, not OSError
    cfg = modules.set_mode({"station": {}}, "station")
    cfg["station"]["allow"] = ["a..b"]
    with pytest.raises(ModuleError, match="fix:"):
        apply.plan(cfg)


def test_null_station_allow_plans():
    cfg = modules.set_mode({}, "all-in-one")
    cfg["station"]["allow"] = None
    acts = apply.plan(cfg, resolve=lambda h: [h])
    assert any(a.kind == "install_file" and a.arg[0] == apply.DROPIN for a in acts)


# ---------- merge-ops Task 0: web unit ----------

def test_web_on_installs_and_enables_unit():
    cfg = set_mode(_cfg(), "server")
    cfg["modules"]["web"] = True
    cfg["web"] = {**cfg.get("web", {}), "public_url": "https://kit.example.com/filament"}  # Ruling AA
    acts = apply.plan(cfg)
    assert "filament-kit-web.service" in _of(acts, "install_unit")
    en = _of(acts, "enable")
    assert en.index("filament-kit-web.service") > en.index("filament-kit.service")
    assert "filament-kit-web.service" not in _of(acts, "disable")
    kinds = [a.kind for a in acts]
    assert acts.index(apply.Action("install_unit", "filament-kit-web.service")) < kinds.index("daemon_reload")


def test_web_explicitly_off_disables_unit():
    acts = apply.plan(set_mode(_cfg(), "server"))
    assert "filament-kit-web.service" in _of(acts, "disable")
    assert "filament-kit-web.service" not in _of(acts, "install_unit")


def test_legacy_plan_unchanged_by_new_modules():
    # No `modules` key: nothing about web/remote/orders appears at all.
    for a in apply.plan({}):
        assert "web" not in str(a.arg) and "nginx" not in str(a.arg)


def test_remote_adds_apt_packages():
    cfg = set_mode(_cfg(), "server")
    cfg["modules"].update(web=True, remote=True)
    cfg["web"]["public_url"] = "https://kit.example.com"
    assert {"nginx", "certbot"} <= set(_of(apply.plan(cfg), "apt"))
