// The Hub page's alerts, shared parts (03 2.8): the texts of the alert places (a stub table until the string catalogue holds
// them, as web-shared/alerts.js does) and the banner host, mounted once in the page frame. Loaded after setup.js. The banners,
// the toast with Show, the Alerts list and the browser notifications are SW_ALERTS (web-shared/alerts.js); nothing here writes
// to the Hub. Everything from the Hub goes in through textContent, as in setup.js.
"use strict";

// ----- texts: the stub table (key -> English), replaced by the catalogue's own text once it has the key -----
// {product} is the product's name. A key the catalogue has wins; these are the few it does not have (the server step added the rest).
const AX_STUB = {
  alerts_notify_on: "Notifications are on in this browser.",
  alerts_notify_off: "Notifications are off in this browser.",
  alerts_low_foot: "Spools at or under {grams} g that are opened.",
  alerts_low_foot_link: "Change it in Settings",
  alerts_low_error: "Could not read what is running low.",
  alerts_storage_free: "{free} free of {total} ({percent} % used)",
  alerts_storage_empty: "Nothing to show.",
};
const axPlural = new Intl.PluralRules("en");
function axt(key, vars) {
  const fixed = { product: SW.t("app_name"), ...vars };
  if (window.SW_TEXT && window.SW_TEXT[key] != null) return SW.t(key, fixed);
  let v = AX_STUB[key];
  if (v == null) return key;
  if (typeof v === "object") v = v[axPlural.select(fixed.count != null ? Number(fixed.count) : 0)] || v.other;
  return v.replace(/\{([a-z][a-z0-9_]*)\}/g, (m, n) => (fixed[n] != null ? String(fixed[n]) : m));
}
// a size from bytes, as the Hub writes it (alerts_api.size_text)
const axSize = (n) => {
  const v = Number(n);
  if (!Number.isFinite(v)) return String(n);
  for (const [unit, step] of [["TB", 1e12], ["GB", 1e9], ["MB", 1e6], ["kB", 1e3]]) if (v >= step) { const x = v / step; return (x >= 10 || step < 1e9 ? x.toFixed(0) : x.toFixed(1)) + " " + unit; }
  return v.toFixed(0) + " B";
};

// ----- the banner host (03 2.8): mounted once, above the page header and below the "cannot reach the Hub" banner -----
// An alert's action goes to the page's own addresses (03 1.2): a printer's row by its key, the two places of Overview, Devices.
const AX_HREF = { "storage-use": "#overview/storage-use", storage: "#overview/storage-use", "running-low": "#overview/running-low", devices: "#devices" };
const alertHref = (a) => (a.place === "printer" ? "#printers" + (a.id ? "/" + encodeURIComponent(a.id) : "") : AX_HREF[a.place] || null);
let alertsHost = null;
// `main`: the page's main area. Resolves with the first poll; without the shared alerts script nothing is mounted.
function mountAlerts(main) {
  if (!window.SW_ALERTS || alertsHost) return null;
  alertsHost = h("div", { class: "alert-host" });
  main.prepend(alertsHost);
  // the page's own api(): a refusal or a missing route is a quiet no-alerts; the Hub-not-answering banner stays the page's
  const first = SW_ALERTS.start({ host: alertsHost, interval: 10000, href: alertHref, api: (path) => api(path), onError: () => {} });
  // a tab that is shown again reads at once (03 2.7); the poll itself keeps its rhythm while hidden, as alerts.js runs it
  document.addEventListener("visibilitychange", () => { if (!document.hidden) SW_ALERTS.poll(); });
  return first;
}
