#!/usr/bin/env bash
# Export a filament-ops VM's data as one bundle for `filament-kit migrate-ops` (docs/migrate-from-filament-ops.md).
#
# Read-only: nothing on this machine is written, stopped or restarted. The Spoolman database is copied with
# sqlite's online backup API into memory (never `cp` of a live database), and the bundle is streamed straight
# into the output: give `-` to write it to stdout, so even the bundle never lands on this machine's disk:
#
#   ssh spoolman-vm 'sudo bash -s -- --no-secrets -' < tools/export_ops.sh > ops-bundle.tar.gz
#
# Usage: sudo bash export_ops.sh [--no-secrets] [--spoolman-db PATH] OUT.tar.gz|-
#   --no-secrets   leave out the web passphrase hash, oauth.json and the Anthropic key (a rehearsal bundle);
#                  the full bundle (with them) is for the owner's real cut-over only, root-only (600) on disk
#   --spoolman-db  the Spoolman database (default: SPOOLMAN_DIR_DATA of Spoolman.service, else the service
#                  user's ~/.local/share/spoolman/spoolman.db)
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

PROG=$(cat <<'PY'
import io, json, os, socket, sqlite3, subprocess, sys, tarfile, time, urllib.request

args = sys.argv[1:]
secrets, db_arg, out = True, None, None
while args:
    a = args.pop(0)
    if a == "--no-secrets":
        secrets = False
    elif a == "--spoolman-db":
        db_arg = args.pop(0) if args else sys.exit("error: --spoolman-db needs a path")
    elif out is None and (a == "-" or not a.startswith("-")):
        out = a
    else:
        sys.exit(f"error: unknown argument {a!r}")
if out is None:
    sys.exit("usage: export_ops.sh [--no-secrets] [--spoolman-db PATH] OUT.tar.gz|-")

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
    if db_arg:
        return db_arg
    for unit in ("Spoolman.service", "spoolman.service"):
        try:
            show = subprocess.run(["systemctl", "show", "-p", "User", "-p", "Environment", unit],
                                  capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        props = dict(l.split("=", 1) for l in show.splitlines() if "=" in l)
        for kv in props.get("Environment", "").split():
            if kv.startswith("SPOOLMAN_DIR_DATA="):
                return os.path.join(kv.split("=", 1)[1], "spoolman.db")
        user = props.get("User")
        if user:
            import pwd
            try:
                home = pwd.getpwnam(user).pw_dir
            except KeyError:
                continue
            cand = os.path.join(home, ".local", "share", "spoolman", "spoolman.db")
            if os.path.isfile(cand):
                return cand
    sys.exit("error: Spoolman database not found; pass --spoolman-db PATH")


def db_copy(path):
    """Online backup into memory (consistent while Spoolman writes), then serialized: no file is written."""
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    dst = sqlite3.connect(":memory:")
    try:
        src.backup(dst)
        counts = {t: dst.execute(f"select count(*) from {t}").fetchone()[0] for t in ("spool", "filament", "vendor")}
        return dst.serialize(), counts
    finally:
        src.close()
        dst.close()


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

db_path = spoolman_db()
db_bytes, counts = db_copy(db_path)
manifest = {"format": 1, "created": int(time.time()), "host": socket.gethostname(), "secrets": secrets,
            "sources": {**files, **trees, "spoolman.db": db_path}, "spoolman": {"version": spoolman_version(),
            **counts}, "orders_file": orders, "missing": [], "presets": {}}

if out == "-":
    fh = sys.stdout.buffer
else:
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # it may hold secrets: root only
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
