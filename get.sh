#!/usr/bin/env bash
# filament-kit one-command install for Ubuntu 24.04 or newer, piped or downloaded first (both work the same):
#
#   curl -fsSL https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh | sudo bash
#
#   curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh
#   sudo bash get.sh
#
# Options go after `bash -s --` when piped (`... | sudo bash -s -- --mode server`), else after the file name
# (`sudo bash get.sh --mode server`):
#   --version X.Y.Z    install that release instead of the latest
#   --mode M, --modules a,b, --server NAME-OR-IP, --set KEY=VALUE (repeatable, with --modules)
#                      passed to install.sh (no questions asked when given); --set gives a chosen module a setting
#                      it needs, e.g. --set web.public_url=https://kit.example.net/filament for web
#   --token-file FILE  a GitHub token for a private repo (or set FK_GITHUB_TOKEN; with sudo use `sudo -E` or
#                      the file). The token is never printed and goes only to api.github.com and
#                      objects.githubusercontent.com over https.
#   --repo OWNER/NAME, --api URL   another repo, or a mirror of the GitHub API (testing: tools/e2e/run.sh
#                      serves a fake one; the release public key below is then set in a throwaway copy of this
#                      file with tools/sign_release.py set-pubkey, never in the published get.sh)
#
# What it does: finds the release through the GitHub API, downloads SHA256SUMS and SHA256SUMS.sig, checks the
# signature with the release public key carried below (ed25519, checked with the system python3), then
# downloads the tarball and checks its hash against the signed list. Anything that does not match: it stops and
# installs nothing. Then it unpacks into a temporary folder, keeps a copy of the verified release in
# /opt/filament-kit/releases/ (for `filament-kit update --rollback`), runs install.sh with the terminal (so its
# questions work through the pipe; without a terminal install.sh asks nothing) and removes the temporary folder.
# Piped, sudo (use_pty) starts bash as a background job of its terminal. Under sudo-rs, Ubuntu 25.10+'s default, the
# first command to touch the terminal (install.sh's questions, apt) stops for good; so before install.sh runs this
# script makes itself the terminal's foreground job (fk_take_tty), and gives the terminal back afterwards. Classic sudo
# (Ubuntu 24.04) handles that first touch itself and must be left to it: see fk_classic_sudo.
# On an existing install it first holds every printer's mapping lock, as the updater does: it stops when a printer
# is mapping slots or loading a spool.
#
# Everything runs inside fk_main, called on the last line, so a download cut short runs nothing.
set -euo pipefail

fk_die() { printf 'error: %s\n' "$*" >&2; exit 1; }
fk_usage() {
    echo "usage: curl -fsSL <get.sh url> | sudo bash -s -- [--version X.Y.Z] [--mode M] [--modules a,b]" >&2
    echo "       [--server NAME-OR-IP] [--set KEY=VALUE]... [--token-file FILE] [--repo OWNER/NAME] [--api URL]" >&2
    echo "   or: sudo bash get.sh [the same options]" >&2
    exit 2
}

# Make this script's process group the foreground job of the terminal on stdin (/dev/tty) when it is not, and
# print the group that had it (nothing when there was nothing to do). SIGTTOU is ignored for the switch: a
# background job may then take the terminal (tcsetpgrp(3)). Any failure leaves things as they are.
fk_take_tty() {
    python3 -I -c '
import os, signal
signal.signal(signal.SIGTTOU, signal.SIG_IGN)
try:
    fg, me = os.tcgetpgrp(0), os.getpgrp()
    if fg != me:
        os.tcsetpgrp(0, me)
        print(fg)
except OSError:
    pass
' 2>/dev/null || true
}

# Give the terminal back to process group $1 (what fk_take_tty printed).
fk_give_tty() {
    [ -n "$1" ] || return 0
    python3 -I -c '
import os, signal, sys
signal.signal(signal.SIGTTOU, signal.SIG_IGN)
try:
    os.tcsetpgrp(0, int(sys.argv[1]))
except (OSError, ValueError):
    pass
' "$1" 2>/dev/null || true
}

