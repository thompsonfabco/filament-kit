# Android app: adding a spool by hand (HTTP contract)

AI label reading is optional (module `ai_intake`, off on a new install). This is everything an app screen needs
to add spools without it: pick an existing filament or type a new one in, check with a dry run, then add. All of
it works whether `ai_intake` is on or off. Nothing here changes an existing route; `/api/filaments` and
`/api/vendors` are new (additive, API version stays 1).

## Basics

- Base: `https://<host>:<port>` as the app already uses it (pinned certificate, see `Endpoints.kt`).
- Every route below needs `Authorization: Bearer <token>` (the token from `POST /api/pair`).
- Errors are always JSON: `{"error": "<code>", "message": "<text for the user>", ...}`. Show `message`.
  Codes that apply here:

  | Status | `error` | When |
  |---|---|---|
  | 400 | `bad_request` | body is not a JSON object, or an item is invalid (the message names the item and field, e.g. `SUNLU PETG Grey: tare must be a positive number`) |
  | 401 | `unauthorized` | missing or revoked token: pair again |
  | 409 | `tag_conflict` | the `tag` is already linked to another spool; extra fields `reason`, `other_spool` |
  | 502 | `spoolman_error` | Spoolman refused or failed part-way; extra field `partial_spool_ids` (spools already written: do not resend blindly) |
  | 503 | `spoolman_unreachable` | Spoolman is down |
  | 500 | `internal` | server bug (logged on the server) |

## 1. Which screens to show: `GET /api/info`

No token needed. `modules` lists the modules that are on.

```json
{"name": "Workshop", "version": "0.2.0", "api": 1, "apk_version": "7",
 "modules": ["backup", "library", "presets", "printers", "server", "spoolman"]}
```

- Always show the manual **Add spool** screen.
- Show the label-photo flow (`POST /api/intake/read`, `/api/intake/retry/{read_id}`) only when `modules`
  contains `"ai_intake"`. With it off those two routes answer `409 {"error": "module_off", "module": "ai_intake"}`.

## 2. Existing filaments: `GET /api/filaments?q=<words>`

Every filament in Spoolman (also ones with no spools left), sorted by vendor then name. `q` is optional: each
word must appear in vendor, name or material (case-insensitive), e.g. `q=sunlu petg`.

```json
{"filaments": [
  {"id": 3, "vendor": "Elegoo", "name": "PLA Red", "material": "PLA", "density": 1.24,
   "net": 1000, "tare": 160, "color_hex": "cc0000", "nozzle": 210, "bed": 60, "spools": 2}
]}
```

| Field | Meaning |
|---|---|
| `id` | Spoolman filament id (for display only; the add matches by vendor + name) |
| `vendor`, `name`, `material` | as in Spoolman; `name` includes the colour |
| `density` | g/cm³ |
| `net` | filament grams on a full spool (Spoolman `weight`), may be null |
| `tare` | empty spool grams (Spoolman `spool_weight`), may be null |
| `color_hex` | 6 hex digits without `#`, may be null |
| `nozzle`, `bed` | °C, may be null |
| `spools` | how many spools of it Spoolman has (archived ones not counted) |

The field names are the add item's (below), so picking a filament means copying `vendor`, `name`, `material`,
`density`, `net`, `tare` (and `color_hex`, `nozzle`, `bed` if you like) into a new item.

## 3. Vendors: `GET /api/vendors`

For a vendor picker or autocomplete on a new filament, sorted by name:

```json
{"vendors": [{"id": 1, "name": "Elegoo", "tare": 160}, {"id": 2, "name": "SUNLU", "tare": 213}]}
```

`tare` is the vendor's empty spool weight (may be null): a good default for a new filament's `tare`.

## 4. Locations: `GET /api/locations` (existing route)

`{"locations": ["Rack 1", "Storage box 01", ...]}`: the configured places plus every location a spool has.
Offer them, plus "automatic" (send no `location`).

## 5. Add: `POST /api/intake/add`

Body:

