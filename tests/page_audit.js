// Spoolwarden page audit, AUT-5 of docs/design/07-accessibility.md section 15. Paste it into the browser's console
// on a rendered page (the console is not limited by the page's Content-Security-Policy), or inject it from a test
// runner. It returns the list of findings and prints them; window.swPageAudit() runs it again (for example after a
// change of view, so the title check can compare the two views). An empty list is a pass for this view only: run it
// for every view, theme and appearance, at 1280 px and 320 px wide.
(() => {
  "use strict";
  const LANDMARK_NAV = ["Sections", "Settings groups", "Breadcrumb", "More sections", "Pages"];   // SR-3, 02 6.1
  // FRM-4: the attributes of 07 9.1 by field name; a field whose name is not listed is not checked here
  const FIELDS = {
    code: { type: "password", inputmode: "numeric", autocomplete: "off" },
    access_code: { type: "password", autocomplete: "off", autocapitalize: "off", spellcheck: "false" },
    api_key: { type: "password", autocomplete: "off", autocapitalize: "off", spellcheck: "false" },
    token: { type: "password", autocomplete: "off", autocapitalize: "off", spellcheck: "false" },
    passphrase: { type: "password", autocomplete: "new-password", minlength: "12" },
    passphrase_again: { type: "password", autocomplete: "new-password", minlength: "12" },
    address: { type: "text", inputmode: "url", autocomplete: "off", autocapitalize: "off", spellcheck: "false" },
    public_address: { type: "url", inputmode: "url", autocomplete: "off", spellcheck: "false" },
    port: { type: "text", inputmode: "numeric", autocomplete: "off", pattern: "[0-9]*" },
    subnet: { type: "text", autocomplete: "off", autocapitalize: "off", spellcheck: "false" },
    serial: { type: "text", autocomplete: "off", autocapitalize: "characters", spellcheck: "false" },
    name: { type: "text", autocomplete: "off" },
    net_weight: { type: "text", inputmode: "decimal", autocomplete: "off" },
    empty_weight: { type: "text", inputmode: "decimal", autocomplete: "off" },
    density: { type: "text", inputmode: "decimal", autocomplete: "off" },
    price_per_kg: { type: "text", inputmode: "decimal", autocomplete: "off" },
    days: { type: "text", inputmode: "numeric", autocomplete: "off" },
    reads_per_day: { type: "text", inputmode: "numeric", autocomplete: "off" },
    colour: { type: "text", autocomplete: "off", autocapitalize: "off", spellcheck: "false" },
    search: { type: "search", inputmode: "search", autocomplete: "off", enterkeyhint: "search" },
  };
  const FOCUSABLE = "a[href], button, input, select, textarea, summary, [tabindex], [contenteditable=''], [contenteditable=true]";
  const CONTROL = "a[href], button, input, select, textarea, summary, [role=button], [role^=menuitem], [role=switch], [role=tab]";   // pressed

  function audit() {
    const doc = document, out = [];
    const add = (check, el, detail) => out.push({ check, where: el ? path(el) : "page", detail: detail || "" });
    const layer = (el) => el.closest("dialog[open], [role=dialog], [role=alertdialog]");
    const shown = (el) => !!(el.getClientRects().length) && getComputedStyle(el).visibility !== "hidden" && !el.closest("[hidden], [inert]");
    const closedLayer = (el) => { const d = el.closest("dialog"); return d && !d.open; };

    // SR-1 lang, TXT-6 zoom, SR-2 title
    if (!doc.documentElement.getAttribute("lang")) add("lang missing", null);
    const vp = doc.querySelector('meta[name="viewport"]');
    if (vp && /user-scalable\s*=\s*(no|0)|maximum-scale/i.test(vp.content)) add("viewport meta blocks zoom", vp, vp.content);
    if (!doc.title.trim()) add("title empty", null);
    const seen = window.__swAuditTitles = window.__swAuditTitles || {};
    for (const [view, title] of Object.entries(seen)) {
      if (view !== location.hash && title === doc.title) add("title unchanged between views", null, `${view} and ${location.hash}: ${title}`);
    }
    seen[location.hash] = doc.title;

    // SR-4 one h1 outside open layers; SR-5 no skipped heading level
    const h1s = [...doc.querySelectorAll("h1")].filter((h) => shown(h) && !layer(h));
    if (h1s.length !== 1) add("not exactly one h1", null, `${h1s.length} found`);
    const scopes = [doc.body, ...doc.querySelectorAll("dialog[open]")];
    for (const scope of scopes) {
      let last = scope === doc.body ? 0 : 1;
      for (const hd of scope.querySelectorAll("h1, h2, h3, h4, h5, h6")) {
        if (!shown(hd) || (scope === doc.body && layer(hd))) continue;
        const lv = Number(hd.tagName[1]);
        if (last && lv > last + 1) add("heading level skipped", hd, `h${last} then h${lv}`);
        last = lv;
      }
    }

    // SR-3 landmarks: one banner, one main, one Sections navigation, no other navigation; content inside landmarks
    const banners = [...doc.querySelectorAll("header")].filter((h) => !h.closest("main, section, article, aside, nav, dialog"));
    if (banners.length !== 1) add("landmark missing or doubled", null, `${banners.length} top-level header`);
    if (doc.querySelectorAll("main").length !== 1) add("landmark missing or doubled", null, `${doc.querySelectorAll("main").length} main`);
    const navs = [...doc.querySelectorAll("nav")].filter((n) => !closedLayer(n));
    const sections = navs.filter((n) => n.getAttribute("aria-label") === "Sections");
    if (sections.length !== 1) add("landmark missing or doubled", null, `${sections.length} nav "Sections"`);
    for (const n of navs) if (!LANDMARK_NAV.includes(n.getAttribute("aria-label") || "")) add("landmark not allowed", n, `nav "${n.getAttribute("aria-label") || ""}"`);
    for (const el of doc.body.children) {
      if (!shown(el) || el.matches(".skip, .toasts, #announcer, dialog, .sprite, script, header, nav, main, footer, aside, section[aria-label], [role=region][aria-label]")) continue;
      if (el.querySelector("header, nav, main")) continue;   // a wrapper that holds the landmarks
      if (el.textContent.trim()) add("visible content outside a landmark", el);
    }

    // KEY-2 tabindex, SR-6 names, SR-7 names start with the visible text, TGT-1 hit areas
    for (const el of doc.querySelectorAll("[tabindex]")) if (Number(el.getAttribute("tabindex")) > 0) add("tabindex above 0", el);
    for (const el of doc.querySelectorAll(FOCUSABLE)) {
      if (el.matches("[tabindex='-1']:not(a, button, input, select, textarea)") || el.disabled || !shown(el) || closedLayer(el)) continue;
      if (el.matches("input[type=hidden]")) continue;
      const name = accName(el);
      if (!name) add("focusable element without a name", el);
      if (el.matches("button, a[href], [role=button], [role=menuitem], [role=menuitemradio]")) {
        const vis = visibleText(el);
        if (vis && name && !words(name).startsWith(words(vis))) add("name does not start with the visible text", el, `"${name}" / "${vis}"`);
      }
      if (!el.matches(CONTROL) || (el.getAttribute("tabindex") === "-1" && !el.matches("[role^=menuitem]"))) continue;
      const box = hitBox(el);
      if (box && (box.w < 43.5 || box.h < 43.5) && !inlineLink(el)) add("hit area under 44 x 44", el, `${Math.round(box.w)} x ${Math.round(box.h)}`);
    }

    // FRM-1, FRM-2 labels; FRM-4 attributes; no type=number
    for (const f of doc.querySelectorAll("input:not([type=hidden]), select, textarea")) {
      if (closedLayer(f)) continue;
      const labelled = f.labels && f.labels.length || f.getAttribute("aria-labelledby") ||
        (f.matches("[type=radio], [type=checkbox]") && f.closest("fieldset") && f.closest("fieldset").querySelector("legend") && f.labels.length);
      if (!labelled) add("field without a label", f);
      if (f.type === "number") add("field attribute differs from 07 9.1", f, "type=number is not used");
      const want = FIELDS[f.name];
      if (want) for (const [k, v] of Object.entries(want)) {
        const got = k === "type" ? f.getAttribute("type") || "text" : f.getAttribute(k);
        if (got !== v) add("field attribute differs from 07 9.1", f, `${f.name}: ${k}="${got}", wants "${v}"`);
      }
    }

    // SR-27 images, SR-31 drawings
    for (const img of doc.querySelectorAll("img")) {
      if (!img.hasAttribute("alt")) add("img without alt", img);
      else if (/^photo \d+$/i.test(img.alt.trim())) add('img alt is "photo N"', img, img.alt);
    }
    for (const svg of doc.querySelectorAll("svg")) {
      if (svg.closest("[aria-hidden=true]") || svg.matches(".sprite") || svg.closest("symbol")) continue;
      if (svg.getAttribute("role") === "img" && (svg.getAttribute("aria-label") || svg.getAttribute("aria-labelledby"))) continue;
      const ctl = svg.closest("button, a[href], [role=button], [role=img]");
      if (ctl && accName(ctl)) continue;
      add("svg neither hidden nor named", svg);
    }

    // SR-9 disclosures, SR-18 busy regions, SR-12 result slots
    for (const b of doc.querySelectorAll("button[aria-controls], [role=button][aria-controls]")) {
      const t = doc.getElementById(b.getAttribute("aria-controls"));
      if (t && (t.hidden || !shown(t)) && !b.hasAttribute("aria-expanded") && !b.hasAttribute("aria-pressed")) add("disclosure button without aria-expanded", b);
    }
    for (const r of doc.querySelectorAll('[aria-busy="true"]')) if (!r.matches("button")) add("region still aria-busy after load", r);
    for (const r of doc.querySelectorAll(".result")) {
      if (closedLayer(r)) continue;
      if (r.getAttribute("role") !== "status" && !r.closest("[role=status], [aria-live]")) add("result slot without role=status", r);
    }

    // SR-25 cells
    for (const c of doc.querySelectorAll("[role=cell]")) {
      if (closedLayer(c) || c.getAttribute("aria-label") || c.getAttribute("aria-labelledby")) continue;
      const table = c.closest("[role=table], [role=grid]");
      const heads = table ? [...table.querySelectorAll("[role=columnheader]")] : [];
      const col = c.getAttribute("data-col");
      const ok = c.hasAttribute("aria-colspan") ? heads.length > 0 : heads.some((hd) => hd.getAttribute("data-col") === col && accName(hd));
      if (!ok) add("cell with neither a column header nor a label", c, col || "");
    }

    // TXT-3 no sideways page scroll
    const sw = doc.documentElement.scrollWidth;
    if (sw > window.innerWidth + 0.5) add("horizontal page scroll", null, `${sw} px wide at ${window.innerWidth} px`);

    return out;
  }

  // ----- helpers -----
  const norm = (s) => s.replace(/\s+/g, " ").trim().toLowerCase();
  const words = (s) => norm(s.replace(/[…:.,;!?()]/g, " "));   // punctuation is not said
  function text(el) {
    let s = "";
    for (const n of el.childNodes) {
      if (n.nodeType === 3) s += n.textContent;
      else if (n.nodeType === 1) {
        if (n.getAttribute("aria-hidden") === "true" || n.hidden || getComputedStyle(n).display === "none") continue;
        s += n.tagName === "IMG" ? n.alt || "" : text(n);
      }
    }
    return s;
  }
  function accName(el) {
    const by = el.getAttribute("aria-labelledby");
    if (by) return norm(by.split(/\s+/).map((id) => { const r = document.getElementById(id); return r ? text(r) : ""; }).join(" "));
    const lab = el.getAttribute("aria-label");
    if (lab && lab.trim()) return norm(lab);
    if (el.matches("input, select, textarea")) {
      if (el.labels && el.labels.length) return norm([...el.labels].map(text).join(" "));
      return norm(el.getAttribute("title") || el.getAttribute("placeholder") || "");
    }
    if (el.tagName === "IMG") return norm(el.alt || "");
    return norm(text(el) || el.getAttribute("title") || "");
  }
  function visibleText(el) {
    let s = "";
    for (const n of el.childNodes) {
      if (n.nodeType === 3) s += n.textContent;
      else if (n.nodeType === 1 && n.getClientRects().length && !n.matches(".sr, .tooltip, [aria-hidden=true]")) s += visibleText(n);
    }
    return norm(s);
  }
  // the element's box, or the box its ::after hit-area extension draws when that is larger (02-components.md 1.2)
  function hitBox(el) {
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) return null;
    let w = r.width, hgt = r.height;
    const a = getComputedStyle(el, "::after");
    if (a.content && a.content !== "none" && a.position === "absolute") {
      const px = (v) => (v.endsWith("px") ? parseFloat(v) : 0);
      // positioned by the element itself, or by its nearest positioned ancestor (a link covering its row)
      const cb = getComputedStyle(el).position === "static" && el.offsetParent ? el.offsetParent.getBoundingClientRect() : r;
      w = Math.max(w, cb.width - px(a.left) - px(a.right));
      hgt = Math.max(hgt, cb.height - px(a.top) - px(a.bottom));
    }
    const lab = el.matches("input") && el.closest("label");   // a checkbox or switch whose whole row is the hit area
    if (lab) { const lr = lab.getBoundingClientRect(); w = Math.max(w, lr.width); hgt = Math.max(hgt, lr.height); }
    else if (el.matches("input, select, textarea") && el.labels && el.labels.length) {   // a field and its label
      const lr = el.labels[0].getBoundingClientRect();
      hgt = Math.max(hgt, Math.max(r.bottom, lr.bottom) - Math.min(r.top, lr.top));
    }
    if (el.matches(".segmented__input, .theme-picker__input") && el.labels && el.labels[0]) {
      const l = el.labels[0], b = hitBox(l) || { w: 0, h: 0 };
      w = b.w; hgt = b.h;
    }
    return { w, h: hgt };
  }
  const inlineLink = (el) => el.tagName === "A" && getComputedStyle(el).display === "inline" && !el.matches(".coll__title");
  function path(el) {
    const parts = [];
    for (let e = el; e && e.nodeType === 1 && parts.length < 4; e = e.parentElement) {
      let s = e.tagName.toLowerCase();
      if (e.id) { parts.unshift(s + "#" + e.id); break; }
      const cls = (e.getAttribute("class") || "").trim().split(/\s+/).filter(Boolean)[0];
      if (cls) s += "." + cls;
      parts.unshift(s);
    }
    return parts.join(" > ");
  }

  window.swPageAudit = () => {
    const found = audit();
    if (found.length) console.table(found); else console.log("Page audit (AUT-5): no findings for", location.hash || "/");
    return found;
  };
  return window.swPageAudit();
})();
