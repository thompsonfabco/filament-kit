"""One local MQTT-over-TLS connection per configured Bambu printer: live status and commands.

Port 8883, user `bblp`, password = the printer's Access Code; the printer's certificate is self-signed, so TLS is
not verified (the Access Code only ever goes to the registry IP, which discovery ties to the announcing host).
Reports on `device/<serial>/report` are deep-merged into one state; commands go to `device/<serial>/request` and
the printer's reply is matched by `sequence_id`. Ported from the owner's single-printer remote (`remote.py`).

The Access Code is never logged and never part of a repr."""
from __future__ import annotations

import itertools
import json
import logging
import re
import secrets
import ssl
import threading
import time
from typing import Any, Callable

from . import registry, status
from ..spoolman import SpoolmanError

log = logging.getLogger(__name__)

PORT = 8883
USER = 'bblp'
KEEPALIVE = 20                  # seconds; a dead printer is noticed within about one keepalive
BACKOFF = (2, 60)               # reconnect delay, doubling from 2 s up to 60 s
COMMAND_TIMEOUT = 10.0          # seconds to wait for the printer's reply to a command
PUSHALL_AFTER_COMMAND = 1.5     # seconds after a command, ask for a full report
QUIET_PUSHALL = 90              # a connected printer silent this long gets a pushall
SPOOL_TTL = 30                  # seconds the Spoolman spool list is cached
AUTH_REFUSED = {4, 5, 134, 135}  # CONNACK bad user/password, not authorized (MQTT 3.1.1 and paho v5 codes)
DEVELOPER_MODE_REASON = re.compile(r'verify|auth|permission|denied|developer', re.I)
ACTIONS = ('pause', 'resume', 'stop', 'light_on', 'light_off')


class PrinterOffline(Exception):
    pass


class NoReply(Exception):
    pass


class UnknownPrinter(KeyError):
    pass


def paho_client(client_id: str):
    import paho.mqtt.client as mqtt
    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)


def _auth_refused(rc: Any) -> bool:
    try:
        return int(getattr(rc, 'value', rc)) in AUTH_REFUSED
    except (TypeError, ValueError):
        return False


def _rc_ok(rc: Any) -> bool:
    try:
        return int(getattr(rc, 'value', rc)) == 0
    except (TypeError, ValueError):
        return False


def _tls_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class _Waiter:
    def __init__(self):
        self.event = threading.Event()
        self.reply: dict | None = None


