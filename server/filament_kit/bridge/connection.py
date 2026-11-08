"""One local MQTT-over-TLS connection per configured Bambu printer: live status and commands.

Port 8883, user `bblp`, password = the printer's Access Code. The printer's certificate is self-signed, so it is
pinned instead of CA-verified (`tlspin`): paho's `on_socket_open` runs after the TLS handshake and before the
CONNECT packet is built, and only there, once the live socket's leaf passed the pin, is the Access Code handed to
paho. A changed leaf: state `cert_changed`, the code is withdrawn, paho stops retrying, until the printer is added
again with its code (which clears the pin).
Reports on `device/<serial>/report` are deep-merged into one state; commands go to `device/<serial>/request` and
the printer's reply is matched by `sequence_id`. Ported from the owner's single-printer remote (`remote.py`).
`publish` sends any command and returns the reply; `set_slot` builds on it with the owner's proven
`ams_filament_setting` payload (`h2d-filament-scanner/orchestrator/server.py`); `wait_report` waits until the merged
report satisfies a condition (how a write is confirmed: a later report shows it).

The Access Code is never logged and never part of a repr."""
from __future__ import annotations

import itertools
import json
import logging
import re
import secrets
import threading
import time
from dataclasses import replace
from typing import Any, Callable

from . import hardware, layout, registry, status, tlspin
from ..spoolman import SpoolmanError

log = logging.getLogger(__name__)

PORT = 8883
USER = 'bblp'
KEEPALIVE = 10                  # seconds; a dead printer is noticed within ~10-20 s
BACKOFF = (2, 60)               # reconnect delay, doubling from 2 s up to 60 s
COMMAND_TIMEOUT = 10.0          # seconds to wait for the printer's reply to a command
PUSHALL_AFTER_COMMAND = 1.5     # seconds after a command, ask for a full report
VERSION_GAP = 15.0              # seconds at least between two get_version asks (a later one is sent then)
QUIET_PUSHALL = 90              # a connected printer silent this long gets a pushall
SPOOL_TTL = 30                  # seconds the Spoolman spool list is cached
AUTH_REFUSED = {4, 5, 134, 135}  # CONNACK bad user/password, not authorized (MQTT 3.1.1 and paho v5 codes)
DEVELOPER_MODE_REASON = re.compile(r'verify|auth|permission|denied|developer', re.I)
DEVELOPER_MODE_HOLD = 600.0   # seconds a Developer Mode refusal is shown without a new one (the owner may have fixed it)
DEVELOPER_MODE_ERR_CODES = {84033543}   # Bambu: "mqtt message verify failed" (LAN-only without Developer Mode)
ACTIONS = ('pause', 'resume', 'stop', 'light_on', 'light_off')
SEQ_RANGE = 1_000_000_000        # sequence ids start at a random number below this
STICKY = ('wrong_code', 'cert_changed')   # states only a new code / re-add clears; a drop does not reset them


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


def _developer_mode_refusal(reply: dict) -> bool:
    """A command reply refused because the printer wants Developer Mode (LAN-only mode blocks control)."""
    if not str(reply.get('result', '')).lower().startswith('fail'):
        return False
    try:
        if int(reply.get('err_code')) in DEVELOPER_MODE_ERR_CODES:
            return True
    except (TypeError, ValueError):
        pass
    return bool(DEVELOPER_MODE_REASON.search(str(reply.get('reason', ''))))


class _Waiter:
    def __init__(self):
        self.event = threading.Event()
        self.reply: dict | None = None


def _unit_ids(report: dict) -> set[int] | None:
    units = status._d(report.get('ams')).get('ams')
    if not isinstance(units, list):
        return None
    return {i for i in (status._int(u.get('id')) for u in status._l(units)) if i is not None}


_MODULE_NAME = re.compile(r'^[a-z0-9_]+/(\d{1,3})$', re.I)


