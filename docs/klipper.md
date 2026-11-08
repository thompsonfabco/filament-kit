# Klipper printers

filament-kit works with Klipper printers that run Moonraker (Mainsail, Fluidd and most vendor screens use it), next to
Bambu printers. The app, the phone web app, the tag reader and the Claude tools show both kinds the same way: each
printer's slots, the spool in each, loading a spool into a slot, the camera, pause / resume / stop and a usage log.

What it needs:

- the **klipper** module (`sudo filament-kit modules enable klipper`; it needs the server module);
- the printer's Moonraker reachable from the kit server (port 7125);
- Moonraker's `[spoolman]` section pointing at the kit's Spoolman, so filament usage is recorded (the printer pack can
  set it, see below).

## Add a printer

On the kit server:

    sudo filament-kit klipper add "Workshop Printer" printer.home.arpa

It prints what the printer is: the model (from the kit's printer data file), its filament system (one extruder, a
toolchanger, an AFC unit such as a Box Turtle, a Happy Hare MMU), and its slots. Use the printer's host name when it
has one; an address works too.

- **Not sure of the address?** `sudo filament-kit klipper scan` looks for Moonraker on the server's own network (at
  most 256 addresses, only when you run it). Printers that announce themselves (Moonraker's `[zeroconf]`) appear by
  themselves.
- **Moonraker asks for an API key?** `sudo filament-kit klipper api-key <id>` asks for it; it is never shown again.
- The server's API can add one too (`POST /api/printers` with `family: "klipper"` and `host`); the Android app has
  no Add screen for Klipper printers yet, but shows them once added.

## Slots and spools

A Klipper printer's slots are its tools or lanes:

| Filament system | Slots | How the kit sets a slot's spool |
|---|---|---|
| One extruder | `T0` | `SET_ACTIVE_SPOOL ID=<spool>` |
| Toolchanger / IDEX (needs the printer pack) | one per tool, e.g. `L`, `C1` … `C6` | `FK_SET_TOOL_SPOOL TOOL=<n> ID=<spool>` |
| AFC (Box Turtle …) | one per lane | `SET_SPOOL_ID LANE=<lane> SPOOL_ID=<spool>` |
| Happy Hare | `G0`, `G1` … | `MMU_GATE_MAP GATE=<n> SPOOLID=<spool>` |

Loading a spool from the app or the reader sends that gcode and waits up to 10 seconds for the printer to show the
spool; only then does Spoolman's location change (to `<printer name> – <slot>`, and the spool that was there goes
back to its shelf). Loading is refused while the printer prints; pause it first.

The kit also follows the printer: when a slot's spool changes on the printer itself (a tag tapped on a reader there,
the touchscreen, a macro, an AFC or Happy Hare lane change), Spoolman's locations are updated the same way.

## Filament usage

Moonraker deducts the filament it uses from the active spool in Spoolman while it prints (its own `[spoolman]`
support). The kit only records each finished job in the printer's usage log; those entries cannot be undone from the
kit (correct the spool in Spoolman instead). The printer status warns when Moonraker reports usage to another
Spoolman, or to none.

On a multi-tool printer Moonraker charges only one spool at a time, so the active spool must follow the tool: the
printer pack's `_FK_TOOL_CHANGED T=<n>` does that; add it to the end of your tool-change macro. AFC and Happy Hare do
this themselves.

## Slicer presets

For each load the kit names the OrcaSlicer preset it built for that filament, printer and nozzle (when the profiles
module made one). The **Spool Sync** OrcaSlicer plugin (`integrations/orca-spool-sync/`) selects those presets in
Orca's filament slots: for a multi-tool printer it reads Moonraker's `lane_data`, which the kit publishes for
toolchangers (`sudo filament-kit klipper set <id> --lane-data auto|on|off`; never on AFC printers, AFC writes it
itself). OrcaSlicer's own "Sync filaments" reads `lane_data` too.

## The printer pack (optional, runs on the printer)

The kit talks to Moonraker without installing anything on the printer. The printer pack adds what a printer may lack:

- per-tool spools for toolchangers and IDEX printers, and `SET_ACTIVE_SPOOL` / `CLEAR_ACTIVE_SPOOL` when there are
  none;
- a spool check at print start (warn or cancel when the sliced filament differs from the active spool) and the active
  spool's load temperature (both need Klipper's `gcode_shell_command` extra);
- an NFC tag reader on the printer (nfc2klipper with a PN532) and the read-only `lasttag` service the kit reads taps
  from;
- Moonraker settings: report usage to the kit's Spoolman, announce Moonraker on the network.

`sudo filament-kit klipper pack` prints the command to run on the printer (as its normal user):

    curl -fsSL https://github.com/thompsonfabco/filament-kit/releases/latest/download/fk-printer-pack.tar.gz | tar xz
    sh fk-printer-pack/fk-printer-pack.sh install

It asks about each part and before every change, never overwrites a file it did not write, and makes a backup before
its only edits to your own files: one `[include filament-kit/*.cfg]` line in `printer.cfg` and the `moonraker.conf`
sections. It restarts Klipper only when the printer is idle and you say yes. `status` shows what is installed;
`uninstall` removes it again. An nfc2klipper that is already installed is checked against the pack's version but
never changed.

## Printer models

What the kit knows about Klipper printer models (how to recognise them, their slots, their OrcaSlicer printer names,
their light and scan-feedback macros) lives in `klipper_hardware.xml`, not in the program. To add or correct a model,
put an override in `/etc/filament-kit/klipper_hardware.xml` with a higher `version` than the kit's own file; the
server rereads it, and the updater can deliver newer data. A printer no entry matches works as a generic Klipper
printer (its state says `unknown_model`).

- **Sovol SV08 MAX**: verified.
- **Sovol M1D**: an unverified placeholder (seven tools: `L` and `C1` … `C6`). Sovol has not published its firmware
  yet; when the printer is in hand, `python tools/capture_klipper.py --host <printer> --out m1d` records what is needed
  (read only) to fill the entry in.
