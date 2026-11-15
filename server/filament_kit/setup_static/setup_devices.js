// The Devices section (03 7): paired devices, the pairing dialog, Weigh Stations asking to pair, the web app on a phone and
// Tag Readers. Loaded after setup.js; everything from the server goes in through textContent, as there. Trusted computers
// are in setup_trust.js. The pairing itself is the Hub's: nothing here makes a code or a token.
"use strict";

const DEVICES = "devices";       // the section's name in TABS; its catalogue keys start with it
const ASK_EVERY = 5000;          // Weigh Stations asking to pair: read again this often while the section shows (03 7.3)
const PAIR_EVERY = 3000;         // the pairing dialog asks for the new device this often (03 7.2)
let devBlocks = 0;
let devPairing = false;          // a pairing is being asked for: pressed again, it does nothing
let devMaking = false;           // a reader token is being made: pressed again (or Enter held), it makes no second one
let devClose = null;             // closes the pairing dialog that is open
const devAnswering = new Set();  // station requests whose Pair or Refuse is out
// a read behind Try again: a refusal for the setup code locks the page, as in every other button
const devRetry = (run) => () => Promise.resolve(run()).catch((e) => { if (!e.locked) throw e; SW.setLock("locked"); });
// a lock takes the pairing code and a new reader token off the screen
document.addEventListener("sw:lock", () => { if (SW.lock.state !== "locked") return; if (devClose) devClose(); SW.result(boxFor("readers"), null); });
let devMetaEl = null;            // the line under the title, kept to change its counts in place
let devTrusted = null;           // trusted computers listed, once read (null: not read, locked or off)
let devQrUrls = [];

const devPad = (n) => String(n).padStart(2, "0");
const devStamp = (t) => { if (!t) return null; const d = new Date(t * 1000); return `${d.getFullYear()}-${devPad(d.getMonth() + 1)}-${devPad(d.getDate())} ${devPad(d.getHours())}:${devPad(d.getMinutes())}`; };
const devGroup = (code) => (code.length === 6 ? `${code.slice(0, 3)} ${code.slice(3)}` : code);
// a catalogue text with `code` spans between backticks
const devParts = (text) => text.split("`").map((p, i) => (i % 2 ? h("code", { class: "mono", textContent: p }) : p));

// a block of code with Copy (02 7.7), as the log in Logs
function devCodeBlock(caption, text) {
  const id = "dev-code-" + ++devBlocks;
  return h("div", { class: "code" },
    h("div", { class: "code__bar" }, h("span", { class: "code__caption mono", id: id + "-name", textContent: caption }),
      h("span", { class: "result", role: "status" }), SW.btn(SW.t("common_copy"), { cls: "btn--ghost", icon: "copy", action: "copy" })),
    h("pre", { class: "code__text", tabindex: "0", "aria-labelledby": id + "-name", textContent: text }));
}
// the Hub's QR drawing through a Blob URL, never as markup; `keep` lists the URLs to let go of at the next drawing
function devQr(svg, alt, keep) {
  if (!svg) return null;
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  keep.push(url);
  return h("img", { class: "qr", alt, src: url });
}

// a collection (02 6.1): `cols` columns, one row group per item, each with the slot of its own result
const devHead = (col, label, prio) => h("div", { class: "coll__cell", role: "columnheader", "data-col": col, "data-prio": prio, textContent: label });
const devActionsHead = () => h("div", { class: "coll__cell", role: "columnheader", "data-col": "actions" }, h("span", { class: "sr", textContent: SW.t("common_actions") }));
const devCell = (col, prio, key, ...kids) => h("div", { class: "coll__cell", role: "cell", "data-col": col, "data-prio": prio },
  key ? h("span", { class: "coll__key", "aria-hidden": "true", textContent: key }) : null, ...kids);
const devRow = (key, box, cols, ...cells) => h("div", { class: "coll__item", role: "rowgroup", "data-key": key, "data-id": key },
  h("div", { class: "coll__row", role: "row" }, ...cells),
  h("div", { class: "coll__row coll__row--result", role: "row", hidden: !box.dataset.state }, h("div", { class: "coll__cell", role: "cell", "aria-colspan": cols }, box)));
const devTable = (cls, name, heads, rows) => h("div", { class: "coll " + cls, role: "table", "aria-label": name },
  h("div", { class: "coll__head", role: "rowgroup" }, h("div", { class: "coll__row", role: "row" }, ...heads)), ...rows);

