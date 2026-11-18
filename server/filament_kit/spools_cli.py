"""The spool, catalog and device commands of the command line (R83 10.5, idea B5), each a thin client of the Hub's routes:

    spools [<words>] [--sealed|--opened|--loaded|--low]    `GET /api/spools?q=&filter=`
    spool show <n>                                         `GET /api/spools/<n>`
    spool weigh <n> <grams with the spool>                 `PATCH /api/spools/<n>` {gross}
    spool move <n> <location|auto>                         `PATCH /api/spools/<n>` {location} or {auto_location: true}
    spool empty <n>                                        `PATCH /api/spools/<n>` {empty: true}
    catalog local | local remove <id> | add --ask          `GET /api/library/local`, `DELETE /api/library/local/<id>`,
                                                           `POST /api/library/local/form`
    devices show <id|name> | set <id|name> <setting> <value>   the Hub page's `GET device/<id>`, `POST device/<id>/settings`

Every changing command asks the Hub for a dry run, shows what would change, asks, and then does it; `-y` skips the
asking, and `--json` never asks (output.confirm). Every command gives `output.emit` the object of its route.

`api` is the kit API client (`cli._server_api()`: `get`, `patch`, `post`, `delete`, raising web.slots.SlotError), or
None when no Hub answers. `page` for the device commands is `page(method, route, body=None) -> dict`, one of the Hub
page's routes under `/setup/api/` (R83 10.2), raising SlotError like `api`. cli.py hooks the parsers in with
`add_parser` and runs them with `run`; the printer commands are in klipper_cli.py.

The texts are the module constants named CLI_*: each is a catalogue key in capitals (`cli_spools_empty`), moved
into strings/en.json with its name lower-cased. `catalogue_texts()` lists them, for the drift test.
"""
from __future__ import annotations

import argparse
import sys
import urllib.parse

from . import output

# ---------- texts (catalogue keys; {name} fields are filled with str.format) ----------

