// Service worker: keeps the page shell for offline start (04 10.2) and shows the Hub's alerts (every alert type, R80 section 4)
// when the server has web.push on. Served whether or not alerts are on. Never caches <app path>/api/ replies.
"use strict";
const VERSION = "__VERSION__";   // the server writes its version here when it serves this file
const CACHE = "fk-shell-" + VERSION;
// the web app's address as this worker sees it: its scope is the app's path (/intake/, or under the public path)
const BASE = new URL(self.registration.scope).pathname.replace(/\/+$/, "");
const SHELL = [BASE, ...["app.css", "app.js", "printers.js", "icon.png", "icon-512.png", "manifest-light.webmanifest",
  "manifest-dark.webmanifest", "shared/theme-init.js", "shared/tokens.css", "shared/components.css", "shared/strings.js",
  "shared/components.js", "shared/alerts.js", "shared/alerts.css", "shared/sprite.svg"].map((f) => BASE + "/" + f)];
self.addEventListener("install", (event) => {
  // a file the Hub does not serve (printers.js without the Printers tab) is skipped, not fatal; so is an answer that was
  // redirected (to the sign-in page): it is not the shell
  event.waitUntil(caches.open(CACHE).then((c) => Promise.all(SHELL.map((u) => fetch(u).then((resp) => (resp.ok && !resp.redirected ? c.put(u, resp) : null)).catch(() => null)))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith("fk-shell-") && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (event) => {
  const r = event.request, u = new URL(r.url);
  if (r.method !== "GET" || u.origin !== self.location.origin || !SHELL.includes(u.pathname)) return;
  // network first, the copy when the Hub does not answer
  event.respondWith(fetch(r).then((resp) => {
    // only the page itself: an answer redirected (to the sign-in page) is not the shell
    if (resp.ok && !resp.redirected) { const copy = resp.clone(); caches.open(CACHE).then((c) => c.put(u.pathname, copy)); }
    return resp;
  }).catch(() => caches.match(u.pathname).then((hit) => hit || Response.error())));
});
self.addEventListener("push", (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (e) { d = {}; }
  // one notification per alert (R80 section 4): the Hub builds the title and the line, names the place that fixes it in `url`, and tags a
  // lasting condition by its key so it is shown once; an older Hub's print alert has the same fields
  event.waitUntil(self.registration.showNotification(d.title || "Alert", { body: d.body || "", tag: d.tag || d.kind || "alert", data: { url: d.url || "./" } }));
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || "./", self.location.origin).href;
  // an open window is taken to the place that fixes the alert (the page's own address, so a window of another site is never moved), else one opens
  event.waitUntil(self.clients.matchAll({ type: "window" }).then((all) => {
    for (const c of all) {
      if (!("focus" in c) || new URL(c.url).origin !== self.location.origin) continue;
      return url.startsWith(self.location.origin + BASE) && c.navigate ? c.navigate(url).catch(() => c).then((w) => (w || c).focus()) : c.focus();
    }
    return self.clients.openWindow(url);
  }));
});
