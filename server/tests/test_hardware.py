"""bridge/hardware.py: the bundled bambu_hardware.xml, the /etc override, the validator, schemes, presence, speech."""
import os

import pytest

from filament_kit.bridge import hardware, models


@pytest.fixture(autouse=True)
def _etc(tmp_path, monkeypatch):
    """Every test gets its own (empty) /etc/filament-kit and a fresh loader cache."""
    etc = tmp_path / "etc"
    etc.mkdir()
    monkeypatch.setenv("FK_ETC", str(etc))
    hardware._reset_cache()
    yield etc
    hardware._reset_cache()


def _override(etc, body: str, version: str = "1"):
    p = etc / "bambu_hardware.xml"
    p.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<bambu-hardware version="{version}">{body}</bambu-hardware>',
                 encoding="utf-8")
    st = p.stat()   # a rewrite within the same mtime tick must still count as a change
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000 * (1 + len(body) % 7)))
    return p


# --- the bundled file ---------------------------------------------------------------------------------------------

def test_bundled_file_loads_clean():
    hw = hardware.load()
    assert hw.errors == []
    assert hardware.load() is hw   # cached while nothing changed


@pytest.mark.parametrize("code,name,camera,cmax", [
    ("BL-P001", "X1 Carbon", "hls", None), ("3DPrinter-X1-Carbon", "X1 Carbon", "hls", None),
    ("BL-P002", "X1", "hls", None), ("3DPrinter-X1", "X1", "hls", None), ("C13", "X1E", "hls", 60),
    ("O1D", "H2D", "hls", 65), ("O1E", "H2D Pro", "hls", 65), ("O1S", "H2S", "hls", 65), ("O1C", "H2C", "hls", 65),
    ("O1C2", "H2C", "hls", 65), ("N6", "X2D", "hls", 65), ("N7", "P2S", "hls", None), ("C11", "P1P", "mjpeg", None),
    ("C12", "P1S", "mjpeg", None), ("N1", "A1 mini", "mjpeg", None), ("N2S", "A1", "mjpeg", None),
    ("N9", "A2L", "mjpeg", None),
])
def test_every_model_carried_over(code, name, camera, cmax):
    m = hardware.load().model(code)
    assert (m.known, m.name, m.camera, m.chamber_max, m.preset_name) == (True, name, camera, cmax, f"Bambu Lab {name}")


@pytest.mark.parametrize("typed,name", [
    ("X1C", "X1 Carbon"), ("x1 carbon", "X1 Carbon"), ("Bambu Lab H2D", "H2D"), ("h2d pro", "H2D Pro"),
    ("H2DPRO", "H2D Pro"), ("A1MINI", "A1 mini"), ("o1e", "H2D Pro"), ("h2d", "H2D"),
])
def test_model_by_typed_name(typed, name):
    assert hardware.load().model(typed).name == name


def test_h2d_record():
    m = hardware.load().model("O1D")
    assert m.code == "O1D" and m.nozzles == 2 and m.presence == "bits-v1"
    assert m.gcode_only_failed_is_finish is True
    assert [(e.id, e.label, e.say) for e in m.externals] == [(254, "Ext-L", "external left"),
                                                            (255, "Ext-R", "external right")]
    assert m.numbering == ("shift8", "legacy")
    assert m.light_nodes == ("chamber_light", "chamber_light2")
    assert m.ftp_dirs == ("/", "/cache")


@pytest.mark.parametrize("code", ["BL-P001", "C12", "N1", "N2S", "C11", "BL-P002"])
def test_single_external_printers_keep_ext(code):
    m = hardware.load().model(code)
    assert [(e.id, e.label) for e in m.externals] == [(254, "Ext")]
    assert m.gcode_only_failed_is_finish is False


@pytest.mark.parametrize("code", ["zz", "", None, "Bambu Lab Q9"])
def test_unknown_model_is_generic(code):
    m = hardware.load().model(code)
    assert m.known is False
    assert (m.camera, m.chamber_max, m.nozzles, m.numbering, m.preset_name, m.presence, m.light_nodes) == \
        (None, None, 1, ("legacy",), None, None, ())
    assert [(e.id, e.label) for e in m.externals] == [(254, "Ext")]
    assert "unknown" in m.name.lower()


# --- AMS types ----------------------------------------------------------------------------------------------------

