# Spoolwarden design: the Hub page

This document specifies the Hub page in the default theme, Console: every section, card, control and state, at the
three widths of foundations section 7. It builds on `01-foundations.md` (principles, names, tokens, appearance,
themes, navigation, hard rules) and uses the components of `02-components.md` by name. Neither is repeated here:
a component's look, texts and behaviour (lock chip, unlock and lock dialogs, top bar, appearance control, job strip,
the Hub is restarting, banners, the unsaved-changes guard) are as `02-components.md` gives them, and this document
adds only what is particular to the Hub page.
Other themes change how these things look and are laid out (foundations section 6), never what is here: the same
sections, cards, fields, words, order and actions.

Contents: 1 Conventions · 2 Page-wide behaviour · 3 Global chrome · 4 Overview · 5 Printers · 6 Recently added ·
7 Devices · 8 Slicer presets · 9 Features · 10 Settings · 11 Flash a device · 12 Updates · 13 Logs ·
14 Where today's controls went · 15 Needs from the Hub · 16 Spools · 17 Analytics

---

## 1. Conventions

### 1.1 How to read the tables

| Term | Meaning |
|---|---|
| **Phone / Tablet / Desktop** | The three widths of foundations section 7. |
| **P1 / P2 / P3** | Column priority in a collection. P1 is shown at every width (on a phone the row becomes a card that shows only P1 parts). P2 appears from tablet up. P3 appears on desktop only. A column that is not shown moves into the row's inline expansion, so nothing is ever unreachable. |
| **G / P** | `GET` / `POST` to the Hub. Every endpoint is under `/setup/api/` (written without that prefix). |
| **(code)** | The request carries the setup code, or the trusted-computer cookie stands in for it (section 2.1). Without either, the control asks for the code first. |
| **(view)** | The request needs nothing. |
| **job `name`** | `P job` (code) with the body `{name}` starts the background job of that name (the restore job adds `confirm` and `sha256`, section 10.11); the job strip follows it (section 3.5). |
| **(unreleased)** | The Hub has this endpoint or setting in code that is not in a release yet (Flash a device, the On this Hub engine of the Label Reader). The page uses it as named once that code is released; section 15 lists them. |
| `<name>`, `<v>` | A value filled in from the Hub's reply, put in with `textContent`. |
| Choice cards | The segmented choice, cards variant (`02-components.md` section 5.7): one card per option, each with its name and one line of text (used where options need explaining). |
| Button kinds | Primary, default, ghost, danger and icon buttons of `02-components.md`. Every section, card and row has at most one primary button (foundations principle 2). |

Example values in this document are those of `mockups/CONTENT-SPEC.md`: the Hub is named "Workshop hub", version 0.5.2, at
`https://192.0.2.10/setup` (a new Hub uses port 443, so its address has no port; section 10.7); printers Workshop X1
(192.0.2.40), Garage Voron (voron.example:7125) and Study A1 mini (192.0.2.41); devices "Kitchen phone" and "Desk PC".
Where an example shows a Hub on another port (10.7, 10.11), it is `https://192.0.2.10:8710/setup`.
`http://127.0.0.1:7915` is not an example but the product's own default address of the On this Hub engine (section 10.5).

### 1.2 Addresses inside the page

The Hub page is served at `/setup`. The part after `#` names the place (foundations section 8). Every section and
every detail that can be opened has an address; reloading returns to it, Back and Forward move between them.

