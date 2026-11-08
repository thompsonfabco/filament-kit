"""Which model and filament system a Klipper printer is, from what Moonraker shows (spec §4.2).

`detect(objects, namespaces, hostname, hw) -> Detected`: a pure function. The models of `klipper_hardware.xml` are
tried in file order (an override's new models come after the bundled ones), `generic` last; a model matches when it
has at least one detect rule and every rule matches: each `<object>` is in the Klipper object list, each
`<namespace>` is a Moonraker database namespace, each `<hostname>` is an fnmatch pattern (case-insensitive) of the
printer's host name. No match → `generic`. The filament system is the model's own `system`, or for `system="auto"`
the first `<system>` in file order whose `detect-object` is an object or whose `detect-namespace` is a namespace,
else `single`. `reasons` says what matched, for the CLI and the API.

`probe(client, hw) -> Detected` asks Moonraker (object list, database namespaces, host name).
`save(d, path)` / `read(path)` keep the last result in `state/printers/<id>/detected.xml`.
"""
from __future__ import annotations

import fnmatch
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .. import xmlfile
from .hardware import Hardware


@dataclass(frozen=True)
class Detected:
    model_key: str
    system_key: str
    verified: bool
    hostname: str = ""
    reasons: list = field(default_factory=list, compare=False)


def _match(m, objects: set[str], namespaces: set[str], hostname: str) -> list[str] | None:
    rules = [("object", o, o in objects) for o in m.detect_objects]
    rules += [("namespace", n, n in namespaces) for n in m.detect_namespaces]
    rules += [("hostname", h, fnmatch.fnmatch(hostname.lower(), h.lower())) for h in m.detect_hostnames]
    if not rules or not all(ok for _, _, ok in rules):
        return None
    return [f"{kind} {value}" for kind, value, _ in rules]


def detect(objects, namespaces, hostname: str, hw: Hardware) -> Detected:
    objs, nss = set(objects or ()), set(namespaces or ())
    model, reasons = None, []
    for key, m in hw.models.items():
        if key == "generic":
            continue
        why = _match(m, objs, nss, hostname or "")
        if why is not None:
            model, reasons = m, why
            break
    if model is None:
        model = hw.model("generic")
        reasons = ["no model entry matched: generic Klipper printer"]
    system = model.system
    if system == "auto" or system not in hw.systems:
        system = "single"
        for key, s in hw.systems.items():
            if (s.detect_object and s.detect_object in objs) or (s.detect_namespace and s.detect_namespace in nss):
                system = key
                reasons = reasons + [f"filament system {key} ("
                                     f"{'object ' + s.detect_object if s.detect_object in objs else 'namespace ' + str(s.detect_namespace)})"]
                break
    return Detected(model.key, system, model.verified, hostname or "", reasons)


def probe(client, hw: Hardware) -> Detected:
    """Ask Moonraker and detect. Raises the client's errors (Offline, Unauthorized ...)."""
    info = client.info()
    return detect(client.objects(), client.db_namespaces(), str(info.get("hostname") or ""), hw)


def save(d: Detected, path: Path) -> None:
    root = ET.Element("detected", version="1", model=xmlfile.clean(d.model_key), system=xmlfile.clean(d.system_key),
                      verified="true" if d.verified else "false", hostname=xmlfile.clean(d.hostname))
    for r in d.reasons:
        ET.SubElement(root, "reason").text = xmlfile.clean(r)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    tmp.replace(path)


def read(path: Path) -> Detected | None:
    try:
        from defusedxml.ElementTree import fromstring
        root = fromstring(path.read_bytes(), forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception:  # noqa: BLE001 - missing or broken: detect again
        return None
    if root.tag != "detected" or not root.get("model"):
        return None
    return Detected(root.get("model"), root.get("system", "single"), root.get("verified") == "true",
                    root.get("hostname", ""), [(r.text or "") for r in root.findall("reason")])
