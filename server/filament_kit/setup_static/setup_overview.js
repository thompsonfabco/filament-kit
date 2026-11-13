// The Overview section: the checklist and the status rows.
// Loaded after setup.js; everything from the server goes in through textContent, as there.
"use strict";

// ----- Overview -----
const ROW_MARK = { ok: ["ok", "OK"], fail: ["bad", "needs a look"], info: ["", "note"] };
function rowEl(r) {
  if (r.state === "detail") return h("p", { class: "muted indent", textContent: r.text });
  const [cls, word] = ROW_MARK[r.state] || ROW_MARK.info;
  const box = r.action ? boxFor("check:" + r.action) : slot();
  return h("div", { class: "item" },
    h("p", {}, h("span", { class: "pill " + cls, textContent: word }), " ", r.text),
    r.state === "fail" && r.fix ? h("p", { class: "muted indent", textContent: `Fix: ${r.fix}` }) : null,
    r.action === "ensure_fields" ? h("div", { class: "row" }, h("button", { textContent: "Make the fields", on: { click: () => change(box, "fields", {}, () => say(box, "Done.", true)) } })) : null,
    box);
}

function checklist() {
  const todo = [];
  if (!S.code_set) todo.push("No setup code yet: at the server, sudo filament-kit setup-code");
  if (S.printers.on && !S.printers.list.length) todo.push(["Printers: none yet → ", link("printers", "Printers")]);
  if (!S.devices.length) todo.push(["Phone: not paired → ", link("devices", "Devices")]);
  if (!S.devices.length && !S.printers.list.length) todo.push(["Moving from another computer? Restore its backup → ", link("settings", "Settings")]);
  if (S.anthropic.ai_intake && !S.anthropic.set) todo.push(["Anthropic key: not set → ", link("settings", "Settings")]);
  if (S.passphrase.web && !S.passphrase.set) todo.push(["Web passphrase: not set → ", link("settings", "Settings")]);
  return todo.length ? card("Still to do", h("ul", {}, ...todo.map((t) => h("li", {}, t)))) : null;
}

function overviewTab() {
  const rowsBox = h("div");
  const head = h("div"), note = h("div", { role: "status" });     // the hidden-values note
  const show = (r) => {
    const u = r.update;
    head.replaceChildren(h("p", {}, `filament-kit ${r.version_text || r.version} · mode ${S.mode} `,
      u.newer ? h("span", { class: "pill no", textContent: `${u.latest} is available` }) : null,
      " ", link("updates", u.newer ? "Update" : "Updates")));
    fill(rowsBox,
      u.half_install && !r.job.running ? h("p", { textContent: `The last install or update stopped halfway. To repair it, run on the server: ${u.half_install}` }) : null,
      ...r.rows.map(rowEl));
    note.replaceChildren(...(r.redacted ? [lockNote("lock_hidden_note")] : []));
  };
  // addresses and serials load by themselves once the page is open, and are read again without the code when it locks
  whenOpen(rowsBox, (open) => readRegion(rowsBox, "overview", () => (open ? api("overview", { code: theCode() }) : api("overview")), show));
  return [checklist(), card("Status", head, rowsBox, note)];
}