def test_ams_type_by_module_code():
    hw = hardware.load()
    assert hw.ams_type(0, "N3F05", "O1D", 4).key == "ams_2pro"
    assert hw.ams_type(128, "N3S05", "O1D", 1).key == "ams_ht"
    assert hw.ams_type(128, "n3s05", "O1D", 1).name == "AMS HT"


def test_ams_type_by_model_and_range():
    hw = hardware.load()
    assert hw.ams_type(0, None, "N2S", 4).key == "ams_lite"
    assert hw.ams_type(0, None, hw.model("A1 mini"), 4).key == "ams_lite"
    t = hw.ams_type(3, None, "C12", 4)
    assert t.key == "ams" and t.known is False      # first-gen AMS: unverified until a capture confirms it
    assert hw.ams_type(130, None, "O1D", 1).key == "ams_ht"
    t = hw.ams_type(129, None, None, None)
    assert t.key == "ams_ht" and t.slots == 1 and t.label == "ht" and t.label_prefix == "HT-"


def test_ams_type_unknown_is_generic():
    hw = hardware.load()
    t = hw.ams_type(300, "ZZZ99", "O1D", 2)
    assert (t.known, t.slots) == (False, 2)
    t = hw.ams_type(5, None, "O1D", 6)   # no type has 6 slots
    assert (t.known, t.slots, t.label) == (False, 6, "letter")
    assert hw.ams_type(5, None, None, None).slots == 4


# --- numbering schemes --------------------------------------------------------------------------------------------

def test_legacy_scheme():
    s = hardware.load().scheme("legacy")
    assert (s.kind, s.per_unit, s.ht_from) == ("linear", 4, 128)
    assert [s.encode(0, 0), s.encode(1, 3), s.encode(15, 3), s.encode(128, 0), s.encode(129, 0)] == [0, 7, 63, 128, 129]
    assert [s.decode(0), s.decode(7), s.decode(63), s.decode(128), s.decode(129)] == \
        [(0, 0), (1, 3), (15, 3), (128, 0), (129, 0)]
    assert s.decode(-1) is None
    with pytest.raises(ValueError):
        s.encode(32, 0)       # would land on 128 = the first HT number
    with pytest.raises(ValueError):
        s.encode(0, 4)


def test_shift8_scheme():
    s = hardware.load().scheme("shift8")
    assert s.encode(1, 1) == 257 and s.encode(129, 0) == 33024 and s.encode(0, 3) == 3
    assert s.decode(33024) == (129, 0) and s.decode(258) == (1, 2)
    assert s.decode(-1) is None
    for a in list(range(16)) + [128, 129, 143]:
        for t in range(4 if a < 128 else 1):
            assert s.decode(s.encode(a, t)) == (a, t)
    with pytest.raises(ValueError):
        s.encode(0, 256)


def test_unknown_scheme_raises():
    with pytest.raises(KeyError):
        hardware.load().scheme("nope")


# --- presence -----------------------------------------------------------------------------------------------------

def test_presence_bits_v1():
    p = hardware.load().presence("bits-v1")
    assert (p.exist, p.reading) == ("tray_exist_bits", "tray_reading_bits")
    assert [p.bit(0, 0), p.bit(1, 2), p.bit(3, 3), p.bit(128, 0), p.bit(129, 0)] == [0, 6, 15, 16, 17]
    assert p.bit(4, 0) is None       # beyond what the layout describes: unknown, never guessed
    assert p.bit(200, 0) is None and p.bit(None, 0) is None and p.bit("x", 0) is None
    assert hardware.load().presence("nope") is None


@pytest.mark.parametrize("expr,id_,tray,want", [
    ("id*4+tray", 2, 1, 9), ("16+id-128", 130, 0, 18), ("(id+1)*2", 3, 0, 8), ("1<<id+tray", 1, 1, 4),
    ("id - tray - 1", 5, 1, 3), ("2*3+4", 0, 0, 10), ("id<<2|tray", 0, 0, None),
])
def test_expression_grammar(expr, id_, tray, want):
    if want is None:
        with pytest.raises(ValueError):
            hardware.parse_expr(expr)
    else:
        assert hardware.parse_expr(expr)(id_, tray) == want


@pytest.mark.parametrize("expr", [
    "__import__('os')", "id**2", "id/2", "x", "id+", "(id", "id)", "", "1 << 99", "id.real", "tray()", "-id",
    "1" * 40,
])
def test_expression_rejects(expr):
    with pytest.raises(ValueError):
        hardware.parse_expr(expr)(1, 1)


