# filament-kit Android app + printers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A sideloadable Android app that pairs with a filament-kit server, adds spools from label photos + tag + weight, and opens/updates spools from a tag tap; plus the server-side printer bridge part 1 (discovery, status, controls, camera relay) and the app's Printers screens.

**Architecture:** One Gradle project in `android/`, single `app` module, package `com.thompsonfabco.filamentkit`. Pure-Kotlin core packages (`tags`, `pairing`, `net`, `drafts`, `imaging`) with JVM unit tests; Compose UI on top (`ui/*`), one activity, Navigation Compose. Networking is OkHttp with a TrustManager that trusts exactly the pinned certificate fingerprint and ignores the host name, so any address of the server (mDNS name, IP, emulator `10.0.2.2`) works once paired.

**Tech Stack:** Kotlin (current stable), Jetpack Compose (BOM), Navigation Compose, kotlinx.serialization, OkHttp (+ MockWebServer, okhttp-tls in tests), CameraX, ML Kit barcode-scanning (bundled model), DataStore Preferences, JUnit 4, Compose UI test / AndroidX Test (instrumented). Build with the Gradle wrapper, AGP current stable supporting compileSdk 37, JDK 21 at `G:\Android\jdk-21.0.13+9`, SDK `G:\Android\Sdk`.

**Server printer stack (Tasks 12–15):** Python in `server/filament_kit/bridge/` (paho-mqtt, ffmpeg from apt), ported from the owner's proven `C:\CODING\h2d-filament-scanner\remote\remote.py` and generalised to many printers. **App printer screens (Task 16):** Media3 ExoPlayer (HLS, with an OkHttp data source on the pinned client) and an MJPEG view.

**Spec:** `docs/superpowers/specs/2026-11-01-filament-kit-design.md` (section 4 Android app incl. Printers; section 5 "Finding and adding printers", "Status", "Controls", "Camera relay"; section 3 Security for the QR/pinning contract; section 7 app error handling; section 8 app testing). Server API: `server/filament_kit/api.py`.

## Global Constraints

