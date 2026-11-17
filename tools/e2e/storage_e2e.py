"""The pure parts of e2e scenario h (storage locations after an upgrade): the fixed spool list, the old release's
placement rule as an oracle, the settings variants, placement comparison, and the owner/mode and ACL parsing. No host,
no network, nothing from the kit: tested without WSL by server/tests/test_e2e_storage.py. The host side is
E2E.h_storage in e2e.py.
"""
from __future__ import annotations

import re
import struct
from collections import Counter

# The old settings' defaults (config.DEFAULTS before storage.xml): a variant names only what it changes.
OLD_DEFAULTS = {"locations": ["Sealed stock", "Rack 1", "Storage box", "Overflow"], "pla_location": "Rack 1",
                "box_prefix": "Storage box ", "box_count": 0, "overflow": "Overflow", "sealed_location": "Sealed stock"}

# What `config set` of the old release writes: setting -> key (`locations` is a comma list). sealed_location has no
# `config set` key in v0.6.x: it is written to config.json, which the old release reads.
OLD_KEYS = {"locations": "locations", "pla_location": "placement.pla_location", "box_prefix": "placement.box_prefix",
            "box_count": "placement.box_count", "overflow": "placement.overflow"}

# The settings an owner changed, named for the check texts. The main one is upgraded for real (the old release
# keeps it to the end); the others are migrated again from config.json on the new release.
VARIANTS = [
    {"name": "boxes with a trailing space", "main": True,
     "locations": ["Sealed shelf", "PLA rack", "Dry box", "Overflow bin", "Spare"],
     "pla_location": "PLA rack", "box_prefix": "Dry box ", "box_count": 3, "overflow": "Overflow bin",
     "sealed_location": "Sealed shelf"},
    {"name": "boxes with no space after the prefix", "main": False,
     "locations": ["Cold room", "Shelf P", "Floor"],
     "pla_location": "Shelf P", "box_prefix": "Bin", "box_count": 4, "overflow": "Floor",
     "sealed_location": "Cold room"},
    {"name": "no boxes, a blank prefix", "main": False,
     "locations": ["Sealed stock", "Rack Q", "Garage"],
     "pla_location": "Rack Q", "box_prefix": " ", "box_count": 0, "overflow": "Garage",
     "sealed_location": "Sealed stock"},
]


def variants_main_last() -> list[dict]:
    """The order the old release gets them in: the one that is upgraded for real is the last one set."""
    return [v for v in VARIANTS if not v["main"]] + [v for v in VARIANTS if v["main"]]


def fixed_spools() -> list[dict]:
    """The fixed list of spools added (one item each, in this order). More non-PLA opened spools (5) than the boxes of
    any variant (3, 4, 0), so the overflow place is hit; PLA, PLA+, PETG, ABS, TPU and two sealed spools."""
    def item(name, material, count, sealed):
        return {"vendor": "E2E Test Co", "name": name, "material": material, "color_hex": "336699", "net": 1000,
                "tare": 200, "density": 1.24, "count": count, "nozzle": 210, "bed": 60, "sealed": sealed}
    return [item("E2E PLA Red", "PLA", 2, False), item("E2E PLA+ Blue", "PLA+", 1, False),
            item("E2E PETG Black", "PETG", 2, False), item("E2E ABS Grey", "ABS", 1, False),
            item("E2E TPU Green", "TPU", 2, False), item("E2E Sealed PETG White", "PETG", 1, True),
            item("E2E Sealed PLA Gold", "PLA", 1, True)]


def old_settings(variant: dict) -> dict:
    return {**OLD_DEFAULTS, **{k: v for k, v in variant.items() if k in OLD_DEFAULTS}}


def cli_args(variant: dict) -> list[tuple[str, str]]:
    """(key, value) of each `config set` the old release gets for a variant, in order."""
    s = old_settings(variant)
    return [(OLD_KEYS[k], ",".join(s[k]) if k == "locations" else str(s[k])) for k in OLD_KEYS]


def cfg_with(cfg: dict, variant: dict) -> dict:
    """A copy of a config.json dict carrying a variant's six old keys (what the old release left in it)."""
    s = old_settings(variant)
    out = {**cfg, "locations": list(s["locations"])}
    out["placement"] = {**(cfg.get("placement") or {}), "pla_location": s["pla_location"],
                        "box_prefix": s["box_prefix"], "box_count": s["box_count"], "overflow": s["overflow"],
                        "sealed_location": s["sealed_location"]}
    return out


def old_keys_of(cfg: dict) -> dict:
    """The six old storage keys of a config.json dict, for 'untouched' comparisons."""
    pl = cfg.get("placement") or {}
    return {"locations": cfg.get("locations"), **{k: pl.get(k) for k in
            ("pla_location", "box_prefix", "box_count", "overflow", "sealed_location")}}


def old_rule(items: list[dict], variant: dict, taken: set[str] | None = None) -> list[tuple[str, int, str]]:
    """Where the old release (placement.place of v0.6.x) puts each spool: (item name, nth of its count, location).
    sealed -> the sealed place; a material starting with PLA -> the PLA place; else the lowest free box
    (prefix + two digits), the overflow place when none is free."""
    s = old_settings(variant)
    used = set(taken or ())
    out: list[tuple[str, int, str]] = []
    for it in items:
        for n in range(1, int(it.get("count", 1)) + 1):
            if it.get("sealed") is not False:
                loc = s["sealed_location"]
            elif str(it.get("material", "")).upper().startswith("PLA"):
                loc = s["pla_location"]
            else:
                loc = next((f"{s['box_prefix']}{b:02d}" for b in range(1, int(s["box_count"]) + 1)
                            if f"{s['box_prefix']}{b:02d}" not in used), s["overflow"])
                used.add(loc)
            out.append((it["name"], n, loc))
    return out


