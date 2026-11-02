"""`filament-kit migrate-ops <bundle> [--apply]`: a filament-ops VM's data into this kit install (spec 4.5).

The bundle is what `tools/export_ops.sh` wrote on the ops VM (a tar.gz, or the folder it unpacks to):
MANIFEST.json, lines.py, regen_config.json, server.json, filament_orders.json, spoolman.db (an sqlite online
backup), presets/{installed,live}/{bs/base,orca}/ and, unless exported with --no-secrets,
secrets/{web_passphrase,oauth.json,anthropic_key}. The H2D slot token is not in it: the runbook copies it.

Steps, each reporting what it would do (dry run, the default) or did (`--apply`, root):
1. spoolman  the bundle's database into the spoolman module's data dir (FK_SPOOLMAN_DATA, /var/lib/spoolman),
             services stopped meanwhile; a database that already holds spools is only replaced with
             --replace-spoolman. The counts are checked after the copy.
2. lines     lines.py -> lines.json: vendor/product (the ops name minus its vendor), the Bambu Studio template as
             `bambu_parent` and the Orca library parent as `orca_parent` (both source "user"), the members, and
             the `filament_id` of the line's existing Bambu Studio presets, so the first build adopts them.
             `extra.line` is set on every member filament the kit would otherwise group into another line
             (the lines with no library entry, and lines such as "SUNLU High Speed PLA+ 2.0").
3. presets   owner-edits.json (the record a build carries when there is no installed build, ruling S34): per
             preset of an ops line, the calibrated keys (CALIBRATED) from the live preset plus anything changed in
             the app since the ops install, and the note lines below MARK; deleted.json from the ops deletions.
             Skipped once the kit has built presets (its builds carry the record from then on).
4. web       oauth.json (same format, so Claude's connector stays signed in), the passphrase hash and the
             Anthropic key; a file the kit already has is never overwritten (its tokens are newer).
5. config    the owner's values (placement, locations, tare hints, tag readers, slot service, orders file,
             Orca printers, public URL, remote host name); a key the owner already changed from the kit default
             is kept and reported. The bundle's order list is copied to the kit's state dir.

Idempotent: a second --apply with the same bundle changes nothing. Every file replaced is first copied to
FK_BACKUPS/migrate-ops-<stamp>/. Secret values are never printed.
"""
from __future__ import annotations

import ast
import collections
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urlparse

from . import config
from . import library as library_mod
from .pairing import _write_atomic, make_state_dir
from .profiles import inapp, lines as lines_mod
from .profiles.lines import Line
from .spoolman import Spoolman, SpoolmanError

SPOOLMAN_VERSION = "0.27.0"         # install/spoolman.sh SPOOLMAN_VERSION: one database schema on both sides
STEPS = ("spoolman", "lines", "presets", "web", "config")
# what the owner calibrated in the apps (ops gen.py FLOW/PA/NOZZLE/PLATE keys); Orca uses the same names
CALIBRATED = ("filament_flow_ratio", "enable_pressure_advance", "pressure_advance", "filament_max_volumetric_speed",
              "nozzle_temperature", "nozzle_temperature_initial_layer", "hot_plate_temp",
              "hot_plate_temp_initial_layer", "textured_plate_temp", "textured_plate_temp_initial_layer")

# filament-ops code constants (vm/intake.py, gen.py, h2d_tools.py): the owner's values the kit keeps in config
OPS_LOCATIONS = ["Sealed stock", "Bench Rack 2", "Bench Rack 3", "Little Rack 4", "Storage Cabinet A",
                 "Upper storage (unverified)", "Overflow bags"]
OPS_PLACEMENT = {"pla_location": "Rack 1", "box_prefix": "Storage Cabinet A - Cereal Box ", "box_count": 50,
                 "overflow": "Overflow bags", "sealed_location": "Sealed stock"}
OPS_TARE_HINTS = {"SUNLU": 213, "Push Plastic": 218, "Bambu": 250, "Polymaker/Panchroma": 142,
                  "ELEGOO cardboard": 154, "OVERTURE": 155, "GEEETECH": 180, "JAYO": 120, "DEEPLEE": 140}
