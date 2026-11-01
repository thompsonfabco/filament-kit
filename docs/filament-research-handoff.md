# Filament spec research — handoff

Use Research mode. Your job is to collect **published manufacturer specs** for 3D-printer filament product
lines and return them as JSON entries for a local spec library. The library feeds an automatic preset generator
for **Bambu Studio** (printers: Bambu Lab X2D, X1 / X1C / X1E, P1S / P1P / P2S; nozzles 0.2 / 0.4 / 0.6 / 0.8 mm).
Values you return become slicer settings, so accuracy and sourcing matter more than coverage.

## What to research

One entry per **brand + product line** (all colours of a line share one entry). Work in this order:

1. **Lines Bambu Studio users commonly buy that are not in the existing library.** Start with each brand's full
   current catalogue for: Bambu Lab, Polymaker (PolyLite, PolyTerra, Panchroma, PolyMax, Fiberon), eSUN, SUNLU,
   ELEGOO, OVERTURE, JAYO, Kingroon, Hatchbox, Inland, Creality, Anycubic, Prusament, Siraya Tech, Push Plastic,
   Atomic Filament, Fiberlogy, Fillamentum, Extrudr, Spectrum, Eryone, AMOLEN, GEEETECH, Sovol, QIDI Tech,
   Flashforge, Kexcelled, 3DXTech, Protopasta, ColorFabb, Formfutura, Amazon Basics.
   Ask me before expanding beyond this list.
2. **Refresh existing lines** (list below) only when you find a better source than `source_quality` suggests
   (e.g. an official TDS where only a listing was used), or a value changed.

Skip discontinued lines unless still widely sold. Treat a meaningfully different product (e.g. "PLA" vs "PLA+"
vs "High Speed PLA", "PETG" vs "PETG HF", a CF/GF variant) as its own line. Colours that are a different product
(different temps/density, e.g. glow, silk, metal-fill) are their own line too.

## Rules

- **Every value needs a source.** Prefer, in order: official TDS/datasheet PDF → official product page →
  brand's own marketplace listing → reseller copy of the TDS. Record which in `source_quality`.
- **Published ranges are bounds.** Copy them as printed ("200-230"). Never invent a midpoint, never widen or
  narrow a range, never fill a value the sources don't give: leave it out.
- When a label/page gives several ranges (normal vs high-speed, per grade), record all of them in
  `published_ranges._nozzle_by_speed` and put the **highest** range in `fields.nozzle_temperature_range_low/high`.
- **Do not set `temperature_vitrification`** in `fields` (Bambu uses that key as a heat-creep threshold, not
  Tg). Put Tg / Vicat / HDT values under `published_ranges` (`_vitrification`, `_vicat`, `_hdt_0.45MPa`) with
  the metric named.
- Conflicting sources: keep the official one in `fields`, list the others in `conflicts` with their source.
- Density in g/cm³, diameter in mm, temperatures in °C, drying as "<temp>C <hours>h".
- `bambu_parent`: the **Bambu Studio system filament preset** this line is closest to. Prefer the brand's own
  system preset if Bambu Studio ships one (e.g. "Polymaker PolyLite PLA", "eSUN PLA+", "SUNLU PETG",
  "Overture PLA"); otherwise Bambu Lab's own product for that material and variant ("Bambu PLA Basic",
  "Bambu PLA Matte", "Bambu PETG HF", "Bambu PETG Basic", "Bambu ABS", "Bambu ASA", "Bambu TPU 95A HF",
  "Bambu PA6-CF", "Bambu PC"); "Generic <material>" only when nothing closer exists. Give the preset name
  without the "@BBL <printer>" suffix. Say in `_notes` if you couldn't confirm the name exists in current
  Bambu Studio.
- Note anything printer-relevant: AMS compatibility (cardboard spools, TPU hardness, brittle CF), hardened
  nozzle required, enclosure/chamber needs, minimum nozzle size, max volumetric speed if published.

## Output format