// whenOpen (setup.js) for this section's cards: whenOpen forgets every place whose element is not in the page yet, and a
// section draws all its cards before any of them is in, so with several code-gated cards only the last would follow the lock.
// This list forgets a place only once its element has been in the page and left it.
const devPlaces = new Set();
function devWhenOpen(el, paint) {
  for (const p of devPlaces) if (p.checked && !p.el.isConnected) devPlaces.delete(p);
  const p = { el, open: null, checked: false, run() {
    const open = SW.lock.state !== "locked";
    if (open === p.open) return;
    p.open = open;
    later(Promise.resolve(paint(open)).catch((e) => (e.locked ? SW.setLock("locked") : say(el, e.message, false))));
  } };
  devPlaces.add(p);
  queueMicrotask(() => { p.checked = true; });       // the region is drawn and in the page by then
  p.run();
}
document.addEventListener("sw:lock", () => { for (const p of devPlaces) if (p.el.isConnected) p.run(); else if (p.checked) devPlaces.delete(p); });

// ----- the section header (02 2.1): the counts under the title, the pairings at the right -----
function devMeta() {
  if (!devMetaEl || !S) return;
  const parts = [SW.t("devices_meta_paired", { count: S.devices.length }), SW.t("devices_meta_readers", { count: S.readers.list.length })];
  if (devTrusted != null) parts.push(SW.t("devices_meta_trusted", { count: devTrusted }));
  devMetaEl.textContent = parts.join(" · ");
}
function devHeader() {
  const phone = SW.btn(SW.t("devices_pair_phone"), { cls: "btn--primary", icon: "plus", action: "pair-phone", run: () => devPair("phone") });
  const sync = SW.btn(SW.t("devices_link_sync"), { action: "link-sync", run: () => devPair("pc") });
  const more = SW.iconBtn("more", SW.t("common_more_actions"), { action: "pair-more" });
  const here = S.modules.some((m) => m.name === "station" && m.on);       // the Weigh Station feature is on
  SW.menu(more, [{ label: SW.t("devices_link_station"), action: "link-station", run: () => devPair("station") },
    ...(here ? [{ label: SW.t("devices_pair_station_here"), action: "pair-here", run: () => devPairHere() }] : [])],
  { label: SW.t("common_more_actions") });
  devMetaEl = h("p", { class: "page-head__meta" });
  devMeta();
  pageHead(devMetaEl, h("div", { class: "page-head__actions" }, sync, more, phone));
}
// the pairing of the Weigh Station on this Hub is the Hub's own job: it makes its own code and the job strip follows it
const devPairHere = () => startJob(boxFor("pair"), "station_pair");

// ----- the pairing dialog (03 7.2) -----
const PAIR_KINDS = {
  phone: { heading: "devices_pair_phone", text: "devices_pair_instruction_phone", print: "devices_pair_fingerprint_phone", back: "pair-phone" },
  pc: { heading: "devices_link_sync", text: "devices_pair_instruction_sync", print: "devices_pair_fingerprint_other", back: "link-sync" },
  station: { heading: "devices_link_station", text: "devices_pair_instruction_station", print: "devices_pair_fingerprint_other", back: "pair-more" },
};

// asks the Hub for a code (it needs the setup code), then shows it
async function devPair(kind) {
  if (devPairing) return;
  devPairing = true;
  try {
    const box = boxFor("pair"), known = new Set(S.devices.map((d) => d.id));
    const r = await change(box, "pair", { kind }, () => fill(box));
    if (r) devPairDialog(kind, r, known);
  } finally { devPairing = false; }
}

