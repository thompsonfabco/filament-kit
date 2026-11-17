"""`spoolwarden locations` (06 9.15) and the Storage locations screen of `config` (06 8.3).

Both change the list the way the Hub page does: the whole list goes through `storage_api.save` (the same checks, the
same refusals, the same rename of the spools, the same job for a rename of more than 20 spools), so a refusal reads the
same everywhere. `--json` is `storage_api.current_view`: one function behind GET api/storage, the web app's twin and
this command.

    run(args, sm_factory)    the `locations` command
    StorageEditor            the screens of Settings > Storage locations (a numbered list; a number edits)
"""
from __future__ import annotations

import copy
import time
from collections import Counter

from . import config, inventory, menu_ui, output, storage, storage_api
from .spoolman import Spoolman, SpoolmanError
from .storage import ANY, BULK, CONTAINERS, MATERIALS, NONE, Location

FOOTER = "The places fill in this order. Change them: sudo spoolwarden locations -h"


# ---------- the catalogue's words ----------

def _catalogue() -> dict:
    from . import cli
    return cli._hub_catalogue()


def text(key: str, **kw) -> str:
    """The catalogue text of `key` with the {names} filled in; a plural text takes its form from `count`."""
    value = _catalogue()[key]
    if isinstance(value, dict):
        value = value["one" if kw.get("count") == 1 else "other"]
    return value.format(**kw).replace(" · ", output.sym("sep"))


# ---------- the list as text (the table and the screen) ----------

def how_full(row: dict, short: bool = False) -> str:
    """`18 of 20` (a limit), `4 spools`, `9 of 12 containers used`; the table shortens the last to `9 of 12`."""
    if row["type"] == CONTAINERS:
        return f"{row['used']} of {row['count']}" if short else text("storage_used_containers", used=row["used"],
                                                                      count=row["count"])
    if row["limit"] is not None:
        return f"{row['used']} of {row['limit']}" if short else text("storage_used_limit", used=row["used"],
                                                                     limit=row["limit"])
    return text("storage_used_plain", count=row["used"])


def takes(row: dict) -> str:
    if row["fill"] == MATERIALS:
        return ", ".join(row["materials"])
    return text("storage_fill_any") if row["fill"] == ANY else text("storage_takes_none")


def marks(row: dict, rows: list[dict]) -> str:
    """`Overflow`, `Default overflow` (alone while it is the only overflow place; with the other overflow places it is
    `Overflow, Default overflow`) and `Sealed spools`."""
    out = []
    if row["overflow"]:
        others = sum(1 for r in rows if r["overflow"]) > 1
        if not row["default_overflow"] or others:
            out.append(text("storage_badge_overflow"))
        if row["default_overflow"]:
            out.append(text("storage_badge_default_overflow"))
    if row["sealed"]:
        out.append(text("storage_badge_sealed"))
    return ", ".join(out)


def summary(rows: list[dict]) -> str:
    """`4 locations · 2 with a limit` (a containers location always has one: its count)."""
    limited = sum(1 for r in rows if r["type"] == CONTAINERS or r["limit"] is not None)
    return text("cli_storage_summary", count=len(rows), limit=limited)


def row_line(row: dict, rows: list[dict]) -> str:
    return output.sym("sep").join(x for x in (how_full(row), takes(row), marks(row, rows)) if x)


def type_word(kind: str, short: bool = False) -> str:
    if kind == CONTAINERS:
        return "Containers" if short else text("storage_type_containers")
    return text("storage_type_bulk")


def notes(view: dict) -> None:
    """The `Note:` lines of a list (the default overflow without a limit; the converted notice)."""
    for n in view.get("notices", []):
        output.note(n["text"])


def error_text(message: str) -> tuple[str, str | None]:
    """(what, fix) of a text that holds its own `Error:` and `Fix:` lines (storage and inventory make these)."""
    what, _, fix = message.removeprefix("Error: ").partition("\nFix: ")
    return what, fix or None


def reason(e: Exception) -> str:
    """The sentence of a failure of the save (a refusal, the storage's own Error text, Spoolman)."""
    if isinstance(e, storage_api.StorageRefused) and e.errors:
        return e.errors[0]["error"]
    if isinstance(e, SpoolmanError):
        return f"Spoolman did not answer: {e}"
    return error_text(str(e))[0]


