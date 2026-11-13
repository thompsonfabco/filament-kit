# Coming next: the design upgrade (notes in progress, not a release)

This file collects what the redesign of the setup page, the phone web app, the Android app and the command line
changes for you, as the parts merge. It is not a release yet and carries no version number; the first release that
includes these parts takes its text from here.

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

## Still to come

Notes for the visible changes (the new Hub page shell, the section pages, the phone web app, the Android app, the
command line's wording and the theme picker) are added here when each one merges.
