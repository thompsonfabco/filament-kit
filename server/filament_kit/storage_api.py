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
from .spoolman import SpoolmanError
from .storage import BULK, CONTAINERS, MATERIALS, Location, Problem, Storage

log = logging.getLogger("filament_kit.storage")

JOB_STEPS_ABOVE = inventory.RENAME_BATCH       # up to this many renamed spools: done inside the save's own answer


class StorageRefused(ValueError):
    """The list was not saved. `status` is 400 (the list or change is wrong), 409 (a rename is running) or 502."""

    def __init__(self, message: str, errors: list[dict], status: int = 400):
        super().__init__(message)
        self.errors, self.status = errors, status


# ---------------------------------------------------------------- the messages the server sends

# Every error, fix and notice text of the storage list API, under its key in strings/en.json. The catalogue holds
# exactly the same text, first letter included (test_the_storage_messages_are_the_catalogue_texts keeps them equal), so
# a client that wants the text in another language finds it by the key. {name} holes are filled by `say`.
MESSAGES = {
    "storage_error_list_shape": "Send the whole list as locations.",
    "storage_fix_list_shape": "Send {locations: [...]}, every location in fill order.",
    "storage_error_row_object": "Each location must be an object.",
    "storage_fix_row_object": "Send name, type, fill and the other fields.",
    "storage_error_id_type": "The id must be text or null.",
    "storage_error_id_unknown": "That location is not in the saved list.",
    "storage_fix_id_new": "Leave the id empty for a new location.",
    "storage_error_whole": "Enter a whole number, 1 or more.",
    "storage_fix_whole": "Use digits only, or leave it empty.",
    "storage_error_materials_list": "Materials must be a list of names.",
    "storage_fix_materials_list": "Send the names as a list, e.g. [\"PLA\"].",
    "storage_error_flag": "{field} must be true or false.",
    "storage_fix_flag": "Send true or false.",
    "storage_error_type_fixed": "Move the spools out to change the type.",
    "storage_fix_type_fixed": "Move the spools in {name} to another location first.",
    "storage_error_container_in_use": "{name} holds spools. Move it first, or keep at least {least}.",
    "storage_error_containers_in_use": "{names} hold spools. Move them first, or keep at least {least}.",
    "storage_fix_containers_in_use": "Move the spools out of the containers above {count}, or enter {least} or more.",
    "storage_error_remove_default_overflow": "Make another location the default overflow first.",
    "storage_fix_remove_default_overflow": "Mark another overflow location as the default, then remove {name}.",
    "storage_error_remove_sealed": "Choose another location for sealed spools first.",
    "storage_fix_remove_sealed": "Mark another Bulk storage location for sealed spools, then remove {name}.",
    "storage_error_rename_unfinished": "A rename of storage locations is not finished.",
    "storage_fix_rename_unfinished": "Save the storage locations again; the Hub finishes the rename first.",
    "storage_error_resume_failed": "The unfinished rename of storage locations could not be finished ({reason}).",
    "storage_fix_resume_failed": "Check that Spoolman is running, then save again. Nothing else was saved.",
    "storage_error_busy": "Another change to the storage locations is still running. Try again when it is done.",
    "storage_nothing_saved": "Nothing was saved.",
    "storage_nothing_more_saved": "Nothing more was saved.",
    "storage_error_spoolman_unreachable": "Spoolman is not reachable",
}


def say(key: str, **fill) -> str:
    text = MESSAGES[key]
    return text.format(**fill) if fill else text


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


def _apply_plan(st: Storage, plan: dict) -> Storage:
    """`st` with the renames of a recorded plan applied to the names (and prefixes) they were planned for, all at once
    (a swap swaps). The list is only written after its spools were renamed, so while a plan is pending the saved list
    still has the old names: this is the list the unfinished save was making. An existing set's prefix only follows its
    name (R79 C3), so a containers rename also renames the set when its prefix was its name plus a space."""
    out = storage.copy_of(st)
    for x in out.locations:
        for old, new, containers in plan["renames"]:
            if not containers and x.type == BULK and x.name == old:
                x.name = new
            elif containers and x.type == CONTAINERS and x.container_prefix() == old:
                if x.name + " " == old:
                    x.name = new.rstrip()
                x.prefix = new
            else:
                continue
            break
    return out


def _base() -> Storage:
    """The list a page or a save works on: the saved list, with the unfinished rename (if any) applied, so a person
    never has to retype it and a save does not rename the places back."""
    st = storage.current()
    plan = inventory.pending_rename()
    return _apply_plan(st, plan) if plan is not None else st