CLI_HUB_DOWN = "the Hub is not running, so nothing can be read or changed."
CLI_HUB_DOWN_FIX = "start it: sudo systemctl start filament-kit"
CLI_SPOOLS_EMPTY = "No spools yet. Add your first one from your phone."
CLI_SPOOLS_NONE_MATCH = "No spool matches."
CLI_SPOOLS_COUNT_ONE = "1 spool."
CLI_SPOOLS_COUNT = "{n} spools."
CLI_SPOOLMAN_LINE = "Spoolman: {url}"
CLI_SPOOL_NOT_FOUND = "there is no spool {n}."
CLI_SPOOL_NOT_FOUND_FIX = "list the spools: spoolwarden spools"
CLI_SPOOL_NUMBER_BAD = "{value} is not a spool number."
CLI_GRAMS_BAD = "{value} is not a number of grams."
CLI_NUMBER_BAD = "{value} is not a number."
CLI_SPOOL_WEIGH_PREVIEW = "Spool {n}, {name}: {before} left, would be {after} left."
CLI_SPOOL_WEIGH_ASK = "Set spool {n} to {after} left?"
CLI_SPOOL_WEIGH_DONE = "Spool {n} has {after} left."
CLI_SPOOL_MOVE_PREVIEW = "Spool {n}, {name}: now {before}, would go to {after}."
CLI_SPOOL_MOVE_ASK = "Move spool {n} to {after}?"
CLI_SPOOL_MOVE_DONE = "Spool {n} is now at {after}."
CLI_SPOOL_MOVE_SAME = "Spool {n} is already at {after}."
CLI_SPOOL_EMPTY_PREVIEW = "Spool {n}, {name}: {before} left, would be marked empty."
CLI_SPOOL_EMPTY_ASK = "Mark spool {n} empty?"
CLI_SPOOL_EMPTY_DONE = "Spool {n} is marked empty."
CLI_SPOOL_NOT_PLACED = "no place"
CLI_SPOOL_IN_PRINTER = "in {printer}, {slot}"
CLI_CATALOG_LOCAL_EMPTY = "No entries of your own yet."
CLI_CATALOG_LOCAL_EMPTY_FIX = "Add one: spoolwarden catalog add --ask"
CLI_CATALOG_REMOVE_ASK = "Remove {brand} {name} from your own entries? Slicer presets are rebuilt."
CLI_CATALOG_REMOVE_DONE = "Removed {brand} {name}. Slicer presets are rebuilt in a minute."
CLI_CATALOG_NOT_FOUND = "there is no entry {id} of your own."
CLI_CATALOG_NOT_FOUND_FIX = "list them: spoolwarden catalog local"
CLI_CATALOG_ASK_BRAND = "Brand: "
CLI_CATALOG_ASK_NAME = "Name: "
CLI_CATALOG_ASK_MATERIAL = "Material (for example PLA, PETG, ABS, or Other): "
CLI_CATALOG_ASK_MORE = "Add more details (temperatures, density, notes)?"
CLI_CATALOG_ASK_NOZZLE_MIN = "Nozzle temperature from, in °C (Enter to skip): "
CLI_CATALOG_ASK_NOZZLE_MAX = "Nozzle temperature to, in °C (Enter to skip): "
CLI_CATALOG_ASK_BED_MIN = "Bed temperature from, in °C (Enter to skip): "
CLI_CATALOG_ASK_BED_MAX = "Bed temperature to, in °C (Enter to skip): "
CLI_CATALOG_ASK_DENSITY = "Density, in g/cm³ (Enter to skip): "
CLI_CATALOG_ASK_SPEED = "Maximum volumetric speed, in mm³/s (Enter to skip): "
CLI_CATALOG_ASK_PARENT = "Bambu Studio parent preset (Enter to skip): "
CLI_CATALOG_ASK_NOTES = "Notes (Enter to skip): "
CLI_CATALOG_ASK_REQUIRED = "{field} is needed."
CLI_CATALOG_ADD_ASK = "Add {brand} {name} ({material})?"
CLI_CATALOG_ADD_DONE = "Added. Slicer presets are rebuilt in a minute."
CLI_CATALOG_ADD_PROBLEM = "{field}: {text}"
CLI_CATALOG_ADD_NO_TERMINAL = "asking for the entry needs a terminal."
CLI_CATALOG_ADD_NO_TERMINAL_FIX = "give an entry file instead: spoolwarden catalog add <file>"
CLI_DEVICE_NOT_FOUND = "there is no device {name}."
CLI_DEVICE_NOT_FOUND_FIX = "list them: spoolwarden devices"
CLI_DEVICE_AMBIGUOUS = "{name} fits more than one device: {names}."
CLI_DEVICE_AMBIGUOUS_FIX = "give the id."
CLI_DEVICE_NO_SETTINGS = "{name} has no settings the Hub can change."
CLI_DEVICE_SETTING_UNKNOWN = "{name} has no setting {setting}."
CLI_DEVICE_SETTING_UNKNOWN_FIX = "its settings are: {ids}"
CLI_DEVICE_VALUE_BAD = "{value} is not a value for {setting}: {why}."
CLI_DEVICE_WHY_SWITCH = "use on or off"
CLI_DEVICE_WHY_CHOICE = "choose one of {choices}"
CLI_DEVICE_WHY_NUMBER = "give a number from {low} to {high}"
CLI_DEVICE_WHY_NUMBER_ANY = "give a number"
CLI_DEVICE_SET_ASK = "Set {label} to {value} on {device}?"
CLI_DEVICE_SET_DONE = "{label} is now {value} on {device}."
CLI_DEVICE_SET_SAME = "{label} is already {value} on {device}."
CLI_DEVICE_KIND_PHONE = "Phone"
CLI_DEVICE_KIND_PC = "Slicer Sync PC"
CLI_DEVICE_KIND_STATION = "Weigh Station"
CLI_DEVICE_KIND_WEB = "Web app"
CLI_DEVICE_KIND_READER = "Tag Reader"
CLI_DEVICE_KIND_BUILTIN = "built in"
CLI_DEVICE_VERSION_UNKNOWN = "Version not known"

_KINDS = {"phone": CLI_DEVICE_KIND_PHONE, "pc": CLI_DEVICE_KIND_PC, "station": CLI_DEVICE_KIND_STATION,
          "web": CLI_DEVICE_KIND_WEB, "reader": CLI_DEVICE_KIND_READER, "builtin": CLI_DEVICE_KIND_BUILTIN}


def catalogue_texts() -> dict[str, str]:
    """{catalogue key: English text} of every CLI_* constant of this module and of klipper_cli (for part B's move into
    strings/en.json and for the drift test)."""
    from . import klipper_cli
    out = {}
    for mod in (sys.modules[__name__], klipper_cli):
        out.update({k.lower(): v for k, v in vars(mod).items() if k.startswith("CLI_") and isinstance(v, str)})
    return out


