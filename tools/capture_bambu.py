"""Read-only capture of a Bambu printer's MQTT report, for a test fixture (spec P §6). The OWNER runs it.

    sudo /opt/h2d-scanner/venv/bin/python -I tools/capture_bambu.py --env /etc/h2d-scanner/env --out h2d.json

Reads PRINTER_IP, PRINTER_SERIAL and PRINTER_CODE from the env file it is given (the h2d-filament-scanner
format, `KEY=value` lines as systemd's EnvironmentFile reads them), connects to the printer over MQTT/TLS (port
8883, user bblp), subscribes to its report, sends ONLY two read-only requests, `pushall` (the full report) and
`get_version` (the module list: AMS module codes), collects for --seconds (15), and disconnects.

The fixture (JSON) holds every message received (`messages`: topic, seconds since connect, payload) and the
`print` payloads merged in order (`report`). The serial is replaced by SERIAL0000000000 everywhere (keys, topics,
nested strings) and every IPv4 address by 192.0.2.1. The access code is never printed or written (a value
equal to it is replaced by REDACTED). An --out inside the repository's tests directory is refused without
--force: review the file before it is committed.

Standard library + paho-mqtt (the scanner's and the kit's venvs both have it)."""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "server" / "tests"
SERIAL_OUT = "SERIAL0000000000"
IP_OUT = "192.0.2.1"
REDACTED = "REDACTED"
SECONDS = 15.0
PORT = 8883
ENV_KEYS = ("PRINTER_IP", "PRINTER_SERIAL", "PRINTER_CODE")
# the only payloads this script ever publishes (read-only requests Bambu Studio sends too)
PUSHALL = {"pushing": {"sequence_id": "0", "command": "pushall"}}
GET_VERSION = {"info": {"sequence_id": "0", "command": "get_version"}}
COMMANDS = (PUSHALL, GET_VERSION)
# an IPv4 address: no leading zeros (Bambu firmware versions such as "01.08.02.00" stay), not inside a word or a
# longer dotted number ("v1.2.3.4")
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4 = re.compile(rf"(?<![\w.]){_OCTET}(?:\.{_OCTET}){{3}}(?![\w.])")


class CaptureError(Exception):
    """A message for the owner (never containing the access code)."""


def check_read_only(payload: dict) -> None:
    """The read-only rule, checked at the one place the script publishes: exactly `pushall` or `get_version`
    (compared with literals, not with COMMANDS, so an edit there cannot widen it)."""
    if payload not in ({"pushing": {"sequence_id": "0", "command": "pushall"}},
                       {"info": {"sequence_id": "0", "command": "get_version"}}):
        raise CaptureError("refusing to publish anything but pushall and get_version")


