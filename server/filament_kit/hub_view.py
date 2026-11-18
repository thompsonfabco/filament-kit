"""The Hub at a glance (R83 s5): the data behind `GET /api/hub`, one read-only answer for the apps' Hub screen.

    {name, version, newest: {version, checked_at}?, update_available, checks: [{group, state, text, fix?}],
     getting_started: {done, total, hidden, finished}, features: [{id, name, on}], catalog: {version?, checked_at?},
     backup: {last_at?, nightly}, reader: {engine, key_set}, devices: [{name, kind, version?, last_seen?,
     out_of_date, this}], records_kept, spoolman_url?, hub_page?}

Every time (`checked_at`, `last_at`, `last_seen`) is ONE type: whole seconds since 1970 (an integer), null or absent
when not known; no ISO text.

Everything is redacted as the Overview is for a locked page (`redact`): no addresses, serial numbers or secrets; a
check's text and fix are cleaned, the devices are names only. Looking costs no network call but the checks' own (the
Overview's rows). A source that cannot be read leaves its part out or at its empty value: the answer never fails for
one of them. The Getting started counts come from the caller (`getting_started`: the first-run panel's counts);
without them the panel is hidden, which is what an unreadable panel means (R82 s4.6).
"""
from __future__ import annotations

import datetime
import logging
import re

from . import __version__, config, modules, redact

log = logging.getLogger(__name__)

SPOOLMAN_PORT = 7912
HUB_PAGE_PATH = "/setup/"
CHECK_STATES = {"ok": "ok", "fail": "look", "info": "note"}     # status.Row.state -> the contract's; detail rows go
KINDS = ("phone", "pc", "station", "web", "reader", "builtin")
BACKUP_PAGES = 20                                               # pages of 1000 events read for the last backup
_HOST = re.compile(r"[A-Za-z0-9.\-]{1,253}|\[[0-9A-Fa-f:.]{2,45}\]")


def epoch(t) -> int | None:
    """A time as whole seconds since 1970, the one type every time of the answer has: an epoch number is cut to whole
    seconds, an ISO 8601 text (a missing offset is UTC) is converted; None when it is neither or not a real time."""
    if isinstance(t, bool):
        return None
    if isinstance(t, (int, float)):
        try:
            datetime.datetime.fromtimestamp(float(t), datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
        return int(t)
    if isinstance(t, str) and t.strip():
        try:
            d = datetime.datetime.fromisoformat(t.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return int((d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)).timestamp())
    return None


iso = epoch          # the earlier name of this function; the answer carries no ISO text


def version_tuple(v) -> tuple[int, ...] | None:
    """'0.7.0' -> (0, 7, 0); a leading 'v' and a suffix after the numbers ('0.7.0-rc1') are ignored; None otherwise."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", v) if isinstance(v, str) else None
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def older(version, than) -> bool:
    """`version` is lower than `than`; False when either is not known (a device that sends nothing is never called
    out of date)."""
    a, b = version_tuple(version), version_tuple(than)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) < b + (0,) * (n - len(b))


def _safe(what: str, fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - one source must not take the answer down
        log.warning("hub view: cannot read %s", what, exc_info=True)
        return default


def _host(host) -> str | None:
    """The host the caller used (no port, no scheme), or None when it is not a plain host name or address."""
    if not isinstance(host, str):
        return None
    h = host.strip()
    return h if _HOST.fullmatch(h) else None


def spoolman_url(cfg: dict, host: str | None) -> str | None:
    """Spoolman's own page: with Spoolman on the Hub `http://<the host the caller used>:7912` (None when the caller
    has no usable host: the web app on its public address); with one elsewhere, the configured address."""
    host = _host(host)
    if "spoolman" in modules.enabled(cfg):
        return f"http://{host}:{SPOOLMAN_PORT}" if host else None
    url = cfg.get("spoolman_url")
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None


def hub_page(host: str | None) -> str | None:
    host = _host(host)
    return f"https://{host}{HUB_PAGE_PATH}" if host else None


def checks(cfg: dict, client_factory=None) -> list[dict]:
    """The Overview's rows as `{group, state, text, fix?}`, redacted; the detail rows (continuations) are left out."""
    from . import status
    known = redact.known_values(cfg)
    out = []
    for r in status.collect(cfg, client_factory):
        state = CHECK_STATES.get(r.state)
        if state is None:
            continue
        row = {"group": r.group, "state": state, "text": redact.text(r.text, known)}
        if r.fix:
            row["fix"] = redact.text(r.fix, known)
        out.append(row)
    return out


def features(cfg: dict) -> list[dict]:
    on = modules.enabled(cfg)
    return [{"id": m.name, "name": m.title, "on": m.name in on} for m in modules.MODULES.values()]


def catalog() -> dict:
    from . import library
    st = library.status()
    out: dict = {}
    if st.get("source") != "none":
        out["version"] = st.get("version")
    lc = st.get("last_check") or {}
    at = iso(lc.get("at"))
    if at:
        out["checked_at"] = at
    return out


