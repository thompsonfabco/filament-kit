# Spoolwarden design: accessibility

This document is the accessibility specification for the four interfaces of Spoolwarden: the Hub page, the web app,
the Android app and the `spoolwarden` command. It builds on `01-foundations.md` and does not repeat it; where a rule
already stands there, this document names the section and adds only how it is met and how it is checked. Where the
two disagree, the foundations win.

Contents: 1 Targets and how to read this · 2 What fails in the current UI · 3 Contrast · 4 Colour independence ·
5 Text size, zoom and reflow · 6 Touch targets and pointer · 7 Keyboard and focus · 8 Screen readers ·
9 Forms · 10 Motion · 11 Time limits · 12 Language and plain words · 13 Android app · 14 Command line ·
15 Automated checks · 16 Release checklist · 17 Needs from the Hub

---

## 1. Targets and how to read this

| Interface | Target |
|---|---|
| Hub page, web app | WCAG 2.2 level AA, in all four themes (foundations 6), in Light and Dark (foundations 5), at the three layouts (foundations 7) |
| Android app | Android accessibility guidance: TalkBack, Switch Access and a hardware keyboard work everywhere; 48 dp targets; font scale up to 200 %; Accessibility Scanner reports nothing |
| `spoolwarden` command | Usable with a screen reader in a plain terminal, without colour, without a cursor-addressed screen |

Every requirement has an ID (for example `CON-3`), says where it applies, and says how it is checked.

| Mark | Applies to |
|---|---|
| H | Hub page |
| W | web app |
| A | Android app |
| C | `spoolwarden` command |

| Check kind | Meaning |
|---|---|
| **Auto** | A test in the build; it fails the build. Listed in section 15. |
| **Manual** | A tester does it; the steps are in the row or in the release checklist (section 16). |
| **Review** | Read in code review against the rule; no tool can settle it. |

A requirement is met only when its check passes in every theme and in both Light and Dark, unless the row says
otherwise. A check that did not run counts as not passed.

Words used here: **accessible name** is what a screen reader says for a control; **live region** is an element whose
changes a screen reader reads out without the focus moving there; **visually hidden** means present for screen readers
but not drawn (the visually-hidden utility of `02-components.md`; never `display: none`, which hides it from screen
readers too).

---

## 2. What fails in the current UI

These are the failures in the pages and the app as they are today. Each is closed by the requirements named.

| Failure today | Where | Closed by |
|---|---|---|
| Confirmations, renames, addresses and even Access Codes and API keys are asked with `window.confirm` / `window.prompt`: no masking, no labels, no consistent focus return | H, W | KEY-9 to KEY-12, SR-20 to SR-24, FRM-8, AUT-3 |
| White text on the old accent button is about 3.6:1 in light and 2.6:1 in dark | H, W | CON-1 to CON-6, AUT-1 |
| Muted grey is the main text style; labels and captions at 0.7 to 0.8 rem | H, W | TXT-4, CON-1 |
| Slot buttons about 35 px high, photo remove button 24 px, `TextButton` actions in small rows | W, A | TGT-1 to TGT-5, AND-6 |
| Print state shown as one neutral pill with the printer's raw word; success and failure told apart by border colour | H, W | COL-1 to COL-5 |
| Coloured dots with hard-coded colours that are not adjusted for dark | A | COL-1, AND-11 |
| Result boxes are not live regions; spinner text is never announced | H, W | SR-12 to SR-19 |
| Results appear far from the button that caused them (one message block under the camera, one job panel at the top) | H, W | SR-13, SR-17 |
| Inputs with a placeholder and no label (secret fields, addresses, reader name) | H, W | FRM-1, FRM-2, AUT-4 |
| No focus style; no skip link; tab strip without state | H, W | KEY-1 to KEY-4 |
| Photo alt text "photo 0"; QR code alt text only | H, W | SR-27, SR-28 |
| Checkboxes toggle only on the box, not on their label | A | AND-5 |
| Only 11 content descriptions in the whole app; no headings marked | A | AND-1 to AND-3 |
| Disabled buttons with no reason given, or the reason shown below the fold | W, A | FRM-11 |
| Pairing code expiry is a static "Expires in N min." line; when it runs out nothing says so | H | TIM-1, TIM-2 |
| Command line: a 30 s silent wait, a curses menu that switches to another UI below 40 x 8 with different keys, errors split between stdout and stderr | C | CLI-3 to CLI-8 |

---

## 3. Contrast

Foundations 4.1 sets the rule: text pairs reach 4.5:1, control outlines and focus rings 3:1, and a test computes this
from `tokens/tokens.json` for every theme in light and dark. This section lists the exact pairs the test checks, the
Console values they have today, and the pairs this document adds because the components use them.

Contrast is the WCAG 2.x ratio `(L1 + 0.05) / (L2 + 0.05)` with sRGB relative luminance. Ratios are computed from the
token values, never measured from screenshots. The test compares the unrounded ratio with the requirement (4.499
fails); the tables here show ratios rounded to two decimals.

### 3.1 Pairs from foundations 4.1 (Console values)

Text pairs, required 4.5:1.

| Foreground | on `--bg` light / dark | on `--surface` light / dark | on `--surface-2` light / dark |
|---|---|---|---|
| `--text` | 16.66 / 15.71 | 18.22 / 14.74 | 16.06 / 13.47 |
| `--muted` | 6.04 / 7.57 | 6.61 / 7.10 | 5.83 / 6.49 |
| `--accent-text` | 6.24 / 11.16 | 6.83 / 10.47 | 6.02 / 9.57 |
| `--ok` | 4.93 / 9.84 | 5.39 / 9.23 | 4.76 / 8.44 |
| `--warn` | 5.58 / 10.72 | 6.10 / 10.06 | 5.38 / 9.19 |
| `--bad` | 5.96 / 7.73 | 6.52 / 7.25 | 5.75 / 6.63 |
| `--info` | 5.82 / 9.06 | 6.36 / 8.50 | 5.61 / 7.77 |

| Pair | Required | Console light | Console dark |
|---|---|---|---|
| `--ok` on `--ok-soft` | 4.5 | 4.69 | 8.19 |
| `--warn` on `--warn-soft` | 4.5 | 5.38 | 8.85 |
| `--bad` on `--bad-soft` | 4.5 | 5.49 | 6.63 |
| `--info` on `--info-soft` | 4.5 | 5.43 | 7.66 |
| `--on-accent` on `--accent` | 4.5 | 5.18 | 8.21 |
| `--on-bad` on `--bad` | 4.5 | 6.52 | 7.43 |

Non-text pairs, required 3:1.

| Pair | Required | Console light | Console dark |
|---|---|---|---|
| `--border-strong` on `--surface` | 3 | 3.62 | 3.71 |
| `--focus` on `--bg` | 3 | 4.17 | 11.80 |
| `--focus` on `--surface` | 3 | 4.56 | 11.07 |
| `--focus` on `--surface-2` | 3 | 4.02 | 10.12 |

### 3.2 Pairs added by this document

The components put these colours together, so the test checks them too. They tighten foundations 4.1; they do not
change any value. Every pair below reaches its ratio in all eight token sets of `tokens.json`; the last column gives
the lowest of the eight and where it occurs.

| Pair | Where it occurs | Required | Console light | Console dark | Lowest of the eight |
|---|---|---|---|---|---|
| `--on-accent` on `--accent-hover` | Main button under the pointer | 4.5 | 6.97 | 9.78 | 6.77 (Spool light) |
| `--accent-text` on `--accent-soft` | Active navigation label, selected chip | 4.5 | 5.91 | 8.75 | 4.59 (Panes light) |
| `--text` on `--surface-3` | Selected row, pressed control | 4.5 | 14.49 | 11.63 | 10.06 (Workbench dark) |
| `--muted` on `--surface-3` | Secondary text in a selected row | 4.5 | 5.25 | 5.60 | 5.10 (Panes light) |
| `--bad` on `--surface-3` | Pressed destructive item of an overflow menu | 4.5 | 5.19 | 5.72 | 5.03 (Spool light) |
| `--surface` on `--text` | Tooltip (inverse) | 4.5 | 18.22 | 14.74 | 13.35 (Workbench dark) |
| `--text` on `--code` | Logs, command blocks | 4.5 | 17.10 | 15.27 | 13.64 (Spool light) |
| `--muted` on `--code` | Time stamps in logs | 4.5 | 6.20 | 7.35 | 5.83 (Panes light) |
| `--border-strong` on `--bg` | Control outline on the page ground | 3 | 3.31 | 3.96 | 3.19 (Panes light) |
| `--border-strong` on `--surface-2` | Control outline in a table header or quiet fill | 3 | 3.19 | 3.39 | 3.19 (Console light) |
| `--focus` on `--code` | Focus ring on a log or command block | 3 | 4.28 | 11.47 | 4.28 (Console light) |
| `--focus` on `--surface-3` | Focus ring inside a selected row | 3 | 3.63 | 8.73 | 3.63 (Console light) |

These pairs fail in at least one token set and are therefore **not allowed** in any component:

| Pair | Fails in | Rule instead |
|---|---|---|
| `--ok` as text directly on `--surface-3` | Console light 4.29 | In a selected row a status badge keeps its `-soft` ground (CON-4). (`--bad` on `--surface-3` passes and is in the table above.) |
| `--accent-text` on `--surface-3` | Panes light 4.39 | A link inside a selected row is drawn in `--text` and underlined. |
| `--border-strong` on `--surface-3` | Console light 2.87, Console dark 2.93, Spool dark 2.83, Panes light 2.92 | A control inside a selected row keeps its own `--surface` fill, so its outline sits on `--surface` (CON-5) |

**Not a required pair: the edge of a filled main button** (`--accent` against `--bg` or `--surface`). The button is
identified by its label, which is checked as `--on-accent` on `--accent` (3.1), so WCAG 1.4.11 asks no ratio of its
edge. The values vary widely (Spool light 2.04 on `--bg`, 2.20 on `--surface`, because Spool's accent is a light
orange with dark text, foundations 6.3); the test does not check them. A main button therefore never relies on its
fill alone to be found: it always has a visible label (an icon-only control is never a filled main button).

This exception covers that one use and no other. `--accent` is never text, an icon, an outline or a mark that
stands on a surface by itself: a link, a checked box, a switch that is on, a progress fill, a selection mark and
the current step all use `--accent-text` (CON-9), whose pairs are in 3.1.

