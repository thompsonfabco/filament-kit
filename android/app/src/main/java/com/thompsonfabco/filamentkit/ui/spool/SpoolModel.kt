package com.thompsonfabco.filamentkit.ui.spool

import androidx.compose.runtime.mutableStateMapOf
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import java.io.IOException
import kotlin.math.roundToInt

/** The server calls the spool screens need; [of] adapts the real [Api] at each call, tests pass a fake. */
interface SpoolBackend {
    suspend fun search(q: String, sealedOnly: Boolean): List<JsonObject>
    suspend fun tag(uid: String): JsonObject?
    suspend fun link(spoolId: Int, tag: String, force: Boolean, dryRun: Boolean, gross: Double?): JsonObject
    suspend fun update(spoolId: Int, gross: Double?, location: String?, empty: Boolean, dryRun: Boolean): JsonObject
    suspend fun locations(): List<String>

    companion object {
        /** Calls go to whatever [current] returns at that moment, so a re-pair or a trusted certificate reaches the screen. */
        fun of(current: () -> Api): SpoolBackend = object : SpoolBackend {
            override suspend fun search(q: String, sealedOnly: Boolean) = current().search(q, sealedOnly)
            override suspend fun tag(uid: String) = current().tag(uid)
            override suspend fun link(spoolId: Int, tag: String, force: Boolean, dryRun: Boolean, gross: Double?) =
                current().link(spoolId, tag, force, dryRun, gross, null)

            override suspend fun update(spoolId: Int, gross: Double?, location: String?, empty: Boolean, dryRun: Boolean) =
                current().update(spoolId, gross, null, location, empty, dryRun)

            override suspend fun locations() = current().locations()
        }
    }
}

enum class SpoolState { Sealed, Opened, Empty }

/** The fields of a Spoolman spool the screens show; a field the Hub did not send is null. */
data class SpoolSummary(
    val id: Int,
    val brand: String,
    val name: String,
    val material: String,
    val colorHex: String?,
    val location: String?,
    val remaining: Double?,
    /** The net weight of a full spool: the spool's own, else its filament's. */
    val total: Double? = null,
    val state: SpoolState = SpoolState.Opened,
    val tag: String? = null,
    val filamentId: Int? = null,
    val emptyWeight: Double? = null,
    val lot: String? = null,
) {
    /** "Brand Name", else "spool 214" has no name to show. */
    val title: String get() = listOf(brand, name).filter { it.isNotBlank() }.joinToString(" ")

    /** The share left, 0 to 100; null when the Hub gave no weights or the spool is sealed or empty. */
    val percent: Int?
        get() {
            val left = remaining ?: return null
            val all = total?.takeIf { it > 0 } ?: return null
            return (left / all * PERCENT).roundToInt().coerceIn(0, PERCENT)
        }

    private companion object {
        const val PERCENT = 100
    }
}

private const val SEALED_NOTE = "SEALED"

fun JsonObject.toSpoolSummary(): SpoolSummary {
    val filament = this["filament"] as? JsonObject
    val vendor = filament?.get("vendor") as? JsonObject
    fun JsonElement?.text(): String? = (this as? JsonPrimitive)?.contentOrNull
    fun JsonElement?.number(): Double? = (this as? JsonPrimitive)?.doubleOrNull
    val archived = (this["archived"] as? JsonPrimitive)?.booleanOrNull == true
    val sealed = this["comment"].text()?.contains(SEALED_NOTE) == true
    return SpoolSummary(
        id = (this["id"] as? JsonPrimitive)?.intOrNull ?: 0,
        brand = vendor?.get("name").text().orEmpty(),
        name = filament?.get("name").text().orEmpty(),
        material = filament?.get("material").text().orEmpty(),
        colorHex = filament?.get("color_hex").text(),
        location = this["location"].text()?.ifBlank { null },
        remaining = this["remaining_weight"].number(),
        total = (this["initial_weight"].number() ?: filament?.get("weight").number())?.takeIf { it > 0 },
        state = when {
            archived -> SpoolState.Empty
            sealed -> SpoolState.Sealed
            else -> SpoolState.Opened
        },
        tag = storedTag(this),
        filamentId = (filament?.get("id") as? JsonPrimitive)?.intOrNull,
        emptyWeight = (this["spool_weight"].number() ?: filament?.get("spool_weight").number())?.takeIf { it > 0 },
        lot = this["lot_nr"].text()?.ifBlank { null },
    )
}

/** The Hub keeps a spool's tag as a JSON-encoded string in `extra.nfc_id`; blank is no tag. */
private fun storedTag(spool: JsonObject): String? {
    val raw = ((spool["extra"] as? JsonObject)?.get("nfc_id") as? JsonPrimitive)?.contentOrNull ?: return null
    val decoded = runCatching { (Json.parseToJsonElement(raw) as? JsonPrimitive)?.contentOrNull }.getOrNull() ?: raw
    return decoded.trim().ifBlank { null }
}

