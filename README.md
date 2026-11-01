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
2. Open the filament-kit app and scan the QR code shown on the computer.
   If the camera can't scan it, pick the server from the list in the app and type the 6-digit pairing code
   instead. The computer also prints the server's **certificate fingerprint** in groups of four characters;
   check that it matches the one the app shows.
3. The code expires after a few minutes. To get a new one, run:

   ```
   sudo filament-kit pair
   ```

## Building the Android app release (owner, Windows PC)

The app is signed with a key that lives only on your PC. Android only installs an update over an installed app
if it is signed with the **same** key, so losing the key means everyone has to uninstall and reinstall the app.

1. Once: `powershell -File tools\android_keystore.ps1`. It creates `%LOCALAPPDATA%\filament-kit\release.jks` and
   a random password stored (encrypted with Windows DPAPI) in `%LOCALAPPDATA%\filament-kit\keystore.pw.dpapi`.
   You never type or see the password. It refuses to overwrite an existing keystore.
2. Each release: `bash tools/make_release.sh` (Git Bash). It builds and signs the app and puts `app/filament-kit.apk`
   and `app/version.txt` into the tarball.
3. **Back up both** `release.jks` **and** `keystore.pw.dpapi` together, somewhere safe and off this PC. A DPAPI
   file only decrypts on this Windows account on this PC, so also make a portable backup:
   `powershell -File tools\android_keystore.ps1 -Export D:\safe\filament-kit-keystore.bak`
   (you type a passphrase; remember it). On another PC restore it with `-Import <file>`.
4. `-Forget` deletes the keystore and the password file (it asks first).

## Everyday commands

Run these in a Terminal on the Ubuntu computer.

| Command | What it does |
|---|---|
| `sudo filament-kit status` | Checks that everything works. Anything failing shows a `fix:` line telling you what to do. |
| `sudo filament-kit pair` | Shows a new QR code to pair another phone. |
| `sudo filament-kit unpair` | Lists paired phones. `sudo filament-kit unpair <id>` removes one. |
| `sudo filament-kit config` | Settings menu: display name, storage locations, Claude model and daily limit, API key, printers. |

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
