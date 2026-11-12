// Spool intake phone app: add spools by hand or (with AI intake) from label photos, link a tapped NFC tag, refresh
// slicer presets.
// Talks only to <base>/api/* on the same origin (session cookie); no data from the server is put into
// innerHTML, everything goes through textContent / element properties.
"use strict";
const BASE = document.body.dataset.base;
const LOCATIONS = JSON.parse(document.body.dataset.locations);
const SEALED = document.body.dataset.sealed;      // the sealed-stock location
const AUTO = document.body.dataset.auto;          // what a blank location means (the placement rules)
const PICKS = JSON.parse(document.body.dataset.picks); // extra places offered when opening a spool
const AI = document.body.dataset.ai === "1";       // a label reader (ai_intake or local_intake) is on: photos can be read
// typical densities (g/cm3), filled in for a spool added by hand while its density is still blank
const DENSITY = { PLA: 1.24, PETG: 1.27, ABS: 1.04, ASA: 1.07, TPU: 1.21, PA: 1.14, PC: 1.2, PCTG: 1.23, PVA: 1.23, HIPS: 1.04 };
// a material with no entry of its own ("PLA+", "PLA Silk", "PETG-CF") takes the longest known one it starts with
function densityFor(material) {
  const m = String(material ?? "").trim().toUpperCase();
  if (!m) return undefined;
  if (m in DENSITY) return DENSITY[m];
  const key = Object.keys(DENSITY).filter((k) => m.startsWith(k)).sort((x, y) => y.length - x.length)[0];
  return key ? DENSITY[key] : undefined;
}
const MAX_EDGE = 1568, QUALITY = 0.85; // Claude reads labels well at this size; keeps uploads ~300 KB per photo
const app = document.getElementById("app");

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined) continue;
    if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
    else if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k in el && k !== "list" && k !== "style") el[k] = v;
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}

async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body ? "POST" : "GET"), credentials: "same-origin", headers: {} };
  if (opts.body instanceof FormData) init.body = opts.body;
  else if (opts.body) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  const r = await fetch(BASE + "/api/" + path, init);
  let data;
  try { data = await r.json(); } catch { data = { error: `HTTP ${r.status}` }; }
  if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

const out = (res) => {
  const text = typeof res === "string" ? res : (res.output ?? JSON.stringify(res, null, 1));
  return h("pre", { class: res && res.exit_code ? "err" : "ok", textContent: text });
};
const fail = (e) => h("pre", { class: "err", textContent: e.message || String(e) });
const busy = (text) => h("p", {}, h("span", { class: "spin" }), text);
async function run(box, label, fn) {
  box.replaceChildren(busy(label));
  try { const node = await fn(); box.replaceChildren(...[node].flat().filter(Boolean)); }
  catch (e) { box.replaceChildren(fail(e)); }
}

// ---------- History: the intake history (the newest spool additions, their photos, revise, edit, undo) ----------
const HIST_FIELDS = [["vendor", "Brand"], ["name", "Name"], ["material", "Material"], ["color_hex", "Colour (hex)"],
  ["net", "Net g"], ["tare", "Spool g"], ["density", "Density"], ["nozzle", "Nozzle °C"], ["bed", "Bed °C"],
  ["nozzle_range", "Nozzle range"], ["bed_range", "Bed range"], ["price_per_kg", "Price per kg"], ["line", "Line"]];
