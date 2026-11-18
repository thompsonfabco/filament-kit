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

The groups appear in the order of the Hub page's navigation (foundations section 8): Everyday, then System.
Running `spoolwarden` with no command prints the same text.

```
$ spoolwarden -h
Spoolwarden on this Hub. Commands marked (sudo) in their own help need sudo.
Usage: spoolwarden <command> [options]    More: spoolwarden <command> -h

Everyday
  status           What works and what needs a look
  printer          List, test, map and manage printers
  klipper          The Klipper add-on
  recent           Recently added spools: show, correct, undo
  spools           Find spools; spools running low
  spool            One spool: show, weigh, move, empty, label
  events           What happened on the Hub: show, follow
  activity         What was done on the Hub: who, what, when
  undo             Put back the last change made here
  usage            Filament used: this month, by month
  devices          Paired devices: kind, version, show, set
  pair             Pair a phone, the Slicer Sync, a Weigh Station or Home Assistant
  weigh-station    Weigh Station: pair it, flash its display
  tag-reader       Tag Readers: tokens, flash one over USB
  presets          Slicer presets: build, status, parents, updates

System
  features         Switch features on and off; choose the setup
  config           Settings menu; also config show, set and theme
  locations        Storage locations: the list, add, edit, move, remove
  export           Download Spoolwarden's data as CSV files
  import           Add spools or locations from a CSV file
  alerts           What Spoolwarden warns you about: switches, limits, test
  label-reader     Label Reader: status, test, corrections to share
  catalog          Filament Catalog: status, update, roll back, add, your own entries
  backup           Make or list backups; the backup password
  restore          Restore this Hub from a backup
  web              Access from outside the home, and Claude's connector
  remote           Remote access: certificate and firewall rules
  setup-code       The Hub page's address and setup code
  port             The Hub's port: show or change
  certificate      The Hub's certificate and its fingerprint
  spoolman         Spoolman: its address and Spoolwarden's extra fields
  update           Check, install or roll back Spoolwarden
  uninstall        Remove Spoolwarden from this machine
  logs             The end of a service's log
  report           Collect a Hub report for a problem
  language         Languages: list, add, remove, set, make and check a pack
  demo             The demo: made-up data to look around in

Every command: -h  --json  -q/--quiet  -y/--yes  --color auto|always|never
               --plain  --no-progress  --lang <code>
```

### 3.2 Every command

`<printer>`, `<device>`, `<reader>` and `<record>` are explained in section 5. Square brackets mark optional
parts. The last column names the place on the Hub page that does the same thing, so the two stay in step.

| Command | What it does | Hub page place |
|---|---|---|
| `status` | Checks everything and prints one row per check (9.1) | Overview |
| `status --history [--days 7\|30]` | The changes of the checks over the last 7 or 30 days, as a table (9.1) | Overview, Show history |
| `printer list` | All printers, set up and found (9.2) | Printers |
| `printer show <printer> [--watch]` | One printer: details and slots; `--watch` shows state, job, progress and temperatures too, redrawn every 2 s (9.2) | Printers, expanded row, live view |
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
| `printer live <printer>` | Prints where the camera is (section 10) | Show camera |
| `printer load <printer> <slot> <spool>` | Load a spool into a slot (asks); with `auto` for the slot, into whichever slot gets a spool next | Load, Load a spool |
| `printer unload <printer> <slot>` | Unload the spool of a slot (asks) | Unload |
| `printer clear <printer> <slot>` | Clear slot: the Hub forgets the spool recorded there (asks) | Clear slot |
| `printer usage <printer> [--days N]` | Filament used by the printer, newest first | Filament used |
| `printer menu` | The Printers screen (8.4) | Printers |
| `klipper add-on` | Prints the commands that install the Klipper add-on | Klipper add-on |
| `recent` (same as `recent history`) | Recently added records (9.3) | Recently added |
| `recent show <record> [--photos]` | One record: fields, confidence, revisions | Record detail |
| `recent revise <record> --note TEXT [--item N]` | Ask the Label Reader to correct it | Ask the Label Reader to correct it |
| `recent edit <record> field=value... [--item N] [--spools 41,42]` | Edit by hand | Edit by hand, Save changes |
| `recent undo <record>` | Undo the newest revision that is not undone | Undo revision N |
| `spools low` | The opened spools at or under the running-low threshold (9.18) | Overview, Running low |
| `spools [<words>] [--sealed \| --opened \| --loaded \| --low]` | Find spools; the last line is `Spoolman: <address>` (9.21) | Spools |
| `spool show <n>` | One spool: facts, place, tag, last use (9.21) | Spools, one spool |
| `spool weigh <n> <grams>` | Record the weight with the spool (previews, asks) | Update weight |
| `spool move <n> <location \| auto>` | Move a spool (previews, asks) | Move |
| `spool empty <n>` | Mark a spool empty (asks) | Mark empty |
| `spool label <number>... [--size 62x29\|50x30\|sheet24] --out <file.svg>` | Write the labels of these spools as one SVG file (9.21) | Print a label, Print labels |
| `events [--since ID\|TIME] [--kind PREFIX] [--follow]` | The Hub's events, newest last; `--follow` keeps printing new ones (9.16) | Settings > Alerts > Recent alerts (alerts only) |
| `activity [--spool <n>] [--who <name>] [--days 7]` | What was done: time, who, what, newest first (9.22) | Logs > Activity |
| `undo [<event id>] [-y]` | Put back the last change made from the command line, or the named event (shows it, asks) (9.23) | Undo in the toast and in Logs > Activity |
| `usage [--by month] [--printer <name>]` | Filament used this month in sentences, or by month (9.24) | Analytics |
| `devices` (same as `devices list`) | Paired devices with kind, version and the out-of-date sentence (9.4) | Devices |
| `devices show <device>` | One device's detail; for a Weigh Station its status and settings | Devices, Open |
| `devices set <device> <setting> <value>` | Change a Weigh Station setting through the Hub (previews, asks) | Devices, the Weigh Station's detail |
| `devices forget <device>` | Unpair a device | Revoke |
| `pair [--slicer-sync \| --weigh-station \| --home-assistant] [--text] [--no-wait]` | Pairing code, QR and fingerprint | Pair a phone / Link for the Slicer Sync / Link for the Weigh Station / Link Home Assistant |
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
| `locations` (same as `locations list`) | The storage locations in fill order (9.15) | Settings > Storage locations |
| `locations add <name> [--type bulk\|containers] [--limit N] [--count N] [--takes any\|none\|MATERIALS] [--overflow]` | Add a location | Add a location |
| `locations edit <name> [--name NEW] [same options as add] [--no-overflow]` | Change a location; a new name also renames it on its spools; `--no-overflow` switches overflow off | Edit |
| `locations move <name> (--first \| --last \| --before <other>)` | Change the fill order | Move up, Move down |
| `locations remove <name>` | Remove a location (asks) | Remove |
| `locations default-overflow <name>` | Make it the default overflow (a Bulk storage location that is not overflow becomes overflow as well) | Make default overflow |
| `locations sealed <name>` | Sealed spools go here | Sealed spools go here |
| `export <usage\|locations\|recent\|activity\|printers\|lines\|spoolman-spools\|spoolman-filaments> [--out <file>] [--days N] [--printer <name>]` | Write one set as a CSV file (9.25) | Download as CSV |
| `import <spools\|locations> <file> [-y]` | Add spools, or add and change storage locations, from a CSV file (checks first, asks) (9.25) | Import from CSV |
| `alerts` (same as `alerts list`) | The alert switches and thresholds (9.17) | Settings > Alerts |
| `alerts set <type> on\|off` | Switch one alert type | The type's switch |
| `alerts set running-low <grams>` | Running low under | Running low under |
| `alerts set storage-warning <percent>` | Storage warning at | Storage warning at |
| `alerts test` | Send a test alert | Send a test alert |
| `label-reader status` | Label Reader engines and their health (9.9) | Settings > Label Reader |
| `label-reader test <photo>... [--engine cloud\|local]` | Read label photos without adding anything | Test |
| `label-reader corrections` (same as `label-reader corrections list`) | The corrections waiting to be shared (9.9) | Settings > Label Reader, Corrections waiting |
| `label-reader corrections remove <correction>... \| --all` | Take corrections out of the list (`--all` asks) | Remove / Remove all |
| `label-reader corrections package [--out FILE]` | Write the exact file that `send` would send | Download the package |
| `label-reader corrections send` | Send the corrections waiting (asks) | Send now |
| `catalog status` | Filament Catalog version and last check | Settings > Filament Catalog |
| `catalog update [--scheduled]` | Update now | Update now |
| `catalog rollback` | Go back to the version before | Go back to the version before |
| `catalog add <file \| ->` | Add your own entry from an entry file | (none: the Hub page takes the form) |
| `catalog add --ask` | Add your own entry: asks Brand, Name, Material and the optional values | Add (Settings > Filament Catalog) |
| `catalog local` | Your own entries | See custom entries |
| `catalog local remove <id>` | Remove one of your own entries (asks) | Remove |
| `catalog adopt <folder>` | Take over a catalog folder from an older install | (none) |
| `catalog token [--remove]` | Set, replace or remove the catalog token; the one place to do it | (none: the Hub page has no token field) |
| `backup create [--out DIR]` | Back up now | Back up now |
| `backup list` | Backups on this Hub | Show the backups |
| `backup keep <days>` | Keep nightly backups for N days | Keep nightly backups for N days |
| `backup password [--remove \| --show]` | Set or change the backup password; remove it; show it (9.10) | Settings > Backups and restore, Set a backup password |
| `restore <zip or .enc> [--password-file <file>] \| --uploaded` | Restore (asks for the typed word; an encrypted backup also needs its password) | Restore |
| `web status` | Access from outside: rows as in `status` | Settings > Network and addresses |
| `web passphrase` | Set or replace the web passphrase | Web passphrase |
| `remote firewall` | Print the firewall rules (changes nothing) | Show the firewall rules |
| `remote get-certificate` | Get the public certificate now | Get the certificate |
| `setup-code [--new] [--revoke-trusted]` | Hub page address and setup code | Setup code, Trusted computers |
| `port [<number>]` | Show the Hub's port, or move the Hub to another (9.19) | Settings > Network and addresses, Hub port |
| `certificate` | Make the Hub's certificate if missing; print its fingerprint | (none) |
| `spoolman fields` | Make Spoolwarden's extra fields in Spoolman | Overview, Make the fields |
| `spoolman address [<url>]` | Show or change the Spoolman in use (checked before saving) | Settings > General, Spoolman address |
| `update [--check \| --rollback] [--scheduled]` | Updates | Updates |
| `uninstall [--purge]` | Remove Spoolwarden (asks) | Updates, footer line |
| `logs [<service>] [--lines 50\|100\|200]` | The end of a service's log | Logs |
| `report [--out <file>]` | Collect a Hub report and print where it is (9.26) | Logs > Collect a Hub report |
| `language` (same as `language list`) | The languages: built in, installed and available (9.27) | Settings > General, Language |
| `language add <code>` | Download and install a language (9.27) | Get more languages, Install |
| `language remove <code>` | Remove an installed language (9.27) | Get more languages, Remove |
| `language set <code>` | Choose the Hub's language (9.27) | Settings > General, Language |
| `language template <code> [--out <file>]` | Write a language pack with every English text and empty translations (9.27) | (none) |
| `language check <file>` | Check a language pack and say what is wrong in plain sentences (9.27) | (none) |
| `demo` (same as `demo status`) | Says whether the demo is on (9.28) | Settings > General, Demo |
| `demo on` / `demo off` | Start the demo, or leave it and delete what is in it (asks) (9.28) | Try the demo / Leave demo |
| `add` | Prints where spools are added (section 10) | (none) |
| `spool` | Prints the five spool commands and where tags are linked and spools are added (section 10) | (none) |
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

Unchanged: `status`, `config`, `backup`, `restore`, `web`, `setup-code`, `update`, `uninstall`,
`printer map`, `printer report`. Old setup words (`server`, `station`, `all-in-one`) and old
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
matched the same way. `<record>` is a Recently added record's id, as `recent` shows it; `<correction>` is the ID
of a correction waiting to be shared, as `label-reader corrections` shows it.

## 6. Output conventions

### 6.1 One status vocabulary

The words are the ones the Hub page, the web app and the app show; the shapes are foundations section 10. A state
is always shown as a glyph followed by a word, never by colour alone and never by a glyph alone.

| Meaning | Words | Glyph (Unicode) | Glyph (ASCII) | Colour (token, section 6.2) |
|---|---|---|---|---|
| Good | `OK`, `connected`, `on`, `set`, `done`, `high`, `confirmed` | `●` | `+` | green (`--ok`) |
| Off or absent | `off`, `not set`, `not set up`, `found, not added`, `skipped`, `not on label`, `not yet`, `unknown` | `○` | `o` | dim (`--muted`) |
| Offline | `offline` | `○` | `o` | red (`--bad`) |
| Needs a look | `needs a look`, `medium`, `wrong Access Code`, `certificate changed`, `stopped without finishing` | `▲` | `!` | yellow (`--warn`) |
| Error | `error`, `failed`, `low: check this` | `×` | `x` | red (`--bad`) |
| Working | `working`, and the progress lines of section 6.6 | `◐` | `~` | cyan (`--accent`) |
| Note | `note`, `next`, `entered by hand` | `◆` | `*` | blue (`--info`) |

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
| Getting started step | done · next · not yet |

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
- **Language.** The results that come from the string catalogue are in the language of `--lang <code>`, which every
  command accepts, else of the shell's `LANG` when the Hub has that language, else the Hub's language
  (`03-hub-page.md` 10.3). The texts the Hub writes (its refusals, the rows of `status`) come in the same language: the
  command asks for it with `Accept-Language`. Not translated: the option help (`-h`), the installer's lines (9.20),
  and the words `Error:`, `Fix:` and `Note:` as typed. An unknown or not installed code: `Error: there is no language
  <code> on this Hub.` and `Fix: spoolwarden language` (exit code 2). Dates and numbers keep the forms of this
  section.
- **Demo data.** While the Hub runs in demo (9.28), every command that prints a result prints the line `Demo data.`
  first, above the result, also with `--quiet`. With `--json` the line goes to standard error, so that standard
  output stays the one JSON document of section 6.8.
- One term per thing, the shared wording table of `08-platform-mapping.md` section 12: `Weight with spool` (never
  gross weight), `Try again` (never retry, in prompts and Fix lines), `Slicer presets` (never profile), drafts
  (never unfinished adds), and "Leave empty to choose automatically." as the hint of an optional prompt the Hub
  fills in by itself.

### 6.5 Results, errors and Fix lines

