# Android end-to-end test (emulator + real server)

`android/app/src/androidTest/java/com/thompsonfabco/filamentkit/EndToEndTest.kt` drives the whole app
(`MainActivity`) against a real filament-kit server. It is skipped unless `fkPhase` is passed, so a plain
`./gradlew connectedDebugAndroidTest` runs only the other instrumented tests.

## Phases

Run them in this order. Each phase is its own instrumentation run, so `cold` starts in a new process. Keep the APKs
installed between runs (`leaveApksInstalledAfterRun`), otherwise the app data is lost.

| Phase | Arguments | What it checks |
|---|---|---|
| `main` | `fkCode`, `fkHost`, `fkPhoto`, optional `fkPort` (8710), `fkFingerprint` | Manual pairing (host, fingerprint shown and compared, code) → Printers shows the empty state → Add spools with the label photo injected instead of the camera, a new random tag and a weight → Read (one paid Claude call) → Preview shows `would link tag …` → Add → `linked tag … to spool N` → the tag tapped on Home opens the new spool's card → Update weight → Confirm → the test logs `UNPAIR_NOW` and the driver unpairs the phone on the server → the next call (a tag lookup) lands on Pair with "This phone was unpaired from the server", and the spool card is closed. |
| `unpair` | `fkTag` | Only the last step of `main`, on the phone `main` left paired. Use it to repeat that step without another paid Read. |
| `cold` | none | Cold start after the unpair: the app opens Pair and still shows the unpaired message. |
| `forget` | `fkCode`, `fkHost`, ... | Pair again → Settings → Forget server → Pair (no unpaired message), and still Pair after the activity is recreated. |

`fkStopBeforeRead=1` stops `main` right before Read, for a free rehearsal.

The test grants CAMERA and `ACCESS_LOCAL_NETWORK`. Without the second one, API 37 shows the system device picker
("Choose a device to connect") over the app as soon as the Pair screen browses for servers.

The certificate-change case is a separate instrumented test, `net/PinnedTlsDeviceTest.kt`: a MockWebServer with
another `HeldCertificate` checks that Android's TLS stack (Conscrypt) surfaces a bare `FingerprintMismatch` with both
fingerprints, also through `Api`, and not an `SSLHandshakeException` or `offline`. It needs no server and runs with the
other instrumented tests.

## How to run (Git Bash, Windows dev PC)

Server: the WSL test server (`wsl -d Ubuntu`), reachable from the emulator at `10.0.2.2:8710`. The label photo is the
owner's and is never committed; it is pushed to the emulator only.

```bash
ADB=/g/Android/Sdk/platform-tools/adb.exe
/g/Android/Sdk/emulator/emulator.exe -avd fk_test -no-window -no-audio -no-snapshot -gpu swiftshader_indirect &
# wait for: $ADB shell getprop sys.boot_completed  ->  1

MSYS_NO_PATHCONV=1 $ADB push <label photo>.jpg /data/local/tmp/label.jpg
$ADB shell pm clear com.thompsonfabco.filamentkit      # main starts from an unpaired app (ignore an error if not installed)

# one phase; CODE from: wsl -d Ubuntu --exec bash -lc 'sudo filament-kit pair'   ("Pairing code: NNNNNN")
P=-Pandroid.testInstrumentationRunnerArguments
cd android
MSYS_NO_PATHCONV=1 JAVA_HOME=/g/Android/jdk-21.0.13+9 ANDROID_HOME=/g/Android/Sdk ./gradlew connectedDebugAndroidTest \
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

## Result, 2026-11-01 (fk_test, API 37, server = android-app build, Spoolman 0.27.0)

| Run | Result |
|---|---|
| `main` | PASS (1 test, 3 skipped): paired, Printers empty, read "CONJURE Glow in the Dark Rainbow No.6" (existing filament F2), added spool #4 with tag `1a:9e:d9:5:57:e1:de`, card opened from the tag, weight 700 g → 500 g left, unpaired on the server → Pair with the unpaired message within 4 s |
| `cold` | PASS |
| `forget` | PASS |
| `unpair` | PASS (run once on its own, after an earlier `main` whose watcher had failed; spool #3, tag `2e:ae:63:22:c8:a5:9`) |
| all instrumented tests without `fkPhase` | 10 tests, 0 failures, 4 skipped (the E2E phases): `AddFlowTest`, `PairFlowTest`, `PinnedTlsDeviceTest` (4) |

Printers: the WSL server sees no printers (WSL is behind NAT), so only the empty state was checked; the real printer
check is the hardware test.
