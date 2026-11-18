// The Hub page's alerts, shared parts (03 2.8): the texts of the alert places (a stub table until the string catalogue holds
// them, as web-shared/alerts.js does) and the banner host, mounted once in the page frame. Loaded after setup.js. The banners,
// the toast with Show, the Alerts list and the browser notifications are SW_ALERTS (web-shared/alerts.js); nothing here writes
// to the Hub. Everything from the Hub goes in through textContent, as in setup.js.
"use strict";

// ----- texts: the stub table (key -> English), replaced by the catalogue's own text once it has the key -----
// {product} is the product's name. A key the catalogue already has wins. Only the server step that opens strings/ adds these keys.
const AX_STUB = {
  settings_group_alerts: "Alerts",
  alerts_settings_desc: "What {product} warns you about, and where.",
  alerts_settings_save: "Save alerts",
  alerts_settings_state: "{count} of 8 on",
  alerts_type_runout: "Filament ran out",
  alerts_type_paused: "Print paused",
  alerts_type_failed: "Print failed or stopped",
  alerts_type_printer_error: "Printer error",
  alerts_type_finished: "Print finished",
  alerts_type_storage: "Storage almost full",
  alerts_type_running_low: "Spool running low",
  alerts_type_device_down: "Device stopped answering",
  alerts_type_device_down_hint: "A Weigh Station or a printer stopped answering.",
  alerts_last_spool_only: "Only when it is the last spool of that filament",
  alerts_running_low_g: "Running low under",
  alerts_running_low_hint: "Opened spools at or under this are listed as running low.",
  alerts_storage_warn: "Storage warning at",
  alerts_storage_warn_hint: "The Hub treats {bad} % used, and always less than 1 GB free, as bad.",
  alerts_unit_g: "g",
  alerts_unit_used: "% used",
  alerts_error_range: "Enter a whole number from {min} to {max}.",
  alerts_device_heading: "On this device",
  alerts_notify_label: "Notifications in this browser",
  alerts_notify_hint: "Shown while a {product} tab is open in this browser. With the tab in the background they can arrive up to a minute late.",
  alerts_notify_on: "Notifications are on in this browser.",
  alerts_notify_off: "Notifications are off in this browser.",
  alerts_test_button: "Send a test alert",
  alerts_test_sent: "Test alert sent. It arrives here in a moment.",
  alerts_recent: "Recent alerts",
  alerts_low_title: "Running low",
  alerts_low_show_all: "Show all {count}",
  alerts_low_more: { one: "{count} more in stock", other: "{count} more in stock" },
  alerts_low_last: "Last one",
  alerts_low_foot: "Spools at or under {grams} g that are opened.",
  alerts_low_foot_link: "Change it in Settings",
  alerts_low_error: "Could not read what is running low.",
  alerts_storage_row: "Storage: {free} free of {total} ({percent} % used)",
  alerts_storage_row_named: "Storage, {place}: {free} free of {total} ({percent} % used)",
  alerts_storage_show: "Show storage use",
  alerts_storage_title: "Storage use",
  alerts_storage_free: "{free} free of {total} ({percent} % used)",
  alerts_storage_error: "Could not read the storage use.",
  alerts_storage_open_backups: "Open Backups",
  alerts_storage_photos_where: { one: "Recently added keeps the last {count}.", other: "Recently added keeps the last {count}." },
  alerts_storage_reader_where: "Settings > Label Reader",
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
// a size from bytes, as the alert texts of web-shared/alerts.js write it
const axSize = (n) => (typeof n === "number" ? (n >= 1e9 ? (n / 1e9).toFixed(1) + " GB" : n >= 1e6 ? Math.round(n / 1e6) + " MB" : Math.round(n / 1e3) + " kB") : String(n));

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
