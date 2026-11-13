package com.thompsonfabco.filamentkit.ui.history

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.HistoryChange
import com.thompsonfabco.filamentkit.net.HistoryRecord
import com.thompsonfabco.filamentkit.net.HistoryRevision
import com.thompsonfabco.filamentkit.net.HistorySaved
import com.thompsonfabco.filamentkit.net.HistorySpool
import com.thompsonfabco.filamentkit.net.IntakeHistory
import com.thompsonfabco.filamentkit.net.RevisionProposal
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.put
import java.text.DecimalFormat
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.temporal.ChronoUnit

/** The intake history routes (2026-11-12-1031 handoff); [of] adapts the Api, tests pass a fake. */
interface HistoryBackend {
    suspend fun list(): IntakeHistory
    suspend fun record(id: String): HistoryRecord
    suspend fun photo(id: String, n: Int): ByteArray
    suspend fun revise(id: String, note: String, item: Int?): RevisionProposal
    suspend fun applyProposal(id: String, proposal: String): HistoryRecord
    suspend fun applyValues(id: String, item: Int, values: JsonObject): HistoryRecord
    suspend fun undo(id: String, revision: Int): HistoryRecord

    companion object {
        /** Every call goes to the Api [current] gives at that moment (a trusted certificate or a re-pair is used at once). */
        fun of(current: () -> Api): HistoryBackend = object : HistoryBackend {
            override suspend fun list() = current().intakeHistory()
            override suspend fun record(id: String) = current().intakeRecord(id)
            override suspend fun photo(id: String, n: Int) = current().intakePhoto(id, n)
            override suspend fun revise(id: String, note: String, item: Int?) = current().reviseIntake(id, note, item)
            override suspend fun applyProposal(id: String, proposal: String) = current().applyProposal(id, proposal)
            override suspend fun applyValues(id: String, item: Int, values: JsonObject) = current().applyValues(id, item, values)
            override suspend fun undo(id: String, revision: Int) = current().undoIntake(id, revision)
        }
    }
}

/** The four groups of a record's fields (05-android-app 10.2). */
enum class RecentGroup(@StringRes val title: Int) {
    Identity(R.string.recent_group_identity),
    Weights(R.string.recent_group_weights),
    Temperatures(R.string.recent_group_temperatures),
    Other(R.string.recent_group_other),
}

/**
 * How a field's text goes back to JSON, by the Hub's rule: text as it is, a number above 0 ([Positive]), whole degrees
 * from 1 to 499 ([Degrees]), a range written "190-230", or six hex digits.
 */
enum class FieldKind { Text, Positive, Degrees, Range, Colour }

/** A field of a saved item, in the order the screens show it. [wire] is the Hub's name for it. */
enum class RecentField(
    val wire: String,
    @StringRes val label: Int,
    val group: RecentGroup,
    @StringRes val unit: Int? = null,
    val kind: FieldKind = FieldKind.Text,
) {
    Vendor("vendor", R.string.recent_field_brand, RecentGroup.Identity),
    Name("name", R.string.recent_field_name, RecentGroup.Identity),
    Material("material", R.string.recent_field_material, RecentGroup.Identity),
    Colour("color_hex", R.string.recent_field_colour, RecentGroup.Identity, kind = FieldKind.Colour),
    Net("net", R.string.recent_field_net_weight, RecentGroup.Weights, R.string.unit_g, FieldKind.Positive),
    Tare("tare", R.string.recent_field_empty_weight, RecentGroup.Weights, R.string.unit_g, FieldKind.Positive),
    Density("density", R.string.recent_field_density, RecentGroup.Weights, R.string.unit_g_cm3, FieldKind.Positive),
    Nozzle("nozzle", R.string.recent_field_nozzle, RecentGroup.Temperatures, R.string.unit_c, FieldKind.Degrees),
    Bed("bed", R.string.recent_field_bed, RecentGroup.Temperatures, R.string.unit_c, FieldKind.Degrees),
    NozzleRange("nozzle_range", R.string.recent_field_nozzle_range, RecentGroup.Temperatures, R.string.unit_c, FieldKind.Range),
    BedRange("bed_range", R.string.recent_field_bed_range, RecentGroup.Temperatures, R.string.unit_c, FieldKind.Range),
    Price("price_per_kg", R.string.recent_field_price, RecentGroup.Other, kind = FieldKind.Positive),
    Line("line", R.string.recent_field_line, RecentGroup.Other);

    /** Brand, name and material can't be cleared (the Hub refuses an empty one). */
    val required: Boolean get() = this == Vendor || this == Name || this == Material

    companion object {
        fun of(wire: String): RecentField? = entries.firstOrNull { it.wire == wire }
    }
}

