package com.thompsonfabco.filamentkit.alerts

import java.time.Instant
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

// The Hub's events and alerts as the app reads them (R80 section 8 and E4). Parsing is lenient: unknown keys are
// ignored and a missing optional field is a default, so an older or newer Hub never crashes the app.

/** An event's `severity`; the order is the order of seriousness. */
enum class AlertSeverity {
    Info, Ok, Warn, Bad;

    companion object {
        fun of(wire: String?): AlertSeverity = when (wire) {
            "bad" -> Bad
            "warn" -> Warn
            "ok" -> Ok
            else -> Info
        }
    }
}

/** A lasting state an event raises or clears: `key` such as `print-paused:p-3`, `state` `raised` or `cleared`. */
data class AlertCondition(val key: String, val state: String) {
    val raised: Boolean get() = state == "raised"
}

/** What the Hub says the action opens: `place` is `printer`, `running_low`, `storage_use`, `devices` or `backups`. */
data class AlertAction(val place: String?, val id: String?)

/** One event of `GET api/events`. Titles and sentences come from the Hub ([title], [text]); they are never rebuilt. */
data class AlertEvent(
    val id: Long,
    /** The event's time as epoch millis; null when the Hub's time could not be read. */
    val atMillis: Long?,
    val kind: String,
    val severity: AlertSeverity,
    val condition: AlertCondition?,
    /** An alert type that is on covers this event. */
    val alert: Boolean,
    val title: String,
    val text: String,
    val action: AlertAction,
    val data: JsonObject = JsonObject(emptyMap()),
) {
    /** What a banner or notification is keyed by: the condition, else the event itself. */
    val key: String get() = condition?.key ?: "event:$id"
}

/** The test alert the Hub hands out once (`test` in an events answer). */
data class AlertTest(val title: String, val text: String)

/** One answer of `GET api/events`. */
data class EventsAnswer(
    val events: List<AlertEvent>,
    val next: Long?,
    val conditions: List<AlertEvent>,
    val oldest: Long?,
    /** Events between the cursor and [oldest] were deleted by age. */
    val gap: Boolean,
    val test: AlertTest?,
)

/** What `GET api/events` is asked: a cursor [since], or (the first time) a time [sinceAt] in UTC. */
data class EventsQuery(
    val since: Long?,
    val sinceAt: String?,
    val waitS: Int,
    val alertOnly: Boolean = true,
    val limit: Int? = null,
)

/** `GET api/alerts`. */
data class AlertType(val key: String, val title: String, val on: Boolean)

data class AlertsConfig(val types: List<AlertType>, val runningLowG: Int?, val storageWarnPercent: Int?, val storageBadPercent: Int?)

/** One row of `GET api/spools/low`. */
data class LowSpool(
    val id: Int,
    val filament: String,
    val material: String,
    val color: String?,
    val remainingG: Double?,
    val location: String?,
    val inStock: Int,
    val lastOne: Boolean,
)

data class LowSpools(val thresholdG: Int?, val spools: List<LowSpool>)

object AlertParsing {
    fun events(root: JsonElement): EventsAnswer {
        val o = root as? JsonObject ?: JsonObject(emptyMap())
        return EventsAnswer(
            events = o.list("events").mapNotNull(::event).sortedBy { it.id },
            next = o.long("next"),
            conditions = o.list("conditions").mapNotNull(::event),
            oldest = o.long("oldest"),
            gap = o.bool("gap") ?: false,
            test = (o["test"] as? JsonObject)?.let { t ->
                val title = t.str("title").orEmpty()
                val text = t.str("text").orEmpty()
                if (title.isBlank() && text.isBlank()) null else AlertTest(title, text)
            },
        )
    }

    /** Null for an element without an id (nothing can be keyed by it). */
    fun event(element: JsonElement): AlertEvent? {
        val o = element as? JsonObject ?: return null
        val id = o.long("id") ?: return null
        val condition = (o["condition"] as? JsonObject)?.let { c ->
            c.str("key")?.takeIf { it.isNotBlank() }?.let { AlertCondition(it, c.str("state").orEmpty()) }
        }
        val action = o["action"] as? JsonObject
        return AlertEvent(
            id = id,
            atMillis = o.str("at")?.let(::parseTime),
            kind = o.str("kind").orEmpty(),
            severity = AlertSeverity.of(o.str("severity")),
            condition = condition,
            alert = o.bool("alert") ?: false,
            title = o.str("title").orEmpty(),
            text = o.str("text").orEmpty(),
            action = AlertAction(action?.str("place"), action?.str("id")),
            data = o["data"] as? JsonObject ?: JsonObject(emptyMap()),
        )
    }

    fun alerts(root: JsonElement): AlertsConfig {
        val o = root as? JsonObject ?: JsonObject(emptyMap())
        return AlertsConfig(
            types = o.list("types").mapNotNull { t ->
                val x = t as? JsonObject ?: return@mapNotNull null
                x.str("key")?.let { AlertType(it, x.str("title").orEmpty(), x.bool("on") ?: false) }
            },
            runningLowG = o.long("running_low_g")?.toInt(),
            storageWarnPercent = o.long("storage_warn_percent")?.toInt(),
            storageBadPercent = o.long("storage_bad_percent")?.toInt(),
        )
    }

    fun lowSpools(root: JsonElement): LowSpools {
        val o = root as? JsonObject ?: JsonObject(emptyMap())
        return LowSpools(
            thresholdG = o.long("threshold_g")?.toInt(),
            spools = o.list("spools").mapNotNull { s ->
                val x = s as? JsonObject ?: return@mapNotNull null
                val id = x.long("id")?.toInt() ?: return@mapNotNull null
                LowSpool(
                    id = id,
                    filament = x.str("filament").orEmpty(),
                    material = x.str("material").orEmpty(),
                    color = x.str("color")?.takeIf { it.isNotBlank() },
                    remainingG = (x["remaining_g"] as? JsonPrimitive)?.doubleOrNull,
                    location = x.str("location")?.takeIf { it.isNotBlank() },
                    inStock = x.long("in_stock")?.toInt() ?: 0,
                    lastOne = x.bool("last_one") ?: false,
                )
            },
        )
    }

    /** The Hub's time (`2026-11-17T04:12:09Z`, UTC) as epoch millis; null when it is not a time. */
    fun parseTime(text: String): Long? = try {
        Instant.parse(text).toEpochMilli()
    } catch (_: Exception) {
        null
    }

    /** [millis] as the Hub's time for `since_at`. */
    fun formatTime(millis: Long): String = Instant.ofEpochSecond(Math.floorDiv(millis, 1000L)).toString()

    private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull
    private fun JsonObject.long(key: String): Long? = (this[key] as? JsonPrimitive)?.longOrNull
    private fun JsonObject.bool(key: String): Boolean? = (this[key] as? JsonPrimitive)?.booleanOrNull
    private fun JsonObject.list(key: String): List<JsonElement> = (this[key] as? JsonArray) ?: emptyList()
}
