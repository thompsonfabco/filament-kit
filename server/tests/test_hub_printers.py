"""The Printers section of the Hub page (design 09 S2.4, 03 section 5): the page audit of the collection, an open row and both
drawers (AUT-5, through tests/aut5_run.mjs), and the section pressed in a real headless browser through tests/page_drive.mjs:
mapping progress and Stop that stay, addresses and serials that follow the lock, drawers in every look, and nothing typed left
behind. The page is served with the data of test_hub_page_audit.py plus printers in each state. The same skip rules as the
page audit: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
import os

import pytest

from filament_kit import api, pairing
from filament_kit.bridge import mapping as bridge_mapping, registry, status as bridge_status, tlspin

from test_hub_page_audit import _missing, _node, _run, _serve, hub_app  # noqa: F401
from test_hub_presets_ui import AsHttps, T, _drive
from test_setup_page import CODE, FakeManager
from test_setup_printer_states import _klipper_status

X1 = "00M00A000000001"
MINI = "01P00A000000002"
X1_REPORT = {"gcode_state": "IDLE", "subtask_name": "", "mc_percent": 0, "mc_remaining_time": 0, "layer_num": 0, "total_layer_num": 0,
             "ams": {"tray_now": "1", "ams": [{"id": "0", "tray": [
                 {"id": str(i), "tray_type": t, "tray_color": c, "tray_info_idx": "GFA00"} for i, (t, c) in enumerate(
                     [("PLA", "47C1A8FF"), ("PLA", "F5C242FF"), ("PETG", "2B2B2EFF"), ("", "")])]}]}}


class _Manual:
    """The mapping drawer's session: A1 confirmed, A2 asked, the printer reports A2 loaded."""
    session = {"session": "s1", "open": True, "dual_nozzle": False, "reports_loads": True, "offer_report": False,
               "step": {"position": {"id": "a2", "label": "A2"}, "say": "Load A2 to the nozzle, then wait.",
                        "seen": {"reported": {"ams_id": 0, "tray_id": 1}, "reported_label": "A2", "nozzle": None, "nozzle_reported": False, "settled": True},
                        "ask": "The printer now reports A2 loaded. Is that the A2 you loaded?"},
               "positions": [{"id": "a1", "label": "A1", "status": "confirmed", "reported_label": "A1", "nozzle": None, "at": None},
                             {"id": "a2", "label": "A2", "status": "pending", "reported_label": None, "nozzle": None, "at": None},
                             {"id": "a3", "label": "A3", "status": "by_hand", "reported_label": "A3", "nozzle": None, "at": None},
                             {"id": "a4", "label": "A4", "status": "skipped", "reported_label": None, "nozzle": None, "at": None}],
               "summary": "1 of 4 positions confirmed; 1 entered by hand (not checked by the printer); skipped: A4."}

    def __init__(self):
        self.starts = 0

    def view(self, serial):
        return self.session

    def start(self, serial):
        self.starts += 1
        return self.session

    def confirm(self, *args, **kwargs):
        return self.session

    skip = stop = confirm


class _Mapper:
    """The server's slot mapper as the page sees it: idle, `state = "running"` for a mapping in progress (Stop ends it), and a
    report that takes a moment and ends the printer's reason for one."""

    def __init__(self):
        self.manual = _Manual()
        self.state = "none"
        self.reports = 0

    def running(self, serial):
        return self.state == "running" and serial == X1

    def view(self, serial):
        if self.state == "running":
            return {"state": "running", "step": "step 2 of 4"}
        return {"state": self.state, "slots": [{"label": "A1"}, {"label": "A2"}], "problems": [], "notes": []}

    def abort(self, serial, pending=False):
        self.state = "done"

    def report(self, serial):
        import time
        self.reports += 1
        time.sleep(0.4)             # long enough for a second press to land
        d = bridge_mapping._dir(serial)
        status = json.loads((d / bridge_mapping.STATUS_FILE).read_text(encoding="utf-8"))
        status.pop("report_wanted", None)
        (d / bridge_mapping.STATUS_FILE).write_text(json.dumps(status), encoding="utf-8")
        return {"name": "printer-report-1.xml", "xml": "<report/>", "live": True}


