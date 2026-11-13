# Spoolwarden design: the command line

This document specifies the `spoolwarden` command on the Hub and its text menus. It builds on
`01-foundations.md`: the principles (section 1), the names (section 2), the four interfaces (section 3), the
status shapes (section 10) and the wording rules come from there and are not repeated here. Where a current code
name helps a developer find something, it is given once in backticks; today the command lives in
`server/filament_kit/cli.py`, `klipper_cli.py`, `menu_ui.py`, `status.py`, `modules.py` and `secret_input.py`.

Contents: 1 What the command line is for · 2 The command name · 3 The command tree · 4 Old and new spellings ·
5 Naming a printer, device or record · 6 Output conventions · 7 Confirmations · 8 Interactive screens ·
9 Commands in detail · 10 What the command line cannot do · 11 Usability problems and their fixes ·
12 Parity · 13 Needs from the Hub

---

## 1. What the command line is for

- It is the fallback for everything (foundations section 3). It runs in a terminal on the Hub, often over SSH;
  commands that change something run with `sudo`.
- It uses the same words, the same order of fields and the same status vocabulary as the Hub page, the web app
  and the app. A person who knows the Hub page's Printers section recognises `spoolwarden printer list`.
- It has no themes and no Light / Dark / System switch: it uses the terminal's own colours (section 6.2). The one
  appearance setting it holds is the Hub's **theme for new devices** (`spoolwarden config theme`, section 9.8).
- It serves two readers. A person at a terminal gets aligned tables, a glyph plus a word for every state, colour
  where it helps, menus and questions. A script gets `--json`, exit codes, `--yes`, and never a question it
  cannot answer.

Terms used below:

| Term | Meaning |
|---|---|
| at a terminal | standard input is a terminal (for questions and prompts); for full-screen menus, standard output too |
| item | a thing in a list: a printer, a setting, a feature. Items are chosen by number. |
| action | something to do on a screen: save, leave, add. Actions are chosen by letter. |
| needs sudo | the command writes the Hub's state or a secret, shows a secret's file or logs, or calls a Hub page route that needs the setup code. Such a command run without root stops with exit code 3 (section 6.7). `-h` marks them `(sudo)`. Commands that only read and show no secret, `status`, `web status`, `label-reader status` and `config show` among them, run without sudo: they read through the Hub's own service account, so a check that uses a secret (the Anthropic API key) works while the secret is never shown. Run with sudo, `status` also checks the Weigh Station's pairing (section 9.7). |

## 2. The command name

- The command is **`spoolwarden`**, installed in the same place `filament-kit` is installed today.
- **`filament-kit` keeps working for a time.** It is a small wrapper that runs `spoolwarden` with the same
  arguments, standard input, standard output and exit code. Before it runs, it prints exactly one line to
  standard error:

  ```
  Note: filament-kit is now called spoolwarden; the old name will be removed.
  ```

  The line is printed on every run, also with `--quiet` and `--json` (it goes to standard error, so `--json`
  output stays clean). The wrapper is kept for at least two minor releases after the first release named
  Spoolwarden. From the release before its removal, the line names that version:
  `Note: filament-kit is now called spoolwarden; the old name goes away in <version>.`
- Help text, messages, Fix lines and documentation always show `spoolwarden`, never the old name.
- Old spellings of commands and flags (section 4) keep working silently, with no note. They do exactly what the
  new spelling does, its questions included: `unpair <id>`, `profiles apply-updates`, `library rollback` and
  `printer map` now ask first (section 7). At a terminal the question simply appears; a script that runs one of
  them without a terminal adds `--yes`, or it stops with exit code 2 and the Fix line says so. Messages elsewhere
  that still name an old spelling (for example the Slicer Sync's `sudo filament-kit profiles apply-updates` and
  `unpair <id>`) are meant to be typed at a terminal, so they keep working. Old spellings are hidden from `-h`
  and listed by `spoolwarden help aliases`.
- `python -m filament_kit` starts the Hub's server. It is not a person's command and has no UI; its log format
  (`LEVEL logger: message` on standard error) is unchanged.

## 3. The command tree

### 3.1 Top-level help

The groups appear in the order of the Hub page's navigation (foundations section 8): Everyday, then System, then
the two commands for moving in from older tools. Running `spoolwarden` with no command prints the same text.

```
$ spoolwarden -h
Spoolwarden on this Hub. Commands marked (sudo) in their own help need sudo.
Usage: spoolwarden <command> [options]    More: spoolwarden <command> -h

Everyday
  status           What works and what needs a look
  printer          List, test, map and manage printers
  klipper          The Klipper add-on
  recent           Recently added spools: show, correct, undo
  devices          Paired phones, PCs and Weigh Stations
  pair             Pair a phone, the Slicer Sync or a Weigh Station
  weigh-station    Weigh Station: pair it, flash its display
  tag-reader       Tag Readers: tokens, flash one over USB
  presets          Slicer presets: build, status, parents, updates

System
  features         Switch features on and off; choose the setup
  config           Settings menu; also config show, set and theme
  label-reader     Label Reader: status and test
  catalog          Filament Catalog: status, update, roll back, add
  backup           Make or list backups
  restore          Restore this Hub from a backup
  web              Access from outside the home, and Claude's connector
  remote           Remote access: certificate and firewall rules
  setup-code       The Hub page's address and setup code
  certificate      The Hub's certificate and its fingerprint
  spoolman         Spoolman: its address and Spoolwarden's extra fields
  update           Check, install or roll back Spoolwarden
  uninstall        Remove Spoolwarden from this machine
  logs             The end of a service's log

Moving in
  migrate-ops      Move data in from filament-ops
  migrate-scanner  Move a printer in from the older scanner tool

Every command: -h  --json  -q/--quiet  -y/--yes  --color auto|always|never
               --plain  --no-progress
```

### 3.2 Every command

`<printer>`, `<device>`, `<reader>` and `<record>` are explained in section 5. Square brackets mark optional
parts. The last column names the place on the Hub page that does the same thing, so the two stay in step.

| Command | What it does | Hub page place |
|---|---|---|
| `status` | Checks everything and prints one row per check (9.1) | Overview |
| `printer list` | All printers, set up and found (9.2) | Printers |
| `printer show <printer>` | One printer: details and slots | Printers, expanded row |
| `printer test <printer>` | Test connection | Test connection |
| `printer add [--klipper] [options]` | Add a printer; asks for what is missing | Add a printer |
| `printer use <printer>` | Add a Klipper printer that a scan found | Use this printer |
| `printer dismiss <printer>` | Drop a found printer from the list | Dismiss |
| `printer rename <printer> <new name>` | Rename | Rename |
| `printer address <printer> <address>` | Change address | Change address |
| `printer access-code <printer>` | Replace the Access Code (Bambu) | Replace Access Code |
| `printer api-key <printer> [--clear]` | Set, replace or clear the Moonraker API key (Klipper) | Set / Replace / Clear key |
| `printer lane-data <printer> auto\|on\|off` | Klipper lane data | Lane data |
| `printer detect <printer>` | Detect model and slots (Klipper) | Detect model and slots |
| `printer scan [--subnet CIDR]` | Find Klipper printers on the network | Find Klipper printers |
| `printer map <printer> [--by-loading]` | Map slots, or map by loading filament | Map slots / Map by loading filament |
| `printer report <printer>` | Collect a report | Collect a report |
| `printer reports <printer>` | List saved reports | Saved reports |
| `printer forget-certificate <printer>` | Forget certificate (Bambu) | Forget certificate |
| `printer forget <printer>` | Forget printer | Forget printer |
| `printer live <printer>` | Prints where the live view is (section 10) | Open the live printer view |
| `printer menu` | The Printers screen (8.4) | Printers |
| `klipper add-on` | Prints the commands that install the Klipper add-on | Klipper add-on |
| `recent` (same as `recent history`) | Recently added records (9.3) | Recently added |
| `recent show <record> [--photos]` | One record: fields, confidence, revisions | Record detail |
| `recent revise <record> --note TEXT [--item N]` | Ask the Label Reader to correct it | Ask the Label Reader to correct it |
| `recent edit <record> field=value... [--item N] [--spools 41,42]` | Edit by hand | Edit by hand, Save changes |
| `recent undo <record>` | Undo the newest revision that is not undone | Undo revision N |
| `devices` (same as `devices list`) | Paired devices (9.4) | Devices |
| `devices forget <device>` | Unpair a device | Revoke |
| `pair [--slicer-sync \| --weigh-station] [--text]` | Pairing code, QR and fingerprint | Pair a phone / Link for the Slicer Sync / Link for the Weigh Station |
| `weigh-station pair [--local]` | Run on the Weigh Station: pair it with the Hub | Pair the Weigh Station on this machine |
| `weigh-station flash-display` | Write the Weigh Station display firmware over USB | Flash a device |
| `weigh-station pairing-state` | Paired, not paired or not checked yet | (none) |
| `tag-reader list` | Tag Reader tokens | Devices, Tag Readers |
| `tag-reader new-token [--name NAME]` | Make a token | Make a token |
| `tag-reader revoke <reader>` | Revoke a token | Revoke |
| `tag-reader flash [options]` | Write a Tag Reader over the Hub's USB | Flash a device |
| `presets status` | Build, Slicer Sync and update state (9.5) | Slicer presets |
| `presets build` | Build now | Build now |
| `presets lines` | Filament lines and their parents | Product lines |
| `presets set-parent <line> <parent> [--orca]` | Set the Bambu Studio or Orca Slicer parent | Set parent |
| `presets restore-deleted` | Bring back presets deleted in Bambu Studio | Restore deleted presets |
| `presets updates (--line ID \| --all)` | Show what would be accepted (changes nothing) | Show what would be accepted |
| `presets accept-updates (--line ID \| --all)` | Accept updates (asks) | Accept these |
| `features` (same as `features list`) | Features, on or off (9.6) | Features |
| `features menu [--numbered] [--raw]` | The Features checklist (8.5) | Features |
| `features on <feature> [--hub ADDRESS]` / `features off <feature>` | Switch one feature (`--hub` when switching on the Weigh Station without the Hub service) | Turn on / Turn off |
| `features setup <setup> [--hub ADDRESS]` | Choose the setup | Setup |
| `features apply [--no-pair]` | Apply the features again | Apply again |
| `features units` | The service files the features need, one per line | (none) |
| `config [--numbered]` | The settings menu (8.3) | Settings |
| `config show` | All settings, in menu order | Settings |
| `config set <key> <value>` | Change one setting | Settings, one field |
| `config theme [<theme>]` | Show or set the theme for new devices | Settings > Appearance > Theme for new devices |
| `label-reader status` | Label Reader engines and their health (9.9) | Settings > Label Reader |
| `label-reader test <photo>... [--engine cloud\|local]` | Read label photos without adding anything | Test |
| `catalog status` | Filament Catalog version and last check | Settings > Filament Catalog |
| `catalog update [--scheduled]` | Update now | Update now |
| `catalog rollback` | Go back to the version before | Go back to the version before |
| `catalog add <file \| ->` | Add your own entry | Add entry |
| `catalog adopt <folder>` | Take over a catalog folder from an older install | (none) |
| `catalog token [--remove]` | Set, replace or remove the catalog token | Catalog token |
| `backup create [--out DIR]` | Back up now | Back up now |
| `backup list` | Backups on this Hub | Show the backups |
| `backup keep <days>` | Keep nightly backups for N days | Keep nightly backups for N days |
| `restore <zip> \| --uploaded` | Restore (asks for the typed word) | Restore |
| `web status` | Access from outside: rows as in `status` | Settings > Network and addresses |
| `web passphrase` | Set or replace the web passphrase | Web passphrase |
| `remote firewall` | Print the firewall rules (changes nothing) | Show the firewall rules |
| `remote get-certificate` | Get the public certificate now | Get the certificate |
| `setup-code [--new] [--revoke-trusted]` | Hub page address and setup code | Setup code, Trusted computers |
| `certificate` | Make the Hub's certificate if missing; print its fingerprint | (none) |
| `spoolman fields` | Make Spoolwarden's extra fields in Spoolman | Overview, Make the fields |
| `spoolman address [<url>]` | Show or change the Spoolman in use (checked before saving) | Settings > General, Spoolman address |
| `update [--check \| --rollback] [--scheduled]` | Updates | Updates |
| `uninstall [--purge]` | Remove Spoolwarden (asks) | Updates, footer line |
| `logs [<service>] [--lines 50\|100\|200]` | The end of a service's log | Logs |
| `migrate-ops [--apply]` | Move a filament-ops bundle in (a dry run without `--apply`) | (none) |
| `migrate-scanner` | Move a printer in from the older scanner tool | (none) |
| `add` | Prints where spools are added (section 10) | (none) |
| `spool` | Prints where spools are opened, tagged and moved (section 10) | (none) |
| `help [<command> \| aliases \| --markdown]` | Help; `--markdown` prints the command table for the user guide | (none) |

`--version` prints `Spoolwarden 0.5.2`. `spoolwarden help --markdown` is the source of the user guide's command
table, so the guide and the command cannot drift apart.

## 4. Old and new spellings

Groups are renamed where the old word was an internal one or a name that changed in foundations section 2. Every
old spelling stays as a silent alias (section 2).