# --- speech -------------------------------------------------------------------------------------------------------

def test_say():
    hw = hardware.load()
    assert hw.say("A") == ["a"]
    assert hw.say("HT-B") == ["h", "t", "b"]
    assert hw.say("AB") == ["a", "b"]
    assert hw.say("Ext-L") == ["external", "left"]
    assert hw.say("Ext") == ["external"]
    assert hw.say("B12") == ["b", "1", "2"]
    assert hw.say("") == []


# --- override -----------------------------------------------------------------------------------------------------

def test_override_wins_per_element(_etc):
    _override(_etc, '<models><model code="C12" name="P1S Plus" camera="hls" nozzles="1">'
                    '<external id="254" label="Ext" say="external"/><numbering ref="legacy"/></model>'
                    '<model code="ZZ9" name="Z9" camera="mjpeg"><numbering ref="mine"/></model></models>'
                    '<numbering-schemes><scheme key="mine" kind="shift" bits="4"/></numbering-schemes>'
                    '<speech><word text="AB" say="alpha bravo"/></speech>')
    hw = hardware.load()
    assert hw.errors == []
    assert hw.model("C12").name == "P1S Plus" and hw.model("C12").camera == "hls"
    assert hw.model("O1D").name == "H2D"                       # untouched elements stay
    assert hw.model("zz9").known and hw.model("ZZ9").numbering == ("mine",)
    assert hw.scheme("mine").encode(2, 1) == 33
    assert hw.scheme("legacy").encode(1, 0) == 4
    assert hw.say("AB") == ["alpha", "bravo"] and hw.say("HT-A") == ["h", "t", "a"]
    assert models.printer_preset_name("C12") == "Bambu Lab P1S Plus"


def test_override_reread_on_change(_etc):
    assert hardware.load().model("N9").camera == "mjpeg"
    _override(_etc, '<models><model code="N9" name="A2L" camera="hls"/></models>')
    assert hardware.load().model("N9").camera == "hls"
    (_etc / "bambu_hardware.xml").unlink()
    assert hardware.load().model("N9").camera == "mjpeg"


@pytest.mark.parametrize("body,version,needle", [
    ('<models><model code="C12"', "1", "parse"),                                   # not well-formed
    ('<models><model name="X"/></models>', "1", "code"),                            # missing required attribute
    ('<models><model code="C12" name="P1S" nozzles="two"/></models>', "1", "nozzles"),
    ('<models><model code="C12" name="P1S" camera="vhs"/></models>', "1", "camera"),
    ('<models><model code="C12" name="P1S"><numbering ref="nope"/></model></models>', "1", "nope"),
    ('<models><model code="C12" name="P1S" presence="nope"/></models>', "1", "nope"),
    ('<presence-layouts><layout key="x" exist="a"><range from="0" to="3" bit="__import__(1)"/></layout>'
     '</presence-layouts>', "1", "bit"),
    ('<numbering-schemes><scheme key="s" kind="spiral"/></numbering-schemes>', "1", "kind"),
    ('<numbering-schemes><scheme key="s" kind="shift"/></numbering-schemes>', "1", "bits"),
    ('', "2", "version"),
    ('', "2.1", "version"),
    ('', "one", "version"),
    ('<models><model code="C12" name="P1S"/><model code="c12" name="P1S"/></models>', "1", "twice"),
])
def test_bad_override_keeps_last_good(_etc, body, version, needle):
    _override(_etc, '<models><model code="C12" name="P1S Good" camera="mjpeg"/></models>')
    assert hardware.load().model("C12").name == "P1S Good"
    _override(_etc, body, version)
    hw = hardware.load()
    assert hw.model("C12").name == "P1S Good"       # last good data still in use
    assert hw.errors and "bambu_hardware.xml" in hw.errors[0]
    assert needle.lower() in " ".join(hw.errors).lower()


def test_bad_override_on_first_load_uses_bundled(_etc):
    _override(_etc, "<models><model/></models>")
    hw = hardware.load()
    assert hw.model("C12").name == "P1S" and hw.errors


def test_entity_expansion_refused(_etc):
    p = _etc / "bambu_hardware.xml"
    p.write_text('<?xml version="1.0"?><!DOCTYPE b [<!ENTITY a "x">]><bambu-hardware version="1"><speech>'
                 '<word text="Q" say="&a;"/></speech></bambu-hardware>', encoding="utf-8")
    hw = hardware.load()
    assert hw.errors and hw.say("Q") == ["q"]


