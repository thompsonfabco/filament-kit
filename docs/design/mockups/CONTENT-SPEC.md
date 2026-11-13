# Mockup content spec (shared by every design direction)

Every direction mocks the same product page with the same fake data, so the directions differ only in design.
The page is the kit's web setup console. All data below is invented; use it exactly. Addresses use the documentation
ranges (192.0.2.x, *.example). Never invent other addresses, serials, people or emails.

## Technical rules (hard)

- ONE self-contained file: full HTML document with doctype, `<meta charset>`, `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`, one `<style>`, one `<script>`. No external requests of any kind: no CDN, no web fonts, no remote images, no icon fonts. Fonts: system stacks only. Icons: your own simple inline SVG (drawn by you, 24x24 viewBox, `currentColor`), never copied from an icon set. No emoji as icons.
- Plain HTML/CSS/vanilla JS. No framework, no build step.
- Design tokens as CSS custom properties, all defined first on bare `:root` (light values), then redefined for dark in BOTH `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {...} }` and `:root[data-theme="dark"] {...}` (each with `color-scheme: dark`). Components use tokens only; no literal colours in component rules (filament swatch colours from the data are the one exception). Token groups: colour (background, surfaces, text, muted text, border, accent, on-accent, ok, warn, bad, info and their soft backgrounds), type scale, spacing scale, radius, elevation, motion durations.
- Theme switch with three states, Light / Dark / System, visible in the page chrome on every width. It sets or removes `data-theme` on `<html>`, and remembers the choice in `localStorage` inside try/catch.
- URL hash selects view and theme so screenshots can be taken: `#<view>` or `#<view>-<theme>`; views: `overview`, `modules`, `printers`, `devices`, `presets`, `intake`, `settings`, `updates`, `logs`; theme `light` or `dark` (forces it for that load without storing). Extra deep links: `#intake-detail` / `#intake-detail-dark` opens the first history record's detail. Unknown or empty hash: `printers`. Handle `hashchange`.
- Three layouts: phone (up to 600px), tablet (601 to 1024px), desktop (over 1024px). No horizontal page scroll down to 360px wide. Fixed bars respect `env(safe-area-inset-*)`.
- Accessibility: text contrast at least 4.5:1 (3:1 for large text and control outlines) in both themes, including text on the accent colour; every tappable target at least 44x44 CSS px; visible `:focus-visible` ring; real `<button>`, `<a>`, `<label for>`, `<nav aria-label>`, `aria-current`, dialogs with `role="dialog" aria-modal="true"` that trap focus and close on Escape; status never by colour alone (icon or word too); result messages in an `aria-live="polite"` region; honour `prefers-reduced-motion`.
- No `alert()`, `confirm()` or `prompt()`: confirmations and name/address entry are in-page dialogs or sheets.
- Keep it fast and small: aim under 90 KB, no images except inline SVG.

## What must be fully designed and clickable

Navigation shows all nine sections (Overview, Modules, Printers, Devices, Presets, Intake, Settings, Updates, Logs).
Fully build **Printers**, **Intake** (history list + record detail) and **Settings**. The other six open a short
placeholder panel in the same style ("Not part of this mockup") with the section's title and two or three sample rows
or a sentence, so the navigation can be judged. You may group or order the nine sections as your direction requires
(for example a "More" entry on phones), but each must stay reachable in at most two taps.

Global chrome (every view):
- Product name "filament-kit" and the server's display name "Workshop kit", version "0.5.2".
- **Setup code / lock state.** Viewing needs nothing; every change needs the 8-digit setup code unless this browser is a trusted computer. Show the state as Locked / Unlocked (or "Trusted computer") in the chrome with a way to enter the code (placeholder `1234-5678`) and the offer "Trust this computer (no code needed here for 90 days)". Start Locked; the first change the user tries asks for the code in place (any 8 digits unlock in the mockup), then carries on.
- **Background job.** Some actions run as a job on the server (back up, update, apply modules). Show a job as progress the user can follow from any view (title, state line, expandable log lines) and that ends with done/failed. Demo it from Settings > Backups > "Back up now" (fake 4-second job, a few log lines, then "Backup: done.").
- **Feedback.** Saves and results appear next to what caused them or as a toast; never as a raw text block far away.