OPS_LASTTAG = "http://lasttag.home.arpa:5002/last-tag"
OPS_STATION = "http://intake.home.arpa:5003"
OPS_SLOT_STATE = "http://127.0.0.1:8105/api/state"
OPS_SLOT_SET = "http://127.0.0.1:8104/set-slot"
OPS_SLICER_PRINTERS = [{"name": "Sovol SV08 MAX", "slicer": "orca", "nozzles": ["0.4", "0.6", "1.0"],
                        "label": "SV08 MAX", "compatible_printers": {"0.4": "Sovol SV08 MAX",
                                                                     "0.6": "Sovol SV08 MAX 0.6",
                                                                     "1.0": "Sovol SV08 MAX 1.0"}}]
OPS_ORCA_NOZZLES = ["0.4", "0.6", "0.8"]
OPS_ACME_WINDOW = "03:10 America/New_York"   # the ops certbot.timer drop-in: pfSense opens port 80 03:00-03:30
OPS_H2D_SERIAL = "ops-h2d"         # a model-only registry entry (the real serial is not in the bundle)
_HASH = re.compile(r"[0-9a-f]+ [0-9a-f]+")
_UNITS = ("filament-kit-web", "filament-kit", "spoolman")       # stopped while the database is replaced


# ---------- the bundle ----------