const HIST_NUM = new Set(["net", "tare", "density", "nozzle", "bed", "price_per_kg"]);
const HIST_STATE = { detected: "as detected", revised_ai: "revised by AI", edited: "edited by hand" };
function historyTab() {
  const box = h("div");
  const el = h("section", { class: "hidden" }, h("h1", { textContent: "Intake history" }), box);
  const hp = (id, what) => `history/${encodeURIComponent(id)}${what ? "/" + what : ""}`;
  function photoImg(id, n) {
    const img = h("img", { src: `${BASE}/api/${hp(id, "photos/" + n)}`, alt: `Photo ${n}`, loading: "lazy", class: "thumb" });
    img.addEventListener("click", () => img.classList.toggle("big"));     // tap to enlarge
    return img;
  }
  async function load() {
    await run(box, "Loading…", async () => {
      const d = await api("history");
      return [h("p", { class: "muted", textContent: `The newest ${d.keep} additions, with their photos. The number is in the setup page's Settings.` }),
        ...(d.records.length ? d.records.map((r) => row(r, d.ai)) : [h("p", { textContent: "Nothing added since the history started." })])];
    });
  }
  function row(r, ai) {
    const det = h("div");
    det.mark = h("span", { textContent: HIST_STATE[r.state] || r.state });   // the state mark, redrawn after a change
    const names = [...new Set(r.spools.map((s) => `${s.vendor} ${s.name}`))].join(", ");
    return h("div", { class: "card" },
      h("div", { class: "row" }, ...(r.photos ? [photoImg(r.id, 1)] : []),
        h("p", {}, h("b", { textContent: names }), ` · ${(r.at || "").slice(0, 16).replace("T", " ")} · `, det.mark)),
      h("button", { class: "secondary", textContent: "Open", on: { click: () => detail(r.id, ai, det) } }), det);
  }
  async function detail(id, ai, det) {
    await run(det, "Loading…", async () => {
      const rec = await api(hp(id));
      const msg = h("div");
      const parts = [];
      if (rec.photos > 1) parts.push(h("div", { class: "row" }, ...Array.from({ length: rec.photos - 1 }, (_, i) => photoImg(id, i + 2))));
      for (const s of rec.saved) {
        const ins = {};
        const fields = HIST_FIELDS.map(([k, label]) => {
          ins[k] = h("input", { value: s.values[k] ?? "", "aria-label": label });
          return h("label", {}, label, ins[k]);
        });
        const note = h("textarea", { rows: 2, placeholder: "e.g. brand is Polymaker", disabled: !ai });
        parts.push(h("div", { class: "card" },
          h("p", { class: "muted", textContent: `Spool ${s.spool_ids.join(", ")}${s.spool_ids.length > 1 ? ": a change applies to all of them" : ""}` }),
          ...fields,
          h("button", { textContent: "Save changes", on: { click: () => save(id, ai, det, msg, s, ins) } }),
          note, h("button", { class: "secondary", textContent: "Ask the AI to correct it", disabled: !ai,
                              on: { click: () => revise(id, ai, det, msg, s, note) } }),
          ai ? null : h("p", { class: "muted", textContent: "Label reading is off on this server: edit by hand." })));
      }
      const live = rec.revisions.filter((v) => !v.undone);
      const last = live[live.length - 1];
      for (const v of rec.revisions) parts.push(h("p", { class: "muted", textContent: `Revision ${v.n} by ${v.by === "ai" ? "the AI" : "hand"}${v.undone ? " (undone)" : ""}: ${[...new Set(v.changes.map((c) => `${c.field} ${c.old} → ${c.new}`))].join("; ")}${v.note ? " · " + v.note : ""}` }));
      if (last) parts.push(h("button", { class: "secondary", textContent: `Undo revision ${last.n}`, on: { click: () => act(id, ai, det, msg, "undo", { revision: last.n }) } }));
      parts.push(msg);
      return parts;
    });
  }
  async function act(id, ai, det, msg, what, body) {
    await run(msg, "Saving…", async () => {
      const r = await api(hp(id, what), { body });
      if (det.mark) det.mark.textContent = HIST_STATE[r.state] || r.state;
      const v = r.revisions[r.revisions.length - 1] || {}, fl = v.filaments || {};
      await detail(id, ai, det);
      det.append(h("pre", { class: "ok", textContent: what === "undo" ? "Undone." : "Saved."
        + (fl.to !== fl.from ? ` The spools now use filament ${fl.to}${fl.created ? " (new)" : ""}.` : "")
        + (fl.orphaned && fl.orphaned.length ? ` Filament ${fl.orphaned.join(", ")} has no spools left; it was not deleted.` : "") }));
      return [];
    });
  }
  function save(id, ai, det, msg, s, ins) {
    const values = {};
    for (const [k] of HIST_FIELDS) {
      const was = s.values[k] == null ? "" : String(s.values[k]), now = ins[k].value.trim();
      if (now !== was) values[k] = now === "" ? null : (HIST_NUM.has(k) ? Number(now) : now);
    }
    if (!Object.keys(values).length) { msg.replaceChildren(h("p", { class: "muted", textContent: "Nothing changed." })); return; }
    act(id, ai, det, msg, "apply", { item: s.item, values });
  }
  async function revise(id, ai, det, msg, s, note) {
    await run(msg, "Asking the AI… (up to a minute)", async () => {
      const p = await api(hp(id, "revise"), { body: { item: s.item, note: note.value } });
      if (!p.changes.length) return [h("p", { textContent: "The AI changed nothing." })];
      return [h("p", { textContent: "The AI suggests:" }),
        ...p.changes.map((k) => h("p", { textContent: `${k}: ${p.before[k]} → ${p.after[k]}` })),
        p.no_photo ? h("p", { class: "muted", textContent: "No photo was kept: it worked from the saved values and your note." }) : null,
        h("div", { class: "row" },
          h("button", { textContent: "Accept", on: { click: () => act(id, ai, det, msg, "apply", { proposal: p.proposal }) } }),
          h("button", { class: "secondary", textContent: "Discard", on: { click: () => msg.replaceChildren() } }))];
    });
  }
  return { el, enter: load };
}

