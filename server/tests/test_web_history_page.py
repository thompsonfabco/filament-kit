"""The history pieces of the phone web app's page script (R84, HD8): Undo after an action, the refusal sentences, a spool's events and
the downloads, run in Node without a browser (the page's own functions are cut out of app.js and given stubs for `api`, `SW` and `tt`)."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from test_web_app import STATIC

HARNESS = r"""
const tt = (k, v) => k + (v ? JSON.stringify(v) : "");
const whenText = (v) => String(v);
const h = (tag, props, ...kids) => ({ tag, props: props || {}, kids: kids.flat().filter((k) => k != null && k !== false), replaceChildren(...k) { this.kids = k.flat(); } });
const calls = [], toasts = [];
let answers = {};
const api = async (path, opts = {}) => {
  calls.push([path, opts.body === undefined ? "GET" : "POST"]);
  const a = answers[path.split("?")[0].replace(/\/\d+\//, "/N/")];
  if (a instanceof Error) throw a;
  return typeof a === "function" ? a(path, opts) : a;
};
const SW = { toast: (text, kind, o) => { toasts.push([text, kind || "ok", o && o.action ? o.action : null]); }, t: (k) => k };
const window = {};
%s
(async () => {
  const out = {};
  // a possible Undo: a toast with the action, which posts the event's undo and says "Put back."
  answers = { activity: { events: [{ id: 41, undo: { possible: true } }] }, "events/N/undo": { undone: true } };
  let done = 0;
  out.offered = await offerUndo(5, "Moved to Shelf B.", () => { done++; });
  out.firstToast = [toasts[0][0], toasts[0][2].label];
  await toasts[0][2].run();
  out.afterUndo = { calls: calls.slice(), toast: toasts[1], done };
  // an answer that names its event (event_id): no question to the Hub, Undo posts that event
  toasts.length = 0; calls.length = 0;
  answers = { "events/N/undo": { undone: true } };
  out.named = await offerUndo(5, "Weighed.", null, 77);
  await toasts[0][2].run();
  out.namedCalls = calls.slice();
  // not possible, or no events, or a Hub with no activity route: no Undo, and the caller shows its own toast
  toasts.length = 0; calls.length = 0;
  answers = { activity: { events: [{ id: 42, undo: { possible: false, why_not: "too_old" } }] } };
  out.notPossible = await offerUndo(5, "x");
  answers = { activity: { events: [] } };
  out.noEvents = await offerUndo(5, "x");
  answers = { activity: Object.assign(new Error("not found"), { status: 404 }) };
  out.noRoute = await offerUndo(5, "x");
  out.quiet = toasts.length;
  // the Hub's refusal codes become their sentences; any other failure its own
  toasts.length = 0;
  answers = { activity: { events: [{ id: 43, undo: { possible: true } }] }, "events/N/undo": Object.assign(new Error("x"), { data: { code: "changed_since" } }) };
  await offerUndo(5, "y"); await toasts[0][2].run();
  answers["events/N/undo"] = Object.assign(new Error("x"), { data: { code: "weird" } });
  await toasts[0][2].run();
  out.refusals = toasts.slice(1).map((t) => [t[0], t[1]]);
  // the subject of the question and the cut-out limit
  out.asked = calls.filter((c) => c[0].startsWith("activity")).map((c) => c[0]).slice(-1);
  // a row: the text, who, and "put back" for an undone one
  const row = (e) => JSON.stringify(eventRow(e));
  out.row = row({ at: "T", text: "Moved.", actor: { name: "Pat phone" } });
  out.undoneRow = row({ at: "T", title: "Weighed", undone: true });
  // the box: a list, an empty note, nothing at all when the Hub has no route
  const box = historyBox(7);
  answers = { activity: { events: [{ at: "T", text: "A" }, { at: "T", text: "B" }] } };
  out.listed = [await box.load(), box.box.kids ? box.box.kids : null];
  answers = { activity: { events: [] } };
  out.empty = await box.load();
  answers = { activity: Object.assign(new Error("nf"), { status: 404 }) };
  out.none = await box.load();
  console.log(JSON.stringify(out));
})();
"""


def _source() -> str:
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    start = js.index("const undoWhy = ")
    end = js.index("// the downloads of a phone")
    return js[start:end]


def _run(tmp_path, body):
    node = shutil.which("node")
    if not node:
        pytest.skip("needs Node")
    (tmp_path / "h.js").write_text(HARNESS % body, encoding="utf-8")
    run = subprocess.run([node, str(tmp_path / "h.js")], capture_output=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_undo_is_offered_only_when_the_hub_can_put_it_back(tmp_path):
    out = _run(tmp_path, _source())
    assert out["offered"] is True and out["firstToast"] == ["Moved to Shelf B.", "common_undo"]
    assert out["afterUndo"]["calls"] == [["activity?subject=spool:5&limit=1", "GET"], ["events/41/undo", "POST"]]
    assert out["afterUndo"]["toast"][0] == "history_undo_put_back" and out["afterUndo"]["done"] == 1      # the spool is drawn again
    assert out["named"] is True and out["namedCalls"] == [["events/77/undo", "POST"]]
    assert out["notPossible"] is False and out["noEvents"] is False and out["noRoute"] is False and out["quiet"] == 0
    assert [t[0] for t in out["refusals"]] == ["history_undo_changed_since", "history_undo_failed"]       # a code of the Hub, or the general one
    assert all(t[1] == "bad" for t in out["refusals"])


def test_a_spools_events_are_listed_with_who_and_a_put_back_mark(tmp_path):
    out = _run(tmp_path, _source())
    assert "Moved." in out["row"] and 'history_by{\\"who\\":\\"Pat phone\\"}' in out["row"]
    assert "history_undone" in out["undoneRow"] and "Weighed" in out["undoneRow"]
    assert out["listed"][0] is True and out["empty"] is True and out["none"] is False      # no route: no list, no error


def test_the_downloads_and_by_month_are_wired_to_the_twins():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "`${BASE}/api/export/${key}.csv" in js and 'downloadLink("spoolman-spools"' in js and 'downloadLink("recent"' in js
    assert "health?days=${days}" in js and 'tt("health_col_" + k)' in js          # the table, never colour alone
    pj = (STATIC / "printers.js").read_text(encoding="utf-8")
    assert "usage?by=month" in pj and 'downloadLink("usage"' in pj and "undoToast(" in pj
    assert "SW_HISTORY" in js and "SW_HISTORY" in pj