| Old | New | Why |
|---|---|---|
| `filament-kit` | `spoolwarden` | Product name |
| `pair --pc` | `pair --slicer-sync` | Slicer Sync |
| `pair --station` | `pair --weigh-station` | Weigh Station |
| `station pair [--local]` | `weigh-station pair [--local]` | Weigh Station |
| `station flash-panel` | `weigh-station flash-display` | Weigh Station display |
| `station pairing-state` | `weigh-station pairing-state` | Weigh Station |
| `unpair` | `devices list` | Says what it shows |
| `unpair <id>` | `devices forget <device>` | Now asks first; accepts a name |
| `cert` | `certificate` | Plain word |
| `intake history` | `recent` (or `recent history`) | Recently added |
| `intake show`, `revise`, `edit`, `undo` | `recent show`, `revise`, `edit`, `undo` | Recently added |
| `ensure-fields` | `spoolman fields` | Says where the fields go |
| `printer map --manual` | `printer map --by-loading` | Map by loading filament |
| `printer unpin` | `printer forget-certificate` | Hub page's words |
| `library status`, `update`, `rollback`, `adopt`, `add` | `catalog status`, `update`, `rollback`, `adopt`, `add` | Filament Catalog |
| `profiles build`, `status`, `lines`, `set-parent`, `restore-deleted` | `presets build`, `status`, `lines`, `set-parent`, `restore-deleted` | Slicer presets |
| `profiles apply-updates --dry-run` | `presets updates` | Showing is its own command |
| `profiles apply-updates` | `presets accept-updates` | Hub page's word; now asks |
| `modules list`, `menu`, `apply`, `units` | `features list`, `menu`, `apply`, `units` | Features |
| `modules enable <name>` / `disable <name>` | `features on <feature>` / `off <feature>` | Hub page's words |
| `modules enable <name> --server ADDR` | `features on <feature> --hub ADDRESS` | The Hub's name |
| `modules set server\|station\|all-in-one [--server ADDR]` | `features setup hub\|weigh-station\|hub-with-weigh-station [--hub ADDRESS]` | Setups |
| `reader tokens` | `tag-reader list` | Tag Reader |
| `reader token [--name]` | `tag-reader new-token [--name]` | Says what it makes |
| `reader revoke` | `tag-reader revoke` | Tag Reader |
| `reader setup` | `tag-reader flash` | Says what it does |
| `remote issue` | `remote get-certificate` | Hub page's words |
| `klipper add NAME HOST [--port]` | `printer add --klipper --name NAME --address HOST [--port]` | One place for printers |
| `klipper scan [--subnet]` | `printer scan [--subnet]` | One place for printers |
| `klipper detect ID` | `printer detect <printer>` | One place for printers |
| `klipper set ID --lane-data X` | `printer lane-data <printer> X` | One place for printers |
| `klipper api-key ID` | `printer api-key <printer>` | One place for printers |
| `klipper pack` | `klipper add-on` | Klipper add-on |
| `local-intake status`, `test` | `label-reader status`, `test` | Label Reader |
| `status --station-pairing` (hidden) | `status --weigh-station-pairing` (hidden) | Weigh Station |

Unchanged: `status`, `config`, `backup`, `restore`, `web`, `setup-code`, `update`, `uninstall`, `migrate-ops`,
`migrate-scanner`, `printer map`, `printer report`. Old setup words (`server`, `station`, `all-in-one`) and old
feature keys (section 9.6) are accepted wherever the new ones are.

## 5. Naming a printer, device or record

**Printers.** Every command that takes `<printer>` accepts the printer's name, its serial (Bambu) or its id
(Klipper; the id shown in `printer list`, which a Klipper printer gets when a scan finds it or when it is added,
and keeps from then on). The argument is matched in this order, ignoring case:

1. an exact serial or id;
2. an exact name (quote names with spaces: `"Study A1 mini"`);
3. the start of exactly one name (`study` finds Study A1 mini).

No match, or more than one, stops with exit code 2. The Fix line then lists the **close matches**: every printer
whose name, serial or id contains the argument anywhere, ignoring case, at most five, in `printer list` order,
each as its name and its serial or id. With no close match, the Fix line ends after `spoolwarden printer list.`
and no list follows.

```
$ sudo spoolwarden printer report a1
Error: "a1" does not name one printer.
Fix: use a name, serial or id from spoolwarden printer list. Close matches:
     Study A1 mini  03000A000000002
```

Printers found by a scan but not added match only `printer show`, `test`, `use` and `dismiss`; any other command
says `Error: mainsailos is found on the network but not added yet.` with
`Fix: sudo spoolwarden printer use mainsailos`. A command that works on one printer family only (for example
`printer access-code` on a Klipper printer) says `Error: Garage Voron is a Klipper printer; it has no Access
Code.` and, where one exists, the Klipper command in the Fix line.

**Devices, Tag Readers, records.** `<device>` is a device's name or id, `<reader>` a token's name or id, both
matched the same way. `<record>` is a Recently added record's id, as `recent` shows it.

## 6. Output conventions

### 6.1 One status vocabulary

The words are the ones the Hub page, the web app and the app show; the shapes are foundations section 10. A state
is always shown as a glyph followed by a word, never by colour alone and never by a glyph alone.

| Meaning | Words | Glyph (Unicode) | Glyph (ASCII) | Colour (token, section 6.2) |
|---|---|---|---|---|
| Good | `OK`, `connected`, `on`, `set`, `done`, `high`, `confirmed` | `●` | `+` | green (`--ok`) |
| Off or absent | `off`, `not set`, `not set up`, `found, not added`, `skipped`, `not on label`, `unknown` | `○` | `o` | dim (`--muted`) |
| Offline | `offline` | `○` | `o` | red (`--bad`) |
| Needs a look | `needs a look`, `medium`, `wrong Access Code`, `certificate changed`, `stopped without finishing` | `▲` | `!` | yellow (`--warn`) |
| Error | `error`, `failed`, `low: check this` | `×` | `x` | red (`--bad`) |
| Working | `working`, and the progress lines of section 6.6 | `◐` | `~` | cyan (`--accent`) |
| Note | `note`, `entered by hand` | `◆` | `*` | blue (`--info`) |

The terminal has no octagon, so the error shape is `×`. Words are lower case except `OK`. Where the table has
more than one word for a meaning, the word belongs to a kind of thing:

| Thing | States, in this order |
|---|---|
| Status row (`status`, `web status`, `label-reader status`) | OK · needs a look · note · (detail line, no glyph) |
| Printer | connected · offline · not set up · wrong Access Code · certificate changed · found, not added · unknown (only while the Hub is not running) |
| Feature | on · off |
| Secret (API key, Access Code, passphrase, catalog token) | set · not set |
| Background work (update, backup, restore, apply) | working · done · failed · stopped without finishing |
| Read confidence of a field | high · medium · low: check this · not on label |
| Slot after mapping | confirmed · entered by hand · skipped |

The code's own values map onto these words: status rows `ok` / `fail` / `info` / `detail` are OK / needs a look /
note / detail; printer states follow the printer states table of `02-components.md` 7.1: the badge word as the
status word (`connected`, `offline`, `not configured`, `needs a look`; `connecting` as a progress line) and the
table's sentence as the `Fix:` line.

Recently added records carry a **kind of record**, not a health state: `as detected`, `revised by AI`,
`edited by hand`. These are shown as words without a glyph; `revised by AI` is blue (`--info`) when colour is on.
A revision that was undone is followed by `(undone)` in dim text.

### 6.2 Glyphs and colour

**Glyph set.** The Unicode set is used when the locale's character set is UTF-8 (`LC_ALL`, then `LC_CTYPE`,
then `LANG`); otherwise the ASCII set. `SPOOLWARDEN_GLYPHS=unicode` or `ascii` overrides. The same choice applies
to the other symbols:

| Symbol | Unicode | ASCII |
|---|---|---|
| Before and after | `→` | `->` |
| Separator in one-line summaries | ` · ` | ` - ` |
| Text cut short, wait in progress | `…` | `...` |
| Checkbox | `[x]` / `[ ]` | `[x]` / `[ ]` |
| Degree | `210 °C` | `210 C` |

**When colour is used**, decided separately for standard output and standard error, first rule that applies:

1. `--color always` or `--color never` (default `--color auto`).
2. `NO_COLOR` set to anything but the empty string: no colour.
3. `TERM` is `dumb` or unset: no colour.
4. Colour when that stream is a terminal, none otherwise.

**What is coloured.** Only the glyph and its state word, the `Error:` label, table headers (bold) and secondary
text (dim). Nothing else, so a line read without colour loses nothing. Escape codes are limited to the basic
ones, which the terminal's own palette turns into shades that suit its light or dark background:

| Token | Terminal code |
|---|---|
| `--ok` | green (SGR 32) |
| `--warn` | yellow (SGR 33) |
| `--bad` | red (SGR 31) |
| `--info` | blue (SGR 34) |
| `--accent` | cyan (SGR 36) |
| `--muted` | dim (SGR 2) |
| `--text` | the terminal's default |
| table header, menu title | bold (SGR 1) |
| cursor row in full-screen menus | reverse video (SGR 7), plus the `>` mark |

No background colours, no 256-colour or true-colour codes, no blinking. Every coloured span is reset before the
end of its line.

**Plain mode.** `--plain` is the screen-reader mode, accepted by every command. `SPOOLWARDEN_PLAIN=1` in the
environment turns it on too, and `TERM=dumb` implies it. For that run it sets switches that already exist:
`--numbered` (numbered menus, section 8.1), `SPOOLWARDEN_GLYPHS=ascii`, `--color never`, and `--text` on `pair`
(no QR code). It adds four things no other switch does:

- Status glyphs are left out and only the word is printed (`OK  Services running: 6 of 6`), because screen
  readers read glyphs as their character names. This is the one exception to the glyph rule of section 6.1.
- Progress is printed as whole lines, never rewritten in place (section 6.6).
- Every table is printed as blocks, one `Label: value` line per field and a blank line between rows, the form
  section 6.3 uses below 60 columns, so no value depends on its column position.
- Secret prompts echo nothing and end with `(typing is not shown)` (section 8.3).

Plain output contains no escape sequences and no carriage returns.

### 6.3 Tables and width

- A table has a header row in upper case (bold when colour is on) and columns separated by two spaces. Text is
  left-aligned; numbers (weights, sizes, counts, percentages) are right-aligned with their unit
  (`4,812 KiB`, `62 %`).
- **Width.** The width is the terminal's (`COLUMNS`, then the terminal size), or 80 when unknown. Every line is
  at most one less than the width, so at 80 columns every line, table or sentence, is at most 79 characters.
  All samples in this document fit that.
- Each table names one **long column** (`FILAMENT`, `NAME`, `TEXT`). On a wider terminal it gets the extra room;
  on a narrower one it is cut with `…`. Below 60 columns, and always with `--plain`, the table turns into
  blocks, one per row, each line `Label: value`, with a blank line between rows (the terminal's version of the Hub page's stacked cards on
  phones, foundations section 7).
- When standard output is not a terminal, nothing is cut and nothing turns into blocks: columns are as wide as
  their widest value. Scripts use `--json` instead of parsing tables.
- An empty list prints its empty-state sentence instead of a header, the same sentence the Hub page shows
  (for example `No printers yet. Printers on the network appear here once they announce themselves.`).
- A one-line summary goes above a table (as the Hub page puts header facts above a list); hints and counts that
  belong to the whole list go below it, after one blank line.
- Running text wraps at the width; a continuation line is indented to where the text started. A command is never
  wrapped in the middle: it goes on its own line so it can be copied whole.

### 6.4 Words, numbers, dates

- The wording rules of foundations section 2 apply. Feature names, printer names and setting labels are the
  Hub page's. Code names (`ai_intake`, `lane_data`, `SPOOL_ID`) appear only where a person types them (a
  `config set` key, a Klipper macro name) and are then written exactly as typed.
- Dates in tables and logs are `2026-11-12 14:05`, local time. A summary may add relative words after the exact
  time: `last checked 2026-11-12 03:10 (2 hours ago)`; a terminal has no hover, so the exact time is never
  left out.
- Sizes: `KiB` and `MB` as the Hub page shows them, with thousands separators (`4,812 KiB`).
- One term per thing, the shared wording table of `08-platform-mapping.md` section 12: `Weight with spool` (never
  gross weight), `Try again` (never retry, in prompts and Fix lines), `Slicer presets` (never profile), drafts
  (never unfinished adds), and "Leave empty to choose automatically." as the hint of an optional prompt the Hub
  fills in by itself.

### 6.5 Results, errors and Fix lines

- **Results** go to standard output: one line, past tense, naming the thing. `Forgot Workshop X1.`,
  `Saved 2 changes: display name, PLA rack.`, `Unchanged.`
- **Errors** go to standard error, always, also inside menus (the line appears right under the prompt that caused
  it). The first line is `Error: ` followed by what went wrong. When something can be done about it, the next
  line is `Fix: ` followed by what to do, with the exact command when one does it. A command too long for the
  line goes on its own line, indented five spaces under the Fix text:

  ```
  $ spoolwarden printer map "Study A1 mini"
  Error: Study A1 mini did not answer at 192.0.2.41:8883.
  Fix: check that it is switched on and on the network, then test it:
       sudo spoolwarden printer test "Study A1 mini"
  ```

- **Notes** that are not results (the old-name line, `No QR code here: …`) go to standard error and start with
  `Note: `.
- **Errors from the Hub** (the `error` text of a Hub reply) are printed after `Error: ` as they come, so the
  Hub's own messages follow the same rules (section 13). When the reply carries `message` (a printer that refused a
  command included), that sentence is printed after `Error: ` instead, the same words the other interfaces show
  (`02-components.md` 12). A Hub reply is never printed raw: no JSON, braces or quotes outside `--json`.
- `Fix:` is the word the Hub page's Overview uses under a row that needs a look; the command line uses it for
  status rows and for errors alike.
- Commands that need root and run without it: `Error: this needs administrator rights.` and
  `Fix: run it with sudo:` followed by the full command on its own line. Exit code 3.

### 6.6 Waits and progress

Any step that can take longer than 2 seconds shows a progress line once 2 seconds pass with no other output.

- At a terminal the line is rewritten in place once a second: `◐ <what is happening>… <N> s`. After 5 seconds
  it adds `(Ctrl-C stops)`. There is no spinner and no other animation. When the step ends, the progress line is
  replaced by its result line.
- Steps that know their count say so: `◐ Mapping the slots of Workshop X1… step 2 of 4`.
- Output from a background job (an update, applying features) is printed below the progress line, dim and
  indented two spaces, as it arrives.
- When standard error is not a terminal, the progress line is printed once, without the counter, and the result
  line follows. Progress never goes to standard output, so it never mixes with `--json`.
- `--no-progress` prints each progress line once, as a whole line without the counter (the form above for a
  standard error that is not a terminal), then the step's result line.
- `--plain` prints the same first line without its glyph and, while the wait lasts, one more whole line every 10
  seconds with the time so far: `Connecting to Workshop X1 at 192.0.2.40… 10 s`.
- `--quiet` drops progress lines entirely (section 6.8), so it needs no `--no-progress`.
- Ctrl-C during a wait stops the step. Steps that must clean up say so first, for example
  `Stopping: putting the slots' colours back first…`, then `Stopped.` and exit code 130.

