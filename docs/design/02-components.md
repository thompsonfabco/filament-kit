# Spoolwarden design: components

This document specifies every reusable component of the Spoolwarden interface: what it is for, what it is made of,
which tokens it uses, how it behaves, how it is announced to assistive technology, how it changes with the layout
profile of a theme, which Material 3 component it becomes in the Android app, and what its HTML looks like. The Hub
page and the web app are built from these components and nothing else.

`01-foundations.md` is binding and is not repeated here. References such as "foundations §4.3" point into it. Token
names, part names (section 2 of the foundations) and status words come from there.

Contents: 1 Conventions · 2 App shell · 3 Lock and appearance · 4 Actions · 5 Fields and forms · 6 Collections and
detail · 7 Showing data and status · 8 Progress and feedback · 9 Dialogs and sheets · 10 Page states ·
11 Problems of the current interfaces and where they are solved · 12 Needs from the Hub

---

## 1. Conventions

### 1.1 Class names

One scheme for every component:

| Kind | Form | Examples |
|---|---|---|
| Block (the component) | The component's name: one lowercase word, or two joined by a hyphen | `btn`, `coll`, `detail`, `slot-strip`, `page-head` |
| Element (a part of it) | Block, two underscores, part name | `coll__row`, `nav__item`, `dialog__foot` |
| Variant (a fixed kind) | Block, two hyphens, variant name; a variant of a part: part, two hyphens, variant name | `btn--primary`, `dialog--drawer`, `coll__row--detail` |
| Several blocks on one element | Allowed when the element is both things | `class="appearance segmented"`, `class="subnav__dirty status status--warn"` |
| State | A native or ARIA attribute where one exists (`disabled`, `aria-disabled`, `aria-expanded`, `aria-invalid`, `aria-busy`, `aria-current`, `aria-checked`, `aria-sort`, `:checked`); otherwise `data-state="…"` | `[aria-expanded="true"]`, `[data-state="running"]`, `[data-state="dirty"]` |
| Theme profile | Never in markup. CSS selects on `:root[data-look="…"]` (foundations §6.2) | `:root[data-look="panes"] .coll` |
| Script hook | `data-action`, `data-id`, `data-col`, `data-prio`, `data-tab`, `data-group`, `data-section` (a page's section), `data-draft` (a form group whose input is kept as a draft, 5.11), `data-effect` (a field whose saving restarts the Hub or starts an apply job, 5.11), `data-photo` (a thumbnail's photo id, 7.6), `data-revision` (a revision's id, 7.10); never a class | `data-action="test"` |
| Theme preview | `data-preview="<look>"` on a theme picker's drawing (3.4): each theme's token blocks also match it | `data-preview="spool"` |
| Utility | Only three: `sr` (visually hidden, still read), `mono` (`--mono`, tabular numbers), `muted` (`--muted`) | `<span class="sr">Connected: </span>` |
| Icon | `icon` (20 px), `icon--s` (16 px), `icon--l` (28 px); symbol ids in the inline sprite `i-<name>` for icons, `s-<shape>` for status shapes; only the icons of foundations §10. The one chevron, `i-chevron`, points right; CSS turns it (down in a select, up or down by `aria-sort` in a sort button) | `<svg class="icon"><use href="#i-printer"/></svg>` |
| Icon sprite | `sprite`: the one hidden inline `<svg>` near the top of `body` that holds every `<symbol>` (`i-<name>`, `s-<shape>`); `aria-hidden="true"`, never shown | `<svg class="sprite" aria-hidden="true">…</svg>` |

There are no `is-*` or `has-*` classes, no theme names in class names and no inline `style` or `script` (foundations
§12 rule 2). Two deliberate exceptions to "a part lives inside its block": every status shape on the page, wherever it
appears (results, toasts, banners), is drawn with `status__shape`; and per-collection column layouts are the one
place a block gets a per-use variant (`coll--printers`, see 6.1). Other blocks used throughout: `skip` (the skip
link), `actions` (a row of buttons; `actions--list` a two-column list of ghost buttons), `result` (8.6).

### 1.2 Lengths

Every length is a token of foundations §4.3 or a `calc()` of tokens. Lengths used by several components:

| Use | Value |
|---|---|
| Icon | `calc(var(--s4) + var(--s1))` = 20 px; small `var(--s4)` = 16 px; large `calc(var(--s5) + var(--s1))` = 28 px |
| Status shape | `var(--s2)` = 8 px (triangle and octagon `calc(var(--s2) + var(--s1) / 2)` = 10 px) |
| Spacing (padding, gap, margin) | Only the steps `--s1` to `--s7`, never a sum with a literal (foundations §4.3). Sizes of drawn parts may be a `calc()` of tokens with plain numbers, as in the rows above |
| Hairline, focus ring, active mark | 1 px, 2 px with 2 px offset, 3 px: the literal values foundations §4.1, §8 and §10 give |
| Minimum hit area | 44 px (48 dp on Android); a smaller visible control gets an `::after` that reaches 44 px (foundations §4.3) |
| Sidebar width (`nav` = `sidebar`) | `var(--side-w)`: the theme's `size` entry `side-w` (256 px in every theme) |
| Section pane width (`nav` = `list`) | `var(--list-w)`: the theme's `size` entry `list-w` (Panes 360 px) |
| Drawer and wide sheet width | 420 px, as foundations §7 |
| Floating limits | Menus `min(20rem, 100vw - 2 * var(--s4))`; toasts and the job strip `min(25rem, 100vw - 2 * var(--s4))`; dialogs `min(30rem, …)`, wide dialogs `min(45rem, …)`. Given in `rem` so they grow with the text-size setting, like the content width of foundations §7 |

### 1.3 Layout profiles

A theme's layout profile (`nav`, `collection`, `detail`, foundations §6.1) reaches the components in two ways:

1. **Layout is CSS only.** Base rules render the Console profile (`rail`, `table`, `inline`). Each other profile
   value has one block of rules under the look that uses it, for example
   `:root[data-look="workbench"] .coll { … }` for `cards`. The markup does not change.
2. **Behaviour reads the profile.** One shared function `profile()` returns `{nav, collection, detail}` for the
   current `data-look` from the fixed table of foundations §6.1 (missing or unknown look = Console). Components ask it
   only what CSS cannot express: whether an open detail region is modal (`sheet`), how many details may be open at
   once, and whether the navigation's overflow opens as a menu or a sheet. A theme supplies no script.

Breakpoints are the three of foundations §7: **phone** (up to 600 px), **tablet** (601 to 1024 px), **desktop** (over
1024 px). On Android they are the compact, medium and expanded window size classes.

### 1.4 Shared behaviour every component follows

- **Text from the Hub** goes in with `textContent` (foundations §12 rule 3). Nothing the Hub sends is inserted as
  HTML.
- **Colours from data** (filament colours) are checked against `^#[0-9A-Fa-f]{6}$` and set by script with
  `element.style.setProperty('--swatch', value)`; levels likewise with `--level` (a number from 0 to 1); a loading
  button's kept width likewise with `--btn-min` (4.1). These three are the only script-set custom properties. Script-set
  custom properties are not inline style in the markup and are allowed by the Content-Security-Policy. A value that
  fails the check renders as "no colour" (7.3).
- **One shared script.** The Hub page and the web app load the same shared component script, served by the Hub
  from one place. It holds the one implementation of building elements (`textContent` only), calling the Hub (one
  request helper with one shape for its arguments, the setup code and the error reply), `guard()`, `profile()`,
  `announce()`, the dialog (9.1), the toast (8.7), the inline result (8.6) and the other components of this document.
  A page script holds only that page's own places and wiring; it never keeps its own copy of a helper or a component,
  so a fix is made once and reaches both pages.
- **One announcer.** The page holds one visually hidden `aria-live="polite"` element, `#announcer`. `announce(text)`
  clears it and sets the text 30 ms later so repeats are read. Components with their own result area (8.6) use a
  `role="status"` container that exists before the result is written into it.
- **Focus after a change of place.** When the address changes section or opens a page, focus moves to that page's
  `h1` (which has `tabindex="-1"`) without scrolling. When a dialog, sheet or menu closes, focus returns to the
  control that opened it, or to the `h1` if that control is gone.
- **Writes pass the lock.** Every control that changes something on the Hub calls `guard(what, run)`: when the
  Hub page is Locked the unlock dialog (3.2) opens and `run` continues after a successful unlock; when it is
  Unlocked or a Trusted computer, `run` starts at once. The web app and the Android app are allowed to change
  things by the home network and by pairing, so they have no lock.
- **Reads that need the setup code.** Most reading needs nothing, but two kinds of read on the Hub page do:
  1. *Code-only reads*: the backups list (`POST backups/list`), the trusted-computer list (`POST trust/list`),
     Weigh Station pairing requests (`POST stations/requests`), service logs (`POST logs`) and the whole job log
     (`POST job/log`). Each is fetched through `guard()` like a write. While the page is Unlocked or a Trusted
     computer, the place fetches it by itself when it opens, with no Show press. While Locked, the place shows the
     **locked placeholder**: the lock icon, one sentence ("The backups list needs the setup code.") and **Unlock to
     show** (`btn`), which opens the unlock dialog (3.2) and then fetches. The one remaining Show press is where the
     person chooses first what to read (Logs: service and number of lines, then **Show**).
  2. *Hidden values*: a read answered without the code hides addresses and serials and says so (`redacted: true` in
     `GET overview` and `GET job`). The component showing it adds the **hidden-values note**: the lock icon, "Addresses
     and serial numbers are hidden while the page is locked." and **Unlock to show**. The hidden values themselves show as the Hub
     sent them.
  After a successful unlock, every locked placeholder and hidden-values note on the current page re-reads with the
  code (`POST overview`, `POST job/log` and the reads of kind 1) and the results are patched in place by the live
  update rules of 6.1: a focused control or a dirty form is never replaced. **Lock now** reverses it: code-only
  content is removed and replaced by the locked placeholder, and hidden-value reads are fetched again without the
  code. Both are `role="status"` areas, so the change is announced.
- **Answer where the question was asked.** A control's result appears in its own result area (8.6) or, when the
  control has gone away, as a toast (8.7). Never in a shared box elsewhere.
- **Redraw only what changed.** A successful change re-reads and redraws only the form group, row or card it
  changed, never the whole section or page. Everything else stays as it is: text typed and not yet sent in any other
  field (a half-typed passphrase, an API key, a new location), the focused field, open rows and the scroll position.
  A reply that changes the page's height keeps the changed element where it was on screen.
- **Shared data is fetched once per view.** Data that several groups or cards of one view show (the general
  settings, the Filament Catalog state) is requested once when the view opens and handed to each of them, never once
  per card; after a change only the replies that change can have touched are requested again.
- **Reduced motion.** Under `prefers-reduced-motion: reduce` the motion tokens are 0 ms (foundations §4.3); spinners
  show the word "Working…" instead of turning; nothing slides.
- **Words.** Sentence case, the names of foundations §2, units with a space ("62 %", "1000 g"), "…" as one
  character, never three dots.

### 1.5 How each component is described

Every component below has the same nine parts: **Purpose** · **Anatomy** · **Sizes and tokens** · **States** (default,
hover, focus, pressed, disabled, loading, error) · **Behaviour and keyboard** · **Accessibility** · **Theme profiles**
(what changes with `nav`, `collection` and `detail`; token values change with every theme and are not repeated) ·
**Android** (the Material 3 component it maps to; details in `08-platform-mapping.md`) · **HTML**.

---

## 2. App shell

### 2.1 Shell

**Purpose.** The frame every Hub page and web app page sits in: top bar, navigation, the page, and the layers that
float above it (job strip, toasts, dialogs).

**Anatomy.** Skip link "Skip to content" · top bar (2.2) · navigation (2.3) · `main` with one page (2.6) · bottom bar
on phones (2.4) · job strip (8.4) · toast region (8.7) · announcer · dialog layer (dialogs and sheets are `dialog`
elements, children of `body`).

```
Desktop, nav = rail                        Phone (Console, Workbench, Spool)
+--------------------------------------+   +--------------------+
| top bar                              |   | top bar            |
+----+---------------------------------+   +--------------------+
|rail| page (max 1400 px)              |   | page               |
|    |                                 |   |                    |
|    |                    [job strip]  |   |   [job strip]      |
+----+---------------------------------+   +--------------------+
                                           | bottom bar  (5)    |
                                           +--------------------+
```

**Sizes and tokens.** Grid rows `calc(var(--top) + env(safe-area-inset-top))` and `1fr`. Side column `--rail`
(rail), 228 px (sidebar), none (pills), 304 px (list). Page padding `--s5` on desktop, `--s4` on tablet and phone, plus
the safe-area insets; on phones the bottom padding adds `--tab`, the bottom inset and room for the job strip so the
last control is never hidden. Ground `--bg`. Skip link: `--accent` ground, `--on-accent` text, `--r`.

**States.**
- Default: as drawn. The skip link sits above the top edge, out of view.
- Hover: none on the shell itself.
- Focus: the skip link moves into view at the top left when focused.
- Pressed: none.
- Disabled: while the Hub is restarting (8.5) the shell stays usable for reading; write controls are disabled by
  their components, not by the shell.
- Loading: the shell renders at first paint with skeletons (10.3) in the page; it never waits for data.
- Error: when the Hub cannot be reached at all, a banner (8.8) "Cannot reach the Hub" sits at the top of the page;
  the shell stays.

**Behaviour and keyboard.** The address hash selects the section and the place inside it (foundations §8); the shell
listens to `hashchange`, shows the section, sets `aria-current="page"` on its navigation item, updates
`document.title` to "<Page title> · <Hub name>" and moves focus to the page title. Tab order: skip link, top bar, navigation, page, job
strip. The skip link moves focus to `main`.

**Accessibility.** Landmarks: `header` (top bar), `nav aria-label="Sections"`, `main id="main" tabindex="-1"`. The job
strip is a `section` with `aria-label="Background job"`. The toast region and the announcer are live regions (8.7,
1.4).

**Theme profiles.** `nav` sets the grid: rail and sidebar add a side column; pills put the navigation inside the top
bar; list adds the section pane, and on desktop a third pane for details (6.2). `collection` and `detail` do not
change the shell.

**Android.** `Scaffold` inside a `NavigationSuiteScaffold` (navigation bar on compact, rail on medium, drawer or rail
on expanded); the Panes look uses `ListDetailPaneScaffold`.

**HTML.**
```html
<body>
  <a class="skip" href="#main">Skip to content</a>
  <div class="shell">
    <header class="topbar">…</header>
    <nav class="nav" aria-label="Sections">…</nav>
    <main class="shell__main" id="main" tabindex="-1">
      <section class="page" data-section="printers">…</section>
    </main>
  </div>
  <section class="job" aria-label="Background job" hidden>…</section>
  <div class="toasts" aria-live="polite"></div>
  <div class="sr" id="announcer" aria-live="polite"></div>
</body>
```

### 2.2 Top bar

**Purpose.** Says where you are (product, Hub name, version) and holds the three global controls: job indicator, lock
chip, appearance control (foundations §8).

**Anatomy.** Left: product mark (decorative SVG), "Spoolwarden", a slash, the Hub's name, the version tag. Right: job
indicator (only while a job runs or has just ended), lock chip (3.1), appearance control (3.3). With `nav` = `pills`
the pill navigation sits between left and right (2.3). In the web app the lock chip is absent.

**Sizes and tokens.** Height `--top` plus the top safe-area inset; `--surface` ground, 1 px `--border` bottom
hairline, no shadow (`--e0`). Product name `--fs-l` weight 650; Hub name `--fs-m` `--muted`; version `--fs-xs` `--mono`
in a 1 px `--border` box with `--r-s`. Gap `--s2`. Job indicator and lock chip are chip buttons: height `--ctl`,
padding `0 var(--s3)`, 1 px `--border-strong`, `--r`, `--fs-m` weight 600.

**States.**
- Default: as described.
- Hover: chip buttons take `--surface-2`.
- Focus: 2 px `--focus` ring on the focused chip.
- Pressed: `--surface-3` on the chip.
- Disabled: never; the chips always open something.
- Loading: before `GET state` answers, the Hub name and version show a skeleton line (10.3) of the same width.
- Error: if `GET state` fails, the Hub name reads "Hub not reachable" in `--bad` with an octagon (7.1).

**Behaviour and keyboard.** The job indicator opens the job strip with its log expanded and moves focus to the log
toggle. The lock chip opens the unlock dialog or the lock dialog (3.1). On phones the top bar keeps the mark, the
product name above the Hub name (two lines, `--fs-l` and `--fs-xs`), the lock chip without its hint, and the
appearance icon button; the job indicator and version move out (the job strip is visible on its own above the
bottom bar). With `nav` = `list` on phones the top bar shows a Back button in front of the mark when the page is
deeper than the section list (2.3).

**Accessibility.** `header` landmark. The mark is `aria-hidden`. The version reads "version 0.5.2" through a hidden
prefix. The job indicator's name is "Background job: <title>, <state>. Show the job panel."; it has
`aria-controls` pointing at the job strip.

**Theme profiles.** `nav` = `pills`: on desktop the pill row sits in the top bar; on tablet it forms a second row of
the top bar, full width. `nav` = `list`: Back button on phones as above. `collection`, `detail`: no change.

**Android.** `TopAppBar` (small) whose title names the place, not the product (foundations §9): the screen's place
name ("Home", "Spools", "Printers", "Settings") or the thing's name; on Home the Hub's name is the subtitle under it.
The appearance control is an `IconButton` in `actions`. No lock chip (the app is paired); the connection chip (3.1)
takes its place.

**HTML.**
```html
<header class="topbar">
  <a class="topbar__brand" href="#overview">
    <svg class="topbar__mark" aria-hidden="true"><use href="#i-spoolwarden"/></svg>
    <span class="topbar__name">Spoolwarden</span>
    <span class="topbar__hub"><span aria-hidden="true">/</span> Workshop Hub
      <span class="topbar__version mono"><span class="sr">version </span>0.5.2</span></span>
  </a>
  <div class="topbar__tools">
    <button class="chip chip--job" type="button" data-state="running"
            aria-controls="job" hidden>…</button>
    <button class="chip chip--lock" type="button" aria-haspopup="dialog" data-state="locked">…</button>
    <fieldset class="appearance">…</fieldset>
  </div>
</header>
```

### 2.3 Navigation

**Purpose.** Reach every section in at most two steps, see which section you are in, and on some profiles see a
live one-line summary of each section. One markup serves all four `nav` profiles and, on phones, the bottom bar
and the More sheet.

**Anatomy.** A `nav` holding two groups (foundations §8): **Everyday** (Overview, Printers, Recently added, Devices,
Slicer presets) and **System** (Features, Settings, Flash a device, Updates, Logs). Each group: a heading and a list.
Each item: icon, label, live summary (one short line, for example "2 connected · 1 offline"), chevron. Items that sit
in the phone bottom bar carry `data-tab`. A **More** button closes the navigation; it is shown only by profiles and
breakpoints that hide items (pills on wide screens, the bottom bar on phones).

```
rail (Console)     sidebar (Workbench)       pills (Spool)                         list (Panes)
+------+           +--------------------+    [Overview][Printers][Recently added]  +--------------------------+
| [ic] |           | EVERYDAY           |    [Devices][Slicer presets][More v]     | EVERYDAY                 |
|Overvw|           | [ic] Overview      |                                          | [ic] Overview          > |
| [ic] |           | [ic] Printers      |                                          |      All checks OK       |
|Printr|           | [ic] Recently added|                                          | [ic] Printers          > |
| ...  |           | ...                |                                          |      2 connected · 1 off |
|------|           | SYSTEM             |                                          | ...                      |
| [ic] |           | [ic] Features      |                                          | SYSTEM                   |
| ...  |           | ...                |                                          | ...                      |
+------+           +--------------------+                                          +--------------------------+
```

**Sizes and tokens.**

| Part | rail | sidebar | pills | list |
|---|---|---|---|---|
| Width | `--rail` | `--side-w` | content width | `--list-w` pane |
| Item | Icon over label, min height 56 px (`calc(var(--s7) + var(--s2))`), margin `0 var(--s1)`, `--r` | Icon left of label, height `--ctl`, padding `0 var(--s3)`, `--r` | Icon left of label, height `--ctl`, padding `0 var(--s4) 0 var(--s3)`, radius `--r-l` (pill shape comes from the Spool token values) | Icon in a `calc(var(--s5) + var(--s1))` tile, label, summary line, chevron; min height `calc(var(--s7) + var(--s1))`; inset hairline `--border` between rows |
| Label | `--fs-xs` weight 600 | `--fs-m` weight 600 | `--fs-m` weight 600 | `--fs-b` weight 600 |
| Summary | hidden | hidden | hidden | `--fs-s` `--muted` |
| Group heading | visually hidden; groups split by a 1 px `--border` hairline | `--fs-xs` uppercase, 0.05em spacing, `--muted` | hidden (System group lives in More) | `--fs-xs` uppercase, `--muted`, above a grouped `--surface` block with `--r` |
| Active | `--accent-soft` ground, `--accent-text`, weight 650, 3 px `--accent-text` mark on the outer edge | same, mark on the left edge | `--accent-soft` ground, `--accent-text` | `--surface-3` ground, icon tile `--accent` with `--on-accent` |

Ground of the rail, sidebar and section pane: `--surface` with a 1 px `--border` edge. Icon colour `--muted`, active
`--accent-text`.

**States.**
- Default: label `--muted` (rail) or `--text` (others).
- Hover: `--surface-2` ground, `--text`.
- Focus: 2 px `--focus` ring inside the item (`outline-offset: -2px` in list rows).
- Pressed: `--surface-3`.
- Disabled: never disabled. A section switched off in Features is **dimmed**: icon and label at `--muted`, a hollow
  circle (7.1) after the label in sidebar and list, and a hidden suffix ", switched off". It still opens its page,
  which shows the feature-off empty state (10.1).
- Loading: summaries show a skeleton line until their data arrives; labels and icons are static and never wait.
- Error: a summary whose data failed reads "Not available" in `--muted`; the item still navigates.

**Behaviour and keyboard.** Items are links (`href="#printers"`); Tab moves between them, Enter follows. The active
item has `aria-current="page"`, also when the page shown is a detail inside the section (`#printers/p1`).
**More** collects every item that the current layout hides: the shell lists the items whose `li` is not rendered
(`offsetParent === null`), clones them in order into the More container and marks the current one. With `pills` on
wide screens More opens a menu (4.2) below the button; on phones it opens the More sheet (2.5). When the current
section is in More, the More button shows the active style and its hidden text says ", current: Logs"; with `pills`
its visible label becomes the section's name. With `list` on phones the navigation is the root page: `#` with no
section shows the list full screen; choosing an item drills in; the top bar's Back returns to the list.

**Accessibility.** `nav aria-label="Sections"`; each group a `ul` labelled by its heading (`aria-labelledby`); in the
rail the heading is `sr`. Icons are `aria-hidden`. Summaries are part of the link's name only in `list` (they are
visible there); elsewhere they are hidden with `display:none` so they are not read. The More button has
`aria-haspopup` (`menu` or `dialog`) and `aria-expanded`.

**Theme profiles.** This component **is** the `nav` profile: rail, sidebar, pills and list as in the table. Tablet:
`sidebar` collapses to the rail form (foundations §6); `pills` move to the top bar's second row; `list` shows two
panes (sections and the page). Phones: rail, sidebar and pills become the bottom bar (2.4); `list` becomes the root
page. `collection` and `detail` do not change it.

**Android.** rail: `NavigationRail`. sidebar: `PermanentNavigationDrawer` on expanded width, `NavigationRail` on
medium. pills: `PrimaryScrollableTabRow` under the top app bar with a trailing "More" tab opening a `DropdownMenu`.
list: the list pane of `ListDetailPaneScaffold`, items as `ListItem` with `supportingContent` for the summary.

