"""Label reading: photos -> filament/spool items, read by Claude with structured output.

Photos are checked (JPEG, <= 3 MB, 1-8), counted against a persisted daily cap, and sent with a cached catalog
block of the vendors and filaments already in Spoolman. Failed reads keep their photos for 24 h so the app can retry.

Every item also gets its product `line` (an existing filament's `extra.line` wins; an empty answer is derived from
the name as `lines.product_of` does) and the line's proposal: `bambu_parent`, `parent_source` and `line_exists`.
When no proposal can be made the line is the library product that prefixes the name, else "" (never the
name with its colour).

merge-ops additions (ports of filament-ops intake.py): with the `orders` module on, the caller passes the order
history (`load_orders`) and the prompt gains an orders block plus the order/price rules, so each item may come back
with `order`, `price_per_kg` and `price_line`; config `intake.tare_hints` ({vendor: grams}) go into the prompt;
a fresh unknown tag (`tagsources.fresh_unknown_tag`) with one item forces `sealed=false`, and then one opened single
spool with a fresh (or held) station weight above its tare gets `gross`.

Two readers: Claude (the cloud, ai_intake) and the local reader (local_intake, local_reader.py, a separate program
on this network). `intake.reader` sets the order (`reader_order`); by default the local one first and the cloud when
the local answer is unsure or fails. Both answers go through the same post-processing (`_finish`), and the result
says which reader answered. The daily cap is taken only for a cloud read (`charge`).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import logging
import time
from pathlib import Path

from . import config, library, local_reader, locks, modules, read_confidence, tagsources
from .profiles import builds, lines
from .spoolman import Spoolman

log = logging.getLogger(__name__)

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
Use the highest one: nozzle_range and bed_range are the higher range, nozzle and bed its middle.
line: the product line as printed, without the colour (e.g. 'PLA+ 2.0', 'PETG HF');
for an existing filament copy its line from the catalog."""

# Appended to RULES only when an order history is passed (the `orders` module); the text is ops intake.py's.
ORDER_RULES = """Brand from orders: when neither the label nor the spool shows the brand, the order history can; use
'Unknown' only when neither the photos nor the orders point to a brand.
Orders: the user's Amazon filament purchases not yet in the catalog are listed below (newest first), plus every
bundle (a bundle's other colours often arrive later as new filaments: match them to it). A spool of a catalog
filament doesn't need an order (order, price_per_kg, price_line null: the filament keeps its price). Match each spool to the order line
it most likely came from (brand or seller, material, colour, weight, bundle contents, recent delivery) and use it
to confirm the brand, product line and colour, the net weight per spool (bundle kg / spools in the bundle) and the
price: price_per_kg = unit price / kg in the bundle, before tax and promotions, and
price_line = 'Price: $<price_per_kg>/kg - Amazon order <order> (<date>): $<unit price> / <kg> kg, ASIN <asin>'.
Set order to the order id. No good match: order, price_per_kg and price_line null (say so in questions only if it
matters, e.g. the brand is still uncertain). A bundle with colours you can't see in the photos is fine."""

