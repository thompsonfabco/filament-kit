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
// Stop checks the setup code through the helper, whose lockout file is not locked between threads on Windows (no flock): a request that
// meets another one there is refused with "the setup helper failed", and the progress and Stop rightly stay. Press Stop again then.
result.refusals = 0;
stopIn(rowOf("Workshop X1")).click();
let pressed = Date.now();
while (stopIn(rowOf("Workshop X1")) && Date.now() - pressed < 20000) {
  await sleep(100);
  if (box().dataset.state === "bad" && Date.now() - pressed > 2500 && stopIn(rowOf("Workshop X1"))) { result.refusals++; pressed = Date.now(); stopIn(rowOf("Workshop X1")).click(); }
}
try { await until(() => !stopIn(rowOf("Workshop X1")), "the end of the mapping"); } catch (e) {
  throw new Error(e.message + " " + JSON.stringify({ lock: SW.lock.state, mapping, dialogs: [...document.querySelectorAll("dialog[open]")].map((d) => text(d).slice(0, 80)),
    box: text(box()), prog: text($(".coll__row--note .result", rowOf("Workshop X1"))) }));
}
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


# ---------------------------------------------------------------- Printers add (S2.5): Add a printer, Find Klipper printers, Klipper add-on

PRINTERS_PRELUDE = """
  const until = async (what, f, ms = 10000) => {
    for (let t = 0; t < ms && !f(); t += 100) await new Promise((r) => setTimeout(r, 100));
    if (!f()) throw new Error("Printers: " + what + " :: lock=" + SW.lock.state);
  };
  const quiet = () => until("the page did not finish its first reads", () => !document.querySelector(".chip--lock .skeleton__line")
    && !document.querySelector('[aria-busy="true"]:not(button)'));
  const unlock = async () => { await quiet(); SW.setLock("unlocked", { code: %r }); };
""" % CODE

# the drawer opens from its address; Add with nothing typed shows the field's own error, then a refusal of the Hub shows at its field
ADD_DRAWER = """(async () => {""" + PRINTERS_PRELUDE + """
  await unlock();
  await until("no Add a printer drawer", () => document.querySelector(".detail--drawer .printers-add"));
  const drawer = document.querySelector(".detail--drawer"), add = drawer.querySelector(".detail__foot .btn--primary");
  if (add.textContent.trim() !== "Add printer") throw new Error("Printers: the drawer's main action is " + add.textContent);
  add.click();
  await until("no error at an empty address", () => drawer.querySelector('.field[data-state="error"] .field__error:not([hidden])'));
  const set = (name, v) => { const c = drawer.querySelector('[name="' + name + '"]'); c.value = v; c.dispatchEvent(new Event("input", { bubbles: true })); };
  set("address", "192.0.2.77"); set("access_code", "12345678");
  const real = window.fetch;
  window.fetch = (u, o) => (String(u).endsWith("/api/printers") && o && o.method === "POST"
    ? Promise.resolve(new Response(JSON.stringify({ error: "the printer at 192.0.2.77 names itself 01P00A000000009, not 00M00A000000001: check the address", field: "address" }),
      { status: 400, headers: { "Content-Type": "application/json" } })) : real(u, o));
  add.click();
  await until("no refusal at the address field", () => /calls itself/.test(drawer.querySelector('[name="address"]').closest(".field").innerText));
  if (document.activeElement !== drawer.querySelector('[name="address"]')) throw new Error("Printers: the refused field is not focused");
  window.fetch = real;
})()"""

SCAN_AND_ADDON = """(async () => {""" + PRINTERS_PRELUDE + """
  %s
  await until("no Find Klipper printers card", () => document.querySelector(".printers-tools .btn"));
  const tools = document.querySelector(".printers-tools");
  %s
})()"""

FIND_RESULTS = SCAN_AND_ADDON % ("await unlock();", """
  const scan = [...tools.querySelectorAll(".btn")].find((b) => b.textContent.trim() === "Scan");
  scan.click();
  await until("no scan result", () => /Found on 192[.]168[.]1[.]0[/]24/.test(tools.innerText));
  if (![...tools.querySelectorAll(".btn")].some((b) => b.textContent.trim() === "Use this printer")) throw new Error("Printers: no Use this printer in the result");
  await until("the found group did not take the new printer", () => document.querySelectorAll(".printers-found .coll__item").length >= 2);
""")

ADDON_COMMANDS = SCAN_AND_ADDON % ("await quiet();", """
  [...tools.querySelectorAll(".btn")].find((b) => b.textContent.trim() === "Show the commands").click();
  await until("no commands", () => tools.querySelector(".code__text") && tools.querySelector('.printers-addon [data-action="copy"]'));
  if (!tools.querySelector(".code__text").textContent.includes("sha256sum")) throw new Error("Printers: the commands are not shown");
""")


