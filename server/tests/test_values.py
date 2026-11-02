from filament_kit.library import Lookup
from filament_kit.profiles import values as V

STD, HF = "Direct Drive Standard", "Direct Drive High Flow"


def entry(fields=None, ranges=None, **top):
    e = {"vendor": "Acme", "product": "PLA", "material": "PLA", "fields": fields or {},
         "published_ranges": ranges or {}, "sources": ["https://example.com/tds.pdf", "https://example.com/2"]}
    e.update(top)
    return e


def apply(cfg, e, template=None, nozzle="0.4", chamber_max=None, material=None):
    log = []
    cfg.setdefault("name", "Acme PLA @Bambu Lab H2D 0.4 nozzle")
    V.apply_library(cfg, e, template=template or {}, printer="Bambu Lab H2D", nozzle=nozzle,
                    chamber_max=chamber_max, log=log)
    return log


def test_clamp_parent_value_into_range():
    e = entry({"nozzle_temperature_range_low": ["190"], "nozzle_temperature_range_high": ["230"]})
    cfg = {}
    log = apply(cfg, e, template={"nozzle_temperature": ["250"]})
    assert cfg["nozzle_temperature"] == ["230"]
    assert cfg["nozzle_temperature_range_low"] == ["190"] and cfg["nozzle_temperature_range_high"] == ["230"]
    assert any("published 190-230" in line for line in log)


def test_spoolman_value_outside_range_kept_and_reported():
    e = entry({"nozzle_temperature_range_low": ["190"], "nozzle_temperature_range_high": ["230"]})
    template = {"nozzle_temperature": ["220"], "filament_extruder_variant": [STD]}
    cfg = {"name": "Acme PLA @Bambu Lab H2D 0.4 nozzle"}
    apply(cfg, e, template=template)
    sv = V.SpoolmanValues(material="PLA", density=None, cost=0, nozzle=245, bed=None, nozzle_range=None, colors="")
    keys = V.apply_spoolman(cfg, sv, variants=[STD], template=template)
    assert "nozzle_temperature" in keys
    log = []
    V.report_outside(cfg, e, keys, log)
    assert cfg["nozzle_temperature"] == ["245"]
    assert any("your nozzle_temperature 245 is outside the published 190-230; kept" in line for line in log)


def test_never_invent_midpoint():
    e = entry({"nozzle_temperature_range_low": ["200"]})
    cfg = {}
    apply(cfg, e, template={"nozzle_temperature": ["190"], "nozzle_temperature_initial_layer": ["300"]})
    assert cfg["nozzle_temperature"] == ["200"]
    assert "nozzle_temperature_initial_layer" not in cfg  # 300 kept: no high bound, no upper clamp
    assert "nozzle_temperature_range_high" not in cfg


def test_no_vitrification_ever():
    e = entry({"temperature_vitrification": ["60"]}, {"_vitrification": "60 (Tg)"})
    cfg = {"temperature_vitrification": ["45"]}
    apply(cfg, e, template={"temperature_vitrification": ["45"]})
    assert cfg["temperature_vitrification"] == ["45"]
    cfg2 = {}
    apply(cfg2, e, template={"temperature_vitrification": ["45"]})
    assert "temperature_vitrification" not in cfg2


def test_fan_off_exact_zero_only():
    cfg = {}
    apply(cfg, entry(ranges={"fan_max_speed": "0 (OFF)"}), template={"fan_min_speed": ["40"], "fan_max_speed": ["80"]})
    assert cfg["fan_min_speed"] == ["0"] and cfg["fan_max_speed"] == ["0"]
    for text in ("0", "0%", " 0 (off) "):
        assert V.fan_off(entry(ranges={"fan_max_speed": text}))
    cfg = {}
    apply(cfg, entry(ranges={"fan_max_speed": "0-30"}), template={"fan_min_speed": ["20"], "fan_max_speed": ["80"]})
    assert cfg["fan_max_speed"] == ["30"]
    assert "fan_min_speed" not in cfg
    assert not V.fan_off(entry(ranges={"fan_max_speed": "0-30"}))
    assert not V.fan_off(entry(ranges={"fan_max_speed": "OFF-20%"}))


