// The console's Intake tab: the intake history (the newest spool additions with their photos), revise with the AI, edit
// by hand, undo. Loaded after setup.js; everything from the server goes in through textContent, as there.
"use strict";

const INTAKE_FIELDS = [["vendor", "Brand"], ["name", "Name"], ["material", "Material"], ["color_hex", "Colour (hex)"],
  ["net", "Net g"], ["tare", "Spool g"], ["density", "Density"], ["nozzle", "Nozzle °C"], ["bed", "Bed °C"],
  ["nozzle_range", "Nozzle range"], ["bed_range", "Bed range"], ["price_per_kg", "Price per kg"], ["line", "Line"]];
const INTAKE_NUM = new Set(["net", "tare", "density", "nozzle", "bed", "price_per_kg"]);
const INTAKE_STATE = { detected: "as detected", revised_ai: "revised by AI", edited: "edited by hand" };
const intakeSize = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.ceil(n / 1024)} KB`;
const histPath = (id, what) => `intake/history/${encodeURIComponent(id)}${what ? "/" + what : ""}`;

// A change on this tab: the setup code as every write, but no page re-render (change() reloads every tab, which would
// close the record being edited); the record redraws itself from the answer.
function intakePost(box, path, body, done) {
  return coded(box, async () => {
    working(box, path.endsWith("/revise") ? "Asking the AI… (up to a minute)" : SW.t("common_saving"));
    try { done(await api(path, { ...body, code: theCode() })); } catch (e) { if (e.locked) fill(box); throw e; }
  });
}

function intakeTab() {
  const body = h("div"), box = boxFor("intake");
  const el = card("Intake history", body, box);
  later(readRegion(body, "recent", () => api("intake/history"), (d) => fill(body,
    h("p", { class: "muted", textContent: `The newest ${d.keep} spool additions are kept with the photos that were taken (${intakeSize(d.photo_bytes)} of photos now). Change the number in Settings, General.` }),
    d.ai ? null : h("p", { class: "muted", textContent: "Label reading (ai_intake or local_intake) is off on this server: revisions are by hand." }),
    ...(d.records.length ? d.records.map((r) => intakeRow(r, d.ai)) : [SW.empty({ icon: "recent", title: SW.t("recent_empty_title"), text: SW.t("recent_empty_text"), level: 3 })]))));
  return [el];
}

function intakePhoto(id, n) {
  const img = h("img", { src: "/setup/api/" + histPath(id, `photos/${n}`), alt: `Photo ${n}`, loading: "lazy" });
  img.style.maxWidth = "8rem";
  img.style.cursor = "zoom-in";
  img.addEventListener("click", () => {                 // tap to enlarge, tap again to shrink
    const big = img.style.maxWidth !== "100%";
    img.style.maxWidth = big ? "100%" : "8rem";
    img.style.cursor = big ? "zoom-out" : "zoom-in";
  });
  return img;
}

function intakeRow(r, ai) {
  const detail = h("div"), when = (r.at || "").slice(0, 16).replace("T", " ");
  detail.mark = h("span", { textContent: INTAKE_STATE[r.state] || r.state });     // redrawn after a change
  const names = [...new Set(r.spools.map((s) => `${s.vendor} ${s.name}`))].join(", ");
  const open = h("button", { class: "secondary", textContent: "Open", on: { click: () => intakeDetail(r.id, ai, detail) } });
  return h("div", { class: "item", "data-key": r.id },
    h("div", { class: "row" }, ...(r.photos ? [intakePhoto(r.id, 1)] : []),
      h("p", {}, h("b", { textContent: names || "no spools" }),
        ` · ${when} · ${r.source} · `, detail.mark, ` · spool ${r.spools.map((s) => s.spool_id).join(", ")}`),
      open),
    detail);
}

async function intakeDetail(id, ai, detail) {
  let rec;
  try { rec = await api(histPath(id)); } catch (e) { say(detail, e.message, false); return; }
  const note = boxFor("record:" + id);     // the record's result slot (Undo): kept when the record is drawn again
  const photos = Array.from({ length: rec.photos }, (_, i) => intakePhoto(id, i + 1));
  const items = rec.saved.map((s) => {
    const inputs = {}, at = boxFor("record:" + id + ":" + s.item);     // the item's own slot, under its controls
    const fields = INTAKE_FIELDS.map(([k, label]) => {
      const v = s.values[k];
      inputs[k] = h("input", { value: v == null ? "" : String(v), ariaLabel: label });
      return h("label", {}, `${label}: `, inputs[k]);
    });
    const save = h("button", { textContent: "Save changes", on: { click: () => {
      const values = {};
      for (const [k] of INTAKE_FIELDS) {
        const was = s.values[k] == null ? "" : String(s.values[k]), now = inputs[k].value.trim();
        if (now !== was) values[k] = now === "" ? null : (INTAKE_NUM.has(k) ? Number(now) : now);
      }
      if (!Object.keys(values).length) { say(at, "Nothing changed.", "neutral"); return; }
      intakePost(at, histPath(id, "apply"), { item: s.item, values }, (r) => intakeDone(r, id, ai, detail, null, at));
    } } });
    const ask = h("textarea", { rows: 2, placeholder: "e.g. brand is Polymaker", ariaLabel: "What is wrong", disabled: !ai });
    const revise = h("button", { class: "secondary", textContent: "Ask the AI to correct it", disabled: !ai, on: { click: () =>
      intakePost(at, histPath(id, "revise"), { item: s.item, note: ask.value }, (p) => intakeProposal(p, id, ai, detail, at)) } });
    return h("div", { class: "item", "data-key": s.item },
      h("p", { textContent: `Item ${s.item + 1}: spool ${s.spool_ids.join(", ")} (filament ${s.filament_id})${s.spool_ids.length > 1 ? "; changes apply to all of them" : ""}` }),
      h("div", { class: "row" }, ...fields), save,
      h("div", {}, ask, revise, ai ? null : h("p", { class: "muted", textContent: "Label reading is off on this server, so only edits by hand." })), at);
  });
  const live = (rec.revisions || []).filter((v) => !v.undone);
  const last = live[live.length - 1];
  fill(detail,
    photos.length ? h("div", { class: "row" }, ...photos) : h("p", { class: "muted", textContent: "No photo was taken for this addition." }),
    ...items,
    ...(rec.revisions || []).map((v) => h("p", { class: "muted", textContent:
      `Revision ${v.n} ${(v.at || "").slice(0, 16).replace("T", " ")} by ${v.by === "ai" ? "the AI" : "hand"}${v.undone ? " (undone)" : ""}: `
      + [...new Set(v.changes.map((c) => `${c.field} ${c.old} → ${c.new}`))].join("; ")
      + (v.note ? ` · note: ${v.note}` : "")
      + (!v.undone && (v.filaments || {}).orphaned && v.filaments.orphaned.length ? ` · filament ${v.filaments.orphaned.join(", ")} has no spools left (not deleted)` : "") })),
    last ? h("button", { class: "secondary", textContent: `Undo revision ${last.n}`, on: { click: () =>
      intakePost(note, histPath(id, "undo"), { revision: last.n }, (r) => intakeDone(r, id, ai, detail, "Undone.")) } }) : null,
    note);
}

function intakeProposal(p, id, ai, detail, note) {
  const rows = p.changes.map((k) => h("p", { textContent: `${k}: ${p.before[k]} → ${p.after[k]}` }));
  fill(note,
    h("p", { textContent: p.changes.length ? "The AI suggests:" : "The AI changed nothing." }),
    p.no_photo ? h("p", { class: "muted", textContent: "No photo was kept for this record: it worked from the saved values and your note." }) : null,
    p.reader ? h("p", { class: "muted", textContent: `Read again by ${p.reader === "local" ? "the local reader" : "Claude"}${p.confidence != null ? ", " + Math.round(p.confidence * 100) + " % sure" : ""}${p.note ? " (" + p.note + ")" : ""}.` }) : null,
    ...rows,
    p.changes.length ? h("div", { class: "row" },
      h("button", { textContent: "Accept", on: { click: () => intakePost(note, histPath(id, "apply"), { proposal: p.proposal }, (r) => intakeDone(r, id, ai, detail, null, note)) } }),
      h("button", { class: "secondary", textContent: "Discard", on: { click: () => fill(note) } })) : null);
}

// `at`: the slot of the control that asked (an item's, or the record's)
function intakeDone(r, id, ai, detail, text, at) {
  if (detail.mark) detail.mark.textContent = INTAKE_STATE[r.state] || r.state;
  const v = r.revisions[r.revisions.length - 1] || {};
  const fl = v.filaments || {};
  intakeDetail(id, ai, detail).then(() => say(at || boxFor("record:" + id), text || (
    "Saved." + (fl.to !== fl.from ? ` The spools now use filament ${fl.to}${fl.created ? " (new)" : ""}.` : "")
    + (fl.orphaned && fl.orphaned.length ? ` Filament ${fl.orphaned.join(", ")} has no spools left; it was not deleted.` : "")), true));
}
