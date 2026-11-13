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
14 Where today's controls went · 15 Needs from the Hub

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

Example values in this document are invented: the Hub is named "Workshop hub", version 0.5.2, at
`https://192.0.2.10:8710/setup`; printers Workshop X1 (192.0.2.40), Garage Voron (voron.example:7125) and Study
A1 mini (192.0.2.41); devices "Kitchen phone" and "Desk PC". `http://127.0.0.1:7915` is not an example but the
product's own default address of the On this Hub engine (section 10.5).

### 1.2 Addresses inside the page

The Hub page is served at `/setup`. The part after `#` names the place (foundations section 8). Every section and
every detail that can be opened has an address; reloading returns to it, Back and Forward move between them.

| Address | Opens |
|---|---|
| `#overview` (also empty or unknown) | Overview |
| `#printers` · `#printers/<id>` · `#printers/add` · `#printers/find` | Printers; one printer's row expanded and scrolled to; the Add a printer drawer; the Find Klipper printers card focused |
| `#printers/<id>/load-map` · `#printers/<id>/reports` | The Map by loading filament drawer; the Saved reports drawer. `<id>` is the Hub's key for the printer (for a Bambu Lab printer it may equal the serial), so a Klipper printer has an address too |
| `#recent` · `#recent/<id>` | Recently added; one record |
| `#devices` · `#devices/pair` · `#devices/trusted` · `#devices/tag-readers` | Devices; the pairing dialog; the Trusted computers card; the Tag Readers card |
| `#presets` · `#presets/updates` | Slicer presets; its Updates card |
| `#features` · `#features/<feature>` · `#features/setup-<mode>` | Features; the preview drawer for turning that feature on or off; the preview drawer for changing the setup |
| `#settings` · `#settings/<group>` | Settings; one group (`appearance`, `general`, `storage`, `label-reader`, `backups`, `network`, `passphrase`, `catalog`, `voice`) |
| `#flash` · `#flash/tag-reader` · `#flash/display` | Flash a device; with the device chosen |
| `#updates` · `#logs` · `#logs/<service>` | Updates; Logs; Logs with a service chosen and shown (when unlocked) |
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
| Toast | Bottom right on desktop and tablet, above the bottom bar on phone; 5 s; never the only place an error is shown | Results of actions whose control disappears (a forgotten printer, a closed dialog) |
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
       Turn on Slicer presets in Features to build filament
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
| Section data | When the section opens; when its own change succeeds (only that region) | Overview: when it opens and on **Run the checks again**. Printers: printer states every 10 s while the section is visible (`G state`). Weigh Station requests: every 5 s while Devices is visible and the page is Unlocked or Trusted. |
| `G job?from=N` | Page load; while a job runs | Every 1 s; while the Hub restarts, `G state` every 2 s instead (section 3.6) |
| Polls of a running flow | Slot mapping every 2 s, Map by loading filament every 2 s, pairing every 3 s | Until the flow ends or its expiry passes |

All timers stop while the browser tab is hidden and resume, with an immediate read, when it is shown again.

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
| [mark] Spoolwarden      [lock Locked] [half] |
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

Uses the navigation component (`nav` profile `rail` in Console) with the ten sections of foundations section 8, in
two groups separated by a hairline.

| Section | Address | Rail label | Bottom bar | Live summary (More sheet, rail tooltip) |
|---|---|---|---|---|
| Overview | `#overview` | Overview | Overview | "<n> to do" or "All checks OK" or "<n> need a look" |
| Printers | `#printers` | Printers | Printers | "<n> connected · <m> offline" |
| Recently added | `#recent` | Recently added | Recent | "Newest: spool <id>, <relative time>" |
| Devices | `#devices` | Devices | More | "<n> paired · <m> Tag Readers" |
| Slicer presets | `#presets` | Slicer presets | More | "Last build <relative time>" or "No build yet" |
| Features | `#features` | Features | More | "Setup: <setup name>" |
| Settings | `#settings` | Settings | Settings | "<n> groups" or "<group> unsaved" |
| Flash a device | `#flash` | Flash a device | More | "Tag Reader · Weigh Station display" (devices this Hub has firmware for) |
| Updates | `#updates` | Updates | More | "<installed> · up to date" or "<latest> is available" |
| Logs | `#logs` | Logs | More | "<n> services" |

- **Desktop and tablet:** the navigation rail, `--rail` wide, icon above a `--fs-xs` label; labels that do not fit
  in two lines ("Recently added", "Slicer presets", "Flash a device") break into two lines, never truncate. The
  active entry has `--accent-soft` ground, weight 600 label, the 3 px `--accent` mark at the rail's inner edge and
  `aria-current="page"`. Hover shows the live summary as a tooltip.
- **Phone:** the bottom bar with Overview, Printers, Recent, Settings, More. More opens the More sheet: the six
  other sections, each a row with icon, name, live summary and chevron; the active one has `aria-current="page"`.
  When one of those six is open, More shows the active mark and its accessible name ends ", current: <section>".
- A badge on a navigation entry shows only these: Overview a warn triangle when a check needs a look; Updates an
  info dot when a newer version is available; Settings a warn dot while a group has unsaved changes; a dimmed
  hollow circle for a section switched off.
- Live summaries come from data the page already has (`G state`, the job); the More sheet reads `G presets` and
  `G updates` when it opens if those were not read yet, showing a skeleton line until they arrive.

### 3.3 Lock chip

The lock chip of `02-components.md` section 3.1: icon, state word and, on tablet and desktop, the hint (texts in
section 2.1); on phone the icon and the word, without the hint. Its colours per state, accessible names and
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
| `update`, `rollback`, `check`, `channel_nightly`, `channel_stable` | Updates |
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
https://192.0.2.10:8710/setup. Other names can be added in Settings > Network and addresses." A change refused with
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
- Moving to another section scrolls to the top and focuses the page title (`tabindex="-1"`).
- Content is at most 1400 px wide on desktop with `--s5` gutters; `--s4` on tablet and phone.
- Cards: a title row (`--fs-l`, weight 650, optional icon, optional status badge, optional
  actions at the right), body, optional footer for the group's Save. Cards are separated by `--s4`.

---

## 4. Overview

**Purpose.** Show at a glance whether the Hub is healthy and what is still to do, with a way to each fix. It is the
page form of `spoolwarden status`. Address `#overview`.

