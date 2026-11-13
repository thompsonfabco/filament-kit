"""QR codes drawn by the Hub (S2.8): each one stands for its link, with qrencode absent; segno is vendored unchanged."""
import hashlib
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from test_setup_page import app, client, env, helper, manager, post  # noqa: F401

from filament_kit import cli, config, modules, pairing, qr, setup_page
from filament_kit.qr import segno

consts = segno.consts

PKG = Path(cli.__file__).parent
VENDOR = PKG / "_vendor"
LINK = "fkit://pair?h=kit.local&ip=192.0.2.5&p=8710&t=" + "Ab3-_" * 12
START, END = "\x1b[30;47m", "\x1b[0m"


@pytest.fixture(autouse=True)
def no_qrencode(monkeypatch):
    """qrencode is absent: nothing is on PATH, and running it fails the test."""
    monkeypatch.setenv("PATH", "")
    real = subprocess.run

    def run(args, *a, **kw):
        assert args[0] != "qrencode", "the Hub must not run qrencode"
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", run)


# ---- reading a symbol back (ISO 18004): format info, unmask, undo the block interleave, byte-mode segment ----

_MASKS = (lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
          lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
          lambda r, c: (r * c) % 2 + (r * c) % 3 == 0, lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
          lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0)


def _function_modules(version):
    """The places that are not data: finders with separators and format info, timing lines, alignment patterns, version
    information (ISO 18004 section 6.3 and 7.9, drawn here from the standard's rules, not from the encoder)."""
    n = 17 + 4 * version
    taken = {(r, c) for r in range(9) for c in range(9)}                       # top left finder, format info
    taken |= {(r, c) for r in range(9) for c in range(n - 8, n)}               # top right
    taken |= {(r, c) for r in range(n - 8, n) for c in range(9)}               # bottom left, with the dark module
    taken |= {(6, i) for i in range(n)} | {(i, 6) for i in range(n)}           # timing
    if version >= 2:
        centres = (6,) + consts.ALIGNMENT_POS[version - 2][1:]
        for r in centres:
            for c in centres:
                if (r, c) in ((6, 6), (6, centres[-1]), (centres[-1], 6)):
                    continue                                                   # these fall on finders
                taken |= {(r + i, c + j) for i in range(-2, 3) for j in range(-2, 3)}
    if version >= 7:
        taken |= {(r, c) for r in range(6) for c in range(n - 11, n - 8)} | {(c, r) for r in range(6) for c in range(n - 11, n - 8)}
    return taken


def decode(m) -> str:
    """The text a QR symbol (rows of booleans, no quiet zone) carries."""
    n = len(m)
    version = (n - 17) // 4
    assert n == 17 + 4 * version
    # format information, bit 14 first: row 8 left to right (skipping the timing column), then column 8 upwards
    cells = [(8, c) for c in (0, 1, 2, 3, 4, 5, 7, 8)] + [(r, 8) for r in (7, 5, 4, 3, 2, 1, 0)]
    word = int("".join("1" if m[r][c] else "0" for r, c in cells), 2)
    assert word in consts.FORMAT_INFO, "no valid format information"
    level, mask = divmod(consts.FORMAT_INFO.index(word), 8)        # the table runs M, L, H, Q; eight masks each
    taken = _function_modules(version)
    bits, up, c = [], True, n - 1
    while c > 0:
        if c == 6:
            c -= 1
        for r in (range(n - 1, -1, -1) if up else range(n)):
            for cc in (c, c - 1):
                if (r, cc) not in taken:
                    bits.append(m[r][cc] ^ _MASKS[mask](r, cc))
        up, c = not up, c - 2
    words = [int("".join("1" if b else "0" for b in bits[i:i + 8]), 2) for i in range(0, len(bits) - 7, 8)]
    lens = [ec.num_data for ec in consts.ECC[version][level] for _ in range(ec.num_blocks)]
    per, i = [[] for _ in lens], 0
    for k in range(max(lens)):
        for b, ln in enumerate(lens):
            if k < ln:
                per[b].append(words[i])
                i += 1
    stream = "".join(f"{w:08b}" for blk in per for w in blk)
    assert stream[:4] == "0100", "not byte mode"
    width = 8 if version < 10 else 16
    count = int(stream[4:4 + width], 2)
    body = stream[4 + width:4 + width + 8 * count]
    return bytes(int(body[j:j + 8], 2) for j in range(0, len(body), 8)).decode("utf-8")


