package com.thompsonfabco.filamentkit.ui.storage

import android.content.Context
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.StorageAnswer
import com.thompsonfabco.filamentkit.net.StorageLocation
import com.thompsonfabco.filamentkit.net.StorageWire
import com.thompsonfabco.filamentkit.ui.add.AddText
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * One location as the Location field and the "Move to" sheet list it (ruling R79, 05-android-app 6.3 and 7.4): its
 * [name], how full it is as supporting text ([howFull], null when the Hub did not say) and [full]. A full location
 * stays choosable.
 */
data class LocationRow(val name: String, val howFull: AddText?, val full: Boolean, val containers: Boolean = false,
    val containerNames: List<String> = emptyList()) {
    /** The spool's [current] location is this row: its name, or for a containers location one of the container names the Hub lists (never built here). */
    fun holds(current: String?): Boolean = current != null && (current == name || (containers && current in containerNames))

    /** The lines of the "Move to" row under its name: "Moving…" while saved, "Now here" for the current one, then how full. */
    fun moveLines(here: Boolean, moving: Boolean): List<AddText> = when {
        moving -> listOf(AddText.of(R.string.spool_move_moving))
        else -> listOfNotNull(if (here) AddText.of(R.string.spool_move_here) else null, howFull)
    }
}

/** "18 of 20 spools", "7 spools", "3 free", "Full"; null when the answer gives no counts. */
fun StorageLocation.howFullText(): AddText? {
    if (containers) {
        val left = free ?: if (count != null && used != null) count - used else return null
        return if (left <= 0) AddText.of(R.string.storage_how_full_full) else AddText.of(R.string.storage_how_full_free, left)
    }
    val n = used ?: return null
    // every bulk limit counts, the default overflow's and the sealed location's too (R79 C1)
    val cap = limit
    return when {
        cap == null -> AddText.of(R.string.storage_how_full_spools, n)
        n >= cap -> AddText.of(R.string.storage_how_full_full)
        else -> AddText.of(R.string.storage_how_full_limit, n, cap)
    }
}

/** The rows in fill order: one per location (a containers location is one row). */
fun StorageAnswer.rows(): List<LocationRow> = locations.map {
    val text = it.howFullText()
    LocationRow(it.name, text, full = text?.res == R.string.storage_how_full_full, containers = it.containers, containerNames = it.containerNames)
}

/** A place a spool goes and, when the Hub placed it, why ([reason] is null for a place the person chose). */
data class Place(val location: String, val reason: AddText?) {
    /** "Rack 1 (the first place for PLA with room)", or the name alone. */
    fun resolve(context: Context): String =
        if (reason == null) location else context.getString(R.string.storage_where_why, location, reason.resolve(context))
}

/** The reason of a placement from its code (`placed_by`); an unknown code or a missing material gives none. */
fun reasonOf(code: String?, material: String?): AddText? = when (code) {
    StorageWire.REASON_MATERIAL -> material?.let { AddText.of(R.string.storage_reason_material, it) }
    StorageWire.REASON_ANY -> AddText.of(R.string.storage_reason_any)
    StorageWire.REASON_OVERFLOW -> material?.let { AddText.of(R.string.storage_reason_overflow, it) }
    StorageWire.REASON_OVERFLOW_NONE -> material?.let { AddText.of(R.string.storage_reason_overflow_none, it) }
    StorageWire.REASON_SEALED -> AddText.of(R.string.storage_reason_sealed)
    else -> null
}

private fun JsonObject.text(key: String): String? =
    (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content?.trim()?.ifBlank { null }

/**
 * Where the spools of one preview item go: the Hub's `placements` (one place per part, with its reason), else the
 * item-level `location`, else the location the item names (no reason). [item] is the app's own item.
 */
fun placesOf(hub: JsonObject?, item: JsonObject): List<Place> {
    val material = hub?.text("material") ?: item.text("material")
    val placed = (hub?.get(StorageWire.PLACEMENTS) as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
        .mapNotNull { p -> p.text("location")?.let { Place(it, reasonOf(p.text(StorageWire.PLACED_BY), p.text("material") ?: material)) } }
    if (placed.isNotEmpty()) return placed.distinct()
    hub?.text("location")?.let { return listOf(Place(it, reasonOf(hub.text(StorageWire.PLACED_BY), material))) }
    return listOfNotNull(item.text("location")?.let { Place(it, null) })
}

/** Per item index, the places "Automatic" chose; items that name their own location are left out. */
fun autoPlacesOf(items: List<JsonObject>, hubItems: List<JsonObject>): Map<Int, List<Place>> =
    items.indices.mapNotNull { i ->
        if (items[i].text("location") != null) return@mapNotNull null
        val hub = hubItems.firstOrNull { (it["index"] as? JsonPrimitive)?.content?.toIntOrNull() == i } ?: hubItems.getOrNull(i)
        val places = placesOf(hub, items[i])
        if (places.isEmpty()) null else i to places
    }.toMap()
