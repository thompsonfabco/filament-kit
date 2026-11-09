#!/usr/bin/env python3
"""filament-kit printer pack: the on-printer side of filament-kit for Klipper printers (spec §7).

Run on the printer as its normal user (not root): `./fk-printer-pack.sh install | status | uninstall`.
Python 3.9+, standard library only.

Parts (install asks for each; --parts picks them without asking which):
  spool      config/filament-kit/fk_spool.cfg: per-tool spools (FK_SET_TOOL_SPOOL, _FK_TOOL_CHANGED), scan feedback
             hooks; plus fk_active_spool.cfg (SET_ACTIVE_SPOOL / CLEAR_ACTIVE_SPOOL) only if the printer has none
  check      spool check at print start (FK_SPOOL_CHECK, _FK_SPOOL_CHECK); needs gcode_shell_command
  loadtemp   the active spool's load temperature (_FK_LOAD_LOOKUP); needs gcode_shell_command
  nfc        nfc2klipper (bofh69) at the pinned commit + the kit's patches; an existing ~/nfc2klipper is ADOPTED
             (compared, never changed)
  lasttag    the read-only :5002 last-tag service the kit's tag sources read (needs nfc)
  moonraker  moonraker.conf: [spoolman] server -> the kit's Spoolman, [zeroconf] on (each its own question)

Install and uninstall can be run again and again: the manifest lists each file and service once, a service the pack
installed but you keep stays in it (with its files), and an nfc2klipper the pack started installing is finished by
the next install.

Rules: it never overwrites a file it did not write (config/filament-kit/.manifest lists what it wrote). Its only
edits to your own files are one `[include filament-kit/*.cfg]` line in printer.cfg and the moonraker.conf sections
above, each shown as a diff and asked y/N, with a timestamped backup. A restart of Klipper (a macro changed) or of
Moonraker (moonraker.conf changed) is offered only while the printer is idle (print_stats standby / complete /
cancelled / error), each only when you say yes.
"""
import argparse
import datetime
import difflib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS = ("spool", "check", "loadtemp", "nfc", "lasttag", "moonraker")
SCRIPT_MOONRAKER = 'MOONRAKER = "http://localhost:7125"'    # the line in scripts/*.py that install replaces
INCLUDE = "[include filament-kit/*.cfg]"
SAVE_CONFIG = "#*# <---------------------- SAVE_CONFIG ---------------------->"
IDLE = ("standby", "complete", "cancelled", "error")
NFC_REPO = "https://github.com/bofh69/nfc2klipper.git"
PY39_PINS = ["requests<2.33", "gunicorn==23.0.0"]   # nfc2klipper's pins need Python 3.10+
SPOOLMAN_URL = re.compile(r"https?://[^\s\"'`$;&|<>()\\]+")      # one line of moonraker.conf: no spaces, no shell
SERVICE = re.compile(r"[A-Za-z0-9_.-]{1,64}")            # a manifest service entry: a plain unit name, nothing else
SERVICE_FILES = {"lasttag": ("lasttag/lasttag.py", "lasttag/allow")}   # files a kept service still needs
EMPTY = {"files": [], "include": False, "services": [], "asvc": [], "moonraker": [], "nfc": None}


class PackError(Exception):
    pass


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


