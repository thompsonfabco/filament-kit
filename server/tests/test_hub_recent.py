"""Recently added on the Hub page (design 09 S2.7, 03 6): the list, one record, and a record changed by hand, by the Label Reader
and undone, in a real browser (tests/hub_drive.mjs) and under the page audit (tests/aut5_run.mjs). The page, its example data and the
runners are test_hub_page_audit.py's. The same skips: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time

import pytest

from filament_kit import config, intake, intake_history, inventory, pairing
from filament_kit.spoolman import Spoolman

from test_hub_page_audit import CODE, ITEM, ROOT, _missing, _node, _run, _serve, hub_app  # noqa: F401  (hub_app is a fixture)

PHOTO = base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABQODxIPDRQSEBIXFRQYHjIhHhwcHj0sLiQySUBMS0dARkVQWnNiUFVtVkVGZIhlbXd7gYKBTmCNl4x9lnN+gXz/2wBDARUXFx4aHjshITt8U0ZTfHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHz/wAARCAAwAEADASIAAhEBAxEB/8QAGAABAQEBAQAAAAAAAAAAAAAAAAYEBQP/xAAiEAABAQgDAQEAAAAAAAAAAAAAAgEDBREWVKPRBGTiEkH/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AnQC5p+GW2RWwIYFzT8Mtsitin4ZbZFbAhgXNPwy2yK2KfhltkVsCGBc0/DLbIrZDADp0/E7bInZzDp1BE7nGnQCn4nbZE7FPxO2yJ2KgidzjToVBE7nGnQHlyYPz+K4U+fuPh2mU2/aWym2X40wm7kxjn8pwpy/f/btUps+EsnJs/wAYYQAAAFNV3Sy+SZAFNV3Sy+RV3Sy+SZAFNV3Sy+RV3Sy+SZAAAAf/2Q==")      # a 64 x 48 label picture
RECENT_RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2, "overflow": "Overflow",
                "sealed_location": "Sealed stock"}
LEVELS = {k: "high" for k in ("vendor", "name", "material", "color_hex", "net", "tare", "density", "nozzle", "bed",
                              "nozzle_range", "bed_range", "price_per_kg")}


def _seed(sm, item, *, source, photos=0, read=None):
    """One record: the spools are added to the fake Spoolman, the read (when there is one) is set aside as the Hub does."""
    read_id = None
    if read is not None:
        read_id = f"rd{abs(hash((item['name'], source))) % 10**8}"
        intake_history.stash_read(read_id, [PHOTO] * photos, {"items": [{**item, **read.pop("item")}], **read}, "", None)
    done = inventory.add_and_link(sm, [dict(item)], RECENT_RULES, False, None)
    return intake_history.record_save(done.saved, source=source, read_id=read_id), done.spool_ids


class HttpsOrigin:
    """ASGI wrapper for a browser test over plain http: the Hub serves https, so the page's writes must come with
    `Origin: https://<host>`; the browser sends http, and this sets the header the Hub expects (shipped code is untouched)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            host = dict(scope["headers"]).get(b"host", b"")
            scope = {**scope, "headers": [(k, v) for k, v in scope["headers"] if k != b"origin"] + [(b"origin", b"https://" + host)]}
        await self.app(scope, receive, send)


