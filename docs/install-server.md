# Install the Hub

This guide puts Spoolwarden on a Linux computer at home. That computer is the Hub: it keeps your spool list and talks to your
printers. The app (Android), the web app on an iPhone and Slicer Sync all connect to it, so install it first.

> **Beta.** What is still rough is in [Known gaps](known-gaps.md). If the one command does not suit you, use
> [Install from a downloaded file](#install-from-a-downloaded-file).

## What you need

- **A computer running Ubuntu 24.04 or newer** (desktop or server edition), on your home network, that stays
  on. An old laptop or a mini PC is fine. Other Linux systems (Debian, Fedora, Raspberry Pi OS) are refused.
- **A user account that can use `sudo`.** That is the account you made when you installed Ubuntu.
- **Internet access** during the install. It downloads Ubuntu packages, Python packages and Spoolman.
- **About 15 minutes.**
- Optional: an **Anthropic API key** (it starts with `sk-ant-`), only if you want the Label Reader to read spool labels from photos.
  Without one you type spools in yourself, and you can add the key later.
- Good to know: some Bambu printers accept Spoolwarden's commands only in **LAN Only** mode with **Developer Mode** on,
  which turns off Bambu Cloud for that printer. Spoolwarden cannot tell in advance which printers need it; the app tells
  you if yours does.

The computer must be on the **same network as your printers and phone**: the same router and Wi-Fi, not a
guest network.

## Install with one command

1. On the Ubuntu computer, open **Terminal** (press Ctrl+Alt+T, or search for "Terminal").
2. Copy this line, paste it into the Terminal (Ctrl+Shift+V) and press Enter:

   ```bash
   curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh
   ```

   If it says `curl` is not found, use this line instead:

   ```bash
   wget -q https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh
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

1. **Setup** (the installer asks "Install mode")

   ```
   Install mode: 1) server 2) station 3) all-in-one 4) custom [1]
   ```

   Press Enter for choice 1, the **Hub**, the usual choice. Choose 3, **Hub with Weigh Station**, if a USB scale and a tag reader are
   plugged into this computer. Choice 2, **Weigh Station only**, is only for a second computer that has the scale and reader, when
   the Hub runs somewhere else; it then asks for the Hub's address. Choice 4, **custom**, shows a checklist of
   every Feature (see [Change what is installed](#change-what-is-installed)).

2. **Label Reader (Cloud)**

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

   This is the name the app shows for this Hub. Press Enter to keep the computer's name, or type any name.

4. **Storage locations**

   ```
   Use the default storage locations? [Y/n]:
   ```

   Press Enter for yes. The defaults are **Sealed stock**, **Rack 1**, **Storage box** and **Overflow**. You can
   rename them later in `sudo spoolwarden config` under **Storage locations**.

5. **Anthropic API key**: only if you answered `y` to question 2. Paste the key and press Enter. Each character
   shows as a `*`.

### Answers on the command line

To skip the questions, give the answers as options after `get.sh` (or after `./install.sh` from an unpacked
release):

| Option | What it does |
|---|---|
| `--mode hub`, `--mode weigh-station`, `--mode hub-with-weigh-station` | Installs that Setup (Hub, Weigh Station only, Hub with Weigh Station) without asking. |
| `--hub <name or IP>` | For `--mode weigh-station`: the address of the computer the Hub runs on. |
| `--modules a,b` | A custom set of Features, for example `--modules spoolman,server,printers`. What they need is added. |
| `--set key=value` | A setting a Feature in `--modules` needs, for example `--set web.public_url=https://my-server.local/filament`. |
| `--version 0.3.0` | `get.sh` only: that release instead of the newest. |

For example:

```bash
curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh --mode hub-with-weigh-station
```

## What you see at the end

The installer finishes with a status list, a QR code to download the app (Android), and a pairing code:

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

Certificate fingerprint (the phone asks for two groups of it):
  7616 34e9 ...
Pairing code: 123456
Expires at 10:07:30 (in 9 min)

Done.   Spoolman: http://my-server.local:7912   Pair another phone: sudo spoolwarden pair

