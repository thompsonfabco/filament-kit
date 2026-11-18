package com.thompsonfabco.filamentkit.ui.profile

import com.thompsonfabco.filamentkit.ui.hub.hubDay

/**
 * The texts of the catalog form and the list of the owner's own entries (EV7b) that are not in the string catalogue
 * yet. Only the catalogue step (EV2) opens `strings/en.json`; each text here has a proposed key in the EV7b report and
 * moves there with it. The Hub's own problem texts and the entries' names are never built here.
 */
object CatalogTexts {
    const val BRAND = "Brand *"
    const val NAME = "Name *"
    const val MATERIAL = "Material *"
    const val MATERIAL_OTHER = "Other"
    const val MATERIAL_OTHER_FIELD = "Other material *"
    const val MORE = "More (optional)"
    const val NOZZLE_MIN = "Nozzle temperature from (°C)"
    const val NOZZLE_MAX = "Nozzle temperature to (°C)"
    const val BED_MIN = "Bed temperature from (°C)"
    const val BED_MAX = "Bed temperature to (°C)"
    const val FILL = "Fill in Brand, Name and Material."
    const val ADD = "Add"
    const val ADDED = "Added. Slicer presets are rebuilt in a minute."

    const val SEE_ENTRIES = "See custom entries"
    const val HIDE_ENTRIES = "Hide custom entries"
    const val ENTRIES_EMPTY = "You have not added any entries of your own yet."
    const val ENTRIES_LOADING = "Loading your entries…"
    const val ENTRIES_UPDATE_HUB = "Update the Hub to see your own entries."
    const val REMOVE = "Remove"
    const val REMOVING = "Removing…"

    /** The materials the form offers when the Hub sends none (an older Hub); anything else is typed under "Other". */
    val MATERIALS = listOf("PLA", "PETG", "ABS", "ASA", "TPU", "PC", "PA", "PVA", "HIPS", "PP")

    /** The line of one entry: brand and name, then the material and the day it was added when the Hub gave them. */
    fun entryLine(brand: String, name: String): String = listOf(brand, name).filter { it.isNotBlank() }.joinToString(" ")

    fun entryDetail(material: String, added: String?): String =
        listOfNotNull(material.ifBlank { null }, hubDay(added)?.let { "Added $it" }).joinToString(" · ")

    fun removeTitle(brand: String, name: String): String = "Remove ${entryLine(brand, name)}?"

    /** The question before a removal: "Remove <brand> <name> from your own entries? Slicer presets are rebuilt." */
    fun removeQuestion(brand: String, name: String): String =
        "Remove ${entryLine(brand, name)} from your own entries? Slicer presets are rebuilt."
}