/** What is wrong with a typed value. */
enum class FieldError { Required, Whole, Degrees, DegreesMax, Grams, Density, Price, Range, Colour }

/** A typed value turned into JSON, or the reason it can't be. */
sealed interface Parsed {
    data class Ok(val value: JsonElement) : Parsed
    data class Bad(val error: FieldError) : Parsed
}

/** Values of a record as text, and typed text back to values. */
object RecentValues {
    /** One value as text: numbers without a needless ".0", a range as "190–230"; null when there is nothing. */
    fun text(v: JsonElement?): String? = when (v) {
        null, JsonNull -> null
        is JsonArray -> v.map { text(it) }.takeIf { parts -> parts.all { it != null } }?.joinToString("–")
        is JsonPrimitive -> if (v.isString) v.content.ifBlank { null } else v.doubleOrNull?.let(::number) ?: v.content
        is JsonObject -> v.toString()
    }

    /** The form text of a saved value: blank for nothing. */
    fun formText(v: JsonElement?): String = text(v).orEmpty()

    private fun number(d: Double): String = if (d == Math.floor(d) && kotlin.math.abs(d) < 1e12) d.toLong().toString() else d.toString()

    /**
     * The edit form's text back to JSON for [field], by the Hub's rule (intake_history `_check_values`); blank clears
     * the value. A range goes as the text "190-230", temperatures as whole numbers.
     */
    fun parse(text: String, field: RecentField): Parsed {
        val t = text.trim()
        if (t.isEmpty()) return if (field.required) Parsed.Bad(FieldError.Required) else Parsed.Ok(JsonNull)
        return when (field.kind) {
            FieldKind.Text -> Parsed.Ok(JsonPrimitive(t))
            FieldKind.Positive -> {
                val n = t.toDoubleOrNull()?.takeIf { it.isFinite() && it > 0 }
                if (n == null) Parsed.Bad(positiveError(field)) else Parsed.Ok(JsonPrimitive(n))
            }
            FieldKind.Degrees -> {
                val n = t.toDoubleOrNull()?.takeIf { it.isFinite() }
                when {
                    n == null || n != Math.floor(n) -> Parsed.Bad(FieldError.Whole)
                    n <= 0 -> Parsed.Bad(FieldError.Degrees)
                    n >= MAX_DEGREES -> Parsed.Bad(FieldError.DegreesMax)
                    else -> Parsed.Ok(JsonPrimitive(n.toInt()))
                }
            }
            FieldKind.Range -> {
                val nums = t.split('-', '–', ',').map { it.trim() }.filter { it.isNotEmpty() }.map { it.toDoubleOrNull() }
                if (nums.size == 2 && nums.all { it != null && it.isFinite() && it > 0 }) {
                    Parsed.Ok(JsonPrimitive(nums.joinToString("-") { number(it!!) }))
                } else {
                    Parsed.Bad(FieldError.Range)
                }
            }
            FieldKind.Colour -> {
                val hex = t.removePrefix("#").uppercase()
                if (hex.length == HEX_DIGITS && hex.all { it.digitToIntOrNull(HEX_RADIX) != null }) {
                    Parsed.Ok(JsonPrimitive(hex))
                } else {
                    Parsed.Bad(FieldError.Colour)
                }
            }
        }
    }

    private fun positiveError(field: RecentField) = when (field) {
        RecentField.Density -> FieldError.Density
        RecentField.Price -> FieldError.Price
        else -> FieldError.Grams
    }

    private const val MAX_DEGREES = 500

