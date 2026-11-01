"""Label reading: photos -> filament/spool items, read by Claude with structured output.

Photos are checked (JPEG, <= 3 MB, 1-8), counted against a persisted daily cap, and sent with a cached catalog
block of the vendors and filaments already in Spoolman. Failed reads keep their photos for 24 h so the app can retry.
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from . import config
from .spoolman import Spoolman

MAX_PHOTOS, MAX_PHOTO_BYTES = 8, 3 * 1024 * 1024
KEEP_FAILED_SECONDS = 24 * 3600

RULES = """You read filament spool labels from photos for a home 3D-printing inventory (Spoolman).
Several photos can show the same spool (front, side, box); group them into one item per distinct product and set
count to the number of physical spools of it you can see or that the user's note gives. The user's note wins over
your guesses.

Naming: reuse an existing filament when vendor + product line + colour match one in the catalog: set
existing_filament_id and copy its exact vendor and name. A new colour of a known line is named like its siblings,
'<Line> <Colour>' (e.g. 'High Speed PLA+ 2.0 Grey'). File by the product line printed on the label, which can
differ from what a shop calls it. Vendor names follow the catalog's spelling when the brand is already there.
Material: every PLA variant (PLA+, high speed, silk, matte, wood, glow, CF-free blends) is 'PLA'; PETG HF stays
'PETG'; otherwise the base polymer as printed (PETG, ABS, ASA, TPU, PA12-CF, PC ...).
Net weight in grams from the label (1 kg = 1000).
Tare (empty spool grams): a printed spool weight wins; otherwise the catalog vendor's empty spool weight or a
sibling filament's tare; otherwise SUNLU 213, Push Plastic 218, Bambu 250, Polymaker/Panchroma 142, ELEGOO
cardboard 154, OVERTURE 155, GEEETECH 180, JAYO 120, DEEPLEE 140; otherwise 200 and list 'tare' in estimates.
Density g/cm3: the label or the sibling filament; otherwise PLA 1.24, PETG 1.27, ABS 1.04, ASA 1.07, TPU 1.21,
PC 1.20, and list 'density' in estimates.
color_hex: 6 hex digits without '#'; the printed hex if any, else the sibling's, else your estimate from the
photo (list 'color_hex' in estimates). Nozzle and bed: the middle of the printed range as integers, ranges as
'200-230'. lot: the batch/lot number if printed.
note: one line of label facts worth keeping (SKU, printed ranges, anything odd) and which values are estimates.
If the brand can't be read, vendor 'Unknown' and start the note with 'BRAND UNKNOWN:'.
Put anything you need the user to confirm in questions (short, one per line). Don't invent values you can't
read or derive; use null.

