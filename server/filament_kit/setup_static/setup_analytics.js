// The Analytics section (R84 section 5): the six insight sentences, filament used per month as bars (inline SVG, no chart
// library) or a table, and a table per material for one month. Loaded after setup.js; everything from the server goes in
// through textContent, as there. The section is opened by the registry (TABS in setup.js), which is not this file's.
"use strict";

// The texts of this section until the catalogue has them (only HD2 opens strings/): a key the catalogue has wins.
const AN_TEXT = {
  analytics_error: "Could not read the analytics{reason}",
  analytics_title: "Analytics",
  analytics_insights_title: "Highlights",
  analytics_chart_title: "Filament used per month",
  analytics_chart_label: "Filament used per month in the last 12 months",
  analytics_printer_label: "Printers",
  analytics_printer_all: "All printers",
  analytics_show_table: "Show as table",
  analytics_grams: "{grams} g",
  analytics_kilograms: "{kg} kg",
  analytics_col_month: "Month",
  analytics_col_grams: "Filament used",
  analytics_col_prints: "Prints",
  analytics_col_unfinished: "Did not finish",
  analytics_col_material: "Most used material",
  analytics_col_share: "Share",
  analytics_unfinished_cell: "{count} ({grams})",
  analytics_nothing: "None",
  analytics_material_title: "Filament used by material",
  analytics_month_label: "Month",
  analytics_material_col: "Material",
  analytics_share: "{percent}%",
  analytics_material_none: "No filament was used in {month}.",
  analytics_material_unknown: "No materials are recorded for {month}.",
  analytics_empty_title: "No usage yet",
  analytics_empty_text: "Filament your printers use is counted here, month by month, once a print has been logged.",
  analytics_note_logged_only: "Includes {grams} g the Hub logged but took off no spool.",
  analytics_note_no_weight_one: "{count} print has no weight.",
  analytics_note_no_weight_other: "{count} prints have no weight.",
};
const anT = (key, vars) => (window.SW_TEXT && window.SW_TEXT[key] != null ? SW.t(key, vars)
  : AN_TEXT[key].replace(/\{([a-z]+)\}/g, (m, n) => (vars && vars[n] != null ? String(vars[n]) : m)));

// the insights come in the order of R84 5.2, whatever order the Hub sends them in
const AN_ORDER = ["total", "favourite_material", "busiest_printer", "unfinished", "biggest_print", "spools_finished"];
const AN_MONTHS = 12;

// what the section keeps while it is drawn again (a job ended, the lock changed): the choices and the printers seen
const anState = { printer: "", table: false, month: "", printers: new Map() };

const anKey = (y, m) => y + "-" + String(m).padStart(2, "0");
// the last `count` months, oldest first, ending with the newest the Hub answered or this month
function anSpan(months, count) {
  const now = new Date();
  let end = anKey(now.getFullYear(), now.getMonth() + 1);
  for (const m of months) if (m.month > end) end = m.month;
  let [y, mo] = end.split("-").map(Number);
  const keys = [];
  for (let i = 0; i < count; i++) { keys.unshift(anKey(y, mo)); if (--mo === 0) { mo = 12; y--; } }
  return keys;
}
const anMonth = (key, long) => {
  const [y, m] = key.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 15)).toLocaleDateString(undefined, { month: long ? "long" : "short", year: "numeric", timeZone: "UTC" });
};
const anGrams = (g) => (g >= 1000 ? anT("analytics_kilograms", { kg: (g / 1000).toFixed(2) }) : anT("analytics_grams", { grams: Math.round(g) }));
const anBlank = (month) => ({ month, grams: 0, prints: 0, unfinished_prints: 0, unfinished_grams: 0, logged_only_grams: 0,
  no_weight_prints: 0, by_printer: [], by_material: [] });