def modules_from_version(info) -> dict[str, str]:
    """{"<ams_id>": "<module code>"} from a `get_version` reply's `module` list: entries named "<kind>/<id>"
    (e.g. "n3f/0" -> hw_ver "N3F05", "n3s/128" -> "N3S05"); anything else is ignored."""
    if not isinstance(info, dict) or info.get('command') != 'get_version':
        return {}
    out = {}
    for m in info.get('module') if isinstance(info.get('module'), list) else []:
        if not isinstance(m, dict):
            continue
        mt = _MODULE_NAME.match(str(m.get('name') or ''))
        hw = m.get('hw_ver')
        if mt and isinstance(hw, str) and hw.strip() and hw.strip().upper() != 'N/A' and int(mt.group(1)) <= 253:
            out[str(int(mt.group(1)))] = hw.strip()
    return out


def firmware_from_version(info) -> list[dict]:
    """[{"name", "version"}] from a `get_version` reply, for the printer report: name and sw_ver only (`sn` is a serial)."""
    if not isinstance(info, dict) or info.get('command') != 'get_version':
        return []
    out = []
    for m in info.get('module') if isinstance(info.get('module'), list) else []:
        if isinstance(m, dict) and isinstance(m.get('name'), str) and isinstance(m.get('sw_ver'), str):
            out.append({'name': m['name'], 'version': m['sw_ver']})
    return out