# ---------- shared by the command modules ----------

def fail(e) -> int:
    """Print a refusal of the Hub (a web.slots.SlotError) as an error; its exit code (2 for what was asked wrongly,
    4 when nothing answered, else 1)."""
    if getattr(e, "code", None) == "unreachable":
        output.error(CLI_HUB_DOWN, CLI_HUB_DOWN_FIX)
        return output.HUB_DOWN
    output.error(str(e).rstrip(".") + ".")
    return output.USAGE if getattr(e, "http", None) in (400, 404) else output.FAILED


def down() -> int:
    """No Hub answers (`api` is None)."""
    output.error(CLI_HUB_DOWN, CLI_HUB_DOWN_FIX)
    return output.HUB_DOWN


def grams(value) -> str:
    """A weight as the commands print it: `512 g`, `512.5 g`, or `unknown`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "unknown"
    return f"{value:g} g"


def spool_name(view: dict) -> str:
    """Brand and name of a spool view (its material when it has neither)."""
    return f"{view.get('vendor') or ''} {view.get('name') or ''}".strip() or view.get("material") or "no name"


def where(view: dict) -> str:
    """Where a spool is: in a printer's slot, else its location."""
    loaded = view.get("loaded")
    if loaded:
        return CLI_SPOOL_IN_PRINTER.format(printer=loaded.get("printer"), slot=loaded.get("slot"))
    return view.get("location") or CLI_SPOOL_NOT_PLACED


def confirmed(question: str, doing: str, rerun: str, yes: bool) -> int | None:
    """None to go on, else the exit code (output.confirm: 5 after no, 2 with no terminal and no -y or under --json)."""
    return output.confirm(question, yes=yes, doing=doing, rerun=rerun + " --yes" if "--yes" not in rerun else rerun)


def _kv(pairs: list[tuple[str, object]]) -> list[str]:
    width = max(len(k) for k, _ in pairs)
    return [f"  {k:<{width}}  {v}" for k, v in pairs]


# ---------- spools ----------

FILTERS = ("sealed", "opened", "loaded", "low")


def cmd_spools(api, words: list[str] | None = None, filter: str | None = None) -> int:
    """`spools`: the spools matching every word and the one filter, one row each, then the count and Spoolman's address."""
    if api is None:
        return down()
    from .web.slots import SlotError
    query = {k: v for k, v in (("q", " ".join(words or [])), ("filter", filter)) if v}
    try:
        r = api.get("/api/spools" + ("?" + urllib.parse.urlencode(query) if query else ""))
    except SlotError as e:
        return fail(e)
    output.emit(r)
    rows = r.get("spools") or []
    if not rows:
        output.out(CLI_SPOOLS_NONE_MATCH if query else CLI_SPOOLS_EMPTY)
    else:
        views = [x.get("view") or {} for x in rows]
        output.out_lines(output.table(
            ["No", "Filament", "Material", "Left", "Where", "State"],
            [[v.get("id"), spool_name(v), v.get("material") or "", grams(v.get("remaining_g")), where(v),
              ", ".join(x for x in (v.get("state") or "", "low" if v.get("low") else "", "tagged" if v.get("tag") else "")
                        if x)] for v in views], long=1, right=(0, 3)))
        output.out()
        output.out(CLI_SPOOLS_COUNT_ONE if len(rows) == 1 else CLI_SPOOLS_COUNT.format(n=r.get("total", len(rows))))
    if r.get("spoolman_url"):
        output.out(CLI_SPOOLMAN_LINE.format(url=r["spoolman_url"]))
    return 0


def _number(value) -> int | None:
    try:
        n = int(str(value).lstrip("#"))
        return n if n > 0 else None
    except ValueError:
        return None


def _spool_error(e, n: int) -> int:
    if getattr(e, "http", None) == 404 or getattr(e, "code", None) == "not_found":
        output.error(CLI_SPOOL_NOT_FOUND.format(n=n), CLI_SPOOL_NOT_FOUND_FIX)
        return output.USAGE
    return fail(e)


