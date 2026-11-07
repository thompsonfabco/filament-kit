# filament-kit

filament-kit keeps track of your 3D printer filament. It runs on a small computer at home, keeps every spool you
own in [Spoolman](https://github.com/Donkie/Spoolman), and connects those spools to your Bambu Lab printers: add
a spool from your phone, load it into a printer slot, and the printer gets the right filament setting while the
filament it uses comes off that spool. It also builds slicer presets for every filament you own.

The goal is a kit a normal user can set up without being a developer: one command installs it, a menu picks
the parts you want and says what each one needs, AI is optional, every Bambu Lab printer is supported (Klipper
and Prusa printers are planned), the facts about printers live in data files you can correct yourself, and it
can keep itself up to date. The whole kit is free software (GPL-3.0).

## What you need

- A computer running **Ubuntu 24.04 or newer** on your home network that stays on (an old laptop or a mini PC).
- An **Android phone** (Android 10 or newer), or an **iPhone** for the web app.
- One or more **Bambu Lab printers** on the same network. The kit works without a printer too, as a spool list.
- Optional: a Windows PC with Bambu Studio (for the presets), an Anthropic API key (for AI label reading), a USB
  scale and an NFC reader (for the intake station).

## Install

On the Ubuntu computer, open a Terminal, paste this line and press Enter:

```bash
curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh
```

It downloads the installer (`get.sh`) and runs it. The installer fetches the newest release, checks its
signature, and asks a few questions (pressing Enter at each one is fine). At the end it shows a QR code for pairing your phone. Step by step, with every question and what you see:
**[Install the server](docs/install-server.md)**.

The command works once the repository is public. It is private for now (a beta), so until then the server
how-to has the private route, and [Known gaps](docs/known-gaps.md) lists what else is still rough.

Then, on your phone:

- **Android:** [Install the Android app](docs/install-android-app.md) and pair it with the server.
- **iPhone** (or any phone browser): [Use the web app on an iPhone](docs/install-iphone-web-app.md).

Optional afterwards: the PC sync for Bambu Studio presets ([Pair your PC](#pair-your-pc)), an intake station with
a scale and an NFC reader ([Intake station](docs/user-guide.md#intake-station)), and the bench
[reader](#the-reader).

Your spool list is also in any web browser at home, at `http://<computer name>.local:7912` (the installer prints
the address). If something doesn't work, `sudo filament-kit status` on the server checks everything and says
what to do about a failing line.

Everything else (every command, printers and slot mapping, presets, the station, the Claude connector, remote
access) is in the **[user guide](docs/user-guide.md)**.

## What it does

- **Add spools** from the Android app or the phone web app: type them in, or pick a filament you already have.
  Reading the label from a photo is **optional AI** (your own Anthropic API key); everything else works without it.
- **Load a spool into a printer slot** from the app, or tap its NFC tag on the bench reader: the printer gets the
  right filament setting and Spoolman the spool's new location. Filament used in a print comes off the right
  spools.
- **Build slicer presets**: a Bambu Studio (and, if you like, Orca Slicer) preset for every filament line you own;
  the PC sync installs them on your Windows PC.
- **Weigh a spool and read its tag** at an intake station (USB scale and NFC reader), **back up** every night, and
  **update** from signed releases (by hand, or daily with the `updates` module).

## Modules

The kit is made of modules. A **mode** is a ready-made set: `server` (the default) is Spoolman, server, printers,
presets and backup; `station` is only the station; `all-in-one` is both. AI, the web part, remote access, orders,
the library and auto-update are off until you turn them on. Change them any time with `sudo filament-kit config`
(**6) Modules**): a checklist where each module says what it needs. Turning a module off never deletes its data.

| Module | What it is | Needs |
|---|---|---|
| `spoolman` | Spoolman filament database, run on this machine | nothing |
| `server` | App server: pairing, inventory, API, avahi announcement | Spoolman (this machine or a remote one) |
| `ai_intake` | **Optional AI**: Claude reads spool labels from photos | `server`, an Anthropic API key |
| `printers` | Bambu bridge: discovery, usage, slot mapping, camera | `server` |
| `presets` | Bambu Studio preset builds and PC sync | `server`, a Windows PC with Bambu Studio |
| `library` | Filament spec library: downloaded on request, then a daily update | nothing |
| `backup` | Nightly backup of the Spoolman database, settings and state | nothing |
| `station` | USB scale and PN532 reader, read-only HTTP | a DYMO USB scale and a PN532 NFC reader |
| `web` | Phone web app and the Claude connector (MCP), on top of the server | `server`, an https address (`web.public_url`) |
| `remote` | nginx in front of the web part, and a public https name (certbot) | `web`; for a public name: DNS, ports 443 and 80 |
| `orders` | Order history file for the shop tools | `ai_intake`, an order history file (`orders.file`) |
| `updates` | Daily check for a new signed release; installs it and keeps the one before | nothing |

## The phone app

On Android, install `filament-kit.apk` from the Releases page (Android 10 or newer), run `sudo filament-kit pair`
on the server and scan the QR code it prints: [Install the Android app](docs/install-android-app.md). On an iPhone
or in any phone browser, the `web` module gives the same tasks as a web app you can put on the home screen:
[Use the web app on an iPhone](docs/install-iphone-web-app.md). `sudo filament-kit unpair` lists and removes
paired phones.

## Pair your PC

For the Bambu Studio presets: install `filament-kit-sync-setup-<version>.exe` from the Releases page on the
Windows PC with Bambu Studio, run `sudo filament-kit pair --pc` on the server and paste the link it prints into
the setup's console. Step by step: [Pair your PC](docs/user-guide.md#pair-your-pc) in the guide.

## The reader

A small ESP32-C3 box next to the printer: tap a spool's tag, turn the knob to a slot, and the spool is loaded
there. It talks to the `web` module: make its token with `sudo filament-kit reader token --name bench`. Parts,
wiring, building and its API are in [reader/README.md](reader/README.md).

## Supported printers

Every Bambu Lab printer the hardware data file describes: H2D, H2D Pro, H2S, H2C, X2D, P2S, X1 Carbon, X1, X1E,
P1P, P1S, A1 mini, A1 and A2L, with any number of AMS, AMS 2 Pro, AMS HT and AMS Lite units and the external
spool holders. Slots are labelled by unit and position: A1 ... Z4, then AA1 ..., HT-A ... for AMS HT units, and
Ext (or Ext-L / Ext-R) for the external holders. Klipper and Prusa printers are planned.

The facts about each model and unit live in a data file (`bambu_hardware.xml`), not in the program, and updates
bring new versions of it. To correct or add something yourself, see
[Your own printer data](docs/user-guide.md#your-own-printer-data-override).

Printers are found on the network (the computer must be on the same network segment; allow UDP 2021 and 1990 if
it runs a firewall). Add one by hand with `sudo filament-kit config` > **Printers** > **add printer**. See
[Bambu Lab printers](docs/user-guide.md#bambu-lab-printers).

## Updates and rollback

- `sudo filament-kit update --check`: says whether a newer release is out.
- `sudo filament-kit update`: downloads it, checks its signature and hash as the installer does, and installs it.
  Your spools, settings and paired phones stay, and the version it replaced is kept. It does nothing while a
  printer is mapping slots or loading a spool. When the release carries a newer Android app, paired phones
  offer it on their home screen.
- `sudo filament-kit update --rollback`: goes back to that version.
- `sudo filament-kit modules enable updates`: checks every day and installs on its own. Details:
  [Update](docs/user-guide.md#update).

## The filament library

Published filament specs (temperatures, speeds) for the presets. It is optional and nothing needs it: ask for it
with `sudo filament-kit library update`, or turn on the `library` module to also check daily. See
[Spec library updates](docs/user-guide.md#spec-library-updates).

## Where your data lives

| Path | What |
|---|---|
| `/etc/filament-kit` | Settings (`config.json`), the server certificate, the API key, the web passphrase, your hardware file |
| `/var/lib/filament-kit` | Paired phones, printers, slot maps, usage, presets, the library, reader tokens |
| `/var/lib/spoolman` | Spoolman's database (your spools) |
| `/var/backups/filament-kit` | Nightly backups (14 days) |
| `/opt/filament-kit`, `/opt/spoolman` | The programs; `/opt/filament-kit/releases` keeps the verified releases for rollback |

## Uninstall

`sudo ./uninstall.sh` from an unpacked release removes the programs and keeps your spools, settings and backups;
`--purge` deletes those too (it asks you to type `purge`). Where to find the unpacked release after a
one-command install, and what stays behind: [Install the server, Uninstall](docs/install-server.md#uninstall).

## More

- [docs/install-server.md](docs/install-server.md), [docs/install-android-app.md](docs/install-android-app.md),
  [docs/install-iphone-web-app.md](docs/install-iphone-web-app.md): the how-tos.
- [docs/user-guide.md](docs/user-guide.md): install modes, every command, printers and slot mapping, presets,
  the intake station, the Claude connector and phone web app, remote access, order history, troubleshooting.
- [docs/known-gaps.md](docs/known-gaps.md): what doesn't work the way the how-tos describe yet.
- [docs/migrate-from-filament-ops.md](docs/migrate-from-filament-ops.md): moving from the older filament-ops
  setup.
- For maintainers and contributors: [docs/maintainer.md](docs/maintainer.md) (releases, signing keys, secrets),
  [docs/testing-e2e.md](docs/testing-e2e.md) and [docs/android-e2e.md](docs/android-e2e.md) (the end-to-end
  tests), and the design documents in [docs/design/](docs/design/).

filament-kit is GPL-3.0 (see [LICENSE](LICENSE)). What else a release contains or installs, and under what
terms: [THIRD-PARTY.md](THIRD-PARTY.md).
