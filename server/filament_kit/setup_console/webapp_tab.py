"""The iPhone's entry on the Devices tab. It is not paired: it opens the `web` module's address in Safari.

    GET webapp    {on: false} | {on: true, url, set_address, qr_svg}
"""
from __future__ import annotations

import anyio

from .. import config, modules, pairing


def _view() -> dict:
    cfg = config.load()
    if "web" not in modules.enabled(cfg):
        return {"on": False}
    from ..setup_page import qr_svg
    public = str((cfg.get("web") or {}).get("public_url") or "").strip()
    base = public or f"https://{pairing.short_hostname()}.local/filament"      # Way A of docs/install-iphone-web-app.md
    url = base.rstrip("/") + "/intake"      # the phone web app; the module's base address has no page of its own
    return {"on": True, "url": url, "set_address": bool(public), "qr_svg": qr_svg(url)}


def routes(page) -> list[tuple]:
    async def read(request, body):
        return await anyio.to_thread.run_sync(_view)

    return [("/webapp", page.guard(read), "GET")]
