# filament-kit printer pack (Klipper)

The part of filament-kit that runs on a Klipper printer. The kit's server talks to Moonraker without it; the pack adds:

- per-tool spools for multi-tool printers (`FK_SET_TOOL_SPOOL`, `_FK_TOOL_CHANGED`), and `SET_ACTIVE_SPOOL` /
  `CLEAR_ACTIVE_SPOOL` when the printer has none;
- an optional spool check at print start and the active spool's load temperature (both need `gcode_shell_command`);
- optional nfc2klipper (a PN532 tag reader) at a pinned commit with the kit's patches, and the read-only `lasttag`
  service;
- optional Moonraker settings: report usage to the kit's Spoolman, announce Moonraker on the LAN.

Run on the printer as its normal user:

    sh fk-printer-pack.sh install      # asks about each part and every change
    sh fk-printer-pack.sh status
    sh fk-printer-pack.sh uninstall

It never overwrites a file it did not write, and shows a diff and asks before its only edits to your own config (one
include line in `printer.cfg`, the `moonraker.conf` sections). Install and uninstall can be run again at any time.
Options: `--data <printer_data>`, `--klipper <klipper folder>` (default `~/klipper`), `--moonraker <url>`,
`--parts`, `--spoolman <url>`, `--allow <IP addresses>` (lasttag), `--yes`.
