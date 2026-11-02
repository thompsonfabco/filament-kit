# filament-kit Bambu bridge part 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin every printer's TLS certificate; map each printer's AMS slots automatically (slot test + gcode-only calibration job); load a spool into a slot from the app; deduct filament used by each finished print from Spoolman.

**Architecture:** New modules in `server/filament_kit/bridge/` (`tlspin`, `ams`, `slottest`, `calib3mf`, `ftps`, `usage`, `loading`) on top of part 1's registry / connection Manager / camera Hub; per-printer state files under `paths().state / "printers" / <serial>/`. Ported from the owner's proven H2D code: `C:\CODING\h2d-filament-scanner\usage\usage_tracker.py` (FTPS with session reuse, name-based 3MF lookup, slice_info parsing, mc_percent scaling) and `orchestrator/server.py` (`ams_filament_setting`, preset matching, location bookkeeping). App: spool card "Load into printer", Printers "Map slots" and "Filament used" history with Undo.

**Tech Stack:** Python 3.12+ (paho-mqtt, ftplib, zipfile, stdlib xml), existing Starlette API; Kotlin/Compose app.

**Spec:** `docs/superpowers/specs/2026-11-01-filament-kit-design.md` section 5 ("Slot mapping", "Loading a spool", "Usage tracking", "Prototype on the owner's H2D first"), section 7 (bridge error handling), section 8 (fake printer tests).

## Global Constraints

- Never use a Generic preset: loading sends `tray_info_idx` = the owner's own generated Bambu Studio preset `filament_id` for that line × printer model × nozzle; no match → refused (`409 no_preset`). The preset lookup is an interface (`profiles.preset_for(filament: dict, model: str, nozzle_mm: float) -> PresetRef | None`); until the profiles plan lands it returns None (loading always refuses with a clear message). Do not invent preset ids.
- Printer TLS: trust-on-first-use per printer. The SHA-256 of the leaf (DER) seen on the first successful MQTT connect is stored in the registry (`cert_fp`); every later connection to that printer on 8883 (MQTT), 322 (RTSPS), 6000 (JPEG), 990 (FTPS) must present that leaf, else state `cert_changed` and no Access Code is sent. Re-adding the printer with its code (`POST /api/printers`, CLI add) clears the pin. Verified on the owner's H2D 2026-11-01: one leaf on all four ports, `CN=<serial>`; also check CN == serial when present.
- Access Codes: never logged, returned, or on a command line (as part 1).
- Printer-changing actions (slot test, calibration job, loading) run only while the printer is idle (`gcode_state` not RUNNING/PAUSE/PREPARE/SLICING) and connected; otherwise `409 printer_busy` / `409 printer_offline`.
- Slot test and calibration always restore every slot they changed and verify the restore from the next report; on any failure they restore what they can and report each slot not confirmed.
- Calibration 3MF: gcode is only comments and `M400` — no heating, homing, moves or `T` commands; print flags `bed_levelling`, `flow_cali`, `vibration_cali`, `layer_inspect`, `timelapse` all false; `use_ams` true; uploaded to `/cache/fk-calib-<serial>.gcode.3mf`, deleted afterwards.
- Usage: never settle a FINISH/FAILED already present in the first report after connect; deduction = `used_g × final mc_percent / 100` per plate filament; written to Spoolman via `PUT /spool/{id}/use {use_weight}`; every deduction logged in `state/printers/<serial>/usage.jsonl` and undoable for 7 days (`use_weight` negative). Printers without a confirmed calibration stay in **observe mode** (log only, `observe: true` in the entry, nothing written).
- API additions (Bearer): `POST /api/printers/{id}/map` → starts slot test + calibration, returns `{job_id}`; `GET /api/printers/{id}/map` → `{state: "none"|"running"|"done"|"failed", step, slots: [{label, ams_id, tray_id, global}], calibrated: bool, observe: bool, problems: [...]}`; `POST /api/printers/{id}/slots/{label}/load {spool_id, dry_run}` → `{spool, slot, preset}` (409 `no_preset`, `printer_busy`, `printer_offline`, 404 `not_found`); `POST /api/printers/{id}/slots/{label}/unload {dry_run}`; `GET /api/printers/{id}/usage?days=7` → `{entries: [{id, at, job, grams, spool_id, slot, observe, undone}]}`; `POST /api/usage/{entry_id}/undo` → `{entry}` (409 `too_old` after 7 days, `already_undone`). New state `cert_changed` in printer state (app shows "The printer's certificate changed — add it again with its Access Code").
- Spoolman location for a loaded spool: `"<printer name> – AMS <label>"` (en dash, as part 1's status join); previous location kept in `extra.prev_location`; the spool previously in that slot gets its `prev_location` back (or "Sealed stock" if none).
- Tests: a fake printer (fake paho client from part 1 + a fake FTPS server built on `pyftpdlib` in tests only) replays reports; no test touches real hardware. Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Hardware checks (Task 9) only on the owner's H2D, idle, with the owner's explicit OK for each step; the owner types the Access Code.

## Review Focus

1. A LAN host announces itself as a printer (spoofed SSDP) after the printer was offline → the pinned leaf doesn't match → `cert_changed`, no Access Code sent on any port (test in Task 1).
2. The printer starts a print (or goes offline) in the middle of the slot test → stop, restore what was changed, report each unconfirmed slot; never leave a test colour in a slot silently (test in Task 3).
3. The server restarts while a print is RUNNING and then it FINISHes → the deduction happens once; a FINISH already present right after connect is never settled (test in Task 5).
4. The 3MF can't be found by name (renamed on the SD card / printed from Studio's cloud cache) → no deduction, a logged `entry` with `error: "file_not_found"` and no guessing from the newest file (test in Task 5).
5. Two phones load different spools into the same slot at once → one wins, the other gets the new state; Spoolman locations stay consistent (only one spool at a slot location) (test in Task 6).

