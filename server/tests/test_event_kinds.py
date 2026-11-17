"""The catalogue of event kinds is a published contract (R80 section 2): these tests pin every name, so renaming or
removing one fails here. Adding a kind or a value name is fine (the sets below are checked as "at least")."""
import pytest

from filament_kit import event_kinds as ek

R, C = ek.RAISES, ek.CLEARS

# kind: (severities, condition, base, keyed, values)
P2 = {
    "print.started": (("info",), None, None, True, {"job", "printer"}),
    "print.paused": (("warn",), R, "print-paused", True, {"job", "percent", "reason", "stage"}),
    "print.runout": (("warn",), R, "print-paused", True, {"job", "percent", "slot"}),
    "print.resumed": (("ok",), C, "print-paused", True, {"job"}),
    "print.finished": (("ok",), C, "print-paused", True, {"job", "minutes"}),
    "print.failed": (("bad",), C, "print-paused", True, {"job", "percent", "reason", "error"}),
    "printer.error": (("bad",), None, None, True, {"code", "text"}),
    "printer.offline": (("warn",), R, "printer-offline", True, set()),
    "printer.online": (("ok",), C, "printer-offline", True, set()),
    "usage.recorded": (("info",), None, None, True, {"printer", "job", "spool", "material", "grams"}),
    "spool.low": (("warn",), R, "spool-low", True, {"spool", "filament", "material", "grams", "in_stock"}),
    "spool.ok": (("ok",), C, "spool-low", True, {"spool"}),
    "storage.low": (("warn", "bad"), R, "storage-low", False, {"free", "total", "percent"}),
    "storage.ok": (("ok",), C, "storage-low", False, {"free", "total"}),
    "device.down": (("warn",), R, "device-down", True, set()),
    "device.up": (("ok",), C, "device-down", True, set()),
    "check.failed": (("warn",), R, "check", True, {"text"}),
    "check.ok": (("ok",), C, "check", True, {"text"}),
}
for _n in ("added", "opened", "weighed", "moved", "emptied", "loaded", "unloaded"):
    P2[f"spool.{_n}"] = (("info",), None, None, True,
                         {"spool", "before_location", "after_location", "before_grams", "after_grams",
                          "before_slot", "after_slot"})
LATER = ("hub.started", "hub.updated", "backup.finished", "backup.failed", "device.paired", "device.removed",
         "settings.changed")


@pytest.mark.parametrize("name", sorted(P2))
def test_every_phase_2_kind_is_present_with_its_severity_condition_and_values(name):
    sev, cond, base, keyed, values = P2[name]
    k = ek.get(name)
    assert k is not None, f"{name} was renamed or removed"
    assert k.severities == sev and k.severity == sev[0]
    assert (k.condition, k.base, k.keyed) == (cond, base, keyed)
    assert values <= set(k.values), f"a value name of {name} was renamed or removed"
    assert k.emitted


@pytest.mark.parametrize("name", LATER)
def test_the_later_names_are_reserved_and_not_emitted(name):
    k = ek.get(name)
    assert k is not None and not k.emitted and k.condition is None


def test_the_catalogue_has_the_expected_number_of_kinds():
    assert len(ek.KINDS) >= len(P2) + len(LATER)
    assert {n for n, k in ek.KINDS.items() if k.emitted} >= set(P2)


def test_every_condition_has_a_raising_and_a_clearing_kind():
    raises = {k.base for k in ek.KINDS.values() if k.condition == R}
    clears = {k.base for k in ek.KINDS.values() if k.condition == C and not k.key_from_data}
    assert raises == clears == {"print-paused", "printer-offline", "spool-low", "storage-low", "device-down", "check"}


def test_severities_are_only_the_four_banner_kinds():
    assert ek.SEVERITIES == ("info", "ok", "warn", "bad")
    assert all(set(k.severities) <= set(ek.SEVERITIES) for k in ek.KINDS.values())


def test_subject_and_actor_types_are_the_ruled_ones():
    assert ek.SUBJECT_TYPES == ("printer", "spool", "device", "location", "hub")
    assert ek.ACTOR_TYPES == ("hub", "device", "page", "cli", "connector")


def test_condition_keys():
    assert ek.condition_key(ek.get("print.paused"), "p-3") == "print-paused:p-3"
    assert ek.condition_key(ek.get("storage.low"), "") == "storage-low"
    assert ek.condition_key(ek.get("check.failed"), "", "hub-disk") == "check:hub-disk"
    assert ek.condition_key(ek.get("print.started"), "p-3") is None


def test_the_additions_of_r80_e2_and_e5():
    cc = ek.get("condition.cleared")
    assert (cc.severities, cc.condition, cc.key_from_data, set(cc.values)) == (("info",), C, True, {"key", "reason"})
    assert dict(cc.choices)["reason"] == ("reconciled", "subject_removed", "feature_off")
    lr = ek.get("location.renamed")
    assert lr.severity == "info" and lr.condition is None and set(lr.values) == {"from", "to", "spools"}
    for name in ("print.started", "print.paused", "print.runout", "print.resumed", "print.finished",
                 "print.failed", "usage.recorded"):
        assert {"run", "printer_job"} <= set(ek.get(name).values), name
    for name in ("added", "opened", "weighed", "moved", "emptied", "loaded", "unloaded"):
        assert "batch" in ek.get(f"spool.{name}").values
    assert "direction" in ek.get("storage.low").values
