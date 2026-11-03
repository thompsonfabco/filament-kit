"""filament-kit migrate-scanner: the owner's H2D from h2d-filament-scanner to the kit (spec P §7, plan P7)."""
from __future__ import annotations

import json

import pytest

from filament_kit import cli, migrate_scanner
from filament_kit.bridge import ams, layout, mapping, registry, status
from filament_kit.bridge.registry import Printer
from filament_kit.spoolman import Spoolman

SERIAL = "SERIAL0000000000"
NAME = "Workshop H2D"           # not "H2D": the prefix must come from the registry
D = status.DASH


def loc(label: str) -> str:
    return f"{NAME} {D} AMS {label}"


def tag(a: int, t: int) -> str:
    return f"H2D:ams{a}:tray{t}"


def cal_file(tmp_path, **over):
    """The scanner's learned calibration (usage_tracker.new_cal shape): shift8, 0/2/32768/33024 = AMS 1 trays 1/3,
    HT 1, HT 2 from the calibration job, 1 learned from a print."""
    c = {"version": 1, "status": "calibrated", "scheme": "shift8", "calibrated_at": 1761800000,
         "last_attempt": 1761800000, "problems": [], "mismatch_streak": 0, "history": [],
         "table": {"0": {"slot": tag(0, 0), "source": "job", "at": 1},
                   "2": {"slot": tag(0, 2), "source": "job", "at": 1},
                   "32768": {"slot": tag(128, 0), "source": "job", "at": 1},
                   "33024": {"slot": tag(129, 0), "source": "job", "at": 1},
                   "1": {"slot": tag(0, 1), "source": "print", "at": 2}}}
    c.update(over)
    p = tmp_path / "calibration.json"
    p.write_text(json.dumps(c), encoding="utf-8")
    return p


def j(v) -> str:
    return json.dumps(v)


@pytest.fixture
def env(tmp_path, monkeypatch, spoolman_url, spoolman_fake_store):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_BACKUPS", str(tmp_path / "backups"))
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "config.json").write_text(json.dumps({"spoolman_url": spoolman_url}), encoding="utf-8")
    registry.upsert(Printer(SERIAL, NAME, "O1D", "192.0.2.1", "code", True))
    st = spoolman_fake_store
    st["fields"]["spool"] = [{"key": k, "name": k, "field_type": "text", "order": 0, "entity_type": "spool"}
                             for k in ("active_tray", "prev_location")]
    st["filaments"][1] = {"id": 1, "name": "PLA", "vendor_id": None, "material": "PLA", "weight": 1000,
                          "spool_weight": 200, "extra": {}}
    rows = [  # id, location, extra
        (1, "H2D - AMS slot 1", {"active_tray": j(tag(0, 0)), "prev_location": j("Rack 1")}),
        (2, "H2D - AMS slot 3", {"active_tray": j(tag(0, 2)), "prev_location": j("Rack 2")}),
        (3, "H2D - AMS HT 1", {"active_tray": j(tag(128, 0))}),
        (4, "H2D - AMS HT 2", {"active_tray": j(tag(129, 0)), "prev_location": j("Box")}),
        (5, "H2D - External left", {"active_tray": j(tag(254, 0))}),
        (6, "H2D - External right", {}),
        (7, "Rack 1", {"prev_location": j("Rack 3")}),
        (8, "H2D - Garage shelf", {"active_tray": j("x")}),
        (9, "H2D - AMS slot 2", {"active_tray": j("")}),
    ]
    for sid, where, extra in rows:
        st["spools"][sid] = {"id": sid, "registered": "2026-01-01T00:00:00Z", "first_used": None,
                             "last_used": None, "filament_id": 1, "location": where, "comment": None,
                             "archived": False, "extra": dict(extra), "initial_weight": 1000, "spool_weight": 200,
                             "used_weight": 0, "remaining_weight": 1000}
    st["next"]["spool"] = 10
    return {"tmp": tmp_path, "store": st, "sm": Spoolman(spoolman_url), "url": spoolman_url}


def run(env, cal, out, **kw):
    kw.setdefault("sm", env["sm"])
    return migrate_scanner.run(str(cal), out=out.append, **kw)


def snapshot(store):
    return {sid: (s["location"], dict(s["extra"])) for sid, s in store["spools"].items()}