def test_validate_rejects_bundled_style_problems():
    """The validator is usable on its own (the library updater checks a downloaded file before installing it)."""
    good = hardware.BUNDLED.read_bytes()
    assert hardware.validate(good) == []
    assert hardware.validate(b"<bambu-hardware/>")   # no version


# --- fix round 1 --------------------------------------------------------------------------------------------------

def test_unknown_module_code_is_generic():
    hw = hardware.load()
    t = hw.ams_type(0, "ZZZ", "C12", 4)
    assert (t.known, t.key, t.slots) == (False, "generic", 4)
    assert hw.ams_type(0, "ZZZ", "N2S", 4).known is False      # a code that matches nothing beats the model list
    assert hw.ams_type(0, "N3F05", "O1D", 4).known is True


def test_unknown_elements_and_attributes_are_warnings(_etc):
    _override(_etc, '<models><model code="C12" name="P1S Next" bogus="1" camera="mjpeg">'
                    '<future-thing x="1"/><numbering ref="legacy"/></model></models><gadgets><g/></gadgets>',
              version='1.3" flavour="new')
    hw = hardware.load()
    assert hw.errors == []
    assert hw.model("C12").name == "P1S Next"
    w = " ".join(hw.warnings)
    for needle in ("bogus", "future-thing", "gadgets", "flavour"):
        assert needle in w
    assert "bambu_hardware.xml" in hw.warnings[0]
    assert hardware.load().warnings == hw.warnings


def test_bundled_has_no_warnings():
    assert hardware.load().warnings == []


def test_version_major_minor(_etc):
    _override(_etc, '<models><model code="C12" name="P1S Minor"/></models>', version="1.3")
    assert hardware.load().model("C12").name == "P1S Minor"
    _override(_etc, '<models><model code="C12" name="P1S Major"/></models>', version="2")
    hw = hardware.load()
    assert hw.model("C12").name == "P1S Minor" and "version" in hw.errors[0]


def test_collision_check_covers_every_tray(_etc):
    # tray 3 of unit 0 lands on bit 3 = unit 1 tray 0 with a 3-wide stride
    _override(_etc, '<presence-layouts><layout key="bits-v1" exist="tray_exist_bits">'
                    '<range from="0" to="3" bit="id*3+tray"/></layout></presence-layouts>')
    hw = hardware.load()
    assert hw.errors and "bit" in hw.errors[0]
    _override(_etc, '<presence-layouts><layout key="bits-v1" exist="tray_exist_bits">'
                    '<range from="0" to="3" bit="id*4+tray+50"/></layout></presence-layouts>')
    assert hardware.load().errors and "0-63" in hardware.load().errors[0]


def test_empty_hardware_has_builtin_schemes():
    hw = hardware.Hardware()
    assert hw.scheme("legacy").encode(1, 2) == 6 and hw.scheme("shift8").encode(1, 2) == 258
    assert hw.model("O1D").known is False


def test_say_with_model():
    hw = hardware.load()
    assert hw.say("Ext", "C12") == ["external"]
    assert hw.say("Ext-L", hw.model("O1D")) == ["external", "left"]
    assert hw.say("Ext-R", "O1D") == ["external", "right"]
    assert hw.say("HT-A", "O1D") == ["h", "t", "a"]


def test_model_say():
    hw = hardware.load()
    assert hw.model("BL-P001").say == "x one c"          # P4: words the reader firmware can speak
    assert hw.model("O1D").say == "h two d"
    assert all(m.say for m in hw.models)
    assert hw.model("zz").say


@pytest.mark.parametrize("ext", [
    '<external id="254" label="Ext-L" alias="Ext-R"/><external id="255" label="Ext-R"/>',   # another holder's label
    '<external id="254" label="Ext-L" alias="Ext-L"/><external id="255" label="Ext-R"/>',   # its own label
    '<external id="254" label="Ext-L" alias="ext-r"/><external id="255" label="Ext-R"/>',   # case does not matter
])
def test_external_alias_must_not_name_a_label_of_the_model(_etc, ext):
    """P3 (P2 review minor): an alias that is a current label would send that holder's spools and slot-map keys
    to the wrong holder (or nowhere): the file is refused."""
    _override(_etc, f'<models><model code="C12" name="P1S Bad">{ext}</model></models>')
    hw = hardware.load()
    assert hw.model("C12").name == "P1S" and hw.errors
    assert "alias" in " ".join(hw.errors).lower()
