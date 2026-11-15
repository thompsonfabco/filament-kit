// The Features section (03 9): the setup choice cards, the features collection and applying again; a change is shown in
// the preview drawer first. Loaded after setup.js; everything from the server goes in through textContent, as there.
"use strict";

// the setup names in the catalogue, in the order 03 9.1 gives them
const SETUPS = [["server", "server"], ["all-in-one", "all_in_one"], ["station", "station"]];
const setupKey = (mode) => (SETUPS.find(([m]) => m === mode) || [mode, mode])[1];
const setupName = (mode) => (mode === "custom" ? SW.t("features_setup_custom") : SW.t("features_setup_" + setupKey(mode)));
// a feature's plain name and line; one the catalogue does not know shows the Hub's own title and description
const cataloguedText = (key, then) => { const text = SW.t(key); return text === key ? then : text; };
const featureName = (n) => {
  const m = S.modules.find((x) => x.name === n);
  return cataloguedText("features_name_" + n, m ? m.title : n);
};
const featureLine = (m) => cataloguedText("features_line_" + m.name, m.description);
const needsOf = (m) => m.needs.map((n) => (S.modules.some((x) => x.name === n) ? featureName(n) : n)).join(", ");

let featuresFilter = "all";          // the collection's filter survives a redraw
let drawerOpen = false;              // one preview drawer at a time (the address opens it, so a redraw must not open a second)
const featuresPlace = () => { try { return decodeURIComponent(location.hash.slice(1).split("/")[1] || ""); } catch { return ""; } };
const featuresAddress = (place) => history.replaceState(null, "", "#features" + (place ? "/" + place : ""));
const applyRunning = () => S.apply.running;

// text with `code` parts: the code goes in a code element
const codeParts = (text) => text.split("`").map((part, i) => (i % 2 ? h("code", { class: "mono", textContent: part }) : part));

// ----- the preview drawer (9.4): what the change does, the settings it needs, then Apply -----
const previewSkeleton = () => h("div", { class: "skeleton", "aria-busy": "true" }, h("span", { class: "sr", textContent: SW.t("features_drawer_loading") }),
  ...[0, 1].map(() => h("div", { class: "skeleton__item", "aria-hidden": "true" },
    h("span", { class: "skeleton__line skeleton__line--title" }), h("span", { class: "skeleton__line" }))));

// o: {title, place (the address), read() (the preview), path and body (what Apply sends), opener, refusal(p)}
// Resolves with the reply when the change was saved, else null.
async function previewDrawer(o) {
  if (drawerOpen) return null;
  drawerOpen = true;
  featuresAddress(o.place);
  const body = h("div", { class: "features__preview", "aria-live": "polite" }, previewSkeleton());
  const fields = [];
  let dlg = null;
  const answer = SW.ask({ title: o.title, body, confirm: SW.t("features_drawer_apply"), opener: o.opener,
    open: (d, opener) => { dlg = d; d.classList.add("dialog--drawer"); SW.openModal(d, opener); },
    run: async (_values, { result }) => {
      if (!fields.ready) return false;
      const settings = {};
      let first = null;
      for (const f of fields) {
        const err = f._check();
        SW.fieldError(f, err);
        if (err && !first) first = f;
        settings[f._key] = f._control.value.trim();
      }
      if (first) { first._control.focus(); return false; }
      let r = null;
      await needCode(async () => {
        try { r = await api(o.path, { ...o.body, settings, code: theCode() }); } catch (e) {
          if (e.locked) throw e;
          SW.result(result, "bad", hubText(e.message));
        }
      });
      if (r && !r.changed) { SW.result(result, "info", SW.t("features_drawer_unchanged")); return false; }   // the drawer stays
      return r || false;
    } });
  const apply = dlg.querySelector('[data-action="confirm"]');
  apply.setAttribute("aria-disabled", "true");
  const refuse = (nodes) => {
    body.replaceChildren(SW.banner({ kind: "bad", inline: true, text: nodes }));
    apply.remove();
  };
  let p = null;
  try { p = await o.read(); } catch (e) { refuse(hubText(e.message)); }
  if (p && p.refused) { refuse(codeParts(o.refusal(p))); p = null; }
  if (p) {
    for (const n of p.needs) {
      const web = n.key === "web.public_url";
      const prompt = web ? SW.t("features_drawer_public_prompt") : n.prompt[0].toUpperCase() + n.prompt.slice(1);
      const f = SW.field({ label: prompt, mono: true, placeholder: web ? SW.t("features_drawer_public_placeholder") : undefined,
        check: (v) => (v.trim() ? null : SW.t("features_drawer_required")) });
      f._key = n.key;
      fields.push(f);
    }
    fields.ready = true;
    body.replaceChildren(
      ...p.notes.map((n) => h("p", { class: "muted", textContent: n })),
      h("p", {}, h("span", { class: "features__after", textContent: SW.t("features_drawer_afterwards") }), " ",
        p.after.length ? p.after.map(featureName).join(", ") : SW.t("features_drawer_nothing")),
      ...fields);
    apply.removeAttribute("aria-disabled");
    (fields[0] ? fields[0]._control : apply).focus();
  }
  const r = await answer;
  drawerOpen = false;
  featuresAddress("");
  return r;
}