/** Grams for a sentence: whole numbers plain, otherwise one decimal. */
fun formatGrams(grams: Double): String {
    val whole = grams.roundToInt()
    return if (kotlin.math.abs(grams - whole) < GRAMS_EPSILON) whole.toString() else (grams * TENTHS).roundToInt().div(TENTHS).toString()
}

private const val GRAMS_EPSILON = 0.05
private const val TENTHS = 10.0

/**
 * Why a Hub call failed, in 05 3.5's terms, from the real shapes of `Api`'s errors: status 0 is no route, `bad_response`
 * and an error page without the Hub's `message` are an answer the app cannot read, any other reply carries the Hub's own
 * words. A 401 and a changed certificate are the Hub notices of 3.4.
 */
sealed interface HubFailure {
    data object CertificateChanged : HubFailure
    data object NotPaired : HubFailure
    data object Unreachable : HubFailure
    data object Unexpected : HubFailure
    data object SpoolmanDown : HubFailure
    data class Message(val text: String) : HubFailure

    /** The two Hub notices; a later successful call clears them (05 2.7). */
    val isNotice: Boolean get() = this == CertificateChanged || this == NotPaired
}

fun hubFailure(e: Throwable): HubFailure = when {
    e is FingerprintMismatch -> HubFailure.CertificateChanged
    e is ApiError && e.code == "unauthorized" -> HubFailure.NotPaired
    e is ApiError && e.status == 0 -> HubFailure.Unreachable
    e is ApiError && e.code == "spoolman_unreachable" -> HubFailure.SpoolmanDown
    e is ApiError && e.notFromHub -> HubFailure.Unexpected
    e is ApiError -> HubFailure.Message(e.message)
    e is IOException -> HubFailure.Unreachable
    else -> HubFailure.Unexpected
}

/** Keeps [failure] unless it is a Hub notice: any answer from the Hub means the pairing and certificate work again. */
internal fun HubFailure?.afterSuccess(): HubFailure? = this?.takeUnless { it.isNotice }

/** The last change made on the spool screen, shown as a notice line of kind ok (05 7.2) until the next one. */
sealed interface SpoolResult {
    data class WeightUpdated(val left: Double?) : SpoolResult
    data class Moved(val location: String) : SpoolResult
    data object MarkedEmpty : SpoolResult
    data object TagLinked : SpoolResult
    data object TagMoved : SpoolResult
    data class Loaded(val printer: String, val slot: String) : SpoolResult

    /** The printer accepted the load but has not shown the change yet: a warn line. */
    data class LoadedUnconfirmed(val printer: String, val slot: String) : SpoolResult

    /** The result as one text, to hand it to the spool screen through its saved state or its route. */
    fun encode(): String = when (this) {
        is WeightUpdated -> listOf(WEIGHT, left?.toString().orEmpty())
        is Moved -> listOf(MOVED, location)
        MarkedEmpty -> listOf(EMPTY)
        TagLinked -> listOf(LINKED)
        TagMoved -> listOf(TAG_MOVED)
        is Loaded -> listOf(LOADED, printer, slot)
        is LoadedUnconfirmed -> listOf(UNCONFIRMED, printer, slot)
    }.joinToString(SEPARATOR)

    companion object {
        private const val SEPARATOR = ""
        private const val WEIGHT = "1"
        private const val MOVED = "2"
        private const val EMPTY = "3"
        private const val LINKED = "4"
        private const val TAG_MOVED = "5"
        private const val LOADED = "6"
        private const val UNCONFIRMED = "7"

        /** The result [encode] made; null for anything else. */
        fun decode(text: String): SpoolResult? {
            val p = text.split(SEPARATOR)
            return when {
                p[0] == WEIGHT -> WeightUpdated(p.getOrNull(1)?.toDoubleOrNull())
                p[0] == MOVED && p.size == 2 -> Moved(p[1])
                p[0] == EMPTY -> MarkedEmpty
                p[0] == LINKED -> TagLinked
                p[0] == TAG_MOVED -> TagMoved
                p[0] == LOADED && p.size == 3 -> Loaded(p[1], p[2])
                p[0] == UNCONFIRMED && p.size == 3 -> LoadedUnconfirmed(p[1], p[2])
                else -> null
            }
        }
    }
}

/**
 * The spools the screens have seen, by number: the title the top bar shows and the summary a screen opens with. Memory
 * only; it is emptied when the Hub changes.
 */
object SpoolCache {
    private val seen = mutableStateMapOf<Int, SpoolSummary>()

    fun put(spool: SpoolSummary) {
        if (spool.id != 0) seen[spool.id] = spool
    }

    fun get(id: Int): SpoolSummary? = seen[id]

    /** The top bar's title for spool [id]: its brand and name once seen. */
    fun title(id: Int): String? = seen[id]?.title?.ifBlank { null }

    fun clear() {
        seen.clear()
    }
}