| Wait | Progress line |
|---|---|
| Running the status checks | `◐ Checking… 4 of 15` |
| Connecting to a printer (up to 20 s) | `◐ Connecting to Workshop X1 at 192.0.2.40…` |
| Waiting for a printer's first report (up to 10 s) | `◐ Waiting for Workshop X1 to report…` |
| Test connection | `◐ Testing Workshop X1…` |
| Detect (Klipper) | `◐ Asking Garage Voron…` |
| Scan | `◐ Looking for Moonraker on 192.0.2.0/24…` |
| Map slots | `◐ Mapping the slots of Workshop X1… step 2 of 4` |
| Collect a report | `◐ Collecting a report from Workshop X1…` |
| Check the Anthropic API key | `◐ Checking the API key…` |
| Ask the Label Reader to correct a record | `◐ Asking the Label Reader… (up to a minute)` |
| Label Reader test | `◐ Reading 2 photos with On this Hub…` |
| Apply features | `◐ Applying the changes…` |
| Update, roll back, check | `◐ Updating to 0.5.3…`, `◐ Rolling back to 0.5.1…`, `◐ Checking for updates…` |
| Back up, restore | `◐ Backing up…`, `◐ Restoring…` |
| Filament Catalog update | `◐ Updating the Filament Catalog…` |
| Slicer presets build | `◐ Building the Slicer presets…` |
| Removing Spoolwarden | `◐ Removing Spoolwarden…` |
| Get the public certificate | `◐ Getting the certificate…` |
| Writing firmware over USB | `◐ Writing the firmware to /dev/ttyACM0… 45 %` |
| The Hub restarting after a save | `◐ The Hub is restarting…`, then `The Hub is back.` |
| Waiting for a phone to pair | `◐ Waiting for the phone… (the code works until 14:20)` |

### 6.7 Exit codes

| Code | Meaning |
|---|---|
| 0 | Done. For `status`: nothing needs a look. For `printer map`: confirmed or partly mapped. |
| 1 | Something failed, or `status` found at least one row that needs a look |
| 2 | Wrong use: unknown command or option, bad value, no such or more than one printer, device or record, or a question was needed and there is no terminal and no `--yes` |
| 3 | Needs sudo |
| 4 | The Hub is not running and this command needs it (`Fix: sudo systemctl start` with the Hub's service) |
| 5 | Cancelled: the answer was no, or a menu was left without saving its changes. Nothing changed. |
| 130 | Stopped with Ctrl-C |

### 6.8 `--json` and `--quiet`

`--json` is accepted by every command that prints data or a result. Rules:

- Standard output gets exactly one JSON document followed by a newline: indented by two spaces when standard
  output is a terminal, on one line otherwise. Nothing else is printed to standard output.
- Field names and values are those of the Hub's own replies where the Hub page reads the same data (table
  below), so a script and the Hub page see one shape. Times are ISO 8601 with offset; weights in grams, sizes in
  bytes, temperatures in °C, all as numbers.
- Secrets never appear: a secret is `{"set": true}` or `{"set": false}`.
- A command that acts prints the Hub's reply shape: `{"ok": true, ...}`.
- On an error, standard output gets `{"ok": false, "error": "<text>", "fix": "<text or null>"}`, standard error
  gets the usual text, and the exit code is as in section 6.7.
- `--json` never asks: a command that would ask needs `--yes`, or it stops with exit code 2.
- Menus (`config`, `features menu`, `printer menu`) do not take `--json`; they say
  `Error: config is a menu. Fix: use spoolwarden config show --json`.
- Fields are only ever added. Removing or renaming one is announced in the release notes one minor release
  ahead.

| Command | JSON shape |
|---|---|
| `status`, `web status`, `label-reader status` | `{"rows": [{"group", "state", "text", "fix", "action"}], "summary": {...}}`, the rows of `GET /setup/api/overview` plus `group` (section 13) |
| `printer list`, `printer show` | the printer objects of `GET /setup/api/state` (`printers.list`): `serial, name, model, ip, configured, state, pinned, family` and, for Klipper, `host, port, api_key, lane_data` |
| `printer test` | `{reachable, state, text}`, the reply of `printers/<serial>/test` |
| `printer map` | the map view of `GET /api/printers/<serial>/map` at its end |
| `printer reports` | `{reports: [{name, size, at}], never}`, the reply of `printers/<serial>/reports` |
| `recent` | `GET /setup/api/intake/history`: `{keep, photo_bytes, ai, count, records: [...]}` |
| `recent show` | `GET /setup/api/intake/history/<id>` |
| `devices` | `state.devices`: `[{id, name, paired, last_seen, built_in}]` |
| `tag-reader list` | `state.readers.list`: `[{id, name, created}]` |
| `presets status` | `GET /setup/api/presets` |
| `features list` | `state.modules` plus `{"setup": "<setup>"}` |
| `config show`, `config theme` | the `values` of `GET /setup/api/settings/general`, plus `theme` |
| `catalog status` | `GET /setup/api/library` |
| `backup list` | `{backups: [{name, at, kind, size}], keep_days, folder}` |
| `update --check` | `GET /setup/api/updates` |
| `logs` | `{unit, text, truncated}` |
| `weigh-station pairing-state` | `{"state": "paired" \| "unpaired" \| "unchecked", "address": ...}` |
| any other action | `{"ok": true, ...}` with the fields its result line names |

`-q` / `--quiet` prints only what the command exists to print: errors, lists and details asked for, and answers
to questions. It drops result lines, notes (except the old-name line of section 2) and progress lines.
`status --quiet` prints only the rows that need a look; its exit code still says whether there were any.

`--plain` (section 6.2) and `--no-progress` (section 6.6) are accepted by every command, like `--color`. They
change only how text is shown on a terminal; with `--json`, standard output is the same JSON document.

## 7. Confirmations

- Every command that deletes, forgets, replaces or is hard to undo asks first, when at a terminal. The question
  is one sentence or two, then ` [y/N] `. `y` or `yes` (any case) goes on; anything else, an empty answer or the
  end of input is no.
- After no: `Nothing changed.` and exit code 5.
- Two commands replace or delete everything and ask for a typed word instead: `restore` (`restore`) and
  `uninstall --purge` (`purge`). The word is compared without case and surrounding spaces.
- `-y` / `--yes` answers yes to every confirmation of that run, typed words included. The question is not
  printed; the result line is.
- Not at a terminal and no `--yes`: the command does nothing and stops with exit code 2:

  ```
  $ sudo spoolwarden printer forget "Workshop X1" < /dev/null
  Error: forgetting Workshop X1 needs a yes, and there is no terminal to ask.
  Fix: run it again with --yes:
       sudo spoolwarden printer forget "Workshop X1" --yes
  ```

- `--yes` does not answer checks or offers, only confirmations. It does not answer the fingerprint check of
  `weigh-station pair` (a person must compare it), and it does not answer the offer to share a map after
  mapping by loading filament (no, unless answered at a terminal). It does answer the `Also turn on|off …?`
  questions of `features on|off`, which confirm a cascade.
- Where the Hub page has the same dialog (`03-hub-page.md` sections 5.5, 7.7, 10.11 and 12.3), the question is
  that dialog's title followed by its body, word for word, so a person reads the same question in both places.
  The one change: where the body names a place on the Hub page, the question names the command that does the
  same. Questions with no Hub page dialog are written in the same style.

A confirmation, both answers:

```
$ sudo spoolwarden printer forget workshop
Forget Workshop X1? Spoolwarden stops connecting to it and deletes its Access
Code. To use it again, add it again. [y/N] y
Forgot Workshop X1.

$ sudo spoolwarden printer forget workshop
Forget Workshop X1? Spoolwarden stops connecting to it and deletes its Access
Code. To use it again, add it again. [y/N]
Nothing changed.
```

Every question, word for word (names are examples):

| Command | Question | Result after yes |
|---|---|---|
| `printer forget` (Bambu) | `Forget Workshop X1? Spoolwarden stops connecting to it and deletes its Access Code. To use it again, add it again.` | `Forgot Workshop X1.` |
| `printer forget` (Klipper) | `Forget Garage Voron? Spoolwarden stops connecting to it and deletes its Moonraker API key, if one is saved.` | `Forgot Garage Voron.` |
| `printer dismiss` | `Dismiss mainsailos? It leaves this list. A new scan may find it again.` | `Dismissed mainsailos.` |
| `printer forget-certificate` | `Forget the certificate of Workshop X1? The next connection trusts whatever certificate answers at 192.0.2.40 and remembers it. Do this only after the printer was reset or replaced.`, then after yes the Access Code prompt (8.7) | `Forgot the certificate of Workshop X1; the next connection pins the one it presents.` |
| `printer map` | `Map the slots of Workshop X1? The printer changes its slot colours briefly and runs a short job with no motion. The colours are put back afterwards.` | the mapping runs (9.2) |
| `printer api-key --clear` | `Clear the Moonraker API key of Garage Voron? Spoolwarden then connects without a key. If Moonraker asks for one, the printer's test says so until a key is set.` | `Cleared the API key of Garage Voron.` |
| `devices forget` | `Unpair Shop phone? It can no longer reach the Hub until it is paired again.` | `Unpaired Shop phone.` |
| `tag-reader revoke` | `Revoke the token tr3? A Tag Reader using it is refused from now on. Set it up again with sudo spoolwarden tag-reader flash to give it a new token.` | `Revoked the token tr3.` |
| `catalog rollback` | `Go back to the previous Filament Catalog? The version before the last update comes back. Your own entries are kept.` | `Back to version 2026.11.1.` |
| `catalog token --remove` | `Remove the Catalog token? The Filament Catalog can then download only from public sources.` | `Removed the Catalog token.` |
| `presets accept-updates` | the list (9.5), then `Accept these 3 updates? The Slicer Sync writes them at its next run, after its backup.` | `3 updates accepted; the Slicer Sync writes them at its next run, after its backup.` |
| `update` | `Update to 0.5.3? Spoolwarden stops while it installs and starts again by itself. Settings and data stay. The version before is kept, so you can roll back.` | the update runs |
| `update --rollback` | `Roll back to 0.5.1? Spoolwarden stops while it installs and starts again by itself. Settings and data stay.` | the roll back runs |
| `remote get-certificate` | `Get the certificate now? Port 80 on your router must reach this Hub while it runs. Spoolwarden never changes your firewall or router.` | the job runs (9.12) |
| `setup-code --new` | `Make a new setup code? The old one stops working.` | the new code, then `The old setup code no longer works.` |
| `setup-code --revoke-trusted` | `Revoke every trusted computer? Each one needs the setup code again.` | `2 trusted computers revoked.` |
| `config`, removing the Anthropic API key | `Remove the Anthropic API key? Label Reader: Cloud (Claude) stops reading labels until a new key is set.` | staged until Save (8.3) |
| `features off` with dependants | `Also turn off Slicer presets? It needs Hub service.` (one question per dependant) | the plan includes it |
| `features on` with needs | `Also turn on Hub service? Label Reader: Cloud (Claude) needs it.` | the plan includes it |
| `recent revise` | the proposal (9.3), then `Accept these changes?` | `Saved as revision 2: Name, Nozzle range.` |
| `weigh-station flash-display` | `Write the Weigh Station display firmware to /dev/ttyACM0?` (one per board found) | the write runs |
| `tag-reader flash` | `Write the Tag Reader firmware to /dev/ttyACM0? What is on the board now is replaced.` | the write runs |
| `restore` | the backup's summary (9.10), then `Type restore to go on: ` | the restore runs |
| `uninstall` | `Remove Spoolwarden from this machine? Its data stays unless you add --purge.` | the removal runs |
| `uninstall --purge` | `This also deletes everything Spoolwarden keeps on this machine. Type purge to go on: ` | the removal runs |
| leaving `config` with changes | `Leave without saving 1 change (PLA rack)?` | `Nothing saved.` (exit 5) |
| leaving the Features checklist with changes | `Leave without applying 2 changes (Label Reader: On this Hub on, Weigh Station off)?` | `Nothing applied.` (exit 5) |

Commands that change something but do not ask, because nothing is lost: `printer rename`, `printer address`,
`printer access-code`, `printer lane-data`, `printer use`, `recent edit`, `recent undo` (the revision is kept,
marked undone, and can be revised again), `backup create`, `presets build`, `catalog update`, `config set`,
`config theme`.

## 8. Interactive screens

### 8.1 Kinds of screen and the two variants

| Kind | Screens |
|---|---|
| Menu: a list of items, each opening a value or another screen | `config` and its groups; the Printers screen; one printer |
| Checklist: items switched on and off, then applied | Features (`features menu`, or `config` > Features) |
| Walkthrough: the Hub asks, the person answers, step by step | Map by loading filament |
| Prompt: one question | Every value in `config`; secrets; the questions of `weigh-station pair`, `weigh-station flash-display`, `tag-reader flash`, `web passphrase`, `printer add`; settings a feature needs |

Menus and checklists come in two variants with **the same items, the same numbers, the same letters and the same
words**:

- **Full-screen** (curses): used when standard input and standard output are terminals, `TERM` is set and is not
  `dumb`, the terminal is at least 40 columns by 8 rows, and curses starts.
- **Numbered**: plain lines and a `Number:` prompt. Used otherwise, and always with `--numbered`,
  `SPOOLWARDEN_MENU=numbered` or `--plain` (screen-reader users and people on a serial console often prefer
  it). When a full-screen menu was wanted but the terminal is too small, one line says why:
  `Note: this terminal is smaller than 40 × 8, so the list is numbered instead of full-screen.`

### 8.2 Keys

One key map for every menu, checklist and walkthrough, in both variants. **Numbers choose items; letters choose
actions.** A screen never uses numbers for two different lists.

| Action | Full-screen | Numbered |
|---|---|---|
| Move | Up / Down (or `k` / `j`), Home, End, PgUp / PgDn (5 rows) | (none) |
| Open or choose an item | Enter on the row, or type its number | type its number, then Enter |
| Switch an item on or off (checklist) | Space, or Enter on the row (Enter never applies) | type its number; several at once: `2 5 7` |
| Save (or apply) | `s` | `s` |
| Leave this screen | `q` or Esc | `q` |
| Show every key | `?` | `?` |
| Leave at once, saving nothing | Ctrl-C | Ctrl-C |

