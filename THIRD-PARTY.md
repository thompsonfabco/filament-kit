# Third-party software and data

filament-kit is free software under the GNU General Public License, version 3 or later ([LICENSE](LICENSE)).
This page lists what else a filament-kit release contains, what the installer fetches onto your computer, and
the terms each piece comes under. Audit of 2026-11-07 against `main` and the v0.2.0 release; licences read from
the projects' own LICENSE files, PyPI metadata and model cards on that day. Not legal advice.

Two kinds of entry:

- **Shipped**: inside a release file (the server tarball, the Android APK, the Windows PC sync setup, the
  firmware images). These we redistribute, so their licences must allow that alongside GPL-3.0.
- **Installed**: fetched by the installer or `pip` onto your computer from the project's own source (Ubuntu's
  package archive, PyPI, GitHub). We don't redistribute these; the kit runs them as separate programs or imports
  them. Their licence is between you and that project; we list it so you know what arrives.

## Action needed (open items)

| # | Item | Why | What to do |
|---|---|---|---|
| 1 | ~~**Google ML Kit barcode scanning** in the Android app (`com.google.mlkit:barcode-scanning`)~~ | Proprietary, closed source, under Google's ML Kit terms. The APK bundled it, which sat badly with GPL-3.0 §6, and F-Droid refuses it. | **Done**: the QR scanner uses zxing-cpp (Apache-2.0); ML Kit is gone from the APK. |
| 2 | **Licence metadata of our own packages** | `server/pyproject.toml` and `pc-sync/pyproject.toml` declare no `license`; `pip-licenses` shows filament-kit as UNKNOWN. | Add `license = "GPL-3.0-or-later"` to both (and the LICENSE file to the wheel), so installs and tools see it. |
| 3 | **Notices in the release files** | The APK and the PC sync setup carry third-party code (AndroidX, OkHttp, PyInstaller's bootloader, ...), whose BSD/MIT/Apache terms want their notices kept. | Ship this file in the server tarball and the PC sync setup, and show it (or the Gradle-generated OSS notices) in the app's Settings. **App part done**: the APK carries this file and LICENSE, shown under Settings > Licences. |

Everything else below is in order: GPL-3.0-compatible, or only installed and never redistributed.

## Shipped in the server tarball (`filament-kit-<version>.tar.gz`)

| Component | Licence | Notes |
|---|---|---|
| filament-kit (the wheel, `install.sh`, `uninstall.sh`, units, `get.sh`) | GPL-3.0-or-later | Our code. `release.py` carries its own ed25519 verifier (RFC 8032), no external library. |
| `bambu_hardware.xml` | GPL-3.0-or-later | Our data file about Bambu Lab printers and AMS units. |
| Button-panel firmware `install/panel/intake-panel.bin` | GPL-3.0-or-later (our source, `station/panel/src`), built with the ESP8266 Arduino core (LGPL-2.1) and Espressif's ESP8266 SDK binaries (Espressif MIT-style licence) | A compiled image. Its source is in this repository, which satisfies the LGPL's relinking terms. No third-party Arduino library is used in the shipped firmware 6. Planned for firmware 7 (the OLED display): U8g2 2.36.5, BSD-2-Clause for the library code, with the fonts under their own terms (see [Display library](#display-library-planned-firmware-7)). |
| The Android app `app/filament-kit.apk` | see [The Android app](#the-android-app) | The same APK as on the Releases page. |

## Installed on the server by the installer

Ubuntu packages, from Ubuntu's archive (`apt`), each used as a separate program:

| Package | Licence | Used for |
|---|---|---|
| python3-venv, curl, unzip | PSF-2.0; curl licence (MIT-style); Info-ZIP | the install itself |
| avahi-daemon | LGPL-2.1-or-later | announcing the server to phones (`_filamentkit._tcp`) |
| qrencode | LGPL-2.1-or-later | the pairing QR code in the terminal |
| ffmpeg | GPL-2.0-or-later (Ubuntu's build) | the printer camera relay; the station's webcam picture and speech resampling |
| alsa-utils (`aplay`) | GPL-2.0-or-later | the station's beep |
| espeak-ng | GPL-3.0-or-later | the station's speech ("Held, 1042 grams") |
| nginx, certbot | BSD-2-Clause; Apache-2.0 | the `remote` module |

Spoolman, downloaded from its GitHub release and checked by SHA-256:

| Component | Version | Licence |
|---|---|---|
| [Spoolman](https://github.com/Donkie/Spoolman) | v0.27.0 | MIT |

Python packages, installed into `/opt/filament-kit/venv` from PyPI (`pip install filament-kit[station,web]`,
plus `[push]` when Web Push is turned on). Direct dependencies first; the rest come with them. Versions are
the ones pip resolved on 2026-11-07; pins are marked.

| Package | Licence | Notes |
|---|---|---|
| starlette, uvicorn | BSD-3-Clause | the API and web servers |
| python-multipart | Apache-2.0 | |
| anthropic | Apache-2.0 | AI label reading (`ai_intake`) |
| cryptography | Apache-2.0 OR BSD-3-Clause | the server certificate |
| paho-mqtt | EPL-2.0 OR BSD-3-Clause (EDL) | the printer connection; we take it under the BSD-3-Clause option |
| defusedxml 0.7.1 (pinned) | PSF-2.0 | the hardware XML |
| websockets | BSD-3-Clause | the Klipper bridge (Moonraker's websocket); `>=13`, 17.4 checked on 2026-11-08 |
| zeroconf | LGPL-2.1-or-later | Klipper printer discovery (Moonraker's mDNS announcements, listen only); `>=0.136`, 0.154.0 resolved on 2026-11-08. Installed from PyPI and imported unmodified, not shipped in a release; the LGPL lets a GPL-3.0 program use it as a library. |
| nfcpy 1.0.4 (pinned) | EUPL-1.1 "or subsequent versions" | the station's NFC reader. EUPL-1.1's own compatibility list stops at GPL-2, but nfcpy's headers allow any later EUPL, and EUPL-1.2 lists GPL-3. Imported unmodified. |
| pyserial | BSD-3-Clause | the station's reader and panel |
| esptool 5.6.0 (pinned) | GPL-2.0-or-later | run as a separate program to reflash the panel |
| mcp 2.3.0 (pinned) | MIT | the Claude connector |
| pywebpush, py-vapid | MPL-2.0 | Web Push (optional); MPL-2.0 names GPL-3.0 as a secondary licence |
| Transitive: aiohttp, aiosignal, frozenlist, multidict, propcache, yarl, requests, opentelemetry-api, esp-pylib | Apache-2.0 (aiohttp: Apache-2.0 AND MIT) | |
| Transitive: packaging | Apache-2.0 OR BSD-2-Clause | |
| Transitive: click, httpx2, httpcore2, idna, pycparser, sse-starlette, Pygments, intelhex | BSD-2/3-Clause | |
| Transitive: anyio, attrs, annotated-types, charset-normalizer, h11, http_ece, ifaddr (with zeroconf), jiter, jsonschema, jsonschema-specifications, markdown-it-py, mdurl, pydantic, pydantic_core, pyDes, PyJWT, PyYAML, referencing, rich, rich-click, rpds-py, truststore, typing-inspection, urllib3, docstring_parser | MIT | |
| Transitive: cffi, reedsolo | MIT-0 (reedsolo: MIT-0 OR Unlicense) | |
| Transitive: ndeflib | ISC | with nfcpy |
| Transitive: libusb1 | LGPL-2.1-or-later | with nfcpy |
| Transitive: certifi | MPL-2.0 | |
| Transitive: typing_extensions, aiohappyeyeballs | PSF-2.0 | |
| Transitive: sniffio | Apache-2.0 OR MIT | |

From v0.3.0, as a `station` extra in the same venv: **piper-tts 1.8.0**
(GPL-3.0-or-later, from OHF-Voice/piper1-gpl; its wheel also carries g2pW under Apache-2.0) with
**onnxruntime** (MIT; licence not re-checked since it landed), for the station's speech; espeak-ng (above) stays
the fallback. The Piper **voice model** is downloaded at install time and checked against a pinned SHA-256; it
is not in the release. Voice models carry their own dataset licences: see [Speech voice](#speech-voice).

## The Android app

Built by the release workflow and shipped as `filament-kit.apk`. Everything below is compiled into it.

| Component | Licence | Notes |
|---|---|---|
| filament-kit app | GPL-3.0-or-later | our code |
| Kotlin standard library, kotlinx-coroutines, kotlinx-serialization | Apache-2.0 | |
| AndroidX: core, activity, compose (BOM 2026.09), material3, lifecycle, navigation, datastore, camera (CameraX), exifinterface, media3 (ExoPlayer, HLS, OkHttp datasource, UI) | Apache-2.0 | |
| OkHttp, okhttp-tls | Apache-2.0 | |
| [zxing-cpp](https://github.com/zxing-cpp/zxing-cpp) Android library 3.1.1 (`io.github.zxing-cpp:android`) | Apache-2.0 | the QR pairing scanner. A native library (`libzxingcpp_android.so`, one per CPU type) with a small Kotlin wrapper. Its source also carries libzueci (BSD-3-Clause, from upstream's headers; not re-checked for 3.1.1). |
| Test-only (not in the APK): JUnit 4 (EPL-1.0), Robolectric (MIT), AndroidX test, Espresso (Apache-2.0), MockWebServer (Apache-2.0); Google ML Kit barcode scanning (proprietary) and ZXing core (Apache-2.0), only in the scanner comparison test | | |

## The Windows PC sync (`filament-kit-sync-setup-<version>.exe`)

| Component | Licence | Notes |
|---|---|---|
| filament-kit-sync (`pc-sync/fksync`) | GPL-3.0-or-later | our code; no third-party Python packages |
| Python interpreter and standard library | PSF-2.0 | bundled by PyInstaller. The Linux PC sync (v0.3.0, PyInstaller 6.11.1) bundles CPython 3.12 the same way, with the same terms. |
| PyInstaller bootloader and runtime hooks | GPL-2.0-or-later WITH Bootloader-exception; hooks Apache-2.0 | the exception allows bundling a program under any licence |
| Inno Setup (the setup stub) | Inno Setup licence (permissive; keep its notice) | makes the setup `.exe` |

## The Klipper printer pack (`fk-printer-pack.tar.gz`, v0.4.0)

**Shipped** in the pack (our code, GPL-3.0-or-later): the gcode macros, the `lasttag` service, the helper scripts, and two
small patches to nfc2klipper (`printer-pack/nfc2klipper/patches/`). The patches are changes to a GPL-3.0-or-later program
and are under the same licence.

**Installed on your printer** by the pack, from the projects' own sources (we do not redistribute them):

| Component | Licence | Notes |
|---|---|---|
| nfc2klipper, by Sebastian Andersson (a pinned commit, with the two patches) | GPL-3.0-or-later | the NFC tag reader service on the printer |
| flask | BSD-3-Clause | nfc2klipper's requirement; installed on the printer with pip, nothing copied into the kit |
| npyscreen | BSD-2-Clause | nfc2klipper's requirement |
| gunicorn | MIT | nfc2klipper's requirement |
| toml, urllib3 | MIT | nfc2klipper's requirements |
| requests | Apache-2.0 | nfc2klipper's requirement |
| types-toml, types-requests | Apache-2.0 | nfc2klipper's requirements |
| nfcpy 1.0.4 | EUPL-1.1 "or subsequent versions" | nfc2klipper's requirement; see the same package in the table above |
| Klipper, Moonraker, AFC-Klipper-Add-On, Happy Hare | GPL-3.0 | already on your printer; the kit talks to them and copies nothing from them |

The OrcaSlicer plugin **Spool Sync** (`integrations/orca-spool-sync/`) is our code (GPL-3.0-or-later) and runs inside
OrcaSlicer (AGPL-3.0).

## The bench reader firmware (built by you from `reader/`)

Not in a release: you build it with PlatformIO and flash it yourself; later versions arrive over the air from
your own server. What goes into it:

| Component | Licence |
|---|---|
| reader firmware (`reader/src`, `reader/lib/reader_core`) | GPL-3.0-or-later |
| ESP32 Arduino core (arduino-esp32) | LGPL-2.1 |
| pioarduino platform-espressif32 and ESP-IDF components | Apache-2.0 |
| Adafruit PN532, Adafruit SSD1306, Adafruit GFX Library | BSD-3-Clause |
| Adafruit BusIO | MIT |
| ArduinoJson 7 | MIT |
| TalkiePCM 0.1.1 (pschatzmann) | GPL-3.0 |

A built image is a GPL-3.0 work (TalkiePCM is GPL-3.0; our code is GPL-3.0-or-later). The source is here.

## Speech voice

The station's speech uses Piper with a voice model downloaded at install time (about 79 MB) from
`huggingface.co/rhasspy/piper-voices`, checked against pinned SHA-256 hashes. Not bundled in any release.

| Voice | Dataset | Licence | Status |
|---|---|---|---|
| `en_US-libritts_r-medium`, speaker 0 | LibriTTS-R (openslr.org/141) | CC BY 4.0 | default |
| `en_US-ljspeech-medium` | LJ Speech | public domain | selectable (`station.voice`) |

- **Attribution (CC BY 4.0), to keep with the voice and in the notices:** the voice is based on LibriTTS-R, the
  sound-quality-restored version of LibriTTS (Koizumi et al., 2023; openslr.org/141), licensed CC BY 4.0
  (creativecommons.org/licenses/by/4.0/), converted for Piper by the rhasspy/piper-voices project. Changes: none
  by filament-kit; the model is used as published.
- Pinned in the installer: the `.onnx` file's hash is Hugging Face's published one; the `.onnx.json` is hashed by us.
  The voice's hashes live in the installer's code, not here.

## Display library (planned, firmware 7)

The button panel's OLED display (panel firmware 7, not on `main` yet) adds the PlatformIO library
**olikraus/U8g2 2.36.5**:

- **Library code**: BSD-2-Clause (Copyright (c) 2016 olikraus). Compatible with GPL-3.0-or-later in one image;
  keep its copyright notice and disclaimer with the source and in the notices shipped with the release. The
  2.36.5 tag exists on GitHub; whether PlatformIO's registry lists it was not confirmed (check with
  `pio pkg show olikraus/U8g2`).
- **Fonts**: U8g2's LICENSE says fonts are "licensed under different conditions", per font group. The fonts used
  must be named here and checked one by one before firmware 7 ships. Checked so far: the Adobe X11 fonts
  (`helvB08_tr`, `ncenB08_tr` and the like) allow use, copying and sale for any purpose with the notice kept; the
  X11 monospace fonts (`6x10_tf`, `5x7_tf`) are described as public domain. Not safe without a closer look: some
  fonts from the dafont group (Nokia Cellphone is "distribute as you wish" but asks not to be sold on media;
  others say only "100% free"). Prefer the X11 and Adobe fonts.

## Data

- **The filament library** ([thompsonfabco/filament-library](https://github.com/thompsonfabco/filament-library),
  `library.tar.gz` with a release when the token is set): GPL-3.0. Its entries are manufacturers' published
  specifications (temperatures, speeds, densities) with a source URL per value; numbers of fact, copied as
  printed, not the manufacturers' texts.
- **Bambu Studio and Orca Slicer system presets**: the slicers are AGPL-3.0, and their preset files come with
  them. The kit never ships them. The PC sync reads the copies installed on your PC, and the generated presets
  inherit from them there (`inherits` by name); the server keeps only the uploaded copies for your own build.
  Nothing from them is in a release.
- **`bambu_hardware.xml`**: our own description of Bambu Lab's printers and AMS units, from public
  documentation and observation; GPL-3.0-or-later.

## How this was checked

- Python: `pip-licenses` over a venv with `filament-kit[station,web,push]` and PyInstaller (2026-11-07).
- zeroconf 0.154.0 and ifaddr 0.2.0: the `METADATA` (`License-Expression: LGPL-2.1-or-later`; `License: MIT`)
  and the licence files (`COPYING`, `LICENSE.txt`) in their dist-info, in a venv with `filament-kit[test]` (2026-11-08).
- Android: `android/gradle/libs.versions.toml` and the published licences of each artifact.
- Firmware: `reader/platformio.ini`, `station/panel/platformio.ini` and the panel source's includes.
- Installer: the `apt` lists in `server/filament_kit/modules.py`, `install/install.sh`, `install/spoolman.sh`.
- Licence texts: each project's LICENSE file or PyPI metadata; the Piper voice's `MODEL_CARD` on Hugging Face
  and the Blizzard 2013 licence page it links to; Google's ML Kit terms page.
- Not re-verified: Ubuntu 24.04's own `ffmpeg` copyright file (Debian's was read; Ubuntu builds from the same
  source with GPL enabled), and tag-specific LICENSE files of Bambu Studio and Orca Slicer (read from `main`).

Found something wrong or missing? Open an issue naming the component and where you read its licence.
