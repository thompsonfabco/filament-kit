# Android end-to-end test (emulator + real server)

`android/app/src/androidTest/java/com/thompsonfabco/filamentkit/EndToEndTest.kt` drives the whole app
(`MainActivity`) against a real filament-kit server. It is skipped unless `fkPhase` is passed, so a plain
`./gradlew connectedDebugAndroidTest` runs only the other instrumented tests.

## Phases

Run them in this order. Each phase is its own instrumentation run, so `cold` starts in a new process. Keep the APKs
installed between runs (`leaveApksInstalledAfterRun`), otherwise the app data is lost.

| Phase | Arguments | What it checks |
|---|---|---|
| `main` | `fkCode`, `fkHost`, `fkPhoto`, optional `fkPort` (8710), optional `fkFingerprint` | Manual pairing (host, fingerprint shown and compared, code) → Printers shows the empty state → Add spools with the label photo injected instead of the camera, a new random tag and a weight → Read (one paid Claude call) → Preview shows `would link tag …` → Add → `linked tag … to spool N` → the tag tapped on Home opens the new spool's card → Update weight → Confirm → the test logs `UNPAIR_NOW` and the driver unpairs the phone on the server → the next call (a tag lookup) lands on Pair with "This phone was unpaired from the server", and the spool card is closed. |
| `unpair` | `fkTag` | Only the last step of `main`, on the phone `main` left paired. Use it to repeat that step without another paid Read. |
| `cold` | none | Cold start after the unpair: the app opens Pair and still shows the unpaired message. |
| `forget` | `fkCode`, `fkHost`, ... | Pair again → Settings → Forget server → Pair (no unpaired message), and still Pair after the activity is recreated. |

`fkStopBeforeRead=1` stops `main` right before Read, for a free rehearsal. The `main` phase needs the server's
`ai_intake` module on, with an API key.

With `fkPhase` the test grants CAMERA and `ACCESS_LOCAL_NETWORK` before the app starts. Without `fkPhase` it skips
before any rule runs (it does not even start the activity), so the default run keeps `ACCESS_LOCAL_NETWORK` denied.

## Local network permission (API 37)

`ACCESS_LOCAL_NETWORK` governs every LAN socket the app opens: API calls, the certificate probe, camera streams, the
APK download and NSD browsing. The app asks for it the first time it needs the network (API 37+ only). While it is
missing the app does not browse, probe, verify or pair, the session does not look for the server (Home shows "Needs
local network access", never "Can't reach the server"), and a failed connection says the permission is missing
instead of "offline". Pair and Home show a plain explanation with **Allow**, plus **Open app settings** once
Android stops showing its dialog.

`LocalNetworkDeniedTest` covers the denied state on the emulator in the default run: the app is installed fresh
without the grant; it refuses the system dialog, checks the explanation and **Allow** (and that no QR scan or
"Can't reach the server" is shown), asks again, refuses again and checks **Open app settings**. To rerun it after the
permission was granted, revoke it first (revoking kills the app, so do it between runs, never inside a test):

```bash
$ADB shell pm revoke com.thompsonfabco.filamentkit android.permission.ACCESS_LOCAL_NETWORK
```

On the emulator the permission is a normal runtime permission; if a future image enforces it only behind the
compatibility change, also run `$ADB shell am compat enable RESTRICT_LOCAL_NETWORK com.thompsonfabco.filamentkit`.

### Checks on a real phone (Android 17 / API 37), not automated

1. Install the app fresh (or `adb shell pm clear com.thompsonfabco.filamentkit`) and open it: the system asks for
   local network access (it may be shown as "Nearby devices"). Tap **Don't allow**: Pair shows the explanation and
   **Allow**, and no QR scan button; no "Choose a device to connect" picker appears.
2. Tap **Allow** in the app and refuse again: **Open app settings** takes the place of **Allow** and opens the app's settings page. Allow
   the permission there and return: the Pair screen (QR scan, servers found on this network) appears without
   restarting the app.
3. Pair by QR. Then revoke the permission in the system settings (Android restarts the app): Home shows "Needs local
   network access" with **Allow**, not "Can't reach the server". Allow it: Home turns to "Connected".
4. With the permission granted, check Printers (camera view, HLS playback in the app), Search, Add spools and an
   app update download once.

The certificate-change case is a separate instrumented test, `net/PinnedTlsDeviceTest.kt`: a MockWebServer with
another `HeldCertificate` checks that Android's TLS stack (Conscrypt) surfaces a bare `FingerprintMismatch` with both
fingerprints, also through `Api`, and not an `SSLHandshakeException` or `offline`. It needs no server and runs with the
other instrumented tests.

## How to run (Git Bash on a Windows dev PC)

Server: a test install in WSL (`wsl -d Ubuntu`), reachable from the emulator at `10.0.2.2:8710`. The label photo is
never committed; it is pushed to the emulator only. Set `ANDROID_HOME` and `JAVA_HOME` to your SDK and JDK 21.

```bash
ADB=$ANDROID_HOME/platform-tools/adb.exe
$ANDROID_HOME/emulator/emulator.exe -avd fk_test -no-window -no-audio -no-snapshot -gpu swiftshader_indirect &
# wait for: $ADB shell getprop sys.boot_completed  ->  1

MSYS_NO_PATHCONV=1 $ADB push <label photo>.jpg /data/local/tmp/label.jpg
$ADB shell pm clear com.thompsonfabco.filamentkit      # main starts from an unpaired app (ignore an error if not installed)

# one phase; CODE from: wsl -d Ubuntu --exec bash -lc 'sudo filament-kit pair'   ("Pairing code: NNNNNN")
P=-Pandroid.testInstrumentationRunnerArguments
cd android
MSYS_NO_PATHCONV=1 ./gradlew connectedDebugAndroidTest \
  -Pandroid.injected.androidTest.leaveApksInstalledAfterRun=true \
  $P.class=com.thompsonfabco.filamentkit.EndToEndTest $P.fkPhase=main \
  $P.fkCode=$CODE $P.fkHost=10.0.2.2 $P.fkFingerprint=<fingerprint from 'filament-kit status'> \
  $P.fkPhoto=/data/local/tmp/label.jpg
```

`MSYS_NO_PATHCONV=1` stops Git Bash from rewriting `/data/local/tmp/...` into a Windows path.

During `main` (and `unpair`), run this next to it; it waits for `UNPAIR_NOW` and revokes the one device paired since
it started (set `BASE` to the device ids listed before the run):

```bash
BASE="<ids from: wsl -d Ubuntu --exec bash -lc 'sudo filament-kit unpair'>"
list() { wsl -d Ubuntu --exec bash -lc 'sudo filament-kit unpair' 2>/dev/null | awk '{print $1}' | sort; }
until $ADB logcat -d -s FkE2E:I | grep -q UNPAIR_NOW; do sleep 1; done
new=$(comm -13 <(echo $BASE | tr ' ' '\n' | sort) <(list))
wsl -d Ubuntu --exec bash -lc "sudo filament-kit unpair $new"
```

Then `fkPhase=cold` (after `$ADB shell am force-stop com.thompsonfabco.filamentkit`) and `fkPhase=forget` (new
code). Afterwards unpair the device `forget` paired (`sudo filament-kit unpair <id>`). `main` adds one real spool to
the server's Spoolman each run (the test logs `ADDED spool=N tag=…`); it is left in place.

The test's progress is in logcat under the tag `FkE2E`.

A server in WSL sees no printers (WSL is behind NAT), so the test only checks the Printers empty state; printer
features are checked on a real phone against a real printer.