// one bar per month: the grams above it in words, the bar itself an SVG that is told its length by --level (0 to 1) and is
// laid out upright, or lengthwise when the room is narrow (setup_analytics.css)
function anBar(m, level) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg"), rect = document.createElementNS(NS, "rect");
  svg.setAttribute("viewBox", "0 0 1 1");
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.setAttribute("class", "an-bar__svg");
  for (const [k, v] of [["x", "0"], ["y", "0"], ["width", "1"], ["height", "1"], ["class", "an-bar__rect"]]) rect.setAttribute(k, v);
  svg.append(rect);
  const li = h("li", { class: "an-bar", "data-month": m.month },
    h("span", { class: "an-bar__grams", textContent: anGrams(m.grams) }),
    h("span", { class: "an-bar__plot" }, svg),
    h("span", { class: "an-bar__month", textContent: anMonth(m.month) }));
  li.style.setProperty("--level", String(level));
  if (!m.grams) li.dataset.empty = "true";
  return li;
}

function anChart(rows) {
  const top = Math.max(0, ...rows.map((m) => m.grams));
  return h("div", { class: "an-chartbox" },
    h("ul", { class: "an-chart", "aria-label": anT("analytics_chart_label") }, rows.map((m) => anBar(m, top ? m.grams / top : 0))));
}

// a table that stacks into labelled blocks when the room is narrow (the cells carry their column's name in data-label)
function anTable(caption, head, rows) {
  return h("div", { class: "an-tablebox" }, h("table", { class: "an-table" },
    h("caption", { class: "sr", textContent: caption }),
    h("thead", {}, h("tr", {}, head.map((c) => h("th", { scope: "col", textContent: c })))),
    h("tbody", {}, rows.map((cells) => h("tr", {}, cells.map((c, i) => (i ? h("td", { "data-label": head[i], textContent: c })
      : h("th", { scope: "row", textContent: c }))))))));
}

function anMonthTable(rows) {
  const head = ["month", "grams", "prints", "unfinished", "material"].map((k) => anT("analytics_col_" + k));
  return anTable(anT("analytics_chart_title"), head, [...rows].reverse().map((m) => [
    anMonth(m.month, true), anGrams(m.grams), String(m.prints),
    m.unfinished_grams ? anT("analytics_unfinished_cell", { count: m.unfinished_prints, grams: anGrams(m.unfinished_grams) }) : String(m.unfinished_prints),
    m.top_material || anT("analytics_nothing")]));
}

function anMaterials(m) {
  const list = [...(m.by_material || [])].sort((a, b) => b.grams - a.grams);
  if (!list.length) return h("p", { class: "muted", textContent: anT(m.grams ? "analytics_material_unknown" : "analytics_material_none", { month: anMonth(m.month, true) }) });
  const sum = list.reduce((s, x) => s + x.grams, 0) || 1;
  const head = [anT("analytics_material_col"), anT("analytics_col_grams"), anT("analytics_col_share")];
  return anTable(anT("analytics_material_title"), head,
    list.map((x) => [x.material, anGrams(x.grams), anT("analytics_share", { percent: Math.round((x.grams / sum) * 100) })]));
}

// the notes under the bars: the Hub's own (R84 5.5), else the same two drawn from the months
function anNotes(data, rows) {
  const given = (data.notes || []).filter(Boolean);
  if (given.length) return given;
  const logged = rows.reduce((s, m) => s + (m.logged_only_grams || 0), 0), bare = rows.reduce((s, m) => s + (m.no_weight_prints || 0), 0);
  return [logged ? anT("analytics_note_logged_only", { grams: Math.round(logged) }) : null,
    bare ? anT(bare === 1 ? "analytics_note_no_weight_one" : "analytics_note_no_weight_other", { count: bare }) : null].filter(Boolean);
}