def from_svg(doc: str):
    root = ET.fromstring(doc)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    scale = int(re.search(r"scale\((\d+)\)", doc).group(1))
    size = int(root.get("width")) // scale
    d = re.search(r'class="qrline"[^>]* d="([^"]+)"', doc).group(1)
    grid, x, y = [[False] * size for _ in range(size)], 0.0, 0.0
    for cmd, a, b in re.findall(r"([Mmh])(-?[\d.]+)(?: (-?[\d.]+))?", d):
        if cmd == "M":
            x, y = float(a), float(b)
        elif cmd == "m":
            x, y = x + float(a), y + float(b)
        else:
            for k in range(int(float(a))):
                grid[int(y)][int(x) + k] = True
            x += float(a)
    return unquiet(grid)


def from_text(txt: str):
    rows = []
    for line in txt.splitlines():
        assert line.startswith(START) and line.endswith(END)
        cells = line[len(START):-len(END)]
        rows.append([ch in "▀█" for ch in cells])
        rows.append([ch in "▄█" for ch in cells])
    return unquiet(rows)


def unquiet(rows):
    q = qr.QUIET
    size = len(rows[0]) - 2 * q
    assert all(not v for row in rows[:q] for v in row), "quiet zone above"
    assert all(not v for row in rows[q + size:] for v in row), "quiet zone below"
    assert all(not v for row in rows for v in row[:q] + row[len(row) - q:]), "quiet zone at the sides"
    return [row[q:q + size] for row in rows[q:q + size]]


LINKS = (LINK, "https://kit.local:8710/intake", "https://fk.example.org/filament/intake", "x")


@pytest.mark.parametrize("link", LINKS)
def test_text_and_svg_stand_for_their_link(link):
    assert decode(from_text(qr.text(link))) == link
    assert decode(from_svg(qr.svg(link))) == link


def test_the_reader_is_not_a_rubber_stamp():
    assert decode(from_text(qr.text(LINK))) != LINK + "x"


