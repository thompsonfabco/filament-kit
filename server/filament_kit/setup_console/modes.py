"""The setup presets (`modules set`) in the Features section of the Hub page.

    GET  modules/preview?mode=M              what the preset would do; changes nothing (route in setup_page.py)
    POST modules/mode {code, mode[, settings]}   the root helper's `mode`
"""
from __future__ import annotations

from .. import config, modules


def preview(mode: str) -> dict:
    from ..setup_page import Refused
    mode = modules.canonical_mode(mode)
    if mode not in modules.MODES:
        raise Refused(400, "no such mode")
    cfg = config.load()
    on = modules.enabled(cfg)
    if "server" not in modules.MODES[mode]:
        return {"mode": mode, "on": True, "notes": [], "after": sorted(on), "needs": [],
                "refused": "this page is the server module's, and that mode has none: at the server: "
                           f"sudo filament-kit modules set {mode} --server <the kit server's address>"}
    notes: list[str] = []
    try:
        out = modules.set_mode(cfg, mode, say=notes.append)
    except modules.ModuleError as e:
        raise Refused(400, str(e)) from None
    after = modules.enabled(out)
    off, gained = [n for n in modules.MODULES if n in on - after], [n for n in modules.MODULES if n in after - on]
    if off:
        notes.append("Turns off: " + ", ".join(off))
    if gained:
        notes.append("Turns on: " + ", ".join(gained))
    needs = [{"key": k, "prompt": modules._SETTING_PROMPTS[k].rstrip(": ")}
             for k in modules.missing_settings(after, out) if k != "station.allow"]
    return {"mode": mode, "on": True, "notes": notes, "after": [n for n in modules.MODULES if n in after],
            "needs": needs, "refused": None}


def routes(page) -> list[tuple]:
    async def set_mode(request, body):
        mode = body.get("mode")
        r = await page._helper({"op": "mode", "code": body["code"], "mode": mode, "settings": body.get("settings")})
        if r.get("changed"):
            page.audit(request, f"mode set to {mode}")
        return {"ok": True, "changed": bool(r.get("changed")), "notes": r.get("notes") or []}

    return [("/modules/mode", page.guard(set_mode, write="helper"), "POST")]
