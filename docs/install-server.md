# Install the filament-kit server

This guide puts filament-kit on a Linux computer at home. The server keeps your spool list and talks to your
printers. The Android app, the iPhone web app and the PC sync all connect to it, so install it first.

> **Beta.** What is still rough is in [Known gaps](known-gaps.md). If the one command does not suit you, use
> [Install from a downloaded file](#install-from-a-downloaded-file).

## What you need

- **A computer running Ubuntu 24.04 or newer** (desktop or server edition), on your home network, that stays
  on. An old laptop or a mini PC is fine. Other Linux systems (Debian, Fedora, Raspberry Pi OS) are refused.
- **A user account that can use `sudo`.** That is the account you made when you installed Ubuntu.
- **Internet access** during the install. It downloads Ubuntu packages, Python packages and Spoolman.
- **About 15 minutes.**
- Optional: an **Anthropic API key** (it starts with `sk-ant-`), only if you want spool labels read from photos.
  Without one you type spools in yourself, and you can add the key later.
- Good to know: some Bambu printers accept the kit's commands only in **LAN Only** mode with **Developer Mode** on,
  which turns off Bambu Cloud for that printer. The kit cannot tell in advance which printers need it; the app tells
  you if yours does.

The computer must be on the **same network as your printers and phone**: the same router and Wi-Fi, not a
guest network.

## Install with one command

1. On the Ubuntu computer, open **Terminal** (press Ctrl+Alt+T, or search for "Terminal").
2. Copy this line, paste it into the Terminal (Ctrl+Shift+V) and press Enter:

   ```bash
   curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh
   ```

3. Type your password when asked and press Enter. Nothing shows while you type. That is normal.
4. Answer the questions (see [The questions](#the-questions) below).

The first half of the line saves the installer, `get.sh`, into the folder you are in (your home folder, in a new
Terminal); the second half runs it. `get.sh` downloads the newest release, checks its signature and stops without
installing anything if the check fails. Then it runs the installer. You can delete `get.sh` afterwards.

(The piped form, `curl -fsSL .../get.sh | sudo bash`, also works since v0.3.0. Version 0.2.0 could hang at
"Installing system packages" with it; use the two-step form above if you must install that version.)

## Install from a downloaded file

This does the same as the one command, by hand:

1. Open the project's GitHub **Releases** page and download `filament-kit-<version>.tar.gz` (the newest
   version number on the page) into your **Downloads** folder.
2. In Terminal, unpack it and go into the folder. Replace `<version>` with the version number you downloaded:

   ```bash
   cd ~/Downloads
   tar xzf filament-kit-<version>.tar.gz
   cd filament-kit-<version>
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
   errors but are not. Look at the status list at the end instead.

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

5. **Anthropic API key**: only if you answered `y` to question 2. Paste the key and press Enter. Each character
   shows as a `*`.

### Answers on the command line

To skip the questions, give the answers as options after `get.sh` (or after `./install.sh` from an unpacked
release):

| Option | What it does |
|---|---|
| `--mode server`, `--mode station`, `--mode all-in-one` | Installs that mode without asking. |
| `--server <name or IP>` | For `--mode station`: the address of the computer the server runs on. |
| `--modules a,b` | A custom set of modules, for example `--modules spoolman,server,printers`. What they need is added. |
| `--set key=value` | A setting a module in `--modules` needs, for example `--set web.public_url=https://my-server.local/filament`. |
| `--version 0.3.0` | `get.sh` only: that release instead of the newest. |

For example:

```bash
curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh --mode all-in-one
```

## What you see at the end

The installer finishes with a status list, a QR code to download the Android app, and a pairing code:

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

==> Android app: scan this code with the phone's camera to download it
(a large QR code)
It downloads filament-kit.apk from this server (https://192.0.2.10:8710/app.apk); the browser warns about the
kit's own certificate: continue, then open the file to install the app.
Press Enter when the app is installed and you're ready to pair (or s to skip)

==> Pair a phone: open the filament-kit app and scan this code
(a large QR code)

Certificate fingerprint (check it matches the phone):
  7616 34e9 ...
Pairing code: 123456
Expires at 10:07:30 (in 9 min)

Done.   Spoolman: http://my-server.local:7912   Pair another phone: sudo filament-kit pair

Open https://my-server.local:8710/setup  (setup code: 1234-5678)
```

- **No line should start with `FAIL`.** Lines starting with `--` are information. On a new install, "library not
  downloaded", "no build yet" and "PC sync: not set up" are expected.
- The **first QR code** downloads the Android app to the phone (it only appears when this server has the app). Scan
  it with the phone's camera. The installer then waits. Press **Enter** when the app is installed to see the
  **pairing QR code and pairing code**: scan that one **inside the app**, not with the camera. Or type **s** to skip
  pairing. They expire after about 10 minutes. If you are not ready, type **s**; you can pair later from the setup page
  or with `sudo filament-kit pair`, which gives new ones. Without a terminal (a script) the app link is printed as text and
  nothing waits; pair later with `sudo filament-kit pair`.
- Typing a secret (the Access Code, the Anthropic key, the web passphrase) shows a `*` for each character.
- **Spoolman**, where your spool list lives, opens in any web browser at home at the address on the `Done` line
  (`http://<computer name>.local:7912`).

You can run the installer again at any time. It never deletes your spools or settings.

## The setup page (v0.4.0)

From v0.4.0 you can enter the things the installer does not ask for in a web page instead of the Terminal: the
Anthropic key, printers and their Access Codes, the web passphrase, the library token, pairing a phone, PC or
station, NFC reader tokens, and switching modules on or off.

1. Find the address and the code. The installer prints the page's address at the end (`https://<computer
   name>.local:8710/setup`). It prints the **setup code** only when you are at a Terminal. To see them again:

   ```bash
   sudo filament-kit setup-code
   ```

   The setup code is 8 digits, shown like `1234-5678`.
2. Open the address in a browser on a computer or phone **on your home network**. Your browser warns about the
   server's own certificate: continue, as you do for the app download.
3. You can look at everything on the page without the code. **Every change asks for the setup code.**

**Who can reach it.** Only devices on your home network: IPv4 addresses that start with 192.168 or 10 by default
(addresses that start with 172.16 need `web.lan` in the settings), and the server itself. Open it by the server's own name or address; another name is refused. It is not
available from the internet, even when you turned on remote access.

**A wrong code.** Five wrong codes from one device in 10 minutes lock that device out for a while. If wrong codes
come in from many devices (30 in 10 minutes), everyone waits: 10 minutes, doubling each time up to 24 hours. Make
a new code, which also clears the lock: `sudo filament-kit setup-code --new`. The old code stops working.

**What the page can do.**

| Section | What you do there |
|---|---|
| **Anthropic API key** | Set, replace, remove or check the key for AI label reading. The page never shows the key, only whether one is set. |
| **Printers** | Add a Bambu Lab printer by its IP address and Access Code, change a wrong Access Code, test the connection, forget a printer. Printers on the network that announce themselves are listed. With the klipper module on, Klipper printers are listed too (v0.4.1), with **Test** and **Forget** (no Access Code; add them with `sudo filament-kit klipper add`, see [Klipper printers](klipper.md)). |
| **Web passphrase** | Set the passphrase that approves Claude's connector at its sign-in page. |
| **Library token** | Optional. A GitHub token that lets the filament library download from a private repository. |
| **Phones, PC and station** | Make the pairing QR code and code for a phone, or the link for the PC sync or the intake station, and remove a paired device. |
| **NFC readers** | Make a token for a bench NFC reader (shown once) and revoke one. |
| **Modules** | Switch modules on or off and set the addresses they need (for example the web public address). Changes are applied in the background and the page waits while the server restarts. |

Secrets are write-only: after you save one, the page only says it is set. Each change is written to the server's
log (for example `setup: anthropic key replaced from 192.0.2.20`) without the value.

Everything the page does can still be done from the Terminal, as the other sections of this guide describe.
`sudo filament-kit modules apply --no-pair` applies module changes without the pairing screen at the end (the page
uses it).

## After the install

1. **Phone:** [Install the Android app](install-android-app.md) and pair it, or
   [use the web app on an iPhone](install-iphone-web-app.md) (any phone browser; it needs extra setup).
2. **Printer:** the server finds Bambu Lab printers on your network. Open **Printers** in the app and type each
   printer's Access Code (shown on the printer's screen). Steps:
   [Set up a printer](android-app.md#2-set-up-a-printer). To add one by hand: `sudo filament-kit config`, then
   **5) Printers**. More: [user guide, Bambu Lab printers](user-guide.md#bambu-lab-printers).
3. **Slots:** [map the printer's slots](android-app.md#map-slots-needed-before-filament-use-is-taken-off-spools), so that
   filament used in a print is taken off the right spools, then
   [load a spool](android-app.md#load-and-unload-a-spool).
4. **Bambu Studio presets:** install the PC sync on your Windows PC: [user guide, Pair your PC](user-guide.md#pair-your-pc).

## Change what is installed

filament-kit is made of parts called **modules**. To see or change them:

```bash
sudo filament-kit config
```

Type `6` for **Modules**. A menu appears. Each line says what the module needs:

```
 [x]  1 spoolman   Spoolman filament database, run on this machine
 [x]  2 server     App server: pairing, inventory, API, avahi announcement    needs: Spoolman (this machine or a remote one)
 [ ]  3 ai_intake  Claude reads spool labels from photos ...                  needs: server, an Anthropic API key   OPTIONAL AI
 [x]  4 printers   Bambu bridge: discovery, usage, slot mapping, camera       needs: server
 ...
 [ ]  9 web        Browser UI and the MCP endpoint, on top of the server      needs: server
 [ ] 10 remote     Public https name for the web UI (nginx, certbot)          needs: web
```

Move with **Up/Down** (or `k`/`j`; **Home**, **End**, **PgUp**, **PgDn** too) and press **Space** to switch a
module on or off. What it needs is switched on too, and switching one off switches off whatever needs it; the
bottom lines show the row's needs, what the last key did, and the keys. The letters `a`, `s` and `t` pick the
all-in-one, server or station set. Press **Enter** to apply, or `q` or **Esc** to cancel (nothing changes). Then
answer any question it asks (for example `web` asks for its https address), and type `0` at the settings menu
to save and exit. The kit installs and starts what you turned on. Turning a module off never deletes its data.

Without a usable terminal (no terminal, `TERM` unset or `dumb`, or one smaller than 40 by 8) a numbered list
appears instead: type a module's number (or several, like `9 10`) and press Enter to tick or untick it, Enter on an
empty line to apply, `q` to cancel.

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

## Running the server in WSL

Ubuntu inside **WSL** on a Windows PC works, with one catch: WSL's default network mode (**NAT**) hides the Linux
side behind the PC. Printers' announcements don't reach it, so none are found, and your phone and the PC sync
can't connect to it either. Two ways out:

- **Switch WSL to mirrored networking** (Windows 11 22H2 or newer). Create or edit the file `.wslconfig` in your
  Windows user folder (`C:\Users\<you>\.wslconfig`) so it contains:

  ```
  [wsl2]
  networkingMode=mirrored
  ```

  Then, in PowerShell, `wsl --shutdown`, and start Ubuntu again. The Linux side now shares the PC's network
  address: printers are discovered, and phones reach the server at the PC's name or IP address. If Windows
  Firewall is on, allow the kit's ports through it (8710 for the app, 7912 for Spoolman, 5353 for `.local`
  names).
- **Stay in NAT mode and add printers by hand**: `sudo filament-kit config` → **5) Printers** → **add printer**.
  Phones still can't reach a NAT-mode server, so this only suits testing on the PC itself.

Either way, the PC must stay on and awake for the server to answer.

## Common problems

- **`Ubuntu 24.04 or newer is required`**: the computer runs another system or an older Ubuntu. Upgrade it, or
  use another computer.
- **`curl: (22) The requested URL returned error: 404`** from the one command: check that the address was copied
  whole. If it still fails, download `get.sh` from the project's Releases page and run `sudo bash get.sh`, or use
  [Install from a downloaded file](#install-from-a-downloaded-file).
- **The install stops at "Installing system packages" for several minutes**: a new Ubuntu often installs its own
  updates in the background first. The installer waits up to 5 minutes for them. Let it run.
- **A line in the status list starts with `FAIL`**: read the `fix:` line under it and do what it says, then run
  `sudo filament-kit status` again.
- **The setup page says "the setup page only answers the home network"** (v0.4.0): open it from a device on your
  home network, not from the internet or a guest network.
- **The setup page says "open the setup page by the server's own name or address"**: use the `.local` name or the
  IP address, as in [The setup page](#the-setup-page-v040).
- **Locked out of the setup page after wrong codes**: `sudo filament-kit setup-code --new` makes a new code and
  clears the lock.
- **The phone can't find the server**: the phone and the computer must be on the same Wi-Fi network. Type
  `hostname -I` on the computer to see its address. If you
  turned on Ubuntu's firewall (`ufw`), allow the app's port and name lookups:
  `sudo ufw allow 8710/tcp` and `sudo ufw allow 5353/udp`. For Spoolman in a browser, also `sudo ufw allow 7912/tcp`.
- **`sudo filament-kit update` says a printer is mapping or loading**: it does nothing then. Try again when the
  mapping or loading is done.
- **The install stops with "a Spoolman the kit did not install is in /opt/spoolman"**: the kit never replaces a Spoolman
  it did not put there, and nothing was changed. To keep using that one, run `sudo filament-kit modules disable
  spoolman` and set `spoolman_url` in `/etc/filament-kit/config.json` to its address. To let the kit replace the
  Spoolman program (its database is not touched), run `sudo touch /opt/spoolman/.fk-installed` and the same command
  again.
- **Printers don't show up**: the computer must be on the same network as the printers, and a firewall must allow
  UDP ports 2021 and 1990. A server inside WSL or a virtual machine with NAT networking can't see printers (see
  [Running the server in WSL](#running-the-server-in-wsl)): add them by hand with `sudo filament-kit config` →
  **5) Printers** → **add printer**, with the name, IP address, serial number and Access Code from the printer's
  screen.
- **The pairing code expired**: run `sudo filament-kit pair` for a new one.

## Uninstall

```bash
sudo filament-kit uninstall
```

This runs the uninstaller of the release copy the kit kept in `/opt/filament-kit/releases/`. It removes the
programs and keeps your spools, settings and backups, so a later install picks up where you left off.
`sudo filament-kit uninstall --purge` deletes those too; it asks you to type `purge` first. If the kit has no kept
copy, it says where to download the release file; unpack it (`tar xzf filament-kit-<version>.tar.gz`) and run
`sudo ./uninstall.sh` (or with `--purge`) in its folder instead. If you turned on remote
access, nginx and certbot stay installed; remove them with `apt` if nothing else uses them.
