# Spoolwarden design: foundations

This is the base of the Spoolwarden design system: the principles, the names, the design tokens, the appearance
switch (Light / Dark / System) and the Themes feature. Every other document in this folder builds on it. Where
another document and this one disagree, this one wins.

Contents: 1 Principles · 2 Names · 3 The four interfaces · 4 Tokens · 5 Appearance (Light / Dark / System) ·
6 Themes · 7 Layout and breakpoints · 8 Navigation · 9 Type · 10 Icons · 11 Motion · 12 Hard rules for every page

---

## 1. Principles

Judged in this order, always: **1. it works, 2. it is easy, 3. it is secure without getting in the way of 1 and 2.**

1. **Show the state, then the action.** Every screen opens on what is true now (connected, offline, 62 % left, as
   detected) and offers the one thing most people do next. Everything else is one step away, not on the surface.
2. **One main action per thing.** A printer, a spool, a record or a settings group has at most one filled button.
   Other actions sit in a menu or a quiet row. Destructive actions are kept apart and always ask first.
3. **Answer where the question was asked.** The result of a button appears next to that button (or as a short
   toast), in words, and is announced to screen readers. Never a block of raw text somewhere else on the page.
4. **Never lose what was typed.** Saving one field does not redraw others. Leaving a form with unsaved edits asks.
   A failed save keeps the edits and says what to change.
5. **Plain words.** Name things by what the person does with them (section 2). A button says what happens
   ("Forget printer", not "OK"). An error says what went wrong and what to do next.
6. **Same thing, same place, on every device.** The Hub page, the web app and the Android app use the same tokens,
   the same components, the same words and the same order of things. A person who learned one knows the others.
7. **Works at arm's length and with gloves off the keyboard.** Touch targets are at least 44 px (48 dp on Android),
   status is never told by colour alone, and everything is reachable by keyboard.
8. **Security is offered, not imposed.** The lock, the setup code, trusted computers and fingerprint checks are
   shown as a state with a one-sentence explanation and a clear way to use or relax them. No nagging, no extra
   step the owner cannot switch off.
9. **Fast and offline.** Pages are served by the Hub on the home network: no downloads at run time, system fonts,
   one small stylesheet, no build step. A page is usable before any data has arrived (skeleton, then data).
10. **Dense by default, never cramped.** The default look (Console) shows a lot at once for people who keep it
    open beside their printer; spacing, alignment and type stay on the scale in section 4 so density reads as
    order. People who want it roomier pick another theme (section 6).

## 2. Names

The product is **Spoolwarden**. Parts are named by what a person does with them. Use these words in every label,
message, help text and document. The middle column is what the code and older documents call the same thing.

| Name in the UI | Was | Meaning |
|---|---|---|
| **Spoolwarden** | filament-kit | The whole product |
| **the Hub** | the server, "the kit" | The home computer that runs Spoolwarden |
| **Hub page** | setup page, setup console | The web page served by the Hub for status, printers, history and settings |
| **web app** | phone web app, `/intake` | The page for phones in a browser (iPhone, or any phone) |
| **app** | Android app | The native Android app |
| **`spoolwarden` command** | `filament-kit` command | The command line on the Hub |
| **Features** | modules | Parts of Spoolwarden that can be switched on and off |
| **Setups**: Hub · Weigh Station only · Hub with Weigh Station | modes: server · station · all-in-one | What a machine is |
| **Weigh Station** | intake station | USB scale and tag reader where new spools are weighed and tagged |
| **Weigh Station display** | intake panel | The small screen on the Weigh Station |
| **Tag Reader** | Printer Station, bench reader, NFC reader | A small NFC reader, usually at a printer |
| **Label Reader** | AI intake, Local AI intake | Reads a spool's label from a photo. Two engines: **Cloud (Claude)** and **On this Hub** |
| **Add spools** | intake (the action) | Adding spools to the inventory |
| **Recently added** | intake history | The newest additions with their photos; correct or undo them here |
| **Klipper add-on** | printer pack | Macros and Moonraker settings installed on a Klipper printer |
| **Filament Catalog** | filament library | The catalog of known filaments and their settings |
| **Slicer presets** | presets | Filament presets built for Bambu Studio and Orca Slicer |
| **Slicer Sync** | PC sync | The small tool on the PC that writes Slicer presets |
| setup code · Access Code · API key · Spoolman · slot · spool | unchanged | Already plain, or another product's own word |

