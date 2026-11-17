// Scenarios of server/tests/test_alerts_ui.py, run in the alerts page by tests/page_drive.mjs (one async function body; the
// Python test replaces __SCENARIO__ with the name to run). Each returns plain data for the test to check.
const A = window.SW_ALERTS, hub = window.__hub, ev = window.__ev, add = window.__add;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const q = (s) => document.querySelector(s), qa = (s) => [...document.querySelectorAll(s)];
const MIN = 60000, HOUR = 60 * MIN, DAY = 24 * HOUR;
const kindOf = (b) => [...b.classList].find((c) => c.startsWith("banner--")).slice(8);
const banners = () => qa(".alert-host .banner").map((b) => ({
  kind: kindOf(b), title: b.querySelector("b").textContent, text: b.querySelector(".banner__text").textContent.trim(),
  time: b.querySelector(".alert__time").textContent, role: b.getAttribute("role"), key: b.dataset.alert,
  action: (b.querySelector(".actions .btn") || {}).textContent || null, href: (b.querySelector(".actions a") || {}).getAttribute?.("href") || null,
  dismiss: !!b.querySelector('[data-action="dismiss"]'),
}));
const more = () => { const m = q(".alert-more"); return m ? m.textContent.trim() : null; };
const toasts = () => qa(".toast .toast__text").map((x) => x.textContent);
const dismiss = (i) => qa(".alert-host .banner")[i].querySelector('[data-action="dismiss"]').click();
const store = (k) => localStorage.getItem("spoolwarden.dismissed.alert." + k);
const raise = (kind, sev, key, o = {}) => add(ev({ kind, severity: sev, condition: { key, state: "raised" }, ...o }));
const clear = (kind, key, o = {}) => add(ev({ kind, severity: "ok", condition: { key, state: "cleared" }, alert: false, ...o }));
const list = () => {
  const d = q("dialog.dialog[open]");
  if (!d) return null;
  return { rows: qa("dialog[open] .alert-row").map((r) => ({ title: r.querySelector(".alert-row__title").textContent, time: r.querySelector(".alert-row__time").textContent,
    text: (r.querySelector(".alert-row__text") || {}).textContent || "", action: (r.querySelector(".btn") || {}).textContent || null, kind: [...r.classList].find((c) => c.startsWith("alert-row--")).slice(11) })),
    headings: qa("dialog[open] .alert-list__heading").map((x) => x.textContent), empty: (q("dialog[open] .alert-list__empty") || {}).textContent || null,
    title: q("dialog[open] .dialog__title").textContent };
};
const closeList = () => { const d = q("dialog[open]"); if (d) d.close(); };
const fresh = async (o = {}) => { A.stop(); hub.events = []; hub.conditions = []; hub.requests = []; hub.fail = false; localStorage.clear(); qa(".toast").forEach((x) => x.remove());
  await A.start({ now: window.__now, interval: 100000, ...o }); };

