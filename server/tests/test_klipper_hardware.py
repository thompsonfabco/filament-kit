"""bridge.klipper.hardware: klipper_hardware.xml loader, validator, override and gcode templates."""
import pytest

from filament_kit.bridge.klipper import hardware as kh


@pytest.fixture(autouse=True)
def etc(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path))
    kh._reset_cache()
    yield tmp_path
    kh._reset_cache()


def test_bundled_file_is_valid():
    assert kh.validate(kh.BUNDLED.read_bytes()) == []
    assert kh.load().errors == []


def test_SV08_model_values():
    m = kh.load().model("SOVOL-SV08-MAX")
    assert m.verified is True
    assert m.system == "single"
    assert [(o.nozzle, o.printer) for o in m.orca] == [
        ("0.4", "Sovol SV08 MAX"), ("0.6", "Sovol SV08 MAX 0.6"), ("1.0", "Sovol SV08 MAX 1.0")]
    assert [s.label for s in m.slots] == ["T0"]
    assert m.detect_objects == ("gcode_macro DEMON_START",)
    assert m.light_on == "SET_LED LED=chamber_light WHITE=1 SYNC=0"
    assert not hasattr(m, "scan_ok") and not hasattr(m, "tag_source")


def test_m1d_is_unverified_with_seven_tools():
    m = kh.load().model("sovol-m1d")
    assert m.verified is False
    assert m.system == "tool-macros"
    assert [(s.n, s.label) for s in m.slots] == [(0, "L")] + [(i, f"C{i}") for i in range(1, 7)]


def test_unknown_model_is_generic():
    hw = kh.load()
    assert hw.model("no-such").key == "generic"
    assert hw.model("generic").system == "auto"


def test_systems():
    hw = kh.load()
    assert hw.system("single").set_gcode == "SET_ACTIVE_SPOOL ID={spool}"
    assert hw.system("afc").detect_object == "AFC"
    assert hw.system("lane-data").detect_namespace == "lane_data"
    assert hw.system("tool-macros").spool_var_macro == "_FK_TOOL_SPOOLS"


def test_fill():
    assert kh.fill("FK_SET_TOOL_SPOOL TOOL={tool} ID={spool}", tool=3, spool=12) == "FK_SET_TOOL_SPOOL TOOL=3 ID=12"
    assert kh.fill("SET_SPOOL_ID LANE={lane} SPOOL_ID=", lane="lane_1") == "SET_SPOOL_ID LANE=lane_1 SPOOL_ID="


def test_fill_rejects_unknown_placeholder():
    with pytest.raises(ValueError):
        kh.fill("X {bed}", bed=1)


def test_fill_rejects_bad_lane():
    with pytest.raises(ValueError):
        kh.fill("L {lane}", lane="a;b")


def test_fill_rejects_negative_or_bool_spool():
    with pytest.raises(ValueError):
        kh.fill("S {spool}", spool=-1)
    with pytest.raises(ValueError):
        kh.fill("S {spool}", spool=True)


def _override(etc, body: str, version="1.1"):
    (etc / "klipper_hardware.xml").write_text(f'<klipper-hardware version="{version}">{body}</klipper-hardware>',
                                              encoding="utf-8")


def test_template_with_newline_is_error(etc):
    assert kh.load().errors == []
    _override(etc, '<filament-systems><system key="single" adapter="single">'
                   '<set-gcode>SET_ACTIVE_SPOOL ID={spool}\nFIRMWARE_RESTART</set-gcode></system></filament-systems>')
    hw = kh.load()
    assert len(hw.errors) == 1 and "must be one line" in hw.errors[0]
    assert hw.system("single").set_gcode == "SET_ACTIVE_SPOOL ID={spool}"   # last good kept


def test_template_with_unknown_placeholder_is_error(etc):
    _override(etc, '<filament-systems><system key="single" adapter="single">'
                   '<set-gcode>X {bed}</set-gcode></system></filament-systems>')
    errors = kh.load().errors
    assert len(errors) == 1 and "unknown placeholder(s) bed" in errors[0]


def test_override_merges_per_key(etc):
    _override(etc, '<models><model key="x" name="X printer" system="single"><detect><object>gcode_macro X</object>'
                   '</detect></model></models>')
    hw = kh.load()
    assert hw.errors == []
    assert hw.model("x").name == "X printer"
    assert hw.model("SOVOL-SV08-MAX").name == "Sovol SV08 MAX"


def test_model_with_unknown_system_is_error(etc):
    _override(etc, '<models><model key="x" name="X" system="nope"/></models>')
    errors = kh.load().errors
    assert len(errors) == 1 and "system 'nope' is not a <system> key" in errors[0]


def test_unknown_element_warning(etc):
    _override(etc, '<models><model key="x" name="X" system="single"><gizmo/></model></models>')
    hw = kh.load()
    assert hw.errors == []
    assert any("gizmo" in w for w in hw.warnings)


def test_old_file_with_dropped_fields_still_loads(etc):
    """FA-071: <scan-feedback> and <tag-source> were read by nothing and left the schema; an old file that has them loads."""
    _override(etc, '<models><model key="old" name="Old" system="single"><scan-feedback ok="_X ID={spool}" '
                   'unknown="_Y"/><tag-source url="http://{host}:5002/last-tag"/></model></models>')
    hw = kh.load()
    assert hw.errors == []
    assert hw.warnings == []
    assert hw.model("old").name == "Old"


def test_say():
    hw = kh.load()
    assert hw.say("T0") == ["tool zero"]


def test_light_gcode_with_a_placeholder_is_refused(etc):
    """Final review M7: light gcode has nothing to fill in."""
    _override(etc, '<models><model key="x" name="X" system="single"><light on="SET_LED ID={spool}" off="OFF"/>'
                   '</model></models>')
    errors = kh.load().errors
    assert len(errors) == 1 and "may not have placeholders" in errors[0]


def test_an_override_version_that_is_not_above_the_bundled_one_is_ignored_with_a_warning(etc):
    body = '<models><model key="x" name="X printer" system="single"/></models>'
    _override(etc, body, version="1.0")
    hw = kh.load()
    assert hw.errors == [] and "x" not in hw.models
    assert any("not newer than the kit's own" in w for w in hw.warnings)
    _override(etc, body, version="1.1")
    assert "x" in kh.load().models


@pytest.mark.parametrize("version", ["0.9", "2.0", "abc"])
def test_an_override_of_another_major_version_is_an_error_and_the_bundled_data_stays(etc, version):
    _override(etc, '<models><model key="x" name="X printer" system="single"/></models>', version=version)
    hw = kh.load()
    assert len(hw.errors) == 1 and f"version '{version}' not supported" in hw.errors[0]
    assert "x" not in hw.models and hw.model("SOVOL-SV08-MAX").name == "Sovol SV08 MAX"