class PrinterConnection:
    def __init__(self, printer: registry.Printer, client_factory: Callable, port: int = PORT,
                 listeners: list[Callable] | None = None):
        self.serial = printer.serial
        self.name = registry.display_name(printer)
        self.ip = printer.ip
        self._code = printer.access_code
        self._printer = replace(printer)     # own copy: tlspin records the pin on it
        self.model = printer.model or None   # registry model code / name (hardware.ModelInfo lookup)
        self._factory = client_factory
        self._port = port
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)   # notified on every report and every state change
        self._report: dict = {}
        self.updated: float | None = None
        self._state = 'offline'
        self._developer_mode_needed = False
        self._developer_mode_at = 0.0
        self._settled = threading.Event()
        self._pending: dict[str, _Waiter] = {}
        # a random start, so two sessions (the service and `printer map`) never reuse each other's sequence ids
        self._seq = itertools.count(secrets.randbelow(SEQ_RANGE))
        self._stopping = False
        self._fresh = False          # no report with `gcode_state` seen yet since the last connect
        self._unit_ids: set[int] | None = None   # AMS unit ids in the last report (a change asks get_version)
        self._version_lock = threading.Lock()
        self._version_at: float | None = None     # monotonic time of the last get_version ask
        self._version_timer: threading.Timer | None = None
        self._listeners = listeners if listeners is not None else []
        self.client = None

    def __repr__(self) -> str:
        return f"PrinterConnection(serial={self.serial!r}, ip={self.ip!r}, state={self.state!r})"

    def same_target(self, p: registry.Printer) -> bool:
        """Same address, code and pin. A cleared pin (the printer was added again) means a new connection."""
        return (p.ip, p.access_code, p.cert_fp) == (self.ip, self._code, self._printer.cert_fp)

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        c = self._factory(f"filament-kit-{self.serial}-{secrets.token_hex(3)}")
        # no password yet: `_on_socket_open` sets it once the leaf of the socket it will go over passed the pin
        c.tls_set_context(tlspin.context())
        c.reconnect_delay_set(min_delay=BACKOFF[0], max_delay=BACKOFF[1])
        c.on_socket_open = self._on_socket_open
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
        with self._version_lock:
            if self._version_timer is not None:
                self._version_timer.cancel()
                self._version_timer = None
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
            if time.monotonic() - self._developer_mode_at < DEVELOPER_MODE_HOLD:
                return 'needs_developer_mode'
            self._developer_mode_needed = False      # not refused again since: the next refusal says so anew
        return self._state

    def _developer_mode_refused(self) -> None:
        self._developer_mode_needed = True
        self._developer_mode_at = time.monotonic()

    def _set_state(self, state: str) -> None:
        if state != self._state:
            log.info("printer %s (%s): %s", self.serial, self.ip, state)
            if state == 'connected':                 # a new session: the printer may have been set up since
                self._developer_mode_needed = False
        self._state = state
        self._settled.set()
        with self._changed:
            self._changed.notify_all()

    def wait_settled(self, timeout: float) -> str:
        self._settled.wait(timeout)
        return self.state

    # ---------------------------------------------------------------- paho callbacks
    def _on_socket_open(self, client, userdata, sock):
        """paho: TLS handshake done, CONNECT not built yet (every connect and reconnect). Raising an OSError here
        aborts the attempt (paho reports it through on_connect_fail)."""
        try:
            tlspin.check_socket(self._printer, sock)
        except tlspin.CertChanged as e:
            client.username_pw_set(USER, None)   # a reconnect must not reuse the code meant for the pinned leaf
            self._set_state('cert_changed')
            client.disconnect()                  # stop paho retrying: only a re-add can clear this
            raise ConnectionAbortedError("the printer's certificate changed") from e
        except Exception as e:
            client.username_pw_set(USER, None)
            raise ConnectionAbortedError(f"cannot check the printer's certificate ({type(e).__name__})") from e
        client.username_pw_set(USER, self._code)

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if _rc_ok(rc):
            self._fresh = True
            self._unit_ids = None
            self._set_state('connected')
            client.subscribe(f"device/{self.serial}/report", qos=0)
            self.request_pushall()
            self.request_version()
        elif _auth_refused(rc):
            self._set_state('wrong_code')
            client.disconnect()          # stop paho retrying a code the printer rejects
        else:
            log.warning("printer %s: connection refused (%s)", self.serial, rc)
            self._set_state('offline')

    def _on_connect_fail(self, client, userdata):
        if self._state not in STICKY:
            self._set_state('offline')

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        if self._state not in STICKY:
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
        mods = modules_from_version(payload.get('info'))
        if mods:      # merged like a report delta (a dict: later replies add to it)
            pr = {**pr, layout.MODULES: mods} if isinstance(pr, dict) else {layout.MODULES: mods}
        firmware = firmware_from_version(payload.get('info'))
        if firmware:
            pr = {**pr, layout.FIRMWARE: firmware} if isinstance(pr, dict) else {layout.FIRMWARE: firmware}
        ask = False
        if isinstance(pr, dict):
            with self._changed:
                self._report = status.merge_report(self._report, pr)
                ids = _unit_ids(self._report)
                if ids is not None and self._unit_ids is not None and ids != self._unit_ids:
                    # units plugged in or out: their module codes are asked again, codes of gone ids dropped
                    keep = ids & self._unit_ids
                    old = status._d(self._report.get(layout.MODULES))
                    self._report = {**self._report, layout.MODULES: {k: v for k, v in old.items()
                                                                     if status._int(k) in keep}}
                    ask = True
                if ids is not None:
                    self._unit_ids = ids
                self.updated = time.time()
                report, first = self._report, self._fresh
                if 'gcode_state' in pr:
                    self._fresh = False
                self._changed.notify_all()
            if ask:
                self.request_version()
            for fn in list(self._listeners):
                try:
                    fn(self.serial, report, first)
                except Exception:
                    log.exception("printer %s: report listener failed", self.serial)

    def _wake_pending(self) -> None:
        for w in list(self._pending.values()):
            w.event.set()
        with self._changed:
            self._changed.notify_all()

    # ---------------------------------------------------------------- reports
    def report(self) -> dict:
        with self._lock:
            return self._report

    def forget_report_key(self, key: str) -> None:
        """Drop `key` from the kept report, so the next value seen is one the printer has sent since."""
        with self._changed:
            if key in self._report:
                self._report = {k: v for k, v in self._report.items() if k != key}

    def wait_report(self, predicate: Callable[[dict], bool], timeout: float) -> dict | None:
        """The merged report as soon as `predicate(report)` is true: checked on the current report, then after each
        report delta. None after `timeout` s, or at once when the connection is not (or no longer) connected.
        `predicate` runs under the connection's lock: keep it a quick pure function of the report."""
        deadline = time.monotonic() + timeout
        with self._changed:
            while True:
                if self._state != 'connected' or self._stopping:
                    return None
                if predicate(self._report):
                    return self._report
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self._changed.wait(left)

    def request_pushall(self) -> None:
        c = self.client
        if c is not None and self._state == 'connected':
            c.publish(f"device/{self.serial}/request",
                      json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}), qos=1)

    def request_version(self) -> None:
        """Ask for the module list (`get_version`: a read-only info request Bambu Studio sends too) at each
        connect and when units are plugged in or out; the reply's AMS module codes ("n3f/0" -> "N3F05") land in
        the report under `layout.MODULES`. At most one ask per VERSION_GAP s: an ask inside the gap is sent when
        it ends (one trailing ask). A printer that never answers keeps resolving its units by id range and tray
        count. While not connected nothing is sent and the gap is not taken (the connect asks again)."""
        with self._version_lock:
            if self.client is None or self._state != 'connected':
                return
            now = time.monotonic()
            if self._version_at is not None and now - self._version_at < VERSION_GAP:
                if self._version_timer is None and not self._stopping:
                    t = threading.Timer(VERSION_GAP - (now - self._version_at), self._trailing_version)
                    t.daemon = True
                    self._version_timer = t
                    t.start()
                return
            self._version_at = now
        c = self.client
        if c is not None and self._state == 'connected':
            c.publish(f"device/{self.serial}/request",
                      json.dumps({"info": {"sequence_id": str(next(self._seq)), "command": "get_version"}}), qos=1)

    def _trailing_version(self) -> None:
        with self._version_lock:
            self._version_timer = None
        if not self._stopping:
            self.request_version()

    # ---------------------------------------------------------------- commands
    def _messages(self, action: str) -> list[tuple[str, dict]]:
        if action in ('pause', 'resume', 'stop'):
            return [('print', {'command': action, 'param': ''})]
        mode = action[len('light_'):]
        nodes = ['chamber_light']
        lights = self.report().get('lights_report')
        if any(isinstance(l, dict) and l.get('node') == 'chamber_light2'
               for l in (lights if isinstance(lights, list) else [])):
            nodes.append('chamber_light2')     # printers with a second chamber light report it
        return [('system', {'command': 'ledctrl', 'led_node': n, 'led_mode': mode, 'led_on_time': 500,
                            'led_off_time': 500, 'loop_times': 0, 'interval_time': 0}) for n in nodes]

    def publish(self, payload: dict, timeout: float) -> dict | None:
        """Send one command (`{"print": {...}}`, `{"system": {...}}` ...) and wait for the printer's reply.

        A `sequence_id` is added unless the body has one. Returns the reply body (the object under `print`/`system`
        carrying `result`, matched by `sequence_id`) or None if no reply came within `timeout` s: some commands get
        no reply, so None is not a failure by itself; confirm the effect with `wait_report`. A reply whose `result`
        is not "success" is returned as is; one refused for Developer Mode also turns the state into
        `needs_developer_mode` (a later success, a new connection or DEVELOPER_MODE_HOLD seconds without another
        refusal clear it). Raises PrinterOffline if not connected or if the
        connection drops while waiting. A full report is requested shortly afterwards."""
        if not isinstance(payload, dict) or len(payload) != 1:
            raise ValueError("payload must have exactly one top-level key")
        (top, body), = payload.items()
        if not isinstance(body, dict):
            raise ValueError("payload body must be an object")
        if self._state != 'connected' or self.client is None:
            raise PrinterOffline(self.serial)
        body = dict(body)
        sid = str(body.get('sequence_id') or next(self._seq))
        body['sequence_id'] = sid
        w = _Waiter()
        self._pending[sid] = w
        try:
            self.client.publish(f"device/{self.serial}/request", json.dumps({top: body}), qos=1)
            w.event.wait(timeout)
        finally:
            self._pending.pop(sid, None)
        t = threading.Timer(PUSHALL_AFTER_COMMAND, self.request_pushall)
        t.daemon = True
        t.start()
        reply = w.reply
        if reply is None:
            if self._state != 'connected':
                raise PrinterOffline(self.serial)
            return None
        if _developer_mode_refusal(reply):
            if not self._developer_mode_needed:
                log.warning("printer %s: %s refused (%s); Developer Mode needed",
                            self.serial, body.get('command'), reply.get('reason'))
            self._developer_mode_refused()
        elif str(reply.get('result', '')).lower() == 'success':
            self._developer_mode_needed = False
        return reply

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
        replies = [w.reply for _, w in waiters]      # ok only if every node's reply succeeded
        reply = replies[0]
        if any(r is None for r in replies):
            if self._state != 'connected':
                raise PrinterOffline(self.serial)
            raise NoReply(self.serial)
        ok = all(str(r.get('result', '')).lower() == 'success' for r in replies)
        refused = [r for r in replies if _developer_mode_refusal(r)]
        if refused:
            if not self._developer_mode_needed:
                log.warning("printer %s: command refused (%s); Developer Mode needed",
                            self.serial, refused[0].get('reason'))
            self._developer_mode_refused()
            reply = refused[0]
        elif ok:
            self._developer_mode_needed = False
        else:
            reply = next(r for r in replies if str(r.get('result', '')).lower() != 'success')
        return {'ok': ok, 'reply': reply}


