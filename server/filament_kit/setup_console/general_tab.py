"""The Settings tab's general settings and the remote module's certificate.

    GET  settings/general                the values of the helper's whitelist (GENERAL), and Spoolman's address redacted
    POST settings/general {code, key, value}   one of them; the helper checks it against its table and saves it
    POST settings/spoolman {code, url}   an external Spoolman: only after this server has reached it and it answered as one
    POST remote/firewall {code}          the rules the owner sets up by hand: printed only, and it names their networks
    GET  settings/local-intake           the local label reader's health (local_reader.health): a read, no code
    GET  settings/local-intake/plan      what the last plan job (local_intake_plan) saved: no network here, the server's
                                         unit does not reach GitHub (install / removal: jobs local_intake_install, _remove)
The certificate itself is the job `remote_issue`.
"""
from __future__ import annotations

import anyio

from .. import config, local_intake_install, local_reader, modules, redact, remote, setup_helper
from ..spoolman import Spoolman, SpoolmanError


def _history_use() -> dict:
    """The intake history's records and photo bytes now, for the line beside its setting."""
    from .. import intake_history
    try:
        d = intake_history.list_records(False)
        return {"count": d["count"], "photo_bytes": d["photo_bytes"]}
    except Exception:  # noqa: BLE001 - a line beside a setting
        return {"count": 0, "photo_bytes": 0}


def _view() -> dict:
    cfg = config.load()
    on = modules.enabled(cfg)
    values = {k: setup_helper.general_value(cfg, k) for k in setup_helper.GENERAL}
    return {"values": values, "station_on": "station" in on, "remote_on": "remote" in on, "web_on": "web" in on,
            "ai_intake_on": "ai_intake" in on, "local_intake_on": "local_intake" in on,
            "local_intake_installed": local_intake_install.installed(),
            "spoolman_external": "server" in on and "spoolman" not in on,
            "intake_history": _history_use(),
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

    async def reader_health(request, body):
        def check() -> dict:
            cfg = config.load()
            if "local_intake" not in modules.enabled(cfg):
                raise Refused(409, "the local_intake module is off: turn it on in Modules")
            return local_reader.health(cfg)
        return await anyio.to_thread.run_sync(check)

    async def reader_plan(request, body):
        return {"saved": await anyio.to_thread.run_sync(local_intake_install.saved_plan)}

    return [("/settings/general", page.guard(read), "GET"),
            ("/settings/local-intake", page.guard(reader_health), "GET"),
            ("/settings/local-intake/plan", page.guard(reader_plan), "GET"),
            ("/settings/general", page.guard(write, write="helper"), "POST"),
            ("/settings/spoolman", page.guard(spoolman, write=True), "POST"),
            ("/remote/firewall", page.guard(firewall, write=True), "POST")]
