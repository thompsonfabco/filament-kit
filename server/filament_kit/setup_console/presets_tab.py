"""The Presets tab: `filament-kit profiles` on the page. Add or accept only: nothing here replaces a preset in a slicer but
an accept the owner asked for, and the PC sync writes that after its backup, exactly as the command.

    GET  presets                               last build, problems, the lines (no device id; no file names)
    GET  presets/parents?material=&target=     the parents the sync reported: bambu (default) or orca
    POST presets/build {code}                  ask for a build
    POST presets/restore_deleted {code}        the next build brings back presets deleted in Bambu Studio
    POST presets/lines/{id}/parent {code, parent, target}
    POST presets/updates {code, line | all, dry_run}   the list; it names files, so it takes the code
    POST presets/updates {code, all, dry_run: false, stamp, names}   accept exactly what that list showed: 409 once a newer
                                               build has come, so nothing unseen ever replaces a preset
"""
from __future__ import annotations

import re

import anyio

from .. import config, modules, profiles_api, redact
from ..profiles import builds
from ..profiles import lines as lines_mod
from ..profiles.errors import ProfileError

LINE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


def _view() -> dict:
    if "presets" not in modules.enabled(config.load()):
        return {"on": False}
    st = profiles_api._status_view()
    pc = st.get("pc")
    if isinstance(pc, dict):
        pc = {k: v for k, v in pc.items() if k != "device_id"}
    known = redact.known_values()
    try:
        counts = profiles_api._preset_counts()
        rows = [profiles_api._line_view(line, counts) for _k, line in sorted(lines_mod.load().items())]
        lines_error = None
    except lines_mod.LineStoreError as e:
        rows, lines_error = [], e.message
    up = st.get("updates") or {}
    attempt = st.get("last_attempt")
    if isinstance(attempt, dict) and attempt.get("error"):      # holds whatever the exception held, a path usually
        attempt = {**attempt, "error": redact.text(str(attempt["error"]), known)}
    return {"on": True, "lines": rows, "lines_error": lines_error, "build": st.get("build"),
            "presets": st.get("presets"), "orca_presets": st.get("orca_presets"),
            "last_attempt": attempt, "installed": st.get("installed"), "pc": pc,
            # from the status's own times, which it words in local time; _status_view has made them ISO text
            "waiting_text": builds.pc_waiting_text(builds.status().get("pc")) if st.get("pc") else None,
            "updates": {k: up.get(k, 0) for k in ("count", "lines", "accepted", "yours")},
            "stale": st.get("stale") or [], "orca_stale": st.get("orca_stale") or [],
            "problems": [redact.text(str(p), known) for p in st.get("problems") or []]}


def _parents(material: str, target: str) -> dict:
    if target != "orca":
        return profiles_api._parents(material)
    known = lines_mod._orca_library(builds.orca_store())
    return {"parents": sorted(known) if known else [], "synced": bool(known)}


def routes(page) -> list[tuple]:
    from ..setup_page import Refused
    from .. import cli

    w = lambda fn: page.guard(fn, write=True)  # noqa: E731

    def need_on() -> None:
        if "presets" not in modules.enabled(config.load()):
            raise Refused(409, "the presets module is off: turn it on in Modules")

    async def read(request, body):
        return await anyio.to_thread.run_sync(_view)

    async def parents(request, body):
        need_on()
        material = request.query_params.get("material", "").strip()[:200]
        target = request.query_params.get("target", "bambu")
        if target not in ("bambu", "orca"):
            raise Refused(400, "target must be bambu or orca")
        return await anyio.to_thread.run_sync(_parents, material, target)

    async def build(request, body):
        need_on()
        await anyio.to_thread.run_sync(builds.request_rebuild, "asked for on the setup page")
        page.audit(request, "preset build requested")
        return {"ok": True}

    async def restore_deleted(request, body):
        need_on()

        def run() -> None:
            builds.restore_deleted_next()
            builds.request_rebuild("restore presets deleted in Bambu Studio")
        await anyio.to_thread.run_sync(run)
        page.audit(request, "presets deleted in Bambu Studio: restore requested")
        return {"ok": True}

    async def set_parent(request, body):
        need_on()
        lid = request.path_params["id"]
        target = body.get("target", "bambu")
        parent = body.get("parent")
        if not LINE_ID.fullmatch(lid):
            raise Refused(404, "no such line")
        if target not in ("bambu", "orca"):
            raise Refused(400, "target must be bambu or orca")
        if not isinstance(parent, str):
            raise Refused(400, "parent must be text")

        def run():
            try:
                return cli.set_parent_checked(lid, parent, orca=target == "orca")
            except KeyError:
                raise Refused(404, "no such line") from None
            except (ValueError, ProfileError) as e:
                raise Refused(400, str(e)) from None
            except lines_mod.LineStoreError as e:
                raise Refused(503, e.message) from None
        line = await anyio.to_thread.run_sync(run)
        page.audit(request, f"preset line {lid}: {target} parent set")
        return {"ok": True, "parent": line.orca_parent if target == "orca" else line.bambu_parent}

    async def updates(request, body):
        need_on()
        line, all_ = body.get("line"), body.get("all") is True
        if (line is None) == (not all_):
            raise Refused(400, "give one line, or all")
        if line is not None and (not isinstance(line, str) or not LINE_ID.fullmatch(line)):
            raise Refused(400, "no such line")
        dry = body.get("dry_run") is not False      # accepting takes a plain false
        stamp, names = body.get("stamp"), body.get("names")
        if not dry and not (isinstance(stamp, str) and isinstance(names, list) and names
                            and all(isinstance(n, str) for n in names)):
            raise Refused(400, "accepting names what the list showed: stamp and names")

        def run() -> dict:
            try:
                if dry:
                    return builds.apply_updates(line_id=line, all_=all_, dry_run=True)
                return builds.apply_updates(line_id=line, all_=all_, dry_run=False, only=set(names), expect_stamp=stamp)
            except builds.UpdatesChanged:
                raise Refused(409, "the updates changed since this list: show them again") from None
            except ValueError as e:
                raise Refused(400, str(e)) from None
        r = await anyio.to_thread.run_sync(run)
        chosen = r.get("chosen") or []
        if not dry:
            page.audit(request, f"{len(chosen)} preset updates accepted")
        return {"ok": True, "dry_run": dry, "stamp": r.get("stamp"),
                "chosen": [{"line_id": u["line_id"], "target": u["target"], "name": u["name"], "file": u.get("file"),
                            "keys": u["keys"]} for u in chosen]}

    return [("/presets", page.guard(read), "GET"), ("/presets/parents", page.guard(parents), "GET"),
            ("/presets/build", w(build), "POST"), ("/presets/restore_deleted", w(restore_deleted), "POST"),
            ("/presets/lines/{id}/parent", w(set_parent), "POST"), ("/presets/updates", w(updates), "POST")]
