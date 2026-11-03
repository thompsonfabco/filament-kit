# filament-kit for everyone: one-command install, module menu, optional AI, updater, XML data — design

Date: 2026-11-02. Status: awaiting owner approval. Sub-project 6. Builds on `merge-ops` and the printers design
(`2026-11-02-bambu-printers-design.md`, sub-project 5).

## 1. The owner's goal (their words, condensed)

1. A normal user copies ONE command from the GitHub repo into a Linux console; it downloads and runs the installer.
2. They get a menu of modules to pick by need; anything that depends on another module says so clearly.
3. AI is an optional feature, never a requirement.
4. All Bambu printers are supported (sub-project 5).
5. Data lives in data files, not in the program; XML is the format, for new AND existing data files.
6. An optional auto-updater updates the program and pulls new data.
7. The filament-library is optional, downloaded on request, and used as the initial source for filament profiles.

Owner decisions (2026-11-02, refined 22:38): the repo goes **public only when the owner says so**, after the whole project reaches strong beta; until then everything stays private and the bootstrap is built so it works once public (tested privately now). **XML for everything, but the conversion of existing JSON files is deferred** (logged as later work); new data files are XML now.

## 2. Components

### 2.1 Public repo, with the owner's private data scrubbed
- Move everything owner-specific out of the public tree into a private companion repo (`filament-kit-owner`,
  private): the filament-ops migration runbook with real hostnames/IPs, `migrate-ops` owner defaults (SV08 map,
  Cereal boxes, tare hints, H2D slot service, mcp.example.com), the panel PANEL.md wiring notes if they name the
  owner's setup, docs that cite 192.168.1.x, test fixtures carrying the owner's serials/IPs (replaced by fakes).
  The public `migrate-ops` stays generic (reads a bundle + an owner profile XML from the private repo).
- History: the public repo starts from a squashed or filtered history (`git filter-repo`) with a pre-publish scan:
  gitleaks-style secret scan, plus a word list (owner IPs, hostnames, serials, email, VM names). Nothing is pushed
  public until the owner reviews the scan report and says go.
- Android release keystore, PC sync signing, OTA keys never enter the repo (already the case; re-verified by the scan).

### 2.2 One-command install
- `get.sh` at the repo root and as a release asset. README's first line:
  `curl -fsSL https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh | sudo bash`
- get.sh: checks Ubuntu ≥ 24.04 and root; finds the latest release via the GitHub API (no token); downloads the
  tarball and its `SHA256SUMS` + `SHA256SUMS.sig`; verifies the signature with the release public key embedded in
  get.sh (minisign/ed25519 via `openssl` if available, else a small Python verifier) and the hash; unpacks to a temp
  dir; runs `install.sh` with a TTY (`</dev/tty`) so the menu works through a pipe; cleans up. `--version X`,
  `--mode`, `--modules a,b` pass through.
- Release CI signs `SHA256SUMS` (key in a GitHub Actions secret; the owner creates it once).

### 2.3 Module menu with dependencies shown
- One checklist screen, used by install.sh and `filament-kit config` → Modules:
  ```
   [x] 1 spoolman   Spoolman inventory (downloaded)
   [x] 2 server     App server and phone pairing          needs: Spoolman (this or remote)
   [ ] 3 ai_intake  Read spool labels with Claude (AI)    needs: server, an Anthropic API key   OPTIONAL AI
   ...
  ```
  Number toggles, `a` all-in-one/`s` server/`t` station presets, `Enter` to apply. Turning on a module turns on what it
  needs (and says so); turning one off lists what else goes. Modes stay as presets.
- Non-interactive: `--modules spoolman,server,printers` or `--mode`.

### 2.4 AI optional
- `ai_intake` default **off**; the installer offers it with "needs an Anthropic API key".
- Ungate spool adding: `/api/intake/add` (and the web app's add) work without AI; only `read`/`retry` need
  `ai_intake`. Android app and web app get a manual "Add spool" form (vendor, material, colour, weights; picks
  existing filaments from Spoolman); label photos appear only when ai_intake is on (`/api/info` modules).
- MCP connector (`web`) stays independent of ai_intake (Claude calls the tools; the server needs no key).

### 2.5 Auto-updater (module `updates`, optional, off by default)
- Timer (daily, configurable): checks the latest release; if newer, downloads and verifies exactly as get.sh does,
  stops services, runs install.sh in upgrade mode (no questions), restarts; keeps the previous version for
  `filament-kit update --rollback`. Data feeds (hardware XML, filament-library) are separate entries with the same
  verify-then-swap rule. `filament-kit update [--check]` runs it by hand. Never updates while a print is mapping/loading.

### 2.6 filament-library optional and on request
- The wheel no longer bundles the 1023-entry snapshot. `library` module off by default; switching it on (or
  `filament-kit library update`) downloads the public library release, verified like the program.
- Profiles work without it (Spoolman values + Bambu/Orca parents). With it, new lines use it as the initial source
  (current behaviour). Public: the filament-library repo becomes public too, or its releases are mirrored into
  filament-kit's releases (owner decides when 2.1 is done; default: publish the library data as release assets of
  filament-kit).

### 2.7 XML everywhere
- Format conventions: UTF-8, one root element per file with `version`, attributes for scalars, child elements for
  lists, ISO dates; parsed with `defusedxml`; each file type has a validator in code and a bundled XSD for editors.
- Files: `/etc/filament-kit/config.xml` (was config.json), `profiles/lines.xml`, `library/*.xml` + `index.xml`,
  `bambu_hardware.xml`, `state/printers.xml`, slot maps, `installed.xml`/`current.xml`/BUILD manifests,
  `owner-edits.xml`, `deleted.xml`, web `oauth.xml`, pairing store, reads cap, migration step records.
- Not converted (not ours to choose): Spoolman's database and API, Bambu/Orca preset files (slicer JSON), MQTT/HTTP
  payloads, the Android app's wire format (HTTP JSON API stays JSON; it is a protocol, not a data file). The owner can
  overrule per item.
- Migration: on upgrade, `modules apply` converts each JSON file to XML once (backup kept, `.json.bak-<stamp>`), then
  only XML is read. The filament-library repo gets an XML export + the kit reads either during the transition.
- pc-sync talks HTTP JSON (protocol) but its own local state files become XML too.

## 3. Order of work
1. Printers (sub-project 5), 2. AI optional + module menu, 3. XML conversion (with migration), 4. library on request,
5. updater + get.sh + signed releases (testable against private releases with a token), 6. scrub + public flip (only on the owner's word, after strong beta). LATER (deferred by the owner): 2.7 conversion of existing JSON files to XML.

## 4. Testing
- pytest per component; JSON→XML migration round-trip on real-shaped fixtures (every file type), idempotent;
  get.sh in WSL against a local fake "releases" server (signature good/bad, hash mismatch, no TTY);
  updater upgrade/rollback on WSL; scrub scan run on the branch with the report reviewed by the owner.
