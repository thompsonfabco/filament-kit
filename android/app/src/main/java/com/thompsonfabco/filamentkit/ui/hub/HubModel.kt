package com.thompsonfabco.filamentkit.ui.hub

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.GettingStarted
import com.thompsonfabco.filamentkit.net.HubAnswer
import com.thompsonfabco.filamentkit.net.HubCheckState
import com.thompsonfabco.filamentkit.ui.home.printersFailure
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale

/** `hub-glance`: the read-only Hub screen (R83 section 5), on the stack of the selected tab. */
@Serializable data object HubGlanceRoute

/** The groups of the Hub screen, in the order it shows them (R83 section 5.1). */
enum class HubGroup(val title: String) {
    Status(HubTexts.GROUP_STATUS),
    GettingStarted(HubTexts.GROUP_GETTING_STARTED),
    Version(HubTexts.GROUP_VERSION),
    Features(HubTexts.GROUP_FEATURES),
    Catalog(HubTexts.GROUP_CATALOG),
    Backups(HubTexts.GROUP_BACKUPS),
    LabelReader(HubTexts.GROUP_LABEL_READER),
    Devices(HubTexts.GROUP_DEVICES),
    RecentlyAdded(HubTexts.GROUP_RECENTLY_ADDED),
}

/** Steps remain and the list is not hidden: the Getting started group and the line on Home are shown. */
fun gettingStartedShown(g: GettingStarted?): Boolean = g != null && !g.hidden && !g.finished && g.total > 0 && g.done < g.total

/** "Getting started on the Hub: 4 of 8 done" while [gettingStartedShown]; null (no line) otherwise. */
fun gettingStartedLine(g: GettingStarted?): String? =
    if (g != null && gettingStartedShown(g)) HubTexts.gettingStartedLine(g.done, g.total) else null

/** One line of a group. */
sealed interface HubLine {
    /** A label over a value. */
    data class Field(val label: String, val value: String) : HubLine

    /** A row of Status: the Hub's own text and its fix line. */
    data class Check(val state: HubCheckState, val text: String, val fix: String?) : HubLine

    /** A sentence on its own. */
    data class Note(val text: String) : HubLine
}

/** A group with what it shows. */
data class HubSection(val group: HubGroup, val lines: List<HubLine>)

/**
 * The Hub's time as an instant: a number is whole seconds since 1970 (what the Hub sends now), a text is ISO 8601 with
 * an offset (an older Hub); null when it is neither.
 */
internal fun hubInstant(raw: String?): Instant? {
    val text = raw?.trim().orEmpty()
    if (text.isEmpty()) return null
    text.toDoubleOrNull()?.let { return if (it.isFinite()) runCatching { Instant.ofEpochSecond(it.toLong()) }.getOrNull() else null }
    return try {
        OffsetDateTime.parse(text).toInstant()
    } catch (_: Exception) {
        null
    }
}

/** [raw] (the Hub's time: seconds since 1970 or ISO 8601 with offset) in the phone's zone and language; the text as given when it is not a time. */
fun hubTime(raw: String?, zone: ZoneId = ZoneId.systemDefault(), locale: Locale = Locale.getDefault()): String? {
    if (raw.isNullOrBlank()) return null
    val at = hubInstant(raw) ?: return raw
    return DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM, FormatStyle.SHORT).withLocale(locale).format(at.atZone(zone))
}

/** Like [hubTime], the day only ("Nov 17, 2026"); a plain `YYYY-MM-DD` text (an older Hub's entry day) is read as that day. */
fun hubDay(raw: String?, zone: ZoneId = ZoneId.systemDefault(), locale: Locale = Locale.getDefault()): String? {
    if (raw.isNullOrBlank()) return null
    val format = DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM).withLocale(locale)
    runCatching { return format.format(LocalDate.parse(raw.trim())) }
    val at = hubInstant(raw) ?: return raw
    return format.format(at.atZone(zone))
}

internal fun deviceKindText(kind: String): String = when (kind) {
    "phone" -> HubTexts.KIND_PHONE
    "pc" -> HubTexts.KIND_PC
    "station" -> HubTexts.KIND_STATION
    "web" -> HubTexts.KIND_WEB
    "reader" -> HubTexts.KIND_READER
    "builtin" -> HubTexts.KIND_BUILTIN
    else -> kind
}

/**
 * What the screen shows, group by group, in order. A group the Hub left out (no part, or an empty list) is not shown;
 * Getting started only while [gettingStartedShown]. Nothing here is built from an address or a secret: the Hub redacts.
 */
