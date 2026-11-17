// The stub Hub of the alert tests (server/tests/test_alerts_ui.py): a fake GET api/events in the shape of DECISIONS R80
// section 8, held in window.__hub (tests change it, then call SW_ALERTS.poll()), and the alert banner host started on it.
// ?scenario=blank (nothing raised) | layout (two conditions, two moments, one more condition); ?manual=1 does not start the poller.
(() => {
"use strict";
const query = new URLSearchParams(location.search), MIN = 60000;
const hub = window.__hub = { events: [], conditions: [], requests: [], now: Date.now(), fail: false, gap: false, oldest: 1, test: null };
window.__now = () => hub.now;
const iso = (ms) => new Date(ms).toISOString().replace(/\.\d+Z$/, "Z");
let nextId = 1;
// ev({...}) -> an event of the contract; `ago` minutes before the stub's clock
window.__ev = (o) => {
  const set = Object.fromEntries(Object.entries(o).filter(([k, v]) => v !== undefined && k !== "ago"));      // undefined = keep the default
  return { id: nextId++, at: iso(hub.now - (o.ago || 0) * MIN), kind: "print.failed", severity: "bad",
    subject: { type: "printer", id: "p-3", name: "Workshop X1" }, actor: { type: "hub" }, data: {}, condition: null, alert: true,
    title: "", text: "", action: { place: "printer", id: "p-3" }, ...set };
};
window.__add = (e, o = {}) => {       // the Hub writes the event; a condition event also changes the raised list
  hub.events.push(e);
  if (e.condition && e.condition.state === "raised") hub.conditions = hub.conditions.filter((c) => c.condition.key !== e.condition.key).concat(e);
  if (e.condition && e.condition.state === "cleared") hub.conditions = hub.conditions.filter((c) => c.condition.key !== e.condition.key);
  return e;
};
SW.configure({ base: "api/", hub: "Workshop hub", fetch: async (url) => {
  hub.requests.push(url);
  if (hub.fail) throw new TypeError("offline");
  const q = new URLSearchParams(url.split("?")[1] || ""), since = q.get("since") == null ? 0 : Number(q.get("since"));
  const sinceAt = q.get("since_at") ? Date.parse(q.get("since_at")) : null;      // since_at: by time; alert=1: alert events only
  const events = hub.events.filter((e) => (sinceAt == null ? e.id > since : Date.parse(e.at) >= sinceAt) && (q.get("alert") !== "1" || e.alert))
    .slice(0, Number(q.get("limit")) || 100);
  const test = hub.test; hub.test = null;                  // a test alert from POST api/alerts/test arrives once
  const next = hub.events.length ? Math.max(...hub.events.map((e) => e.id)) : since;
  return { ok: true, status: 200, json: async () => ({ events, next, oldest: hub.oldest, gap: hub.gap, conditions: hub.conditions, ...(test ? { test } : {}) }) };
} });

const scenario = query.get("scenario") || "blank";
if (scenario === "layout") {
  const cond = (kind, sev, key, ago, subject, data, action) => window.__add(window.__ev({ kind, severity: sev, ago, subject, data,
    condition: { key, state: "raised" }, action }));
  cond("print.runout", "warn", "print-paused:p-3", 62, undefined, { job: "bracket_v4.3mf", percent: 41, slot: "A2" });
  cond("storage.low", "bad", "storage-low", 20, { type: "hub", id: "hub", name: "Hub" }, { free: 3.2e9, total: 64e9, percent: 95 }, { place: "storage-use" });
  cond("spool.low", "warn", "spool-low:214", 5, { type: "spool", id: "214", name: "Spool 214" },
    { spool: 214, filament: "Polymaker PLA Teal", grams: 92, others: 2 }, { place: "running-low" });
  window.__add(window.__ev({ kind: "printer.error", ago: 8, data: { code: "0300-0100", text: "The nozzle temperature is abnormal and the printer stopped." } }));
  window.__add(window.__ev({ kind: "print.failed", ago: 3, subject: { type: "printer", id: "p-4", name: "Study A1 mini" }, data: { job: "gear.3mf", percent: 12, reason: "cancelled" } }));
}

// the icon sprite, as the Hub's pages carry it inline
const ready = fetch("/icons/sprite.svg").then((r) => r.text()).then((text) => {
  document.body.prepend(document.importNode(new DOMParser().parseFromString(text, "image/svg+xml").documentElement, true));
});
window.__ready = ready.then(() => (query.get("manual") ? null : window.SW_ALERTS.start({ interval: Number(query.get("interval")) || 10000, now: window.__now })));
})();
