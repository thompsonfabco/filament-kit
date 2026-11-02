"""Tree hash of a preset folder. Must match the server's builds.tree_hash byte for byte.

Contract: every file under root whose suffix casefolds to .json or .info, as a relative POSIX
path; paths sorted as strings; for each, h.update(path.encode("utf-8") + b"\\0" +
sha256(content).digest()); result h.hexdigest(). A missing root gives sha256(b"").hexdigest().
"""
import hashlib
from pathlib import Path

SUFFIXES = (".json", ".info")


def preset_files(root: Path) -> list[tuple[str, Path]]:
    """(relative POSIX path, file) for every .json/.info file under root, sorted by path."""
    root = Path(root)
    if not root.is_dir():
        return []
    out = [(p.relative_to(root).as_posix(), p) for p in root.rglob("*")
           if p.suffix.casefold() in SUFFIXES and p.is_file()]
    return sorted(out, key=lambda t: t[0])


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for rel, path in preset_files(root):
        h.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()
