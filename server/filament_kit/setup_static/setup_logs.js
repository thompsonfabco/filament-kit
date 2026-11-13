// The console's Logs section (03 13). Loaded after setup.js; everything from the server goes in through textContent, as there.
// Logs hold addresses and serial numbers, so reading them takes the setup code; nothing is kept on the page once it locks.
"use strict";

const LOG_LINES = [50, 100, 200];
let logBlocks = 0;

// `#logs/<service>` shows that service once the page is open
const wantedUnit = () => {
  try { return decodeURIComponent(location.hash.slice(1).split("/")[1] || ""); } catch { return ""; }
};

function logsView(units) {
  const want = units.includes(wantedUnit()) ? wantedUnit() : "";
  const unit = SW.field({ label: SW.t("logs_service"), type: "select", mono: true, value: want || units[0],
    options: units.map((u) => ({ value: u, label: u })) });
  const lines = SW.segmented({ legend: SW.t("logs_lines"), name: "logs-lines", value: "100",
    options: LOG_LINES.map((n) => ({ value: String(n), label: String(n) })) });
  const show = SW.btn(SW.t("common_show"), { cls: "btn--primary", run: () => read() });
  const locked = h("div", { role: "status" });
  const out = h("div", { class: "logs__out" });
  const controls = h("div", { class: "logs__controls" }, unit, lines, show);
  let seen = false, running = false, again = false;

  const label = () => { show.textContent = SW.t(seen ? "logs_show_again" : SW.lock.state === "locked" ? "logs_unlock_show" : "common_show"); };
  const block = (service, text) => {
    const id = "log-" + ++logBlocks;
    const copy = SW.btn(SW.t("common_copy"), { cls: "btn--ghost", icon: "copy", action: text ? "copy" : null });
    if (!text) SW.disable(copy, SW.t("code_nothing"));
    return h("div", { class: "code" },
      h("div", { class: "code__bar" }, h("span", { class: "code__caption mono", id: id + "-name", textContent: service }),
        h("span", { class: "result", role: "status" }), copy),
      h("pre", { class: "code__text", tabindex: "0", "aria-labelledby": id + "-name", textContent: text || SW.t("logs_empty") }));
  };
  const read = () => needCode(async () => {
    if (running) { again = true; return; }
    running = true;
    SW.busy(show, SW.t("common_reading"));
    const sent = { unit: unit._control.value, lines: Number(lines.querySelector("input:checked").value) };
    try {
      const r = await api("logs", { ...sent, code: theCode() });
      if (SW.lock.state === "locked") return;      // locked while it was read: the reply is dropped, not written back
      seen = true;
      out.replaceChildren(block(sent.unit, r.text),
        r.truncated ? h("p", { class: "muted", textContent: SW.t("logs_truncated") }) : null);
    } catch (e) {
      if (e.locked) { again = false; throw e; }
      out.replaceChildren(h("div", { class: "code" }, SW.errorState({ title: SW.t("logs_read_error"), text: hubText(e.message), level: 3,
        onTry: () => read() })));
    } finally {
      running = false;
      SW.idle(show);
      label();
    }
    if (again) { again = false; read(); }
  });
  // Unlocked or Trusted, a new choice shows its log at once; Locked, Show asks for the code first
  controls.addEventListener("change", () => { if (SW.lock.state !== "locked") read(); });
  whenOpen(controls, (open) => {
    if (open) {
      locked.replaceChildren();
      if (want && !seen) read();
    } else {
      seen = false;
      out.replaceChildren();
      locked.replaceChildren(h("div", { class: "banner banner--info banner--inline" }, SW.icon("lock", "icon--s"),
        h("p", { class: "banner__text", textContent: SW.t("logs_locked") })));
    }
    label();
  });
  return h("div", { class: "logs" }, locked, controls, out);
}

function logsTab() {
  const body = h("div");
  later(readRegion(body, "logs", () => api("logs/units"), (r) => {
    if (!r.units.length) { fill(body, SW.empty({ icon: "logs", title: SW.t("logs_none"), level: 3 })); return; }
    fill(body, logsView(r.units));
  }));
  return [card(SW.t("nav_logs"), body)];
}
