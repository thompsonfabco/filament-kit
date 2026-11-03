# Every Bambu printer, every AMS layout: folding h2d-filament-scanner into filament-kit — design

Date: 2026-11-02. Status: awaiting owner approval. Sub-project 5 of the filament-ops merge; builds on branch
`merge-ops` (main merged in at 03ffc67).
Inputs: survey of `C:\CODING\h2d-filament-scanner` (orchestrator, usage tracker, /printer/ PWA, ESP32-C3 reader
firmware) and of kit's `bridge/` (models, status, ams, connection, mapping, slottest, calib3mf, loading, usage).

## 1. Purpose and success

One program drives every Bambu printer the owner (or a family member) has, with whatever AMS units are attached,
and the NFC reader on the bench works with all of them. Nothing is H2D-specific in code.

**Success:**
- A new Bambu printer on the LAN is found by itself (SSDP); the owner types its access code once (app, web page or
  CLI) and from then on its status, camera, slots, loading and filament usage work.
- Adding, removing or swapping AMS units (up to 16, any type) shows up in the slot lists within one report, with no
  config change; slot mapping re-runs by itself when the layout changed and the printer is idle.
- The reader shows Printer → Slot on the knob from lists the server sends; new printers or AMS changes never need a
  reflash.
- Hardware facts (models, AMS types, numbering, presence bits, external holders) live in one data file the server
  rereads when it changes; updating it needs no rebuild.
- No runtime use of Claude anywhere in this path.
- The owner's H2D keeps every behaviour it has today (exact preset or `no_preset`, queue-on-empty, usage deduction,
  camera, controls, alerts); its Spoolman records are migrated.

## 2. Decisions