def cmd_spool_show(api, number) -> int:
    n = _number(number)
    if n is None:
        output.error(CLI_SPOOL_NUMBER_BAD.format(value=number), CLI_SPOOL_NOT_FOUND_FIX)
        return output.USAGE
    if api is None:
        return down()
    from .web.slots import SlotError
    try:
        r = api.get(f"/api/spools/{n}")
    except SlotError as e:
        return _spool_error(e, n)
    output.emit(r)
    v = r.get("view") or {}
    net = v.get("net_g")
    output.out_lines([f"Spool {n}: {spool_name(v)}"] + _kv([
        ("Material", v.get("material") or "unknown"), ("Left", grams(v.get("remaining_g")) + (
            f" of {grams(net)}" if net else "")), ("Empty spool", grams(v.get("tare_g"))),
        ("State", ", ".join(x for x in (v.get("state") or "unknown", "running low" if v.get("low") else "") if x)),
        ("Where", where(v)), ("Tag", v.get("tag") or "none"), ("Lot", v.get("lot") or "none")]))
    return 0


def _change(api, number, body: dict, *, command: str, preview, ask, done, yes: bool) -> int:
    """The shared run of weigh, move and empty: dry run, what would change (`preview(before, after)`), the question
    (`ask(after)`), the real change, its result line (`done(after)`; None: nothing changes, a line says so)."""
    n = _number(number)
    if n is None:
        output.error(CLI_SPOOL_NUMBER_BAD.format(value=number), CLI_SPOOL_NOT_FOUND_FIX)
        return output.USAGE
    if api is None:
        return down()
    from .web.slots import SlotError
    try:
        dry = api.patch(f"/api/spools/{n}", {**body, "dry_run": True})
    except SlotError as e:
        return _spool_error(e, n)
    before, after = dry.get("before") or {}, dry.get("view") or {}
    line = preview(n, before, after)
    if line is None:                    # the spool already is as asked
        output.emit({**dry, "dry": False})
        output.out(done(n, after, same=True))
        return 0
    output.out(line)
    rc = confirmed(ask(n, after), f"changing spool {n}", f"spoolwarden spool {command}", yes)
    if rc is not None:
        return rc
    try:
        r = api.patch(f"/api/spools/{n}", {**body, "dry_run": False})
    except SlotError as e:
        return _spool_error(e, n)
    output.emit(r)
    output.out(done(n, r.get("view") or after, same=False))
    return 0


def cmd_spool_weigh(api, number, weight, yes: bool = False) -> int:
    try:
        gross = float(weight)
        if gross != gross or gross in (float("inf"), float("-inf")):
            raise ValueError
    except (TypeError, ValueError):
        output.error(CLI_GRAMS_BAD.format(value=weight))
        return output.USAGE
    cmd = f"weigh {number} {weight}"
    return _change(
        api, number, {"gross": gross}, command=cmd, yes=yes,
        preview=lambda n, b, a: CLI_SPOOL_WEIGH_PREVIEW.format(
            n=n, name=spool_name(a or b), before=grams(b.get("remaining_g")), after=grams(a.get("remaining_g"))),
        ask=lambda n, a: CLI_SPOOL_WEIGH_ASK.format(n=n, after=grams(a.get("remaining_g"))),
        done=lambda n, a, same: CLI_SPOOL_WEIGH_DONE.format(n=n, after=grams(a.get("remaining_g"))))


def cmd_spool_move(api, number, location: str, yes: bool = False) -> int:
    auto = location.strip().lower() == "auto"
    body = {"auto_location": True} if auto else {"location": location}

    def preview(n, b, a):
        return None if (a.get("location") == b.get("location") and not auto) else CLI_SPOOL_MOVE_PREVIEW.format(
            n=n, name=spool_name(a or b), before=b.get("location") or CLI_SPOOL_NOT_PLACED,
            after=a.get("location") or CLI_SPOOL_NOT_PLACED)

    return _change(
        api, number, body, command=f"move {number} {location}", yes=yes, preview=preview,
        ask=lambda n, a: CLI_SPOOL_MOVE_ASK.format(n=n, after=a.get("location") or CLI_SPOOL_NOT_PLACED),
        done=lambda n, a, same: (CLI_SPOOL_MOVE_SAME if same else CLI_SPOOL_MOVE_DONE).format(
            n=n, after=a.get("location") or CLI_SPOOL_NOT_PLACED))


