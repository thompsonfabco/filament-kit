"""The design's shared files (S0.10, N29/N30): what the generator copies, what package-data ships, and the sprite's
place in a page. The two pages' own tests (test_setup_page.py, test_web_app.py) request the files from their addresses."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from filament_kit import shared_files

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
# name -> the repository source each served file is a copy of
SOURCES = {"tokens.css": ROOT / "tokens" / "tokens.css", "theme-init.js": ROOT / "tokens" / "theme-init.js",
           "strings.js": ROOT / "strings" / "strings.js", "sprite.svg": ROOT / "icons" / "sprite.svg"}
TYPES = {"tokens.css": "text/css", "theme-init.js": "text/javascript", "strings.js": "text/javascript",
         "sprite.svg": "image/svg+xml"}
# Today's page headers (the CSP the pages had before S0.10), compared whole
SETUP_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
             "connect-src 'self'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'")
INTAKE_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
              "connect-src 'self'; manifest-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")

# with the Printers tab the intake CSP also allows media-src (IntakeApp.headers)
INTAKE_CSP_PRINTERS = INTAKE_CSP.replace("connect-src 'self';", "connect-src 'self'; media-src 'self';")


def expected():
    """name -> bytes every page address must serve: the sources, and any file in web-shared/."""
    out = {name: p.read_bytes() for name, p in SOURCES.items()}
    folder = ROOT / "web-shared"
    if folder.is_dir():
        out.update({p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()})
    return out


def check_files(get, prefix):
    """Every shared file, requested from `prefix` with `get`, has the source's bytes and the right type."""
    for name, data in expected().items():
        r = get(f"{prefix}/shared/{name}")
        assert r.status_code == 200, name
        assert r.content == data, name
        assert r.headers["content-type"].split(";")[0] == shared_files.TYPES[Path(name).suffix], name
        assert r.headers["x-content-type-options"] == "nosniff"
    assert get(f"{prefix}/shared/nothing.js").status_code == 404


def check_sprite_first(page_text):
    """The sprite is the first child of <body>, hidden, and the generated header comment is left out."""
    m = re.search(r"<body[^>]*>", page_text)
    assert m, "no <body>"
    after = page_text[m.end():]
    assert after.startswith('<svg class="sprite" aria-hidden="true" width="0" height="0">')
    assert "GENERATED" not in page_text and "<!--" not in page_text
    assert "</svg><main id=app>" in after


def test_the_copies_the_hub_serves_equal_the_repository_sources():
    served = shared_files.load()
    for name, data in expected().items():
        assert served[name] == data, name
    assert set(TYPES) <= set(served)


def test_the_wheel_ships_shared_static():
    cfg = tomllib.loads((SERVER / "pyproject.toml").read_text(encoding="utf-8"))
    assert "shared_static/*" in cfg["tool"]["setuptools"]["package-data"]["filament_kit"]


def test_missing_folder_is_no_files_and_no_sprite(tmp_path, monkeypatch):
    monkeypatch.setattr(shared_files, "SHARED", tmp_path / "absent")
    assert shared_files.load() == {} and shared_files.sprite_inline({}) == ""
    assert shared_files.response({}, "tokens.css").status_code == 404
