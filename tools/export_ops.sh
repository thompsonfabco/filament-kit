#!/usr/bin/env bash
# Export a filament-ops VM's data as one bundle for `filament-kit migrate-ops` (docs/migrate-from-filament-ops.md).
#
# Read-only: nothing on this machine is written, stopped or restarted. The Spoolman database is copied with
# sqlite's online backup API into memory (never `cp` of a live database), and the bundle is streamed straight
# into the output: give `-` to write it to stdout, so even the bundle never lands on this machine's disk:
#
#   (umask 077; ssh <ops-vm> 'sudo bash -s -- --no-secrets -' < tools/export_ops.sh > ops-bundle.tar.gz)
#
# The umask matters for a full bundle (without --no-secrets): the shell creates the output file, at its umask
# (usually 0644), and the bundle holds the passphrase hash, oauth.json and the Anthropic key. Run here, with `-`
# redirected into a group/world-readable file, the script refuses (OPS_EXPORT_ALLOW_READABLE=1 switches that off).
#
# Usage: sudo bash export_ops.sh [--no-secrets] [--spoolman-db PATH [--force]] OUT.tar.gz|-
#   --no-secrets   leave out the web passphrase hash, oauth.json and the Anthropic key (a rehearsal bundle);
#                  the full bundle (with them) is for the owner's real cut-over only, root-only (600) on disk
#   --spoolman-db  the Spoolman database (default: SPOOLMAN_DIR_DATA of Spoolman.service, else the service
#                  user's ~/.local/share/spoolman/spoolman.db)
#   --force        with --spoolman-db: export a WAL database (one with a -wal file) anyway. There is no unit
#                  to check then, so give it only when the Spoolman using that database is stopped
# The H2D slot service token is never exported: the runbook copies it on the VM itself.
#
# Bundle (tar.gz, everything under ops-bundle/): MANIFEST.json, lines.py, regen_config.json, server.json,
# instructions.txt, filament_orders.json, spoolman.db, presets/installed/**, presets/live/** and, without
# --no-secrets, secrets/{web_passphrase,oauth.json,anthropic_key}.
# Paths can be moved with OPS_ETC, OPS_STATE, OPS_OPT and OPS_DATA (tests).
set -euo pipefail

if [ "$(id -u)" != 0 ] && [ "${OPS_EXPORT_NOT_ROOT:-0}" != 1 ]; then
    echo "error: run as root (sudo): the ops state and secrets are root/filament-mcp only" >&2
    exit 1
fi
command -v python3 >/dev/null || { echo "error: python3 is needed" >&2; exit 1; }
# Connection.serialize() (the in-memory database copy) is new in Python 3.11
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'     || { echo "error: Python 3.11 or newer is needed (python3 here is $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])'))" >&2; exit 1; }