def refused(e: "storage_api.StorageRefused") -> int:
    """The first error of a refusal as Error and Fix; exit code 1."""
    if e.errors:
        first = e.errors[0]
        output.error(first["error"], first["fix"] or None)
    else:
        output.error(*error_text(str(e)))
    return output.FAILED


# ---------- the command ----------

def default_spoolman() -> Spoolman:
    """The Spoolman of this Hub for a screen of `config` or `config show`, which must not wait long for it."""
    return Spoolman(config.load()["spoolman_url"], timeout=5)


def _sm(sm_factory):
    from . import cli
    return (sm_factory or cli._default_spoolman)()


def _need_root(sub: str, argv_tail: str) -> int | None:
    from . import cli
    if not cli._no_systemd() and not cli._is_root():
        return output.need_sudo(cli._sudo_command(f"sudo spoolwarden locations {sub} {argv_tail}".rstrip()))
    return None


def _view(sm) -> dict:
    return storage_api.current_view(sm)


def cmd_list(sm_factory) -> int:
    """`locations` (06 9.15): the list in fill order; `--json` is the answer of GET api/storage."""
    try:
        view = _view(_sm(sm_factory))
    except SpoolmanError as e:
        output.error(f"Spoolman did not answer: {e}", "start Spoolman, then run it again.")
        return output.FAILED
    except storage.StorageError as e:
        output.error(*error_text(str(e)))
        return output.FAILED
    output.emit(view)
    rows = view["locations"]
    output.out(summary(rows))
    output.out_lines(output.table(
        ["Pos", "Name", "Type", "How full", "Takes", "Marks"],
        [[r["position"], r["name"], type_word(r["type"], True), how_full(r, True), takes(r), marks(r, rows)]
         for r in rows], long=1, right=(0,)))
    output.out()
    notes(view)
    output.out(FOOTER)
    return 0


class _Plan:
    """A change in progress: the saved list as rows (the dicts of GET api/storage), which the command edits."""

    def __init__(self, sm):
        self.sm = sm
        self.saved = storage.current()
        self.before = storage_api._base()              # the saved list with a half-done rename applied (what a save builds on)
        self.taken = inventory._used_locations(sm)
        self.rows = copy.deepcopy(self.before.describe(self.taken))

    def find(self, name: str) -> dict | None:
        """The row called `name`; while a rename is half done also the row the saved list still calls `name`, so the
        command that was interrupted can be run again as it was typed."""
        low = name.strip().casefold()
        hit = next((r for r in self.rows if r["name"].casefold() == low), None)
        if hit is None:
            old = next((x for x in self.saved.locations if x.name.casefold() == low), None)
            hit = next((r for r in self.rows if old is not None and r["id"] == old.id), None)
        return hit

    def differs(self) -> bool:
        """Is there anything to save: the edited list is another list than the saved one (numbers typed as text count
        as numbers), or a rename is half done and the save finishes it."""
        if inventory.pending_rename() is not None:
            return True
        after, _ = storage_api.parse({"locations": self.rows}, self.before)
        return after.describe(self.taken) != self.before.describe(self.taken)

    def spools_at(self, row: dict) -> int:
        loc = self.before.by_name(row["name"])
        return self.before.used(loc, self.taken) if loc is not None else storage.counts_of(self.taken).get(row["name"], 0)


def _no_such(name: str, plan: _Plan) -> int:
    output.error(f'there is no location called "{name}".',
                 "the locations are " + ", ".join(r["name"] for r in plan.rows) + ".")
    return output.USAGE


def _wait_for_job(sm, steps: int) -> dict:
    """The rename of more than 20 spools runs as a job of the save: show it, wait for its end."""
    with output.wait(f"Renaming spools{output.sym('ellipsis')}", steps=(0, steps)) as w:
        seen = 0
        while True:
            state = storage_api.job_state()
            step = state.get("step")
            if step and step["index"] != seen:
                seen = step["index"]
                w.step(seen, step["count"])
            if state["state"] != "running":
                return state
            time.sleep(0.05)