class PrinterConnection:
    def __init__(self, printer: registry.Printer, client_factory: Callable, port: int = PORT):
        self.serial = printer.serial
        self.name = printer.name
        self.ip = printer.ip
        self._code = printer.access_code
        self._factory = client_factory
        self._port = port
        self._lock = threading.Lock()
        self._report: dict = {}
        self.updated: float | None = None
        self._state = 'offline'
        self._developer_mode_needed = False
        self._settled = threading.Event()
        self._pending: dict[str, _Waiter] = {}
        self._seq = itertools.count(int(time.time()) % 100000)
        self._stopping = False
        self.client = None

    def __repr__(self) -> str:
        return f"PrinterConnection(serial={self.serial!r}, ip={self.ip!r}, state={self.state!r})"

    def same_target(self, p: registry.Printer) -> bool:
        return (p.ip, p.access_code) == (self.ip, self._code)

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        c = self._factory(f"filament-kit-{self.serial}-{secrets.token_hex(3)}")
        c.username_pw_set(USER, self._code)
        c.tls_set_context(_tls_context())
        c.reconnect_delay_set(min_delay=BACKOFF[0], max_delay=BACKOFF[1])
        c.on_connect = self._on_connect
        c.on_connect_fail = self._on_connect_fail
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message
        self.client = c
        log.info("printer %s: connecting to %s:%s", self.serial, self.ip, self._port)
        c.connect_async(self.ip, self._port, keepalive=KEEPALIVE)
        c.loop_start()

    def stop(self) -> None:
        self._stopping = True
        c = self.client
        if c is None:
            return
        try:
            c.disconnect()
        except Exception as e:  # already closed
            log.debug("printer %s: disconnect: %s", self.serial, e)
        c.loop_stop()
        self._wake_pending()

    @property
    def state(self) -> str:
        if self._state == 'connected' and self._developer_mode_needed:
            return 'needs_developer_mode'
        return self._state

    def _set_state(self, state: str) -> None:
        if state != self._state:
            log.info("printer %s (%s): %s", self.serial, self.ip, state)
        self._state = state
        self._settled.set()

    def wait_settled(self, timeout: float) -> str:
        self._settled.wait(timeout)
        return self.state

    # ---------------------------------------------------------------- paho callbacks
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if _rc_ok(rc):
            self._set_state('connected')
            client.subscribe(f"device/{self.serial}/report", qos=0)
            self.request_pushall()
        elif _auth_refused(rc):
            self._set_state('wrong_code')
            client.disconnect()          # stop paho retrying a code the printer rejects
        else:
            log.warning("printer %s: connection refused (%s)", self.serial, rc)
            self._set_state('offline')

    def _on_connect_fail(self, client, userdata):
        if self._state != 'wrong_code':
            self._set_state('offline')

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        if self._state != 'wrong_code':
            self._set_state('offline')
        self._wake_pending()

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8', 'replace'))
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        for top in ('print', 'system'):
            body = payload.get(top)
            if isinstance(body, dict) and 'result' in body:
                w = self._pending.get(str(body.get('sequence_id')))
                if w is not None:
                    w.reply = body
                    w.event.set()
        pr = payload.get('print')
        if isinstance(pr, dict):
            with self._lock:
                self._report = status.merge(self._report, pr)
                self.updated = time.time()

    def _wake_pending(self) -> None:
        for w in list(self._pending.values()):
            w.event.set()

    # ---------------------------------------------------------------- reports
    def report(self) -> dict:
        with self._lock:
            return self._report

    def request_pushall(self) -> None:
        c = self.client
        if c is not None and self._state == 'connected':
            c.publish(f"device/{self.serial}/request",
                      json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}), qos=1)

    # ---------------------------------------------------------------- commands
    def _messages(self, action: str) -> list[tuple[str, dict]]:
        if action in ('pause', 'resume', 'stop'):
            return [('print', {'command': action, 'param': ''})]
        mode = action[len('light_'):]
        nodes = ['chamber_light']
        if any(isinstance(l, dict) and l.get('node') == 'chamber_light2'
               for l in self.report().get('lights_report') or []):
            nodes.append('chamber_light2')     # printers with a second chamber light report it
        return [('system', {'command': 'ledctrl', 'led_node': n, 'led_mode': mode, 'led_on_time': 500,
                            'led_off_time': 500, 'loop_times': 0, 'interval_time': 0}) for n in nodes]

    def command(self, action: str, timeout: float) -> dict:
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        if self._state != 'connected' or self.client is None:
            raise PrinterOffline(self.serial)
        waiters: list[tuple[str, _Waiter]] = []
        try:
            for top, body in self._messages(action):
                sid = str(next(self._seq))
                w = _Waiter()
                self._pending[sid] = w
                waiters.append((sid, w))
                self.client.publish(f"device/{self.serial}/request",
                                    json.dumps({top: dict(body, sequence_id=sid)}), qos=1)
            deadline = time.monotonic() + timeout
            for _, w in waiters:
                w.event.wait(max(0.0, deadline - time.monotonic()))
        finally:
            for sid, _ in waiters:
                self._pending.pop(sid, None)
        t = threading.Timer(PUSHALL_AFTER_COMMAND, self.request_pushall)
        t.daemon = True
        t.start()
        reply = waiters[0][1].reply
        if reply is None:
            if self._state != 'connected':
                raise PrinterOffline(self.serial)
            raise NoReply(self.serial)
        result = str(reply.get('result', '')).lower()
        ok = result == 'success'
        if ok:
            self._developer_mode_needed = False
        elif result.startswith('fail') and DEVELOPER_MODE_REASON.search(str(reply.get('reason', ''))):
            if not self._developer_mode_needed:
                log.warning("printer %s: command refused (%s); Developer Mode needed",
                            self.serial, reply.get('reason'))
            self._developer_mode_needed = True
        return {'ok': ok, 'reply': reply}


