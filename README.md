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
   - **Server name**: press Enter to keep the suggested name.
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
   instead.
3. The code expires after a few minutes. To get a new one, run:

   ```
   sudo filament-kit pair
   ```

## Everyday commands

Run these in a Terminal on the Ubuntu computer.

| Command | What it does |
|---|---|
| `sudo filament-kit status` | Checks that everything works. Anything failing shows a `fix:` line telling you what to do. |
| `sudo filament-kit pair` | Shows a new QR code to pair another phone. |
| `sudo filament-kit unpair` | Lists paired phones. `sudo filament-kit unpair <id>` removes one. |
| `sudo filament-kit config` | Settings menu: server name, storage locations, Claude model and daily limit, API key. |

Your spool inventory (Spoolman) is also in a web browser on any computer at home:
`http://<server name>.local:7912`

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
