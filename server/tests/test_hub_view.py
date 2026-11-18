"""The Hub at a glance (R83 s5, hub_view.py): the shape of GET /api/hub, its redaction and its fallbacks."""
import json

import pytest

from filament_kit import __version__, config, events, hub_view, modules, reader_tokens, status, updates
from filament_kit.bridge import registry
from filament_kit.bridge.registry import Printer

HOME_ADDR = "10.1.2.3"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    mods = {n: True for n in modules.MODES["server"]}
    config.save({"modules": mods, "server_name": "Workshop", "spoolman_url": "http://127.0.0.1:7912"})
    registry.upsert(Printer("01S00C123456789", "Office H2D", "O1D", HOME_ADDR, "13572468", True))
    monkeypatch.setattr(status, "collect", lambda cfg, cf=None, sp=None: [
        status.Row("ok", "Spoolman answering", group="Spoolman"),
        status.Row("fail", f"printer 01S00C123456789 at {HOME_ADDR} is offline", f"check {HOME_ADDR}", group="Printers"),
        status.Row("detail", "a continuation line", group="Printers"),
        status.Row("info", "Filament Catalog not downloaded", group="Filament Catalog")])


def get(**kw):
    kw.setdefault("paired", [])
    kw.setdefault("readers", [])
    return hub_view.build(**kw)


def test_the_answer_has_exactly_the_contracts_keys():
    r = get(host="hub.local", getting_started={"done": 4, "total": 8, "hidden": False, "finished": False})
    assert set(r) == {"name", "version", "update_available", "checks", "getting_started", "features", "catalog",
                      "backup", "reader", "devices", "records_kept", "spoolman_url", "hub_page"} | (
        {"newest"} if "newest" in r else set())
    assert r["name"] == "Workshop" and r["version"] == updates.current_version()
    assert r["getting_started"] == {"done": 4, "total": 8, "hidden": False, "finished": False}
    assert isinstance(r["records_kept"], int) and r["update_available"] is False
    json.dumps(r)                                                  # all of it is JSON


def test_checks_are_the_overviews_rows_redacted_without_the_detail_rows():
    checks = get()["checks"]
    assert [c["state"] for c in checks] == ["ok", "look", "note"]
    assert [c["group"] for c in checks] == ["Spoolman", "Printers", "Filament Catalog"]
    bad = checks[1]
    assert HOME_ADDR not in json.dumps(checks) and "01S00C123456789" not in json.dumps(checks)
    assert "fix" in bad and "fix" not in checks[0]


def test_features_name_every_module_and_say_whether_it_is_on():
    f = {x["id"]: x for x in get()["features"]}
    assert set(f) == set(modules.MODULES) and f["server"]["on"] is True and f["server"]["name"] == "Hub service"
    assert f["klipper"]["on"] is False and f["backup"]["on"] in (True, False)


def test_getting_started_without_the_panel_is_hidden():
    assert get()["getting_started"] == {"done": 0, "total": 0, "hidden": True, "finished": False}


def test_version_and_update(monkeypatch):
    monkeypatch.setattr(updates, "summary", lambda: {"installed": "0.5.0", "latest": "0.7.0", "newer": True,
                                                     "checked_at": 1_800_000_000, "half_install": False})
    r = get()
    assert r["version"] == "0.5.0" and r["update_available"] is True
    assert r["newest"] == {"version": "0.7.0", "checked_at": "2027-01-15T08:00:00+00:00"}
    monkeypatch.setattr(updates, "summary", lambda: {"installed": "0.7.0", "latest": None, "newer": False,
                                                     "checked_at": None, "half_install": False})
    assert "newest" not in get()


def test_catalog_says_its_version_and_last_check(monkeypatch, no_library):
    assert get()["catalog"] == {}                                    # nothing downloaded, never checked
    from filament_kit import library
    monkeypatch.setattr(library, "last_check", lambda: {"at": 1_800_000_000, "ok": True, "error": None})
    assert get()["catalog"]["checked_at"] == "2027-01-15T08:00:00+00:00"


def test_catalog_with_a_library():
    c = get()["catalog"]
    assert isinstance(c["version"], int)                             # the test library is in place