PROG=$(cat <<'PY'
import io, json, os, shutil, socket, sqlite3, stat, subprocess, sys, tarfile, tempfile, time, urllib.request

args = sys.argv[1:]
secrets, db_arg, out, force = True, None, None, False
while args:
    a = args.pop(0)
    if a == "--no-secrets":
        secrets = False
    elif a == "--force":
        force = True
    elif a == "--spoolman-db":
        db_arg = args.pop(0) if args else sys.exit("error: --spoolman-db needs a path")
    elif out is None and (a == "-" or not a.startswith("-")):
        out = a
    else:
        sys.exit(f"error: unknown argument {a!r}")
if out is None:
    sys.exit("usage: export_ops.sh [--no-secrets] [--spoolman-db PATH [--force]] OUT.tar.gz|-")

if out == "-" and secrets and os.environ.get("OPS_EXPORT_ALLOW_READABLE") != "1":
    st = os.fstat(sys.stdout.fileno())
    if stat.S_ISREG(st.st_mode) and st.st_mode & 0o077:
        sys.exit(f"error: stdout is a file readable by group/others (mode {st.st_mode & 0o777:03o}) and the bundle holds secrets: "
                 "run it under `umask 077`, give --no-secrets, or set OPS_EXPORT_ALLOW_READABLE=1")

ETC = os.environ.get("OPS_ETC", "/etc/filament-mcp")
STATE = os.environ.get("OPS_STATE", "/var/lib/filament-mcp")
OPT = os.environ.get("OPS_OPT", "/opt/filament-mcp")
DATA = os.environ.get("OPS_DATA", "/srv/filament")


def log(msg):
    print(msg, file=sys.stderr)


def regen_config():
    try:
        with open(os.path.join(OPT, "regen_config.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def spoolman_db():
    """(database path, the systemd unit that runs it or None)."""
    if db_arg:
        return db_arg, None
    for unit in ("Spoolman.service", "spoolman.service"):
        try:
            show = subprocess.run(["systemctl", "show", "-p", "User", "-p", "Environment", unit],
                                  capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        props = dict(l.split("=", 1) for l in show.splitlines() if "=" in l)
        for kv in props.get("Environment", "").split():
            if kv.startswith("SPOOLMAN_DIR_DATA="):
                return os.path.join(kv.split("=", 1)[1], "spoolman.db"), unit
        user = props.get("User")
        if user:
            import pwd
            try:
                home = pwd.getpwnam(user).pw_dir
            except KeyError:
                continue
            cand = os.path.join(home, ".local", "share", "spoolman", "spoolman.db")
            if os.path.isfile(cand):
                return cand, unit
    sys.exit("error: Spoolman database not found; pass --spoolman-db PATH")


def _backup_to_memory(uri):
    src = sqlite3.connect(uri, uri=True)
    dst = sqlite3.connect(":memory:")
    try:
        src.backup(dst)
        counts = {t: dst.execute(f"select count(*) from {t}").fetchone()[0] for t in ("spool", "filament", "vendor")}
        try:
            rev = dst.execute("select version_num from alembic_version").fetchone()
        except sqlite3.Error:
            rev = None
        return dst.serialize(), counts, rev[0] if rev else None
    finally:
        src.close()
        dst.close()


def db_copy(path, unit):
    """(database bytes, counts, alembic revision): sqlite's online backup into memory, then serialized.
    A rollback-journal database is read in place (consistent even while Spoolman writes). A WAL database with
    a -wal file (Spoolman stopped without a checkpoint, e.g. killed) is read from a private copy of the db and
    its -wal in a temp dir, so the frames in the -wal are included and sqlite never touches the live files (a
    read-only open still rewrites -shm). That copy is only consistent with Spoolman stopped: refused otherwise."""
    wal = path + "-wal"
    if not (os.path.isfile(wal) and os.path.getsize(wal) > 0):
        return _backup_to_memory(f"file:{path}?mode=ro")
    if unit and subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0:
        sys.exit(f"error: {path} has a -wal file and {unit} is running: stop it first "
                 f"(sudo systemctl stop {unit}), then export")
    if not unit and not force:          # --spoolman-db: no unit known, so nothing says Spoolman is stopped
        sys.exit(f"error: {path} has a -wal file and no Spoolman unit was checked (--spoolman-db): stop the "
                 f"Spoolman that uses it, then export again with --force")
    tmp = tempfile.mkdtemp(prefix="ops-export-", dir="/dev/shm" if os.path.isdir("/dev/shm") else None)
    try:
        for suffix in ("", "-wal"):
            shutil.copyfile(path + suffix, os.path.join(tmp, "spoolman.db" + suffix))
        return _backup_to_memory(f"file:{os.path.join(tmp, 'spoolman.db')}?mode=ro")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def spoolman_version():
    try:
        with urllib.request.urlopen("http://127.0.0.1:7912/api/v1/info", timeout=5) as r:
            return json.loads(r.read()).get("version")
    except Exception:
        return None


rc = regen_config()
presets_state = rc.get("state") or os.path.join(STATE, "presets")
data = rc.get("data") or DATA
orders = os.environ.get("FILAMENT_ORDERS") or os.path.join(STATE, "filament_orders.json")
files = {                                   # name in the bundle -> source path (optional unless noted)
    "lines.py": os.path.join(presets_state, "lines.py"),
    "regen_config.json": os.path.join(OPT, "regen_config.json"),
    "server.json": os.path.join(ETC, "server.json"),
    "instructions.txt": os.path.join(OPT, "instructions.txt"),
    "filament_orders.json": orders,
}
if secrets:
    files.update({"secrets/web_passphrase": os.path.join(ETC, "passphrase"),
                  "secrets/oauth.json": os.path.join(STATE, "oauth.json"),
                  "secrets/anthropic_key": os.path.join(ETC, "anthropic_key")})
trees = {"presets/installed": os.path.join(data, "installed"), "presets/live": os.path.join(data, "live")}

db_path, db_unit = spoolman_db()
db_bytes, counts, revision = db_copy(db_path, db_unit)
manifest = {"format": 1, "created": int(time.time()), "host": socket.gethostname(), "secrets": secrets,
            "sources": {**files, **trees, "spoolman.db": db_path}, "spoolman": {"version": spoolman_version(),
            "revision": revision, **counts}, "orders_file": orders, "missing": [], "presets": {}}

if out == "-":
    fh = sys.stdout.buffer
else:
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # it may hold secrets: root only
    os.fchmod(fd, 0o600)                    # O_CREAT's mode does not apply to a file that already existed
    fh = os.fdopen(fd, "wb")
P = "ops-bundle/"


def add_bytes(tar, name, blob):
    ti = tarfile.TarInfo(P + name)
    ti.size, ti.mtime, ti.mode = len(blob), int(time.time()), 0o600
    tar.addfile(ti, io.BytesIO(blob))


with tarfile.open(fileobj=fh, mode="w|gz") as tar:
    for name, src in files.items():
        if os.path.isfile(src):
            with open(src, "rb") as f:
                add_bytes(tar, name, f.read())
        else:
            manifest["missing"].append(name)
            log(f"missing (left out): {src}")
    for name, root in trees.items():
        n = 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for fn in sorted(filenames):
                if not fn.endswith((".json", ".info")):
                    continue
                src = os.path.join(dirpath, fn)
                with open(src, "rb") as f:
                    add_bytes(tar, name + "/" + os.path.relpath(src, root).replace(os.sep, "/"), f.read())
                n += 1
        manifest["presets"][name] = n
        if not n:
            manifest["missing"].append(name)
    add_bytes(tar, "spoolman.db", db_bytes)
    add_bytes(tar, "MANIFEST.json", json.dumps(manifest, indent=2).encode())
fh.flush()
if out != "-":
    fh.close()
missing = manifest["missing"]
log(f"bundle: {counts} from {db_path}; presets {manifest['presets']}; "
    f"secrets {'included' if secrets else 'left out'}" + (f"; missing {missing}" if missing else ""))
PY
)
exec python3 -I -c "$PROG" "$@"
