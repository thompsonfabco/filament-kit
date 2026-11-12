# Third-party software and data

filament-kit is free software under the GNU General Public License, version 3 or later ([LICENSE](LICENSE)).
This page lists the components a filament-kit release contains or the installer fetches, and their licences.

- **Shipped**: inside a release file (the server tarball, the Android APK, the Windows PC sync setup, the
  firmware images).
- **Installed**: fetched by the installer or `pip` onto your computer from the project's own source (Ubuntu's
  package archive, PyPI, GitHub) and not redistributed by filament-kit.

## Shipped in the server tarball (`filament-kit-<version>.tar.gz`)

| Component | Licence |
|---|---|
| filament-kit (the wheel, `install.sh`, `uninstall.sh`, units, `get.sh`) | GPL-3.0-or-later |
| `bambu_hardware.xml` | GPL-3.0-or-later |
| Button-panel firmware `install/panel/intake-panel.bin` | GPL-3.0-or-later (our source, `station/panel/src`), built with the ESP32 Arduino core (arduino-esp32 3.x, LGPL-2.1) for the panel's ESP32-C3 |
| Button-panel firmware: U8g2 2.36.5 (olikraus), the OLED library | BSD-2-Clause |
| Button-panel firmware: pioarduino platform-espressif32 and ESP-IDF components | Apache-2.0 |
| Printer Station firmware `install/reader/printer-station.bin` | see [The Printer Station firmware](#the-printer-station-firmware-built-from-reader) |
| [esptool-js](https://github.com/espressif/esptool-js) 0.7.0, its published `bundle.js` unchanged as `setup_static/esptool.bundle.js` (SHA-256 `00ebe6fb0b202976d3e2a3c6b9a6bd438c26a81d2af6739c95ac276a64c1a84e`), which the setup page's Flash a device tab loads to write firmware over Web Serial; licences in `setup_static/esptool.bundle.LICENSES.txt` | Apache-2.0 |
| pako 2.1.0, inside that bundle | MIT AND Zlib |
| atob-lite 2.0.0, inside that bundle | MIT |
| The Android app `app/filament-kit.apk` | see [The Android app](#the-android-app) |

## Installed on the server by the installer

Ubuntu packages, from Ubuntu's archive (`apt`):

| Package | Licence |
|---|---|
| python3-venv, curl, unzip | PSF-2.0; curl licence (MIT-style); Info-ZIP |
| avahi-daemon | LGPL-2.1-or-later |
| libnss-mdns | LGPL-2.1-or-later |
| qrencode | LGPL-2.1-or-later |
| ffmpeg | GPL-2.0-or-later (Ubuntu's build) |
| alsa-utils (`aplay`) | GPL-2.0-or-later |
| espeak-ng | GPL-3.0-or-later |
| nginx, certbot | BSD-2-Clause; Apache-2.0 |

Spoolman, downloaded from its GitHub release:

| Component | Version | Licence |
|---|---|---|
| [Spoolman](https://github.com/Donkie/Spoolman) | v0.27.0 | MIT |

Python packages, installed into `/opt/filament-kit/venv` from PyPI:

| Package | Licence |
|---|---|
| starlette, uvicorn | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| anthropic | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| paho-mqtt | EPL-2.0 OR BSD-3-Clause (EDL), used under the BSD-3-Clause option |
| defusedxml 0.7.1 | PSF-2.0 |
| websockets | BSD-3-Clause |
| zeroconf | LGPL-2.1-or-later |
| nfcpy 1.0.4 | EUPL-1.1 "or subsequent versions" |
| pyserial | BSD-3-Clause |
| esptool 5.6.0 | GPL-2.0-or-later |
| mcp 2.3.0 | MIT |
| pywebpush, py-vapid | MPL-2.0 |
| aiohttp | Apache-2.0 AND MIT |
| aiosignal, frozenlist, multidict, propcache, yarl, requests, opentelemetry-api, esp-pylib | Apache-2.0 |
| packaging | Apache-2.0 OR BSD-2-Clause |
| click, httpx2, httpcore2, idna, pycparser, sse-starlette, Pygments, intelhex | BSD-2/3-Clause |
| anyio, attrs, annotated-types, charset-normalizer, h11, http_ece, ifaddr, jiter, jsonschema, jsonschema-specifications, markdown-it-py, mdurl, pydantic, pydantic_core, pyDes, PyJWT, PyYAML, referencing, rich, rich-click, rpds-py, truststore, typing-inspection, urllib3, docstring_parser | MIT |
| cffi | MIT-0 |
| reedsolo | MIT-0 OR Unlicense |
| ndeflib | ISC |
| libusb1 | LGPL-2.1-or-later |
| certifi | MPL-2.0 |
| typing_extensions, aiohappyeyeballs | PSF-2.0 |
| sniffio | Apache-2.0 OR MIT |

From v0.3.0, for the station's speech (`station` extra in the same venv):

| Component | Licence |
|---|---|
| piper-tts 1.8.0 (OHF-Voice/piper1-gpl), with g2pW in its wheel | GPL-3.0-or-later; g2pW Apache-2.0 |
| onnxruntime | MIT |
| Piper voice model, downloaded at install time | see [Speech voice](#speech-voice) |

## The Android app

Built by the release workflow and shipped as `filament-kit.apk`. Everything below is compiled into it.

| Component | Licence |
|---|---|
| filament-kit app | GPL-3.0-or-later |
| Kotlin standard library, kotlinx-coroutines, kotlinx-serialization | Apache-2.0 |
| AndroidX: all groups on the release classpath, including core, activity, compose (BOM 2026.09), material3, lifecycle, navigation, datastore, camera (CameraX), exifinterface, media3 (ExoPlayer, HLS, OkHttp datasource, UI) | Apache-2.0 |
| OkHttp, Okio | Apache-2.0 |
| kotlinx-atomicfu, JetBrains annotations | Apache-2.0 |
| Guava (Android flavour), failureaccess, Dagger, javax.inject, jakarta.inject, JSR-305, JSpecify, Error Prone annotations, J2ObjC annotations, AutoValue annotations | Apache-2.0 |
| Checker Framework annotations (checker-qual) | MIT |
| [zxing-cpp](https://github.com/zxing-cpp/zxing-cpp) Android library 3.1.1 (`io.github.zxing-cpp:android`) | Apache-2.0 |
| libzueci (in zxing-cpp's source) | BSD-3-Clause |
| Test-only (not in the APK): JUnit 4 (EPL-1.0), Robolectric (MIT), AndroidX test, Espresso (Apache-2.0), MockWebServer and okhttp-tls (Apache-2.0); Google ML Kit barcode scanning (proprietary) and ZXing core (Apache-2.0), only in the scanner comparison test | |

## The Windows PC sync (`filament-kit-sync-setup-<version>.exe`)

| Component | Licence |
|---|---|
| filament-kit-sync (`pc-sync/fksync`) | GPL-3.0-or-later |
| Python interpreter and standard library (bundled by PyInstaller; the Linux PC sync bundles CPython 3.12 the same way) | PSF-2.0 |
| PyInstaller bootloader and runtime hooks | GPL-2.0-or-later WITH Bootloader-exception; hooks Apache-2.0 |
| Inno Setup (the setup stub) | Inno Setup licence (permissive; keep its notice) |

## The Klipper printer pack (`fk-printer-pack.tar.gz`, v0.4.0)

Shipped in the pack: the gcode macros, the `lasttag` service, the helper scripts and two patches to nfc2klipper
(`printer-pack/nfc2klipper/patches/`), all GPL-3.0-or-later.

Installed on your printer by the pack, from the projects' own sources:

| Component | Licence |
|---|---|
| nfc2klipper, by Sebastian Andersson (a pinned commit, with the two patches) | GPL-3.0-or-later |
| flask | BSD-3-Clause |
| npyscreen | BSD-2-Clause |
| gunicorn | MIT |
| toml, urllib3 | MIT |
| requests | Apache-2.0 |
| types-toml, types-requests | Apache-2.0 |
| nfcpy 1.0.4 | EUPL-1.1 "or subsequent versions" |
| Klipper, Moonraker, AFC-Klipper-Add-On, Happy Hare | GPL-3.0 |

| Component | Licence |
|---|---|
| Spool Sync (`integrations/orca-spool-sync/`) | GPL-3.0-or-later |
| OrcaSlicer, which Spool Sync runs inside | AGPL-3.0 |

## The Printer Station firmware (built from `reader/`)

| Component | Licence |
|---|---|
| reader firmware (`reader/src`, `reader/lib/reader_core`) | GPL-3.0-or-later |
| ESP32 Arduino core (arduino-esp32) | LGPL-2.1 |
| pioarduino platform-espressif32 and ESP-IDF components | Apache-2.0 |
| Adafruit PN532, Adafruit SSD1306, Adafruit GFX Library | BSD-3-Clause |
| Adafruit BusIO | MIT |
| ArduinoJson 7 | MIT |

## Speech voice

The station's speech uses Piper with a voice model downloaded at install time from
`huggingface.co/rhasspy/piper-voices`. It is not bundled in any release.

| Voice | Dataset | Licence |
|---|---|---|
| `en_US-libritts_r-medium`, speaker 0 (default) | LibriTTS-R (openslr.org/141) | CC BY 4.0 |
| `en_US-ljspeech-medium` (selectable) | LJ Speech | public domain |

Attribution (CC BY 4.0): the voice is based on LibriTTS-R, the sound-quality-restored version of LibriTTS
(Koizumi et al., 2023; openslr.org/141), licensed CC BY 4.0 (creativecommons.org/licenses/by/4.0/), converted for
Piper by the rhasspy/piper-voices project. Changes: none by filament-kit; the model is used as published.

## Display library (planned, firmware 7)

| Component | Licence |
|---|---|
| olikraus/U8g2 2.36.5, library code (Copyright (c) 2016 olikraus) | BSD-2-Clause |
| U8g2 fonts | per font group, under their own conditions (see U8g2's LICENSE) |

## Data

| Component | Licence |
|---|---|
| [filament library](https://github.com/thompsonfabco/filament-library) (`library.tar.gz`, with a release) | GPL-3.0 |
| `bambu_hardware.xml` | GPL-3.0-or-later |
| Bambu Studio and Orca Slicer system presets (not shipped; read from your PC's own slicer install) | AGPL-3.0 (the slicers) |
