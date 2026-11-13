// Spoolwarden shared components, the job addition (02-components.md 8.4, 8.5; 03-hub-page.md 3.5 to 3.7): loaded after
// components.js, only by the Hub page (the web app starts no jobs). It adds window.SW_JOBS.create(): the background-job
// strip, the top-bar job indicator, the Hub-is-restarting state and the Hub-not-answering banner. It also fills the
// core's two hooks, waitJob and waitHub. Text from the Hub goes in as textContent, never as markup.
(() => {
"use strict";
const SW = window.SW, { t, h } = SW;
const doc = document, $ = (s, r = doc) => r.querySelector(s), E = (tag, cls, ...kids) => h(tag, { class: cls }, ...kids);
const NAMED = new Set(["backup", "restore", "apply", "update", "rollback", "check", "library_update", "library_rollback", "remote_issue",
  "station_pair", "reader_setup"]);
const RESTARTS = new Set(["apply", "update", "rollback", "restore"]);    // jobs that restart the Hub (8.4, "Error")
const WORD = { running: "status_running", done: "status_done", failed: "status_failed" };
const titleOf = (name) => t(NAMED.has(name) ? "job_title_" + name : "job_title_other");
const clock = (s) => (s < 60 ? t("job_time_seconds", { seconds: s }) : t("job_time_minutes", { minutes: Math.floor(s / 60), seconds: s % 60 }));
const newest = (text) => text.trimEnd().split("\n").pop().replace(/^==> /, "");
// a text with `code` parts (restart_timeout_line) as nodes
const parts = (s) => s.split("`").map((p, i) => (i % 2 ? E("code", "mono", p) : p));
const UPDATED = "sw.updated";

// create({job(from), state(), version(), banners(), wholeLog(box), onEnd(reply, title), onBack()}) -> {strip, chip, follow, restart,
// down, up}. job and state are the page's own requests (they throw an error with `unreachable` or `status`); version() is the
// version the page was loaded with; banners() the element the not-answering banner goes at the top of; wholeLog(box)
// passes the lock and resolves with the whole log's text (null when cancelled); onEnd runs once when a job has ended; onBack
// when the Hub answers again after a restart or after not answering.
function create(o) {
  const say = h("span", { class: "sr", role: "status" });                // the only live part: the start and the end, never a step
  const badge = E("span", "job__badge"), title = E("span", "job__title"), line = E("span", "job__step mono");
  const toggle = h("button", { class: "btn btn--ghost btn--icon job__toggle", type: "button", "aria-expanded": "false", "aria-controls": "job-log",
    "aria-label": t("job_log_show"), on: { click: () => (collapsed() ? open(true) : logShown(!log.hidden)) } }, SW.icon("chevron"));
  const hide = SW.iconBtn("close", t("job_hide"), { run: () => (SW.phone() ? strip.setAttribute("data-collapsed", "") : (strip.hidden = true, chip.setAttribute("aria-expanded", "false"))) });
  const close = SW.iconBtn("close", t("job_close"), { run: () => { strip.hidden = chip.hidden = true; const t1 = $("main h1"); if (t1) t1.focus({ preventScroll: true }); } });
  const lost = E("p", "job__lost", SW.shape("s-triangle"), t("job_lost_touch"));
  const log = h("pre", { class: "job__log", id: "job-log", tabindex: "0", "aria-label": t("job_log_label"), hidden: true });
  const whole = SW.btn(t("job_show_whole_log"), { run: () => wholeLog() }), box = h("div", { class: "result result--block", role: "status" });
  const foot = E("div", "job__foot", whole, E("p", "job__note muted", t("job_hidden_note")), box);
  const lateFoot = h("div", { class: "job__foot", hidden: true }, SW.btn(t("restart_reload"), { run: () => location.reload() }));
  const strip = h("section", { class: "job", id: "job", "aria-label": t("job_label"), hidden: true }, E("div", "job__head", E("div", "job__text", say, badge, " ", title, line), toggle, hide, close),
    lost, log, foot, lateFoot);
  let bar = null, barKey = "";
  const chip = h("button", { class: "chip chip--job", type: "button", "aria-controls": "job", "aria-expanded": "false", hidden: true, on: { click: () => open(true) } });
  const collapsed = () => strip.hasAttribute("data-collapsed");
  const logShown = (on) => { log.hidden = !on; toggle.setAttribute("aria-expanded", String(on)); toggle.setAttribute("aria-label", t("job_log_show")); };
  // the chip, the collapsed bar or a hidden strip opens the strip with the log expanded, focus on the log toggle (2.2)
  function open(focus) {
    strip.hidden = false; strip.removeAttribute("data-collapsed"); chip.setAttribute("aria-expanded", "true"); logShown(true);
    if (focus) toggle.focus();
  }
  const announceLive = (text) => { say.textContent = ""; setTimeout(() => { say.textContent = text; }, 30); };

  // what the strip shows: {st, word, title, line, value, text, lost, ended}; value null is the indeterminate bar
  function paint(v) {
    strip.dataset.state = v.st;
    badge.replaceChildren(SW.status(v.word));
    title.textContent = v.title;
    line.replaceChildren(...(Array.isArray(v.line) ? v.line : [v.line]));
    line.title = line.textContent;
    const key = `${v.value == null}|${v.failed}`;
    if (key !== barKey) {
      const el = SW.progress({ name: t("job_progress_label", { title: v.title }), value: v.value || 0, indeterminate: v.value == null, failed: v.failed, valuetext: v.text });
      bar ? bar.replaceWith(el) : strip.querySelector(".job__head").after(el);
      bar = el; barKey = key;
    } else if (v.value != null) SW.setProgress(bar, v.value, v.text);
    lost.hidden = !v.lost;
    const job = !!v.job;
    hide.hidden = v.st !== "running"; close.hidden = !(job && v.ended);
    toggle.hidden = !job;
    if (!job) logShown(false);
    foot.hidden = !(job && (v.ended || !log.hidden));
    lateFoot.hidden = v.st !== "late";
    SW.disable(whole, v.ended ? null : t("job_log_disabled"));
    // the top-bar indicator mirrors it (only a job's own states, 2.2)
    chip.hidden = !job;
    if (job) {
      chip.dataset.state = v.st;
      chip.setAttribute("aria-label", t("topbar_job_name", { title: v.title, state: t(WORD[v.st] || "status_running").toLocaleLowerCase() }));
      chip.replaceChildren(v.st === "running" ? SW.spinner() : SW.shape(v.st === "failed" ? "s-octagon" : "s-filled"), E("span", "chip__word", v.title));
    }
  }

  // ----- following a job (8.4 "Behaviour") -----
  let from = 0, name = null, live = false, text = "", stepKey = "", stepAt = 0, ended = false, onceEnd = null;
  function view(r) {
    const ttl = titleOf(r.name), failed = !r.running && (r.lost || r.exit !== 0), st = r.running ? "running" : failed ? "failed" : "done";
    const s = r.step, key = s ? "s" + s.index : "n", counted = !!s;
    if (key !== stepKey) { stepKey = key; stepAt = Date.now(); }
    let l = counted ? t("job_step", { step: s.index, total: s.count, text: s.text }) : newest(text);
    const secs = Math.floor((Date.now() - stepAt) / 1000);
    if (r.running && secs >= 10) l = t("job_step_elapsed", { line: l, time: clock(secs) });
    if (!r.running) l = r.lost ? t("job_failed_stopped", { title: ttl }) : failed ? t("job_failed", { title: ttl }) : t("job_done", { title: ttl });
    return { st, word: st, title: ttl, line: l, job: true, ended: !r.running, failed, lost: false,
      value: r.running ? (r.progress == null ? null : r.progress) : (failed ? (r.progress == null ? 1 : r.progress) : 1),
      text: counted ? t("progress_step", { step: s.index, total: s.count }) : null };
  }
  let last = null, restartTimer = 0, banner = null, timer = 0;
  async function tick() {
    let r;
    try { r = await o.job(from); }
    catch (e) {
      // a release without this route answers 404: reload
      if (e.status === 404) { location.reload(); return; }
      if (e.unreachable && name && RESTARTS.has(name)) { restart(null, true); return; }
      if (last) paint({ ...last, lost: true });
      setTimeout(tick, 1000);
      return;
    }
    if (o.version() && r.version !== o.version()) { remember(r.version); location.reload(); return; }   // the new release's own page
    if (r.next < from || (name && r.name && r.name !== name)) {    // another job started over
      from = 0; text = ""; log.textContent = ""; name = r.name; stepKey = "";
      begin(r);
      setTimeout(tick, 200);
      return;
    }
    if (!r.name && !r.running) { live = false; return; }       // no job has run yet
    if (!name) begin(r);
    name = r.name;
    const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
    if (r.text) { text += r.text; log.textContent += r.text; }
    from = r.next;
    if (atEnd) log.scrollTop = log.scrollHeight;
    last = view(r);
    paint(last);
    if (r.running || r.text) { setTimeout(tick, 1000); return; }
    live = false;
    finish(r);
  }
  function begin(r) {
    announceLive(t("job_started", { title: titleOf(r.name) }));
    ended = false;
  }
  function finish(r) {
    if (ended) return;
    ended = true;
    const ttl = titleOf(r.name), ok = !r.lost && r.exit === 0, end = ok ? t("job_done", { title: ttl }) : r.lost ? t("job_failed_stopped", { title: ttl }) : t("job_failed", { title: ttl });
    announceLive(end);
    // the toast repeats the end line for the eye; the strip's status area is what is announced
    const tt = SW.toast(ok ? end : t("job_failed_toast", { title: ttl }), ok ? "ok" : "bad");
    tt.setAttribute("aria-hidden", "true");
    if (o.onEnd) o.onEnd(r, ttl);
    if (onceEnd) { const f = onceEnd; onceEnd = null; f({ state: ok ? "done" : "failed" }); }
  }
  // follow(fresh): fresh starts a log from the top (a job just started)
  function follow(fresh) {
    if (fresh) { from = 0; name = null; text = ""; log.textContent = ""; stepKey = ""; ended = false; last = null; }
    if (fresh) { strip.hidden = false; strip.removeAttribute("data-collapsed"); }
    if (live) return;
    live = true;
    tick();
  }

  // ----- the Hub is restarting (8.5) -----
  const shellEl = () => $(".shell");
  let held = [];
  const reason = h("span", { class: "sr", id: "restart-reason", text: t("common_wait_hub_back") });
  function writes(off) {
    for (const b of held) { b.removeAttribute("aria-disabled"); b.removeAttribute("aria-describedby"); b._refused = null; }
    held = [];
    if (!off) { reason.remove(); return; }
    strip.append(reason);
    for (const b of doc.querySelectorAll("main button:not([aria-disabled])")) {
      b.setAttribute("aria-disabled", "true"); b.setAttribute("aria-describedby", reason.id); b._refused = () => SW.announce(t("common_wait_hub_back"));
      held.push(b);
    }
  }
  let backs = [];
  // restart(done, fromJob): the Hub restarts (a save replied `restarts`, or the job poll failed during a job that restarts it).
  // done runs when it answers again.
  function restart(done, fromJob) {
    if (done) backs.push(done);
    if (restartTimer) return;
    if (banner) { banner.remove(); banner = null; clearInterval(timer); }       // the failed request that led here said "cannot reach" first
    if (fromJob) live = false;
    const since = Date.now(), shown = strip.dataset.state === "running";
    const sh = shellEl();
    if (sh) sh.dataset.state = "restarting";
    writes(true);
    paint({ st: "restarting", word: "running", title: t("restart_title"), line: t("restart_line"), value: null, job: false });
    strip.hidden = false; chip.hidden = false;
    chip.dataset.state = "restarting";
    chip.setAttribute("aria-label", t("topbar_job_name", { title: t("restart_title"), state: t("status_running").toLocaleLowerCase() }));
    chip.replaceChildren(SW.spinner(), E("span", "chip__word", t("restart_title")));
    announceLive(t("restart_title") + ". " + t("restart_line"));
    let lateShown = false;
    const ask = async () => {
      let r = null;
      try { r = await o.state(); } catch (e) { /* no answer yet */ }
      if (!r) {
        if (!lateShown && Date.now() - since > 120000) {
          lateShown = true;
          paint({ st: "late", word: "needs_look", title: t("restart_timeout_title"), line: parts(t("restart_timeout_line")), value: null, job: false });
        }
        restartTimer = setTimeout(ask, 2000);
        return;
      }
      restartTimer = 0;
      if (r.version !== o.version()) { remember(r.version); location.reload(); return; }   // the new files, then the toast
      back(shown || fromJob);
    };
    restartTimer = setTimeout(ask, 2000);
  }
  function back(wasJob) {
    const sh = shellEl();
    if (sh) sh.removeAttribute("data-state");
    writes(false);
    paint({ st: "done", word: "done", title: t("restart_back"), line: "", value: 1, job: false, ended: true });
    chip.hidden = true;
    announceLive(t("restart_back"));
    for (const f of backs.splice(0)) f();
    if (o.onBack) o.onBack();
    // the strip hides after 5 s unless a job is shown again
    if (wasJob && name && !ended) { live = true; tick(); }
    setTimeout(() => { if (strip.dataset.state === "done" && title.textContent === t("restart_back")) strip.hidden = true; }, 5000);
  }
  // after a reload for a new version: "Spoolwarden is now 0.6.0." (and that the code is asked again)
  function remember(version) {
    try { sessionStorage.setItem(UPDATED, JSON.stringify({ version, locked: SW.lock.state === "unlocked" })); } catch (e) { /* no storage: no toast */ }
  }
  try {
    const kept = JSON.parse(sessionStorage.getItem(UPDATED) || "null");
    sessionStorage.removeItem(UPDATED);
    if (kept) setTimeout(() => SW.toast(t(kept.locked ? "restart_updated_locked" : "restart_updated", { version: kept.version })), 300);
  } catch (e) { /* nothing kept */ }

  // ----- the whole log (8.4 "Behaviour" 5) -----
  async function wholeLog() {
    if (whole.getAttribute("aria-disabled") === "true") return;
    SW.busy(whole, t("common_working"));
    try {
      const all = await o.wholeLog(box);
      if (all != null) { log.textContent = all; text = all; logShown(true); log.scrollTop = log.scrollHeight; }
    } finally { SW.idle(whole); }
  }

  // ----- the Hub is not answering (03 3.7) -----
  const probe = async () => { try { await o.state(); } catch (e) { /* still down */ } };
  function down() {
    const host = o.banners && o.banners();
    if (banner || restartTimer || !host) return;
    const try1 = SW.btn(t("common_try_now"), { run: async (e) => { const b = e.currentTarget; SW.busy(b, t("common_trying")); await probe(); SW.idle(b); } });
    banner = SW.banner({ kind: "bad", text: t("common_banner_unreachable"), actions: [try1], late: true });
    host.prepend(banner);
    timer = setInterval(probe, 10000);
  }
  function up() {
    if (!banner) return;
    banner.remove(); banner = null; clearInterval(timer);
    if (o.onBack) o.onBack();
  }

  SW.configure({
    waitJob: () => new Promise((res) => { onceEnd = res; follow(true); }),
    waitHub: () => new Promise((res) => restart(res)), down, up,
  });
  return { strip, chip, follow, restart, down, up };
}
window.SW_JOBS = Object.freeze({ create });
})();
