"""The iPhone's entry on the Devices tab. It is not paired: it opens the phone web app in Safari. The kit server
serves it itself on the home network (the user's decision, 2026-11-09), so there is always a home address; with the
web module on and its public address set, that one is offered too.

    GET webapp    {url, qr_svg, public_url, public_qr_svg, public_hidden}: the home address
                  (https://<name>.local:<port>/intake) and its QR. The web module's public one is owner data (`redact`
                  hides its host), so without the setup code it is None and public_hidden says there is one
    POST webapp {code}  the same with the public address and its QR (None when the module is off or has no address)
"""
from __future__ import annotations

import anyio

from .. import config, modules, pairing


def _view(whole: bool) -> dict:
    cfg = config.load()
    from ..setup_page import qr_svg
    home = f"https://{pairing.short_hostname()}.local:{int(cfg.get('port', 8710))}/intake"     # the kit server's own
    public = str((cfg.get("web") or {}).get("public_url") or "").strip() if "web" in modules.enabled(cfg) else ""
    public_url = public.rstrip("/") + "/intake" if public else None      # the module's base address has no page
    return {"url": home, "qr_svg": qr_svg(home), "public_url": public_url if whole else None,
            "public_qr_svg": qr_svg(public_url) if public_url and whole else None,
            "public_hidden": bool(public_url) and not whole}


def routes(page) -> list[tuple]:
    async def read(request, body):
        return await anyio.to_thread.run_sync(_view, False)

    async def read_whole(request, body):
        return await anyio.to_thread.run_sync(_view, True)

    return [("/webapp", page.guard(read), "GET"), ("/webapp", page.guard(read_whole, write=True), "POST")]
