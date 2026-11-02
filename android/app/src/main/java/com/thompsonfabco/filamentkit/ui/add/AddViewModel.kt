package com.thompsonfabco.filamentkit.ui.add

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.drafts.Draft
import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.imaging.prepareJpeg
import com.thompsonfabco.filamentkit.net.AddResult
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LOCAL_NETWORK_MESSAGE
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.net.Proposal
import com.thompsonfabco.filamentkit.net.ReadResult
import com.thompsonfabco.filamentkit.tags.TagEvents
import com.thompsonfabco.filamentkit.ui.isValidWeight
import java.io.File
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

/** The server calls the add flow uses; [of] adapts the real [Api] (tests pass a fake). */
interface IntakeApi {
    suspend fun read(photos: List<ByteArray>, hint: String, tag: String?): ReadResult
    suspend fun retry(readId: String): ReadResult
    suspend fun add(items: JsonArray, dryRun: Boolean, tag: String?): AddResult
    suspend fun locations(): List<String>

    /** The line and Bambu parent the server would use; the defaults keep older fakes compiling (no proposal). */
    suspend fun propose(vendor: String, line: String, material: String): Proposal =
        throw ApiError(0, "not_supported", "No proposals")

    suspend fun parents(material: String): ParentList = ParentList()

    companion object {
        fun of(api: Api): IntakeApi = object : IntakeApi {
            override suspend fun read(photos: List<ByteArray>, hint: String, tag: String?) = api.read(photos, hint, tag)
            override suspend fun retry(readId: String) = api.retry(readId)
            override suspend fun add(items: JsonArray, dryRun: Boolean, tag: String?) = api.add(items, dryRun, tag)
            override suspend fun locations() = api.locations()
            override suspend fun propose(vendor: String, line: String, material: String) = api.propose(vendor, line, material)
            override suspend fun parents(material: String) = api.parents(material)
        }
    }
}

/** Capture → (Reading) → Review → (Previewing) → Preview → (Adding) → Done. */
enum class Stage { Capture, Reading, Review, Previewing, Preview, Adding, Done }

/**
 * A problem shown to the user. [canRetry] offers Retry (repeats the failed step; a failed read is retried from the
 * photos the server kept). [canDropTag] offers adding without the tag. [pairAgain] sends the user to pairing; with
 * [expectedFingerprint]/[actualFingerprint] it is a changed server certificate.
 */
data class AddError(
    val message: String,
    val detail: String? = null,
    val canRetry: Boolean = false,
    val canDropTag: Boolean = false,
    val pairAgain: Boolean = false,
    val expectedFingerprint: String? = null,
    val actualFingerprint: String? = null,
)

/**
 * A real add failed after it may have written to Spoolman: [spoolIds] are the spools the server reported as created
 * (a partial `spoolman_error`); empty when the reply was lost and nothing is known.
 */
data class AddedBefore(val spoolIds: List<Long>) {
    val note: String
        get() = if (spoolIds.isEmpty()) {
            "The last add may have gone through: the connection was lost before the server answered."
        } else {
            "Spools already added: ${spoolIds.joinToString { "#$it" }}"
        }
}

data class AddUiState(
    val stage: Stage = Stage.Capture,
    val draftId: String? = null,
    val photos: List<File> = emptyList(),
    val hint: String = "",
    val tag: String? = null,
    val weight: Double? = null,
    val sealed: Boolean = false,
    val questions: List<String> = emptyList(),
    /** The read's items as the server sent them, plus the user's edits; sent back to `add` as-is. */
    val items: List<JsonObject> = emptyList(),
    val notices: List<String> = emptyList(),
    val previewLines: List<String> = emptyList(),
    val spoolIds: List<Int> = emptyList(),
    val resultLines: List<String> = emptyList(),
    val locations: List<String> = emptyList(),
    val error: AddError? = null,
    /** Bumped when items or fields are replaced wholesale (read, restore, remove), so screens reset their text. */
    val generation: Int = 0,
    /** A real add may already have written spools; the next real add needs [AddViewModel.addAgain]. */
    val addedBefore: AddedBefore? = null,
    /** The "I checked — add again" warning is open (Add was tapped while [addedBefore] is set). */
    val askAddAgain: Boolean = false,
    /** Bambu Studio parents per material (for the parent dropdown); a material missing here is not loaded yet. */
    val parents: Map<String, ParentList> = emptyMap(),
) {
    /** Every item has a whole spool count of at least 1 (Preview is blocked otherwise). */
    val countsValid: Boolean
        get() = items.all { ((it["count"] as? JsonPrimitive)?.intOrNull ?: 0) >= 1 }
}