Open https://my-server.local:8710/setup  (setup code: 1234-5678)
```

- **No line should start with `FAIL`.** Lines starting with `--` are information. On a new install,
  `library not downloaded`, `no build yet` and `PC sync: not set up` are expected.
- The **first QR code** downloads the app to the phone (it only appears when this Hub has the app). Scan
  it with the phone's camera. The installer then waits. Press **Enter** when the app is installed to see the
  **pairing QR code and pairing code**: scan that one **inside the app**, not with the camera. Or type **s** to skip
  pairing. They expire after about 10 minutes. If you are not ready, type **s**; you can pair later from the Hub page
  or with `sudo spoolwarden pair`, which gives new ones. Without a terminal (a script) the app link is printed as text and
  nothing waits; pair later with `sudo spoolwarden pair`.
- Typing a secret (the Access Code, the Anthropic key, the web passphrase) shows a `*` for each character.
- **Spoolman**, where your spool list lives, opens in any web browser at home at the address on the `Done` line
  (`http://<computer name>.local:7912`).

You can run the installer again at any time. It never deletes your spools or settings.

<a id="the-setup-page-v040"></a>
## The Hub page (v0.4.0)

From v0.4.0 you can enter the things the installer does not ask for in a web page instead of the Terminal: the
Anthropic key, printers and their Access Codes, the web passphrase, the Catalog token, pairing a phone, a PC or a
Weigh Station, Tag Reader tokens, and switching Features on or off.

1. Find the address and the code. The installer prints the page's address at the end (`https://<computer
   name>.local:8710/setup`). It prints the **setup code** only when you are at a Terminal. To see them again:

   ```bash
   sudo spoolwarden setup-code
   ```

   The setup code is 8 digits, shown like `1234-5678`.
2. Open the address in a browser on a computer or phone **on your home network**. Your browser warns about the
   Hub's own certificate: continue, as you do for the app download.
3. You can look at everything on the page without the code. **Every change asks for the setup code**, unless you
   chose to trust that computer after the code worked (the user guide's Hub page section says how, and how to revoke).

**Who can reach it.** Only devices on your home network: IPv4 addresses that start with 192.168 or 10 by default
(addresses that start with 172.16 need `web.lan` in the settings), and the Hub itself. Open it by the Hub's own name or address, or by a local name your own DNS gives it (one word, or one ending in .local, .lan, .home.arpa, or the network's own domain that the Hub's DNS settings name). Any other name is refused unless you add it in Settings (Network and addresses: Names for this page), since a public name pointing here is how DNS rebinding would reach the page. It is not
available from the internet, even when you turned on remote access.

**A wrong code.** Five wrong codes from one device in 10 minutes lock that device out for a while. If wrong codes
come in from many devices (30 in 10 minutes), everyone waits: 10 minutes, doubling each time up to 24 hours. Make
a new code, which also clears the lock: `sudo spoolwarden setup-code --new`. The old code stops working; computers
you trusted stay trusted (the command says so and how many), unless you add `--revoke-trusted`.

**What the page can do.**

| Section | What you do there |
|---|---|
| **Anthropic API key** | Set, replace, remove or check the key for the Label Reader's Cloud engine. The page never shows the key, only whether one is set. |
| **Printers** | **Add a printer** (v0.4.3): choose the type, then give an IP address or a name. A Bambu Lab printer also needs its Access Code; a Klipper printer (with the Klipper printers Feature on) needs none, only an optional Moonraker API key (see [Klipper printers](klipper.md)). Also change a wrong Access Code, test the connection, forget a printer. Printers on the network that announce themselves are listed. |
| **Web passphrase** | Set the passphrase that approves Claude's connector at its sign-in page. |
| **Catalog token** | Optional. A GitHub token that lets the Filament Catalog download from a private repository. |
| **Paired devices** | Make the pairing QR code and code for a phone, or the link for Slicer Sync or the Weigh Station, and remove a paired device. |
| **Tag Readers** | Make a token for a Tag Reader (shown once) and revoke one. |
| **Features** | Switch Features on or off and set the addresses they need (for example the web public address). Changes are applied in the background and the page waits while the Hub restarts. |

Secrets are write-only: after you save one, the page only says it is set. Each change is written to the Hub's
log (for example `setup: anthropic key replaced from 192.0.2.20`) without the value.

### The sections (v0.4.3)

From v0.4.3 the page has sections: **Overview**, **Features**, **Printers**, **Devices**, **Settings** and **Updates**
(`https://<computer name>.local:8710/setup#updates` opens one directly). v0.5.0 adds **Slicer presets** and **Logs**. **Flash a device** (between **Settings** and **Updates**) writes Spoolwarden's firmware to a Tag Reader or a Weigh Station display over USB ([the user guide](user-guide.md#flash-a-device)). The table above says what is on **Printers**,
**Devices** and **Settings**.

