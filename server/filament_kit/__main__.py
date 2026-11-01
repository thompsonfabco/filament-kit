"""Run the app API: `python -m filament_kit` (HTTPS on 0.0.0.0:<port>, one worker)."""
import uvicorn

from . import config
from .api import create_app


def main() -> None:
    cfg = config.load()
    etc = config.paths().etc
    # one worker only: the pairing and inventory locks are per process
    uvicorn.run(create_app(), host="0.0.0.0", port=cfg["port"], ssl_certfile=str(etc / "cert.pem"),
                ssl_keyfile=str(etc / "key.pem"), workers=1)


if __name__ == "__main__":
    main()
