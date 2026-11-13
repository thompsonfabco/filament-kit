# Spoolwarden design: the web app

The web app is the page for phones in a browser: Safari on iPhone first, any phone browser after that. It is
installable to the home screen. This document specifies it screen by screen in the default theme, **Console**. It
builds on `01-foundations.md` (principles, names, tokens, appearance switch, themes, layout, navigation, hard rules)
and repeats none of it; section numbers in the form "F4.3" point there. Components (top bar, bottom bar, navigation
rail, sheet, dialog, side drawer, menu, toast, segmented control, chip, status, swatch, skeleton, collection, detail
region) are the ones of `02-components.md`; this document says where they go and what they say.

Contents: 1 Where the web app runs · 2 Navigation · 3 Patterns used on every screen · 4 Add spools · 5 Spools (find
and open a spool) · 6 Printers · 7 Recently added · 8 Slicer presets · 9 More and Settings · 10 Home screen, offline
and "Cannot reach the Hub" · 11 The refusal page and the sign-in page · 12 Dialogs that replace the browser's own ·
13 Touch targets · 14 Needs from the Hub · 15 Where today's controls went

Examples use the fake data of the mockups: a Hub called "Workshop", printers "Workshop X1" (192.0.2.40), "Garage
Voron" (voron.example:7125) and "Study A1 mini" (192.0.2.41), spools 209 to 214. Spools being added in the
examples take the next numbers, 215 and 216. Tag ids are shown as the placeholder `<tag id>`.

---

## 1. Where the web app runs

### 1.1 Two addresses, one app

The same files are served from two places. The code keeps its paths (`/intake`, `/intake/api/…`); only the words
on screen change.

| Address | Served by | Differences on screen |
|---|---|---|
| `https://<hub>:8710/intake` (the **home address**) | the Hub itself | Everything in this document. |
| `<public address>/intake` (the **public address**, when the web Feature is on) | the Hub's web service behind its reverse proxy | **Recent** is dimmed and opens the notice in 7.4. **Printer settings** are read-only unless the owner allowed printer changes from the public address (6.8). **Open the Hub page** is not offered (9.1). |

Both addresses are refused to anyone outside the home network (section 11.1). Neither asks for a setup code: the
home network is the gate, so the web app has no lock chip in its top bar. The Hub page's setup code is not used here.

### 1.2 What the page knows when it loads

The Hub writes the page's configuration into `data-*` attributes on `<body>` (as today: `base`, `locations`,
`sealed`, `auto`, `picks`, `ai`, `printers`, `push`, `history`). The web app reads them once at start:

| Attribute | Used for |
|---|---|
| `data-ai` | Whether the Label Reader is on. Off: section 4.3 shows its "off" state. |
| `data-printers` | Whether the Printers Feature is on. Off: **Printers** is dimmed (6.10). |
| `data-push` | Whether print alerts can be offered (9.2, "Print alerts on this phone"). |
| `data-history` | Whether Recently added is served here (home address). Off: 7.4. |
| `data-locations`, `data-sealed`, `data-auto`, `data-picks` | Location lists, the sealed-stock location and the placement rule text used in Add spools and Spools. |
| `data-base` | Prefix for every request. |

Further attributes the design needs (Hub name, Hub page address, Slicer presets on/off, spool editing) are listed in
section 14.

---

## 2. Navigation

### 2.1 The five bottom-bar destinations

On a phone the web app uses the same bottom bar as the Hub page (F8), with its own five destinations:

| Position | Label | Icon | Page | Address |
|---|---|---|---|---|
| 1 | **Add** | plus | Add spools (section 4) | `#add` |
| 2 | **Spools** | spool | Find a spool, open it, link its tag (section 5) | `#spools`, `#spools/<spool id>` |
| 3 | **Printers** | printer | Printers list and one printer (section 6) | `#printers`, `#printers/<printer id>` |
| 4 | **Recent** | clock | Recently added (section 7) | `#recent`, `#recent/<record id>` |
| 5 | **More** | more | Sheet: Slicer presets, Settings, Add to Home Screen, Open the Hub page (section 9) | none (a sheet); Slicer presets `#presets`, Settings `#settings` (2.4) |

Why these five:
- **Add** and **Spools** are the two jobs people do at the bench, several times a week, often with a spool in one
  hand. They get the two positions nearest the left thumb-sweep start and are one tap from anywhere.
- **Printers** is the live view people keep open while printing (status, camera, pause). It is the third everyday
  job and the one the Hub page links to (`#printers`).
- **Recent** is where an addition is checked and corrected right after it is made. It carries the same label and
  icon as on the Hub page's bottom bar (F8), so it is in the same place on both.
- **Slicer presets** is needed only after new filaments arrive, and the Add result links straight to it (4.6), so it
  sits in **More**. Settings (appearance, theme, print alerts) changes rarely and also sits in **More**.
- Today's "Open spool" tab becomes **Spools**: finding a spool is the first half of opening it, and the same page now
  also offers search on its own (section 5).

Every place is reachable in at most two taps: four destinations in one, and everything in **More** in two.

Bottom bar details (all from F4.3 and F8): height `--tab` plus the bottom safe-area inset; five equal cells; icon
above label (`--fs-xs`); the current destination has the `--accent-soft` ground, `--accent-text` label at weight
650, the 3 px mark on the bar's top edge and `aria-current="page"`. The bar is a `<nav aria-label="Sections">`.

Badges on destinations (a small chip at the icon's top-right, with words added to the accessible name):

| Destination | Badge | When | Accessible name |
|---|---|---|---|
| Add | number of spools in the unfinished add, e.g. `3` | an unfinished add exists (4.7) | "Add, 3 spools waiting" |
| Printers | warning triangle | any printer reports an alert, a problem or a refused state | "Printers, needs a look" |

A destination whose Feature is off stays in the bar, dimmed (`--muted` icon and label), and opens a page that says
so (F8). Recent on the public address is shown the same way.

### 2.2 Top bar

```
+------------------------------------------+
| [mark] Spoolwarden                [ (o) ]|   height --top + top safe-area inset
|        Workshop                          |
+------------------------------------------+
```

- Left: the product mark (24 px) and "Spoolwarden" (`--fs-l`, weight 650), with the Hub's name below it
  (`--fs-xs`, `--muted`). Tapping the name does nothing.
- Right, in this order: the connection chip, only while the Hub cannot be reached (wifi-off icon and "Offline";
  pressing it retries, section 10.3); the appearance icon button (sun, moon or half-circle for the current choice;
  opens a menu "Light / Dark / System", F5).
- No lock chip and no job indicator (the web app starts no background jobs).

### 2.3 Tablet and wider

From 601 px the bottom bar is replaced by the navigation rail (F7, Console profile `rail`). The rail lists, top to
bottom: Add, Spools, Printers, Recent, a hairline, Slicer presets, Settings. "More" is not needed there; "Add to Home
Screen" and "Open the Hub page" move into the Settings page, which on tablets is a page, not a sheet. Above
1024 px the layout stays the tablet layout with content up to 1024 px wide and centred; the web app does not use
the desktop layout.

List-and-detail pages (Spools, Printers, Recent) take their layout from the theme's `detail` profile (F6.1, F6.2),
not from the page. In Console it is `inline` (02-components 6.2): on tablets the list keeps the full content width
as a collection, and opening an item (a spool, a printer, a record) expands its detail in place under its row;
several can be open at once. Columns that do not fit move into the expanded row (F7). An item's address still opens
it: `#printers/<id>` shows the list with that printer expanded and scrolled into view. Sheets become dialogs (width
`min(30rem, 100vw - 2 * var(--s4))`, 02-components 1.2); long forms (the Add printer forms and the printer settings
sheets of 12.2, Map by loading filament) open in the side drawer (420 px, F7).

### 2.4 Addresses and remembered state

- The address reflects the place (F8). Back and forward work; a reload returns to the same place.
- Today's addresses keep working: `#add`, `#printers` and `#presets` open their pages; `#open` opens `#spools`;
  `#history` opens `#recent`.
- No address, or an unknown one: the last place, read from `localStorage` key `spoolwarden.place`; if none, `#add`.
- Two sheets are places and have their own address:
  - the spool sheet, `#spools/<spool id>` (5.4): opening it pushes that address; Back closes it and returns to
    `#spools`; a reload opens Spools with the sheet open over it.
  - the Settings sheet, `#settings` (9.2): opening it pushes `#settings`; Back closes it and returns to the place
    it was opened from; a reload opens it over the place stored in `spoolwarden.place` (`#settings` itself is never
    stored there). On tablets `#settings` is the Settings page.
- Every other sheet and dialog (More, Load, the confirmations and questions of section 12, the photo viewer) does
  not change the address. Opening one pushes a history entry with the same address, so the phone's Back gesture
  closes the sheet first; a reload closes it.
- `localStorage` keys, every read and write in try/catch: `spoolwarden.place`, `spoolwarden.printer` (the last
  printer opened, expanded when the printers list opens on tablets), `spoolwarden.sealedOnly` (section 5),
  `spoolwarden.draft.add` (the unfinished add, 4.7), plus the appearance and theme keys of F5 and F6.
- The document title follows the place as `<Page title> · <Hub name>` (F9): "Add spools · Workshop", "Spool 214 ·
  Workshop", "Printers · Workshop". Until the Hub reports its name (section 14), "Spoolwarden" stands in for it. The
  refusal and sign-in pages are the exception (section 11).

---

## 3. Patterns used on every screen

### 3.1 Layout on a phone

- Content in one column, side gutter `--s4`, bottom padding `--tab` + bottom safe-area inset + `--s7` (so the last
  control clears the bottom bar and any sticky action bar).
- One page title (`--fs-xl`) per screen, as the first thing in the content, with focus moved to it on every change
  of place (it has `tabindex="-1"`).
- Groups inside a page are form groups (02-components 5.11): `--surface`, 1 px `--border`, radius `--r`, a header
  row (`--fs-l`, weight `--fw-title`) and a body padded `--s4`. Groups are separated by `--s4`.
- Inputs use `--fs-l` (16 px) on phones so Safari does not zoom; buttons and labels `--fs-m`; controls are `--ctl`
  (44 px at this width).

### 3.2 Results appear where the question was asked

Every action that talks to the Hub has an **inline result** (02-components 8.6) directly under the control that
started it: a status shape and words on the matching soft ground (`--ok-soft`, `--warn-soft`, `--bad-soft`, `--info-soft`), `--fs-m`,
inside an `aria-live="polite"` region. A failed destructive action uses `role="alert"`. Short confirmations also
raise a toast (above the bottom bar on phones). There is no shared message area anywhere on the page.

When the Hub returns its own text (`output` of add, open, presets; `error`), the line shows a one-line summary
written by the web app, and the Hub's full text sits under it in a code block (02-components 7.7; `--code` ground,
`--mono`, `--fs-s`, wraps; long text scrolls inside the block, never the page). The summary is:

| Hub answer | Summary line |
|---|---|
| `exit_code` 0 on a preview | ok: "Preview ready. Nothing is saved yet." |
| `exit_code` 0 on a real change | ok: the change in words, e.g. "Added 2 spools: 215, 216." |
| `exit_code` not 0 | error: "The Hub found a problem. Nothing was changed." (preview) or "The Hub could not finish this. Read its answer below." (real change) |
| `error` text | error: the Hub's text itself, no code block |

### 3.3 Status: shape and word

Status follows F10 and the status badge of 02-components 7.1. Only that component's sixteen words are badges, each
with the shape and colour given there. The badges this app uses:

| Badge | Shape and colour (02-components 7.1) | Used for |
|---|---|---|
| Connected | filled circle, `--ok` | A printer that answers (6.1, 6.3) |
| Offline | hollow circle, `--bad` | A printer that does not answer (6.1, 6.3) |
| Not configured | hollow circle, `--muted` | A printer the Hub knows but that is not set up (`not_configured`) |
| Needs a look | triangle, `--warn` | A printer that needs something (`wrong_code`, `cert_changed`, `needs_developer_mode`, other problem states); always followed by a sentence saying what to do (6.3) |
| On · Off | filled circle `--ok` · hollow circle `--muted` | Print alerts on this phone (9.2) |
| Set · Not set | filled circle `--ok` · hollow circle `--muted` | Access Code and Moonraker API key (6.8) |
| As detected | hollow circle, `--muted` | A Recently added record as the Label Reader read it (7) |
| Revised by AI | info circle, `--info` | A record corrected by the Label Reader and accepted (7) |
| Edited by hand | pencil, `--info` | A record corrected by hand (7) |
| Running | half-filled circle, `--accent-text` | Slot mapping under way (6.7) |
| Done · Failed | filled circle `--ok` · octagon `--bad` | Result of a slot mapping (6.7) |

Every other state is a **sentence**, not a badge. Where a sentence reports a state it starts with the matching
shape (`aria-hidden`, F10) in the semantic colour, so the state is never told by colour alone:

| Shape | Colour | Sentences in this app |
|---|---|---|
| half-filled circle | `--accent-text` | "Printing: <job>" · "Preparing: <job>" · "Reading…" · "Checking…" · "Working…" |
| filled circle | `--ok` | "Finished: <job>" · "The slots are mapped." · inline results that succeeded |
| hollow circle | `--muted` | "Idle" · "The slots are not mapped yet." · "No tag read yet: tap one on a reader." |
| triangle | `--warn` | "Paused: <job>" · "The slot layout changed since the last mapping." · lines that need attention |
| octagon | `--bad` | "Print failed: <job>" · printer alerts · inline results that failed |

