# Install the filament-kit server

This guide puts filament-kit on a Linux computer at home. The server keeps your spool list and talks to your
printers. The Android app, the iPhone web app and the PC sync all connect to it, so install it first.

> **Beta.** The one-command install below needs a public repository, and the repository is private for now. Until
> it goes public, use [While the repository is private](#while-the-repository-is-private) or
> [Install from a downloaded file](#install-from-a-downloaded-file) (signed in to GitHub). What else is still rough
> is in [Known gaps](known-gaps.md).

## What you need

- **A computer running Ubuntu 24.04 or newer** (desktop or server edition), on your home network, that stays
  on. An old laptop or a mini PC is fine. Other Linux systems (Debian, Fedora, Raspberry Pi OS) are refused.
- **A user account that can use `sudo`.** That is the account you made when you installed Ubuntu.
- **Internet access** during the install. It downloads Ubuntu packages, Python packages and Spoolman.
- **About 15 minutes.**
- Optional: an **Anthropic API key** (it starts with `sk-ant-`), only if you want spool labels read from photos.
  Without one you type spools in yourself, and you can add the key later.

The computer must be on the **same network as your printers and phone**: the same router and Wi-Fi, not a
guest network.

## Install with one command

1. On the Ubuntu computer, open **Terminal** (press Ctrl+Alt+T, or search for "Terminal").
2. Copy this line, paste it into the Terminal (Ctrl+Shift+V) and press Enter:

   ```bash
   curl -fsSL https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh | sudo bash
   ```

3. Type your password when asked and press Enter. Nothing shows while you type. That is normal.
4. Answer the questions (see [The questions](#the-questions) below).

The command downloads the newest release, checks its signature and stops without installing anything if the
check fails. Then it runs the installer.

## While the repository is private

The command above only works once the repository is public. Until then you need a GitHub account that can see
the repository and a GitHub token that can read it:

1. Get `get.sh` from the newest release, for example with the GitHub CLI (`sudo apt install gh`, then
   `gh auth login` once):

   ```bash
   gh release download -R thompsonfabco/filament-kit -p get.sh
   ```

2. Save the token in a file only you can read, for example `~/fk-token` (`chmod 600 ~/fk-token`).
3. Run the installer with that file:

   ```bash
   sudo bash get.sh --token-file ~/fk-token
   ```

The token is never shown on screen and is only sent to GitHub.

## Install from a downloaded file

This does the same as the one command, by hand:

1. Open the project's GitHub **Releases** page and download `filament-kit-<version>.tar.gz`, for example
   `filament-kit-0.2.0.tar.gz`, into your **Downloads** folder.
2. In Terminal, unpack it and go into the folder. Use the version number you downloaded:

   ```bash
   cd ~/Downloads
   tar xzf filament-kit-0.2.0.tar.gz
   cd filament-kit-0.2.0
   ```

3. Start the installer:

   ```bash
   sudo ./install.sh
   ```

This way skips the signature check that the one command does.

## The questions

The installer first installs two small packages (`==> Installing system packages`), then asks these one at a
time. For a first install, pressing **Enter** at every question is fine.

1. **Install mode**

   ```
   Install mode: 1) server 2) station 3) all-in-one 4) custom [1]
   ```

   Press Enter for **server**, the usual choice. Choose **all-in-one** (3) if a USB scale and an NFC reader are
   plugged into this computer. **station** (2) is only for a second computer that has the scale and reader, when
   the server runs somewhere else; it then asks for the server's address. **custom** (4) shows a checklist of
   every part (see [Change what is installed](#change-what-is-installed)).

2. **AI label reading**

   ```
   Read spool labels from photos with Claude (ai_intake; needs an Anthropic API key)? [y/N]
   ```

   Press Enter for **no**. You then add spools by typing them in, which works fine. Type `y` only if you have an
   Anthropic API key.

   The installer now installs packages and Spoolman. Several screens of text scroll past. Some lines look like
   errors but are not, for example `id: 'spoolman': no such user` on a first install. Look at the status list
   at the end instead.

3. **Display name**

   ```
   Display name shown in the phone app (any text) [<computer name>]:
   ```

   This is the name the app shows for this server. Press Enter to keep the computer's name, or type any name.

4. **Storage locations**

   ```
   Use the default storage locations? [Y/n]:
   ```

   Press Enter for yes. The defaults are **Sealed stock**, **Rack 1**, **Storage box** and **Overflow**. You can
   rename them later in `sudo filament-kit config` → **2) storage**.

5. **Anthropic API key**: only if you answered `y` to question 2. Paste the key and press Enter. Nothing shows
   while you paste. That is on purpose.

### Answers on the command line

To skip the questions, give the answers as options. With the one command they go after `sudo bash -s --`; with
`get.sh` or `./install.sh`, after the file name:

| Option | What it does |
|---|---|
| `--mode server`, `--mode station`, `--mode all-in-one` | Installs that mode without asking. |
| `--server <name or IP>` | For `--mode station`: the address of the computer the server runs on. |
| `--modules a,b` | A custom set of modules, for example `--modules spoolman,server,printers`. What they need is added. |
| `--set key=value` | A setting a module in `--modules` needs, for example `--set web.public_url=https://my-server.local/filament`. |
| `--version 0.2.0` | One command and `get.sh` only: that release instead of the newest. |

For example:

```bash
curl -fsSL https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh | sudo bash -s -- --mode all-in-one
```

## What you see at the end

The installer finishes with a status list, a QR code and a pairing code:

```
==> Status
OK   service spoolman active
OK   service filament-kit active
OK   filament-kit API answering at https://127.0.0.1:8710/api/info
OK   Spoolman reachable at http://127.0.0.1:7912 (v0.27.0)
OK   certificate present, fingerprint 7616...2eb8
--   display name: my-server
--   paired devices: 0
...
--   PC sync: not set up (see README: Pair your PC)

==> Pair a phone: open the filament-kit app and scan this code
(a large QR code)

Certificate fingerprint (check it matches the phone):
  7616 34e9 ...
Pairing code: 123456
Expires at 10:07:30 (in 9 min)

Done.   Spoolman: http://my-server.local:7912   Pair another phone: sudo filament-kit pair
```

- **No line should start with `FAIL`.** Lines starting with `--` are information. On a new install, "library not
  downloaded", "no build yet" and "PC sync: not set up" are expected.
- The **QR code** and the **pairing code** are for the Android app. They expire after about 10 minutes. If you
  are not ready, ignore them and run `sudo filament-kit pair` later to get new ones.
- **Spoolman**, where your spool list lives, opens in any web browser at home at the address on the `Done` line
  (`http://<computer name>.local:7912`).

You can run the installer again at any time. It never deletes your spools or settings.

## Next steps

- **Android phone:** [Install the Android app](install-android-app.md) and pair it.
- **iPhone (or any phone browser):** [Use the web app on an iPhone](install-iphone-web-app.md). It needs extra setup.
- **Printers:** the server finds Bambu Lab printers on your network. Open **Printers** in the app and type each
  printer's Access Code (shown on the printer's screen). To add one by hand: `sudo filament-kit config`, then
  **5) Printers**. Details: [user guide, Bambu Lab printers](user-guide.md#bambu-lab-printers).
- **Bambu Studio presets:** install the PC sync on your Windows PC: [user guide, Pair your PC](user-guide.md#pair-your-pc).

## Change what is installed

filament-kit is made of parts called **modules**. To see or change them:

```bash
sudo filament-kit config
```

Type `6` for **Modules**. A checklist appears. Each line says what the module needs:

```
 [x]  1 spoolman   Spoolman filament database, run on this machine
 [x]  2 server     App server: pairing, inventory, API, avahi announcement    needs: Spoolman (this machine or a remote one)
 [ ]  3 ai_intake  Claude reads spool labels from photos ...                  needs: server, an Anthropic API key   OPTIONAL AI
 [x]  4 printers   Bambu bridge: discovery, usage, slot mapping, camera       needs: server
 ...
 [ ]  9 web        Browser UI and the MCP endpoint, on top of the server      needs: server
 [ ] 10 remote     Public https name for the web UI (nginx, certbot)          needs: web
```

Type a module's number (or several, like `9 10`) and press Enter to tick or untick it. What it needs is ticked
too, and unticking one that others need asks about those. Press Enter on an empty line to apply, answer any
question it asks (for example `web` asks for its https address), then type `0` at the settings menu to save
and exit. The kit installs and starts what you turned on. Turning a module off never deletes its data.

To use AI label reading later: in `sudo filament-kit config`, type `4` to enter the API key, then `6` and tick
`ai_intake`.

## Everyday commands

| Command | What it does |
|---|---|
| `sudo filament-kit status` | Checks everything. A failing line has a `fix:` line under it. |
| `sudo filament-kit pair` | New QR code and pairing code for another phone. |
| `sudo filament-kit unpair` | Lists paired phones and PCs; `sudo filament-kit unpair <id>` removes one. |
| `sudo filament-kit config` | Settings: display name, storage, API key, printers, modules. |
| `sudo filament-kit update` | Installs the newest release and keeps your data (`--check` only looks, `--rollback` goes back). |

Every command is in the [user guide](user-guide.md#everyday-commands).

## Common problems

- **`Ubuntu 24.04 or newer is required`**: the computer runs another system or an older Ubuntu. Upgrade it, or
  use another computer.
- **`curl: (22) The requested URL returned error: 404`** from the one command: the repository is still private.
  See [While the repository is private](#while-the-repository-is-private).
- **The install stops at "Installing system packages" for several minutes**: a new Ubuntu often installs its own
  updates in the background first. The installer waits up to 5 minutes for them. Let it run.
- **A line in the status list starts with `FAIL`**: read the `fix:` line under it and do what it says, then run
  `sudo filament-kit status` again.
- **The phone can't find the server**: the phone and the computer must be on the same Wi-Fi network. If you
  turned on Ubuntu's firewall (`ufw`), allow the app's port and name lookups:
  `sudo ufw allow 8710/tcp` and `sudo ufw allow 5353/udp`. For Spoolman in a browser, also `sudo ufw allow 7912/tcp`.
- **Printers don't show up**: the computer must be on the same network as the printers, and a firewall must allow
  UDP ports 2021 and 1990. A server inside WSL or a virtual machine with NAT networking can't see printers: add
  them by hand with `sudo filament-kit config` → **5) Printers**.
- **The pairing code expired**: run `sudo filament-kit pair` for a new one.

## Uninstall

The uninstaller is in the release file. If you installed with the one command, the kit kept a copy of that file;
unpack it into your home folder first (use your version number; `ls /opt/filament-kit/releases` shows it):

```bash
cd ~
tar xzf /opt/filament-kit/releases/0.2.0/filament-kit-0.2.0.tar.gz
cd filament-kit-0.2.0
```

If you installed from a downloaded file, go into that unpacked folder instead. Then:

```bash
sudo ./uninstall.sh
```

This removes the programs and keeps your spools, settings and backups, so a later install picks up where you left
off. `sudo ./uninstall.sh --purge` deletes those too; it asks you to type `purge` first. If you turned on remote
access, nginx and certbot stay installed; remove them with `apt` if nothing else uses them.