def _literal(node, names: dict, where: str):
    """ops linesfile.py: only plain literals, and names assigned before (G = "Generic")."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        items = [_literal(n, names, where) for n in node.elts]
        return items if isinstance(node, ast.List) else tuple(items)
    if isinstance(node, ast.Dict) and None not in node.keys:
        return {_literal(k, names, where): _literal(v, names, where) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.Name) and node.id in names:
        return names[node.id]
    raise ValueError(f"{where}:{getattr(node, 'lineno', '?')}: not a plain literal")


@dataclass
class OpsLine:
    name: str
    vendor: str
    ids: list[int]
    orca_parent: str
    bs_template: str
    product: str = ""
    material: str = ""
    fid: str | None = None
    fid_note: str = ""


class Bundle:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.manifest = self._json("MANIFEST.json")
        if not isinstance(self.manifest, dict) or self.manifest.get("format") != 1:
            raise ValueError(f"{root} is not a filament-ops export bundle (no MANIFEST.json format 1)")
        self.id = f"{self.manifest.get('host')}-{self.manifest.get('created')}"

    def _json(self, name: str):
        try:
            return json.loads((self.root / name).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return None

    def obj(self, name: str) -> dict:
        d = self._json(name)
        return d if isinstance(d, dict) else {}

    def secret(self, name: str) -> Path | None:
        p = self.root / "secrets" / name
        return p if self.manifest.get("secrets") and p.is_file() else None

    def lines(self) -> list[OpsLine]:
        path = self.root / "lines.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), "lines.py")
        names: dict = {}
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue                                    # docstring
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                raise ValueError(f"lines.py:{node.lineno}: only NAME = literal assignments are allowed")
            names[node.targets[0].id] = _literal(node.value, names, "lines.py")
        out = []
        for row in names.get("LINES") or []:
            name, vendor, ids, orca, bs = row[:5]
            out.append(OpsLine(name.strip(), vendor.strip(), [int(i) for i in ids], (orca or "").strip(),
                               (bs or "").split("|", 1)[0].strip()))
        return out

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(f"{(self.root / 'spoolman.db').resolve().as_uri()}?mode=ro&immutable=1", uri=True)

    def counts(self) -> dict[str, int]:
        db = self._db()
        try:
            return {t: db.execute(f"select count(*) from {t}").fetchone()[0] for t in ("spool", "filament", "vendor")}
        finally:
            db.close()

    def filaments(self) -> dict[int, dict]:
        """Spoolman API-shaped filaments: {id, name, material, vendor: {name}, extra: {key: JSON text}}."""
        db = self._db()
        try:
            out = {i: {"id": i, "name": n or "", "material": m or "", "vendor": {"name": v} if v else None, "extra": {}}
                   for i, n, m, v in db.execute("select f.id, f.name, f.material, v.name from filament f "
                                                "left join vendor v on v.id = f.vendor_id")}
            for i, k, val in db.execute("select filament_id, key, value from filament_field"):
                if i in out:
                    out[i]["extra"][k] = val
            return out
        finally:
            db.close()

    def presets(self, which: str, tree: str) -> dict[str, dict]:
        folder = self.root / "presets" / which / ("bs/base" if tree == "bs" else "orca")
        out = {}
        if folder.is_dir():
            for p in sorted(folder.glob("*.json")):
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, ValueError):
                    continue
                if isinstance(d, dict):
                    out[p.stem] = d
        return out


@contextmanager
def open_bundle(path) -> Iterator[Bundle]:
    """The bundle folder, or a tar.gz unpacked into a private temp dir that is removed afterwards."""
    p = Path(path)
    if p.is_dir():
        yield Bundle(p if (p / "MANIFEST.json").is_file() else p / "ops-bundle")
        return
    tmp = tempfile.mkdtemp(prefix="fk-ops-bundle-")
    try:
        with tarfile.open(p, "r:*") as tar:
            tar.extractall(tmp, filter="data")
        yield Bundle(Path(tmp) / "ops-bundle")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- the run ----------

def _spoolman_dir() -> Path:
    return Path(os.environ.get("FK_SPOOLMAN_DATA", "/var/lib/spoolman"))


def _no_systemd() -> bool:
    return os.environ.get("FK_NO_SYSTEMD") == "1"


def _is_root() -> bool:
    return getattr(os, "geteuid", lambda: -1)() == 0


def _chown(path: Path, user: str | None, group: str) -> None:
    """Root only: hand a file to user:group (names that do not exist leave it as it is)."""
    if not _is_root():
        return
    try:
        shutil.chown(path, user=user, group=group)
    except (LookupError, OSError):
        pass


def _nil(v) -> bool:
    if isinstance(v, str):
        return v == "nil"
    if isinstance(v, list):
        return any(_nil(x) for x in v)
    return False


class _Ctx:
    def __init__(self, apply: bool, out: Callable[[str], None], library, replace_spoolman: bool, sm):
        self.apply, self.out, self.library, self.replace_spoolman = apply, out, library, replace_spoolman
        self.sm = sm
        self.errors = 0
        self.stamp = time.strftime("%Y%m%d-%H%M%S")
        self._backups: Path | None = None
        self.stopped: list[str] = []
        self.record_path = config.paths().state / "migrate-ops.json"
        try:
            rec = json.loads(self.record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rec = {}
        self.record = rec if isinstance(rec, dict) else {}

    def say(self, step: str, text: str) -> None:
        self.out(f"[{step}] {text}")

    def fail(self, step: str, text: str) -> None:
        self.errors += 1
        self.out(f"[{step}] ERROR: {text}")

    def verb(self, would: str, did: str) -> str:
        return did if self.apply else f"would {would}"

    def backup(self, path: Path, name: str | None = None) -> None:
        if not path.exists():
            return
        if self._backups is None:
            self._backups = config.paths().backups / f"migrate-ops-{self.stamp}"
            self._backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(path, self._backups / (name or path.name))

    def done(self, bundle: Bundle, step: str) -> bool:
        return step in ((self.record.get("bundles") or {}).get(bundle.id) or {})

    def mark(self, bundle: Bundle, step: str) -> None:
        if not self.apply or self.done(bundle, step):
            return                              # the first time counts: a second run rewrites nothing
        self.record.setdefault("bundles", {}).setdefault(bundle.id, {})[step] = int(time.time())
        make_state_dir(self.record_path.parent)
        _write_atomic(self.record_path, (json.dumps(self.record, indent=2) + "\n").encode(), 0o644, state_owned=True)

    def systemctl(self, *args: str) -> int:
        if _no_systemd():
            return 0
        try:
            return subprocess.run(["systemctl", *args], capture_output=True, timeout=120).returncode
        except (OSError, subprocess.SubprocessError):
            return 1

    def stop_services(self) -> None:
        for unit in _UNITS:
            if not _no_systemd() and self.systemctl("is-active", "--quiet", unit) == 0:
                self.systemctl("stop", unit)
                self.stopped.append(unit)

    def start(self, unit: str) -> None:
        if unit in self.stopped:
            self.systemctl("start", unit)
            self.stopped.remove(unit)

    def restart_rest(self) -> None:
        for unit in reversed(list(self.stopped)):
            self.systemctl("start", unit)
        self.stopped.clear()


def _db_counts(path: Path) -> tuple[int, int]:
    try:
        db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return (0, 0)
    try:
        out = []
        for t in ("spool", "filament"):
            try:
                out.append(db.execute(f"select count(*) from {t}").fetchone()[0])
            except sqlite3.Error:
                out.append(0)
        return out[0], out[1]
    finally:
        db.close()


def _wait_spoolman(sm, seconds: float = 120) -> bool:
    end = time.time() + seconds
    while True:
        try:
            sm.ping()
            return True
        except SpoolmanError:
            if time.time() > end:
                return False
            time.sleep(2)


# ---------- 1. Spoolman ----------

def step_spoolman(b: Bundle, ctx: _Ctx) -> None:
    S = "spoolman"
    m = b.manifest.get("spoolman") or {}
    have = b.counts()
    if (m.get("spool"), m.get("filament")) != (have["spool"], have["filament"]):
        ctx.fail(S, f"the bundle's database has {have['spool']} spools, {have['filament']} filaments but its "
                    f"manifest says {m.get('spool')}, {m.get('filament')}: export again")
        return
    if m.get("version") and m.get("version") != SPOOLMAN_VERSION:
        ctx.fail(S, f"the bundle comes from Spoolman {m.get('version')}; the kit runs {SPOOLMAN_VERSION}: upgrade the "
                    f"ops Spoolman to {SPOOLMAN_VERSION} and export again")
        return
    target = _spoolman_dir() / "spoolman.db"
    what = f"{have['spool']} spools, {have['filament']} filaments, {have['vendor']} vendors"
    if ctx.done(b, S):
        ctx.say(S, f"already imported from this bundle ({what}); unchanged")
        return
    spools, fils = _db_counts(target) if target.exists() else (0, 0)
    if (spools or fils) and not ctx.replace_spoolman:
        ctx.fail(S, f"{target} already holds {spools} spool(s) and {fils} filament(s); not replaced (pass "
                    f"--replace-spoolman to replace it with the bundle's; a backup is kept)")
        return
    ctx.say(S, ctx.verb(f"{'replace' if target.exists() else 'create'} {target} with the bundle's database "
                        f"({what}); services stopped meanwhile, backup kept",
                        f"{target} now holds the bundle's database ({what})"))
    if not ctx.apply:
        return
    ctx.stop_services()
    target.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        p = target.with_name(target.name + suffix)
        if p.exists():
            ctx.backup(p)
            p.unlink()
    tmp = target.with_name(target.name + ".migrate.tmp")
    src, dst = b._db(), sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    os.chmod(tmp, 0o640)
    _chown(tmp, "spoolman", "spoolman")
    os.replace(tmp, target)
    if _db_counts(target) != (have["spool"], have["filament"]):
        ctx.fail(S, f"{target} does not hold the bundle's counts after the copy; restore it from the backup")
        return
    ctx.start("spoolman")
    ctx.mark(b, S)


# ---------- 2. lines ----------

def _ops_fid(line: OpsLine, live: dict, installed: dict) -> tuple[str | None, str]:
    """The filament_id of the line's Bambu Studio presets (live, else installed): the most common valid one."""
    prefix = f"{line.name} @".casefold()
    for presets in (live, installed):
        ids = collections.Counter(c.get("filament_id") for n, c in presets.items()
                                  if n.casefold().startswith(prefix) and isinstance(c.get("filament_id"), str)
                                  and lines_mod.FID.fullmatch(c["filament_id"]))
        if ids:
            best = ids.most_common(1)[0][0]
            odd = sorted(i for i in ids if i != best)
            return best, (f"{line.name}: presets carry filament_id {', '.join([best] + odd)}; the line keeps "
                          f"{best}, the build replaces the others") if odd else ""
    return None, ""