# True under classic sudo. Piped, it starts us as a background job on purpose: our first touch of the terminal stops
# us, it notices, makes the job the foreground one and starts passing keys on, and it reads no keys until then. Taking
# the terminal ourselves skips that, and no key ever arrives. sudo-rs has no such step (a stopped job stays stopped), so
# it needs fk_take_tty. Asked of the sudo that is running, an ancestor: `sudo` on root's PATH may be another one.
fk_classic_sudo() {
    local pid=$PPID exe
    while [ "${pid:-0}" -gt 1 ] 2>/dev/null; do
        exe=$(readlink "/proc/$pid/exe" 2>/dev/null) || exe=""
        case "${exe##*/}" in
            sudo | sudo.ws | sudo-ws | sudo-rs)
                case "$(LC_ALL=C LANGUAGE= "$exe" --version 2>/dev/null)" in "Sudo version"*) return 0 ;; esac
                return 1
                ;;
        esac
        pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    done
    return 1
}

# The person's own terminal when sudo runs us on a pseudo-terminal of its own (use_pty): the terminal of the first
# ancestor on another terminal than ours (sudo itself). Nothing when there is none.
fk_outer_tty() {
    local mine pid t
    mine=$(ps -o tty= -p $$ 2>/dev/null | tr -d ' ')
    pid=$PPID
    while [ "${pid:-0}" -gt 1 ] 2>/dev/null; do
        t=$(ps -o tty= -p "$pid" 2>/dev/null | tr -d ' ')
        if [ -n "$t" ] && [ "$t" != "?" ] && [ "$t" != "$mine" ]; then
            [ ! -c "/dev/$t" ] || echo "/dev/$t"
            return 0
        fi
        pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    done
}

# An existing install: refuse while a printer is mapping slots or loading a spool, as `filament-kit update` does
# (updates.printers_idle). Every printer's mapping.lock is held (exclusive, not waiting) until this script ends,
# so neither can start while install.sh stops and replaces the services. A fresh install has no printers yet.
fk_hold_printers() {
    local state=${FK_STATE:-/var/lib/filament-kit} lock fd name
    [ -d "$state/printers" ] || return 0
    command -v flock >/dev/null 2>&1 || return 0
    for lock in "$state"/printers/*/mapping.lock; do
        [ -e "$lock" ] || continue
        exec {fd}>>"$lock" || fk_die "cannot open $lock; nothing was installed"
        if ! flock -n -x "$fd"; then
            name=${lock%/mapping.lock}
            fk_die "printer ${name##*/} is mapping slots or loading a spool; nothing was installed (try again once it is idle)"
        fi
    done
}

fk_main() {
    local version="" token_file="" repo="" api=""
    local -a pass=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --version | --mode | --modules | --server | --set | --token-file | --repo | --api)
                [ $# -ge 2 ] || fk_usage
                case "$1" in
                    --version) version="$2" ;;
                    --token-file) token_file="$2" ;;
                    --repo) repo="$2" ;;
                    --api) api="$2" ;;
                    *) pass+=("$1" "$2") ;;
                esac
                shift 2
                ;;
            -h | --help) fk_usage ;;
            *) fk_usage ;;
        esac
    done

    [ "$(id -u)" -eq 0 ] || fk_die "run as root: curl -fsSL <get.sh url> | sudo bash"
    [ -r /etc/os-release ] || fk_die "cannot read /etc/os-release"
    local ID="" VERSION_ID="" PRETTY_NAME=""
    # shellcheck disable=SC1091
    . /etc/os-release
    local major=${VERSION_ID%%.*}
    if [ "${ID:-}" != ubuntu ] || ! [ "$major" -ge 24 ] 2>/dev/null; then
        fk_die "Ubuntu 24.04 or newer is required (found ${PRETTY_NAME:-unknown})"
    fi
    command -v python3 >/dev/null 2>&1 || fk_die "python3 is missing: sudo apt-get install python3"
    if [ -n "$token_file" ] && [ ! -r "$token_file" ]; then
        fk_die "cannot read the token file $token_file"
    fi

    local tmp
    tmp=$(mktemp -d /tmp/filament-kit-get.XXXXXX)
    # shellcheck disable=SC2064  # expand $tmp now
    trap "rm -rf '$tmp'" EXIT
    chmod 700 "$tmp"

    cat > "$tmp/fk_release.py" <<'FK_RELEASE_PY'
