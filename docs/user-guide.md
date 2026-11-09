# filament-kit user guide

The reference for everything the [README](../README.md) and the how-tos leave out: install modes, every command,
printers and slot mapping, presets in Bambu Studio and Orca Slicer, the intake station, the Claude connector and
phone web app, remote access and order history.

If you are setting up for the first time, start with the step-by-step how-tos instead:
[Install the server](install-server.md), [Install the Android app](install-android-app.md) and
[Use the web app on an iPhone](install-iphone-web-app.md). The README has the module list and where your data
lives.

## What you need

- A computer running **Ubuntu 24.04 or newer**, on your home network, that stays on.
- Optional: an **Anthropic API key** (starts with `sk-ant-`), only for AI label reading. Without one you add
  spools by hand; you can turn label reading on later (`sudo filament-kit config`, 4 for the key and 6 for the
  `ai_intake` module).
- An Android phone (Android 10 or newer) for the filament-kit app, or an iPhone (or any phone) for the phone
  web app.
- Optional: a Windows PC with Bambu Studio (and, if you like, Orca Slicer), for the presets.
- Optional: an **intake station**: a USB scale (DYMO) and a PN532 NFC reader on the same computer or on a second
  one (see [Intake station](#intake-station)).

## Install the server

Step by step, with every question and what you see: [Install the server](install-server.md). In short, on the
Ubuntu computer:

```
curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh
```

Options go after `get.sh` (or after `./install.sh` from an unpacked release): `--mode server|station|all-in-one`,
`--server <address>` for a station, `--modules a,b` with `--set key=value` for the settings a module needs
(for example `--modules server,web --set web.public_url=https://filament.example.com/filament`), and
`--version 0.3.0`. Without a terminal it asks nothing and installs the `server` mode unless told otherwise.

The installer takes a few minutes. You can run it again at any time; it never deletes your spools or settings.
Running it again later (an update) asks no questions and keeps the mode you have.

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

- `sudo filament-kit config`, then **6) Modules** (or `sudo filament-kit modules menu`). Move with Up/Down (or
  `k`/`j`), switch a module on or off with Space, press `a`, `s` or `t` for the all-in-one, server or station set,
  Enter to apply, `q` or Esc to cancel. A module's needs are switched on with it, and switching one off switches off
  what needs it. Choosing `station` asks for the server's address. Then **0) save and exit**. Without a usable
  terminal a numbered list runs instead: type numbers, Enter applies, `q` cancels.
- `sudo filament-kit modules set <mode>`, for example `sudo filament-kit modules set all-in-one`. For the station
  mode, add the server's address: `sudo filament-kit modules set station --server 192.0.2.10`.
  A mode never turns `web`, `remote` or `orders` on or off: the ones you turned on stay on, unless the new mode
  lacks a module they need (then they go off, and the command says so).
- One module at a time: `sudo filament-kit modules enable <name>` or `sudo filament-kit modules disable <name>`,
  for example `sudo filament-kit modules disable printers`. `sudo filament-kit modules list` shows the names and
  which are on.

Turning a module off **never deletes its data**. Spoolman's spools, settings and paired phones stay where they
are and come back when you turn the module on again. Only `sudo filament-kit uninstall --purge` deletes data. While a
module is off, the app gets the message that it is turned off for anything that needs it.

## Install the app and pair your phone

Step by step: [Install the Android app](install-android-app.md). In short: install `filament-kit.apk` from the
Releases page (or from your server at `https://<computer name>.local:8710/app.apk`), run `sudo filament-kit pair`
on the server, and scan the QR code it prints, or pick the server in the app, compare the fingerprint and type
the 6-digit code. The code expires after about 10 minutes and works once; `sudo filament-kit pair` makes a new
one. On Android 17 and newer the app needs **Local network** access.

The app updates itself: after `sudo filament-kit update` to a release with a newer app, the home screen offers
it. `sudo filament-kit unpair` lists the paired phones; `sudo filament-kit unpair <id>` removes one. Using the app (printers, adding spools by hand or from label photos): [Using the Android app](android-app.md).

No Android phone? The phone web app ([Use the web app on an iPhone](install-iphone-web-app.md)) does the same
tasks in any phone browser.

## Pair your PC

Do this once, on the PC where you use Bambu Studio (Windows below; Linux in [PC sync on Linux](#pc-sync-on-linux)). The PC sync tool sends your Bambu Studio filament
list to the server and installs the presets the server builds. One server works with **one** sync PC: the
first PC that syncs is the one. To move to another PC, remove the first one with `sudo filament-kit unpair`
(see [Everyday commands](#everyday-commands)); the next PC that syncs then starts fresh, like a first install.

1. On the PC, download `filament-kit-sync-setup-<version>.exe` from the same GitHub Releases page and run it.
   It does not need administrator rights. Windows may first show **Windows protected your PC** and say it
   prevented an unrecognized app from starting. That is because the program is not code-signed. If you downloaded
   it from the project's Releases page, click **More info**, then **Run anyway**. To check that the download is
   intact, run this in PowerShell in the folder where you saved it, and compare the result with the line for this
   file in the release's `SHA256SUMS`:

   ```
   Get-FileHash .\filament-kit-sync-setup-<version>.exe -Algorithm SHA256
   ```

   That check only shows the file arrived whole; it does not show who made it.
2. On the Ubuntu computer, run:

   ```
   sudo filament-kit pair --pc
   ```

   It prints a long link that starts with `fkit://pair?`, the certificate fingerprint and a 6-digit code.
3. Click **Finish** in the setup with **Pair this PC with the filament-kit server now** ticked. A console window
   opens. (Missed it? Start menu, **Pair filament-kit sync**.)
4. In that console, paste the link and press Enter. (No link? Type the server's name or address instead. The
   window shows the server's certificate fingerprint. Check that it matches the one on the Ubuntu computer and
   type `y` to confirm it. Then it asks for the 6-digit code.) From then on the PC syncs every 10 minutes. While
   Bambu Studio is open it waits and tries again later (see [While Bambu Studio is open](#while-bambu-studio-is-open-v040)).

The link and the code expire after about 10 minutes. If they do, run `sudo filament-kit pair --pc` again. Pairing again
keeps the pairing that works until the new one is proven: a refused link changes nothing.

### Stable and Beta Bambu Studio (v0.4.0)

From v0.4.0 the PC sync keeps **every** Bambu Studio folder on the PC current: on Windows both
`%APPDATA%\BambuStudio` (stable) and `%APPDATA%\BambuStudioBeta`; on Linux the native, Beta and both Flatpak
folders.

**Primary and other folders.** One folder is the **primary**: its presets are sent to the server, and the server's
builds are made from them. The other folders receive every build too.

- **The primary is sticky.** The first sync picks it: the folder you pinned in the sync's `config.json`, otherwise
  the one whose `BambuStudio.conf` is newest. After that it stays that folder, whichever Bambu Studio you open
  last. `filament-kit-sync status` shows the `Primary:` line.
- **Changing the primary.** Set `"variant"` (and `"user_id"`) in the sync's `config.json` to the other folder, or
  remove the primary's folder. The change is logged, and the new primary starts like a first sync: its presets are
  uploaded as they are, the server lists the ones that differ as updates, and nothing in it is replaced. The server
  must be on v0.4.0 too.
- **Install only into the primary** (the old behaviour): set `"secondaries": false` in `config.json`. The default is
  on, and the setting survives pairing again.

**Presets are never replaced unless you accept an update.** In every folder only **new** presets are added.

- In the **primary**, the updates you accept with `sudo filament-kit profiles apply-updates` are written.
- In the **other folders**, an accepted update is written only over a preset the kit itself put there and that you have
  not changed. Your own presets there are never replaced. Same-name presets that differ from the build are kept and
  listed: one line per folder in the log, and `Kept, differ:` lines in `filament-kit-sync status`.
- To take the build's copy in one of the other folders yourself, on the PC, with Bambu Studio closed:

  ```
  filament-kit-sync apply-updates --folder BambuStudioBeta-1234567890 --all
  ```

  Use `--name "<preset>"` (repeat it for more presets) instead of `--all` to pick presets, and `--dry-run` first to
  see what would be written. The folder is **named** `<variant>-<user id>`, as `status` shows it. The folder is backed up
  first, and only the listed presets are written.

**Backups.** Each folder has its own backups (the 5 newest are kept). The other folders' backups are in
`%LOCALAPPDATA%\filament-kit-sync\folders\<variant>-<user id>\backups`.

**A folder that fails.** If installing into one folder fails, the sync tries that folder again after 6 hours, or at
once when a new build arrives. `status` shows the error. The other folders are not held up.

`filament-kit-sync status` also shows, for each other folder, `Also installs: <folder>, user <id>: build <stamp>` (or
"nothing installed yet", or "last try failed: ...").

**Caution: two cloud copies.** Presets the sync writes into the second Bambu Studio are **local** presets of that app
(its own user id, no cloud id). The first time that Bambu Studio syncs with its account, it may create a second cloud
copy of a preset that has the same name, as it does for any preset you save by hand there.

### While Bambu Studio is open (v0.4.0)

The sync never changes presets while Bambu Studio or Orca Slicer is open. It waits and tries again at the next run.
Any running `bambu-studio.exe` blocks **all** folders, because the program's path does not say whether it is stable or
Beta. Close Bambu Studio to let new presets in.

You can see the wait: `filament-kit-sync status` shows `Waiting: for Bambu Studio to close since <date> (<n> runs
skipped)`. After 24 hours the log line becomes a warning saying how long it has waited. The server is told too (at
most once an hour): `sudo filament-kit status` and `sudo filament-kit profiles status` show "PC sync waiting for
Bambu Studio to close since <date>", and so does the preset status in the phone app and Claude's connector. It is
shown only for the PC that is paired as the sync PC, and clears at the first sync after Studio closes.

### Undo an update, unpair, or remove the PC sync

**Undo an installed update.** Before the sync writes presets, it copies your Bambu Studio filament folder to
`%LOCALAPPDATA%\filament-kit-sync\backups\<date and time>` (Orca Slicer's copy is in `backups-orca` under the same
name; the 5 newest of each are kept; a second Bambu Studio folder has its own under `folders\<name>\backups`). On
Linux they are under `~/.local/share/filament-kit-sync`. To go back, close Bambu Studio, copy the presets from the
backup folder over the ones in the slicer's filament folder, and start Bambu Studio again.

**Warning.** The sync runs exactly when Bambu Studio is closed, so it can run again between your closing Studio and
your copy. Copy the files back quickly, or stop the sync first (Task Scheduler on Windows, `systemctl --user stop
filament-kit-sync.timer` on Linux). The server still holds the newer build, so the restored presets show as
"differing" there; they are not reverted on the server.

**Unpair this PC.** `filament-kit-sync unpair` deletes the PC's token and settings and prints the PC's id. It does not
turn off the scheduled sync, which keeps running every 10 minutes and logging that the PC is not paired. The server still
counts this PC as the sync PC, so also run `sudo filament-kit unpair <id>` on the Ubuntu computer. Until you do, another
PC's sync is refused with "Other PC".

**Remove the program on Windows.** **Uninstall filament-kit sync** (Start menu, or Windows Settings, Apps) removes the
scheduled sync and the program's entry on your PATH. It keeps the sync's data (pairing token, settings, backups,
log) in `%LOCALAPPDATA%\filament-kit-sync`, so a later install is still paired. Presets already in the slicers stay. To
leave the server for good, run `filament-kit-sync unpair` first and then `sudo filament-kit unpair <id>`, as above.

### PC sync on Linux

The PC sync also runs on Linux (x86_64) with Bambu Studio and Orca Slicer, whether they are installed natively, as an
AppImage or from Flathub. It installs for your user only, without root. The server side is the same as above: one
server works with one sync PC.

**Install.** Download `filament-kit-sync-linux-x86_64-<version>.tar.gz` from the release (check it against the
release's `SHA256SUMS`), then:

```
tar -xzf filament-kit-sync-linux-x86_64-<version>.tar.gz
bash filament-kit-sync-linux-x86_64-<version>/install.sh
```

This puts the program in `~/.local/opt/filament-kit-sync`, links `~/.local/bin/filament-kit-sync`, and turns on a
systemd user timer (`filament-kit-sync.timer`) that runs the sync a couple of minutes after you log in and every 10
minutes after that. If `~/.local/bin` is not on your PATH yet, log out and in again. Run the same `install.sh` again
to update.

**Pair.** On the server run `sudo filament-kit pair --pc`. On the PC run `filament-kit-sync pair` and paste the link
(or type the server address and the 6-digit code), as on Windows.

**Status.** `filament-kit-sync status` shows the server, the Bambu Studio and Orca Slicer folders it found, the last run
(what stopped it, if it failed) and the installed build. `systemctl --user list-timers filament-kit-sync.timer` shows the next run. The log is
`~/.local/share/filament-kit-sync/sync.log`. `filament-kit-sync run` runs one sync now.

**While logged out.** The timer runs only while you are logged in. To run it while you are logged out too, run
`loginctl enable-linger` once (the install does not do this).

**Uninstall.** `~/.local/opt/filament-kit-sync/uninstall.sh` turns the timer off and removes the program. Your pairing
token and settings stay in `~/.local/share/filament-kit-sync`, so a reinstall is still paired. Add `--purge` to delete
them too, then run `sudo filament-kit unpair <id>` on the server. Presets already installed in the slicers stay.

**Flatpak and AppImage.**

- Flathub Bambu Studio (`com.bambulab.BambuStudio`) keeps its presets in
  `~/.var/app/com.bambulab.BambuStudio/config/BambuStudio`. Flathub Orca Slicer keeps them in
  `~/.var/app/<id>/config/OrcaSlicer`. The sync finds these by itself.
- Native installs and AppImages use `~/.config/BambuStudio` (or `BambuStudioBeta`) and `~/.config/OrcaSlicer`
  (or `$XDG_CONFIG_HOME` if you set it).
- From v0.4.0 the sync installs into all of them. One is the primary (see
  [Stable and Beta Bambu Studio](#stable-and-beta-bambu-studio-v040)). To choose it, set `"variant"` in
  `~/.local/share/filament-kit-sync/config.json` to `BambuStudio`, `BambuStudioBeta`, `Flatpak BambuStudio` or
  `Flatpak BambuStudioBeta`.
- The sync waits while Bambu Studio or Orca Slicer is open, including the Flatpak and AppImage versions. If it cannot
  list the running programs (it cannot read `/proc`), it counts a slicer as running and waits. The log then says
  Bambu Studio is open even if it is not, and closing Studio will not help. Check with `ps` that no slicer is running
  and that `/proc` is readable by your user.
- With the Orca AppImage, the Orca filament library is read from Orca's own copy under its data folder, because the
  AppImage's files can only be read while it runs.

This was written from the code and the slicers' documented folders, and has not been tried on a Linux machine with the
slicers running.

## The setup page (v0.4.0)

The kit server has a web page for setup at `https://<computer name>.local:8710/setup`, on the home network only.
It does what the Terminal's `config` menu, `pair` and the key commands do: the Anthropic key, printers and their
Access Codes, the web passphrase and library token, pairing a phone, the PC sync or the station, NFC reader
tokens, and switching modules on or off. How to find the code, what it asks for, the lock-out after wrong codes
and the full list: [Install the server, The setup page](install-server.md#the-setup-page-v040).

`sudo filament-kit setup-code` shows the page's address and its 8-digit setup code (at a Terminal);
`sudo filament-kit setup-code --new` makes a new one. Viewing needs no code; every change does.

## Everyday commands

Run these in a Terminal on the Ubuntu computer.

| Command | What it does |
|---|---|
| `sudo filament-kit status` | Checks that everything works. Anything failing shows a `fix:` line telling you what to do. |
| `sudo filament-kit pair` | Shows a new QR code to pair another phone. |
| `sudo filament-kit station pair` | On the intake station computer: pairs the station's button flow with the server. Paste the link from `sudo filament-kit pair --station`; without a terminal it says so and saves nothing (v0.4.1). |
| `sudo filament-kit station pairing-state` | Prints whether the station is paired, on one line: `paired <address>:<port>`, `unpaired`, or `unchecked` when you are not root (v0.4.1). |
| `sudo filament-kit pair --pc` | Shows the link and code to pair the PC sync tool (Windows or Linux). `--station` does the same for the intake station; `--text` prints the link instead of a QR code. The three are exclusive. |
| `sudo filament-kit setup-code` | Shows the setup page's address and setup code (v0.4.0). `--new` replaces the code and clears a lock-out. |
| `sudo filament-kit modules apply --no-pair` | Applies module changes without the pairing screen at the end (v0.4.0). |
| `sudo filament-kit uninstall` | Removes the kit (`--purge` also deletes your data). |
| `sudo filament-kit unpair` | Lists paired devices: phones and the PC sync (named `pc`). `sudo filament-kit unpair <id>` removes one. |
| `sudo filament-kit config` | Settings menu: display name, storage locations, Claude model and daily limit, API key, printers, modules. |
| `sudo filament-kit modules list` | Shows each module on or off and the mode. `modules set <mode>`, `modules enable <name>` and `modules disable <name>` change them (see [Change the mode later](#change-the-mode-later)); `modules apply` sets the computer up again from the saved settings. |
| `sudo filament-kit printer map <serial>` | Maps a printer's AMS slots (see [Map slots](#map-slots)), printing each step. |
| `sudo filament-kit profiles status` / `build` | Shows or rebuilds the Bambu Studio and Orca Slicer presets (see [Presets](#presets-in-bambu-studio)). |
| `sudo filament-kit profiles apply-updates --all` (or `--line <id>`; add `--dry-run` to only look) | Writes the updated presets you accept over the ones in the primary Bambu Studio folder (see [Stable and Beta Bambu Studio](#stable-and-beta-bambu-studio-v040)). |
| `sudo filament-kit profiles lines` / `set-parent <line_id> <parent>` | Lists the filament lines; sets a line's Bambu Studio parent (`--orca`: its Orca Slicer parent). |
| `sudo filament-kit profiles restore-deleted` | Brings back, at the next build, the generated presets you deleted in Bambu Studio. |
| `sudo filament-kit library status` / `update` / `rollback` | The spec library (see [Spec library updates](#spec-library-updates)). |
| `sudo filament-kit printer unpin <serial>` | Forgets a printer's pinned certificate; the next connection trusts the one it presents. |
| `sudo filament-kit web passphrase` | Sets the sign-in passphrase of the Claude connector (see [Claude connector and phone web app](#claude-connector-and-phone-web-app)). |
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

Klipper printers (through Moonraker) are a separate, opt-in module that is never part of an install mode: switch it on with
`sudo filament-kit modules enable klipper`. See [Klipper printers](klipper.md) (v0.4.0). The rest of this section is about
Bambu Lab printers.

The server finds Bambu Lab printers by listening for the announcements they send on your home network. For
that to work:

- The Ubuntu computer must be on the **same network segment** as the printers: the same router or switch and
  the same Wi-Fi / LAN, not a separate guest network or VLAN. Announcements do not cross routers.
- If the computer runs a firewall (for example `ufw`), allow incoming **UDP ports 2021 and 1990** from your
  home network, for example `sudo ufw allow from 198.51.100.0/24 to any port 2021,1990 proto udp` (use your
  own network's range).
- A server inside **WSL**, a virtual machine with NAT networking, or a container without host networking does
  not receive the announcements (and phones can't reach it). In WSL, switch to mirrored networking
  (`networkingMode=mirrored` in `.wslconfig`; see [Running the server in WSL](install-server.md#running-the-server-in-wsl)).
  Otherwise add the printers by hand: `sudo filament-kit config` → **Printers** → **add printer**, and enter the
  name, IP address, serial number and Access Code shown on the printer's screen.

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

- It briefly changes the colour of each AMS slot that holds filament, and of each external holder, to a test colour,
  checks which slot showed it, and puts every slot back as it was. An AMS slot that the printer reports as empty is
  skipped.
- It then runs a short calibration job that has **no heating and no motion** (only comments and a wait), so
  the printer reports which slot it used for each filament. The job file is deleted afterwards.
- External holders (a spool holder outside the AMS, numbered as its own id) stay out of the calibration job and keep
  their own ids, and so do empty AMS slots. A printer with no AMS unit needs no job: its holders keep their own ids
  and it maps without one.
- A printer can end up mapped with no named numbering scheme. Slots that are empty today show as "no number yet"
  until a spool is loaded in them and the printer is mapped again.
- On a printer whose numbers fit no known scheme, mapping may run one short job per scheme, so it takes longer than
  a single job.
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

**Backups and restore (v0.4.0).** The web unit runs as its own user, `filament-kit-web`, with its state in
`/var/lib/filament-kit-web` (the Claude connector's sign-ins, its token, push keys). Backups include it and keep the
file permissions (`tar --acls --xattrs`). If you restore a backup by hand, extract it with `tar --acls --xattrs`
into a removed or empty folder, or run `sudo filament-kit modules apply` afterwards; otherwise the web unit loses
read access to the files it needs.

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
then installs them in every Bambu Studio folder on the PC ([Stable and Beta Bambu Studio](#stable-and-beta-bambu-studio-v040)); presets already there are never replaced unless you accept an update.

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
and set `library.url` to `https://api.github.com/repos/<owner>/<repo>/releases/assets/<id>`. While that release is private, `library update` shows an error and the daily check
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
  (it says things like "1042 grams. Hold yellow to save.") and a **USB webcam** that takes a picture of the spool when you press
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
- **The speaking voice.** The station speaks with the Piper voice `en_US-libritts_r-medium` (speaker 0), downloaded
  when the station is installed (60 to 80 MB, checked against a pinned hash). If the download fails or the file
  does not match, the install carries on with a warning and espeak-ng speaks. To use espeak-ng on purpose (no
  download), choose **7) Station voice** in `sudo filament-kit config`. The voice is licensed **CC BY 4.0**
  (LibriTTS-R; credit in [THIRD-PARTY.md](../THIRD-PARTY.md#speech-voice)). To use the public-domain
  `en_US-ljspeech-medium` voice instead, set `station.voice` to it in `/etc/filament-kit/config.json` and run
  `sudo filament-kit modules apply`.
- With the panel, Hold and Discard also speak (`"speech"`), and Hold takes a picture with the webcam
  (`"camera"`). `curl http://127.0.0.1:5003/state` then shows `"air"` (the BME280 reading) and `"photo"`, and the
  picture itself is at `/photo`. The station only answers GET requests, and only the addresses it allows.
- These settings are in `/etc/filament-kit/config.json` under `"station"`: `"nfc_device"` (`"auto"`, or a
  device such as `"tty:USB0:pn532"`), `"beep"` (`true` or `false`), `"beep_device"` (empty for automatic, or
  an ALSA device such as `"plughw:1,0"`), `"speech"` (`true` or `false`) and `"camera"` (`"auto"` for the first
  USB camera, a device such as `"/dev/video0"`, or `"off"`), `"panel_flash"` (`true` or `false`, see the
  next point) and `"panel_swap"` (`true` or `false`, see the point after that). After a change, run `sudo filament-kit modules apply`.
- **Panel firmware updates itself.** The station carries the panel's firmware. When it finds a panel running
  another version, it writes the bundled one to it over USB (once per version) and then uses it. If that does
  not work, the panel keeps running as it is. Set `"panel_flash": false` to never touch the panel's firmware.
  `curl http://127.0.0.1:5003/state` shows the panel's version as `"panel_version"`.
- **Buttons and lamps the other way round (v0.4.0).** If your panel's yellow and red buttons and lamps are wired the
  opposite way to the pin table in the panel guide (the button you press for yellow acts as red, and the lamps are
  swapped too), set `"panel_swap": true` under `"station"` in `/etc/filament-kit/config.json`, then run
  `sudo filament-kit modules apply`. The default is `false`. This needs the panel's firmware 9, which the station
  installs itself unless `"panel_flash"` is `false`; with an older firmware, yellow can't do a long press, so it
  can't save.

### Is it working?

- `sudo filament-kit status` shows the station's real pairing state (v0.4.1; before, it asked you to run it with
  `sudo` even when you had), and on the server it shows `station answering at ...`. `station reader not seen` means no
  tag has been read yet; `station scale not seen` means the scale has sent nothing yet (switch it on and put
  something on it).
- On the station computer: `curl http://127.0.0.1:5003/state` shows the last tag and weight.
  `sudo journalctl -u filament-kit-station -n 30` shows what the station is doing; `NFC reader ...; retrying in
  5 s` means the reader is not plugged in or not found.
- The station answers only its own computer and the server's address. Anything else gets no answer.
- The button flow talks to the server with its own pairing (v0.3.0 and newer). On the kit server run
  `sudo filament-kit pair --station`, then within 10 minutes run `sudo filament-kit station pair` on the station
  computer and paste the link; it checks the link with the server and says "expired" if you were late. On an
  all-in-one both run on the same machine. The station's pairing can reach only the station part of the server.
  `sudo filament-kit pair` on a station-only computer says that pairing runs on the kit server.
- After the panel says "Saved #N / tag not linked", holding yellow again links the tag to that spool instead of
  saving a duplicate.
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

The connector needs a passphrase; the phone web app has no sign-in: it only answers your home network. Adding
spools does a dry run first in both, as in the Android app.

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

3. Set the passphrase (at least 12 characters; you type it twice and each character shows as a `*`):

   ```
   sudo filament-kit web passphrase
   ```

4. Turn the module on and check it:

   ```
   sudo filament-kit modules enable web
   sudo filament-kit web status
   ```

   `web status` shows the public address, the connector and phone app addresses, whether the passphrase is set,
   whether the service answers, and how many connectors are signed in. No line should start with
   `FAIL`. (At a terminal, `modules enable web` asks for `web.public_url` if it is not set; without a terminal it stops
   with an error. The Modules checklist in `sudo filament-kit config` asks for it too, so steps 2 and 4 can be done
   there in one go.)

### Add the connector in Claude

In claude.ai, add a custom connector with the address `<public address>/mcp`. Claude then opens a sign-in page:
type the passphrase there. Claude stays signed in after that; changing the passphrase later does not sign it out.

### Use the phone web app

Open `<public address>/intake` on the phone while it is on the home network and add the page to the home screen
if you like (step by step, including a home-only setup without a public name:
[Use the web app on an iPhone](install-iphone-web-app.md)). There is no sign-in: anyone on your home network can
use it (as with the Android app's pairing, the home network is the gate).

### What only works at home

The sign-in pages (`/authorize`, `/login`) and the whole phone web app answer only addresses from your home
network. Elsewhere they say that they only work on the home network. Claude's servers reach the connector itself
(`/mcp` and the token exchange) from the internet, so sign Claude in from home once. The home network is the
`192.168.0.0/16` and `10.0.0.0/8` by default (not `172.16.0.0/12`, where Docker's bridges live); set your own
in `"web": {"lan": ["198.51.100.0/24"]}` (each entry a network; `modules apply` refuses a bad one). Five wrong passphrases
lock the connector's sign-in for 10 minutes.

### The home network ranges (web.lan)

The ranges above are IPv4. A phone or computer that reaches the web address over IPv6 is refused with "This device
reached the server over IPv6" until you add your home network's IPv6 prefix. (The setup page is IPv4 only.) To do it:

1. On the server, find your prefix: `ip -6 addr show scope global`. A line such as
   `inet6 2001:db8:1234:5678::abcd/64` has the prefix `2001:db8:1234:5678::/64`: the first four groups of the address,
   then `::/64`. (`2001:db8` is the range reserved for examples; yours comes from your provider and can change.)
2. Edit `/etc/filament-kit/config.json` (for example `sudo nano /etc/filament-kit/config.json`) and set the list. Your list
   replaces the default, so keep the IPv4 ranges you want in it:

   ```
   "web": {"lan": ["192.168.0.0/16", "10.0.0.0/8", "2001:db8:1234:5678::/64"]}
   ```

3. Apply it: `sudo filament-kit modules apply`. It refuses an entry that is not a network.

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

The module needs `ai_intake`, so turn that on first. Then turn `orders` on; at a terminal it asks for the path to
the file (it is saved as `orders.file` in `/etc/filament-kit/config.json`):

```
sudo filament-kit modules enable ai_intake
sudo filament-kit modules enable orders
```

The kit's user must be able to read the file (for example owner `root`, group `filament-kit`, mode 640). If it
cannot be read, labels are still read, without the orders. From v0.4.0 only the web service itself can read the
order list through the server: phones, the PC sync and the station are refused.

## Moving from filament-ops

If you ran the older filament-ops setup (filament MCP server, phone intake app, `regen.py` presets, the
`intake-station` service and the `fpsync` task), the kit takes over all of it. The steps, checks and rollback for
each computer are in [Moving from filament-ops](migrate-from-filament-ops.md). In short:

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
  the last run. If it shows `Waiting: for Bambu Studio to close`, that is why. Also check you are looking at the right
  Bambu Studio: stable and Beta each have their own folder, and the other folder only gets new presets and the updates
  described under [Stable and Beta Bambu Studio](#stable-and-beta-bambu-studio-v040).
- The sync log is `%LOCALAPPDATA%\filament-kit-sync\sync.log`. Backups of your Bambu Studio filament folder,
  made before each install (the 5 newest are kept), are in `%LOCALAPPDATA%\filament-kit-sync\backups`.
- "Other PC" errors: another PC already syncs with this server. Remove it with `sudo filament-kit unpair <id>`.
- `sudo filament-kit profiles build` says the PC sync hasn't run yet (this is a message, not an error): do [Pair your PC](#pair-your-pc).

## Update

`sudo filament-kit update` downloads the newest release, checks its signature and hash as get.sh does, stops the
kit, installs it (no questions) and starts it again. It keeps your spools, settings, key and paired phones, and the
version it replaced: `sudo filament-kit update --rollback` goes back to that one. `sudo filament-kit update --check`
only says whether there is a newer release. It does nothing while a printer is mapping slots or loading a spool.
If an update fails, the previous version is put back and the daily timer does not try the failed version again until
a newer release appears; `sudo filament-kit update` by hand tries it again.

Automatic updates: `sudo filament-kit modules enable updates` (off by default) checks once a day and installs a
new release on its own; it never reinstalls a version you rolled back from. For a weekly check, set
`"updates": {"schedule": "weekly"}` in `/etc/filament-kit/config.json`. For a private repository, put a GitHub
token in a file only root can read and set `"updates": {"token_file": "/etc/filament-kit/github_token"}`.

**Updating from v0.3.0 to v0.4.0 with a PC sync (in this order).**
1. Update the server: `sudo filament-kit update`.
2. Update the PC sync: run the new `filament-kit-sync-setup-<version>.exe` (Windows) or the new Linux `install.sh`.
3. Close Bambu Studio, so the sync can run.
4. On the server, see what the updates would change: `sudo filament-kit profiles apply-updates --all --dry-run`, then
   apply the ones you want: `sudo filament-kit profiles apply-updates --all`. These go to the primary Bambu Studio folder;
   for the other folders use `filament-kit-sync apply-updates --folder ...` on the PC (see
   [Stable and Beta Bambu Studio](#stable-and-beta-bambu-studio-v040)).

The server must be updated first: a PC sync that is newer than its server logs a warning.

**Existing users: the other Bambu Studio folder.** A record the kit made before v0.4.0 cannot prove that a preset in the
other folder is the kit's. So after the upgrade, that folder's accepted updates are listed as "differing" and are **not**
written on their own. To take them, with Bambu Studio closed, run on the PC (use the folder name `status` shows):

```
filament-kit-sync apply-updates --folder BambuStudioBeta-1234567890 --all
```

Use `--dry-run` first to see what would be written. New presets still arrive in that folder by themselves.

By hand: download the newer `filament-kit-<version>.tar.gz`, unpack it and run `sudo ./install.sh` again.

**Going back from v0.4.1 to v0.4.0.** `sudo filament-kit update --rollback` goes back to the release it replaced. The
Spoolman allow-list (`/etc/systemd/system/spoolman.service.d/kit.conf`) stays in place after the rollback, and v0.4.0
cannot change it: edit it by hand if a range needs adding, then restart Spoolman.

**Going back from v0.4.0 to v0.3.0.** `sudo filament-kit update --rollback` goes back to the release it replaced.

- **Klipper first.** v0.3.0 has no `klipper` module and stops at a config that names it. If it is on, run
  `sudo filament-kit modules disable klipper` before the rollback: the rollback refuses until you do. If it is off, the
  rollback takes the `"klipper"` entry out of `modules` in `/etc/filament-kit/config.json` for you. Your Klipper
  printers stay in `printers.xml` for when you upgrade again.
- **What comes back.** The web app's Claude connector sign-ins, push subscriptions and its pairing come back as they
  were when you upgraded. v0.4.0 copies them into its new folder (`/var/lib/filament-kit-web`) and leaves the originals
  in place. Anything you changed in them while on v0.4.0 stays behind in the new folder.
- **The daily Claude read count.** Going back within a day restarts the day's count of label reads once.
- **Printers.** v0.4.0 also keeps the old-format `printers.json` beside `printers.xml`, so Bambu printers survive the
  rollback.
- **What stays behind.** v0.3.0 works with these left in place, and has no setup page: the setup page's service files,
  the `filament-kit-web` user and its folder, and the setup code. To remove them, run as root:

  ```bash
  systemctl disable --now filament-kit-setup.socket
  rm -f /etc/systemd/system/filament-kit-setup.socket /etc/systemd/system/filament-kit-setup@.service \
        /etc/systemd/system/filament-kit-setup-apply.service /etc/tmpfiles.d/filament-kit-setup.conf
  rm -rf /run/filament-kit-setup && systemctl daemon-reload
  setfacl -R -x u:filament-kit-web /etc/filament-kit /var/lib/filament-kit
  find /var/lib/filament-kit -type d -exec setfacl -d -x u:filament-kit-web {} +
  rm -rf /var/lib/filament-kit-web && userdel filament-kit-web
  rm -f /etc/filament-kit/setup_code /etc/filament-kit/setup_code.plain /etc/filament-kit/setup_lockout.xml
  ```

  Remove the user's file permissions (the two `setfacl` lines) before the user itself. If `slot_service.token_file` in
  `config.json` names a token file, remove that user's permission on it the same way. If you upgrade to v0.4.0 again
  later, removing `/var/lib/filament-kit-web` first makes the upgrade copy the web app's current files again.

**Upgrading a station from v0.2.0 to v0.3.0:** the station's button flow now needs pairing once. On the kit server run
`sudo filament-kit pair --station`, then within 10 minutes run `sudo filament-kit station pair` on the station
computer (on an all-in-one, both on the same machine) and paste the link. `sudo filament-kit status` and the install
say so until it is done.

## Uninstall

```
sudo filament-kit uninstall
```

This runs the uninstaller of the release copy the kit kept. With no kept copy it says where to download the release
file, and you run `sudo ./uninstall.sh` from the unpacked folder.

This removes the programs (Spoolman and the intake station too, with the station's user and udev rule) but
**keeps** your spools, settings and backups, so a later install picks up where you left off, in the same mode.
The station's computer changes (brltty, ModemManager, sleep, audio) stay; see
[What the installer changes on the computer](#what-the-installer-changes-on-the-computer) to undo them. With
[Remote access](#remote-access) on, it also removes the kit's router file, its route and its certbot hook; nginx,
certbot, the certificate and any other routes stay (remove them with `apt` if nothing else uses them). The
router file stays while other routes in `/etc/nginx/mcp.d` need it (it says so). To delete everything, including
all spool data and backups:

```
sudo filament-kit uninstall --purge
```

It asks you to type `purge` to confirm. `--purge` also removes the certbot timer drop-in
`/etc/systemd/system/certbot.timer.d/acme-window.conf` (the `remote.acme_window` setting).