// after a saved change: the region is read again, the change is said as a toast, the job strip follows the apply
async function featureSaved(opener) {
  const row = opener.closest ? opener.closest("[data-key]") : null;
  await refresh(opener.isConnected ? opener : undefined);
  SW.toast(SW.t("common_saved_applying"));
  followApply(true);
  // the button changed its words with the new state, so the focus it had is found again by the row
  const a = document.activeElement;
  if (row && (!a || a === document.body || a === pageTitle)) {
    const again = sections.querySelector(`[data-key="${CSS.escape(row.dataset.key)}"] button`);
    if (again) again.focus({ preventScroll: true });
  }
}

function featureDrawer(m, opener) {
  const title = SW.t(m.on ? "features_drawer_off" : "features_drawer_on", { feature: featureName(m.name) });
  return previewDrawer({ title, place: m.name, opener, path: "modules", body: { name: m.name, on: !m.on },
    read: () => api(`modules/preview?name=${encodeURIComponent(m.name)}`),
    refusal: () => SW.t("features_drawer_refused_server") }).then((r) => (r ? featureSaved(opener) : null));
}

// the setup's drawer; resolves true once the change was saved (the choice card then stays on the new setup)
async function setupDrawer(mode, opener) {
  const title = SW.t("features_drawer_setup", { setup: setupName(mode) });
  const command = SW.t("features_setup_station_command", { hub_address: location.hostname });
  const r = await previewDrawer({ title, place: "setup-" + mode, opener, path: "modules/mode", body: { mode },
    read: () => api(`modules/preview?mode=${encodeURIComponent(mode)}`),
    refusal: () => `${SW.t("features_setup_station_note")} \`${command}\`` });
  if (r) await featureSaved(opener);
  return !!r;
}

// ----- the setup (9.2, 9.3): one choice card per setup; choosing one opens its drawer -----
function commandBlock(caption, text) {
  const id = SW.uid("cmd");
  return h("div", { class: "code" },
    h("div", { class: "code__bar" }, h("span", { class: "code__caption mono", id: id + "-name", textContent: caption }),
      h("span", { class: "result", role: "status" }), SW.btn(SW.t("common_copy"), { cls: "btn--ghost", icon: "copy", action: "copy" })),
    h("pre", { class: "code__text", tabindex: "0", "aria-labelledby": id + "-name", textContent: text }));
}

function modesCard() {
  const waiting = applyRunning();
  const on = S.modules.filter((m) => m.on).length;
  const here = (name) => (S.modes.find((m) => m.name === name) || { here: true }).here;
  const options = SETUPS.filter(([m]) => S.modes.some((x) => x.name === m)).map(([m, key]) => ({ value: m, label: SW.t("features_setup_" + key),
    disabled: waiting || !here(m) }));
  if (S.mode === "custom") options.push({ value: "custom", label: SW.t("features_setup_custom"), disabled: true });
  const choice = SW.segmented({ legend: SW.t("features_setup_title"), legendSr: true, cls: "segmented--cards", name: "features-setup",
    value: S.mode, options,
    apply: async (mode) => { if (!(await setupDrawer(mode, document.activeElement))) throw new Error("not changed"); } });
  for (const input of choice.querySelectorAll(".segmented__input")) {
    const label = input.nextElementSibling, mode = input.value;
    const line = mode === "custom" ? SW.t("features_setup_custom_line") : SW.t("features_setup_" + setupKey(mode) + "_line");
    label.replaceChildren(h("span", { class: "segmented__name", textContent: label.textContent }), h("span", { class: "segmented__line", textContent: line }));
    if (input.disabled && mode !== "custom") label.title = waiting ? SW.t("features_job_tooltip") : SW.t("features_setup_disabled");
  }
  const command = SW.t("features_setup_station_command", { hub_address: location.hostname });
  // the address `#features/setup-<setup>` opens that setup's drawer, once the page is drawn
  const want = featuresPlace().startsWith("setup-") ? featuresPlace().slice(6) : "";
  if (want && SETUPS.some(([m]) => m === want) && !drawerOpen && !waiting) {
    setTimeout(() => { if (!drawerOpen && choice.isConnected) setupDrawer(want, choice.querySelector(".segmented__input:checked") || choice); }, 0);
  }
  return card(SW.t("features_setup_title"),
    waiting ? SW.banner({ kind: "info", inline: true, text: SW.t("features_job_banner") }) : null,
    h("p", { class: "features__meta muted", textContent: SW.t("features_meta", { setup: setupName(S.mode), on, total: S.modules.length }) }),
    choice,
    S.modes.some((m) => !m.here) ? [h("p", { class: "muted", textContent: SW.t("features_setup_station_note") }),
      commandBlock(SW.t("features_setup_station"), command)] : null);
}

