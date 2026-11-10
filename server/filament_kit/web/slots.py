"""Printer AMS slots for the MCP tools `printer_slots` / `printer_set_slot` (ops `h2d_slots` / `h2d_set_slot`).

Two backends, picked by config:
- `slot_service` `{state_url, set_url, token_file}`: the owner's own slot services (ops h2d_tools.py: the
  h2d-remote state and the scanner orchestrator's `/set-slot`). The web process never talks to the printer;
  the orchestrator picks the user's exact preset, sets Spoolman and releases the slot's previous spool.
- else, with the `printers` module on: the kit's bridge, through the kit server's own API on 127.0.0.1 (the server
  process owns the printer connections; a second MQTT session from this process would compete with it). The web
  process pairs itself once like a phone, in-process (device 'web (MCP)'), at start, and keeps that token in
  `<web state>/kit_token` (0600; on an install the web unit runs as its own user, which may not write the kit's
  pairing files, so `modules apply` pairs it as root). If the owner unpairs it, slot calls fail with a clear error
  (logged once) and the token file is dropped, so the next `modules apply` pairs again.
"""
from __future__ import annotations

import http.client
import json
import logging
import re
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .. import config, pairing
from ..profiles import builds
from .errors import Problem

log = logging.getLogger(__name__)

TIMEOUT_STATE, TIMEOUT_SET = 10, 20
DEVICE_NAME = "web (MCP)"
UNPAIRED = (f"the kit server no longer accepts this web unit (the device '{DEVICE_NAME}' was unpaired); "
            "pair it again: sudo filament-kit modules apply")
NOT_PAIRED = "this web unit is not paired with the kit server yet; pair it: sudo filament-kit modules apply"


def pair_token(f: Path, role: str | None = None, name: str = DEVICE_NAME) -> str:
    """Pair as the device `name` ('web (MCP)') and keep the token in `f` (0600). Run by `modules apply` as root (then
    handed to the web unit's user), or in-process where the process may write the kit's pairings (one-user installs,
    and the kit server's own phone web app)."""
    tok = pairing.issue(name, role=role).token
    pairing.check(tok)                   # claims the device, like a phone's first call
    f.parent.mkdir(parents=True, exist_ok=True)
    pairing._write_atomic(f, (tok + "\n").encode("utf-8"), 0o600)
    return tok
OPS_NOTE = "spool = the Spoolman spool assigned by an NFC tap or printer_set_slot (null: never assigned)"


class SlotError(Problem):
    """A refusal to show the caller (bad slot, no backend, a service that cannot be reached). From the kit server:
    `code` = its error code ("no_preset", "printer_offline", "slot_in_use", "not_found" ...; "unreachable" when it
    did not answer, "unpaired" when it refused this unit's token) and `http` = its status (None: no answer)."""

    def __init__(self, message: str, *, code: str | None = None, http: int | None = None):
        super().__init__(message)
        self.code, self.http = code, http


# ---------- ids (port of ops h2d_tools.py) ----------

def slot_label(ams_id: int, tray_id: int) -> str:
    ams_id, tray_id = int(ams_id), int(tray_id)
    if ams_id < 128:
        return f"AMS slot {ams_id * 4 + tray_id + 1}"
    if ams_id < 254:
        return f"AMS HT {ams_id - 127}"
    return f"External {'left' if ams_id == 254 else 'right'}"


def parse_slot(slot) -> tuple[int, int]:
    """'3' / 'AMS slot 3' -> (0, 2); 'HT2' / 'AMS HT 2' -> (129, 0); 'EXT-L' / 'external left' -> (254, 0),
    'EXT-R' / 'external right' -> (255, 0) (back spool holder or direct TPU feed, per nozzle)."""
    s = str(slot).strip().upper()
    m = re.fullmatch(r"(?:AMS\s*)?HT\s*([1-3])", s)
    if m:
        return 127 + int(m.group(1)), 0
    m = re.fullmatch(r"(?:AMS\s*)?(?:SLOT\s*)?([1-4])", s)
    if m:
        return 0, int(m.group(1)) - 1
    m = re.fullmatch(r"EXT(?:ERNAL)?[\s_-]*(L|LEFT|R|RIGHT)", s)
    if m:
        return (254 if m.group(1).startswith("L") else 255), 0
    raise SlotError(f"unknown slot {slot!r}: use 1-4 (4-slot AMS), HT1-HT3 (AMS HT units) "
                    "or EXT-L / EXT-R (external spool, left / right nozzle)")


def _http_json(req: urllib.request.Request | str, timeout: float, context: ssl.SSLContext | None = None):
    with urllib.request.urlopen(req, timeout=timeout, context=context) as r:
        return json.loads(r.read())


# ---------- the owner's slot service ----------

