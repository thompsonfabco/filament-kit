"""The MCP tools of the `web` process (ports of filament-ops vm/server.py's tools, same names and arguments).

`Tools` holds the plain, synchronous implementations; the phone web app (intake_app.py) calls the same methods.
`register(mcp, tools)` publishes them on an MCPServer: each runs in a worker thread and returns indented JSON.
A deliberate refusal (`Problem`, a ValueError, a tag conflict, Spoolman's own error) reaches Claude as a tool error
with its text; anything else is a crash, logged here and shown as a generic failure (the SDK's rule).

They call the kit in-process: inventory (adds, links, opens), tagsources (the readers' last tap), profiles (preset
lines and builds), and the slot service or the kit's bridge for printer slots (slots.py). `instructions(cfg)` is
the connector's instructions: config `web_instructions`, else a text built from the owner's placement, locations
and tare hints (ops instructions.txt is the model).
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Callable

import anyio
from pydantic import BaseModel, Field

from .. import config, inventory, modules, tags, tagsources
from ..inventory import AddFailed, TagConflict
from ..profiles.errors import ProfileError
from ..spoolman import Spoolman, SpoolmanError
from . import presets, slots
from .errors import Problem

log = logging.getLogger(__name__)

MAX_FILAMENTS = 60
OLD_TAP = 900  # seconds: a tap this old may not be the spool the user is holding


def ago(s) -> str:
    s = int(s or 0)
    return f"{s} s ago" if s < 60 else f"{s // 60} min ago" if s < 3600 else f"{s // 3600} h ago"


class SpoolItem(BaseModel):
    vendor: str
    name: Annotated[str, Field(description="e.g. 'High Speed PLA+ 2.0 Grey'; reuse an existing filament's exact name")]
    material: str
    net: Annotated[float, Field(description="net filament grams")]
    tare: Annotated[float, Field(description="empty spool grams")]
    density: float
    count: int
    color_hex: Annotated[str | None, Field(description="no #")] = None
    nozzle: int | None = None
    bed: int | None = None
    lot: str | None = None
    nozzle_range: Annotated[str | None, Field(description="e.g. '200-230'")] = None
    bed_range: str | None = None
    price_per_kg: float | None = None
    price_line: Annotated[str | None, Field(description="'Price: $X/kg - <source>'")] = None
    note: Annotated[str | None, Field(description="label facts and which values are estimates")] = None
    location: Annotated[str | None, Field(description="default: the sealed-stock location")] = None
    sealed: Annotated[bool | None, Field(description="false = already out of its bag/box: no SEALED comment")] = None
    gross: Annotated[float | None, Field(description="opened spool's scale weight incl. spool (count 1): "
                                                     "remaining = gross - tare")] = None
    spool_note: Annotated[str | None, Field(description="appended to each spool's comment")] = None
    line: Annotated[str | None, Field(description="only for a new filament: its product line without the colour, "
                                                    "e.g. 'PLA+ 2.0' (ignored for an existing filament)")] = None
    bambu_parent: Annotated[str | None, Field(description="only for a new filament: the Bambu Studio base preset "
                                                            "for its new line (ignored for an existing filament)")] = None


def _num(v) -> float | int | None:
    """A whole float as int, so Spoolman and the add's validation see what a JSON body would carry."""
    return int(v) if isinstance(v, float) and v.is_integer() else v


def item_dict(it: SpoolItem) -> dict:
    d = it.model_dump(exclude_none=True)
    return {k: _num(v) if k in ("net", "tare", "gross", "price_per_kg") else v for k, v in d.items()}


