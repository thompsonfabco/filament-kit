# filament-kit

Take photos of a filament spool's label with your phone; filament-kit reads the label and adds the spool to
your inventory (Spoolman). Runs on a small Ubuntu computer on your home network.

It also:

- connects to your Bambu Lab printer, so filament used in a print comes off the right spool;
- builds a filament preset for every filament line you own and installs them in Bambu Studio on your Windows PC
  (see [Presets in Bambu Studio](#presets-in-bambu-studio)).

## What you need

- A computer running **Ubuntu 24.04 or newer**, on your home network, that stays on.
- An **Anthropic API key** (starts with `sk-ant-`). Keep it handy; the installer asks for it once.
- An Android phone (Android 10 or newer) for the filament-kit app.
- Optional: a Windows PC with Bambu Studio, for the presets.
- Optional: an **intake station**: a USB scale (DYMO) and a PN532 NFC reader on the same computer or on a second
  one (see [Intake station](#intake-station)).

## Install the server

Do these steps on the Ubuntu computer, in a Terminal window.

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
   - **Default storage locations**: press Enter for yes. Type `n` if you want to name your own racks and
     boxes now (you can also change them later).
   - **Anthropic API key**: paste the key and press Enter. Nothing shows while you type or paste; that is on
     purpose.
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
| `server` (1, the default) | Spoolman, the server, AI label reading, printers, presets, library, backup | One computer runs the kit. This is the kit as it always was. |
| `station` (2) | Only the intake station (USB scale and NFC reader) | The station is a second computer and the server runs on another one. It asks for the **server's address**. |
| `all-in-one` (3) | Everything, station included | The scale and reader are plugged into the server computer. |
| `custom` (4) | The modules you pick one by one | You know which parts you want. |

A station-only computer needs no API key, certificate or Spoolman.

You can also give the mode on the command line, so the installer asks no mode question:

```
sudo ./install.sh --mode server
sudo ./install.sh --mode all-in-one
sudo ./install.sh --mode station --server 192.0.2.10
```

`--server` is the kit server's name or IP address, for example `spoolman.home.arpa` or `192.0.2.10`. Give one
address, not a range. The station answers only that address and the station computer itself.

Running `sudo ./install.sh` again later (an update) asks no questions and keeps the mode you have. An install
from before modules existed counts as the `server` mode and works exactly as before.

### All-in-one on one computer

Plug the USB scale and the NFC reader into the Ubuntu computer, then:

```
sudo ./install.sh --mode all-in-one
```

Answer the display name, storage and API key questions as in [Install the server](#install-the-server). Besides
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

## Building the Android app release (owner, Windows PC)

The app is signed with a key that lives only on your PC. Android only installs an update over an installed app
if it is signed with the **same** key, so losing the key means everyone has to uninstall and reinstall the app.

1. Once: `powershell -ExecutionPolicy Bypass -File tools\android_keystore.ps1`. It creates
   `%LOCALAPPDATA%\filament-kit\release.jks` and a random password stored (encrypted with Windows DPAPI) in
   `%LOCALAPPDATA%\filament-kit\keystore.pw.dpapi`. You never type or see the password. It refuses to overwrite an
   existing keystore. It uses `keytool` from `JAVA_HOME` if set, otherwise from `<local path>`.
2. Each release: pick the app's version code and run, in Git Bash,
   `FK_VERSION_CODE=<n> bash tools/make_release.sh`. It builds and signs the app with that versionCode and puts
   `app/filament-kit.apk` and `app/version.txt` (containing the same number) into the tarball.
   **Bump the version code for every app release**: use the previous release's number plus one (it must be a whole
   number above 0 and must never go down; without `FK_VERSION_CODE` it is `1`). Phones only offer the update when
   the server's `version.txt` is higher than the installed app's versionCode, and Android refuses to install a
   lower one. Without the keystore, no app is built and any old `app-release.apk` is deleted, so a tarball never
   carries a stale app.
3. **Back up both** `release.jks` **and** `keystore.pw.dpapi` together, somewhere safe and off this PC. A DPAPI
   file only decrypts on this Windows account on this PC, so also make a portable backup:
   `powershell -ExecutionPolicy Bypass -File tools\android_keystore.ps1 -Export D:\safe\filament-kit-keystore.bak`
   (you type a passphrase of at least 12 characters; remember it). On another PC restore it with
   `-Import <file>`. The `FK_BACKUP_PASSPHRASE` environment variable is for test automation only; never use it for
   a real backup.
4. `-Forget` deletes the keystore and the password file (it asks first).

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
| `sudo filament-kit profiles status` / `build` | Shows or rebuilds the Bambu Studio presets (see [Presets](#presets-in-bambu-studio)). |
| `sudo filament-kit profiles restore-deleted` | Brings back, at the next build, the generated presets you deleted in Bambu Studio. |
| `sudo filament-kit library status` / `update` / `rollback` | The spec library (see [Spec library updates](#spec-library-updates)). |
| `sudo filament-kit printer unpin <serial>` | Forgets a printer's pinned certificate; the next connection trusts the one it presents. |

Your spool inventory (Spoolman) is also in a web browser on any computer at home:
`http://<computer name>.local:7912`, where `<computer name>` is the Ubuntu computer's own name (type
`hostname` in a Terminal to see it). The installer prints this address at the end.

## Bambu Lab printers

The server finds Bambu Lab printers by listening for the announcements they send on your home network. For
that to work:

- The Ubuntu computer must be on the **same network segment** as the printers: the same router or switch and
  the same Wi-Fi / LAN, not a separate guest network or VLAN. Announcements do not cross routers.
- If the computer runs a firewall (for example `ufw`), allow incoming **UDP ports 2021 and 1990** from your
  home network, for example `sudo ufw allow from 192.168.1.0/24 to any port 2021,1990 proto udp` (use your
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

## Spec library updates

The library holds published filament specs (temperatures, speeds). A copy comes with the server, so it works
at once. The server checks for a newer copy every day.

- `sudo filament-kit library status`: shows the library version and the last check.
- `sudo filament-kit library update`: checks for a newer version now.
- `sudo filament-kit library rollback`: goes back to the version before the last update. The next daily check
  installs the newer version again. To keep the rolled-back version, turn the daily check off first: in
  `/etc/filament-kit/config.json` set `"library": {"schedule": "off"}` (or `"weekly"`; the default is
  `"daily"`), then roll back. Set it back to `"daily"` to get updates again.
- `sudo filament-kit library add <file>`: adds or replaces your own entry from a JSON file.

Updates only arrive once the library's GitHub repository is public or the server's library address points to a
public mirror. While the library repository can't be reached, the daily check logs a warning, and running
`sudo filament-kit library update` yourself shows an error. Neither is a failure; the bundled library keeps
working.

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
  build and flash it: [station/PANEL.md](station/PANEL.md).
- Optional: a speaker (USB or the computer's headphone socket) for the scan beep when there is no panel.

### What the installer changes on the computer

Turning the station on (install or **Modules**) also changes these, because each one stops a station from
working:

- **brltty is removed.** It takes CH340 USB adapters for braille displays and grabs the reader.
- **ModemManager is turned off.** It probes every new USB serial port and confuses the reader and the panel.
- **Sleep, suspend and hibernate are turned off** (masked). An idle Ubuntu desktop otherwise goes to sleep and
  the station stops answering.
- **Audio outputs are unmuted** at 80% and saved, so the scan beep can be heard.
- A **udev rule** (`/etc/udev/rules.d/99-filament-kit-station.rules`) lets the station read the DYMO scale
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
- These settings are in `/etc/filament-kit/config.json` under `"station"`: `"nfc_device"` (`"auto"`, or a
  device such as `"tty:USB0:pn532"`), `"beep"` (`true` or `false`) and `"beep_device"` (empty for automatic, or
  an ALSA device such as `"plughw:1,0"`). After a change, run `sudo filament-kit modules apply`.

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

Download the newer `filament-kit-<version>.tar.gz`, unpack it as in step 2 above and run `sudo ./install.sh`
again. It keeps your spools, settings, key and paired phones and asks no questions.

## Uninstall

From the unpacked folder:

```
sudo ./uninstall.sh
```

This removes the programs (Spoolman and the intake station too, with the station's user and udev rule) but
**keeps** your spools, settings and backups, so a later install picks up where you left off, in the same mode.
The station's computer changes (brltty, ModemManager, sleep, audio) stay; see
[Intake station](#what-the-installer-changes-on-the-computer) to undo them. To delete everything, including all spool data and backups:

```
sudo ./uninstall.sh --purge
```

It asks you to type `purge` to confirm.
