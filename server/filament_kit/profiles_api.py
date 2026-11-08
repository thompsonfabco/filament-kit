"""Sync and profiles routes (global-constraints "Sync and profiles API contract").

`routes(authed, sm)` returns the routes; `authed` is api.`_authed`, so every route needs the Bearer token, sets
`request.state.device` and turns a `ProfileError` into `{"error", "message", **extra}`.

Uploads (`PUT /api/sync/live|system`; live takes `user_id` and, after a half-finished install, `partial=<stamp>`,
ruling S28; `target=orca` stores Orca Slicer's folders instead, kinds `orca_live` / `orca_system`, Ruling L, and
`partial` works the same, Ruling O): the owner is checked before the body is read (409 `other_pc`), a declared
Content-Length over the cap is refused at once (413), then `request.stream()` is read by `builds.store_upload`
in the threadpool through a small blocking reader, which stops at the cap (never `await request.body()`).

`GET /api/profiles/updates` lists the presets already in the slicers whose generated values differ (never written
over until the owner accepts them, `filament-kit profiles apply-updates`; builds.updates_view); the install report
(`POST /api/sync/installed`) may name what the PC wrote (`written`).

`PUT /api/sync/live?fresh=1` (PCBOTH R2): the PC's Bambu Studio folder changed (stable <-> Beta); the server treats
the upload as that folder's first sync (builds.store_upload `fresh`). `POST /api/sync/heartbeat` (PCBOTH R3):
{outcome, waiting_since, app}, at most HEARTBEAT_MAX bytes, from the sync PC only: the PC is waiting for a slicer to
close (or that wait is over); `GET /api/profiles/status` shows it as `pc.waiting`.

Times in responses are ISO 8601 UTC text (`2026-11-02T08:01:00Z`, ruling S18). Every state-changing route writes
one audit line: what, `device_id`, a few plain fields and the result; never a body, a query string or a token.
"""
from __future__ import annotations

import datetime
import json
import logging
import re

import anyio.from_thread
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import library as library_mod
from .profiles import builds, lines as lines_mod
from .profiles.errors import ProfileError

log = logging.getLogger(__name__)

MAX_JSON = 64 << 10                     # a small JSON body (rebuild, installed, PATCH, propose)
HEARTBEAT_MAX = 1024                    # the PC sync's heartbeat (PCBOTH R3)
_OUTCOME = re.compile(r"[a-z_]{1,32}")
MAX_TEXT = lines_mod.MAX_TEXT           # vendor, line, material, bambu_parent
HASH_RE = re.compile(r"[0-9a-f]{64}")
USER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_PLAIN = re.compile(r"[A-Za-z0-9_.-]{1,64}")


# ---------- small helpers ----------

def _bad(message: str) -> ProfileError:
    return ProfileError(400, "bad_request", message)


