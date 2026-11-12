# /// script
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.orcaslicer.plugin]
# name = "Spool Sync"
# description = "Selects the filament presets for the spools loaded on a Klipper printer, one per filament slot. Use the Spool Sync tab (or its Dock button, which pins a Sync button beside the 3D view) and press Sync. It asks the active printer preset's Moonraker host for the active Spoolman spool, picks the compatible filament preset whose notes list that Spoolman filament id, else the one with the same vendor and type for each slot (filament name words break ties, your own presets beat system ones). The spool colour is shown beside the button; Orca's plugin API cannot set slot colours yet. If several presets tie, pick one by hand and Sync again: it keeps your pick and remembers it for that Spoolman filament. Multi-tool printers: the slots come from Moonraker's lane_data (published by filament-kit's Klipper bridge, or AFC); a single-tool printer syncs slot 1 from the active spool. On load it asks for network access to the active printer preset's print host plus any hosts listed in hosts.txt in the plugin's storage folder, and for a background thread. Needs Moonraker's [spoolman] section and Orca with the preset plugin API (nightly after 2026-10-23)."
# author = "filament-kit"
# version = "2.0.0"
# ///
"""Select each filament slot's preset from the spools loaded on the printer (filament-kit integration).

  printer preset print_host --> Moonraker lane_data (laneN: lane, spool_id, preset ...)   multi-tool printers
                            --> else Moonraker /server/spoolman/spool_id                 slot 1
                            --> Moonraker /server/spoolman/proxy (GET /v1/spool/<id>)
  the lane's published preset (when Orca has it), else Spoolman vendor + material + name --> best compatible
  filament preset --> begin_update(slot, name)

Buttons: the "Spool Sync" page tab (always present), an optional dock panel beside
the 3D view opened from that tab, and the "Sync filament from printer" script in
the Plugins dialog. Page and panel handlers run on the UI thread, so a sync runs
on its own thread: begin_update() hands the selection to the UI thread and
blocks only that thread, and HTTP never stalls the UI.

Matching, per compatible and visible filament preset:
  ids     filament_notes line "Spoolman filament ids: 1, 13, 14" naming this spool's
          filament (one preset per brand + product line, printer and nozzle) wins outright
  type    filament_type equal to the Spoolman material (or one contains the other)
  vendor  filament_vendor equal to / containing the Spoolman vendor
  score   exact type 3 / partial 1, +1 per Spoolman filament-name word in the
          preset name, +0.5 for user presets
Order: a preset listing this Spoolman filament id, then a remembered pick, then the unique top score.
On a tie the slot's current preset wins if it is one of the tied presets (and is
remembered); otherwise the sync fails and lists them. With no vendor match it
falls back to the Generic preset of that type and says so (never remembered).
"""

import json
import os
import re
import threading
import urllib.error
import urllib.request

import orca

SLOT = 1
TIMEOUT = 5
KLIPPER_HOST_TYPES = ("moonraker", "klipper")
# Orca's sandbox blocks network calls a plugin did not request at load; one grant covers a host. The hosts are the
# active printer preset's print host plus the lines of hosts.txt in the plugin's storage folder (one URL per line,
# e.g. http://printer.home.arpa), so a printer you switch to later can be listed there.
HOSTS_FILE = "hosts.txt"
# The slot colour lives in Orca's project config, which plugins cannot write (the preset API
# rejects "filament_colour"), so the spool colour is only shown next to the Sync button.

_sync_lock = threading.Lock()


def norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def first_value(serialized):
    """First element of a serialized config vector: '"Bambu Lab";"Generic"' -> 'Bambu Lab'."""
    if serialized is None:
        return ""
    value = str(serialized).split(";")[0].strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value.strip()


def related(a, b):
    a, b = norm(a), norm(b)
    return bool(a and b) and (a == b or a in b or b in a)


# ---- printer side ----------------------------------------------------------

def moonraker_url(printer):
    host_type = first_value(printer.config_value("host_type")).lower()
    if host_type and host_type not in KLIPPER_HOST_TYPES:
        raise RuntimeError(f"the printer preset uses host type '{host_type}', not Moonraker")
    host = first_value(printer.config_value("print_host"))
    if not host:
        raise RuntimeError("the printer preset has no print host set (Printer settings > connection)")
    if not re.match(r"^https?://", host):
        host = "http://" + host
    return host.rstrip("/")