Rules for wording: sentence case everywhere ("Add a printer"); no internal words (module, unit, endpoint, job id);
numbers with units and a space ("210 °C", "1000 g", "4,812 KiB"); dates as `2026-11-12 14:05` in tables and logs and
as relative words in summaries ("3 minutes ago") with the exact time on hover or long-press.

## 3. The four interfaces

| Interface | Runs on | Used for | Look |
|---|---|---|---|
| **Hub page** | Any browser on the home network (computer, tablet, phone) | Setting up and running the Hub | This design system, all four themes |
| **web app** | Phone browser (Safari on iPhone; installable to the home screen) | Add spools, open a spool, printers, Recently added, Slicer presets | This design system, same tokens and components, phone and tablet layouts |
| **app** | Android phone or tablet | Same tasks as the web app, plus camera and NFC | The same tokens mapped onto Material 3 (see `08-platform-mapping.md`) |
| **`spoolwarden` command** | Terminal on the Hub | Everything, as the fallback | Same words, same status vocabulary, same order of fields (see `06-command-line.md`) |

A feature offered in one interface is offered in all four where the device can do it. Where it cannot (a phone
cannot flash a board over USB), the interface says in one line where to do it instead.

## 4. Tokens

Tokens are the only place colours, sizes and timings are written. Components use tokens; they never contain a
literal colour or size. The machine-readable source is `tokens/tokens.json`; `tokens/tokens.css` (web) and the
Kotlin theme (Android) are generated from it or kept equal to it by a test.

Token names are the same in every theme. A theme (section 6) supplies the values. The values below are the
**Console** theme, which is the default.

### 4.1 Colour

| Token | Role | Console light | Console dark |
|---|---|---|---|
| `--bg` | Page ground | `#f3f5f6` | `#0b0f12` |
| `--surface` | Bars, cards, tables, inputs | `#ffffff` | `#11171c` |
| `--surface-2` | Hover, table header, quiet fill | `#eef1f3` | `#172027` |
| `--surface-3` | Pressed, selected row, track | `#e1e6e9` | `#212c34` |
| `--text` | Main text | `#10161b` | `#e3e9ed` |
| `--muted` | Secondary text, placeholders | `#545e68` | `#98a4ae` |
| `--border` | Hairlines between things | `#d6dce1` | `#253039` |
| `--border-strong` | Outlines of controls (3:1 against the surface) | `#7d8892` | `#66737e` |
| `--accent` | Fill of the main action, always behind a label in `--on-accent` | `#00788a` | `#3cccd8` |
| `--accent-hover` | Hover on accent fill | `#00636f` | `#6bdbe4` |
| `--on-accent` | Text and icons on `--accent` | `#ffffff` | `#04262b` |
| `--accent-soft` | Selected chip, active navigation ground | `#e0f2f4` | `#0e2a30` |
| `--accent-text` | Everything accent-coloured that stands on a surface: links, icons, marks, a checked box, a switch that is on, a progress fill | `#006474` | `#5fd6e0` |
| `--ok` / `--ok-soft` | Good state: text or icon / its ground | `#1a7a3c` / `#e3f3e8` | `#5ccf88` / `#0f2619` |
| `--warn` / `--warn-soft` | Needs attention | `#8a5700` / `#fbf0d5` | `#efb946` / `#2a210e` |
| `--bad` / `--bad-soft` | Error, destructive | `#b42519` / `#fbe7e5` | `#ff7d73` / `#311816` |
| `--on-bad` | Text on a filled `--bad` button | `#ffffff` | `#2b0704` |
| `--info` / `--info-soft` | Neutral notice, "revised by AI" | `#1d5fae` / `#e4eefa` | `#80b4ff` / `#122039` |
| `--focus` | Focus ring | `#0b7fa6` | `#6bdbe4` |
| `--scrim` | Behind dialogs and sheets | `rgb(12 18 22 / .5)` | `rgb(0 0 0 / .62)` |
| `--code` | Ground of logs and command blocks | `#f6f8f9` | `#0d1317` |

