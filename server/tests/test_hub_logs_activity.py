"""The Hub page's Logs section with Activity (R84 sections 2, 3.3, 8, 9.3), in a real headless browser: the choice Activity | Service
logs, the Activity table (when, who, what, a link, Undo) with its two filters and Show more, Undo in the rows (done, refused, locked),
Collect a Hub report (start, download), the service logs as they were (still behind the setup code), the empty state, and the table
readable in all four looks at 1280 and 390 px. The Hub's routes for activity, undo and report are not in this tree yet (HD6), so a
stub answers them as 9.3 gives them, in front of the real page and the real logs routes; every request it sees is kept. The same
skip rules as the page audit: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
from urllib.parse import parse_qs

import pytest

from test_hub_page_audit import _serve, hub_app  # noqa: F401
from test_hub_presets_ui import AsHttps, T, _drive
from test_setup_page import CODE

UNDONE_NOTE = "The printer still shows what it was set to."
CHANGED = "This changed again since, so it cannot be undone."


def _event(id, kind, title, text, actor, subject, action=None, undo=None, **more):
    return {"id": id, "at": f"2026-11-{1 + id // 24:02d}T{id % 24:02d}:15:00Z", "kind": kind, "severity": "info", "subject": subject,
            "actor": actor, "data": {}, "title": title, "text": text, "action": action, "undone": False,
            "undo": undo or {"possible": False, "why_not": "not_undoable"}, **more}


def events():
    """Eight kinds of row: an undoable one, one changed since, none-undoable, a load with a note, a backup with no link, one already
    undone, an undo itself, a printer added."""
    page, cli, hub = ({"type": t, "id": "", "name": n} for t, n in (("page", "Hub page"), ("cli", "command line"), ("hub", "Hub")))
    phone = {"type": "device", "id": "d1", "name": "Kitchen phone"}
    spool = {"type": "spool", "id": "212", "name": "Bambu Lab PETG HF Orange (212)"}
    return [
        _event(9, "spool.moved", "Moved", "Moved Bambu Lab PETG HF Orange (212) to Shelf B.", page, spool, {"place": "spool", "id": "212"}, {"possible": True, "until": "2026-11-24T09:15:00Z"}),
        _event(8, "spool.weighed", "Weighed", "Weighed Bambu Lab PETG HF Orange (212): 640 g.", phone, spool, {"place": "spool", "id": "212"}, {"possible": False, "why_not": "changed_since"}),
        _event(7, "settings.changed", "Settings changed", "Changed the settings of General.", cli, {"type": "settings", "id": "general", "name": "General"}, {"place": "settings", "id": "general"}),
        _event(6, "spool.loaded", "Loaded", "Loaded spool 212 into slot 1 of Workshop X1.", phone, {"type": "printer", "id": "P1", "name": "Workshop X1"}, {"place": "printer", "id": "P1"}, {"possible": True}),
        _event(5, "backup.finished", "Backup finished", "The nightly backup finished.", hub, {"type": "hub", "id": "", "name": ""}),
        _event(4, "spool.emptied", "Marked empty", "Marked spool 90 empty.", page, {"type": "spool", "id": "90", "name": "Spool 90"}, {"place": "spool", "id": "90"}, {"possible": False, "why_not": "already_undone"}, undone=True),
        _event(3, "spool.moved", "Moved", "Moved spool 90 to Rack 1.", page, {"type": "spool", "id": "90", "name": "Spool 90"}, {"place": "spool", "id": "90"}, undo_of=2),
        _event(2, "printer.added", "Printer added", "Added Garage Voron.", page, {"type": "printer", "id": "P2", "name": "Garage Voron"}, {"place": "printer", "id": "P2"}),
    ]


class StubHub:
    """ASGI wrapper that answers GET activity, POST events/<id>/undo, POST report and POST report/download as 9.3 gives them (a code is
    needed where the table says unlocked) and keeps every request to those and to the real logs routes in `calls`."""

    def __init__(self, app, rows):
        self.app, self.rows, self.calls = app, rows, []
        self.undo = {}                           # id -> (status, body): what the next undo of it answers
        self.report_text = "Spoolwarden report\nversion 1\n"

    def find(self, id):
        return next(e for e in self.rows if str(e["id"]) == str(id))

    async def reply(self, send, status, body, ctype="application/json", extra=()):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", ctype.encode()), (b"content-length", str(len(data)).encode()), *extra]})
        await send({"type": "http.response.body", "body": data})

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/setup/api/"):
            return await self.app(scope, receive, send)
        name = path[len("/setup/api/"):]
        if name == "logs" or name == "logs/units":
            self.calls.append((name, None))
            return await self.app(scope, receive, send)
        if not (name == "activity" or name in ("report", "report/download") or (name.startswith("events/") and name.endswith("/undo"))):
            return await self.app(scope, receive, send)
        body = b""
        while True:
            m = await receive()
            body += m.get("body", b"")
            if not m.get("more_body"):
                break
        sent = json.loads(body or b"{}")
        if name == "activity":
            q = {k: v[0] for k, v in parse_qs(scope["query_string"].decode()).items()}
            self.calls.append(("activity", q))
            rows = [e for e in self.rows if not q.get("actor") or e["actor"]["type"] == q["actor"]]
            if q.get("kinds"):
                rows = [e for e in rows if e["kind"] in q["kinds"].split(",")]
            rows = sorted(rows, key=lambda e: -e["id"])[:int(q["limit"])]
            return await self.reply(send, 200, {"events": rows, "next": max((e["id"] for e in self.rows), default=0), "oldest": min((e["id"] for e in self.rows), default=0)})
        self.calls.append((name, "code" if sent.get("code") == CODE else "no code"))
        if sent.get("code") != CODE:
            return await self.reply(send, 403, {"error": "the setup code is needed", "field": "code"})
        if name == "report":
            return await self.reply(send, 200, {"started": True})
        if name == "report/download":
            return await self.reply(send, 200, self.report_text.encode(), "text/plain; charset=utf-8",
                                    [(b"content-disposition", b'attachment; filename="hub-report-2026-11-17.txt"')])
        id = name.split("/")[1]
        status, answer = self.undo.get(id, (200, {"undone": True, "event": {"id": 99}, "note": UNDONE_NOTE if id == "6" else None}))
        if status == 200:
            self.find(id).update(undone=True, undo={"possible": False, "why_not": "already_undone"})
            if answer.get("note") is None:
                answer.pop("note", None)
        else:
            self.find(id)["undo"] = {"possible": False, "why_not": "changed_since"}
        await self.reply(send, status, answer)


@pytest.fixture
def stubbed(hub_app):  # noqa: F811
    """The Hub page served through the stub: (the page's address, the stub)."""
    stub = StubHub(hub_app[0], events())
    running = _serve(AsHttps(stub), hub_app[1])
    try:
        yield running.url + "/setup", stub
    finally:
        running.stop()


PRELUDE = r"""const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 450; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what + "; the page shows: " + document.querySelector("main").innerText.slice(0, 400)); }
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const text = (el) => (el ? el.textContent.trim().replace(/\s+/g, " ") : null);
const shown = (el) => !!el && el.getClientRects().length > 0;
const rowEls = () => $$(".coll--activity > .coll__item");
const rowOf = (id) => rowEls().find((r) => r.dataset.id === String(id));
const cellOf = (row, col) => $(`.coll__cell[data-col="${col}"]`, row);
const cellText = (row, col) => { const c = cellOf(row, col); if (!c) return null; const k = $(".coll__key", c); return text(c).slice(k ? text(k).length : 0).trim(); };
const ready = async (look = "console") => {
  document.documentElement.setAttribute("data-look", look);
  location.hash = "#logs";
  await until(() => $(".logs__activity .coll--activity, .logs__activity .empty, .logs__activity .error-state"), "the activity");
  await sleep(200);
};
const unlock = async () => { SW.setLock("unlocked", { code: "__CODE__" }); await sleep(500); await until(() => $(".logs__activity .coll--activity, .logs__activity .empty"), "the activity again"); };
const settle = (ms = 400) => sleep(ms);
const choose = async (select, value) => { select.value = value; select.dispatchEvent(new Event("change", { bubbles: true })); await settle(500); };
const filterSelect = (label) => $$(".logs__activity .field").find((f) => text($(".field__label", f)).startsWith(label)).querySelector("select");
const rowIds = () => rowEls().map((r) => r.dataset.id);
const unlockDialog = () => $("dialog[open]");
"""


def drive(url, tmp_path, body, width=1280, look="console"):
    return _drive(url, tmp_path, PRELUDE + f'await ready("{look}");\nconst out = {{}};\n' + body + "\nreturn out;\n", width=width)


def test_logs_opens_on_activity_with_the_choice_the_table_its_links_and_undo_in_the_rows_with_no_code(stubbed, tmp_path):
    url, stub = stubbed
    page = drive(url, tmp_path, r"""
out.lock = SW.lock.state;
out.choice = $$('input[name="logs-view"]').map((i) => [i.value, i.checked, text(i.labels[0])]);
out.cards = $$("main .card > h2").map(text);
out.filters = $$(".logs__activity .field__label").map(text);
out.who = $$("option", filterSelect("Who")).map((o) => [o.value, text(o)]);
out.kind = $$("option", filterSelect("What kind")).map((o) => [o.value, text(o)]);
out.head = $$(".coll--activity .coll__head [role=columnheader]").map(text);
out.ids = rowIds();
out.rows = Object.fromEntries(rowEls().map((r) => [r.dataset.id, { when: $("time", r).getAttribute("datetime"), shownTime: text($("time", r)).length > 5, who: cellText(r, "who"), what: text($('[data-col="what"] > span:not(.coll__key):not(.coll__sub)', r)),
  sub: text($(".coll__sub", r)), link: $("a", cellOf(r, "thing")) ? [text($("a", cellOf(r, "thing"))), $("a", cellOf(r, "thing")).getAttribute("href")] : cellText(r, "thing"), undo: $(".btn", cellOf(r, "actions")) ? $(".btn", cellOf(r, "actions")).getAttribute("aria-label") : null }]));
out.serviceHidden = $$(".logs__activity").length === 1 && !shown($(".logs .banner"));
out.more = !!$(".logs__out > .btn");
""")
    assert page["lock"] == "locked"                                    # nothing was typed: reading Activity needs no code
    assert page["choice"] == [["activity", True, "Activity"], ["service", False, "Service logs"]]
    assert page["cards"] == [T("nav_logs"), "Collect a Hub report"]
    assert page["filters"] == ["Who", "What kind"]
    assert [v for v, _ in page["who"]] == ["", "page", "cli", "hub", "device", "connector"] and page["who"][0][1] == "Anyone"
    assert [v for v, _ in page["kind"]][0] == "" and page["kind"][0][1] == "Everything" and len(page["kind"]) == 9
    assert page["head"] == ["When", "Who", "What", "Where", "Undo"]
    assert page["ids"] == ["9", "8", "7", "6", "5", "4", "3", "2"] and page["more"] is False        # newest first, fewer than a page: no Show more
    rows = page["rows"]
    assert rows["9"]["when"] == "2026-11-01T09:15:00.000Z" and all(r["shownTime"] for r in rows.values())
    assert rows["9"]["who"] == "Hub page" and rows["8"]["who"] == "Kitchen phone" and rows["7"]["who"] == "command line"
    assert rows["9"]["what"] == "Moved Bambu Lab PETG HF Orange (212) to Shelf B."
    assert rows["9"]["link"] == ["Bambu Lab PETG HF Orange (212)", "#spools/212"] and rows["6"]["link"] == ["Workshop X1", "#printers/P1"]
    assert rows["7"]["link"] == ["General", "#settings/general"] and rows["5"]["link"] == ""            # no action: no link
    # Undo stays while the Hub allows it (undo.possible); otherwise the Hub's why_not says why, as text, never a button
    assert rows["9"]["undo"] == "Undo: Moved Bambu Lab PETG HF Orange (212) to Shelf B." and rows["6"]["undo"].startswith("Undo: Loaded")
    assert sorted(i for i, r in rows.items() if r["undo"]) == ["6", "9"]
    assert rows["8"]["sub"] == CHANGED and rows["4"]["sub"] == "Undone." and rows["3"]["sub"] == "This put an earlier change back."
    assert rows["7"]["sub"] is None and rows["5"]["sub"] is None                                      # not undoable: nothing said
    assert stub.calls and all(c == ("activity", {"limit": "50"}) for c in stub.calls)                  # only reads of the newest 50: no code, no filter


def test_the_filters_ask_the_hub_and_show_more_asks_for_more(stubbed, tmp_path):
    url, stub = stubbed
    stub.rows.extend(_extra(n) for n in range(100, 220))       # 120 more: 128 rows, all of kind spool.moved by the Hub page
    page = drive(url, tmp_path, r"""
const count = () => rowEls().length, more = () => $(".logs__out > .btn");
out.first = { n: count(), more: !!more(), label: text(more()) };
more().click(); await until(() => count() === 100, "100 rows");
out.second = { n: count(), more: !!more(), focused: document.activeElement.dataset.id === rowEls()[50].dataset.id };
more().click(); await until(() => count() === 128 || count() === 150, "all rows");
out.third = { n: count(), more: !!more() };
await choose(filterSelect("Who"), "cli");
out.cli = { ids: rowIds(), more: !!more() };
await choose(filterSelect("What kind"), "spools");
out.cliSpools = { ids: rowIds(), empty: text($(".logs__activity .empty")) };
await choose(filterSelect("Who"), "device");
out.deviceSpools = { ids: rowIds() };
await choose(filterSelect("What kind"), "");
out.device = { ids: rowIds() };
await choose(filterSelect("Who"), "");
out.again = { n: count(), more: !!more() };
""")
    assert page["first"] == {"n": 50, "more": True, "label": "Show more"}
    assert page["second"] == {"n": 100, "more": True, "focused": True}
    assert page["third"] == {"n": 128, "more": False}
    assert page["cli"] == {"ids": ["7"], "more": False}
    assert page["cliSpools"]["ids"] == [] and page["cliSpools"]["empty"] == "Nothing matches these choices."
    assert page["deviceSpools"]["ids"] == ["8", "6"] and page["device"]["ids"] == ["8", "6"]
    assert page["again"] == {"n": 50, "more": True}                                                    # a new choice starts on the first page again
    asked = [q for n, q in stub.calls if n == "activity"]
    assert {"limit": "50"} in asked and {"limit": "100"} in asked and {"limit": "150"} in asked
    assert {"limit": "50", "actor": "cli"} in asked
    assert {"limit": "50", "actor": "cli", "kinds": "spool.added,spool.weighed,spool.moved,spool.emptied,spool.opened,spool.loaded,spool.unloaded,slot.cleared"} in asked
    assert {"limit": "50", "actor": "device"} in asked


def _extra(n):
    page = {"type": "page", "id": "", "name": "Hub page"}
    return _event(n, "spool.moved", "Moved", f"Moved spool {n} to Shelf A.", page, {"type": "spool", "id": str(n), "name": f"Spool {n}"}, {"place": "spool", "id": str(n)})


def test_activity_with_nothing_in_it_says_so(stubbed, tmp_path):
    url, stub = stubbed
    stub.rows.clear()
    page = drive(url, tmp_path, r"""
out.empty = { title: text($(".logs__activity .empty__title")), text: text($(".logs__activity .empty__text")), table: !!$(".coll--activity"), more: !!$(".logs__out > .btn") };
""")
    assert page["empty"] == {"title": "No activity yet", "text": "What is done on this Hub is listed here.", "table": False, "more": False}


def test_undo_puts_back_and_says_so_with_the_hubs_note_and_the_row_stops_offering_it(stubbed, tmp_path):
    url, stub = stubbed
    page = drive(url, tmp_path, r"""
await unlock();
const said = () => text($(".logs__activity .result__text"));
$(".btn", cellOf(rowOf(9), "actions")).click();
await until(() => said() && said().includes("Put back"), "the result");
out.first = { said: said(), state: $(".logs__activity .result").dataset.state, row: { undo: !!$(".btn", cellOf(rowOf(9), "actions")), sub: text($(".coll__sub", rowOf(9))) } };
$(".btn", cellOf(rowOf(6), "actions")).click();
await until(() => said() && said().includes("printer still"), "the result with the note");
out.second = { said: said(), row: { undo: !!$(".btn", cellOf(rowOf(6), "actions")), sub: text($(".coll__sub", rowOf(6))) } };
out.focus = document.activeElement.dataset ? document.activeElement.dataset.id : null;
""")
    assert page["first"] == {"said": page["first"]["said"], "state": "ok", "row": {"undo": False, "sub": "Undone."}}
    assert page["first"]["said"].startswith("Put back.") and UNDONE_NOTE not in page["first"]["said"]
    assert page["second"]["said"].startswith(f"Put back. {UNDONE_NOTE}") and page["second"]["row"] == {"undo": False, "sub": "Undone."}
    assert [c for c in stub.calls if c[0].startswith("events/")] == [("events/9/undo", "code"), ("events/6/undo", "code")]
    assert page["focus"] == "6"


def test_a_refused_undo_says_the_hubs_reason_and_the_row_then_says_it_too(stubbed, tmp_path):
    url, stub = stubbed
    stub.undo["9"] = (409, {"error": "changed_since", "text": CHANGED})
    page = drive(url, tmp_path, r"""
await unlock();
$(".btn", cellOf(rowOf(9), "actions")).click();
await until(() => text($(".logs__activity .result__text")), "the refusal");
out.said = { text: text($(".logs__activity .result__text")), state: $(".logs__activity .result").dataset.state };
await sleep(300);
out.row = { undo: !!$(".btn", cellOf(rowOf(9), "actions")), sub: text($(".coll__sub", rowOf(9))) };
""")
    assert page["said"] == {"text": CHANGED, "state": "bad"}
    assert page["row"] == {"undo": False, "sub": CHANGED}                                               # the list was read again: the Hub's word on the row
    assert [c for c in stub.calls if c[0].startswith("events/")] == [("events/9/undo", "code")]


def test_undo_and_the_report_ask_for_the_code_first_when_locked(stubbed, tmp_path):
    url, stub = stubbed
    page = drive(url, tmp_path, r"""
const buttons = { undo: $(".btn", cellOf(rowOf(9), "actions")), collect: $('[data-action="collect-report"]'), get: $('[data-action="download-report"]') };
for (const [name, b] of Object.entries(buttons)) {
  b.click();
  await until(unlockDialog, "the unlock dialog for " + name);
  out[name] = { dialog: !!unlockDialog(), lock: SW.lock.state };
  $('[data-action="cancel"]', unlockDialog()).click();
  await until(() => !unlockDialog(), "the dialog to close");
}
""")
    assert page["undo"] == {"dialog": True, "lock": "locked"} and page["collect"]["dialog"] and page["get"]["dialog"]
    assert [c for c in stub.calls if c[0] != "activity"] == []                                         # nothing was sent


def test_collect_a_hub_report_asks_the_hub_to_start_the_job_with_the_code(stubbed, tmp_path):
    url, stub = stubbed
    page = drive(url, tmp_path, r"""
await unlock();
out.labels = [text($('[data-action="collect-report"]')), text($('[data-action="download-report"]'))];
out.about = text($(".logs__report p"));
$('[data-action="collect-report"]').click();
await until(() => $(".jobstrip, .job-strip, .chip--job, [data-job]") || true, "the job strip");
await sleep(800);
out.result = text($(".logs__report .result"));
""")
    assert page["labels"] == ["Collect a Hub report", "Download the latest report"]
    assert "Addresses, serial numbers and names are left out" in page["about"]
    assert [c for c in stub.calls if c[0].startswith("report")] == [("report", "code")]
    assert page["result"] in (None, "")                                                                # the job strip follows the job: nothing is left in the card


def test_download_hands_over_the_newest_report_as_a_text_file(stubbed, tmp_path):
    url, stub = stubbed
    page = drive(url, tmp_path, r"""
await unlock();
const grabbed = [], blobs = [], makeUrl = URL.createObjectURL.bind(URL);
URL.createObjectURL = (blob) => { blobs.push(blob); return makeUrl(blob); };
HTMLAnchorElement.prototype.click = function () { if (this.download) grabbed.push(blobs[blobs.length - 1].text().then((t) => ({ name: this.download, type: blobs[blobs.length - 1].type, text: t }))); };
$('[data-action="download-report"]').click();
await until(() => grabbed.length, "the download");
out.grabbed = await Promise.all(grabbed);
out.result = text($(".logs__report .result"));
""")
    assert page["grabbed"] == [{"name": "hub-report-2026-11-17.txt", "type": "text/plain; charset=utf-8", "text": stub.report_text}]
    assert [c for c in stub.calls if c[0].startswith("report")] == [("report/download", "code")]
    assert page["result"] in (None, "")


def test_service_logs_are_still_there_still_behind_the_code_and_still_read_as_before(stubbed, tmp_path):
    url, stub = stubbed
    page = drive(url, tmp_path, r"""
$('input[name="logs-view"][value="service"]').click();
await until(() => $(".logs .logs__controls .field select"), "the service controls");
await sleep(300);
const view = () => $(".logs");
out.shown = { activity: shown($(".logs__activity")), service: shown(view()), hash: location.hash };
out.locked = { banner: text($(".logs .banner__text")), show: text($(".logs .logs__controls .btn--primary")), units: $$("option", $(".logs .logs__controls .field select")).map((o) => o.value), lines: $$('input[name="logs-lines"]').map((i) => [i.value, i.checked]) };
$(".logs .logs__controls .btn--primary").click();
await until(unlockDialog, "the unlock dialog");
out.dialog = true;
$('[data-action="cancel"]', unlockDialog()).click();
await until(() => !unlockDialog(), "the dialog to close");
SW.setLock("unlocked", { code: "__CODE__" });
await until(() => text($(".logs .logs__controls .btn--primary")) === "Show", "Show");
$(".logs .logs__controls .btn--primary").click();
await until(() => $(".logs .code__text"), "the log");
out.read = { text: text($(".logs .code__text")), caption: text($(".logs .code__caption")) === $(".logs .logs__controls .field select").value, again: text($(".logs .logs__controls .btn--primary")) };
$('input[name="logs-view"][value="activity"]').click();
await sleep(200);
out.back = { activity: shown($(".logs__activity")), rows: rowEls().length };
""")
    assert page["shown"] == {"activity": False, "service": True, "hash": "#logs"}
    assert page["locked"]["banner"] == T("logs_locked") and page["locked"]["show"] == T("logs_unlock_show")
    assert "filament-kit.service" in page["locked"]["units"] and page["locked"]["lines"] == [["50", False], ["100", True], ["200", False]]
    assert page["dialog"] is True
    assert page["read"] == {"text": T("logs_empty"), "caption": True, "again": T("logs_show_again")}
    assert page["back"] == {"activity": True, "rows": 8}
    asked = [c for c in stub.calls if c[0].startswith("logs")]
    assert asked[0] == ("logs/units", None) and asked.count(("logs", None)) == 1                       # one read of a log: the one pressed after unlocking


def test_an_address_naming_a_service_opens_service_logs(stubbed, tmp_path):
    url, _ = stubbed
    page = _drive(url, tmp_path, PRELUDE + r"""
document.documentElement.setAttribute("data-look", "console");
location.hash = "#logs/spoolman.service";
await until(() => $(".logs .logs__controls .field select"), "the service controls");
return { choice: $('input[name="logs-view"]:checked').value, unit: $(".logs .logs__controls .field select").value };
""")
    assert page == {"choice": "service", "unit": "spoolman.service"}


LOOKS = r"""
const seen = [];
for (const look of ["console", "workbench", "palette", "panes"]) {
  document.documentElement.setAttribute("data-look", look);
  await sleep(500);
  const page = { sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth };
  const items = rowEls().map((r) => {
    const box = r.getBoundingClientRect();
    const cells = ["when", "who", "what", "thing"].map((c) => { const el = cellOf(r, c), e = el.getBoundingClientRect(), lh = parseFloat(getComputedStyle(el).lineHeight) || 20; return { c, w: Math.round(e.width), h: Math.round(e.height), lines: Math.round(e.height / lh), inside: e.right <= box.right + 1 && e.left >= box.left - 1 }; });
    const b = $(".btn", cellOf(r, "actions"));
    const bb = b && b.getBoundingClientRect();
    return { id: r.dataset.id, w: Math.round(box.width), cells, btn: bb ? { w: Math.round(bb.width), h: Math.round(bb.height), inside: bb.right <= box.right + 1 && bb.left >= box.left - 1 } : null,
      seen: shown(r) };
  });
  const filters = $$(".logs__activity .field").map((f) => Math.round(f.getBoundingClientRect().width));
  const table = $(".coll--activity").getBoundingClientRect();
  seen.push({ look, page, items, filters, table: Math.round(table.width), inView: table.right <= innerWidth + 1 && table.left >= -1 });
}
out.seen = seen;
"""


@pytest.mark.parametrize("width", [1280, 390])
def test_the_table_is_readable_in_all_four_looks(stubbed, tmp_path, width):
    url, stub = stubbed
    stub.rows[0]["text"] = "Moved Bambu Lab PETG HF Orange Extra Long Name (212) to the Garage shelf, left side, top row."
    page = drive(url, tmp_path, "await unlock();\n" + LOOKS, width=width)
    assert [s["look"] for s in page["seen"]] == ["console", "workbench", "palette", "panes"]
    for s in page["seen"]:
        where = (width, s["look"])
        assert s["page"]["sw"] <= s["page"]["cw"], (where, "the page scrolls sideways", s["page"])
        assert s["inView"] and len(s["items"]) == 8 and all(i["seen"] for i in s["items"]), (where, s["table"])
        for i in s["items"]:
            for c in i["cells"]:
                assert c["inside"], (where, i["id"], c, "a cell drawn outside its row")
                if c["c"] == "what":                       # a cell is as wide as its text asks (Panes and phones lay it out as a card): never a tall sliver
                    assert c["lines"] <= 4 and c["w"] >= 100, (where, i["id"], c, "the What cell is squeezed")
            assert i["btn"] is None or (i["btn"]["inside"] and i["btn"]["h"] < 64 and i["btn"]["w"] >= 32), (where, i["id"], i["btn"])
        assert {i["id"] for i in s["items"] if i["btn"]} == {"9", "6"}, where
        assert all(w >= 120 for w in s["filters"]), (where, "a filter is squeezed", s["filters"])
