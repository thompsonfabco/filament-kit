# Spoolwarden design: feature ideas

Suggested new features and additions for Spoolwarden, each with what the person sees, why it is worth doing,
which interfaces get it, what the Hub must offer, a rough effort and the open questions. Nothing here is
required for the new look: the redesign in `01-foundations.md` and the documents beside it stands without any of
these ideas. Where an idea touches something the foundations already settle, it refers to the section and does
not restate it.

Contents: 1 Summary · 2 How to read an idea · 3 Group A: follows from the design · 4 Group B: closing parity
gaps · 5 Group C: ease of use · 6 Group D: quality of life for the Hub · 7 Group E: accessibility and language ·
8 Left out, and already in the redesign · 9 Needs from the Hub

---

## 1. Summary

### 1.1 All ideas

Ordered by group, and inside each group by value for effort (most worth doing first).

| ID | Idea | Group | Effort | Value |
|---|---|---|---|---|
| A1 | Welcome checklist on the Hub page | A design | S | high |
| A2 | Short links and "Copy link" | A design | S | medium |
| A3 | Shared string catalogue | A design | M | high |
| A4 | Theme for new devices, delivered to every device | A design | S | medium |
| A5 | Quick find | A design | M | medium |
| A6 | The Themes feature | A design | L | medium |
| B1 | Live printer view on the Hub page | B parity | M | high |
| B2 | Spools on the Hub page | B parity | M | high |
| B3 | Find Klipper printers in the web app | B parity | S | medium |
| B4 | The Hub at a glance in the apps (read-only) | B parity | M | high |
| B5 | Spools and printers on the command line | B parity | M | medium |
| B6 | More Slicer presets in the app | B parity | M | medium |
| B7 | Add spools on the Hub page | B parity | M | medium |
| B8 | One form for a filament line, everywhere | B parity | M | medium |
| B9 | About and licences everywhere | B parity | S | low |
| C1 | Running low | C ease | M | high |
| C2 | Undo the last action | C ease | M | high |
| C3 | Add your first printer, guided | C ease | M | high |
| C4 | Search by colour name | C ease | S | medium |
| C5 | Export and import as CSV | C ease | M | medium |
| C6 | Spool label with a QR code | C ease | M | medium |
| C7 | Print alerts: runout, pause, failed job | C ease | L | high |
| C8 | Storage map | C ease | M | medium |
| C9 | Filament used per printer per month | C ease | M | medium |
| C10 | Published JSON shapes for scripts | C ease | M | low |
| C11 | Demo mode | C ease | M | medium |
| C12 | Activity log | C ease | L | medium |
| C13 | What fits this job | C ease | L | medium |
| D1 | Storage use | D Hub | S | high |
| D2 | Quiet hours for updates | D Hub | S | medium |
| D3 | Hub report for a problem | D Hub | S | medium |
| D4 | Backup to a second place | D Hub | M | high |
| D5 | Restore drill | D Hub | M | medium |
| D6 | Health history | D Hub | M | medium |
| E1 | More contrast | E access | M | high |
| E2 | Units and number formats | E access | M | medium |
| E3 | Translations | E access | L | medium |
| E4 | Right-to-left readiness | E access | M | low |

Count: 38 ideas (A 6, B 9, C 13, D 6, E 4). Effort: S 9, M 24, L 5. Ideas that the redesign documents
already specify are not counted here; section 8.2 lists them.

### 1.2 Start with these five

| Order | Idea | Why first |
|---|---|---|
| 1 | **B1** Live printer view on the Hub page | Today the Hub page sends people to the web app in a new tab for the camera, controls, loading and usage. The web app's printer code and endpoints already run on the same address, so the Hub page can reuse them; it closes three parity rows at once with no server work. |
| 2 | **C1** Running low | Needs only data Spoolman already holds (remaining weight per spool) and one threshold setting. It turns the inventory from a record into something that warns before a print fails for lack of filament. |
| 3 | **A1** Welcome checklist | Small (S), and it grows from the existing "Still to do" card. First-run is when people give up; a list that says what is done and what is next keeps them going. |
| 4 | **D1** Storage use | Small (S). A full disk breaks Spoolman and the backups at once, and a small Hub fills up without warning; one Overview row prevents the worst failure the Hub can have. |
| 5 | **D4** Backup to a second place | Backups sit on the same disk as the data they protect. Copying to a folder the person already mounts is a modest job that turns the backups into real protection. |

---

## 2. How to read an idea

Every idea has the same seven parts:

| Part | Holds |
|---|---|
| Heading | ID and name |
| **What the person sees** | One paragraph from the point of view of the person using it |
| **Why** | The problem it solves, with the survey evidence where there is some (survey file and item number) |
| **Interfaces** | A one-row table: what the Hub page, the web app, the app (Android) and the `spoolwarden` command each get. "Not offered" always comes with the one line the interface shows instead (foundations section 3) |
| **Needs from the Hub** | Existing endpoints it uses, and new needs by number (`H1`, `H2`, …) from section 9 |
| **Effort** | S (a day or two), M (about a week), L (several weeks), with the main cost named |
| **Risks and open questions** | What could go wrong and what must be decided before building |

Survey references: `setup-page` = the Hub page survey, `phone-web-app` = the web app survey, `android-app` = the app
survey, `cli` = the command line and feature survey (all in `survey/`). "Parity row" means a row of the parity table
in `survey/cli-and-features.md` section (g).

All visual parts use the tokens of foundations section 4 and the components named in `02-components.md`
(top bar, navigation rail, bottom bar, More sheet, Collection, Detail region, side drawer, dialog, sheet, menu,
toast, segmented choice, spool ring, lock chip, job indicator, status shapes of foundations section 10). No idea
adds a token. An idea that needs a component `02-components.md` does not define says so under its open questions
(C9 and D6).

Endpoints are named as the surveys list them. The few the surveys do not list but the code and the redesign
documents already use carry their source.

Where an idea changes something the redesign documents (`03-hub-page.md` to `06-command-line.md`) already specify,
it names the section and describes only the change; what those documents already specify is not repeated as an
idea (section 8.2).

---

## 3. Group A: follows from the design

### A1 Welcome checklist on the Hub page

**What the person sees.** On a Hub with nothing set up yet, Overview opens on a panel titled "Getting started"
above the status rows. It lists the steps in order, each as one row with its state in words, a one-line reason and
one button that goes there. A done step has the filled circle and "Done"; the next step has the word "Next" in
bold; a later step has the word "Not yet" in `--muted`. "Next" and "Not yet" carry no status shape, because the
triangle and the hollow circle mean "needs a look" and "offline / off" (foundations section 10). The steps:
Make a setup code (only while none exists; the button is the code block with Copy that the "Still to do" card
shows today) · Add a printer · Map its slots · Use a phone (pair the app, or open the web app) · Add your first
spool · Pair Slicer Sync (only with Slicer presets on) · Set the Anthropic API key (only with the Label Reader's
Cloud (Claude) engine on) · Set the web passphrase (only with web access on) · Make a first backup. A first row
"Moving from another computer? Restore its backup" appears while nothing else is done. The step marked Next has the
one filled button (foundations principle 2); the others are quiet buttons. A row turns to Done by itself when the
Hub sees the step happen (a printer exists, a spool was added, a backup exists). "Hide this list" at the panel's
foot hides it; Overview then shows a single quiet line "Getting started: 4 of 7 done · Show". When every step is
done the panel shows "All set" once and then stays hidden.

While the panel shows, it takes the place of the "Still to do" card of `03-hub-page.md` section 4.2: every item of
that card is one of the steps above, so nothing is shown twice. When the panel is hidden or all set, the "Still to
do" card returns exactly as section 4.2 describes it.

```
+ Getting started ------------------------------------------------ 3 of 7 done +
| (*) Done     Add a printer               Workshop X1 is connected            |
| (*) Done     Map its slots               A1-A4 mapped                         |
|     Next     Use a phone                 [ Show the pairing code ]            |
|     Not yet  Add your first spool        [ Open the web app ]                 |
|     Not yet  Make a first backup         [ Back up now ]                      |
+---------------------------------------------------------- Hide this list ----+
```

**Why.** The current Overview has a "Still to do" list that appears only when items exist, has no order and no
progress, and gives way to a flat status table (`setup-page` 4.1); the redesigned card (`03-hub-page.md` 4.2) keeps
that shape. Several first-run steps are not in it at all (mapping slots, first spool, Slicer Sync, first backup). People who meet the Hub for the first time are the ones
least able to work out the order.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| The panel on Overview as above | Not offered: the steps that matter on a phone (pair, add a spool) are its own first screens; the More sheet shows "Getting started on the Hub page: 3 of 7 done" with a link while steps remain | Home shows the same one-line summary with "Open the Hub page" while steps remain | `spoolwarden status` prints a "Getting started" block before the checks while steps remain: one line per step, `done` / `next` / `not yet`, and the command for the next one |

**Needs from the Hub.** Uses `GET /setup/api/overview` and `GET /setup/api/state`. New: H1 (step list with state,
and the hidden flag).

**Effort.** S. Main cost: deciding "done" for each step on the Hub (the data exists; the rules need writing and
testing).

**Risks and open questions.** A Hub restored from a backup must start with the panel hidden. Whether "hidden" is
per Hub or per device: per Hub is proposed (one owner sets up one Hub), stored on the Hub, changed only with the
setup code.

### A2 Short links and "Copy link"