- minSdk 29 (Android 10), targetSdk/compileSdk 37. Sideloaded APK; no Google Play services required (ML Kit **bundled** model only).
- applicationId `com.thompsonfabco.filamentkit`; versionCode integer, starts at 1; the server's `apk_version` (from `/opt/filament-kit/app/version.txt`) is that integer.
- QR payload: `fkit://pair?h=<host>.local&p=<port>&t=<token>&fp=<sha256 hex lowercase, no colons>&ip=<ipv4>` (`ip` repeated 0..n).
- TLS: trust only a certificate whose SHA-256 (DER) equals the stored fingerprint; host-name check disabled for that pinned cert only. A different fingerprint → stop and ask the user (never auto-accept).
- Auth: `Authorization: Bearer <token>` on every call except `GET /api/info`, `POST /api/pair`, `GET /app.apk`.
- Server API (JSON): `GET /api/info` → `{name, version, api, apk_version}`; `POST /api/pair {code}` → `{token}`; `POST /api/intake/read` multipart `photo`×1–8 (JPEG ≤ 3 MB each), `hint`, optional `tag` → `{items, questions, tag, usage, read_id}`; `POST /api/intake/retry/{read_id}`; `POST /api/intake/add {items, dry_run, tag}` → `{spool_ids, lines, dry}`; `GET /api/tags/{uid}` → `{spool|null}`; `POST /api/spools/{id}/link {tag, force, dry_run, gross?, location?}` → `{spool}`; `PATCH /api/spools/{id} {gross|remaining|location|empty, dry_run}` → `{spool}`; `GET /api/spools?q=&sealed=1` → `{spools}`; `GET /api/locations` → `{locations}`; `GET /app.apk`.
- Errors: body `{error, message, ...}`; codes `bad_photo`, `bad_request` (400), `unauthorized` (401), `not_found` (404), `tag_conflict` (409, `reason`, `other_spool`), `daily_cap` (429), Claude codes `bad_key|rate_limited|unreachable|refused|truncated|api_error` (502, `read_id`), `spoolman_error` (502, `partial_spool_ids`), `spoolman_unreachable` (503), `internal` (500).
- Printer API (Bearer on all): `GET /api/printers` → `{printers: [{id, name, model, serial, ip, configured: bool, state: "connected"|"offline"|"wrong_code"|"needs_developer_mode"|"not_configured", camera: {kind: "hls"|"mjpeg"|null}, summary: {gcode_state, percent, remaining_min, job}}]}`; `POST /api/printers {serial, access_code, name?}` → `{printer}` (409 `exists`, 400 `bad_request`); `GET /api/printers/{id}` → `{printer, status}` (`status`: `gcode_state`, `stage`, `job`, `percent`, `layer`, `total_layers`, `remaining_min`, `eta`, `temps {nozzle[], bed, chamber}`, `ams [{unit, label, kind, slots [{slot, label, type, color_hex, spool}]}]`, `hms [{code, text}]`, `light`, `updated`); `POST /api/printers/{id}/command {action}` with `pause|resume|stop|light_on|light_off` → `{ok, reply}` (409 `printer_offline`, 504 `no_reply`); camera `GET /api/printers/{id}/camera/index.m3u8` (+ segments under the same path) or `GET /api/printers/{id}/camera.mjpeg` (`multipart/x-mixed-replace`) (404 `not_found` for an unknown printer or a camera of the other kind, 409 `not_configured` when the printer has no Access Code yet, 503 `camera_unavailable` when the stream did not start within 12 s: printer off or LAN mode liveview off). `id` = printer serial.
- Access Codes: stored only in `/var/lib/filament-kit/printers.json` (filament-kit:filament-kit 600); never returned by any API, never logged, never on a command line (ffmpeg reads from the loopback relay).
- Writes always send `dry_run` explicitly: `true` for the preview, `false` for the confirmed write.
- Tag UID format: bytes as lowercase hex without padding joined by `:` (`04 77 90 0E` → `4:77:90:e`), identical to the server's `tags.format_uid`.
- Photos: always JPEG, longest side ≤ 1600 px, quality 85, EXIF orientation applied; must end ≤ 3 MB.
- No owner-specific values (hosts, locations) in code. User-visible text in plain English.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Gradle commands run from `android/` with `JAVA_HOME=G:\Android\jdk-21.0.13+9` and `ANDROID_HOME=G:\Android\Sdk` (`local.properties` is git-ignored).

## Review Focus

1. The server's certificate changes (reinstalled server) → the app must refuse, show old vs new fingerprint and require an explicit re-pair, never silently trust (test in Task 3).
2. Network drops or the server returns 503/502 between Read and Add → the draft (photos + edited fields) survives, including an app kill and restart (test in Task 6).
3. The token is revoked (`unpair`) → any 401 sends the user to the pairing screen with an explanation, not a crash loop (test in Task 4).
4. The server's DHCP address changes → stored endpoints are tried in order (mDNS name, last good, each `ip=`), then NSD discovery; the first that presents the pinned cert wins and is remembered (test in Task 3).
5. A camera returns a huge or rotated image → resized/rotated JPEG ≤ 3 MB, never HEIC/PNG (test in Task 2).
6. Two phones open the same printer's camera and one leaves → the stream keeps running for the other; it stops 45 s after the last viewer, and no ffmpeg process is left behind if the client disconnects mid-segment (test in Task 15).
7. A printer powers off mid-print or its IP changes → state goes `offline` within one keepalive, the next SSDP announce updates the IP and it reconnects without a restart; commands while offline get 409 `printer_offline`, not a hang (test in Task 13).

---

### Task 1: Project scaffold and CI

**Files:** Create `android/settings.gradle.kts`, `android/build.gradle.kts`, `android/gradle.properties`, `android/gradle/libs.versions.toml`, Gradle wrapper, `android/app/build.gradle.kts`, `android/app/src/main/AndroidManifest.xml`, `android/app/src/main/java/com/thompsonfabco/filamentkit/MainActivity.kt`, `android/app/src/test/.../SmokeTest.kt`; modify `.gitignore`, `.github/workflows/` (new `android.yml`).