def _preset_names() -> dict[str, str]:
    """filament_id -> '<vendor> <product>' from the current build's lines (ops read the generated H2D files)."""
    cur = builds.current()
    m = builds.manifest(cur["stamp"]) if cur else None
    out = {}
    for row in ((m or {}).get("lines") or {}).values():
        if isinstance(row, dict) and isinstance(row.get("filament_id"), str):
            out[row["filament_id"]] = f"{row.get('vendor', '')} {row.get('product', '')}".strip()
    return out


def _assigned(sm) -> dict[str, dict]:
    """'H2D:ams<id>:tray<id>' -> the spool whose `extra.active_tray` says it sits there (set by the orchestrator)."""
    out = {}
    for s in sm.get("spool"):
        at = (s.get("extra") or {}).get("active_tray") or ""
        try:
            at = json.loads(at)
        except ValueError:
            pass
        if isinstance(at, str) and at.startswith("H2D:"):
            f = s.get("filament") or {}
            out[at] = {"spool_id": s["id"], "filament_id": f.get("id"),
                       "name": f"{(f.get('vendor') or {}).get('name', '')} {f.get('name', '')}".strip(),
                       "remaining_g": round(s.get("remaining_weight") or 0), "location": s.get("location")}
    return out


def service_slots(svc: dict, sm) -> dict:
    try:
        state = _http_json(str(svc["state_url"]), TIMEOUT_STATE)
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        raise SlotError(f"the slot service at {svc['state_url']} is not reachable ({e})") from None
    assigned, names, out = _assigned(sm), _preset_names(), []
    for u in state.get("ams") or []:
        for t in u.get("trays") or []:
            pid = t.get("preset_id") or ""
            out.append({
                "slot": slot_label(u["id"], t["id"]),
                "loaded": not t.get("empty"),
                "printer_type": t.get("type"), "printer_color": t.get("color"),
                "preset": names.get(pid) or ("Generic " + (t.get("type") or "") if pid.startswith("GF") else
                                             f"not a current preset ({pid}): re-set this slot" if pid else ""),
                "preset_id": pid,
                "feeding_now": bool(t.get("active")),
                "spool": assigned.get(f"H2D:ams{u['id']}:tray{t['id']}"),
                "humidity_pct": u.get("humidity"),
            })
    return {"printer_online": state.get("online"), "printer_state": state.get("state"), "job": state.get("name"),
            "slots": out, "note": OPS_NOTE}


