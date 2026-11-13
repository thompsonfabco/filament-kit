# Example data: one fake Hub for mockups, tests and screenshots

This file is the single set of example data for Spoolwarden. The four mockups show it, the page audit and the
other tests serve it, and screenshots and documents quote it. Using one set means a screen looks the same wherever
it is shown, and nothing real ever appears in an example.

Everything here is invented. Addresses use the documentation ranges (`192.0.2.x`) and `*.example` / `.local`
names. Never add other addresses, serials, people or emails; add to this file first when a test needs more data.

There are two variants:

- **Workshop hub** (sections 2 to 12): a Hub in everyday use. This is the default everywhere.
- **Empty Hub** (section 13): the same Hub right after installing, for every empty state and the "Still to do" list.

---

## 1. Rules for the mockups

The mockups are single files that show this data in one theme each. They are illustrations: where a mockup and
the design documents differ, the documents are right.

- One self-contained HTML file: no external requests, system fonts, own inline SVG icons, plain HTML, CSS and
  JavaScript, tokens as CSS custom properties, light values on bare `:root` and dark values under both dark
  selectors of `01-foundations.md` section 5.
- The address selects the section and, for screenshots, the appearance: `#<section>` or `#<section>-light` /
  `#<section>-dark`. Sections: `overview`, `printers`, `recent`, `devices`, `presets`, `features`, `settings`,
  `flash`, `updates`, `logs`. `#recent-detail` opens the first record of Recently added. `#intake`,
  `#intake-detail` and `#modules` remain as aliases of `recent`, `recent-detail` and `features`.
- Printers, Recently added and Settings are built out; the other seven sections are short placeholders in the same
  style. The tests' fake Hub serves all ten sections with the data below.
- Any eight digits unlock the lock. Jobs are faked: "Back up now" runs four seconds, prints a few log lines and
  ends with "Backup: done."

## 2. The Hub

| Item | Value |
|---|---|
| Product | Spoolwarden |
| Hub name | **Workshop hub** (in addresses and breadcrumbs: `workshop-hub`) |
| Version | 0.5.2 (signed release) |
| Hub page address | `https://192.0.2.10:8710/setup` |
| web app address at home | `https://192.0.2.10:8710/intake` |
| Other names for this page | `kit.example.net` |
| Setup | Hub with Weigh Station |
| Lock | Starts Locked. The first change asks for the setup code (placeholder `1234-5678`) with the offer "Trust this computer (no code needed here for 90 days)". |
| Certificate fingerprint (pairing) | `1111 2222 3333 4444 5555 6666 7777 8888` (an obvious placeholder) |
| Inventory | 64 spools of 23 filaments |
| Today | 2026-11-12; times are local, written `2026-11-12 14:05` |

## 3. Overview

Status rows, in this order:

| State | Text | Fix line |
|---|---|---|
| OK | Hub service is running. | |
| OK | Spoolman answers: 64 spools, 23 filaments. | |
| OK | Certificate is valid until 2027-10-30. | |
| OK | Label Reader: Cloud (Claude) key is set; 12 of 40 reads used today. | |
| Needs a look | Study A1 mini has not answered since 2026-11-12 09:10. | Check that the printer is on and on the home network. |
| OK | Weigh Station: the scale and the tag reader answer. | |
| OK | Slicer presets: last build 2026-11-12 14:06, 58 presets. | |
| OK | Nightly backup: last one 2026-11-12 03:00. | |
| Note | Spoolwarden 0.5.3 is available. | |

"Still to do" is absent in this variant (nothing is left to set up). Summaries used by navigation rows and the More
sheet: Printers "2 connected, 1 offline"; Recently added "5 records, 14.2 MB of photos"; Devices "3 paired, 2 Tag
Readers"; Slicer presets "58 presets, 3 updates"; Features "10 on, 4 off"; Updates "0.5.3 is available".

## 4. Printers

| Name | Kind | Address | Serial | State | Details |
|---|---|---|---|---|---|
| **Workshop X1** | Bambu Lab X1 Carbon | 192.0.2.40 | 00M00A000000001 | Connected | Certificate pinned; slots mapped |
| **Garage Voron** | Klipper (Voron 2.4) | voron.example:7125 | (none) | Connected | API key set; lane data: auto |
| **Study A1 mini** | Bambu Lab A1 mini | 192.0.2.41 | 03000A000000002 | Offline | Certificate pinned; problem line: "The last slot mapping stopped twice. A report would help." (main action: Collect a report) |
| mainsailos | Klipper printer found on the network, not added | 192.0.2.57:7125 | (none) | Not added | Actions: Use this printer / Dismiss |