@pytest.mark.skipif(not shutil.which("wsl"), reason="no WSL to run qrencode in")
def test_qrencode_symbol_reads_back_the_same_link(monkeypatch):
    monkeypatch.undo()
    try:
        r = subprocess.run(["wsl", "-e", "qrencode", "-l", "L", "-m", "0", "-t", "ASCII", LINK],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("qrencode is not reachable")
    if r.returncode or "#" not in r.stdout:
        pytest.skip("qrencode is not installed")
    theirs = [[line[i] == "#" for i in range(0, len(line), 2)] for line in r.stdout.splitlines() if line]
    assert decode(theirs) == LINK                               # the reader reads qrencode's own symbol
    assert theirs == from_text(qr.text(LINK))                   # and ours is the same matrix


def test_text_is_block_characters_with_a_four_module_quiet_zone():
    assert qr.QUIET == 4
    txt = qr.text(LINK)
    plain = re.sub(r"\x1b\[[0-9;]*m", "", txt)
    assert set(plain) <= set(" ▀▄█\n") and "█" in plain
    lines = plain.splitlines()
    side = len(decode_rows := from_text(txt)) + 2 * qr.QUIET
    assert {len(line) for line in lines} == {side} and len(lines) == -(-side // 2)
    assert lines[0].strip() == "" and lines[1].strip() == ""     # four blank module rows above (two characters)
    assert all(line[:4].strip() == "" and line[-4:].strip() == "" for line in lines)
    assert decode_rows


def test_svg_is_an_svg_document_with_a_white_quiet_zone():
    doc = qr.svg(LINK)
    n = len(from_svg(doc))
    assert doc.lstrip().startswith(("<?xml", "<svg")) and f'width="{(n + 2 * qr.QUIET) * 4}"' in doc
    assert 'fill="#fff"' in doc


def test_a_link_too_long_for_a_code_gives_none_and_the_link_itself():
    assert qr.svg("x" * 5000) is None and qr.text("x" * 5000) is None
    assert cli._qr_text("x" * 5000) == "x" * 5000


def test_the_cli_qr_is_the_blocks_not_the_link(capsys):
    url = "https://kit.local:8710/filament-kit.apk"
    print(cli._qr_text(url))
    assert decode(from_text(capsys.readouterr().out.rstrip("\n"))) == url


def test_pair_prints_a_qr_for_the_pairing_link(capsys, env):
    pairing.make_cert("kit", ["192.0.2.5"], config.paths().etc)
    assert cli.main(["pair"]) == 0
    out = capsys.readouterr().out
    block = "\n".join(ln for ln in out.splitlines() if ln.startswith(START))
    link = decode(from_text(block))
    assert link.startswith("fkit://pair?")
    assert re.search(r"Pairing code: \d{6}", out) and "Certificate fingerprint" in out


def test_the_hub_pairing_reply_for_a_phone_carries_a_qr_of_the_link(app):
    pairing.make_cert("kit", ["192.0.2.5"], config.paths().etc)
    r = post(client(app), "pair", {"kind": "phone"}).json()
    assert r["link"].startswith("fkit://pair?") and re.fullmatch(r"[0-9]{6}", r["code"])
    assert decode(from_svg(r["qr_svg"])) == r["link"]


def test_the_page_shows_the_svg_as_an_image_of_the_right_type():
    js = (PKG / "setup_static" / "setup.js").read_text(encoding="utf-8")
    assert js.count('new Blob([r.qr_svg], { type: "image/svg+xml" })') == 1
    assert setup_page.qr_svg(LINK) == qr.svg(LINK)


def test_the_server_module_no_longer_installs_qrencode():
    assert "qrencode" not in modules.MODULES["server"].apt


# ---- vendored segno ----

def test_vendored_segno_matches_the_recorded_hashes():
    text = (VENDOR / "VENDORED.txt").read_text(encoding="utf-8")
    recorded = {ln.split("  ", 1)[1]: ln.split("  ", 1)[0] for ln in text.splitlines()
                if re.fullmatch(r"[0-9a-f]{64}  \S+", ln)}
    assert "segno/__init__.py" in recorded and "segno-LICENSE" in recorded
    for name, digest in recorded.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == digest, name
    on_disk = {p.relative_to(VENDOR).as_posix() for p in (VENDOR / "segno").rglob("*")
               if p.is_file() and "__pycache__" not in p.parts}
    assert on_disk == {n for n in recorded if n != "segno-LICENSE"}
    assert "28c7d081ed0cf935e0411293a465efd4d500704072cdb039778a2ab8736190c7" in text
    assert "https://pypi.org/project/segno/1.6.6/" in text


def test_third_party_lists_segno_and_no_longer_qrencode():
    text = (PKG.parent.parent / "THIRD-PARTY.md").read_text(encoding="utf-8")
    assert "segno" in text and "BSD-3-Clause" in text and "qrencode" not in text


def test_the_package_data_carries_the_vendored_folder():
    """Every file under _vendor/ ships: a .py in a package (it has an __init__.py) or a package-data pattern."""
    import fnmatch
    import tomllib
    cfg = tomllib.loads((PKG.parent / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]
    patterns = cfg["package-data"]["filament_kit"]
    assert (VENDOR / "__init__.py").is_file() and (VENDOR / "segno" / "__init__.py").is_file()
    for f in VENDOR.rglob("*"):
        if f.is_dir() or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(PKG).as_posix()
        assert f.suffix == ".py" or any(fnmatch.fnmatchcase(rel, pat) for pat in patterns), rel