def _plan_lines(b: Bundle, fils: dict[int, dict]) -> tuple[list[OpsLine], list[str]]:
    live, inst = b.presets("live", "bs"), b.presets("installed", "bs")
    notes = []
    plan = b.lines()
    for p in plan:
        if p.name.casefold().startswith(p.vendor.casefold() + " "):
            p.product = p.name[len(p.vendor) + 1:].strip()
        else:
            p.product = p.name
            notes.append(f"{p.name}: the name does not start with its vendor {p.vendor!r}; product = the whole name, "
                         f"so its presets get new names")
        mats = collections.Counter((fils[i].get("material") or "").strip() for i in p.ids if i in fils)
        mats.pop("", None)
        p.material = mats.most_common(1)[0][0] if mats else ""
        p.fid, note = _ops_fid(p, live, inst)
        if note:
            notes.append(note)
    return plan, notes


def _apply_lines(ls: lines_mod.LineSet, plan: list[OpsLine]) -> tuple[collections.Counter, list[str]]:
    counts: collections.Counter = collections.Counter()
    notes: list[str] = []
    taken = {l.filament_id: l.line_id for l in ls.values()}
    owner: dict[int, str] = {}
    for p in plan:
        lid = lines_mod.line_id_for(p.vendor, p.product)
        line = ls.get(lid)
        before = asdict(line) if line is not None else None
        fid = p.fid if p.fid and taken.get(p.fid, lid) == lid else None
        if p.fid and fid is None:
            notes.append(f"{p.name}: filament_id {p.fid} belongs to line {taken[p.fid]}; this line gets a new one")
        if line is None:
            line = Line(lid, p.vendor, p.product, p.material, p.bs_template or None,
                        "user" if p.bs_template else "none",
                        fid or lines_mod.new_filament_id(set(taken)), lines_mod._now())
            ls[lid] = line
        else:
            if fid and fid != line.filament_id:
                notes.append(f"{lid}: filament_id {line.filament_id} -> {fid} (from your Bambu Studio presets)")
                taken.pop(line.filament_id, None)
                line.filament_id = fid
            if p.bs_template:
                line.bambu_parent, line.parent_source = p.bs_template, "user"
            if not line.material:
                line.material = p.material
        if p.orca_parent:
            line.orca_parent, line.orca_parent_source = p.orca_parent, "user"
        taken[line.filament_id] = lid
        mine = [i for i in p.ids if owner.setdefault(i, lid) == lid]
        line.filaments = sorted(set(line.filaments) | set(mine))
        for other in ls.values():                   # one line per filament: the ops line wins
            moved = sorted(set(other.filaments) & set(mine)) if other.line_id != lid else []
            if moved:
                notes.append(f"filaments {moved} moved from {other.line_id} to {lid}")
                other.filaments = [i for i in other.filaments if i not in mine]
        counts["created" if before is None else "updated" if asdict(line) != before else "unchanged"] += 1
    return counts, notes


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", (text or "").casefold())