def http_json(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                               "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def active_spool(base):
    spool_id = http_json(base + "/server/spoolman/spool_id")["result"]["spool_id"]
    if not spool_id:
        return None
    return spool_by_id(base, spool_id)


def lane_data(base):
    """Moonraker's lane_data namespace ({"lane0": {...}}), or None when the printer has none."""
    try:
        reply = http_json(base + "/server/database/item?namespace=lane_data")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    value = (reply.get("result") or {}).get("value")
    return value if isinstance(value, dict) and value else None


def lanes_to_slots(lanes, slot_count):
    """{slot (1-based): lane dict} for lanes whose `lane` index fits the slots Orca shows."""
    out = {}
    for key, lane in sorted((lanes or {}).items()):
        if not isinstance(lane, dict):
            continue
        try:
            n = int(lane.get("lane", re.sub(r"\D", "", key) or -1))
        except (TypeError, ValueError):
            continue
        if 0 <= n < slot_count:
            out[n + 1] = lane
    return out


def spool_by_id(base, spool_id):
    reply = http_json(base + "/server/spoolman/proxy",
                      {"request_method": "GET", "path": f"/v1/spool/{spool_id}", "use_v2_response": True})
    result = reply["result"]
    if result.get("error"):
        raise RuntimeError(f"Spoolman: {result['error']}")
    spool = result["response"]
    filament = spool.get("filament") or {}
    colour = filament.get("color_hex") or (filament.get("multi_color_hexes") or "").split(",")[0]
    return {
        "id": spool_id,
        "filament_id": filament.get("id"),
        "vendor": (filament.get("vendor") or {}).get("name") or "",
        "material": filament.get("material") or "",
        "name": filament.get("name") or "",
        "colour": f"#{colour[:6].upper()}" if re.fullmatch(r"[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", colour or "") else "",
    }


def describe(spool):
    return f"spool {spool['id']} ({spool['vendor']} {spool['material']} {spool['name']})".replace("  ", " ")


# ---- preset matching -------------------------------------------------------

def candidates(bundle):
    """Filament presets the slot dropdown can offer for the current printer."""
    found = []
    for name in bundle.filaments.preset_names():
        preset = bundle.filaments.find_preset(name)
        if preset is None or preset.is_default or not preset.is_visible or not preset.is_compatible:
            continue
        found.append({
            "name": preset.name,
            "label": preset.label() or preset.name,
            "vendor": first_value(preset.config_value("filament_vendor")),
            "type": first_value(preset.config_value("filament_type")),
            "is_user": preset.is_user(),
            "spoolman_ids": spoolman_ids(preset.config_value("filament_notes")),
        })
    return found


def spoolman_ids(notes):
    """Spoolman filament ids a preset claims in its notes: 'Spoolman filament ids: 1, 13' -> {1, 13}."""
    found = re.search(r"Spoolman filament ids?:\s*([\d,\s]+)", str(notes or ""))
    return {int(n) for n in re.findall(r"\d+", found.group(1))} if found else set()


def score(preset, spool):
    if norm(preset["type"]) == norm(spool["material"]):
        total = 3.0
    elif related(preset["type"], spool["material"]):
        total = 1.0
    else:
        return None
    label = norm(preset["label"])
    skip = {norm(spool["vendor"]), norm(spool["material"])}
    for word in re.split(r"[\s\-_/+]+", spool["name"]):
        if len(norm(word)) >= 2 and norm(word) not in skip and norm(word) in label:
            total += 1
    if preset["is_user"]:
        total += 0.5
    return total


def choose(presets, spool, current, remembered, slot=SLOT, published=None):
    """Return (preset name, how it was chosen); raise with the candidates on a tie."""
    if published and published in {p["name"] for p in presets}:
        return published, "preset filament-kit published"
    listed = [p for p in presets if spool["filament_id"] in p["spoolman_ids"]]
    if len(listed) == 1:
        return listed[0]["name"], "Spoolman filament id in preset notes"
    names = {p["name"] for p in presets}
    if remembered in names:
        return remembered, "remembered pick"

    if listed:       # two or more presets list this filament id: the pick is among them, as the module notes say
        presets = listed

    vendor_matches = [p for p in presets if related(p["vendor"], spool["vendor"])]
    pool, how = vendor_matches, "vendor + type"
    if not vendor_matches:
        # Another brand's tuned preset is a worse guess than Orca's generic one.
        generic = [p for p in presets if norm(p["vendor"]) == "generic" or p["name"].startswith("Generic ")]
        pool = generic or presets
        how = f"no {spool['vendor'] or 'vendor'} preset, used {'generic' if generic else 'any'} {spool['material']}"
    scored = [(score(p, spool), p) for p in pool]
    scored = [(s, p) for s, p in scored if s is not None]
    if not scored:
        raise LookupError(f"no compatible {spool['material']} filament preset for this printer")

    best = max(s for s, _ in scored)
    top = [p for s, p in scored if s == best]
    if len(top) == 1:
        return top[0]["name"], how
    if current in {p["name"] for p in top}:
        return current, how + ", tie kept current"
    listed = ", ".join(sorted(p["label"] for p in top))
    raise LookupError(f"{len(top)} presets match equally ({listed}). Select one for slot {slot} "
                      "by hand and Sync again to remember it")


# ---- remembered picks ------------------------------------------------------

def picks_path():
    path = orca.host.plugin.storage()
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, "picks.json")