**HTML.** (Identical in every theme.)
```html
<nav class="nav" aria-label="Sections">
  <h2 class="nav__heading" id="nav-everyday">Everyday</h2>
  <ul class="nav__group" data-group="everyday" aria-labelledby="nav-everyday">
    <li><a class="nav__item" href="#overview" data-tab>
      <svg class="icon nav__icon" aria-hidden="true"><use href="#i-overview"/></svg>
      <span class="nav__label">Overview</span>
      <span class="nav__summary">All checks OK</span>
      <svg class="icon icon--s nav__chevron" aria-hidden="true"><use href="#i-chevron"/></svg>
    </a></li>
    <li><a class="nav__item" href="#printers" data-tab aria-current="page">…Printers…</a></li>
    <li><a class="nav__item" href="#recent" data-tab>…Recently added…</a></li>
    <li><a class="nav__item" href="#devices">…</a></li>
    <li><a class="nav__item" href="#presets" data-state="off">…Slicer presets
      <span class="sr">, switched off</span>…</a></li>
  </ul>
  <h2 class="nav__heading" id="nav-system">System</h2>
  <ul class="nav__group" data-group="system" aria-labelledby="nav-system">
    <li><a class="nav__item" href="#features">…</a></li>
    <li><a class="nav__item" href="#settings" data-tab>…</a></li>
    …
  </ul>
  <button class="nav__more" type="button" aria-haspopup="dialog" aria-expanded="false">
    <svg class="icon nav__icon" aria-hidden="true"><use href="#i-more"/></svg>
    <span class="nav__label">More</span><span class="sr nav__more-current"></span>
  </button>
</nav>
```

### 2.4 Phone bottom bar

**Purpose.** On phones, the four most used sections and More, always under the thumb.

**Anatomy.** It is the navigation (2.3) rendered at phone width: the items marked `data-tab` (Hub page: Overview,
Printers, Recent, Settings; the web app and the app have their own five, see `04-web-app.md` and
`05-android-app.md`) and the More button, in one row of five equal cells. Each cell: icon in a pill-shaped
highlight area, label below. The label of Recently added shortens to "Recent" in the bar: its `nav__label` holds a
full and a short form, and the CSS shows the short form only here.

**Sizes and tokens.** Height `--tab` plus the bottom safe-area inset; `--surface` ground, 1 px `--border` top hairline.
Cells: min height 52 px (`calc(var(--s7) + var(--s1))`), label `--fs-xs` weight 600. Active: `--accent-soft` highlight
behind the icon (`calc(var(--s7) + var(--s3))` wide, `calc(var(--s5) + var(--s2))` tall, radius `--r-l`), label
`--accent-text` weight 650, and the 3 px `--accent-text` mark on the top edge. Fixed to the bottom; `z-index` above the
page, below dialogs.

**States.**
- Default: icon and label `--muted`.
- Hover: (pointer devices) `--text`.
- Focus: 2 px `--focus` ring around the cell.
- Pressed: highlight `--surface-3`.
- Disabled: never; dimmed sections as in 2.3.
- Loading: static; never waits.
- Error: none of its own.

**Behaviour and keyboard.** Same links as the navigation. Pressing the current section's cell again scrolls its page
to the top. While a text field has focus on a phone the bar hides (it would sit on the keyboard) and returns on
blur. More opens the More sheet (2.5).

**Accessibility.** It is the same `nav` landmark, so it is not announced twice. Each cell's name is its full label
("Recently added", not "Recent": the short form is `aria-hidden` and the full label is `sr`). More: "More" plus
", current: <section>" when the current section is in the sheet.

**Theme profiles.** `nav` = rail, sidebar, pills: shown on phones. `nav` = list: not shown; Panes drills in from the
section list (2.3). `collection`, `detail`: no change.

**Android.** `NavigationBar` with `NavigationBarItem` (icon and label always shown).

**HTML.** No separate markup: the CSS at phone width lays out `.nav` as the bar, hides `.nav__heading`,
`.nav__summary`, `.nav__chevron` and every `li` without `data-tab`, and shows `.nav__more`.
```html
<li><a class="nav__item" href="#recent" data-tab>
  <svg class="icon nav__icon" aria-hidden="true"><use href="#i-recent"/></svg>
  <span class="nav__label"><span class="nav__label-full">Recently added</span>
    <span class="nav__label-short" aria-hidden="true">Recent</span></span>
</a></li>
```

### 2.5 More sheet

**Purpose.** On phones, the six sections that do not fit the bottom bar, each with a live one-line summary, one tap
away.

**Anatomy.** A bottom sheet (9.2) titled "More sections", holding a `nav` with two lists, one under the Everyday
heading and one under the System heading (the same `nav__heading` and `nav__group` markup as 2.3); each row is a
hidden section's `nav__item`, cloned from 2.3, with its icon, label, summary and chevron. A Close button in the sheet head.

**Sizes and tokens.** As the bottom sheet. Rows: min height 52 px, padding `0 var(--s3)`, gap `--s3`, `--r`; label
`--fs-b` weight 600; summary `--fs-s` `--muted` on a second line; current row `--accent-soft` with `--accent-text`.

**States.**
- Default: rows on `--surface`.
- Hover: `--surface-2`.
- Focus: 2 px `--focus` ring inside the row.
- Pressed: `--surface-3`.
- Disabled: never; dimmed sections as in 2.3.
- Loading: summary skeleton lines.
- Error: "Not available" summary.

**Behaviour and keyboard.** Opening moves focus to the first row. Choosing a row closes the sheet and navigates;
focus goes to the new page's title (not back to More). Escape, the Close button, the scrim or a downward swipe close
it without navigating, focus back on More.

**Accessibility.** The sheet is a modal `dialog` labelled "More sections"; inside, `nav aria-label="More sections"`.
The current row has `aria-current="page"`.

**Theme profiles.** Exists only where the bottom bar exists (`nav` = rail, sidebar, pills on phones). `collection`,
`detail`: no change.

**Android.** `ModalBottomSheet` with a `Column` of `ListItem`s (`headlineContent` label, `supportingContent` summary,
`leadingContent` icon, `trailingContent` chevron).

**HTML.**
```html
<dialog class="sheet" aria-labelledby="more-title">
  <div class="sheet__head">
    <h2 class="sheet__title" id="more-title">More sections</h2>
    <button class="btn btn--ghost btn--icon" type="button" data-action="close" aria-label="Close">
      <svg class="icon" aria-hidden="true"><use href="#i-close"/></svg></button>
  </div>
  <nav class="sheet__body nav nav--sheet" aria-label="More sections">
    <!-- Everyday and System: nav__heading + nav__group each, holding the hidden nav__items in order -->
  </nav>
</dialog>
```

### 2.6 Page header

**Purpose.** Names the place, states what is true now in one line, and offers the page's one main action
(foundations §1 principle 1).

**Anatomy.** Breadcrumb (only below section level: "Printers / Workshop X1"), page title `h1`, meta line (counts and
status badges, for example "3 printers · Connected 2 · Offline 1"), page actions (at most one primary button, other
buttons default or ghost; a long list goes into an overflow menu).

**Sizes and tokens.** Bottom padding and margin `--s4`, 1 px `--border` hairline under it. Breadcrumb `--fs-s` `--mono`
`--muted`. Title `--fs-xl` weight 650, line height 1.25. Meta `--fs-m` `--muted`, gap `var(--s1) var(--s4)`. Actions
gap `--s2`, aligned to the bottom right on wide screens.

**States.**
- Default: as described.
- Hover: breadcrumb links underline.
- Focus: the title takes focus after navigation without a visible ring (it is not a control); breadcrumb links and
  buttons show the 2 px `--focus` ring.
- Pressed: as buttons.
- Disabled: as buttons (4.1).
- Loading: the meta line shows a skeleton line; the title is static text and never waits.
- Error: when the page's data failed, the meta line is replaced by the error state's one-line summary (10.2).

**Behaviour and keyboard.** On phones the actions move under the title and the primary button stretches to fill the
row. The title wraps (`overflow-wrap: anywhere`), it never truncates.

**Accessibility.** One `h1` per page (foundations §9). Breadcrumb is `nav aria-label="Breadcrumb"` with
`aria-current="page"` on the last part. Meta badges follow 7.1.

**Theme profiles.** `nav` = list: on desktop and tablet the header of each pane is a pane header (title `--fs-l`,
actions at the right) and the page `h1` belongs to the content pane. Others: no change. `collection`, `detail`: no
change.

**Android.** The `TopAppBar` title takes the page title; page actions become a `Button` row at the top of the
content, the main one as `Button`, others `OutlinedButton`, the rest in the bar's overflow `DropdownMenu`.

**HTML.**
```html
<header class="page-head">
  <div class="page-head__text">
    <nav class="page-head__crumbs" aria-label="Breadcrumb">…</nav>
    <h1 class="page-head__title" tabindex="-1">Printers</h1>
    <p class="page-head__meta"><span class="mono">3 printers</span>
      <span class="status status--ok">…Connected 2</span></p>
  </div>
  <div class="page-head__actions">
    <button class="btn" type="button" data-action="find">Find Klipper printers</button>
    <button class="btn btn--primary" type="button" data-action="add">Add a printer</button>
  </div>
</header>
```

---

## 3. Lock and appearance

### 3.1 Lock chip

**Purpose.** Shows on every Hub page whether changes are allowed right now (Locked, Unlocked, Trusted computer) and
is the one place to unlock or lock. Changing something needs the setup code (foundations §1 principle 8); viewing
does not, except the few reads listed in 1.4 ("Reads that need the setup code"), which show a locked placeholder
or a hidden-values note with their own **Unlock to show**.

**Anatomy.** A chip button (`chip chip--lock`): state icon (closed lock, open lock, shield), state word, and on wide
screens a hint separated by a hairline: Locked "Enter setup code", Unlocked "Changes allowed", Trusted computer "No
code needed". The job indicator in the top bar uses the same `chip` block (`chip--job`), and so does the
connection chip of the web app and the Android app (`chip--connection`, below).

**Sizes and tokens.** Height `--ctl`, padding `0 var(--s3)`, gap `--s2`, 1 px border, `--r`,
`--surface` ground, word `--fs-m` weight 600, hint `--fs-m` weight 400 `--muted` with a 1 px `--border` divider and
`--s2` padding. Colours by state:

| `data-state` | Icon | Word | Text and border |
|---|---|---|---|
| `locked` | `i-lock` | Locked | `--text`, `--border-strong` |
| `unlocked` | `i-lock-open` | Unlocked | `--ok`, `--ok` |
| `trusted` | `i-shield` | Trusted computer | `--accent-text`, `--accent-text` |

**States.**
- Default: one of the three `data-state` values above.
- Hover: `--surface-2` ground.
- Focus: 2 px `--focus` ring, 2 px offset.
- Pressed: `--surface-3` ground.
- Disabled: never.
- Loading: until `GET trust` answers, the chip shows the Locked form (the safe assumption) with the hint replaced by
  a skeleton line; it never shows Unlocked before the Hub has said so.
- Error: if `GET trust` fails, the chip stays Locked and works; the unlock dialog then reports the problem.

**Behaviour and keyboard.** Enter or Space opens:
- Locked: the unlock dialog (3.2) with no pending change.
- Unlocked: a small dialog "Unlocked" ("Changes are allowed in this browser until you lock it or close the tab.")
  with Close and **Lock now** (primary). Lock now forgets the code held in memory, sets Locked and shows the toast
  "Locked. Changes need the setup code again."
- Trusted computer: a small dialog "Trusted computer" ("No code is needed in this browser until 2027-02-10.") with a
  link "Trusted computers" (to `#devices/trusted`), Close, and **Stop trusting this computer** (default button;
  calls `POST trust/<id>/revoke`; result: chip Locked, toast "This computer is no longer trusted.").

When any write is refused by the Hub because the code is missing, wrong or no longer valid, the chip returns to
Locked and the unlock dialog opens for that same change. On phones the chip shows the icon and the word only (no
hint).

**Accessibility.** `button` with `aria-haspopup="dialog"`. Its name states the state and what pressing does:
"Locked: enter the setup code", "Unlocked: changes allowed. Lock options", "Trusted computer: no code needed.
Options". A change of state is announced ("Unlocked.", "Locked.").

**Theme profiles.** No change with `nav`, `collection` or `detail`.

**Android.** Not shown: the app is allowed to change things by its pairing. The web app has no lock either. Both
show the connection chip variant below instead.

**HTML.**
```html
<button class="chip chip--lock" type="button" data-state="locked" aria-haspopup="dialog"
        aria-label="Locked: enter the setup code">
  <svg class="icon icon--s" aria-hidden="true"><use href="#i-lock"/></svg>
  <span class="chip__word">Locked</span>
  <span class="chip__hint" aria-hidden="true">Enter setup code</span>
</button>
```

**Variant: connection chip** (`chip chip--connection`). The web app and the Android app have no lock chip; in its
place they show the state of their connection to the Hub with the same chip block (sizes, tokens, focus and pressed
states as above). In the web app it is shown only while the Hub cannot be reached; in the Android app it is shown on
every screen of the main graph with the states of `05-android-app.md` 2.4 (Connected, Offline, Needs a look).

| `data-state` | Leading part | Word | Text and border | Pressing |
|---|---|---|---|---|
| `offline` | `i-wifi-off` (web app) or the hollow-circle `status__shape` (Android) | Offline | `--bad`, `--border-strong` | Web app: checks the Hub again at once (state `connecting`). Android: opens the Hub connection sheet |
| `connecting` | Inline spinner (8.1) | Connecting… | `--muted`, `--border-strong` | Nothing: `aria-disabled="true"` while the check runs; then `offline` again or, on success, the chip hides (web app) or shows Connected (Android) |

Its name states the state and what pressing does: "Offline: try again", "Connecting to the Hub". A change of state is
announced ("Offline.", "Connected."). On Android it is `AssistChip` with a leading status shape, 32 dp tall, hit
area 48 dp.

```html
<button class="chip chip--connection" type="button" data-state="offline" aria-label="Offline: try again">
  <svg class="icon icon--s" aria-hidden="true"><use href="#i-wifi-off"/></svg>
  <span class="chip__word">Offline</span>
</button>
```

### 3.2 Unlock dialog

**Purpose.** Asks for the 8-digit setup code at the moment a change needs it, in place, then carries on with that
change. Offers "Trust this computer" so this browser does not ask again.