class Tools:
    def __init__(self, sm: Spoolman, *, kit_api=None, load_config: Callable[[], dict] = config.load):
        self.sm = sm
        self._kit = kit_api
        self._load = load_config

    def cfg(self) -> dict:
        return self._load()

    def _rules(self) -> dict:
        return self.cfg()["placement"]

    def _need(self, module: str) -> None:
        if module not in modules.enabled(self.cfg()):
            raise Problem(f"the {module} module is off on this server")

    # ---------- inventory ----------

    def find_spools(self, query: str = "", sealed_only: bool = False, location: str | None = None) -> dict:
        """Filaments matching every word of `query` (vendor, name, material), with their spools."""
        words = (query or "").lower().split()
        out: dict[int, dict] = {}
        for s in self.sm.get("spool"):
            f = s.get("filament") or {}
            vendor = (f.get("vendor") or {}).get("name") or ""
            hay = f"{vendor} {f.get('name') or ''} {f.get('material') or ''}".lower()
            sealed = inventory.SEALED_COMMENT in (s.get("comment") or "")
            if any(w not in hay for w in words) or (sealed_only and not sealed):
                continue
            if location and location.lower() not in (s.get("location") or "").lower():
                continue
            e = out.setdefault(f.get("id"), {"filament_id": f.get("id"), "vendor": vendor, "name": f.get("name"),
                                             "material": f.get("material"), "net_g": f.get("weight"),
                                             "tare_g": f.get("spool_weight"), "spools": []})
            e["spools"].append({"spool_id": s["id"], "location": s.get("location"),
                                "remaining_g": s.get("remaining_weight"), "sealed": sealed, "lot": s.get("lot_nr"),
                                "tagged": bool(tags.stored(s))})
        res = sorted(out.values(), key=lambda e: (e["vendor"].lower(), (e["name"] or "").lower()))
        for e in res:
            e["spools"].sort(key=lambda s: s["spool_id"])
        return {"matches": len(res), "filaments": res[:MAX_FILAMENTS], "truncated": len(res) > MAX_FILAMENTS}

    def add_spools(self, items: list[dict], dry_run: bool = True, link_tag: str | None = None, *,
                   new_filaments_only_lines: bool = False) -> dict:
        """Add spools (vendor + name reuse an existing filament). `link_tag` (the web app): the tag a label read
        saw; it is linked to the one opened spool only while it is still the readers' last tap.
        `new_filaments_only_lines` (the MCP path, Ruling AC): `line` / `bambu_parent` are dropped from items that
        match an existing filament, so a routine add never moves that filament to another preset line (the web
        app sends the label read's own line, which is the filament's, and keeps them)."""
        notes: list[str] = []
        if new_filaments_only_lines and isinstance(items, list):
            items = self._drop_lines_of_existing(items)
        uid = None
        if link_tag:
            uid = tags.normalize_uid(str(link_tag))
            last = tagsources.latest(self.cfg())
            now = _uid(last.get("nfc_id")) if last else None
            if now != uid:
                notes.append(f"Tag {uid} not linked: the reader's last tag is now {now or 'none'}. "
                             "Tap it again and link it on Open spool.")
                uid = None
        r = inventory.add_and_link(self.sm, items, self._rules(), bool(dry_run), uid)
        if r.dry:
            notes.append("dry run: nothing written. Show the user, then call again with dry_run=false.")
        return {"output": "\n".join(r.lines + notes), "exit_code": 0, "spool_ids": r.spool_ids, "dry": r.dry}

    def _drop_lines_of_existing(self, items: list) -> list:
        have = {(((f.get("vendor") or {}).get("name") or "").lower(), (f.get("name") or "").lower())
                for f in self.sm.get("filament")}
        out = []
        for it in items:
            if isinstance(it, dict) and (str(it.get("vendor", "")).lower(), str(it.get("name", "")).lower()) in have:
                it = {k: v for k, v in it.items() if k not in ("line", "bambu_parent")}
            out.append(it)
        return out

    def tag_state(self) -> dict:
        """The newest tap on any reader, the spool it is linked to, and spools whose tag is one byte apart."""
        t = tagsources.latest(self.cfg())
        if not t:
            return {"nfc_id": None, "spool": None, "near": [],
                    "text": "No tag read on any reader yet: tap one."}
        uid = _uid(t["nfc_id"])
        base = {"nfc_id": uid or t["nfc_id"], "read_at_unix": t.get("read_at_unix"),
                "age_seconds": t["age_seconds"], "reader": t["reader"], "held": t.get("held", False)}
        when = f"{ago(t['age_seconds'])} on the {t['reader']} reader"
        if uid is None:
            return {**base, "spool": None, "near": [], "text": f"last tag: {t['nfc_id']} {when} (not a tag UID)"}
        owner = inventory.by_tag(self.sm, uid)
        near = inventory.tag_neighbours(self.sm, uid)
        text = [f"last tag: {uid}  {when}"]
        text.append(f"  linked in Spoolman: {inventory.describe(owner)}" if owner
                    else "  not linked to any spool yet (a new tag): ready to link")
        near = [i for i in near if not owner or i != owner["id"]]
        if near:
            text.append(f"  note: tags from one batch differ in a single byte; don't confuse it with spool(s) {near}")
        return {**base, "spool": _spool_view(owner) if owner else None, "near": near, "text": "\n".join(text)}

    def open_spool(self, spool: int | None = None, filament: int | None = None, location: str | None = None,
                   gross: float | None = None, remaining: float | None = None, humidity: float | None = None,
                   force: bool = False, dry_run: bool = True) -> dict:
        """Link the readers' last tap to a spool (or a filament's lowest-id sealed spool) and mark it opened."""
        if (spool is None) == (filament is None):
            raise Problem("give exactly one of spool or filament")
        t = tagsources.latest(self.cfg())
        if not t:
            raise Problem("No tag read on any reader yet: tap the tag on a reader first.")
        uid = _uid(t["nfc_id"])
        if uid is None:
            raise Problem(f"the last tap {t['nfc_id']!r} is not a tag UID: tap again")
        if spool is None:
            spool = inventory.pick_sealed(self.sm, filament)
            if spool is None:
                raise Problem(f"filament {filament} has no sealed spool; give the spool id instead")
        notes = []
        if t["age_seconds"] > OLD_TAP and not t.get("held"):
            notes.append(f"note: the last tap was {ago(t['age_seconds'])}; if the user just tapped this spool, "
                         "the reader may have missed it")
        near = inventory.tag_neighbours(self.sm, uid)
        if near:
            notes.append(f"note: spool(s) {near} carry a tag one byte apart from {uid} (same batch)")
        out = inventory.open_spool(self.sm, int(spool), uid, self._rules(), gross=_num(gross),
                                   location=location or None, force=bool(force), dry=bool(dry_run),
                                   humidity=_num(humidity), remaining=_num(remaining))
        head = (f"{'would link' if dry_run else 'linked'} tag {uid} ({ago(t['age_seconds'])} on the {t['reader']} "
                f"reader) to {inventory.describe(out)}")
        if dry_run:
            notes.append("dry run: nothing changed. Show the user, then call again with dry_run=false.")
        return {"output": "\n".join([head, *notes]), "exit_code": 0, "spool": _spool_view(out), "dry": bool(dry_run)}

    # ---------- presets ----------

    def preset_status(self) -> dict:
        self._need("presets")
        return presets.status(self.sm)

    def list_lines(self, vendor: str | None = None) -> dict:
        self._need("presets")
        return presets.list_lines(vendor)

    def find_parents(self, text: str) -> dict:
        self._need("presets")
        return presets.find_parents(text)

    def add_filaments_to_line(self, line: str, filament_ids: list[int]) -> dict:
        self._need("presets")
        return presets.add_ids(self.sm, line, filament_ids)

    def add_line(self, name: str, vendor: str, filament_ids: list[int], orca_parent: str, bs_template: str) -> dict:
        self._need("presets")
        return presets.add_line(self.sm, name, vendor, filament_ids, orca_parent, bs_template)

    def generate(self) -> dict:
        self._need("presets")
        return presets.generate()

    # ---------- printer slots ----------

    def _slot_backend(self):
        cfg = self.cfg()
        svc = cfg.get("slot_service")
        if svc is not None:
            if isinstance(svc, dict) and svc.get("state_url") and svc.get("set_url"):
                return "service", svc
            log.error("config slot_service is set but lacks state_url or set_url; the printer slot tools are off")
            raise Problem("config slot_service is incomplete: it needs state_url and set_url (and token_file); "
                          "fix config.json, or remove slot_service to use the printers module")
        if "printers" in modules.enabled(cfg):
            if self._kit is None:
                self._kit = slots.KitApi()
            return "bridge", self._kit
        raise Problem("no printer slots on this server: neither slot_service is configured nor the printers "
                      "module on")

    def printer_slots(self) -> dict:
        kind, b = self._slot_backend()
        return slots.service_slots(b, self.sm) if kind == "service" else slots.bridge_slots(b)

    def printer_set_slot(self, spool: int, slot: str, dry_run: bool = True, printer: str | None = None) -> dict:
        kind, b = self._slot_backend()
        if kind == "service":
            return slots.service_set_slot(b, spool, slot, dry_run)
        return slots.bridge_set_slot(b, spool, slot, dry_run, printer)


