# Design tokens

- `tokens.json` is the source: four themes (console, workbench, spool, panes), each with light and dark values, type, space, radius, size, elevation and motion.
- `tokens.css` is generated from `tokens.json`; do not edit it by hand.
- `build_tokens.py` writes `tokens.css`; with `--check` it exits 1 when `tokens.css` is out of date.
- `check_contrast.py` checks the required contrast pairs of every theme and exits 1 on a failure; `contrast-report.txt` holds its last output.
- `ADJUSTMENTS.md` lists any colour changed to meet a ratio.
- Commands: `python build_tokens.py` (regenerate), then `python build_tokens.py --check` and `python check_contrast.py` (verify).
- Console is on bare `:root`; the other themes are under `:root[data-look="<name>"]`.
- Dark values sit under `:root[data-theme="dark"]` and, when no theme is chosen, under `prefers-color-scheme: dark`.
- Phone sizes (`*-phone` entries) are emitted in a `max-width: 600px` block; durations are 0 ms under `prefers-reduced-motion`.