Confidence marks of the Label Reader are their own component (02-components 7.2) and are described in 4.5.

### 3.4 Buttons that cannot be pressed yet say why

A button that is not available yet is never silently greyed. It keeps its place, gets `aria-disabled="true"` (not
`disabled`, so it stays focusable and is read out), and a reason line sits directly under it or, in an action bar,
in the bar's text (`aria-describedby` points at it). Pressing it moves focus to the first thing that blocks it (for
example the first empty required field, expanding its card).

### 3.5 Loading, live data and typing

- Lists and status blocks show a skeleton (grey bars in the shape of the content, `--surface-2`) until their first
  data arrives. No page is ever blank.
- Busy buttons keep their width and show the half-filled working shape and a verb ("Checking…"). With reduced
  motion it does not spin (F4.3).
- Live data (tag every 3 s, printer stream, mapping polls) updates text nodes in place. An input that has focus or
  unsaved edits is never redrawn. A poll that fails keeps the last data on screen and adds a triangle line "Last
  update 40 s ago: the Hub did not answer." under the block.
- Leaving a page with unsaved edits in a form (not the unfinished add, which is kept, 4.7) asks with the sheet
  "Leave without saving?" ("Your changes to <thing> are not saved." · "Stay", focused first · "Leave without
  saving", danger), as the unsaved-changes guard of 02-components 5.11.

### 3.6 Errors in words

| What happened | Line shown | Offered |
|---|---|---|
| No answer (network failure, timeout 30 s; 90 s for label reads; 180 s for preset builds, which the page itself announces as "a minute or two") | "Cannot reach the Hub. Check that this phone is on the home network." | "Try again" |
| 403 "home network only" | The whole page becomes the refusal page (11.1). | |
| 403 with the Hub's refusal text for the address the page was opened at (when the web app is served by the Hub itself, the Hub page's address rule applies) | The whole page becomes the refusal page (11.1) with the heading "Not at this address" and the Hub's text in place of the network paragraph. | "Try again" |
| 403 "bad origin" | "The Hub refused this because the page was opened from another address. Reload the page and try again." | "Reload" |
| 403 public-address change refused | Shown as the read-only state of 6.8, not as an error. | |
| 409, 429, 400 with the Hub's text | The Hub's text. | depends on the screen |
| 500 | "The Hub hit an error it did not expect. The details are on the Hub page under Logs." | "Try again" |
| 502 from a label read | The Hub's text, then "Your photos and edits are kept." | "Try again" |
| any other status without text | "The Hub answered with an error (HTTP 503). Try again; if it keeps happening, look on the Hub page under Logs." | "Try again" |

Words on every screen follow the shared wording table of `08-platform-mapping.md` section 12 ("Weight with spool",
"Try again", "Leave empty to choose automatically.", "Slicer presets", "Draft"); every text comes from the shared
string catalogue, which a test keeps equal to the app's.

### 3.7 Sheets and dialogs

On phones every dialog is a bottom sheet (F7): full width, radius `--r-l` on the top corners, at most 92 % of the
screen high, scrolling inside, with the bottom safe-area inset. Header: title (`--fs-l`, 650) and a close icon
button. Footer: buttons side by side, each half the width, the main one on the right. Escape, the close button, a
tap on the scrim and the Back gesture all close it, except while a change is being written (then only the footer's
progress shows). Focus moves into the sheet and returns to the control that opened it. Section 12 lists every sheet
that replaces a browser dialog.

---

## 4. Add spools (`#add`)

Adds spools to the inventory (Spoolman) by hand or from label photos. Nothing is written until the person previews
and then presses Add. Code today: `addTab` in `app.js`.

### 4.1 Layout (phone, 390 px)

```
+------------------------------------------+
| [mark] Spoolwarden                [ (o) ]|
|        Workshop                          |
+------------------------------------------+
| Add spools                               |  page title
| Nothing is saved until you preview and   |
| press Add.                               |
|                                          |
| +- From label photos -------------------+|
| | [ Take photo ]  [ Choose photos ]     ||
| | [img] [img]            2 of 8 photos  ||
| | [ x ] [ x ]                           ||
| | Note for the Label Reader (optional)  ||
| | [ e.g. 3 of the grey ones           ] ||
| | [          Read labels              ] ||
| +---------------------------------------+|
| +- By hand -----------------------------+|
| | Find a filament you already have      ||
| | [ Brand, colour, material        (S)] ||
| | [ + New filament ]                    ||
| +---------------------------------------+|
|                                          |
| Spools to add  2                         |
| +- [#] Polymaker PolyTerra PLA ... -- v-+|
| | PLA . 1000 g . x1 . Sealed            ||
| | ! Medium: Colour, Price per kg        ||
| +---------------------------------------+|
| +- [#] Bambu Lab PETG HF Orange ---- v--+|
| +---------------------------------------+|
+------------------------------------------+
| 2 spools . not previewed     [ Preview ] |  action bar (sticky)
+------------------------------------------+
| Add   Spools  Printers  Recent   More    |  bottom bar
+------------------------------------------+
```

Order, top to bottom: page title and one-line intro; the draft banner when there is a draft (4.7); group
"From label photos" (4.3); group "By hand" (4.2); the read summary when a read has happened (4.4); "Spools to add"
with its count and one card per spool (4.5); the preview or add result (4.6); the sticky action bar (4.6).

When nothing has been added yet the list shows the empty state: "No spools yet. Photograph the labels, or find a
filament you already have." The label-photo group comes first because it is the faster way for sealed stock; when
the Label Reader is off the "By hand" group moves to the top.

Tablet: the two input groups sit side by side above the list; each spool card's form uses two columns.

### 4.2 By hand

| Control | Label and text | Behaviour | Endpoint |
|---|---|---|---|
| Search field | label "Find a filament you already have", placeholder "Brand, colour, material" | Searches after a 300 ms pause once 2 characters are typed, and on Enter. Clearing it clears the results. | GET `filaments?q=` |
| Search icon button inside the field | accessible name "Search" | Runs the search now. | same |
| Result rows (the Hub returns up to 60; shown in pages, see below) | swatch (from the filament's colour, with the hex in the row's `sr` text), "<Brand> <Name>" (`--fs-b`, 600), below it `--muted` "<Material> · <net> g · <n> spools" and the filament number "F57" in `--mono` | Pressing a row adds a spool card filled from that filament, marked "Existing filament", and scrolls to it. The results stay so several can be added. | |
| Pager | the collection's pager (02-components 6.1): "1–50 of 60" (`--mono`), "Previous", "Next" | Only when more than 50 rows came back (F12 rule 7): pages of 50. The page is not in the address, because search results are not kept. Changing page moves focus to the first row. | |
| Results footer | "Showing the first 60. Type more of the name to narrow it down." | only when 60 rows came back | |
| "New filament" button (plus icon) | | Adds a blank card: Spools 1, Net weight 1000 g, Still sealed on, location the sealed-stock location, marked "New filament". | |
| Vendor list | | Loaded once for the Brand suggestions and empty-spool weights. | GET `vendors` |