"""Signed releases: find, download, verify and unpack a filament-kit release (spec R sections 2.2 and 2.5).

Standard library only, no package imports: get.sh carries this file verbatim (between its FK_RELEASE_PY lines,
kept in step by `tools/sign_release.py sync-get`) and runs it with the system python3 before anything is
installed; the updater (`filament_kit.updates`) imports it.

A release holds the tarball `filament-kit-<version>.tar.gz`, `SHA256SUMS` (sha256sum lines for every asset) and
`SHA256SUMS.sig` (base64 of the ed25519 signature of SHA256SUMS, made by release CI with the secret
FK_RELEASE_KEY). The signature is checked with PUBKEY below before the tarball is downloaded, then the tarball's
hash against the signed list; anything that does not match is deleted and nothing is unpacked.

A GitHub token (private repos; `--token-file` or FK_GITHUB_TOKEN) is sent only over https to TOKEN_HOSTS and
never on a redirect; it is never printed.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

REPO = "thompsonfabco/filament-kit"
API = "https://api.github.com"
# The release public key: ed25519, the raw 32 bytes in base64. Empty until the owner runs
# `tools/sign_release.py keygen` then `tools/sign_release.py set-pubkey <key>`; nothing verifies without it.
PUBKEY = "CUwA4XV86H/Orv8A1f7ghiTarDdsPdrpZjQsTvJpJCA="
TOKEN_HOSTS = frozenset({"api.github.com", "objects.githubusercontent.com"})
SUMS = "SHA256SUMS"
SIG = "SHA256SUMS.sig"
LIMIT_JSON = 4 << 20
LIMIT_SUMS = 64 << 10
LIMIT_SIG = 1 << 10
LIMIT_TARBALL = 1 << 30
# MAJOR.MINOR.PATCH as release.yml allows it (no pre-release tags)
VERSION_RE = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]?)\.(0|[1-9][0-9]?)")
_SUM_LINE = re.compile(r"([0-9a-f]{64}) [ *]([A-Za-z0-9][A-Za-z0-9._+-]*)")
_CHUNK = 1 << 16


class ReleaseError(Exception):
    """A release could not be found, fetched or verified; the message says which and what to do."""


# ---------------------------------------------------------------- ed25519 verification (RFC 8032, section 5.1.7)
# Verification only: every input is public, so plain integer arithmetic is fine (no constant-time concerns).

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    aa = (y1 - x1) * (y2 - x2) % _P
    bb = (y1 + x1) * (y2 + x2) % _P
    cc = 2 * t1 * t2 * _D % _P
    dd = 2 * z1 * z2 % _P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, pt):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _equal(a, b) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _recover_x(y: int, sign: int):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    if x & 1 != sign:
        x = _P - x
    return x


def _decompress(s: bytes):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


_GY = 4 * pow(5, _P - 2, _P) % _P
_G = (_recover_x(_GY, 0), _GY, 1, _recover_x(_GY, 0) * _GY % _P)


def ed25519_verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """True when `signature` is a valid ed25519 signature of `message` by `public` (RFC 8032, strict on S)."""
    if len(public) != 32 or len(signature) != 64:
        return False
    a = _decompress(public)
    r = _decompress(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % _L
    return _equal(_mul(s, _G), _add(r, _mul(h, a)))


# ---------------------------------------------------------------- versions, sums, signature

def parse_version(text: str) -> tuple[int, int, int]:
    m = VERSION_RE.fullmatch(str(text))
    if not m:
        raise ReleaseError(f"{text!r} is not a release version (MAJOR.MINOR.PATCH)")
    return (int(m[1]), int(m[2]), int(m[3]))


def tarball_name(version: str) -> str:
    parse_version(version)
    return f"filament-kit-{version}.tar.gz"


def parse_sums(data: bytes) -> dict[str, str]:
    """sha256sum output -> {file name: hex}; any other line, or a name listed twice, is an error."""
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise ReleaseError(f"{SUMS} is not plain text") from None
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            continue
        m = _SUM_LINE.fullmatch(line)
        if not m or m[2] in out:
            raise ReleaseError(f"{SUMS} has a bad line: {line[:80]!r}")
        out[m[2]] = m[1]
    if not out:
        raise ReleaseError(f"{SUMS} is empty")
    return out


_IDENTITY = (0, 1, 1, 0)


def small_order(point) -> bool:
    """[8]A is the identity: A is a small-order point (or the identity); such a key verifies forged signatures."""
    return _equal(_mul(8, point), _IDENTITY)


def check_public_key(raw: bytes) -> None:
    """Raise ReleaseError unless `raw` is 32 bytes encoding a curve point that is not of small order."""
    a = _decompress(raw) if len(raw) == 32 else None
    if a is None:
        raise ReleaseError("the release public key is not an ed25519 key")
    if small_order(a):
        raise ReleaseError("the release public key is a small-order point, not a real key")


def public_key(pubkey_b64: str | None = None) -> bytes:
    text = PUBKEY if pubkey_b64 is None else pubkey_b64
    if not text:
        raise ReleaseError("this copy has no release public key, so it cannot check a release "
                           "(the release key is set with tools/sign_release.py set-pubkey)")
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raw = b""
    if len(raw) != 32:
        raise ReleaseError("the release public key is not a base64 ed25519 key")
    check_public_key(raw)
    return raw


def verify_sums(sums: bytes, sig_text: bytes, pubkey_b64: str | None = None) -> dict[str, str]:
    """Check SHA256SUMS.sig over SHA256SUMS, then parse it. Raises ReleaseError on any mismatch."""
    key = public_key(pubkey_b64)
    try:
        sig = base64.b64decode(sig_text.strip(), validate=True)
    except (binascii.Error, ValueError):
        sig = b""
    if len(sig) != 64 or not ed25519_verify(key, sums, sig):
        raise ReleaseError(f"the signature {SIG} does not match {SUMS}: this release was not signed with the "
                           "filament-kit release key (or was changed); nothing was installed")
    return parse_sums(sums)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def check_hash(path: Path, table: dict[str, str]) -> None:
    want = table.get(path.name)
    if want is None:
        raise ReleaseError(f"{path.name} is not listed in {SUMS}")
    if not hmac.compare_digest(file_sha256(path), want):
        raise ReleaseError(f"{path.name} does not match its hash in the signed {SUMS} "
                           "(a damaged or changed download); nothing was installed")


def verify_dir(folder: Path, version: str, pubkey_b64: str | None = None) -> Path:
    """Re-check a kept release (folder with the tarball, SHA256SUMS and the signature); returns the tarball."""
    folder = Path(folder)
    tarball = folder / tarball_name(version)
    for f in (folder / SUMS, folder / SIG, tarball):
        if not f.is_file():
            raise ReleaseError(f"{f} is missing")
    table = verify_sums((folder / SUMS).read_bytes(), (folder / SIG).read_bytes(), pubkey_b64)
    check_hash(tarball, table)
    return tarball


# ---------------------------------------------------------------- download

def _host_ok_for_token(url: str) -> bool:
    u = urllib.parse.urlsplit(url)
    return u.scheme == "https" and (u.hostname or "").lower() in TOKEN_HOSTS and u.port in (None, 443)


class _Redirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to https, or within the same origin (a local test server). The token is an
    unredirected header, so it never follows."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        o, t = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        same = (o.scheme, o.hostname, o.port) == (t.scheme, t.hostname, t.port)
        if t.scheme != "https" and not same:
            raise ReleaseError(f"refused a redirect to {t.scheme}://{t.hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    od = urllib.request.OpenerDirector()
    for h in (urllib.request.ProxyHandler(), urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(),
              _Redirect(), urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor()):
        od.add_handler(h)
    return od


class Fetcher:
    """GitHub releases API client. `api` is the API base URL (another one only for a mirror or a test server)."""

    def __init__(self, api: str = API, token: str | None = None, opener=None, timeout: float = 60):
        u = urllib.parse.urlsplit(api)
        if u.scheme not in ("https", "http") or not u.hostname:
            raise ReleaseError(f"bad API address {api!r}")
        self.api = api.rstrip("/")
        self._token = token or None
        self._opener = opener or _opener()
        self.timeout = timeout

    def request(self, url: str, accept: str) -> urllib.request.Request:
        req = urllib.request.Request(url, headers={"User-Agent": "filament-kit-get", "Accept": accept})
        if self._token and _host_ok_for_token(url):
            req.add_unredirected_header("Authorization", f"Bearer {self._token}")
        return req

    def _open(self, url: str, accept: str):
        try:
            return self._opener.open(self.request(url, accept), timeout=self.timeout)
        except urllib.error.HTTPError as e:
            host = urllib.parse.urlsplit(url).hostname
            if e.code == 404:
                hint = "no such release" + ("" if self._token else
                                            " (a private repo needs a token: --token-file or FK_GITHUB_TOKEN)")
            elif e.code in (401, 403):
                hint = "access refused (a bad token, or the GitHub rate limit: try again in an hour)"
            else:
                hint = "try again later"
            raise ReleaseError(f"{host} answered HTTP {e.code}: {hint}") from None
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise ReleaseError(f"cannot reach {urllib.parse.urlsplit(url).hostname}: {reason}") from None

    def get(self, url: str, limit: int, accept: str = "application/octet-stream") -> bytes:
        with self._open(url, accept) as resp:
            data = resp.read(limit + 1)
        if len(data) > limit:
            raise ReleaseError(f"{url.rsplit('/', 1)[-1]} is larger than {limit} bytes")
        return data

    def save(self, url: str, dest: Path, limit: int) -> None:
        n = 0
        with self._open(url, "application/octet-stream") as resp, open(dest, "wb") as out:
            for chunk in iter(lambda: resp.read(_CHUNK), b""):
                n += len(chunk)
                if n > limit:
                    raise ReleaseError(f"{dest.name} is larger than {limit} bytes")
                out.write(chunk)

    def release(self, repo: str = REPO, version: str | None = None) -> dict:
        """{"version", "assets": {name: download url}} of the latest release, or of tag v<version>."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ReleaseError(f"bad repo name {repo!r} (owner/name)")
        if version is not None:
            parse_version(version)
        path = "latest" if version is None else f"tags/v{version}"
        raw = self.get(f"{self.api}/repos/{repo}/releases/{path}", LIMIT_JSON, "application/vnd.github+json")
        try:
            doc = json.loads(raw)
            tag = doc["tag_name"]
            assets = {a["name"]: a["url"] for a in doc["assets"]}
        except (ValueError, KeyError, TypeError):
            raise ReleaseError("the release list answer is not a GitHub release") from None
        if not isinstance(tag, str) or not tag.startswith("v"):
            raise ReleaseError(f"release tag {tag!r} is not v<version>")
        found = tag[1:]
        parse_version(found)
        if version is not None and found != version:
            raise ReleaseError(f"asked for {version}, the server answered {found}")
        for name, url in assets.items():
            if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme not in ("https", "http"):
                raise ReleaseError(f"asset {name!r} has a bad address")
        return {"version": found, "assets": assets}


