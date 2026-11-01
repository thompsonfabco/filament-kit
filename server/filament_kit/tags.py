"""NFC tag UID helpers. Canonical form: hex bytes joined by ':' with no padding."""
import json
import re

_HEX = re.compile(r"^[0-9a-fA-F]+$")


def format_uid(uid: bytes) -> str:
    return ":".join(f"{b:x}" for b in uid)


def normalize_uid(text: str) -> str:
    text = "".join(text.split())
    if ":" in text:
        parts = text.split(":")
        if any(not p or len(p) > 2 or not _HEX.match(p) for p in parts):
            raise ValueError(f"not a valid tag UID: {text!r}")
        uid = bytes(int(p, 16) for p in parts)
    else:
        if not _HEX.match(text) or len(text) % 2:
            raise ValueError(f"not a valid tag UID: {text!r}")
        uid = bytes.fromhex(text)
    if len(uid) < 4:
        raise ValueError(f"tag UID too short ({len(uid)} bytes, need at least 4)")
    return format_uid(uid)


def stored(spool: dict) -> str | None:
    """Tag UID stored on a Spoolman spool (extra.nfc_id is a JSON-encoded string)."""
    raw = (spool.get("extra") or {}).get("nfc_id")
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        value = raw
    return value if isinstance(value, str) and value else None
