# Spoolwarden design: implementation order

This document turns the design of this folder into a sequence of small changes. It starts from the four interfaces
as they are today (a Hub page of nine tabs, a web app with a tab bar, an app without navigation and the
`filament-kit` command) and ends with the Hub page, web app, app and `spoolwarden` command of `01-foundations.md`.
It adds no design: each step points at the part that specifies it, and what the parts leave open is listed in
section 13.

Contents: 1 Rules of the road · 2 How a step is written · 3 Stage 0: groundwork · 4 Stage 1: the Console shell on
the Hub page · 5 Stage 2: Hub page sections · 6 Stage 3: the web app · 7 Stage 4: the app · 8 Stage 5: the command
line · 9 Stage 6: Themes · 10 Stage 7: wording · 11 Hub API additions · 12 Dependencies and the first ten steps ·
13 Open points · 14 Coverage · 15 Stage 8: Share corrections · 16 Stage 9: Storage locations · 17 Stage 10: Events
and alerts · 18 Stage 11: Address and first run · 19 Stage 12: Every function in every version · 20 Stage 13:
History, data and safety, and Home Assistant · 21 Stage 14: Reach: the rest of the data as XML, languages, demo mode
and spool labels

---

## 1. Rules of the road

1. **One step, one change.** Each step can be reviewed, tested and released on its own. After every step all four
   interfaces work; nothing waits for a later step to be usable.
2. **No screen is half old and half new.** The look of an interface changes for the whole interface in one step
   (S1.1 for the Hub page, S3.2 for the web app, S4.1 for the app): from then on every card, row and control of it
   is drawn with the same tokens and components. Later steps rebuild a whole card, section or screen at once inside
   that look; a step never leaves part of a card in its old form.
3. **Behaviour first, look second.** Where a part changes both what it does (saving, confirming, results, where a
   value comes from) and how it is laid out, the behaviour lands in an earlier step or in the same step, never after.
4. **Every step names** its files today, what changes, what must not change, how to check it (an automated check
   of `07-accessibility.md` section 15 or of `08-platform-mapping.md` section 3, or a manual step of the release
   checklist in `07-accessibility.md` section 16), and the steps it depends on.
5. **Side by side.** Steps that touch different files are marked as able to run beside each other ("Beside").
   Two steps that edit the same file never run beside each other.
6. **The Hub first.** A change to what the Hub offers comes in its own step before the first step that uses it.
   Where an interface step can ship before its Hub step, it uses the fallback its document gives ("Until then"
   columns of the "Needs from the Hub" sections); section 11 lists every addition.
7. **One feature, four interfaces.** A feature goes into the Hub page, the web app, the app and the command line,
   or the step says in one line why one of them cannot have it (foundations section 3).
8. **The rename comes in two parts.** What a person sees or types (the product name, the `spoolwarden` command)
   changes in S5.9 and S7.4 to S7.8. The package, paths, unit names, protocol names and repository names change
   in a later piece of work with its own schedule; until then every step keeps those code names.
9. **Example data only.** Tests, fixtures and screenshots use the fake data of `mockups/CONTENT-SPEC.md` and the
   documentation addresses `192.0.2.x`, `printer.local` and `*.example` (foundations section 12, rule 8).

## 2. How a step is written

```
### S<stage>.<n> Title
Interface · Size · Depends on · Beside
Files today   where the thing lives now (path shorthand below; line numbers as surveyed from the current code)
Change        what the step does, with the design section that specifies it
Keep          what must not change
Check         the automated check, and the manual check where one applies
```

Sizes: **S** about a day, **M** a few days, **L** about a week.

Path shorthand:

| Short | Full path |
|---|---|
| `setup_static/` | `server/filament_kit/setup_static/` (`setup.js`, `setup_tabs.js`, `setup_printers.js`, `setup_trust.js`, `setup_presets.js`, `setup_backup.js`, `setup_intake.js`, `setup_logs.js`, `setup.css`) |
| `setup_console/` | `server/filament_kit/setup_console/` (`overview.py`, `printers_tab.py`, `station_tab.py`, `webapp_tab.py`, `presets_tab.py`, `intake_tab.py`, `general_tab.py`, `backup_tab.py`, `updates_tab.py`, `logs_tab.py`, `modes.py`, `jobs.py`) |
| `setup_page.py`, `setup_code.py`, `setup_helper.py`, `trusted.py`, `status.py`, `modules.py`, `api.py`, `cli.py`, `klipper_cli.py`, `menu_ui.py`, `intake_history.py`, `inventory.py` | under `server/filament_kit/` |
| `web/` | `server/filament_kit/web/` (`intake_app.py`, `printers_app.py`, `auth.py`); `web/static/` holds `app.js`, `printers.js`, `app.css`, `sw.js` |
| `<app>/` | `android/app/src/main/java/<app package>/` |
| `res/` | `android/app/src/main/res/` |
| `tokens/`, `icons/`, `strings/`, `tests/` | New folders at the repository root (`08-platform-mapping.md` section 1) |

Design references: "03 5.4" is section 5.4 of `03-hub-page.md`; "F6.4" is section 6.4 of `01-foundations.md`; "N12"
is item 12 of the Hub API table (section 11).

---

## 3. Stage 0: groundwork

Nothing a person sees changes in this stage. It puts the tokens, words, icons and checks in place so every later
step is checked from its first line.

### S0.1 Token folder in the code
Tooling · S · Depends on: none · Beside: none (first step)
- **Files today:** none in the code. The token set is delivered with the design (`design/tokens/`). The pages carry
  their own identical `:root` blocks (`setup_static/setup.css`, `web/static/app.css`).
- **Change:** add `tokens/tokens.json`, `tokens/build_tokens.py`, `tokens/tokens.css` and
  `tokens/check_contrast.py` to the repository as they are in the design folder (08 1, 3.1 to 3.3); run
  `build_tokens.py --check` and `check_contrast.py` in the project's normal test run. From this step the
  repository's `tokens/` folder is the only place the token files exist: the copy that came with the design is
  removed, and its `README.md` and `ADJUSTMENTS.md` move to `tokens/` (08 1).
- **Keep:** every served file; nobody installing Spoolwarden runs the generator (F12 rule 2).
- **Check:** `python tokens/build_tokens.py --check` prints `OK: tokens.css matches tokens.json`;
  `python tokens/check_contrast.py` ends with `RESULT: PASS`.

### S0.2 `tokens.json` version 2
Tooling · S · Depends on: S0.1 · Beside: none
- **Files today:** `tokens/tokens.json`.
- **Change:** add the proposed keys of 08 3.4 (`size.content-max` in every theme;
  `type.android`; `elevation.android`) and the proposed `size` entries of 05 1 (`label-col`, `thumb-s`,
  `swatch-row-w`, `swatch-row-h`, `swatch-head`, `empty-mark`, `chip`, `slot-label`, `port-field`, `column-max`,
  `preview-max`, `list-pane`) with the values 05 1 gives for each of the four themes; raise `version` to 2;
  regenerate `tokens.css`.
- **Keep:** every existing token value; Console's values of foundations section 4.
- **Check:** 08 test 2 (`tokens.json` complete and well-formed); `build_tokens.py --check`; contrast unchanged.

### S0.3 Generator: appearance script and preview tiles
Tooling · S · Depends on: S0.2 · Beside: S0.6
- **Files today:** `tokens/build_tokens.py`.
- **Change:** the generator also writes `tokens/theme-init.js` (08 8) and the preview-tile blocks in `tokens.css`
  (08 3.4); `--check` covers both.
- **Keep:** the order and content of today's `tokens.css` blocks (08 3.2).
- **Check:** 08 test 1 for the two new outputs.

### S0.4 Generator: Android tokens and window colour
app · M · Depends on: S0.3 · Beside: S0.6, S0.7
- **Files today:** `tokens/build_tokens.py`; the app uses the stock Material 3 scheme (`<app>/MainActivity.kt`
  lines 435-442).
- **Change:** the generator writes `<app>/ui/theme/SpoolwardenTokens.kt` and `res/values/sw_window.xml`,
  `res/values-night/sw_window.xml` in the shape of 08 3.4; `--check` covers them. The files compile but no screen
  reads them yet.
- **Keep:** the app's look; `MainActivity.kt` and every screen.
- **Check:** 08 test 1; the app builds.

### S0.5 Contrast over every pair
Tooling · S · Depends on: S0.4 · Beside: S0.6, S0.7
- **Files today:** `tokens/check_contrast.py`.
- **Change:** extend the check to every pair of 07 3.1 and 3.2 for the eight token sets, `--focus` on `--surface-2`,
  and the Material roles of 07 CON-8 read from the generated Kotlin values (AUT-1; 08 test 3). The two advisory
  pairs become required.
  For CON-8, `primary` is read from `accent-text` and `onPrimary` from `surface` (08 4.1), so `primary` on
  `surface` and on the `surfaceContainer` roles is a required pair in all eight sets.
- **Keep:** today's 248 required pairs and their results.
- **Check:** AUT-1 passes; a deliberately lowered value in a copy of `tokens.json` makes it fail with the message
  form of AUT-1.

### S0.6 Source tests: tokens used are tokens
Tooling · S · Depends on: S0.2 · Beside: S0.3, S0.4, S0.5
- **Files today:** none (`tests/test_design_sources.py` is new).
- **Change:** 08 tests 2 and 4: `tokens.json` well-formed; every `var(--name)` in the web stylesheets and every
  `SpoolwardenTheme.<group>.<field>` in hand-written Kotlin is a token; media queries use only the edges of F7.
- **Keep:** no shipped file changes.
- **Check:** the tests pass on today's files (today's stylesheets use their own `:root` names; those files are
  listed in the allow-list until S1.1 and S3.2 remove them, open point 4).

### S0.7 Lint checks
Hub page, web app, app · S · Depends on: S0.6 · Beside: S0.4, S0.5
- **Files today:** none (the checks are new); they read `setup_static/*`, `web/static/*` and `<app>/**/*.kt`.
- **Change:** literal colours and values, and `var(--accent)` outside the listed labelled fills (AUT-2 with CON-9; 08 test 5), native dialogs (AUT-3), fields outside the field
  component (AUT-4), press-down handlers (AUT-6), and the words lint with its word list (AUT-7: internal words, the
  old names of the "Was" column of F2, "color", "OK" and "here" as whole button or link texts). Today's findings go
  into `tests/literal_allowlist.txt` and the allow-lists of AUT-3, AUT-4, AUT-6 and AUT-7, each with file,
  reason and the number of findings of that kind in that file, so the build stays green and a new finding in a
  listed file still fails (the count may only go down); every later step that rewrites a file removes that file's entries (open
  point 4), and S7.2 removes the last AUT-7 entries.
- **Keep:** every shipped file.
- **Check:** each lint fails on a planted `confirm(`, `#fff`, bare `<input>` and a button text "Modules" in a
  scratch file and passes on the tree with the allow-lists.

### S0.8 Shared string catalogue
Tooling · M · Depends on: S0.4, S0.7 · Beside: S0.5
- **Files today:** none; every text is written in the code (`setup_static/*`, `web/static/*`, Kotlin under `<app>/ui/`,
  `cli.py`).
- **Change:** `strings/en.json` with the texts of 02 to 06 under the keys of 05 15 (`<screen>_<element>[_<state>]`,
  `common_…`, `theme_<key>_name`, `theme_<key>_line`), the product's name only in `app_name` and the command's
  only in `command_name`, every other text naming them through `{product}` and `{command}` (08 12); the generator
  writes `strings/strings.js` and
  `res/values/strings.xml` (08 12); 08 test 7 (key and text equality; the literal scan with today's literals in
  `tests/strings_allowlist.txt`) and test 8 (theme names agree). Nothing reads the catalogue yet: the Hub page
  starts in S1.3, the web app in S3.3 and the app in S4.3.
- **Keep:** every text on screen.
- **Check:** 08 tests 1, 7 and 8.

### S0.9 Icon set and sprite
Tooling · M · Depends on: S0.8 · Beside: S0.5
- **Files today:** none; the pages and the app draw no icons (the app has no `Icon(` call).
- **Change:** `icons/src/<name>.svg` for every icon of F10 and `icons/status/<shape>.svg` for the six status
  shapes, drawn by hand to F10; the generator writes `icons/sprite.svg`, `res/drawable/sw_ic_<name>.xml` and
  `res/drawable/sw_st_<shape>.xml` (08 11). One chevron, rotated by CSS.
- **Keep:** no page or screen shows them yet.
- **Check:** 08 tests 1 and 6.

### S0.10 The Hub serves the shared files
Hub · S · Depends on: S0.3, S0.8, S0.9, S0.11 (it serves the files S0.11 makes) · Beside: S1.8
- **Files today:** `setup_page.py` (static files read once and served by name, lines 293-329; HTML shell 478-499);
  `web/intake_app.py` (page shell, lines 288-321).
- **Change:** serve `tokens.css`, `theme-init.js`, `strings.js` and the shared component files (S0.11) from one
  place to the Hub page and the web app (N29); place `icons/sprite.svg` inline as the first child of `<body>` of
  every page (N30). The pages do not link the new files yet; the sprite is hidden.
- **Keep:** the Content-Security-Policy (`setup_page.py` lines 73-76, `web/intake_app.py` lines 47-52, 301-308);
  every visible part of both pages.
- **Check:** a test requests each shared file from both page addresses and gets the same bytes; AUT-5 is not yet
  run (S1.11).

### S0.11 Shared component stylesheet and script
Hub page, web app · L · Depends on: S0.3, S0.8, S0.9 · Beside: S1.8
- **Files today:** none; each page styles its own elements (`setup_static/setup.css`, 51 lines; `web/static/app.css`,
  85 lines).
- **Change:** `components.css` and the shared component script (the core), and the two additions
  `components-jobs` and `components-media` (02 1, "Files"), with the components of 02 sections 2 to 10 in the
  Console profile (`rail`, `table`, `inline`), the `data-look` profile groups present but keyed on Console only, and
  a component sample page under `tests/` that shows every component in every state with fake data. The script is
  the one implementation of the element builder, the Hub request helper, the dialog, the toast, the inline result
  and the announcer (02 1.4, "One shared script"); each page's own copies (`h()`, `api()` and their variants in
  `setup_static/` and `web/static/`) are removed in the step that moves that page onto it (S1.3 to S1.7, S3.2 to
  S3.6). No page uses them yet.
- **Keep:** both pages unchanged; the size limits of F12 rule 7 (core stylesheet under 60 KB, core script under
  64 KB, each addition under 30 KB), checked by a test.
- **Check:** AUT-2, AUT-3, AUT-4, AUT-6 and 08 tests 4 and 5 with no allow-list entry for the new files; AUT-5 run
  on the sample page at 1280 px and 320 px, light and dark.

---

## 4. Stage 1: the Console shell on the Hub page

The Hub page takes the Console look as a whole, then its chrome (top bar, navigation, lock, dialogs, results, job
strip) is replaced. Section contents keep today's cards until their Stage 2 step.

### S1.1 The Hub page on tokens
Hub page · M · Depends on: S0.10, S0.11 · Beside: S1.8
- **Files today:** `setup_static/setup.css` (own `:root` block and every rule); `setup_page.py` (head, lines 478-492).
- **Change:** the page links `tokens.css` then `components.css`; `setup.css` keeps only rules for today's markup,
  written with tokens and the component classes (buttons, fields, cards, pills drawn as status badges, focus ring).
  The whole page shows Console, light or dark as the device is set (F4, F5).
- **Keep:** markup, scripts, texts, endpoints, what every button does.
- **Check:** AUT-2 with no entry left for `setup.css`; 08 test 4; manual: release checklist step 5 (200 % zoom and
  320 px) on every tab.

### S1.2 Appearance switch on the Hub page
Hub page · S · Depends on: S1.1 · Beside: S1.8
- **Files today:** `setup_page.py` (head); `setup_static/setup.js` (page layout, lines 292-298).
- **Change:** `theme-init.js` as the first script in the head; the appearance control of 02 3.3 at the right end of
  today's header line, stored as `spoolwarden.appearance` (F5, 03 3.4). S1.3 puts it in the top bar unchanged.
- **Keep:** the default (System); no setup code needed; nothing else on the page.
- **Check:** AUT-5 on the sample page; manual: choose Light, Dark and System and reload each time (no flash of the
  wrong appearance).

### S1.3 Shell: top bar, navigation, More sheet, addresses
Hub page · L · Depends on: S1.2 · Beside: S1.8
- **Files today:** `setup_static/setup.js` (heading and intro 293-294, sticky block and tab nav 64-82, re-render on
  `hashchange` 290); `setup_static/setup.css` (`.sticky`, `.tabs`); `setup_page.py` (`<title>`).
- **Change:** top bar, navigation rail, phone bottom bar and More sheet, page header and page frame (02 2.1 to 2.6;
  03 3.1, 3.2, 3.8): ten sections in the two groups of F8 with their new names (Spools, the eleventh, comes with EV5);
  Flash a device shows its empty state
  until S2.16; addresses of 03 1.2 with Back and Forward; title "<Page title> · <Hub name>". More-sheet summaries use
  the fallback of 02 12 until S2.2. The setup-code card stays as the first card of the content until S1.5. The page
  links `strings.js` and the shell's texts come from the catalogue (N35).
- **Keep:** the content of every section; the lock behaviour; endpoints.
- **Check:** AUT-5 on the sample page; 08 test 7 with the shell's literals gone from `tests/strings_allowlist.txt`;
  manual: release checklist step 2 up to "Go to Printers", and every section reachable in two taps at 320 px.

### S1.4 Hub: setup code check, trust expiry, field in errors
Hub · M · Depends on: S0.10 (both edit `setup_page.py`); can be done any time before S1.5 · Beside: S1.8
- **Files today:** `setup_page.py` (gates, lines 412-456); `setup_code.py`; `setup_helper.py` (wrong code and lockout
  texts, lines 105-108); `trusted.py`; the endpoints listed in 07 17 (`setup_console/*`, `web/intake_app.py`,
  `web/printers_app.py`, `api.py`).
- **Change:** check a setup code without a change, replying right, wrong (with `tries_left`) or too many tries (with
  `retry_at`) (N3); `GET trust` reports `expires` (N28); error replies of the endpoints of 07 17 carry `field` (N5).
- **Keep:** the lockout rules (5 wrong per 10 minutes per address, ceiling 30); every existing reply field.
- **Check:** tests of the three reply shapes; existing tests pass.

### S1.5 Lock chip and unlock dialog
Hub page · M · Depends on: S1.3, S1.4 · Beside: S1.8
- **Files today:** `setup_static/setup.js` (code card 34-37, change pattern 37-56); `setup_static/setup_trust.js`
  (trusted line and offer 8-14); the "Show…" buttons that only fetch with the code (`setup_tabs.js` Show addresses,
  `setup_backup.js` Show the backups, `setup.js` Show requests, `setup_trust.js` Show the list).
- **Change:** the lock chip (Locked, Unlocked, Trusted computer) and the unlock dialog with "Trust this computer"
  replace the setup-code card, the trusted line and the trust offer (02 3.1, 3.2; 03 2.1, 3.3); a change asked while
  Locked opens the dialog in place and carries on; reads that need the code load by themselves once unlocked
  (03 14.1, 14.2, 14.5, 14.8).
- **Keep:** the code is sent in the request body, never in an address; the trusted-computer cookie rules.
- **Other interfaces:** the web app has no lock: the home network is its gate (04 1.1); the app's gate is pairing
  (S4.5); the command line runs on the Hub and shows or renews the setup code (`setup-code`, S5.8).
- **Check:** AUT-5 on Overview and Devices; manual: release checklist step 3 (dialog read with title and sentence).

### S1.6 Dialogs replace native confirm and prompt
Hub page · M · Depends on: S1.5 · Beside: S1.8
- **Files today:** every `confirm(` and `prompt(` in `setup_static/` (`setup_printers.js`, `setup_trust.js`,
  `setup.js`, `setup_backup.js`, `setup_tabs.js`, `setup_presets.js`).
- **Change:** each becomes the confirm, destructive, typed-word or text-entry dialog of 02 9.1, with the words of
  03 2.6, 5.5, 7.7, 10.11 and 12.3; secrets in secret fields with Show / Hide (02 5.3). The actions that do not ask
  today and must (Clear Moonraker API key, Stop trusting this computer, Revoke, Remove catalog token) ask from this
  step on. Change address and Forget certificate ask for the Access Code (03 15; open point 1).
- **Keep:** what each action does once confirmed; the endpoints.
- **Check:** AUT-3 with no entry left for `setup_static/`; manual: release checklist step 2 (Rename and Forget
  printer by keyboard, Escape and the guard).

### S1.7 Inline results, toasts and region refresh
Hub page · M · Depends on: S1.6 · Beside: S1.8
- **Files today:** `setup_static/setup.js` (`change()` and the whole-tab re-render 37-56, 85-89; cached result
  boxes `boxFor` 58-62); the result boxes of every `setup_*.js`.
- **Change:** results appear beside their control and are announced, toasts when the control is gone, every
  finished result carries its time (02 8.6, 8.7; 03 2.3); a change reads again only its own section, never redrawing
  a field being typed in (03 2.2, 2.7).
- **Keep:** the texts the Hub returns, shown as given with `textContent`.
- **Check:** AUT-5 (a result slot has its status region at load); manual: release checklist step 3 (results read
  without moving focus).

### S1.8 Hub: job progress
Hub · S · Depends on: none · Beside: any step that does not edit `setup_console/jobs.py`
- **Files today:** `setup_console/jobs.py`.
- **Change:** jobs report a progress fraction (N13), read from the newest `==> step K of N` line of the job's
  log; null when the job writes none. Which jobs write step lines, and the final form of the fraction, is S1.12.
- **Keep:** job names, states and log redaction.
- **Check:** a test of the job reply with and without a fraction.

### S1.9 Job strip, the Hub is restarting, not answering
Hub page · M · Depends on: S1.7, S1.8 · Beside: none
- **Files today:** `setup_static/setup_tabs.js` (background job panel, lines 9-55); `setup_static/setup.js`.
- **Change:** the job indicator in the top bar and the job strip with a title per job and a determinate bar when a
  fraction is given (02 8.4; 03 3.5); the restarting state (02 8.5; 03 3.6) and the "not answering" states (03 3.7).
- **Keep:** "Show the whole log"; redaction of addresses and serials.
- **Other interfaces:** the command line prints a progress line for every wait (S5.1). The web app starts no
  background jobs, so it has no job strip (04 2); the app shows progress on the screen that started the action
  (S4.4).
- **Check:** AUT-5 with a fake running job; manual: release checklist step 2 (Back up now, open the strip, scroll the
  log by keyboard) and step 3 (exactly two job announcements).

### S1.10 Standard states and switched-off sections
Hub page · M · Depends on: S1.7 · Beside: none
- **Files today:** "Checking…", "Reading…" and red error blocks in `setup_static/setup_tabs.js`, `setup_printers.js`,
  `setup_presets.js`, `setup_logs.js`, `setup_intake.js`; the module-off cards (Printers, Presets).
- **Change:** loading skeleton with its limits, empty state, error state with Try again, and the switched-off
  section page with its button to Features (02 10; 03 2.4, 2.5).
- **Keep:** the content once loaded.
- **Check:** AUT-5 (no region still busy after load) with fake replies that are slow, empty, failing and off.

### S1.11 Page audit on the Hub page
Hub page · M · Depends on: S1.10 · Beside: none
- **Files today:** none (the audit is new); fake data in `mockups/CONTENT-SPEC.md`.
- **Change:** AUT-5 runs against the Hub page served with fake data in every view, Console light and dark, at
  1280 px and 320 px. From this step on, every Hub page step runs it on its views.
- **Keep:** no shipped file changes.
- **Check:** the audit passes on the shell; a planted unlabelled button fails it.

### S1.12 Hub: jobs write their steps
Hub · M · Depends on: S1.8 · Beside: any step that does not edit the job commands or `setup_console/jobs.py`
- **Files today:** the commands the jobs run (`backup.py`, `updates.py`, `apply.py`, `library.py`,
  `reader_setup.py`, the Weigh Station pairing in `cli.py`); `setup_console/jobs.py`.
- **Change:** each counted job of 02 8.4 "Steps" writes `==> step K of N <sentence>` when a step starts, with the
  sentences given there; the job reply gains `step` (`index`, `count`, `text`) and `progress` becomes
  `(K - 1) / N` while step K runs and 1 at exit 0 (N13). Jobs that are not counted are unchanged.
- **Keep:** what each job does, its other log lines, its exit codes, redaction.
- **Other interfaces:** the command line shows the same step sentences as its progress lines (S5.1). The web app
  and the app start no Hub jobs.
- **Check:** for each counted job, a test that its command writes step lines 1 to N in order with N constant; a
  test of the reply at step 2 of 4 (`progress` 0.25, `step.index` 2) and at the end (1); a step sentence
  containing an address fails a test.

---

## 5. Stage 2: Hub page sections

Order: by how often a section is opened and how much harm a mistake in it can do. Overview and Printers are opened
most and come first (Overview only reads). Recently added, Devices and Slicer presets follow. Features and Updates
switch services and install software, so they come after the patterns have settled. Logs is opened least. Flash a
device waits for its Hub code to be released. Settings comes last, because it changes how every setting is saved.

Every interface step in this stage depends on S1.11 (the page audit then checks it) and runs AUT-5 on its own views.
Each one reads its section's texts from the catalogue (`strings.js`) and removes that section's literals from
`tests/strings_allowlist.txt`, so 08 test 7 covers it from then on.

### S2.1 Hub: grouped status rows, cloud reads, section summaries
Hub · M · Depends on: S1.4 · Beside: any step that edits only `setup_static/`
- **Files today:** `status.py` (rows, lines 219-250); `setup_console/overview.py`; `setup_page.py` (`G state`, lines
  524-551).
- **Change:** each status row carries its group, the same in `G overview` (N26); `G state` reports the cloud reads
  used today and the daily limit (N16); a one-line summary for each navigation section (N7).
- **Keep:** the checks, their order inside a group, their Fix texts; the command line's `status` output (S5.1
  changes it).
- **Check:** tests of the reply shapes; `filament-kit status` output unchanged against fake data.

### S2.2 Overview
Hub page · M · Depends on: S1.11, S2.1 · Beside: S2.3, S2.4, S2.5, S2.7, S2.10, S2.14
- **Files today:** `setup_static/setup_tabs.js` (Overview, lines 72-115); `setup_console/overview.py`.
- **Change:** 03 4: header meta line with the setup; Still to do card with a button to the exact place for each item;
  checks collection in groups, problems first, OK rows folded, Fix column with code blocks; Make the fields as a row
  action; half-install banner; Label Reader tile; the hidden-values line with **Unlock to show**. Navigation and
  More-sheet summaries switch to the Hub's (N7).
- **Keep:** what each check reports and how it is computed.
- **Other interfaces:** the command line's `status` shows the same groups (S5.1). The web app and the app show no
  Hub status: they are for work at the bench, and a read-only Hub summary is feature idea B4 (06 12).
- **Check:** AUT-5 on Overview Locked, Unlocked and with a failing check; manual: release checklist step 5 at 320 px.

### S2.3 Hub: printer states in one read
Hub · M · Depends on: S1.4 · Beside: any step that edits only `setup_static/`
- **Files today:** `setup_page.py` (`G state`); `setup_console/printers_tab.py`.
- **Change:** printer states, with job progress and slots, for the whole list in one light read or a change stream
  (N14). Optional: without it the page reads `G state` every 10 s (03 2.7).
- **Keep:** the per-printer replies the web app and the app use.
- **Check:** a test that one read returns every printer of the fake data.

### S2.4 Printers: collection, rows, mapping and reports
Hub page · L · Depends on: S1.11; S2.3 when present · Beside: S2.2, S2.7, S2.10, S2.14
- **Files today:** `setup_static/setup_printers.js` (the Printers cards); `setup_console/printers_tab.py`.
- **Change:** 03 5.1 to 5.4, 5.7 to 5.9: the printer collection (Printer, Address, State; tags Bambu Lab and
  Klipper; Connection badge), the row expansion with one primary action, Test connection, Lane data as a segmented
  choice, Detect model and slots, the header link **Open the live printer view**; one message row per printer with
  "Needs a look: <why>" and **Collect a report**; slot mapping as step progress in the message row; the Map by
  loading filament drawer and the Saved reports drawer; the result texts and states. The dialogs of S1.6 stay.
- **Keep:** the endpoints; what each action does; the live printer view stays in the web app (feature idea B1).
- **Other interfaces:** web app S3.11; app S4.10 and S4.11; command line S5.5.
- **Check:** AUT-5 on Printers, an expanded row and both drawers; manual: release checklist steps 2 and 3 (printers
  table read by row, Test connection results read where they appear).

### S2.5 Printers: add, find Klipper printers, Klipper add-on
Hub page · M · Depends on: S2.4 · Beside: S2.2, S2.7, S2.10, S2.14
- **Files today:** `setup_static/setup_printers.js` (cards Add a printer, Find Klipper printers, Printer pack).
- **Change:** 03 5.6 Add a printer drawer with field errors (N5); 03 5.4 and 5.8 Find Klipper printers card with
  **Use this printer** and **Dismiss**; the Klipper add-on card (was Printer pack).
- **Keep:** the scan limits and the signed-release check of the add-on commands.
- **Other interfaces:** web app S3.11 (adding a Klipper printer; its scan is feature idea B3); app S4.10; command
  line S5.5 (`printer add`, `printer scan`, `klipper add-on`).
- **Check:** AUT-5 on the drawer with a field error; AUT-4 (fields only through the field component).

### S2.6 Hub: Label Reader confidence and engine, small photos
Hub · M · Depends on: S1.4 · Beside: any step that does not edit the files below
- **Files today:** the read endpoints (`web/intake_app.py` `read`; `api.py` `api/intake/read`); `intake_history.py`;
  `setup_console/intake_tab.py`.
- **Change:** per-field confidence (high, medium, low, not on the label) in the read reply and on each Recently
  added record, a per-record summary, and the engine, model and tier that read it (N4); small versions of label
  photos for 44 / 48 px and 96 px thumbnails (N8).
- **Keep:** every existing field of the read reply and of a record; the number of records kept.
- **Check:** tests of the read reply and the record reply with and without the new fields.

### S2.7 Recently added
Hub page · L · Depends on: S1.11, S2.6 · Beside: S2.2, S2.4, S2.5, S2.10, S2.14
- **Files today:** `setup_static/setup_intake.js`; `setup_console/intake_tab.py`.
- **Change:** 03 6: the list (thumbnail, names or "No spools", time, source, state badge, confidence and the To check
  filter); the record (Photos card with viewer, item choice, Fields card grouped and shown before editing, **Save
  changes**, the Ask the Label Reader card, the suggestion as a before-and-after change list naming the engine, the
  revision list with undo).
- **Keep:** what a revision, an edit and an undo change in Spoolman.
- **Other interfaces:** web app S3.12; app S4.12 (new there); command line S5.6 (`recent`).
- **Check:** AUT-5 on the list and a record; manual: release checklist step 5 (320 px on Recently added).

### S2.8 Hub: QR codes drawn by the Hub
Hub · M · Depends on: S1.4 · Beside: any step that edits only `setup_static/`
- **Files today:** the pairing and web app replies that carry QR text made with the optional `qrencode` tool
  (`setup_console/station_tab.py`, `setup_console/webapp_tab.py`); `cli.py` (pair, lines 138-179).
- **Change:** QR codes drawn by the Hub itself, always available, loadable as an image, and as terminal text for
  the command line (N6). Bundled code needs a GPL-3.0-compatible licence and a `THIRD-PARTY.md` entry (F12 rule 1).
- **Keep:** pairing codes, expiry, fingerprints.
- **Check:** a test that each QR decodes to the link it stands for, with `qrencode` absent.

### S2.9 Devices
Hub page · L · Depends on: S1.11, S2.8 · Beside: S2.4, S2.5, S2.7, S2.10
- **Files today:** `setup_static/setup.js` (Devices, lines 128-234); `setup_static/setup_trust.js` (Trusted
  computers, lines 45-80); `setup_console/station_tab.py`, `setup_console/webapp_tab.py`; `station_requests.py`.
- **Change:** 03 7: Paired devices with **Unpair**; **Pair a phone**, **Link Slicer Sync**, **Link a Weigh Station**,
  **Pair the Weigh Station on this Hub**; the pairing dialog with QR block and countdown bar; Weigh Stations asking
  to pair, refreshing by itself; the web app on a phone; Tag Readers with **Make a token**; Trusted computers with a
  toggle, Rename, Revoke and Revoke all.
- **Keep:** the pairing protocol; built-in pairings cannot be unpaired.
- **Other interfaces:** app pairing S4.5; command line S5.6 and S5.7 (`devices`, `pair`, `tag-reader`). The web app
  pairs nothing: the home network is its gate (04 1.1).
- **Check:** AUT-5 on Devices and the pairing dialog; manual: release checklist step 3 (dialog read with title and
  sentence).

### S2.10 Slicer presets
Hub page · M · Depends on: S1.11 · Beside: S2.2, S2.4, S2.5, S2.7, S2.9, S2.14
- **Files today:** `setup_static/setup_presets.js`; `setup_console/presets_tab.py`.
- **Change:** 03 8: Build card with the Slicer Sync badge, problems, old presets to delete by hand, **Build now**
  and **Bring back deleted presets**; Updates card with **Show what would change** and **Accept these**; Product
  lines with **Set parent** (menu and dialog).
