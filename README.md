`curl -fsSL https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh | sudo bash`

# filament-kit

That one command installs filament-kit on an Ubuntu 24.04 (or newer) computer on your home network, after
checking the release's signature, and asks a few questions (install mode, display name, AI label reading). It
works once the repository is public. While it is private: get `get.sh` with a GitHub token that can read the
repository (for example `gh release download -R thompsonfabco/filament-kit -p get.sh`), save the token in a file
only you can read and run `sudo bash get.sh --token-file <file>` (the token is never shown and only goes to
GitHub).

Options go after `sudo bash -s --` (or after `get.sh`): `--mode server|station|all-in-one`, `--server <address>`
for a station, `--modules a,b` with `--set key=value` for the settings a module needs (for example
`--modules spoolman,server,printers,web --set web.public_url=https://filament.example.com/filament`), or
`--version 0.3.0`. Without a terminal it asks nothing and installs the `server` mode unless told otherwise.

## What it does

filament-kit keeps your filament spools in [Spoolman](https://github.com/Donkie/Spoolman) and connects them to
your Bambu Lab printers:

- Add spools from the Android app or the phone web app: type them in, or pick a filament you already have.
  Reading the label from a photo is **optional AI** (your own Anthropic API key); everything else works without it.
- Load a spool into a printer slot from the app, or tap its NFC tag on the bench [reader](#the-reader): the
  printer gets the right filament setting and Spoolman the spool's new location. Filament used in a print comes
  off the right spools.
- Build a Bambu Studio (and, if you like, Orca Slicer) preset for every filament line you own; the PC sync
  installs them on your Windows PC.
- Weigh a spool and read its tag at an intake station (USB scale and NFC reader), back up every night, and
  update from signed releases (by hand, or daily with the `updates` module).

The full guide (every module, the station, presets, the Claude connector, remote access) is
[docs/user-guide.md](docs/user-guide.md).

## Modules

The kit is made of modules. A **mode** is a ready-made set: `server` (the default) is Spoolman, server, printers,
presets and backup; `station` is only the station; `all-in-one` is both. AI, the web part, remote access, orders,
the library and auto-update are off until you turn them on. Change them any time with `sudo filament-kit config`
(**Modules**) or `sudo filament-kit modules enable <name>` / `disable <name>`; turning a module off never deletes
its data. What each one needs (another module, or something of yours):

| Module | What it is | Needs |
|---|---|---|
| `spoolman` | Spoolman filament database, run on this machine | nothing |
| `server` | App server: pairing, inventory, API, avahi announcement | Spoolman (this machine or a remote one) |
| `ai_intake` | **Optional AI**: Claude reads spool labels from photos | `server`, an Anthropic API key |
| `printers` | Bambu bridge: discovery, usage, slot mapping, camera | `server` |
| `presets` | Bambu Studio preset builds and PC sync | `server`, a Windows PC with Bambu Studio |
| `library` | Filament spec library: downloaded on request, then a daily update | nothing |
| `backup` | Nightly backup of Spoolman db, settings and state | nothing |
| `station` | USB scale and PN532 reader, read-only HTTP | a DYMO USB scale and a PN532 NFC reader |
| `web` | Browser UI and the MCP endpoint, on top of the server | `server`, an https address (`web.public_url`) |
| `remote` | Public https name for the web UI (nginx, certbot) | `web`, a public DNS name, ports 443 and 80 |
| `orders` | Order history file for the shop tools | `ai_intake`, an order history file (`orders.file`) |
| `updates` | Daily check for a new signed release; installs it and keeps the one before | nothing |

## Supported printers

Every Bambu Lab printer the hardware data file describes: H2D, H2D Pro, H2S, H2C, X2D, P2S, X1 Carbon, X1, X1E,
P1P, P1S, A1 mini, A1 and A2L, with any number of AMS, AMS 2 Pro, AMS HT and AMS Lite units and the external
spool holders. Slots are labelled A1 ... P4, AA1 ..., HT-A ..., Ext (or Ext-L / Ext-R).

The facts about each model and unit live in a data file, not in the program. Each release also carries that
file (`bambu_hardware.xml`); `sudo filament-kit update` checks its signature and, when it is newer than the one in
use, puts it in place, also when the program itself is up to date. To correct or add something yourself, put your own file at
`/etc/filament-kit/bambu_hardware.xml` with a version above the built-in one's: it wins element by element over
the built-in one, a file that is not newer is ignored, a bad file is refused whole (the last good data stays in
use), and the updater never replaces a file you made. `sudo filament-kit
status` says whether the data loaded and names a refused file.

Printers are found on the network (the computer must be on the same network segment; allow UDP 2021 and 1990 if
it runs a firewall). Add one by hand with `sudo filament-kit config` > **Printers** > **add printer**. The
printer's TLS certificate is pinned on first use. See [docs/user-guide.md](docs/user-guide.md#bambu-lab-printers).

## The phone app

Download `filament-kit.apk` from the Releases page onto an Android phone (Android 10 or newer) and install it.
On the server run `sudo filament-kit pair` and scan the QR code it prints (or pick the server in the app and type
the 6-digit code). Pair another phone the same way; `sudo filament-kit unpair` lists and removes them. With the
`web` module on, the same tasks also work in any phone browser at `<public address>/intake`.

## Pair your PC

For the presets: install `filament-kit-sync-setup-<version>.exe` from the Releases page on the Windows PC with
Bambu Studio, run `sudo filament-kit pair --pc` on the server and paste the link it prints into the setup's
console. Step by step: [Pair your PC](docs/user-guide.md#pair-your-pc) in the guide.

## The reader

A small ESP32-C3 box next to the printer: tap a spool's tag, turn the knob to a slot, and the spool is loaded
there. It works with any printer and slot layout the server knows. It talks to the `web` module: make its token
with `sudo filament-kit reader token --name bench`. Parts, wiring, building and its API are in
[reader/README.md](reader/README.md).

## Updates and rollback

- `sudo filament-kit update --check`: says whether a newer release is out.
- `sudo filament-kit update`: downloads it, checks its signature and hash as the installer does, stops the kit,
  installs it (no questions) and starts it again. Your spools, settings and paired phones stay, and the version
  it replaced is kept. It does nothing while a printer is mapping slots or loading a spool.
- `sudo filament-kit update --rollback`: goes back to that version.
- `sudo filament-kit modules enable updates`: checks every day (or weekly: `"updates": {"schedule": "weekly"}`
  in `/etc/filament-kit/config.json`) and installs on its own; it never reinstalls a version you rolled back
  from. While the repository is private, set `"updates": {"token_file": "<root-only file with the token>"}`.

## The filament library

Published filament specs (temperatures, speeds) for the presets. It is not part of the program and nothing needs
it: ask for it with `sudo filament-kit library update`, or turn on the `library` module to also check daily.
`library status`, `library rollback` and `library add <file>` (your own entries) are in the
[guide](docs/user-guide.md#spec-library-updates).

## Where your data lives

| Path | What |
|---|---|
| `/etc/filament-kit` | Settings (`config.json`), the server certificate, the API key, the web passphrase, your hardware file |
| `/var/lib/filament-kit` | Paired phones, printers, slot maps, usage, presets, the library, reader tokens |
| `/var/lib/spoolman` | Spoolman's database (your spools) |
| `/var/backups/filament-kit` | Nightly backups (14 days) |
| `/opt/filament-kit`, `/opt/spoolman` | The programs; `/opt/filament-kit/releases` keeps the verified releases for rollback |

## Uninstall

From an unpacked release (`filament-kit-<version>.tar.gz` from the Releases page):

```
sudo ./uninstall.sh
```

It removes the programs and services but **keeps** your spools, settings and backups, so a later install picks
up where you left off. `sudo ./uninstall.sh --purge` deletes those too (it asks you to type `purge`). The
station's computer changes (sleep, ModemManager, brltty, audio) stay; the guide says how to undo them.

## More

- [docs/user-guide.md](docs/user-guide.md): install modes, every command, printers and slot mapping, presets,
  the intake station, the Claude connector and phone web app, remote access, order history, troubleshooting.
- [docs/testing-e2e.md](docs/testing-e2e.md): the end-to-end test run on WSL.
- [docs/migrate-from-filament-ops.md](docs/migrate-from-filament-ops.md): moving from the older filament-ops
  setup, and the maintainer's notes (release signing, the Android release build).

filament-kit is GPL-3.0 (see [LICENSE](LICENSE)).