def cmd_spool_empty(api, number, yes: bool = False) -> int:
    return _change(
        api, number, {"empty": True}, command=f"empty {number}", yes=yes,
        preview=lambda n, b, a: CLI_SPOOL_EMPTY_PREVIEW.format(n=n, name=spool_name(b), before=grams(b.get("remaining_g"))),
        ask=lambda n, a: CLI_SPOOL_EMPTY_ASK.format(n=n), done=lambda n, a, same: CLI_SPOOL_EMPTY_DONE.format(n=n))


# ---------- the catalog's own entries ----------

def cmd_catalog_local(api) -> int:
    if api is None:
        return down()
    from .web.slots import SlotError
    try:
        r = api.get("/api/library/local")
    except SlotError as e:
        return fail(e)
    output.emit(r)
    entries = r.get("entries") or []
    if not entries:
        output.out(CLI_CATALOG_LOCAL_EMPTY)
        output.out(CLI_CATALOG_LOCAL_EMPTY_FIX)
        return 0
    output.out_lines(output.table(["Id", "Brand", "Name", "Material", "Added"],
                                  [[e.get("id"), e.get("brand"), e.get("name"), e.get("material"), e.get("added") or ""]
                                   for e in entries], long=2))
    return 0


def cmd_catalog_local_remove(api, entry_id: str, yes: bool = False) -> int:
    if api is None:
        return down()
    from .web.slots import SlotError
    try:
        entries = api.get("/api/library/local").get("entries") or []
    except SlotError as e:
        return fail(e)
    entry = next((e for e in entries if str(e.get("id")) == entry_id), None)
    if entry is None:
        output.error(CLI_CATALOG_NOT_FOUND.format(id=entry_id), CLI_CATALOG_NOT_FOUND_FIX)
        return output.USAGE
    rc = confirmed(CLI_CATALOG_REMOVE_ASK.format(**{k: entry.get(k) for k in ("brand", "name")}),
                   f"removing {entry.get('brand')} {entry.get('name')}", f"spoolwarden catalog local remove {entry_id}", yes)
    if rc is not None:
        return rc
    try:
        r = api.delete(f"/api/library/local/{urllib.parse.quote(entry_id, safe='')}")
    except SlotError as e:
        return fail(e) if getattr(e, "http", None) != 404 else _missing_entry(entry_id)
    output.emit(r)
    output.out(CLI_CATALOG_REMOVE_DONE.format(**{k: entry.get(k) for k in ("brand", "name")}))
    return 0


def _missing_entry(entry_id: str) -> int:
    output.error(CLI_CATALOG_NOT_FOUND.format(id=entry_id), CLI_CATALOG_NOT_FOUND_FIX)
    return output.USAGE


_MORE = (("nozzle_min", CLI_CATALOG_ASK_NOZZLE_MIN, float), ("nozzle_max", CLI_CATALOG_ASK_NOZZLE_MAX, float),
         ("bed_min", CLI_CATALOG_ASK_BED_MIN, float), ("bed_max", CLI_CATALOG_ASK_BED_MAX, float),
         ("density", CLI_CATALOG_ASK_DENSITY, float), ("max_volumetric_speed", CLI_CATALOG_ASK_SPEED, float),
         ("bambu_parent", CLI_CATALOG_ASK_PARENT, str), ("notes", CLI_CATALOG_ASK_NOTES, str))


def cmd_catalog_add_ask(api, *, ask=input, yes: bool = False) -> int:
    """`catalog add --ask`: Brand, Name and Material (each needed), then, when wanted, the "More (optional)" values in
    the form's order. The Hub builds the entry from the values (`POST /api/library/local/form`). `ask(prompt)`: the
    terminal's input (a test's own)."""
    if not output.terminal() and ask is input:
        output.error(CLI_CATALOG_ADD_NO_TERMINAL, CLI_CATALOG_ADD_NO_TERMINAL_FIX)
        return output.USAGE
    if api is None:
        return down()
    from .web.slots import SlotError
    values: dict = {}
    try:
        for key, prompt in (("brand", CLI_CATALOG_ASK_BRAND), ("name", CLI_CATALOG_ASK_NAME),
                            ("material", CLI_CATALOG_ASK_MATERIAL)):
            answer = (ask(prompt) or "").strip()
            if not answer:
                output.error(CLI_CATALOG_ASK_REQUIRED.format(field=key.capitalize()))
                return output.USAGE
            values[key] = answer
        more = (ask(CLI_CATALOG_ASK_MORE + " [y/N] ") or "").strip().lower() in ("y", "yes")
        for key, prompt, kind in _MORE if more else ():
            answer = (ask(prompt) or "").strip()
            if answer:
                try:
                    values[key] = kind(answer)
                except ValueError:
                    output.error(CLI_NUMBER_BAD.format(value=answer))
                    return output.USAGE
    except (EOFError, KeyboardInterrupt):
        output.result("Nothing changed.")
        return output.CANCELLED
    rc = confirmed(CLI_CATALOG_ADD_ASK.format(**values), "adding the entry", "spoolwarden catalog add --ask", yes)
    if rc is not None:
        return rc
    try:
        r = api.post("/api/library/local/form", values)
    except SlotError as e:
        problems = getattr(e, "problems", None) or []
        if getattr(e, "code", None) == "invalid_entry" and problems:
            for p in problems:
                output.err(CLI_CATALOG_ADD_PROBLEM.format(field=p.get("field"), text=p.get("text")))
            return output.USAGE
        return fail(e)
    output.emit(r)
    output.out(CLI_CATALOG_ADD_DONE)
    return 0