- **Keep:** what a build, an accept and a parent change write.
- **Other interfaces:** web app S3.13; app S4.14; command line S5.7.
- **Check:** AUT-5 on Slicer presets, on and switched off.

### S2.11 Hub: setup names and feature titles
Hub · S · Depends on: S1.4 · Beside: any step that edits only `setup_static/`
- **Files today:** `modules.py`; `setup_console/modes.py`.
- **Change:** the setups `hub`, `weigh-station` and `hub-with-weigh-station` accepted beside `server`, `station`
  and `all-in-one`, and `--hub ADDRESS` beside `--server` (N27); feature titles in the names of 03 9.1 (part of
  N15).
- **Keep:** the old words keep working everywhere they work today; stored configuration.
- **Check:** tests that both spellings select the same setup.

### S2.12 Features
Hub page · M · Depends on: S1.11, S2.2 (same file), S2.11 · Beside: S2.4, S2.5, S2.7, S2.10
- **Files today:** `setup_static/setup_tabs.js` (Modules, lines 118-146); `setup_static/setup.js` (lines 237-288);
  `setup_console/modes.py`.
- **Change:** 03 9: the Setup card with choice cards; the Features collection with plain names, "Uses AI" tag and
  Needs column; **Turn on** / **Turn off** opening the preview drawer as the confirmation; **Apply the features
  again**.
- **Keep:** what each switch installs and starts; the refusal for the Hub service itself.
- **Other interfaces:** command line S5.4 and S5.7 (`features`, the checklist). The web app and the app do not switch
  the Hub's services; they show a switched-off destination with a pointer to the Hub page (04 6.10, 05 2.3).
- **Check:** AUT-5 on Features and the drawer; manual: turn a feature off and on with fake data, by keyboard only.

### S2.13 Updates
Hub page · M · Depends on: S2.12 (same file) · Beside: S2.4, S2.5, S2.7, S2.9, S2.10
- **Files today:** `setup_static/setup_tabs.js` (Updates, lines 240-286); `setup_console/updates_tab.py`.
- **Change:** 03 12: version key-value list, **Check now**, **Update to <version>** with its dialog, release notes,
  Roll back, the uninstall line as a code block.
- **Keep:** the signed-release checks and the meaning of the refusal texts.
- **Other interfaces:** command line S5.8 (`update`, `uninstall`). The app has its own App updates (S4.15); Hub
  updates install on the Hub and start from the Hub page or the command line (06 12).
- **Check:** AUT-5 on Updates with an update available, held back and failed.

### S2.14 Logs
Hub page · S · Depends on: S1.11 · Beside: S2.2, S2.4, S2.5, S2.7, S2.10
- **Files today:** `setup_static/setup_logs.js`; `setup_console/logs_tab.py`.
- **Change:** 03 13: service select, Lines as a segmented choice, the log in a code block with Copy, the locked line.
- **Keep:** logs need the setup code; the length limit.
- **Other interfaces:** command line S5.8 (`logs`). Logs hold addresses and serials, so the web app and the app do not
  show them (06 12).
- **Check:** AUT-5 on Logs, Locked and Unlocked.

### S2.15 Hub: firmware and flash released
Hub · M · Depends on: S1.4 · Beside: any step that edits only `setup_static/`
- **Files today:** not in a release yet: `G firmware`, `G firmware/<id>.bin`, `P flash/provision`, `P flash/server`,
  job `reader_setup`, and the bundled flashing script.
- **Change:** release them (first part of N11), with a `THIRD-PARTY.md` entry for the bundled script.
- **Keep:** the command line's own flashing of boards plugged into the Hub.
- **Check:** tests of the replies; flashing a spare board as a manual check.

### S2.16 Flash a device
Hub page · M · Depends on: S1.11, S2.15 · Beside: S2.4, S2.5, S2.7, S2.10
- **Files today:** none on the released page (the section is new); `setup_static/setup_flash.js` holds the unreleased tab
  (S2.15) that this step rebuilds, and its texts come from the catalogue (`flash_` keys).
- **Change:** 03 11: device choice (Tag Reader, Weigh Station display), where it is plugged in (this computer, or the
  Hub), **Connect and write**, step progress and results.
- **Keep:** nothing is written without the setup code.
- **Other interfaces:** command line S5.7 (`tag-reader flash`, `weigh-station flash-display`). A phone cannot flash
  a board over USB, so the web app and the app say where to do it (F3).
- **Check:** AUT-5 on every state; manual flash of a spare board.

### S2.17 Hub: group save and last backup time
Hub · M · Depends on: S1.4 · Beside: any step that edits only `setup_static/`
- **Files today:** `setup_console/general_tab.py` (`P settings/general` takes one key at a time);
  `setup_console/backup_tab.py`; `setup_page.py` (`G state`).
- **Change:** several settings of one group in one request, all or nothing, with per-key errors and one
  restarts / applies answer (N2); the last backup time readable without the setup code (N12).
- **Keep:** the one-key form keeps working.
- **Check:** a test of a mixed request that fails on one key and changes nothing.

### S2.18 Hub: On this Hub engine and address test
Hub · M · Depends on: S2.6 · Beside: any step that edits only `setup_static/`
- **Files today:** not in a release yet: `G settings/local-intake`, `intake.reader`, `local_intake.url`,
  `local_intake.tier`, the 409 `no_photo` answer.
- **Change:** release them (second part of N11) and test an address before it is saved (N10).
- **Keep:** the Cloud engine's settings and behaviour.
- **Check:** tests of the test reply for a saved and an unsaved address.

### S2.19 Settings regrouped
Hub page · L · Depends on: S2.13 (same file), S2.17; S2.18 when present · Beside: S2.4, S2.5, S2.7, S2.10, S2.16
- **Files today:** `setup_static/setup_tabs.js` (General and the other settings cards, lines 177-238);
  `setup_static/setup_backup.js` (lines 30-77); `setup_static/setup.js` (lines 92-125);
  `setup_console/general_tab.py`, `setup_console/backup_tab.py`.
- **Change:** 03 10: nine groups in the fixed order with the sub-navigation (desktop list, tablet chips, phone list of
  groups), one Save per group sending its changed keys in one request (N2), unsaved marks and the leave guard;
  Appearance (Light / Dark / System; Theme arrives in S6.2, Theme for new devices in S6.10); General; Storage
  locations; Label Reader (Cloud fields and Records kept; the On this Hub fields with S2.18); Backups and restore;
  Network and addresses (with Remote access); Web passphrase; Filament Catalog; Weigh Station voice.
- **Keep:** every setting's key and meaning; which changes restart or apply, and the warning before they do.
- **Other interfaces:** command line S5.4 (`config` menu) and S5.8 (`config show`, `config set`) follow the same
  groups. The web app and the app hold only Appearance (S3.3, S4.15): the other groups change the Hub (06 12).
- **Check:** AUT-5 on every group, phone and desktop; manual: release checklist step 2 (Settings > General, change
  Display name, Enter) and step 5 (200 % zoom on Settings).

---

## 6. Stage 3: the web app

The web app shares tokens, words, icons and components with the Hub page (Stage 0), so this stage can start as soon
as Stage 0 is done; it does not wait for Stages 1 and 2 except for the Hub steps it names. From S3.3 on, each
rebuilt screen reads its texts from the catalogue (`strings.js`) and removes its literals from
`tests/strings_allowlist.txt`, so 08 test 7 covers it. S3.8, S3.10, S3.12, S3.13, S3.15 and S3.17 all edit
`web/static/app.js`, so they run one after another.

### S3.1 Hub: web app page attributes, manifests, status bar
Hub · M · Depends on: S0.10 · Beside: any step that does not edit `web/intake_app.py`
- **Files today:** `web/intake_app.py` (page shell, lines 288-321; manifest and icon, lines 56-75 and 338-342;
  `theme-color` fixed at a dark value).
- **Change:** `<body>` attributes for the Hub name, the Hub page address (absent on the public address), Slicer
  presets on or off, and spool editing available (N17); two manifests, light and dark, named "Spoolwarden" with the
  Spoolwarden mark at 180 and 512 px, `apple-mobile-web-app-title` "Spoolwarden", and the two `theme-color` metas of
  08 13 (N23).
- **Keep:** today's `data-*` attributes; the Content-Security-Policy; both addresses of 04 1.1.
- **Check:** tests of the page shell on the home and the public address; manual: 08 13 status-bar check on an iPhone.

### S3.2 The web app on tokens
web app · M · Depends on: S0.11, S3.1 · Beside: S3.14
- **Files today:** `web/static/app.css` (85 lines, own `:root` block); `web/intake_app.py` (head).
- **Change:** the page links `theme-init.js`, `tokens.css` and `components.css`; `app.css` keeps only rules for
  today's markup, written with tokens and component classes; the appearance follows the phone, and the appearance
  script keeps the `theme-color` metas and the manifest link in step (F5, 08 13). Inputs are 16 px on phones.
- **Keep:** markup, scripts, texts, endpoints.
- **Check:** AUT-2 with no entry left for `app.css`; manual: release checklist step 6, first part (no page zoom when
  a field gets focus).

### S3.3 Web app shell
web app · L · Depends on: S3.2 · Beside: S3.7, S3.9, S3.14, S3.16
- **Files today:** `web/static/app.js` (tab bar and `show()`, lines 161-177; `localStorage["tab"]`, line 172);
  `web/static/printers.js` (alerts section; `localStorage["printer"]`, lines 48 and 54).
- **Change:** 04 2 and 9: top bar with the Hub name and the appearance menu; bottom bar with Add, Spools, Printers,
  Recent, More; rail on tablets; the More sheet (Slicer presets, Settings, Add to Home Screen, Open the Hub page);
  the Settings sheet with Appearance and "Print alerts on this phone" (moved from Printers); addresses and
  remembered state of 04 2.4 (`#open` and `#history` redirect); page titles; dimmed destinations (Recent on the
  public address, Printers switched off). The page links `strings.js` and the shell's texts come from the catalogue
  (N35).
- **Keep:** the content of each tab; endpoints; what an alert subscription does.
- **Check:** AUT-5 on the sample page; 08 test 7 with the shell's literals gone from `tests/strings_allowlist.txt`;
  manual: every place reachable in two taps at 320 px.

### S3.4 Page audit on the web app
web app · M · Depends on: S3.3 · Beside: S3.7, S3.9, S3.14, S3.16
- **Files today:** none; fake data of `mockups/CONTENT-SPEC.md`.
- **Change:** AUT-5 runs against the web app in every view, Console light and dark, at 1280 px and 320 px. From this
  step on, every web app step runs it on its views.
- **Keep:** no shipped file changes.
- **Check:** the audit passes on the shell.

### S3.5 Sheets replace native confirm and prompt
web app · M · Depends on: S3.4 · Beside: S3.7, S3.9, S3.14, S3.16
- **Files today:** the 5 `window.confirm` and about 10 `window.prompt` calls in `web/static/app.js` and
  `web/static/printers.js`.
- **Change:** 04 12: confirmations (Stop the print?, Unload from <slot>?, Put it back on the spool?, Map the slots?,
  Forget <printer>?) and questions (Rename printer, Change address, Replace Access Code, Forget the certificate?,
  Moonraker API key, Add <model>, Add a Klipper printer) as sheets; secrets in secret fields.
- **Keep:** what each action does once confirmed.
- **Check:** AUT-3 with no entry left for `web/static/`; manual: release checklist step 6 (Printers: load into a
  slot).

### S3.6 Results, errors and reasons in place
web app · M · Depends on: S3.5 · Beside: S3.7, S3.9, S3.14, S3.16
- **Files today:** result `pre` blocks, `pre.err`, spinner text in `web/static/app.js` and `web/static/printers.js`.
- **Change:** 04 3.2 to 3.6: results where the question was asked, status as shape and word, disabled buttons that
  say why, loading and live data without losing typing, errors in words; 04 10.3 "Cannot reach the Hub".
- **Keep:** the Hub's texts, shown as given.
- **Check:** AUT-5; manual: release checklist step 6 (results read where they appear; the reason beside Add read
  before Check).

### S3.7 Hub: add preview per item, colour in find, search paging
Hub · M · Depends on: S1.4 · Beside: S3.3 to S3.6, S3.14
- **Files today:** `web/intake_app.py` (`add`, `find`, `filaments`); `inventory.py`; `api.py` (`api/intake/add`).
- **Change:** per-item results of the add preview (existing or new filament, spools to create, location, problems
  tied to a field) on both path families (N18); filament colour in find results (N20); `offset` or a page on spool
  and filament searches (N9).
- **Keep:** today's reply fields and the dry-run guarantee (the preview changes nothing).
- **Check:** tests of the three replies.

### S3.8 Add spools
web app · L · Depends on: S3.6, S3.7; S2.6 when present · Beside: S3.9, S3.11, S3.14, S3.16
- **Files today:** `web/static/app.js` (Add spools, lines 180-358).
- **Change:** 04 4: by hand (find a filament you already have, search while typing, rows with swatch, New filament);
  from label photos (Take photo, Choose photos, photo strip and viewer, note for the Label Reader, Read labels with
  its reason); the read summary; the spool card with grouped fields, colour with swatch, estimated and confidence
  marks; the action bar with Preview and Add <n> spools; the link to Slicer presets; the unfinished add kept as a
  draft (`spoolwarden.draft.*`).
- **Keep:** what is created in Spoolman; the 8-photo limit.
- **Other interfaces:** app S4.7. The Hub page has no Add spools (feature idea B7). The command line cannot take
  photos; `add` prints where to add spools (S5.8).
- **Check:** AUT-5 on every state of Add spools; manual: release checklist step 6 (add by hand with VoiceOver).

### S3.9 Hub: spool read and edit for the phones, usage source
Hub · M · Depends on: S1.4 · Beside: S3.3 to S3.6, S3.8
- **Files today:** `web/intake_app.py`; `web/printers_app.py` (usage undo); `api.py`; `inventory.py`.
- **Change:** spool read and edit for the web app (preview and save a new weight, move, mark empty) and
  `GET api/spools/{id}` for the app (location, remaining, net and empty weight, tag, state, filament, lot) (N19, the
  phone parts); the spool a usage entry was taken from (N21).
- **Keep:** the app's existing spool routes; the tag link flow.
- **Check:** tests of each reply, including a refused change.

### S3.10 Spools
web app · L · Depends on: S3.6, S3.9 · Beside: S3.11, S3.14, S3.16
- **Files today:** `web/static/app.js` (Open spool, lines 361-429).
- **Change:** 04 5: Last tag; search while typing with "Sealed only" remembered, rows with swatch and paging; the spool
  sheet with Update weight, Move, Mark empty, Load into a printer and Link tag and open, each with its reasons.
- **Keep:** the 3 s tag poll only while the screen is visible.
- **Other interfaces:** app S4.8. The Hub page has no Spools section (feature idea B2). The command line
  cannot read tags; `spool` prints where (S5.8).
- **Check:** AUT-5; manual: release checklist step 6 (open a spool).

### S3.11 Printers
web app · L · Depends on: S3.6, S3.9; S2.3 when present · Beside: S3.8, S3.10, S3.12, S3.13, S3.14, S3.16
- **Files today:** `web/static/printers.js` (lines 5-525).
- **Change:** 04 6: the printers list with found printers; one printer with status in words, controls (Pause, Resume,
  Stop print set apart, light), camera, slots with Load and Unload, Filament used with Put it back, slot mapping with
  the Map by loading filament sheet, Printer settings (read-only on the public address unless allowed), adding a
  printer, Printers switched off.
- **Keep:** camera and stream limits; the server-sent stream closing when the screen is left.
- **Other interfaces:** Hub page S2.4 and S2.5; app S4.10 and S4.11; command line S5.5.
- **Check:** AUT-5 on the list and one printer; manual: release checklist step 6 (load into slot A4).

### S3.12 Recently added
web app · M · Depends on: S3.6; S2.6 when present · Beside: S3.11, S3.14
- **Files today:** `web/static/app.js` (History, lines 62-156); `web/intake_app.py` (history routes).
- **Change:** 04 7: list with the To check filter; one record with the photo viewer, four field groups, Edit then
  **Save changes**, "What is wrong?" and **Ask the Label Reader**, the suggestion, revisions with undo; the notice on
  the public address.
- **Keep:** Recently added is served on the home address only.
- **Other interfaces:** Hub page S2.7; app S4.12; command line S5.6.
- **Check:** AUT-5 on the list, a record and the public-address notice.

### S3.13 Slicer presets
web app · S · Depends on: S3.6 · Beside: S3.11, S3.14, S3.16
- **Files today:** `web/static/app.js` (Presets, lines 432-482).
- **Change:** 04 8: status naming Slicer Sync; filaments without a line; **Add to the line**; **Start a new line**;
  **Find a parent**; **Build presets now**; the dimmed More row and switched-off page.
- **Keep:** the presets endpoints.
- **Other interfaces:** Hub page S2.10; app S4.14; command line S5.7.
- **Check:** AUT-5 on, off and with filaments waiting.

### S3.14 Hub: service worker always served
Hub · S · Depends on: S1.4 · Beside: S3.2 to S3.8, S3.10 to S3.13, S3.16
- **Files today:** `web/static/sw.js` (notifications only); `web/printers_app.py` (served only with print alerts on,
  lines 157-158).
- **Change:** `sw.js` served whether or not print alerts are on, and the page shell cacheable by it (N22).
- **Keep:** print alerts as today.
- **Check:** a test that `sw.js` is served with alerts off.

### S3.15 Home screen and offline
web app · M · Depends on: S3.13, S3.14 · Beside: none
- **Files today:** `web/static/sw.js`; `web/static/app.js`.
- **Change:** 04 10: the Add to Home Screen sheet; the shell kept by the service worker so the app opens without the
  Hub; "Cannot reach the Hub" (the banner, the chip, the retry and the toast). The marks on each screen are S3.17.
- **Keep:** API replies are never cached.
- **Other interfaces:** the app is installed from its package and has its own offline state (S4.4). The Hub page
  is served by the Hub itself and shows "The Hub is not answering" (S1.9); the command line runs on the Hub.
