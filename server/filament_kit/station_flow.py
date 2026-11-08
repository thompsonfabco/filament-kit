"""The intake station's button flow, server side: look up a tapped tag, recognise a spool from one photo, save.

The station runs the flow (its buttons, lamps, display, camera and scale are local); these calls are stateless.
Every answer carries `display`: ready-made lines for the station's screen (a title of TITLE_WIDTH characters and
up to two lines of DISPLAY_WIDTH; the station keeps its last rows for its own hints and the temperature line).

Recognition order (the owner's rule): the local AI module when it is on and installed (`filament_kit.local_ai`,
not written yet: `recognize(sm, images, cfg) -> dict | None` in read_labels' shape), then Claude when ai_intake is
on, else nothing ("use phone"). A local recogniser that fails or answers None falls through to Claude.

Saving a new spool: the photo's sealed / opened decides; when the photo can't tell (sealed_reason 'unsure') or
no recogniser read it, the weight decides: within SEALED_TOLERANCE g of a full spool (net + tare) is sealed. An
opened spool gets remaining = gross - tare and its location from the placement rules; a sealed one keeps its
net weight. The tag is linked either way (a sealed spool's link leaves it sealed). An existing spool (its tag
already linked) only gets its weight: remaining = gross - its tare.
"""
from __future__ import annotations

import importlib
import logging
import textwrap
import unicodedata

from . import intake, inventory, modules, tags

log = logging.getLogger(__name__)

# SSD1306 128x64: a bold title row (~16 chars), body rows of 21 chars; the station uses body rows 3-4 itself
DISPLAY_LINES, TITLE_WIDTH, DISPLAY_WIDTH = 3, 16, 21
SEALED_TOLERANCE = 20  # g: a gross weight this close to net + tare is a full (sealed) spool
LOCAL_MODULE = "filament_kit.local_ai"


class FlowError(Exception):
    """A refusal the station shows: `code` for the station's logic, `display` for its screen."""

    def __init__(self, status: int, code: str, message: str, display: list[str], **extra):
        super().__init__(message)
        self.status, self.code, self.display, self.extra = status, code, display, extra


def _ascii(s: str) -> str:
    """The screen's character set: printable ASCII (accents dropped, anything else gone)."""
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if " " <= c <= "~")


def lines(title: str, *parts: str) -> list[str]:
    """Screen lines: the title (cut to TITLE_WIDTH), then the parts wrapped to DISPLAY_WIDTH; DISPLAY_LINES in all
    (the station keeps its last body rows for its own hints and the temperature line)."""
    out = [_ascii(title)[:TITLE_WIDTH]]
    for p in parts:
        if p:
            out += textwrap.wrap(_ascii(p), DISPLAY_WIDTH, break_long_words=True)
    return out[:DISPLAY_LINES]


def _local(cfg: dict):
    """The local AI module when it is switched on and installed, else None."""
    if (cfg.get("modules") or {}).get("local_ai") is not True:
        return None
    try:
        return importlib.import_module(LOCAL_MODULE)
    except ImportError:
        return None


def recognizers(cfg: dict) -> list[str]:
    """The recognisers this server would try, in order."""
    order = ["local"] if _local(cfg) is not None else []
    if "ai_intake" in modules.enabled(cfg):
        order.append("claude")
    return order


def _spool_view(s: dict) -> dict:
    f = s.get("filament") or {}
    return {"id": s["id"], "vendor": (f.get("vendor") or {}).get("name"), "name": f.get("name"),
            "material": f.get("material"), "colour_hex": f.get("color_hex"),
            "remaining_g": s.get("remaining_weight"),
            "spool_weight_g": s.get("spool_weight") or f.get("spool_weight"), "location": s.get("location"),
            "sealed": inventory.SEALED_COMMENT in (s.get("comment") or "")}


def tag_info(sm, uid: str) -> dict:
    """What the station shows after a tap: the linked spool, or a new tag."""
    uid = tags.normalize_uid(uid)
    s = inventory.by_tag(sm, uid)
    if s is None:
        return {"known": False, "uid": uid, "display": lines("New Tag Scanned")}
    v = _spool_view(s)
    left = f"{v['remaining_g']:.0f} g left" if isinstance(v["remaining_g"], (int, float)) else ""
    return {"known": True, "uid": uid, "spool": v,
            "display": lines(v["name"] or "Spool", f"{v['vendor'] or ''} {v['material'] or ''}".strip(),
                             f"{left} {v['location'] or ''}".strip())}