@pytest.fixture
def mapper():
    return _Mapper()


@pytest.fixture
def printers_hub(monkeypatch, request, mapper):
    """The Hub page with printers in each state: Workshop X1 (connected, four slots), Garage Voron (connected, two tool
    slots), Study A1 mini (offline, its last mapping says a report would help) and a Klipper printer a scan found."""
    real = api.create_app
    monkeypatch.setattr(api, "create_app", lambda *a, **k: real(*a, **{**k, "mapper": mapper}))
    app, port = request.getfixturevalue("hub_app")
    registry.upsert(registry.Printer(MINI, "Study A1 mini", "A1M", "192.0.2.41", "12345678", True))
    registry.detected_klipper("192.0.2.57", 7125, "mainsailos")
    d = bridge_mapping._dir(MINI)
    d.mkdir(parents=True, exist_ok=True)
    (d / bridge_mapping.STATUS_FILE).write_text(json.dumps({"state": "failed", "job_id": "j1", "step": "", "problems": [], "notes": [],
                                                           "report_wanted": "job_failed", "finished": 1.0}), encoding="utf-8")
    voron = next(p for p in registry.load().values() if p.family == "klipper" and p.configured)
    klipper = _klipper_status()
    klipper["ams"][0]["slots"].append({"slot": 1, "label": "T1", "type": "TPU", "color_hex": "2255CC", "present": True, "active": False, "spool": None})
    held = {X1: bridge_status.summarize(X1_REPORT, [], printer_name="Workshop X1", model="X1C"), voron.serial: klipper}

    def status(self, serial):
        if serial not in held:
            raise KeyError(serial)          # an offline printer has no held report
        return held[serial]

    monkeypatch.setattr(FakeManager, "state", lambda self, serial: "offline" if serial == MINI else "connected", raising=False)
    monkeypatch.setattr(FakeManager, "status", status, raising=False)
    monkeypatch.setattr(tlspin, "leaf_fp", lambda host, port: (_ for _ in ()).throw(OSError("no route")))      # a test needs no network
    running = _serve(AsHttps(app), port)
    try:
        yield running.url + "/setup", voron.serial
    finally:
        running.stop()


def _printer_views(voron: str) -> str:
    return ",".join(["#printers", f"#printers/{X1}", f"#printers/{voron}", f"#printers/{MINI}", f"#printers/{X1}/reports", f"#printers/{X1}/load-map"])


def test_printers_rows_expansions_and_both_drawers_pass_the_audit(printers_hub):
    """The collection, a Bambu Lab row open, a Klipper row open, an offline row with its problem line, the Map by loading
    filament drawer and the Saved reports drawer. The three cards S2.5 rebuilds (Add a printer, Find Klipper printers, the
    add-on) are in the page and keep their findings, which tests/aut5_hub_allowlist.txt lists; nothing else may be found."""
    url, voron = printers_hub
    views = _printer_views(voron)
    run = _run("--url", url, "--views", views, "--settle", "500")
    assert run.returncode in (0, 1), run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == len(views.split(",")) * 2 * 2
    found = [(r["view"], r["width"], r["scheme"], f["check"], f["where"], f["detail"]) for r in out.get("report", [])
             for f in r["findings"] if "section.card" not in f["where"]]
    assert not found, "\n".join(map(str, found))


def test_printers_do_not_scroll_sideways_at_320_px_in_a_wide_font(monkeypatch, printers_hub):
    """As Devices and Flash: DejaVu is wider than the fonts of a Windows machine, and a long host name is what a CI runner has."""
    monkeypatch.setattr(pairing, "short_hostname", lambda: "runnervm8axu0")
    url, voron = printers_hub
    fonts = ["--font-dir", os.environ["AUT5_FONT_DIR"]] if os.environ.get("AUT5_FONT_DIR") else ["--wide-font"]
    run = _run("--url", url, "--views", _printer_views(voron), "--widths", "320", "--settle", "500", *fonts)
    assert run.returncode in (0, 1), run.stdout + run.stderr
    found = [(r["view"], r["scheme"], f["detail"]) for r in json.loads(run.stdout).get("report", [])
             for f in r["findings"] if f["check"] in ("sideways scroll", "horizontal page scroll")]
    assert not found, found