- **Leaving.** `q` leaves every menu, checklist and walkthrough and goes back one level (at the top it ends the
  command). In a prompt, an empty answer leaves the prompt and keeps the current value, printing
  `Unchanged.`; at a yes/no question, an empty answer is no. That is the one way out of each kind of screen.
- **Unsaved changes.** `q` at the top of `config` with changes not saved asks
  `Leave without saving 2 changes (Display name, PLA rack)? [y/N]`; yes prints `Nothing saved.`. `q` in the
  Features checklist with switched rows not applied asks
  `Leave without applying 2 changes (Label Reader: On this Hub on, Weigh Station off)? [y/N]`; yes prints
  `Nothing applied.`. Both then end with exit code 5; no stays.
- **Ctrl-C** anywhere leaves without asking and without saving: `Left without saving 2 changes.` and exit code
  130. The end of input (Ctrl-D, or the end of piped input) does the same but ends with exit code 5:
  `Input ended: 2 changes not saved.` With nothing staged, both just end (exit code 130 and 0).
- **Help.** `?` lists every key of the screen, including the setup letters of the Features checklist; any key
  returns.
- **Footer** (full-screen). Two lines at the bottom: the first explains the cursor row (what it is, what it
  needs); the last lists the keys in a short form that fits 40 columns, for example
  `Enter open  s save  q leave  ? help`. The Features checklist adds one line between them, the plan of changes
  (8.5), so its footer has three lines. In the numbered variant the same keys are printed under the list.
- **Header.** The screen's place, as the Hub page's breadcrumbs: `Settings > Storage locations`. When changes
  are waiting, the header adds `· 2 changes not saved`.
- **Cursor.** The cursor row is in reverse video and starts with `>`, so it is visible without colour. Every
  line is cut to the width minus one.
- Unknown input prints `Error: "x" is not a number or letter on this screen.` to standard error and asks again.

### 8.3 `config`: the settings menu

The menu edits the Hub's settings. Changes are **collected, then saved together** with `s`; nothing is saved
by leaving. The groups and their order are those of Settings on the Hub page. Printers and Features are listed
after them because people look for them here; they open their own screens, where changes apply at once, as on
the Hub page.

```
$ sudo spoolwarden config
Settings · Workshop hub

   1  Appearance             Theme for new devices: Console
   2  General                Workshop hub
   3  Storage locations      4 locations · PLA rack Shelf A · 2 boxes
   4  Label Reader           Cloud (Claude) · 40 reads a day · key set
   5  Backups and restore    Nightly backups kept 14 days
   6  Network and addresses  Public address not set
   7  Web passphrase         not set
   8  Filament Catalog       Catalog token not set
   9  Weigh Station voice    Piper (natural)

  These open their own screens; changes there apply at once:
  10  Printers               3 set up · 1 found
  11  Features               Hub with Weigh Station

  s save   q leave   ? help
Number: 3

Settings > Storage locations

   1  Locations                Shelf A, Shelf B, Dry box 1, Dry box 2
   2  PLA rack                 Shelf A
   3  Box location prefix      Dry box
   4  Number of storage boxes  2
   5  Overflow location        Shelf B

  s save   q back   ? help
Number: 2
PLA rack [Shelf A]: Shelf B
  Changed, not saved yet.
Number: 4
Number of storage boxes [2]: two
Error: the number of storage boxes is a whole number, 0 or more.
Number of storage boxes [2]:
  Unchanged.
Number: q

Settings · Workshop hub · 1 change not saved
  (the main list again)
Number: q
Leave without saving 1 change (PLA rack)? [y/N] y
Nothing saved.
```

Saving instead:

```
Number: s
Saved 1 change: PLA rack.
```

**Groups and their items.** Group names, item labels, their order and the choice words are the Hub page's
(`03-hub-page.md` section 10); the one difference is the engine name Cloud (Claude), which follows foundations
section 2. "Key" is the setting's key for `config set` (9.8).

| Group | Item | Key | Kind of answer |
|---|---|---|---|
| Appearance | Theme for new devices | `appearance.theme` (section 13) | choice: Console (dense and technical) · Workbench (calm cards) · Palette (colourful and roomy) · Panes (simple lists) |
| General | Display name | `server_name` | text |
| General | Spoolman address | (none: `spoolman address`, 9.12) | text, an http address; only when Spoolman runs on another machine. On Save the Hub first checks that Spoolman answers there, as `spoolman address` does, and saves it after the other changes |
| Storage locations | Locations | `locations` | text, separated by commas |
| Storage locations | PLA rack | `placement.pla_location` | text |
| Storage locations | Box location prefix | `placement.box_prefix` | text, shown in quotes when it starts or ends with a space |
| Storage locations | Number of storage boxes | `placement.box_count` | whole number, 0 or more |
| Storage locations | Overflow location | `placement.overflow` | text |
| Label Reader | Engine order | `intake.reader` | choice: Automatic: On this Hub first, Cloud (Claude) when it is unsure or fails · On this Hub, then Cloud (Claude) · Cloud (Claude), then On this Hub · Cloud (Claude) only · On this Hub only |
| Label Reader | Anthropic API key | (secret) | secret; then `c` checks it, `x` removes it (asks) |
| Label Reader | Claude model | `model` | text; empty for the default model |
| Label Reader | Reads per day | `reads_per_day` | whole number from 1 |
| Label Reader | Address | `local_intake.url` | text |
| Label Reader | Tier | `local_intake.tier` | choice: Automatic · Processor (CPU) · Graphics card (GPU) |
| Label Reader | Records kept | `intake.history_keep` | whole number 0 to 500; the row adds `Now 5 records, 14.2 MB of photos` |
| Backups and restore | Keep nightly backups for | `backups.keep_days` | whole number of days, 1 to 365 |
| Network and addresses | Public address | `web.public_url` | text, an https address |
| Network and addresses | Weigh Station address | `station.url` | text; empty answer keeps, `-` clears |
| Network and addresses | Names for this page | `setup.hosts` | text, separated by spaces |
| Network and addresses | Allow printer changes from the public address | `web.printer_changes` | on / off |
| Web passphrase | New passphrase | (secret) | secret, asked twice (`New passphrase again`) |
| Filament Catalog | Catalog token | (secret) | secret; `x` removes it (asks) |
| Weigh Station voice | Voice | `station.tts` | choice: Piper (natural; a 60-80 MB download) · espeak-ng (robotic; no download) |

The Engine order choices map to the stored values `auto`, `local-then-cloud`, `cloud-then-local`, `cloud`,
`local`; the Tier choices to `auto`, `cpu`, `gpu`; Piper and espeak-ng to `auto` and `espeak`. The Label Reader
screen shows the Hub page's sub-headings above its items, numbering straight through: `Cloud (Claude)` above
Anthropic API key, `On this Hub` above Address, `Recently added` above Records kept. Engine order is a choice
only while both Label Reader features are on; with one on, its row reads
`Engine: Cloud (Claude). Switch on the other one in Features (11) to use both.` (or `Engine: On this Hub. …`)
and cannot be opened. The Cloud (Claude) items show only while Label Reader: Cloud (Claude) is on, the On this
Hub items only while Label Reader: On this Hub is on; Records kept always shows.
Each group's screen ends with the actions that are commands elsewhere, so they are one step away: Backups and
restore ends with `Back up now: sudo spoolwarden backup create` and `Restore: sudo spoolwarden restore <zip>`;
Filament Catalog with
`Update now: sudo spoolwarden catalog update`; Network and addresses with
`Firewall rules: spoolwarden remote firewall`.

**Prompts in the menu.**

- A text or number item asks `<Label> [<current value>]: `. An empty answer keeps the value (`Unchanged.`); a
  value equal to the current one also prints `Unchanged.`; anything else prints `Changed, not saved yet.`
- A wrong value prints an error and asks again; the earlier staged changes stay.
- A choice item lists its choices numbered under the question, the current one marked `(now)`:

  ```
  Weigh Station voice
     1  Piper (natural; a 60-80 MB download)  (now)
     2  espeak-ng (robotic; no download)
  Number (Enter keeps it):
  ```

- A secret item asks `<Label> (Enter keeps it): ` and echoes one `*` per character (Backspace works). When
  standard input is not a terminal, nothing is echoed. With `--plain` nothing is echoed either, and the prompt
  ends with `(typing is not shown)`, so a screen reader does not say "star" for each key. A secret is never shown
  back; its row says `set` or
  `not set`. A secret asked twice that does not match prints
  `Error: the two passphrases do not match. Type them again.`
- **Switched-off features.** A group whose feature is off stays in the list, dim, with `off: switch it on in
  Features (11)`. Opening it prints `Weigh Station is off on this Hub. Switch it on in Features (11) first.` and
  stays on the main list. This applies to Weigh Station voice (feature Weigh Station). Two groups keep one
  item open while their feature is off, as on the Hub page:
  - **Label Reader** counts as on while either Label Reader: Cloud (Claude) or Label Reader: On this Hub is on.
    With both off, its row reads `off: only Records kept`; opening it prints
    `The Label Reader is switched off. Spools are then added by hand. Switch it on in Features (11).` and shows
    only Records kept.
  - **Filament Catalog** with its feature off: opening it prints
    `The Filament Catalog is switched off. Switch it on in Features (11).` and shows only Catalog token.

**Saving.**

- `s` from any level saves every staged change at once and prints `Saved 2 changes: display name, PLA rack.`
  With nothing staged it prints `Nothing to save.`
- If a change needs the Hub to restart (Claude model, Reads per day), the item's row says
  `restarts the Hub` while staged, and saving shows `◐ The Hub is restarting…` then `The Hub is back.`
- If a value was changed elsewhere (the Hub page, another terminal) while the menu was open, saving asks per
  value: `Display name was changed elsewhere to "Workshop" while this menu was open. Keep yours? [y/N]`.
- If saving fails, nothing is saved, the menu stays open with every staged change kept, and the error says what
  to change (foundations principle 4):
  `Error: nothing was saved: the web public address must start with https://. Your changes are still here.`

**The full-screen variant** shows the same rows; Enter on an item opens it, and the prompt appears on the
footer's first line.

### 8.4 The Printers screen

Opened by `config` > Printers or `spoolwarden printer menu`. Printers are items (numbers); actions are letters.
Actions run at once, with the confirmations of section 7, exactly as on the Hub page.

```
Printers · 3 set up · 1 found

   1  Workshop X1    Bambu    192.0.2.40          ● connected
   2  Garage Voron   Klipper  voron.example:7125  ● connected
   3  Study A1 mini  Bambu    192.0.2.41          ○ offline
   4  mainsailos     Klipper  192.0.2.57:7125     ○ found, not added

  a add a printer   l look again   q back   ? help
Number: 3

Printers > Study A1 mini
  Bambu Lab A1 mini · 192.0.2.41 · serial 03000A000000002
  ○ offline · certificate pinned
  ▲ needs a look  The last slot mapping stopped twice. A report would help.

  c collect a report   t test connection   m map slots
  b map by loading filament   v saved reports   r rename
  e change address   k replace Access Code
  u forget certificate   f forget printer
  q back   ? help
Number or letter: c
◐ Collecting a report from Study A1 mini… 3 s
```

| Printer | Actions, in this order (the first is the main one) |
|---|---|
| Bambu | `c` collect a report then `t` test connection when a problem is shown; without a problem `t` comes first and `c` second; then `m` map slots, `b` map by loading filament, `v` saved reports, `r` rename, `e` change address, `k` replace Access Code, then the destructive ones on their own line: `u` forget certificate, `f` forget printer |
| Klipper | `t` test connection, `d` detect model and slots, `b` map by loading filament, `r` rename, `e` change address, `k` set or replace Moonraker API key, `n` lane data, then on their own line: `x` clear API key, `f` forget printer |
| Found, not added | `u` use this printer, `t` test connection, then on its own line: `f` dismiss |

`a` on the list asks the same questions as `printer add` (8.7). `l` reads the list again.

### 8.5 The Features checklist

Opened by `config` > Features or `spoolwarden features menu`. Rows are features; Space (or the number) switches
one; nothing changes on the Hub until `s` applies.

```
Features · Hub with Weigh Station                          rows 1-11 of 14
  [x] Spoolman                      Filament database on this machine
  [x] Hub service                   Serves the Hub page and the apps
> [x] Label Reader: Cloud (Claude)  Reads spool labels from photos
  [ ] Label Reader: On this Hub     Reads spool labels on this Hub
  [x] Bambu Lab printers            Bambu Lab printers on the network
  [x] Klipper printers              Klipper printers through Moonraker
  [x] Slicer presets                Builds presets for your slicers
  [x] Filament Catalog              Known filaments and their settings
  [x] Nightly backup                Nightly backups of everything
  [x] Weigh Station                 Scale and tag reader for new spools
  [ ] Web access                    Access from outside the home
Needs Hub service and an Anthropic API key. Off also turns off: nothing else.
Changes: none
Space on/off  s apply  q leave  ? help
```

- **Needs, before switching.** The footer's first line always shows what the cursor row needs and what switching
  it off would also switch off, so the cascade is known before Space is pressed.
- **Changes line.** After switching, the second footer line lists the plan, as the Hub page's preview does:
  `Turns on: Label Reader: On this Hub. Turns off: Weigh Station.` Switching that pulls in another feature says
  so on the same line: `Turns on: Hub service (Label Reader: Cloud (Claude) needs it).`
- **Enter** on a row switches it, like Space. It never applies; only `s` does.
- **Setups.** `h` sets the Hub setup, `w` Weigh Station only, `b` Hub with Weigh Station. The plan line shows
  the result; nothing applies until `s`.