def _confidence(item: dict, questions: list) -> str:
    unsure = (item.get("sealed_reason") == "unsure" or item.get("vendor") == "Unknown" or bool(questions)
              or any(e in (item.get("estimates") or []) for e in ("vendor", "name", "material")))
    return "low" if unsure else "high"


def recognize(sm, cfg: dict, image: bytes, claude=None, cap=None) -> dict:
    """Read one spool photo with the first recogniser that answers. Raises FlowError (no recogniser, or the read
    failed) and lets intake.CapReached through (the API answers 429)."""
    order = recognizers(cfg)
    if not order:
        raise FlowError(409, "no_recognizer", "no local AI and no Claude (ai_intake) on this server",
                        lines("No AI on server", "use phone"))
    out, source = None, None
    if "local" in order:
        try:
            out = _local(cfg).recognize(sm, [image], cfg)
            source = "local" if out else None
        except Exception as e:  # noqa: BLE001 - a broken local recogniser falls through to Claude
            log.warning("local AI recognise failed: %s: %s", e.__class__.__name__, e)
            out = None
    if out is None and "claude" in order:
        if cap is not None:
            cap.take()
        try:
            # no station weight and no reader tap: the photo alone decides sealed (the tap would force opened)
            ctx = intake.read_context(cfg, sm, None, app_tag=True)
            out, source = intake.read_labels(sm, [image], "", None, claude, **ctx), "claude"
        except intake.ReadError as e:
            if cap is not None and e.code in ("unreachable", "api_error"):
                cap.refund()
            raise FlowError(502, "read_failed", str(e), lines("Read failed", "try again, or", "use the phone")) from e
    if not out or not out.get("items"):
        raise FlowError(422, "nothing_read", "no spool found in the photo", lines("No spool seen", "try again"))
    item = dict(out["items"][0])
    item.pop("gross", None)
    conf = _confidence(item, out.get("questions") or [])
    state = {True: "sealed", False: "opened"}.get(None if item.get("sealed_reason") == "unsure"
                                                  else item.get("sealed"), "?")
    mark = "?" if conf == "low" else ""
    return {"source": source, "item": item, "confidence": conf, "questions": out.get("questions") or [],
            "display": lines(f"{item.get('name', '')}{mark}", f"{item.get('vendor', '')}{mark} {item.get('material', '')}",
                             state)}