def current_view(sm, st: Storage | None = None) -> dict:
    return view(st or _base(), inventory._used_locations(sm))


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
        return Storage([], before.next_id), [Problem(None, "locations", say("storage_error_list_shape"),
                                                     say("storage_fix_list_shape"))]
    old = {x.id: x for x in before.locations if x.id}
    out: list[Location] = []
    for i, r in enumerate(rows):
        def bad(fld, error, fix):
            problems.append(Problem(i, fld, error, fix))
        if not isinstance(r, dict):
            bad("row", say("storage_error_row_object"), say("storage_fix_row_object"))
            out.append(Location(""))
            continue
        loc = Location(name=r["name"] if isinstance(r.get("name"), str) else "",
                       type=r["type"] if isinstance(r.get("type"), str) else BULK if r.get("type") is None else "?")
        ident = r.get("id")
        if ident is not None and not isinstance(ident, str):
            bad("id", say("storage_error_id_type"), say("storage_fix_id_new"))
        elif ident is not None and ident not in old:
            bad("id", say("storage_error_id_unknown"), say("storage_fix_id_new"))
        else:
            loc.id = ident
        for key, fld in (("limit", "limit"), ("count", "count")):
            ok, n = _whole(r.get(key))
            if not ok:
                bad(fld, say("storage_error_whole"), say("storage_fix_whole"))
            elif key == "limit" and loc.type == BULK:
                loc.limit = n
            elif key == "count" and loc.type == CONTAINERS:
                loc.count = n
        loc.fill = r.get("fill", storage.NONE) if isinstance(r.get("fill", storage.NONE), str) else "?"
        mats = r.get("materials", [])
        if isinstance(mats, str):
            mats = mats.split(",")
        if not isinstance(mats, list) or not all(isinstance(m, str) for m in mats):
            bad("materials", say("storage_error_materials_list"), say("storage_fix_materials_list"))
            mats = []
        if loc.fill == MATERIALS:
            loc.materials = [m.strip() for m in mats if m.strip()]
        for key in ("overflow", "default_overflow", "sealed"):
            v = r.get(key, False)
            if not isinstance(v, bool):
                bad(key, say("storage_error_flag", field=key), say("storage_fix_flag"))
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
                out.append(Problem(i, "type", say("storage_error_type_fixed"),
                                   say("storage_fix_type_fixed", name=o.name)))
        elif o.type == CONTAINERS and x.type == CONTAINERS and isinstance(x.count, int):
            over = _above(o, x.count, counts)
            if over:
                least = over[-1][0]
                text = (say("storage_error_container_in_use", name=over[0][1], least=least) if len(over) == 1 else
                        say("storage_error_containers_in_use", names=_and([t for _, t in over]), least=least))
                out.append(Problem(i, "count", text, say("storage_fix_containers_in_use", count=x.count, least=least)))
    for o in before.locations:
        if o.id in kept:
            continue
        if o.default_overflow and not any(x.default_overflow for x in after.locations):
            out.append(Problem(None, "default_overflow", say("storage_error_remove_default_overflow"),
                               say("storage_fix_remove_default_overflow", name=o.name)))
        if o.sealed and not any(x.sealed for x in after.locations):
            out.append(Problem(None, "sealed", say("storage_error_remove_sealed"),
                               say("storage_fix_remove_sealed", name=o.name)))
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
    return StorageRefused(f"{problems[0].error} {say('storage_nothing_saved')}", errors_of(problems, after))


def preview(sm, body) -> dict:
    """The view of an unsaved list with its `errors` (empty = it could be saved): the panel "Where a new spool goes",
    the how-full of each row and the notices, before anything is written. Writes nothing, renames nothing."""
    before = _base()
    taken = inventory._used_locations(sm)
    after, shape = parse(body, before)
    problems = problems_of(before, after, shape, taken)
    renames = storage.renames(before, after)
    return {"ok": not problems, "dry_run": True, **view(after, taken), "errors": errors_of(problems, after),
            "renames": [{"from": r.label[0], "to": r.label[1]} for r in renames]}


UNFINISHED = f"Error: {say('storage_error_rename_unfinished')}\nFix: {say('storage_fix_rename_unfinished')}"

_lock = threading.Lock()          # one save at a time; a running rename job keeps it
_job: dict | None = None


def job_state() -> dict:
    """The rename job of the last save that needed one: {state: none | running | done | failed, step, progress,
    text, error}. `step` is {index, count, text} of the newest batch; `progress` runs 0 to 1."""
    if _job:
        return dict(_job)
    if inventory.pending_rename() is not None:      # a rename left half-done (failed, or the Hub restarted)
        return {"state": "failed", "step": None, "progress": None, "text": "",
                "error": UNFINISHED}
    return {"state": "none", "step": None, "progress": None, "text": "", "error": None}