def service_set_slot(svc: dict, spool_id: int, slot: str, dry_run: bool) -> dict:
    ams_id, tray_id = parse_slot(slot)
    try:
        token = Path(svc["token_file"]).read_text(encoding="utf-8").strip()
    except (OSError, KeyError, TypeError):
        raise SlotError("the slot service token file (slot_service.token_file) cannot be read; if it is there, let "
                        "the web unit read it: sudo filament-kit modules apply") from None
    body = json.dumps({"spool_id": int(spool_id), "ams_id": ams_id, "tray_id": tray_id,
                       "dry_run": bool(dry_run)}).encode()
    req = urllib.request.Request(str(svc["set_url"]), data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Auth-Token": token})
    try:
        res = _http_json(req, TIMEOUT_SET)
    except urllib.error.HTTPError as e:      # orchestrator errors carry a JSON body
        try:
            res = json.loads(e.read() or b"{}") or {}
        except ValueError:
            res = {}
        res = res if isinstance(res, dict) and res else {"ok": False, "status": f"http {e.code}"}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        raise SlotError(f"the slot service at {svc['set_url']} is not reachable ({e})") from None
    res["slot"] = slot_label(ams_id, tray_id)
    if dry_run and res.get("ok"):
        res["note"] = "dry run: nothing sent. Show the user, then call again with dry_run=false."
    return res


# ---------- the kit's own bridge (through the kit server's API) ----------

class KitApi:
    """GET/POST JSON to the kit server (`https://127.0.0.1:<port>`), its certificate pinned (etc/cert.pem)."""

    def __init__(self, base_url: str | None = None, context: ssl.SSLContext | None = None, *,
                 token_file: Path | None = None, device: str = DEVICE_NAME, role: str | None = None):
        """`token_file`, `device`, `role`: another caller's own pairing (the kit server's phone web app keeps one in
        its state folder); by default the web unit's."""
        cfg = config.load()
        self._file, self._device, self._role = token_file, device, role
        self.base = (base_url or f"https://127.0.0.1:{cfg['port']}").rstrip("/")
        self._context = context
        self._lock = threading.Lock()
        self._refused = False

    def _ctx(self) -> ssl.SSLContext | None:
        if self._context is None and self.base.startswith("https:"):
            ctx = ssl.create_default_context(cafile=str(config.paths().etc / "cert.pem"))
            ctx.check_hostname = False  # the pinned self-signed cert names the host, not 127.0.0.1
            self._context = ctx
        return self._context

    def _token_file(self) -> Path:
        return self._file or config.paths().web / "kit_token"

    def ensure_paired(self) -> None:
        """Read this process's token, or pair as the device 'web (MCP)' when there is none (called at start)."""
        self._token()

    def _token(self) -> str:
        """This process's own pairing token (device 'web (MCP)'), made in-process when the file is missing and
        kept in <web state>/kit_token (0600). Never renewed while running: see `_refused`."""
        with self._lock:
            if self._refused:
                raise SlotError(UNPAIRED, code="unpaired")
            f = self._token_file()
            try:
                tok = f.read_text(encoding="utf-8").strip()
                if tok:
                    return tok
            except OSError:
                pass
            try:
                tok = pair_token(f, self._role, self._device) if self._file else pair_token(f)
            except (OSError, pairing.PairingError) as e:   # the web unit's user may not write the kit's pairings
                raise SlotError(f"{NOT_PAIRED} ({type(e).__name__})", code="unpaired") from None
            log.info("paired with the kit server as %r", DEVICE_NAME)
            return tok

    def _refuse(self) -> None:
        """The kit server refused the token: the owner unpaired 'web (MCP)'. Say so loudly, drop the token so the
        next `modules apply` pairs again, and refuse until then (re-pairing behind the owner's back would undo the unpair)."""
        with self._lock:
            if not self._refused:
                log.error("the kit server refused this web unit's pairing token (the device %r was unpaired?); "
                          "printer slots are off until it is paired again: sudo filament-kit modules apply",
                          DEVICE_NAME)
            self._refused = True
            self._token_file().unlink(missing_ok=True)

    def _call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"})
        try:
            return _http_json(req, 30, self._ctx())
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read() or b"{}")
            except ValueError:
                err = {}
            if e.code == 401:
                self._refuse()
                raise SlotError(UNPAIRED, code="unpaired", http=401) from None
            err = err if isinstance(err, dict) else {}
            raise SlotError(err.get("message") or f"the kit server answered {e.code}",
                            code=err.get("error") if isinstance(err.get("error"), str) else None,
                            http=e.code) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            raise SlotError(f"the kit server ({self.base}) is not reachable: {e}", code="unreachable") from None

    def raw(self, path: str, timeout: float = 30):
        """GET a binary or streaming kit route (the camera): (status, content type, open response). The caller
        reads it and closes it; closing ends the kit hub's viewer."""
        req = urllib.request.Request(self.base + path, headers={"Authorization": f"Bearer {self._token()}"})
        try:
            r = urllib.request.urlopen(req, timeout=timeout, context=self._ctx())
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read() or b"{}")
            except ValueError:
                err = {}
            if e.code == 401:
                self._refuse()
                raise SlotError(UNPAIRED, code="unpaired", http=401) from None
            err = err if isinstance(err, dict) else {}
            raise SlotError(err.get("message") or f"the kit server answered {e.code}",
                            code=err.get("error") if isinstance(err.get("error"), str) else None,
                            http=e.code) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            raise SlotError(f"the kit server ({self.base}) is not reachable: {e}", code="unreachable") from None
        return r.status, r.headers.get_content_type(), r

    def get(self, path: str):
        return self._call("GET", path)

    def post(self, path: str, body: dict):
        return self._call("POST", path, body)


LABEL = re.compile(r"[A-Za-z0-9-]{1,16}")       # kit labels: A1 ... Z4, AA1 ..., HT-A ..., Ext, Ext-L / Ext-R


def label_key(label) -> str:
    """How labels are compared: case and surrounding spaces do not matter."""
    return str(label).strip().upper()


def kit_label(slot, labels=None) -> str:
    """A slot as the kit names it, for any printer. `labels` = that printer's slot labels (from its status); a kit
    label matches whatever its case (an exact match first, else the first label equal by `label_key`, the one
    the reader lists). The H2D's old names still work (compat parser): '1'-'4' / 'AMS slot N' -> A1-A4, 'HT1' / 'AMS HT 1' -> HT-A (HT2 -> HT-B ...), 'EXT-L' / 'external left' -> Ext-L, 'EXT-R' -> Ext-R (on a
    printer with one holder: Ext). With `labels` the result is one of them; without (no report yet) the kit
    server checks it."""
    s = str(slot).strip()
    labels = [str(x) for x in labels or () if x]
    if s in labels:
        return s                    # an exact match wins
    have: dict[str, str] = {}
    for x in labels:
        have.setdefault(label_key(x), x)    # labels equal by key: the first (the one the reader lists)
    if label_key(s) in have:
        return have[label_key(s)]
    cand: list[str] = []
    m = re.fullmatch(r"(?i)(?:AMS\s*)?HT\s*([1-9][0-9]?)", s)
    if m:
        cand = [f"HT-{letters(int(m.group(1)) - 1)}"]
    m = re.fullmatch(r"(?i)(?:AMS\s*)?(?:SLOT\s*)?([1-4])", s)
    if m:
        cand = [f"A{m.group(1)}"]
    x = re.fullmatch(r"(?i)EXT(?:ERNAL)?(?:[\s_-]*(L|LEFT|R|RIGHT))?", s)
    if x:
        side = (x.group(1) or "").upper()[:1]
        cand = [f"Ext-{side}", "Ext"] if side else ["Ext", "Ext-L"]
    if not cand and LABEL.fullmatch(s):
        cand = [s]
    if have:
        for c in cand:
            if label_key(c) in have:
                return have[label_key(c)]
        raise SlotError(f"unknown slot {slot!r}: use a label from printer_slots ({', '.join(have.values())})")
    if not cand:
        raise SlotError(f"unknown slot {slot!r}: use a label from printer_slots (A1, B3, HT-A, Ext-L ...)")
    return cand[0]


