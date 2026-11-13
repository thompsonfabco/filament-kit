# Design tokens

This folder is the only place the token files exist. The design documents in `docs/design/` describe them; the
pages and the app are generated from them.

- `tokens.json` is the source: four themes (console, workbench, palette, panes), each with light and dark values, type, space, radius, size, elevation and motion.
- `tokens.css` is generated from `tokens.json`; do not edit it by hand.
- `build_tokens.py` writes `tokens.css`; with `--check` it exits 1 when `tokens.css` is out of date.
- `check_contrast.py` checks the required contrast pairs of every theme and exits 1 on a failure.
- `ADJUSTMENTS.md` lists any colour changed to meet a ratio.
- Commands, in this folder: `python build_tokens.py` (regenerate), then `python build_tokens.py --check` and `python check_contrast.py` (verify). The project's test run does the last two.
- Console is on bare `:root`; the other themes are under `:root[data-look="<name>"]`.
- Dark values sit under `:root[data-theme="dark"]` and, when no theme is chosen, under `prefers-color-scheme: dark`.
- Phone sizes (`*-phone` entries) are emitted in a `max-width: 600px` block; durations are 0 ms under `prefers-reduced-motion`.