| Address | Opens |
|---|---|
| `#overview` (also empty or unknown) · `#overview/storage-use` · `#overview/running-low` · `#overview/history` | Overview; Overview with the Storage use panel open; Overview with the full Running low list open (the places that "Show storage use" and "Show running low" of an alert banner go to); Overview with the history table of the checks open (4.2) |
| `#printers` · `#printers/<id>` · `#printers/add` · `#printers/find` | Printers; one printer's row expanded and scrolled to, with its live view (5.10); the Add a printer drawer; the Find Klipper printers card focused |
| `#printers/<id>/load-map` · `#printers/<id>/reports` | The Map by loading filament drawer; the Saved reports drawer. `<id>` is the Hub's key for the printer (for a Bambu Lab printer it may equal the serial), so a Klipper printer has an address too |
| `#spools` · `#spools/<id>` | Spools; one spool's Detail region (16) |
| `#analytics` | Analytics (17) |
| `#recent` · `#recent/<id>` | Recently added; one record |
| `#devices` · `#devices/pair` · `#devices/trusted` · `#devices/tag-readers` · `#devices/<id>` | Devices; the pairing dialog; the Trusted computers card; the Tag Readers card; the detail of a device that serves no page of its own (7.10; `<id>` is a device's id, never one of those four words) |
| `#presets` · `#presets/updates` | Slicer presets; its Updates card |
| `#features` · `#features/<feature>` · `#features/setup-<mode>` | Features; the preview drawer for turning that feature on or off; the preview drawer for changing the setup |
| `#settings` · `#settings/<group>` | Settings; one group (`appearance`, `general`, `storage`, `alerts`, `label-reader`, `backups`, `network`, `passphrase`, `catalog`, `voice`) |
| `#flash` · `#flash/tag-reader` · `#flash/display` | Flash a device; with the device chosen |
| `#updates` · `#logs` · `#logs/activity` · `#logs/<service>` | Updates; Logs; Logs with Activity chosen; Logs with a service chosen and shown (when unlocked) |
| `#job` | The current section with the job strip expanded |

The document title is "<Page title> · <Hub name>" as `02-components.md` section 2.1 sets it, for example "Printers ·
Workshop hub" or, for one record, "Polymaker PolyTerra PLA Charcoal Black · Workshop hub".

---

## 2. Page-wide behaviour

### 2.1 The lock: Locked, Unlocked, Trusted computer

Viewing needs nothing; every change needs the 8-digit setup code. The page shows this as one state in the lock chip
(section 3.3), not as a field.

| State | Meaning | Lock chip text | Lock chip hint (tablet and desktop) |
|---|---|---|---|
| **Locked** | No code in this tab, browser not trusted | Locked | Enter setup code |
| **Unlocked** | The code was typed in this tab and worked | Unlocked | Changes allowed |
| **Trusted computer** | The Hub's trusted-computer cookie is valid (`G trust` says `trusted: true`) | Trusted computer | No code needed |

Rules:
- The code is kept only in the page's memory (a JavaScript variable), never in storage, a cookie or an address. It is
  sent as `code` in the body of each (code) request, exactly as today. Closing or reloading the tab locks it.
- **Asking in place.** A control that needs the code, pressed while Locked, opens the unlock dialog with the action
  named ("To forget Workshop X1, enter the 8-digit setup code."). After a successful unlock the original action carries on by
  itself; Cancel leaves everything as it was (a toggle or segmented choice that was moved goes back).
- **Unlocking checks the code at once**: the dialog sends `P overview` with the code (the same call that shows
  addresses on the Overview). A wrong code is shown at the field, the dialog stays open.
- **Reads that need the code happen by themselves once unlocked.** Lists that today hide behind "Show …" buttons
  (backups, trusted computers, Weigh Station requests, addresses in Overview) load automatically as soon as the page
  is Unlocked or Trusted. While Locked they show a quiet line and an **Unlock to show** default button. The one
  exception is the whole job log: it can be long, so it is read only when **Show the whole log** is pressed
  (section 3.5).
- **Trust is offered inside the unlock dialog**, as a checkbox, not as a separate offer after an unrelated action.
  It appears only when trusted computers are on (`G trust` says `enabled: true`). Ticked, a successful unlock is
  followed by `P trust` (code); the chip then reads Trusted computer and the code is dropped from memory.
- **Trust that stops working.** When a reply carries `trust_gone`, the page switches to Locked, shows the toast
  "This computer is no longer trusted. Enter the setup code to go on." and opens the unlock dialog for the action
  that failed.
- **The camera is the one thing that only looks and still needs the code** (5.10): a picture from inside a home can
  be as private as an address, so the camera, like every control of a printer, waits for Unlocked or Trusted. A picture
  that is running is not cut when the page locks again (5.10).
- **Questions are never skipped.** Unlocked or trusted, every confirmation dialog of this document is still asked.
- **Lockout.** When the Hub answers "too many wrong setup codes", the unlock dialog shows the Hub's own wording at
  the field (as `02-components.md` section 3.2 gives for too many tries); Unlock stays enabled, and pressing it before the wait is over shows the
  Hub's answer again.

The unlock dialog is the one of `02-components.md` section 3.2, with its title, sentences, field, checkbox, buttons,
errors (including "Cannot reach the Hub. Check that it is on, then try again.") and success toast, on tablet and
desktop as a dialog and on phone as a bottom sheet. The Hub page adds two things:

| Case | What the dialog shows |
|---|---|
| The pending change | Its sentence names the change in the words of the control that asked, for example "To forget Workshop X1, enter the 8-digit setup code. Viewing needs nothing; every change needs the code." |
| No code set on the Hub (`G state` says `code_set: false`) | The sentence reads "This Hub has no setup code yet. At the Hub, run the command below, then type the code it shows." and the field hint's command is shown as a code block with Copy: `sudo spoolwarden setup-code`. |

### 2.2 Saving

The Hub page follows the form-group saving model of `02-components.md`. What it means here:

- **Settings groups** have at most one Save button each (section 10). Saving sends only the fields whose value
  differs from what was loaded. Today the Hub takes one setting per request, so the page sends them one after
  another, in the order the fields appear, and stops at the first refusal: fields already saved show as saved, the
  refused field shows the Hub's reason at the field, the rest stay edited and unsaved. The group's inline result
  then reads "Saved <n> of <m>: <names>. <Field> was not saved: see the field." (a single-request write is listed in
  section 15).
- **A save never redraws other groups or other rows.** Only the region that changed is read again; text typed and
  not yet sent elsewhere on the page and the scroll position survive (`02-components.md` 1.4, "Redraw only what
  changed"). Data that several groups of a section show (for example the general settings behind several Settings
  groups) is read once when the section opens, not once per group.
- **Unsaved changes** show the dirty mark of `02-components.md` (triangle, warn): "Unsaved changes" in the group's
  foot and on its title row, "Unsaved" on its entry in the Settings sub-navigation. Leaving the section or opening another address with unsaved edits asks first (the "Leave without
  saving?" dialog of `02-components.md` section 5.11); closing or reloading the tab triggers the browser's own
  `beforeunload` prompt instead, since a page cannot show its own dialog then.
- **A save that restarts the Hub** (the Hub replies `restarts: true`) shows the restart notice (section 3.6). The
  page keeps its place and the person's unsaved edits in other groups, and reloads the data when the Hub is back.
- **A save that applies changes in the background** (`applies: true`) starts following the `apply` job in the job
  strip (section 3.5); the group's inline result reads "Saved; applying… Follow it in the job panel."
- **Controls that apply at once** (appearance, theme, lane data, Weigh Station voice, toggles that start a job) have
  no Save button; their result appears next to them.
- Secrets are never shown back. A saved secret shows as "Set" with a masked value; fields for secrets are cleared
  after a successful save.

### 2.3 Results and messages

| Kind | Where | Used for |
|---|---|---|
| Inline result | Directly under or beside the control that caused it, in an `aria-live="polite"` region | Every save, test, check, scan, copy |
| Toast | Bottom right on desktop and tablet, above the bottom bar on phone; 5 s, 10 s when it carries a button (Undo, 2.9); never the only place an error is shown | Results of actions whose control disappears (a forgotten printer, a closed dialog) |
| Banner | Top of the section's content | A condition of the whole section (Hub half installed, feature switched off, Hub not answering) |
| Job strip | Fixed, above the bottom edge (section 3.5) | Background jobs |
| Status badge | In tables, titles and key-value lists | State words (foundations section 10 shapes) |

The texts of the Hub's own errors are shown as the Hub sends them, after the first letter is made upper case and a
full stop is added when missing. Where this document gives a rewrite of a Hub text, the page shows the rewrite when
the reply matches; any other text is shown as sent.

### 2.4 Standard states

Every card or region that loads data has these states. Card-specific texts in sections 4 to 13 replace the
`<…>` parts.

| State | What shows | Text |
|---|---|---|
| Loading | Loading skeleton in the shape of the content (three rows for a list, two lines for a sentence) | Screen reader: "Loading <card title>." |
| Loaded, empty | Empty state: icon, one-line title, one sentence, at most one button | Per card |
| Error | Error state in place of the content | "Could not read <what>. <Hub's text>" and a default button **Try again** |
| Hub not answering | Banner on every section (section 3.7) | "Cannot reach the Hub. Check that it is on; this page tries again every 10 s." |
| Locked (for code-only reads) | Quiet line and default button **Unlock to show** | Per card |
| Feature switched off | Section 2.5 | Per section |
| Job running | The control that started it shows an inline spinner and is disabled; the job strip shows the job | "<job title>… Follow it in the job panel." |
| Success | Inline result with the OK shape | Per control |

### 2.5 A section whose feature is switched off

Sections never leave the navigation (foundations section 8). A section that cannot work because a feature is off is
dimmed in the navigation (its label in `--muted`, a small hollow-circle badge, `aria-description="switched off"`)
and opens this page:

```
  Slicer presets
  ------------------------------------------------------------
  ( )  Slicer presets are switched off
       Switch on Slicer presets in Features to build filament
       presets for Bambu Studio and Orca Slicer.
       [ Go to Features ]
```

The empty-state component with the hollow-circle icon; title "<Section> is switched off" or "<Section> are
switched off"; one sentence per section (given in each section); primary button **Go to Features**, which opens
`#features/<feature>` with the feature's preview drawer ready.

### 2.6 Dialogs used everywhere

| Dialog | Title | Body | Buttons |
|---|---|---|---|
| Unsaved changes | "Leave without saving?" | As `02-components.md` section 5.11, for example "You changed 2 settings in General and 1 in Storage locations." | **Stay** (focused first) · **Leave without saving** (danger) |
| Lock (from the lock chip, Unlocked) | "Unlocked" | As `02-components.md` section 3.1: "Changes are allowed in this browser until you lock it or close the tab." | Close · **Lock now** (primary) |
| Lock (from the lock chip, Trusted computer) | "Trusted computer" | As `02-components.md` section 3.1: "No code is needed in this browser until <date>." + link "Trusted computers" (`#devices/trusted`) | Close · **Stop trusting this computer** (default button; revokes at once with `P trust/<id>/revoke` (code), as 02 section 3.1 gives) |

On a phone, every dialog of this document opens as a bottom sheet with the same title, body and buttons; the
buttons fill the width, the safe action on the left.

### 2.7 Refreshing data

| Data | Read when | Repeats |
|---|---|---|
| `G state` | Page load; after any change that alters printers, devices, readers, features or addresses | No timer |
| `G trust` | Page load; after unlock, trust, revoke | No timer |
| Section data | When the section opens; when its own change succeeds (only that region) | Overview: when it opens and on **Run the checks again**. Printers: printer states every 10 s while the section is visible (`G state`). Weigh Station requests: every 5 s while Devices is visible and the page is Unlocked or Trusted. Spools: no timer. |
| A printer's live state (`G printers/<id>/live`, 5.10) | When the printer's detail opens | Every 2 s while the detail is open and the tab is visible; the Printers list keeps its 10 s |
| `G job?from=N` | Page load; while a job runs | Every 1 s; while the Hub restarts, `G state` every 2 s instead (section 3.6) |
| Polls of a running flow | Slot mapping every 2 s, Map by loading filament every 2 s, pairing every 3 s | Until the flow ends or its expiry passes |
| `G events` (`GET api/events`) | Page load; then on every section, with `since` set to the last `next` | Every 10 s with `wait=0` (section 2.8) |
| `G health` | When Overview opens and on **Run the checks again**; when the range changes (4.2) | No timer |
| `G activity` | When Logs > Activity opens and on **Show more**; a spool's detail reads its last ten (16.3) | No timer; Activity reads again after an Undo |
| `G analytics` | When Analytics opens and when its printer choice changes (17); Overview reads the month once | No timer |

All timers stop while the browser tab is hidden and resume, with an immediate read, when it is shown again. The
events poll of section 2.8 is the one exception: it keeps its rhythm in a hidden tab while Settings > Alerts >
"Notifications in this browser" is on, so that the browser can notify.

### 2.8 Alerts

Every section of the page shows the alert banners of `02-components.md` section 8.8 and, when an alert arrives while
the page is open, a toast (02 section 8.7) with the alert's title and the action **Show**. The banners are mounted
once in the page frame, at the top of the main area above the page header, so no section draws its own; they sit
below the "Cannot reach the Hub" banner of section 3.7. Titles, sentences and actions are the table of 02 section
8.8; the actions go to `#printers/<id>` (Open the printer), `#devices` (Open Devices), `#overview/storage-use` (Show
storage use) and `#overview/running-low` (Show running low). "<n> more alerts" and Settings > Alerts > "Recent alerts"
open the Alerts list of 02 section 8.9 as a dialog.

- **Where the events come from.** The Hub writes every event once into its event store (`events/<yyyy-mm>.xml`,
  `09-implementation-order.md` Stage 10). The page reads it with `G events` (`GET api/events`): on page load with
  `since_at` set to 24 hours ago and `alert=1`, for the raised `conditions` and the cursor `next`, then every 10 s
  with `wait=0` (section 2.7) with `since` set to the last `next`. The banners are built from `conditions` (a
  condition's banner leaves when it clears, and changes when the Hub raises the same condition again with another
  severity) and from the events of the last 24 hours that an alert type switched on covers (`alert: true`, a moment's
  banner). A new event with `alert: true` shows its toast once.
- **The browser id.** The page makes a random id on its first use, keeps it in the browser (`localStorage`,
  `spoolwarden.browser`) and sends it as `client` on its events requests. Nothing about a browser is stored on the
  Hub. A test alert (10.13) arrives as `test: {title, text}` in the next events answer of that browser and is shown as
  a notification.
- **Dismiss** hides a banner on this browser only and remembers it as 02 section 8.8 says; it comes back when the
  alert gets worse (warn to bad) or is raised again. Dismissing never removes the row from the Alerts list.
- **Notifications outside the page.** With Settings > Alerts > "Notifications in this browser" on, the page also shows
  a browser notification for each new alert while a Hub page tab is open in that browser (the tab may be in the
  background). Nothing is sent when no tab is open. A notification has the title of the alert, one line of body and,
  when chosen, opens the place of its action. A condition's notification has the tag `sw-condition-<key>` (02 section
  8.8); a moment's has a tag of its own per event. One per event; a condition notifies when it is raised, not again
  while it lasts; clearing sends nothing.

### 2.9 Undo the last action

After an action that changes a spool or a slot the page raises a toast (`02-components.md` 8.7) that says what happened
and carries **Undo** for 10 seconds. It is the rule behind Update weight, Move, Mark empty and Link the last tapped tag
(16.3) and Load, Unload and Clear slot (5.10).

| Action | The toast says |
|---|---|
| Update weight | "Updated Polymaker PolyTerra PLA Charcoal Black (214): 482 g left." |
| Move | "Moved Bambu Lab PETG HF Orange (212) to Shelf B." |
| Mark empty | "Marked Polymaker PETG Teal (77) empty." |
| Link a tag | "Linked tag 04A1B2C3D4 to Polymaker PolyTerra PLA Charcoal Black (214)." |
| Load | "Loaded Bambu Lab PETG HF Orange (212) into A2 of Workshop X1." |
| Unload | "Unloaded Bambu Lab PETG HF Orange (212) from A2 of Workshop X1." |
| Clear slot | "Cleared slot A2 of Workshop X1." |

- **What can be undone.** Exactly these seven (the Hub's kinds `spool.weighed`, `spool.moved`, `spool.emptied`,
  `spool.opened`, `spool.loaded`, `spool.unloaded` and `slot.cleared`), and a filament-used entry, as today (Put it
  back, 5.10; Bambu Lab printers only). A Recently added revision keeps its own **Undo revision** (6.3). Nothing else
  can be undone: removing a printer, a key, a pairing or a location still asks first and has no undo.
- **The Hub's rule.** An event can be undone once, for 7 days, and only while nothing changed since: the spool's
  present values equal the event's after-values, and no later undoable event exists for that spool or slot. Undo puts
  back exactly the before-values and writes a new event of the same kind that names the first one (`undo_of`); the
  first is then served with `undone: true`.
- **What the person sees.** **Undo** calls `P events/<id>/undo` (code; the page is Unlocked or Trusted, since the action
  just done was a change). The toast's sentence becomes "Put back." or the refusal "This changed again since, so it
  cannot be undone."; any other refusal (too old, already undone, not undoable) shows the Hub's text as sent. After a
  load or an unload the answer adds "The printer still shows what it was set to.": undoing puts the Hub's record
  back and does not change the printer's own slot setting.
- **Finding the event.** The change's answer carries `event_id`, the id of the event the change made, beside what it
  answers otherwise (absent on a dry run), and **Undo** sends `P events/<id>/undo` with it. Where an answer has none,
  the page reads the newest event of that spool or slot (`G activity` with `subject`) and shows **Undo** only when its
  `undo.possible` is true.
- **Missing the toast costs nothing.** In Logs > Activity (13.4) a row that can still be undone keeps **Undo** as long
  as the Hub allows it. For a person who asked for no time limits the toast stays until it is dismissed
  (`07-accessibility.md` TIM-7).

### 2.10 Export and import as CSV

Spoolman's own export is passed on, not rebuilt; the Hub's own data is offered as files of its own. The page asks the
Hub for a file with `G export/<set>.csv` (code: a file leaves the Hub, so the page asks for the setup code in place),
shows the inline spinner "Preparing the file…" and the browser saves it.

| Place | Menu | Items | File |
|---|---|---|---|
| Spools (16) | the page menu (3.8) | **Download as CSV** → "Spools (Spoolman's file)" and "Filaments (Spoolman's file)"; **Import from CSV** | `spoolman-spools.csv`, `spoolman-filaments.csv` (what Spoolman's own export gives, through the Hub); the import below |
| A printer's Filament used (5.10) | the overflow menu in the card's title row | **Download as CSV** → "Last 7 days", "Last 30 days", "Last 12 months" | `usage.csv` of that printer |
| Recently added (6) | the page menu | **Download as CSV** | `recent.csv` |
| Logs > Activity (13.4) | the page menu, while Activity is chosen | **Download as CSV** → "Last 7 days", "Last 30 days", "Last 12 months" | `activity.csv` |
| Settings > Storage locations (10.4) | the overflow menu in the group's title row | **Download as CSV**, **Import from CSV** | `locations.csv`; the import below |
| Slicer presets (8) | the page menu | **Download as CSV** | `lines.csv` |
| Printers (5) | the page menu | **Download as CSV** | `printers.csv` |

- **The files.** UTF-8, commas, a header row with the field names (those of the Add spools card, `04-web-app.md` 4.5,
  for spools: `vendor`, `name`, `material`, `color_hex`, `line`, `count`, `density`, `net`, `tare`, `sealed`, `gross`,
  `nozzle`, `bed`, `location`, `lot`, `price_per_kg`, `note`), dates as ISO 8601, numbers with a dot, grams without a
  unit. A cell that starts with `=`, `+`, `-` or `@` gets a leading `'`, as Spoolman does, so a spreadsheet never takes
  it for a formula.
  - `usage.csv`: `time`, `printer`, `job`, `slot`, `spool`, `vendor`, `name`, `material`, `grams`, `outcome`, `taken_off`
    (yes or no), `undone` (yes or no).
  - `locations.csv`: `name`, `type`, `limit`, `count`, `prefix`, `fill`, `materials` (joined with `;`), `overflow`,
    `default_overflow`, `sealed`, `position`.
  - `recent.csv`: `record`, `added`, the filament fields as saved, `spools` (the numbers made), `revisions`.
  - `activity.csv`: `time`, `who`, `kind`, `subject`, `text`.
  - `printers.csv`: `name`, `kind`, `model`, `slot`, `spool` (the number): no address, serial or code.
  - `lines.csv`: `vendor`, `line`, `material`, `preset`.
- **Import spools** (Spoolman has no import). **Import from CSV** on Spools opens the drawer "Import spools from CSV"
  (a dialog on tablet, a sheet on a phone): a file field "CSV file" (accept `.csv`) and the link **Download a sample
  file**. After a file is chosen the page shows what it read as a table, one row per line of the file (No., what would
  be added, problems), with a problem marked on its row by the error shape and its words ("net: Enter grams above
  0."). **Check** (default button) sends the file to the Hub with `dry_run`, the same dry run as Add spools, and the
  rows show the Hub's own `line` and problems; then the primary button reads **Add <n> spools** ("Add 1 spool"). Rows
  with a problem are left out, and the table says so ("<k> rows have problems and are left out."). It only adds: it
  never changes or removes a spool. Result "Added <n> spools." ("Added 1 spool.") with the new spool numbers. A column
  left empty takes the value the Add spools card gives an empty field. The sample file has the right columns and two
  example lines:

  ```
  vendor,name,material,color_hex,count,net,tare,sealed,location,lot
  Polymaker,PolyTerra PLA Charcoal Black,PLA,#2B2B2E,2,1000,140,yes,,F57
  Bambu Lab,PETG HF Orange,PETG,#F2762E,1,1000,,yes,Shelf B,
  ```
  `vendor`, `name`, `material` and `net` are required.
- **Import storage locations.** **Import from CSV** in the Storage locations group opens the same drawer with the title
  "Import storage locations from CSV". It adds new locations and changes same-named ones, after the preview the Hub gives
  (**Check**); it never removes one. The primary button reads **Import locations** and the result "Added <a> locations
  and changed <c>."
- **Locks.** Downloads and imports are changes of what leaves or enters the Hub and need the page Unlocked or Trusted;
  looking at a menu does not. A file that cannot be read says so at the file field: "This file is not a CSV file that
  Spoolwarden can read." Spoolman's two files come from Spoolman's own export: where the Hub says Spoolman cannot give
  them, the two items are left out of the menu and the menu says "Spoolman's own export is not available in this
  Spoolman version."

---

## 3. Global chrome

### 3.1 Top bar

Fixed, `--top` high, `--surface` with a bottom hairline. Left to right (foundations section 8):

```
Desktop (over 1024 px)
+------------------------------------------------------------------------------------------------+
| [mark] Spoolwarden / Workshop hub 0.5.2        [o Backup  Running] [lock Locked  Enter setup code] [sun Light|moon Dark|half System] |
+------------------------------------------------------------------------------------------------+

Tablet (601-1024 px)
+---------------------------------------------------------------------------+
| [mark] Spoolwarden / Workshop hub 0.5.2   [o Backup] [lock Locked  Enter setup code] [sun Light|moon Dark|half System] |
+---------------------------------------------------------------------------+

Phone (up to 600 px)
+----------------------------------------------+
| [mark] Spoolwarden             [lock] [half] |
|        Workshop hub                          |
+----------------------------------------------+
```

The top bar is the one of `02-components.md` section 2.2; on phones the job indicator and the version move out of
it (the job strip shows on its own above the bottom bar; the version stays on Overview and Updates).

| Part | Content | Behaviour |
|---|---|---|
| Product mark and name | The Spoolwarden mark (own drawing) and "Spoolwarden", `--fs-l`, weight 650 | Link to `#overview` |
| Hub name and version | `<server_name>` from `G state`, then the version in `--mono`, `--muted` | On phone the Hub name moves to a second line under the product name, `--fs-xs`, without the version |
| Job indicator | Section 3.5; only while a job runs or has just finished; tablet and desktop | Opens the job strip expanded |
| Lock chip | Section 3.3 | Opens the unlock dialog or the lock dialog |
| Appearance control | Section 3.4 | Changes Light / Dark / System at once |

### 3.2 Navigation

Uses the navigation component (`nav` profile `rail` in Console) with the twelve sections of foundations section 8, in
two groups separated by a hairline.

| Section | Address | Rail label | Bottom bar | Live summary (More sheet, rail tooltip) |
|---|---|---|---|---|
| Overview | `#overview` | Overview | Overview | "<n> to do" or "All checks OK" or "<n> need a look" |
| Printers | `#printers` | Printers | Printers | "<n> connected · <m> offline" |
| Spools | `#spools` | Spools | More | "<n> running low" or "<n> spools" |
| Analytics | `#analytics` | Analytics | More | "<x> kg used this month" or "Nothing used this month" |
| Recently added | `#recent` | Recently added | Recent | "Newest: spool <id>, <relative time>" |
| Devices | `#devices` | Devices | More | "<n> paired · <m> Tag Readers" |
| Slicer presets | `#presets` | Slicer presets | More | "Last build <relative time>" or "No build yet" |
| Features | `#features` | Features | More | "Setup: <setup name>" |
| Settings | `#settings` | Settings | Settings | "<n> groups" or "<group> unsaved" |
| Flash a device | `#flash` | Flash a device | More | "Tag Reader · Weigh Station display" (devices this Hub has firmware for) |
| Updates | `#updates` | Updates | More | "<installed> · up to date" or "<latest> is available" |
| Logs | `#logs` | Logs | More | "<n> services" |

Where a summary comes from: the Hub gives one line per section with its state reply. Two are completed by the page:
Overview shows "<n> to do" when the page's Still to do list (4.2) has entries, else the Hub's "<n> need a look" or
"All checks OK"; Settings shows "<group> unsaved" while a group holds unsaved edits, else the Hub's "<n> groups".
The Hub runs its checks only when Overview is read, so the Overview summary is empty until then: the page reads
Overview once in the background after it has loaded, and a section whose summary is empty shows no second line.
Spools shows "<n> running low" when the Running low list (4.2) has entries, else "<n> spools" (the `total` of `G spools`
with `limit` 1). Analytics shows "<x> kg used this month" ("640 g" under a kilogram) from the month's `grams` in `G analytics`
(`months` 1), or "Nothing used this month". Summaries are refreshed with every state read, so relative times in them stay current. Flash a device
names the
devices by their design names ("Tag Reader", "Weigh Station display"), whatever the Hub's firmware ids are; a
firmware id the page does not know is shown as the Hub names it.

- **Desktop and tablet:** the navigation rail, `--rail` wide, icon above a `--fs-xs` label; labels that do not fit
  in two lines ("Recently added", "Slicer presets", "Flash a device") break into two lines, never truncate. The
  active entry has `--accent-soft` ground, weight 600 label, the 3 px `--accent-text` mark at the rail's inner edge and
  `aria-current="page"`. Hover shows the live summary as a tooltip.
- **Phone:** the bottom bar with Overview, Printers, Recent, Settings, More. More opens the More sheet: the eight
  other sections, each a row with icon, name, live summary and chevron; the active one has `aria-current="page"`.
  When one of those eight is open, More shows the active mark and its accessible name ends ", current: <section>".
- A badge on a navigation entry shows only these: Overview a warn triangle when a check needs a look; Updates an
  info dot when a newer version is available; Settings a warn dot while a group has unsaved changes; a dimmed
  hollow circle for a section switched off.
- Live summaries come from data the page already has (`G state`, the job); the More sheet reads `G presets`, `G updates`,
  `G spools` and `G analytics` when it opens if those were not read yet, showing a skeleton line until they arrive.

### 3.3 Lock chip

The lock chip of `02-components.md` section 3.1: icon, state word and, on tablet and desktop, the hint (texts in
section 2.1); on phone the icon alone (02 3.1). Its colours per state, accessible names and
announcements are as 02 gives them. Pressing it opens the unlock dialog (Locked) or the lock dialog (section 2.6).

### 3.4 Appearance control

As foundations section 5 and `02-components.md` section 3.3. Desktop and tablet: the three-part segmented choice
with sun, moon and half-circle icons and the words Light, Dark, System. Phone: one icon button showing the current
choice's icon; it opens a menu with the three choices as menu radio items.
Choosing applies at once with no message; the same control is the first row of Settings > Appearance.

### 3.5 Job indicator and job strip

One background job runs at a time on the Hub. The page follows it wherever the person is, with the background-job
strip and the top-bar job indicator of `02-components.md` section 8.4: their parts, sizes, job titles, end lines,
Hide and Close, **Show the whole log** (which reads `P job/log` (code) page by page) and the "already running" result
are as given there.

```
Desktop and tablet: floating at the bottom right, min(25rem, 100vw - 2 x --s4) wide
                                   +---------------------------------------------+
                                   | (*) Running  Backup                 [v] [-] |
                                   | Adding the Recently added photos (14.2 MB)  |
                                   | [====== bar ===============================]|
                                   +---------------------------------------------+
Phone: above the bottom bar, the width of the screen less --s2 on each side
+----------------------------------------------+
| (*) Running  Backup                  [v] [-] |
+----------------------------------------------+
```

What the Hub page adds:

| Point | Content |
|---|---|
| Data | `G job?from=N` (view): once on page load, then once a second while a job runs. |
| Locked | **Show the whole log** asks for the code first (section 2.1). |
| More job names | `reader_setup` (from Flash a device) has the title "Setting up a Tag Reader"; a name the page does not know has the title "Working". |
| After the end | The region that started the job reads its data again (for example the backup list after `backup`). |

Where each job is started:

| `name` | Started from |
|---|---|
| `apply` | Features; Settings > General (Spoolman address), Network and addresses, Weigh Station voice |
| `update`, `rollback`, `check` | Updates |
| `backup`, `restore` | Settings > Backups and restore |
| `library_update`, `library_rollback` | Settings > Filament Catalog |
| `remote_issue` | Settings > Network and addresses |
| `station_pair` | Devices |
| `reader_setup` | Flash a device |

### 3.6 The Hub is restarting

When a save, update, roll back or restore makes the Hub restart, or the job poll stops answering during a job that
restarts the Hub, the page shows the Hub is restarting state of `02-components.md` section 8.5: the job strip in its
restarting form ("The Hub is restarting", "This page comes back by itself."), write controls disabled with the
reason "Wait for the Hub to come back.", `G state` every 2 s, "The Hub is back." when it answers with the same
version, a reload at the same address when the version differs, and after 2 minutes the "has not come back" form
with `spoolwarden status` and **Reload the page**. What the Hub page adds: when the Hub is back, only the current
section reads its data again; edits the person made in other groups and sections are kept.

### 3.7 The Hub is not answering

When a request fails because nothing answers (not because the Hub refused it) while no restart is expected, every
section shows the global banner of `02-components.md` section 8.8 in its error form: "Cannot reach the Hub. Check
that it is on; this page tries again every 10 s." with **Try now**, and the page retries `G state` every 10 s. The
content already shown stays as it was and typed edits are kept; controls that send something wait with an inline
spinner until the Hub answers. When it answers, the banner goes and the section reads its data again. A refusal from the
Hub's access rules is not this case: "the setup page only answers the home network" and "Open the setup page by the
server's own name or address" are shown as a full-page error state with the rewritten texts "This Hub page only
opens from the home network." and "Open the Hub page by the Hub's own name or address, for example
https://192.0.2.10/setup. Other names can be added in Settings > Network and addresses." A change refused with
"bad origin" (the page was opened under another address than the one the request reached) is shown where the
change's result goes, as the error "The Hub refused this change because the page was opened under a different
address. Reload the page and try again."

### 3.8 Page frame

- A skip link "Skip to content" is the first focusable element.
- Each section starts with a header: a breadcrumb line in `--fs-s` `--muted` (`02-components.md`: "<Section> / <item>"
  in sentence case, for example "Recently added / Spool 214", with the section as link; a section's own page shows
  only "<Section>"), the page title (`--fs-xl`, one per
  screen), an optional meta line of status badges and short facts, and at the right the section's actions (at most
  one primary). On phone the actions wrap under the title; the primary comes first.
- **The page menu.** At the right end of every section's actions, an icon button "More actions for this page" (the
  overflow menu of `02-components.md` 4.2). It holds **Open the web app**, which opens the home address of the web
  app in a new tab (`G webapp`, 7.4). It is on every section and is shown only while the web app's feature is on. On the
  sections that offer a file (Printers, Spools, Recently added, Slicer presets and Logs > Activity) it also holds
  **Download as CSV** and, on Spools, **Import from CSV** (2.10).
- While the demo is on, the demo banner (3.9) is the first thing in `main`, above the alert banners and the page header.
- Moving to another section scrolls to the top and focuses the page title (`tabindex="-1"`).
- Content is at most 1400 px wide on desktop with `--s5` gutters; `--s4` on tablet and phone.
- Cards: a title row (`--fs-l`, weight 650, optional icon, optional status badge, optional
  actions at the right), body, optional footer for the group's Save. Cards are separated by `--s4`.

### 3.9 The demo

**What it is.** The whole product running on made-up data with pretend printers, so that a person can look around
without owning anything. The data is the sample set of `mockups/CONTENT-SPEC.md`, "Workshop hub": 64 spools, three
printers and one found, and a print running at 42 %. The pretend printers move: they print, pause, resume and stop,
slots can be loaded and unloaded, filament used is recorded, and two minutes after the demo starts or restarts one
scripted alert, "Filament ran out" on the Klipper printer (the alert of 2.8), shows what an alert looks like. There is
no camera picture: the live view says "No camera in the demo."

**Switching it on.** Only on an empty Hub, one with no spool and no printer: otherwise the Hub refuses with "The demo is
for an empty Hub. This Hub has real data." It is offered in Getting started ("Just looking? Try the demo", 4.2) and as
**Try the demo** in Settings > General (10.3), and needs the page Unlocked or Trusted. The command line has `sudo
spoolwarden demo on` (`06-command-line.md` 9.28). Result "The demo is on."

**The banner.** Every screen shows the demo banner of `02-components.md` 8.8 (kind info, "Demo data. Nothing here is
real." with **Leave demo**) in the global chrome, at the top of `main`, also on a Locked page and in the error states.
It cannot be dismissed. A test holds that no section, dialog page or state lacks it while the demo is on.

**Leave demo** asks once, in a destructive dialog (`02-components.md` 9.1):

| Dialog | Title | Body | Buttons |
|---|---|---|---|
| Leave demo | "Leave the demo?" | "Everything in it is deleted." | Cancel (focused first) · **Leave demo** (danger) |

It calls `P demo` `{on: false}` (code), deletes the demo's own folder and brings the Hub back as it was, empty. Result
"The demo is off." Getting started is not marked by anything done in the demo.

**Nothing real is touched.** In the demo the Hub talks to a demo inventory instead of Spoolman and to pretend printers
instead of real ones, and keeps everything it records (events, filament used, storage locations, Recently added) in a
folder of its own. These do nothing and answer "Not in the demo." where the person pressed the control (the inline
result of 2.3, the toast, or the job strip):

- reaching a printer;
- writing to Spoolman;
- calling the Label Reader's cloud;
- downloading from GitHub: updates, the Filament Catalog and language packs (Get more languages, 10.3);
- sending a push;
- making a backup or restoring one;
- flashing a device;
- changing system settings through the Hub's root helper.

Pairing a phone or a PC works, so the demo can be seen on them. Every answer that says what the Hub is (`G state`,
`GET api/info`, `GET api/hub`) carries `demo: true` while it is on, and the page draws the banner from it.

---

## 4. Overview

**Purpose.** Show at a glance whether the Hub is healthy and what is still to do, with a way to each fix. It is the
page form of `spoolwarden status`. Address `#overview`.

**Data.** `G state`, `G overview` (view); when Unlocked or Trusted, `P overview` (code) instead, which returns the
same shape without hidden addresses. `G intake/history` for the Recently added tile. `G storage-use` (`GET
api/storage-use`) for the Storage row and its panel; `G spools/low` (`GET api/spools/low`) for the Running low card. `G start` (`GET start`, view) for the Getting started panel; `P start`
(code) for its Hide, Show and Keep buttons. `G health` (`GET health`, view) for the strips and the history table of the
Checks (`days` 7 or 30); `G analytics` (`GET analytics`, view, `months` 1) for the Filament line.

### 4.1 Layout

```
Desktop
+--------------------------------------------------------------------------------------------+
| Overview                                                                                   |
| Overview                                                       [Run the checks again]       |
| Spoolwarden 0.5.2 · Setup: Hub · [i 0.5.3 is available -> Updates]   Checked 2 minutes ago  |
|                                                                                            |
| [banner: The last install or update stopped halfway ...]          (only when half installed) |
|                                                                                            |
| +-- Still to do (2) -------------------------------------------------------------------+   |
| | /!\ Add your first printer.                                       [Go to Printers]   |   |
| | /!\ Set the Anthropic API key, so the Label Reader can use Cloud.  [Open settings]   |   |
| +--------------------------------------------------------------------------------------+   |
|                                                                                            |
| +-- Running low (3) ------------------------------------------------ [Show all 3] ----+   |
| | [swatch] Prusament PLA Galaxy Black   Spool 214   96 g left   Rack 1   2 more in stock |   |
| | [swatch] Polymaker PETG Teal          Spool 77    140 g left  Rack 2   (!) Last one    |   |
| +--------------------------------------------------------------------------------------+   |
|                                                                                            |
| +- Printers ---------+ +- Recently added ----+ +- Devices ----------+ +- Label Reader ---+ |
| | 2 connected        | | Spool 214           | | 3 paired           | | 12 of 40 reads   | |
| | 1 offline          | | 3 minutes ago       | | 1 Tag Reader       | | used today       | |
| +--------------------+ +---------------------+ +--------------------+ +------------------+ |
|                                                                                            |
| Filament used this month: 1.84 kg                                                          |
|                                                                                            |
| +-- Checks ---------------- [Show history] [Show 30 days] [1 needs a look] [14 OK] ----+   |
| | STATUS            CHECK                             FIX                LAST 7 DAYS   |   |
| | /!\ Needs a look  Spoolman fields are missing       [Make the fields]  ___________   |   |
| | (i) Note          Slicer Sync: not set up           Link it in Devices ___________   |   |
| | /!\ Needs a look  Storage: 4 GB free (97 % used)    [Show storage use] ___####____   |   |
| | > Show 14 checks that are OK                                                         |   |
|  Addresses and serial numbers are hidden while the page is locked.  [Unlock to show]       |
+--------------------------------------------------------------------------------------------+

Tablet: tiles in a 2 x 2 grid; the Checks table keeps Status, Check and Last 7 days, Fix moves under the check text.
Phone:  one column; the tiles become one key-value list card; each check is a stacked card
        (badge, text, fix, action, then its strip). The Running low rows are stacked cards (swatch, name, "Spool 214", grams,
        location, stock note).
```

The Getting started panel takes the place of the Still to do card while it shows (4.2). Desktop, with five steps shown:

```
+-- Getting started ------------------------------------------------------------ 2 of 5 done --+
| (*) Done     Name this Hub                          Workshop hub                [Open settings] |
| (*) Done     Check storage locations                The default locations      [Open settings] |
| **Next**     Choose features                           [Keep these]  [Go to Features]          |
| Not yet      Add a printer                                                    [Add a printer] |
| Not yet      Use a phone                                                      [Go to Devices] |
|                                                                               [Hide this list] |
+--------------------------------------------------------------------------------------------+
Hidden:  Getting started: 4 of 8 done · Show
Tablet and phone: one column; each row stacks the state word and the name, the line, then the button.
```

### 4.2 Cards

**Header meta line.** "Spoolwarden <version_text>" · "Setup: <setup name>" (names in section 9) · when
`update.newer`, an info status badge "<latest> is available" that links to `#updates` · at the right "Checked
<relative time>" (exact time on hover).

**Half-install banner** (warn; when `update.half_install` and no job runs): title "The last install or update
stopped halfway", body "To repair it, run this on the Hub:" and a code block with Copy holding the command the Hub
sends.

**Label Reader banner** (warn; while Label Reader: On this Hub is on and the reader is not installed, and only after
the person has left Features before the switch's job ended, 9.4): "The Label Reader is switched on but not installed."
with the default button **Finish in Settings** → `#settings/label-reader`. It goes when the reader is installed.

**Getting started** (the welcome checklist: Guided Setup is this panel; built from the parts of `02-components.md`
section 6.5). It is the top card of Overview, above the tiles, and it replaces the Still to do card while it shows.
Title "Getting started", and at the right the count "<n> of <m> done", where <m> is the number of steps shown. One row
per step, in the order of the table: the state word, the step's name, one line of result or reason (the Hub's own
`line`), and one button. Any step can be done in any order. Conditions are in brackets; the first column is the name
shown.

| Step | Button → place | Done when |
|---|---|---|
| Name this Hub | **Open settings** → `#settings/general`; ghost **Keep "<name>"** | The name was saved once, on this page or at the installer's question, or **Keep "<name>"** was pressed |
| Check storage locations | **Open settings** → `#settings/storage`; ghost **Keep the defaults** | The list was saved once, or the installer's storage question was answered, or **Keep the defaults** was pressed |
| Choose features | **Go to Features** → `#features`; ghost **Keep these** | A feature was switched once, or the installer asked about features, or **Keep these** was pressed |
| Install the Label Reader (only with "Label Reader: On this Hub" on) | **Open settings** → `#settings/label-reader` | The reader is installed |
| Set the Anthropic API key (only with the Cloud (Claude) engine on) | **Open settings** → the key field of `#settings/label-reader` | A key is set |
| Add a printer (only with a printer feature on) | **Add a printer** → the guided drawer (5.6) | A printer exists |
| Map its slots (same condition) | **Map slots** → that printer's Map slots (5.7) | A printer has a saved slot map |
| Use a phone | **Go to Devices** → `#devices/pair`, the pairing code | A phone is paired, or the web passphrase is set |
| Set the web passphrase (only with Web access on) | **Open settings** → `#settings/passphrase` | The passphrase is set |
| Pair Slicer Sync (only with Slicer presets on) | **Go to Devices** → `#devices/pair`, the pairing code | A PC is paired |
| Add your first spool | **Open the web app**: the phone web app's Add (7.4); with the hint "Do this from your phone." beside it when no phone is set up | Spoolman has at least one spool |
| Make a first backup | **Back up now** → `#settings/backups` | A backup exists |

**The Restore row.** "Moving from another computer? Restore its backup" with **Restore a backup** → `#settings/backups`
is not a step. It is a quiet row above the steps, shown only while no step is done, and it goes when any step is done.
It has no state word: it is never "Next" and never "Done", and it is not counted in "<n> of <m>". The Hub's answer
carries it as `restore_offer` (section 15).

**The demo row.** "Just looking? Try the demo" with the default button **Try the demo** (`P demo` `{on: true}`, code;
3.9) is a second quiet row above the steps. It is shown only while the Hub has no spool and no printer and the demo is
not on, it is not a step, has no state word and is not counted in "<n> of <m>". When the Hub has real data the Hub
refuses it with "The demo is for an empty Hub. This Hub has real data." Nothing done inside the demo marks a step done
(3.9).

The setup code is not a step: a Hub installed by the installer always has one. The Still to do card keeps its row for
the rare Hub without one, and while Getting started shows, that row is the only part of the card drawn.

- **State words.** "Done" with the filled circle; "Next" in bold on the first step not done, and its button is the one
  filled button of the card; "Not yet" in `--muted` with no status shape. "Next" only marks the first open step.
- **Hide and finish.** The foot has a ghost button **Hide this list**. Overview then shows one quiet line "Getting
  started: 4 of 8 done · Show", and **Show** brings the panel back. When every shown step is done, the panel says "All
  set" once and is then gone for good, with no line. Changing something (Hide, Show, Keep) needs the setup code as
  everywhere; looking does not.
- **When it shows at all.** On a Hub installed with this version or later. A Hub that was updated from an earlier
  version starts with the panel hidden (the line with **Show** is there, so nothing is forced on an owner who is long
  set up); a Hub restored from a backup starts hidden too.
- **Where it is kept.** The marks (hidden, finished, and that the name, storage and features questions were answered) are
  kept by the Hub in `firstrun.xml` in its state folder, and are part of a backup. Everything else is read at the
  moment the panel is drawn: printers, slot maps, devices, features, the reader's install state, the key, the
  passphrase, backups and the number of spools. The state of the panel never stops the Hub from starting: when it cannot
  be read or written, the panel is treated as hidden and nothing else changes.

**Still to do** (only when it has items, and only while Getting started is hidden, finished or not shown, or, while
Getting started shows, only its setup-code row; card title "Still to do" with the count in a badge). Each item is a row: warn triangle, one sentence, one default button.

| Shown when | Sentence | Button → place |
|---|---|---|
| `code_set` is false | "No setup code yet. On the Hub, run this to make one:" and a code block with Copy, `sudo spoolwarden setup-code` | none |
| Printer features on, no printers | "Add your first printer." | **Go to Printers** → `#printers/add` |
| No phone paired | "Pair a phone to add spools from it." | **Go to Devices** → `#devices/pair` |
| No devices and no printers | "Moving from another computer? Restore its backup." | **Restore a backup** → `#settings/backups` |
| Label Reader Cloud on, key not set | "Set the Anthropic API key, so the Label Reader can use Cloud." | **Open settings** → `#settings/label-reader` |
| Web access on, passphrase not set | "Set the web passphrase, so Claude's connector can sign in." | **Open settings** → `#settings/passphrase` |

**Running low** (between Still to do and the tiles; only when `G spools/low` lists at least one spool: no card when
nothing is low). Card title "Running low" with the count in a badge. The body is up to five rows, the spools with the
least filament first; each row has the swatch, the filament name, "Spool <id>", "<grams> g left", its location and
"<n> more in stock" (other spools of the same filament line that are not empty, sealed ones included) or "Last one"
(a warn badge). Under the rows, a ghost button **Show all <n>** (when more than five) opens the full list in a dialog
"Running low" (`#overview/running-low`): the same rows, all of them, with Close. The threshold is the Hub's "Running low
under" setting (10.13); the dialog's foot says "Spools at or under <n> g that are opened." with a link to
`#settings/alerts`.

**Summary tiles.** Four key-value tiles, each a link to its section; numbers in `--fs-2xl`.

| Tile | Value | Second line | Source |
|---|---|---|---|
| Printers | "<n> connected" with the status badge shape | "<m> offline", "<k> not configured", or "No printers yet" | `G state` `printers.list` |
| Recently added | "Spool <id>" | Relative time of the newest record, or "Nothing added yet" | `G intake/history` |
| Devices | "<n> paired" | "<m> Tag Readers", and, when any device is out of date (7.2), the warn line "<k> out of date" | `G state` `devices`, `readers`; `G devices` for the out-of-date count |
| Label Reader | "<used> of <limit>" | "Cloud reads used today" | The "reads used today" check row of `G overview` |

When Share corrections is on and corrections are waiting (10.5.2), the Label Reader tile adds the link line
"<n> corrections waiting to be shared" to `#settings/label-reader`. That line is the only reminder: no toast, no
mark on the navigation, and nothing is ever sent by itself.

While Label Reader: On this Hub is on and the reader is not installed, the Label Reader tile says "Not installed yet" as
its second line, with the link **Finish in Settings** to `#settings/label-reader`.

When the feature behind a tile is off, the tile shows "Switched off" in `--muted` and still links to its section.

**Filament line.** Under the tiles one quiet line, "Filament used this month: 1.84 kg", a link to `#analytics`. It reads
the month's total from `G analytics` (`months` 1) and is left out while no filament was used this month or the usage
cannot be read. Grams under 1000 read "640 g".

**Checks** (a collection of the Hub's `rows`, `table` profile in Console).

| Column | Content | Priority |
|---|---|---|
| Status | Status badge: `ok` → "OK"; `fail` → "Needs a look"; `info` and anything else → "Note" | P1 |
| Check | The row's `text`. A `detail` row has no badge and sits indented under the row before it, in `--muted`. | P1 |
| Fix | The row's `fix` (a command shows as a code block with Copy), or the row's action button | P2 (under the check text on phone and tablet) |
| Last 7 days | The history strip (`02-components.md` 7.11) of that check: the last 7 days, or 30 after **Show 30 days**. A `detail` row has none. | P2 (on phone under the row's last line) |

- Order: Needs a look first, then Note, then OK; within each, the Hub's order. OK rows are folded under a disclosure
  "Show <n> checks that are OK" (open by default when nothing needs a look). The card title row carries two badges
  with the counts ("1 needs a look", "14 OK").
- **Storage row** (group Hub): "Storage: <free> free of <total> (<percent> % used)", status OK, or Needs a look past a
  limit (warn at 85 % used, bad at 95 % used, and always bad under 1 GB free; the limits are set in Settings > Alerts,
  10.13), with the fix **Show storage use**. It is measured by the Hub every 5 minutes and when Overview is opened,
  for the filesystem that holds the Hub's state and for the backups folder's filesystem when it is another one. The
  fix opens a small panel "Storage use" (`#overview/storage-use`; a dialog, a sheet on a phone): the total bar and one
  line per item with its size and where to reduce it.

  | Line | Size of | Where to reduce it |
  |---|---|---|
  | Backups | the backups folder | **Open Backups** → `#settings/backups` |
  | Photos | photos of recently added spools | "Recently added keeps the last <n>." (the Records kept field of Settings > Label Reader) |
  | Label Reader | the Label Reader on this Hub | "Settings > Label Reader" → `#settings/label-reader` |
  | Events and logs | the event store and the logs | none |

  The same row is in `spoolwarden status`. A storage warning also shows as an alert banner on every section
  (section 2.8).
- **Rows for the satellites and the reader.** The same rows are in `spoolwarden status` (`06-command-line.md` 9.1).

  | Group | Status | Row | Fix |
  |---|---|---|---|
  | Devices | Needs a look | "The Weigh Station <name> is not using HTTPS. Update it." (a Weigh Station that sends no fingerprint because it has not been updated, or because it could not make its certificate and logged why in its own log; the Hub keeps calling it over plain HTTP, and only if it has no pinned certificate) | none: the text is the fix; the station's log (`sudo spoolwarden logs` on its machine) says why when it is already updated |
  | Devices | Needs a look | "The Weigh Station <name> does not show the certificate the Hub saved for it." (a Weigh Station whose certificate the Hub has pinned and which now sends none or another one; the Hub does not call it over plain HTTP) | "Unpair it in Devices, then link it again." |
  | Devices | Needs a look | "<n> devices are out of date." ("1 device is out of date.") | **Open Devices** → `#devices` (the Hub does not update a satellite itself, 7.2) |
  | Devices | Needs a look | "The tag source <address> is not using HTTPS." (a printer-side tag service that answers only on plain HTTP, which the Hub still reads) | none |
  | Devices | Needs a look | "The certificate of the tag source <address> has changed." | "Save the tag source again to trust the new certificate." |
  | Label Reader | Note | "The Label Reader at <address> is not using HTTPS. A later Label Reader version adds it." (a reader on another machine at an `http://` address, until the reader's own software can serve HTTPS) | none |
  | Label Reader | Needs a look | "The Label Reader at <address> is not using HTTPS." (from the release that turns the rule on, for a stored `http://` address of a reader on another machine, 10.5) | "Update the Label Reader on that machine, then change its address to https:// in Settings > Label Reader." |
  | Label Reader | Needs a look | "The Label Reader is switched on but not installed." | The command that installs the reader, as a code block with Copy |
- **Rows for the Hub's own files.** At the first start with this version the Hub moves each of its stored-data and
  settings files from JSON to XML (`09-implementation-order.md` Stage 14). The Hub always starts. A JSON file that
  cannot be read is left where it is, and the Hub works with what it does for a missing file; the Checks then show one
  row for it, in group Hub, Needs a look: "<What it is> could not be converted (<reason>)." ("The list of paired devices
  could not be converted (the file is damaged).") with the Fix the Hub can name. The same row is in `spoolwarden status`
  (`06-command-line.md` 9.1). An XML file that cannot be read is never overwritten: the next save keeps it as
  `<name>.unreadable`, as `storage.xml` does (10.4).
- Row action `ensure_fields`: primary button **Make the fields** (code) → `P fields`, the page's main action while
  its check needs a look (4.3; a default button while Getting started shows a Next step); inline result "Made the fields: <made>." or, when `made` is 0, "The fields were
  already there." It is the only row action.
- Card action (title row, ghost button with refresh icon): **Run the checks again** → reads the rows again.
- **History.** The Checks card's title row also has the ghost buttons **Show history** and **Show 30 days** (which then
  reads **Show 7 days**). The strips come from `G health`: plain where the check was fine, marked where it needed a
  look, with the times in words on hover, focus or long press ("Workshop X1 offline 2026-11-11 23:10 to 2026-11-12
  06:45"). **Show history** opens a dialog "History of the checks" (`#overview/history`; a sheet on a phone) with the
  changes of the range as a table: Time (`--mono`), Check, From and To (the words "OK", "Needs a look" and, for a
  check at its worst, "Needs a look now"), newest first, and the foot "Changes of the last 7 days." ("30 days"). The
  strip never carries meaning by colour alone: every change on a strip is a row of this table. History starts when the
  Hub started to keep it; before that the strip is empty and the sentence "No history before <date>." stands beside it,
  and the table's foot repeats it. Empty table: "No changes in the last 7 days."
  The checks come from the conditions the Hub already records every 5 minutes (check rows, printers offline and online,
  devices down and up, storage low and ok); nothing is measured for it.

**Hidden addresses.** When the reply says `redacted: true` (Locked): a quiet line under the Checks card "Addresses
and serial numbers are hidden while the page is locked." and a default button **Unlock to show**. Once Unlocked or
Trusted, the page reads `P overview` by itself and the line goes.

### 4.3 States

| State | Text |
|---|---|
| Loading | Tiles and five check rows as loading skeleton; screen reader "Checking the Hub." |
| Error | Error state in the Checks card: "Could not check the Hub. <Hub's text>" and **Try again** |
| Nothing to do, all OK | No Still to do card; the Checks card title badge reads "OK" and the first line of the card "Everything checked out." |
| Getting started loading | Three skeleton rows in the panel's place |
| Getting started shows | Still to do is not drawn, except its setup-code row on a Hub that has no setup code |
| Getting started unreadable | The panel is left out until `G start` answers, and Still to do shows as it does without the panel |
| Getting started hidden | One quiet line "Getting started: <n> of <m> done · Show" in the panel's place; Still to do shows |
| Getting started, every step done | "All set" once, then neither the panel nor the line; Still to do shows |
| Job running | The meta line adds "<job title> is running" with a link that opens the job strip |
| Storage use loading or unreadable | The Storage row is left out until `G storage-use` answers; the panel shows the loading skeleton, or the error state "Could not read the storage use. <Hub's text>" with **Try again** |
| Nothing running low | No Running low card |
| History loading | A skeleton strip in each row; the title row's buttons wait |
| History unreadable | The strips are left out and the table stays as it is; a quiet line under the card's title "Could not read the history. <Hub's text>" with **Try again** |
| History not started | A dashed strip and "No history before <date>." |
| No filament used this month | No Filament line |

**Main action:** none permanent. When a check needs a look and has an action, that action is the page's one primary
button. **Run the checks again** is a ghost button. While Getting started shows and a step is Next, that step's button is
the one filled button of Overview, and a check's action is then a default button.

---

## 5. Printers

**Purpose.** See every printer's state and slots; add, test and set up printers, and keep them working. Two
families: Bambu Lab (feature "Bambu Lab printers", code name `printers`) and Klipper (feature "Klipper printers",
`klipper`). Address `#printers`.

**Data.** `G state` (`printers: {on, bambu, klipper, list}`); the per-printer calls listed with each control.

**Switched off** (neither feature on): section 2.5 with title "Printers are switched off" and sentence "Switch on Bambu
Lab printers or Klipper printers in Features to connect printers." The button opens `#features`.

### 5.1 Layout

```
Desktop
+----------------------------------------------------------------------------------------------------+
| Printers                                                                                           |
| Printers                                             [Find Klipper printers] [+ Add a printer] [...] |
| 3 printers · (*) 2 connected · ( ) 1 offline · (i) 1 found, not added                              |
|                                                                                                    |
|     PRINTER v           ADDRESS v            STATE v        SLOTS            CONNECTION             |
| [>] Workshop X1         192.0.2.40           (*) Connected  [#][#][#][ ] 3/4 Certificate pinned  [Test connection][...] |
|     Bambu Lab X1 Carbon SN 00M00A000000001                                   Slots mapped          |
| [v] Garage Voron        voron.example:7125   (*) Connected  [#][#] 2/2       API key (*) Set     [Test connection][...] |
|     +-- inline expansion ---------------------------------------------------------------------+   |
|     | TOOL SLOTS                                | ACTIONS                                     |   |
|     | T0 [#] Prusament PLA Galaxy Silver  47 %  | [Detect model and slots] [Map by loading filament] |
|     | T1 [#] Overture TPU Blue            71 %  | CHANGE                                      |   |
|     | Address            voron.example:7125     |  Rename · Change address ·                  |   |
|     | Moonraker API key  (*) Set                |  Replace Moonraker API key ·                |   |
|     | Lane data          [Auto|On|Off]          |  Clear Moonraker API key                    |   |
|     |                                           | REMOVE                                      |   |
|     |                                           |  [Forget printer]                           |   |
|     +-----------------------------------------------------------------------------------------+   |
| [>] Study A1 mini       192.0.2.41           ( ) Offline    No slot data while offline  [Test connection][...] |
|     /!\ Needs a look: The last slot mapping stopped twice. A report would help. [Collect a report]  |
| --- Found on the network, not added yet ------------------------------------------------------    |
|     mainsailos          192.0.2.57:7125      ( ) Not configured                 [+ Use this printer][Dismiss] |
|                                                                                                    |
| +-- Find Klipper printers -------------------+ +-- Klipper add-on ---------------------------+     |
| | Subnet (optional) [192.0.2.0/24  ] [Scan]  | | Installs the spool macros and Spoolwarden's |     |
| | Bambu Lab printers announce themselves;    | | Moonraker settings on a Klipper printer.    |     |
| | Klipper printers are found by a scan.      | | [Show the commands]                         |     |
| +--------------------------------------------+ +---------------------------------------------+     |
+----------------------------------------------------------------------------------------------------+

Tablet: columns Expand, Printer, State, Slots, Actions. Address and Connection move into the expansion.
        The two tool cards stack.
Phone:  each printer is a card:
+----------------------------------------------+
| Workshop X1                  (*) Connected   |
| Bambu Lab X1 Carbon                          |
| [#][#][#][ ]  3/4 loaded                     |
| [Test connection]                     [...]  |
| [v Details]                                  |
+----------------------------------------------+
        Header actions: [+ Add a printer] full width, then Find Klipper printers as a ghost button.
```

### 5.2 Printer collection

`collection` profile `table` in Console; one row per printer, then a group "Found on the network, not added yet" for
Klipper printers a scan found that are not configured (`configured: false`).

| Column | Content | Priority |
|---|---|---|
| Expand | Icon button with chevron, "Details for <name>", `aria-expanded`, `aria-controls` | P1 (on phone a ghost button "Details" at the card's foot) |
| Printer (sortable) | Name in weight 600; under it the model in `--muted`. When both families are on, a tag "Bambu Lab" or "Klipper" after the name. | P1 |
| Address (sortable) | `ip` (Bambu Lab) or `host:port` (Klipper) in `--mono`, or "No address yet" in `--muted`; under it "SN <serial>" (Bambu Lab) or "Moonraker" (Klipper). Hidden values read "Hidden while locked". | P3 |
| State (sortable) | Status badge and sentence from `state`, as the printer states table of `02-components.md` 7.1 gives them (the Klipper states `unknown_model`, `unauthorized`, `klippy_not_ready` and `connecting` included) | P1 |
| Slots | Slot strip of filament swatches with fill level and "<loaded> of <total> loaded"; a slot with a spool waiting for it (5.10) shows that spool's colour with a dashed ring; or "No slot data while offline"; or "No slots read yet" | P1 |
| Connection | Bambu Lab: "Certificate pinned" or "Certificate not pinned yet"; "Slots mapped" when mapped. Klipper: "Moonraker API key" with status badge "Set" (OK) or "Not set" (Note); "Lane data: <auto, on or off>" | P3 |
| Actions | Default button **Test connection** ("Test" on tablet) and icon button "More actions for <name>" (overflow menu) | P1 |

- Sorting by Printer (default, A to Z), Address or State, with `aria-sort` on the header. Not stored.
- A **message row** under a printer holds its latest inline result (test, mapping, report, save) and, when
  `report_why` is set, the problem line: warn shape, "Needs a look: <report_why>" and the primary button **Collect
  a report** (the row's one primary).
- The row expands in place (inline expansion of the detail region). On phone one row is expanded at a time; on
  tablet and desktop several may be. `#printers/<id>` expands that row and scrolls to it.

### 5.3 Row expansion

Two columns on desktop, one on tablet and phone.

| Part | Bambu Lab | Klipper |
|---|---|---|
| Live view | For a connected printer, the top of the expansion: state, job, progress, temperatures, alerts, **Show camera** and the print controls (5.10) | The same |
| Slots | Title "AMS slots". One line per slot: slot name (`--mono`), filament swatch, filament name, colour name, hex in `--mono` `--muted`, fill bar and percentage, and the slot's actions **Load**, **Unload** and **Clear slot** (5.10). An empty slot: hollow swatch and "Empty". A slot a spool is waiting for: the spool's name and "Waiting for the spool to load in <slot>." | Title "Tool slots", same lines |
| Facts (key-value list) | Address · Serial · Access Code "Saved (hidden)" or "Not set" · Certificate "Pinned" or "Not pinned yet" | Address · Moonraker API key, status badge "Set" or "Not set" · Lane data, segmented choice Auto / On / Off |
| Actions | Primary **Map slots**; default **Map by loading filament**. When `report_why` is set, the row's one primary is **Collect a report** in the message row (5.2), so Map slots here becomes a default button. Not configured: primary **Connect** instead of both. | Primary **Detect model and slots**; default **Map by loading filament** |
| Change (ghost buttons) | Rename · Change address · Replace Access Code · Collect a report · Saved reports | Rename · Change address · Set Moonraker API key or Replace Moonraker API key · Clear Moonraker API key (only when set) |
| Remove (apart, under a hairline, danger buttons) | Forget certificate (only when `pinned`) · Forget printer | Forget printer |

The row's overflow menu holds the same actions in the same order, with separators between Actions, Change and
Remove; danger items in `--bad`.

### 5.4 Controls

| Control | Type | Does | Endpoint |
|---|---|---|---|
| **Add a printer** | Primary button (header) | Opens the Add a printer drawer (5.6) | |
| **Find Klipper printers** | Default button (header; Klipper on) | Scrolls to the Find Klipper printers card and focuses Subnet | |
| **Download as CSV** | Item of the page menu (3.8) | Downloads the printers and their slots as `printers.csv` (2.10) | `G export/printers.csv` (code) |
| **Test connection** | Default button (row) | Inline spinner "Testing the connection to <address>…", then the result in the message row (5.8). One test per printer every 3 s: a press inside that time shows "Wait 3 seconds between tests." | `P printers/<serial>/test` (view) |
| **Map slots** | Primary (Bambu Lab, expansion) | Confirm dialog, then mapping (5.7) | `P printers/<serial>/map` (code); poll `G printers/<serial>/map` |
| **Stop** | Default button in the mapping message row | Stops the mapping | `P printers/<serial>/map/stop` (code) |
| **Map by loading filament** | Default button | Opens the Map by loading filament drawer (5.7) | `P printers/<serial>/manual-map/start` (code) |
| **Detect model and slots** | Primary (Klipper) | Inline spinner "Asking <name>…"; result "Detected <model> with slots <T0, T1>." or "Detected <model> (not confirmed by the printer) with slots <…>."; the Hub's `spoolman.warning` as a warn line, `message` as a Note line | `P printers/<serial>/detect` (view) |
| **Connect** / **Replace Access Code** | Primary (not configured) / ghost | Text entry dialog "Replace Access Code: <name>" | `P printers/<serial>/code` (code) `{access_code}` |
| **Set** / **Replace Moonraker API key** | Ghost | Text entry dialog "Moonraker API key: <name>" | `P printers/<serial>/api_key` (code) `{key}` |
| **Clear Moonraker API key** | Ghost | Confirm dialog, then clears | `P printers/<serial>/api_key` (code) with an empty key |
| **Lane data** | Segmented choice Auto / On / Off; hint "Publishes this printer's slots to Moonraker's lane data." | Saves on change; inline result "Lane data: <On>." A cancelled unlock puts the choice back. | `P printers/<serial>/lane_data` (code) `{mode}` |
| **Rename** | Ghost | Text entry dialog | `P printers/<serial>/rename` (code) |
| **Change address** | Ghost | Text entry dialog (Bambu Lab: with the Access Code, section 15); result "Address changed to <address>. <note> Test the connection to check it." | `P printers/<serial>/address` (code) |
| **Collect a report** | Ghost in the expansion's Change group; primary in the message row when `report_why` is set | Inline spinner "Collecting a report from <name>…"; result "Report saved: <name>. <note>" with a link **Saved reports** | `P printers/<serial>/report` (code) |
| **Saved reports** | Ghost | Opens the Saved reports drawer (5.7) | `P printers/<serial>/reports` (code) |
| **Forget certificate** | Danger | Confirm dialog with the Access Code (section 15) | `P printers/<serial>/unpin` (code) |
| **Forget printer** | Danger | Confirm dialog; on success the row leaves, toast "<name> forgotten.", focus moves to the page title | `P printers/<serial>/forget` (code) |
| **Use this printer** | Primary (found row) | Dialog "Use <name>" (5.5) | `P printers/<serial>/connect` (code) |
| **Test connection** | Default (found row) | As above | `P printers/<serial>/test` (view) |
| **Dismiss** | Ghost (found row) | Confirm dialog | `P printers/<serial>/forget` (code) |
| **Subnet** | Text field, `--mono`, label "Subnet (optional)", placeholder `192.0.2.0/24`, hint "Leave it empty to scan the Hub's own network. At most 256 addresses (a /24)." | | |
| **Scan** | Default button (the card's only button) | Inline spinner "Scanning <subnet> for Klipper printers…"; results (5.8); new finds join the "Found on the network" group | `P printers/scan` (code) |
| **Show the commands** | Default button (Klipper add-on card) | Loading skeleton with "Checking the signed release…", then a code block with the commands and Copy, and the caption "Run these on the printer. Klipper add-on <version>." | `P printers/pack` (view) |
| **Copy** | Ghost button in a code block | Copies; inline result "Copied." or, when the browser blocks it, "Copy is blocked here: select the text and copy it." | |

### 5.5 Dialogs

| Dialog | Title | Body | Fields | Buttons |
|---|---|---|---|---|
| Forget printer (Bambu Lab) | "Forget <name>?" | "Spoolwarden stops connecting to it and deletes its Access Code. To use it again, add it again." | | Cancel · **Forget printer** (danger) |
| Forget printer (Klipper) | "Forget <name>?" | "Spoolwarden stops connecting to it and deletes its Moonraker API key, if one is saved." | | Cancel · **Forget printer** (danger) |
| Dismiss | "Dismiss <name>?" | "It leaves this list. A new scan may find it again." | | Cancel · **Dismiss** (danger) |
| Forget certificate | "Forget the certificate of <name>?" | "The next connection trusts whatever certificate answers at <address> and remembers it. Do this only after the printer was reset or replaced." | Secret field "Access Code"; hint "On the printer: Settings > Network/LAN. The Hub needs it again to trust the new certificate." | Cancel · **Forget certificate** (danger) |
| Map slots | "Map the slots of <name>?" | "The printer changes its slot colours briefly and runs a short job with no motion. The colours are put back afterwards." | | Cancel · **Map slots** (primary) |
| Clear key | "Clear the Moonraker API key of <name>?" | "Spoolwarden then connects without a key. If Moonraker asks for one, the printer's test says so until a key is set." | | Cancel · **Clear key** (danger) |
| Rename | "Rename printer" | | Text field "Name", filled with the current name and selected | Cancel · **Rename** (primary) |
| Change address (Bambu Lab) | "Change address: <name>" | | Text field "IP address or name", `--mono`, filled; hint "For example 192.0.2.40 or printer.local. A name is kept as you type it." Secret field "Access Code"; hint "On the printer: Settings > Network/LAN. The Hub needs it again when the address changes." | Cancel · **Change address** (primary) |
| Change address (Klipper) | "Change address: <name>" | | Text field "Address", `--mono`; hint "For example voron.example. The port stays <port>." | Cancel · **Change address** (primary) |
| Access Code | "Replace Access Code: <name>" | | Secret field "Access Code"; hint "On the printer: Settings > Network/LAN." | Cancel · **Connect** (not configured yet) or **Replace Access Code** (primary) |
| Moonraker API key | "Moonraker API key: <name>" | | Secret field "Moonraker API key"; hint "Moonraker shows it in its settings." | Cancel · **Save key** (primary) |
| Use this printer | "Use <name>" | "Found at <host>:<port>." | Secret field "Moonraker API key (optional)" | Cancel · **Use this printer** (primary) |

Empty required fields are refused at the field before anything is sent: "Enter a name.", "Enter the printer's
address.", "Enter the Access Code shown on the printer.", "Enter the API key." The Hub's refusals show at the field
they concern, otherwise in the dialog above its buttons; the dialog stays open with the typed values.

### 5.6 Add a printer (drawer)

One guided add flow, for the first printer and every later one. Side drawer on desktop (420 px), full-height dialog on
tablet, bottom sheet on phone. Address `#printers/add`. Title "Add a printer". It is opened by **Add a printer** in
Printers and by the Getting started step of that name (4.2). Four steps; each has **Back** (default), and the drawer
keeps what was typed when the person goes back or forward. Cancel (default) closes; with typed values it asks "Leave
without saving?" (section 2.6).

**Step 1: Which printer?** The printer type: segmented choice "Bambu Lab" / "Klipper", only for the families whose
feature is on; with one family on, the step shows the found list only. Above the choice, "Found on your network": one
row per printer found, each with **Use this**, which fills the next step. Klipper printers come from the existing search
(`P printers/scan`, 5.4); Bambu Lab printers come from the Hub's own listener for printer announcements when it can
supply them (section 15).

| State of the list | Text |
|---|---|
| Searching | "Looking…" |
| Nothing found | "None found. Type its address in the next step." |
| The Hub cannot list Bambu Lab printers | The list holds Klipper printers only, and the sentence is "Bambu Lab printers are added by address." |

**Step 2: Its details.**

| Field | Type | Shown | Sent as |
|---|---|---|---|
| IP address or name | Text, `--mono`, placeholder `192.0.2.40 or printer.local`; filled from the found row | Bambu Lab | `address` |
| Access Code | Secret field with show/hide; hint "On the printer: Settings > Network/LAN > Access Code", and one more line when the model is known from the found row or the reply | Bambu Lab | `access_code` |
| Name (optional) | Text | Both | `name` |
| Serial (optional) | Text, `--mono`, upper case; hint "Read from the printer when left empty."; under "More" | Bambu Lab | `serial` |
| Address | Text, `--mono`, placeholder `voron.example`; filled from the found row | Klipper | `host` |
| Port | Number, `--mono`, default 7125 | Klipper | `port` |
| Moonraker API key (optional) | Secret field | Klipper | `api_key` |

**Step 3: Test, then add.** Main action **Add printer** (primary, drawer foot) tests first and says the result in
words, then adds → `P printers` (Bambu Lab) or `P printers/klipper` (code). Nothing is saved on a failed test unless
**Add anyway** is pressed.

| Result | What shows |
|---|---|
| Added | The printer is saved; toast "Added <name>."; the drawer goes to step 4. A `note` from the Hub joins the message of the new row. |
| Bambu Lab: the printer cannot be read | The add reads the printer's certificate and fails with the Hub's text when it cannot; the text stays at its field and the drawer stays open |
| Klipper: no answer | The Hub asks the printer for its info before it saves. Above the drawer's buttons: "The Hub could not reach a Klipper printer at <address>:<port>." with **Try again** and, beside it, **Add anyway** (for a printer that is switched off), which saves it without the test |
| "names itself <A>, not <B>" | At the address field: "The printer at <ip> calls itself <A>, not <B>. Check the address." |
| Serial cannot be read | At the serial field: "Spoolwarden could not read the serial. Type it in: on the printer, Settings > Device." |
| Bad address | At the address field: the Hub's text, which ends "On the printer: Settings > Network." |
| Other refusal | Above the drawer's buttons, the Hub's text |

Empty required fields are refused at the field before anything is sent (5.5).

**Step 4: Map its slots now?** One sentence: "Mapping tells the Hub which slot is which. Nothing heats or moves." **Map slots**
(primary) opens the existing map flow (5.7) for the new printer. **Later** closes the drawer on the new printer's row,
expanded with the message "Added. The Hub is connecting to it." and its Test connection button focused. The fifth
step of a guided add, loading a spool, is not here: a spool is loaded from the printer's live view (5.10).

### 5.7 Mapping and reports

**Map slots** (after the confirm). The message row shows step progress: "Mapping… step <n> of <m>" or the Hub's step
text, a determinate bar when the number of steps is known, and a default button **Stop**. `problems[]` show as error
lines, `notes[]` as Note lines, `report_why` as a warn line. End: "Mapped. Slots: <A1, A2, A3, A4>." (OK), or
"Mapping failed." (error) followed by "If mapping keeps failing, map it by loading each slot instead." and a default
button **Map by loading filament**. A mapping already running when the page loads (`mapping: true`) is picked up
and shown again. Mapping states from the Hub: `running` → step progress, `failed` → the failure lines, `not run`
→ nothing shown.

**Map by loading filament** (side drawer, 420 px, on desktop; full-height dialog on tablet; bottom sheet on phone;
address `#printers/<id>/load-map`). Title "Map <name>
by loading filament". The Hub leads; the drawer shows its view (`G printers/<serial>/manual-map`, every 2 s).

```
+-- Map Workshop X1 by loading filament ---------------- [x] +
| Load the spool for A2 to the nozzle.                       |  <- step.say
|                                                            |
| Did you load A2?                                           |  <- step.ask
| [Yes]   or   No, I loaded [ A3      v] [Save that]         |
| Nozzle [ Right nozzle v ]           (dual-nozzle printers) |
|                                                            |
|  POSITION   STATUS                                         |
|  A1         (*) Confirmed (A1, right nozzle)               |
|  A2         (o) Waiting                                    |
|  A3         (i) Entered by hand (A3)                       |
|                                                            |
| [Skip A2]                                  [Stop mapping]  |
+------------------------------------------------------------+
```

| Part | Text and endpoint |
|---|---|
| Sentence | `step.say`, or `summary` when finished |
| Question (the printer reports loads) | `step.ask`; primary **Yes** → `P printers/<serial>/manual-map/confirm`; "No, I loaded" select of positions and default **Save that** → the same endpoint with the chosen position; a "Nozzle" select "Right nozzle" / "Left nozzle" on dual-nozzle printers |
| Question (the printer does not report loads) | Select "The slot it is in" and primary **Save (not checked by the printer)** → `P printers/<serial>/manual-map/confirm` |
| Settling | Inline spinner "The printer reports a change; waiting for it to settle…" |
| Skip | Ghost **Skip <position>** → `P printers/<serial>/manual-map/skip` |
| Stop | Default **Stop mapping** → `P printers/<serial>/manual-map/stop`. Closing the drawer while it runs asks: title "Stop mapping <name>?", body "The positions confirmed so far are kept.", buttons **Keep mapping** (primary) · Stop mapping (danger) |
| Positions | Collection: Position, Status ("Confirmed (<label>, <nozzle> nozzle)", "Entered by hand (<label>)" with the info shape (`--info`, as the web app shows it), "Waiting", or the Hub's word) |
| Share offer (finished, `offer_report`) | "Share this map in a printer report, so other owners of this model benefit? Nothing is sent unless you choose to." Primary **Yes, show me how** and default **No thanks**, both → `P printers/<serial>/manual-map/offer` with the answer; after Yes the Hub's steps text shows in the drawer |

**Saved reports** (side drawer, 420 px, on desktop; full-height dialog on tablet; bottom sheet on phone, where the
collection's rows become stacked cards; address `#printers/<id>/reports`). Title "Saved reports: <name>". A collection with
Report (`--mono`), Size ("<n> KiB"), Made (`at`), and a ghost **Download** per row → `P
printers/<serial>/reports/<name>` (a file). Empty: "No report kept for this printer yet. Collect one when something
goes wrong." Foot: the Hub's `never` text in `--muted` (what a report never contains). Primary **Collect a report**
in the drawer foot.

### 5.8 Result texts

| Event | Shape | Text |
|---|---|---|
| Bambu Lab test, pinned and matching | OK | "Test passed: <ip> answers; its certificate matches the pinned one." |
| Bambu Lab test, not pinned yet | OK | "Test passed: <ip> answers. Its certificate is pinned at the first connection." |
| Bambu Lab test, certificate differs | error | "Test failed: <ip> answers, but its certificate differs from the pinned one. If the printer was not reset, check its address before adding it again." |
| Bambu Lab test, no answer | error | "Test failed: no answer from <ip>:8883 (<error type>). Check that it is on." |
| Klipper test, answers | OK | "Test passed: Moonraker at <host>:<port> answers; Klipper is <state>." |
| Klipper test, wants a key | warn | "Moonraker at <host>:<port> answers but wants an API key. Set it in this printer's details." |
| Klipper test, no answer | error | "Test failed: no answer from Moonraker at <host>:<port>. Check that the printer is on and the address." |
| Klipper test, not Moonraker | error | "Test failed: <host>:<port> answers, but not as Moonraker." |
| Every test | | Followed by the connection state as a status badge |
| Scan found | OK | "Found on <subnet>: <host:port>, …" with **Use this printer** on each new one |
| Scan found nothing | Note | "No Moonraker found on <subnet>." |
| Scan too soon | warn | "Wait <n> seconds between scans." |
| Scan running | warn | "A scan is already running. Wait for it to finish." |
| Scan subnet refused | error, at Subnet | "Use a private network of at most 256 addresses, for example 192.0.2.0/24." |
| Klipper add-on unavailable (409) | error, in the card | "The Klipper add-on commands are not available: <Hub's text>" |

### 5.9 States

| State | Text |
|---|---|
| Loading | Three skeleton rows |
| Empty (no printers, nothing found) | Empty state with the printer icon: title "No printers yet"; sentence "Bambu Lab printers on the network appear here once they announce themselves. Klipper printers are found by a scan." (only the sentences for families that are on); primary **Add a printer**; default **Find Klipper printers** (Klipper on) |
| Only one family on | The other family's tool card, tag and type choice are absent; one quiet line at the page foot: "Klipper printers are switched off. Switch them on in Features." (or "Bambu Lab printers are switched off. …"), with Features as a link |
| Locked | Addresses and serials read "Hidden while locked"; every change asks for the code in place; the live view shows state, slots and filament used, and its camera and controls ask for the code in place (5.10) |
| Row busy | The busy button shows an inline spinner and its working label ("Testing…", "Mapping…"); the row's other buttons stay usable |

**Main action:** Add a printer. Per row: Test connection (default), with Map slots or Detect model and slots as the
expansion's primary; a problem line's Collect a report outranks both.

### 5.10 The live view

**Purpose.** What the web app's printer page shows, in the printer's own Detail region (the inline expansion of 5.3),
so a person at the computer works in one page. Address `#printers/<id>`. A connected printer shows it above the facts
of 5.3; a printer that is offline shows the facts alone, with the line "No live status: the printer is offline."
The page has its own routes for it (section 15) that call the same printer code as the Hub's other interfaces; it does
not call the web app's routes, so the page's lock applies whether or not the web app is switched on.

```
Desktop: the expansion of Workshop X1
+--------------------------------------------------------------------------------------------------+
| (*) Printing: Benchy                                          [Pause] [Turn the light off]         |
| [==============----------------]  42 %                                    [Show camera] [Stop print] |
| Layer 80 of 190 · 1 h 12 min left · Nozzle 220 / 220 °C · Bed 55 / 55 °C                           |
| /!\ Printer alert 0300_0100                                                                      |
|                                                                                                  |
| AMS A · AMS 2 Pro                                                                                |
| A1 [#] Polymaker PolyTerra PLA  Charcoal Black #2B2B2E   62 %  In use  [Load] [Unload] [Clear slot] |
| A2 [#] Bambu Lab PETG HF Orange                                                                  |
|        Waiting for the spool to load in A2.                             [Load] [Clear slot]      |
| A4 [ ] Empty                                                            [Load] [Clear slot]      |
|                                                                                                  |
| Filament used                                                                      Last 7 days   |
| 12.4 g   Benchy · A1                                  2026-11-12 14:05                  [Undo]   |
+--------------------------------------------------------------------------------------------------+
Tablet: one column; the controls wrap under the progress.
Phone:  one column; each slot is a card with its actions on their own line; the camera opens under the controls.
```

| Part | Content |
|---|---|
| State | A status badge and the sentence from `state` (`02-components.md` 7.1), then the print state as a sentence with its shape: "Printing", "Paused", "Preparing", "Finished", "Print failed", "Idle", followed by ": <job name>" |
| Progress | While Printing, Paused or Preparing: the determinate bar (`02-components.md` 8.3) with the percentage in `--mono`, then "Layer <n> of <total> · <time> left", where <time> is "<h> h <m> min" or "<m> min" under an hour |
| Temperatures | "<name> <current> / <target> °C", joined by " · " |
| The printer's alerts | One error-shape line each: the printer's text, or "Printer alert <code>" |
| Camera | **Show camera** and **Hide camera**; a 16:9 box under the controls; MJPEG printers draw the picture, HLS printers play it; the box and its states are those of `04-web-app.md` 6.4 |
| Slots | The full slot strip (`02-components.md` 7.5), grouped by unit; each row has the slot's actions (below). A waiting slot shows the spool's colour with the dashed ring (`02-components.md` 7.3) and the line "Waiting for the spool to load in <slot>." |
| Filament used | Title "Filament used" and "Last 7 days", and the overflow menu "More actions for Filament used" with **Download as CSV** (2.10); the rows, newest first, up to 20: "<g> g" in `--mono`, "<job> · <slot>", the time in `--mono` `--muted`, and ghost **Undo** on each row that can still be undone; an undone row is struck through and ends "(undone)". Empty: "Nothing used in the last 7 days." The months are in Analytics (17). |

**Waiting.** A spool assigned to a slot that has not loaded yet (Bambu Lab printers) is shown wherever a slot is
shown: in the live view, in the slot strip of the Slots column (5.2) and in the result of a load. The state ends by
itself when the printer shows the load, or by **Unload** or **Clear slot**.

| Control | Shown when | Style | Does | Endpoint |
|---|---|---|---|---|
| **Pause** | Printing | Default | Result "Paused." | `P printers/<id>/command` (code) `{action: "pause"}` |
| **Resume** | Paused | Primary | Result "Resumed." | `{action: "resume"}` |
| **Stop print** | Printing, Paused or Preparing | Danger, apart at the end of the row | Opens "Stop the print?"; result "Stopped." | `{action: "stop", confirm: true}` |
| **Turn the light on** / **Turn the light off** | The printer reports a light | Ghost; the label says what pressing does | Result "Light on." / "Light off." | `{action: "light_on"}` / `{action: "light_off"}` |
| **Show camera** / **Hide camera** | The printer has a camera | Default | Shows or closes the box; closing the region, leaving the section or hiding the tab stops the stream | `G printers/<id>/camera.mjpeg` or `G printers/<id>/camera/<name>` (code; on a computer that is not trusted, with `?ticket=<ticket>` from `P printers/<id>/camera/ticket` on the first request, see Lock); **Hide camera** also calls `P printers/<id>/camera/close` |
| **Load** | Every slot | Default | Opens the Load dialog (below) | `P printers/<id>/slots/<slot>/load` (code) `{spool_id, dry_run}` |
| **Unload** | A spool is recorded in the slot | Default | Runs the dry run, then opens "Unload from <slot>?" | `P printers/<id>/slots/<slot>/unload` (code) `{dry_run}` |
| **Clear slot** | Every slot, whether a spool is recorded there or not | Ghost | Runs the dry run, then opens "Clear slot <label>?" | `P printers/<id>/slots/<slot>/clear` (code) `{dry_run}` |
| **Undo** (Filament used) | The entry can be undone | Ghost | Opens "Put it back on the spool?" | `P usage/<entry>/undo` (code) |
| **Download as CSV** (Filament used) | Always | Menu item | "Last 7 days", "Last 30 days" or "Last 12 months" of this printer as `usage.csv` | `G export/usage.csv?printer=<id>&days=<n>` (code) |

Controls that a printer does not have are not shown: a Klipper printer shows the same view and leaves out what the
Hub answers with `not_supported`. While a command is sent its button shows the working shape. When the printer refuses,
the result is the sentence in the reply's `message` as sent, or the Hub's text for a refusal (printer offline, no reply,
busy, slot in use, certificate changed, needs Developer Mode, no preset, write refused, already running).

**Clear slot and Unload** mean two things. **Clear slot** is "the Hub forgets which spool is in this slot": for a spool
the Hub does not know, or a record that is simply wrong. **Unload** is "I took this spool out". Both do this, in this
order: a spool waiting for the slot is no longer waiting; the spool recorded in the slot goes back where it was before
it was loaded; on a Klipper printer the slot's setting on the printer is cleared when the printer is online and can do
it. On a Bambu Lab printer what the printer shows for the slot is left as it is, and Clear slot's `printer_cleared` is
always false there. Afterwards the slot has no spool:
filament used from it is logged with no spool and taken off none, until the next Load, the next scanned assignment or
the slot's own tag sets a spool again.

| Dialog | Title | Body | Buttons |
|---|---|---|---|
| Stop the print | "Stop the print?" | "Stop <job> on <printer>? It cannot be resumed." (without a job name: "Stop the print on <printer>? It cannot be resumed.") | Cancel (focused first) · **Stop print** (danger) |
| Unload | "Unload from <slot>?" | "Unload <spool name> from <slot>? It goes back to <place>." and then, on a Bambu Lab printer, "Only the inventory changes; the printer's slot setting stays as it is.", on a Klipper printer, "The slot's setting on the printer is cleared." | Cancel · **Unload** (primary) |
| Clear slot | "Clear slot <label>?" | "The Hub forgets the spool recorded here. <Spool> goes back to <place>." (the second sentence only when a spool is recorded) and then, on a Bambu Lab printer, "The printer still shows the old filament for this slot until a spool is loaded." | Cancel · **Clear slot** (danger) |
| Put it back | "Put it back on the spool?" | "Put <g> g back on the spool? (<job>, <slot>, <time>)" | Keep · **Put it back** (primary) |
| Load into <slot> | "Load into <slot>" | The button **Use the last tapped tag**, "or", a search field "Brand, colour, material" with rows of opened and sealed spools. Before a pick: "Pick a spool: tap its tag on a reader, or search." After a pick, the plan lines of the dry run: "Load <spool> into <slot>", "Preset: <name or none>", "Nozzle: <mm> mm" ("Nozzle size not reported by the printer; assuming <mm> mm"), "Spool <n> now in <slot> goes back to <place>", and the Hub's problems as error lines. The tag lines: "Tag <id> is not linked to a spool." / "No tag read yet: tap one." | Cancel · **Load** (primary; disabled with "Pick a spool first." or "Working out the plan…") |

| Result | Shape | Text |
|---|---|---|
| Loaded | OK | "Loaded into <slot>." (or "Sent to <slot>. The printer accepted it but hasn't shown the change yet.") |
| Load waits for the printer (Bambu Lab) | Note | "Waiting for the spool to load in <slot>." |
| Unloaded | OK | "Unloaded <spool name> from <slot>. Moved back: spool <n> to <place>." |
| Slot cleared | OK | "Cleared slot <label>. Spool <n> is back on <place>." (without a spool: "Cleared slot <label>.") |
| A waiting assignment ended | Note | "No spool is waiting for <slot> any more." |
| Cleared on a Bambu Lab printer (`printer_cleared` is always false there) | Note | "The printer still shows the old filament for this slot until a spool is loaded." |
| Filament put back | OK | "Put <g> g back on the spool." |

**Undo after a slot action.** Load, Unload and Clear slot each end in the toast of 2.9 with **Undo** (for 10 seconds), beside
the result above, which stays. A Bambu Lab load that is still waiting for the printer is not undone by Undo but by
**Unload** or **Clear slot**, as before. Undoing a load or an unload puts the Hub's record back and not the printer's
own slot setting; the answer says "Put back. The printer still shows what it was set to."

**Lock.** Looking needs nothing: state, slots, waiting and filament used show on a Locked page. The camera, the print
controls, the light and every slot action need the page Unlocked or Trusted (section 2.1) and ask for the code in place.
**The camera's address.** On a trusted computer the page asks for the stream directly. Otherwise it first asks
`P printers/<id>/camera/ticket` with the setup code and gets `{ticket, expires_in: 60}`; the first camera request takes
`?ticket=<ticket>` (the stream's address, or the playlist's). That request spends the ticket, and the Hub answers it
with a cookie that is the **camera session**.

- **The cookie** is valid only for that printer's camera routes (its path is `/setup/api/printers/<id>/camera`) and is
  HttpOnly, Secure and SameSite=Strict. It names a session that the Hub keeps in memory for that printer for 10 minutes.
  Every camera request that carries it (a segment, the playlist again) moves the 10 minutes forward. It lets its holder
  do nothing but ask that camera. A Bambu Lab printer with an RTSP camera is served as a playlist with many segment
  requests; a Bambu Lab P1 or A1 and every Klipper camera are one stream. The rule is the same for both.
- **It ends** when the page closes the camera (**Hide camera**, closing the region, leaving the section or hiding the
  tab call `P printers/<id>/camera/close`, which needs only the cookie and answers `{closed: true}`), when 10 minutes
  pass with no camera request, when the Hub restarts, or when the printer is removed. Locking the page again does not
  cut a running picture; the next **Show camera** needs the setup code again.
- **At most 8 camera sessions** run at a time. A ninth ticket is refused with "Too many camera views are open. Close one
  first.", shown in place of the picture.
**State is read** every 2 seconds while the detail is open and the tab is visible (`G printers/<id>/live`, section 2.7);
the Printers list keeps its 10 seconds.

---

## 6. Recently added

**Purpose.** The newest spool additions with the photos that were taken, to check them, correct a record by hand or
with the Label Reader, and undo a correction. Address `#recent`; one record `#recent/<id>`. Code name: the intake
history (`intake/history`).

**Data.** `G intake/history` (view) → `{keep, photo_bytes, ai, count, records}`; `G intake/history/<id>` (view);
photos `G intake/history/<id>/photos/<n>`. Changes here never redraw the rest of the page.

### 6.1 Layout

```
Desktop: list
+--------------------------------------------------------------------------------------------------+
| Recently added                                                                                   |
| Recently added                                                    [All 5 | To check 2]           |
| The newest 20 additions are kept with their photos (14.2 MB now). · Label Reader (*) On          |
|                                                                                                  |
|  PHOTO  FILAMENT v                          ADDED v           STATE            SPOOL     CONFIDENCE    |
|  [img2] Polymaker PolyTerra PLA Charcoal Black 2026-11-12 14:05 As detected    Spool 214 /!\ Mostly high > |
|         From a phone photo                                                                Colour: medium |
|  [img1] Bambu Lab PETG HF Orange  x2        2026-11-12 09:41  Revised by AI    Spools 212, 213  High   > |
|  [doc ] Prusament PLA Galaxy Silver         2026-11-10 08:15  As detected      Spool 210  Not read     > |
+--------------------------------------------------------------------------------------------------+

Desktop: one record (#recent/214)
+--------------------------------------------------------------------------------------------------+
| Recently added / Spool 214                                      [< Back] [< newer] [older >]       |
| Polymaker PolyTerra PLA Charcoal Black                                                           |
| 2026-11-12 14:05 · From a phone photo · As detected · Spool 214                                  |
| +-- Photos (2) ------------------+  +-- Fields ----------------------------- [Edit by hand] --+   |
| | [photo] [photo]                |  | IDENTITY                 | WEIGHTS                       |   |
| +--------------------------------+  | Brand     Polymaker      | Net weight   1000 g           |   |
| +-- Revisions (1) ---------------+  | Name      PolyTerra ...  | Empty spool weight 140 g      |   |
| | Revision 1, 2026-11-12 14:09,  |  | Material  PLA            | Density      1.31 g/cm3       |   |
| | by hand: Empty spool weight    |  | Colour    [#] #2B2B2E  /!\ Medium                        |   |
| | 150 -> 140 g [Undo revision 1] |  | TEMPERATURES             | OTHER                         |   |
| +--------------------------------+  | Nozzle 210 °C ...        | Price per kg (empty) Not on label |
| +-- Record ----------------------+  +------------------------------------------------------+   |
| | Added   2026-11-12 14:05       |  +-- Ask the Label Reader to correct it -----------------+   |
| | Source  From a phone photo     |  | What is wrong?  [e.g. brand is Polymaker           ]  |   |
| | Spool   214 · Photos 2         |  | [Ask the Label Reader]                                 |   |
| +--------------------------------+  +------------------------------------------------------+   |
+--------------------------------------------------------------------------------------------------+

Tablet: list keeps Photo, Filament, Added, State; Spool and Confidence move under the filament name.
        Record: one column, Fields first, then Ask the Label Reader, Photos, Revisions, Record.
Phone:  list rows become cards (photo left, name, time, state badge, confidence line); record as on tablet,
        with the field groups stacked and the edit form's Save fixed at the bottom while editing.
```

### 6.2 List

| Column | Content | Priority |
|---|---|---|
| Photo | Photo thumbnail of the first photo (48 px square, rounded `--r-s`) with the photo count; "No photo" icon when none | P1 |
| Filament (sortable) | Link "<vendor> <name>" to `#recent/<id>`; "x<n>" when several spools; under it the source in words ("From a phone photo", "From the Weigh Station", "Added by hand", or the Hub's `source`). A record whose `spools` list is empty (its spools were removed since) reads "No spools" in `--muted` as the link text; it opens like any other record. | P1 |
| Added (sortable, default newest first) | `at` as `YYYY-MM-DD HH:MM`, `--mono` | P2 (under the name on phone) |
| State | Status badge: `detected` → "As detected", `revised_ai` → "Revised by AI", `edited` → "Edited by hand" | P1 |
| Spool | "Spool <id>" or "Spools <id>, <id>", `--mono`; "None" in `--muted` for a record with no spools | P3 |
| Confidence | Confidence display summary: "High", "Mostly high" with the less sure fields named, "Low: check these" with the fields, "Not read" for additions by hand | P2 (only when the Hub sends confidence; section 15) |
| Open | Chevron; the whole row opens the record | P1 |

- Header meta: "The newest <keep> additions are kept with their photos (<size> now)." with "Change" as a link to
  `#settings/label-reader`; then "Label Reader" followed by a status badge "On" or "Off".
  While Share corrections is on (10.5.1): then "Share corrections" with the badge "On" and the link "<n> waiting"
  to `#settings/label-reader`.
- Filter (segmented choice, header actions): "All <n>" / "To check <m>", where To check means medium or low
  confidence on any field. Shown only when the Hub sends confidence.
- More than 50 records: paged, 50 per page, with "Newer" / "Older" at the foot.
- **Download as CSV** is an item of the page menu (3.8): the records as `recent.csv` (2.10).

### 6.3 Record

| Card | Content |
|---|---|
| Header | Breadcrumb with the list as link; title "<vendor> <name>" (x<n>), or "No spools" for a record with no spools (its photos, fields and revisions still show; a change the Hub refuses because the spools are gone shows the Hub's text at the Save or Accept button); meta: time, source, state badge, spools. Actions: ghost **Back** (to `#recent`), ghost **Print labels** (only when the record has spools: opens the print page of 16.5 for all of the record's spools, every item), icon buttons "Newer record" and "Older record" (disabled at the ends) |
| Item choice | Only when the record has several items: segmented choice "Item 1", "Item 2", … with the line "Spools <ids> (filament <id>). Changes apply to all of them." |
| Photos | Photo thumbnails (96 px); pressing one opens the photo viewer (full width, Left and Right between photos, Escape closes, "Photo <n> of <m>"). No photo: "No photo was taken for this addition." |
| Fields | Key-value list in four groups. Identity: Brand, Name, Material, Colour (filament swatch and hex). Weights: Net weight, Empty spool weight, Density. Temperatures: Nozzle, Bed, Nozzle range, Bed range. Other: Price per kg, Line. Empty values read "(empty)" in `--muted`. Per-field confidence display next to the value when it is not high. Card action: default **Edit by hand**. |
| Fields, editing | The values become fields (text; numbers with unit). Foot: inline result, default **Cancel**, primary **Save changes**. Only changed fields are sent: `P intake/history/<id>/apply` (code) `{item, values}`. |
| Ask the Label Reader to correct it | Text area "What is wrong?", placeholder "e.g. brand is Polymaker", hint "The Label Reader reads the photos again with your note and suggests changes. Nothing changes until you accept." Default button **Ask the Label Reader** → `P intake/history/<id>/revise` (code) `{item, note}` |
| Suggestion | Change list (before → after per field), title "The Label Reader (<engine>) suggests <n> changes" or "The Label Reader changed nothing."; when no photo was kept: "No photo was kept for this record: the Label Reader worked from the saved values and your note." Primary **Accept** → `P intake/history/<id>/apply` (code) `{proposal}`; default **Discard** (nothing is sent) |
| Revisions | Revision list, newest first: "Revision <n>, <time>, by hand / by the Label Reader: <field old → new; …>", the note when there was one, "Filament <ids> has no spools left (not deleted)" when it applies; an undone revision is struck through and ends with "(undone)" (no badge). The newest live revision has default **Undo revision <n>** → `P intake/history/<id>/undo` (code) `{revision}`. Empty: "No revisions. Corrections by hand or by the Label Reader appear here." |
| Read facts | The lines of `02-components.md` 7.2 ("Read facts"): when read, read again, weighed and tag read, under the fields; a revision's note and device in the revision list; the filament lines in results |
| Record | Key-value list: Added, Source, State, Spool(s), Photos |

### 6.4 Results and states

| Event | Shape | Text |
|---|---|---|
| Save changes, nothing changed | Note | "Nothing changed." |
| Save changes | OK | "Saved <n> changes: <field names>." plus the Hub's filament sentences: "The spools now use filament <id> (new)." / "Filament <ids> has no spools left; it was not deleted." |
| Asking | inline spinner | "Asking the Label Reader… (up to a minute)" |
| Accept | OK | "Accepted. <n> fields changed; revision <r> keeps the old values." |
| Discard | Note | "Suggestion discarded. Nothing changed." |
| Undo | OK | "Revision <n> undone." |
| Empty note | error, at the text area | "Say what is wrong first, for example: brand is Polymaker." |
| No photo, only On this Hub on (409 `no_photo`, unreleased) | error | "No photo was kept for this record, and the On this Hub engine needs one. Switch on Cloud in Features, or correct the fields by hand." |
| Daily limit reached | error | The Hub's text, for example "Today's Cloud reads are used up. Correct the fields by hand, or raise Reads per day in Settings > Label Reader." |
| Editing or a suggestion shown, Share corrections on | Note, above the Save changes or Accept button | "Share corrections is on: this correction will wait on this Hub to be shared." |
| Save changes or Accept, Share corrections on | Note, after the result | "This correction is waiting to be shared." with the link **Corrections waiting** (`#settings/label-reader`) |
| The same, no photo kept for the record | Note | "Not shared: no photo was kept for this record." |
| The same, the reader did not take it | warn | "Saved. The correction is not waiting to be shared: <the Hub's reason>." The save itself never fails or waits because of sharing. |
| Undo, Share corrections on | (none) | The correction waiting follows the record: it holds the record's values as they are now, and is removed when nothing differs from the reading any more. |

| State | Text |
|---|---|
| Loading | Five skeleton rows; record: skeleton photos and field groups |
| Empty | Empty state with spool icon: "Nothing added yet" / "No spool has been added since the history started. Spools added from the web app, the app or the Weigh Station appear here." |
| Record not found (deep link to an old id) | Error state "This record is no longer kept. Only the newest <keep> are." with **Back to Recently added** |
| Label Reader off (`ai: false`) | The Ask card shows the off state: "The Label Reader is switched off. Correct by hand, or switch it on in Features on the Hub page." with link **Features**; Edit by hand works |
| Locked | Edit by hand, Ask, Accept and Undo ask for the code in place |
| Error | "Could not read the additions. <Hub's text>" + **Try again** |

**Main action:** none in the list (it is for reading); in a record, **Save changes** while editing, **Accept** while
a suggestion is shown, otherwise **Edit by hand** is a default button and there is no primary.

---

## 7. Devices

**Purpose.** Everything that connects to the Hub: phones and the app, Slicer Sync, the Weigh Station, Tag Readers,
and trusted computers; what version each runs, whether it is out of date, and each device's detail. Address
`#devices`.

**Data.** `G state` (`devices`, `readers`, `station`), `G devices`, `G device/<id>`, `G webapp`, `G trust`; when
Unlocked or Trusted also `P stations/requests` and `P trust/list`. `G state` keeps its `devices` and `readers` fields as
they are.

### 7.1 Layout

```
Desktop
+--------------------------------------------------------------------------------------------------+
| Devices                                                     [Link Slicer Sync ...] [+ Pair a phone] |
| 3 paired · 1 Tag Reader · 1 trusted computer · 1 out of date                                      |
| +-- Paired devices ---------------------------------------------------------------------------+ |
| |  DEVICE          KIND           VERSION   PAIRED            LAST SEEN                        | |
| |  Kitchen phone   Phone          0.5.2     2026-11-02 18:20  2026-11-12 14:05    [Open][Unpair] | |
| |  Bench scale     Weigh Station  0.5.0     2026-11-03 09:10  2026-11-12 14:03    [Open][Unpair] | |
| |  /!\ Out of date (0.5.0; the Hub is 0.7.0). On that machine: sudo spoolwarden update          | |
| |  Printer bench   Tag Reader     build 41  (made 2026-11-01) 2026-11-12 14:01    [Open]         | |
| |  This Hub's web app  Web app    0.5.2     (built in)        2026-11-12 14:06    [Open]         | |
| +---------------------------------------------------------------------------------------------+ |
| +-- Weigh Stations asking to pair ------+ +-- The web app on a phone ---------------------------+ |
| | No Weigh Station is asking to pair.   | | At home: https://192.0.2.10/intake  [QR]           | |
| +---------------------------------------+ | Away from home: https://hub.example/... [QR]       | |
| +-- Tag Readers ------------------------+ +----------------------------------------------------+ |
| | rd-3  Printer bench  made 2026-11-01  | +-- Trusted computers ------------------ (*) On -----+ |
| |                          [Revoke]     | | This computer is trusted (Desk PC).                 | |
| | Name [            ] [Make a token]    | | Desk PC (this computer) · last seen ... [Rename][Revoke] |
| +---------------------------------------+ +----------------------------------------------------+ |
+--------------------------------------------------------------------------------------------------+
Tablet: one column, cards in the order Paired devices, Weigh Stations asking to pair, The web app on a phone,
        Tag Readers, Trusted computers.
Phone:  one column; collections become stacked cards; QR blocks keep their size (14rem) and centre.
```

### 7.2 Paired devices

Collection (`table`):

| Column | Content | Priority |
|---|---|---|
| Device | `name`; built-in pairings show a tag "Built in" and the line "This Hub's own pairing" in `--muted`. A device that is out of date has the warn line of 7.9 under its name. | P1 |
| Kind | "Phone", "Slicer Sync PC", "Weigh Station", "Web app", "Tag Reader", "Home Assistant" or "Built in" (7.9) | P2 |
| Version | The version in `--mono` ("build <n>" for a Tag Reader), or "Version not known" in `--muted` (7.9) | P2 |
| Paired | `paired` as `YYYY-MM-DD HH:MM`, or "Unknown" | P3 |
| Last seen | `last_seen`, or "Never"; for a Weigh Station it says that the station is running (7.9) | P1 |
| Action | Ghost **Open** (7.10) and ghost **Unpair** (not on built-in rows, and not on a Tag Reader's row: its token is revoked in the Tag Readers card, 7.5) | P1 |

The Tag Readers that have used their token are rows of this list too, with the kind Tag Reader.

Header actions: primary **Pair a phone**; default **Link Slicer Sync**; overflow menu with **Link a Weigh Station**,
**Link Home Assistant** and, when the Weigh Station feature is on, **Pair the Weigh Station on this Hub**.

| Control | Does | Endpoint |
|---|---|---|
| **Pair a phone** | Opens the pairing dialog for a phone | `P pair` (code) `{kind: "phone"}` |
| **Link Slicer Sync** | Opens the pairing dialog for Slicer Sync | `P pair` (code) `{kind: "pc"}` |
| **Link a Weigh Station** | Opens the pairing dialog for a Weigh Station on another computer | `P pair` (code) `{kind: "station"}` |
| **Link Home Assistant** | Opens the pairing dialog for the Home Assistant integration, which may only read (the viewer role, `09-implementation-order.md` Stage 13) | `P pair` (code) `{kind: "home-assistant"}` |
| **Pair the Weigh Station on this Hub** | Starts pairing of the Hub's own Weigh Station; job strip follows | `P pair` (code) `{kind: "station"}`, then job `station_pair` |
| **Open** | The detail of the device, a Weigh Station's included (7.10) | `G device/<id>` |
| **Unpair** | Confirm dialog | `P devices/<id>/revoke` (code) |

**Pairing dialog** (dialog on desktop and tablet, bottom sheet on phone; address `#devices/pair`). Polls `G state`
every 3 s until a new device appears or the time runs out.

| Part | Phone | Slicer Sync | Weigh Station | Home Assistant |
|---|---|---|---|---|
| Title | "Pair a phone" | "Link Slicer Sync" | "Link a Weigh Station" | "Link Home Assistant" |
| Instruction | "Open the Spoolwarden app or the web app and scan this code, or type the pairing code." | "Paste this link into Slicer Sync when it asks for it." | "On the Weigh Station computer, run `sudo spoolwarden weigh-station pair`, then paste this link." | "In Home Assistant, add the Spoolwarden integration and type this pairing code when it asks. It can read the Hub and change nothing." |
| Main content | QR block (alt "QR code for pairing a phone", white quiet zone); when the Hub has no QR maker (`qr_svg` null), the link as a code block with Copy instead | The link as a code block with Copy | Code block with Copy for the command, then the link as a code block with Copy | The Hub's address as a code block with Copy, for adding it by address (Home Assistant also finds the Hub on its own); no QR block |
| Code | "Pairing code" and the code in `--mono` `--fs-2xl`, grouped for reading | same | same | same, six digits |
| Fingerprint | "Certificate fingerprint: the phone asks for two groups of it." and the groups of four in `--mono` | "Certificate fingerprint: check it matches." and the groups | same as Slicer Sync | same as Slicer Sync (Home Assistant shows the fingerprint to compare) |
| Time | Determinate bar counting down and "Expires in <n> min" | same | same | same |
| Waiting | Inline spinner "Waiting for the device…" | same | same | same |
| Done | OK result "Paired: <name>." The bar and code go; button **Done** (primary) | same | same | same |
| Expired | Warn result "The pairing code expired. Make a new one." with primary **Make a new code**, which sends the same `P pair` (code) `{kind}` again and shows the new code | same | same | same |
| Buttons | Cancel (closes; the code simply expires) | | | |

### 7.3 Weigh Stations asking to pair

A Weigh Station on another computer asks from its own screen; the list refreshes every 5 s while the section is
visible and the page is Unlocked or Trusted.

| State | Content |
|---|---|
| Locked | "A Weigh Station on another computer asks from its own screen. Requests are shown once the page is unlocked." and default **Unlock to show** |
| None | "No Weigh Station is asking to pair." |
| Request (one row each) | "<name> at <address> asks to pair. Its screen shows <ddd ddd>." (digits in `--mono` `--fs-l`); hint "Pair only if the Weigh Station shows the same six digits. If not, refuse it: someone else asked." Primary **Pair** → `P stations/requests/<id>/pair` (code), result "Paired <name>. It picks up its pairing within a few seconds."; default **Refuse** → `P stations/requests/<id>/refuse` (code), result "Refused <name>." |

A paired Weigh Station serves HTTPS with a certificate it made itself. At every start it tells the Hub its certificate's
fingerprint, its port and its version over the connection it already has, and the Hub then calls it only at that port
and accepts only that certificate; nobody types an address or a fingerprint for it. A Weigh Station on this Hub's own
machine is called at `http://127.0.0.1:5003`, which never leaves the machine. A station that has not been updated sends
no fingerprint and is still called over plain HTTP; so is a station that cannot make its certificate: it serves plain
HTTP as before and logs why in its own log. The Checks show a row for it (4.2). The Hub never goes back to plain HTTP
for a station whose certificate it has pinned: for such a station a missing or changed certificate is an error, and the
Checks show it (4.2). A paired Weigh Station also calls the Hub
every 5 minutes (`GET api/station/hello`), so its "Last seen" in Devices (7.2) means that it is running.

### 7.4 The web app on a phone

From `G webapp` → `{url, qr_svg, public_url, public_qr_svg}`.

| Part | Content |
|---|---|
| At home | "At home, open this address in the phone's browser:" the `url` in `--mono` with Copy and the default button **Open**, and its QR block (alt "QR code of the web app's home address"). **Open** opens the home address of the web app in a new tab; it is shown only while the web app's feature is on. |
| Hint | "The browser warns once about the Hub's own certificate: accept it to go on. This address works on the home network only." |
| Away from home (only with `public_url`) | "Away from home too:" the `public_url` with Copy and its QR block (alt "QR code of the web app's public address") |
| Keep it | "To keep it on an iPhone: tap Share, then Add to Home Screen." |
| Error | "Could not read the web app's address. <Hub's text>" + **Try again** |

### 7.5 Tag Readers

Code name: reader tokens (`readers`). A Tag Reader needs a token to reach the Hub; Flash a device makes one by
itself, so this card is for readers built by hand. It is where a token is made and revoked; a reader that uses its token
is also a row of Paired devices (7.2) with its build and last seen.

| Part | Content |
|---|---|
| Collection | Columns Name (P1), ID (`--mono`, P2), Made (`created`, P3), and ghost **Revoke** (P1) → confirm, `P readers/<id>/revoke` (code) |
| Empty | "No Tag Reader tokens yet. Set up a Tag Reader in Flash a device, and it gets one by itself." with link **Flash a device** |
| Store error | Error line with the Hub's `readers.error` |
| Make a token | Text field "Name", placeholder "e.g. printer bench"; default **Make a token** → `P readers` (code) `{name}` |
| New token | OK result "New Tag Reader token <id> (<name>):" then a code block with the token and Copy, and the warn line "Shown only this once. Put it in the reader's `src/secrets.h` as `READER_TOKEN`, then build and flash it." The token is cleared from the page when the section is left. |
| Pointer | Quiet line at the card foot: "Setting up a Tag Reader over USB is easier: Flash a device." (link) |

### 7.6 Trusted computers

Title "Trusted computers" with status badge "On" or "Off".

| Part | Content |
|---|---|
| Explanation | "A trusted browser needs no setup code for 90 days after its last use. It never skips a question such as Roll back. A new setup code keeps trusted computers trusted; revoke them here." |
| This computer | "This computer is trusted (<name>)." with default **Stop trusting this computer** → confirm, `P trust/<id>/revoke` (code) |
| List (On; loads by itself when Unlocked or Trusted) | Collection: Name ("(this computer)" after this one) P1; Made P3; Last seen with address ("the Hub itself" for loopback) P2; Runs out P2; row actions ghost **Rename** (text entry dialog → `P trust/<id>/rename` (code)) and ghost **Revoke** (confirm → `P trust/<id>/revoke` (code)) |
| Locked | "The list is shown once the page is unlocked." and **Unlock to show** |
| Empty | "No computer is trusted." |
| Card foot | Danger **Revoke all** (when the list has rows) → confirm, `P trust/revoke_all` (code); toggle "Trusted computers" (On/Off) → `P trust/enabled` (code) `{enabled}`; turning it off asks first |
| Off | "Trusted computers are off: every change needs the setup code." Toggle turns it on without asking. |

### 7.7 Dialogs

| Dialog | Title | Body | Buttons |
|---|---|---|---|
| Unpair | "Unpair <name>?" | "It can no longer reach the Hub until it is paired again." | Cancel · **Unpair** (danger) |
| Revoke Tag Reader token | "Revoke the token <id>?" | "A Tag Reader using it is refused from now on. Set it up again in Flash a device to give it a new token." | Cancel · **Revoke token** (danger) |
| Rename trusted computer | "Rename <name>" | Text field "Name", filled and selected | Cancel · **Rename** (primary) |
| Revoke one trusted computer | "Revoke <name>?" | "That browser needs the setup code again for every change." | Cancel · **Revoke** (danger) |
| Stop trusting this computer | "Stop trusting this computer?" | "This browser then needs the setup code for every change." | Cancel · **Stop trusting** (danger) |
| Revoke all | "Revoke every trusted computer?" | "Each one, this one included, needs the setup code again." | Cancel · **Revoke all** (danger) |
| Turn trusted computers off | "Turn trusted computers off?" | "Every trusted computer is forgotten, and each change needs the setup code. You can turn it on again here." | Cancel · **Turn off** (danger) |

### 7.8 States

| State | Text |
|---|---|
| Loading | Skeleton rows in each card; QR blocks as grey squares of their final size |
| Empty paired devices | "Nothing paired yet. Pair a phone to add spools from it." (primary stays **Pair a phone** in the header) |
| Built-in revoke refused (409) | Not reachable: built-in rows have no Unpair |
| Weigh Station feature off | **Pair the Weigh Station on this Hub** is absent; the other pairings stay |
| A device sends no version | "Version not known" in its row; it is never called out of date (7.9) |
| The Weigh Station cannot be reached | The detail says "The Weigh Station <name> does not answer. Check that it is on, then try again." |

**Main action:** Pair a phone.

### 7.9 Kind, version and out of date

**Kind.** Every row has a kind: Phone, Slicer Sync PC, Weigh Station, Web app, Tag Reader, Home Assistant, or Built in.
The page route `G devices` gives it as `kind` (`phone`, `pc`, `station`, `web`, `reader`, `home-assistant`, `builtin`).

**How the Hub learns kind and version.** Every client of ours sends one header on every call,
`X-Spoolwarden-Client: <kind>/<version>`, with the kind `android`, `slicer-sync`, `weigh-station`, `web` or `home-assistant`; the Hub keeps
the newest value with the pairing, beside "last seen". A Weigh Station also gives its version on its hello call. A Tag
Reader sends `X-Reader-Build: <number>` with its token to the web unit, which hands the build and the time of the
reader's last call to the Hub; the Hub keeps the newest values with the reader's entry. The web unit does this when a
reader's build changes and otherwise at most once a minute per reader, so a reader's "last seen" can be a minute old.
A device that sends nothing shows "Version not known"; a pairing without a kind shows its name alone.

**Check-in.** A Weigh Station calls its hello every 5 minutes, so its "Last seen" says that it is running, not that
it was last used; Devices shows "Last seen" for a station as for every other row.

**Out of date.** The row says it, in a warn line under the name, with what to do:

| Kind | Out of date when | The row says |
|---|---|---|
| Weigh Station | its version is lower than the Hub's | "Out of date (0.5.0; the Hub is 0.7.0). On that machine: sudo spoolwarden update" |
| Slicer Sync PC | its version is lower than the Hub's | "Out of date (<version>). Install the current Slicer Sync on that PC." |
| Phone (Android app) | its build is lower than the app the Hub offers | "Out of date. The app offers the update when it is opened." |
| Tag Reader | its build is lower than the firmware the Hub offers | "Out of date. Hold the knob for 4 seconds to update." |

A device whose version is not known is never called out of date, and neither is a kind this table does not list (Home
Assistant: its version is shown and nothing more). The Overview's Devices tile and one Checks row (group
Devices, Needs a look: "<n> devices are out of date.", 4.2) point to Devices. The Hub does not update a satellite
itself.

### 7.10 A device's detail

**Open** on a row opens the detail of that device in the Hub page itself (`#devices/<id>`, a side drawer on desktop, a
full-height dialog on tablet, a bottom sheet on phone). The Hub page draws it; no page of a device is passed through the
Hub, and nothing a device sends is ever served by the Hub as HTML, script or style.

**The Weigh Station's detail.** It shows the station's status (the tag, the scale, the last weight, the panel and its
version, the air, the step of a running intake and the photo) and its settings: sounds (beep, speech, voice, volume),
the panel (the yellow and red swap) and **which lamp lights for which step** of an intake, chosen from the panel's lamps
or Off. The settings are kept on the station in a file of their own in its state folder and win over the values the
installer wrote; **Back to the installed values** removes them and the installed values apply again. Looking needs
nothing; saving a setting needs the page Unlocked or Trusted and asks for the code in place. The station takes a setting
change only with a proof the Hub can give because the station is paired.

**What the Hub takes from a station is checked data.** The Hub reads the status and the settings from the station and
shows what passes these checks:

- JSON only (`application/json`), at most 256 KiB, a 5 second limit; any redirect is an error; only to the stored host
  and port of that pairing, over the pinned certificate when the station has one (7.3).
- Every text from a station is shown as text, never as markup.
- A setting's `id` must match `[a-z0-9_.-]{1,40}`, its `kind` is one of `switch`, `choice`, `number`, `text`, a `label`
  is at most 80 characters, and there are at most 60 settings. Anything else is dropped, and the detail says "Some of
  this station's settings could not be shown."
- The photo is taken only as `image/jpeg`, at most 4 MiB, through `G device/<id>/photo` (open). `G device/<id>` says
  with `photo` whether there is one.

**The station's own page.** The detail has **Open this station's page**: a new tab to the station's own address
(`rel="noopener noreferrer"`), never fetched, framed or proxied by the Hub. Its hint: "Your browser asks once whether to
trust this station's certificate." It is shown for any device whose `G device/<id>` gives an `own_page`; a Tag Reader, a
phone and the Slicer Sync PC give none and have the Hub-drawn detail only.

- The link needs the page Unlocked or Trusted. **Open this station's page** calls `P device/<id>/open`: the Hub asks the
  station for a one-time ticket and answers `{address: "<own_page>#ticket=<ticket>"}`, which the page opens.
- The station's page hands the ticket to the station, which answers with a session cookie of its own, on its own origin,
  for 60 minutes; with it that browser may read the status and change the settings there. A ticket works once, within
  60 seconds, and travels after `#`.
- Without a ticket or a session the station's page says only: "Open this page from the Hub: Devices, this station, Open
  this station's page."
- The station serves its page's own files (HTML, script, stylesheet) to any address on the home network; its data
  routes (`/state`, `/settings`, `/photo`, `/last-tag`) answer only its allow-list or a browser with a session.

**Other devices.** The detail of a device that gives no `own_page` is:

| Device | The detail |
|---|---|
| Tag Reader | Name, build, last seen, and "Its settings are changed in Flash a device." with the link **Flash a device** (`#flash`) |
| Phone, Slicer Sync PC, Web app, Home Assistant | Kind, version, paired, last seen |

A Label Reader on another machine is not a paired device; Settings > Label Reader stays its place (10.5). The Weigh
Station voice group of Settings (10.10) links to the station's detail, and the voice is one value: the station's own
file wins, and the group reads it through `G device/<id>` when the station answers.

| Control | Does | Endpoint |
|---|---|---|
| **Open** (any row) | Opens the detail | `G device/<id>` (open; `{device, status?, settings?, own_page?, photo}`) |
| The photo | Shows the station's photo | `G device/<id>/photo` (open; `image/jpeg`) |
| A setting in the detail | Saves it on the station | `P device/<id>/settings` (code) `{<setting id>: <value>}` |
| **Back to the installed values** | Removes the station's own values; result "The installed values apply again." | `P device/<id>/settings` (code) `{reset: true}` |
| **Open this station's page** | Opens the station's own address in a new tab, with the ticket | `P device/<id>/open` (unlocked) → `{address}` |

---

## 8. Slicer presets

**Purpose.** Filament presets built for Bambu Studio and Orca Slicer from the Filament Catalog and the spools, the
state of Slicer Sync on the PC, and updates waiting to be accepted. Address `#presets`. Code name `presets`.

**Data.** `G presets` (view) → `{on, lines, lines_error, build, presets, orca_presets, last_attempt, installed, pc,
waiting_text, updates, stale, orca_stale, problems}`.

**Switched off:** section 2.5, title "Slicer presets are switched off", sentence "Switch on Slicer presets in Features
to build filament presets for Bambu Studio and Orca Slicer."

### 8.1 Layout

```
Desktop
+--------------------------------------------------------------------------------------------------+
| Slicer presets                                                                     [Build now]   |
| Last build 2026-11-12 03:12 · Presets: 46 (12 for Orca Slicer) · (*) Slicer Sync reported in      |
| +-- Build ---------------------------------------------+ +-- Updates -------------------------+  |
| | Last build 2026-11-12 03:12. Presets: 46 (12 for Orca | | 3 updates are waiting. Lines with   |  |
| | Slicer). Problems: 0.                                 | | updates: 2. Presets already in your |  |
| | (*) Slicer Sync has reported in.                      | | slicers are never replaced unless   |  |
| | Delete by hand in Bambu Studio: Generic PLA (old)     | | [Show what would change]            |  |
| | [Bring back deleted presets]                          | |                                     |  |
| +-------------------------------------------------------+ +-------------------------------------+  |
| +-- Product lines ------------------------------------------------------------------------------+ |
| |  LINE                       MATERIAL  PRESETS  BAMBU STUDIO PARENT        ORCA SLICER PARENT    | |
| |  Polymaker PolyTerra PLA    PLA       4        Bambu PLA Basic (catalog)  Generic PLA   [Set parent v] | |
| +-----------------------------------------------------------------------------------------------+ |
+--------------------------------------------------------------------------------------------------+
Tablet: Build and Updates stack; Product lines keeps Line, Presets and the action; parents go into the expansion.
Phone:  one column; product lines become cards.
```

### 8.2 Cards and controls

**Build.**

| Part | Content |
|---|---|
| Summary | "Last build <stamp>. Presets: <n> (<m> for Orca Slicer). Problems: <k>." or "No build yet." |
| Last attempt failed | Error line: "The last preset build failed: <error>" |
| Waiting | Note line with `waiting_text` |
| Slicer Sync | Status badge "OK" with "Slicer Sync has reported in.", or "Not configured" (Note) with "Slicer Sync is not set up. Link it in Devices." (link to `#devices`) |
| Problems | List of `problems` as error lines |
| Delete by hand | Lines "Delete by hand in Bambu Studio: <name>" / "Delete by hand in Orca Slicer: <name>" for `stale` / `orca_stale`, under the sub-title "Old presets to delete by hand" |
| **Build now** | Primary (section header) → `P presets/build` (code); inline result "A build was asked for. It runs in a moment." |
| **Bring back deleted presets** | Ghost → `P presets/restore_deleted` (code); inline result "The next build brings back the presets deleted in Bambu Studio. A build was asked for." |

**Updates** (address `#presets/updates`).

| Part | Content |
|---|---|
| Summary | "<n> updates are waiting<, <a> accepted: Slicer Sync writes them next>. Lines with updates: <m>. Presets already in your slicers are never replaced unless you accept here." ("1 update is waiting") or "No updates. Presets already in your slicers are never replaced on their own." |
| Your own presets | When `updates.yours`: "<n> generated presets have the same name as one of your own in Bambu Studio. Yours stay: rename or delete yours to get the generated one." |
| **Show what would change** | Default → `P presets/updates` (code) `{all: true, dry_run: true}`; shows a change list: "<Orca Slicer / Bambu Studio>: <name> (in your file <file>): <up to 6 keys>, …"; inline result "<n> updates would be accepted; nothing was changed yet." or "No updates to accept." |
| **Accept these** | Primary, only under a shown list → `P presets/updates` (code) `{all, dry_run: false, stamp, names}`; result "<n> updates accepted. Slicer Sync writes them at its next run, after its backup." |
| Stale list (409) | Warn: "The updates changed since this list was shown. Show them again." and the list is cleared |

**Product lines** (collection, `table`).

| Column | Content | Priority |
|---|---|---|
| Line | "<vendor> <product>", weight 600 | P1 |
| Material | `material` | P2 |
| Presets | count | P1 |
| Bambu Studio parent | "<name> (<source>)" or "None" | P3 |
| Orca Slicer parent | the same, only when Orca presets exist | P3 |
| Action | Default button **Set parent** with a small menu "Bambu Studio" / "Orca Slicer" (only Bambu Studio when no Orca presets) | P1 |

**Set parent dialog.** Title "Parent preset for <vendor> <product>" with a sub-line "<Bambu Studio / Orca Slicer>,
<material>". Reads `G presets/parents?material=<m>&target=<t>`. When `parents` is empty: "Slicer Sync has not
reported any parent presets yet. It reports them each time it runs." and only **Close**. Otherwise a select "Parent
preset" (current one chosen) and buttons Cancel · **Save parent** (primary) → `P presets/lines/<id>/parent` (code)
`{parent, target}`; result in the row "Saved. A build was asked for."

**Menu.** The page menu (3.8) also holds **Download as CSV**: the product lines as `lines.csv` (2.10).

### 8.3 States

| State | Text |
|---|---|
| Loading | Skeleton summary lines and three skeleton rows |
| Lines error | Error state in Product lines: "Could not read the product lines. <lines_error>" |
| No lines | "No product lines yet. They are made from the filaments in Spoolman at the next build or when spools are added." |
| Error | "Could not read the Slicer presets. <Hub's text>" + **Try again** |

**Main action:** Build now.

---

## 9. Features

**Purpose.** Choose what this machine is (its setup) and switch features on and off. Every change is shown before it
is made and then applied in the background. Address `#features`. Code names: `modes` and `modules`.

**Data.** `G state` (`mode`, `modes`, `modules`); previews from `G modules/preview?mode=<m>` and
`G modules/preview?name=<n>` (view).

### 9.1 Names

| Setup (code name) | Name | One line |
|---|---|---|
| `server` | Hub | "The Hub: inventory, printers, Slicer presets and this page." |
| `all-in-one` | Hub with Weigh Station | "The Hub, with the scale and tag reader plugged into this machine." |
| `station` | Weigh Station only | "Only the scale and tag reader; the Hub runs on another machine." |
| (none of the three) | Custom | "Features chosen one by one." |

| Feature (code name) | Name | What it does (shown in the row) |
|---|---|---|
| `spoolman` | Spoolman | "Runs the Spoolman filament database on this machine." |
| `server` | Hub service | "Pairing, the inventory, the API and this page." |
| `ai_intake` | Label Reader: Cloud (Claude) | "Claude reads spool labels from photos. Needs an Anthropic API key." |
| `local_intake` | Label Reader: On this Hub | "A label reader that runs on this Hub or another computer at home." |
| `printers` | Bambu Lab printers | "Finds Bambu Lab printers, follows use, maps slots, shows the camera." |
| `klipper` | Klipper printers | "Connects Klipper printers through Moonraker: spool loads, use, camera." |
| `presets` | Slicer presets | "Builds filament presets for Bambu Studio and Orca Slicer, for Slicer Sync." |
| `library` | Filament Catalog | "Downloads the catalog of known filaments, then checks for updates daily." |
| `backup` | Nightly backup | "Backs up the spools, settings and state every night." |
| `station` | Weigh Station | "USB scale and tag reader on this machine." |
| `web` | Web access | "The web app and Claude's connector at a public https address." |
| `remote` | Remote access | "Gets a certificate for the public address (nginx, certbot)." |
| `orders` | Order history | "Keeps an order history for shop tools." |
| `updates` | Automatic updates | "Checks daily for a new signed release, installs it and keeps the one before." |

A feature the Hub reports that is not in this table is shown with the Hub's `title` and `description`.

### 9.2 Layout

```
Desktop
+--------------------------------------------------------------------------------------------------+
| Features                                                                                          |
| Setup: Hub · 9 of 14 on                                                                           |
| +-- Setup -------------------------------------------------------------------------------------+ |
| | (o) Hub                         ( ) Hub with Weigh Station        ( ) Weigh Station only (dimmed) | |
| |     The Hub: inventory, ...         The Hub, with the scale ...       Only the scale ...        | |
| | A Weigh Station only machine has no Hub page. To make one, on that machine run                 | |
| |   sudo spoolwarden features setup weigh-station --hub <the Hub's address>          [Copy]      | |
| +----------------------------------------------------------------------------------------------+ |
| +-- Features -------------------------------------------------------- [On 10 | Off 4 | All] ----+ |
| |  FEATURE                     STATE     WHAT IT DOES                           NEEDS             | |
| |  Label Reader: Cloud (Claude)  Uses AI  (*) On  Claude reads spool labels from photos.  Hub service  [Turn off] | |
| |  Klipper printers            ( ) Off   Connects Klipper printers through ...  Hub service  [Turn on]  | |
| +----------------------------------------------------------------------------------------------+ |
|  Features are applied in the background. [Apply the features again]                              |
+--------------------------------------------------------------------------------------------------+
Tablet: setups as three stacked choice cards; the Features table keeps Feature, State and the button;
        What it does goes under the name, Needs into the expansion.
Phone:  features as cards: name, badge, one line, button.
```

### 9.3 Controls

| Control | Type | Does | Endpoint |
|---|---|---|---|
| Setup | Choice cards (one per setup), the current one checked. A setup that cannot run a Hub page (`here: false`) is disabled with tooltip "A machine with this setup has no Hub page." | Choosing one opens the preview drawer for the setup | `G modules/preview?mode=<m>` (view) |
| Features filter | Segmented choice "On <n>" / "Off <m>" / "All" (default All) | Filters the collection | |
| **Turn on** / **Turn off** | Default button per row | Opens the preview drawer for that feature | `G modules/preview?name=<n>` (view) |
| **Apply the features again** | Ghost button under the collection | Re-applies the current features in the background; inline result "Applying the features again…" | `P apply` (code), job `apply` |

Collection columns: Feature (name, and a tag "Uses AI" for `optional_ai`) P1; State, status badge "On" / "Off" P1;
What it does P2; Needs ("Needs <list>" in `--muted`) P3; button P1.

### 9.4 Preview drawer (the confirmation)

Side drawer on desktop, full-height dialog on tablet, bottom sheet on phone. Address `#features/<name>` or
`#features/setup-<mode>`.

| Part | Content |
|---|---|
| Title | "Turn on <feature>?" / "Turn off <feature>?" / "Change the setup to <setup>?" |
| Notes | The Hub's `notes`, one per line ("Turns on: …", "Turns off: …") |
| Corrections waiting | Only when turning off Label Reader: On this Hub while corrections are waiting (10.5.2): a warn line "Deletes <n> corrections waiting to be shared. Send them first in Settings > Label Reader, or go on." They are kept by the reader and go with it. |
| Afterwards | "On afterwards:" and the list of feature names, or "Nothing" |
| Settings it needs | One labelled field per `needs` item: the label from the item's `prompt` (for example "Public https address of the web app", placeholder `https://hub.example/filament`); required |
| Label Reader lead-in | Only when turning on Label Reader: On this Hub: the line "After this, install the reader in Settings > Label Reader (a download)." |
| Refused | Error banner with the Hub's `refused` text, rewritten when it matches: "This page belongs to the Hub service. To switch it off, run on the Hub: `sudo spoolwarden features off hub`." Apply is then absent. |
| Remote access while the Hub holds port 443 | Refused before anything is changed: "Remote access needs port 443, and the Hub is using it. Move the Hub to another port first: Settings > Network and addresses, Hub port." with a link to `#settings/network`. Apply is absent. The Hub never moves by itself. |
| Loading | Skeleton lines, screen reader "Reading what changes." |
| Buttons | Cancel · **Apply** (primary) → `P modules/mode` (code) `{mode, settings}` or `P modules` (code) `{name, on, settings}` |
| Result | Reply `changed: true`: the drawer closes, toast "Saved; applying… Follow it in the job panel.", the job strip follows job `apply`. `changed: false`: inline "Nothing to change." and the drawer stays. |
| After Label Reader: On this Hub is switched on | When the job ends well and the reader is not installed, the page goes to Settings > Label Reader by itself, with the install plan in view (10.5), and shows the toast "Label Reader switched on. Install it here to finish." If the person has left Features meanwhile, Overview shows the Label Reader banner instead (4.2). A failed job changes nothing here: the job strip says so as it does for every feature. |

**Main action:** none permanent; Apply in the drawer.

### 9.5 States

| State | Text |
|---|---|
| Loading | Three skeleton choice cards, six skeleton rows |
| Job running (`apply`) | Every Turn on / Turn off and the setup cards are disabled with tooltip "Wait for the current change to finish."; a banner "Applying the changes… Follow it in the job panel." |
| Hub service row | Its button is absent; the row reads "Always on while this page is open." |
| Label Reader: On this Hub is on and the reader is not installed | The row says "Not installed yet" with the link **Finish in Settings** → `#settings/label-reader` |

---

## 10. Settings

**Purpose.** Everything about how the Hub behaves, in ten groups, each with at most one Save. Address `#settings`;
one group `#settings/<group>`.

**Data.** `G settings/general` (view) → `{values, station_on, remote_on, web_on, spoolman_external, intake_history,
spoolman_url}`; `G state` (`anthropic`, `passphrase`, `web`, `station`); `G library`; `G library/local`; when
Unlocked or Trusted, `P backups/list`; `G alerts` for Alerts. Each group reads only its own
data again after its own save.

### 10.1 Layout and sub-navigation

```
Desktop: one scrolling page, sticky sub-navigation on the left of the content
+--------------------------------------------------------------------------------------------------+
| Settings                                                                                          |
| One Save per group. Appearance and Weigh Station voice apply as you choose.                      |
| +--------------------------+ +-- General -------------------------------------------------------+ |
| | Appearance               | | Display name        [Workshop hub                 ]               | |
| | General      /!\ Unsaved | | Spoolman address    [http://spoolman.example:7912 ]               | |
| | Storage locations        | |                       /!\ Unsaved changes   [Save general]       | |
| | Alerts                   | +------------------------------------------------------------------+ |
| | Label Reader             | +-- Storage locations ---------------------------------------------+ |
| | Backups and restore      | | ...                                                              | |
| | Network and addresses    |                                                                       |
| | Web passphrase           |                                                                       |
| | Filament Catalog         |                                                                       |
| | Weigh Station voice      |                                                                       |
| +--------------------------+                                                                       |
+--------------------------------------------------------------------------------------------------+
Tablet: the sub-navigation becomes a row of chips under the page title that scrolls sideways inside its own box;
        the current group's chip is marked as the page scrolls.
Phone:  Settings opens on the list of groups (a collection of rows: group name, one-line state, chevron).
        A group opens on its own page (#settings/<group>) with a Back link "Settings"; its Save is fixed at
        the bottom above the bottom bar while the group has unsaved changes.
```

- The sub-navigation is the Settings sub-navigation component: each entry links to `#settings/<group>`; the current
  group (by scroll position on desktop and tablet) has `aria-current="true"`; a group with unsaved edits shows the
  dirty mark of `02-components.md` (triangle, warn): "Unsaved" on its entry, "Unsaved changes" on its title row and
  in its foot.
- Group order is fixed: Appearance, General, Storage locations, Alerts, Label Reader, Backups and restore, Network
  and addresses, Web passphrase, Filament Catalog, Weigh Station voice. (Alerts sits fourth, after Storage locations;
  its section is 10.13 only so that the numbers of 10.5 to 10.12 stay as they are.)
- Each group is a form group card: icon, title, one-line description, optional status badge at the right, the
  fields as label-and-control rows (label left 200 px on desktop, above the control on tablet and phone), a foot
  with the inline result at the left and the group's Save at the right.
- Phone list of groups, one-line states: Appearance "<Light/Dark/System> · <theme>"; General "<display name>";
  Storage locations "<n> locations"; Alerts "<n> of 8 on"; Label Reader "<engine order in words>", followed by " · <n> corrections
  waiting" when there are any; Backups and restore "Last: <time>" or
  "Unlock to show"; Network and addresses "<public address>" or "No public address"; Web passphrase "Set" / "Not
  set"; Filament Catalog "<version>" or "Not downloaded"; Weigh Station voice "<Piper / espeak-ng>" or "Switched off".

### 10.2 Appearance

Description: "How this page looks and which language it uses on this device." Per device; needs no setup code, except
the last field.

| Field | Type | Does | Stored / endpoint |
|---|---|---|---|
| Light, dark or system | Appearance control (segmented choice with icons), hint "System follows this device's light or dark setting." | Applies at once | `localStorage` `spoolwarden.appearance` (foundations section 5) |
| Theme | Theme picker: four preview tiles Console "Dense and technical", Workbench "Calm cards", Palette "Colourful and roomy", Panes "Simple lists"; the current one checked | Applies at once, no reload | `localStorage` `spoolwarden.look` (foundations section 6.2) |
| Language | Select: **Automatic** (the default), then every language installed on the Hub, each named as its own language names it ("English", "Русский", "Deutsch (machine-translated)"); hint "Automatic uses this browser's language if the Hub has it, otherwise the Hub's language." | Applies at once: the page loads that language's texts and draws itself again | `localStorage` `spoolwarden.language`; the texts from `GET api/strings/<code>.js` (section 15) |
| Theme for new devices | Select of the four themes, hint "Used by browsers and phones that have not chosen a theme." | Saved with the group's Save | Section 15 (no endpoint yet) |

Save: **Save theme for new devices** (only this field needs it; the button is enabled only while it changed).
Inline result for the three device fields: none (the change is the feedback); screen reader "Theme: <name>." and
"Language: <name>." The page's `lang` is the code of the language in use, and its plural forms, dates and numbers follow
that language (`07-accessibility.md` SR-1); where the Hub has no pack for a person's language, Automatic shows the Hub's
language. Which language the Hub itself uses is set in General (10.3). Right-to-left languages are not supported.

### 10.3 General

Description: "The Hub's name, its language and its Spoolman database."

| Field | Type | Key / endpoint | Notes |
|---|---|---|---|
| Display name | Text | `server_name` → `P settings/general` (code) | Shown in the top bar and the document title. Required: "Enter a name for the Hub." |
| Spoolman address | Text, `--mono`, placeholder `http://spoolman.example:7912`; only when Spoolman runs on another machine (`spoolman_external`) | `P settings/spoolman` (code) `{url}` | Shows the address in use (hidden parts as the Hub sends them). Hint "A new address must answer as Spoolman before it is saved. Spoolwarden then uses that database for everything." Saved by the group's Save, after the other field; the Hub checks it first, the field shows "Checking that Spoolman answers…" meanwhile. Refusal at the field: "Nothing was changed: no Spoolman answered at that address (<why>)." Success applies in the background (job `apply`). |
| Language | Select: "English" and every language installed on the Hub, named as in 10.2; hint "The language of the Hub's own texts and of devices set to Automatic." | `P settings/language` (code) `{hub}` | The language the Hub's own texts (alert titles and texts, Checks rows, refusals) are written in, and the default of every interface set to Automatic (10.2). It applies at once with its own inline result "Language: <name>." and is not part of **Save general**. |
| Get more languages | Ghost button, opens the dialog below | `G languages` (view) | Lists the languages of this Hub's release that are not installed yet. |
| Demo | While off, the default button **Try the demo**, hint "Look around the whole product on made-up data. Only on a Hub with no spools and no printers."; while on, the line "The demo is on." and **Leave demo** | `P demo` (code) `{on}` | Rules, banner, question and what answers "Not in the demo." are in 3.9. It has its own inline result and is not part of **Save general**. |

Save: **Save general** (Display name and Spoolman address).

**Get more languages.** A dialog (a sheet on a phone) titled "Get more languages". It lists, from `G languages`
(`available`, the packs of this Hub's release), one row per language: its name, with "(machine-translated)" after it
when no speaker of the language has read the pack yet, how much is translated ("<n> % translated"), and the default
button **Install**. A language that is installed shows the badge "Installed" and a ghost button **Remove**; English is
inside the product and is never listed. **Install** (`P languages/<code>/install`, code) starts a job, as the Filament
Catalog's update does, and the job strip follows it. The Hub checks the pack by the rules of `spoolwarden language
check` (`06-command-line.md` 9.27) before it keeps it in its state folder; a pack that fails is not installed and the
result is "<name> was not installed: <the check's first sentence>." On success "<name> installed." **Remove** (`P
languages/<code>/remove`, code) answers "<name> removed." and the pack can be installed again. An update of the Hub
fetches the matching pack of each installed language; until it has it, the old pack is used and the new texts are in
English.

| State | Text |
|---|---|
| Loading | Three skeleton rows |
| Nothing to get | "This release has no other languages." |
| The list could not be fetched (`problem`) | "Could not read the list of languages. <the Hub's text>" with **Try again** |
| In the demo | "Not in the demo." (3.9) |

### 10.4 Storage locations

Description: "Where spools are put away, and in which order the places fill up."

**What a location is.** Storage is one list of locations. The order of the list is the order in which the places
fill: the first place with room takes the next spool.

- A location has a **name** (one line, 1 to 100 characters, not the same as another location's name, capitals
  ignored) and a **type**. "Bulk storage" is a shelf, rack or drawer that holds many spools under one name; it may
  have a spool limit (1 to 9999) or none. "Individual containers" are boxes or bags that hold one spool each; one
  location stands for the whole numbered set (1 to 999 containers). A container is named with the set's prefix, the
  text before the number, and its number with at least two digits: "Storage box 01" to "Storage box 12", then
  "Storage box 100". The prefix of a location added here is its name plus one space, and a rename sets it to the new
  name plus one space (the spools in its containers are renamed with it). A set carried over from the old settings
  keeps the old box prefix as it was, also when it is empty or only spaces. The Hub gives the number: a spool gets
  the lowest free one. A container is taken while a spool's location is exactly its name.
- **A location's name may not be a container's name.** The name of a container is the set's prefix followed only by
  digits ("Rack 01" beside a set with the prefix "Rack "). A new or changed name that is a container's name of any
  Individual containers location is refused: "<name> is the name of a container in <set>. Choose another name." The
  check also runs the other way: a set that is added, renamed or enlarged, or whose prefix changes, may not get a
  container named like an existing location (the same sentence, with that location's name). Only a clash that is new
  is refused. A clash that already exists, for example one carried over from the old settings, may stay: either
  location can be edited in its other fields, and removing or renaming one of the two ends it. While it exists the
  text is one place: a spool stored under that text counts in the bulk location's "how full" and also makes that
  container taken, so the set skips it, and a request that names the text means the bulk location (the literal
  text is stored). A client that matches a spool's location text takes a location's name before a container's name.
- **Filled automatically with** says what the place takes when nobody chooses: "Nothing, only when you choose it",
  "Any material", or "These materials" with a list of material names. A material name also takes its variants: the
  spool's material, capitals ignored, starts with the name ("PLA" takes PLA+ and PLA-CF). When names of different
  length match a spool, only the locations with the longest matching name count. An overflow location takes "Nothing"
  (overflow only) or "These materials" (it is then also an own place for those materials); "Any material" is not
  allowed on it.
- **Overflow** places take spools when their own places are full, and then they take every material, whatever
  "Filled automatically with" says. Exactly one overflow location is the default overflow; there is always one, so
  the last overflow location cannot be removed or switched off. The default overflow is Bulk storage and may have a
  spool limit like any Bulk storage location. It fills first, up to its limit; then the other overflow locations fill
  in list order; only when all of them are full does the default overflow take more, over its limit.
- Exactly one location is where **sealed spools** go. It is Bulk storage and its limit is not applied to them.
- "How full" is the number of spools in Spoolman whose location is the location's name (bulk) or one of its
  containers' names.
- Changing a setting here moves no spool. A location over its limit (the limit was lowered, or spools were put there
  by hand) shows "22 of 20" and takes no more automatically.

**The placement rule.** When a spool is added or opened with no location given, the Hub chooses in this order:

1. A location the person gave is kept, whatever limits or materials say.
2. A sealed spool goes to the sealed-spools location.
3. Own places: the locations that take the spool's material by name (the longest matching name), overflow
   locations included. If there are any, only these are tried, in list order; the first one under its limit (or with
   a free container) takes the spool. A location with no limit always has room.
4. If no location names the material: the non-overflow "Any material" locations, in list order, the first with room.
5. If 3 or 4 found no room, or there was no candidate: the overflow locations, the default overflow first, then the
   others in list order; the first one under its limit (or with a free container) takes the spool. When every
   overflow location is at its limit, the default overflow takes the spool over its limit.
6. Several spools added together are placed one by one; a count may be split over locations, and the result lists
   each part.

Nobody is asked: the rule always answers, and the answer says why. Unloading a spool from a printer is unchanged
(its previous place, otherwise the sealed-spools location).

**The screen.** A collection "Locations", one row per location in fill order:

| Part | Content |
|---|---|
| Position | The number in the list |
| Name and type | "Rack 1", "Bulk storage" or "Individual containers" |
| How full | "18 of 20 spools", "7 spools" (no limit), "9 of 12 containers used" |
| Takes | "PLA", "Any material", "Only when chosen" |
| Badges | "Overflow", "Default overflow", "Sealed spools" |
| Row actions | **Edit** (default button); icon buttons "Move <name> up" and "Move <name> down" (keyboard and touch; no dragging needed); the overflow menu: "Make default overflow" (overflow rows), "Sealed spools go here" (Bulk storage rows), "Remove" |

- Header action: **Add a location** (primary). The list is never empty: the default overflow and the
  sealed-spools location always exist, and they may be one location. The group's title row also has the overflow menu
  "More actions for Storage locations" with **Download as CSV** (`locations.csv`) and **Import from CSV** (2.10).
- Add and Edit open the theme's detail region (as a printer does, 5.6). Cancel (default) closes it; with typed
  values it asks "Leave without saving?" (section 2.6).
- **Notice under the list** (warn): shown whenever two or more locations are overflow and the default overflow has no
  limit: "The default overflow has no limit, so the other overflow places are never used. Give it a spool limit to let
  them fill."
- **Warn line on a row.** A Bulk storage row whose name is also the name of a container in a set shows the line "Same
  name as a container in <set>." under its name.

| Field | Type | Key / endpoint | Notes |
|---|---|---|---|
| Name | Text | `name` of the row → `P settings/storage` (code) | Required: "Enter a name for the location." Refusal: "There is already a location called <name>." A name that is a container's name is refused with "<name> is the name of a container in <set>. Choose another name."; adding, renaming or enlarging a set so that a container would be named like an existing location is refused at its Name or Number of containers field with the same sentence and that location's name. An existing clash is not refused (see "A location's name may not be a container's name" above) |
| Type | Segmented choice "Bulk storage" / "Individual containers"; hints "A shelf, rack or drawer that holds many spools." and "Boxes or bags that hold one spool each. Spoolwarden numbers them." | `type` | Fixed while spools are in the location: "Move the spools out to change the type." |
| Spool limit | Number, `--mono`; Bulk storage only; hint "Leave empty for no limit." | `limit` | Whole number 1 to 9999. Field error "Enter a whole number, 1 or more." |
| Number of containers | Number, `--mono`; Individual containers only | `count` | Whole number 1 to 999; same field error. Fewer than the highest number in use is refused at the field: "Storage box 11 and Storage box 12 hold spools. Move them first, or keep at least 12." |
| Filled automatically with | Three radios: "Nothing, only when you choose it", "Any material", "These materials" | `fill` | "Any material" is disabled while "Use as overflow" is ticked, with the hint "An overflow place already takes any material when the other places are full." Ticking "Use as overflow" while "Any material" is chosen sets this to "Nothing, only when you choose it" and shows the hint; unticking does not change it back |
| Materials | Text; shown for "These materials"; hint "Separate them with commas, e.g. PLA, PETG. A material also takes its variants: PLA takes PLA+ and PLA-CF." | `materials` (a list) | Field error "Enter at least one material, e.g. PLA." |
| Use as overflow | Checkbox; hint "Takes spools when their own places are full." | `overflow` | The last overflow location cannot be switched off. While ticked, the "Any material" radio above is disabled; if it was chosen, it becomes "Nothing, only when you choose it" |

Buttons of the detail region: **Add location** (a new row) or **Save location** (an edited row), and Cancel. They
change the unsaved list only.

- **Where a new spool goes.** Under the list, a read-only panel: one line per material named in the list, then
  "Everything else", each as "PLA: Rack 1, then Rack 2, then Overflow" (the places joined by ", then "). It is built
  from the unsaved list, so the effect shows before saving.
- **Save.** One Save for the group, **Save storage locations**, with the dirty mark as in every group. Order
  changes, additions, edits and removals are all part of the unsaved state. The Save sends the whole list in one
  request, `P settings/storage` (code) `{locations: [...]}`, with the ids kept for existing rows and none for new
  ones; the Hub answers the saved list, or errors per row and field.
- **Rename.** On Save the Hub also changes the location of the spools stored there: a job with steps when more
  than 20 spools are affected; the result reads "Renamed Rack 1 to PLA rack 1. 18 spools updated."
- **Remove.** The row's "Remove" opens the dialog of section 10.11. It is refused for the default overflow ("Make
  another location the default overflow first.") and for the sealed-spools location ("Choose another location for
  sealed spools first.").

- **When the list could not be saved or read.** The list is stored in `storage.xml` in the Hub's state folder. A Save
  that cannot write answers a refusal at the group, "Storage locations were not saved: <reason>.", and nothing is half
  written. The Hub always starts: if the list cannot be written at start, or `storage.xml` exists but cannot be read,
  the Hub keeps the list it has in memory (the list migrated from the old settings) and places spools with it exactly
  as the file would. The Checks on Overview then show one row in group Hub, Needs a look: "Storage locations could not
  be saved (<reason>)." or "Storage locations could not be read (<reason>)." with the Fix the Hub can name. An
  unreadable file is not overwritten: a Save writes the new file and keeps the old one as `storage.xml.unreadable`.
  The Hub tries the write again at the next change and at the next start.

The group's one-line state in the Settings list is "<n> locations".

### 10.5 Label Reader

Description: "Reads a spool's label from a photo." Title-row badges: one per engine that is on, each after the
engine's name: "Cloud key" with "Set" / "Not set"; "On this Hub" with "OK", or "Needs a look" followed by the
sentence "The reader does not answer." When neither engine is on, the group
shows the off state: "The Label Reader is switched off. Spools are then added by hand." with **Go to Features**, and
only Records kept stays editable.

```
+-- Label Reader ------------------------------------------------ Cloud key [(*) Set]  On this Hub [(*) OK] -+
| Engine order   [Automatic: On this Hub first, Cloud when it is unsure  v]                                    |
| CLOUD (CLAUDE)                                                                                              |
| Anthropic API key   (*) Set  sk-ant-...****            [Check] [Replace] [Remove]                            |
| Claude model        [                    ]  Leave empty for the default model.                               |
| Reads per day       [ 40 ] reads                                                                            |
| ON THIS HUB                                                                                                 |
| Address             [http://127.0.0.1:7915      ]  [Test]                                                   |
|                     (*) Answers: version 1.2.0, API 1, tiers CPU and GPU, corrections supported              |
| Tier                [Automatic | Processor (CPU) | Graphics card (GPU)]                                     |
| Installed on this machine: version 1.2.0, CPU tier.      [Check for an upgrade]  [Remove the reader]        |
| Reader token  (*) Not set    [                    ] [Set a token]                                           |
| RECENTLY ADDED                                                                                              |
| Records kept        [ 20 ]  Now 20 records, 14.2 MB of photos. Each record with photos takes 0.5 to 2 MB.   |
| /!\ Saving a new model or reads per day restarts the Hub. This page comes back by itself.                  |
|                                                         /!\ Unsaved changes     [Save Label Reader]      |
+------------------------------------------------------------------------------------------------------------+
```

| Field | Type | Key / endpoint | Shown | Notes |
|---|---|---|---|---|
| Engine order | Select: "Automatic: On this Hub first, Cloud when it is unsure or fails" (`auto`), "On this Hub, then Cloud" (`local-then-cloud`), "Cloud, then On this Hub" (`cloud-then-local`), "Cloud only" (`cloud`), "On this Hub only" (`local`) | `intake.reader` (unreleased) → `P settings/general` (code) | Both engines on | Hint "An engine that is switched off in Features is skipped." With one engine on, the row reads "Engine: <Cloud / On this Hub>. Switch on the other one in Features to use both." |
| Anthropic API key | Key row: status badge "Set" / "Not set", masked value, default **Check**, default **Replace** (or **Set a key**), danger **Remove** (only when set). Replace reveals a secret field "New Anthropic API key", placeholder `sk-ant-…`, and a ghost **Cancel** | New key: `P key` (code) `{key}`, sent by the group's Save. Check: `P key/check` (view). Remove: confirm, `P key/remove` (code) | Cloud on (otherwise one line: "Only used by Label Reader: Cloud (Claude), which is switched off.") | Check: inline spinner "Checking the key…", then the Hub's text as OK or error; "Wait 3 seconds between checks." when too soon. After a new key is saved: "Key saved. Check it to be sure it works." |
| Claude model | Text, `--mono`, placeholder "Default model" | `model` | Cloud on | Hint "Leave empty for the default model." Restarts the Hub. |
| Reads per day | Number with unit "reads" | `reads_per_day` | Cloud on | Hint "Cloud reads allowed per day; reads On this Hub do not count." Restarts the Hub. Field error "Enter a whole number from 1." |
| Address | Text, `--mono`, default `http://127.0.0.1:7915` | `local_intake.url` (unreleased) | On this Hub on | Hint "Where the reader answers: this Hub, or another computer at home." A reader on this machine (`127.0.0.1`) stays on plain `http://`, as it never leaves the machine. Until the reader's own software can serve HTTPS, an `http://` address of a reader on another machine is accepted and used as today, and an `https://` address is pinned at **Test**; the Checks show a Note for the `http://` one (4.2). From the release that turns the rule on (only together with a reader version that serves HTTPS; it is not a setting), saving an `http://` address that is not `127.0.0.1` is refused at the field with "A Label Reader on another machine needs an https address."; a stored one keeps working and its Checks row becomes Needs a look (4.2). |
| **Test** | Default button beside Address | The saved address: `G settings/local-intake` (view, unreleased). An address that is typed but not saved: the Hub's test of a given address, a change-like request that passes the lock (the Hub contacts a host the person typed, so it asks for the setup code like any change; it sends no token there and follows no redirect) | On this Hub on | Inline spinner "Asking the reader…"; OK "Answers: version <v>, API <n>, tiers <list>, corrections <supported / not supported>."; warn "Answers, but degraded: <reason>."; error "No answer at <address>. Check that the reader is running and the address." Test works on what the field shows: the saved address without the lock, a changed address after unlocking in place, without saving it. Until the Hub offers the test of a given address, Test is disabled while the field holds an unsaved change, with the reason "Save the address first, then test it." A 409 (On this Hub switched off) shows "Label Reader: On this Hub is switched off. Switch it on in Features." For a reader at an `https://` address on another machine, Test also pins its certificate the first time (trust on first use) and shows the fingerprint, in groups of four in `--mono`, beside the result; from then on the Hub accepts no other certificate from that address. |
| Tier | Segmented choice "Automatic" / "Processor (CPU)" / "Graphics card (GPU)" | `local_intake.tier` (unreleased; `auto` / `cpu` / `gpu`) | On this Hub on | Hint "Automatic uses the graphics card when the reader has one." |
| Records kept | Number | `intake.history_keep` | Always | Hint "How many of the newest additions Recently added keeps with their photos (0 keeps none). Now <count> records, <size> of photos; a record with photos takes about 0.5 to 2 MB." Field error "Enter a whole number from 0 to 500." |

**Install block.** Under Tier, with On this Hub on: the reader that runs on this machine, its install plan and its
token. None of it is part of Save Label Reader: install and removal run as jobs, and the token is set by its own
buttons.

| Element | Text / behaviour |
|---|---|
| State line | Installed: "Installed on this machine: version <version>, <tier> tier." Not installed: "Not installed on this machine. A reader on another computer at home (one with a graphics card) works too: switch it on in Features and give its address above." |
| **Check what an install needs** (default; **Check for an upgrade** when installed) | Runs the job `local_intake_plan` (`P job` (code) `{name}`; the Hub's own process cannot reach the release, so a helper job does); the job strip follows it (3.5). |
| Install plan | After the check, under the buttons: "Checked <date and time>:", then the lines of the plan, one per line. Required download: "Download now: <n> MB (required)." Optional download of the tier: "Also downloaded for the <tier> tier (optional): <what>. The release gives no size in MB for it, so it is not added to the figures here." or "… (optional): nothing." Total disk space: "Disk used in total: <n> MB." Before them the line "Install the local label reader <version>, <tier> tier, about <n> min." (or "Upgrade to", "Reinstall", "Go back (downgrade) to"), "Installed: version <version> (<tier> tier)." when one is installed, and, right after that line, "This release has no <tier> tier: its <tier> tier is used." when the tier asked for is not the one the plan uses (the first <tier> is the one asked for, the second the one used), and "Other tiers: <tier>: <n> MB download, <n> MB disk." when the release has more. A figure the release does not state reads "not stated by this release (missing: <field>)", never a guess. When the plan is over an hour old: "That check is over an hour old: check again to install." The plan always ends with "The tier is the one under Tier above: change it there and save, then check again." |
| **Install** (primary; its name is "<label> <version> (<tier> tier)", where <label> is Install, Upgrade or Reinstall by the plan) | Shown when the plan is fresh, the release has the tier and the install is not a downgrade. Opens the confirm "Install the local label reader <version>?" with the plan lines (without "Installed" and "Other tiers") as its text and the button's name as its confirm; runs the job `local_intake_install`; the job strip follows it. |
| **Remove the reader** (ghost, danger; only when installed) | Confirm "Remove the local label reader?" "It leaves this machine, and Label Reader: On this Hub is switched off. Its settings are kept." with **Remove** (danger); runs the job `local_intake_remove`; the job strip follows it. |
| Reader token | Label "Reader token" with the status "Set" / "Not set"; hint "Only for a reader installed with a token, usually one on another computer. It is sent with each read and never shown again."; secret field; default **Set a token** (**Replace** when set) → `P local_intake_token` (code) `{token}`, result "Saved."; ghost danger **Remove** (only when set) → `P local_intake_token/remove` (code). The group is read again afterwards. |
| States | Loading the plan fails: the Hub's text as an error line under the buttons. A job in progress or one that ends: the job strip (3.5); the group is read again when it ends. A button that needs the setup code asks for it in place (3.2). |

**Arriving from Features.** When Label Reader: On this Hub has just been switched on and the reader is not installed, the
page opens this group by itself with the install plan of the reader in view, and the toast "Label Reader switched on.
Install it here to finish." (9.4).

Fields are sent in this order: Engine order, Address, Tier, Records kept, Share corrections (10.5.1), Anthropic API
key, Claude model, Reads per day, so the two that restart the Hub go last. When either of the last two is among the changes, Save opens a
confirm first (10.11). Save: **Save Label Reader**.

#### 10.5.1 Share corrections

The last block of the Label Reader group, under the sub-heading "SHARE CORRECTIONS". Off by default. It is the
only control of the feature: there is no address to see or set anywhere (the reader knows where its maintainer
collects corrections; the Hub never tells it).

```
| SHARE CORRECTIONS                                                                                          |
| Share corrections to improve the Label Reader                                                     [ off ] |
| When this is on, each correction you make to a reading waits on this Hub to be shared: the label photos   |
| (made smaller, with location and camera data removed), what the Label Reader read, what you changed it    |
| to, and your note if you wrote one. Readings by On this Hub and by Cloud (Claude) both count. Nothing is  |
| sent until you press Send now; then the corrections waiting go to the project maintainer for review, to   |
| improve the Label Reader.                                                                                 |
```

| Field | Type | Key / endpoint | Shown | Notes |
|---|---|---|---|---|
| Share corrections to improve the Label Reader | Switch, off by default; the paragraph above is its description (`aria-describedby`) and is always shown, on or off | `label_reader.share_corrections` → `P settings/general` (code), saved by **Save Label Reader**; the Hub then sets the reader the same way in a short job (the job strip follows it) | Always, in the group | Result after the job: "Saved: Share corrections. The reader restarted." A correction is a change saved in Recently added (Save changes, or Accept of a suggestion) or a read field changed on the Check step while adding spools; from then on each one waits in 10.5.2, with no question per spool. |

| Condition | The switch | Line under it |
|---|---|---|
| Label Reader: On this Hub is off or not installed | Disabled, off | Info: "Needs Label Reader: On this Hub, which keeps the corrections until they are sent. Switch it on in Features." with the link **Features**. Cloud (Claude) readings are shared too once it is on. |
| The reader does not offer it (an older reader) | Disabled, off | Info: "The reader on this Hub is too old to share corrections. Update it in Updates." with the link **Updates** |
| The reader does not answer | Disabled, showing the saved value | warn: "The reader does not answer, so this cannot be changed now." |
| The reader's own state differs from the saved setting | Enabled, showing the saved value | warn: "The reader is set differently from this Hub. Save Label Reader to set it again." (Save is then enabled without another change) |

Switching it off stops new corrections from being added. When corrections are still waiting, Save first asks what
to do with them (10.11, "Stop sharing corrections?").

#### 10.5.2 Corrections waiting

A card of its own directly under the Label Reader group, outside the group's Save: everything in it applies at
once. Shown while Share corrections is on (as saved), and for as long as anything is still waiting after it was
switched off. It has no address of its own; links to it go to `#settings/label-reader` and scroll to the card.

**Data** (thin pass-through to the reader; the names are the server builder's, Stage V1.4):
`G label-reader/corrections` (view) → `{sharing, count, bytes, entries}`, each entry `{id, record, item, at,
engine, changes: [{field, read, now}], note, photos, queued, reason}`; thumbnails
`G label-reader/corrections/<id>/photos/<n>` (view); `P label-reader/corrections/<id>/remove` (code);
`P label-reader/corrections/remove-all` (code); `P label-reader/corrections/<id>/retry` (code);
`G label-reader/corrections/package` (view); `P label-reader/corrections/send` (code).

```
Desktop
+-- Corrections waiting -------------------------------------------------- 12 waiting · 3.4 MB --+
| Nothing is sent until you press Send now. Remove any you do not want to share.                  |
|  PHOTO   RECORD                               READ BY       CHANGES                              |
|  [img2]  Polymaker PolyTerra PLA Charcoal..   On this Hub   Brand: Polymakr -> Polymaker [Remove]|
|          2026-11-12 14:09                                   Colour: #2B2B2E -> #1F1F22           |
|                                                             Note: brand is Polymaker             |
|  [img1]  Bambu Lab PETG HF Orange             Cloud         Net weight: 1000 g -> 750 g  [Remove]|
|          2026-11-12 09:50                     (Claude)                                           |
| [Remove all]                                          [Download the package]   [Send now]        |
+--------------------------------------------------------------------------------------------------+
Tablet: Read by moves under the record's name.
Phone:  rows become cards (photo left; name, time and Read by; the changes; Remove at the foot of the card);
        the three buttons stack full width, Send now first.
```

| Column | Content | Priority |
|---|---|---|
| Photo | Photo thumbnail of the first photo (48 px square, rounded `--r-s`) with the photo count; pressing it opens the photo viewer of 6.3 on the photos that would be sent | P1 |
| Record | Link "<vendor> <name>" to `#recent/<id>`, and under it the time of the correction as `YYYY-MM-DD HH:MM`, `--mono`. A record that Recently added no longer keeps: the name as text and "This record is no longer kept." in `--muted`; the correction still waits, with its photos | P1 |
| Read by | "On this Hub" or "Cloud (Claude)": the engine whose reading was corrected | P2 |
| Changes | Change list, one line per field: "<Field>: <what was read> → <what it is now>", values in `--mono`; then "Note: <note>" when there is one | P1 |
| Remove | Default button **Remove** (accessible name "Remove the correction for <vendor> <name>") | P1 |

| Control | Type | Endpoint | Notes |
|---|---|---|---|
| Title-row count | Text | from `count`, `bytes` | "<n> waiting · <size>" ("1 waiting"); absent when nothing waits |
| Intro | Text | | "Nothing is sent until you press Send now. Remove any you do not want to share." With Share corrections off and corrections left: "Share corrections is off, so no new corrections are added. These are still waiting." |
| **Remove** | Default button per row | `P label-reader/corrections/<id>/remove` (code) | No confirmation: it only takes the correction out of this list. Result (note): "Removed. The record in Recently added is unchanged." |
| **Remove all** | Danger button, at the left of the foot; absent when nothing waits | `P label-reader/corrections/remove-all` (code) | Asks first (10.11). Result: "Removed <n> corrections. Nothing was sent." |
| **Download the package** | Default button; disabled when nothing waits ("Nothing is waiting.") | `G label-reader/corrections/package` (view) | Saves `spoolwarden-corrections-<YYYY-MM-DD>.zip`. Hint under the buttons: "The package is the exact file that Send now sends, so you can look at it first." Failure: "Could not make the package. <Hub's text>" |
| **Send now** | Primary button; disabled when nothing waits ("Nothing is waiting.") | `P label-reader/corrections/send` (code) | Asks first (10.11). Sending: inline spinner "Sending <n> corrections…"; the list is not editable meanwhile |

| Event or state | Shape | Text |
|---|---|---|
| Sent | OK | "Sent <n> corrections. Thank you." The list empties. |
| Not sent | error | "Could not send. <the Hub's or the reader's reason> The corrections are still waiting." |
| A correction the reader did not take | warn line in its row, in place of the changes' note | "Not waiting: the reader did not take this correction. <reason>" with default **Try again**; such a row is never part of the package or of Send now, and is not counted |
| Empty, Share corrections on | Empty state with the Label Reader icon | "No corrections waiting" / "Corrections you make in Recently added, or while adding spools, appear here." |
| Loading | | Three skeleton rows |
| The reader does not answer | Error state | "The reader does not answer, so the corrections waiting cannot be shown. They are kept." + **Try again** |
| Error | Error state | "Could not read the corrections waiting. <Hub's text>" + **Try again** |
| Locked | | The list and Download the package work; Remove, Remove all, Try again and Send now ask for the code in place |

**Main action:** **Send now**, the card's one primary button.

### 10.6 Backups and restore

Description: "One zip with everything Spoolwarden keeps." Title row: "Nightly backup" followed by the status badge "On" /
"Off" (the Nightly backup feature).

| Part | Content |
|---|---|
| Warning (banner, warn) | While no backup password is set: "The zip is not encrypted and holds the setup secrets (the keys, Access Codes and certificate). Store it somewhere safe." and the link **Set a backup password** (below). With a password set the banner is a Note: "Every backup is encrypted with the backup password." |
| Backup password | Title "Backup password" with the status badge "Set" or "Not set". **Set a backup password** (default button; **Change password** and ghost **Remove password** once it is set) opens the dialog of 10.11 (two fields, at least 10 characters) with the sentence "Write this password down. Without it these backups cannot be restored, and Spoolwarden cannot recover it." From then on every backup is encrypted: the nightly one, **Back up now**, and the copy made before a restore. Changing it makes new backups use the new password; older files keep the one they were made with. Removing it makes new backups plain again; encrypted files stay as they are. The page never shows the password again: the hint reads "To read it again, run this on the Hub:" with the code block `sudo spoolwarden backup password --show`. → `P backups/password` (code) `{password}`, `P backups/password/remove` (code) |
| **Back up now** | Primary → job `backup` (code); inline result "Backing up… follow it in the job panel." then "Backup: done. It is at the top of the list." |
| Backups on the Hub | Collection, loaded by itself when Unlocked or Trusted (`P backups/list` (code)). Columns Made (`at`, `--mono`) P1; Kind ("Nightly", "Before a restore", "Made here"; an encrypted file also shows the tag "Encrypted" with the lock icon, from `encrypted`) P2; Size ("<n> KiB") P2; ghost **Download** P1 → `P backups/download` (code), inline spinner "Preparing the zip…", then the browser saves the file (an encrypted backup is saved as it is, its name ending `.enc`). Empty: "No backups in <folder> yet." Locked: "The list is shown once the page is unlocked." and **Unlock to show** |
| Keep nightly backups for | Number with unit "days" (1 to 365), hint "Backups made here are kept until you delete them." → `P backups/keep` (code) `{days}`, by the group's Save; result "Nightly backups are kept for <n> days." |
| Restore (step progress, three steps) | 1 "Choose a backup zip": file field (accept `.zip` and `.enc`), label "Backup zip". 2 "Upload and check": default **Upload and check** (enabled once a file is chosen) → raw `P restore/upload` with the code in the `X-Setup-Code` header; inline spinner "Uploading and checking…" with a determinate bar of the upload. For an encrypted file the Hub tries its stored backup password first; when that does not open the file, this step shows the field "Password of this backup" (a secret field) with default **Open the backup** → `P restore/password` (code) `{password}`, and a wrong password says "Wrong password, or the file is damaged. Nothing was changed." at the field. The checks that follow (the manifest, every file's hash) run on the opened content as for a zip. 3 "Restore": the check summary and danger **Restore…** (opens the typed-word confirm), ghost **Discard the upload** → `P restore/forget` (code) |
| Check summary (key-value list) | "Backup of <host or "another Hub"> made <created> by Spoolwarden <version>"; "Contains <n> files<, and the Spoolman database>"; "Features: <list or "none">"; when `replaces_data`, a warn line "This replaces the spools, settings, printers and pairings on this Hub. What is here now is saved as a backup first."; the other-host note as Note; "Afterwards the setup code is the one from the backup."; "Checked copy: SHA-256 <hash>. Only this copy is restored." (`--mono`); for an encrypted file the line "Encrypted: the password that opened it becomes this Hub's backup password if none is set." |
| Upload errors | No file: at the field "Choose the backup zip first." Too large: "The backup is larger than this page can take. Copy it to the Hub and run `sudo spoolwarden restore <file>` there." (code block with Copy). Other: the Hub's text. |

Save: **Save backup settings** (only Keep nightly backups for). Back up now, the backup password and Restore are actions, not saves.

### 10.7 Network and addresses

Description: "How the Hub is reached from the web, by the Weigh Station, and by name."

| Field | Type | Key / endpoint | Shown | Notes |
|---|---|---|---|---|
| Hub port | Read-only value in `--mono` ("443", or the port in use) with the default button **Change port** | `port` in the group's answer (`G settings/general`); **Change port** opens the dialog of 10.11 and then runs as a job | Always | With port 443 every address of this Hub is shown without a port; with another port it is shown as `https://192.0.2.10:8710/setup`. |
| Public address | Text, `--mono`, placeholder `https://hub.example/filament` | `web.public_url` → `P settings` (code) `{key, value}` | Always; hint differs when Web access is off | Hint "The https address of the web app and Claude's connector." Off: "Used when Web access is on." Applies in the background (job `apply`). |
| Weigh Station address | Text, `--mono`, placeholder `https://station.local` | `station.url` → `P settings` (code) | Always | Hint "Where this Hub reads a Weigh Station on another computer. Leave empty for none." Applies in the background. A Weigh Station is called over HTTPS at the port and certificate it told the Hub when it paired (7.3); an address with no port means port 443. |
| Names for this page | Text, `--mono`, placeholder `hub.example` | `setup.hosts` (list) → `P settings/general` (code) | Always | Hint "Separate them with spaces. The Hub's own names and addresses always work, and so does a local name from your network (one word, .local, .lan, .home.arpa or your network's own domain) that points at this Hub. Add any other name here." |
| Allow printer changes from the public address | Toggle | `web.printer_changes` → `P settings/general` (code) | Web access on | Hint "Off: the web app at the public address shows printers but cannot add, change or forget them. At home it always can." Saved with the group's Save (no longer on change). |
| Remote access | Sub-group, Remote access on | | | Text "Spoolwarden never changes your firewall or router. Getting the certificate needs port 80 on your router to reach this Hub while it runs." Default **Show the firewall rules** → `P remote/firewall` (code), result shown in a code block with Copy under the button. Default **Get the certificate** → confirm, job `remote_issue` (code). Remote access off: "Turn on Remote access in Features to get a certificate for the public address." (link) |

Save: **Save network settings**. A result that applies in the background: "Saved; applying… Follow it in the job
panel."

### 10.8 Web passphrase

Description: "Approves Claude's connector on the web access sign-in page." Title-row badge "Set" / "Not set". When
Web access is off, a Note line "Web access is switched off; the passphrase is used once it is on."

| Field | Type | Notes |
|---|---|---|
| New passphrase | Secret field with show/hide, `autocomplete="new-password"` | Hint "At least 12 characters." Error "Use at least 12 characters. This one has <n>." |
| New passphrase again | Secret field | Error "The two passphrases do not match." (checked in the page before sending) |

Save: **Set passphrase** (or **Replace passphrase** when set) → `P passphrase` (code); result "Passphrase set." Both
fields clear after saving.

### 10.9 Filament Catalog

Description: "The catalog of known filaments and their settings." Title row from `G library`: status badge "OK"
when up to date; "Needs a look" (triangle) followed by the sentence "The last check failed." when it failed; when
the catalog is not downloaded yet, no badge but the sentence "The catalog is not downloaded yet." When the Filament Catalog feature is off: the off state "The Filament
Catalog is switched off." with **Go to Features**.

| Part | Content |
|---|---|
| State | "Version <v> (<source>), <n> entries of your own." or "The catalog is not downloaded yet."; "Last check <at>: OK." / "Last check <at>: <error>" (warn) / "Last check: never."; `skipped` as a Note line |
| **Update now** | Default → job `library_update` (code) |
| **Go back to the version before** | Ghost → confirm, job `library_rollback` (code) |
| Add your own entry | A form of three fields and a button: **Brand**, **Name** and **Material** (all required; Material is a choice from the materials the catalog knows, with "Other" and a text field), and the primary **Add**. Under a closed disclosure "More (optional)": Nozzle temperature from and to (°C), Bed temperature from and to (°C), Density (g/cm³), Maximum volumetric speed (mm³/s), Bambu Studio parent, Notes. The page sends the form's values and never an entry's text: the Hub builds the entry with one function, so every interface gives the same entry, and there is no box to paste an entry into. Result "Added. Slicer presets are rebuilt in a minute." Empty required fields are refused at the field: "Enter the brand.", "Enter the name.", "Choose the material." (for "Other": "Type the material."). The Hub's own refusals (`problems`) show at the field they name, or above the button. → `P library/local` (code) `{brand, name, material, nozzle_min, nozzle_max, bed_min, bed_max, density, max_volumetric_speed, bambu_parent, notes}` |
| See custom entries | Default button. Opens a list of the owner's own entries in a dialog (a bottom sheet on a phone): a collection of Brand, Name, Material and Added (`YYYY-MM-DD`) with a ghost **Remove** per entry, which asks first (10.11). Empty: "You have no entries of your own yet." → `G library/local` (view); `P library/local/<id>/remove` (code) |

No Save button: Update now, Go back, Add and Remove are actions. The Hub page has no field for the catalog token: a
token that is stored keeps working, and `spoolwarden catalog token` (`06-command-line.md` 9.11) is the one place to
set or remove it.

### 10.10 Weigh Station voice

Description: "The voice the Weigh Station speaks with." Shown when the Weigh Station feature is on; otherwise the off
state "The Weigh Station is switched off on this machine." with **Go to Features**.

| Field | Type | Key | Notes |
|---|---|---|---|
| Voice | Two choice cards: "Piper" with "Natural. A 60 to 80 MB download." (`auto`) and "espeak-ng" with "Robotic. No download." (`espeak`) | `station.tts` → `P settings/general` (code) | Applies on choosing (job `apply`); result "Saved: Piper. The Weigh Station downloads it next time it is idle." or "Saved: espeak-ng." A cancelled unlock puts the choice back. |

No Save button.

When the Weigh Station is paired, the group ends with the ghost link **Open the Weigh Station's detail** (7.10), where
the station's sounds and lamps are set too. The voice is one value: the station's own file wins, and this group reads it
through `G device/<id>` when the station answers.

### 10.11 Dialogs

| Dialog | Title | Body | Buttons |
|---|---|---|---|
| Save restarts the Hub | "Restart the Hub to save?" | "A new Claude model or number of reads per day takes effect after a restart. The Hub restarts now and this page comes back by itself." | Cancel · **Save and restart** (primary) |
| Remove Anthropic API key | "Remove the Anthropic API key?" | "Label Reader: Cloud (Claude) stops reading labels until a new key is set." | Cancel · **Remove key** (danger) |
| Send the corrections waiting | "Send <n> corrections?" ("Send 1 correction?") | "The photos and values in this list go to the project maintainer for review, to improve the Label Reader. This cannot be taken back." | Cancel · **Send** (primary) |
| Remove all corrections waiting | "Remove all corrections waiting?" | "<n> corrections are taken out of this list and are not sent. The records in Recently added are unchanged." | Cancel · **Remove all** (danger) |
| Share corrections switched off while corrections wait (asked by Save Label Reader) | "Stop sharing corrections?" | "<n> corrections are still waiting. Keep them to send later, or delete them now." | Cancel · **Keep them** (default) · **Delete them** (danger). Cancel saves nothing; the other two save the group. |
| Remove a custom entry | "Remove <brand> <name> from your own entries?" | "Slicer presets are rebuilt." | Cancel · **Remove** (danger) |
| Catalog go back | "Go back to the previous Filament Catalog?" | "The version before the last update comes back. Your own entries are kept." | Cancel · **Go back** (danger) |
| Get the certificate | "Get the certificate now?" | "Port 80 on your router must reach this Hub while it runs. Spoolwarden never changes your firewall or router." | Cancel · **Get the certificate** (primary) |
| Set a backup password | "Set a backup password" ("Change the backup password" when one is set) | Fields "Backup password" and "Backup password again" (secret fields, at least 10 characters; "The two passwords do not match."; too short: "Use at least 10 characters."). "Write this password down. Without it these backups cannot be restored, and Spoolwarden cannot recover it." When one is set: "New backups use the new password. Older backups keep the password they were made with." | Cancel · **Set password** (**Change password**) (primary) |
| Remove the backup password | "Remove the backup password?" | "New backups are plain again. Backups already made stay encrypted and need the password they were made with." | Cancel · **Remove password** (danger) |
| Restore (typed word) | "Restore this backup?" | The check summary in short ("Backup of <host> made <created>"), then "This replaces the spools, settings, printers and pairings on this Hub. What is here now is saved as a backup first. The Hub restarts, and afterwards the setup code is the one from the backup." For a backup that was encrypted: "The password that opened it becomes this Hub's backup password if none is set." Field "Type restore to go on" (`--mono`, placeholder `restore`) | Cancel · **Restore** (danger, enabled only when the field reads `restore`) → `P job` (code) `{name: "restore", confirm: "restore", sha256: <the checked copy's SHA-256>}` |
| Change the Hub's port | "Move the Hub to port <number>?" with a field "Port" (a number, `--mono`) | "Phones and the Slicer Sync PC find the Hub again on your network. A Weigh Station on another machine must be paired again." The Hub restarts, runs the change as a job, and this page then opens at the new address. A port that is taken, or that is not 443 or from 1024 to 65535, is refused at the field with the reason. | Cancel · **Change port** (primary) |
| Remove a storage location | "Remove <name>?" | "<n> spools are recorded there. They keep that location until you move them; it is no longer offered for new spools." ("No spools are recorded there." when n is 0) | Cancel · **Remove** (danger) |
| Unsaved changes | Section 2.6 | | |

The typed word is compared after removing spaces at either end; it must then read `restore` in lower case. The Hub receives it with the restore job and checks it again.

### 10.12 States

| State | Text |
|---|---|
| Loading | Each group shows skeleton rows of its fields; the sub-navigation is usable at once |
| Error reading the settings | Error state in each group that depends on `settings/general`: "Could not read the settings. <Hub's text>" + **Try again** |
| Saving | The group's Save shows an inline spinner and "Saving…"; fields stay editable |
| Saved | Inline result "Saved: <field names>." |
| Nothing changed | The Save button is disabled while nothing differs; pressing Enter in a field then shows "Nothing changed." |
| Refused | The field's error with the Hub's reason; the group's result "<Field> was not saved: see the field." |
| Restart | Section 3.6 |
| Locked | Saving asks for the code in place, then saves |
| Hub port changing | The job strip follows the job; the Hub restarts (section 3.6); when it is back, the page opens at the new address |

**Main action:** each group's Save is that group's one primary button; Back up now is the primary of Backups and
restore, so its Save button is a default button.

### 10.13 Alerts

Position: fourth in the order of 10.1, after Storage locations (`#settings/alerts`). Description: "What Spoolwarden
warns you about, and where." Group summary (title-row badge and the phone list): "<n> of 8 on". What an alert is, the
banners and the Alerts list are in section 2.8 and `02-components.md` sections 8.8 and 8.9.

The first part is Hub-wide and is saved with the group's Save; the part "On this device" is set off under its own small
heading and applies at once.

| Field | Type | Key / endpoint | Notes |
|---|---|---|---|
| Filament ran out | Switch | `types[].key` (`runout`) → `P settings/alerts` (code) | Events `print.runout`. Default on |
| Print paused | Switch | same | `print.paused`. Default on |
| Print failed or stopped | Switch | same | `print.failed`. Default on |
| Printer error | Switch | same | `printer.error`. Default on |
| Print finished | Switch | same | `print.finished`. Default off |
| Storage almost full | Switch | same | `storage.low`. Default on |
| Spool running low | Switch | same | `spool.low`. Default on |
| Device stopped answering | Switch | same | `device.down` and `printer.offline`. Default off. Description "A Weigh Station or a printer stopped answering." |
| Only when it is the last spool of that filament | Switch, beside "Spool running low" | `last_spool_only` | Default off. It limits the alert, not the Running low list of 4.2 |
| Running low under | Number with unit "g" | `running_low_g` | Default 150, 10 to 2000. Hint "Opened spools at or under this are listed as running low." |
| Storage warning at | Number with unit "% used" | `storage_warn_percent` | Default 85. The Hub treats 95 % used (`storage_bad_percent`), and always less than 1 GB free, as bad |

Every event is written whatever the switches say; the switches only decide what is shown and sent as an alert.

| On this device | Type | Does | Endpoint |
|---|---|---|---|
| Notifications in this browser | Switch, off until switched on (the browser then asks for permission); hint "Shown while a Spoolwarden tab is open in this browser. With the tab in the background they can arrive up to a minute late." | Applies at once; needs no setup code; kept in the browser, not on the Hub | none (the browser's `localStorage`) |
| Send a test alert | Default button | One test notification to this browser only | `P alerts/test` with the browser id (`client`); it arrives as `test` in the next `G events` answer |
| Recent alerts | Link | Opens the Alerts list (`02-components.md` 8.9) | `G events` |

- States of the browser switch: "Blocked in this browser's settings" with how to allow it (the browser's own site
  settings), and "This browser cannot show notifications" where the browser refuses (a page on the Hub's own address
  with a certificate the browser does not trust may be refused; the way out is the public address with a real
  certificate, said in that text).
- Save: **Save alerts**. Result "Saved: <field names>."
- Where it is kept: the switches and limits are in `alerts.xml` in the Hub's state folder, written in the Hub process
  by `P settings/alerts` (the command line writes it directly as root); it holds no per-device entries. The phone web
  app's push subscriptions are in `push.xml` in the web unit's own folder, not in the Hub's state folder. The Hub
  always starts: when `alerts.xml` cannot be written, the defaults apply from memory and the Checks on Overview show one row in group Hub, Needs a look: "Alerts settings could not be saved ({reason})."


---

## 11. Flash a device

**Purpose.** Write Spoolwarden's firmware to a Tag Reader or a Weigh Station display over USB, and set a Tag Reader
up, without a toolchain. Address `#flash`; with a device chosen `#flash/tag-reader` or `#flash/display`. Code names:
`Printer Station` (Tag Reader) and `intake panel` (Weigh Station display).

**Data.** All endpoints of this section are unreleased (section 1.1). `G firmware` (view) → the devices this Hub has
firmware for and their versions, the boards plugged into the Hub (port and product), and whether the public address
allows a Tag Reader setup. Firmware images `G firmware/<id>.bin` (view), never from the internet.

### 11.1 Layout

```
Desktop
+--------------------------------------------------------------------------------------------------+
| Flash a device                                                                                    |
| Writes Spoolwarden's firmware over USB. Nothing is downloaded: the firmware comes with the Hub.   |
| 1 DEVICE                                                                                          |
|   (o) Tag Reader                       ( ) Weigh Station display                                  |
|       Firmware <version>                   Firmware 0.5.2                                         |
| 2 PLUGGED INTO                                                                                    |
|   [ This computer | The Hub ]                                                                     |
|   Plug it in with a data cable.                                                                   |
| 3 SETTINGS (Tag Reader)                                                                           |
|   Wi-Fi name          [                ]                                                          |
|   Wi-Fi password      [                ] [show]   2.4 GHz networks only.                          |
|   Password again      [                ]                                                          |
|   Buzzer              (o) High-triggered (the build in the parts list)  ( ) Older 3-pin module     |
|   Name (optional)     [                ]                                                          |
| 4 WRITE                                                                                           |
|   [Connect and write]   then pick the board in the browser's list.                                |
|   ( ) Connecting  ( ) Writing the firmware  ( ) Restarting  ( ) Sending the settings  ( ) Waiting for its report |
+--------------------------------------------------------------------------------------------------+
Tablet: the same, one column, choice cards side by side.
Phone:  steps stacked. A phone browser cannot write to USB: "This computer" is disabled with the line
        "Phones cannot write to USB devices. Plug the board into the Hub and choose The Hub, or open this page
        on a computer." The Hub way works.
```

### 11.2 Controls

| Control | Type | Shown | Does / endpoint |
|---|---|---|---|
| Device | Choice cards "Tag Reader" and "Weigh Station display", each with its firmware version | Only devices `G firmware` lists | Chooses the device |
| Plugged into | Segmented choice "This computer" / "The Hub" | Always | "This computer" needs a browser with Web Serial (Chrome or Edge on a computer, over https) |
| Board | Select of the Hub's boards ("<port> · <product>") | The Hub, Tag Reader, more than one board plugged in | Chooses the port |
| Wi-Fi name | Text | Tag Reader | Required: "Enter the Wi-Fi name." |
| Wi-Fi password | Secret field with show/hide | Tag Reader | Hint "2.4 GHz networks only." |
| Password again | Secret field | Tag Reader | "The two passwords do not match." |
| Buzzer | Radio: "High-triggered (the build in the parts list)" (default), "Older 3-pin module" | Tag Reader | |
| Name (optional) | Text | Tag Reader | The name the Hub gives the reader's token |
| **Connect and write** | Primary | This computer | Asks for the code if Locked, then the browser's port picker (it needs the press's user activation, and no token is made when no board is chosen); then (Tag Reader) `P flash/provision` (code) for a token the page never shows; then writes `G firmware/<id>.bin` at 0x0, restarts the board, finds it again, sends the settings and waits up to 60 s for the reader's own report. Any failure revokes the new token (`P readers/<id>/revoke`). |
| **Write on the Hub** | Primary | The Hub, Tag Reader | `P flash/server` (code) with the answers and the port; the Hub starts job `reader_setup`, which the job strip and the step list follow |
| **Stop** | Default, while writing from this computer | | Stops before the next step; a half-written board is reported as such |

Weigh Station display with "The Hub": no form and no button, only the sentence "Plug the display into the Weigh
Station computer. The Weigh Station writes its own firmware to it by itself."

### 11.3 Progress and results

Step progress with five steps (Tag Reader) or three (display: Connecting, Writing the firmware, Restarting), and a
determinate bar with the percentage during Writing the firmware (this computer). It takes up to about a minute and a
half.

| Outcome | Shape | Text |
|---|---|---|
| Tag Reader done | OK | "Done. The Tag Reader joined '<Wi-Fi name>' and reached the Hub. Unplug it and power it where it lives; it keeps its settings." |
| Display done | OK | "Done. The Weigh Station display firmware <version> is written. Plug it into the Weigh Station computer." |
| No Web Serial | Note, button disabled | "This browser cannot write to USB devices. Use Chrome or Edge on a computer, or plug the board into the Hub and choose The Hub." |
| No board chosen | Note | "No board was chosen. Press Connect and write again and pick the board." |
| No public address | error, before writing | "A Tag Reader needs the Hub's public address. Set it in Settings > Network and addresses." (link) |
| Writing failed | error | "Writing the firmware failed (<reason>). Check the cable is a data cable and try again." |
| Did not come back | error | "The board did not come back on USB after its restart. Unplug it, plug it in again, and run this again." |
| No answer before the settings | error | "The board did not answer before the settings. Run this again." |
| Settings refused | error | "The board refused the settings: <reason>. Run this again." |
| No report | error | "The board did not report back. Run this again." |
| Wi-Fi failed | error | "The Tag Reader could not join '<Wi-Fi name>'. Check the Wi-Fi name and password (2.4 GHz networks only)." |
| Hub refused it | error | "The Tag Reader reached the Hub, but the Hub refused it. Run this again." |
| Hub unreachable | error | "The Tag Reader joined the Wi-Fi but could not reach the Hub at <address>. Check the public address in Settings > Network and addresses." |
| Job failed (The Hub) | error | The job strip's end text; the step list marks the failed step |

| State | Text |
|---|---|
| Loading | Skeleton choice cards |
| No firmware on the Hub | Empty state "No firmware to write" / "This Hub has no device firmware installed. Updating Spoolwarden brings it." |
| No boards on the Hub (The Hub chosen) | Note "No board is plugged into the Hub. Plug it in with a data cable; this list updates by itself." (re-reads `G firmware` every 3 s while shown) |
| Locked | The main button asks for the code first |
| Job running (another job) | Write on the Hub disabled: "Wait for <job title> to finish." |

**Main action:** Connect and write, or Write on the Hub.

---

## 12. Updates

**Purpose.** See the installed version, update, roll back. Address `#updates`.

**Data.** `G updates` (view) → `{installed, latest, newer, checked_at, half_install, installed_text, notes,
going_back, held, failed, previous, module_on, schedule, update_refused, rollback_refused}`.

### 12.1 Layout

```
Desktop
+--------------------------------------------------------------------------------------------------+
| Updates                                                          [Check now] [Update to 0.5.3]    |
| +-- Version -----------------------------------+ +-- What 0.5.3 brings -------------------------+ |
| | Installed       0.5.2                         | | (release notes)                              | |
| | Latest release  0.5.3                         | |                                              | |
| | Last checked    2026-11-12 03:00              | |                                              | |
| | Checked by itself daily (Automatic updates).  | |                                              | |
| +-----------------------------------------------+ +----------------------------------------------+ |
| +-- Roll back ----------------------------------+                                                |
| | Goes back to 0.5.1, the version this one      |                                                |
| | replaced. Settings and data stay.             |                                                |
| | [Roll back to 0.5.1]                          |                                                |
| +-----------------------------------------------+                                                |
|  To remove Spoolwarden: on the Hub, run sudo spoolwarden uninstall.                               |
+--------------------------------------------------------------------------------------------------+
Tablet: two columns become one; Version, release notes, Roll back.
Phone:  one column; the header buttons go full width, Update first.
```

### 12.2 Cards and controls

**Version** (key-value list).

| Row | Content |
|---|---|
| Installed | `installed_text` |
| Latest release | `latest`, with status badge "OK" when it is the installed version, or the sentence "<latest> is available." when it is newer; before any check, the sentence "Not checked yet." |
| Last checked | `checked_at` |
| Held back | When `held` equals `latest`: "<v> was rolled back. Automatic updates skip it; Update here installs it." |
| Failed before | When `failed` equals `latest`: "Installing <v> failed before. Automatic updates wait for a newer release; Update here tries it again." |
| Checking | "Checked by itself <schedule> (Automatic updates)." or "Not checked by itself: Automatic updates are switched off." with link **Features** |
| Refused | `update_refused` as an error line under the buttons |

A Hub that still runs a nightly build shows its version as "<version>-nightly.<date>"; Update then installs the latest signed release over it, even when that release has a lower number, and the confirm dialog says so: "This replaces the nightly build with the signed release <latest>."

| Control | Type | Does | Endpoint |
|---|---|---|---|
| **Check now** | Default (header) | Job | job `check` (code) |
| **Update to <latest>** | Primary (header), only when `newer`; disabled with the refusal as tooltip when `update_refused` | Confirm, then job | job `update` (code) |

**What <latest> brings** (when `newer` and `notes`) or **Release notes of <latest>** (when not newer and `notes`):
the notes as text with line breaks kept, at most 72 characters a line, in a box that scrolls inside past 24rem.

**Roll back.** "Goes back to <previous>, the version this one replaced. Settings and data stay." or "No earlier
version is kept, so there is nothing to roll back to." `going_back` as a Note block. Danger **Roll back to
<previous>**, disabled with the refusal shown as an error line when `rollback_refused` → confirm, job `rollback`
(code).

**Foot:** "To remove Spoolwarden: on the Hub, run" and a code block with Copy, `sudo spoolwarden uninstall`.

### 12.3 Dialogs

| Dialog | Title | Body | Buttons |
|---|---|---|---|
| Update | "Update to <v>?" | "Spoolwarden stops while it installs and starts again by itself. Settings and data stay. The version before is kept, so you can roll back." | Cancel · **Update to <v>** (primary) |
| Roll back | "Roll back to <v>?" | "Spoolwarden stops while it installs and starts again by itself. Settings and data stay." | Cancel · **Roll back** (danger) |

### 12.4 States

| State | Text |
|---|---|
| Loading | Skeleton key-value rows |
| Error | "Could not read the update state. <Hub's text>" + **Try again** |
| Half installed | The banner of section 4.2 also shows here |
| Job running | Both header buttons disabled with "Wait for <job title> to finish."; an update or roll back leads into the restart notice (section 3.6) and the page reloads on the new version |

**Main action:** Update to <latest> when one is available; otherwise Check now is a default button and there is no
primary.

---

## 13. Logs

**Purpose.** Two readings of what the Hub did. **Activity** lists the things that were done: when, by whom, what, and a
link to the thing, with **Undo** where it can still be undone. **Service logs** read the end of a service's log. Logs
hold addresses and serial numbers, so reading a service log needs the setup code; Activity holds no addresses, serials or
secrets and needs nothing. Addresses `#logs` and `#logs/activity` (Activity chosen); `#logs/<service>` shows that service
once Unlocked. A button collects a report for a problem (13.5).

**Data.** `G logs/units` (view) → `{units}`; `P logs` (code) `{unit, lines}` → `{unit, text, truncated}`. Activity:
`G activity` (view) and `P events/<id>/undo` (code), 13.4; the report: `P report` (code) and `P report/download` (code),
13.5.

### 13.1 Layout

```
Desktop (Service logs chosen)
+--------------------------------------------------------------------------------------------------+
| Logs                                                                      [Collect a Hub report] |
| [ Activity | Service logs ]                                                                      |
| Service [spoolwarden.service     v]   Lines [50 | 100 | 200]   [Show]                             |
| +----------------------------------------------------------------------------------- [Copy] ---+ |
| | 2026-11-12 03:00:02  backup   nightly backup started                                         | |
| | 2026-11-12 03:00:09  backup   done · 4,812 KiB                                               | |
| +----------------------------------------------------------------------------------------------+ |
| Only the end is shown: the rest is too long for this page.                                       |
+--------------------------------------------------------------------------------------------------+
Tablet: the same; the controls wrap onto two lines.
Phone:  controls stacked full width. At every width the log's lines wrap inside the code block (components 7.7:
        `white-space: pre-wrap; overflow-wrap: anywhere`); the block never scrolls sideways.
```

### 13.2 Controls

| Control | Type | Does | Endpoint |
|---|---|---|---|
| Show | Segmented choice "Activity" / "Service logs" (`02-components.md` 5.7), label "Show"; Activity is chosen when the section opens | Switches between 13.4 and the controls below; `#logs/activity` or `#logs` | |
| **Collect a Hub report** | Default button (header) | 13.5 | `P report` (code) |
| Service | Select of the unit names (shown as sent, `--mono`) | Chooses the log; when Unlocked, changing it shows the new log at once | |
| Lines | Segmented choice "50" / "100" (default) / "200", label "Lines" | As above | |
| **Show** | Primary | Reads the log; inline spinner "Reading…"; afterwards it reads **Show again** | `P logs` (code) |
| **Copy** | Ghost in the log's code block | Copies the log text | |

The log is a code block (`02-components.md` section 7.7; `--code` ground, `--mono`, max 64 KiB and 200 lines from the Hub).

### 13.3 States

These are the states of Service logs; Activity's are in 13.4.

| State | Text |
|---|---|
| Loading units | Skeleton select |
| No services | Empty state "No services are switched on." |
| Locked | Above the controls: "Logs hold addresses and serial numbers, so reading them needs the setup code." Show reads "Unlock and show" and asks for the code first |
| Empty log | "Nothing logged." in the log's code block |
| Truncated | Under the box: "Only the end is shown: the rest is too long for this page." |
| Error | Error state in the log's code block with the Hub's text and **Try again** |

### 13.4 Activity

**What it holds.** The events that are something done, as a list: the time, who did it, what, and a link to the thing.
That is every action of the kinds in `09-implementation-order.md` Stage 13 (settings saved, features switched, printers
added, changed and removed, devices paired and removed, backups, restores and updates, catalog changes, slot clears,
filament-used undos, Recently added revisions), the spool kinds except "running low" and "OK again", the filament-used
entries and the renamed locations. Conditions (a printer offline, a spool low, a check that needs a look) are not
activity; they are the health history (4.2). Rows go back as far as the Hub keeps events (400 days unless changed).

```
Desktop (Activity chosen)
+--------------------------------------------------------------------------------------------------+
| Logs                                                                      [Collect a Hub report] |
| [ Activity | Service logs ]                                                                      |
| Who [All                v]    What kind [All                  v]                                 |
|                                                                                                  |
| TIME              WHO             WHAT                                  ABOUT                    |
| 2026-11-12 14:09  Kitchen phone   Moved spool 212 to Shelf B.            Spool 212     [Undo]    |
| 2026-11-12 14:05  Hub page        Set spool 214 to 482 g left.           Spool 214     [Undo]    |
| 2026-11-12 13:50  command line    Saved the alert settings.              Settings                |
| 2026-11-12 03:00  The Hub         Backup finished (4,812 KiB, encrypted). Backups                |
|                                                                                                  |
| Showing 4 of the newest events.                                                 [ Show more ]    |
+--------------------------------------------------------------------------------------------------+
Tablet: the same; About moves under What.
Phone:  rows become cards: time and who on one line, what under it, then About and Undo.
```

| Column | Content | Priority |
|---|---|---|
| Time | `at` as `YYYY-MM-DD HH:MM`, `--mono` | P1 |
| Who | The actor's name: a paired device's name, the trusted computer's name or "Hub page", "command line", "Claude connector", "The Hub" for the Hub's own jobs | P1 |
| What | The event's `text`, built by the Hub in its language ("Moved Bambu Lab PETG HF Orange (212) to Shelf B."). An undone row is struck through and ends "(undone)". | P1 |
| About | A link to the thing, from the event's `action`: a spool to `#spools/<id>`, a printer to `#printers/<id>`, a device to `#devices`, a storage location to `#settings/storage` | P2 |
| (action) | Ghost **Undo** on a row the Hub says can still be undone (`undo.possible`), for as long as it says so | P1 |

| Control | Does | Endpoint |
|---|---|---|
| **Who** | Select "All", then "The Hub", "Hub page", "Command line", "Claude connector" and each paired device by name | `G activity` (view) `actor=<type>` or `actor=<type>:<id>` |
| **What kind** | Select "All", "Spools" (the spool kinds and Clear slot), "Filament used", "Printers", "Devices", "Settings", "Backups and updates", "Catalog and records", "Storage locations" | `G activity` (view) `kinds` |
| **Show more** | Default button under the last row; adds the next 50 rows and moves focus to the first new one | `G activity` (view) `since` set to `next`, `limit` 50 |
| **Undo** (a row) | Asks the Hub to undo that event; the row's result reads "Put back." or the refusal (2.9), and the row is read again | `P events/<id>/undo` (code) |
| **Download as CSV** (page menu) | "Last 7 days", "Last 30 days" or "Last 12 months" as `activity.csv` (2.10) | `G export/activity.csv?days=<n>` (code) |

Reading Activity needs nothing, unlike the service logs; **Undo** and the download are changes of the page's lock and
ask for the setup code in place. Rows are newest first, 50 at a time, with "Showing <n> of the newest events." at the
foot while more exist.

| State | Text |
|---|---|
| Loading | Five skeleton rows; screen reader "Loading the activity." |
| Empty | Empty state "Nothing has been done yet." and the sentence "What people and the Hub do is listed here." |
| No match | "Nothing matches." and the default button **Show everything**, which sets both filters to All |
| Error | "Could not read the activity. <Hub's text>" and **Try again** |

### 13.5 Collect a Hub report

**Collect a Hub report** (default button in the header of Logs) makes one text file that someone can read as it is, for a
problem. It starts the job `report` (`P report` (code)); the job strip follows it (3.5); the inline result reads "Hub
report: done. It is kept beside the backups." and the default button **Download** (`P report/download` (code)) saves the
newest one as `text/plain`. The newest three reports are kept beside the backups; older ones go.

- **What it holds.** Spoolwarden's version; the versions of Spoolman, Python and the system; the features that are on;
  the Checks rows with their fix lines; the printers (kind and model, no name); the number of devices of each kind and
  their versions; the storage use; the log of the last update; the last 200 events (their kinds and times); the settings'
  names with their values where a value is not private; and the last 500 lines of each service's log.
- **What it never holds.** Addresses, host names, serials, tokens, keys, codes, e-mail addresses and the name of the
  user's folder are replaced by placeholders, with the rules the job log already uses; every printer's, device's,
  location's and the Hub's own name becomes `printer-1`, `device-2`, `location-3` and `hub`. The file's first lines say
  what it holds and what it never holds.
- **Lock.** Making and downloading it ask for the setup code in place. The apps say "Collect a Hub report on the Hub
  page." and do not offer it.

| State | Text |
|---|---|
| Running | The button shows the inline spinner; the job strip shows "Hub report…" |
| Done | OK result "Hub report: done. It is kept beside the backups." with **Download** |
| Failed | Error result "Hub report: failed. <Hub's text>" with the job log link |
| None yet | **Download** is absent |

**Main action:** Show (Service logs); Activity has none.

---

## 14. Where today's controls went

Every control and text block of today's page (the tabbed setup page), with its new place. "Kept" means same place
and meaning, possibly reworded; "Moved to" a new place; "Merged into" combined with another; "Renamed" a new label;
"Removed" with the reason.

### 14.1 Global chrome

| Today | Fate | New place and reason |
|---|---|---|
| Heading "filament-kit" | Renamed | Top bar product name "Spoolwarden" (3.1) |
| Document title "filament-kit setup: <server_name>" | Renamed | "<Page title> · <Hub name>", changing with the section (1.2) |
| 403 "the setup page only answers the home network" / "Open the setup page by the server's own name or address…" | Kept | Full-page error states, reworded (3.7) |
| 403 "bad origin" | Kept | Error at the refused change, reworded (3.7) |
| Intro paragraph ("Everything after the install is here; …") | Removed | Its meaning is in the unlock dialog ("Viewing needs nothing; every change needs it", where to find the code) and the lock chip hint (2.1); the command line is named where a fallback is needed |
| Sticky block (code card and tabs) | Removed | Replaced by the fixed top bar and navigation rail; a phone no longer loses half its screen (3.1, 3.2) |
| Setup code card and field | Moved to | Unlock dialog, opened from the lock chip or in place by any change (2.1) |
| "This computer is trusted (<name>): no setup code needed here." + link Trusted computers | Moved to | Lock chip state "Trusted computer" and its dialog with the link (2.6) |
| Trust offer: "Trust this computer?" text, **Trust this computer**, **Not now** | Merged into | Checkbox "Trust this computer" in the unlock dialog; Not now is not ticking it (2.1) |
| Tab nav "Console sections" (9 tabs) | Renamed | Navigation rail / bottom bar with twelve sections (3.2) |
| Tab "Modules" | Renamed | Features (9) |
| Tab "Presets" | Renamed | Slicer presets (8) |
| Tab "Intake" | Renamed | Recently added (6) |
| Background job card: title, state line, log, note | Moved to | Job strip and job indicator (3.5) |
| Job titles "Applying the changes", "Updating", "Rolling back", "Checking for updates", "Working" | Kept, extended | A title for every job (`02-components.md` section 8.4, and 3.5) |
| Job state texts running / lost / done / failed (exit N) | Kept | Reworded end lines (`02-components.md` section 8.4) |
| "The server is restarting; waiting for it to come back…" | Renamed | Restarting state "The Hub is restarting. This page comes back by itself." (3.6) |
| "Addresses and serials are hidden here." + **Show the whole log** | Kept | Job strip note and button (3.5) |
| Result boxes "Saving…", "Saved.", red error blocks | Moved to | Inline results beside the control, toasts, field errors (2.3) |
| Pills (OK / warn / bad) | Renamed | Status badges with shape and word (foundations 10) |
| Native confirm and prompt dialogs | Removed | Every one is a dialog of this document (5.5, 7.7, 10.11, 12.3, 2.6) |
| Cached result boxes surviving tab switches | Removed | Results belong to their control and clear when its region is read again (2.3) |
| Whole-tab redraw after each change | Removed | Only the changed region is read again; typed values survive (2.2) |

### 14.2 Overview

| Today | Fate | New place and reason |
|---|---|---|
| Card "Still to do" and its six items | Kept | Still to do card, each item with a button to the exact place (4.2) |
| "No setup code yet: at the server, sudo filament-kit setup-code" | Kept | Still to do item with a code block (4.2) |
| "Printers: none yet" → link | Kept | "Add your first printer." → Go to Printers (4.2) |
| "Phone: not paired" → link | Kept | "Pair a phone to add spools from it." → Go to Devices (4.2) |
| "Moving from another computer? Restore its backup" → link | Kept | → Restore a backup (4.2) |
| "Anthropic key: not set" → link | Kept | → Settings > Label Reader (4.2) |
| "Web passphrase: not set" → link | Kept | → Settings > Web passphrase (4.2) |
| Card "Status" head line "filament-kit <version> · mode <mode>" | Moved to | Overview header meta line, "Setup: <name>" (4.2) |
| Pill "<latest> is available" + link Update | Kept | Info badge linking to Updates, plus the Updates navigation dot (4.2, 3.2) |
| "The last install or update stopped halfway…" | Moved to | Half-install banner with the command in a code block (4.2) |
| Status rows with OK / needs a look / note / detail | Kept | Checks collection, sorted with problems first, OK rows folded (4.2) |
| "Fix: <fix>" | Kept | Fix column (4.2) |
| **Make the fields** | Kept | Row action (4.2) |
| "Addresses and serials are hidden until the setup code is given." | Kept | Quiet line with **Unlock to show** (4.2) |
| **Show addresses** | Merged into | Unlocking; addresses load by themselves once unlocked (2.1) |
| "Checking…" | Renamed | Loading skeleton (4.3) |
| Red error block | Renamed | Error state with Try again (4.3) |

### 14.3 Features (was Modules)

| Today | Fate | New place and reason |
|---|---|---|
| Card "Mode: <mode>" | Renamed | Card "Setup" with choice cards (9.2) |
| Mode buttons server / station / all-in-one | Renamed | Setups Hub / Weigh Station only / Hub with Weigh Station (9.1) |
| Disabled mode tooltip "A machine in this mode has no setup page" | Kept | "A machine with this setup has no Hub page." (9.3) |
| "Station mode has no server … sudo filament-kit modules set station --server …" | Kept | Note in the Setup card with a code block (9.2) |
| Preview panel: "Set the mode to <m>.", notes, "On afterwards:", setting fields, **Apply**, **Cancel** | Moved to | Preview drawer (9.4) |
| Preview loading "…" | Renamed | Skeleton (9.4) |
| Refusal (red) | Kept | Error banner in the drawer (9.4) |
| Card "Modules (mode: <mode>)" rows: pill, name, description, "needs", "OPTIONAL AI" | Kept | Features collection with plain names, "Uses AI" tag, Needs column (9.1, 9.3) |
| **Turn on** / **Turn off** | Kept | Row buttons opening the preview drawer (9.3) |
| "Turn on <name>." / "Turn off <name>." | Renamed | Drawer title "Turn on <feature>?" (9.4) |
| Refusal "this page is the server module's…" | Kept | Rewritten refusal; Hub service row has no button (9.4, 9.5) |
| "Saved; applying…" / "Unchanged." | Renamed | Toast "Saved; applying… Follow it in the job panel." / "Nothing to change." (9.4) |
| Card "Apply": text and **Apply again** | Moved to | Ghost **Apply the features again** under the collection (9.3) |

### 14.4 Printers

| Today | Fate | New place and reason |
|---|---|---|
| Tab-off card "The printers and klipper modules are off…" | Renamed | Switched-off page (5) |
| Card "Printers" list | Kept | Printer collection (5.2) |
| Empty texts "No printer yet. Printers on the network appear here…" / "No printer yet." | Kept | Empty state (5.9) |
| Bambu row heading (name, " Bambu" tag, model, address, serial, pill) | Kept | Columns Printer, Address, State; tag "Bambu Lab" (5.2) |
| Access Code field + **Connect** / **Replace code** | Moved to | Access Code dialog from **Connect** (primary when not configured) or **Replace Access Code** (5.3, 5.5) |
| **Test** | Renamed | **Test connection** (5.4) |
| **Rename** (prompt) | Kept | Text entry dialog (5.5) |
| **Change address** (prompt) | Kept | Text entry dialog with hint (5.5) |
| **Map slots** + confirm | Kept | Expansion primary with confirm dialog (5.3, 5.5) |
| **Map by loading filament** | Kept | Drawer flow (5.7) |
| **Collect a report** | Kept | Ghost, or primary with a problem line (5.3) |
| **Saved reports** | Kept | Drawer (5.7) |
| **Forget certificate** + confirm | Kept | Remove group, danger, dialog (5.3, 5.5) |
| **Forget** + confirm (two wordings) | Renamed | **Forget printer**, two dialog bodies (5.5) |
| Problem line "<why> Collect a report and attach it to an issue." | Kept | Message row "Needs a look: <why>" with Collect a report (5.2) |
| Per-row result boxes (general, map, report) | Merged into | One message row per printer (5.2) |
| Slot mapping step text, "Mapping…", problems, notes, "Slots: …", **Stop**, failure fallback | Kept | Step progress in the message row (5.7) |
| Map-by-loading: say, **Yes**, "No, I loaded" + **Save that**, nozzle select, "The slot it is in" + **Save (not checked by the printer)**, settling text, **Skip**, **Stop**, positions list | Kept | Drawer parts (5.7) |
| Share offer + **Yes, how do I share it?** / **No thanks** | Renamed | **Yes, show me how** / **No thanks** (5.7) |
| Reports list rows + **Download**, "No report kept…", `never` footer, "Collected <name>…" | Kept | Saved reports drawer, result text (5.7, 5.4) |
| Klipper found row: "found at", API key field, **Use this printer**, **Test**, **Forget** + confirm | Kept, reworded | Found group: **Use this printer** dialog, Test connection, **Dismiss** with dialog (5.2, 5.5) |
| Klipper row heading, " Klipper" tag, pills "API key set" / "no API key" | Kept | Columns and Connection badge (5.2) |
| Klipper key field + **Replace key** / **Set key** | Moved to | Moonraker API key dialog (5.5) |
| **Clear key** (no confirm) | Kept | **Clear Moonraker API key**, now with a confirm (5.5) |
| Select "Lane data: auto / on / off" | Renamed | Segmented choice Lane data (5.4) |
| **Detect** + "Asking it…" | Renamed | **Detect model and slots** (5.4) |
| Test result texts (eight) | Kept | Reworded (5.8) |
| Card "Live printer view" + link | Moved to | The printer's live view in its Detail region (5.10); the link is gone |
| Card "Add a printer": Type select, Bambu and Klipper fields, **Add** | Moved to | Add a printer drawer, **Add printer** (5.6) |
| Add errors (names itself, serial, bad address) | Kept | Field errors (5.6) |
| Card "Find Klipper printers": text, subnet field, **Scan**, results, limits | Kept | Find Klipper printers card (5.4, 5.8) |
| Card "Printer pack": text, **Show the commands**, "Checking the signed release…", commands + **Copy**, 409 | Renamed | Card "Klipper add-on" (5.4, 5.8) |

### 14.5 Devices

| Today | Fate | New place and reason |
|---|---|---|
| Card "Phones, PC and station" | Renamed | Card "Paired devices", with the columns Kind and Version and the button **Open** (7.2) |
| Row text "<name> · paired <date> · last seen <date>" | Kept | Columns (7.2) |
| "built in: this server's own pairing" | Kept | Tag "Built in" and "This Hub's own pairing" (7.2) |
| **Revoke** + confirm "Unpair <name>?" | Renamed | **Unpair** with dialog (7.2, 7.7) |
| "Nothing paired yet." | Kept | Empty text (7.8) |
| 409 on built-in revoke | Removed | Built-in rows have no Unpair (7.8) |
| **Pair a phone** | Kept | Header primary (7.2) |
| **Link for the PC sync** | Renamed | **Link Slicer Sync** (7.2) |
| **Link for the station** | Renamed | **Link a Weigh Station** in the header menu (7.2) |
| **Pair the station on this machine** | Renamed | **Pair the Weigh Station on this Hub** (7.2) |
| Pairing texts (phone, pc, station), QR, "Pairing code", fingerprint lines, "Expires in N min.", "Paired: <name>." | Kept | Pairing dialog with countdown bar (7.2) |
| Card "Stations asking to pair", text, **Show requests** | Renamed | "Weigh Stations asking to pair"; loads and refreshes by itself when unlocked (7.3) |
| "No station is asking to pair." | Kept | "No Weigh Station is asking to pair." (7.3) |
| Request text, six-digit hint, **Pair**, **Refuse**, "Paired <name>…" | Kept | (7.3) |
| Card "iPhone: the web app" | Renamed | "The web app on a phone" (7.4) |
| Home address + QR, Safari warning, public address + QR, "Add to Home Screen", error | Kept | (7.4); the home address gains **Open** |
| (none) | Added | Kind, version, "Out of date" lines and the detail of a device, the Weigh Station's included (7.9, 7.10) |
| Card "NFC readers" | Renamed | "Tag Readers" (7.5) |
| Reader rows + **Revoke** + confirm, "No reader tokens.", store error | Kept | (7.5, 7.7) |
| Name field + **Make a token**, token block, "Shown only this once…" note | Kept | (7.5) |
| Card "Trusted computers" + on/off pill | Kept | (7.6) |
| Policy paragraph | Kept | Shortened explanation (7.6) |
| "This computer is trusted (<name>)." | Kept | (7.6) |
| **Show the list** | Merged into | Unlocking; the list loads by itself (7.6) |
| **Stop trusting this computer** (no confirm) | Kept | Now with a confirm (7.6, 7.7) |
| **Turn trusted computers off / on** + confirm | Renamed | Toggle "Trusted computers" with a confirm when turning off (7.6) |
| List rows, **Rename** (prompt), **Revoke** (no confirm) | Kept | Collection; Rename dialog; Revoke now confirms (7.6, 7.7) |
| **Revoke all** + confirm | Kept | (7.6, 7.7) |
| "No computer is trusted.", "Reading…" | Kept | Empty text; skeleton (7.6) |

### 14.6 Slicer presets (was Presets)

| Today | Fate | New place and reason |
|---|---|---|
| Module-off card "Turn on the presets module…" | Renamed | Switched-off page (8) |
| Card "Build": last build line, "No build yet.", last attempt error, waiting text | Kept | Build card (8.2) |
| "The PC sync has reported in." / "PC sync: not set up. Pair it on the Devices tab." | Renamed | Slicer Sync badge and line (8.2) |
| Problems list | Kept | (8.2) |
| "Delete in Bambu Studio: <name>" / "Delete in Orca Slicer: <name>" | Kept | "Old presets to delete by hand" (8.2) |
| **Build now** | Kept | Section primary (8.2) |
| **Restore deleted presets** | Renamed | **Bring back deleted presets** (ghost) (8.2) |
| Card "Updates": count text, "differ" text | Kept | (8.2) |
| **Show what would be accepted** | Renamed | **Show what would change** (8.2) |
| Result list, **Accept these**, three result texts, 409 | Kept | (8.2) |
| Card "Product lines": error, empty text, line text, parents line | Kept | Collection (8.2, 8.3) |
| **Set Bambu Studio parent** / **Set Orca parent** | Merged into | **Set parent** with a menu (8.2) |
| No-parents text, select, **Save**, **Cancel** | Moved to | Set parent dialog, **Save parent** (8.2) |

### 14.7 Recently added (was Intake)

| Today | Fate | New place and reason |
|---|---|---|
| Card "Intake history" | Renamed | Section Recently added (6) |
| "The newest <keep> spool additions are kept… Change the number in Settings, General." | Kept | Header meta with link to Settings > Label Reader (6.2) |
| "Label reading (the ai_intake module) is off…" | Renamed | Badge "Label Reader off" and the Ask card's off state (6.2, 6.4) |
| "No spool has been added since the history started." | Kept | Empty state (6.4) |
| Record row: thumbnail (click to enlarge), names (or "no spools"), time, source, state word, spools, **Open** | Kept | List columns, "No spools" when a record has none; the row opens the record; photos enlarge in the record (6.2, 6.3) |
| State words "as detected", "revised by AI", "edited by hand" | Kept | Status badges (6.2) |
| Photo row / "No photo was taken for this addition." | Kept | Photos card with viewer (6.3) |
| "Item N: spool <ids> (filament <id>); changes apply to all of them" | Kept | Item choice (6.3) |
| Thirteen field inputs | Kept | Fields card, grouped, view then edit (6.3) |
| **Save changes**, "Nothing changed." | Kept | (6.3, 6.4) |
| Text area "What is wrong" + **Ask the AI to correct it** | Renamed | "Ask the Label Reader to correct it" card, **Ask the Label Reader** (6.3) |
| "Label reading is off on this server, so only edits by hand." | Kept | Off state of the Ask card (6.4) |
| "Asking the AI… (up to a minute)" | Renamed | "Asking the Label Reader… (up to a minute)" (6.4) |
| "The AI suggests:" / "The AI changed nothing.", no-photo note, before → after lines, **Accept**, **Discard** | Renamed | Suggestion change list naming the engine (6.3) |
| Revisions list, **Undo revision N**, "Saved." / filament sentences / "Undone." | Kept | Revision list and results (6.3, 6.4) |

### 14.8 Settings

| Today | Fate | New place and reason |
|---|---|---|
| Eight cards, about thirteen Save buttons | Merged into | Ten groups, one Save each at most (10) |
| General: "Display name" + Save | Kept | General (10.3) |
| General: "Locations, comma separated" + Save | Moved to | Storage locations, the list of locations (10.4) |
| General: "PLA rack", "Box location prefix", "Number of storage boxes", "Overflow location" (each + Save) | Moved to | Storage locations, one Save: PLA rack became a location that takes PLA, the boxes one Individual containers location, the overflow location the default overflow (10.4) |
| General: "Names for this page, space separated" + Save + DNS explanation | Moved to | Network and addresses (10.7) |
| General: "Allow printer changes from the public address" + explanation | Moved to | Network and addresses, saved with the group (10.7) |
| General: "Claude model" + Save | Moved to | Label Reader (10.5) |
| General: "Label reads per day" + Save | Moved to | Label Reader, "Reads per day" (10.5) |
| General: "Intake records kept" + usage line | Moved to | Label Reader, "Records kept" (10.5) |
| General: "Changing the model or the reads per day restarts the server." | Kept | Warn line in Label Reader and the restart dialog (10.5, 10.11) |
| General: "Station voice" two buttons | Moved to | Weigh Station voice choice cards (10.10) |
| General: Spoolman in use text + address field + **Change** | Kept | General, Spoolman address, saved with the group (10.3) |
| "Saved. The server restarts now; this page comes back by itself." | Kept | Restart notice (3.6) |
| Card "Backups": warning | Kept | Banner (10.6) |
| **Back up now** | Kept | Group primary (10.6) |
| **Show the backups** | Merged into | Unlocking; the list loads by itself (10.6) |
| Backup rows + **Download**, "Preparing the zip…", "No backups in <folder> yet." | Kept | (10.6) |
| "Keep nightly backups for N days" + **Save**, "Backups are kept for N days." | Kept | The group's Save (10.6) |
| Restore text, file field, **Upload and check**, "Uploading and checking…", "Choose the backup zip first." | Kept | Restore steps 1 and 2 (10.6) |
| Restore summary lines (backup of, replaces warning, other-host note, setup code note, SHA-256) | Kept | Check summary (10.6) |
| "Type restore to go on" + **Restore** + **Cancel** | Moved to | Typed-word dialog; Cancel renamed **Discard the upload** (10.6, 10.11) |
| Over-size error | Kept | (10.6) |
| Card "Anthropic API key" + pill | Merged into | Label Reader, Cloud part (10.5) |
| "Used for AI label reading (ai_intake)." / module-off text | Renamed | Field hint and off line (10.5) |
| Key field + **Set** / **Replace** | Kept | Replace reveals the field; the group's Save sends it (10.5) |
| **Remove** + confirm | Kept | Dialog (10.11) |
| **Check**, "Checking…", "wait 3 s between checks" | Kept | (10.5) |
| Card "Web passphrase" + pill, text, two fields, **Set** / **Replace**, mismatch text | Kept | Web passphrase group (10.8) |
| Card "Library token" + pill, text, field, **Set** / **Replace**, **Remove** | Removed | The Hub page no longer takes the token; a stored token keeps working and `spoolwarden catalog token` sets or removes it (10.9) |
| Card "Filament library": version, last check, skipped | Renamed | Filament Catalog state (10.9) |
| **Update now** | Kept | (10.9) |
| **Go back to the version before** + confirm | Kept | (10.9, 10.11) |
| Add entry text, text area, **Add entry**, "Added <vendor> <product>.", "entry not added: …" | Removed | The JSON text box goes; the form of Brand, Name and Material with **Add** takes its place (10.9) |
| (none) | Added | **See custom entries** with **Remove** per entry (10.9) |
| Card "Addresses": "Web public address" + Save | Renamed | Network and addresses, "Public address" (10.7) |
| Card "Addresses": "Station address" + Save | Renamed | Network and addresses, "Weigh Station address" (10.7) |
| "Saved; applying…" | Kept | "Saved; applying… Follow it in the job panel." (10.7) |
| Card "Remote access": module-off text, firewall text, **Show the firewall rules**, **Get the certificate** + confirm | Moved to | Network and addresses, Remote access part (10.7, 10.11) |
| (none) | Added | Appearance group: Light / Dark / System, Theme, Theme for new devices (10.2) |
| (none) | Added | Label Reader engine order, On this Hub address, Test and tier (10.5) |
| (none) | Added | Alerts group: alert switches, running-low and storage thresholds, notifications in this browser, test alert, recent alerts (10.13) |
| (none) | Added | Language in Appearance (this browser) and in General (the Hub), **Get more languages**, and **Try the demo** (10.2, 10.3, 3.9) |

### 14.9 Updates

| Today | Fate | New place and reason |
|---|---|---|
| "Installed: <v>", "Latest release: …", "Last checked …" | Kept | Version key-value list (12.2) |
| Held-back and failed-before lines | Kept | Reworded (12.2) |
| "Checked by itself <schedule> (the updates module)." / "Not checked by itself…" + Modules link | Renamed | "(Automatic updates)" and link to Features (12.2) |
| **Check now** | Kept | Header default (12.2) |
| **Update to <latest>** + confirm | Kept | Header primary with dialog (12.2, 12.3) |
| `update_refused` text | Kept | Error line and tooltip (12.2) |
| Card "What <v> brings" / "Release notes of <v>" | Kept | (12.2) |
| Card "Nightly builds": checkbox, two confirms, state texts | Not part of the design | The product has no nightly builds |
| Card "Roll back": texts, `going_back`, **Roll back to <v>** + confirm, `rollback_refused` | Kept | (12.2, 12.3) |
| Footer "To remove the kit: at the server, sudo filament-kit uninstall." | Kept | Foot with code block (12.2) |
| "Reading…", red error | Renamed | Skeleton, error state (12.4) |

### 14.10 Logs

| Today | Fate | New place and reason |
|---|---|---|
| "No services are on." | Kept | Empty state (13.3) |
| "Logs hold addresses and serial numbers, so this takes the setup code." | Kept | Locked line (13.3) |
| Select "Service" | Kept | (13.2) |
| Select "Lines" (50 / 100 / 200) | Renamed | Segmented choice (13.2) |
| **Show**, "Reading…" | Kept | (13.2) |
| Log output, "Nothing logged." | Kept | Code block with Copy (13.2, 13.3) |
| "Only the end is shown: the rest is too long for this page." | Kept | (13.3) |
| (none) | Added | Section Flash a device (11): writes firmware to a Tag Reader or a Weigh Station display over USB |
| (none) | Added | Activity beside the service logs (13.4), with Undo in its rows (2.9) |
| (none) | Added | **Collect a Hub report** (13.5) |

### 14.11 Spools

| Today | Fate | New place and reason |
|---|---|---|
| (none: the Hub page had no spool list; spools were found in the web app and the app) | Added | Section Spools: list, search, chips, detail and its actions (16) |
| (none) | Added | Header link **Open Spoolman** (16.2) |
| (none) | Added | A spool's last ten events (16.3); Undo toasts (2.9); Download as CSV and Import from CSV (2.10) |
| (none) | Added | Section Analytics: the month in sentences, the months as bars and tables (17) |
| (none) | Added | **Print a label** on a spool, **Print labels** on selected spools and on a Recently added record, the print page (16.5, 6.3) |

---

## 15. Needs from the Hub

What this design uses that the Hub does not offer today. Until each exists, the page does what the "Until then"
column says.

| Need | Used by | Until then |
|---|---|---|
| A stored default theme for new devices (a general setting `appearance.theme`, the key the command line uses, readable in `G state` and writable through `P settings/general`) | Settings > Appearance, Theme for new devices (10.2) | The field is hidden and no default can be set (the command line's `config theme` needs the same stored setting); devices that have not chosen use Console |
| Saving several general settings in one request, all or nothing | Every Settings group's Save (2.2) | One request per field, in order, stopping at the first refusal |
| A way to check the setup code without side effects | Unlock dialog (2.1) | `P overview` with the code |
| A test of an On this Hub address before it is saved, gated like a change (today `G settings/local-intake` checks only the saved address) | Label Reader Test button (10.5) | Test is disabled while the Address field holds an unsaved change |
| A release of the unreleased endpoints and settings: `G firmware`, `G firmware/<id>.bin`, `P flash/provision`, `P flash/server`, job `reader_setup`; `G settings/local-intake`, `intake.reader`, `local_intake.url`, `local_intake.tier`, the 409 `no_photo` answer | Flash a device (11); Settings > Label Reader (10.5); Recently added (6.4) | Flash a device shows its "No firmware to write" empty state; the Label Reader group shows only the Cloud fields and Records kept |
| Per-field confidence and the engine that read it, stored with each Recently added record | Confidence column, To check filter, field flags (6.2, 6.3) | The column, filter and flags are hidden |
| Last backup time readable without the setup code (the time only: no file name, folder or size) | Settings list of groups (10.1) and the Backups group's first line, for a locked visitor too | Until the Hub gives it: shown only when Unlocked or Trusted. A backup's result and the list of backups are never shown to a locked page. |
| A progress fraction for jobs | Job strip determinate bar (3.5) | Indeterminate bar and the last log line |
| One rule for Bambu Lab address and certificate changes: whether changing the address (`P printers/<serial>/address`) and forgetting the certificate (`P printers/<serial>/unpin`) take the Access Code (`access_code`) and use it, as the web app and the app ask for it | Change address and Forget certificate dialogs (5.5) | Both dialogs ask for the Access Code, so every interface behaves the same; the page sends it with the request as `access_code` |
| Printer states for the whole list in one light read, or a change stream | Printers refresh every 10 s (2.7) | `G state` every 10 s |
| Feature titles in the plain names of section 9.1 | Features collection | The page maps code names to the names of section 9.1 |
| Cloud reads used today and the daily limit as numbers in `G state` | Overview Label Reader tile (4.2) | The numbers are taken from the Overview check row that reports them; when that row is missing the tile shows "Reads per day: <limit>" |
| Share corrections: what the reader can do and its state (it offers sharing, sharing on or off, how many wait), the setting `label_reader.share_corrections` with the job that sets the reader, the corrections waiting (list, thumbnails, remove, remove all, try again, package, send), and each correction handed to the reader when it is saved | Settings > Label Reader (10.5.1, 10.5.2), Recently added (6.2, 6.4), Overview tile (4.2), Features preview (9.4) | The block SHARE CORRECTIONS shows only its paragraph and the line "Not available on this Hub yet."; nothing else of the feature is shown |
| An event store with `GET api/events?since=&since_at=&alert=&wait=&kinds=&limit=&client=` answering `{events: [{id, at, kind, severity, subject: {type, id, name}, actor: {type, id, name}, data: {}, condition: {key, state} or null, alert: true or false, title, text, action: {place, id}}], next, oldest, gap, test: {title, text} or null, conditions: [the raised ones, same shape]}` (`since` is an id and `since_at` a time, UTC, one of them; `alert=1` returns only events of alert types that are on; `wait` up to 55 s; `alert` in an event says whether an alert type that is on covers it; `oldest` is the lowest id still kept and `gap` is true when `since` is lower than `oldest` minus one, because events between were deleted by age; `test` is the test alert of `POST api/alerts/test` for the caller, given once; `client` is the browser id of the Hub page, kept in `localStorage` `spoolwarden.browser`, and a paired device is known by its token; `title` and `text` are built in the Hub's language) | Alert banners, toasts and the Alerts list on every section (2.8), Settings > Alerts > Recent alerts (10.13) | No banner, toast or Alerts list; the "Recent alerts" link is hidden |
| `GET api/alerts` answering `{types: [{key, title, on}] (exactly the eight fixed keys `runout`, `paused`, `failed`, `printer_error`, `finished`, `storage`, `running_low`, `device_down`), last_spool_only, running_low_g, storage_warn_percent, storage_bad_percent}` and `P settings/alerts` (code) with the same fields (the names may be adjusted by the Hub; the fields may not); the write is the setup code's alone: no route lets a paired phone or the web app change the alert types or thresholds | Settings > Alerts (10.13) | The group is hidden |
| `POST api/alerts/test`: stores nothing; the Hub keeps one test for the caller (the paired device of the token, or the browser id sent as `client`) for 60 seconds and gives it once as `test: {title, text}` in that caller's next `GET api/events` answer | **Send a test alert** (10.13) | The button is hidden |
| `POST api/events/web` `{events: [{kind, at, subject, actor, data}]}`, a web-only route for the web unit's own events: the Hub accepts only the `spool.*` kinds, gives the id, keeps the `at` and sets the actor (`device` for the phone web app, `connector` for the connector's tools); only the web unit calls it, with its token | The web unit's spool events (09 Stage 10) | The events of spool changes made through the web unit wait in the web unit's outbox (at most 500) |
| `GET api/spools/low` answering `{threshold_g, spools: [{id, filament, material, color, remaining_g, location, in_stock, last_one}]}`, least filament first | Overview, Running low card and its dialog (4.2) | No Running low card |
| `GET api/storage-use` answering `{filesystems: [{path_label, total, free, percent_used, state}], items: [{key, title, bytes}]}` (not `api/storage`, which is the storage locations route) | Overview, Storage row and Storage use panel (4.2) | No Storage row |
| A stored list of storage locations (`storage.xml` in the Hub's state folder, written by the Hub and read by the web unit) with `GET api/storage` and `P settings/storage` (code): the read answers `{locations: [{id, name, type: "bulk" or "containers", limit or null, count or null, used, free or null, prefix or null, containers: [{name, number, taken}] or null, fill: "none", "any" or "materials", materials: [], overflow, default_overflow, sealed, position}], order_by_material: [{material, locations: [names]}], everything_else: [names]}`; on an Individual containers location `containers` is the whole set in number order (as many as `count`): `name` is the exact location text of a spool in that container ("Storage box 03"), `number` the whole number, `taken` true while a spool's location is that name, and `prefix` is the exact text before the number, for information; both are `null` on Bulk storage, and `used` and `free` equal the counts of `taken`; a client never builds a container name, not from `name` and not from `prefix`: it matches a spool's location text with each location's `name` (taken first) and each `containers[].name`, and to place or move a spool it sends the set's `name` (the Hub takes the lowest free container) or one `containers[].name`; a text that matches nothing (a removed location, a text typed by hand) is shown as it is, under no location; the write takes the whole list `{locations: [...]}` (ids kept for existing rows, none for new ones) and answers the saved list, or `errors` per row and field | Settings > Storage locations (10.4) | The group shows "Could not read the settings. <Hub's text>" with **Try again**, and the list cannot be edited |
| `GET start` answering `{show, hidden, finished, restore_offer: true or false, done, total, steps: [{id, state: done or next or open, line, target}]}` and `POST start` (code) with `{hide: true or false}` or `{keep: "name", "storage" or "features"}`, served in the Hub process; the step ids are fixed: `name`, `storage`, `features`, `reader`, `key`, `printer`, `slots`, `phone`, `passphrase`, `pc`, `spool`, `backup` (the Restore row is not a step: `restore_offer` says whether it shows); the marks are kept in `firstrun.xml` in the Hub's state folder | Overview, Getting started (4.2) | No Getting started panel and no line; Still to do shows as it always did |
| The Hub's port in the answer of `G settings/general` (`port`), and the change of it as a job (`P job` (code) with the new port) | Settings > Network and addresses, Hub port (10.7, 10.11) | The Hub port row is hidden |
| The three values a Weigh Station tells the Hub at every start on `GET api/station/hello`: `fp` (the SHA-256 of its certificate), `port` and `version`, kept with its pairing | The Hub's calls to a Weigh Station (7.3), the Checks row "The Weigh Station <name> is not using HTTPS. Update it." (4.2) | A Weigh Station that sends none (not updated, or it could not make its certificate) is called over plain HTTP as before, and the Checks show that row; a station whose certificate is pinned is never called over plain HTTP, and the Checks show the error row "The Weigh Station <name> does not show the certificate the Hub saved for it." |
| Printers announced by Bambu Lab printers, listed by the Hub's own listener for them | Add a printer, step 1 (5.6) | The found list holds Klipper printers only, with the sentence "Bambu Lab printers are added by address." |
| A Label Reader on another machine that serves HTTPS on its port (a change in the reader's own repository) | Settings > Label Reader, Address and Test (10.5) | The Hub accepts the reader's `http://` address as before and the Checks show the Note "The Label Reader at <address> is not using HTTPS. A later Label Reader version adds it." |
| The page routes of the Spools section, under `/setup/api/`: `GET spools` (`q`, `filter`, `offset`, `limit`; answer `{spools, total, offset, has_more, spoolman_url?}`, `filter` one of `sealed`, `opened`, `loaded`, `low`, none meaning every spool that is not empty), `GET spools/{id}` (`{spool, last_use: {at, printer, grams}?}`), `POST spools/{id}` (`{gross` or `remaining` or `location` or `auto_location: true` or `empty`, `dry_run}` → `{spool, before, dry, event_id?}`), `GET spools/last-tag` (`{tag: {uid, read_at, source}?}`), `POST spools/{id}/link` (`{tag, dry_run}` → `{spool, before, dry, event_id?}`); a spool carries `loaded` and `low` besides the spool view; the three changes need the page unlocked; a change answers `event_id`, the id of its event, absent on a dry run (2.9) | Spools (16) | The section shows the error state "Could not read the spools. <Hub's text>" with **Try again** |
| The page routes of the live view: `GET printers/{id}/live` (`{summary, status}` as `GET api/printers/{id}` gives them, the slots with `pending`), `POST printers/{id}/command` (`{action}`: `pause`, `resume`, `stop` with `confirm: true`, `light_on`, `light_off`), `POST printers/{id}/slots/{label}/load`, `unload` and `clear` (`{spool_id?, dry_run}`; `clear` answers `{slot, spool?, moved_back?, waiting_ended, printer_cleared, dry_run}`; each of the three also answers `event_id`, absent on a dry run), `GET printers/{id}/usage` (`days`), `POST usage/{entry}/undo`, `GET printers/{id}/camera.mjpeg` and `camera/{name}` (on a computer that is not trusted, with `?ticket=<ticket>` from `POST printers/{id}/camera/ticket`, which takes the setup code and answers `{ticket, expires_in: 60}`: the first camera request that carries `?ticket=` spends the ticket and gets a camera-session cookie, valid only for that printer's camera routes and for 10 minutes after the last camera request; at most 8 sessions, the ninth ticket is refused with "Too many camera views are open. Close one first."), `POST printers/{id}/camera/close` (needs only the camera-session cookie; answers `{closed: true}`); they call the same printer code as the kit routes, in the Hub's process, and not the web app's routes; the state and usage reads are open, `camera/close` needs only the camera-session cookie, and every other route, the camera included, needs the page unlocked | Printers, the live view (5.10) | The expansion shows the facts of 5.3 and no live view |
| The Hub page's part of the catalog form: `GET library/local` (`{entries: [{id, brand, name, material, added}]}`), `POST library/local` (the form's values; 400 `{error: "invalid_entry", problems: [{field, text}]}`) and `POST library/local/{id}/remove` (`{removed: true}`); the Hub builds the entry from the values with one function | Settings > Filament Catalog (10.9) | The group shows its state and the update buttons only |
| Devices: `GET devices` (`{devices: [{id, name, kind, version?, newest?, out_of_date, advice?, paired?, last_seen?, reachable?, built_in, page}]}`, `kind` one of `phone`, `pc`, `station`, `web`, `reader`, `builtin`; the Tag Readers are rows of it), `GET device/{id}` (`{device, status?, settings?: [{id, label, kind, value, choices?, min?, max?}], own_page: <address as text>?, photo: bool}`), `GET device/{id}/photo` (open; `image/jpeg`), `POST device/{id}/settings` (code) and `POST device/{id}/open` (unlocked; the Hub asks the station for a one-time ticket and answers `{address: "<own_page>#ticket=<ticket>"}`); what the Hub takes from a station is checked (JSON only, at most 256 KiB, 5 seconds, no redirect, only to the stored host and port over the pinned certificate; a setting's `id` matches `[a-z0-9_.-]{1,40}`, its `kind` is `switch`, `choice`, `number` or `text`, a `label` is at most 80 characters, at most 60 settings; the photo is `image/jpeg`, at most 4 MiB; 7.10); the Hub keeps each client's `X-Spoolwarden-Client: <kind>/<version>` and each reader's `X-Reader-Build` with its pairing, and a Weigh Station's hello gives its version every 5 minutes; `GET state` keeps its `devices` and `readers` fields | Devices (7.2, 7.9, 7.10) | The list is the one of `G state`, without Kind, Version and out-of-date lines |
| `GET api/events` takes `activity=1` (only the kinds of the Activity list), `subject=<type>:<id>` (for example `spool:212`) and `actor=<type>` or `actor=<type>:<id>`; each served event gains `undo: {possible: bool, until?, why_not?: "changed_since" or "too_old" or "already_undone" or "not_undoable"}`, `undone: bool` and `undo_of?: <id>`; `POST api/events/{id}/undo` answers 200 `{undone: true, event: <the new event>, note?: <text>}`, 409 `{error: <one of the why_not values>, text}` or 404; a web token may call it; the routes that make an undoable change (`PATCH api/spools/{id}`, `POST api/spools/{id}/link`, the slot `load`, `unload` and `clear` routes) answer with `event_id` beside what they answer today, absent on a dry run | Activity (13.4), Undo (2.9), a spool's last ten events (16.3) | No Activity choice, no Undo button, no last ten events |
| The page routes of history and data, under `/setup/api/`: `GET activity` (`subject`, `actor`, `kinds`, `since`, `limit` → `{events, next, oldest}`, the events as the kit route serves them; open), `POST events/{id}/undo` (as the kit route; code), `GET health` (`days`; open), `GET analytics` (`months`, `printer`; open), `GET export/{set}.csv` (as the kit route; code, because a file leaves the Hub), `POST import/spools` and `POST import/locations` (as the kit routes; code), `POST report` (starts the job; code) and `POST report/download` (the newest report, `text/plain`; code) | Activity, Undo, the Checks' history (4.2), Analytics (17), CSV (2.10), the Hub report (13.5) | Each of these places is left out |
| `GET api/health` (`days` 7 or 30) answering `{from, to, since?, checks: [{key, group, text, now: "ok" or "look" or "bad", spans: [{from, to, state: "look" or "bad"}]}], changes: [{at, key, text, from, to}]}`, built from the conditions the event store already records (`since` is when that history starts) | The strips and the history table of the Checks (4.2) | The strips are left out and the Checks show as they did |
| `GET api/analytics` (`months` 1 to 13, `printer?`) answering `{months: [{month: "2026-11", grams, prints, unfinished_prints, unfinished_grams, logged_only_grams, no_weight_prints, by_printer: [{id, name, grams, prints}], by_material: [{material, grams}], top_material?}], insights: [{key: "total" or "favourite_material" or "busiest_printer" or "unfinished" or "biggest_print" or "spools_finished", text}], notes: [<text>]}`; each new filament-used entry also stores `material`, `vendor`, `name`, `color_hex`, `printer_name` and `outcome` (`finished`, `failed`, `cancelled`, `unknown`), and `GET api/printers/{id}/usage` takes `by=month` | Analytics (17), the Overview line (4.2) | The Analytics section shows the error state "Could not read the usage. <Hub's text>" with **Try again**; no Filament line |
| `GET api/export/{set}.csv`, set one of `usage` (`days`, `printer`), `locations`, `recent`, `activity` (`days`), `printers`, `lines`, `spoolman-spools`, `spoolman-filaments`, answering `text/csv; charset=utf-8` as a download; `POST api/import/spools` (the file as the body, `text/csv`; `dry_run` 1 by default) answering `{rows: [{n, ok, problems: [{column, text}], line}], add, dry, spool_ids?}` and `POST api/import/locations` answering `{rows, add, change, dry}`; a web token may call the exports, not the imports | CSV downloads and imports (2.10) | The menus do not offer them |
| The backup password: `POST backups/password` `{password}` → `{set: true}` or 400 `{error: "too_short", text}` (code); `POST backups/password/remove` → `{set: false}` (code); `POST backups/list` rows gain `encrypted: bool` and the answer `password_set: bool`; `POST restore/password` `{password}` (for the uploaded file) → `{ok: true}` or 400 `{error: "wrong_password", text}` (code) | Settings > Backups and restore (10.6, 10.11) | The group keeps its warning and offers no password |
| The kind `home-assistant` in `GET devices` and the pairing kind `{kind: "home-assistant"}` of `POST pair`: a pairing with the role `viewer`, which may call only these routes, all GET: `api/info`, `api/hub`, `api/events`, `api/alerts`, `api/printers`, `api/printers/{id}`, `api/printers/{id}/usage`, `api/printers/{id}/camera.mjpeg`, `api/printers/{id}/camera/{name}`, `api/spools`, `api/spools/{id}`, `api/spools/low`, `api/storage`, `api/storage-use`, `api/health` and `api/analytics`; every other route answers 403 | Devices, **Link Home Assistant** (7.2) | The item is not offered |
| Languages: `GET languages` (`{hub: "<code>", languages: [{code, name, reviewed, installed, complete}], available: [{code, name, reviewed, complete}], problem?}`, `complete` 0 to 100; `available` is the release's packs and is empty, with `problem`, when the list could not be fetched; open), `POST languages/{code}/install` (starts the job; code), `POST languages/{code}/remove` (`{removed: true}`; code) and `POST settings/language` (`{hub: "<code>"}` → `{hub}`; code), and the kit routes `GET api/languages` (the same without `available`) and `GET api/strings/{code}.js` (the texts of that language as the pages load them, English filled in where a translation is empty) | Appearance and General: Language, Get more languages (10.2, 10.3) | The Language fields and **Get more languages** are hidden and the page is in English |
| `key` and `params` beside `text` in every answer that carries a text the Hub wrote (an alert's title and text, a Checks row, a refusal); `text` is in the language the caller asked for (`Accept-Language`, or `?lang=<code>`), else the Hub's language, else English; and `language: "<code>"` in `GET api/info` and `GET api/hub` | Every text the Hub writes (2.3, 2.8, 4.2) | The text is shown as sent, in English |
| The demo: `POST demo` (`{on: true or false}` → `{demo}`; 409 `{error: "not_empty", text}` with the text "The demo is for an empty Hub. This Hub has real data."; code) and `demo: true` in `G state`, `GET api/info` and `GET api/hub` while it is on; the answer "Not in the demo." to every route that would reach outside the Hub (3.9) | The demo banner and Leave demo (3.9), Getting started (4.2), Settings > General (10.3) | No demo is offered and no banner is drawn |
| Spool labels and the short address: `GET /s/{id}` (a redirect to the spool, 404 for an unknown number), `GET api/spools/{id}/label.svg` and `GET spools/{id}/label.svg` (`size` one of `62x29`, `50x30`, `sheet24`; `image/svg+xml`; open), and the page route `GET labels` (`ids=<n,n,...>`, `size`; the print page, HTML with the labels as inline SVG; open) | Print a label, Print labels, the print page (16.5, 6.3) | The buttons are not shown |
| A Checks row for a data file that could not be converted: "<What it is> could not be converted (<reason>)." in group Hub, Needs a look, with a Fix | The Checks on Overview (4.2) | The file is left unconverted and nothing says so |

---

## 16. Spools

**Purpose.** Find any spool, see where it is and what is left of it, and keep its record right: update its weight, move
it, link a tag, mark it empty. Group Everyday, after Printers (foundations section 8); on a phone inside the More sheet.
Address `#spools`; one spool `#spools/<id>`. Adding spools stays on the phones (`04-web-app.md` 4, `05-android-app.md` 6).

**Data.** `G activity` (view) with `subject=spool:<id>` and `limit` 10 for a spool's last ten events; `G spools` (view) with `q`, `filter`, `offset` and `limit` (50 by default) → `{spools, total, offset, has_more,
spoolman_url?}`; `G spools/<id>` (view) → `{spool, last_use?}`; `G spools/last-tag` (view) → `{tag?}`; the changes `P
spools/<id>` (code) and `P spools/<id>/link` (code). A spool in these answers is the spool view of the Hub's inventory:
`{id, location, remaining_g, net_g, tare_g, tag, state, filament_id, vendor, name, material, color_hex, lot}` with
`loaded: {printer_id, printer, slot}` when it is in a printer and `low` when it is running low. The page routes are in
section 15.

### 16.1 Layout

```
Desktop: list
+--------------------------------------------------------------------------------------------------+
| Spools                                                                                           |
| Spools                                                                        [Open Spoolman]    |
| 214 spools                                                                                       |
| [ Search: brand, name, material, location, number or tag                      ]                  |
| [Sealed] [Opened] [In a printer] [Running low]                                                   |
|                                                                                                  |
|  NO.  SPOOL                                MATERIAL  LEFT            WHERE             STATE   TAG |
|  214  [#] Polymaker PolyTerra PLA ...      PLA       (o) 620 g       Workshop X1 · A1  Opened  Tagged |
|           Charcoal Black #2B2B2E                                                                 |
|  212  [#] Bambu Lab PETG HF Orange         PETG      (o) 880 g       Workshop X1 · A2  Opened  Tagged |
|  213  [#] Bambu Lab PETG HF Orange         PETG      (O) 1000 g      Shelf B           Sealed  No tag |
|   77  [#] Polymaker PETG Teal              PETG      (o) 140 g /!\ Running low  Rack 2  Opened  No tag |
|                                    Showing 50 of 214   [ Show more ]                              |
+--------------------------------------------------------------------------------------------------+

Desktop: one spool (#spools/214)
+--------------------------------------------------------------------------------------------------+
| Spools / Spool 214                                                                  [< Back]     |
| Polymaker PolyTerra PLA Charcoal Black                                                           |
| Opened · 620 g left · Workshop X1 · A1                                                           |
| +-- The spool --------------------------------+ +-- Actions ------------------------------------+ |
| | (ring)  62 %   620 g left of 1000 g          | | [Update weight] [Move] [Link the last tapped tag] | |
| | Spool          214                           | |   Weight updated: 482 g left.                  | |
| | Material       PLA        Lot  F57           | | ---------------------------------------------- | |
| | Colour         [#] #2B2B2E                   | | [Mark empty]                                   | |
| | Empty spool    140 g                         | +------------------------------------------------+ |
| | Where          Workshop X1 · A1              |                                                  |
| | Tag            04A1B2C3D4                    |                                                  |
| | Last filament taken off it                   |                                                  |
| |                12.4 g, Workshop X1, 2026-11-12 14:05                                            | |
| +----------------------------------------------+                                                  |
+--------------------------------------------------------------------------------------------------+

Tablet: the list keeps No., Spool, Left and Where; Material, State and Tag move under the spool's name. The detail
        opens in place under its row (the inline expansion), one column.
Phone:  rows become cards (swatch, number and name, grams with the ring, where it is, state); a spool opens as a full
        page with the same parts, and its actions in a column under the facts.
```

### 16.2 List

A collection (`table` profile in Console), filled from `G spools`.

| Column | Content | Priority |
|---|---|---|
| No. | The spool's number, `--mono` | P1 |
| Spool | The filament swatch (`02-components.md` 7.3) and "<vendor> <name>" as the link to `#spools/<id>`; under it the colour's hex in `--mono` `--muted` | P1 |
| Material | `material` | P3 (under the name on tablet and phone) |
| Left | The small spool ring (`02-components.md` 7.4) and "<g> g"; a sealed spool shows its net weight; a spool that is running low adds the warn shape and "Running low" | P1 |
| Where | `location`; for a spool in a printer "<printer> · <slot>" as a link to `#printers/<id>`; "No place" in `--muted` when it has none | P2 |
| State | Status badge "Sealed" or "Opened" | P2 |
| Tag | "Tagged" with the tag icon, or "No tag" in `--muted` | P3 |

- **Search.** A text field, label "Find a spool", placeholder "Brand, name, material, location, number or tag". It
  matches the way the Hub's own word match does (`inventory.find`): every word must be found in the brand, name,
  material, location, spool number or tag. It searches 300 ms after typing stops, and on Enter.
- **Chips.** Four toggle chips under the field: **Sealed**, **Opened**, **In a printer**, **Running low**. One is on at
  a time (`filter` `sealed`, `opened`, `loaded` or `low`); pressing the chosen one again, or **Show all spools** in the
  empty state, shows every spool that is not empty. A chip works together with the search.
- **Paging.** 50 rows at a time. Under the last row "Showing <n> of <total>" and the default button **Show more**, which
  adds the next 50 and moves focus to the first new row (foundations section 12, rule 7).
- **Header.** The meta line holds the count, "<total> spools" ("1 spool"). At the right, the ghost link **Open
  Spoolman**, which opens Spoolman's own page in a new tab (`spoolman_url`, given by the Hub: the address with the host
  name the person uses for the Hub, or the configured address of a Spoolman elsewhere). Spoolman's page is plain http.
  The link is absent when the Hub gives no address. The page never builds the address itself.
- **Selection.** The list offers selection (`02-components.md` 6.1): a checkbox "Select <name>" in the first cell and
  the header checkbox for the rows of the page. With one or more selected the selection bar shows "<n> selected", the
  default button **Print labels** (opens the print page, 16.5, for those spools) and **Clear selection**.
- **Menu.** The page menu (3.8) also holds **Download as CSV** ("Spools (Spoolman's file)" and "Filaments (Spoolman's
  file)") and **Import from CSV** (2.10).

### 16.3 Spool

The Detail region of the theme: in Console the inline expansion under the row on tablet and desktop, a full page on a
phone. Address `#spools/<id>`.

| Part | Content |
|---|---|
| Header | Breadcrumb "Spools / Spool <id>" with the list as link; title "<vendor> <name>"; meta: state badge, "<g> g left", the place. Ghost **Back** (to `#spools`) |
| The spool | Key-value list with the large spool ring: Spool, Material, Colour (swatch and hex), Net weight and Left, Empty spool weight, Lot, Where, Tag ("None" when there is none) |
| Last filament taken off it | "<g> g on <printer>, <date and time>", or "No filament has been taken off it yet." (`last_use`) |
| Latest events | Title "Latest events": the spool's last ten events, newest first, each with the time (`--mono`), who and what (the Hub's `text`); empty: "Nothing has been recorded for this spool yet." |
| Actions | **Update weight** (primary), **Move**, **Link the last tapped tag**, **Print a label**, and, apart under a hairline, **Mark empty** (danger). Each shows its result beside the button |

Every action previews first, with the Hub's dry run, and shows what would change before anything is saved. Changes need
the page Unlocked or Trusted, like every change on the Hub page (2.1); looking does not.

| Control | Does | Endpoint |
|---|---|---|
| **Update weight** | Opens a small form in place: a segmented choice "Weight with the spool" / "Filament left" and a number field in g. A valid number shows the preview "Remaining changes from 620 g to 482 g."; then the primary **Save weight**. Result "Weight updated: 482 g left." | `P spools/<id>` (code) `{gross or remaining, dry_run}` |
| **Move** | Opens a menu "Move to": "Automatic" first, then every storage location in fill order with how full it is (as 10.4 and `04-web-app.md` 5.4 give them; a full one stays choosable and says "Full"). A choice shows the preview "Spool 214 would move to Shelf B." with **Move**. Result "Moved to Shelf B." | `P spools/<id>` (code) `{location, dry_run}`; for "Automatic" `{auto_location: true, dry_run}` (the Hub moves the spool where its placement rule puts it) |
| **Link the last tapped tag** | Shows the last tag ("Tag <id>, tapped <age> on the Tag Reader", read when the detail opens and every 3 s while it is open) and the preview "Tag <id> would be linked to spool 214." with **Link tag**. With no tag read the button is disabled with "No tag read yet: tap the spool's tag on a reader." Result "Tag linked." | `G spools/last-tag` (view); `P spools/<id>/link` (code) `{tag, dry_run}` |
| **Print a label** | Opens the print page (16.5) for this spool in a new tab. It changes nothing, so it needs no code and writes no event | `G labels?ids=<id>` (view) |
| **Mark empty** | Dry run, then the dialog "Mark spool <id> empty?". Result "Marked empty." | `P spools/<id>` (code) `{empty: true, dry_run}` |

Each of these actions also raises the toast of 2.9 with **Undo**, and the latest events list reads again after an Undo.
The preview, the Hub's refusals (for example a tag that belongs to another spool) and every result show beside the
button that was pressed, in an `aria-live="polite"` region, and are never lost by another part's redraw.

### 16.4 Dialogs, results and states

| Dialog | Title | Body | Buttons |
|---|---|---|---|
| Mark empty | "Mark spool <id> empty?" | "<Vendor> <name> will be marked as used up." | Cancel (focused first) · **Mark empty** (danger) |

| Event | Shape | Text |
|---|---|---|
| Weight preview | Note | "Remaining changes from <before> g to <after> g." |
| Weight saved | OK | "Weight updated: <g> g left." |
| Moved | OK | "Moved to <place>." |
| Tag linked | OK | "Tag linked." |
| Marked empty | OK | "Marked empty." |
| Undone | OK | "Put back." |
| Undo refused | Note | "This changed again since, so it cannot be undone." (any other refusal as the Hub sends it) |
| Weight not a number above 0 | error, at the field | "Enter grams above 0." |
| The Hub refuses | error | The Hub's text, as sent |

| State | Text |
|---|---|
| Loading | Five skeleton rows; a spool: skeleton ring and facts |
| Empty (no spools at all) | Empty state with the spool icon: title "No spools yet", sentence "Add your first one from your phone." (read together: "No spools yet. Add your first one from your phone.") |
| No match | "No spools match." and the default button **Show all spools** |
| Spool not found (a deep link to an empty or removed spool) | Error state "This spool is not in the inventory." with **Back to Spools** |
| Locked | The list and the facts show; every action asks for the code in place |
| Error | "Could not read the spools. <Hub's text>" + **Try again** |

**Main action:** none in the list (it is for finding); in a spool, **Update weight**.

### 16.5 Print a label and Print labels

**What is printed.** A label for each chosen spool, drawn by the Hub as SVG (`02-components.md` 7.13): the QR code, the
spool's number large, brand, name, material, a box in the filament's colour with its hex value, the lot, the date it
was added, the net weight, and the nozzle and bed temperatures when the filament has them. It is black on white; the
colour box is the only colour. Scanning the code opens the spool: the short address
`https://<name>.local[:port]/s/<number>` goes to the web app's spool when the web app is on (`/intake#spools/<number>`)
and otherwise to this page's Spools section (`#spools/<number>`). The Android app's **Scan a label** opens the spool
whatever Hub address is printed, because it uses only the number after `/s/` (`05-android-app.md` 7).

**Where it starts.** **Print a label** on a spool (16.3), **Print labels** on the selected spools (16.2) and **Print
labels** on a Recently added record, for the record's spools (6.3). Each opens the print page in a new tab:
`G labels?ids=<n,n,...>&size=<size>` (view), an HTML page with the labels as inline SVG.

```
+--------------------------------------------------------------------------------------------------+
| Print labels                                                                                     |
| Size   [ 62 x 29 mm | 50 x 30 mm | Sheet of 24 ]                                                 |
|                                                                                                  |
|  +--------------------------------------+   +--------------------------------------+             |
|  | [QR]  214                            |   | [QR]  213                            |             |
|  |       Polymaker PolyTerra PLA ...    |   |       Bambu Lab PETG HF Orange       |             |
|  |       [#] #2B2B2E  Lot F57           |   |       [#] #F28A1B  Lot B21           |             |
|  +--------------------------------------+   +--------------------------------------+             |
|                                                                                                  |
| The code holds this Hub's address, https://spoolwarden.local. If the Hub is renamed or moves to   |
| another port, old labels still open in the Spoolwarden app's scanner but not from a phone's camera.|
|                                                                                  [Print]         |
+--------------------------------------------------------------------------------------------------+
```

| Part | Content |
|---|---|
| Title | "Print a label" for one spool, "Print labels" for several |
| Size | Segmented choice "62 x 29 mm" (a 62 mm roll; the default), "50 x 30 mm", "Sheet of 24" (A4 or Letter, by the browser's paper). Choosing one shows the labels again at that size (`size=62x29`, `50x30` or `sheet24`) |
| Preview | The labels as they will print, in the chosen size, one per spool; the sheet shows 24 to a page |
| The printed address | One line: "The code holds this Hub's address, <address>. If the Hub is renamed or moves to another port, old labels still open in the Spoolwarden app's scanner but not from a phone's camera." |
| **Print** | Primary. Opens the browser's own print dialog; the print rules (`setup_static/setup_labels.css`) hide everything but the labels. No label printer is driven directly and no PDF is made |

| State | Text |
|---|---|
| Loading | Skeleton labels |
| Error | "Could not draw the labels. <Hub's text>" with **Try again** |
| A number the Hub does not know | "Spool <n> was not found." in its place; the other labels still show |

---

## 17. Analytics

**Purpose.** See how much filament the printers used over the last 12 months: this month in a few plain sentences, then
every month as a bar and as a table. Group Everyday, after Spools (foundations section 8); on a phone inside the More
sheet. Address `#analytics`.

**Data.** `G analytics` (view; `GET analytics`) with `months` (12 here, 1 to 13) and `printer` (the Hub's id of one
printer, or none for all) → `{months, insights, notes}` as section 15 gives them; the printers of the choice come from
`G state`. Reading needs nothing: it holds no address, serial or secret.

**Where the numbers come from.** The filament-used logs of every printer, undone entries left out. Each new entry also
stores `material`, `vendor`, `name`, `color_hex`, `printer_name` and `outcome` (`finished`, `failed`, `cancelled` or
`unknown`), because the logs did not hold them. An older entry gets its material from Spoolman while the spool still
exists and "Unknown material" otherwise; the older entries of a removed printer belong to "A removed printer". Klipper
printers keep 13 months of entries, kept by time and not by count.

### 17.1 Layout

```
Desktop
+--------------------------------------------------------------------------------------------------+
| Analytics                                                         [More actions for this page]   |
| Analytics                                                                                        |
| Last 12 months                                                                                   |
|                                                                                                  |
| +-- This month ------------------------------------------------------------------------------+   |
| | Filament used this month: 1.84 kg (last month 1.52 kg).                                    |   |
| | Your favourite material this month was PA6 (640 g).                                        |   |
| | Workshop X1 did the most work this month (1.1 kg, 23 prints).                              |   |
| | 2 of 25 prints did not finish this month (96 g).                                           |   |
| | The biggest print this month was bracket_v4.3mf (212 g).                                   |   |
| | You finished 3 spools this month.                                                          |   |
| +--------------------------------------------------------------------------------------------+   |
|                                                                                                  |
| +-- Filament used per month   Printer [All printers v]   [Show as table] --------------------+   |
| |                                                       1.84 kg                              |   |
| |                                        1.52 kg         ####                                |   |
| |    1.1 kg   0.9 kg   1.3 kg   ...       ####   1.2 kg   ####                               |   |
| |    ####     ####     ####              ####   ####      ####                               |   |
| |    Dec 2025 Jan 2026 Feb       ...     Sep    Oct       Nov (so far)                       |   |
| | Includes 38 g the Hub logged but took off no spool. 2 prints have no weight.               |   |
| +--------------------------------------------------------------------------------------------+   |
|                                                                                                  |
| +-- Materials in [Nov 2026 v] ---------------------------------------------------------------+   |
| | MATERIAL   GRAMS                                                                           |   |
| | PETG       720 g                                                                           |   |
| | PA6        640 g                                                                           |   |
| +--------------------------------------------------------------------------------------------+   |
+--------------------------------------------------------------------------------------------------+
Tablet: the same, the bars a little narrower.
Phone:  one column; the bars lie flat, one row per month (02-components.md 7.12); the tables are stacked cards.
```

### 17.2 This month

A card "This month" of plain sentences, each shown only when its numbers exist, in this order. The Hub builds them
(`insights[].text`) and the page shows them as sent:

| Key | Sentence |
|---|---|
| `total` | "Filament used this month: 1.84 kg (last month 1.52 kg)." (without the bracket when last month has no numbers) |
| `favourite_material` | "Your favourite material this month was PA6 (640 g)." |
| `busiest_printer` | "<Printer> did the most work this month (1.1 kg, 23 prints)." |
| `unfinished` | "<n> of <m> prints did not finish this month (<grams> g)." |
| `biggest_print` | "The biggest print this month was <job> (<grams> g)." |
| `spools_finished` | "You finished <n> spools this month." (1 spool: "You finished 1 spool this month.") |

When none exists the card says "No filament used this month."

### 17.3 The months

A card "Filament used per month" holds the monthly bars (`02-components.md` 7.12): one bar per month for the last 12
months, in the accent colour, the grams in words above each bar, drawn by the page as inline SVG with no chart library.

| Control | Does | Endpoint |
|---|---|---|
| **Printer** | Select "All printers", then each printer by name (and "A removed printer" when older entries of a removed printer exist); redraws the bars and both tables | `G analytics` (view) `printer` |
| **Show as table** | Opens the table under the bars, then reads **Hide the table** | |
| **Month** (above the materials table) | Select of the 12 months, this month first | |

- **The monthly table** (after **Show as table**): Month (`--mono`), Grams, Prints, Prints that did not finish, Most used
  material (`top_material`).
- **The materials table**, titled "Materials in <month>": Material, Grams, for the chosen month, the most first
  (`by_material`).
- **Honesty notes.** Under the bars, quietly, the Hub's `notes` as sent: entries the Hub logged without taking filament
  off a spool are counted and said so ("Includes <grams> g the Hub logged but took off no spool."), and entries
  without a weight are counted as prints and named ("<n> prints have no weight.").
- A print that did not finish is a stopped one: its `outcome` is `failed`, `cancelled` or `unknown` (stopped for a reason
  the printer did not tell), counted together.

### 17.4 States

| State | Text |
|---|---|
| Loading | The sentences as two skeleton lines, the bars as grey bars; screen reader "Loading the filament used." |
| Empty (no entry in 12 months) | Empty state with the spool icon: title "No filament used yet", sentence "Prints that use filament appear here." |
| One printer, no entries | The bars at "0 g" and the sentence "<Printer> used no filament in these months." |
| Error | "Could not read the usage. <Hub's text>" and **Try again** |

**Main action:** none; the section is for reading.