### 3.3 Requirements

| ID | Where | Requirement | Check |
|---|---|---|---|
| CON-1 | H W A | Every pair in 3.1 and 3.2 reaches its ratio in all four themes, in light and in dark (eight token sets). | Auto: AUT-1. |
| CON-2 | H W | Text is drawn only in the foreground tokens of 3.1 on the grounds of 3.1 and 3.2. No opacity is applied to text or to a control to show a state (a disabled control uses `--muted` text and a `--border` outline and says why it is disabled, FRM-11). | Auto: AUT-2 rejects `opacity` below 1 on text and controls in component rules. Review for the rest. |
| CON-3 | H W | The focus ring is drawn outside the control with a 2 px offset, so it is measured against the ground behind the control, never against the control's own fill (`--focus` on `--accent` is only about 1.1:1). Inside a clipped box (menu items, rows of a scrolling list) the ring is drawn inset, 2 px, against the item's own ground. | Manual: tab through a page with a filled main button and an overflow menu in each theme; the ring is visible all round. |
| CON-4 | H W | A status badge on `--surface-3` keeps its `-soft` ground; a link inside a selected row is drawn in `--text` and underlined (3.2). | Review; AUT-1 checks the soft pairs. |
| CON-5 | H W | A field, checkbox or select inside a selected row keeps a `--surface` fill. | Manual: select a row that contains a control, in Console light; the outline is visible. |
| CON-6 | H W A | Text over a photo or a camera picture sits on a solid `--surface` strip, never directly on the picture. | Review. |
| CON-7 | H W | Placeholder text uses `--muted` (4.5:1), although a placeholder is never the only label (FRM-1). | Auto: AUT-1 (the `--muted` pairs). |
| CON-8 | A | The Material 3 colour roles generated from the tokens (`08-platform-mapping.md`) keep the same ratios: `onSurface`, `onSurfaceVariant`, `primary` on `surface` and `surfaceContainer*`; `onPrimary` on `primary`; `onError` on `error`; `outline` on `surface` at 3:1. `primary` is generated from `--accent-text` and `onPrimary` from `--surface`, because Material components draw `primary` as text and marks on surfaces; the amber or teal fill of the main button is the extended colour `accent` with `onAccent`, checked as `--on-accent` on `--accent`. | Auto: the Kotlin theme test that keeps the theme equal to `tokens.json` also runs the ratio check. |
| CON-9 | H W A | `--accent` (Android: the extended colour `accent`) is used only as the fill (and the same-coloured edge) of a part that carries its own label or icon in `--on-accent`: the main button, the chosen part of a segmented choice, the skip link, and the icon tile of the current section in the `list` navigation. Text, icons, outlines, checked boxes, switches that are on, progress fills, selection marks and the current step use `--accent-text` (Android: `primary`). | Auto: AUT-2 fails on `var(--accent)` in a rule whose selector is not in the lint's short list of these labelled fills. Android: AUT-8 fails on `SpoolwardenTheme.colors.accent` used outside `SwButton` and the segmented choice. |

---

## 4. Colour independence

Foundations 1.7 and 10: status is never told by colour alone; status shapes are always used with a word.

