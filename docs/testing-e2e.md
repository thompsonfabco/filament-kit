# End-to-end run on WSL

`tools/e2e/run.sh` installs filament-kit for real on a Linux host, the way a user does, and checks that the pieces
work together: the signed release and get.sh, the installer and its modules, the real Spoolman, the kit server, the
web unit with the reader API, a fake Bambu printer with 16 AMS units, the updater with its hardware data feed and
the rollback, and a station upgrade. It is made for the WSL Ubuntu on the dev PC and puts the host back as it
found it.

```
wsl -d Ubuntu -- sudo bash /mnt/c/<checkout>/tools/e2e/run.sh
```

Options: `--only a,d,c,b,e` runs some scenarios (the later ones need a), `--previous vX.Y.Z` adds scenario f
(from a clone with its tags), `--results FILE` copies the results
(JSON, every check with its outcome) to FILE, and `--keep-work` keeps the work folder in `/tmp/fk-e2e.*` for
debugging (it holds the throwaway release key and the command logs; delete it afterwards). A full run takes about
15 minutes, most of it pip and apt.

## Needs

- Ubuntu 24.04 or newer as root (`sudo` without a password in the WSL distro), with `python3` and
  `python3-cryptography`.
- Internet: apt, PyPI (the kit's and Spoolman's Python packages, `build` for the wheel) and the Spoolman release
  zip on GitHub. Spoolman is the real one (0.27.0, from the `spoolman` module); nothing is stubbed.
- No filament-kit on the host (it refuses when `/etc/filament-kit`, `/opt/filament-kit`, `/var/lib/spoolman` or
  the like exist) and ports 7912, 8101, 8710 and 8883 free.
- Nothing else: everything it starts listens on 127.0.0.1, and no live printer, VM or station is touched.

## What it does

1. **Builds two releases** of the checkout it is in: a copy of the tree gets a fresh ed25519 key pair made for
   the run (`tools/sign_release.py set-pubkey` into the copy's `release.py` and `get.sh`; the checkout itself is
   never changed), the version is set (the checkout's, then one patch higher) and `tools/make_release.sh` builds
   the tarball (`FK_NO_APP=1`, no library asset) and `bambu_hardware.xml`. `SHA256SUMS` lists both and is signed
   with `tools/sign_release.py sign` and the throwaway key.
2. **Serves them** with `python3 -m http.server` on 127.0.0.1 as a fake GitHub releases API: files at
   `repos/<owner>/<repo>/releases/latest` and `.../tags/v<version>` in the GitHub JSON shape, assets under `dl/`.
   get.sh reaches it with `--api http://127.0.0.1:<port>`, the updater with `"updates": {"api", "repo"}` in
   config.json. `--api` and a set-pubkey copy of get.sh are test hooks only; the published get.sh carries the real
   key and talks to api.github.com.
3. **Runs the scenarios**, with no terminal (as a piped install), and records every check.
4. **Cleans up** (also after a failure or Ctrl-C): `uninstall.sh --purge`, the station's system changes undone
   (sleep targets unmasked unless they were masked before, ALSA state restored), packages the run installed
   purged (and any it removed put back), the work folder deleted. Then it compares the host with a snapshot taken
   at the start: packages, unit files and `/etc/systemd/system`, the kit's loaded units, `/etc/passwd` and
   `/etc/group`, the kit's paths, the ALSA state and root's home. Any difference is printed and fails the run. Not
   compared: apt's package lists (`apt-get update`) and the journal.

## Scenarios

| | Scenario | Checks |
|---|---|---|
| a | Install from the fake release server | A tampered tarball and a release signed by another key are refused and nothing is installed. `get.sh --modules spoolman,server,printers,web --set web.public_url=...` installs the first release: spoolman, filament-kit and filament-kit-web active, the kit API answers its version, Spoolman and the web unit answer, `filament-kit status` exits 0, the verified release is kept for rollback. |
| d | Manual add without AI | Server mode with no API key: `ai_intake` off, no key file, `/api/intake/read` answers `module_off`. A phone is paired through `/api/pair`; `/api/intake/add` (dry run, then for real, with a tag) adds a spool that Spoolman shows with its filament, vendor and tag. |
| c | Fake 16-unit printer through the reader API | `tools/e2e/fake_printer.py` is an MQTT 3.1.1 broker over TLS on 127.0.0.1:8883 around the unit tests' `FakePrinter`: 16 AMS units, 8 AMS HT units and both external holders, a self-signed leaf with CN = serial, user `bblp` and a throwaway Access Code. It is added as `filament-kit config` > Printers > add printer does (`registry.upsert`). `sudo filament-kit reader token` makes the reader token; `GET reader/printers` lists it, `GET reader/printers/<id>/slots` gives 74 unique labels (also ignoring case, at most 40 bytes), and `POST reader/scan` of the spool from d into P3 answers `set`. The printer received exactly one `ams_filament_setting`, for AMS 15 tray 2 with the preset's filament id, and Spoolman shows the spool in that slot. The preset comes from a one-preset build written into `/var/lib/filament-kit/profiles`, as the PC sync and `profiles build` leave it (the reader loads only with the user's exact preset). |
| b | Updater | `update --check` says up to date, then sees the second release once it is published; `update` installs it (services active again, the API answers the new version) and the hardware feed installs the release's newer `bambu_hardware.xml` (version 1.1) as `/etc/filament-kit/bambu_hardware.xml`. A newer valid file (1.2) swaps in with the old one kept as `.previous`; a signed but invalid one (1.3 with an empty model name) is refused (exit 1) and the installed file stays. `update --rollback` restores the first release, and `update --check` then says the rolled-back version is held from the timer. |
| e | Station upgraded by the updater | After a purge: `get.sh --version <first> --mode station --server 192.0.2.10` (a documentation address), then `filament-kit update` to the second release. Still station mode, `station.allow` still the server address, and the station unit's drop-in still allows it. |
| f | The last released tag (`--previous`) | After a purge, the tag's own files build its release and its own `get.sh` installs it; a phone is paired and a spool added. The tag's own updater installs this checkout (one patch higher) and this checkout's `update --rollback` goes back: each time the services run, the API answers the right version, the token works and the spool is there. |

## On a runner, before a tag

The `e2e` workflow is started by hand (Actions, Run workflow) on the commit to be tagged, and runs all of the above with `--previous` set to the newest tag, or the tag you give it. A runner is not a minimal Ubuntu, so its apt path proves less than a clean VM would.

## Results and logs

The run prints `ok` / `FAIL` per check and a line per scenario (`pass`, `fail`, or `skip: <why>`). Each command's
output is in `<work>/log/NN-<step>.log` (kept with `--keep-work`); the reader token's command is not logged. Exit
status 0 means every scenario passed or was skipped and the host is as it was.

## Bugs it found (fixed with unit tests)

- `install.sh --modules ...` always failed: a `'` inside the custom-mode `python -c '...'` block ended the shell
  word, so Python got a cut program (`test_inline_python_survives_shell_single_quotes`).
- get.sh did not pass `--set` on to install.sh, so a piped `--modules ...,web` install could not be given
  `web.public_url` (`test_get_sh_takes_set_for_install_sh`).
- `sudo filament-kit reader token` (and `revoke`) always refused: the wrapper ran them as the service user
  (`test_wrapper_runs_reader_token_and_revoke_as_root`).