- **Results** go to standard output: one line, past tense, naming the thing. `Forgot Workshop X1.`,
  `Saved 2 changes: display name, storage locations.`, `Unchanged.`
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
| Move the Hub to another port | `◐ Moving the Hub to port 8710…` |
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
  below), so a script and the Hub page see one shape. Times are ISO 8601 with offset, but a day (an own catalog entry's `added`) is `YYYY-MM-DD`;
  weights in grams, sizes in bytes, temperatures in °C, all as numbers.
- Stored secrets never appear: an API key, Access Code, passphrase, catalog token, existing Tag Reader token or
  the current setup code is `{"set": true}` or `{"set": false}`.
- One exception: a code, link or token that the command was asked to make is in that command's own reply, since
  handing it over is what the command is for (`pair`, `tag-reader new-token`, `setup-code --new`; table below).
  It appears in that one reply only; every later `list`, `show` or `status` gives `{"set": ...}` or leaves it out.
- `pair --json` prints its document and ends: it does not wait for the device. `devices --json` shows whether
  the device has paired.
- A command that acts prints the Hub's reply shape: `{"ok": true, ...}`.
- On an error, standard output gets `{"ok": false, "error": "<text>", "fix": "<text or null>"}`, standard error
  gets the usual text, and the exit code is as in section 6.7.
- `--json` never asks, at a terminal or not: a command that would ask needs `--yes`, or it stops with exit
  code 2.
- Menus (`config`, `features menu`, `printer menu`) do not take `--json`; they say
  `Error: config is a menu. Fix: use spoolwarden config show --json`.
- Fields are only ever added. Removing or renaming one is announced in the release notes one minor release
  ahead.

| Command | JSON shape |
|---|---|
| `status`, `web status`, `label-reader status` | `{"rows": [{"group", "state", "text", "fix", "action"}], "summary": {...}}`, the rows of `GET /setup/api/overview` plus `group` (section 13); `status` adds `"storage": ` the answer of `GET api/storage-use`, `"running_low": <number of spools>` and `"getting_started": ` the answer of `GET start` (`{show, hidden, finished, restore_offer, done, total, steps: [{id, state, line, target}]}`, 9.1) |
| `printer list`, `printer show` | the printer objects of `GET /setup/api/state` (`printers.list`): `serial, name, model, ip, configured, state, pinned, family` and, for Klipper, `host, port, api_key, lane_data`; `printer show --watch` prints `{summary, status}` of `GET api/printers/<id>`, one object per line each time it redraws |
| `printer test` | `{reachable, state, text}`, the reply of `printers/<serial>/test` |
| `printer map` | the map view of `GET /api/printers/<serial>/map` at its end |
| `printer reports` | `{reports: [{name, size, at}], never}`, the reply of `printers/<serial>/reports` |
| `recent` | `GET /setup/api/intake/history`: `{keep, photo_bytes, ai, count, records: [...]}` |
| `recent show` | `GET /setup/api/intake/history/<id>` |
| `devices` | the answer of `GET /setup/api/devices`: `{devices: [{id, name, kind: "phone", "pc", "station", "web", "reader", "home-assistant" or "builtin", version?, newest?, out_of_date, advice?, paired?, last_seen?, reachable?, built_in, page}]}` |
| `devices show` | the answer of `GET /setup/api/device/<id>`: `{device, status?, settings?: [{id, label, kind: "switch", "choice", "number" or "text", value, choices?, min?, max?}], own_page?, photo}` |
| `devices set` (needs `--yes`) | `{settings: [...]}`, the new list |
| `tag-reader list` | `state.readers.list`: `[{id, name, created}]` |
| `presets status` | `GET /setup/api/presets` |
| `features list` | `state.modules` plus `{"setup": "<setup>"}` |
| `config show`, `config theme` | the `values` of `GET /setup/api/settings/general`, plus `theme` |
| `locations` | the answer of `GET api/storage`: `{locations: [{id, name, type: "bulk" or "containers", limit or null, count or null, used, free or null, prefix or null, containers: [{name, number, taken}] or null, fill: "none", "any" or "materials", materials: [], overflow, default_overflow, sealed, position}], order_by_material: [{material, locations: [names]}], everything_else: [names]}` |
| `spools` | the answer of `GET api/spools`: `{spools: [{id, location, remaining_g, net_g, tare_g, tag, state: "sealed", "opened" or "empty", filament_id, vendor, name, material, color_hex, lot, loaded: {printer_id, printer, slot}?, low, view}], spoolman_url?}` |
| `spool show` | `{spool, last_use: {at, printer, grams}?}` |
| `spool weigh`, `spool move`, `spool empty` (need `--yes`) | `{spool, before, dry}`, the spool view after and before the change; the same for `spool move <n> auto` |
| `printer clear` (needs `--yes`) | the answer of `POST api/printers/<id>/slots/<slot>/clear`: `{slot, spool?, moved_back?, waiting_ended, printer_cleared, dry_run}` |
| `printer load`, `printer unload` (need `--yes`) | the answers of the routes `.../slots/<slot>/load` and `.../unload`; `unload` adds `waiting_ended`, and a load for a printer that has not shown it yet says `pending: true`; `printer load <printer> auto <spool>` gives the answer of `POST api/printers/<id>/slots/auto/load`: the dry run `{auto: true, watching: [<labels>], replaces?: {spool_id, name}, dry_run: true}`, the real one `{auto: true, pending: true, confirmed: null, expires_in: 900, message}`, and the refusal `{"ok": false, "error": "<text>", ...}` for 409 `auto_not_possible` |
| `printer usage` | the answer of `GET api/printers/<id>/usage` |
| `catalog local` | `{entries: [{id, brand, name, material, added}]}` |
| `catalog add --ask` (needs `--yes`) | `{entry: {id, brand, name, material, added}}` |
| `catalog local remove` (needs `--yes`) | `{removed: true}` |
| `spools low` | the answer of `GET api/spools/low`: `{threshold_g, spools: [{id, filament, material, color, remaining_g, location, in_stock, last_one}]}` |
| `events` | the answer of `GET api/events`: `{events: [{id, at, kind, severity, subject: {type, id, name}, actor: {type, id, name}, data: {}, condition: {key, state} or null, alert, title, text, action: {place, id}}], next, oldest, gap, test, conditions: [...]}`; with `--follow`, one event object per line (9.16) |
| `alerts` | the answer of `GET api/alerts`: `{types: [{key, title, on}], last_spool_only, running_low_g, storage_warn_percent, storage_bad_percent}` |
| `catalog status` | `GET /setup/api/library` |
| `backup list` | `{backups: [{name, at, kind, size, encrypted}], keep_days, folder, password_set}` |
| `backup password`, `backup password --remove` | `{"ok": true, "set": true}` or `{"ok": true, "set": false}`; `--show` has no JSON form (a stored secret is `{"set": true}`) |
| `status --history` | the answer of `GET api/health`: `{from, to, since?, checks: [{key, group, text, now, spans: [{from, to, state}]}], changes: [{at, key, text, from, to}]}` |
| `activity` | the answer of `GET api/events` with `activity=1` (as `events`, each event also with `undo: {possible, until?, why_not?}`, `undone` and `undo_of?`) |
| `undo` (needs `--yes`) | `{"ok": true, "undone": true, "event": <the new event>, "note"?: <text>}`, or the refusal `{"ok": false, "error": <changed_since, too_old, already_undone or not_undoable>, "text": ...}` |
| `usage` | the answer of `GET api/analytics`: `{months: [{month, grams, prints, unfinished_prints, unfinished_grams, logged_only_grams, no_weight_prints, by_printer, by_material, top_material?}], insights: [{key, text}], notes: [text]}` |
| `export` (with `--out`) | `{"ok": true, "set", "file", "rows"}` |
| `import spools` (needs `--yes`) | `{rows: [{n, ok, problems: [{column, text}], line}], add, dry, spool_ids?}`; `import locations`: `{rows, add, change, dry}` |
| `report` | `{"ok": true, "file"}` |
| `language`, `language list` | the answer of `GET /setup/api/languages`: `{hub, languages: [{code, name, reviewed, installed, complete}], available: [{code, name, reviewed, complete}], problem?}` |
| `language add`, `language remove`, `language set` | `{"ok": true, "code"}` |
| `language template` | `{"ok": true, "file", "texts"}` |
| `language check` | `{"ok": true or false, "texts", "translated", "problems": [{"line"?, "text"}]}` |
| `demo`, `demo on`, `demo off` (`off` needs `--yes`) | `{"demo": true or false}`; `demo on` and `demo off` add `"ok": true` |
| `spool label` | `{"ok": true, "file", "size", "labels"}` |
| `update --check` | `GET /setup/api/updates` |
| `logs` | `{unit, text, truncated}` |
| `weigh-station pairing-state` | `{"state": "paired" \| "unpaired" \| "unchecked", "address": ...}` |
| `pair` (and the pairing part of `features apply`, as `pair`) | `{"ok": true, "code", "link", "fingerprint", "expires"}` |
| `tag-reader new-token` | `{"ok": true, "id", "name", "token"}` |
| `setup-code` | `{"address", "code": {"set": true}}` |
| `setup-code --new` (needs `--yes`) | `{"ok": true, "address", "code"}` |
| `port` | `{"port", "address"}` |
| `port <number>` (needs `--yes`) | `{"ok": true, "port", "address"}` |
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
| `locations remove` | `Remove Rack 2? 3 spools are recorded there. They keep that location until you move them; it is no longer offered for new spools.` (`No spools are recorded there.` when there are none) | `Removed Rack 2.` |
| `devices forget` | `Unpair Shop phone? It can no longer reach the Hub until it is paired again.` | `Unpaired Shop phone.` |
| `devices set` | the preview, for example `Volume would change from 70 to 40.`, then `Apply?` | `Saved: volume 40.` |
| `printer load` | the plan lines (`Load Polymaker PolyTerra PLA Charcoal Black into A4`, `Preset: …`, `Nozzle: 0.4 mm`, `Spool 211 now in A4 goes back to Shelf B.`), then `Load it?`; with `auto` the plan lines are `Load Polymaker PolyTerra PLA Charcoal Black into any slot of Workshop X1`, `Watching: A1, A2, A3, A4` and, when one is waiting, `Replaces eSUN ABS+ White, which was waiting.`, then `Wait for it?` | `Loaded into A4.`, `Sent to A4. The printer accepted it but hasn't shown the change yet.` or `Waiting for the spool to load in A4.`; with `auto`, `Waiting for Polymaker PolyTerra PLA Charcoal Black to be loaded into any slot of Workshop X1.` |
| `printer unload` | `Unload from A3? Unload eSUN ABS+ White from A3? It goes back to Shelf B. Only the inventory changes; the printer's slot setting stays as it is.` (on a Klipper printer the last sentence is `The slot's setting on the printer is cleared.`) | `Unloaded eSUN ABS+ White from A3. Moved back: spool 211 to Shelf B.` |
| `printer clear` | `Clear slot A3? The Hub forgets the spool recorded here. eSUN ABS+ White (211) goes back to Shelf B.` (the second sentence only when a spool is recorded; on a Bambu Lab printer it ends with `The printer still shows the old filament for this slot until a spool is loaded.`) | `Cleared slot A3. Spool 211 is back on Shelf B.` (without a spool `Cleared slot A3.`; also `No spool is waiting for A3 any more.` when a waiting assignment ended, and, on a Bambu Lab printer, `The printer still shows the old filament for this slot until a spool is loaded.`) |
| `spool weigh` | `Remaining changes from 620 g to 482 g.`, then `Apply?` | `Weight updated: 482 g left.` |
| `spool move` | `Spool 214 would move to Shelf B.`, then `Apply?` | `Moved to Shelf B.` |
| `spool empty` | `Mark spool 214 empty? Polymaker PolyTerra PLA Charcoal Black will be marked as used up.` | `Marked empty.` |
| `catalog local remove` | `Remove Polymaker PolyTerra PLA from your own entries? Slicer presets are rebuilt.` | `Removed Polymaker PolyTerra PLA.` |
| `tag-reader revoke` | `Revoke the token tr3? A Tag Reader using it is refused from now on. Set it up again with sudo spoolwarden tag-reader flash to give it a new token.` | `Revoked the token tr3.` |
| `catalog rollback` | `Go back to the previous Filament Catalog? The version before the last update comes back. Your own entries are kept.` | `Back to version 2026.11.1.` |
| `catalog token --remove` | `Remove the Catalog token? The Filament Catalog can then download only from public sources.` | `Removed the Catalog token.` |
| `presets accept-updates` | the list (9.5), then `Accept these 3 updates? The Slicer Sync writes them at its next run, after its backup.` | `3 updates accepted; the Slicer Sync writes them at its next run, after its backup.` |
| `update` | `Update to 0.5.3? Spoolwarden stops while it installs and starts again by itself. Settings and data stay. The version before is kept, so you can roll back.` | the update runs |
| `update --rollback` | `Roll back to 0.5.1? Spoolwarden stops while it installs and starts again by itself. Settings and data stay.` | the roll back runs |
| `remote get-certificate` | `Get the certificate now? Port 80 on your router must reach this Hub while it runs. Spoolwarden never changes your firewall or router.` | the job runs (9.12) |
| `setup-code --new` | `Make a new setup code? The old one stops working.` | the new code, then `The old setup code no longer works.` |
| `setup-code --revoke-trusted` | `Revoke every trusted computer? Each one needs the setup code again.` | `2 trusted computers revoked.` |
| `port <number>` | `Move the Hub to port 8710? Phones and the Slicer Sync PC find the Hub again on your network. A Weigh Station on another machine must be paired again.` | the change runs (9.19) |
| `config`, removing the Anthropic API key | `Remove the Anthropic API key? Label Reader: Cloud (Claude) stops reading labels until a new key is set.` | staged until Save (8.3) |
| `features off` with dependants | `Also turn off Slicer presets? It needs Hub service.` (one question per dependant) | the plan includes it |
| `features on` with needs | `Also turn on Hub service? Label Reader: Cloud (Claude) needs it.` | the plan includes it |
| `recent revise` | the proposal (9.3), then `Accept these changes?` | `Saved as revision 2: Name, Nozzle range.` |
| `label-reader corrections send` | `Send 12 corrections? The photos and values in the list go to the project maintainer for review, to improve the Label Reader. This cannot be taken back.` | `Sent 12 corrections. Thank you.` |
| `label-reader corrections remove --all` | `Remove all 12 corrections waiting? They are not sent. The records in Recently added are unchanged.` | `Removed 12 corrections. Nothing was sent.` |
| `config`, switching Share corrections off while corrections wait | `Delete the 12 corrections still waiting?` (no keeps them to send later) | staged until Save (8.3); then `12 corrections deleted.` or `12 corrections kept.` |
| `features off label-reader-local` while corrections wait | `Also delete 12 corrections waiting to be shared? The reader keeps them, so they go with it.` (no stops the command: `Nothing changed.`) | the plan includes it |
| `weigh-station flash-display` | `Write the Weigh Station display firmware to /dev/ttyACM0?` (one per board found) | the write runs |
| `tag-reader flash` | `Write the Tag Reader firmware to /dev/ttyACM0? What is on the board now is replaced.` | the write runs |
| `undo` | the change in one line, for example `2026-11-12 14:11 · Moved spool 214 to Shelf B.`, then `Undo it?` | `Put back.` (after a load or an unload also `The printer still shows what it was set to.`) |
| `backup password --remove` | `Remove the backup password? New backups are plain again. Backups already made stay encrypted and need the password they were made with.` | `Removed the backup password.` |
| `import spools` | the table of what was read, then `Add 2 spools?` | `Added 2 spools: 215, 216.` |
| `import locations` | the table of what was read, then `Add 1 location and change 1?` | `Added 1 location and changed 1.` |
| `restore` | the backup's summary (9.10), then `Type restore to go on: ` | the restore runs |
| `uninstall` | `Remove Spoolwarden from this machine? Its data stays unless you add --purge.` | the removal runs |
| `uninstall --purge` | `This also deletes everything Spoolwarden keeps on this machine. Type purge to go on: ` | the removal runs |
| leaving `config` with changes | `Leave without saving 1 change (Storage locations)?` | `Nothing saved.` (exit 5) |
| leaving the Features checklist with changes | `Leave without applying 2 changes (Label Reader: On this Hub on, Weigh Station off)?` | `Nothing applied.` (exit 5) |

Commands that change something but do not ask, because nothing is lost: `printer rename`, `printer address`,
`printer access-code`, `printer lane-data`, `printer use`, `recent edit`, `locations add`, `locations edit`, `locations move`, `locations default-overflow`, `locations sealed`, `recent undo` (the revision is kept,
marked undone, and can be revised again), `backup create`, `presets build`, `catalog update`, `config set`,
`config theme`, `backup password` (setting or changing it: it is typed twice), `export`, `report`.

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
  `Leave without saving 2 changes (Display name, Storage locations)? [y/N]`; yes prints `Nothing saved.`. `q` in the
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
   3  Storage locations      4 locations · 2 with a limit
   4  Alerts                 6 of 8 on
   5  Label Reader           Cloud (Claude) · 40 reads a day · key set
   6  Backups and restore    Nightly backups kept 14 days
   7  Network and addresses  Public address not set
   8  Web passphrase         not set
   9  Filament Catalog       Version 2026.11.2
  10  Weigh Station voice    Piper (natural)

  These open their own screens; changes there apply at once:
  11  Printers               3 set up · 1 found
  12  Features               Hub with Weigh Station

  s save   q leave   ? help
Number: 3

Settings > Storage locations

   1  Sealed       4 spools · Only when chosen · Sealed spools
   2  Rack 1       18 of 20 spools · PLA
   3  Storage box  9 of 12 containers used · Any material
   4  Overflow     7 spools · Only when chosen · Default overflow

  a add   m move   r remove   s save   q back   ? help
Number: 2

Rack 1
   1  Name                       Rack 1
   2  Type                       Bulk storage (fixed: 18 spools are here)
   3  Spool limit                20
   4  Filled automatically with  These materials
   5  Materials                  PLA
   6  Use as overflow            no
   7  Sealed spools go here      no

  s save   q back   ? help
Number: 3
Spool limit [20]: lots
Error: Enter a whole number, 1 or more.
Spool limit [20]:
  Unchanged.
Number: 3
Spool limit [20]: 25
  Changed, not saved yet.
Number: q
Number: q

Settings · Workshop hub · 1 change not saved
  (the main list again)
Number: q
Leave without saving 1 change (Storage locations)? [y/N] y
Nothing saved.
```

Saving instead:

```
Number: s
Saved 1 change: storage locations.
```

**The Storage locations screen** is the list of locations in fill order, numbered; the order of the list is the order
in which the places fill. Each row is the location's name, how full it is, what it takes and its marks, in the words
of the Hub page (`03-hub-page.md` section 10.4). Its keys:

- A number opens that location's fields as a small screen (above), each edited as the prompts below do: Name, Type
  (a choice, fixed while spools are in the location), Spool limit (Bulk storage; empty means none) or Number of
  containers, Filled automatically with (a choice), Materials (for "These materials"; separated by commas), Use as
  overflow, and, on the row that qualifies, Make default overflow (an overflow row) and Sealed spools go here (a Bulk
  storage row). While Use as overflow is yes, the choice "Any material" is not offered for Filled automatically with
  (an overflow place already takes any material when the other places are full). Setting Use as overflow to yes while
  "Any material" is chosen sets Filled automatically with to "Nothing, only when you choose it"; setting it back to no
  does not change it back.
- `a` adds a location: it asks the same fields one after the other, and the new row goes at the end.
- `m` moves one: `Move which location? Number:` and then `Put it at position [<now>]:`.
- `r` removes one: it asks the Hub page's question, `Remove Rack 2? 3 spools are recorded there. They keep that
  location until you move them; it is no longer offered for new spools. [y/N]` (`No spools are recorded there.`
  when there are none). The default overflow and the sealed-spools location are refused with the Hub page's
  sentences (9.15).
- Every change is staged like any other item of the menu and saved by `s`, which sends the whole list. A rename also
  renames the location on its spools when it is saved. A save that cannot write stops with `Error: Storage locations
  were not saved: {reason}.` and a `Fix:` line the Hub can name. The group works before the Hub runs and without
  restarting it: the menu writes `storage.xml` itself, as `locations` does (9.15). The commands of 9.15 do the same at once, one change each.

**Groups and their items.** Group names, item labels, their order and the choice words are the Hub page's
(`03-hub-page.md` section 10); the one difference is the engine name Cloud (Claude), which follows foundations
section 2. "Key" is the setting's key for `config set` (9.8).

| Group | Item | Key | Kind of answer |
|---|---|---|---|
| Appearance | Theme for new devices | `appearance.theme` (section 13) | choice: Console (dense and technical) · Workbench (calm cards) · Palette (colourful and roomy) · Panes (simple lists) |
| General | Display name | `server_name` | text |
| General | Spoolman address | (none: `spoolman address`, 9.12) | text, an http address; only when Spoolman runs on another machine. On Save the Hub first checks that Spoolman answers there, as `spoolman address` does, and saves it after the other changes |
| Storage locations | Locations | (none: `locations`, 9.15) | a numbered list of locations: a number edits, `a` adds, `m` moves, `r` removes |
| Alerts | Filament ran out · Print paused · Print failed or stopped · Printer error · Print finished · Storage almost full · Spool running low · Device stopped answering | (none: `alerts set`, 9.17) | on / off, eight rows; the group's row reads `<n> of 8 on` |
| Alerts | Only when it is the last spool of that filament | (none: `alerts`, 9.17) | on / off |
| Alerts | Running low under | (none: `alerts set running-low`, 9.17) | whole number of grams, 10 to 2000 |
| Alerts | Storage warning at | (none: `alerts set storage-warning`, 9.17) | whole number, % used |
| Label Reader | Engine order | `intake.reader` | choice: Automatic: On this Hub first, Cloud (Claude) when it is unsure or fails · On this Hub, then Cloud (Claude) · Cloud (Claude), then On this Hub · Cloud (Claude) only · On this Hub only |
| Label Reader | Anthropic API key | (secret) | secret; then `c` checks it, `x` removes it (asks) |
| Label Reader | Claude model | `model` | text; empty for the default model |
| Label Reader | Reads per day | `reads_per_day` | whole number from 1 |
| Label Reader | Address | `local_intake.url` | text |
| Label Reader | Tier | `local_intake.tier` | choice: Automatic · Processor (CPU) · Graphics card (GPU) |
| Label Reader | Records kept | `intake.history_keep` | whole number 0 to 500; the row adds `Now 5 records, 14.2 MB of photos` |
| Label Reader | Share corrections | `label_reader.share_corrections` | on / off; the row adds `12 waiting` when there are any. Opening it first prints the description of 9.9 |
| Backups and restore | Keep nightly backups for | `backups.keep_days` | whole number of days, 1 to 365 |
| Network and addresses | Public address | `web.public_url` | text, an https address |
| Network and addresses | Weigh Station address | `station.url` | text; empty answer keeps, `-` clears |
| Network and addresses | Names for this page | `setup.hosts` | text, separated by spaces |
| Network and addresses | Allow printer changes from the public address | `web.printer_changes` | on / off |
| Web passphrase | New passphrase | (secret) | secret, asked twice (`New passphrase again`) |
| Weigh Station voice | Voice | `station.tts` | choice: Piper (natural; a 60-80 MB download) · espeak-ng (robotic; no download) |

The Alerts group is kept in the Hub's alert rules, not in the settings, so `config set` does not change it either
(use `alerts set`, 9.17); the part "On this device" of the Hub page's group (notifications in a browser) has no
counterpart here, since the command line gets no notifications. Storage locations is a list, not a set of keys, so
`config set` does not change it. `config set` with `locations`,
`placement.pla_location`, `placement.box_prefix`, `placement.box_count`, `placement.overflow` or
`placement.sealed_location` is refused, with exit code 2:

```
$ sudo spoolwarden config set placement.overflow "Shelf B"
Error: storage locations are a list now.
Fix: spoolwarden locations
```

The Engine order choices map to the stored values `auto`, `local-then-cloud`, `cloud-then-local`, `cloud`,
`local`; the Tier choices to `auto`, `cpu`, `gpu`; Piper and espeak-ng to `auto` and `espeak`. The Label Reader
screen shows the Hub page's sub-headings above its items, numbering straight through: `Cloud (Claude)` above
Anthropic API key, `On this Hub` above Address, `Recently added` above Records kept, `Share corrections` above
Share corrections. Engine order is a choice
only while both Label Reader features are on; with one on, its row reads
`Engine: Cloud (Claude). Switch on the other one in Features (12) to use both.` (or `Engine: On this Hub. …`)
and cannot be opened. The Cloud (Claude) items show only while Label Reader: Cloud (Claude) is on, the On this
Hub items only while Label Reader: On this Hub is on; Records kept always shows. Share corrections always shows;
while it cannot be changed its row gives the reason and cannot be opened:
`needs Label Reader: On this Hub. Switch it on in Features (12).`,
`the reader on this Hub is too old to share corrections. Update it: sudo spoolwarden update`, or
`the reader does not answer, so this cannot be changed now`.
Each group's screen ends with the actions that are commands elsewhere, so they are one step away: Backups and
restore ends with `Back up now: sudo spoolwarden backup create` and `Restore: sudo spoolwarden restore <zip>`;
Filament Catalog (which has no item to change: it shows the version and the last check) with
`Update now: sudo spoolwarden catalog update`, `Add your own entry: sudo spoolwarden catalog add --ask`, `Your own
entries: spoolwarden catalog local` and `Catalog token: sudo spoolwarden catalog token`; Network and addresses with
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
  Features (12)`. Opening it prints `Weigh Station is off on this Hub. Switch it on in Features (12) first.` and
  stays on the main list. This applies to Weigh Station voice (feature Weigh Station) and to Filament Catalog (feature
  Filament Catalog). One group keeps one item open while its feature is off, as on the Hub page:
  - **Label Reader** counts as on while either Label Reader: Cloud (Claude) or Label Reader: On this Hub is on.
    With both off, its row reads `off: only Records kept`; opening it prints
    `The Label Reader is switched off. Spools are then added by hand. Switch it on in Features (12).` and shows
    only Records kept.

**Saving.**

- `s` from any level saves every staged change at once and prints `Saved 2 changes: display name, storage locations.`
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
| `printer add` (Bambu) | the found list when anything was found (9.2) · `IP address or name (e.g. 192.0.2.40 or printer.local): ` · `Access Code (on the printer: Settings > Network/LAN > Access Code): ` (secret) · `Name (optional): ` · `Serial (optional: read from the printer): ` · after the test and the add, `Map its slots now? [Y/n] ` | Same order as the Hub page's drawer (`03-hub-page.md` 5.6). An empty Access Code: `No Access Code entered; nothing added.` |
| `printer add --klipper` | the found list when anything was found (9.2) · `Address: ` · `Port [7125]: ` · `Name (optional): ` · `Moonraker API key (optional): ` (secret) · after the test and the add, `Map its slots now? [Y/n] ` | When the test fails: `Add anyway? [y/N] ` (the Hub page's **Add anyway**; `--yes` does not answer it) |
| `printer address` (Bambu) | `Access Code of Workshop X1 (on the printer: Settings > Network/LAN): ` (secret), after the address is given as the argument | Same as the Hub page's Change address dialog. `--access-code -` reads it from standard input. Empty: `No Access Code entered; nothing changed.` (exit 5). A Klipper printer has no such prompt. |
| `printer access-code` | `New Access Code for Workshop X1 (on the printer: Settings > Network/LAN): ` (secret) | Empty: `Unchanged.` |
| `printer forget-certificate` | after the confirmation (section 7): `Access Code of Workshop X1 (on the printer: Settings > Network/LAN): ` (secret) | Same as the web app and the app. `--access-code -` reads it from standard input; `--yes` answers the confirmation, not this prompt. Empty: `No Access Code entered; nothing changed.` (exit 5) |
| `printer api-key` | `Moonraker API key for Garage Voron: ` (secret) | Empty: `Unchanged.` An empty answer no longer clears the key (it does today); clearing is `printer api-key <printer> --clear`, which asks (section 7). |
| `weigh-station pair` | `Paste the link from the Hub (sudo spoolwarden pair --weigh-station): ` then the fingerprint in four-character groups and `Does it match the fingerprint the Hub shows? [y/N]` | Run on the Weigh Station. Not answered by `--yes`. No: `Not paired. Nothing changed.` |
| `weigh-station flash-display` | one confirmation per blank board found (section 7) | Stops and restarts the Weigh Station service around the write, saying so |
| `tag-reader flash` | `Wi-Fi network the Tag Reader joins: ` · `Its Wi-Fi password: ` (secret) · `The password again: ` (secret) · `Buzzer: h for high, l for low [h]: ` | `--ssid` and `--buzzer high\|low` skip their prompts; `--password -` reads the password from standard input. The other options of today's `reader setup` keep their names and meaning (9.7). |
| `web passphrase` | `New passphrase, at least 12 characters: ` · `New passphrase again: ` (both secret) | Mismatch: `Error: the two passphrases do not match.` |
| `backup password` | `New backup password, at least 10 characters: ` · `New backup password again: ` (both secret) | Mismatch: `Error: the two passwords do not match.` Too short: `Error: use at least 10 characters.` After it is set, the Hub page's sentence is printed: `Write this password down. Without it these backups cannot be restored, and Spoolwarden cannot recover it.` |
| `restore` of an encrypted backup the stored password does not open | `Password of this backup: ` (secret) | `--password-file <file>` reads it from a file instead; a wrong one: `Error: wrong password, or the file is damaged. Nothing was changed.` |
| `catalog token` | `Catalog token (GitHub token): ` (secret) | The one place to set or remove the token: the Hub page and the `config` menu have no token field. A stored token keeps working and an update never deletes it |
| `catalog add --ask` | `Brand: ` · `Name: ` · `Material (number, or Other): ` (the numbered list of the materials the catalog knows, with Other last; Other asks `Type the material: `) · `More values (optional)? [y/N]` and, after yes, `Nozzle temperature from (°C): ` · `to (°C): ` · `Bed temperature from (°C): ` · `to (°C): ` · `Density (g/cm³): ` · `Maximum volumetric speed (mm³/s): ` · `Bambu Studio parent: ` · `Notes: ` | The Hub page's form, field for field and in its order; an empty answer to a required field asks again, to an optional one skips it. The command sends the values and the Hub builds the entry |
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

Getting started: 4 of 8 done
  ● done          Name this Hub
  ● done          Check storage locations
  ● done          Choose features
  ◆ next          Add a printer
                  sudo spoolwarden printer add
  ○ not yet       Map its slots
  ○ not yet       Use a phone
  ○ not yet       Add your first spool
  ● done          Make a first backup

Hub
  ● OK            Services running: 6 of 6
  ● OK            Answering at https://192.0.2.10
  ● OK            Certificate present, fingerprint 1111 2222 3333 4444 …
  ● OK            Storage: 41 GB free of 117 GB (65 % used)
  ◆ note          Running low: 3 spools
Spoolman
  ● OK            Reachable at http://192.0.2.10:7912 (v0.22.1)
  ● OK            Spoolwarden's extra fields are in place
Label Reader
  ● OK            Cloud (Claude): the API key works
  ◆ note          Reads used today: 12 of 40
Weigh Station
  ● OK            Answering at https://station.local
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

2 need a look · 10 OK · 2 connected · 1 offline · 4 notes
```

| Group | Rows (OK form / needs-a-look form) | Fix when it needs a look |
|---|---|---|
| Hub | `Services running: N of N` / `Service <name> is stopped` (one row per stopped service) | `sudo systemctl start <name>` |
| Hub | `Answering at <address>` / `Not answering at <address>` | `see what it logged: sudo spoolwarden logs` |
| Hub | `Certificate present, fingerprint …` / `Certificate missing` | `sudo spoolwarden certificate` |
| Hub | `Storage: <free> free of <total> (<percent> % used)` / the same words, needs a look past a limit (warn at 85 % used, bad at 95 % used, always bad under 1 GB free; the limits are in the Alerts group of `config`) | `Show storage use (Hub page, Overview)` |
| Hub | note `Running low: <n> spools` (`Running low: 1 spool`; no row when none is low) | `spoolwarden spools low` |
| Hub | note `Display name: <name>` (only when not set: needs a look, `Display name not set`) | `sudo spoolwarden config` |
| Hub | needs a look `<What it is> could not be converted (<reason>).` (one row for each of the Hub's own JSON files that the first start with this version could not move to XML; `The list of paired devices could not be converted (the file is damaged).`) | the Fix the Hub can name |
| Spoolman | `Reachable at <url> (v<version>)` / `Not reachable at <url>` | for Spoolman on this machine `sudo systemctl start <its service>`, else `check that Spoolman is running at <url>` |
| Spoolman | `Spoolwarden's extra fields are in place` / `Spoolwarden's extra fields are missing` | `sudo spoolwarden spoolman fields` |
| Label Reader | `Cloud (Claude): the API key works` / `Cloud (Claude): no API key` / `Cloud (Claude): the API key was refused` | `sudo spoolwarden config` (Label Reader) |
| Label Reader | note `Reads used today: N of M` (needs a look when N = M: `No reads left today (M of M)`) | `raise Reads per day in sudo spoolwarden config, or wait until tomorrow` |
| Label Reader | `On this Hub: answering at <url> (tier: <tier>)` / `On this Hub: not answering at <url>` (only when installed) | `sudo spoolwarden label-reader status` |
| Label Reader | needs a look `The Label Reader is switched on but not installed.` (only while Label Reader: On this Hub is on and the reader is not installed; no row otherwise) | the command that installs the reader, the one `Next:` names after switching it on (9.6) |
| Label Reader | note `The Label Reader at <address> is not using HTTPS. A later Label Reader version adds it.` (a reader on another machine at an `http://` address, until the reader's own software can serve HTTPS) | (none) |
| Label Reader | needs a look `The Label Reader at <address> is not using HTTPS.` (from the release that turns the rule on, a stored `http://` address of a reader on another machine) | `Update the Label Reader on that machine, then change its address to https:// in Settings > Label Reader.` |
| Label Reader | note `Share corrections: on, 12 waiting` (only while it is on, or while corrections still wait: `Share corrections: off, 12 still waiting`) | `spoolwarden label-reader corrections` |
| Weigh Station | `Answering at <url>`, `Tag reader seen`, `Scale seen`, `Paired with <address>` / `… not seen`, `Not paired` | per row: check the cable; `sudo spoolwarden pair --weigh-station` |
| Devices | note `Paired devices: N` | (none) |
| Devices | needs a look `The Weigh Station <name> is not using HTTPS. Update it.` (a Weigh Station that sent the Hub no fingerprint, because it has not been updated or because it could not make its certificate and logged why; the Hub still calls it over plain HTTP, and only if it has no pinned certificate) | `sudo spoolwarden update`, run on the Weigh Station's machine; if it is already updated, `sudo spoolwarden logs` there says why |
| Devices | needs a look `The Weigh Station <name> does not show the certificate the Hub saved for it.` (a station whose certificate the Hub has pinned and which now sends none or another one; the Hub never calls it over plain HTTP) | `Unpair it in Devices, then link it again.` |
| Devices | needs a look `<n> devices are out of date.` (`1 device is out of date.`) | `spoolwarden devices` |
| Devices | needs a look `The tag source <address> is not using HTTPS.` (a printer-side tag service that answers only on plain HTTP) | (none) |
| Devices | needs a look `The certificate of the tag source <address> has changed.` | `Save the tag source again to trust the new certificate.` |
| Printers | one row per printer with its state word (section 6.1); one needs-a-look row per printer problem | `sudo spoolwarden printer report "<name>"`, or the fix for that state |
| Slicer presets | `Last build <time>. Presets: N. Problems: none` / `… Problems: M` with each problem as a detail line; note `Slicer Sync last reported <time>` or needs a look `Slicer Sync: not set up`; note for the waiting text | `sudo spoolwarden presets status`; `sudo spoolwarden pair --slicer-sync` |
| Filament Catalog | `Version <v> (<source>), N local additions` / `Not downloaded yet` / `Last check failed: <why>` | `sudo spoolwarden catalog update` |

- **Getting started.** While steps remain and the list is not hidden on the Hub page, `status` prints the block
  "Getting started: <n> of <m> done" before the checks, in the Hub page's order (`03-hub-page.md` 4.2): one line per
  step with its state word, `done`, `next` or `not yet`, and under the `next` line the command that does it
  (`sudo spoolwarden config` for the name and the Anthropic API key, `sudo spoolwarden locations`,
  `sudo spoolwarden features`, `sudo spoolwarden printer add`, `sudo spoolwarden printer map "<printer>"`,
  `sudo spoolwarden pair`, `sudo spoolwarden web passphrase`, `sudo spoolwarden pair --slicer-sync`,
  `spoolwarden add` for the first spool, `sudo spoolwarden backup create`; the command for installing the Label Reader is the
  one of 9.6). While no step is done, one quiet line above the steps, "Moving from another computer? Restore its
  backup", names `sudo spoolwarden restore <zip>`; it is not a step, has no state word and is not counted in
  "<n> of <m>". On a Hub with no spool and no printer a second quiet line, "Just looking? Try the demo", names `sudo
  spoolwarden demo on`, and is not a step either. The block is not printed when the list is hidden or
  finished, and not with `--quiet`. Hiding, showing and the Keep buttons are on the Hub page only.
- A group whose feature is switched off prints one row: `○ off  Switched off in Features.` (no Fix; it is not a
  problem).
- The summary line counts rows by word; it is omitted with `--quiet`.
- While checks run, `◐ Checking… 4 of 15` shows on standard error (section 6.6).
- `--quiet` prints only the rows that need a look (with their group heading and Fix). Exit code 1 when any row
  needs a look (section 6.7). `--json`: section 6.8.
- `web status` and `label-reader status` print the rows of their own group in the same form.
- `status --history [--days 7|30]` prints the changes of the checks instead of the rows, the table of the Hub page's
  Show history (`03-hub-page.md` 4.2), newest first; `--days` takes 7 (the default) or 30. The exit code is 0.

  ```
  $ spoolwarden status --history
  TIME              CHECK                 FROM          TO
  2026-11-12 06:45  Workshop X1 offline   needs a look  OK
  2026-11-11 23:10  Workshop X1 offline   OK            needs a look
  2 changes in the last 7 days. No history before 2026-11-08.
  ```

  `FROM` and `TO` are `OK`, `needs a look` and, for a check at its worst, `needs a look now`. With no change: `No
  changes in the last 7 days.` The last sentence appears only when the history starts inside the range; with no
  history at all: `No history before <date>.` alone. `--json`: the answer of `GET api/health` (6.8).
- `status --json` carries the numbers of the Storage row: `storage` is the answer of `GET api/storage-use`
  (`{filesystems: [{path_label, total, free, percent_used, state}], items: [{key, title, bytes}]}`), and
  `running_low` the number of spools running low, and `getting_started` the object of `GET start`
  (`{show, hidden, finished, restore_offer, done, total, steps: [{id, state: done, next or open, line, target}]}`; the
  step ids are `name`, `storage`, `features`, `reader`, `key`, `printer`, `slots`, `phone`, `passphrase`, `pc`, `spool`,
  `backup`; the Restore row is not a step, `restore_offer` is true while it shows).

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

A Klipper printer shows `API key  set` and `Lane data  auto` in place of Certificate, and its tool slots (`T0`, `T1`). A
slot a spool is waiting for (a Bambu Lab printer that has not shown the load yet) shows `waiting for the spool to load
in A2` in the LEFT column. While the printer has an Auto assignment, `printer show` prints under the fields, above the
table, `Note: Waiting for Polymaker PolyTerra PLA Charcoal Black to be loaded into any slot of Workshop X1.`, or, in the
state choose, `▲ Two slots were loaded. Which one got Polymaker PolyTerra PLA Charcoal Black? A2, A3` with the Fix
`spoolwarden printer load workshop A2 214` (a named load of the same spool into the slot that got it ends the
assignment). It ends by itself after 15 minutes. A printer with a problem shows it under the fields, with its Fix: `▲
needs a look  The last slot mapping stopped twice. A report would help.` A printer offline shows `No slot data while
offline.` in place of the slot table.

**`printer show <printer> --watch`** prints the same, preceded by the printer's state line (state, job, progress, layer,
time left) and its temperatures, and redraws every 2 seconds until Ctrl-C (exit code 130). Not at a terminal it stops
with exit code 2: `Error: --watch needs a terminal.` and `Fix: use spoolwarden printer show --json for one reading.`
With `--json` it prints one `{summary, status}` object per line each time, with `auto_possible` on the printer,
`watchable` on each slot and `auto` while an Auto assignment exists, as `GET api/printers/<id>` gives them.

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
| `printer load` | The plan, then the question and the result of section 7 | `printer load workshop A4 214` loads spool 214. A load that waits for the printer ends with `Waiting for the spool to load in A4.` `printer load workshop auto 214` assigns spool 214 to the printer with no slot named: the Hub watches the slots it can and loads the spool into the one where a spool shows up (`auto` is not a slot name). It needs a printer with two or more slots the Hub can watch, else `Error: This printer has no slots the Hub can watch. Choose a slot.`; a new `auto` for the printer replaces the old one and the plan says so; it ends after 15 minutes, when the same spool is loaded into a named slot, or when the printer is removed. Needs the Hub running |
| `printer unload` | section 7 | Offered only when a spool is recorded in the slot: otherwise `Error: no spool is recorded in A3.` and `Fix: spoolwarden printer clear workshop A3` |
| `printer clear` | section 7 | Always possible. It means "the Hub forgets which spool is in this slot": a spool waiting for the slot is no longer waiting, the recorded spool goes back where it was before it was loaded, and on a Klipper printer the slot's setting is cleared when the printer is online and can do it; on a Bambu Lab printer what the printer shows is left as it is |
| `printer usage` | Table `WHEN`, `SLOT`, `JOB`, `GRAMS` and the note of an entry (`undone`, `logged only`), newest first; `Nothing used in the last 7 days.` | `--days N` (default 7) |
| `printer forget-certificate`, `printer forget`, `printer dismiss` | section 7 | |

**`printer add`** asks the questions of the Hub page's guided drawer (`03-hub-page.md` 5.6), in its order: the found
list, the details, the test, then the slots. Flags answer their questions and skip them.

```
$ sudo spoolwarden printer add --klipper
◐ Looking for printers on your network…
Found on your network:
  1  mainsailos  Klipper  192.0.2.57:7125
Use one of these? Number, or Enter to type an address: 1
Name (optional): Garage Voron
Moonraker API key (optional):
◐ Asking mainsailos…
Added Garage Voron as garage-voron (192.0.2.57:7125).
Mapping tells the Hub which slot is which. Nothing heats or moves.
Map its slots now? [Y/n]
```

- The found list holds the Klipper printers of the search (`printer scan`) and, when the Hub can list them, the Bambu
  Lab printers it heard announce themselves. Nothing found: `None found. Type its address.` When the Hub cannot list
  Bambu Lab printers: `Bambu Lab printers are added by address.`
- The test comes first and is said in words. A Bambu Lab printer whose certificate cannot be read fails with the Hub's
  text. A Klipper printer that does not answer: `Error: The Hub could not reach a Klipper printer at voron.example:7125.`
  then `Add anyway? [y/N]` (for a printer that is switched off); nothing is saved unless the answer is yes. Not at a
  terminal, nothing is saved and the command ends with exit code 1.
- `Map its slots now?` answers yes by default and then runs the flow of `printer map` (asks, section 7); no ends with
  `Map them later: sudo spoolwarden printer map "Garage Voron"`.

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
Photos open on the Hub page: https://192.0.2.10/setup#recent/35
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
NAME         KIND            VERSION   PAIRED            LAST SEEN         ID
Shop phone   Phone           0.5.2     2026-10-02 18:11  2026-11-12 14:05  d7
Studio PC    Slicer Sync PC  0.7.0     2026-10-03 09:40  2026-11-12 07:30  d8
Bench scale  Weigh Station   0.5.0     2026-10-04 10:02  2026-11-12 14:03  d9
Bench tags   Tag Reader      build 41  made 2026-11-01   2026-11-12 14:01  rd-3
Hub page     Built in        0.7.0     built in: this Hub's own pairing    d1
▲ Bench scale is out of date (0.5.0; the Hub is 0.7.0). On that machine: sudo spoolwarden update
```

- `KIND` is Phone, Slicer Sync PC, Weigh Station, Web app, Tag Reader or Built in. `VERSION` is `Version not known` for a
  device that sends none, which is never called out of date. Each out-of-date device adds one line under the table with
  the sentence of the Hub page (`03-hub-page.md` 7.9): Weigh Station `Out of date (0.5.0; the Hub is 0.7.0). On that
  machine: sudo spoolwarden update`, Slicer Sync PC `Out of date (<version>). Install the current Slicer Sync on that
  PC.`, phone `Out of date. The app offers the update when it is opened.`, Tag Reader `Out of date. Hold the knob for 4
  seconds to update.` `LAST SEEN` of a Weigh Station says that it is running (it calls the Hub every 5 minutes).
- Built-in pairings cannot be forgotten: `Error: Hub page is built in: it is this Hub's own pairing.`
- Empty: `Nothing paired yet.` then `Pair a phone: sudo spoolwarden pair`.

**`devices show <device>`** prints one device's detail. A Weigh Station also prints its status and settings, read through
the Hub the way the Hub page's **Open** reads them:

```
$ spoolwarden devices show "Bench scale"
Bench scale  Weigh Station  0.5.0  last seen 2026-11-12 14:03
  Status     tag 04A1B2C3D4 · scale 622 g · panel 1.2 · air ok · no intake running
  Settings
    beep          on
    speech        on
    voice         piper
    volume        70
    panel_swap    off
    lamp.weigh    green
    lamp.read     yellow
```

A Tag Reader prints its name, build and last seen, and `Its settings are changed in Flash a device (spoolwarden
tag-reader flash).` A phone, Slicer Sync PC, Web app or Home Assistant prints kind, version, paired and last seen.

**`devices set <device> <setting> <value>`** changes one setting of a Weigh Station through the Hub, as the detail on
the Hub page does. It shows what would change, asks (section 7) and takes `-y`; the setting's name is the one `devices
show` prints, and a value the setting does not take stops with exit code 2 and the values it takes in the Fix line.

```
$ sudo spoolwarden devices set "Bench scale" volume 40
Volume would change from 70 to 40. Apply? [y/N] y
Saved: volume 40.
```

**`pair`** prints, in the Hub page's order: the QR code (phone only), the instruction, the pairing code, the
certificate fingerprint, the expiry; then waits for the device to pair. With `--json` it does not wait
(section 6.8).

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
- `--home-assistant`: `In Home Assistant, add the Spoolwarden integration and type this pairing code when it asks. It can read the Hub and change nothing.` then the Hub's address alone on its line, the six-digit code, the fingerprint and the expiry (no QR code). The pairing is read-only (the viewer role) and shows in `devices` with the kind `home-assistant`.
- `--no-wait` prints everything and ends without waiting for the device; its last line is
  `The code works until 14:20.` It is listed in `pair -h` like any option (no hidden switches). The install and
  `features apply` show the pairing code this way, so they never hang on a phone.
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
| `features apply [--no-pair]` | `Setup: Hub with Weigh Station (Spoolman, Hub, …).`, `Weigh Station answers at: 192.0.2.10`, the apply, and the pairing code of 9.4 unless `--no-pair`; it does not wait for the phone (`pair --no-wait`) |
| `features units` | One service file name per line (for the installer) |

Switching `label-reader-local` on, when the reader is not installed, ends with `Next: ` and the command that installs
the reader, alone on its line after the words, and `status` shows the same command as the Fix of its row (9.1):

```
$ sudo spoolwarden features on label-reader-local
Features applied: Label Reader: On this Hub.
Next: <the command that installs the reader>
```

Switching `remote` on while the Hub holds port 443 is refused before anything is changed:

```
$ sudo spoolwarden features on remote
Error: Remote access needs port 443, and the Hub is using it.
Fix: move the Hub to another port first: sudo spoolwarden port 8710
```

Refusals use the Hub's text, for example switching the Hub off from the Hub page's own feature:
`Error: the Hub page belongs to the Hub service; switch it off on the Hub itself.` with
`Fix: sudo spoolwarden features off hub`.

### 9.7 `weigh-station` and `tag-reader`

| Command | Output |
|---|---|
| `weigh-station pair` | Prompts (8.7), then `Paired with the Hub at 192.0.2.10.` |
| `weigh-station pair --local` | For a Hub with Weigh Station: `The Weigh Station on this machine is paired with this Hub.` |
| `weigh-station flash-display` | `◐ Stopping the Weigh Station service…`, the list of blank boards found, one question each (section 7), `◐ Writing the firmware to /dev/ttyACM0… 45 %`, `● done  The display answered.`, `Started the Weigh Station service again.` No board: `No blank display board found on USB.` with `Fix: plug the display in with a data cable, then run this again.` |
| `weigh-station pairing-state` | `paired with 192.0.2.10` / `not paired` / `not checked yet` (the `--json` `state` keeps the values `paired`, `unpaired`, `unchecked` for scripts; see the root wrapper below) |
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
  1  Sealed       4 spools · Only when chosen · Sealed spools
  2  Rack 1       18 of 20 spools · PLA
  3  Storage box  9 of 12 containers used · Any material
  4  Overflow     7 spools · Only when chosen · Default overflow
Alerts
  6 of 8 on · running low under 150 g · storage warning at 85 % used
  ...
```

**`config set <key> <value>`** changes one setting with the keys of section 8.3, checked as the menu checks them.
`Saved: Reads per day is 60.` A setting that restarts the Hub shows the restart wait. A secret cannot be set
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
Fix: choose console, workbench, palette or panes. Light and dark are chosen on
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
  ● OK            On this Hub: answering at http://127.0.0.1:7915 (tier: cpu)
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

**Share corrections.** Off by default; switched with `sudo spoolwarden config` (Label Reader, Share corrections) or
`sudo spoolwarden config set label_reader.share_corrections on|off`. There is no address to show or set. The
description, printed when the item is opened in the menu and by `help label-reader corrections`:

```
When this is on, each correction you make to a reading waits on this Hub to be shared: the label photos
(made smaller, with location and camera data removed), what the Label Reader read, what you changed it to,
and your note if you wrote one. Readings by On this Hub and by Cloud (Claude) both count. Nothing is sent
until you run: sudo spoolwarden label-reader corrections send. Then the corrections waiting go to the
project maintainer for review, to improve the Label Reader.
```

Switching it prints `Share corrections is on. The reader restarted.` (or `… is off. …`). A correction is an edit
by hand or an accepted proposal in Recently added (`recent edit`, `recent revise`), or a read field changed while
adding spools in the web app or the app. `recent edit` and `recent revise` end with one more line while it is on:
`Note: this correction is waiting to be shared.`, or `Note: not shared: no photo was kept for this record.`, or
`Note: the correction is not waiting to be shared: <reason>.` The edit itself never fails because of sharing.

**`label-reader corrections`** lists what is waiting, oldest first. Listing and `package` need no sudo (they show
what `recent show --photos` already shows); `remove` and `send` do.

```
$ spoolwarden label-reader corrections
Corrections waiting: 2 · 0.6 MB. Nothing is sent until you run: sudo spoolwarden label-reader corrections send

  ID   CORRECTED         RECORD                                   READ BY         PHOTOS
  c7   2026-11-12 14:09  Polymaker PolyTerra PLA Charcoal Black   On this Hub     2
         Brand: Polymakr → Polymaker
         Colour: #2B2B2E → #1F1F22
         Note: brand is Polymaker
  c8   2026-11-12 09:50  Bambu Lab PETG HF Orange                 Cloud (Claude)  1
         Net weight: 1000 g → 750 g
```

- `<correction>` is a correction's ID, as this list shows it (section 5).
- Nothing waiting: `No corrections waiting.` (exit 0). Share corrections off with some left: the first line is
  `Share corrections is off, so no new corrections are added. 2 are still waiting.`
- A correction the reader did not take is listed last with `▲ not waiting: <reason>` in place of its changes; it
  is not counted, packaged or sent.
- `--json`: `{"sharing": true, "count": 2, "bytes": 629145, "entries": [{"id", "record", "item", "at", "engine",
  "changes": [{"field", "read", "now"}], "note", "photos", "queued", "reason"}]}`, the Hub's own reply.
- The reader does not answer: `Error: the reader does not answer, so the corrections waiting cannot be shown. They
  are kept.` with `Fix: sudo spoolwarden label-reader status`.

**`label-reader corrections remove <correction>...`** prints one line each,
`Removed c7. The record in Recently added is unchanged.`; `--all` asks (section 7).

**`label-reader corrections package [--out FILE]`** writes the exact file that `send` would send, by default
`spoolwarden-corrections-<YYYY-MM-DD>.zip` in the current folder, and prints
`Wrote spoolwarden-corrections-2026-11-12.zip (2 corrections, 0.6 MB). Nothing was sent.` Nothing waiting:
`Error: no corrections are waiting, so there is nothing to package.`

**`label-reader corrections send`** asks (section 7), shows `◐ Sending 2 corrections…`, then
`Sent 2 corrections. Thank you.` A failure: `Error: could not send. <reason> The corrections are still waiting.`
with `Fix: try again later; sudo spoolwarden label-reader status shows whether the reader answers`. Nothing
waiting: `No corrections waiting. Nothing was sent.` (exit 0). Nothing is ever sent by a timer, an update or any
other command.

### 9.10 `backup` and `restore`

```
$ sudo spoolwarden backup list
Nightly backups are kept 14 days.

MADE              KIND       SIZE       NAME                            ENCRYPTED
2026-11-12 03:00  nightly    4,812 KiB  backup-2026-11-12-0300.zip.enc  yes
2026-11-11 03:00  nightly    4,790 KiB  backup-2026-11-11-0300.zip      -
2026-11-10 16:32  made here  4,771 KiB  backup-2026-11-10-1632.zip      -

Folder: <backup folder on this Hub>
```

- `KIND` uses the Hub page's words: `nightly`, `made here`, `before a restore`.
- Empty: `No backups in <folder> yet.` then `Back up now: sudo spoolwarden backup create`.
- `backup create`: `◐ Backing up…` then `Backup written: <path>` and, while no backup password is set, the Hub page's warning on one
  line: `Note: the zip is not encrypted and holds the setup secrets: store it somewhere safe.` With a password set it
  writes `Backup written (encrypted): <path>` and no note.
- `backup password` sets the backup password, asking twice (8.7); from then on every backup is encrypted: the nightly one,
  `backup create` and the copy made before a restore. It prints `Write this password down. Without it these backups
  cannot be restored, and Spoolwarden cannot recover it.` and `Backup password set. Every backup is now encrypted.`
  Run again it changes the password: new backups use it and older files keep the one they were made with.
  `backup password --remove` asks (section 7), then new backups are plain again and encrypted files stay as they are.
  `backup password --show` prints the password on the terminal and is the only way to read it again: the Hub page never
  shows it. It is kept in `/etc/filament-kit/backup_password`, readable by root only, and left out of every backup. All
  three need sudo.
- `backup keep 14`: `Backups are kept for 14 days.`
- `restore <zip>` (or `--uploaded` for a zip uploaded on the Hub page) prints the Hub page's summary, then asks
  for the typed word (section 7). A backup that ends `.enc` is opened with the stored backup password first; when that does
  not open it, the command asks `Password of this backup: ` (hidden), or reads it from `--password-file <file>`. A wrong
  password stops with exit code 1: `Error: wrong password, or the file is damaged. Nothing was changed.` The checks before
  the restore (the manifest, every file's hash) run on the opened content. After a restore from an encrypted backup the
  password that opened it becomes this Hub's backup password if none is set (a line before the question says so):

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
| `catalog add <file \| ->` | `Added Polymaker PolyTerra PLA. A preset build follows.` / `Error: entry not added: larger than <limit> KiB.` (the limit the Hub checks). The file form stays for an entry file |
| `catalog add --ask` | asks the fields of 8.7, then `Added. Slicer presets are rebuilt in a minute.`; the Hub's refusals are printed per field, `Error: Material: <text>` |
| `catalog local` | Table `ID`, `BRAND`, `NAME`, `MATERIAL`, `ADDED`; empty: `You have no entries of your own yet.` |
| `catalog local remove <id>` | the question of section 7, then `Removed Polymaker PolyTerra PLA.` An unknown id: `Error: no entry of your own has the id 4.` |
| `catalog adopt <folder>` | `Took over the catalog in <folder>: N local additions.` |
| `catalog token` | prompt (8.7), then `Saved the catalog token.` It is the one place to set or remove the token |

### 9.12 `web`, `remote`, `setup-code`, `certificate`, `spoolman`

| Command | Output |
|---|---|
| `web status` | Rows in the 9.1 form under the heading `Web access`, in the order of the table below |
| `web passphrase` | prompts (8.7), then `Passphrase saved.` |
| `remote firewall` | `Spoolwarden never changes your firewall or router. These are the rules to add:` then the rules, each on its own line |
| `remote get-certificate` | section 7, then `Note: certbot listens on port 80 of this Hub now. Spoolwarden does not open it: your router must forward it here.`, `◐ Getting the certificate…`, then `● done  Certificate issued for hub.example.` or `× failed  The certificate was not issued: <why>.` with `Fix: check that hub.example points at this Hub and port 80 reaches it, then run this again.` (exit 1). Remote access off: `Error: Remote access is off.` with `Fix: sudo spoolwarden features on remote` (exit 1) |
| `setup-code` | At a terminal: `Open https://192.0.2.10/setup  (setup code: 1234-5678)`. Not at a terminal, only the address and `Note: the setup code is shown at a terminal only.` `--json` gives `"code": {"set": true}` (section 6.8). |
| `setup-code --new` | section 7, then the new code and `The old setup code no longer works.` The new code is printed without a terminal too, and in `--json`: the command was asked to make it (section 6.8). |
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

### 9.15 `locations` (Storage locations)

`spoolwarden locations` prints the list of storage locations in fill order, as Settings > Storage locations does.
Reading needs no sudo; every change needs sudo, as `config set` does. A `<name>` is the location's name as written
(capitals ignored; in quotes when it holds spaces).

```
$ spoolwarden locations
4 locations · 2 with a limit
POS  NAME         TYPE          HOW FULL  TAKES             MARKS
  1  Sealed       Bulk storage  4 spools  Only when chosen  Sealed spools
  2  Rack 1       Bulk storage  18 of 20  PLA
  3  Storage box  Containers    9 of 12   Any material
  4  Overflow     Bulk storage  7 spools  Only when chosen  Default overflow

The places fill in this order. Change them: sudo spoolwarden locations -h
```

- `POS` is the position in the list; `TYPE` reads `Bulk storage` or `Containers` (Individual containers, whose
  `HOW FULL` counts the containers in use); `TAKES` reads `PLA` (or `PLA, PETG`), `Any material` or
  `Only when chosen`; `MARKS` lists `Overflow`, `Default overflow` and `Sealed spools`. A location over its limit
  shows `22 of 20`. The long column is `NAME`.
- `--json` prints the answer of `GET api/storage` (6.8): the `locations` with `id, name, type, limit, count, used,
  free, prefix, containers, fill, materials, overflow, default_overflow, sealed, position`, then `order_by_material`
  and `everything_else`. On a `containers` location, `containers` is `[{name, number, taken}]`, the whole set in number
  order, and `prefix` is the text before the number; both are `null` for bulk, and `used` and `free` equal the counts
  of `taken`.
- When two or more locations are overflow and the default overflow has no limit, a `Note:` line follows the table
  (and follows any change that causes it, such as `locations add` or `locations edit`; not with `--json`):

```
$ spoolwarden locations
5 locations · 2 with a limit
POS  NAME         TYPE          HOW FULL  TAKES             MARKS
  1  Sealed       Bulk storage  4 spools  Only when chosen  Sealed spools
  2  Rack 1       Bulk storage  18 of 20  PLA
  3  Storage box  Containers    9 of 12   Any material
  4  Overflow     Bulk storage  7 spools  Only when chosen  Overflow, Default overflow
  5  Overflow 2   Bulk storage  0 spools  Only when chosen  Overflow

Note: The default overflow has no limit, so the other overflow places are never used. Give it a spool limit to let
      them fill.
The places fill in this order. Change them: sudo spoolwarden locations -h
```

| Command | What it does |
|---|---|
| `locations add <name> [--type bulk\|containers] [--limit N] [--count N] [--takes any\|none\|MATERIALS] [--overflow]` | Adds a location at the end of the list. `--type` is `bulk` (a shelf, rack or drawer) or `containers` (boxes or bags, one spool each); `--limit` (1 to 9999) is for bulk, `--count` (1 to 999) for containers; `--takes` is `any`, `none` or a comma list of materials (`PLA,PETG`); `--overflow` makes it an overflow location, which cannot take `--takes any` (a refusal below). Without options: bulk, no limit, takes nothing. |
| `locations edit <name> [--name NEW] [same options as add] [--no-overflow]` | Changes what is given. `--no-overflow` switches overflow off (refused for the last overflow location, with the text of the Remove refusal below). A new name is a rename: the spools stored there get the new name, as on the Hub page (`Renamed Rack 1 to PLA rack 1. 18 spools updated.`); for Individual containers the prefix becomes the new name plus one space, so the containers are renamed with it |
| `locations move <name> (--first \| --last \| --before <other>)` | Puts the location first, last, or just before another |
| `locations remove <name>` | Asks the question of section 7, then removes it; the spools keep their location text |
| `locations default-overflow <name>` | Makes an overflow location the default overflow. On a Bulk storage location that is not overflow it makes it overflow as well; on any other location it stops with `Error:` and the Fix "choose a Bulk storage location" |
| `locations sealed <name>` | Makes a Bulk storage location the place for sealed spools |

```
$ sudo spoolwarden locations add "Rack 2" --limit 20 --takes PLA
Added Rack 2.

$ sudo spoolwarden locations move "Rack 2" --before Overflow
Moved Rack 2 before Overflow.

$ sudo spoolwarden locations remove Overflow
Error: Make another location the default overflow first.
Fix: sudo spoolwarden locations default-overflow <name>
```

- Refusals, each with exit code 1: removing the default overflow (`Error: Make another location the default overflow
  first.`) or the sealed-spools location (`Error: Choose another location for sealed spools first.`); a name that
  exists (`Error: There is already a location called Rack 1.`); a number that is not whole or below 1
  (`Error: Enter a whole number, 1 or more.`); materials left empty for `--takes` (`Error: Enter at least one
  material, e.g. PLA.`); a type changed while spools are in the location (`Error: Move the spools out to change the
  type.`); fewer containers than the highest number in use (`Error: Storage box 11 and Storage box 12 hold spools.
  Move them first, or keep at least 12.`); `--takes any` with `--overflow`, or on an overflow location
  (`Error: an overflow location cannot take any material automatically.` with `Fix: use --takes none or name the
  materials`); `--no-overflow` on the last overflow location (the Remove refusal's text); a name that is the name of
  a container in a set (`Error: Rack 01 is the name of a container in Rack. Choose another name.`), also when
  `locations add` or `locations edit` makes a set whose containers would be named like an existing location (the
  same sentence with that location's name). Only a new clash is refused. A name that matches no location stops with
  exit code 2.
- A clash that already exists (a Bulk storage location named like a container in a set, as the migration can leave
  it) is not refused and may stay: either location can be edited in its other fields, and removing or renaming one of
  the two ends it. `locations` then adds a `Note:` line under the table, with the same words as the Hub page's row
  (not with `--json`):

```
Note: Rack 01: Same name as a container in Rack.
```
- Every change is written to `storage.xml` in the Hub's state folder by the command itself, with the same storage code
  as the Hub, under the Hub's lock, with the Hub's owner and mode. It works before the Hub runs (the installer uses
  it) and the running Hub reads the changed file without a restart. A change that cannot be written stops with
  `Error: Storage locations were not saved: {reason}.` and a `Fix:` line the Hub can name; nothing is half written.
- Changing a location moves no spool. `locations` shows the result at once; `spoolwarden config` shows the same list
  as a numbered menu (8.3).

### 9.16 `events`

`spoolwarden events` prints the events of the Hub's event store, oldest first, as the Alerts list of the Hub page reads
them (`02-components.md` 8.9, with every kind, not only the alert types that are on). Reading needs no sudo. Options:
`--since <id or time>` (an event number, "everything after 1412", read with `since`, or a time such as `2026-11-17 04:00`, read with `since_at`), `--kind <prefix>` (the dotted names of the catalogue, so `--kind print` shows `print.started`, `print.runout`
and the rest), `--follow` and `--json`. Without `--since` it prints the newest 50.

```
$ spoolwarden events --since 1408
ID    TIME              KIND          SUBJECT        WHAT
1409  2026-11-17 03:58  spool.low     Spool 214      Running low: Prusament PLA Galaxy Black
1412  2026-11-17 04:12  print.runout  Workshop X1    Filament ran out on Workshop X1
1413  2026-11-17 04:40  storage.low   Hub            Storage on the Hub is almost full

3 events. Raised now: spool-low:214 · print-paused:p-3 · storage-low
```

- `WHAT` is the title the Hub built for the event in its language (the table of `02-components.md` 8.8 for the alert
  kinds).
- The last line counts the events printed and names the conditions that are raised now. When `gap` is true (events
  after the given number were deleted by age) a note line says so: `Note: some events were deleted by age.`
- `--follow` prints the same rows as they come (it waits at the Hub, `GET api/events?since=<id>&wait=55`), starts with
  `Following events after 1413. Ctrl-C ends.` on standard error and ends with Ctrl-C (exit code 0). With `--json` each
  event is one object on its own line.
- `--json` prints the answer of `GET api/events` (6.8); `condition` is `null` for a moment.
- Events are the Hub's record of what happened. They are not the usage logs or the Recently added history, which stay
  as they are.

### 9.17 `alerts`

`spoolwarden alerts` shows which alert types are on and the thresholds, as Settings > Alerts does. Reading needs no
sudo; every change needs sudo, as `config set` does; no route lets a paired phone or the web app change them. `<type>` is one of the eight fixed type keys (the `key` of each entry of `GET api/alerts`,
shown in the first column):

| Key | Alert | Events |
|---|---|---|
| `runout` | Filament ran out | `print.runout` |
| `paused` | Print paused | `print.paused` |
| `failed` | Print failed or stopped | `print.failed` |
| `printer_error` | Printer error | `printer.error` |
| `finished` | Print finished | `print.finished` |
| `storage` | Storage almost full | `storage.low` |
| `running_low` | Spool running low | `spool.low` |
| `device_down` | Device stopped answering | `device.down`, `printer.offline` |

The description of `device_down` is "A Weigh Station or a printer stopped answering."

```
$ spoolwarden alerts
Alerts · 6 of 8 on
KEY            ALERT                          EVENTS                       STATE
runout         Filament ran out               print.runout                 on
paused         Print paused                   print.paused                 on
failed         Print failed or stopped        print.failed                 on
printer_error  Printer error                  printer.error                on
finished       Print finished                 print.finished               off
storage        Storage almost full            storage.low                  on
running_low    Spool running low              spool.low                    on
device_down    Device stopped answering       device.down, printer.offline off

Spool running low only when it is the last spool of that filament: off
Running low under 150 g · Storage warning at 85 % used (bad at 95 %, or under 1 GB free)
Change them: sudo spoolwarden alerts set -h
```

| Command | What it does |
|---|---|
| `alerts set <type> on\|off` | Switches one alert type; `<type>` is exactly one of the eight keys above. Every event is written whatever the switches say; a switch only decides what is shown and sent as an alert |
| `alerts set running-low <grams>` | Running low under: a whole number, 10 to 2000 |
| `alerts set storage-warning <percent>` | Storage warning at: a whole number, % used |
| `alerts test` | Asks the Hub to send one test alert (`POST api/alerts/test`) and prints the Hub's answer. The test goes to every client that asks within 60 seconds and to every push subscription |

```
$ sudo spoolwarden alerts set finished on
Print finished alerts are on.

$ sudo spoolwarden alerts set running-low 200
Running low under 200 g.

$ sudo spoolwarden alerts set running-low 5
Error: Enter a whole number, 10 to 2000.
```

- `--json` prints the answer of `GET api/alerts` (6.8). The switch "Only when it is the last spool of that filament" is
  changed in `config` (8.3), as is the whole group.
- A name that is no alert type stops with exit code 2 and lists the keys. Each device decides for itself whether it gets
  notifications; the command line gets none: `spoolwarden events --follow` prints the events as they come.

### 9.18 `spools low`

`spoolwarden spools low` prints the opened spools (not sealed, not empty) whose remaining weight is at or under the
running-low threshold, least filament first, as the Running low card of the Hub page does. Reading needs no sudo.

```
$ spoolwarden spools low
3 spools running low (at or under 150 g)
SPOOL  FILAMENT                         LEFT   LOCATION       STOCK
  214  Prusament PLA Galaxy Black       96 g   Rack 1         2 more in stock
   77  Polymaker PETG Teal             140 g   Rack 2         Last one
  209  Bambu Lab PLA Basic Black       112 g   Storage box 03 4 more in stock
Change the limit: sudo spoolwarden alerts set running-low <grams>
```

- `STOCK` is `<n> more in stock` (other spools of the same filament line that are not empty, sealed ones included) or
  `Last one`, marked with the warn glyph (6.2). When nothing is low: `No spools are running low (at or under 150 g).`
- `--json` prints the answer of `GET api/spools/low` (6.8).

### 9.19 `port`

`spoolwarden port` shows the port the Hub listens on; `sudo spoolwarden port <number>` moves the Hub to another. It is
also the way an existing Hub moves to port 443, and the way out of the refusal of Remote access on port 443 (9.6).
Reading needs no sudo.

```
$ spoolwarden port
Hub port: 443
Address: https://192.0.2.10/setup

$ sudo spoolwarden port 8710
Move the Hub to port 8710? Phones and the Slicer Sync PC find the Hub again on your network. A Weigh Station on another machine must be paired again. [y/N] y
◐ Moving the Hub to port 8710…
● done  The Hub is on port 8710: https://192.0.2.10:8710/setup
The ufw firewall is on, and Spoolwarden does not change it. For other devices to reach this computer, run:
  sudo ufw allow 8710/tcp
```

- A port is allowed when it is 443 or from 1024 to 65535, and free. Otherwise the command says why and changes
  nothing, exit code 2:

  ```
  $ sudo spoolwarden port 80
  Error: port 80 is not allowed: use 443, or a port from 1024 to 65535.

  $ sudo spoolwarden port 8101
  Error: port 8101 is already in use on this machine.
  Fix: choose another port: sudo spoolwarden port 8710
  ```

- It writes the configuration, the unit drop-in that lets the Hub bind a port below 1024 (and removes it for a port of
  1024 or more), the network advert, the Weigh Station's drop-in when one runs on this machine, restarts the Hub and
  the web unit, prints the firewall line naming the real port, and says what each paired device needs: the question
  above is the Hub page's dialog word for word (section 7).
- The Hub never moves by itself: an update leaves every port as it is.
- A machine that holds 443 for Remote access refuses `port 443`: `Error: port 443 is already in use on this machine.`
- `--json`: `{"port", "address"}` when reading; `{"ok": true, "port", "address"}` after a change, which needs `--yes`
  (section 6.8).

### 9.20 The installer

The installer (`install.sh`) is the first thing a person runs, so what it asks and prints on a first install is part of
the command line's design. It asks its questions on a terminal only; with no terminal it asks nothing and takes the
defaults. Addresses it prints have no port when the Hub is on port 443.

**The first question: Guided Setup.** On a first install at a terminal, when none of `--mode`, `--modules`, `--set`,
`--server` or `--restore` was given (the flags win), the first question is:

```
  y: the Hub is installed with the usual choices; its page takes you through the rest.
  n: answer the questions here. Also the way to install only a Weigh Station.
Finish setting up in your browser (Guided Setup)? [Y/n]
```

- **Yes** (Enter): the installer asks nothing else. The mode is the Hub, the features are the defaults, the display
  name is the host name, the storage locations are the defaults, no key is asked and the phone step is skipped: what it
  does without a terminal already. It ends with
  `Open https://spoolwarden.local/  (setup code: 1234-5678)` and `Guided Setup starts there.` and then the firewall
  line. The lines `Spoolman: ...` and `Pair another phone: ...` are not printed in this case: the page has both.
- **No**: today's questions in today's order, unchanged, and the closing lines as they are today with the address
  written without a port when the Hub is on 443.
- **No terminal**: no question; today's behaviour. The Hub page still offers Getting started (`03-hub-page.md` 4.2), so
  an unattended install ends in the same place.
- An update, `--restore`, any of the flags above and the install of only a Weigh Station never ask it.
- The installer records what it did (which of the name, storage and features questions were answered at the terminal)
  in the first-run file in the Hub's state folder, so the Hub page knows which steps are already answered.

**The Hub's port.** On a first install, before the port is written, the installer checks whether TCP 443 is free on
this machine, and whether the chosen features include Remote access, which owns 443 for the public address.

| Case | What the installer does |
|---|---|
| 443 is free and Remote access is not chosen | Port 443, no question |
| 443 is taken, at a terminal | `Port 443 is already in use on this machine.` (followed by ` Remote access uses it for the public address.` when that is the reason), then `Port for the Hub [8710]: `. Enter takes 8710. A typed port must be 1024 to 65535 and free; otherwise the reason is said and the question repeats. When 8710 is itself taken, the port offered is the next free one above it |
| 443 is taken, no terminal or Guided Setup chosen | The Hub takes 8710 (or the next free port above it) without a question and prints `Port 443 is in use on this machine, so the Hub uses port 8710.` |

The chosen port is written into the settings file (`config.xml`) at the first install. An install whose settings have no
port keeps 8710 whatever happens, and no update moves an existing Hub. When the port is below 1024 the installer writes
the unit drop-in that gives the Hub exactly the right to bind it; for a port of 1024 or more the drop-in is removed. The
pairing link carries the real port and so does the network advert; the firewall line names the real port. To change the
port later: `sudo spoolwarden port <number>` (9.19).

**A Weigh Station.** A new Weigh Station install takes port 443 when it is free, with the same question and the same
texts for the Weigh Station (the port offered instead is 5003: `Port for the Weigh Station [5003]: `). On a machine that
also runs the Hub, 443 is the Hub's, so the station takes 5003 without asking. The station makes its own certificate at
install and serves HTTPS only; its unit gets the same drop-in when its port is below 1024. A Weigh Station that is
already installed keeps its port (5003) on update and switches to HTTPS. The printer-side tag service installs the same
way: a new install takes 443 when it is free and allowed, otherwise 5002, asked like the others; an existing one keeps
5002.

**The language.** The installer reads the system's language (`LANG`). When the release has a language pack for it, the
installer downloads the pack, makes it the Hub's language and says so in one line, and asks nothing:

```
Language: Deutsch (machine-translated). Change it in Settings > General.
```

When the release has no pack for the system's language, nothing is installed and no line is printed: the Hub's language
is English. The installer's own lines and questions stay English (not in the catalogue, 6.4), this one included; only
the language's name is its own.

### 9.21 `spools` and `spool`

`spools` finds spools the way the Hub page's Spools section does (`03-hub-page.md` 16), from the Hub's inventory. Reading
needs no sudo.

```
$ spoolwarden spools petg
SPOOL  FILAMENT                   MATERIAL  LEFT    WHERE             STATE   TAG
  212  Bambu Lab PETG HF Orange   PETG      880 g   Workshop X1 · A2  opened  tagged
  213  Bambu Lab PETG HF Orange   PETG     1000 g   Shelf B           sealed  -
   77  Polymaker PETG Teal        PETG      140 g   Rack 2            opened  -   ▲ running low
Spoolman: http://192.0.2.10:7912
```

- `spools [<words>]`: every word must be found in the brand, name, material, location, spool number or tag (the Hub's
  word match). `--sealed`, `--opened`, `--loaded` (in a printer) and `--low` (running low) narrow the list; one at a
  time, and they work with the words. `spools low` stays the command of 9.18 and keeps its own output; any other words
  search. To search for the word itself, write `spoolwarden spools -- low`. `spools --low` is the filter. Spools that
  are empty are not listed.
- The last line is `Spoolman: <address>` (the Hub's `spoolman_url`; the command never builds it). It is left out when
  the Hub gives none.
- Nothing matches: `No spools match.` No spools at all: `No spools yet. Add your first one from your phone.`
- `--json`: the answer of `GET api/spools` (6.8).

`spool` has five commands. Each changing one shows what would change, asks (section 7), and takes `-y`; `label` changes
nothing.

```
$ spoolwarden spool show 214
Spool 214
  Filament     Polymaker PolyTerra PLA Charcoal Black (PLA, #2B2B2E)
  Left         620 g of 1000 g (62 %)
  State        opened
  Where        Workshop X1 · A1
  Tag          04A1B2C3D4
  Empty spool  140 g
  Lot          F57
  Last use     12.4 g on Workshop X1, 2026-11-12 14:05

$ sudo spoolwarden spool weigh 214 622
Remaining changes from 620 g to 482 g. Apply? [y/N] y
Weight updated: 482 g left.

$ sudo spoolwarden spool move 214 "Shelf B"
Spool 214 would move to Shelf B. Apply? [y/N] y
Moved to Shelf B.

$ sudo spoolwarden spool empty 214
Mark spool 214 empty? Polymaker PolyTerra PLA Charcoal Black will be marked as used up. [y/N] y
Marked empty.
```

| Command | Does | Notes |
|---|---|---|
| `spool show <n>` | One spool: its facts, where it is, its tag, the last filament taken off it | `--json`: `{spool, last_use?}` |
| `spool weigh <n> <grams with the spool>` | Records a scale reading with the spool | Grams above 0, or `Error: enter grams above 0.` |
| `spool move <n> <location\|auto>` | Moves it; `auto` sends `{"auto_location": true}` and the Hub moves the spool where its placement rule puts it | An unknown location stops with exit code 2 and its Fix line lists the Hub's locations |
| `spool empty <n>` | Marks it as used up | |
| `spool label <number>... --out <file.svg>` | Writes the labels of these spools as SVG (below) | Needs no sudo and changes nothing; `--json`: `{"ok": true, "file", "size", "labels"}` |

**`spool label`** draws the labels the Hub page's **Print a label** prints (`02-components.md` 7.13) and writes them to
the file `--out` names; the printing is then the person's (open the file in a browser, or in a program that prints
SVG). `--size` is `62x29` (the default, a 62 mm roll), `50x30` or `sheet24` (24 to a sheet, A4 or Letter by the
printer). The one file holds a label for each number, in the order given.

```
$ spoolwarden spool label 214 213 --size 62x29 --out labels.svg
Wrote 2 labels (62 x 29 mm) to labels.svg.
Note: the codes hold this Hub's address (https://spoolwarden.local/s/214). If the Hub is renamed or moves to another
      port, old labels stop opening from a phone's camera; the Spoolwarden app's scanner still reads them.
```

- Without `--out`: `Error: say where to write the file.` and `Fix: add --out <file.svg>.` (exit code 2). A number the
  Hub does not know: `Error: spool 999 was not found.` and `Fix: spoolwarden spools lists the numbers.` (exit code 2). A
  size that is not one of the three: `Error: the size must be 62x29, 50x30 or sheet24.` (exit code 2).

`spool` with no word prints these five commands and the line of section 10 for what still needs a phone: a tag is linked
by tapping it, and spools are added from photos or by hand.

### 9.22 `activity`

`spoolwarden activity` lists what was done on the Hub, as Logs > Activity does (`03-hub-page.md` 13.4): newest first,
the events that are something done (not the conditions of `events`). Reading needs no sudo. Options: `--spool <n>`
(only that spool's events), `--who <name>` (a paired device's name, `Hub page`, `command line`, `Claude connector`
or `The Hub`; an unknown name stops with exit code 2 and its Fix line lists the names) and `--days 7` (how far back,
7 by default).

```
$ spoolwarden activity --days 7
ID    TIME              WHO            WHAT
1431  2026-11-12 14:11  command line   Moved spool 214 to Shelf B.                       undo
1429  2026-11-12 14:09  Kitchen phone  Moved Bambu Lab PETG HF Orange (212) to Shelf B.  undo
1426  2026-11-12 03:00  The Hub        Backup finished (4,812 KiB, encrypted).

3 events in the last 7 days.
```

- `WHAT` is the text the Hub built for the event; the word `undo` ends a row that can still be undone (`spoolwarden undo
  <ID>`, 9.23); an undone row ends `(undone)`.
- Nothing in the range: `Nothing has been done in the last 7 days.` More than 200 rows: the newest 200 and the line
  `Showing the newest 200. Narrow it with --days, --who or --spool.`
- `--json`: the answer of `GET api/events` with `activity=1` (6.8).

### 9.23 `undo`

`spoolwarden undo` puts back the last change made from the command line: it shows that change, asks `Undo it? [y/N]`
(section 7) and asks the Hub. `spoolwarden undo <event id>` puts back a named one (the ID column of `activity`). It
needs sudo and takes `-y`. The rule is the Hub's (`03-hub-page.md` 2.9): an event is undone once, for 7 days, and only
while nothing changed since.

```
$ sudo spoolwarden undo
2026-11-12 14:11 · Moved spool 214 to Shelf B.
Undo it? [y/N] y
Put back.

$ sudo spoolwarden undo 1429
2026-11-12 14:09 · Moved Bambu Lab PETG HF Orange (212) to Shelf B.
Error: This changed again since, so it cannot be undone.
```

- A refusal prints the Hub's text after `Error:` and exits with code 1. No change made from the command line in the last 7
  days: `Nothing has been changed from the command line in the last 7 days.` (exit code 0). An event number the Hub does
  not know: `Error: there is no event 1429.` (exit code 2).
- After a load or an unload the answer adds `The printer still shows what it was set to.`
- `--json` needs `--yes` (6.8) and prints the answer of `POST api/events/<id>/undo`.

### 9.24 `usage`

`spoolwarden usage` shows the filament used by all printers, from the filament-used logs, undone entries left out
(`03-hub-page.md` 17). Reading needs no sudo. Without options it prints this month's sentences; `--by month` prints the
last 12 months as a table; `--printer <name>` limits either to one printer (a name, serial or unique start of a name, as
section 5 gives).

```
$ spoolwarden usage
Filament used this month: 1.84 kg (last month 1.52 kg).
Your favourite material this month was PA6 (640 g).
Workshop X1 did the most work this month (1.1 kg, 23 prints).
2 of 25 prints did not finish this month (96 g).
The biggest print this month was bracket_v4.3mf (212 g).
You finished 3 spools this month.
Includes 38 g the Hub logged but took off no spool. 2 prints have no weight.

$ spoolwarden usage --by month --printer "Workshop X1"
MONTH    GRAMS   PRINTS  DID NOT FINISH  MOST USED MATERIAL
2026-11  1,100       23               2  PETG
2026-10    920       19               1  PLA
```

- Each sentence is printed only when its numbers exist, in the order of the Hub page; the last line is the honesty notes
  of the Hub. With no filament used this month: `No filament used this month.` With none in 12 months: `No filament used
  yet.`
- `--json`: the answer of `GET api/analytics` (6.8), with `printer` when `--printer` is given.

### 9.25 `export` and `import`

**`export <set>`** writes one set as a CSV file (`03-hub-page.md` 2.10): `usage` (`--days N`, `--printer <name>`),
`locations`, `recent`, `activity` (`--days N`), `printers`, `lines`, `spoolman-spools` and `spoolman-filaments` (what
Spoolman's own export gives, passed on through the Hub). With `--out <file>` the file is written there and the command
prints `Wrote 214 rows to usage.csv.`; without it the CSV goes to standard output and nothing else is printed. It needs
sudo, because a file leaves the Hub. Where Spoolman gives no export: `Error: Spoolman's own export is not available in
this Spoolman version.`

**`import <spools|locations> <file>`** reads a CSV file, checks it with the Hub's dry run (the same as Add spools),
prints what it read, asks and adds. It needs sudo and takes `-y`. It only adds: it never changes or removes a spool;
storage locations are added and same-named ones changed, never removed.

```
$ sudo spoolwarden import spools new-spools.csv
Checked 3 rows: 2 can be added, 1 has problems.
ROW  WHAT                                                               PROBLEMS
  1  Add 2 × Polymaker PolyTerra PLA Charcoal Black (PLA, 1000 g)
  2  Add 1 × Bambu Lab PETG HF Orange (PETG, 1000 g, Shelf B)
  3  left out                                                            net: Enter grams above 0.
Add 3 spools? [y/N] y
Added 3 spools: 215, 216, 217.
```

- The number in the question counts the spools to add; rows with a problem are left out and say so. Nothing can be
  added: `Nothing to add.` (exit code 1). A file that is not a CSV file Spoolwarden can read: `Error: this is not a CSV file
  that Spoolwarden can read.`
- The columns are those of `03-hub-page.md` 2.10; `spoolwarden export` has no sample file, the Hub page offers it.
- `--json` on `import` needs `--yes` and prints the Hub's answer (6.8).

### 9.26 `report`

`sudo spoolwarden report` collects a Hub report, the file the Hub page's **Collect a Hub report** makes
(`03-hub-page.md` 13.5), and prints where it is; `--out <file>` also copies it there.

```
$ sudo spoolwarden report
◐ Collecting a Hub report…
Hub report written: <backup folder>/hub-report-2026-11-12-1415.txt
It holds no address, host name, serial, token, key, code or e-mail address. Printers, devices and locations
are named printer-1, device-2 and location-3, and the Hub hub.
```

- The newest three reports are kept beside the backups. `--json`: `{"ok": true, "file": "<path>"}`.

### 9.27 `language`

`spoolwarden language` lists the languages of this Hub; `add`, `remove` and `set` change what the Hub keeps and need
sudo (`language set` is the Hub page's Settings > General > Language). `template` and `check` work on a file, need
neither the Hub nor sudo, and are for the person who translates. The packs come with each release
(`08-platform-mapping.md` section 12); English is always inside the product.

```
$ spoolwarden language
Hub language: English
CODE  LANGUAGE                      STATE      TRANSLATED
en    English                       in use     100 %
ru    Русский                       installed   96 %
de    Deutsch (machine-translated)  available  100 %
```

- `STATE` is `in use` (the Hub's language), `built in` (English when it is not in use), `installed` or `available` (a
  pack of this release that is not installed yet). `TRANSLATED` is how much of the English the pack has translated.
  When the list of the release's packs could not be fetched, the installed languages are listed and `Note: the list of
  languages could not be fetched (<reason>).` goes to standard error. `--json`: the answer of `GET api/languages` plus
  `available` (6.8).
- `sudo spoolwarden language add de` starts the job of the Hub page's **Install** (a progress line, 6.6) and ends with
  `Installed Deutsch (machine-translated).`. The Hub checks the pack first; one that fails is not installed:
  `Error: Deutsch was not installed: <the check's first sentence>.` A code the release has no pack for: `Error: this
  release has no language de.` and `Fix: spoolwarden language` (exit code 2).
- `sudo spoolwarden language remove ru` ends with `Removed Русский.`; when `ru` is the Hub's language it is refused:
  `Error: Русский is the Hub's language. Choose another one for the Hub first.` (exit code 2). Removing any other
  installed language sets the devices that had chosen it back to Automatic at their next visit. `sudo spoolwarden language set ru` with `The Hub's
  language is Русский.` and, for a language that is not installed, `Error: Русский is not installed.` and `Fix: sudo
  spoolwarden language add ru` (exit code 2).
- `spoolwarden language template ru` writes a pack for that language with every English text and empty translations to
  `ru.xml` in the current folder, or to `--out <file>`: `Wrote ru.xml: 1,640 texts, none translated.` When the file
  `--out` names is already a pack of that language, its translations are kept, the texts that are new are added and the
  texts whose English changed are marked `changed="yes"`: `Updated ru.xml: 12 new texts, 3 changed.`
- `spoolwarden language check ru.xml` reads the file and says in plain sentences what is wrong, with the line, and how
  much is translated. It prints nothing but the result, and exits with code 0 when nothing is wrong and 1 when
  something is.

```
$ spoolwarden language check ru.xml
ru.xml: Русский, made for 0.7.0.
Line 88: the tag <ru> is not closed: a ">" is missing after "</ru".
Line 120: {kolichestvo} is not a placeholder of this text. The English has {count}: keep it as it is.
Line 161: the text has a "&". Write it as "&amp;".
Line 212: the plural form <many> is empty while <one>, <few> and <other> are filled. Fill it, or empty all four.
1,402 of 1,640 texts are translated (85 %). 4 problems.
```

- A missing or extra `{placeholder}`, a broken tag, a plural form left empty where others are filled and a form the
  language does not have are the problems it names; an empty translation is not a problem (the English is used).
  `--json`: `{"ok": true or false, "texts", "translated", "problems": [{"line"?, "text"}]}` (6.8).

### 9.28 `demo`

`spoolwarden demo` says whether the demo is on; `sudo spoolwarden demo on` and `sudo spoolwarden demo off` start and end
it. The demo is the whole product on made-up data with pretend printers (`03-hub-page.md` 3.9).

```
$ spoolwarden demo
The demo is off.

$ sudo spoolwarden demo on
The demo is on. Look around on the Hub page: https://spoolwarden.local/setup
Leave it with: sudo spoolwarden demo off

$ spoolwarden printer list
Demo data.
NAME           TYPE     ID               ADDRESS             STATE
Workshop X1    Bambu    00M00A000000001  192.0.2.40          ● connected
...
```

- `demo on` works only on an empty Hub, one with no spool and no printer; otherwise
  `Error: The demo is for an empty Hub. This Hub has real data.` (exit code 1).
- `demo off` asks once, with the dialog's words (section 7): `Leave the demo? Everything in it is deleted. [y/N]`, and
  takes `-y`. It deletes the demo's folder and the Hub is empty again: `The demo is off.`
- While the demo is on, every command that prints a result prints `Demo data.` above it (6.4). A command that would
  reach outside the Hub (a printer, Spoolman, the Label Reader's cloud, GitHub, a push, a backup, a flash, the root
  helper) stops with `Error: Not in the demo.` (exit code 1); `printer live` still says where the camera is, and the
  camera says "No camera in the demo."
- `--json`: `{"demo": true or false}`; `demo on` and `demo off` add `"ok": true` (6.8).

## 10. What the command line cannot do

Some features need a camera, NFC or a screen for photos. Where a person might look for them on the command line,
the command prints one line saying where they are, with the address to open, and exits with code 0. When the
line and the address do not fit the width together, the address goes on the next line. With `--json`:
`{"available": false, "where": "web app", "url": "…"}`.

| Feature | Command | The line it prints |
|---|---|---|
| Live printer view: the camera, pause, resume, stop, the light | `printer live <printer>` | `The camera and the print controls are on the Hub page: https://192.0.2.10/setup#printers/<id>` |
| Add spools, from label photos or by hand | `add` | `Add spools in the web app, app or Weigh Station: https://192.0.2.10/intake` |
| Link a tag to a spool by tapping it | `spool` | `A tag is linked by tapping it, in the web app or the app: https://192.0.2.10/intake` |
| The photos of a Recently added record | `recent show <record>` | `Photos open on the Hub page: https://192.0.2.10/setup#recent/35` (`--photos` adds their file paths) |
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
| Pair a phone or device (QR and code) | Y | Y | - | Y | Y, and waits for the device (`--no-wait` ends at once) | none |
| List and forget paired devices | P | Y | N | Y (forget without asking) | Y (`devices`; asks) | web app: remains |
| Hub status and checks | P | Y | N | Y | Y, grouped as Overview, `--json` | web app, app: remain |
| Add spools by hand | Y | N | Y | N | N (`add` prints where) | remains: needs a phone or the Weigh Station |
| Add spools from label photos | Y | N | Y | N | N (`add`); `label-reader test` reads photos without adding | remains: needs a camera |
| Share corrections: switch it on or off | N | new | N | N | new (`config`, `config set`) | web app, app: remain on purpose (Hub settings are on the Hub page) |
| Share corrections: see what is waiting, remove | new | new | new | N | new (`label-reader corrections`, `remove`) | none |
| Share corrections: download the package, send | N | new | N | N | new (`label-reader corrections package`, `send`) | web app, app: remain on purpose (sending is done on the Hub) |
| Open a spool: link a tag, set weight, move, mark empty | Y | new | Y | N | P (`spool weigh`, `move`, `empty`; a tag is linked by tapping it) | remains: linking needs NFC |
| Search spools | Y | new | Y | N | Y (`spools`) | none for the command line |
| Add a filament line | Y | new | new | N | Y (`catalog add --ask`) | none for the command line |
| Slicer presets: status, change parent | P | Y | Y | Y | Y | none |
| Slicer presets: build, restore deleted, accept updates | N | Y | N | Y (accepts without asking) | Y (asks) | app, web app: remain |
| Recently added: list, show | N | Y | Y | Y | Y | app: remains |
| Recently added: revise, edit, undo | N | Y | Y | Y | Y | app: remains |
| Records kept (Recently added setting) | N | Y | N | Y | Y | none for the command line |
| Printer list; add a Bambu Lab printer with its Access Code | Y | Y | Y | P (inside `config` only) | Y (`printer list`, `printer add`) | **closed** |
| Add a Klipper printer | N | Y | Y | Y | Y (`printer add --klipper`) | app: remains |
| Find Klipper printers | N | Y | P | Y | Y (`printer scan`, `use`, `dismiss`) | none for the command line |
| Test, rename, change address, replace Access Code or API key, lane data, detect, forget certificate, forget printer | Y | Y | Y | P (rename and remove in `config`; unpin; API key) | Y (one `printer` command each) | **closed** |
| Live printer view: camera, pause, resume, stop, light | Y | new | Y | N | P: state and slots in `printer show --watch`; `printer live` prints where the camera and controls are | remains: needs a screen for the camera |
| Map slots | Y | Y | Y | Y | Y | none |
| Map by loading filament | Y | Y | Y | Y | Y | none |
| Collect a printer report | Y | Y | Y | Y | Y | none |
| Saved printer reports | unknown | Y | unknown | N | Y (`printer reports`) | **closed** |
| Load or unload a spool in a slot; clear a slot | Y | new | Y | N | Y (`printer load`, `unload`, `clear`) | none for the command line |
| Load a spool into whichever slot gets a spool next (Auto), with its notice, Stop waiting and the choice between two slots | new | new | new | N | P (`printer load <printer> auto <spool>`; the notice and the choice in `printer show`) | remains: Stop waiting and the buttons of the choice are on the Hub page, the web app and the app; on the command line a named `printer load` of the same spool into a slot does the work of the choice and ends the assignment |
| Filament used, with undo | Y | new | Y | N | P (`printer usage` lists it; `usage` totals it) | remains: a filament-used entry's undo is on the Hub page, the web app and the app |
| Features on and off | N | Y | N | Y | Y, needs shown before switching | none for the command line |
| Choose the setup | N | Y | N | Y | Y (`features setup`) | none for the command line |
| Backups: make, list, download | N | Y | N | Y | Y | none for the command line |
| Keep nightly backups for N days | N | Y | N | N | Y (`backup keep`, `config`) | **closed** |
| Restore from a backup | N | Y | N | Y | Y | none for the command line |
| Updates: check, install, roll back | P | Y | N | Y | Y | web app: remains |
| Anthropic API key: set, check, remove | N | Y | N | Y | Y (`config`, Label Reader) | none for the command line |
| Web passphrase | N | Y | N | Y | Y | none for the command line |
| Catalog token | N | N (no field) | N | N | Y (`catalog token` is the one place) | none |
| Setup code: show, new; revoke all trusted computers | N | Y | N | Y | Y (new code asks) | none for the command line |
| Trusted computers: list, rename, revoke one | N | Y | N | N | N | remains: Hub page only |
| Weigh Station: pair, flash the display | N | Y | N | Y | Y | none for the command line |
| Devices: kind, version, out of date | new | new | N | N | new (`devices`) | web app: remains |
| A Weigh Station's detail: status, sounds, lamps | N | new | N | N | new (`devices show`, `devices set`) | app, web app: remain |
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
| Alerts: banners, toast, Alerts list, notifications | new | new | new | N | new (`events`, `events --follow`) | none for the command line |
| Alerts: switches and thresholds | N | new | N | N | new (`alerts`, `alerts set`, `config`) | app, web app: remain on purpose (Hub settings are on the Hub page) |
| Alerts: send a test alert | new | new | new | N | new (`alerts test`) | none |
| Spools running low | new | new | new | N | new (`spools low`, `status`) | none |
| Storage use of the Hub's disk | N | new | N | N | new (`status`, `status --json`) | app, web app: the banner and the Alerts list only |
| Getting started: what is left to set up | N | new | N | N | new (`status`, `status --json`) | app, web app: a one-line summary comes later; Hide, Show and Keep: Hub page only |
| Add a printer, guided (found list, test, slots) | N | new | N | N | new (`printer add` in the guided order) | app, web app: the guided order comes later |
| The Hub's port: show, change | N | new | N | N | new (`port`) | app, web app: remain on purpose (Hub settings are on the Hub page) |
| Installer: the first question (Guided Setup), the port | N | N | N | Y (the installer's own questions) | new (9.20) | command line only, by design |
| Undo the last change (weight, move, empty, tag, load, unload, clear slot) | new | new | new | N | new (`undo`) | none |
| Activity: who did what | N (a spool's last ten events) | new | N (a spool's last ten events) | N | new (`activity`) | app, web app: the spool's last ten events only |
| Health history of the checks | N (the table) | new | N (the table) | N | new (`status --history`) | app, web app: the table only |
| Analytics: filament used per month | new (By month) | new | new (By month) | N | new (`usage`) | none |
| Export as CSV | new (spools, filament used, Recently added) | new | new (spools, filament used, Recently added) | N | new (`export`) | app, web app: three sets only |
| Import spools and locations from CSV | N | new | N | N | new (`import`) | remains: Hub page and command line only |
| Backup password: set, change, remove; restore with it | N | new | N | N | new (`backup password`, `restore`) | remains: Hub page and command line only; showing it again: command line only |
| Hub report for a problem | N ("Collect a Hub report on the Hub page.") | new | N (the same sentence) | N | new (`report`) | app, web app: remain |
| Home Assistant: link it | N | new | N | N | new (`pair --home-assistant`) | remains: Hub page and command line only |
| Language: choose one, install more, make a pack | new (Settings > Appearance; the app carries its languages) | new (Settings > Appearance and General) | new (Settings) | N | new (`language`, `--lang`) | app, web app: no download of packs by the app; making and checking a pack: command line only |
| Demo mode: look around on made-up data | new (the notice) | new | new (the banner) | N | new (`demo`, the line `Demo data.`) | app, web app: Leave demo works in place; switching the demo on: Hub page and command line only |
| Spool labels: print them, scan one | new (Print a label, Scan a label) | new (Print a label, Print labels) | new (Print a label) | N | new (`spool label` writes the SVG) | app, web app: one label at a time; printing is the browser's or Android's |

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
7. **Share corrections.** What the reader can do and its state, the setting `label_reader.share_corrections`
   with the job that sets the reader, and the corrections waiting (list, remove, remove all, package, send) on
   the routes the Hub page uses (`03-hub-page.md` 10.5.2). Until they exist the `label-reader corrections`
   commands say `Error: this Hub cannot share corrections yet.` and the config item is not shown.
8. **Events and alerts.** The routes `GET api/events`, `GET api/alerts` (and the write behind the Alerts group),
   `POST api/alerts/test`, `GET api/spools/low` and `GET api/storage-use` (`03-hub-page.md` section 15). Until they
   exist `events`, `alerts` and `spools low` say `Error: this Hub does not keep events yet.` with the Fix
   `sudo spoolwarden update`, `status` has no Storage row and no Running low note, and the Alerts group is not shown
   in `config`.
9. **Getting started.** The route `GET start` (`03-hub-page.md` section 15), which `status` reads for its Getting
   started block. Until it exists `status` has no Getting started block and no `getting_started` key.
10. **Spools, slots, devices and the catalog form.** The kit routes `GET api/spools` (with `filter`, each spool with
    `loaded` and `low`, and `spoolman_url`), `POST api/printers/<id>/slots/<slot>/clear`, the changed `unload`,
    `POST api/printers/<id>/slots/auto/load` for `printer load <printer> auto <spool>` (and `auto_possible`, `watchable`
    and `auto` in the printer's answers),
    `GET api/library/local`, `POST api/library/local/form` and `DELETE api/library/local/<id>`, and the page routes
    `GET /setup/api/devices`, `GET /setup/api/device/<id>` and `POST /setup/api/device/<id>/settings`
    (`03-hub-page.md` section 15). Until they exist, the commands that need one say `Error: this Hub does not offer
    that yet.` with the Fix `sudo spoolwarden update`.
11. **History and data.** The kit routes `GET api/events` with `activity`, `subject` and `actor` and its `undo`,
    `undone` and `undo_of` fields, `event_id` in the answers of the routes that make an undoable change, `POST
    api/events/<id>/undo`, `GET api/health`, `GET api/analytics`, `GET api/export/<set>.csv`, `POST api/import/spools`
    and `POST api/import/locations`, the backup password and the encrypted backups, the Hub report, and the pairing kind
    `home-assistant` (`03-hub-page.md` section 15). Until they exist the commands that need one say `Error: this Hub
    does not offer that yet.` with the Fix `sudo spoolwarden update`.
12. **Languages, the demo and labels.** The page routes `GET /setup/api/languages`, `POST languages/<code>/install`,
    `POST languages/<code>/remove` and `POST settings/language`, `POST demo`, and the kit routes `GET api/languages`,
    `POST api/demo/leave` and `GET api/spools/<id>/label.svg`, with `key` and `params` beside `text` in every answer the Hub writes in words
    and `Accept-Language` or `?lang=` choosing its language (`03-hub-page.md` section 15). Until they exist `language`,
    `demo` and `spool label` say `Error: this Hub does not offer that yet.` with the Fix `sudo spoolwarden update`;
    `language template` and `language check` need nothing from the Hub.