### Printers view

Printers (list):
1. **Workshop X1**: Bambu Lab X1 Carbon, address 192.0.2.40, serial 00M00A000000001, state connected, certificate pinned, slots mapped. AMS slots: A1 Polymaker PolyTerra PLA Charcoal Black #2B2B2E 62%; A2 Bambu Lab PETG HF Orange #F2762E 88%; A3 eSUN ABS+ White #F4F4F2 35%; A4 empty.
2. **Garage Voron**: Klipper (Voron 2.4), voron.example:7125, state connected, API key set, lane data: auto. Slots: T0 Prusament PLA Galaxy Silver #8D9199 47%; T1 Overture TPU Blue #2E6FD9 71%.
3. **Study A1 mini**: Bambu Lab A1 mini, address 192.0.2.41, serial 03000A000000002, state offline, certificate pinned, problem line: "The last slot mapping stopped twice. A report would help." (primary suggestion: Collect a report).
4. **Found on the network, not added yet**: Klipper printer "mainsailos" found at 192.0.2.57:7125 with actions Use this printer / Dismiss.

Per-printer actions (design a clear hierarchy: one or two primary, the rest in a secondary area or menu, destructive ones separated):
- Bambu: Test connection, Rename, Change address, Replace Access Code (secret field; hint "On the printer: Settings > Network/LAN"), Map slots, Map by loading filament, Collect a report, Saved reports, Forget certificate, Forget printer.
- Klipper: Test connection, Detect model and slots, Rename, Change address, Set/Replace/Clear Moonraker API key, Lane data (auto / on / off), Map by loading filament, Forget printer.
- Must work in the mockup: **Test connection** (spinner, then inline result "192.0.2.40 answers; its certificate matches the pinned one" for connected printers, "no answer from 192.0.2.41:8883: check that it is on" for the offline one); **Rename** (in-page dialog with a text field); **Forget printer** (confirm dialog: "Forget Workshop X1? Its Access Code is deleted." with Cancel / Forget); **Map slots** (a short fake progress: "Mapping… step 2 of 4", then "Slots: A1, A2, A3, A4").
- Add a printer: type choice Bambu / Klipper. Bambu fields: IP address or name (e.g. 192.0.2.40 or printer.local), Access Code (secret), Name (optional), Serial (optional: read from the printer). Klipper fields: Address, Port (7125), Name (optional), Moonraker API key (optional).
- Find Klipper printers: optional subnet field (e.g. 192.0.2.0/24), Scan button; result "Found on 192.0.2.0/24: 192.0.2.57:7125".
- Printer pack (Klipper): "Installs the spool macros and the kit's Moonraker settings on a Klipper printer." Show the commands (a code block with a Copy button; two fake lines beginning `curl -fsSL https://kit.example/...`).
- Link: "Open the live printer view" (camera, pause/resume; opens the phone web app).
- Also design the empty state (no printers yet: "Printers on the network appear here once they announce themselves." plus Add a printer). Show it via a small "Preview empty state" toggle at the bottom of the view.

### Intake view (history of spool additions)

Header facts: "The newest 20 spool additions are kept with their photos (14.2 MB now)." Label reading (AI) is on.
Records, newest first:
1. Polymaker PolyTerra PLA Charcoal Black: 2026-11-12 14:05, from phone photo, state **as detected**, spool 214, 2 photos. Read confidence: high, except Colour (medium) and Price per kg (not on label).
2. Bambu Lab PETG HF Orange x2: 2026-11-12 09:41, from phone photo, state **revised by AI**, spools 212 and 213, 1 photo.
3. eSUN ABS+ White: 2026-11-11 19:22, from intake station, state **edited by hand**, spool 211, 1 photo.
4. Prusament PLA Galaxy Silver: 2026-11-10 08:15, added by hand, state **as detected**, spool 210, no photo.
5. Overture TPU Blue: 2026-11-09 17:48, from phone photo, state **as detected**, spool 209, 3 photos. Read confidence: low on Material and Net weight ("check these").
Photos do not exist in the mockup: draw a placeholder (an inline SVG spool-label sketch tinted with the filament colour).
On desktop the list may be a table; on a phone it must become cards. States and confidence need a clear, non-colour-only display.