    private const val HEX_DIGITS = 6
    private const val HEX_RADIX = 16

    /** "2026-11-12 14:05" in [zone]; the raw text when it can't be read. */
    fun time(iso: String, zone: ZoneId = ZoneId.systemDefault()): String = try {
        val t = OffsetDateTime.parse(iso).atZoneSameInstant(zone).toLocalDateTime().truncatedTo(ChronoUnit.MINUTES)
        t.toLocalDate().toString() + " " + t.toLocalTime().toString()
    } catch (_: Exception) {
        iso
    }

    /** Photo bytes as megabytes with one decimal ("14.2"). */
    fun megabytes(bytes: Long): String = DecimalFormat("0.0").format(bytes / BYTES_PER_MB)

    private const val BYTES_PER_MB = 1_048_576.0

    /** "Polymaker PolyTerra PLA Charcoal Black", the filaments of a record's spools; null when none has a name. */
    fun filaments(spools: List<HistorySpool>): String? = spools
        .map { listOfNotNull(it.vendor, it.name).joinToString(" ").trim() }
        .filter { it.isNotEmpty() }.distinct().joinToString(", ").ifEmpty { null }

    /** The record's spool numbers, each once, in order. */
    fun spoolIds(spools: List<HistorySpool>): List<Int> = spools.mapNotNull { it.spoolId }.distinct()

    fun idList(ids: List<Int>): String = ids.joinToString(", ")
}

/** A mark beside a field value the reader was not sure of (05-android-app 6.3, the part that needs no Hub levels). */
enum class FieldMark(@DrawableRes val shape: Int, @StringRes val word: Int, val warn: Boolean) {
    Estimated(R.drawable.sw_st_triangle, R.string.recent_mark_estimated, true),
    NotOnLabel(R.drawable.sw_st_hollow, R.string.confidence_not_on_label, false),
}

/** The record state vocabulary (05-android-app 10.1): shape, word and tone. */
enum class IntakeState(val wire: String, @DrawableRes val shape: Int, @StringRes val word: Int, val info: Boolean) {
    Detected("detected", R.drawable.sw_st_hollow, R.string.status_as_detected, false),
    RevisedAi("revised_ai", R.drawable.sw_ic_info, R.string.status_revised_ai, true),
    Edited("edited", R.drawable.sw_ic_pencil, R.string.status_edited, true);

    companion object {
        fun of(wire: String): IntakeState? = entries.firstOrNull { it.wire == wire }
    }
}

/** The source in words: a known word from the catalogue, or the Hub's own value as it is given. */
class SourceLabel(@StringRes val word: Int?, val raw: String)

/** Records without photos were added by hand; the others say where the photos came from. */
fun sourceLabel(source: String, photos: Int): SourceLabel = when {
    photos == 0 -> SourceLabel(R.string.recent_source_hand, source)
    source == "phone" -> SourceLabel(R.string.recent_source_phone, source)
    source == "station" -> SourceLabel(R.string.recent_source_station, source)
    else -> SourceLabel(null, source)
}

/** The Hub's reason a request failed, before it becomes words (the screen picks the catalogue text). */
sealed interface RecentFailure {
    data object Offline : RecentFailure
    data object Unexpected : RecentFailure
    data object SpoolmanDown : RecentFailure
    data object ReaderOff : RecentFailure
    data object DailyLimit : RecentFailure
    data object ReaderBusy : RecentFailure
    data object KeyRefused : RecentFailure
    data object CloudDown : RecentFailure
    data object Unreadable : RecentFailure
    data object NoPhoto : RecentFailure

    /** A refusal with the Hub's own message, shown as given. */
    data class Hub(val message: String) : RecentFailure
}