def fetch(dest: Path, *, repo: str = REPO, version: str | None = None, fetcher: Fetcher,
          pubkey_b64: str | None = None) -> tuple[str, Path]:
    """Download and verify a release into `dest` (SHA256SUMS, its signature and the tarball).
    Returns (version, tarball). The signature is checked before the tarball is downloaded; on any failure the
    downloaded files are deleted."""
    public_key(pubkey_b64)              # no key: stop before any download
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    rel = fetcher.release(repo, version)
    ver = rel["version"]
    name = tarball_name(ver)
    for need in (SUMS, SIG, name):
        if need not in rel["assets"]:
            raise ReleaseError(f"release {ver} has no {need}")
    sums = fetcher.get(rel["assets"][SUMS], LIMIT_SUMS)
    sig = fetcher.get(rel["assets"][SIG], LIMIT_SIG)
    table = verify_sums(sums, sig, pubkey_b64)
    if name not in table:
        raise ReleaseError(f"the signed {SUMS} does not list {name}")
    tarball = dest / name
    try:
        fetcher.save(rel["assets"][name], tarball, LIMIT_TARBALL)
        check_hash(tarball, table)
    except BaseException:
        tarball.unlink(missing_ok=True)
        raise
    (dest / SUMS).write_bytes(sums)
    (dest / SIG).write_bytes(sig)
    return ver, tarball