def test_hardened_rules():
    cfg = {}
    apply(cfg, entry(material="PETG-CF"), template={})
    assert cfg["required_nozzle_HRC"] == ["40"]
    cfg = {}
    apply(cfg, entry(ranges={"_hardened_nozzle_required": "No - brass ok"}), template={})
    assert "required_nozzle_HRC" not in cfg
    cfg = {}
    apply(cfg, entry(ranges={"_hardened_nozzle_required": "Hard steel nozzle required"}), template={})
    assert cfg["required_nozzle_HRC"] == ["40"]
    assert V.hardened(entry(), "PLA-GF")
    assert V.hardened(None, "PA6-CF20") or V.hardened(None, "PA CF15")
    assert not V.hardened(entry(), "PLA")


def test_chamber_only_with_chamber():
    e = entry(ranges={"chamber_temperatures": "25-45"})
    cfg = {}
    apply(cfg, e, template={"chamber_temperatures": ["70"]}, chamber_max=None)
    assert "chamber_temperatures" not in cfg
    cfg = {}
    apply(cfg, e, template={"chamber_temperatures": ["70"]}, chamber_max=65)
    assert cfg["chamber_temperatures"] == ["45"]
    cfg = {}
    apply(cfg, entry(ranges={"chamber_temperatures": "50-80"}), template={"chamber_temperatures": ["70"]},
          chamber_max=65)
    assert cfg["chamber_temperatures"] == ["65"]


def test_mvs_cap_only_04():
    e = entry({"filament_max_volumetric_speed": ["12"]})
    cfg = {}
    apply(cfg, e, template={"filament_max_volumetric_speed": ["21", "35"]}, nozzle="0.4")
    assert cfg["filament_max_volumetric_speed"] == ["12", "12"]
    cfg = {}
    apply(cfg, e, template={"filament_max_volumetric_speed": ["21", "35"]}, nozzle="0.6")
    assert "filament_max_volumetric_speed" not in cfg


def test_variant_temps_keep_offset():
    template = {"nozzle_temperature": ["220", "230"], "filament_extruder_variant": [STD, HF]}
    sv = V.SpoolmanValues(material="PLA", density=None, cost=0, nozzle=210, bed=None, nozzle_range=None, colors="")
    cfg = {}
    V.apply_spoolman(cfg, sv, variants=[STD, HF], template=template)
    assert cfg["nozzle_temperature"] == ["210", "220"]


def test_spoolman_values_odd_input():
    fs = [{"id": 1, "name": "PLA+ Grey", "material": "PLA", "density": 1.24, "settings_extruder_temp": None,
           "settings_bed_temp": 0, "weight": 1000},
          {"id": 2, "name": "PLA+ Red", "material": "PLA", "settings_extruder_temp": 0, "settings_bed_temp": "60",
           "weight": 1000},
          {"id": 3, "name": "PLA+ Blue", "material": None, "density": "1.26", "settings_extruder_temp": "215",
           "extra": {"nozzle_range": '"200-230"'}}]
    sv = V.spoolman_values(fs)
    assert sv.nozzle == 215
    assert sv.bed == 60
    assert sv.density == 1.25
    assert sv.cost == 0
    assert sv.material == "PLA"
    assert sv.nozzle_range == (200, 230)
    assert sv.colors == "Blue, Grey, Red"
    priced = V.spoolman_values([{"name": "x", "price": 20, "weight": 1000}, {"name": "y", "price": "30", "weight": 500},
                                {"name": "z", "price": 0, "weight": 1000}])
    assert priced.cost == 40.0
    assert priced.density is None and priced.nozzle is None and priced.nozzle_range is None
    bad = V.spoolman_values([{"name": "x", "extra": {"nozzle_range": "not json"}}])
    assert bad.nozzle_range is None


