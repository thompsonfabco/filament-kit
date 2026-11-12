"""The Printers tab, beyond what setup_page.py had: both families' controls. Addresses are kept as typed (hostaddr).

    POST printers/klipper {code, host[, port, name, api_key]}     add one (no Access Code; its API key is optional)
    POST printers/scan {code[, subnet]}             look for Moonraker on this server's /24 or a private one: it records what
                                                    it finds, unconfigured, so it needs the code; one at a time, 30 s apart
    POST printers/pack {}                           the printer pack's commands, checked against the signed release
    POST printers/{serial}/rename {code, name}      POST printers/{serial}/address {code, address[, port]}
    POST printers/{serial}/unpin {code}             Bambu: forget its pinned certificate
    POST printers/{serial}/connect {code[, api_key]}   Klipper: a scanned printer goes into use
    POST printers/{serial}/api_key {code, key}      Klipper: write-only; empty clears it
    POST printers/{serial}/lane_data {code, mode}   Klipper: auto, on or off
    POST printers/{serial}/detect {}                Klipper: what it is
    POST printers/{serial}/map {code}  GET printers/{serial}/map  POST printers/{serial}/map/stop {code}
        Bambu: slot mapping on the server's own connection, so the printer never sees a second LAN client
    POST printers/{serial}/report {code}            Bambu: collect a printer report now (bridge/printer_report.py), as the app's
                                                    "Collect a report"; kept beside the printer's other files, the last five
    POST printers/{serial}/reports {code}           the kept reports: [{name, size, at}], newest first, and what they never hold
    POST printers/{serial}/reports/{name} {code}    one of them, to save (the server's own files: no root needed)
"""
from __future__ import annotations

import ipaddress
import re
import threading
import time

import anyio

from .. import config, hostaddr, release, updates
from ..bridge import camera, mapping, registry
from ..bridge.connection import PrinterOffline, UnknownPrinter
from ..bridge.klipper import discovery
from ..bridge.slottest import NoStatus, PrinterBusy

# Map by loading filament (bridge/manual.py): (route, method, call)
MANUAL_STEPS = [
    ("start", "POST", lambda mm, s, b: mm.start(s)),
    ("", "GET", lambda mm, s, b: mm.view(s)),
    ("confirm", "POST", lambda mm, s, b: mm.confirm(s, b.get("session"), b.get("position"), b.get("reported"),
                                                     b.get("nozzle"), b.get("by_hand") is True)),
    ("skip", "POST", lambda mm, s, b: mm.skip(s, b.get("session"), b.get("position"))),
    ("stop", "POST", lambda mm, s, b: mm.stop(s, b.get("session"))),
    ("offer", "POST", lambda mm, s, b: mm.answer_offer(s, b.get("share") is True)),
]

SCAN_GAP = 30.0
API_KEY = re.compile(r"[!-~]{1,64}")
BAD_API_KEY = "a Moonraker API key has no spaces and at most 64 characters"
OFFLINE = "the printer is offline; check that it is on and on the network"


