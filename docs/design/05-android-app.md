# Spoolwarden design: the Android app

This document specifies every screen, sheet and dialog of the Spoolwarden Android app in the default theme,
**Console**: layout, components, exact texts, states and navigation. It builds on `01-foundations.md` and does not
repeat it; section numbers in the form "F4.1" point into the foundations. Component names are the ones of
`02-components.md`; how tokens become a Material 3 theme is in `08-platform-mapping.md`. Example data uses the
documentation ranges (`192.0.2.x`, `printer.local`, `*.example`) and the fake printers and spools of the mockups.

Contents: 1 Baseline · 2 App shell · 3 Shared parts and states · 4 Pairing · 5 Home · 6 Add spools ·
7 Spools and the spool screen · 8 Add a line to the Filament Catalog · 9 Printers · 10 Recently added ·
11 Slicer presets · 12 Settings · 13 App updates · 14 Accessibility · 15 Strings and wording ·
16 Needs from the Hub · 17 Where today's screens and controls went

---

## 1. Baseline

| Item | Value |
|---|---|
| Toolkit | Jetpack Compose, Material 3, one `MainActivity`, edge to edge. No XML layouts. |
| Android versions | minSdk 29, target and compile SDK as today. |
| Theme | `SpoolwardenTheme(look, appearance)` (F6.2) wraps everything. It supplies the Material 3 `ColorScheme`, `Typography`, `Shapes` and the Console density from the tokens of F4. Dynamic colour is off. No component uses a literal colour. Sizes are the tokens of F4 read as dp, and fixed dimensions are `size` entries read through `SpoolwardenTheme.sizes` (listed below this table); status colours come from `--ok`, `--warn`, `--bad`, `--info` and their `-soft` grounds, never from Material's `primary`/`error` alone. |
| Window size classes | Compact (phone), medium (tablet, small window), expanded (large tablet, desktop window) as in F7. Read with `currentWindowAdaptiveInfo()` (or the version of it the Compose release in use provides). Rotation and multi-window are supported on every screen; state survives both (view models plus `SavedStateHandle`). |
| Navigation | Navigation Compose, one `NavHost`, type-safe routes (`@Serializable` route classes). Every screen in this document is a destination; sheets and dialogs that carry their own state are `dialog` or bottom-sheet destinations. Nothing is navigated with local `remember` state. |
| Icons | Spoolwarden's own vector drawables (F10). No Material icon library. |
| Strings | Every user-visible text is in `res/values/strings.xml` (section 15). |
| Units on screen | dp for layout; `sp` derived from the type tokens so the phone's font size setting scales all text. |
| App label | "Spoolwarden". |
| Launcher icon | An adaptive icon (`android:icon` and `android:roundIcon`): foreground the Spoolwarden mark (a spool seen from the side inside a ring) drawn in the icon style of F10 in `--on-accent`, inside the adaptive icon's safe zone; background Console's light `--accent`; a monochrome layer of the same mark for themed icons. Files and colours: `08-platform-mapping.md` section 11. |
| Threads | No file, database or network read on the main thread: assets (the Licences texts of 12.5 included), DataStore and every Hub request are read in a coroutine on `Dispatchers.IO` (`produceState`, or the screen's view model) and the screen shows a skeleton until they arrive. |

Spacing, size and radius values in this document are the tokens of F4.3 read as dp: `--s1` 4 dp, `--s2` 8 dp,
`--s3` 12 dp, `--s4` 16 dp, `--s5` 24 dp, `--s6` 32 dp, `--s7` 48 dp; `--r-s` 4 dp, `--r` 6 dp, `--r-l` 10 dp;
`--top` 52 dp (plus the status bar inset). The bottom bar and the rail keep Material's own sizes (80 dp high, 80 dp wide, plus the insets), not `--tab` and `--rail`: an accepted difference of `08-platform-mapping.md` section 14.

Font weights are `--fw-text`, `--fw-label` and `--fw-title` (F4.2); no other weight is used.

Fixed dimensions that are not steps of the space scale are entries of the `size` group (F4.3) and components read
them through `SpoolwardenTheme.sizes` (`08-platform-mapping.md`); no component writes them inline. "Existing" entries
are in `tokens.json` today; "new" entries are `size` entries this app needs, added to every theme with the values
given here (the web reads the same entries where it draws the same part). The other themes scale with their type
and density: Workbench and Panes one step roomier than Console where a size holds text, Palette larger again, and
its swatches larger still because the spool colour is that theme's main mark. Collection, settings and slot rows use `ListItem`'s own minimum height (56 dp), the
accepted difference of `08-platform-mapping.md` for rows; it is not a size entry. Selection outlines (2 dp) are border
widths, not sizes.

| `size` entry | Console | Workbench | Palette | Panes | Status | Used for |
|---|---|---|---|---|---|---|
| `hairline` | 1 dp | 1 dp | 1 dp | 1 dp | existing | Hairlines between rows and around panels |
| `thumb` | 96 dp | 96 dp | 96 dp | 96 dp | existing | Photo thumbnails in strips (6.2, 10.2) |
| `drawer` | 420 dp | 420 dp | 420 dp | 420 dp | existing | Minimum width of the detail pane of `ListDetailPaneScaffold` (2.1) |
| `label-col` | 118 dp | 128 dp | 144 dp | 128 dp | new | Label column of the key-value list on medium width (3.1) |
| `thumb-s` | 48 dp | 56 dp | 64 dp | 48 dp | new | Photo thumbnails in Recently added rows (10.1) |
| `swatch-row-w` | 16 dp | 20 dp | 28 dp | 20 dp | new | Width of the swatch in rows (3.1, 7.2) |
| `swatch-row-h` | 22 dp | 20 dp | 28 dp | 20 dp | new | Height of the swatch in rows (3.1, 7.2) |
| `swatch-head` | 40 dp | 44 dp | 64 dp | 40 dp | new | Swatch in the spool header, square (3.1, 7.2) |
| `empty-mark` | 56 dp | 64 dp | 80 dp | 56 dp | new | Circle of the empty state (3.1) |
| `chip` | 32 dp | 32 dp | 40 dp | 32 dp | new | Height of the connection chip (hit area still 48 dp) |
| `slot-label` | 32 dp | 36 dp | 40 dp | 36 dp | new | Slot label column (9.5) |
| `port-field` | 120 dp | 120 dp | 136 dp | 120 dp | new | Port field width (4.5) |
| `column-max` | 560 dp | 600 dp | 640 dp | 560 dp | new | Maximum width of single-column content on medium and expanded width (4, 5) |
| `preview-max` | 400 dp | 400 dp | 400 dp | 400 dp | new | Camera preview width on medium and expanded width (6.2) |
| `list-pane` | 360 dp | 360 dp | 400 dp | 360 dp | new | Minimum width of the list pane of `ListDetailPaneScaffold` (2.1) |

In `tokens.json` the values are written in px (`"label-col": "118px"`); 1 px in the file is 1 dp in the app. In
Palette the row swatch is drawn as a ring (the spool seen from the side); in the other themes it is a rounded
rectangle with `--r-s` corners.

---

## 2. App shell

### 2.1 Structure

The app has two graphs:

- **Pairing graph** (section 4): full screen, top app bar, no bottom navigation. Shown when no Hub is stored, and
  when the person chose "Pair again" or "Review the certificate" after the Hub stopped accepting this phone or its
  certificate changed (2.7). Opened that way it sits on top of the main graph, which keeps its screens and anything
  typed on them.

At start the app reads the stored pairing and appearance from DataStore before it draws anything: the system splash
screen (`installSplashScreen()` with `setKeepOnScreenCondition`) stays on the `--bg` ground until both are read,
then the app opens `home` when a Hub is stored, else `pair` (or `pair/network-access`, 2.7). No other first-launch
screen exists.
- **Main graph**: `NavigationSuiteScaffold` (Material 3 adaptive navigation suite) around a `Scaffold`. The suite
  draws a `NavigationBar` on compact width and a `NavigationRail` on medium and expanded width, with the same five
  destinations (2.3). Each destination keeps its own back stack (`saveState` / `restoreState`).

```
Compact (phone)                         Medium / expanded (tablet)
+--------------------------------+      +------+-------------------------------------------+
| <  Title        (o) Connected ☼|      | logo | Title                 (o) Connected   ☼   |
+--------------------------------+      +------+-------------------------------------------+
|                                |      | Home |                    |                      |
|  content, one column,          |      | Spool|  list pane          |  detail pane         |
|  16 dp gutters                 |      | Print|  (expanded only:    |  (expanded only,     |
|                                |      | Recen|   360 dp min)        |   420 dp min)        |
|                                |      | Setti|                    |                      |
+--------------------------------+      |      |                    |                      |
| Home Spools Printers Recent Set|      +------+-------------------------------------------+
+--------------------------------+
```

On expanded width the Spools, Printers and Recently added destinations use `ListDetailPaneScaffold`
(Material 3 adaptive): the collection on the left, the selected thing's screen on the right. On compact and medium
width the detail screen replaces the list. This is how the Console `detail = inline` profile (F6.1) reads on
Android: detail opens next to its list when there is room, and as its own screen when there is not.

### 2.2 Top app bar

Component: **top bar** (`02-components.md`), built from Material 3 `TopAppBar` with
`TopAppBarDefaults.pinnedScrollBehavior()`. Height `--top`, ground `--surface`, a 1 dp `--border` hairline at the
bottom (no shadow, `--e0`). The bar is present on every screen except the two full-screen camera surfaces (QR
scanner 4.4, photo viewer 10.5), which draw their own close button.

| Slot | Content | Material 3 |
|---|---|---|
| Navigation icon | Back arrow on every screen that is not a destination root. Absent on the five roots and on the first pairing screen. Pressing it does exactly what system Back does (2.5). | `IconButton` with the "chevron" icon pointing left, content description "Back" |
| Title | The place, not the product (F9): "Home", "Spools", "Printers", "Recently added", "Settings", or the thing's name ("Workshop X1"). One line, ellipsis at the end, `--fs-xl` `--fw-title` on medium and expanded, `--fs-l` `--fw-title` on compact. On Home the title is "Home" with the Hub's name under it in `--fs-s` `--muted` ("Workshop hub"). | `TopAppBar` `title` |
| Connection chip | The Hub connection state as shape plus word (2.4). Tapping it opens the **Hub connection sheet** (2.4). Shown on every screen of the main graph. On the pairing graph it is replaced by nothing. | `AssistChip` with a leading status shape, `chip` tall, hit area 48 dp |
| Appearance icon | One icon button showing the current choice (sun, moon or half-circle). Opens a menu with three items "Light", "Dark", "System", each with its icon and a check mark on the current one. Choosing applies at once (F5). Present on every screen including pairing. | `IconButton` + `DropdownMenu` / `DropdownMenuItem` |
| Overflow | Only where a screen names one ("More actions"). | `IconButton` "more" + `DropdownMenu` |

When the title and the chip do not fit, the title shortens first (ellipsis). The chip never drops its word.

### 2.3 Destinations (bottom navigation and rail)

Component: **bottom bar** and **navigation rail** (F8, `02-components.md` "Navigation"), the same component the web
app uses with its own destinations. `NavigationBar` and `NavigationRail` keep Material's own height and width (80 dp, plus the insets), so their
indicator and label layout stay intact. Active item: `--accent-soft` indicator, `--accent-text` icon and label, label weight `--fw-label`; inactive items
`--muted`. Labels are always shown (`alwaysShowLabel = true`), `--fs-xs`.

| Order | Label | Icon | Root screen | Badge |
|---|---|---|---|---|
| 1 | Home | the Overview section icon | Home (5) | none |
| 2 | Spools | spool | Spools (7.1) | none |
| 3 | Printers | printer | Printers (9.1) | a small warning triangle in `--warn` with the count when a printer has an alert or a certificate problem; content description "Printers, 1 needs a look" |
| 4 | Recent | clock | Recently added (10.1) | none |
| 5 | Settings | the Settings section icon | Settings (12.1) | a dot when an app update is ready; content description "Settings, update available" |

Pressing the destination that is already selected scrolls its root to the top, or, when the person is deeper in
that destination, pops back to its root. Every destination root is one tap away from any screen of the main graph.

A Feature switched off on the Hub never removes a destination (F8): the destination stays in the bar or rail,
dimmed (icon and label drawn like a disabled control, but still selectable; content description "Printers, switched
off"). Printers with the printers Feature off opens a page that says "Printers is switched
off. Switch it on in Features on the Hub page." with the
button "Open the Hub page" (opens the Hub page in the browser, as 12.3).

### 2.4 Hub connection state

The app checks the Hub with `GET api/info` every 20 s while any main-graph screen is in the foreground, and at once
when the app returns to the foreground or the network changes.

The chip shows only words of the status badge vocabulary (`02-components.md` 7.1); what the state means is the
sentence in the sheet.

| State | Shape (F10) and colour | Chip word | Meaning, shown in the sheet |
|---|---|---|---|
| Connected | filled circle, `--ok` | Connected | "Connected to Workshop hub at 192.0.2.10:8710." |
| Not known yet (first check after start) | none: a skeleton of the badge's width (02 7.1, Loading) | none; content description "Hub connection: checking" | "Checking the connection to the Hub…" |
| Offline | hollow circle, `--bad` | Offline | "Cannot reach Workshop hub. Check that this phone is on the home network." |
| Certificate changed | triangle, `--warn` | Needs a look | "The Hub's certificate is not the one this phone paired with." |
| No longer paired | triangle, `--warn` | Needs a look | "This phone is no longer paired with the Hub." |
| Needs local network access | triangle, `--warn` | Needs a look | "Android needs your permission before Spoolwarden can reach the Hub on your network." |

Later checks keep the last known word on the chip while they run.

**Hub connection sheet** (`ModalBottomSheet`, `--r-l` top corners, `--e2`): title "Hub connection", the status
line, then:

| Row | Content |
|---|---|
| Hub | name (`--fs-l` `--fw-title`) and address in `--mono` ("192.0.2.10:8710") |
| Versions | "App 0.5.2 · Hub 0.5.2" in `--mono`; "Hub version not known yet" when it is not |
| Last answer | relative time ("12 seconds ago"); long-press shows the exact time (F2) |
| Action | one button by state: Offline "Try again" (filled; runs the check now, label "Checking…" with a spinner while it runs); Certificate changed "Review the certificate" (filled; opens 4.8); No longer paired "Pair again" (filled; opens the pairing graph); Needs local network access "Allow" or "Open app settings" (filled; as 4.2). Connected: "Hub connection settings" (text button; opens 12.3). |

### 2.5 Routes and Back

| Route | Screen | Graph / tab | Back goes to |
|---|---|---|---|
| `pair` | Pair: start (4.3) | Pairing | leaves the app; when opened with "Pair again" from the main graph, the screen it was opened from |
| `pair/network-access` | Allow local network access (4.2) | Pairing | leaves the app |
| `pair/scan` | QR scanner (4.4) | Pairing | `pair` |
| `pair/address` | Enter the Hub's address (4.5) | Pairing | `pair` |
| `pair/fingerprint` | Check the fingerprint (4.6) | Pairing | the step before it (`pair/address`, or `pair` when the Hub was picked from the found list) |
| `pair/code` | Enter the pairing code (4.7) | Pairing | the step before it (`pair/fingerprint`, or `pair/address` or `pair` when the check is skipped) |
| `pair/certificate/{source}` | Certificate changed / does not match (4.8) | Pairing | for `stored`: the screen it was opened from; otherwise `pair` |
| `pair/settings`, `pair/settings/appearance`, `pair/settings/hub`, `pair/settings/updates`, `pair/settings/licences` | Settings screens 12.1 to 12.5 opened from the pairing overflow (4) | Pairing | `pair/settings`: the pairing step it was opened from; the others: `pair/settings` |
| `home` | Home (5) | Home root | leaves the app |
| `add/{draftId}/photos` | Add spools: photos (6.2) | Home | `home` (draft kept) |
| `add/{draftId}/review` | Add spools: check the spools (6.3) | Home | `add/{draftId}/photos` for the photo path, `home` for the hand path (draft kept) |
| `add/{draftId}/preview` | Add spools: preview (6.5) | Home | `add/{draftId}/review` |
| `add/{draftId}/done` | Spools added (6.6) | Home | `home` (the add stack is cleared) |
| `presets` | Slicer presets (11.2) | Home | `home` |
| `catalog/new` | Add a line to the Filament Catalog (8) | Home | the screen it was opened from; asks first when fields were typed |
| `spools` | Spools: search (7.1) | Spools root | `home` tab |
| `spools/{id}` | Spool (7.2) | Spools | `spools` |
| `spools/{id}/weight` | Update weight sheet (7.3) | Spools | `spools/{id}`; asks first when a weight was typed |
| `spools/{id}/move` | Move sheet (7.4) | Spools | `spools/{id}` |
| `spools/{id}/load` | Load: pick a printer (7.6) | Spools | `spools/{id}` |
| `spools/{id}/load/{printerId}` | Load: pick a slot (7.6) | Spools | `spools/{id}/load`, or `spools/{id}` when the printer step was skipped |
| `spools/{id}/load/{printerId}/{slot}` | Load: preview and load (7.6) | Shared | the slot step, or 9.6 when opened from there; blocked while the load is being written |
| `tag/{uid}` | Tag lookup and "Tag not linked" (7.7) | Shared | the screen that was open when the tag was tapped |
| `tag/{uid}/link` | Link to a sealed spool: find (7.8) | Shared | `tag/{uid}` |
| `tag/{uid}/link/{spoolId}` | Link to a sealed spool: preview, conflict (7.8) | Shared | `tag/{uid}/link` |
| `printers` | Printers (9.1) | Printers root | `home` tab |
| `printers/add/{serial}` | Add a Bambu Lab printer (dialog destination, 9.2) | Printers | `printers` |
| `printers/add-klipper` | Add a Klipper printer (dialog destination, 9.3) | Printers | `printers` |
| `printers/{id}` | Printer (9.4) | Printers | `printers` |
| `printers/{id}/slots/{slot}/pick` | Pick a spool for a slot (9.6) | Printers | `printers/{id}` |
| `printers/{id}/map-by-loading` | Map by loading filament (9.8) | Printers | `printers/{id}`; asks first while a mapping is open |
| `printers/{id}/settings` | Printer settings (9.9) | Printers | `printers/{id}` |
| `recent` | Recently added (10.1) | Recent root | `home` tab |
| `recent/{hid}` | Record (10.2) | Recent | `recent` |
| `recent/{hid}/edit/{item}` | Edit by hand (10.3) | Recent | `recent/{hid}`; asks first when a field changed |
| `recent/{hid}/photos/{n}` | Photo viewer (10.5) | Recent | `recent/{hid}` |
| `settings` | Settings (12.1) | Settings root | `home` tab |
| `settings/appearance` | Appearance (12.2) | Settings | `settings` |
| `settings/hub` | Hub connection (12.3) | Settings | `settings` |
| `settings/updates` | App updates (12.4, 13) | Settings | `settings` |
| `settings/licences` | Licences (12.5) | Settings | `settings` |
| `settings/developer` | Developer (debug builds only, 12.6) | Settings | `settings` |

**Shared** routes are included in the graph of every main destination and are pushed on the stack of the
destination that is selected; the tab does not change, so Back returns to the screen beneath. The same holds for
`spools/{id}` with its sheets and load steps when they are reached from a shared route (a tag that resolves to a
spool, 7.7) or from 9.6: they open on the current stack, and Back from them returns to the screen beneath. Reached
from the Spools search, they sit on the Spools stack as the table says.

Back rules, in this order:

1. A screen that holds unsaved typing asks before leaving (dialog "Leave without saving?", body
   "Your changes to <thing> are not saved." with the screen's subject as <thing>, for example "this printer" or
   "the new catalog line", buttons "Stay" (focused first) and "Leave without saving" (danger)). Add spools never asks:
   it saves its draft on every change (6.1).
2. A screen that is writing something the person cannot safely abandon (a load into a printer, 7.6) ignores Back
   and shows the snackbar "Loading into the printer… wait for its answer."
3. Otherwise Back pops one destination.
4. At the root of Spools, Printers, Recent or Settings, Back selects Home. At the root of Home, Back leaves the app.

The top-bar back arrow follows the same rules. Sheets and dialogs close on Back, on a tap on the scrim, and on
their Cancel button, under rule 1.

Deep links (`spoolwarden://` scheme, opened from any link that uses it; the app itself posts no notifications):
`spoolwarden://printers/{id}`, `spoolwarden://spools/{id}`, `spoolwarden://recent/{hid}`. Opening one builds the
back stack of its tab (root first), so Back from it behaves as if the person had navigated there.

### 2.6 NFC tag taps

While the app is in the foreground it reads NFC tags with reader mode.

| Where the person is | What a tap does |
|---|---|
| Pairing graph | Nothing. |
| Add spools: photos or check-the-spools screen | Attaches the tag to the draft (6.2); no navigation. |
| A load being written (7.6) | Nothing changes; snackbar "Tag read. It opens when loading has finished." The tag opens once the load ends. |
| Pick a spool for a slot (9.6) | Picks the tag's spool for that slot: opens the preview step of 7.6 for this printer and slot on the Printers stack. A tag linked to no spool shows the notice line "This tag is not linked to a spool yet. Search for the spool instead." on 9.6. |
| Anywhere else | Opens `tag/{uid}` on top of the stack of the destination that is selected, without changing the tab (2.5, Shared), so Back returns to the screen that was open. A second tap of the same tag while its screen is open does nothing; a different tag replaces the tag screen. |

A short haptic tick confirms every read. The read itself is announced by TalkBack as "Tag read".

### 2.7 Gating

- Every Hub-backed screen checks the stored pairing. When the Hub answers 401 (no longer paired) or presents a
  different certificate, the app never navigates by itself and never clears a screen: the connection state becomes
  "Needs a look" (2.4), and the screen that made the request shows the Hub notice of 3.4 where the result would have
  appeared, keeping its data and anything typed. Its button ("Pair again" or "Review the certificate") pushes the
  pairing graph on top of the main graph (`pair` with the banner of 4.1, or `pair/certificate/stored`). When pairing
  or trusting succeeds, the pairing graph closes and the person is back on that screen with their typing intact.
- On Android 17 (API 37) and later, if local network access is not granted, the connection state is "Needs
  permission" and every Hub-backed screen shows the notice of 3.3 instead of its content; the pairing graph starts
  at `pair/network-access`.

---

## 3. Shared parts and states

### 3.1 Components used in this app

The component names are those of `02-components.md`. The table says which Material 3 composable draws each one in
the Console theme.

| Component | Material 3 | Console look on Android |
|---|---|---|
| Top bar | `TopAppBar` | 2.2 |
| Bottom bar / navigation rail | `NavigationSuiteScaffold`, `NavigationBar`, `NavigationRail` | 2.3 |
| Page header | `Column` under the top bar | Optional one-line meta row in `--fs-m` `--muted` under the title; actions at the right on medium width, full width under it on compact |
| Form group (02 5.11; Android `SwPanel`; "panel" in this document) | `OutlinedCard` with `--surface` ground, 1 dp `--border`, `--r` corners, no elevation | Header row 48 dp min: title `--fs-l` `--fw-title`, optional count tag, optional actions at the right; body padding `--s4`; optional footer on `--surface-2` with the result line at the left and buttons at the right |
| Collection (table profile) | `LazyColumn` of `ListItem`s separated by `HorizontalDivider` (`--border`) inside a panel | Rows at `ListItem`'s minimum height (56 dp, 1); leading swatch or status shape; headline `--fs-b` `--fw-label`; supporting line `--fs-s` `--muted`, numbers in `--mono`; trailing chevron or one action |
| Detail region | Its own destination; right pane of `ListDetailPaneScaffold` on expanded width | 2.1 |
| Key-value list (02 6.3; "field rows" in this document) | `Row` in a panel | Label `--fs-m` `--muted` (`label-col` column on medium width, above the value on compact), value `--fs-b`, data in `--mono`; 48 dp min height; hairline between rows |
| Text field | `OutlinedTextField`, `--r` corners, `--border-strong` outline, `--focus` when focused, `--bad` when invalid | Label above inside the outline (Material floating label), supporting text under it for hint or error; error text starts with the octagon shape |
| Secret field | `OutlinedSecureTextField` with a trailing `TextButton` "Show" / "Hide" (no eye icon) | The button's accessible name adds the field ("Show Access Code" / "Hide Access Code"); never prefilled; cleared on rotation |
| Main button | `Button`, fill `--accent`, text `--on-accent`, `--r` corners, height `--ctl` (44 dp at every window size; the app's pointer is a finger) | At most one enabled filled button per screen (Home: 5; Printer: 9.7); a sheet or dialog has its own |
| Other button | `OutlinedButton`, `--border-strong` outline, `--text` text | |
| Quiet button | `TextButton`, `--accent-text` | For "Cancel", "Not now", links inside text |
| Danger button | `OutlinedButton` with `--bad` outline and text; filled `--bad` with `--on-bad` text only as the confirming button inside a danger dialog | Always separated from other buttons by space or a divider |
| Icon button | `IconButton`, 48 dp | Always has a content description and a `TooltipBox` with `PlainTooltip` on long-press |
| Segmented control | `SingleChoiceSegmentedButtonRow` + `SegmentedButton` | Selected: `--accent-soft` ground, `--accent-text`, weight `--fw-title` |
| Switch row | `ListItem` with a trailing `Switch`; the whole row is `toggleable` | 48 dp min |
| Check row | `ListItem` with a leading `Checkbox`; the whole row is `toggleable` | 48 dp min |
| Filter chip | `FilterChip` | `--r-s` corners |
| Status | `Row` of a status shape (`--s2`, triangle and octagon `--s2` + 2 dp) and a word | F10 shapes; colour from the state; never the shape alone |
| Inline banner (02 8.8; Android `NoticeCard`; "notice line" in this document) | `Surface` with a `-soft` ground, `--r` corners, `--s3` padding, leading shape, text, optional trailing action | `ok`, `warn`, `bad`, `info` kinds; used for inline results and problems |
| Hub notice | An inline banner of kind `bad` with fixed texts and one action (3.4) | One composable used by every screen |
| Dialog | Medium width and up: `AlertDialog` (`BasicAlertDialog` when it holds a form), `--r-l`, `--e2`, scrim `--scrim`. Compact width: the same content in a `ModalBottomSheet` (F7: dialogs become bottom sheets on phones). | Title `--fs-l` `--fw-title`; body `--fs-b`; buttons at the bottom right (in a sheet: full width, stacked, confirming button on top); confirming button last in reading order on wide screens. Every "dialog" in this document follows this rule. |
| Sheet | `ModalBottomSheet`, `--r-l` top corners, drag handle | Used for short tasks on one thing (update weight, move, slot actions) |
| Toast | `Snackbar` in the `Scaffold`'s `SnackbarHost`, `--surface` ground, `--border-strong` outline, `--e2` | One line, optional one action ("Undo"); held 5 s, 10 s when it has an action, by the host's own timer |
| Determinate bar (02 8.3; "progress line" in this document) | `LinearProgressIndicator`, 4 dp, track `--surface-3`, indicator `--accent-text` | Determinate when the Hub gives a number; indeterminate while it does not |
| Spinner | `CircularProgressIndicator`, 16 dp, inside the button that started the work | Replaced by the word "Working…" when animations are off |
| Skeleton | `Box` blocks in `--surface-2` with `--r-s` corners | Same height as the rows they stand for; no shimmer |
| Empty state | `Column` centred in a panel with a dashed `--border` | `empty-mark` circle in `--accent-soft` with the section icon, title `--fs-l` `--fw-title`, one sentence `--muted`, at most two buttons |
| Swatch | `Box` `swatch-row-w` by `swatch-row-h` (rows) or `swatch-head` square (spool header), `--r-s` corners, 1 dp `--border-strong` outline, fill from the data | Empty slot: dashed `--border-strong` outline, no fill; always next to the colour's name or hex (F4.1) |
| Determinate bar (02 8.3) for the level ("level bar" in this document) | `LinearProgressIndicator` (determinate) | Remaining filament against net weight, with the grams in `--mono` beside it |
| Confidence mark | Status at `--fs-s` | 6.3 |

### 3.2 Loading, empty, error, offline

Every Hub-backed screen has these four states besides its content. The screen sections below give only their texts.

| State | How it looks |
|---|---|
| Loading (first time) | The screen's real layout with skeleton rows in place of data, and a `LinearProgressIndicator` (indeterminate) directly under the top bar. No spinner in the middle of the page. If loading takes over 10 s, a notice line of kind `info` appears: "Still waiting for the Hub…". |
| Refreshing | Data stays; the progress line under the top bar runs. Collections also support `PullToRefreshBox`; the same refresh is always available as a "Refresh" item in the top bar overflow (pull alone is not enough for switch access or TalkBack). |
| Empty | Empty state component with the texts given per screen. |
| Error | A notice line of kind `bad` at the top of the content, saying what went wrong in the words of 3.5, with "Try again". Data already on screen stays. |
| Offline | Data already loaded stays, with a notice line of kind `info` at the top: "Offline. Showing what was loaded 2 minutes ago. Spoolwarden keeps trying." Buttons that need the Hub are disabled, and the first one shows the reason under it: "Needs the Hub. Reconnecting…". With nothing loaded yet: empty state with the hollow-circle icon, title "Cannot reach the Hub", text "Check that this phone is on the home network.", button "Try again". |

Results of an action appear next to the control that caused it as a notice line (and are announced, 14.4), or as a
snackbar when the control has gone away (a closed sheet, a popped screen).

### 3.3 Local network access notice

Shown in place of the content of a Hub-backed screen on API 37 and later until access is granted. Panel with the
title "Allow local network access" and the text "Spoolwarden reaches your Hub over your home network. Android asks
your permission for that once." Button "Allow" (filled; starts the permission request). When Android will not ask
again, the text adds "Android will not ask again. Allow local network access for Spoolwarden in the app's
settings." and the button becomes "Open app settings" (opens the app's system settings page).

### 3.4 Hub notices

One composable, used wherever a request fails for these two reasons. It takes the place of that request's result on
the screen; it never replaces or clears the screen (2.7).

| Case | Text | Action |
|---|---|---|
| Certificate changed | "The Hub's certificate has changed. This phone stopped talking to it to stay safe." | "Review the certificate" (opens `pair/certificate/stored`) |
| No longer paired | "This phone is no longer paired with the Hub." | "Pair again" (opens `pair`) |

The fingerprints are shown only on the certificate screen (4.8), grouped and in `--mono`, never in the notice.

### 3.5 Error words

Hub and network failures use these texts everywhere (`strings.xml`, one key each):

| Cause | Text |
|---|---|
| No route to the Hub, timeout | "Cannot reach the Hub. Check that this phone is on the home network." |
| Unexpected answer | "The Hub sent an answer this app does not understand. Update the app or the Hub, then try again." |
| A refusal with the Hub's own message | the Hub's message, as given |
| Feature off | Title "<Feature name> is switched off", text "Switch it on in Features on the Hub page." |
| Spoolman unreachable | "The Hub can't reach Spoolman right now. Try again in a minute." |

Ellipses are always the single character "…".

---

## 4. Pairing

Pairing connects this phone to one Hub, once. All pairing screens share one layout: top bar (title "Pair with your
Hub", back arrow from the second step on, appearance icon, overflow with "Settings"), content in one column up to
`column-max` wide, centred on medium and expanded width, 16 dp gutters, the step's main button at the bottom of the
content (not floating). Opening Settings from here shows the Settings screens without the bottom bar; Back returns
to the pairing step.

Requests: discovery is local network service discovery (NSD), not HTTP. Probing a Hub is `GET api/info`; pairing is
`POST api/pair` with `{code}`. The Hub's certificate is pinned at pairing time.

### 4.1 Banner

When the pairing graph opens because the Hub stopped accepting this phone, a notice line of kind `bad` sits at the
top of 4.3: "This phone is no longer paired with the Hub. Pair it again to carry on." It disappears once pairing
succeeds.

### 4.2 Allow local network access (`pair/network-access`)

Only on API 37 and later, only until access is granted. Page header "Pair with your Hub", the version line
"App 0.5.2" (`--mono`, `--muted`), then the panel of 3.3. When access is granted the app moves on to `pair` by
itself.

### 4.3 Start (`pair`)

```
+--------------------------------------+
| Pair with your Hub          ☼   :    |
+--------------------------------------+
| App 0.5.2                            |
| Show a pairing code on the Hub page  |
| (Devices > Pair a phone), or run     |
| "sudo spoolwarden pair" on the Hub.  |
| Then scan its QR code.               |
| [ (camera) Scan QR code            ] |  <- main button
|                                      |
| Hubs found on this network           |
| +----------------------------------+ |
| | (o) Workshop hub   192.0.2.10  > | |
| +----------------------------------+ |
| [ Enter the address instead        ] |
+--------------------------------------+
```

| Element | Text / behaviour | Material 3 |
|---|---|---|
| Version line | "App 0.5.2" | `Text`, `--mono` `--fs-s` `--muted` |
| Intro | "Show a pairing code on the Hub page (Devices > Pair a phone), or run `sudo spoolwarden pair` on the Hub. Then scan its QR code." The command is in `--mono`. | `Text` |
| Scan | "Scan QR code", camera icon. Opens 4.4. While a scanned code is being checked: "Connecting…" with a spinner, disabled. | `Button` (main) |
| Result line | The last failure, as a notice line of kind `bad` directly under the button (texts in 4.9). | Notice line |
| Found Hubs | Panel titled "Hubs found on this network". Each found Hub is a row: status shape (filled circle), name, address in `--mono`, chevron. Tapping a row probes it and goes to 4.6 (or 4.7 when the fingerprint check is switched off, 12.3). While searching with nothing found: an indeterminate progress line in the panel header and the text "Still looking. A VPN or a guest Wi-Fi can hide the Hub; you can enter its address instead." | Panel, `ListItem` rows |
| Enter address | "Enter the address instead". Opens 4.5. | `OutlinedButton` |

The fingerprint-check switch is not on this screen; it lives in Settings > Hub connection (12.3).

### 4.4 QR scanner (`pair/scan`)

Full screen camera preview (CameraX `PreviewView` inside `AndroidView`), no top bar, no bottom bar. The system bars
stay visible over a `--scrim` band.

| Element | Text / behaviour |
|---|---|
| Hint chip at the top | "Point the camera at the QR code" (`--surface` ground, `--r`, `--fs-m`) |
| Close | `IconButton` with the close icon at the top left on a `--surface` circle, content description "Close the scanner". Same as Back. |
| Viewfinder | A square 2 dp `--border-strong` outline in the middle; no animation. |
| Found | A short haptic tick; the scanner closes and 4.3 shows "Connecting…". |
| Camera permission | Asked on first open. |
| Permission refused | The preview is replaced by a panel: "The camera is needed to scan the pairing code. You can allow it in the phone's app settings, or enter the address by hand instead." Buttons "Try again" (filled) and "Enter the address instead" (outlined). |
| Camera failed | "The camera could not start, so the pairing code can't be scanned. Enter the Hub's address instead." Button "Enter the address instead". |

### 4.5 Enter the Hub's address (`pair/address`)

| Element | Text / behaviour | Material 3 |
|---|---|---|
| Heading | "Enter the Hub's address" | `Text` `--fs-l` `--fw-title` |
| Address | Label "IP address or name", placeholder "192.0.2.10 or hub.local", one line, `KeyboardType.Uri`, no autocorrect | `OutlinedTextField` |
| Port | Label "Port", prefilled "8710", `KeyboardType.Number`, `port-field` wide | `OutlinedTextField` |
| Connect | "Connect"; "Connecting…" with a spinner while busy; fields disabled while busy | `Button` |
| Errors | Under the field they concern: "Enter the Hub's address." (address empty); "The port must be a number from 1 to 65535." (port). Connection failures under the button (4.9). | supporting text, notice line |

### 4.6 Check the fingerprint (`pair/fingerprint`)

| Element | Text / behaviour |
|---|---|
| Heading | "Check the Hub's fingerprint" |
| Text | "hub.local presented this certificate fingerprint. Compare it with the fingerprint shown with the pairing code on the Hub page before you continue." (with the address the person typed or picked) |
| Fingerprint | In a `--code` box with a 1 dp `--border`, `--mono` `--fs-b`, in groups of four characters, four groups per line, selectable (`SelectionContainer`). TalkBack reads it group by group. |
| Buttons | "It matches" (filled) and "It does not match" (outlined); side by side on medium width, stacked full width on compact with "It matches" on top. |
| Does not match | Returns to 4.3 with the notice "The fingerprint didn't match, so something else may be answering at this address. Nothing was paired." |

### 4.7 Enter the pairing code (`pair/code`)

| Element | Text / behaviour |
|---|---|
| Heading | "Enter the pairing code" |
| Text | "Type the 6-digit code shown on the Hub page." |
| Code | Label "6-digit code", digits only, at most 6, `KeyboardType.NumberPassword`, `--mono` `--fs-l` with letter spacing, focused on open. The sixth digit does not submit by itself. |
| Pair | "Pair"; "Pairing…" with a spinner while busy; disabled until six digits are typed, with the reason under it: "Enter all 6 digits." |
| Success | The pairing graph is cleared and Home opens with the snackbar "Paired with Workshop hub." When the pairing graph was opened with "Pair again" from a screen of the main graph (2.7), it closes and that screen shows again instead of Home, with the same snackbar. |

### 4.8 Certificate changed (`pair/certificate/{source}`)

A panel with the octagon shape and a title in `--bad`. Fingerprints are shown as in 4.6, each under its label.

| Source | Title | Body | Buttons |
|---|---|---|---|
| `stored` (a paired Hub now shows another certificate) | "The Hub's certificate has changed" | "This happens after the Hub was reinstalled or restored. If nothing like that was done, something else may be answering at its address." Labels "Paired with" and "The Hub now shows", then "Check the fingerprint on the Hub page under Devices." | "Trust the new certificate" (filled; pins it and returns to the screen it was opened from with the snackbar "The new certificate is trusted.") and "Pair again" (outlined). "Trust the new certificate" is offered only when the app can trust it in place; otherwise "Pair again" is the main button. |
| `qr` (a scanned code names another certificate) | "This pairing code doesn't match the Hub" | "The QR code names a different certificate than the Hub at this address shows." Labels "The code expects" and "The Hub shows". | "Start again" (filled) |
| `manual` (the certificate changed between the fingerprint check and the code) | "The Hub's certificate changed while pairing" | "Start again and compare the fingerprint once more." | "Start again" (filled) |

For `stored` the top bar title is "Hub certificate"; the back arrow returns to the screen it was opened from, and
the app keeps refusing to talk to the Hub until one of the two buttons is used.

### 4.9 Pairing messages

| Cause | Text |
|---|---|
| Hub unreachable | "Cannot reach the Hub. Check that this phone is on the home network." |
| Something else answers | "Something answers at this address, but it is not a Spoolwarden Hub. Check the address and port." |
| Code expired or used | "This pairing code has expired or was already used. Show a new one on the Hub page." |
| Not a pairing code (QR) | "That is not a Spoolwarden pairing code." |
| Code refused | "The Hub did not accept this code. Check it and try again." |
| Certificate differs from the pinned one | opens 4.8 |

---

## 5. Home (`home`)

Home opens on what is true now and offers the next thing to do (F1). One scrolling column on compact width
(`LazyColumn`, 16 dp gutters, 12 dp between panels). On medium and expanded width, two columns: left (Add spools,
Drafts), right (Printers, Slicer presets), each up to `column-max`.

```
+--------------------------------------+
| Home               (o) Connected  ☼  |
| Workshop hub                         |
+--------------------------------------+
| (i) Update ready: Spoolwarden 0.5.3 >|  <- only when there is one
|                                      |
| Add spools                           |
|  Photograph each label, check what   |
|  was read, then add.                 |
|  [ (camera) Add from label photos  ] |
|  [ Add by hand                     ] |
|                                      |
| Drafts                          2    |
|  3 minutes ago  2 photos · tag    >  |
|  Yesterday      1 photo           >  |
|                                      |
| Printers                  All >  3   |
|  (o) Workshop X1  Printing 42 %   >  |
|  (o) Garage Voron  Idle           >  |
|  ( ) Study A1 mini  Offline       >  |
|                                      |
| Slicer presets                    >  |
|  24 presets for 9 lines, built 3 h   |
|  Installed on your PC 2 h ago        |
+--------------------------------------+
| Home  Spools  Printers  Recent  Set  |
+--------------------------------------+
```

| Element | Content and behaviour | Requests | Material 3 |
|---|---|---|---|
| Top bar | Title "Home", the Hub's name under it, connection chip, appearance icon (2.2). | `GET api/info` | `TopAppBar` |
| Local network notice | 3.3, at the top, only in that state. | | Panel |
| Update notice | Only when an app update is offered or the Hub is newer than the app (13). Notice line of kind `info` "Update ready: Spoolwarden 0.5.3." or of kind `warn` "Update the app: the Hub is newer, so some things may not work." Trailing chevron; tapping opens `settings/updates`. | `GET api/info` | Notice line |
| Add spools panel | Title "Add spools". Text "Photograph each label, check what was read, then add. Nothing is saved until you add." Main button "Add from label photos" (camera icon) starts a new draft at `add/{id}/photos`. Other button "Add by hand" starts a new draft at `add/{id}/review` with the filament picker (6.4). When the Label Reader is off on the Hub, "Add by hand" is the main button, the photo button is absent, and one line says "The Label Reader is switched off. Add the spool by hand, or switch it on in Features on the Hub page." | `GET api/info` (`labelReading`) | Panel, `Button`, `OutlinedButton` |
| Drafts panel | Only when drafts exist. Title "Drafts" with the count. One row per draft, newest first: headline the relative time ("3 minutes ago"; exact time on long-press), supporting line "2 photos · note: 3 of the grey ones · tag <tag ID>" (only the parts that exist), trailing chevron. Tapping resumes the draft where it stopped. The row's overflow offers "Discard": dialog "Discard this add?" / "Its photos and edits are removed from this phone." / "Keep" / "Discard" (danger); then the snackbar "Add discarded." | none (drafts live on the phone) | Panel, `ListItem`, `DropdownMenu` |
| Printers panel | Title "Printers" with the count; header action "All printers" selects the Printers destination. One row per configured printer, at most 4, then "and 2 more": status shape and word, name, and the job when printing ("Printing · 42 % · 1 h 12 min left"). Tapping a row opens `printers/{id}` in the Printers destination. Empty: "No printers yet." with the text button "Add a printer" (selects Printers). Absent when the printers Feature is off. | `GET api/printers` (with each connection check) | Panel, `ListItem` |
| Slicer presets panel | 11.1 | `GET api/profiles/status` | Panel |

**One filled button on Home (F1 principle 2, `02-components.md` 4.1).** Adding spools is Home's main action, and
the Add spools panel's main button is the only filled button on the screen. "Add from label photos" and "Add by
hand" are the two ways into the same Add spools flow (6.1), offered side by side inside that panel, not separate
actions of Home. Search, Printers, Slicer presets and Settings are destinations (2.3) or panel rows and links, never
buttons of their own on Home; nothing else on Home is filled, and the same holds on every other screen (one main
action, its order given where several could apply, as 9.7).

States: loading shows the panels with skeleton rows. Offline keeps the last data with the notice of 3.2 and leaves
the Add spools panel usable: photos are taken and kept on the phone; reading waits for the Hub.

TalkBack order: top bar (title and Hub name as one node, connection chip, appearance), notices, Add spools (title,
text, main button, other button), Drafts (each row one node with a "Discard" custom action), Printers,
Slicer presets, bottom bar.

---

## 6. Add spools

Adding is one flow for both paths. Every add is a **draft** stored on the phone from the moment the flow starts (the
existing draft store, `DraftStore`) and saved after every change: photos, note, tag, weight, every field. A draft
survives Back, switching destinations, rotation, the app being stopped, and time offline. It ends when its spools are
added or when the person discards it (5).

Requests: `POST api/intake/read` (multipart `photo` parts, `hint`, `tag`), `POST api/intake/retry/{readId}`,
`POST api/intake/add` with `{items, dry_run, tag}`, `GET api/filaments?q=`, `GET api/vendors`, `GET api/locations`,
`GET api/profiles/parents?material=`.

### 6.1 Flow

```
Home -- Add from label photos --> Photos -- Read labels --> Check the spools -- Preview --> Preview -- Add --> Spools added
Home -- Add by hand -------------------------------------> Check the spools (with the filament picker) ---^
```

The top bar title is "Add spools" on every step. The step is the page header ("Photos", "Check the spools",
"Preview", "Spools added") with a line under it in `--fs-s` `--muted`: "Step 1 of 3" on the photo path (Photos,
Check, Preview), "Step 1 of 2" on the hand path (Check, Preview).

Under the page header every step shows the draft's tags (`--fs-s`, `--r-s`, `--surface-2`): "2 photos",
"Tag <tag ID>". They are information only.

### 6.2 Photos (`add/{draftId}/photos`)

```
+--------------------------------------+
| <  Add spools       (o) Connected ☼  |
+--------------------------------------+
| Photos                Step 1 of 3    |
| Photograph each label. Several       |
| photos of one spool are fine.        |
| +----------------------------------+ |
| |       camera preview 3:4         | |
| +----------------------------------+ |
| [ (camera) Take photo        2 of 8] |
| [img x][img x]                       |
| (tag) No tag                         |
|   Hold the spool's tag to the back   |
|   of the phone to link it.           |
| Still sealed (in its bag or box) [on]|
| [Weight with spool                  ]|
| [Note for the Label Reader         ] |
+--------------------------------------+
| [ Read labels (2 photos)           ] |  <- sticky action bar
+--------------------------------------+
```

| Element | Text / behaviour | Material 3 |
|---|---|---|
| Intro | "Photograph each label. Several photos of one spool are fine. Nothing is saved to the inventory until you check and add." | `Text` |
| Camera preview | 3:4, `--r` corners, 1 dp `--border`. Hidden at 8 photos and while reading. On medium and expanded width the preview sits on the left (up to `preview-max`) and the other controls on the right. | CameraX `PreviewView` in `AndroidView` |
| Take photo | "Take photo", camera icon, the count "2 of 8" at the right end in `--mono`. "Taking photo…" while saving. Main button until the first photo; then outlined, because "Read labels" becomes the main action. | `Button` / `OutlinedButton` |
| Camera permission | Panel in place of the preview: "The camera is needed to photograph labels." Button "Allow camera". When Android will not ask again: "Allow the camera for Spoolwarden in the app's settings." and "Open app settings". | Panel |
| Camera errors | Notice line `bad` under the preview: "The camera could not start. Close other apps that use it, then try again." / "The photo failed. Try again." | Notice line |
| Photo strip | Thumbnails `thumb` square, `--r` corners. Each has a close-icon `IconButton` in its corner with a 48 dp hit area, content description "Remove photo 2". Tapping a thumbnail opens it full screen (viewer as 10.5). After a removal: snackbar "Photo removed." with "Undo". | `LazyRow`, `IconButton` |
| Tag row | Tag icon. No tag: headline "No tag", supporting "Hold the spool's tag to the back of the phone to link it (optional)." With a tag: headline "Tag <tag ID>" (`--mono`), supporting "It is linked when you add exactly one opened spool.", trailing text button "Remove". | `ListItem`, `TextButton` |
| Still sealed | Switch row "Still sealed (in its bag or box)", on by default. | `ListItem` + `Switch` |
| Weight with spool | Label "Weight with spool (optional)", supporting "Only for one opened spool. Leave empty for a full spool.", `KeyboardType.Decimal`, `--mono`. Disabled while Still sealed is on, with the supporting text "Not needed for a sealed spool." Error "Enter grams above 0." | `OutlinedTextField` |
| Note | Label "Note for the Label Reader (optional)", placeholder "e.g. 3 of the grey ones", up to 3 lines. | `OutlinedTextField` |
| Action bar | Sticky above the navigation bar, `--surface` with a top hairline. Main button "Read labels (2 photos)" (plural from strings), disabled with no photo, with the reason above it: "Take at least one photo first." When the draft already holds read results, "Back to the check" (outlined) appears to its left. | `Surface`, `Button`, `OutlinedButton` |

**Reading** is a state of this screen. The preview and photo controls give way to a panel with an indeterminate
progress line and "Reading 2 photos… (up to a minute)". The action bar shows "Cancel reading" (outlined);
cancelling keeps the draft and the photos. When the read ends, the app moves on to 6.3. If the person has left the
screen, the result is stored in the draft and a snackbar "The labels are read." with the action "Check" appears
wherever they are.

**Read failures** show a notice line of kind `bad` above the action bar: the reason, then "Your photos and edits
are kept.", and the buttons the case allows: "Try again" (`POST api/intake/retry/{readId}` when the Hub gave a read
id, else a new read), "Add without the tag", "Pair again", "Add by hand".

| Cause | Text |
|---|---|
| Daily limit used up | "Today's label reads on the Hub are used up. Try again tomorrow, or add by hand." |
| Cloud key refused | "The Hub's Anthropic API key was refused. Check it on the Hub page under Settings > Label Reader." |
| Rate limit | "The Label Reader is busy. Wait a minute, then try again." |
| Hub can't reach the cloud | "The Hub can't reach the Label Reader's cloud service. Try again in a minute." |
| Declined, cut off, or nothing read | "The Label Reader could not read the labels this time. Take a sharper photo, or add by hand." |
| Photos gone on the Hub | "The Hub no longer has these photos. Read the labels again." |
| A photo unusable | "One photo could not be used. Remove it and take it again." |
| Tag already linked | "This tag is already linked to another spool. Add without the tag, or open that spool first." |
| Label Reader off | "The Label Reader is switched off. Add the spool by hand, or switch it on in Features on the Hub page." |
| Spoolman unreachable | 3.5 |
| Offline | "Needs the Hub. Your photos are kept; read them when the Hub is back." |

### 6.3 Check the spools (`add/{draftId}/review`)

The read result is a list of proposed spools. Each is a panel that expands in place (Console `detail = inline`).
On compact width one panel is open at a time; on medium width and up any number can be open.

```
+--------------------------------------+
| <  Add spools       (o) Connected ☼  |
+--------------------------------------+
| Check the spools        Step 2 of 3  |
| 3 spools · 2 values estimated ·      |
| 1 spool needs fields                 |
| +----------------------------------+ |
| | (i) The Label Reader asks:       | |
| |   - Is the grey one PLA or PETG? | |
| +----------------------------------+ |
| +----------------------------------+ |
| | [sw] Polymaker PolyTerra PLA     | |
| |      Charcoal Black        x1  ^ | |
| |      Existing filament 41        | |
| |      /\ 1 estimated              | |
| |----------------------------------| |
| | IDENTITY                         | |
| | [Brand: Polymaker           v]   | |
| | [Name: PolyTerra PLA Charcoal..] | |
| | [Colour: 2B2B2E ]                | |
| |   /\ Estimated: check this       | |
| |   ...                            | |
| +----------------------------------+ |
| +----------------------------------+ |
| | [  ] New filament          x2  v | |
| |      <> Needs: Material, Net wt  | |
| +----------------------------------+ |
+--------------------------------------+
| Spool 2 still needs: Material,  Show |
| [Back to photos]  [ Preview        ] |
+--------------------------------------+
```

**Summary line** under the header, in words: "3 spools · 2 values estimated · 1 spool needs fields".

**Label Reader questions**: a notice line of kind `info` titled "The Label Reader asks:" with the questions as a
bulleted list. Notices from the read follow as `info` lines, and the tag note: "Tag <tag ID> is linked when you
add exactly one opened spool."

**Spool panel header** (always visible; the whole header toggles the panel, `Role.Button`, state "expanded" or
"collapsed"): swatch (from Colour), headline "<brand> <name>" or "New filament", a count tag "×2" when Spools is
more than 1, supporting line "Existing filament 41 (3 spools). A different brand or name makes a new filament." or
"New filament", and one status: "Ready" (filled circle, `--ok`), "1 estimated" (triangle, `--warn`), or "Needs:
Material, Net weight" (octagon, `--bad`). Trailing: the chevron and an overflow "More actions" with "Remove this spool" (no
dialog; snackbar "Spool removed." with "Undo") and "Add this line to the Filament Catalog" (opens `catalog/new`, 8,
with Brand, Line and Material filled in from this panel; the draft is kept and Back returns here). When the Label Reader gave a reason for sealed, a line under the header in
`--fs-s` `--muted`: "Label Reader: in a vacuum bag".

**Fields**, in the add-form groups shared with the web app: Identity · Amount · State · Print settings · Storage ·
Other. A group with no field on this screen (Other) is not drawn. Group titles are `--fs-xs`, uppercase, `--muted`,
0.05em letter spacing. Each field is an `OutlinedTextField`, full width on compact, two per row on medium width and
up. Numeric fields use `KeyboardType.Decimal` or `Number` and `--mono`.

| Group | Field label | Notes |
|---|---|---|
| Identity | Brand | Trailing `IconButton` "Pick a brand" opens an `ExposedDropdownMenuBox` list "<brand> · 250 g spool" (from `GET api/vendors`); picking also fills an empty "Empty spool weight". |
| | Name | The name with the colour, e.g. "PolyTerra PLA Charcoal Black". |
| | Line | Up to 100 characters. Supporting: "Presets are made per line." |
| | Material | |
| | Colour (hex) | `--mono`, with the live swatch at the leading end. Error "Enter 6 hex digits, e.g. 2B2B2E." |
| Amount | Spools | Whole number, at least 1. |
| | Net weight | Supporting: "Filament only, as printed on the label." |
| | Empty spool weight | Error "Enter grams above 0." |
| State | Still sealed | Check row "Still sealed (in its bag or box)"; the whole row toggles. |
| | Weight with spool (optional) | Only when Spools is 1 and the spool is not sealed. Supporting: "Leave empty for a full spool." |
| Print settings | Density | Always on the hand path; on the photo path only when the Hub asks for it. Supporting "Leave empty to choose automatically."; placeholder the usual value for the material ("1.24"). |
| | Nozzle (optional), Bed (optional) | Hand path only. |
| | Bambu Studio parent | `ExposedDropdownMenuBox` with "Automatic" first, then the Hub's parent presets when they are synced. Without synced presets it is a plain text field with the supporting text "Bambu Studio's presets are not synced to the Hub yet; type the name." Always under it: "Applies to every colour of this line." As a plain text field it adds the supporting text "Leave empty to choose automatically." |
| Storage | Location | `ExposedDropdownMenuBox`: "Automatic" first, then the Hub's locations. |

**Per-field confidence.** A field whose value is not certain carries a confidence mark in its supporting text. The
mark is a status (shape plus word, `--fs-s`) and TalkBack reads it with the field ("Colour, 2B2B2E, estimated, check
this").

| Mark | Shape and colour | Word | When |
|---|---|---|---|
| none | | | The Label Reader read the value from the label. |
| Estimated | triangle, `--warn` | "Estimated: check this" | The field is in the read's `estimates` list. |
| Not on the label | hollow circle, `--muted` | "Not on the label" | The reader left the field empty. |
| Medium | triangle, `--warn` | "Medium" | Only when the Hub sends per-field levels (16). |
| Low | octagon, `--bad` | "Low: check this" | Only when the Hub sends per-field levels (16). |

Editing a field removes its mark. The panel header counts the marks that remain.

**Validation** is shown under the field after it loses focus, or for all fields after "Preview" is pressed:
"Enter a whole number.", "Enter grams above 0.", "Enter a density above 0.", "Enter degrees above 0.". A complaint
from the Hub about a field appears under that field; complaints that name no field are `bad` notice lines at the
bottom of the panel.

**Action bar** (sticky): "Back to photos" (outlined, photo path only) and "Preview" (main). While "Preview" is
disabled, the reason is shown **above** the bar, never below the button: "Spool 2 still needs: Material, Net
weight." with the text button "Show", which opens that panel and focuses the first missing field; or "Enter a spool
count for every spool."; or the empty-spool problem.

**Added before.** When the Hub reports these spools may have been added already: a `warn` notice line at the top,
"These spools may have been added already: <the Hub's note>. Check Spoolman before adding them again."

Empty (photo path, nothing found): empty state "No spools found in these photos" / "Go back to the photos and read
them again, or add by hand." with "Back to photos" and "Add by hand".

Empty (hand path, no spool panel yet): under the filament picker (6.4) the line "Pick a filament above, or tap New
filament." in `--fs-m` `--muted`. "Preview" is disabled, with the same sentence as its reason above the action bar.

### 6.4 Filament picker (hand path)

At the top of 6.3 on the hand path: panel "Find the filament" with a search field (label "Brand, name or
material", placeholder "e.g. sunlu petg", leading search icon; results 300 ms after typing stops, from 2
characters). Results are rows (swatch, "<brand> <name>", supporting "<material> · 3 spools"), at most 20, then the
line "12 more: type more of the name to narrow it down." Tapping a row adds a spool panel filled from that filament
and collapses the picker to the single row "Add another filament" (tap to expand). Under the results, the outlined
button "New filament" adds an empty spool panel to type in. States: "Looking…" (progress line in the panel
header), "No filament matches. Use New filament.", error notice line.

### 6.5 Preview (`add/{draftId}/preview`)

The Hub's dry run (`dry_run: true`) runs on entry: progress line and "Checking with the Hub…". The page header is
"Preview" with the line "Nothing is saved yet." The content is one row per spool (swatch, name, count, location,
"New filament" or "Existing filament 41"), then a panel "What the Hub will do" with the Hub's lines, one row per
line, `--fs-m`. Problems from the Hub are `bad` notice lines at the top, each with "Fix", which returns to 6.3 at
the field concerned.

Action bar: "Back to the check" (outlined) and the main button "Add 3 spools" (plural). Pressing it sends the real
add (`dry_run: false`) with "Adding to Spoolman…" and a spinner. Back is allowed; the add continues and its result
arrives as a snackbar wherever the person is.

**Add these spools again?** (dialog, when the Hub says this read was added before): title "Add these spools
again?", body "<the Hub's note> Adding again can create duplicate spools. Check Spoolman first and only continue if
they are missing.", buttons "Cancel" and "Add again" (danger, filled).

### 6.6 Spools added (`add/{draftId}/done`)

Page header "Spools added" with the status "Added" (filled circle, `--ok`). Text "New spools: spool 212, spool 213"
(numbers `--mono`), or "The Hub returned no new spool numbers." Then the Hub's result lines. If a tag was linked:
"Tag <tag ID> is linked to spool 212." Buttons: "Done" (main; returns to Home and deletes the draft), "Add more"
(outlined; starts a new draft on the same path), and, when the Hub returned a record id, the text button "Open in
Recently added" (`recent/{hid}`). Partial failure: `warn` notice "Some spools were not added: <the Hub's message>.
Spools 212 and 213 were created." and the draft is kept with the spools that failed.

---

## 7. Spools and the spool screen

The spool card of today becomes a proper screen with sheets and sub-screens. A spool is reached from a search
result, from a tag tap (2.6), from a printer slot (9.6) or from a deep link.

Requests: `GET api/spools?q=<q>[&sealed=1]`, `GET api/tags/{uid}`, `PATCH api/spools/{id}` with `gross`,
`remaining`, `location` or `empty` and `dry_run`, `GET api/locations`, `POST api/spools/{id}/link` with
`{tag, force, dry_run, gross, location}`, `GET api/printers`, `GET api/printers/{id}`,
`POST api/printers/{id}/slots/{label}/load` with `dry_run`.

### 7.1 Spools (`spools`)

```
+--------------------------------------+
| Spools              (o) Connected ☼  |
+--------------------------------------+
| [(search) Brand, material, colour  ] |
| [Sealed only]                        |
| (tag) Hold a spool's tag to the back |
|       of the phone to open it.       |
| +----------------------------------+ |
| |[sw] Polymaker PolyTerra PLA      | |
| |     Charcoal Black             > | |
| |     Spool 214 · PLA ·            | |
| |     Workshop X1 A1 · 620 g       | |
| |----------------------------------| |
| |[sw] Bambu Lab PETG HF Orange   > | |
| |     Spool 212 · PETG ·           | |
| |     Dry box 1 · 1000 g · sealed  | |
| +----------------------------------+ |
+--------------------------------------+
```

| Element | Text / behaviour | Material 3 |
|---|---|---|
| Search field | Label "Brand, material, colour…", leading search icon, trailing clear `IconButton` ("Clear search") when not empty, `ImeAction.Search`. Searches 300 ms after typing stops once 2 or more characters are typed, and at once on the keyboard's search key. Clearing the field clears the results. No separate Search button. | `OutlinedTextField` |
| Sealed only | Filter chip "Sealed only"; the whole chip toggles; re-runs the search. | `FilterChip` |
| Tag hint | Tag icon and "Hold a spool's tag to the back of the phone to open it." `--fs-m` `--muted`. Shown while no search is typed. When the phone has no NFC: "This phone can't read tags. Search instead." When NFC is off: "Turn on NFC to open spools by their tag." with the text button "NFC settings" (opens the system NFC settings). | `Row`, `TextButton` |
| Results | Panel with a collection: swatch, headline "<brand> <name>", supporting "Spool 214 · PLA · Workshop X1 A1 · 620 g left" (the spool's location as the Hub gives it; numbers `--mono`; "sealed" and "tagged" added when true), chevron. Tapping opens `spools/{id}` (right pane on expanded width). | `LazyColumn`, `ListItem` |

States: idle shows only the field, the chip and the tag hint. Searching: indeterminate progress line under the
field (the results stay until new ones arrive). Empty: "No spools match "petg"." with the text button "Clear the
Sealed only filter" when it is on. Error, offline, Hub notices: 3.2 to 3.4.

TalkBack order: search field, Sealed only, tag hint, results ("Polymaker PolyTerra PLA Charcoal Black, spool 214,
PLA, Workshop X1 A1, 620 grams left"), bottom bar.

### 7.2 Spool (`spools/{id}`)

```
+--------------------------------------+
| <  PolyTerra PLA Ch… (o) Connected ☼ |
+--------------------------------------+
| [sw]  Polymaker                      |
| [  ]  PolyTerra PLA Charcoal Black   |
|       Spool 214 · PLA · #2B2B2E      |
|                                      |
|  620 g left        of 1000 g         |
|  [============--------]  62 %        |
|  (o) Weight updated just now         |  <- result line
|                                      |
|  [ Update weight                   ] |  <- main
|  [ Load into a printer ] [Move]  [:] |
|                                      |
| Details                              |
|  Location      Workshop X1 A1        |
|  Tag           <tag ID>              |
|  State         Opened                |
|  Filament      41                    |
|  Empty spool weight  140 g           |
+--------------------------------------+
```

| Element | Text / behaviour | Material 3 |
|---|---|---|
| Top bar | Title "<name>" (ellipsis); back arrow; overflow "More actions" with "Mark empty" (danger) and "Refresh". | `TopAppBar`, `DropdownMenu` |
| Header | Swatch `swatch-head`; vendor `--fs-m` `--muted`; name `--fs-l` `--fw-title`; line "Spool 214 · PLA · #2B2B2E" in `--fs-s`, numbers and hex in `--mono`. | `Row` |
| Remaining | "620 g left" in `--fs-2xl` `--mono`, "of 1000 g" `--muted`; level bar with "62 %". Sealed spools show "Sealed · 1000 g" and no bar. Empty spools show the status "Empty" (hollow circle). | `Text`, `LinearProgressIndicator` |
| Result line | The last change on this screen, as a notice line of kind `ok` under the level bar: "Weight updated: 482 g left.", "Moved to Shelf B.", "Marked empty.", "Tag linked.", "Tag moved to this spool.", "Loaded into Workshop X1, slot A2." It stays until the next change or until the screen is left; it is announced politely. | Notice line |
| Main action | "Update weight" opens 7.3. | `Button` |
| Other actions | "Load into a printer" (outlined; opens 7.6; absent when the printers Feature is off); "Move" (outlined; opens 7.4). | `OutlinedButton` |
| Details | Panel "Details", field rows: Location, Tag ("<tag ID>" `--mono`, or "None"), State ("Sealed", "Opened", "Empty"), Filament ("41"), Empty spool weight ("140 g"), Lot. A row whose value the Hub did not send is left out (16). | Panel, field rows |

When the spool screen was opened from a tag, the header shows a tag status "Opened by tag <tag ID>" in `--fs-s`.

States: the screen opens with the spool summary it was given (search row or tag lookup) and refreshes after every
change from the Hub's answer. Offline: actions disabled with "Needs the Hub. Reconnecting…".

TalkBack order: back, title, connection, appearance, header (one node: "Polymaker PolyTerra PLA Charcoal Black,
spool 214, PLA, colour 2B2B2E"), remaining (one node: "62 percent left: 620 of 1000 grams"), result line, Update
weight, Load into a printer, Move, More actions, Details rows.

### 7.3 Update weight (sheet destination `spools/{id}/weight`)

`ModalBottomSheet`, title "Update weight".

| Element | Text / behaviour |
|---|---|
| Field | Label "Weight with spool", `KeyboardType.Decimal`, `--mono`, focused on open (the keyboard opens with the sheet). Supporting "Put the spool on the scale and type what it shows." Error "Enter grams above 0." |
| Preview | 400 ms after a valid weight is typed the app asks the Hub for a dry run and shows, under the field: "Remaining becomes 482 g (now 620 g)." with a progress line while it asks. |
| Buttons | "Cancel" (text) and "Save weight" (main), disabled until a preview is shown; the reason under the field: "Enter the weight to see the result first." "Saving…" with a spinner while saving. |
| After saving | The sheet closes; the result line of 7.2 shows "Weight updated: 482 g left." |
| Leaving with a typed weight | Back or a scrim tap asks as 2.5 rule 1: "Leave without saving?" / "Your changes to the weight are not saved." / "Stay" (focused first) / "Leave without saving" (danger). |

### 7.4 Move (sheet destination `spools/{id}/move`)

`ModalBottomSheet`, title "Move to". A list of the Hub's locations as radio rows (`ListItem` with `RadioButton`,
whole row selectable); the current location is marked "Now here" and selected. Tapping another location saves at
once ("Moving…" in its row), closes the sheet, sets the result line "Moved to Shelf B." and shows the snackbar
"Moved to Shelf B." with "Undo" (moves it back with the same request). Empty list: "The Hub has no storage locations
yet. Add them on the Hub page under Settings > Storage locations." Error: notice line in the sheet.

### 7.5 Mark empty (dialog)

From the overflow. `AlertDialog`: title "Mark spool 214 empty?", body "Polymaker PolyTerra PLA Charcoal Black (spool
214) will be marked as used up.", buttons "Cancel" and "Mark empty" (danger, filled). After: result line "Marked empty."

### 7.6 Load into a printer (`spools/{id}/load…`)

Three destinations, one per step, each with the top bar title "Load into a printer" and a step line. The spool's
summary row is pinned at the top of each step.

| Step | Route | Content |
|---|---|---|
| 1. Printer | `spools/{id}/load` | Header "Which printer?". One row per configured printer: status shape and word, name, model. Printers that cannot take a load now (offline, wrong Access Code) are shown disabled with the reason as the supporting line ("Offline"). Skipped when exactly one printer can take the load; step 2 then shows "Printer: Workshop X1". Loading: "Loading printers…" skeleton rows. Empty: "No printers are set up yet. Add one under Printers." with the text button "Open Printers". |
| 2. Slot | `spools/{id}/load/{printerId}` | Header "Which slot on Workshop X1?". The printer's slots grouped by unit ("AMS A", "Toolhead"): one row per slot: slot label in `--mono` (as the Hub names it: "A2", "T0"), swatch, and the line "<material> · <spool name> · <percent> %" ("PETG · Bambu Lab PETG HF Orange · 88 %"); parts the printer or the inventory does not give are left out with their separator ("PLA" for filament linked to no spool); an empty slot reads "Empty" with the dashed swatch; the active slot adds " · in use". A printer problem, when there is one, as a notice line at the top with its fix text. "The printer reports no slots." when empty. Loading: "Loading slots…". |
| 3. Preview | `spools/{id}/load/{printerId}/{slot}` | On entry the app asks for a dry run ("Checking…"). Header "Load into Workshop X1, slot A2?". The Hub's preview lines as rows (preset, nozzle, where the spool now in the slot goes back to). The text "This sets the slot on the printer and moves the spool there in the inventory." Buttons "Back" (outlined) and "Load" (main; "Loading…" with a spinner). |

While the load is being written Back is ignored (2.5 rule 2). Results:

| Result | What happens |
|---|---|
| Loaded | The load stack closes; the spool screen's result line shows "Loaded into Workshop X1, slot A2." |
| Accepted, not shown yet | Same, with a `warn` result line: "The printer accepted it but hasn't shown the change yet." |
| Connection lost during the write | The step stays open with a `bad` notice: "The connection dropped while loading, so the app can't tell if it worked. Check the printer's slot and the spool's location before trying again." Buttons "Open the printer" and "Done". |
| Refused | `bad` notice with the Hub's or printer's reason; for a pairing refusal: "Not loaded: the Hub did not accept this phone's pairing at that moment. Nothing was changed." |

### 7.7 Tag (`tag/{uid}`)

| State | Content |
|---|---|
| Looking up | Page header "Tag <tag ID>" (`--mono`), progress line, text "Looking up the tag…". |
| Linked to a spool | The screen replaces itself with `spools/{id}` (the tag route is removed from the back stack). |
| Not linked | Empty-state layout with the tag icon: title "This tag is not linked to a spool yet", text "Link it to a sealed spool you are opening, or add the spool as new." Buttons "Link to a sealed spool" (main; opens 7.8) and "Add as a new spool" (outlined; starts a draft with this tag: photo path when the Label Reader is on, hand path otherwise). |
| Failed | `bad` notice with the reason and "Try again"; Hub notices as 3.4. |

### 7.8 Link to a sealed spool (`tag/{uid}/link`, `tag/{uid}/link/{spoolId}`)

**Find** (`tag/{uid}/link`): header "Link tag <tag ID> to a sealed spool". Fields: search "Brand, name or colour"
(searches as in 7.1, sealed spools only) and "Weight with spool (optional)" (`--mono`; error
"Enter grams above 0, or leave this empty."). Results as rows; tapping one opens the preview. Rows are disabled while the
weight is invalid, with the reason above the list. Empty: "No sealed spools match." Error: notice with "Try again".

**Preview** (`tag/{uid}/link/{spoolId}`): on entry a dry run. Header "Link this tag?" The spool's summary row; the
lines "Tag <tag ID> is linked to this spool." and, with a weight, "Weight with spool is recorded as
1240 g." Buttons "Back" and "Link tag" (main; "Linking…"). On success the stack is replaced by `spools/{id}` with the
result line "Tag linked."

**Tag already in use** (a state of the preview): `warn` notice "This tag is already linked to another spool:" with
that spool's summary row under it, then the button "Move the tag to this spool" (main), or, when the chosen spool
already has a tag, "Move the tag here and replace this spool's tag". "Cancel" returns to Find. On success: result
line "Tag moved to this spool."

---

## 8. Add a line to the Filament Catalog (`catalog/new`)

What today's app calls "Add profile": it records a product line's values from the maker's label or data sheet in the
Filament Catalog, so Slicer presets can be built for it. Reached from the Slicer presets screen (11.2) and from the
spool panel overflow in 6.3 ("Add this line to the Filament Catalog").

Request: `POST api/library/local`; parents from `GET api/profiles/parents?material=`.

| Element | Text / behaviour |
|---|---|
| Top bar | Title "New catalog line", back arrow. |
| Intro | "Values from the maker's label or data sheet for one product line. They apply to every colour of the line." |
| Group "Line" | "Brand *", "Line *", "Material *" |
| Group "Temperatures" | "Nozzle range" with placeholder "e.g. 190-220", "Bed range" with placeholder "e.g. 55-65" |
| Group "Material" | "Density", "Max volumetric speed" |
| Group "Slicer" | "Bambu Studio parent" (as in 6.3) |
| Group "Notes" | "Notes" (multi-line) |
| Required marker | "*" after the label and the line "Fields marked * are needed." at the top. |
| Action bar | "Save to the catalog" (main; "Saving…"); disabled until the required fields are filled, with the reason above it: "Fill in Brand, Line and Material." |
| Success | Back to the screen it came from with the snackbar "Saved to the Filament Catalog. Slicer presets are rebuilt in a minute." The form is gone with its values, so a second tap cannot save the same line twice; while saving, "Save to the catalog" ignores further taps. |
| Refused | `bad` notice "The Hub could not use these values:" with one bullet per problem; each problem also under its field when it names one. Hub notices as 3.4. |
| Leaving with typing | Asks (2.5 rule 1). |

---

## 9. Printers

Requests: `GET api/printers`, `POST api/printers` (Bambu: serial, name, Access Code; Klipper: `family: "klipper"`,
host, port, name, API key), `POST api/printers/scan` with `{subnet?}`, `GET api/printers/{id}` (polled every 2 s
while the printer screen is visible), `POST api/printers/{id}/command` with `{action}`, camera
`GET api/printers/{id}/camera/index.m3u8` (HLS, Media3 ExoPlayer) or `GET api/printers/{id}/camera.mjpeg`,
`POST api/printers/{id}/slots/{label}/load` and `/unload` (dry run first), `GET api/printers/{id}/usage?days=7`,
`POST api/usage/{id}/undo`, `GET` and `POST api/printers/{id}/map`, `api/printers/{id}/manual-map/…`,
`POST api/printers/{id}/report`, `PATCH api/printers/{id}`, `DELETE api/printers/{id}`.

### 9.1 Printers (`printers`)

```
+--------------------------------------+
| Printers            (o) Connected ☼ :|
+--------------------------------------+
| +----------------------------------+ |
| | (o) Workshop X1                > | |
| |     Bambu Lab X1 Carbon          | |
| |     Printing · 42 % · 1 h 12 min | |
| |     [sw][sw][sw][ ]              | |
| |----------------------------------| |
| | (o) Garage Voron               > | |
| |     Voron 2.4 (Klipper) · Idle   | |
| |----------------------------------| |
| | ( ) Study A1 mini              > | |
| |     Bambu Lab A1 mini · Offline  | |
| |     /\ The last slot mapping ... | |
| +----------------------------------+ |
| FOUND ON THE NETWORK                 |
| +----------------------------------+ |
| | ( ) Bambu Lab <model>  [ Add ]   | |
| |     Not configured · <address>   | |
| +----------------------------------+ |
| [ Add a Klipper printer ]            |
+--------------------------------------+
```

| Element | Text / behaviour | Material 3 |
|---|---|---|
| Top bar | Title "Printers"; overflow "Refresh", "Find Klipper printers", "Add a Klipper printer". | `TopAppBar`, `DropdownMenu` |
| Refresh | On every visit and by pull. While refreshing: progress line under the top bar. | `PullToRefreshBox` |
| Configured printers | Panel, one row per printer: status shape and word (vocabulary below), name (`--fs-b` `--fw-label`), model, job line when printing ("Printing · 42 % · 1 h 12 min left"), slot swatches (up to 8, then "+4"), and, when the printer needs something, a line with the triangle and the fix ("Enter the Access Code again.", "The last slot mapping stopped twice. A report would help."). Tapping opens `printers/{id}` (right pane on expanded width). A printer whose Access Code is wrong opens its screen with the Access Code dialog (9.9) already open. | Panel, `ListItem` |
| Found on the network | Group title "Found on the network" (`--fs-xs` uppercase). Rows for printers the Hub sees but that are not set up: model, the status "Not configured", address in `--mono`, trailing "Add" (outlined; opens 9.2). Ground `--accent-soft`. | Panel, `ListItem`, `OutlinedButton` |
| Add a Klipper printer | Outlined button under the lists; opens 9.3. | `OutlinedButton` |
| Empty | Empty state with the printer icon: title "No printers yet", text "The Hub finds Bambu Lab printers on its network by itself: turn the printer on, then add it here with its Access Code. A Klipper printer is added by its address." Buttons "Refresh" (main) and "Add a Klipper printer". | Empty state |

Printer state vocabulary. The badge words are those of `02-components.md` 7.1; what the state is comes in the fix
sentence that always follows a "Needs a look".

| State (Hub's `state`) | Shape and colour | Badge word | Fix line |
|---|---|---|---|
| `connected` | filled circle, `--ok` | Connected | none |
| `offline` | hollow circle, `--bad` | Offline | "Check that the printer is on and on the same network as the Hub." |
| `wrong_code` | triangle, `--warn` | Needs a look | "The printer did not accept the Access Code. Enter the Access Code again." |
| `needs_developer_mode` | triangle, `--warn` | Needs a look | "The printer refuses remote control. Turn on LAN mode and Developer Mode on the printer." |
| `cert_changed` | triangle, `--warn` | Needs a look | "The printer's certificate changed. Forget its old certificate in Printer settings." |
| `not_configured` | hollow circle, `--muted` | Not configured | Bambu Lab: "Add it with its Access Code." Klipper: "Use this printer to add it." |
| `unknown_model` (Klipper) | filled circle, `--ok` | Connected | Note line (diamond, `--info`): "Model not known; slots are read as a generic Klipper printer." The job line and swatches are shown. |
| `unauthorized` (Klipper) | triangle, `--warn` | Needs a look | "Moonraker refused the API key. Replace it in Printer settings." |
| `klippy_not_ready` (Klipper) | triangle, `--warn` | Needs a look | "Klipper is not ready on the printer. Check it in Mainsail or Fluidd." |
| `connecting` | inline spinner | "Connecting…" (not a badge) | none |
| any other value | triangle, `--warn` | Needs a look | The Hub's word (underscores as spaces, sentence case) and its fix text when it sends one |

While a job is known, the job state follows the badge as words (not a badge): "Printing", "Paused", "Preparing",
"Slicing", "Finished", "Print failed", "Idle".

### 9.2 Add a Bambu Lab printer (dialog destination `printers/add/{serial}`)

`BasicAlertDialog` with a form; on compact width it is a `ModalBottomSheet` (F7: dialogs become bottom sheets on
phones).

| Element | Text / behaviour |
|---|---|
| Title | "Add <model>" ("Add Bambu Lab X1 Carbon") |
| Facts | The model and serial the Hub found: "<model> · serial <serial>" (`--mono` for the serial) |
| Access Code | Secret field "Access Code", hint "On the printer: Settings > Network/LAN > Access Code." Error when "Add printer" is pressed with it empty: "Enter the Access Code shown on the printer." |
| Name | "Name (optional)", placeholder "e.g. Workshop X1" |
| Buttons | "Cancel" and "Add printer" (main; disabled until an Access Code is typed). Busy: "Connecting to the printer…" with a spinner. |
| Result | Success closes it, refreshes the list and shows the snackbar "Added <name>." Failure keeps the form (the Access Code stays only while the dialog is open) with a `bad` notice: the Hub's reason. |

### 9.3 Add a Klipper printer (dialog destination `printers/add-klipper`) and Find Klipper printers

Form: "Address" (placeholder "192.0.2.57 or printer.local", `KeyboardType.Uri`), "Port" (prefilled "7125"), "Name
(optional)", secret field "Moonraker API key (optional)" with the hint "Only if Moonraker asks for one." Buttons
"Cancel" and "Add printer" (busy "Connecting to Moonraker…"). Checked when "Add printer" is pressed, each error
under its field: Address empty "Enter the printer's address."; Port not a number from 1 to 65535 "Enter a port from
1 to 65535." A refusal from the Hub is a `bad` notice above the
buttons with the Hub's reason; the form keeps what was typed.

"Find Klipper printers" (overflow item) opens a sheet: field "Network to search (optional)" with placeholder
"e.g. 192.0.2.0/24" and the hint "Leave empty to search the Hub's own network.", button "Search" ("Searching…").
Results: rows "192.0.2.57:7125" (`--mono`) with "Add" (opens 9.3 with the address filled in). Empty: "No Klipper
printers answered on 192.0.2.0/24." With the Klipper Feature off: 3.5 "Feature off" text.

### 9.4 Printer (`printers/{id}`)

One scrolling column on compact width. On expanded width, as the right pane, the same column. The camera never
autoplays sound.

```
+--------------------------------------+
| <  Workshop X1      (o) Connected ☼ :|
+--------------------------------------+
| (o) Printing · benchy.3mf            |
| [==========---------]  42 %          |
| layer 120 of 284 · 1 h 12 min left · |
| done about 15:40                     |
| Nozzle 215 → 215 °C · Bed 60 → 60 °C |
|                                      |
| [Pause] [Turn the light off] [Stop]  |
|                                      |
| Camera                        [Hide] |
| +----------------------------------+ |
| |          16:9 picture            | |
| +----------------------------------+ |
|                                      |
| Slots                                |
|  AMS A                               |
|  A1 [sw] PLA · PolyTerra Charcoal    |
|          Black   [=====---] 62 %   > |
|  A2 [sw] PETG HF Orange  88 %  in use|
|  A4 [  ] Empty                     > |
|                                      |
| Slot mapping                         |
|  (o) Slots mapped (4)                |
|  [ Map slots again ] [Map by loading]|
|                                      |
| Filament used (last 7 days)          |
|  12.4 g · benchy.3mf · A2      Undo  |
|  2026-11-12 14:05                    |
|                                      |
| Printer settings                   > |
+--------------------------------------+
```

Top bar: title the printer's name, back arrow, overflow "More actions": "Printer settings", "Collect a report",
"Refresh".

**Status panel**

| Element | Text / behaviour |
|---|---|
| State line | Status shape and word (9.1 vocabulary) and the job name: "Printing · benchy.3mf". Not connected: the word and the fix line in the state's colour. No status yet: "No live status from the printer yet." |
| Progress | While printing: determinate progress line, "42 %" at its end in `--mono`, and under it "layer 120 of 284 · 1 h 12 min left · done about 15:40" (`--mono` for numbers). |
| Temperatures | One line, `--mono`: "Nozzle 215 → 215 °C · Bed 60 → 60 °C · Chamber 31 °C"; two nozzles: "Nozzle 1 …, Nozzle 2 …". |
| Alerts | One `bad` notice line per printer alert with the printer's text, or "Printer alert <code>" (the code as the printer sends it, `--mono`) when it gives only a code. |
| Messages | The Hub's notes as `info` lines. |

**Controls** (a row; wraps on narrow screens):

| Control | Text / behaviour | Material 3 |
|---|---|---|
| Pause / Resume | Main button: "Pause" while printing, "Resume" while paused. Absent when nothing is printing. | `Button` |
| Light | "Turn the light on" / "Turn the light off". Only when the printer reports a light. | `OutlinedButton` |
| Stop | "Stop print", danger outlined, placed apart at the right end (on compact width alone on its own line, right-aligned). Only while printing or paused. Opens the dialog below. | `OutlinedButton` (danger) |
| Disabled reason | Under the row: "Available when the printer is connected." or "Waiting for the printer…" while a command is out. | `Text` |
| Result | A notice line under the row: "Paused.", "Light off.", or, when the printer refuses, the sentence in the Hub reply's `message` as sent, the same words the web app and the command line show (until the Hub sends one: "The printer said no: <the reply's `error` text>."; `02-components.md` 8.6 and 12); never the raw reply. | Notice line |

Stop dialog: title "Stop the print?", body "Stop <job> on <printer>? It cannot be resumed." ("Stop benchy.3mf on
Workshop X1? It cannot be resumed."), buttons "Keep printing"
and "Stop print" (danger, filled).

**Camera panel**: title "Camera" with the header action "Hide" / "Show" (remembered per printer on this phone; shown
by default). The picture is 16:9 with `--r` corners on a `--surface-3` ground; it plays only while the screen is
visible. States: "Waiting for the camera picture…" (`--muted`, centred); "The app can't show this printer model's
camera." (no camera kind); failure: `bad` notice with the text for the Hub's error code (table below) and "Try
again". The picture has the content description "Live camera of Workshop X1". A tap on the picture opens it full
screen in landscape with a close button.

| Camera error code | Text |
|---|---|
| `camera_unavailable` | "The camera did not start. Check that the printer is on and that LAN Mode Liveview is turned on in the printer's network settings (Settings > Network/LAN)." |
| `not_configured` | "Set up this printer first: enter its Access Code under Printers." |
| `not_found` | "The Hub has no camera view for this printer." |
| `unauthorized` (or HTTP 401) | the Hub notice "No longer paired" (3.4) in place of the picture |
| `cert_changed` | "The printer's certificate changed. If you reset the printer or replaced its mainboard, forget its old certificate in Printer settings. If not, something else may be answering at the printer's address: check the printer's IP address first." |
| any other code | "The camera could not be shown right now. Leave this screen and come back to try again." |

**Slots panel** (9.5). **Slot mapping panel** (9.7). **Filament used panel** (9.10). A final row "Printer settings"
with a chevron opens 9.9.

TalkBack order: back, title, connection, appearance, More actions; state line, progress (one node: "Printing
benchy.3mf, 42 percent, layer 120 of 284, 1 hour 12 minutes left"), temperatures, alerts, controls (Pause, Turn the
light off, Stop print), camera (Hide, picture), each slot row, Slot mapping, Filament used, Printer settings.

### 9.5 Slots panel

Title "Slots". One group per unit, titled by the unit ("AMS A", "AMS HT A", "Toolhead"). One row per slot
(`ListItem` minimum height): slot label in `--mono` (fixed `slot-label` column), swatch, headline "<material> · <spool name>" or "Empty"
(dashed swatch), supporting "<n> g left" with a level bar, and the tag "In use" for the active slot. Slot messages
from the Hub follow the group as `info` lines.

Tapping a row opens the **slot sheet** (`ModalBottomSheet`):

| Slot holds | Sheet title | Content and actions |
|---|---|---|
| A spool from the inventory | "Slot A1" | Spool summary row; buttons "Open spool" (main; opens `spools/{id}` in the Spools destination) and "Unload" (outlined). |
| Filament the inventory does not know | "Slot A1" | "This slot holds PLA that is not linked to a spool." Button "Load a spool" (main). |
| Nothing | "Slot A4" | "This slot is empty." Button "Load a spool" (main). |

"Load a spool" opens 9.6. "Unload" runs the dry run and opens the dialog: title "Unload from <slot>?" ("Unload from
A1?"), body "Unload Polymaker PolyTerra PLA Charcoal Black from A1? It goes back to Shelf A. Only the inventory
changes; the printer's slot setting stays as it is.", buttons "Cancel" and "Unload" (main). Result: notice line under
the slots, "Unloaded from A1. Spool 214 is back on Shelf A."

### 9.6 Pick a spool for a slot (`printers/{id}/slots/{slot}/pick`)

Header "Load into Workshop X1, slot A4". The Spools search of 7.1 (same field, chip and results) with the tag hint
"Or hold the spool's tag to the back of the phone." While this screen is open a tag tap picks that spool instead of
opening it. Picking a spool opens the preview step of 7.6 for this printer and slot; after loading, Back returns to
the printer screen.

### 9.7 Slot mapping panel

Title "Slot mapping" (Bambu) or "Slot names" (Klipper). Content:

| Part | Text / behaviour |
|---|---|
| Status | Shape and word: running "Mapping slots…" (half-filled circle, progress line, step text from the Hub); "Slots mapped (4)" with "The slot numbering is confirmed." (filled circle); "Slots mapped: confirmed for the loaded slots" (filled circle); "Layout changed: map again" (triangle); "Recent prints disagreed with the map: map again" (triangle); "The last slot mapping did not confirm the numbering" (triangle); "Slot numbering not confirmed" (triangle); "The last slot mapping failed" (octagon); "Slot mapping failed" (octagon). |
| Detail | The Hub's detail line, `--fs-s`. |
| Not counted yet | When mapping has not succeeded: `info` line "Filament use is only logged for this printer, not taken off spools, until slot mapping succeeds." |
| Problems | Heading "Problems the Hub reported:" (or "Also reported during mapping:", or "From an earlier mapping; it may be fixed by now:" in `--muted`) and one line per problem (`bad`, or `--muted` when old). |
| Notes | "Not settled yet:" and the Hub's notes. |
| Buttons | "Map slots" or "Map slots again": main when the Hub's reason calls for a new mapping, otherwise outlined. Disabled unless the printer is connected (or needs Developer Mode) and idle, with the reason under it: "Available when the printer is connected." / "Available when the printer is idle." "Map by loading filament": main when automatic mapping can't confirm the numbering, otherwise outlined; opens 9.8. |
| Report | "Collect a report" (outlined; main when the Hub says a report would help), with the line "The file holds no serial number, address, name or account id." |

**One filled button per printer screen (F1.2).** Pause / Resume (9.4), "Map by loading filament", "Map slots" /
"Map slots again" and "Collect a report" can each be the main button. When more than one of their conditions holds,
only the first in this order is filled and the others are outlined: 1. "Pause" / "Resume" while a print is running
or paused; 2. "Map by loading filament" when automatic mapping can't confirm the numbering; 3. "Map slots" / "Map
slots again" when the Hub's reason calls for a new mapping; 4. "Collect a report" when the Hub says a report would
help. Disabled buttons never count as the filled one.

"Map slots" asks first: dialog "Map the slots of <name>?" ("Map the slots of Workshop X1?"), body "The printer
changes its slot colours briefly and runs a short job with no motion. The colours are put back afterwards.", buttons
"Cancel" and "Map slots" (main). That the printer must be idle is the button's disabled reason above, not part of
the dialog. While running, the panel polls every 2 s (backing off to 30 s after
failures).

**Report sharing.** "Collect a report" shows "Collecting a report…" in the button, then opens the Android share sheet
(`Intent.ACTION_SEND` through the app's `FileProvider`) with the file "printer-report-<model>.zip" and the subject
"Printer report". Failure: `bad` notice line under the button with the reason and "Try again".

### 9.8 Map by loading filament (`printers/{id}/map-by-loading`)

Top bar title "Map by loading filament", back arrow. Page header: the printer's name.

| State | Content |
|---|---|
| Starting | Progress line, "Starting…". Failure: `bad` notice and "Try again". |
| Instruction | The Hub's instruction in `--fs-l` `--fw-title`, e.g. "Load any filament into slot 1 of AMS A." |
| Waiting for the load | Indeterminate progress line, "Waiting for the printer to show the load…" |
| Settling | Progress line, "The printer shows a change. Waiting a few seconds for it to settle…" |
| Question | The Hub's question ("Did you load slot 1?"). With two nozzles: "Which nozzle did you load it to?" with filter chips "Left nozzle" and "Right nozzle". Buttons "Yes" (main) and "No, I loaded another one" (outlined; opens the dialog "Which one did you load?" with one button per position and "Cancel"). |
| By hand (printer cannot report loads) | "Which slot is it in?" and one button per choice; the line "Saved as you say: the printer can't check it." |
| Always | Text buttons "Skip slot 1" and "Stop" at the bottom. |
| Progress list | Panel "Slots": one row per position with its status: "A1: confirmed (A1, left nozzle)", "entered by hand (A2)", "skipped", "not answered yet", "not mapped". |
| Lost contact | `info` line "Lost touch with the Hub for a moment; still trying…" |
| Finished | Summary line from the Hub, then "Share this map in a printer report, so other owners of this model benefit? Nothing is sent unless you choose to." with "Yes, how do I share it?" (opens the report sharing of 9.7) and "No thanks"; then "Done" (main; back to the printer). |

Stop and Back while open ask: dialog "Stop mapping <name>?" ("Stop mapping Workshop X1?"), body "The positions
confirmed so far are kept.", buttons "Keep mapping" and "Stop mapping" (danger).

### 9.9 Printer settings (`printers/{id}/settings`)

Top bar title "Printer settings", back arrow. A panel of rows (`ListItem`, chevron), one per setting, with its
current value as the supporting line; each opens a dialog (a bottom sheet on compact width).

| Row (Bambu) | Row (Klipper) | Dialog title | Field and hint | Action button |
|---|---|---|---|---|
| Name · "Workshop X1" | Name | "Rename printer" | "Name" | "Rename" |
| Address · "192.0.2.40" | Address · "voron.example:7125" | "Change address: <name>" | "Address" (+ "Port" for Klipper). Bambu also asks the Access Code, hint "The Hub needs the Access Code again when the address changes." | "Change address" |
| Access Code · "Set" | | "Replace Access Code: <name>" | Secret field "Access Code", hint "On the printer: Settings > Network/LAN > Access Code." | "Replace Access Code" |
| | API key · "Set" / "Not set" | "Moonraker API key: <name>" | Secret field "Moonraker API key", hint "Leave empty to remove the API key." | "Save key" |
| Certificate · "Pinned" (only when one is pinned) | | "Forget the certificate of <name>?" | Text "The next connection pins the certificate <name> shows then. Enter its Access Code to go on." and the secret field "Access Code". | "Forget certificate" (danger) |

Each dialog: "Cancel" and its action button (main, or danger where the table says so; while busy "Saving…", or
"Saving and connecting…" when the printer is contacted). Errors appear under their field when the action button is
pressed:

| Field | Error |
|---|---|
| Name empty | "Enter a name." |
| Address empty | "Enter the printer's address." |
| Port (Klipper) not a number from 1 to 65535 | "Enter a port from 1 to 65535." |
| Access Code empty where it is needed | "Enter the Access Code shown on the printer." |

Address hint: "An IP address or a name; a name is kept as you type it." Port hint (Klipper): "Moonraker's port.
Leave empty to keep it." A refusal from the Hub is a `bad` notice in the dialog with the Hub's reason; the dialog
keeps what was typed (secrets only while it is open). Success closes the dialog, updates the row, and shows the result line at the top of the
screen ("Renamed to Workshop X1.", "Address changed. The printer answers.").

Below a divider: "Forget printer" (danger outlined). Dialog: title "Forget <name>?" ("Forget Workshop X1?"), body
(Bambu Lab) "Spoolwarden stops connecting to it and deletes its Access Code. To use it again, add it again." or
(Klipper) "Spoolwarden stops connecting to it and deletes its Moonraker API key, if one is saved.", buttons "Cancel"
and "Forget printer" (danger, filled). Success returns to `printers` with the snackbar "Forgot Workshop X1."

### 9.10 Filament used panel

Title "Filament used (last 7 days)". Rows: headline "12.4 g · benchy.3mf · A2" (`--mono` for numbers), supporting
"2026-11-12 14:05 · <note>". Notes: "undone", "logged only", "no spool in that slot, nothing taken off", "not taken
off a spool: <reason>", with the reason from the Hub's error code:

| Code | Reason |
|---|---|
| `file_not_found` | "print file not found on the printer" |
| `no_slice_info` | "the print file has no filament amounts" |
| `plate_not_found` | "the printed plate was not in the print file" |
| `printer_unreachable` | "the printer could not be reached" |
| `cert_changed` | "the printer's certificate changed" |
| `spoolman_unreachable` | "Spoolman could not be reached" |
| `spoolman_failed` | "Spoolman refused the change" |
| `ambiguous_spool` | "two spools are set to that slot" |
| `no_mapping` | "the printer didn't say which slots it used" |
| `unmapped_slot` | "that slot isn't in the slot map: run Map slots" |
| any other code | the code with underscores as spaces |

Trailing "Undo" (text button, 48 dp) where allowed. Undo asks: dialog "Put it back on the spool?", body
"Put <g> g back on the spool? (<job>, <slot>, <time>)" ("Put 12.4 g back on the spool? (benchy.3mf, A2,
2026-11-12 14:05)"), buttons "Keep" and "Put it back" (main). Result: the row shows "undone" and a notice line
"12.4 g put back on spool 214." Empty: "Nothing logged in the last 7 days."

---

## 10. Recently added

New in the app, matching the web app and the Hub page: the newest spool additions with their label photos; correct
them by hand or with the Label Reader, and undo a revision.

Requests: `GET api/intake/history`, `GET api/intake/history/{hid}`, `GET api/intake/history/{hid}/photos/{n}`
(JPEG), `POST api/intake/history/{hid}/revise` with `{item, note}`, `POST api/intake/history/{hid}/apply` with
`{proposal}` or `{item, values}`, `POST api/intake/history/{hid}/undo` with `{revision}`. These are the Hub's paired
API routes that the app's pairing already allows.

### 10.1 Recently added (`recent`)

```
+--------------------------------------+
| Recently added      (o) Connected ☼  |
+--------------------------------------+
| The newest 20 spool additions are    |
| kept with their photos (14.2 MB now).|
| [ All 5 | To check 2 ]               |
| +----------------------------------+ |
| |[ph] Polymaker PolyTerra PLA    > | |
| | 2   Charcoal Black               | |
| |     2026-11-12 14:05 · Spool 214 | |
| |     ( ) As detected              | |
| |     /\ Colour: medium            | |
| |----------------------------------| |
| |[ph] Bambu Lab PETG HF Orange x2> | |
| |     2026-11-12 09:41 ·           | |
| |     Spools 212, 213              | |
| |     (i) Revised by AI            | |
| +----------------------------------+ |
+--------------------------------------+
```

| Element | Text / behaviour | Material 3 |
|---|---|---|
| Header facts | "The newest 20 spool additions are kept with their photos (14.2 MB now)." from `keep` and `photo_bytes`. When the Label Reader is off: an extra line with the hollow circle "The Label Reader is switched off. Correct by hand, or switch it on in Features on the Hub page." | `Text` |
| Filter | Segmented control "All 5" / "To check 2". Shown only when the Hub sends read confidence (16); otherwise absent. | `SingleChoiceSegmentedButtonRow` |
| Rows | Thumbnail `thumb-s` of the first photo with the photo count in a small `--mono` badge, or a dashed box with "No photo" for the screen reader; headline the filaments ("Polymaker PolyTerra PLA Charcoal Black", "×2" tag when several spools); supporting "2026-11-12 14:05 · Spool 214" (`--mono`; "Spools 212, 213"); the state as a status; the source word ("From a phone photo", "From the Weigh Station", "Added by hand"); when there is confidence data, the lowest mark ("Colour: medium", "Low: Material, Net weight"). Chevron. Tapping opens `recent/{hid}`. | Panel, `ListItem` |
| Empty | Empty state with the clock icon: title "Nothing added yet", text "No spool has been added since the history started. Spools added from the web app, the app or the Weigh Station appear here." | Empty state |

Record state vocabulary (the badges of `02-components.md` 7.1, as on the Hub page):

| State (Hub's `state`) | Shape and colour | Word |
|---|---|---|
| `detected` | hollow circle, `--muted` | As detected |
| `revised_ai` | info circle, `--info` | Revised by AI |
| `edited` | pencil, `--info` | Edited by hand |

The Hub's `source` value is shown in words: phone reads "From a phone photo", Weigh Station reads "From the Weigh
Station", records without photos "Added by hand"; any other value is shown as the Hub gives it.

### 10.2 Record (`recent/{hid}`)

```
+--------------------------------------+
| <  PolyTerra PLA Ch… (o) Connected ☼ |
+--------------------------------------+
| 2026-11-12 14:05 · From a phone photo|
| ( ) As detected · Spool 214          |
|                       [<] [>]        |
| Photos 2                             |
| [photo][photo]                       |
|                                      |
| Fields          [ (pencil) Edit ]    |
|  IDENTITY                            |
|  Brand       Polymaker               |
|  Name        PolyTerra PLA Charcoal  |
|              Black                   |
|  Material    PLA                     |
|  Colour      [sw] #2B2B2E            |
|              /\ Medium               |
|  WEIGHTS ...                         |
|                                      |
| Ask the Label Reader to correct it   |
|  [What is wrong?                   ] |
|  [ Ask the Label Reader ]            |
|                                      |
| Revisions 1                          |
|  Revision 1, 2026-11-12 14:09, by    |
|  hand: Empty spool weight            |
|  150 → 140 g                         |
|  [ (undo) Undo revision 1 ]          |
+--------------------------------------+
```

| Element | Text / behaviour | Material 3 |
|---|---|---|
| Top bar | Title: the filament name; back arrow; overflow "Open spool 214" (opens `spools/214` in the Spools destination; one item per spool). | `TopAppBar` |
| Header | Meta row: "2026-11-12 14:05 · From a phone photo", the state, "Spool 214" (`--mono`). Two icon buttons "Newer record" and "Older record" (disabled at the ends) step through the list without going back. | `Row`, `IconButton` |
| Photos panel | Title "Photos (2)", the count in brackets. Thumbnails `thumb` square in a `LazyRow`; each has the content description "Label photo 1 of 2, opens it large". Tapping opens 10.5. No photo: "No photo: this spool was added by hand." | Panel, `LazyRow` |
| Fields panel | Title "Fields", the tag "Read confidence is high unless marked" (only with confidence data), header action "Edit by hand" (pencil icon; opens 10.3 for this item). Field rows in four groups: **Identity** Brand, Name, Material, Colour (swatch + hex); **Weights** Net weight, Empty spool weight, Density; **Temperatures** Nozzle, Bed, Nozzle range, Bed range; **Other** Price per kg, Line. Empty values read "(empty)" in `--muted`. Confidence marks as in 6.3 next to the value. When one record saved several items, there is one Fields panel per item, titled "Spools 212, 213" with the line "A change applies to both." | Panel, field rows |
| Ask the Label Reader panel | 10.4. | Panel |
| Revisions panel | Title "Revisions (2)", the count in brackets. One entry per revision: "Revision 1, 2026-11-12 14:09, by hand: Empty spool weight 150 → 140 g" (`--mono` for the change); undone ones are struck through and followed by "(undone)" (02 7.10; text, not a badge). The newest live revision has the button "Undo revision 1" (outlined, undo icon). None: "No revisions. Corrections by hand or by the Label Reader appear here." | Panel |

Undo asks: dialog "Undo revision 1?", body "Empty spool weight goes back to 150 g.", buttons "Cancel" and "Undo" (main).
Result: notice line in the Revisions panel "Revision 1 undone. Empty spool weight is 150 g again." plus, when the Hub
reports them, "The spools now use filament 42 (new)." and "Filament 41 has no spools left; it was not deleted."

TalkBack order: back, title, connection, appearance, More actions; meta row, Newer record, Older record; Photos;
Fields (each row read as "Colour, 2B2B2E, medium"), Edit; Ask the Label Reader; Revisions.

### 10.3 Edit by hand (`recent/{hid}/edit/{item}`)

Top bar title "Edit by hand", back arrow. The same four groups as text fields (`OutlinedTextField`, `--mono` for
numbers, units as suffixes), prefilled with the saved values; confidence marks stay until the field is changed.
Action bar: "Cancel" (text) and "Save changes" (main; "Saving…"). Only changed fields are sent
(`{item, values}`). Nothing changed: the line "Nothing changed." next to the button, and nothing is sent. Success
returns to 10.2 with its Fields panel result line "Saved 2 changes: Name, Nozzle range. Only these were sent." and
the record's state "Edited by hand". Errors under their fields; others as a `bad` notice. Leaving with changes
asks (2.5 rule 1).

### 10.4 Ask the Label Reader to correct it

A panel on 10.2, titled "Ask the Label Reader to correct it".

| State | Content |
|---|---|
| Ready | Field "What is wrong?" (placeholder "e.g. brand is Polymaker", up to 3 lines); hint "The Label Reader reads the photos again with your note and suggests changes. Nothing changes until you accept."; button "Ask the Label Reader" (outlined). Empty note: error "Say what is wrong first, e.g. brand is Polymaker." |
| Waiting | Progress line and "Asking the Label Reader… (up to a minute)". |
| Proposal | Before-and-after change list (02 7.9) with `--accent-soft` ground and a 1 dp `--accent-text` outline: heading "Proposal: 2 changes", one row per change: field name, old value struck through in `--muted`, arrow, new value at `--fw-label` ("Name: PolyTerra PLA Charcoal Black → PolyTerra PLA Charcoal Black (Matte)"); TalkBack reads "Name, PolyTerra PLA Charcoal Black, becomes PolyTerra PLA Charcoal Black (Matte)". With no photo kept: "No photo was kept for this record: the Label Reader worked from the saved values and your note." Buttons "Accept" (main) and "Discard" (outlined). |
| No change | "The Label Reader changed nothing." |
| Accepted | `ok` line "Accepted. 2 fields changed; revision 2 keeps the old values." |
| Discarded | Hollow-circle line "Proposal discarded. Nothing changed." |
| Label Reader off | Field and button disabled, line "The Label Reader is switched off. Correct by hand, or switch it on in Features on the Hub page." |
| Failure | `bad` notice with the reason (texts of 6.2 where they apply) and "Try again". |

### 10.5 Photo viewer (`recent/{hid}/photos/{n}`)

Full screen, `--bg` ground, no bars except a close `IconButton` ("Close photo") and the line "Photo 1 of 2" at the
top. `HorizontalPager` across the record's photos; pinch and double-tap zoom. Photos are never inverted in dark
(F5). Loading: "Loading photo…"; failure "The photo could not be loaded." with "Try again".

---

## 11. Slicer presets

### 11.1 Home panel

Panel "Slicer presets" on Home; the whole header is a link to 11.2 (chevron). Request: `GET api/profiles/status`.

| Case | Lines |
|---|---|
| Status not available | "Slicer preset status is not available right now." (`--muted`) |
| Built | "24 presets for 9 lines, built 3 hours ago" |
| Last build failed | "The last preset build failed: <the Hub's error>" (`bad` line) |
| Never built | "No presets built yet" |
| Installed on the PC | "Installed on your PC 2 hours ago" (filled circle) |
| Slicer Sync not set up | "Slicer Sync is not set up" (hollow circle) |
| Not installed yet | "Not installed on your PC yet" (triangle) |

The panel is absent until the app is paired.

### 11.2 Slicer presets (`presets`)

Top bar title "Slicer presets", back arrow. The status lines of 11.1 as field rows (Built, Last build, On your PC).
An `info` line: "Presets are built on the Hub and installed on your PC by Slicer Sync the next time the slicers are
closed." A panel "Missing a product line?" with the text "If a filament's line is not in the Filament Catalog, add
it so presets can be built for it." and the outlined button "Add a line to the Filament Catalog" (opens 8).

A panel "Product lines" lists the lines the Hub knows, as on the Hub page and in the web app (the
app's existing product-lines route). One row per line: headline "<brand> <product line>", supporting
"<material> · <n> presets", and a second supporting line "Bambu Studio parent: <name>" or "Bambu Studio parent:
none" with the triangle (a line without a parent builds no presets). The row's action is the text button "Change
parent"; it opens a sheet titled "Bambu Studio parent of <line>" with the field "Find a parent" (a search over the
parents Slicer Sync has reported), the list of matches as radio rows, and the buttons "Save" (main) and "Cancel".
Saving shows the inline result "Saved. A preset build was asked for." on the row; the Hub's refusal is shown as
given. No parents reported yet: the sheet says "Slicer Sync has not reported any parents yet. It reports them
when it runs." and has only "Close". Empty list: "No lines yet. They are made from the filaments in Spoolman at the
next build or when a spool is added." Loading: three skeleton rows. The list is paged at 50.

A last line: "Attach filaments to lines and build presets now on the Hub page or in the web app." with the text
button "Open the Hub page".

---

## 12. Settings

### 12.1 Settings (`settings`)

A list of groups, each a `ListItem` row with an icon, a title, a one-line live summary and a chevron. Works without a
Hub connection.

| Row | Summary | Opens |
|---|---|---|
| Appearance | "System · Console" | 12.2 |
| Hub connection | "Workshop hub · Connected" (or the state word) | 12.3 |
| App updates | "App 0.5.2 · up to date" / "Update ready: 0.5.3" (with the dot of 2.3) | 12.4 |
| Licences | "Free software under GPL-3.0-or-later" | 12.5 |
| Developer | "Debug build tools" (debug builds only) | 12.6 |

On expanded width the list is the left pane and the chosen group the right pane (`ListDetailPaneScaffold`).

### 12.2 Appearance (`settings/appearance`)

| Element | Text / behaviour |
|---|---|
| Appearance | Group title "Appearance". Segmented control with icons and words: "Light", "Dark", "System". Applies at once. |
| Theme | Group title "Theme". Four preview tiles in a 2 × 2 grid on compact and medium width, one row of four on expanded width: each tile a small drawing of the theme in its own colours, the name and one line: "Console" "Dense and technical"; "Workbench" "Calm cards"; "Palette" "Colourful and roomy"; "Panes" "Simple lists". The tiles are a radio group; the chosen one has a 2 dp `--accent-text` outline and a check mark. Choosing applies at once, with no save button. |
| Note | "These choices are kept on this phone only." |

Stored in the app's settings store (DataStore) beside each other. When nothing is chosen yet the app uses System and
Console.

### 12.3 Hub connection (`settings/hub`)

| Element | Text / behaviour | Material 3 |
|---|---|---|
| Status | Shape and word (2.4) with the last answer time. | Status |
| Field rows | "Hub" Workshop hub; "Address" 192.0.2.10:8710 (`--mono`); "Certificate fingerprint" (grouped, `--mono`, selectable); "Hub version" 0.5.2. None paired: "No Hub is paired." with the main button "Pair with a Hub". | Panel, field rows |
| Open the Hub page | Outlined button "Open the Hub page", with the line "Features, keys, devices and backups are set on the Hub page." Opens the Hub page's address (today `https://<host>:<port>/setup`) in the browser. Errors: "No browser on this phone could open it." / "The Hub's address isn't known yet." | `OutlinedButton` |
| Pair again | Outlined button "Pair again" (opens `pair`). | `OutlinedButton` |
| Fingerprint check | Group "Security". Switch row "Check the fingerprint when pairing by address", on by default, with the supporting text "When this is off, the app trusts the certificate a Hub presents when you pair by typing its address. A scanned QR code is always checked." Turning it off asks: dialog "Skip the fingerprint check?" / "Only do this on a network you trust." / "Cancel" / "Skip the check". | `ListItem` + `Switch` |
| Forget this Hub | Below a divider, danger outlined "Forget this Hub". Dialog: title "Forget Workshop hub?", body "This phone stops using it until you pair again. Drafts stay on this phone.", buttons "Cancel" and "Forget" (danger, filled). Afterwards the pairing graph opens. | `OutlinedButton` (danger), `AlertDialog` |

### 12.4 App updates (`settings/updates`)

Field rows "This app" 0.5.2 and "On the Hub" 0.5.3 (`--mono`), then the update panel of 13, then the text button
"Check for updates" (runs `GET api/info` now; "Checking…"; result line "This app is up to date." or the panel
changes).

### 12.5 Licences (`settings/licences`)

Top bar title "Licences", back arrow. A `LazyColumn`: the line "Spoolwarden is free software under
GPL-3.0-or-later. It comes with no warranty."; the outlined button "Show the GPL-3.0 text" / "Hide the GPL-3.0
text"; then the bundled `LICENSE` (when shown) and `THIRD-PARTY.md` rendered as headings (`--fs-l` `--fw-title`), paragraphs,
bullet lists, and tables as rows of field rows. A missing file shows "<name> is missing from this build." Works
offline. Both files are read and parsed off the main thread (1, Threads), with skeleton rows until they are ready.

### 12.6 Developer (`settings/developer`, debug builds only)

Field "Tag ID" (`--mono`) and button "Simulate a tag tap": behaves as a real tap (2.6). Absent from release builds.

---

## 13. App updates

The Hub carries the app's package. The app compares its version with the one the Hub offers (`GET api/info`) and
downloads it from `GET /app.apk` over the pinned connection; Android's package installer does the install
(`REQUEST_INSTALL_PACKAGES`).

The update panel appears on 12.4, and as a one-line notice on Home (5) that links to it.

| State | Panel content | Button |
|---|---|---|
| Up to date | Filled circle "This app is up to date." | none |
| Update offered | `info` "Spoolwarden 0.5.3 is on your Hub. This app is 0.5.2." | "Install update" (main) |
| Hub newer than the app | `warn` "Update the app: the Hub is newer than this app, so some things may not work." | "Install update" (main) |
| Downloading | Determinate progress line and "Downloading… 42 %" (indeterminate "Downloading…" while the size is unknown). | "Cancel" (text) |
| Needs permission | `warn` "Allow Spoolwarden to install apps, then tap Install update again." | "Open settings" (opens the system "Install unknown apps" page for Spoolwarden) |
| Installing | "Tap Install in the window Android shows." | none |
| Waiting for the install to be confirmed (Android's install window was closed or went to the background without an answer) | `info` "The update is downloaded. Tap to install to open Android's install window again." On Home the notice reads "Update downloaded: tap to install." | "Tap to install" (main; opens Android's install window again without downloading) |
| Installed | The app restarts on the new version; snackbar "Updated to 0.5.3." | none |
| Signature refused | `bad` "Android refused this update because it is not signed like the app on this phone. Do not install it; check where the app on your Hub came from." and the text button "What this means", which opens a dialog: title "An update signed with a different key", text "An update signed with a different key is what a forged app looks like, so Android refuses it and the app on this phone stays as it is. If you built or replaced the app on your Hub yourself, that is the reason. If you did not, do not install it: check where the app on your Hub came from.", button "Close". The app never tells the person to uninstall in this case, here or anywhere else: uninstalling is the one step that would get a forged app past this protection. | "Try again" (outlined; it picks up a corrected copy on the Hub) |
| Failures | `bad` with one of: "Could not reach the Hub. Check that you are on the same network.", "The Hub has no app update to download.", "The Hub's certificate changed.", "A newer version is already installed.", "The download was damaged. Try again.", "Not enough storage on this phone.", "The install was blocked on this phone.", "This update does not work on this Android version.", "The download timed out. Try again.", "The update could not be installed." | "Try again" (main) |

---

## 14. Accessibility

`07-accessibility.md` holds the rules for every interface; this section gives the Android specifics.

### 14.1 Touch targets

- Every tappable thing is at least 48 × 48 dp (`minimumInteractiveComponentSize()`), including chips, the photo
  remove buttons, row actions ("Undo", "Remove", "Unload"), the segmented control's parts and the connection chip.
  A control drawn smaller (the connection chip, `chip` tall) gets a hit area that reaches 48 dp.
- Check rows and switch rows toggle on the whole row (`Modifier.toggleable` with `Role.Checkbox` / `Role.Switch`),
  never on the box alone.
- Adjacent targets keep 8 dp between their hit areas; the danger button is never next to the button that confirms.

### 14.2 Content descriptions

| Element | Content description |
|---|---|
| Back arrow | "Back" |
| Appearance icon | "Appearance: System" (the current choice), menu items "Light", "Dark", "System" with the selected state |
| Connection chip | "Hub connection: Connected. Opens details." |
| More icon | "More actions" (on a row: "More actions for Workshop X1") |
| Status shapes next to a word | none (decorative); the word is read |
| Swatch | "Colour 2B2B2E"; empty slot "Empty slot" |
| Level bar | merged with its text: "62 percent left: 620 of 1000 grams" |
| Photo thumbnail | "Label photo 1 of 2" (record) / "Photo 2" (draft) |
| Remove photo | "Remove photo 2" |
| Camera picture | "Live camera of Workshop X1" |
| QR viewfinder | "Camera viewfinder. Point it at the QR code." |
| Clear search | "Clear search" |
| Secret field toggle | "Show Access Code" / "Hide Access Code" |
| Newer / older record | "Newer record" / "Older record" |
| Theme tile | "Console, dense and technical, selected" |
| Bottom bar items | the label, plus the badge ("Printers, 1 needs a look") |

Rows that hold several texts are one TalkBack node (`Modifier.semantics(mergeDescendants = true)`), with their
actions offered as custom actions (`CustomAccessibilityAction`: "Open", "Discard", "Unload", "Put it back").

### 14.3 TalkBack order

Order follows the layout: top bar (back, title, connection, appearance, overflow), then the content top to bottom,
left column before right column on two-column layouts, then the sticky action bar, then the navigation bar or rail.
Main screens: Home 5, Spools 7.1, Spool 7.2, Printer 9.4, Record 10.2; Check the spools: page header, summary line,
questions, each spool panel (header node first, then its fields group by group), the reason line, then the action
bar. Headings (page headers, panel titles, group titles) carry `Modifier.semantics { heading() }` so TalkBack can
jump between them. Opening a screen moves focus to its title; closing a sheet or dialog returns focus to the control
that opened it.

### 14.4 Announcements

Result lines and inline notices are live regions (`liveRegion = LiveRegionMode.Polite`); a `bad` result that blocks
the person uses `Assertive`. Snackbars are announced by the host. Progress text changes ("Reading 2 photos…") are
announced once when they start and once when they end, not on every percent.

### 14.5 Text size and motion

- All text scales with the phone's font size up to 200 %; rows grow in height, nothing clips; the top bar title
  wraps to two lines before it ellipsizes when the font scale is over 130 %.
- When the phone's animator duration scale is 0 (Remove animations), all transitions are instant and spinners are
  replaced by the word "Working…" (F4.3).
- Colour is never the only signal: every status has its shape and word (F10); confidence marks have words; the
  selected tile has a check mark.

---

## 15. Strings and wording

- Every user-visible text, including content descriptions, snackbar texts, dialog texts and error words, is in
  `res/values/strings.xml`. Counts use `<plurals>` ("1 photo" / "2 photos", "Add 1 spool" / "Add 3 spools").
  Values are inserted with positional arguments (`%1$s`, `%1$d`); sentences are never built by joining pieces in
  code.
- Keys are `<screen>_<element>[_<state>]` in lower case: `home_add_from_photos`, `pair_code_error_length`,
  `spool_weight_saved`, `printer_stop_dialog_title`. Shared texts start with `common_` (`common_cancel`,
  `common_try_again`, `common_hub_unreachable`).
- A lint check fails the build when a string literal is passed to `Text`, `label`, `placeholder`,
  `supportingText`, `contentDescription` or a snackbar call.
- The product's name is never written into a text: the catalogue holds it once (`app_name`, also the launcher
  label) and texts that name it use the `{product}` placeholder, which the generator fills
  (`08-platform-mapping.md` section 12). The command's name is held the same way (`command_name`, `{command}`).
- Text that comes from the Hub (its messages, printer alerts, the Label Reader's questions, names) is shown as
  given and never translated or reworded by the app.
- Wording follows F2: the names of F2 everywhere ("Hub", "Hub page", "Label Reader", "Weigh Station", "Recently
  added", "Filament Catalog", "Slicer presets", "Slicer Sync"); sentence case; units after a space ("210 °C",
  "862 g"); the single character "…"; dates as `2026-11-12 14:05` in lists and logs and as relative words in
  summaries, with the exact time on long-press.
- One term per thing, as the shared wording table of `08-platform-mapping.md` section 12: "Weight with spool",
  "Try again", "Leave empty to choose automatically.", "Slicer presets", "Drafts". The keys are shared with the web
  pages through the string catalogue, and its test (08 test 7) fails when the app and the pages differ.
- Numbers, addresses, serials, fingerprints, tag IDs and weights are set in `--mono` with tabular figures.

---

## 16. Needs from the Hub

The design above works with the Hub as it is. These additions to the Hub's paired API make parts of it complete:

| Need | Used by | Until it exists |
|---|---|---|
| Per-field read confidence levels (high, medium, low, not on the label) for each item in the answer of `POST api/intake/read`, and per saved item in `GET api/intake/history/{hid}`. | 6.3 marks "Medium" and "Low"; 10.2 field marks | The app marks only "Estimated" (from `estimates`) and "Not on the label" (empty fields). |
| A per-record confidence summary (the lowest level and the fields concerned) in `GET api/intake/history`. | 10.1 "To check" filter and row marks | The filter and the row marks are absent. |
| A single spool by number: `GET api/spools/{id}` with location, remaining and net weight, tag, sealed or opened, filament number, empty spool weight and lot. | 7.2 Details, deep links, restoring after the app was stopped | The spool screen shows the fields the search or tag answer carries; after a restart it shows the last summary and refreshes after the first change. |
| Phone-callable Slicer presets actions: list filaments without a preset line, add them to a line, create a line, build presets now (today these exist only under `api/profiles/web/`, which phones may not call). | 11.2 | 11.2 points to the Hub page and the web app. |
| The Hub's default theme ("Theme for new devices", F6.2) in `GET api/info` as the field `look` (for example `"look": "console"`). | 12.2 first start | The app starts on Console. |
| A per-item structure in the dry-run answer of `POST api/intake/add` (what is created, what is reused, where each spool goes). | 6.5 rows | The app shows the Hub's lines one per row. |

Routes this design uses that today's app does not call, all already on the Hub's paired API (`server/filament_kit/api.py`,
behind the paired-device check), so they need nothing new from the Hub:

| Route | Used by |
|---|---|
| `POST api/printers/scan` with `{subnet?}` | Find Klipper printers 9.3 |
| `POST api/printers` with `family: "klipper"`, host, port, name, API key | Add a Klipper printer 9.3 |
| `GET api/intake/history`, `GET api/intake/history/{hid}`, `GET api/intake/history/{hid}/photos/{n}`, `POST api/intake/history/{hid}/revise`, `/apply`, `/undo` | Recently added 10 |

---

## 17. Where today's screens and controls went

Every route, screen, dialog and flow of today's app (`filament-kit` Android app), and where it is in this design.

### 17.1 Routes and screens

| Today | Where it is now |
|---|---|
| Route `pair` (Choose, Address, Confirm, Code, Done steps inside one route) | Pairing graph, one destination per step: `pair` 4.3, `pair/address` 4.5, `pair/fingerprint` 4.6, `pair/code` 4.7; Done is the snackbar on Home (4.7) |
| Pair banner (unpaired message) | 4.1 |
| Local network permission gate and `LocalNetworkPanel` | `pair/network-access` 4.2; the same panel on Hub-backed screens 3.3; Home notice 5 |
| QR scanner takeover | `pair/scan` 4.4 |
| Certificate mismatch panel (STORED, QR, MANUAL) | `pair/certificate/{source}` 4.8 |
| Route `home` | `home` 5 |
| Route `search` | Spools destination root `spools` 7.1 |
| Route `add?tag&draft&manual` (stages Capture, Reading, Review, Previewing, Preview, Adding, Done) | `add/{draftId}/photos` 6.2 (Capture, Reading), `/review` 6.3, `/preview` 6.5 (Previewing, Preview, Adding), `/done` 6.6 |
| Route `profile/add` (Add profile) | `catalog/new` 8 |
| Route `settings` | Settings destination root `settings` 12.1 with `settings/hub` 12.3 |
| Route `settings/licences` | `settings/licences` 12.5 |
| Route `printers` with `PrintersEntry` local state (list, printer, manual map) | Printers destination: `printers` 9.1, `printers/{id}` 9.4, `printers/{id}/map-by-loading` 9.8, all real destinations |
| "Not paired" placeholder (Search, Add, Add profile, Printers) | Hub notice 3.4 where the request's result would appear, screen and typing kept (2.7); its "Pair again" opens the pairing graph with the banner 4.1 |
| Spool card `Dialog` over any route | Spool screen `spools/{id}` 7.2 with sheets and sub-screens |
| NFC tap opens the spool card anywhere except pair and add | 2.6, opens `tag/{uid}` 7.7 |
| Connection poll every 20 s | 2.4 |
| (new) | Recently added `recent`, `recent/{hid}`, `recent/{hid}/edit/{item}`, `recent/{hid}/photos/{n}` 10; Slicer presets screen `presets` 11.2; Appearance 12.2; App updates 12.4; Developer 12.6; Printer settings `printers/{id}/settings` 9.9; slot pick 9.6; Add a Klipper printer and Find Klipper printers 9.3; top bar, bottom bar and rail 2.2, 2.3 |

### 17.2 Pairing controls

| Today | Where it is now |
|---|---|
| Title "Pair with your server" + version line | Top bar title "Pair with your Hub"; version line 4.3 |
| Scan intro text | 4.3 intro |
| "Scan QR code" / "Connecting..." | 4.3 Scan |
| Inline error | 4.3 result line, texts 4.9 |
| "Servers found on this network", progress + "Still looking…", one button per server | 4.3 Found Hubs panel |
| "Enter address" | 4.3 "Enter the address instead" |
| "Skip the fingerprint check for new servers" switch (Choose step and Settings) | Settings > Hub connection 12.3, worded "Check the fingerprint when pairing by address" |
| Address step fields "Host name or IP address", "Port", "Connect", "Back" | 4.5; Back is the top bar and system Back |
| Confirm step "It matches" / "It does not match", `FINGERPRINT_REJECTED` | 4.6 |
| Code step "6-digit code", "Pair" / "Pairing...", "Back" | 4.7 |
| Pairing error vocabulary | 4.9 |
| Scanner hint chip, "Cancel", permission denied texts and "Try again" / "Enter address instead", camera failure | 4.4 (Cancel is the close button) |
| "Trust the new certificate" / "Pair again" / "Start again" | 4.8 |
| "Allow" / "Open app settings" | 3.3, 4.2 |

### 17.3 Home controls

| Today | Where it is now |
|---|---|
| Title "filament-kit" + version line | Top bar "Home" and the Hub's name 5; versions in the Hub connection sheet 2.4 and 12.3, 12.4 |
| Connection row (dot, name, status: Connected, Connecting…, Can't reach the server, certificate changed, Not paired, Needs local network access) | Connection chip in the top bar and its sheet 2.4 (badge words Connected, Offline, Needs a look; a skeleton while the first check runs; the state's sentence in the sheet) |
| "Retry" / "Review" | Hub connection sheet "Try again" / "Review the certificate" 2.4 |
| Update banner (all states, "Tap to install", "Install", "Downloading… n%", "Try again", "What this means") | Home notice 5 and the update panel 13 on 12.4 ("Tap to install" is the state "Waiting for the install to be confirmed") |
| "Add spool" | Home "Add by hand" 5 |
| "Add from label photos" | Home "Add from label photos" 5 |
| "Add profile" | Slicer presets screen 11.2 and spool panel overflow 6.3, opening `catalog/new` 8 |
| "Existing lines" list on the Add profile screen, with "Change parent" on each line | Product lines panel of the Slicer presets screen 11.2 ("Change parent" opens a sheet) |
| "Search" | Bottom bar "Spools" 2.3 |
| "Printers" | Bottom bar "Printers" 2.3; Home Printers panel 5 |
| "Settings" | Bottom bar "Settings" 2.3 |
| Presets card | Home Slicer presets panel 11.1 |
| "Unfinished adds" cards | Home Drafts panel 5 (plus Discard) |
| Debug "Tag UID" + "Simulate tag" | Settings > Developer 12.6 |

### 17.4 Search and spool card

| Today | Where it is now |
|---|---|
| "Back" text button, title "Search spools" | Spools destination root; no back needed (2.5) |
| Search field "Brand, material, colour…" with debounce | 7.1 search field |
| "Sealed spools only" checkbox | 7.1 "Sealed only" filter chip |
| "Search" / "Searching…" button | Removed: search runs as you type or on the keyboard key; progress line 7.1 |
| Results rows (`SpoolSummaryRow`) | 7.1 result rows |
| "No spools found.", error texts, mismatch and unauthorized notices | 7.1 empty; 3.2 to 3.5 |
| Spool card loading "Looking up tag…" | `tag/{uid}` 7.7 |
| Card summary row | 7.2 header and remaining |
| Success messages ("Weight updated", "Moved to …", "Marked empty", "Tag linked", "Tag moved") | 7.2 result line |
| "Gross weight (g)" field + "Update weight" + preview "Remaining would change…" + "Confirm" / "Cancel" | Update weight sheet 7.3 |
| "Move" + move list + "Cancel" | Move sheet 7.4 (with Undo) |
| "Mark empty" + dialog "Mark empty?" | Overflow item and dialog 7.5 |
| "Load into printer" | 7.2 button, load flow 7.6 |
| "Done" | Back (top bar or system) |
| Unknown tag: "Link to a sealed spool", "Add as new", "Cancel" | `tag/{uid}` 7.7 ("Add as a new spool"; Cancel is Back) |
| Link flow: search step, "Gross weight (g), optional", "Search" / "Retry" / "Back", results | 7.8 Find |
| Link preview "Link this tag to:", "Confirm link" / "Retry" / "Back" | 7.8 Preview ("Link tag") |
| Conflict "Tag already in use", "Move tag here" / "Move tag here (replace its current tag)" / "Cancel" | 7.8 Tag already in use |
| Failed state with "Try again" / "Close" | 7.7 Failed; 3.2 |
| Load flow: pick printer, pick slot, preview, done, errors | 7.6 steps and results |
| Outside tap / Back closes and loses typed weight | Back rules 2.5; typed weight asks 7.3 |

### 17.5 Add flow

| Today | Where it is now |
|---|---|
| Title "Add spools" + intro | 6.1, 6.2 |
| Camera preview + "Take photo" / "Taking photo…" | 6.2 |
| Camera permission card "Allow camera"; camera errors | 6.2 |
| "Photos: n of 8" | Count inside "Take photo" and the draft tag 6.1 |
| Photo strip with "Remove" | 6.2 photo strip (with Undo) |
| Tag card / "Remove tag" | 6.2 tag row |
| "Weight on the scale, with spool (g)" | 6.2 |
| "Sealed (still in its bag or box)" switch | 6.2 "Still sealed (in its bag or box)" |
| "Note for Claude (optional)" | 6.2 "Note for the Label Reader (optional)" |
| Error card with "Retry" / "Add without the tag" / "Pair again" / "OK" | 6.2 read failures; "OK" dropped (the notice stays until the next action) |
| Reading spinner "Claude is reading n photo(s)…" | 6.2 Reading state |
| "Close" / "Back to review" / "Read labels" | Back; "Back to the check"; "Read labels (n photos)" 6.2 |
| Titles "Add spool" / "Check the spools" | Top bar "Add spools", page header "Check the spools" 6.3 |
| Filament picker (manual) with "New filament" | 6.4 |
| "Claude asks" card, notices, tag note | 6.3 "The Label Reader asks:" and `info` lines |
| Spool item card: header, match note, "Remove", "Claude: <reason>" | 6.3 spool panel header ("Remove this spool" in its overflow, with Undo) |
| Fields 1 to 15 (Vendor + Pick … Location + Pick) | 6.3 fields table in the shared add-form groups (Vendor is "Brand", Empty spool is "Empty spool weight") |
| Empty texts "Pick a filament above, or tap New filament." / "No spools to add. Go back to the photos and read again." | 6.3 Empty (hand path; photo path as the empty state "No spools found in these photos") |
| "(estimated)" in labels | 6.3 confidence marks |
| Per-field validation and complaints from the Hub | 6.3 Validation |
| "Added before" warning card | 6.3 Added before |
| Buttons by stage, "Checking…", "Adding to Spoolman…", "Preview (nothing saved yet)", "Add n spool(s)", disabled reasons | 6.3 action bar (reasons above), 6.5 |
| Dialog "Add these spools again?" ("I checked — add again" / "Cancel") | 6.5 ("Add again" / "Cancel") |
| Done "Spools added", "New spool(s): …", "Add more" / "Done" | 6.6 (plus "Open in Recently added") |
| Add error vocabulary | 6.2 read failures, 3.5 |

### 17.6 Add profile, Settings, Licences

| Today | Where it is now |
|---|---|
| Add profile title, help, fields (Vendor*, Product line*, Material*, nozzle low/high, bed range, density, max volumetric speed, Bambu Studio parent, Notes) | 8, grouped (Product line is "Line"; nozzle low and high are one "Nozzle range (°C)") |
| "Back" / "Done", "Save" / "Saving…", "Fill in the fields marked *." | 8 action bar and reason; Back is the top bar |
| Error card "The server could not use these values", "Pair again", success "Saved. Presets are rebuilt in a minute." | 8 Refused, Success; 3.4 |
| Settings "No server is paired." | 12.3 "No Hub is paired." |
| Server name, address, "Certificate fingerprint" | 12.3 field rows |
| "Open the setup page" + help + errors | 12.3 "Open the Hub page" |
| "Pair again" | 12.3 |
| "Forget server" + dialog "Forget this server?" | 12.3 "Forget this Hub" + dialog |
| Skip fingerprint switch | 12.3 Security |
| "Licences and third-party software" | Settings row "Licences" 12.1 |
| Licences screen, "Show / Hide the GPL-3.0 text", parsed blocks, missing-asset text | 12.5 |

### 17.7 Printers

| Today | Where it is now |
|---|---|
| Title "Printers" + "Refresh" | 9.1 top bar overflow "Refresh" and pull to refresh |
| Empty text | 9.1 Empty |
| Printer row (dot, name, model · state, job, "Tap to add this printer", "Tap to enter the Access Code again") | 9.1 rows, Found on the network with "Add", fix line |
| State label vocabulary and hard-coded colours | 9.1 state table with the shared badge words, shapes and tokens: "Wrong Access Code", "Needs Developer Mode" and "Certificate changed" become "Needs a look" with a fix sentence; "Not set up" becomes "Not configured" |
| Add printer dialog (serial, "Name (optional)", "Access Code" + help, "Add" / "Cancel", "Connecting to the printer…") | 9.2 |
| Printer screen "Back" + name | 9.4 top bar |
| Mismatch / unpaired notices, "Loading…" | 3.4, 3.2 |
| Camera box (HLS / MJPEG, unsupported text, waiting text, error + "Try again") | 9.4 Camera panel (plus Show / Hide) |
| State row + fix text + messages + "No live status…" | 9.4 status panel |
| Status block (stage, job, progress, temperatures) | 9.4 status panel |
| AMS blocks, slot lines, "Unload" per slot, "Checking…" | 9.5 slots and slot sheet |
| Printer alerts ("Printer alert <code>") | 9.4 Alerts |
| "Pause" / "Resume", "Stop", "Light on" / "Light off", "Waiting for the printer…", result text | 9.4 Controls |
| Slot mapping section states, notices, problems, notes, "Map slots" / "Map slots again", "Map by loading filament", disabled reasons | 9.7 |
| "Collect a report" + privacy note + share sheet | 9.7 Report and report sharing; also the printer's overflow 9.4 |
| Filament used (last 7 days), rows, notes, "Undo" | 9.10 |
| Printer settings heading and buttons (Rename, Change address, Replace Access Code, Trust a new certificate, Rename, Change address, Change API key) | `printers/{id}/settings` 9.9 rows |
| Field edit dialogs ("Name", "Address", "Access Code", "API key", Port, second secret, "Saving…" / "Saving and connecting…", "Save" / "Cancel") | 9.9 dialogs |
| "Remove printer" + dialog "Remove printer?" ("Remove" / "Keep") | 9.9 "Forget printer" and dialog "Forget <name>?" |
| Dialog "Map slots?" | 9.7 "Map the slots of <name>?" |
| Dialog "Unload?" | 9.5 "Unload from <slot>?" |
| Dialog "Undo this?" | 9.10 "Put it back on the spool?" |
| Two-step stop: "Stop the print?" then "Are you sure?" | One dialog naming the job, 9.4 (same as the web app and the Hub page) |
| Manual map screen: "Back", title, printer name, "Starting…", error + "Try again" | 9.8 |
| Instruction, by-hand list, settled question with nozzle chips and "Yes" / "No, I loaded…", settling and waiting progress | 9.8 states |
| "Skip <position>", "Stop", summary, per-position list | 9.8 |
| Share offer "Yes, how do I share it?" / "No thanks", "Done" | 9.8 Finished |
| Dialogs "Which one did you load?" and "Stop mapping?" | 9.8 |
| Back asks while mapping is open | 2.5 rule 1, 9.8 |
| "Lost touch with the server for a moment; still trying…" | 9.8 Lost contact |

### 17.8 Cross-cutting

| Today | Where it is now |
|---|---|
| Material 3 baseline colour scheme, `isSystemInDarkTheme()` only | `SpoolwardenTheme(look, appearance)` 1, appearance switch 2.2 and 12.2 |
| Hard-coded status colours and dots | Status component with shapes and tokens 3.1, 2.4, 9.1 |
| No icons | Own vector drawables 1 |
| Hard-coded strings, no `strings.xml` | 15 |
| No top bar, bottom bar or back control | 2.2, 2.3, 2.5 |
| No tablet layout | 2.1, window size classes 1 |
| Mixed loading displays and ellipses | 3.2, 3.5 |
| Five copies of the certificate and unpaired notices | One Hub notice 3.4 |
| Errors as red text, error cards, dialogs | Notice lines 3.1, 3.2 |
| No snackbar | Toast (snackbar) 3.1 |
| Text buttons in small rows ("Unload", "Undo", "Remove") | 48 dp targets 14.1, row sheets 9.5 |
| Checkboxes that toggle only on the box | Whole-row check and switch rows 3.1, 14.1 |
| 11 content descriptions in total | 14.2 |