def compare_placements(old: list[tuple[str, int, str]], new: list[tuple[str, int, str]]) -> list[str]:
    """One line per spool that is not at the same place (or missing on a side); [] = the same."""
    a = {(name, n): loc for name, n, loc in old}
    b = {(name, n): loc for name, n, loc in new}
    out = []
    for key in sorted(set(a) | set(b)):
        if a.get(key) != b.get(key):
            out.append(f"{key[0]} #{key[1]}: {a.get(key)!r} -> {b.get(key)!r}")
    return out


def expected_used(rows: list[dict], placements: list[tuple[str, int, str]]) -> dict[str, int]:
    """How full each location of GET api/storage should be for spools at these places: a bulk place counts spools,
    a containers set counts the containers that hold one. Keys are location names; text at no location is not
    counted (the API's rows know only their own)."""
    per = Counter(loc for _, _, loc in placements)
    out = {}
    for r in rows:
        if r.get("type") == "containers":
            names = {c["name"] for c in r.get("containers") or []}
            out[r["name"]] = sum(1 for t in per if t in names)
        else:
            out[r["name"]] = per.get(r["name"], 0)
    return out


def container_names(rows: list[dict]) -> set[str]:
    return {c["name"] for r in rows for c in (r.get("containers") or [])}


def location_texts(rows: list[dict]) -> set[str]:
    """Every text a spool may be at that the list answers for: location names and container names."""
    return {r["name"] for r in rows} | container_names(rows)


def structure_problems(rows: list[dict], variant: dict) -> list[str]:
    """What the migrated list must say about a variant's settings (the roles, the set, the PLA place). Names are
    matched as the kit matches them (case ignored)."""
    s = old_settings(variant)
    by = {r["name"].casefold(): r for r in rows}
    out = []

    def need(what, ok):
        if not ok:
            out.append(what)
    sealed = [r for r in rows if r.get("sealed")]
    need(f"exactly one sealed place, {s['sealed_location']!r}", len(sealed) == 1 and
         sealed[0]["name"].casefold() == s["sealed_location"].casefold())
    default = [r for r in rows if r.get("default_overflow")]
    need(f"the default overflow is {s['overflow']!r}", len(default) == 1 and
         default[0]["name"].casefold() == s["overflow"].casefold() and default[0].get("overflow"))
    pla = by.get(s["pla_location"].strip().casefold())
    need(f"{s['pla_location']!r} takes PLA", bool(pla) and pla.get("fill") == "materials" and
         [m.casefold() for m in pla.get("materials") or []] == ["pla"])
    sets = [r for r in rows if r.get("type") == "containers"]
    if int(s["box_count"]) > 0:
        need(f"one containers set of {s['box_count']} with the prefix {s['box_prefix']!r}", len(sets) == 1 and
             sets[0].get("count") == int(s["box_count"]) and sets[0].get("prefix") == s["box_prefix"])
    else:
        need("no containers set", not sets)
    for name in s["locations"]:
        n = name.strip().casefold()
        need(f"{name!r} is still a place the spools can be at", n in by or any(
            n == (r.get("prefix") or "").strip().casefold() for r in sets) or n in {x.casefold() for x in container_names(rows)})
    return out


# ---------------------------------------------------------------- owner and mode

def parse_stat(text: str) -> tuple[str, str, int]:
    """(owner, group, mode) of `stat -c '%U %G %a' FILE`, the mode as a number (0o640 -> 416)."""
    m = re.fullmatch(r"\s*(\S+)\s+(\S+)\s+([0-7]{3,4})\s*", text)
    if not m:
        raise ValueError(f"not `stat -c '%U %G %a'` output: {text!r}")
    return m[1], m[2], int(m[3], 8)


def decode_acl(data: bytes, name_of) -> dict[str, str]:
    """The named-user entries of a `system.posix_acl_access` value (linux/posix_acl_xattr.h, version 2): {user: 'r--'};
    `name_of(uid)` gives the user name (None = the number is kept as text)."""
    if len(data) < 4 or struct.unpack("<I", data[:4])[0] != 2 or (len(data) - 4) % 8:
        raise ValueError("not a POSIX ACL")
    out = {}
    for i in range(4, len(data), 8):
        tag, perm, eid = struct.unpack("<HHI", data[i:i + 8])
        if tag == 0x02:                                       # ACL_USER
            out[name_of(eid) or str(eid)] = ("r" if perm & 4 else "-") + ("w" if perm & 2 else "-") + (
                "x" if perm & 1 else "-")
    return out


def state_file_problems(dir_stat: tuple[str, str, int], file_stat: tuple[str, str, int]) -> list[str]:
    """What differs from what the Hub's state files are: the owner and group of the state folder (the Hub's user) and
    mode 644, which the web unit reads through its pass on the folder."""
    out = []
    if file_stat[:2] != dir_stat[:2]:
        out.append(f"owner:group {file_stat[0]}:{file_stat[1]}, the state folder has {dir_stat[0]}:{dir_stat[1]}")
    if file_stat[2] != 0o644:
        out.append(f"mode {file_stat[2]:o}, not 644")
    return out
