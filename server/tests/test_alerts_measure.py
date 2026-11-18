"""The Hub's disk measurement and the running-low list (R80 sections 6 and 7)."""
from collections import namedtuple

import pytest

from filament_kit import alerts, config, inventory

Usage = namedtuple("Usage", "total used free")
GB = 1000 ** 3


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    for name in ("state", "backups", "opt"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_BACKUPS", str(tmp_path / "backups"))
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    alerts.reset()
    yield tmp_path
    alerts.reset()


def disk(monkeypatch, total, free):
    monkeypatch.setattr(alerts.shutil, "disk_usage", lambda p: Usage(total, total - free, free))


@pytest.mark.parametrize("total,free,want", [
    (100 * GB, 50 * GB, "ok"), (100 * GB, 15.1 * GB, "ok"), (100 * GB, 15 * GB, "warn"), (100 * GB, 5.1 * GB, "warn"),
    (100 * GB, 5 * GB, "bad"), (100 * GB, 0.9 * GB, "bad"),
    (10 * GB, 0.99 * GB, "bad"),               # under 1 GB free is always bad, whatever the percentage
    (500 * GB, 1.2 * GB, "bad"),               # over 1 GB free, but 99.8 % used: judged by the percentage
    (1000 * GB, 100 * GB, "warn"),
])
def test_disk_state_by_limits(total, free, want):
    assert alerts.disk_state(int(total), int(free)) == want


def test_disk_state_uses_the_settings_limits():
    alerts.save({"storage_warn_percent": 50, "storage_bad_percent": 60})
    assert alerts.disk_state(100 * GB, 45 * GB) == "warn" and alerts.disk_state(100 * GB, 35 * GB) == "bad"


def test_one_filesystem_when_state_and_backups_share_it(monkeypatch):
    disk(monkeypatch, 100 * GB, 40 * GB)
    fs = alerts.filesystems()
    assert [f["path_label"] for f in fs] == ["state"]
    assert fs[0]["total"] == 100 * GB and fs[0]["free"] == 40 * GB and fs[0]["percent_used"] == 60.0
    assert fs[0]["state"] == "ok"


def test_two_filesystems_when_the_backups_folder_is_on_another_disk(monkeypatch, state):
    disk(monkeypatch, 100 * GB, 40 * GB)
    real = alerts.os.stat
    seen = {}

    def fake(path, *a, **k):
        st = real(path, *a, **k)
        if str(path).startswith(str(state / "backups")):
            seen["x"] = 1
            return type("S", (), {"st_dev": st.st_dev + 1})()
        return st
    monkeypatch.setattr(alerts.os, "stat", fake)
    assert [f["path_label"] for f in alerts.filesystems()] == ["state", "backups"] and seen


def test_a_backups_folder_not_made_yet_is_measured_at_its_parent(monkeypatch, state):
    (state / "backups").rmdir()
    monkeypatch.setenv("FK_BACKUPS", str(state / "backups" / "deeper"))
    disk(monkeypatch, 10 * GB, 9 * GB)
    assert len(alerts.filesystems()) == 1


def test_worst_disk_is_the_one_in_the_worst_state():
    fs = [{"path_label": "state", "state": "warn", "percent_used": 90}, {"path_label": "backups", "state": "bad", "percent_used": 96}]
    assert alerts.worst(fs)["path_label"] == "backups" and alerts.worst([]) is None


def test_items_are_the_sizes_of_what_spoolwarden_keeps(state, monkeypatch):
    (state / "backups" / "b.zip").write_bytes(b"x" * 1000)
    (state / "state" / "events").mkdir()
    (state / "state" / "events" / "2026-11.xml").write_bytes(b"y" * 300)
    (state / "opt" / "local-intake").mkdir()
    (state / "opt" / "local-intake" / "m.bin").write_bytes(b"z" * 5000)
    (state / "state" / "server.log").write_bytes(b"l" * 40)
    monkeypatch.setattr("filament_kit.intake_history._size", lambda: 77)
    got = {i["key"]: i["bytes"] for i in alerts.items()}
    assert got == {"backups": 1000, "photos": 77, "reader": 5000, "events": 300, "logs": 40}
    assert [i["key"] for i in alerts.items()] == ["backups", "photos", "reader", "events", "logs"]


def test_tree_size_does_not_follow_links(state):
    import os
    if os.name == "nt":
        pytest.skip("links")
    (state / "state" / "a").mkdir()
    (state / "state" / "a" / "f").write_bytes(b"1" * 10)
    (state / "state" / "link").symlink_to(state / "backups")
    (state / "backups" / "big").write_bytes(b"2" * 999)
    assert alerts.tree_size(state / "state") == 10


def test_storage_use_has_both_parts(monkeypatch):
    disk(monkeypatch, 10 * GB, 5 * GB)
    u = alerts.storage_use()
    assert set(u) == {"filesystems", "items"} and u["filesystems"][0]["state"] == "ok"
    assert len(u["items"]) == 5


def spool(i, left, *, fid=1, comment="", archived=False, loc="Rack 1", name="PLA Basic", vendor="Acme", **kw):
    return {"id": i, "remaining_weight": left, "comment": comment, "archived": archived, "location": loc,
            "filament": {"id": fid, "name": name, "material": "PLA", "color_hex": "FF0000", "vendor": {"name": vendor}},
            **kw}


def test_running_low_lists_opened_spools_at_or_under_the_threshold_least_first():
    spools = [spool(1, 150), spool(2, 40), spool(3, 151), spool(4, 90, fid=2, name="PETG")]
    got = alerts.running_low(spools)
    assert got["threshold_g"] == 150
    assert [r["id"] for r in got["spools"]] == [2, 4, 1]
    assert got["spools"][0] == {"id": 2, "filament": "Acme PLA Basic", "material": "PLA", "color": "FF0000",
                                "remaining_g": 40, "location": "Rack 1", "in_stock": 2, "last_one": False}


def test_sealed_empty_and_archived_spools_are_not_low():
    sealed = spool(1, 100, comment=inventory.SEALED_COMMENT)
    empty, gone, none = spool(2, 0), spool(3, 50, archived=True), spool(4, None)
    assert alerts.running_low([sealed, empty, gone, none])["spools"] == []


def test_in_stock_counts_other_not_empty_spools_of_the_filament_sealed_included_and_last_one():
    low = spool(1, 50)
    others = [spool(2, 900, comment=inventory.SEALED_COMMENT), spool(3, 0), spool(4, 20, archived=True)]
    row = alerts.running_low([low] + others)["spools"][0]
    assert row["in_stock"] == 1 and row["last_one"] is False
    last = alerts.running_low([low] + others[1:])["spools"][0]
    assert last["in_stock"] == 0 and last["last_one"] is True
    other_line = alerts.running_low([low, spool(9, 800, fid=2)])["spools"][0]
    assert other_line["last_one"] is True


def test_the_threshold_comes_from_the_settings():
    alerts.save({"running_low_g": 30})
    assert alerts.running_low([spool(1, 40), spool(2, 30)])["spools"][0]["id"] == 2