function analyticsTab() {
  const out = h("div", { class: "an" });
  const gate = h("div", { class: "an__gate" }), main = h("div", { class: "an__main", hidden: true });
  const insights = h("section", { class: "card an__insights", hidden: true });
  const printerField = SW.field({ label: anT("analytics_printer_label"), type: "select", name: "printer", options: [{ value: "", label: anT("analytics_printer_all") }] });
  const tableCheck = SW.check({ label: anT("analytics_show_table"), name: "table", checked: anState.table });
  const monthField = SW.field({ label: anT("analytics_month_label"), type: "select", name: "month", options: [] });
  const chartArea = h("div", { class: "an__chart" }), notes = h("ul", { class: "an__notes muted" }), materials = h("div", { class: "an__materials" });
  main.append(insights,
    h("section", { class: "card an__months" }, h("h2", { textContent: anT("analytics_chart_title") }),
      h("div", { class: "an__controls" }, printerField, tableCheck), chartArea, notes),
    h("section", { class: "card an__by-material" }, h("h2", { textContent: anT("analytics_material_title") }), monthField, materials));
  out.append(gate, main);

  let data = null, seq = 0;

  const syncPrinters = (answer) => {
    if (!anState.printer) for (const m of answer.months || []) for (const p of m.by_printer || []) anState.printers.set(String(p.id), p.name);
    printerField._control.replaceChildren(...[["", anT("analytics_printer_all")], ...anState.printers].map(([value, label]) => h("option", { value, textContent: label })));
    printerField._control.value = anState.printer;
    printerField.hidden = anState.printers.size === 0;
  };

  const drawMaterials = (rows) => {
    const m = rows.find((x) => x.month === monthField._control.value) || rows[rows.length - 1];
    materials.replaceChildren(anMaterials(m));
  };

  const draw = () => {
    const answer = data, keys = anSpan(answer.months || [], AN_MONTHS), by = new Map((answer.months || []).map((m) => [m.month, m]));
    const rows = keys.map((k) => by.get(k) || anBlank(k));
    const used = rows.some((m) => m.grams || m.prints);
    const lines = [...(answer.insights || [])].sort((a, b) => (AN_ORDER.indexOf(a.key) + 1 || 99) - (AN_ORDER.indexOf(b.key) + 1 || 99));
    insights.hidden = !lines.length;
    insights.replaceChildren(...(lines.length ? [h("h2", { textContent: anT("analytics_insights_title") }),
      h("ul", { class: "an__list" }, lines.map((l) => h("li", { "data-key": l.key, textContent: l.text })))] : []));
    tableCheck.hidden = !used;
    if (!used) {
      // nothing logged in these months: one calm line, not twelve empty bars
      chartArea.replaceChildren(SW.empty({ icon: "info", title: anT("analytics_empty_title"), text: anT("analytics_empty_text"), level: 3 }));
      notes.replaceChildren();
      monthField.closest(".card").hidden = true;
      return;
    }
    monthField.closest(".card").hidden = false;
    chartArea.replaceChildren(anState.table ? anMonthTable(rows) : anChart(rows));
    notes.replaceChildren(...anNotes(answer, rows).map((t) => h("li", { textContent: t })));
    const latest = [...rows].reverse().find((m) => m.grams) || rows[rows.length - 1];
    if (!rows.some((m) => m.month === anState.month)) anState.month = latest.month;
    monthField._control.replaceChildren(...[...rows].reverse().map((m) => h("option", { value: m.month, textContent: anMonth(m.month, true) })));
    monthField._control.value = anState.month;
    drawMaterials(rows);
  };

  // `where`: the part that shows the wait or the failure (the whole section the first time, the bars when a printer is chosen)
  const load = (where) => {
    const mine = ++seq, L = SW.loading(where, { thing: anT("analytics_title"), items: 3, onTry: () => load(where) });
    const query = "analytics?months=" + AN_MONTHS + (anState.printer ? "&printer=" + encodeURIComponent(anState.printer) : "");
    return Promise.resolve().then(() => api(query)).then((answer) => {
      if (mine !== seq) return;
      L.done();
      data = answer;
      syncPrinters(answer);
      gate.replaceChildren();
      main.hidden = false;
      draw();
    }, (e) => {
      if (mine !== seq) return;
      if (e.locked) { L.done(); throw e; }
      L.done(SW.errorState({ title: anT("analytics_error", { reason: "" }).trim(), text: hubText(e.message), onTry: () => load(where),
        details: (e.path ? "/setup/api/" + e.path + "\n" : "") + (e.status ? "HTTP " + e.status + ": " : "") + e.message }));
    });
  };

  printerField._control.addEventListener("change", () => { anState.printer = printerField._control.value; load(chartArea); });
  tableCheck._control.addEventListener("change", () => { anState.table = tableCheck._control.checked; if (data) draw(); });
  monthField._control.addEventListener("change", () => { anState.month = monthField._control.value; if (data) draw(); });

  later(load(gate));
  return [out];
}