def backups(env):
    d = env["tmp"] / "backups"
    return sorted(d.glob("migrate-scanner-*.json")) if d.exists() else []


def test_dry_run_prints_every_change_and_writes_nothing(env, tmp_path):
    before = snapshot(env["store"])
    out: list[str] = []
    assert run(env, cal_file(tmp_path), out) == 0
    text = "\n".join(out)
    for old, new in [("H2D - AMS slot 1", "A1"), ("H2D - AMS slot 3", "A3"), ("H2D - AMS slot 2", "A2"),
                     ("H2D - AMS HT 1", "HT-A"), ("H2D - AMS HT 2", "HT-B"),
                     ("H2D - External left", "Ext-L"), ("H2D - External right", "Ext-R")]:
        assert f"{old} → {loc(new)}" in text
    assert "H2D - Garage shelf" in text and "not moved" in text            # reported, untouched
    assert "Rack 1 →" not in text
    assert "A1 = 0" in text and "A3 = 2" in text and "HT-A = 32768" in text and "HT-B = 33024" in text
    assert "Dry run" in text
    assert snapshot(env["store"]) == before
    assert not backups(env)
    assert ams.load_map(SERIAL).slots == {}


def test_apply_moves_spools_seeds_the_map_and_marks_it(env, tmp_path):
    out: list[str] = []
    assert run(env, cal_file(tmp_path), out, apply=True) == 0
    sp = env["store"]["spools"]
    assert sp[1]["location"] == loc("A1") and sp[2]["location"] == loc("A3") and sp[9]["location"] == loc("A2")
    assert sp[3]["location"] == loc("HT-A") and sp[4]["location"] == loc("HT-B")
    assert sp[5]["location"] == loc("Ext-L") and sp[6]["location"] == loc("Ext-R")
    for sid in (1, 2, 3, 4, 5):
        assert json.loads(sp[sid]["extra"]["active_tray"]) == ""
    assert sp[1]["extra"]["prev_location"] == j("Rack 1") and sp[4]["extra"]["prev_location"] == j("Box")
    assert "active_tray" not in sp[6]["extra"]
    assert sp[7]["location"] == "Rack 1" and sp[7]["extra"] == {"prev_location": j("Rack 3")}
    assert sp[8]["location"] == "H2D - Garage shelf" and sp[8]["extra"]["active_tray"] == j("x")

    m = ams.load_map(SERIAL)
    assert m.slots == {"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0},
                       "A3": {"ams_id": 0, "tray_id": 2, "global_id": 2},
                       "HT-A": {"ams_id": 128, "tray_id": 0, "global_id": 32768},
                       "HT-B": {"ams_id": 129, "tray_id": 0, "global_id": 33024}}
    assert m.scheme == "shift8" and m.calibrated and not m.observe and m.learned == {"1": "A2"}
    assert m.fingerprint is None and not m.stale            # LayoutWatch adopts the live layout at the first report
    view = mapping.Mapper(None).view(SERIAL)
    assert view["state"] == "done" and view["step"] == migrate_scanner.SEEDED_STEP
    assert view["calibrated"] and view["scheme"] == "shift8"

    (b,) = backups(env)
    assert str(b) in "\n".join(out)
    data = json.loads(b.read_text(encoding="utf-8"))
    old = {s["id"]: s for s in data["spools"]}
    assert set(old) == {1, 2, 3, 4, 5, 6, 9}
    assert old[1]["location"] == "H2D - AMS slot 1" and old[1]["extra"]["active_tray"] == j(tag(0, 0))
    assert data["printer"] == SERIAL and data["slot_map"] is None


def test_kit_labels_come_from_the_layout_code(env, tmp_path):
    """Every new location is status.location(name, layout.label_for(...)): the kit's own label builder."""
    out: list[str] = []
    run(env, cal_file(tmp_path), out, apply=True)
    sp = env["store"]["spools"]
    assert sp[5]["location"] == status.location(NAME, layout.label_for(254, 0, "O1D"))
    assert sp[3]["location"] == status.location(NAME, layout.label_for(128, 0, "O1D"))