@pytest.fixture
def klipper_tools(monkeypatch, printers_hub):
    from filament_kit import klipper_cli, setup_page
    from filament_kit.bridge.klipper import discovery
    from filament_kit.setup_console import printers_tab
    monkeypatch.setattr(printers_tab, "SCAN_GAP", 0)
    monkeypatch.setattr(setup_page, "CHECK_GAP", 0)      # the passes of one run read the commands a few seconds apart
    monkeypatch.setattr(discovery, "scan", lambda net, port=7125: [("192.0.2.57", 7125), ("192.0.2.58", 7125)])
    monkeypatch.setattr(discovery, "own_subnet", lambda: __import__("ipaddress").ip_network("192.168.1.0/24"))
    monkeypatch.setattr(klipper_cli, "pack_info", lambda v, cfg: {"version": "0.4.3", "sha256": "ab", "url": "u", "lines": [
        "curl -fsSLo fk-printer-pack.tar.gz https://example.invalid/releases/download/v0.4.3/fk-printer-pack.tar.gz",
        'echo "abababababababababababababababababababababababababababababababab  fk-printer-pack.tar.gz" | sha256sum -c - && tar xzf fk-printer-pack.tar.gz']})
    return printers_hub[0]


def _printers_run(url: str, view: str, ready: str, wide: bool):
    args = ["--url", url, "--views", view, "--settle", "500", "--ready", ready]
    if wide:
        args += ["--widths", "320", *(["--font-dir", os.environ["AUT5_FONT_DIR"]] if os.environ.get("AUT5_FONT_DIR") else ["--wide-font"])]
    run = _run(*args)
    assert run.returncode == 0, run.stdout + run.stderr      # no allow-list: nothing of these cards is allowed
    assert json.loads(run.stdout)["views"] == (2 if wide else 4)


@pytest.mark.parametrize("wide", [False, True])
def test_the_add_a_printer_drawer_with_a_field_error_passes_the_audit(monkeypatch, printers_hub, wide):
    """03 5.6: the drawer from its address, Locked then Unlocked by the test, an empty address refused at the field and a Hub refusal at its field."""
    monkeypatch.setattr(pairing, "short_hostname", lambda: "runnervm8axu0")
    url, _ = printers_hub
    _printers_run(url, "#printers/add", ADD_DRAWER, wide)


@pytest.mark.parametrize("wide", [False, True])
def test_find_klipper_printers_results_pass_the_audit(monkeypatch, klipper_tools, wide):
    monkeypatch.setattr(pairing, "short_hostname", lambda: "runnervm8axu0")
    _printers_run(klipper_tools, "#printers/find", FIND_RESULTS, wide)


@pytest.mark.parametrize("wide", [False, True])
def test_the_klipper_add_on_commands_pass_the_audit_while_locked(monkeypatch, klipper_tools, wide):
    monkeypatch.setattr(pairing, "short_hostname", lambda: "runnervm8axu0")
    _printers_run(klipper_tools, "#printers", ADDON_COMMANDS, wide)


ADD_PRE = PRE + UNLOCK + """
location.hash = "#printers";
await until(() => rowOf("Workshop X1"), "the rows");
const posts = [], real = window.fetch;
let hold = null;                                    // a promise the Hub's answer to an add waits for
window.fetch = (u, o) => {
  const add = o && o.method === "POST" && /\\/setup\\/api\\/printers(\\/klipper)?$/.test(String(u));
  if (add) posts.push([String(u).replace(/^.*\\/setup\\/api\\//, ""), JSON.parse(o.body)]);
  return add && hold ? hold.then(() => real(u, o)) : real(u, o);
};
const open = () => $("dialog[open] .detail--drawer");
const setv = (root, name, v) => { const c = $('[name="' + name + '"]', root); c.value = v; c.dispatchEvent(new Event("input", { bubbles: true })); };
const addButton = () => [...document.querySelectorAll(".printers-head .page-head__actions .btn")].find((b) => text(b) === "Add a printer");
const openAdd = async () => { addButton().click(); return until(open, "the Add drawer"); };
const kind = (region, k) => { $('input[type=radio][value="' + k + '"]', region).click(); };
const typed = () => [...document.querySelectorAll("input[type=password]")].filter((i) => i.value).length;
const dup = () => { const ids = [...document.querySelectorAll("[id]")].map((e) => e.id), seen = new Set(); return ids.filter((i) => seen.size === seen.add(i).size); };
const footBtn = (region, label) => [...region.querySelectorAll(".detail__foot .btn")].find((b) => text(b) === label);
const said = (name) => text([...rowOf(name).querySelectorAll(".coll__row--note .result")].pop());
const leftOver = () => ({ drawers: document.querySelectorAll(".detail--drawer, dialog.dialog--drawer").length, typed: typed(), dup: dup() });
"""