def slot_setting(ams_id: int, tray_id: int, setting: dict, kind: str | None = None,
                 addressing: str = "legacy") -> dict:
    """The `ams_filament_setting` command exactly as the owner's orchestrator sends it (verified on the H2D);
    `publish` adds the `sequence_id`.

    `kind` = the slot's unit kind (`layout`): for an external holder ("ext") the model's `external_addressing`
    decides: "tray-is-ams" sends `tray_id = ams_id, slot_id = 0` (the scanner's rule, verified on the H2D),
    "legacy" sends `ams_id` = the holder id, `tray_id` 0 and no slot_id (the kit's earlier command; every model
    but the H2D until a capture says otherwise). AMS slots are always `ams_id, tray_id`.

    `setting`: `tray_info_idx`, `tray_color` (RRGGBBAA, sent upper-case), `tray_type`, `nozzle_temp_min`,
    `nozzle_temp_max` (ints; the report's strings are accepted, missing = 0), optional `tray_sub_brands`,
    `setting_id` (default "")."""
    def temp(k):
        try:
            return int(setting.get(k) or 0)
        except (TypeError, ValueError):
            return 0
    cmd = {"print": {
        "command": "ams_filament_setting",
        "ams_id": int(ams_id), "tray_id": int(tray_id),
        "tray_info_idx": str(setting.get('tray_info_idx') or ''),
        "tray_color": str(setting.get('tray_color') or '').upper(),
        "tray_type": str(setting.get('tray_type') or ''),
        "tray_sub_brands": str(setting.get('tray_sub_brands') or ''),
        "nozzle_temp_min": temp('nozzle_temp_min'), "nozzle_temp_max": temp('nozzle_temp_max'),
        "setting_id": str(setting.get('setting_id') or ''),
    }}
    if kind == layout.EXT_KIND and addressing == "tray-is-ams":
        cmd["print"].update(tray_id=int(ams_id), slot_id=0)
    return cmd