Record detail (record 1 must work; others may open the same layout):
- Photos row (placeholders, tap to enlarge).
- Fields (label: value): Brand Polymaker; Name PolyTerra PLA Charcoal Black; Material PLA; Colour #2B2B2E (show a swatch); Net weight 1000 g; Spool weight 140 g; Density 1.31 g/cm3; Nozzle 210 C; Bed 55 C; Nozzle range 190-230 C; Bed range 25-60 C; Price per kg (empty); Line PolyTerra PLA. Group them sensibly (Identity / Weights / Temperatures / Other); show per-field confidence where it is not high.
- Edit by hand, then Save changes (only changed fields are sent; "Nothing changed." when none).
- "Ask the AI to correct it": text box (placeholder "e.g. brand is Polymaker") and a button; fake wait "Asking the AI… (up to a minute)" for 2 seconds, then a proposal shown as before -> after lines: "Name: PolyTerra PLA Charcoal Black -> PolyTerra PLA Charcoal Black (Matte)", "Nozzle range: 190-230 C -> 190-220 C", with Accept / Discard.
- Revisions: "Revision 1, 2026-11-12 14:09, by hand: Spool weight 150 -> 140 g" with Undo revision 1 (works: marks it undone).
- Empty state for the list: "No spool has been added since the history started."

### Settings view

Today this is one long page of eight cards with about thirteen separate Save buttons. Redesign the grouping and saving
as your direction sees fit (sections, sub-navigation, one save per group, or save-on-change with clear feedback), but
keep every setting:

- **Appearance** (new): Theme Light / Dark / System.
- **General**: Display name "Workshop kit"; Names for this page (space separated) "kit.example.net".
- **Storage locations**: Locations (comma separated) "Shelf A, Shelf B, Dry box 1, Dry box 2"; PLA rack "Shelf A"; Box location prefix "Dry box"; Number of storage boxes 2; Overflow location "Shelf B".
- **Label reading (AI)**: Anthropic API key (state: set; Replace / Remove / Check; secret field placeholder "sk-ant-…"); Claude model (text); Label reads per day 40; Intake records kept 20 ("Now: 20 records, 14.2 MB of photos"); note "Changing the model or the reads per day restarts the server."
- **Backups**: warning "One zip with everything the kit keeps. It is not encrypted and holds the setup secrets: store it somewhere safe."; Back up now (job demo); list: "2026-11-12 03:00 · nightly · 4,812 KiB", "2026-11-11 03:00 · nightly · 4,790 KiB", "2026-11-10 16:32 · made here · 4,771 KiB", each with Download; Keep nightly backups for 14 days; Restore: choose a zip, Upload and check, then a summary and "Type restore to go on" with Restore / Cancel (design it; only the file chooser and disabled Restore need to exist).
- **Network and addresses**: Web public address (placeholder https://mcp.example.com/filament); Station address (placeholder http://station.local:5003); Allow printer changes from the public address (toggle, off); Remote access: Show the firewall rules, Get the certificate.
- **Web passphrase** (state: not set): new passphrase (at least 12 characters) + again, Set.
- **Filament library**: "Library version 2026.11.2 (signed release), 3 local additions. Last check 2026-11-12 03:10: ok."; Update now; Go back to the version before; Library token (optional, state: not set); Add your own entry (JSON text area, Add entry).
- **Station voice** (station module on): Piper (natural; a 60-80 MB download) / espeak-ng (robotic; no download).
Must work in the mockup: theme control, editing and saving at least the General and Storage groups with visible "Saved" feedback, the unlock prompt on first save, the Back up now job, the passphrase mismatch error ("The two passphrases do not match.") shown inline at the field.

## Wording

Plain language, sentence case, no jargon the labels above do not already use. Buttons say what happens. Errors say
what went wrong and what to do. Keep the product's existing terms (setup code, Access Code, slot, spool, intake).