// The dialog on desktop and tablet, the bottom sheet on a phone (the shared dialog look does both). It counts the code
// down, asks the Hub for the new device every 3 s, and ends as Done, or as Expired with a way to make a new code. Closing
// it only stops the asking: the code simply expires.
function devPairDialog(kind, first, known) {
  const K = PAIR_KINDS[kind], id = SW.uid("pair"), box = boxFor("pair");
  const st = { r: first, known, phase: "waiting", end: 0, total: 1, poll: 0, tick: 0, qr: null, stopped: false, said: false, asking: false, name: "" };
  const body = h("div", { class: "pairing" }), res = h("p", { class: "result result--block dialog__result", role: "status" });
  const foot = h("div", { class: "dialog__foot" });
  const close = () => dlg.close();
  const form = h("form", { class: "dialog__form", method: "dialog", novalidate: true },
    h("div", { class: "dialog__head" }, h("h2", { class: "dialog__title", id: id + "-title", textContent: SW.t(K.heading) }),
      SW.iconBtn("close", SW.t("common_close"), { action: "cancel", run: close })),
    h("div", { class: "dialog__body" }, body, res), foot);
  const dlg = h("dialog", { class: "dialog dialog--wide", "aria-labelledby": id + "-title" }, form);
  let bar = null, expiry = null;

  const left = () => Math.max(0, st.end - Date.now());
  const readState = async () => { try { return await api("state"); } catch { return null; } };    // the Hub may be restarting: the next try tells
  const newcomer = (s) => (s ? s.devices.find((d) => !st.known.has(d.id)) : null);
  const stopTimers = () => { clearTimeout(st.poll); clearInterval(st.tick); };

  function paint() {
    if (st.qr) { URL.revokeObjectURL(st.qr); st.qr = null; }
    const r = st.r, urls = [];
    SW.result(res, null);
    bar = expiry = null;
    const cancel = SW.btn(SW.t("common_cancel"), { action: "cancel", run: close });
    if (st.phase === "paired") {
      const done = SW.btn(SW.t("devices_pair_done_button"), { cls: "btn--primary", action: "done", run: close });
      body.replaceChildren();
      SW.result(res, "ok", SW.t("qr_paired", { name: st.name }));
      foot.replaceChildren(done);
      done.focus();
      return;
    }
    if (st.phase === "expired") {
      const again = SW.btn(SW.t("qr_new_code"), { cls: "btn--primary", action: "new-code", run: () => makeNew() });
      body.replaceChildren();
      SW.result(res, "warn", SW.t("qr_expired"));
      foot.replaceChildren(cancel, again);
      again.focus();
      return;
    }
    const text = SW.t(K.text), command = text.split("`")[1];
    const link = devCodeBlock(SW.t("devices_pair_link"), r.link);
    const main = kind === "phone"
      ? (r.qr_svg ? [h("div", { class: "pairing__qr" }, devQr(r.qr_svg, SW.t("qr_alt_pair"), urls))]
        : [h("p", { class: "muted", textContent: SW.t("qr_unavailable") }), link])
      : kind === "station" ? [devCodeBlock(SW.t("devices_pair_command"), command), link] : [link];
    st.qr = urls[0] || null;
    const minutes = Math.max(1, Math.ceil(left() / 60000));
    bar = SW.progress({ name: SW.t("qr_expires", { minutes }), value: left() / st.total, valuetext: SW.t("qr_expires", { minutes }) });
    expiry = h("p", { class: "muted", textContent: SW.t("qr_expires", { minutes }) });
    body.replaceChildren(h("p", {}, ...devParts(text)), ...main,
      h("div", { class: "pairing__code" }, h("p", { class: "muted", textContent: SW.t("devices_pair_code") }),
        h("p", { class: "pairing__digits mono", textContent: devGroup(r.code) })),
      h("div", {}, h("p", { class: "muted", textContent: SW.t(K.print) }), h("p", { class: "pairing__print mono", textContent: r.fingerprint })),
      h("div", {}, bar, expiry),
      h("p", { class: "pairing__wait" }, SW.spinner(), SW.t("devices_pair_waiting")));
    foot.replaceChildren(cancel);
  }

  // every second: the bar and the minutes; at one minute and at zero the person hears it (02 7.8)
  function count() {
    if (st.phase !== "waiting") return;
    const ms = left(), minutes = Math.max(1, Math.ceil(ms / 60000)), words = SW.t("qr_expires", { minutes });
    if (bar) SW.setProgress(bar, ms / st.total, words);
    if (expiry && expiry.textContent !== words) expiry.textContent = words;
    if (ms <= 60000 && !st.said) { st.said = true; SW.announce(words); }
    if (ms <= 0) expire();
  }
  async function poll() {
    if (st.stopped || st.phase !== "waiting") return;
    const fresh = newcomer(await readState());
    if (st.stopped || st.phase !== "waiting") return;
    if (fresh) { await paired(fresh); return; }
    st.poll = setTimeout(poll, PAIR_EVERY);
  }
  // the code ran out: one last look, in case the device came in at the end
  async function expire() {
    if (st.phase !== "waiting") return;
    st.phase = "checking";
    stopTimers();
    const fresh = newcomer(await readState());
    if (st.stopped) return;
    if (fresh) { await paired(fresh); return; }
    st.phase = "expired";
    paint();
  }
  async function paired(fresh) {
    st.phase = "paired";
    st.name = fresh.name;
    stopTimers();
    await refresh(box);          // the list of paired devices follows
    if (!st.stopped) paint();
  }
  function begin() {
    stopTimers();
    st.phase = "waiting";
    st.total = Math.max(1, st.r.expires_in * 1000);
    st.end = Date.now() + st.total;
    st.said = false;
    paint();
    st.tick = setInterval(count, 1000);
    st.poll = setTimeout(poll, PAIR_EVERY);
    if (st.r.expires_in <= 0) expire();
  }
  // Make a new code: the same request as the first; what goes wrong is said in the dialog
  async function makeNew() {
    if (st.asking) return;
    st.asking = true;
    try {
      const r = await change(res, "pair", { kind }, () => SW.result(res, null));
      if (r && !st.stopped) { st.r = r; st.known = new Set(S.devices.map((d) => d.id)); begin(); }
    } finally { st.asking = false; }
  }

  // the dialog has its own address while it is open; leaving the section closes it
  const away = () => { if (!location.hash.startsWith("#" + DEVICES)) close(); };
  window.addEventListener("hashchange", away);
  devClose = close;
  dlg._noReturn = true;          // focus goes back to the pairing's own button, which the redraw has made new
  SW.modal(dlg, { temp: true, onClose: () => {
    st.stopped = true;
    devClose = null;
    stopTimers();
    if (st.qr) URL.revokeObjectURL(st.qr);
    window.removeEventListener("hashchange", away);
    if (location.hash === "#" + DEVICES + "/pair") history.replaceState(null, "", "#" + DEVICES);
    const back = document.querySelector(`.page-head__actions [data-action="${K.back}"]`);
    if (back && back.getClientRects().length) back.focus({ preventScroll: true }); else pageTitle.focus({ preventScroll: true });
  } });
  begin();
  SW.openModal(dlg, document.activeElement);
  history.replaceState(null, "", "#" + DEVICES + "/pair");
  const first1 = foot.querySelector("button");
  if (first1) first1.focus();
}