@pytest.fixture
def recent_hub(hub_app, spoolman_url, monkeypatch):
    """The Hub page with four records in Recently added (a read by the On this Hub engine with a medium and a low field, a Cloud
    read that is not rated, one added by hand, one with long names), one of them revised by hand and undone; yields (the page's
    address, {name: record id}). The Label Reader's engine is a fake that proposes nozzle 235."""
    app, port = hub_app
    cfg = config.load()
    cfg["modules"]["ai_intake"] = True                 # the Label Reader is on
    config.save(cfg)
    sm = Spoolman(spoolman_url)
    for h in intake_history.list_records(False)["records"]:        # the audit fixture's own record has no spool in Spoolman
        shutil.rmtree(intake_history._dir(h["id"]))
    base = {"count": 1, "sealed": False, "density": 1.24, "tare": 200, "net": 1000, "nozzle": 220, "bed": 55, "material": "PLA"}
    ids, spools = {}, {}
    ids["hand"], spools["hand"] = _seed(sm, {**base, "vendor": "Prusament", "name": "PLA Galaxy Silver", "color_hex": "C0C0C8"}, source="phone")      # a spool typed in: no photo
    ids["cloud"], spools["cloud"] = _seed(sm, {**base, "vendor": "Bambu Lab", "name": "PETG HF Orange", "material": "PETG", "color_hex": "D9822B", "count": 2},
                                          source="web", photos=1, read={"item": {"confidence_levels": {k: None for k in LEVELS}},
                                                                       "engine": {"reader": "cloud", "model": "claude", "tier": None},
                                                                       "confidence_rated": False})
    for values in ({"nozzle": 230}, None, {"bed": 60}):            # a revision by hand, undone, and another: the revisions list has both
        if values:
            intake_history.apply(sm, ids["cloud"], item=0, values=values, device="setup page")
        else:
            intake_history.undo(sm, ids["cloud"], None)
    ids["long"], spools["long"] = _seed(sm, {**base, "vendor": "Polymaker Industrial Filament Manufacturing Company",
                                             "name": "PolyTerra PLA Extra Long Product Line Name Charcoal Black Matte Edition", "color_hex": "2B2B2E"},
                                        source="station", photos=1, read={"item": {"confidence_levels": dict(LEVELS), "confidence": 0.95},
                                                                          "engine": {"reader": "local", "model": "label-reader", "tier": "full"},
                                                                          "confidence_rated": True})
    ids["local"], spools["local"] = _seed(sm, {**base, "vendor": "Polymaker", "name": "PolyTerra PLA Charcoal Black", "color_hex": "2B2B2E", "nozzle_range": "190-230"},
                                          source="phone", photos=2,
                                          read={"item": {"confidence_levels": {**LEVELS, "color_hex": "medium", "net": "low"}, "confidence_filled": ["color_hex"], "confidence": 0.72},
                                                "engine": {"reader": "local", "model": "label-reader", "tier": "full"}, "confidence_rated": True})
    def revise_by_the_engine(*a, **k):
        time.sleep(1.2)                  # the Label Reader takes a moment: a second press can come while it is asked
        return {"items": [{**k["revise"][0], "nozzle": 235}], "reader": "local", "confidence": 0.9, "note": "second look at the label",
                "engine": {"reader": "local", "model": "label-reader", "tier": "full"}}
    monkeypatch.setattr(intake, "_call", revise_by_the_engine)
    running = _serve(HttpsOrigin(app), port)
    try:
        yield running.url + "/setup", {**ids, "spools": spools}
    finally:
        running.stop()


def _drive(url: str, steps: str, ids: dict, *extra: str, **arg) -> subprocess.CompletedProcess:
    """tests/hub_drive.mjs: real clicks and typing in a headless browser; the setup code and the record ids go in as the argument."""
    node = _node()
    if not node:
        _missing("the browser flow needs Node 22 or later")
    run = subprocess.run([node, str(ROOT / "tests" / "hub_drive.mjs"), "--url", url, "--steps", str(ROOT / "tests" / steps),
                          "--arg", json.dumps({"ids": ids, "code": CODE, **arg}), *extra], capture_output=True, text=True, timeout=300)
    if run.returncode == 2 and "no Chrome, Edge or Chromium" in run.stderr:
        _missing("the browser flow needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    if run.returncode == 3:
        _missing("the browser flow: " + run.stderr.strip())
    return run


def test_recently_added_passes_the_page_audit_with_every_kind_of_record(recent_hub):
    """The list and four records (marks and a note, revisions, an item choice, long names) at 1280 and 320 px, light and dark; no allow-list."""
    url, ids = recent_hub
    views = ",".join(["#recent"] + [f"#recent/{ids[k]}" for k in ("local", "cloud", "long", "hand")] + ["#recent/000000000000"])
    run = _run("--url", url, "--views", views)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout)["views"] == 6 * 2 * 2


