// Service worker: keeps the page shell for offline start (04 10.2) and handles Printers tab alerts when the server has
// web.push on. Served whether or not print alerts are on. Never caches /intake/api/ replies.
"use strict";
const VERSION = "__VERSION__";   // the server writes its version here when it serves this file
const CACHE = "fk-shell-" + VERSION;
const SHELL = ["/intake", "/intake/app.css", "/intake/app.js", "/intake/printers.js", "/intake/icon.png",
  "/intake/icon-512.png", "/intake/manifest-light.webmanifest", "/intake/manifest-dark.webmanifest",
  "/intake/shared/theme-init.js", "/intake/shared/tokens.css", "/intake/shared/components.css",
  "/intake/shared/strings.js", "/intake/shared/components.js", "/intake/shared/sprite.svg"];
self.addEventListener("install", (event) => {
  // a file the Hub does not serve (printers.js without the Printers tab) is skipped, not fatal
  event.waitUntil(caches.open(CACHE).then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => null)))).then(() => self.skipWaiting()));
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
    if (resp.ok) { const copy = resp.clone(); caches.open(CACHE).then((c) => c.put(u.pathname, copy)); }
    return resp;
  }).catch(() => caches.match(u.pathname).then((hit) => hit || Response.error())));
});
self.addEventListener("push", (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (e) { d = {}; }
  event.waitUntil(self.registration.showNotification(d.title || "Printer", { body: d.body || "", tag: d.tag || "printer", data: { url: d.url || "./" } }));
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || "./", self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: "window" }).then((all) => {
    for (const c of all) if ("focus" in c) return c.focus();
    return self.clients.openWindow(url);
  }));
});