def test_adding_a_bambu_and_a_klipper_printer_sends_one_add_each_and_opens_the_new_row(printers_hub, tmp_path):
    """03 5.6: the path and body of each add, a double press that sends one, the drawer gone with nothing typed left in the page, and the
    new row open with its message; the second opening makes no id twice."""
    url, _ = printers_hub
    page = _drive(url, tmp_path, ADD_PRE + """
const out = {};
let region = await openAdd();
out.hashOpen = location.hash;
out.bambuFields = ["address", "access_code", "serial"].map((n) => !!$('[name="' + n + '"]', region).offsetParent);
setv(region, "address", " 192.0.2.77 "); setv(region, "access_code", "12345678"); setv(region, "name", "Fresh P1"); setv(region, "serial", "01P00A000000009");
const add = footBtn(region, "Add printer");
add.click(); add.click();
await sleep(50); add.click();
await until(() => !open() && rowOf("Fresh P1"), "the drawer to close and the new row");
await sleep(300);
const row = rowOf("Fresh P1");
out.bambu = { posts: posts.slice(), expanded: row.querySelector(".coll__expand").getAttribute("aria-expanded"), said: said("Fresh P1"), hash: location.hash, left: leftOver() };
posts.length = 0;
region = await openAdd();
out.second = dup();
kind(region, "klipper");
out.klipperFields = ["host", "port", "api_key"].map((n) => !!$('[name="' + n + '"]', region).offsetParent);
out.bambuHidden = ["address", "access_code"].map((n) => !$('[name="' + n + '"]', region).offsetParent);
setv(region, "host", "192.0.2.88"); setv(region, "name", "Fresh Klipper"); setv(region, "api_key", "k-secret");
const go = footBtn(region, "Add printer");
go.click(); go.click();
await until(() => !open() && rowOf("Fresh Klipper"), "the drawer to close and the Klipper row");
await sleep(300);
out.klipper = { posts: posts.slice(), expanded: rowOf("Fresh Klipper").querySelector(".coll__expand").getAttribute("aria-expanded"), said: said("Fresh Klipper"), left: leftOver() };
return out;
""")
    assert page["hashOpen"] == "#printers/add" and page["bambuFields"] == [True, True, True], page
    assert page["bambu"]["posts"] == [["printers", {"address": "192.0.2.77", "access_code": "12345678", "name": "Fresh P1", "serial": "01P00A000000009", "code": CODE}]], page
    assert page["bambu"]["expanded"] == "true" and page["bambu"]["said"].startswith(T("printers_added_connecting")), page
    assert page["bambu"]["hash"] == "#printers/01P00A000000009", page
    assert page["bambu"]["left"] == {"drawers": 0, "typed": 0, "dup": []}, page
    assert page["second"] == [] and page["klipperFields"] == [True, True, True] and page["bambuHidden"] == [True, True], page
    assert page["klipper"]["posts"] == [["printers/klipper", {"host": "192.0.2.88", "port": "7125", "name": "Fresh Klipper", "api_key": "k-secret", "code": CODE}]], page
    assert page["klipper"]["expanded"] == "true" and page["klipper"]["said"].startswith(T("printers_added_connecting")), page
    assert page["klipper"]["left"] == {"drawers": 0, "typed": 0, "dup": []}, page