def last_backup() -> str | None:
    """When the last backup finished (the Hub's event store: the backup folder is root's alone)."""
    from . import events
    last, since = None, 0
    for _ in range(BACKUP_PAGES):
        page = events.read(since, 1000, ["backup.finished"])
        for e in page.get("events") or []:
            last = e.get("at") or last
        if not page.get("events") or page["next"] <= since:
            break
        since = page["next"]
    return iso(last)


def reader(cfg: dict) -> dict:
    """{engine, key_set}: which label reader answers first ("local", "cloud" or "off") and whether the Anthropic key is
    set. Never the key."""
    from . import cli, intake
    order = intake.reader_order(cfg)
    try:
        key_set = (config.paths().etc / cli.KEY_FILE).stat().st_size > 0
    except OSError:
        key_set = False
    return {"engine": order[0] if order else "off", "key_set": key_set}


def devices(cfg: dict, this_device: str | None = None, hub_version: str | None = None, paired: list | None = None,
            readers: list | None = None) -> list[dict]:
    """Names, kind, version and last seen of what is paired, and the Tag Readers: no ids, no addresses.

    `paired` is `pairing.devices()` (each row may also carry `kind` and `version` where the pairing keeps them);
    `readers` is `reader_tokens.readers()`. A row with no kind has the name alone. Out of date is R83 s9.4: a Weigh
    Station or a Slicer Sync PC below the Hub's version; a Tag Reader below the firmware on offer; a phone only when
    the pairing says so (`out_of_date`)."""
    from . import pairing, reader_tokens
    hub_version = hub_version or __version__
    rows = []
    for d in paired if paired is not None else pairing.devices():
        kind = d.get("kind") if d.get("kind") in KINDS else ("station" if d.get("type") == "station" else None)
        version = d.get("version") if isinstance(d.get("version"), str) and d.get("version") else None
        late = kind in ("station", "pc") and older(version, hub_version)
        rows.append({"name": redact.text(str(d.get("name") or ""), redact.known_values(cfg)), "kind": kind,
                     **({"version": version} if version else {}), "last_seen": iso(d.get("last_seen")),
                     "out_of_date": bool(late or d.get("out_of_date") is True), "this": d.get("id") == this_device})
    for r in readers if readers is not None else reader_tokens.readers():
        rows.append({"name": r["name"], "kind": "reader", **({"version": str(r["build"])} if r.get("build") else {}),
                     "last_seen": iso(r.get("last_seen")), "out_of_date": bool(r.get("out_of_date")), "this": False})
    return rows


def records_kept(cfg: dict) -> int:
    """How many "Recently added" records the Hub keeps (Settings > Label Reader, Records kept)."""
    from . import intake_history
    return intake_history.keep(cfg)


def build(cfg: dict | None = None, *, host: str | None = None, this_device: str | None = None,
          getting_started: dict | None = None, client_factory=None, paired: list | None = None,
          readers: list | None = None) -> dict:
    """The answer of `GET /api/hub`. `host`: the host name the caller used for the Hub (None on the public address:
    `hub_page` and, with Spoolman on the Hub, `spoolman_url` are then absent). `this_device`: the caller's pairing id
    (marks its row). `getting_started`: {done, total, hidden, finished} of the first-run panel."""
    from . import updates
    cfg = cfg if cfg is not None else config.load()
    up = _safe("the update state", updates.summary, {}) or {}
    newest_at = iso(up.get("checked_at"))
    out: dict = {"name": str(cfg.get("server_name") or "Hub"), "version": up.get("installed") or __version__}
    if up.get("latest"):
        out["newest"] = {"version": up["latest"], "checked_at": newest_at}
    out["update_available"] = bool(up.get("newer"))
    out["checks"] = _safe("the checks", lambda: checks(cfg, client_factory), [])
    gs = getting_started or {}
    out["getting_started"] = {"done": int(gs.get("done") or 0), "total": int(gs.get("total") or 0),
                              "hidden": bool(gs.get("hidden", True)), "finished": bool(gs.get("finished", False))}
    out["features"] = _safe("the features", lambda: features(cfg), [])
    out["catalog"] = _safe("the catalog", catalog, {})
    last = _safe("the last backup", last_backup, None)
    out["backup"] = {**({"last_at": last} if last else {}), "nightly": "backup" in modules.enabled(cfg)}
    out["reader"] = _safe("the label reader", lambda: reader(cfg), {"engine": "off", "key_set": False})
    out["devices"] = _safe("the devices", lambda: devices(cfg, this_device, out["version"], paired, readers), [])
    out["records_kept"] = records_kept(cfg)
    sm, page = spoolman_url(cfg, host), hub_page(host)
    if sm:
        out["spoolman_url"] = sm
    if page:
        out["hub_page"] = page
    return out