| ID | Where | Requirement | Check |
|---|---|---|---|
| COL-1 | H W A | Every status shows a shape and a word: filled circle + "Connected" / "OK" / "On" / "Set"; hollow circle + "Offline" / "Off" / "Not set" / "Not configured"; triangle + "Needs a look", always followed by a sentence saying what to do (a wrong Access Code, a changed certificate, Developer Mode needed); octagon + "Failed" only; half-filled circle + "Running". The words are those of the status badge vocabulary in `02-components.md`. | Manual: view Printers and Overview with the page in greyscale (devtools "Emulate vision deficiency: achromatopsia"); every state can still be told apart. |
| COL-2 | H W | A printer's own state word (`gcode_state`, for example `RUNNING`, `PAUSE`) is never shown raw; it is mapped to a sentence-case word with its shape ("Printing", "Paused", "Preparing", "Finished", "Print failed", "Idle"). An unknown word is shown as it comes, with the hollow circle and the word "Other: " before it. | Review of the mapping table; Manual: a fake printer reporting an unknown state. |
| COL-3 | H W A | Success and failure of an inline result or toast differ by icon (check / error octagon) and by the first word ("Saved." / "Not saved: …"), not only by colour or border. | Manual: save a field with a valid and an invalid value; read both results in greyscale. |
| COL-4 | H W A | Links inside running text are underlined. Links that stand alone as navigation (rail, bottom bar, Settings sub-navigation, breadcrumbs) are recognisable by position and shape instead. | Review. |
| COL-5 | H W A | A filament colour is always given in words too (the colour's name, or its hex when there is no name), per foundations 4.1. The swatch has the 1 px `--border-strong` outline. An empty slot is a dashed outline plus the word "Empty". | Manual: Printers > a printer's slots in greyscale. |
| COL-6 | H W A | Label Reader confidence is shown as a word ("high", "medium", "low", "not on the label") next to the field, never only as a tint of the field. | Manual: open a record in Recently added that has a medium and a not-on-the-label field. |
| COL-7 | H W | Charts or bars that compare amounts (spool remaining, usage) carry the number as text. | Review. |
| COL-8 | H W A | The selected item in a navigation, segmented control, theme picker or list shows more than a colour change: bold label plus the 3 px mark (navigation), a check icon (segmented control, theme picker, menu radio items), or the `--surface-3` ground plus a check (selected rows). | Manual: greyscale pass over the top bar, the rail and Settings > Appearance. |

---

## 5. Text size, zoom and reflow

Foundations 4.2 and 7 set `rem` sizes, the 16 px minimum for phone inputs, and no page scroll sideways down to 320 px.

| ID | Where | Requirement | Check |
|---|---|---|---|
| TXT-1 | H W | Every font size is a type token (`rem`); line heights are the unitless values of foundations 4.2 (1.45 body, 1.25 titles); other sizes that hold text are in `rem` or `em`. No `px` font sizes or line heights; no `vw`-only font sizes. The root font size is never set (it stays the browser's). | Auto: AUT-2 rejects `px` in `font-size` and `line-height` of component rules. |
| TXT-2 | H W | At 200 % browser zoom on a 1280 px wide window, every page is fully usable: nothing is cut off, nothing overlaps, every control can be reached and used. | Manual: Chrome or Firefox, Ctrl and + to 200 %, walk Overview, Printers, Recently added, Settings. |
| TXT-3 | H W | At 320 CSS px wide (or 1280 px at 400 % zoom) there is no sideways page scroll; only logs, command blocks and wide tables scroll inside their own box (foundations 7). Tables have already turned into stacked cards there. | Manual: devtools device toolbar at 320 x 640; also Auto in the page audit (AUT-5) checks `document.documentElement.scrollWidth <= innerWidth`. |
| TXT-4 | H W | Nothing a person must read to act is below `--fs-m`; nothing at all is below `--fs-xs` (foundations 4.2). Help text and errors under fields are `--fs-m` or larger. | Auto: AUT-2 rejects font sizes other than the type tokens. Review which token each text uses. |
| TXT-5 | H W | Text inputs, selects and text areas use at least `--fs-l` (16 px) at 600 px wide and below, so iPhone Safari does not zoom on focus. | Manual: iPhone Safari, focus each field type in the web app and the Hub page; the page does not zoom. |
| TXT-6 | H W | The viewport meta never disables zoom (`user-scalable=no` and `maximum-scale` are not used). | Auto: AUT-5 reads the meta. |
| TXT-7 | H W | With text spacing overridden (line height 1.5, space after paragraphs 2 em, letter spacing 0.12 em, word spacing 0.16 em) no text is cut off or overlaps. Containers that hold text have no fixed height; buttons grow in height, they do not clip. | Manual: paste a rule with the four values for `*` into the devtools Styles pane (no script needed) and walk Printers and Settings. |
| TXT-8 | H W | Running text is at most 72 characters wide (foundations 9) and is never justified. | Review. |
| TXT-9 | H W A | Text is real text, never an image of text (the product mark beside "Spoolwarden" is an icon; the name is text). | Review. |
| TXT-10 | H W A | The screen works in portrait and landscape; neither the web app manifest nor the Android app locks the orientation. | Review of the manifest and `AndroidManifest.xml`; Manual: rotate a phone on Printers. |

Android font scale is in section 13 (AND-8, AND-9).

---

## 6. Touch targets and pointer

Foundations 1.7 and 4.3: 44 px on the web, 48 dp on Android; a control shorter than 44 px gets an invisible hit area
that reaches 44 px; density never changes the minimum.

| ID | Where | Requirement | Check |
|---|---|---|---|
| TGT-1 | H W | Every control that can be pressed has a hit area of at least 44 x 44 CSS px at every width and in every theme, including the photo remove button, slot Load / Unload buttons, row overflow buttons, chips, the toast close button and the theme picker tiles. | Auto: AUT-5 measures every focusable element's hit box (its box, or its `::after` hit-area extension, `02-components.md` 1.2) and lists those under 44 x 44. Manual spot check on a phone. |
| TGT-2 | H W | Hit areas of two controls never overlap. Where the visible controls sit closer than the 44 px reach (dense Console rows), the hit areas are split at the middle of the gap, never stacked. | Review of the hit-area rule in `02-components.md`; Manual: tap between two row buttons on a phone; exactly one responds. |
| TGT-3 | H W | Adjacent separate targets in a row have at least `--s2` (8 px) between their visible edges on phones. Destructive actions are never next to the main action (foundations 1.2); they sit in the overflow menu or apart with at least `--s5` (24 px) of space. | Review; Manual on Printers at 375 px. |
| TGT-4 | H W | A whole collection row or card is a target only when it does one thing (open). Buttons inside it stay separate targets with their own names; a press on a button never also opens the row. | Manual: on Printers, press Test connection in a row; the row does not expand. |
| TGT-5 | H W | Actions fire on release (`click`), not on press (`pointerdown`), so a press can be cancelled by moving off. | Auto: AUT-6 rejects `pointerdown`, `mousedown` and `touchstart` handlers (allowed only for the photo viewer's pan and zoom of TGT-6, which move the view and perform no action). |
| TGT-6 | H W A | Nothing needs a path gesture, a two-finger gesture or dragging. Swipe to dismiss a sheet or toast always has a button too (Close). The photo viewer pans and zooms, but also has buttons for previous, next and close. | Manual: dismiss every sheet and toast with a single tap. |
| TGT-7 | H W | Text links inside running text are exempt from 44 px, but have at least `--s2` of line spacing around them (line height 1.45 does this) and are never two links in a row of less than 24 px. | Review. |

Android targets are in section 13 (AND-6).

---

## 7. Keyboard and focus

Foundations 12.6: every page works by keyboard alone. This section says how.

### 7.1 Order and focus ring

| ID | Where | Requirement | Check |
|---|---|---|---|
| KEY-1 | H W | Every action that can be done with a pointer can be done with the keyboard, and focus can always leave every control with Tab or Escape (no keyboard trap; the camera video's own controls included). | Manual: unplug the mouse; do the tasks of the release checklist (section 16). |
| KEY-2 | H W | Tab order follows the reading order, which is the DOM order: skip link, top bar (product mark and name, job indicator when shown, lock chip, appearance control), navigation (rail, sidebar, pills, list or bottom bar: one element, foundations 6.2), main content, then the toast region. On phones the bottom bar is drawn at the bottom but stays after the top bar in the DOM; the skip link passes it. No `tabindex` above 0 anywhere. | Auto: AUT-5 fails on `tabindex` above 0. Manual: Tab from the address bar on Printers at desktop and phone widths and write down the order. |
| KEY-3 | H W | Every focusable element shows a ring on `:focus-visible`: 2 px solid `--focus`, 2 px outside the element (CON-3), following its radius. Fields also turn their border `--focus` (a ring at 0 offset is allowed for fields, because the border change adds to it). `outline: none` is only allowed in a rule that draws the inset ring instead. Mouse clicks do not show the ring on buttons; keyboard use always does. | Auto: AUT-2 fails on `outline: none` or `outline: 0` in a rule that draws no other ring for `:focus-visible`. Manual: Tab through one page per theme. |
| KEY-4 | H W | The first focusable element is a "Skip to content" link, visually hidden until focused, then shown at the top left above everything (`--accent` ground, `--on-accent` text). It moves focus to `<main id="main" tabindex="-1">`. | Manual: load any page, press Tab once, see the link, press Enter; the next Tab lands on the first control in the content. |
| KEY-5 | H W | A focused element is never hidden under the sticky top bar, the bottom bar, the job strip or a toast. The page sets `scroll-padding-top` to `--top` plus the job strip's height while it shows, and `scroll-padding-bottom` to `--tab` plus the bottom safe-area inset on phones. Toasts sit where they cover no focusable content, or move up while the focus is below them. | Manual: at 375 px, Tab down the Settings page with a job running; every focused control is fully in view. |
| KEY-6 | H W | Going to another section or to an item's own address (foundations 8, for example `#printers/<id>`) moves focus to that view's `h1` (which has `tabindex="-1"`) and sets the document title to "`<Page title> · <Hub name>`" (foundations 9) on the Hub page and in the web app alike, for example "Printers · Workshop" or "Add spools · Workshop". Back and forward do the same. In the Panes theme, drilling into a pane moves focus to that pane's heading, and its Back button returns focus to the row that opened it. | Manual with a screen reader: choose Printers in the navigation; the reader says "Printers, heading level 1". |
| KEY-7 | H W | When an action removes the element that had focus (forgetting a printer, revoking a device, removing a photo), focus moves to the next item in the same list, or to the previous one when it was the last, or to the list's heading when the list is now empty. Focus never falls back to the top of the page. | Manual: forget the second printer of three; focus is on the third. |

### 7.2 Widgets and their keys

There are no single-character shortcuts on the web; the only keys with meaning are the standard ones below. A
single-key shortcut would clash with screen reader keys and with typing in fields.

| Widget (`02-components.md` name) | Tab stops | Keys |
|---|---|---|
| Navigation (rail, sidebar, pills, list, bottom bar) and the list in the "More" sheet | One per link | Enter follows the link. |
| Settings sub-navigation, breadcrumbs | One per link | Enter follows the link. |
| Button, icon button, link | One | Enter (both); Space (buttons). |
| Overflow menu (`role="menu"`), and the phone appearance menu (`menuitemradio` items) | One: the menu button | Enter, Space or Down opens the menu and focuses the first item; Up opens it and focuses the last. In the open menu Up and Down move with wrap-around, Home and End go to the ends, a letter moves to the next item starting with it, Enter or Space chooses, Escape closes and returns focus to the menu button, Tab closes and moves on. Focus inside the menu is roving (`tabindex="0"` on the current item, `-1` on the others). |
| Segmented choice (appearance control on wide screens, list filters) and the theme picker | One per group | Native radio buttons in a `fieldset` with a `legend` (or `role="radiogroup"` with `aria-labelledby`). Arrow keys move and choose; the choice applies at once (foundations 5 and 6.2) and is announced in the group's inline result. |
| Toggle (switch) | One | Space toggles. A native checkbox with `role="switch"`; the visible text is its `<label>`, so a press on the text toggles too. |
| Checkbox | One | Space toggles. The whole row is the `<label>`, so a press anywhere on the row toggles. |
| Select | One | Native `<select>` with the browser's keys. Choosing never navigates or submits (FRM-12). |
| Collection row with inline detail | One per control in the row | The row's name is a button with `aria-expanded` and `aria-controls`; Enter or Space opens or closes the detail; focus stays on the button. The detail's own controls follow it in the Tab order. |
| Sortable column header (table rendering) | One per sortable column | A button inside the column header; Enter or Space sorts, again reverses. |
| Dialog, bottom sheet, side drawer | Its own controls only | Focus is held inside (KEY-10); Escape cancels (KEY-9). |
| Tooltip | None of its own | Shows while its trigger has focus or the pointer; Escape hides it without moving focus (KEY-12). |
| Toast with an action ("Undo") | One for the action, one for Close | Reached by Tab after the main content; it does not time out while it holds focus or the pointer (SR-14). The same action is always also offered where it belongs (Recently added, the usage list), so the toast is never the only way. |
| Photo viewer | Previous, Next, Close | Left and Right go to the previous and next photo; Escape closes. |
| Log, command block, box of a wide table (scrolls inside) | One: the box (`tabindex="0"`, `role="region"`, an `aria-label` such as "Backup log") | Arrow keys and Page Up / Page Down scroll it. Copy is its own button. |
| Job indicator and job strip | The indicator; inside the strip, "Show log" and the log box | Enter on the indicator opens or closes the strip (`aria-expanded`). |
| Step-by-step sheet (Spool theme detail) | Its controls; Back and Next | Next moves focus to the new step's heading. |

### 7.3 Layers: Escape, focus return, focus trap, hover

| ID | Where | Requirement | Check |
|---|---|---|---|
| KEY-8 | H W | A control that cannot be used yet (for example "Add 2 spools" before a successful check) stays focusable with `aria-disabled="true"`, does nothing when pressed except point at the reason, and has the reason in its `aria-describedby` (FRM-11). Native `disabled` is used only for secondary controls whose reason is shown right next to them. | Manual: Tab to "Add 2 spools" before Check; the screen reader says it is unavailable and why. |
| KEY-9 | H W | Escape closes the topmost open layer only, in this order: tooltip, menu, then dialog, sheet or drawer. Closing is the same as Cancel. If the layer holds typed but unsaved input, Escape first opens the unsaved-changes guard of `02-components.md` 5.11 ("Leave without saving?", buttons **Stay**, focused first, and **Leave without saving**); Escape in the guard is Stay. Escape never collapses an inline detail and never leaves the page. | Manual: open the Rename dialog, type, press Escape; the guard appears with focus on Stay; press Escape again; you are back in Rename with the text. |
| KEY-10 | H W | While a dialog, bottom sheet or side drawer is open, Tab and Shift+Tab cycle through its controls only, and everything behind it is inert (native `<dialog>` opened with `showModal()`, or the `inert` attribute on the app shell for a layer drawn without `<dialog>`). The scrim takes no focus. | Manual: open Forget printer, press Tab ten times; focus never reaches the page behind. |
| KEY-11 | H W | When a layer closes, focus returns to the control that opened it. If that control no longer exists, focus goes where KEY-7 says. When a layer opens another (the guard over a form), closing the second returns focus into the first. | Manual: open a printer's overflow menu, choose Rename, Cancel; focus is on the overflow button. |
| KEY-12 | H W | Nothing is reachable only by hover. Row actions shown on hover in wide tables are also shown while focus is inside the row (`:focus-within`) and are always shown on touch screens (`(hover: none)`). A tooltip appears on focus as well as hover, stays while the pointer moves onto it, stays until pointer and focus leave or Escape is pressed, and holds nothing that is not also in the accessible name or on the page (exact times: SR-10). | Manual: Tab through a Console table; each row's actions appear. Review of tooltip contents. |
| KEY-13 | H W | Focus is not moved by results that arrive by themselves (polls, live printer status, a finished job). Focus moves only to the first invalid field after a failed submit (FRM-7), into a layer the person opened, back from a closed layer (KEY-11), to the view's `h1` after navigation (KEY-6), and after a removal (KEY-7). | Manual: start Map slots and Tab around while it runs; focus is never taken away. |
| KEY-14 | H W | In a form group, Enter in a single-line field submits that group (its one Save); Enter in a text area is a new line. A group never submits when a field changes, except controls that apply at once by design (FRM-12). | Manual: Settings > General, change Display name, press Enter; that group saves, and only that group. |

---

## 8. Screen readers

Reference pairs for manual checks: NVDA with Firefox or Chrome on Windows, VoiceOver with Safari on macOS and on
iPhone, TalkBack with Chrome on Android (for the web app on Android). The Android app is in section 13.

### 8.1 Structure and names

| ID | Where | Requirement | Check |
|---|---|---|---|
| SR-1 | H W | `<html lang="en">` on every page, including the refusal page for addresses outside the home network and the Claude sign-in page (`/login`). | Auto: AUT-5. |
| SR-2 | H W | Each view sets a unique document title (KEY-6). The refusal page's title says what it is ("Only on the home network · Spoolwarden"). | Auto: AUT-5 (title not empty and changes between two views). |
| SR-3 | H W | Landmarks: the top bar is `<header>` (banner); the navigation is one `<nav aria-label="Sections">`; the content is `<main id="main">`; the Settings sub-navigation is `<nav aria-label="Settings groups">`; breadcrumbs are `<nav aria-label="Breadcrumb">`; the "More" sheet holds `<nav aria-label="More sections">`. No other `nav`. Everything visible is inside a landmark except the skip link, the toast region and open layers. | Auto: AUT-5. Manual: NVDA landmark list (Insert+F7, Landmarks). |
| SR-4 | H W | Exactly one `h1` per view: the place's name (foundations 9), for example "Printers" or "Workshop X1". In the Panes theme, with two or three panes side by side, the `h1` is the section name and each pane's title is an `h2`. Dialogs and sheets have their own title (`h2`), which does not count as a second `h1`. | Auto: AUT-5 counts `h1` outside open layers. |
| SR-5 | H W | Headings do not skip levels: `h1` view, `h2` panel, card or Settings group, `h3` part of a group (for example "Identity", "Weights", "Temperatures" in a Recently added record). Text that only looks like a heading (table header caps, eyebrow text) is not marked as one. | Auto: AUT-5 fails on a jump of more than one level. |
| SR-6 | H W | Every control has an accessible name. Icon-only buttons have `aria-label` and a tooltip with the same words (foundations 10); the icon itself is `aria-hidden="true"` and `focusable="false"`. Names say the action and the thing when the thing is not clear from context: "More actions for Workshop X1", "Remove photo 2", "Copy pairing code", "Show Access Code". | Auto: AUT-5 fails on a focusable element without a name. Manual: NVDA, Tab through a printer's row. |
| SR-7 | H W | A control with visible words has an accessible name that starts with those words (so speech-control users can say what they see): a button showing "Forget" with `aria-label="Forget Workshop X1"` is correct; `aria-label="Remove printer"` is not. | Auto: AUT-5 compares visible text with the name. |
| SR-8 | H W | The current place is marked: `aria-current="page"` on the active link in the navigation (foundations 8) and on the last breadcrumb; `aria-current="true"` on the Settings group in view in the Settings sub-navigation. A section switched off in the Features section stays a normal link; its label adds the visually hidden suffix ", switched off" (for example "Slicer presets, switched off"; `02-components.md` 2.3). | Manual: NVDA on Settings; the reader says "current" on Settings and on the group in view. |
| SR-9 | H W | Controls expose their state: `aria-expanded` on everything that opens and closes (row name buttons, the job indicator, "Show log", menu buttons), `aria-haspopup="menu"` on overflow buttons and `aria-haspopup="dialog"` on buttons that open a dialog (the lock chip, Rename), `aria-checked` on menu radio items, native `checked` on radios, checkboxes and switches. `aria-pressed` is used for the show/hide button of a secret field. | Auto: AUT-5 (buttons that control a hidden element must carry `aria-expanded`). Manual: NVDA on the job indicator. |
| SR-10 | H W | Relative times ("3 minutes ago") are `<time datetime="2026-11-12T14:05">` elements whose accessible text includes the exact time ("3 minutes ago, 2026-11-12 14:05", the second part visually hidden), because the tooltip alone is not reachable by every user (KEY-12). Numbers with units are written so they are read well: "62 %", "210 °C", "1000 g". Fingerprints and codes are shown in groups of four (or three for the six-digit code a Weigh Station shows when it asks to pair) and read group by group. | Manual: NVDA on Recently added and on Devices > Pair a phone. |
| SR-11 | H W | A status badge is read as its word. The shape icon is `aria-hidden`. When the word needs its subject to make sense out of context, the subject comes from the collection's cell label (SR-25) or from visually hidden text before it ("State: Offline"). Confidence is read as "Colour: medium confidence". | Manual: NVDA on Printers and on a Recently added record. |

### 8.2 Live regions, results and progress

Foundations 1.3: the result of a button appears next to it, in words, and is announced.

| ID | Where | Requirement | Check |
|---|---|---|---|
| SR-12 | H W | Live regions exist in the page from the first paint and stay; only their text changes. The page has the two page-wide polite regions of `02-components.md` 1.4 and 2.1, after `main`: the toast region (`<div class="toasts" aria-live="polite">`) and the one visually hidden announcer (`#announcer`, `aria-live="polite"`, written only through `announce(text)`). Each inline result (the result slot next to a button, or at the foot of a form group) is an element with `role="status"` present and empty until a result arrives. Regions are never created at the same moment as their text (screen readers would miss it). | Auto: AUT-5 finds a `role="status"` region for each result slot at load. Manual: NVDA, press Test connection; the result is read without moving focus. |
| SR-13 | H W | An inline result says what happened in words, starting with the outcome: "Saved.", "Not saved: the address must be an IP address or a name.", "192.0.2.40 answers; its certificate matches the pinned one." To repeat an identical message (saving twice), the slot is cleared and the same text is set again 30 ms later, as `announce()` does (`02-components.md` 1.4), so the reader announces it again. Waiting text ("Testing…") is placed in the same result slot. | Manual: save the same field twice with NVDA; both are announced. |
| SR-14 | H W | A toast is announced through the toast region. It stays 5 seconds, 10 seconds when it has an action (`02-components.md` 8.7), and does not disappear while the pointer is on it or focus is in it. Errors are never shown only in a toast: an error also stays in the inline result of what caused it. | Manual: trigger a toast, keep the pointer on it for 15 seconds; it stays. |
| SR-15 | H W | Progress has a name and a value: determinate progress is `<progress>` (or `role="progressbar"` with `aria-valuemin`, `aria-valuemax`, `aria-valuenow`) with `aria-label` ("Printing Benchy") and `aria-valuetext` in words ("62 %, layer 140 of 230, 1 h 12 min left"); step progress has `aria-valuetext` like "Step 2 of 4: mapping slot A2". The related status region announces the start, each step for step progress, each 25 % for determinate progress, and the end; never every percent. A spinner always has its words beside it ("Working…", "Asking the Label Reader… up to a minute"); the spinner graphic is `aria-hidden`. | Manual: Map slots with NVDA; four step announcements and an end announcement, nothing more. |
| SR-16 | H W | The background job: the job strip's status line is a polite status region and announces "`<job title>` started", then "`<job title>`: done." or "`<job title>`: failed. See the log." The expandable log is `role="log"` with `aria-live="off"`, so its lines are not read out as they arrive; it is read when the person goes into it. "The Hub is restarting. This page comes back by itself." is announced once, and "The Hub is back." once. | Manual: Settings > Backups and restore > Back up now, with NVDA; exactly two announcements. |
| SR-17 | H W | Live data that updates by itself (printer status, the last-tag card, slot mapping, map by loading filament) is not read out on each update. Only a change of state of the printer or item on screen is announced, once per change, through the region of that block: "Workshop X1: Paused", "Tag read on the Tag Reader at Workshop X1", "Printer alert on Workshop X1: AMS slot A2 is stuck". Temperatures, times left and percentages are never announced by themselves. | Manual: watch a fake printing printer for one minute with NVDA; nothing is announced until it pauses. |
| SR-18 | H W | A region that is loading has `aria-busy="true"` until its data is in, then `aria-busy="false"`. Skeleton shapes are `aria-hidden`; the region holds visually hidden text "Loading printers…" while busy. An empty result is a sentence (the empty state), never a blank region. | Auto: AUT-5 (no region stays `aria-busy="true"` after the fake data loads). Manual: throttle the network to "Slow 3G", open Printers with NVDA. |
| SR-19 | H W | `role="alert"` (assertive) is used only for: the connection to the Hub lost while a change was being sent ("Lost the connection to the Hub while saving. Your edits are kept."), an error that stopped a print on the printer in view, and the error summary of a form group after a save with two or more errors (FRM-7, `02-components.md` 5.1). Everything else is polite. | Review: AUT-6 lists every `role="alert"` and `aria-live="assertive"` in the code for the reviewer. |

### 8.3 Dialogs, sheets and menus

| ID | Where | Requirement | Check |
|---|---|---|---|
| SR-20 | H W | A dialog or bottom sheet has `role="dialog"` (native `<dialog>` opened with `showModal()`), `aria-modal="true"`, `aria-labelledby` pointing to its title and `aria-describedby` pointing to its main sentence. Focus goes in when it opens: to the first field of a form dialog; to "Cancel" in a confirmation; to the text field in a typed-word confirmation; to the title (with `tabindex="-1"`) in a dialog that only shows information. | Manual: NVDA opens Rename; it reads "Rename printer, dialog, Name, edit, Workshop X1". |
| SR-21 | H W | A destructive confirmation is `role="alertdialog"`. Its sentence names the thing and the consequence ("Forget Workshop X1? Its Access Code is deleted."), and its buttons name the action ("Forget printer", "Cancel"), never "OK" (foundations 1.5). The destructive button is drawn with `--bad` and the icon, and is not the focused button. | Manual: Forget a printer with NVDA. |
| SR-22 | H W | A typed-word confirmation (Restore) labels its field with the instruction ("Type restore to go on"). The main button stays `aria-disabled` until the word matches, and its description says "Type restore to go on." until then. | Manual: Settings > Backups and restore > a checked backup, with NVDA. |
| SR-23 | H W | Text entry dialogs replace every `window.prompt` (rename, change address, Access Code, API key, Klipper host and port). Each has a visible label, the current value filled in and selected (never for secrets), its hint, and its errors in the dialog (FRM-6). Its main button names the action, never "Save" ("Rename", "Change address", "Replace Access Code", "Save key"; `02-components.md` 9.1); that button keeps the dialog open until the Hub answers and puts the result in the dialog's own result slot. | Manual: Change address with an invalid value; the error is in the dialog and the dialog stays open. |
| SR-24 | H W | Overflow menus are `role="menu"` with `menuitem` items (destructive items marked with the icon and the word, and separated, `role="separator"`); the phone appearance menu uses `menuitemradio` with `aria-checked`. The "More" sheet on phones is a dialog with the title "More sections" holding a `nav` list of links, each with its one-line live summary inside the link text. | Manual: NVDA on a printer's overflow menu and on the More sheet. |

### 8.4 The collection in its four renderings

The collection component has one markup that the theme profile draws as table, cards, tiles or rows (foundations 6.1
and 6.2). A screen reader must hear every value with its name in every rendering, and the markup cannot change between
themes. The rule that achieves this:

- The markup is a table with **explicit ARIA roles** on every element: `role="table"` with `aria-labelledby` (the
  heading above it) and `aria-rowcount` when paged; `role="rowgroup"` for the head and for each item, `role="row"`,
  `role="columnheader"` (with `aria-sort` on the sorted column), `role="rowheader"` for the item's name cell,
  `role="cell"` for the rest. A rowgroup holds only rows: each item's rowgroup holds its main row, its result row and
  its detail row, and the result and detail rows each hold one `role="cell"` with `aria-colspan` equal to the column
  count (`02-components.md` 6.1). Nothing else is a child of a rowgroup or a row.
  Explicit roles keep the table semantics when CSS turns rows into cards (some browsers drop the native table meaning
  of `<table>` elements whose `display` is changed).
- Each cell starts with a cell label (`<span>` with the column's name, for example "Address"). In the `table`
  rendering the cell label is `display: none` (the column header names the cell). In `cards`, `tiles` and `rows` the
  header row is `display: none` and the cell label is shown (or, where the design shows only the value, visually
  hidden). `display: none` takes an element out of the accessibility tree too, so a name is never read twice.
- Sorting has two controls with the same effect: the header buttons in the `table` rendering, and a "Sort by" select
  above the collection in the other three, shown by the same CSS profile switch.

| Rendering | A screen reader hears, moving into the first row | Navigation keys |
|---|---|---|
| `table` (Console) | "Workshop X1, row header. Model, X1 Carbon. Address, 192.0.2.40. State, Connected." with column names from the headers | Table keys (NVDA Ctrl+Alt+arrows) and Tab between controls |
| `cards` (Workbench) | "Workshop X1. Model: X1 Carbon. Address: 192.0.2.40. State: Connected." from the cell labels | Same table keys; rows are read as one card each |
| `tiles` (Spool) | Same as cards; the spool ring adds "62 % left" (SR-29) | Same |
| `rows` (Panes) | "Workshop X1. State: Connected. Open Workshop X1, link." The `rows` profile hides the less important cells with `display: none`, so they are neither drawn nor read; they appear in the item's pane | Same |

| ID | Where | Requirement | Check |
|---|---|---|---|
| SR-25 | H W | The collection follows the rule above in all four renderings and in the phone layout. Every value is announced with its name; the item's name is the row header; no value is announced twice. | Manual: NVDA on Printers in each of the four themes, desktop and phone width; read the first row with the table keys and write down what is said. Auto: AUT-5 checks that every `role="cell"` has a cell label or a column header in the accessibility tree. |
| SR-26 | H W | Selection checkboxes are named "Select `<item name>`"; the count is announced in a polite region ("3 selected"). Paging is a `nav aria-label="Pages"` with "Page 2 of 5" as visible text and `aria-current="page"` on the current page. Inline detail opened from a row is a region (`<section>` or `role="region"`, `aria-labelledby` its `h2`) inside the spanning cell of the item's detail row, which follows the main row and the result row in the same rowgroup (8.4), so it comes right after the row in reading order without breaking the table. The empty state is a sentence inside the collection's place, with its one action. | Manual: NVDA on Recently added with the "To check" filter, page 2. |

### 8.5 Pictures, swatches, QR codes, camera

| ID | Where | Requirement | Check |
|---|---|---|---|
| SR-27 | H W | Label photos have alt text that names what they show and where they belong: "Label photo 1 of 2, Polymaker PolyTerra PLA Charcoal Black". A photo with no spool data yet: "Label photo 1 of 3, not read yet". The enlarged viewer is a dialog titled "Photo 1 of 2". A photo that failed to load shows its alt text in a box with the words "The photo could not be loaded". | Auto: AUT-5 fails on an `<img>` without `alt`, or with an `alt` that matches `/^photo \d+$/i`. Manual: NVDA on Recently added. |
| SR-28 | H W | A QR code is never the only way: next to it, as text, is the same information. Pairing a phone: the pairing code (large, `--mono`, with Copy), the link (with Copy), the certificate fingerprint in groups of four, and the expiry (TIM-1). Web app address: the address as a link with Copy. The QR image's alt says what it is for: "QR code for pairing a phone" (`02-components.md`); what it holds is the text beside it. | Manual: Devices > Pair a phone with the QR image hidden (devtools); pairing still possible by the text. |
| SR-29 | H W | A filament swatch is decorative when the colour's name or hex is beside it (foundations 4.1 requires that), so it is `aria-hidden`. The spool ring (Spool theme) is `role="img"` with `aria-label="62 % left, 620 g"`, unless the same numbers are visible text next to it, then `aria-hidden`. A slot in a slot strip is read as one phrase: "Slot A1, Polymaker PolyTerra PLA Charcoal Black, 62 % left, in use" or "Slot A4, empty". | Manual: NVDA on a printer's slots. |
| SR-30 | H W | The printer camera is user-started ("Show camera"), has a name ("Live camera of Workshop X1" as `alt` for the picture stream or `aria-label` for the video), plays muted, and has "Hide camera". Its errors are text next to it. | Manual: show and hide the camera with the keyboard. |
| SR-31 | H W | Icons next to words are `aria-hidden="true"` (foundations 10). Decorative drawings (the theme picker's preview tiles) are `aria-hidden`; the tile's name and one line are its label. | Auto: AUT-5 fails on an `<svg>` without `aria-hidden` that is not inside a named control or a `role="img"` with a label. |

---

## 9. Forms

The field and form group components are in `02-components.md`; this section sets what makes them accessible.

| ID | Where | Requirement | Check |
|---|---|---|---|
| FRM-1 | H W | Every field has a visible label that stays visible while typing. A placeholder is only an example of the format ("e.g. 192.0.2.40 or printer.local"), never the label and never the only place an instruction is written. | Auto: AUT-4 and AUT-5. Manual: type into every field of Add a printer; the labels stay. |
| FRM-2 | H W | Labels are tied to their fields (`<label for>` or a wrapping `<label>`); the hint, the unit and the error under a field are tied with `aria-describedby` (hint id, unit id, error id, in that order, as `02-components.md` 5.1). The error id stays in the list while no error shows; the error element is then empty, so nothing extra is read, and its text is read as soon as it is written. Radio and checkbox groups are a `fieldset` with a `legend`. Fields that belong together (address and port of a Klipper printer; new passphrase and again) sit in a group with a visible group label. | Auto: AUT-5 fails on a field without a label. Manual: NVDA reads label, value, hint and error for the Access Code field. |
| FRM-3 | H W | Required and optional are told in words, not by an asterisk or colour alone: the form group says once at its top which kind is the exception, and each field of that kind carries the word in its label ("Name (optional)"). Required fields have `required` (or `aria-required="true"` on custom fields). | Review; Manual on Add a printer. |
| FRM-4 | H W | Each field uses the input type, keyboard and autofill settings of the table below. | Auto: AUT-5 compares the attributes of the fields it finds with the table, by field name. Manual: iPhone, Add a printer and Add spools; the right keyboard appears for each field. |
| FRM-5 | H W | A secret (setup code, Access Code, Moonraker API key, Anthropic API key, Catalog token, web passphrase) is a password field with a show/hide button beside it (foundations 12.4). The button is named "Show `<field label>`", has `aria-pressed`, keeps focus on itself, and toggles the field between `password` and `text`. Pasting is always allowed. A saved secret is never shown back; its state is shown as a status badge ("Set" / "Not set") with Replace and Remove. | Manual: Settings, Anthropic API key, with NVDA; paste a value, show it, hide it. |
| FRM-6 | H W | Errors are checked when a field loses focus after it was changed (never on first focus, never on every keystroke), and for every field when the group is saved. An error is a sentence under the field with the error octagon, saying what is wrong and how to fix it ("Enter grams above 0, like 812."). The field gets `aria-invalid="true"`, and the sentence is written into its error element, already listed in its `aria-describedby` (FRM-2). The error goes away as soon as the value is valid (checked on input once an error is showing). | Manual: Add spools, type "abc" in Net weight and Tab away; the error appears and is read; type "1000"; it goes. |
| FRM-7 | H W | Saving a group that has errors does not send it. Focus moves to the first field with an error. With two or more errors, the group's error summary (the `role="alert"` region of `02-components.md` 5.1, allowed by SR-19) lists them ("2 fields need a look: Net weight, Empty spool weight"), each as a link that moves focus to its field. | Manual: save a group with two errors with NVDA. |
| FRM-8 | H W | An error from the Hub keeps everything typed (foundations 1.4). When the Hub names the field (see section 17), the error is shown on that field as in FRM-6; otherwise it is shown in the group's inline result, starting with "Not saved:" and the Hub's own words. A raw status code is never the whole message ("HTTP 502" becomes "The Hub did not answer. Check that it is on, then try again."). | Manual: with the Hub stopped, save a group; the edits stay and the message says what to do. |
| FRM-9 | H W | Unlocking with the setup code needs no puzzle, memory test or transcription: paste works, the dash and spaces are optional, password managers are not blocked, and "Trust this computer" is offered after a correct code (foundations 1.8). Wrong codes say how many tries remain before a wait; a lockout says until when (TIM-3). | Manual: unlock by pasting "1234 5678" style input. |
| FRM-10 | H W | Nothing already given in the same visit is asked again: the setup code is kept in memory for the visit (until the tab closes or the person presses Lock); the serial number of a Bambu printer is read from the printer when left empty; a form re-opened after an error keeps its values; Add spools carries values from a chosen filament into the item. | Manual: unlock once, then make three changes in different sections; the code is not asked again. |
| FRM-11 | H W A | When a main action cannot be used yet, the reason is shown next to it, above or beside the button (never only below it, where it can be off screen), in words that say what to do ("Check the spools first: any edit needs a new check."; "Enter a spool count for every item."). On the web the button follows KEY-8. | Manual: Add spools on a phone; edit an item after Check; the reason is visible without scrolling. |
| FRM-12 | H W | A control that applies at once (appearance, theme, a toggle like "Allow printer changes from the public address", the lane data select) says so in its label or hint, never navigates, never moves focus, and reports the result in its inline result ("Lane data: on. Saved."). | Manual: change lane data with NVDA; the result is read; focus stays. |
| FRM-13 | H W A | Actions that delete or replace data ask first or can be undone (foundations 1.2): forget printer, revoke, remove key, restore, roll back, undo of a usage entry, stop print. Adding spools keeps its check step (a dry run) before the real add. | Review against the list of destructive actions in `03-hub-page.md` and `04-web-app.md`. |
| FRM-14 | H W A | Help is always in the same place: a field's help is the hint under the field; a view's help is the first sentence under its `h1`; the command-line equivalent, where shown, is at the end of the group. | Review. |

### 9.1 Input purpose and keyboards

`type="number"` is not used: it changes values on scroll and arrow keys, rejects some decimal separators and reads
poorly. Numbers are text fields with an `inputmode` and are checked by the page.

| Field | `type` | `inputmode` | `autocomplete` | Other attributes |
|---|---|---|---|---|
| Setup code | `password` (show/hide) | `numeric` | `off` | Accepts `12345678`, `1234-5678`, `1234 5678` |
| Access Code, Moonraker API key, Anthropic API key, Catalog token | `password` (show/hide) | `text` | `off` | `autocapitalize="off"`, `spellcheck="false"` |
| Web passphrase, and "again" | `password` (show/hide) | `text` | `new-password` | `minlength="12"`, error text from FRM-6 for a mismatch ("The two passphrases do not match.") |
| Passphrase on the Claude sign-in page | `password` (show/hide) | `text` | `current-password` | |
| Printer address (IP or name), Weigh Station address | `text` | `url` | `off` | `autocapitalize="off"`, `autocorrect="off"`, `spellcheck="false"` |
| Web public address | `url` | `url` | `off` | `spellcheck="false"` |
| Port | `text` | `numeric` | `off` | `pattern="[0-9]*"` |
| Subnet | `text` | `text` | `off` | `autocapitalize="off"`, `spellcheck="false"` (the slash needs the full keyboard) |
| Serial number | `text` | `text` | `off` | `autocapitalize="characters"`, `spellcheck="false"` |
| Names (Hub display name, printer, computer, Tag Reader) | `text` | `text` | `off` | |
| Weights, density, price per kg | `text` | `decimal` | `off` | Unit shown beside the field and in the label ("Net weight (g)") |
| Counts, days, records kept, reads per day, temperatures | `text` | `numeric` | `off` | Unit beside the field where there is one |
| Colour (hex) | `text` | `text` | `off` | `autocapitalize="off"`, `spellcheck="false"`; the `#` is optional |
| Search | `search` | `search` | `off` | `enterkeyhint="search"` |
| Note for the Label Reader, "What is wrong" | text area | `text` | `off` | Spell check on |
| Filament Catalog entry (JSON) | text area | `text` | `off` | `autocapitalize="off"`, `spellcheck="false"`, `--mono` |
| Label photos | `file` | | | `accept="image/*"`, `multiple`; the button text says "Take or choose photos" |
| Backup zip | `file` | | | `accept=".zip"` |

---

## 10. Motion

Foundations 4.3 and 11 set what moves, for how long, and that `prefers-reduced-motion: reduce` turns durations to
0 ms and spinners into a static "Working…" label.

| ID | Where | Requirement | Check |
|---|---|---|---|
| MOT-1 | H W | With reduced motion on: every transition and animation of every theme has 0 ms duration (the token values do this; no component sets its own duration); spinners are replaced by the static "Working…" label; scrolling into view is instant (`scroll-behavior: auto`, and `behavior: "auto"` in script); skeletons do not shimmer; progress bars jump to their new value. | Auto: AUT-2 fails on a duration that is not a motion token. Manual: Windows "Animation effects" off, or devtools "Emulate CSS prefers-reduced-motion: reduce"; open a sheet, run Map slots. |
| MOT-2 | H W A | Nothing flashes more than three times in one second. No parallax, no animated backgrounds, no motion that does not explain a change of place or state (foundations 11). | Review. |
| MOT-3 | H W | Animations never delay input or focus: focus moves into a sheet as it starts to rise, and a control is usable during its own transition. | Manual: open the More sheet and press Tab at once, while it still rises; focus moves from the first row to the second. |
| MOT-4 | H W | Content that moves by itself for more than 5 seconds can be paused: the job log stops following new lines as soon as the person scrolls it up or focuses it, and offers "Follow the log" to resume; the camera has "Hide camera". | Manual: run Back up now, scroll the log up; it stays still. |

---

## 11. Time limits

| ID | Where | Requirement | Check |
|---|---|---|---|
| TIM-1 | H | The pairing dialog (Pair a phone, Link Slicer Sync, Link a Weigh Station; `03-hub-page.md` 7.2) shows the time left as its determinate bar plus the text "Expires in `<n>` min", from `expires_in` in the reply of `POST pair`. The text is the accessible form: it updates once a minute and is not announced on each update; the bar is `aria-hidden`. | Manual: open Pair a phone with NVDA; the dialog reads the expiry text; wait one minute; it changes without being announced. |
| TIM-2 | H | One minute before expiry the dialog announces once (polite) "The pairing code expires in 1 minute." At expiry the bar and code go and the dialog shows the warn result "The pairing code expired. Make a new one." with the primary button **Make a new code** (`03-hub-page.md` 7.2); the result is announced once and focus is not moved (KEY-13). **Make a new code** asks `POST pair` again with the same kind, shows the new code, link and QR code, moves focus to the new code (which has `tabindex="-1"`) and announces "New pairing code. Expires in `<n>` min." The page stops polling `GET state` for the new device at expiry. Nothing expires silently. | Manual: let a code run out with NVDA on, then press Make a new code. |
| TIM-3 | H W | After wrong setup codes, the message says how many tries remain before a wait, and a lockout says until when ("Too many wrong setup codes. Try again at 14:25, or see the code at the Hub: `sudo spoolwarden setup-code`."). The time comes from the Hub (section 17); until the Hub sends it, the message keeps the Hub's own words. | Manual: enter five wrong codes. |
| TIM-4 | H W | A trusted computer's expiry is shown in the lock chip's dialog ("Trusted until 2027-02-10; renewed each time you use it"). When the Hub no longer accepts the trust (`trust_gone` in an error reply), the page says "This computer is no longer trusted. Enter the setup code to go on.", opens the unlock dialog over the change that was refused, and keeps every typed value. | Manual: revoke the trust from another computer, then save on this one. |
| TIM-5 | H W A | Every wait says what it waits for and how long it usually takes ("Asking the Label Reader… up to a minute"; "Building Slicer presets… a minute or two"). Past that time it says "Still waiting… (2 minutes)" and offers Cancel where the Hub can stop the work (`printers/<serial>/map/stop`, `manual-map/stop`). A request that gives up says so in words and keeps what was typed. "The Hub is restarting" past 2 minutes adds how to check it at the Hub (`spoolwarden status`). | Manual: stop the Hub during a save and during Label Reader reading. |
| TIM-6 | H W A | There is no session timeout: the Hub page, the web app and the app never sign out, lock or discard a form because time passed. The one external time limit (a Claude sign-in request on `/login` that expired) is shown in words with what to do ("This sign-in request expired. Start again from Claude."). | Review; Manual: leave a half-filled form open for 30 minutes, then save. |

---

## 12. Language and plain words

Foundations 1.5 and 2 set the words. These rules make them work for people using assistive technology and for people
who read with effort.

| ID | Where | Requirement | Check |
|---|---|---|---|
| LNG-1 | H W A C | Only the names of foundations 2 appear in the UI. Internal words never do: no `ai_intake`, `gcode_state`, module, endpoint, job id, HMS (shown as "Printer alert"), dry run (shown as "Check"), exit code without words. | Auto: AUT-7 searches UI strings for a list of banned words. |
| LNG-2 | H W A C | A button says what happens ("Forget printer", "Back up now"); a link says where it goes ("Open Features"), never "here" or "more"; two controls with the same words on one view do the same thing. | Auto: AUT-7 bans "click here", "here", "OK" as whole button or link texts. Review. |
| LNG-3 | H W A C | An error says what went wrong and what to do next, in one or two sentences. Text from the Hub that the page cannot map is shown after "The Hub said:". | Review. |
| LNG-4 | H W A C | The same thing has the same name, the same icon and the same status words in all four interfaces (foundations 1.6). | Review against the names table of foundations 2 and the status badge vocabulary. |
| LNG-5 | H W A C | Instructions never depend on colour, shape or position alone ("press the green button", "the box on the right" are not allowed); they name the control. | Review. |
| LNG-6 | H W A C | Messages keep sentences under 25 words and one idea per sentence. Product terms that must stay (Access Code, AMS, Moonraker) are explained once in the hint of the field or place that uses them. | Review. |
| LNG-7 | H W A C | One spelling throughout, the one the foundations use ("colour"); numbers, units and dates as in foundations 2. | Auto: AUT-7 bans "color" in UI strings. Code identifiers and command-line flag names (such as `--color`) are not UI strings. |

---

## 13. Android app

The app maps the same tokens and components onto Material 3 (`08-platform-mapping.md`). Every web requirement above
that names "A" applies to the app as well; this section adds what is specific to Android. Check tools: TalkBack,
Switch Access, a Bluetooth or USB keyboard, Accessibility Scanner, and Compose UI tests (AUT-8).

| ID | Requirement | Check |
|---|---|---|
| AND-1 | Every icon-only control has a `contentDescription` with the same words as the web's `aria-label` ("More actions for Workshop X1", "Show Access Code"). Icons beside words have `contentDescription = null`. Label photos are described as in SR-27; the camera preview is "Camera preview" and the shutter button "Take photo". | Auto: AUT-8. Manual: TalkBack on Printers and Add spools. |
| AND-2 | Screen titles and section titles are headings (`Modifier.semantics { heading() }`), so TalkBack's heading navigation moves between them. One screen title per screen. | Auto: AUT-8 checks that each screen's top app bar title has `Heading` and is the only `Heading` node in the top app bar, and that the section titles the test lists for that screen have `Heading`. Manual: TalkBack, reading controls set to Headings. |
| AND-3 | A collection row or card is read as one phrase: it uses `Modifier.semantics(mergeDescendants = true)` (or a merging `clickable`) so TalkBack says "Workshop X1, X1 Carbon, Connected, button". Buttons inside the row stay separate focus stops. A swatch, status dot or spool ring inside a merged row uses `clearAndSetSemantics { }` with no description when the words are already in the row, or a `contentDescription` like "62 % left" when they are not. | Manual: TalkBack swipes through Printers; one stop per row plus one per inner button. |
| AND-4 | TalkBack order follows the visual order: top app bar, content top to bottom, bottom bar. Cards and groups that must be read together set `isTraversalGroup = true`; `traversalIndex` is used only where the visual order cannot follow the composition order, and each use has a comment saying why. | Manual: TalkBack swipe from the top on Home, Printer and Add spools. Review of every `traversalIndex`. |
| AND-5 | A checkbox, switch or radio row toggles when any part of the row is pressed: the row has `Modifier.toggleable(value, role = Role.Checkbox)` (or `Role.Switch`, or `selectable(role = Role.RadioButton)` inside `selectableGroup()`), and the inner `Checkbox`, `Switch` or `RadioButton` has `onCheckedChange = null` / `onClick = null`, so TalkBack reads one control: "Sealed spools only, checkbox, checked". This replaces today's checkboxes that toggle only on the box. | Manual: tap the words of "Sealed spools only"; it toggles. Auto: AUT-8 finds no `Checkbox` with a non-null `onCheckedChange` inside a row that also has text. |
| AND-6 | Every touch target is at least 48 x 48 dp: Material components keep their minimum interactive size (`LocalMinimumInteractiveComponentSize` is never set lower), and custom clickables use `Modifier.minimumInteractiveComponentSize()`. Text buttons in rows ("Unload", "Undo", "Remove") reach 48 dp. Adjacent targets have at least 8 dp between them. | Manual: Accessibility Scanner "Touch target" on Printer, Add spools, Spools. Auto: AUT-8 asserts `assertHeightIsAtLeast(48.dp)` and `assertWidthIsAtLeast(48.dp)` on every clickable node of the tested screens. |
| AND-7 | A row with several actions (a slot with Load and Unload, a usage entry with Undo, a photo with Remove) also offers them as TalkBack custom actions (`semantics { customActions = … }`) named like the buttons. A swipe gesture (dismissing a sheet or snackbar) always has a button too. | Manual: TalkBack actions menu on a slot row lists Load and Unload. |
| AND-8 | Text sizes are in `sp` through the theme's `Typography`; no fixed heights on anything holding text. At font scale 200 % (Android 14 and later scale large text non-linearly) nothing a person must read to act is cut off or ellipsized: button rows use `FlowRow` and wrap; buttons grow to two lines rather than truncate; a name may ellipsize in a list only when the full name is in the row's content description and on its detail screen. | Manual: `adb shell settings put system font_scale 2.0`, walk Home, Spools, Printer, Add spools, Spool. |
| AND-9 | With font scale 200 % and the largest display size together, dialogs and bottom sheets scroll, the bottom bar keeps its labels (it grows in height), and the top app bar title wraps to two lines before it ellipsizes. | Manual: Settings > Display size largest plus `font_scale 2.0`, open Forget printer and the More sheet. |
| AND-10 | Inline results and status lines that change are polite live regions (`semantics { liveRegion = LiveRegionMode.Polite }`), with the same rules as SR-13 and SR-17 (state changes only, never every update). Toasts are snackbars held 5 seconds (10 seconds when they hold an action, as SR-14), do not disappear while they hold focus, and are announced by the system. Progress uses `LinearProgressIndicator` with `progressSemantics` and a `stateDescription` in words, announced at the steps of SR-15. | Manual: TalkBack, Map slots and Update weight; announcements as in SR-15. |
| AND-11 | Status is shape plus word (COL-1) with colours from the theme roles generated from the tokens; no hard-coded `Color(0xFF…)` remains for status. The status node has a `stateDescription` with the word ("Connected"). | Auto: AUT-8 greps the app's Kotlin for `Color(0x` outside the theme file and the swatch. Manual: dark mode on Printers. |
| AND-12 | Dialogs and bottom sheets are Material `AlertDialog` and `ModalBottomSheet` with a title (`paneTitle` for sheets) so TalkBack announces them; focus goes inside when they open; the system Back closes them as Cancel, after the unsaved-changes guard when something was typed; when they close, focus returns to the control that opened them (a `FocusRequester` on the trigger). Destructive buttons name the action (SR-21). | Manual: TalkBack, Forget printer; then Back; focus is on "Forget printer". |
| AND-13 | Text fields always have a `label`; hints and errors are in `supportingText`; an error sets `isError = true` and `semantics { error("…") }` with the same sentence as the web (FRM-6). Keyboards: `KeyboardType.Number` for counts and ports, `Decimal` for weights, `Uri` for addresses, `Password` for secrets, `NumberPassword` for the 6-digit pairing code; `imeAction` Next between fields and Done on the last. Secret fields have a visibility button named "Show `<field label>`" and keep the typed value across rotation only in memory. Pasting is allowed in every field. | Manual: Pair by address; Add printer; Add spool with an invalid weight under TalkBack. |
| AND-14 | Everything works with a hardware keyboard and with Switch Access: every control is focusable, the focus indication is visible (custom clickables keep an `indication`), Enter or Space activates, Escape or Back closes the top layer. | Manual: connect a keyboard; Tab and arrow through Home, Spools, a Spool screen. |
| AND-15 | When the system's "Remove animations" is on (animator duration scale 0), the app uses 0 ms for every motion token, and spinners become the static "Working…" text (MOT-1). | Manual: `adb shell settings put global animator_duration_scale 0`; open a sheet; run Map slots. |
| AND-16 | An NFC tap that opens the Spool screen announces its title ("Spool: Polymaker PolyTerra PLA Charcoal Black") and gives a short vibration. A photo taken announces "Photo 2 of 8 taken". QR scanning always offers "Enter address instead" on screen. | Manual: TalkBack, tap a tag; take a photo. |
| AND-17 | The app does not lock orientation and works in landscape and in split screen at compact width (TXT-10). | Manual: rotate on Printer; split screen with another app. |
| AND-18 | Accessibility Scanner reports no issue on any screen in light and dark at font scale 100 % and 200 %; a reported issue that is a false positive is listed with its reason in the test notes of the release. | Manual: release checklist step 7. |
| AND-19 | Explore by touch works on every screen: touching any drawn element makes TalkBack read it, in the same unit as swiping does (a merged row is read whole, AND-3; a button inside it alone), and a double tap then activates it. Each node's touch bounds are its drawn bounds, at least 48 x 48 dp for controls (AND-6). Nothing invisible can be touched or read: a closed sheet, a scrim, an off-screen pane or a hidden page leaves no node in the tree (it is removed from composition, or marked `invisibleToUser()` while it animates out). | Manual: TalkBack on; drag one finger slowly over Home, Spools, Printer and Add spools, and over the area where a sheet was just closed; every element is read once where it is drawn and nothing else is read. |

---

## 14. Command line

The command line is specified in `06-command-line.md` (status vocabulary, `--color auto|always|never`, `NO_COLOR`,
`--json`, confirmations, menus). These requirements make it usable with a screen reader in a terminal.

| ID | Requirement | Check |
|---|---|---|
| CLI-1 | No meaning is carried by colour alone: every status is a word (OK, needs a look, note; connected, offline; on, off; set, not set), with colour only added on top. With `NO_COLOR` set, `--color never`, or stdout not a terminal, output contains no escape sequences. | Auto: AUT-9. Manual: `NO_COLOR=1 spoolwarden status`. |
| CLI-2 | A status glyph is always followed by its word (`06-command-line.md` 6.1). In plain mode (CLI-3) the glyph is left out and only the word is printed, because screen readers read glyphs as their character names; the other symbols use their ASCII forms (06 6.2). | Auto: AUT-9 checks plain output is ASCII except data that came from the user (names). |
| CLI-3 | Two switches are added to those of `06-command-line.md` (6.2, 6.6, 6.8). Both are accepted by every command, like `--color`. **`--plain`** (also `SPOOLWARDEN_PLAIN=1` in the environment, and implied by `TERM=dumb`) is the screen-reader mode. It sets, for that run, switches 06 already has: `--numbered` (`SPOOLWARDEN_MENU=numbered`: numbered menus, same keys and words, no full-screen screens), `SPOOLWARDEN_GLYPHS=ascii`, `--color never`, and `--text` on `pair`. It adds four things 06 has no switch for: glyphs left out (CLI-2); progress as whole lines, never rewritten in place (CLI-4); tables always printed as blocks, one `Label: value` line per field and a blank line between items, the form 06 6.3 uses below 60 columns, so no value depends on its column position; secret prompts without echo (CLI-8). **`--no-progress`** is described in CLI-4. | Auto: AUT-9 fails on ESC (0x1b) or CR (0x0d) bytes in `--plain` output. Manual: `spoolwarden printer list --plain` read with NVDA in Windows Terminal over SSH to the Hub. |
| CLI-4 | Progress follows `06-command-line.md` 6.6 (a progress line once a wait passes 2 seconds; never on standard output). `--no-progress` prints each progress line once, as a whole line without the counter (the form 06 6.6 uses when standard error is not a terminal), then the step's result line. `--plain` prints the same first line and, while the wait lasts, one more whole line every 10 seconds with the time so far ("Connecting to Workshop X1 at 192.0.2.40… 10 s"). `--quiet` drops progress lines entirely, as 06 6.8 says, and therefore needs no `--no-progress`. | Manual: `sudo spoolwarden backup create --no-progress`; one progress line, then the result line. |
| CLI-5 | Nothing waits silently: in every mode except `--quiet`, every wait longer than 2 seconds has its progress line from the table of 06 6.6 (today a printer connection can wait 30 seconds without output). | Manual: map the slots of an offline printer with `--plain`; a line within 2 seconds, then one every 10 seconds. |
| CLI-6 | Results go to standard output; errors go to standard error, menu errors included, with the first line `Error: ` and, when something can be done, a second line `Fix: ` (06 6.5); notes start with `Note: `. Exit codes as in 06 6.7. | Auto: AUT-9 runs a failing command and checks standard output is empty and standard error starts with "Error: ". |
| CLI-7 | Prompts say the choices in words, accept whole words as well as letters ("yes", "y"), show the default in capitals ("[y/N]") and never time out. Every interactive screen has the one way to leave that `06-command-line.md` defines, and says it on the screen. | Manual: a destructive command without `--yes`; read the prompt with a screen reader. |
| CLI-8 | Secret entry echoes one `*` per character at a terminal (06 8.3). In plain mode it echoes nothing and the prompt ends with "(typing is not shown)", so a screen reader does not say "star" for each key. | Manual: `sudo spoolwarden config --plain`, set the Anthropic API key. |
| CLI-9 | A QR code printed in the terminal is always followed by the same information as text: the pairing code, the link, the certificate fingerprint in groups of four and the expiry time (06 9.4). In plain mode the QR code is not printed (`--text`). | Manual: `sudo spoolwarden pair --plain`. |
| CLI-10 | Every line is at most one character less than the terminal width, so at most 79 characters at 80 columns (06 6.3); longer text wraps at spaces, never inside a word, a number or an address. | Auto: AUT-9 runs its commands with `COLUMNS=80` and fails on any line over 79 characters. |
| CLI-11 | `-h` help is plain sentences with the names of foundations 2 and one example per command, using example data only. | Review. |

---

## 15. Automated checks

Every check below runs in the build and fails it, except where the row says it reports for review. None of them
ships with Spoolwarden; they are tests. A check that did not run is reported as not run, never as passed.

| ID | Check | Input | Fails when |
|---|---|---|---|
| AUT-1 | **Contrast over tokens.** Reads `tokens/tokens.json`, resolves the eight token sets (Console, Workbench, Spool, Panes; light and dark), and computes the WCAG ratio of every pair in 3.1 and 3.2, comparing the unrounded ratio with the requirement. The existing `tokens/check_contrast.py` already checks the pairs of 3.1 except `--focus` on `--surface-2`; AUT-1 adds that pair and those of 3.2 (where `--accent-text` on `--accent-soft` and `--text` on `--surface-3` are only advisory today and become required). Translucent tokens (`--scrim`) are skipped. Also checks the Android roles of CON-8 from the generated Kotlin theme. | `tokens.json`; the generated Kotlin theme | A pair is below its ratio, or a token of a pair is missing from a set. The message names theme, appearance, pair, ratio and requirement: "spool dark: --muted on --surface-2 is 4.31:1, needs 4.5:1 (CON-1)". |
| AUT-2 | **Literal style lint.** Reads every shipped stylesheet. | `*.css` served by the Hub | A literal colour (hex, `rgb()`, `hsl()`, a colour name other than `transparent`, `currentColor`, `inherit`) appears outside the token blocks (foundations 12.5); a `font-size` is in `px` or is not a type token; a `line-height` is in `px` or is not one of the unitless values of foundations 4.2; a duration is not a motion token; `opacity` below 1 is set on a state of text or a control; `outline: none` or `outline: 0` appears in a rule that draws no other focus ring; `var(--accent)` appears in a rule whose selector is not one of the labelled fills listed in the lint (CON-9). |
| AUT-3 | **Native dialog lint.** Reads every shipped script. | `*.js` served by the Hub | Any call of `alert`, `confirm` or `prompt`, with or without `window.`, `self.` or `globalThis.`, or through bracket access (`window["confirm"]`) (foundations 12.4). |
| AUT-4 | **Missing label lint (static).** Fields are created only through the field component, which always renders a visible label. | `*.js` served by the Hub | An `input`, `select` or `textarea` element is created anywhere outside the field component, or the field component is called with an empty label. |
| AUT-5 | **Page audit (runtime).** A small audit script kept with the tests runs in a headless browser against the Hub page and the web app served with fake data (the content of `mockups/CONTENT-SPEC.md`), for every view, in all four themes, light and dark, at 1280 px and 320 px wide. The same script can be pasted into the browser's developer console by a tester (the console is not limited by the page's Content-Security-Policy). | The rendered pages | Any of: a focusable element without an accessible name; a field without a label; a name that does not start with the visible text (SR-7); not exactly one `h1` outside open layers; a heading level skipped; a landmark missing or doubled (SR-3); `lang` missing; title empty or unchanged between views; `tabindex` above 0; `<img>` without `alt` or with "photo N"; an `<svg>` neither hidden nor named; a disclosure button without `aria-expanded`; a region still `aria-busy="true"` after load; a result slot without a `role="status"` region at load; a `role="cell"` with neither a column header nor a cell label; a field whose attributes differ from 9.1; a hit area under 44 x 44 px; horizontal page scroll at 320 px; a viewport meta that blocks zoom. |
| AUT-6 | **Event and announcement lint.** | `*.js` served by the Hub | Fails on `pointerdown`, `mousedown` or `touchstart` handlers (TGT-5), except those on an allow-list file that names only the photo viewer's pan and zoom handlers (TGT-6). Reports, for review, every `role="alert"` and `aria-live="assertive"` (SR-19). |
| AUT-7 | **Words lint.** Reads the UI strings of the web pages and the app (string literals passed to text in the page scripts; `Text(…)` and string constants in the app). An allow-list file holds reviewed exceptions. | Shipped scripts and the app's Kotlin | A banned internal word appears (LNG-1: `ai_intake`, `gcode_state`, module, endpoint, job id, HMS, dry run, and the old names in the "Was" column of foundations 2); a word of the "Never" column of the shared wording table (`08-platform-mapping.md` section 12); "color"; a whole button or link text of "OK", "here" or "click here". |
| AUT-8 | **Android semantics tests.** Compose UI tests for Home, Spools, Spool, Add spools, Printers, Printer and Settings, in light and dark, at font scale 1 and 2. Where the Compose test library offers its built-in accessibility checks (`enableAccessibilityChecks()`), they are switched on. | The app's UI tests; the app's Kotlin | A clickable node without text or content description; a screen without its one heading; a clickable smaller than 48 x 48 dp; a `Checkbox` or `Switch` with its own click handler inside a row that has text (AND-5); `Color(0x…)` outside the theme file and the swatch (AND-11). |
| AUT-9 | **Command-line output.** Runs `status`, `printer list`, `recent`, a failing command and, as root, `pair --text` against a test Hub with example data, with `COLUMNS=80`, each with `NO_COLOR=1`, with `--plain` and with standard output piped. | Captured standard output and standard error | An ESC byte with `NO_COLOR` or piped standard output; an ESC or CR byte or a non-ASCII glyph in `--plain` output (user data excepted); an error on standard output, or an error whose first line does not start with "Error: "; a line over 79 characters. |

---

## 16. Release checklist

One tester, one hour or less. Run it on the release build, with the fake data of `mockups/CONTENT-SPEC.md` (or a test
Hub with example data only). Write down each step as passed, failed (with what happened) or not run. A step not run is
not passed.

Equipment: a computer with Firefox and NVDA (or Safari and VoiceOver); an iPhone with VoiceOver; an Android phone
with TalkBack and Accessibility Scanner; a terminal on the Hub.

| Step | Minutes | Do | Passes when |
|---|---|---|---|
| 1 | 2 | Open the build's results of AUT-1 to AUT-9. | All nine ran and passed. |
| 2 | 8 | **Keyboard only**, Hub page, Console light, 1280 px. Tab once (skip link), Enter. Go to Printers. On Workshop X1: overflow menu with the keyboard, Rename, type, Escape (the guard "Leave without saving?" appears, focus on Stay), Enter on Stay (back in Rename with the text), Escape again, Leave without saving. Forget printer: Tab ten times, Escape. Settings > General: change Display name, Enter. Settings > Backups and restore: Back up now; open the job strip; scroll its log with the arrow keys. | Every step done without a mouse; ring always visible and never hidden under a bar; focus returns to the trigger each time; nothing announced twice (step 3). |
| 3 | 10 | **Screen reader**, same browser with NVDA (or VoiceOver). Landmark list and heading list on Printers. Read the first row of the printers table with the table keys. Test connection on Workshop X1 and on Study A1 mini. Repeat Rename and Forget printer from step 2. Back up now. | Landmarks and headings as SR-3 to SR-5; each value read with its name; both test results read without moving focus; dialogs read with title and sentence; exactly two job announcements. |
| 4 | 6 | **Themes**: switch to Workbench, Spool and Panes, each in light and dark. On Printers, Tab through one row and read its status; in Panes drill into a printer and back. Turn on greyscale emulation once. | Ring visible in all eight; statuses told apart in greyscale; NVDA reads Workbench cards and Spool tiles with field names (SR-25); Panes returns focus to the row. |
| 5 | 6 | **Zoom, reflow, motion**: 200 % zoom on Settings; 320 px wide on Printers and Recently added; paste the text-spacing rule (TXT-7); turn on reduced motion and open the More sheet. | Nothing cut off or overlapping; no sideways page scroll; no animation; spinners show "Working…". |
| 6 | 10 | **iPhone, web app, VoiceOver**: Add spools by hand: focus each field (no page zoom; right keyboard); type "abc" in Net weight; Check, then Add. Open a spool. Printers: Load into slot A4. | Labels read with hints and errors; the reason beside Add is read before Check; results read where they appear; slot read as one phrase. |
| 7 | 12 | **Android, TalkBack**: Home, first by swiping, then by dragging a finger over it (explore by touch, AND-19); Spools with "Sealed spools only" toggled by its words; open a Spool screen; Printers > Workshop X1: status, slot custom actions, Unload confirmation and Back. Then font scale 200 % with the largest display size: Home, Printer, Add spools. Accessibility Scanner on Home, Printer and Add spools. | One stop per row; touch reads the same units as swiping; headings navigable; dialogs announced and focus returned; nothing cut off at 200 %; Scanner shows no issue. |
| 8 | 4 | **Command line**: `spoolwarden status --plain`; `NO_COLOR=1 spoolwarden printer list`; `sudo spoolwarden config --plain`, leave with the documented key; one destructive command without `--yes`, answer "no". | Words for every status; no glyphs or escape codes in plain output; the leave key is on screen; the prompt names the action and its default. |
| | **58** | | |

---

## 17. Needs from the Hub

The requirements above use only what the Hub offers today, except these. Until each exists, the page or app falls back
as stated in the requirement.

| Need | For | Today |
|---|---|---|
| Error replies of endpoints that check input carry the field they are about, as an optional `field` key with the same name as the request body's key: `{"error": "<text>", "field": "access_code"}`. Endpoints: `POST printers`, `POST printers/klipper`, `printers/<serial>/rename`, `…/address`, `…/code`, `…/api_key`, `settings/general`, `settings`, `settings/spoolman`, `passphrase`, `key`, `backups/keep`, `readers`; in the web app `add`, `open`, `printers/add`, `printers/{id}/edit`; in the app's API the matching `api/…` calls. | FRM-8, AND-13: show the Hub's error on the field, with `aria-invalid` | `{"error": "<text>"}` only; the error goes to the group's inline result. |
| A wrong setup code reply carries `tries_left`, and a lockout reply carries `retry_at` (local time, `YYYY-MM-DDTHH:MM`). | TIM-3, FRM-9 | The text "too many wrong setup codes: wait 10 minutes …" only. |
| The reply of `GET trust` includes this computer's trust expiry (`expires`), as `POST trust/list` already does for each computer. | TIM-4: "Trusted until …" in the lock chip's dialog without asking for the setup code | The expiry is only in `POST trust/list`, which needs the setup code. |