**Interfaces:**
- Produces: buildable module; `BuildConfig.VERSION_CODE`; manifest permissions `INTERNET`, `CAMERA`, `NFC`, `ACCESS_NETWORK_STATE`, `CHANGE_WIFI_MULTICAST_STATE`, `REQUEST_INSTALL_PACKAGES`, `<uses-feature android:name="android.hardware.nfc" android:required="false"/>`, camera `required="false"`.

- [ ] **Step 1:** Write `SmokeTest` asserting `BuildConfig.APPLICATION_ID == "com.thompsonfabco.filamentkit"`.
- [ ] **Step 2:** Generate the project (wrapper via a temporary `gradle` download or Android Studio template equivalent), Compose enabled, an empty "filament-kit" screen.
- [ ] **Step 3:** Run `./gradlew testDebugUnitTest assembleDebug` → BUILD SUCCESSFUL, APK at `app/build/outputs/apk/debug/`.
- [ ] **Step 4:** Install on the `fk_test` AVD (`emulator -avd fk_test -no-window`), `adb install`, `adb shell am start -n com.thompsonfabco.filamentkit/.MainActivity` → activity resumed (logcat).
- [ ] **Step 5:** CI `android.yml`: ubuntu-24.04, JDK 21 (temurin), `android-actions/setup-android`, `./gradlew testDebugUnitTest assembleDebug`. Commit `feat(android): project scaffold`.

### Task 2: Tag UIDs and photo preparation

**Files:** Create `.../tags/TagUid.kt`, `.../tags/TagEvents.kt`, `.../imaging/PhotoPrep.kt`; tests `TagUidTest.kt`, `PhotoPrepTest.kt` (Robolectric for Bitmap).

**Interfaces:**
- Produces: `fun formatUid(uid: ByteArray): String`; `object TagEvents { val taps: SharedFlow<String>; fun emit(uid: String) }` plus `fun Activity.enableTagReader()/disableTagReader()` (NfcAdapter reader mode for NFC-A/B/F/V, skip NDEF check, emits `formatUid(tag.id)`; no-op without NFC); `fun prepareJpeg(input: ByteArray, maxSide: Int = 1600, quality: Int = 85): ByteArray` (decodes any Android-decodable image, applies EXIF orientation, scales, encodes JPEG; steps quality down by 10 to ≥ 55 until ≤ 3 MB, else throws `IllegalArgumentException("photo too large")`).

- [ ] **Step 1: Failing tests** — `formatUid(byteArrayOf(0x04,0x77,0x90.toByte(),0x0E,0x09,0x22,0x89.toByte())) == "4:77:90:e:9:22:89"`; `prepareJpeg` of a 4000×3000 PNG → starts `FF D8 FF`, max side 1600; an EXIF-rotated (orientation 6) 400×300 JPEG → output 300×400; output ≤ 3 145 728 bytes.
- [ ] **Steps 2–4:** RED → implement → GREEN (`./gradlew testDebugUnitTest --tests '*TagUid*' --tests '*PhotoPrep*'`).
- [ ] **Step 5:** Commit `feat(android): tag uid format and photo preparation`.

### Task 3: Pairing payload, pinned TLS and endpoint selection

**Files:** Create `.../pairing/PairingPayload.kt`, `.../net/PinnedTls.kt`, `.../net/Endpoints.kt`; tests `PairingPayloadTest.kt`, `PinnedTlsTest.kt`, `EndpointsTest.kt` (MockWebServer + okhttp-tls `HeldCertificate`).