def _uid(v) -> str | None:
    try:
        return tags.normalize_uid(str(v))
    except (ValueError, TypeError):
        return None


def _spool_view(s: dict) -> dict:
    f = s.get("filament") or {}
    return {"id": s.get("id"), "filament_id": f.get("id"), "vendor": (f.get("vendor") or {}).get("name"),
            "name": f.get("name"), "material": f.get("material"), "location": s.get("location"),
            "remaining_g": s.get("remaining_weight"), "first_used": s.get("first_used"), "nfc_id": tags.stored(s),
            "sealed": inventory.SEALED_COMMENT in (s.get("comment") or ""), "extra": s.get("extra") or {}}


def error_text(e: BaseException) -> str | None:
    """The text a caller may see for a deliberate refusal; None for a crash (logged, not shown)."""
    if isinstance(e, TagConflict):
        return f"{e} (force moves it; ask the user first)" if e.reason == "tag_on_other_spool" else str(e)
    if isinstance(e, AddFailed):
        return f"{e} (spools already added: {e.partial.spool_ids})"
    if isinstance(e, SpoolmanError):
        return "Spoolman is not reachable" if e.status is None else str(e)
    if isinstance(e, ProfileError):
        return e.message
    if isinstance(e, ValueError):        # Problem, and the validation in inventory / intake / tags
        return str(e) or type(e).__name__
    return None