def iso(t) -> str | None:
    """Epoch seconds as ISO 8601 UTC (`...Z`); text is kept as it is; anything else is None."""
    if isinstance(t, bool) or t is None:
        return None
    if isinstance(t, str):
        return t
    if isinstance(t, (int, float)):
        try:
            d = datetime.datetime.fromtimestamp(float(t), datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
        return d.isoformat(timespec="seconds").replace("+00:00", "Z")
    return None


def _iso_at(d: dict | None, key: str = "at") -> dict | None:
    if not isinstance(d, dict):
        return d
    return {**d, key: iso(d.get(key))}


def _safe(v) -> str:
    s = str(v)
    return s if _PLAIN.fullmatch(s) else "<invalid>"


def _audit(what: str, device, fn, **fields):
    """Run `fn` and log one line: `<what> device_id=<id> k=v ... result=ok|<exception class>`."""
    result = "ok"
    try:
        return fn()
    except Exception as e:
        result = type(e).__name__
        raise
    finally:
        extra = "".join(f" {k}={_safe(v)}" for k, v in fields.items())
        log.info("%s device_id=%s%s result=%s", what, _safe(device), extra, result)


async def _read_capped(request: Request, cap: int, too_big: ProfileError) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.strip().isdigit() and int(declared) > cap:
        raise too_big
    buf = bytearray()
    try:
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > cap:
                raise too_big
    except ClientDisconnect:
        raise _bad("the request body was cut off") from None
    return bytes(buf)


async def _json(request: Request) -> dict:
    raw = await _read_capped(request, MAX_JSON, ProfileError(413, "too_large", "the request body is too large"))
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise _bad("the request body must be JSON") from None
    if not isinstance(body, dict):
        raise _bad("the request body must be a JSON object")
    return body


def _text(body: dict, key: str, *, required: bool = True, empty_ok: bool = False, at_ok: bool = True) -> str:
    """`body[key]` stripped, checked by the shared `lines.text_problem` (text of at most MAX_TEXT characters, no
    `@` unless `at_ok`); 400 `bad_request` otherwise."""
    v = body.get(key)
    if v is None and not required:
        return ""
    problem = lines_mod.text_problem(v, at_ok=at_ok)
    if problem:
        raise _bad(f"{key} {problem}")
    v = v.strip()
    if not v and not empty_ok:
        raise _bad(f"{key} is required")
    return v


class _StreamReader:
    """A blocking `read(n)` over `request.stream()`, for use from a threadpool thread (anyio worker)."""

    def __init__(self, request: Request):
        self._it = request.stream().__aiter__()
        self._buf = bytearray()
        self._done = False

    def readable(self) -> bool:
        return True

    def _next(self) -> bytes | None:
        async def step():
            try:
                return await self._it.__anext__()
            except StopAsyncIteration:
                return None
        return anyio.from_thread.run(step)

    def read(self, n: int = -1) -> bytes:
        while not self._done and (n is None or n < 0 or len(self._buf) < n):
            try:
                chunk = self._next()
            except ClientDisconnect:
                raise _bad("the upload was cut off") from None
            if chunk is None:
                self._done = True
            elif chunk:
                self._buf += chunk
        if n is None or n < 0:
            out, self._buf = bytes(self._buf), bytearray()
        else:
            out, self._buf = bytes(self._buf[:n]), self._buf[n:]
        return out


# ---------- views ----------

def _state_view(device: str) -> dict:
    v = builds.state_view(device)
    v["build"] = _iso_at(v.get("build"), "created")
    v["last_attempt"] = _iso_at(v.get("last_attempt"))
    v["installed"] = _iso_at(v.get("installed"))
    v["rebuild_requested"] = _iso_at(v.get("rebuild_requested"))
    return v


def _status_view() -> dict:
    v = builds.status()
    v["build"] = _iso_at(v.get("build"), "created")
    v["last_attempt"] = _iso_at(v.get("last_attempt"))
    v["installed"] = _iso_at(v.get("installed"))
    v["pc"] = _iso_at(v.get("pc"), "last_upload")
    if isinstance(v["pc"], dict) and isinstance(v["pc"].get("waiting"), dict):
        w = v["pc"]["waiting"]
        v["pc"]["waiting"] = {"since": iso(w.get("since")), "app": w.get("app"), "at": iso(w.get("at"))}
    lib = library_mod.status()
    v["library"] = {"version": lib.get("version"), "source": lib.get("source"), "local": lib.get("local"),
                    "last_check": _iso_at(lib.get("last_check"))}
    return {k: v[k] for k in ("lines", "presets", "orca_presets", "build", "updates", "last_attempt", "installed",
                              "pc", "library", "stale", "orca_stale", "problems")}


def _preset_counts() -> dict[str, int]:
    cur = builds.current()
    m = builds.manifest(cur["stamp"]) if cur else None
    out: dict[str, int] = {}
    for p in builds.bambu_rows(m):              # Bambu Studio presets only (Orca's are counted apart)
        lid = p.get("line_id")
        if isinstance(lid, str):
            out[lid] = out.get(lid, 0) + 1
    return out


def _line_view(line: lines_mod.Line, counts: dict[str, int]) -> dict:
    return {"line_id": line.line_id, "vendor": line.vendor, "product": line.product, "material": line.material,
            "bambu_parent": line.bambu_parent, "parent_source": line.parent_source,
            "orca_parent": line.orca_parent, "orca_parent_source": line.orca_parent_source,
            "spoolman_ids": list(line.filaments), "presets": counts.get(line.line_id, 0)}


def _target(request: Request) -> str:
    """`?target=` of an upload: absent or `bambu` (Bambu Studio), `orca` (Orca Slicer); else 400."""
    t = request.query_params.get("target")
    if t is None or t == "bambu":
        return "bambu"
    if t == "orca":
        return "orca"
    raise _bad("target must be bambu or orca")


def _parents(material: str) -> dict:
    store = builds.system_store()
    if store is None:
        return {"parents": [], "synced": False}
    btype = lines_mod.bs_type(material)
    types = lines_mod.GENERIC_TYPES.get(btype, (btype,)) if btype else None
    bases = set()
    for t in types or (None,):
        bases.update(store.bases(t))
    return {"parents": sorted(b for b in bases if lines_mod.usable(store, b)), "synced": True}


# ---------- routes ----------

def routes(authed, sm) -> list[Route]:
    async def upload(request: Request, kind: str, user_id: str | None, partial: str | None = None,
                     fresh: bool = False):
        device = request.state.device
        cap = builds.KINDS[kind][1]
        declared = request.headers.get("content-length")

        def precheck() -> None:                 # before a byte of the body is read
            builds.check_owner(device)
            if declared is not None and declared.strip().isdigit() and int(declared) > cap:
                raise builds.TooLarge(f"the upload is over {cap >> 20} MiB")
        await run_in_threadpool(_audit, f"sync upload {kind}", device, precheck, stage="check")
        reader = _StreamReader(request)

        def run() -> str:
            h = builds.store_upload(kind, reader, device_id=device, user_id=user_id, partial=partial, fresh=fresh)
            if kind in ("system", "orca_system"):
                builds.request_rebuild(f"{kind.replace('_', ' ')} upload")
            return h
        return await run_in_threadpool(_audit, f"sync upload {kind}", device, run)

    @authed
    async def sync_state(request: Request):
        return JSONResponse(await run_in_threadpool(_state_view, request.state.device))

    @authed
    async def sync_live(request: Request):
        orca = _target(request) == "orca"
        user_id = request.query_params.get("user_id")
        if user_id is not None and not USER_ID.fullmatch(user_id):
            raise _bad("user_id may only have letters, digits, - and _ (at most 64)")
        partial = request.query_params.get("partial")
        if partial is not None and not builds.STAMP_RE.fullmatch(partial):
            raise _bad("partial must be a build stamp")
        fresh = request.query_params.get("fresh")     # PCBOTH R2: another Bambu Studio folder's first sync
        if fresh is not None and (fresh != "1" or orca):
            raise _bad("fresh must be 1 (Bambu Studio live uploads only)")
        h = await upload(request, "orca_live" if orca else "live", user_id, partial, fresh=fresh == "1")
        return JSONResponse({"live_hash": h, **({"fresh": True} if fresh == "1" else {})})

    @authed
    async def sync_system(request: Request):
        kind = "orca_system" if _target(request) == "orca" else "system"
        h = await upload(request, kind, None)
        key = builds.KINDS[kind][3] + "system_presets"
        presets = await run_in_threadpool(lambda: builds.meta().get(key))
        return JSONResponse({"system_hash": h, "presets": int(presets or 0)})

    @authed
    async def sync_rebuild(request: Request):
        device = request.state.device
        body = await _json(request)
        lh, olh = body.get("live_hash"), body.get("orca_live_hash")       # orca_live_hash: Ruling O
        for key, v in (("live_hash", lh), ("orca_live_hash", olh)):
            if v is not None and not (isinstance(v, str) and HASH_RE.fullmatch(v)):
                raise _bad(f"{key} must be a sha256 hex digest")

        def run() -> None:
            builds.check_owner(device)
            builds.request_rebuild("pc sync", lh, orca_live_hash=olh)
        await run_in_threadpool(_audit, "sync rebuild", device, run)
        return JSONResponse({"requested": True}, status_code=202)

    @authed
    async def sync_build(request: Request):
        stamp = request.query_params.get("stamp", "")
        data = await run_in_threadpool(builds.build_zip, stamp)
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="build-{_safe(stamp)}.zip"'})

    @authed
    async def sync_installed(request: Request):
        device = request.state.device
        body = await _json(request)
        stamp = body.get("stamp")
        if not isinstance(stamp, str):
            raise _bad("stamp is required")
        trees = body.get("trees")               # Ruling AB: ["base"] | ["base", "orca"]; absent = ["base"]
        written = body.get("written")           # {"base"|"orca": [names]}: what the PC wrote (absent: an older PC)
        inst = await run_in_threadpool(_audit, "sync installed", device,
                                       lambda: builds.record_installed(stamp, device, trees, written), stamp=stamp)
        return JSONResponse({"installed": _iso_at(inst)})

    @authed
    async def sync_heartbeat(request: Request):
        """PCBOTH R3: the PC sync is waiting for Bambu Studio (or Orca Slicer) to close (at most one an hour), or
        that wait is over (once). A tiny body (HEARTBEAT_MAX), three plain fields, nothing else."""
        device = request.state.device
        raw = await _read_capped(request, HEARTBEAT_MAX, ProfileError(413, "too_large", "the heartbeat is too large"))
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise _bad("the request body must be JSON") from None
        if not isinstance(body, dict) or set(body) - {"outcome", "waiting_since", "app"}:
            raise _bad("a heartbeat has only outcome, waiting_since and app")
        outcome, since, app = body.get("outcome"), body.get("waiting_since"), body.get("app")
        if not (isinstance(outcome, str) and _OUTCOME.fullmatch(outcome)):
            raise _bad("outcome must be a sync outcome")
        if since is not None and (isinstance(since, bool) or not isinstance(since, (int, float))
                                  or not 0 <= since < 1e11):
            raise _bad("waiting_since must be epoch seconds")
        if app is not None and app not in builds.HEARTBEAT_APPS:
            raise _bad("app must be Bambu Studio or Orca Slicer")
        await run_in_threadpool(_audit, "sync heartbeat", device,
                                lambda: builds.record_heartbeat(device, outcome, since, app), outcome=outcome)
        return JSONResponse({"ok": True})

    @authed
    async def profiles_status(request: Request):
        return JSONResponse(await run_in_threadpool(_status_view))

    @authed
    async def profiles_updates(request: Request):
        return JSONResponse(await run_in_threadpool(builds.updates_view))

    @authed
    async def profiles_lines(request: Request):
        def build() -> list[dict]:
            counts = _preset_counts()
            return [_line_view(l, counts) for _k, l in sorted(lines_mod.load().items())]
        return JSONResponse({"lines": await run_in_threadpool(build)})

    @authed
    async def line_patch(request: Request):
        device = request.state.device
        lid = request.path_params["line_id"]
        body = await _json(request)
        # `bambu_parent` and/or `orca_parent` (Task 3); at least one
        parent = _text(body, "bambu_parent", at_ok=False) if "bambu_parent" in body or "orca_parent" not in body \
            else None
        oparent = _text(body, "orca_parent", at_ok=False) if "orca_parent" in body else None

        def run() -> dict:
            store = builds.system_store() if parent is not None else None
            ostore = builds.orca_store() if oparent is not None else None
            with lines_mod.transaction() as ls:
                if lid not in ls:
                    raise ProfileError(404, "not_found", f"no line {lid!r}")
                if parent is not None:
                    lines_mod.check_parent(parent, store)
                # the Orca store's own spelling: Orca resolves `inherits "<name> @System"` by exact name (fix I1)
                canon = lines_mod.check_orca_parent(oparent, ostore) if oparent is not None else None
                if parent is not None:
                    lines_mod.set_parent(ls, lid, parent)
                if canon is not None:
                    lines_mod.set_parent(ls, lid, canon, target="orca")
                line = ls[lid]
            builds.request_rebuild("line parent")
            return _line_view(line, _preset_counts())
        line = await run_in_threadpool(_audit, "line parent", device, run, line=lid)
        return JSONResponse({"line": line})

    @authed
    async def parents(request: Request):
        material = request.query_params.get("material", "").strip()
        if len(material) > MAX_TEXT:
            raise _bad(f"material is longer than {MAX_TEXT} characters")
        return JSONResponse(await run_in_threadpool(_parents, material))

    @authed
    async def propose(request: Request):
        body = await _json(request)
        vendor, line, material = _text(body, "vendor"), _text(body, "line"), _text(body, "material",
                                                                                     required=False, empty_ok=True)

        def run() -> dict:
            return lines_mod.propose(vendor, line, material, library=library_mod.load(),
                                     store=builds.system_store(), lines=lines_mod.load(),
                                     orca_store=builds.orca_store())
        return JSONResponse(await run_in_threadpool(run))

    @authed
    async def library_local(request: Request):
        device = request.state.device
        limit = library_mod.LOCAL_LIMIT
        too_big = ProfileError(400, "invalid_entry", f"entry is larger than {limit // 1024} KiB",
                               problems=[f"entry is larger than {limit // 1024} KiB"])
        raw = await _read_capped(request, limit, too_big)

        def run():
            problems = _local_problems(raw)
            if problems:
                raise ProfileError(400, "invalid_entry", "; ".join(problems), problems=problems)
            try:
                entry, line_id = library_mod.add_local(raw)
            except ValueError as e:
                raise ProfileError(400, "invalid_entry", str(e), problems=[str(e)]) from None
            builds.request_rebuild("library local")
            return entry, line_id
        entry, line_id = await run_in_threadpool(_audit, "library local", device, run)
        return JSONResponse({"entry": entry, "line_id": line_id}, status_code=201)

    return [
        Route("/api/sync/state", sync_state),
        Route("/api/sync/live", sync_live, methods=["PUT"]),
        Route("/api/sync/system", sync_system, methods=["PUT"]),
        Route("/api/sync/rebuild", sync_rebuild, methods=["POST"]),
        Route("/api/sync/build", sync_build),
        Route("/api/sync/installed", sync_installed, methods=["POST"]),
        Route("/api/sync/heartbeat", sync_heartbeat, methods=["POST"]),
        Route("/api/profiles/status", profiles_status),
        Route("/api/profiles/updates", profiles_updates),
        Route("/api/profiles/lines", profiles_lines),
        Route("/api/profiles/lines/{line_id}", line_patch, methods=["PATCH"]),
        Route("/api/profiles/parents", parents),
        Route("/api/profiles/propose", propose, methods=["POST"]),
        Route("/api/library/local", library_local, methods=["POST"]),
        *web_routes(authed, sm),
    ]


def _local_problems(raw: bytes) -> list[str]:
    """The schema problems of a local entry, as a list (`add_local` joins them into one message); [] when the
    entry is valid or is not a JSON object at all (`add_local` then says why)."""
    try:
        entry = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return []
    if not isinstance(entry, dict):
        return []
    entry.pop("local", None)
    entry.setdefault("schema_version", library_mod.SCHEMA_VERSION)
    entry.setdefault("updated", datetime.date.today().isoformat())
    return list(library_mod.validate(entry, local=True))


# ---------- the web unit's preset writes (its user may not write profiles/ itself) ----------

def _ids(body: dict) -> list[int]:
    ids = body.get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise _bad("ids must be a list of Spoolman filament ids")
    return ids


def _text_field(body: dict, key: str, required: bool = True) -> str:
    v = body.get(key)
    if v is None and not required:
        return ""
    if not isinstance(v, str) or len(v) > 400 or (required and not v.strip()):
        raise _bad(f"{key} must be text")
    return v


def web_routes(authed, sm) -> list[Route]:
    """The MCP tools' and phone web app's preset writes, as the web unit sends them through its kit token:
    `web.presets` runs here, in the kit (the owner of profiles/), so the web unit only reads that folder."""
    from .web import presets

    @authed
    async def line_add(request: Request):
        body = await _json(request)
        line, ids = _text_field(body, "line"), _ids(body)
        return JSONResponse(await run_in_threadpool(
            _audit, "web line add", request.state.device, lambda: presets.add_ids(sm, line, ids)))

    @authed
    async def line_new(request: Request):
        body = await _json(request)
        args = (_text_field(body, "name"), _text_field(body, "vendor"), _ids(body),
                _text_field(body, "orca_parent", False), _text_field(body, "bs_template"))
        return JSONResponse(await run_in_threadpool(
            _audit, "web line new", request.state.device, lambda: presets.add_line(sm, *args)))

    @authed
    async def generate(request: Request):
        await _json(request)
        return JSONResponse(await run_in_threadpool(
            _audit, "web generate", request.state.device, presets.generate))

    return [Route("/api/profiles/web/line_add", line_add, methods=["POST"]),
            Route("/api/profiles/web/line_new", line_new, methods=["POST"]),
            Route("/api/profiles/web/generate", generate, methods=["POST"])]