```json
{"items": [ITEM, ...], "dry_run": true, "tag": "4:77:90:e:9:22:89"}
```

- `dry_run`: **defaults to true** (nothing written). Send `true` first, show `lines` to the user, then send the
  same body with `false`. Any edit needs a new dry run.
- `tag` (optional): a tapped NFC tag UID. It is linked only when the request adds exactly one opened spool
  (one item, `count` 1, `sealed` false); otherwise `lines` says it was not linked.

ITEM fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `vendor` | text | yes | non-empty |
| `name` | text | yes | product name with the colour, e.g. `PLA+ 2.0 Grey`. **vendor + name equal (case-insensitive) to an existing filament reuse it**; anything else creates a new filament (and a new vendor if needed) |
| `material` | text | yes | e.g. `PLA`, `PETG` |
| `net` | number | yes | filament grams on a full spool, > 0 |
| `tare` | number | yes | empty spool grams, > 0. For an existing filament the filament's own tare is used when it has one |
| `density` | number | yes | g/cm³, > 0 (used only for a new filament; send the picked filament's) |
| `count` | whole number | yes | spools of this kind, ≥ 1 |
| `sealed` | true/false | no | default true (still in its bag/box: the spool gets the SEALED comment). `false` = opened |
| `gross` | number | no | opened spool on a scale, grams **with** the spool: remaining = gross − tare. Needs `count` 1 and a weight above the tare. Without it the spool counts as full |
| `location` | text | no | blank/absent = automatic: sealed → the sealed-stock location; opened PLA → the PLA place; other opened → the next free storage box |
| `color_hex` | text | no | 6 hex digits, no `#` (new filament only) |
| `nozzle`, `bed` | number | no | °C (new filament only) |
| `nozzle_range`, `bed_range` | text | no | e.g. `200-230` (new filament only) |
| `lot` | text | no | lot number, stored on each spool |
| `price_per_kg` | number | no | sets the new filament's price |
| `note` | text | no | new filament's comment |
| `spool_note` | text | no | appended to each spool's comment |
| `line` | text | no | product line without the colour, e.g. `PLA+ 2.0` (preset grouping), ≤ 100 chars, no `@` |
| `bambu_parent` | text | no | Bambu Studio base preset for a new filament's line; an unknown one is refused |

Send numbers as JSON numbers (not strings) and leave optional fields out rather than sending `""`.

Reply (200):

```json
{"spool_ids": [41, 42], "dry": false,
 "lines": ["F3 Elegoo PLA Red (existing filament): 2 spool(s) [41, 42] @ Sealed stock, 1000 g"]}
```

On a dry run `spool_ids` is `[]`, `dry` is true and `lines` says what would happen (e.g. `new vendor X`,
`(new filament)`, `would link tag ...`). Show `lines` as they are.

### Examples

Two sealed spools of a filament picked from the list:

```json
{"items": [{"vendor": "Elegoo", "name": "PLA Red", "material": "PLA", "density": 1.24,
            "net": 1000, "tare": 160, "count": 2}], "dry_run": true}
```

One opened spool of a new filament, weighed, with its tag:

```json
{"items": [{"vendor": "SUNLU", "name": "PETG Grey", "material": "PETG", "density": 1.27, "net": 1000,
            "tare": 213, "count": 1, "sealed": false, "gross": 1100, "color_hex": "808080"}],
 "dry_run": false, "tag": "4:77:90:e:9:22:89"}
```

## Suggested screen

1. Search box → `GET /api/filaments?q=...` → list `vendor name · material · spools`; tap one to fill the form.
2. "New filament" → empty form; vendor field with `GET /api/vendors` suggestions (fill `tare` from the vendor).
   A density default by material helps (PLA 1.24, PETG 1.27, ABS 1.04, ASA 1.07, TPU 1.21); the phone web app
   does the same.
3. Form: count, sealed switch, gross (when opened), location (from `/api/locations`, default automatic).
4. **Check** (`dry_run: true`) → show `lines` → **Add** (`dry_run: false`) → show the spool ids.