def test_backup_is_written_before_any_change(env, tmp_path, monkeypatch):
    seen = []
    real = Spoolman.patch

    def patch(self, path, body):
        seen.append(bool(backups(env)))
        return real(self, path, body)

    real_save = ams.save_map

    def save(serial, m):
        seen.append(bool(backups(env)))
        return real_save(serial, m)

    monkeypatch.setattr(Spoolman, "patch", patch)
    monkeypatch.setattr(ams, "save_map", save)
    assert run(env, cal_file(tmp_path), [], apply=True) == 0
    assert seen and all(seen)


def test_second_apply_changes_nothing_and_says_so(env, tmp_path):
    cal = cal_file(tmp_path)
    assert run(env, cal, [], apply=True) == 0
    before, stamp = snapshot(env["store"]), ams.load_map(SERIAL).updated
    out: list[str] = []
    assert run(env, cal, out, apply=True) == 0
    assert "Nothing to change" in "\n".join(out)
    assert snapshot(env["store"]) == before
    assert ams.load_map(SERIAL).updated == stamp
    assert len(backups(env)) == 1


def test_unknown_entries_are_reported_not_written(env, tmp_path):
    cal = cal_file(tmp_path)
    c = json.loads(cal.read_text(encoding="utf-8"))
    c["table"]["7"] = {"slot": "somewhere", "source": "job"}
    c["table"]["9"] = {"slot": tag(0, 3), "source": "guess"}
    c["table"]["x"] = {"slot": tag(0, 3), "source": "job"}
    c["table"]["11"] = "H2D:ams0:tray3"
    cal.write_text(json.dumps(c), encoding="utf-8")
    out: list[str] = []
    assert run(env, cal, out, apply=True) == 0
    text = "\n".join(out)
    for k in ("7", "9", "x", "11"):
        assert f"entry {k!r}" in text
    m = ams.load_map(SERIAL)
    assert set(m.slots) == {"A1", "A3", "HT-A", "HT-B"} and m.learned == {"1": "A2"}
    assert "A4" not in m.slots


def test_entry_against_the_scheme_drops_the_scheme(env, tmp_path):
    cal = cal_file(tmp_path)
    c = json.loads(cal.read_text(encoding="utf-8"))
    c["table"]["5"] = {"slot": tag(0, 3), "source": "job"}        # shift8 says 3
    cal.write_text(json.dumps(c), encoding="utf-8")
    out: list[str] = []
    assert run(env, cal, out, apply=True) == 0
    m = ams.load_map(SERIAL)
    assert m.scheme is None and m.slots["A4"]["global_id"] == 5
    assert "shift8" in "\n".join(out) and "not seeded" in "\n".join(out)


def test_unknown_scheme_is_not_seeded(env, tmp_path):
    out: list[str] = []
    assert run(env, cal_file(tmp_path, scheme="zigzag"), out, apply=True) == 0
    assert ams.load_map(SERIAL).scheme is None
    assert "zigzag" in "\n".join(out)


def test_uncalibrated_scanner_seeds_an_observe_map(env, tmp_path):
    out: list[str] = []
    assert run(env, cal_file(tmp_path, status="suspect"), out, apply=True) == 0
    m = ams.load_map(SERIAL)
    assert not m.calibrated and m.observe
    assert "observe" in "\n".join(out)


def test_existing_map_is_refused_without_replace(env, tmp_path):
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}}, calibrated=True,
                                     observe=False, scheme="shift8"))
    before = snapshot(env["store"])
    out: list[str] = []
    assert run(env, cal_file(tmp_path), out, apply=True) == 1
    assert "--replace-map" in "\n".join(out)
    assert snapshot(env["store"]) == before                       # nothing written, Spoolman included
    assert set(ams.load_map(SERIAL).slots) == {"A1"}
    assert not backups(env)


def test_replace_map_keeps_the_old_map_in_the_backup(env, tmp_path):
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 7}}, calibrated=True,
                                     observe=False))
    out: list[str] = []
    assert run(env, cal_file(tmp_path), out, apply=True, replace_map=True) == 0
    assert ams.load_map(SERIAL).slots["A1"]["global_id"] == 0
    (b,) = backups(env)
    assert json.loads(b.read_text(encoding="utf-8"))["slot_map"]["slots"]["A1"]["global_id"] == 7