// ---------- tabs ----------
const PRINTERS = document.body.dataset.printers === "1";   // the printers module is on (printers.js is loaded)
const HISTORY = document.body.dataset.history === "1";     // the kit's own page: the intake history is here
const tabs = { add: addTab(), open: openTab(), presets: presetsTab(), ...(HISTORY ? { history: historyTab() } : {}),
               ...(PRINTERS ? { printers: printersTab() } : {}) };
const bar = h("nav", { class: "tabs" });
for (const [key, label] of [["add", "Add spools"], ["open", "Open spool"], ["presets", "Presets"],
    ...(HISTORY ? [["history", "History"]] : []), ...(PRINTERS ? [["printers", "Printers"]] : [])]) {
  bar.append(h("button", { textContent: label, dataset: { key }, on: { click: () => show(key) } }));
}
app.append(bar, ...Object.values(tabs).map((t) => t.el));
function show(key) {
  for (const b of bar.children) b.classList.toggle("on", b.dataset.key === key);
  for (const [k, t] of Object.entries(tabs)) { t.el.classList.toggle("hidden", k !== key); (k === key ? t.enter : t.leave)?.(); }
  try { localStorage.setItem("tab", key); } catch {}
}
let first = "add";
try { first = localStorage.getItem("tab") || "add"; } catch {}
if (Object.hasOwn(tabs, location.hash.slice(1))) first = location.hash.slice(1);   // a link to a tab, e.g. the setup page's #printers
show(tabs[first] ? first : "add");

