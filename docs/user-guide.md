# filament-kit user guide

The reference for everything the [README](../README.md) and the how-tos leave out: Setups, every command,
printers and slot mapping, Slicer presets in Bambu Studio and Orca Slicer, the Weigh Station, the Claude connector and
the web app, remote access and order history.

If you are setting up for the first time, start with the step-by-step how-tos instead:
[Install the Hub](install-server.md), [Install the app](install-android-app.md) and
[Use the web app on an iPhone](install-iphone-web-app.md). The README has the Feature list and where your data
lives.

## What you need

- A computer running **Ubuntu 24.04 or newer**, on your home network, that stays on.
- Optional: an **Anthropic API key** (starts with `sk-ant-`), only for the Label Reader's Cloud engine. Without one you add
  spools by hand; you can turn the Label Reader on later (`sudo filament-kit config` for the key, then
  `sudo filament-kit features on label-reader`).
- An Android phone (Android 10 or newer) for the filament-kit app, or an iPhone (or any phone) for the
  web app.
- Optional: a Windows PC with Bambu Studio (and, if you like, Orca Slicer), for Slicer presets.
- Optional: a **Weigh Station**: a DYMO M10 USB scale and a PN532 tag reader on the same computer or on a second
  one (see [Weigh Station](#intake-station)).

<a id="install-the-server"></a>
## Install the Hub

Step by step, with every question and what you see: [Install the Hub](install-server.md). In short, on the
Ubuntu computer:

```
curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh
```

Options go after `get.sh` (or after `./install.sh` from an unpacked release): `--mode hub|weigh-station|hub-with-weigh-station`,
`--hub <address>` for a Weigh Station, `--modules a,b` with `--set key=value` for the settings a Feature needs
(for example `--modules server,web --set web.public_url=https://filament.example.com/filament`), and
`--version 0.3.0`. Without a terminal it asks nothing and installs the Hub Setup unless told otherwise.

The installer takes a few minutes. You can run it again at any time; it never deletes your spools or settings.
Running it again later (an update) asks no questions and keeps the Setup you have.

<a id="install-modes"></a>
## Setups

filament-kit is made of parts called **Features** (Spoolman, the Hub service, the Label Reader, printers, Slicer presets, the Filament
Catalog, the nightly backup and the Weigh Station). A **Setup** is a ready-made set of them. The installer asks
for the Setup on the first install (it calls the question "Install mode"):

| Setup | What it installs | Use it when |
|---|---|---|
| **Hub** (1, the default) | Spoolman, the Hub service, printers, Slicer presets, backup (the Label Reader and the Filament Catalog are switched on when you want them) | One computer runs filament-kit. |
| **Weigh Station only** (2) | Only the Weigh Station (USB scale and tag reader) | The Weigh Station is a second computer and the Hub runs on another one. It asks for the **Hub's address**. |
| **Hub with Weigh Station** (3) | Everything, Weigh Station included | The scale and reader are plugged into the Hub computer. |
| **custom** (4) | One checklist of Features: type a number to switch one, and what it needs goes on too (what depends on it is listed when you switch it off). The same checklist is in `sudo filament-kit features menu` | You know which parts you want. |

The Label Reader's Cloud engine (the `ai_intake` Feature) is in no Setup: the installer asks about it on the first install, and
`sudo filament-kit features on label-reader` turns it on later. Without it, spools are added by hand in the
app and the web app, unless you use the [Label Reader on this Hub](#local-label-reading) instead. A Weigh Station only computer needs no API key, certificate or Spoolman.

You can also give the Setup on the command line, so the installer asks no Setup question. `--mode` takes
`hub`, `weigh-station` or `hub-with-weigh-station`; for `custom`, answer 4 at the question, give `--modules spoolman,server,printers` (what they need is added; for web, orders or a Weigh Station add the setting they need with `--set web.public_url=https://...`, `--set orders.file=PATH` or `--set station.allow=ADDRESS`), or switch Features afterwards with
`sudo filament-kit features on <feature>` and `sudo filament-kit features off <feature>`:

```
sudo ./install.sh --mode hub
sudo ./install.sh --mode hub-with-weigh-station
sudo ./install.sh --mode weigh-station --hub 192.0.2.10
```

`--hub` is the Hub's name or IP address, for example `kit-server.local` or `192.0.2.10`. Give one
address, not a range. The Weigh Station answers only that address and the Weigh Station computer itself.

Running `sudo ./install.sh` again later (an update) asks no questions and keeps the Setup you have. An install
from before Features existed counts as the Hub Setup and works exactly as before, the Label Reader included.

### The Hub with Weigh Station on one computer

Plug the USB scale and the tag reader into the Ubuntu computer, then:

```
sudo ./install.sh --mode hub-with-weigh-station
```

Answer the label reading, display name, storage and API key questions as in
[Install the Hub](#install-the-server). Besides
the usual Hub, this sets up:

- the Weigh Station service `filament-kit-station`, which reads the scale and the reader and answers on port 5003,
  for this computer only (`http://127.0.0.1:5003/state`);
- the Hub's link to it, so `sudo filament-kit status` shows a line `station answering at
  http://127.0.0.1:5003`, and the app can read the scale and the last tag;
- the computer changes the Weigh Station needs (see [Weigh Station](#intake-station)): brltty removed, ModemManager
  off, sleep and suspend off, audio unmuted, and a rule that lets the Weigh Station read the DYMO scale.

Until a tag has been read and the scale has been switched on, `status` shows `station reader not seen` and
`station scale not seen`. Those lines are information, not failures.

<a id="change-the-mode-later"></a>
### Change the Setup later

Use either way. Both install what the new Setup needs, start it, and stop what it no longer uses:

- `sudo filament-kit features menu`. Move with Up/Down (or
  `k`/`j`), switch a Feature on or off with Space, press `h`, `w` or `b` for the Hub, Weigh Station only or Hub with Weigh Station Setup,
  `s` to apply (Enter only switches a row), `q` or Esc to cancel. A Feature's needs are switched on with it, and switching one off switches off
  what needs it. Choosing Weigh Station only asks for the Hub's address. Without a usable
  terminal a numbered list runs instead: type numbers and Enter to switch rows, `s` applies, `q` cancels.
- `sudo filament-kit features setup <setup>`, for example `sudo filament-kit features setup hub-with-weigh-station`. For the Weigh Station only
  Setup, add the Hub's address: `sudo filament-kit features setup weigh-station --hub 192.0.2.10`.
  A Setup never turns `web`, `remote` or `orders` on or off: the ones you turned on stay on, unless the new Setup
  lacks a Feature they need (then they go off, and the command says so).
- One Feature at a time: `sudo filament-kit features on <feature>` or `sudo filament-kit features off <feature>`,
  for example `sudo filament-kit features off printers`. `sudo filament-kit features list` shows the names and
  which are on. At a terminal, turning one off offers to turn off what needs it too, and turning one on offers to turn
  on what it needs and asks for any setting those need; it says what else changed. A script gets a refusal that names them.

Turning a Feature off **never deletes its data**. Spoolman's spools, settings and paired phones stay where they
are and come back when you turn the Feature on again. Only `sudo filament-kit uninstall --purge` deletes data. While a
Feature is off, the app gets the message that it is turned off for anything that needs it.

The older names still work wherever a Setup name is asked for: `server` for `hub`, `station` for `weigh-station` and `all-in-one` for `hub-with-weigh-station` (`install.sh --mode`, `filament-kit features`). `filament-kit features setup` and `features on` take `--hub` beside `--server`. Nothing stored changes.

## Install the app and pair your phone

Step by step: [Install the app](install-android-app.md). In short: install `filament-kit.apk` from the
Releases page (or from your Hub at `https://<computer name>.local:8710/app.apk`), run `sudo filament-kit pair`
on the Hub, and scan the QR code it prints, or pick the Hub in the app, compare the fingerprint, tap
**It matches** and type the 6-digit code. The code expires after about 10 minutes and works once;
`sudo filament-kit pair` makes a new one. The switch **Check the fingerprint when pairing by address** in the app's **Settings** is on by default. On Android 17 and newer the app needs **Local network** access.

The app updates itself: after `sudo filament-kit update` to a release with a newer app, the home screen offers
it. `sudo filament-kit devices` lists the paired phones; `sudo filament-kit devices forget <device>` removes one. Using the app (printers, adding spools by hand or from label photos): [Using the app](android-app.md).

No Android phone? The web app ([Use the web app on an iPhone](install-iphone-web-app.md)) does the same
tasks in any phone browser.

## Pair your PC

Do this once, on the PC where you use Bambu Studio (Windows below; Linux in [Slicer Sync on Linux](#pc-sync-on-linux)). Slicer Sync sends your Bambu Studio filament
list to the Hub and installs the Slicer presets the Hub builds. One Hub works with **one** Slicer Sync PC: the
first PC that syncs is the one. To move to another PC, remove the first one with `sudo filament-kit devices forget <device>`
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
      sudo filament-kit pair --slicer-sync
   ```

   It prints a long link that starts with `fkit://pair?`, the certificate fingerprint and a 6-digit code.
3. Click **Finish** in the setup with **Pair this PC with the filament-kit server now** ticked. A console window
   opens. (Missed it? Start menu, **Pair filament-kit sync**.)
4. In that console, paste the link and press Enter. (No link? Type the Hub's name or address instead. The
   window shows the Hub's certificate fingerprint. Check that it matches the one on the Ubuntu computer and
   type `y` to confirm it. Then it asks for the 6-digit code.) From then on the PC syncs every 10 minutes. While
   Bambu Studio is open it waits and tries again later (see [While Bambu Studio is open](#while-bambu-studio-is-open-v040)).

The link and the code expire after about 10 minutes. If they do, run `sudo filament-kit pair --slicer-sync` again. Pairing again
keeps the pairing that works until the new one is proven: a refused link changes nothing.

### Stable and Beta Bambu Studio (v0.4.0)

From v0.4.0 Slicer Sync keeps **every** Bambu Studio folder on the PC current: on Windows both
`%APPDATA%\BambuStudio` (stable) and `%APPDATA%\BambuStudioBeta`; on Linux the native, Beta and both Flatpak
folders.

**Primary and other folders.** One folder is the **primary**: its Slicer presets are sent to the Hub, and the Hub's
builds are made from them. The other folders receive every build too.

- **The primary is sticky.** The first sync picks it: the folder you pinned in the sync's `config.json`, otherwise
  the one whose `BambuStudio.conf` is newest. After that it stays that folder, whichever Bambu Studio you open
  last. `filament-kit-sync status` shows the `Primary:` line.
- **Changing the primary.** Set `"variant"` (and `"user_id"`) in the sync's `config.json` to the other folder, or
  remove the primary's folder. The change is logged, and the new primary starts like a first sync: its Slicer presets are
  uploaded as they are, the Hub lists the ones that differ as updates, and nothing in it is replaced. The Hub
  must be on v0.4.0 too.
- **Install only into the primary** (the old behaviour): set `"secondaries": false` in `config.json`. The default is
  on, and the setting survives pairing again.

**Slicer presets are never replaced unless you accept an update.** In every folder only **new** Slicer presets are added.

- In the **primary**, the updates you accept with `sudo filament-kit presets accept-updates` are written.
- In the **other folders**, an accepted update is written only over a preset filament-kit itself put there and that you have
  not changed. Your own Slicer presets there are never replaced. Same-name Slicer presets that differ from the build are kept and
  listed: one line per folder in the log, and `Kept, differ:` lines in `filament-kit-sync status`.
- To take the build's copy in one of the other folders yourself, on the PC, with Bambu Studio closed:

  ```
  filament-kit-sync apply-updates --folder BambuStudioBeta-1234567890 --all
  ```

  Use `--name "<preset>"` (repeat it for more Slicer presets) instead of `--all` to pick Slicer presets, and `--dry-run` first to
  see what would be written. The folder is **named** `<variant>-<user id>`, as `status` shows it. The folder is backed up
  first, and only the listed Slicer presets are written.

**Backups.** Each folder has its own backups (the 5 newest are kept). The other folders' backups are in
`%LOCALAPPDATA%\filament-kit-sync\folders\<variant>-<user id>\backups`.

**A folder that fails.** If installing into one folder fails, Slicer Sync tries that folder again after 6 hours, or at
once when a new build arrives. `status` shows the error. The other folders are not held up.

`filament-kit-sync status` also shows, for each other folder, `Also installs: <folder>, user <id>: build <stamp>` (or
"nothing installed yet", or "last try failed: ...").

**Caution: two cloud copies.** The Slicer presets that Slicer Sync writes into the second Bambu Studio are **local** Slicer presets of that app
(its own user id, no cloud id). The first time that Bambu Studio syncs with its account, it may create a second cloud
copy of a preset that has the same name, as it does for any preset you save by hand there.

### While Bambu Studio is open (v0.4.0)

Slicer Sync never changes Slicer presets while Bambu Studio or Orca Slicer is open. It waits and tries again at the next run.
Any running `bambu-studio.exe` blocks **all** folders, because the program's path does not say whether it is stable or
Beta. Close Bambu Studio to let new Slicer presets in.

You can see the wait: `filament-kit-sync status` shows `Waiting: for Bambu Studio to close since <date> (<n> runs
skipped)`. After 24 hours the log line becomes a warning saying how long it has waited. The Hub is told too (at
most once an hour): `sudo filament-kit status` and `sudo filament-kit presets status` show "Slicer Sync waiting for
Bambu Studio to close since <date>", and so does the preset status in the app and Claude's connector. It is
shown only for the PC that is paired as the Slicer Sync PC, and clears at the first sync after Studio closes.

### Undo an update, unpair, or remove Slicer Sync

**Undo an installed update.** Before Slicer Sync writes Slicer presets, it copies your Bambu Studio filament folder to
`%LOCALAPPDATA%\filament-kit-sync\backups\<date and time>` (Orca Slicer's copy is in `backups-orca` under the same
name; the 5 newest of each are kept; a second Bambu Studio folder has its own under `folders\<name>\backups`). On
Linux they are under `~/.local/share/filament-kit-sync`. To go back, close Bambu Studio, copy the Slicer presets from the
backup folder over the ones in the slicer's filament folder, and start Bambu Studio again.

**Warning.** Slicer Sync runs exactly when Bambu Studio is closed, so it can run again between your closing Studio and
your copy. Copy the files back quickly, or stop the sync first (Task Scheduler on Windows, `systemctl --user stop
filament-kit-sync.timer` on Linux). The Hub still holds the newer build, so the restored Slicer presets show as
"differing" there; they are not reverted on the Hub.

**Unpair this PC.** `filament-kit-sync unpair` deletes the PC's token and settings and prints the PC's id. It does not
turn off the scheduled sync, which keeps running every 10 minutes and logging that the PC is not paired. The Hub still
counts this PC as the Slicer Sync PC, so also run `sudo filament-kit devices forget <device>` on the Ubuntu computer. Until you do, another
PC's sync is refused with "Other PC".

**Remove the program on Windows.** **Uninstall filament-kit sync** (Start menu, or Windows Settings, Apps) removes the
scheduled sync and the program's entry on your PATH. It keeps the sync's data (pairing token, settings, backups,
log) in `%LOCALAPPDATA%\filament-kit-sync`, so a later install is still paired. Slicer presets already in the slicers stay. To
leave the Hub for good, run `filament-kit-sync unpair` first and then `sudo filament-kit devices forget <device>`, as above.

<a id="pc-sync-on-linux"></a>
### Slicer Sync on Linux

Slicer Sync also runs on Linux (x86_64) with Bambu Studio and Orca Slicer, whether they are installed natively, as an
AppImage or from Flathub. It installs for your user only, without root. The Hub side is the same as above: one
Hub works with one Slicer Sync PC.

**Install.** Download `filament-kit-sync-linux-x86_64-<version>.tar.gz` from the release (check it against the
release's `SHA256SUMS`), then:

```
tar -xzf filament-kit-sync-linux-x86_64-<version>.tar.gz
bash filament-kit-sync-linux-x86_64-<version>/install.sh
```

This puts the program in `~/.local/opt/filament-kit-sync`, links `~/.local/bin/filament-kit-sync`, and turns on a
systemd user timer (`filament-kit-sync.timer`) that runs Slicer Sync a couple of minutes after you log in and every 10
minutes after that. If `~/.local/bin` is not on your PATH yet, log out and in again. Run the same `install.sh` again
to update.

**Pair.** On the Hub run `sudo filament-kit pair --slicer-sync`. On the PC run `filament-kit-sync pair` and paste the link
(or type the Hub address and the 6-digit code), as on Windows.

**Status.** `filament-kit-sync status` shows the Hub, the Bambu Studio and Orca Slicer folders it found, the last run
(what stopped it, if it failed) and the installed build. `systemctl --user list-timers filament-kit-sync.timer` shows the next run. The log is
`~/.local/share/filament-kit-sync/sync.log`. `filament-kit-sync run` runs one sync now.

**While logged out.** The timer runs only while you are logged in. To run it while you are logged out too, run
`loginctl enable-linger` once (the install does not do this).

**Uninstall.** `~/.local/opt/filament-kit-sync/uninstall.sh` turns the timer off and removes the program. Your pairing
token and settings stay in `~/.local/share/filament-kit-sync`, so a reinstall is still paired. Add `--purge` to delete
them too, then run `sudo filament-kit devices forget <device>` on the Hub. Slicer presets already installed in the slicers stay.

**Flatpak and AppImage.**

- Flathub Bambu Studio (`com.bambulab.BambuStudio`) keeps its Slicer presets in
  `~/.var/app/com.bambulab.BambuStudio/config/BambuStudio`. Flathub Orca Slicer keeps them in
  `~/.var/app/<id>/config/OrcaSlicer`. The sync finds these by itself.
- Native installs and AppImages use `~/.config/BambuStudio` (or `BambuStudioBeta`) and `~/.config/OrcaSlicer`
  (or `$XDG_CONFIG_HOME` if you set it).
- From v0.4.0 Slicer Sync installs into all of them. One is the primary (see
  [Stable and Beta Bambu Studio](#stable-and-beta-bambu-studio-v040)). To choose it, set `"variant"` in
  `~/.local/share/filament-kit-sync/config.json` to `BambuStudio`, `BambuStudioBeta`, `Flatpak BambuStudio` or
  `Flatpak BambuStudioBeta`.
- Slicer Sync waits while Bambu Studio or Orca Slicer is open, including the Flatpak and AppImage versions. If it cannot
  list the running programs (it cannot read `/proc`), it counts a slicer as running and waits. The log then says
  Bambu Studio is open even if it is not, and closing Studio will not help. Check with `ps` that no slicer is running
  and that `/proc` is readable by your user.
- With the Orca AppImage, Orca's own list of filaments is read from its own copy under its data folder, because the
  AppImage's files can only be read while it runs.

This has not been tried on a Linux machine with the slicers running.

<a id="the-setup-page-v040"></a>
## The Hub page (v0.4.0)

The Hub has a web page for setup at `https://<computer name>.local:8710/setup`, on the home network only.
It does what the Terminal's `config` menu, `pair` and the key commands do: the Anthropic key, printers and their
Access Codes, the web passphrase and Catalog token, pairing a phone, Slicer Sync or a Weigh Station, Tag Reader
tokens, and switching Features on or off. How to find the code, what it asks for, the lock-out after wrong codes
and the full list: [Install the Hub, The Hub page](install-server.md#the-setup-page-v040).

`sudo filament-kit setup-code` shows the page's address and its 8-digit setup code (at a Terminal);
`sudo filament-kit setup-code --new` makes a new one. Viewing needs no code; every change does, unless the computer
is trusted: after the code works once, the page offers **Trust this computer** (v0.4.3), and that browser then needs
no code for 90 days after its last use (a question like "Roll back?" is still asked). **Devices** lists the trusted
computers, with Rename, Revoke and Revoke all, and a switch that turns the feature off and forgets them all. A new
setup code keeps trusted computers trusted; `sudo filament-kit setup-code --revoke-trusted` forgets them, alone or
with `--new`.

**Light, dark or system.** The page header has a switch with three choices: Light, Dark and System (the default, which follows your device). The choice is kept in that browser only.

**Moving around.** The sections are a list down the side on a wide screen. On a phone the page has a bar at the bottom with Overview, Printers, Recent and Settings, and a **More** button that opens the other sections.

## Everyday commands

Run these in a Terminal on the Ubuntu computer, after `filament-kit` (for example `filament-kit status`). A command's own help (`-h`) says if it needs `sudo`.

| Command | What it does | Hub page place |
| --- | --- | --- |
| `status` | Checks everything and prints one row per check | Overview |
| `printer list` | All printers, set up and found | Printers |
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
| `printer live <printer>` | Prints where the live view is | Open the live printer view |
| `printer menu` | The Printers screen | Printers |
| `klipper add-on` | Prints the commands that install the Klipper add-on | Klipper add-on |
| `recent` (same as `recent history`) | Recently added records | Recently added |
| `recent show <record> [--photos]` | One record: fields, confidence, revisions | Record detail |
| `recent revise <record> --note TEXT [--item N]` | Ask the Label Reader to correct it | Ask the Label Reader to correct it |
| `recent edit <record> field=value... [--item N] [--spools 41,42]` | Edit by hand | Edit by hand, Save changes |
| `recent undo <record>` | Undo the newest revision that is not undone | Undo revision N |
| `devices` (same as `devices list`) | Paired devices | Devices |
| `devices forget <device>` | Unpair a device | Revoke |
| `pair [--slicer-sync \| --weigh-station] [--text] [--no-wait]` | Pairing code, QR and fingerprint | Pair a phone / Link for the Slicer Sync / Link for the Weigh Station |
| `weigh-station pair [--local]` | Run on the Weigh Station: pair it with the Hub | Pair the Weigh Station on this machine |
| `weigh-station flash-display` | Write the Weigh Station display firmware over USB | Flash a device |
| `weigh-station pairing-state` | Paired, not paired or not checked yet | (none) |
| `tag-reader list` | Tag Reader tokens | Devices, Tag Readers |
| `tag-reader new-token [--name NAME]` | Make a token | Make a token |
| `tag-reader revoke <reader>` | Revoke a token | Revoke |
| `tag-reader flash [options]` | Write a Tag Reader over the Hub's USB | Flash a device |
| `presets status` | Build, Slicer Sync and update state | Slicer presets |
| `presets build` | Build now | Build now |
| `presets lines` | Filament lines and their parents | Product lines |
| `presets set-parent <line> <parent> [--orca]` | Set the Bambu Studio or Orca Slicer parent | Set parent |
| `presets restore-deleted` | Bring back presets deleted in Bambu Studio | Restore deleted presets |
| `presets updates (--line ID \| --all)` | Show what would be accepted (changes nothing) | Show what would be accepted |
| `presets accept-updates (--line ID \| --all)` | Accept updates (asks) | Accept these |
| `features` (same as `features list`) | Features, on or off | Features |
| `features menu [--numbered] [--raw]` | The Features checklist | Features |
| `features on <feature> [--hub ADDRESS]` / `features off <feature>` | Switch one feature (`--hub` when switching on the Weigh Station without the Hub service) | Turn on / Turn off |
| `features setup <setup> [--hub ADDRESS]` | Choose the setup | Setup |
| `features apply [--no-pair]` | Apply the features again | Apply again |
| `features units` | The service files the features need, one per line | (none) |
| `config [--numbered]` | The settings menu | Settings |
| `config show` | All settings, in menu order | Settings |
| `config set <key> <value>` | Change one setting | Settings, one field |
| `label-reader status` | Label Reader engines and their health | Settings > Label Reader |
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
| `spoolman fields` | Make the kit's extra fields in Spoolman | Overview, Make the fields |
| `spoolman address [<url>]` | Show or change the Spoolman in use (checked before saving) | Settings > General, Spoolman address |
| `update [--check \| --rollback] [--scheduled]` | Updates | Updates |
| `uninstall [--purge]` | Remove filament-kit (asks) | Updates, footer line |
| `logs [<service>] [--lines 50\|100\|200]` | The end of a service's log | Logs |
| `add` | Prints where spools are added | (none) |
| `spool` | Prints where spools are opened, tagged and moved | (none) |
| `help [<command> \| aliases \| --markdown]` | Help; `--markdown` prints the command table for the user guide | (none) |

### Notes on some commands

- **`printer map <printer> --by-loading`** needs the running Hub: it works on the same session as the Hub page and the
  apps (see [When mapping fails](#when-mapping-fails-map-by-loading-filament-v050); the usual way is
  [Map slots](#map-slots)). It names each slot and you load it. At **Answer:** type `y` (or the slot you loaded, for
  example `A2`), `s` to skip it or `q` to stop; `?` lists the keys. A Klipper printer is mapped only this way.
- **`printer report <printer>`** makes a short file to attach to an issue when a printer is not known or its mapping
  failed. It holds no serial number, address, name or account id; read it first. When the printer can't be reached,
  the report is built from what the Hub saved and says so. **Collect a report** on the Hub page does the same.
- **`tag-reader flash`** writes the Tag Reader plugged into the Hub's USB (see [Flash a device](#flash-a-device)).
  `--port <port>` names its USB port. `--source <folder>` builds the firmware from the `reader` folder of a checkout with
  PlatformIO and flashes it; `--out <file>` only writes its `secrets.h` (mode 600) so you can build elsewhere
  ([reader/README.md](../reader/README.md)).
- **`weigh-station pairing-state`** prints one line: `paired with <address>:<port>`, `not paired`, or `not checked yet`
  (when you are not root, so it can't read the pairing).

Your spool inventory (Spoolman) is also in a web browser on any computer at home:
`http://<computer name>.local:7912`, where `<computer name>` is the Ubuntu computer's own name (type
`hostname` in a Terminal to see it). The installer prints this address at the end.

## Bambu Lab printers

Klipper printers (through Moonraker) are a separate, opt-in Feature that is never part of a Setup: switch it on with
`sudo filament-kit features on klipper`. See [Klipper printers](klipper.md) (v0.4.0). The rest of this section is about
Bambu Lab printers.

The Hub finds Bambu Lab printers by listening for the announcements they send on your home network. For
that to work:

- The Ubuntu computer must be on the **same network segment** as the printers: the same router or switch and
  the same Wi-Fi / LAN, not a separate guest network or VLAN. Announcements do not cross routers.
- If the computer runs a firewall (for example `ufw`), allow incoming **UDP ports 2021 and 1990** from your
  home network, for example `sudo ufw allow from 198.51.100.0/24 to any port 2021,1990 proto udp` (use your
  own network's range).
- A Hub inside **WSL**, a virtual machine with NAT networking, or a container without host networking does
  not receive the announcements (and phones can't reach it). In WSL, switch to mirrored networking
  (`networkingMode=mirrored` in `.wslconfig`; see [Running the Hub in WSL](install-server.md#running-the-server-in-wsl)).
  Otherwise add the printers by hand with **Add a printer** on the Hub page's Printers section (below), or with
  `sudo filament-kit printer add`.

A printer appears in the app once it has been seen on the network (or added by hand with its IP address or its name,
which is kept as you typed it and looked up each time it is used); you then enter its Access Code in the app to set it up.

### Add a printer

Use any of these ways:

- On the Hub page ([Install the Hub](install-server.md#the-setup-page-v040)): open **Printers**, **Add a printer**, choose
  the type (Bambu or Klipper), and give an IP address or a name. A Bambu printer also needs its **Access Code** (shown
  on the printer's screen; the serial number can be left blank, the Hub reads it from the printer). A Klipper printer
  needs no Access Code. The web app's **Manage printers** adds a printer too.
- In the app: open **Printers**. The printer must already be in the list (the Hub finds it on the network).
  Tap it, and type its **Access Code**. To add a Klipper printer, tap **Add a Klipper printer** at the end of the list
  (name, address, port; the API key, if it needs one, is set later from the printer's own screen).
- On the Ubuntu computer: `sudo filament-kit printer add`. Enter the name, IP
  address, serial number and Access Code.

Then run **Map slots** (next section), and load spools into the printer from the app.

### Map slots

Before the Hub takes filament off your spools in Spoolman, it has to learn how the printer numbers its AMS
slots. **Map slots** in the app (or `sudo filament-kit printer map <printer>` on the Ubuntu computer) does that:

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

- **Stopping a mapping** (Ctrl-C, closing the terminal, or restarting the Hub) always puts the slots back
  first and then reports the mapping as failed. If the computer loses power or the process is killed mid-way,
  the Hub keeps a note of every slot's original setting (`/var/lib/filament-kit/printers/<serial>/slottest-snapshot.json`);
  the next mapping run, or the Hub when it starts and the printer is idle, puts back every slot that still
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

#### When mapping fails: map by loading filament (v0.5.0)

If **Map slots** keeps failing, map the printer by hand. On the Hub page, open **Printers** and tap **Map by loading
filament** next to the printer (it is also offered under a failed mapping). The web app's Printers section and the
app's printer screen have the same button, and `sudo filament-kit printer map --by-loading <printer>` does it in a
terminal (it needs the running Hub). All four share one session per printer. The page names one slot at a time:

1. It says, for example, "Load A2 to the nozzle, then wait." Load that slot on the printer's screen.
2. When the printer reports the load, the page asks "The printer now reports A2 loaded. Is that the A2 you loaded?"
   Tap **Yes**. If you loaded another slot, pick it after **No, I loaded** and tap **Save that**.
3. **Skip** leaves a slot unmapped; **Stop** ends the mapping and keeps what you confirmed.

On a printer with two nozzles the page also asks which nozzle, unless the printer says so itself. A printer that does
not report what is loaded gets a list instead: pick the slot, and the page records it as entered by hand.

Afterwards, loading spools into those slots works. Filament use comes off the spools only once **Map slots** has
proven the printer's slot numbering; until then it is only logged, and the page says so. A later **Map slots** never
changes a slot you confirmed: if it finds something else, it says so instead. The page asks you once whether to
share the map in a printer report for other owners of the same model. filament-kit sends nothing itself: **Yes** says how
to make the report (**Collect a report** on the Hub page's Printers section, on the printer's screen in the
app or in the web app, or `sudo filament-kit printer report <printer>`) and attach it to an issue.

A Klipper printer has the same button: it names its tools or lanes, and you make each one active. See the Klipper
guide.

If a printer's certificate changed, the Hub stops talking to it. If you reset the printer or its mainboard was
replaced, add the printer again with its Access Code. If not,
something else may be answering at the printer's address: check the printer's IP before re-adding it.

**Backups and restore (v0.4.0).** The web unit runs as its own user, `filament-kit-web`, with its state in
`/var/lib/filament-kit-web` (the Claude connector's sign-ins, its token, push keys). Backups include it and keep the
file permissions (`tar --acls --xattrs`). If you restore a backup by hand, extract it with `tar --acls --xattrs`
into a removed or empty folder, or run `sudo filament-kit features apply` afterwards; otherwise the web unit loses
read access to the files it needs.

A backup of your spools and settings is made every night in `/var/backups/filament-kit` (the last 14 days are
kept, unless you change that on the Hub page).

### Backups and restore (v0.5.0)

A backup is **one zip file** with everything filament-kit keeps, so a new machine can be brought back to how this one was:

- the Spoolman database (your spools and filaments);
- the settings, the setup code, the trusted computers, the printers and their slot maps, the Hub's certificate;
- the paired phones and Slicer Sync, the Tag Readers' tokens, the web unit's sign-ins, the Weigh Station's pairing;
- `manifest.xml`, which lists every file with its checksum, and the filament-kit version and Features it came from.

Not in it: the program itself, the downloaded releases, the logs, the Slicer presets from Bambu itself that Slicer Sync uploads and
earlier Filament Catalog versions. Those come back by themselves.

**Keep the zip somewhere safe.** It holds every secret filament-kit has: the Anthropic key, the printers' Access Codes and
the certificate's private key. The zip is not encrypted.

**Make one.** On the Hub page, open **Settings**, then **Backups and restore**, and tap **Back up now**. **Show the backups**
lists them (the nightly ones too, the newest first) and **Download** saves one as
`filament-kit-backup-<computer name>-<date>-v<version>.zip`. Both take the setup code, or a trusted computer. At
the Hub:

```bash
sudo filament-kit backup create
```

**Restore on a new machine.** Install the Hub as usual, then either:

- on the Hub page, under **Settings**, **Backups and restore**, choose the zip and tap **Upload and check**. The page says what
  is in it. Type `restore` and tap **Restore**; or
- copy the zip to the Hub and run:

  ```bash
  sudo filament-kit restore filament-kit-backup-<...>.zip
  ```

The restore checks every file against the manifest first, and refuses a backup made by a newer version of filament-kit
(it says which version to install first). It keeps a backup of what is on the machine now, puts everything back,
turns on the Features the backup names (installing what they need), and shows `filament-kit status`. Afterwards the
setup code, the trusted computers, the printers and the pairings are the ones from the backup: phones and Slicer
Sync keep working without pairing again.

On a machine with **another computer name**, the Hub makes a new certificate, and the phones and Slicer Sync need
pairing again (**Devices**). With a release tarball, `sudo ./install.sh --restore <zip>` installs and restores in one
step.

### Your own printer data (override)

The facts about each printer model and AMS unit come from filament-kit's own `bambu_hardware.xml`. To correct or add
something, put your own file at `/etc/filament-kit/bambu_hardware.xml`. It wins element by element over
filament-kit's own file, and the updater never replaces a file you made.

Your file must carry a **version above filament-kit's own file**, in its first line: for example, when its own file
says `<bambu-hardware version="1.0">`, write `<bambu-hardware version="1.1">`. A file whose version is the same
as or lower than its own is **ignored**, so an old file never hides newer data that an upgrade brings.
`sudo filament-kit status` then shows a note: `override version ... is not newer than the kit's own ...: ignored`. After an upgrade that ships a newer file, check that note: raise your file's version again, or delete
your file if the new release already has what you added. A file with mistakes is refused whole (the last good
data stays in use), and status names it.

<a id="presets-in-bambu-studio"></a>
## Slicer presets in Bambu Studio

The Hub builds one Bambu Studio filament preset for each filament line you own (a line is a brand's product,
for example one brand's PLA, without the colour), for each of your printers and each nozzle size. Slicer Sync
then installs them in every Bambu Studio folder on the PC ([Stable and Beta Bambu Studio](#stable-and-beta-bambu-studio-v040)); Slicer presets already there are never replaced unless you accept an update.

- Names look like `<brand> <line> @Bambu Lab <printer> <nozzle> nozzle`.
- Spoolman data for your filaments wins over the Filament Catalog, and the Filament Catalog wins over Bambu's own starting preset
  (the "Bambu Studio parent").
- **Your edits are kept.** If you change a preset in Bambu Studio, the Hub keeps those values the next
  time it builds.
- **Delete Slicer presets in Bambu Studio, never on disk.** Slicer Sync never deletes preset files. A preset that is
  no longer built is listed as "delete in Bambu Studio" in the sync log; delete it there yourself.
- A generated preset you delete in Bambu Studio stays deleted: later builds leave it out. To get the deleted
  ones back, run `sudo filament-kit presets restore-deleted`; the next build brings them back and Slicer Sync
  installs them.
- Bambu's cloud keeps about 100 filament Slicer presets. The rest stay on this PC only.
- A line the Filament Catalog doesn't have: in the app tap **Add a line to the Filament Catalog** (on the Slicer presets screen), fill in the line and tap **Save to the catalog**. The Hub page has its own box for this, **Add your own entry**.
- To change which Bambu preset a line starts from, change its **Bambu Studio parent**: in the app, on the
  **Check the spools** screen while you add spools (field **Bambu Studio parent**; it applies to every colour of
  that line), or in **Add a line to the Filament Catalog**, or on the Ubuntu computer with `sudo filament-kit presets lines` (lists the
  lines) and `sudo filament-kit presets set-parent <line> <parent>`.
- To see how the last build went: `sudo filament-kit presets status`. To rebuild now:
  `sudo filament-kit presets build`. (It needs Slicer Sync to have run once.)

## Slicer presets in Orca Slicer

The Hub can also build filament Slicer presets for Orca Slicer, for your Bambu Lab printers and for other printers Orca
Slicer knows (for example a Sovol). This is off until you ask for it in `/etc/filament-kit/config.json`:

- `"presets_orca": true` makes Orca Slicer presets for the Bambu Lab printers the Hub knows, for every nozzle Orca
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
  printers are named differently in Orca Slicer from the default.

Then run `sudo filament-kit presets build` (or wait for the next sync).

- Names look like `<brand> <line> @<printer> <nozzle>`, for example `SUNLU PLA+ 2.0 @SV08 MAX 0.4`.
- Each line also has an **Orca Slicer parent**, the Orca system preset it starts from. The Hub picks one;
  `sudo filament-kit presets lines` shows it and `sudo filament-kit presets set-parent --orca <line> <parent>`
  changes it (give the parent's name without ` @System`).
- Slicer Sync finds Orca Slicer on the PC by itself (its folder in `%APPDATA%\OrcaSlicer`). It sends
  the Orca Slicer presets to the Hub along with the Bambu Studio ones and installs the Orca Slicer presets the Hub builds. It waits
  while Orca Slicer is open, just like for Bambu Studio. A PC without Orca Slicer only gets the Bambu Studio
  ones. While the Hub makes no Orca Slicer presets (no Orca printers set up as above), Slicer Sync leaves Orca
  Slicer alone: it does not wait for it and sends nothing from it. `filament-kit-sync status` on the PC shows the
  Orca folder it uses.
- The same rules as for Bambu Studio apply: your edits in Orca Slicer are kept, and Slicer presets are deleted in Orca
  Slicer, never on disk.
- `sudo filament-kit presets status` shows the last build (its count is the Bambu Studio ones) and the
  problems of both slicers, for example a line whose Orca parent is not in your Orca Slicer.

<a id="spec-library-updates"></a>
## Filament Catalog updates

The Filament Catalog holds published filament specs (temperatures, speeds). It is optional and is not part of the
program: Slicer presets work without it, from your Spoolman values and Bambu's or Orca's own starting Slicer presets. Ask for it
with `sudo filament-kit catalog update`, or switch the **Filament Catalog** Feature on (it then also checks every day). A
copy you downloaded earlier keeps being used when filament-kit is upgraded.

- `sudo filament-kit catalog status`: shows the Filament Catalog version (or that none is downloaded), the last check, and any
  entries and fields left out of it because the Hub can't read them.
- `sudo filament-kit catalog update`: downloads the Filament Catalog, or a newer version, now.
- `sudo filament-kit catalog rollback`: goes back to the version before the last update, and says so. The daily
  check then skips the version you left until a newer one is published; `catalog update` by hand still installs it.
  Rolling back again goes forward and clears that. To stop checks altogether, set
  `/etc/filament-kit/config.json` to `"library": {"schedule": "off"}` (or `"weekly"`; the default is `"daily"`).
- `sudo filament-kit catalog add <file>`: adds or replaces your own entry from a JSON file.

The download is the `library.tar.gz` asset of the latest release (`library.url` in the config can point to
another `.tar.gz` or to a folder that serves `index.json` and the entries). The release's `library.tar.gz` is
checked against the release's signed `SHA256SUMS`, like the program itself, and refused without it. Another
`.tar.gz` is checked the same way when a signed `SHA256SUMS` sits next to it; otherwise (and for a folder URL)
`catalog update` prints a note that it is not signature-checked. Every entry is checked before it is used, and a
bad download changes nothing. A signed one with some entries or fields this version can't read yet is used without them, unless more than a quarter of its entries would go. The token below is only ever sent to api.github.com and objects.githubusercontent.com,
as for program updates. Testing against a private repository: put a GitHub token that can read it in
`/etc/filament-kit/github_token`; the `releases/latest/download` link does not accept a token for a private
repository, so find the asset's id (`gh api repos/<owner>/<repo>/releases/latest --jq '.assets[] | [.name, .id]'`)
and set `library.url` to `https://api.github.com/repos/<owner>/<repo>/releases/assets/<id>`. While that release is private, `catalog update` shows an error and the daily check
logs a warning; neither is a failure, and the Filament Catalog you already have (or none) keeps working.

Your own `catalog add` entries override the shared Filament Catalog for that line.

## Flash a device

The Tag Reader (the tag reader at a printer) and the Weigh Station display are ESP32-C3 boards. The Hub carries a
ready-made firmware for each, so you need no toolchain: plug the board into a USB port with a data cable (a
charge-only cable shows nothing) and write it from the Hub page or the command line.

**Tag Reader, from the Hub page.** Open the Hub page in Chrome or Edge on a desktop or laptop computer and go
to **Flash a device**.

1. Device: **Tag Reader**. Plugged into: **This computer** (the board is on the computer you sit at) or **The Hub**
   (the board is on the Hub's USB port; then pick the board if several are plugged in).
2. Type the Wi-Fi name (2.4 GHz only) and its password twice. Pick the buzzer: high-triggered for the build in the
   parts list, low-triggered for the older 3-pin buzzer. A name is optional (for example "bench"). Type the setup code
   if this computer isn't trusted.
3. Press **Connect and write** and pick the board in the browser's list (from this computer), or **Write on the Hub**
   (on the Hub).
4. Wait for "Done. The Tag Reader joined '<Wi-Fi>' and reached the Hub." It takes up to about a minute and a half.
   If it ends with a reason instead, it names what to fix: the Wi-Fi name or password, the Hub's public address, or
   "run this again". A failed run removes the reader's token again.
5. Unplug it and power it where it lives. It keeps its settings and asks you to pick a printer with the knob.

Writing from this computer needs Chrome or Edge on a desktop or laptop and the Hub page opened over HTTPS; phones and
other browsers can't reach USB from a page, and the page says so and disables the button. The firmware comes from the
installed Hub, never from the internet. The Tag Reader also needs the Hub's public HTTPS address (`web.public_url`,
see [Remote access](#remote-access)): it only calls the Hub over that address, and the page says so when it is missing.

**Tag Reader, from the command line.** Plug it into the Hub and run `sudo filament-kit tag-reader flash`. It asks
the same three questions (Wi-Fi name, password twice, buzzer) and ends the same way. To update a reader later, run it
again with the board plugged in: it keeps its settings and writes the Hub's newer firmware. A reader set up this way
refuses updates over Wi-Fi unless you gave `--ota-pubkey`; see [reader/README.md](../reader/README.md).

**Weigh Station display.** The same page: Device **Weigh Station display**, then **This computer**, **Connect and write**; afterwards plug it
into the Weigh Station computer. A display plugged straight into the Weigh Station computer needs nothing from you: the Weigh Station
writes its firmware to it by itself (see [Reader, panel and beep](#reader-panel-and-beep)).

The web app and the app can't write USB firmware; the Hub page does it.

<a id="intake-station"></a>
## Weigh Station

The Weigh Station weighs a spool and reads its NFC tag, so adding or opening a spool needs no typing. It runs as
the `station` Feature, on the Hub computer (Hub with Weigh Station) or on a second computer (Weigh Station only, see
[Setups](#install-modes)).

### Hardware

- A **DYMO M10 USB scale**. Other DYMO USB postal scales that the Weigh Station detects also work. Switch it on before you start
  the Weigh Station; a DYMO only shows up on USB while it is on, and it switches itself off after a few minutes.
- A **PN532 tag reader**: on a USB serial adapter (CH340 chip), on the button panel's I2C header (an Elechouse NFC
  Module V3 in I2C mode, firmware 11), or both. With both, the same tag seen by the two within 2 seconds counts as
  one tap; a quick second tap of the same tag on the same reader inside those 2 seconds is merged as well.
- Optional: the **button panel** (Hold and Discard buttons, lamps, an OLED, a buzzer and a speaker, on an ESP32-C3 Super Mini). How
  to build it: the [Weigh Station display guide](https://github.com/thompsonfabco/filament-kit-hardware/tree/main/devices/intake-panel). What the Weigh Station does with it:
  [station/PANEL.md](../station/PANEL.md).
- Optional: a speaker (USB or the computer's headphone socket) for the scan beep when there is no panel.
- Optional, with the panel: a **BME280** sensor for room temperature and humidity, a small speaker on the panel
  (it says things like "1042 grams. Hold yellow to save.") and a **USB webcam** that takes a picture of the spool when you press
  Hold. How to build them is in the [hardware guides](https://github.com/thompsonfabco/filament-kit-hardware/tree/main/devices); the Weigh Station's side is in
  [station/PANEL.md](../station/PANEL.md). The Weigh Station installs `espeak-ng` and `ffmpeg` for
  the speech and the picture, and its user joins the `video` group to read the camera.

Build guides, wiring diagrams and enclosures for the Weigh Station's devices are kept in the
[filament-kit-hardware](https://github.com/thompsonfabco/filament-kit-hardware) repository.
[station/PANEL.md](../station/PANEL.md) keeps the panel's behaviour, serial protocol and speech format. This guide keeps the list of supported devices above, and the Hub flashes a C3 panel
itself when it runs other firmware than the one it carries.

### What the installer changes on the computer

Turning the Weigh Station on (install or **Features**) also changes these, because each one stops a Weigh Station from
working:

- **brltty is removed.** It takes CH340 USB adapters for braille displays and grabs the reader.
- **ModemManager is turned off.** It probes every new USB serial port and confuses the reader and the panel.
- **Sleep, suspend and hibernate are turned off** (masked). An idle Ubuntu desktop otherwise goes to sleep and
  the Weigh Station stops answering.
- **Audio outputs are unmuted** at 80% and saved, so the scan beep can be heard.
- A **udev rule** (`/etc/udev/rules.d/99-zz-filament-kit-station.rules`) lets the Weigh Station read the DYMO scale
  without running as root.

Turning the Weigh Station off again, or switching to another Setup, leaves these changes as they are. To undo them by
hand: `sudo systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target`,
`sudo systemctl enable --now ModemManager`, and `sudo apt-get install brltty`. Uninstalling removes the udev rule.

### Reader, panel and beep

- An older ESP8266 panel and the reader both use CH340 USB adapters, which have no serial numbers, so their
  `ttyUSB` numbers can swap between boots. A C3 panel is native USB: it shows up as a `ttyACM` port with USB
  vendor `303a`. The Weigh Station finds the panel by asking each port who it is, and the reader gets a `ttyUSB` port
  the panel isn't on (`NFC_DEVICE=auto`). With no panel, the reader gets the first USB serial port.
- A scan beeps on the panel's buzzer, or, without a panel, through a USB speaker or the headphone socket
  (`STATION_BEEP`).
- **The speaking voice.** The Weigh Station speaks with the Piper voice `en_US-libritts_r-medium` (speaker 0), downloaded
  when the Weigh Station is installed (60 to 80 MB, checked against a pinned hash). If the download fails or the file
  does not match, the install carries on with a warning and espeak-ng speaks. To use espeak-ng on purpose (no
  download), choose **Weigh Station voice** in `sudo filament-kit config`. The voice is licensed **CC BY 4.0**
  (LibriTTS-R; credit in [THIRD-PARTY.md](../THIRD-PARTY.md#speech-voice)). To use the public-domain
  `en_US-ljspeech-medium` voice instead, set `station.voice` to it in `/etc/filament-kit/config.json` and run
  `sudo filament-kit features apply`.
- With the panel, Hold and Discard also speak (`"speech"`), and Hold takes a picture with the webcam
  (`"camera"`). `curl http://127.0.0.1:5003/state` then shows `"air"` (the BME280 reading) and `"photo"`, and the
  picture itself is at `/photo`. The Weigh Station only answers GET requests, and only the addresses it allows.
- These settings are in `/etc/filament-kit/config.json` under `"station"`: `"nfc_device"` (`"auto"`, or a
  device such as `"tty:USB0:pn532"`), `"beep"` (`true` or `false`), `"beep_device"` (empty for automatic, or
  an ALSA device such as `"plughw:1,0"`), `"speech"` (`true` or `false`) and `"camera"` (`"auto"` for the first
  USB camera, a device such as `"/dev/video0"`, or `"off"`), `"panel_flash"` (`true` or `false`, see the
  next point), `"panel_swap"` (`true` or `false`, see the point after that) and `"speaker_volume"` (0 to 100,
  default 50: how loud the C3 panel speaks; environment `STATION_SPEAKER_VOLUME`). After a change, run `sudo filament-kit features apply`.
- **Panel firmware updates itself.** The Weigh Station carries the display's firmware. When it finds a panel running
  another version, it writes the bundled one to it over USB (once per version) and then uses it. If that does
  not work, the panel keeps running as it is. Set `"panel_flash": false` to never touch the panel's firmware.
  `curl http://127.0.0.1:5003/state` shows the panel's version as `"panel_version"`. A panel on older ESP8266
  firmware (9 or earlier) is used as it is and never reflashed.
- **A blank display board.** A new ESP32-C3 has no firmware for the Weigh Station to find. Plug it in and run
  `sudo filament-kit weigh-station flash-display`: it stops the Weigh Station, lists the C3 ports that give no answer, asks before
  flashing each one, checks the display answers afterwards and restarts the Weigh Station.
- **Buttons and lamps the other way round (v0.4.0).** If your panel's yellow and red buttons and lamps are wired the
  opposite way to the C3 pin table in the [Weigh Station display hardware guide](https://github.com/thompsonfabco/filament-kit-hardware/tree/main/devices/intake-panel) (the button you press for yellow acts as red, and the lamps are
  swapped too), set `"panel_swap": true` under `"station"` in `/etc/filament-kit/config.json`, then run
  `sudo filament-kit features apply`. The default is `false`. This needs firmware 9 or later. A C3 panel already runs
  firmware 10 or later. An ESP8266 panel on older firmware has to be reflashed by hand, because the Weigh Station never reflashes
  it; until then yellow can't do a long press, so it can't save.

### Is it working?

- `sudo filament-kit status` shows the Weigh Station's real pairing state (v0.4.1; before, it asked you to run it with
  `sudo` even when you had), and on the Hub it shows `station answering at ...`. `station reader not seen` means no
  tag has been read yet; `station scale not seen` means the scale has sent nothing yet (switch it on and put
  something on it).
- On the Weigh Station computer: `curl http://127.0.0.1:5003/state` shows the last tag and weight.
  `sudo journalctl -u filament-kit-station -n 30` shows what the Weigh Station is doing;
  `NFC reader ...; retrying in 5 s` means the reader is not plugged in or not found.
- The Weigh Station answers only its own computer and the Hub's address. Anything else gets no answer.
- The button flow talks to the Hub with its own pairing (v0.3.0 and newer). On the Hub run
  `sudo filament-kit pair --weigh-station`, then within 10 minutes run `sudo filament-kit weigh-station pair` on the Weigh Station
  computer and paste the link; it checks the link with the Hub and says "expired" if you were late. On a
  Hub with Weigh Station both run on the same machine. The Weigh Station's pairing can reach only the Weigh Station part of the Hub.
  `sudo filament-kit pair` on a Weigh Station only computer says that pairing runs on the Hub.
- **Pairing from the Weigh Station's own screen (v0.5.0).** An unpaired Weigh Station asks the Hub named in
  `station.allow` when it starts, and again when you hold yellow while it shows "Not paired". Its screen shows
  "Pair code" and six digits, and it says them. On the Hub page, open **Devices**; a Weigh Station that asks to
  pair is listed there. Tap **Pair** only if the page shows the same six digits; otherwise tap
  **Refuse**, because someone else asked. The Weigh Station saves its pairing by itself within a few seconds.
- After the panel says "Saved #N / tag not linked", holding yellow again links the tag to that spool instead of
  saving a duplicate.
- A Weigh Station on a second computer: on the **Hub**, put the Weigh Station's address in
  `/etc/filament-kit/config.json` under `"station"`, for example `"url": "http://station.local:5003"`. If the
  Hub's address changes, run `sudo filament-kit features apply` on the Weigh Station computer so it answers the new
  one.

## Recently added

Every time you add a spool, the Hub keeps a record of it: the photos of the label (when the save came
from a label read), the values you saved, the weight and the tag. From the record you can correct a wrong read
afterwards without scanning the spool again, and undo the correction.

A record is made when a save succeeds, from any place you save from: the app, the web app, the Weigh Station's
buttons or the command line. A save you typed by hand makes a record without a photo. The records live on the
Hub, are part of its backups, and a photo goes nowhere except to the Label Reader engine you set up, and only when you ask for a
revision.

**Where to find it.** On the Hub page, **Recently added**, and in the web app that the Hub itself
serves, **Recent**. Records are listed newest first, each with its first photo (tap to enlarge), the spools'
names, the time and a mark for its state: **as detected**, **revised by AI** or **edited by hand**. **Open** shows the
rest of the photos and the saved values of each spool.

**Correct a record by hand.** Change any of the values and press **Save changes**. No Label Reader is needed.

**Correct a record with a note.** Type what is wrong in the note box, for example "brand is Polymaker", and press
**Ask the Label Reader to correct it**. The Hub asks the Label Reader again with the photos, the first result and your note, and shows
the values before and after. Nothing is written until you press **Accept**. If you saved several spools in one
add, accepting applies to all of them. A revision counts as one label read toward the daily limit. With the Label
Reader off on this Hub, the note box is greyed.

**What a correction does to Spoolman.** A filament that other spools also use is never edited: the spools are moved to
a filament with the new values, found if one exists and created if not. A filament only this record's spools use is
edited in place. A filament left with no spools is reported, not deleted. Each spool keeps its NFC tag, its opened
state, its location and its used weight.

**Undo.** **Undo revision** takes back the newest correction that is not undone yet, one step at a time.

**How many records are kept.** The newest 20 by default. Change the number under **Settings**, **Label Reader**, **Records kept** on the Hub page, or in `sudo filament-kit config`. 0 keeps none, and the highest is 500. The oldest
records and their photos go first. **Recently added** shows how much disk the photos use.

**On the command line.**

| Command | What it does |
|---|---|
| `filament-kit recent` (or `recent history`) | Lists the records, newest first, with their photo files on the Hub. |
| `filament-kit recent show <record>` | One record with its corrections. |
| `filament-kit recent revise <record> --note "brand is X" [--item N]` | Shows the values before and after, then asks before applying (`--yes` applies without asking). |
| `filament-kit recent edit <record> [--item N] field=value ...` | Edits by hand. |
| `filament-kit recent undo <record>` | Undoes the newest correction. |

## Tag readers and printer slots

### More tag readers

Besides the Weigh Station, the Hub can read tags from other tag readers that report the last tag they saw, for
example a Tag Reader on a printer. List them in `/etc/filament-kit/config.json`:

```
"tag_sources": [{"name": "printer", "url": "http://printer-reader.local:5002/last-tag"}]
```

Each address must answer a GET with JSON like `{"status": "ok", "nfc_id": "04A1B2C3", "read_at_unix": ...,
"age_seconds": 12}` (the station's own `/last-tag` speaks the same). The newest tap across all readers and the
Weigh Station wins. A tap from the last 5 minutes, or a spool held on the Weigh Station's display, counts as the spool you are
working on: a label read then treats that spool as opened, and the Open spool tab of the web app shows it.
A reader that does not answer is skipped for a minute.

### Printer slots for the Claude connector

The connector's `printer_slots` and `printer_set_slot` tools show and set what is loaded in a printer's AMS
slots, using the Hub's own printer connection (the `printers` Feature must be on).

<a id="claude-connector-and-phone-web-app"></a>
## Claude connector and web app

The `web` Feature runs one more service, `filament-kit-web`, on this computer only (`127.0.0.1:8101`). It gives:

- a **Claude connector** (an MCP server) at `<public address>/mcp`, so Claude can find spools, add spools,
  open a spool, check the Slicer presets and the printer slots for you (tools `find_spools`, `add_spools`, `tag_state`,
  `open_spool`, `preset_status`, `list_lines`, `find_parents`, `add_filaments_to_line`, `add_line`, `generate`,
  `printer_slots`, `printer_set_slot`);
- the **web app** at `<public address>/intake` too (the Hub always serves it at home, with no
  Feature to switch on: [Use the web app](#use-the-phone-web-app)), in any phone browser (no install): add spools by hand (or
  from label photos, with `ai_intake`), open a tapped spool, and see the Slicer presets. With the `printers` Feature on it
  also has a **Printers** tab (replaces the old `/printer/` page): a printer picker, live status, the camera,
  pause / resume / stop (stop asks first), the chamber light, the filament in each AMS unit, the usage log with
  undo, and a re-map button. The camera is a picture stream on printers that have one and an HLS video on the
  rest (HLS plays in Safari on iPhone and Mac). The light button follows the printer's reported chamber light;
  the Hub switches both light nodes when a printer has two, as the old page did. Print alerts to the phone
  (Web Push) are off; `"web": {"push": true}` turns them on, needs `pip install 'filament-kit[push]'` and lets the
  web service reach the browsers' push services on the internet, which the Hub does not open for you: the web service's
  systemd limits allow only your home network, so run `sudo systemctl edit filament-kit-web`, add `[Service]` and
  `IPAddressAllow=any`, save, and `sudo systemctl restart filament-kit-web`. The phone's Test button says when the
  push service cannot be reached.

The connector needs a passphrase; the web app has no sign-in: it only answers your home network. Adding
spools shows a preview first in both, as in the app.

### Turn it on

1. Pick the **public address**: the `https://` address people (and Claude) will use, ending in a path such as
   `/filament`, for example `https://filament.example.com/filament`. It must start with `https://`, also when
   web access is only used at home: the connector's sign-in only works over https. The web service itself only
   listens on this computer, so something has to carry that address to it: the Hub's [Remote access](#remote-access)
   Feature, or a web server of your own that passes the path on to `http://127.0.0.1:8101`.
2. Put it into `/etc/filament-kit/config.json`:

   ```
   "web": {"public_url": "https://filament.example.com/filament"}
   ```

3. Set the passphrase (at least 12 characters; you type it twice and each character shows as a `*`):

   ```
   sudo filament-kit web passphrase
   ```

4. Turn the Feature on and check it:

   ```
   sudo filament-kit features on web
   sudo filament-kit web status
   ```

   `web status` shows the public address, the connector and web app addresses, whether the passphrase is set,
   whether the service answers, and how many connectors are signed in. No line should start with
   `FAIL`. (At a terminal, `features on web` asks for `web.public_url` if it is not set; without a terminal it stops
   with an error. The Features checklist (`sudo filament-kit features menu`) asks for it too, so steps 2 and 4 can be done
   there in one go.)

### Add the connector in Claude

In claude.ai, add a custom connector with the address `<public address>/mcp`. Claude then opens a sign-in page:
type the passphrase there. Claude stays signed in after that; changing the passphrase later does not sign it out.

<a id="use-the-phone-web-app"></a>
### Use the web app

The Hub serves the web app itself, whatever Features are on: open
`https://<server name>.local:8710/intake` on the phone while it is on the home network (the Hub page's
**Devices** section shows the address and a QR code), accept Safari's warning about the Hub's own certificate once,
and add the page to the home screen if you like. With the `web` Feature on, `<public address>/intake` serves the
same app as well, with your certificate (step by step: [Use the web app on an iPhone](install-iphone-web-app.md)).
There is no sign-in: anyone on your home network can use it (as with the app's pairing, the home network is
the gate). Since it is part of the Hub, it is always on: anyone on the home network who opens it can add and edit
spools, read labels (within the daily cap, with `ai_intake`) and, with the `printers` Feature, use its Printers tab.
The Hub page's Printers section links that tab (**Open the live printer view**), for loading spools, the camera and
the printer controls from a computer.
The Printers tab's **Manage printers** section adds a printer the Hub has seen on the network (with its Access Code)
or a Klipper printer, and renames, readdresses, re-keys, unpins or forgets one, as the Hub page's Printers section does.
It asks for the Access Code again before trusting a new certificate (and for a new address when none is pinned yet),
and for a Klipper printer's API key when it moves, so the Hub never sends a stored secret to a host it can't vouch
for. At the `web` Feature's public address these changes are off unless **Allow printer changes from the public
address** is on (Hub page: Settings, Network and addresses); there the section only lists the printers.
It answers by the Hub's own names, as the Hub page does. Print alerts to the phone come only through the `web`
Feature's address. In Devices it shows as the built-in device ("This Hub's own pairing"):
it is how the page reaches the Hub and pairs again whenever the Hub starts.

### What only works at home

The sign-in pages (`/authorize`, `/login`) and the whole web app answer only addresses from your home
network. Elsewhere they say that they only work on the home network. Claude's servers reach the connector itself
(`/mcp` and the token exchange) from the internet, so sign Claude in from home once. The home network is the
`192.168.0.0/16` and `10.0.0.0/8` by default (not `172.16.0.0/12`, where Docker's bridges live); set your own
in `"web": {"lan": ["198.51.100.0/24"]}` (each entry a network; `features apply` refuses a bad one). Five wrong passphrases
lock the connector's sign-in for 10 minutes.

### The home network ranges (web.lan)

The ranges above are IPv4. A phone or computer that reaches the web address over IPv6 is refused with
`This device reached the server over IPv6` until you add your home network's IPv6 prefix. (The Hub page is IPv4 only.) To do it:

1. On the Hub, find your prefix: `ip -6 addr show scope global`. A line such as
   `inet6 2001:db8:1234:5678::abcd/64` has the prefix `2001:db8:1234:5678::/64`: the first four groups of the address,
   then `::/64`. (`2001:db8` is the range reserved for examples; yours comes from your provider and can change.)
2. Edit `/etc/filament-kit/config.json` (for example `sudo nano /etc/filament-kit/config.json`) and set the list. Your list
   replaces the default, so keep the IPv4 ranges you want in it:

   ```
   "web": {"lan": ["192.168.0.0/16", "10.0.0.0/8", "2001:db8:1234:5678::/64"]}
   ```

3. Apply it: `sudo filament-kit features apply`. It refuses an entry that is not a network.

## Remote access

The `remote` Feature puts web access on a public `https://` name, with a free certificate from Let's Encrypt.
It installs nginx and certbot. It **never changes your firewall or router**: it prints the rules, and you set
them up yourself.

1. Do [Claude connector and web app](#claude-connector-and-phone-web-app) first (`web.public_url` set).
   Its host name is the public name; you can also write it as `"remote": {"hostname": "filament.example.com"}`,
   which must then be the same name. Optional in `"remote"`: `"email"` (certbot's expiry mails) and
   `"acme_window"`, see the port 80 note below.
2. Make the name point to your home's public address (DNS), and to this computer at home.
3. Turn it on:

   ```
   sudo filament-kit features on remote
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
      sudo filament-kit remote get-certificate
   ```

   nginx stops while certbot runs and starts again afterwards. From then on certbot renews the certificate by
   itself.

**Port 80.** certbot needs port 80 from the internet to this computer whenever it issues or renews (it answers
the check itself). If you only want port 80 open at a set time, open it on your router for a short window each
night and set `"acme_window"` to a time inside it, for example `"03:10 America/New_York"`: certbot's renewal
timer then runs only at that time. Outside the window port 80 can stay closed.

**HTTP/2.** The router speaks HTTP/1.1 only, so its nginx settings work on Ubuntu 24.04's nginx too. Claude and
phone browsers work with that.

Turning `remote` off removes only filament-kit's own router file, its certbot hook and its route. nginx, certbot,
the certificate and any other routes stay. While `/etc/nginx/mcp.d` still holds routes filament-kit did not add, the
router file stays too, because it is what serves them; it says so, and you remove it by hand once nothing
needs those routes.

<a id="local-label-reading"></a>
## Label Reader: On this Hub

The `local_intake` Feature is the other way to read labels: instead of sending the photos to Claude, the Hub sends them
to a label reader running on your own network, so nothing leaves your home. It is a separate service that you run
yourself (on this computer or another one, for example one with a GPU); the Hub talks to it at an address you give it.
It needs the `server` Feature (Hub service), and the Anthropic key is not needed for it. Turn it on with
`sudo filament-kit features on label-reader-local`. You can have it on beside `ai_intake`, and the two work together.

**Install the reader on this computer.** The reader itself is the `filament-kit-vision` program, downloaded from its
own public release. Run `sudo filament-kit local-intake install`: it shows the latest signed release with its
download size, disk space and time for each tier, asks, installs it (the service `filament-kit-vision`, in
`/opt/filament-kit-vision`, its own settings in `/etc/filament-kit-vision/`), switches `local_intake` on and points
the Hub at it. `--tier auto|cpu|gpu` picks the tier (the default is the **Local reader tier** setting),
`--version X.Y.Z` names a version (the only way back to an older one) and `--yes` skips the question.
`filament-kit local-intake plan` only shows what the latest release needs. On the Hub page, **Settings**, **Label Reader**, **On this Hub**: **Check what an install needs**, then **Install <version> (<tier> tier)**; once it is installed the
same place offers **Check for an upgrade** and **Remove**. `sudo filament-kit local-intake remove` runs the reader's
own uninstaller and switches `local_intake` off; its settings are kept.

**A reader on another computer.** It needs no install here: switch `local_intake` on under **Features** and set the
**Address** (see below).

**What the reader gets.** The photos, and a trimmed list of your filaments (names, materials and colours, no
comments, prices, spool data or order history). If the reader asks for a token, set it on the Hub
page under **Settings**, **Label Reader**, or run `sudo filament-kit local-intake token` (it asks with nothing
shown; `--remove` clears it). The token is kept in `/etc/filament-kit/local_intake_token`, and the Hub sends it only
with a read or a revision.

**Which engine reads first.** The setting **Engine order** has four choices:

| Choice | What happens |
|---|---|
| Automatic: On this Hub first, Cloud when it is unsure or fails (the default) | The local reader answers. If it is unsure or fails, Claude reads the photos, when the `ai_intake` Feature is on. |
| Cloud, then On this Hub | Claude reads; the local reader takes over if Claude fails. |
| On this Hub only | Only the local reader reads. If it is down, you get a plain error and the photos are kept. |
| Cloud only | The local reader is not used. |

An engine whose Feature is off is skipped. The local reader is **unsure** when any spool comes back below 78 % sure,
with no confidence, with the brand "Unknown", or with nothing read. When Claude is not on, or its daily limit is
used up, an unsure local answer is still shown, with a note. Only Claude's reads count against **Reads per
day**; local reads are free.

**Where to set it.** On the Hub page, **Settings**, **Label Reader**:

- **Engine order**: the order above (shown when both Features are on).
- **Address**: where the reader answers (the default is `http://127.0.0.1:7915`; any host name or address
  on your network). **Save Label Reader** keeps it; **Test** asks the reader how it is: its version, its API, which tiers are usable
  and whether it can revise readings.
- **Tier**: **Auto** (the CPU first, then the GPU when unsure), **CPU only** or **GPU only**.

At a terminal, `sudo filament-kit config`, under **Label Reader**, asks the same three things.
`filament-kit label-reader status` shows whether the reader answers, its tiers, why it is degraded if it is, and the
last read. `filament-kit label-reader test <photo>... --engine local` sends photos to the local reader only, as a trial: nothing is
saved and no daily read is used. `filament-kit status` and the Hub page's Overview show the reader's health and the
order.

**What you see.** The web app's result screen says which reader answered, its tier, how sure it is, the colour
name and family, and the fields it was least sure of. In Recently added, **Ask the Label Reader to correct it** follows the
same setting: the local reader revises the record for free; a reader that cannot revise gives way to Claude when Claude
is on; a record with no photo goes to Claude only. Only a Claude revision counts toward the daily limit.

**Order history.** The `orders` Feature works with either Label Reader Feature on. The order history is used only in Claude's
reads; the local reader never gets it.

A backup holds the reader's settings and token with the rest of `/etc/filament-kit`.

## Order history

The `orders` Feature gives label reading your shop order history, so the AI can tell the brand, the seller and
the price of a spool when the label does not show them. You need a file with your orders, kept up to date by a
tool of yours, in this shape:

```
{"items": [{"order": "112-...", "date": "2026-10-01", "asin": "B0...", "title": "SUNLU PLA+ 1kg ...",
            "qty": 2, "unit_price": 19.99, "seller": "SUNLU"}]}
```

The Feature needs a Label Reader, `ai_intake` or `local_intake`, so turn one on first (the order history is used by Claude's reads only). Then turn `orders` on; at a terminal it asks for the path to
the file (it is saved as `orders.file` in `/etc/filament-kit/config.json`):

```
sudo filament-kit features on label-reader
sudo filament-kit features on orders
```

The Hub's user must be able to read the file (for example owner `root`, group `filament-kit`, mode 640). If it
cannot be read, labels are still read, without the orders. From v0.4.0 only the web service itself can read the
order list through the Hub: phones, Slicer Sync and the Weigh Station are refused.

## Troubleshooting

- Run `sudo filament-kit status` on the Ubuntu computer. No line should start with `FAIL`; a failing line
  shows a `fix:` line.
- Slicer presets don't appear in Bambu Studio: close Bambu Studio (Slicer Sync waits while it is open), then wait up to
  10 minutes. On the PC, run `filament-kit-sync status` to see the Hub, the Bambu Studio folder in use and
  the last run. If it shows `Waiting: for Bambu Studio to close`, that is why. Also check you are looking at the right
  Bambu Studio: stable and Beta each have their own folder, and the other folder only gets new Slicer presets and the updates
  described under [Stable and Beta Bambu Studio](#stable-and-beta-bambu-studio-v040).
- The Slicer Sync log is `%LOCALAPPDATA%\filament-kit-sync\sync.log`. Backups of your Bambu Studio filament folder,
  made before each install (the 5 newest are kept), are in `%LOCALAPPDATA%\filament-kit-sync\backups`.
- "Other PC" errors: another PC already syncs with this Hub. Remove it with `sudo filament-kit devices forget <device>`.
- `sudo filament-kit presets build` says Slicer Sync hasn't run yet (this is a message, not an error): do [Pair your PC](#pair-your-pc).

## Update

`sudo filament-kit update` downloads the newest release, checks its signature and hash as get.sh does, stops
filament-kit, installs it (no questions) and starts it again. It keeps your spools, settings, key and paired phones, and the
version it replaced: `sudo filament-kit update --rollback` goes back to that one. `sudo filament-kit update --check`
only says whether there is a newer release. It does nothing while a printer is mapping slots or loading a spool.
If an update fails, the previous version is put back and the daily timer does not try the failed version again until
a newer release appears; `sudo filament-kit update` by hand tries it again.

Automatic updates: `sudo filament-kit features on updates` (off by default) checks once a day and installs a
new release on its own; it never reinstalls a version you rolled back from. For a weekly check, set
`"updates": {"schedule": "weekly"}` in `/etc/filament-kit/config.json`. For a private repository, put a GitHub
token in a file only root can read and set `"updates": {"token_file": "/etc/filament-kit/github_token"}`.

**Updating from v0.3.0 to v0.4.0 with Slicer Sync (in this order).**
1. Update the Hub: `sudo filament-kit update`.
2. Update Slicer Sync: run the new `filament-kit-sync-setup-<version>.exe` (Windows) or the new Linux `install.sh`.
3. Close Bambu Studio, so Slicer Sync can run.
4. On the Hub, see what the updates would change: `sudo filament-kit presets updates --all`, then
   accept the ones you want: `sudo filament-kit presets accept-updates --all`. These go to the primary Bambu Studio folder;
   for the other folders use `filament-kit-sync apply-updates --folder ...` on the PC (see
   [Stable and Beta Bambu Studio](#stable-and-beta-bambu-studio-v040)).

The Hub must be updated first: a Slicer Sync that is newer than its Hub logs a warning.

**Existing users: the other Bambu Studio folder.** A record the Hub made before v0.4.0 cannot prove that a preset in the
other folder is its own. So after the upgrade, that folder's accepted updates are listed as "differing" and are **not**
written on their own. To take them, with Bambu Studio closed, run on the PC (use the folder name `status` shows):

```
filament-kit-sync apply-updates --folder BambuStudioBeta-1234567890 --all
```

Use `--dry-run` first to see what would be written. New Slicer presets still arrive in that folder by themselves.

By hand: download the newer `filament-kit-<version>.tar.gz`, unpack it and run `sudo ./install.sh` again.

**Going back from v0.4.1 to v0.4.0.** `sudo filament-kit update --rollback` goes back to the release it replaced. The
Spoolman allow-list (`/etc/systemd/system/spoolman.service.d/kit.conf`) stays in place after the rollback, and v0.4.0
cannot change it: edit it by hand if a range needs adding, then restart Spoolman.

**Going back from v0.4.0 to v0.3.0.** `sudo filament-kit update --rollback` goes back to the release it replaced.

- **Klipper first.** v0.3.0 has no `klipper` Feature and stops at a config that names it. If it is on, run
  `sudo filament-kit features off klipper` before the rollback: the rollback refuses until you do. If it is off, the
  rollback takes the `"klipper"` entry out of `modules` in `/etc/filament-kit/config.json` for you. Your Klipper
  printers stay in `printers.xml` for when you upgrade again.
- **What comes back.** The web app's Claude connector sign-ins, push subscriptions and its pairing come back as they
  were when you upgraded. v0.4.0 copies them into its new folder (`/var/lib/filament-kit-web`) and leaves the originals
  in place. Anything you changed in them while on v0.4.0 stays behind in the new folder.
- **The daily Claude read count.** Going back within a day restarts the day's count of label reads once.
- **Printers.** v0.4.0 also keeps the old-format `printers.json` beside `printers.xml`, so Bambu printers survive the
  rollback.
- **What stays behind.** v0.3.0 works with these left in place, and has no Hub page: the Hub page's service files,
  the `filament-kit-web` user and its folder, and the setup code. To remove them, run as root:

  ```bash
  systemctl disable --now filament-kit-setup.socket
  rm -f /etc/systemd/system/filament-kit-setup.socket /etc/systemd/system/filament-kit-setup@.service \
        /etc/systemd/system/filament-kit-setup-apply.service /etc/systemd/system/filament-kit-setup-job@.service \
        /etc/tmpfiles.d/filament-kit-setup.conf
  rm -rf /run/filament-kit-setup && systemctl daemon-reload
  setfacl -R -x u:filament-kit-web /etc/filament-kit /var/lib/filament-kit
  find /var/lib/filament-kit -type d -exec setfacl -d -x u:filament-kit-web {} +
  rm -rf /var/lib/filament-kit-web && userdel filament-kit-web
  rm -f /etc/filament-kit/setup_code /etc/filament-kit/setup_code.plain /etc/filament-kit/setup_lockout.xml
  ```

  Remove the user's file permissions (the two `setfacl` lines) before the user itself. If you upgrade to v0.4.0 again
  later, removing `/var/lib/filament-kit-web` first makes the upgrade copy the web app's current files again.

**Upgrading a Weigh Station from v0.2.0 to v0.3.0:** the Weigh Station's button flow now needs pairing once. On the Hub run
`sudo filament-kit pair --weigh-station`, then within 10 minutes run `sudo filament-kit weigh-station pair` on the Weigh Station
computer (on a Hub with Weigh Station, both on the same machine) and paste the link. `sudo filament-kit status` and the install
say so until it is done.

## Uninstall

```
sudo filament-kit uninstall
```

This runs the uninstaller of the release copy filament-kit kept. With no kept copy it says where to download the release
file, and you run `sudo ./uninstall.sh` from the unpacked folder.

This removes the programs (Spoolman and the Weigh Station too, with its user and udev rule) but
**keeps** your spools, settings and backups, so a later install picks up where you left off, in the same Setup.
The Weigh Station's computer changes (brltty, ModemManager, sleep, audio) stay; see
[What the installer changes on the computer](#what-the-installer-changes-on-the-computer) to undo them. With
[Remote access](#remote-access) on, it also removes filament-kit's router file, its route and its certbot hook; nginx,
certbot, the certificate and any other routes stay (remove them with `apt` if nothing else uses them). The
router file stays while other routes in `/etc/nginx/mcp.d` need it (it says so). To delete everything, including
all spool data and backups:

```
sudo filament-kit uninstall --purge
```

It asks you to type `purge` to confirm. `--purge` also removes the certbot timer drop-in
`/etc/systemd/system/certbot.timer.d/acme-window.conf` (the `remote.acme_window` setting).