class Pack:
    def __init__(self, data, moonraker="http://localhost:7125", home=None, ask=None, out=None, run=None,
                 klipper_dir=None, units_dir="/etc/systemd/system", prompt=None):
        self.units_dir = units_dir
        self.data = os.path.abspath(os.path.expanduser(data))
        self.cfg = os.path.join(self.data, "config")
        self.dest = os.path.join(self.cfg, "filament-kit")
        self.moonraker = moonraker.rstrip("/")
        self.home = home or os.path.expanduser("~")
        self.klipper_dir = klipper_dir or os.path.join(self.home, "klipper")
        self.ask = ask or (lambda q: input(q + " [y/N] ").strip().lower() in ("y", "yes"))
        self.prompt = prompt or _read_line
        self.out = out or print
        self.run = run or (lambda cmd, **kw: subprocess.run(cmd, check=True, **kw))
        self.manifest_path = os.path.join(self.dest, ".manifest")
        self.changed = False      # a Klipper config file was written or edited: a restart is needed
        self.moonraker_changed = False      # moonraker.conf was edited: Moonraker reads it only when it starts

    # --- Moonraker -------------------------------------------------------------------------------------------------
    def _get(self, path):
        with urllib.request.urlopen(self.moonraker + path, timeout=5) as r:
            return json.load(r)["result"]

    def objects(self):
        try:
            return set(self._get("/printer/objects/list")["objects"])
        except Exception as e:
            raise PackError("cannot reach Moonraker at {} ({}); is this the printer?".format(self.moonraker, e))

    def print_state(self):
        try:
            return self._get("/printer/objects/query?print_stats=state")["status"]["print_stats"]["state"]
        except Exception:
            return "unknown"

    # --- the manifest ----------------------------------------------------------------------------------------------
    def manifest(self):
        """The pack's manifest. The folder is writable through Moonraker's file API, so every entry is checked:
        files are relative paths inside the pack's folder, services plain unit names; others are dropped (said)."""
        try:
            with open(self.manifest_path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        m = json.loads(json.dumps(EMPTY))
        if not isinstance(raw, dict):
            return m
        for key in ("files", "services", "asvc", "moonraker"):
            for v in raw.get(key) or []:
                if not isinstance(v, str) or v in m[key]:
                    continue
                if key == "files" and not self._inside(v):
                    self.out("  manifest: ignoring the file entry {!r} (not inside the pack's folder)".format(v))
                    continue
                if key in ("services", "asvc") and not SERVICE.fullmatch(v):
                    self.out("  manifest: ignoring the service entry {!r} (not a plain unit name)".format(v))
                    continue
                m[key].append(v)
        m["include"] = raw.get("include") is True
        nfc = raw.get("nfc")
        if isinstance(nfc, dict) and nfc.get("dir") == self.nfc_dir() and nfc.get("state") in ("started", "done"):
            m["nfc"] = {"dir": nfc["dir"], "state": nfc["state"]}
        return m

    def _inside(self, rel):
        if os.path.isabs(rel) or not rel or "\\" in rel:
            return False
        full = os.path.normpath(os.path.join(self.dest, rel))
        return full.startswith(os.path.normpath(self.dest) + os.sep)

    @staticmethod
    def _add(lst, v):
        if v not in lst:
            lst.append(v)

    def save_manifest(self, m):
        os.makedirs(self.dest, exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1)

    def write(self, m, rel, text, mode=0o644):
        """Write a file of the pack (refuses a file that exists and is not the pack's own)."""
        path = os.path.join(self.dest, rel)
        if os.path.exists(path) and rel not in m["files"]:
            raise PackError("{} exists and was not written by the pack; not overwriting it".format(path))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, encoding="utf-8") as f:
                same = f.read() == text
        except OSError:
            same = False
        if not same and rel.endswith(".cfg"):
            self.changed = True
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, mode)
        self._add(m["files"], rel)

    def _read_pack(self, rel):
        with open(os.path.join(HERE, rel), encoding="utf-8") as f:
            return f.read()

    # --- edits to the owner's files -----------------------------------------------------------------------------
    def edit(self, path, new_text, why):
        """Show a diff of `path` → new_text and ask; on yes back the file up and write it. True when written."""
        try:
            with open(path, encoding="utf-8") as f:
                old = f.read()
        except FileNotFoundError:
            old = ""
        if old == new_text:
            return False
        diff = "".join(difflib.unified_diff(old.splitlines(True), new_text.splitlines(True), path, path + " (new)"))
        self.out("{}:\n{}".format(why, diff))
        if not self.ask("Change {}?".format(os.path.basename(path))):
            self.out("  left as it is")
            return False
        if old:
            shutil.copy2(path, "{}.bak-fk-{}".format(path, stamp()))
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        return True

    def add_include(self, m):
        path = os.path.join(self.cfg, "printer.cfg")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if INCLUDE in text:
            m["include"] = True
            return
        line = INCLUDE + "\n"
        if SAVE_CONFIG in text:
            i = text.index(SAVE_CONFIG)
            new = text[:i].rstrip("\n") + "\n\n" + line + "\n" + text[i:]
        else:
            new = text.rstrip("\n") + "\n\n" + line
        if self.edit(path, new, "printer.cfg needs one include line for the pack's macros"):
            m["include"] = True
            self.changed = True

    # --- parts -----------------------------------------------------------------------------------------------------
    def part_spool(self, m, objs, scan_ok, scan_unknown):
        text = self._read_pack("cfg/fk_spool.cfg")
        text = text.replace("@SCAN_OK@", scan_ok or 'M118 Spool {params.ID|default("?")} scanned')
        text = text.replace("@SCAN_UNKNOWN@", scan_unknown or 'RESPOND TYPE=error MSG="Tag matches no spool"')
        self.write(m, "fk_spool.cfg", text)
        if {"gcode_macro SET_ACTIVE_SPOOL", "gcode_macro CLEAR_ACTIVE_SPOOL"} & objs and \
                "fk_active_spool.cfg" not in m["files"]:
            self.out("  SET_ACTIVE_SPOOL / CLEAR_ACTIVE_SPOOL already present: the printer's own are kept")
        else:
            self.write(m, "fk_active_spool.cfg", self._read_pack("cfg/fk_active_spool.cfg"))
        self.out("  spool macros written. For a multi-tool printer, add this line at the end of your tool-change "
                 "macro (T0, T1 ...):\n    _FK_TOOL_CHANGED T=<the tool number>")

    def has_shell_command(self):
        return os.path.exists(os.path.join(self.klipper_dir, "klippy", "extras", "gcode_shell_command.py"))

    def _script(self, rel):
        """A pack script as it is installed: talking to this printer's Moonraker (--moonraker), not the default."""
        text = self._read_pack(rel)
        if SCRIPT_MOONRAKER not in text:
            raise PackError("{} in the pack does not name its Moonraker".format(rel))
        return text.replace(SCRIPT_MOONRAKER, "MOONRAKER = {}".format(json.dumps(self.moonraker)))

    def part_scripts(self, m, which):
        if not self.has_shell_command():
            self.out("  {}: skipped, Klipper has no gcode_shell_command extra (install it with KIAUH first)".format(
                which))
            return False
        scripts = os.path.join(self.dest, "scripts")
        if which == "check":
            self.write(m, "scripts/fk_spool_check.py", self._script("scripts/fk_spool_check.py"), 0o755)
            self.write(m, "fk_spool_check.cfg", self._read_pack("cfg/fk_spool_check.cfg").replace("@PACK@", self.dest))
            self.out("  spool check written: call _FK_SPOOL_CHECK FILAMENT=... VENDOR=... in your print start macro")
        else:
            self.write(m, "scripts/fk_load_temp.py", self._script("scripts/fk_load_temp.py"), 0o755)
            self.write(m, "scripts/fk_load_temp.sh", self._read_pack("scripts/fk_load_temp.sh"), 0o755)
            self.write(m, "fk_load_temp.cfg", self._read_pack("cfg/fk_load_temp.cfg").replace("@PACK@", self.dest))
            self.out("  load temperature written: _FK_LOAD_LOOKUP.temp holds the active spool's temperature")
        assert scripts
        return True

    def nfc_dir(self):
        return os.path.join(self.home, "nfc2klipper")

    def patches(self):
        d = os.path.join(HERE, "nfc2klipper", "patches")
        return [os.path.join(d, p) for p in sorted(os.listdir(d)) if p.endswith(".patch")]

    def pin(self):
        with open(os.path.join(HERE, "nfc2klipper", "PIN"), encoding="utf-8") as f:
            return f.read().strip()

    def nfc_status(self):
        """(present, lines) about an nfc2klipper checkout: its commit against the PIN and each patch's state."""
        d = self.nfc_dir()
        if not os.path.isdir(os.path.join(d, ".git")):
            return False, ["nfc2klipper: not installed"]
        def git(*a):
            return subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
        head = git("rev-parse", "HEAD").stdout.strip()
        lines = ["nfc2klipper: present at {} ({})".format(d, "the pinned commit" if head == self.pin()
                                                           else "commit {}, the pack pins {}".format(head[:7],
                                                                                                    self.pin()[:7]))]
        for p in self.patches():
            name = os.path.basename(p)
            if git("apply", "--check", "--reverse", p).returncode == 0:
                lines.append("  {}: applied".format(name))
            elif git("apply", "--check", p).returncode == 0:
                lines.append("  {}: not applied".format(name))
            else:
                lines.append("  {}: differs from the local changes (left as they are)".format(name))
        return True, lines

    def nfc_will_install(self, m):
        """Whether part_nfc is going to install or finish a reader, and so write its config: the same test it uses."""
        d = self.nfc_dir()
        nfc = m.get("nfc") or {}
        if self.nfc_status()[0]:
            return nfc.get("dir") == d and nfc.get("state") == "started"
        return not os.path.exists(d)

    def part_nfc(self, m, device, spoolman, web):
        d = self.nfc_dir()
        services = ["nfc2klipper_backend"] + (["nfc2klipper_api"] if web else [])
        mine = (m.get("nfc") or {}).get("dir") == d
        present, lines = self.nfc_status()
        if present and not (mine and m["nfc"]["state"] == "started"):
            self.out("  adopted, nothing changed:" if not mine else "  installed by the pack earlier:")
            for line in lines:
                self.out("  " + line)
            missing = [s for s in services if not os.path.exists(self.unit_path(s))
                       and os.path.exists(os.path.join(d, s + ".service"))]
            if missing:
                self.out("  its service(s) {} are not installed".format(", ".join(missing)))
                self.install_services(m, d, missing)
            return
        if os.path.exists(d) and not present:
            self.out("  {} exists but is not a git checkout of nfc2klipper; left alone (move it away to install)"
                     .format(d))
            return
        m["nfc"] = {"dir": d, "state": "started"}
        self.save_manifest(m)                 # a failure below is finished by the next install, never "adopted"
        if present:
            self.out("  finishing the nfc2klipper install the pack started in {}".format(d))
        else:
            self.out("  installing nfc2klipper into {}".format(d))
            self.run(["git", "clone", "-q", NFC_REPO, d])
        self.run(["git", "-C", d, "checkout", "-q", self.pin()])
        for p in self.patches():
            applied = subprocess.run(["git", "-C", d, "apply", "--check", "--reverse", p],
                                     capture_output=True).returncode == 0 if present else False
            if not applied:
                self.run(["git", "-C", d, "apply", p])
        self.run([sys.executable, "-m", "venv", os.path.join(d, "venv")])
        pip = [os.path.join(d, "venv", "bin", "pip"), "install", "-q", "-r", os.path.join(d, "requirements.txt")]
        if sys.version_info < (3, 10):
            cons = os.path.join(d, "constraints-fk.txt")
            with open(cons, "w", encoding="utf-8") as f:
                f.write("\n".join(PY39_PINS) + "\n")
            pip += ["-c", cons]
        self.run(pip)
        cfg_dir = os.path.join(self.home, ".config", "nfc2klipper")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(d, "nfc2klipper.cfg"), encoding="utf-8") as f:
            upstream = f.read()
        target = os.path.join(cfg_dir, "nfc2klipper.cfg")
        if os.path.exists(target):          # someone's own config (or an earlier run's): never overwritten
            target += ".fk-new"
            self.out("  {} exists; the pack's version is in {} for you to compare".format(target[:-7], target))
        with open(target, "w", encoding="utf-8") as f:
            f.write(nfc_config(upstream, device, spoolman, self.moonraker, web))
        if not spoolman:
            self.out("  no Spoolman URL given, so {} keeps the example's spoolman-url and tag lookups won't reach the "
                     "kit; set it there (--spoolman sets it on an install)".format(target))
        self.install_services(m, d, services)
        m["nfc"]["state"] = "done"

    def _stage(self, name, text):
        """A unit file staged for `sudo install` in a private temp folder (not printer_data, which Moonraker's
        file API can write), so what is installed is exactly what the pack wrote."""
        d = tempfile.mkdtemp(prefix="fk-pack-")
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def _unstage(self, path):
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def install_services(self, m, d, services):
        user = os.environ.get("USER") or os.path.basename(self.home)
        for s in services:
            if self.foreign_unit(m, s):
                continue
            with open(os.path.join(d, s + ".service"), encoding="utf-8") as f:
                unit = f.read()
            unit = re.sub(r"(?m)^User=.*$", "User=" + user, unit).replace("/home/pi/", self.home + "/")
            if not self.ask("Install the {} service (sudo systemctl enable --now)?".format(s)):
                continue
            tmp = self._stage(s + ".service", unit)
            try:
                self.run(["sudo", "install", "-m", "644", tmp, self.unit_path(s)])
            finally:
                self._unstage(tmp)
            self.run(["sudo", "systemctl", "daemon-reload"])
            self.run(["sudo", "systemctl", "enable", "--now", s])
            self._add(m["services"], s)
            self.asvc_add(m, s)

    def unit_path(self, service):
        return os.path.join(self.units_dir, service + ".service")

    def foreign_unit(self, m, service):
        """A systemd unit of that name that the pack did not install: adopted as it is, never replaced."""
        if os.path.exists(self.unit_path(service)) and service not in m["services"]:
            self.out("  {} is already installed (not by the pack): left as it is".format(service))
            return True
        return False

    def asvc_add(self, m, service):
        path = os.path.join(self.data, "moonraker.asvc")
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            text = ""
        if service in text.split():
            return
        with open(path, "a", encoding="utf-8") as f:
            f.write(("" if text.endswith("\n") or not text else "\n") + service + "\n")
        self._add(m["asvc"], service)

    def part_lasttag(self, m, allow):
        if not os.path.isdir(self.nfc_dir()):
            self.out("  lasttag: skipped, it needs nfc2klipper")
            return
        if self.foreign_unit(m, "lasttag"):
            return
        self.write(m, "lasttag/lasttag.py", self._read_pack("lasttag/lasttag.py"))
        allow_path = os.path.join(self.dest, "lasttag", "allow")
        try:
            with open(allow_path, encoding="utf-8") as f:
                before = f.read()
        except OSError:
            before = None
        if allow or before is None or "lasttag/allow" not in m["files"]:
            self.write(m, "lasttag/allow", "\n".join(["127.0.0.1"] + [a for a in allow if a]) + "\n")
        else:
            self.out("  lasttag: keeping its allow list (give --allow to change it)")
        with open(allow_path, encoding="utf-8") as f:
            changed = before is not None and f.read() != before
        unit = self._read_pack("lasttag/lasttag.service").replace("@USER@", os.environ.get("USER") or
                                                                  os.path.basename(self.home))
        unit = unit.replace("@PYTHON@", os.path.join(self.nfc_dir(), "venv", "bin", "python"))
        unit = unit.replace("@LASTTAG@", os.path.join(self.dest, "lasttag", "lasttag.py"))
        if "lasttag" in m["services"] and os.path.exists(self.unit_path("lasttag")):
            if changed and self.ask("lasttag's allow list changed; restart it to use the new one?"):
                self.run(["sudo", "systemctl", "restart", "lasttag"])
            return
        if self.ask("Install the lasttag service (port 5002, read only)?"):
            tmp = self._stage("lasttag.service", unit)
            try:
                self.run(["sudo", "install", "-m", "644", tmp, self.unit_path("lasttag")])
            finally:
                self._unstage(tmp)
            self.run(["sudo", "systemctl", "daemon-reload"])
            self.run(["sudo", "systemctl", "enable", "--now", "lasttag"])
            self._add(m["services"], "lasttag")
            self.asvc_add(m, "lasttag")

    def part_moonraker(self, m, spoolman):
        path = os.path.join(self.cfg, "moonraker.conf")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if spoolman:
            new = set_section(text, "spoolman", {"server": spoolman})
            if self.edit(path, new, "moonraker.conf: report filament usage to the kit's Spoolman"):
                self._add(m["moonraker"], "[spoolman] server: " + spoolman)
                self.moonraker_changed = True
                text = new
        else:
            self.out("  no Spoolman URL given, so [spoolman] is left as it is; usage only reaches the kit if it already "
                     "points there (--spoolman sets it)")
        if not has_section(text, "zeroconf"):
            new = text.rstrip("\n") + "\n\n[zeroconf]\n"
            if self.edit(path, new, "moonraker.conf: announce Moonraker on the LAN so filament-kit finds it"):
                self._add(m["moonraker"], "[zeroconf]")
                self.moonraker_changed = True

    def ask_spoolman(self):
        """The kit's Spoolman URL from the person installing, "" to leave it (--yes answers nothing: also ""). A wrong
        answer is asked again, not written into a config file."""
        for _ in range(3):
            url = self.prompt("The kit's Spoolman URL as this printer reaches it, e.g. "
                              "http://filament.home.arpa:7912 (empty: leave it)").strip()
            if not url or SPOOLMAN_URL.fullmatch(url):
                return url
            self.out("  that isn't an http:// or https:// URL")
        return ""

    # --- the commands ----------------------------------------------------------------------------------------------
    def install(self, parts, scan_ok="", scan_unknown="", nfc_device="tty:USB0:pn532", spoolman="", web=False,
                allow=()):
        if spoolman and not SPOOLMAN_URL.fullmatch(spoolman):
            raise PackError("the Spoolman URL must be one http:// or https:// address")
        for a in allow:
            try:
                ipaddress.ip_address(a)
            except ValueError:      # lasttag compares the caller's address with the list as text: a name never matches
                raise PackError("--allow takes IP addresses, not names: {}".format(a)) from None
        objs = self.objects()
        if not os.path.isfile(os.path.join(self.cfg, "printer.cfg")):
            raise PackError("no printer.cfg in {}; give --data <printer_data folder>".format(self.cfg))
        m = self.manifest()
        if not spoolman and ("moonraker" in parts or ("nfc" in parts and self.nfc_will_install(m))):
            spoolman = self.ask_spoolman()
        self.changed = False
        self.moonraker_changed = False
        for part in parts:
            self.out("[{}]".format(part))
            if part == "spool":
                self.part_spool(m, objs, scan_ok, scan_unknown)
            elif part in ("check", "loadtemp"):
                self.part_scripts(m, part)
            elif part == "nfc":
                self.part_nfc(m, nfc_device, spoolman, web)
                nfc = m.get("nfc") or {}        # the pack's own reader, this run's or an earlier one's; never an adopted one
                if nfc.get("dir") == self.nfc_dir() and nfc.get("state") == "done" and "fk_spool.cfg" not in m["files"]:
                    self.save_manifest(m)       # the reader is in, whatever the spool part says about its file
                    self.out("  the reader's gcode uses the spool part's macros: installing them too")
                    self.part_spool(m, objs, scan_ok, scan_unknown)
            elif part == "lasttag":
                self.part_lasttag(m, allow)
            elif part == "moonraker":
                self.part_moonraker(m, spoolman)
            self.save_manifest(m)
        if any(f.endswith(".cfg") for f in m["files"]):
            self.add_include(m)
        self.save_manifest(m)
        restart_klipper = self.changed and m["include"]
        if restart_klipper or self.moonraker_changed:
            state = self.print_state()      # once: while Klipper restarts, the state can't be read
            if restart_klipper:
                self.offer_restart(state)
            if self.moonraker_changed:      # after Klipper: Klipper's restart is asked for through Moonraker
                self.offer_moonraker_restart(state)
        return 0

    def offer_moonraker_restart(self, state):
        later = "sudo systemctl restart moonraker"
        if state not in IDLE:
            self.out("Moonraker must restart to use its new settings; the printer is {}, so restart it yourself later "
                     "({})".format(state, later))
            return
        if not self.ask("Restart Moonraker now to use its new settings?"):
            self.out("  restart it later ({})".format(later))
            return
        self._restart("/server/restart", "Moonraker", later)

    def _restart(self, path, what, later):
        req = urllib.request.Request(self.moonraker + path, data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except ConnectionError:     # not wrapped in URLError: it was sent, and a server may hang up as it restarts
            pass
        except OSError as e:
            self.out("  could not ask {} to restart ({}): restart it yourself ({})".format(what, e, later))
            return
        self.out("  {} is restarting".format(what))

    def offer_restart(self, state):
        if state not in IDLE:
            self.out("Klipper must restart to load the macros; the printer is {}, so restart it yourself later "
                     "(RESTART in the console)".format(state))
            return
        if not self.ask("Restart Klipper now to load the macros?"):
            self.out("  restart it later (RESTART in the console)")
            return
        self._restart("/printer/restart", "Klipper", "RESTART in the console")

    def status(self):
        objs = self.objects()
        m = self.manifest()
        self.out("filament-kit printer pack in {}".format(self.dest))
        self.out("  files: {}".format(", ".join(m["files"]) or "none"))
        self.out("  include line in printer.cfg: {}".format("yes" if m["include"] else "no"))
        for name in ("SET_ACTIVE_SPOOL", "CLEAR_ACTIVE_SPOOL", "FK_SET_TOOL_SPOOL", "FK_SPOOL_CHECK",
                     "_FK_LOAD_LOOKUP"):
            self.out("  {}: {}".format(name, "present" if "gcode_macro " + name in objs else "absent"))
        self.out("  gcode_shell_command: {}".format("present" if self.has_shell_command() else "absent"))
        for line in self.nfc_status()[1]:
            self.out("  " + line)
        if m["services"]:
            self.out("  services installed by the pack: " + ", ".join(m["services"]))
        return 0

    def _try(self, cmd):
        """Run a command of the uninstall; a failure (a unit already gone ...) is said, and the uninstall goes on."""
        try:
            self.run(cmd)
            return True
        except (subprocess.CalledProcessError, OSError) as e:
            self.out("  {} failed ({}); going on".format(" ".join(cmd), e))
            return False

    def uninstall(self):
        m = self.manifest()
        kept = []
        for s in m["services"]:
            if not self.ask("Remove the {} service the pack installed?".format(s)):
                kept.append(s)
                self.out("  {} kept (still listed in the pack's manifest)".format(s))
                continue
            self._try(["sudo", "systemctl", "disable", "--now", s])
            self._try(["sudo", "rm", "-f", self.unit_path(s)])
        if len(kept) < len(m["services"]):
            self._try(["sudo", "systemctl", "daemon-reload"])
        keep_files = [f for s in kept for f in SERVICE_FILES.get(s, ())]
        for rel in m["files"]:
            p = os.path.join(self.dest, rel)
            if rel not in keep_files and os.path.exists(p):
                os.remove(p)
        asvc = os.path.join(self.data, "moonraker.asvc")
        gone = [a for a in m["asvc"] if a not in kept]
        if gone and os.path.exists(asvc):
            with open(asvc, encoding="utf-8") as f:
                left = [l for l in f.read().splitlines() if l.strip() not in gone]
            with open(asvc, "w", encoding="utf-8") as f:
                f.write("\n".join(left) + "\n")
        if m["include"]:
            path = os.path.join(self.cfg, "printer.cfg")
            with open(path, encoding="utf-8") as f:
                text = f.read()
            new = re.sub(r"\n*" + re.escape(INCLUDE) + r"\n", "\n", text, count=1)
            self.edit(path, new, "printer.cfg: the pack's include line goes")
        if m["moonraker"]:
            self.out("moonraker.conf keeps what the pack changed (remove it by hand if you want): " +
                     "; ".join(m["moonraker"]))
        for d in (os.path.join(self.dest, "scripts"), os.path.join(self.dest, "lasttag")):
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        if kept:
            left = json.loads(json.dumps(EMPTY))
            left.update(files=keep_files, services=kept, asvc=[a for a in m["asvc"] if a in kept])
            self.save_manifest(left)
            self.out("the pack's manifest keeps what you kept: " + ", ".join(kept))
        elif os.path.exists(self.manifest_path):
            os.remove(self.manifest_path)
        if os.path.isdir(self.dest) and not os.listdir(self.dest):
            os.rmdir(self.dest)
        self.out("printer pack removed; restart Klipper (RESTART) to unload its macros")
        return 0


def _read_line(question):
    try:
        return input(question + ": ")
    except (EOFError, OSError):         # no terminal: nobody to answer
        return ""


def _is_header(line, section):
    """A `[section]` line, a trailing comment allowed; a commented-out one is not."""
    return re.fullmatch(r"\s*\[{}\]\s*([#;].*)?\s*".format(re.escape(section)), line) is not None


def has_section(text, section):
    return any(_is_header(line, section) for line in text.splitlines())


def set_section(text, section, values):
    """`text` (a Klipper/Moonraker config) with `values` set in `[section]` (added when missing)."""
    lines = text.splitlines(True)
    start = next((i for i, l in enumerate(lines) if _is_header(l, section)), None)
    if start is None:
        return text.rstrip("\n") + "\n\n[{}]\n".format(section) + "".join(
            "{}: {}\n".format(k, v) for k, v in values.items())
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    todo = dict(values)
    for i in range(start + 1, end):
        mm = re.match(r"\s*([A-Za-z0-9_]+)\s*[:=]", lines[i])
        if mm and mm.group(1) in todo:
            lines[i] = "{}: {}\n".format(mm.group(1), todo.pop(mm.group(1)))
    insert = "".join("{}: {}\n".format(k, v) for k, v in todo.items())
    return "".join(lines[:end]).rstrip("\n") + "\n" + insert + ("\n" if end < len(lines) else "") + "".join(lines[end:])


def _set_key(text, section, key, value):
    pat = re.compile(r"(?ms)(^\[{}\]\s*\n.*?)(^{}\s*=.*?$)".format(re.escape(section), re.escape(key)))
    if pat.search(text):
        return pat.sub(lambda mm: mm.group(1) + "{} = {}".format(key, value), text, count=1)
    return text.replace("[{}]\n".format(section), "[{}]\n{} = {}\n".format(section, key, value), 1)


def nfc_config(upstream, device, spoolman, moonraker, web):
    """nfc2klipper.cfg from the upstream example: the reader, Spoolman, Moonraker and the kit's gcode."""
    t = upstream
    t = _set_key(t, "webserver", "disable_web_server", "false" if web else "true")
    t = _set_key(t, "nfc", "nfc-device", json.dumps(device))
    if spoolman:
        t = _set_key(t, "spoolman", "spoolman-url", json.dumps(spoolman))
    t = _set_key(t, "moonraker", "moonraker-url", json.dumps(moonraker))
    t = _set_key(t, "moonraker", "always-send", "true")
    t = re.sub(r'(?ms)^setting_gcode = """.*?"""', 'setting_gcode = """\nSET_ACTIVE_SPOOL ID={spool}\n'
                                                  '_FK_SCAN_OK ID={spool}\n"""', t, count=1)
    t = re.sub(r'(?ms)^clearing_gcode = """.*?"""', 'clearing_gcode = """\n"""', t, count=1)
    return t


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fk-printer-pack.sh", description="filament-kit printer pack")
    ap.add_argument("command", choices=("install", "status", "uninstall"))
    ap.add_argument("--data", default="~/printer_data", help="the printer_data folder (default ~/printer_data)")
    ap.add_argument("--moonraker", default="http://localhost:7125")
    ap.add_argument("--klipper", default="", help="the Klipper folder (default ~/klipper; gcode_shell_command is looked "
                                                  "for in its klippy/extras)")
    ap.add_argument("--parts", help="comma list of " + ",".join(PARTS) + " (default: asked one by one)")
    ap.add_argument("--scan-ok", default="", help="gcode for a known tag (e.g. your LED macro, {params.ID} = spool)")
    ap.add_argument("--scan-unknown", default="", help="gcode for an unknown tag")
    ap.add_argument("--nfc-device", default="tty:USB0:pn532", help="nfcpy device of the reader")
    ap.add_argument("--spoolman", default="", help="the kit's Spoolman URL, e.g. http://filament.home.arpa:7912")
    ap.add_argument("--web", action="store_true", help="turn on nfc2klipper's web page (port 5001, no password)")
    ap.add_argument("--allow", default="", help="lasttag: comma list of IP addresses that may read it (the kit server)")
    ap.add_argument("--yes", action="store_true", help="answer yes to every question (for scripted installs)")
    a = ap.parse_args(argv)
    if os.geteuid() == 0 if hasattr(os, "geteuid") else False:
        print("run this as the printer's normal user, not root (it uses sudo where it must)", file=sys.stderr)
        return 1
    pack = Pack(a.data, a.moonraker, ask=(lambda q: True) if a.yes else None,
                prompt=(lambda q: "") if a.yes else None,
                klipper_dir=os.path.abspath(os.path.expanduser(a.klipper)) if a.klipper else None)
    try:
        if a.command == "status":
            return pack.status()
        if a.command == "uninstall":
            return pack.uninstall()
        if a.parts:
            parts = [p.strip() for p in a.parts.split(",") if p.strip()]
            bad = [p for p in parts if p not in PARTS]
            if bad:
                print("unknown part(s): " + ", ".join(bad), file=sys.stderr)
                return 1
        else:
            parts = [p for p in PARTS if pack.ask("Install part '{}'?".format(p))]
        return pack.install(parts, a.scan_ok, a.scan_unknown, a.nfc_device, a.spoolman, a.web,
                            [x.strip() for x in a.allow.split(",") if x.strip()])
    except PackError as e:
        print("error: {}".format(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