# ---------- devices ----------

def kind_word(kind: str | None) -> str:
    """The word for a device row's kind (R83 9.1); empty when it has none."""
    return _KINDS.get(kind or "", "")


def version_cell(row: dict) -> str:
    return str(row["version"]) if row.get("version") else CLI_DEVICE_VERSION_UNKNOWN


def _find_device(page, ident: str):
    """(row, None) of the device the id or name stands for, else (None, exit code) after the error was printed."""
    rows = page("GET", "devices").get("devices") or []
    exact = [r for r in rows if r.get("id") == ident] or [r for r in rows if str(r.get("name")).lower() == ident.lower()]
    found = exact or [r for r in rows if str(r.get("name")).lower().startswith(ident.lower())]
    if len(found) == 1:
        return found[0], None
    if found:
        output.error(CLI_DEVICE_AMBIGUOUS.format(name=ident, names=", ".join(f"{r['name']} ({r['id']})" for r in found)),
                     CLI_DEVICE_AMBIGUOUS_FIX)
    else:
        output.error(CLI_DEVICE_NOT_FOUND.format(name=ident), CLI_DEVICE_NOT_FOUND_FIX)
    return None, output.USAGE


def _setting_text(s: dict) -> str:
    v = s.get("value")
    if s.get("kind") == "switch":
        return "on" if v else "off"
    return "" if v is None else str(v)


def cmd_devices_show(page, ident: str) -> int:
    from .web.slots import SlotError
    try:
        row, rc = _find_device(page, ident)
        if row is None:
            return rc
        r = page("GET", f"device/{urllib.parse.quote(str(row['id']), safe='')}") if row.get("page") else {"device": row}
    except SlotError as e:
        return fail(e)
    output.emit(r)
    d = r.get("device") or row
    pairs = [("Kind", kind_word(d.get("kind")) or "unknown"), ("Version", version_cell(d))]
    if d.get("paired"):
        pairs.append(("Paired", d["paired"]))
    pairs.append(("Last seen", d.get("last_seen") or "never"))
    if d.get("reachable") is not None:
        pairs.append(("Connection", "answering" if d["reachable"] else "not answering"))
    out = [d.get("name") or ident] + _kv(pairs)
    if d.get("out_of_date") and d.get("advice"):
        out += output.status_row("needs a look", d["advice"])
    status = r.get("status")
    if isinstance(status, dict) and status:
        out += ["", "Status"] + _kv([(str(k), "" if v is None else str(v)) for k, v in status.items()
                                       if not isinstance(v, (dict, list))])
    if r.get("settings"):
        out += [""] + output.table(["Setting", "Value", "Name"], [[s["id"], _setting_text(s), s.get("label") or ""]
                                                                  for s in r["settings"]], long=2)
    output.out_lines(out)
    return 0