Rules:
- Semantic colours (`ok`, `warn`, `bad`, `info`) are separate from the accent and mean the same in every theme.
- `--accent` is only ever the fill of a part that carries its own label or icon in `--on-accent` (the main button,
  the chosen part of a segmented choice, the skip link). A theme may make it light, as Palette does, so it is never text, an icon, an
  outline, or a mark that has to be seen on its own against a surface. All of those use `--accent-text`, which is
  checked at 4.5:1 on `--bg`, `--surface` and `--surface-2` in every theme.
- Text pairs must reach 4.5:1: `--text`, `--muted`, `--accent-text`, `--ok`, `--warn`, `--bad`, `--info` on `--bg`,
  `--surface` and `--surface-2`; each semantic colour on its own `-soft` ground; `--on-accent` on `--accent`;
  `--on-bad` on `--bad`. Control outlines and focus rings must reach 3:1 against what is behind them. A test
  computes these from `tokens.json` for every theme in light and dark and fails the build when one drops below.
- On `--surface-3` (pressed and selected rows) only `--text`, `--muted` and `--bad` are used as text colours; links
  in a selected row are `--text`, underlined. `07-accessibility.md` section 3 lists every allowed pair with its ratio.
- Filament colours come from the data, not from tokens. A swatch always has a 1 px `--border-strong` outline (a
  white spool on a white card must still be visible) and is always accompanied by the colour's name or hex.

### 4.2 Type

| Token | Console | Use |
|---|---|---|
| `--sans` | `system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif` | Everything except data |
| `--mono` | `ui-monospace, "Cascadia Mono", "SF Mono", Menlo, Consolas, "Liberation Mono", monospace` | Addresses, serials, weights, temperatures, codes, logs |
| `--fs-xs` | 0.6875rem (11 px) | Navigation labels under icons, table header caps |
| `--fs-s` | 0.75rem (12 px) | Captions, badges, breadcrumbs |
| `--fs-m` | 0.8125rem (13 px) | Buttons, labels, table cells, secondary text |
| `--fs-b` | 0.875rem (14 px) | Body text, inputs on wide screens |
| `--fs-l` | 1rem (16 px) | Card titles, the product name, inputs on phones |
| `--fs-xl` | 1.25rem (20 px) | Page title |
| `--fs-2xl` | 1.5rem (24 px) | Big numbers (remaining weight, counts) |
| `--lh-body` / `--lh-title` | 1.45 / 1.25 | Line height of text / of titles |
| `--fw-text` / `--fw-label` / `--fw-title` | 400 / 600 / 650 | Weight of text / labels and buttons / titles |

Rules: sizes are in `rem` so the browser's or phone's text-size setting scales the whole page. Text inputs use
at least 16 px on phones (smaller makes iPhone Safari zoom the page on focus). Numbers that line up in columns use
`font-variant-numeric: tabular-nums`. No text below `--fs-xs`; nothing a person must read to act is below `--fs-m`.
No web fonts are downloaded; a theme may only choose among system font stacks.

### 4.3 Space, size, radius, elevation, motion

| Group | Tokens (Console values) |
|---|---|
| Space | `--s1` 4 · `--s2` 8 · `--s3` 12 · `--s4` 16 · `--s5` 24 · `--s6` 32 · `--s7` 48 (px). Only these steps. |
| Rhythm | `--row` (height of a collection row: 48 px in Console) · `--gap` (space between items of a group: `--s3` in Console). Themes set these two for density. |
| Control height | `--ctl` 40 px on wide screens, 44 px at 600 px and below. A control shorter than 44 px gets an invisible hit area that reaches 44 px. |
| Chrome sizes | `--top` 52 px (top bar) · `--rail` 76 px (navigation rail) · `--tab` 60 px (phone bottom bar, plus the safe-area inset) |
| Radius | `--r-s` 4 px (chips, small parts) · `--r` 6 px (controls, cards) · `--r-l` 10 px (dialogs, sheets) |
| Elevation | `--e0` none: things are separated by hairlines, not shadows. `--e2`: dialogs, sheets, drawers, menus and toasts only. |
| Motion | `--t-fast` 120 ms (hover, press) · `--t` 200 ms (menus, toasts, expanding rows) · `--t-slow` 320 ms (sheets, dialogs). Easing `--ease`: `cubic-bezier(.2, 0, 0, 1)`. With `prefers-reduced-motion: reduce` all three are 0 ms and spinners become a static "Working…" label. |

