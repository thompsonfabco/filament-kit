"""The allow-lists (tests/allowlists/<list>/): one folder per list, one file per source file the list names, so two
branches that touch different source files never touch the same file. The loaders read a whole folder; the rules every
file keeps are checked by `problems` (tests/test_allowlist_files.py)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "tests" / "allowlists"
SCREENS = ("Add spools", "Spools", "Slicer presets")     # the web app's screens (aut5): the reason starts with one


def key_path(line):
    """The source file the line names, as a file name: '/' becomes '__'."""
    return line.split("|", 1)[0].strip().replace("/", "__")


def key_view(line):
    """The Hub section ('#features | ...' -> features)."""
    return line.split("|", 1)[0].strip().lstrip("#")


def key_screen(line):
    reason = line.split("|")[-1].strip()
    for s in SCREENS:
        if reason == s or reason.startswith(s + " "):
            return s.lower().replace(" ", "-")
    return "?"


KEYS = {"strings": key_path, "words": key_path, "field": key_path, "literal": key_path, "dialog": key_path,
        "press": key_path, "accent": key_path, "design_source": key_path, "aut5_hub": key_view, "aut5": key_screen}


def text(folder):
    """All the lines of one list, as the old single file read: the files in name order (a single file is read as is,
    for the tests that plant their own list)."""
    if folder.is_file():
        return folder.read_text(encoding="utf-8")
    return "".join(p.read_text(encoding="utf-8") for p in sorted(folder.glob("*.txt")))


def problems(folder, key):
    """What is wrong with one list's folder: an unsorted file, a duplicate line, a line whose source does not match the
    file's name, a CR, a file that is not a .txt or lacks the final newline, an empty file."""
    out = []
    for p in sorted(folder.iterdir()):
        if p.name == "README.md":
            continue
        if p.suffix != ".txt":
            out.append(f"{p.name}: only .txt files and README.md belong here")
            continue
        raw = p.read_bytes().decode("utf-8")
        if "\r" in raw:
            out.append(f"{p.name}: has a CR")
        lines = raw.split("\n")
        if lines.pop() != "" or not lines:
            out.append(f"{p.name}: empty, or the last line has no newline")
            continue
        if any(not l.strip() or re.match(r"#(\s|$)", l) for l in lines):
            out.append(f"{p.name}: a blank or comment line (the comments go in README.md)")
        if lines != sorted(lines):
            out.append(f"{p.name}: lines are not sorted")
        dup = sorted({l for l in lines if lines.count(l) > 1})
        out += [f"{p.name}: listed twice: {l}" for l in dup]
        out += [f"{p.name}: belongs in {key(l)}.txt: {l}" for l in lines if key(l) + ".txt" != p.name]
    return out
