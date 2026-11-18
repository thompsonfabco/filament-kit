// The Overview's two alert places (03 4.2): the Running low card with its "Running low" dialog (#overview/running-low) and the
// Storage row with its "Storage use" panel (#overview/storage-use). Loaded after setup_alertbar.js (its texts, axt). The Overview
// calls ovLowCard() and ovStorageRows() / ovStorageFix(); the two addresses open by themselves (alertsPlace, below). Reads
// only GET api/spools/low and GET api/storage-use; everything from the Hub goes in through textContent.
"use strict";

// ----- Running low (03 4.2): up to five rows in the card, every row in the dialog -----
const LOW_CARD_ROWS = 5;
const lowHex = (c) => (/^#?[0-9A-Fa-f]{6}$/.test(String(c || "")) ? "#" + String(c).replace("#", "") : null);
function lowRow(s) {
  const stock = s.last_one ? SW.status("needs_look", { small: true, text: axt("running_low_last_one") })
    : h("span", { class: "low__stock muted", textContent: axt("running_low_in_stock", { count: s.in_stock || 0 }) });
  return h("li", { class: "low__row", "data-spool": s.id },
    SW.swatch(lowHex(s.color)),
    h("div", { class: "low__text" },
      h("span", { class: "low__name", textContent: s.filament || "", title: s.filament || "" }),
      h("span", { class: "low__meta muted" },
        h("span", { textContent: SW.t("running_low_spool", { id: s.id }) }),
        h("span", { class: "mono", textContent: SW.t("running_low_left", { grams: s.remaining_g }) }),
        s.location ? h("span", { textContent: s.location }) : null)),
    stock);
}
// the Overview's card: nothing at all (an empty box) while the Hub has no spool low or no such route (03 4.3)
function ovLowCard() {
  const el = h("div", { class: "overview__low" });
  later(api("spools/low").then((d) => {
    const list = d.spools || [];
    if (!list.length) return;
    const more = list.length > LOW_CARD_ROWS;
    el.replaceChildren(h("section", { class: "card low", "aria-labelledby": "overview-low-title" },
      h("div", { class: "overview__head" }, h("h2", { id: "overview-low-title", textContent: axt("running_low_title") }),
        SW.status("needs_look", { small: true, text: String(list.length) })),
      h("ul", { class: "low__list" }, list.slice(0, LOW_CARD_ROWS).map(lowRow)),
      more ? h("div", { class: "actions" }, SW.btn(axt("running_low_show_all", { count: list.length }), { cls: "btn--ghost", action: "low-show-all",
        run: (e) => openPlace("running-low", e.currentTarget) })) : null));
  }, () => {}));
  return el;
}
async function lowBody(region) {
  const L = SW.loading(region, { thing: axt("running_low_title"), items: 3, onTry: () => lowBody(region), title: axt("alerts_low_error") });
  try {
    const d = await api("spools/low");
    L.done(h("ul", { class: "low__list" }, (d.spools || []).map(lowRow)),
      h("p", { class: "low__foot muted" }, axt("alerts_low_foot", { grams: d.threshold_g }), " ", axLink("#settings/alerts", axt("alerts_low_foot_link"))));
  } catch (e) {
    L.done(SW.errorState({ title: axt("alerts_low_error"), text: hubText(e.message), onTry: () => lowBody(region) }));
  }
}

// ----- the Storage row and the panel (03 4.2): the row is the Hub's own check row (status key hub.storage, action storage_use) -----
// the row's fix: opens the panel
const ovStorageFix = () => h("div", { class: "actions" }, SW.btn(axt("alert_show_storage"), { action: "storage-show", run: (e) => openPlace("storage-use", e.currentTarget) }));

// a link that closes the open dialog first (its address then opens the place)
const axLink = (href, text, cls) => h("a", { href, class: cls, textContent: text, on: { click: (e) => { const d = e.currentTarget.closest("dialog"); if (d) d.close(); } } });
// where to reduce an item (03 4.2): the Hub's item keys backups, photos, reader; events and logs have none
function stuseWhere(it, keep) {
  const key = String(it.key || "");
  if (key === "backups") return axLink("#settings/backups", axt("storage_use_where_backups"), "btn");
  if (key === "photos") return keep == null ? null : h("span", { class: "muted", textContent: axt("storage_use_where_photos", { count: keep }) });
  if (key === "reader") return axLink("#settings/label-reader", axt("storage_use_where_reader"));
  return null;
}
function stuseBody(d, general) {
  // Records kept (Settings > Label Reader): 20 until it is set, as that field says
  const keep = general && general.values ? Number(general.values["intake.history_keep"] ?? 20) : null;
  const bars = (d.filesystems || []).map((f) => h("div", { class: "stuse__fs", "data-state": f.state },
    SW.progress({ label: f.title, value: (f.percent_used || 0) / 100, valuetext: axt("alerts_storage_free", { free: axSize(f.free), total: axSize(f.total), percent: Math.round(f.percent_used) }),
      failed: f.state === "bad" }),
    h("p", { class: "stuse__line muted", textContent: axt("alerts_storage_free", { free: axSize(f.free), total: axSize(f.total), percent: Math.round(f.percent_used) }) })));
  const items = (d.items || []).map((it) => h("li", { class: "stuse__item", "data-key": it.key },
    h("span", { class: "stuse__title", textContent: it.title }), h("span", { class: "stuse__size mono", textContent: axSize(it.bytes) }),
    h("span", { class: "stuse__where" }, stuseWhere(it, keep))));
  return h("div", { class: "stuse__body" }, ...bars, items.length ? h("ul", { class: "stuse__items" }, items) : h("p", { class: "muted", textContent: axt("alerts_storage_empty") }));
}
// the panel reads when it opens: the skeleton, then the parts, or the error state with Try again
function stuseFill(region) {
  const go = async () => {
    const L = region._loaded ? null : SW.loading(region, { thing: axt("storage_use_title"), items: 3, onTry: go, title: axt("storage_use_unreadable", { reason: "" }).trim() });
    try {
      const [d, general] = await Promise.all([api("storage-use"), api("settings/general").catch(() => null)]);
      if (L) L.done();
      region._loaded = true;
      region.replaceChildren(stuseBody(d, general));
    } catch (e) {
      if (L) L.done();
      region._loaded = false;
      region.replaceChildren(SW.errorState({ title: axt("storage_use_unreadable", { reason: "" }).trim(), text: hubText(e.message), onTry: go }));
    }
  };
  return go();
}

// ----- the two addresses (03 1.2): #overview/storage-use and #overview/running-low open their dialog over Overview -----
// A place opens once; closing it puts the address back to #overview, and leaving the address (Back, another link) closes it. The
// Storage use panel is a sheet on a phone. A button moves the address without a hash change, so the page behind is not drawn again.
let axShown = null, axDlg = null;
const AX_PLACES = {
  "running-low": (opener) => axDialog("running-low", axt("running_low_title"), (r) => lowBody(r), opener, false),
  "storage-use": (opener) => axDialog("storage-use", axt("storage_use_title"), (r) => stuseFill(r), opener, SW.phone()),
};
function axDialog(place, title, fill, opener, asSheet) {
  if (axShown === place) return;
  axShown = place;
  const region = h("div", { class: "alerts__place", "data-place": place });
  const open = (d, op) => { axDlg = d; SW.openModal(d, op); };
  const done = () => {
    if (axShown === place) { axShown = null; axDlg = null; }
    if (location.hash === "#overview/" + place) history.replaceState(null, "", "#overview");
  };
  if (asSheet) open(SW.sheet({ title, body: region, onClose: done }), opener);
  else SW.ask({ kind: "info", wide: true, title, body: region, opener, open }).then(done);
  fill(region);
}
function openPlace(place, opener) {
  if (location.hash !== "#overview/" + place) history.pushState(null, "", "#overview/" + place);
  AX_PLACES[place](opener);
}
function alertsPlace() {
  const [section, place] = location.hash.slice(1).split("/");
  const here = section === "overview" && AX_PLACES[place] ? place : null;
  if (axShown && axShown !== here && axDlg) axDlg.close();
  if (here) AX_PLACES[here]();
}
window.addEventListener("hashchange", alertsPlace);
document.addEventListener("DOMContentLoaded", () => setTimeout(alertsPlace, 0));