# ---------- instructions ----------

def _placement_text(cfg: dict) -> str:
    pl = cfg.get("placement") or {}
    n = int(pl.get("box_count") or 0)
    boxes = (f"other materials to the lowest free '{pl.get('box_prefix', '')}NN' (01-{n:02d}), then "
             f"'{pl.get('overflow')}'") if n else f"other materials to '{pl.get('overflow')}'"
    return f"PLA goes to '{pl.get('pla_location')}', {boxes}"


def instructions(cfg: dict) -> str:
    own = cfg.get("web_instructions")
    if isinstance(own, str) and own.strip():
        return own.strip()
    pl = cfg.get("placement") or {}
    sealed = pl.get("sealed_location") or "Sealed stock"
    locs = ", ".join(f"'{loc}'" for loc in cfg.get("locations") or [])
    hints = (cfg.get("intake") or {}).get("tare_hints") or {}
    hint_text = ", ".join(f"{v} {g}" for v, g in sorted(hints.items(), key=lambda kv: str(kv[0]).lower()))
    tares = (f"Tares: {hint_text}, else the printed or a sibling filament's, else 200 marked as an estimate."
             if hint_text else "Tares: the printed spool weight or a sibling filament's, else 200 marked as an "
                               "estimate.")
    place = _placement_text(cfg)
    return "\n".join([
        "Filament inventory (Spoolman) and slicer presets for the user's printers.",
        "NEW SPOOLS from label photos: find_spools first (same vendor + product + colour already there? then reuse "
        "its exact vendor+name so spools join it). Then add_spools with dry_run=true, show the user, then "
        f"dry_run=false. A spool already out of its bag/box: sealed=false (no SEALED comment; {place}). Name new "
        "colours like their siblings ('<Line> <Colour>'); material PLA for every PLA variant. Set line (and "
        "bambu_parent) only for a new filament; a reused filament keeps its own line. " + tares +
        " Densities: PLA 1.24, PETG 1.27, ABS 1.04, ASA 1.07, TPU 1.21, PC 1.20. "
        f"Storage locations: {locs} ('{sealed}' is the default for sealed spools). Then refresh presets (below).",
        "OPENING A SPOOL: the user taps its NFC tag on a reader first, then sends name/photo, weight, location, "
        "humidity; wait until they're done. tag_state shows the last tap; open_spool dry_run=true then false. A bare "
        f"weight from the user is GROSS (pass gross). With no location, {place}. If the tag belongs to another "
        "spool, ask before force.",
        "PRESETS after new filaments: preset_status (filaments no line records yet; each joins a line by its name "
        "at the next build) -> add_filaments_to_line when that line would be wrong, or find_parents then add_line "
        "for a new brand or product line -> generate. The desktop installs each build by itself the next time the "
        "slicers are closed (preset_status shows waiting_for_desktop). Never delete presets here.",
        "PRINTER SLOTS: printer_slots shows what each AMS slot holds and its assigned spool. To put a spool in a "
        "slot (the user loaded it): find_spools for its spool id, then printer_set_slot dry_run=true, show the "
        "user the preset it picked, then dry_run=false. no_preset means the filament needs a preset line first "
        "(PRESETS), then generate, and the desktop must install it.",
        "Never connect to a printer directly; the printer tools go through the server.",
    ])


