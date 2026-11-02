"""A stand-in for paho's MQTT client and a fake Bambu printer behind it. No network.

`FakeClient` records what the connection publishes; the test drives paho's callbacks (`connected`, `dropped`,
`deliver`). A `responder` (fn(topic, body) -> payload | [payloads] | None) answers publishes; its payloads arrive
shortly afterwards on the report topic, in order, from a timer thread (as paho's network loop would).

`FakePrinter` is such a responder: it keeps a report, answers `pushall` with the full report and applies
`ams_filament_setting` to its AMS units / external holder (reply first, then the changed report delta)."""
from __future__ import annotations

import copy
import json
import threading

from .fake_certs import FakeTlsSock, Leaf

LEAF = Leaf()                       # the default printer leaf (no CN): pins for any serial


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, json.dumps(payload).encode()


class FakeClient:
    """Stands in for paho.mqtt.client.Client; the test drives its callbacks."""

    def __init__(self, client_id):
        self.client_id = client_id
        self.published, self.subscribed, self.calls = [], [], []
        self.host = self.port = self.keepalive = None
        self.username = self.password = None
        self.reconnect_delay = None
        self.on_connect = self.on_disconnect = self.on_message = self.on_connect_fail = None
        self.on_socket_open = None
        self.responder = None          # fn(topic, payload_dict) -> reply payload dict | list of them | None

    def username_pw_set(self, username, password):
        self.username, self.password = username, password

    def tls_set_context(self, ctx):
        self.tls = ctx

    def reconnect_delay_set(self, min_delay, max_delay):
        self.reconnect_delay = (min_delay, max_delay)

    def connect_async(self, host, port, keepalive):
        self.host, self.port, self.keepalive = host, port, keepalive
        self.calls.append("connect_async")

    def loop_start(self):
        self.calls.append("loop_start")

    def loop_stop(self):
        self.calls.append("loop_stop")

    def disconnect(self):
        self.calls.append("disconnect")

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)

    def publish(self, topic, payload, qos=0):
        body = json.loads(payload)
        self.published.append((topic, body))
        if self.responder:
            reply = self.responder(topic, body)
            if reply is not None:
                replies = reply if isinstance(reply, list) else [reply]
                threading.Timer(0.02, self._deliver_all, args=(replies,)).start()

    def _deliver_all(self, payloads):
        for p in payloads:
            self.deliver(p)

    # test helpers
    def socket_open(self, der=None) -> bool:
        """What paho does after the TLS handshake and before CONNECT; False = the attempt failed (OSError)."""
        if self.on_socket_open is not None:
            try:
                self.on_socket_open(self, None, FakeTlsSock(LEAF.der if der is None else der))
            except OSError:
                if self.on_connect_fail:
                    self.on_connect_fail(self, None)
                return False
        return True

    def connected(self, rc=0, der=None):
        if self.socket_open(der):
            self.on_connect(self, None, {}, rc, None)

    def dropped(self, rc=7):
        self.on_disconnect(self, None, {}, rc, None)

    def deliver(self, payload, serial=None):
        self.on_message(self, None, Msg(f"device/{serial or 'x'}/report", payload))


SETTING_FIELDS = ('tray_info_idx', 'tray_color', 'tray_type', 'tray_sub_brands', 'nozzle_temp_min',
                  'nozzle_temp_max', 'setting_id')


class FakePrinter:
    """A Bambu printer's MQTT side: `client.responder = printer.respond`.

    Knobs: `refuse[(ams_id, tray_id)] = {"result": "fail", "reason": ...}` refuses that slot's writes;
    `frozen = True` replies success but no longer applies writes; `route[(ams_id, tray_id)] = (a, t)` applies a
    write to another tray (a mis-addressed slot); `silent = True` applies writes but sends no reply.
    `writes` lists every `ams_filament_setting` body received."""

    def __init__(self, client: FakeClient, report: dict):
        self.client = client
        self.report = copy.deepcopy(report)
        self.refuse: dict = {}
        self.route: dict = {}
        self.frozen = False
        self.silent = False
        self.writes: list[dict] = []
        self.lock = threading.Lock()
        client.responder = self.respond

    def respond(self, topic, body):
        pr = body.get('print') if isinstance(body.get('print'), dict) else None
        if body.get('pushing', {}).get('command') == 'pushall':
            with self.lock:
                return {'print': copy.deepcopy(self.report)}
        if pr is None or pr.get('command') != 'ams_filament_setting':
            return None
        self.writes.append(pr)
        key = (int(pr['ams_id']), int(pr['tray_id']))
        reply = {'command': 'ams_filament_setting', 'sequence_id': pr['sequence_id'], 'result': 'success',
                 'reason': ''}
        if key in self.refuse:
            return {'print': dict(reply, **self.refuse[key])}
        out = [] if self.silent else [{'print': reply}]
        if not self.frozen:
            delta = self._apply(self.route.get(key, key), pr)
            if delta is not None:
                out.append({'print': delta})
        return out or None

    def _apply(self, key, pr) -> dict | None:
        ams_id, tray_id = key
        with self.lock:
            vt = self.report.get('vt_tray')
            if isinstance(vt, dict) and str(vt.get('id')) == str(ams_id):
                self._set(vt, pr)
                return {'vt_tray': copy.deepcopy(vt)}
            units = self.report.get('ams', {}).get('ams', [])
            for u in units:
                if str(u.get('id')) != str(ams_id):
                    continue
                for t in u.get('tray', []):
                    if str(t.get('id')) == str(tray_id):
                        self._set(t, pr)
                        return {'ams': {'ams': copy.deepcopy(units)}}
        return None

    @staticmethod
    def _set(tray: dict, pr: dict) -> None:
        for k in SETTING_FIELDS:
            if k in pr:
                v = pr[k]
                tray[k] = str(v) if k.startswith('nozzle_temp') else v   # the printer reports temps as strings

    def push(self, delta: dict) -> None:
        """The printer reports a change of its own (e.g. a print starts): merge it and send it."""
        with self.lock:
            for k, v in delta.items():
                self.report[k] = copy.deepcopy(v)
        self.client.deliver({'print': delta})

    def tray(self, ams_id, tray_id) -> dict:
        with self.lock:
            vt = self.report.get('vt_tray')
            if isinstance(vt, dict) and str(vt.get('id')) == str(ams_id):
                return copy.deepcopy(vt)
            for u in self.report.get('ams', {}).get('ams', []):
                if str(u.get('id')) == str(ams_id):
                    for t in u.get('tray', []):
                        if str(t.get('id')) == str(tray_id):
                            return copy.deepcopy(t)
        raise KeyError((ams_id, tray_id))