def test_local_overrides_library_per_key():
    lib = entry({"nozzle_temperature_range_low": ["190"], "nozzle_temperature_range_high": ["230"]},
                {"bed_all_plates": "50-60"}, bambu_parent="Generic PLA")
    loc = {"vendor": "Acme", "product": "PLA", "material": "PLA+",
           "fields": {"nozzle_temperature_range_high": ["220"]}}
    m = V.merged_entry(Lookup(lib, loc))
    assert m["fields"] == {"nozzle_temperature_range_low": ["190"], "nozzle_temperature_range_high": ["220"]}
    assert m["published_ranges"] == {"bed_all_plates": "50-60"}
    assert m["material"] == "PLA+" and m["bambu_parent"] == "Generic PLA"
    assert lib["fields"]["nozzle_temperature_range_high"] == ["230"]  # deep copy
    assert V.merged_entry(Lookup(None, None)) is None
    assert V.merged_entry(Lookup(None, loc)) == loc
    assert V.merged_entry(Lookup(lib, None)) == lib


def test_unsupported_nozzles():
    assert V.unsupported_nozzles(entry(ranges={"_not_supported": "0.2, High Flow nozzle"})) == {"0.2"}
    assert V.unsupported_nozzles(None) == set()


def test_spec_notes_has_sources():
    e = entry({"nozzle_temperature_range_low": ["190"], "nozzle_temperature_range_high": ["230"],
               "filament_max_volumetric_speed": ["12"]}, {"bed_all_plates": "50-60", "_drying": "55C 6h"})
    text = V.spec_notes(e)
    assert text.startswith("Manufacturer specs:")
    assert "https://example.com/tds.pdf" in text
    assert "nozzle 190-230 C" in text and "bed 50-60" in text and "max flow 12 mm3/s" in text
    assert V.spec_notes(None) is None


def test_rng_and_bounds():
    assert V.rng("50-70 (glue)") == (50.0, 70.0)
    assert V.rng("70-100 (min 60 highly recommended)") == (60.0, 100.0)
    assert V.rng("room temperature") is None
    assert V.rng(None) is None
    assert V.nozzle_bounds({"nozzle_temperature_range_high": ["230"]}) == (None, 230.0)


def test_no_nil_written_and_plates_skip_zero():
    e = entry(ranges={"bed_all_plates": "50-60"})
    cfg = {}
    apply(cfg, e, template={"hot_plate_temp": ["0"], "textured_plate_temp": ["nil"], "eng_plate_temp": ["80"]})
    assert "hot_plate_temp" not in cfg and "textured_plate_temp" not in cfg
    assert cfg["eng_plate_temp"] == ["60"]
    assert "nil" not in str(cfg)


def test_apply_spoolman_bed_range_density_cost():
    template = {"hot_plate_temp": ["55", "55"], "filament_extruder_variant": [STD, HF]}
    sv = V.SpoolmanValues(material="PLA", density=1.24, cost=19.5, nozzle=None, bed=60, nozzle_range=(200, 230),
                          colors="")
    cfg = {}
    keys = V.apply_spoolman(cfg, sv, variants=[STD, HF], template=template)
    assert cfg["hot_plate_temp"] == ["60", "60"]
    assert cfg["textured_plate_temp_initial_layer"] == ["60"]
    assert cfg["nozzle_temperature_range_low"] == ["200"] and cfg["nozzle_temperature_range_high"] == ["230"]
    assert cfg["filament_density"] == ["1.24"] and cfg["filament_cost"] == ["19.5"]
    assert "nozzle_temperature" not in cfg
    assert keys == {"hot_plate_temp", "hot_plate_temp_initial_layer", "textured_plate_temp",
                    "textured_plate_temp_initial_layer", "nozzle_temperature_range_low",
                    "nozzle_temperature_range_high", "filament_density", "filament_cost"}
    cfg = {}
    keys = V.apply_spoolman(cfg, V.SpoolmanValues(None, None, 0, None, None, None, ""), variants=[STD], template={})
    assert cfg == {} and keys == set()
