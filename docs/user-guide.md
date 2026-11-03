# filament-kit user guide

Everything the [README](../README.md) leaves out: install modes, every command, printers and slot mapping, presets
in Bambu Studio and Orca Slicer, the intake station, the Claude connector and phone web app, remote access and
order history. The README has the one-command install, the module list and where your data lives.

## What you need

- A computer running **Ubuntu 24.04 or newer**, on your home network, that stays on.
- Optional: an **Anthropic API key** (starts with `sk-ant-`), only for AI label reading. Without one you add
  spools by hand; you can turn label reading on later (`sudo filament-kit config`, 4 for the key and 6 for the
  `ai_intake` module).
- An Android phone (Android 10 or newer) for the filament-kit app.
- Optional: a Windows PC with Bambu Studio (and, if you like, Orca Slicer), for the presets.
- Optional: an **intake station**: a USB scale (DYMO) and a PN532 NFC reader on the same computer or on a second
  one (see [Intake station](#intake-station)).

## Install the server

Do these steps on the Ubuntu computer, in a Terminal window.

**One command** (it does steps 1 to 3 for you, checking the release's signature first):

```
curl -fsSL https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh | sudo bash
```

Options go after `sudo bash -s --`, for example `... | sudo bash -s -- --mode server` or `--version 0.3.0`.
While the repository is private, get `get.sh` with a GitHub token that can read it (for example
`gh release download -R thompsonfabco/filament-kit -p get.sh`), save the token in a file only you can read and run
`sudo bash get.sh --token-file <file>`. The token is never shown and is only sent to GitHub. Then answer the
questions as in step 4. Without a terminal it asks nothing: give the mode or modules on the command line, and with
`--modules` the settings a module needs, for example
`--modules server,web --set web.public_url=https://filament.example.com/filament`.

Or by hand:

1. Open the project's GitHub **Releases** page and download the newest `filament-kit-<version>.tar.gz`
   (for example `filament-kit-0.1.0.tar.gz`) into your **Downloads** folder.
2. Unpack it and go into the folder (use the version number you downloaded):

   ```
   cd ~/Downloads
   tar xzf filament-kit-0.1.0.tar.gz
   cd filament-kit-0.1.0
   ```

3. Run the installer. It asks for your password (that is normal for `sudo`):

   ```
   sudo ./install.sh
   ```

4. Answer the questions:
   - **Install mode**: press Enter for `1) server`, the usual choice. The other modes are in
     [Install modes](#install-modes).
   - **Display name**: the name the phone app shows for this server. Any text works (spaces, accents);
     press Enter to keep the suggested name. Phones find the server by the computer's own name, not this one.
   - **Read spool labels from photos with Claude**: press Enter for no (spools are then added by hand), or type
     `y` if you have an Anthropic API key.
   - **Default storage locations**: press Enter for yes. Type `n` if you want to name your own racks and
     boxes now (you can also change them later).
   - **Anthropic API key** (only if you answered `y` above): paste the key and press Enter. Nothing shows while
     you type or paste; that is on purpose.
5. At the end the installer prints a status list (no line should start with `FAIL`) and a **QR code** with a
   pairing code underneath.

The installer takes a few minutes. You can run it again at any time; it never deletes your spools or
settings.

## Install modes

The kit is made of parts called **modules** (Spoolman, the server, AI label reading, printers, presets, the spec
library, the nightly backup and the intake station). A **mode** is a ready-made set of them. The installer asks
for the mode on the first install:

| Mode | What it installs | Use it when |
|---|---|---|
| `server` (1, the default) | Spoolman, the server, printers, presets, backup (AI label reading and the library are switched on when you want them) | One computer runs the kit. |
| `station` (2) | Only the intake station (USB scale and NFC reader) | The station is a second computer and the server runs on another one. It asks for the **server's address**. |
| `all-in-one` (3) | Everything, station included | The scale and reader are plugged into the server computer. |
| `custom` (4) | One checklist of modules: type a number to switch one, and what it needs goes on too (what depends on it is listed when you switch it off). The same checklist is in `sudo filament-kit config` > Modules | You know which parts you want. |

AI label reading (the `ai_intake` module) is in no mode: the installer asks about it on the first install, and
`sudo filament-kit modules enable ai_intake` turns it on later. Without it, spools are added by hand in the phone
app and the phone web app. A station-only computer needs no API key, certificate or Spoolman.

You can also give the mode on the command line, so the installer asks no mode question. `--mode` takes
`server`, `station` or `all-in-one`; for `custom`, answer 4 at the question, give `--modules spoolman,server,printers` (what they need is added; for web, orders or a station add the setting they need with `--set web.public_url=https://...`, `--set orders.file=PATH` or `--set station.allow=ADDRESS`), or switch modules afterwards with
`sudo filament-kit modules enable <module>` and `sudo filament-kit modules disable <module>`:

```
sudo ./install.sh --mode server
sudo ./install.sh --mode all-in-one
sudo ./install.sh --mode station --server 192.0.2.10
```

`--server` is the kit server's name or IP address, for example `kit-server.local` or `192.0.2.10`. Give one
address, not a range. The station answers only that address and the station computer itself.

Running `sudo ./install.sh` again later (an update) asks no questions and keeps the mode you have. An install
from before modules existed counts as the `server` mode and works exactly as before, AI label reading included.

### All-in-one on one computer

Plug the USB scale and the NFC reader into the Ubuntu computer, then:

```
sudo ./install.sh --mode all-in-one
```

Answer the label reading, display name, storage and API key questions as in
[Install the server](#install-the-server). Besides
the usual server, this sets up:

- the station service `filament-kit-station`, which reads the scale and the reader and answers on port 5003,
  for this computer only (`http://127.0.0.1:5003/state`);
- the server's link to it, so `sudo filament-kit status` shows a line `station answering at
  http://127.0.0.1:5003`, and the phone app can read the scale and the last tag;
- the computer changes the station needs (see [Intake station](#intake-station)): brltty removed, ModemManager
  off, sleep and suspend off, audio unmuted, and a rule that lets the station read the DYMO scale.

Until a tag has been read and the scale has been switched on, `status` shows `station reader not seen` and
`station scale not seen`. Those lines are information, not failures.

### Change the mode later

Use either way. Both install what the new mode needs, start it, and stop what it no longer uses:

- `sudo filament-kit config`, then **6) Modules**. Pick **m) choose mode**, or type a module's number to turn it
  on or off. Turning a module off that others need asks to turn those off too. Choosing `station` asks for the
  server's address. Then **0) back** and **0) save and exit**.
- `sudo filament-kit modules set <mode>`, for example `sudo filament-kit modules set all-in-one`. For the station
  mode, add the server's address: `sudo filament-kit modules set station --server 192.0.2.10`.
  A mode never turns `web`, `remote` or `orders` on or off: the ones you turned on stay on, unless the new mode
  lacks a module they need (then they go off, and the command says so).
- One module at a time: `sudo filament-kit modules enable <name>` or `sudo filament-kit modules disable <name>`,
  for example `sudo filament-kit modules disable printers`. `sudo filament-kit modules list` shows the names and
  which are on.

Turning a module off **never deletes its data**. Spoolman's spools, settings and paired phones stay where they
are and come back when you turn the module on again. Only `sudo ./uninstall.sh --purge` deletes data. While a
module is off, the app gets the message that it is turned off for anything that needs it.

## Install the app and pair your phone

1. On your phone, download `filament-kit.apk` from the same GitHub Releases page and open it. If the phone
   asks, allow "install unknown apps" for your browser.
2. On the server, run:

   ```
   sudo filament-kit pair
   ```

   It prints a QR code, a 6-digit pairing code and the server's certificate fingerprint in the terminal.
3. Open the filament-kit app. On Android 17 and newer, allow **Local network** access when Android asks; the app
   can't find or reach the server without it (if you said no, the app shows **Allow** and, if Android stops
   asking, **Open app settings**). Then scan the QR code from the terminal.
   If the camera can't scan it, pick the server from the list in the app (or enter its address), check that the
   fingerprint matches the one `sudo filament-kit pair` printed, and type the 6-digit code instead.
4. The QR code and the code expire after a few minutes. If the app says the code has expired or was already
   used, run `sudo filament-kit pair` again.

## Pair your PC

Do this once, on the Windows PC where you use Bambu Studio. The PC sync tool sends your Bambu Studio filament
list to the server and installs the presets the server builds. One server works with **one** sync PC: the
first PC that syncs is the one. To move to another PC, remove the first one with `sudo filament-kit unpair`
(see [Everyday commands](#everyday-commands)); the next PC that syncs then starts fresh, like a first install.

1. On the PC, download `filament-kit-sync-setup-<version>.exe` from the same GitHub Releases page and run it.
   It does not need administrator rights.
2. On the Ubuntu computer, run:

   ```
   sudo filament-kit pair --pc
   ```

   It prints a long link that starts with `fkit://pair?`, the certificate fingerprint and a 6-digit code.
3. Click **Finish** in the setup with **Pair this PC with the filament-kit server now** ticked. A console window
   opens. (Missed it? Start menu, **Pair filament-kit sync**.)
4. In that console, paste the link and press Enter. (No link? Type the server's name or address instead. The
   window shows the server's certificate fingerprint. Check that it matches the one on the Ubuntu computer and
   type `y` to confirm it. Then it asks for the 6-digit code.) From then on the PC syncs every 10 minutes. It
   waits while Bambu Studio is open and tries again later, so close Bambu Studio to let new presets in.

The link and the code expire after a few minutes. If they do, run `sudo filament-kit pair --pc` again.

## Everyday commands

Run these in a Terminal on the Ubuntu computer.

| Command | What it does |
|---|---|
| `sudo filament-kit status` | Checks that everything works. Anything failing shows a `fix:` line telling you what to do. |
| `sudo filament-kit pair` | Shows a new QR code to pair another phone. |
| `sudo filament-kit pair --pc` | Shows the link and code to pair the Windows PC sync tool. |
| `sudo filament-kit unpair` | Lists paired devices: phones and the PC sync (named `pc`). `sudo filament-kit unpair <id>` removes one. |
| `sudo filament-kit config` | Settings menu: display name, storage locations, Claude model and daily limit, API key, printers, modules. |
| `sudo filament-kit modules list` | Shows each module on or off and the mode. `modules set <mode>`, `modules enable <name>` and `modules disable <name>` change them (see [Change the mode later](#change-the-mode-later)); `modules apply` sets the computer up again from the saved settings. |
| `sudo filament-kit printer map <serial>` | Maps a printer's AMS slots (see [Map slots](#map-slots)), printing each step. |
| `sudo filament-kit profiles status` / `build` | Shows or rebuilds the Bambu Studio and Orca Slicer presets (see [Presets](#presets-in-bambu-studio)). |
| `sudo filament-kit profiles lines` / `set-parent <line_id> <parent>` | Lists the filament lines; sets a line's Bambu Studio parent (`--orca`: its Orca Slicer parent). |
| `sudo filament-kit profiles restore-deleted` | Brings back, at the next build, the generated presets you deleted in Bambu Studio. |
| `sudo filament-kit library status` / `update` / `rollback` | The spec library (see [Spec library updates](#spec-library-updates)). |
| `sudo filament-kit printer unpin <serial>` | Forgets a printer's pinned certificate; the next connection trusts the one it presents. |
| `sudo filament-kit web passphrase` | Sets the sign-in passphrase of the Claude connector and the phone web app (see [Claude connector and phone web app](#claude-connector-and-phone-web-app)). |
| `sudo filament-kit web status` | Checks the web part: public address, passphrase, the service, signed-in connectors. |
| `sudo filament-kit remote firewall` | Prints the firewall and port-forward rules remote access needs (it changes nothing; see [Remote access](#remote-access)). |
| `sudo filament-kit remote issue` | Gets the https certificate with certbot (port 80 must reach this computer while it runs). |
| `sudo filament-kit reader token --name <name>` | Makes a token for the bench NFC reader, shown once ([reader/README.md](../reader/README.md)); `reader tokens` lists them, `sudo filament-kit reader revoke <id>` removes one. |
| `sudo filament-kit update` / `update --check` / `update --rollback` | Installs the newest signed release, only checks, or goes back (see [Update](#update)). |
| `sudo filament-kit migrate-ops <bundle>` | Moving from filament-ops: shows what it would do; `--apply` does it (see [Moving from filament-ops](#moving-from-filament-ops)). |

Your spool inventory (Spoolman) is also in a web browser on any computer at home:
`http://<computer name>.local:7912`, where `<computer name>` is the Ubuntu computer's own name (type
`hostname` in a Terminal to see it). The installer prints this address at the end.

## Bambu Lab printers

The server finds Bambu Lab printers by listening for the announcements they send on your home network. For
that to work:

- The Ubuntu computer must be on the **same network segment** as the printers: the same router or switch and
  the same Wi-Fi / LAN, not a separate guest network or VLAN. Announcements do not cross routers.
- If the computer runs a firewall (for example `ufw`), allow incoming **UDP ports 2021 and 1990** from your
  home network, for example `sudo ufw allow from 198.51.100.0/24 to any port 2021,1990 proto udp` (use your
  own network's range).
- A server inside **WSL**, a virtual machine with NAT networking, or a container without host networking does
  not receive the announcements. Add the printers by hand there: `sudo filament-kit config` → **Printers** →
  **add printer**, and enter the name, IP address, serial number and Access Code shown on the printer's screen.

A printer appears in the app once it has been seen on the network (or added by hand with its IP address); you
then enter its Access Code in the app to set it up.

### Add a printer

Use either way:

- In the app: open **Printers**. The printer must already be in the list (the server finds it on the network). Tap it, and type its **Access Code** (shown on the printer's screen).
- On the Ubuntu computer: `sudo filament-kit config`, then **Printers** and **add printer**. Enter the name, IP
  address, serial number and Access Code.

Then run **Map slots** (next section), and load spools into the printer from the app.

### Map slots

Before the server takes filament off your spools in Spoolman, it has to learn how the printer numbers its AMS
slots. **Map slots** in the app (or `sudo filament-kit printer map <serial>` on the Ubuntu computer) does that:

- It briefly changes each slot's colour on the printer to a test colour, checks which slot showed it, and puts
  every slot back as it was.
- It then runs a short calibration job that has **no heating and no motion** (only comments and a wait), so
  the printer reports which slot it used for each filament. The job file is deleted afterwards.
- The printer must be **idle** (not printing, paused or preparing) and online, or mapping is refused.

Until mapping succeeds, filament use is **only logged** (you can see it in the app's usage list) and nothing is
taken off your spools. If a slot could not be put back, mapping says which one so you can check it on the
printer.

- **Stopping a mapping** (Ctrl-C, closing the terminal, or restarting the server) always puts the slots back
  first and then reports the mapping as failed. If the computer loses power or the process is killed mid-way,
  the server keeps a note of every slot's original setting (`/var/lib/filament-kit/printers/<serial>/slottest-snapshot.json`);
  the next mapping run, or the server when it starts and the printer is idle, puts back every slot that still
  shows a test colour before doing anything else. A slot you changed in the meantime (another spool, Bambu
  Studio, the touchscreen) is left as you set it. A calibration job file left on the printer is deleted then
  too. A mapping refuses to start while that restore is not confirmed.
- Test colours are near-pure reds, `FAnn00FF` (the first two digits F7 to FE). Mapping picks test colours that
  no slot holds, so a real spool of such a red is mapped like any other. If the note file cannot be read,
  mapping says so: set the filament of any slot showing such a red again (on the printer or in Bambu Studio),
  then delete the file and map again.
- The calibration job is stopped at once if the printer starts heating or loading a filament, and a filament
  left loaded in the toolhead afterwards is reported. Only the calibration job itself is ever stopped: if
  someone starts another print meanwhile (touchscreen or Bambu Studio), mapping gives up on the calibration and
  leaves that print alone.
- Loading a spool and mapping never run at the same time on one printer; the second one is refused with "try
  again".

When a print ends, its filament is taken off the spools in its slots. An entry in the usage list says why when it
could not be: for example the printer didn't say which slots it used (`no_mapping`), or a slot isn't in the slot
map (`unmapped_slot`, run **Map slots** again).

Spools in a printer's slots have the location "<printer name> – AMS <slot>" in Spoolman (the printer's serial
number when it has no name). If you rename a printer, the spools already in its slots keep the old location
text: load them again (or fix their location in Spoolman) so filament use finds them.

If a printer's certificate changed, the server stops talking to it. If you reset the printer or its mainboard was
replaced, add the printer again with its Access Code (or run `sudo filament-kit printer unpin <serial>`). If not,
something else may be answering at the printer's address: check the printer's IP before re-adding it.

A backup of your spools and settings is made every night in `/var/backups/filament-kit` (the last 14 days are
kept).

### Your own printer data (override)

The facts about each printer model and AMS unit come from the kit's own `bambu_hardware.xml`. To correct or add
something, put your own file at `/etc/filament-kit/bambu_hardware.xml`. It wins element by element over the
kit's own file, and the updater never replaces a file you made.

Your file must carry a **version above the kit's own file**, in its first line: for example, when the kit's file
says `<bambu-hardware version="1.0">`, write `<bambu-hardware version="1.1">`. A file whose version is the same
as or lower than the kit's own is **ignored**, so an old file never hides newer data that an upgrade brings.
`sudo filament-kit status` then shows a note: "override version ... is not newer than the kit's own ...:
ignored". After an upgrade that ships a newer file, check that note: raise your file's version again, or delete
your file if the new release already has what you added. A file with mistakes is refused whole (the last good
data stays in use), and status names it.

## Presets in Bambu Studio

The server builds one Bambu Studio filament preset for each filament line you own (a line is a brand's product,
for example one brand's PLA, without the colour), for each of your printers and each nozzle size. The PC sync
then installs them in Bambu Studio.

- Names look like `<brand> <line> @Bambu Lab <printer> <nozzle> nozzle`.
- Spoolman data for your filaments wins over the library, and the library wins over Bambu's own starting preset
  (the "Bambu Studio parent").
- **Your edits are kept.** If you change a preset in Bambu Studio, the server keeps those values the next
  time it builds.
- **Delete presets in Bambu Studio, never on disk.** The PC sync never deletes preset files. A preset that is
  no longer built is listed as "delete in Bambu Studio" in the sync log; delete it there yourself.
- A generated preset you delete in Bambu Studio stays deleted: later builds leave it out. To get the deleted
  ones back, run `sudo filament-kit profiles restore-deleted`; the next build brings them back and the PC sync
  installs them.
- Bambu's cloud keeps about 100 filament presets. The rest stay on this PC only.
- A line the library doesn't have: in the app tap **Add profile** and fill in the line.
- To change which Bambu preset a line starts from, change its **Bambu Studio parent**: in the app, on the
  **Check the spools** screen while you add spools (field **Bambu Studio parent**; it applies to every colour of
  that line), or in **Add profile**, or on the Ubuntu computer with `sudo filament-kit profiles lines` (lists the
  lines) and `sudo filament-kit profiles set-parent <line_id> <parent>`.
- To see how the last build went: `sudo filament-kit profiles status`. To rebuild now:
  `sudo filament-kit profiles build`. (It needs the PC sync to have run once.)

## Presets in Orca Slicer

The server can also build Orca Slicer filament presets, for your Bambu Lab printers and for other printers Orca
Slicer knows (for example a Sovol). This is off until you ask for it in `/etc/filament-kit/config.json`:

- `"presets_orca": true` makes Orca presets for the Bambu Lab printers the server knows, for every nozzle Orca
  has for them except 0.2. To choose the nozzles, add for example `"presets_orca_nozzles": ["0.4", "0.6", "0.8"]`.
- `"slicer_printers"` adds printers that are not Bambu Lab ones. Each entry names the printer as Orca Slicer
  does and its nozzles:

  ```
  "slicer_printers": [
    {"name": "Sovol SV08 MAX", "slicer": "orca", "nozzles": ["0.4", "0.6", "1.0"],
     "label": "SV08 MAX",
     "compatible_printers": {"0.4": "Sovol SV08 MAX", "0.6": "Sovol SV08 MAX 0.6", "1.0": "Sovol SV08 MAX 1.0"}}
  ]
  ```

  `label` (optional) is the printer's name in the preset names. `compatible_printers` (optional) gives, for each
  nozzle, the name of the printer preset in Orca Slicer that the filament preset belongs to; use it when your
  printer presets are named differently from the default.

Then run `sudo filament-kit profiles build` (or wait for the next sync).

- Names look like `<brand> <line> @<printer> <nozzle>`, for example `SUNLU PLA+ 2.0 @SV08 MAX 0.4`.
- Each line also has an **Orca Slicer parent**, the Orca system preset it starts from. The server picks one;
  `sudo filament-kit profiles lines` shows it and `sudo filament-kit profiles set-parent --orca <line_id> <parent>`
  changes it (give the parent's name without ` @System`).
- The PC sync finds Orca Slicer on the PC by itself (its folder in `%APPDATA%\OrcaSlicer`). It sends the Orca
  presets to the server along with the Bambu Studio ones and installs the Orca presets the server builds. It waits
  while Orca Slicer is open, just like for Bambu Studio. A PC without Orca Slicer only gets the Bambu Studio
  presets. While the server makes no Orca presets (no Orca printers set up as above), the PC sync leaves Orca
  Slicer alone: it does not wait for it and sends nothing from it. `filament-kit-sync status` on the PC shows the
  Orca folder it uses.
- The same rules as for Bambu Studio apply: your edits in Orca Slicer are kept, and presets are deleted in Orca
  Slicer, never on disk.
- `sudo filament-kit profiles status` shows the last build (its count is the Bambu Studio presets) and the
  problems of both slicers, for example a line whose Orca parent is not in your Orca Slicer.

## Spec library updates

The library holds published filament specs (temperatures, speeds). It is optional and is not part of the
program: profiles work without it, from your Spoolman values and Bambu's or Orca's own starting presets. Ask for it
with `sudo filament-kit library update`, or switch the **library** module on (it then also checks every day). A
copy you downloaded earlier keeps being used when the kit is upgraded.

- `sudo filament-kit library status`: shows the library version (or that none is downloaded) and the last check.
- `sudo filament-kit library update`: downloads the library, or a newer version, now.
- `sudo filament-kit library rollback`: goes back to the version before the last update. The next daily check
  installs the newer version again. To keep the rolled-back version, turn the daily check off first: in
  `/etc/filament-kit/config.json` set `"library": {"schedule": "off"}` (or `"weekly"`; the default is
  `"daily"`), then roll back. Set it back to `"daily"` to get updates again.
- `sudo filament-kit library add <file>`: adds or replaces your own entry from a JSON file.

The download is the `library.tar.gz` asset of the latest release (`library.url` in the config can point to
another `.tar.gz` or to a folder that serves `index.json` and the entries). The release's `library.tar.gz` is
checked against the release's signed `SHA256SUMS`, like the program itself, and refused without it. Another
`.tar.gz` is checked the same way when a signed `SHA256SUMS` sits next to it; otherwise (and for a folder URL)
`library update` prints a note that it is not signature-checked. Every entry is checked before it is used, and a
bad download changes nothing. The token below is only ever sent to api.github.com and objects.githubusercontent.com,
as for program updates. Testing against a private repository: put a GitHub token that can read it in
`/etc/filament-kit/github_token`; the `releases/latest/download` link does not accept a token for a private
repository, so find the asset's id (`gh api repos/<owner>/<repo>/releases/latest --jq '.assets[] | [.name, .id]'`)
and set `library.url` to `https://api.github.com/repos/<owner>/<repo>/releases/assets/<id>`. Until the release is public, `library update` shows an error and the daily check
logs a warning; neither is a failure, and the library you already have (or none) keeps working.

Your own `library add` entries override the shared library for that line.

## Intake station

The intake station weighs a spool and reads its NFC tag, so adding or opening a spool needs no typing. It runs as
the `station` module, on the server computer (`all-in-one`) or on a second computer (`station` mode, see
[Install modes](#install-modes)).

### Hardware

- A **DYMO USB postal scale** (for example the M10 or M25). Switch it on before you start the station; a DYMO
  only shows up on USB while it is on, and it switches itself off after a few minutes.
- A **PN532 NFC reader** on a USB serial adapter (CH340 chip).
- Optional: the **button panel** (Hold and Discard buttons, lamps and a buzzer on a Wemos D1 mini). How to
  build and flash it: [station/PANEL.md](../station/PANEL.md).
- Optional: a speaker (USB or the computer's headphone socket) for the scan beep when there is no panel.
- Optional, with the panel: a **BME280** sensor for room temperature and humidity, a small speaker on the panel
  (it says things like "Held, 1042 grams") and a **USB webcam** that takes a picture of the spool when you press
  Hold. All of it is in [station/PANEL.md](../station/PANEL.md). The station installs `espeak-ng` and `ffmpeg` for
  the speech and the picture, and its user joins the `video` group to read the camera.

### What the installer changes on the computer

Turning the station on (install or **Modules**) also changes these, because each one stops a station from
working:

- **brltty is removed.** It takes CH340 USB adapters for braille displays and grabs the reader.
- **ModemManager is turned off.** It probes every new USB serial port and confuses the reader and the panel.
- **Sleep, suspend and hibernate are turned off** (masked). An idle Ubuntu desktop otherwise goes to sleep and
  the station stops answering.
- **Audio outputs are unmuted** at 80% and saved, so the scan beep can be heard.
- A **udev rule** (`/etc/udev/rules.d/99-zz-filament-kit-station.rules`) lets the station read the DYMO scale
  without running as root.

Turning the station off again, or switching to another mode, leaves these changes as they are. To undo them by
hand: `sudo systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target`,
`sudo systemctl enable --now ModemManager`, and `sudo apt-get install brltty`. Uninstalling removes the udev rule.

### Reader, panel and beep

- The panel and the reader both use CH340 USB adapters, which have no serial numbers. The station finds the
  panel by asking each port who it is, and the reader gets the other port (`NFC_DEVICE=auto`). With no panel,
  the reader gets the first USB serial port.
- A scan beeps on the panel's buzzer, or, without a panel, through a USB speaker or the headphone socket
  (`STATION_BEEP`).
- With the panel, Hold and Discard also speak (`"speech"`), and Hold takes a picture with the webcam
  (`"camera"`). `curl http://127.0.0.1:5003/state` then shows `"air"` (the BME280 reading) and `"photo"`, and the
  picture itself is at `/photo`. The station only answers GET requests, and only the addresses it allows.
- These settings are in `/etc/filament-kit/config.json` under `"station"`: `"nfc_device"` (`"auto"`, or a
  device such as `"tty:USB0:pn532"`), `"beep"` (`true` or `false`), `"beep_device"` (empty for automatic, or
  an ALSA device such as `"plughw:1,0"`), `"speech"` (`true` or `false`) and `"camera"` (`"auto"` for the first
  USB camera, a device such as `"/dev/video0"`, or `"off"`) and `"panel_flash"` (`true` or `false`, see the
  next point). After a change, run `sudo filament-kit modules apply`.
- **Panel firmware updates itself.** The station carries the panel's firmware. When it finds a panel running
  another version, it writes the bundled one to it over USB (once per version) and then uses it. If that does
  not work, the panel keeps running as it is. Set `"panel_flash": false` to never touch the panel's firmware.
  `curl http://127.0.0.1:5003/state` shows the panel's version as `"panel_version"`.

### Is it working?

- `sudo filament-kit status` on the server shows `station answering at ...`. `station reader not seen` means no
  tag has been read yet; `station scale not seen` means the scale has sent nothing yet (switch it on and put
  something on it).
- On the station computer: `curl http://127.0.0.1:5003/state` shows the last tag and weight.
  `sudo journalctl -u filament-kit-station -n 30` shows what the station is doing; `NFC reader ...; retrying in
  5 s` means the reader is not plugged in or not found.
- The station answers only its own computer and the server's address. Anything else gets no answer.
- A station on a second computer: on the **server**, put the station's address in
  `/etc/filament-kit/config.json` under `"station"`, for example `"url": "http://station.local:5003"`. If the
  server's address changes, run `sudo filament-kit modules apply` on the station computer so it answers the new
  one.

## Tag readers and printer slots

### More tag readers

Besides the intake station, the kit can read tags from other NFC readers that report the last tag they saw, for
example a reader on a printer. List them in `/etc/filament-kit/config.json`:

```
"tag_sources": [{"name": "printer", "url": "http://printer-reader.local:5002/last-tag"}]
```

Each address must answer a GET with JSON like `{"status": "ok", "nfc_id": "04A1B2C3", "read_at_unix": ...,
"age_seconds": 12}` (the station's own `/last-tag` speaks the same). The newest tap across all readers and the
station wins. A tap from the last 5 minutes, or a spool held on the station's panel, counts as the spool you are
working on: a label read then treats that spool as opened, and the Open spool tab of the phone web app shows it.
A reader that does not answer is skipped for a minute.

### Printer slots for the Claude connector

The connector's `printer_slots` and `printer_set_slot` tools show and set what is loaded in a printer's AMS
slots. With the `printers` module on, they use the kit's own printer connection. If another service of yours
already talks to the printer, point the tools at it instead, so the kit never connects to that printer:

```
"slot_service": {"state_url": "http://127.0.0.1:8105/api/state", "set_url": "http://127.0.0.1:8104/set-slot",
                 "token_file": "/etc/filament-kit/slot_token"}
```

The token file holds the bearer token for `set_url` (copy it with `sudo install -m 640 -o root -g filament-kit
<file> /etc/filament-kit/slot_token`; never paste it into config.json). `sudo filament-kit web status` shows which
one is in use.

## Claude connector and phone web app

The `web` module runs one more service, `filament-kit-web`, on this computer only (`127.0.0.1:8101`). It gives:

- a **Claude connector** (an MCP server) at `<public address>/mcp`, so Claude can find spools, add spools,
  open a spool, check the presets and the printer slots for you (tools `find_spools`, `add_spools`, `tag_state`,
  `open_spool`, `preset_status`, `list_lines`, `find_parents`, `add_filaments_to_line`, `add_line`, `generate`,
  `printer_slots`, `printer_set_slot`);
- a **phone web app** at `<public address>/intake`, in any phone browser (no install): add spools by hand (or
  from label photos, with `ai_intake`), open a tapped spool, and see the presets. With the `printers` module on it
  also has a **Printers** tab (replaces the old `/printer/` page): a printer picker, live status, the camera,
  pause / resume / stop (stop asks first), the chamber light, the filament in each AMS unit, the usage log with
  undo, and a re-map button. The camera is a picture stream on printers that have one and an HLS video on the
  rest (HLS plays in Safari on iPhone and Mac). The light button follows the printer's reported chamber light;
  the kit switches both light nodes when a printer has two, as the old page did. Print alerts to the phone
  (Web Push) are off; `"web": {"push": true}` turns them on, needs `pip install 'filament-kit[push]'` and lets the
  web service reach the browsers' push services on the internet, which the kit does not open for you.

Both use one passphrase. Adding spools does a dry run first in both, as in the Android app.

### Turn it on

1. Pick the **public address**: the `https://` address people (and Claude) will use, ending in a path such as
   `/filament`, for example `https://filament.example.com/filament`. It must start with `https://`, also when the
   web part is only used at home: the connector's sign-in only works over https. The web service itself only
   listens on this computer, so something has to carry that address to it: the kit's [Remote access](#remote-access)
   module, or a web server of your own that passes the path on to `http://127.0.0.1:8101`.
2. Put it into `/etc/filament-kit/config.json`:

   ```
   "web": {"public_url": "https://filament.example.com/filament"}
   ```

3. Set the passphrase (at least 12 characters; you type it twice and nothing shows):

   ```
   sudo filament-kit web passphrase
   ```

4. Turn the module on and check it:

   ```
   sudo filament-kit modules enable web
   sudo filament-kit web status
   ```

   `web status` shows the public address, the connector and phone app addresses, whether the passphrase is set,
   whether the service answers, and how many connectors and phones are signed in. No line should start with
   `FAIL`.

### Add the connector in Claude

In claude.ai, add a custom connector with the address `<public address>/mcp`. Claude then opens a sign-in page:
type the passphrase there. Claude stays signed in after that; changing the passphrase later does not sign it out.

### Use the phone web app

Open `<public address>/intake` on the phone, type the passphrase and add the page to the home screen if you
like. It stays signed in for 30 days.

### What only works at home

The sign-in pages (`/authorize`, `/login`) and the whole phone web app answer only addresses from your home
network. Elsewhere they say that sign-in is only available from the home network. Claude's servers reach the connector itself
(`/mcp` and the token exchange) from the internet, so sign Claude in from home once. The home network is the
`192.168.0.0/16` and `10.0.0.0/8` by default (not `172.16.0.0/12`, where Docker's bridges live); set your own
in `"web": {"lan": ["198.51.100.0/24"]}` (each entry a network; `modules apply` refuses a bad one). Five wrong passphrases
lock the sign-in for 10 minutes.

## Remote access

The `remote` module puts the web part on a public `https://` name, with a free certificate from Let's Encrypt.
It installs nginx and certbot. It **never changes your firewall or router**: it prints the rules, and you set
them up yourself.

1. Do [Claude connector and phone web app](#claude-connector-and-phone-web-app) first (`web.public_url` set).
   Its host name is the public name; you can also write it as `"remote": {"hostname": "filament.example.com"}`,
   which must then be the same name. Optional in `"remote"`: `"email"` (certbot's expiry mails) and
   `"acme_window"`, see the port 80 note below.
2. Make the name point to your home's public address (DNS), and to this computer at home.
3. Turn it on:

   ```
   sudo filament-kit modules enable remote
   ```

   That sets up nginx with a router on port 443 (`/etc/nginx/conf.d/filament-kit-router.conf`), a route from
   the public path (for example `/filament`) to the web service, and a temporary self-signed certificate, so
   nginx starts before the real one exists. Other routes can share the same name:
   `sudo /usr/local/sbin/mcp-route ls`, `add <name> <port>` and `rm <name>`.
4. Print the rules you need and set them up on your firewall and router:

   ```
   sudo filament-kit remote firewall
   ```

   It lists port 443 from Claude's address range and your home network, port 80 for certbot, and an optional
   nginx hardening file.
5. Get the certificate, with port 80 reaching this computer:

   ```
   sudo filament-kit remote issue
   ```

   nginx stops while certbot runs and starts again afterwards. From then on certbot renews the certificate by
   itself.

**Port 80.** certbot needs port 80 from the internet to this computer whenever it issues or renews (it answers
the check itself). If you only want port 80 open at a set time, open it on your router for a short window each
night and set `"acme_window"` to a time inside it, for example `"03:10 America/New_York"`: certbot's renewal
timer then runs only at that time. Outside the window port 80 can stay closed.

**HTTP/2.** The router speaks HTTP/1.1 only, so its nginx settings work on Ubuntu 24.04's nginx too. Claude and
phone browsers work with that.

Turning `remote` off removes only the kit's own router file, its certbot hook and its route. nginx, certbot,
the certificate and any other routes stay. While `/etc/nginx/mcp.d` still holds routes the kit did not add, the
router file stays too, because it is what serves them; the kit says so, and you remove it by hand once nothing
needs those routes.

## Order history

The `orders` module gives label reading your shop order history, so the AI can tell the brand, the seller and
the price of a spool when the label does not show them. You need a file with your orders, kept up to date by a
tool of yours, in this shape:

```
{"items": [{"order": "112-...", "date": "2026-10-01", "asin": "B0...", "title": "SUNLU PLA+ 1kg ...",
            "qty": 2, "unit_price": 19.99, "seller": "SUNLU"}]}
```

Put its path into `/etc/filament-kit/config.json` and turn the module on (it needs `ai_intake`):

```
"orders": {"file": "/var/lib/filament-kit/filament_orders.json"}
```

```
sudo filament-kit modules enable orders
```

The kit's user must be able to read the file (for example owner `root`, group `filament-kit`, mode 640). If it
cannot be read, labels are still read, without the orders.

## Moving from filament-ops

If you ran the older filament-ops setup (filament MCP server, phone intake app, `regen.py` presets, the
`intake-station` service and the `fpsync` task), the kit takes over all of it. The steps, checks and rollback for
each computer are in [docs/migrate-from-filament-ops.md](migrate-from-filament-ops.md). In short:

1. On the old server, export a bundle with `tools/export_ops.sh` (it only reads).
2. Install the kit in server mode, then `sudo filament-kit migrate-ops <bundle>`: it shows what it would do and
   changes nothing. `sudo filament-kit migrate-ops <bundle> --apply` then moves your Spoolman data, lines,
   calibrated preset values, the connector's sign-ins, the passphrase and your settings. Running it again changes
   nothing.
3. Turn on `web`, `orders` and `remote`; the connector and phone app keep their addresses and sign-ins.
4. Then the station computer and the Windows PC, as the guide says.

## Troubleshooting

- Run `sudo filament-kit status` on the Ubuntu computer. No line should start with `FAIL`; a failing line
  shows a `fix:` line.
- Presets don't appear in Bambu Studio: close Bambu Studio (the sync waits while it is open), then wait up to
  10 minutes. On the PC, run `filament-kit-sync status` to see the server, the Bambu Studio folder in use and
  the last run.
- The sync log is `%LOCALAPPDATA%\filament-kit-sync\sync.log`. Backups of your Bambu Studio filament folder,
  made before each install (the 5 newest are kept), are in `%LOCALAPPDATA%\filament-kit-sync\backups`.
- "Other PC" errors: another PC already syncs with this server. Remove it with `sudo filament-kit unpair <id>`.
- `sudo filament-kit profiles build` says the PC sync hasn't run yet (this is a message, not an error): do [Pair your PC](#pair-your-pc).

## Update

`sudo filament-kit update` downloads the newest release, checks its signature and hash as get.sh does, stops the
kit, installs it (no questions) and starts it again. It keeps your spools, settings, key and paired phones, and the
version it replaced: `sudo filament-kit update --rollback` goes back to that one. `sudo filament-kit update --check`
only says whether there is a newer release. It does nothing while a printer is mapping slots or loading a spool.

Automatic updates: `sudo filament-kit modules enable updates` (off by default) checks once a day and installs a
new release on its own; it never reinstalls a version you rolled back from. For a weekly check, set
`"updates": {"schedule": "weekly"}` in `/etc/filament-kit/config.json`. For a private repository, put a GitHub
token in a file only root can read and set `"updates": {"token_file": "/etc/filament-kit/github_token"}`.

By hand: download the newer `filament-kit-<version>.tar.gz`, unpack it as in step 2 above and run
`sudo ./install.sh` again.

## Uninstall

From the unpacked folder:

```
sudo ./uninstall.sh
```

This removes the programs (Spoolman and the intake station too, with the station's user and udev rule) but
**keeps** your spools, settings and backups, so a later install picks up where you left off, in the same mode.
The station's computer changes (brltty, ModemManager, sleep, audio) stay; see
[What the installer changes on the computer](#what-the-installer-changes-on-the-computer) to undo them. With
[Remote access](#remote-access) on, it also removes the kit's router file, its route and its certbot hook; nginx,
certbot, the certificate and any other routes stay (remove them with `apt` if nothing else uses them). The
router file stays while other routes in `/etc/nginx/mcp.d` need it (it says so). To delete everything, including
all spool data and backups:

```
sudo ./uninstall.sh --purge
```

It asks you to type `purge` to confirm. `--purge` also removes the certbot timer drop-in
`/etc/systemd/system/certbot.timer.d/acme-window.conf` (the `remote.acme_window` setting).