Return JSON only, in a fenced ```json block, an **array of entries**, in batches of about 25 entries per reply.
After each batch, list the lines you plan to do next and wait for me to say "continue".

Each entry:

```json
{
  "schema_version": 1,
  "vendor": "ELEGOO",
  "product": "PLA+",
  "material": "PLA",
  "colors": ["Red", "Neon Green", "Yellow"],
  "bambu_parent": "Bambu PLA Basic",
  "fields": {
    "nozzle_temperature_range_low": ["200"],
    "nozzle_temperature_range_high": ["230"],
    "filament_density": ["1.30"],
    "filament_diameter": ["1.75"]
  },
  "published_ranges": {
    "bed_all_plates": "35-65",
    "chamber_temperatures": "20-45",
    "_drying": "50C 8h",
    "_hdt_0.45MPa": "56",
    "_vitrification": "63 (Vicat)",
    "_diameter_tolerance": "+/-0.02",
    "_notes": "Cardboard spool on some colours: wrap edges before AMS use."
  },
  "conflicts": [],
  "source_quality": "official_page",
  "sources": ["https://www.elegoo.com/products/elegoo-pla-plus-3d-printer-filament-1-75mm-colored-1kg"],
  "updated": "2026-11-01"
}
```

Allowed `fields` keys (values are one-element string arrays, like Bambu Studio's own preset files):
`nozzle_temperature_range_low`, `nozzle_temperature_range_high`, `filament_density`, `filament_diameter`,
`filament_soluble` ("1"/"0"), `filament_is_support` ("1"/"0"), `filament_shrink` (e.g. "99.6%"),
`filament_max_volumetric_speed` (mm³/s, only if published).

Allowed `published_ranges` keys: `bed_all_plates`, `cool_plate_temp`, `hot_plate_temp`, `textured_plate_temp`,
`chamber_temperatures`, `fan_max_speed`, `fan_min_speed/fan_max_speed`, `filament_retraction_length`,
`filament_retraction_speed`, `overhang_fan_threshold`, and any key starting `_` for notes
(`_drying`, `_nozzle_by_speed`, `_print_speed`, `_max_print_speed`, `_hardened_nozzle_required`, `_min_nozzle`,
`_enclosure`, `_ams`, `_fiber_content`, `_hardness`, `_hdt_0.45MPa`, `_vicat`, `_vitrification`,
`_diameter_tolerance`, `_annealing`, `_notes`).

`source_quality`: `official_tds` | `official_page` | `brand_amazon_listing` | `reseller_tds_copy`.

## Already in the library (skip unless refreshing)

- AMOLEN: PLA Glow
- Anycubic: PETG-CF
- Bambu Lab: PA6-GF; PC FR; PETG HF; PETG-CF; PVA; TPU 85A; TPU 90A
- CC3D: PC; TPU 72D
- CCTREE: ABS
- CHCKX: ABS-CF; PETG; PETG-GF; PP-CF
- Comgrow: ABS
- Creality: CR-ABS; CR-PETG
- DEEPLEE: PLA+ 2.0
- ELEGOO: PAHT-CF; PETG-CF; PLA; PLA Relievo; PLA+; Silk PLA; TPU 72D
- eSUN: PETG; Wood PLA
- Flashforge: ASA
- GEEETECH: PLA; Silk PLA; TPU; Wood PLA
- Gizmo Dorks: HIPS; POM
- IEMAI: PC-CF
- Inland: PLA
- Inslogic: PA12-CF; PC-ABS
- JAYO: PETG; PLA; Wood PLA
- LADUALFILA: PLA+
- OVERTURE: ASA; Matte PLA; Matte TPU; PC Professional; PETG; PLA Professional; PLA+
- Phrozen: PLA HS
- Polymaker: Fiberon PPS-CF10; Fiberon PPS-GF20; Panchroma PLA; PolyMax PC
- Push Plastic: PETG; PLA
- QIDI Tech: PAHT-GF
- Siraya Tech: Fibreheart PET-CF; Fibreheart PPA-CF; Fibreheart TPU-GF
- SOVOL: Silk PLA
- SUNLU: ABS; ABS Transparent; Easy PA; Elite PETG; Fluorescent PLA; High Speed ABS; High Speed Marble PLA;
  High Speed Matte PETG; High Speed PLA; High Speed PLA+ 2.0; PA12-CF; PA6-CF; PA6-GF; PC-ABS; PETG Glow; PLA;
  PLA Meta; PLA+ 2.0; Silk PLA+; TPU
- TEQStone: PETG; TPU
- UJOYBIO: Metal PLA
- XZN: ASA; Silk PLA; TPU
- yxpolyer: ABS; Easy PA; PPS; PVA

## Start

Begin with Bambu Lab's full current filament catalogue (excluding the lines above), then Polymaker.
