package com.thompsonfabco.filamentkit.ui.spool

import com.thompsonfabco.filamentkit.net.ApiError
import kotlinx.coroutines.CompletableDeferred
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** A Spoolman spool as the Hub passes it on (example data only). */
internal fun spoolJson(
    id: Int,
    remaining: Double? = 620.0,
    location: String? = "Workshop X1 A1",
    sealed: Boolean = false,
    archived: Boolean = false,
    tag: String? = null,
    total: Double? = 1000.0,
    lot: String? = null,
): JsonObject = buildJsonObject {
    put("id", id)
    put("filament", buildJsonObject {
        put("id", 41)
        put("name", "PolyTerra PLA Charcoal Black")
        put("material", "PLA")
        put("color_hex", "2B2B2E")
        put("spool_weight", 140.0)
        put("vendor", buildJsonObject { put("name", "Polymaker") })
    })
    location?.let { put("location", it) }
    remaining?.let { put("remaining_weight", it) }
    total?.let { put("initial_weight", it) }
    if (sealed) put("comment", "SEALED - tag when opened")
    if (archived) put("archived", true)
    lot?.let { put("lot_nr", it) }
    tag?.let { put("extra", buildJsonObject { put("nfc_id", "\"$it\"") }) }
}

/** The Hub's calls for the spool screens, answered by the test; every call is written to [calls]. */
internal class FakeSpoolBackend : SpoolBackend {
    val calls = mutableListOf<String>()
    var spools: List<JsonObject> = emptyList()
    var tagAnswer: JsonObject? = null
    var tagGate: CompletableDeferred<Unit>? = null
    var locations: List<String> = listOf("Shelf B", "Workshop X1 A1", "Dry box 1")

    /** Answers to `update`; the dry run and the real one are told apart by the flag. */
    var updateAnswer: (gross: Double?, location: String?, empty: Boolean, dry: Boolean) -> JsonObject = { _, _, _, _ -> spoolJson(214) }
    var linkAnswer: (force: Boolean, dry: Boolean) -> JsonObject = { _, _ -> spoolJson(212, tag = "04A1B2") }

    /** When set, the next call of that name throws it (once, unless [sticky]). */
    var failure: Pair<String, Exception>? = null
    var sticky = false

    private fun check(name: String) {
        val f = failure
        if (f != null && f.first == name) {
            if (!sticky) failure = null
            throw f.second
        }
    }

    override suspend fun search(q: String, sealedOnly: Boolean): List<JsonObject> {
        calls += "search:$q:$sealedOnly"
        check("search")
        return spools
    }

    override suspend fun spool(id: Int): JsonObject {
        calls += "spool:$id"
        check("spool")
        return spools.firstOrNull { (it["id"] as? JsonPrimitive)?.content == id.toString() }
            ?: throw ApiError(404, "not_found", "spool $id was not found")
    }

    override suspend fun tag(uid: String): JsonObject? {
        calls += "tag:$uid"
        tagGate?.await()
        check("tag")
        return tagAnswer
    }

    override suspend fun link(spoolId: Int, tag: String, force: Boolean, dryRun: Boolean, gross: Double?): JsonObject {
        calls += "link:$spoolId:$tag:force=$force:dry=$dryRun:gross=$gross"
        check("link")
        return linkAnswer(force, dryRun)
    }

    override suspend fun update(spoolId: Int, gross: Double?, location: String?, empty: Boolean, dryRun: Boolean): JsonObject {
        calls += "update:$spoolId:gross=$gross:location=$location:empty=$empty:dry=$dryRun"
        check("update")
        return updateAnswer(gross, location, empty, dryRun)
    }

    override suspend fun locations(): List<String> {
        calls += "locations"
        check("locations")
        return locations
    }
}

internal fun jsonArrayOf(vararg items: JsonObject) = JsonArray(items.toList())
internal fun text(s: String) = JsonPrimitive(s)
