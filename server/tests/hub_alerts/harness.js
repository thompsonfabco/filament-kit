// The page-side stand-in of the later mount (EA6 phase B), for the tests only: it registers what phase B registers in the registry
// files, so the new modules run inside the real Hub page. Nothing here is shipped.
(() => {
  const q = new URLSearchParams(location.search), notif = q.get("notif");
  // the browser's notifications: "none" = unsupported; "granted" | "denied" | "default" (asks: answers window.__notifAnswer)
  window.__notes = [];
  if (notif === "none") Object.defineProperty(window, "Notification", { value: undefined, configurable: true });
  else if (notif) {
    window.__notifAnswer = "granted";
    class Fake {
      constructor(title, o) { window.__notes.push({ title, body: o && o.body, tag: o && o.tag }); this.close = () => {}; }
      static get permission() { return window.__perm; }
      static async requestPermission() { window.__perm = window.__notifAnswer; return window.__perm; }
    }
    window.__perm = notif;
    Object.defineProperty(window, "Notification", { value: Fake, configurable: true });
  }
  // Settings: the Alerts group is the fourth, read by its own route, and the phone list says its state
  SET_GROUPS.splice(3, 0, ALERTS_GROUP);
  SET_KEY.alerts = ALERTS_GROUP[1];
  SET_ICON.alerts = ALERTS_GROUP[2];
  ALERTS_GROUP[3] = () => alertsGroup({ al: setSeen.al });
  const loadGroup0 = loadGroup;
  loadGroup = async (id, o) => {
    if (id === "alerts") { try { setSeen.al = await loadAlerts(); } catch (e) { setSeen.al = null; } }
    return loadGroup0(id, o);
  };
  const listState0 = listState;
  listState = (id) => (id === "alerts" ? (setSeen.al ? alertsState(setSeen.al) : "") : listState0(id));
  // Overview: the Running low card between Still to do and the tiles, and the Storage row with its fix
  const overview0 = overviewTab;
  overviewTab = () => { const parts = overview0(); parts.splice(2, 0, ovLowCard()); return parts; };
  const api0 = api;
  api = async (path, body) => {
    const r = await api0(path, body);
    if (path === "overview" && r.rows) r.rows = [...r.rows, ...(await ovStorageRows())];
    return r;
  };
  const fix0 = fixCell;
  fixCell = (r) => (r.action === "storage_use" ? ovStorageFix() : fix0(r));
  // the catalogue's own key for the group name (the stub table holds it until the string step adds it)
  document.addEventListener("DOMContentLoaded", () => {
    window.SW_TEXT = Object.freeze({ ...window.SW_TEXT, settings_group_alerts: AX_STUB.settings_group_alerts });
  });
})();