def test_backup_last_time_and_nightly(monkeypatch):
    """`backup.finished` is not written yet (the event store reserves it): the time shows once it is."""
    assert "last_at" not in get()["backup"]
    pages = [{"events": [{"id": 1, "at": "2027-01-14T03:00:00Z"}, {"id": 2, "at": "2027-01-15T03:00:00Z"}], "next": 2},
             {"events": [{"id": 3, "at": "2027-01-16T03:00:00Z"}], "next": 3}, {"events": [], "next": 3}]
    asked = []

    def read(since, limit, kinds):
        asked.append((since, kinds))
        return pages[len(asked) - 1]
    monkeypatch.setattr(events, "read", read)
    assert get()["backup"]["last_at"] == "2027-01-16T03:00:00+00:00"
    assert asked == [(0, ["backup.finished"]), (2, ["backup.finished"]), (3, ["backup.finished"])]
    cfg = config.load()
    for on in (True, False):
        cfg["modules"] = {**cfg["modules"], "backup": on}
        assert hub_view.build(cfg, paired=[], readers=[])["backup"]["nightly"] is on


def test_reader_engine_and_the_key_never_its_value(tmp_path):
    from filament_kit import cli
    assert get()["reader"]["key_set"] is False
    (tmp_path / "etc" / cli.KEY_FILE).write_text("sk-ant-secret-value")
    r = get()["reader"]
    assert r["key_set"] is True and "secret" not in json.dumps(get())
    assert r["engine"] in ("local", "cloud", "off")


def test_devices_have_names_kinds_versions_and_one_is_this():
    paired = [{"id": "d1", "name": "Pixel", "paired": 1, "last_seen": 1_800_000_000, "type": None},
              {"id": "d2", "name": "station", "paired": 1, "last_seen": None, "type": "station", "version": "0.5.0"},
              {"id": "d3", "name": "Shop PC", "paired": 1, "last_seen": None, "type": None, "kind": "pc",
               "version": "99.0.0"},
              {"id": "d4", "name": "Old PC", "paired": 1, "last_seen": None, "type": None, "kind": "pc",
               "version": "0.0.1"},
              {"id": "d5", "name": "Phone", "paired": 1, "last_seen": None, "type": None, "kind": "phone",
               "version": "1.2", "out_of_date": True}]
    d = {x["name"]: x for x in get(paired=paired, this_device="d1")["devices"]}
    assert d["Pixel"] == {"name": "Pixel", "kind": None, "last_seen": "2027-01-15T08:00:00+00:00",
                          "out_of_date": False, "this": True}
    assert d["station"]["kind"] == "station" and d["station"]["version"] == "0.5.0" and d["station"]["out_of_date"]
    assert d["Shop PC"]["out_of_date"] is False and d["Old PC"]["out_of_date"] is True
    assert d["Phone"]["out_of_date"] is True and all(not x["this"] for n, x in d.items() if n != "Pixel")
    assert "id" not in d["Pixel"]


def test_a_device_that_sends_no_version_is_never_out_of_date():
    d = get(paired=[{"id": "d", "name": "station", "paired": 1, "last_seen": None, "type": "station"}])["devices"][0]
    assert d["out_of_date"] is False and "version" not in d


def test_the_tag_readers_are_devices():
    rows = [{"id": "r1", "name": "bench", "created": "x", "build": 100, "last_seen": "2027-01-15T08:00:00+00:00",
             "out_of_date": True},
            {"id": "r2", "name": "never", "created": "x", "build": None, "last_seen": None, "out_of_date": False}]
    d = {x["name"]: x for x in get(readers=rows)["devices"]}
    assert d["bench"] == {"name": "bench", "kind": "reader", "version": "100",
                          "last_seen": "2027-01-15T08:00:00+00:00", "out_of_date": True, "this": False}
    assert d["never"]["kind"] == "reader" and "version" not in d["never"]


def test_readers_come_from_the_token_store_when_not_given(tmp_path):
    reader_tokens.TokenStore().issue("bench")
    d = hub_view.build(paired=[])["devices"]
    assert [(x["name"], x["kind"]) for x in d] == [("bench", "reader")]