---

### Task 1: Printer TLS pinning (server)

**Files:** Create `server/filament_kit/bridge/tlspin.py`; modify `registry.py` (`cert_fp` field, `pin()/clear_pin()`), `connection.py` (the leaf must be verified BEFORE the MQTT CONNECT carrying the Access Code is sent: open the TLS socket ourselves with `tlspin.connect(ip, 8883)`, check it, and hand the socket to paho through its socket hook; if the installed paho has no such hook, do a pre-flight handshake on 8883 and check it immediately before `connect()`, and also re-check the live socket's leaf in `on_connect`, dropping the connection on mismatch), `camera.py` (relay upstream + port 6000), `api.py` + `cli.py` (re-add clears the pin), new state `cert_changed`; tests `test_tlspin.py`.

**Interfaces:**
- Produces: `tlspin.leaf_fp(ip, port, timeout=5) -> str` (SHA-256 hex of the DER leaf, raises `OSError`); `tlspin.check(printer, port) -> None` (raises `CertChanged(expected, actual)`; pins on first use when `printer.cert_fp` is empty and the leaf CN, if present, equals the serial); `tlspin.context()` (TLS client context without CA verification, used only together with `check`).
- [ ] **Step 1: Failing tests** — first connect pins; a different leaf later → `CertChanged`, Manager state `cert_changed`, the fake client never receives the password; camera relay and MJPEG refuse with `cert_changed`; re-add via API clears the pin and re-pins; a leaf whose CN is another serial is refused even on first use; the fingerprint never includes the code in logs.
- [ ] **Steps 2–4:** RED → implement → GREEN (full server suite). **Step 5:** Commit `feat(bridge): per-printer TLS pinning`.

### Task 2: AMS model and slot map store (server)

**Files:** Create `bridge/ams.py`; tests `test_ams.py` (use `tests/data/h2d_pushall.json`).

**Interfaces:**
- Produces: `ams.units(report) -> list[Unit]` (`Unit(ams_id:int, kind:"ams"|"ams_ht"|"ams_lite", label:str, slots:list[Slot])`, `Slot(tray_id:int, label:str, global_id:int|None, type:str, color:str, preset:str)`; labels A1–D4 by unit order for 4-slot units, HT-A… for HT units (ams_id ≥ 128), "Ext" for the external spool holder (`vt_tray`, global 254/255)); `ams.SlotMap` dataclass (`slots: dict[label, {ams_id, tray_id, global_id}]`, `calibrated: bool`, `observe: bool`, `updated`); `ams.load_map(serial)`, `ams.save_map(serial, map)` (atomic, `state/printers/<serial>/slotmap.json`, state-owner chown as part 1); `ams.default_global(ams_id, tray_id)` = part 1's best guess (4-slot: `ams_id*4+tray_id`; HT: `ams_id`), used until calibrated.
- [ ] **Step 1: Failing tests** — H2D pushall → A1–A4 + HT-A/B/C with ams_id/tray_id; a P1S-style single AMS; an X1 with two AMS → A1–B4; external spool; map round-trips; default_global for 4-slot and HT.
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(bridge): AMS model and slot map`.

### Task 3: Slot test (server)

**Files:** Create `bridge/slottest.py`; modify `connection.py` (`Manager.set_slot(serial, ams_id, tray_id, setting) -> reply`, publishing `ams_filament_setting` exactly as `orchestrator/server.py` does, and `Manager.wait_report(serial, predicate, timeout)`); tests `test_slottest.py`.

**Interfaces:**
- Consumes: `ams.units`, `Manager`.
- Produces: `slottest.run(manager, serial, on_step) -> SlotTestResult` (`confirmed: dict[label, {ams_id, tray_id}]`, `restored: bool`, `problems: list[str]`): idle check; snapshot every slot's `tray_info_idx`, `tray_color`, `tray_type`, temps; for each slot write the snapshot setting with a unique colour `FK<nn>00FF` and confirm the report shows it on that unit/tray within 10 s; then restore every slot to its snapshot and confirm. Aborts and restores if the printer becomes busy or offline. An empty slot is written and restored like any other.
- [ ] **Step 1: Failing tests** (fake printer that applies `ams_filament_setting` to its report) — all slots confirmed and restored; printer starts printing mid-test → abort, restore, problems list names the unconfirmed slots; a slot whose write is refused (`result: fail` with auth reason) → `needs_developer_mode`, restore the rest; restore failure reported, never silent.
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(bridge): slot test`.

### Task 4: FTPS client and calibration job (server)

**Files:** Create `bridge/ftps.py` (port `ImplicitFTP_TLS` with data-channel session reuse from `usage_tracker.py`; uses `tlspin.check` on 990), `bridge/calib3mf.py`; tests `test_ftps.py`, `test_calib3mf.py` (fake FTPS server via `pyftpdlib` + TLS in tests; add `pyftpdlib` to the test extra).

**Interfaces:**
- Produces: `ftps.Client(printer)` context manager with `upload(path, bytes)`, `download(path) -> bytes`, `nlst(dir) -> list[str]`, `delete(path)`; `calib3mf.build(slots: list[label]) -> bytes` (a valid Bambu 3MF: `[Content_Types].xml`, `_rels/.rels`, `3D/3dmodel.model` minimal, `Metadata/plate_1.gcode` (comments + `M400`), `Metadata/plate_1.gcode.md5`, `Metadata/slice_info.config` with one `<filament id="i" tray_info_idx="" type="PLA" color="#..." used_g="0" used_m="0"/>` per slot, `Metadata/model_settings.config`, `Metadata/project_settings.config` minimal); `calib3mf.run(manager, serial, slotmap) -> CalibResult` (`decoding: dict[label, global_id]`, `consistent: bool`, `problems`): upload, publish `project_file` with `ams_mapping` (filament i → the slot's candidate global id from `default_global`), flags off, wait for the job to start and end (≤ 120 s), record `mapping` / `tray_now` from reports, compare, delete the file, restore slots.
- [ ] **Step 1: Failing tests** — the built 3MF opens with zipfile, has N filaments and gcode with no G0/G1/G28/M104/M109/M140/M190/T lines; upload/download/nlst/delete against the fake FTPS (session reuse required by the fake, like the real printer); calibration with a fake printer that echoes the mapping → `consistent: true` and decoding recorded; a printer that refuses the job → `consistent: false`, problem "printer refused the calibration job", file deleted; FTPS leaf mismatch → `cert_changed`.
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(bridge): FTPS client and calibration job`.

### Task 5: Usage tracking (server)

**Files:** Create `bridge/usage.py`; modify `connection.py` (hand job lifecycle events to a listener), `__main__.py` (start the tracker), `spoolman.py` (`use(spool_id, grams)` → `PUT /spool/{id}/use`); tests `test_usage.py` (fixtures: a real-shaped `slice_info.config` from the owner's H2D test 3MF format in `usage_tracker.py` docstring; build 3MFs in tests).

**Interfaces:**
- Consumes: `ftps.Client`, `ams.load_map`, Spoolman, registry.
- Produces: `usage.Tracker(manager, spoolman)` — per printer: remember the job (`subtask_name`, plate, `mapping`) while RUNNING; on FINISH/FAILED (not the first report after connect) fetch the 3MF by name (`<subtask_name>[_plate_<n>].gcode.3mf` in `/` then `/cache`, then an NLST name match — never newest-file), parse filaments, scale by final `mc_percent`, map each filament's global slot (from the print's `mapping`) → label via the calibrated map → the spool whose location is `"<printer> – AMS <label>"`, deduct (or log only in observe mode / uncalibrated), append to `usage.jsonl`; `usage.entries(serial, days)`; `usage.undo(entry_id)` (≤ 7 days, once). API routes from Global Constraints.
- [ ] **Step 1: Failing tests** — a finished 2-colour print deducts the right grams from the right spools; cancelled at 40 % deducts 40 %; FINISH seen right after (re)connect is not settled; restart mid-print then FINISH → exactly one deduction; 3MF not found → entry with `error: "file_not_found"`, nothing written; observe mode → entry `observe: true`, nothing written; undo restores the weight once, second undo 409, > 7 days 409 `too_old`; no spool at a slot → entry `spool_id: null`, nothing written.
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(bridge): usage tracking`.

### Task 6: Loading and unloading a spool (server)

**Files:** Create `bridge/loading.py`, `server/filament_kit/profiles.py` (stub interface: `PresetRef(filament_id: str, name: str, nozzle_temp_min: int|None, nozzle_temp_max: int|None)`, `preset_for(filament, model, nozzle_mm) -> PresetRef | None` returning None until the profiles plan), modify `api.py`; tests `test_loading.py`.

**Interfaces:**
- Consumes: `ams`, `Manager.set_slot`, `inventory` (Spoolman writes under the inventory lock), `profiles.preset_for`.
- Produces: `loading.load(manager, sm, serial, label, spool_id, dry) -> dict` and `loading.unload(...)`: idle + connected checks; nozzle size from the report (`nozzle_diameter`, per extruder on H2D/X2D — the slot's extruder from `ams.units`); preset lookup → None → `NoPreset`; `ams_filament_setting` with `tray_info_idx`, `tray_color` (Spoolman `color_hex` + "FF"), `tray_type` (material), nozzle temps from the preset; verify the next report; Spoolman: target spool location `"<printer> – AMS <label>"` with `prev_location`, previous occupant restored; dry run returns the plan without writing. Serialised per printer slot.
- [ ] **Step 1: Failing tests** (fake printer, fake Spoolman, a fake `preset_for`) — load writes the right command and locations; dry run writes nothing; no preset → 409 `no_preset` and nothing sent; busy → 409 `printer_busy`; previous occupant moved back; concurrent loads into one slot → one wins, Spoolman has exactly one spool at that location; unload only moves the spool back in Spoolman and leaves the printer's slot setting untouched (assert no MQTT command is sent).
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(bridge): load and unload spools`.

### Task 7: Mapping job API + CLI (server)

**Files:** Create `bridge/mapping.py` (orchestrates Task 3 + Task 4 as one background job per printer, persists progress, saves the SlotMap with `calibrated`/`observe`), modify `api.py`, `cli.py` (`filament-kit printer map <serial>` runs it with progress; `filament-kit printer unpin <serial>` clears the certificate pin), `README.md` (what "Map slots" does, that it briefly changes slot colours and runs a no-motion job); tests `test_mapping.py`, `test_api_bridge2.py`.

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces: the `map`, `load`, `unload`, `usage`, `undo` routes in Global Constraints; one mapping job per printer at a time (409 `already_running`); mapping refused while busy; on success `calibrated: true, observe: false`; on calibration inconsistency `calibrated: false, observe: true` with the reason in `problems`.
- [ ] **Step 1: Failing tests** — route shapes and error codes; job progress visible via GET; CLI map prints steps; unpin clears `cert_fp`; no route returns an Access Code.
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(api): slot mapping, loading and usage routes`.

### Task 8: App — load into printer, map slots, filament used (Android)

**Files:** Modify `net/Api.kt`/`Models.kt` (new routes, `cert_changed`), `ui/spool/SpoolCard.kt` (+ "Load into printer": printer list → slot picker from `GET /api/printers/{id}` AMS slots → preview (`dry_run`) → confirm), `ui/printers/PrinterScreen.kt` (+ "Map slots" with a confirm dialog explaining the colour flicker and no-motion job, progress from `GET /map`, result; observe-mode notice; "Filament used" list with Undo), `PrinterHelp` messages (`no_preset`: "No preset for this filament on this printer yet — profiles come next", `printer_busy`, `cert_changed`); tests `LoadFlowTest.kt` (JVM VM tests), `ApiBridge2Test.kt`.

**Interfaces:**
- Consumes: Task 7 routes.
- Produces: the UI flows above; every write previews with `dry_run=true` first, confirms with `false`.
- [ ] **Step 1: Failing tests** — VM: load preview → confirm; `no_preset` message; busy message; map job progress polling stops when done; undo confirms and updates the list; `cert_changed` state text.
- [ ] **Steps 2–4:** RED → implement → GREEN (`testDebugUnitTest lintDebug assembleDebug`). **Step 5:** Commit `feat(android): load into printer, map slots, filament used`.

### Task 9: Hardware checks on the owner's H2D (owner present)

Each step needs the owner's explicit OK at that moment; the H2D must be idle; never a real print, never heating or motion.
- [ ] **Step 1:** TLS pin recorded on connect; `printer unpin` + re-add works.
- [ ] **Step 2:** Slot test on the H2D (writes test colours to every slot, restores them) — compare every slot's preset/colour/type before vs after (must be identical); the owner's own h2d-scanner service sees the same settings afterwards.
- [ ] **Step 3:** Calibration job: confirm the firmware accepts the unsigned gcode-only job (no heating/plate check), record `mapping`/`tray_now`, compare with `default_global`; job ends by itself; file deleted.
- [ ] **Step 4:** Record results in `docs/android-e2e.md` (bridge part 2 section) and set the H2D's `observe` per the result. Commit `test: bridge part 2 hardware checks (H2D)`.

## Execution waves (parallel where independent)

W1: Tasks 1, 2 · W2: Tasks 3, 4, 6 · W3: Tasks 5, 7 · W4: Task 8 · W5: Task 9 (owner present).
