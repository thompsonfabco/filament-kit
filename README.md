# filament-kit

Take photos of a filament spool's label with your phone; filament-kit reads the label and adds the spool to
your inventory (Spoolman). Runs on a small Ubuntu computer on your home network.

## What you need

- A computer running **Ubuntu 24.04 or newer**, on your home network, that stays on.
- An **Anthropic API key** (starts with `sk-ant-`). Keep it handy; the installer asks for it once.
- An Android phone (Android 10 or newer) for the filament-kit app.

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
   - **Display name**: the name the phone app shows for this server. Any text works (spaces, accents);
     press Enter to keep the suggested name. Phones find the server by the computer's own name, not this one.
   - **Default storage locations**: press Enter for yes. Type `n` if you want to name your own racks and
     boxes now (you can also change them later).
   - **Anthropic API key**: paste the key and press Enter. Nothing shows while you type or paste; that is on
     purpose.
5. At the end the installer prints a status list (every line should start with `OK`) and a **QR code** with a
   pairing code underneath.

The installer takes a few minutes. You can run it again at any time; it never deletes your spools or
settings.

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

## Building the Android app release (owner, Windows PC)

The app is signed with a key that lives only on your PC. Android only installs an update over an installed app
if it is signed with the **same** key, so losing the key means everyone has to uninstall and reinstall the app.

1. Once: `powershell -ExecutionPolicy Bypass -File tools\android_keystore.ps1`. It creates
   `%LOCALAPPDATA%\filament-kit\release.jks` and a random password stored (encrypted with Windows DPAPI) in
   `%LOCALAPPDATA%\filament-kit\keystore.pw.dpapi`. You never type or see the password. It refuses to overwrite an
   existing keystore. It uses `keytool` from `JAVA_HOME` if set, otherwise from `G:\Android\jdk-21.0.13+9`.
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
| `sudo filament-kit unpair` | Lists paired phones. `sudo filament-kit unpair <id>` removes one. |
| `sudo filament-kit config` | Settings menu: display name, storage locations, Claude model and daily limit, API key, printers. |
| `sudo filament-kit printer map <serial>` | Maps a printer's AMS slots (see [Map slots](#map-slots)), printing each step. |
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
  the next mapping run, or the server when it starts and the printer is idle, puts those slots back before
  doing anything else. A mapping refuses to start while that restore is not confirmed.
- Test colours are near-pure reds, `FAnn00FF` (the first two digits F7 to FE). Mapping picks test colours that
  no slot holds, so a real spool of such a red is mapped like any other. If the note file cannot be read,
  mapping says so: set the filament of any slot showing such a red again (on the printer or in Bambu Studio),
  then delete the file and map again.
- The calibration job is stopped at once if the printer starts heating or loading a filament, and a filament
  left loaded in the toolhead afterwards is reported.
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

## Update

Download the newer `filament-kit-<version>.tar.gz`, unpack it as in step 2 above and run `sudo ./install.sh`
again. It keeps your spools, settings, key and paired phones and asks no questions.

## Uninstall

From the unpacked folder:

```
sudo ./uninstall.sh
```

This removes the programs but **keeps** your spools, settings and backups, so a later install picks up where
you left off. To delete everything, including all spool data and backups:

```
sudo ./uninstall.sh --purge
```

It asks you to type `purge` to confirm.