// ----- the features (9.2, 9.3): name with "Uses AI", state, what it does, needs, Turn on / Turn off -----
const featureCell = (col, prio, ...kids) => h("div", { class: "coll__cell", role: "cell", "data-col": col, "data-prio": prio }, ...kids);
const featureHead = (col, prio, text) => h("div", { class: "coll__cell", role: "columnheader", "data-col": col, "data-prio": prio }, text);

function featureRow(m, waiting) {
  const name = featureName(m.name), needs = m.needs.length ? SW.t("features_needs", { list: needsOf(m) }) : "";
  let act;
  if (m.name === "server") act = h("span", { class: "muted", textContent: SW.t("features_always_on") });
  else {
    act = SW.btn(SW.t(m.on ? "common_turn_off" : "features_turn_on"), { name: SW.t(m.on ? "features_turn_off_named" : "features_turn_on_named", { feature: name }) });
    act.addEventListener("click", () => featureDrawer(m, act));
    if (waiting) { act.setAttribute("aria-disabled", "true"); SW.tooltip(act, SW.t("features_job_tooltip")); }
  }
  return h("div", { class: "coll__item", role: "rowgroup", "data-key": m.name, "data-state": m.on ? "on" : "off",
    hidden: featuresFilter === (m.on ? "off" : "on") },
    h("div", { class: "coll__row", role: "row" },
      featureCell("title", 1, h("span", { class: "coll__name", textContent: name }),
        m.optional_ai ? [" ", h("span", { class: "features__tag", textContent: SW.t("features_uses_ai") })] : null,
        h("span", { class: "coll__sub", textContent: [featureLine(m), needs].filter(Boolean).join(" ") })),
      featureCell("status", 1, SW.status(m.on ? "on" : "off", { prefix: true })),
      featureCell("what", 2, featureLine(m)),
      featureCell("needs", 3, h("span", { class: "muted", textContent: needs })),
      featureCell("actions", 1, act)));
}

function modulesCard() {
  const waiting = applyRunning();
  const on = S.modules.filter((m) => m.on).length;
  const list = h("div", { class: "coll coll--features", role: "table", "aria-label": SW.t("nav_features") },
    h("div", { class: "coll__head", role: "rowgroup" }, h("div", { class: "coll__row", role: "row" },
      featureHead("title", 1, SW.t("features_col_feature")), featureHead("status", 1, SW.t("common_field_state")),
      featureHead("what", 2, SW.t("features_col_what")), featureHead("needs", 3, SW.t("features_col_needs")),
      featureHead("actions", 1, h("span", { class: "sr", textContent: SW.t("common_actions") })))),
    ...S.modules.map((m) => featureRow(m, waiting)));
  SW.collection(list, { name: "features" });
  const filter = SW.segmented({ legend: SW.t("features_filter_legend"), legendSr: true, cls: "features__filter", name: "features-filter",
    value: featuresFilter, options: [
      { value: "on", label: SW.t("features_filter_on", { count: on }) },
      { value: "off", label: SW.t("features_filter_off", { count: S.modules.length - on }) },
      { value: "all", label: SW.t("features_filter_all") }] });
  filter.addEventListener("change", (e) => {
    featuresFilter = e.target.value;
    for (const it of list.querySelectorAll(".coll__item")) it.hidden = featuresFilter === (it.dataset.state === "on" ? "off" : "on");
  });
  // the address `#features/<feature>` opens that feature's drawer, once the page is drawn
  const want = S.modules.find((m) => m.name === featuresPlace() && m.name !== "server");
  if (want && !drawerOpen && !waiting) setTimeout(() => { if (!drawerOpen && list.isConnected) featureDrawer(want, list.querySelector(`[data-key="${CSS.escape(want.name)}"] button`) || list); }, 0);
  return card(SW.t("nav_features"), h("div", { class: "coll__toolbar" }, filter), list);
}

// ----- applying again (the job strip is SW_JOBS', wired in setup_tabs.js) -----
function applyCard() {
  const box = boxFor("apply");
  return h("div", { class: "features__apply" }, h("p", { class: "muted", textContent: SW.t("features_apply_note") }),
    h("div", { class: "actions" }, SW.btn(SW.t("features_apply_again"), { cls: "btn--ghost", run: async () => {
      const r = await change(box, "apply", {}, () => say(box, SW.t("features_applying_again"), "info"));
      if (r) { followApply(true); refresh(); }
    } })), box);
}

// a change in one of these draws the other with it: the cards go dark together while the apply runs, and the counts agree
modesCard.also = modulesCard;
modulesCard.also = modesCard;
