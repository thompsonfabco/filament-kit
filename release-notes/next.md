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

## Still to come

Notes for the visible changes (the new Hub page shell, the section pages, the phone web app, the Android app, the
command line's wording and the theme picker) are added here when each one merges.