def _save(sm, rows: list[dict], result: str, *, json_extra: dict | None = None, renames: bool = False) -> int:
    """Send the whole list; print the rename sentence (every rename the save did, one that was left half-done first)
    and the result line (not after the rename the command itself asked for: that sentence is its result), the notes;
    the exit code."""
    try:
        out = storage_api.save(sm, {"locations": rows})
        if not out.get("saved"):
            state = _wait_for_job(sm, out["job"]["steps"])
            if state["state"] != "done":
                what, fix = error_text(state.get("error") or "it did not finish")
                if fix is None:
                    what, fix = (f"renaming the spools stopped: {what.rstrip('.')}.",
                                 "run the same command again; it finishes where it stopped.")
                output.error(what, fix)
                return output.FAILED
            out = {"saved": True, "text": state.get("text", ""), **storage_api.current_view(sm)}
    except storage_api.StorageRefused as e:
        return refused(e)
    except storage.StorageError as e:
        output.error(*error_text(str(e)))
        return output.FAILED
    except ValueError as e:                  # inventory.RenamePending and the like: Error and Fix lines in the text
        output.error(*error_text(str(e)))
        return output.FAILED
    except SpoolmanError as e:
        output.error(f"Spoolman did not answer: {e}. Nothing more was changed.",
                     "run the same command again; it finishes where it stopped.")
        return output.FAILED
    from . import cli
    cli._hub_audit("storage locations changed")
    output.emit({"ok": True, **(json_extra or {}), **{k: out[k] for k in ("locations", "order_by_material",
                                                                          "everything_else", "notices") if k in out}})
    if out.get("text"):
        output.result(out["text"])
    if not (renames and out.get("text")):
        output.result(result)
    notes(out)
    return 0


def _split_takes(raw: str) -> tuple[str, list[str]]:
    word = raw.strip().casefold()
    if word in (ANY, NONE):
        return word, []
    return MATERIALS, [m.strip() for m in raw.split(",") if m.strip()]


def _apply_options(row: dict, a, *, adding: bool) -> int | None:
    """The options of add and edit written into `row`; the exit code of a refusal, else None."""
    if a.type is not None:
        row["type"] = a.type
    kind = row["type"]
    if a.limit is not None and kind != BULK:
        output.error("--limit is for Bulk storage.", "a Containers location takes --count.")
        return output.USAGE
    if a.count is not None and kind != CONTAINERS:
        output.error("--count is for Containers.", "a Bulk storage location takes --limit.")
        return output.USAGE
    if a.limit is not None:
        row["limit"] = None if a.limit.strip().casefold() == "none" else a.limit.strip()
    if a.count is not None:
        row["count"] = a.count.strip()
    if kind == BULK:
        row["count"] = None
    else:
        row["limit"] = None
    if a.takes is not None:
        row["fill"], row["materials"] = _split_takes(a.takes)
        if row["fill"] == MATERIALS and not row["materials"]:
            output.error(text("storage_error_materials"), "separate several with commas.")
            return output.FAILED
    if a.overflow:
        row["overflow"] = True
    if getattr(a, "no_overflow", False):
        if row["default_overflow"]:
            output.error(text("storage_error_remove_default_overflow"),
                         "sudo spoolwarden locations default-overflow <name>")
            return output.FAILED
        row["overflow"] = False
    if row["overflow"] and row["fill"] == ANY:
        output.error(text("storage_error_overflow_any"),
                     "use --takes none or name the materials.")
        return output.FAILED
    return None


def cmd_add(a, sm_factory) -> int:
    stop = _need_root("add", "")
    if stop is not None:
        return stop
    plan = _Plan(_sm(sm_factory))
    row = {"id": None, "name": a.name.strip(), "type": BULK, "limit": None, "count": None, "fill": NONE,
           "materials": [], "overflow": False, "default_overflow": False, "sealed": False}
    stop = _apply_options(row, a, adding=True)
    if stop is not None:
        return stop
    plan.rows.append(row)
    return _save(plan.sm, plan.rows, f"Added {row['name']}.")


def cmd_edit(a, sm_factory) -> int:
    stop = _need_root("edit", "")
    if stop is not None:
        return stop
    plan = _Plan(_sm(sm_factory))
    row = plan.find(a.name)
    if row is None:
        return _no_such(a.name, plan)
    if a.new_name is not None:
        row["name"] = a.new_name.strip()
    stop = _apply_options(row, a, adding=False)
    if stop is not None:
        return stop
    if not plan.differs():
        output.emit({"ok": True, "changed": False})
        output.result("Unchanged.")
        return 0
    return _save(plan.sm, plan.rows, f"Changed {row['name']}.", json_extra={"changed": True},
                 renames=a.new_name is not None)