def read_env(path: str | Path) -> dict[str, str]:
    """PRINTER_IP / PRINTER_SERIAL / PRINTER_CODE from a systemd EnvironmentFile (`KEY=value`, optional quotes,
    `#` comments, optional `export`). Other keys are ignored and never kept."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise CaptureError(f"cannot read the env file {path}: {e.strerror or e}") from None
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if key not in ENV_KEYS:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key] = val
    missing = [k for k in ENV_KEYS if not out.get(k)]
    if missing:
        raise CaptureError(f"the env file {path} has no {', '.join(missing)}")
    return out


def scrub(obj: Any, serial: str, code: str | None = None) -> Any:
    """A copy with the serial -> SERIAL0000000000 (also inside keys and longer strings), every IPv4 address ->
    192.0.2.1, and a value equal to the access code -> REDACTED."""
    if isinstance(obj, dict):
        return {scrub(k, serial, code): scrub(v, serial, code) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, serial, code) for v in obj]
    if isinstance(obj, str):
        if code and code in obj:
            obj = obj.replace(code, REDACTED)
        if serial:
            obj = obj.replace(serial, SERIAL_OUT)
        return _IPV4.sub(IP_OUT, obj)
    return obj


def merge(base: dict, delta: dict) -> dict:
    """Deep-merge a report delta (dicts merge, everything else replaces)."""
    for k, v in delta.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge(base[k], v)
        else:
            base[k] = json.loads(json.dumps(v))
    return base


def inside_tests(out: Path) -> bool:
    try:
        out.resolve().relative_to(TESTS.resolve())
        return True
    except ValueError:
        return False


def _paho_client(client_id: str):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        raise CaptureError("paho-mqtt is not installed for this python; run it with the scanner's venv "
                           "(/opt/h2d-scanner/venv/bin/python) or the kit's (/opt/filament-kit/venv/bin/python)") \
            from None
    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)


def capture(host: str, serial: str, code: str, seconds: float = SECONDS,
            client_factory: Callable[[str], Any] = _paho_client, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Connect, send the two read-only requests once connected, collect for `seconds`, disconnect. Returns the
    raw (unscrubbed) capture: {"messages": [...], "connected": bool}."""
    client = client_factory(f"fk-capture-{int(time.time())}")
    messages: list[dict] = []
    state = {"connected": False, "sent": False, "rc": None}
    lock = threading.Lock()
    t0 = time.monotonic()
    request = f"device/{serial}/request"

    def send(payload: dict) -> None:
        check_read_only(payload)
        client.publish(request, json.dumps(payload), qos=1)

    def on_connect(c, userdata, flags, rc, props=None):
        state["rc"] = str(rc)
        if getattr(rc, "is_failure", False) or (isinstance(rc, int) and rc != 0):
            return
        state["connected"] = True
        c.subscribe(f"device/{serial}/report", qos=0)
        with lock:                           # a reconnect inside the window does not ask again
            first = not state["sent"]
            state["sent"] = True
        if first:                            # outside the lock: a reply may be delivered at once
            for p in COMMANDS:
                send(p)

    def on_message(c, userdata, msg):
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            payload = {"_undecodable": msg.payload.decode("utf-8", "replace")[:2000]}
        with lock:
            messages.append({"topic": msg.topic, "t": round(time.monotonic() - t0, 2), "payload": payload})

    client.username_pw_set("bblp", code)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE          # Bambu printers present a self-signed leaf (read-only capture)
    client.tls_set_context(ctx)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(host, PORT, keepalive=30)
    except OSError as e:
        raise CaptureError(f"cannot connect to the printer at {host}:{PORT}: {e.strerror or type(e).__name__}") \
            from None
    client.loop_start()
    try:
        sleep(seconds)
    finally:
        client.loop_stop()
        client.disconnect()
    if not state["connected"]:
        raise CaptureError(f"the printer did not accept the connection (result {state['rc']}); check the "
                           "access code and LAN mode on the printer")
    with lock:
        return {"connected": True, "messages": list(messages)}


def fixture(raw: dict, serial: str, code: str, seconds: float) -> dict:
    report: dict = {}
    for m in raw["messages"]:
        p = m["payload"].get("print") if isinstance(m["payload"], dict) else None
        if isinstance(p, dict):
            merge(report, p)
    version = [m["payload"]["info"] for m in raw["messages"]
               if isinstance(m["payload"], dict) and isinstance(m["payload"].get("info"), dict)
               and m["payload"]["info"].get("command") == "get_version"]
    out = {"captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seconds": seconds,
           "sent": [c for c in COMMANDS], "report": {"print": report}, "version": version[-1] if version else None,
           "messages": raw["messages"]}
    return scrub(out, serial, code)


def main(argv: list[str] | None = None, *, client_factory: Callable[[str], Any] = _paho_client,
         sleep: Callable[[float], None] = time.sleep) -> int:
    ap = argparse.ArgumentParser(prog="capture_bambu.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--env", required=True, help="the env file with PRINTER_IP, PRINTER_SERIAL, PRINTER_CODE")
    ap.add_argument("--out", required=True, help="the fixture to write (JSON)")
    ap.add_argument("--seconds", type=float, default=SECONDS, help=f"how long to collect (default {SECONDS:g})")
    ap.add_argument("--force", action="store_true", help="allow --out inside the repository's tests directory")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if inside_tests(out) and not args.force:
        print(f"error: {out} is inside {TESTS}; write it elsewhere, review it, then copy it in "
              "(or pass --force)", file=sys.stderr)
        return 2
    try:
        env = read_env(args.env)
        host, serial, code = env["PRINTER_IP"], env["PRINTER_SERIAL"], env["PRINTER_CODE"]
        print(f"capturing from the printer for {args.seconds:g} s (pushall + get_version only) ...")
        raw = capture(host, serial, code, args.seconds, client_factory, sleep)
    except CaptureError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    data = fixture(raw, serial, code, args.seconds)
    text = json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False)
    if code in text or serial in text:       # belt and braces: never write either
        print("error: the scrubbed capture still holds the serial or access code; nothing written", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {out}: {len(data['messages'])} messages, module list "
          f"{'received' if data['version'] else 'NOT received'}; serial and IPs replaced. Review it before "
          "sending or committing it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