**Interfaces:**
- Produces:
  - `data class PairingPayload(val host: String, val port: Int, val token: String, val fingerprint: String, val ips: List<String>)`; `fun parsePairingUri(uri: String): PairingPayload` (throws `IllegalArgumentException` on wrong scheme, missing h/p/t/fp, fp not 64 hex).
  - `fun pinnedClient(fingerprint: String, base: OkHttpClient = OkHttpClient()): OkHttpClient` — TrustManager accepts only a leaf cert whose SHA-256(DER) hex == fingerprint; HostnameVerifier returns true only for that pinned cert; a mismatch raises `FingerprintMismatch(expected: String, actual: String)` (IOException subclass).
  - `fun probeFingerprint(host: String, port: Int): String` — connects with a trust-all manager used **only** to read the presented cert's fingerprint (for manual entry confirmation); never used for API calls.
  - `class Endpoints(stored: List<String>, port: Int)` with `suspend fun firstReachable(client: OkHttpClient, discovered: suspend () -> List<String>): String?` — tries stored order (mDNS name, last good, each ip), then `discovered()`; a reachable host = `GET /api/info` 200 over the pinned client; returns it and moves it to front.
- [ ] **Step 1: Failing tests** — parse the server's real format incl. two `ip=` params and URL-encoded values; reject `http://`; pinned client succeeds against a MockWebServer with `HeldCertificate` whose fingerprint is pinned, while the URL host is `127.0.0.1` but the cert names `pat.local` (host check skipped); a server with a different cert → `FingerprintMismatch` carrying both fingerprints; `Endpoints` skips a dead first host and a wrong-cert second host, returns the third, and puts it first.
- [ ] **Steps 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** Commit `feat(android): pairing payload, pinned TLS, endpoint selection`.

### Task 4: API client

**Files:** Create `.../net/Api.kt`, `.../net/Models.kt`; test `ApiTest.kt` (MockWebServer over TLS with a pinned `HeldCertificate`).

**Interfaces:**
- Consumes: `pinnedClient`, `Endpoints`.
- Produces: `class Api(client: OkHttpClient, baseUrl: () -> String, token: () -> String?)` with suspend funs `info()`, `pair(code)`, `read(photos: List<ByteArray>, hint: String, tag: String?)`, `retry(readId)`, `add(items, dryRun: Boolean, tag: String?)`, `tag(uid)`, `link(spoolId, tag, force, dryRun, gross: Double?, location: String?)`, `update(spoolId, gross?, remaining?, location?, empty: Boolean, dryRun)`, `search(q, sealedOnly)`, `locations()`, `downloadApk(to: File)`. `@Serializable` models mirror the API shapes (unknown keys ignored; `items` kept as `JsonObject` round-trip so edited fields go back exactly). Failures throw `ApiError(status: Int, code: String, message: String, extra: JsonObject)`; 401 → `ApiError` with `code == "unauthorized"`; connection failures → `ApiError(0, "offline", ...)`.
- [ ] **Step 1: Failing tests** — each route's method/path/body/headers (Bearer present except info/pair/apk; multipart has N `photo` parts with `image/jpeg`); `dry_run` always serialized; error bodies map to `ApiError` codes incl. `tag_conflict.reason` and `spoolman_error.partial_spool_ids`; 401 → `unauthorized`; socket refused → `offline`; an `items` object with an unknown field round-trips unchanged into `add`.
- [ ] **Steps 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** Commit `feat(android): API client`.

### Task 5: Settings store and pairing screens

**Files:** Create `.../data/Settings.kt` (DataStore), `.../ui/pair/PairScreen.kt`, `.../ui/pair/QrScanner.kt` (CameraX + ML Kit), `.../ui/pair/ManualPair.kt`, `.../net/Discovery.kt` (NsdManager `_filamentkit._tcp`); tests `SettingsTest.kt` (Robolectric), `PairFlowTest.kt` (Compose UI test, instrumented).

**Interfaces:**
- Produces: `Settings` with `server: Flow<ServerConfig?>` (`ServerConfig(endpoints: List<String>, port: Int, fingerprint: String, token: String, name: String)`), `save(ServerConfig)`, `clear()`. Pair screen offers: Scan QR (parses with `parsePairingUri`, saves, verifies with `info()`), Servers found on this network (NSD list → host → manual flow), Enter address (host/IP + port default 8710 → `probeFingerprint` shown as 4-char groups for confirmation → 6-digit code → `pair(code)`). On success navigate Home. Settings screen: server name/address, "Pair again", "Forget server".
- [ ] **Step 1: Failing tests** — `Settings` round-trips and clears; manual flow: fingerprint shown before any code is sent; wrong code shows the server's message; success saves config with the probed fingerprint.
- [ ] **Steps 2–4:** RED → implement → GREEN (`connectedDebugAndroidTest` on `fk_test` for the UI test).
- [ ] **Step 5:** Commit `feat(android): pairing and settings`.