// ----- Paired devices (03 7.2) -----
function pairCard() {
  devHeader();
  const box = boxFor("pair");
  const rows = S.devices.map((d) => {
    const at = boxFor("device:" + d.id);
    const unpair = d.built_in ? null : SW.btn(SW.t("devices_unpair"), { cls: "btn--ghost", name: SW.t("devices_unpair_named", { name: d.name }), action: "unpair",
      run: () => asking(at, `devices/${encodeURIComponent(d.id)}/revoke`, destroy("devices_unpair_title", "devices_unpair_body", "devices_unpair", { name: d.name }),
        undefined, () => say(at, SW.t("devices_unpaired", { name: d.name }), true)) });
    return devRow(d.id, at, 4,
      devCell("title", 1, null, h("span", { class: "devices__name", textContent: d.name }),
        d.built_in ? [" ", SW.status("note", { text: SW.t("devices_built_in"), small: true }), h("span", { class: "coll__sub muted", textContent: SW.t("devices_built_in_line") })] : null),
      devCell("paired", 2, SW.t("devices_col_paired"), d.paired || SW.t("common_unknown")),
      devCell("last_seen", 1, SW.t("devices_col_last_seen"), d.last_seen || SW.t("common_never")),
      devCell("actions", 1, null, h("div", { class: "actions" }, unpair)));
  });
  return card(SW.t("devices_paired_title"), box, S.devices.length
    ? devTable("coll--paired", SW.t("devices_paired_title"), [devHead("title", SW.t("devices_col_device")), devHead("paired", SW.t("devices_col_paired"), 2),
      devHead("last_seen", SW.t("devices_col_last_seen"), 1), devActionsHead()], rows)
    : SW.empty({ icon: "devices", title: SW.t("devices_empty"), level: 3 }));
}

// one answer per request at a time: pressed again while it is out, Pair or Refuse sends nothing more
async function devAnswer(id, run) {
  if (devAnswering.has(id)) return;
  devAnswering.add(id);
  try { await run(); } finally { devAnswering.delete(id); }
}