- **Apply.** `s` prints the plan, then asks for any setting the chosen features need and the Hub does not have
  yet, one prompt each, in the order of the table below. Each prompt is preceded by one line saying which
  feature needs it. A wrong value prints its error and asks again. An empty answer returns to the checklist with
  `Not applied: <feature> needs that setting.` and the switched rows kept. After the answers,
  `◐ Applying the changes…` runs as in section 6.6 and ends with
  `Features applied: Label Reader: On this Hub on, Weigh Station off.` or `Unchanged.`

  | Setting (key) | Asked when | Line, then prompt | Wrong value |
  |---|---|---|---|
  | `web.public_url` | Web access or Remote access is on and no https public address is set | `Web access needs the address people use.` then `Public https address of the web app (e.g. https://hub.example/filament): ` | `Error: give the https address people use, e.g. https://hub.example/filament.` |
  | `orders.file` | Order history is on and no file is set | `Order history needs its file.` then `Path of the order history file: ` | `Error: give the path of the order history file.` |
  | `spoolman_url` | Hub service is on, Spoolman is off, and no Spoolman on another machine is set | `The Hub service needs a Spoolman: none runs on this machine.` then `Address of your Spoolman (e.g. http://spoolman.example:7912): ` | `Error: give the address of a Spoolman on another machine, e.g. http://spoolman.example:7912.` |
  | `station.allow` | Weigh Station is on, Hub service is off, and no Hub address is set (the `--hub` option gives it) | `Weigh Station only needs the Hub's address.` then `The Hub's address (IP address or name): ` | `Error: enter one address or name, not a range or wildcard.`; for this machine's own address: `Error: give the address of the machine the Hub runs on.` |

- **Leaving.** `q` with switched rows not applied asks
  `Leave without applying 2 changes (Label Reader: On this Hub on, Weigh Station off)? [y/N]` (section 7).
- **Numbered variant.** The same rows, numbered 1 to 14, then:
  `Type numbers to switch (several: 2 5 7); h, w, b choose a setup; s applies; q leaves; ? help.`
  An empty answer applies nothing; it prints the line above again.
- **`features menu --raw`** is for the installer: the questions go to standard error (the checklist draws on
  `/dev/tty` when standard output is captured), and standard output gets the chosen features as one line of
  keys separated by commas, then one `set key=value` line per answered setting.

### 8.6 Map by loading filament

`spoolwarden printer map <printer> --by-loading` (and `b` on the Printers screen). It needs the Hub running and
follows the Hub's walkthrough (`POST /api/printers/<serial>/manual-map/start`, then
`GET /api/printers/<serial>/manual-map` every 2 seconds; answers through `manual-map/confirm`, `skip`, `stop` and
`offer`). The Hub's own sentences (`say`, `ask`) are printed as they come; the command line adds only the
answer line.

```
$ sudo spoolwarden printer map workshop --by-loading
Map by loading filament: Workshop X1
Load each slot to the nozzle when asked.

Load A1 to the nozzle now.
◐ Waiting for the printer to report a change… 7 s
The printer reports A1 loaded. Is that right?
  y yes · a slot (e.g. A2) I loaded that one · s skip A1 · q stop
Answer: y
  ● confirmed  A1 (right nozzle)

Load A2 to the nozzle now.
...
Done: 3 confirmed, 1 skipped.
  A1  ● confirmed (A1, right nozzle)
  A2  ● confirmed (A2, right nozzle)
  A3  ◆ entered by hand (A3)
  A4  ○ skipped
Share this map in a printer report, so other owners of this model benefit?
Nothing is sent unless you choose to. [y/N]
```

- Answers: `y` / `yes`; a slot label (`A2`); for dual-nozzle printers `y right` or `y left`; `s` / `skip`;
  `q` / `stop` / `quit`. When the printer reports no loads, the Hub offers a numbered list of slots and the
  answer is a number.
- `q` stops at once (the Hub keeps what was confirmed) and prints the summary.
- The share question waits 60 seconds, then counts as no.

### 8.7 Other prompts

| Command | Prompts, in order | Notes |
|---|---|---|
| `printer add` (Bambu) | `IP address or name (e.g. 192.0.2.40 or printer.local): ` · `Access Code (on the printer: Settings > Network/LAN): ` (secret) · `Name (optional): ` · `Serial (optional: read from the printer): ` | Same order as the Hub page's form. An empty Access Code: `No Access Code entered; nothing added.` |
| `printer add --klipper` | `Address: ` · `Port [7125]: ` · `Name (optional): ` · `Moonraker API key (optional): ` (secret) | |
| `printer address` (Bambu) | `Access Code of Workshop X1 (on the printer: Settings > Network/LAN): ` (secret), after the address is given as the argument | Same as the Hub page's Change address dialog. `--access-code -` reads it from standard input. Empty: `No Access Code entered; nothing changed.` (exit 5). A Klipper printer has no such prompt. |
| `printer access-code` | `New Access Code for Workshop X1 (on the printer: Settings > Network/LAN): ` (secret) | Empty: `Unchanged.` |
| `printer forget-certificate` | after the confirmation (section 7): `Access Code of Workshop X1 (on the printer: Settings > Network/LAN): ` (secret) | Same as the web app and the app. `--access-code -` reads it from standard input; `--yes` answers the confirmation, not this prompt. Empty: `No Access Code entered; nothing changed.` (exit 5) |
| `printer api-key` | `Moonraker API key for Garage Voron: ` (secret) | Empty: `Unchanged.` An empty answer no longer clears the key (it does today); clearing is `printer api-key <printer> --clear`, which asks (section 7). |
| `weigh-station pair` | `Paste the link from the Hub (sudo spoolwarden pair --weigh-station): ` then the fingerprint in four-character groups and `Does it match the fingerprint the Hub shows? [y/N]` | Run on the Weigh Station. Not answered by `--yes`. No: `Not paired. Nothing changed.` |
| `weigh-station flash-display` | one confirmation per blank board found (section 7) | Stops and restarts the Weigh Station service around the write, saying so |
| `tag-reader flash` | `Wi-Fi network the Tag Reader joins: ` · `Its Wi-Fi password: ` (secret) · `The password again: ` (secret) · `Buzzer: h for high, l for low [h]: ` | `--ssid` and `--buzzer high\|low` skip their prompts; `--password -` reads the password from standard input. The other options of today's `reader setup` keep their names and meaning (9.7). |
| `web passphrase` | `New passphrase, at least 12 characters: ` · `New passphrase again: ` (both secret) | Mismatch: `Error: the two passphrases do not match.` |
| `catalog token` | `Catalog token (GitHub token): ` (secret) | |
| `restore`, `uninstall --purge` | the typed word (section 7) | |

Secrets are never accepted as plain arguments (they would be visible to other users of the machine). A script
passes a secret on standard input with the option's value `-` (`--access-code -`, `--api-key -`,
`--password -`).

## 9. Commands in detail

Samples use the example data of the mockups. The Hub's address in samples is `192.0.2.10`; the real command
prints the Hub's own address, as `setup-code` shows it. The certificate fingerprint in samples
(`1111 2222 …`) is a placeholder; the real command prints the Hub certificate's SHA-256 in groups of four.

### 9.1 `status`

Runs every check and prints one row per check, grouped under the same headings, in the same order, as the
Hub page's Overview (both read the same rows, section 13). A row is two spaces, the glyph, the state word padded
to 12 characters, two spaces, the text. A state word longer than 12 characters (`found, not added`,
`wrong Access Code`, `certificate changed`) is not cut: on that row alone the text starts two spaces after the
word, and its Fix and detail lines stay at the usual column. A row that needs a look is followed by its `Fix:`
line, aligned with the text. Detail lines (no glyph) are aligned with the text too.

```
$ spoolwarden status
Spoolwarden 0.5.2 · Workshop hub · Hub with Weigh Station

Hub
  ● OK            Services running: 6 of 6
  ● OK            Answering at https://192.0.2.10:8710
  ● OK            Certificate present, fingerprint 1111 2222 3333 4444 …
Spoolman
  ● OK            Reachable at http://192.0.2.10:7912 (v0.22.1)
  ● OK            Spoolwarden's extra fields are in place
Label Reader
  ● OK            Cloud (Claude): the API key works
  ◆ note          Reads used today: 12 of 40
Weigh Station
  ● OK            Answering at http://station.local:5003
  ▲ needs a look  Scale not seen
                  Fix: check the scale's USB cable, then run this again.
Devices
  ◆ note          Paired devices: 3
Printers
  ● connected     Workshop X1
  ● connected     Garage Voron
  ○ offline       Study A1 mini
  ▲ needs a look  Study A1 mini: the last slot mapping stopped twice.
                  A report would help.
                  Fix: sudo spoolwarden printer report "Study A1 mini"
Slicer presets
  ● OK            Last build 2026-11-12 03:05. Presets: 48. Problems: none
  ◆ note          Slicer Sync last reported 2026-11-12 07:30
Filament Catalog
  ● OK            Version 2026.11.2 (signed release), 3 local additions

2 need a look · 9 OK · 2 connected · 1 offline · 3 notes
```

| Group | Rows (OK form / needs-a-look form) | Fix when it needs a look |
|---|---|---|
| Hub | `Services running: N of N` / `Service <name> is stopped` (one row per stopped service) | `sudo systemctl start <name>` |
| Hub | `Answering at <address>` / `Not answering at <address>` | `see what it logged: sudo spoolwarden logs` |
| Hub | `Certificate present, fingerprint …` / `Certificate missing` | `sudo spoolwarden certificate` |
| Hub | note `Display name: <name>` (only when not set: needs a look, `Display name not set`) | `sudo spoolwarden config` |
| Spoolman | `Reachable at <url> (v<version>)` / `Not reachable at <url>` | for Spoolman on this machine `sudo systemctl start <its service>`, else `check that Spoolman is running at <url>` |
| Spoolman | `Spoolwarden's extra fields are in place` / `Spoolwarden's extra fields are missing` | `sudo spoolwarden spoolman fields` |
| Label Reader | `Cloud (Claude): the API key works` / `Cloud (Claude): no API key` / `Cloud (Claude): the API key was refused` | `sudo spoolwarden config` (Label Reader) |
| Label Reader | note `Reads used today: N of M` (needs a look when N = M: `No reads left today (M of M)`) | `raise Reads per day in sudo spoolwarden config, or wait until tomorrow` |
| Label Reader | `On this Hub: answering at <url> (tier: <tier>)` / `On this Hub: not answering at <url>` (only when installed) | `sudo spoolwarden label-reader status` |
| Weigh Station | `Answering at <url>`, `Tag reader seen`, `Scale seen`, `Paired with <address>` / `… not seen`, `Not paired` | per row: check the cable; `sudo spoolwarden pair --weigh-station` |
| Devices | note `Paired devices: N` | (none) |
| Printers | one row per printer with its state word (section 6.1); one needs-a-look row per printer problem | `sudo spoolwarden printer report "<name>"`, or the fix for that state |
| Slicer presets | `Last build <time>. Presets: N. Problems: none` / `… Problems: M` with each problem as a detail line; note `Slicer Sync last reported <time>` or needs a look `Slicer Sync: not set up`; note for the waiting text | `sudo spoolwarden presets status`; `sudo spoolwarden pair --slicer-sync` |
| Filament Catalog | `Version <v> (<source>), N local additions` / `Not downloaded yet` / `Last check failed: <why>` | `sudo spoolwarden catalog update` |

- A group whose feature is switched off prints one row: `○ off  Switched off in Features.` (no Fix; it is not a
  problem).
- The summary line counts rows by word; it is omitted with `--quiet`.
- While checks run, `◐ Checking… 4 of 15` shows on standard error (section 6.6).
- `--quiet` prints only the rows that need a look (with their group heading and Fix). Exit code 1 when any row
  needs a look (section 6.7). `--json`: section 6.8.
- `web status` and `label-reader status` print the rows of their own group in the same form.

### 9.2 `printer` and `klipper`

**`printer list`**: every printer, set up or found, in the Hub page's order. The long column is `NAME`.

```
$ spoolwarden printer list
NAME           TYPE     ID               ADDRESS             STATE
Workshop X1    Bambu    00M00A000000001  192.0.2.40          ● connected
Garage Voron   Klipper  garage-voron     voron.example:7125  ● connected
Study A1 mini  Bambu    03000A000000002  192.0.2.41          ○ offline
mainsailos     Klipper  mainsailos       192.0.2.57:7125     ○ found, not added

3 set up: 2 connected, 1 offline. 1 found on the network, not added.
▲ Study A1 mini needs a look: spoolwarden printer show "Study A1 mini"
Add the found one: sudo spoolwarden printer use mainsailos
```

- The state comes from the running Hub (`GET /setup/api/state`, `printers.list`). When the Hub is not running,
  the list comes from the settings and every state is `○ unknown` with the note
  `Note: the Hub is not running, so connection states are unknown.`
- Empty: `No printer yet. Printers on the network appear here once they announce themselves.` then
  `Add one: sudo spoolwarden printer add`.

**`printer show <printer>`**: the fields in the Hub page's order (model, address, serial or id, state,
certificate or API key and lane data, slots), then the slots.

```
$ spoolwarden printer show "Workshop X1"
Workshop X1
  Model        Bambu Lab X1 Carbon
  Address      192.0.2.40
  Serial       00M00A000000001
  State        ● connected
  Certificate  pinned
  Slots        mapped

SLOT  FILAMENT                                COLOUR   LEFT
A1    Polymaker PolyTerra PLA Charcoal Black  #2B2B2E  62 %
A2    Bambu Lab PETG HF Orange                #F2762E  88 %
A3    eSUN ABS+ White                         #F4F4F2  35 %
A4    empty
```

A Klipper printer shows `API key  set` and `Lane data  auto` in place of Certificate, and its tool slots (`T0`,
`T1`). A printer with a problem shows it under the fields, with its Fix:
`▲ needs a look  The last slot mapping stopped twice. A report would help.` A printer offline shows
`No slot data while offline.` in place of the slot table.

**Other printer commands.** Result lines use the Hub page's words.

