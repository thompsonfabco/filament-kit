// Service worker for Printers tab alerts (served only when the server has web.push on).
"use strict";
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