**Anatomy.** Dialog (9.1) titled "Enter the setup code" · one sentence that names the pending change ("To forget
Workshop X1, enter the 8-digit setup code. Viewing needs nothing; every change needs the code.") or, opened from the
chip, "Viewing needs nothing. Every change needs the 8-digit setup code." · secret field (5.3) "Setup code" with
hint "Shown when Spoolwarden was installed. At the Hub: `sudo spoolwarden setup-code`." · checkbox (5.8) "Trust this
computer (no code needed here for 90 days)", present only when trusted computers are switched on at the Hub ·
footer: Cancel, and **Unlock** or, with a pending change, **Unlock and continue**.

**Sizes and tokens.** As the dialog. The field is `8rem` wide plus its Show button, `--mono`, `--fs-l` on phones.

**States.**
- Default: field empty and focused; checkbox unchecked.
- Hover: as its parts.
- Focus: as its parts; focus starts in the field.
- Pressed: as its parts.
- Disabled: the primary button is never disabled; pressing it with an empty field shows the error.
- Loading: the primary button shows a spinner and "Checking…" while the code is checked; the field becomes
  read-only.
- Error: inline at the field, each with what to do: empty "Enter the 8-digit setup code."; wrong length "The setup
  code has 8 digits; this has 6. Check it and try again."; refused by the Hub "This is not the setup code. Check it
  at the Hub: `sudo spoolwarden setup-code`."; too many tries: the Hub's own wording; Hub not reachable "Cannot reach the
  Hub. Check that it is on, then try again."

**Behaviour and keyboard.** The field accepts digits with or without a dash or spaces; other characters are dropped
before checking. Enter submits. On success: with the checkbox ticked the page calls `POST trust` with the code and
the chip becomes Trusted computer; otherwise the chip becomes Unlocked and the code is kept in a script variable for
this tab only (never in any storage) and sent with each write as the Hub expects. The dialog closes, a toast says
"Unlocked. Changes are allowed in this browser." (or "Unlocked. This computer is trusted for 90 days."), and the
pending change runs at once. Cancel or Escape drops the pending change and puts back whatever control started it (a
toggle or a segmented choice returns to its previous value). Until the Hub offers a way to check a code on its own
(section 12), opening from the chip checks the code with `POST overview`, a read that needs the code.

**Accessibility.** `aria-describedby` points at the sentence, so the pending change is read when the dialog opens.
Errors are linked to the field and focus returns to it. The result of the pending change is announced by that
change's own result area.

**Theme profiles.** No change; it is a dialog (on phones a bottom sheet, 9.1) in every profile.

**Android.** Not used (see 3.1).

**HTML.**
```html
<dialog class="dialog" aria-labelledby="unlock-title" aria-describedby="unlock-text">
  <form class="dialog__form" method="dialog" novalidate>
    <div class="dialog__head"><h2 class="dialog__title" id="unlock-title">Enter the setup code</h2>…</div>
    <div class="dialog__body">
      <p id="unlock-text">To forget Workshop X1, enter the 8-digit setup code. …</p>
      <div class="field field--secret">…Setup code…</div>
      <label class="check"><input class="check__input" type="checkbox" name="trust">
        <span class="check__label">Trust this computer (no code needed here for 90 days)</span></label>
    </div>
    <div class="dialog__foot">
      <button class="btn" type="button" data-action="cancel">Cancel</button>
      <button class="btn btn--primary" type="submit">Unlock and continue</button>
    </div>
  </form>
</dialog>
```

### 3.3 Appearance control

**Purpose.** Light, Dark or System for this device (foundations §5), always reachable, applied at once.

**Anatomy.** Two forms of one choice:
1. **Segmented** (wide screens, top bar; and the first row of Settings > Appearance on every width): three radio
   segments, each icon plus word: sun "Light", moon "Dark", half-circle "System".
2. **Icon button** (phones, top bar): shows the current choice's icon; opens a menu (4.2) headed "Appearance" with
   the three choices as radio items.

**Sizes and tokens.** Segmented as 5.7: outer 1 px `--border-strong`, `--r`, padding `--s1`; segments height
`calc(var(--ctl) - var(--s2))`, padding `0 var(--s3)`, `--fs-m`; checked segment `--accent-soft` with `--accent-text`
weight 650. Icon button as 4.1 (`btn--ghost btn--icon`).

**States.**
- Default: the stored choice is checked (System when nothing is stored).
- Hover: unchecked segment `--surface-2`, `--text`.
- Focus: 2 px `--focus` ring on the focused segment.
- Pressed: `--surface-3`.
- Disabled: never.
- Loading: none; the stored choice is applied before first paint (foundations §5).
- Error: when storage is blocked, the choice still applies for this visit and the Settings result says "Applied.
  This browser does not keep it after a reload."

**Behaviour and keyboard.** Arrow keys move between segments and select (radio behaviour). Choosing sets or removes
`data-theme` on `html`, writes `spoolwarden.appearance` inside try/catch, updates `meta[name="theme-color"]` to the
computed `--surface`, and syncs every other appearance control on the page. No setup code, no Save, no request to
the Hub. In Settings the group's result area says "Saved on this device: Dark."

**Accessibility.** `fieldset` with `legend` "Appearance" (`sr` in the top bar); each segment a real radio with a
`label`. The icon button's name is "Appearance: System"; the menu items are `menuitemradio` with `aria-checked`.

**Theme profiles.** No change with `nav`, `collection`, `detail`. With `nav` = pills on tablet the segmented form
stays in the first top-bar row.

**Android.** Settings > Appearance: `SingleChoiceSegmentedButtonRow` with three `SegmentedButton`s. Top app bar:
`IconButton` opening a `DropdownMenu` of three `DropdownMenuItem`s with a trailing check on the current one.

**HTML.**
```html
<fieldset class="appearance segmented">
  <legend class="sr">Appearance</legend>
  <input class="segmented__input" type="radio" name="appearance" id="ap-light" value="light">
  <label class="segmented__option" for="ap-light">
    <svg class="icon icon--s" aria-hidden="true"><use href="#i-sun"/></svg>Light</label>
  <input class="segmented__input" type="radio" name="appearance" id="ap-dark" value="dark">
  <label class="segmented__option" for="ap-dark">…Dark</label>
  <input class="segmented__input" type="radio" name="appearance" id="ap-system" value="system" checked>
  <label class="segmented__option" for="ap-system">…System</label>
</fieldset>
<button class="btn btn--ghost btn--icon appearance appearance--menu" type="button"
        aria-haspopup="menu" aria-expanded="false" aria-label="Appearance: System">…</button>
```

### 3.4 Theme picker

**Purpose.** Choose one of the four themes for this device (foundations §6.2), seeing each one before choosing.

**Anatomy.** In Settings > Appearance, under the appearance control: a radio group "Theme" of four tiles. Each tile:
a preview drawing (a miniature of the shell in that theme's own tokens: bar, its navigation form, its collection
form), the theme's name, and its one line (foundations §6.2: "Dense and technical", "Calm cards", "Colourful and
roomy", "Simple lists"). Below the tiles, a form group (5.11) "Theme for new devices" with a select of the four
themes and Save (a Hub setting, so it needs the setup code).

**Sizes and tokens.** Tiles in a grid: four columns on desktop, two on tablet and phone, gap `--s3`. Tile: padding
`--s3`, 1 px `--border-strong`, `--r`; preview area aspect 4:3, `--r-s`; name `--fs-b` weight 650; line `--fs-s`
`--muted`. Checked tile: 2 px `--accent-text` border (1 px border plus 1 px inset), `--accent-soft` ground, check icon
`--accent-text` in the top right. The preview drawing is plain elements styled by tokens: each theme's token blocks
also match `[data-preview="<look>"]`, in light and in both dark selectors, so a tile shows its theme in the current
appearance.

**States.**
- Default: the device's theme is checked (Console when nothing is stored).
- Hover: border `--text`.
- Focus: 2 px `--focus` ring around the tile.
- Pressed: `--surface-2` ground.
- Disabled: a theme that is not built yet (foundations §6.4) is shown with its name, a hollow circle and the line
  "Not available yet"; its radio is disabled.
- Loading: none for the tiles. The stored `spoolwarden.look` is applied before first paint by the same small head
  script that applies the appearance (foundations §5): it sets `data-look` on `html` before the stylesheet paints, so
  a device set to Panes never draws Console first and re-lays out (foundations §12 rule 7). The "Theme for new devices" select shows a skeleton until `GET state` answers.
- Error: storage blocked: applies for this visit with the same message as 3.3. Save of "Theme for new devices"
  fails: the group's result area shows the error.

**Behaviour and keyboard.** Arrow keys move and select. Choosing sets `data-look` on `html`, writes
`spoolwarden.look` (try/catch), and re-lays out the page at once: no reload, no Save. Focus stays on the chosen tile
even when the layout around it changes. Result area: "Theme: Spool. Saved on this device." The same group exists in
the web app's settings sheet.

**Accessibility.** `fieldset` with `legend` "Theme"; each tile is a `label` wrapping a radio input; the preview is
`aria-hidden`; the line is linked with `aria-describedby`. The change is announced through the result area.

**Theme profiles.** No change. The previews themselves show each theme's `nav` and `collection` forms.

**Android.** `Column(Modifier.selectableGroup())` of `Card`s with `Modifier.selectable(role = Role.RadioButton)`,
each holding a drawn preview (`Canvas` in that theme's `ColorScheme`), a `RadioButton`, name and line. Grid on medium
and expanded widths.

**HTML.**
```html
<fieldset class="theme-picker">
  <legend class="theme-picker__legend">Theme</legend>
  <label class="theme-picker__tile">
    <input class="theme-picker__input" type="radio" name="look" value="console" checked
           aria-describedby="look-console-line">
    <span class="theme-picker__preview" data-preview="console" aria-hidden="true">
      <span class="theme-picker__bar"></span><span class="theme-picker__nav"></span>
      <span class="theme-picker__rows"></span></span>
    <span class="theme-picker__name">Console</span>
    <span class="theme-picker__line" id="look-console-line">Dense and technical</span>
  </label>
  …Workbench, Spool, Panes…
</fieldset>
```

---

## 4. Actions

### 4.1 Buttons and the one-main-action rule

**Purpose.** Start an action. Their look tells how important and how risky the action is.

**Anatomy.** Optional leading icon (`icon--s`), label (a verb and its object: "Forget printer", "Save storage
locations", "Test connection"), a spinner in place of the icon while loading. Variants:

| Variant | Use | Look |
|---|---|---|
| `btn--primary` | The one main action of a thing | `--accent` ground and border, `--on-accent` text |
| `btn` (default) | Other common actions | `--surface` ground, 1 px `--border-strong`, `--text` |
| `btn--ghost` | Quiet actions: lists of "Change" actions, Cancel inside rows, icon buttons in bars | Transparent, no border, `--text` |
| `btn--danger` | Destructive actions where they are offered | Transparent, 1 px `--bad` border, `--bad` text |
| `btn--danger btn--solid` | Only the confirming button inside a destructive dialog | `--bad` ground, `--on-bad` text |
| `btn--icon` (combines with the above) | Icon-only actions: close, more, expand, previous, next | Square, width = height |

**The one-main-action rule.** Each of these has **at most one** `btn--primary`: a page header, a collection item's
visible actions, a detail region, a form group, a dialog or sheet footer, an empty state, a banner. All other
actions are default or ghost; when a thing has more than three secondary actions, the rest go into an overflow menu
(4.2). Destructive actions are never primary-styled outside their confirming dialog, are placed last and apart
(after a separator in menus; in a "Remove" zone with a hairline above it in detail regions) and always ask first
(9.1). In a row of buttons the primary is last (rightmost) on wide screens; in dialog footers the order is Cancel
then the confirming button. On phones, footer buttons share the row equally in the same order; a page header's
primary takes the full width.

**Sizes and tokens.** Min height `--ctl` (40 px wide, 44 px phones); padding `0 var(--s4)`; gap `--s2`; `--fs-m`
weight 600, line height 1.2; `--r`; no shadow. Icon button width `--ctl`. Transition of ground, border and colour
over `--t-fast`. Every button also has an `::after` hit area reaching 44 px.

**States.**
- Default: as in the table.
- Hover: default and ghost `--surface-2`; primary `--accent-hover` ground and border; danger `--bad-soft` ground.
- Focus: 2 px `--focus` ring, 2 px offset.
- Pressed: default and ghost `--surface-3`; primary `--accent-hover`; danger `--bad-soft`.
- Disabled: `aria-disabled="true"` (stays focusable), ground `--surface-2`, text `--muted`, border `--border`,
  cursor `not-allowed`; a disabled button **always** has its reason visible next to it and linked by
  `aria-describedby` ("Check the spools first: any edit needs a new check."). Native `disabled` is used only where
  the reason is the current step of the dialog it sits in.
- Loading: `aria-busy="true"` and `aria-disabled="true"`; the icon becomes a spinner (8.1); the label becomes the
  progress form of its verb ("Testing…", "Saving…", "Checking…"); the button keeps the width it had (the script
  sets `--btn-min` from its measured width) so nothing moves.
- Error: buttons have no error look; the outcome shows in the result area next to them (8.6) and the button returns
  to default.

**Behaviour and keyboard.** Enter and Space press. A second press while loading does nothing. Buttons that open
something have `aria-haspopup` and `aria-expanded`. A button that submits a form is `type="submit"`; all others
`type="button"`. Writes pass the lock (1.4).

**Accessibility.** Real `button` elements (or `a` for navigation only). Icon buttons have `aria-label` and a tooltip
(4.3) with the same words. When several identical buttons are on a page, the accessible name names the thing ("Test
connection to Workshop X1"), even when the visible label is shorter ("Test" on tablets).

**Theme profiles.** No change with `nav`, `collection`, `detail`; shape and size come from the theme's tokens.

**Android.** `btn--primary` `Button`; default `OutlinedButton`; ghost `TextButton`; danger `OutlinedButton` with
`colorScheme.error` content and border; solid danger `Button` with `ButtonDefaults.buttonColors(containerColor =
error)`; icon `IconButton` (ghost) or `OutlinedIconButton`. Minimum touch target 48 dp.

**HTML.**
```html
<div class="actions">
  <button class="btn" type="button" data-action="test" aria-label="Test connection to Workshop X1">
    <svg class="icon icon--s" aria-hidden="true"><use href="#i-refresh"/></svg>Test connection</button>
  <button class="btn btn--primary" type="button" data-action="map">Map slots</button>
</div>
<button class="btn btn--primary" type="button" aria-busy="true" aria-disabled="true">
  <span class="spinner" aria-hidden="true"></span>Saving…</button>
<button class="btn btn--danger" type="button" data-action="forget">Forget printer</button>
```

### 4.2 Overflow menu

**Purpose.** Holds the secondary actions of a thing so that its surface shows only the main ones.

**Anatomy.** A trigger (`btn btn--icon` with the "more" icon, or a labelled button such as "More") and a popup:
optional headings, items (icon, label, optional second line, optional check for radio items), separators.
Destructive items come last, after a separator, in `--bad`.

**Sizes and tokens.** Popup `--surface`, 1 px `--border-strong`, `--r`, `--e2`, padding `--s1`, width
`min(20rem, 100vw - 2 * var(--s4))`, min width 14rem, max height the viewport minus `--s4`, scrolls inside. Item min
height 44 px, padding `0 var(--s3)`, gap `--s2`, `--fs-m`, `--r-s`. Heading `--fs-xs` weight 650
`--muted`. Separator 1 px `--border` with `--s1` margin. Appears over `--t`.

**States.**
- Default: closed; trigger `aria-expanded="false"`.
- Hover: item `--surface-2`.
- Focus: the focused item has `--surface-2` and, when focused by keyboard, a 2 px inset `--focus` ring.
- Pressed: `--surface-3`.
- Disabled: item stays listed with `aria-disabled="true"`, `--muted`, and its reason as the second line ("Available
  when the printer is idle.").
- Loading: items never load; an item that starts a long action closes the menu, and the action's result appears at
  the row of the trigger.
- Error: none of its own.

**Behaviour and keyboard.** Enter, Space or Arrow Down on the trigger opens and focuses the first enabled item; Arrow
Up opens on the last. Arrow keys move (wrapping), Home and End jump, typing a letter moves to the next item starting
with it, Enter or Space activates, Escape closes and returns focus to the trigger, Tab closes and moves on. A click
outside closes it. Position: below the trigger, right edges aligned, flipped above when there is no room; it never
leaves the viewport. On phones a menu with more than four items opens as a bottom sheet (9.2) with the same items in
44 px rows.

**Accessibility.** Trigger `aria-haspopup="menu"`, `aria-expanded`, `aria-controls`, name "More actions for Workshop
X1". Popup `role="menu"` with `aria-label`; items `role="menuitem"` (or `menuitemradio` with `aria-checked`);
headings `role="presentation"`; separators `role="separator"`. Items are buttons with `tabindex="-1"` (roving focus).

**Theme profiles.** `collection` = rows: rows show no trigger on their face; the menu lives in the detail region's
header. Other `collection` values, and `nav` and `detail`: no change.

**Android.** `IconButton` (more icon) with `DropdownMenu` and `DropdownMenuItem` (`leadingIcon`, `enabled`, error
colour for destructive items); `HorizontalDivider` as separator; long menus on compact width as `ModalBottomSheet`.

**HTML.**
```html
<button class="btn btn--icon" type="button" aria-haspopup="menu" aria-expanded="false"
        aria-controls="menu-p1" aria-label="More actions for Workshop X1">
  <svg class="icon" aria-hidden="true"><use href="#i-more"/></svg></button>
<div class="menu" id="menu-p1" role="menu" aria-label="Actions for Workshop X1" hidden>
  <button class="menu__item" type="button" role="menuitem" tabindex="-1" data-action="rename">
    <svg class="icon icon--s" aria-hidden="true"><use href="#i-pencil"/></svg>Rename</button>
  <div class="menu__separator" role="separator"></div>
  <button class="menu__item menu__item--danger" type="button" role="menuitem" tabindex="-1"
          data-action="forget">…Forget printer</button>
</div>
```

### 4.3 Tooltip

**Purpose.** Names icon-only buttons, shows the exact time behind a relative date ("3 minutes ago" for
2026-11-12 14:05), and the full text of something shortened. Never the only place for information a person needs to
act.

**Anatomy.** A small floating label with one line of text (at most two), no controls inside.

**Sizes and tokens.** `--text` ground with `--surface` text (inverse), `--fs-s`, padding `var(--s1) var(--s2)`,
`--r-s`, `--e0` (the inverse ground sets it apart; foundations §4.3 keeps `--e2` for dialogs, sheets, menus and
toasts), max width 20rem. Offset `--s1` from its target. Appears over `--t-fast`.

**States.**
- Default: hidden.
- Hover: shown 500 ms after the pointer rests on the target; hidden when it leaves (with 100 ms grace so the pointer
  can cross onto the tooltip).
- Focus: shown at once while the target has keyboard focus.
- Pressed: hidden when the target is pressed.
- Disabled: disabled targets (`aria-disabled`) still show their tooltip, which may give the reason.
- Loading: not applicable.
- Error: not applicable.

**Behaviour and keyboard.** Escape hides it without moving focus. On touch screens a long press on the target shows
it for 3 s (relative dates, icon buttons); a short tap does the button's action. Placed above the target, flipped
below near the top edge; never covers the target.

**Accessibility.** `role="tooltip"` with an id. For an icon button the tooltip repeats the button's `aria-label` and
is `aria-hidden` (so the name is not read twice). For a relative date the date is a `time` element with `datetime`
and the exact time is linked with `aria-describedby`.

**Theme profiles.** No change.

**Android.** `TooltipBox` with `PlainTooltip` (long press), and `contentDescription` on the icon.

**HTML.**
```html
<button class="btn btn--ghost btn--icon" type="button" aria-label="Close">…</button>
<span class="tooltip" role="tooltip" id="tip-1" aria-hidden="true" hidden>Close</span>
<time class="mono" datetime="2026-11-12T14:05" aria-describedby="tip-2">3 minutes ago</time>
<span class="tooltip" role="tooltip" id="tip-2" hidden>2026-11-12 14:05</span>
```

---

## 5. Fields and forms

### 5.1 Field (rules shared by every field type)

**Purpose.** Let a person enter or choose one value, with its label always visible, its hint at hand and its error
said in place. Sections 5.2 to 5.10 add what each type needs on top of this.

**Anatomy.** Wrapper `field` · label (`field__label`), with " (optional)" (`field__optional`) when the field is
optional · the control · unit or inline button where the type has one · hint (`field__hint`) · error
(`field__error`, hidden until needed: octagon shape plus text). Two layouts: **stacked** (label above control, the
default and the only layout on phones) and **row** (`field--row`: label in a 200 px left column on wide screens,
used in Settings).

**Rules for every field.**

| Rule | What it means |
|---|---|
| Label | Always a visible `label` (or `legend` for groups). A placeholder is an example ("e.g. 192.0.2.40 or printer.local"), never the label. |
| Required and optional | Every field is required unless its label ends in "(optional)". No asterisks, no "required" word. A form whose fields are all optional says so once in its description. The same rule holds in the web app and the Android app. |
| Hint | One short sentence under the control: where to find the value, its format, or its effect ("On the printer: Settings > Network/LAN"; "Changing this restarts the Hub."). |
| Error | Says what is wrong and what to do ("Enter the printer's address."; "Use at least 12 characters. This one has 9."). Never only "Invalid". |
| When checked | On submit or Save. After a field has shown an error it is checked again on every input and the error clears as soon as the value is good. Nothing is flagged while a person is still typing a value for the first time. |
| Errors from the Hub | An error the Hub ties to a field is shown at that field; anything else goes to the form's result area (8.6). Edits are always kept. |
| Several errors | Focus moves to the first field in error. A form with more than six fields and two or more errors also shows an error summary at its top: "2 fields need a look:" followed by links to them. |
| Never lose input | Refreshing data never replaces a field that has focus or holds an edited value (foundations §1 principle 4). |

**Sizes and tokens.** Label `--fs-m` weight 600 `--text`, `--s1` below. Control min height `--ctl`, padding
`0 var(--s3)`, 1 px `--border-strong`, `--r`, `--surface` ground, `--text`, text `--fs-b` (`--fs-l` on phones so
iPhone Safari does not zoom; this holds for monospace values too). Monospace values (`mono`) `--fs-m` on wide
screens. Placeholder `--muted`. Hint `--fs-m` `--muted`, `--s1` above (it can carry the reason a control is
disabled, so it is never smaller: foundations §4.2). Error `--fs-m` weight 600 `--bad` with the octagon shape (7.1),
`--s1` above. Widths: text fields `min(100%, 30rem)`, short values (port,
code) 8rem; on phones 100 %. Row layout: grid `calc(var(--s7) * 4 + var(--s2)) minmax(0, 1fr)` (200 px label
column), gap `var(--s1) var(--s4)`, rows separated by
1 px `--border` and padded `--s3` top and bottom.

**States.**
- Default: as above.
- Hover: border `--text`.
- Focus: 2 px `--focus` outline at 0 offset, border `--focus`.
- Pressed: not applicable to text controls (see each type for buttons inside fields).
- Disabled: ground `--surface-2`, text `--muted`, border `--border`, the reason in the hint. Values that can never be
  changed are not disabled fields: they are shown as a key-value list (6.3).
- Loading: before the value arrives, the control shows a skeleton line (10.3) and `aria-busy="true"`; when a value is
  checked by the Hub (for example a Spoolman address that must answer), a spinner sits at the control's end and the
  hint reads "Checking…".
- Error: `aria-invalid="true"`, border `--bad` plus a 1 px inset `--bad` (2 px in all, so it is not colour alone),
  error text shown.

**Behaviour and keyboard.** Standard for each native control. Enter in a single-line field submits its form (or
presses the group's Save). Fields never auto-submit on blur.

**Accessibility.** `label for` the control; `aria-describedby` lists the hint id, the unit id and the error id (the
error is in the list even while hidden, so it is read once shown); `aria-invalid` when in error. Grouped controls
(radios, segments, checkbox lists) use `fieldset` and `legend`. An error summary is a `role="alert"` region whose
links move focus to the fields.

**Theme profiles.** No change with `nav`, `collection`, `detail`. Spool's larger type and control height come from
its tokens.

**Android.** `OutlinedTextField` with `label`, `supportingText` (hint or error), `isError`, `singleLine`; optional
marked in the label text "(optional)"; error summary as a `Card` with `errorContainer` at the top of the form.

**HTML.**
```html
<div class="field">
  <label class="field__label" for="printer-name">Name <span class="field__optional">(optional)</span></label>
  <input class="field__control" id="printer-name" name="name" type="text" autocomplete="off"
         aria-describedby="printer-name-hint printer-name-error">
  <p class="field__hint" id="printer-name-hint">Shown in lists. Empty uses the printer's own name.</p>
  <p class="field__error" id="printer-name-error" hidden></p>
</div>
```

### 5.2 Text field

**Purpose.** One line of free text: a name, an address, a subnet, a location.

**Anatomy.** As 5.1, with an `input type="text"` (or `type="search"` for the search field of a collection, 6.1).

**Sizes and tokens.** As 5.1. Addresses, ports, serials and codes use `mono`.

**States.**
- Default, hover, focus, disabled, error: as 5.1.
- Pressed: not applicable.
- Loading: as 5.1; a search field shows a spinner at its end while results load.

**Behaviour and keyboard.** Addresses and serials have `autocapitalize="none"`, `spellcheck="false"` and
`autocomplete="off"`; serials `autocapitalize="characters"`. Leading and trailing spaces are dropped on save. A list
of known values (vendors, storage locations) is offered with a `datalist`; the person may still type a new value. A
search field searches 300 ms after typing stops (at least two characters), shows its result count, and has no
separate Search button; Enter searches at once; Escape clears it.

**Accessibility.** As 5.1. A search field has `role="search"` on its wrapper and announces the count ("4 spools
found") through the collection's result area.

**Theme profiles.** No change.

**Android.** `OutlinedTextField(singleLine = true)` with `KeyboardOptions(capitalization, autoCorrect = false,
keyboardType = Uri or Ascii)`; known values with `ExposedDropdownMenuBox`; search with `SearchBar` or a text field
with `ImeAction.Search`.

**HTML.**
```html
<div class="field">
  <label class="field__label" for="add-address">IP address or name</label>
  <input class="field__control mono" id="add-address" type="text" autocapitalize="none" spellcheck="false"
         autocomplete="off" placeholder="e.g. 192.0.2.40 or printer.local"
         aria-describedby="add-address-error">
  <p class="field__error" id="add-address-error" hidden></p>
</div>
```

### 5.3 Secret field

**Purpose.** Typing a secret (Access Code, setup code, Moonraker API key, Anthropic API key, web passphrase, the
Catalog token) without showing it by default, and showing the state of a secret that is already saved without ever showing
its value.

**Anatomy.** Two forms:
1. **Entry**: as 5.1 with `input type="password"` and a **Show** text button inside the control's end. Show turns the
   input to `type="text"` and the button to **Hide**.
2. **Saved secret** (a key row): a status badge "Set" or "Not set" (7.1), the words "Saved (hidden)" when set, and
   the actions **Replace** (or **Set**), **Remove** (danger, asks first) and, where the Hub offers it, **Check**.
   Replace opens the entry form in place with **Save key** (primary) and **Cancel** (ghost).

**Sizes and tokens.** As 5.1; the Show button is `btn--ghost` at `calc(var(--ctl) - var(--s2))` height inside the control's
right padding (the control's right padding grows by its width). The key row: min height `--ctl`, gap
`var(--s2) var(--s3)`, wraps on phones.

**States.**
- Default: entry empty, hidden; key row shows the saved state.
- Hover: as 5.1; Show button `--surface-2`.
- Focus: as 5.1; Show button has its own ring.
- Pressed: Show button `--surface-3`; `aria-pressed="true"` while the value is shown.
- Disabled: as 5.1.
- Loading: Save key or Check shows its spinner (4.1); the entry becomes read-only.
- Error: as 5.1 ("Paste the new key first. It starts with sk-ant-."; "The two passphrases do not match." on the
  second field of a pair).

**Behaviour and keyboard.** Never prefilled, never sent back by the Hub, cleared from the input after a successful
save. `autocomplete="new-password"` for passphrases (so password managers can offer one), `off` for codes and keys.
Paste is allowed. Shown values return to hidden when the field loses focus or the form is saved. A passphrase pair
checks its length on the first field and the match on the second.

**Accessibility.** The Show button's name includes the field ("Show Access Code"), `aria-pressed` tells its state,
and `aria-controls` points at the input. Saving announces "Access Code replaced." through the result area, never the
value.

**Theme profiles.** No change.

**Android.** `OutlinedTextField` with `visualTransformation = PasswordVisualTransformation()` toggled by a trailing
`TextButton` "Show"/"Hide"; `KeyboardOptions(keyboardType = KeyboardType.Password)` (`NumberPassword` for codes).
Saved-secret row as a `ListItem` with the badge and `TextButton`s.

**HTML.**
```html
<div class="field field--secret">
  <label class="field__label" for="access-code">Access Code</label>
  <div class="field__box">
    <input class="field__control mono" id="access-code" type="password" autocomplete="off"
           aria-describedby="access-code-hint access-code-error">
    <button class="btn btn--ghost field__action" type="button" aria-controls="access-code"
            aria-pressed="false" aria-label="Show Access Code">Show</button>
  </div>
  <p class="field__hint" id="access-code-hint">On the printer: Settings > Network/LAN</p>
  <p class="field__error" id="access-code-error" hidden></p>
</div>
<div class="key-row">
  <span class="status status--ok">…Set</span><span class="muted">Saved (hidden)</span>
  <div class="actions"><button class="btn" type="button" data-action="check">Check</button>
    <button class="btn" type="button" data-action="replace">Replace</button>
    <button class="btn btn--danger" type="button" data-action="remove">Remove</button></div>
</div>
```

### 5.4 Number field with unit

**Purpose.** A number with its unit: grams, degrees, days, reads per day, port, boxes.

**Anatomy.** As 5.1, with a text input set up for numbers and the unit (`field__unit`) shown inside the control's
end ("g", "°C", "g/cm³", "days", "%").

**Sizes and tokens.** As 5.1; width 8rem plus the unit; value `mono` with `tabular-nums`; unit `--fs-s` `--mono`
`--muted`.

**States.**
- Default, hover, focus, disabled: as 5.1.
- Pressed: not applicable.
- Loading: as 5.1.
- Error: as 5.1, with errors that state the rule: "Enter a whole number, e.g. 2."; "Enter a number from 1 to 365.";
  "Enter grams above 0, or leave this empty."

**Behaviour and keyboard.** `type="text"` with `inputmode="numeric"` (whole numbers) or `"decimal"`, so the mouse
wheel and arrow keys never change a value by accident; a comma is read as a decimal point. Ranges are shown in the
hint when they are not obvious ("1 to 365"). Empty is allowed only for optional fields. Values are sent as numbers.

**Accessibility.** The unit has an id listed in `aria-describedby`, so "Net weight, edit text, g" is read.

**Theme profiles.** No change.

**Android.** `OutlinedTextField` with `suffix = { Text("g") }` and `KeyboardOptions(keyboardType =
KeyboardType.Number or Decimal)`.

**HTML.**
```html
<div class="field field--number">
  <label class="field__label" for="keep-days">Keep nightly backups for</label>
  <div class="field__box">
    <input class="field__control mono" id="keep-days" type="text" inputmode="numeric"
           aria-describedby="keep-days-unit keep-days-hint keep-days-error">
    <span class="field__unit" id="keep-days-unit">days</span>
  </div>
  <p class="field__hint" id="keep-days-hint">1 to 365. Backups made here are kept until you delete them.</p>
  <p class="field__error" id="keep-days-error" hidden></p>
</div>
```

### 5.5 Select

**Purpose.** Choose one value from a known list of more than four (a printer type with many options, a log service,
a slicer parent, a storage location, the theme for new devices). Up to four options use a segmented choice (5.7).

**Anatomy.** As 5.1, with a native `select` drawn without the browser's arrow (`appearance: none`) and a chevron icon
at its end. When the Hub offers an automatic choice, it is the first option and says what it will do: "Automatic:
Shelf A (PLA rack)".

**Sizes and tokens.** As 5.1; right padding `calc(var(--s3) + var(--s4) + var(--s2))` for the chevron; chevron
`icon--s` `--muted`, not clickable (`pointer-events: none`).

**States.**
- Default, hover, focus, disabled, error: as 5.1.
- Pressed: the native list opens.
- Loading: while options load: a skeleton line and `aria-busy`; when options failed to load: the error "Could not
  load the list." with a **Try again** button in the hint line.

**Behaviour and keyboard.** Native. A select inside a form group is part of its dirty state; a select outside one
applies when its value changes (with the lock and a result, like a toggle).

**Accessibility.** Native semantics. The chevron is `aria-hidden`.

**Theme profiles.** No change.

**Android.** `ExposedDropdownMenuBox` with a read-only `OutlinedTextField` and `ExposedDropdownMenu`.

**HTML.**
```html
<div class="field field--select">
  <label class="field__label" for="log-service">Service</label>
  <div class="field__box">
    <select class="field__control" id="log-service">…</select>
    <svg class="icon icon--s field__chevron" aria-hidden="true"><use href="#i-chevron"/></svg>
  </div>
</div>
```

### 5.6 Toggle (switch)

**Purpose.** Switch something on or off **at once**, with no Save: "Follow nightly builds", "Trusted computers",
"Notify this phone" (in the web app's group "Print alerts on this phone").

**Anatomy.** A switch (track and thumb), its label, and the state word "On" or "Off" after it. A hint and a result
area below.

**Rule.** A toggle applies the moment it changes. It is never placed inside a form group that has a Save button;
there the same choice is a checkbox (5.8). When switching has a consequence worth reading first (nightly builds are
untested), the change opens a confirm dialog (9.1) before anything is sent.

**Toggles that guard security** (the Android app's "Check the fingerprint when pairing by address", on by default)
are never placed among routine options or at the bottom of a task screen. They sit last in their screen or group,
under a small heading "Security", with a hint at `--fs-m` (never smaller, 5.1) that says the risk of the less safe
position in full ("When this is off, the app trusts the certificate a Hub presents when you pair by typing its
address. A scanned QR code is always checked."). Such a switch is worded so that **On is the safe position** and Off
lowers security. Turning it off opens a destructive dialog (9.1) naming the risk ("Skip the fingerprint check?" /
"Only do this on a network you trust." / Cancel / **Skip the check**); while it is off, the row shows the Needs a look
badge (7.1) beside the state word. Turning it back on asks nothing.

**Sizes and tokens.** Track `calc(var(--s6) + var(--s2))` by `--s5` (40 by 24 px), radius half its height, 1 px
`--border-strong`, `--surface-3` ground; thumb `--s4`, `--muted`. On: track `--accent-text` with border `--accent-text`, thumb
`--surface`, moved by `--s4` over `--t-fast`. State word `--fs-s` `--mono`, `--muted` (Off) or `--accent-text`
(On). The row is at least 44 px high and the label is part of the hit area.

**States.**
- Default: Off or On as the Hub reports.
- Hover: track border `--text`.
- Focus: 2 px `--focus` ring around the track.
- Pressed: thumb grows to `calc(var(--s4) + var(--s1) / 2)` (18 px).
- Disabled: track `--surface-2`, border `--border`, label `--muted`, reason in the hint.
- Loading: after a change, the switch shows its new position with `aria-busy="true"` and is not operable until the
  Hub answers; the result area says "Saving…".
- Error: the switch returns to its previous position and the result area says what failed ("Not changed: the Hub did
  not answer. Try again."). Cancelling the unlock dialog or the confirm dialog also returns it.

**Behaviour and keyboard.** Space toggles (Enter too). The change passes the lock (1.4). Success writes a result
naming the consequence ("On: each new nightly build is installed after the current one.").

**Accessibility.** `input type="checkbox" role="switch"` with its `label`; the state word is `aria-hidden` (the
switch's checked state is read); the result area is `role="status"`.

**Theme profiles.** No change.

**Android.** `Switch` in a `Row(Modifier.toggleable(role = Role.Switch))` so the whole row toggles.

**HTML.**
```html
<div class="toggle">
  <label class="toggle__row">
    <input class="toggle__input" type="checkbox" role="switch" aria-describedby="nightly-hint">
    <span class="toggle__label">Follow nightly builds</span>
    <span class="toggle__word" aria-hidden="true"></span>
  </label>
  <p class="toggle__hint" id="nightly-hint">Nightly builds are untested and unsigned.</p>
  <p class="result" role="status"></p>
</div>
```

### 5.7 Segmented choice

**Purpose.** Pick one of two to four short options, all visible at once: printer type (Bambu Lab / Klipper), lane
data (Auto / On / Off), Appearance, a collection filter (All / To check). A variant with descriptions,
`segmented--cards`, is used when each option needs a line of explanation (Weigh Station voice: "Piper" with
"Natural. A 60 to 80 MB download." / "espeak-ng" with "Robotic. No download.").

**Anatomy.** A `fieldset` of radio inputs, each with a label drawn as a segment (icon optional, word, optional count
in `mono`). The cards variant draws each option as a card with the radio, a bold name and a muted line.

**Sizes and tokens.** Outer 1 px `--border-strong`, `--r`, padding `--s1`, gap `--s1`; segment min height
`calc(var(--ctl) - var(--s2))` with a hit area reaching 44 px, padding `0 var(--s3)`, `--fs-m`, `--muted`; checked
`--accent-soft` ground, `--accent-text`, weight 650. `segmented--wide` stretches segments to equal widths. Cards
variant: grid of two columns (one on phones), gap `--s2`, card padding `--s3`, 1 px `--border-strong`, `--r`;
checked card `--accent-soft` with a 1 px inset `--accent-text`.

**States.**
- Default: one option checked.
- Hover: unchecked option `--surface-2`, `--text`.
- Focus: 2 px `--focus` ring on the focused option.
- Pressed: `--surface-3`.
- Disabled: a single option can be disabled (`--muted`, reason in the hint); the group can be disabled as a whole.
- Loading: when the choice applies at once, the newly checked option shows `aria-busy` and a spinner in place of its
  icon until the Hub answers.
- Error: inside a form: as 5.1 on the group. Applied at once: the previous option is checked again and the result
  area says what failed.

**Behaviour and keyboard.** Tab enters the group at the checked option; arrow keys move and check. Inside a form
group it is part of the dirty state. Outside one it applies at once, passing the lock, like a toggle.

**Accessibility.** `fieldset` with a `legend` (visible or `sr`), real radios. Counts in labels are read ("To check,
2").

**Theme profiles.** No change.

**Android.** `SingleChoiceSegmentedButtonRow`; the cards variant as a `Column(Modifier.selectableGroup())` of
`Card`s with `RadioButton`s.

**HTML.**
```html
<fieldset class="segmented segmented--wide">
  <legend class="field__label">Printer type</legend>
  <input class="segmented__input" type="radio" name="kind" id="kind-bambu" value="bambu" checked>
  <label class="segmented__option" for="kind-bambu">Bambu Lab</label>
  <input class="segmented__input" type="radio" name="kind" id="kind-klipper" value="klipper">
  <label class="segmented__option" for="kind-klipper">Klipper</label>
</fieldset>
```

### 5.8 Checkbox

**Purpose.** A yes or no inside a form ("Still sealed (in its bag or box)", "Trust this computer"), the
selection of collection items, and on/off settings that are saved with a group's Save.

**Anatomy.** Native checkbox, label text, optional second line (`check__desc`).

**Sizes and tokens.** Box `calc(var(--s4) + var(--s1) / 2)` (18 px), `accent-color: var(--accent-text)`; row min height
44 px, gap `--s2`, `--fs-m`; description `--fs-s` `--muted`. The whole row is the hit area.

**States.**
- Default: unchecked or checked.
- Hover: label `--text`, box border `--text`.
- Focus: 2 px `--focus` ring around the box.
- Pressed: native.
- Disabled: `--muted` label, reason in the description.
- Loading: not applicable (checkboxes are saved with their form).
- Error: as 5.1 ("Tick this to go on" style errors are avoided: a required yes is a button, not a checkbox).

**Behaviour and keyboard.** Space toggles. Clicking anywhere on the label row toggles (never only the box). The
select-all checkbox of a collection can be mixed (`indeterminate`).

**Accessibility.** `label` wraps the input; description linked by `aria-describedby`; mixed state is read as
"mixed".

**Theme profiles.** No change.

**Android.** `Checkbox` in a `Row(Modifier.toggleable(role = Role.Checkbox))`; `TriStateCheckbox` for select-all.

**HTML.**
```html
<label class="check">
  <input class="check__input" type="checkbox" name="sealed" aria-describedby="sealed-desc">
  <span class="check__label">Still sealed (in its bag or box)</span>
  <span class="check__desc" id="sealed-desc">A sealed spool is stored as full.</span>
</label>
```

### 5.9 File field

**Purpose.** Choose a file from the device: a backup zip to restore, label photos in the web app.

**Anatomy.** As 5.1, with a native `input type="file"` whose button (`::file-selector-button`) looks like a default
button ("Choose a zip", "Take or choose photos"). After choosing: the file name and size in `mono` in the hint line.
On wide screens the field is also a drop zone. The photos variant (`field--photos`) shows the chosen photos as
thumbnails (7.6) with a Remove button on each and a count "Photos: 2 of 8".

**Sizes and tokens.** As 5.1; selector button as `btn` (4.1). Drop zone: 1 px dashed `--border-strong`, `--r`,
padding `--s4`; while a file is dragged over it `--accent-soft` ground and `--accent-text` border. Thumbnails 96 px
(`calc(var(--s7) * 2)`) in a wrapping grid, gap `--s2`; their Remove buttons are 44 px.

**States.**
- Default: "No file chosen" in the hint.
- Hover: selector button `--surface-2`.
- Focus: 2 px `--focus` ring on the input.
- Pressed: selector button `--surface-3`.
- Disabled: as 5.1.
- Loading: while uploading, a determinate bar (8.3) under the field with "Uploading… 42 %"; photos being prepared
  (resized on the device) show a skeleton thumbnail.
- Error: as 5.1: "This is not a zip file. Choose the backup zip."; "The file is larger than the Hub takes. Copy it to
  the Hub and run: `sudo spoolwarden restore <file>`."; "8 photos at a time."; "<file name>: this image cannot be read."

**Behaviour and keyboard.** `accept` limits the types (`.zip,application/zip`; `image/*`). Choosing a new file
replaces the old one (single) or adds (photos, up to the limit). A photo's Remove keeps focus on the next photo's
Remove, or on the selector when none is left.

**Accessibility.** The native input keeps its own semantics; its label names what to choose. The chosen file is in
the hint, linked by `aria-describedby`. Each thumbnail has alt "Photo 1 of 2" and its Remove "Remove photo 1".

**Theme profiles.** No change.

**Android.** `rememberLauncherForActivityResult(GetContent())` or the photo picker (`PickMultipleVisualMedia`) from a
`Button`; the camera capture of the app is its own screen (`05-android-app.md`).

**HTML.**
```html
<div class="field field--file">
  <label class="field__label" for="restore-file">Backup zip</label>
  <input class="field__control" id="restore-file" type="file" accept=".zip,application/zip"
         aria-describedby="restore-file-hint restore-file-error">
  <p class="field__hint mono" id="restore-file-hint">No file chosen</p>
  <p class="field__error" id="restore-file-error" hidden></p>
</div>
```

### 5.10 Text area

**Purpose.** Several lines of text: a note for the Label Reader ("e.g. 3 of the grey ones"), "What is wrong?" when
asking the Label Reader to correct a record, an own Filament Catalog entry as JSON.

**Anatomy.** As 5.1, with a `textarea`; a character count under it when the Hub sets a limit.

**Sizes and tokens.** As 5.1; min height three lines (`calc(var(--s7) + var(--s6) + var(--s1))`), padding
`var(--s2) var(--s3)`, line height 1.45, `resize: vertical`. JSON and code use `mono`. Count `--fs-s` `--muted`,
right aligned.

**States.**
- Default, hover, focus, disabled: as 5.1.
- Pressed: not applicable.
- Loading: as 5.1.
- Error: as 5.1 ("This is not valid JSON: check the brackets, quotes and commas."; "Say what is wrong first, e.g.
  brand is Polymaker.").

**Behaviour and keyboard.** Grows with its content up to ten lines, then scrolls inside. Enter makes a new line; the
form submits with its button (or Ctrl+Enter). The count appears once 80 % of the limit is used ("1,640 of 2,000
characters") and turns `--warn` at the limit; typing stops at the limit.

**Accessibility.** As 5.1; the count is linked by `aria-describedby` and announced politely only when the limit is
reached.

**Theme profiles.** No change.

**Android.** `OutlinedTextField(minLines = 3, maxLines = 10)` with `supportingText` for the count.

**HTML.**
```html
<div class="field">
  <label class="field__label" for="ai-note">What is wrong?</label>
  <textarea class="field__control" id="ai-note" rows="3" placeholder="e.g. brand is Polymaker"
            aria-describedby="ai-note-hint ai-note-error"></textarea>
  <p class="field__hint" id="ai-note-hint">The AI reads the photos again with your note and proposes changes.
    Nothing changes until you accept.</p>
  <p class="field__error" id="ai-note-error" hidden></p>
</div>
```

### 5.11 Form group and the saving model

**Purpose.** A set of related settings that is saved together with **one** Save, keeps what was typed, tells what is
unsaved, asks before edits are lost, and handles saves that restart the Hub.

**Anatomy.** A `form` (`group`) with: head (icon, title `h2`, one-line description, state badges at the right, for
example "Set" or "OK") · body (fields, mostly in row layout) · notes (inline banners, 8.8, such as "Changing
the model or the reads per day restarts the Hub.") · foot: result area (left), **Undo changes** (ghost, only while
dirty) and **Save <group name>** (primary, right: "Save storage locations").

**Which choices apply at once and which wait for Save.**

| Applies at once (no Save) | Saved with the group's Save |
|---|---|
| Appearance and theme (device only), toggles (5.6), segmented choices and selects that stand alone (lane data in a printer's detail, Weigh Station voice), each with its own result | Text, secret entry inside a group, numbers, selects, checkboxes and segmented choices that sit in the group's body |

**Sizes and tokens.** `--surface` ground, 1 px `--border`, `--r`. Head min height `--s7`, padding
`var(--s3) var(--s4)`, title `--fs-l` weight 650 (foundations §9), description `--fs-s` `--muted`, 1 px `--border`
below. Body padding `--s4`. Foot `--surface-2` ground, 1 px `--border` above, padding `var(--s3) var(--s4)`,
gap `var(--s2) var(--s3)`, bottom corners `--r`. Groups on a page are separated by `--s4`.

**States.**
- Default (clean): values as loaded; foot shows the last result, if any.
- Hover: not applicable to the group; its controls have their own.
- Focus: not applicable to the group; its controls have their own. When the sub-navigation (6.4) jumps to a group,
  focus moves to the group's title (`tabindex="-1"`).
- Pressed: not applicable.
- Disabled: when the feature behind the group is switched off, the fields are disabled and a banner in the group says
  so with a button to Features ("Label Reader is switched off. Turn it on in Features."). While the Hub restarts (8.5)
  Save is disabled with the reason "Wait for the Hub to come back."
- Loading: until the group's data arrives, each field shows a skeleton and the form has `aria-busy="true"`; Save is
  disabled with the reason "Loading the current settings…". While saving: Save shows "Saving…", the fields become
  read-only (not disabled, so focus is kept).
- Error: the foot's result shows what failed, the fields named by the Hub show their errors, edits stay, the group
  stays dirty.
- Dirty (`data-state="dirty"`): the foot shows a triangle and "Unsaved changes" in `--warn`, Undo changes appears,
  and the group's entry in the sub-navigation shows the same mark (6.4).

**Behaviour and keyboard.**
1. **Dirty state.** The script keeps a snapshot of the loaded values (in memory, not in the markup) and compares
   every input with it; typing back the old value makes the group clean again. Undo changes puts the snapshot back.
2. **Save.** Pressing Save (or Enter in a field) with nothing changed says "Nothing changed." (neutral). Otherwise:
   check the fields (5.1), pass the lock, send **only the changed values**, then: success writes "Saved: Display
   name, Names for this page." to the result area and updates the snapshot for those fields only. **Nothing else on
   the page is redrawn**: other groups, their edits and the focused field stay as they are. **No second send.** After
   a success the same values cannot be sent twice: a group is clean again, so pressing Save once more says "Nothing
   changed." and sends nothing; a form that creates something (Add a printer, a new catalog line, Add spools) closes,
   or empties its fields and returns to its first state, and its Save is disabled until something is typed again (with its reason, 4.1).
3. **Saves that restart the Hub.** The Hub's reply says `restarts` or `applies` (`POST settings/general` replies
   `{ok, restarts, applies}`). Fields known to restart the Hub carry the hint "Changing this restarts the Hub." On
   `restarts` the result reads "Saved. The Hub restarts to apply it; this page comes back by itself." and the Hub
   restarting state begins (8.5). On `applies` the result reads "Saved; applying… Follow it in the job panel." and
   the job strip (8.4) opens.
   **Order while the Hub takes one key per request** (see 12, "Needs from the Hub"). Each field whose key restarts
   the Hub carries `data-effect="restarts"` (today: Claude model, Reads per day); each field whose key starts
   an apply job carries `data-effect="applies"`. The page sends the changed keys in this order and stops at the first
   error:
   1. keys with no effect, one after another;
   2. keys marked `applies`, one at a time: after each, the page waits for its job to end (8.4) before sending the
      next, because the Hub runs one job at a time; a failed job stops the save;
   3. keys marked `restarts` last, one at a time: after each, the page waits for the Hub to come back (8.5) before
      sending the next. While it waits, the result reads "Saved 3 of 4. The Hub restarts to apply the Claude model;
      the rest is saved when it is back." The group stays dirty for the unsent keys; if the page is reloaded
      meanwhile, they are lost and the result after the reload says which were saved.
   When the save stops, the result names what was saved and what was not ("Saved: Display name. Not saved: Label
   reads per day: the Hub did not answer."), the saved fields leave the dirty state and the others keep their edits.
4. **Unsaved-changes guard.** Leaving the page (another section, a link, Back) while any group is dirty opens a
   dialog: title "Leave without saving?", text "You changed 2 settings in General and 1 in Storage locations.",
   buttons **Stay** (focused first) and **Leave without saving** (danger). Closing a drawer, sheet or dialog that
   holds a dirty form asks the same, except a text-entry dialog with a single field (9.1), which closes at once. Closing or reloading the tab triggers the browser's own `beforeunload` prompt.
   Moving between groups on the same page does not ask: edits stay where they are.
5. **Drafts.** A long form marked `data-draft="<name>"` (Add spools in the web app) keeps its unsaved values, never
   secrets, in `localStorage` under `spoolwarden.draft.<name>` while dirty. On return a banner offers "You have
   unsaved changes from 10 minutes ago." with **Restore them** (primary) and **Discard**. Saving or discarding
   clears the draft. The one other case that writes drafts: when the page reloads itself after an update (8.5),
   every dirty form is kept the same way for that reload, under its `id` when it has no `data-draft`.

**Accessibility.** `form` with `aria-labelledby` its title. The result area is `role="status"`. The dirty mark has
the text "Unsaved changes" (not only a shape). The guard dialog follows 9.1.

**Theme profiles.** `nav` = list: Settings shows one group per pane (the sub-navigation is the list, 6.4). Other `nav`
values: groups follow each other on one page. `detail` = card: forms that belong to no page (Add a printer) open as
dialogs; groups on the Settings page are not affected. `collection`: no change.

**Android.** A `Card` (or a `Column` section on the Settings screen) with a header row, fields and a `Button` "Save";
dirty state in the `ViewModel`; the guard as `BackHandler` plus `AlertDialog`; drafts in the app's settings store.

**HTML.**
```html
<form class="group" id="set-storage" aria-labelledby="set-storage-title" novalidate data-state="dirty">
  <div class="group__head">
    <svg class="icon icon--s" aria-hidden="true"><use href="#i-spool"/></svg>
    <div><h2 class="group__title" id="set-storage-title" tabindex="-1">Storage locations</h2>
      <p class="group__desc">Where spools are put away.</p></div>
  </div>
  <div class="group__body">
    <div class="field field--row">…Locations…</div>
    <div class="field field--row field--number">…Number of storage boxes…</div>
  </div>
  <div class="group__foot">
    <p class="result" role="status"><span class="status status--warn">…</span>Unsaved changes</p>
    <button class="btn btn--ghost" type="button" data-action="undo-changes">Undo changes</button>
    <button class="btn btn--primary" type="submit">Save storage locations</button>
  </div>
</form>
```

---

## 6. Collections and detail

### 6.1 Collection

**Purpose.** Show many things of one kind (printers, Recently added records, devices, backups, slicer preset lines,
spools) so they can be scanned, sorted, opened and acted on. One markup renders as a **table**, **cards**,
**tiles** or **rows**, chosen by the theme's `collection` profile, and turns into stacked cards on phones.

**Anatomy.**
- **Toolbar** (optional): search field (5.2), a filter as a segmented choice (5.7, for example "All 5 / To check 2"),
  and the result area (8.6) for counts and collection-wide results.
- **Head**: one header row of column headers; sortable columns hold a sort button.
- **Items**: one per thing. Each item holds its **main row**, an optional **result row** (the inline result of an
  action on that item, 8.6) and an optional **detail row** (holding its detail region, 6.2).
- **Group rows** (optional): a heading row that starts a group of items ("Found on the network, not added yet").
- **Cells**: each has `data-col` (its column) and `data-prio` (1, 2 or 3). A body cell holds a key (`coll__key`, the
  column name, shown as a label where there are no column headers) and its value. Reserved column names place a cell
  on cards and tiles: `select` (selection checkbox), `expand` (expand button), `visual` (swatch, spool ring or photo),
  `title` (the item's name, a link to its detail, with a sub-line), `status` (status badge), `actions` (row actions),
  `go` (chevron, rows only). Any other name is a body field.
- **Selection bar** (when items are selected): count, bulk actions, Clear selection.
- **Pager** (more than 50 items).
- Empty, error and loading states (10.1 to 10.3) appear in the collection's place.

**Sizes and tokens.**

| | `table` (Console) | `cards` (Workbench) | `tiles` (Spool) | `rows` (Panes) |
|---|---|---|---|---|
| Container | `--surface`, 1 px `--border`, `--r`; CSS grid, every row a `subgrid` of the collection's column template | Grid `repeat(auto-fill, minmax(18rem, 1fr))`, gap `--s4` | Grid `repeat(auto-fill, minmax(14rem, 1fr))`, gap `--s4` | `--surface` block, `--r`, 1 px `--border` hairlines between rows inset by the visual's width |
| Item | Main row min height `var(--row)` (48 px); 1 px `--border` between items | Card: `--surface`, 1 px `--border`, `--r`, padding `--s4`, gap `--s2` | Tile: `--surface`, 1 px `--border`, `--r`, padding `--s4`; `visual` at the top, `calc(var(--s7) * 2)` | Row min height `var(--row)` (48 px), padding `var(--s3) var(--s4)` |
| Cells shown | prio 1 always; prio 2 from tablet up; prio 3 on desktop only | prio 1 and 2, each prio-2 field as "key: value" | prio 1 only | `visual`, `title` with prio-1 fields joined into one sub-line, `status`, `go` |
| Head | `--surface-2`, height 44 px, `--fs-xs` uppercase 0.05em `--muted` (foundations §9) | A wrapping row of sort chips labelled "Sort by" | As cards | As cards |
| Text | Cells `--fs-m`; title `--fs-b` weight 600; sub-line `--fs-s` `--muted`; data in `mono` | Title `--fs-l` weight 650 | Title `--fs-l` weight 650 | Title `--fs-b` weight 600 |
| Actions | `actions` cell at the row end, right aligned | Bottom of the card | Bottom of the tile, main action full width | Not on the row: in the detail |

Each collection's column template for `table` is written once in the stylesheet as a variant, for example
`.coll--printers { grid-template-columns: auto minmax(0, 2fr) minmax(0, 1.2fr) max-content minmax(0, 1fr)
minmax(0, 1fr) max-content; }`. Column widths use `fr`, `auto`, `max-content` and `minmax(0, …)` only.

**Phones.** `table` and `cards` become one column of stacked cards: the title and expand button on the first line,
`status` at the right, prio-1 and prio-2 fields as "key: value" lines, actions full width at the bottom (the main one
stretching). `tiles` become one column below 420 px wide and two above. `rows` stay rows.

**States.**
- Default: as above.
- Hover: table and rows: the row `--surface-2`; cards and tiles: border `--border-strong`.
- Focus: the focused control in a row has its ring; a row has no ring of its own (rows are not focus stops; their
  title link is).
- Pressed: `--surface-3` on the row or card while its title area is pressed.
- Disabled: an item that cannot be acted on now (a printer being forgotten) is dimmed (`--muted`) with its reason in
  its result row; it stays listed.
- Loading: before data: a skeleton of five items in the current profile's shape (10.3). While refreshing: nothing
  moves; values change in place.
- Error: data failed: the error state (10.2) replaces the items, the toolbar stays. One item's action failed: its
  result row shows the failure.
- Locked: a collection that is a code-only read (1.4: backups, trusted computers, pairing requests) shows the locked
  placeholder in its place while the page is Locked, with the toolbar hidden; a collection whose read hides values
  shows the hidden-values note in its toolbar. After unlocking, the items load or are patched in place.
- Selected: `--surface-3` ground (foundations: "selected row"); in `rows` also the item open in the detail pane
  (`aria-current="true"`).

**Behaviour and keyboard.**
- **Opening.** The title is a link to the item's address (`#printers/p1`). Clicking anywhere on the empty area of a
  row, card or tile follows that link (the link's `::after` covers the item; the item's other controls sit above
  it). With `table` and `cards` the expand button (`aria-expanded`) opens and closes the detail in place.
- **Sorting.** Pressing a sortable header (or sort chip) sorts by it ascending; pressing again, descending. The header
  carries `aria-sort`; focus stays on the button; the result area announces "Sorted by Address, A to Z". The choice
  is kept per device in `spoolwarden.sort.<collection>`. Each collection has a default (Recently added: newest
  first). Lists of up to 50 items sort on the device; paged lists offer only the sorts the Hub supports.
- **Column priority.** `data-prio` 1: the thing's name, state and main action; 2: useful at a glance; 3: reference
  facts. Whatever a profile or width hides is always in the item's detail facts (6.3), so hiding a column never
  hides information.
- **Row actions.** At most one primary per item (only when the Hub suggests it, for example "Collect a report" for a
  printer with a problem, or "Use this printer" for a found one), at most one default action ("Test connection"),
  and an overflow menu for the rest. Destructive actions are only in the menu or the detail's Remove zone. The
  item's result row never repeats an action its main row shows: when a result leads to the row's primary action
  ("Collect a report"), the result's text says so and the result shows no button; any other action in a result row
  is a default `btn` (8.6), so an item never shows two primary buttons.
- **Selection.** Offered only where the Hub has an action for several items at once. The first cell is a checkbox
  "Select <name>"; the header checkbox selects every item on the current page (mixed when some are). With one or
  more selected, the selection bar appears above the collection (on phones above the bottom bar): "2 selected", the
  bulk actions, **Clear selection**. Shift+click selects a range; Escape clears.
- **Paging.** More than 50 items (foundations §12 rule 7): pages of 50; the pager under the collection shows
  "51–100 of 214" (`mono`), **Previous** and **Next**; the page is in the address (`#recent?page=2`). Changing page
  moves focus to the first item's title and announces "Page 2 of 5".
- **Live updates.** When data refreshes (polling or the printers' event stream), cells are patched in place by
  `data-id` and `data-col`. An item whose detail holds focus or a dirty form is never replaced. New items are
  inserted in sort order and announced ("1 printer found on the network"); removed items fade out over `--t`.
  Collections the Hub changes on its own (stations asking to pair, printers found) refresh every 5 s while the page
  is visible, and stop while it is hidden.

**Accessibility.** The container is `role="table"` with `aria-label` (or `aria-labelledby` the page title). When
paged, it carries `aria-rowcount`: the header row, plus one main row per item on **all** pages (the Hub's total),
plus the result and detail rows that are shown on the current page. A result row without a result and a closed
detail row are `hidden` and are not counted. Each shown row then carries `aria-rowindex` in that numbering (header 1;
page 2's first main row 52 when nothing is open). An unpaged collection has neither attribute. Head and each item are `role="rowgroup"`; rows `role="row"`; header cells
`role="columnheader"` with `aria-sort` on the sorted one; cells `role="cell"`; the detail and result rows' single
cell has `aria-colspan` equal to the column count. These explicit roles hold in every profile, so a screen reader
gets the same table whether it is drawn as rows, cards or tiles. The `coll__key` labels are `aria-hidden` (the
column header already names the cell). The expand button has `aria-expanded` and `aria-controls`.

**Theme profiles.** This component **is** the `collection` profile (table above). `detail` decides where the detail
row's region is drawn (6.2). `nav` = list: on desktop the collection is the middle pane. `nav` other values: no
change.

**Android.** `table`: `LazyColumn` of rows laid out in columns on expanded width (no Material 3 table exists; header
row as a sticky header). `cards`: `LazyVerticalGrid` of `OutlinedCard`. `tiles`: `LazyVerticalGrid` of `Card`s with
the spool ring. `rows`: `LazyColumn` of `ListItem` with `trailingContent` chevron. Selection: `Checkbox` in
`leadingContent` and a contextual top app bar showing the count. More than 50 items load by page as the list
scrolls, with "51–100 of 214" in the list footer.

**HTML.** (Identical in every theme.)
```html
<div class="coll coll--printers" role="table" aria-labelledby="page-title">
  <div class="coll__head" role="rowgroup">
    <div class="coll__row" role="row">
      <div class="coll__cell" role="columnheader" data-col="expand"><span class="sr">Details</span></div>
      <div class="coll__cell" role="columnheader" data-col="title" aria-sort="ascending">
        <button class="coll__sort" type="button">Printer
          <svg class="icon icon--s" aria-hidden="true"><use href="#i-chevron"/></svg></button></div>
      <div class="coll__cell" role="columnheader" data-col="address" data-prio="2">…Address…</div>
      <div class="coll__cell" role="columnheader" data-col="status">…State…</div>
      <div class="coll__cell" role="columnheader" data-col="slots" data-prio="2">Slots</div>
      <div class="coll__cell" role="columnheader" data-col="connection" data-prio="3">Connection</div>
      <div class="coll__cell" role="columnheader" data-col="actions"><span class="sr">Actions</span></div>
    </div>
  </div>
  <div class="coll__item" role="rowgroup" data-id="p1">
    <div class="coll__row" role="row">
      <div class="coll__cell" role="cell" data-col="expand">
        <button class="btn btn--ghost btn--icon coll__expand" type="button" aria-expanded="true"
                aria-controls="detail-p1" aria-label="Details for Workshop X1">…</button></div>
      <div class="coll__cell" role="cell" data-col="title" data-prio="1">
        <a class="coll__title" href="#printers/p1">Workshop X1</a>
        <span class="coll__sub">Bambu Lab X1 Carbon</span></div>
      <div class="coll__cell" role="cell" data-col="address" data-prio="2">
        <span class="coll__key" aria-hidden="true">Address</span><span class="mono">192.0.2.40</span></div>
      <div class="coll__cell" role="cell" data-col="status" data-prio="1">
        <span class="status status--ok">…Connected</span></div>
      <div class="coll__cell" role="cell" data-col="slots" data-prio="2">
        <span class="coll__key" aria-hidden="true">Slots</span><div class="slot-strip slot-strip--compact">…</div></div>
      <div class="coll__cell" role="cell" data-col="connection" data-prio="3">…Certificate pinned…</div>
      <div class="coll__cell" role="cell" data-col="actions" data-prio="1">
        <div class="actions">…Test connection… …more…</div></div>
    </div>
    <div class="coll__row coll__row--result" role="row">
      <div class="coll__cell" role="cell" aria-colspan="7"><p class="result" role="status"></p></div>
    </div>
    <div class="coll__row coll__row--detail" role="row">
      <div class="coll__cell" role="cell" aria-colspan="7">
        <section class="detail" id="detail-p1" aria-labelledby="detail-p1-title">…</section></div>
    </div>
  </div>
</div>
<nav class="coll__pager" aria-label="Pages">…</nav>
```

### 6.2 Detail region

**Purpose.** Show and act on one thing: a printer, a Recently added record, a device. The same markup also holds a
form that belongs to no single item (Add a printer, Restore a backup): then it is a **form container**. One markup
is drawn inline, in a card, in a sheet or in a pane, chosen by the theme's `detail` profile; in the inline profile
long forms open in a side **drawer**.

**Anatomy.** `section.detail` with:
- **Head**: Back button (only where the detail covers its list: sheet, and pane on phones and tablets), title `h2`,
  status badge, previous and next buttons where the order matters ("Newer record", "Older record"), the item's
  overflow menu (always here in `rows`), Close button (sheet, pane, drawer).
- **Body**: sections with small headings (`--fs-s` weight 650 `--muted`), for example for a printer: "AMS slots" (slot
  strip, 7.5) and facts (key-value list, 6.3) on the left; "Actions" (main action), "Change" (ghost buttons), and a
  "Remove" zone (destructive buttons, hairline above) on the right.
- **Foot** (forms only): result area, Cancel, the primary button.

```
inline (Console)                         sheet (Spool, phone)        pane (Panes, desktop)
| v Workshop X1  ...   [Test] [...] |    +------------------+       +--------+-------------+--------------+
|  +---------------------------------+   | < Workshop X1  x |       |Sections| Printers    | Workshop X1  |
|  | AMS slots        | Actions      |   |------------------|       |        | Workshop X1>| AMS slots    |
|  | A1 ... 62 %      | [Map slots]  |   | AMS slots        |       |        | Garage V.  >| ...          |
|  | Facts            | Change       |   | ...              |       |        | Study A1   >| Actions      |
|  |                  | Remove       |   | [Map slots]      |       |        |             | ...          |
|  +---------------------------------+   +------------------+       +--------+-------------+--------------+
```

**Sizes and tokens.**

| `detail` | Drawn as | Sizes |
|---|---|---|
| `inline` (Console) | Under its row, full width of the collection | `--surface-2` ground, 1 px dashed `--border` above, padding `var(--s4) var(--s4) var(--s5)`, left edge aligned with the title column (`calc(var(--s7) + var(--s4))` on desktop, `--s4` below); body two columns `minmax(0, 1.25fr) minmax(0, 1fr)` with gap `--s5` on desktop, one column below |
| `card` (Workbench) | Inside its card, which grows to the full width of the grid | 1 px `--border` above, padding-top `--s4`, same two columns on desktop |
| `sheet` (Spool) | A modal sheet: the region is moved into the detail host (below) | Phone: from `--top` below the top edge to the bottom, full width, top corners `--r-l`. Tablet and desktop: full height at the right edge, 420 px wide, 1 px `--border-strong` on its left. `--surface`, `--e2`, `--scrim` behind; rises or slides in over `--t-slow` |
| `pane` (Panes) | The right pane | Desktop: third column, at least 22rem, own scroll, sticky below the top bar, 1 px `--border` on its left. Tablet and phone: covers the list pane (drill in), Back in its head |
| drawer (form container under `inline`) | The region moved into the drawer host, a `dialog--drawer` (9.1) | Full height at the right edge, 420 px, as the sheet on wide screens; a bottom sheet on phones |

**Where the region is drawn.** The region's markup is written once and sits once in the page, `hidden` until
opened: an item's detail in its collection's detail row, a form container right after the collection it belongs
to (or at the end of its page). The shell holds three empty **hosts** in the dialog layer (children of `body`, 2.1):
the detail host `dialog.sheet.sheet--detail#detail-host`, the drawer host `dialog.dialog.dialog--drawer#drawer-host`
and the form host `dialog.dialog.dialog--wide#form-host`. On opening, the shared script asks `profile()` and does
one of two things:

| `detail` | An item's detail | A form container |
|---|---|---|
| `inline` | Shown in place (in flow) | Moved into the drawer host |
| `card` | Shown in place, inside its card (in flow) | Moved into the form host (a wide dialog) |
| `sheet` | Moved into the detail host | Moved into the detail host |
| `pane` | Shown in place; CSS places the open region in the pane column | Shown in place; CSS places it in the pane column |

A moved region is opened with the host's `showModal()`, so the host is the modal `dialog` of 9.1 and 9.2: the
browser makes everything outside it inert (the script sets no `inert` itself and never touches `main`), traps
focus and draws `::backdrop`. The host's `aria-labelledby` is set to the region's title id. On closing, the region
is moved back to where it came from and `hidden` again; moving a node keeps what was typed in it. On phones the
drawer and form hosts are drawn as bottom sheets (9.1).

**States.**
- Default: closed (`hidden`), or open.
- Hover: not applicable to the region; its controls have their own.
- Focus: on opening by link or address, focus moves to the title (`tabindex="-1"`); on opening with the expand
  button, focus stays on the button.
- Pressed: not applicable.
- Disabled: when the thing is busy (a printer being mapped), the actions that cannot run now are disabled with their
  reason ("Available when the mapping has finished."); the region stays readable.
- Loading: opening fetches the full item when the collection holds only a summary: the body shows a skeleton of its
  sections; the head shows the title at once (it is known from the row).
- Error: the item could not be loaded: the error state (10.2) inside the body, with **Try again**. The item no longer exists
  (forgotten elsewhere): "Workshop X1 is no longer on this Hub." and a link back to the list.

**Behaviour and keyboard.**
- **Address.** Opening a detail pushes its address (`#printers/p1`, `#recent/214`); loading that address opens it;
  Back closes it. The collection's title links use the same address, so every profile opens in the same way.
- **How many open.** `inline`: several at once. `card`, `sheet`, `pane`: one; opening another closes the first
  (asking first if it holds a dirty form).
- **Modal or not.** A region in a host (the table above) is modal: Escape, Close or a tap on the scrim close it,
  as for any dialog or sheet. With `pane` it is not modal: Escape moves focus back to the item's row. In-place
  regions under `inline` and `card` are part of the page flow.
- **One step at a time.** Detail content made of numbered steps (8.2: Restore, Map by loading filament) shows every
  step in `inline`, `card` and `pane`. In `sheet`, finished and later steps collapse to their title line and the
  current step is open; every step and every action still exists.
- **Live content.** Values refresh in place as in the collection; a focused control or a dirty form is never
  replaced.
- **Closing a dirty form** asks first (5.11).
- **Pane with nothing chosen** (desktop) shows the empty state "Choose a printer to see its details."

**Accessibility.** `section` with `aria-labelledby` its title (a region); in a host, the host is the labelled modal
`dialog`; the expand
button or title link that opened it controls it (`aria-controls`). Back and Close buttons have names ("Back to
printers", "Close Workshop X1").

**Theme profiles.** This component **is** the `detail` profile (table above). `collection` = rows puts the item's
overflow menu in the detail head. `nav` = list: on desktop the pane is the third column.

**Android.** inline: `AnimatedVisibility` inside the list item. card: an expandable `OutlinedCard`. sheet:
`ModalBottomSheet(skipPartiallyExpanded = true)`. pane: the detail pane of `ListDetailPaneScaffold` (on compact
width a separate destination). Every detail is a navigation route (`printers/{id}`), so it can be opened from a link
and survives rotation. Drawer form containers: a full-screen `Dialog` on compact width, a 420 dp side panel on
expanded.

**HTML.** (Identical in every theme; also used as the form container with a `form` inside.)
```html
<section class="detail" id="detail-p1" aria-labelledby="detail-p1-title">
  <header class="detail__head">
    <button class="btn btn--ghost btn--icon detail__back" type="button" aria-label="Back to printers">…</button>
    <h2 class="detail__title" id="detail-p1-title" tabindex="-1">Workshop X1</h2>
    <span class="status status--ok">…Connected</span>
    <button class="btn btn--icon detail__menu" type="button" aria-haspopup="menu"
            aria-label="More actions for Workshop X1">…</button>
    <button class="btn btn--ghost btn--icon detail__close" type="button" aria-label="Close Workshop X1">…</button>
  </header>
  <div class="detail__body">
    <div class="detail__section"><h3 class="detail__heading">AMS slots</h3><ul class="slot-strip">…</ul>
      <dl class="kv">…</dl></div>
    <div class="detail__section"><h3 class="detail__heading">Actions</h3><div class="actions">…</div>
      <h3 class="detail__heading">Change</h3><div class="actions actions--list">…</div>
      <div class="detail__remove"><h3 class="detail__heading">Remove</h3>…Forget printer…</div></div>
  </div>
</section>

<!-- A form container: the same block with a form inside, after its collection -->
<section class="detail" id="add-printer" aria-labelledby="add-printer-title" hidden>
  <header class="detail__head">…<h2 class="detail__title" id="add-printer-title" tabindex="-1">Add a printer</h2>…</header>
  <form class="detail__body" novalidate>…fields…
    <div class="detail__foot"><p class="result" role="status"></p>…Cancel… …primary button…</div></form>
</section>

<!-- The three hosts, once per page, children of body (empty until a region is moved in) -->
<dialog class="sheet sheet--detail" id="detail-host"></dialog>
<dialog class="dialog dialog--drawer" id="drawer-host"></dialog>
<dialog class="dialog dialog--wide" id="form-host"></dialog>
```

### 6.3 Key-value list

**Purpose.** Show facts about one thing as label and value: a printer's address, serial and Access Code state; a
record's fields; a backup's summary.

**Anatomy.** A `dl` of rows; each row a key (`dt`) and a value (`dd`); the value may carry a status badge, a
confidence mark (7.2), a swatch (7.3) and a Copy icon button for values people copy (addresses, serials, links).
Grouped lists (`kv--groups`) split rows under small headings ("Identity", "Weights", "Temperatures", "Other").

**Sizes and tokens.** Row min height 44 px, grid `calc(var(--s7) * 3) minmax(0, 1fr)` (144 px key column; 108 px
`calc(var(--s7) * 2 + var(--s3))` on phones), gap `--s2`, 1 px `--border` between rows; key `--fs-m` `--muted`;
value `--fs-m` `--text`, data in `mono`, wraps (`overflow-wrap: anywhere`). Group headings `--fs-s` weight 650
`--muted`. Grouped lists show two groups side by side on desktop (gap `var(--s2) var(--s5)`), one column below.

**States.**
- Default: as above. An empty value reads "Empty" (record fields) or "Not set" (settings) in `--muted`; secrets read
  "Saved (hidden)".
- Hover: the Copy button shows on wide screens (always shown on touch screens).
- Focus: the Copy button shows and has its ring.
- Pressed: Copy as 4.1.
- Disabled: not applicable.
- Loading: values show skeleton lines; keys are static.
- Error: a value that could not be read: "Not available" in `--muted`.
- Hidden (Locked): when the read behind the list was answered without the code (1.4, "Hidden values"), the list
  shows the hidden-values note above its first row and the values as the Hub sent them; Copy buttons of hidden
  values are not shown. After unlocking, the values are patched in place and the note goes away.

**Behaviour and keyboard.** Copy writes the value to the clipboard and shows "Copied." next to it for 3 s (or the
blocked message of 7.7). A record's "Edit by hand" turns the same rows into fields (5.4 and 5.2) in the same order
and place, with Save changes and Cancel in a foot; only changed fields are sent; "Nothing changed." when none.

**Accessibility.** `dl`/`dt`/`dd` (each row a `div` inside the `dl`). Copy buttons are named "Copy address
192.0.2.40". Grouped lists use a heading per group.

**Theme profiles.** No change with `nav` or `collection`. In `sheet` and `pane` (narrower than desktop inline) the
grouped list is one column.

**Android.** `Column` of rows: key in `labelMedium` `onSurfaceVariant`, value in `bodyMedium`; or `ListItem` with
`overlineContent` key; Copy as `IconButton` with `LocalClipboardManager`.

**HTML.**
```html
<dl class="kv">
  <div class="kv__row"><dt class="kv__key">Address</dt>
    <dd class="kv__value"><span class="mono">192.0.2.40</span>
      <button class="btn btn--ghost btn--icon kv__copy" type="button" aria-label="Copy address 192.0.2.40">…</button></dd></div>
  <div class="kv__row"><dt class="kv__key">Access Code</dt><dd class="kv__value">Saved (hidden)</dd></div>
  <div class="kv__row"><dt class="kv__key">Price per kg</dt>
    <dd class="kv__value"><span class="muted">Empty</span> <span class="confidence">…Not on the label</span></dd></div>
</dl>
```

### 6.4 Sub-navigation inside Settings

**Purpose.** Settings has about nine groups (Appearance, General, Storage locations, Label Reader, Backups and
restore, Network and addresses, Web passphrase, Filament Catalog, Weigh Station voice). The sub-navigation shows them all, jumps to
one, shows where you are and which groups hold unsaved edits.

**Anatomy.** A `nav` with one link per group: label, and the dirty mark (triangle, "Unsaved") when that group is
dirty (5.11). In `list` it also shows each group's one-line summary ("Set", "3 locations", "Last: <time>").

**Sizes and tokens.** Wide screens: a sticky column 200 px wide (`calc(var(--s7) * 4 + var(--s1) * 2)`) at the
left of the groups, top offset `calc(var(--top) + var(--s4))`; links height `--ctl`, padding `0 var(--s3)`, `--r`,
`--fs-m`, `--muted`; current link `--surface` ground, `--text`, weight 650, a 2 px `--accent-text` mark on its left and a
1 px `--border` ring. Tablet: a sticky row under the top bar on `--bg` with a 1 px `--border` below, links as chips
(1 px `--border`, height `calc(var(--s6) + var(--s1))` = 36 px plus hit area) that **wrap** onto a second line rather than scroll. Phone: one sticky
button "Group: General" (`btn`, full width) that opens a bottom sheet listing the groups. Dirty mark `--fs-xs`
`--warn` with the triangle.

**States.**
- Default: the group in view is current.
- Hover: `--surface-2`, `--text`.
- Focus: 2 px `--focus` ring.
- Pressed: `--surface-3`.
- Disabled: never; a group whose feature is off is listed with the hollow circle and opens to its disabled state
  (5.11).
- Loading: static; summaries (in `list`) show skeleton lines.
- Error: none of its own.

**Behaviour and keyboard.** Choosing a group scrolls it into view (smoothly, unless reduced motion), moves focus to
its title, and sets the address to `#settings/<group>` with `replaceState`. Loading `#settings/backups` scrolls to
that group. While scrolling, the group whose title crosses the upper third of the view becomes current
(`aria-current="true"`). Edits in other groups are kept while moving between them.

**Accessibility.** `nav aria-label="Settings groups"`; current link `aria-current="true"`; the dirty mark has text
("Unsaved") read as part of the link ("Storage locations, Unsaved").

**Theme profiles.** `nav` = rail, sidebar, pills: as above (one page with all groups). `nav` = list: the groups are
the rows of the Settings list pane, each opening its group alone in the next pane (on phones, drill in).
`collection`, `detail`: no change.

**Android.** The Settings screen is a list of `ListItem`s (one per group, with summary) that open one screen per
group; on expanded width `ListDetailPaneScaffold` shows the group beside the list.

**HTML.**
```html
<nav class="subnav" aria-label="Settings groups">
  <button class="btn subnav__phone" type="button" aria-haspopup="dialog">Group: General</button>
  <ul class="subnav__list">
    <li><a class="subnav__link" href="#settings/appearance">Appearance</a></li>
    <li><a class="subnav__link" href="#settings/general" aria-current="true">General</a></li>
    <li><a class="subnav__link" href="#settings/storage">Storage locations
      <span class="subnav__dirty status status--warn status--s">…Unsaved</span></a></li>
    …
  </ul>
</nav>
```

---

## 7. Showing data and status

### 7.1 Status badge

**Purpose.** Say the state of something in one word, with a shape so it is never told by colour alone (foundations
§1 principle 7, §10).

**Anatomy.** A shape (`svg` from the sprite) and a word; optionally a count after the word ("Connected 2").
Variants by state (`status--ok`, `status--bad`, `status--warn`, `status--info`, `status--muted`, `status--run`) and a
small size (`status--s`).

**The vocabulary.** These sixteen words are the only badges. Every interface (Hub page, web app, app, command line)
uses the same words for the same states. Anything else is a sentence.

| Word | Shape | Colour | Means / maps from |
|---|---|---|---|
| Connected | filled circle `s-filled` | `--ok` | A printer, device or the Hub answers (`connected`) |
| Offline | hollow circle `s-hollow` | `--bad` | Something that should answer does not (`offline`, no reply) |
| Not configured | hollow circle | `--muted` | Known but not set up yet (`not_configured`; a printer found, not added) |
| On | filled circle | `--ok` | A feature or option is on |
| Off | hollow circle | `--muted` | A feature or option is off |
| Set | filled circle | `--ok` | A secret is saved |
| Not set | hollow circle | `--muted` | A secret is not saved |
| OK | filled circle | `--ok` | A check passed (Overview row `ok`; up to date) |
| Needs a look | triangle `s-triangle` | `--warn` | A check failed or a printer needs something (`fail`, `wrong_code`, `cert_changed`, `needs_developer_mode`); always followed by a sentence saying what to do |
| Note | diamond `s-diamond` | `--info` | Information worth reading (Overview row `info`) |
| As detected | hollow circle | `--muted` | A Recently added record as the Label Reader read it (`detected`) |
| Revised by AI | info circle `i-info` | `--info` | Corrected by the Label Reader and accepted (`revised_ai`) |
| Edited by hand | pencil `i-pencil` | `--info` | Corrected by hand (`edited`) |
| Running | half-filled circle `s-half` | `--accent-text` | A job or mapping is under way |
| Done | filled circle | `--ok` | A job ended well (exit 0) |
| Failed | octagon `s-octagon` | `--bad` | A job, mapping or check ended badly (non-zero exit; a job that stopped without finishing also reads Failed, followed by "It stopped without finishing.") |

**Sizes and tokens.** Word `--fs-m` weight 600 (`status--s`: `--fs-s`), line height 1.3, no wrap; gap
`--s1`; shape `--s2` (triangle and octagon `calc(var(--s2) + var(--s1) / 2)`, 1.2). The two icons used as shapes
(`i-info`, `i-pencil`) are drawn by `status__shape` at `--s3` (12 px), not with `icon--s` (16 px). Colour as the table, for shape and word. No ground and no border: a badge is text.

**States.**
- Default: one of the sixteen.
- Hover: none; a badge is not a control (inside a link it follows the link).
- Focus: not focusable.
- Pressed: not applicable.
- Disabled: not applicable; a dimmed item keeps its badge.
- Loading: before the state is known: a skeleton of the badge's width. "Running" is a static half-filled circle;
  motion belongs to the spinner (8.1), not to badges.
- Error: expressed by the words Offline, Needs a look and Failed.

**Behaviour and keyboard.** Badges update in place when data refreshes. A change the person caused is announced by
that action's result. A change that happens by itself is announced politely only when it needs action ("Study A1
mini is offline."; "Backup: failed.").

**Accessibility.** The shape is `aria-hidden`; the word is real text. Where a word is unclear out of its column, a
`sr` prefix gives the subject ("State: "). Contrast of each colour on `--surface`, `--surface-2` and `--bg` is tested
by the token check (foundations §4.1).

**Theme profiles.** No change in look. `collection` = tiles and cards place the badge at the top right of the item;
`rows` at the row end before the chevron.

**Android.** A small `StatusLabel(kind, text)` composable: `Icon` (the shape) and `Text` in the semantic colour of
the app's theme. Not Material 3 `Badge` (that is a count on an icon).

**HTML.**
```html
<span class="status status--ok"><svg class="status__shape" aria-hidden="true"><use href="#s-filled"/></svg>Connected</span>
<span class="status status--bad"><svg class="status__shape" aria-hidden="true"><use href="#s-hollow"/></svg>Offline</span>
<span class="status status--warn status--s"><svg class="status__shape" aria-hidden="true"><use href="#s-triangle"/></svg>Needs a look</span>
```

### 7.2 Confidence display (Label Reader results)

**Purpose.** Show how sure the Label Reader was of each value it read from a label, so a person checks exactly the
fields that need it.

**Anatomy.** Four levels, each a shape and words:

| Level | Shape | Colour | Words |
|---|---|---|---|
| High | filled circle | `--ok` | "High" (shown only in summaries; a high field shows no mark) |
| Medium | triangle | `--warn` | "Medium" |
| Low | octagon | `--bad` | "Low: check this" |
| Not on the label | hollow circle | `--muted` | "Not on the label" |

Three uses:
1. **Per field**: the mark after the value (key-value list, 6.3) or after the label (in an editable form).
2. **Field group note**: "Read confidence is high unless marked." in the head of the fields.
3. **Record summary** (in a collection cell "Read confidence"): "High" when every field is high; otherwise the
   lowest level with the fields at that level, then the others: "Low: check Material, Net weight", "Medium: Colour ·
   Not on the label: Price per kg". A record added by hand has no reading: the cell says "Not read (typed by hand)"
   in `--muted`, no mark.

**Sizes and tokens.** As the status badge, small size (`status--s`) for per-field marks. A summary is one line
of `--fs-m` text: the badge with the level's words ("Low: check", "Medium:"), then the field names in `--text`; the
line wraps after the badge when it is narrow, and the next level follows after " · ".

**States.**
- Default: as above.
- Hover: none.
- Focus: not focusable.
- Pressed: not applicable.
- Disabled: not applicable.
- Loading: skeleton of the summary while the record loads.
- Error: when the Hub sends no confidence for a field, the field shows no mark (treated as high) only if the read
  itself succeeded; if the read failed, the summary says "Not read" with the reason in the detail.

**Behaviour and keyboard.** A mark stays next to its field until the person changes that field's value (a value set
by hand is no longer a reading). In the Add spools review (web app and app), fields at Low or Medium also get the
hint "The Label Reader was not sure: check this." (not an error; the field is not `aria-invalid`). The collection
filter "To check" lists the records with any Medium or Low field.

**Accessibility.** Shape `aria-hidden`; the words are text and read after the value ("Colour, #2B2B2E, Medium"). The
summary is plain text.

**Theme profiles.** No change in look. `collection` = tiles show only the summary's first words ("Low: check 2
fields"); full lists are in the detail.

**Android.** The same `StatusLabel`; in fields as part of `supportingText`.

**HTML.**
```html
<span class="confidence status status--warn status--s">
  <svg class="status__shape" aria-hidden="true"><use href="#s-triangle"/></svg>Medium</span>
<div class="coll__cell" role="cell" data-col="confidence">
  <p class="confidence__summary"><span class="status status--bad">…Low: check</span> Material, Net weight</p></div>
```

### 7.3 Filament swatch

**Purpose.** Show a filament's colour next to its name, so spools can be recognised at a glance.

**Anatomy.** A block filled with the filament colour (`--swatch`, set by script, 1.4) with a 1 px `--border-strong`
outline (so a white spool on a white card is still visible, foundations §4.1); variants: **level** (a tall swatch
whose filled part is the remaining amount, `--level`), **empty** (dashed outline, no fill: an empty slot), **no
colour** (a hatched fill of `--surface-2` and `--surface-3` stripes `var(--s1)` wide). Always beside the colour's name
or hex in text.

**Sizes and tokens.** Small `--s3` square (inline in text); medium `calc(var(--s4) + var(--s1) / 2)` (18 px) square (slot
rows, review cards); level `--s4` by `calc(var(--s5) - var(--s1) / 2)` (16 by 22 px); large
`calc(var(--s6) - var(--s1))` (28 px) square (spool cards).
Radius `--r-s`. Not inverted in dark (foundations §5).

**States.**
- Default: filled.
- Hover: none (not a control).
- Focus: not focusable.
- Pressed: not applicable.
- Disabled: not applicable.
- Loading: a skeleton square.
- Error: a colour that fails the hex check renders as "no colour" and the text says "No colour".

**Behaviour and keyboard.** None. The level variant's fill height follows `--level` over `--t`.

**Accessibility.** `aria-hidden="true"`: the colour's name and hex are in visible text or in the item's `sr`
sentence ("A1 Polymaker PolyTerra PLA Charcoal Black #2B2B2E, 62 % left").

**Theme profiles.** `collection` = tiles uses the spool ring (7.4) as the visual instead; table, cards and rows use
swatches. `nav`, `detail`: no change.

**Android.** The app's existing `ColorSwatch` composable (a `Canvas` with fill, 1 dp outline in the `outline` role,
dashed ring for empty), kept and fed from the theme.

**HTML.**
```html
<span class="swatch" aria-hidden="true"></span> Charcoal Black <span class="mono muted">#2B2B2E</span>
<span class="swatch swatch--level" aria-hidden="true"><span class="swatch__fill"></span></span>
<span class="swatch swatch--empty" aria-hidden="true"></span>
```

### 7.4 Spool ring

**Purpose.** Show one spool's colour and how much is left as a ring, the way a spool looks from the side. The main
visual of the Spool theme's tiles, and the spool picture in every detail of a spool.

**Anatomy.** An inline SVG: a track circle (`--surface-3`), an arc in the filament colour from 12 o'clock clockwise
for the remaining share, 1 px `--border-strong` rings inside and outside the band (pale colours stay visible), a hub
circle (`--surface-2`, 1 px `--border-strong`). Text beside or below: "62 %" and "620 g left" in `mono`. Empty slot:
dashed outline ring and the word "Empty". Remaining unknown: full track, no arc, "Unknown".

**Sizes and tokens.** Small `--s6` (32 px), medium `calc(var(--s7) + var(--s4))` (64 px), large `calc(var(--s7) * 2)`
(96 px); band width one eighth of the size. Arc colour `var(--swatch)`; arc length from `--level` (the circle has
`pathLength="100"` and `stroke-dasharray: calc(var(--level) * 100) 100`). Percentage `--fs-2xl` (large), `--fs-l`
(medium), `--fs-s` (small) with `tabular-nums`. Not inverted in dark.

**States.**
- Default: as above.
- Hover: none (inside a tile the tile has the hover).
- Focus: not focusable.
- Pressed: not applicable.
- Disabled: not applicable.
- Loading: track only, text skeleton.
- Error: invalid colour: the arc is `--muted` and the text says "No colour".

**Behaviour and keyboard.** When the remaining amount changes, the arc moves to its new length over `--t` (at once
with reduced motion).

**Accessibility.** `role="img"` with `aria-label` "Charcoal Black, 62 % left, 620 g" when no visible text says the
same; otherwise `aria-hidden`.

**Theme profiles.** `collection` = tiles: large ring as the tile's visual (for printers, one small ring per slot).
Other `collection` values: medium ring in the detail only. `nav`, `detail`: no change.

**Android.** `Canvas` drawing the track, arc (`drawArc` with the filament colour) and outline rings; or
`CircularProgressIndicator(progress = { level }, color = filamentColor, trackColor = surfaceContainerHighest)` with
the outline drawn behind it.

**HTML.**
```html
<svg class="spool-ring spool-ring--l" viewBox="0 0 96 96" role="img" aria-label="Charcoal Black, 62 % left, 620 g">
  <circle class="spool-ring__track" cx="48" cy="48" r="42"/>
  <circle class="spool-ring__arc" cx="48" cy="48" r="42" pathLength="100"/>
  <circle class="spool-ring__edge" cx="48" cy="48" r="48"/>
  <circle class="spool-ring__hub" cx="48" cy="48" r="18"/>
</svg>
```

### 7.5 Slot strip

**Purpose.** Show what is loaded in each slot of a printer (AMS slots, tool slots), how much is left, and which slot
is in use; offer Load and Unload where the interface has them.

**Anatomy.** Two forms:
1. **Compact** (in a collection cell or on a card): one level swatch per slot in a row, empty slots dashed, then
   "3 of 4 loaded" in `mono`, and an `sr` sentence listing every slot.
2. **Full** (in a detail): a list, grouped under unit headings ("AMS A", "AMS HT A") when a printer has several
   units. Each row: slot label (`mono`: A1, T0), medium swatch, filament name with colour name and hex (`--muted`),
   remaining as a determinate bar (8.3) plus "62 %", "In use" for the active slot, and the row's actions (web app and
   app: **Load**, **Unload**).

**Sizes and tokens.** Compact: swatches gap `--s1`. Full: rows min height 44 px, grid
`calc(var(--s6) - var(--s1) / 2) calc(var(--s4) + var(--s1) / 2) minmax(0, 1fr) 7rem auto` (30 px, 18 px), gap
`--s2`, padding `var(--s1) var(--s3)`, 1 px `--border` between rows, the list in `--surface` with 1 px `--border` and `--r`. Active row:
3 px `--accent-text` mark on its left and "In use" in `--accent-text` weight 650. On phones the bar is hidden (the
percentage stays) and the last column shrinks to 4.5rem.

**States.**
- Default: as above.
- Hover: rows with actions take `--surface-2`.
- Focus: as the buttons inside.
- Pressed: as the buttons.
- Disabled: Load and Unload are disabled with the reason when the printer cannot take them now ("Available when the
  printer is connected.").
- Loading: a slot the printer is still reading shows a spinner and "Reading…"; the whole strip shows skeleton rows
  until the first status arrives.
- Error: no slot data: one line in place of the rows: "No slot data: the printer is offline." or "No slots read yet.
  Test the connection, then map the slots."

**Behaviour and keyboard.** Updates live from the printer status without moving focus. Load opens the load flow for
that slot; Unload asks first (9.1), naming the spool and where it goes back to.

**Accessibility.** Full form: a `ul` with an `aria-label` ("AMS slots of Workshop X1"); each row's text reads in order
"A1, Polymaker PolyTerra PLA, Charcoal Black, 62 % left, in use". Compact form: swatches `aria-hidden`, the `sr`
sentence carries the content, "3 of 4 loaded" is visible.

**Theme profiles.** `collection` = table and cards: compact form in the Slots cell; tiles: one small spool ring per
slot instead of swatches; rows: only "3 of 4 loaded" in the row's sub-line. Full form in every `detail`.

**Android.** Full: `Column` of rows (swatch, texts, `LinearProgressIndicator(progress)`, `TextButton`s Load and
Unload); compact: a `Row` of swatches with a `semantics { contentDescription = … }` sentence.

**HTML.**
```html
<div class="slot-strip slot-strip--compact">
  <span class="slot-strip__swatches" aria-hidden="true"><span class="swatch swatch--level">…</span>…</span>
  <span class="sr">A1 Polymaker PolyTerra PLA Charcoal Black 62 %; A2 …; A4 empty.</span>
  <span class="slot-strip__count mono" aria-hidden="true">3 of 4 loaded</span>
</div>
<ul class="slot-strip" aria-label="AMS slots of Workshop X1">
  <li class="slot-strip__row" data-state="active">
    <span class="slot-strip__label mono">A1</span><span class="swatch" aria-hidden="true"></span>
    <span class="slot-strip__name">Polymaker PolyTerra PLA <span class="muted">Charcoal Black</span></span>
    <span class="slot-strip__level"><span class="progress" aria-hidden="true">…</span><span class="mono">62 %</span></span>
    <span class="slot-strip__use">In use</span>
  </li>
</ul>
```

### 7.6 Photo thumbnail and viewer

**Purpose.** Show the label photos of a Recently added record small in lists and large on demand, and the photos
chosen before reading labels.

**Anatomy.** **Thumbnail**: a button holding the image (cropped to fill), a count badge when a record has several
photos ("2"); without a photo, a placeholder (dashed box with the camera icon and "No photo" for screen readers).
**Viewer**: a wide dialog (full screen on phones) with the title "Photo 2 of 3", the image fitted inside, Previous
and Next buttons, a Download link, and Close.

**Sizes and tokens.** Thumbnail small `calc(var(--s7) - var(--s1))` (44 px, in collections), medium `calc(var(--s7) * 2)` (96 px) in a grid
`repeat(auto-fill, minmax(6rem, 1fr))` gap `--s2` (in details); `--r`, 1 px `--border`, `--surface-2` ground;
count badge `--surface` ground, 1 px `--border-strong`, fully rounded, `--fs-xs` `mono`, at the bottom right.
Placeholder 1 px dashed `--border-strong`, icon `--muted`. Viewer: `dialog--wide`, image area `--surface-2`, image
`object-fit: contain`, max height the viewport minus head and foot.

**States.**
- Default: as above.
- Hover: thumbnail border `--border-strong`, `cursor: zoom-in`.
- Focus: 2 px `--focus` ring.
- Pressed: border `--accent-text`.
- Disabled: not applicable.
- Loading: a skeleton box of the same size (width and height are set, so nothing shifts); in the viewer a spinner in
  the image area.
- Error: the image failed: the warning triangle icon in the box and "Photo could not be loaded" (`sr` on the
  thumbnail, visible in the viewer with **Try again**).

**Behaviour and keyboard.** A thumbnail opens the viewer at that photo. In the viewer: Left and Right arrows (and the
buttons) go to the previous and next photo, Home and End to the first and last, Escape closes; on wide screens
clicking the image toggles between fitted and actual size (scrolling inside); on phones pinch zoom works
(`touch-action: pinch-zoom`). Closing returns focus to the thumbnail of the photo last shown. Photos come from
`GET intake/history/<id>/photos/<n>` (Hub page) and `GET history/{id}/photos/{n}` (web app).

**Accessibility.** Thumbnail button name "Enlarge photo 2 of 3"; its image `alt=""` (the button names it). Viewer
`dialog` labelled by its title; image alt "Label photo 2 of 3 of Polymaker PolyTerra PLA Charcoal Black"; moving
between photos updates the title and announces "Photo 3 of 3".

**Theme profiles.** `collection` = table and rows: small thumbnail as the `visual` cell; cards: medium thumbnail on the
card; tiles: the first photo across the tile's width (4:3) as the visual. `nav`, `detail`: no change.

**Android.** Thumbnail: `Image` with `Modifier.clickable`, bitmap loaded by the app; viewer: full-screen `Dialog` with
`HorizontalPager` and pinch zoom; Previous and Next as `IconButton`s.

**HTML.**
```html
<button class="thumb" type="button" aria-label="Enlarge photo 1 of 2" data-action="photo" data-photo="0">
  <img class="thumb__img" src="…/photos/0" alt="" width="44" height="44">
  <span class="thumb__count mono" aria-hidden="true">2</span></button>
<span class="thumb thumb--none"><svg class="icon icon--s" aria-hidden="true"><use href="#i-camera"/></svg>
  <span class="sr">No photo</span></span>
<dialog class="dialog dialog--wide viewer" aria-labelledby="viewer-title">…</dialog>
```

### 7.7 Code block with Copy

**Purpose.** Show commands to run elsewhere (Klipper add-on install lines, firewall rules, a reader token) and log
output, exactly, with one-press copying.

**Anatomy.** A box holding a `pre` with the text and a caption bar: where and how to use it ("shell · run on the
printer"), the result area, and **Copy** (ghost, copy icon). Log output uses the same box without the caption bar or
with a **Download** link.

**Sizes and tokens.** `--code` ground, 1 px `--border`, `--r`; `pre` padding `var(--s2) var(--s3)`,
`--fs-s`/1.65 `--mono`. Commands keep their line breaks and scroll sideways inside the box (`white-space: pre`,
foundations §7); logs wrap (`pre-wrap`). Caption bar: 1 px `--border` above, padding `0 0 0 var(--s3)` (Copy fills
the bar's height),
caption `--fs-xs` `mono` `--muted`.

**States.**
- Default: as above.
- Hover: Copy `--surface-2`.
- Focus: Copy has its ring; a `pre` that scrolls is focusable (`tabindex="0"`) and shows the ring, so it can be
  scrolled by keyboard.
- Pressed: Copy `--surface-3`.
- Disabled: Copy is disabled (with the reason "Nothing to copy yet.") until the text is there.
- Loading: while the Hub prepares the text (`POST printers/pack`: "Checking the signed release…"), the box shows a
  spinner line (8.1) in place of the text.
- Error: the text could not be prepared: the Hub's reason in the box as an inline result (failed) with **Try
  again**.

**Behaviour and keyboard.** Copy calls `navigator.clipboard.writeText` with the exact text (no prompt characters);
success shows "Copied." for 3 s; when the clipboard is blocked the text is selected and the result says "Copy is
blocked here: select the text and copy it."

**Accessibility.** The `pre` is labelled by its caption (`aria-labelledby`); Copy's name says what it copies ("Copy
the install commands"); the result area is `role="status"`.

**Theme profiles.** No change.

**Android.** `Surface(color = surfaceContainerHighest)` holding `SelectionContainer { Text(fontFamily = Monospace) }`
with `horizontalScroll`; Copy as `TextButton` using the clipboard manager; result as text under it.

**HTML.**
```html
<figure class="code">
  <pre class="code__text" tabindex="0" aria-labelledby="pack-cap"><code>…</code></pre>
  <figcaption class="code__bar">
    <span class="code__caption mono" id="pack-cap">shell · run on the printer</span>
    <span class="result" role="status"></span>
    <button class="btn btn--ghost" type="button" data-action="copy" aria-label="Copy the install commands">
      <svg class="icon icon--s" aria-hidden="true"><use href="#i-copy"/></svg>Copy</button>
  </figcaption>
</figure>
```

### 7.8 QR block

**Purpose.** Pair a phone, the PC's Slicer Sync or a Weigh Station, or open the web app on an iPhone, by scanning;
with the same information as text for anyone who cannot scan.

**Anatomy.** The QR image (with its own white quiet zone, as the Hub delivers it) · what scanning does ("Scan with the
Spoolwarden app", "Open in Safari on the iPhone") · the link or pairing code as text (`mono`, selectable) with Copy ·
the pairing code large ("Pairing code 123 456") · the certificate fingerprint in groups of four (`mono`) with "Check
that the phone shows the same groups" · "Expires in 9 min".

**Sizes and tokens.** Image width 14rem (it grows with the text size), never smaller than `calc(var(--s7) * 3 + var(--s6))` (176 px); the page adds no
colour or border to the QR itself (the white comes with the image, foundations §5). Caption `--fs-m`; pairing code
`--fs-2xl` `mono` weight 650; fingerprint `--fs-m` `mono` `--text` (a person compares it before pairing, so it is never smaller: foundations
§4.2); expiry `--fs-m` `--muted`. The block is a
`--surface` card with `--r` and padding `--s4`; on wide screens image left and texts right, stacked on phones.

**States.**
- Default: as above.
- Hover: as Copy.
- Focus: as Copy and the link.
- Pressed: as Copy.
- Disabled (expired): the image is removed (an expired code must not be scanned) and replaced by the warn result "The pairing
  code expired. Make a new one." with **Make a new code** (primary).
- Loading: a square skeleton of the image size while `POST pair` answers.
- Error: the Hub cannot draw a QR code (`qr_svg` is empty): no image; the text says "This Hub cannot draw a QR code.
  Type the pairing code or copy the link instead." and the code and link stay.

**Behaviour and keyboard.** The expiry updates once a minute and turns into the expired state at zero. While shown,
the page asks `GET state` every 3 s for the new device; when it appears, the block is replaced by the result "Paired:
Pixel phone." (ok). The image is shown with an `img` whose `src` is a Blob URL made from the Hub's SVG text (never
inserted as markup, foundations §12 rule 3); this needs `blob:` in the image policy (section 12).

**Accessibility.** `img` alt says what it is for ("QR code for pairing a phone"), not its content; the code and link
are text; the expiry is announced politely only at one minute left and at expiry.

**Theme profiles.** No change.

**Android.** The app scans codes (its CameraX scanner, `05-android-app.md`) and does not show them. Where an app
screen shows a code, `Image(bitmap)` on a white `Surface`.

**HTML.**
```html
<div class="qr">
  <img class="qr__image" src="blob:…" alt="QR code for pairing a phone" width="224" height="224">
  <div class="qr__text">
    <p>Scan with the Spoolwarden app, or type the pairing code.</p>
    <p class="qr__code mono"><span class="sr">Pairing code </span>123 456</p>
    <p class="qr__fingerprint mono">…the certificate fingerprint, in groups of four…</p>
    <p>Check that the phone shows the same groups.</p>
    <p class="qr__expiry" aria-live="polite">Expires in 9 min</p>
  </div>
</div>
```

### 7.9 Before-and-after change list

**Purpose.** Show proposed or made changes as old value and new value side by side: an AI proposal for a Recently
added record, the dry run of Add spools, Slicer presets updates that would be accepted, what turning a feature on
changes. Nothing changes until the person accepts.

**Anatomy.** A container (`changes`) with a heading ("Proposal: 2 changes"), a list of changes (field name; old
value, struck through; an arrow; new value, bold; an optional note), a sentence "Nothing changes until you accept.",
and the actions **Accept** (primary) and **Discard**. A compact variant without actions and container (`changes--compact`)
is used inside revision lists.

**Sizes and tokens.** Container 1 px `--accent-text`, `--accent-soft` ground, `--r`, padding `--s3`; heading `--fs-s`
weight 650. Each change: `--surface`, 1 px `--border`, `--r`, padding `var(--s2) var(--s3)`, grid
`minmax(6rem, auto) minmax(0, 1fr) auto minmax(0, 1fr)`, gap `--s2`, `--fs-m`; old value `--muted` with
`line-through`; new value weight 600; values in `mono` with units. On phones the field name takes its own line and
old, arrow, new follow on the next.

**States.**
- Default: the proposal as above.
- Hover: as the buttons.
- Focus: as the buttons; when a proposal arrives, focus moves to Accept.
- Pressed: as the buttons.
- Disabled: Accept and Discard are disabled while accepting.
- Loading: before the proposal: a spinner line "Asking the Label Reader… (up to a minute)" in its place; while
  accepting: "Accepting…" on Accept.
- Error: the Label Reader could not answer: an inline result (failed) with the Hub's reason and **Try again**. No
  changes: "The Label Reader changed nothing." (neutral, no actions). No photo kept: a note "No photo was kept for
  this record: it worked from the saved values and your note."

**Behaviour and keyboard.** Accept passes the lock, applies the proposal (`POST intake/history/<id>/apply` with the
proposal), updates the fields in place, adds a revision (7.10), and replaces the container with the result
"Accepted. 2 fields changed; revision 2 keeps the old values."; focus goes to the note field it came from. Discard
replaces it with "Proposal discarded. Nothing changed." For dry runs (Add spools) each spool is one group of changes
with its own heading, never one block of text.

**Accessibility.** Container `section` labelled by its heading. Each old value is preceded by `sr` "was", the arrow is
`aria-hidden` and followed by `sr` "becomes", so "Nozzle range, was 190-230 °C, becomes 190-220 °C" is read. Results
use the `role="status"` area.

**Theme profiles.** No change.

**Android.** A `Column` of rows: `Text` with `TextDecoration.LineThrough` for old values, an arrow icon, bold new
value; `Button` Accept and `OutlinedButton` Discard.

**HTML.**
```html
<section class="changes" aria-labelledby="prop-title">
  <h3 class="changes__title" id="prop-title">Proposal: 2 changes</h3>
  <ul class="changes__list">
    <li class="changes__item"><span class="changes__key">Nozzle range</span>
      <span class="changes__old mono"><span class="sr">was </span>190-230 °C</span>
      <span aria-hidden="true">→</span>
      <span class="changes__new mono"><span class="sr">becomes </span>190-220 °C</span></li>
  </ul>
  <p class="changes__note">Nothing changes until you accept.</p>
  <div class="actions"><button class="btn" type="button" data-action="discard">Discard</button>
    <button class="btn btn--primary" type="button" data-action="accept">Accept</button></div>
</section>
```

### 7.10 Revision list with undo

**Purpose.** Keep the history of changes to a Recently added record, by hand and by the Label Reader, and undo the newest one.

**Anatomy.** An ordered list, newest first. Each revision: "Revision 2" (bold), the time (`mono`), who ("by hand" or
"by the Label Reader"), the changes in the compact change list (7.9), the person's note if any ("note: brand is Polymaker"),
and on the newest revision that is not undone **Undo revision 2** (default button, undo icon). Undone revisions keep
their text struck through with "(undone)". Empty: "No revisions. Corrections by hand or by the Label Reader appear here."

**Sizes and tokens.** Rows padding `var(--s3) var(--s4)`, 1 px `--border` between rows, gap `--s2`, `--fs-m`; undone
text `--muted` with `line-through`.

**States.**
- Default: as above.
- Hover: as the button.
- Focus: as the button.
- Pressed: as the button.
- Disabled: older revisions have no Undo button (the Hub undoes only the newest); nothing is shown disabled.
- Loading: Undo shows "Undoing…"; the list shows skeleton rows while the record loads.
- Error: the undo failed: inline result under the list with the Hub's reason; the list is unchanged.

**Behaviour and keyboard.** Undo passes the lock and calls `POST intake/history/<id>/undo` with the revision number
(web app: `POST history/{id}/undo`). It does not ask first: the old values are kept as a revision and can be set
again. Success: the fields update, the revision shows "(undone)", the result says "Revision 2 undone. Name is
PolyTerra PLA Charcoal Black again." plus any filament note from the Hub ("Filament 88 has no spools left; it was not
deleted."), and focus moves to the list's heading.

**Accessibility.** `ol reversed` with `aria-labelledby` its heading; the result area is `role="status"`.

**Theme profiles.** No change; it lives in the detail region in every profile.

**Android.** `Column` of `ListItem`s (`headlineContent` "Revision 2 · by hand", `supportingContent` changes,
`trailingContent` `TextButton` "Undo").

**HTML.**
```html
<section class="revisions" aria-labelledby="rev-title">
  <h3 class="revisions__title" id="rev-title" tabindex="-1">Revisions</h3>
  <ol class="revisions__list" reversed>
    <li class="revisions__item"><p><b>Revision 1</b>, <span class="mono">2026-11-12 14:09</span>, by hand</p>
      <ul class="changes changes--compact">…Empty spool weight 150 → 140 g…</ul>
      <button class="btn" type="button" data-action="undo" data-revision="1">
        <svg class="icon icon--s" aria-hidden="true"><use href="#i-undo"/></svg>Undo revision 1</button></li>
  </ol>
  <p class="result" role="status"></p>
</section>
```

---

## 8. Progress and feedback

### 8.1 Inline spinner

**Purpose.** Show that something short is under way (a test, a save, a search), next to the words that say what.

**Anatomy.** A ring with a gap that turns, always beside text ("Testing the connection to 192.0.2.40…"). A spinner
that must stand alone (inside an icon-sized slot) is `spinner--alone` and carries its own hidden text.

**Sizes and tokens.** `--s4` square, `calc(var(--s1) / 2)` (2 px) `currentColor` border with one transparent quarter,
fully rounded, one turn per `calc(var(--t) * 4)` (800 ms), linear. Takes the colour of its text.

**States.**
- Default: turning.
- Hover, focus, pressed: not applicable (not a control).
- Disabled: not applicable.
- Loading: it is the loading state.
- Error: not applicable; when the work fails, the spinner is replaced by the result (8.6).

**Behaviour and keyboard.** Shown from the moment a request starts until it ends. Under reduced motion the ring is not
drawn; the words beside it carry the meaning, and a `spinner--alone` shows the word "Working…" (foundations §4.3).

**Accessibility.** `aria-hidden="true"`; the text beside it is in a `role="status"` area. A `spinner--alone` has
`role="status"` and `sr` text "Working…".

**Theme profiles.** No change.

**Android.** `CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)`.

**HTML.**
```html
<p class="result" role="status"><span class="spinner" aria-hidden="true"></span>
  Testing the connection to <span class="mono">192.0.2.40</span>…</p>
```

### 8.2 Step progress

**Purpose.** Show where a multi-step task stands: a task the Hub runs in steps (slot mapping, a scan), or a task the
person goes through in steps (Restore a backup, Map by loading filament, pairing).

**Anatomy.** Two forms:
1. **Step line** (the Hub runs the steps): a sentence "Mapping… step 2 of 4: reading the slots" with a determinate
   bar (8.3) whose value is the share of steps done.
2. **Numbered steps** (`steps`, the person does them): an ordered list; each step has a number circle, a title and
   its content (fields, buttons, result). Each step is **done** (check icon in the circle, `--ok`), **current**
   (circle `--accent-text` border, title weight 650) or **later** (`--muted`).

**Sizes and tokens.** Step line as the inline result (8.6) with the bar `max-width: 20rem` under the sentence.
Numbered steps: grid `var(--s5) minmax(0, 1fr)`, gap `--s3`; circle `--s5`, 1 px `--border-strong`, `--fs-s` `mono`
weight 600; title `--fs-b` weight 650; steps separated by `--s3`.

**States.**
- Default: as above.
- Hover, pressed: as the controls inside.
- Focus: when a step becomes current, focus moves to its first control.
- Disabled: controls of later steps are disabled with the reason "Do step 1 first." (Restore: Upload and check
  waits for a chosen zip; the typed word waits for a checked upload).
- Loading: the current step shows a spinner line ("Uploading and checking…").
- Error: the failing step's circle shows the octagon in `--bad` and its result says what failed; earlier steps stay
  done; Cancel puts the whole task back to step 1.

**Behaviour and keyboard.** Steps follow in order; going back to an earlier step is allowed and resets the later
ones. In the `sheet` detail profile finished and later steps collapse to their title line (6.2).

**Accessibility.** `ol`; the current step has `aria-current="step"`; done steps have `sr` text "done". The step line's
bar is a `progressbar` with `aria-valuetext` "Step 2 of 4".

**Theme profiles.** `detail` = sheet: one step open at a time, as above. Others: all steps open. `nav`,
`collection`: no change.

**Android.** Step line: `Text` with `LinearProgressIndicator(progress = { done / total })`. Numbered steps: a custom
`Column` of numbered rows (Material 3 has no stepper).

**HTML.**
```html
<ol class="steps">
  <li class="steps__step" data-state="done"><span class="steps__num">…1<span class="sr"> done</span></span>
    <div><h4 class="steps__title">Choose a zip</h4>…</div></li>
  <li class="steps__step" aria-current="step"><span class="steps__num">2</span>
    <div><h4 class="steps__title">Upload and check</h4>…</div></li>
  <li class="steps__step"><span class="steps__num">3</span>
    <div><h4 class="steps__title">Type restore to go on</h4>…</div></li>
</ol>
```

### 8.3 Determinate bar

**Purpose.** Show how far a measurable task is: print progress, an upload, a job with a known number of steps.

**Anatomy.** A label (what, and the value: "Uploading… 42 %", "62 % · layer 120 of 310 · 1 h 12 min left"), a track
and its fill. An indeterminate variant (`progress--indeterminate`) is used when the amount is not known.

**Sizes and tokens.** Height `--s1`, radius half the height, track `--surface-3`, fill `--accent-text`, fill width from
`--level` (set by script), changing over `--t`. Label `--fs-s`, numbers `mono`. A failed task's fill is `--bad`.

**States.**
- Default: filled to its value.
- Hover, focus, pressed: not applicable.
- Disabled: not applicable.
- Loading: indeterminate variant: a segment of a third of the width moves across the track every `calc(var(--t) * 6)` (1.2 s); under
  reduced motion the track shows no movement and the label reads "Working…".
- Error: fill `--bad`, label states the failure ("Upload failed at 42 %.").

**Behaviour and keyboard.** Updates as the value changes; never goes backwards within one task.

**Accessibility.** `role="progressbar"` with `aria-valuemin="0"`, `aria-valuemax="100"`, `aria-valuenow`,
`aria-valuetext` where words say more, and `aria-labelledby` its label. Not announced on every change; the start and
end of the task are announced by its result. Remaining filament (slot strip, 7.5) is not progress: there the bar is
`aria-hidden` and the percentage is text.

**Theme profiles.** No change.

**Android.** `LinearProgressIndicator(progress = { value })`; indeterminate `LinearProgressIndicator()`.

**HTML.**
```html
<div class="progress">
  <p class="progress__label" id="up-label">Uploading… <span class="mono">42 %</span></p>
  <div class="progress__track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="42"
       aria-labelledby="up-label"><span class="progress__fill"></span></div>
</div>
```

### 8.4 Background-job strip

**Purpose.** Follow a job the Hub runs in the background (back up, restore, apply Features, update, roll back, check
for updates, Filament Catalog update, get the certificate, pair the Weigh Station) from any page, until it ends with
Done or Failed, with its log one press away.

**Anatomy.** A floating panel (`job`): head with status badge (Running, Done, Failed), the job's title, the current
step line ("Step K of N: <sentence>" for a counted job, else the newest log line; one line, `mono`), a log toggle, and Hide (while running) or Close (after the end); a
determinate bar under the head (indeterminate for a job that is not counted, see Steps below); the log (`pre`, hidden until
toggled); after the end, **Show the whole log** and the note "Addresses and serials are hidden here." In the top bar,
the job indicator chip (2.2) mirrors it: spinner or shape, title, state.

Job titles by the Hub's job `name`:

| `name` | Title | `name` | Title |
|---|---|---|---|
| `backup` | Backup | `restore` | Restore |
| `apply` | Applying the changes | `update` | Updating Spoolwarden |
| `rollback` | Rolling back | `check` | Checking for updates |
| `library_update` | Updating the Filament Catalog | `library_rollback` | Going back to the previous Filament Catalog |
| `remote_issue` | Getting the certificate | `station_pair` | Pairing the Weigh Station |
| `channel_nightly` | Switching to nightly builds | `channel_stable` | Switching to signed releases |
| `reader_setup` | Setting up a Tag Reader | any other name | Working |

End lines: "<Title>: done." · "<Title>: failed. See the log." · a job that stopped without finishing: "<Title>:
failed. It stopped without finishing; see the log and the Logs section."

**Steps.** A job that has countable steps says so, and the strip shows a determinate bar; a job that has none
shows an indeterminate bar. Which is which is fixed here, so every interface shows the same thing.

| Job (`name`) | Steps | The step sentences, in order |
|---|---|---|
| `backup` | Counted | Collecting the settings and pairings · Copying the Spoolman database · Writing the zip · Checking the zip |
| `restore` | Counted | Checking the backup · Keeping what is here now as a backup · Stopping the services · Putting the backup in place · Starting the services · Checking that everything answers |
| `update` | Counted | Downloading <version> · Checking its signature · Installing · Restarting the Hub · Checking that it answers |
| `rollback` | Counted | Finding the kept version · Installing <version> · Restarting the Hub · Checking that it answers |
| `apply` | Counted | One step per feature or service that changes ("Switching on Klipper printers", "Restarting the Hub service"), then "Checking that everything answers"; the count is known once the plan is made, before the first step |
| `library_update` | Counted | Downloading the Filament Catalog · Checking its signature · Putting it in place · Asking for a preset build |
| `library_rollback` | Counted | Putting the previous Filament Catalog back · Asking for a preset build |
| `reader_setup` (flashing on the Hub) | Counted | Finding the board · Writing the program · Checking what was written · Joining the Wi-Fi · Reaching the Hub |
| `station_pair` | Counted | Asking the Hub · Saving the pairing · Restarting the Weigh Station service |
| `check` | Not counted | One short request |
| `remote_issue` | Not counted | The certificate tool runs for an unknown time and reports no steps |
| any other name | Not counted | |

The sentences are the wording; a job may have one step more or fewer than listed when its work differs, as long as
each sentence names what the person is waiting for. Rules:

1. The command a job runs writes one line when each step **starts**: `==> step K of N <sentence>`. N is fixed
   before the first step line and never changes; K starts at 1 and goes up by one. A step sentence holds no
   address, serial or name of a person or device (a version number is fine), so it is shown without the lock.
2. The Hub's job reply carries `step` (`index` K, `count` N, `text` the sentence) and `progress`: `(K - 1) / N`
   while step K runs, so the bar is never full while work remains, and `1` when the job has ended with exit 0. A
   failed job keeps the fraction of the step it stopped in. With no step line both are null.
3. Counted job: the step line reads "Step K of N: <sentence>" and the bar is determinate, with
   `aria-valuetext` "Step K of N". Not counted: the step line is the newest log line and the bar is indeterminate.
4. After 10 seconds in one step (or in a job that is not counted) the step line ends with the time in that step,
   "… (42 s)", then "(2 min 10 s)"; it is not announced.
5. The command line prints the same sentences as its progress lines (`06-command-line.md` section 6.6), because the
   same commands write them.

**Sizes and tokens.** Fixed at the bottom right, `--s4` from the edges plus the safe-area insets; width
`min(25rem, 100vw - 2 * var(--s4))`; `--surface`, 1 px `--border-strong`, `--r`, `--e0` (its outline sets it apart;
foundations §4.3 keeps `--e2` for dialogs, sheets, menus and toasts). Head min height
`calc(var(--s7) + var(--s2))`, padding `var(--s1) var(--s1) var(--s1) var(--s4)`;
title `--fs-m` weight 600; step line `--fs-s` `mono` `--muted`, one line with ellipsis. Bar `--s1` high, square ends.
Log max height `calc(var(--s7) * 4)`, `--code` ground, 1 px `--border` above, `--fs-s`/1.65 `mono`, wraps. Phones:
left and right `--s2`, bottom above the bottom bar (`calc(var(--tab) + env(safe-area-inset-bottom) + var(--s2))`).

**States.**
- Default (running): Running badge, bar moving, Hide shown.
- Hover: buttons as 4.1.
- Focus: buttons as 4.1; the log is focusable for scrolling.
- Pressed: buttons as 4.1.
- Disabled: Show the whole log is disabled until the job has ended (reason "Available when the job has ended.").
- Loading: on page load, before `GET job` answers, nothing is shown.
- Error: polling fails during a job that restarts the Hub (`apply`, `update`, `rollback`, `restore`, `channel_*`):
  the Hub restarting state (8.5). Polling fails otherwise: a `--warn` line "Lost touch with the Hub; still trying…"
  under the head, polling continues.
- Done / Failed: badge and end line; bar full (`--bad` when failed); Close shown.

**Behaviour and keyboard.**
1. **Start.** The button that starts a job shows its result "Backing up… follow it in the job panel." and the strip
   appears without taking focus. The Hub runs one job at a time: starting another while one runs shows, at that
   button, "A job is already running: Backup. Wait for it to finish." (`--warn`).
2. **Follow.** `GET job?from=N` once a second while running; new log lines are appended; the log scrolls to the end
   unless the person has scrolled up in it.
3. **Hide and show.** Hide collapses the strip into the top-bar chip (wide screens) or a one-line bar (phones); the
   chip or bar opens it again with the log expanded. The log toggle (`aria-expanded`) shows and hides the log.
4. **End.** Badge and end line change, a toast repeats the end line, the starting control's result is updated
   ("Backup: done. It is at the top of the list."), and the end is announced. The strip stays until Close; Close
   hides strip and chip and moves focus to the page title.
5. **Whole log.** Show the whole log passes the lock and reads `POST job/log` page by page (`from` and `next`) until
   it stops growing, then replaces the log text.
6. **Reload.** A page loaded while a job runs (or has ended unseen) shows the strip again from `GET job`.

**Accessibility.** `section aria-label="Background job"`; the head's status text is in a `role="status"` area so the
start ("Backup started.") and the end ("Backup: done.") are announced, but not each step. The log `pre` has
`aria-label="Job log"` and `tabindex="0"`. The toggle has `aria-expanded` and `aria-controls`; Hide and Close have
names ("Hide the job panel", "Close the job panel").

**Theme profiles.** No change.

**Android.** The app starts no Hub jobs. Where it shows one, a `Card` docked above the `NavigationBar` with a
`LinearProgressIndicator` and a `TextButton` to expand the log.

**HTML.**
```html
<section class="job" id="job" aria-label="Background job" data-state="running">
  <div class="job__head">
    <div class="job__text" role="status">
      <span class="status status--run">…Running</span> <span class="job__title">Backup</span>
      <span class="job__step mono">Adding the Recently added photos (14.2 MB)</span></div>
    <button class="btn btn--ghost btn--icon" type="button" aria-expanded="false" aria-controls="job-log"
            aria-label="Show the job log">…</button>
    <button class="btn btn--ghost btn--icon" type="button" aria-label="Hide the job panel">…</button>
  </div>
  <div class="progress"><div class="progress__track" role="progressbar" aria-valuemin="0" aria-valuemax="100"
       aria-valuenow="60" aria-label="Backup progress"><span class="progress__fill"></span></div></div>
  <pre class="job__log" id="job-log" tabindex="0" aria-label="Job log" hidden></pre>
</section>
```

### 8.5 The Hub is restarting

**Purpose.** When a save or a job restarts the Hub, keep the page calm and useful: say so, pause writes, and come back
by itself when the Hub answers again.

**Anatomy.** The job strip (8.4) in its restarting form (on its own when no job is running): Running badge, title
"The Hub is restarting", line "This page comes back by itself.", indeterminate bar. The top-bar chip says the same.

**Sizes and tokens.** As the job strip.

**States.**
- Default (restarting): as above. Every control that writes to the Hub is `aria-disabled` with the reason "Wait for
  the Hub to come back." (the shell sets `data-state="restarting"` on the shell; components read it). Reading and
  moving around keep working with the data already loaded.
- Hover, focus, pressed: as the strip's buttons.
- Disabled: as described for write controls.
- Loading: it is a waiting state.
- Error (not back after 2 minutes): badge Needs a look, title "The Hub has not come back after 2 minutes", line "Check
  that the Hub computer is on. At the Hub: `spoolwarden status`." and **Reload the page** (default). Asking continues
  in the background.
- Back: badge Done, "The Hub is back." for 5 s, then the strip hides (unless a job is shown); writes are enabled
  again; the result that started it is updated ("Saved. The Hub restarted.").

**Behaviour and keyboard.** Starts when a save replies `restarts: true`, or when polling fails during a job that
restarts the Hub. The page asks `GET state` every 2 s. When the Hub answers with the same `version`, the page carries
on (no reload; open forms and their edits are kept). When the `version` differs (after an update or a roll back), the
page keeps the values of every dirty form, never secrets, as a draft (5.11, "Drafts": a form without `data-draft`
uses its `id` as the draft name for this one reload), reloads to get the new files, and then shows the toast
"Spoolwarden is now 0.6.0." and, for each kept form, the restore banner of 5.11. The reload drops the unlock held in
memory: a Hub page that was Unlocked comes back Locked (a Trusted computer stays trusted), so the next write asks
for the setup code again (3.2); the toast says so: "Spoolwarden is now 0.6.0. Enter the setup code again to make
changes." Any other request that fails with no answer while no restart is expected shows the banner "Cannot reach
the Hub." (8.8) instead.

**Accessibility.** The start ("The Hub is restarting. This page comes back by itself.") and the return ("The Hub is
back.") are announced through the strip's status area. Disabled write controls keep focus and say why.

**Theme profiles.** No change.

**Android.** The app's connection state on the Home screen ("Connecting…") covers it; no separate component.

**HTML.**
```html
<section class="job" aria-label="Background job" data-state="restarting">
  <div class="job__head"><div class="job__text" role="status">
    <span class="status status--run">…Running</span> <span class="job__title">The Hub is restarting</span>
    <span class="job__step">This page comes back by itself.</span></div></div>
  <div class="progress progress--indeterminate" aria-hidden="true">
    <span class="progress__track"><span class="progress__fill"></span></span></div>
</section>
```

### 8.6 Inline result

**Purpose.** Answer where the question was asked (foundations §1 principle 3): the outcome of a button, a save, a test
or a check, next to the control, in words.

**Anatomy.** A container (`result`, `role="status"`) placed under the control, in the item's result row (6.1), or in a
form group's foot. Content: a status shape (or a spinner while working) and one sentence whose first words state the
outcome ("Test passed: 192.0.2.40 answers; its certificate matches the pinned one."; "Test failed: no answer from
192.0.2.41:8883. Check that it is on."; "Saved: Display name."; "Nothing changed."), optionally one action button
and a step bar (8.2). The action is a default `btn`, never primary, and never an action the item's main row already
shows (6.1, "Row actions"): the one primary of an item stays on its main row. Its kind changes as the work goes on, so it is a state:
`data-state` = `run`, `ok`, `bad`, `warn`, `info` or `neutral`.

**Sizes and tokens.** Plain (in a group foot or after a button): `--fs-m`, shape in the kind's colour, text `--text`.
Block (`result--block`, in result rows and under panels): the kind's soft ground (`--ok-soft`, `--bad-soft`,
`--warn-soft`, `--info-soft`; neutral `--surface-2` with 1 px `--border`), `--r`, padding `var(--s2) var(--s3)`, gap
`--s2`, the action at the end (wrapping below on phones). Values in `mono`.

**States.**
- Default: empty (takes no space).
- Hover, focus, pressed: as its action button.
- Disabled: not applicable.
- Loading (run): spinner and the progress sentence ("Saving…", "Mapping… step 2 of 4").
- Error (bad): octagon and the failure sentence with what to do; never cleared by a timer. When the Hub or a
  printer refuses (a printer refusing Pause, Stop or the light included), the sentence is the `message` of the Hub's
  reply, shown as sent; without a `message`, the Hub's `error` text; without either, the interface's own sentence for
  that action ("Workshop X1 did not accept Pause. Try again."). A raw reply is never shown: no JSON, braces, quotes or
  bare codes.

**Behaviour and keyboard.** A finished result (`ok`, `bad`, `warn`, `info`, `neutral`) ends with the time it was
written, as a `time` element in `--muted` (" · 14:05", the full date in its tooltip, 4.3), so an old result is never
taken for a new one. A result stays until the next action on the same thing replaces it, or until the person
leaves the section; then it is cleared, so no stale result is waiting on return. Writing a new result first empties
the container, so the same words are announced again. A result never moves focus.

**Accessibility.** `role="status"` (polite) on a container that exists before the result is written. Because the
sentence starts with the outcome, no hidden prefix is needed. Shapes are `aria-hidden`.

**Theme profiles.** No change in look. `collection` = rows: an item's result appears at the top of its detail
instead of under the row.

**Android.** A small `ResultLine` composable (icon and `Text`) under the control; never a dialog.

**HTML.**
```html
<p class="result result--block" role="status" data-state="bad">
  <svg class="status__shape" aria-hidden="true"><use href="#s-octagon"/></svg>
  <span><b>Test failed:</b> no answer from <span class="mono">192.0.2.41:8883</span>. Check that it is on.</span>
  <button class="btn" type="button" data-action="report">Collect a report</button>
</p>
```

### 8.7 Toast

**Purpose.** Tell the outcome of something whose control is gone (a printer forgotten, a found printer dismissed) or
that happened away from where the person is (unlock, lock, the end of a job).

**Anatomy.** A small floating message: status shape, one sentence, optionally one action ("Undo", "Show"), and a
close button when it has an action.

**Sizes and tokens.** Width `min(25rem, 100vw - 2 * var(--s4))`; `--surface`, 1 px `--border-strong`, `--r`, `--e2`;
padding `var(--s3) var(--s4)`, gap `--s2`, `--fs-m`. Wide screens: stacked at the top
right below the top bar (newest on top); phones: above the bottom bar and the job strip, full width minus `--s4`
gutters (newest at the bottom). Arrives over `--t` (fade and a `--s1` slide; fade only with reduced motion).

**States.**
- Default: visible for 5 s (10 s with an action), then leaves.
- Hover: the timer pauses while the pointer is over it.
- Focus: the timer pauses while its action has focus.
- Pressed: action as 4.1.
- Disabled: not applicable.
- Loading: not applicable.
- Error: allowed only for outcomes with nothing to fix in place ("Backup: failed. See the job panel."); errors that
  need action are inline results or banners, never only a toast.

**Behaviour and keyboard.** At most three at once; a fourth replaces the oldest. A toast never takes focus. Every
toast action is also available in the page (Undo of a usage entry is in its list; Show opens the job strip from the
chip), so nothing depends on catching a toast in time.

**Accessibility.** The toast region is `aria-live="polite"`; each toast's sentence starts with the outcome. Its action
is a real button with a full name ("Undo: put 12 g back on spool 214").

**Theme profiles.** No change.

**Android.** `Snackbar` through `SnackbarHostState` with `SnackbarDuration.Indefinite`, dismissed by the host's own
timer after 5 s (10 s with an `actionLabel`), the same times as the web; the timer pauses while TalkBack focus is on
it.

**HTML.**
```html
<div class="toasts" aria-live="polite">
  <div class="toast"><svg class="status__shape" aria-hidden="true"><use href="#s-filled"/></svg>
    <span>Workshop X1 forgotten.</span></div>
</div>
```

### 8.8 Banner

**Purpose.** A lasting notice about a page, a group or the whole Hub page that the person should read before acting:
a feature is off, the Hub cannot be reached, an update is available, the last install stopped halfway, this address
is read-only, a backup is not encrypted, unsaved changes can be restored, the Hub's certificate changed (web app and
app).

**Anatomy.** Icon (info circle, warning triangle or error octagon), an optional bold title, one or two sentences, up
to two actions (one primary), and a Dismiss button for notices that may be dismissed. Placements: **global** (top of
`main`, for Hub-wide notices), **page** (under the page header), **inline** (`banner--inline`, inside a form group or
detail body; never dismissible).

**Sizes and tokens.** Variants `banner--info`, `banner--warn`, `banner--bad`, `banner--ok`, each on its soft ground
(`--info-soft`, `--warn-soft`, `--bad-soft`, `--ok-soft`), no border,
`--r`; padding `var(--s3) var(--s4)` (inline `var(--s2) var(--s3)`); icon in the kind's colour; text `--fs-b` (page and
global) or `--fs-m` (inline) in `--text`; title weight 650. Actions at the end on wide screens, below on phones.

**States.**
- Default: as above.
- Hover, focus, pressed: as its buttons.
- Disabled: not applicable.
- Loading: an action that checks something shows its spinner (4.1).
- Error: the `--bad` kind is itself the error form ("Cannot reach the Hub. Check that it is on; this page tries again
  every 10 s." with **Try now**).

**Behaviour and keyboard.** At most two page or global banners at once, the most serious first. Dismiss hides a
banner and remembers it per device (`spoolwarden.dismissed.<notice>`); it comes back when its content changes (a
newer version). Banners for conditions that must be fixed (Hub unreachable, certificate changed) have no Dismiss.
A banner leaves by itself when its condition ends.

**Accessibility.** A banner present when the page opens is plain content. A banner that appears later is announced:
`role="alert"` for the `--bad` kind, `role="status"` for the others. Icons are `aria-hidden`; the sentence says the
kind in words.

**Theme profiles.** No change.

**Android.** One `NoticeCard` composable (a `Card` with `errorContainer`, `tertiaryContainer` or `secondaryContainer`
colours and `TextButton`s) used for every notice, including the certificate-changed and no-longer-paired notices
that each screen draws today.

**HTML.**
```html
<div class="banner banner--warn" role="status">
  <svg class="icon" aria-hidden="true"><use href="#i-warning"/></svg>
  <p class="banner__text"><b>Slicer presets is switched off.</b> Turn it on in Features to build presets for Bambu
    Studio and Orca Slicer.</p>
  <div class="actions"><a class="btn btn--primary" href="#features">Open Features</a></div>
</div>
```

---

## 9. Dialogs and sheets

### 9.1 Dialog (confirm, destructive, typed word, text entry)

**Purpose.** Ask before an action that matters, or ask for a short input, in the page's own style. Replaces every
`alert()`, `confirm()` and `prompt()` (foundations §12 rule 4).

**Anatomy.** `dialog` with head (title `h2`, Close icon button), body (sentences, fields), foot (Cancel and the
confirming button). Kinds:

| Kind | Title | Body | Buttons | Focus on open |
|---|---|---|---|---|
| Confirm | A question naming the thing: "Map the slots of Workshop X1?" | The consequence: "The printer changes its slot colours briefly and runs a job with no motion; the colours are put back." | Cancel · **Map slots** (primary) | The confirming button |
| Destructive | "Forget Workshop X1?" | What is lost and whether it can be undone: "Spoolwarden stops connecting to it and deletes its Access Code. To use it again, add it again." | Cancel · **Forget printer** (`btn--danger btn--solid`) | Cancel |
| Destructive with a typed word | "Restore this backup?" | The consequence ("Backup of <host> made <created>. This replaces the spools, settings, printers and pairings on this Hub. What is here now is saved as a backup first. The Hub restarts, and afterwards the setup code is the one from the backup.") and a field "Type restore to go on" | Cancel · **Restore** (`btn--danger btn--solid`), disabled until the field holds the word | The field |
| Text entry | "Rename printer", "Change address: Workshop X1", "Replace Access Code: Workshop X1" | One or more fields (5.2 to 5.4), prefilled with the current value and selected; a secret field (5.3, "Replace Access Code") is never prefilled and starts empty | Cancel · the verb (**Rename**, **Change address**) as primary | The first field |
| Information | "Saved reports: Workshop X1" | The content | **Close** (primary) | Close |

One confirm is enough: no action asks twice in a row (stopping a print asks once, with the job named: title "Stop the
print?", body "Stop <job> on <printer>? It cannot be resumed.").

**Sizes and tokens.** Width `min(30rem, 100vw - 2 * var(--s4))`, wide (`dialog--wide`) `min(45rem, …)`; max height
`calc(100vh - var(--s7))`; `--surface`, 1 px `--border-strong`, `--r-l`, `--e2`; `::backdrop` `--scrim`. Head sticky,
padding `var(--s2) var(--s2) var(--s2) var(--s5)`, 1 px `--border` below, title `--fs-l` weight 650. Body padding
`var(--s4) var(--s5)`, gap `--s4`, text `--fs-b`. Foot padding `var(--s3) var(--s5) var(--s4)`, 1 px `--border` above,
buttons at the right, gap `--s2`. Opens over `--t-slow`. **Drawer** variant (`dialog--drawer`, the form container of
the `inline` profile): full height at the right edge, 420 px wide, no radius, 1 px `--border-strong` on its left,
slides in. **Phones**: every dialog is drawn as a bottom sheet (9.2): full width, top corners `--r-l`, max height
92 %, foot buttons sharing the row equally.

**States.**
- Default: as the kind.
- Hover, focus, pressed: as its controls.
- Disabled: the confirming button while the typed word does not match (reason "Type restore to go on.") and while a
  request is in flight.
- Loading: the confirming button shows its loading form ("Forgetting…"); fields become read-only; Escape and Close
  wait until the Hub answers.
- Error: field errors at the fields (5.1); other errors in a result line (8.6) above the foot; the dialog stays open
  and keeps what was typed.

**Behaviour and keyboard.** Opened with `showModal()` (the rest of the page is inert); Tab stays inside; Escape and
Close act as Cancel; Enter in a field submits. The typed word is compared after trimming, exactly as shown
("restore"). Confirming passes the lock (the unlock dialog opens on top and returns). On success the dialog closes,
focus returns to the control that opened it (or the page title if that control is gone), and the outcome appears in
that control's result area, or as a toast when the thing is gone. Closing a dialog holding a dirty form asks first,
except a text-entry dialog with a single field (5.11).

**Accessibility.** `dialog` with `aria-labelledby` its title and `aria-describedby` its consequence sentence;
destructive kinds use `role="alertdialog"`. The confirming button names the action, never "OK" or "Yes".

**Theme profiles.** Form containers (Add a printer, Restore) are moved into a host as 6.2 says: `detail` = card:
the form host, a wide dialog. `detail` = sheet: the detail host, a sheet; confirm and destructive dialogs stay
dialogs. `detail` = inline: the drawer host. `detail` = pane: no host; they open in the pane. `nav`, `collection`:
no change.

**Android.** By window width, as the web's phone rule: on medium width and up, `AlertDialog` for confirm and
destructive (confirm button in error colours), and `BasicAlertDialog` holding a form for typed word (with an
`OutlinedTextField`) and text entry; on compact width, every kind as a `ModalBottomSheet` (9.2) with the same title,
body and buttons; long forms as a full-screen `Dialog`.

**HTML.**
```html
<dialog class="dialog" role="alertdialog" aria-labelledby="forget-title" aria-describedby="forget-text">
  <div class="dialog__head"><h2 class="dialog__title" id="forget-title">Forget Workshop X1?</h2>
    <button class="btn btn--ghost btn--icon" type="button" data-action="cancel" aria-label="Close">…</button></div>
  <div class="dialog__body"><p id="forget-text">Spoolwarden stops connecting to it and deletes its Access Code. To use
    it again, add it again.</p></div>
  <div class="dialog__foot">
    <button class="btn" type="button" data-action="cancel">Cancel</button>
    <button class="btn btn--danger btn--solid" type="button" data-action="confirm">Forget printer</button>
  </div>
</dialog>
```

### 9.2 Bottom sheet

**Purpose.** On phones, the container for anything that would float on a wide screen: the More sections, long menus,
dialogs, the Settings group list, and details in the `sheet` profile. It sits where the thumb is.

**Anatomy.** A handle (decorative bar), head (title, Close), body (scrolls), optional foot (stays visible).

**Sizes and tokens.** Full width, max height 92 % of the viewport (details in the `sheet` profile: from `--top` to the
bottom); `--surface`, top corners `--r-l`, `--e2`, `--scrim` behind; handle `calc(var(--s6) + var(--s1))` by
`--s1`, `--border-strong`, centred, `--s2` margin; bottom padding adds the safe-area inset. Rises over `--t-slow`.

**States.**
- Default: open at its content height (up to the maximum).
- Hover, focus, pressed: as its controls.
- Disabled: not applicable.
- Loading: the body shows a skeleton.
- Error: the body shows the error state (10.2).

**Behaviour and keyboard.** Opened with `showModal()`; focus moves to the first item or field. It closes with Close,
Escape, a tap on the scrim, or a downward swipe that starts on the handle or head (more than a third of its height,
or a quick flick); the swipe always has the Close button as its equivalent. When the on-screen keyboard opens, the
sheet shrinks to stay above it (`visualViewport`). Focus returns to the opener on close.

**Accessibility.** As a modal dialog: labelled by its title; the handle is `aria-hidden`.

**Theme profiles.** `detail` = sheet: the detail host (`sheet--detail`, 6.2) is this sheet; it holds details and
form containers on phones, and on wider screens is drawn as the side sheet of 6.2. `nav` = list: Panes uses drill-in instead of the More sheet. `collection`: no change.

**Android.** `ModalBottomSheet` with `BottomSheetDefaults.DragHandle()`.

**HTML.**
```html
<dialog class="sheet" aria-labelledby="sheet-title">
  <div class="sheet__handle" aria-hidden="true"></div>
  <div class="sheet__head"><h2 class="sheet__title" id="sheet-title">Actions for Workshop X1</h2>
    <button class="btn btn--ghost btn--icon" type="button" data-action="close" aria-label="Close">…</button></div>
  <div class="sheet__body">…</div>
</dialog>
```

---

## 10. Page states

### 10.1 Empty state

**Purpose.** Say why a place is empty and what to do, instead of a blank area.

**Anatomy.** Icon in a soft disc, title, one sentence, actions (at most one primary and one secondary). Kinds:

| Kind | Example title | Sentence | Actions |
|---|---|---|---|
| First use | "No printers yet" | "Printers on the network appear here once they announce themselves." | **Add a printer**, Find Klipper printers |
| Feature off | "Slicer presets is switched off" | "Turn it on in Features to build presets for Bambu Studio and Orca Slicer." | **Open Features** |
| Nothing matches | "No spools match "galaxy"" | "Check the spelling, or search by brand, material or colour." | Clear search |
| All done | "Nothing to check" | "Every record was read with high confidence." | Show all |
| Nothing chosen (`pane`) | "Choose a printer" | "Its slots, facts and actions appear here." | none |

**Sizes and tokens.** Centred; padding `var(--s7) var(--s5)`; gap `--s2`; disc `calc(var(--s7) + var(--s2))`,
`--accent-soft`, icon `icon--l` `--accent-text`; title `--fs-l` weight 650; sentence `--muted`, at most 60ch wide.
In a collection: a panel with 1 px dashed `--border`, `--r`.

**States.**
- Default: as above.
- Hover, focus, pressed: as its buttons.
- Disabled: not applicable.
- Loading: never shown while loading (the skeleton is shown).
- Error: not applicable (10.2 is separate).

**Behaviour and keyboard.** Appears in place of the items when there are none; replaced as soon as one arrives.

**Accessibility.** The title is a heading at the level below the page title. A "nothing matches" state reached by
typing is announced by the collection's result area ("No spools match").

**Theme profiles.** `collection` = tiles: drawn as one wide tile; rows: inside the grouped block; table and cards: the
dashed panel. `detail` = pane: the nothing-chosen kind fills the pane. `nav`: no change.

**Android.** A custom `Column` (icon, `titleMedium`, `bodyMedium`, `Button`).

**HTML.**
```html
<div class="empty">
  <span class="empty__disc" aria-hidden="true"><svg class="icon icon--l"><use href="#i-printer"/></svg></span>
  <h2 class="empty__title">No printers yet</h2>
  <p class="empty__text">Printers on the network appear here once they announce themselves.</p>
  <div class="actions"><button class="btn" type="button" data-action="find">Find Klipper printers</button>
    <button class="btn btn--primary" type="button" data-action="add">Add a printer</button></div>
</div>
```

### 10.2 Error state

**Purpose.** When a region's data could not be loaded, say so in plain words, say what to do, and offer to try again.
Technical text is available but not in the way.

**Anatomy.** Octagon in a soft disc, title ("Could not load the printers"), one sentence with the cause in plain words
and what to do ("The Hub did not answer. Check that it is on, then try again."), **Try again** (primary), and a
"Details" disclosure with the Hub's own message and the request in `mono` (for a report).

**Sizes and tokens.** As the empty state, disc `--bad-soft`, icon `--bad`. Details: `--fs-s` `mono` on `--code`,
`--r-s`, padding `--s2`.

**States.**
- Default: as above.
- Hover, focus, pressed: as its controls.
- Disabled: not applicable.
- Loading: Try again shows "Trying…"; the skeleton returns in its place until the answer.
- Error: it is the error form.

**Behaviour and keyboard.** Scope is the region that failed (a collection, a detail body, a form group); the rest of
the page keeps working and keeps its input. Regions that refresh by themselves retry on their own after 2, 4, 8 and
then every 30 s and say "Trying again…"; others wait for Try again. A Hub that cannot be reached at all shows the
global banner (8.8) instead of an error state in every region. In the web app and the app, "no longer paired" and
"certificate changed" are banners with **Pair again**, not error states.

**Accessibility.** When it replaces content after the person acted (a retry), its container has `role="alert"`;
otherwise it is plain content. Details is a native `details` and `summary`.

**Theme profiles.** No change, other than taking the shape of the region it replaces (a tile, a pane).

**Android.** A custom `Column` like the empty state, with `OutlinedButton` "Try again"; or the `NoticeCard` (8.8) for
connection problems.

**HTML.**
```html
<div class="error-state" role="alert">
  <span class="error-state__disc" aria-hidden="true"><svg class="status__shape"><use href="#s-octagon"/></svg></span>
  <h2 class="error-state__title">Could not load the printers</h2>
  <p class="error-state__text">The Hub did not answer. Check that it is on, then try again.</p>
  <button class="btn btn--primary" type="button" data-action="retry">Try again</button>
  <details class="error-state__details"><summary>Details</summary><pre class="mono">…</pre></details>
</div>
```

### 10.3 Loading skeleton

**Purpose.** Make a page usable and stable before its data arrives (foundations §1 principle 9): the layout is
drawn at once and nothing jumps when data lands.

**Anatomy.** Plain blocks in the shape of the content they stand for: text lines (60 to 90 % of the width), title
lines, badge widths, swatch squares, and the item shapes of the current collection profile (table rows, cards, tiles,
rows), five items long; detail bodies show their section headings with lines under them.

**Sizes and tokens.** Blocks `--surface-2` on `--surface` (`--surface-3` on `--surface-2`), radius `--r-s`, each
line exactly one text line high so the real text takes the same space. Static: no shimmer (foundations §11).

**States.**
- Default: shown while waiting.
- Hover, focus, pressed: not applicable (skeletons are not focusable).
- Disabled: not applicable.
- Loading: it is the loading state. After 10 s a line appears under it: "Still loading… The Hub is slow to answer."
  with Try again; after 30 s it becomes the error state (10.2) "The Hub did not answer in 30 s."
- Error: replaced by the error state.

**Behaviour and keyboard.** Part of the page's first HTML, so it shows at first paint; replaced in place, item by
item, when data arrives. Static text (titles, labels, buttons that do not depend on data) is never a skeleton.

**Accessibility.** The waiting region has `aria-busy="true"` and one `sr` text ("Loading printers…"); the blocks are
`aria-hidden`. When the data is in, `aria-busy` is removed; the content is not announced.

**Theme profiles.** Its item shapes follow `collection`; detail bodies follow `detail`. `nav`: no change.

**Android.** Placeholder `Box`es in `surfaceContainerHighest` in the shape of the content (no Material 3 component; no
shimmer).

**HTML.**
```html
<div class="coll coll--printers" role="table" aria-label="Printers" aria-busy="true">
  <span class="sr">Loading printers…</span>
  <div class="coll__item skeleton" aria-hidden="true">
    <span class="skeleton__line skeleton__line--title"></span><span class="skeleton__line"></span>
  </div>
  …
</div>
```

---

## 11. Problems of the current interfaces and where they are solved

The current Hub page (served at `/setup` today), the web app and the Android app have these known problems. Each one a
component can solve is solved by the component named. The command line's problems are handled in
`06-command-line.md`.

| Problem in the current interfaces | Solved by |
|---|---|
| Saving one setting redraws the whole tab and loses other unsaved edits | Form group: only changed values are sent and nothing else is redrawn (5.11); collections and details patch in place and never replace a focused or edited field (6.1, 6.2) |
| Settings is one long page of eight cards with about thirteen Save buttons and no way to jump | Form groups with one Save each (5.11) and the Settings sub-navigation with unsaved marks (6.4) |
| Many equal-weight buttons in a row; destructive "Forget" looks like "Test" | Buttons and the one-main-action rule, the Remove zone (4.1), overflow menu (4.2), detail region layout (6.2) |
| Browser `confirm()` and `prompt()` for destructive actions, names, addresses and secrets | Dialogs: confirm, destructive, typed word, text entry (9.1); secret field (5.3) |
| Results appear as plain text boxes away from the control, are not announced, and stay stale on return | Inline result in place, announced, cleared on leaving (8.6); toast when the control is gone (8.7) |
| Status words differ per place ("set", "on", "OK", "needs a look", "connected") and some are colour only | One vocabulary of sixteen words with shapes (7.1) |
| The setup code sits in a header field and fails far away; reads need extra "Show" presses; the trust offer appears after an unrelated action | Lock chip with visible state (3.1); unlock dialog in place with the pending change named and "Trust this computer" in it (3.2); reads that need the code load by themselves once unlocked, and show a locked placeholder or hidden-values note with **Unlock to show** while Locked (1.4) |
| Results carry no time, so an old "Saved." looks new | Every finished inline result ends with its time (8.6) |
| Android: the security switch "Skip the fingerprint check" sits at the bottom of the first pairing screen with only a small explanation | Toggles that guard security: worded "Check the fingerprint when pairing by address" (On is safe), own "Security" heading, full-size risk hint, destructive dialog to turn off, Needs a look while off (5.6) |
| Muted grey is the main text style; warnings such as "the backup is not encrypted" are easy to miss | Page header (2.6) and inline banners for warnings (8.8) |
| Inputs labelled only by placeholders; no focus styles; no live regions; tabs without semantics | Field rules (5.1), focus rings in every component, the announcer and result areas (1.4, 8.6), navigation semantics (2.3) |
| Nine tabs scroll sideways on phones with no cue; a large sticky area | Phone bottom bar and More sheet (2.4, 2.5) |
| Lists such as stations asking to pair never refresh; "Checking…" never times out | Collection live updates (6.1); skeleton with a 10 s and 30 s limit (10.3); error state with retry (10.2) |
| One job panel at the top of the page while start buttons are far below; the generic title "Working" | Background-job strip visible on every page, with a title per job (8.4), and the start button's own result (8.6) |
| Sections look broken when their feature is off; the web app's tabs differ by address and feature | Dimmed navigation items that still open (2.3), feature-off empty state (10.1), feature-off banner (8.8) |
| Dry runs and results shown as long raw text | Before-and-after change list, one group per spool (7.9); key-value list (6.3) |
| The add button just goes disabled with a small line, or no explanation at all | Disabled buttons always show their reason (4.1) |
| Sixteen ungrouped inputs per spool; required and optional not told apart; colour typed as hex only | Grouped key-value and fields (6.3, 5.11), the "(optional)" rule (5.1), swatch next to the colour (7.3) |
| Print state shown as a raw word in one neutral pill; progress a thin unlabeled bar | Status badge (7.1), determinate bar with a label (8.3) |
| Results of printer commands land below the camera, off screen | Inline result next to the control (8.6) |
| Touch targets of 24 to 35 px; checkboxes that toggle only on the box | 44 px hit areas in every component (1.2), whole-row checkboxes and toggles (5.8, 5.6) |
| No skeletons; live polling redraws blocks and resets input | Loading skeleton (10.3); in-place updates (6.1) |
| Pause, Resume and Stop print side by side with equal weight | One-main-action rule and destructive placement (4.1), destructive dialog (9.1) |
| Dark mode follows the system only; browser bar colour fixed | Appearance control with `theme-color` following it (3.3) |
| Thumbnails with alt text "photo 0" | Photo thumbnail and viewer names (7.6) |
| Work in the web app is lost on reload | Form drafts (5.11) |
| Android: a flat stack of six buttons with no rule for emphasis | One-main-action rule (4.1) |
| Android: no persistent navigation; Back in different places | App shell with navigation bar or rail (2.1, 2.3, 2.4) |
| Android: printer screens are not real destinations | Detail region as a navigation route (6.2) |
| Android: the spool card is a dialog holding ten flows; Back discards typed weights | Detail region as a sheet with steps (6.2, 8.2), unsaved-changes guard (5.11) |
| Android: certificate-changed and no-longer-paired notices drawn five different ways | One banner component (`NoticeCard`, 8.8) |
| Android: no snackbar, success shown as Done/OK screens, mixed loading styles and "..." | Toast as `Snackbar` (8.7), one spinner and bar (8.1, 8.3), "…" as one character (1.4) |
| Android: hard-coded status colours that ignore dark mode | Status badge colours from tokens (7.1) |
| Android: search runs as you type and also has a Search button, with no progress | Search field rule: searches after a pause, no button, spinner in the field (5.2) |
| Android: no layout for tablets | Breakpoints as window size classes (1.3); rail, panes and grids per profile (2.3, 6.1, 6.2) |

---

## 12. Needs from the Hub

The components above work with the Hub as it is, except for these. Until each exists, the interim behaviour named
here applies.

| Need | Used by | Until then |
|---|---|---|
| Save several settings of one group in one request, all or nothing, replying with per-key errors and one `restarts` / `applies` answer. Today `POST settings/general` takes one `{key, value}` at a time. | Form group (5.11) | The page sends the changed keys one at a time in the order of 5.11 (plain keys, then apply keys each after its job ends, then restarting keys each after the Hub is back), stops at the first error, and says which were saved |
| Check a setup code without making a change (reply: right, wrong, or too many tries) | Unlock dialog (3.2) | `POST overview` with the code, a read that needs it |
| Per-field confidence of the Label Reader (high, medium, low, not on the label) in the `read` reply and in `GET intake/history/<id>` (web app `GET history/{id}`) | Confidence display (7.2) | A field the reader marks as estimated shows Medium; a field without a value shows Not on the label; all others count as High; Low is not shown |
| Store and report the theme for new devices (in `GET state`, and a setting to change it) | Theme picker (3.4) | The "Theme for new devices" group is hidden |
| QR codes as an image the page can load with `<img src>` (an image URL), always available on the Hub (not dependent on an optional system tool) | QR block (7.8) | The SVG text from `POST pair` and `GET webapp` is shown through a Blob URL, which needs `blob:` added to the image sources of the Content-Security-Policy; when the Hub sends no QR, the code and link are shown alone |
| One-line live summaries for every navigation section (for example in `GET state` or `GET overview`) | Navigation summaries and More sheet (2.3, 2.5) | Summaries are built from the replies the page already loads; a section without data shows no summary |
| Small versions of label photos (for 44 px and 96 px thumbnails) | Photo thumbnail (7.6) | Thumbnails load the full photo |
| `offset` (or a page number) on spool and filament searches (`GET find`, `GET filaments?q=`) that today stop at a fixed count and report `truncated` | Collection paging (6.1) | The first page is shown with "Showing the first 60. Narrow the search to see others." |
| Error replies that name the field they concern (a `field` key beside `error`) | Field errors from the Hub (5.1) | The error is shown in the form's result area |
| Every refusal reply carries `message`, one sentence for people that says what was refused and what to do; for a printer that refuses a command, the Hub turns the printer's answer into that sentence, so every interface shows the same words | Inline result (8.6), the printer controls of `04-web-app.md` 6.4 and `05-android-app.md` 9.4, errors of `06-command-line.md` 6.5 | Each interface shows the reply's `error` text, or its own sentence for that action (8.6); never the raw reply |
