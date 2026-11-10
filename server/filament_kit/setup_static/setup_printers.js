// The console's Printers tab. Loaded after setup.js; everything from the server goes in through textContent, as there.
// A Klipper printer has no Access Code and a Bambu printer no API key: each family's words and controls appear only with its module on.
"use strict";

const printerPath = (p, what) => `printers/${encodeURIComponent(p.serial)}/${what}`;
const nice = (s) => String(s).replace(/_/g, " ");
const dotted = (...parts) => parts.filter(Boolean).map((t) => ` · ${t}`).join("");
const hostPort = (p) => `${p.host.includes(":") ? `[${p.host}]` : p.host}:${p.port}`;

function testButton(p, box) {
  return h("button", { class: "secondary", textContent: "Test", on: { click: async () => {
    box.replaceChildren(h("p", { class: "muted", textContent: "Testing…" }));
    try { const r = await api(printerPath(p, "test"), {}); say(box, `${r.text}\nconnection: ${nice(r.state)}`, r.reachable); } catch (e) { say(box, e.message, false); }
  } } });
}

function forgetButton(p, box, words) {
  return h("button", { class: "secondary", textContent: "Forget", on: { click: () => { if (window.confirm(`Forget ${p.name}? ${words}`)) change(box, printerPath(p, "forget"), {}); } } });
}

function renameButton(p, box) {
  return h("button", { class: "secondary", textContent: "Rename", on: { click: () => {
    const name = window.prompt(`A new name for ${p.name}:`, p.name);
    if (name && name.trim()) change(box, printerPath(p, "rename"), { name: name.trim() });
  } } });
}

function addressButton(p, box, now) {
  return h("button", { class: "secondary", textContent: "Change address", on: { click: () => {
    const address = window.prompt(`The address of ${p.name} (an IP address or a name; a name is kept as you type it):`, now);
    if (address && address.trim()) change(box, printerPath(p, "address"), { address: address.trim() }, (r) => say(box, r.note ? `Saved. ${r.note}.` : "Saved.", true));
  } } });
}

function bambuRow(p) {
  const box = boxFor("printer:" + p.serial), code = secret("Access Code (printer: Settings > Network/LAN)");
  const mapBox = boxFor("map:" + p.serial);
  if (p.mapping) followMap(p, mapBox);      // a job already running (a reload, another browser): progress and Stop again
  return h("div", { class: "item" },
    h("p", {}, h("b", { textContent: p.name }), S.printers.klipper ? " Bambu" : "", `${dotted(p.model, p.ip || "no address yet", `serial ${p.serial}`)} `,
      pill(p.state === "connected", "connected", nice(p.state))),
    h("div", { class: "row" }, code,
      h("button", { textContent: p.configured ? "Replace code" : "Connect", on: { click: () => change(box, printerPath(p, "code"), { access_code: code.value }, null, [code]) } })),
    h("div", { class: "row" },
      testButton(p, box), renameButton(p, box), addressButton(p, box, p.ip || ""),
      p.configured ? h("button", { class: "secondary", textContent: "Map slots", on: { click: () => startMap(p, mapBox) } }) : null,
      p.configured ? h("button", { class: "secondary", textContent: "Map by loading filament", on: { click: () => manualMap(p, mapBox) } }) : null,
      p.pinned ? h("button", { class: "secondary", textContent: "Forget certificate", on: { click: () => { if (window.confirm(`Forget the certificate pinned for ${p.name}? The next connection trusts whatever answers at its address.`)) change(box, printerPath(p, "unpin"), {}); } } }) : null,
      forgetButton(p, box, "Its Access Code is deleted.")),
    box, mapBox);
}

// ----- slot mapping: the server's own connection does it, and this follows it -----
const mapping = {};
async function startMap(p, box) {
  if (!window.confirm(`Map the slots of ${p.name}? It changes their colours briefly and runs a job with no motion; the colours are put back.`)) return;
  const r = await change(box, printerPath(p, "map"), {}, () => box.replaceChildren(h("p", { class: "muted", textContent: "Starting…" })));
  if (r) { followMap(p, box); return; }
  try { if ((await api(printerPath(p, "map"))).state === "running") followMap(p, box); } catch (e) { /* the refusal is already in the box */ }
}

