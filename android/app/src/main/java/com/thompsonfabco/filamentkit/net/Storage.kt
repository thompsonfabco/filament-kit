package com.thompsonfabco.filamentkit.net

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull

/**
 * One storage location of `GET api/storage` (ruling R79 section 4). Every field is optional on the wire: the Hub's
 * answer may still change its key names, so all of them are read here ([StorageWire]) and nowhere else.
 */
data class StorageLocation(
    val name: String,
    val id: String = "",
    /** [BULK] or [CONTAINERS]. */
    val type: String = BULK,
    val limit: Int? = null,
    val count: Int? = null,
    val used: Int? = null,
    val free: Int? = null,
    /** `none`, `any` or `materials`. */
    val fill: String = "none",
    val materials: List<String> = emptyList(),
    val overflow: Boolean = false,
    val defaultOverflow: Boolean = false,
    val sealed: Boolean = false,
    val position: Int? = null,
) {
    val containers: Boolean get() = type == CONTAINERS

    companion object {
        const val BULK = "bulk"
        const val CONTAINERS = "containers"
    }
}

/** Where a new spool of [material] goes, in order (`order_by_material`). */
data class MaterialOrder(val material: String, val locations: List<String>)

/**
 * The Hub's storage answer: [locations] in fill order. [detailed] is false for the fallback made from `GET api/locations`
 * (names only: no how-full text, no reason).
 */
data class StorageAnswer(
    val locations: List<StorageLocation> = emptyList(),
    val orderByMaterial: List<MaterialOrder> = emptyList(),
    val everythingElse: List<String> = emptyList(),
    val detailed: Boolean = true,
) {
    val names: List<String> get() = locations.map { it.name }

    companion object {
        /** What an older Hub (no `api/storage`) gives: its names, nothing else. */
        fun ofNames(names: List<String>) = StorageAnswer(names.map { StorageLocation(it) }, detailed = false)
    }
}

/** The key names of the storage answer and of the placements that name a reason, in one place. */
object StorageWire {
    const val LOCATIONS = "locations"
    const val ORDER_BY_MATERIAL = "order_by_material"
    const val EVERYTHING_ELSE = "everything_else"

    /** On a dry-run placement: `placed_by`, the reason code (`material`, `any`, `overflow`, `sealed`). */
    const val PLACED_BY = "placed_by"
    const val PLACEMENTS = "placements"
    const val REASON_MATERIAL = "material"
    const val REASON_ANY = "any"
    const val REASON_OVERFLOW = "overflow"
    const val REASON_SEALED = "sealed"

    /** The answer of `GET api/storage`, or null when it has no `locations` list (not a storage answer). Lenient. */
    fun parse(el: JsonElement?): StorageAnswer? {
        val root = el as? JsonObject ?: return null
        val list = root[LOCATIONS] as? JsonArray ?: return null
        val locations = list.mapNotNull(::location)
            .withIndex().sortedWith(compareBy({ it.value.position ?: Int.MAX_VALUE }, { it.index })).map { it.value }
        val byMaterial = (root[ORDER_BY_MATERIAL] as? JsonArray).orEmpty().mapNotNull { e ->
            val o = e as? JsonObject ?: return@mapNotNull null
            val m = o.text("material") ?: return@mapNotNull null
            MaterialOrder(m, o.texts("locations"))
        }
        return StorageAnswer(locations, byMaterial, (root[EVERYTHING_ELSE] as? JsonArray).orEmpty().mapNotNull { it.asText() })
    }

    private fun location(e: JsonElement): StorageLocation? {
        if (e is JsonPrimitive) return e.asText()?.let { StorageLocation(it) } // a bare name
        val o = e as? JsonObject ?: return null
        val name = o.text("name") ?: return null
        return StorageLocation(
            name = name, id = o.text("id").orEmpty(),
            type = if (o.text("type") == StorageLocation.CONTAINERS) StorageLocation.CONTAINERS else StorageLocation.BULK,
            limit = o.num("limit"), count = o.num("count"), used = o.num("used"), free = o.num("free"),
            fill = o.text("fill") ?: "none", materials = o.texts("materials"),
            overflow = o.flag("overflow"), defaultOverflow = o.flag("default_overflow"), sealed = o.flag("sealed"),
            position = o.num("position"),
        )
    }

    private fun JsonElement.asText(): String? = (this as? JsonPrimitive)?.takeIf { it.isString }?.content?.trim()?.ifBlank { null }
    private fun JsonObject.text(key: String): String? = this[key]?.asText()
    private fun JsonObject.texts(key: String): List<String> = (this[key] as? JsonArray).orEmpty().mapNotNull { it.asText() }
    private fun JsonObject.num(key: String): Int? {
        val p = this[key] as? JsonPrimitive ?: return null
        return p.intOrNull ?: p.content.trim().toDoubleOrNull()?.toInt()
    }
    private fun JsonObject.flag(key: String): Boolean = (this[key] as? JsonPrimitive)?.booleanOrNull ?: false
}