| Command | Result line(s) | Notes |
|---|---|---|
| `printer test` | `● OK  192.0.2.40 answers; its certificate matches the pinned one.` / `× failed  No answer from 192.0.2.41:8883: check that it is on.` | The Hub's test texts, in the row form. Exit 1 when it does not answer. |
| `printer add` | Bambu: `Added Workshop X1 (serial 00M00A000000001).` plus the Hub's note. Klipper: `Added Garage Voron as garage-voron (voron.example:7125).`, the Hub's note if any, then what detect found, indented: `  Model: Voron 2.4 (not verified)` and `  Slots: T0, T1`, each with the Hub's reason on the next line, indented further, when it gives one | Asks for what the flags do not give (8.7). Flags: `--address`, `--name`, `--serial`, `--access-code -`; Klipper `--klipper --address --port --name --api-key -`. |
| `printer use` | `Added mainsailos (192.0.2.57:7125).` | Optional `--api-key -` |
| `printer rename` | `Renamed Workshop X1 to Workshop X1C.` | |
| `printer address` | `Saved. Workshop X1 is at 192.0.2.42.` plus the Hub's note | A Bambu Lab printer's address change asks for its Access Code (8.7), as the Hub page's Change address dialog does. |
| `printer access-code` | `Saved the Access Code of Workshop X1.` | |
| `printer api-key` | `Saved the API key of Garage Voron.` / `Cleared the API key of Garage Voron.` | |
| `printer lane-data` | `Saved. Lane data: auto.` | |
| `printer detect` | `Garage Voron: Voron 2.4 (not verified). Slots: T0, T1.` | The Hub's Spoolman warning, if any, as a `Note:` |
| `printer scan` | `Found on 192.0.2.0/24: 192.0.2.57:7125 (add it: sudo spoolwarden printer use mainsailos)` / `No Moonraker found on 192.0.2.0/24.` | One line per printer found; ones already added say `(added as Garage Voron)` |
| `printer report` | `Collected a report: <file>.` then the Hub's sentence on what a report never holds | |
| `printer reports` | table `MADE`, `SIZE`, `NAME` (long column) and the folder they are in / `No report kept for this printer yet.` | |
| `printer forget-certificate`, `printer forget`, `printer dismiss` | section 7 | |

**`printer map <printer>`** (auto) asks (section 7), then shows the steps as a progress line and ends with the
result block:

```
$ sudo spoolwarden printer map workshop --yes
◐ Mapping the slots of Workshop X1… step 2 of 4
● done  Slots mapped: A1, A2, A3, A4
  A1  AMS 0 tray 0 → printer slot 1
  A2  AMS 0 tray 1 → printer slot 2
  A3  AMS 0 tray 2 → printer slot 3
  A4  AMS 0 tray 3 → printer slot 4
```

A slot without a number says `→ no number yet`. Problems print as `▲ needs a look` lines, notes as `i note`
lines, then the Hub's outcome sentence and, when there is one, `Next: …`. When mapping keeps failing, the last
line is `Fix: map it by loading each slot to the nozzle: sudo spoolwarden printer map workshop --by-loading`.
When the Hub is not running, the command connects to the printer itself; the waits of section 6.6 show. Exit
code 0 when confirmed or partly mapped, 1 otherwise, 130 after Ctrl-C (which first puts the colours back). After
Ctrl-C the result block lists each slot as put back or not, and when any slot could not be put back, its last
line is `▲ needs a look  A slot listed above as not put back may still show a test colour: set its colour again
on the printer.`

**`klipper add-on`** prints the Hub page's sentence and the commands, each on its own unbroken line:

```
$ spoolwarden klipper add-on
Installs the spool macros and Spoolwarden's Moonraker settings on a Klipper
printer. Run these on the printer:

curl -fsSL https://spoolwarden.example/klipper-add-on.sh -o add-on.sh
sha256sum add-on.sh
```

With `--json`: `{version, lines}` as the Hub page's reply.

### 9.3 `recent` (Recently added)

**History.** A summary line, then the table. The long column is `FILAMENT`. Records newest first; the record's
kind (section 6.1) in `STATE`.

```
$ spoolwarden recent
Recently added: 5 records, keeping 20, 14.2 MB of photos.

ID  ADDED             STATE           SPOOLS    FILAMENT
35  2026-11-12 14:05  as detected     214       Polymaker PolyTerra PLA Charco…
34  2026-11-12 09:41  revised by AI   212, 213  Bambu Lab PETG HF Orange x2
33  2026-11-11 19:22  edited by hand  211       eSUN ABS+ White
32  2026-11-10 08:15  as detected     210       Prusament PLA Galaxy Silver
31  2026-11-09 17:48  as detected     209       Overture TPU Blue

▲ 31 has fields read with low confidence: spoolwarden recent show 31
```

- `--from` adds the `FROM` column (`phone photo`, `web app`, `Weigh Station`, `by hand`, `command line`) on wide
  terminals; it is always in `show` and in `--json`.
- When the Label Reader is off, a note follows the summary:
  `Note: the Label Reader is off on this Hub, so corrections are by hand only.`
- Empty: `No spool has been added since the history started.`

**Show.** The fields in groups, in the Hub page's order; a confidence mark only where it is not high.

```
$ spoolwarden recent show 35
Record 35 · 2026-11-12 14:05 · from a phone photo · as detected
Spool 214 · filament 88 · 2 photos · read by Cloud (Claude)

Identity
  Brand               Polymaker
  Name                PolyTerra PLA Charcoal Black
  Material            PLA
  Colour              #2B2B2E                   ▲ medium
Weights
  Net weight          1000 g
  Empty spool weight  140 g
Temperatures
  Nozzle              210 °C
  Bed                 55 °C
  Nozzle range        190-230 °C
  Bed range           25-60 °C
Other
  Density             1.31 g/cm³
  Price per kg        (empty)                   ○ not on label
  Line                PolyTerra PLA
Read confidence is high unless marked.

Revisions: none.
Photos open on the Hub page: https://192.0.2.10:8710/setup#recent/35
```

- A record with several items prints `Item 1: spool 212 (filament 86); changes apply to all of them` and its
  fields, then `Item 2: …`.
- Revisions, newest last: `  1  2026-11-12 14:09  by hand  Empty spool weight 150 g → 140 g`; an undone
  revision ends with `(undone)` in dim text; a note follows as `· note: …`; a filament left with no spools adds
  `· filament 87 has no spools left (not deleted)`.
- `--photos` adds the photos' file paths on the Hub, one per line.
- No photo: `No photo was taken for this addition.` in place of the photos line.

**Revise, edit, undo.**

```
$ sudo spoolwarden recent revise 35 --note "it is the matte one"
◐ Asking the Label Reader… (up to a minute) 6 s
The Label Reader suggests:
  Name: PolyTerra PLA Charcoal Black
     → PolyTerra PLA Charcoal Black (Matte)
  Nozzle range: 190-230 °C → 190-220 °C
Accept these changes? [y/N] y
Saved as revision 1: Name, Nozzle range.

$ sudo spoolwarden recent edit 35 empty-spool-weight=150
Saved as revision 2: Empty spool weight 140 g → 150 g.

$ sudo spoolwarden recent undo 35
Undone: revision 2. Record 35 is revised by AI again.
```

- A change line is `<Field>: <before> → <after>`; when it does not fit, the after value goes on the next line,
  indented, starting with the arrow.
- Revise with nothing to change: `The Label Reader changed nothing.` (exit 0). No photo kept:
  `Note: no photo was kept for this record; the Label Reader worked from the saved values and your note.`
- Revise when the Label Reader is off: `Error: the Label Reader is off on this Hub, so only edits by hand
  work.` with `Fix: sudo spoolwarden recent edit 35 name="…"`.
- Edit with values equal to the current ones: `Nothing changed.` (exit 0).
- Filament changes after a save or undo print the Hub's sentences: `The spools now use filament 89 (new).`,
  `Filament 88 has no spools left; it was not deleted.`

Field names for `recent edit` (`--item N` picks the item; `--spools 41,42` limits a change to those spools):

| Field | Key | Also accepted | Value |
|---|---|---|---|
| Brand | `brand` | `vendor` | text |
| Name | `name` | | text |
| Material | `material` | | text |
| Colour | `colour` | `color` | `#RRGGBB` |
| Net weight | `net-weight` | `net` | grams, `1000` or `1000 g` |
| Empty spool weight | `empty-spool-weight` | `spool-weight`, `tare` | grams |
| Density | `density` | | g/cm³ |
| Nozzle | `nozzle` | | °C |
| Bed | `bed` | | °C |
| Nozzle range | `nozzle-range` | | `190-230` |
| Bed range | `bed-range` | | `25-60` |
| Price per kg | `price-per-kg` | `price_per_kg` | number |
| Line | `line` | | text |

Keys the command accepts today keep working. An unknown key stops with exit code 2 and the list of keys.

### 9.4 `devices` and `pair`

```
$ spoolwarden devices
NAME        PAIRED            LAST SEEN         ID
Shop phone  2026-10-02 18:11  2026-11-12 14:05  d7
Studio PC   2026-10-03 09:40  2026-11-12 07:30  d8
Hub page    built in: this Hub's own pairing    d1
```

- Built-in pairings cannot be forgotten: `Error: Hub page is built in: it is this Hub's own pairing.`
- Empty: `Nothing paired yet.` then `Pair a phone: sudo spoolwarden pair`.

**`pair`** prints, in the Hub page's order: the QR code (phone only), the instruction, the pairing code, the
certificate fingerprint, the expiry; then waits for the device to pair.

```
$ sudo spoolwarden pair
(QR code)
Open the Spoolwarden app and scan this code, or type the pairing code.
Pairing code: 482 913
Certificate fingerprint (the phone asks for two groups of it):
  1111 2222 3333 4444 5555 6666 7777 8888
  9999 AAAA BBBB CCCC DDDD EEEE FFFF 0000
Expires at 14:20 (in 10 min).
◐ Waiting for the phone… (the code works until 14:20)
Paired: Shop phone.
```

- `--slicer-sync`: `Paste this link into the Slicer Sync when it asks:` then the link alone on its line, never
  wrapped (it may be wider than the terminal; the terminal wraps it, but it is one line to copy).
  `--weigh-station`: `On the Weigh Station run: sudo spoolwarden weigh-station pair, then paste this link:`.
- No QR possible: none; the Hub draws the QR code itself (section 13), so no note is needed.
- `--text` prints the link and code without the QR code.
- Ctrl-C stops waiting; the code stays valid until it expires (`Stopped waiting. The code works until 14:20.`).
- The pair command on a machine without the Hub service feature: `Error: this machine has no Hub, so it cannot pair
  devices.` with `Fix: run it on the Hub.`

### 9.5 `presets` (Slicer presets)

| Command | Output |
|---|---|
| `presets status` | Lines in the Hub page's order: `Lines: 14.`; `Last build 2026-11-12 03:05. Presets: 48 (12 for Orca Slicer). Problems: none.` (or `No build yet.`); the last attempt's error, if any; the waiting text; `Installed on the PC: the build of 2026-11-12 03:05, written 2026-11-12 07:30.` or `Installed on the PC: nothing yet.`; `Slicer Sync: last reported 2026-11-12 07:30.` or `▲ needs a look  Slicer Sync: not set up.` with `Fix: sudo spoolwarden pair --slicer-sync`; `Updates: 3 on 2 lines. Presets already in your slicers are never replaced unless you accept them.`; `Delete in Bambu Studio: <name>` and `Delete in Orca Slicer: <name>` lines; problems as `▲ needs a look` lines |
| `presets build` | Runs the build here and waits for it, as today, with `◐ Building the Slicer presets…` (section 6.6). Then `● done  Presets built: 48. Problems: none.` or `● done  Presets built: 48. Problems: 2:` followed by one `▲ needs a look  <problem>` line per problem (exit 0). Still waiting for the Slicer Sync's first run: `i note  <the Hub's waiting text>` (exit 0). Failed: `× failed  The build failed: <why>. The last good build stays in use.` with `Fix: see what it logged: sudo spoolwarden logs <the build's service>` (exit 1). |
| `presets lines` | Table `ID`, `LINE` (long column), `MATERIAL`, `PRESETS`; under each row two dim detail lines: `parents: Bambu Studio <name> (<source>) · Orca Slicer <name> (<source>)` and `filaments: 86, 88` (or `filaments: none`). Empty: `No lines yet. They are made from the Spoolman filaments at the next build or addition.` |
| `presets set-parent` | `Saved. A build was asked for.` When the Slicer Sync has reported no parents: `Error: the Slicer Sync has not reported any parents yet. It reports them when it runs.` |
| `presets restore-deleted` | `The next build brings back the presets deleted in Bambu Studio. A build was asked for.` |
| `presets updates` | One line per update: `PolyTerra PLA  Bambu Studio: <preset> (in your file <file>): <up to 6 keys>`; then `3 updates would be accepted; nothing was changed.` / `No updates to accept.` |
| `presets accept-updates` | The same list, the question of section 7, then `3 updates accepted; the Slicer Sync writes them at its next run, after its backup.` If the list changed meanwhile: `Error: the updates changed since this list.` with `Fix: run it again to see them.` |

### 9.6 `features`

```
$ spoolwarden features
Setup: Hub with Weigh Station

FEATURE                       KEY                 STATE  NEEDS
Spoolman                      spoolman            ● on
Hub service                   hub                 ● on   Spoolman
Label Reader: Cloud (Claude)  label-reader        ● on   Hub service, API key
Label Reader: On this Hub     label-reader-local  ○ off  Hub service
Bambu Lab printers            printers            ● on   Hub service
...
```

Feature names (titles as in Features on the Hub page, `03-hub-page.md` section 9.1, except Cloud (Claude),
which follows foundations section 2; `uses AI` marks the optional AI features):

| Title | Key | Old key |
|---|---|---|
| Spoolman | `spoolman` | `spoolman` |
| Hub service | `hub` | `server` |
| Label Reader: Cloud (Claude) (uses AI) | `label-reader` | `ai_intake` |
| Label Reader: On this Hub (uses AI) | `label-reader-local` | `local_intake` |
| Bambu Lab printers | `printers` | `printers` |
| Klipper printers | `klipper` | `klipper` |
| Slicer presets | `presets` | `presets` |
| Filament Catalog | `catalog` | `library` |
| Nightly backup | `backups` | `backup` |
| Weigh Station | `weigh-station` | `station` |
| Web access | `web` | `web` |
| Remote access | `remote` | `remote` |
| Order history | `orders` | `orders` |
| Automatic updates | `updates` | `updates` |

Setups: `hub` (old `server`), `weigh-station` (old `station`), `hub-with-weigh-station` (old `all-in-one`); a
custom choice shows as `custom`.