// ----- Weigh Stations asking to pair (03 7.3): Pair only when the Weigh Station's screen shows the same six digits -----
function stationAsksCard() {
  const body = h("div"), note = h("div", { role: "status" });
  let me = 0, timer = 0, loaded = false, seen = null, L = null;
  const stop = () => { clearInterval(timer); timer = 0; };
  const failed = (e) => SW.errorState({ title: SW.t("devices_requests_error", { reason: "" }).trim(), text: hubText(e.message), level: 3, onTry: devRetry(() => read()) });
  const rows = (list) => (list.length ? list.map((q) => {
    const box = boxFor("request:" + q.id), line = SW.t("devices_request_line", { name: q.name, address: q.address, code: "\u0001" }).split("\u0001");
    return h("div", { class: "item", "data-key": q.id },
      h("p", {}, line[0], h("b", { class: "devices__digits mono", textContent: devGroup(q.code) }), line[1]),
      h("p", { class: "muted", textContent: SW.t("devices_request_hint") }),
      h("div", { class: "row" },
        SW.btn(SW.t("devices_request_pair"), { cls: "btn--primary", name: SW.t("devices_request_pair_named", { name: q.name }), action: "pair",
          run: () => devAnswer(q.id, () => change(box, `stations/requests/${q.id}/pair`, {}, () => say(box, SW.t("devices_request_paired", { name: q.name }), true))) }),
        SW.btn(SW.t("devices_request_refuse"), { name: SW.t("devices_request_refuse_named", { name: q.name }), action: "refuse",
          run: () => devAnswer(q.id, () => change(box, `stations/requests/${q.id}/refuse`, {}, () => say(box, SW.t("devices_request_refused", { name: q.name }), true))) })),
      box);
  }) : [h("p", { class: "muted", textContent: SW.t("devices_requests_none") })]);
  // a read that is not the newest, or comes after the page locked or the card left, is dropped
  async function read() {
    const n = ++me;
    if (!loaded && !L) L = SW.loading(body, { thing: SW.t("devices_requests_title"), items: 1, onTry: devRetry(() => read()), title: SW.t("devices_requests_error", { reason: "" }).trim() });
    let r;
    try { r = await api("stations/requests", { code: theCode() }); } catch (e) {
      if (e.locked) throw e;
      if (n !== me || !body.isConnected) return;
      if (L) { L.done(); L = null; }
      if (!loaded) fill(body, failed(e));          // a later read that fails leaves what is shown; the next one tells
      return;
    }
    if (n !== me || SW.lock.state === "locked" || !body.isConnected) return;
    if (L) { L.done(); L = null; }
    const sig = JSON.stringify(r.requests.map((q) => [q.id, q.name, q.address, q.code]));
    if (loaded && sig === seen) return;            // nothing new: what is being pressed stays
    const a = document.activeElement, at = body.contains(a) && a.closest("[data-key]") ? [a.closest("[data-key]").dataset.key, a.dataset.action] : null;
    loaded = true;
    seen = sig;
    fill(body, ...rows(r.requests));
    const back = at && body.querySelector(`[data-key="${CSS.escape(at[0])}"] [data-action="${at[1]}"]`);
    if (back) back.focus({ preventScroll: true });
  }
  devWhenOpen(body, (open) => {
    stop();
    me++;
    loaded = false;
    seen = null;
    L = null;
    body.removeAttribute("aria-busy");
    if (!open) { body.replaceChildren(); note.replaceChildren(lockNote("devices_requests_locked")); return; }
    note.replaceChildren();
    timer = setInterval(() => {
      if (!body.isConnected) { stop(); return; }
      if (document.hidden || SW.lock.state === "locked") return;
      read().catch((e) => { if (e.locked) SW.setLock("locked"); });
    }, ASK_EVERY);
    return read();
  });
  return card(SW.t("devices_requests_title"), note, body);
}

