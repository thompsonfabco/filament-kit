"""The design's shared files, served to the Hub page and the web app from one place (design 08 section 1, N29/N30).

`shared_static/` is generated (tokens/build_tokens.py copies tokens.css, theme-init.js, strings.js, sprite.svg and every
file of web-shared/ into it); each page serves it under `<its own address>/shared/<file>`. The sprite also goes inline
as the first child of every page's `<body>`, hidden (it carries aria-hidden and zero size)."""
from __future__ import annotations

from pathlib import Path

from starlette.responses import Response

SHARED = Path(__file__).parent / "shared_static"
TYPES = {".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml"}
SPRITE = "sprite.svg"


def load() -> dict[str, bytes]:
    """name -> bytes of every shared file (empty when the folder is missing)."""
    if not SHARED.is_dir():
        return {}
    return {p.name: p.read_bytes() for p in sorted(SHARED.iterdir()) if p.is_file() and p.suffix in TYPES}


def sprite_inline(files: dict[str, bytes]) -> str:
    """The sprite for the top of `<body>`: the generated header comment left out, and the xmlns attribute (HTML needs
    none; the pages carry no URL text)."""
    text = files.get(SPRITE, b"").decode("utf-8")
    return text[text.index("<svg"):].strip().replace(' xmlns="http://www.w3.org/2000/svg"', "", 1) if "<svg" in text else ""


def response(files: dict[str, bytes], name: str) -> Response:
    """The file, or 404; the headers are those of the page's own assets."""
    if name not in files:
        return Response(status_code=404)
    return Response(files[name], media_type=TYPES[Path(name).suffix],
                    headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})