def cmd_move(a, sm_factory) -> int:
    stop = _need_root("move", "")
    if stop is not None:
        return stop
    plan = _Plan(_sm(sm_factory))
    row = plan.find(a.name)
    if row is None:
        return _no_such(a.name, plan)
    other = None
    if a.before is not None:
        other = plan.find(a.before)
        if other is None:
            return _no_such(a.before, plan)
        if other is row:
            output.error(f"{row['name']} cannot go before itself.", "name another location.")
            return output.USAGE
    rows = [r for r in plan.rows if r is not row]
    at = 0 if a.first else len(rows) if a.last else rows.index(other)
    rows.insert(at, row)
    where = "first" if a.first else "last" if a.last else f"before {other['name']}"
    if [r["id"] for r in rows] == [r["id"] for r in plan.rows]:
        output.emit({"ok": True, "changed": False})
        output.result("Unchanged.")
        return 0
    return _save(plan.sm, rows, f"Moved {row['name']} {where}.", json_extra={"changed": True})


def cmd_remove(a, sm_factory) -> int:
    stop = _need_root("remove", "")
    if stop is not None:
        return stop
    plan = _Plan(_sm(sm_factory))
    row = plan.find(a.name)
    if row is None:
        return _no_such(a.name, plan)
    if row["default_overflow"]:
        output.error(text("storage_error_remove_default_overflow"), "sudo spoolwarden locations default-overflow <name>")
        return output.FAILED
    if row["sealed"]:
        output.error(text("storage_error_remove_sealed"), "sudo spoolwarden locations sealed <name>")
        return output.FAILED
    from . import cli
    stop = cli._confirm(remove_question(row["name"], plan.spools_at(row)), f"removing {row['name']}", yes=a.yes)
    if stop is not None:
        return stop
    rows = [r for r in plan.rows if r is not row]
    return _save(plan.sm, rows, f"Removed {row['name']}.")


def remove_question(name: str, spools: int) -> str:
    """The Hub page's question: `Remove Rack 2? 3 spools are recorded there. They keep that location ...`."""
    body = text("storage_remove_body", count=spools) if spools else text("storage_remove_body_none")
    return f"{text('storage_remove_title', name=name)} {body}"


def cmd_default_overflow(a, sm_factory) -> int:
    stop = _need_root("default-overflow", "")
    if stop is not None:
        return stop
    plan = _Plan(_sm(sm_factory))
    row = plan.find(a.name)
    if row is None:
        return _no_such(a.name, plan)
    if row["type"] != BULK:
        output.error(f"{row['name']} cannot be the default overflow.", "choose a Bulk storage location.")
        return output.FAILED
    if row["default_overflow"]:
        output.emit({"ok": True, "changed": False})
        output.result("Unchanged.")
        return 0
    if row["fill"] == ANY:
        output.error(text("storage_error_overflow_any"),
                     f"sudo spoolwarden locations edit {_quote(row['name'])} --takes none, then run this again.")
        return output.FAILED
    for r in plan.rows:
        r["default_overflow"] = r is row
    row["overflow"] = True
    return _save(plan.sm, plan.rows, f"Made {row['name']} the default overflow.", json_extra={"changed": True})


def cmd_sealed(a, sm_factory) -> int:
    stop = _need_root("sealed", "")
    if stop is not None:
        return stop
    plan = _Plan(_sm(sm_factory))
    row = plan.find(a.name)
    if row is None:
        return _no_such(a.name, plan)
    if row["type"] != BULK:
        output.error(f"{row['name']} cannot take the sealed spools.", "choose a Bulk storage location.")
        return output.FAILED
    if row["sealed"]:
        output.emit({"ok": True, "changed": False})
        output.result("Unchanged.")
        return 0
    for r in plan.rows:
        r["sealed"] = r is row
    return _save(plan.sm, plan.rows, f"Sealed spools now go to {row['name']}.", json_extra={"changed": True})


def _quote(name: str) -> str:
    import shlex
    return shlex.quote(name)