# ---------------------------------------------------------------- unpack

def _member_ok(m: tarfile.TarInfo, top: str) -> bool:
    p = PurePosixPath(m.name)
    if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != top:
        return False
    if m.issym() or m.islnk():
        return False                    # the release tarball has no links
    return m.isfile() or m.isdir()


def extract(tarball: Path, version: str, dest: Path) -> Path:
    """Unpack a verified tarball into `dest`; returns the folder holding install.sh. Only plain files and
    folders under filament-kit-<version>/ are accepted."""
    top = f"filament-kit-{version}"
    dest = Path(dest)
    with tarfile.open(tarball, "r:gz") as tf:
        members = tf.getmembers()
        bad = [m.name for m in members if not _member_ok(m, top)]
        if bad:
            raise ReleaseError(f"the tarball holds an unexpected entry {bad[0]!r}; nothing was installed")
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, members=members, filter="data")
        else:                           # Python before 3.12 (and its backports): the checks above suffice
            tf.extractall(dest, members=members)
    root = dest / top
    if not (root / "install.sh").is_file():
        raise ReleaseError(f"the tarball has no {top}/install.sh")
    return root


# ---------------------------------------------------------------- command line (get.sh)

def read_token(token_file: str | None) -> str | None:
    """FK_GITHUB_TOKEN, else the first line of `token_file`. Never printed."""
    if token_file:
        try:
            with open(token_file, encoding="utf-8") as fh:
                tok = fh.readline().strip()
        except OSError as e:
            raise ReleaseError(f"cannot read the token file {token_file}: {e.strerror}") from None
        if not tok:
            raise ReleaseError(f"the token file {token_file} is empty")
        return tok
    return os.environ.get("FK_GITHUB_TOKEN", "").strip() or None