# ---------- MCP registration ----------

# module level: the tools' annotations are evaluated in this module's globals (postponed annotations)
SLOT_ARG = ("'1'-'4' = 4-slot AMS, 'HT1'-'HT3' = AMS HT units, 'EXT-L' / 'EXT-R' = external spool for the "
            "left / right nozzle; or a slot label from printer_slots (A1, HT-A ...)")

def register(mcp, tools: Tools) -> None:
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp_types import ToolAnnotations

    read = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    async def call(fn, *args, **kw) -> str:
        try:
            res = await anyio.to_thread.run_sync(lambda: fn(*args, **kw))
        except Exception as e:  # noqa: BLE001 - a refusal becomes a tool error with its text
            text = error_text(e)
            if text is None:
                log.exception("tool %s failed", getattr(fn, "__name__", fn))
                raise
            raise ToolError(text) from None
        return json.dumps(res, indent=1, ensure_ascii=False)

    @mcp.tool(annotations=read)
    async def find_spools(query: Annotated[str, Field(description="words that must all appear in vendor/name/material")] = "",
                          sealed_only: bool = False, location: str | None = None) -> str:
        """Search Spoolman: matching filaments with their spools (id, location, remaining g, sealed, lot, tagged)."""
        return await call(tools.find_spools, query, sealed_only, location)

    @mcp.tool(annotations=write)
    async def add_spools(items: list[SpoolItem], dry_run: bool = True) -> str:
        """Add new spools. A filament with the same vendor + name is reused, otherwise created (with its vendor).
        Run with dry_run=true, show the user, then dry_run=false. New filaments then join a preset line
        (preset_status)."""
        return await call(tools.add_spools, [item_dict(i) for i in items], dry_run, None,
                          new_filaments_only_lines=True)

    @mcp.tool(annotations=read)
    async def tag_state() -> str:
        """Last NFC tag tapped on any of the server's readers (the newest tap wins) and the Spoolman spool it is
        linked to, if any."""
        return await call(tools.tag_state)

    @mcp.tool(annotations=write)
    async def open_spool(spool: Annotated[int | None, Field(description="spool id")] = None,
                         filament: Annotated[int | None, Field(description="filament id: uses its lowest-id sealed spool")] = None,
                         location: str | None = None,
                         gross: Annotated[float | None, Field(description="scale weight incl. spool (a bare weight from the user)")] = None,
                         remaining: Annotated[float | None, Field(description="filament grams only")] = None,
                         humidity: Annotated[float | None, Field(description="box hygrometer %")] = None,
                         force: Annotated[bool, Field(description="move a tag linked to another spool; ask the user first")] = False,
                         dry_run: bool = True) -> str:
        """Link the last tapped NFC tag to a spool and mark it opened (first_used, location, weight, humidity;
        removes SEALED). Give spool or filament. With no weight it stays full; with no location it goes where the
        server's placement rules say (see the instructions)."""
        return await call(tools.open_spool, spool, filament, location, gross, remaining, humidity, force, dry_run)

    @mcp.tool(annotations=read)
    async def preset_status() -> str:
        """Spoolman filament ids not in any preset line yet (with the lines that brand has), the last build, and
        whether the desktop has installed it yet."""
        return await call(tools.preset_status)

    @mcp.tool(annotations=read)
    async def list_lines(vendor: str | None = None) -> str:
        """Preset lines (one per brand + product line) with their Spoolman filament ids and parents."""
        return await call(tools.list_lines, vendor)

    @mcp.tool(annotations=read)
    async def find_parents(text: str) -> str:
        """Search Bambu Studio system presets (and Orca '@System' parents) to build a line on, e.g. 'PETG-CF'.
        Prefer the maker's own preset."""
        return await call(tools.find_parents, text)

    @mcp.tool(annotations=write)
    async def add_filaments_to_line(line: str, filament_ids: list[int]) -> str:
        """Put Spoolman filament ids into an existing preset line (same brand). This moves a filament out of any
        other line it is in, and pins it here by setting its Spoolman extra.line to this line (later builds keep
        it here). Refuses a filament already in this line or of another brand."""
        return await call(tools.add_filaments_to_line, line, filament_ids)

    @mcp.tool(annotations=write)
    async def add_line(name: Annotated[str, Field(description="'<Brand> <Line>'")], vendor: str,
                       filament_ids: list[int],
                       orca_parent: Annotated[str, Field(description="from find_parents")],
                       bs_template: Annotated[str, Field(description="from find_parents")]) -> str:
        """Create a preset line for a new brand or product line (PLA variants use PLA parents)."""
        return await call(tools.add_line, name, vendor, filament_ids, orca_parent, bs_template)

    @mcp.tool(annotations=write)
    async def generate() -> str:
        """Request a build of all presets from Spoolman + the lines, keeping the user's in-app edits. The desktop
        installs the build the next time the slicers are closed."""
        return await call(tools.generate)

    slots_doc = ("Every printer AMS slot: what the printer has loaded (type, colour, preset) and the Spoolman spool "
                 "assigned to it, plus the printer state.")
    set_doc = ("Set a printer AMS slot to a spool, exactly like tapping its NFC tag: the printer gets the user's "
               "own preset for that filament (never Generic; refused with no_preset if none exists), and Spoolman "
               "records the spool in that slot, releasing the spool that was there. Run with dry_run=true, show the "
               "user, then dry_run=false.")

    async def _slots() -> str:
        return await call(tools.printer_slots)

    async def _set(spool: Annotated[int, Field(description="Spoolman spool id (find_spools)")],
                   slot: Annotated[str, Field(description=SLOT_ARG)], dry_run: bool = True,
                   printer: Annotated[str | None, Field(description="printer id or name, when several are set up")] = None
                   ) -> str:
        return await call(tools.printer_set_slot, spool, slot, dry_run, printer)

    async def _h2d_set(spool: Annotated[int, Field(description="Spoolman spool id (find_spools)")],
                       slot: Annotated[str, Field(description=SLOT_ARG)], dry_run: bool = True) -> str:
        return await call(tools.printer_set_slot, spool, slot, dry_run)

    mcp.tool(name="printer_slots", description=slots_doc, annotations=read)(_slots)
    mcp.tool(name="printer_set_slot", description=set_doc, annotations=write)(_set)
    # ops names, kept so a connector that learned them keeps working
    mcp.tool(name="h2d_slots", description=slots_doc + " (Same as printer_slots.)", annotations=read)(_slots)
    mcp.tool(name="h2d_set_slot", annotations=write,
             description=set_doc + " (Same as printer_set_slot. 'EXT-L' / 'EXT-R' work only with the "
                                   "slot_service backend; the kit bridge names the external slot 'Ext'.)")(_h2d_set)