def step_lines(b: Bundle, ctx: _Ctx) -> None:
    S = "lines"
    fils = b.filaments()
    plan, notes = _plan_lines(b, fils)
    for n in notes:
        ctx.say(S, n)
    if ctx.apply:
        with lines_mod.locked():
            ls = lines_mod.load()
            counts, more = _apply_lines(ls, plan)
            if counts["created"] or counts["updated"] or more:
                ctx.backup(lines_mod._path())
                lines_mod.save(ls)
    else:
        counts, more = _apply_lines(lines_mod.load(), plan)
    for n in more:
        ctx.say(S, n)
    adopted = sum(1 for p in plan if p.fid)
    ctx.say(S, f"{len(plan)} ops lines -> lines.json: {ctx.verb('create', 'created')} {counts['created']}, "
               f"{ctx.verb('update', 'updated')} {counts['updated']}, unchanged {counts['unchanged']}; "
               f"{adopted} keep the filament_id of their Bambu Studio presets")
    # extra.line where the kit's own grouping would put a member elsewhere
    current = dict(fils)
    try:
        for f in ctx.sm.get("filament"):            # Spoolman's view wins where it has the same filament
            if isinstance(f, dict) and f.get("id") in current and f.get("name") == current[f["id"]]["name"]:
                current[f["id"]] = f
    except (SpoolmanError, TypeError):
        pass
    need: list[tuple[int, str]] = []
    affected: set[str] = set()
    for p in plan:
        lid = lines_mod.line_id_for(p.vendor, p.product)
        for i in p.ids:
            f = current.get(i)
            if f is None:
                ctx.say(S, f"{p.name}: filament {i} is not in Spoolman; skipped")
                continue
            vendor = ((f.get("vendor") or {}).get("name") or "").strip()
            if _norm(vendor) != _norm(p.vendor):
                ctx.say(S, f"{p.name}: filament {i} has vendor {vendor!r} in Spoolman, not {p.vendor!r}; "
                           f"extra.line not set (fix the vendor in Spoolman)")
                continue
            if lines_mod.line_id_for(vendor, lines_mod.product_of(f, ctx.library)) != lid:
                need.append((i, p.product))
                affected.add(p.name)
    if not need:
        ctx.say(S, "extra.line: every member filament already groups into its line; unchanged")
        ctx.mark(b, S)
        return
    ctx.say(S, ctx.verb(f"set extra.line on {len(need)} filaments of {len(affected)} lines",
                        f"extra.line set on {len(need)} filaments of {len(affected)} lines")
            + f" ({', '.join(sorted(affected))})")
    if not ctx.apply:
        return
    try:
        ctx.sm.ensure_fields()
        for i, product in need:
            cur = ctx.sm.get(f"filament/{i}")
            if lines_mod._extra_line(cur) == product:
                continue
            ctx.sm.patch(f"filament/{i}", {"extra": {**(cur.get("extra") or {}), "line": json.dumps(product)}})
    except SpoolmanError as e:
        ctx.fail(S, f"Spoolman: {e}; run migrate-ops --apply again once Spoolman answers")
        return
    ctx.mark(b, S)