Slots:

| Printer | Slot | Spool | Filament | Colour | Left |
|---|---|---|---|---|---|
| Workshop X1 | A1 | 187 | Polymaker PolyTerra PLA Charcoal Black | #2B2B2E | 62 % |
| Workshop X1 | A2 | 198 | Bambu Lab PETG HF Orange | #F2762E | 88 % |
| Workshop X1 | A3 | 176 | eSUN ABS+ White | #F4F4F2 | 35 % |
| Workshop X1 | A4 | (empty) | | | |
| Garage Voron | T0 | 165 | Prusament PLA Galaxy Silver | #8D9199 | 47 % |
| Garage Voron | T1 | 171 | Overture TPU Blue | #2E6FD9 | 71 % |

Fixed results:

- Test connection: connected Bambu Lab printer "192.0.2.40 answers; its certificate matches the pinned one";
  Klipper "Moonraker at voron.example:7125 answers; Klipper is ready"; offline printer "no answer from
  192.0.2.41:8883: check that it is on".
- Map slots on Workshop X1: "Mapping… step 2 of 4", then "Slots: A1, A2, A3, A4".
- Forget printer: "Forget Workshop X1? Its Access Code is deleted." with Cancel / Forget printer.
- Find Klipper printers on `192.0.2.0/24`: "Found on 192.0.2.0/24: 192.0.2.57:7125".
- Klipper add-on commands: two lines beginning `curl -fsSL https://kit.example/...`.
- Add a printer, Bambu Lab: address `192.0.2.42` or `printer.local`, Access Code (secret), name, serial
  (optional). Klipper: address, port 7125, name, API key (optional).
- Saved reports of Study A1 mini: "report-2026-11-12-0915.zip · 212 KiB".
- Live state for the web app and the app: Workshop X1 is printing "bracket-v3.3mf", 42 %, layer 96 of 228,
  nozzle 220 °C, bed 65 °C, 1 h 12 min left, light on. Garage Voron is idle. Filament used, newest first:
  "2026-11-12 13:20 · Workshop X1 · A1 · 18.4 g (spool 187)", "2026-11-11 21:05 · Garage Voron · T0 · 42.0 g
  (spool 165)".

## 5. Recently added

Header facts: the newest 20 additions are kept with their photos (14.2 MB now). The Label Reader is on (Cloud).

| # | Filament | Added | From | State | Spools | Photos | Read confidence |
|---|---|---|---|---|---|---|---|
| 1 | Polymaker PolyTerra PLA Charcoal Black | 2026-11-12 14:05 | From a phone photo | As detected | 214 | 2 | High, except Colour (medium) and Price per kg (not on the label) |
| 2 | Bambu Lab PETG HF Orange ×2 | 2026-11-12 09:41 | From a phone photo | Revised by AI | 212, 213 | 1 | High |
| 3 | eSUN ABS+ White | 2026-11-11 19:22 | From the Weigh Station | Edited by hand | 211 | 1 | High |
| 4 | Prusament PLA Galaxy Silver | 2026-11-10 08:15 | Added by hand | As detected | 210 | 0 | (none: no photo) |
| 5 | Overture TPU Blue | 2026-11-09 17:48 | From a phone photo | As detected | 209 | 3 | Low on Material and Net weight ("check these") |

Photos do not exist: a drawn placeholder (a spool-label sketch tinted with the filament colour) stands in.

Record 1 in detail:

| Group | Field | Value |
|---|---|---|
| Identity | Brand | Polymaker |
| Identity | Name | PolyTerra PLA Charcoal Black |
| Identity | Material | PLA |
| Identity | Colour | #2B2B2E (medium confidence) |
| Identity | Line | PolyTerra PLA |
| Weights | Net weight | 1000 g |
| Weights | Empty spool weight | 140 g |
| Weights | Density | 1.31 g/cm³ |
| Temperatures | Nozzle | 210 °C |
| Temperatures | Bed | 55 °C |
| Temperatures | Nozzle range | 190-230 °C |
| Temperatures | Bed range | 25-60 °C |
| Other | Price per kg | (empty; not on the label) |