fun hubSections(h: HubAnswer, time: (String?) -> String? = { hubTime(it) }): List<HubSection> = buildList {
    if (h.checks.isNotEmpty()) {
        add(HubSection(HubGroup.Status, h.checks.map { HubLine.Check(it.state, it.text, it.fix) }))
    }
    val started = h.gettingStarted
    if (started != null && gettingStartedShown(started)) {
        add(HubSection(HubGroup.GettingStarted, listOf(HubLine.Note(HubTexts.stepsDone(started.done, started.total)))))
    }
    add(HubSection(HubGroup.Version, buildList {
        add(HubLine.Field(HubTexts.INSTALLED, h.version))
        h.newest?.let { n ->
            add(HubLine.Field(HubTexts.NEWEST, n.version))
            time(n.checkedAt)?.let { add(HubLine.Field(HubTexts.LAST_CHECKED, it)) }
        }
        if (h.updateAvailable) add(HubLine.Note(HubTexts.UPDATE_AVAILABLE))
    }))
    if (h.features.isNotEmpty()) {
        add(HubSection(HubGroup.Features, h.features.map { HubLine.Field(it.name, if (it.on) HubTexts.ON else HubTexts.OFF) }))
    }
    h.catalog?.let { c ->
        add(HubSection(HubGroup.Catalog, listOf(
            HubLine.Field(HubTexts.CATALOG_VERSION, c.version ?: HubTexts.NOT_KNOWN),
            HubLine.Field(HubTexts.LAST_CHECKED, time(c.checkedAt) ?: HubTexts.NEVER),
        )))
    }
    h.backup?.let { b ->
        add(HubSection(HubGroup.Backups, listOf(
            HubLine.Field(HubTexts.LAST_BACKUP, time(b.lastAt) ?: HubTexts.NEVER),
            HubLine.Field(HubTexts.NIGHTLY_BACKUP, if (b.nightly) HubTexts.ON else HubTexts.OFF),
        )))
    }
    h.reader?.let { r ->
        add(HubSection(HubGroup.LabelReader, listOf(
            HubLine.Field(HubTexts.ENGINE, r.engine),
            HubLine.Field(HubTexts.KEY, if (r.keySet) HubTexts.KEY_SET else HubTexts.KEY_NOT_SET),
        )))
    }
    if (h.devices.isNotEmpty()) {
        add(HubSection(HubGroup.Devices, h.devices.map { d ->
            val parts = buildList {
                if (d.kind.isNotBlank()) add(deviceKindText(d.kind))
                add(d.version ?: HubTexts.VERSION_NOT_KNOWN)
                time(d.lastSeen)?.let { add("${HubTexts.LAST_SEEN} $it") }
                if (d.outOfDate) add(HubTexts.OUT_OF_DATE)
            }
            HubLine.Field(if (d.thisOne) "${d.name} (${HubTexts.THIS_DEVICE})" else d.name, parts.joinToString(" · "))
        }))
    }
    h.recordsKept?.let { add(HubSection(HubGroup.RecentlyAdded, listOf(HubLine.Field(HubTexts.RECORDS_KEPT, it.toString())))) }
}

/** What the Hub screen and Home's line draw from: [hub] is the last answer, kept while a newer read fails. */
data class HubUi(
    val hub: HubAnswer? = null,
    val loading: Boolean = false,
    /** A read has finished (with an answer, a 404 or a failure). */
    val loaded: Boolean = false,
    /** 404: an older Hub without `GET api/hub`. */
    val unavailable: Boolean = false,
    /** The Hub's own refusal, if that was the failure. */
    val message: String? = null,
    /** The failure was no route to the Hub, or an answer not understood, with no message of the Hub's. */
    val failed: Boolean = false,
    /** When [hub] was read (epoch millis), for the offline notice. */
    val loadedAt: Long? = null,
)

/**
 * The Hub's `GET api/hub`. [load] asks each time (it resolves the session's current client, so a re-pair reaches it) and
 * returns null for an older Hub (404); a failed read keeps the answer already shown.
 */
class HubViewModel(
    private val load: suspend () -> HubAnswer?,
    private val now: () -> Long = System::currentTimeMillis,
) : ViewModel() {
    private val _state = MutableStateFlow(HubUi())
    val state: StateFlow<HubUi> = _state.asStateFlow()

    fun refresh() {
        if (_state.value.loading) return
        _state.update { it.copy(loading = true) }
        viewModelScope.launch {
            try {
                val answer = load()
                _state.value = if (answer == null) {
                    HubUi(loaded = true, unavailable = true)
                } else {
                    HubUi(hub = answer, loaded = true, loadedAt = now())
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val failure = printersFailure(e)
                _state.update { it.copy(loading = false, loaded = true, failed = true, message = failure.message) }
            }
        }
    }
}