### Task 6: Drafts

**Files:** Create `.../drafts/DraftStore.kt`; test `DraftStoreTest.kt` (JVM, temp dir).

**Interfaces:**
- Produces: `data class Draft(id: String, photos: List<File>, hint: String, tag: String?, weightGrams: Double?, sealed: Boolean, readResult: JsonObject?, editedItems: JsonArray?, created: Long)`; `class DraftStore(dir: File)` with `create()`, `addPhoto(id, jpeg: ByteArray)`, `update(draft)`, `list()`, `get(id)`, `delete(id)`. One folder per draft: `draft.json` (atomic write) + `photoN.jpg`. Deleted only after a successful real add.
- [ ] **Step 1: Failing tests** — create/add photos/update/list survive a new `DraftStore` on the same dir; delete removes the folder; a corrupt `draft.json` is skipped, not fatal.
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(android): drafts`.

### Task 7: Add-spools flow

**Files:** Create `.../ui/add/CaptureScreen.kt`, `.../ui/add/ReviewScreen.kt`, `.../ui/add/AddViewModel.kt`; test `AddViewModelTest.kt` (JVM with a fake `Api`), `AddFlowTest.kt` (instrumented).

**Interfaces:**
- Consumes: `prepareJpeg`, `DraftStore`, `Api`, tag events (Task 8's `TagEvents`).
- Produces: flow: Capture (CameraX, 1–8 photos, thumbnails, delete) → tag (optional, from a tap during the flow) → weight field (grams) or "Sealed" toggle → Read (`api.read`) → Review (per item: vendor, name, material, color swatch from `color_hex`, count, net, tare, location; Claude `questions` shown on top; estimates marked "estimated") → Preview (`add(dry_run=true)`, shows `lines`) → Add (`add(dry_run=false)`) → result with spool ids; draft deleted. For a single opened spool with a weight: `gross` set on the item. Errors: `daily_cap`, Claude codes (with Retry using `read_id`), `offline`, `spoolman_unreachable`, `spoolman_error` (shows created ids) — each a plain message; the draft is kept.
- [ ] **Step 1: Failing tests** — view model: read → review state; edited fields go into `add`; preview always `dry_run=true`, confirm always `false`; `offline` during Add keeps the draft and shows retry; weight + single opened spool → `gross` in the item; `daily_cap` message.
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(android): add spools flow`.

### Task 8: Tag taps and the spool card