def run(args, sm_factory=None) -> int:
    which = getattr(args, "loc_cmd", None) or "list"
    return {"list": lambda: cmd_list(sm_factory), "add": lambda: cmd_add(args, sm_factory),
            "edit": lambda: cmd_edit(args, sm_factory), "move": lambda: cmd_move(args, sm_factory),
            "remove": lambda: cmd_remove(args, sm_factory),
            "default-overflow": lambda: cmd_default_overflow(args, sm_factory),
            "sealed": lambda: cmd_sealed(args, sm_factory)}[which]()


# ---------- the screens of `config` > Storage locations (06 8.3) ----------

class NoSpools:
    """The spools of a machine that has none yet (the installer's first-run question asks before Spoolman exists)."""

    def get(self, path):
        return []

    def patch(self, path, body):
        raise SpoolmanError("no Spoolman yet", 0)


def _blank_row() -> dict:
    return {"id": None, "name": "", "type": BULK, "limit": None, "count": None, "fill": NONE, "materials": [],
            "overflow": False, "default_overflow": False, "sealed": False}


class StorageEditor:
    """The list as a numbered menu. The owner (the settings menu) keeps what is staged in `owner.staged["storage"]`
    (the whole list, as rows) and saves it with `s`; every change is checked on the spot against the same rules the
    save applies, so a staged list can always be saved."""

    ID = "storage"

    def __init__(self, owner, sm_factory=None):
        self.owner, self.sm_factory = owner, sm_factory
        self.load()

    # ----- state
    def load(self) -> None:
        """The saved list. How full each place is comes from Spoolman, asked the first time a screen needs it (the main
        list of `config` shows only the number of locations)."""
        self.before = storage_api._base()
        self._spools, self._taken = None, Counter()
        self.offline = None
        self.base = copy.deepcopy(self.before.describe(Counter()))

    def spools(self):
        """Spoolman (or, for the installer's question, a machine with no spools), once; None when it did not answer."""
        if self._spools is None:
            if self.owner.embedded:
                self._spools = NoSpools()
            else:
                try:
                    self._spools = (self.sm_factory or default_spoolman)()
                    self._taken = inventory._used_locations(self._spools)
                except (SpoolmanError, OSError, KeyError) as e:
                    self._spools, self._taken, self.offline = False, Counter(), str(e)
        return self._spools or None

    @property
    def taken(self) -> Counter:
        self.spools()
        return self._taken

    @property
    def rows(self) -> list[dict]:
        return self.owner.staged.get(self.ID) or self.base

    def view_rows(self, rows: list[dict] | None = None) -> list[dict]:
        """The rows as the screen shows them (how full, position) for the list `rows`."""
        after, _ = storage_api.parse({"locations": rows or self.rows}, self.before)
        return after.describe(self.taken)

    def problem(self, rows: list[dict]) -> str | None:
        """The first thing wrong in the list `rows`, or None."""
        after, shape = storage_api.parse({"locations": rows}, self.before)
        found = storage_api.problems_of(self.before, after, shape, self.taken)
        return found[0].error if found else None

    def commit(self, rows: list[dict]) -> bool:
        """Stage `rows` when they are valid (and tell the person); False after the Error line."""
        why = self.problem(rows)
        if why:
            self.owner.ui.error(why)
            return False
        clean = self.normal(rows)
        base = self.normal(self.base)
        if clean == self.rows_clean():
            self.owner.ui.say("Unchanged.")
        elif clean == base:
            self.owner.staged.pop(self.ID, None)
            self.owner.ui.say("Unchanged.")
        else:
            self.owner.staged[self.ID] = clean
            self.owner.ui.say("Changed, not saved yet.")
        return True

    def rows_clean(self) -> list[dict]:
        return self.normal(self.rows)

    def normal(self, rows: list[dict]) -> list[dict]:
        """`rows` as the list will hold them (numbers as numbers, the same keys), to compare two lists."""
        after, _ = storage_api.parse({"locations": rows}, self.before)
        return [{"id": x.id, "name": x.name, "type": x.type, "limit": x.limit, "count": x.count, "fill": x.fill,
                 "materials": list(x.materials), "overflow": x.overflow, "default_overflow": x.default_overflow,
                 "sealed": x.sealed} for x in after.locations]

    # ----- screens
    def list_screen(self) -> menu_ui.Screen:
        rows = self.view_rows()
        screen_rows = [menu_ui.Row(r["name"], row_line(r, rows),
                                   note="Enter to change this location; a adds, m moves, r removes.") for r in rows]
        after = []
        for n in storage_api.notices(storage_of(self.rows, self.before)):
            after.append(f"Note: {n['text']}")
        if self.offline:
            after.append(f"Note: Spoolman did not answer ({self.offline}), so how full the places are is not shown.")
        return menu_ui.Screen("storage", "Settings > Storage locations", screen_rows,
                              actions=(("a", "add"), ("m", "move"), ("r", "remove")),
                              save="" if self.owner.embedded else "save", leave="back",
                              changes=len(self.owner.staged), after=tuple(after))

    def location_screen(self, i: int) -> tuple[menu_ui.Screen, list[str]]:
        rows = self.view_rows()
        r = rows[i]
        fields, shown = [], []

        def add(fid: str, label: str, value: str) -> None:
            fields.append(fid)
            shown.append(menu_ui.Row(label, value))
        add("name", "Name", r["name"])
        here = self.spools_in(r)
        kind = type_word(r["type"])
        add("type", "Type", f"{kind} (fixed: {here} {'spool is' if here == 1 else 'spools are'} here)" if here else kind)
        if r["type"] == CONTAINERS:
            add("count", "Number of containers", str(r["count"]))
        else:
            add("limit", "Spool limit", "none" if r["limit"] is None else str(r["limit"]))
        add("fill", "Filled automatically with", self.fill_word(r["fill"]))
        if r["fill"] == MATERIALS:
            add("materials", "Materials", ", ".join(r["materials"]))
        if r["type"] == BULK:
            add("overflow", "Use as overflow", "yes" if r["overflow"] else "no")
            if r["overflow"]:
                add("default", text("storage_make_default_overflow"), "yes" if r["default_overflow"] else "no")
            add("sealed", text("storage_sealed_here"), "yes" if r["sealed"] else "no")
        return menu_ui.Screen(f"storage-{i}", r["name"], shown, save="" if self.owner.embedded else "save",
                              leave="back", changes=len(self.owner.staged)), fields

    def spools_in(self, r: dict) -> int:
        return self.before.used(storage_of([r], self.before).locations[0], self.taken)

    @staticmethod
    def fill_word(fill: str) -> str:
        return {NONE: text("storage_fill_none"), ANY: text("storage_fill_any"),
                MATERIALS: text("storage_fill_materials")}[fill]

    # ----- running
    def run(self) -> None:
        ui, show = self.owner.ui, True
        while True:
            ev = ui.choose(self.list_screen(), show)
            show = False
            if ev[0] == "eof":
                raise self.owner.ended()
            if ev[0] == "leave":
                return
            if ev[0] == "save":
                self.owner.save()
                self.load()
                show = True
            elif ev[0] == "open":
                self.location(ev[1])
                show = True
            elif ev[0] == "action":
                {"a": self.add, "m": self.move, "r": self.remove}[ev[1]]()
                show = True

    def location(self, i: int) -> None:
        ui, show = self.owner.ui, True
        while True:
            if i >= len(self.rows):
                return
            sc, fields = self.location_screen(i)
            ev = ui.choose(sc, show)
            show = False
            if ev[0] == "eof":
                raise self.owner.ended()
            if ev[0] == "leave":
                return
            if ev[0] == "save":
                self.owner.save()
                self.load()
                show = True
            elif ev[0] == "open":
                self.edit(i, fields[ev[1]])

    # ----- one field
    def ask(self, prompt: str) -> str | None:
        raw = self.owner.ui.ask(prompt)
        if raw is None:
            raise self.owner.ended()
        return raw

    def edit(self, i: int, fid: str) -> None:
        rows = copy.deepcopy(self.rows)
        r = rows[i]
        ui = self.owner.ui
        if fid in ("overflow", "default", "sealed"):
            return self.toggle(rows, i, fid)
        if fid == "type":
            return self.edit_type(rows, i)
        if fid == "fill":
            return self.edit_fill(rows, i)
        while True:
            now = {"name": r["name"], "limit": "none" if r["limit"] is None else r["limit"], "count": r["count"],
                   "materials": ", ".join(r["materials"])}[fid]
            label = {"name": "Name", "limit": "Spool limit", "count": "Number of containers",
                     "materials": "Materials"}[fid]
            raw = self.ask(f"{label} [{now}]: ")
            if not raw.strip():
                ui.say("Unchanged.")
                return
            trial = copy.deepcopy(rows)
            self.put(trial[i], fid, raw)
            why = self.problem(trial)
            if why:
                ui.error(why)
                continue
            self.commit(trial)
            return

    @staticmethod
    def put(r: dict, fid: str, raw: str) -> None:
        raw = raw.strip()
        if fid == "name":
            r["name"] = raw
        elif fid == "limit":
            r["limit"] = None if raw.casefold() == "none" else raw
        elif fid == "count":
            r["count"] = raw
        elif fid == "materials":
            r["materials"] = [m.strip() for m in raw.split(",") if m.strip()]

    def toggle(self, rows: list[dict], i: int, fid: str) -> None:
        r, ui = rows[i], self.owner.ui
        if fid == "overflow":
            if r["overflow"] and r["default_overflow"]:
                ui.error(text("storage_error_remove_default_overflow"))
                return
            r["overflow"] = not r["overflow"]
        elif fid == "default":
            if r["default_overflow"]:
                ui.error(text("storage_error_remove_default_overflow"))
                return
            for x in rows:
                x["default_overflow"] = x is r
        else:
            if r["sealed"]:
                ui.error(text("storage_error_remove_sealed"))
                return
            for x in rows:
                x["sealed"] = x is r
        self.commit(rows)

    def choose(self, key: str, title: str, choices: list[tuple[str, str]], now) -> str | None:
        """A choice on its own screen; the chosen value, or None when Enter keeps the current one."""
        ui = self.owner.ui
        rows = [menu_ui.Row(words + ("  (now)" if value == now else "")) for value, words in choices]
        sc = menu_ui.Screen(key, title, rows, leave="back", empty_leaves=True, prompt="Number (Enter keeps it): ")
        ev = ui.choose(sc, True)
        if ev[0] == "eof":
            raise self.owner.ended()
        return choices[ev[1]][0] if ev[0] == "open" else None

    def type_choices(self) -> list[tuple[str, str]]:
        return [(BULK, text("storage_type_bulk")), (CONTAINERS, text("storage_type_containers"))]

    def fill_choices(self, overflow: bool) -> list[tuple[str, str]]:
        return [(v, w) for v, w in ((NONE, text("storage_fill_none")), (ANY, text("storage_fill_any")),
                                    (MATERIALS, text("storage_fill_materials"))) if not (overflow and v == ANY)]

    def edit_type(self, rows: list[dict], i: int) -> None:
        r, ui = rows[i], self.owner.ui
        new = self.choose("storage-type", "Type", self.type_choices(), r["type"])
        if new is None or new == r["type"]:
            ui.say("Unchanged.")
            return
        if self.spools_in(self.view_rows(rows)[i]):
            ui.error(text("storage_error_type_fixed"))
            return
        r["type"] = new
        r["limit"], r["count"] = None, None
        if new == CONTAINERS:
            r["overflow"] = r["default_overflow"] = r["sealed"] = False
            if not self.fill_number(rows, i, "count", "Number of containers"):
                return
        self.commit(rows)

    def fill_number(self, rows: list[dict], i: int, fid: str, label: str) -> bool:
        """Ask for a number until the list is valid with it; False when the person gives up (an empty answer)."""
        while True:
            raw = self.ask(f"{label}: ")
            if not raw.strip():
                self.owner.ui.say("Unchanged.")
                return False
            self.put(rows[i], fid, raw)
            why = self.problem(rows)
            if why is None:
                return True
            self.owner.ui.error(why)

    def edit_fill(self, rows: list[dict], i: int) -> None:
        r, ui = rows[i], self.owner.ui
        new = self.choose("storage-fill", "Filled automatically with", self.fill_choices(r["overflow"]), r["fill"])
        if new is None or new == r["fill"]:
            ui.say("Unchanged.")
            return
        r["fill"] = new
        if new != MATERIALS:
            r["materials"] = []
        elif not r["materials"]:
            if not self.fill_number(rows, i, "materials", "Materials (separated by commas)"):
                return
        self.commit(rows)

    # ----- add, move, remove
    def add(self) -> None:
        rows, ui = copy.deepcopy(self.rows), self.owner.ui
        r = _blank_row()
        rows.append(r)
        i = len(rows) - 1
        while True:                                            # the name first: a row without one is never valid
            raw = self.ask("Name: ")
            if not raw.strip():
                ui.say("Unchanged.")
                return
            r["name"] = raw.strip()
            why = self.problem(rows)
            if not why:
                break
            ui.error(why)
        kind = self.choose("storage-type", "Type", self.type_choices(), BULK)
        r["type"] = kind or BULK
        if r["type"] == CONTAINERS:
            r["count"] = 1
            if not self.fill_number(rows, i, "count", "Number of containers"):
                return
        else:
            raw = self.ask("Spool limit (Enter for no limit): ")
            r["limit"] = raw.strip() or None
            while r["limit"] is not None and (why := self.problem(rows)):
                ui.error(why)
                raw = self.ask("Spool limit (Enter for no limit): ")
                r["limit"] = raw.strip() or None
            yes = ui.yesno("Use it as overflow? Overflow takes spools when their own places are full.")
            if yes is None:
                raise self.owner.ended()
            r["overflow"] = bool(yes)
        fill = self.choose("storage-fill", "Filled automatically with", self.fill_choices(r["overflow"]), NONE)
        r["fill"] = fill or NONE
        if r["fill"] == MATERIALS and not self.fill_number(rows, i, "materials", "Materials (separated by commas)"):
            return
        self.commit(rows)

    def pick(self, question: str) -> int | None:
        """The number of a location typed after `question`, or None (the error was printed, or nothing was typed)."""
        raw = self.ask(question)
        if not raw.strip():
            self.owner.ui.say("Unchanged.")
            return None
        n = len(self.rows)
        if not raw.strip().isdigit() or not 1 <= int(raw) <= n:
            self.owner.ui.error(f"enter a number from 1 to {n}.")
            return None
        return int(raw) - 1

    def move(self) -> None:
        i = self.pick("Move which location? Number: ")
        if i is None:
            return
        n = len(self.rows)
        raw = self.ask(f"Put it at position [{i + 1}]: ")
        if not raw.strip():
            self.owner.ui.say("Unchanged.")
            return
        if not raw.strip().isdigit() or not 1 <= int(raw) <= n:
            self.owner.ui.error(f"Enter a position from 1 to {n}.")
            return
        rows = copy.deepcopy(self.rows)
        row = rows.pop(i)
        rows.insert(int(raw) - 1, row)
        self.commit(rows)

    def remove(self) -> None:
        i = self.pick("Remove which location? Number: ")
        if i is None:
            return
        rows, ui = copy.deepcopy(self.rows), self.owner.ui
        r = rows[i]
        if r["default_overflow"]:
            ui.error(text("storage_error_remove_default_overflow"))
            return
        if r["sealed"]:
            ui.error(text("storage_error_remove_sealed"))
            return
        yes = ui.yesno(remove_question(r["name"], self.spools_in(self.view_rows()[i])))
        if yes is None:
            raise self.owner.ended()
        if not yes:
            return
        del rows[i]
        self.commit(rows)

    # ----- saving
    def save_rows(self, rows: list[dict]):
        """What `s` does with the staged list: the same save as the Hub page. Returns the answer, or raises the
        refusal / Spoolman error for the owner to word."""
        sm = self.spools()
        if sm is None:
            raise SpoolmanError(self.offline or "no answer", 0)
        out = storage_api.save(sm, {"locations": rows})
        if not out.get("saved"):
            with self.owner.ui.suspended():          # only the rename job shows progress on the terminal; a plain save stays in the menu
                state = _wait_for_job(sm, out["job"]["steps"])
            if state["state"] != "done":
                raise ValueError(state.get("error") or "the rename did not finish.")
            out = {"saved": True, "text": state.get("text", "")}
        return out


def storage_of(rows: list[dict], before: storage.Storage) -> storage.Storage:
    """The list of `rows` as a Storage (for what it says about itself: the notices)."""
    after, _ = storage_api.parse({"locations": rows}, before)
    return after
