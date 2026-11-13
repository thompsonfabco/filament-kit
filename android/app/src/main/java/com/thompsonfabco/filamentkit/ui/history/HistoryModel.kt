package com.thompsonfabco.filamentkit.ui.history

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.HistoryRecord
import com.thompsonfabco.filamentkit.net.HistoryRevision
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
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale

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
        fun of(api: Api): HistoryBackend = object : HistoryBackend {
            override suspend fun list() = api.intakeHistory()
            override suspend fun record(id: String) = api.intakeRecord(id)
            override suspend fun photo(id: String, n: Int) = api.intakePhoto(id, n)
            override suspend fun revise(id: String, note: String, item: Int?) = api.reviseIntake(id, note, item)
            override suspend fun applyProposal(id: String, proposal: String) = api.applyProposal(id, proposal)
            override suspend fun applyValues(id: String, item: Int, values: JsonObject) = api.applyValues(id, item, values)
            override suspend fun undo(id: String, revision: Int) = api.undoIntake(id, revision)
        }
    }
}

/** Words and value formatting of the intake history screens. */
object HistoryTexts {
    const val TITLE = "Intake history"
    const val EMPTY = "No spools added since the server started keeping intake records."
    const val KEEP_NONE = "This server keeps no intake records (Settings on the setup page: Intake records kept)."
    const val AI_OFF = "Label reading is off on this server, so the AI can't revise; edit by hand instead."
    const val NOTE_LABEL = "What's wrong? (e.g. brand is Polymaker)"
    const val NOTE_HELP = "The AI looks at the photos again with your note and proposes new values; nothing changes " +
        "until you accept them."
    const val NO_PHOTO = "This record has no photo: the AI only had the saved values and your note."
    const val ASK = "Ask the AI"
    const val ASKING = "Asking…"
    const val NEED_NOTE = "Write what is wrong first."
    const val ACCEPT = "Accept"
    const val DISCARD = "Discard"
    const val NO_CHANGE = "The AI proposes no change."
    const val EDIT = "Edit by hand"
    const val UNDO = "Undo last change"
    const val STALE = "The record changed since the AI answered. Ask again."
    const val SAVED = "Saved."
    const val UNDONE = "Undone."

    /** The order fields are shown and edited in (the add's item fields). */
    val FIELDS = listOf(
        "vendor", "name", "material", "color_hex", "line", "net", "tare", "density", "nozzle", "bed",
        "nozzle_range", "bed_range", "price_per_kg",
    )

    private val LABELS = mapOf(
        "vendor" to "Brand", "name" to "Name", "material" to "Material", "color_hex" to "Colour", "line" to "Line",
        "net" to "Net weight (g)", "tare" to "Empty spool (g)", "density" to "Density (g/cm³)",
        "nozzle" to "Nozzle (°C)", "bed" to "Bed (°C)", "nozzle_range" to "Nozzle range (°C)",
        "bed_range" to "Bed range (°C)", "price_per_kg" to "Price per kg",
    )

    fun label(field: String): String = LABELS[field] ?: field.replace('_', ' ')

    fun state(s: String): String = when (s) {
        "detected" -> "As saved"
        "revised_ai" -> "Revised by AI"
        "edited" -> "Edited by hand"
        else -> s.replace('_', ' ')
    }

    fun source(s: String): String = when (s) {
        "phone" -> "Android app"
        "web" -> "phone web app"
        "station" -> "intake station"
        "cli" -> "command line"
        else -> s
    }

    /** "SUNLU PLA+ Grey (PLA)", the spool count when there are several. */
    fun spools(list: List<HistorySpool>): String {
        val first = list.firstOrNull() ?: return "No spools"
        val text = listOfNotNull(first.vendor, first.name).joinToString(" ").ifBlank { "Spool #${first.spoolId ?: "?"}" } +
            (first.material?.let { " ($it)" } ?: "")
        return if (list.size > 1) "$text · ${list.size} spools" else text
    }

