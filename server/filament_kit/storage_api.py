"""The storage list over HTTP (ruling R79 section 4): the data of `GET api/storage` and its web twin, and the whole-list
save of the Hub page (`POST settings/storage`), with its preview of an unsaved list and the rename job.

    view(st, taken)        {locations, order_by_material, everything_else, notices}: ONE function, so the app token's
                           route, the web app's twin and `spoolwarden locations --json` give the same data
    preview(sm, body)      the same for an unsaved list, plus `errors` (a list not ready to save is still drawn)
    save(sm, body)         validates the whole list and the change against the spools, renames the spools of a renamed
                           location, writes storage.xml; refusals raise StorageRefused (`errors` per row and field)
    job_state()            the rename job of a save that touches more than RENAME_JOB spools

An `error` of the refusal is {row, id, name, field, error, fix}: `row` is the position (0-based) in the submitted list,
None for the list as a whole; `fix` is the second line of the Error/Fix pair.
"""
from __future__ import annotations

import logging
import threading

from . import inventory, placement, storage
from .storage import BULK, CONTAINERS, MATERIALS, Location, Problem, Storage

log = logging.getLogger("filament_kit.storage")

JOB_STEPS_ABOVE = inventory.RENAME_BATCH       # up to this many renamed spools: done inside the save's own answer


class StorageRefused(ValueError):
    """The list was not saved. `status` is 400 (the list or change is wrong), 409 (a rename is running) or 502."""

    def __init__(self, message: str, errors: list[dict], status: int = 400):
        super().__init__(message)
        self.errors, self.status = errors, status


# ---------------------------------------------------------------- the data every interface shows

def notices(st: Storage) -> list[dict]:
    """What the list says about itself, {code, text}: shown under it by the Hub page (warn notice) and by the command
    line (`Note:` line). `converted`: the migration kept two roles apart; `default_overflow_no_limit`: R79 C1."""
    out = []
    if st.converted:
        out.append({"code": "converted", "text": storage.NOTICE})
    try:
        if storage.default_overflow_starves_others(st):
            out.append({"code": "default_overflow_no_limit", "text": storage.DEFAULT_OVERFLOW_NOTE})
    except StopIteration:                  # a list not saved yet may have no default overflow: the errors say so
        pass
    return out


def view(st: Storage, taken) -> dict:
    """The answer of `GET api/storage`: the locations in fill order (`Storage.describe`), `order_by_material` (one entry
    for each material a location names, in the order the list first names them: the places it is tried at, as
    `placement.order`), `everything_else` (the same for a material no location names) and `notices`."""
    seen: dict[str, str] = {}
    for x in st.locations:
        if x.fill == MATERIALS:
            for m in x.materials:
                if m.strip():
                    seen.setdefault(m.strip().casefold(), m.strip())
    return {"locations": st.describe(taken),
            "order_by_material": [{"material": m, "locations": placement.order(st, m)} for m in seen.values()],
            "everything_else": placement.order(st), "notices": notices(st)}


def current_view(sm, st: Storage | None = None) -> dict:
    return view(st or storage.current(), inventory._used_locations(sm))


# ---------------------------------------------------------------- reading a submitted list

def _whole(v) -> tuple[bool, int | None]:
    """(ok, value) of a number field: None is empty; a whole number or its digits."""
    if v is None or v == "":
        return True, None
    if isinstance(v, bool):
        return False, None
    if isinstance(v, int):
        return True, v
    if isinstance(v, str) and v.strip().isdigit():
        return True, int(v.strip())
    return False, None


