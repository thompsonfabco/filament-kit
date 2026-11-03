"""Reads the filament presets packed in Orca Slicer's OrcaFilamentLibrary.opc (port of ops gen.py orca_lib_ids).

Orca 2.5.0 ships its system presets packed in `resources/profiles/*.opc` (header "ZCRO"); the JSON folders
are empty. Like ops gen.py this does not decode the whole format; it reads what the server needs (Ruling L):
every preset record is `<u64 len><name><u64 len>filament/...json` followed by its values, then a tail
`<u64 len><inherits> <empty> <empty> <len>"true"|"false" <len><setting_id or empty> <len><filament_id or empty>`
(an `@base` record holds the filament_id its `@System` children inherit). The
header's key table (`<u64 n>` key names after the vendor name and version) gives the index of
`filament_type`; a record that sets it holds `<u16 index><u64 1><u64 len><type>`.
"""
from __future__ import annotations

import re
import struct

MAGIC = b"ZCRO"
# a record start: <len><name><len>filament/...json (lengths are u64 little endian; names are printable ASCII)
_RECORD = re.compile(rb"([\x01-\xff])\x00{7}([ -~]{3,120})([\x01-\xff])\x00{7}(filament/[ -~]{1,240}?\.json)")
# the tail: <len><inherits> <0> <0> <len>true|false <16><setting_id>|<0> <len><filament_id>
_TAIL = re.compile(rb"\x00{16}(?:\x04\x00{7}true|\x05\x00{7}false)"
                   rb"(?:\x10\x00{7}([A-Za-z0-9]{16})|\x00{8})(?:([\x01-\x20])\x00{7}([A-Za-z0-9_]{1,32}))?")
_PRINTABLE = re.compile(rb"[ -~]+")
_ID = re.compile(rb"(?<![A-Za-z0-9])([A-Za-z0-9]{16})(?![A-Za-z0-9])")


def _keys(b: bytes) -> list[str]:
    """The header's key table, or [] when the header is not the known layout."""
    try:
        if not b.startswith(MAGIC):
            return []
        p = 4 + 4 + 8 + 4 + 4                       # magic, version, offset, checksum, count
        for _ in range(2):                          # vendor name, version
            n, = struct.unpack_from("<Q", b, p)
            p += 8 + n
        count, = struct.unpack_from("<Q", b, p)
        p += 8
        if count > 10_000:
            return []
        keys = []
        for _ in range(count):
            n, = struct.unpack_from("<Q", b, p)
            if n > 200:
                return []
            keys.append(b[p + 8:p + 8 + n].decode("ascii"))
            p += 8 + n
        return keys
    except (struct.error, UnicodeDecodeError):
        return []


def _string_before(window: bytes, end: int) -> str | None:
    """The length-prefixed printable string that ends exactly at `end`, if there is one."""
    for n in range(1, min(end - 8, 120) + 1):
        start = end - n
        if window[start - 8] == n and window[start - 7:start] == b"\0" * 7 and _PRINTABLE.fullmatch(window[start:end]):
            return window[start:end].decode("ascii")
    return None


def _string_value(window: bytes, key_index: int | None) -> str | None:
    if key_index is None:
        return None
    m = re.search(re.escape(struct.pack("<HQ", key_index, 1)) + rb"([\x01-\x40])\x00{7}", window)
    if not m:
        return None
    n = m.group(1)[0]
    text = window[m.end():m.end() + n]
    return text.decode("ascii") if len(text) == n and re.fullmatch(rb"[ -~]+", text) else None


def library_presets(b: bytes) -> list[dict]:
    """Every `... @System` filament preset in an OrcaFilamentLibrary.opc blob:
    [{name, setting_id, filament_id, filament_type, inherits}], sorted by name. filament_id and filament_type are
    taken from the inherited records when the preset does not set them; None where no record says."""
    keys = _keys(b)
    type_index = keys.index("filament_type") if "filament_type" in keys else None
    starts = []
    for m in _RECORD.finditer(b):
        name = m.group(2)
        if m.group(1)[0] == len(name) and m.group(3)[0] == len(m.group(4)):
            starts.append(m)
    records = {}
    for i, m in enumerate(starts):
        name = m.group(2).decode("ascii")
        if name in records:
            continue
        end = starts[i + 1].start() if i + 1 < len(starts) else len(b)
        window = b[m.end():end]
        inherits = setting_id = filament_id = None
        tail = _TAIL.search(window)
        if tail:
            inherits = _string_before(window, tail.start())
            setting_id = tail.group(1).decode("ascii") if tail.group(1) else None
            if tail.group(3) is not None and tail.group(2)[0] == len(tail.group(3)):
                filament_id = tail.group(3).decode("ascii")
        elif name.endswith(" @System"):  # ops gen.py: the first 16-character token after the record
            tok = _ID.search(b[m.end():m.end() + 1500])
            setting_id = tok.group(1).decode("ascii") if tok else None
        records[name] = {"name": name, "setting_id": setting_id, "filament_id": filament_id,
                         "filament_type": _string_value(window, type_index), "inherits": inherits}
    out = []
    for name in sorted(n for n in records if n.endswith(" @System")):
        rec = dict(records[name])
        parent, hops = rec["inherits"], 0
        while parent in records and hops < 10 and (rec["filament_id"] is None or rec["filament_type"] is None):
            for key in ("filament_id", "filament_type"):   # inherited from the @base / fdm_filament_* record
                if rec[key] is None:
                    rec[key] = records[parent][key]
            parent, hops = records[parent]["inherits"], hops + 1
        out.append(rec)
    return out