def _steps_for(sm, items) -> int:
    """How many job steps the spools under the names of `items` need (0 up to JOB_STEPS_ABOVE spools)."""
    n = sum(1 for sp in sm.get("spool") if inventory._renamed(sp.get("location") or "", items) is not None)
    return 0 if n <= JOB_STEPS_ABOVE else -(-n // inventory.RENAME_BATCH)


def _finish_recorded(sm, step) -> dict:
    """Finish the rename a failed save recorded, from the plan alone (no names asked), then write the list it was
    making. A failure (Spoolman down) keeps the plan and refuses with Error and Fix; the next save tries again."""
    plan = inventory.pending_rename()
    try:
        done = inventory.rename_locations(sm, [], step=step)
    except SpoolmanError as e:
        why = str(e) if e.status is not None else say("storage_error_spoolman_unreachable")
        raise StorageRefused(f"Error: {say('storage_error_resume_failed', reason=why)}\n"
                             f"Fix: {say('storage_fix_resume_failed')}", [], 502) from None
    made = _apply_plan(storage.current(), plan)
    storage.save(made, before=made)
    log.info("storage locations: unfinished rename finished; %s", done["text"])
    return done


def _write(sm, before: Storage, after: Storage, items, step=None) -> dict:
    """Rename the spools of the renamed locations, then write the list. A rename that fails part-way leaves the list
    as it was and the plan stays recorded (`inventory.pending_rename`); the next save finishes it first."""
    done = inventory.rename_locations(sm, items, step=step)
    after.converted = False            # the person has seen the list and saved it: the converted notice is spent
    storage.save(after)
    log.info("storage locations saved: %d locations%s", len(after.locations), f"; {done['text']}" if done["text"] else "")
    return done


def _save_all(sm, body, step=None, resumed: bool = False) -> dict:
    """The work of one save: finish the recorded rename (if any), then validate and apply the submitted list on the
    list as it now is saved. Answers {updated, text}: the sentences of every rename done, the resumed one first."""
    texts, updated = [], 0
    if inventory.pending_rename() is not None:
        done = _finish_recorded(sm, step)
        texts.append(done["text"])
        updated += done["updated"]
        resumed = True
    before = storage.current()
    taken = inventory._used_locations(sm)
    after, shape = parse(body, before)
    problems = problems_of(before, after, shape, taken)
    if problems:
        refusal = _refusal(problems, after)
        if resumed:
            refusal.args = (refusal.args[0].replace(say("storage_nothing_saved"), say("storage_nothing_more_saved")),)
        raise refusal
    done = _write(sm, before, after, storage.renames(before, after), step)
    if done["text"]:
        texts.append(done["text"])
    return {"updated": updated + done["updated"], "text": " ".join(texts)}


def save(sm, body) -> dict:
    """Save the whole submitted list. A rename a failed save left half-done is finished first, from its recorded plan,
    and the submitted list is applied on the list that rename was making. Answers {ok, saved: true, text, updated,
    **view} (`text` is the rename sentence "Renamed Rack 1 to PLA rack 1. 18 spools updated." once per rename, or ""),
    or, when more than JOB_STEPS_ABOVE spools are renamed, {ok, saved: false, job: {steps}}: the save is finished by
    the job (`job_state`), and a second save is refused (409) while it runs. Raises StorageRefused with `errors` per
    row and field."""
    global _job
    if not _lock.acquire(blocking=False):
        raise StorageRefused(say("storage_error_busy"), [], 409)
    release = True
    try:
        plan = inventory.pending_rename()
        before = _base()
        after, shape = parse(body, before)
        if plan is None:
            problems = problems_of(before, after, shape, inventory._used_locations(sm))
            if problems:
                raise _refusal(problems, after)
        steps = inventory.rename_steps(sm, []) if plan is not None else 0
        items = storage.renames(before, after)
        steps += _steps_for(sm, items) if items else 0
        if steps:
            _job = {"state": "running", "step": None, "progress": 0.0, "text": "", "error": None, "steps": steps}

            def run() -> None:
                global _job
                n = [0]

                def step(text: str) -> None:
                    n[0] += 1
                    _job.update(step={"index": n[0], "count": steps, "text": text},
                                progress=min(1.0, (n[0] - 1) / steps))
                try:
                    done = _save_all(sm, body, step, plan is not None)
                    _job.update(state="done", progress=1.0, text=done["text"])
                except Exception as e:  # noqa: BLE001 - the page gets the reason, the log the trace
                    log.exception("storage rename job")
                    _job.update(state="failed", error=str(e) or type(e).__name__)
                finally:
                    _lock.release()
            threading.Thread(target=run, name="storage-rename", daemon=True).start()
            release = False
            return {"ok": True, "saved": False, "job": {"steps": steps}}
        _job = None                    # an older job's end is not this save's state
        done = _save_all(sm, body, None, plan is not None)
        return {"ok": True, "saved": True, "text": done["text"], "updated": done["updated"],
                **current_view(sm, storage.current())}
    finally:
        if release:
            _lock.release()