    /** A record's time in the phone's zone, short; the raw text when it can't be read. */
    fun time(iso: String): String = try {
        OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault())
            .format(DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT).withLocale(Locale.getDefault()))
    } catch (_: Exception) {
        iso
    }

    /** One value as text: numbers without a needless ".0", ranges as "190–230", nothing as "–". */
    fun value(v: JsonElement?): String = when (v) {
        null, JsonNull -> "–"
        is JsonArray -> v.joinToString("–") { value(it) }
        is JsonPrimitive -> if (v.isString) v.content.ifBlank { "–" } else v.doubleOrNull?.let(::number) ?: v.content
        is JsonObject -> v.toString()
    }

    private fun number(d: Double): String = if (d == Math.floor(d) && kotlin.math.abs(d) < 1e12) d.toLong().toString() else d.toString()

    /** "Brand: SUNLU → Polymaker" lines of a revision. */
    fun changes(r: HistoryRevision): List<String> = r.changes.map {
        "${label(it.field)}: ${value(it.old)} → ${value(it.new)}" + (it.spoolId?.let { id -> " (spool #$id)" } ?: "")
    }

    /** The revision's heading: "AI, note “brand is X”" or "By hand", with the time and device; "(undone)". */
    fun revision(r: HistoryRevision): String = listOfNotNull(
        if (r.by == "ai") "AI" else "By hand",
        r.note?.ifBlank { null }?.let { "“$it”" },
        r.device?.ifBlank { null },
        time(r.at),
        "(undone)".takeIf { r.undone },
    ).joinToString(" · ")

    /** What a re-link did: a new or other filament, and filaments left with no spools (kept, not deleted). */
    fun filaments(r: HistoryRevision): String? {
        val f = r.filaments ?: return null
        if (f.from == null && f.to == null && f.orphaned.isEmpty()) return null
        return listOfNotNull(
            if (f.to != null && f.to != f.from) "Re-linked to ${if (f.created) "a new" else "another"} filament (#${f.to})." else null,
            if (f.orphaned.isNotEmpty()) "Filament ${f.orphaned.joinToString(", ") { "#$it" }} now has no spools; " +
                "it was kept (delete it in Spoolman if you don't need it)." else null,
        ).joinToString(" ").ifBlank { null }
    }

    /**
     * The edit form's text back to JSON, shaped like the saved value [old]: a number stays a number, a range is two
     * numbers ("190-230"), anything else text; blank is null. Null when the text doesn't fit a number or a range.
     */
    fun parse(text: String, old: JsonElement?, field: String = ""): JsonElement? {
        val t = text.trim()
        if (t.isEmpty()) return JsonNull
        return when {
            old is JsonArray || ranged(field) -> {
                val parts = t.split(Regex("\\s*[-–,]\\s*")).filter { it.isNotEmpty() }
                val nums = parts.map { it.toDoubleOrNull() ?: return null }
                if (nums.size != 2) null else JsonArray(nums.map { JsonPrimitive(it) })
            }
            numeric(field) || (old is JsonPrimitive && !old.isString && old != JsonNull) -> t.toDoubleOrNull()?.let { JsonPrimitive(it) }
            else -> JsonPrimitive(t)
        }
    }

    /** The form text of a saved value (the same as [value], but blank for nothing). */
    fun formText(v: JsonElement?): String = value(v).let { if (it == "–") "" else it }

    fun numeric(field: String) = field in setOf("net", "tare", "density", "nozzle", "bed", "price_per_kg")

    fun ranged(field: String) = field.endsWith("_range")
}

data class HistoryListState(
    val history: IntakeHistory? = null,
    val loading: Boolean = false,
    val message: String? = null,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
)

/** Keeps fetched photos for the visit (a list and a record share them), so a photo is downloaded once. */
class PhotoCache {
    private val bytes = mutableMapOf<String, ByteArray>()
    fun get(id: String, n: Int): ByteArray? = synchronized(bytes) { bytes["$id/$n"] }
    fun put(id: String, n: Int, b: ByteArray) = synchronized(bytes) { bytes["$id/$n"] = b }
}

/** The list (newest first) and the shared photo cache. */
class HistoryListViewModel(private val backend: HistoryBackend) : ViewModel() {
    private val _state = MutableStateFlow(HistoryListState())
    val state: StateFlow<HistoryListState> = _state.asStateFlow()
    val photos = PhotoCache()

    fun refresh() {
        _state.update { it.copy(loading = true) }
        viewModelScope.launch {
            guard(_state, { msg -> _state.update { it.copy(message = msg) } }, { u, m -> copy(unauthorized = u || unauthorized, mismatch = m ?: mismatch) }) {
                val h = backend.list()
                _state.update { it.copy(history = h, message = null) }
            }
            _state.update { it.copy(loading = false) }
        }
    }

    /** Photo [n] of record [id], from the cache or the server; null when it can't be had. */
    suspend fun photo(id: String, n: Int): ByteArray? = photos.get(id, n) ?: try {
        backend.photo(id, n).also { photos.put(id, n, it) }
    } catch (e: CancellationException) {
        throw e
    } catch (_: Exception) {
        null
    }
}

/** An edit form open on one saved item. */
data class EditForm(val item: Int, val busy: Boolean = false, val error: String? = null)

data class RecordState(
    val record: HistoryRecord? = null,
    val message: String? = null,
    val messageIsError: Boolean = false,
    val reviseBusy: Boolean = false,
    val noteError: String? = null,
    val proposal: RevisionProposal? = null,
    val applyBusy: Boolean = false,
    val edit: EditForm? = null,
    val undoBusy: Boolean = false,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
) {
    /** The newest revision not undone, which Undo takes back (null: nothing to undo). */
    val undoTarget: HistoryRevision? get() = record?.takeIf { it.undoable }?.revisions?.lastOrNull { !it.undone }
}