# ---------- 3. presets: owner edits ----------

def _records(live: dict, installed: dict, prefixes: tuple[str, ...]) -> tuple[dict, dict]:
    inapp_rec, notes = {}, {}
    for name, cfg in sorted(live.items()):
        if not name.casefold().startswith(prefixes):
            continue                                # the owner's own presets: the kit never writes them
        rec = {k: cfg[k] for k in CALIBRATED if k in cfg and not _nil(cfg[k])}
        old = installed.get(name)
        if old is not None:
            rec.update({k: v for k, v in inapp.diff(old, cfg).items() if not _nil(v)})
        if rec:
            inapp_rec[name] = rec
        mine = inapp.user_notes(old if old is not None else cfg, cfg)
        if mine:
            notes[name] = mine
    return inapp_rec, notes


def step_presets(b: Bundle, ctx: _Ctx) -> None:
    S = "presets"
    prof = config.paths().state / "profiles"
    if ctx.done(b, S):
        ctx.say(S, "owner edits already seeded from this bundle; unchanged")
        return
    if (prof / "installed.json").exists() or (prof / "current.json").exists():
        ctx.say(S, "the kit has built presets already: owner edits not seeded (its builds carry your in-app values)")
        return
    prefixes = tuple(f"{p.name} @".casefold() for p in b.lines())
    bs_rec, bs_notes = _records(b.presets("live", "bs"), b.presets("installed", "bs"), prefixes)
    or_rec, or_notes = _records(b.presets("live", "orca"), b.presets("installed", "orca"), prefixes)
    oe = {"stamp": None, "source": f"filament-ops {b.id}", "inapp": bs_rec, "notes": bs_notes,
          "orca_inapp": or_rec, "orca_notes": or_notes}
    ops_del = b.obj("presets/installed/deleted.json")
    try:
        kit_del = json.loads((prof / "deleted.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        kit_del = {}
    kit_del = kit_del if isinstance(kit_del, dict) else {}

    def names(*vals) -> list[str]:
        return sorted({n for v in vals if isinstance(v, list) for n in v if isinstance(n, str)})

    deleted = {**kit_del, "deleted_before": names(kit_del.get("deleted_before"), ops_del.get("bs")),
               "orca_deleted_before": names(kit_del.get("orca_deleted_before"), ops_del.get("orca"))}
    keys = sum(len(v) for v in bs_rec.values()) + sum(len(v) for v in or_rec.values())
    ctx.say(S, ctx.verb("seed", "seeded") + f" owner-edits.json: {len(bs_rec)} Bambu Studio and {len(or_rec)} Orca "
               f"Slicer presets with {keys} calibrated or in-app values, {len(bs_notes) + len(or_notes)} with your "
               f"note lines; deleted in the apps: {len(deleted['deleted_before'])} Bambu Studio, "
               f"{len(deleted['orca_deleted_before'])} Orca Slicer")
    if not ctx.apply:
        return
    make_state_dir(prof)
    for name, obj in (("owner-edits.json", oe), ("deleted.json", deleted)):
        path = prof / name
        data = (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        if path.exists() and path.read_bytes() == data:
            continue
        ctx.backup(path)
        _write_atomic(path, data, 0o644, state_owned=True)
    ctx.mark(b, S)


# ---------- 4. web secrets ----------

def _install_secret(ctx: _Ctx, step: str, src: Path, dest: Path, mode: int, group: str | None, what: str,
                    state: bool = False) -> None:
    data = src.read_bytes()
    if dest.exists():
        ctx.say(step, f"{what}: unchanged" if dest.read_bytes() == data else
                f"{what}: kept yours ({dest} differs from the bundle's, the kit's copy is newer); not replaced")
        return
    ctx.say(step, ctx.verb(f"install {what} as {dest}", f"{what} installed as {dest}"))
    if not ctx.apply:
        return
    if state:
        make_state_dir(dest.parent)
        _write_atomic(dest, data, mode, state_owned=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(dest, data, mode)
        _chown(dest, "root", group or "root")


def step_web(b: Bundle, ctx: _Ctx) -> None:
    S = "web"
    if not b.manifest.get("secrets"):
        ctx.say(S, "skipped: the bundle has no secrets (exported with --no-secrets); set the passphrase with "
                   "`filament-kit web passphrase`, then reconnect Claude's connector")
        return
    oauth, phrase, key = b.secret("oauth.json"), b.secret("web_passphrase"), b.secret("anthropic_key")
    if oauth is not None:
        try:
            d = json.loads(oauth.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                raise ValueError
        except (OSError, UnicodeDecodeError, ValueError):
            ctx.fail(S, "the bundle's oauth.json is not a JSON object; not installed")
        else:
            _install_secret(ctx, S, oauth, config.paths().state / "web" / "oauth.json", 0o600, None,
                            f"oauth.json ({len(d.get('clients') or {})} connector registrations)", state=True)
    if phrase is not None:
        if not _HASH.fullmatch(phrase.read_text(encoding="utf-8").strip()):
            ctx.fail(S, "the bundle's passphrase file is not 'salt_hex digest_hex'; not installed")
        else:
            _install_secret(ctx, S, phrase, config.paths().etc / "web_passphrase", 0o640, "filament-kit",
                            "the sign-in passphrase hash")
    if key is not None:
        _install_secret(ctx, S, key, config.paths().etc / "anthropic_key", 0o640, "filament-kit",
                        "the Anthropic API key")
    ctx.mark(b, S)


# ---------- 5. config ----------

def owner_config(b: Bundle) -> dict[str, object]:
    """Dotted config key -> the owner's value."""
    server, regen = b.obj("server.json"), b.obj("regen_config.json")
    out: dict[str, object] = {}
    public = server.get("public_url")
    if isinstance(public, str) and public.startswith("https://"):
        out["web.public_url"] = public.rstrip("/")
        out["remote.hostname"] = urlparse(public).hostname
        out["remote.acme_window"] = OPS_ACME_WINDOW
    if isinstance(server.get("lan"), list) and server["lan"]:
        out["web.lan"] = list(server["lan"])
    if isinstance(server.get("port"), int):
        out["web.port"] = server["port"]
    out.update({f"placement.{k}": v for k, v in OPS_PLACEMENT.items()})
    out["locations"] = list(OPS_LOCATIONS)
    out["intake.tare_hints"] = dict(OPS_TARE_HINTS)
    out["tag_sources"] = [{"name": "printer", "url": regen.get("lasttag") or OPS_LASTTAG}]
    out["station.url"] = (regen.get("station") or OPS_STATION).rstrip("/")
    out["slot_service"] = {"state_url": OPS_SLOT_STATE, "set_url": OPS_SLOT_SET,
                           "token_file": str(config.paths().etc / "h2d_token")}
    out["orders.file"] = str(config.paths().state / "filament_orders.json")
    out["slicer_printers"] = json.loads(json.dumps(OPS_SLICER_PRINTERS))
    out["presets_orca"] = True
    out["presets_orca_nozzles"] = list(OPS_ORCA_NOZZLES)
    return out


def _h2d_entry(ctx: _Ctx, step: str) -> None:
    """The kit makes Bambu Studio presets (and, with presets_orca, Orca ones) per printer model in its registry.
    The owner's H2D is never connected to by the kit (the slot service talks to it), so it gets a model-only entry:
    no address, no Access Code, not configured, which the bridge never connects to."""
    from .bridge import models as models_mod, registry
    try:
        have = registry.load() if ctx.apply else registry._read()   # _read: no lock file in a dry run
    except (OSError, ValueError, registry.RegistryError):
        have = {}
    if any(models_mod.printer_preset_name(p.model) == "Bambu Lab H2D" for p in have.values()):
        ctx.say(step, "printer registry: an H2D is listed; unchanged")
        return
    ctx.say(step, ctx.verb("list the H2D in the printer registry", "H2D listed in the printer registry")
            + f" (serial {OPS_H2D_SERIAL}, model only: no address or Access Code, never connected; it makes the "
              "kit build the H2D presets)")
    if ctx.apply:
        registry.upsert(registry.Printer(serial=OPS_H2D_SERIAL, name="H2D", model="O1D"))


def _get(d: dict, dotted: str):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def step_config(b: Bundle, ctx: _Ctx) -> None:
    S = "config"
    path = config.paths().etc / "config.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        ctx.fail(S, f"{path} is not readable JSON; fix it first")
        return
    current = config.load()
    changed, kept = [], []
    for key, val in owner_config(b).items():
        cur = _get(current, key)
        if cur == val:
            continue
        if cur is not None and cur != _get(config.DEFAULTS, key) and _get(raw, key) is not None:
            kept.append(f"{key} kept yours ({json.dumps(cur)}; ops: {json.dumps(val)})")
            continue
        parts = key.split(".")
        node = raw
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = val
        changed.append(key)
    for k in kept:
        ctx.say(S, k)
    ctx.say(S, (ctx.verb("set", "set") + f" {len(changed)} keys: {', '.join(changed)}") if changed
            else "config.json unchanged")
    if ctx.apply and changed:
        ctx.backup(path)
        config.save(raw)
    orders = config.paths().state / "filament_orders.json"
    src = b.root / "filament_orders.json"
    if src.is_file() and not orders.exists():
        ctx.say(S, ctx.verb(f"copy the order list to {orders}", f"order list copied to {orders}")
                + " (the root orders exporter keeps it fresh: see the runbook)")
        if ctx.apply:
            make_state_dir(orders.parent)
            _write_atomic(orders, src.read_bytes(), 0o640)
            _chown(orders, "root", "filament-kit")
    _h2d_entry(ctx, S)
    token = config.paths().etc / "h2d_token"
    if not token.exists():
        ctx.say(S, f"note: copy the H2D slot token to {token} (runbook; root:filament-kit 640)")
    ctx.mark(b, S)


# ---------- entry ----------

def run(bundle, *, apply: bool = False, library=None, out: Callable[[str], None] = print,
        replace_spoolman: bool = False, sm=None) -> int:
    """Migrate (or, without `apply`, report what would be migrated); 0 when every step went through."""
    lib = library if library is not None else library_mod.load()
    sm = sm if sm is not None else Spoolman(config.load().get("spoolman_url") or "http://127.0.0.1:7912", timeout=10)
    ctx = _Ctx(apply, out, lib, replace_spoolman, sm)
    try:
        with open_bundle(bundle) as b:
            out(f"filament-ops bundle {b.id} ({'with' if b.manifest.get('secrets') else 'without'} secrets)")
            for name, fn in (("spoolman", step_spoolman), ("lines", step_lines), ("presets", step_presets),
                             ("web", step_web), ("config", step_config)):
                try:
                    if name == "lines" and apply and not _no_systemd():
                        _wait_spoolman(sm)       # just restarted with the new database
                    fn(b, ctx)
                except Exception as e:  # noqa: BLE001 - one failed step is reported; the others still run
                    ctx.fail(name, f"{e.__class__.__name__}: {e}")
    except (OSError, ValueError, tarfile.TarError) as e:
        ctx.fail("bundle", f"{e.__class__.__name__}: {e}")
    finally:
        if apply:
            ctx.restart_rest()
    if ctx._backups is not None:
        out(f"backups of the replaced files: {ctx._backups}")
    if not apply:
        out("Dry run: nothing was written. Run again with --apply (as root) to migrate.")
    else:
        out("Done." if not ctx.errors else f"{ctx.errors} step(s) failed; fix them and run --apply again "
                                           "(finished steps are not redone).")
    return 1 if ctx.errors else 0