def parse(body, before: Storage) -> tuple[Storage, list[Problem]]:
    """The submitted `{locations: [...]}` as a Storage built on `before` (ids kept for rows that carry one, the
    prefix of an existing set kept, a renamed set following its name), and the problems of its shape."""
    problems: list[Problem] = []
    rows = body.get("locations") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return Storage([], before.next_id), [Problem(None, "locations", "Send the whole list as locations.",
                                                     "Send {locations: [...]}, every location in fill order.")]
    old = {x.id: x for x in before.locations if x.id}
    out: list[Location] = []
    for i, r in enumerate(rows):
        def bad(fld, error, fix):
            problems.append(Problem(i, fld, error, fix))
        if not isinstance(r, dict):
            bad("row", "Each location must be an object.", "Send name, type, fill and the other fields.")
            out.append(Location(""))
            continue
        loc = Location(name=r["name"] if isinstance(r.get("name"), str) else "",
                       type=r["type"] if isinstance(r.get("type"), str) else BULK if r.get("type") is None else "?")
        ident = r.get("id")
        if ident is not None and not isinstance(ident, str):
            bad("id", "The id must be text or null.", "Leave the id empty for a new location.")
        elif ident is not None and ident not in old:
            bad("id", "That location is not in the saved list.", "Leave the id empty for a new location.")
        else:
            loc.id = ident
        for key, fld in (("limit", "limit"), ("count", "count")):
            ok, n = _whole(r.get(key))
            if not ok:
                bad(fld, "Enter a whole number, 1 or more.", "Use digits only, or leave it empty.")
            elif key == "limit" and loc.type == BULK:
                loc.limit = n
            elif key == "count" and loc.type == CONTAINERS:
                loc.count = n
        loc.fill = r.get("fill", storage.NONE) if isinstance(r.get("fill", storage.NONE), str) else "?"
        mats = r.get("materials", [])
        if isinstance(mats, str):
            mats = mats.split(",")
        if not isinstance(mats, list) or not all(isinstance(m, str) for m in mats):
            bad("materials", "Materials must be a list of names.", "Send the names as a list, e.g. [\"PLA\"].")
            mats = []
        if loc.fill == MATERIALS:
            loc.materials = [m.strip() for m in mats if m.strip()]
        for key in ("overflow", "default_overflow", "sealed"):
            v = r.get(key, False)
            if not isinstance(v, bool):
                bad(key, f"{key} must be true or false.", "Send true or false.")
            else:
                setattr(loc, key, v)
        if loc.id in old and old[loc.id].type == CONTAINERS and loc.type == CONTAINERS:
            loc.prefix = old[loc.id].prefix                      # the exact text before the number stays
        out.append(loc)
    after = Storage(out, before.next_id)
    storage.follow_names(before, after)
    return after, problems


def _above(prefix_of: Location, count: int, taken) -> list[tuple[int, str]]:
    """The containers of `prefix_of` that hold spools and are numbered above `count`: [(number, name)] ascending."""
    out = []
    pre = prefix_of.container_prefix()
    for text, n in storage.counts_of(taken).items():
        if n > 0 and storage.is_container_name(prefix_of, text):
            num = int(text[len(pre):])
            if num > count:
                out.append((num, text))
    return sorted(out)


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def check_change(before: Storage, after: Storage, taken) -> list[Problem]:
    """What the spools and the saved list forbid about this change (R79 section 3): fewer containers than the highest
    in use, the type while spools are in it, and removing the default overflow or the sealed-spools location."""
    out: list[Problem] = []
    old = {x.id: x for x in before.locations if x.id}
    kept = set()
    counts = storage.counts_of(taken)
    for i, x in enumerate(after.locations):
        o = old.get(x.id) if x.id else None
        if o is None:
            continue
        kept.add(x.id)
        if o.type != x.type and x.type in (BULK, CONTAINERS):
            holds = (counts.get(o.name, 0) > 0 if o.type == BULK
                     else any(storage.is_container_name(o, t) and n > 0 for t, n in counts.items()))
            if holds:
                out.append(Problem(i, "type", "Move the spools out to change the type.",
                                   f"Move the spools in {o.name} to another location first."))
        elif o.type == CONTAINERS and x.type == CONTAINERS and isinstance(x.count, int):
            over = _above(o, x.count, counts)
            if over:
                least = over[-1][0]
                text = (f"{over[0][1]} holds spools. Move it first, or keep at least {least}." if len(over) == 1 else
                        f"{_and([t for _, t in over])} hold spools. Move them first, or keep at least {least}.")
                out.append(Problem(i, "count", text, f"Move the spools out of the containers above {x.count}, or "
                                                     f"enter {least} or more."))
    for o in before.locations:
        if o.id in kept:
            continue
        if o.default_overflow and not any(x.default_overflow for x in after.locations):
            out.append(Problem(None, "default_overflow", "Make another location the default overflow first.",
                               f"Mark another overflow location as the default, then remove {o.name}."))
        if o.sealed and not any(x.sealed for x in after.locations):
            out.append(Problem(None, "sealed", "Choose another location for sealed spools first.",
                               f"Mark another Bulk storage location for sealed spools, then remove {o.name}."))
    return out