/** 05-android-app 3.5 and 6.2 by the Hub's error code; a reply with no message of the Hub's own is an unknown answer. */
internal fun failureOf(e: ApiError): RecentFailure = when (e.code) {
    "offline", "local_network" -> RecentFailure.Offline
    "bad_response" -> RecentFailure.Unexpected
    "spoolman_unreachable" -> RecentFailure.SpoolmanDown
    "ai_off" -> RecentFailure.ReaderOff
    "daily_cap" -> RecentFailure.DailyLimit
    "local_busy", "rate_limited" -> RecentFailure.ReaderBusy
    "bad_key" -> RecentFailure.KeyRefused
    "unreachable" -> RecentFailure.CloudDown
    "api_error", "refused", "truncated" -> RecentFailure.Unreadable
    "no_photo" -> RecentFailure.NoPhoto
    else -> if (e.notFromHub) RecentFailure.Unexpected else RecentFailure.Hub(e.message)
}

/** The record's read item that saved item [item] came from, to mark estimated and unread fields. */
object RecentMarks {
    /**
     * The read item saved item [item] came from. Saved items are numbered in the add's order (only items that wrote
     * spools), not the read's, so a removed card or an item with no spools shifts them: the one read item with the
     * same vendor, name and material; else, when nothing was dropped (as many read as saved), the read item at the
     * same place if its material matches; else null (no mark beats a mark on the wrong spool).
     */
    fun readItem(r: HistoryRecord, item: Int): JsonObject? {
        val read = r.read?.items.orEmpty()
        val saved = r.saved.firstOrNull { it.item == item } ?: return null
        val key = matchKey(saved.values)
        read.singleOrNull { matchKey(it) == key }?.let { return it }
        if (read.size != r.saved.size) return null
        return read.getOrNull(item)?.takeIf { matchKey(it).last() == key.last() }
    }

    private fun matchKey(o: JsonObject): List<String> = listOf(RecentField.Vendor, RecentField.Name, RecentField.Material).map {
        (o[it.wire] as? JsonPrimitive)?.contentOrNull?.trim()?.lowercase().orEmpty()
    }