Density is a theme property: a theme sets `--ctl`, `--row` and `--gap`. It never changes the 44 px minimum hit area.

A few fixed dimensions are not steps of the space scale (the 420 px drawer, the 1 px hairline, the 3 px navigation
mark, thumbnail and QR sizes). Each is a named entry in the `size` group of `tokens.json` and is used by that name;
components still contain no bare numbers.

## 5. Appearance: Light, Dark, System

- Three choices: **Light**, **Dark**, **System** (follow the device). Default: System.
- It is a per-device choice, stored on the device (web: `localStorage` key `spoolwarden.appearance`; Android: the
  app's own settings store). It needs no setup code and no connection to the Hub.
- **Where it lives.** On wide screens: a three-part segmented control (sun, moon, half-circle icons with the words
  Light, Dark, System) at the right end of the top bar, always visible. On phones: one icon button in the top bar
  that opens a small menu with the three choices, and the same control as the first row of Settings > Appearance.
  In the Android app: Settings > Appearance, plus the same top-bar icon. The web app: the top-bar icon and its
  Settings sheet.
- **How it works on the web.** Light values are defined on bare `:root`. Dark values are defined twice with the same
  numbers: inside `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { … } }` and under
  `:root[data-theme="dark"] { … }`. System removes the `data-theme` attribute; Light and Dark set it. Each dark
  block sets `color-scheme: dark` so native controls and scrollbars follow. A four-line inline-free script in the
  page head (served as its own small file, loaded before the stylesheet paints) applies the stored choice so the
  page never flashes the wrong theme.
- The phone's status bar matches the page: two `theme-color` meta tags (light and dark) carry `--surface`, and the
  appearance script keeps them in step with an explicit choice. A web app manifest cannot follow a per-device
  choice, so the Hub serves a light and a dark manifest and the appearance script points the manifest link at the
  matching one.
- Photos, QR codes and filament swatches are not inverted in dark. QR codes keep a white quiet zone.
- Android: `isSystemInDarkTheme()` for System; the stored choice overrides it. See `08-platform-mapping.md`.
- The command line has no appearance switch; it follows the terminal (section in `06-command-line.md`).

## 6. Themes

A **theme** is a whole look. It is separate from Light / Dark / System: every theme has a light and a dark side.
Four themes ship; **Console is the default.**

| Theme | Character | Navigation on wide screens | Lists of things | Detail of one thing |
|---|---|---|---|---|
| **Console** (default) | Dense, technical, hairlines, monospace data, teal accent, 6 px radius | Icon rail with small labels | Table rows | Row expands in place; long forms open a side drawer |
| **Workbench** | Calm app shell, cards on a tinted ground, indigo accent, 12 px radius | Labelled sidebar (rail on tablets) | Cards in a grid | Card expands; dialogs for forms |
| **Palette** | Colour-led and roomy, spool rings, large type and buttons, warm amber accent, 20 px radius | Pill tabs in the top bar | Large tiles with a spool ring | Full-height sheet, one step at a time |
| **Panes** | Flat grouped lists like a phone's settings, green accent, 10 px radius | A list of sections in the left pane | Rows with a chevron | Its own pane (two or three panes side by side) |

On phones Console, Workbench and Spool use a bottom bar; Panes opens on the list of sections and drills in.

### 6.1 What a theme is made of

1. **A token set**: every token of section 4, for light and for dark. This alone gives colour, type, radius,
   elevation and density.
2. **A layout profile**: one choice from each of three fixed sets. Components are written once and read the
   profile; a theme never brings its own markup or script.

| Profile key | Choices | Console | Workbench | Palette | Panes |
|---|---|---|---|---|---|
| `nav` (wide screens) | `rail` · `sidebar` · `pills` · `list` | rail | sidebar | pills | list |
| `collection` | `table` · `cards` · `tiles` · `rows` | table | cards | tiles | rows |
| `detail` | `inline` · `card` · `sheet` · `pane` | inline | card | sheet | pane |

### 6.2 How a theme is applied

- Web: `<html data-look="console">` (or `workbench`, `palette`, `panes`). Missing or unknown means Console. One
  stylesheet holds the components; each theme adds a short block that redefines tokens under
  `:root[data-look="…"]` (light), and the two dark selectors of section 5 with `[data-look="…"]` added. Layout
  profiles are CSS only, keyed on the same attribute: the markup of the navigation, of a collection and of a detail
  region is identical in every theme (see `02-components.md`, "Navigation", "Collection" and "Detail region").
- Android: one `SpoolwardenTheme(look, appearance)` that supplies a Material 3 `ColorScheme`, `Shapes`,
  `Typography` and a density object per theme, and the `nav`, `collection` and `detail` choices as composition locals.
- The choice is per device, stored beside the appearance choice (web: `localStorage` key `spoolwarden.look`).
  It needs no setup code. The Hub can hold a **default theme** for devices that have not chosen
  (Settings > Appearance > "Theme for new devices"; `spoolwarden config theme <name>` on the command line).
- **Where it lives.** Settings > Appearance, under the Light / Dark / System control: four preview tiles, each a
  small drawing of the theme in its own colours with its name and one line ("Dense and technical", "Calm cards",
  "Colourful and roomy", "Simple lists"). Choosing applies at once, with no reload and no save button. The same
  group exists in the web app's settings sheet and the Android app's Settings screen.
- A theme never changes words, order of fields, what a button does, or which actions exist. It changes how the
  same things look and are laid out.

### 6.3 The other three token sets

The full values for Workbench, Palette and Panes, light and dark, are in `tokens/tokens.json` and shown in
`mockups/a-workbench.html`, `mockups/b-palette.html` and `mockups/d-panes.html`. Their light accents: Workbench
`#3949C0` (white text on it), Palette `#F59A2E` (dark text `#2A1806` on it; links and accent text use `#9A4700`),
Panes `#1b7a43` (white text on it). Palette uses a rounded system stack
(`ui-rounded, "SF Pro Rounded", "Segoe UI Variable Display", "Segoe UI", system-ui, …`) and a type scale one step
larger than Console; Workbench and Panes use `--fs-b` 0.9375rem (15 px) as body size.

### 6.4 Order of building

Console first, complete, with the `data-look` hook and the token structure in place. Then the Appearance group
with the theme picker showing Console only as selected and the others arriving one by one: Workbench (tokens plus
`sidebar` and `cards`), Palette (tokens plus `pills`, `tiles`, `sheet`), Panes (tokens plus `list`, `rows`, `pane`;
the most work, because of the drill-in navigation). See `09-implementation-order.md`.

## 7. Layout and breakpoints

| Name | Width | Layout (Console) |
|---|---|---|
| Phone | up to 600 px | Top bar, content in one column, bottom bar. Tables become stacked cards. Dialogs become bottom sheets. |
| Tablet | 601 to 1024 px | Top bar, navigation rail, content. Tables keep their most important columns; the rest move into the expanded row. |
| Desktop | over 1024 px | Top bar, navigation rail, content up to 1400 px wide. Full tables. A side drawer (420 px) for forms and detail. |

- No horizontal page scroll at any width down to 320 px. Only logs, command blocks and wide tables may scroll
  sideways, each inside its own box.
- Fixed bars add the device's safe-area insets (`env(safe-area-inset-*)`) to their padding.
- Content keeps a side gutter of at least `--s4` (16 px).
- Android: compact, medium and expanded window size classes correspond to phone, tablet and desktop.

## 8. Navigation

Hub page sections, in this order, in two groups:

| Group | Sections |
|---|---|
| Everyday | **Overview** · **Printers** · **Recently added** · **Devices** · **Slicer presets** |
| System | **Features** · **Settings** · **Flash a device** · **Updates** · **Logs** |

- Console, wide screens: icon rail, the two groups separated by a hairline; the active section has the soft accent
  ground, bold label and a 3 px mark at the rail's edge, and `aria-current="page"`.
- Phones: bottom bar with **Overview, Printers, Recent, Settings, More**. "More" opens a sheet listing the other
  six with their icons and one-line live summaries. Every section is reachable in at most two taps.
- A section that is switched off in Features stays in the navigation, dimmed, and opens a page that says so with a
  button to Features. Sections never vanish (people look for them).
- The address reflects the place: `#printers`, `#printers/<id>`, `#recent/<id>`, `#settings/backups`. Back and
  forward work; a link can be shared; reloading returns to the same place.
- Top bar, left to right: product mark and "Spoolwarden", the Hub's name and version, then at the right the job
  indicator (only while a background job runs or has just finished), the lock chip (Locked / Unlocked / Trusted
  computer) and the appearance control.

The web app's and the Android app's navigation are in `04-web-app.md` and `05-android-app.md`; both use the same
bottom-bar component with their own five destinations.

## 9. Type in use

- One page title (`--fs-xl`) per screen; it names the place ("Printers"), not the product. The browser tab reads
  `<Page title> · <Hub name>`.
- Card and group titles `--fs-l`, weight `--fw-title`. Table headers `--fs-xs`, uppercase with 0.05em letter spacing,
  `--muted`.
- Data (addresses, serials, weights, temperatures, codes, dates in tables) in `--mono`.
- Running text is at most 72 characters wide.

## 10. Icons

- Own drawings only: 24 × 24 viewBox, 1.75 px stroke, round caps and joins, `currentColor`, no fill. Shipped as
  one inline SVG sprite in the page (web) and as vector drawables (Android). No icon font, no third-party icon set,
  no emoji.
- An icon never stands alone without an accessible name; icon-only buttons have `aria-label` and a tooltip.
- The set: one per navigation section; lock (closed, open, shield for trusted); sun, moon, half-circle; plus,
  pencil, trash, refresh, more (three dots), chevron, close, check, warning triangle, info circle, error octagon,
  copy, download, upload, camera, tag, scale, printer, spool, plug, wifi-off, search, clock, undo.
- Status shapes (used with a word, never alone): filled circle = connected / OK; hollow circle = offline / off /
  not set; triangle = needs a look; octagon = error / failed; half-filled circle = working; diamond = note. The one
  phrase for "something wants attention" is **Needs a look**, in every interface.

## 11. Motion

Motion explains a change of place or state and nothing else: a row expanding, a sheet rising, a toast arriving, a
progress bar. No decorative animation, no parallax, no animated backgrounds. Nothing moves for longer than 320 ms
except progress indicators. Everything respects `prefers-reduced-motion`.

## 12. Hard rules for every web page

1. Served by the Hub, works offline on the home network: no CDN, no remote fonts, images, scripts or icon sets.
   Anything bundled needs a GPL-3.0-compatible licence and an entry in `THIRD-PARTY.md`.
2. No build step: plain HTML, CSS and JavaScript files as served. The strict Content-Security-Policy stays: no
   inline script or style; scripts and styles are files.
3. Text from the Hub goes into the page with `textContent` (never as HTML).
4. No `alert()`, `confirm()` or `prompt()`. Confirmations, names, addresses and secrets are asked in dialogs or
   sheets from `02-components.md`. Secrets are typed into password fields with a show/hide button.
5. Every colour, size and duration comes from a token. A check fails the build on a literal colour in a component
   rule.
6. Every page works by keyboard alone and with a screen reader (`07-accessibility.md`).
7. Fast on a phone: the shared stylesheet stays under 40 KB and the shared script under 60 KB uncompressed; no
   layout shift after the first paint; lists of more than 50 items are paged or virtualised.
8. No owner data in examples, placeholders, screenshots or tests: example addresses use `192.0.2.x`,
   `printer.local`, `*.example`.