const SCENARIOS = {
  async content() {       // layout scenario: 2 banners, "3 more alerts", the most serious first then the newest
    await window.__ready;
    const first = banners(), moreFirst = more(), toastsAtOpen = toasts();
    dismiss(0);
    await sleep(50);
    return { first, moreFirst, toastsAtOpen, afterDismiss: banners().map((b) => b.title), moreAfter: more(), hostKids: q(".alert-host").children.length };
  },
  async limits() {        // one, two, three alerts
    await window.__ready;
    await fresh();
    const out = {};
    raise("storage.low", "warn", "storage-low", { subject: { type: "hub", id: "hub", name: "Hub" }, data: { free: 9e9, total: 64e9, percent: 86 }, action: { place: "storage-use" } });
    await A.poll(); out.one = [banners().length, more()];
    raise("print.paused", "warn", "print-paused:p-3", { data: { job: "a.3mf", percent: 5, reason: "user" } });
    await A.poll(); out.two = [banners().length, more()];
    raise("device.down", "warn", "device-down:d1", { subject: { type: "device", id: "d1", name: "Bench scale" }, action: { place: "devices" } });
    await A.poll(); out.three = [banners().map((b) => b.title), more()];
    out.threeText = banners().map((b) => b.text);
    return out;
  },
  async dismiss_rules() {
    await window.__ready;
    await fresh();
    const out = {};
    raise("storage.low", "warn", "storage-low", { subject: { type: "hub", id: "hub", name: "Hub" }, data: { free: 9e9, total: 64e9, percent: 86 }, action: { place: "storage-use" } });
    await A.poll(); out.shown = banners().map((b) => [b.title, b.dismiss]);
    dismiss(0); await sleep(30);
    out.afterDismiss = banners().length; out.stored = store("storage-low");
    await A.poll(); await A.poll(); out.stillHidden = banners().length;
    hub.now += 3 * MIN; A.paint(); out.stillHiddenLater = banners().length;
    raise("storage.low", "bad", "storage-low", { subject: { type: "hub", id: "hub", name: "Hub" }, data: { free: 1e9, total: 64e9, percent: 98 }, action: { place: "storage-use" } });
    await A.poll(); out.worse = banners().map((b) => [b.kind, b.title]);
    dismiss(0); await sleep(30); out.afterSecond = banners().length;
    clear("storage.ok", "storage-low", { subject: { type: "hub", id: "hub", name: "Hub" } });
    await A.poll(); out.cleared = banners().length; out.keyAfterClear = store("storage-low");
    raise("storage.low", "warn", "storage-low", { subject: { type: "hub", id: "hub", name: "Hub" }, data: { free: 9e9, total: 64e9, percent: 86 }, action: { place: "storage-use" } });
    await A.poll(); out.raisedAgain = banners().map((b) => b.title);
    return out;
  },
  async conditions_and_moments() {
    await window.__ready;
    await fresh();
    const out = {};
    raise("print.runout", "warn", "print-paused:p-3", { data: { job: "bracket_v4.3mf", percent: 41, slot: "A2" } });
    add(ev({ kind: "print.failed", severity: "bad", ago: 30, subject: { type: "printer", id: "p-4", name: "Study A1 mini" }, data: { job: "gear.3mf", percent: 12, error: "Nozzle clogged." } }));
    await A.poll(); out.both = banners().map((b) => [b.title, b.time]);
    clear("print.resumed", "print-paused:p-3");
    await A.poll(); out.condLeft = banners().map((b) => b.title);
    await sleep(10);
    hub.now += 23 * HOUR; A.paint(); out.at23h = banners().length;
    hub.now += 2 * HOUR; A.paint(); out.at25h = banners().length;
    // a moment stays until dismissed, on this device
    await fresh();
    add(ev({ kind: "printer.error", severity: "bad", ago: 1, data: { code: "0300", text: "The chamber door is open." } }));
    await A.poll(); out.errorShown = banners().map((b) => [b.title, b.text]);
    await A.poll(); await A.poll(); out.errorStays = banners().length;
    dismiss(0); await sleep(30); out.errorDismissed = banners().length; out.errorKey = Object.keys(localStorage).filter((k) => k.startsWith("spoolwarden.dismissed.alert.e")).length;
    // a switched-off alert type (alert false) has no banner
    await fresh();
    raise("print.paused", "warn", "print-paused:p-3", { alert: false, data: { job: "x.3mf", percent: 1 } });
    add(ev({ kind: "print.failed", severity: "bad", alert: false, data: { job: "x.3mf", percent: 1 } }));
    await A.poll(); out.switchedOff = banners().length;
    return out;
  },
  async list() {
    await window.__ready;
    const out = {};
    // old events, a switched-off event and an event of the last 7 days
    const other = { type: "printer", id: "p-9", name: "Garage P1S" };
    add(ev({ kind: "print.finished", severity: "ok", ago: 7 * 24 * 60 + 60, subject: other, data: { job: "old.3mf" }, condition: { key: "print-paused:p-9", state: "cleared" } }));
    add(ev({ kind: "print.finished", severity: "ok", ago: 60 * 5, subject: other, data: { job: "calibration.3mf" }, condition: { key: "print-paused:p-9", state: "cleared" } }));
    add(ev({ kind: "print.started", severity: "info", alert: false, ago: 70 }));
    await A.poll();
    q(".alert-more button").click();
    await sleep(80);
    out.layout = list();
    const dlg = q("dialog[open]"), opener = q(".alert-more button");
    dlg.close(); await sleep(50);
    out.focusBack = document.activeElement === opener || document.activeElement === document.querySelector("main h1");
    out.closed = !q("dialog[open]");
    await fresh();
    A.openList(); await sleep(80); out.empty = list(); closeList();
    return out;
  },
  async poller() {
    await window.__ready;
    const out = {};
    await fresh();
    out.firstUrl = hub.requests[0]; out.client = localStorage.getItem("spoolwarden.browser");
    add(ev({ kind: "print.failed", severity: "bad", data: { job: "a.3mf", percent: 3 } }));
    add(ev({ kind: "print.failed", severity: "bad", data: { job: "b.3mf", percent: 4 }, subject: { type: "printer", id: "p-5", name: "Third" } }));
    await A.poll(); out.secondUrl = hub.requests[hub.requests.length - 1];
    await A.poll(); await A.poll(); out.cursor = A.state().cursor; out.stored = A.state().events.length; out.banners = banners().length; out.toasts = toasts().length;
    out.thirdUrl = hub.requests[hub.requests.length - 1];
    // the rhythm: a timer polls by itself
    await fresh({ interval: 120 });
    const n = hub.requests.length;
    add(ev({ kind: "printer.error", severity: "bad", data: { code: "1", text: "Jam." } }));
    await sleep(700);
    out.timerPolls = hub.requests.length - n; out.timerArrived = banners().map((b) => b.title);
    // a Hub that does not answer: the banners stay, the next answer is taken
    hub.fail = true; await A.poll(); await sleep(150); out.failedKept = banners().length;
    hub.fail = false; add(ev({ kind: "print.failed", severity: "bad", data: { job: "c.3mf", percent: 9 } })); await sleep(400); out.recovered = A.state().events.length;
    A.stop();
    const stopped = hub.requests.length; await sleep(400); out.stopped = hub.requests.length === stopped;
    return out;
  },
  async arrivals() {
    await window.__ready;
    await fresh();
    const out = {};
    add(ev({ kind: "print.failed", severity: "bad", ago: 1, data: { job: "old.3mf", percent: 7 } }));
    await A.stop(); await A.start({ now: window.__now, interval: 100000 });
    out.historyToasts = toasts().length;
    add(ev({ kind: "print.failed", severity: "bad", subject: { type: "printer", id: "p-4", name: "Study A1 mini" }, data: { job: "gear.3mf", percent: 12, reason: "cancelled" } }));
    await A.poll(); out.arrived = toasts(); out.toastAction = (q(".toast .btn") || {}).textContent || null;
    raise("print.paused", "warn", "print-paused:p-3", { data: { job: "a.3mf", percent: 5, reason: "user" } });
    await A.poll(); out.raised = toasts().length;
    raise("print.runout", "warn", "print-paused:p-3", { data: { job: "a.3mf", percent: 5 } });
    await A.poll(); out.againWhileLasting = toasts().length;
    clear("print.resumed", "print-paused:p-3"); add(ev({ kind: "spool.low", severity: "warn", alert: false }));
    await A.poll(); out.clearedAndOff = toasts().length;
    raise("print.paused", "warn", "print-paused:p-3", { data: { job: "a.3mf", percent: 6, reason: "user" } });
    await A.poll(); out.raisedAfterClear = toasts().length;
    // late banners are announced: alert for bad, status for the others
    out.roles = banners().map((b) => [b.kind, b.role]);
    await sleep(4300); out.rolesLater = banners().map((b) => b.role);
    return out;
  },
  async gap_and_test() {
    await window.__ready;
    await fresh();
    const out = {};
    raise("print.paused", "warn", "print-paused:p-3", { data: { job: "a.3mf", percent: 5, reason: "user" } });
    await A.poll(); out.before = banners().length; out.toastsBefore = toasts().length;
    // the Hub dropped events: the batch is not replayed (no toasts); the conditions are the truth
    hub.gap = true;
    add(ev({ kind: "print.failed", severity: "bad", data: { job: "z.3mf", percent: 2 } }));
    clear("print.resumed", "print-paused:p-3");
    hub.oldest = hub.events[hub.events.length - 2].id; await A.poll(); out.gapToasts = toasts().length; out.afterGap = banners().map((b) => b.title); hub.gap = false;
    // "Send a test alert": the answer carries `test` once
    hub.test = { title: "Test alert", text: "This is a test." };
    await A.poll(); out.testToasts = toasts().filter((x) => x === "Test alert"); await A.poll(); out.testOnce = toasts().filter((x) => x === "Test alert").length;
    return out;
  },
  async late_roles() {    // present at open: plain; arrived later: announced
    await window.__ready;
    const atOpen = banners().map((b) => b.role);
    raise("storage.low", "warn", "storage-low", { subject: { type: "hub", id: "hub", name: "Hub" }, data: { free: 9e9, total: 64e9, percent: 86 }, action: { place: "storage-use" } });
    add(ev({ kind: "printer.error", severity: "bad", data: { code: "1", text: "Jam." }, subject: { type: "printer", id: "p-9", name: "Late one" } }));
    await A.poll();
    return { atOpen, later: banners().map((b) => [b.title, b.kind, b.role]) };
  },
  async backfill() {     // more alert events in the week than `limit`: the first calls page on, all of it history
    await window.__ready;
    class Fake { static permission = "granted"; static made = []; constructor(title, o) { this.title = title; this.o = o; Fake.made.push(this); } close() { this.closed = true; } }
    await fresh({ Notification: Fake, limit: 200 });
    const out = {};
    localStorage.setItem("spoolwarden.alerts.notifications", "1");
    const total = 450;
    for (let i = 0; i < total; i++) add(ev({ kind: "print.failed", severity: "bad", ago: (total - i) * 20 - 10, data: { job: `old${i}.3mf`, percent: 3 } }));   // 10 min to 6.25 days old, oldest first
    const lastId = hub.events[total - 1].id;
    hub.requests = [];
    await A.start({ now: window.__now, interval: 100000, Notification: Fake, limit: 200 });
    out.urls = hub.requests.map((u) => u.replace(/since_at=[^&]+/, "since_at=T").replace(/&client=.*/, ""));
    out.lastId = lastId; out.cursor = A.state().cursor; out.stored = A.state().events.length;
    out.toasts = toasts().length; out.notified = Fake.made.length;
    out.banners = banners().map((b) => b.title); out.more = more();
    A.openList(); await sleep(150); out.rows = list().rows.length; closeList();
    await A.poll(); out.quiet = [toasts().length, Fake.made.length, hub.requests[hub.requests.length - 1].startsWith(`api/events?since=${lastId}&alert=1`)];
    add(ev({ kind: "printer.error", severity: "bad", data: { code: "9", text: "Jam." } }));
    await A.poll(); out.after = [toasts().length, Fake.made.map((n) => n.title)];
    // an event from long before the page opened is history even when it comes late
    add(ev({ kind: "print.failed", severity: "bad", ago: 3 * 24 * 60, data: { job: "late.3mf", percent: 1 } }));
    await A.poll(); out.lateOld = [toasts().length, Fake.made.length];
    return out;
  },
  async notifications() {
    await window.__ready;
    const out = {};
    class Fake { static permission = "default"; static made = []; static async requestPermission() { Fake.asked = (Fake.asked || 0) + 1; Fake.permission = Fake.answer; return Fake.answer; }
      constructor(title, o) { this.title = title; this.o = o; Fake.made.push(this); } close() { this.closed = true; } }
    const N = A.notifications;
    // the real browser's state, untouched
    out.real = N.permission();
    // granted by the person
    Fake.answer = "granted"; Fake.made = [];
    await fresh({ Notification: Fake });
    out.initial = [N.permission(), N.on(), N.say()];
    out.setOn = await N.set(true); out.asked = Fake.asked; out.onAfter = N.on();
    add(ev({ kind: "print.failed", severity: "bad", subject: { type: "printer", id: "p-4", name: "Study A1 mini" }, data: { job: "gear.3mf", percent: 12, reason: "cancelled" } }));
    await A.poll(); await A.poll(); await A.poll();
    out.one = Fake.made.map((n) => [n.title, n.o.body, n.o.tag]);
    raise("print.paused", "warn", "print-paused:p-3", { data: { job: "a.3mf", percent: 5, reason: "user" } });
    await A.poll(); out.afterRaise = Fake.made.length;
    raise("print.runout", "warn", "print-paused:p-3", { data: { job: "a.3mf", percent: 5 } });
    await A.poll(); out.afterAgain = Fake.made.length;
    // a raised condition is tagged by its key; its clearing closes that notification and sends nothing new; a moment keeps its event tag
    out.tags = Fake.made.map((n) => n.o.tag);
    clear("print.resumed", "print-paused:p-3");
    await A.poll(); out.afterClear = Fake.made.length; out.closedFlags = Fake.made.map((n) => !!n.closed);
    add(ev({ kind: "storage.low", severity: "warn", alert: false, subject: { type: "hub", id: "hub", name: "Hub" } }));
    await A.poll(); out.afterOff = Fake.made.length;
    await N.set(false); out.offState = [N.on(), N.permission()];
    add(ev({ kind: "printer.error", severity: "bad", data: { code: "1", text: "Jam." } }));
    await A.poll(); out.afterSwitchOff = Fake.made.length;
    // blocked in the browser's settings
    Fake.permission = "denied"; Fake.made = []; Fake.asked = 0; await N.set(false);
    out.denied = [N.permission(), N.say(), await N.set(true), N.on(), Fake.asked];
    add(ev({ kind: "printer.error", severity: "bad", data: { code: "2", text: "Jam again." } }));
    await A.poll(); out.deniedMade = Fake.made.length;
    // a browser with no notifications at all
    const real = window.Notification; delete window.Notification;
    await fresh();
    out.unsupported = [N.permission(), N.say(), await N.set(true), N.on()];
    window.Notification = real;
    // the browser answers "denied" to the request itself
    Fake.permission = "default"; Fake.answer = "denied"; await fresh({ Notification: Fake });
    out.refused = [await N.set(true), N.on(), N.say()];
    return out;
  },
};
return await SCENARIOS["__SCENARIO__"]();