def test_cancel_with_typed_values_asks_first_and_the_busy_drawer_says_wait(printers_hub, tmp_path):
    """03 5.6: Cancel with typed values asks to leave first (Stay keeps them; Leave sends nothing and leaves no secret in the page);
    Cancel while the Hub answers an add warns and keeps the drawer."""
    url, _ = printers_hub
    page = _drive(url, tmp_path, ADD_PRE + """
const out = {};
let region = await openAdd();
setv(region, "address", "192.0.2.78"); setv(region, "access_code", "87654321");
footBtn(region, "Cancel").click();
const ask = await until(() => $("dialog[open]:not(.dialog--drawer)"), "the leave-first ask");
out.ask = text(ask);
$('[data-action="cancel"]', ask).click();
await until(() => !$("dialog[open]:not(.dialog--drawer)"), "the ask to close");
out.stay = { open: !!open(), address: $('[name="address"]', region).value, code: $('[name="access_code"]', region).value };
footBtn(region, "Cancel").click();
$('[data-action="confirm"]', await until(() => $("dialog[open]:not(.dialog--drawer)"), "the second ask")).click();
await until(() => !open() && !$(".detail--drawer"), "the drawer to close");
out.leave = { posts: posts.length, hash: location.hash, left: leftOver() };
region = await openAdd();
out.second = dup();
setv(region, "address", "192.0.2.79"); setv(region, "access_code", "12345678"); setv(region, "serial", "01P00A000000010");
let release; hold = new Promise((r) => { release = r; });
footBtn(region, "Add printer").click();
await until(() => footBtn(region, "Cancel") && $('.detail__foot [aria-busy="true"]', region), "the add to be sent");
footBtn(region, "Cancel").click();
await until(() => text($(".detail__foot .result", region)), "the warning");
out.busy = { warning: text($(".detail__foot .result", region)), open: !!open(), asked: !!$("dialog[open]:not(.dialog--drawer)"), posts: posts.length };
release();
for (let i = 0; i < 300 && open(); i++) await sleep(100);
out.end = { left: leftOver(), hash: location.hash, still: open() ? text(open()) : null };
return out;
""")
    count = T("form_leave_first", count=2, group=T("printers_add"))
    assert page["ask"].startswith(T("common_leave_title")) and T("form_leave_body", changes=count) in page["ask"], page
    assert page["stay"] == {"open": True, "address": "192.0.2.78", "code": "87654321"}, page
    assert page["leave"] == {"posts": 0, "hash": "#printers", "left": {"drawers": 0, "typed": 0, "dup": []}}, page
    assert page["second"] == [], page
    assert page["busy"]["warning"].startswith(T("printers_add_wait")), page      # the result line adds the time
    assert (page["busy"]["open"], page["busy"]["asked"], page["busy"]["posts"]) == (True, False, 1), page
    assert page["end"]["left"] == {"drawers": 0, "typed": 0, "dup": []}, page


ADD_LOOKS = PRE + """
document.documentElement.setAttribute("data-look", "__LOOK__");
""" + UNLOCK + """
location.hash = "#printers";
await until(() => rowOf("Workshop X1"), "the rows");
const open = () => $("dialog[open] .detail--drawer");
const out = { profile: SW.profile().detail, opened: [] };
for (const how of ["button", "address"]) {
  if (how === "button") [...document.querySelectorAll(".printers-head .page-head__actions .btn")].find((b) => text(b) === "Add a printer").click();
  else location.hash = "#printers/add";
  const region = await until(open, "the Add drawer by " + how);
  out.opened.push({ how, title: text($(".detail__title", region)), visible: !!region.getClientRects().length, hash: location.hash, form: !!$(".printers-add", region) });
  $(".detail__close", region).click();
  await until(() => !open() && !$(".detail--drawer"), "the Add drawer to close");
  out.opened[out.opened.length - 1].after = location.hash;
  out.opened[out.opened.length - 1].left = document.querySelectorAll(".detail--drawer, dialog.dialog--drawer").length;
}
return out;
"""


@pytest.mark.parametrize("look", ["console", "workbench", "palette", "panes"])
def test_the_add_a_printer_drawer_opens_and_closes_in_every_look(printers_hub, tmp_path, look):
    url, _ = printers_hub
    page = _drive(url, tmp_path, ADD_LOOKS.replace("__LOOK__", look))
    assert [o["how"] for o in page["opened"]] == ["button", "address"], page
    for o in page["opened"]:
        assert o["title"] == T("printers_add") and o["visible"] is True and o["form"] is True and o["hash"] == "#printers/add", page
        assert o["after"] == "#printers" and o["left"] == 0, page


def test_the_klipper_add_on_caption_and_copy_sit_above_the_block_and_inside_the_page_at_320_px(klipper_tools, tmp_path):
    """The caption and Copy are not in the scrolling block: both are fully inside the page's width at 320 px."""
    page = _drive(klipper_tools, tmp_path, PRE + UNLOCK + """
location.hash = "#printers";
await until(() => $(".printers-tools .btn"), "the cards");
[...document.querySelectorAll(".printers-tools .btn")].find((b) => text(b) === "Show the commands").click();
const addon = await until(() => $(".printers-addon .code__text") && $(".printers-addon"), "the commands");
const box = (e) => { const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.right)]; };
const block = $(".printers-addon .code");
return { width: document.documentElement.clientWidth, caption: box($(".code__caption", addon)), copy: box($('[data-action="copy"]', addon)),
  captionInBlock: block.contains($(".code__caption", addon)), copyInBlock: block.contains($('[data-action="copy"]', addon)),
  scroll: document.documentElement.scrollWidth };
""", width=320)
    assert page["captionInBlock"] is False and page["copyInBlock"] is False, page
    assert page["caption"][0] >= 0 and page["copy"][0] >= 0 and page["caption"][1] <= page["width"] and page["copy"][1] <= page["width"], page
    assert page["scroll"] <= page["width"], page