**Data.** `G state`, `G overview` (view); when Unlocked or Trusted, `P overview` (code) instead, which returns the
same shape without hidden addresses. `G intake/history` for the Recently added tile.

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
| +- Printers ---------+ +- Recently added ----+ +- Devices ----------+ +- Label Reader ---+ |
| | 2 connected        | | Spool 214           | | 3 paired           | | 12 of 40 reads   | |
| | 1 offline          | | 3 minutes ago       | | 1 Tag Reader       | | used today       | |
| +--------------------+ +---------------------+ +--------------------+ +------------------+ |
|                                                                                            |
| +-- Checks ----------------------------------------------- [1 needs a look] [14 OK] ----+   |
| | STATUS          CHECK                                       FIX                        |   |
| | /!\ Needs a look  Spoolman is missing Spoolwarden's fields  [Make the fields]          |   |
| | (i) Note        Slicer Sync: not set up                     Link it in Devices         |   |
| | > Show 14 checks that are OK                                                           |   |
| +---------------------------------------------------------------------------------------+   |
|  Addresses and serial numbers are hidden while the page is locked.  [Unlock to show]       |
+--------------------------------------------------------------------------------------------+

Tablet: tiles in a 2 x 2 grid; the Checks table keeps Status and Check, Fix moves under the check text.
Phone:  one column; the tiles become one key-value list card; each check is a stacked card
        (badge, text, fix, action).
```

### 4.2 Cards

**Header meta line.** "Spoolwarden <version_text>" · "Setup: <setup name>" (names in section 9) · when
`update.newer`, an info status badge "<latest> is available" that links to `#updates` · at the right "Checked
<relative time>" (exact time on hover).

**Half-install banner** (warn; when `update.half_install` and no job runs): title "The last install or update
stopped halfway", body "To repair it, run this on the Hub:" and a code block with Copy holding the command the Hub
sends.

**Still to do** (only when it has items; card title "Still to do" with the count in a badge). Each item is a row:
warn triangle, one sentence, one default button.

| Shown when | Sentence | Button → place |
|---|---|---|
| `code_set` is false | "No setup code yet. On the Hub, run this to make one:" and a code block with Copy, `sudo spoolwarden setup-code` | none |
| Printer features on, no printers | "Add your first printer." | **Go to Printers** → `#printers/add` |
| No phone paired | "Pair a phone to add spools from it." | **Go to Devices** → `#devices/pair` |
| No devices and no printers | "Moving from another computer? Restore its backup." | **Restore a backup** → `#settings/backups` |
| Label Reader Cloud on, key not set | "Set the Anthropic API key, so the Label Reader can use Cloud." | **Open settings** → `#settings/label-reader` |
| Web access on, passphrase not set | "Set the web passphrase, so Claude's connector can sign in." | **Open settings** → `#settings/passphrase` |

**Summary tiles.** Four key-value tiles, each a link to its section; numbers in `--fs-2xl`.

| Tile | Value | Second line | Source |
|---|---|---|---|
| Printers | "<n> connected" with the status badge shape | "<m> offline", "<k> not configured", or "No printers yet" | `G state` `printers.list` |
| Recently added | "Spool <id>" | Relative time of the newest record, or "Nothing added yet" | `G intake/history` |
| Devices | "<n> paired" | "<m> Tag Readers" | `G state` `devices`, `readers` |
| Label Reader | "<used> of <limit>" | "Cloud reads used today" | The "reads used today" check row of `G overview` |

When the feature behind a tile is off, the tile shows "Switched off" in `--muted` and still links to its section.