States: "Searching…" (working shape in the field's trailing slot); empty: "No filament matches. Use New filament."
(with the button repeated inline); error per 3.6.

### 4.3 From label photos

Shown when the Label Reader is on (`data-ai`). When it is off the group stays, collapsed to one line: info circle
and "The Label Reader is switched off. Add the spool by hand, or switch it on in Features on the Hub page."

| Control | Label and text | Behaviour |
|---|---|---|
| "Take photo" (camera icon) | | A file input with `accept="image/*" capture="environment"`: opens the camera on iPhone. One photo per press. Filled while no photo exists; default once one exists (then "Read labels" is the filled button, so the group never has two). |
| "Choose photos" | | A file input with `accept="image/*" multiple`: opens the photo library. Always default. |
| Photo strip | each photo is a column: the thumbnail, 96 px square (2 × `--s7`), radius `--r`, numbered "1", "2"… in a corner chip, and under it, `--s2` apart, its remove button; columns `--s2` apart; "2 of 8 photos" to the right | Photos are resized on the phone to at most 1568 px on the long side, JPEG quality 0.85, as today. At 8 photos the two buttons are aria-disabled with the reason "8 photos at a time. Remove one to add another." |
| Remove photo (x icon button under each thumbnail) | accessible name "Remove photo 2 of 3" | A 44 × 44 icon button of its own, outside the thumbnail's target and `--s2` below it, centred under the thumbnail. Removes at once; a toast offers "Undo" for 10 s. |
| Thumbnail | accessible name "Photo 2 of 3, enlarge" | Opens the photo in a dialog with "Remove this photo" and "Close". |
| Note | label "Note for the Label Reader (optional)", placeholder "e.g. 3 of the grey ones, or all the PETG is white" | A textarea, sent with the photos (cut to 2000 characters by the Hub). |
| "Read labels" | full-width button: default while no photo exists, filled once one exists | Sends photos and note. aria-disabled with "Add a photo first." until a photo exists. |

Endpoint: POST `read` (multipart `photos`, `hint`).

While reading: the button becomes "Reading…" with the working shape; under it the line "The Label Reader is reading
2 photos… (up to a minute)". The photo buttons and the note stay usable. The action bar says "Wait for the Label
Reader."

A photo that cannot be decoded is not added; a line under the strip says "<file name>: this image cannot be read.
Try another photo."

**Reading again** replaces the spools that came from the previous read and keeps spools added by hand. If any of the
spools to be replaced were edited, the sheet "Replace the spools from the last read?" asks first ("You changed 2
spools from the last read. Reading again replaces them; spools you added by hand stay." · "Keep them" · "Read and
replace").

### 4.4 The read summary

After a read, a group "What the Label Reader found" sits above "Spools to add":

```
+- What the Label Reader found ----------------+
| (*) Found 2 spools in 2 photos.              |
| Label Reader: Cloud (Claude) . model-name    |
| ! Medium: Colour . Not on the label: Price   |
|   per kg                                     |
|                                              |
| The Label Reader asks                        |
|  - Are the two orange spools the same lot?   |
|                                              |
| (i) Tag <tag id> was tapped 40 s before the  |
|     photos on the Tag Reader, so this spool  |
|     counts as opened. ...                    |
| (i) Weigh Station scale: 1212 g, 8 s ago,    |
|     filled in as Weight with spool.          |
| > Details                                    |
+----------------------------------------------+
```

| Part | Text | Source |
|---|---|---|
| Result | ok: "Found <n> spools in <m> photos." or warn: "Found no spools. Try clearer photos of the labels, or add by hand." | `items` |
| Reader | "Label Reader: <engine> · <model>", engine one of **Cloud (Claude)** or **On this Hub** (F2); with the On this Hub engine also its tier ("CPU" or "GPU") | `usage.model` today; engine and tier, section 14 |
| Confidence summary | the record summary of 02-components 7.2: "High" (filled circle) when every field is high; otherwise the lowest level with its fields, then the others, e.g. "Low: check Material, Net weight" (octagon) or "Medium: Colour · Not on the label: Price per kg" (triangle) | per-field confidence, 4.5 |
| Questions | heading "The Label Reader asks", one bullet per question, on `--info-soft` | `questions` |
| Tag notice | "Tag <id> was tapped <n> s before the photos on <reader>, so this spool counts as opened. Adding links the tag to it (one opened spool only)." <reader> is "the Tag Reader" or "the Weigh Station" (F2). | `tag` |
| Scale notice | "Weigh Station scale: <g> g, <n> s ago (filled in as Weight with spool)." or "(… not used: only for one opened spool)." | `scale` |
| Details (collapsed) | "<in> tokens in (<cached> cached), <out> out" in `--mono` | `usage` |

### 4.5 The spool card

One card per spool to add. Collapsed it shows a summary; expanded it shows the form. Cards that need attention
(missing required fields, low or medium confidence) start expanded; others start collapsed.

Collapsed card:

| Part | Content |
|---|---|
| Swatch | from Colour, with the hex in the summary line; dashed outline and "No colour" when Colour is empty |
| Title | "<Brand> <Name>", or "New spool" while both are empty |
| Chips | plain text chips without a status shape (these are not states): "Existing filament F57" or "New filament"; "x2" when Spools is above 1 |
| Summary line (`--muted`) | "<Material> · <hex> · <net> g · Sealed" or "· Opened, <g> g on the scale" · "<location or Automatic>" |
| Attention line | the confidence summary of 02-components 7.2, e.g. triangle "Medium: Colour, Price per kg"; or, for missing values, octagon "Needs: Material, Net weight" |
| Expand icon button | chevron, `aria-expanded`, accessible name "Edit <title>" |

Expanded card: the fields below in six groups (the same as the Android app's), each a `<fieldset>` with a
`--fs-s` legend. On phones one column,
except the pairs marked "pair", which share a row. Labels follow the field rule of 02-components 5.1: every field is
required unless its label ends in "(optional)"; there is no "required" word and no asterisk.

| Group | Field label | Input | Rule and helper text | Item field |
|---|---|---|---|---|
| Identity | **Brand** | text, suggestions from the vendor list | Typing a known brand fills a blank Empty spool weight from the vendor list; that field then shows the hint "Filled in from the brand list". | `vendor` |
| | **Name** | text | Helper: "With the colour, e.g. PolyTerra PLA Charcoal Black" | `name` |
| | **Material** | text | Typing a known material fills a blank Density from the built-in table (PLA 1.24, PETG 1.27, ABS 1.04, ASA 1.07, TPU 1.21, PA 1.14, PC 1.2, PCTG 1.23, PVA 1.23, HIPS 1.04); Density then shows the hint "Typical for PLA". | `material` |
| | **Colour (optional)** | swatch, hex text (`--mono`, placeholder "#2B2B2E") and a colour picker button | "Enter a colour as 6 hex digits, e.g. #2B2B2E." when invalid; a value without "#" is accepted | `color_hex` |
| | **Line (optional)** | text | Helper: "The product line, e.g. PolyTerra PLA. Slicer presets are built per line." | `line` |
| Amount | **Spools** (pair) | whole number, `inputmode="numeric"` | "Enter a whole number, 1 or more." | `count` |
| | **Density (optional)** (pair) | decimal, unit "g/cm³" | "Enter a density above 0." | `density` |
| | **Net weight** (pair) | decimal, unit "g" | "Enter grams above 0." | `net` |
| | **Empty spool weight (optional)** (pair) | decimal, unit "g" | "Enter grams above 0." | `tare` |
| State | **Still sealed (in its bag or box)** | toggle | Under it, when the Label Reader gave a reason: "Label Reader: <sealed reason>". Turning it on moves Location to the sealed-stock location and hides the weight; turning it off sets Location to Automatic. | `sealed` |
| | **Weight with spool (optional)** | decimal, unit "g" | Shown only when not sealed. Helper: "Leave empty for a full spool." With Spools above 1: aria-disabled, "Only used for one opened spool." | `gross` |
| Print settings | **Nozzle (optional)** (pair) | whole number, unit "°C" | "Enter degrees above 0." | `nozzle` |
| | **Bed (optional)** (pair) | whole number, unit "°C" | "Enter degrees above 0." | `bed` |
| Storage | **Location** | select: "Automatic (<placement rule>)", then every configured location; always has a value | | `location` |
| Other | **Lot (optional)** | text, `--mono` | | `lot` |
| | **Price per kg (optional)** | decimal | Helper, when the label showed a price: "From the label: <price line>". | `price_per_kg`, `price_line` |
| | **Note (optional)** | text | Saved on the spool. | `note` |

The card's footer holds "Remove" (ghost, trash icon) on the left. Removing a card that has edits raises a toast with
"Undo" for 10 s; nothing asks first.

Values the card keeps but does not show (sent with the item as today): the chosen filament's number and match text,
the photo indexes, the estimate list, the price line, the sealed reason, nozzle and bed from the chosen filament,
and the "added by hand" flag.

**Per-field confidence.** After a read, each field the Label Reader filled carries the confidence mark of
02-components 7.2 after its label (never only a colour; the input's outline does not change; marks are text, not
focusable, read after the value: "Colour, #2B2B2E, Medium"):

| Confidence | Mark (02-components 7.2) | Field hint |
|---|---|---|
| High | none | |
| Medium | triangle "Medium" | "The Label Reader was not sure: check this." (not an error; the field is not `aria-invalid`) |
| Low | octagon "Low: check this" | "The Label Reader was not sure: check this." (not an error) |
| Not on the label | hollow circle "Not on the label" | |

Two further notes are field **hints** (plain sentences under the field, no mark): "Estimated by the Label Reader:
not printed on the label." for fields the Hub lists in `estimates`, and the page's own "Filled in from the brand
list" / "Typical for <material>".

A mark and these hints clear when the person edits the field. Today the Hub reports only which fields are estimated
(`estimates`); the confidence levels need the Hub (section 14). Until then only the "Estimated" and "Filled in"
hints appear, and the summary line in 4.4 says "Estimated: <fields>" in `--muted` instead of the confidence summary.

### 4.6 Preview and Add: the action bar

A sticky bar above the bottom bar (on tablets, at the bottom of the content column): `--surface`, top hairline,
`--s3` padding, the bottom safe-area inset when there is no bottom bar. Left: a status text (`--fs-m`, it wraps to
two lines at most). Right: one filled button. The status text is the button's reason (`aria-describedby`).

| Situation | Status text | Button |
|---|---|---|
| No spools in the list | "Add a spool first: photograph a label or find a filament." | "Preview", aria-disabled |
| A required field is empty | "Spool 2 needs: Material, Net weight." (several spools: "3 spools need fields. Spool 2 is first.") | "Preview", aria-disabled; pressing it opens spool 2 and focuses Material |
| A value is not valid | "Spool 1: enter grams above 0 for Net weight." | "Preview", aria-disabled |
| The Label Reader is reading | "Wait for the Label Reader." | "Preview", aria-disabled |
| The Hub cannot be reached | "The Hub cannot be reached. Your spools are kept on this phone." | "Preview", aria-disabled |
| Ready | "<n> spools · not previewed" | "Preview" |
| Previewing | "Checking with the Hub…" | "Checking…" (working shape) |
| The preview found problems | "The Hub found problems. Fix them and preview again." | "Preview" |
| Previewed, nothing changed since | "Preview ready: <n> spools." | "Add <n> spools" ("Add 1 spool") |
| Something was edited after the preview | "You changed spool 2. Preview again." | "Preview" |
| Adding | "Adding to Spoolman…" | "Adding…" (working shape) |

Any edit to any card, adding or removing a card, or a new read makes the preview out of date. "Medium" and "Low"
marks do not block the preview; they are counted in the status text ("3 fields to check · Preview ready: 2
spools.").

Endpoints: POST `add` with `{items, dry_run: true}` for Preview; POST `add` with `{items, dry_run: false, link_tag,
read_id}` for Add (as today).

**Preview result** (a group after the last card, scrolled into view): title "Preview" with the line "Nothing is saved yet.", the
summary line of 3.2 and the Hub's text in a code block. Problems the Hub names for a field are also shown under that
field when the Hub returns them per item (section 14); until then they are only in the code block.

**Add result.** On success:
- The group becomes ok: "Added <n> spools: 215, 216." and a toast "Added 2 spools.".
- When `history_id` came back and Recently added is served here: button "Check them in Recently added" (opens
  `#recent/<history id>`).
- When any added spool was a new filament: "<n> new filaments need a preset line." with button "Set up Slicer
  presets" (opens `#presets`).
- The unfinished add is cleared (4.7): cards, photos, note, tag and the search field empty. The result group stays
  at the top of the page until the person starts a new add.

On failure the cards stay as they were, the group shows the summary and the Hub's text, and the action bar returns
to "Preview".

### 4.7 The unfinished add survives a reload

Everything being added is kept on the phone until it is added or discarded, so a reload, a closed tab or iOS
dropping the home-screen app loses nothing.

The add is a long form with drafts as in 02-components 5.11 (`data-draft="add"`).

- **Store.** `localStorage` key `spoolwarden.draft.add`, one JSON value: the cards with all their values and
  confidence marks, the note, the last read's `read_id`, questions, tag and scale notices, the reader line, the
  time it was started and last changed, and the id of the tab that wrote it (a random id kept in `sessionStorage`).
  Every read and write in try/catch.
- **When it is written.** While the add holds anything: 400 ms after the last change, and at once on
  `visibilitychange` to hidden and on `pagehide`.
- **What is not kept.** The photos (they are files, not typed values: after a restore the cards are back, and the
  photos are taken again only to read the labels again). The preview: after a restore the action bar says "<n>
  spools · not previewed". Search results.
- **Restore.** On load, when a draft exists, the Add page shows the draft banner of 02-components 5.11 at its top:
  "You have a draft from 10 minutes ago: 3 spools." with **Restore them** (filled) and **Discard**.
  Restore puts the cards, note and notices back; when the draft came from a read, the banner's inline result adds
  "The photos are not kept; take them again to read the labels again." The Add destination shows its badge (2.1)
  while a draft exists.
- **Discard.** The sheet "Discard this add?" ("The 3 spools on this phone are deleted. Nothing was added to the
  inventory." · "Keep" · "Discard", danger). Afterwards a toast "Discarded."
- **Cleared** after a successful Add and after Discard.
- **Two tabs.** Only one tab keeps the draft. When the page sees a `storage` event for `spoolwarden.draft.add`
  written by another tab, it stops writing the draft and shows under the title: triangle "This add is also open in
  another tab, which now keeps it. Reload this tab to continue here." Reloading makes that tab the one that keeps
  it (Restore as above).
- **No storage.** If `localStorage` cannot be written (private browsing, storage blocked or full), the page keeps
  working and shows under the title: triangle "This browser cannot keep a draft. Finish before leaving the
  page."

### 4.8 Texts of this screen

| State | Text |
|---|---|
| Intro | "Nothing is saved until you preview and press Add." |
| Empty list | "No spools yet. Photograph the labels, or find a filament you already have." |
| Label Reader off | "The Label Reader is switched off. Add the spool by hand, or switch it on in Features on the Hub page." |
| Reading | "The Label Reader is reading <n> photos… (up to a minute)" |
| Daily limit (429) | the Hub's text, then "Add by hand, or try again tomorrow." |
| Read failed (502) | the Hub's text, then "Your photos and edits are kept." with "Try again" |
| Tag conflict (409) on Add | the Hub's text, then "Nothing was added." |

---

## 5. Spools: find and open a spool (`#spools`)

Finds spools in the inventory and acts on one: link the tag last tapped on a reader and open the spool (weight,
location, box humidity), and, where the Hub offers it, update the weight, move it, mark it empty or load it into a
printer. Code today: `openTab` in `app.js`.

### 5.1 Layout (phone)

```
+------------------------------------------+
| Spools                                   |
| Tap the spool's tag on a reader, find    |
| the spool, weigh it, link.               |
|                                          |
| +- Last tag ----------------------------+|
| | [tag] <tag id>            12 s ago    ||
| | Tag Reader . scale 1212 g             ||
| | Not linked to a spool yet.            ||
| +---------------------------------------+|
|                                          |
| [ Brand, colour, material          (S) ] |
| [x] Sealed only                          |
|                                          |
| Polymaker PolyTerra PLA Charcoal Black   |
|  PLA . F57                               |
| +---------------------------------------+|
| | Spool 214  Shelf A . 1000 g . Sealed >||
| +---------------------------------------+|
+------------------------------------------+
| Add   Spools  Printers  Recent   More    |
+------------------------------------------+
```

### 5.2 Last tag

A group that follows the last tag read by any reader. GET `tag`, every 3 s while the page is visible; it stops when
the page is hidden or left.

| State | Content |
|---|---|
| Loading (first request) | skeleton line and "Checking for the last tag…" |
| No tag | hollow circle "No tag read yet: tap one on a reader." |
| A tag | tag icon, the tag id (`--mono`), the age ("12 s ago", "3 min ago", "2 h ago"; exact time on long-press), the reader ("Tag Reader" or "Weigh Station", F2), and "scale <g> g" when the Weigh Station scale sent a reading; below, the Hub's text for the tag (`text`) |
| The tag belongs to a spool | (Printers Feature on, from GET `printers/tagged`) "Linked to spool 214, Polymaker PolyTerra PLA Charcoal Black" and the button "Show spool 214" |
| The poll failed | the last tag stays; a triangle line "Last update 40 s ago: the Hub did not answer." |

A new tap that comes with a Weigh Station scale reading fills the weight in an open spool sheet (5.4) if that field
has not been typed in; the field shows "Filled in from the Weigh Station scale, 8 s ago".

### 5.3 Search

| Control | Label and text | Behaviour | Endpoint |
|---|---|---|---|
| Search field | label "Find a spool" (visually hidden), placeholder "Brand, colour, material" | Searches after a 300 ms pause once 2 characters are typed, and on Enter. | GET `find?q=&sealed=0|1` |
| Search icon button inside the field | accessible name "Search" | Runs the search now. | same |
| "Sealed only" | checkbox, 44 px row | On by default. Remembered in `spoolwarden.sealedOnly`. Changing it re-runs the search. | same |
| Result groups | per filament: "<Brand> <Name>" (600), `--muted` "<Material> · F57", then one row per spool | | |
| Spool row (whole row is the button, `--row` tall) | "Spool 214" (`--mono`), "<location or ?> · <remaining> g · Sealed · Has a tag · Lot <lot>" | Opens the spool sheet (5.4) and sets the address to `#spools/214`. | |

The Hub returns up to 60 spools. More than 50 are shown in pages of 50 with the collection's pager (02-components
6.1: "1–50 of 60", "Previous", "Next"; not in the address; changing page moves focus to the first row). When the Hub
says the list was cut (`truncated`), the last line is "More spools match.
Type more of the name to narrow it down." Empty: "No spools match." (with "Sealed only" on: "No sealed spools match.
Turn off Sealed only to include opened spools.") Errors per 3.6.

### 5.4 The spool sheet (`#spools/<spool id>`)

On phones a sheet (it fills up to 92 % of the screen) with the address `#spools/<spool id>` (2.4); on tablets the
same content expands in place under the spool's row in the results (2.3).

```
+------------------------------------------+
| Spool 214                            [x] |
| Polymaker PolyTerra PLA Charcoal Black   |
| Shelf A . 1000 g left . Sealed           |
|------------------------------------------|
| Open it and link the tag                 |
| Tag: <tag id>, tapped 12 s ago on the    |
| Tag Reader                               |
| Weight with spool (optional)             |
| [ 1212                           ] g     |
| Filled in from the Weigh Station scale   |
| Location (optional)                      |
| [                                  ]     |
| Leave empty to choose automatically.     |
| Box humidity (optional)                  |
| [ From the box hygrometer        ] %     |
| (i) Preview first: nothing changes until |
|     you link.                            |
| [ Preview ]     [ Link tag and open ]    |
|------------------------------------------|
| Other actions                            |
| [ Update weight ] [ Move ]               |
| [ Load into a printer ]                  |
|                          [ Mark empty ]  |
+------------------------------------------+
```

**Open it and link the tag.** Fields and buttons:

| Control | Label and text | Behaviour |
|---|---|---|
| Tag line | "Tag: <id>, tapped <age> on <reader>" (<reader> is "the Tag Reader" or "the Weigh Station"), or "No tag read yet: tap the spool's tag on a reader." | Live from 5.2. |
| Weight | "Weight with spool (optional)", unit "g", decimal | "Enter grams above 0, or leave this empty." |
| Location | "Location (optional)", text with suggestions (pick locations, then all locations), hint "Leave empty to choose automatically." | |
| Box humidity | "Box humidity (optional)", unit "%", decimal, placeholder "From the box hygrometer" | "Enter a percentage from 0 to 100." |
| "Preview" | default button | POST `open` with `{spool, gross, location, humidity, dry_run: true}`; inline result under the buttons with the Hub's text (it names the tag, old taps, tags one byte apart and "dry run: nothing changed"). |
| "Link tag and open" | filled | aria-disabled until a preview succeeded with no change since. Reasons: "Preview first: nothing changes until you link." · "You changed the weight. Preview again." · "The Hub found a problem. Fix it and preview again." POST `open` with `dry_run: false`. |

On success: ok line "Spool 214 is open" followed by the Hub's text, a toast "Spool 214 opened.", the three fields
clear and the summary at the top of the sheet updates from the returned spool (location, remaining, "Has a tag").
When no tag has been read the main button keeps its label; the Hub's preview says whether it can open the spool
without one.

**Other actions.** "Update weight", "Move" and "Mark empty" are shown when the Hub offers spool editing to the web
app (section 14). "Load into a printer" is shown whenever the Printers Feature is on, because it uses endpoints the
Hub has today. When none of the four is available the group is absent and the sheet ends after "Link tag and open".

| Action | How it works |
|---|---|
| "Update weight" | Opens a small form in place: "Weight with spool"; "Preview" shows "Remaining changes from 1000 g to 812 g."; then "Save weight". |
| "Move" | A menu of locations; choosing one moves it at once; inline result "Moved to Dry box 1." with "Undo" for 5 s. |
| "Mark empty" | Kept apart at the end (danger outline). Sheet "Mark spool 214 empty?" ("Polymaker PolyTerra PLA Charcoal Black will be marked as used up." · "Cancel" · "Mark empty", danger). Result "Marked empty." |
| "Load into a printer" | Printers Feature on. A step list in the sheet: "Load into which printer?" (one row per printer with state), then "Which slot on Workshop X1?" (one row per slot with its current spool), then the automatic preview and "Load", exactly as the load sheet of 6.5. Endpoints: GET `printers`, GET `printers/<id>/state`, POST `printers/<id>/slots/<slot>/load`. |

---

## 6. Printers (`#printers`)

Live status, camera and print controls, the slots with load and unload, the filament used, slot mapping and the
printer's settings. Code today: `printersTab` in `printers.js`. Shown when the Printers Feature is on.

### 6.1 Printers list (`#printers`)

```
+------------------------------------------+
| Printers                    [ + Add ]    |
| 3 printers . (o) Connected 2             |
|              ( ) Offline 1               |
|                                          |
| +---------------------------------------+|
| | Workshop X1              (o) Connected||
| | Bambu Lab X1 Carbon                   ||
| | (*) Printing: Benchy . 42 % . 1 h 12  ||
| |     min left                          ||
| | [=========-------------]              ||
| | [#][#][#][ ]  3 of 4 loaded         > ||
| +---------------------------------------+|
| +---------------------------------------+|
| | Garage Voron             (o) Connected||
| | Klipper (Voron 2.4)                   ||
| | ( ) Idle                              ||
| | [#][#]  2 of 2 loaded               > ||
| +---------------------------------------+|
| +---------------------------------------+|
| | Study A1 mini             ( ) Offline ||
| | Bambu Lab A1 mini                     ||
| | ! The last slot mapping stopped twice.||
| +---------------------------------------+|
|                                          |
| Found on the network, not added yet      |
| +---------------------------------------+|
| | Bambu Lab P1S  192.0.2.42   [ Add ]   ||
| +---------------------------------------+|
| [ Add a Klipper printer ]                |
+------------------------------------------+
```

- Data: GET `printers` every 5 s while the list is visible; GET `printers/<id>/state` for each printer every 10 s
  for progress and slots; GET `printers/manage` once on open and after every change, for the found printers.
- Card (the whole card opens `#printers/<id>`): name (`--fs-l`, 650) and the connection badge at the right
  (Connected, Offline, Not configured or Needs a look, 3.3); model (`--muted`); while connected, the print state
  sentence (3.3, 6.3: "Printing: Benchy", "Idle"), and while printing also percent, time left and a 4 px progress
  bar; slot swatches (the level swatch of 02-components 7.3, filled from the bottom by the remaining percentage,
  dashed when empty) with "<n> of <m> loaded"; any problem or alert as a triangle or octagon line. The
  swatches are `aria-hidden`; each slot's colour is in the card's `sr` text, one sentence per slot ("A1 Polymaker
  PolyTerra PLA Charcoal Black #2B2B2E, 62 % left"; "A4 empty"), so every swatch has its colour's name or hex
  (F4.1).
- Header line: "<n> printers · Connected <n> · Offline <n>" (badges with counts, 02-components 7.1).
- "Add" (plus icon) at the top right opens the add choice (6.9). The default button "Add a Klipper printer" at the
  end of the page opens the sheet "Add a Klipper printer" (12.2).
- Found on the network: one row per Bambu Lab printer the Hub has seen but not added: model, address (`--mono`) and
  "Add". Shown only when there is one.
- Empty: "No printers yet." · "The Hub finds Bambu Lab printers on its network by itself: turn the printer on, then add it here with its Access Code. A Klipper printer is added by its address." · "Add a Klipper printer".
- Errors: as 3.6; the cards keep their last data.

Tablet: the list keeps the full content width; opening a printer expands its page (6.2 to 6.8) in place under its
card (2.3). When the list opens without an address naming a printer, the printer opened last
(`spoolwarden.printer`) is expanded.

### 6.2 One printer (`#printers/<id>`): layout

```
+------------------------------------------+
| < Printers                               |
| Workshop X1                              |
| Bambu Lab X1 Carbon . 192.0.2.40         |
| (o) Connected                            |
|------------------------------------------|
| (*) Printing: Benchy                     |
| [============-----------------]  42 %    |
| Layer 80 of 190 . 1 h 12 min left        |
| Nozzle 220 / 220 C . Bed 55 / 55 C       |
|                                          |
| [ Pause ] [ Turn the light off ]         |
|                         [ Stop print ]   |
| [ Show camera ]                          |
|------------------------------------------|
| Slots                                    |
| AMS A . AMS 2 Pro                        |
| A1 [#] Polymaker PolyTerra PLA     In use|
|        Charcoal Black . 620 g left       |
|        [ Load ] [ Unload ]               |
| A4 [ ] Empty                             |
|        [ Load ]                          |
|------------------------------------------|
| Filament used          Last 7 days       |
| 12.4 g  Benchy . A1             [ Undo ] |
| 2026-11-12 14:05                         |
|------------------------------------------|
| Slot mapping                             |
| Printer settings                         |
+------------------------------------------+
```

Sections in this order, each a group: status (6.3), controls and camera (6.4), Slots (6.5), Filament used (6.6), Slot
mapping (6.7), Printer settings (6.8). The back link "Printers" (chevron) sits above the title on phones; on tablets
the printer is expanded under its card in the list (2.3), so there is no back link and the card's expand button
closes it.

The printer has at most one filled button (F1, principle 2), chosen in this order: "Resume" while paused; else "Map
slots" while the slots are not mapped yet; else "Collect a report" when the Hub says a report would help. Every
other button on the printer is default, ghost or danger outline.

The page opens the printer's live stream, GET `printers/<id>/events`, and closes it, the camera and any open sheet
when the page is left or hidden. Until the first message arrives, the status and Slots groups show skeletons.

### 6.3 Status

| Part | Content |
|---|---|
| Title | printer name (`--fs-xl`) |
| Facts | model · address (`--mono`) |
| Connection | a badge (3.3) and the sentence under it from the printer's `state`, as the printer states table of `02-components.md` 7.1 gives them, the same in every interface. Under it: the Hub's fix text when it sends one. |
| Print state | a sentence with its shape (3.3), from `gcode_state`: RUNNING "Printing", PAUSE "Paused", PREPARE "Preparing", FINISH "Finished", FAILED "Print failed", IDLE "Idle" (others: the word in sentence case), then ": <job name>" |
| Progress | while Printing, Paused or Preparing: progress bar (4 px, `--accent-text`) with the percent at the right (`--mono`), then "Layer <n> of <total> · <time> left" and the stage when the printer reports one; <time> is "<h> h <m> min", or "<m> min" under one hour |
| Temperatures | "<name> <current> / <target> °C" joined by " · " (`--mono` numbers) |
| Printer alerts | one octagon line each: the printer's text, or "Printer alert <code>" |
| Notes | `--muted` lines |
| Stream line | hidden while the stream is open; "Reconnecting…" (working) after a stream error; the Hub's stream error text otherwise; when the Hub has too many open views: "Too many phones and tabs are watching the printers. Close one; this page tries again by itself." |

### 6.4 Controls and camera

| Control | Shown when | Style | Endpoint and result |
|---|---|---|---|
| "Pause" | Printing | default | POST `printers/<id>/command` `{action: "pause"}`; line "Paused." |
| "Resume" | Paused | filled | `{action: "resume"}`; line "Resumed." |
| "Stop print" | Printing, Paused or Preparing | danger outline, alone at the end of the row (on phones on its own line, right-aligned) | opens the sheet "Stop the print?" (12); then `{action: "stop", confirm: true}`; line "Stopped." |
| "Turn the light on" / "Turn the light off" | the printer reports a light | ghost; the label says what pressing does and changes with the light's state (no `aria-pressed`) | `{action: "light_on"}` / `{action: "light_off"}`; line "Light on." / "Light off." |
| "Show camera" / "Hide camera" (camera icon) | the printer has a camera | default | see below |

While a command is sent its button shows the working shape. The inline result sits under the row: the words above,
or, when the printer refuses, the sentence in the reply's `message` as sent (until the Hub sends one: "The printer
said no: <the reply's `error` text>"; 02-components 8.6 and 12; never the raw reply, never JSON), or the Hub's text (its refusals: printer offline, no reply, busy, slot in use,
certificate changed, needs Developer Mode, no preset, write refused, already running). A refusal that points at
Slicer presets carries the button "Open Slicer presets".

**Camera.** A box with a 16:9 ratio, radius `--r`, ground `--surface-3`, under the controls. MJPEG printers:
`<img alt="Camera of Workshop X1">` from GET `printers/<id>/camera.mjpeg`. HLS printers: `<video controls autoplay
muted playsinline>` from GET `printers/<id>/camera/<name>`. The picture is never inverted in dark (F5).

| State | Text in the box |
|---|---|
| Starting | skeleton and "Starting the camera…" |
| Browser cannot play HLS | "This browser cannot play this printer's camera. Use Safari on iPhone or Mac." |
| Did not start | "The camera did not start. Check that the printer is on, LAN Mode Liveview is on, and not too many views are open." · "Try again" |
| Too many views (429) | "Too many camera views are open (4 at most). Close one on another phone or tab." · "Try again" |

### 6.5 Slots, load and unload

One group per unit, headed "<label> · <type>" (for example "AMS A · AMS 2 Pro"). One row per slot:

| Part | Content |
|---|---|
| Slot | label in `--mono` ("A1", "T0") |
| Swatch | the medium swatch of 02-components 7.3, the slot's colour; dashed outline when empty, hatched "no colour" without one |
| Name | the spool's name, else the slot's material type, else the state; under it `--muted` "<hex> · <g> g left", "Empty" or "Reading…" (the hex accompanies the swatch, F4.1) |
| In use | as the slot strip (02-components 7.5): the active slot carries the words "In use" in `--accent-text` weight 650 and a 3 px `--accent-text` mark on its left, not only bold text |
| Buttons | on their own line under the name: "Load" (always) and "Unload" (when the slot holds a spool); each `--ctl` (44 px) high, at least `calc(2 * var(--ctl))` (88 px) wide |

Empty: "The printer reports no slots." Results of load and unload appear in a line under that slot's row.

**Load sheet** ("Load into A4"):

```
+------------------------------------------+
| Load into A4                         [x] |
| [ Use the last tapped tag ]              |
| or                                       |
| [ Brand, colour, material          (S) ] |
|  Spool 214  Polymaker PolyTerra PLA ...  |
|  Spool 210  Prusament PLA Galaxy ...     |
|------------------------------------------|
| Load Polymaker PolyTerra PLA into A4     |
| Preset: Polymaker PolyTerra PLA @X1C     |
| Nozzle: 0.4 mm                           |
| Spool 211 now in A4 goes back to Shelf B |
|------------------------------------------|
| [ Cancel ]                    [ Load ]   |
+------------------------------------------+
```

| Control | Behaviour | Endpoint |
|---|---|---|
| "Use the last tapped tag" | Picks the spool linked to the last tag. Lines: "Tag <id> is not linked to a spool." · "No tag read yet: tap one." | GET `printers/tagged` |
| Search field, placeholder "Brand, colour, material" | as 5.3, opened spools included | GET `find?q=&sealed=0` |
| Spool rows | as 5.3; picking one shows it as "Spool 214, Polymaker PolyTerra PLA Charcoal Black (Shelf A, 1000 g)" with "Change", and runs the plan | |
| Plan | runs by itself after a pick: "Load <spool> into <slot>", "Preset: <name or none>", "Nozzle: <mm> mm" or "Nozzle size not reported by the printer; assuming <mm> mm", "Spool <id> now in <slot> goes back to <location>", and the Hub's problems as octagon lines | POST `printers/<id>/slots/<slot>/load` `{spool_id, dry_run: true}` |
| "Cancel" | closes | |
| "Load" | filled; aria-disabled with "Pick a spool first." · "Working out the plan…" · "The Hub found a problem; see above." | same with `dry_run: false` |

Before a pick the sheet says "Pick a spool: tap its tag on a reader, or search." After loading, the sheet closes, a
toast says "Loaded into A4." (or "Sent to A4.") and the slot's line says "Loaded into A4." or "Sent to A4. The printer
accepted it but hasn't shown the change yet."

**Unload.** Pressing "Unload" runs the preview first (the button shows "Checking…"; POST
`printers/<id>/slots/<slot>/unload` with `dry_run: true`), then opens the sheet "Unload from A3?" (12). Confirming
sends it for real. Line under the slot: "Unloaded eSUN ABS+ White from A3. Moved back: spool 211 to Shelf B."

### 6.6 Filament used

Heading "Filament used" with "Last 7 days" at the right. GET `printers/<id>/usage?days=7`, up to 20 rows, newest
first.

| Part | Content |
|---|---|
| Amount | "<g> g" (`--mono`, 600) |
| What | job name (or "Print job") · slot |
| When | `2026-11-12 14:05` (`--mono`, `--muted`) |
| State | undone rows: the row's text `--muted` and struck through, followed by "(undone)" (as 02-components 7.10; not a badge) |
| "Undo" | ghost button, 44 px, not on undone rows; opens the sheet "Put it back on the spool?" (12); POST `printers/<id>/usage/<entry>/undo`; line in the row "Put 12.4 g back on the spool." |

Empty: "Nothing used in the last 7 days."

### 6.7 Slot mapping

GET `printers/<id>/map` on open and every 2 s while mapping runs.

| Part | Content |
|---|---|
| Status | the sentence "The slots are mapped." (filled circle) or "The slots are not mapped yet." (hollow circle), then the Hub's state and step words; while mapping runs the badge Running, after it Done or Failed (3.3); "The slot layout changed since the last mapping." (triangle) when the Hub says so; or the Hub's `outcome_text` |
| Next step | the Hub's `next_step` as a paragraph |
| Problems | octagon lines; when they are from an earlier mapping, first the line "From an earlier mapping; it may be fixed by now. Map the slots again to check." |
| Notes | `--muted` lines; the report hint |
| "Map slots" | default; filled when not mapped yet and the printer is not paused (6.2: one filled button per printer). Opens the sheet "Map the slots of <printer>?" (12), then POST `printers/<id>/map`. While running: "Mapping…" with the working shape, aria-disabled with "Mapping is running." |
| "Map by loading filament" | default; opens 6.7.1 |
| "Collect a report" | filled when the Hub says a report would help and neither "Resume" nor "Map slots" is filled (6.2), else default. POST `printers/<id>/report`. Then the line "Report ready." with the button "Download report" (the file the Hub made) and the text "Then attach it to a "Printer report" issue on the project's issue tracker." When the printer is not live: `--muted` "The printer is offline, so the report holds only what the Hub saved earlier." |

#### 6.7.1 Map by loading filament

A full-height sheet on phones, the side drawer on tablets. GET `printers/<id>/manual-map` every 2 s while it is open;
the selects keep their choice across polls.

```
+------------------------------------------+
| Map by loading filament              [x] |
|------------------------------------------|
| Load filament into one slot at a time;   |   intro: the Hub's say / summary
| the Hub notes where it went.             |
|                                          |
| Did you load A2?                         |   question
| [            Yes                       ] |   filled
| No, I loaded                             |
| [ A3                                v ]  |
| [ Save that ]                            |
|                                          |
| (*) The printer reports a change;        |   waiting line, only while waiting
|     waiting for it to settle...          |
|------------------------------------------|
| Positions                                |
| (o) A1: Confirmed (A1)                   |
| (i) A2: Entered by hand (A2)             |
|     A3: waiting                          |
|------------------------------------------|
| [ Skip A2 ]                   [ Stop ]   |
+------------------------------------------+
```

Before a run the question block is replaced by the intro and "Start" (filled); at the end the positions stay and
the offer below replaces the question block. Only one filled button shows at a time ("Start" or "Yes").

| Part | Content | Endpoint |
|---|---|---|
| Intro | the Hub's `say` or `summary` text | |
| Start | "Start" (filled) when no mapping by loading is running | POST `printers/<id>/manual-map/start` |
| Question | the Hub's question text, then "Yes" (filled) | POST `…/manual-map/confirm` |
| Correction | "No, I loaded" + select of positions + "Save that" | POST `…/manual-map/confirm` |
| Nozzle (two-nozzle printers) | select "Nozzle": "Right nozzle", "Left nozzle" | sent with the confirm |
| Printers that cannot report loads | select "The slot it is in" + "Save (not checked by the printer)" | POST `…/manual-map/confirm` |
| Waiting | working shape and "The printer reports a change; waiting for it to settle…" | |
| "Skip <position>" | default | POST `…/manual-map/skip` |
| "Stop" | default, at the end | POST `…/manual-map/stop` |
| Positions | one row each: "<position>: Confirmed (<slot>[, <nozzle> nozzle])" (filled circle), "Entered by hand (<slot>)" (info circle), or the Hub's word | |
| Offer at the end | "Share this map in a printer report, so other owners of this model benefit? Nothing is sent unless you choose to." · "Yes, how do I share it?" · "No thanks" | POST `…/manual-map/offer` |

### 6.8 Printer settings

From GET `printers/manage`. A list of rows, label left, value and one button right (stacked on phones):

| Row | Value | Button | Sheet (section 12) |
|---|---|---|---|
| Name | "Workshop X1" | "Rename" | Rename printer |
| Address | "192.0.2.40" (`--mono`), or "No address yet" (`--muted`) while the Hub has none | "Change" ("Set" when there is no address) | Change address |
| Access Code (Bambu) | badge "Set" (3.3); the code itself is never shown | "Replace" | Replace Access Code |
| Certificate (Bambu) | the words "Pinned" or "Not pinned" (plain text, no shape) | "Forget" (when pinned) | Forget the certificate |
| Moonraker API key (Klipper) | "Set" or "Not set" | "Set" or "Replace" | Moonraker API key |

Then, apart, after a hairline: "Forget printer" (danger outline, trash icon), which opens "Forget Workshop X1?".

Every change goes to POST `printers/<id>/edit` (forget: POST `printers/<id>/forget`). Results appear in a line under
the list ("Renamed to Workshop X1.", "Address changed to 192.0.2.40. The Hub reconnects now.", "Access Code
replaced.", "Certificate forgotten. The next connection pins a new one.", "API key saved."); after Forget the page
returns to the list with the toast "Workshop X1 forgotten."

On the home address the group's description line under its heading says: "Anyone on the home network can use this page." (`--muted`).

**On the public address with printer changes off** (`changes` false): the values show without buttons, and the
group starts with the info line "Read-only here: printer changes from the public address are off. Open this page on
the home address to add, change or forget a printer, or allow them on the Hub page under Settings." The add buttons
of 6.1 are hidden and the same line appears there.

### 6.9 Adding a printer

"Add" on the list opens a menu: "Bambu Lab printer found on the network" (one item per found printer) and "Klipper
printer by address". The sheets are in section 12 ("Add <model>", "Add a Klipper printer"). POST `printers/add`.
While the Hub connects: "Connecting to the printer…". On success the sheet closes, the new printer opens
(`#printers/<id>`) and its status line says "Added. The Hub is connecting to it."

### 6.10 Printers switched off

When the Printers Feature is off, the destination is dimmed and the page shows: printer icon, "Printers is switched
off" and "Switch it on in Features on the Hub page." with "Open the Hub page" (home address only).

---

## 7. Recently added (`#recent`)

The newest additions with their label photos: check them, correct them by hand or by asking the Label Reader, and
undo a correction. Served on the home address only (7.4). Code today: `historyTab` in `app.js`.

### 7.1 List (`#recent`)

```
+------------------------------------------+
| Recently added                           |
| The newest 20 additions are kept with    |
| their photos (14.2 MB now).              |
| [ All 5 | To check 2 ]                   |
|                                          |
| +---------------------------------------+|
| | [img] Polymaker PolyTerra PLA       > ||
| |  2    Charcoal Black                  ||
| |       From a phone photo . 2 h ago    ||
| | ( ) As detected           Spool 214   ||
| |---------------------------------------||
| | ! Medium: Colour . Not on the label:  ||
| |   Price per kg                        ||
| +---------------------------------------+|
| +---------------------------------------+|
| | [img] Bambu Lab PETG HF Orange  x2  > ||
| |       From a phone photo . 7 h ago    ||
| | (i) Revised by AI     Spools 212, 213 ||
| +---------------------------------------+|
+------------------------------------------+
```

- Data: GET `history`. Photos: GET `history/<id>/photos/<n>`.
- Intro: "The newest <keep> additions are kept with their photos (<size> now). Change the number on the Hub page
  under Settings."
- Filter (segmented control, shown only when the Hub reports read confidence, section 14): "All <n>" · "To check
  <n>".
- Card (the whole card opens `#recent/<id>`): first photo 48 px (`--s7`) with the photo count chip, or a dashed box
  with "No photo"; names "<Brand> <Name>" and "x<n>" for several spools; source in words ("From a phone photo", "From
  the Weigh Station", "Added by hand"; another value: the Hub's word) and the relative time (exact time on
  long-press); state: the badge "As detected", "Revised by AI" or "Edited by hand" (3.3); "Spool 214" or "Spools
  212, 213" in `--mono`; when confidence is known, a last line with the record summary of 02-components 7.2, e.g.
  "Medium: Colour · Not on the label: Price per kg" (triangle) or "Low: check Material, Net weight" (octagon).
- Empty: "Nothing added yet" with the text "No spool has been added since the history started. Spools added from the web app, the app or the Weigh Station appear here."
- Tablet: the list keeps the full content width; opening a record expands it in place under its card (2.3).

### 7.2 One record (`#recent/<id>`)

```
+------------------------------------------+
| < Recently added            [ < ] [ > ]  |
| Polymaker PolyTerra PLA Charcoal Black   |
| 2026-11-12 14:05 . From a phone photo    |
| ( ) As detected . Spool 214              |
|                                          |
| +- Photos  2 ---------------------------+|
| | [ img ] [ img ]                       ||
| +---------------------------------------+|
| +- Spool 214 ------------ [ Edit ] -----+|
| | Identity                              ||
| |  Brand        Polymaker               ||
| |  Name         PolyTerra PLA Charcoal..||
| |  Material     PLA                     ||
| |  Colour       [#] #2B2B2E  ! Medium   ||
| |  Line         PolyTerra PLA           ||
| | Weights                               ||
| |  Net weight          1000 g           ||
| |  Empty spool weight   140 g           ||
| |  Density             1.31 g/cm3       ||
| | Temperatures  ...                     ||
| | Other                                 ||
| |  Price per kg  (empty)                 ||
| |                ( ) Not on the label   ||
| +---------------------------------------+|
| +- Ask the Label Reader to correct it --+|
| | What is wrong?                        ||
| | [ e.g. brand is Polymaker           ] ||
| | [ Ask the Label Reader ]              ||
| +---------------------------------------+|
| +- Revisions  1 ------------------------+|
| | Revision 1, 2026-11-12 14:09, by hand:||
| | Empty spool weight 150 -> 140 g       ||
| | [ Undo revision 1 ]                   ||
| +---------------------------------------+|
+------------------------------------------+
```

Data: GET `history/<id>`. Header: back link "Recently added"; icon buttons "Newer addition" and "Older addition"
(chevrons; aria-disabled at the ends); title "<Brand> <Name>" with "x<n>"; facts line (time, source, state, spools);
when the record has a reader: "Label Reader: <engine> · <model>" in `--muted`.

**Photos.** Thumbnails 96 px in a wrapping grid. Tapping one opens the photo viewer dialog: full-width photo,
"Photo 1 of 2", "Previous" and "Next" icon buttons, swipe left and right, "Close". Photos are never inverted in
dark.

**Fields.** One group per saved item, headed "Spool 214" or "Spools 212, 213" with the line "A change applies to all
of them." Fields in four groups, label left (`--muted`) and value right; units in `--mono`; empty values show
"(empty)"; confidence marks as in 4.5:

| Group | Fields |
|---|---|
| Identity | Brand · Name · Material · Colour (swatch and hex) · Line |
| Weights | Net weight · Empty spool weight · Density |
| Temperatures | Nozzle · Bed · Nozzle range (placeholder "190-230") · Bed range |
| Other | Price per kg |

"Edit by hand" (pencil) turns the values into inputs in place (same rules and error texts as 4.5; ranges: "Enter a range
like 190-230."). The group footer then shows "Cancel" and "Save changes" (filled). Only changed fields are sent:
POST `history/<id>/apply` `{item, values}`. Results in the footer: "Saving…"; ok "Saved 2 changes: Name, Empty spool
weight."; "Nothing changed." when no field differs; then, from the Hub, "The spools now use filament <id>." (with
"(new)" when it was created) and "Filament <ids> has no spools left; it was not deleted." The record's state becomes
"Edited by hand". Leaving with unsaved edits asks (3.5).

**Ask the Label Reader to correct it.**

| Control | Text | Endpoint |
|---|---|---|
| Field | label "What is wrong?", placeholder "e.g. brand is Polymaker", helper "The Label Reader reads the photos again with your note and suggests changes. Nothing changes until you accept." | |
| "Ask the Label Reader" | default button; aria-disabled with "Say what is wrong first." while the field is empty | POST `history/<id>/revise` `{item, note}` |
| Waiting | working shape and "Asking the Label Reader… (up to a minute)" | |
| Proposal | the before-and-after change list (02-components 7.9) on `--accent-soft` with an `--accent-text` outline: "Proposal: <n> changes" then one row per change: field name, old value struck through, arrow (read as "becomes"), new value (600); or "The Label Reader changed nothing." When the record has no photo: `--muted` "No photo was kept for this record: the Label Reader worked from the saved values and your note." | |
| "Accept" | filled | POST `history/<id>/apply` `{proposal}`; result "Accepted. 2 fields changed; revision 2 keeps the old values." State becomes "Revised by AI". |
| "Discard" | default | nothing is sent; line "Proposal discarded. Nothing changed." |

When the Label Reader is off (`ai` false in the list, or 409 `ai_off`) the group shows only: info circle
"The Label Reader is switched off. Correct by hand, or switch it on in Features on the Hub page."

**Revisions.** One row per revision, oldest first: "Revision <n>, <time>, by hand|by AI: <field old → new; …>" with
the note when there is one. Undone revisions are struck through with "(undone)" (02-components 7.10). The newest revision that is
not undone carries "Undo revision <n>" (undo icon): POST `history/<id>/undo` `{revision}`; result "Revision 1 undone.
<Field> is <value> again." (e.g. "Empty spool weight is 150 g again."; with several fields, one sentence each) plus
the filament lines above. Empty: "No revisions. Corrections by hand or by the Label Reader appear here."

### 7.3 Errors

The Hub's history errors carry a code; the line shows the Hub's text. A record that no longer exists (the oldest are
dropped as new ones arrive): "This record is no longer kept. Only the newest <keep> are." with "Back to
Recently added".

### 7.4 On the public address

Recent is dimmed in the bottom bar and the page shows: clock icon, "Recently added is on the home address only." and
"Open Spoolwarden at its home address on the home network to check and correct recent additions."

---

## 8. Slicer presets (`#presets`)

Shows filaments that have no preset line, attaches them to a line or starts one, and builds the presets. Reached from
More (and from the Add result). Code today: `presetsTab` in `app.js`.

```
+------------------------------------------+
| Slicer presets                           |
| New filaments need a preset line before  |
| a build covers them. Slicer Sync on the  |
| PC installs a build by itself the next   |
| time the slicers are closed.             |
|                                          |
| +---------------------------------------+|
| | Last build    2026-11-12 03:10        ||
| | Installed     2026-11-11 22:40        ||
| | ! Waiting for Slicer Sync on the PC   ||
| | 14 lines                              ||
| | [ Build presets now ]                 ||
| +---------------------------------------+|
|                                          |
| Filaments without a preset line  2       |
| +---------------------------------------+|
| | Overture TPU Blue                     ||
| | TPU . F61                             ||
| | Add to the line                       ||
| | [ Overture TPU                  v ]   ||
| | [ Add to line ]                       ||
| | > Or start a new line                 ||
| +---------------------------------------+|
+------------------------------------------+
```

| Part | Content | Endpoint |
|---|---|---|
| Status group | "Last build" and "Installed" times (`--mono`, or "Never"); "Waiting for Slicer Sync on the PC" (triangle) when the Hub says so; "<n> lines"; the Hub's problems (octagon lines) and note | GET `presets` |
| "Build presets now" | filled; while building "Building presets… (a minute or two)"; then the status reloads and the inline result shows the summary and the Hub's text (3.2) | POST `generate` |
| Filament card | "<Brand> <Name>", `--muted` "<Material> · F<id>" | |
| Add to a line (when the brand has lines) | select "Add to the line" (the brand's lines) and button "Add to line"; result "Adding…", then the card leaves the list with the toast "Added to <line>." | POST `line_add` `{line, ids: [id]}` |
| New line (a disclosure: "Or start a new line" when lines exist, "Start a new line (new brand or product line)" when none) | "Line name" (prefilled "<Brand> <name without its last word>", helper "Brand and line, e.g. Polymaker PolyTerra PLA"); "Find a parent" (prefilled with the material; changing it searches again); "Orca Slicer parent" (select, default "Generic <material>"); "Bambu Studio template" (select); "Create line" (filled within the disclosure, the card's only filled button: while it is open "Add to line" is default); result "Creating…", then the card leaves the list with the toast "Line <name> created." | GET `parents?q=` (on first opening), POST `line_new` `{name, vendor, ids, orca_parent, bs_template}` |

Empty: filled circle "Every filament has a preset line." Errors per card in a line under its buttons.

When the Slicer presets Feature is off, the More row and the page are dimmed and the page shows "Slicer presets is
switched off" and "Switch it on in Features on the Hub page." with "Open the Hub page" (home address
only).

---

## 9. More and Settings

### 9.1 The More sheet

```
+------------------------------------------+
| More                                 [x] |
| [=] Slicer presets                     > |
|     2 filaments without a preset line    |
| [*] Settings                           > |
|     Appearance, theme, print alerts      |
| [+] Add to Home Screen                 > |
|     Open Spoolwarden like an app         |
| [^] Open the Hub page                  > |
|     Features, settings, backups          |
+------------------------------------------+
```

Rows are 56 px tall, icon, name (`--fs-b`, 600), a one-line live summary (`--muted`) and a chevron. "Add to Home
Screen" is shown only when the page is not already running from the home screen. "Open the Hub page" is shown only on
the home address and opens the Hub page in the browser (a new tab when installed). The row of the current place has
`aria-current="page"`.

### 9.2 The Settings sheet

A sheet on phones with the address `#settings` (2.4), opened over the last place; a page on tablets.

```
+------------------------------------------+
| Settings                             [x] |
|------------------------------------------|
| Appearance                               |
| [ Light    | Dark     | System    ]      |   sun, moon, half-circle icons
| Saved on this device: Dark.              |
|------------------------------------------|
| Theme                                    |
| +-----------------+ +-----------------+  |
| | (o) Console     | | ( ) Workbench   |  |
| | Dense and       | | Calm cards      |  |
| | technical       | |                 |  |
| +-----------------+ +-----------------+  |
| +-----------------+ +-----------------+  |
| | ( ) Palette     | | ( ) Panes       |  |
| | Colourful and   | | Simple lists    |  |
| | roomy           | |                 |  |
| +-----------------+ +-----------------+  |
| New phones start with the Hub's theme    |
| for new devices.                         |
|------------------------------------------|
| Print alerts on this phone               |
| (o) On: this phone gets print alerts.    |
| Notify this phone                  [on]  |
| [ Send a test alert ]                    |
|------------------------------------------|
| This Hub                                 |
| Workshop                                 |
| https://192.0.2.10:8710/intake           |
| [ Open the Hub page ]                    |
+------------------------------------------+
```

The segmented control takes the full content width; each theme tile is a radio target at least 44 px high.

| Group | Content |
|---|---|
| Appearance | The wide segmented control "Light / Dark / System" with sun, moon and half-circle icons (F5). Applies at once; line "Saved on this device: <choice>." |
| Theme | Four preview tiles in a two-by-two grid (F6.2): Console "Dense and technical", Workbench "Calm cards", Palette "Colourful and roomy", Panes "Simple lists". A radio group; choosing applies at once, no reload, no save button; line "Saved on this device: <choice>." Helper: "New phones start with the Hub's theme for new devices." |
| Print alerts on this phone (only when print alerts are offered, `data-push`) | Status: "Off" (hollow circle), "On: this phone gets print alerts." (filled circle), "Notifications are blocked for this site. Allow them in the phone's settings." (triangle), or "This browser cannot receive print alerts. On iPhone, add Spoolwarden to the Home Screen first." (info) with the button "Add to Home Screen". Toggle "Notify this phone" (on: GET `push/key` then POST `push/subscribe`; off: POST `push/unsubscribe`). Button "Send a test alert" (POST `push/test`; "Sent." or the Hub's "wait <n> s between test alerts"). |
| This Hub | Hub name; the address this page is using (`--mono`); on the home address "Open the Hub page". |

The alert itself (from the service worker) has the Hub's title (default "Printer"), body and tag; tapping it brings
an open Spoolwarden window forward or opens the web app.

---

## 10. Home screen, offline and "Cannot reach the Hub"

### 10.1 Installing to the home screen

- **iPhone (Safari).** "Add to Home Screen" (More, and the print-alerts group) opens the sheet "Add Spoolwarden to
  the Home Screen" with three numbered steps: "1. Tap Share in Safari's toolbar (the square with an arrow)." "2.
  Choose Add to Home Screen." "3. Tap Add." and the line "Print alerts on iPhone work only from the Home Screen."
  Button "Done".

```
+------------------------------------------+
| Add Spoolwarden to the Home Screen   [x] |
|------------------------------------------|
| 1  Tap Share in Safari's toolbar (the    |
|    square with an arrow).                |
| 2  Choose Add to Home Screen.            |
| 3  Tap Add.                              |
|                                          |
| (i) Print alerts on iPhone work only     |
|     from the Home Screen.                |
|------------------------------------------|
|                          [    Done    ]  |
+------------------------------------------+
```

- **Other browsers that offer installing** (`beforeinstallprompt`): the More row reads "Install app" and calls the
  browser's own install prompt directly.
- Hidden when running installed (`display-mode: standalone`, or `navigator.standalone` on iPhone).
- Installed name and icon: "Spoolwarden" with the Spoolwarden mark; it opens in standalone mode on the last place.
  The status bar follows the active appearance through two `theme-color` meta tags (one per `prefers-color-scheme`,
  values `--surface`), rewritten by the appearance script when Light or Dark is forced (F5). The manifest's colours
  follow the active appearance too (F5): the Hub serves two manifests with the same name, icons and start address,
  one with the light and one with the dark `--surface` as `theme_color` and `background_color`. The page links the
  one matching the system setting, and the appearance script (F5) points the `<link rel="manifest">` at the light or
  dark one whenever the active appearance changes, before the browser offers to install.

### 10.2 The app opens without the Hub

A service worker (`sw.js`, scope the web app's path) keeps a copy of the page, its stylesheet, its scripts, the icon
and the manifest, under a cache named after the web app's version. Pages load network first and fall back to the
copy; requests to the Hub's `api` are never cached. When a new version is found the new copy is used on the next
load (no prompt). The same worker keeps handling print alerts.

### 10.3 "Cannot reach the Hub"

When a request gets no answer, or the page was loaded from the copy:

```
+------------------------------------------+
| [mark] Spoolwarden        [Offline] [(o)]|
|------------------------------------------|
| [wifi-off] Cannot reach the Hub.         |
| Retrying every 10 s.        [ Try now ]  |
+------------------------------------------+
```

- A banner (02-components 8.8) directly under the top bar on `--warn-soft` with the wifi-off icon and the text (read
  out as "Needs a look: Cannot reach the Hub. Retrying every 10 s."), and the "Offline" chip in the top bar.
- When the phone itself has no network (`navigator.onLine` false): "This phone has no network. Your draft is
  kept on this phone."
- Every group keeps its last data with the line "Last update <age>: the Hub did not answer." Buttons that need the
  Hub get `aria-disabled` and the reason "Needs the Hub." Add spools keeps working for photos, cards and fields
  (4.7); "Read labels" and "Preview" say "The Hub cannot be reached."
- Retries every 10 s while the page is visible; "Try now" retries at once.
- When the Hub answers again: the banner goes, a toast says "Connected to the Hub again.", and the page reloads its
  data (inputs and drafts are kept).

---

## 11. The refusal page and the sign-in page

These two pages are the exception to the tab title `<Page title> · <Hub name>` (2.4): the refusal page is served
outside the home network and shows no Hub data, so its title is "Spoolwarden"; the sign-in page's title is
"Spoolwarden sign-in" (11.2).

### 11.1 Refusal page (outside the home network)

Served instead of the web app, with status 403, to any address outside the home network. No navigation, no data.
It uses four files and nothing else: the appearance script and three stylesheets (the token stylesheet, the shared
component stylesheet and the web app's own stylesheet). So that a refused phone can load them, these four answer
every address and every Host name. They are fixed files that hold no data, no name and no setting of the Hub, are
served for reading only, and set no cookie. Every other file of the web app (its scripts, the string catalogue, the
API) stays on the home network only; the refusal page loads no script but the appearance script and its texts are
written into the page by the Hub.

```
+------------------------------------------+
|                                          |
|   [mark] Spoolwarden                     |
|                                          |
|   Only on the home network               |
|   Spoolwarden only works on the home     |
|   network. Connect this phone to the     |
|   home Wi-Fi and open the page again.    |
|                                          |
|   [ Try again ]                          |
|                                          |
+------------------------------------------+
```

Content column `min(30rem, 100vw - 2 * var(--s4))` (the dialog limit of 02-components 1.2), centred, padded
`--s5`. Heading `--fs-xl`. When the request came over IPv6, the Hub's
IPv6 hint follows as a second paragraph. When the Hub refuses the address the page was opened at (3.6), the same
page shows the heading "Not at this address" and the Hub's refusal text as its paragraph. "Try again" is a link
styled as a button that reloads the page. API
requests from outside the home network keep their 403 JSON answer.

### 11.2 Sign-in page (`/login`)

The page a Claude connector opens to ask the owner's permission. Home network only. It uses the web app's
stylesheet (no styles inside the page) and the appearance script. Same column as the refusal page (11.1); no
navigation.

```
+------------------------------------------+
|                                          |
|   [mark] Spoolwarden                     |
|                                          |
|   Allow Example Client?                  |
|   It will be able to read and change     |
|   your Spoolman inventory and slicer     |
|   presets.                               |
|                                          |
|   Passphrase                             |
|   [ ************            ] [Show]     |
|   Wrong passphrase.                      |   error line, only after a 401
|                                          |
|   [             Allow                ]   |
|                                          |
+------------------------------------------+
```

| Part | Content |
|---|---|
| Document title | "Spoolwarden sign-in" |
| Heading | "Allow <client name>?" |
| Text | "It will be able to read and change your Spoolman inventory and slicer presets." |
| Field | "Passphrase", password field with a "Show" / "Hide" text button (`field__action`, 44 px high, named "Show passphrase" / "Hide passphrase", 02-components 5.3), focused on load |
| Button | "Allow" (filled, full width) |

| Situation | Text (under the field or in place of the form) |
|---|---|
| Wrong passphrase (401) | under the field: "Wrong passphrase." The field keeps focus, empty, ready to try again. |
| Too many tries (429) | "Too many wrong passphrases. Wait 10 minutes." |
| No passphrase set (503) | "No passphrase is set on the Hub yet. Set one on the Hub page under Settings > Web passphrase, or run `sudo spoolwarden web passphrase` on the Hub." |
| Request expired | "This sign-in request expired. Start again from Claude." |
| Form opened from elsewhere | "This form only works from its own page. Start again from Claude." |
| Outside the home network | "Sign-in is only available from the home network." |

---

## 12. Dialogs that replace the browser's own

No `confirm()` or `prompt()` remains (F12). Every one is a sheet (3.7). Secret fields are `type="password"` with
`autocomplete="off"`, a "Show" / "Hide" text button (`field__action`, 44 px high, 02-components 5.3) named after its
field ("Show Access Code" / "Hide Access Code"; "Show API key" / "Hide API key"), never prefilled, and
cleared when the sheet closes. Destructive buttons are filled `--bad` with `--on-bad` text; the safe choice is on the
left and receives focus first.

### 12.1 Confirmations (today `window.confirm`)

| Sheet title | Body | Buttons (safe, then action) | Opened by | Then |
|---|---|---|---|---|
| Stop the print? | "Stop <job> on <printer>? It cannot be resumed." | "Keep printing" · "Stop print" (danger) | "Stop print" (6.4) | POST `printers/<id>/command` `{action: "stop", confirm: true}` |
| Unload from <slot>? | "Unload <spool name> from <slot>? It goes back to <location or its previous place>. Only the inventory changes; the printer's slot setting stays as it is." | "Cancel" · "Unload" | "Unload" (6.5), after the preview | POST `printers/<id>/slots/<slot>/unload` |
| Put it back on the spool? | "Put <g> g back on the spool? (<job>, <slot>, <time>)" | "Keep" · "Put it back" | "Undo" in Filament used (6.6) | POST `printers/<id>/usage/<entry>/undo` |
| Map the slots of <printer>? | "The printer changes its slot colours briefly and runs a short job with no motion. The colours are put back afterwards." | "Cancel" · "Map slots" | "Map slots" (6.7) | POST `printers/<id>/map` |
| Forget <printer>? | Bambu: "Spoolwarden stops connecting to it and deletes its Access Code. To use it again, add it again." Klipper: "Spoolwarden stops connecting to it and deletes its Moonraker API key, if one is saved." | "Cancel" · "Forget printer" (danger) | "Forget printer" (6.8) | POST `printers/<id>/forget` |

### 12.2 Questions (today `window.prompt`)

| Sheet title | Fields (label · type · helper) | Buttons | Validation texts | Then |
|---|---|---|---|---|
| Rename printer | "Name" · text, prefilled, selected | "Cancel" · "Rename" | "Enter a name." | POST `printers/<id>/edit` |
| Change address: <printer> (Bambu) | "IP address or name" · text `--mono`, prefilled · "e.g. 192.0.2.40 or printer.local"; "Access Code" · secret · "The Hub needs it again when the address changes. On the printer: Settings > Network/LAN > Access Code." | "Cancel" · "Change address" | "Enter the printer's address." · "Enter the Access Code shown on the printer." | POST `printers/<id>/edit` |
| Change address: <printer> (Klipper) | "Address" · text `--mono`, prefilled · "e.g. voron.example or 192.0.2.57"; "Port" · number, prefilled (7125) | "Cancel" · "Change address" | "Enter the printer's address." · "Enter a port from 1 to 65535." | POST `printers/<id>/edit` |
| Replace Access Code: <printer> | "Access Code" · secret · "On the printer: Settings > Network/LAN > Access Code." | "Cancel" · "Replace Access Code" | "Enter the Access Code shown on the printer." | POST `printers/<id>/edit` |
| Forget the certificate of <printer>? | Body "The next connection pins the certificate <printer> shows then. Enter its Access Code to go on."; "Access Code" · secret | "Cancel" · "Forget certificate" (danger) | "Enter the Access Code shown on the printer." | POST `printers/<id>/edit` |
| Moonraker API key: <printer> | "Moonraker API key" · secret | "Cancel" · "Save key" | "Enter the API key." | POST `printers/<id>/edit` |
| Add <model> | Line "Found on the network at <address>."; "Access Code" · secret · "On the printer: Settings > Network/LAN > Access Code."; "Name (optional)" · text, placeholder the model name | "Cancel" · "Add printer" | "Enter the Access Code shown on the printer." | POST `printers/add` |
| Add a Klipper printer | "Address" · text `--mono` · "e.g. voron.example or 192.0.2.57"; "Port" · number, prefilled 7125; "Name (optional)" · text | "Cancel" · "Add printer" | "Enter the printer's address." · "Enter a port from 1 to 65535." | POST `printers/add` |

While a sheet's change is being written its action button shows the working shape ("Saving…", "Connecting to the
printer…"); a refusal appears inside the sheet under the fields, and the typed values (except secrets, which stay
until the sheet closes) are kept.

### 12.3 Sheets added by this design

| Sheet | Section |
|---|---|
| Replace the spools from the last read? | 4.3 |
| Discard this add? | 4.7 |
| Photo viewer (Add spools and Recently added) | 4.3, 7.2 |
| Spool sheet; Mark spool <id> empty? | 5.4 |
| Load into <slot> | 6.5 |
| Map by loading filament | 6.7.1 |
| Leave without saving? | 3.5 |
| More; Settings; Add Spoolwarden to the Home Screen | 9, 10.1 |
| Appearance menu (Light / Dark / System) | 2.2 |

---

## 13. Touch targets

Every target is at least 44 × 44 px (F1, principle 7), with at least `--s2` between neighbouring targets. Targets
that were smaller today, and the other dense spots:

| Target | Size |
|---|---|
| Bottom bar cells | full cell, `--tab` high (60 px plus the bottom safe-area inset), about 78 px wide at 390 px |
| Slot "Load" and "Unload" (today about 35 px) | 44 px high, at least 88 px wide, on their own line under the slot name |
| Remove photo (today 24 px) | 44 × 44 icon button of its own, `--s2` below its 96 px thumbnail, outside the thumbnail's target |
| Photo thumbnails | 96 × 96 px (Add), 96 px (record), 48 px (list, with the whole card as the target) |
| Search result rows, spool rows, printer and record cards | whole row or card, at least `--row` high |
| "Undo" in Filament used, "Undo revision" | 44 px high |
| Checkboxes and toggles ("Sealed only", "Still sealed", "Notify this phone") | the whole 44 px row toggles, not only the box |
| Icon buttons (close, appearance, newer/older, expand) | 44 × 44 px |
| "Show" / "Hide" text buttons in secret fields | 44 px high |
| Segmented control options | 44 px high (hit area extended as F4.3) |
| Colour picker button | 44 × 44 px |

---

## 14. Needs from the Hub

What the design uses that the Hub does not provide to the web app today. Until each exists, the part named in the
right column is left out or falls back as described there.

| Need | Used in | Without it |
|---|---|---|
| Page attributes: Hub name, Hub page address (absent on the public address), Slicer presets on or off, theme for new devices, spool editing available | 2.2, 9, 8, 9.2, 5.4 | Top bar shows "Spoolwarden" alone; "Open the Hub page" is left out; Slicer presets errors are shown as the Hub's text; theme defaults to Console; "Other actions" are left out |
| Label Reader result per item: confidence per field (high, medium, low, not on the label) | 4.4, 4.5 | Only "Estimated" hints (from `estimates`) |
| Label Reader result: which engine (Cloud (Claude) or On this Hub), model and tier | 4.4, 7.2 | The model name from `usage.model` only |
| Add preview with per-item results: existing or new filament, spools to create, location, and problems tied to a field | 4.6 | The Hub's text in a code block |
| Recently added: read confidence and engine per record | 7.1, 7.2 | No "To check" filter, no confidence lines |
| Spool editing for the web app: preview and save a new weight, move to a location, mark empty (the app has this through its own API) | 5.4 | "Update weight", "Move" and "Mark empty" left out; "Load into a printer" stays |
| Filament colour in spool search results (`find`) | 5.3, 6.5 | Rows without a swatch |
| The spool an entry of Filament used was taken from | 12.1 | The "Put it back" sheet names job, slot and time only |
| `sw.js` served whether or not print alerts are on, and the page shell cacheable by it | 10.2 | No offline start; "Cannot reach the Hub" works only while the page is open |
| Manifest and icon: two manifests (light and dark Console `--surface` colours, 10.1) with name and short name "Spoolwarden" and the Spoolwarden mark (180 and 512 px); page title and `apple-mobile-web-app-title` "Spoolwarden"; two `theme-color` meta tags | 10.1 | Installed as "Spools" with today's icon and a dark status bar |
| New wording in the Hub's own texts: the refusal page (11.1); the `no_preset` refusal ("Slicer presets" instead of "the Presets tab"); the busy-stream text; "internal error (see the server log)"; the sign-in page's title and the command it names | 6.4, 11 | Today's wording appears in those places |
| The sign-in page served with the web app's stylesheet instead of styles inside the page | 11.2 | Today's look on that page |
| Optional: the printers list with job progress and slots, so the list needs one request | 6.1 | One state request per printer every 10 s |

---

## 15. Where today's controls went

Every tab, section, control, native dialog and page of the web app as it is before this redesign, and its place in
this design.

### 15.1 Shell and navigation

| Today | Now |
|---|---|
| Top tab bar of buttons (`nav.tabs`), wrapping to two rows | Bottom bar with five destinations (2.1); rail on tablets (2.3) |
| Tab "Add spools" | Bottom bar **Add** (4) |
| Tab "Open spool" | Bottom bar **Spools** (5) |
| Tab "Presets" | More > **Slicer presets** (8) |
| Tab "History" (home address only) | Bottom bar **Recent** (7); dimmed with a notice on the public address (7.4) |
| Tab "Printers" (Printers Feature on) | Bottom bar **Printers** (6); dimmed with a notice when the Feature is off (6.10) |
| `localStorage["tab"]` | `spoolwarden.place` (2.4) |
| `localStorage["printer"]` and the printer select | `spoolwarden.printer` and the printers list (6.1) |
| Hash `#<tab>` (e.g. `#printers` from the Hub page) | Addresses of 2.4; `#open` and `#history` redirect |
| Headings "Add spools", "Open a spool", "Slicer presets", "Intake history", "Printers" | Page titles "Add spools", "Spools", "Slicer presets", "Recently added", "Printers" |
| Page title "Spool intake"; home-screen name "Spools"; fixed dark `theme-color` | "<Page title> · <Hub name>" (2.4); "Spoolwarden"; `theme-color` follows the appearance (10.1) |
| Dark mode from the phone only | Appearance menu in the top bar and Settings (2.2, 9.2) |
| Spinner with text in a `pre` | Working shape in the button and an inline result (3.2, 3.5) |
| Result `pre` with green or red border | Inline result with summary and the Hub's text in a code block (3.2) |
| Error `pre.err`, "HTTP <status>", "internal error (see the server log)" | Error texts of 3.6 |

### 15.2 Add spools

| Today | Now |
|---|---|
| "Existing filament: brand, colour, material" search field | "Find a filament you already have" (4.2) |
| "Search" button | Search icon button in the field, plus search while typing (4.2) |
| Result rows "F<id> <vendor> <name>" (max 60) | Result rows with swatch, name, material, weight, spool count, "F57" (4.2) |
| "No filament matches: use New filament." | "No filament matches. Use New filament." with the button inline (4.2) |
| "New filament (type it in)" | "New filament" (4.2) |
| "Take or choose photos" file input | "Take photo" and "Choose photos" (4.3) |
| Thumbnails with "✕" remove (24 px) | Photo strip, 44 px "Remove photo n of m", photo viewer (4.3, 13) |
| "8 photos at a time" / "<file>: can't read this image" | "8 photos at a time. Remove one to add another." / "<file name>: this image cannot be read. Try another photo." (4.3) |
| Note textarea for Claude | "Note for the Label Reader (optional)" (4.3) |
| "Read labels" | "Read labels", with its reason when not available (4.3) |
| "Claude is reading N photo(s)… (up to a minute)" | "The Label Reader is reading <n> photos… (up to a minute)" (4.3) |
| Tag-tapped line, station-scale line | Tag and scale notices in "What the Label Reader found" (4.4) |
| "Claude asks" card | "The Label Reader asks" (4.4) |
| Usage line "<n> product(s) found · <model>, tokens" | Result, reader line and "Details" (4.4) |
| Item card header: swatch, title, badge "existing filament" / "new filament" | Collapsed spool card: swatch, title, chips "Existing filament F57" / "New filament" (4.5) |
| Card sub-lines "photos …· estimated: …" and price line | "Estimated" hints on fields; price line as the Price per kg helper (4.5) |
| "Vendor" (with vendor list) | "Brand" (4.5) |
| "Material" | "Material" (4.5) |
| "Name (with the colour)" | "Name" with helper (4.5) |
| "Spools" | "Spools" (4.5) |
| "Net g" | "Net weight" (4.5) |
| "Empty spool g" | "Empty spool weight" (4.5) |
| "Density" | "Density" (4.5) |
| "Colour hex" | "Colour" with swatch, hex and picker (4.5) |
| "Lot" | "Lot" (4.5) |
| "Nozzle °C", "Bed °C" | "Nozzle", "Bed" (4.5) |
| "Opened: scale weight g (with spool, blank = full)" | "Weight with spool" (4.5) |
| "Price $/kg" | "Price per kg" (4.5) |
| "Note" | "Note" (4.5) |
| "Still sealed (in its bag or box)" + sealed reason | Toggle with "Label Reader: <reason>" (4.5) |
| "Location" select "Auto: <rule>" | "Location" select "Automatic (<rule>)" (4.5) |
| Density from the material table, empty-spool weight from the vendor list | Same, with "Typical for <material>" / "Filled in from the brand list" hints (4.5) |
| "Remove" | "Remove" with undo toast (4.5) |
| "Check (dry run)" | "Preview" in the action bar (4.6) |
| "Check first; any edit needs a new check." | Action bar status texts (4.6) |
| "Add N spool(s)" (disabled until checked) | "Add <n> spools", with its reason (4.6) |
| "Checking…", "Adding to Spoolman…" | Same words in the action bar (4.6) |
| "Next: presets for new filaments" | "Set up Slicer presets" in the Add result (4.6) |
| Items lost on reload | Unfinished add kept as a draft in `localStorage` (4.7) |
| Label-photo section absent when the Label Reader is off | One-line "off" notice (4.3) |

### 15.3 Open spool

| Today | Now |
|---|---|
| Intro "Tap the spool's tag on a reader, pick the spool, weigh it…, link." | Spools intro (5.1) |
| Tag card "Last tag: <id>" / "No tag read yet: tap one", text, age, reader, scale | "Last tag" group (5.2) |
| "Reading the tag reader…" | "Checking for the last tag…", with skeleton (5.2) |
| "Search: brand, colour, material" + "Search" | Search field, search while typing (5.3) |
| "sealed spools only" checkbox | "Sealed only", remembered (5.3) |
| Result rows "S<id> …" | Spool rows "Spool 214 …" (5.3) |
| "No spools match." | "No spools match." / sealed variant (5.3) |
| Form card "Selected spool" | Spool sheet (5.4) |
| "Gross weight (with spool)" | "Weight with spool" (5.4) |
| "Location" with suggestions | "Location" with suggestions (5.4) |
| "Humidity" | "Box humidity" (5.4) |
| "Check" | "Preview" (5.4) |
| "Link tag and open" (disabled without explanation) | "Link tag and open" with its reasons (5.4) |
| "Searching…", "Checking…", "Linking…" | Working shapes and the same verbs (5.3, 5.4) |
| (new) | Update weight, Move, Mark empty, Load into a printer (5.4) |

### 15.4 Presets

| Today | Now |
|---|---|
| Intro text | Intro naming Slicer Sync (8) |
| Status line "Last build · installed · waiting for the desktop · n lines" | Status group (8) |
| "Every filament has a preset line." | Same (8) |
| "Filaments without a preset line" cards | Same heading and cards (8) |
| "Add to the line" select + "Add to line" | Same (8) |
| "…or a new line" / "New line (new brand or product line)" | "Or start a new line" / "Start a new line (new brand or product line)" (8) |
| "Line name '<Brand> <Line>'" | "Line name" with helper (8) |
| "Search parents" | "Find a parent" (8) |
| "Orca parent" | "Orca Slicer parent" (8) |
| "Bambu Studio template" | Same (8) |
| "Create line" | Same (8) |
| "Build presets now", "Building presets… (a minute or two)" | Same (8) |
| "Adding…", "Creating…" | Same, in the card's line (8) |
| Tab always shown; every request fails with "the presets module is off on this server" | Dimmed More row and a "switched off" page (8) |

### 15.5 History

| Today | Now |
|---|---|
| "The newest <keep> additions, with their photos…" | Recently added intro (7.1) |
| "Nothing added since the history started." | "Nothing has been added since the history started." (7.1) |
| Record card with photo, names, time, state word | Record card (7.1) |
| Photo click toggles a larger size | Photo viewer dialog (7.2) |
| "Open" button | The whole card (7.1) |
| Detail photos | Photos group (7.2) |
| "Spool <ids>: a change applies to all of them" | Panel heading and line (7.2) |
| Inputs Brand, Name, Material, Colour (hex), Net g, Spool g, Density, Nozzle °C, Bed °C, Nozzle range, Bed range, Price per kg, Line | The same fields in four groups; "Spool g" is now "Empty spool weight" (7.2) |
| "Save changes", "Saving…", "Saved.", "Nothing changed." | "Edit by hand", then "Save changes" with its results (7.2) |
| Textarea "e.g. brand is Polymaker" | "What is wrong?" (7.2) |
| "Ask the AI to correct it" | "Ask the Label Reader" (7.2) |
| "Asking the AI… (up to a minute)" | "The Label Reader is reading it again… (up to a minute)" (7.2) |
| "The AI suggests:" / "The AI changed nothing." / no-photo note | "The Label Reader suggests:" / "The Label Reader changed nothing." / same note (7.2) |
| "Accept", "Discard" | Same (7.2) |
| "Label reading is off on this server: edit by hand." | "The Label Reader is switched off. Correct by hand, or switch it on in Features on the Hub page." (7.2) |
| Revision log lines | Revisions group (7.2) |
| "Undo revision <n>", "Undone." | Same, "Revision <n> undone." (7.2) |
| "The spools now use filament <id> (new)", "Filament <ids> has no spools left; it was not deleted." | Same lines (7.2) |

### 15.6 Printers

| Today | Now |
|---|---|
| Printer `<select>` | Printers list (6.1) |
| "No printer is set up on the server yet: add one under Manage printers." | List empty state (6.1) |
| Header card: name, state pill, job, progress, temperatures | Status group with words for every state (6.3) |
| HMS lines "HMS <code>", notes | "Printer alert <code>" lines, notes (6.3) |
| Connection line, "Reconnecting…" | Stream line (6.3) |
| "Pause" | "Pause" (6.4) |
| "Resume" | "Resume" (6.4) |
| "Stop print" + `confirm("Stop this print? It cannot be resumed.")` | "Stop print", set apart, + sheet "Stop the print?" (6.4, 12.1) |
| "Light on" / "Light off" | "Turn the light on" / "Turn the light off" (6.4) |
| "Sending…", "Done.", "The printer said no: <reason>" | Inline result under the controls (6.4) |
| "Show camera" / "Hide camera", camera errors | Same buttons, camera box and texts (6.4) |
| Filament: AMS cards, slot rows, "No AMS units reported." | Slots (6.5); "The printer reports no slots." |
| Slot "Load" | "Load", 44 px (6.5) |
| Slot "Unload" + `confirm("Unload <name> from <slot>? It goes back to <where>.")` | "Unload" + sheet "Unload from <slot>?" (6.5, 12.1) |
| Load picker card "Load into <label>" | Load sheet (6.5) |
| "Use the last tapped tag", its two messages | Same (6.5) |
| Load picker search + "Search" | Search field in the load sheet (6.5) |
| "Pick a spool: tap its tag on a reader, or search." | Same (6.5) |
| Plan lines (Load, Preset, Nozzle, goes back, problems) | Plan in the load sheet (6.5) |
| "Load" / "Cancel" | Same (6.5) |
| "Loaded into <slot>" / "Sent to <slot>" + "hasn't shown the change yet" | Same, in the slot's line and a toast (6.5) |
| Usage rows with "Undo" + `confirm("Put <g> g back on the spool?")` | Filament used + sheet "Put it back on the spool?" (6.6, 12.1) |
| "Nothing recorded in the last days." | "Nothing used in the last 7 days." (6.6) |
| Slots status line, next step, problems, stale note, notes | Slot mapping group (6.7) |
| "Collect a report" + download link text | "Collect a report", "Download report" (6.7) |
| "Re-map slots" / "Mapping…" + `confirm("Re-map the slots? …")` | "Map slots" + sheet "Map the slots?" (6.7, 12.1) |
| "Map by loading filament" (inline card) | Sheet "Map by loading filament" (6.7.1) |
| Manual map: Hub text, question, "Yes" | Same (6.7.1) |
| "No, I loaded" + select + "Save that" | Same (6.7.1) |
| Nozzle select "right nozzle" / "left nozzle" | "Nozzle": "Right nozzle" / "Left nozzle" (6.7.1) |
| Slot select "The slot it is in" + "Save (not checked by the printer)" | Same (6.7.1) |
| "The printer reports a change; waiting for it to settle…" | Same (6.7.1) |
| "Skip <position>", "Stop" | Same (6.7.1) |
| Position list (confirmed / entered by hand) | Positions with status shapes (6.7.1) |
| Share offer, "Yes, how do I share it?", "No thanks" | Same (6.7.1) |
| Alerts: "Notify this phone", "Stop", "Test" and their messages | Settings > "Print alerts on this phone": toggle "Notify this phone", "Send a test alert" (9.2) |
| "Add or change printers" button | Gone: each printer's settings are on its page (6.8); adding is on the list (6.1) |
| Manage text (Bambu shows up by itself…; "Anyone on the home network can use this page."; read-only from the public address) | List empty state (6.1), the Printer settings description line and the read-only line (6.8) |
| Manage rows "name · model · address · state" / "no address yet" / "seen on the network, not added" | Printer settings (6.8), with "No address yet"; "Found on the network, not added yet" (6.1) |
| "Rename" + `prompt` | "Rename" + sheet "Rename printer" (12.2) |
| "Address" + `prompt` (chained) | "Change" + sheet "Change address" (12.2) |
| "Access Code" + `prompt` | "Replace" + sheet "Replace Access Code" (12.2) |
| "Forget certificate" + `prompt` for the Access Code | "Forget" + sheet "Forget the certificate?" (12.2) |
| "API key" + `prompt` | "Set" / "Replace" + sheet "Moonraker API key" (12.2) |
| "Forget" + `confirm("Forget <name>? …")` | "Forget printer" + sheet "Forget <printer>?" (12.1) |
| "Add" (found Bambu) + `prompt` for Access Code and name | "Add" + sheet "Add <model>" (12.2) |
| "Add a Klipper printer" + `prompt` for host, port, name | "Add a Klipper printer" + sheet (12.2) |
| Manage result `pre` | Inline result under Printer settings (6.8) |
| Hub refusal texts (offline, no reply, busy, slot in use, …) | Inline results, with "Open Slicer presets" for the no-preset refusal (6.4) |
| Camera and stream limits (4 views, 12 streams) | Camera "too many views" and the stream line (6.4, 6.3) |

### 15.7 Other pages

| Today | Now |
|---|---|
| Refusal page "Spool intake only works on the home network." (+ IPv6 hint) | Refusal page (11.1) |
| 403 refusal text for an address the Hub does not accept (web app served by the Hub itself) | Refusal page "Not at this address" with the Hub's text (3.6, 11.1) |
| `/login` "Allow <client name>?", "Passphrase", "Allow", its messages, title "Filament MCP sign-in" | Sign-in page (11.2) |
| No offline use | Service worker copy and "Cannot reach the Hub" (10.2, 10.3) |
| Install guide "Spools" on the home screen | "Add to Home Screen" sheet (10.1) |