def test_recently_added_does_not_scroll_sideways_at_320_px_with_long_names_and_a_wide_font(monkeypatch, recent_hub):
    monkeypatch.setattr(pairing, "short_hostname", lambda: "runnervm8axu0")
    url, ids = recent_hub
    fonts = ["--font-dir", os.environ["AUT5_FONT_DIR"]] if os.environ.get("AUT5_FONT_DIR") else ["--wide-font"]
    run = _run("--url", url, "--views", f"#recent,#recent/{ids['long']},#recent/{ids['local']}", "--widths", "320", *fonts)
    assert run.returncode in (0, 1), run.stdout + run.stderr
    found = [(r["view"], r["scheme"], f["detail"]) for r in json.loads(run.stdout).get("report", [])
             for f in r["findings"] if f["check"] == "sideways scroll"]
    assert not found, found


@pytest.mark.parametrize("width", [1280, 320])
def test_recently_added_flow_in_a_browser(recent_hub, width):
    """List, filter, open a record, the photo viewer, Edit by hand (the code asked in place, a field error, Save changes), Ask the
    Label Reader (the empty note, Discard, Accept), Undo, Newer and Older, and a record that is gone: with real clicks and typing."""
    url, ids = recent_hub
    run = _drive(url, "recent_flow.mjs", ids, "--width", str(width))
    assert run.returncode == 0, run.stdout + run.stderr


class FailHistory:
    """ASGI wrapper: the list of additions answers 500 (the error state); shipped code is untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/setup/api/intake/history":
            await send({"type": "http.response.start", "status": 500, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"error": "the history is unreadable"}'})
            return
        await self.app(scope, receive, send)


@pytest.fixture
def variant(request, hub_app):
    """Recently added in a state of its own: `empty`, `off` (the Label Reader switched off, one record), `nophoto` (only the On this Hub engine, a record without a photo), `paging` (55 records)
    or `error` (the list cannot be read); yields (the page's address, the id of one record, its name)."""
    app, port = hub_app
    kind = request.param
    cfg = config.load()
    cfg["modules"]["ai_intake"] = kind not in ("off", "nophoto")
    cfg["modules"]["local_intake"] = kind == "nophoto"        # only the On this Hub engine: a record without a photo cannot be revised
    cfg["intake"] = {**(cfg.get("intake") or {}), "history_keep": 80, **({"reader": "local"} if kind == "nophoto" else {})}
    config.save(cfg)
    for h in intake_history.list_records(False)["records"]:
        shutil.rmtree(intake_history._dir(h["id"]))
    rid = None
    for i in range({"empty": 0, "error": 1, "off": 1, "nophoto": 1, "paging": 55}[kind]):
        rid = intake_history.record_save([{"values": {**ITEM, "name": f"Line {i:02d}"}, "spool_ids": [1000 + i], "filament_id": 3}], source="phone")
    running = _serve(HttpsOrigin(FailHistory(app) if kind == "error" else app), port)
    try:
        yield running.url + "/setup", {"one": rid}, kind
    finally:
        running.stop()


@pytest.mark.parametrize("variant", ["empty", "off", "nophoto", "paging", "error"], indirect=True)
def test_recently_added_states_in_a_browser(variant):
    """The empty state, the Label Reader switched off, no photo for the only engine, the second page of 55 records, and a list that cannot be read."""
    url, ids, kind = variant
    run = _drive(url, "recent_states.mjs", ids, scenario=kind)
    assert run.returncode == 0, run.stdout + run.stderr


def test_recently_added_keeps_what_belongs_to_a_record_and_sends_each_press_once(recent_hub):
    """A note typed at one record stays out of the next; an open edit form and its typed values survive a redraw of the page; a
    wrong range shows its catalogue text, never a key; a double press of Save or Undo and an Ask asked again after a redraw send
    one request each; the Label Reader's own note is shown."""
    url, ids = recent_hub
    run = _drive(url, "recent_guards.mjs", ids)
    assert run.returncode == 0, run.stdout + run.stderr