// ---------- Add spools ----------
function addTab() {
  let readId = null;
  const photos = []; // {blob, url}
  let items = [], checked = false, tag = null; // tag: unlinked tag tapped just before the photos (server links it)
  const thumbs = h("div", { class: "thumbs" });
  const hint = h("textarea", { placeholder: "Optional note for Claude, e.g. \"3 of the grey ones\" or \"all the PETG is white\"" });
  const picker = h("input", { type: "file", accept: "image/*", multiple: true, on: { change: addFiles } });
  const readBtn = h("button", { textContent: "Read labels", disabled: true, on: { click: read } });
  const readBox = h("div");
  const itemsBox = h("div");
  const actBox = h("div");
  // ---- by hand: pick an existing filament, or start a new one ----
  const fq = h("input", { type: "search", placeholder: "Existing filament: brand, colour, material", enterKeyHint: "search",
                          on: { keydown: (e) => { if (e.key === "Enter") findFilaments(); } } });
  const filBox = h("div", { class: "list" });
  const vendorList = h("datalist", { id: "vendors" });
  let vendorTare = new Map(); // vendor name (lower case) -> empty spool weight
  const byHand = h("div", { class: "card" },
    h("h3", { textContent: "Add by hand" }),
    h("p", { class: "muted", textContent: "Pick a filament you already have, or start a new one; fill in the spool and check before saving." }),
    h("div", { class: "row" }, fq, h("button", { class: "fit", textContent: "Search", on: { click: findFilaments } })),
    filBox,
    h("p", {}, h("button", { class: "secondary", textContent: "New filament (type it in)", on: { click: () => addItem(blankItem()) } })),
    vendorList);
  const photoPart = AI ? [
    h("h2", { textContent: "From label photos" }),
    h("p", { class: "muted", textContent: "Photograph each label (several photos of one spool are fine). Claude reads them; you check and edit before anything is saved." }),
    h("label", { class: "filebtn", style: "display:flex" }, h("button", { textContent: "Take or choose photos", tabIndex: -1 }), picker),
    thumbs, hint, h("p", {}, readBtn), readBox] : [];
  const el = h("section", {},
    h("h1", { textContent: "Add spools" }), byHand, ...photoPart, itemsBox, actBox);
  api("vendors").then((res) => {
    vendorTare = new Map(res.vendors.map((v) => [v.name.toLowerCase(), v.tare]));
    vendorList.replaceChildren(...res.vendors.map((v) => h("option", { value: v.name })));
  }).catch(() => {}); // no list: the vendor is typed in

  function blankItem() {
    return { vendor: "", name: "", material: "", count: 1, net: 1000, tare: null, density: null, color_hex: "",
             sealed: true, location: SEALED, price_per_kg: "", photos: [], estimates: [], match: "new filament", hand: true };
  }
  function addItem(it) {
    items.push(it); drawItems(); dirty();
    itemsBox.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  async function findFilaments() {
    await run(filBox, "Searching…", async () => {
      const res = await api(`filaments?q=${encodeURIComponent(fq.value)}`);
      if (!res.filaments.length) return h("p", { class: "muted", textContent: "No filament matches: use New filament." });
      return res.filaments.slice(0, 60).map((f) => h("button", {
        class: "pick", on: { click: () => addItem({ ...blankItem(), vendor: f.vendor, name: f.name, material: f.material || "",
          net: f.net ?? 1000, tare: f.tare, density: f.density, color_hex: f.color_hex || "", nozzle: f.nozzle, bed: f.bed,
          existing_filament_id: f.id, match: "existing filament" }) } },
        h("strong", { textContent: `F${f.id} ` }), `${f.vendor || "(no vendor)"} ${f.name}`,
        h("div", { class: "muted", textContent: `${f.material || "?"} · ${f.net ?? "?"} g · ${f.spools} spool${f.spools === 1 ? "" : "s"}` })));
    });
  }

  async function shrink(file) {
    const url = URL.createObjectURL(file);
    try {
      const img = new Image(); img.src = url; await img.decode();
      const s = Math.min(1, MAX_EDGE / Math.max(img.naturalWidth, img.naturalHeight));
      const c = document.createElement("canvas");
      c.width = Math.round(img.naturalWidth * s); c.height = Math.round(img.naturalHeight * s);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      return await new Promise((ok) => c.toBlob(ok, "image/jpeg", QUALITY));
    } finally { URL.revokeObjectURL(url); }
  }
  async function addFiles() {
    const files = [...picker.files]; picker.value = "";
    for (const f of files) {
      if (photos.length >= 8) { readBox.replaceChildren(fail(new Error("8 photos at a time"))); break; }
      try { const blob = await shrink(f); photos.push({ blob, url: URL.createObjectURL(blob) }); }
      catch (e) { readBox.replaceChildren(fail(new Error(`${f.name}: can't read this image`))); }
    }
    drawThumbs();
  }
  function drawThumbs() {
    thumbs.replaceChildren(...photos.map((p, i) => h("figure", {}, h("img", { src: p.url, alt: `photo ${i}` }),
      h("figcaption", { textContent: i }),
      h("button", { textContent: "✕", "aria-label": "remove photo", on: { click: () => { URL.revokeObjectURL(p.url); photos.splice(i, 1); drawThumbs(); } } }))));
    readBtn.disabled = !photos.length;
  }
  async function read() {
    const fd = new FormData();
    photos.forEach((p, i) => fd.append("photos", p.blob, `photo${i}.jpg`));
    fd.append("hint", hint.value);
    readBtn.disabled = true; actBox.replaceChildren();
    await run(readBox, `Claude is reading ${photos.length} photo${photos.length > 1 ? "s" : ""}… (up to a minute)`, async () => {
      const res = await api("read", { body: fd });
      tag = res.tag;
      readId = res.read_id || null;                      // the intake history keeps this read's photos with the save
      const got = res.items.map((it) => ({ price_per_kg: "", ...it, location: it.sealed ? SEALED : "" }));
      items = [...items.filter((it) => it.hand), ...got]; // a new read replaces the last read, not spools added by hand
      checked = false; drawItems();
      const filled = got.length === 1 && got[0].gross != null;
      return [res.tag ? h("p", { class: "muted", textContent: `New tag ${res.tag.nfc_id} was tapped on the ${res.tag.reader} reader ${res.tag.age_seconds} s before the photos, so this spool counts as opened; Add links the tag to it (one opened spool only).` }) : null,
        res.scale ? h("p", { class: "muted", textContent: `Station scale: ${res.scale.grams} g, ${res.scale.age_seconds} s ago${filled ? " (filled in as the scale weight)" : " (not used: only for one opened spool)"}.` }) : null,
        res.questions.length ? h("div", { class: "card" }, h("h3", { textContent: "Claude asks" }),
        ...res.questions.map((q) => h("p", { textContent: "• " + q }))) : null,
        h("p", { class: "muted", textContent: `${got.length} product${got.length === 1 ? "" : "s"} found · ${res.usage.model}, ${res.usage.input_tokens} in (${res.usage.cached} cached) / ${res.usage.output_tokens} out tokens` })];
    });
    readBtn.disabled = !photos.length;
  }
  function field(it, key, label, type = "text", extra = {}, ins = {}) {
    const inp = h("input", {
      type, value: it[key] ?? "", inputMode: type === "number" ? "decimal" : undefined, step: "any",
      list: key === "vendor" ? "vendors" : undefined,
      on: { input: (e) => { it[key] = type === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value;
                            if (key === "color_hex") swatchFor(it);
                            if (key === "material") fillBlank(it, "density", densityFor(it.material), ins);
                            if (key === "vendor") fillBlank(it, "tare", vendorTare.get(it.vendor.trim().toLowerCase()), ins);
                            dirty(); } } });
    ins[key] = inp;
    return h("label", extra, label, inp);
  }
  function fillBlank(it, key, value, ins) { // a known default for a field the user left blank
    if (value == null || (it[key] != null && it[key] !== "")) return;
    it[key] = value; if (ins[key]) ins[key].value = value;
  }
  const swatches = new Map();
  function swatchFor(it) { const s = swatches.get(it); if (s) s.style.background = /^[0-9a-f]{6}$/i.test(it.color_hex || "") ? "#" + it.color_hex : "transparent"; }
  function drawItems() {
    swatches.clear();
    itemsBox.replaceChildren(...items.map((it, idx) => {
      const ins = {}; // this card's inputs by field, for filled-in defaults
      const f = (key, label, type, extra) => field(it, key, label, type, extra, ins);
      const sw = h("span", { class: "swatch" }); swatches.set(it, sw); swatchFor(it);
      const loc = h("select", { on: { change: (e) => { it.location = e.target.value; dirty(); } } },
        h("option", { value: "", textContent: "Auto: " + AUTO, selected: !it.location }),
        ...LOCATIONS.map((l) => h("option", { value: l, textContent: l, selected: l === it.location })));
      const sealed = h("input", { type: "checkbox", checked: it.sealed, on: { change: (e) => {
        it.sealed = e.target.checked;
        if (it.location === (it.sealed ? "" : SEALED)) { it.location = it.sealed ? SEALED : ""; loc.value = it.location; }
        dirty(); } } });
      return h("div", { class: "card" },
        h("h3", {}, sw, h("span", { textContent: `${it.vendor} ${it.name}`.trim() || "New spool" }),
          h("span", { class: "badge " + (it.existing_filament_id ? "ok" : "new"), textContent: it.match })),
        it.photos.length ? h("p", { class: "muted", textContent: `photos ${it.photos.join(", ")}${it.estimates.length ? " · estimated: " + it.estimates.join(", ") : ""}` }) : null,
        h("p", { class: "muted", textContent: it.price_line ? it.price_line.replace(/^Price: /, "") : "no price" }),
        h("div", { class: "grid" },
          f("vendor", "Vendor"), f("material", "Material"),
          f("name", "Name (with the colour)", "text", { class: "wide" }),
          f("count", "Spools", "number"), f("net", "Net g", "number"),
          f("tare", "Empty spool g", "number"), f("density", "Density", "number"),
          f("color_hex", "Colour hex"), f("lot", "Lot"),
          f("nozzle", "Nozzle °C", "number"), f("bed", "Bed °C", "number"),
          f("gross", "Opened: scale weight g (with spool, blank = full)", "number", { class: "wide" }),
          h("label", { class: "check wide" }, sealed, "Still sealed (in its bag or box)",
            it.sealed_reason ? h("span", { class: "muted", textContent: ` · ${it.sealed_reason}` }) : null),
          f("price_per_kg", "Price $/kg", "number"), h("label", {}, "Location", loc),
          f("note", "Note", "text", { class: "wide" })),
        h("p", {}, h("button", { class: "secondary", textContent: "Remove", on: { click: () => { items.splice(idx, 1); drawItems(); dirty(); } } })));
    }));
    drawActions();
  }
  function dirty() { if (checked) { checked = false; drawActions(); } }
  const total = () => items.reduce((n, it) => n + (Number(it.count) || 0), 0);
  function drawActions(result) {
    if (!items.length) { actBox.replaceChildren(); return; }
    const check = h("button", { class: checked ? "secondary" : "", textContent: "Check (dry run)", on: { click: () => submit(true) } });
    const add = h("button", { textContent: `Add ${total()} spool${total() === 1 ? "" : "s"}`, disabled: !checked, on: { click: () => submit(false) } });
    actBox.replaceChildren(h("div", { class: "row" }, check, add), result || h("p", { class: "muted", textContent: "Check first; any edit needs a new check." }));
  }
  async function submit(dry) {
    const box = h("div"); actBox.replaceChildren(box);
    await run(box, dry ? "Checking…" : "Adding to Spoolman…", async () => {
      const res = await api("add", { body: { items, dry_run: dry, link_tag: tag ? tag.nfc_id : null, read_id: readId } });
      checked = dry && !res.exit_code;
      if (!dry && !res.exit_code) {
        items = []; tag = null; readId = null; itemsBox.replaceChildren(); filBox.replaceChildren(); photos.splice(0).forEach((p) => URL.revokeObjectURL(p.url)); drawThumbs();
        return [out(res), h("p", {}, h("button", { textContent: "Next: presets for new filaments", on: { click: () => show("presets") } }))];
      }
      drawActions(out(res));
      return null;
    });
  }
  return { el };
}

// ---------- Open spool ----------
function openTab() {
  let timer = null, picked = null, lastKey = null;
  const tagBox = h("div", { class: "card" }, busy("Reading the tag reader…"));
  const q = h("input", { type: "search", placeholder: "Search: brand, colour, material", enterKeyHint: "search",
                         on: { keydown: (e) => { if (e.key === "Enter") find(); } } });
  const sealed = h("input", { type: "checkbox", checked: true });
  const results = h("div", { class: "list" });
  const gross = h("input", { type: "number", inputMode: "decimal", step: "any", placeholder: "scale reading, g (optional)" });
  const loc = h("input", { placeholder: "blank = " + AUTO, list: "locs" });
  const hum = h("input", { type: "number", inputMode: "decimal", step: "any", placeholder: "box hygrometer % (optional)" });
  const actBox = h("div");
  const linkBtn = h("button", { textContent: "Link tag and open", disabled: true, on: { click: () => submit(false) } });
  const form = h("div", { class: "card hidden" }, h("h3", { textContent: "Selected spool" }), h("p", { class: "picked" }),
    h("div", { class: "grid" }, h("label", { class: "wide" }, "Gross weight (with spool)", gross),
      h("label", { class: "wide" }, "Location", loc), h("label", { class: "wide" }, "Humidity", hum)),
    h("div", { class: "row", style: "margin-top:.6rem" }, h("button", { class: "secondary", textContent: "Check", on: { click: () => submit(true) } }), linkBtn),
    actBox);
  for (const inp of [gross, loc, hum]) inp.addEventListener("input", () => { linkBtn.disabled = true; });
  const el = h("section", { class: "hidden" },
    h("h1", { textContent: "Open a spool" }),
    h("p", { class: "muted", textContent: "Tap the spool's tag on a reader, pick the spool, weigh it (the station scale fills it in), link." }),
    tagBox, h("datalist", { id: "locs" }, ...[...new Set([...PICKS, ...LOCATIONS])].map((l) => h("option", { value: l }))),
    h("h2", { textContent: "Which spool?" }), h("div", { class: "row" }, q, h("button", { class: "fit", textContent: "Search", on: { click: find } })),
    h("label", { class: "check" }, sealed, "sealed spools only"),
    results, form);

  async function poll() {
    try {
      const t = await api("tag");
      const key = `${t.nfc_id}|${t.read_at}`;
      if (key !== lastKey) {
        lastKey = key; linkBtn.disabled = true;
        if (t.reader === "station" && t.scale) gross.value = t.scale.grams; // a new station tap: that spool is on the scale
        tagBox.replaceChildren(h("h3", { textContent: t.nfc_id ? "Last tag: " + t.nfc_id : "No tag read yet: tap one" }),
          h("pre", { textContent: t.text }));
      }
      tagBox.querySelector(".age")?.remove();
      if (t.age_seconds != null) tagBox.append(h("p", { class: "muted age", textContent: `tapped ${ago(t.age_seconds)} on the ${t.reader} reader${t.scale ? ` · station scale ${t.scale.grams} g` : ""}` }));
    } catch (e) { tagBox.replaceChildren(fail(e)); }
  }
  const ago = (s) => s < 60 ? `${s} s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`;
  async function find() {
    await run(results, "Searching…", async () => {
      const res = await api(`find?q=${encodeURIComponent(q.value)}&sealed=${sealed.checked ? 1 : 0}`);
      const rows = res.filaments.flatMap((f) => f.spools.map((s) => ({ f, s })));
      if (!rows.length) return h("p", { class: "muted", textContent: "No spools match." });
      return rows.slice(0, 60).map(({ f, s }) => h("button", {
        class: "pick", on: { click: (e) => pick(e.currentTarget, f, s) } },
        h("strong", { textContent: `S${s.spool_id} ` }), `${f.vendor} ${f.name}`,
        h("div", { class: "muted", textContent: `${s.location || "?"} · ${s.remaining_g} g${s.sealed ? " · sealed" : ""}${s.tagged ? " · has a tag" : ""}${s.lot ? " · lot " + s.lot : ""}` })));
    });
  }
  function pick(btn, f, s) {
    for (const b of results.querySelectorAll(".pick")) b.classList.toggle("on", b === btn);
    picked = s.spool_id; linkBtn.disabled = true; actBox.replaceChildren();
    form.querySelector(".picked").textContent = `S${s.spool_id} ${f.vendor} ${f.name} (${s.location}, ${s.remaining_g} g)`;
    form.classList.remove("hidden"); form.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  async function submit(dry) {
    if (picked == null) return;
    await run(actBox, dry ? "Checking…" : "Linking…", async () => {
      const res = await api("open", { body: { spool: picked, gross: gross.value, location: loc.value, humidity: hum.value, dry_run: dry } });
      linkBtn.disabled = !(dry && !res.exit_code);
      if (!dry && !res.exit_code) { picked = null; gross.value = hum.value = loc.value = ""; lastKey = null; }
      return out(res);
    });
  }
  return { el, enter() { poll(); timer = setInterval(poll, 3000); }, leave() { clearInterval(timer); timer = null; } };
}

// ---------- Presets ----------
function presetsTab() {
  const box = h("div");
  const genBox = h("div");
  const el = h("section", { class: "hidden" },
    h("h1", { textContent: "Slicer presets" }),
    h("p", { class: "muted", textContent: "New filaments need a preset line before a build covers them. The desktop installs a build by itself the next time the slicers are closed." }),
    box, h("p", {}, h("button", { textContent: "Build presets now", on: { click: build } })), genBox);

  async function load() {
    await run(box, "Loading…", async () => {
      const st = await api("presets");
      const info = h("p", { class: "muted", textContent: `Last build ${st.last_build || "-"} · installed ${st.installed_build || "-"}${st.waiting_for_desktop ? " · waiting for the desktop" : ""} · ${st.lines} lines` });
      if (!st.uncovered_filaments.length) return [info, h("p", { textContent: "Every filament has a preset line." })];
      return [info, h("h2", { textContent: "Filaments without a preset line" }), ...st.uncovered_filaments.map(lineCard)];
    });
  }
  function lineCard(f) {
    const res = h("div");
    const card = h("div", { class: "card" }, h("h3", { textContent: `F${f.id} ${f.vendor} ${f.name}` }),
      h("p", { class: "muted", textContent: f.material || "" }));
    if (f.lines_for_vendor.length) {
      const sel = h("select", {}, ...f.lines_for_vendor.map((l) => h("option", { value: l, textContent: l })));
      card.append(h("label", {}, "Add to the line", sel), h("p", {}, h("button", { textContent: "Add to line", on: { click: () =>
        run(res, "Adding…", async () => { await api("line_add", { body: { line: sel.value, ids: [f.id] } }); load(); return null; }) } })));
    }
    const nm = h("input", { value: `${f.vendor} ${f.name.split(" ").slice(0, -1).join(" ") || f.name}` });
    const orca = h("select"), bs = h("select");
    const q = h("input", { value: f.material || "", placeholder: "search parents, e.g. PETG-CF" });
    async function parents() {
      try {
        const p = await api(`parents?q=${encodeURIComponent(q.value)}`);
        const fill = (sel, list, want) => sel.replaceChildren(...list.map((n) => h("option", { value: n, textContent: n, selected: n === want })));
        fill(orca, p.orca_parents, `Generic ${f.material}`); fill(bs, p.bs_templates, `Generic ${f.material}`);
      } catch (e) { res.replaceChildren(fail(e)); }
    }
    const details = h("details", {}, h("summary", { textContent: f.lines_for_vendor.length ? "…or a new line" : "New line (new brand or product line)" }),
      h("div", { class: "grid" }, h("label", { class: "wide" }, "Line name '<Brand> <Line>'", nm),
        h("label", { class: "wide" }, "Search parents", q), h("label", { class: "wide" }, "Orca parent", orca),
        h("label", { class: "wide" }, "Bambu Studio template", bs)),
      h("p", {}, h("button", { textContent: "Create line", on: { click: () =>
        run(res, "Creating…", async () => { await api("line_new", { body: { name: nm.value, vendor: f.vendor, ids: [f.id], orca_parent: orca.value, bs_template: bs.value } }); load(); return null; }) } })));
    q.addEventListener("change", parents);
    details.addEventListener("toggle", () => { if (details.open && !orca.options.length) parents(); });
    card.append(details, res);
    return card;
  }
  async function build() {
    await run(genBox, "Building presets… (a minute or two)", async () => { const r = await api("generate", { body: {} }); load(); return out(r); });
  }
  return { el, enter: load };
}