    /**
     * The fields of [saved] to mark: "Estimated" when the read listed the field in its `estimates` and the value is
     * still what was read, "Not on the label" when the read left it empty and it still is. Without the read (a record
     * added by hand) there is nothing to mark; a field changed since the read has no mark.
     */
    fun of(r: HistoryRecord, saved: HistorySaved): Map<RecentField, FieldMark> {
        val read = readItem(r, saved.item) ?: return emptyMap()
        val estimates = (read["estimates"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.toSet()
        val marks = mutableMapOf<RecentField, FieldMark>()
        for (f in RecentField.entries) {
            val was = RecentValues.text(read[f.wire])
            val now = RecentValues.text(saved.values[f.wire])
            when {
                was != now -> Unit
                was == null -> marks[f] = FieldMark.NotOnLabel
                f.wire in estimates -> marks[f] = FieldMark.Estimated
            }
        }
        return marks
    }
}

/** What the Label Reader said about an item when it read the photos: colour, how sure, and its least sure fields. */
class ReadDetails(
    /** The colour's name; null when the reader gave none or could not name it ([unnamed]). */
    val colourName: String?,
    val colourFamily: String?,
    /** The reader gave a colour but not a name from the library. */
    val unnamed: Boolean,
    /** How sure the reader was of the item, in percent. */
    val percent: Int?,
    /** The Hub's names of the fields the reader was least sure of (below [SURE]). */
    val leastSure: List<String>,
) {
    companion object {
        /** A field below this is "least sure" (the Hub's own threshold for an unsure item). */
        const val SURE = 0.78
        private const val PERCENT = 100

        /** The details of saved item [item] where the Hub sent any for its read item; null when it sent none. */
        fun of(r: HistoryRecord, item: Int): ReadDetails? {
            val read = RecentMarks.readItem(r, item) ?: return null
            fun text(key: String) = (read[key] as? JsonPrimitive)?.takeIf { it.isString }?.content?.trim()?.takeIf { it.isNotEmpty() }
            val name = text("color_name")?.takeIf { it != "unknown" }
            val named = text("color_name") != null
            val family = text("color_family")
            val sure = (read["confidence"] as? JsonPrimitive)?.takeIf { !it.isString }?.contentOrNull?.toDoubleOrNull()
            val low = (read["field_confidence"] as? JsonObject).orEmpty()
                .filter { (_, v) -> ((v as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull() ?: 1.0) < SURE }.keys.toList()
            val d = ReadDetails(name, family, named && name == null, sure?.let { Math.round(it * PERCENT).toInt() }, low)
            return d.takeIf { name != null || family != null || named || it.percent != null || it.leastSure.isNotEmpty() }
        }
    }
}

/** One change of a revision for every spool it applied to: the Hub writes one entry per spool and field. */
class MergedChange(val field: String, val old: JsonElement?, val new: JsonElement?, val spoolIds: List<Int>)

/** Identical entries across spools become one; the order of first appearance stays. */
fun mergedChanges(changes: List<HistoryChange>): List<MergedChange> =
    changes.groupBy { Triple(it.field, it.old, it.new) }.map { (k, v) ->
        MergedChange(k.first, k.second, k.third, v.mapNotNull { it.spoolId }.distinct())
    }

data class HistoryListState(
    val history: IntakeHistory? = null,
    val loading: Boolean = false,
    val error: RecentFailure? = null,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
    /** When [history] was loaded (epoch milliseconds), for the offline notice. */
    val loadedAt: Long? = null,
) {
    val offline: Boolean get() = error == RecentFailure.Offline

    /** Whether the Hub reads labels; null while unknown (not loaded yet), which is not "off". */
    val aiAvailable: Boolean? get() = history?.ai
}

/** Keeps fetched photos for the visit (a list and a record share them), so a photo is downloaded once. */
class PhotoCache {
    private val bytes = mutableMapOf<String, ByteArray>()
    fun get(id: String, n: Int): ByteArray? = synchronized(bytes) { bytes[key(id, n)] }
    fun put(id: String, n: Int, b: ByteArray) = synchronized(bytes) { bytes[key(id, n)] = b }
    private fun key(id: String, n: Int) = id + "/" + n
}

/** The list (newest first) and the shared photo cache. */
class HistoryListViewModel(
    private val backend: HistoryBackend,
    private val now: () -> Long = System::currentTimeMillis,
) : ViewModel() {
    private val _state = MutableStateFlow(HistoryListState())
    val state: StateFlow<HistoryListState> = _state.asStateFlow()
    val photos = PhotoCache()

    fun refresh() {
        if (_state.value.loading) return
        _state.update { it.copy(loading = true) }
        viewModelScope.launch {
            guard(_state, { f -> _state.update { it.copy(error = f) } }, { u, m -> copy(unauthorized = u || unauthorized, mismatch = m ?: mismatch) }) {
                val h = backend.list()
                _state.update { it.copy(history = h, error = null, loadedAt = now(), unauthorized = false, mismatch = null) }
            }
            _state.update { it.copy(loading = false) }
        }
    }

    private var client: Any? = null
    private var clientKnown = false

    /** The session's client as the screen sees it now: a different one (paired again) than last time reloads. */
    fun clientSeen(now: Any?) {
        val changed = clientKnown && client !== now
        client = now
        clientKnown = true
        if (changed) refresh()
    }

    /** Loads the list once when nothing is loaded or loading (a record restored on its own needs the Label Reader flag). */
    fun ensureLoaded() {
        val s = _state.value
        if (s.history == null && !s.loading) refresh()
    }

    /** Photo [n] of record [id], from the cache or the Hub; null when it can't be had. */
    suspend fun photo(id: String, n: Int): ByteArray? = photos.get(id, n) ?: try {
        backend.photo(id, n).also { photos.put(id, n, it) }
    } catch (e: CancellationException) {
        throw e
    } catch (_: Exception) {
        null
    }
}

/** The edit form (05-android-app 10.3): the texts typed so far against the texts it opened with. */
data class EditUi(
    val item: Int,
    val original: Map<RecentField, String>,
    val texts: Map<RecentField, String>,
    val busy: Boolean = false,
    val errors: Map<RecentField, FieldError> = emptyMap(),
    val failure: RecentFailure? = null,
    val nothingChanged: Boolean = false,
) {
    /** Fields whose text differs from what the form opened with. */
    val changed: List<RecentField> get() = RecentField.entries.filter { texts[it].orEmpty().trim() != original[it].orEmpty().trim() }
    val dirty: Boolean get() = changed.isNotEmpty()
}

/** The Label Reader panel (05-android-app 10.4). */
sealed interface Ask {
    data object Idle : Ask
    data object Waiting : Ask
    data class Proposal(val proposal: RevisionProposal) : Ask
    data object NoChange : Ask
    data class Accepted(val count: Int, val revision: Int) : Ask
    data object Discarded : Ask
    /** A request failed; [proposal] is kept when it was the accept that failed, so "Try again" accepts it again. */
    data class Failed(val failure: RecentFailure, val proposal: RevisionProposal? = null) : Ask
}

/** A hand edit that the Hub took: the item and the fields that were sent. */
data class SavedEdit(val item: Int, val fields: List<RecentField>)

data class RecordState(
    val record: HistoryRecord? = null,
    val loading: Boolean = false,
    val error: RecentFailure? = null,
    val loadedAt: Long? = null,
    val ask: Ask = Ask.Idle,
    /** The note was empty when it was sent: the field shows its error until the person types. */
    val noteMissing: Boolean = false,
    val applyBusy: Boolean = false,
    val edit: EditUi? = null,
    /** The form was asked for and the record has no such item: the screen says so (never while it opens or closes). */
    val editUnavailable: Boolean = false,
    /** What the last hand edit sent, for the result line of its Fields panel. */
    val saved: SavedEdit? = null,
    val undoAsk: Boolean = false,
    val undoBusy: Boolean = false,
    /** The revision just undone, for the result lines of the Revisions panel. */
    val undone: HistoryRevision? = null,
    val undoFailure: RecentFailure? = null,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
) {
    /** The Hub cannot be reached: what needs it is disabled (05-android-app 3.2). */
    val offline: Boolean get() = error == RecentFailure.Offline

    /** The newest revision not undone, which Undo takes back (null: nothing to undo). */
    val undoTarget: HistoryRevision? get() = record?.takeIf { it.undoable }?.revisions?.lastOrNull { !it.undone }
}

/** Two values are the same when they read the same: 140.0 and 140, "190-230" and the range 190–230, nothing and null. */
internal fun sameValue(a: JsonElement?, b: JsonElement?): Boolean = norm(a) == norm(b)

private fun norm(v: JsonElement?): String? = RecentValues.text(v)?.replace('–', '-')?.trim()

/** One record: load, ask the Label Reader (proposal, then accept or discard), edit by hand, undo. */
class RecordViewModel(
    private val backend: HistoryBackend,
    private val id: String,
    private val now: () -> Long = System::currentTimeMillis,
) : ViewModel() {
    private val _state = MutableStateFlow(RecordState())
    val state: StateFlow<RecordState> = _state.asStateFlow()
    private var lastNote = ""
    private var client: Any? = null
    private var clientKnown = false

    /** The session's client as a screen sees it now: a different one (paired again) than last time reloads the record. */
    fun clientSeen(now: Any?) {
        val changed = clientKnown && client !== now
        client = now
        clientKnown = true
        if (changed) load()
    }

    /** The connection is back: leave the offline state at once, keeping what was typed. */
    fun hubBack() {
        if (_state.value.offline) load()
    }

    /** The item whose form was just saved: the screen leaving must not open it again while it fades out. */
    private var sealed: Int? = null

    /** A 401 or a changed certificate keeps what the person typed and shows the Hub notice; whatever was running stops. */
    private val auth: RecordState.(Boolean, Pair<String, String>?) -> RecordState = { u, m ->
        copy(
            unauthorized = u || unauthorized, mismatch = m ?: mismatch, edit = edit?.copy(busy = false),
            ask = if (ask == Ask.Waiting) Ask.Idle else ask, undoAsk = false,
        )
    }

    /** A failure leaves the data on screen as it was; the Hub being out of reach is the offline state. */
    private fun RecordState.failed(f: RecentFailure): RecordState = if (f == RecentFailure.Offline) copy(error = f) else this

    /** Loads the record when it isn't there yet (the edit screen can be the first one restored). */
    fun ensureLoaded() {
        val s = _state.value
        if (s.record == null && !s.loading) load()
    }

    fun load() {
        if (_state.value.loading) return
        _state.update { it.copy(loading = true) }
        viewModelScope.launch {
            guard(_state, { f -> _state.update { it.copy(error = f) } }, auth) {
                val r = backend.record(id)
                _state.update {
                    it.copy(
                        record = r, error = null, loadedAt = now(), unauthorized = false, mismatch = null,
                        edit = it.edit?.let { e -> if (e.failure == RecentFailure.Offline) e.copy(failure = null) else e },
                    )
                }
            }
            _state.update { it.copy(loading = false) }
        }
    }

    /** Asks the Label Reader about every item of the record; an empty note is not sent. */
    fun ask(note: String) {
        val n = note.trim()
        if (_state.value.ask == Ask.Waiting) return
        if (n.isEmpty()) {
            _state.update { it.copy(noteMissing = true) }
            return
        }
        lastNote = n
        _state.update { it.copy(ask = Ask.Waiting, noteMissing = false, saved = null, undone = null) }
        viewModelScope.launch {
            guard(_state, { f -> _state.update { it.copy(ask = Ask.Failed(f)).failed(f) } }, auth) {
                val p = backend.revise(id, n, null)
                _state.update { it.copy(ask = if (p.changes.isEmpty()) Ask.NoChange else Ask.Proposal(p), error = null, unauthorized = false, mismatch = null) }
            }
        }
    }

    /** "Try again": accepts the proposal again when that is what failed, else asks again with the same note. */
    fun retry() {
        val a = _state.value.ask
        if (a is Ask.Failed && a.proposal != null) {
            _state.update { it.copy(ask = Ask.Proposal(a.proposal)) }
            accept()
        } else {
            ask(lastNote)
        }
    }

    fun noteTyped() = _state.update { if (it.noteMissing) it.copy(noteMissing = false) else it }

    fun discard() = _state.update { if (it.ask is Ask.Proposal) it.copy(ask = Ask.Discarded) else it }

    fun accept() {
        val p = (_state.value.ask as? Ask.Proposal)?.proposal ?: return
        if (_state.value.applyBusy) return
        _state.update { it.copy(applyBusy = true) }
        viewModelScope.launch {
            guard(_state, { f -> _state.update { it.copy(ask = Ask.Failed(f, p)).failed(f) } }, auth) {
                val r = backend.applyProposal(id, p.proposal)
                _state.update { it.copy(record = r, error = null, unauthorized = false, mismatch = null, ask = Ask.Accepted(p.changes.size, r.revisions.lastOrNull()?.n ?: 0)) }
            }
            _state.update { it.copy(applyBusy = false) }
        }
    }

    // ---- edit by hand ----

    /** The person asked for the form: it may open on [item] again. */
    fun beginEdit(item: Int) {
        if (sealed == item) sealed = null
        _state.update { it.copy(editUnavailable = false) }
    }

    /** Opens the form on saved item [item] once the record is there; a form already open on it stays as typed. */
    fun startEdit(item: Int) {
        val s = _state.value
        if (s.edit?.item == item || sealed == item) return
        val record = s.record ?: return
        val saved = record.saved.firstOrNull { it.item == item }
        if (saved == null) {
            _state.update { it.copy(editUnavailable = true) }
            return
        }
        val texts = RecentField.entries.associateWith { RecentValues.formText(saved.values[it.wire]) }
        _state.update { it.copy(edit = EditUi(item, texts, texts), saved = null, undone = null) }
    }

    fun setText(field: RecentField, text: String) = _state.update { s ->
        val e = s.edit ?: return@update s
        s.copy(edit = e.copy(texts = e.texts + (field to text), errors = e.errors - field, nothingChanged = false, failure = null))
    }

    /** Leaves the form; nothing happens while it is saving. */
    fun closeEdit() = _state.update { if (it.edit?.busy == true) it else it.copy(edit = null) }

    /** Sends the changed fields only; [onDone] runs when the Hub has taken them. */
    fun saveEdit(onDone: () -> Unit) {
        val e = _state.value.edit ?: return
        if (e.busy) return
        val old = _state.value.record?.saved?.firstOrNull { it.item == e.item }?.values ?: JsonObject(emptyMap())
        val changes = mutableMapOf<RecentField, JsonElement>()
        val errors = mutableMapOf<RecentField, FieldError>()
        for (field in e.changed) {
            when (val p = RecentValues.parse(e.texts.getValue(field), field)) {
                is Parsed.Ok -> if (!sameValue(p.value, old[field.wire])) changes[field] = p.value
                is Parsed.Bad -> errors[field] = p.error
            }
        }
        if (errors.isNotEmpty()) {
            _state.update { it.copy(edit = e.copy(errors = errors, nothingChanged = false)) }
            return
        }
        if (changes.isEmpty()) {
            _state.update { it.copy(edit = e.copy(nothingChanged = true)) }
            return
        }
        _state.update { it.copy(edit = e.copy(busy = true, errors = emptyMap(), failure = null, nothingChanged = false)) }
        viewModelScope.launch {
            guard(_state, { f -> _state.update { s -> s.copy(edit = s.edit?.copy(busy = false, failure = f)).failed(f) } }, auth) {
                val r = backend.applyValues(id, e.item, JsonObject(changes.mapKeys { it.key.wire }))
                sealed = e.item
                _state.update {
                    it.copy(record = r, error = null, unauthorized = false, mismatch = null, edit = null, saved = SavedEdit(e.item, changes.keys.toList()), ask = Ask.Idle)
                }
                onDone()
            }
        }
    }

    // ---- undo ----

    fun askUndo() = _state.update { if (it.undoTarget != null && !it.undoBusy) it.copy(undoAsk = true, undoFailure = null) else it }

    fun cancelUndo() = _state.update { if (it.undoBusy) it else it.copy(undoAsk = false) }

    fun undo() {
        val target = _state.value.undoTarget ?: return
        if (_state.value.undoBusy) return
        _state.update { it.copy(undoBusy = true, undone = null, saved = null) }
        viewModelScope.launch {
            guard(_state, { f -> _state.update { it.copy(undoFailure = f).failed(f) } }, auth) {
                val r = backend.undo(id, target.n)
                // the Hub's answer carries what the undo did to the filaments (undo_to, orphaned_by_undo)
                val done = r.revisions.firstOrNull { rev -> rev.n == target.n } ?: target
                _state.update { it.copy(record = r, error = null, undone = done, unauthorized = false, mismatch = null, ask = Ask.Idle) }
            }
            _state.update { it.copy(undoBusy = false, undoAsk = false) }
        }
    }
}

/**
 * A spool as the search answers give it, from what the record knows (number, brand, name, material, colour). The Hub
 * has no call for one spool by number yet (05-android-app 16), so the card opens without location and weight.
 */
fun HistorySpool.asSpoolJson(): JsonObject = buildJsonObject {
    spoolId?.let { put("id", it) }
    put("filament", buildJsonObject {
        name?.let { put("name", it) }
        material?.let { put("material", it) }
        colorHex?.let { put("color_hex", it) }
        vendor?.let { v -> put("vendor", buildJsonObject { put("name", v) }) }
    })
}

/** The key a record's view model is kept under, in the record's own back stack entry. */
internal fun recordKey(id: String): String = listOf(RECORD_KEY, id).joinToString("/")

private const val RECORD_KEY = "record"

/** The usual error handling: unpaired and certificate changes go to [onAuth], the rest become a [RecentFailure]. */
private suspend fun <S> guard(
    state: MutableStateFlow<S>,
    onError: (RecentFailure) -> Unit,
    onAuth: S.(Boolean, Pair<String, String>?) -> S,
    block: suspend () -> Unit,
) {
    try {
        block()
    } catch (e: CancellationException) {
        throw e
    } catch (e: FingerprintMismatch) {
        state.update { it.onAuth(false, e.expected to e.actual) }
    } catch (e: ApiError) {
        if (e.code == "unauthorized") state.update { it.onAuth(true, null) } else onError(failureOf(e))
    } catch (_: Exception) {
        onError(RecentFailure.Unexpected)
    }
}
