# Spoolwarden design: implementation order

This document turns the design of this folder into a sequence of small changes. It starts from the four interfaces
as they are today (a Hub page of nine tabs, a web app with a tab bar, an app without navigation and the
`filament-kit` command) and ends with the Hub page, web app, app and `spoolwarden` command of `01-foundations.md`.
It adds no design: each step points at the part that specifies it, and what the parts leave open is listed in
section 13.

Contents: 1 Rules of the road · 2 How a step is written · 3 Stage 0: groundwork · 4 Stage 1: the Console shell on
the Hub page · 5 Stage 2: Hub page sections · 6 Stage 3: the web app · 7 Stage 4: the app · 8 Stage 5: the command
line · 9 Stage 6: Themes · 10 Stage 7: wording · 11 Hub API additions · 12 Dependencies and the first ten steps ·
13 Open points · 14 Coverage

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
8. **The code rename is separate.** The command name, package and paths change in their own piece of work with its
   own schedule. Steps that wait for it say so ("Waits for the rename"); everything else uses the new words on
   screen and keeps the code names.
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
- **Change:** `components.css` and the shared component script with the components of 02 sections 2 to 10 in the
  Console profile (`rail`, `table`, `inline`), the `data-look` profile groups present but keyed on Console only, and
  a component sample page under `tests/` that shows every component in every state with fake data. The script is
  the one implementation of the element builder, the Hub request helper, the dialog, the toast, the inline result
  and the announcer (02 1.4, "One shared script"); each page's own copies (`h()`, `api()` and their variants in
  `setup_static/` and `web/static/`) are removed in the step that moves that page onto it (S1.3 to S1.7, S3.2 to
  S3.6). No page uses them yet.
- **Keep:** both pages unchanged; the size limits of F12 rule 7 (stylesheet under 40 KB, script under 60 KB).
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
  03 3.1, 3.2, 3.8): ten sections in the two groups of F8 with their new names; Flash a device shows its empty state
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
- **Files today:** none on the released page (the section is new).
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
`tests/strings_allowlist.txt`, so 08 test 7 covers it. S3.8, S3.10, S3.12, S3.13 and S3.15 all edit
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
  Hub; "Cannot reach the Hub".
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
- **Check:** 08 test 5 Kotlin part, with the app's entries removed from `tests/literal_allowlist.txt` in this step
  (the camera's black ground and the swatch fill stay listed with their reasons); AUT-1 Material roles; the app's
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
app · M · Depends on: S4.2, S0.8 · Beside: Stage 3 steps
- **Files today:** every Kotlin file under `<app>/ui/` (texts written inline, `PairTexts.kt`, `UpdateTexts.kt`).
- **Change:** 05 15: every visible text, content description and snackbar text comes from the generated
  `strings.xml` (through `strings/en.json`), with plurals and positional arguments. Texts move unchanged; each screen
  step rewrites its own keys.
- **Keep:** every text as it reads today.
- **Check:** 08 test 7 with no Kotlin entry left in `tests/strings_allowlist.txt` other than routes, keys, log tags
  and MIME types.

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
- **Keep:** what is saved.
- **Other interfaces:** Hub page Settings > Filament Catalog, Add entry (S2.19); command line `catalog add` (S5.8).
  The web app has none yet (feature idea B8).
- **Check:** AUT-8 on the screen.

### S4.10 Printers list, add, find Klipper printers
app · M · Depends on: S4.4 · Beside: S4.5, S4.9, S4.15
- **Files today:** `<app>/ui/printers/PrintersScreen.kt`; `<app>/net/Api.kt`.
- **Change:** 05 9.1 to 9.3: the list with status shape and word; Add a Bambu printer; Add a Klipper printer and Find
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
- **Change:** 05 11: the Home panel and the Slicer presets screen.
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
  2138-2167, `cert` and `ensure-fields` 779-798, `uninstall` 1895-1925, `migrate-*` 2226-2243, `update` 2498-2509,
  parser 2262-2427); `backup.py`; `updates.py`.
- **Change:** 06 9.8 to 9.15, 10 and 3: `config show` and `config set`; `label-reader status` and `test`; `catalog`;
  `backup create`, `list`, `keep`; `restore`; `web`; `remote get-certificate` and `firewall`; `setup-code`;
  `certificate`; `spoolman fields` and `address`; `update`; `uninstall`; `logs`; `migrate-ops`; `migrate-scanner`;
  the pointer commands `add` and `spool`; `help aliases` and `help --markdown`; the grouped top-level help.
  `config theme` arrives in S6.10.
- **Keep:** old spellings as aliases; `restore`'s typed word.
- **Other interfaces:** Hub page S2.13, S2.14, S2.19; the pointer commands name the web app and the app for what needs
  a camera or NFC (06 10).
- **Check:** AUT-9 at 80 columns; a test that `help --markdown` lists every command of 06 3.2.

### S5.9 The `spoolwarden` command
command line · S · Depends on: S5.8 · Beside: S6.1 to S6.9 · **Waits for the rename**
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
  in both pickers.