Sealed: true when the spool is still in its factory bag (vacuum or zip bag) or box in the photos, false when it is
clearly out of both (bare spool). An RFID/NFC tag stuck on the spool (a sticker or disc, usually on a flange or
the hub) always means opened: false, even if a bag is also in the picture. Unsure: true. sealed_reason says why in
a few words ('in vacuum bag', 'bare spool', 'RFID tag on flange', 'unsure'). Spools of one item share the state;
split an item when some are sealed and some aren't.
Brand: when the label has no readable brand, identify it from the spool itself (flange shape, perforation
pattern, label layout, colours, typography: e.g. SUNLU's perforated spools and label style); put that brand in
vendor and list 'vendor' in estimates. Use 'Unknown' only when the photos don't point to a brand.
Temperatures: labels often give more than one range (normal and high-speed printing, or one per material grade).
Use the highest one: nozzle_range and bed_range are the higher range, nozzle and bed its middle."""

_S, _I = {"anyOf": [{"type": "string"}, {"type": "null"}]}, {"anyOf": [{"type": "integer"}, {"type": "null"}]}
ITEM_PROPS = {"photos": {"type": "array", "items": {"type": "integer"}}, "existing_filament_id": _I,
              "vendor": {"type": "string"}, "name": {"type": "string"}, "material": {"type": "string"},
              "color_hex": _S, "net": {"type": "number"}, "tare": {"type": "number"}, "density": {"type": "number"},
              "count": {"type": "integer"}, "nozzle": _I, "bed": _I, "nozzle_range": _S, "bed_range": _S, "lot": _S,
              "note": {"type": "string"}, "estimates": {"type": "array", "items": {"type": "string"}},
              "sealed": {"type": "boolean"}, "sealed_reason": {"type": "string"}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items", "questions"],
          "properties": {"questions": {"type": "array", "items": {"type": "string"}},
                         "items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                              "required": list(ITEM_PROPS), "properties": ITEM_PROPS}}}}


class PhotoError(ValueError):
    """A photo the server will not send to Claude (names the file and the limit)."""


class CapReached(Exception):
    """The daily cap of label reads is used up."""


class ReadError(Exception):
    def __init__(self, code: str, message: str, read_id: str | None = None):
        super().__init__(message)
        self.code, self.message, self.read_id = code, message, read_id


def check_photos(photos: list[tuple[str, bytes]]) -> list[bytes]:
    if not photos or len(photos) > MAX_PHOTOS:
        raise PhotoError(f"send 1-{MAX_PHOTOS} photos")
    out = []
    for name, data in photos:
        if len(data) > MAX_PHOTO_BYTES or data[:3] != b"\xff\xd8\xff":
            raise PhotoError(f"{name}: expected a JPEG under {MAX_PHOTO_BYTES // 1048576} MB")
        out.append(data)
    return out


class ReadCap:
    """At most `per_day` reads in any 24 h; timestamps persist in `path` so restarts don't reset the cap."""

    def __init__(self, path: Path, per_day: int):
        self.path, self.per_day = Path(path), per_day
        self._lock = threading.Lock()

    def _load(self, now: float) -> list[float]:
        try:
            return [t for t in json.loads(self.path.read_text(encoding="utf-8")) if t > now - 86400]
        except (OSError, ValueError, TypeError):
            return []

    def _save(self, stamps: list[float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(stamps), encoding="utf-8")
        os.replace(tmp, self.path)

    def take(self) -> None:
        with self._lock:
            now = time.time()
            stamps = self._load(now)
            if len(stamps) >= self.per_day:
                raise CapReached(f"daily limit of {self.per_day} label reads reached (reads_per_day)")
            stamps.append(now)
            self._save(stamps)

    def refund(self) -> None:
        """Give back the newest read (one that never reached Claude)."""
        with self._lock:
            stamps = self._load(time.time())
            if stamps:
                stamps.remove(max(stamps))
            self._save(stamps)


# ---------- failed reads kept for retry ----------

def _failed_dir() -> Path:
    return config.paths().state / "failed"


def _sweep_failed() -> None:
    root = _failed_dir()
    if not root.is_dir():
        return
    cutoff = time.time() - KEEP_FAILED_SECONDS
    for d in root.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _keep(read_id: str, images: list[bytes], hint: str, tag_uid: str | None) -> None:
    d = _failed_dir() / read_id
    d.mkdir(parents=True, exist_ok=True)
    for i, data in enumerate(images):
        (d / f"photo{i}.jpg").write_bytes(data)
    (d / "meta.json").write_text(json.dumps({"hint": hint, "tag_uid": tag_uid}), encoding="utf-8")


def _forget(read_id: str) -> None:
    shutil.rmtree(_failed_dir() / read_id, ignore_errors=True)


# ---------- Claude ----------

def _api_key() -> str:
    try:
        key = (config.paths().etc / "anthropic_key").read_text(encoding="utf-8").strip()
    except OSError:
        key = ""
    if not key:
        raise ReadError("bad_key", "no Anthropic API key is set on the server")
    return key


def _call(sm: Spoolman, images: list[bytes], hint: str, tag_uid: str | None, client) -> dict:
    import anthropic
    cfg = config.load()
    if client is None:
        client = anthropic.Anthropic(api_key=_api_key(), timeout=180, max_retries=2)
    fils, vendors = sm.get("/filament"), sm.get("/vendor")
    catalog = "\n".join(
        f"F{f['id']} | {(f.get('vendor') or {}).get('name', '?')} | {f['name']} | {f.get('material')} | "
        f"net {f.get('weight')} | tare {f.get('spool_weight')} | density {f.get('density')} | {f.get('color_hex') or '-'}"
        for f in sorted(fils, key=lambda f: (((f.get("vendor") or {}).get("name") or "").lower(), f["name"].lower())))
    vlist = ", ".join(f"{v['name']} (empty spool {v.get('empty_spool_weight') or '?'} g)" for v in vendors)
    # reference data first and cached: it only changes with Spoolman, so a batch of reads pays for it once
    content = [{"type": "text", "cache_control": {"type": "ephemeral"},
                "text": f"Vendors: {vlist}\n\nCatalog (id | vendor | name | material | net | tare | density | "
                        f"hex):\n{catalog}"}]
    for i, data in enumerate(images):
        content += [{"type": "text", "text": f"Photo {i}:"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.standard_b64encode(data).decode()}}]
    tag = {"nfc_id": tag_uid} if tag_uid else None
    if tag:
        content.append({"type": "text", "text": f"The user tapped an NFC tag ({tag_uid}) that isn't linked to any "
                                                f"spool just before sending these photos: the pictured spool is an "
                                                f"opened one (sealed false)."})
    content.append({"type": "text", "text": f"User's note: {hint or '(none)'}"})
    try:
        resp = client.beta.messages.create(
            model=cfg["model"], max_tokens=16000, system=RULES, messages=[{"role": "user", "content": content}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    except anthropic.AuthenticationError:
        raise ReadError("bad_key", "the Anthropic API key was rejected") from None
    except anthropic.RateLimitError:
        raise ReadError("rate_limited", "Anthropic rate limit: try again in a minute") from None
    except anthropic.APIStatusError as e:
        raise ReadError("api_error", f"Anthropic API error {e.status_code}: {e.message}") from None
    except anthropic.APIConnectionError:
        raise ReadError("unreachable", "can't reach the Anthropic API (check the server's internet access)") from None
    if resp.stop_reason == "refusal":
        raise ReadError("refused", "Claude declined to read these photos; try other photos")
    if resp.stop_reason == "max_tokens":
        raise ReadError("truncated", "the answer was cut off; try fewer photos at once")
    try:
        out = json.loads(next(b.text for b in resp.content if b.type == "text"))
        items = out["items"]
    except (StopIteration, ValueError, KeyError, TypeError):
        raise ReadError("api_error", "Claude's answer could not be read; try again") from None
    by_id = {f["id"]: f for f in fils}
    for it in items:
        f = by_id.get(it.get("existing_filament_id"))
        if f:  # exact vendor + name so the add joins the existing filament; its values win
            it.update(vendor=(f.get("vendor") or {}).get("name") or it["vendor"], name=f["name"],
                      material=f.get("material") or it["material"], tare=f.get("spool_weight") or it["tare"],
                      density=f.get("density") or it["density"], color_hex=f.get("color_hex") or it["color_hex"])
            it["match"] = f"existing filament F{f['id']}"
        else:
            it["existing_filament_id"] = None
            known = any(v["name"].lower() == it["vendor"].lower() for v in vendors)
            it["match"] = "new filament" + ("" if known else " and new vendor")
        hx = (it.get("color_hex") or "").lstrip("#").upper()
        it["color_hex"] = hx if len(hx) == 6 and all(c in "0123456789ABCDEF" for c in hx) else None
        it["count"] = max(1, int(it.get("count") or 1))
    if tag and len(items) == 1:  # a fresh unknown tap is the user opening this very spool
        items[0].update(sealed=False, sealed_reason=f"new tag {tag_uid} tapped before the photos")
    out["tag"] = tag
    u = resp.usage
    out["usage"] = {"model": resp.model, "input_tokens": u.input_tokens + (u.cache_read_input_tokens or 0)
                    + (u.cache_creation_input_tokens or 0), "cached": u.cache_read_input_tokens or 0,
                    "output_tokens": u.output_tokens}
    return {"items": items, "questions": out.get("questions", []), "tag": out["tag"], "usage": out["usage"]}


def read_labels(sm: Spoolman, images: list[bytes], hint: str, tag_uid: str | None, client=None,
                read_id: str | None = None) -> dict:
    """Read label photos. On a ReadError the photos are kept under state/failed/<read_id> (error.read_id)."""
    _sweep_failed()
    rid = read_id or secrets.token_hex(6)
    try:
        out = _call(sm, images, hint, tag_uid, client)
    except ReadError as e:
        _keep(rid, images, hint, tag_uid)
        e.read_id = rid
        raise
    _forget(rid)
    out["read_id"] = rid
    return out


def is_kept(read_id: str) -> bool:
    """True when a failed read's photos are still kept (expired reads are swept first)."""
    if not isinstance(read_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", read_id):
        return False
    _sweep_failed()
    return (_failed_dir() / read_id).is_dir()


def retry(read_id: str, sm: Spoolman, client=None) -> dict:
    """Re-run a failed read from its kept photos."""
    if not is_kept(read_id):
        raise ReadError("not_found", "those photos are no longer kept (24 h); send them again")
    d = _failed_dir() / read_id
    images = [p.read_bytes() for p in sorted(d.glob("photo*.jpg"), key=lambda p: int(p.stem[5:]))]
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    return read_labels(sm, images, meta.get("hint") or "", meta.get("tag_uid"), client=client, read_id=read_id)