**What the person sees.** The redesign already gives every place an address: the Hub page's of foundations
section 8, the web app's hash forms (`#spools/<id>`, `#printers/<id>`, `#recent/<id>`; `04-web-app.md` 2.4) and the
app's deep links (`spoolwarden://spools/{id}`, `spoolwarden://printers/{id}`, `spoolwarden://recent/{hid}`;
`05-android-app.md` 2.5). This idea adds what ties them together. A spool's detail shows "Copy link" in its menu
on every screen interface; the link is a short one, `https://<hub>/s/<id>` (for example
`https://spoolwarden.example:8710/s/214`), short enough for the QR code on a spool label (C6). Opening it sends the
browser to the web app's `#spools/214`, where the spool sheet offers "Open in the app" when the app is installed.
The command line prints the same addresses.

**Why.** Labels need an address short enough for a small QR code, and a link copied on one device must open on
another. Each interface's own addresses work only inside that interface.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| "Copy link" in a spool's menu (with B2's Spools section; otherwise in quick find results, A5) | "Copy link" in the spool sheet's menu; "Open in the app" on the spool sheet | "Copy link" in the spool screen's menu (`05-android-app.md` 7.2), through the share sheet | `spool show` (B5) and `recent show` end with a line "Open: <address>" |

**Needs from the Hub.** New: H2 (the short link route for spools).

**Effort.** S. Main cost: the short-link route and the "Open in the app" hand-over.

**Risks and open questions.** Android App Links cannot be verified for a `.local` name, so the app uses its own
scheme (05 section 2.5); whether the web app can tell that the app is installed is uncertain (a plain "Open in the
app" link to `spoolwarden://spools/{id}` that does nothing when the app is missing is the fallback). Spool ids must
stay stable across a restore from backup (Spoolman ids do). Short links for printers and records are not needed:
alerts carry the full address (C7).

### A3 Shared string catalogue

**What the person sees.** Nothing new on screen: the same thing is called the same everywhere, in the words of
foundations section 2, and a fixed message reads the same on the Hub page, in the web app, in the app and at the
command line.

**Why.** Words drift today: "Brand" in one place and "Vendor" in another, "Spool g" and "Empty spool g" for the
same value (`phone-web-app` 7.11); the app has every string hard-coded in Kotlin with no `strings.xml`
(`android-app` section 1); the same notices are written five times with different wording (`android-app` 7.8);
the command line's docs and menus differ (`cli` (f) 13). One catalogue fixes this and is the base for E3.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Reads `strings/en.json` (a static file the Hub serves) and fills every label and message from it by key | Same file | `strings.xml` generated from the same file at build time | Reads the same file from its package |

The catalogue is one JSON object per language: keys like `printers.forget.title` and `printers.forget.body`,
values with named placeholders (`"Forget {name}?"`, with the body of `03-hub-page.md` 5.5: `"Spoolwarden stops
connecting to it and deletes its Access Code. To use it again, add it again."`) and plural forms (`{"one": "{n} spool", "other":
"{n} spools"}`). A test fails the build when code uses a key that is missing, or when a key is unused.

**Needs from the Hub.** New: H3 (serve the catalogue; messages the Hub composes itself carry a key and
parameters as well as the English text).

**Effort.** M. Main cost: moving several hundred strings out of four code bases (the surveys count about 105
distinct button labels on the Hub page, about 114 controls in the web app and about 150 in the app).

**Risks and open questions.** Error texts the Hub builds from pieces (printer refusals, status rows) need keys
too, or they stay English-only; this is most of the work in E3. The catalogue must not be cached so hard that a
Hub update shows old words with new screens.

### A4 Theme for new devices, delivered to every device

**What the person sees.** The owner picks a theme once under Settings > Appearance > "Theme for new devices"
(foundations section 6.2). A phone or computer that has never chosen a theme opens the Hub page, the web app and the
app in that theme. A device that chose one keeps its choice.

**Why.** Foundations section 6.2 defines the setting and the command; this idea is the delivery: the web app at
the public address and the app need to learn the value, and nothing carries it today.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| The setting (foundations 6.2); the page shell carries the default as `data-look` so there is no flash | Page shell carries the default the same way, at home and at the public address | Reads the default when it connects; uses it until the person chooses | `spoolwarden config theme <name>` (foundations 6.2) |

**Needs from the Hub.** New: H4 (the default in the page shells and in `GET /api/info`).

**Effort.** S. Main cost: the app reading and storing the default without overriding a choice.

**Risks and open questions.** None of weight. A device that cleared its storage falls back to the default again,
which is the intended behaviour.

### A5 Quick find

**What the person sees.** On the Hub page, pressing `/` or Ctrl+K (Cmd+K on a Mac), or the search icon in the
top bar, opens a dialog with one search field. Typing "dry" shows, grouped: Settings > Storage locations; spools
in "Dry box 1"; the Recently added record of a spool whose name holds "dry". Typing "x1" shows the printer Workshop X1
and its actions (Map slots, Collect a report). Arrow keys move, Enter opens, Escape closes. The web app and the app
have the same search behind the search icon in their top bars.

**Why.** Console is dense and keeps many things one step away (foundations principle 1); people who keep the
Hub page open beside the printer want to jump, not hunt. The Hub page has ten sections and many settings groups,
and today's Settings is one long page with no in-page navigation (`setup-page` 8.2).

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Dialog as above | Sheet from the top-bar search icon; results limited to spools, printers and Recently added | Search screen from the top bar, same groups | Not offered: `spoolwarden help --find <word>` lists the commands whose help mentions the word (`help <command>` stays as in `06-command-line.md` 3.2) |

**Needs from the Hub.** Uses the spool search of B2 (H5) on the Hub page, the web app's `find` and the app's
`GET /api/spools?q=`, and the lists the pages already load. Sections and settings
are matched in the page from the string catalogue (A3); no new endpoint.

**Effort.** M. Main cost: an index of section and settings names with synonyms ("API key" finds the Label Reader
group).

**Risks and open questions.** Keyboard shortcuts must not fire while typing in a field. `/` is taken by some
screen readers' quick navigation; Ctrl+K stays the documented shortcut and `/` can be switched off.

### A6 The Themes feature

**What the person sees.** Settings > Appearance offers four themes with preview tiles; choosing one changes the
look at once on that device (foundations section 6).

**Why.** Chosen as part of the design: Console is the default and Workbench, Palette and Panes stay available as
themes. This entry records the cost and the parity only; the behaviour, the order of building and the token rules
are foundations sections 6.1 to 6.4.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Four themes, picker in Settings > Appearance | Four themes, picker in its settings sheet | Four themes, picker in Settings | Not offered: the terminal sets the look (foundations section 5) |

**Needs from the Hub.** None beyond A4.

**Effort.** L. Main cost: the three non-default layout profiles (sidebar and cards, pills and tiles and sheets,
list and rows and panes), Panes' drill-in navigation in particular, each on web and Android, and screenshots of
every theme in light and dark at three widths for review.

**Risks and open questions.** Every later feature must be checked in four themes; a test that renders each new
view in all four and fails on horizontal scroll or on a contrast drop keeps this affordable.

---

## 4. Group B: closing parity gaps

Foundations section 3 says a feature offered in one interface is offered in all four where the device can do it.
The parity table in the survey shows where that is not yet true. Each idea below closes one or more rows; section
4.10 lists every row marked N or P and what happens to it.

### B1 Live printer view on the Hub page

**What the person sees.** On the Hub page, opening a printer in Printers shows, in its Detail region, what the
web app's Printers tab shows today: state, job, progress, temperatures, alerts, the camera (behind "Show camera"),
Pause / Resume, Stop print (asks first), the light, each AMS unit with its slots and their spools, Load and Unload,
and "Filament used" with Undo per entry. The link "Open the live printer view" in a new tab goes away.

**Why.** Parity rows "Live printer status, camera, pause/resume/stop, light" (Hub page P), "Load / unload spool into
slot" (Hub page N) and "Filament usage log with undo" (Hub page P). Today the Hub page only links out to the web app
(`setup-page` 4.3, card "Live printer view"), so a person at the computer works in two pages.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| In the printer's Detail region, as above | Exists | Exists | See B5 (`printer show --watch`, `printer load`, `unload`, `usage`) |

**Needs from the Hub.** When the Hub serves the web app, both pages share one address and port, so the Hub page
calls the web app's existing printer endpoints: `GET /intake/api/printers/{id}/events` (status stream),
`POST …/command`, `GET …/usage?days=`, `POST …/usage/{entry}/undo`, `POST …/slots/{label}/load` and `…/unload`,
`GET /intake/api/printers/tagged`, `GET /intake/api/find`, `GET …/camera.mjpeg` and `…/camera/{name}`. Nothing new.

**Effort.** M. Main cost: moving the web app's printer code (`printers.js`) into shared components both pages
load, and the Console table layout for slots.

**Risks and open questions.** The Hub page asks the setup code for every change; the web app's printer controls
do not (the home network is the gate). Proposed: printer controls on the Hub page follow the web app's rule, since
the same person can do the same thing from the web app on the same network; Stop print still asks first. The
Hub's limits on open camera views (4) and status streams (12) now count Hub page tabs too.

### B2 Spools on the Hub page

**What the person sees.** A Spools section on the Hub page lists every spool as a Collection: swatch with colour
name, brand and name, material, remaining grams with a small spool ring (`02-components.md` 7.4), location, sealed
or opened, tagged or not. A search field filters as the person types (brand, name, material, colour, location,
spool number); chips filter by Sealed, Opened, In a printer, Running low (C1). Opening a spool shows its Detail
region: the facts, where it is, its tag, the last filament taken off it, and the actions "Update weight", "Move",
"Link the last tapped tag" and, apart, "Mark empty" (asks first). Each action shows its result next to the button.
The web app's Spools destination (`04-web-app.md` section 5) and the app's (`05-android-app.md` section 7) already
do this on phones; they gain only the chips of C1 and the colour names of C4.

```
Spools                                           [ search: petg            ]
[Sealed] [Opened] [In a printer] [Running low]                    214 spools
 NO.  COLOUR        SPOOL                     LEFT          WHERE
 212  [#] Orange    Bambu Lab PETG HF         880 g  (o)    Workshop X1 - AMS A2
 213  [#] Orange    Bambu Lab PETG HF        1000 g  (O)    Shelf B (sealed)
```

**Why.** Parity row "Search spools" is N on the Hub page, and row "Open / link NFC tag, set weight, move, mark
empty" is N on the Hub page. After the redesign the web app and the app both answer "do I have it, and where is
it?"; the Hub page, where the inventory is set up, is the one place that cannot.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| A Spools section as above (see open questions) | Exists (`04-web-app.md` section 5); gains the chips and colour names | Exists (`05-android-app.md` section 7); gains the chips and colour names | See B5 |

**Needs from the Hub.** The web app uses `GET /intake/api/find?q=&sealed=` and `POST /intake/api/open`, with the
spool editing that `04-web-app.md` section 14 asks for. The app uses `GET /api/spools?q=&sealed=`,
`PATCH /api/spools/{id}` (weight, move, empty, each with a dry run) and `POST /api/spools/{id}/link`. New: H5 (the
same search, detail and changes for the Hub page). This is server work as well as a page.

**Effort.** M. Main cost: the Hub page endpoints of H5 and the Collection and Detail region, with paging past 50
rows (foundations section 12 rule 7).

**Risks and open questions.** **This adds a section to the Hub page's navigation**, which foundations section 8
fixes at ten. Building B2 means amending foundations section 8 first: the proposed place is Everyday, after
Printers, and on phones inside the More sheet so the bottom bar stays as it is. Whether changes on the Hub page
need the setup code is the same question as in B1.

Without that amendment there is no Spools section, and the Hub page parts of other ideas go here instead:

| Idea | Hub page place without a Spools section |
|---|---|
| A2 "Copy link", A5 and C4 spool results | A spool opened from quick find (A5) shows its detail in the side drawer over the current section; quick find needs H5's search either way |
| C1 Running low | The Overview row and its list only; no chip |
| C5 Export and import | "Download spools as CSV" and "Import from CSV" in the Recently added section's header menu, beside B7's "Add spools" |
| C6 Spool label | "Print a label" on a spool opened from quick find, and "Print labels for these spools" on a Recently added record |
| C8 Storage map | Settings > Storage locations gains "Show what is where", which opens the map in the side drawer |
| C9 Sort by use | Not offered on the Hub page; the Overview line and the printer's "Use by month" stay |

### B3 Find Klipper printers in the web app

**What the person sees.** In the web app's Printers, the "Add" menu (`04-web-app.md` 6.9) gains "Find Klipper
printers": a sheet with "Network to search (optional)" (placeholder "e.g. 192.0.2.0/24") and "Search". Results are
rows "192.0.2.57:7125" with "Add", which opens the "Add a Klipper printer" sheet (04 section 12.2) with the address
filled in. It is the same search the Hub page and the app offer.

**Why.** Parity row "Scan for Klipper printers" is P in the web app: it adds Klipper printers by address only. The
app's side of this row and of "Add Klipper printer" is closed by `05-android-app.md` 9.3.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Exists | New as above | Exists (`05-android-app.md` 9.3) | Exists (`printer scan`, `printer use`) |

**Needs from the Hub.** The app's scan is `POST /api/printers/scan` with `{subnet?}` (not in the surveys; in the code
at `api.py:650`, used by `05-android-app.md` 9.3). The web app needs H6 for the scan.

**Effort.** S. Main cost: the sheet and the relay of the scan for the web app.

**Risks and open questions.** Scans are limited to one private /24 at a time, 30 s apart; the web app must say so in
words when refused.

### B4 The Hub at a glance in the apps (read-only)

**What the person sees.** The app gets a "Hub" screen (from Settings > Hub connection, `05-android-app.md` 12.3,
and from the connection line on Home); the web app gets the same in its More sheet. It shows, read-only: the status rows of Overview with their states (OK,
needs a look, note) and fix lines; which Features are on; the Setup; the installed and latest version and when it
was last checked; the Filament Catalog version; the last backup and whether nightly backups run; the Label Reader
key set or not set (never the key); the paired devices with this one marked; the Recently added setting "Records
kept" (`03-hub-page.md` 10.5). Each group ends with one line "Change this on the Hub page" and the button "Open the
Hub page".

**Why.** The app shows only a connection dot (parity row "Server status / health checks", app P, web app N). The
redesigned app shows its own and the Hub's version and checks for app updates (`05-android-app.md` 12.3, 12.4),
but nothing else about the Hub. Many rows (Features, Setup, backups, updates, the Label Reader key, Filament
Catalog, Records kept, devices) are N in the apps; most should stay changeable only on the Hub page and at the
command line, but people want to see them where they are.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Exists (the source of all of it) | More sheet > Hub, read-only; at the public address it shows "Only at home" | Hub screen, read-only | Exists (`status`, `features`, `update --check`, `catalog status`, `backup list`, `devices`) |

**Needs from the Hub.** At home the web app reads the Hub page's view endpoints on the same address
(`GET /setup/api/overview`, `GET /setup/api/updates`, `GET /setup/api/library`, `GET /setup/api/settings/general`),
which answer without the setup code and hide addresses and serials. The app needs H7.

**Effort.** M. Main cost: the read-only summary for paired devices on the Hub, with the same redaction as Overview.

**Risks and open questions.** `GET /setup/api/state` still lists serials and addresses without the code
(`known-gaps.md` item 16); the web app must not use it. A device list on a phone shows other people's device names;
proposed: names only, no addresses.

### B5 Spools and printers on the command line

**What the person sees.** `06-command-line.md` already lists, renames, readdresses and forgets printers, shows
logs and sets the catalog token. What it cannot do it names in its section 10, where `spool` and `printer live`
print the address of the web app instead. This idea turns those pointers into real commands, each printing in the
order and words of the other interfaces:

| Command | Does |
|---|---|
| `spoolwarden spool find <words> [--sealed]` | Lists matching spools: number, brand and name, material, grams left, location |
| `spoolwarden spool show <id>` | One spool, all facts, and its address (A2) |
| `spoolwarden spool weigh <id> <grams>` | Records a scale reading with spool; prints "Remaining would change from 640 g to 512 g. Apply? [y/N]" |
| `spoolwarden spool move <id> <location>` | Moves it; an unknown location lists the known ones |
| `spoolwarden spool empty <id>` | Asks "Mark Bambu Lab PETG HF Orange (212) empty? [y/N]" |
| `spoolwarden spool link <id> [--tag <uid>]` | Links the last tapped tag, or the given one |
| `spoolwarden printer show <printer> --watch` | `printer show` (06 section 9.2) with state, job, progress and temperatures, redrawn every 2 s until Ctrl-C |
| `spoolwarden printer load <printer> <slot> <spool>` | Shows the dry run lines, asks, loads |
| `spoolwarden printer unload <printer> <slot>` | Shows where the spool goes back, asks, unloads |
| `spoolwarden printer usage <printer> [--days 7]` | The filament used list |
| `spoolwarden printer usage <printer> --undo <entry>` | Puts the grams back; asks first |

`spool` with no further word keeps printing the line of 06 section 10, now limited to what still needs a phone
(adding spools from photos, reading a tag with NFC). `printer live` keeps printing where the camera and print
controls are. `<printer>` is matched as in 06 section 5; confirmations, `--yes`, exit codes and `--json` follow 06
sections 6.7, 6.8 and 7.

**Why.** Parity rows "Search spools", "Open / link NFC tag, set weight, move, mark empty", "Live printer status…",
"Load / unload spool into slot" and "Filament usage log with undo" are N at the command line, and stay N in the
command-line design (06 section 12). A person at the Hub's terminal, or a script, has no way to look a spool up.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Exists | Exists | Exists | New as above |

**Needs from the Hub.** None new: with the Hub running, the command calls the existing `/api/printers/…` and
`/api/spools…` endpoints.

**Effort.** M. Main cost: output formatting and tests for about ten commands, in the conventions of 06 section 6.

**Risks and open questions.** The new words must not clash with the `printer` commands of 06 section 3.2; `load`,
`unload` and `usage` are free there, and `--watch` is a new option of `show`. `spool link` without `--tag` needs a
tag tapped on a reader shortly before.

### B6 More Slicer presets in the app

**What the person sees.** The app's Slicer presets screen (`05-android-app.md` 11.2) already shows the last build,
whether it is installed on the PC, and "Add a line to the Filament Catalog". In place of its last line ("Attach
filaments to lines and build presets now on the Hub page or in the web app.") it gains: "Filaments without a preset
line" with "Add to the line" or "New line" (name, parents for Orca Slicer and Bambu Studio), "Build presets now",
and a line "3 updates waiting. Accept them on the Hub page." with "Open the Hub page".

**Why.** Parity rows "Presets: view status, change parent" (app P) and "Presets: build now, restore deleted, apply
updates" (app N, web app N). The web app already lets a phone attach new filaments to a line and build (`phone-web-app`
3.3); the redesigned app still sends the person elsewhere for it.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Exists | Exists; gains the "updates waiting" line | The Slicer presets screen gains the actions above | Exists (`presets …`, 06 section 9.5) |

Accepting updates and restoring deleted presets stay on the Hub page and at the command line: both rewrite files on
the PC and are judged from a list of changed settings that needs a wide screen.

**Needs from the Hub.** Uses `GET /api/profiles/status`, `GET /api/profiles/parents` and `GET /api/profiles/lines`
(the last not in the surveys; in the code at `profiles_api.py:445`); new: H8 (adding to a line, a new line and
"build now" for paired phones).

**Effort.** M. Main cost: the line picker and the new-line form in Compose.

**Risks and open questions.** Whether paired phones may start a build is a choice for the Hub (a build is cheap and
safe; proposed yes).

### B7 Add spools on the Hub page

**What the person sees.** Recently added on the Hub page gets the filled button "Add spools". It opens a side
drawer with the same steps as the web app: find an existing filament or type a new one, or drop label photos onto
the drawer (or choose files, up to 8), "Read labels", review each spool, "Check" and then "Add 3 spools". The new
record appears at the top of Recently added.

**Why.** Parity rows "Add spools by hand" and "Add spools from label photos" are N on the Hub page. People who
keep label or order photos on the computer have no way in except a phone.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| New as above | Exists | Exists | In bulk through C5 import; photos are not offered ("Read labels on the Hub page or a phone") |

**Needs from the Hub.** The Hub page calls the web app's endpoints on the same address: `GET /intake/api/filaments?q=`,
`GET /intake/api/vendors`, `POST /intake/api/read`, `POST /intake/api/add` (dry run, then real). Nothing new.

**Effort.** M. Main cost: making the web app's add flow a shared component that fits the 420 px side drawer.

**Risks and open questions.** Same setup-code question as B1. Photos from a computer can be large; the page
resizes them before upload as the web app does (longest side 1568 px). The drawer keeps an unfinished add across a
reload the way the web app does (`04-web-app.md` 4.7), under its own `localStorage` key `spoolwarden.draft.hub-add`
so the two pages do not take each other's draft.

### B8 One form for a filament line, everywhere

**What the person sees.** "Add a line to the Filament Catalog" is the app's short form (`05-android-app.md`
section 8): brand, product line, material (required), nozzle and bed ranges, density, maximum volumetric speed,
Bambu Studio parent, notes. The Hub page and the web app get the same form. Saving says "Saved. Slicer presets are
rebuilt in a minute." On the Hub page it sits in Settings > Filament Catalog and replaces the JSON text box, which
moves behind "Paste a catalog entry instead".

