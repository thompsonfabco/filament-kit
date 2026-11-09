"""The Settings tab's general settings and the remote module's certificate.

    GET  settings/general                the values of the helper's whitelist (GENERAL), and Spoolman's address redacted
    POST settings/general {code, key, value}   one of them; the helper checks it against its table and saves it
    POST settings/spoolman {code, url}   an external Spoolman: only after this server has reached it and it answered as one
    POST remote/firewall {code}          the rules the owner sets up by hand: printed only, and it names their networks
The certificate itself is the job `remote_issue`.
"""
from __future__ import annotations

import anyio

from .. import config, modules, redact, remote, setup_helper
from ..spoolman import Spoolman, SpoolmanError


def _view() -> dict:
    cfg = config.load()
    on = modules.enabled(cfg)
    values = {k: setup_helper.general_value(cfg, k) for k in setup_helper.GENERAL}
    return {"values": values, "station_on": "station" in on, "remote_on": "remote" in on,
            "spoolman_external": "server" in on and "spoolman" not in on,
            "spoolman_url": redact.text(str(cfg.get("spoolman_url") or ""), redact.known_values())}


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    async def read(request, body):
        return await anyio.to_thread.run_sync(_view)

    async def write(request, body):
        key = body.get("key")
        r = await page._helper({"op": "general", "code": body["code"], "key": key, "value": body.get("value")})
        page.audit(request, f"setting {r['key']} changed")
        return {"ok": True, "restarts": r["restarts"], "applies": r["applies"]}

    async def spoolman(request, body):
        url = body.get("url")
        if not isinstance(url, str) or not url.strip():
            raise Refused(400, "give the address of the Spoolman to use")
        url = url.strip().rstrip("/")
        err = modules.check_setting("spoolman_url", url)
        if err:
            raise Refused(400, err)

        def answers() -> str | None:
            try:
                Spoolman(url, timeout=5).ping()
                return None
            except (SpoolmanError, OSError, ValueError) as e:
                return str(e)
        why = await anyio.to_thread.run_sync(answers)
        if why:
            raise Refused(400, f"nothing was changed: no Spoolman answered at that address ({why})")
        await page._helper({"op": "spoolman_url", "code": body["code"], "url": url})
        page.audit(request, "Spoolman address changed")
        return {"ok": True}

    async def firewall(request, body):
        def text() -> str:
            cfg = config.load()
            if "remote" not in modules.enabled(cfg):
                raise Refused(409, "the remote module is off: turn it on in Modules")
            try:
                return remote.firewall_text(remote.settings(cfg), config.paths().opt / "resources")
            except modules.ModuleError as e:
                raise Refused(400, str(e)) from None
            except OSError as e:
                raise Refused(503, f"cannot read the remote files ({e.strerror or e})") from None
        return {"text": await anyio.to_thread.run_sync(text)}

    return [("/settings/general", page.guard(read), "GET"),
            ("/settings/general", page.guard(write, write="helper"), "POST"),
            ("/settings/spoolman", page.guard(spoolman, write=True), "POST"),
            ("/remote/firewall", page.guard(firewall, write=True), "POST")]