def routes(page) -> list[tuple]:
    from .. import klipper_cli
    from ..setup_page import Refused

    w = lambda fn: page.guard(fn, write=True)  # noqa: E731
    g = page.guard
    scan_lock = threading.Lock()
    last_scan = [-SCAN_GAP]

    def api_key(body: dict) -> str:
        key = body.get("api_key", body.get("key"))
        key = key.strip() if isinstance(key, str) else ""
        if key and not API_KEY.fullmatch(key):
            raise Refused(400, BAD_API_KEY)
        return key

    def port_of(body: dict) -> int:
        port = body.get("port", discovery.DEFAULT_PORT)
        try:
            if isinstance(port, bool):
                raise ValueError
            port = int(port)
        except (TypeError, ValueError):
            raise Refused(400, "the port must be a number from 1 to 65535") from None
        if not 1 <= port <= 65535:
            raise Refused(400, "the port must be a number from 1 to 65535")
        return port

    def address(body: dict, key: str = "address") -> hostaddr.Inspected:
        """The address as it will be kept, with the note to show beside it (the unit doesn't reach it) or None."""
        a = hostaddr.inspect(body.get(key))
        if a.problem:
            raise Refused(400, a.problem)
        return a

    def klipper_entry(serial: str) -> registry.Printer:
        p = page._entry(serial)
        if p.family != "klipper":
            raise Refused(400, "that is for a Klipper printer")
        return p

    def found_by_name(host: str, port: int) -> registry.Printer | None:
        """The unconfigured entry a scan left at the address a typed name resolves to, if any."""
        if hostaddr.is_literal(host):
            return None
        at = hostaddr.addresses(host)
        return next((p for p in registry.load().values()
                     if p.family == "klipper" and not p.configured and p.port == port and p.host in at), None)

    def bambu_entry(serial: str) -> registry.Printer:
        p = page._entry(serial)
        if p.family != "bambu":
            raise Refused(400, "that is for a Bambu printer")
        return p

    async def klipper_add(request, body):
        page._manager("klipper")
        name, key, port = page._opt_text(body, "name"), api_key(body), port_of(body)

        def run() -> tuple[str, str | None]:
            host, _, note = address(body, "host")
            same = registry.klipper_at(registry.load(), host, port) or found_by_name(host, port)
            if same is not None and same.configured:
                raise Refused(409, f"{registry.display_name(same)} is already at {host}:{port}")
            if same is not None:        # a scan found it (by this address, or the address this name stands for): into use
                registry.configure_klipper(same.serial, name)
                if same.host.lower() != host.lower():
                    registry.set_address(same.serial, host, port)       # the name, as typed, is what the owner wants kept
                pid = same.serial
            else:
                pid = registry.add_klipper(name or host, host, port).serial
            if key:
                registry.set_api_key(pid, key)
            page.printers.sync()
            return pid, note
        pid, note = await anyio.to_thread.run_sync(run)
        page.audit(request, f"klipper printer {pid} added")
        return {"ok": True, "serial": pid, **({"note": note} if note else {})}

    async def scan(request, body):
        page._manager("klipper")
        subnet = body.get("subnet")

        def net_of():
            if not subnet:
                net = discovery.own_subnet()
                if net is None:
                    raise Refused(400, "can't tell this server's network; give a subnet such as 192.168.1.0/24")
                return net
            try:
                net = ipaddress.ip_network(str(subnet).strip(), strict=False)
            except ValueError:
                raise Refused(400, "give a subnet such as 192.168.1.0/24") from None
            if net.version != 4 or not net.is_private or net.is_loopback or net.is_link_local or net.is_multicast:
                raise Refused(400, "scan your own network: a private IPv4 subnet such as 192.168.1.0/24") from None
            if net.prefixlen < 24:
                raise Refused(400, "scan at most a /24 (256 addresses)")
            return net

        def run() -> dict:
            net = net_of()
            if not scan_lock.acquire(blocking=False):
                raise Refused(429, "a scan is running")
            try:
                wait = last_scan[0] + SCAN_GAP - time.monotonic()
                if wait > 0:
                    raise Refused(429, f"wait {wait:.0f} s between scans")
                last_scan[0] = time.monotonic()
                found = discovery.scan(net, port=discovery.DEFAULT_PORT)
                rows = []
                for host, port in found:
                    p = registry.detected_klipper(host, port)
                    rows.append({"serial": p.serial, "host": host, "port": port, "configured": p.configured})
                return {"ok": True, "subnet": str(net), "found": rows}
            finally:
                scan_lock.release()
        r = await anyio.to_thread.run_sync(run)
        page.audit(request, f"scanned for Klipper printers, {len(r['found'])} found")
        return r

    async def pack(request, body):
        page._manager("klipper")
        page._gap()

        def run() -> dict:
            try:
                info = klipper_cli.pack_info(updates.current_version(), config.load())
            except release.ReleaseError as e:       # no command at all, never an unchecked one
                raise Refused(409, f"no printer pack command: {e}") from None
            return {"version": info["version"], "lines": info["lines"]}
        return await anyio.to_thread.run_sync(run)

    async def rename(request, body):
        serial = page._serial(request)
        name = page._opt_text(body, "name")
        if not name:
            raise Refused(400, "give the printer a name")

        def run() -> None:
            page._entry(serial)
            registry.rename(serial, name)
            page.printers.sync()
        await anyio.to_thread.run_sync(run)
        page.audit(request, f"printer {serial} renamed")
        return {"ok": True}

    async def change_address(request, body):
        serial = page._serial(request)

        def run() -> str | None:
            p = page._entry(serial)
            port = port_of({"port": body.get("port", p.port)}) if p.family == "klipper" else None
            host, _, note = address(body)
            if p.family == "klipper":
                other = registry.klipper_at(registry.load(), host, port)
                if other is not None and other.serial != serial:
                    raise Refused(409, f"{registry.display_name(other)} is already at {host}:{port}")
            registry.set_address(serial, host, port)
            page.printers.sync()
            return note
        note = await anyio.to_thread.run_sync(run)
        page.audit(request, f"printer {serial} address changed")
        return {"ok": True, **({"note": note} if note else {})}

    async def unpin(request, body):
        serial = page._serial(request)

        def run() -> None:
            bambu_entry(serial)
            registry.clear_pin(serial)
            page.printers.sync()
        await anyio.to_thread.run_sync(run)
        page.audit(request, f"printer {serial} certificate pin cleared")
        return {"ok": True}

    async def connect(request, body):
        serial, key = page._serial(request), api_key(body)

        def run() -> None:
            klipper_entry(serial)
            registry.configure_klipper(serial, "")
            if key:
                registry.set_api_key(serial, key)
            page.printers.sync()
        await anyio.to_thread.run_sync(run)
        page.audit(request, f"klipper printer {serial} put into use")
        return {"ok": True}

    async def set_key(request, body):
        serial, key = page._serial(request), api_key(body)

        def run() -> None:
            klipper_entry(serial)
            registry.set_api_key(serial, key)
            page.printers.sync()
        await anyio.to_thread.run_sync(run)
        page.audit(request, f"printer {serial} API key {'stored' if key else 'cleared'}")
        return {"ok": True, "set": bool(key)}

    async def lane_data(request, body):
        serial, mode = page._serial(request), body.get("mode")
        if mode not in registry.LANE_DATA:
            raise Refused(400, "mode must be one of: " + ", ".join(registry.LANE_DATA))

        def run() -> None:
            klipper_entry(serial)
            registry.set_lane_data(serial, mode)
            page.printers.sync()
        await anyio.to_thread.run_sync(run)
        page.audit(request, f"printer {serial} lane data {mode}")
        return {"ok": True}

    async def detect(request, body):
        serial = page._serial(request)
        await anyio.to_thread.run_sync(klipper_entry, serial)
        page._gap()
        return await anyio.to_thread.run_sync(lambda: klipper_cli.detect(klipper_entry(serial)))

    def mapper_of(serial: str):
        bambu_entry(serial)
        if page.mapper is None:
            raise Refused(409, "slot mapping isn't running on this server")
        return page.mapper

    async def map_start(request, body):
        serial = page._serial(request)

        def run() -> str:
            m = mapper_of(serial)
            try:
                return m.start(serial)
            except mapping.AlreadyRunning as e:
                raise Refused(409, e.message) from None
            except mapping.CertChanged:
                raise Refused(409, camera.CERT_CHANGED) from None
            except PrinterBusy as e:
                raise Refused(409, f"the printer is busy ({e}); try again once it is idle") from None
            except NoStatus as e:
                raise Refused(409, str(e)) from None
            except PrinterOffline:
                raise Refused(409, OFFLINE) from None
            except UnknownPrinter:
                raise Refused(404, "no such printer") from None
        job = await anyio.to_thread.run_sync(run)
        page.audit(request, f"printer {serial} slot mapping started")
        return {"ok": True, "job_id": job}

    async def report_collect(request, body):
        serial = page._serial(request)

        def run() -> dict:
            m = mapper_of(serial)
            try:
                r = m.report(serial)
            except PrinterOffline:
                raise Refused(409, "the printer cannot be reached and the kit has saved nothing about it yet") from None
            except UnknownPrinter:
                raise Refused(404, "no such printer") from None
            except OSError as e:
                raise Refused(500, f"the report could not be kept ({type(e).__name__})") from None
            note = None if r.get("live", True) else (
                "The printer could not be reached: this report is built from what the kit saved"
                + (f" (newest record {time.strftime('%Y-%m-%d %H:%M', time.localtime(r['saved_until']))})"
                   if r.get("saved_until") else "") + ".")
            return {"ok": True, "name": r["name"], "live": r.get("live", True), "note": note}
        res = await anyio.to_thread.run_sync(run)
        page.audit(request, f"printer {serial} report collected")
        return res

    async def report_list(request, body):
        serial = page._serial(request)

        def run() -> dict:
            bambu_entry(serial)
            from ..bridge import printer_report
            return {"reports": printer_report.saved(serial), "never": printer_report.NEVER}
        return await anyio.to_thread.run_sync(run)

    async def report_download(request, body):
        from starlette.responses import Response
        serial, name = page._serial(request), request.path_params["name"]

        def run() -> bytes:
            bambu_entry(serial)
            from ..bridge import printer_report
            try:
                return printer_report.read_saved(serial, name)
            except OSError:
                raise Refused(404, "no such report") from None
        data = await anyio.to_thread.run_sync(run)
        page.audit(request, f"printer {serial} report downloaded")
        return Response(data, media_type="application/xml",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    def manual(what: str, fn):
        """A manual-map step (bridge/manual.py): the same answers as the kit API gives the app."""
        from ..bridge import manual as manual_mod

        async def route(request, body):
            serial = page._serial(request)

            def run():
                if page._entry(serial).family == "klipper":
                    kf = getattr(page.printers, "klipper", None)
                    if kf is None:
                        raise Refused(409, "the klipper module is off on this server")
                    session = kf.manual
                else:
                    session = mapper_of(serial).manual
                try:
                    return fn(session, serial, body)
                except manual_mod.ManualError as e:
                    raise Refused(e.status, str(e)) from None
            out = await anyio.to_thread.run_sync(run)
            if what != "view":
                page.audit(request, f"printer {serial} manual map {what}")
            return out
        return route

    async def map_get(request, body):
        serial = page._serial(request)
        return await anyio.to_thread.run_sync(lambda: mapper_of(serial).view(serial))

    async def map_stop(request, body):
        serial = page._serial(request)
        m = await anyio.to_thread.run_sync(mapper_of, serial)
        m.abort(serial, pending=False)  # the slots are put back first, as when the command line's run is stopped
        page.audit(request, f"printer {serial} slot mapping stopped")
        return {"ok": True}

    one = "/printers/{serial}"
    return [("/printers/klipper", w(klipper_add), "POST"), ("/printers/scan", w(scan), "POST"),
            ("/printers/pack", g(pack), "POST"),
            (one + "/rename", w(rename), "POST"), (one + "/address", w(change_address), "POST"),
            (one + "/unpin", w(unpin), "POST"), (one + "/connect", w(connect), "POST"),
            (one + "/api_key", w(set_key), "POST"), (one + "/lane_data", w(lane_data), "POST"),
            (one + "/detect", g(detect), "POST"),
            (one + "/map", w(map_start), "POST"), (one + "/map", g(map_get), "GET"),
            (one + "/map/stop", w(map_stop), "POST"),
            (one + "/report", w(report_collect), "POST"), (one + "/reports", w(report_list), "POST"),
            (one + "/reports/{name}", w(report_download), "POST"),
            *[(one + "/manual-map" + (f"/{name}" if name else ""), (w if method == "POST" else g)(manual(name or "view", fn)),
               method) for name, method, fn in MANUAL_STEPS]]
