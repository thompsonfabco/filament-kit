"""Trusted computers on the Devices tab: `trusted.py` has what it means. The root helper keeps them and checks them.

    GET  trust                       is this browser trusted, and is the feature on
    POST trust {code[, name]}        trust this browser: only with the setup code typed, never with a trusted cookie
    POST trust/list {code}           the list
    POST trust/{id}/rename {code, name}  trust/{id}/revoke {code}  trust/revoke_all {code}
    POST trust/enabled {code, enabled}   the off switch: off forgets them all

The cookie goes out only in Set-Cookie: a reply's body never holds the token. `code` is either the typed code or, when a trusted
browser sends none, its cookie (SetupPage.guard).
"""
from __future__ import annotations

from .. import trusted


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    hw = lambda fn: page.guard(fn, write="helper")  # noqa: E731

    def device_id(request) -> str:
        did = request.path_params["id"]
        if not trusted.ID.fullmatch(did):
            raise Refused(404, "no such trusted computer")
        return did

    async def state(request, body):
        token = request.cookies.get(trusted.COOKIE)
        try:
            return await page._helper({"op": "trust_status", "token": token if isinstance(token, str) else None})
        except Refused:            # no helper yet: the page still works, with the code
            return {"enabled": False, "trusted": False, "id": None, "name": None}

    async def add(request, body):
        if body["code"].startswith(trusted.PREFIX):
            raise Refused(403, "type the setup code to trust another browser")
        name = body.get("name") or trusted.name_from_agent(request.headers.get("user-agent"))
        r = await page._helper({"op": "trust_add", "code": body["code"], "name": name})
        request.state.set_trust = r["token"]
        page.audit(request, f"computer {r['id']} trusted")
        return {"ok": True, "id": r["id"], "name": trusted.clean_name(name)}

    async def listing(request, body):
        r = await page._helper({"op": "trust_list", "code": body["code"]})
        return {"enabled": r["enabled"], "devices": r["devices"], "this": r.get("this")}

    async def rename(request, body):
        did = device_id(request)
        await page._helper({"op": "trust_rename", "code": body["code"], "id": did, "name": body.get("name")})
        page.audit(request, f"trusted computer {did} renamed")
        return {"ok": True}

    async def revoke(request, body):
        did = device_id(request)
        r = await page._helper({"op": "trust_revoke", "code": body["code"], "id": did})
        request.state.clear_trust = bool(r.get("self"))
        page.audit(request, f"trusted computer {did} revoked")
        return {"ok": True, "self": bool(r.get("self"))}

    async def revoke_all(request, body):
        r = await page._helper({"op": "trust_revoke_all", "code": body["code"]})
        request.state.clear_trust = bool(request.cookies.get(trusted.COOKIE))
        page.audit(request, f"all trusted computers revoked ({r.get('count', 0)})")
        return {"ok": True, "count": r.get("count", 0)}

    async def set_enabled(request, body):
        on = body.get("enabled")
        if not isinstance(on, bool):
            raise Refused(400, "enabled must be true or false")
        r = await page._helper({"op": "trust_enabled", "code": body["code"], "enabled": on})
        if not on:
            request.state.clear_trust = bool(request.cookies.get(trusted.COOKIE))
        page.audit(request, f"trusted computers turned {'on' if on else 'off'}")
        return {"ok": True, "enabled": on, "forgotten": r.get("forgotten", 0)}

    return [("/trust", page.guard(state), "GET"), ("/trust", hw(add), "POST"), ("/trust/list", hw(listing), "POST"),
            ("/trust/revoke_all", hw(revoke_all), "POST"), ("/trust/enabled", hw(set_enabled), "POST"),
            ("/trust/{id}/rename", hw(rename), "POST"), ("/trust/{id}/revoke", hw(revoke), "POST")]