PRE = """const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const $ = (s, root = document) => root.querySelector(s);
const text = (el) => (el ? el.textContent.trim().replace(/\\s+/g, " ") : null);
const rowOf = (name) => [...document.querySelectorAll(".coll--printers .coll__item")].find((i) => i.querySelector(".coll__title") && text(i.querySelector(".coll__title")) === name);
const stopIn = (it) => it && [...it.querySelectorAll(".coll__row--note .result button")].find((b) => text(b) === "Stop");
await until(() => $("main") && !$(".chip--lock .skeleton__line"), "the page and the lock");
"""
UNLOCK = 'SW.setLock("unlocked", { code: "__CODE__" });\n'


def test_mapping_progress_and_stop_stay_through_a_test_result_and_leaving_the_section(printers_hub, mapper, tmp_path):
    mapper.state = "running"
    url, _ = printers_hub
    page = _drive(url, tmp_path, PRE + UNLOCK + """
location.hash = "#printers";
await until(() => rowOf("Workshop X1"), "the row");
await until(() => stopIn(rowOf("Workshop X1")), "the progress and Stop");
const progress = text($(".coll__row--note .result[data-state=run]", rowOf("Workshop X1")));
rowOf("Workshop X1").querySelector('[data-col="actions"] .actions button').click();         // Test connection
const box = () => [...rowOf("Workshop X1").querySelectorAll(".coll__row--note .result")].pop();
await until(() => box().dataset.state && box().dataset.state !== "run", "the test result");
const result = { progress, test: text(box()), afterTest: !!stopIn(rowOf("Workshop X1")) };
location.hash = "#overview";
await until(() => !rowOf("Workshop X1"), "the other section");
location.hash = "#printers";
await until(() => rowOf("Workshop X1"), "the row again");
result.afterReturn = !!(await until(() => stopIn(rowOf("Workshop X1")), "Stop after returning"));
result.rowShown = !rowOf("Workshop X1").querySelector(".coll__row--note").hidden;
stopIn(rowOf("Workshop X1")).click();
await until(() => !stopIn(rowOf("Workshop X1")), "the end of the mapping");
await until(() => text(box()).startsWith("Mapped"), "the end said (a result is written a moment after it is set)");
result.end = text(box());
result.progressGone = !$(".coll__row--note .result[data-state=run]", rowOf("Workshop X1"));
return result;
""")
    assert page["progress"].startswith("Mapping") and "step 2 of 4" in page["progress"], page      # (the page's text comes back in the console's code page)
    assert page["test"] and page["afterTest"] is True and page["afterReturn"] is True and page["rowShown"] is True, page
    assert page["end"].startswith(T("printers_mapped", slots="A1, A2")) and page["progressGone"] is True, page
    assert mapper.state == "done"


LOCK_SCRIPT = PRE + """
location.hash = "#printers";
await until(() => rowOf("Workshop X1"), "the rows");
const list = () => $(".printers-list");
const names = ["Workshop X1", "Garage Voron", "Study A1 mini"];
const secrets = ["00M00A000000001", "01P00A000000002", "192.0.2.40", "192.0.2.41", "voron.example.com", "192.0.2.57"];
const leaks = () => { const html = list().outerHTML; return secrets.filter((s) => html.includes(s)); };
const out = { startLocked: SW.lock.state, lockedAtStart: leaks() };
SW.setLock("unlocked", { code: "__CODE__" });
await until(() => leaks().length >= 5, "the addresses after Unlock");
out.unlocked = leaks();
out.unlockedHidden = list().textContent.includes("Hidden while locked");
out.hrefUnlocked = rowOf("Workshop X1").querySelector(".coll__title").getAttribute("href");
SW.setLock("locked");
await until(() => !leaks().length, "the addresses to go after Lock now");
out.locked = leaks();
out.lockedHidden = list().textContent.includes("Hidden while locked");
out.lockedAttrs = [...list().querySelectorAll("[data-id], [data-sort], [href], [id], [aria-controls], [aria-labelledby], [name]")].map((e) =>
  ["data-id", "data-sort", "href", "id", "aria-controls", "aria-labelledby", "name"].map((a) => e.getAttribute(a)).filter(Boolean).join(" ")).join(" | ");
out.lockedExpanded = rowOf("Workshop X1").querySelector(".coll__expand").getAttribute("aria-expanded");
// a test result read back while Locked has no address in it
const bambu = { family: "bambu", ip: "192.0.2.40", serial: "00M00A000000001", name: "Workshop X1" };
const klip = { family: "klipper", host: "voron.example.com", port: 7125, serial: "k1", name: "Garage Voron" };
out.results = [
  testResult(bambu, { text: "192.0.2.40 answers; its certificate matches the pinned one", reachable: true })[0],
  testResult(bambu, { text: "no answer from 192.0.2.40:8883 (TimeoutError): check that it is on", reachable: false })[0],
  testResult(bambu, { text: "something else about 192.0.2.40", reachable: false })[0],
  testResult(klip, { text: "Moonraker at voron.example.com:7125 answers; Klipper is ready", reachable: true })[0],
];
SW.setLock("unlocked", { code: "__CODE__" });
await until(() => leaks().length >= 5, "the addresses after Unlock again");
out.again = leaks();
out.againHidden = list().textContent.includes("Hidden while locked");
return out;
"""