function followMap(p, box) {
  if (mapping[p.serial]) return;
  mapping[p.serial] = true;
  const stop = h("button", { class: "secondary", textContent: "Stop", on: { click: () => change(box, printerPath(p, "map/stop"), {}, () => {}) } });
  const tick = async () => {
    let v;
    try { v = await api(printerPath(p, "map")); } catch (e) {
      mapping[p.serial] = false;
      say(box, e.message, false);
      return;
    }
    const running = v.state === "running";
    fill(box,
      h("p", { class: "muted", textContent: running ? v.step || "Mapping…" : `Slot mapping: ${nice(v.state || "not run")}.` }),
      ...(v.problems || []).map((t) => h("p", { class: "err", textContent: t })),
      ...(v.notes || []).map((t) => h("p", { class: "muted", textContent: t })),
      v.report_why ? h("p", { class: "muted", textContent: v.report_why }) : null,
      !running && v.slots && v.slots.length ? h("p", { class: "muted", textContent: "Slots: " + v.slots.map((s) => s.label).join(", ") }) : null,
      running ? h("div", { class: "row" }, stop) : null,
      v.state === "failed" ? h("div", { class: "row" }, h("p", { textContent: "If mapping keeps failing, map it by loading each slot to the nozzle:" }),
        h("button", { class: "secondary", textContent: "Map by loading filament", on: { click: () => manualMap(p, box) } })) : null);
    if (running) setTimeout(tick, 1500); else mapping[p.serial] = false;
  };
  tick();
}

// ----- map by loading filament: the owner loads each slot, the printer says which one it sees -----
const manualOn = {};
async function manualMap(p, box) {
  const base = printerPath(p, "manual-map");
  let v;
  try { v = await api(base + "/start", { code: codeIn.value }); offerTrust(); } catch (e) { say(box, e.message, false); return; }
  if (manualOn[p.serial]) return;
  manualOn[p.serial] = true;
  const send = async (what, body) => {
    try { v = await api(`${base}/${what}`, { session: v.session, code: codeIn.value, ...body }); draw(); } catch (e) { say(note, e.message, false); }
  };
  const offer = async (share) => {      // its answer is a line, not the session: the card is redrawn from v
    try { const r = await api(`${base}/offer`, { session: v.session, code: codeIn.value, share }); v.offer_report = false; draw(); say(note, r.message, true); }
    catch (e) { say(note, e.message, false); }
  };
  const note = h("div");
  // a redraw rebuilds the selects: a choice the owner is making survives it while the same position is asked
  let shown, picks = {};
  const draw = () => {
    const st = v.step;
    const pos = st ? st.position.id : null;
    const prev = pos === shown ? Object.fromEntries(Object.entries(picks).map(([k, e]) => [k, e.value])) : {};
    shown = pos; picks = {};
    const keep = (k, el) => {
      if (!el) return el;
      picks[k] = el;
      if (prev[k] !== undefined && [...el.options].some((o) => o.value === prev[k])) el.value = prev[k];
      return el;
    };
    const positions = h("ul", {}, ...v.positions.map((q) => h("li", { textContent: `${q.label}: ${q.status === "confirmed" ? `confirmed (${q.reported_label}${q.nozzle ? ", " + q.nozzle + " nozzle" : ""})` : q.status === "by_hand" ? `entered by hand (${q.reported_label})` : q.status}` })));
    let ask = null;
    if (st && st.seen && st.ask) {
      const other = keep("other", h("select", { ariaLabel: "The position you loaded" }, ...v.positions.map((q) => h("option", { value: q.id, textContent: q.label, selected: q.id === st.position.id }))));
      const noz = keep("noz", v.dual_nozzle && !st.seen.nozzle_reported ? h("select", { ariaLabel: "Nozzle" }, h("option", { value: "right", textContent: "right nozzle" }), h("option", { value: "left", textContent: "left nozzle" })) : null);
      const nozzle = () => (st.seen.nozzle_reported ? st.seen.nozzle : noz ? noz.value : null);
      ask = h("div", {},
        h("p", { textContent: st.ask }),
        h("div", { class: "row" }, noz,
          h("button", { textContent: "Yes", on: { click: () => send("confirm", { position: st.position.id, reported: st.seen.reported, nozzle: nozzle() }) } }),
          h("label", {}, "No, I loaded ", other),
          h("button", { class: "secondary", textContent: "Save that", on: { click: () => send("confirm", { position: other.value, reported: st.seen.reported, nozzle: nozzle() }) } })));
    } else if (st && !v.reports_loads) {
      const pick = keep("pick", h("select", { ariaLabel: "The slot it is in" }, ...(v.choices || []).map((c, i) => h("option", { value: String(i), textContent: c.label }))));
      ask = h("div", { class: "row" }, pick, h("button", { textContent: "Save (not checked by the printer)", on: { click: () => send("confirm", { position: st.position.id, reported: v.choices[Number(pick.value)].reported, by_hand: true }) } }));
    } else if (st && st.seen && !st.seen.settled) {
      ask = h("p", { class: "muted", textContent: "The printer reports a change; waiting for it to settle…" });
    }
    fill(box,
      h("p", { textContent: st ? st.say : v.summary }),
      ask,
      st ? h("div", { class: "row" },
        h("button", { class: "secondary", textContent: `Skip ${st.position.label}`, on: { click: () => send("skip", { position: st.position.id }) } }),
        h("button", { class: "secondary", textContent: "Stop", on: { click: () => send("stop", {}) } })) : null,
      st ? h("p", { class: "muted", textContent: v.summary }) : null,
      positions,
      !v.open && v.offer_report ? h("div", { class: "row" },
        h("p", { textContent: "Share this map in a printer report, so other owners of this model benefit? Nothing is sent unless you choose to." }),
        h("button", { class: "secondary", textContent: "Yes, how do I share it?", on: { click: () => offer(true) } }),
        h("button", { class: "secondary", textContent: "No thanks", on: { click: () => offer(false) } })) : null,
      note);
  };
  const tick = async () => {
    if (!v.open) { manualOn[p.serial] = false; draw(); return; }
    const was = JSON.stringify(v);
    try { v = await api(base); } catch (e) { manualOn[p.serial] = false; say(box, e.message, false); return; }
    if (JSON.stringify(v) !== was) draw();     // unchanged: an open list or a choice being made stays as it is
    setTimeout(tick, 2000);
  };
  draw();
  setTimeout(tick, 2000);
}