- Asking the Label Reader to correct it (text box placeholder "e.g. brand is Polymaker"; wait text "Asking the
  Label Reader… (up to a minute)", two seconds in the mockups) proposes: "Name: PolyTerra PLA Charcoal Black →
  PolyTerra PLA Charcoal Black (Matte)" and "Nozzle range: 190-230 °C → 190-220 °C", with Accept / Discard.
- Revisions: "Revision 1, 2026-11-12 14:09, by hand: Empty spool weight 150 → 140 g" with Undo revision 1.
- Saving with nothing edited answers "Nothing changed."

## 6. Devices

| Group | Entry | Details |
|---|---|---|
| Phones | Kitchen phone | app · paired 2026-10-02 · last seen 2026-11-12 14:06 |
| Phones | Garage tablet | app · paired 2026-10-19 · last seen 2026-11-10 18:30 |
| PC | Desk PC | Slicer Sync · paired 2026-10-03 · last seen 2026-11-12 13:50 |
| Built in | This Hub's web app | built in: this Hub's own pairing |
| Built in | This Hub's command line | built in: this Hub's own pairing |
| Weigh Station | On this machine | scale and tag reader connected |
| Weigh Stations asking to pair | Bench station at 192.0.2.60 | its screen shows 482 913 (Pair / Refuse) |
| Tag Readers | rd-01 · Tag Reader for Workshop X1 | made 2026-10-20 |
| Tag Readers | rd-02 · Tag Reader for Garage Voron | made 2026-11-01 |
| Trusted computers (on) | Desk PC browser (this computer) | made 2026-11-01 · last seen 2026-11-12 at 192.0.2.21 · runs out 2027-02-10 |

Pairing a phone shows a drawn placeholder QR code, "Pairing code: 4821 9370", the fingerprint of section 2 and
"Expires in 10 min." A new Tag Reader token is shown once as `rd-03-EXAMPLE-TOKEN-0000`.

## 7. Slicer presets

- Build: "Last build 2026-11-12 14:06. Presets: 58 (46 for Orca Slicer). Problems: 1." Problem: "Overture TPU has no
  Bambu Studio parent." Slicer Sync: "Slicer Sync reported in 2026-11-12 13:50 (Desk PC)."
- Updates: "3 updates are waiting. Lines with updates: 2. Presets already in your slicers are never replaced unless
  you accept here." Showing them lists: "Bambu Studio: Polymaker PolyTerra PLA @Workshop X1: nozzle temperature, fan speed",
  "Orca Slicer: Polymaker PolyTerra PLA @Workshop X1: nozzle temperature", "Bambu Studio: eSUN ABS+ @Workshop X1:
  bed temperature".

| Product line | Material | Presets | Bambu Studio parent | Orca Slicer parent |
|---|---|---|---|---|
| Polymaker PolyTerra PLA | PLA | 12 | Generic PLA @BBL X1C (catalog) | Generic PLA @BBL X1C (catalog) |
| Bambu Lab PETG HF | PETG | 8 | Bambu PETG HF @BBL X1C (catalog) | Bambu PETG HF @BBL X1C (catalog) |
| eSUN ABS+ | ABS | 6 | Generic ABS @BBL X1C (chosen here) | Generic ABS @BBL X1C (chosen here) |
| Prusament PLA | PLA | 10 | Generic PLA @BBL X1C (catalog) | Generic PLA @BBL X1C (catalog) |
| Overture TPU | TPU | 4 | none | Generic TPU @BBL X1C (catalog) |

## 8. Features

Setup: Hub with Weigh Station. Ten features on, four off.

| Feature | State |
|---|---|
| Spoolman | On |
| Hub service | On |
| Label Reader: Cloud (Claude) | On |
| Label Reader: On this Hub | Off |
| Bambu Lab printers | On |
| Klipper printers | On |
| Slicer presets | On |
| Filament Catalog | On |
| Nightly backup | On |
| Weigh Station | On |
| Web access | Off |
| Remote access | Off (needs Web access) |
| Order history | Off |
| Automatic updates | On |

Turning Web access on asks for one setting: "The public https address of the web app" with the placeholder
`https://mcp.example.com/filament`.

## 9. Settings

| Group | Setting | Value |
|---|---|---|
| Appearance | Light / Dark / System | System |
| Appearance | Theme | the theme of the page being shown |
| Appearance | Theme for new devices | Console |
| General | Display name | Workshop hub |
| General | Names for this page | kit.example.net |
| Storage locations | Locations | Shelf A, Shelf B, Dry box 1, Dry box 2 |
| Storage locations | PLA rack | Shelf A |
| Storage locations | Box location prefix | Dry box |
| Storage locations | Number of storage boxes | 2 |
| Storage locations | Overflow location | Shelf B |
| Label Reader | Read labels with | Cloud (Claude) |
| Label Reader | Anthropic API key | Set (placeholder of the field: `sk-ant-…`) |
| Label Reader | Claude model | the Hub's default (shown as text) |
| Label Reader | Label reads per day | 40 |
| Label Reader | Records kept (Recently added) | 20 ("Now: 5 records, 14.2 MB of photos") |
| Backups and restore | Keep nightly backups for | 14 days |
| Backups and restore | Backups | "2026-11-12 03:00 · nightly · 4,812 KiB", "2026-11-11 03:00 · nightly · 4,790 KiB", "2026-11-10 16:32 · made here · 4,771 KiB" |
| Network and addresses | Web public address | empty (placeholder `https://mcp.example.com/filament`) |
| Network and addresses | Weigh Station address | empty (placeholder `http://station.local:5003`) |
| Network and addresses | Allow printer changes from the public address | Off |
| Web passphrase | State | Not set (at least 12 characters; mismatch error "The two passphrases do not match.") |
| Filament Catalog | State | "Catalog version 2026.11.2 (signed release), 3 local additions. Last check 2026-11-12 03:10: OK." |
| Filament Catalog | Catalog token | Not set |
| Weigh Station voice | Voice | Piper (natural; a 60-80 MB download); the other choice is espeak-ng (robotic; no download) |

Backup warning text: "One zip with everything the Hub keeps. It is not encrypted and holds the setup secrets: store
it somewhere safe."

## 10. Flash a device

| Item | Value |
|---|---|
| Devices | Tag Reader · Weigh Station display |
| Plugged into | This computer · The Hub |
| Port on the Hub | `/dev/ttyACM0` |
| Wi-Fi name asked for | Workshop-WiFi (the password is never shown or stored in examples) |
| Buzzer | High |
| Success | "Done. The Tag Reader joined 'Workshop-WiFi' and reached the Hub." |
| Failure | "The board did not answer. Hold its BOOT button while plugging it in, then try again." |

## 11. Updates

| Item | Value |
|---|---|
| Installed | 0.5.2 (signed release), installed 2026-11-08 |
| Latest release | 0.5.3 |
| Last checked | 2026-11-12 03:12; checked by itself every day at about 03:10 |
| What 0.5.3 brings | "Recently added in the app." · "Faster slot mapping on the A1 mini." · "Fixes a restore that stopped on large backups." |
| Roll back | to 0.5.1, the version this one replaced |
| Update job | "Updating…", five log lines, "The Hub is restarting…", then the page reloads on 0.5.3 |

## 12. Logs

Services: Hub service · Spoolman · Weigh Station · Nightly backup · Automatic updates. Lines: last 50 / 100 / 200.

Sample of "Hub service", last lines:

```
2026-11-12 14:05:12 added spool 214 from a phone photo (Kitchen phone)
2026-11-12 14:06:01 preset build finished: 58 presets, 1 problem
2026-11-12 13:50:44 Slicer Sync reported in (Desk PC)
2026-11-12 13:20:09 Workshop X1 used 18.4 g from spool 187 (A1)
2026-11-12 09:10:31 Study A1 mini at 192.0.2.41 stopped answering
2026-11-12 03:12:00 update check: 0.5.3 is available
```

## 13. The Empty Hub variant

The same Hub (name, version, address) right after installing: Setup "Hub", no printers, no devices, no records,
Label Reader key not set, Slicer presets never built, no backups yet, Trusted computers on with none trusted, no
update available.

| Section | What it shows |
|---|---|
| Overview | "Still to do": "Printers: none yet" (link to Printers) · "Phone: not paired" (link to Devices) · "Moving from another computer? Restore its backup" (link to Settings) · "Anthropic key: not set" (link to Settings). Status rows: Hub service OK, Spoolman OK with "0 spools, 0 filaments", certificate OK. |
| Printers | "No printers yet. Printers on the network appear here once they announce themselves." with Add a printer |
| Recently added | "No spool has been added since the history started." |
| Devices | "Nothing paired yet." · "No Tag Readers yet." · "No computer is trusted." |
| Slicer presets | "No build yet." · "No lines yet. They are made from the filaments in Spoolman at the next build or when a spool is added." |
| Features | Setup Hub; Weigh Station, Web access, Remote access, Order history and Label Reader: On this Hub off |
| Settings | Anthropic API key Not set; backups list "No backups yet." |
| Updates | "Latest release: 0.5.2 (up to date)" · "No earlier version is kept, so there is nothing to roll back to." |
| Logs | "Nothing logged." for a freshly started service |