// ----- The web app on a phone (03 7.4): opened in the phone's browser, served by this Hub; nothing is paired -----
function webAppCard() {
  const body = h("div"), note = h("div", { role: "status" });     // the hidden-values note; the card (home address, QR) stays
  const el = card(SW.t("devices_webapp_title"), body, note);
  let me = 0, loaded = false, L = null;
  const load = (open) => {
    const n = ++me;
    if (!loaded && !L) L = SW.loading(body, { thing: SW.t("devices_webapp_title"), items: 2, onTry: devRetry(() => load(SW.lock.state !== "locked")), title: SW.t("devices_webapp_error", { reason: "" }).trim() });
    return (open ? api("webapp", { code: theCode() }) : api("webapp")).then((r) => {
      if (n !== me) return;
      if (L) { L.done(); L = null; }
      loaded = true;
      note.replaceChildren(...(r.public_hidden ? [lockNote("lock_hidden_note")] : []));
      devQrUrls.forEach((u) => URL.revokeObjectURL(u));
      devQrUrls = [];
      fill(body,
        h("p", { textContent: SW.t("devices_webapp_home") }),
        h("div", { class: "devices__web" }, devCodeBlock(SW.t("devices_webapp_home_caption"), r.url), devQr(r.qr_svg, SW.t("devices_webapp_home_alt"), devQrUrls)),
        h("p", { class: "muted", textContent: SW.t("devices_webapp_hint") }),
        r.public_url ? h("p", { textContent: SW.t("devices_webapp_away") }) : null,
        r.public_url ? h("div", { class: "devices__web" }, devCodeBlock(SW.t("devices_webapp_away_caption"), r.public_url), devQr(r.public_qr_svg, SW.t("devices_webapp_away_alt"), devQrUrls)) : null,
        h("p", { textContent: SW.t("devices_webapp_keep") }));
    }, (e) => {
      if (e.locked) throw e;
      if (n !== me) return;
      if (L) { L.done(); L = null; }
      loaded = false;
      fill(body, SW.errorState({ title: SW.t("devices_webapp_error", { reason: "" }).trim(), text: hubText(e.message), level: 3, onTry: devRetry(() => load(SW.lock.state !== "locked")) }));
    });
  };
  devWhenOpen(body, (open) => { body.removeAttribute("aria-busy"); L = null; loaded = false; return load(open); });
  return el;
}

// ----- Tag Readers (03 7.5): the tokens a reader built by hand needs -----
function readersCard() {
  devMeta();
  const R = S.readers, box = boxFor("readers");
  const name = SW.field({ label: SW.t("common_field_name"), name: "name", placeholder: SW.t("devices_readers_name_placeholder"), attrs: { "aria-required": "false" } });
  const make = SW.btn(SW.t("devices_readers_make"), { action: "make-token", run: async () => { if (devMaking) return; devMaking = true; try { await change(box, "readers", { name: name._control.value }, (r) => say(box, [
    h("p", { textContent: SW.t("devices_readers_new", { id: r.id, name: r.name }) }), devCodeBlock(SW.t("devices_readers_token"), r.token),
    SW.banner({ kind: "warn", inline: true, text: devParts(SW.t("devices_readers_once")) })], true)); } finally { devMaking = false; } } });
  name._control.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); if (!e.repeat) make.click(); } });
  const rows = R.list.map((t) => {
    const at = boxFor("reader:" + t.id);
    return devRow(t.id, at, 4,
      devCell("title", 1, null, h("span", { class: "devices__name", textContent: t.name })),
      devCell("id", 2, SW.t("devices_readers_col_id"), h("span", { class: "mono", textContent: t.id })),
      devCell("made", 3, SW.t("devices_readers_col_made"), String(t.created || "").replace("T", " ").slice(0, 16)),
      devCell("actions", 1, null, h("div", { class: "actions" }, SW.btn(SW.t("devices_readers_revoke"), { cls: "btn--ghost", name: SW.t("devices_readers_revoke_named", { id: t.id }), action: "revoke-token",
        run: () => asking(at, `readers/${encodeURIComponent(t.id)}/revoke`, destroy("devices_revoke_token_title", "devices_revoke_token_body", "devices_revoke_token_confirm", { id: t.id }),
          undefined, () => say(at, SW.t("devices_token_revoked", { id: t.id }), true)) }))));
  });
  return card(SW.t("devices_readers_title"),
    R.error ? h("p", {}, SW.status("failed", { text: hubText(R.error) })) : null,
    R.list.length ? devTable("coll--readers", SW.t("devices_readers_title"), [devHead("title", SW.t("common_field_name")), devHead("id", SW.t("devices_readers_col_id"), 2),
      devHead("made", SW.t("devices_readers_col_made"), 3), devActionsHead()], rows)
      : R.error ? null : h("div", {}, h("p", { class: "muted", textContent: SW.t("devices_readers_empty") }),
        h("a", { class: "btn", href: "#flash", textContent: SW.t("nav_flash_device") })),
    h("div", { class: "row devices__make" }, name, make), box,
    h("p", { class: "muted" }, SW.t("devices_readers_pointer"), " ", h("a", { href: "#flash", textContent: SW.t("nav_flash_device") })));
}