def test_links_are_built_from_the_host_the_caller_used():
    cfg = config.load()
    cfg["modules"] = {**cfg["modules"], "spoolman": True}
    r = hub_view.build(cfg, host="hub.local", paired=[], readers=[])
    assert r["spoolman_url"] == "http://hub.local:7912" and r["hub_page"] == "https://hub.local/setup/"
    r = hub_view.build(cfg, host=None, paired=[], readers=[])
    assert "spoolman_url" not in r and "hub_page" not in r                 # the public address: neither is reachable
    for bad in ("evil.com/x", "a b", "", "http://x", "x:80/", "<script>"):
        r = hub_view.build(cfg, host=bad, paired=[], readers=[])
        assert "hub_page" not in r and "spoolman_url" not in r


def test_spoolman_elsewhere_is_the_configured_address():
    cfg = config.load()
    cfg["modules"] = {k: v for k, v in cfg["modules"].items() if k != "spoolman"}
    cfg["modules"]["spoolman"] = False
    cfg["spoolman_url"] = "http://nas.local:7912"
    assert hub_view.build(cfg, host="hub.local", paired=[], readers=[])["spoolman_url"] == "http://nas.local:7912"
    assert hub_view.build(cfg, host=None, paired=[], readers=[])["spoolman_url"] == "http://nas.local:7912"
    cfg["spoolman_url"] = "not a url"
    assert "spoolman_url" not in hub_view.build(cfg, host="hub.local", paired=[], readers=[])


def test_a_source_that_fails_does_not_fail_the_answer(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(status, "collect", boom)
    monkeypatch.setattr(updates, "summary", boom)
    monkeypatch.setattr(events, "read", boom)
    monkeypatch.setattr(reader_tokens, "readers", boom)
    r = hub_view.build(paired=[])
    assert r["checks"] == [] and r["backup"]["nightly"] in (True, False) and "last_at" not in r["backup"]
    assert r["devices"] == [] and r["version"] == __version__ and r["update_available"] is False


@pytest.mark.parametrize("a,b,late", [("0.5.0", "0.7.0", True), ("0.7.0", "0.7.0", False), ("0.7.1", "0.7.0", False),
                                      ("0.7", "0.7.0", False), ("0.6.9", "0.7", True), ("v0.5.0", "0.7.0", True),
                                      (None, "0.7.0", False), ("junk", "0.7.0", False), ("0.5.0", None, False),
                                      ("0.7.0-rc1", "0.7.0", False), ("0.10.0", "0.9.0", False)])
def test_older(a, b, late):
    assert hub_view.older(a, b) is late


@pytest.mark.parametrize("v,out", [(1_800_000_000, "2027-01-15T08:00:00+00:00"), ("2027-01-15T08:00:00Z",
                                   "2027-01-15T08:00:00+00:00"), ("2027-01-15T03:00:00-05:00",
                                   "2027-01-15T03:00:00-05:00"), ("2027-01-15T08:00:00", "2027-01-15T08:00:00+00:00"),
                                   (None, None), ("", None), ("x", None), (True, None), (float("inf"), None)])
def test_iso(v, out):
    assert hub_view.iso(v) == out


def test_spoolman_url_is_given_as_it_is_and_absent_when_it_cannot_be_reached():
    cfg = config.load()
    cfg["modules"] = {**cfg["modules"], "spoolman": True}
    assert hub_view.build(cfg, host="hub.local", paired=[], readers=[])["spoolman_url"] == "http://hub.local:7912"
    assert "spoolman_url" not in hub_view.build(cfg, host=None, paired=[], readers=[])


def test_every_time_is_iso_8601_with_an_offset_and_null_stays_null(monkeypatch):
    import re
    monkeypatch.setattr(updates, "summary", lambda: {"installed": "0.5.0", "latest": "0.7.0", "newer": True,
                                                     "checked_at": 1_800_000_000.7, "half_install": False})
    paired = [{"id": "d", "name": "P", "paired": 1, "last_seen": 1_800_000_000, "type": None},
              {"id": "e", "name": "Q", "paired": 1, "last_seen": None, "type": None}]
    r = get(paired=paired)
    times = [r["newest"]["checked_at"], r["devices"][0]["last_seen"]]
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", t) for t in times)
    assert r["devices"][1]["last_seen"] is None