- **Overview.** The installed version and Setup, with a note and a link to **Updates** when a newer release exists. Under
  it are the same checks as `sudo spoolwarden status`, each marked **OK**, **needs a look** or **note**, with a
  `Fix:` line for the ones that need a look and a **Make the fields** button where Spoolman is missing fields the
  Hub needs. **Still to do** lists what is missing: a setup code, printers, a paired phone, the Anthropic key (when the Label Reader's Cloud engine is on), the web passphrase (when Web access is on), each with a link to its tab. Addresses and
  serial numbers are hidden. Type the setup code to see them, and the Weigh Station's
  pairing when the Weigh Station is on this computer (without the code it says "not checked").
- **Devices.** From v0.5.0, with Web access on, it also shows the address of the web app (`<address>/intake`),
  its QR code and how to add it to an iPhone's home screen. See
  [use the web app on an iPhone](install-iphone-web-app.md) for the setup Safari needs.
- **Features.** **Setup** buttons set a ready-made set of Features. Pick one to see what will be on afterwards and what it
  asks for, then **Apply**. Weigh Station only has no Hub and so no Hub page: its button is greyed, and you set it on the
  Weigh Station with `sudo spoolwarden features setup weigh-station --hub <address>`. Below the Setups, Features are switched on or off
  one by one, as before. The changes are applied in a background job with a live log (see below).
- **Slicer presets.** The last preset build and any problems with it, **Build now**, and **Bring back deleted presets**. Each
  product line can have its Bambu Studio and Orca Slicer parents set, picked from what Slicer Sync reported. **Show what
  would change** lists the pending updates, and **Accept these** accepts exactly that list: if a newer build has
  come since, it asks you to look again. Slicer Sync writes accepted updates at its next run, after its backup. Nothing
  else here replaces a preset in your slicers. Each of these needs the setup code.
- **Settings** (v0.5.0). **General** changes the display name, storage locations, the Claude model, the reads per day and
  the Weigh Station's voice, each with the setup code. Changing the model or the reads per day restarts the Hub. With an
  external Spoolman it changes that address too, once the new one has answered. **Remote access**, with the remote Feature
  on, shows the firewall rules and gets the certificate.
  **Filament Catalog** shows its version and last check, with **Update now**, a button to go back
  to the version before, and a box to add your own entry. Each takes the setup code, and the first two run as
  background jobs.
- **Backups** (v0.5.0, on **Settings**). **Back up now**, the list of backups with **Download** as a zip, how many days
  to keep, and **Restore** from a backup zip, also onto a freshly installed machine. See the
  [user guide, Backups and restore](user-guide.md#backups-and-restore-v050).
- **Updates.** Shows the installed and the latest release, when it was last checked, and the release notes of the
  latest. **Check now** asks GitHub for the latest release and needs the setup code; the page itself cannot reach GitHub, so
  a background job does it. **Update to <version>** asks you to confirm: Spoolwarden stops while it installs and starts
  again by itself. **Roll back to <version>** goes back to the release the current one replaced and keeps your
  settings and data. Either is greyed, with the reason shown, while a printer is mapping or loading.
- **Logs** (v0.5.0). The last lines of one service of a Feature that is on, with the setup code, because logs hold
  addresses and serial numbers.
- **Background jobs.** Applying Features, updating, rolling back and checking run as a separate service, so they carry on
  when the Hub service restarts. The **Background job** panel shows the log, says "The Hub is restarting" while it is down, and after an update the page reloads itself into the new version. The log hides
  addresses and serial numbers; **Show the whole log** (with the setup code) shows them.

Everything the page does can still be done from the Terminal, as the other sections of this guide describe.
`sudo spoolwarden features apply --no-pair` applies Feature changes without the pairing screen at the end (the page
uses it).

## After the install

1. **Phone:** [Install the app](install-android-app.md) and pair it, or
   [use the web app on an iPhone](install-iphone-web-app.md) (any phone browser; it needs extra setup).
2. **Printer:** the Hub finds Bambu Lab printers on your network. Open **Printers** in the app and type each
   printer's Access Code (shown on the printer's screen). Steps:
   [Set up a printer](android-app.md#2-set-up-a-printer). To add one by hand: `sudo spoolwarden printer add`. More: [user guide, Bambu Lab printers](user-guide.md#bambu-lab-printers).
3. **Slots:** [map the printer's slots](android-app.md#map-slots-needed-before-filament-use-is-taken-off-spools), so that
   filament used in a print is taken off the right spools, then
   [load a spool](android-app.md#load-and-unload-a-spool).
4. **Slicer presets:** install Slicer Sync on your Windows PC: [user guide, Pair your PC](user-guide.md#pair-your-pc).

## Change what is installed

Spoolwarden is made of parts called **Features**. To see or change them:

```bash
sudo spoolwarden features menu
```

A checklist appears. Each line says what the Feature needs:

```
 [x]  1 spoolman   Spoolman filament database, run on this machine
 [x]  2 server     App server: pairing, inventory, API, avahi announcement    needs: Spoolman (this machine or a remote one)
 [ ]  3 ai_intake  Claude reads spool labels from photos ...                  needs: server, an Anthropic API key   OPTIONAL AI
 [x]  4 printers   Bambu bridge: discovery, usage, slot mapping, camera       needs: server
 ...
 [ ]  9 web        Browser UI and the MCP endpoint, on top of the server      needs: server
 [ ] 10 remote     Public https name for the web UI (nginx, certbot)          needs: web
```

Move with **Up/Down** (or `k`/`j`; **Home**, **End**, **PgUp**, **PgDn** too) and press **Space** or **Enter** to
switch a Feature on or off. What it needs is switched on too, and switching one off switches off whatever needs it; the
bottom lines show the row's needs, what the last key did, and the keys. The letters `h`, `w` and `b` pick the
Hub, Weigh Station only or Hub with Weigh Station Setup. Press `s` to apply (Enter never applies), or `q` or **Esc** to cancel (nothing changes). Then
answer any question it asks (for example Web access asks for its https address). Spoolwarden installs and starts what you turned on. Turning a Feature off never deletes its data.

Without a usable terminal (no terminal, `TERM` unset or `dumb`, or one smaller than 40 by 8) a numbered list
appears instead: type a Feature's number (or several, like `9 10`) and press Enter to tick or untick it, `s` to apply, `q` to
cancel.

To use the Label Reader's Cloud engine later: in `sudo spoolwarden config`, enter the API key under **Label Reader**, then run `sudo spoolwarden features menu` and tick
Label Reader: Cloud (Claude).

## Everyday commands

| Command | What it does |
|---|---|
| `sudo spoolwarden status` | Checks everything. A failing line has a `fix:` line under it. |
| `sudo spoolwarden pair` | New QR code and pairing code for another phone. |
| `sudo spoolwarden devices` | Lists paired phones and PCs; `sudo spoolwarden devices forget <device>` removes one. |
| `sudo spoolwarden config` | Settings: display name, storage, API key, backups, addresses. |
| `sudo spoolwarden update` | Installs the newest release and keeps your data (`--check` only looks, `--rollback` goes back). |

Every command is in the [user guide](user-guide.md#everyday-commands).

<a id="running-the-server-in-wsl"></a>
## Running the Hub in WSL

Ubuntu inside **WSL** on a Windows PC works, with one catch: WSL's default network mode (**NAT**) hides the Linux
side behind the PC. Printers' announcements don't reach it, so none are found, and your phone and Slicer Sync
can't connect to it either. Two ways out:

- **Switch WSL to mirrored networking** (Windows 11 22H2 or newer). Create or edit the file `.wslconfig` in your
  Windows user folder (`C:\Users\<you>\.wslconfig`) so it contains:

  ```
  [wsl2]
  networkingMode=mirrored
  ```

  Then, in PowerShell, `wsl --shutdown`, and start Ubuntu again. The Linux side now shares the PC's network
  address: printers are discovered, and phones reach the Hub at the PC's name or IP address. If Windows
  Firewall is on, allow Spoolwarden's ports through it (8710 for the app, 7912 for Spoolman, 5353 for `.local`
  names).
- **Stay in NAT mode and add printers by hand**: `sudo spoolwarden printer add`.
  Phones still can't reach a NAT-mode Hub, so this only suits testing on the PC itself.

Either way, the PC must stay on and awake for the Hub to answer.

## Common problems

- **`Ubuntu 24.04 or newer is required`**: the computer runs another system or an older Ubuntu. Upgrade it, or
  use another computer.
- **`curl: (22) The requested URL returned error: 404`** from the one command: check that the address was copied
  whole. If it still fails, download `get.sh` from the project's Releases page and run `sudo bash get.sh`, or use
  [Install from a downloaded file](#install-from-a-downloaded-file).
- **The install stops at "Installing system packages" for several minutes**: a new Ubuntu often installs its own
  updates in the background first. The installer waits up to 5 minutes for them. Let it run.
- **A line in the status list starts with `FAIL`**: read the `fix:` line under it and do what it says, then run
  `sudo spoolwarden status` again.
- **The Hub page says "This Hub page only opens from the home network"** (v0.4.0): open it from a device on your
  home network, not from the internet or a guest network.
- **The Hub page says "Open the Hub page by the Hub's own name or address"**: it does not list them (anyone
  can see this page). `sudo spoolwarden setup-code` shows its address; use the Hub's name or IP address, or add
  your name in Settings (Network and addresses: Names for this page).
  A local name of your own DNS (one word, `.local`, `.lan`, `.home.arpa`, or the network's own domain) that points at the Hub
  works without adding it.
- **Locked out of the Hub page after wrong codes**: `sudo spoolwarden setup-code --new` makes a new code and
  clears the lock.
- **The phone can't find the Hub**: the phone and the computer must be on the same Wi-Fi network. Type
  `hostname -I` on the computer to see its address. If you
  turned on Ubuntu's firewall (`ufw`), allow the app's port and name lookups:
  `sudo ufw allow 8710/tcp` and `sudo ufw allow 5353/udp`. For Spoolman in a browser, also `sudo ufw allow 7912/tcp`.
- **`sudo spoolwarden update` says a printer is mapping or loading**: it does nothing then. Try again when the
  mapping or loading is done.
- **`a Spoolman the kit did not install is in /opt/spoolman`**: Spoolwarden never replaces a Spoolman
  it did not put there, and nothing was changed. To keep using that one, run `sudo spoolwarden features off spoolman` and set `spoolman_url` in `/etc/filament-kit/config.json` to its address. To let Spoolwarden replace the
  Spoolman program (its database is not touched), run `sudo touch /opt/spoolman/.fk-installed` and the same command
  again.
- **Printers don't show up**: the computer must be on the same network as the printers, and a firewall must allow
  UDP ports 2021 and 1990. A Hub inside WSL or a virtual machine with NAT networking can't see printers (see
  [Running the Hub in WSL](#running-the-server-in-wsl)): add them by hand with `sudo spoolwarden printer add`, with the name, IP address, serial number and Access Code from the printer's
  screen.
- **The pairing code expired**: run `sudo spoolwarden pair` for a new one.

## Uninstall

```bash
sudo spoolwarden uninstall
```

This runs the uninstaller of the release copy Spoolwarden kept in `/opt/filament-kit/releases/`. It removes the
programs and keeps your spools, settings and backups, so a later install picks up where you left off.
`sudo spoolwarden uninstall --purge` deletes those too; it asks you to type `purge` first. If there is no kept
copy, it says where to download the release file; unpack it (`tar xzf filament-kit-<version>.tar.gz`) and run
`sudo ./uninstall.sh` (or with `--purge`) in its folder instead. If you turned on remote
access, nginx and certbot stay installed; remove them with `apt` if nothing else uses them.