class Manager:
    """Keeps one PrinterConnection per configured printer in the registry (`sync()`), serves status and commands."""

    def __init__(self, client_factory: Callable = paho_client, spoolman=None, port: int = PORT,
                 only: set[str] | None = None):
        """`only`: connect just these serials (the CLI's short-lived Manager for one printer); None = all."""
        self._factory = client_factory
        self._only = set(only) if only is not None else None
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
        self._listeners: list[Callable] = []

    def add_listener(self, fn: Callable[[str, dict, bool], None]) -> None:
        """Call `fn(serial, report, first)` after every report from any printer, on that printer's MQTT thread
        (keep it quick; hand slow work to a thread of your own). `report` is the merged report (do not change
        it); `first` is true for the reports after a (re)connect up to and including the first one that carries
        `gcode_state`: what they show happened while nobody watched (usage tracking must not settle it)."""
        self._listeners.append(fn)

    @staticmethod
    def _usable(p: registry.Printer) -> bool:
        return bool(p.configured and p.ip and p.access_code)

    def sync(self) -> None:
        """Reconcile connections with the registry: start new ones, drop removed ones, reconnect on IP/code change."""
        printers = registry.load()
        if self._only is not None:
            printers = {s: p for s, p in printers.items() if s in self._only}
        stale: list[PrinterConnection] = []
        with self._lock:
            self._printers = printers
            for serial, conn in list(self._conns.items()):
                p = printers.get(serial)
                if p is None or not self._usable(p) or not conn.same_target(p):
                    stale.append(conn)
                    del self._conns[serial]
                else:
                    conn.name = registry.display_name(p)
                    conn.model = p.model or None
            for serial, p in printers.items():
                if serial not in self._conns and self._usable(p):
                    conn = PrinterConnection(p, self._factory, self.port, self._listeners)
                    self._conns[serial] = conn
                    conn.start()
        for conn in stale:  # a slow disconnect must not block state reads and commands for other printers
            conn.stop()

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
            conns = list(self._conns.values())
            self._conns.clear()
        for conn in conns:
            conn.stop()

    def _conn(self, serial: str) -> PrinterConnection | None:
        with self._lock:
            return self._conns.get(serial)

    def state(self, serial: str) -> str:
        conn = self._conn(serial)
        if conn is not None:
            return conn.state
        p = self._printers.get(serial)
        return 'offline' if p is not None and p.configured else 'not_configured'

    def request_pushall(self, serial: str) -> None:
        """Ask a connected printer for a full report (nothing when it is unknown or not connected)."""
        conn = self._conn(serial)
        if conn is not None:
            conn.request_pushall()

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
        return status.summarize(conn.report(), self._spool_list(), printer_name=conn.name, updated=conn.updated,
                                model=conn.model)

    def summary(self, serial: str) -> dict:
        conn = self._conn(serial)
        return status.brief(conn.report() if conn is not None else {})

    def model(self, serial: str) -> str | None:
        """The printer's model code or name from the registry (None when unknown)."""
        conn = self._conn(serial)
        if conn is not None:
            return conn.model
        p = self._printers.get(serial)
        return (p.model or None) if p is not None else None

    def _live(self, serial: str) -> PrinterConnection:
        conn = self._conn(serial)
        if conn is None:
            p = self._printers.get(serial)
            if p is not None and p.configured:
                raise PrinterOffline(serial)
            raise UnknownPrinter(serial)
        return conn

    def command(self, serial: str, action: str) -> dict:
        return self._live(serial).command(action, COMMAND_TIMEOUT)

    def publish(self, serial: str, payload: dict, timeout: float | None = None) -> dict | None:
        """Send any command to a printer: the reply body, or None if it did not reply within `timeout` s (default
        COMMAND_TIMEOUT); see `PrinterConnection.publish`. Raises UnknownPrinter / PrinterOffline. A command that
        changes the printer is the caller's to gate on the printer being idle."""
        return self._live(serial).publish(payload, COMMAND_TIMEOUT if timeout is None else timeout)

    def set_slot(self, serial: str, ams_id: int, tray_id: int, setting: dict,
                 timeout: float | None = None, kind: str | None = None) -> dict | None:
        """Write one AMS slot's filament setting (`slot_setting`; `kind` = the unit's kind, "ext" for an external
        holder, addressed as the printer's model says); returns the reply as `publish` does. A reply with
        `result` "success" means accepted, not applied: confirm it with `wait_report` (a later report shows it)."""
        addressing = hardware.load().model(self.model(serial)).external_addressing
        return self.publish(serial, slot_setting(ams_id, tray_id, setting, kind, addressing), timeout)

    def forget_report_key(self, serial: str, key: str) -> None:
        c = self._conns.get(serial)
        if c is not None:
            c.forget_report_key(key)

    def wait_report(self, serial: str, predicate: Callable[[dict], bool], timeout: float) -> dict | None:
        """Wait up to `timeout` s for the printer's merged report to satisfy `predicate` and return that report;
        None on timeout, or at once when the printer is unknown, not connected or drops."""
        conn = self._conn(serial)
        if conn is None:
            return None
        return conn.wait_report(predicate, timeout)