- **Keep:** markup and scripts: a theme brings no markup or script of its own (F6.1).
- **Check:** AUT-5 in Workbench light and dark; manual: release checklist step 4 (Workbench part).

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
- **Keep:** markup and scripts.
- **Check:** AUT-5 in Palette light and dark; manual: release checklist step 4 (Palette tiles read with field names).

### S6.7 Palette on Android
app · M · Depends on: S6.5 · Beside: S6.6
- **Files today:** the composables that read the profile locals.
- **Change:** `NavStyle.Pills`, `CollectionStyle.Tiles`, `DetailStyle.Sheet`; `FontFamily.Default` (08 14); the tile.
- **Keep:** screens and routes.
- **Check:** AUT-8 in Palette.

### S6.8 Panes on the web
Hub page, web app · L · Depends on: S6.6 · Beside: S6.9
- **Files today:** `components.css`; the navigation part of the shared component script.
- **Change:** the `list`, `rows` and `pane` profile groups keyed on Panes, with drill-in navigation on phones (F6);
  the Panes tile.
- **Keep:** addresses: the same `#section/<id>` places open the same things.
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
- **Change:** AUT-7 with no allow-list entry for an old name; any old name left on a screen replaced; any text left
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

---

## 11. Hub API additions

Every item of the merged list of what the design needs from the Hub, with the step that adds it and the first step
that uses it. Items marked "feature idea" belong to an idea of `10-feature-ideas.md` that this order does not build;
they come with that idea.

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
| N36 | Klipper scan relayed for the web app | Feature idea B3 | none in this order |
| N37 | Read-only Hub summary for paired devices | Feature idea B4 | none in this order |
| N38 | Add a Filament Catalog entry from the web app | Feature idea B8 | none in this order |
| N39 | `/LICENSE` and `/THIRD-PARTY.md` served as text | Feature idea B9 | none in this order |
| N40 | Running-low thresholds and list | Feature idea C1 | none in this order |
| N41 | Undo tokens for spool changes and slot loads | Feature idea C2 | none in this order |
| N42 | Where the Access Code is on each printer model | Feature idea C3 | none in this order |
| N43 | Colour name and family per filament, searchable | Feature idea C4 | none in this order |
| N44 | CSV downloads | Feature idea C5 | none in this order |
| N45 | Spool label SVG with QR | Feature idea C6 | none in this order |
| N46 | Printer events with kind and reason; a stream for the app | Feature idea C7 | none in this order |
| N47 | Spools grouped by location with dry-box humidity | Feature idea C8 | none in this order |
| N48 | Monthly usage totals, kept 13 months | Feature idea C9 | none in this order |
| N49 | Demo data store, simulated printers, `demo` flag | Feature idea C11 | none in this order |
| N50 | Activity record with actor | Feature idea C12 | none in this order |
| N51 | Read a project file and match spools | Feature idea C13 | none in this order |
| N52 | Disk use per category | Feature idea D1 | none in this order |
| N53 | Update window and "no printer printing" check | Feature idea D2 | none in this order |
| N54 | Hub report job with redaction | Feature idea D3 | none in this order |
| N55 | Second backup folder and copy state | Feature idea D4 | none in this order |
| N56 | Backup check job | Feature idea D5 | none in this order |
| N57 | Scheduled status checks kept 30 days | Feature idea D6 | none in this order |

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
          S0.11 > S3.2      S3.7 > S3.8      S3.9 > S3.10, S3.11      S3.13 + S3.14 > S3.15      S3.2 > S3.16

Stage 4   S0.4 + S0.9 > S4.1 > S4.2 > S4.3 > S4.4 > each of S4.5 to S4.12 and S4.15 (S4.5 / S4.8)
          S4.6 + S4.13 > S4.14      S3.7 > S4.7      S3.9 > S4.8, S4.11      S4.10 > S4.11

Stage 5   S2.1 > S5.1 > S5.2 > S5.4      S2.17 > S5.4
                 S5.1 > S5.3 > S5.5 / S5.6 / S5.7 / S5.8 > S5.9 (waits for the rename)
          S2.8 > S5.6      S2.11 > S5.7      (every Stage 5 step edits cli.py: one at a time)

Stage 6   S2.17 > S6.1 > S6.2 > S6.4 > S6.6 > S6.8 \
                  S6.1 > S6.3 > S6.5 > S6.7 > S6.9  > S6.10 (also needs S5.8)

Stage 7   S2.11 > S7.1 > S7.2 (after every interface step of Stages 1 to 5)      S5.8 > S7.3 (command names after S5.9)
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
   data for all ten sections of foundations 8, and an Empty Hub variant for the empty states. S1.11 serves it.
7. **The poll interval of a running slot mapping (N32).** Optional; until set, the interfaces poll as today. Needed
   only if S2.4, S3.11 or S4.11 change the interval.
8. **The headless browser for AUT-5.** 07 15 names a headless browser but not which; it runs only in tests, and its
   licence and where it runs are open. Needed by S0.11 and S1.11.
9. **Settled: the app's Recent destination.** The app has Recently added screens, so S4.2 builds the bar with all
   five destinations and moves those screens onto the `recent` routes unchanged; S4.12 rebuilds them.
