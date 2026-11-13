# 0.6.0 release notes in progress: the design upgrade (not yet a release)

This file collects what the redesign of the setup page, the phone web app, the Android app and the command line
changes for you, as the parts merge. These are the notes for version 0.6.0; it is not released yet, and the release's text is taken from here.

## Already merged: the groundwork

Nothing on the screens looks different yet. The pieces below are in the code so the interfaces can share them:

- **One set of design values.** The colours, sizes, radii and fonts of the four themes (Console, Workbench, Palette and
  Panes) live in one folder, `tokens/`, and the pages and the Android app are generated from it. The contrast between
  every text colour and its background is checked in both light and dark.
- **One catalogue of texts and one icon set** for the interfaces to share, so the same sentence reads the same on the
  setup page, in the phone web app, in the Android app and on the command line.
- **The Spool theme is called Palette.**

## Long jobs report their steps

The nine long jobs now say which step they are on: backup, restore, update, rollback, applying modules, a library update
and its rollback, setting up a reader, and pairing a station. Each prints lines such as `==> step 2 of 3 <what it is
doing>` as a step starts, on the command line and in the setup page's job log. The setup page can use them to show
"Step 2 of 3" and a progress bar that fills step by step; until the new pages arrive, the bar behaves as before.

## The setup page and the phone web app are on the new look

- **The setup page uses the shared design values and components.** Its colours, sizes and buttons come from the same tokens as the other interfaces.
- **Light, dark or system.** A switch in the page header picks Light, Dark or System (the default, which follows the device); the choice is kept in that browser.
- **A new page shell.** A top bar and navigation: a side list on wide screens, and on a phone a bottom bar (Overview, Printers, Recent, Settings) with a More sheet for the other sections.
- **The setup code can be checked without changing anything.** A right code costs no try, a wrong one says how many tries are left, and an error about a form names the field it is about (the address, the code). The setup page also reports when a trusted computer's trust expires.
- **The phone web app** has light and dark manifests, and its theme colour follows the appearance.

## The phone web app is on the new look

- **The web app uses the shared design values and components**, the same as the setup page.
- **A new shell.** A top bar and a bottom bar (a side rail on tablets), with Add, Spools, Printers, Recent, Slicer presets and Settings; a **More** sheet holds the places that do not fit. A place whose feature is switched off says so instead of showing an empty page.
- **The page shown outside the home network, and the sign-in page,** use the same styles and the shared texts.

## The Android app is on the new look

- The app draws in the Console theme from the shared design values, with an app shell (bottom bar, side rail on wide screens, top bar), 44 dp controls and a new launcher icon. Its name and texts come from the shared catalogue. The shared parts every screen uses (page states such as loading and empty, dialogs) now exist, with tests for their accessibility semantics.

## More of the new design is merged

- **Android app:** Settings, app updates and licences; pairing with one screen per step; Home; the Printers list, adding and finding Klipper printers; adding a line to the Filament Catalog; Recently added (what was read, how sure the Label Reader was, a record's changes, editing and undo); Spools and the spool screen (loading and linking tags, with a tag read during a load held until it finishes); Add spools with one screen per step (Photos, Check the spools, Preview, Done), where every add is kept as a draft on the phone and a read or add carries on when you leave the screen. All in the new design.
- **Phone web app:** sheets replace the browser's own confirm and prompt boxes; results, errors and reasons appear in place; the add preview works per item with colour finding and paging; spools can be read and edited from the phone, with the usage source shown; the offline helper (service worker) is always served.
- **The Hub:** every printer's state comes in one read; the status shows groups and section summaries; the label reader's confidence and engine are reported; a settings group saves at once, and the last backup time is shown; an address you enter for the Hub can be tested before it is saved. A reader that gives no per-field numbers (the Cloud reader, for one) is shown as not rated instead of as sure.
- **The setup page:** a lock chip in the header shows whether the page is unlocked and opens an unlock dialog; Hub dialogs replace the browser's own confirm and prompt boxes; the result of a button appears beside it, with short toasts for what finished; a job strip shows a background job, with restarting and not-answering states; loading, empty, error and switched-off pages look the same everywhere.
- **QR codes:** the Hub now draws its QR codes itself, on the Hub page (the pairing code and the phone web app's address) and in the terminal, so the `qrencode` package is no longer needed (the pairing link is shown when it cannot fit one).
- **Setup names:** `hub`, `weigh-station` and `hub-with-weigh-station` are accepted beside `server`, `station` and `all-in-one`, and `--hub` beside `--server` in `filament-kit modules set` and `modules enable`; what the kit stores does not change. Feature titles use the names of the new Hub page.

## Still to come

Notes for the visible changes (the new Hub page shell, the section pages, the phone web app, the Android app, the
command line's wording and the theme picker) are added here when each one merges.