/** One record: load, AI revise (proposal, then accept or discard), edit by hand, undo. */
class RecordViewModel(private val backend: HistoryBackend, private val id: String) : ViewModel() {
    private val _state = MutableStateFlow(RecordState())
    val state: StateFlow<RecordState> = _state.asStateFlow()

    private val auth: RecordState.(Boolean, Pair<String, String>?) -> RecordState =
        { u, m -> copy(unauthorized = u || unauthorized, mismatch = m ?: mismatch, edit = null, proposal = null) }

    fun load() {
        viewModelScope.launch {
            guard(_state, ::fail, auth) {
                val r = backend.record(id)
                _state.update { it.copy(record = r) }
            }
        }
    }

    /** [item] null: every item of the record. */
    fun revise(note: String, item: Int? = null) {
        val n = note.trim()
        if (_state.value.reviseBusy) return
        if (n.isEmpty()) {
            _state.update { it.copy(noteError = HistoryTexts.NEED_NOTE) }
            return
        }
        _state.update { it.copy(reviseBusy = true, noteError = null, message = null, proposal = null) }
        viewModelScope.launch {
            guard(_state, { msg -> _state.update { it.copy(noteError = msg) } }, auth) {
                val p = backend.revise(id, n, item)
                _state.update { it.copy(proposal = p) }
            }
            _state.update { it.copy(reviseBusy = false) }
        }
    }

    fun discard() = _state.update { it.copy(proposal = null) }

    fun accept() {
        val p = _state.value.proposal ?: return
        if (_state.value.applyBusy) return
        _state.update { it.copy(applyBusy = true) }
        viewModelScope.launch {
            guard(_state, { msg -> _state.update { it.copy(message = msg, messageIsError = true, proposal = null) } }, auth) {
                val r = backend.applyProposal(id, p.proposal)
                _state.update { it.copy(record = r, proposal = null, message = HistoryTexts.SAVED, messageIsError = false) }
            }
            _state.update { it.copy(applyBusy = false) }
        }
    }

    fun openEdit(item: Int) = _state.update { it.copy(edit = EditForm(item), message = null) }

    fun closeEdit() = _state.update { if (it.edit?.busy == true) it else it.copy(edit = null) }

    /** [texts] is the form (field → text); only fields whose value changed are sent. */
    fun saveEdit(texts: Map<String, String>) {
        val f = _state.value.edit ?: return
        if (f.busy) return
        val old = _state.value.record?.saved?.firstOrNull { it.item == f.item }?.values ?: JsonObject(emptyMap())
        val changes = mutableMapOf<String, JsonElement>()
        for ((field, text) in texts) {
            if (text.trim() == HistoryTexts.formText(old[field]).trim()) continue
            val v = HistoryTexts.parse(if (field == "color_hex") text.trim().removePrefix("#").uppercase() else text, old[field], field)
                ?: return _state.update { it.copy(edit = f.copy(error = "${HistoryTexts.label(field)}: not a valid value")) }
            changes[field] = v
        }
        if (changes.isEmpty()) {
            _state.update { it.copy(edit = null) }
            return
        }
        _state.update { it.copy(edit = f.copy(busy = true, error = null)) }
        viewModelScope.launch {
            guard(_state, { msg -> _state.update { s -> s.copy(edit = s.edit?.copy(busy = false, error = msg)) } }, auth) {
                val r = backend.applyValues(id, f.item, JsonObject(changes))
                _state.update { it.copy(record = r, edit = null, message = HistoryTexts.SAVED, messageIsError = false) }
            }
        }
    }

    fun undo() {
        val target = _state.value.undoTarget ?: return
        if (_state.value.undoBusy) return
        _state.update { it.copy(undoBusy = true, message = null) }
        viewModelScope.launch {
            guard(_state, ::fail, auth) {
                val r = backend.undo(id, target.n)
                _state.update { it.copy(record = r, message = HistoryTexts.UNDONE, messageIsError = false) }
            }
            _state.update { it.copy(undoBusy = false) }
        }
    }

    private fun fail(msg: String) = _state.update { it.copy(message = msg, messageIsError = true) }
}

/** The usual error handling: unpaired and certificate changes go to [onAuth], the rest become one line. */
private suspend fun <S> guard(
    state: MutableStateFlow<S>,
    onError: (String) -> Unit,
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
        if (e.code == "unauthorized") state.update { it.onAuth(true, null) } else onError(errorText(e))
    } catch (e: Exception) {
        onError("Unexpected response from the server")
    }
}

internal fun errorText(e: ApiError): String = when (e.code) {
    "ai_off" -> HistoryTexts.AI_OFF
    "stale" -> HistoryTexts.STALE
    "daily_cap" -> "Today's label reading limit is used up (revisions count too). Try again tomorrow, or edit by hand."
    "offline" -> "Could not reach the server. Check that you are on the same network."
    else -> e.message
}