def _setting_value(s: dict, raw: str):
    """(the value in the setting's own type, None) or (None, why it is not one)."""
    kind = s.get("kind")
    if kind == "switch":
        word = raw.strip().lower()
        if word in ("on", "yes", "true", "1"):
            return True, None
        if word in ("off", "no", "false", "0"):
            return False, None
        return None, CLI_DEVICE_WHY_SWITCH
    if kind == "choice":
        choices = [str(c) for c in s.get("choices") or []]
        hit = next((c for c in choices if c.lower() == raw.strip().lower()), None)
        return (hit, None) if hit is not None else (None, CLI_DEVICE_WHY_CHOICE.format(choices=", ".join(choices)))
    if kind == "number":
        low, high = s.get("min"), s.get("max")
        try:
            n = float(raw)
            n = int(n) if n == int(n) else n
            if (low is not None and n < low) or (high is not None and n > high):
                raise ValueError
            return n, None
        except ValueError:
            return None, (CLI_DEVICE_WHY_NUMBER.format(low=low, high=high) if low is not None and high is not None
                          else CLI_DEVICE_WHY_NUMBER_ANY)
    return raw, None


def cmd_devices_set(page, ident: str, setting: str, value: str, yes: bool = False) -> int:
    from .web.slots import SlotError
    try:
        row, rc = _find_device(page, ident)
        if row is None:
            return rc
        path = f"device/{urllib.parse.quote(str(row['id']), safe='')}"
        settings = (page("GET", path).get("settings") or []) if row.get("page") else []
        if not settings:
            output.error(CLI_DEVICE_NO_SETTINGS.format(name=row["name"]))
            return output.USAGE
        s = next((x for x in settings if x["id"].lower() == setting.lower()), None)
        if s is None:
            output.error(CLI_DEVICE_SETTING_UNKNOWN.format(name=row["name"], setting=setting),
                         CLI_DEVICE_SETTING_UNKNOWN_FIX.format(ids=", ".join(x["id"] for x in settings)))
            return output.USAGE
        new, why = _setting_value(s, value)
        if why:
            output.error(CLI_DEVICE_VALUE_BAD.format(value=value, setting=s["id"], why=why))
            return output.USAGE
        shown = dict(s, value=new)
        label = s.get("label") or s["id"]
        if new == s.get("value"):
            output.emit({"settings": settings})
            output.out(CLI_DEVICE_SET_SAME.format(label=label, value=_setting_text(shown), device=row["name"]))
            return 0
        rc = confirmed(CLI_DEVICE_SET_ASK.format(label=label, value=_setting_text(shown), device=row["name"]),
                       f"changing {label} on {row['name']}", f"spoolwarden devices set {ident} {setting} {value}", yes)
        if rc is not None:
            return rc
        r = page("POST", path + "/settings", {s["id"]: new})
    except SlotError as e:
        return fail(e)
    output.emit(r)
    output.out(CLI_DEVICE_SET_DONE.format(label=label, value=_setting_text(shown), device=row["name"]))
    return 0


# ---------- the parsers and their run (hooked in by cli.py) ----------

def add_parser(sub) -> None:
    """`spools` and `spool show|weigh|move|empty`."""
    sp = sub.add_parser("spools", help="the spools: search by words, or only sealed, opened, loaded or running low")
    sp.add_argument("words", nargs="*", help="brand, name, material, place or tag: every word must match")
    group = sp.add_mutually_exclusive_group()
    for f, text in (("sealed", "only sealed spools"), ("opened", "only opened spools"),
                    ("loaded", "only spools in a printer"), ("low", "only spools running low")):
        group.add_argument("--" + f, dest="filter", action="store_const", const=f, help=text)
    one = sub.add_parser("spool", help="one spool: show, weigh, move, mark empty")
    ones = one.add_subparsers(dest="spool_cmd", required=True)
    ones.add_parser("show", help="its facts").add_argument("number")
    w = ones.add_parser("weigh", help="set its weight from a weighing with the spool on the scale")
    w.add_argument("number")
    w.add_argument("grams", help="grams, the spool included")
    m = ones.add_parser("move", help="put it in a place, or auto for the place the Hub picks")
    m.add_argument("number")
    m.add_argument("location")
    ones.add_parser("empty", help="mark it empty").add_argument("number")
    for p in (w, m, ones.choices["empty"]):
        p.add_argument("-y", "--yes", action="store_true", help="do not ask")


def run(args, api) -> int:
    if args.cmd == "spools":
        return cmd_spools(api, args.words, args.filter)
    c = args.spool_cmd
    if c == "show":
        return cmd_spool_show(api, args.number)
    if c == "weigh":
        return cmd_spool_weigh(api, args.number, args.grams, args.yes)
    if c == "move":
        return cmd_spool_move(api, args.number, args.location, args.yes)
    return cmd_spool_empty(api, args.number, args.yes)
