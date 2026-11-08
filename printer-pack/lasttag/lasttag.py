"""lasttag: read-only HTTP view of nfc2klipper's last NFC tag, for the filament-kit server (its tag sources).

GET /last-tag -> {"status": "ok", "nfc_id": "...", "spool_id": ..., "read_at": "<ISO local time>", "read_at_unix": ...,
                  "age_seconds": ...}   (nfc2klipper's IPC get_state, nothing else; read_at is null until a tap
                  after the backend started, or if the backend lacks the local read_at patch)
Answers only the addresses listed in the `allow` file next to this script (one per line; written by the
filament-kit printer pack). No writes, no other routes. Runs as the lasttag systemd service on port 5002
with nfc2klipper's venv Python (for its lib.ipc client); lives outside ~/nfc2klipper so updates don't touch it.
"""
import datetime, json, os, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer

NFC = os.path.expanduser("~/nfc2klipper")
sys.path.insert(0, NFC)
from lib.ipc import IPCClient  # noqa: E402

ALLOW_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "allow")
with open(ALLOW_FILE, encoding="utf-8") as _f:
    ALLOW = {line.strip() for line in _f if line.strip() and not line.startswith("#")} | {"127.0.0.1"}
CLIENT = IPCClient(os.path.join(NFC, "nfc2klipper.sock"))


class Handler(BaseHTTPRequestHandler):
    server_version = "lasttag"
    sys_version = ""

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.client_address[0] not in ALLOW:
            return self._send(403, {"status": "error", "message": "forbidden"})
        if self.path != "/last-tag":
            return self._send(404, {"status": "error", "message": "not found"})
        try:
            s = CLIENT.send_request({"command": "get_state"})
        except Exception as e:  # backend down or restarting
            return self._send(503, {"status": "error", "message": f"nfc2klipper backend: {e}"})
        at = s.get("read_at")  # unix time; needs the local read_at patch in nfc2klipper_backend.py
        self._send(200, {"status": s.get("status"), "nfc_id": s.get("nfc_id"), "spool_id": s.get("spool_id"),
                         "read_at": datetime.datetime.fromtimestamp(at).astimezone().isoformat(timespec="seconds") if at else None,
                         "read_at_unix": at, "age_seconds": round(time.time() - at) if at else None})

    def log_message(self, fmt, *args):
        pass  # one journal line per poll is noise


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 5002), Handler).serve_forever()