/**
 * The add-spools flow. A draft (photos + choices + read result + edited items) is created at the first photo, saved
 * after every change and deleted only after a successful real add, so a failure or an app kill loses nothing.
 * Tag taps from [taps] while the flow is open become the new spool's tag. [draftId] reopens a saved draft.
 */
class AddViewModel(
    private val api: IntakeApi,
    private val store: DraftStore,
    taps: Flow<String> = TagEvents.taps,
    draftId: String? = null,
    initialTag: String? = null,
    private val prepare: (ByteArray) -> ByteArray = { prepareJpeg(it) },
    private val io: CoroutineDispatcher = Dispatchers.IO,
) : ViewModel() {
    private val _state = MutableStateFlow(AddUiState(tag = initialTag))
    val state: StateFlow<AddUiState> = _state.asStateFlow()

    private val json = Json { ignoreUnknownKeys = true }
    private var draft: Draft? = null
    private var readResult: JsonObject? = null
    /** Read id of the last failed read (photos kept on the server for a retry). */
    private var failedReadId: String? = null
    private var retryAction: (() -> Unit)? = null
    /** Latest draft snapshot to write; conflated so writes stay in order and only the newest is written. */
    private val saves = MutableStateFlow<Draft?>(null)
    /** Serialises photo adds/removes so two quick shots cannot create two drafts. */
    private val photoLock = Mutex()
    /** The pending (debounced) proposal per item index; cancelled by the next edit of that item. */
    private val proposalJobs = mutableMapOf<Int, Job>()
    private val parentsLoading = mutableSetOf<String>()

    init {
        viewModelScope.launch(io) {
            saves.filterNotNull().collect { d ->
                try {
                    store.update(d)
                } catch (_: Exception) { // deleted after a successful add, or storage trouble: nothing to save
                }
            }
        }
        viewModelScope.launch { taps.collect { setTag(it) } }
        viewModelScope.launch {
            try {
                val names = api.locations()
                _state.update { it.copy(locations = names) }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) { // suggestions only; the location field still takes free text
            }
        }
        if (draftId != null) viewModelScope.launch { restore(draftId) }
    }

    // ---------- capture ----------

    fun addPhoto(raw: ByteArray) {
        viewModelScope.launch {
            photoLock.withLock {
                if (_state.value.photos.size >= MAX_PHOTOS) {
                    showError(AddError("$MAX_PHOTOS photos at most. Remove one to add another."))
                    return@withLock
                }
                try {
                    val existing = draft
                    val (d, photos) = withContext(io) {
                        val jpeg = prepare(raw)
                        val d = existing ?: store.create()
                        store.addPhoto(d.id, jpeg)
                        d to store.get(d.id)?.photos.orEmpty()
                    }
                    if (draft == null) draft = d
                    forgetFailedRead()
                    _state.update { it.copy(photos = photos, draftId = d.id) }
                    save()
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    showError(AddError("That photo could not be used. Take it again.", detail = e.message))
                }
            }
        }
    }

    fun removePhoto(index: Int) {
        val file = _state.value.photos.getOrNull(index) ?: return
        viewModelScope.launch {
            val photos = photoLock.withLock {
                withContext(io) {
                    file.delete()
                    draft?.let { store.get(it.id)?.photos }.orEmpty()
                }
            }
            forgetFailedRead()
            _state.update { it.copy(photos = photos) }
        }
    }

    fun setHint(text: String) {
        if (text == _state.value.hint) return
        forgetFailedRead()
        edit { it.copy(hint = text) }
    }

    /** Grams on the scale, spool included; only used for one opened spool. */
    fun setWeight(grams: Double?) {
        val g = grams?.takeIf(::isValidWeight) // NaN, Infinity, 0 or less never reach the draft
        edit { it.copy(weight = g, sealed = if (g != null) false else it.sealed) }
    }

    fun setSealed(sealed: Boolean) = edit { it.copy(sealed = sealed, weight = if (sealed) null else it.weight) }

    fun clearTag() = changeTag(null)

    /** Taps while a call is running are ignored, so the tag sent is the tag the user saw. */
    private fun setTag(uid: String) {
        if (_state.value.stage in BUSY) return
        changeTag(uid)
    }

    /** A different tag changes what Read and Add do: a pending retry and any preview are no longer valid. */
    private fun changeTag(uid: String?) {
        if (uid == _state.value.tag) return
        forgetFailedRead()
        _state.update { it.copy(tag = uid).invalidated() }
        save()
    }

    /** Photos, hint or tag changed: the server's kept copy of a failed read no longer matches. */
    private fun forgetFailedRead() {
        failedReadId = null
        retryAction = null
        _state.update { it.copy(error = null) }
    }

    fun read() {
        val s = _state.value
        if (s.photos.isEmpty() || s.stage == Stage.Reading) return
        runRead { api.read(withContext(io) { s.photos.map { it.readBytes() } }, s.hint, s.tag) }
    }

    private fun runRead(call: suspend () -> ReadResult) {
        _state.update { it.copy(stage = Stage.Reading, error = null) }
        viewModelScope.launch {
            try {
                val res = call()
                failedReadId = null
                onRead(res)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                failedReadId = (e as? ApiError)?.extra?.get("read_id")?.let { (it as? JsonPrimitive)?.contentOrNull }
                    ?: if ((e as? ApiError)?.code == "not_found") null else failedReadId
                _state.update { it.copy(stage = Stage.Capture) }
                retryAction = {
                    val id = failedReadId
                    if (id != null) runRead { api.retry(id) } else read()
                }
                showError(describe(e))
            }
        }
    }

    private fun onRead(res: ReadResult) {
        val s = _state.value
        val (items, notices) = applyCaptureChoices(res.items.mapNotNull { it as? JsonObject }, s.weight, s.sealed)
        readResult = json.encodeToJsonElement(res) as JsonObject
        _state.update {
            it.copy(
                stage = Stage.Review, items = items, questions = res.questions, notices = notices,
                previewLines = emptyList(), error = null, generation = it.generation + 1,
            )
        }
        save()
        loadParentsForItems()
    }

    fun backToPhotos() = _state.update { it.copy(stage = Stage.Capture, previewLines = emptyList(), error = null) }

    /** From the photos back to the items already read (no new read). */
    fun showReview() = _state.update { if (it.items.isEmpty() || it.stage != Stage.Capture) it else it.copy(stage = Stage.Review, error = null) }

    // ---------- review ----------

    /** Text fields (vendor, name, material, color_hex, lot, note, ...). A blank optional value becomes null. */
    fun setText(index: Int, key: String, value: String) {
        val v = if (key == "color_hex") value.trim().removePrefix("#").uppercase() else value
        val el: JsonElement = if (v.isBlank() && key !in REQUIRED_TEXT) JsonNull else JsonPrimitive(v)
        editItem(index) { JsonObject(it + (key to el)) }
        if (key in LINE_KEYS) scheduleProposal(index)
    }

    /**
     * The Bambu Studio parent for this item's line. A picked parent is kept when a later edit re-proposes; blank
     * forgets the pick and lets the server propose one again.
     */
    fun setParent(index: Int, value: String) {
        if (value.isBlank()) {
            editItem(index) { JsonObject(it - PICKED + ("bambu_parent" to JsonNull)) }
            scheduleProposal(index)
        } else {
            editItem(index) { JsonObject(it + ("bambu_parent" to JsonPrimitive(value)) + (PICKED to JsonPrimitive(true))) }
        }
    }

    /**
     * After a pause of [PROPOSE_DEBOUNCE_MS] (a newer edit restarts it), asks the server which line and parent these
     * values give: `line_exists` is always updated, the parent only when the user has not picked one. An answer for
     * values that changed meanwhile, or a failure, changes nothing (the proposal is only a help).
     */
    private fun scheduleProposal(index: Int) {
        proposalJobs.remove(index)?.cancel()
        proposalJobs[index] = viewModelScope.launch {
            delay(PROPOSE_DEBOUNCE_MS)
            val asked = _state.value.items.getOrNull(index) ?: return@launch
            val material = asked.text("material")
            if (!material.isNullOrBlank()) loadParents(material)
            val vendor = asked.text("vendor")
            val line = asked.text("line")
            if (vendor.isNullOrBlank() || line.isNullOrBlank() || material.isNullOrBlank()) return@launch
            val p = try {
                api.propose(vendor, line, material)
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                return@launch
            }
            val now = _state.value.items.getOrNull(index) ?: return@launch
            if (LINE_KEYS.any { now.text(it) != asked.text(it) }) return@launch
            var next = now + ("line_exists" to JsonPrimitive(p.exists))
            if ((now[PICKED] as? JsonPrimitive)?.booleanOrNull != true) {
                next = next + ("bambu_parent" to (p.bambuParent?.let(::JsonPrimitive) ?: JsonNull)) +
                    ("parent_source" to JsonPrimitive(p.parentSource))
            }
            if (JsonObject(next) != now) editItem(index) { JsonObject(next) }
        }
    }

    private fun loadParentsForItems() {
        _state.value.items.mapNotNull { it.text("material")?.takeIf(String::isNotBlank) }.distinct().forEach { m ->
            viewModelScope.launch { loadParents(m) }
        }
    }

    /** Loads the parent list for [material] once; a failure leaves it unloaded (the field stays free text). */
    private suspend fun loadParents(material: String) {
        if (material in _state.value.parents || !parentsLoading.add(material)) return
        try {
            val list = api.parents(material)
            _state.update { it.copy(parents = it.parents + (material to list)) }
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
        } finally {
            parentsLoading.remove(material)
        }
    }

    private fun cancelProposals() {
        proposalJobs.values.forEach { it.cancel() }
        proposalJobs.clear()
    }

    /** Weights (`net`, `tare`, `gross`); a value that is not finite and above 0 is ignored. */
    fun setNumber(index: Int, key: String, value: Double?) {
        if (value != null && !isValidWeight(value)) return
        editItem(index) { JsonObject(it + (key to (value?.let(::number) ?: JsonNull))) }
    }

    /** `gross` only applies to a single spool, so any other count drops it. */
    fun setCount(index: Int, count: Int?) = editItem(index) {
        val o = it + ("count" to (count?.let { c -> JsonPrimitive(c) } ?: JsonNull))
        JsonObject(if (count != 1) o - "gross" else o)
    }

    /** Blank leaves the location to the server's placement rules. */
    fun setLocation(index: Int, location: String) = editItem(index) {
        if (location.isBlank()) JsonObject(it - "location") else JsonObject(it + ("location" to JsonPrimitive(location.trim())))
    }

    /** A sealed spool has no gross weight. */
    fun setItemSealed(index: Int, sealed: Boolean) = editItem(index) {
        val o = it + ("sealed" to JsonPrimitive(sealed))
        JsonObject(if (sealed) o - "gross" else o)
    }

    fun removeItem(index: Int) {
        if (index !in _state.value.items.indices || _state.value.stage in BUSY) return
        cancelProposals() // indices shift
        _state.update { s ->
            s.copy(items = s.items.filterIndexed { i, _ -> i != index }, generation = s.generation + 1).invalidated()
        }
        retryAction = null
        save()
    }

    private fun editItem(index: Int, change: (JsonObject) -> JsonObject) {
        if (index !in _state.value.items.indices || _state.value.stage in BUSY) return
        _state.update { s -> s.copy(items = s.items.mapIndexed { i, o -> if (i == index) change(o) else o }).invalidated() }
        retryAction = null
        save()
    }

    /**
     * Any edit makes a preview and a pending retry stale: back to Review (a new preview is needed before Add) and the
     * error is cleared (callers also drop [retryAction]).
     */
    private fun AddUiState.invalidated() =
        (if (stage == Stage.Preview) copy(stage = Stage.Review, previewLines = emptyList()) else this).copy(error = null)

    fun preview() {
        val s = _state.value
        if (s.items.isEmpty() || !s.countsValid || s.stage != Stage.Review) return
        runAdd(dryRun = true)
    }

    /** The real add. After an add that may already have written spools, this only opens the "add again?" warning. */
    fun confirm() {
        val s = _state.value
        if (s.stage != Stage.Preview) return
        if (s.addedBefore != null) {
            _state.update { it.copy(askAddAgain = true) }
            return
        }
        runAdd(dryRun = false)
    }

    /** "I checked — add again" in the warning: the real add, once. */
    fun addAgain() {
        val s = _state.value
        if (!s.askAddAgain) return
        _state.update { it.copy(askAddAgain = false) }
        if (s.stage == Stage.Preview) runAdd(dryRun = false)
    }

    fun cancelAddAgain() = _state.update { it.copy(askAddAgain = false) }

    private fun runAdd(dryRun: Boolean) {
        val s = _state.value
        val back = if (dryRun) Stage.Review else Stage.Preview
        _state.update { it.copy(stage = if (dryRun) Stage.Previewing else Stage.Adding, error = null) }
        viewModelScope.launch {
            try {
                val res = api.add(JsonArray(s.items.map { JsonObject(it - PICKED) }), dryRun, s.tag)
                if (dryRun) {
                    _state.update { it.copy(stage = Stage.Preview, previewLines = res.lines) }
                } else {
                    val id = draft?.id
                    draft = null
                    if (id != null) withContext(io) { store.delete(id) }
                    _state.update {
                        it.copy(stage = Stage.Done, spoolIds = res.spoolIds, resultLines = res.lines, draftId = null)
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val code = (e as? ApiError)?.code
                var err = describe(e)
                // A real add that may have written something (Spoolman failed part-way, or the reply was lost) needs a
                // fresh preview before another real add; its retry is that preview, never a blind second write.
                val mayHaveWritten = !dryRun && (code == "spoolman_error" || code == "offline")
                if (!dryRun && code == "offline") err = err.copy(message = ADD_REPLY_LOST)
                val stage = if (mayHaveWritten) Stage.Review else back
                // Spools may exist now: a partial Spoolman failure (ids known) or a lost reply (unknown).
                val created = (e as? ApiError)?.let(::partialIds).orEmpty()
                val warn = !dryRun && (code == "offline" || (code == "spoolman_error" && created.isNotEmpty()))
                _state.update {
                    it.copy(
                        stage = stage,
                        previewLines = if (stage == Stage.Review) emptyList() else it.previewLines,
                        addedBefore = if (warn) {
                            AddedBefore((it.addedBefore?.spoolIds.orEmpty() + created).distinct())
                        } else it.addedBefore,
                    )
                }
                if (warn) save()
                // Retries go through the stage guards of preview()/confirm(), so a later edit blocks a stale write.
                retryAction = if (dryRun || mayHaveWritten) ::preview else ::confirm
                showError(err)
            }
        }
    }

    // ---------- errors ----------

    fun retry() {
        val action = retryAction ?: return
        if (_state.value.error?.canRetry != true) return
        retryAction = null
        _state.update { it.copy(error = null) }
        action()
    }

    /** After a tag conflict: forget the tag and preview again without it (a tag change always needs a new preview). */
    fun dropTagAndRetry() {
        if (_state.value.error?.canDropTag != true) return
        retryAction = null
        _state.update { it.copy(tag = null).invalidated() }
        save()
        preview()
    }

    fun dismissError() {
        retryAction = null
        _state.update { it.copy(error = null) }
    }

    /** After Done: start a fresh flow (no draft until the next photo). */
    fun startOver() {
        draft = null
        readResult = null
        failedReadId = null
        retryAction = null
        cancelProposals()
        _state.update { AddUiState(locations = it.locations, parents = it.parents, generation = it.generation + 1) }
    }

    private fun showError(e: AddError) = _state.update { it.copy(error = e) }

    // ---------- draft ----------

    private fun edit(change: (AddUiState) -> AddUiState) {
        _state.update(change)
        save()
    }

    private fun save() {
        val d = draft ?: return
        val s = _state.value
        val next = d.copy(
            hint = s.hint, tag = s.tag, weightGrams = s.weight, sealed = s.sealed, readResult = readResult,
            editedItems = if (s.items.isEmpty() && readResult == null) null else JsonArray(s.items),
            addedBefore = s.addedBefore?.spoolIds,
        )
        draft = next
        saves.value = next
    }

    private suspend fun restore(id: String) {
        val d = withContext(io) { store.get(id) } ?: return
        draft = d
        readResult = d.readResult
        val res = d.readResult?.let {
            try {
                json.decodeFromJsonElement<ReadResult>(it)
            } catch (_: Exception) {
                null
            }
        }
        val items = (d.editedItems ?: res?.items)?.mapNotNull { it as? JsonObject }
        _state.update {
            it.copy(
                stage = if (items != null) Stage.Review else Stage.Capture,
                draftId = d.id, photos = d.photos, hint = d.hint, tag = d.tag ?: it.tag, weight = d.weightGrams,
                sealed = d.sealed, questions = res?.questions.orEmpty(), items = items.orEmpty(),
                addedBefore = d.addedBefore?.let(::AddedBefore),
                generation = it.generation + 1,
            )
        }
        loadParentsForItems()
    }

    companion object {
        const val MAX_PHOTOS = 8
        internal const val PROPOSE_DEBOUNCE_MS = 500L
        /** App-only item key (kept in the draft, never sent): the user picked this item's Bambu parent. */
        internal const val PICKED = "app_parent_picked"
        private val LINE_KEYS = listOf("vendor", "line", "material")
        private val REQUIRED_TEXT = setOf("vendor", "name", "material")
        private val BUSY = setOf(Stage.Reading, Stage.Previewing, Stage.Adding)
        internal const val ADD_REPLY_LOST = "The connection to the server was lost while adding, so the spools may " +
            "have been added. Check Spoolman before trying again; Retry first runs a new preview."
    }
}

/**
 * Applies the capture screen's choices to freshly read items: "Sealed" marks every item sealed; a weight becomes
 * `gross` on a single opened spool (one item, count 1) and is otherwise reported as unused.
 */
internal fun applyCaptureChoices(
    items: List<JsonObject>,
    weight: Double?,
    sealed: Boolean,
): Pair<List<JsonObject>, List<String>> {
    if (sealed) return items.map { JsonObject(it + ("sealed" to JsonPrimitive(true)) - "gross") } to emptyList()
    if (weight == null) return items to emptyList()
    val one = items.singleOrNull()
    val opened = one != null && one["count"]?.jsonPrimitive?.intOrNull == 1 &&
        one["sealed"]?.jsonPrimitive?.booleanOrNull == false
    return if (opened) {
        listOf(JsonObject(one + ("gross" to number(weight)))) to emptyList()
    } else {
        items to listOf("The weight (${grams(weight)} g) was not filled in: it is only used for one opened spool.")
    }
}

/** A text value of an item (null when missing, JSON null or not a string). */
private fun JsonObject.text(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content

/** Whole numbers stay integers in the JSON (and on screen). */
internal fun number(v: Double): JsonPrimitive =
    if (v == Math.floor(v) && !v.isInfinite() && kotlin.math.abs(v) < 1e15) JsonPrimitive(v.toLong()) else JsonPrimitive(v)

internal fun grams(v: Double): String = number(v).content

/** The ids of spools a failed `spoolman_error` add had already created. */
internal fun partialIds(e: ApiError): List<Long> = (e.extra["partial_spool_ids"] as? JsonArray).orEmpty()
    .mapNotNull { (it as? JsonPrimitive)?.longOrNull }

/** Maps a failure to a plain-English [AddError]. */
internal fun describe(e: Exception): AddError = when (e) {
    is FingerprintMismatch -> AddError(
        "The server's certificate has changed. This can mean the server was reinstalled, or that another device " +
            "is pretending to be it. Pair again only if you reinstalled the server.",
        pairAgain = true, expectedFingerprint = e.expected, actualFingerprint = e.actual,
    )
    is ApiError -> describeApi(e)
    else -> AddError("Unexpected response from the server")
}

private fun describeApi(e: ApiError): AddError {
    val claude = { text: String -> AddError(text, detail = e.message, canRetry = true) }
    return when (e.code) {
        "offline" -> AddError(
            "Can't reach the server. Check that this phone is on the same network as the server, then try again.",
            canRetry = true,
        )
        "local_network" -> AddError(LOCAL_NETWORK_MESSAGE, canRetry = true)
        "unauthorized" -> AddError("This phone is no longer paired with the server. Pair it again.", pairAgain = true)
        "daily_cap" -> AddError("Today's limit of label reads on the server is used up. Try again tomorrow.")
        "bad_key" -> claude("The server's Anthropic API key was rejected. Fix the key on the server, then retry.")
        "rate_limited" -> claude("Claude is busy right now (rate limit). Wait a minute, then retry.")
        "unreachable" -> claude("The server can't reach Claude. Check the server's internet connection, then retry.")
        "refused" -> claude("Claude declined to read these photos. Retry, or take different photos.")
        "truncated" -> claude("Claude's answer was cut off. Retry, or read fewer photos at once.")
        "api_error" -> claude("Claude could not read the labels this time. Retry in a moment.")
        "not_found" -> AddError(
            "The server no longer has those photos. Read them again.", canRetry = true,
        )
        "spoolman_unreachable" -> AddError(
            "The server can't reach Spoolman. Check that Spoolman is running, then try again.", canRetry = true,
        )
        "spoolman_error" -> {
            val ids = partialIds(e)
            if (ids.isEmpty()) {
                AddError("Spoolman reported an error; nothing was added. Check the values and try again.", detail = e.message)
            } else {
                AddError(
                    "Spoolman failed part-way. These spools were already created: ${ids.joinToString { "#$it" }}. " +
                        "Check them in Spoolman before adding again.",
                    detail = e.message,
                )
            }
        }
        "tag_conflict" -> AddError(
            "This tag is already linked to another spool. Add without the tag, or use a different tag.",
            detail = e.message, canDropTag = true,
        )
        "bad_photo" -> AddError("The server could not use a photo. Remove it and take it again.", detail = e.message)
        "bad_request" -> AddError("The server could not use these values.", detail = e.message)
        "bad_response" -> AddError("Unexpected response from the server")
        else -> AddError("The server hit an error. Try again later.", detail = e.message, canRetry = true)
    }
}