10. **A printer's id and its serial.** 06 writes `/api/printers/<serial>/…`, 05 `api/printers/{id}/…`; whether they
    are the same value is not stated. Needed by S5.5 (naming a printer by serial or id).
11. **"The web app answers on this Hub (port 8101)" in 06 9.12.** Whether this is the web service's own port behind
    the Hub's address or the Hub's 8710 is not stated. Needed by S5.8 (`web status`).
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
| 3.1 Top bar; 3.2 Navigation; 3.8 Page frame | S1.3 |
| 3.3 Lock chip | S1.5 |
| 3.4 Appearance control | S1.2 |
| 3.5 Job indicator and job strip | S1.8, S1.9 |
| 3.6 The Hub is restarting; 3.7 The Hub is not answering | S1.9 |
| 4 Overview | S2.1, S2.2 |
| 5 Printers (5.1 to 5.5, 5.7 to 5.9) | S2.3, S2.4 (dialogs S1.6) |
| 5.6 Add a printer; 5.4 Find Klipper printers and Klipper add-on | S2.5 |
| 6 Recently added | S2.6, S2.7 |
| 7 Devices | S2.8, S2.9 |
| 8 Slicer presets | S2.10 |
| 9 Features | S2.11, S2.12 |
| 10 Settings | S2.17, S2.18, S2.19; 10.2 Theme S6.2, Theme for new devices S6.1, S6.10 |
| 11 Flash a device | S2.15, S2.16 |
| 12 Updates | S2.13 |
| 13 Logs | S2.14 |
| 14 Where today's controls went | the steps above, section by section |
| 15 Needs from the Hub | section 11 |

### 14.2 `04-web-app.md`

| Section | Steps |
|---|---|
| 1 Where the web app runs | S3.1 |
| 2 Navigation | S3.3 |
| 3.1 to 3.6 Patterns used on every screen | S3.2, S3.6 |
| 3.7 Sheets and dialogs | S3.5 |
| 4 Add spools | S3.7, S3.8 |
| 5 Spools | S3.9, S3.10 |
| 6 Printers | S3.11 |
| 7 Recently added | S3.12 |
| 8 Slicer presets | S3.13 |
| 9 More and Settings | S3.3; theme S6.2 |
| 10 Home screen, offline and "Cannot reach the Hub" | S3.6, S3.14, S3.15 |
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
| 5 Home | S4.6 |
| 6 Add spools | S4.7 |
| 7 Spools and the spool screen | S3.9, S4.8 |
| 8 Add a line to the Filament Catalog | S4.9 |
| 9 Printers | S4.10, S4.11 |
| 10 Recently added | S4.12 |
| 11 Slicer presets | S4.13, S4.14 |
| 12 Settings | S4.15; 12.2 theme S6.3 |
| 13 App updates | S4.15 |
| 14 Accessibility | S4.4 (AUT-8), and the check of every screen step |
| 15 Strings and wording | S0.8, S4.3 |
| 16 Needs from the Hub | section 11 |
| 17 Where today's screens and controls went | the steps above |

### 14.4 `06-command-line.md`

| Section or command group | Steps |
|---|---|
| 2 The command name | S5.9 (waits for the rename) |
| 3 The command tree | S5.8 (help), S5.9 |
| 4 Old and new spellings | S5.5 to S5.8 |
| 5 Naming a printer, device or record | S5.5, S5.6 |
| 6 Output conventions | S5.1, S5.3 |
| 7 Confirmations | S5.2 |
| 8 Interactive screens | S5.4 |
| 9.1 `status` | S2.1, S5.1 |
| 9.2 `printer` and `klipper` | S5.5 |
| 9.3 `recent` | S5.6 |
| 9.4 `devices` and `pair` | S2.8, S5.6 |
| 9.5 `presets` | S5.7 |
| 9.6 `features` | S2.11, S5.7 |
| 9.7 `weigh-station` and `tag-reader` | S5.7 |
| 9.8 `config show`, `config set`, `config theme` | S5.8; `config theme` S6.10 |
| 9.9 `label-reader` | S2.18, S5.8 |
| 9.10 `backup` and `restore` | S5.2, S5.8 |
| 9.11 `catalog` | S5.8 |
| 9.12 `web`, `remote`, `setup-code`, `certificate`, `spoolman` | S5.8 |
| 9.13 `update` and `uninstall` | S5.2, S5.8 |
| 9.14 `logs` | S5.8 |
| 9.15 `migrate-ops` and `migrate-scanner` | S5.8 |
| 10 What the command line cannot do (`add`, `spool`, `printer live`) | S5.5, S5.8 |
| 11 Usability problems and their fixes | S5.1 to S5.8 |
| 12 Parity | the "Other interfaces" lines of the steps |
| 13 Needs from the Hub | section 11 |

### 14.5 What this order does not build

The parity gaps that the parts keep on purpose stay open after the last step: the live printer view, spools and
Add spools on the Hub page (feature ideas B1, B2, B7); a Hub summary in the web app and the app (B4); Find Klipper
printers and adding a Filament Catalog entry in the web app (B3, B8); licences outside the app (B9). The other ideas
of `10-feature-ideas.md` are not scheduled here either.