| Command | Output |
|---|---|
| `features on <feature>` / `off <feature>` | The `Also turn on|off …?` questions (section 7), then the plan, then the setting prompts of 8.5 when needed, then `◐ Applying the changes…` and `Features applied: …` or `Unchanged.` `--hub ADDRESS` answers the Hub's address prompt. Not at a terminal and a question needed: exit 2 with `Fix: add --yes to accept the cascade, or switch the others first.` |
| `features setup <setup> [--hub ADDRESS]` | `Setup: Weigh Station only.` then the plan and the apply. The Weigh Station only setup needs the Hub's address (`--hub`, or asked). |
| `features apply [--no-pair]` | `Setup: Hub with Weigh Station (Spoolman, Hub, …).`, `Weigh Station answers at: 192.0.2.10`, the apply, and the pairing code of 9.4 unless `--no-pair` |
| `features units` | One service file name per line (for the installer) |

Refusals use the Hub's text, for example switching the Hub off from the Hub page's own feature:
`Error: the Hub page belongs to the Hub service; switch it off on the Hub itself.` with
`Fix: sudo spoolwarden features off hub`.

### 9.7 `weigh-station` and `tag-reader`

| Command | Output |
|---|---|
| `weigh-station pair` | Prompts (8.7), then `Paired with the Hub at 192.0.2.10.` |
| `weigh-station pair --local` | For a Hub with Weigh Station: `The Weigh Station on this machine is paired with this Hub.` |
| `weigh-station flash-display` | `◐ Stopping the Weigh Station service…`, the list of blank boards found, one question each (section 7), `◐ Writing the firmware to /dev/ttyACM0… 45 %`, `● done  The display answered.`, `Started the Weigh Station service again.` No board: `No blank display board found on USB.` with `Fix: plug the display in with a data cable, then run this again.` |
| `weigh-station pairing-state` | `paired with 192.0.2.10:8710` / `not paired` / `not checked yet` (the `--json` `state` keeps the values `paired`, `unpaired`, `unchecked` for scripts; see the root wrapper below) |
| `tag-reader list` | Table `ID`, `NAME` (long column), `MADE`. Empty: `No Tag Reader tokens.` then `Make one: sudo spoolwarden tag-reader new-token --name bench` |
| `tag-reader new-token` | `New Tag Reader token tr3 (bench):`, the token alone on its line, then `Shown only this once. tag-reader flash puts it on the reader for you.` |
| `tag-reader revoke` | section 7 |
| `tag-reader flash` | Prompts (8.7), `Tag Reader on USB: /dev/ttyACM0.`, `◐ Writing the firmware… 45 %`, then `Done. The Tag Reader joined "HomeNet" and reached the Hub.` On a failure, the step that failed: `× failed  The Tag Reader did not join "HomeNet".` with `Fix: check the Wi-Fi name and password, then run: sudo spoolwarden tag-reader flash --reflash`. Without `--ota-pubkey`: `Note: without --ota-pubkey this Tag Reader refuses every update over Wi-Fi until it is flashed again with one.` |

The other options of today's `reader setup` keep their names and meaning under `tag-reader flash`:

| Option | Meaning |
|---|---|
| `--name NAME` | The token's name |
| `--port PORT` | The board's USB serial port; found by itself when one board is plugged in |
| `--source FOLDER` | Build the firmware from this source folder and write it |
| `--out FILE` | Write the reader's secrets file here (mode 0600) to build elsewhere; nothing is written to a board |
| `--secrets FILE` | Write a secrets file made earlier with `--out` (needs `--source`) |
| `--ota-pubkey FILE` | The public key that updates over Wi-Fi are signed with |
| `--token-file FILE` | Use a token made on the Hub (`tag-reader new-token`) instead of a new one |
| `--base URL` | The Hub's reader address when this machine is not the Hub: `<public address>/reader` |

**The root wrapper.** The installed command is a small shell wrapper (`install/filament-kit-cli.sh` today) that
runs each command as root or as the Hub's service account. It keeps two jobs for scripts, and the command line
keeps them working:

- For `status` run as root on a machine with a Weigh Station pairing folder, it runs
  `weigh-station pairing-state --json` and passes the `state` value on as
  `status --weigh-station-pairing=<state>` (`failed` when the command fails). It reads only the `--json` value,
  never the text, so the text above may change without breaking it.
- For `catalog add <file>` (and the old `library add <file>`) run as root, it opens the file as root, because the
  service account may not be able to read a file in the caller's home folder, and runs `catalog add -` with the
  file on standard input. A file that is missing or cannot be read stops with exit code 2:
  `Error: there is no readable file at <file>.` and `Fix: give the path of one catalog entry as a JSON file.`

### 9.8 `config show`, `config set`, `config theme`

**`config show`** prints every setting in the menu's order, one group heading per group, `Label  value` lines,
secrets as `set` / `not set`.

```
$ spoolwarden config show
Appearance
  Theme for new devices    Console
General
  Display name             Workshop hub
Storage locations
  Locations                Shelf A, Shelf B, Dry box 1, Dry box 2
  PLA rack                 Shelf A
  ...
```

**`config set <key> <value>`** changes one setting with the keys of section 8.3, checked as the menu checks them.
`Saved: PLA rack is Shelf B.` A setting that restarts the Hub shows the restart wait. A secret cannot be set
this way (`Error: the Anthropic API key is a secret. Fix: sudo spoolwarden config, Label Reader.`). An unknown
key stops with exit code 2 and lists the keys.

**`config theme [<theme>]`** shows or sets the Hub's theme for new devices: devices that have not chosen a theme
open in it; devices that chose keep theirs (foundations section 6.2). Names: `console`, `workbench`, `palette`,
`panes`, any case.

```
$ spoolwarden config theme
Theme for new devices: Console (dense and technical; the default).

$ sudo spoolwarden config theme workbench
Theme for new devices: Workbench (calm cards).
Devices that already chose a theme keep theirs.

$ sudo spoolwarden config theme dark
Error: there is no theme called "dark".
Fix: choose console, workbench, spool or panes. Light and dark are chosen on
     each device, in Settings > Appearance.
```

### 9.9 `label-reader`

**`label-reader status`** prints the Label Reader group of `status` (9.1), preceded by the engine order:

```
$ spoolwarden label-reader status
Label Reader
  ● on            Engine order: On this Hub, then Cloud (Claude)
  ● OK            Cloud (Claude): the API key works
  ◆ note          Reads used today: 12 of 40
  ● OK            On this Hub: answering at http://192.0.2.10:7915 (tier: cpu)
```

**`label-reader test <photo>... [--engine cloud|local]`** reads label photos (files on the Hub) with the chosen
engine, or with the engine order when none is given, and prints the fields with their confidence. Nothing is
added and no record is made.

```
$ sudo spoolwarden label-reader test label-1.jpg label-2.jpg
◐ Reading 2 photos with On this Hub… 9 s
Read by On this Hub (tier: cpu) in 11 s. Nothing was added.

  Brand         Polymaker                     ● high
  Name          PolyTerra PLA Charcoal Black  ● high
  Material      PLA                           ● high
  Colour        #2B2B2E (black)               ▲ medium
  Net weight    1000 g                        ● high
  Price per kg  (empty)                       ○ not on label
```

- An engine that is off or not installed: `Error: On this Hub is not installed.` with
  `Fix: sudo spoolwarden features on label-reader-local`.
- A Cloud test counts toward the reads used today and says so: `Note: this used 1 of today's 40 reads.`

### 9.10 `backup` and `restore`

```
$ sudo spoolwarden backup list
Nightly backups are kept 14 days.

MADE              KIND       SIZE       NAME
2026-11-12 03:00  nightly    4,812 KiB  backup-2026-11-12-0300.zip
2026-11-11 03:00  nightly    4,790 KiB  backup-2026-11-11-0300.zip
2026-11-10 16:32  made here  4,771 KiB  backup-2026-11-10-1632.zip

Folder: <backup folder on this Hub>
```

- `KIND` uses the Hub page's words: `nightly`, `made here`, `before a restore`.
- Empty: `No backups in <folder> yet.` then `Back up now: sudo spoolwarden backup create`.
- `backup create`: `◐ Backing up…` then `Backup written: <path>` and the Hub page's warning on one line:
  `Note: the zip is not encrypted and holds the setup secrets: store it somewhere safe.`
- `backup keep 14`: `Backups are kept for 14 days.`
- `restore <zip>` (or `--uploaded` for a zip uploaded on the Hub page) prints the Hub page's summary, then asks
  for the typed word (section 7):

  ```
  Backup of Workshop hub made 2026-11-12 03:00 by Spoolwarden 0.5.2:
  412 files and the Spoolman database. Features: Spoolman, Hub, Label Reader…
  This replaces the spools, settings, printers and pairings on this Hub.
  What is here now is saved as a backup first.
  The Hub restarts, and afterwards the setup code is the one from the backup.
  Type restore to go on:
  ```

  Then `◐ Restoring…` and `● done  Restored. The Hub is back.`

### 9.11 `catalog` (Filament Catalog)

| Command | Output |
|---|---|
| `catalog status` | `Filament Catalog version 2026.11.2 (signed release), 3 local additions.` or `The Filament Catalog is not downloaded yet.` with `Fix: sudo spoolwarden catalog update`; `Source: <the address it downloads from>`; `Last check 2026-11-12 03:10: ok.`, `Last check 2026-11-12 03:10: failed: <why>.` or `Last check: never.`; the skipped text, if any |
| `catalog update` | `◐ Updating the Filament Catalog…`, then the Hub's note as `Note: …` if any, then `Up to date: 2026.11.2.` or `Installed 2026.11.3 (N entries downloaded).` and the skipped text, if any. Failed: `× failed  <the Hub's text>` (exit 1). With `--scheduled` (the timer's run): `Filament Catalog updates are off.` or `Not due yet.` when it has nothing to do; when the source is a private repository that is not published yet (or the token cannot read it), `Note: <the Hub's text>. The version in use stays.` on standard error and exit 0, since the timer's run has not failed |
| `catalog rollback` | section 7 |
| `catalog add <file \| ->` | `Added Polymaker PolyTerra PLA. A preset build follows.` / `Error: entry not added: larger than <limit> KiB.` (the limit the Hub checks) |
| `catalog adopt <folder>` | `Took over the catalog in <folder>: N local additions.` |
| `catalog token` | prompt (8.7), then `Saved the catalog token.` |

### 9.12 `web`, `remote`, `setup-code`, `certificate`, `spoolman`

| Command | Output |
|---|---|
| `web status` | Rows in the 9.1 form under the heading `Web access`, in the order of the table below |
| `web passphrase` | prompts (8.7), then `Passphrase saved.` |
| `remote firewall` | `Spoolwarden never changes your firewall or router. These are the rules to add:` then the rules, each on its own line |
| `remote get-certificate` | section 7, then `Note: certbot listens on port 80 of this Hub now. Spoolwarden does not open it: your router must forward it here.`, `◐ Getting the certificate…`, then `● done  Certificate issued for hub.example.` or `× failed  The certificate was not issued: <why>.` with `Fix: check that hub.example points at this Hub and port 80 reaches it, then run this again.` (exit 1). Remote access off: `Error: Remote access is off.` with `Fix: sudo spoolwarden features on remote` (exit 1) |
| `setup-code` | At a terminal: `Open https://192.0.2.10:8710/setup  (setup code: 1234-5678)`. Not at a terminal, only the address and `Note: the setup code is shown at a terminal only.` |
| `setup-code --new` | section 7, then the new code and `The old setup code no longer works.` |
| `setup-code --revoke-trusted` | section 7, then `2 trusted computers revoked. Each needs the setup code again.` |
| `certificate` | `Certificate present.` or `Made a new certificate.`, then `Fingerprint:` and the groups of four, two lines of eight groups |
| `spoolman fields` | `Spoolman: added Spoolwarden's extra fields: <names>.` or `Spoolman: Spoolwarden's extra fields are in place.` |
| `spoolman address` | `Spoolman in use: http://192.0.2.10:7912.` With a URL: `◐ Checking http://spoolman.example:7912…`, then `Saved. Spoolwarden now uses the Spoolman at http://spoolman.example:7912.` or `Error: nothing was changed: no Spoolman answered at that address.` |

`web status` rows (the Fix column is printed only when the row needs a look; a note's Fix follows as a detail
line):

| Row | OK form | Other forms | Fix |
|---|---|---|---|
| Feature | `● OK  Web access is on` | `▲ needs a look  Web access is off` | `sudo spoolwarden features on web` |
| Public address | `● OK  Public address https://hub.example/filament` | `▲ needs a look  Public address not set` / `▲ needs a look  Public address https…: not an https address` | `sudo spoolwarden config set web.public_url https://hub.example/filament` |
| Where to find it (detail, only with a public address) | `Claude's connector: https://hub.example/filament/mcp · web app: https://hub.example/filament/intake` | | |
| Web passphrase | `● OK  Web passphrase set` | `i note  Web passphrase not set: Claude's connector cannot sign in until one is set` | `sudo spoolwarden web passphrase` |
| Health | `● OK  The web app answers on this Hub (port 8101)` | `▲ needs a look  The web app does not answer on this Hub (port 8101): <why>` | `sudo systemctl restart <the web app's service>, then see its log: sudo spoolwarden logs <that service>` |
| Certificate (only with Remote access on, only when there is something to say) | (no row) | expired: `▲ needs a look  <the Hub's certificate text>`; expiring soon: `i note  <the Hub's certificate text>` | the Hub's fix text |
| Connectors (detail) | `Claude's connectors: 2 registered, 1 signed in` | `Claude's connectors: none signed in yet` / `Claude's connectors: shown with sudo only` | |
| Printer slots (detail) | `Printer slots from: the Hub's printer connection · Tag Readers: 2, and the Weigh Station` | `Printer slots from: none` / `… · Tag Readers: 0, no Weigh Station` | |

### 9.13 `update` and `uninstall`

