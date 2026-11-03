"""Printer AMS slots for the MCP tools `printer_slots` / `printer_set_slot` (ops `h2d_slots` / `h2d_set_slot`).

Two backends, picked by config:
- `slot_service` `{state_url, set_url, token_file}`: the owner's own slot services (ops h2d_tools.py: the
  h2d-remote state and the scanner orchestrator's `/set-slot`). The web process never talks to the printer;
  the orchestrator picks the user's exact preset, sets Spoolman and releases the slot's previous spool.
- else, with the `printers` module on: the kit's bridge, through the kit server's own API on 127.0.0.1 (the server
  process owns the printer connections; a second MQTT session from this process would compete with it). The web
  process pairs itself once like a phone, in-process (device 'web (MCP)'), at start, and keeps that token in
  `FK_STATE/web/kit_token` (0600). If the owner unpairs it, slot calls fail with a clear error (logged once) and
  the token file is dropped, so the next start pairs again.
"""
from __future__ import annotations

import http.client
import json
import logging
import re
import ssl
import threading
import urllib.error
import urllib.request
from pathlib import Path

from .. import config, pairing
from ..profiles import builds
from .errors import Problem

log = logging.getLogger(__name__)

TIMEOUT_STATE, TIMEOUT_SET = 10, 20
DEVICE_NAME = "web (MCP)"
UNPAIRED = (f"the kit server no longer accepts this web unit (the device '{DEVICE_NAME}' was unpaired); "
            "restart it to pair again: sudo systemctl restart filament-kit-web")
OPS_NOTE = "spool = the Spoolman spool assigned by an NFC tap or printer_set_slot (null: never assigned)"


class SlotError(Problem):
    """A refusal to show the caller (bad slot, no backend, a service that cannot be reached). `status` is the HTTP
    status the kit server answered with, None when it did not answer."""
    status: int | None = None


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
        raise SlotError("the slot service token file (slot_service.token_file) cannot be read") from None
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

    def __init__(self, base_url: str | None = None, context: ssl.SSLContext | None = None):
        cfg = config.load()
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

    @staticmethod
    def _token_file() -> Path:
        return config.paths().state / "web" / "kit_token"

    def ensure_paired(self) -> None:
        """Read this process's token, or pair as the device 'web (MCP)' when there is none (called at start)."""
        self._token()

    def _token(self) -> str:
        """This process's own pairing token (device 'web (MCP)'), made in-process when the file is missing and
        kept in FK_STATE/web/kit_token (0600). Never renewed while running: see `_refused`."""
        with self._lock:
            if self._refused:
                raise SlotError(UNPAIRED)
            f = self._token_file()
            try:
                tok = f.read_text(encoding="utf-8").strip()
                if tok:
                    return tok
            except OSError:
                pass
            tok = pairing.issue(DEVICE_NAME).token
            pairing.check(tok)                   # claims the device, like a phone's first call
            pairing.make_state_dir(f.parent)
            pairing._write_atomic(f, (tok + "\n").encode("utf-8"), 0o600, state_owned=True)
            log.info("paired with the kit server as %r", DEVICE_NAME)
            return tok

    def _refuse(self) -> None:
        """The kit server refused the token: the owner unpaired 'web (MCP)'. Say so loudly, drop the token so the
        next start pairs again, and refuse until then (re-pairing behind the owner's back would undo the unpair)."""
        with self._lock:
            if not self._refused:
                log.error("the kit server refused this web unit's pairing token (the device %r was unpaired?); "
                          "printer slots are off until the next start, which pairs again: "
                          "sudo systemctl restart filament-kit-web", DEVICE_NAME)
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
                raise SlotError(UNPAIRED) from None
            raise self._error(e.code, (err.get("message") if isinstance(err, dict) else None)
                              or f"the kit server answered {e.code}") from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            raise SlotError(f"the kit server ({self.base}) is not reachable: {e}") from None

    @staticmethod
    def _error(status: int, text: str) -> SlotError:
        e = SlotError(text)
        e.status = status
        return e

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
                raise SlotError(UNPAIRED) from None
            raise self._error(e.code, (err.get("message") if isinstance(err, dict) else None)
                              or f"the kit server answered {e.code}") from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            raise SlotError(f"the kit server ({self.base}) is not reachable: {e}") from None
        return r.status, r.headers.get_content_type(), r

    def get(self, path: str):
        return self._call("GET", path)

    def post(self, path: str, body: dict):
        return self._call("POST", path, body)


def kit_label(slot) -> str:
    """A slot as the kit names it (A1-D4, HT-A.., Ext): kit labels pass through; ops names '1'-'4' and 'HT1'-'HT3'
    map to the first AMS's A1-A4 and HT-A..HT-C."""
    s = str(slot).strip()
    m = re.fullmatch(r"(?i)(?:AMS\s*)?HT\s*([1-9])", s)
    if m:
        return f"HT-{chr(ord('A') + int(m.group(1)) - 1)}"
    m = re.fullmatch(r"(?i)(?:AMS\s*)?(?:SLOT\s*)?([1-4])", s)
    if m:
        return f"A{m.group(1)}"
    if re.fullmatch(r"(?i)EXT(?:ERNAL)?[\s_-]*(L|LEFT|R|RIGHT)", s):
        raise SlotError("the kit bridge names the external spool 'Ext'; see printer_slots for the slot labels")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,16}", s):
        raise SlotError(f"unknown slot {slot!r}: use a label from printer_slots (A1-D4, HT-A, Ext)")
    return s


def bridge_slots(kit) -> dict:
    out = []
    for p in kit.get("/api/printers").get("printers", []):
        if not p.get("configured"):
            continue
        st = kit.get(f"/api/printers/{p['id']}").get("status") or {}
        slots = [{"slot": sl.get("label"), "unit": u.get("label"), "type": sl.get("type"),
                  "color_hex": sl.get("color_hex"), "feeding_now": bool(sl.get("active")), "spool": sl.get("spool")}
                 for u in st.get("ams") or [] for sl in u.get("slots") or []]
        out.append({"id": p["id"], "name": p.get("name"), "state": p.get("state"),
                    "printer_state": st.get("gcode_state"), "job": st.get("job") or None, "slots": slots})
    return {"printers": out, "note": "spool = the Spoolman spool whose location is that slot"}


def bridge_set_slot(kit, spool_id: int, slot: str, dry_run: bool, printer: str | None = None) -> dict:
    label = kit_label(slot)
    printers = [p for p in kit.get("/api/printers").get("printers", []) if p.get("configured")]
    if printer is not None:
        printers = [p for p in printers if printer in (p.get("id"), p.get("name"))]
        if not printers:
            raise SlotError(f"no printer {printer!r} is set up in the kit")
    if len(printers) != 1:
        raise SlotError("several printers are set up: name one (printer = its id or name from printer_slots)"
                        if printers else "no printer is set up in the kit")
    p = printers[0]
    res = kit.post(f"/api/printers/{p['id']}/slots/{label}/load", {"spool_id": int(spool_id), "dry_run": bool(dry_run)})
    res = dict(res) if isinstance(res, dict) else {"result": res}
    res.update(printer=p["id"], slot=label)
    if dry_run:
        res["note"] = "dry run: nothing sent. Show the user, then call again with dry_run=false."
    return res


__all__ = ["KitApi", "SlotError", "bridge_set_slot", "bridge_slots", "kit_label", "parse_slot", "service_set_slot",
           "service_slots", "slot_label"]