function klipperRow(p) {
  const box = boxFor("printer:" + p.serial), key = secret("Moonraker API key (optional)");
  if (!p.configured) return h("div", { class: "item" },
    h("p", {}, h("b", { textContent: p.name }), ` · found at ${hostPort(p)}`),
    h("div", { class: "row" }, key,
      h("button", { textContent: "Use this printer", on: { click: () => change(box, printerPath(p, "connect"), { api_key: key.value }, null, [key]) } }),
      testButton(p, box), forgetButton(p, box, "A scan may find it again.")),
    box);
  const lane = h("select", { ariaLabel: "Publish slots to Moonraker's lane data", on: { change: () => change(box, printerPath(p, "lane_data"), { mode: lane.value }) } },
    ...["auto", "on", "off"].map((m) => h("option", { value: m, textContent: `Lane data: ${m}`, selected: m === p.lane_data })));
  return h("div", { class: "item" },
    h("p", {}, h("b", { textContent: p.name }), S.printers.bambu ? " Klipper" : "", `${dotted(p.model, hostPort(p))} `,
      pill(p.state === "connected", "connected", nice(p.state)), " ", pill(p.api_key, "API key set", "no API key")),
    h("div", { class: "row" }, key,
      h("button", { textContent: p.api_key ? "Replace key" : "Set key", on: { click: () => change(box, printerPath(p, "api_key"), { key: key.value }, null, [key]) } }),
      h("button", { class: "secondary", textContent: "Map by loading filament", on: { click: () => manualMap(p, box) } }),
      p.api_key ? h("button", { class: "secondary", textContent: "Clear key", on: { click: () => change(box, printerPath(p, "api_key"), { key: "" }) } }) : null, lane),
    h("div", { class: "row" },
      testButton(p, box),
      h("button", { class: "secondary", textContent: "Detect", on: { click: async () => {
        box.replaceChildren(h("p", { class: "muted", textContent: "Asking it…" }));
        try {
          const d = await api(printerPath(p, "detect"), {});
          box.replaceChildren(...[d.ok ? `${d.model || "A Klipper printer"}${d.verified ? "" : " (not verified)"}${d.slots && d.slots.length ? ": " + d.slots.join(", ") : ""}` : d.message,
            d.spoolman && d.spoolman.warning].filter(Boolean).map((t) => h("p", { class: d.ok ? "muted" : "err", textContent: t })));
        } catch (e) { say(box, e.message, false); }
      } } }),
      renameButton(p, box), addressButton(p, box, p.host), forgetButton(p, box, "Its Moonraker API key, if one is saved, is deleted.")),
    box);
}