def test_printer_choice(env, tmp_path):
    out: list[str] = []
    assert run(env, cal_file(tmp_path), out, serial="NOPE") == 1
    assert "NOPE" in "\n".join(out)
    registry.upsert(Printer("OTHER1", "Other", "O1D", "192.0.2.2", "c", True))
    out = []
    assert run(env, cal_file(tmp_path), out) == 1                 # two printers: say which
    assert "--printer" in "\n".join(out)
    assert run(env, cal_file(tmp_path), [], serial=SERIAL) == 0


def test_unreadable_calibration_is_refused(env, tmp_path):
    bad = tmp_path / "cal.json"
    bad.write_text("{not json", encoding="utf-8")
    out: list[str] = []
    assert run(env, bad, out, apply=True) == 1
    bad.write_text(json.dumps({"version": 2, "table": {}}), encoding="utf-8")
    assert run(env, bad, out, apply=True) == 1
    assert not backups(env)


def test_cli_dry_run_and_apply_needs_root(env, tmp_path, monkeypatch, capsys):
    cal = cal_file(tmp_path)
    assert cli.main(["migrate-scanner", str(cal)]) == 0
    assert "Dry run" in capsys.readouterr().out
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert cli.main(["migrate-scanner", str(cal), "--apply"]) == 1
    assert "root" in capsys.readouterr().err
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    assert cli.main(["migrate-scanner", str(cal), "--apply", "--printer", SERIAL]) == 0
    assert env["store"]["spools"][1]["location"] == loc("A1")


# ---------- fix round 1 ----------

def test_learning_scanner_seeds_as_calibrated(env, tmp_path):
    """Ruling BP: the scanner deducted on a "learning" calibration, so the kit does too."""
    out: list[str] = []
    assert run(env, cal_file(tmp_path, status="learning"), out, apply=True) == 0
    m = ams.load_map(SERIAL)
    assert m.calibrated and not m.observe
    assert "observe" not in "\n".join(out).split("Slot map")[-1].split("\n")[-2]


def test_rerun_after_the_kit_learned_is_not_a_refusal(env, tmp_path):
    cal = cal_file(tmp_path)
    assert run(env, cal, [], apply=True) == 0
    m = ams.load_map(SERIAL)
    m.learned["4"] = "A4"
    m.mismatch_streak = 1
    ams.save_map(SERIAL, m)
    stamp = ams.load_map(SERIAL).updated
    out: list[str] = []
    assert run(env, cal, out, apply=True) == 0
    text = "\n".join(out)
    assert "seeded earlier, since updated by the kit" in text and "Nothing to change" in text
    assert ams.load_map(SERIAL).updated == stamp and len(backups(env)) == 1


def test_empty_table_seeds_nothing_and_rerun_writes_nothing(env, tmp_path):
    cal = cal_file(tmp_path, table={})
    out: list[str] = []
    assert run(env, cal, out, apply=True) == 0
    assert "no slot map seeded" in "\n".join(out)
    assert ams.load_map(SERIAL).slots == {} and not (env["tmp"] / "state" / "printers" / SERIAL / "slotmap.json").exists()
    assert env["store"]["spools"][1]["location"] == loc("A1")          # the spools still move
    out = []
    assert run(env, cal, out, apply=True) == 0
    assert "Nothing to change" in "\n".join(out) and len(backups(env)) == 1


def test_map_saved_meanwhile_is_not_overwritten(env, tmp_path, monkeypatch):
    """--replace-map compares and saves: a map saved between the plan and the save wins (no lost update)."""
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 7}}, calibrated=True,
                                     observe=False))
    real = Spoolman.patch

    def patch(self, path, body):            # a mapping job saves while the spools are being moved
        if not getattr(patch, "done", False):
            patch.done = True
            ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 9}},
                                             calibrated=True, observe=False))
        return real(self, path, body)

    monkeypatch.setattr(Spoolman, "patch", patch)
    out: list[str] = []
    assert run(env, cal_file(tmp_path), out, apply=True, replace_map=True) == 1
    assert ams.load_map(SERIAL).slots["A1"]["global_id"] == 9
    assert "changed meanwhile" in "\n".join(out)


def test_no_private_helpers_used():
    import inspect
    src = inspect.getsource(migrate_scanner)
    assert "_ProcessLock" not in src and "status._int" not in src
