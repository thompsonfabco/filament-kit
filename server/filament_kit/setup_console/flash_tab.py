"""The "Flash a device" tab: the kit's own firmware written to an ESP32-C3, from the browser over Web Serial (the
board plugged into the computer the owner sits at) or by the server (plugged into the server's USB). The images come
from the installed kit version (reader_flash.DEVICES), never the internet, and hold no settings.

    GET  firmware                       the devices this kit has images for, the boards on the server's USB, and
                                        whether the Printer Station's settings can be made (web.public_url)
    GET  firmware/{device}.bin          one image, for the browser to write
    POST flash/provision {code[, name]} the browser way, Printer Station: a new reader token and the kit's reader
                                        address, which the page writes into the board over USB (FK-SET) and never
                                        shows; a run that fails revokes it (readers/{id}/revoke)
    POST flash/server {code, ssid, pass, buzzer[, port][, name]}   the server way: the root helper's op reader_usb
                                        starts the job reader_setup (`reader setup --pending`); the page follows it
                                        as every job

The intake panel needs no settings: from the browser it is written and then plugged into the station computer; on
the server the station writes its bundled firmware to a panel by itself (station/panel.py), so the server way is
just plugging it in there.
"""
from __future__ import annotations

import anyio
from starlette.responses import Response

from .. import config, modules, reader_flash, reader_setup, reader_tokens


def _base() -> tuple[str | None, str | None]:
    try:
        return reader_setup.reader_base(config.load()), None
    except reader_setup.SetupError as e:
        return None, str(e)


def listing() -> dict:
    devices = []
    for dev, title in reader_flash.DEVICES.items():
        got = reader_flash.device_image(dev)
        devices.append({"id": dev, "title": title, "bundled": got is not None,
                        "version": got[1] if got else None, "size": got[0].stat().st_size if got else None,
                        "settings": dev == "printer-station"})
    base, why = _base()
    cfg = config.load()
    return {"devices": devices,
            # the port and the board's own name; never the by-id path, which holds the chip's serial
            "server_boards": [{"port": r.port, "product": r.product} for r in reader_setup.find_readers()],
            "station_here": "station" in modules.enabled(cfg),
            "settings_ok": base is not None, "settings_why": why}


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    g = page.guard
    w = lambda fn: page.guard(fn, write=True)  # noqa: E731
    hw = lambda fn: page.guard(fn, write="helper")  # noqa: E731

    async def firmware(request, body):
        return await anyio.to_thread.run_sync(listing)

    async def image(request, body):
        name = request.path_params["device"]
        dev = name.removesuffix(".bin")
        got = reader_flash.device_image(dev) if name.endswith(".bin") else None
        if got is None:
            raise Refused(404, "this kit has no such firmware")
        data = await anyio.to_thread.run_sync(got[0].read_bytes)
        return Response(data, media_type="application/octet-stream",
                        headers={"X-Firmware-Version": got[1], "X-Content-Type-Options": "nosniff"})

    async def provision(request, body):
        name = page._opt_text(body, "name") or "printer-station"
        if reader_flash.bundled_image() is None:
            raise Refused(409, "this kit has no Printer Station firmware bundled; update the kit")
        base, why = _base()
        if base is None:
            raise Refused(409, why)

        def run():
            try:
                return reader_tokens.TokenStore().issue(name)
            except reader_tokens.TokenFileError as e:
                raise Refused(409, f"{e}; nothing was changed") from None
        tid, token = await anyio.to_thread.run_sync(run)
        page.audit(request, f"reader token {tid} made for a Printer Station flashed from the browser")
        # the one reply with a token: the page writes it to the board over USB and keeps it nowhere
        return {"ok": True, "id": tid, "token": token, "base": base}

    async def server(request, body):
        req = {"op": "reader_usb", "code": body["code"]}
        for k in ("ssid", "pass", "buzzer", "port", "name"):
            if k in body:
                req[k] = body[k]
        r = await page._helper(req)
        page.audit(request, "Printer Station setup on the server's USB started")
        return {"ok": True, "name": r.get("name")}

    return [("/firmware", g(firmware), "GET"), ("/firmware/{device}", g(image), "GET"),
            ("/flash/provision", w(provision), "POST"), ("/flash/server", hw(server), "POST")]