def problems_of(before: Storage, after: Storage, shape: list[Problem], taken) -> list[Problem]:
    """Every problem of a submitted list: its shape, `storage.validate`, and the change against the spools. The
    refusals about a removed role replace the general "exactly one" line of validate for the same field."""
    changes = check_change(before, after, taken)
    roles = {p.field for p in changes if p.row is None}
    found = [*shape, *(p for p in storage.validate(after.locations) if not (p.row is None and p.field in roles)),
             *changes]
    seen, out = set(), []
    for p in found:
        if (p.row, p.field, p.error) not in seen:
            seen.add((p.row, p.field, p.error))
            out.append(p)
    return sorted(out, key=lambda p: (p.row is None, p.row or 0))


def errors_of(problems: list[Problem], after: Storage) -> list[dict]:
    rows = after.locations
    return [{"row": p.row, "id": rows[p.row].id if p.row is not None and p.row < len(rows) else None,
             "name": rows[p.row].name if p.row is not None and p.row < len(rows) else None,
             "field": p.field, "error": p.error, "fix": p.fix} for p in problems]


# ---------------------------------------------------------------- preview and save

def _refusal(problems: list[Problem], after: Storage) -> StorageRefused:
    return StorageRefused(f"{problems[0].error} Nothing was saved.", errors_of(problems, after))


def preview(sm, body) -> dict:
    """The view of an unsaved list with its `errors` (empty = it could be saved): the panel "Where a new spool goes",
    the how-full of each row and the notices, before anything is written. Writes nothing, renames nothing."""
    before = storage.current()
    taken = inventory._used_locations(sm)
    after, shape = parse(body, before)
    problems = problems_of(before, after, shape, taken)
    renames = storage.renames(before, after)
    return {"ok": not problems, "dry_run": True, **view(after, taken), "errors": errors_of(problems, after),
            "renames": [{"from": r.label[0], "to": r.label[1]} for r in renames]}


_lock = threading.Lock()          # one save at a time; a running rename job keeps it
_job: dict | None = None


def job_state() -> dict:
    """The rename job of the last save that needed one: {state: none | running | done | failed, step, progress,
    text, error}. `step` is {index, count, text} of the newest batch; `progress` runs 0 to 1."""
    return dict(_job) if _job else {"state": "none", "step": None, "progress": None, "text": "", "error": None}


def _write(sm, before: Storage, after: Storage, items, step=None) -> dict:
    """Rename the spools of the renamed locations, then write the list. A rename that fails part-way leaves the list
    as it was, so the same save can be sent again (spools already renamed are not touched twice)."""
    done = inventory.rename_locations(sm, items, step=step)
    after.converted = False            # the person has seen the list and saved it: the converted notice is spent
    storage.save(after)
    log.info("storage locations saved: %d locations%s", len(after.locations), f"; {done['text']}" if done["text"] else "")
    return done


def save(sm, body) -> dict:
    """Save the whole submitted list. Answers {ok, saved: true, text, updated, **view} (`text` is the rename sentence
    "Renamed Rack 1 to PLA rack 1. 18 spools updated." or ""), or, when more than JOB_STEPS_ABOVE spools are renamed,
    {ok, saved: false, job: {steps}}: the save is finished by the job (`job_state`), and a second save is refused
    (409) until it ends. Raises StorageRefused with `errors` per row and field."""
    global _job
    if not _lock.acquire(blocking=False):
        raise StorageRefused("Another change to the storage locations is still running. Try again when it is done.",
                             [], 409)
    release = True
    try:
        before = storage.current()
        taken = inventory._used_locations(sm)
        after, shape = parse(body, before)
        problems = problems_of(before, after, shape, taken)
        if problems:
            raise _refusal(problems, after)
        items = storage.renames(before, after)
        steps = inventory.rename_steps(sm, items) if items else 0
        if steps:
            _job = {"state": "running", "step": None, "progress": 0.0, "text": "", "error": None, "steps": steps}

            def run() -> None:
                global _job
                n = [0]

                def step(text: str) -> None:
                    n[0] += 1
                    _job.update(step={"index": n[0], "count": steps, "text": text}, progress=(n[0] - 1) / steps)
                try:
                    done = _write(sm, before, after, items, step)
                    _job.update(state="done", progress=1.0, text=done["text"])
                except Exception as e:  # noqa: BLE001 - the page gets the reason, the log the trace
                    log.exception("storage rename job")
                    _job.update(state="failed", error=str(e) or type(e).__name__)
                finally:
                    _lock.release()
            threading.Thread(target=run, name="storage-rename", daemon=True).start()
            release = False
            return {"ok": True, "saved": False, "job": {"steps": steps}}
        done = _write(sm, before, after, items)
        _job = None
        return {"ok": True, "saved": True, "text": done["text"], "updated": done["updated"],
                **current_view(sm, storage.current())}
    finally:
        if release:
            _lock.release()
