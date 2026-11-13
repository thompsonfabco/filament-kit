# Spoolwarden design system

This folder is the design system for Spoolwarden: the principles, names, tokens, components and screens of its four
interfaces (the Hub page, the web app, the app on Android and the `spoolwarden` command). It says what each screen
shows and says, how it behaves, how it is checked, and in what order to build it from today's code.

## The decisions

| Decision | Choice |
|---|---|
| Name | **Spoolwarden** (was filament-kit) |
| Default theme | **Console**: dense and technical, hairlines, monospace data, teal accent |
| Themes | Console, **Workbench** (calm cards), **Palette** (colourful and roomy), **Panes** (simple lists); a per-device choice in Settings > Appearance, plus a theme for new devices held by the Hub |
| Appearance switch | **Light / Dark / System**, default System, per device, inside every theme; at the right of the top bar on wide screens |
| Part names | the Hub · Hub page · web app · app · `spoolwarden` command · Features · Setups (Hub, Weigh Station only, Hub with Weigh Station) · Weigh Station · Weigh Station display · Tag Reader · Label Reader (Cloud (Claude), On this Hub) · Add spools · Recently added · Klipper add-on · Filament Catalog · Slicer presets · Slicer Sync |

The full list of names, with what each was called before, is in `01-foundations.md` section 2.

## How to read it

| Question | Read |
|---|---|
| What are the rules, names, tokens, appearance and themes? | `01-foundations.md` (it wins over every other part) |
| How does a button, field, dialog, list or status look and behave? | `02-components.md` |
| What does a section of the Hub page show and say? | `03-hub-page.md` |
| What does a screen of the web app show and say? | `04-web-app.md` |
| What does a screen of the app show and say? | `05-android-app.md` |
| What does a command print, ask and accept? | `06-command-line.md` |
| What must pass for keyboard, screen reader, contrast and touch, and how is it tested? | `07-accessibility.md` |
| How do the tokens become CSS and Kotlin, and how are the two kept equal? | `08-platform-mapping.md` |
| In what order is it built, and what does the Hub need to add? | `09-implementation-order.md` |
| What could come next? | `10-feature-ideas.md` |
| Where did a control of today's interface go? | the closing "Where today's … went" section of 03, 04 and 05; 06 section 4 for commands |

## Files

| File | What it is |
|---|---|
| `01-foundations.md` | Principles, names, the four interfaces, tokens, appearance, themes, layout, navigation, type, icons, motion, hard rules |
| `02-components.md` | Every component: shell, lock and appearance, actions, fields and forms, collections, status, progress, dialogs, page states |
| `03-hub-page.md` | The Hub page, section by section, with where today's controls went and what it needs from the Hub |
| `04-web-app.md` | The web app on phones and tablets, screen by screen |
| `05-android-app.md` | The app on Android: shell, every screen, strings and accessibility |
| `06-command-line.md` | The `spoolwarden` command: tree, spellings, output, confirmations, menus, every command |
| `07-accessibility.md` | Requirements, contrast pairs, automated checks AUT-1 to AUT-9, the one-hour release checklist |
| `08-platform-mapping.md` | `tokens.json`, the generator, the checks, how each token, component, icon and word maps to web and Android |
| `09-implementation-order.md` | 95 small steps in eight stages, the Hub API additions, open points, coverage |
| `10-feature-ideas.md` | 38 ideas beyond this design, each with effort, value and what it needs from the Hub |
| `/tokens/` (top of the repository, not in this folder) | The token files: `tokens.json` (the source of every value, four themes in light and dark), the generated `tokens.css`, `build_tokens.py`, `check_contrast.py`, and `ADJUSTMENTS.md` (colours changed to meet a contrast ratio). They exist only there |
| `mockups/c-console.html` | Mockup of the Hub page in Console, the default theme |
| `mockups/a-workbench.html`, `b-palette.html`, `d-panes.html` | The same page in Workbench, Palette and Panes |
| `mockups/gallery.html` | The four mockups side by side, with one control for screen, appearance and device size. Open it through a local web server (for example `python -m http.server` in `mockups/`): browsers do not let a page opened from a file show other files in frames |
| `mockups/CONTENT-SPEC.md` | The fake data and rules every mockup shares |

The mockups are in `mockups/`.

## Opening the mockups

- Double-click a mockup file; it opens in the browser. Each is one self-contained file and needs no Hub, no network
  and no build.
- They show example data only: invented printers, spools and addresses in the documentation ranges (`192.0.2.x`,
  `*.example`). Nothing is read from or sent to a Hub; any eight digits unlock the lock.
- Printers, Recently added and Settings are built out; the other sections are short placeholders. Add `#printers`,
  `#recent` or `#settings` to the address to open one, and `-light` or `-dark` to force an appearance (for example
  `c-console.html#printers-dark`).
- Settings > Appearance shows the four theme tiles. Choosing a tile opens the mockup of that theme, so the tiles
  switch between the four files.
- Where a mockup and the documents differ, the documents are right.

## Hard rules

1. Served by the Hub and works offline: no CDN, remote font, image, script or icon set; no build step.
2. Strict Content-Security-Policy: no inline script or style; text from the Hub goes in with `textContent`.
3. No `alert()`, `confirm()` or `prompt()`: dialogs and sheets from `02-components.md`.
4. Every colour, size and duration comes from a token; status is never told by colour alone.
5. Keyboard and screen reader everywhere, small and fast pages, and no owner data in examples, tests or screenshots.

The full eight rules are in `01-foundations.md` section 12.

## Changing the design

- **A colour, size, radius, duration or font:** edit `tokens/tokens.json` at the top of the repository, then run,
  in that `tokens/` folder:

  ```
  python build_tokens.py
  python build_tokens.py --check
  python check_contrast.py
  ```

  The first writes `tokens.css`; the second must print `OK: tokens.css matches tokens.json`; the third must end with
  `RESULT: PASS`. If a colour had to change to meet a ratio, note it in `tokens/ADJUSTMENTS.md`. Never edit
  `tokens.css` by hand.
- **A component:** change it in `02-components.md` first, then in the parts that use it (03 to 06) and in
  `08-platform-mapping.md` where its Android form is named.
- **A name or a rule of the foundations:** change `01-foundations.md` first; every other part follows it.
- **A screen:** change its section in 03, 04 or 05, and its row in the closing "Where today's … went" table when a
  control moves.