**Checks** (a collection of the Hub's `rows`, `table` profile in Console).

| Column | Content | Priority |
|---|---|---|
| Status | Status badge: `ok` → "OK"; `fail` → "Needs a look"; `info` and anything else → "Note" | P1 |
| Check | The row's `text`. A `detail` row has no badge and sits indented under the row before it, in `--muted`. | P1 |
| Fix | The row's `fix` (a command shows as a code block with Copy), or the row's action button | P2 (under the check text on phone and tablet) |

- Order: Needs a look first, then Note, then OK; within each, the Hub's order. OK rows are folded under a disclosure
  "Show <n> checks that are OK" (open by default when nothing needs a look). The card title row carries two badges
  with the counts ("1 needs a look", "14 OK").
- Row action `ensure_fields`: primary button **Make the fields** (code) → `P fields`, the page's main action while
  its check needs a look (4.3); inline result "Made the fields: <made>." or, when `made` is 0, "The fields were
  already there." It is the only row action.
- Card action (title row, ghost button with refresh icon): **Run the checks again** → reads the rows again.

**Hidden addresses.** When the reply says `redacted: true` (Locked): a quiet line under the Checks card "Addresses
and serial numbers are hidden while the page is locked." and a default button **Unlock to show**. Once Unlocked or
Trusted, the page reads `P overview` by itself and the line goes.

### 4.3 States

| State | Text |
|---|---|
| Loading | Tiles and five check rows as loading skeleton; screen reader "Checking the Hub." |
| Error | Error state in the Checks card: "Could not check the Hub. <Hub's text>" and **Try again** |
| Nothing to do, all OK | No Still to do card; the Checks card title badge reads "OK" and the first line of the card "Everything checked out." |
| Job running | The meta line adds "<job title> is running" with a link that opens the job strip |

**Main action:** none permanent. When a check needs a look and has an action, that action is the page's one primary
button. **Run the checks again** is a ghost button.

---

## 5. Printers

**Purpose.** See every printer's state and slots; add, test and set up printers, and keep them working. Two
families: Bambu Lab (feature "Bambu Lab printers", code name `printers`) and Klipper (feature "Klipper printers",
`klipper`). Address `#printers`.

**Data.** `G state` (`printers: {on, bambu, klipper, list}`); the per-printer calls listed with each control.

**Switched off** (neither feature on): section 2.5 with title "Printers are switched off" and sentence "Turn on Bambu
Lab printers or Klipper printers in Features to connect printers." The button opens `#features`.

### 5.1 Layout

```
Desktop
+----------------------------------------------------------------------------------------------------+
| Printers                                                                                           |
| Printers               [camera Open the live printer view] [Find Klipper printers] [+ Add a printer] |
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
        Header actions: [+ Add a printer] full width, then Find Klipper printers and the live view link
        as ghost buttons in one row.
```

### 5.2 Printer collection

`collection` profile `table` in Console; one row per printer, then a group "Found on the network, not added yet" for
Klipper printers a scan found that are not configured (`configured: false`).

| Column | Content | Priority |
|---|---|---|
| Expand | Icon button with chevron, "Details for <name>", `aria-expanded`, `aria-controls` | P1 (on phone a ghost button "Details" at the card's foot) |
| Printer (sortable) | Name in weight 600; under it the model in `--muted`. When both families are on, a tag "Bambu Lab" or "Klipper" after the name. | P1 |
| Address (sortable) | `ip` (Bambu Lab) or `host:port` (Klipper) in `--mono`, or "No address yet" in `--muted`; under it "SN <serial>" (Bambu Lab) or "Moonraker" (Klipper). Hidden values read "Hidden while locked". | P3 |
| State (sortable) | Status badge from `state`: `connected` → "Connected"; `offline` → "Offline"; `not_configured` → "Not configured"; any other value → "Needs a look" (triangle) followed by the state's sentence (the value with underscores as spaces) | P1 |
| Slots | Slot strip of filament swatches with fill level and "<loaded>/<total> loaded"; or "No slot data while offline"; or "No slots read yet" | P1 |
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
| Slots | Title "AMS slots". One line per slot: slot name (`--mono`), filament swatch, filament name, colour name, hex in `--mono` `--muted`, fill bar and percentage. An empty slot: hollow swatch and "Empty". | Title "Tool slots", same lines |
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
| **Open the live printer view** | Ghost link with camera icon (header; Bambu Lab on) | Opens the web app's printers page in a new tab: `<base>/intake#printers` | |
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

Side drawer on desktop (420 px), full-height dialog on tablet, bottom sheet on phone. Address `#printers/add`. Title
"Add a printer".

| Field | Type | Shown | Sent as |
|---|---|---|---|
| Printer type | Segmented choice "Bambu Lab" / "Klipper" | Only when both families are on; kept while the drawer is open | |
| IP address or name | Text, `--mono`, placeholder `192.0.2.40 or printer.local` | Bambu Lab | `address` |
| Access Code | Secret field with show/hide; hint "On the printer: Settings > Network/LAN." | Bambu Lab | `access_code` |
| Name (optional) | Text | Both | `name` |
| Serial (optional) | Text, `--mono`, upper case; hint "Read from the printer when left empty." | Bambu Lab | `serial` |
| Address | Text, `--mono`, placeholder `voron.example` | Klipper | `host` |
| Port | Number, `--mono`, default 7125 | Klipper | `port` |
| Moonraker API key (optional) | Secret field | Klipper | `api_key` |

Main action **Add printer** (primary, drawer foot) → `P printers` (Bambu Lab) or `P printers/klipper` (code).
Cancel (default) closes; with typed values it asks "Leave without saving?" (section 2.6).

| Result | What shows |
|---|---|
| Success | The drawer closes; toast "Added <name>."; the new row is expanded with the message "Added. Test the connection next." and its Test connection button focused. A `note` from the Hub joins the message. |
| "names itself <A>, not <B>" | At the address field: "The printer at <ip> calls itself <A>, not <B>. Check the address." |
| Serial cannot be read | At the serial field: "Spoolwarden could not read the serial. Type it in: on the printer, Settings > Device." |
| Bad address | At the address field: the Hub's text, which ends "On the printer: Settings > Network." |
| Other refusal | Above the drawer's buttons, the Hub's text |

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
| Only one family on | The other family's tool card, tag and type choice are absent; one quiet line at the page foot: "Klipper printers are switched off. Turn them on in Features." (or "Bambu Lab printers are switched off. …"), with Features as a link |
| Locked | Addresses and serials read "Hidden while locked"; every change asks for the code in place |
| Row busy | The busy button shows an inline spinner and its working label ("Testing…", "Mapping…"); the row's other buttons stay usable |

**Main action:** Add a printer. Per row: Test connection (default), with Map slots or Detect model and slots as the
expansion's primary; a problem line's Collect a report outranks both.

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
- Filter (segmented choice, header actions): "All <n>" / "To check <m>", where To check means medium or low
  confidence on any field. Shown only when the Hub sends confidence.
- More than 50 records: paged, 50 per page, with "Newer" / "Older" at the foot.

### 6.3 Record

| Card | Content |
|---|---|
| Header | Breadcrumb with the list as link; title "<vendor> <name>" (x<n>), or "No spools" for a record with no spools (its photos, fields and revisions still show; a change the Hub refuses because the spools are gone shows the Hub's text at the Save or Accept button); meta: time, source, state badge, spools. Actions: ghost **Back** (to `#recent`), icon buttons "Newer record" and "Older record" (disabled at the ends) |
| Item choice | Only when the record has several items: segmented choice "Item 1", "Item 2", … with the line "Spools <ids> (filament <id>). Changes apply to all of them." |
| Photos | Photo thumbnails (96 px); pressing one opens the photo viewer (full width, Left and Right between photos, Escape closes, "Photo <n> of <m>"). No photo: "No photo was taken for this addition." |
| Fields | Key-value list in four groups. Identity: Brand, Name, Material, Colour (filament swatch and hex). Weights: Net weight (g), Empty spool weight (g), Density (g/cm³). Temperatures: Nozzle (°C), Bed (°C), Nozzle range (°C), Bed range (°C). Other: Price per kg, Line. Empty values read "(empty)" in `--muted`. Per-field confidence display next to the value when it is not high. Card action: default **Edit by hand**. |
| Fields, editing | The values become fields (text; numbers with unit). Foot: inline result, default **Cancel**, primary **Save changes**. Only changed fields are sent: `P intake/history/<id>/apply` (code) `{item, values}`. |
| Ask the Label Reader to correct it | Text area "What is wrong?", placeholder "e.g. brand is Polymaker", hint "The Label Reader reads the photos again with your note and suggests changes. Nothing changes until you accept." Default button **Ask the Label Reader** → `P intake/history/<id>/revise` (code) `{item, note}` |
| Suggestion | Change list (before → after per field), title "The Label Reader (<engine>) suggests <n> changes" or "The Label Reader changed nothing."; when no photo was kept: "No photo was kept for this record: it worked from the saved values and your note." Primary **Accept** → `P intake/history/<id>/apply` (code) `{proposal}`; default **Discard** (nothing is sent) |
| Revisions | Revision list, newest first: "Revision <n>, <time>, by hand / by the Label Reader: <field old → new; …>", the note when there was one, "Filament <ids> has no spools left (not deleted)" when it applies; an undone revision is struck through and ends with "(undone)" (no badge). The newest live revision has default **Undo revision <n>** → `P intake/history/<id>/undo` (code) `{revision}`. Empty: "No revisions. Corrections by hand or by the Label Reader appear here." |
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

| State | Text |
|---|---|
| Loading | Five skeleton rows; record: skeleton photos and field groups |
| Empty | Empty state with spool icon: "Nothing added yet" / "No spool has been added since the history started. Spools added from the web app, the app or the Weigh Station appear here." |
| Record not found (deep link to an old id) | Error state "This record is no longer kept. Only the newest <keep> are." with **Back to Recently added** |
| Label Reader off (`ai: false`) | The Ask card shows the off state: "The Label Reader is switched off, so corrections are by hand." with link **Features**; Edit by hand works |
| Locked | Edit by hand, Ask, Accept and Undo ask for the code in place |
| Error | "Could not read the additions. <Hub's text>" + **Try again** |

**Main action:** none in the list (it is for reading); in a record, **Save changes** while editing, **Accept** while
a suggestion is shown, otherwise **Edit by hand** is a default button and there is no primary.

---

## 7. Devices

**Purpose.** Everything that connects to the Hub: phones and the app, Slicer Sync, the Weigh Station, Tag Readers,
and trusted computers. Address `#devices`.

**Data.** `G state` (`devices`, `readers`, `station`), `G webapp`, `G trust`; when Unlocked or Trusted also `P
stations/requests` and `P trust/list`.

### 7.1 Layout

```
Desktop
+--------------------------------------------------------------------------------------------------+
| Devices                                                     [Link Slicer Sync ...] [+ Pair a phone] |
| 3 paired · 1 Tag Reader · 1 trusted computer                                                      |
| +-- Paired devices ---------------------------------------------------------------------------+ |
| |  DEVICE                PAIRED              LAST SEEN                                         | |
| |  Kitchen phone         2026-11-02 18:20    2026-11-12 14:05                      [Unpair]    | |
| |  This Hub's web app    (built in)          2026-11-12 14:06                                  | |
| +---------------------------------------------------------------------------------------------+ |
| +-- Weigh Stations asking to pair ------+ +-- The web app on a phone ---------------------------+ |
| | No Weigh Station is asking to pair.   | | At home: https://192.0.2.10:8710/intake  [QR]      | |
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
| Device | `name`; built-in pairings show a tag "Built in" and the line "This Hub's own pairing" in `--muted` | P1 |
| Paired | `paired` as `YYYY-MM-DD HH:MM`, or "Unknown" | P2 |
| Last seen | `last_seen`, or "Never" | P1 |
| Action | Ghost **Unpair** (not on built-in rows) | P1 |

Header actions: primary **Pair a phone**; default **Link Slicer Sync**; overflow menu with **Link a Weigh Station** and,
when the Weigh Station feature is on, **Pair the Weigh Station on this Hub**.

| Control | Does | Endpoint |
|---|---|---|
| **Pair a phone** | Opens the pairing dialog for a phone | `P pair` (code) `{kind: "phone"}` |
| **Link Slicer Sync** | Opens the pairing dialog for Slicer Sync | `P pair` (code) `{kind: "pc"}` |
| **Link a Weigh Station** | Opens the pairing dialog for a Weigh Station on another computer | `P pair` (code) `{kind: "station"}` |
| **Pair the Weigh Station on this Hub** | Starts pairing of the Hub's own Weigh Station; job strip follows | `P pair` (code) `{kind: "station"}`, then job `station_pair` |
| **Unpair** | Confirm dialog | `P devices/<id>/revoke` (code) |

**Pairing dialog** (dialog on desktop and tablet, bottom sheet on phone; address `#devices/pair`). Polls `G state`
every 3 s until a new device appears or the time runs out.

| Part | Phone | Slicer Sync | Weigh Station |
|---|---|---|---|
| Title | "Pair a phone" | "Link Slicer Sync" | "Link a Weigh Station" |
| Instruction | "Open the Spoolwarden app or the web app and scan this code, or type the pairing code." | "Paste this link into Slicer Sync when it asks for it." | "On the Weigh Station computer, run `sudo spoolwarden weigh-station pair`, then paste this link." |
| Main content | QR block (alt "QR code for pairing a phone", white quiet zone); when the Hub has no QR maker (`qr_svg` null), the link as a code block with Copy instead | The link as a code block with Copy | Code block with Copy for the command, then the link as a code block with Copy |
| Code | "Pairing code" and the code in `--mono` `--fs-2xl`, grouped for reading | same | same |
| Fingerprint | "Certificate fingerprint: the phone asks for two groups of it." and the groups of four in `--mono` | "Certificate fingerprint: check it matches." and the groups | same as Slicer Sync |
| Time | Determinate bar counting down and "Expires in <n> min" | same | same |
| Waiting | Inline spinner "Waiting for the device…" | same | same |
| Done | OK result "Paired: <name>." The bar and code go; button **Done** (primary) | same | same |
| Expired | Warn result "The pairing code expired. Make a new one." with primary **Make a new code**, which sends the same `P pair` (code) `{kind}` again and shows the new code | same | same |
| Buttons | Cancel (closes; the code simply expires) | | |

### 7.3 Weigh Stations asking to pair

A Weigh Station on another computer asks from its own screen; the list refreshes every 5 s while the section is
visible and the page is Unlocked or Trusted.

| State | Content |
|---|---|
| Locked | "A Weigh Station on another computer asks from its own screen. Requests are shown once the page is unlocked." and default **Unlock to show** |
| None | "No Weigh Station is asking to pair." |
| Request (one row each) | "<name> at <address> asks to pair. Its screen shows <ddd ddd>." (digits in `--mono` `--fs-l`); hint "Pair only if the Weigh Station shows the same six digits. If not, refuse it: someone else asked." Primary **Pair** → `P stations/requests/<id>/pair` (code), result "Paired <name>. It picks up its pairing within a few seconds."; default **Refuse** → `P stations/requests/<id>/refuse` (code), result "Refused <name>." |

### 7.4 The web app on a phone

From `G webapp` → `{url, qr_svg, public_url, public_qr_svg}`.

| Part | Content |
|---|---|
| At home | "At home, open this address in the phone's browser:" the `url` in `--mono` with Copy, and its QR block (alt "QR code of the web app's home address") |
| Hint | "The browser warns once about the Hub's own certificate: accept it to go on. This address works on the home network only." |
| Away from home (only with `public_url`) | "Away from home too:" the `public_url` with Copy and its QR block (alt "QR code of the web app's public address") |
| Keep it | "To keep it on an iPhone: tap Share, then Add to Home Screen." |
| Error | "Could not read the web app's address. <Hub's text>" + **Try again** |

### 7.5 Tag Readers

Code name: reader tokens (`readers`). A Tag Reader needs a token to reach the Hub; Flash a device makes one by
itself, so this card is for readers built by hand.

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

**Main action:** Pair a phone.

---

## 8. Slicer presets

**Purpose.** Filament presets built for Bambu Studio and Orca Slicer from the Filament Catalog and the spools, the
state of Slicer Sync on the PC, and updates waiting to be accepted. Address `#presets`. Code name `presets`.

**Data.** `G presets` (view) → `{on, lines, lines_error, build, presets, orca_presets, last_attempt, installed, pc,
waiting_text, updates, stale, orca_stale, problems}`.

**Switched off:** section 2.5, title "Slicer presets are switched off", sentence "Turn on Slicer presets in Features
to build filament presets for Bambu Studio and Orca Slicer."

### 8.1 Layout

```
Desktop
+--------------------------------------------------------------------------------------------------+
| Slicer presets                                                                     [Build now]   |
| Last build 2026-11-12 03:12 · 46 presets, 12 for Orca Slicer · (*) Slicer Sync reported in        |
| +-- Build ---------------------------------------------+ +-- Updates -------------------------+  |
| | Last build 2026-11-12 03:12: 46 presets, 12 for Orca  | | 3 updates on 2 lines.               |  |
| | Slicer, 0 problems.                                   | | Presets already in your slicers are |  |
| | (*) Slicer Sync has reported in.                      | | never replaced unless you accept.   |  |
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
| Summary | "Last build <stamp>: <n> presets, <m> for Orca Slicer, <k> problems." or "No build yet." |
| Last attempt failed | Error line: "The last build failed: <error>" |
| Waiting | Note line with `waiting_text` |
| Slicer Sync | Status badge "OK" with "Slicer Sync has reported in.", or "Not configured" (Note) with "Slicer Sync is not set up. Link it in Devices." (link to `#devices`) |
| Problems | List of `problems` as error lines |
| Delete by hand | Lines "Delete by hand in Bambu Studio: <name>" / "Delete by hand in Orca Slicer: <name>" for `stale` / `orca_stale`, under the sub-title "Old presets to delete by hand" |
| **Build now** | Primary (section header) → `P presets/build` (code); inline result "A build was asked for. It runs in a moment." |
| **Bring back deleted presets** | Ghost → `P presets/restore_deleted` (code); inline result "The next build brings back the presets deleted in Bambu Studio. A build was asked for." |

**Updates** (address `#presets/updates`).

| Part | Content |
|---|---|
| Summary | "<n> updates on <m> lines<, <a> accepted: Slicer Sync writes them next>. Presets already in your slicers are never replaced unless you accept here." or "No updates. Presets already in your slicers are never replaced on their own." |
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
| +-- Features -------------------------------------------------------- [On 9 | Off 5 | All] ----+ |
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
| Afterwards | "On afterwards:" and the list of feature names, or "Nothing" |
| Settings it needs | One labelled field per `needs` item: the label from the item's `prompt` (for example "Public https address of the web app", placeholder `https://hub.example/filament`); required |
| Refused | Error banner with the Hub's `refused` text, rewritten when it matches: "This page belongs to the Hub service. To switch it off, run on the Hub: `sudo spoolwarden features off hub`." Apply is then absent. |
| Loading | Skeleton lines, screen reader "Reading what changes." |
| Buttons | Cancel · **Apply** (primary) → `P modules/mode` (code) `{mode, settings}` or `P modules` (code) `{name, on, settings}` |
| Result | Reply `changed: true`: the drawer closes, toast "Saved; applying… Follow it in the job panel.", the job strip follows job `apply`. `changed: false`: inline "Nothing to change." and the drawer stays. |

**Main action:** none permanent; Apply in the drawer.

### 9.5 States

| State | Text |
|---|---|
| Loading | Three skeleton choice cards, six skeleton rows |
| Job running (`apply`) | Every Turn on / Turn off and the setup cards are disabled with tooltip "Wait for the current change to finish."; a banner "Applying the changes… Follow it in the job panel." |
| Hub service row | Its button is absent; the row reads "Always on while this page is open." |

---

## 10. Settings

**Purpose.** Everything about how the Hub behaves, in nine groups, each with at most one Save. Address `#settings`;
one group `#settings/<group>`.

**Data.** `G settings/general` (view) → `{values, station_on, remote_on, web_on, spoolman_external, intake_history,
spoolman_url}`; `G state` (`anthropic`, `passphrase`, `library_token`, `web`, `station`); `G library`; when
Unlocked or Trusted, `P backups/list`. Each group reads only its own data again after its own save.

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
| | Label Reader             | +------------------------------------------------------------------+ |
| | Backups and restore      | +-- Storage locations ---------------------------------------------+ |
| | Network and addresses    | | ...                                                              | |
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
- Group order is fixed: Appearance, General, Storage locations, Label Reader, Backups and restore, Network and
  addresses, Web passphrase, Filament Catalog, Weigh Station voice.
- Each group is a form group card: icon, title, one-line description, optional status badge at the right, the
  fields as label-and-control rows (label left 200 px on desktop, above the control on tablet and phone), a foot
  with the inline result at the left and the group's Save at the right.
- Phone list of groups, one-line states: Appearance "<Light/Dark/System> · <theme>"; General "<display name>";
  Storage locations "<n> locations"; Label Reader "<engine order in words>"; Backups and restore "Last: <time>" or
  "Unlock to show"; Network and addresses "<public address>" or "No public address"; Web passphrase "Set" / "Not
  set"; Filament Catalog "<version>" or "Not downloaded"; Weigh Station voice "<Piper / espeak-ng>" or "Switched off".

### 10.2 Appearance

Description: "How this page looks on this device." Per device; needs no setup code, except the last field.

| Field | Type | Does | Stored / endpoint |
|---|---|---|---|
| Light, dark or system | Appearance control (segmented choice with icons), hint "System follows this device's light or dark setting." | Applies at once | `localStorage` `spoolwarden.appearance` (foundations section 5) |
| Theme | Theme picker: four preview tiles Console "Dense and technical", Workbench "Calm cards", Spool "Colourful and roomy", Panes "Simple lists"; the current one checked | Applies at once, no reload | `localStorage` `spoolwarden.look` (foundations section 6.2) |
| Theme for new devices | Select of the four themes, hint "Used by browsers and phones that have not chosen a theme." | Saved with the group's Save | Section 15 (no endpoint yet) |

Save: **Save theme for new devices** (only this field needs it; the button is enabled only while it changed).
Inline result for the two device fields: none (the change is the feedback); screen reader "Theme: <name>."

### 10.3 General

Description: "The Hub's name and its Spoolman database."

| Field | Type | Key / endpoint | Notes |
|---|---|---|---|
| Display name | Text | `server_name` → `P settings/general` (code) | Shown in the top bar and the document title. Required: "Enter a name for the Hub." |
| Spoolman address | Text, `--mono`, placeholder `http://spoolman.example:7912`; only when Spoolman runs on another machine (`spoolman_external`) | `P settings/spoolman` (code) `{url}` | Shows the address in use (hidden parts as the Hub sends them). Hint "A new address must answer as Spoolman before it is saved. Spoolwarden then uses that database for everything." Saved by the group's Save, after the other field; the Hub checks it first, the field shows "Checking that Spoolman answers…" meanwhile. Refusal at the field: "Nothing was changed: no Spoolman answered at that address (<why>)." Success applies in the background (job `apply`). |

Save: **Save general**.

### 10.4 Storage locations

Description: "Where spools are put away. Used when a spool is added."

| Field | Type | Key | Notes |
|---|---|---|---|
| Locations | Text, hint "Separate them with commas, e.g. Shelf A, Shelf B, Dry box 1." | `locations` (sent as a list) | |
| PLA rack | Text | `placement.pla_location` | Hint "Where PLA goes." |
| Box location prefix | Text | `placement.box_prefix` | Hint "Boxes are named with this and a number, e.g. Dry box 1." |
| Number of storage boxes | Number, `--mono` | `placement.box_count` | Field error "Enter a whole number, e.g. 2." |
| Overflow location | Text | `placement.overflow` | Hint "Where spools go when the boxes are full." |

All → `P settings/general` (code), one key each (section 2.2). Save: **Save storage locations**.

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
| Address | Text, `--mono`, default `http://127.0.0.1:7915` | `local_intake.url` (unreleased) | On this Hub on | Hint "Where the reader answers: this Hub, or another computer at home." |
| **Test** | Default button beside Address | `G settings/local-intake` (view, unreleased): the reader's health at the saved address | On this Hub on | Inline spinner "Asking the reader…"; OK "Answers: version <v>, API <n>, tiers <list>, corrections <supported / not supported>."; warn "Answers, but degraded: <reason>."; error "No answer at <address>. Check that the reader is running and the address." The Hub tests the saved address, so while the Address field holds an unsaved change, Test is disabled with the reason "Save the address first, then test it." A 409 (On this Hub switched off) shows "Label Reader: On this Hub is switched off. Turn it on in Features." |
| Tier | Segmented choice "Automatic" / "Processor (CPU)" / "Graphics card (GPU)" | `local_intake.tier` (unreleased; `auto` / `cpu` / `gpu`) | On this Hub on | Hint "Automatic uses the graphics card when the reader has one." |
| Records kept | Number | `intake.history_keep` | Always | Hint "How many of the newest additions Recently added keeps with their photos (0 keeps none). Now <count> records, <size> of photos; a record with photos takes about 0.5 to 2 MB." Field error "Enter a whole number from 0 to 500." |

Fields are sent in this order: Engine order, Address, Tier, Records kept, Anthropic API key, Claude model, Reads per
day, so the two that restart the Hub go last. When either of the last two is among the changes, Save opens a
confirm first (10.11). Save: **Save Label Reader**.

### 10.6 Backups and restore

Description: "One zip with everything Spoolwarden keeps." Title row: "Nightly backup" followed by the status badge "On" /
"Off" (the Nightly backup feature).

| Part | Content |
|---|---|
| Warning (banner, warn) | "The zip is not encrypted and holds the setup secrets (the keys, Access Codes and certificate). Store it somewhere safe." |
| **Back up now** | Primary → job `backup` (code); inline result "Backing up… follow it in the job panel." then "Backup: done. It is at the top of the list." |
| Backups on the Hub | Collection, loaded by itself when Unlocked or Trusted (`P backups/list` (code)). Columns Made (`at`, `--mono`) P1; Kind ("Nightly", "Before a restore", "Made here") P2; Size ("<n> KiB") P2; ghost **Download** P1 → `P backups/download` (code), inline spinner "Preparing the zip…", then the browser saves the file. Empty: "No backups in <folder> yet." Locked: "The list is shown once the page is unlocked." and **Unlock to show** |
| Keep nightly backups for | Number with unit "days" (1 to 365), hint "Backups made here are kept until you delete them." → `P backups/keep` (code) `{days}`, by the group's Save; result "Nightly backups are kept for <n> days." |
| Restore (step progress, three steps) | 1 "Choose a backup zip": file field (accept `.zip`), label "Backup zip". 2 "Upload and check": default **Upload and check** (enabled once a file is chosen) → raw `P restore/upload` with the code in the `X-Setup-Code` header; inline spinner "Uploading and checking…" with a determinate bar of the upload. 3 "Restore": the check summary and danger **Restore…** (opens the typed-word confirm), ghost **Discard the upload** → `P restore/forget` (code) |
| Check summary (key-value list) | "Backup of <host or "another Hub"> made <created> by Spoolwarden <version>"; "Contains <n> files<, and the Spoolman database>"; "Features: <list or "none">"; when `replaces_data`, a warn line "This replaces the spools, settings, printers and pairings on this Hub. What is here now is saved as a backup first."; the other-host note as Note; "Afterwards the setup code is the one from the backup."; "Checked copy: SHA-256 <hash>. Only this copy is restored." (`--mono`) |
| Upload errors | No file: at the field "Choose the backup zip first." Too large: "The backup is larger than this page can take. Copy it to the Hub and run `sudo spoolwarden restore <file>` there." (code block with Copy). Other: the Hub's text. |

Save: **Save backup settings** (only Keep nightly backups for). Back up now and Restore are actions, not saves.

### 10.7 Network and addresses

Description: "How the Hub is reached from the web, by the Weigh Station, and by name."

| Field | Type | Key / endpoint | Shown | Notes |
|---|---|---|---|---|
| Public address | Text, `--mono`, placeholder `https://hub.example/filament` | `web.public_url` → `P settings` (code) `{key, value}` | Always; hint differs when Web access is off | Hint "The https address of the web app and Claude's connector." Off: "Used when Web access is on." Applies in the background (job `apply`). |
| Weigh Station address | Text, `--mono`, placeholder `http://station.local:5003` | `station.url` → `P settings` (code) | Always | Hint "Where this Hub reads a Weigh Station on another computer. Leave empty for none." Applies in the background. |
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
Catalog is switched off." with **Go to Features**; the token field stays.

| Part | Content |
|---|---|
| State | "Version <v> (<source>), <n> entries of your own." or "The catalog is not downloaded yet."; "Last check <at>: OK." / "Last check <at>: <error>" (warn) / "Last check: never."; `skipped` as a Note line |
| **Update now** | Default → job `library_update` (code) |
| **Go back to the version before** | Ghost → confirm, job `library_rollback` (code) |
| Catalog token | Secret field "Catalog token (optional)", hint "Lets the Filament Catalog download from a private repository, for example a GitHub token." Status badge "Set" / "Not set" beside the label; ghost danger **Remove token** when set → confirm, `P library_token/remove` (code). A new token is sent by the group's Save → `P library_token` (code). |
| Add your own entry | Text area `--mono`, 4 rows, label "Add your own entry", placeholder `{"brand": "…", "name": "…", "material": "PLA"}`, hint "One entry as JSON. It is checked like `spoolwarden catalog add` checks it, and a preset build follows." Default **Add entry** → `P library/add` (code) `{entry}`; result "Added <vendor> <product>." Errors at the field: "This is not valid JSON: check the brackets, quotes and commas." (checked in the page), or "Entry not added: <reason>." |

Save: **Save Catalog token** (only the token field). Update now, Go back and Add entry are actions.

### 10.10 Weigh Station voice

Description: "The voice the Weigh Station speaks with." Shown when the Weigh Station feature is on; otherwise the off
state "The Weigh Station is switched off on this machine." with **Go to Features**.

| Field | Type | Key | Notes |
|---|---|---|---|
| Voice | Two choice cards: "Piper" with "Natural. A 60 to 80 MB download." (`auto`) and "espeak-ng" with "Robotic. No download." (`espeak`) | `station.tts` → `P settings/general` (code) | Applies on choosing (job `apply`); result "Saved: Piper. The Weigh Station downloads it next time it is idle." or "Saved: espeak-ng." A cancelled unlock puts the choice back. |

No Save button.

### 10.11 Dialogs

| Dialog | Title | Body | Buttons |
|---|---|---|---|
| Save restarts the Hub | "Restart the Hub to save?" | "A new Claude model or number of reads per day takes effect after a restart. The Hub restarts now and this page comes back by itself." | Cancel · **Save and restart** (primary) |
| Remove Anthropic API key | "Remove the Anthropic API key?" | "Label Reader: Cloud (Claude) stops reading labels until a new key is set." | Cancel · **Remove key** (danger) |
| Remove Catalog token | "Remove the Catalog token?" | "The Filament Catalog can then download only from public sources." | Cancel · **Remove token** (danger) |
| Catalog go back | "Go back to the previous Filament Catalog?" | "The version before the last update comes back. Your own entries are kept." | Cancel · **Go back** (danger) |
| Get the certificate | "Get the certificate now?" | "Port 80 on your router must reach this Hub while it runs. Spoolwarden never changes your firewall or router." | Cancel · **Get the certificate** (primary) |
| Restore (typed word) | "Restore this backup?" | The check summary in short ("Backup of <host> made <created>"), then "This replaces the spools, settings, printers and pairings on this Hub. What is here now is saved as a backup first. The Hub restarts, and afterwards the setup code is the one from the backup." Field "Type restore to go on" (`--mono`, placeholder `restore`) | Cancel · **Restore** (danger, enabled only when the field reads `restore`) → `P job` (code) `{name: "restore", confirm: "restore", sha256: <the checked copy's SHA-256>}` |
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

**Main action:** each group's Save is that group's one primary button; Back up now is the primary of Backups and
restore, so its Save button is a default button.

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
| **Connect and write** | Primary | This computer | Asks for the code if Locked, then (Tag Reader) `P flash/provision` (code) for a token the page never shows; then the browser's port picker; then writes `G firmware/<id>.bin` at 0x0, restarts the board, finds it again, sends the settings and waits up to 60 s for the reader's own report. Any failure revokes the new token (`P readers/<id>/revoke`). |
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

**Purpose.** See the installed version, update, follow nightly builds, roll back. Address `#updates`.

**Data.** `G updates` (view) → `{installed, latest, newer, checked_at, half_install, installed_text, channel, notes,
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
| +-- Roll back ----------------------------------+ +-- Nightly builds ----------------------------+ |
| | Goes back to 0.5.1, the version this one      | | [ ] Follow nightly builds                     | |
| | replaced. Settings and data stay.             | | Off: only signed releases are installed.      | |
| | [Roll back to 0.5.1]                          | | Nightly builds are untested and unsigned.     | |
| +-----------------------------------------------+ +----------------------------------------------+ |
|  To remove Spoolwarden: on the Hub, run sudo spoolwarden uninstall.                               |
+--------------------------------------------------------------------------------------------------+
Tablet: two columns become one; Version, release notes, Roll back, Nightly builds.
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

| Control | Type | Does | Endpoint |
|---|---|---|---|
| **Check now** | Default (header) | Job | job `check` (code) |
| **Update to <latest>** | Primary (header), only when `newer`; disabled with the refusal as tooltip when `update_refused` | Confirm, then job | job `update` (code) |

**What <latest> brings** (when `newer` and `notes`) or **Release notes of <latest>** (when not newer and `notes`):
the notes as text with line breaks kept, at most 72 characters a line, in a box that scrolls inside past 24rem.

**Nightly builds.** Toggle "Follow nightly builds" showing what the Hub does now (`channel`). Changing it never
flips by itself: it opens the confirm, and the job changes the channel; the toggle follows the Hub afterwards. Text
under it: "On: <installed> is installed, and each new nightly build after it. Nightly builds are untested and
unsigned." or "Off: only signed releases are installed. Nightly builds are untested and unsigned." Shown only when
`G updates` reports a `channel`.

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
| Follow nightly builds | "Follow nightly builds?" | "Nightly builds are untested and unsigned: Spoolwarden checks a download only against the nightly's own checksum list, which proves nothing about who built it. The newest nightly build is installed now, and each new one after it. Turn this off to go back to signed releases." | Cancel · **Follow nightly builds** (danger) |
| Stop following | "Go back to signed releases?" | "The latest signed release replaces the nightly build now." | Cancel · **Use signed releases** (primary) |

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

**Purpose.** Read the end of a service's log on the Hub. Logs hold addresses and serial numbers, so reading them
needs the setup code. Address `#logs`; `#logs/<service>` shows that service once Unlocked.

**Data.** `G logs/units` (view) → `{units}`; `P logs` (code) `{unit, lines}` → `{unit, text, truncated}`.

### 13.1 Layout

```
Desktop
+--------------------------------------------------------------------------------------------------+
| Logs                                                                                             |
| Service [spoolwarden.service     v]   Lines [50 | 100 | 200]   [Show]                             |
| +----------------------------------------------------------------------------------- [Copy] ---+ |
| | 2026-11-12 03:00:02  backup   nightly backup started                                         | |
| | 2026-11-12 03:00:09  backup   done · 4,812 KiB                                               | |
| +----------------------------------------------------------------------------------------------+ |
| Only the end is shown: the rest is too long for this page.                                       |
+--------------------------------------------------------------------------------------------------+
Tablet: the same; the controls wrap onto two lines.
Phone:  controls stacked full width; the log's code block scrolls sideways inside itself, lines are not wrapped.
```

### 13.2 Controls

| Control | Type | Does | Endpoint |
|---|---|---|---|
| Service | Select of the unit names (shown as sent, `--mono`) | Chooses the log; when Unlocked, changing it shows the new log at once | |
| Lines | Segmented choice "50" / "100" (default) / "200", label "Lines" | As above | |
| **Show** | Primary | Reads the log; inline spinner "Reading…"; afterwards it reads **Show again** | `P logs` (code) |
| **Copy** | Ghost in the log's code block | Copies the log text | |

The log is a code block (`02-components.md` section 7.7; `--code` ground, `--mono`, max 64 KiB and 200 lines from the Hub).

### 13.3 States

| State | Text |
|---|---|
| Loading units | Skeleton select |
| No services | Empty state "No services are switched on." |
| Locked | Above the controls: "Logs hold addresses and serial numbers, so reading them needs the setup code." Show reads "Unlock and show" and asks for the code first |
| Empty log | "Nothing logged." in the log's code block |
| Truncated | Under the box: "Only the end is shown: the rest is too long for this page." |
| Error | Error state in the log's code block with the Hub's text and **Try again** |

**Main action:** Show.

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
| Tab nav "Console sections" (9 tabs) | Renamed | Navigation rail / bottom bar with ten sections (3.2) |
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
| Card "Live printer view" + link | Moved to | Header ghost link **Open the live printer view** (5.4) |
| Card "Add a printer": Type select, Bambu and Klipper fields, **Add** | Moved to | Add a printer drawer, **Add printer** (5.6) |
| Add errors (names itself, serial, bad address) | Kept | Field errors (5.6) |
| Card "Find Klipper printers": text, subnet field, **Scan**, results, limits | Kept | Find Klipper printers card (5.4, 5.8) |
| Card "Printer pack": text, **Show the commands**, "Checking the signed release…", commands + **Copy**, 409 | Renamed | Card "Klipper add-on" (5.4, 5.8) |

### 14.5 Devices

| Today | Fate | New place and reason |
|---|---|---|
| Card "Phones, PC and station" | Renamed | Card "Paired devices" (7.2) |
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
| Home address + QR, Safari warning, public address + QR, "Add to Home Screen", error | Kept | (7.4) |
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
| Eight cards, about thirteen Save buttons | Merged into | Nine groups, one Save each at most (10) |
| General: "Display name" + Save | Kept | General (10.3) |
| General: "Locations, comma separated" + Save | Moved to | Storage locations (10.4) |
| General: "PLA rack", "Box location prefix", "Number of storage boxes", "Overflow location" (each + Save) | Moved to | Storage locations, one Save (10.4) |
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
| Card "Library token" + pill, text, field, **Set** / **Replace**, **Remove** | Merged into | Filament Catalog, "Catalog token"; Remove now confirms (10.9) |
| Card "Filament library": version, last check, skipped | Renamed | Filament Catalog state (10.9) |
| **Update now** | Kept | (10.9) |
| **Go back to the version before** + confirm | Kept | (10.9, 10.11) |
| Add entry text, text area, **Add entry**, "Added <vendor> <product>.", "entry not added: …" | Kept | (10.9) |
| Card "Addresses": "Web public address" + Save | Renamed | Network and addresses, "Public address" (10.7) |
| Card "Addresses": "Station address" + Save | Renamed | Network and addresses, "Weigh Station address" (10.7) |
| "Saved; applying…" | Kept | "Saved; applying… Follow it in the job panel." (10.7) |
| Card "Remote access": module-off text, firewall text, **Show the firewall rules**, **Get the certificate** + confirm | Moved to | Network and addresses, Remote access part (10.7, 10.11) |
| (none) | Added | Appearance group: Light / Dark / System, Theme, Theme for new devices (10.2) |
| (none) | Added | Label Reader engine order, On this Hub address, Test and tier (10.5) |

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
| Card "Nightly builds": checkbox, two confirms, state texts | Kept | Toggle with dialogs (12.2, 12.3) |
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

---

## 15. Needs from the Hub

What this design uses that the Hub does not offer today. Until each exists, the page does what the "Until then"
column says.

| Need | Used by | Until then |
|---|---|---|
| A stored default theme for new devices (a general setting `appearance.theme`, the key the command line uses, readable in `G state` and writable through `P settings/general`) | Settings > Appearance, Theme for new devices (10.2) | The field is hidden and no default can be set (the command line's `config theme` needs the same stored setting); devices that have not chosen use Console |
| Saving several general settings in one request, all or nothing | Every Settings group's Save (2.2) | One request per field, in order, stopping at the first refusal |
| A way to check the setup code without side effects | Unlock dialog (2.1) | `P overview` with the code |
| A test of an On this Hub address before it is saved (today `G settings/local-intake` checks only the saved address) | Label Reader Test button (10.5) | Test is disabled while the Address field holds an unsaved change |
| A release of the unreleased endpoints and settings: `G firmware`, `G firmware/<id>.bin`, `P flash/provision`, `P flash/server`, job `reader_setup`; `G settings/local-intake`, `intake.reader`, `local_intake.url`, `local_intake.tier`, the 409 `no_photo` answer | Flash a device (11); Settings > Label Reader (10.5); Recently added (6.4) | Flash a device shows its "No firmware to write" empty state; the Label Reader group shows only the Cloud fields and Records kept |
| Per-field confidence and the engine that read it, stored with each Recently added record | Confidence column, To check filter, field flags (6.2, 6.3) | The column, filter and flags are hidden |
| Last backup time readable without the setup code | Settings list of groups on phone (10.1) | Shown only when Unlocked or Trusted |
| A progress fraction for jobs | Job strip determinate bar (3.5) | Indeterminate bar and the last log line |
| One rule for Bambu Lab address and certificate changes: whether changing the address (`P printers/<serial>/address`) and forgetting the certificate (`P printers/<serial>/unpin`) take the Access Code (`access_code`) and use it, as the web app and the app ask for it | Change address and Forget certificate dialogs (5.5) | Both dialogs ask for the Access Code, so every interface behaves the same; the page sends it with the request as `access_code` |
| Printer states for the whole list in one light read, or a change stream | Printers refresh every 10 s (2.7) | `G state` every 10 s |
| Feature titles in the plain names of section 9.1 | Features collection | The page maps code names to the names of section 9.1 |
| Cloud reads used today and the daily limit as numbers in `G state` | Overview Label Reader tile (4.2) | The numbers are taken from the Overview check row that reports them; when that row is missing the tile shows "Reads per day: <limit>" |