class Manager:
    """Keeps one PrinterConnection per configured printer in the registry (`sync()`), serves status and commands."""

    def __init__(self, client_factory: Callable = paho_client, spoolman=None, port: int = PORT):
        self._factory = client_factory
        self._spoolman = spoolman
        self.port = port
        self._conns: dict[str, PrinterConnection] = {}
        self._printers: dict[str, registry.Printer] = {}
        self._lock = threading.Lock()
        self._spools: list[dict] = []
        self._spools_at = 0.0
        self._spools_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _usable(p: registry.Printer) -> bool:
        return bool(p.configured and p.ip and p.access_code)

    def sync(self) -> None:
        """Reconcile connections with the registry: start new ones, drop removed ones, reconnect on IP/code change."""
        printers = registry.load()
        with self._lock:
            self._printers = printers
            for serial, conn in list(self._conns.items()):
                p = printers.get(serial)
                if p is None or not self._usable(p) or not conn.same_target(p):
                    conn.stop()
                    del self._conns[serial]
                else:
                    conn.name = p.name
            for serial, p in printers.items():
                if serial not in self._conns and self._usable(p):
                    conn = PrinterConnection(p, self._factory, self.port)
                    self._conns[serial] = conn
                    conn.start()

    def start(self, interval: float = 15) -> None:
        """Sync now, then every `interval` s (picks up CLI edits) and nudge quiet printers with a pushall."""
        self.sync()

        def run():
            while not self._stop.wait(interval):
                try:
                    self.sync()
                    for conn in list(self._conns.values()):
                        if conn.state != 'offline' and time.time() - (conn.updated or 0) > QUIET_PUSHALL:
                            conn.request_pushall()
                except Exception:
                    log.exception("printer manager housekeeping failed")
        self._thread = threading.Thread(target=run, name='printer-manager', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        with self._lock:
            for conn in self._conns.values():
                conn.stop()
            self._conns.clear()

    def _conn(self, serial: str) -> PrinterConnection | None:
        with self._lock:
            return self._conns.get(serial)

    def state(self, serial: str) -> str:
        conn = self._conn(serial)
        if conn is not None:
            return conn.state
        p = self._printers.get(serial)
        return 'offline' if p is not None and p.configured else 'not_configured'

    def wait_settled(self, serial: str, timeout: float) -> str:
        """Wait until a new connection has its first result (connected, wrong code, unreachable); return the state."""
        conn = self._conn(serial)
        if conn is not None:
            conn.wait_settled(timeout)
        return self.state(serial)

    def _spool_list(self) -> list[dict]:
        if self._spoolman is None:
            return []
        with self._spools_lock:
            if time.monotonic() - self._spools_at > SPOOL_TTL or not self._spools_at:
                try:
                    self._spools = self._spoolman.get('spool') or []
                except SpoolmanError as e:
                    log.warning("spoolman: cannot list spools for printer slots: %s", e)
                self._spools_at = time.monotonic()
            return self._spools

    def status(self, serial: str) -> dict | None:
        conn = self._conn(serial)
        if conn is None:
            return None
        return status.summarize(conn.report(), self._spool_list(), printer_name=conn.name, updated=conn.updated)

    def summary(self, serial: str) -> dict:
        conn = self._conn(serial)
        r = conn.report() if conn is not None else {}
        s = status.summarize(r, [])
        return {'gcode_state': s['gcode_state'], 'percent': s['percent'], 'remaining_min': s['remaining_min']}

    def command(self, serial: str, action: str) -> dict:
        conn = self._conn(serial)
        if conn is None:
            p = self._printers.get(serial)
            if p is not None and p.configured:
                raise PrinterOffline(serial)
            raise UnknownPrinter(serial)
        return conn.command(action, COMMAND_TIMEOUT)