def keep(version: str, src: Path, store: Path) -> Path:
    """Copy a verified release (tarball, SHA256SUMS, signature) to store/<version>/ for a later rollback."""
    out = Path(store) / version
    tmp = Path(store) / f".{version}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, mode=0o755)
    for name in (tarball_name(version), SUMS, SIG):
        shutil.copyfile(Path(src) / name, tmp / name)
    shutil.rmtree(out, ignore_errors=True)
    os.replace(tmp, out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fk_release")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download, verify and unpack a release; prints the folder with install.sh")
    f.add_argument("--dest", required=True)
    f.add_argument("--version")
    f.add_argument("--repo", default=REPO)
    f.add_argument("--api", default=API)
    f.add_argument("--token-file")
    f.add_argument("--keep", help="also copy the verified release to KEEP/<version>/")
    args = ap.parse_args(argv)
    try:
        fetcher = Fetcher(args.api, read_token(args.token_file))
        dest = Path(args.dest)
        ver, tarball = fetch(dest / "download", repo=args.repo, version=args.version, fetcher=fetcher)
        root = extract(tarball, ver, dest / "unpacked")
        if args.keep:
            try:
                keep(ver, tarball.parent, Path(args.keep))
            except OSError as e:
                print(f"warning: could not keep a copy for rollback in {args.keep}: {e}", file=sys.stderr)
    except ReleaseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"verified filament-kit {ver}", file=sys.stderr)
    print(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
FK_RELEASE_PY

    local -a args=(fetch --dest "$tmp" --keep /opt/filament-kit/releases)
    [ -z "$version" ] || args+=(--version "$version")
    [ -z "$token_file" ] || args+=(--token-file "$token_file")
    [ -z "$repo" ] || args+=(--repo "$repo")
    [ -z "$api" ] || args+=(--api "$api")
    local root
    # stdin from /dev/null: with `curl | bash` the rest of this script is still on stdin
    root=$(python3 -I "$tmp/fk_release.py" "${args[@]}" </dev/null) \
        || fk_die "nothing was installed"
    [ -f "$root/install.sh" ] || fk_die "nothing was installed (no install.sh)"
    fk_hold_printers

    local rc=0 owner="" outer="" saved=""
    if (exec </dev/tty) 2>/dev/null; then
        fk_classic_sudo || owner=$(fk_take_tty </dev/tty)
        if [ -n "$owner" ]; then
            # Piped, sudo-rs leaves the person's terminal as it was (echoing, line by line) and passes on whole
            # lines: a secret would show as typed and the module menu would get no key before Enter. Set it to
            # pass each key on, as sudo does when it runs at a terminal (this pty then echoes and edits), and put
            # it back afterwards, also when this script is stopped.
            outer=$(fk_outer_tty) || outer=""
            if [ -z "$outer" ] || ! saved=$(stty -g -F "$outer" 2>/dev/null); then
                saved=""
                echo "note: could not find your terminal; what you type may show. Safer: sudo bash get.sh" >&2
            else
                # shellcheck disable=SC2064  # expand now
                trap "rm -rf '$tmp'; stty -F '$outer' '$saved' 2>/dev/null || true" EXIT
                stty -F "$outer" -echo -icanon -isig -iexten -ixon -icrnl min 1 time 0 2>/dev/null || true
            fi
        fi
        bash "$root/install.sh" "${pass[@]}" </dev/tty || rc=$?
        [ -z "$saved" ] || stty -F "$outer" "$saved" 2>/dev/null || true
        fk_give_tty "$owner" </dev/tty
    else
        echo "no terminal: installing without questions" >&2
        bash "$root/install.sh" "${pass[@]}" </dev/null || rc=$?
    fi
    return "$rc"
}

fk_main "$@"