| Command | Output |
|---|---|
| `update --check` | `◐ Checking for updates…`, then `Installed: 0.5.2.` and `Latest release: 0.5.3.` or `Latest release: 0.5.2 (up to date).`; the Hub page's held and failed lines when they apply; `Checked by itself <schedule> (the Automatic updates feature).` or `Not checked by itself: the Automatic updates feature is off.` |
| `update` | section 7, `◐ Updating to 0.5.3…` with the installer's lines dim below it, then `● done  Installed 0.5.3. The Hub is back.` or `× failed  Updating to 0.5.3 failed.` with the log's last lines and `Fix: see the whole log: sudo spoolwarden logs`. Nothing newer: `No updates available: 0.5.2 is the latest.` On a Hub that still runs a nightly build, update installs the latest signed release over it and prints: going back to the signed release <latest>. |
| `update --rollback` | section 7, `◐ Rolling back to 0.5.1…` with the installer's lines dim below it, then `● done  Rolled back to 0.5.1. The Hub is back.` or `× failed  Rolling back to 0.5.1 failed.` with the log's last lines and `Fix: see the whole log: sudo spoolwarden logs` (exit 1). Nothing kept: `Error: no earlier version is kept, so there is nothing to roll back to.` |
| `uninstall [--purge]` | section 7, then `◐ Removing Spoolwarden…` with the removal script's own lines dim and indented below it as they arrive (section 6.6), then `Spoolwarden is removed from this machine.` (exit 0) or `× failed  The removal stopped: <the script's last line>.` (exit 1). The removal script is the one kept with the installed release; when only an older release is kept: `Note: using the removal script of 0.5.1, the newest kept release; no copy of 0.5.2 is kept.` When none is kept: `Error: no copy of a release is kept, so there is no removal script to run.` with `Fix: download spoolwarden-0.5.2.tar.gz from the releases page, unpack it, then in its folder run:` and `sudo ./uninstall.sh` on its own line (with ` --purge` when given) |

A stopped half-install is shown by `status` and `update --check`: `▲ needs a look  The last install or update
stopped halfway.` with the repair command as its Fix.

`update --feed` stays a hidden option: the installer runs the new program with it to finish an update. It is not
in `-h` and prints nothing of its own beyond the update's lines.

### 9.14 `logs`

`spoolwarden logs [<service>] [--lines 50|100|200]` prints the end of a service's log (default: the Hub's,
100 lines). `<service>` is one of the services the switched-on features run; without a match the error lists
them. The command needs sudo and shows the log in full (addresses and serials included); the Hub page hides
them until the setup code is given. Empty: `Nothing logged.` Cut: `Only the last 100 lines are shown.` and
`Fix: for more, run journalctl -u <service>`.

### 9.15 `migrate-ops` and `migrate-scanner`

Unchanged in behaviour. `migrate-ops` without `--apply` is a dry run and says so on its first line:
`Dry run: nothing is moved. Add --apply to move it.` Both end with a summary line and use the error and Fix rules
of section 6.5.

## 10. What the command line cannot do

Some features need a camera, NFC or a screen for photos. Where a person might look for them on the command line,
the command prints one line saying where they are, with the address to open, and exits with code 0. When the
line and the address do not fit the width together, the address goes on the next line. With `--json`:
`{"available": false, "where": "web app", "url": "…"}`.

| Feature | Command | The line it prints |
|---|---|---|
| Live printer view: camera, pause, resume, stop, light, load and unload a spool | `printer live <printer>` | `Camera and controls are in the web app: https://192.0.2.10:8710/intake#printers` |
| Add spools, from label photos or by hand | `add` | `Add spools in the web app, app or Weigh Station: https://192.0.2.10:8710/intake` |
| Open a spool, link a tag, set its weight, move it, mark it empty, search spools, filament used, add a filament line | `spool` | `Spools are opened and tagged in the web app or app: https://192.0.2.10:8710/intake` |
| The photos of a Recently added record | `recent show <record>` | `Photos open on the Hub page: https://192.0.2.10:8710/setup#recent/35` (`--photos` adds their file paths) |
| Light / Dark / System, a device's own theme | (none) | The terminal's own colours apply (section 6.2); `config theme` sets only the Hub's theme for new devices |

Flashing a device from the computer in front of the person (Web Serial on the Hub page) has no command-line
form; the command line flashes boards plugged into the Hub itself (`tag-reader flash`,
`weigh-station flash-display`).

## 11. Usability problems and their fixes

The current command line has these problems; each has a fix in this design.

| # | Problem today | Fix | Section |
|---|---|---|---|
| 1 | `config` saves on leaving, with no way to discard; Ctrl-C is not handled. | Changes are staged; `s` saves; `q` with changes asks `Leave without saving …?`; Ctrl-C and end of input leave without saving and say so. | 8.2, 8.3 |
| 2 | Each screen leaves differently (`0`, `q`, Esc, Enter, Ctrl-C). | One key map: `q` (and Esc) leaves every menu, checklist and walkthrough; an empty answer leaves every prompt; Ctrl-C always leaves at once. `0` is no longer used. | 8.2 |
| 3 | Destructive commands do not ask (`unpair`, printer remove, catalog roll back, accepting preset updates) while harmless ones do. | Every destructive command asks, with the Hub page's words; `--yes` for scripts; no terminal and no `--yes` refuses. Harmless changes do not ask. | 7 |
| 4 | Printer commands need a serial and nothing lists printers outside `config`. | `printer list` and `printer show`; every `<printer>` takes a name, serial, id or unique start of a name; Klipper commands moved under `printer`. | 5, 9.2 |
| 5 | The Printers submenu numbers printers and actions in the same screen. | Numbers are only for items, letters only for actions, on every screen. | 8.2, 8.4 |
| 6 | Blank answers in `config` are ignored silently. | Every prompt answers: `Unchanged.` or `Changed, not saved yet.` | 8.3 |
| 7 | Some errors go to standard output, others to standard error. | Every error goes to standard error, also in menus, as `Error:` plus `Fix:`. | 6.5 |
| 8 | No machine-readable output and no quiet mode; scripts parse `status` text. | `--json` on every command that prints data, in the Hub's own reply shapes; `--quiet`; documented exit codes. | 6.7, 6.8 |
| 9 | Waits of up to 30 seconds print nothing. | A progress line after 2 seconds for every wait, with elapsed seconds and how to stop. | 6.6 |
| 10 | Pairing fell back silently from QR to a raw link when `qrencode` was missing; long links are printed raw. | The Hub draws the QR code itself (segno), so none goes missing; links are labelled and printed alone on their line, unwrapped; the Hub renders QR codes itself. | 9.4, 13 |
| 11 | The checklist's key help is cut at narrow widths; below 40 × 8 it switches silently to a numbered list with other keys. | A short key line that fits 40 columns, `?` for all keys; a `Note:` says why the list is numbered; both variants share the same keys; `--numbered` chooses it on purpose. | 8.1, 8.2, 8.5 |
| 12 | What a feature needs, or switches off with it, shows only after switching. | The footer shows needs and cascade for the cursor row before switching; the plan line shows every change before applying. | 8.5 |
| 13 | The user guide's command list misses commands and `config` items. | `spoolwarden help --markdown` is the source of the user guide's command table. | 3.2 |
| 14 | `ensure-fields` and `cert` are found only through a failure's fix text. | Renamed `spoolman fields` and `certificate`, listed in help under System; every status row that needs a look names its command in its Fix line. | 3.1, 9.1 |
| 15 | Messages use internal words (`lane_data`, module names, `lasttag`). | Messages use the names of foundations section 2 and the Hub page's labels; code names only where typed. | 6.4 |

## 12. Parity

The same feature table as for the other interfaces, with the new names. Marks: **Y** present, **P** partly,
**N** not present, **-** not applicable, **unknown** not established, **new** specified in this design system but not built yet. The app,
Hub page and web app columns show what exists today; the last two columns show the command line today and in
this design.

| Feature | app | Hub page | web app | Command line today | Command line in this design | Gap |
|---|---|---|---|---|---|---|
| Pair a phone or device (QR and code) | Y | Y | - | Y | Y, and waits for the device | none |
| List and forget paired devices | P | Y | N | Y (forget without asking) | Y (`devices`; asks) | web app: remains |
| Hub status and checks | P | Y | N | Y | Y, grouped as Overview, `--json` | web app, app: remain |
| Add spools by hand | Y | N | Y | N | N (`add` prints where) | remains: needs a phone or the Weigh Station |
| Add spools from label photos | Y | N | Y | N | N (`add`); `label-reader test` reads photos without adding | remains: needs a camera |
| Open a spool: link a tag, set weight, move, mark empty | Y | N | Y | N | N (`spool` prints where) | remains: needs NFC or a camera |
| Search spools | Y | N | N | N | N (`spool`) | remains |
| Add a filament line | Y | N | N | N | N (`spool`) | remains |
| Slicer presets: status, change parent | P | Y | Y | Y | Y | none |
| Slicer presets: build, restore deleted, accept updates | N | Y | N | Y (accepts without asking) | Y (asks) | app, web app: remain |
| Recently added: list, show | N | Y | Y | Y | Y | app: remains |
| Recently added: revise, edit, undo | N | Y | Y | Y | Y | app: remains |
| Records kept (Recently added setting) | N | Y | N | Y | Y | none for the command line |
| Printer list; add a Bambu Lab printer with its Access Code | Y | Y | Y | P (inside `config` only) | Y (`printer list`, `printer add`) | **closed** |
| Add a Klipper printer | N | Y | Y | Y | Y (`printer add --klipper`) | app: remains |
| Find Klipper printers | N | Y | P | Y | Y (`printer scan`, `use`, `dismiss`) | none for the command line |
| Test, rename, change address, replace Access Code or API key, lane data, detect, forget certificate, forget printer | Y | Y | Y | P (rename and remove in `config`; unpin; API key) | Y (one `printer` command each) | **closed** |
| Live printer view: camera, pause, resume, stop, light | Y | P (link) | Y | N | P: state and slots in `printer show`; `printer live` prints where | remains: needs a screen for the camera |
| Map slots | Y | Y | Y | Y | Y | none |
| Map by loading filament | Y | Y | Y | Y | Y | none |
| Collect a printer report | Y | Y | Y | Y | Y | none |
| Saved printer reports | unknown | Y | unknown | N | Y (`printer reports`) | **closed** |
| Load or unload a spool in a slot | Y | N | Y | N | N (`printer live` prints where) | remains |
| Filament used, with undo | Y | P | Y | N | N (`spool` prints where) | remains |
| Features on and off | N | Y | N | Y | Y, needs shown before switching | none for the command line |
| Choose the setup | N | Y | N | Y | Y (`features setup`) | none for the command line |
| Backups: make, list, download | N | Y | N | Y | Y | none for the command line |
| Keep nightly backups for N days | N | Y | N | N | Y (`backup keep`, `config`) | **closed** |
| Restore from a backup | N | Y | N | Y | Y | none for the command line |
| Updates: check, install, roll back | P | Y | N | Y | Y | web app: remains |
| Anthropic API key: set, check, remove | N | Y | N | Y | Y (`config`, Label Reader) | none for the command line |
| Web passphrase | N | Y | N | Y | Y | none for the command line |
| Catalog token | N | Y | N | N | Y (`catalog token`, `config`) | **closed** |
| Setup code: show, new; revoke all trusted computers | N | Y | N | Y | Y (new code asks) | none for the command line |
| Trusted computers: list, rename, revoke one | N | Y | N | N | N | remains: Hub page only |
| Weigh Station: pair, flash the display | N | Y | N | Y | Y | none for the command line |
| Weigh Stations asking to pair | N | Y | N | N | N | remains: Hub page only |
| Tag Reader tokens | N | Y | N | Y | Y | none for the command line |
| Flash a Tag Reader | N | new (Flash a device) | N | Y | Y (`tag-reader flash`) | none for the command line |
| Filament Catalog: status, update, roll back, add | N | Y | N | Y (roll back without asking) | Y (asks) | none for the command line |
| Logs | N | Y | N | P (fix lines only) | Y (`logs`) | **closed** |
| Remote access: certificate, firewall rules | N | Y | N | Y | Y | none for the command line |
| Spoolman: extra fields | N | Y | N | Y | Y (`spoolman fields`) | none for the command line |
| Spoolman: change the address in use | N | Y | N | N | Y (`spoolman address`) | **closed** |
| Move in from older tools | N | N | N | Y | Y | command line only, by design |
| Uninstall | N | N | N | Y | Y (asks) | command line only, by design |
| Licences | Y | N | N | N | N | remains |
| Light / Dark / System | Y | Y | Y | - | - (follows the terminal) | not applicable |
| Themes | new | new | new | - | `config theme` sets the theme for new devices | **closed** for the Hub's default |
| Label Reader: status and test | N | new | P (shows the engine on a result) | N | Y (`label-reader status`, `test`) | **closed** |

Gaps marked "remains" outside the command-line column are specified in the documents of those interfaces.

## 13. Needs from the Hub

The command line calls the same code as the Hub page's routes (`/setup/api/...`) or the Hub's own API
(`/api/info`, `/api/printers/<serial>/...`). The design above needs these from the Hub:

1. **Theme for new devices.** A stored Hub setting (`appearance.theme`, values `console`, `workbench`, `palette`,
   `panes`; default `console`), written by `config theme` / `config set` and by the Hub page's Settings >
   Appearance, and delivered to the Hub page, the web app and the app so a device that has not chosen opens in
   it. No such setting exists today.
2. **Grouped status rows.** Each status row (`status.Row`) carries a `group` (Hub, Spoolman, Label Reader, Weigh
   Station, Devices, Printers, Slicer presets, Filament Catalog, Web access; a group is shown only when it has rows), and the Printers group has one row per printer
   with its state and one row per printer problem. `GET /setup/api/overview` returns the same rows, so the
   Overview and `status` show the same groups in the same order.
3. **Hub messages in the new words.** Error texts in Hub replies and Fix texts in status rows are printed as they
   come, so they must use the names of foundations section 2 and the commands of section 4 (`spoolwarden …`,
   not `filament-kit …`; Features, not modules; Weigh Station, not station).
4. **QR codes drawn by the Hub.** The Hub renders pairing QR codes itself, for the Hub page (`qr_svg`) and as
   terminal text for `pair`, so pairing never loses its QR code because a package is missing. Any bundled code
   follows foundations section 12, rule 1.
5. **The Label Reader's On this Hub engine.** Its settings (`intake.reader`, `local_intake.url`,
   `local_intake.tier`), its health check and its test are not in a released Hub yet. Until they are,
   `label-reader status` shows the Cloud engine only, and `label-reader test --engine local` says
   `Error: On this Hub is not installed.`
6. **A setup word for the Weigh Station only setup.** The Hub page's setup and the `--hub ADDRESS` option need the
   new setup names (`hub`, `weigh-station`, `hub-with-weigh-station`) accepted by the Hub's mode code beside the
   old ones (`server`, `station`, `all-in-one`).