def test_lock_now_hides_addresses_and_serials_and_unlock_shows_them(printers_hub, tmp_path):
    url, _ = printers_hub
    page = _drive(url, tmp_path, LOCK_SCRIPT)
    assert page["startLocked"] == "locked" and page["lockedAtStart"] == [], page
    assert len(page["unlocked"]) >= 5 and page["unlockedHidden"] is False, page
    assert page["hrefUnlocked"].startswith("#printers/"), page
    assert page["locked"] == [] and page["lockedHidden"] is True, page            # in the text and in every attribute
    assert not any(s in page["lockedAttrs"] for s in ("00M00A000000001", "192.0.2", "voron.example.com")), page["lockedAttrs"]
    assert page["lockedExpanded"] == "false"
    assert page["results"][0] == T("printers_result_locked_bambu_pinned")
    assert page["results"][1] == T("printers_result_locked_bambu_none", error_type="TimeoutError")
    assert "192.0.2.40" not in page["results"][2] and "voron.example.com" not in page["results"][3], page["results"]
    assert page["results"][3] == T("printers_result_locked_klipper_ok", state="ready")
    assert len(page["again"]) >= 5 and page["againHidden"] is False, page


def test_a_deep_link_to_a_printer_opens_its_row_while_locked_without_the_serial_in_the_page(printers_hub, tmp_path):
    """Locked, #printers/<serial> still opens the row and sets the title, as typed: the address stays as the person wrote it, and
    nothing this script draws carries the serial (an id, a data-id, a link); Unlock leaves the row open."""
    url, _ = printers_hub
    page = _drive(url + f"#printers/{X1}", tmp_path, PRE + """
await until(() => rowOf("Workshop X1"), "the rows");
const open = () => rowOf("Workshop X1").querySelector(".coll__expand").getAttribute("aria-expanded");
await until(() => open() === "true", "the row to open while Locked");
const out = { locked: SW.lock.state, openLocked: open(), hash: location.hash, title: document.title,
  leaks: $(".printers-list").outerHTML.includes("00M00A000000001") };
SW.setLock("unlocked", { code: "__CODE__" });
await sleep(500);
out.openUnlocked = open();
out.hashUnlocked = location.hash;
return out;
""")
    assert page["locked"] == "locked" and page["openLocked"] == "true" and page["hash"] == f"#printers/{X1}", page
    assert page["title"].startswith("Workshop X1") and page["leaks"] is False, page
    assert page["openUnlocked"] == "true" and page["hashUnlocked"] == f"#printers/{X1}", page