**Files:** Modify `MainActivity.kt` (reader mode on resume/off on pause via Task 2's helpers; debug builds add a "Simulate tag" button that calls `TagEvents.emit` with a typed UID); create `.../ui/spool/SpoolCard.kt`, `.../ui/spool/SpoolViewModel.kt`, `.../ui/spool/LinkSealedScreen.kt`; tests `SpoolViewModelTest.kt`.

**Interfaces:**
- Produces: a tap anywhere outside the add flow → `api.tag(uid)`: known → Spool card (brand, name, color, location, remaining; actions Update weight (gross g → `update(gross, dry_run=true)` preview → confirm), Move (location list from `api.locations()`), Mark empty (confirm dialog)); unknown → choice "Link to a sealed spool" (search `sealed=1`, pick → `link(dry_run=true)` preview → confirm, optional gross) or "Add as new" (starts Task 7's flow with the tag preset). `tag_conflict` shows which spool holds the tag and offers "Move tag here" (`force=true`). "Load into printer" is not shown (Bambu bridge plan).
- [ ] **Step 1: Failing tests** — known tag → card state; unknown → choice; link preview uses `dry_run=true`, confirm `false`; conflict → state with `other_spool` and force path; mark empty sends `empty=true`.
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(android): tag taps and spool card`.

### Task 9: Home, search, app updates

**Files:** Create `.../ui/home/HomeScreen.kt`, `.../ui/search/SearchScreen.kt`, `.../update/Updater.kt`; tests `UpdaterTest.kt`.

**Interfaces:**
- Produces: Home: Add spools, Search, open drafts list (resume), server name + connection dot, Settings. Search: query box → `api.search(q, sealedOnly)` → tap opens the spool card. Updater: on start and daily, `info().apk_version > BuildConfig.VERSION_CODE` → banner "Update available" → `downloadApk` → `PackageInstaller` session install (asks for "install unknown apps" once, via `Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES`). Global 401 handler → Pair screen with "This phone was unpaired from the server".
- [ ] **Step 1: Failing tests** — updater decides correctly for null/equal/higher versions; a 401 from any call routes to Pair with the message.
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(android): home, search, updates`.

### Task 10: Release signing and packaging

**Files:** Create `tools/android_keystore.ps1`, modify `android/app/build.gradle.kts` (release signing from env `FK_KEYSTORE`, `FK_KEYSTORE_PASSWORD`), `tools/make_release.sh` (build `assembleRelease` when the keystore env is set; copy `app-release.apk` → `app/filament-kit.apk` and versionCode → `app/version.txt`), `README.md` (install the APK).

**Interfaces:**
- Produces: `android_keystore.ps1` creates `%LOCALAPPDATA%\filament-kit\release.jks` once with a random password stored via DPAPI (`%LOCALAPPDATA%\filament-kit\keystore.pw.dpapi`), never printed; `make_release.sh` reads it through a tiny PowerShell helper. The keystore must be backed up by the owner (README says where and why: updates need the same key).
- [ ] **Step 1:** Write the script and Gradle config; run `./gradlew assembleRelease` with the env → signed APK (`apksigner verify --print-certs`).
- [ ] **Step 2:** `bash tools/make_release.sh` → tarball contains `app/filament-kit.apk` and `app/version.txt`.
- [ ] **Step 3:** Commit `feat(android): release signing and packaging`.

### Task 11: End-to-end test in the emulator

**Files:** Create `android/app/src/androidTest/.../EndToEndTest.kt`, `docs/android-e2e.md`.

**Interfaces:**
- Consumes: everything; the WSL Ubuntu test server (reachable from the emulator at `10.0.2.2:8710`; WSL forwards localhost); pairing code and fingerprint passed as instrumentation args (`-e fkCode <code> -e fkHost 10.0.2.2`); a label photo pushed to the emulator before the run (`adb push <photo> /data/local/tmp/label.jpg`, path passed as `-e fkPhoto`) — the owner's photos are never committed.
- [ ] **Step 1:** Test: manual pair (host `10.0.2.2`, confirm fingerprint, code) → Add spools with the asset photo injected instead of the camera → Read → Preview → Add → simulate a tap with a new UID on the new spool → card shows it; Update weight; unpair from the server mid-test (`wsl -d Ubuntu -- sudo filament-kit unpair <id>`) → next call lands on Pair with the unpaired message.
- [ ] **Step 2:** Run `./gradlew connectedDebugAndroidTest` on `fk_test` with the args → PASS; record in `docs/android-e2e.md`.
- [ ] **Step 3:** Commit `test(android): end-to-end against a real server`.

### Task 12: Printer registry and SSDP discovery (server)

**Files:** Create `server/filament_kit/bridge/__init__.py`, `bridge/registry.py`, `bridge/discovery.py`; modify `cli.py` (config menu `5) Printers`: list, add manually, rename, remove); tests `server/tests/test_registry.py`, `test_discovery.py`.

**Interfaces:**
- Produces: `registry.Printer` dataclass (`serial, name, model, ip, access_code (repr hidden), configured`); `registry.load() -> dict[str, Printer]`, `registry.upsert(p)`, `registry.remove(serial)`, `registry.detected(serial, ip, model, name)` (adds or updates an unconfigured entry, updates `ip` of a configured one) — file `state/printers.json`, mode 600, atomic, same lock pattern as `pairing._locked`. `discovery.parse_notify(data: bytes) -> dict | None` (headers `Location`, `USN`, `DevModel.bambu.com`, `DevName.bambu.com`, `DevConnect.bambu.com`; case-insensitive); `discovery.Listener(on_found)` binds UDP 2021 (SO_REUSEADDR) in a thread.
- [ ] **Step 1: Failing tests** — parse a Bambu NOTIFY built from the format above (CRLF and lowercase-header variants); garbage → None; `detected()` adds unconfigured, updates the IP of a configured one, never touches its access code; `printers.json` mode 600 (POSIX); `repr(Printer)` hides the code; CLI add/rename/remove via scripted stdin; the access code is never printed.
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(bridge): printer registry and discovery`.

### Task 13: MQTT connection and status (server)

**Files:** Create `bridge/connection.py`, `bridge/status.py`; add `paho-mqtt` to `server/pyproject.toml`; tests `test_status.py`, `test_connection.py`, `server/tests/data/h2d_pushall.json` + `h2d_delta.json` (built from the field usage in the owner's `remote.py`; no secrets).

**Interfaces:**
- Consumes: registry.
- Produces: `status.merge(full: dict, delta: dict) -> dict` (deep merge; lists element-wise as Bambu sends them); `status.summarize(report: dict, spools: list[dict]) -> dict` (the `status` shape in Global Constraints; stage names ported from `remote.py`; AMS labels A1–D4 / HT-A…; slots joined to Spoolman spools whose `location` is `"<printer name> – AMS <label>"`); `connection.Manager` — one `PrinterConnection` per configured printer (paho, TLS without verification, user `bblp`, password = Access Code; subscribe `device/<serial>/report`; `pushall` on connect and 1.5 s after each command; reconnect with backoff 2 → 60 s; states `connected|offline|wrong_code|needs_developer_mode` (MQTT rc 5 → `wrong_code`; a command reply with `result: fail` and an authorization reason → `needs_developer_mode`)); `Manager.command(serial, action) -> dict` waits ≤ 10 s for the reply with the matching `sequence_id` (`pause|resume|stop` → `print.command`; `light_on|light_off` → `system` `ledctrl` `chamber_light`); offline → `PrinterOffline`; no reply → `NoReply`. The paho client is injected (`client_factory`) so tests drive it with a fake.
- [ ] **Step 1: Failing tests** — merge keeps untouched keys and replaces list elements; summarize gives stage text, percent, eta, temps, AMS labels and joins a spool; fake client: connect → pushall published; rc 5 → `wrong_code`; disconnect → `offline`, then reconnect with backoff; a registry IP change → reconnect to the new IP; `command("pause")` publishes the right JSON and returns the reply; offline → `PrinterOffline`; a silent printer → `NoReply` after the (patched, 0.2 s) timeout.
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(bridge): mqtt connection, status, commands`.

### Task 14: Printer API routes (server)

**Files:** Modify `server/filament_kit/api.py`, `__main__.py` (start the discovery listener and connection manager with the app, stop them on shutdown); tests `test_api_printers.py`.

**Interfaces:**
- Consumes: registry, discovery, connection, status.
- Produces: the printer routes in Global Constraints. `POST /api/printers` stores the code, starts the connection, waits ≤ 8 s for the first state and returns it (so the app can say "wrong code" at once). Commands are logged with `device_id`, `serial`, `action`, result at INFO (never the code). Errors: `printer_offline` 409, `no_reply` 504, `not_found` 404, `exists` 409.
- [ ] **Step 1: Failing tests** (TestClient + fake Manager): list shows detected and configured printers with states; add → 200 with state, duplicate → 409; status shape; command ok / offline 409 / no reply 504; no response body contains an access code (checked in every test); 401 without a token.
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(api): printer routes`.

### Task 15: Camera relay (server)

**Files:** Create `bridge/camera.py`; modify `api.py` (camera routes), `install/install.sh` (apt `ffmpeg`), `install/systemd/filament-kit.service` (`RuntimeDirectory=filament-kit` for HLS segments on tmpfs); tests `test_camera.py`.

**Interfaces:**
- Produces: `camera.Hub` — per printer, reference-counted viewers; the first viewer starts the source, `release()` schedules a stop after 45 s. RTSP models (X1 series, H2D, X2D families; table in code): port the loopback RTSP relay from `remote.py` (TLS + Digest auth to `rtsps://<ip>:322/streaming/live/1`) and run `ffmpeg -rtsp_transport tcp -i rtsp://127.0.0.1:<relay>/... -c copy -f hls -hls_time 1 -hls_list_size 4 -hls_flags delete_segments` into `$RUNTIME_DIRECTORY/cam/<serial>/`; routes serve only `index.m3u8` and `*.ts` from there. P1/A1 (port 6000): TLS socket, 80-byte auth packet (user `bblp`, Access Code), then 16-byte header + JPEG frames; the route streams `multipart/x-mixed-replace; boundary=frame` at ≤ 5 fps. A viewer = an open MJPEG response, or an HLS fetch within the last 10 s.
- [ ] **Step 1: Failing tests** — refcount: two viewers, one leaves → still running; both leave → stopped after the (patched) delay; the ffmpeg command line never contains the access code; a fake port-6000 server (TLS, checks the auth packet, sends 3 frames) → the MJPEG route yields 3 parts; the HLS route refuses `../` and names other than `.ts`/`.m3u8`; the source process is killed on Hub shutdown (no orphans).
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(bridge): camera relay`.

### Task 16: Printers screens (app)

**Files:** Create `.../ui/printers/PrintersScreen.kt`, `PrinterScreen.kt`, `PrinterViewModel.kt`, `MjpegView.kt`, `HlsPlayer.kt`; modify `Api.kt` / `Models.kt` (printer routes) and Home (Printers entry); tests `PrinterViewModelTest.kt`, `ApiPrintersTest.kt`, `MjpegParserTest.kt`.

**Interfaces:**
- Consumes: Api, pinned client.
- Produces: Printers list (name, model, state dot, job + percent while printing; an unconfigured printer → "Add printer" dialog asking for the Access Code, with help text "on the printer: Settings → Network/LAN → Access Code"); printer screen: camera on top (Media3 HLS through `OkHttpDataSource.Factory(pinnedClient)` with the Bearer header, or `MjpegView` reading the multipart stream), status below, polling every 2 s only while visible, controls (Pause or Resume by state; Stop → confirm → second confirm naming the printer and job; Light toggle); each command shows the printer's reply or the error (`printer_offline`, `no_reply`). States `wrong_code` / `needs_developer_mode` show the fix in plain words.
- [ ] **Step 1: Failing tests** — printer API routes (MockWebServer); the MJPEG parser yields frames from a multipart stream split across reads; view model: polls only while active, Stop needs two confirms, a 409 shows "printer is offline".
- [ ] **Steps 2–4:** RED → implement → GREEN. **Step 5:** Commit `feat(android): printers and camera`.

### Task 17: Real-printer check on the owner's H2D

The owner's OK is required before starting, and the H2D must be idle. Read-only plus the chamber light only: never pause, resume or stop a real printer in this task.
- [ ] **Step 1:** On the WSL test server, confirm the H2D shows up via SSDP; the owner enters its Access Code through the app or `filament-kit config` (never typed by the agent).
- [ ] **Step 2:** Status fields match the printer screen (state, temps, AMS slots); the camera plays in the emulator (HLS); light on → off with the reply shown.
- [ ] **Step 3:** Record results in `docs/android-e2e.md`; commit `test: real-printer check (H2D)`.

## Execution waves (parallel where independent)

W1: Tasks 1, 12 · W2: Tasks 2, 3, 6, 13 · W3: Tasks 4, 14, 15 · W4: Tasks 5, 7, 8, 16 · W5: Tasks 9, 10 · W6: Task 11 · W7: Task 17 (owner present).
