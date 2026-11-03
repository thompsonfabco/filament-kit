#!/usr/bin/env python3
"""The filament-kit release key: make it, put its public half in the code, sign SHA256SUMS.

  keygen --out PATH      make an ed25519 key pair; the private key goes to PATH (mode 0600, never overwritten),
                         only the public key is printed. Keep PATH off the repo; add its contents as the GitHub
                         Actions secret FK_RELEASE_KEY yourself (repo Settings > Secrets and variables > Actions).
  set-pubkey KEY         write the public key (base64) into server/filament_kit/release.py and get.sh
  sync-get               copy server/filament_kit/release.py into get.sh (after editing release.py)
  sign SUMS              write SUMS.sig with the key in FK_RELEASE_KEY (or --key-file); refuses when the key does not
                         match the public key in release.py, so a release that get.sh cannot verify is never made
  pubkey --key-file F    print the public key of a private key file

Needs the `cryptography` package (a dependency of filament-kit). The private key is never printed or logged.
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE_PY = Path("server/filament_kit/release.py")
GET_SH = Path("get.sh")
BEGIN = "cat > \"$tmp/fk_release.py\" <<'FK_RELEASE_PY'\n"
END = "\nFK_RELEASE_PY\n"
_PUBKEY_LINE = re.compile(r'^PUBKEY = "[A-Za-z0-9+/=]*"$', re.M)


class SignError(Exception):
    pass


def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError:
        raise SignError("needs the cryptography package: pip install cryptography") from None
    return serialization, ed25519


def _public_b64(priv) -> str:
    serialization, _ = _crypto()
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def _load_private(pem: bytes):
    serialization, ed25519 = _crypto()
    try:
        key = serialization.load_pem_private_key(pem, password=None)
    except (ValueError, TypeError):
        raise SignError("the release key is not an unencrypted PEM private key") from None
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise SignError("the release key is not an ed25519 key")
    return key


def _key_pem(key_file: str | None) -> bytes:
    if key_file:
        return Path(key_file).read_bytes()
    env = os.environ.get("FK_RELEASE_KEY", "")
    if not env.strip():
        raise SignError("no release key: set FK_RELEASE_KEY (the GitHub secret) or pass --key-file")
    return env.encode("ascii")


def keygen(out: Path) -> str:
    serialization, ed25519 = _crypto()
    priv = ed25519.Ed25519PrivateKey.generate()
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    try:
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SignError(f"{out} exists; not overwriting a key") from None
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    return _public_b64(priv)


def _release_text(root: Path) -> str:
    return (root / RELEASE_PY).read_text(encoding="utf-8")


def embedded(get_sh_text: str) -> str:
    """The release.py copy inside get.sh."""
    try:
        start = get_sh_text.index(BEGIN) + len(BEGIN)
        end = get_sh_text.index(END, start)
    except ValueError:
        raise SignError("get.sh has no FK_RELEASE_PY block") from None
    return get_sh_text[start:end + 1]


def sync_get(root: Path) -> None:
    src = _release_text(root)
    if "\nFK_RELEASE_PY\n" in "\n" + src:
        raise SignError("release.py must not contain a line FK_RELEASE_PY")
    path = root / GET_SH
    text = path.read_text(encoding="utf-8")
    old = embedded(text)
    start = text.index(BEGIN) + len(BEGIN)
    new = text[:start] + src + text[start + len(old):]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new)


def set_pubkey(root: Path, key_b64: str) -> None:
    try:
        raw = base64.b64decode(key_b64, validate=True)
    except ValueError:
        raw = b""
    if len(raw) != 32:
        raise SignError("the public key must be 32 bytes in base64 (what keygen printed)")
    path = root / RELEASE_PY
    text = path.read_text(encoding="utf-8")
    if len(_PUBKEY_LINE.findall(text)) != 1:
        raise SignError(f"{RELEASE_PY} has no single PUBKEY line")
    text = _PUBKEY_LINE.sub(f'PUBKEY = "{key_b64}"', text)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    sync_get(root)


def embedded_pubkey(root: Path) -> str:
    m = re.search(r'^PUBKEY = "([A-Za-z0-9+/=]*)"$', _release_text(root), re.M)
    return m[1] if m else ""


def sign(sums: Path, pem: bytes, expect_pub: str) -> Path:
    priv = _load_private(pem)
    if not expect_pub:
        raise SignError("release.py has no PUBKEY: run set-pubkey with the key's public half first")
    if _public_b64(priv) != expect_pub:
        raise SignError("FK_RELEASE_KEY does not match PUBKEY in release.py; get.sh could not verify this release")
    data = sums.read_bytes()
    sig = priv.sign(data)
    priv.public_key().verify(sig, data)
    out = sums.with_name(sums.name + ".sig")
    out.write_text(base64.b64encode(sig).decode("ascii") + "\n", encoding="ascii")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sign_release.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)  # tests work on a copy of the tree
    sub = ap.add_subparsers(dest="cmd", required=True)
    kg = sub.add_parser("keygen")
    kg.add_argument("--out", required=True, help="where to write the private key (outside the repo)")
    sp = sub.add_parser("set-pubkey")
    sp.add_argument("key")
    sub.add_parser("sync-get")
    sg = sub.add_parser("sign")
    sg.add_argument("sums")
    sg.add_argument("--key-file")
    pk = sub.add_parser("pubkey")
    pk.add_argument("--key-file", required=True)
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        if args.cmd == "keygen":
            out = Path(args.out).resolve()
            if out.is_relative_to(root.resolve()):
                raise SignError("write the private key outside the repository")
            pub = keygen(out)
            print(pub)
            print(f"private key written to {out} (keep it secret; add its contents as the GitHub secret "
                  "FK_RELEASE_KEY, then run: tools/sign_release.py set-pubkey <the key above>)", file=sys.stderr)
        elif args.cmd == "set-pubkey":
            set_pubkey(root, args.key)
            print("public key written to release.py and get.sh")
        elif args.cmd == "sync-get":
            sync_get(root)
            print("get.sh carries the current release.py")
        elif args.cmd == "sign":
            out = sign(Path(args.sums), _key_pem(args.key_file), embedded_pubkey(root))
            print(f"signed: {out}")
        else:
            print(_public_b64(_load_private(Path(args.key_file).read_bytes())))
    except SignError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
