// The Settings section's Alerts group (03 10.13): eight switches, the last-spool-only switch, Running low under, Storage warning
// at (one Save, the Hub's alerts.xml) and the part "On this device" (the browser switch kept in this browser, Send a test alert,
// Recent alerts) that applies at once. Loaded after setup_settings.js and setup_alertbar.js (its texts, axt). It is the pattern of
// setup_storage.js: loadAlerts() is the group's read, alertsGroup(data) its builder, ALERTS_GROUP its row for SET_GROUPS.
// Everything from the Hub goes in through textContent.
"use strict";

// ----- the data: the Hub's own routes (03 15) -----
// GET alerts answers {types: [{key, title, on}] (the eight fixed keys), last_spool_only, running_low_g, storage_warn_percent,
// storage_bad_percent}; POST settings/alerts (code) takes the same fields; POST alerts/test (no code) takes {client}.
const ALERT_TYPES = ["runout", "paused", "failed", "printer_error", "finished", "storage", "running_low", "device_down"];
const loadAlerts = () => api("alerts");
// the group's row of SET_GROUPS: id, catalogue key of the name, icon, builder, the read it needs
const ALERTS_GROUP = ["alerts", "settings_group_alerts", "warning", (d) => alertsGroup(d), "alerts"];
const alertsOnCount = (al) => (al.types || []).filter((x) => x.on).length;
// the phone list's one-line state and the title-row badge (03 10.13)
const alertsState = (al) => axt("alerts_settings_state", { count: alertsOnCount(al) });

// the page's own id (the same key and kind as the shared poller makes: a random id kept in this browser)
function axBrowserId() {
  let id = null;
  try { id = localStorage.getItem("spoolwarden.browser"); } catch { /* none */ }
  if (!id) {
    id = window.crypto && crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36);
    try { localStorage.setItem("spoolwarden.browser", id); } catch { /* none */ }
  }
  return id;
}
const alertsRange = (min, max) => (v) => (/^\d+$/.test(v.trim()) && +v >= min && +v <= max ? null : axt("alerts_error_range", { min, max }));

// ----- On this device (03 10.13): applies at once, needs no code, kept in this browser -----
function alertsDevice() {
  const N = () => SW_ALERTS.notifications;
  const res = sbox(), note = h("div", { class: "alerts__state", role: "status" });
  const notify = SW.toggle({ label: axt("alerts_notify_label"), hint: axt("alerts_notify_hint"), checked: N().on() });
  let painting = false;
  // the switch and the words under it from what the browser says now: Blocked, or cannot show notifications
  const paint = () => {
    const say1 = N().say(), on = N().on();
    painting = true;
    notify._control.checked = on;
    notify._control.dispatchEvent(new Event("change"));      // the toggle writes its On / Off word
    painting = false;
    notify.dataset.state = say1 ? "refused" : on ? "on" : "off";
    note.replaceChildren(...(say1 ? [h("b", { textContent: say1.text }), " ", say1.hint] : []));
  };
  notify._control.addEventListener("change", async () => {
    if (painting) return;
    const want = notify._control.checked;
    SW.result(res, null);
    await N().set(want);
    paint();
    if (!N().say()) say(res, axt(N().on() ? "alerts_notify_on" : "alerts_notify_off"), true);
  });
  const test = SW.btn(axt("alerts_test_button"), { action: "alerts-test", run: async () => {
    SW.busy(test, SW.t("common_working"));
    try {
      await api("alerts/test", { client: axBrowserId() });
      say(res, axt("alerts_test_sent"), true);
      SW_ALERTS.poll();                                       // it arrives in the next events answer: ask now, not in 10 s
    } catch (e) {
      if (e.status === 404 || e.status === 405) test.hidden = true;       // an older Hub: the button is hidden (03 15)
      else say(res, hubText(e.message), false);
    } finally { SW.idle(test); }
  } });
  const recent = SW.btn(axt("alerts_recent"), { cls: "btn--ghost", action: "alerts-recent", run: (e) => SW_ALERTS.openList(e.currentTarget) });
  paint();
  return h("section", { class: "alerts__device", "aria-labelledby": "alerts-device-title" },
    h("h3", { class: "settings__heading", id: "alerts-device-title", textContent: axt("alerts_device_heading") }),
    notify, note, h("div", { class: "actions" }, test, recent), res);
}

// ----- the group -----
function alertsGroup({ al }) {
  const sw = (key, label, hint, on) => {
    const t1 = SW.toggle({ label, hint, checked: !!on });
    t1._control.name = key;                                   // the form group reads the named controls
    return t1;
  };
  const on = Object.fromEntries((al.types || []).map((x) => [x.key, x.on]));
  const switches = [];
  for (const key of ALERT_TYPES) {
    switches.push(sw(key, axt("alerts_type_" + key), key === "device_down" ? axt("alerts_type_device_down_hint") : undefined, on[key]));
    if (key === "running_low") {
      const sub = sw("last_spool_only", axt("alerts_last_spool_only"), undefined, al.last_spool_only);
      sub.classList.add("alerts__sub");
      switches.push(sub);
    }
  }
  const bad = al.storage_bad_percent || 95;
  const fields = [
    requiredField({ name: "running_low_g", type: "number", mono: true, label: axt("alerts_running_low_g"), unit: axt("alerts_unit_g"), hint: axt("alerts_running_low_hint"),
      value: String(al.running_low_g), check: alertsRange(10, 2000) }),
    requiredField({ name: "storage_warn_percent", type: "number", mono: true, label: axt("alerts_storage_warn"), unit: axt("alerts_unit_used"),
      hint: axt("alerts_storage_warn_hint", { bad }), value: String(al.storage_warn_percent), check: alertsRange(1, bad - 1) }),
  ];
  const el = setGroup("alerts", { desc: axt("alerts_settings_desc"), save: axt("alerts_settings_save"),
    badges: [SW.status("note", { small: true, cls: "alerts__count", text: alertsState(al) })],
    body: [h("div", { class: "alerts__types" }, ...switches), ...fields, alertsDevice()] });

  // one request for the whole group: the first changed key sends all the fields, the others have nothing more to send
  let plan = null;
  const o = { send: null };
  o.send = async (key) => {
    if (!plan) {
      const form = el.elements, body = { types: ALERT_TYPES.map((k) => ({ key: k, on: form[k].checked })), last_spool_only: form.last_spool_only.checked,
        running_low_g: Number(form.running_low_g.value), storage_warn_percent: Number(form.storage_warn_percent.value) };
      plan = { left: o.group.changed(), reply: null };
      try { plan.reply = await api("settings/alerts", { ...body, code: theCode() }); } catch (e) { plan = null; throw setRefusal(el, e); }
    }
    plan.left = plan.left.filter((k) => k !== key);
    return {};
  };
  o.send.reset = () => { plan = null; };
  wireGroup(el, "alerts", o);
  return el;
}