def _number(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise FlowError(400, "bad_request", f"{what} must be a number", lines("Bad request", what))
    return float(v)


def sealed_by_weight(item: dict, gross: float) -> bool:
    """Sealed when the scale reads at least a bare full spool (net + tare) less SEALED_TOLERANCE. Heavier counts as
    sealed too, on purpose: a spool still in its bag or box (desiccant, cardboard) weighs more than a bare full one;
    only a reading clearly under full means some filament was used."""
    full = (item.get("net") or 0) + (item.get("tare") or 0)
    return full > 0 and gross >= full - SEALED_TOLERANCE


def save(sm, rules: dict, body: dict) -> dict:
    """The long press: update the tag's spool's weight, or add a new spool and link the tag."""
    if not isinstance(body, dict):
        raise FlowError(400, "bad_request", "body must be an object", lines("Bad request"))
    uid = body.get("uid")
    if not isinstance(uid, str) or not uid.strip():
        raise FlowError(400, "bad_request", "uid is required", lines("No tag", "scan a tag first"))
    uid = tags.normalize_uid(uid)
    gross = _number(body.get("gross_g"), "gross_g")
    dry = body.get("dry_run") is True
    if gross <= 0:
        raise FlowError(422, "no_weight", "no weight on the scale", lines("No weight", "put the spool on the scale"))
    linked = inventory.by_tag(sm, uid)
    if body.get("spool_id") is not None or linked is not None:
        sid = body.get("spool_id") if body.get("spool_id") is not None else linked["id"]
        if linked is not None and linked["id"] != sid:
            raise FlowError(409, "tag_mismatch", f"tag {uid} is not linked to spool {sid}",
                            lines("Tag mismatch", "scan again"))
        sealed_now = False
        if linked is None:
            # the retry after `tag_not_linked`: that save made spool `sid` but its link failed. Link the free tag to
            # it now (as the first save would have: a sealed one stays sealed), so a second long press never adds a
            # second spool. A spool with another tag is refused.
            if not isinstance(sid, int) or isinstance(sid, bool):
                raise FlowError(400, "bad_request", "spool_id must be a whole number", lines("Bad request"))
            try:
                target = sm.get(f"spool/{sid}")
                sealed_now = inventory.SEALED_COMMENT in (target.get("comment") or "")
                inventory.link_tag(sm, sid, uid, force=False, dry=dry, keep_sealed=True)
            except inventory.TagConflict as e:
                raise FlowError(409, "tag_mismatch", str(e), lines("Tag mismatch", "scan again")) from e
            except RuntimeError as e:
                raise FlowError(502, "tag_not_linked", str(e), lines(f"Saved #{sid}", "tag not linked:",
                                                                     "link it on the phone"), spool_id=sid) from e
        try:
            # a sealed spool keeps its net weight (its bag weighs too), as when it was first saved
            s = sm.get(f"spool/{sid}") if sealed_now else inventory.update_spool(sm, sid, gross=gross, dry=dry)
        except ValueError as e:
            raise FlowError(422, "weight_out_of_range", str(e), lines("Weight too low", "check the scale")) from e
        v = _spool_view(s)
        return {"spool_id": sid, "created": False, "dry": dry, "remaining_g": v["remaining_g"],
                "location": v["location"],
                "display": lines("Saved" if not dry else "Would save", v["name"] or "",
                                 f"{v['remaining_g']:.0f} g left {v['location'] or ''}".strip())}
    item = body.get("item") if body.get("item") is not None else body.get("filament")  # the panel sends "filament"
    if not isinstance(item, dict):
        raise FlowError(409, "no_filament", "a new tag needs a recognised spool (item)",
                        lines("New tag", "show the spool to the camera first"))
    it = {k: v for k, v in item.items() if k in intake.ITEM_PROPS or k in ("price_per_kg", "price_line", "order")}
    it["count"] = 1
    unsure = it.get("sealed_reason") == "unsure" or not isinstance(it.get("sealed"), bool)
    sealed = sealed_by_weight(it, gross) if unsure else it["sealed"]
    it["sealed"] = sealed
    if unsure:
        it["sealed_reason"] = f"{'full' if sealed else 'partial'} weight {gross:.0f} g (photo unsure)"
    if not sealed:
        it["gross"] = gross
    try:
        # one inventory lock around the tag check, the add and the link (a sealed spool's link keeps it sealed)
        r = inventory.add_and_link(sm, [it], rules, dry, uid, keep_sealed=sealed)
    except inventory.TagConflict as e:
        raise FlowError(409, "tag_in_use", str(e), lines("Tag in use", "linked to another spool")) from e
    except inventory.AddFailed as e:  # Spoolman failed part-way: say which spool exists, so nobody saves it twice
        if e.partial.spool_ids:
            sid = e.partial.spool_ids[0]
            raise FlowError(502, "tag_not_linked", str(e), lines(f"Saved #{sid}", "tag not linked:",
                                                                 "link it on the phone"), spool_id=sid) from e
        raise FlowError(502, "spoolman_error", str(e), lines("Save failed", "Spoolman error, try again")) from e
    except ValueError as e:
        raise FlowError(422, "invalid", str(e), lines("Can't save:", str(e))) from e
    if dry:
        return {"spool_id": None, "created": True, "dry": True, "sealed": sealed, "lines": r.lines,
                "display": lines("Would save", f"{it['vendor']} {it['name']}", "sealed" if sealed else "opened")}
    v = _spool_view(sm.get(f"spool/{r.spool_ids[0]}"))
    return {"spool_id": v["id"], "created": True, "dry": False, "sealed": sealed, "remaining_g": v["remaining_g"],
            "location": v["location"],
            "display": lines("Saved", v["name"] or "",
                             f"{'sealed' if sealed else format(v['remaining_g'], '.0f') + ' g left'} {v['location'] or ''}".strip())}