def letters(n: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA: the kit's unit letters (as bridge.layout.letters, which this process does not
    import)."""
    out, n = "", int(n) + 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(ord("A") + r) + out
    return out


def kit_printers(kit) -> list[dict]:
    """The configured printers of the kit server (`GET /api/printers`), in its order."""
    return [p for p in kit.get("/api/printers").get("printers", []) if p.get("configured")]


def printer_path(printer_id) -> str:
    return "/api/printers/" + urllib.parse.quote(str(printer_id), safe="")


def load_path(printer_id, label: str) -> str:
    """The kit API's load URL for a slot; the label is quoted (layout's clash suffix "#<id>" is not a fragment)."""
    return f"{printer_path(printer_id)}/slots/{urllib.parse.quote(str(label), safe='')}/load"


def status_slots(status: dict) -> list[dict]:
    """Every slot of a printer status (`GET /api/printers/{id}` "status"), in unit order, each with its unit's
    label (`unit`) and `kind` ("ams", "ams_2pro", "ams_ht", "ams_lite", "generic", or "ext" for a holder)."""
    return [{**sl, "unit": u.get("label"), "kind": u.get("kind")}
            for u in (status or {}).get("ams") or [] if isinstance(u, dict)
            for sl in u.get("slots") or [] if isinstance(sl, dict) and sl.get("label")]


def pick_printer(kit, printer: str | None) -> dict:
    """The one printer meant: by id or name, or the only one set up."""
    printers = kit_printers(kit)
    if printer is not None:
        printers = [p for p in printers if str(printer) in (str(p.get("id")), p.get("name"))]
        if not printers:
            raise SlotError(f"no printer {printer!r} is set up in the kit")
    if len(printers) != 1:
        raise SlotError("several printers are set up: name one (printer = its id or name from printer_slots)"
                        if printers else "no printer is set up in the kit")
    return printers[0]


def bridge_slots(kit, printer: str | None = None) -> dict:
    out = []
    printers = kit_printers(kit) if printer is None else [pick_printer(kit, printer)]
    for p in printers:
        st = kit.get(printer_path(p["id"])).get("status") or {}
        slots = [{"slot": sl.get("label"), "unit": sl.get("unit"), "kind": sl.get("kind"), "type": sl.get("type"),
                  "color_hex": sl.get("color_hex"), "present": sl.get("present"),
                  "feeding_now": bool(sl.get("active")), "spool": sl.get("spool")}
                 for sl in status_slots(st)]
        out.append({"id": p["id"], "name": p.get("name"), "model": p.get("model"), "state": p.get("state"),
                    "printer_state": st.get("gcode_state"), "job": st.get("job") or None, "slots": slots})
    return {"printers": out, "note": "spool = the Spoolman spool whose location is that slot; present = filament "
                                     "in the slot (null: the printer does not say)"}


def bridge_set_slot(kit, spool_id: int, slot: str, dry_run: bool, printer: str | None = None) -> dict:
    p = pick_printer(kit, printer)
    try:
        labels = [sl["label"] for sl in status_slots(kit.get(printer_path(p["id"])).get("status") or {})]
    except SlotError:
        labels = []           # no status: the old names map as usual and the kit server checks the label
    label = kit_label(slot, labels)
    res = kit.post(load_path(p["id"], label),
                   {"spool_id": int(spool_id), "dry_run": bool(dry_run)})
    res = dict(res) if isinstance(res, dict) else {"result": res}
    res.update(printer=p["id"], slot=label)
    if dry_run:
        res["note"] = "dry run: nothing sent. Show the user, then call again with dry_run=false."
    return res


__all__ = ["KitApi", "SlotError", "bridge_set_slot", "bridge_slots", "kit_label", "kit_printers", "parse_slot",
           "pick_printer", "printer_path", "service_set_slot", "service_slots", "slot_label", "status_slots"]