| Topic | Decision |
|---|---|
| Where | kit `bridge/` is the one implementation; the three ops services are retired at cut-over |
| Hardware knowledge | `bambu_hardware.xml` (XML, the owner's format for data files): bundled default in the package + optional override `/etc/filament-kit/bambu_hardware.xml` (wins per element, matched by `code`/`id`); reread on mtime change; parsed with `defusedxml` (no entities, no external references) and checked against a bundled XSD-equivalent validator in code; bad file → keep last good, status shows the error |
| Updates | same channel as the spec library: optional daily fetch from the library repo/mirror (`hardware` section), with rollback; local override always wins |
| Unknowns in the file | the program never guesses silently: an unknown model gets a "generic Bambu" record (camera off, no chamber, 1 nozzle, legacy numbering, calibration required); an unknown AMS module gets a generic unit with the slot count from the report |
| Numbering schemes | named scheme kinds implemented in code (`linear`, `shift`), parameters in the file; which one a printer uses is **learned by calibration** (try every candidate scheme, keep the one the printer's reports confirm), the file only gives the first guess |
| Presence bits | layout described in the file per printer family; if a layout would collide (more units than the bitfield covers) presence falls back to `tray_type` and status says "presence layout unknown"; no assumed encodings |
| Externals | read `vir_slot[]` and `vt_tray`; one unit per holder; labels from the file (`Ext` for single-holder printers, keeping today's Spoolman locations; `Ext-L`/`Ext-R` for two-holder printers); slot command for externals: `tray_id = ams_id, slot_id = 0` (from the scanner, verified on the H2D) |
| Unit labels | spreadsheet style without limit: A…Z, AA, AB…; HT units HT-A…; AMS Lite/other kinds from the file |
| Preset rule | exact generated preset for (line, printer model, nozzle) or refuse `no_preset`; never Generic (kit already does this; kept and tested) |
| Reader | talks to the `web` process (public cert, ISRG root pinned as today) at `/<web path>/reader/*` with its own token; server sends printer and slot lists with display text and speech tokens |
| Remote /printer/ PWA | becomes a **Printers** tab of the web app, multi-printer, using kit's camera hub and controls; Web Push is a separate opt-in (needs internet egress: owner decides) |

## 3. The hardware data file (XML)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<bambu-hardware version="1">
  <models>
    <model code="O1D" name="H2D" preset-name="Bambu Lab H2D" nozzles="2" camera="hls" chamber-max="65"
           presence="bits-v1" gcode-only-failed-is-finish="true">
      <alias>H2D</alias>
      <light-node>chamber_light</light-node>
      <light-node>chamber_light2</light-node>
      <external id="254" label="Ext-L" say="external left"/>
      <external id="255" label="Ext-R" say="external right"/>
      <numbering ref="shift8"/>
      <numbering ref="legacy"/>
      <ftp-dir>/</ftp-dir>
      <ftp-dir>/cache</ftp-dir>
    </model>
    <model code="C12" name="P1S" preset-name="Bambu Lab P1S" nozzles="1" camera="mjpeg" presence="bits-v1">
      <external id="254" label="Ext" say="external"/>
      <numbering ref="legacy"/>
    </model>
    <!-- … every model now in bridge/models.py … -->
  </models>
  <ams-types>
    <ams-type key="ams" name="AMS" slots="4" label="letter"><ids from="0" to="127"/><module prefix="AMS"/></ams-type>
    <ams-type key="ams_2pro" name="AMS 2 Pro" slots="4" label="letter"><ids from="0" to="127"/><module prefix="N3F05"/></ams-type>
    <ams-type key="ams_ht" name="AMS HT" slots="1" label="ht"><ids from="128" to="253"/><module prefix="N3S"/></ams-type>
    <ams-type key="ams_lite" name="AMS Lite" slots="4" label="letter"><model code="N1"/><model code="N2S"/></ams-type>
  </ams-types>
  <numbering-schemes>
    <scheme key="legacy" kind="linear" per-unit="4" ht-from="128"/>
    <scheme key="shift8" kind="shift" bits="8"/>
  </numbering-schemes>
  <presence-layouts>
    <layout key="bits-v1" exist="tray_exist_bits" reading="tray_reading_bits">
      <range from="0" to="3" bit="id*4+tray"/>
      <range from="128" to="143" bit="16+id-128"/>
    </layout>
  </presence-layouts>
  <speech>
    <word text="HT" say="h t"/>
    <!-- letters and digits map to the reader's built-in words -->
  </speech>
</bambu-hardware>
```

- Keys and values above are the schema shape; real values come from the current `models.py`, the scanner and live
  reports. Values marked unverified in the survey (module codes for each AMS type, presence encoding beyond 4 units,
  numbering beyond AMS 0 and HT 128/129) ship as best-known and are confirmed or corrected by reports (section 6).
- `bit` expressions use a tiny fixed grammar (`id`, `tray`, integers, `+ - * <<`), parsed safely, never `eval`.
- `models.py` keeps its public functions (`camera_kind`, `printer_preset_name`, `chamber_max`) as thin readers of the
  file, plus `model(code) -> ModelInfo`.

## 4. Server changes (kit `bridge/` and friends)

1. **hardware.py** (new): load/validate/merge/reload the file; `ModelInfo`, `AmsType`, `Scheme`, `Presence`.
2. **Units and slots** (`ams.units`, `status._ams`, one shared builder): iterate `ams.ams[]` (any count), detect type
   (module code from `get_version` when known, else id range + tray count), label without limit, add externals from
   `vir_slot[]`/`vt_tray`, add `present`/`reading` from the presence layout. Additive API fields: unit `kind`,
   `type_name`; slot `present`, `reading`, `say`.
3. **Layout fingerprint**: (unit ids, types, slots) per printer; a change marks the slot map `stale`; the mapper
   re-runs when the printer is idle (config `auto_remap`, default on) and the app shows "re-mapping".
4. **Calibration** (`calib3mf`, `mapping`): send `ams_mapping` for each candidate scheme in turn (and `ams_mapping2`
   when the model lists it); accept the scheme whose reported mapping matches; save scheme + decoding per printer;
   two mismatched prints → `suspect` → re-map when idle. FAILED with no `print_error` for the gcode-only calibration
   job counts as finished when the model says so.
5. **Usage** (`usage.py`): decode `mapping` through the saved decoding, else the learned scheme; keep restart-safe
   settle, FAILED proportional, observe mode until calibrated; port the scanner's "learn an unseen number only when
   exactly one loaded slot matches" rule.
6. **Slot command** (`connection.slot_setting`): externals use `tray_id = ams_id`, `slot_id = 0`; driven by unit kind.
7. **Reader API** (web process, token-gated, LAN-only): `GET reader/printers` → `[{id, name, say}]`;
   `GET reader/printers/{id}/slots` → `[{label, say, kind, present, type, spool}]`; `POST reader/scan`
   `{uid, printer, slot, dry_run}` → statuses `set | queued | unknown_tag | unknown_spool | archived_spool | no_preset |
   offline | error` (scanner-compatible). Queue-on-empty ported (900 s TTL, settle 3 s, verify 4 s, 3 tries).
   Reader token: `filament-kit reader token` (root; prints once for the owner to put in `secrets.h`; stored hashed).
8. **MCP tools**: `printer_slots(printer=None)`, `printer_set_slot(spool, printer, slot, dry_run)`; `h2d_*` aliases kept
   for the owner's habits; slot labels are the kit labels (old "1-4/HT1/EXT-L" forms still accepted for the H2D via
   a compat parser).
9. **Printers tab (web app)**: status (SSE), camera (kit hub), controls (pause/resume/stop with confirm/lights from
   `light_nodes`), filament per unit, usage + re-map; multi-printer picker. Web Push: optional `web.push` (off).

## 5. Reader firmware (ESP32-C3)

- Removes `SLOTS[]`; on boot and every 60 s while lit fetches the printer list, then the selected printer's slots.
- Knob: rotate = slot; press = re-send last tag; hold 1 s = printer list (rotate, press to pick); hold 4 s = OTA check.
  Last printer + slot label saved in NVS (by label, so a layout change keeps the choice when it still exists).
- Display: printer name on the top line, slot label + contents below; long labels scroll.
- Speech: plays the server's `say` tokens from the built-in TI99 vocabulary (unknown token → beep), so new labels
  need only a data-file entry.
- Same signed OTA, pinned ISRG root, `secrets.h` (Wi-Fi + reader token); one reflash at cut-over, none afterwards.

## 6. Verifying the unverified (needs the owner's OK, read-only)

A one-off **read-only** capture from the live H2D on the VM (pushall + `get_version`, no commands that change
anything), using the VM's existing printer access, to confirm: module codes of the AMS 2 Pro and AMS HT units,
`vir_slot[]` shape, `tray_exist_bits`/`tray_reading_bits` with 1 AMS + 3 HT, and the shift8 values. The capture is
stored as a test fixture with the serial and IP replaced.

## 7. Migration of the owner's H2D (part of the cut-over runbook)

- Spoolman: "H2D - AMS slot N" → "H2D – AMS A<N>" (ams 0), "H2D - AMS HT N" → "H2D – AMS HT-<letter>",
  "H2D - External left|right" → "H2D – AMS Ext-L|Ext-R"; `extra.active_tray` cleared after the move (kept in a
  backup); `extra.prev_location` kept. Dry run first.
- Usage calibration: the scanner's learned table (shift8, values 0/2/32768/33024) seeds the kit slot map, so
  deduction continues without a new calibration print.
- Retire h2d-scanner (:8104), h2d-usage (:8106), h2d-remote (:8105) and the `/h2d/` + `/printer/` routes after the
  reader is reflashed; keep `/h2d/fw/` for OTA until the new firmware is in.

## 8. Network, security, owner decisions

- SSDP discovery needs the server to receive UDP 2021 / multicast 1990 on the LAN, and MQTT/FTPS/RTSP to each printer
  (8883/990/322/6000). On the owner's VM today only the scanner services may reach 192.0.2.109. **Every firewall,
  IPAddressAllow or pfSense change is listed in the runbook for the owner to apply; nothing changes them.**
- Access codes are typed by the owner (app/web/CLI), stored 600, never logged; the reader never sees them.
- Web Push (optional) needs egress to Apple/Google/Mozilla push hosts: owner decides.
- Reader token: hashed at rest; LAN-only routes plus token.

## 9. Testing

- pytest: hardware file load/validate/override/reload; units/labels for 0, 1, 4, 16 AMS units mixed with HT and
  externals; presence fallback on collision; scheme candidates in calibration (legacy, shift8); FAILED-as-finish;
  externals' slot command; reader API (lists, scan statuses, queue); migration of the H2D records; compat labels.
- Fixtures: the existing H2D reports plus the read-only capture; synthetic 16-unit reports.
- Firmware: unit tests for label/say parsing and menu state on the host (PlatformIO native), a build in CI; on-device
  test by the owner (reader flash = owner step).
- WSL: server with a fake MQTT printer (16 units) end to end through the reader API.