def load_picks():
    try:
        with open(picks_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_pick(filament_id, preset_name):
    picks = load_picks()
    picks[str(filament_id)] = preset_name
    with open(picks_path(), "w", encoding="utf-8") as fh:
        json.dump(picks, fh, indent=2)


# ---- the sync itself -------------------------------------------------------

def loaded_spool():
    """(spool or None, text) for the status line; never raises."""
    try:
        spool = active_spool(moonraker_url(orca.host.preset_bundle().current_printer_preset()))
    except Exception as exc:
        return None, f"Printer not reachable: {type(exc).__name__}: {exc}"
    if spool is None:
        return None, "No active spool on the printer"
    return spool, f"Loaded: {describe(spool)}" + (f" {spool['colour']}" if spool["colour"] else "")


def sync_slot(bundle, slot, spool, current_names, published=None):
    """Select one slot's preset; returns the message line. Raises LookupError on a tie / no match."""
    current = current_names[slot - 1] if len(current_names) >= slot else ""
    remembered = load_picks().get(str(spool["filament_id"]))
    name, how = choose(candidates(bundle), spool, current, remembered, slot, published)
    if how == "vendor + type, tie kept current" and spool["filament_id"] is not None:
        save_pick(spool["filament_id"], name)
    # Selecting the preset is all begin_update() needs to do; nothing is staged or committed.
    orca.host.preset.filament.begin_update(slot, name)
    verb = "kept" if name == current else "selected"
    colour = f" - spool colour {spool['colour']}" if spool["colour"] else ""
    return f"Slot {slot}: {verb} \"{name}\" for {describe(spool)} - {how}{colour}"


def run_sync():
    """Do one sync off the UI thread. Returns (ok, message)."""
    if not _sync_lock.acquire(blocking=False):
        return False, "A sync is already running"
    try:
        bundle = orca.host.preset_bundle()
        base = moonraker_url(bundle.current_printer_preset())
        current_names = list(bundle.current_filament_preset_names())
        lanes = lane_data(base)
        if lanes:
            by_slot = lanes_to_slots(lanes, max(len(current_names), 1))
            lines, ok = [], True
            for slot, lane in sorted(by_slot.items()):
                sid = lane.get("spool_id")
                if not isinstance(sid, int) or sid <= 0:
                    lines.append(f"Slot {slot}: no spool")
                    continue
                try:
                    lines.append(sync_slot(bundle, slot, spool_by_id(base, sid), current_names,
                                           lane.get("preset")))
                except LookupError as exc:
                    ok = False
                    lines.append(f"Slot {slot}: {exc}")
            if not lines:
                return False, "lane_data lists no slot this printer preset has"
            return ok, "\n".join(lines)
        spool = active_spool(base)
        if spool is None:
            return False, "No active spool on the printer - scan the spool tag or pick it in Mainsail"
        return True, sync_slot(bundle, SLOT, spool, current_names)
    except LookupError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        _sync_lock.release()


def printer_hosts():
    """The hosts to ask network access for: the active printer preset's print host and hosts.txt's lines."""
    hosts = []
    try:
        hosts.append(moonraker_url(orca.host.preset_bundle().current_printer_preset()))
    except Exception:
        pass
    try:
        with open(os.path.join(orca.host.plugin.storage(), HOSTS_FILE), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    hosts.append(line if re.match(r"^https?://", line) else "http://" + line)
    except OSError:
        pass
    return sorted(set(h.rstrip("/") for h in hosts))


def in_background(work, post):
    """Run work() on a thread and post its {type, ...} result back to a page."""
    def runner():
        try:
            post(work())
        except Exception as exc:  # posting can fail if the page closed meanwhile
            print(f"[spool-sync] {type(exc).__name__}: {exc}")
    threading.Thread(target=runner, name="spool-sync", daemon=True).start()


def sync_message():
    ok, text = run_sync()
    return {"type": "result", "ok": ok, "text": text}


def state_message():
    spool, text = loaded_spool()
    return {"type": "state", "text": text, "colour": spool["colour"] if spool else ""}


# ---- UI --------------------------------------------------------------------

STYLE = """
<style>
  body { margin: 0; padding: 14px; font-size: 13px; }
  h3 { margin: 0 0 6px; font-size: 15px; }
  .row { display: flex; align-items: center; gap: 8px; margin: 8px 0; flex-wrap: wrap; }
  button.big { font-size: 14px; padding: 8px 16px; }
  .chip { width: 14px; height: 14px; border-radius: 3px; border: 1px solid var(--orca-border); display: none; }
  .muted { color: var(--orca-muted); font-size: 12px; }
  .err { color: #d9534f; }
  .ok { color: #2e9e5b; }
</style>
"""

SCRIPT = """
<script>
(function () {
  var $ = function (id) { return document.getElementById(id); };
  orca.onMessage(function (m) {
    if (!m) return;
    if (m.type === "state") {
      $("loaded").textContent = m.text;
      $("chip").style.display = m.colour ? "inline-block" : "none";
      $("chip").style.background = m.colour || "transparent";
    }
    if (m.type === "result") {
      $("sync").disabled = false;
      $("result").textContent = m.text;
      $("result").className = m.ok ? "ok" : "err";
      orca.postMessage({ type: "state" });
    }
  });
  $("sync").addEventListener("click", function () {
    $("sync").disabled = true;
    $("result").className = "muted";
    $("result").textContent = "Syncing...";
    orca.postMessage({ type: "sync" });
  });
  var dock = $("dock");
  if (dock) dock.addEventListener("click", function () { orca.postMessage({ type: "dock" }); });
  var refresh = $("refresh");
  if (refresh) refresh.addEventListener("click", function () { orca.postMessage({ type: "state" }); });
  orca.postMessage({ type: "state" });
})();
</script>
"""

PAGE = STYLE + """
<h3>Spool Sync</h3>
<p class="muted">Selects each filament slot's preset for the spools loaded on the active printer
(lane_data from filament-kit or AFC; else slot 1 from the active spool). The chip shows the colour of the printer's
active spool (on a multi-tool printer, the active tool's); set slot colours by hand if they matter.</p>
<div class="row"><span id="chip" class="chip"></span><span id="loaded" class="muted">Checking printer...</span>
  <button type="button" id="refresh">Refresh</button></div>
<div class="row"><button type="button" id="sync" class="big">Sync filament from printer</button>
  <button type="button" id="dock">Dock button beside 3D view</button></div>
<p id="result" class="muted"></p>
""" + SCRIPT

PANEL = STYLE + """
<div class="row"><button type="button" id="sync" class="big">Sync filament</button>
  <span id="chip" class="chip"></span></div>
<div id="loaded" class="muted">Checking printer...</div>
<p id="result" class="muted"></p>
""" + SCRIPT


class SyncPanel:
    """The dock panel beside the 3D view; one per Orca session."""
    panel = None

    @classmethod
    def open(cls):
        if cls.panel is not None and cls.panel.is_open():
            cls.panel.show()
            return
        cls.panel = orca.host.ui.create_dock_panel(
            html=PANEL, title="Spool Sync", width=240, height=150,
            on_message=cls.on_message, on_close=cls.on_close, dock="right")

    @classmethod
    def on_message(cls, message):
        kind = (message or {}).get("type")
        post = lambda reply: cls.panel is not None and cls.panel.post(reply)
        if kind == "sync":
            in_background(sync_message, post)
        elif kind == "state":
            in_background(state_message, post)

    @classmethod
    def on_close(cls):
        cls.panel = None


class SpoolSyncPage(orca.pages.PagesPluginCapabilityBase):
    def get_name(self):
        return "Spool Sync"

    def get_ui(self):
        return PAGE

    # Called on the UI thread when the page posts.
    def on_message(self, message):
        kind = (message or {}).get("type")
        if kind == "sync":
            in_background(sync_message, self.post_message)
        elif kind == "state":
            in_background(state_message, self.post_message)
        elif kind == "dock":
            SyncPanel.open()
            self.post_message({"type": "result", "ok": True,
                               "text": "Sync button docked beside the 3D view (Prepare / Preview)"})


class SyncFilamentFromPrinter(orca.script.ScriptPluginCapabilityBase):
    def get_name(self):
        return "Sync filament from printer"

    def execute(self):
        ok, text = run_sync()
        if ok:
            return orca.ExecutionResult.success(text)
        return orca.ExecutionResult.failure(orca.PluginResult.RecoverableError, f"Spool Sync: {text}")


@orca.plugin
class SpoolSync(orca.base):
    def register_capabilities(self):
        orca.request_permissions(network=printer_hosts(), threading=True)
        orca.register_capability(SpoolSyncPage)
        orca.register_capability(SyncFilamentFromPrinter)