**Why.** Parity row "Add profile (filament line)" is Y only in the app; the Hub page asks for raw JSON (`setup-page`
4.7, card "Filament library") and the web app has no way to add a line.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Form in Settings > Filament Catalog | Form under Slicer presets | Exists (`05-android-app.md` section 8) | Exists (`catalog add <file \| ->`, 06 section 3.2); gains `catalog add --ask`, which asks field by field |

**Needs from the Hub.** The app uses `POST /api/library/local`; the Hub page builds the same entry in the page and
sends it to `POST /setup/api/library/add`. The web app needs H9.

**Effort.** M. Main cost: one set of field rules shared by three forms (the Hub's own check stays the authority).

**Risks and open questions.** The field list must follow the Filament Catalog's schema as it grows; generating the
forms from the schema is better than three hand-written copies.

### B9 About and licences everywhere

**What the person sees.** An About group on the Hub page and in the web app's settings sheet shows the version of
the Hub, "Spoolwarden is free software under GPL-3.0-or-later. It comes with no warranty.", "Show the licence", and
the list of third-party software with their licences, as the app's Licences screen already does
(`05-android-app.md` 12.5). On the Hub page this adds a tenth group, Settings > About, after the nine of
`03-hub-page.md` section 10.

**Why.** Parity row "Licences screen" is Y only in the app. Foundations section 12 rule 1 requires every bundled
part to be in `THIRD-PARTY.md`; showing it is the other half.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Settings > About (a new, tenth group) | Settings sheet > About | Exists (Licences, `05-android-app.md` 12.5; versions in 12.3 and 12.4) | `spoolwarden about` prints versions, the licence line and where `THIRD-PARTY.md` is |

**Needs from the Hub.** New: H10 (serve the licence and third-party files).

**Effort.** S. Main cost: rendering the third-party Markdown as plain blocks.

**Risks and open questions.** None of weight.

### 4.10 Parity coverage

Every row of the parity table with an N or P cell, and what happens to it. "Left" names a gap that stays on
purpose, with the one line the interface shows instead (foundations section 3). "Closed by" names a redesign
document that already specifies the missing part. Row labels are the survey's own; labels that still use an old
name are in backticks.

| Parity row | N or P cells | Addressed by, or left |
|---|---|---|
| List / remove paired devices | web app N | B4 shows the list read-only. Left: removing a device stays on the Hub page and command line ("Remove devices on the Hub page"). |
| Server status / health checks | app P, web app N | B4 |
| Add spools by hand | Hub page N, command line N | B7 (Hub page); C5 import (command line, in bulk) |
| Add spools from label photos | Hub page N, command line N | B7 (Hub page). Left at the command line: photos are taken on a phone or uploaded on the Hub page. |
| Open / link NFC tag, set weight, move, mark empty | Hub page N, command line N | B2, B5 |
| Search spools | Hub page N, web app N, command line N | Hub page: B2. Web app: closed by `04-web-app.md` section 5. Command line: B5. |
| `Add profile (filament line)` | Hub page N, web app N, command line N | B8 (the command line's `catalog add` already takes an entry; B8 adds `--ask`) |
| Presets: view status, change parent | app P | B6 |
| Presets: build now, restore deleted, apply updates | app N, web app N | B6 for build now and the count of waiting updates. Left: accepting updates and restoring deleted presets ("Accept them on the Hub page"). |
| `Intake history list / show` | app N | Closed by `05-android-app.md` section 10 (Recently added). |
| `Intake revise with AI, edit by hand, undo` | app N | Closed by `05-android-app.md` section 10. |
| `Intake records kept setting` | app N, web app N | B4 shows Records kept. Left: changing it ("Change this on the Hub page"). |
| Add Klipper printer | app N | Closed by `05-android-app.md` 9.3. |
| Scan for Klipper printers | app N, web app P | App: closed by `05-android-app.md` 9.3. Web app: B3. |
| Rename / readdress / re-key / unpin / forget printer | command line P | Closed by `06-command-line.md` 3.2 (one `printer` command each). |
| Live printer status, camera, pause/resume/stop, light | Hub page P, command line N | B1; B5 (`printer show --watch`). Left at the command line: camera and print controls ("Use the Hub page or a phone"). |
| Load / unload spool into slot | Hub page N, command line N | B1, B5 |
| Filament usage log with undo | Hub page P, command line N | B1, B5 |
| `Modules on/off` (Features) | app N, web app N | B4 shows them. Left: switching Features ("Change this on the Hub page"). |
| `Install mode set` (Setup) | app N, web app N | B4 shows it. Left: changing the Setup. |
| Backup now / list / download | app N, web app N | B4 shows the last backup. Left: making and downloading backups (the zip holds every secret). |
| Restore from backup | app N, web app N | Left: a restore replaces the Hub's data and runs as a job on the Hub. |
| Update: check / install / rollback | app P, web app N | B4 shows the Hub's versions; the app's own update check is `05-android-app.md` 12.4. Left: installing Hub updates and rolling back. |
| Anthropic key set/check/remove | app N, web app N | B4 shows set or not set. Left: secrets are typed on the Hub page or at the command line only. |
| `Web passphrase / library token` | app N, web app N, command line P | Command line: closed by `06-command-line.md` 3.2 (`catalog token`). Left in the apps: secrets. |
| Setup code show / new / revoke trusted computers | app N, web app N | Left: the setup code is shown at the Hub's own terminal on purpose. |
| `Station: pair, flash panel, pairing requests` | app N, web app N | Left: pairing approval needs the setup code; a phone cannot flash over USB ("Do this on the Hub page"). |
| Reader tokens (list / make / revoke) | app N, web app N | Left: a token is a secret for a Tag Reader, made on the Hub page or command line. |
| `Printer Station / bench reader setup (flash)` | app N, Hub page N, web app N | Hub page: the Flash a device section is already in the design (foundations section 8). Left in the apps: a phone cannot flash over USB. |
| `Library status / update / rollback / add` | app N, web app N | B4 shows the Filament Catalog version; B8 adds entries. Left: updating and rolling back the Filament Catalog. |
| Logs | app N, web app N, command line P | Command line: closed by `06-command-line.md` 9.14 (`logs`); D3 adds the Hub report. Left in the apps: logs hold addresses and serials and are long. |
| Remote access cert + firewall rules | app N, web app N | Left: needs the Hub page or the Hub's terminal, and the router. |
| Migrate from filament-ops / scanner | app N, Hub page N, web app N | Left: a one-time move, command line only. |
| Uninstall / purge | app N, Hub page N, web app N | Left: command line only; the Hub page's Updates section keeps its one-line pointer. |
| Ensure Spoolman extra fields | app N, web app N | B4 shows the status row and its fix. Left: the action stays on the Hub page and command line. |
| Licences screen | Hub page N, web app N, command line N | B9 |

---

## 5. Group C: ease of use

### C1 Running low

**What the person sees.** Overview shows a row "Running low: 3 filaments" with a triangle and the words "Running low";
opening it lists each filament whose spools together hold less than the threshold, or of which fewer sealed spools
are left than the person wants to keep: swatch and colour name, brand and name, material, grams left in total,
sealed spools left, where the open spool is, and when it was last used. The same list is the "Running low" chip of
the Spools places (B2). A spool loaded in a printer shows "Running low" beside its slot when it falls under the threshold. Settings > Storage
locations gains "Running low": "Warn under [150] g" (default for every filament), an optional value per material,
and on any filament's detail "Keep at least [1] sealed spool". Nothing is ordered or sent anywhere; it is a list.

```
Running low                                                        3 filaments
[#] Charcoal Black  Polymaker PolyTerra PLA   112 g left  0 sealed  Workshop X1 - AMS A1
[#] Galaxy Silver   Prusament PLA             140 g left  0 sealed  Garage Voron - T0
[#] Blue            Overture TPU              310 g left  0 sealed  keep 1 sealed
```

**Why.** The inventory knows remaining weight for every spool, but no interface turns that into a warning; people
find out when a print runs out. Spoolman already holds the numbers, so this is the cheapest way to make the
inventory useful every day.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Overview row and list; the chip in Spools (B2; without it, the Overview list only); the settings | Spools (`04-web-app.md` section 5) shows a line "Running low: 3" above the search that opens the list, and the chip | Home shows the same line; Spools (`05-android-app.md` 7.1) gains the chip | `spoolwarden spool low` prints the list; `status` prints one info line "running low: 3 filaments" |

**Needs from the Hub.** New: H11 (the thresholds and the list).

**Effort.** M. Main cost: the rule on the Hub (sum per filament, sealed count, per-material defaults) and the
settings form.

**Risks and open questions.** Remaining weight is only as right as the last weighing; a spool never weighed after
opening counts as full. Whether a spool in a printer counts toward the filament's total (proposed: yes) and whether
used-up spools marked empty count (no).

### C2 Undo the last action

**What the person sees.** After an action that changes the inventory or a printer's slot, a toast says what
happened and offers "Undo" for 10 seconds: "Moved Bambu Lab PETG HF Orange (212) to Shelf B. Undo". Undo puts back
the previous values exactly and says "Put back." Actions with undo: update weight, move, mark empty, link a tag,
load or unload a slot, save changes to a Recently added record, accept an AI correction. Actions that delete a
secret or a printer (Forget printer, Remove the Label Reader key) still ask first and have no undo. Undo does not
replace the question before a destructive action (foundations section 1, principle 2); it adds a way back after
ordinary ones.

**Why.** Today undo exists in two places only (filament used, and Recently added revisions) and each looks
different. The web app shows results as raw text blocks away from the control (`phone-web-app` 7.2, 7.6), so a wrong
move is easy to miss and hard to reverse; the app's spool card closes on an outside tap and loses typed weights
(`android-app` 7.5).

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Toast with Undo | Toast with Undo | Snackbar-style toast with Undo (the app's mapping of the toast component) | `spoolwarden undo` shows the last change made from this command line and asks "Undo it? [y/N]" |

**Needs from the Hub.** Uses the existing undo of filament used (`POST /api/usage/{entry_id}/undo`) and of
Recently added (`…/history/{hid}/undo`). New: H12 (undo for spool changes and slot loads).

**Effort.** M. Main cost: the Hub keeping the before-values of each change and refusing an undo when the spool
changed again since.

**Risks and open questions.** Undo of a slot load can only put the inventory back; the printer's own slot setting
may already have changed. The toast must stay until dismissed when a screen reader is running or the person has
asked for no time limits (`07-accessibility.md`).

### C3 Add your first printer, guided

**What the person sees.** "Add a printer" in the empty Printers place (and in A1) opens a guided flow, one step at
a time. 1. "Which printer?" Bambu Lab or Klipper, with the printers already found on the network listed first ("Found
on your network: Bambu Lab X1 Carbon at 192.0.2.40"). 2. Bambu Lab: "Type its Access Code. On the printer: Settings >
Network/LAN > Access Code", with the path shown for the chosen model, and a note when LAN mode or Developer mode is
needed. Klipper: address, port, optional API key. 3. The Hub tests the connection at once and says the result in
words, with what to do on failure. 4. "Map its slots now?" with one sentence on what mapping does (no heating, no
motion) and "Map slots" or "Later". 5. "Load a spool?" (optional) hands over to the load flow. Each step can go Back.

**Why.** Adding a printer is the first hard step: the Access Code's place differs per model, the Hub page shows up
to eleven equal buttons per printer once added (`setup-page` 8.3), the web app asks for the Access Code in a native
browser prompt (`phone-web-app` 7.4), and the command line mixes two number lists on one screen (`cli` (f) 5).

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Side drawer with the steps | Sheet with the steps (replaces the add sheets of `04-web-app.md` 6.9) | Full screen with the steps (replaces the dialogs of `05-android-app.md` 9.2 and 9.3) | `spoolwarden printer add` (`06-command-line.md` 3.2) asks the same questions in the same order, tests, then offers to map |

**Needs from the Hub.** Uses `POST /setup/api/printers`, `POST /setup/api/printers/klipper`,
`POST /setup/api/printers/scan`, `POST /setup/api/printers/{serial}/test` and `…/map`; for phones `POST /api/printers`
(with `family: "klipper"` for Klipper; not in the surveys, in the code at `api.py:402-406`), `POST /api/printers/scan`
(`api.py:650`) and `/api/printers/{id}/map`, as `05-android-app.md` section 9 uses them; the web app
`POST /intake/api/printers/add`. New: H13 (the
Access Code hint per model from the printer hardware data).

**Effort.** M. Main cost: four step-by-step flows and the per-model hints.

**Risks and open questions.** Hints per model must come from data the Hub already ships (the printer hardware
files), not from page code, or they go stale. A printer that needs Developer mode for some features must not look
"failed" when it connects without it.

### C4 Search by colour name

**What the person sees.** Spool search understands colour words: "orange", "dark grey", "silver", "teal" find
spools of those colours even when the name does not contain the word. Results show the swatch with its colour name
(foundations section 4.1: a swatch is always accompanied by its name or hex).

**Why.** People think "the orange PETG", not "#F2762E". Many filament names carry a marketing word ("Galaxy",
"Charcoal") that hides the colour. Colour names also make swatches readable for people who cannot tell colours
apart.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Spools search (B2) and quick find (A5) | Spools search (`04-web-app.md` 5.3) | Spools search (`05-android-app.md` 7.1) | `spool find orange` (B5) |

**Needs from the Hub.** New: H14 (a colour name and family per filament, computed from its hex; a name the Label
Reader read from the label wins over the computed one).

**Effort.** S. Main cost: a fixed list of about 30 colour names with their families and a nearest-colour rule.

**Risks and open questions.** Computed names will sometimes disagree with how a person sees a colour; the
detail shows the hex beside the name so the person can judge. Names are words, so they go through the string
catalogue (A3) for E3.

### C5 Export and import as CSV

**What the person sees.** Spools, filament used and Recently added each have "Download as CSV" in their menu; the
file opens in any spreadsheet. Spools also has "Import from CSV" on the Hub page (without B2's Spools section: in Recently added, see B2): choose a file, the page shows a
table of what it read with problems marked per row, "Check" runs a dry run like Add spools, then "Add 24 spools".
A sample file with the right columns is offered beside the button.

**Why.** People keep their own lists and want to move them in or out without retyping; the parity table has no
way to add spools at the command line (rows "Add spools by hand", command line N), and bulk entry is where a form is
slowest.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Download on Spools (B2), Recently added and the printer's filament used; Import on Spools (without B2: both in Recently added's header menu) | Download only (files land in the phone's downloads) | Download only, through the share sheet | `spoolwarden spool export [--out file]`, `printer usage <printer> --csv` (B5), `spoolwarden spool import <file> [--yes]` (dry run first, asks) |

Columns follow the Add spools fields in their order, with the names of foundations section 2 as headers; numbers
in plain units (grams, °C), dates as `2026-11-12 14:05`.

**Needs from the Hub.** Import reuses the dry run and add of `POST /intake/api/add`. New: H15 (CSV downloads).

**Effort.** M. Main cost: the import's per-row problem display and matching existing filaments.

**Risks and open questions.** CSV from spreadsheets varies (separator, decimal comma, encoding); the import accepts
comma and semicolon and UTF-8 with or without a byte-order mark, and says which it read. Cells that start with `=`,
`+`, `-` or `@` are written with a leading apostrophe on export so spreadsheets do not run them as formulas.

### C6 Spool label with a QR code

**What the person sees.** A spool's menu has "Print a label". A dialog offers a size (62 mm continuous roll, 50 x 30
mm, or a sheet of 24 on A4 or Letter) and shows a preview: brand and name, material, the colour name and hex in
words with a printed colour box, the spool number, nozzle and bed temperatures, and a QR code. "Print" opens the
system print dialog. Scanning the QR code with any phone opens that spool (A2). Several spools can be printed at
once from a selection in Spools (on the Hub page without B2's Spools section: "Print labels for these spools" on a
Recently added record).

```
+------------------------------------------------------+
| Polymaker PolyTerra PLA            [###]  #2B2B2E     |
| Charcoal Black                     Spool 214          |
| PLA · nozzle 190-230 °C · bed 25-60 °C   [QR code]    |
+------------------------------------------------------+
```

**Why.** Spools without an NFC tag, or tags hidden by a dry box, still need a quick way from the physical spool to
its record; a phone camera reads a QR code without any reader hardware.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| "Print a label" on a spool and on a selection in Spools (B2; without it, from quick find and Recently added) | Same; the print dialog of the phone | Same through Android's print service | `spoolwarden spool label <id>… --out labels.pdf` (or `.svg`) |

**Needs from the Hub.** New: H16 (the label as SVG with the QR code drawn by the Hub, which already makes QR codes
for pairing). The short link of A2 (H2) is what the code holds.

**Effort.** M. Main cost: label layouts that print at true size in browsers, and the PDF for the command line.

**Risks and open questions.** The QR code holds the Hub's address; a label taken to another home network points
nowhere useful. The printed colour box is only as faithful as the printer; the name and hex in words carry the
meaning. Label printers with their own drivers are out of scope: the label prints through the system dialog.

### C7 Print alerts: runout, pause, failed job

**What the person sees.** A phone gets a notification when a printer pauses for filament ("Workshop X1 paused: AMS
A2 ran out. Load a spool."), pauses for any other reason the printer gives, fails a job, or (if wanted) finishes
one. Tapping it opens that printer: a Web Push notification carries the full address
`https://<hub>/intake#printers/<id>`, an app notification the deep link `spoolwarden://printers/{id}`
(`05-android-app.md` 2.5). A new "Alerts" group in Settings has one switch per kind and per printer.
On the Hub page, while it is open, the same events appear as toasts and as a line on Overview.

**Why.** The web app already sends Web Push for print alerts, but only through the public address, only after a
separate setting, and with no choice of kinds (`phone-web-app` 3.5, "Alerts"); the app has no notifications at all.
Runout is the moment a person most needs to be told.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Toasts and an Overview line while open | Web Push as today, with per-kind switches | Android notifications, per-kind switches | Not offered: `printer show --watch` (B5) shows the events in the terminal |

**Needs from the Hub.** Uses `GET /intake/api/push/key` and `POST /intake/api/push/subscribe`, `…/unsubscribe`, `…/test`.
New: H17 (events with a kind, printer and reason; per-device choice of kinds; a way for the app to receive them).

**Effort.** L. Main cost: delivery to the app without a cloud push service. An Android app on the home network only
receives events while a connection stays open, which needs a foreground service with its own permanent
notification, or polling every 15 minutes, which is too slow for a runout.

**Risks and open questions.** Which delivery the app uses is the main decision (a switch "Keep a connection to the
Hub for alerts" that starts the foreground service is proposed). Printers report pause reasons differently (Bambu
Lab HMS codes, Klipper macros); the Hub maps them to the few kinds above and says "paused (reason not given)"
otherwise. Web Push from the Hub's home address needs a certificate the browser trusts, which the self-signed Hub
certificate may not be.

### C8 Storage map

**What the person sees.** Spools gets a "Storage" view (on the Hub page without B2's Spools section: Settings >
Storage locations > "Show what is where", in the side drawer): one tile per location (each name from Settings > Storage
locations, each dry box from the box prefix and count, the overflow, and each printer's slots), showing the swatches
of the spools there, how many, the grams in total and, for dry boxes, the last humidity reading with its time ("38 %
· 2 days ago"). Opening a tile lists its spools. "Move here" on a tile's menu moves selected spools in one step.

```
+ Shelf A ---------- 12 + + Dry box 1 ---------- 6 + + Workshop X1 ------- 3 +
| [#][#][#][#][#][#]    | | [#][#][#][#][#][#]     | | A1 [#] A2 [#] A3 [#] |
| 9.4 kg                | | 4.1 kg · 38 % 2 d ago  | | A4 empty             |
+-----------------------+ +------------------------+ +----------------------+
```

**Why.** Locations are already set up (Settings: locations, PLA rack, box prefix, box count, overflow:
`setup-page` 4.7) and humidity is recorded when a spool is opened (`phone-web-app` 3.2), but nothing shows them
together, so the question "what is in dry box 2" has no answer short of a search per spool.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Spools > Storage (B2; without it, Settings > Storage locations > "Show what is where") | Spools > Storage | Spools gains a "By place" view | `spoolwarden spool where` prints each location with its count and grams |

**Needs from the Hub.** New: H18 (spools grouped by location, with the last humidity per dry box).

**Effort.** M. Main cost: grouping printer slot locations ("Workshop X1 – AMS A2") with their printer.

**Risks and open questions.** Humidity is only recorded when someone types it at opening, so it goes stale; the
time beside it says how stale. A Weigh Station hygrometer or a dry-box sensor feeding readings is a later idea.

### C9 Filament used per printer per month

**What the person sees.** Overview shows "Filament used this month: 1.84 kg" with last month beside it. A printer's
detail gains "Use by month": a bar per month for the last 12 months with the grams written above each bar, and a
table view of the same numbers (month, grams, prints, most used material) behind "Show as table". Spools can be
sorted by "Used this month" (on the Hub page only with B2's Spools section).

**Why.** Filament used is logged per print, but the logs are shown for 7 days only and nowhere added up
(`android-app` 4.11, "Filament used (last 7 days)"). Monthly totals help people reorder and see which printer
does the work.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Overview line; printer detail chart and table | Printer detail: the table, and the bars at tablet width | Printer screen: the table and bars | `spoolwarden usage [--by month] [--printer <printer>]` |

Bars are drawn by the page's own code as inline SVG in `--accent`, with the value in words above each bar and the
table one tap away; no chart library.

**Needs from the Hub.** Uses `GET /api/printers/{id}/usage?days=`. New: H19 (totals per month and a usage record
kept for at least 13 months).

**Effort.** M. Main cost: totals on the Hub and the chart component with its table twin.

**Risks and open questions.** Usage is only taken off spools once slots are mapped; totals must count logged-only
entries too and say so. How long usage entries are kept today is not documented; if they are pruned, totals start
from the day this ships. **Needs a new component:** a bar chart with its table twin, which `02-components.md`
does not define yet; it is added there before this idea is built.

### C10 Published JSON shapes for scripts

**What the person sees.** `--json`, `--quiet`, the error object and the exit codes are as `06-command-line.md`
sections 6.7 and 6.8 define them, for every command. This idea adds a written promise about the shapes: the user
guide gets one page per command that prints data, listing each field of its `--json` output with its type and
meaning, and `spoolwarden help <command> --json-schema` prints the same as a JSON Schema. The output itself is
unchanged: no extra field is added to it.

**Why.** 06 section 6.8 takes the field names from the Hub's own replies, so a change on the Hub changes what a
script reads, with nothing to warn the person who wrote the script. The status text was the only interface for
scripts until now, and other code parses its marks (`cli` (f) 8).

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Not offered (the Hub page's own endpoints already speak JSON) | Not offered | Not offered | The schema pages and `help <command> --json-schema` for `status`, `printer list`, `printer show`, `spool find`, `spool show` (B5), `backup list`, `devices`, `presets status`, `catalog status`, `recent` |

**Needs from the Hub.** None.

**Effort.** M. Main cost: writing a schema per command and a test that fails when a command's output no longer
matches its schema.

**Risks and open questions.** Once published, the shapes are a promise. A shape that must change keeps the old
fields for one release and the release notes say so; the schema's own `$id` carries its version, so the output
needs no version field.

### C11 Demo mode

**What the person sees.** "Try it with example data" on the Hub page's welcome checklist (A1) and in Settings >
About (B9) turns on demo mode: every interface shows the example data of `mockups/CONTENT-SPEC.md` (three printers, a
found Klipper printer, five Recently added records, storage locations, backups) with a global banner (`02-components.md`
8.8, info) at the top of the page: "Demo data. Nothing here is real." and the action "Leave demo". Everything can be clicked: printers print and pause,
mapping runs, spools are added; nothing touches Spoolman or a real printer, and leaving demo mode throws it all away.

**Why.** People want to see Spoolwarden before buying a scale or tags; documentation and theme screenshots need
the same data every time; a person can practise slot mapping or a restore without risk.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| The banner and "Leave demo" | The banner | The banner (`NoticeCard`) | `spoolwarden demo on` / `off`; while on, every command prints "demo data" first |

**Needs from the Hub.** New: H20 (a demo data store and simulated printers behind the same endpoints).

**Effort.** M. Main cost: the simulated printer status stream and mapping.

**Risks and open questions.** Demo mode must never be on by accident on a Hub with real data: it is offered on the
welcome checklist only while no spool and no printer exist, and needs the setup code elsewhere. Every page must show
the banner; a test checks it.

### C12 Activity log

**What the person sees.** The Logs section gains a segmented choice (`02-components.md` 5.7) at its top:
"Activity" and "Service logs" (today's logs). Activity is
a table: time, who, what, and a link to the thing. Who is the name of the paired phone, the trusted computer, "the
command line", "the Weigh Station", "the Claude connector" or "the Hub" (automatic jobs). What is a plain sentence:
"Moved Bambu Lab PETG HF Orange (212) to Shelf B", "Turned the Label Reader on", "Forgot printer Study A1 mini".
Filters by who and by kind; 90 days are kept. A spool's detail shows its last ten events.

**Why.** Several people and devices change the same inventory, and nothing records who did what; when a spool is
in the wrong place, no one can tell how it got there. Settings changes, Features and printer removals happen
without trace except in service logs that hold addresses and serials.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Logs > Activity; spool detail | Spool sheet: last ten events | Spool screen (`05-android-app.md` 7.2): last ten events | `spoolwarden activity [--spool <id>] [--days 7]` |

Secrets are never in it: a changed key reads "Replaced the Label Reader key", never the value.

**Needs from the Hub.** New: H21 (an event record written by every change, with the actor).

**Effort.** L. Main cost: every write path in the Hub (about 75 changing endpoints on the Hub page alone, plus the
app's, the web app's and the command line's) must record an event.

**Risks and open questions.** Device names are chosen by people and may be personal; the log stays on the Hub and is
shown only on the home network. Viewing the full Activity tab is proposed to need the setup code, like Service logs.

### C13 What fits this job

**What the person sees.** On the Hub page or in the web app, "What fits this job" (in Printers) takes a project
file exported from Bambu Studio or Orca Slicer (`.3mf`). It lists each filament the project uses (material, colour,
grams when the project was sliced) and beside each the best match: a spool already in a printer slot, or one in
storage, with how close the colour is and whether enough is left ("Needs 212 g, 180 g left: not enough"). Choosing
a printer shows which slots to load, with "Load" per slot using the normal load flow.

**Why.** Before a multi-colour print people check by hand that the right materials and colours are loaded and that
enough is left; a short print that runs out is the most common waste.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Printers > "What fits this job", file chooser or drop | Same, file chooser | Same, through the share sheet ("Share to Spoolwarden" from a file manager) | `spoolwarden fits <file.3mf> [--printer <printer>]` |

**Needs from the Hub.** Uses the load flow (`POST …/slots/{label}/load`). New: H22 (read a project file and match it
to spools).

**Effort.** L. Main cost: reading project files from two slicers in their several versions, and the colour and
material matching.

**Risks and open questions.** Grams are only in a sliced project; an unsliced one gives materials and colours only,
and the page says so. Project files can be large; a size limit and a clear refusal are needed. Matching "close
enough" colours needs a rule the person can see and override.

---

## 6. Group D: quality of life for the Hub

### D1 Storage use

**What the person sees.** Overview gains a status row "Disk: 41 GB free of 120 GB" (OK), which turns to "needs a
look" under 10 % or 2 GB free. Opening it shows what Spoolwarden itself takes: photos of Recently added, backups,
service logs, the Spoolman database, kept releases, and the Label Reader's On this Hub engine when it is installed, each
with its size and the setting that controls it ("Keep fewer records", "Keep backups for fewer days").

**Why.** Recently added photos take 0.5 to 2 MB per record and nightly backups are kept 14 days by default
(`setup-page` 4.7, General and Backups); a small Hub (a single-board computer, or a virtual machine with a small
disk) fills up without warning, and a full disk breaks Spoolman and the backups at once.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Overview row and its breakdown | Through B4 | Through B4 | `spoolwarden status` gains the disk row; `spoolwarden status --disk` prints the breakdown |

**Needs from the Hub.** New: H23 (disk use per category in the Overview data).

**Effort.** S. Main cost: measuring each category without slowing Overview (sizes cached, measured at most every
10 minutes).

**Risks and open questions.** The Spoolman database may live on another machine when Spoolman is external; the row
then says "Spoolman: on another computer" instead of a size.

### D2 Quiet hours for updates

**What the person sees.** Updates gains "Install automatic updates only between [02:00] and [05:00]" under the
automatic update switch, and the line "Never while a printer is printing, mapping slots or loading a spool." An
update that finds a printer busy waits for the next window and says so on the Updates page: "Waiting: Workshop X1 is
printing."

**Why.** An automatic update stops the Hub while it installs; doing it during a print loses the filament-used entry
for that print and interrupts anyone using the web app. Today updates wait only for mapping and loading
(`user-guide.md`, "Update").

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Updates section | Through B4 (shows the window) | Through B4 | `spoolwarden update --window 02:00-05:00`; `update --window off` |

**Needs from the Hub.** New: H24 (the window setting and the printing check for automatic updates).

**Effort.** S. Main cost: the busy check across Bambu Lab and Klipper printers.

**Risks and open questions.** A printer that is offline cannot report that it prints; offline counts as idle. An
update by hand ("Update to 0.6.0") ignores the window but still asks first when a printer prints.

### D3 Hub report for a problem

**What the person sees.** Logs gains "Collect a Hub report", next to the Printer report the Printers section already
offers. It makes one file with the Hub's status rows, versions, Features, Setup, the last 500 lines of each
service's log and the settings, with addresses, serials, names and every secret replaced by placeholders. A line
says what it never holds. "Download" saves it; the page says to attach it to an issue.

**Why.** When something goes wrong people are asked for logs, which hold addresses and serials (`setup-page` 4.9)
and are spread over several services; the printer report shows the pattern already works and is trusted.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Logs > "Collect a Hub report" | Not offered ("Collect a Hub report on the Hub page") | Not offered, same line | `spoolwarden report` writes the file and prints its path |

**Needs from the Hub.** New: H25 (the report job, reusing the redaction of the job log and Overview).

**Effort.** S. Main cost: making the redaction cover settings and every service log.

**Risks and open questions.** Redaction must be tested against real-looking data; anything it misses is published
by the person with the issue. The report is shown before download as a list of what is in it.

### D4 Backup to a second place

**What the person sees.** Settings > Backups and restore gains "Also copy each backup to" with a folder on the Hub (for example a
mounted network share or USB drive at `/mnt/backup`), "Keep [10] copies there", and "Copy now". The backups list
shows a second state per backup: "Copied 2026-11-12 03:02" or "Not copied: the folder is not there". Overview turns
"needs a look" when the last three copies failed.

**Why.** Backups are kept on the same disk as the data they protect (`user-guide.md`, "Backups and restore"); a dead
disk takes both. Mounting a share is something people already know how to do; Spoolwarden only needs to copy to it.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Settings > Backups and restore as above | Through B4 (last copy) | Through B4 | `spoolwarden backup copy-to <folder>`, `backup copy-to off`, `backup copy` |

**Needs from the Hub.** New: H26 (the copy target, the copy step after each backup, its state per backup).

**Effort.** M. Main cost: reliable copying to a folder that may be missing, slow or full, with a clear state.

**Risks and open questions.** The zip holds every secret unencrypted (`setup-page` 4.7, Backups); a second copy on a
shared drive spreads that risk. Optional encryption with a passphrase (then needed to restore) is the open decision.
Copying to a cloud service directly is out of scope; the folder can be one a sync tool watches.

### D5 Restore drill

**What the person sees.** Each backup in Settings > Backups and restore has "Check this backup" in its menu. It runs as a job:
it unpacks the zip into a scratch folder, checks every file against the manifest, opens the Spoolman database
read-only and counts what is in it, then deletes the scratch folder. The result is one line: "This backup restores
214 spools, 3 printers and 4 paired devices. Every file checked." or what is wrong. Nothing on the Hub changes. An
optional "Check the newest backup every month" shows its last result on Overview.

**Why.** A backup that has never been restored is a hope, not a backup. Today the only check happens during a real
restore, after "Type restore to go on" (`setup-page` 4.7, Backups).

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Backup menu "Check this backup"; Overview line | Through B4 (last result) | Through B4 | `spoolwarden backup check <file>` or `backup check --latest` |

**Needs from the Hub.** New: H27 (the check job).

**Effort.** M. Main cost: opening the Spoolman database from the backup without touching the running one.

**Risks and open questions.** The check needs free disk about the size of the backup; it says so and refuses when
D1 shows too little room.

### D6 Health history

**What the person sees.** Overview's status rows each gain a thin strip showing the last 7 days (30 on request):
filled where the check was OK, triangle marks where it needed a look, with times on hover or long-press ("Workshop
X1 offline 2026-11-11 23:10 to 2026-11-12 06:45"). "Show history" lists the changes as a table: time, check, from,
to. Status is never told by the strip's colour alone: every change is a row in the table.

**Why.** "Was the printer offline last night when the print failed?" and "how often does Spoolman drop?" have no
answer today: Overview shows only now (`setup-page` 4.1), and the service logs are long and need the setup code.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Overview strips and "Show history" | Through B4 (the table only) | Through B4 (the table only) | `spoolwarden status --history [--days 7]` prints the changes |

**Needs from the Hub.** New: H28 (status checks recorded every 15 minutes and kept 30 days, as changes only).

**Effort.** M. Main cost: running the checks on a schedule without slowing the Hub, and the strip component.

**Risks and open questions.** Some checks call outside services (the Label Reader key check calls the provider);
those are left out of the schedule or checked at most daily. **Needs a new component:** the history strip, which
`02-components.md` does not define yet (its slot strip, 7.5, is a different thing); it is added there before this
idea is built.

---

## 7. Group E: accessibility and language

### E1 More contrast

**What the person sees.** Settings > Appearance gains a second small control under Light / Dark / System:
"Contrast: Standard · More" (a segmented control). "More" makes secondary text as dark as main text is in
Standard, makes every hairline a visible line, thickens the focus ring and fills selected rows more strongly, in
every theme, light and dark. It also turns on by itself when the device asks for more contrast, and the pages
follow the system's forced colours (Windows high contrast) without losing borders or status shapes.

**Why.** Console is dense and uses muted text and hairlines on purpose (foundations section 1, principle 10); some
people need more. The three Light / Dark / System choices of foundations section 5 stay as they are: contrast is a
separate, per-device choice.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| The control; `prefers-contrast: more` and `forced-colors: active` honoured | Same, in the settings sheet | Settings > Appearance; follows Android's own contrast setting | Not offered: the terminal's own colours apply |

Each theme supplies a "more contrast" token set: `--muted` at 7:1 against `--bg`, `--surface` and `--surface-2`;
`--border` at 3:1 against its ground; `--focus` drawn 3 px wide; `--surface-3` at 3:1 against `--surface`. The
contrast test of foundations section 4.1 runs on these sets too, with the higher targets. The choice is stored per
device beside the appearance (web: `localStorage` key `spoolwarden.contrast`).

**Needs from the Hub.** None.

**Effort.** M. Main cost: a fourth token set per theme (light and dark) and checking every component in forced
colours.

**Risks and open questions.** This adds a control to Settings > Appearance next to the ones foundations sections 5
and 6 place there; adopting it means adding it to that section's description. Whether the focus ring width belongs
in the tokens (it is not a token today) is open.

### E2 Units and number formats

**What the person sees.** Settings gains "Units" per device: weight in grams or ounces, temperature in °C or °F,
length in millimetres or inches (for nozzle sizes). Values are stored in grams and °C on the Hub as now; only the
display changes, and every number keeps its unit in words ("1.1 oz", "410 °F"). Once a language other than English
exists (E3), decimal and thousands separators follow it; dates stay as foundations section 2 says.

**Why.** Part of the audience thinks in ounces and Fahrenheit; spool labels in some markets print both.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Settings > Units (per device; a new group after Appearance, beside the nine of `03-hub-page.md` section 10) | Settings sheet > Units | Settings > Units | `--units imperial` on any command; `spoolwarden config units imperial` (or `metric`) sets the command line's default |

**Needs from the Hub.** None: conversion happens in each interface from one shared table in the string catalogue
(A3).

**Effort.** M. Main cost: finding every place a number with a unit is shown or typed, and converting typed values
back exactly.

**Risks and open questions.** Typed values must convert back without drift (a weight typed in ounces and stored in
grams must show the same ounces again). Temperatures from slicer presets and the Filament Catalog stay in °C in
files; only the display converts.

### E3 Translations

**What the person sees.** Settings gains "Language" per device (default: the device's language when a translation
exists, else English). Every label, message and help line appears in that language on the Hub page, in the web app
and in the app; the command line follows the terminal's `LANG`. Words a translation lacks show in English.

**Why.** Spoolwarden's audience is worldwide; the plain-language rule of foundations section 2 helps people reading
in a second language, but a first-language interface helps more.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| Settings > Language (per device; a new group after Units) | Settings sheet > Language | Settings > Language (and Android's per-app language) | `LANG`; `--lang` to override |

**Needs from the Hub.** H3 (the catalogue, served per language, and messages the Hub composes carrying a key and
parameters).

**Effort.** L. Main cost: the Hub's own messages (status rows, printer refusals, job lines, errors), which are built
from pieces today and must become catalogue keys with parameters; then each language's translation.

**Risks and open questions.** Translations go stale as features ship; a check lists untranslated keys per language
and the page falls back word by word, never crashing. Product names (Spoolwarden, Spoolman, Access Code, Bambu
Studio, Orca Slicer) are not translated. Who maintains each language is a project question, not a code one.

### E4 Right-to-left readiness

**What the person sees.** With a right-to-left language chosen, the pages mirror: navigation on the right, text
aligned right, chevrons and back arrows pointing the other way. Things with a physical or technical order do not
mirror: AMS slot order (A1 to A4), addresses, serials, numbers with units, code blocks and logs stay left to right.

**Why.** Needed before any right-to-left translation (E3) can ship; cheap if done while the components are written,
expensive later.

| Hub page | web app | app | `spoolwarden` command |
|---|---|---|---|
| `dir` from the language; logical CSS properties | Same | `supportsRtl` and start/end padding | Not offered: the terminal handles direction |

**Needs from the Hub.** None.

**Effort.** M. Main cost: using logical properties (`margin-inline-start`, `inset-inline-end`) throughout the
stylesheet and a check that fails the build on physical left/right in component rules.

**Risks and open questions.** Low value until a right-to-left language exists; the cheap part (logical properties
in new code) is worth doing from the start, the rest can wait.

---

## 8. Left out, and already in the redesign

### 8.1 Considered and left out

| Idea | Why left out |
|---|---|
| Bulk add from one photo of several spools | The Label Reader already reads several products from one set of photos ("3 products found"); telling which spool in a shelf photo is which needs object detection and a crop per spool, and wrong guesses are worse than one photo per label. Worth revisiting if the Label Reader's On this Hub engine gains detection. |
| Ordering filament from the Running low list | Shops, accounts and payment are outside a home inventory; C1 gives the list and C5 exports it. |
| Pairing approval for Weigh Stations on a phone | The approval needs the setup code by design; a phone notification "A Weigh Station asks to pair" with "Open the Hub page" is enough and is part of B4's status rows. |
| A separate notification centre | C7's alerts and C12's activity log cover the need without a third place to look. |

### 8.2 Already in the redesign

These close parity gaps or ease problems, but the redesign documents already specify them, so they are not ideas
here and carry no effort of their own. Ideas above that extend them say so.

| What | Where it is specified |
|---|---|
| Recently added in the app: list, record, edit by hand, ask the AI to correct it, undo a revision | `05-android-app.md` section 10 |
| Add a Klipper printer and Find Klipper printers in the app | `05-android-app.md` 9.3 |
| Every printer screen of the app, including Map by loading filament, as a real destination; deep links `spoolwarden://printers/{id}`, `spoolwarden://spools/{id}`, `spoolwarden://recent/{hid}` | `05-android-app.md` 2.5 |
| Add a line to the Filament Catalog in the app (today's "Add profile") | `05-android-app.md` section 8 |
| The app's own update check, its version and the Hub's | `05-android-app.md` 12.3, 12.4 |
| Spools in the web app: search, the spool sheet, update weight, move, mark empty, load into a printer | `04-web-app.md` section 5 |
| The web app's unfinished add kept across a reload, a closed tab or a sleeping phone | `04-web-app.md` 4.7 |
| The web app's addresses `#spools/<id>`, `#printers/<id>`, `#recent/<id>`, with Back and Forward | `04-web-app.md` 2.4 |
| `printer list`, `rename`, `address`, `forget`, `logs`, `catalog token`, `--json`, `--quiet` and exit codes at the command line | `06-command-line.md` 3.2, 6.7, 6.8 |

---

## 9. Needs from the Hub

What the ideas need that the Hub does not offer yet. Names in the "Proposed shape" column are proposals for the
developer of the Hub; they follow the existing path families (`/setup/api/…` for the Hub page, `/intake/api/…` for
the web app, `/api/…` for paired devices).

| Need | For | What the Hub must offer | Proposed shape |
|---|---|---|---|
| H1 | A1 | The getting-started steps with a state each (done, next, not yet) and the hidden flag | `GET /setup/api/overview` gains `start: {hidden, steps: [{id, state, detail}]}`; hiding is a change with the setup code |
| H2 | A2, C6 | A short link to a spool that sends the browser to the web app | `GET /s/<id>` answering with a redirect to `/intake#spools/<id>` |
| H3 | A3, E3 | The string catalogue as static files, and a key and parameters on every message the Hub composes | `/strings/<lang>.json`; error bodies gain `{key, params}` beside `error` |
| H4 | A4 | The default theme in the page shells and for the app | `data-look` on the shells' `<html>`; `GET /api/info` gains `look` |
| H5 | B2, A5 | Spool search, detail and changes for the Hub page, with the rules of the app's endpoints (the web app's own need is `04-web-app.md` section 14) | `GET /setup/api/spools?q=&sealed=`, `GET /setup/api/spools/<id>`, `POST /setup/api/spools/<id>` (weight, move, empty, link, each with a dry run) |
| H6 | B3 | The Klipper scan for the web app | `POST /intake/api/printers/scan` relaying the Hub's scan |
| H7 | B4 | A read-only summary for paired devices: status rows (redacted), Features, Setup, versions, Filament Catalog version, last backup, key set or not, device names, Records kept | `GET /api/hub` |
| H8 | B6 | Adding filaments to a line, a new line and "build now" for paired phones | Paired-device access to the existing line and build actions now under `/api/profiles/web/…` |
| H9 | B8 | Adding a Filament Catalog entry from the web app | `POST /intake/api/library/local` with the checks of `POST /api/library/local` |
| H10 | B9 | The licence and third-party list as files | `/LICENSE` and `/THIRD-PARTY.md` served as text |
| H11 | C1 | Running-low thresholds (default, per material, keep-sealed per filament) and the list | Settings keys `low.grams`, `low.by_material`, filament extra field `keep_sealed`; `GET …/spools/low` in all three path families |
| H12 | C2 | Before-values of each spool change and slot load, and an undo that refuses when the thing changed since | Each change reply gains `undo_token`; `POST …/undo {undo_token}` in all three path families; tokens live 10 minutes |
| H13 | C3 | Where the Access Code is on each printer model, from the printer hardware data | Printer model entries gain `access_code_hint` |
| H14 | C4 | A colour name and family per filament, searchable | Search matches `color_name`, `color_family`; filament objects carry both |
| H15 | C5 | CSV downloads of spools, filament used and Recently added | `GET …/spools.csv`, `…/printers/<id>/usage.csv`, `…/intake/history.csv` |
| H16 | C6 | A spool label as SVG with the QR code drawn | `GET …/spools/<id>/label.svg?size=` |
| H17 | C7 | Printer events with a kind (runout, paused, failed, finished), printer and reason; per-device choice of kinds; a stream the app can hold open | `GET /api/events` (server-sent events); push subscriptions gain `kinds` |
| H18 | C8 | Spools grouped by location, with the last humidity per dry box | `GET …/spools/by-location` |
| H19 | C9 | Monthly totals of filament used per printer and per material; usage kept at least 13 months | `GET …/usage/monthly?printer=` |
| H20 | C11 | A demo data store and simulated printers behind the same endpoints, and a flag every reply carries | Setting `demo: true`; every reply gains `demo: true` while on |
| H21 | C12 | An event record written by every change, with the actor's name and kind | `GET /setup/api/activity?who=&kind=&days=`; spool detail gains `events` (last 10) |
| H22 | C13 | Reading a project file's filament list and matching it to spools | `POST …/fits` (file upload, size limit) answering `{filaments: [{material, color_hex, grams, matches: […]}]}` |
| H23 | D1 | Disk use per category and free space | `GET /setup/api/overview` gains `disk: {free, total, parts: [{name, bytes, setting}]}` |
| H24 | D2 | A time window for automatic updates and a check that no printer prints | Setting `updates.window`; the updates view gains `waiting_for` |
| H25 | D3 | A Hub report job with full redaction | Job `hub_report`; `POST /setup/api/report` and a download as for printer reports |
| H26 | D4 | A second backup folder, a copy after each backup, a copy state per backup | Settings `backup.copy_to`, `backup.copy_keep`; backups list gains `copied`, `copy_error` |
| H27 | D5 | A backup check job that changes nothing | Job `backup_check`; `POST /setup/api/backups/check {name}` |
| H28 | D6 | Status checks on a schedule, kept as changes for 30 days | `GET /setup/api/health?days=` |