DRAWERS = PRE + """
document.documentElement.setAttribute("data-look", "__LOOK__");
""" + UNLOCK + """
location.hash = "#printers";
await until(() => rowOf("Workshop X1"), "the rows");
const out = { profile: SW.profile().detail };
const open = () => $("dialog[open] .detail--drawer");
for (const [what, title] of [["reports", "__REPORTS__"], ["load-map", "__LOAD__"]]) {
  location.hash = "#printers/00M00A000000001/" + what;
  const region = await until(open, "the " + what + " drawer");
  out[what] = { title: text($(".detail__title", region)), visible: !!region.getClientRects().length, hash: location.hash };
  $(".detail__close", region).click();
  for (let i = 0; i < 100 && (open() || $(".detail--drawer")); i++) {          // a mapping that is running asks first: Stop it
    const yes = $('dialog[open]:not(.dialog--drawer) [data-action="confirm"]');
    if (yes) yes.click();
    await sleep(100);
  }
  await until(() => !open() && !$(".detail--drawer"), "the " + what + " drawer to close");
  out[what].after = location.hash;
  out[what].left = document.querySelectorAll(".detail--drawer, dialog.dialog--drawer").length;
}
return out;
"""


@pytest.mark.parametrize("look", ["console", "workbench", "palette", "panes"])
def test_both_drawers_open_and_close_in_every_look(printers_hub, tmp_path, look):
    url, _ = printers_hub
    reports, load = T("printers_reports_title", name="Workshop X1"), T("printers_load_title", name="Workshop X1")
    page = _drive(url, tmp_path, DRAWERS.replace("__LOOK__", look).replace("__REPORTS__", reports).replace("__LOAD__", load))
    assert page["reports"]["title"] == reports and page["load-map"]["title"] == load, page
    for what in ("reports", "load-map"):
        assert page[what]["visible"] is True and page[what]["hash"] == f"#printers/{X1}/{what}", page
        assert page[what]["after"] == f"#printers/{X1}" and page[what]["left"] == 0, page


def test_no_secret_typed_in_a_drawer_stays_in_the_page_after_it_closes(printers_hub, tmp_path):
    url, _ = printers_hub
    page = _drive(url, tmp_path, PRE + UNLOCK + """
location.hash = "#printers";
await until(() => rowOf("Workshop X1"), "the rows");
const open = () => $("dialog[open] .detail--drawer");
const ids = [];
let field = null;
for (let n = 0; n < 2; n++) {
  location.hash = "#printers/00M00A000000001/reports";
  const region = await until(open, "the drawer");
  ids.push([...document.querySelectorAll("[id]")].map((e) => e.id).filter((i) => i.startsWith("drawer-")));
  field = document.createElement("input");           // what a form in a drawer holds: a secret typed and not sent
  field.type = "password"; field.value = "hunter2-" + n;
  $(".drawer__body", region).append(field);
  $(".detail__close", region).click();
  await until(() => !open() && !$(".detail--drawer") && location.hash === "#printers/00M00A000000001", "the drawer to close and go");
}
return { ids, value: field.value, left: [...document.querySelectorAll("input[type=password]")].filter((i) => i.value).length,
  drawers: document.querySelectorAll(".detail--drawer").length };
""")
    assert page["value"] == "" and page["left"] == 0 and page["drawers"] == 0, page
    assert all(len(set(i)) == len(i) for i in page["ids"]) and page["ids"][0] == page["ids"][1], page      # no id repeats


def test_a_double_press_on_collect_a_report_and_on_map_by_loading_filament_sends_one_request(printers_hub, mapper, tmp_path):
    url, _ = printers_hub
    page = _drive(url, tmp_path, PRE + UNLOCK + """
location.hash = "#printers";
await until(() => rowOf("Study A1 mini"), "the rows");
const button = () => $(".printers-problem button", rowOf("Study A1 mini"));
const before = !!button();
const b = button(); b.click(); b.click();
await until(() => /Report saved: printer-report-1.xml/.test(text([...rowOf("Study A1 mini").querySelectorAll(".coll__row--note .result")].pop())), "the report said");
await sleep(300);
const out = { before, problemAfter: !!$(".printers-problem", rowOf("Study A1 mini")) };
const x1 = rowOf("Workshop X1"), map = [...x1.querySelectorAll(".detail button")].find((e) => text(e) === "Map by loading filament");
map.click(); map.click();
await until(() => $("dialog[open] .detail--drawer"), "the drawer");
await sleep(300);
return out;
""")
    assert page["before"] is True and page["problemAfter"] is False, page          # "Needs a look" ends with the report
    assert mapper.reports == 1, mapper.reports
    assert mapper.manual.starts == 1, mapper.manual.starts