// ----- adding a printer: the form follows the family, so a Klipper printer is never asked for an Access Code -----
let addFamily = null;       // every change redraws the tab: the form stays on the type you chose
const added = (r) => `Added ${r.serial}.${r.note ? ` ${r.note}.` : ""}`;   // the note: the server's unit doesn't reach that address
function addCard() {
  const P = S.printers, box = boxFor("printer-add");
  const family = h("select", { ariaLabel: "Printer type", on: { change: () => { addFamily = family.value; show(); } } },
    ...(P.bambu ? [h("option", { value: "bambu", textContent: "Bambu" })] : []),
    ...(P.klipper ? [h("option", { value: "klipper", textContent: "Klipper" })] : []));
  if (addFamily && P[addFamily]) family.value = addFamily;
  const fields = h("div");
  const name = h("input", { placeholder: "name (optional)" });
  function show() {
    const address = h("input", { placeholder: "IP address or name, e.g. 192.0.2.40 or printer.local" });
    if (family.value === "klipper") {
      const port = h("input", { placeholder: "port", value: "7125", inputMode: "numeric", size: 6 });
      const key = secret("Moonraker API key (optional)");
      fields.replaceChildren(h("div", { class: "row" }, address, port), h("div", { class: "row" }, name, key,
        h("button", { textContent: "Add", on: { click: () => change(box, "printers/klipper", { host: address.value, port: port.value, name: name.value, api_key: key.value },
          (r) => say(box, added(r), true), [key]) } })));
    } else {
      const ac = secret("Access Code (printer: Settings > Network/LAN)");
      const serial = h("input", { placeholder: "serial (optional: read from the printer)", autocapitalize: "characters" });
      fields.replaceChildren(h("div", { class: "row" }, address, ac), h("div", { class: "row" }, name, serial,
        h("button", { textContent: "Add", on: { click: () => change(box, "printers", { address: address.value, access_code: ac.value, name: name.value, serial: serial.value },
          (r) => say(box, added(r), true), [ac]) } })));
    }
  }
  show();
  return card("Add a printer", P.bambu && P.klipper ? h("label", {}, "Type ", family) : null, fields, box);
}

function scanCard() {
  const box = boxFor("printer-scan"), subnet = h("input", { placeholder: "subnet (optional: this server's own), e.g. 192.168.1.0/24" });
  return card("Find Klipper printers",
    h("p", { class: "muted", textContent: "Looks for Moonraker on your network and lists what answers above, for you to pick." }),
    h("div", { class: "row" }, subnet,
      h("button", { class: "secondary", textContent: "Scan", on: { click: () => change(box, "printers/scan", { subnet: subnet.value.trim() },
        (r) => say(box, r.found.length ? `Found on ${r.subnet}: ${r.found.map((f) => `${f.host}:${f.port}`).join(", ")}` : `No Moonraker found on ${r.subnet}.`, true)) } })),
    box);
}

function packCard() {
  const box = boxFor("printer-pack");
  return card("Printer pack",
    h("p", { class: "muted", textContent: "Installs the spool macros and the kit's Moonraker settings on a Klipper printer. Run these on the printer." }),
    h("div", { class: "row" }, h("button", { class: "secondary", textContent: "Show the commands", on: { click: async () => {
      box.replaceChildren(h("p", { class: "muted", textContent: "Checking the signed release…" }));
      try {
        const r = await api("printers/pack", {}), text = r.lines.join("\n");
        fill(box, h("pre", { class: "ok", textContent: text }),
          navigator.clipboard ? h("button", { class: "secondary", textContent: "Copy", on: { click: () => navigator.clipboard.writeText(text) } }) : null);
      } catch (e) { say(box, e.message, false); }
    } } })), box);
}

// The live printer view (slots, loading, camera, controls, usage) is the phone web app's Printers tab, which the same
// server serves at /intake to this browser too; it has that tab only with the printers module on.
function liveCard() {
  const url = location.pathname.replace(/\/setup\/?$/, "") + "/intake#printers";
  return card("Live printer view",
    h("p", { class: "muted", textContent: "Each printer's slots and the filament in them, loading and unloading spools, the camera, " +
      "pause, resume and stop, and the usage log with undo are in the phone web app's Printers tab. This browser opens it too, " +
      "on the home network." }),
    h("p", {}, h("a", { href: url, target: "_blank", rel: "noopener", textContent: "Open the live printer view" })));
}

function printersTab() {
  const P = S.printers;
  if (!P.on) return [card("Printers", h("p", { class: "muted", textContent: "The printers and klipper modules are off on this server (see Modules)." }))];
  const rows = P.list.map((p) => (p.family === "klipper" ? klipperRow(p) : bambuRow(p)));
  return [card("Printers",
    ...(rows.length ? rows : [h("p", { class: "muted", textContent: P.bambu ? "No printer yet. Printers on the network appear here once they announce themselves." : "No printer yet." })])),
    P.bambu ? liveCard() : null, addCard(), P.klipper ? scanCard() : null, P.klipper ? packCard() : null];
}