_S, _I = {"anyOf": [{"type": "string"}, {"type": "null"}]}, {"anyOf": [{"type": "integer"}, {"type": "null"}]}
ITEM_PROPS = {"photos": {"type": "array", "items": {"type": "integer"}}, "existing_filament_id": _I,
              "vendor": {"type": "string"}, "name": {"type": "string"}, "material": {"type": "string"},
              "color_hex": _S, "net": {"type": "number"}, "tare": {"type": "number"}, "density": {"type": "number"},
              "count": {"type": "integer"}, "nozzle": _I, "bed": _I, "nozzle_range": _S, "bed_range": _S, "lot": _S,
              "note": {"type": "string"}, "estimates": {"type": "array", "items": {"type": "string"}},
              "sealed": {"type": "boolean"}, "sealed_reason": {"type": "string"}, "line": {"type": "string"}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items", "questions"],
          "properties": {"questions": {"type": "array", "items": {"type": "string"}},
                         "items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                              "required": list(ITEM_PROPS), "properties": ITEM_PROPS}}}}
ORDER_PROPS = {**ITEM_PROPS, "order": _S, "price_per_kg": {"anyOf": [{"type": "number"}, {"type": "null"}]},
               "price_line": _S}
SCHEMA_ORDERS = {**SCHEMA, "properties": {
    "questions": SCHEMA["properties"]["questions"],
    "items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                         "required": list(ORDER_PROPS), "properties": ORDER_PROPS}}}}

# an order line that stays listed even when its ASIN is already in the catalog: more colours/spools may follow
MULTI = re.compile(r"bundle|\d+\s*-?\s*(pack|pcs|rolls|spools|colou?rs)\b|(?<![\d.,])([2-9]|\d{2})([.,]\d+)?\s*kg", re.I)


class PhotoError(ValueError):
    """A photo the server will not send to Claude (names the file and the limit)."""


class CapReached(Exception):
    """The daily cap of label reads is used up."""


class ReadError(Exception):
    def __init__(self, code: str, message: str, read_id: str | None = None):
        super().__init__(message)
        self.code, self.message, self.read_id = code, message, read_id
        self.refund = None       # a cloud read's cap refund (callable), for callers that give the read back


def check_photos(photos: list[tuple[str, bytes]]) -> list[bytes]:
    if not photos or len(photos) > MAX_PHOTOS:
        raise PhotoError(f"send 1-{MAX_PHOTOS} photos")
    out = []
    for name, data in photos:
        if len(data) > MAX_PHOTO_BYTES or data[:3] != b"\xff\xd8\xff":
            raise PhotoError(f"{name}: expected a JPEG under {MAX_PHOTO_BYTES // 1048576} MB")
        out.append(data)
    return out


# The Anthropic client of a label read: each try waits CLAUDE_TIMEOUT s, and it tries CLAUDE_RETRIES more times.
CLAUDE_TIMEOUT, CLAUDE_RETRIES = 180, 2
# Seconds a take's refund ticket stays good. The station refunds on the errors that come only after the client has
# given up (unreachable, api_error): up to CLAUDE_TIMEOUT x (CLAUDE_RETRIES + 1) = 9 min, plus the retry backoff and
# the Spoolman catalog fetch before it. 15 minutes covers that worst case.
TICKET_TTL = 15 * 60


class RefundRefused(ValueError):
    """A cap refund with no live ticket of this device's take (unknown, expired, used, or another device's)."""


def _hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()


def _stamps(raw) -> list[dict]:
    """reads.json's entries as {t, ticket?, device?}: a bare number is the old format (a stamp, no ticket)."""
    out = []
    for e in raw if isinstance(raw, list) else []:
        if isinstance(e, (int, float)) and not isinstance(e, bool):
            out.append({"t": float(e)})
        elif isinstance(e, dict) and isinstance(e.get("t"), (int, float)):
            out.append(e)
    return out


def reads_today(path: Path) -> int:
    """The reads taken in the last 24 h (`doctor`'s count and the tests'), in either format of reads.json."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return sum(1 for e in _stamps(raw) if e["t"] > time.time() - 86400)


class ReadCap:
    """At most `per_day` reads in any 24 h; timestamps persist in `path` so restarts don't reset the cap.

    `take` gives a single-use ticket for its stamp; `refund` (a read that never reached Claude) needs that ticket,
    from the same device, within TICKET_TTL, and removes exactly that stamp. Kept hashed in reads.json under its
    lock, so the kit's own reads and the web unit's (through the kit API) share one cap across restarts."""

    def __init__(self, path: Path, per_day: int):
        self.path, self.per_day = Path(path), per_day
        # `reads.lock` beside the file: one cap however many threads and processes take from it
        self._lock = locks.ProcessLock(self.path.with_name("reads.lock"))

    def _load(self, now: float) -> list[dict]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for e in _stamps(raw):
            if e["t"] <= now - 86400:
                continue
            if "ticket" in e and e["t"] < now - TICKET_TTL:   # a dead ticket: keep only the stamp
                e = {"t": e["t"]}
            out.append(e)
        return out

    def _save(self, stamps: list[dict]) -> None:
        """A temp file and a rename, so a crash never resets the cap. The kit's own file: the web unit takes its
        reads through the kit API (/api/intake/cap/take)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps([e if "ticket" in e else e["t"] for e in stamps]))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def take(self, device: str | None = None) -> str:
        """Use one read; returns the ticket that may give it back (`refund`)."""
        with self._lock:
            now = time.time()
            stamps = self._load(now)
            if len(stamps) >= self.per_day:
                raise CapReached(f"daily limit of {self.per_day} label reads reached (reads_per_day)")
            ticket = secrets.token_urlsafe(16)
            stamps.append({"t": now, "ticket": _hash(ticket), "device": device})
            self._save(stamps)
            return ticket

    def refund(self, ticket, device: str | None = None) -> None:
        """Give back the read `ticket` took (one that never reached Claude). Refused, changing nothing, unless the
        ticket is live, unused and this device's."""
        if not isinstance(ticket, str) or not ticket:
            raise RefundRefused("a refund needs the ticket its take returned")
        with self._lock:
            stamps = self._load(time.time())
            h = _hash(ticket)
            for i, e in enumerate(stamps):
                if hmac.compare_digest(str(e.get("ticket") or ""), h) and e.get("device") == device:
                    del stamps[i]
                    self._save(stamps)
                    return
        raise RefundRefused(f"no live read to refund for this ticket (unknown, used, from another device, "
                            f"or older than {TICKET_TTL} s)")


def refund_quietly(cap, ticket, device=None) -> None:
    """A refund on a failure path: logged when refused, never hiding the error being handled."""
    try:
        cap.refund(ticket, device)
    except Exception as e:  # noqa: BLE001 - best effort; the original error is the one to report
        log.warning("cap refund failed: %s", e)


# ---------- order history (the `orders` module) ----------

def load_orders(cfg: dict) -> list[dict] | None:
    """The order lines of `orders.file` (`{items: [{order, date, asin, title, qty, unit_price, seller}]}`), or None
    when the `orders` module is off. On but unreadable: [] (the prompt then says the history is unavailable)."""
    path = (cfg.get("orders") or {}).get("file")
    if not path or "orders" not in modules.enabled(cfg):
        return None
    try:
        items = json.loads(Path(path).read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError, KeyError, TypeError):
        log.warning("orders: %s could not be read", path)
        return []
    return [o for o in items if isinstance(o, dict)] if isinstance(items, list) else []


def read_context(cfg: dict, sm: Spoolman, station=None, *, app_tag: bool = False, orders_from=None) -> dict:
    """The reader context of one label read, for `read_labels(**read_context(...))`; the kit server's
    /api/intake/read and the web app's read both use it. `orders`: the order history, only when the `orders`
    module is on and `orders.file` exists (else None: no orders block). `station_state`: the station's GET /state
    through `station` (a StationClient, None without a station); a dead station gives None. `fresh_tag`: the
    newest reader tap when fresh and on no spool; skipped when the app sent its own tag (`app_tag`), which wins."""
    if orders_from is not None:      # the web unit: the kit's order history through its API (it reads no kit file)
        orders = orders_from()
    else:
        path = (cfg.get("orders") or {}).get("file")
        orders = load_orders(cfg) if path and Path(path).is_file() else None
    station_state = None
    if station is not None and getattr(station, "url", None):
        from .station_client import StationUnreachable
        try:
            station_state = station.state()
        except StationUnreachable as e:      # the read goes on without the scale
            log.info("station: %s", e)
    fresh = None if app_tag else tagsources.fresh_unknown_tag(cfg, sm)
    return {"orders": orders, "station_state": station_state, "fresh_tag": fresh}


def filter_orders(orders: list[dict], fils: list[dict]) -> list[dict]:
    """Only purchases not inventoried yet, newest first: a line whose ASIN is already in a filament's comment (its
    price line) is in Spoolman, unless the title is a bundle (MULTI), whose other colours are still to come.
    Matched by ASIN, not order id: one order can hold several products."""
    known = " ".join((f.get("comment") or "") for f in fils)
    kept = [o for o in orders
            if not o.get("asin") or o["asin"] not in known or MULTI.search(str(o.get("title") or ""))]
    return sorted(kept, key=lambda o: str(o.get("date") or ""), reverse=True)


def _orders_text(orders: list[dict]) -> str:
    return "\n".join(f"{o.get('date')} | {o.get('order')} | {o.get('asin')} | qty {o.get('qty')} | "
                     f"${o.get('unit_price')} | {o.get('seller') or '-'} | {o.get('title')}"
                     for o in orders) or "(order history unavailable)"


# ---------- failed reads kept for retry ----------

def _failed_dir() -> Path:
    """The kit's own (state/failed), or the web unit's (FK_FAILED_DIR, in its own folder: it writes no kit folder)."""
    return Path(os.environ["FK_FAILED_DIR"]) if os.environ.get("FK_FAILED_DIR") else config.paths().state / "failed"


def _write_new(path: Path, data: bytes) -> None:
    """Write a file, never through a link someone planted at `path`."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


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
        _write_new(d / f"photo{i}.jpg", data)
    _write_new(d / "meta.json", json.dumps({"hint": hint, "tag_uid": tag_uid}).encode("utf-8"))


def _forget(read_id: str) -> None:
    shutil.rmtree(_failed_dir() / read_id, ignore_errors=True)


# ---------- the readers: Claude (cloud) and the local reader (local_reader.py) ----------

def _api_key() -> str:
    try:
        key = (config.paths().etc / "anthropic_key").read_text(encoding="utf-8").strip()
    except OSError:
        key = ""
    if not key:
        raise ReadError("bad_key", "no Anthropic API key is set on the server")
    return key


def _cloud(cfg: dict, fils: list[dict], vendors: list[dict], images: list[bytes], hint: str, tag: dict | None,
           when: str, client, orders: list[dict] | None) -> dict:
    """One read by Claude: {items, questions, usage}, items as the model wrote them (post-processing in _finish)."""
    import anthropic
    if client is None:
        client = anthropic.Anthropic(api_key=_api_key(), timeout=CLAUDE_TIMEOUT, max_retries=CLAUDE_RETRIES)
    catalog = "\n".join(
        f"F{f['id']} | {(f.get('vendor') or {}).get('name', '?')} | {f['name']} | {f.get('material')} | "
        f"net {f.get('weight')} | tare {f.get('spool_weight')} | density {f.get('density')} | {f.get('color_hex') or '-'}"
        f" | line {lines._extra_line(f) or '-'}"
        for f in sorted(fils, key=lambda f: (((f.get("vendor") or {}).get("name") or "").lower(), f["name"].lower())))
    vlist = ", ".join(f"{v['name']} (empty spool {v.get('empty_spool_weight') or '?'} g)" for v in vendors)
    # reference data first and cached: it only changes with Spoolman, so a batch of reads pays for it once
    ref = (f"Vendors: {vlist}\n\nCatalog (id | vendor | name | material | net | tare | density | "
           f"hex | line):\n{catalog}")
    hints = (cfg.get("intake") or {}).get("tare_hints") or {}
    if isinstance(hints, dict) and hints:
        ref += ("\n\nOwner's empty spool weights (these win over the defaults in the tare rule): "
                + ", ".join(f"{v} {g} g" for v, g in sorted(hints.items(), key=lambda kv: str(kv[0]).lower())))
    if orders is not None:
        ref += ("\n\nAmazon filament orders (date | order | ASIN | qty | unit price | seller | title):\n"
                + _orders_text(filter_orders(orders, fils)))
    content = [{"type": "text", "cache_control": {"type": "ephemeral"}, "text": ref}]
    for i, data in enumerate(images):
        content += [{"type": "text", "text": f"Photo {i}:"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.standard_b64encode(data).decode()}}]
    if tag:
        content.append({"type": "text", "text": f"The user tapped an NFC tag ({tag['nfc_id']}) that isn't linked to "
                                                f"any spool {when}: the pictured spool is an opened one "
                                                f"(sealed false)."})
    content.append({"type": "text", "text": f"User's note: {hint or '(none)'}"})
    try:
        resp = client.beta.messages.create(
            model=cfg["model"], max_tokens=16000, system=RULES if orders is None else RULES + "\n" + ORDER_RULES,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "medium", "format": {"type": "json_schema",
                                                          "schema": SCHEMA if orders is None else SCHEMA_ORDERS}},
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
    u = resp.usage
    usage = {"model": resp.model, "input_tokens": u.input_tokens + (u.cache_read_input_tokens or 0)
             + (u.cache_creation_input_tokens or 0), "cached": u.cache_read_input_tokens or 0,
             "output_tokens": u.output_tokens}
    return {"items": items, "questions": out.get("questions", []), "usage": usage}


def _local(cfg: dict, fils: list[dict], vendors: list[dict], images: list[bytes], hint: str, tag: dict | None,
           orders: list[dict] | None, revise: tuple[dict, str] | None = None) -> dict:
    """One read by the local reader: {items, questions, usage, confidence, unsure, tier}; with `revise`
    ((the saved values, the owner's note)) its /v1/revise. Raises ReadError."""
    fl, vl = local_reader.catalog(fils, vendors, lines._extra_line)   # the order history is not sent (contract v1)
    try:
        if revise is not None:
            return local_reader.revise(cfg, images, revise[0], revise[1], fl, vl)
        return local_reader.read(cfg, images, hint, fl, vl, tag)
    except local_reader.LocalReaderError as e:
        raise ReadError("local_" + e.code, str(e)) from None


def _finish(raw: dict, fils: list[dict], vendors: list[dict], tag: dict | None, station_state: dict | None) -> dict:
    """The post-processing every reader's answer gets: the existing-filament match (its values win), colour, count
    and price cleanup, the product line and its proposal, the fresh tag, the station's scale."""
    items = raw["items"]
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
        if isinstance(it.get("price_per_kg"), (int, float)) and not isinstance(it["price_per_kg"], bool):
            it["price_per_kg"] = round(float(it["price_per_kg"]), 2)
    _add_lines(items, by_id)
    age = tag.get("age_seconds") if tag else None
    if tag and len(items) == 1:  # a fresh unknown tap is the user opening this very spool
        ago = f" {age} s" if age is not None else ""
        items[0].update(sealed=False, sealed_reason=f"new tag {tag['nfc_id']} tapped{ago} before the photos")
    weight = tagsources.scale_weight(station_state)
    one = items[0] if len(items) == 1 else None
    if (weight and one and one["count"] == 1 and one.get("sealed") is False
            and weight["grams"] > (one.get("tare") or 0)):
        one["gross"] = weight["grams"]  # the opened spool on the station's scale: remaining = gross - tare
    return {"items": items, "questions": raw.get("questions", []), "tag": tag, "scale": weight,
            "usage": raw["usage"]}


# `intake.reader`: which reader reads, in what order. None / "auto": the local reader first and the cloud when the
# local answer is unsure or fails, when both modules are on; else the one that is on.
READER_ORDERS = {"cloud": ("cloud",), "local": ("local",), "local-then-cloud": ("local", "cloud"),
                 "cloud-then-local": ("cloud", "local")}
READER_CHOICES = ("auto", *READER_ORDERS)


def reading_on(cfg: dict) -> bool:
    """A label reader (Claude or the local one) is switched on."""
    return bool(reader_order(cfg))


def reader_order(cfg: dict) -> list[str]:
    """The readers this server would try, in order: "cloud" needs ai_intake, "local" needs local_intake. Empty
    when neither is on."""
    on = modules.enabled(cfg)
    have = {r for r, m in (("cloud", "ai_intake"), ("local", "local_intake")) if m in on}
    want = str((cfg.get("intake") or {}).get("reader") or "auto")
    order = READER_ORDERS.get(want, READER_ORDERS["local-then-cloud"])
    out = [r for r in order if r in have]
    return out or [r for r in READER_ORDERS["local-then-cloud"] if r in have]


def _call(sm: Spoolman, images: list[bytes], hint: str, tag_uid: str | None, client, *,
          orders: list[dict] | None = None, station_state: dict | None = None,
          fresh_tag: dict | None = None, readers: list[str] | None = None, charge=None,
          revise: tuple[dict, str] | None = None) -> dict:
    """Read with the configured readers (`readers` overrides; none configured: the cloud, as before the local
    reader existed). `charge()` is called just before a cloud read (the daily cap: it may raise CapReached) and
    returns a refund callable or None; a local read is free.

    local then cloud: an unsure or failed local read goes on to the cloud; if the cloud cannot read (cap reached,
    error) an unsure local answer is returned with a `note`, a failed one gives the cloud's error. cloud then local
    is the same the other way round, except that a cloud answer is never "unsure". The result says which reader
    answered (`reader`), its `confidence` (local only) and the local `tier`.

    `revise` (the intake history's "correct it": (the saved values, the owner's note)): the local reader gets its
    /v1/revise call; the cloud gets `hint` (the prompt with both). A local reader that cannot revise is a failed
    local read, so the cloud may still answer."""
    cfg = config.load()
    order = list(readers) if readers is not None else (reader_order(cfg) or ["cloud"])
    fils, vendors = sm.get("/filament"), sm.get("/vendor")
    # the app's tag wins; else a fresh unknown tap on a reader (age known: say how long before the photos)
    tag = {"nfc_id": tag_uid} if tag_uid else (dict(fresh_tag) if fresh_tag and fresh_tag.get("nfc_id") else None)
    age = tag.get("age_seconds") if tag else None
    when = f"{age} s before sending these photos" if age is not None else "just before sending these photos"
    kept, notes, err = None, [], None            # kept: an unsure local answer, used when nothing better comes
    for reader in order:
        if reader == "local":
            try:
                raw = _local(cfg, fils, vendors, images, hint, tag, orders, revise)
            except ReadError as e:
                log.warning("local label reader: %s", e)
                err, notes = err or e, notes + [f"local reader: {e}"]
                continue
            raw["reader"] = "local"
            if not raw["unsure"] or reader == order[-1]:
                return _result(raw, fils, vendors, tag, station_state, notes)
            kept = raw
            continue
        refund = None
        try:
            if charge is not None:
                refund = charge()
            raw = _cloud(cfg, fils, vendors, images, hint, tag, when, client, orders)
        except CapReached:
            if kept is None and reader == order[-1]:
                if err is None:
                    raise
                raise ReadError(err.code, f"{err}; and today's cloud reads are used up") from None
            notes.append("today's cloud reads are used up")
            continue
        except ReadError as e:
            e.refund = refund
            if kept is None and reader == order[-1]:
                raise
            # the read goes on without Claude: a call that never reached it gives its read back, as the station's
            # path does when this error reaches it (review R127 note 3)
            if refund is not None and e.code in ("unreachable", "api_error"):
                refund()
            log.warning("cloud label reader: %s", e)
            err, notes = err or e, notes + [f"cloud reader: {e}"]
            continue
        raw.update(reader="cloud", confidence=None, unsure=False, tier=None)
        return _result(raw, fils, vendors, tag, station_state, notes)
    if kept is not None:
        return _result(kept, fils, vendors, tag, station_state, notes)
    raise err if err is not None else ReadError("api_error", "no label reader could read these photos")


def _result(raw: dict, fils, vendors, tag, station_state, notes: list[str]) -> dict:
    out = _finish(raw, fils, vendors, tag, station_state)
    out.update(reader=raw["reader"], confidence=raw.get("confidence"), unsure=bool(raw.get("unsure")),
               tier=raw.get("tier"), escalated=bool(raw.get("escalated")))
    # per-field confidence (read_confidence): on each item, its summary, and the engine that read it
    for it in out["items"]:
        it["confidence_levels"] = read_confidence.levels(it)
    out["confidence_summary"] = read_confidence.summary([it["confidence_levels"] for it in out["items"]])
    out["engine"] = read_confidence.engine(raw)
    if notes:
        out["note"] = "; ".join(notes)
    return out


def _add_lines(items: list[dict], by_id: dict) -> None:
    """Set each item's `line` and its proposal (`bambu_parent`, `parent_source`, `line_exists`). A failure here
    (an unreadable lines.json, ...) keeps the read: the item then has no proposal (source "none")."""
    for it in items:
        f = by_id.get(it.get("existing_filament_id"))
        known = lines._extra_line(f) if f else ""
        if known:
            it["line"] = known
        elif f:
            # an existing filament's line is its own (derived below from its name), never what Claude read: then
            # only an edit in the app can make the add's line differ and move the filament
            it.pop("line", None)
        elif not isinstance(it.get("line"), str) or not it["line"].strip():
            it.pop("line", None)
        else:
            # the add accepts at most 100 characters without "@": keep what Claude read within that
            it["line"] = it["line"].split("@", 1)[0].strip()[:lines.MAX_TEXT].strip()
            if not it["line"]:
                it.pop("line")
    lib = None
    try:
        lib = library.load()
        store = builds.system_store()
        ls = lines.load()
        for it in items:
            it.setdefault("line", lines.product_of(_as_filament(it), lib))
            p = lines.propose(it.get("vendor") or "", it["line"], it.get("material") or "", library=lib,
                              store=store, lines=ls)
            it.update(line=p["line"], bambu_parent=p["bambu_parent"], parent_source=p["parent_source"],
                      line_exists=p["exists"])
    except Exception as e:  # noqa: BLE001 - the label read itself succeeded
        log.warning("label read: no line proposal (%s: %s)", e.__class__.__name__, e)
        for it in items:
            it.setdefault("line", _fallback_line(it, lib))
            it.setdefault("bambu_parent", None)
            it.setdefault("parent_source", "none")
            it.setdefault("line_exists", False)


def _as_filament(it: dict) -> dict:
    return {"name": it.get("name") or "", "vendor": {"name": it.get("vendor") or ""}, "extra": {}}


def _fallback_line(it: dict, lib) -> str:
    """The line when no proposal could be made: the library product that prefixes the name (the name without its
    colour), else "" so the add and the build derive it; never the full name with the colour."""
    if lib is None:
        return ""
    try:
        product = lines.product_of(_as_filament(it), lib)
    except Exception:  # noqa: BLE001 - same reason as the proposal failing
        return ""
    return "" if product == (it.get("name") or "").strip() else product


def read_labels(sm: Spoolman, images: list[bytes], hint: str, tag_uid: str | None, client=None,
                read_id: str | None = None, *, orders: list[dict] | None = None,
                station_state: dict | None = None, fresh_tag: dict | None = None,
                readers: list[str] | None = None, charge=None) -> dict:
    """Read label photos. On a ReadError the photos are kept under state/failed/<read_id> (error.read_id).

    `orders`: the order history (`load_orders`), None when the `orders` module is off. `station_state`: the intake
    station's GET /state (its `last_weight` may become an opened spool's `gross`). `fresh_tag`: the reader's last
    tag when it is fresh and unknown (`tagsources.fresh_unknown_tag`); `tag_uid` (from the app) wins over it.
    `readers` / `charge`: as `_call` (the reader order, and the daily cap taken only for a cloud read)."""
    _sweep_failed()
    rid = read_id or secrets.token_hex(6)
    try:
        out = _call(sm, images, hint, tag_uid, client, orders=orders, station_state=station_state,
                    fresh_tag=fresh_tag, readers=readers, charge=charge)
    except ReadError as e:
        # a retry has no reader context any more: keep the fresh tag as the tag the photos were sent with
        _keep(rid, images, hint, tag_uid or (fresh_tag or {}).get("nfc_id"))
        e.read_id = rid
        raise
    _forget(rid)
    out["read_id"] = rid
    from . import intake_history
    intake_history.stash_read(rid, images, out, hint, tag_uid or (fresh_tag or {}).get("nfc_id"))
    return out


def is_kept(read_id: str) -> bool:
    """True when a failed read's photos are still kept (expired reads are swept first)."""
    if not isinstance(read_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", read_id):
        return False
    _sweep_failed()
    return (_failed_dir() / read_id).is_dir()


def retry(read_id: str, sm: Spoolman, client=None, *, orders: list[dict] | None = None, charge=None) -> dict:
    """Re-run a failed read from its kept photos (the tag it was sent with; no station weight, which is stale)."""
    if not is_kept(read_id):
        raise ReadError("not_found", "those photos are no longer kept (24 h); send them again")
    d = _failed_dir() / read_id
    images = [p.read_bytes() for p in sorted(d.glob("photo*.jpg"), key=lambda p: int(p.stem[5:]))]
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    return read_labels(sm, images, meta.get("hint") or "", meta.get("tag_uid"), client=client, read_id=read_id,
                       orders=orders, charge=charge)