- **Check:** manual: install to the home screen on an iPhone, switch the Hub off, open the app (shell and "Cannot
  reach the Hub" show); 08 13 status-bar check.

### S3.16 Refusal page and sign-in page
web app · S · Depends on: S3.2 · Beside: S3.3 to S3.6, S3.8, S3.10, S3.11, S3.13, S3.14
- **Files today:** `web/intake_app.py` (refusal text, lines 53 and 325-327); `web/auth.py` (sign-in page with inline
  styles, lines 313-374).
- **Change:** 04 11: the refusal page and its "Not at this address" variant in the new words, and the sign-in page on
  the web app's stylesheet with no inline style (N24; part of N15). The command the sign-in page names waits for the
  rename.
- **Keep:** the home-network gate; the sign-in approval itself.
- **Other interfaces:** the Hub page's gate is the lock (S1.5) and the app's is pairing (S4.5); the command line
  runs on the Hub and has no gate of this kind.
- **Check:** AUT-2 on `auth.py`'s page (no inline style); AUT-5 on both pages.

### S3.17 Offline marks on each screen
web app · M · Depends on: S3.15 · Beside: none
- **Files today:** `web/static/app.js` and each screen's script.
- **Change:** 04 10.3, third point: while the Hub cannot be reached, every group keeps its last data with
  "Last update <age>: the Hub did not answer." ("Not loaded: the Hub did not answer." when it never loaded), and
  each control that needs the Hub (buttons, switches, a list's search field and filters) gets `aria-disabled` and
  the reason "Needs the Hub."; rows that only open something are not marked. Each screen marks its own groups
  and controls; the shell switches the marks on and off.
- **Keep:** until this step, a press while offline shows the screen's own error in place, as today.
- **Other interfaces:** the app has its own offline state (S4.4); the Hub page shows "The Hub is not answering"
  (S1.9); the command line runs on the Hub.
- **Check:** AUT-5 with the Hub stopped, on two screens.

---

## 7. Stage 4: the app

Like Stage 3, this stage can start once Stage 0 is done.

### S4.1 Theme and tokens
app · M · Depends on: S0.4, S0.9 · Beside: Stage 3 steps
- **Files today:** `<app>/MainActivity.kt` (`AppFrame` with the stock schemes, lines 435-442; system bars 426-429);
  `res/values/themes.xml`, `res/values-night/themes.xml`; hard-coded status colours in `<app>/ui/home/HomeScreen.kt`
  (105-112), `<app>/ui/printers/PrintersScreen.kt` (97-102), `<app>/ui/printers/PrinterScreen.kt` (197),
  `MjpegView.kt` (166), `HlsPlayer.kt` (93); `<app>/ui/ColorSwatch.kt` (310-357).
- **Change:** the hand-written `SpoolwardenTheme(look, appearance)` (08 4 to 6, 9) wraps everything; `look` has the
  one value Console and the `nav`, `collection` and `detail` composition locals exist with Console's choices as
  their defaults, so later steps add themes without changing a caller. The appearance choice is read from the
  app's settings store (default System; its menu arrives in S4.2) and applied as 08 8 says, including
  `android:configChanges="uiMode"` on `MainActivity` and `setApplicationNightMode`, so a change of light or dark
  never recreates the activity or drops what is being typed. Status colours come from the tokens; the window
  background from `sw_window.xml`; dynamic colour stays off. The whole app changes look at once.
  The launcher icon of 05 1 and 08 11 comes with this step: the adaptive icon (foreground mark, `sw_launcher_bg`
  background, monochrome layer).
- **Keep:** screens, texts, navigation.
- **Check:** 08 test 5 Kotlin part. The app's colour entries leave `tests/literal_allowlist.txt` in this step except
  two reviewed exceptions that stay, each with its reason: the camera view's black ground and the white text drawn
  over the camera picture (07 CON-6); the swatch's fallback colour literal leaves with the step that rebuilds the
  swatch (S4.4), after which the swatch holds no colour literal. Size literals (dp) leave with the step that
  rebuilds their screen; AUT-1 Material roles; the app's
  own `ColorSchemeTest` (08 9), added in this step; manual: release checklist step 7 (Home with TalkBack) in light
  and dark, and a switch of the phone between light and dark while a field holds typed text (the text stays).

### S4.2 Shell and navigation
app · L · Depends on: S4.1 · Beside: Stage 3 steps
- **Files today:** `<app>/MainActivity.kt` (routes 114-131, `NavHost` 214-390, spool card dialog 392-419, NFC
  203-212, "Not paired" gates, connection poll 177-187); `<app>/ui/printers/PrintersEntry.kt` (local state, 20-52);
  `<app>/session/ServerSession.kt`.
- **Change:** 05 2: `NavigationSuiteScaffold` with the destinations of 05 2.3; the top app bar (place title,
  connection chip with the Hub connection sheet, appearance menu); type-safe routes, every screen a destination
  (the Printers local state becomes routes); Back as 08 14; gating with the Hub notice; the splash screen. Recent
  is a destination from this step: today's Recently added screens move onto the routes of 05 2.5 (`recent`,
  `recent/{hid}` and those of its sub-screens that exist today) with their behaviour unchanged; S4.12 rebuilds
  them. An NFC tap keeps opening today's spool card until S4.8.
- **Keep:** what each screen shows inside.
- **Check:** manual: release checklist step 7 (dialogs announced, focus returned, Back).

### S4.3 `strings.xml`
app · S · Depends on: S4.2, S0.8 · Beside: Stage 3 steps
- **Files today:** every Kotlin file under `<app>/ui/` (texts written inline, `PairTexts.kt`, `UpdateTexts.kt`);
  the shell of S4.2.
- **Change:** 05 15: the app reads the generated `strings.xml` (through `strings/en.json`), with plurals and
  positional arguments. The texts of the shell (bar, top bar, connection chip, appearance menu) and the app's name
  (`app_name`, 08 12) come from it in this step. The texts of a screen move when that screen is rebuilt (S4.4 to
  S4.15): the screen switches to the keys of 05, with the wording of 05, in its own step. Today's wording is never
  copied into the catalogue: the catalogue holds the design's texts only, one key per meaning.
- **Keep:** every text of a screen that is not rebuilt yet, as it reads today, written in the code and listed in
  `tests/strings_allowlist.txt` with its file and count (S0.7); each screen step removes its file's entries.
- **Editing the catalogue:** a step adds or changes only the keys of its own screens; a shared key (`common_…`,
  `status_…`, `nav_…`, `unit_…`) is changed by the step that owns the catalogue's tests, on request, so two
  branches never give one key two texts. Whoever edits `strings/en.json` regenerates in the same change.
- **Check:** 08 test 7 passes with the shell's Kotlin literals gone from the allow-list; the app builds; the app's
  name on the launcher and in the top bar comes from `app_name`.

### S4.4 Shared parts, states and semantics tests
app · M · Depends on: S4.3 · Beside: Stage 3 steps
- **Files today:** error cards and spinners in `<app>/ui/add/CaptureScreen.kt`, `ReviewScreen.kt`,
  `<app>/ui/profile/AddProfileScreen.kt`, `<app>/ui/home/HomeScreen.kt`; the five "Not paired" placeholders.
- **Change:** 05 3 and 08 10: status label, icons from the drawables, notice card for Hub notices, loading, empty,
  error and offline states, snackbar, the local network notice; AUT-8 set up for Home, Spools, Printers, Printer and
  Settings as they are, each later screen step adding its screen.
- **Keep:** the flows of each screen.
- **Check:** AUT-8 passes in light and dark at font scale 1 and 2.

### S4.5 Pairing
app · L · Depends on: S4.4 · Beside: S4.9, S4.15
- **Files today:** `<app>/ui/pair/PairScreen.kt`, `ManualPair.kt`, `QrScanner.kt`, `PairViewModel.kt`, `PairTexts.kt`;
  `<app>/MainActivity.kt` (permission gate, 237-245).
- **Change:** 05 4: one destination per step (network access, start, QR scanner, address, fingerprint, code,
  certificate changed), the banner, the security toggle worded as 02 5.6.
- **Keep:** certificate pinning; the pairing protocol.
- **Other interfaces:** Hub page S2.9 (shows the code); command line S5.6 (`pair`). The web app pairs nothing (04 1.1).
- **Check:** AUT-8 on each step; manual: pair against a test Hub with example data.

### S4.6 Home
app · M · Depends on: S4.4 · Beside: S4.5, S4.9
- **Files today:** `<app>/ui/home/HomeScreen.kt`; `<app>/ui/home/VersionLine.kt`.
- **Change:** 05 5.
- **Keep:** unfinished adds and the update notice.
- **Other interfaces:** Hub page Overview (S2.2); command line `status` (S5.1). The web app has no Home: its places
  are the bench tasks (04 2), and a Hub summary there is feature idea B4.
- **Check:** AUT-8; manual: release checklist step 7 (Home by swiping and by touch).

### S4.7 Add spools
app · L · Depends on: S4.4, S3.7; S2.6 when present · Beside: S4.5, S4.9, S4.15
- **Files today:** `<app>/ui/add/AddSpoolsScreen.kt`, `CaptureScreen.kt`, `ReviewScreen.kt`, `AddViewModel.kt`.
- **Change:** 05 6: photos, check the spools, filament picker, preview with per-item rows, spools added, each a
  destination; drafts kept.
- **Keep:** the camera flow; what is created.
- **Other interfaces:** web app S3.8; Hub page none (feature idea B7); command line `add` prints where (S5.8).
- **Check:** AUT-8 on Add spools; manual: release checklist step 7 (Add spools at 200 % font).

### S4.8 Spools and the spool screen
app · L · Depends on: S4.4, S3.9 · Beside: S4.9, S4.15 (not S4.5: both edit `MainActivity.kt`)
- **Files today:** `<app>/ui/search/SearchScreen.kt`; `<app>/ui/spool/SpoolCard.kt`; the spool card dialog in
  `<app>/MainActivity.kt` (392-419).
- **Change:** 05 7: Spools (search after a pause, no button); the spool screen with Update weight, Move, Mark empty,
  Load into a printer; Tag and Link to a sealed spool; an NFC tap now opens `tag/{uid}`.
- **Keep:** a load being written is never replaced by a new tap.
- **Other interfaces:** web app S3.10; Hub page none (feature idea B2); command line `spool` prints where (S5.8).
- **Check:** AUT-8 on Spools and Spool; manual: release checklist step 7 ("Sealed spools only" toggled by its words).

### S4.9 Add a line to the Filament Catalog
app · S · Depends on: S4.4 · Beside: S4.5 to S4.8
- **Files today:** `<app>/ui/profile/AddProfileScreen.kt`, `AddProfileViewModel.kt`.
- **Change:** 05 8 (was Add profile).
- **Keep:** what is saved; the list of existing lines with "Change parent" stays on this screen, in the new look,
  until S4.14 moves it to the Slicer presets screen (no working control goes away between two steps).
- **Other interfaces:** Hub page Settings > Filament Catalog, Add entry (S2.19); command line `catalog add` (S5.8).
  The web app has none yet (feature idea B8).
- **Check:** AUT-8 on the screen.

### S4.10 Printers list, add, find Klipper printers
app · M · Depends on: S4.4 · Beside: S4.5, S4.9, S4.15
- **Files today:** `<app>/ui/printers/PrintersScreen.kt`; `<app>/net/Api.kt`.
- **Change:** 05 9.1 to 9.3: the list with status shape and word; Add a Bambu Lab printer; Add a Klipper printer and Find
  Klipper printers (new in the app; the Hub routes exist).
- **Keep:** printer data and routes.
- **Other interfaces:** Hub page S2.4, S2.5; web app S3.11; command line S5.5.
- **Check:** AUT-8 on Printers.

### S4.11 One printer
app · L · Depends on: S4.10, S3.9 · Beside: S4.5, S4.9, S4.15
- **Files today:** `<app>/ui/printers/PrinterScreen.kt`, `PrinterViewModel.kt`, `PrinterTools.kt`,
  `ManualMapScreen.kt`, `MjpegView.kt`, `HlsPlayer.kt`.
- **Change:** 05 9.4 to 9.10: printer screen, slots panel, pick a spool, slot mapping panel, Map by loading filament,
  Printer settings, Filament used with Put it back.
- **Keep:** camera players; the confirmation before Stop print and Unload.
- **Other interfaces:** Hub page S2.4; web app S3.11; command line S5.5 (the live view and slot loads need a
  screen, so `printer live` prints where, 06 10).
- **Check:** AUT-8 on Printer; manual: release checklist step 7 (slot custom actions, Unload confirmation and Back).

### S4.12 Recently added
app · L · Depends on: S4.4; S2.6 when present · Beside: S4.5, S4.9, S4.15
- **Files today:** none (new in the app; the Hub's paired routes exist, 05 16).
- **Change:** 05 10: list with the To check filter, record, edit by hand, Ask the Label Reader, photo viewer; Recent
  joins the navigation bar.
- **Keep:** the Hub's history routes as they are (05 16).
- **Other interfaces:** Hub page S2.7; web app S3.12; command line S5.6.
- **Check:** AUT-8 on both screens.

### S4.13 Hub: Slicer presets actions for paired phones
Hub · M · Depends on: S1.4 · Beside: any step that does not edit `api.py`
- **Files today:** `api.py` (the line and build actions exist only under `api/profiles/web/…`, which phones may not
  call).
- **Change:** paired phones may list filaments without a line, add them to a line, create a line and build now (N25).
- **Keep:** what the web app calls today.
- **Check:** tests with a paired device's credentials.

### S4.14 Slicer presets
app · M · Depends on: S4.6, S4.13 · Beside: S4.5, S4.9
- **Files today:** the presets panel in `<app>/ui/home/HomeScreen.kt`.
- **Change:** 05 11: the Home panel and the Slicer presets screen, with the Product lines panel and its "Change
  parent" sheet (11.2); the list of existing lines leaves the catalog screen (S4.9) in this step.
- **Keep:** the other panels of Home.
- **Other interfaces:** Hub page S2.10; web app S3.13; command line S5.7.
- **Check:** AUT-8 on the screen.

### S4.15 Settings, app updates, licences
app · M · Depends on: S4.4 · Beside: S4.7, S4.8, S4.10 to S4.12
- **Files today:** `<app>/ui/settings/SettingsScreen.kt` (lines 52-76), `LicencesScreen.kt`; `UpdateTexts.kt`.
- **Change:** 05 12 and 13: Settings, Appearance (Light / Dark / System; Theme in S6.3), Hub connection, App updates,
  Licences, Developer (debug builds only).
- **Keep:** the fingerprint check's meaning; the update install flow.
- **Other interfaces:** Appearance: Hub page S2.19, web app S3.3; the command line follows the terminal (F5). App
  updates update the app itself; the Hub's updates are S2.13 and S5.8. Licences outside the app are feature idea B9.
- **Check:** AUT-8 on Settings; manual: release checklist step 7.

---

## 8. Stage 5: the command line

The command line can start once S2.1 is done (its status groups); it does not wait for the Hub page steps. Every
step of this stage edits `cli.py`, so they run one after another, never beside each other. **What waits for the
rename:** the executable name `spoolwarden`,
the `filament-kit` wrapper and its note, and every place that prints the command's own name (help, Fix lines,
`--version`, the user guide's command table). Until the rename those print `filament-kit`. New subcommand
spellings, output conventions, confirmations, `--json` and menus do not wait: they work under today's command name,
with the old spellings kept as silent aliases (06 2, 4).

### S5.1 Status vocabulary and output conventions
command line · L · Depends on: S2.1 · Beside: Stages 3 and 4
- **Files today:** `cli.py` (plain `print()` throughout); `status.py` (lines 219-250); `klipper_cli.py`; `menu_ui.py`
  (line 131).
- **Change:** 06 6.1 to 6.7: one status vocabulary with glyphs and colour (`NO_COLOR`, `--color`, `--plain`), tables
  that fit the width, words, numbers and dates, results and errors on standard error as `Error:` with a `Fix:` line,
  a progress line after 2 s for every wait, documented exit codes; `status` in the groups of S2.1.
- **Keep:** what each command does; the Hub service's log format (06 2).
- **Check:** AUT-9 for `status` and a failing command (the other commands of AUT-9 join as their steps land);
  manual: release checklist step 8.

### S5.2 Confirmations
command line · M · Depends on: S5.1 · Beside: Stages 3 and 4
- **Files today:** `cli.py` (`unpair` 363-375, printer remove inside `config`, `library rollback`, `profiles
  apply-updates`, `restore` 327-347, `uninstall` 1895-1925, `setup-code --new` 2138-2167).
- **Change:** 06 7: every destructive command asks with the Hub page's words, `--yes` for scripts, and refuses with
  exit code 2 and a Fix line when there is no terminal and no `--yes`. Harmless changes do not ask.
- **Keep:** what each action does once confirmed. Scripts that run these commands without a terminal need `--yes`
  from this step on; the release notes say so.
- **Other interfaces:** Hub page S1.6; web app S3.5; the app's confirmations come with each screen step (S4.5 to
  S4.15).
- **Check:** AUT-9 (a destructive command piped, without `--yes`, exits 2); manual: release checklist step 8 (answer
  "no").

### S5.3 `--json` and `--quiet`
command line · M · Depends on: S5.1 · Beside: Stages 3 and 4
- **Files today:** `cli.py`; `status.py`.
- **Change:** 06 6.8: `--json` on every command that prints data, in the Hub's own reply shapes; `--quiet`.
- **Keep:** standard output of the default form.
- **Other interfaces:** none needed: `--json` and `--quiet` are forms for scripts, and the other three interfaces
  already read the Hub's reply shapes themselves.
- **Check:** a test that every `--json` output parses and contains no escape byte.

### S5.4 Menus and interactive screens
command line · L · Depends on: S5.2, S2.17 · Beside: Stages 3 and 4
- **Files today:** `cli.py` (`config` menu 594-660, Storage and Printers submenus, Station voice prompt, the
  manual-map loop); `menu_ui.py`; `modules.py` (checklist, 292-340); `secret_input.py`.
- **Change:** 06 8: one key map for every screen; the `config` menu with staged changes, `s` to save and `q` to leave
  (asking when changes are unsaved), in the groups of 03 10; the Printers screen; the Features checklist showing
  needs before switching; Map by loading filament; the other prompts; `--numbered`.
- **Keep:** every setting reachable from `config` today.
- **Other interfaces:** Hub page Settings S2.19, Printers S2.4, Features S2.12; Map by loading filament also in the
  web app S3.11 and the app S4.11. Of the settings, the web app and the app hold only Appearance (S2.19).
- **Check:** manual: release checklist step 8 (`config --plain`, leave with the documented key); CLI-8 (secret entry).

### S5.5 `printer` commands
command line · L · Depends on: S5.3 · Beside: Stages 3 and 4
- **Files today:** `cli.py` (printer, 865-1240); `klipper_cli.py` (166-183).
- **Change:** 06 5 and 9.2: `printer list`, `show`, `test`, `add [--klipper]`, `use`, `dismiss`, `rename`, `address`,
  `access-code`, `api-key`, `lane-data`, `detect`, `scan`, `map [--by-loading]`, `report`, `reports`,
  `forget-certificate`, `forget`, `live`, `menu`; `klipper add-on`; a printer named by name, serial, id or a unique
  start of its name; the old `klipper` and `printer` spellings as aliases.
- **Keep:** what `printer map`, `report` and `unpin` do today.
- **Other interfaces:** Hub page S2.4, S2.5; web app S3.11; app S4.10, S4.11.
- **Check:** AUT-9 (`printer list`).

### S5.6 `recent`, `devices`, `pair`
command line · M · Depends on: S5.3, S2.8; S2.6 when present · Beside: Stages 3 and 4
- **Files today:** `cli.py` (`pair` 138-179, `unpair` 363-375, `intake` 679-776).
- **Change:** 06 9.3 and 9.4: `recent` with `show`, `revise`, `edit`, `undo`, and confidence when S2.6 is in;
  `devices` and `devices forget`; `pair` with `--slicer-sync`, `--weigh-station`, `--text`, the QR drawn by the Hub
  and the information as text after it; old spellings as aliases.
- **Keep:** `intake` subcommands keep working.
- **Other interfaces:** Hub page S2.7, S2.9; web app S3.12; app S4.5, S4.12.
- **Check:** AUT-9 (`recent`, `pair --text` as root); manual: CLI-9 (`pair --plain`).

### S5.7 `presets`, `features`, `weigh-station`, `tag-reader`
command line · L · Depends on: S5.3, S2.11 · Beside: Stages 3 and 4
- **Files today:** `cli.py` (`station` 182-354, `profiles` 1358-1526, `modules` 1529-1868, `reader` 1934-2066 and
  2170-2208).
- **Change:** 06 9.5 to 9.7: `presets` (status, build, lines, set-parent, restore-deleted, updates, accept-updates);
  `features` (list, menu, on, off, setup, apply, units) with the new setup names; `weigh-station` (pair,
  flash-display, pairing-state); `tag-reader` (list, new-token, revoke, flash); old spellings as aliases.
- **Keep:** what `modules`, `profiles`, `station` and `reader` do today.
- **Other interfaces:** Hub page S2.9, S2.10, S2.12, S2.16; web app S3.13; app S4.14.
- **Check:** AUT-9 extended to `presets status` and `features`.

### S5.8 The System commands
command line · L · Depends on: S5.3; S2.18 when present · Beside: Stages 3 and 4
- **Files today:** `cli.py` (`library` 1243-1355, `backup` and `restore` 306-347, `web` 2082-2135, `setup-code`
  2138-2167, `cert` and `ensure-fields` 779-798, `uninstall` 1895-1925, `update` 2498-2509,
  parser 2262-2427); `backup.py`; `updates.py`.
- **Change:** 06 9.8 to 9.14, 10 and 3: `config show` and `config set`; `label-reader status` and `test`; `catalog`;
  `backup create`, `list`, `keep`; `restore`; `web`; `remote get-certificate` and `firewall`; `setup-code`;
  `certificate`; `spoolman fields` and `address`; `update`; `uninstall`; `logs`;
  the pointer commands `add` and `spool`; `help aliases` and `help --markdown`; the grouped top-level help.
  `config theme` arrives in S6.10.
- **Keep:** old spellings as aliases; `restore`'s typed word.
- **Other interfaces:** Hub page S2.13, S2.14, S2.19; the pointer commands name the web app and the app for what needs
  a camera or NFC (06 10).
- **Check:** AUT-9 at 80 columns; a test that `help --markdown` lists every command of 06 3.2.

### S5.9 The `spoolwarden` command
command line · S · Depends on: S5.8 · Beside: S6.1 to S6.9, S7.4 to S7.6
- **Files today:** `cli.py` (program name, line 2260); the installed `filament-kit` entry point.
- **Change:** 06 2: `spoolwarden` installed where `filament-kit` is today; `filament-kit` becomes the wrapper that
  prints its one-line note on standard error; help, messages and Fix lines name `spoolwarden`; `--version` prints
  "Spoolwarden <version>".
- **Keep:** exit codes and standard output of every command through the wrapper.
- **Check:** AUT-9 run once through each name; a test that the wrapper's note goes to standard error only.

---

## 9. Stage 6: Themes

Built in the order of F6.4: the Hub's default first, then the picker with Console alone, then Workbench, Palette and
Panes one by one, each on the web and then on Android, and last the theme for new devices in every interface. A theme
changes only how things look and are laid out (F6.2), so no step here changes words, order or actions.

### S6.1 Hub: theme for new devices
Hub · M · Depends on: S2.17 · Beside: any step that does not edit the files below
- **Files today:** `setup_console/general_tab.py`; `setup_page.py` and `web/intake_app.py` (page shells); `api.py`
  (`GET api/info`).
- **Change:** the stored setting `appearance.theme` (console, workbench, palette, panes; default console), readable in
  `G state` and saved through the group save; delivered as `data-look` on `<html>` of both page shells, as the two
  `theme-color` metas and the two manifests of that theme, and as `look` in `GET api/info` (N1).
- **Keep:** a device that has chosen keeps its choice.
- **Check:** tests of the shells and `api/info` for each value.

### S6.2 Theme picker on the web
Hub page, web app · M · Depends on: S6.1, S2.19, S3.3 · Beside: S6.3
- **Files today:** the Appearance group (S2.19) and the web app's Settings sheet (S3.3); `components.css`.
- **Change:** 02 3.4, 03 10.2, 04 9.2: `theme-init.js` applies `spoolwarden.look` (or the Hub's default); the picker
  under Light / Dark / System with the Console tile, selected. The other tiles appear with S6.4, S6.6 and S6.8.
- **Keep:** Console as the look of every device that has not chosen.
- **Check:** AUT-5; 08 test 4 (profile groups keyed on the right themes).

### S6.3 Theme picker on Android
app · M · Depends on: S6.1, S4.15 · Beside: S6.2
- **Files today:** `<app>/ui/theme/SpoolwardenTheme.kt` (S4.1); `<app>/ui/settings/SettingsScreen.kt`.
- **Change:** 05 12.2, 08 9: the picker in Settings > Appearance with the Console tile; the choice in the app's
  settings store, passed to `SpoolwardenTheme(look, appearance)` (its signature and the `nav`, `collection` and
  `detail` locals exist since S4.1); first start uses `look` from the Hub.
- **Keep:** Console as today.
- **Check:** AUT-8 on Settings.

### S6.4 Workbench on the web
Hub page, web app · L · Depends on: S6.2 · Beside: S6.5
- **Files today:** `components.css` (profile groups keyed on Console only); `tokens.json` already holds Workbench.
- **Change:** the `sidebar`, `cards` and `card` profile groups keyed on Workbench (F6.1, 02 1.3); the Workbench tile
  in both pickers. The two pieces of shared markup the look needs are step S6.4b.
- **Keep:** markup and scripts: a theme brings no markup or script of its own (F6.1).
- **Check:** AUT-5 in Workbench light and dark; manual: release checklist step 4 (Workbench part). This step sets
  the size test (`tests/test_design_components.py`) to the numbers of F12 rule 7 and adds its page totals.

### S6.5 Workbench on Android
app · M · Depends on: S6.3 · Beside: S6.4
- **Files today:** the composables that read the profile locals.
- **Change:** `NavStyle.Sidebar` (rail on tablets), `CollectionStyle.Cards`, `DetailStyle.Card`; the Workbench tile.
- **Keep:** screens and routes.
- **Check:** AUT-8 in Workbench.

### S6.6 Palette on the web
Hub page, web app · L · Depends on: S6.4 · Beside: S6.7
- **Files today:** `components.css`.
- **Change:** the `pills`, `tiles` and `sheet` profile groups keyed on Palette; the rounded system stack; the Palette tile.
  The pill row sits under the top bar; More opens the More sheet; details of screens not yet on the shared opener
  show in place (S6.11).
- **Keep:** markup and scripts.
- **Check:** AUT-5 in Palette light and dark; manual: release checklist step 4 (Palette tiles read with field names).

### S6.7 Palette on Android
app · M · Depends on: S6.5 · Beside: S6.6
- **Files today:** the composables that read the profile locals.
- **Change:** `NavStyle.Pills`, `CollectionStyle.Tiles`, `DetailStyle.Sheet`; `FontFamily.Default` (08 14); the tile.
- **Keep:** screens and routes.
- **Check:** AUT-8 in Palette.

### S6.4b Shared parts the looks need
Hub page, web app · S · Depends on: S6.4 · Beside: S6.5, S6.6
- **Files today:** the collection builder and the shell's navigation in `web-shared/components.js`.
- **Change:** the "Sort by" label in every collection head (`coll__sortlabel`, catalogue key `coll_sort_by`; hidden
  under `table`; 02 6.1); the navigation marks a switched-off section with `data-state="off"` and its hidden
  suffix, from the Hub's list of features (02 2.2).
- **Keep:** the Console look unchanged; no text outside the catalogue.
- **Other interfaces:** the app draws both from its own composables (S6.5); the command line has neither.
- **Check:** AUT-5 in Console and Workbench on Printers; AUT-6 on the navigation.

### S6.6b Tiles keep second-priority fields where there is no detail
Hub page, web app · S · Depends on: S6.6 · Beside: S6.7
- **Files today:** `components.css` (the `tiles` group).
- **Change:** a collection whose items have no detail (backups, preset lines, features) shows its prio-2 fields as
  "key: value" under `tiles`, as under `cards` (02 6.1).
- **Keep:** tiles with a detail show prio 1 only.
- **Other interfaces:** the app's tiles follow the same rule (S6.7).
- **Check:** AUT-5 in Palette on Backups, Slicer presets lines and Features.

### S6.11 Details through the shared opener (Palette sheets)
Hub page · M · Depends on: S6.6b · Beside: S6.7, S6.9, S6.10
- **Files today:** `setup_static/setup_printers.js`, `setup_presets.js` (each toggles its in-row details itself).
- **Change:** these screens open and close details through the shared opener (02 6.2), so `sheet` (Palette) draws
  them in the detail host. The opener's script and styles go into the detail part (F12 rule 7), not the core.
- **Keep:** addresses (`#printers/<id>`), what a detail holds, the Console look.
- **Other interfaces:** the web app and the app already open details as their own places; the command line has none.
- **Check:** AUT-5 in Console and Palette on Printers and Slicer presets; focus returns to the row on close.

### S6.12 Details in the pane (Panes)
Hub page · M · Depends on: S6.8, S6.11 · Beside: S6.9, S6.10
- **Files today:** the detail part (S6.11); `setup_static/setup_settings.js`.
- **Change:** what Panes still lacks (02 6.2): one detail open at a time and Escape returning focus to the row; the
  row's actions and every hidden field (Slicer presets: material, "Set parent") inside the detail; the empty pane
  with its text on desktop; Back in the detail head on tablet and phone; Settings one group per pane (02 6.4).
- **Keep:** addresses; the other three looks.
- **Other interfaces:** the app's pane style is S6.13; the web app and the command line have no panes.
- **Check:** AUT-5 in Panes on Printers, Slicer presets and Settings; manual: release checklist step 4 (drill in
  and back). Until this step is on main the release notes list Panes as unfinished.

### S6.13 Android: detail styles and the Panes summaries
app · M · Depends on: S6.5, S6.7, S6.9 · Beside: S6.11, S6.12
- **Files today:** the composables that read `LocalDetailStyle`; the Panes section list.
- **Change:** `DetailStyle.Card`, `Sheet` and `Pane` where the app has an in-place detail (deferred from S6.5,
  S6.7 and S6.9); the Panes section list shows a summary for Printers, Recently added and Slicer presets from
  Home's requests (02 2.2).
- **Keep:** screens and routes; no request made only for a summary.
- **Other interfaces:** the web steps are S6.11 and S6.12.
- **Check:** AUT-8 in each look.

### S6.8 Panes on the web
Hub page, web app · L · Depends on: S6.6 · Beside: S6.9
- **Files today:** `components.css`; the navigation part of the shared component script.
- **Change:** the `list`, `rows` and `pane` profile groups keyed on Panes, with drill-in navigation on phones (F6);
  the Panes tile.
- **Keep:** addresses: the same `#section/<id>` places open the same things. Until S6.12, Printers and Slicer
  presets show details in place under Panes too; Panes is listed as unfinished in the release notes until then.
- **Check:** AUT-5 in Panes light and dark; manual: release checklist step 4 (drill into a printer and back, focus
  returns to the row).

### S6.9 Panes on Android
app · L · Depends on: S6.7 · Beside: S6.8
- **Files today:** the composables that read the profile locals; the navigation scaffold (S4.2).
- **Change:** `NavStyle.List`, `CollectionStyle.Rows`, `DetailStyle.Pane`; the tile.
- **Keep:** routes and Back.
- **Check:** AUT-8 in Panes.

### S6.10 Theme for new devices in every interface
all four · S · Depends on: S6.8, S6.9, S5.8 · Beside: none
- **Files today:** the Appearance group (S2.19); `cli.py` (`config`).
- **Change:** the "Theme for new devices" field with **Save theme for new devices** (03 10.2); `config theme
  [<theme>]` (06 9.8); the web app and the app already follow the Hub's default (S6.1 to S6.3).
- **Keep:** a device's own choice wins over the default.
- **Other interfaces:** the command line has no theme of its own; it follows the terminal (F5).
- **Check:** AUT-5 on the group; AUT-9 for `config theme`.

---

## 10. Stage 7: wording

The new names arrive with each rebuilt part. This stage changes what is left: the Hub's own messages, the words lint,
and the documents.

### S7.1 The Hub's own texts in the plain names
Hub · M · Depends on: S2.11 · Beside: Stages 3 to 6 where files differ
- **Files today:** Fix texts in `status.py`; error texts in `setup_console/*.py`, `setup_helper.py`; `no_preset`
  in `web/printers_app.py` (93-94); the busy-stream and internal-error texts in `web/intake_app.py`.
- **Change:** the remaining items of N15: Features (not modules), Weigh Station (not station), the commands of 06 4,
  the busy-stream and internal-error texts, `no_preset` naming Slicer presets. The command name in them waits for
  the rename.
- **Keep:** reply keys and status codes.
- **Check:** the word list of AUT-7 run over the Hub's message texts; AUT-9 output shows no old name.

### S7.2 Words lint and the last old names
all four · S · Depends on: S7.1 and every interface step of Stages 1 to 5 · Beside: S7.3
- **Files today:** the allow-list of AUT-7 (S0.7); `tests/strings_allowlist.txt` (S0.8);
  `android/app/build.gradle.kts` and the manifest (app label "filament-kit").
- **Change:** AUT-7 with no allow-list entry for an old name that a person reads; any old name left on a screen
  replaced. Entries may stay for identifiers that are never shown (catalogue keys, routes, setting keys, wire
  fields), each with the reason "identifier, not shown", and for the product name until the rename; any text left
  in the Hub page or web app scripts moved into the catalogue; the app label "Spoolwarden"
  (05 1; open point 12).
- **Keep:** the app's package and id (the rename's part).
- **Check:** AUT-7 and AUT-9 pass; 08 test 7 with no entry left in `tests/strings_allowlist.txt` for
  `setup_static/` or `web/static/`.

### S7.3 Documents in the plain names
documents · M · Depends on: S5.8; command names wait for S5.9 · Beside: S7.2
- **Files today:** `README.md`; `docs/user-guide.md`, `docs/install-server.md`, `docs/install-iphone-web-app.md`,
  `docs/android-app.md`, `docs/klipper.md`, `docs/known-gaps.md`.
- **Change:** the names of F2 throughout; the user guide's command table from `help --markdown` (06 3.2).
- **Keep:** the instructions' steps and their order.
- **Check:** the word list of AUT-7 run over `docs/` and `README.md`.

### S7.4 Hub: the product name, the installer's words and the bridge
Hub · L · Depends on: S7.2 · Beside: S5.9, S7.5, S7.6
- **Files today:** `strings/en.json` (`app_name`, `command_name`); texts that spell the name out; `install/`; the
  updater, the backup reader, discovery and the link parsers.
- **Change:** the product is Spoolwarden and the command `spoolwarden` in the two catalogue entries; every text
  that bypasses them moves onto the placeholders; page titles; the installer's first line and its once-only line
  about the new name; the units' `Description=` lines. The bridge, with no visible effect: the updater, the backup
  reader, discovery, link parsers and prefix checks accept the old and the new names.
- **Keep:** paths, users, unit names, the Python package, `FK_*`, protocol and scheme names, repository and asset
  names: nothing outside what a person reads changes name.
- **Other interfaces:** S5.9 (command line), S7.5 (app), S7.6 (web app, Slicer Sync, Klipper add-on), S7.7 (documents).
- **Check:** AUT-7 with the product-name entry gone from its allow-list; the upgrade tests of S7.8.

### S7.5 App: label and texts
app · S · Depends on: S7.4 · Beside: S5.9, S7.6
- **Files today:** `android/app/build.gradle.kts`, the manifest, `strings.xml`.
- **Change:** the app label "Spoolwarden" (05 1); every text that names the product or the command follows the
  catalogue.
- **Keep:** the application id, the signing keys, the link scheme.
- **Other interfaces:** S7.4, S7.6.
- **Check:** AUT-8; an installed 0.6 app updates in place and stays paired.

### S7.6 Web app, Slicer Sync and Klipper add-on: visible names
web app, PC tool, add-on · S · Depends on: S7.4 · Beside: S5.9, S7.5
- **Files today:** the web app's manifests and title; `pc-sync/installer/`; the add-on's messages.
- **Change:** the web app is "Spoolwarden" in its manifests, title and top bar; the PC tool is "Spoolwarden Slicer
  Sync" with the Start menu entries "Pair Slicer Sync", "Slicer Sync status" and "Uninstall Spoolwarden Slicer Sync",
  and the checkbox "Pair this PC with the Hub now"; the add-on's messages say Spoolwarden.
- **Keep:** the program file `filament-kit-sync`, the installer id and state folder; macro, variable and file names
  of the add-on.
- **Other interfaces:** S7.4, S7.5.
- **Check:** AUT-5 on the web app; the PC tool installs over the earlier version and keeps its pairing.

### S7.7 Documents in the new name
documents · M · Depends on: S5.9, S7.4 · Beside: S7.5, S7.6
- **Files today:** `README.md`, `docs/`, the notes of the next release.
- **Change:** Spoolwarden and `spoolwarden` throughout; one sentence says it was called filament-kit and that the
  old command still works; the user guide's command table from `spoolwarden help --markdown`.
- **Keep:** addresses, file names and on-device paths that did not change; the earlier release notes as history.
- **Other interfaces:** none.
- **Check:** the names test of S7.3 without its skip of the old name, with the history files and unchanged
  addresses as its only exceptions.

### S7.8 The rename's gate
all four · S · Depends on: S5.9, S7.4 to S7.7 · Beside: none
- **Files today:** the words lints; the upgrade scenarios.
- **Change:** a words test that fails on a visible "filament-kit" outside the history files and unchanged
  addresses; upgrade from the last release and from the last pre-release keeps pairing, discovery, the old
  command and restoring an older backup.
- **Keep:** every installed kit can update, pair and be found as before.
- **Other interfaces:** each is covered once.
- **Check:** both upgrade runs pass before the tag.

---

## 11. Hub API additions

Every item of the merged list of what the design needs from the Hub, with the step that adds it and the first step
that uses it. Items marked "feature idea" belong to an idea of `10-feature-ideas.md` that this order does not build;
they come with that idea, except the ideas Stages 12 and 13 build (B1 to B5 and B8; C2, C5, C9, C12, D3 and D6).

| # | Need | Added in | First used by |
|---|---|---|---|
| N1 | Theme for new devices: setting `appearance.theme`, `data-look` on the shells, `theme-color` metas, `look` in `GET api/info` | S6.1 | S6.2 |
| N2 | Save several settings of one group in one request, all or nothing | S2.17 | S2.19 |
| N3 | Check the setup code without a change; `tries_left`, `retry_at` | S1.4 | S1.5 |
| N4 | Per-field Label Reader confidence, per-record summary, engine, model and tier | S2.6 | S2.7 |
| N5 | Error replies name their field | S1.4 | S1.6 |
| N6 | QR codes drawn by the Hub, loadable as an image | S2.8 | S2.9 |
| N7 | One-line live summaries for every navigation section | S2.1 | S2.2 (S1.3 uses the fallback of 02 12) |
| N8 | Small versions of label photos | S2.6 | S2.7 |
| N9 | Offset or page on spool and filament searches | S3.7 | S3.8 |
| N10 | Test an On this Hub address before it is saved | S2.18 | S2.19 |
| N11 | Release of firmware and flash endpoints, and of the On this Hub engine settings | S2.15 (firmware, flash); S2.18 (On this Hub) | S2.16; S2.19 and S5.8 |
| N12 | Last backup time readable without the setup code | S2.17 | S2.19 |
| N13 | A progress fraction for jobs, and the step being run (`step`: `index`, `count`, `text`) | S1.8, S1.12 | S1.9 |
| N14 | Printer states for the whole list in one read or a stream | S2.3 | S2.4 |
| N15 | The Hub's own texts in the new names | S2.11 (feature titles); S3.16 (refusal and sign-in pages); S7.1 (the rest) | S2.12; S3.16; S7.1 |
| N16 | Cloud reads used today and the daily limit in `G state` | S2.1 | S2.2 |
| N17 | Web app page attributes (Hub name, Hub page address, Slicer presets on or off, spool editing) | S3.1 | S3.3 |
| N18 | Per-item results of the add preview | S3.7 | S3.8 (app: S4.7) |
| N19 | Spool read and edit: web app, app (`GET api/spools/{id}`), Hub page | S3.9 (web app and app); Hub page: feature idea B2 | S3.10 (app: S4.8) |
| N20 | Filament colour in find results | S3.7 | S3.8 |
| N21 | The spool a usage entry was taken from | S3.9 | S3.11 (app: S4.11) |
| N22 | `sw.js` always served, the shell cacheable | S3.14 | S3.15 |
| N23 | Two web app manifests and `apple-mobile-web-app-title` | S3.1 | S3.2 |
| N24 | The sign-in page on the web app's stylesheet | S3.16 | S3.16 |
| N25 | Slicer presets actions callable by paired phones | S4.13 | S4.14 |
| N26 | Status rows carry a group, also in `G overview` | S2.1 | S2.2 (command line: S5.1) |
| N27 | New setup names and `--hub ADDRESS` accepted | S2.11 | S2.12 (command line: S5.7) |
| N28 | `GET trust` reports `expires` | S1.4 | S1.5 |
| N29 | Shared static files served from one place to both pages | S0.10 | S1.1 |
| N30 | Icon sprite inline as the first child of `<body>` | S0.10 | S1.3 |
| N31 | One rule for whether a Bambu address change and a certificate forget take the Access Code | Not scheduled: open point 1 | S1.6 uses the interim (every interface asks for it) |
| N32 | Optional: the poll interval for a running slot mapping or map by loading | Not scheduled: open point 7 | S2.4, S3.11, S4.11 poll as today |
| N33 | Getting-started steps with a state and a hidden flag | Feature idea A1 | none in this order |
| N34 | Short spool link `/s/<id>` | Feature ideas A2, C6 | none in this order |
| N35 | String catalogue as static files; `{key, params}` on Hub messages | S0.10 serves the generated `strings.js`; the JSON file and `{key, params}`: feature ideas A3, E3 | S1.3 (the first texts read from the catalogue; web app: S3.3; app: S4.3) |
| N36 | Klipper scan relayed for the web app | Feature idea B3; a web token may call `POST /api/printers/scan` (EV1) | EV6b |
| N37 | Read-only Hub summary for paired devices | Feature idea B4; `GET /api/hub` (EV1) | EV6a, EV7a |
| N38 | Add a Filament Catalog entry from the web app | Feature idea B8; `POST /api/library/local/form`, the list and remove (EV1) | EV4d, EV6a, EV7b |
| N39 | `/LICENSE` and `/THIRD-PARTY.md` served as text | Feature idea B9 | none in this order |
| N40 | Running-low thresholds and list | Feature idea C1 | none in this order |
| N41 | Undo for spool changes and slot loads: the rule, `POST /api/events/{id}/undo` | HD1 | HD7d, HD8, HD9 |
| N42 | Where the Access Code is on each printer model | Feature idea C3 | none in this order |
| N43 | Colour name and family per filament, searchable | Feature idea C4 | none in this order |
| N44 | CSV export and import: `GET /api/export/{set}.csv`, `POST /api/import/spools`, `POST /api/import/locations` | HD5 | HD6, HD7d, HD8 |
| N45 | Spool label SVG with QR | Feature idea C6 | none in this order |
| N46 | Printer events with kind and reason; a stream for the app | Feature idea C7 | none in this order |
| N47 | Spools grouped by location with dry-box humidity | Feature idea C8 | none in this order |
| N48 | Monthly usage totals, kept 13 months: `GET /api/analytics`, `by=month` | HD3 | HD7b, HD8, HD9 |
| N49 | Demo data store, simulated printers, `demo` flag | Feature idea C11 | none in this order |
| N50 | Activity record with actor: the kinds of Stage 10's catalogue, `activity=1`, `subject`, `actor` | HD1 | HD6, HD7a, HD8 |
| N51 | Read a project file and match spools | Feature idea C13 | none in this order |
| N52 | Disk use per category | Feature idea D1 | none in this order |
| N53 | Update window and "no printer printing" check | Feature idea D2 | none in this order |
| N54 | Hub report job with redaction | HD6 | HD7a |
| N55 | Second backup folder and copy state | Feature idea D4 | none in this order |
| N56 | Backup check job | Feature idea D5 | none in this order |
| N57 | Health history from the event store: `GET /api/health` | HD1 | HD6, HD7e, HD8 |

---

## 12. Dependencies and the first ten steps

### 12.1 Dependency sketch

`A > B` means B needs A; `A + B > C` means C needs both. Steps after a comma can run beside each other. `A / B`
means both wait for the same step but edit the same file, so they run one after the other, in either order.

```
Stage 0   S0.1 > S0.2 > S0.3 > S0.4 > S0.5
                 S0.2 > S0.6 > S0.7 > S0.8 > S0.9 > S0.11 > S0.10
          (S0.8 also needs S0.4: both edit the generator; S0.10 also needs S0.3)

Stage 1   S0.10 + S0.11 > S1.1 > S1.2 > S1.3 > S1.5 > S1.6 > S1.7 > S1.9 / S1.10      S1.10 > S1.11
          S0.10 > S1.4 > S1.5            S1.8 > S1.9          (S1.4 and S1.8 touch only Hub files)

Stage 2   S1.11 > every Hub page section step
          S2.1 > S2.2      S2.3 > S2.4 > S2.5      S2.6 > S2.7      S2.8 > S2.9
          S2.2 + S2.11 > S2.12 > S2.13 > S2.19 < S2.17      S2.15 > S2.16      S2.6 > S2.18 > S2.19
          Printers (S2.4, S2.5), Recently added (S2.7), Slicer presets (S2.10) and Logs (S2.14) run beside each other

Stage 3   S0.10 > S3.1 > S3.2 > S3.3 > S3.4 > S3.5 > S3.6 > S3.8 / S3.10 / S3.12 / S3.13, S3.11
          S0.11 > S3.2      S3.7 > S3.8      S3.9 > S3.10, S3.11      S3.13 + S3.14 > S3.15 > S3.17      S3.2 > S3.16

Stage 4   S0.4 + S0.9 > S4.1 > S4.2 > S4.3 > S4.4 > each of S4.5 to S4.12 and S4.15 (S4.5 / S4.8)
          S4.6 + S4.13 > S4.14      S3.7 > S4.7      S3.9 > S4.8, S4.11      S4.10 > S4.11

Stage 5   S2.1 > S5.1 > S5.2 > S5.4      S2.17 > S5.4
                 S5.1 > S5.3 > S5.5 / S5.6 / S5.7 / S5.8 > S5.9
          S2.8 > S5.6      S2.11 > S5.7      (every Stage 5 step edits cli.py: one at a time)

Stage 6   S2.17 > S6.1 > S6.2 > S6.4 > S6.6 > S6.8 \
                  S6.1 > S6.3 > S6.5 > S6.7 > S6.9  > S6.10 (also needs S5.8)
                  S6.4 > S6.4b      S6.6 > S6.6b > S6.11      S6.8 + S6.11 > S6.12      S6.5 + S6.7 + S6.9 > S6.13

Stage 8   V1.1 > V1.2 > V1.3 > V1.4 > V2.1 / V2.2 / V2.3 / V2.4      V2.1 > V3      V2.1 to V2.4 + V3 > V4

Stage 7   S2.11 > S7.1 > S7.2 (after every interface step of Stages 1 to 5)      S5.8 > S7.3 (command names after S5.9)
          S7.2 > S7.4 > S7.5 / S7.6      S5.9 + S7.4 > S7.7      S5.9 + S7.4 to S7.7 > S7.8

Stage 9   SL1 > SL2 > SL3      SL2 > SL4 / SL5 / SL6      SL3 + SL4 + SL5 + SL6 > SL7
          (SL4, SL5 and SL6 may start beside SL1 against the contract in 03 section 15; they merge after SL2; SL3
          edits cli.py: one at a time)

Stage 10  EA1 > EA2 > EA3 > EA4      EA5 from the start      EA3 + EA5 > EA6      EA4 + EA5 > EA7      EA8 beside EA6 and EA7
          EA3 to EA8 > EA9
          (Stage 10 starts after Stage 9 is merged: EA2 and EA6 open files that SL steps change; EA5 and EA8 may start
          at once against the contract in 03 section 15; EA8 merges after EA3)

Stage 11  AF1 > AF2      AF7, AF8 from the start      AF1 + AF2 + EA3 merged > AF5      AF5 > AF3, AF4
          AF1 + AF5 + EA6 merged > AF6      AF1 to AF8 > AF9
          (AF5 opens files that EA3 opens and AF6 files that EA6 opens, so each starts after that step is merged;
          AF1, AF7 and AF8 open no file of Stage 10)

Stage 12  EV0 to EV9 from the start, against the contracts of the stage      EV7a > EV7b      EV1 to EV9 > EV10
          registry files: AF5 > EV1 (api.py)      AF5 > EV2 (cli.py, status.py, the string catalogue)
          AF6 > EV5 (setup_page.py, setup_overview.js)      EA6 > EV5 (setup.js)      AF6 > EV4d (setup_settings.js)
          files held by earlier steps: AF2 > EV3      AF3 > EV4b      EA7 + EA4 > EV6a, EV6b      EA8 > EV7a      AF8 > EV8
          (every step but EV7b and EV10 can start at once; the other steps send EV2 their string keys before it files)
          Auto: AS0 from the start      EV1 > AS1 (api.py)      EV2 > AS2 (cli.py, the string catalogue)
          EV6a + EV6b > AS3      EV7a + EV7b > AS4      EV4b > AS5      AS1 to AS5 > AS6

Stage 13  HD0 to HD10 from the start, against the contracts of the stage      HD1 to HD10 > HD11
          registry files: EV1 > HD1 (api.py)      EV2 > HD2 (cli.py, status.py, the string catalogue)
          EV5 > HD7e (setup_page.py, setup.js, setup_overview.js)      EA5 > HD7e (components.js, components.css)
          files held by earlier steps: EV6a + EV6b > HD8      EV7a + EV7b > HD9
          (every step but HD8, HD9 and HD11 can start at once; HD2 files the string keys of the other steps)

Stage 14  RC0 to RC10 from the start, against the contracts of the stage      RC2 > RC11
          registry files: HD1 > RC9 (api.py)      HD2 > RC2 (the string catalogue's form) > RC9 (cli.py, status.py, the
          string catalogue)      HD7e > RC3 (setup_page.py, setup.js, components.js, components.css)
          EV4d > RC3 (setup_settings.js)      EA2 > RC6 (__main__.py)
          files held by earlier steps: HD8 > RC4      HD9 > RC5
          (every step but RC4, RC5 and RC11 can start at once; RC9 files the string keys of the other steps)
```

Stages 3 and 4 do not wait for Stages 1 and 2: once Stage 0 is done they run beside them, each needing only the Hub
steps named in its own steps (S1.4, S2.3, S2.6). Stage 5 starts after S2.1 and needs S2.6, S2.8, S2.11, S2.17 and
S2.18 where its steps say so.

### 12.2 Suggested first ten steps

| Order | Step | Why now |
|---|---|---|
| 1 | S0.1 Token folder in the code | Everything else reads the tokens |
| 2 | S0.2 `tokens.json` version 2 | The keys the generator and the app need |
| 3 | S0.3 Generator: appearance script and preview tiles | The web's first script and the theme tiles |
| 4 | S0.6 Source tests (beside S0.3) | Token use is checked from the first rebuilt line |
| 5 | S0.7 Lint checks | No new literal colour, native dialog, bare field or old name can be added |
| 6 | S0.4 Generator: Android tokens (beside S0.7) | Starts the app's track and the Material contrast pairs (S0.5) |
| 7 | S0.8 Shared string catalogue | One set of words for the pages and the app |
| 8 | S0.9 Icon set and sprite | The shell and every status need the icons |
| 9 | S0.11 Shared component stylesheet and script (S1.8 can run beside) | The components every later step composes |
| 10 | S0.10 The Hub serves the shared files (S1.8 can run beside; S1.4 follows it) | Both pages can link the same files |

The step after these, S1.1, is the first a person sees: the whole Hub page in Console.

---

## 13. Open points

Things the design parts leave open. Each needs a decision before the step named; none is decided here.

1. **Access Code on a Bambu address change and a certificate forget (N31).** The Hub page and the web app call
   different endpoints (03 5.5, 04 6.8); until one rule exists every interface asks for the Access Code. Needed
   before S1.6 changes its interim, and before S3.11, S4.11 and S5.5 settle their dialogs and prompts.
2. **Settled: `size.side-w` and `size.list-w`.** They are in `tokens.json` in every theme (256px and 360px); nothing is left to set.
3. **Settled: the `size` entries of 05 1 in every theme.** 05 1 gives the value of each entry for Console,
   Workbench, Palette and Panes; `swatch-row` is two entries, `swatch-row-w` and `swatch-row-h`. S0.2 adds them.
4. **Settled: how the checks start on today's code.** The allow-lists carry today's findings, each with file, reason
   and count; a count may only go down; each step removes the entries of the files it rebuilds; the lists are empty
   of today's findings when stage 2 ends.
5. **Where the shared files are served, and the component script's name.** N29 asks for one place for both pages but
   names no path; 08 13 names `components.css` but not the shared component script. Needed by S0.10 and S0.11.
6. **Settled: the fake data for the tests.** `mockups/CONTENT-SPEC.md` is one example Hub, "Workshop hub", with
   data for every section of foundations 8 (Spools once EV4a builds it), and an Empty Hub variant for the empty
   states. S1.11 serves it.
7. **The poll interval of a running slot mapping (N32).** Optional; until set, the interfaces poll as today. Needed
   only if S2.4, S3.11 or S4.11 change the interval.
8. **The headless browser for AUT-5.** 07 15 names a headless browser but not which; it runs only in tests, and its
   licence and where it runs are open. Needed by S0.11 and S1.11.
9. **Settled: the app's Recent destination.** The app has Recently added screens, so S4.2 builds the bar with all
   five destinations and moves those screens onto the `recent` routes unchanged; S4.12 rebuilds them.
10. **A printer's id and its serial.** 06 writes `/api/printers/<serial>/…`, 05 `api/printers/{id}/…`; whether they
    are the same value is not stated. Needed by S5.5 (naming a printer by serial or id).
11. **"The web app answers on this Hub (port 8101)" in 06 9.12.** Whether this is the web service's own port behind
    the Hub's address or the Hub's own port is not stated. Needed by S5.8 (`web status`).
12. **Settled: the name on screen and the rename.** The product's name is one catalogue entry (`app_name`, also the
    app's label) and the command's name another (`command_name`); 08 12. Until the code is renamed they hold the
    old name; the rename changes the two entries. The application id stays with the rename.
13. **When the rename lands.** S5.9, the command names in S3.16, S7.1 and S7.3, and the version that removes the
    `filament-kit` wrapper (06 2 gives "0.8.0" as an example) follow it.
14. **When the unreleased Hub code is released.** S2.15 and S2.18 release code that exists but is not in a release;
    which release carries it decides when S2.16 and the On this Hub part of S2.19 can ship.

---

## 14. Coverage

Every screen-level section of 03, 04 and 05 and every command group of 06, with the steps that build it.

### 14.1 `03-hub-page.md`

| Section | Steps |
|---|---|
| 1.2 Addresses inside the page | S1.3 |
| 2.1 The lock | S1.4, S1.5 |
| 2.2 Saving | S1.7, S2.17, S2.19 |
| 2.3 Results and messages | S1.7 |
| 2.4 Standard states; 2.5 A section whose feature is switched off | S1.10 |
| 2.6 Dialogs used everywhere | S1.6 |
| 2.7 Refreshing data | S1.7, S2.3 |
| 3.1 Top bar; 3.2 Navigation; 3.8 Page frame | S1.3; the Spools entry and the page menu EV5; the Analytics entry HD7e |
| 3.3 Lock chip | S1.5 |
| 3.4 Appearance control | S1.2 |
| 3.5 Job indicator and job strip | S1.8, S1.9 |
| 3.6 The Hub is restarting; 3.7 The Hub is not answering | S1.9 |
| 4 Overview | S2.1, S2.2; the Devices tile and Checks row EV2, EV5; the history strips and the Filament line HD7e |
| 5 Printers (5.1 to 5.5, 5.7 to 5.9) | S2.3, S2.4 (dialogs S1.6) |
| 5.10 The live view | EV4b; Load a spool, the Auto notice, Stop waiting and the choice AS5 |
| 5.6 Add a printer; 5.4 Find Klipper printers and Klipper add-on | S2.5 |
| 6 Recently added | S2.6, S2.7 |
| 7 Devices | S2.8, S2.9; 7.9 and 7.10 EV3, EV4c |
| 8 Slicer presets | S2.10 |
| 9 Features | S2.11, S2.12 |
| 10 Settings | S2.17, S2.18, S2.19; 10.2 Theme S6.2, Theme for new devices S6.1, S6.10; 10.9 the form and list EV4d |
| 11 Flash a device | S2.15, S2.16 |
| 12 Updates | S2.13 |
| 13 Logs | S2.14; 13.4 Activity and 13.5 the Hub report HD6, HD7a |
| 14 Where today's controls went | the steps above, section by section |
| 15 Needs from the Hub | section 11 |
| 16 Spools | EV4a, EV5; 2.9 Undo, 2.10 CSV, the last ten events HD7d |
| 17 Analytics | HD7b, HD7e |

### 14.2 `04-web-app.md`

| Section | Steps |
|---|---|
| 1 Where the web app runs | S3.1 |
| 2 Navigation | S3.3 |
| 3.1 to 3.6 Patterns used on every screen | S3.2, S3.6 |
| 3.7 Sheets and dialogs | S3.5 |
| 3.9 Undo the last action | HD8 |
| 4 Add spools | S3.7, S3.8 |
| 5 Spools | S3.9, S3.10; 5.6 EV6a; the last events and the download HD8 |
| 6 Printers | S3.11; 6.5 Clear slot and 6.9 the guided add EV6b; Automatic, Load a spool, the Auto notice and its buttons (5.4, 6.2, 6.5) AS3; Undo, By month and the download HD8 |
| 7 Recently added | S3.12 |
| 8 Slicer presets | S3.13; your own entries EV6a |
| 9 More and Settings | S3.3; theme S6.2; 9.1 and 9.3 EV6a; the history table and the report line in 9.3 HD8 |
| 10 Home screen, offline and "Cannot reach the Hub" | S3.6, S3.14, S3.15, S3.17 |
| 11 The refusal page and the sign-in page | S3.16 |
| 12 Dialogs that replace the browser's own | S3.5 |
| 13 Touch targets | S0.11, S3.4 (AUT-5 checks hit areas) |
| 14 Needs from the Hub | section 11 |
| 15 Where today's controls went | the steps above |

### 14.3 `05-android-app.md`

| Section | Steps |
|---|---|
| 1 Baseline | S0.2, S0.4, S4.1 |
| 2 App shell | S4.2 |
| 3 Shared parts and states | S4.4 |
| 4 Pairing | S4.5 |
| 5 Home | S4.6; the Getting started line EV7a |
| 6 Add spools | S4.7 |
| 7 Spools and the spool screen | S3.9, S4.8; the Spools menu EV7b; 7.6 Automatic AS4; 7.9 Undo and the last events HD9 |
| 8 Add a line to the Filament Catalog | S4.9; the form and list EV7b |
| 9 Printers | S4.10, S4.11; 9.5 Clear slot and waiting, 9.12 EV7b; the Auto notice AS4; 9.10 By month and the download HD9 |
| 10 Recently added | S4.12; the download HD9 |
| 11 Slicer presets | S4.13, S4.14 |
| 12 Settings | S4.15; 12.2 theme S6.3; 12.3 and 12.8 EV7a; the history table and the report line in 12.8 HD9 |
| 13 App updates | S4.15 |
| 14 Accessibility | S4.4 (AUT-8), and the check of every screen step |
| 15 Strings and wording | S0.8, S4.3 |
| 16 Needs from the Hub | section 11 |
| 17 Where today's screens and controls went | the steps above |

### 14.4 `06-command-line.md`

| Section or command group | Steps |
|---|---|
| 2 The command name | S5.9; the rest of the visible rename S7.4 to S7.8 |
| 3 The command tree | S5.8 (help), S5.9; EV2 |
| 4 Old and new spellings | S5.5 to S5.8 |
| 5 Naming a printer, device or record | S5.5, S5.6 |
| 6 Output conventions | S5.1, S5.3 |
| 7 Confirmations | S5.2 |
| 8 Interactive screens | S5.4 |
| 9.1 `status` | S2.1, S5.1; `--history` HD2 |
| 9.2 `printer` and `klipper` | S5.5; `load`, `unload`, `clear`, `usage`, `--watch` EV2; `load ... auto` AS2 |
| 9.3 `recent` | S5.6 |
| 9.4 `devices` and `pair` | S2.8, S5.6; `show`, `set` and the new columns EV2; `pair --home-assistant` HD2 |
| 9.5 `presets` | S5.7 |
| 9.6 `features` | S2.11, S5.7 |
| 9.7 `weigh-station` and `tag-reader` | S5.7 |
| 9.8 `config show`, `config set`, `config theme` | S5.8; `config theme` S6.10 |
| 9.9 `label-reader` | S2.18, S5.8 |
| 9.10 `backup` and `restore` | S5.2, S5.8; `backup password`, `restore --password-file` HD2, HD4 |
| 9.11 `catalog` | S5.8; `add --ask`, `local` EV2 |
| 9.12 `web`, `remote`, `setup-code`, `certificate`, `spoolman` | S5.8 |
| 9.21 `spools` and `spool` | EV2 |
| 9.22 `activity`; 9.23 `undo`; 9.24 `usage`; 9.25 `export` and `import`; 9.26 `report` | HD2 |
| 9.13 `update` and `uninstall` | S5.2, S5.8 |
| 9.14 `logs` | S5.8 |
| 10 What the command line cannot do (`add`, `spool`, `printer live`) | S5.5, S5.8 |
| 11 Usability problems and their fixes | S5.1 to S5.8 |
| 12 Parity | the "Other interfaces" lines of the steps |
| 13 Needs from the Hub | section 11 |

### 14.5 What this order does not build

The parity gaps that the parts keep on purpose stay open after the last step: Add spools on the Hub page (feature idea
B7); licences outside the app (B9). Stage 13 builds undo, the activity log, the health history, analytics, CSV, the
encrypted backups, the Hub report (C2, C12, D6, C9, C5, D3 and the backup password) and the Home Assistant
integration. Stage 12 builds the live printer view and the Spools section on the Hub page (B1,
B2), the Hub summary in the web app and the app (B4), Find Klipper printers in the web app (B3), the catalog form in
every interface (B8) and the spool and slot commands (B5). The other ideas
of `10-feature-ideas.md` are not scheduled here either.

---

## 15. Stage 8: Share corrections

The Label Reader's opt-in list of corrections (03 10.5.1 and 10.5.2, 04 7.5, 05 10.6, 06 9.9). It is not part of
0.6: it ships in the first release where all four interfaces have it. The steps keep the ids the build uses: V,
after the reader's own name (the vision module).

### V1.1 Hub: what the reader can do
Hub · S · Depends on: S2.18 · Beside: Stage 6
- **Files today:** `local_reader.py`; the fake reader under `server/tests/fakes/`.
- **Change:** the Hub reads the reader's capabilities from its health reply (none for an old reader); the fake
  reader gains the corrections endpoints.
- **Keep:** reading labels with an old reader.
- **Other interfaces:** none see this step.
- **Check:** the reader tests with an old and a new fake reader.

### V1.2 Hub: the setting
Hub · S · Depends on: V1.1 · Beside: Stage 6
- **Files today:** the settings registry; the root job runner.
- **Change:** `label_reader.share_corrections` (off); a root job writes it to the reader and restarts it; status
  shows the reader's actual state. No address is a setting or is passed to the reader.
- **Keep:** the reader's own default.
- **Other interfaces:** each shows the switch's state in its V2 step.
- **Check:** the settings tests; the job against the fake reader.

### V1.3 Hub: corrections wait with the reader
Hub · M · Depends on: V1.2 · Beside: Stage 6
- **Files today:** `intake_history.py`; the Add spools Check step.
- **Change:** a correction (Revise, Edit, a changed field at Check) is handed to the reader with its photos, the
  stored reading and the corrected values; it never blocks or fails the save; a failed hand-over is shown as
  "Not waiting" with the reason; no photo kept, no entry.
- **Keep:** the save and the history record.
- **Other interfaces:** the "will wait" line is in each V2 step.
- **Check:** history tests with the fake reader down, slow and refusing.

### V1.4 Hub: routes for the list
Hub · M · Depends on: V1.3 · Beside: Stage 6
- **Files today:** the Hub page's and the phones' route tables.
- **Change:** list, remove, remove all, the package download and Send now, as thin authenticated routes (the
  upload itself is the reader's); the command line's `label-reader corrections` commands on the same functions.
- **Keep:** list and download need no code; remove, Try again and Send now do (03 10.5.2).
- **Other interfaces:** used by V2.1 to V2.4.
- **Check:** route tests per guard; 08 test 7 for the new texts.

### V2.1 Hub page: the group and "Corrections waiting"
Hub page · M · Depends on: V1.4 · Beside: V2.2, V2.3, V2.4
- **Files today:** `setup_static/setup_settings.js` (Label Reader group).
- **Change:** 03 4.2, 6.2, 6.4, 9.4, 10.1, 10.5.1, 10.5.2, 10.11: the switch and its paragraph, the card, the
  three dialogs, the one link line, the Features note.
- **Keep:** the rest of the Label Reader group.
- **Other interfaces:** V2.2 to V2.4.
- **Check:** AUT-5 on the group with 0, 1 and several corrections waiting.

### V2.2 Web app: the list and the lines
web app · S · Depends on: V1.4 · Beside: V2.1, V2.3, V2.4
- **Files today:** `web/static/app.js` (Recently added, Add spools).
- **Change:** 04 7.1, 7.5: the "will wait" line where a correction is saved, the read-only list with Remove at
  `#recent/corrections`, sending named as done on the Hub page.
- **Keep:** settings stay on the Hub page.
- **Other interfaces:** V2.1, V2.3, V2.4.
- **Check:** AUT-5 on the list; manual: correct a record with the switch on.

### V2.3 App: the list and the lines
app · S · Depends on: V1.4 · Beside: V2.1, V2.2, V2.4
- **Files today:** the Recently added and Add spools screens.
- **Change:** 05 2.5, 10.3, 10.6: the same as V2.2, at the route `recent/corrections`.
- **Keep:** screens and routes.
- **Other interfaces:** V2.1, V2.2, V2.4.
- **Check:** AUT-8 on the list.

### V2.4 Command line: `label-reader corrections`
command line · S · Depends on: V1.4 · Beside: V2.1, V2.2, V2.3 (one `cli.py` step at a time)
- **Files today:** `cli.py` (the commands V1.4 added).
- **Change:** 06 3, 5, 7, 8.3, 9.1, 9.9: `list`, `remove`, `package`, `send`, the config item, the status row,
  the four confirmations, `--json`; gaps against 06 filled.
- **Keep:** list and package need no sudo.
- **Other interfaces:** V2.1 to V2.3.
- **Check:** the command tests; AUT-9.

### V3 Reader updates
Hub, Hub page, command line · M · Depends on: V2.1 · Beside: V2.2 to V2.4
- **Files today:** the Updates section; `status`; the reader's installer wrapper.
- **Change:** the installed reader's version and a newer signed release are shown in Updates and `status`;
  "Update" runs the verified install over the old one; `local-intake update` on the command line.
- **Keep:** the reader's settings, token and corrections waiting across an update.
- **Other interfaces:** the web app and the app show the reader's state only.
- **Check:** upgrade tests with the fake release.

### V4 End-to-end test and documents
all four · M · Depends on: V2.1 to V2.4, V3; the reader's next version · Beside: none
- **Files today:** the e2e scenarios; `docs/user-guide.md`.
- **Change:** the scenario (install the reader, switch sharing on, correct a reading, see it waiting, download
  the package and check it holds no location or camera data, send to a local fake address, switch off,
  uninstall); the guide section "Share corrections"; the release notes.
- **Keep:** never a real upload address in a test or a document.
- **Other interfaces:** the scenario touches each once.
- **Check:** the scenario passes on the supported Ubuntu versions; it gates the release that carries the feature.

---

## 16. Stage 9: Storage locations

Storage locations become one ordered list of general locations (03 10.4, 04 4.5 and 5.4, 05 6.3, 6.5 and 7.4, 06 8.3
and 9.15). The six settings `locations`, `placement.pla_location`, `placement.box_prefix`, `placement.box_count`,
`placement.overflow` and `placement.sealed_location` (the last one hidden) are replaced. The contract the interface steps build
against is the row "A stored list of storage locations" in 03 section 15.

### SL1 Hub: the list, its file, the migration and the placement rule
Hub · L · Depends on: none · Beside: SL4, SL5, SL6 (against the contract)
- **Files today:** `config.py` (`locations` and the `placement.*` keys), `placement.py`, `inventory.py`,
  `server/tests/test_placement.py`.
- **Change:** a stored list in `storage.xml` in the Hub's state folder (`/var/lib/filament-kit`, where the event store
  also goes; the config file stays root-owned in `/etc/filament-kit`), written atomically, owned by the Hub's user with
  the mode of the other state files that the web unit reads (it reads the file through its existing read grant): one `<location>` per place in fill order, with `id` (`loc-<n>`, given by the Hub, never
  reused), `name`, `type` (`bulk` or `containers`), `limit` or `count`, `prefix` (the exact text before a container's
  number; a new location gets its name plus one space, and a rename sets it to the new name plus one space), `fill` (`none`, `any` or `materials` with `<material>`
  children), `overflow`, `default-overflow` and `sealed`. A start never fails because of storage:
  if the migration (or any later write at start) cannot write the file, the Hub logs it once, keeps the migrated list
  in memory, places spools with it exactly as the file would, and tries the write again at the next change and at the
  next start; while the list is only in memory the Checks show one row in group Hub, Needs a look, "Storage locations
  could not be saved ({reason})." with the Fix the Hub can name. A `storage.xml` that exists but cannot be read (broken
  XML, no permission) gives the same row with "Storage locations could not be read ({reason}).", and the Hub uses the
  list migrated from the config file until it is fixed; it does not overwrite the unreadable file (a save writes the
  new file and keeps the old one aside as `storage.xml.unreadable`). The old keys are read from the config file for the
  migration and never written. Validation as 03 10.4 (name 1 to 100 characters and unique with capitals
  ignored; limit 1 to 9999; containers 1 to 999; exactly one default overflow, which is Bulk storage and may have a
  limit; fill `any` not allowed on an overflow location; exactly one sealed-spools location, Bulk storage; a location's
  name is not a container's name of any set, and a set's prefix and count give no container named like a location,
  checked only when a location is added or renamed, or a set is added, renamed or changed in prefix or count so that
  a NEW clash would appear, with "{name} is the name of a container in {set}. Choose another name."; the check does
  not run when `storage.xml` is read or by the migration, so a file with an existing clash loads, and saving an
  unrelated edit of it succeeds). The
  placement rule of 03 10.4 (six steps, the longest matching material name, overflow locations that name the material
  among the own places, the default overflow's limit counted before the other overflow locations and ignored only
  when all are full, one spool at a time under the lock that keeps two adds from taking the same place), the
  how-full counts (the
  spools in Spoolman whose location is the name or one of the containers' names, counted the way today's "taken"
  set is), the lowest free container number (at least two digits), and the rename job (the spools stored there get
  the new name; a job with steps above 20 spools). The reasons: `material`, `any`, `overflow`, `overflow_none` and `sealed`; `overflow`
  ("every place for {material} is full") is used only when the own places or the "Any material" places had at least
  one candidate, `overflow_none` ("no place takes {material} automatically") when there was no candidate at all; the old
  values `pla`, `box` and `no_boxes` are no longer produced.
  - **Migration**, on the first start of the new version, only when `storage.xml` is absent (a file that exists is never
    migrated over, also after a rollback and an update), built from the config file in
    this order and dropping nothing:
    1. Every entry of `locations`, in its order: Bulk storage, no limit, fill `none`.
    2. `placement.pla_location`: that entry (added at the end if missing) gets fill `materials` = PLA. When it is
       also the overflow or the sealed place, the one location carries both roles (fill `materials` = PLA on an
       overflow location is allowed), so PLA keeps going there with no limit.
    3. `placement.box_count` above 0: an Individual containers location with `prefix` = `placement.box_prefix`
       verbatim, count = `box_count`, fill `any`. Its name is the prefix without trailing spaces; if that is empty,
       "Container". If that name is also `placement.pla_location`, `placement.overflow` or
       `placement.sealed_location` (a place today's rule uses as one literal name), the bulk location keeps the name
       and the set is named "<name> (containers)". Otherwise, if step 1 made a bulk entry of that name (the default
       "Storage box"), that entry becomes the set in its place; otherwise the set is put just before the overflow
       location. `box_count` = 0: no such location (other materials then go to overflow, as today). A `locations`
       entry that equals a container name of the set ("<prefix>01"): with a role (`placement.pla_location`,
       `placement.overflow` or `placement.sealed_location`) it becomes a Bulk storage location with that exact name
       and its role, beside the set, and the set keeps all its containers, also the one of that name; with no role it
       does not become a location, it is that container, and the spools stored there count in the set.
    4. `placement.overflow`: that entry (added last if missing) becomes overflow and default overflow.
    5. `placement.sealed_location`: that entry (added first if missing) gets the sealed mark.
    6. The notice "Storage locations were converted. Check them." is shown once on the Storage locations group and
       written once to the journal whenever a set was named "<name> (containers)" or "Container", and whenever a bulk
       location was kept beside a set under the name of one of its containers. That location's row then carries the
       warn line "Same name as a container in {set}." (Hub page; a `Note:` line under the table on the command line).
       The migration never fails and never renames a place.
  - The migrated list places every spool exactly where today's rule does. Spools already stored keep their location
    texts; container names are byte-identical (a container's name is the set's `prefix` followed by its number). While such a clash
    exists the text is one place, as today: a spool stored under it counts in the bulk location's "how full" and makes
    that container taken, so the set skips it; a request that names the text means the bulk location (the literal
    text is stored); an existing clash may stay, and only removing or renaming one side ends it. The
    old keys stay in the config file, untouched, so `update --rollback` finds its settings; the new version reads them
    only for the migration. A fresh
    install writes `storage.xml` with today's four default names in the same roles.
  - **One stated change of behaviour, not a loss:** when a plain `locations` entry became the container set, a request
    that names it ("Storage box") now means the lowest free container, where it used to store the literal text. This
    also holds for released apps, which get the name from `GET api/locations`. Spools already stored under the
    literal name keep it.
  - **Backup, restore, rollback, uninstall.** Backup includes `storage.xml` (it is state); restore puts it back, and a
    backup made before this version has none, so the first start after such a restore migrates from the restored config
    file. `update --rollback` to a version without storage locations: that version ignores `storage.xml` and reads its
    old keys, which were never changed; the file stays, and updating again uses it and does not migrate again.
    Uninstall removes it with the state folder; an uninstall that keeps the data keeps it.
- **Keep:** the location texts of spools already stored; unload from a printer (the previous place, else the
  sealed-spools location); the lock; the answers the released apps read.
- **Other interfaces:** none see this step alone.
- **Check:** the model, validation and migration tests; today's `test_placement` cases run through a migrated list
  and give the same places; and the cases pinned here: `pla_location` = `overflow`; `pla_location` = the container
  name; `overflow` = the container name; `sealed_location` = the container name; an empty and an only-spaces
  `box_prefix`; `box_count` 0; a rename with more than 20 spools; an unreadable `storage.xml` (the Hub starts, the row is shown, a save keeps `storage.xml.unreadable`); the state folder
  writable and `/etc` read-only (the first start migrates and writes); the state folder not writable (the Hub starts,
  places spools from memory, shows the row, and writes at the next start once it is writable); backup and restore
  carry the file; rollback and then update again does not migrate again; `pla_location` = "<prefix>01" with
  `box_count` 2 (PLA goes to the literal text without limit; the next other material goes to "<prefix>02" while a
  spool is at "<prefix>01"), the same for `overflow` and for `sealed_location`; a `storage.xml` with such a clash
  loads; saving an unrelated edit of it succeeds; adding a NEW clashing name is refused; the same refusal when a
  set is added, renamed or enlarged to a name that an existing location has; a plain `locations` entry equal to a
  container name does not become a location; the reasons `overflow` and `overflow_none`.

### SL2 Hub: the routes and the strings
Hub · M · Depends on: SL1 · Beside: SL4, SL5, SL6
- **Files today:** `api.py`, `setup_helper.py`, the web app's route table (`web/`), `strings/`.
- **Change:** `GET api/storage` (paired-device token; the web app gets a twin under its own base) with the locations (each
  `containers` location with `prefix` and `containers: [{name, number, taken}]`, `null` for bulk; `used` and `free`
  equal the counts of `taken`), `order_by_material` and `everything_else`; `P settings/storage` (code) taking and answering the whole list, or
  `errors` per row and field; a container-set name accepted as a spool's `location` everywhere a location is taken
  (the name of an Individual containers location means the lowest free container, one `containers[].name` means that
  container, and when a bulk location has the same text as a container the text means the bulk location;
  `placements[]` keep `{location, spools, placed_by}`); the reasons in the add preview and result, with the new
  value `overflow_none`; the refusal "{name} is the name of a container in {set}. Choose another name."; the strings of 03 10.4 and the
  reasons in the shared catalogue, key names given in the catalogue's style, among them "Storage locations could not be
  saved ({reason}).", "Storage locations could not be read ({reason})." and "Storage locations were not saved:
  {reason}."; a save that cannot write answers that refusal and writes nothing.
- **Keep:** `GET api/locations` answers a list of names, so released apps keep working.
- **Other interfaces:** SL3 to SL6 read these.
- **Check:** route tests per guard; the contract fields; the catalogue and wording tests (08 test 7).

### SL3 Command line: `locations`, the menu, the refusal
command line · M · Depends on: SL2 · Beside: SL4, SL5, SL6 (one `cli.py` step at a time)
- **Files today:** `cli.py`, `menu_ui.py`, the installer's storage question.
- **Change:** 06 3.1, 3.2, 7, 8.3, 9.8, 9.15: `locations` with `add`, `edit`, `move`, `remove`,
  `default-overflow` and `sealed` (`edit` also takes `--no-overflow`), the table and `--json`, the `Note:` line after
  the table when the default overflow has no limit beside other overflow places, and the refusal of `--takes any`
  with `--overflow` and the refusal of a new name that is a container's name (`Error:` with the sentence of SL2), the
  `Note:` line "Same name as a container in {set}." for an existing clash, `--json` with `prefix` and `containers`;
  in the `config` screen, Use as overflow set to yes sets "Any material" back to "Nothing, only when you choose it"; the Storage locations screen of `config` and its summary
  row "{n} locations · {m} with a limit"; `config set` with one of the six old keys refused with
  `Error: storage locations are a list now.` and `Fix: spoolwarden locations`; the installer's "Use the default
  storage locations?" keeps its text and, on "n", opens the new list. `locations` and the `config` group write
  `storage.xml` directly (run as root with sudo, and by the installer before the Hub runs) with the same storage code
  as the Hub, under the Hub's lock that already keeps two processes apart, and with the Hub's owner and mode; the Hub
  reads a changed file again without a restart. A rename that also renames spools runs in the command's own process
  with the same code. A channel into the running Hub for changes, where the command line already has one, is an equal
  choice: one lock, the Hub's owner and mode on the file, and no restart. A save that cannot write stops with `Error:`
  "Storage locations were not saved: {reason}." and a `Fix:` line.
- **Keep:** the other `config` items and keys.
- **Other interfaces:** the same changes as SL4.
- **Check:** the command tests; the menu tests (numbered and full-screen); AUT-9.

### SL4 Hub page: Storage locations
Hub page · M · Depends on: the contract in 03 section 15; real data from SL2 · Beside: SL1
- **Files today:** `setup_static/setup_settings.js` (the Storage locations group).
- **Change:** 03 10.4 and 10.11 in all four themes: the Locations collection with its row actions, the detail region
  for Add and Edit (with "Any material" disabled on an overflow location; ticking "Use as overflow" while it is chosen sets the
  radio to "Nothing, only when you choose it" and unticking does not change it back; the refusal at the Name field
  for a container's name; the warn line "Same name as a container in {set}." on a row with an existing clash), the panel "Where a new spool goes", the
  warn notice under the list when the default overflow has no limit beside other overflow places, the group's Save,
  the Remove dialog and the refusals.
- **Keep:** the group's place, order and "Save storage locations".
- **Other interfaces:** SL3, SL5, SL6.
- **Check:** AUT-5 on the group with one, several and over-limit locations; the unsaved-changes guard.

### SL5 Web app: the Location select and Move
web app · S · Depends on: the contract in 03 section 15; merges after SL2 · Beside: SL1, SL4
- **Files today:** `web/static/app.js` (Add spools, the spool sheet).
- **Change:** 04 1.2, 4.5, 5.4 and 14: the Location select with "Automatic" first and, after the preview, the
  supporting line "<place> (<why>)" under it (no rule text from the Hub, so no `data-auto`), then every
  location in fill order with how full it is, one entry per Individual containers location, "Full"; the same
  entries in Move; the page never builds a container name: it matches a spool's location text with each location's
  `name` and then each `containers[].name`, sends the set's `name` or one `containers[].name` to place or move, and
  shows a text that matches nothing as it is, under no location; the reasons in the preview and result.
- **Keep:** editing the list stays on the Hub page and the command line.
- **Other interfaces:** SL3, SL4, SL6.
- **Check:** AUT-5 on the select with a full location and a container set.

### SL6 App: the Location field, preview rows and Move to
app · S · Depends on: the contract in 03 section 15; merges after SL2 · Beside: SL1, SL4
- **Files today:** the Add spools and spool screens, `strings.xml`.
- **Change:** 05 6.3, 6.5, 7.4 and 16: the Location field with "Automatic" first and, once the preview ran, the
  supporting line "<place> (<why>)", then the locations with how full; preview rows with the reason; "Move to" rows
  with how full as supporting text; the app never builds a container name: it matches a spool's location text with
  each location's `name` and then each `containers[].name`, sends the set's `name` or one `containers[].name` to
  place or move, and shows a text that matches nothing as it is, under no location.
- **Keep:** the empty-list sentence, which points to the Hub page.
- **Other interfaces:** SL3, SL4, SL5.
- **Check:** AUT-8 on the field and the sheet.

### SL7 Documents
documents · S · Depends on: SL3 to SL6 merged · Beside: none
- **Files today:** `docs/user-guide.md`, the install guide, the command table (`spoolwarden help --markdown`), the
  release notes.
- **Change:** the user guide's Storage locations text, the install guide's storage question, the command table with
  `locations`, one line in the release notes.
- **Keep:** the wording of the other sections.
- **Other interfaces:** none.
- **Check:** the documents tests; the words lint.

**Out of scope:** labels or QR codes for locations and containers; a "what is where" view; moving several spools at
once; humidity per container; limits by weight; the change of the rest of the config from JSON to XML.

---

## 17. Stage 10: Events and alerts

The Hub writes every thing that happens and that a person, a history or an integration may want later once, as an
**event**, into one store. The alert banners, the toast, the Alerts list and the notifications (02 8.7 to 8.9, 03 2.8,
4.2 and 10.13, 04 3.8, 5.5 and 9.2, 05 3.6, 5, 7.1 and 12.7, 06 8.3 and 9.16 to 9.18) all read this one store. No
feature keeps a second history of its own from now on (the two usage logs and the intake history stay as they are;
they are not events). The contract the interface steps build against is the rows "An event store", `GET api/alerts`,
`POST api/alerts/test`, `GET api/spools/low` and `GET api/storage-use` in 03 section 15.

### The event store

An event has:

| Field | Content |
|---|---|
| `id` | whole number, rising by one, never reused; the cursor clients use ("everything after 1412") |
| `at` | time, UTC, to the second; a writer may give it (the web unit's late hand-over), otherwise the store sets it |
| `kind` | a dotted name from the catalogue below, e.g. `print.paused` |
| `severity` | `info`, `ok`, `warn` or `bad` (the banner kinds) |
| `subject` | what it is about: type and id, plus the name at that time: `printer`, `spool`, `device`, `location`, `hub` |
| `actor` | who caused it, as `{type, id?, name?}`: `hub` (the Hub noticed it, or the installer or an automatic job did it), `device` with the paired device's id and name (the phone web app's pairing and a Weigh Station are devices), `page` (Hub page), `cli`, `connector`. The Hub page gives the id of the trusted computer it runs on (empty when the computer is not trusted) and that computer's name (or "Hub page"); the command line gives the name "command line" |
| `data` | named values of the kind (job name, grams, slot, spool id, material, before and after values; `run` and `batch` below) |
| `condition` | only for lasting states: a key such as `print-paused:<printer id>` and `raised` or `cleared` |
| `undo` | served with every event, not stored: `{possible, until?, why_not?}`, with `undone` and `undo_of?` beside it (Stage 13). User-action events carry the complete before and after values in `data` (below), which is what an undo puts back |

- **Texts are not stored.** An event stores its kind and values; each interface builds the sentence from the catalogue
  of texts (so a language pack changes old events too). The API also returns the built title and sentence in the Hub's
  language, for clients that want ready text (the Home Assistant integration).
- **Storage.** XML under the Hub's state folder, `events/<yyyy-mm>.xml`, one file per month, one `<event>` element per
  event with `<v name="...">` children for `data`; appended without rewriting the file, and a reader tolerates a torn
  last element after a crash. A small `events/conditions.xml` holds the conditions that are raised now, and
  `events/next-id` the counter. Owner and mode as the other state files.
- **Who writes the store.** Only processes that can write the Hub's state folder: the Hub service, the command line as
  root and the Hub's own timers (the store's lock keeps them apart). The web unit, which runs as its own user and can
  write only its own folder, never writes the store and never reads its files. It hands its events to the Hub over the
  channel it already has (its token, the Hub's local address) by the web-only route `POST api/events/web`,
  `{events: [{kind, at, subject, actor, data}]}`. The Hub accepts only the `spool.*` kinds from it, gives the id, keeps
  the `at` the web unit sent and sets the actor: `device` (the web app's pairing) for the phone web app, `connector`
  for the connector's tools. When the Hub does not answer, the spool change still succeeds and the event waits in the
  web unit's own folder, in `events-outbox.xml` (at most 500, the oldest dropped), and is sent with the next
  hand-over. The code that changes spools (`inventory.py`) does not call the store itself: it reports to an **event
  sink** it is given (in the Hub the sink is the store, in the web unit the hand-over, in the command line the store).
  The web unit reads events, alert settings, the running-low list and storage use through Hub routes with its token
  (they are among the routes a web token may call); no file grant for `events/` is needed or used.
- **Ids are never reused.** When the store works out its counter it takes the highest of: the counter file, the highest
  id found in the month files, the recorded high-water mark and the ids in the conditions file. A restore reads the
  present store's last id before the state folder is replaced and, after the replacement, tells the store to carry
  that number as its high-water mark; so ids continue above every id ever given. Events newer than the backup are gone
  with the rest of the state, as the restore dialog says.
- **Reading.** `GET api/events` takes `since` (an id) or `since_at` (a time, UTC) and `alert=1` (only events of alert
  types that are on). The answer gains `oldest` (the lowest id still kept), `gap` (true when `since` is lower than
  `oldest` minus one: events between were deleted by age) and `test` (the test alert, below). Stage 13 adds the query
  values `activity=1` (only the kinds of the Activity list), `subject=<type>:<id>` and `actor=<type>` or
  `actor=<type>:<id>`.
- **Two values that tie events together.** Every `print.*` event of one print run and its `usage.recorded` carry the
  same `run`, made by the Hub when it first writes an event for that run (`r-<id of that first event>`); Klipper events
  also carry `printer_job` (Moonraker's job id) when known. Bambu gives no usable run id of its own (its task id is "0"
  for prints started on the network or at the printer), which is why the Hub makes one. All `spool.*` events caused by
  one request carry the same `batch`: the Recently added record's id when the request made one, otherwise an id the
  Hub (or the web unit) makes for the request.

```
<events version="1" month="2026-11">
  <event id="1412" at="2026-11-17T04:12:09Z" kind="print.runout" severity="warn" actor="hub"
         subject="printer" subject-id="p-3" subject-name="Workshop X1"
         condition="print-paused:p-3" state="raised">
    <v name="job">bracket_v4.3mf</v><v name="slot">A2</v><v name="percent">41</v>
  </event>
</events>
```

- **Retention.** Kept 400 days (setting `events.keep_days`, 30 to 3650), so a year of months can be compared; whole
  month files older than that are deleted once a day by the 5-minute loop. Nothing else prunes.
- **A published contract.** The catalogue of kinds and the names of their `data` values are a published contract from
  the first release that has them: kinds and values are added, never renamed or removed. The Home Assistant integration
  and `--json` readers rely on this.
- **Over the wire** the API stays JSON, the protocol all clients already speak; the stored data is XML.

### The catalogue of kinds

"Now" means this stage's code emits it. "Stage 13" means the name is reserved here and Stage 13 emits it (its
values are in the table, so the kinds never change).

| Kind | When | Severity | Condition | Values | Written |
|---|---|---|---|---|---|
| `print.started` | a job starts | info | - | job, printer, run, printer_job (Klipper) | now |
| `print.paused` | a job pauses for any reason but runout | warn | raises `print-paused:<printer>` | job, percent, reason (`user`, `error`, `unknown`), stage text, run, printer_job (Klipper) | now |
| `print.runout` | a job pauses because filament ran out | warn | raises `print-paused:<printer>` | job, percent, slot if known, run, printer_job (Klipper) | now |
| `print.resumed` | a paused job runs again | ok | clears `print-paused` | job, run, printer_job (Klipper) | now |
| `print.finished` | a job ends well | ok | clears `print-paused` | job, minutes, run, printer_job (Klipper) | now |
| `print.failed` | a job ends cancelled or with an error | bad | clears `print-paused` | job, percent, reason (`cancelled`, `error`, `unknown`), error text, run, printer_job (Klipper) | now |
| `printer.error` | a printer error code appears (Bambu HMS, print error); the same code on the same printer is told again only after 30 minutes, a different code or the same code on another printer at once | bad | - | code, text | now |
| `printer.offline` / `printer.online` | the Hub loses or regains a printer | warn / ok | `printer-offline:<printer>` | - | now |
| `usage.recorded` | filament use of a job is settled | info | - | printer, job, spool, material, grams, run, printer_job (Klipper) | now |
| `spool.low` | an opened spool falls to or under the running-low threshold | warn | raises `spool-low:<spool>` | spool, filament, material, grams left, others in stock, batch | now |
| `spool.ok` | that spool is above the threshold again, emptied, or removed | ok | clears `spool-low` | spool, batch | now |
| `spool.added`, `spool.opened`, `spool.weighed`, `spool.moved`, `spool.emptied`, `spool.loaded`, `spool.unloaded` | a person or the Hub changes a spool | info | - | spool, before and after (location, grams, slot), batch | now |
| `location.renamed` | a storage location is renamed (one event, not one `spool.moved` per spool) | info | - | from, to, spools | now |
| `storage.low` | the Hub's disk passes the warn or the bad limit (one event per limit passed) | warn / bad | raises `storage-low` | free, total, percent used, direction (`down` when the disk fell back from a worse limit) | now |
| `storage.ok` | the disk is under the warn limit again | ok | clears `storage-low` | free, total | now |
| `device.down` / `device.up` | a Weigh Station stops or starts answering (Tag Readers are not covered, below) | warn / ok | `device-down:<device>` | - | now |
| `check.failed` / `check.ok` | a row of the Hub's checks changes between OK and Needs a look | warn / ok | `check:<row key>` | row text | now (shown as the health history, Stage 13) |
| `condition.cleared` | a raised condition is no longer true (see Conditions and alerts) | info | clears the key it names | key, reason (`reconciled`, `subject_removed`, `feature_off`) | now |
| `hub.started` | the Hub starts | info | - | version | Stage 13 |
| `hub.updated` | after an update or a rollback | info | - | from, to, rollback | Stage 13 |
| `hub.restored` | after a restore | info | - | backup, made_at | Stage 13 |
| `backup.finished` | a backup is made, by either backup maker | ok | - | file, bytes, encrypted, nightly | Stage 13 |
| `backup.failed` | a backup fails, in either backup maker | warn | - | reason, nightly | Stage 13 |
| `device.paired` / `device.removed` | a pairing is made or revoked | info | - | kind | Stage 13 |
| `settings.changed` | every settings save and feature switch, from the page, the command line or the installer | info | - | group, names (the settings' names), feature, on | Stage 13 |
| `printer.added`, `printer.changed`, `printer.removed` | the registry's add, edit and remove | info | - | family, names (what changed) | Stage 13 |
| `catalog.changed` | an own entry is added or removed, the catalog is updated or rolled back | info | - | what (`entry_added`, `entry_removed`, `updated`, `rolled_back`), entry, version | Stage 13 |
| `slot.cleared` | Clear slot | info | - | spool, slot, before_location, after_location, batch | Stage 13 |
| `usage.undone` | a filament-used entry is undone | info | - | printer, job, spool, grams, entry | Stage 13 |
| `record.changed` | a Recently added record is revised, or its revision is undone | info | - | record, what (`revised`, `undone`) | Stage 13 |

- **How runout is told from another pause.** Bambu: the printer's stage "Paused: filament runout". Klipper: a filament
  sensor or filament-system object reporting no filament at the moment of the pause (the assumption of EA2). Where
  the Hub cannot tell, the event is `print.paused` with reason `unknown`: the person is still alerted.
- **Why a job stopped.** `print.failed` has three reasons. Klipper: from Moonraker's job history (`cancelled`; `error`
  and a shutdown are `error`). Bambu: `error` when the printer reports a print error at the stop, otherwise `unknown`,
  because nothing in the code or its test data tells a person's cancel from another stop. The sentence for `unknown`
  is "<job> stopped at <percent> %." with nothing added (02 8.8). Until a recorded report shows that a Bambu printer
  tells a cancel in a way the Hub can read (prove-first item 4 of EA2), a Bambu printer never says "It was
  cancelled."
- **Which devices are watched.** `device.down` and `device.up` are written only for a Weigh Station, and only when the
  Hub can ask it: its address is set on the Hub and exactly one station is paired (the known limit of 0.6.2). Tag
  Readers are not covered. The Hub keeps when a reader last called (the web unit hands it over), but a reader calls
  only when it is used, so its silence means nothing and no `device.down` is written for it; the kinds stay reserved
  for them.
- **Data values are never secrets.** A changed key or code is told by its name and the word that it changed, never by its
  value.
- **Every action leaves an event, with who did it.** Stage 13 adds the kinds above and gives each user action the actor
  of its place: the Hub page, the command line, the installer and automatic jobs (`hub`), a paired device as before,
  the Weigh Station as its device, the Claude connector. Before Stage 13 the Hub page and the command line were
  recorded as the Hub.
- **Before-values are complete** on the spool kinds, so a change can be put back: `before_slot` is filled, `before_grams`
  and `after_grams` are always filled on a weight event, a tag link adds `before_tag` and `after_tag`, and marking empty
  adds `before_archived`.
- First sight of a printer after the Hub starts writes no event (as today's push logic), and slot-mapping jobs write
  none.

### Conditions and alerts

- A **condition** is a state that lasts until something ends it (a paused print, a full disk, a low spool, a silent
  device). It is raised by one event and cleared by another. What is raised now is what the alert banners show. A
  **moment** is an event with no condition (print failed, printer error).
- **Conditions are reconciled.** A raised condition is checked against the present state at Hub start, at each
  printer's first sight and in the 5-minute loop; one that is no longer true is cleared by a `condition.cleared`
  event: `reconciled` (the state is no longer so: a paused print that is not paused any more, a printer that
  answers), `subject_removed` (the printer, device or spool was removed) or `feature_off` (the check row no longer
  exists). It clears the key it names and is never an alert. Removing a printer, a device or a spool clears its
  conditions at once.
- **The newest raise wins.** A later raise of the same condition replaces the stored one, whatever its severity. So when
  the disk falls from "full" back under 95 % but stays over the warn limit, `storage.low` is written again with
  severity warn and the value `direction` = `down`, and the banner changes to "almost full". A `storage.low` with
  `direction` = `down` is never sent as an alert.
- An **alert** is an event of an alert type that is switched on. The alert types are Hub-wide, one switch each, in
  Settings > Alerts (03 10.13):

  | Alert type | Events | Default |
  |---|---|---|
  | Filament ran out | `print.runout` | on |
  | Print paused | `print.paused` | on |
  | Print failed or stopped | `print.failed` | on |
  | Printer error | `printer.error` | on |
  | Print finished | `print.finished` | off |
  | Storage almost full | `storage.low` | on |
  | Spool running low | `spool.low` | on |
  | Device stopped answering (description: "A Weigh Station or a printer stopped answering.") | `device.down`, `printer.offline` | off |

- Every event is written whatever the switches say; the switches only decide what is shown and sent as an alert.
- **A printer error repeats rarely.** The same error code on the same printer is told again only after 30 minutes; a
  different code, or the same code on another printer, is told at once.
- **Who changes them.** The alert types and thresholds are changed on the Hub page and with `spoolwarden alerts` only.
  No route lets a paired phone or the web app change them; the web app and the Android app show them read-only with
  the line "Change this on the Hub page."
- Each device decides for itself whether it gets notifications (one switch on that device), and keeps the switch on
  the device, not on the Hub: the Hub page keeps "Notifications in this browser" in the browser, the Android app in
  the app, and the phone web app is on while it has a push subscription. Banners inside an open interface need no
  switch.
- **The test alert.** `POST api/alerts/test` stores nothing. The Hub keeps one test for the caller for 60 seconds and
  gives it once, as `test: {title, text}`, in that caller's next `GET api/events` answer; the client shows it as a
  notification. The caller is the paired device of the token or, for the Hub page, the browser id it sends as `client`.
  From the command line (`spoolwarden alerts test`) the test goes to every client that asks within 60 seconds, and the
  web unit sends it to every push subscription. The phone web app's own test button keeps today's push test route.
- **The browser id.** The Hub page makes a random id on first use, keeps it in the browser (`localStorage`,
  `spoolwarden.browser`) and sends it as `client` on its events requests. Nothing about a browser is stored on the Hub.
- Rules and thresholds are stored as XML in the Hub's state folder (with the `events/` folder), `alerts.xml`: the eight
  switches, the running-low threshold and the two storage limits; it holds no per-device entries. It is written in the
  Hub process (`P settings/alerts`) and by the command line as root, with the Hub's owner and mode, as `storage.xml`.
  The phone web app's push subscriptions move from `push.json` into `push.xml`, in the web unit's own folder where
  `push.json` is, written by the web unit (same content; read once from the old file, which is then left alone).
  Backup includes `alerts.xml` and the `events/` folder; uninstall removes them with the state folder; `push.xml` is
  kept and removed as `push.json` is today.

### EA1 Hub: the event store
Server builder · Depends on: none · Beside: EA5
- **Files today:** new `server/filament_kit/events.py`, new `server/filament_kit/event_kinds.py`, new tests.
- **Change:** the event store of this section: write, read with a cursor, a time and a wait (`since`, `since_at`,
  `wait` up to 55 s), the lowest id it still keeps (for `oldest` and `gap`), month files, conditions (a later raise
  replaces the stored one, whatever its severity), retention, the counter (the highest of the file, the month files,
  the high-water mark and the conditions) with a function for the restore to carry a number as the high-water mark,
  and the catalogue of kinds (`condition.cleared`, `location.renamed`, the values `run`, `printer_job`, `batch` and
  `direction`, the reason `unknown` on `print.failed`). A caller may give the event's time.
- **Keep:** the two usage logs and the intake history.
- **Other interfaces:** none see this step alone.
- **Check:** the store's tests: ids rise by one and are never reused, also when the counter file is lost or a high-water
  mark is carried over; a torn last element after a crash is tolerated; conditions are raised and cleared and the
  newest raise wins; a read by time and the lowest kept id are right; month files older than `events.keep_days` are
  deleted whole; the catalogue's kinds and value names are pinned.

### EA2 Hub: everything that writes events
Server builder · Depends on: EA1 · Beside: EA5
- **Files today:** new `server/filament_kit/watch.py`, new `server/filament_kit/alerts.py`,
  `server/filament_kit/__main__.py`, `server/filament_kit/inventory.py`, `server/filament_kit/bridge/loading.py`,
  `server/filament_kit/bridge/usage.py`, `server/filament_kit/bridge/klipper/usage.py`,
  `server/filament_kit/bridge/klipper/manager.py` (runout objects), `server/filament_kit/config.py`, new
  `server/filament_kit/event_sink.py`, `server/filament_kit/storage.py` (the rename event),
  `server/filament_kit/backup.py` (the one call at restore; the later kinds `backup.finished` and `backup.failed` will
  open it again for another reason), new tests.
- **Change:** a watcher on both printer families' listeners, subscribed through their existing hooks without changing
  those files (if the Bambu side must change, `bridge/connection.py` belongs to this step); the 5-minute loop (disk,
  low spools, devices, check rows, the reconciling of conditions and the daily deletion of old month files); spool and
  usage events through the event sink (`inventory.py` reports to it); the rename event; the rules, thresholds and `alerts.xml`; the disk measurement (the filesystem that
  holds the Hub's state, the backups folder's filesystem when it is another one, and what Spoolwarden itself keeps:
  backups, photos of recently added spools, the Label Reader on this Hub, events and logs) and the running-low list
  (an opened spool, not sealed and not empty, at or under the threshold; default 150 g, 10 to 2000; checked every 5
  minutes and right after the Hub changes a spool's weight).
  `alerts.xml` is in the Hub's state folder and holds no per-device entries; a start never fails because it cannot be written: the defaults apply from
  memory and the Checks show one row in group Hub, Needs a look, "Alerts settings could not be saved ({reason})." Backup
  includes `alerts.xml` and the `events/` folder; uninstall removes them with the state folder. The eight
  alert type keys are fixed: `runout`, `paused`, `failed`, `printer_error`, `finished`, `storage`, `running_low`,
  `device_down`.
- **Keep:** the printer listeners' behaviour for everything else; the config file.
- **Other interfaces:** EA3 reads this step's rules and numbers.
- **Check:** prove first (assumption 3): Moonraker exposes a filament sensor or filament-system state that the Hub can
  read at the pause. If a printer has none, its runout arrives as "Print paused" (`print.paused`, reason `unknown`).
  Prove first (assumption 4): whether a Bambu printer reports a cancel in a way the Hub can read; until that is shown
  with a recorded report, Bambu never says "It was cancelled." Then the tests: each kind of the catalogue marked "now" is written by its cause; first sight of a printer writes no
  event; every event is written whatever the switches say; a condition that is no longer true is cleared by its event;
  `run` and `batch` are shared as the store rules say.

### EA3 Hub: routes, command line, status rows and the texts
Server builder · Depends on: EA2 · Beside: EA5
- **Files today:** `server/filament_kit/api.py`, `server/filament_kit/cli.py`, `server/filament_kit/status.py`,
  `strings/en.json` and its generated copies (`strings/strings.js`, `server/filament_kit/shared_static/strings.js`,
  Android `strings.xml`), new tests.
- **Change:** the routes of 03 section 15 (`GET api/events` with `since`, `since_at`, `alert`, `oldest`, `gap` and
  `test`, `GET api/alerts` with `P settings/alerts` served in the Hub process, `POST api/alerts/test`,
  `GET api/spools/low`, `GET api/storage-use`; no `api/alerts/device`; the names may be adjusted by the builder, the
  fields may not); the web-only route `POST api/events/web` and the read routes (events, alerts, running low, storage
  use) in the list a web token may call; the command line of 06 3.1,
  3.2, 6.8, 8.3, 9.1 and 9.16 to 9.18 (`events`, `alerts`, `spools low`, the Storage row and the Running low note of
  `status`, the Alerts group of `config`); and all the texts of this stage in the catalogue (the table of 02 8.8 and
  the strings of 03 2.8, 4.2, 10.13, 04 3.8, 5.5, 9.2 and 05 3.6, 12.7), among them "Alerts settings could not be saved
  ({reason})."; `GET api/alerts` answers exactly the eight fixed keys `runout`, `paused`, `failed`, `printer_error`,
  `finished`, `storage`, `running_low`, `device_down`, and `alerts set <type> on|off` takes exactly these (the command line writes `alerts.xml` directly as root).
- **Keep:** the other routes and commands.
- **Other interfaces:** EA4 to EA8 read these routes and keys. Only this step opens the catalogue: the client steps
  name the keys they need to this step before it is filed and add none themselves.
- **Check:** the route tests per guard; the contract fields; the command tests; the catalogue and wording tests
  (08 test 7).

### EA4 Hub: Web Push from the store
Server builder · Depends on: EA3 · Beside: EA5
- **Files today:** `server/filament_kit/web/push.py`, `server/filament_kit/web/printers_app.py`,
  `server/filament_kit/web/intake_app.py`, `server/filament_kit/web/app.py` (gives the sink), new
  `server/filament_kit/web/event_outbox.py`.
- **Change:** Web Push fed from the event store with all alert types, not only print states: the push sender no longer
  polls the printers, it waits on `GET api/events?alert=1&wait=55` through the web unit's channel and sends each alert
  to the subscriptions; the web unit hands its spool events to the Hub (`POST api/events/web`, the outbox
  `events-outbox.xml` of at most 500 in its own folder); the subscriptions move from `push.json` to `push.xml`, in the
  web unit's own folder; a start never fails because `push.xml` cannot be written; the web twins pass the Hub's
  routes of EA3 on. Every push ends in a shown notification; when an alert is over, the push replaces its notification
  (the event that ended it, the alert's tag, `silent: true`, `renotify: false`) for print paused, filament ran out and
  device stopped answering only, and never for storage almost full or spool running low; every alert push and its
  replacement carry the header `Topic` (a hash of the tag, at most 32 characters, left out if a push service refuses
  it) and a replacement has a time to live of 1 hour; a condition's tag is `sw-condition-<key>` (02 8.8).
- **Keep:** the limits of today's push: the optional push package, internet from the Hub to the phone maker's push
  service, and the web app opened at an address the phone trusts.
- **Other interfaces:** EA7 reads the web twins.
- **Check:** the push tests with the store as the source; `push.xml` is written from `push.json` once and the old file
  is left alone.

### EA5 Shared components: the alert banner, the Alerts list, the events poller
Bug-bash 1 · Depends on: the contract in 03 section 15 · Beside: EA1 to EA4 (can start at once)
- **Files today:** `server/filament_kit/shared_static/components.js`, `server/filament_kit/shared_static/components.css`,
  new `server/filament_kit/shared_static/alerts.js`, its browser tests.
- **Change:** the alert banner (02 8.8), the Alerts list (02 8.9), the events poller (`since` or `since_at`, `alert=1`,
  `wait=0` every 10 s; the browser id of the Hub page, kept in `localStorage` `spoolwarden.browser` and sent as
  `client`) and the browser-notification helper, in all four themes.
- **Keep:** the existing banner and toast behaviour.
- **Other interfaces:** EA6 and EA7 mount them.
- **Check:** prove first (assumption 1): a browser shows notifications for a page served with the Hub's self-signed
  certificate once the person has accepted it. If a browser refuses, the switch shows "This browser cannot show
  notifications" there and the banners and toasts remain; the public address with a real certificate is the way out,
  said in that text. Then AUT-5 on the banner (one, two and three alerts; condition and moment) and the Alerts list
  (empty and full).

### EA6 Hub page: banners, Storage row, Running low, Settings > Alerts
Bug-bash 1 · Depends on: EA3, EA5 · Beside: EA7, EA8
- **Files today:** `server/filament_kit/setup_page.py`, `server/filament_kit/setup_console/overview.py`, new
  `server/filament_kit/setup_console/alerts_tab.py`, `server/filament_kit/setup_static/setup.js`,
  `setup_static/setup_overview.js`, `setup_static/setup_settings.js`, their CSS (which CSS files it needs is not
  established: see the map's check below).
- **Change:** 03 2.8 (banners mounted on every section, the toast, `G events` every 10 s), 4.2 (the Storage row with its
  "Storage use" panel, the Running low card with its full-list dialog), 10.1 and 10.13 (the group Alerts, fourth in
  the order; "Notifications in this browser" kept in the browser, the test alert shown from `test` in the events
  answer, the hint about a background tab), the addresses of 03 1.2 and the page routes.
- **Keep:** the groups' places and each group's Save.
- **Other interfaces:** EA7 and EA8 mount the same banner.
- **Check:** AUT-5 on Overview with a full disk and with spools running low, and on the Alerts group; the unsaved-changes
  guard.

### EA7 Web app: banners, "Alerts on this phone", Running low
Klipper builder · Depends on: EA4, EA5 · Beside: EA6, EA8
- **Files today:** `server/filament_kit/web/static/app.js`, `web/static/printers.js`, `web/static/sw.js`, its CSS.
- **Change:** 04 3.8 (banners, toast, the Alerts list as a sheet), 5.5 (the Running low filter and its rows), 9.2 (the
  panel "Alerts on this phone" with "Recent alerts"; the switch is the push subscription; the three texts that said
  "print alerts" say "alerts"), and the service worker's notification for every alert type: it shows a notification on
  every path of its push handler, also for a payload it does not understand (a plain "Spoolwarden" notification that
  opens the app), and the web app closes its own notifications whose alert is no longer raised when it is opened or
  comes to the front.
- **Keep:** the push switch, the test button (it keeps today's push test) and their limits as they are.
- **Other interfaces:** none.
- **Check:** AUT-5 on the shell with alerts, the Spools chip and the Settings sheet.

### EA8 App: the watching service, notifications, banners, Alerts list, Settings > Alerts
App builder · Depends on: the contract in 03 section 15; merges after EA3 · Beside: EA6, EA7
- **Files today:** new package `alerts/`, `AndroidManifest.xml`, `ui/components/NoticeCard.kt`, `ui/home/HomeScreen.kt`,
  the Spools and Settings screens, the API client (the exact screen files are not established: see the map's check
  below).
- **Change:** 05 3.6 (the alert banner as `NoticeCard`, the toast, the Alerts list), 5 (the banners and the line
  "<n> spools running low"), 7.1 (the Running low chip), 12.7 (the switch "Alerts on this phone", the notification
  permission, the permanent notification "Watching the Hub for alerts", the test alert, "Recent alerts"), the alert
  notifications (the switch kept in the app, the test alert shown from `test` in the events answer) and the routes
  `alerts` and `settings/alerts`.
- **Keep:** the pairing, the Hub notices and the deep links.
- **Other interfaces:** none.
- **Check:** prove first (assumption 2): a foreground service with a permanent notification may hold the waiting
  connection without a time limit. The App builder checks the current Android documentation for the service type
  first; if no type allows it, the fallback is a check every 15 minutes with the app closed (and immediate alerts
  while the app is open), and the Play Store plan gets the question. Then AUT-8 on Home with alerts, the Spools chip and
  Settings > Alerts.

### EA9 Documents
Design + docs · Depends on: EA3 to EA8 merged · Beside: none
- **Files today:** `docs/*.md`, `README.md`, `release-notes/`.
- **Change:** the user guide's text on events and alerts, the command table (`spoolwarden help --markdown`) with
  `events`, `alerts` and `spools low`, one line in the release notes.
- **Keep:** the wording of the other sections.
- **Other interfaces:** none.
- **Check:** the documents tests; the words lint.

**Order.** EA1 > EA2 > EA3 > EA4; EA5 from the start; EA6 and EA7 after EA5 (EA7 also after EA4); EA8 beside them,
merging after EA3. Stage 10 starts after Stage 9 (SL1 to SL7) is merged: EA2 and EA6 open files that SL steps change.
No file is opened by two EA steps. `backup.py` is opened in EA2 for the restore call only; the later kinds
`backup.finished` and `backup.failed` will open it again for another reason, which is said here so that it is not a
surprise.

**How far the file map is checked.** It is built from one reading of the code, not from opening every file. Each
builder confirms its list before starting and, if it needs a file of another step, stops and says so instead of
opening it. Not in the map because nobody looked: which CSS files EA6 and EA7 need, the exact Android screen files,
and how the generated string copies are produced.

**Later work, so that no file is opened twice for the same reason.** The Hub page's Spools section and "the Hub at a
glance" in the apps read `GET api/spools/low`, `GET api/events` and `GET api/storage-use` as they are; the activity
log, the health history and the analytics page read the store and add the kinds marked "Stage 13" in the files that own
those actions (`backup.py`, `apply.py`, `pairing.py`), none of which this stage opens; undo adds one new file that reads
the before values; running low inside the slicer reads `GET api/spools/low`; the Home Assistant integration is a separate
integration that reads `GET api/events` with a paired read-only device and needs nothing changed on the Hub but that
role.

**Out of scope:** the activity log, undo, health history and analytics (Stage 13 builds them on this store); the Hub page's
Spools section and "the Hub at a glance" in the apps; running low inside the slicer; the Home Assistant integration
itself (Stage 13); e-mail, chat or other outside notification services; quiet hours; alerts per printer or per filament line.

---

## 18. Stage 11: Address and first run

A new Hub answers on port 443, so its address has no port; the Weigh Station and the printer-side tag service serve
HTTPS only, and so does a Label Reader on another machine once its own software can; the installer's first question lets
the Hub page take over the rest of the setup (Guided Setup), and that page leads the owner through what is left (Getting
started, the guided printer add, the Label Reader lead-in). The parts that specify it are 03 4.2, 5.6, 7.3, 9.4, 10.5,
10.7, 10.11 and 15, 06 3.1, 3.2, 9.1, 9.2, 9.6, 9.19 and 9.20, 02 6.5, and the typed address of 04 1 and 05 4.5. The
contract the interface steps build against is the rows "`GET start`", "The Hub's port", the three values of the
station's hello call, the found Bambu Lab printers and the remote reader's HTTPS in 03 section 15.

### The rules of the stage

- **The code's fallback stays 8710.** `config.py` is not changed. A first install writes `port` into the configuration
  file itself (443, or the port the installer's question gives). An install whose file has no `port` key keeps 8710
  whatever happens, and no update ever moves an existing Hub; `spoolwarden port` and Settings > Network and addresses are
  the only ways to move one.
- **Binding below 1024.** The Hub's unit has empty capability sets, so for a port below 1024 the installer writes a
  drop-in that gives exactly `CAP_NET_BIND_SERVICE` (ambient and bounding); for a port of 1024 or more it removes the
  drop-in. The unit file itself does not change. The Weigh Station's unit gets the same drop-in.
- **Remote access and 443 cannot share one machine.** Switching Remote access on while the Hub holds 443 is refused
  before anything is changed, and the Hub never moves by itself. Sharing 443 by name through nginx was looked at and
  dropped: the Hub would see every caller as `127.0.0.1`, which breaks its home-network limit and the per-address lock
  on wrong setup codes.
- **HTTPS on the satellites.** A listener of ours that another machine can reach serves HTTPS only; a listener on
  `127.0.0.1` stays as it is. The Weigh Station makes its own certificate with the Hub's existing `pairing.make_cert`.
  At every start it tells the Hub `fp`, `port` and `version` on `GET /api/station/hello`, over the connection it already
  has; the Hub then calls it over HTTPS at that port, accepts only that certificate and does not fall back to plain
  HTTP. A station that has not been updated sends no fingerprint and is called over plain HTTP as before; so is a
  station that cannot make its certificate, which serves plain HTTP as before and logs why; the Checks show a row for
  either. The Hub never goes back to plain HTTP for a station whose certificate it has pinned: for such a station a
  missing or changed certificate is an error row, never a reason to downgrade. The printer-side tag service is pinned
  the first time the Hub reads its address (trust on first use). A Label Reader on another machine is the exception
  until its own software can serve HTTPS: an `http://` address of it is accepted and used as today, an `https://`
  address is pinned at Test, and the Checks show one Note row, "The Label Reader at <address> is not using HTTPS. A
  later Label Reader version adds it.", with no Fix line. From the release that turns the rule on (only together with a
  reader version that serves HTTPS; it is not a setting), saving an `http://` address that is not 127.0.0.1 is refused
  with "A Label Reader on another machine needs an https address."; a stored one keeps working and its row becomes Needs
  a look: "The Label Reader at <address> is not using HTTPS." with the Fix "Update the Label Reader on that machine,
  then change its address to https:// in Settings > Label Reader." Spoolman is not ours: its page stays
  `http://<host>:7912`. Nothing listens on port 80, so a bare name typed without `https://` shows nothing.
- **Existing satellites keep their ports** (5003 for the Weigh Station, 5002 for the printer-side tag service) and switch
  to HTTPS on update; only new installs take 443. "The printer station" in the code is that tag service, because the
  Printer Station / Tag Reader device itself listens on nothing.
- **Typed addresses.** The Android app's manual entry and Slicer Sync's bare host try 443 first and 8710 second and keep
  the one that answered with the fingerprint of the pairing; a typed port is used as typed. Port 443 counts only when a
  Hub answers `api/info` there: another web server on 443 is not a Hub, and 8710 is tried.
- **Guided Setup is the installer's first question** and its default answer is Yes; after Yes the installer asks nothing
  more. The Hub page's Getting started panel is that setup, and an updated Hub starts with it hidden.
- **Texts.** The installer's sentences stay literals in `install/install.sh` and `apply.py`, as all its texts are. Every
  other new text goes into the string catalogue in ONE step (AF5); the client steps name their keys to it and add none
  themselves.
- **What this stage does not change:** existing Hubs' ports; the `/setup` address, kept beside the base address; the setup
  code and how it is shown; the installer's questions on its No path; pairing; the phone web app; the Tag Reader
  firmware; Spoolman's port.

### Which files the stage shares with Stage 10

The events and alerts steps open, among others: `config.py`, `__main__.py`, `inventory.py`, `storage.py`, `backup.py`,
`api.py`, `cli.py`, `status.py`, the string catalogue and its copies, `setup_page.py`, `setup_console/overview.py`,
`setup_static/setup.js`, `setup_overview.js`, `setup_settings.js`, `shared_static/components.*`, the web app's `app.js`,
`printers.js`, `sw.js`, Android's manifest, `NoticeCard.kt`, `HomeScreen.kt`, the Spools and Settings screens and the
API client. This stage avoids them where it can: the default stays in `config.py`, the Getting started panel is its own
files, and the apps wait for a later stage.

**Seven of those files cannot be avoided**, because each is the one place where a command, a text, a page route or a
Checks row is registered: `cli.py`, `status.py`, `api.py`, the string catalogue, `setup_page.py`, `setup_overview.js` and
`setup_settings.js`. Each is opened by exactly one AF step, and that step starts only after the EA step that has the file
open is merged:

| Shared files | Opened by | Opened in Stage 10 by | Merge first |
|---|---|---|---|
| `cli.py`, `status.py`, `api.py` (only `station_hello`), the string catalogue and its copies | AF5 | EA3 | EA3 |
| `setup_page.py`, `setup_overview.js`, `setup_settings.js` | AF6 | EA6 | EA6 |

So the map has two parts.

**Part A: no file of Stage 10; can start now, beside it.**

### AF0 Design text
Design + docs · Depends on: none · Beside: AF1, AF7, AF8
- **Files today:** `docs/design/*.md`, stacked on the events and alerts text.
- **Change:** the design of this stage: 03 (4 Overview, 5.6 the add drawer, 7.3, 9 Features, 10.5, 10.7, 10.11, 15 routes),
  06 (the installer, `port`, `status`, `printer add`), 09 (this stage), 02 (the panel), and the container-query text
  that was owed (01 section 7, 08 section 7).
- **Keep:** every other part.
- **Other interfaces:** AF1 to AF9 read it.
- **Check:** the design's own tests; every `8710` that states a default is gone from the documents.

### AF1 Hub: installer and port
Server builder · Depends on: none · Beside: AF0, AF7, AF8
- **Files today:** new `server/filament_kit/hubport.py`, new `server/filament_kit/firstrun.py`, `install/install.sh`,
  `server/filament_kit/apply.py`, `server/filament_kit/modules.py`, `server/filament_kit/setup_code.py` (the address
  line), `install/avahi/filament-kit.service` if its template must change, `tools/e2e/e2e.py`, `tools/e2e/run.sh`, new
  tests and the installer's tests.
- **Change:** 06 9.20 and 9.19: the first question, detect and offer, the port written at first install, the capability
  drop-ins for the Hub and the station units, the station's port question, the closing lines, the address without a port,
  the first-run file `firstrun.xml` and its rules (what is done, hidden, finished; written by the installer as root and by
  the Hub process, never through the root helper), the port-change function, and the refusal of Remote access on 443.
- **Keep:** `config.py`; the unit files; the installer's questions on its No path.
- **Other interfaces:** AF2 reads `hubport.py` (the free-port test, the drop-in); AF5 and AF6 read `firstrun.py` and the
  port-change function.
- **Check:** prove first (items 1 and 2 of the list below). Then the installer's tests; the tests that name 8710 and
  assert a default are changed to the new rule (which of them do was not read).

### AF2 Hub: HTTPS on the satellites
Server builder · Depends on: AF1's `hubport` (free-port test, drop-in)
- **Files today:** `server/filament_kit/station/__main__.py`, `station/http.py`, `station/state.py`,
  `station/server_api.py`, `station/pair_request.py`, `server/filament_kit/station_client.py`,
  `server/filament_kit/pairing.py` (the three values kept with a station's pairing), `server/filament_kit/tagsources.py`,
  `server/filament_kit/local_reader.py`, `printer-pack/lasttag/*`, new tests.
- **Change:** the station's certificate and HTTPS listener, the three values on its hello call, the Hub's pinned calls
  to a station, the tag service's HTTPS and its pin on first use, the pin of a remote reader's `https://` address at
  Test and its Checks rows (03 10.5). The reader's own side (a certificate at the remote install, HTTPS on port 7915) is
  a request to the reader's repository; until it ships, the Hub accepts the reader's `http://` address as before and
  shows the Note row. The refusal of such an address comes with the release that has a reader version that serves HTTPS.
- **Keep:** the allow-list of caller addresses; `http://127.0.0.1:5003` for a station on the Hub's own machine.
- **Other interfaces:** AF5 words the rows this step makes possible.
- **Check:** prove first (items 5 and 6 of the list below). Then the tests of each listener and of the pin.

### AF7 Android: a typed address without a port
App builder · Depends on: none · Beside: AF0, AF1, AF8
- **Files today:** `android/.../ui/pair/PairViewModel.kt`, its tests (`PairViewModelTest`, `PairScreensTest`).
- **Change:** 05 4.5: the Port field starts empty with a hint; an address typed without a port tries 443, then 8710,
  and 443 counts only when a Hub answers `api/info` there.
- **Keep:** scanned links and discovery, which already carry the port.
- **Other interfaces:** none.
- **Check:** the two test classes; prove first (item 3 of the list below).

### AF8 Slicer Sync: a bare host
Klipper builder · Depends on: none · Beside: AF0, AF1, AF7
- **Files today:** `pc-sync/fksync/client.py`, `pc-sync/fksync/__main__.py`, `pc-sync/tests/test_client.py`.
- **Change:** a bare host tries 443, then 8710, and keeps the one that answered with the fingerprint of the pairing.
- **Keep:** a typed port, used as typed.
- **Other interfaces:** none.
- **Check:** `pc-sync/tests/test_client.py`; prove first (item 3 of the list below).

**Part B: opens a file that a Stage 10 step also opens; starts after that step is merged.**

### AF5 Hub: command line, Checks rows, hello values and the texts
Server builder · Depends on: AF1, AF2; EA3 merged (it has `api.py`, `cli.py`, `status.py` and the catalogue)
- **Files today:** `server/filament_kit/cli.py`, `server/filament_kit/klipper_cli.py`, `server/filament_kit/status.py`,
  `server/filament_kit/api.py` (only `station_hello`), `strings/en.json` and its generated copies, tests.
- **Change:** `spoolwarden port`, the Getting started block and `getting_started` in `status`, `printer add` in the guided
  order with the test, the `Next:` line after switching the Label Reader on, the rows of 03 4.2 (the satellites and the
  reader), the three values on the hello route, and ALL catalogue texts of this stage.
- **Keep:** the other routes and commands.
- **Other interfaces:** AF3, AF4 and AF6 name the keys they need to this step before it is filed.
- **Check:** the command tests; the route tests; the catalogue and wording tests (08 test 7).

### AF3 Hub page: the guided add drawer
Bug-bash 1 · Depends on: AF5 (texts) · Beside: AF4
- **Files today:** `setup_static/setup_printers.js`, `setup_static/setup_printers_add.css`,
  `setup_console/printers_tab.py`, `server/tests/test_hub_printers.py`.
- **Change:** 03 5.6: the guided add drawer and the Klipper test before saving.
- **Keep:** the printer rows and their other dialogs.
- **Other interfaces:** none.
- **Check:** prove first (item 4 of the list below). Then the drawer's browser tests and AUT-5 on it.

### AF4 Hub page: the Label Reader lead-in
Bug-bash 1 · Depends on: AF5 (texts) · Beside: AF3
- **Files today:** `setup_static/setup_features.js`, `setup_static/setup_features.css`.
- **Change:** 03 9.4 and 9.5: the line in the preview drawer, the arrival in Settings, the row's "Not installed yet".
- **Keep:** the other features' rows and drawers.
- **Other interfaces:** none.
- **Check:** the feature's browser tests; a failed job changes nothing.

### AF6 Hub page: Getting started, the Hub port, the arrival state
Bug-bash 1 · Depends on: AF1, AF5; EA6 merged (it has `setup_page.py`, `setup_overview.js`, `setup_settings.js`)
- **Files today:** new `setup_static/setup_start.js`, new `setup_static/setup_start.css`, new
  `setup_console/start_tab.py`, `server/filament_kit/setup_page.py`, `setup_static/setup_overview.js`,
  `setup_static/setup_settings.js` and its CSS, `server/filament_kit/setup_helper.py` (the port change as a root job),
  `setup_console/general_tab.py` (the port in the group's answer).
- **Change:** 03 4.2 and 15: the Getting started panel and its routes, the Overview's mount, Label Reader tile and banner;
  10.7 and 10.11: Settings > Network "Hub port" with its job; 10.5: the Label Reader group's arrival state.
- **Keep:** `shared_static/components.js` and `.css`, which the panel is built from as they are (EA5 has them).
- **Other interfaces:** none.
- **Check:** AUT-5 on Overview with the panel in each state; the unsaved-changes guard; the port change run on a real
  systemd.

### AF9 Documents
Design + docs · Depends on: AF1 to AF8 merged; after EA9 if that is open then
- **Files today:** `docs/*.md`, `README.md`, `release-notes/next.md`.
- **Change:** the install guide (the first question, the port, the address without a port), the user guide, the app
  documents' pairing parts, the release notes.
- **Keep:** the wording of the other sections.
- **Other interfaces:** none.
- **Check:** the documents tests; the words lint.

**Order.** AF0, AF1, AF7 and AF8 now. AF2 when AF1's `hubport.py` is filed (it can stack on AF1). AF5 after AF1, AF2 and
EA3's merge. AF3 and AF4 after AF5. AF6 after AF5 and EA6's merge. AF9 last. No file is opened by two AF steps: a step
that finds it needs another step's file stops and says so. The panel is built from the shared components as they are; it
adds nothing to `shared_static/components.js` or `.css`.

**How far the map is checked.** It is built from reads of the code and of the registry places, not from opening every
file. Not looked at: the exact test files that pin the installer's lines and 8710 (23 server test files and 7 Android
test files name 8710; which of them assert a default and must change was not read), whether `setup_code.py:333` is the
only place that builds the page address, the CSS a Network row needs, and the installer of `printer-pack/lasttag`.

**Later work, so that no file is opened twice for the same reason.** A later stage opens the web app's and the Android
app's printer and home screens once for the guided order, the one-line Getting started summary, the slot features and the
satellites' version prompt (it reads the `version` AF2 stores); the satellites' own web pages are served by the HTTPS
listeners AF2 builds.

### To prove first, in the step that meets it

Each has a fallback.

1. **AF1: the capability drop-in.** Assumed: `AmbientCapabilities=CAP_NET_BIND_SERVICE` with the same bounding set lets
   the unit bind 443 while `NoNewPrivileges=yes` and the rest of its hardening stay. Proved by the upgrade and install
   runs on a real systemd. Fallback: systemd socket activation for the Hub's listener.
2. **AF1: "taken" is detected the same way for every case** (another web server, the Hub's own nginx, an IPv6-only
   listener). Fallback: the question is asked whenever the test is unsure.
3. **AF1 with AF7 and AF8: paired phones and the PC find a Hub whose port changed.** Assumed from the app browsing the
   network for the Hub (`Discovery.kt:121`); not read further. If they do not, the sentence "Pair your phones and the
   Slicer Sync PC again." replaces the first sentence of the port-change message in 06 9.19 and 03 10.11, and nothing
   else changes.
4. **AF3: found Bambu Lab printers.** Assumed: the Hub's announcement listener (`bridge/discovery.py`) is running in the
   Hub and can give the page a list. If not, the found list is Klipper only.
5. **AF2: the printer-side host can make a certificate and serve HTTPS** with what a Klipper host has installed.
   Fallback: the tag service stays on plain HTTP on that host and the Checks row says so; the owner is told in the release
   notes.
6. **AF2: the remote Label Reader's HTTPS** needs its own repository's change first. Until then the Hub accepts its
   `http://` address as today and shows the Note "The Label Reader at <address> is not using HTTPS. A later Label Reader
   version adds it."

**Out of scope:** a listener on port 80; Spoolman over HTTPS; a real (publicly trusted) certificate for the home address;
the satellites' own web pages, their version prompt and a regular check-in (only the stored `version` is added here); the
guided printer and the Getting started line in the web app and the Android app; loading a spool from the Hub page;
anything on the Tag Reader firmware.

---

## 19. Stage 12: Every function in every version

Every function that one interface has, the others have where they can: the Hub page gets the Spools section and the live
printer view, every interface gets Clear slot and the waiting state, the Filament Catalog has one form everywhere, the
apps show the Hub at a glance, a spool can be assigned to a printer with no slot named (Auto: the Hub loads it into the
slot that gets a spool next), the web app and the app add a printer in the guided order, Spoolman and the Hub page link
to each other, Devices shows kinds, versions and out-of-date devices with the Weigh Station's detail and a link to its
own page, and the command line gets the spool, slot, device and catalog commands. The parts that specify it are 01
section 8, 02 2.6 and 7.3 to 7.5, 03 3.2, 3.8, 4.2, 5, 7, 10.9 to 10.11, 15 and 16, 04 2, 5, 6, 8, 9, 12 and 14, 05 2,
5, 7 to 9, 12 and 16, and 06 3, 6.8, 7, 8.3, 9.2, 9.4, 9.11, 9.21 and 13. In this stage a "kit route" is a route under
`/api/` for paired devices (`api.py`), a "page route" is a route of the Hub page under `/setup/api/`, and a "twin" is
the web app's route under `/intake/api/` that passes a kit route on.

### The rules of the stage

- **All steps start at once**, each against the contracts below and in 03 section 15, 04 section 14, 05 section 16 and
  06 section 13. A registry file waits for the merge of the step named for it, and nothing else waits.
- **The page has its own routes.** The Hub page's live view, Spools section, catalog form and Devices call the same
  printer, inventory and catalog code as the kit routes, in the Hub's process. They do not call the web app's routes:
  the page's lock must apply, and the web app may be switched off.
- **No page of a device is passed through the Hub.** The Hub page draws a device's detail itself, in Devices at
  `#devices/<id>`, from `GET device/{id}` and `POST device/{id}/settings`; nothing a device sends is served by the Hub
  as HTML, script or style. What the Hub takes from a station is checked data: JSON only (`application/json`), at most
  256 KiB, a 5 second limit, any redirect an error, only to the stored host and port of that pairing, over the pinned
  certificate when the station has one; every text from a station is shown as text, never as markup; a setting's `id`
  must match `[a-z0-9_.-]{1,40}`, its `kind` is one of `switch`, `choice`, `number`, `text`, a `label` is at most 80
  characters, at most 60 settings, and anything else is dropped with the line "Some of this station's settings could not
  be shown."; the photo is taken only as `image/jpeg`, at most 4 MiB. The detail's link **Open this station's page**
  opens the station's own address in a new tab, never fetched, framed or proxied by the Hub, with a one-time ticket
  after `#` that the station's page trades for a session cookie of its own (03 7.10).
- **Clear slot is one rule in four interfaces.** The Hub forgets which spool is in the slot. In this order: a spool
  waiting for the slot is no longer waiting; a spool recorded in the slot goes back where it was before it was loaded
  (exactly as Unload moves it); on a Klipper printer the slot's setting on the printer is cleared when the printer is
  online and can do it; on a Bambu Lab printer what the printer shows for the slot is left as it is. There Clear slot's
  `printer_cleared` is always false, and its confirmation and its result both add "The printer still shows the old
  filament for this slot until a spool is loaded." Afterwards the slot has no spool, and filament used from it is logged
  with no spool and taken off none. Unload keeps its meaning, "I took this spool out", and now also ends a waiting
  assignment; it is offered only when a spool is recorded, and Clear slot is offered on every slot.
- **Auto is one rule in every interface.** It is an assignment of a spool to a PRINTER with no slot named. The Hub
  remembers how each slot of that printer looks at that moment, watches them, and when a spool appears in one, loads the
  scanned spool into that slot exactly as a named load would: same preset, same move, same answer.
  - *Which slots the Hub can watch.* Bambu Lab: every slot that has a filament sensor the printer reports, which are the
    slots of an AMS, an AMS 2 Pro and an AMS HT (`tray_exist_bits`, `tray_reading_bits`, `bridge/layout.py`); not the
    external spool holders (they have no sensor), and not the slots of a printer that reports no such bits (there the
    Hub sees only a slot's filament type, which does not change when a spool goes in). Klipper: the lanes or gates of a
    filament system that reports "loaded" per lane, which are AFC (Box Turtle included, `klipper/afc.py`) and Happy Hare
    (`klipper/happyhare.py`); not a single extruder and not a toolchanger (no sensor per tool is read). **Auto is
    offered for a printer with two or more watchable slots.** With fewer there is nothing to choose between, and a
    printer with one source keeps today's behaviour.
  - *A spool shows up in a slot* when the slot is seen empty and then loaded: empty at the start and now loaded, or
    loaded at the start, then seen empty, then loaded again (a spool swapped in a full slot). "Loaded" is what the
    waiting assignment already uses: present and no longer being read, steady for 3 seconds (`pending.py`). A slot that
    was loaded at the start and never changes is never chosen, whatever is recorded for it. A slot whose own tag names
    its spool (a Bambu Lab spool with RFID) is not chosen, as today, and Auto goes on waiting for another slot. The slot
    that feeds a running print is not chosen (it cannot be loaded). If the chosen slot has a spool recorded, that spool
    goes back where it was, as every load does.
  - *One at a time, and never a guess.* A printer has at most one Auto assignment; a new one for the same printer
    replaces the old one, and the answer says so: "Replaces {spool}, which was waiting." If a second watchable slot
    shows up before the first one is applied (within its 3 seconds), the Hub does not pick: the assignment stays in the
    state "choose", and the printer shows "Two slots were loaded. Which one got {spool}?" with those slots as buttons,
    in every interface that shows the printer. Choosing loads it there.
  - *How it ends.* When no slot changes it waits 15 minutes (the waiting assignment's time) and ends without a trace
    other than the notice disappearing. It also ends when someone presses **Stop waiting**, when the same spool is
    loaded into a named slot anywhere, when a new Auto replaces it, when the printer is removed and when the Hub
    restarts (it is kept in memory, like the waiting assignment). While it waits, the printer shows one notice in every
    interface: "Waiting for {spool} to be loaded into any slot of {printer}." with **Stop waiting**.
  - *A Klipper printer that is printing* refuses a load (`klipper/loads.py`): the slot is still noticed, and the load is
    sent when the printer allows it; if the 15 minutes pass first, it ends with the Hub's reason.
  - *Where it is offered, and where it is the default.* The Printer Station's slot list comes from the Hub
    (`web/reader.py`), so on a printer where Auto is possible the list gains a first entry "Auto". It is the default
    wherever the device takes the first entry today: when a printer is picked and when a saved slot no longer exists.
    A device that has a slot saved keeps it until its owner turns the knob. The scan's answer is the waiting one the
    device already shows, with the text "Auto: load any slot (waits 15 min)". In the web app the spool sheet's "Load
    into a printer" gets "Automatic" as the first and preselected choice of its slot step when the printer can do it,
    and the printer page gets **Load a spool** in its header (spool first, then Automatic or a slot) beside the
    per-slot Load buttons. The app's Load screen gets "Automatic" first and preselected in its slot step. The Hub
    page's live printer view gets **Load a spool** in the printer's header, the same way. The command line has
    `spoolwarden printer load <name> auto <spool number>`. A person who wants a certain slot picks it as today: Auto
    is one tap less, not a replacement.
- **One function builds a catalog entry.** The Hub builds an owner's own entry from the form's values; the page, the
  apps and the command line send values and never an entry's text. The Catalog token field leaves the Hub page and the
  `config` menu; a stored token keeps working and is not deleted by an update, and `spoolwarden catalog token` stays.
- **Every client sends its kind and version.** The Hub keeps the newest value with the pairing; a device that sends
  nothing shows "Version not known" and is never called out of date.
- **Texts.** Only EV2 opens the string catalogue. Every other step sends EV2 its keys and English texts before it files;
  until EV2 is merged a step shows its own English text through the catalogue's fallback and adds no key itself. The
  texts of Auto are AS2's: AS1, AS3, AS4 and AS5 send AS2 their keys the same way.
- **No file is opened by two EV steps.** A step that finds it needs another step's file stops and says so. The same
  holds for the AS steps at the end of the stage.

### The contracts

All JSON. Times are ISO 8601 with offset; a day (an own catalog entry's `added`) is `YYYY-MM-DD`, with no time and no
offset. A field marked `?` may be absent or null. Errors keep each route family's
existing shape.

**Kit routes (new or changed).**

| Route | Body / query | Answer |
|---|---|---|
| `POST /api/printers/{id}/slots/{label}/clear` | `{dry_run: true}` (default true) | `{slot: <label>, spool: <spool view>?, moved_back: <location>?, waiting_ended: bool, printer_cleared: bool, dry_run: bool}` |
| `PATCH /api/spools/{id}` (changed) | one kind of change per call: `gross`, `remaining`, `location`, `empty`, or new `{"auto_location": true, "dry_run": ...}` | as today; for `auto_location` the Hub moves the spool where its placement rule puts it |
| `POST /api/printers/{id}/slots/{label}/unload` (changed) | as today | as today plus `waiting_ended: bool` |
| `POST /api/printers/{id}/slots/{label}/load` (unchanged) | | already answers `pending: true` for a waiting load; clients must read it |
| `GET /api/printers`, `GET /api/printers/{id}` (changed) | - | the printer gains `auto_possible: bool`; each slot gains `watchable: bool`; `GET /api/printers/{id}` also gains `auto: {spool_id, spool: {id, name, material, color_hex}, state: "waiting"\|"choose", slots?: [<labels to choose from>], text, expires_at}?` |
| `POST /api/printers/{id}/slots/auto/load` (new) | `{spool_id, dry_run}` (default true) | dry run: `{auto: true, watching: [<labels>], replaces?: {spool_id, name}, dry_run: true}`; real: `{auto: true, pending: true, confirmed: null, expires_in: 900, message}`; 409 `{error: "auto_not_possible", text}` |
| `POST /api/printers/{id}/auto/choose` (new) | `{slot: <label>}` | the answer of a named load into that slot; 409 `{error: "nothing_to_choose", text}` |
| `POST /api/printers/{id}/auto/cancel` (new) | - | `{cancelled: true}`; 409 `{error: "not_waiting", text}` |
| `GET /reader/printers/{id}/slots` (changed) | - | first entry `{label: "auto", ...}` named "Auto" when `auto_possible` |
| `POST /reader/scan` (changed) | `slot: "auto"` | `status: "queued"`, `slot: "auto"`, `message: "Auto: load any slot (waits 15 min)"` |
| `GET /api/hub` | - | the object below |
| `GET /api/library/local` | - | `{entries: [{id, brand, name, material, added}]}` |
| `POST /api/library/local/form` | `{brand, name, material, nozzle_min?, nozzle_max?, bed_min?, bed_max?, density?, max_volumetric_speed?, bambu_parent?, notes?}` | 201 `{entry: {id, brand, name, material, added}}`; 400 `{error: "invalid_entry", problems: [{field, text}]}` |
| `DELETE /api/library/local/{id}` | - | `{removed: true}`; 404 when unknown |
| `POST /api/library/local` (unchanged) | an entry's text | kept for the command line's file form |
| `GET /api/spools` (changed) | adds `filter=sealed\|opened\|loaded\|low` (one value; absent = all not empty) | each spool also carries `view` (the spool view); the answer adds `spoolman_url` |
| `POST /api/readers/web/seen` (new; a web token only) | `{readers: [{id, build?, seen_at}]}` | `{ok: true}`; the Hub keeps the newest values with the reader's entry |
| every kit route | header `X-Spoolwarden-Client: <kind>/<version>` | recorded with the pairing; never required |

`GET /api/hub`: `{name, version, newest: {version, checked_at}?, update_available: bool, checks: [{group, state: "ok" |
"look" | "note" | "off", text, fix?}], getting_started: {done, total, hidden, finished}, features: [{id, name, on}],
catalog: {version?, checked_at?}, backup: {last_at?, nightly: bool}, reader: {engine, key_set: bool}, devices: [{name,
kind, version?, last_seen?, out_of_date: bool, this: bool}], records_kept: <number>, spoolman_url: <string>?,
hub_page: <string>?}`. `getting_started` is the counts of 03 4.2. `hub_page` and `spoolman_url` are built from the host
the caller used and are absent where the thing cannot be reached.

The spool view is `inventory.spool_view` as it is, `{id, location, remaining_g, net_g, tare_g, tag, state: "sealed" |
"opened" | "empty", filament_id, vendor, name, material, color_hex, lot}`, plus two new fields: `loaded: {printer_id,
printer, slot}?` and `low: bool`. What a web token may call gains exactly: `POST /api/printers/{id}/slots/{label}/clear`,
`POST /api/printers/scan`, `GET /api/hub`, `GET /api/library/local`, `POST /api/library/local/form`,
`DELETE /api/library/local/{id}`, `POST /api/readers/web/seen`, `POST /api/printers/{id}/slots/auto/load`,
`POST /api/printers/{id}/auto/choose` and `POST /api/printers/{id}/auto/cancel`; only a web token may call
`/api/readers/web/seen`.

`auto` is a reserved slot label (compared without regard to case): no real slot may carry it. The loaded spool's event
(`spool.loaded`) carries `auto: yes` in its data when an Auto assignment made the load; there is no new event kind. The
texts of Auto, as the Hub and the interfaces show them: "Waiting for {spool} to be loaded into any slot of {printer}." ·
"Stop waiting" · "Two slots were loaded. Which one got {spool}?" · "Replaces {spool}, which was waiting." · "Automatic"
with the hint "The slot where the spool appears." · the refusal "This printer has no slots the Hub can watch. Choose a
slot." · "Auto: load any slot (waits 15 min)".

**Client headers.** Every client of ours sends `X-Spoolwarden-Client: <kind>/<version>` on every call, with the kind
`android`, `slicer-sync`, `weigh-station` or `web`. A Weigh Station also gives its version on its hello call. A Tag
Reader sends `X-Reader-Build: <number>` with its token to the web unit, and the web unit hands the build and the time of
the reader's last call to the Hub with `POST /api/readers/web/seen`; the Hub keeps the newest values with the reader's
entry. The web unit sends a reader's values when its build changes and otherwise at most once a minute per reader; while
the Hub does not answer it keeps only the newest value per reader in memory.

**Page routes.** Under `/setup/api/`: the rows of 03 section 15 for the Spools section, the live view, the catalog form,
Devices. Their answers are the kit routes' answers; the lock of each is in 03 5.10, 7.10, 10.9 and 16. The live view's
page routes for Auto are `POST printers/{id}/slots/auto/load`, `POST printers/{id}/auto/choose` and `POST
printers/{id}/auto/cancel`; they need the page unlocked, like every slot action there. The routes of a device's
detail: `GET device/{id}` (open) answers `{device, status?, settings?, own_page: <address as text>?, photo:
bool}`; `GET device/{id}/photo` (open) answers `image/jpeg`; `POST device/{id}/settings` needs the page unlocked; `POST
device/{id}/open` needs the page unlocked, makes the Hub ask the station for a one-time ticket and answers `{address:
"<own_page>#ticket=<ticket>"}`. The live view's camera has one more: `POST printers/{id}/camera/ticket` with the setup
code, answering `{ticket, expires_in: 60}`; on a computer that is not trusted the first camera request (the stream, or
the playlist) takes `?ticket=<ticket>`, spends the ticket within 60 seconds and gets a cookie, named `fk_setup_camera`, that is the camera
session: valid only for that printer's camera routes (`/setup/api/printers/<id>/camera`), HttpOnly, Secure and
SameSite=Strict, naming a session the Hub keeps in memory for that printer for 10 minutes, moved forward by every
camera request that carries it (a Bambu Lab printer with an RTSP camera is served as a playlist with many segment
requests; a Bambu Lab P1 or A1 and every Klipper camera are one stream; the rule is the same for both). The cookie lets
its holder do nothing but ask that camera. The session ends at `POST printers/{id}/camera/close` (needs only the cookie;
answers `{closed: true}`), after 10 minutes with no camera request, when the Hub restarts and when the printer is
removed. Locking the page again does not cut a running picture; the next Show camera needs the code again. At most 8
camera sessions run at a time: the ninth ticket is refused with "Too many camera views are open. Close one first." A
trusted computer needs no ticket.

**Twins** (under `/intake/api/`; EV6a and EV6b): `GET hub` (the kit object), `GET library/local`, `POST library/local`
(the form), `POST library/local/{id}/remove`, `POST printers/scan`, `POST printers/{id}/slots/{label}/clear`, and for
Auto `POST printers/{id}/slots/auto/load`, `POST printers/{id}/auto/choose` and `POST printers/{id}/auto/cancel`. Each
passes the kit route on unchanged, with the guards the neighbouring twins have.

**The Weigh Station's own routes** (over its HTTPS listener; EV3):

| Route | Answer |
|---|---|
| `GET /` | its page (HTML; its own script and stylesheet under `/static/`), served to any address on the home network; without a ticket or a session it says only "Open this page from the Hub: Devices, this station, Open this station's page." |
| `GET /state` (changed) | as today plus `version` (the station software) and `settings_changed: bool` |
| `GET /settings` | `{settings: [{id, label, kind, value, choices?, min?, max?}]}` with the ids `beep`, `speech`, `voice`, `volume`, `panel_swap`, and one `lamp.<step>` per step of the intake flow (value: one of the panel's lamps, or `off`) |
| `POST /settings` | body `{<id>: <value>}`, with the header that carries the proof of 03 7.10 or with a session; answers the new list; `{reset: true}` removes the station's own values |
| `POST /ticket` | the Hub's proof; answers `{ticket, expires_in: 60}`: a ticket works once, within 60 seconds |
| `POST /session` | body `{ticket}`; sets the station's session cookie, on its own origin, for 60 minutes; answers `{ok: true}` |

The station's data routes (`/state`, `/settings`, `/photo`, `/last-tag`) answer only its allow-list or a browser with a
session; its page's own files (HTML, script, stylesheet) are served to any address on the home network.

The station's 5-minute check-in is `GET /api/station/hello` with `fp`, `port` and `version`: nothing new.

**The command line** (EV2): `spoolwarden spools [<words>] [--sealed|--opened|--loaded|--low]`; `spoolwarden spool show
<n>`; `spoolwarden spool weigh <n> <grams with the spool>`; `spoolwarden spool move <n> <location|auto>`; `spoolwarden
spool empty <n>`; `spoolwarden printer show <name> --watch`; `spoolwarden printer load <name> <slot> <spool n>` (and
`auto` in place of the slot, which is AS2's); `spoolwarden printer unload <name> <slot>`; `spoolwarden printer clear
<name> <slot>`; `spoolwarden printer usage <name> [--days n]`; `spoolwarden catalog add --ask`; `spoolwarden catalog
local`; `spoolwarden catalog local remove <id>`; `spoolwarden devices show <device>`; `spoolwarden devices set <device>
<setting> <value>`. Every changing command previews, asks, and takes `-y`; every one has `--json` with the object of its
route.

### Which files the stage shares with the stages before it

Each registry file below is opened by exactly one EV step, and that step starts only after the step that has the file
open is merged. A step whose only wait is a registry file builds everything else first and adds its registry lines last.

| Registry file | Opened by | Opened before by | Merge first |
|---|---|---|---|
| `api.py` | EV1 | EA3, then AF5 | AF5 |
| `cli.py`, `status.py`, the string catalogue and its copies | EV2 | EA3, then AF5 | AF5 |
| `setup_page.py`, `setup_static/setup_overview.js` | EV5 | EA6, then AF6 | AF6 |
| `setup_static/setup_settings.js` | EV4d | EA6, then AF6 | AF6 |
| `setup_static/setup.js` | EV5 | EA6 | EA6 |

The Auto steps at the end of the stage open `api.py` (AS1) after EV1 is merged, and `cli.py` and the string catalogue
(AS2) after EV2 is merged; no registry file is opened by two steps at once.

### EV0 Design text
Design + docs · Depends on: none · Beside: every other EV step
- **Files today:** `docs/design/*.md`.
- **Change:** the design text of this stage: 01 (eleven sections), 02, 03 (5, 7, 10.9, the Spools section 16, 15), 04, 05,
  06 and 09 (this stage).
- **Keep:** every other part.
- **Other interfaces:** every EV step reads it.
- **Check:** the design's own tests.

### EV1 Hub: the kit side
Server builder · Depends on: none · Beside: every other EV step except for its registry file
- **Files today:** `bridge/loading.py`, `bridge/pending.py`, `bridge/klipper/loads.py`, `inventory.py`, `library.py`,
  `profiles_api.py`, `pairing.py`, `reader_tokens.py`, `web/reader.py`, new `hub_view.py`, tests. Registry file: `api.py`,
  after AF5 is merged.
- **Change:** Clear slot and the changed Unload, `GET /api/hub`, the catalog form, list and remove, the spool view's two
  fields and `filter`, `auto_location` on `PATCH /api/spools/{id}`, kind and version per device, the reader's build and
  last seen (`POST /api/readers/web/seen`), what a web token may call, the camera source handed to the page.
- **Other interfaces:** every other EV step builds against these routes with stubs.
- **Check:** prove first (item 1 of the list below). Then the route and inventory tests.

### EV2 Hub: the command line, the Devices check and the texts
Server builder · Depends on: none · Beside: every other EV step except for its registry files
- **Files today:** new `spools_cli.py`, `klipper_cli.py`, tests. Registry files: `cli.py`, `status.py` and the string
  catalogue, after AF5 is merged.
- **Change:** the command line above, the Devices Checks row ("<n> devices are out of date."), and ALL catalogue texts of
  this stage.
- **Other interfaces:** every other EV step names its keys to this one before it files.
- **Check:** the command tests; the catalogue and wording tests (08 test 7).

### EV3 Hub: the Weigh Station's page
Server builder · Depends on: none · Beside: every other EV step
- **Starts after:** AF2 is merged, for the station files.
- **Files today:** `station/http.py`, `station/state.py`, `station/flow.py`, `station/panel.py`, `station/server_api.py`,
  new `station/page.py`, new `station/settings.py`, new `station/static/*`, `station_client.py`, tests.
- **Change:** the station's page, its settings file, the lamp mapping, the 5-minute check-in, `version` in `/state`,
  `POST /ticket` and `POST /session`, who its page files and data routes answer, and the Hub's client for the station's
  checked data.
- **Other interfaces:** EV4c reads the Hub's client.
- **Check:** prove first (item 2 of the list below).

### EV4a Hub page: the Spools section
Bug-bash 1 · Depends on: none · Beside: every other EV step
- **Files today:** new `setup_console/spools_tab.py`, new `setup_static/setup_spools.js`, new
  `setup_static/setup_spools.css`.
- **Change:** 03 section 16.
- **Other interfaces:** EV5 mounts it.

### EV4b Hub page: the live printer view
Bug-bash 1 · Depends on: none · Beside: every other EV step
- **Starts after:** AF3 is merged, for `setup_printers.js`.
- **Files today:** new `setup_console/printer_live_tab.py`, new `setup_static/setup_printer_live.js` and `.css`,
  `setup_static/setup_printers.js`, `setup_static/setup_printers.css`.
- **Change:** 03 5.10: the live view, the slot actions, waiting in the slot strip, the camera's ticket (asked before the
  first camera request and put on that address only) and the camera's close call.
- **Other interfaces:** EV5 mounts it.

### EV4c Hub page: Devices
Bug-bash 1 · Depends on: none · Beside: every other EV step
- **Files today:** `setup_static/setup_devices.js`, new `setup_console/device_tab.py`, `setup_console/station_tab.py`,
  `setup_console/webapp_tab.py` (the Open button's address).
- **Change:** 03 7.2, 7.4, 7.9 and 7.10: kind, version, out of date, Open, the device detail drawn by the Hub with its
  checks, its photo, and the link to the station's own page with its ticket.
- **Other interfaces:** reads EV3's client; EV5 mounts the routes of the detail.
- **Check:** the detail's tests: what a station sends that fails the checks is dropped or shown as text.

### EV4d Hub page: the catalog form
Bug-bash 1 · Depends on: none · Beside: every other EV step except for its registry file
- **Files today:** `setup_console/library_tab.py`, `setup_helper.py` (the token operations leave the page). Registry file:
  `setup_static/setup_settings.js`, after AF6 is merged.
- **Change:** 03 10.9 to 10.11: the form, the list, no token field.

### EV5 Hub page: the registry
Bug-bash 1 · Depends on: none · The last of the Hub page steps
- **Files today:** registry files only: `setup_page.py`, `setup_static/setup.js`, `setup_static/setup_overview.js`;
  `setup_page.py` and `setup_overview.js` after AF6 is merged, `setup.js` after EA6.
- **Change:** the Spools section in the navigation, the header's "Open the web app", the routes and scripts of EV4a to
  EV4d mounted, the Devices tile and the routes of the device detail.

### EV6a Web app: the Hub screen, links and the catalog form
Klipper builder · Depends on: none · Beside: every other EV step
- **Starts after:** EA7 and EA4 are merged: they have these files open in Stage 10.
- **Files today:** `web/static/app.js`, `web/static/app.css`, `web/intake_app.py`.
- **Change:** the Hub screen and the Getting started line in More, Open Spoolman, "Hub page" in the top bar, the catalog
  form and list under Slicer presets; their twins.

### EV6b Web app: guided add and Clear slot
Klipper builder · Depends on: none · Beside: every other EV step
- **Starts after:** EA7 and EA4 are merged.
- **Files today:** `web/static/printers.js`, `web/printers_app.py`.
- **Change:** the guided add, the search for Klipper printers, Clear slot and the waiting state; their twins.

### EV7a Android: the client and the Hub screen
App builder · Depends on: none · Beside: every other EV step
- **Starts after:** EA8 is merged: it has `Api.kt`, `Models.kt` and `MainActivity.kt` open in Stage 10.
- **Files today:** `net/Api.kt`, `net/Models.kt`, new `ui/hub/*`, `MainActivity.kt`, `nav/Destinations.kt`,
  `ui/settings/HubSettings.kt`, `ui/home/HomeScreen.kt`.
- **Change:** the client header, every new call and model of this stage, the Hub screen, the Getting started line and
  the entry points. Android has no shared registry with the server; `Api.kt`, `Models.kt` and `MainActivity.kt` are this
  step's alone, and it files the calls and models first as a row of their own so that EV7b stacks on it.

### EV7b Android: guided add, Clear slot, waiting and the catalog form
App builder · Depends on: EV7a's row of calls and models · Beside: every other EV step
- **Files today:** `ui/printers/PrintersScreen.kt`, `PrintersViewModel.kt`, `PrinterScreen.kt`, `PrinterViewModel.kt`,
  `ui/spool/LoadScreens.kt`, `LoadViewModel.kt`, `ui/search/SearchScreen.kt`, `ui/profile/AddProfileScreen.kt`,
  `AddProfileViewModel.kt`.
- **Change:** the guided add, Clear slot, waiting on the Load screen and the swatches of the printers list, Open
  Spoolman, the catalog form and list.
- **Check:** prove first (item 3 of the list below).

### EV8 Slicer Sync: the client header
Klipper builder · Depends on: AF8 merged · Beside: every other EV step
- **Files today:** `pc-sync/fksync/client.py`.
- **Change:** Slicer Sync sends `X-Spoolwarden-Client: slicer-sync/<version>`.

### EV9 Tag Reader firmware: the build
To be assigned · Depends on: none · Beside: every other EV step
- **Files today:** `reader/src/main.cpp`, `reader/firmware/VERSION` and what a firmware change needs.
- **Change:** the firmware sends its build as `X-Reader-Build`.
- **Check:** prove first (item 4 of the list below).

### EV10 Documents
Design + docs · Depends on: EV1 to EV9 merged
- **Files today:** `docs/*.md`, `README.md`, `release-notes/next.md`.
- **Change:** the user documents and the release notes.
- **Keep:** the wording of the other sections.

### Auto as the slot choice: AS0 to AS6

Each AS step waits only for the EV step that holds its files to be merged into `next`; no file is opened by two AS
steps. The texts of Auto are AS2's, as the rule on texts above says.

### AS0 Design text
Design + docs · Depends on: none · Beside: every other step
- **Files today:** `docs/design/*.md`.
- **Change:** the design text of Auto: 02 7.5, 03 5.10 and 7.5, 04 5.4, 6.2, 6.5 and 14, 05 7.6, 9.4, 9.5 and 16, 06
  3.2, 6.8, 7, 9.2, 12 and 13, and 09 (this stage).
- **Keep:** every other part.
- **Other interfaces:** every AS step reads it.
- **Check:** the design's own tests.

### AS1 Hub: the Auto assignment and the routes
Server builder · Depends on: none · Beside: every other AS step except for its registry file
- **Starts after:** EV1 is merged: it has `pending.py`, `web/reader.py` and `api.py` open.
- **Files today:** new `bridge/auto_slot.py`, `bridge/pending.py` (it ends when the spool is loaded elsewhere),
  `bridge/connection.py` and `bridge/klipper/manager.py` only where status is built, `web/reader.py`, `web/slots.py`,
  tests. Registry file: `api.py`.
- **Change:** the Auto assignment (a new module beside the waiting assignment), what is watchable, the three kit routes,
  the reader's list and scan, and the status fields `auto_possible`, `watchable` and `auto`.
- **Other interfaces:** every other AS step builds against these routes with stubs.
- **Check:** prove first (items 5 to 8 of the list below). Then the route, assignment and reader tests.

### AS2 Hub: the command line and the texts
Server builder · Depends on: none · Beside: every other AS step except for its registry files
- **Starts after:** EV2 is merged: it has `cli.py` and the string catalogue open.
- **Files today:** tests. Registry files: `cli.py` and the string catalogue.
- **Change:** `printer load ... auto`, and ALL catalogue texts of Auto.
- **Other interfaces:** every other AS step names its keys to this one before it files.
- **Check:** the command tests; the catalogue and wording tests (08 test 7).

### AS3 Web app: Automatic, Load a spool, the notice and the choice
Klipper builder · Depends on: none · Beside: every other AS step
- **Starts after:** EV6a and EV6b are merged: they have these files open.
- **Files today:** `web/static/app.js`, `web/static/printers.js`, `web/printers_app.py`.
- **Change:** Automatic in the spool sheet, Load a spool on the printer page, the notice, Stop waiting and the choice;
  their twins.

### AS4 Android: Automatic, the notice and the choice
App builder · Depends on: none · Beside: every other AS step
- **Starts after:** EV7a and EV7b are merged: they have these files open.
- **Files today:** `ui/spool/LoadScreens.kt`, `LoadViewModel.kt`, `ui/printers/PrinterScreen.kt`, `PrinterViewModel.kt`,
  `net/Api.kt`, `net/Models.kt`.
- **Change:** Automatic in the Load screen, the notice, Stop waiting and the choice.

### AS5 Hub page: Load a spool, the notice and the choice
Bug-bash 1 · Depends on: none · Beside: every other AS step
- **Starts after:** EV4b is merged: it has these files open.
- **Files today:** `setup_static/setup_printer_live.js`, `setup_console/printer_live_tab.py`.
- **Change:** Load a spool in the live view, the notice, Stop waiting and the choice.

### AS6 Documents
Design + docs · Depends on: AS1 to AS5 merged
- **Files today:** `docs/*.md`, `release-notes/next.md`.
- **Change:** the user documents and the release notes.
- **Keep:** the wording of the other sections.

**Later stages.** Stage 13's steps that open the same files (HD8, HD9 and HD7d) come after the AS step that holds them,
or before it, never beside it; the order is set by what is merged.

**Order.** EV0 to EV9 now. EV10 last, after the batch. AS0 now; AS1 to AS5 each after the EV step named above, beside
each other; AS6 last. Registry files, one after the other, per file: `api.py`: EA3 > AF5 > EV1 > AS1. `cli.py` and the
string catalogue: EA3 > AF5 > EV2 > AS2. `status.py`: EA3 > AF5 > EV2. `setup_page.py` and `setup_overview.js`: EA6 >
AF6 > EV5. `setup_settings.js`: EA6 > AF6 > EV4d. `setup.js`: EA6 > EV5.

**How far the map is checked.** It is built from four reads of the code, not from opening every file. Not looked at:
the CSS files the web app and Hub page steps need beyond those named; `PrinterScreen.kt` and `AddViewModel.kt` in full;
`station/PANEL.md` and how many lamps and steps the panel has; the firmware's build and release steps; whether the Android
Spools list has a menu today.

**Later work, so that no file is opened twice for the same reason.** Stage 13's undo, activity log and CSV open the
Spools section's files again for those functions, and a later stage translates these screens once.

### To prove first, in the step that meets it

Each has a fallback, except item 8, which only checks that nothing acts twice.

1. **EV1: an entry built from Brand, Name and Material alone passes the catalog's check and gives a usable preset.** The
   check wants `fields` (`library.py:83-88`); the Hub fills them from the catalog's values for that material. If no
   sensible values exist for a material ("Other"), the form asks nozzle and bed temperatures for it.
2. **EV3: a proof for setting changes.** Assumed: the station and the Hub can both derive a secret from the station's
   pairing without sending the token itself. If the Hub keeps nothing it can derive from, the station's pairing gains a
   second secret at its next hello, sent over the pinned channel.
3. **EV7b: the dashed ring** is drawable with the app's swatch component; else the waiting slot's swatch gets a small
   clock mark.
4. **EV9: a reader in the field takes the new firmware** only when its owner holds the knob; until then its build is
   "not known" and nothing breaks.
5. **AS1: what a Bambu Lab printer reports when a spool is pushed into an AMS slot** is as assumed: empty, then present
   and being read, then present. The order is not in the code; it is taken from a recorded printer report or a real
   printer before the rule of "a spool shows up" is fixed. If a slot never passes through "empty" when a spool is
   swapped quickly, a swap is not noticed and the text says "Take the old spool out first.". The sensor bits of AMS HT
   units beyond the first two are marked unverified in the Hub's hardware data: Auto watches only units whose bits are
   verified.
6. **AS1: the Printer Station needs no new firmware** (it shows the Hub's list and sends the chosen label back). If its
   screen cannot show the entry or the message, the firmware gets the change and devices in the field get Auto when
   their owners update them.
7. **AS1: a Klipper filament system's "loaded" change reaches the Hub in time** (within seconds). If a system only
   reports on request, the Hub asks every 2 seconds while an Auto waits.
8. **AS1: the reader's own queue** (`web/reader.py`) and the kit's waiting assignment do not both act on one scan.

**Out of scope:** adding spools on the Hub page; quick find and colour-name search (the Spoolman link is the answer); the
Hub updating a satellite by itself; pages for the Tag Reader and the printer-side tag service (they serve nothing a browser
can use; the reader has no web server); labels; a camera view on the command line. Undo, the activity log and CSV are
Stage 13.


---

## 20. Stage 13: History, data and safety, and Home Assistant

Every action leaves an event with who did it; a change to a spool or a slot can be put back; the checks have a history;
filament used is shown by the month; the Hub's data can be downloaded as CSV files and spools imported from one; backups
can be encrypted with the owner's password; one button collects a report for a problem; and Home Assistant can read the
Hub. The parts that specify it are 01 section 8, 02 7.11, 7.12 and 8.7, 03 2.9, 2.10, 3.2, 4.2, 5.10, 7, 10.6, 10.11, 13,
15, 16 and 17, 04 3.9, 5.4, 5.6, 6.5, 6.6, 7.1, 9.3 and 14, 05 3.1, 7, 9.10, 10.1, 12.8 and 16, 06 3, 6.8, 7, 9.1, 9.4,
9.10, 9.22 to 9.26 and 13, and 07 COL-9 and TIM-7. The words "kit route", "page route" and "twin" are used as Stage 12 uses
them. It reads the event store of Stage 10 as built: events with `id, at, kind, severity, actor, subject, data,
condition`, served with `title`, `text` and `action`, kept 400 days in month files and read with `GET /api/events`.

### The rules of the stage

- **All steps start at once**, each against the contracts below and in 03 section 15, 04 section 14, 05 section 16 and
  06 section 13. A registry file waits for the merge of the step named for it, and nothing else waits. New kit routes
  live in new modules that give their routes as a list; one step, HD1, mounts them in `api.py`, so `api.py` has one
  holder.
- **Every action leaves an event, with who did it.** The kinds, their data and the actor rule are in Stage 10's catalogue
  and event store. A data value is never a secret: a changed key says that it changed, never its value. A spool change
  carries complete before-values so that it can be put back.
- **Undo is one rule.** What can be undone: update weight, move, mark empty, link a tag, load, unload, clear a slot (the
  kinds `spool.weighed`, `spool.moved`, `spool.emptied`, `spool.opened`, `spool.loaded`, `spool.unloaded` and
  `slot.cleared`) and a filament-used entry (as before, Bambu Lab printers only). A Recently added revision keeps its own
  Undo. Nothing else: removing a printer, a key, a pairing or a location still asks first and has no undo. An event can
  be undone once, for 7 days (the limit the filament-used undo has), and only while nothing changed since: the spool's
  present values equal the event's after-values and no later undoable event exists for that spool or slot. Undo puts
  back exactly the before-values and writes a new event of the same kind with `undo_of`; the first event is then served
  with `undone: true`. Undoing a load or an unload puts the Hub's record back; the printer's own slot setting is not
  changed back, and the answer says so ("The printer still shows what it was set to."). The person sees a toast with
  **Undo** for 10 seconds; the toast stays until dismissed for a person who asked for no time limits (07 TIM-7).
- **Activity** is the events that are something done: every kind that Stage 10's catalogue marks Stage 13, the `spool.*` kinds except
  `spool.low` and `spool.ok`, `usage.recorded` and `location.renamed`. Conditions (offline, low, check rows) are health,
  not activity. It is kept as long as the store keeps events (400 days by default) and reading it needs nothing: it holds
  no addresses, serials or secrets.
- **Health history** comes from the conditions the store already records every 5 minutes: check rows (`check.failed` and
  `check.ok`), printers offline and online, devices down and up, storage low and ok. Nothing new is measured. History
  starts when the store started; before that the strip is empty and says "No history before <date>." The apps show the
  table only.
- **Analytics** is a twelfth section of the Hub page, last 12 months. The numbers come from the printers' filament-used
  logs, all printers, undone entries left out. The logs did not hold the material, the printer's name or whether the print
  finished, so each new entry of both printer families also stores `material`, `vendor`, `name`, `color_hex`,
  `printer_name` and `outcome` (`finished`, `failed`, `cancelled`, `unknown`). Older entries get the material from
  Spoolman while the spool still exists and "Unknown material" otherwise; a removed printer's older entries are "A
  removed printer". Entries the Hub logged without taking filament off a spool are counted and the page says so; entries
  without a weight are counted as prints and named. Klipper printers kept only their newest 2000 entries; the limit is
  raised so that 13 months are kept for any printer, by time and not by count.
- **CSV.** Spoolman's own export is passed on through the Hub, not rebuilt (`/api/v1/export/spools?fmt=csv` and
  `.../filaments?fmt=csv`). The Hub's own data is offered as `usage.csv`, `locations.csv`, `recent.csv`, `activity.csv`,
  `printers.csv` (no address, serial or code) and `lines.csv`. Import adds spools only, and adds and changes storage
  locations after a preview; it never removes anything. The file is UTF-8 with commas, a header row, ISO dates, numbers
  with a dot and grams without a unit; a cell that starts with `=`, `+`, `-` or `@` gets a leading `'`.
- **The backup password.** The owner sets it on the Hub page or with `sudo spoolwarden backup password` (typed twice, at
  least 10 characters). It is kept in `/etc/filament-kit/backup_password`, owned by root and readable by root only, as the
  setup code's file is. Both backup makers and the restore run as root, so the Hub's own process never needs the
  password and cannot read it. The file is left out of every backup: a backup must not carry its own key. From the
  moment it is set every backup is encrypted: the nightly one, **Back up now** and the copy made before a restore. A
  backup keeps its content (the zip, or the nightly archive) and is wrapped whole: a short header (a format mark, the
  salt and the cost of the key derivation), then the content in authenticated pieces (scrypt for the key, AES-256-GCM
  per piece with a counter, so a cut or swapped piece is noticed). The name ends in `.enc`. It is built with the
  `cryptography` library the Hub already has, and the nightly shell script calls the Hub's Python for it. New backups use
  a changed password and older files keep the one they were made with; removing it makes new backups plain again and
  leaves encrypted files as they are. Restore tries the stored password first; when it does not open the file the
  password is asked (the page: a field; the command line: a hidden prompt, or `--password-file`). A wrong password says
  "Wrong password, or the file is damaged. Nothing was changed." After a restore from an encrypted backup the password
  that opened it becomes the Hub's backup password if none is set. A download from the Hub page gives the encrypted file
  as it is, and the checks before a restore (the manifest, every file's hash) run on the opened content as before. The
  password can be shown again only with `sudo spoolwarden backup password --show`; the Hub page never shows it. A second
  place for backups is not part of this stage.
- **The Hub report** is one button, **Collect a Hub report** in Logs, and `sudo spoolwarden report`: one text file with the
  versions, the features on, the Checks rows with their fix lines, the printers (kind and model), the devices by kind,
  the storage use, the last update's log, the last 200 events and the last 500 lines of each service's log. Addresses,
  host names, serials, tokens, keys, codes, e-mail addresses and the user's folder name are replaced by placeholders with
  the rules the job log already uses (`redact.py`), and every printer's, device's, location's and the Hub's own name
  becomes `printer-1`, `device-2`, `location-3` and `hub`. The newest three reports are kept beside the backups.
- **Home Assistant** is a custom integration, domain `spoolwarden`, in a repository of its own (the form Home Assistant's
  community store needs). It talks only to the routes of the viewer role below, with a pairing made by **Link Home
  Assistant** or `sudo spoolwarden pair --home-assistant`, and pins the Hub's certificate by its fingerprint. It is read-only
  in its first version: it changes nothing on the Hub and controls no printer. It is found on the network by the Hub's
  advert (`_spoolwarden._tcp`) or by address; the person types the 6-digit pairing code and compares the fingerprint it
  shows. It gives Home Assistant: the Hub as a device (an update entity that only informs, a problem sensor that is on
  when a check needs a look with the rows as attributes, storage used in percent and free space, spools running low as a
  count with the list as attributes, filament used this month); each printer as a device (state, job, progress, minutes
  left, layer, a paused sensor, a problem sensor, nozzle and bed temperature, the camera where the printer has one, and per
  slot a sensor with the spool's name and grams left); and every alert of the Hub as a Home Assistant event
  `spoolwarden_alert` with the alert's key, title, text and subject, so an automation can act on "filament ran out". It
  reads with one long wait on `GET /api/events?wait=55` for changes, printers every 10 seconds while a print runs and every
  60 otherwise, and the Hub's summary every 5 minutes. No spool becomes an entity of its own. Translations, a logo and a
  place in the community store's default list come after its first working version.
- **Texts.** Only HD2 opens the string catalogue. Every other step sends HD2 its keys and English texts before it files.
- **No file is opened by two HD steps.** A step that finds it needs another step's file stops and says so.

### The contracts

All JSON. A field marked `?` may be absent. Times are ISO 8601 with offset.

**Events (changed; owner HD1).** `GET /api/events` gains the query values `activity=1` (only the kinds of the Activity
list), `subject=<type>:<id>` (for example `spool:212`) and `actor=<type>` or `actor=<type>:<id>`. Each served event
gains `undo: {possible: bool, until?: <time>, why_not?: "changed_since" | "too_old" | "already_undone" |
"not_undoable"}`, `undone: bool` and `undo_of?: <id>`. `POST /api/events/{id}/undo` answers 200 `{undone: true, event:
<the new event>, note?: <text>}`, 409 `{error: <one of the why_not values>, text}` or 404. A web token may call it. The
routes that make an undoable change (`PATCH /api/spools/{id}`, `POST /api/spools/{id}/link`, the slot `load`, `unload`
and `clear` routes, and their page routes and web twins) answer with `event_id: <id>` beside what they answer today,
absent on a dry run. A client uses it for the toast's Undo; where an answer has none, it asks the subject's newest
event.

**New kit routes.**

| Route | Query / body | Answer | Owner |
|---|---|---|---|
| `GET /api/health` | `days=7\|30` | `{from, to, since?: <when history starts>, checks: [{key, group, text, now: "ok"\|"look"\|"bad", spans: [{from, to, state: "look"\|"bad"}]}], changes: [{at, key, text, from, to}]}` | HD1 |
| `GET /api/analytics` | `months=12` (1 to 13), `printer?=<id>` | `{months: [{month: "2026-11", grams, prints, unfinished_prints, unfinished_grams, logged_only_grams, no_weight_prints, by_printer: [{id, name, grams, prints}], by_material: [{material, grams}], top_material?}], insights: [{key: "total"\|"favourite_material"\|"busiest_printer"\|"unfinished"\|"biggest_print"\|"spools_finished", text}], notes: [<text>]}` | HD3 |
| `GET /api/export/{set}.csv` | set = `usage` (`days`, `printer`), `locations`, `recent`, `activity` (`days`), `printers`, `lines`, `spoolman-spools`, `spoolman-filaments` | the file, `text/csv; charset=utf-8`, as a download | HD5 |
| `POST /api/import/spools` | the file as the body (`text/csv`), `?dry_run=1` (default 1) | `{rows: [{n, ok: bool, problems: [{column, text}], line: <what would be added, in words>}], add: <number>, dry: bool, spool_ids?: [...]}` | HD5 |
| `POST /api/import/locations` | the same | `{rows: [{n, ok, problems, line}], add: <number>, change: <number>, dry: bool}` | HD5 |

A web token may call the `GET /api/export/...` routes, `GET /api/health` and `GET /api/analytics`; not the imports.

**Filament-used entries (owner HD3).** New entries of both printer families carry `material`, `vendor`, `name`,
`color_hex`, `printer_name` and `outcome`. `GET /api/printers/{id}/usage` serves them and takes `by=month` (answer
`{months: [{month, grams, prints, unfinished_prints, top_material?}]}`).

**The viewer role (owner HD1 for the Hub side).** A pairing can have the role `viewer`: it may call only these routes,
all GET: `/api/info`, `/api/hub`, `/api/events`, `/api/alerts`, `/api/printers`, `/api/printers/{id}`,
`/api/printers/{id}/usage`, `/api/printers/{id}/camera.mjpeg`, `/api/printers/{id}/camera/{name}`, `/api/spools`,
`/api/spools/{id}`, `/api/spools/low`, `/api/storage`, `/api/storage-use`, `/api/health` and `/api/analytics`. Everything
else answers 403. It is made with `sudo spoolwarden pair --home-assistant` and Devices > **Link Home Assistant** (kind
"Home Assistant" in Devices; client header `X-Spoolwarden-Client: home-assistant/<version>`). The pairing link and code
are the ones every pairing uses.

**Page routes** (under `/setup/api/`): the rows of 03 section 15 for activity, undo, health, analytics, export, import, the
backup password, the restore password and the report. HD6 builds them, except `GET analytics` (HD7b) and the backup
password and restore routes (HD4). **Twins** (under `/intake/api/`; HD8): `GET activity` (passes `GET
/api/events?activity=1&...`), `POST events/{id}/undo`, `GET health`, `GET analytics` and `GET export/{set}.csv` for
`usage`, `recent` and `spoolman-spools`, each passing the kit route on unchanged. **The command line** (HD2): `spoolwarden
activity [--spool <n>] [--who <name>] [--days 7]`; `spoolwarden undo [<event id>] [-y]`; `spoolwarden status --history
[--days 7]`; `spoolwarden usage [--by month] [--printer <name>]`; `spoolwarden export <usage|locations|recent|activity|
printers|lines|spoolman-spools|spoolman-filaments> [--out <file>] [--days n] [--printer <name>]`; `spoolwarden import
<spools|locations> <file> [-y]`; `sudo spoolwarden backup password [--remove|--show]`; `spoolwarden restore <file>
[--password-file <file>]`; `sudo spoolwarden report [--out <file>]`; each with `--json` where it has an object.

### Which files the stage shares with the stages before it

Each registry file below is opened by exactly one HD step, and that step starts only after the step that has the file
open is merged. A step whose only wait is a registry file builds everything else first and adds its registry lines last.

| Registry file | Opened by | Opened before by | Merge first |
|---|---|---|---|
| `api.py` | HD1 | EA3, AF5, then EV1 | EV1 |
| `cli.py`, `status.py`, the string catalogue and its copies | HD2 | EA3, AF5, then EV2 | EV2 |
| `setup_page.py`, `setup_static/setup_overview.js` | HD7e | EA6, AF6, then EV5 | EV5 |
| `setup_static/setup.js` | HD7e | EA6, then EV5 | EV5 |
| `shared_static/components.js`, `shared_static/components.css` | HD7e | EA5 | EA5 |

`setup_static/setup_settings.js` is not opened in this stage.

### HD0 Design text
Design + docs · Depends on: none · Beside: every other HD step
- **Files today:** `docs/design/*.md`.
- **Change:** the design text of this stage: 01 (twelve sections), 02, 03, 04, 05, 06, 07 and 09 (this stage).
- **Keep:** every other part.
- **Other interfaces:** every HD step reads it.
- **Check:** the design's own tests.

### HD1 Hub: events, undo, health and the viewer role
Server builder · Depends on: none · Beside: every other HD step except for its registry file
- **Files today:** `event_kinds.py`, `events.py`, `alerts_api.py`, `event_sink.py`, `inventory.py`, `bridge/loading.py`,
  `bridge/registry.py`, `pairing.py`, `library.py`, `intake_history.py`, new `undo.py`, new `health.py`, tests. Registry
  file: `api.py`, after EV1 is merged.
- **Change:** events for every action, with who did it and complete before-values; the undo rule and route; the activity
  filters of `GET /api/events`; `event_id` in the answers of the routes that make an undoable change; `GET /api/health`;
  the viewer role; the mounts of HD3's and HD5's routes.
- **Other interfaces:** every other HD step builds against these routes with stubs.
- **Check:** prove first (item 3 of the list below). Then the route and event tests.

### HD2 Hub: the command line and the texts
Server builder · Depends on: none · Beside: every other HD step except for its registry files
- **Files today:** `alerts_cli.py`, new `history_cli.py`, tests. Registry files: `cli.py`, `status.py` and the string
  catalogue, after EV2 is merged.
- **Change:** the command line of the contracts above, the events of command-line changes, and ALL catalogue texts of this
  stage.
- **Other interfaces:** every other HD step names its keys to this one before it files.
- **Check:** the command tests; the catalogue and wording tests (08 test 7).

### HD3 Hub: analytics and the richer filament-used entries
Server builder · Depends on: none · Beside: every other HD step
- **Files today:** new `analytics.py`, `bridge/usage.py`, `bridge/klipper/usage.py`, tests.
- **Change:** `GET /api/analytics`, the new fields of every new entry, `usage.undone`, `by=month`, and Klipper's 13 months
  kept by time.
- **Check:** prove first (item 1 of the list below).

### HD4 Hub: backup encryption, the password and restore
Server builder · Depends on: none · Beside: every other HD step
- **Files today:** `backup.py`, new `backup_crypt.py`, `install/backup.sh`, `install/install.sh`, `updates.py`,
  `setup_console/backup_tab.py`, `setup_helper.py`, tests.
- **Change:** backup encryption and the password, restore with a password, the backup, restore and update events; in the
  root helper the password operations, the report job's entry (it calls HD6's `report.py`) and `settings.changed` for
  every save that goes through the helper.
- **Check:** prove first (item 2 of the list below).

### HD5 Hub: CSV export and import
Server builder · Depends on: none · Beside: every other HD step
- **Files today:** new `csv_io.py`, tests.
- **Change:** the export and import routes of the contracts.
- **Check:** prove first (item 5 of the list below).

### HD6 Hub: the Hub report and the page routes
Server builder · Depends on: none · Beside: every other HD step
- **Files today:** new `report.py`, `redact.py`, `setup_console/logs_tab.py`, new `setup_console/history_tab.py`, tests.
- **Change:** the Hub report; the page routes of activity, undo, health, export, import and report; the page's "who". Its
  routes are mounted by HD7e.

### HD7a Hub page: Logs with Activity
Bug-bash 1 · Depends on: none · Beside: every other HD step
- **Files today:** `setup_static/setup_logs.js` and its CSS.
- **Change:** 03 13: Logs with Activity, Undo in its rows, **Collect a Hub report**.
- **Other interfaces:** HD7e mounts it.

### HD7b Hub page: the Analytics section
Bug-bash 1 · Depends on: none · Beside: every other HD step
- **Files today:** new `setup_console/analytics_tab.py`, new `setup_static/setup_analytics.js`, new
  `setup_static/setup_analytics.css`.
- **Change:** 03 17.
- **Other interfaces:** HD7e mounts it.

### HD7c Hub page: the backup password
Bug-bash 1 · Depends on: none · Beside: every other HD step
- **Files today:** `setup_static/setup_backup.js`.
- **Change:** 03 10.6 and 10.11: the backup password, "Encrypted" in the list, the restore password.

### HD7d Hub page: Undo, a spool's last events and CSV
Bug-bash 1 · Depends on: none · Beside: every other HD step
- **Files today:** `setup_static/setup_spools.js`, `setup_printer_live.js`, `setup_intake.js`, `setup_storage.js`,
  `setup_presets.js`, `setup_printers.js`.
- **Change:** 03 2.9, 2.10, 5.10 and 16: the Undo toasts, a spool's last ten events, the CSV menus and the imports.
- **Other interfaces:** HD7e mounts the Undo button of the toast.

### HD7e Hub page: the registry
Bug-bash 1 · Depends on: none · The last of the Hub page steps
- **Files today:** new `setup_static/setup_history.js`. Registry files: `setup_page.py`, `setup_static/setup.js` and
  `setup_static/setup_overview.js`, after EV5 is merged; `shared_static/components.js` and `shared_static/components.css`,
  after EA5 is merged.
- **Change:** Analytics in the navigation, the health strips and "Filament used this month" on Overview, the toast's
  Undo button, the mounts of the routes and scripts of HD6 and HD7a to HD7d.
- **Check:** prove first (item 4 of the list below).

### HD8 Web app: Undo, last events, By month and downloads
Klipper builder · Depends on: none · Beside: every other HD step
- **Starts after:** EV6a and EV6b are merged: they have these files open in Stage 12.
- **Files today:** `web/static/app.js`, `web/static/printers.js`, `web/intake_app.py`, `web/printers_app.py`.
- **Change:** 04: Undo toasts, a spool's last ten events, By month, the downloads and the health table; their twins.

### HD9 App: Undo, last events, By month and downloads
App builder · Depends on: none · Beside: every other HD step
- **Starts after:** EV7a and EV7b are merged: they have these files open in Stage 12.
- **Files today:** `net/Api.kt`, `net/Models.kt`, `ui/spool/SpoolScreen.kt`, `SpoolViewModel.kt`,
  `ui/printers/PrinterScreen.kt`, `PrinterViewModel.kt`, `ui/hub/*`, the toast component.
- **Change:** 05: the same five things as HD8.

### HD10 Home Assistant integration
To be assigned · Depends on: none · Beside: every other HD step
- **Files today:** a new repository.
- **Change:** the integration of the rules above. It needs only the viewer role of the contracts.
- **Check:** prove first (item 6 of the list below).

### HD11 Documents
Design + docs · Depends on: HD1 to HD10 merged
- **Files today:** `docs/*.md`, `README.md`, `release-notes/next.md`.
- **Change:** the user documents and the release notes.
- **Keep:** the wording of the other sections.

**Order.** HD0 to HD10 now. HD11 last, after the batch. Registry files, one after the other, per file: `api.py`: EA3 > AF5 >
EV1 > HD1. `cli.py`, `status.py` and the string catalogue: EA3 > AF5 > EV2 > HD2. `setup_page.py` and
`setup_overview.js`: EA6 > AF6 > EV5 > HD7e. `setup.js`: EA6 > EV5 > HD7e. `shared_static/components.js` and
`components.css`: EA5 > HD7e.

**How far the map is checked.** From three reads of the code. Not looked at: where the command line's changes enter
(`cli.py` is HD2's, so its events are HD2's), how the toast component is built and whether it can carry a button, the
Android toast, `menu_ui.py`'s own undo, the CSS files.

### To prove first, in the step that meets it

Each has a fallback.

1. **HD3: whether a Bambu Lab print that stopped was cancelled or failed** cannot be told today. Until a recorded printer
   answer shows it, a Bambu Lab entry's outcome is `finished` or `unknown` for a stopped print, and "did not finish"
   counts `failed`, `cancelled` and `unknown` stops together.
2. **HD4: the encryption's exact form** (the piece size, the header) is the builder's, inside the rule above. It must be
   shown that a cut file, a changed byte and a wrong password each fail before anything is replaced, and that a 2 GiB
   backup encrypts without holding it in memory.
3. **HD1: undo of a tag link** can restore the tag the spool had before. If Spoolman's record cannot be put back
   exactly, tag links are not undoable and the toast has no Undo for them.
4. **HD7e: the toast can carry a button** in all four themes. Else Undo appears as a line under the action's result.
5. **HD5: Spoolman's export answers at that address** on the installed Spoolman. If not, the two pass-through sets are
   not offered and the page says "Spoolman's own export is not available in this Spoolman version."
6. **HD10: Home Assistant accepts a pinned self-signed certificate** from an integration's own HTTP session (assumed;
   many local integrations do this).

**Out of scope:** a second place for backups; a restore drill; quiet hours; undo for settings; charts beyond the monthly
bars; controlling a printer from Home Assistant; importing filament-used history, events or preset lines; exporting
secrets in any form.

---

## 21. Stage 14: Reach: the rest of the data as XML, languages, demo mode and spool labels

The rest of the Hub's own data is kept as XML like `printers.xml` already is; the string catalogue becomes XML and
language packs follow its form, so the interfaces can speak more than one language; the whole product can run on
made-up data for a person who only wants to look; and a spool gets a label with a QR code that opens it. The parts
that specify it are 02 7.13 and 8.8, 03 3.9, 4.2, 6.3, 10.2, 10.3, 15 and 16, 04 1.2, 2.4, 5.4, 9.2 and 14, 05 2.5, 3.7,
4.4, 7.1, 7.10, 12.2 and 16, 06 3.1, 6.4, 9.1, 9.20, 9.21, 9.27, 9.28 and 13, 07 SR-1 and LNG-8, and 08 section 12. The
words "kit route", "page route" and "twin" are used as Stage 12 uses them. It starts from the Hub as Stage 13 leaves it,
with the shared XML helper (`bridge/xmlfile.py`: a safe parser, a declared shape per file, a size cap, the last good
data kept) and the files `printers.xml`, `storage.xml`, `firstrun.xml`, `alerts.xml`, `push.xml` and the event store
already in XML.

### The rules of the stage

- **All steps start at once**, each against the contracts below and in 03 section 15, 04 section 14, 05 section 16 and
  06 section 13. A registry file waits for the merge of the step named for it, and nothing else waits. New kit routes
  live in new modules that give their routes as a list; one step, RC9, mounts them in `api.py`, so `api.py` has one
  holder.
- **Data as XML: what moves.** Every file that Spoolwarden's own programs keep as stored data or settings: the Hub's
  settings file `config.json`; the pairing files; `reads.json`; the slicer-preset state (`lines.json`, `updates.json`,
  `current.json`, `installed.json`, `deleted.json`, `owner-edits.json`, `build-state.json`, `pc-heartbeat.json`,
  `live/meta.json`, and the build marker files `BUILD.json`, `SLICER.json` and `KEPT.json`); the Filament Catalog's own
  state (`current.json`, `previous.json`, `last_check.json`, `rolled_back.json`) and the owner's own entries
  (`library-local`); the Recently added records and their pending reads; the share queue; the Bambu Lab printers'
  per-printer files (`usage.jsonl`, `mapping.json`, `slotmap.json`, `slottest-snapshot.json`); `station-requests.json`;
  `reader-setup.json`; the Label Reader's `installed.json` and `plan.json`; `releases/state.json`; the web unit's
  `oauth.json`; the Weigh Station's `station_server.json` and `pair/request.json`; the Slicer Sync program's own files.
- **Data as XML: what does not move, and why.** What a slicer reads (the generated presets: the slicers' format). What a
  device in the field reads (the Tag Reader firmware's update manifest). What is sent between programs (API bodies, the
  pairing link, the printers' and Spoolman's protocols). What comes from elsewhere and is only stored as it arrived (the
  downloaded Filament Catalog versions, the Label Reader's own manifest, the voice model's description). The command
  line's `--json` output, which stays. The Android app's settings, which are not JSON files.
- **One way to do it,** the one `printers.xml`, `storage.xml` and `firstrun.xml` already use: the shared XML helper, the
  atomic write with the Hub's owner and mode (`pairing._write_atomic`), and a version on the root element. Element and
  attribute names are lower-case with hyphens; a single value is an attribute, a list is repeated child elements, free
  text is element text; no file mixes text and elements. The exact shape of each file is declared in the code with the
  helper, and the step that makes the file writes it into "The shapes of the files" below; a step may not invent a
  second way.
- **Moving a file.** At the first start (or first use) with this version, a file that exists as JSON and not as XML is
  read, written as XML, and from then on only the XML is used. A start never fails for it: a JSON file that cannot be
  read is left where it is, the Hub works with what that file's code does today for a missing file, and the Checks show
  one row, group Hub, Needs a look: "<What it is> could not be converted (<reason>)." with the Fix the code can name
  (03 4.2, 06 9.1). An XML file that cannot be read is never overwritten: it is kept as `<name>.unreadable` on the next
  save, as today.
- **Going back one version** (`update --rollback`). The JSON files are left on disk as they were at the move and are not
  deleted for one release. Two are also kept up to date in that time, because losing them on a rollback is real harm:
  the Hub's settings and the list of paired devices, written in both forms, XML first, the way `printers.json` is
  today (`bridge/registry.py:225-274`). For the others a rollback sees the state at the move. The release after next
  deletes the left-over JSON files.
- **The settings file** becomes `/etc/filament-kit/config.xml`, with the same owner, mode and read grant for the web
  unit. The three shell scripts that read JSON with sed or Python (`install/install.sh`, `install/uninstall.sh`,
  `install/spoolwarden-cli.sh`) read the XML through the Hub's Python instead of parsing it themselves.
- **The Bambu Lab filament-used log** is one growing line file today; it becomes one XML file per month per printer
  (`usage/<yyyy-mm>.xml`), as the event store has. Klipper's is XML already.
- **Files two programs share** (the build marker files that the Hub writes and Slicer Sync reads) change in one step on
  both sides, and Slicer Sync reads both forms for one release, so a new Hub with an old Slicer Sync or the other way
  round still installs presets.
- **Backup and restore.** A backup made before this version holds JSON; after such a restore the first start moves the
  files as above.
- **The string catalogue** becomes `strings/en.xml` and `strings/en.json` goes. The generator (`tokens/build_tokens.py`)
  reads the XML and writes what it writes today: the web copies and Android's resources. The form is the one of 08
  section 12 (`<strings language="en" name="English" for="0.7.0">` with `<text key="…">`, plural forms as `<one>` and
  `<other>`, `{name}` placeholders as they are, an optional `note="…"` for the translator). Nothing a person sees
  changes by this step alone: the texts are the same.
- **Languages.** The first packs are Russian and German; German is machine-translated and shown everywhere as "Deutsch
  (machine-translated)" until a speaker of German has read it and the pack is marked reviewed. A pack is one XML file in
  the catalogue's form with the English beside each text, so a translator needs nothing but a text editor (08 section
  12); an empty translation means "use the English". `spoolwarden language template <code>` writes a pack, and
  `spoolwarden language check <file>` says in plain sentences what is wrong and how much is translated (06 9.27). Packs
  live in the repository as `strings/packs/<code>.xml` and with each release as `spoolwarden-lang-<code>.xml`; English
  is always inside the product. On the Hub, Settings > General > Language lists English, the installed languages and
  **Get more languages**; choosing one downloads it as a job like the Filament Catalog's update, checks it with the
  rules of `language check` (a pack that fails is not installed) and keeps it in `<state>/languages/<code>.xml`. An
  update of the Hub fetches the matching pack of each installed language; until it has it, the old pack is used and
  new texts are English. At install the installer reads `LANG`; if the release has a pack for it, it downloads it,
  makes it the Hub's language and prints one line (06 9.20); no question is asked.
- **Which language a person gets.** Each interface has "Language: Automatic" by default: the device's language if the
  Hub has that pack, else the Hub's language; removing the Hub's own language is refused ("<Language> is the Hub's
  language. Choose another one for the Hub first."), and removing any other installed language sets the devices that
  had chosen it back to Automatic at their next visit; it can be set per device to any installed language (the Hub page: Settings
  > Appearance, kept in that browser; the web app: Settings, kept on that phone; the Android app: Settings > Appearance,
  Android's own per-app language; the command line: `--lang <code>` or the shell's `LANG`, else the Hub's). Every text
  the Hub writes (alert titles and texts, Checks rows, refusals) carries `key` and `params` beside `text`; `text` is
  in the language the caller asked for (`Accept-Language`, or `?lang=`), falling back to the Hub's language and then to
  English. A notification sent to a phone is in that phone's language: the web app's push subscription and the Android
  app send their language. The Android app carries every language of its release inside the app, as generated resources
  per language, and downloads no pack; a pack newer than the app reaches it with the next app update. Dates and numbers
  follow the chosen language in each interface: pages set their `lang`, and plural rules come from the language, not
  from "en" (`web-shared/components.js:13`).
- **Not translated in this stage:** the installer's lines and the command line's option help (they are not in the
  catalogue; about 31 and 234 texts), the Weigh Station's spoken and panel texts, the Tag Reader's display, and the
  documents. The command line's results that come from the catalogue are translated. Right-to-left languages are not
  supported.
- **Demo mode** is the whole product running on made-up data with pretend printers, in every interface. The data is the
  sample set of `mockups/CONTENT-SPEC.md` ("Workshop hub": 64 spools, three printers and one found, a print running at
  42 %). It can be switched on only while the Hub has no spool and no printer; otherwise it is refused with "The demo is
  for an empty Hub. This Hub has real data." It is offered in Getting started ("Just looking? Try the demo"), in
  Settings > General, and as `sudo spoolwarden demo on`, and switching it on needs the page unlocked.
- **Demo mode touches nothing real.** The Hub talks to a demo inventory instead of Spoolman and to pretend printers
  instead of real ones, and keeps everything it records (events, filament used, storage locations, Recently added) in a
  folder of its own inside its state folder. It does none of these, and each answers "Not in the demo.": reach a
  printer, write to Spoolman, call the Label Reader's cloud, download from GitHub (updates, the catalog, language
  packs), send a push, make or restore a backup, flash a device, change system settings through the root helper. Pairing
  a phone or a PC works, so the demo can be seen on them.
- **Demo mode moves.** The pretend printers print and can be paused, resumed and stopped; slots can be loaded and
  unloaded; filament used is recorded; and one scripted alert ("Filament ran out" on the Klipper printer) shows two
  minutes after the demo starts or restarts. There is no camera picture ("No camera in the demo.").
- **Demo mode is always visible, and it ends cleanly.** Every screen of every interface shows the banner "Demo data.
  Nothing here is real." with **Leave demo** (the Hub page and the web app; the Android app's notice card; the command
  line prints "Demo data." above every result), and a test holds that no screen lacks it. Leaving asks once ("Leave
  the demo? Everything in it is deleted."), in place on the Hub page, in the web app and in the Android app (the apps
  call `POST /api/demo/leave`; none opens the Hub page; switching the demo on stays on the Hub page and the command
  line), deletes the demo's folder and brings the Hub back as it was: empty. Getting
  started is not marked by anything done in the demo. Every answer that says what the Hub is (`GET /api/info`,
  `GET /api/hub`, the page's state) carries `demo: true` while it is on.
- **Spool labels.** A spool has a short address, `https://<hub>/s/<number>`. Opening it in a browser goes to the spool:
  in the web app when that is on (`/intake#spools/<number>`), else on the Hub page's Spools section. The Android app
  understands the same address: **Scan a label** in Spools (the QR scanner that pairing already has) opens the spool
  whatever Hub address is printed on the label, because only the number after `/s/` is used; a phone's own camera opens
  the browser at the printed address. The label is drawn by the Hub as SVG: the QR code, the spool's number large,
  brand, name, material, a box in the filament's colour with its hex value, the lot, the date it was added, the net
  weight, and the nozzle and bed temperatures when the filament has them. Sizes: 62 x 29 mm (a 62 mm roll), 50 x 30 mm,
  and a sheet of 24 (A4 or Letter by the browser's paper). Black on white; the colour box is the only colour.
- **Labels are printed through the browser's or Android's print dialog.** **Print a label** on a spool (the Hub page's
  Spools detail, the web app's spool sheet) and **Print labels** for several (the selected spools; a Recently added
  record's spools) open a print page with the size choice and a preview, then the system's print dialog; Android does
  the same through its print service. No label printer is driven directly and no PDF is made. The QR code holds the
  Hub's home address (`https://<name>.local[:port]/s/<number>`): if the Hub is renamed or its port changes, old labels
  still work in the Android app's scanner and stop working from a phone's camera, and the print page says so in one
  line. Spool numbers are Spoolman's own and survive a restore. The command line writes the SVG:
  `spoolwarden spool label <number>... [--size 62x29|50x30|sheet24] --out <file.svg>`.
- **Texts.** Only RC9 opens the string catalogue for the new texts of this stage; RC2 changes its form and the
  generator. Every other step sends RC9 its keys and English texts before it files.
- **No file is opened by two RC steps.** A step that finds it needs another step's file stops and says so. Two cases are
  known: the demo's stops for the Filament Catalog's download and for push live in files that RC1d and RC4 hold
  (`library.py`, `web/push.py`), and the pending read's `meta.json` lives in `intake.py`, which RC1b holds; RC7 and
  RC1d name the lines to those steps instead of opening the files. A step that changes a file lists the readers of that
  file it finds before it changes it.

### The contracts

All JSON except where the file is named. A field marked `?` may be absent. Times are ISO 8601 with offset.

**Kit routes** (RC2, RC6 and RC8 as marked).

| Route | Query / body | Answer | Owner |
|---|---|---|---|
| `GET /api/languages` | - | `{hub: "<code>", languages: [{code, name, reviewed: bool, installed: bool, complete: <0-100>}]}` | RC2 |
| `GET /api/strings/{code}.js` | - | the texts of that language as the web pages load them (English filled in where a translation is empty) | RC2 |
| every route that answers a text made by the Hub | header `Accept-Language` or `?lang=<code>` | the object gains `key` and `params` beside `text` | RC2 |
| `GET /api/info`, `GET /api/hub` (changed) | - | gain `demo: bool` and `language: "<code>"` | RC6, RC2 |
| `POST /api/demo/leave` | - | `{demo: false}`; 409 `{error: "not_in_demo", text}` when the demo is off; any paired phone or PC | RC6 |
| `GET /s/{id}` | - | a redirect to the spool (`/intake#spools/<number>` when the web app is on, else the Hub page's Spools section); 404 for an unknown number | RC8 |
| `GET /api/spools/{id}/label.svg` | `size=62x29\|50x30\|sheet24` (default 62x29) | `image/svg+xml` | RC8 |

A web token may call `GET /api/languages`, `GET /api/strings/{code}.js`, `POST /api/demo/leave` and `GET
/api/spools/{id}/label.svg`.

**Page routes** (under `/setup/api/`).

| Route | Body / query | Answer | Lock | Owner |
|---|---|---|---|---|
| `GET languages` | - | as the kit route, plus `available: [{code, name, reviewed, complete}]` (the release's packs; empty when the list could not be fetched, with `problem: <text>`) | open | RC2 |
| `POST languages/{code}/install` | - | starts the job | unlocked | RC2 |
| `POST languages/{code}/remove` | - | `{removed: true}`; refused with "<Language> is the Hub's language. Choose another one for the Hub first." for the Hub's own language | unlocked | RC2 |
| `POST settings/language` | `{hub: "<code>"}` | `{hub}` | unlocked | RC2 |
| `POST demo` | `{on: true\|false}` | `{demo: bool}`; 409 `{error: "not_empty", text}` | unlocked | RC6 |
| `GET labels` | `ids=<n,n,...>&size=` | the print page (HTML; the labels as inline SVG) | open | RC8 |
| `GET spools/{id}/label.svg` | `size` | as the kit route | open | RC8 |

**Twins** (under `/intake/api/`; RC4): `GET languages`, `POST demo/leave` and `GET spools/{id}/label.svg`; the web app's print page is
`/intake/labels?ids=&size=`. RC9 mounts all of these.

**The command line** (RC2 for `language`, RC6 for `demo`, RC8 for `label`; all mounted by RC9): `spoolwarden language
[list]`; `sudo spoolwarden language add <code>`; `sudo spoolwarden language remove <code>`; `sudo spoolwarden language
set
<code>`; `spoolwarden language template <code> [--out <file>]`; `spoolwarden language check <file>`; the global option
`--lang <code>`; `sudo spoolwarden demo on|off` and `spoolwarden demo` (says whether it is on); `spoolwarden spool label
<number>... [--size ...] --out <file.svg>`. Each with `--json` where it has an object.

**Files.** `config.xml` has the root `<config version="1">`; each settings group is one child element named as the
group's key, scalars as attributes, lists as repeated children. A language pack and the catalogue have the form of 08
section 12. Installed packs are `<state>/languages/<code>.xml`; the Hub's language is `language` in the settings.

### The shapes of the files

Each RC1 step adds the shape of every file it makes to this table before it merges, in the form of "One way to do it"
above.

| File | Root and shape | Made by |
|---|---|---|
| `/etc/filament-kit/config.xml` | `<config version="1">`; one child element per settings group, named as the group's key; scalars as attributes, lists as repeated children | RC1a |

### Which files the stage shares with the stages before it

Each registry file below is opened by exactly one RC step, and that step starts only after the step that has the file
open is merged. A step whose only wait is a registry file builds everything else first and adds its registry lines last.

| Registry file | Opened by | Opened before by | Merge first |
|---|---|---|---|
| `api.py` | RC9 | EA3, AF5, EV1, then HD1 | HD1 |
| `cli.py`, `status.py` | RC9 | EA3, AF5, EV2, then HD2 | HD2 |
| the string catalogue and its copies | RC2 (its form and the generator), then RC9 (the new texts) | EA3, AF5, EV2, then HD2 | HD2; RC9 also after RC2: the step that changes the file's form merges after every other holder |
| `setup_page.py`, `setup_static/setup.js` | RC3 | EA6, AF6, EV5, then HD7e | HD7e |
| `setup_static/setup_settings.js` | RC3 | AF6, then EV4d | EV4d |
| `shared_static/components.js`, `shared_static/components.css` | RC3 | EA5, then HD7e | HD7e |
| `__main__.py` | RC6 | EA2 | HD1 (EA2 is merged before it) |

### RC0 Design text
Design + docs · Depends on: none · Beside: every other RC step
- **Files today:** `docs/design/*.md`.
- **Change:** the design text of this stage: 02 to 09 (this stage).
- **Keep:** every other part.
- **Other interfaces:** every RC step reads it.
- **Check:** the design's own tests.

### RC1a Hub: the settings file as XML
Server builder · Depends on: none · Beside: every other RC step
- **Files today:** `config.py`, `web_access.py`, `install/install.sh`, `install/uninstall.sh`,
  `install/spoolwarden-cli.sh`, `updates.py` (its state file).
- **Change:** `config.json` becomes `config.xml`, kept in both forms for one release; the three shell scripts read the
  XML through the Hub's Python; the moving of the file and its Checks row.
- **Check:** prove first (item 2 of the list below).

### RC1b Hub: pairing files, reads and the reader's install files
Server builder · Depends on: none · Beside: every other RC step
- **Files today:** `pairing.py`, `intake.py`, `station_requests.py`, `reader_flash.py`, `local_intake_install.py`.
- **Change:** the pairing files (both forms for one release), `reads.json`, `station-requests.json`,
  `reader-setup.json`, the Label Reader's `installed.json` and `plan.json`, each as XML.

### RC1c Slicer presets and Slicer Sync: state and build marker files
Klipper builder · Depends on: none · Beside: every other RC step
- **Files today:** `profiles/lines.py`, `profiles/builds.py`, `profiles/updates.py`, `pc-sync/fksync/store.py`,
  `pc-sync/fksync/installer.py`.
- **Change:** the slicer-preset state and the build marker files as XML, on the Hub and in Slicer Sync, in one step on
  both sides; Slicer Sync reads both forms for one release; Slicer Sync's own files.
- **Check:** prove first (item 1 of the list below).

### RC1d Hub: the Filament Catalog's state, Recently added and the share queue
Server builder · Depends on: none · Beside: every other RC step
- **Files today:** `library.py`, `intake_history.py`, `share_queue.py`.
- **Change:** the Filament Catalog's own state and the owner's entries, the Recently added records and the share queue,
  each as XML.

### RC1e Hub: the Bambu Lab printers' files and the end of the `printers.json` mirror
Server builder · Depends on: none · Beside: every other RC step
- **Files today:** `bridge/usage.py`, `bridge/mapping.py`, `bridge/ams.py`, `bridge/snapshot.py`, `bridge/registry.py`.
- **Change:** the per-printer files as XML, the monthly filament-used files (`usage/<yyyy-mm>.xml`), and the end of the
  `printers.json` mirror.

### RC1f Web unit and Weigh Station: their files
Server builder · Depends on: none · Beside: every other RC step
- **Files today:** `web/auth.py`, `web/app.py`, `station/server_api.py`, `station/pair_request.py`,
  `install/systemd/filament-kit-station-pair.path`.
- **Change:** the web unit's `oauth.json`; the Weigh Station's two files and its path unit.

### RC2 Hub: the catalogue as XML, languages and `key` and `params`
Server builder · Depends on: none · Beside: every other RC step except for its registry file
- **Files today:** `strings/en.xml` (and the removal of `en.json`), `tokens/build_tokens.py`, new `strings/packs/`, new
  `language.py`, new `language_cli.py`, `alerts_api.py`, `storage_api.py`, new `setup_console/language_tab.py`,
  `tools/make_release.sh` (packs as release files), tests. Registry file: the string catalogue, after HD2 is merged; it
  changes the file's form, so every other holder must be merged first.
- **Change:** the catalogue as XML and the generator (also Android's resources per language); packs: template, check,
  download, install; `key` and `params`; the routes of the contracts above for languages.
- **Other interfaces:** every other step builds against these routes with stubs.
- **Check:** prove first (item 3 of the list below).

### RC3 Hub page: Language, the demo and Getting started
Bug-bash 1 · Depends on: none · Beside: every other RC step except for its registry files
- **Files today:** `setup_static/setup_start.js`. Registry files: `setup_page.py`, `setup_static/setup.js`,
  `setup_static/setup_settings.js`, `shared_static/components.js` and `.css`, after HD7e is merged.
- **Change:** 03 10.2 and 10.3: Language in Settings (General and Appearance), the page's `lang`, plural rules by
  language, the demo banner and Leave demo, Try the demo in Getting started.

### RC4 Web app: Language, the demo banner and Print a label
Klipper builder · Depends on: none · Beside: every other RC step
- **Starts after:** HD8 is merged: it has these files open in Stage 13.
- **Files today:** `web/static/app.js`, `web/static/printers.js`, `web/intake_app.py`, `web/pages.py`, `web/push.py`
  (the subscription's language).
- **Change:** 04: Language in Settings, `lang`, the demo banner, Print a label, the print page.

### RC5 App: Language, the demo notice, Scan a label and Print a label
App builder · Depends on: none · Beside: every other RC step
- **Starts after:** HD9 is merged: it has these files open in Stage 13.
- **Files today:** `ui/settings/AppearanceSettings.kt`, `ui/components/NoticeCard.kt`, `MainActivity.kt`,
  `ui/search/SearchScreen.kt`, `ui/spool/SpoolScreen.kt`, `ui/pair/QrScanner.kt`, `net/Api.kt`, `net/Models.kt`,
  `AndroidManifest.xml`.
- **Change:** 05: Language in Settings (the system's per-app language), the demo notice on every screen, Scan a label,
  Print a label.
- **Check:** prove first (item 4 of the list below).

### RC6 Hub: demo mode
Server builder · Depends on: none · Beside: every other RC step except for its registry file
- **Files today:** new package `demo/` (the sample data as XML), `spoolman.py` (the place a client is made),
  `bridge/connection.py` and `bridge/klipper/manager.py` only where a printer's connection is made, new `demo_cli.py`.
  Registry file: `__main__.py` (how the Hub starts in demo), after HD1 is merged.
- **Change:** the demo inventory, the pretend printers, the demo's own folder, the stops of the rules above, the
  scripted alert, `demo: true`, and the route `POST /api/demo/leave`.
- **Check:** prove first (item 5 of the list below).

### RC7 Hub: the demo's stops in the modules that reach outside
Server builder · Depends on: none · Beside: every other RC step
- **Files today:** `release.py`, `backup.py`, `setup_helper.py`, `web/reader.py`.
- **Change:** the stops "Not in the demo." in these modules.

### RC8 Hub: labels and the short address
Server builder · Depends on: none · Beside: every other RC step
- **Files today:** new `labels.py`, new `qr.py`, new `setup_console/labels_tab.py`.
- **Change:** the label as SVG in three sizes, `GET /s/{id}`, the print page.
- **Check:** prove first (item 6 of the list below).

### RC9 Hub: the registry, the command line and the texts
Server builder · Depends on: none · Beside: every other RC step except for its registry files
- **Files today:** none of its own. Registry files: `api.py`, `cli.py`, `status.py` and the string catalogue, after HD1,
  HD2 and RC2 are merged.
- **Change:** the mounts of the routes of RC2, RC6 and RC8; the command line of the contracts above; the Checks row of
  "Moving a file"; and ALL new texts of this stage.
- **Other interfaces:** every other step names its keys to this one before it files.
- **Check:** the command tests; the catalogue and wording tests (08 test 7).

### RC10 Hub page: Print a label and Print labels
Bug-bash 1 · Depends on: none · Beside: every other RC step
- **Files today:** `setup_static/setup_spools.js`, `setup_static/setup_intake.js`, new `setup_static/setup_labels.css`
  (the print rules).
- **Change:** 03 16 and 6.3: Print a label and Print labels in Spools and Recently added.

### RC11 Documents and the first packs
Design + docs · Depends on: RC2 merged, for the packs' form
- **Files today:** `strings/packs/de.xml`, `strings/packs/ru.xml`, `docs/*.md`, `release-notes/next.md`.
- **Change:** the German pack (machine-translated, marked so); the Russian pack as a template for its translator; the
  user documents and the release notes.
- **Keep:** the wording of the other sections.

**Order.** RC0 to RC10 now (RC4 and RC5 after their holders). RC11 after RC2. Registry files, one after the other, per
file: `api.py`: EA3 > AF5 > EV1 > HD1 > RC9. `cli.py` and `status.py`: EA3 > AF5 > EV2 > HD2 > RC9. The string
catalogue: EA3 > AF5 > EV2 > HD2 > RC2 (form) > RC9 (new texts). `setup_page.py` and `setup.js`: EA6 > AF6 > EV5 > HD7e
> RC3. `setup_settings.js`: AF6 > EV4d > RC3. `shared_static/components.js` and `components.css`: EA5 > HD7e > RC3.
`__main__.py`: EA2 > RC6.

**How far the map is checked.** From two reads of the code. Not looked at: every reader of each JSON file (the steps
name their files; a step lists the readers it finds before it changes a file), the Android stores `AlertsStore.kt` and
`DraftStore.kt`, how the Hub's Python texts outside `alerts_api.py` are looked up, where a printer's connection is made
in both families, and the size of the largest files.

### To prove first, in the step that meets it

Each has a fallback.

1. **RC1c: a new Hub with an old Slicer Sync, and the other way round, still installs presets** (both forms read for one
   release). If the older program cannot be served, the Hub keeps writing the JSON marker files for one release beside
   the XML.
2. **RC1a: every reader of the settings file is found** (the web unit, three shell scripts, the backup, the update). A
   reader missed shows as a failing upgrade run; the fallback is the both-forms rule of "Going back one version", which
   keeps an old reader working for one release.
3. **RC2: a translator can edit the pack in a plain text editor without breaking it.** Tried by running the check
   command on a pack with typical slips (a deleted `>`, a translated placeholder name, an `&`); if its sentences do not
   lead to the fix, the form of 08 section 12 changes before any translating starts.
4. **RC5: Android's per-app language works on the oldest Android the app supports;** else the app follows the phone's
   language only and the setting is not shown there.
5. **RC6: the demo's stops are complete.** A test starts the Hub in demo with the network refused and the real state
   folder read-only and walks every route; anything that fails or writes outside the demo's folder is a missing stop.
6. **RC8: a QR code with the Hub's address at 62 x 29 mm is readable** by a phone camera at the error level the Hub's QR
   code uses (L today); else the level is raised or the code gets more of the label.

**Out of scope:** right-to-left languages; translating the installer, the option help, speech, device displays and
documents; units other than grams and Celsius; driving label printers; PDF; a camera picture in the demo; changing the
downloaded catalogue's or the slicers' formats; removing `--json`.
