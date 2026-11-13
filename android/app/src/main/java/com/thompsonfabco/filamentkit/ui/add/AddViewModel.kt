package com.thompsonfabco.filamentkit.ui.add

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.drafts.Draft
import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.imaging.prepareJpeg
import com.thompsonfabco.filamentkit.net.AddResult
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FilamentChoice
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LOCAL_NETWORK_MESSAGE
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.net.Proposal
import com.thompsonfabco.filamentkit.net.ReadResult
import com.thompsonfabco.filamentkit.net.VendorChoice
import com.thompsonfabco.filamentkit.tags.TagEvents
import com.thompsonfabco.filamentkit.ui.isValidWeight
import java.io.File
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
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
    /** [readId]: the label read the items came from (the server's intake record keeps its photos); null by hand. */
    suspend fun add(items: JsonArray, dryRun: Boolean, tag: String?, readId: String?): AddResult
    suspend fun locations(): List<String>

    /** The line and Bambu parent the server would use; the defaults keep older fakes compiling (no proposal). */
    suspend fun propose(vendor: String, line: String, material: String): Proposal =
        throw ApiError(0, "not_supported", "No proposals")

    suspend fun parents(material: String): ParentList = ParentList()

    /** Filaments for the manual add's picker (`GET /api/filaments`); the defaults keep older fakes compiling. */
    suspend fun filaments(q: String): List<FilamentChoice> = emptyList()

    suspend fun vendors(): List<VendorChoice> = emptyList()

    companion object {
        /** Calls go to whatever [current] returns at that moment, so a new client (trusted certificate, re-pair) is used at once. */
        fun of(current: () -> Api): IntakeApi = object : IntakeApi {
            private fun api() = current()
            override suspend fun read(photos: List<ByteArray>, hint: String, tag: String?) = api().read(photos, hint, tag)
            override suspend fun retry(readId: String) = api().retry(readId)
            override suspend fun add(items: JsonArray, dryRun: Boolean, tag: String?, readId: String?) =
                api().add(items, dryRun, tag, readId)
            override suspend fun locations() = api().locations()
            override suspend fun propose(vendor: String, line: String, material: String) = api().propose(vendor, line, material)
            override suspend fun parents(material: String) = api().parents(material)
            override suspend fun filaments(q: String) = api().filaments(q)
            override suspend fun vendors() = api().vendors()
        }

        fun of(api: Api): IntakeApi = object : IntakeApi {
            override suspend fun read(photos: List<ByteArray>, hint: String, tag: String?) = api.read(photos, hint, tag)
            override suspend fun retry(readId: String) = api.retry(readId)
            override suspend fun add(items: JsonArray, dryRun: Boolean, tag: String?, readId: String?) =
                api.add(items, dryRun, tag, readId)
            override suspend fun locations() = api.locations()
            override suspend fun propose(vendor: String, line: String, material: String) = api.propose(vendor, line, material)
            override suspend fun parents(material: String) = api.parents(material)
            override suspend fun filaments(q: String) = api.filaments(q)
            override suspend fun vendors() = api.vendors()
        }
    }
}

/**
 * Photos (Capture, Reading) → Check the spools (Review) → Preview (Previewing, Preview, Adding) → Spools added (Done).
 * Adding by hand ([AddUiState.manual]) starts at Review with no items: the person picks filaments or types new ones in.
 */
enum class Stage { Capture, Reading, Review, Previewing, Preview, Adding, Done }

/**
 * A problem shown to the person (05-android-app 6.2, 3.5). [canRetry] offers "Try again" (repeats the failed step; a
 * failed read is retried from the photos the Hub kept). [canDropTag] offers adding without the tag; [canAddByHand]
 * offers adding by hand instead; [pairAgain] sends the person to pairing, and with [expectedFingerprint] and
 * [actualFingerprint] it is a changed Hub certificate. [detail] is what the Hub said, shown as given.
 */
data class AddError(
    val message: AddText,
    val detail: String? = null,
    val canRetry: Boolean = false,
    val canDropTag: Boolean = false,
    val canAddByHand: Boolean = false,
    val pairAgain: Boolean = false,
    val expectedFingerprint: String? = null,
    val actualFingerprint: String? = null,
)

/**
 * A real add failed after it may have written to Spoolman: [spoolIds] are the spools the Hub reported as created (a
 * partial `spoolman_error`, with its [hubMessage]); empty when the reply was lost and nothing is known.
 */
data class AddedBefore(val spoolIds: List<Long>, val hubMessage: String? = null)

/** Something that happened to the draft that the screen answers with a snackbar (and an "Undo"). */
sealed interface AddEvent {
    data object PhotoRemoved : AddEvent
    data object SpoolRemoved : AddEvent
}

/** One thing the Hub's check refused: [text] as the Hub gave it; [index] and [key] name the field when it does. */
data class PreviewProblem(val text: String, val index: Int? = null, val key: String? = null)

data class AddUiState(
    val stage: Stage = Stage.Capture,
    val draftId: String? = null,
    val photos: List<File> = emptyList(),
    val hint: String = "",
    val tag: String? = null,
    val weight: Double? = null,
    val sealed: Boolean = true,
    val questions: List<String> = emptyList(),
    /** Which reader answered the read and how sure it was (null: no read, or a manual add). */
    val readInfo: ReaderTexts.Info? = null,
    /** The read's items as the server sent them, plus the user's edits; sent back to `add` as-is. */
    val items: List<JsonObject> = emptyList(),
    /** Notices of the read (the Hub's own words) and the app's note on a weight it could not use. */
    val notices: List<AddText> = emptyList(),
    val previewLines: List<String> = emptyList(),
    /** The Hub's check came back with problems or failed: the preview is not usable and Add stays off. */
    val previewFailed: Boolean = false,
    /** What the Hub refused, one entry each (the Hub's words); each has a "Fix" back to the field. */
    val problems: List<PreviewProblem> = emptyList(),
    /** The Hub's record of the add (`history_id`), for "Open in Recently added". */
    val historyId: String? = null,
    /** The tag that was sent with the add that finished (the Done step says it is linked). */
    val doneTag: String? = null,
    /** The field a "Fix" or "Show" asks the Check step to open and focus (item index, item key); cleared once done. */
    val focus: Pair<Int, String>? = null,
    /** A spool just added or put back: the Check step opens its panel (item index); cleared once done. */
    val reveal: Int? = null,
    val spoolIds: List<Int> = emptyList(),
    val resultLines: List<String> = emptyList(),
    val locations: List<String> = emptyList(),
    val error: AddError? = null,
    /** Bumped when items or fields are replaced wholesale (read, restore, remove), so screens reset their text. */
    val generation: Int = 0,
    /** A real add may already have written spools; the next real add needs [AddViewModel.addAgain]. */
    val addedBefore: AddedBefore? = null,
    /** The "Add these spools again?" dialog is open (Add was tapped while [addedBefore] is set). */
    val askAddAgain: Boolean = false,
    /** Bambu Studio parents per material (for the parent dropdown); a material missing here is not loaded yet. */
    val parents: Map<String, ParentList> = emptyMap(),
    /** The server refused a picked Bambu parent (`unknown_parent`); shown at the picked parent fields until an edit. */
    val parentError: String? = null,
    /** Adding by hand: no photos, items come from the filament picker or "New filament". */
    val manual: Boolean = false,
    /** The picker's search text and the filaments it found (manual add). */
    val filamentQuery: String = "",
    val filaments: List<FilamentChoice> = emptyList(),
    val filamentsLoading: Boolean = false,
    val filamentsError: AddText? = null,
    /** Vendor suggestions for a new filament (manual add). */
    val vendors: List<VendorChoice> = emptyList(),
    /** The server's complaint about one field (item index → item key → text), shown at that field until an edit. */
    val fieldErrors: Map<Int, Map<String, String>> = emptyMap(),
) {
    /** What each item still needs before Preview (item keys); empty lists when complete. */
    val missing: List<List<String>>
        get() = items.map { missingFields(it, needDensity = manual) }

    /** Every item has what the Hub needs (a read's density is the Hub's to ask for, so the photo path leaves it out). */
    val complete: Boolean
        get() = missing.all { it.isEmpty() }

    /** Every item has a whole spool count of at least 1 (Preview is blocked otherwise). */
    val countsValid: Boolean
        get() = items.all { ((it["count"] as? JsonPrimitive)?.intOrNull ?: 0) >= 1 }

    /** No item has an empty-spool weight (tare) of 0 g or less, e.g. from a read (blank = unknown is allowed). */
    val taresValid: Boolean
        get() = items.all { item ->
            val tare = (item["tare"] as? JsonPrimitive)?.takeIf { !it.isString }?.contentOrNull?.toDoubleOrNull()
            tare == null || isValidWeight(tare)
        }
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
    /** Wall clock in ms, for the age of the parent lists. */
    private val clock: () -> Long = System::currentTimeMillis,
    /** Add by hand (no photos, no draft): starts at Review with the filament picker. */
    private val manual: Boolean = false,
    /** Where the flow's work runs; the app's [AddFlows] pass theirs, so a read or an add outlives the screen. */
    private val ownScope: CoroutineScope? = null,
) : ViewModel() {
    private val scope: CoroutineScope get() = ownScope ?: viewModelScope

    private val _state = MutableStateFlow(
        if (manual) AddUiState(stage = Stage.Review, tag = initialTag, manual = true, filamentsLoading = true)
        else AddUiState(tag = initialTag),
    )
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
    /** When each material's parent list was loaded ([clock] ms); older than [PARENTS_MAX_AGE_MS] is loaded again. */
    private val parentsLoadedAt = mutableMapOf<String, Long>()
    /** Items whose parent text is being typed (free-text mode): not a pick yet, and proposals leave the text alone. */
    private val typingParent = mutableSetOf<Int>()
    /** The running (or debounced) filament search of the manual add's picker. */
    private var filamentJob: Job? = null
    private var readJob: Job? = null
    private var addJob: Job? = null
    private val _events = Channel<AddEvent>(Channel.BUFFERED)

    /** What the screen answers with a snackbar: a removed photo or spool, each with its "Undo". */
    val events: Flow<AddEvent> = _events.receiveAsFlow()
    private val _readDone = MutableSharedFlow<Unit>(extraBufferCapacity = 4)

    /** A read ended with items: the shell says so (with "Check") when the person is not on the Photos step. */
    val readDone: SharedFlow<Unit> = _readDone
    private val _finished = MutableSharedFlow<Boolean>(extraBufferCapacity = 4)

    /** A real add ended: true when the spools were added, false when it failed. */
    val finished: SharedFlow<Boolean> = _finished
    private var removedPhoto: ByteArray? = null
    private var removedItem: Pair<Int, JsonObject>? = null

    init {
        scope.launch(io) {
            saves.filterNotNull().collect { d ->
                try {
                    store.update(d)
                } catch (_: Exception) { // deleted after a successful add, or storage trouble: nothing to save
                }
            }
        }
        scope.launch { taps.collect { setTag(it) } }
        scope.launch {
            try {
                val names = api.locations()
                _state.update { it.copy(locations = names) }
                hubOk()
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) { // suggestions only; the location field still takes free text
            }
        }
        scope.launch {
            try {
                val list = api.vendors()
                _state.update { it.copy(vendors = list) }
                hubOk()
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) { // suggestions only; the brand field still takes free text
            }
        }
        if (draftId != null) {
            store.get(draftId)?.let(::applyDraft)
            if (initialTag != null) save() // a tapped tag is part of the draft from the start
        }
        if (manual) findFilaments("")
    }

    // ---------- manual add: filament picker ----------

    /** The picker's search text; the list follows after a short pause (each word must match). */
    fun setFilamentQuery(q: String) {
        if (q == _state.value.filamentQuery) return
        _state.update { it.copy(filamentQuery = q) }
        findFilaments(q, FILAMENT_DEBOUNCE_MS)
    }

    private fun findFilaments(q: String, wait: Long = 0) {
        filamentJob?.cancel()
        filamentJob = scope.launch {
            if (wait > 0) delay(wait)
            _state.update { it.copy(filamentsLoading = true, filamentsError = null) }
            try {
                val list = api.filaments(q)
                _state.update { it.copy(filaments = list, filamentsLoading = false) }
                hubOk()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update {
                    it.copy(filamentsLoading = false, filamentsError = describe(e).message, filaments = emptyList())
                }
            }
        }
    }

    /** Adds a spool of a filament Spoolman already has (same vendor + name: the server reuses that filament). */
    fun pickFilament(f: FilamentChoice) {
        if (_state.value.stage in BUSY) return
        val item = buildMap {
            put("vendor", JsonPrimitive(f.vendor))
            put("name", JsonPrimitive(f.name.orEmpty()))
            put("material", JsonPrimitive(f.material.orEmpty()))
            f.density?.let { put("density", number(it)) }
            f.net?.takeIf(::isValidWeight)?.let { put("net", number(it)) }
            f.tare?.takeIf(::isValidWeight)?.let { put("tare", number(it)) }
            f.colorHex?.takeIf { it.isNotBlank() }?.let { put("color_hex", JsonPrimitive(it.uppercase())) }
            f.nozzle?.let { put("nozzle", number(it)) }
            f.bed?.let { put("bed", number(it)) }
            put("count", JsonPrimitive(1))
            put("sealed", JsonPrimitive(true))
            f.id?.let { put(FROM_FILAMENT, JsonPrimitive(it)) }
            put(FROM_SPOOLS, JsonPrimitive(f.spools))
        }
        addItem(JsonObject(item))
    }

    /** Adds an empty item for a filament Spoolman does not have yet. */
    fun newFilament() {
        if (_state.value.stage in BUSY) return
        addItem(JsonObject(mapOf(
            "vendor" to JsonPrimitive(""), "name" to JsonPrimitive(""), "material" to JsonPrimitive(""),
            "count" to JsonPrimitive(1), "sealed" to JsonPrimitive(true),
        )))
    }

    private fun addItem(item: JsonObject) {
        _state.update { s ->
            s.copy(items = s.items + item, generation = s.generation + 1, reveal = s.items.size).invalidated()
        }
        retryAction = null
        save()
    }

    /** A vendor picked from the suggestions; its empty spool weight fills a blank `tare`. */
    fun pickVendor(index: Int, v: VendorChoice) {
        val item = _state.value.items.getOrNull(index) ?: return
        if (_state.value.stage in BUSY) return
        var next = item + ("vendor" to JsonPrimitive(v.name))
        val tare = v.tare?.takeIf(::isValidWeight)
        if (tare != null && item.num("tare") == null) next = next + ("tare" to number(tare))
        editItem(index, "vendor") { JsonObject(next) }
        _state.update { it.copy(generation = it.generation + 1) } // the panel shows the new vendor and tare
        scheduleProposal(index)
    }

    // ---------- capture ----------

    fun addPhoto(raw: ByteArray) {
        scope.launch {
            photoLock.withLock {
                if (_state.value.photos.size >= MAX_PHOTOS) {
                    showError(AddError(AddText.of(R.string.field_file_error_photo_limit, MAX_PHOTOS)))
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
                    showError(AddError(AddText.of(R.string.add_photos_photo_failed), detail = e.message))
                }
            }
        }
    }

    /** Removes a photo; [AddEvent.PhotoRemoved] offers "Undo" ([undoPhoto]) for the latest one. */
    fun removePhoto(index: Int) {
        val file = _state.value.photos.getOrNull(index) ?: return
        scope.launch {
            val photos = photoLock.withLock {
                withContext(io) {
                    removedPhoto = runCatching { file.readBytes() }.getOrNull()
                    file.delete()
                    draft?.let { store.get(it.id)?.photos }.orEmpty()
                }
            }
            forgetFailedRead()
            _state.update { it.copy(photos = photos) }
            if (removedPhoto != null) _events.trySend(AddEvent.PhotoRemoved)
        }
    }

    /** Puts the photo removed last back (at the end of the strip). */
    fun undoPhoto() {
        val bytes = removedPhoto ?: return
        removedPhoto = null
        scope.launch {
            photoLock.withLock {
                val d = draft ?: return@withLock
                try {
                    val photos = withContext(io) {
                        store.addPhoto(d.id, bytes)
                        store.get(d.id)?.photos.orEmpty()
                    }
                    forgetFailedRead()
                    _state.update { it.copy(photos = photos) }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    showError(AddError(AddText.of(R.string.add_photos_photo_failed), detail = e.message))
                }
            }
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

    /** A tag tapped while this flow's screen is showing (the screen passes it; see [taps] for tests). */
    fun onTag(uid: String) = setTag(uid)

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
        readJob = scope.launch {
            try {
                val res = call()
                failedReadId = null
                hubOk()
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
                val err = describe(e)
                // a read needs the Hub: the photos stay, and the words say so (05 6.2)
                showError(if ((e as? ApiError)?.code == "offline") err.copy(message = AddText.of(R.string.add_read_offline)) else err)
            }
        }
    }

    /** "Cancel reading": the draft and its photos stay; the answer, if it still comes, is not used. */
    fun cancelRead() {
        if (_state.value.stage != Stage.Reading) return
        readJob?.cancel()
        readJob = null
        _state.update { it.copy(stage = Stage.Capture) }
    }

    private fun onRead(res: ReadResult) {
        val s = _state.value
        val (items, ours) = applyCaptureChoices(res.items.mapNotNull { it as? JsonObject }, s.weight, s.sealed)
        val notices = listOfNotNull(res.note?.takeIf { it.isNotBlank() }?.let(AddText::hub)) + ours
        readResult = json.encodeToJsonElement(res) as JsonObject
        _state.update {
            it.copy(
                stage = Stage.Review, items = items, questions = res.questions, notices = notices,
                readInfo = ReaderTexts.info(res),
                previewLines = emptyList(), error = null, generation = it.generation + 1,
            )
        }
        save()
        loadParentsForItems()
        _readDone.tryEmit(Unit)
    }

    /** Not in a manual add (it has no photos; the screen offers Cancel instead). */
    fun backToPhotos() = _state.update {
        if (it.manual) it else it.copy(stage = Stage.Capture, previewLines = emptyList(), error = null)
    }

    /** From the photos back to the items already read (no new read). */
    fun showReview() = _state.update { if (it.items.isEmpty() || it.stage != Stage.Capture) it else it.copy(stage = Stage.Review, error = null) }

    // ---------- review ----------

    /** Text fields (vendor, name, material, color_hex, lot, note, ...). A blank optional value becomes null. */
    fun setText(index: Int, key: String, value: String) {
        val v = if (key == "color_hex") value.trim().removePrefix("#").uppercase() else value
        val el: JsonElement = if (v.isBlank() && key !in REQUIRED_TEXT) JsonNull else JsonPrimitive(v)
        editItem(index, key) { JsonObject(it + (key to el)) }
        if (key in LINE_KEYS) scheduleProposal(index)
    }

    /**
     * A Bambu Studio parent picked for this item's line (the Pick menu, or committed free text). A picked parent is
     * kept when a later edit re-proposes and is the only parent sent to `add`; blank ("Automatic") forgets the pick
     * and lets the server propose one again. Once Bambu Studio's presets are synced only a listed name is accepted:
     * the server would keep any other name as this line's parent for good.
     */
    fun setParent(index: Int, value: String) {
        typingParent.remove(index)
        if (value.isBlank()) {
            editItem(index, "bambu_parent") { JsonObject(it - PICKED + ("bambu_parent" to JsonNull)) }
            scheduleProposal(index)
            return
        }
        val listed = syncedParents(index)
        if (listed != null && value !in listed) return
        editItem(index, "bambu_parent") { JsonObject(it + ("bambu_parent" to JsonPrimitive(value)) + (PICKED to JsonPrimitive(true))) }
    }

    /** Free-text typing of the parent (only while not synced). Not a pick until [commitParent] (blur, Done, Preview). */
    fun typeParent(index: Int, value: String) {
        if (syncedParents(index) != null) return
        typingParent += index
        editItem(index, "bambu_parent") { JsonObject(it + ("bambu_parent" to (if (value.isEmpty()) JsonNull else JsonPrimitive(value)))) }
    }

    /** Ends typing: non-blank text becomes a pick; blank lets the server propose again. */
    fun commitParent(index: Int) {
        if (!typingParent.remove(index)) return
        val value = _state.value.items.getOrNull(index)?.text("bambu_parent")?.trim().orEmpty()
        if (value.isEmpty()) {
            editItem(index) { JsonObject(it - PICKED + ("bambu_parent" to JsonNull)) }
            scheduleProposal(index)
        } else {
            editItem(index) { JsonObject(it + ("bambu_parent" to JsonPrimitive(value)) + (PICKED to JsonPrimitive(true))) }
        }
    }

    /** The parent names allowed for this item when its material's list is synced; null for free text. */
    private fun syncedParents(index: Int): List<String>? {
        val material = _state.value.items.getOrNull(index)?.text("material") ?: return null
        return _state.value.parents[material]?.takeIf { it.synced }?.parents
    }

    /**
     * After a pause of [PROPOSE_DEBOUNCE_MS] (a newer edit restarts it), asks the server which line and parent these
     * values give: `line_exists` is always updated, the parent only when the user has not picked one. An answer for
     * values that changed meanwhile, or a failure, changes nothing (the proposal is only a help).
     */
    private fun scheduleProposal(index: Int) {
        proposalJobs.remove(index)?.cancel()
        proposalJobs[index] = scope.launch {
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
            if ((now[PICKED] as? JsonPrimitive)?.booleanOrNull != true && index !in typingParent) {
                next = next + ("bambu_parent" to (p.bambuParent?.let(::JsonPrimitive) ?: JsonNull)) +
                    ("parent_source" to JsonPrimitive(p.parentSource))
            }
            if (JsonObject(next) != now) editItem(index) { JsonObject(next) }
        }
    }

    private fun loadParentsForItems() {
        _state.value.items.mapNotNull { it.text("material")?.takeIf(String::isNotBlank) }.distinct().forEach { m ->
            scope.launch { loadParents(m) }
        }
    }

    /**
     * Loads the parent list for [material] unless one younger than [PARENTS_MAX_AGE_MS] is held (a PC sync may add
     * presets meanwhile); a failure keeps what is held (without a list the field stays free text).
     */
    private suspend fun loadParents(material: String) {
        val at = parentsLoadedAt[material]
        val fresh = material in _state.value.parents && at != null && clock() - at <= PARENTS_MAX_AGE_MS
        if (fresh || !parentsLoading.add(material)) return
        try {
            val list = api.parents(material)
            parentsLoadedAt[material] = clock()
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
        typingParent.clear()
    }

    /** Weights (`net`, `tare`, `gross`); a value that is not finite and above 0 is ignored. */
    fun setNumber(index: Int, key: String, value: Double?) {
        if (value != null && !isValidWeight(value)) return
        editItem(index, key) { JsonObject(it + (key to (value?.let(::number) ?: JsonNull))) }
    }

    /** `gross` only applies to a single spool, so any other count drops it. */
    fun setCount(index: Int, count: Int?) = editItem(index, "count") {
        val o = it + ("count" to (count?.let { c -> JsonPrimitive(c) } ?: JsonNull))
        JsonObject(if (count != 1) o - "gross" else o)
    }

    /** Blank leaves the location to the server's placement rules. */
    fun setLocation(index: Int, location: String) = editItem(index, "location") {
        if (location.isBlank()) JsonObject(it - "location") else JsonObject(it + ("location" to JsonPrimitive(location.trim())))
    }

    /** A sealed spool has no gross weight. */
    fun setItemSealed(index: Int, sealed: Boolean) = editItem(index, "gross") {
        val o = it + ("sealed" to JsonPrimitive(sealed))
        JsonObject(if (sealed) o - "gross" else o)
    }

    /** Removes a spool; [AddEvent.SpoolRemoved] offers "Undo" ([undoRemoveItem]) for the latest one. */
    fun removeItem(index: Int) {
        val gone = _state.value.items.getOrNull(index) ?: return
        if (_state.value.stage in BUSY) return
        cancelProposals() // indices shift
        removedItem = index to gone
        _state.update { s ->
            s.copy(items = s.items.filterIndexed { i, _ -> i != index }, generation = s.generation + 1).invalidated()
        }
        retryAction = null
        save()
        _events.trySend(AddEvent.SpoolRemoved)
    }

    /** Puts the spool removed last back where it was. */
    fun undoRemoveItem() {
        val (index, item) = removedItem ?: return
        removedItem = null
        if (_state.value.stage in BUSY) return
        cancelProposals()
        _state.update { s ->
            val at = index.coerceIn(0, s.items.size)
            s.copy(items = s.items.take(at) + item + s.items.drop(at), generation = s.generation + 1, reveal = at).invalidated()
        }
        retryAction = null
        save()
    }

    private fun editItem(index: Int, touch: String? = null, change: (JsonObject) -> JsonObject) {
        if (index !in _state.value.items.indices || _state.value.stage in BUSY) return
        _state.update { s ->
            s.copy(items = s.items.mapIndexed { i, o -> if (i == index) change(o).touched(touch) else o }).invalidated()
        }
        retryAction = null
        save()
    }

    /**
     * Any edit makes a preview and a pending retry stale: back to Review (a new preview is needed before Add) and the
     * error is cleared (callers also drop [retryAction]).
     */
    private fun AddUiState.invalidated() =
        (if (stage == Stage.Preview) copy(stage = Stage.Review, previewLines = emptyList()) else this)
            .copy(error = null, parentError = null, fieldErrors = emptyMap(), previewFailed = false, problems = emptyList())

    /** "Preview": the Hub's check (`dry_run`) runs on entry to the Preview step. */
    fun preview() {
        val s = _state.value
        val again = s.stage == Stage.Preview && s.previewFailed
        if (s.items.isEmpty() || !s.countsValid || !s.taresValid || (s.stage != Stage.Review && !again)) return
        typingParent.toList().forEach(::commitParent) // parent text still being typed counts as entered
        fillDensities()
        if (!_state.value.complete) return
        runAdd(dryRun = true)
    }

    /** "Back to the check": from the Preview step to Check the spools. Not while the Hub is writing. */
    fun backToCheck() {
        if (_state.value.stage !in setOf(Stage.Preview, Stage.Previewing)) return
        addJob?.cancel()
        retryAction = null
        _state.update {
            it.copy(stage = Stage.Review, previewLines = emptyList(), previewFailed = false, problems = emptyList(), error = null)
        }
    }

    /** "Fix" and "Show": the Check step opens the spool and focuses the field ([AddUiState.focus]). */
    fun fixField(index: Int, key: String) {
        backToCheck()
        if (_state.value.stage == Stage.Review) _state.update { it.copy(focus = index to key) }
    }

    fun focusDone() = _state.update { it.copy(focus = null) }

    fun revealDone() = _state.update { it.copy(reveal = null) }

    /** A missing density becomes the usual one for its material (PLA 1.24, PETG 1.27, ...), shown in the panel. */
    private fun fillDensities() {
        val s = _state.value
        val filled = s.items.map { item ->
            val d = item.num("density")?.takeIf(::isValidWeight)
            val guess = if (d == null) defaultDensity(item.text("material")) else null
            if (guess != null) JsonObject(item + ("density" to number(guess))) else item
        }
        if (filled == s.items) return
        _state.update { it.copy(items = filled, generation = it.generation + 1) }
        save()
    }

    /** The real add. After an add that may already have written spools, this only opens the "add again?" warning. */
    fun confirm() {
        val s = _state.value
        if (s.stage != Stage.Preview || s.previewFailed) return
        if (s.addedBefore != null) {
            _state.update { it.copy(askAddAgain = true) }
            return
        }
        runAdd(dryRun = false)
    }

    /** "Add again" in the warning: the real add, once. */
    fun addAgain() {
        val s = _state.value
        if (!s.askAddAgain) return
        _state.update { it.copy(askAddAgain = false) }
        if (s.stage == Stage.Preview) runAdd(dryRun = false)
    }

    fun cancelAddAgain() = _state.update { it.copy(askAddAgain = false) }

    private fun runAdd(dryRun: Boolean) {
        val s = _state.value
        _state.update {
            it.copy(
                stage = if (dryRun) Stage.Previewing else Stage.Adding, error = null,
                previewFailed = false, problems = emptyList(),
            )
        }
        addJob = scope.launch {
            try {
                val readId = if (s.manual) null else (readResult?.get("read_id") as? JsonPrimitive)?.contentOrNull
                val res = api.add(JsonArray(s.items.map(::forAdd)), dryRun, s.tag, readId)
                hubOk()
                if (dryRun) {
                    _state.update { it.copy(stage = Stage.Preview, previewLines = res.lines) }
                } else {
                    val id = draft?.id
                    draft = null
                    if (id != null) withContext(io) { store.delete(id) }
                    _state.update {
                        it.copy(
                            stage = Stage.Done, spoolIds = res.spoolIds, resultLines = res.lines, draftId = null,
                            historyId = res.historyId, doneTag = it.tag, addedBefore = null,
                        )
                    }
                    _finished.tryEmit(true)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val failure = e as? ApiError
                val code = failure?.code
                var err = describe(e)
                // A real add that may have written something (Spoolman failed part-way, or the reply was lost) needs a
                // fresh preview before another real add; its retry is that preview, never a blind second write.
                val mayHaveWritten = !dryRun && (code == "spoolman_error" || code == "offline")
                if (!dryRun && code == "offline") err = err.copy(message = AddText.of(R.string.add_preview_reply_lost))
                val badParent = code == "unknown_parent" // fixed in Check, at the parent field
                // a failed check stays on the Preview step, with its problems and "Fix"
                val stage = if (mayHaveWritten || badParent) Stage.Review else Stage.Preview
                // Spools may exist now: a partial Spoolman failure (ids known) or a lost reply (unknown).
                val created = failure?.let(::partialIds).orEmpty()
                val warn = !dryRun && (code == "offline" || (code == "spoolman_error" && created.isNotEmpty()))
                val field = if (code == "bad_request") fieldError(e.message.orEmpty(), s.items) else null
                // the Hub's complaint about a field: a line of the preview with "Fix", and under the field itself
                val problem = if (dryRun && code == "bad_request") {
                    listOf(PreviewProblem(e.message.orEmpty(), field?.index, field?.key))
                } else emptyList()
                _state.update {
                    it.copy(
                        stage = stage,
                        previewLines = if (stage == Stage.Review) emptyList() else it.previewLines,
                        previewFailed = dryRun && stage == Stage.Preview,
                        problems = problem,
                        parentError = if (badParent) e.message else null,
                        fieldErrors = field?.let { f -> mapOf(f.index to mapOf(f.key to f.text)) }.orEmpty(),
                        addedBefore = if (warn) {
                            AddedBefore(
                                (it.addedBefore?.spoolIds.orEmpty() + created).distinct(),
                                hubMessage = failure?.message?.takeIf { created.isNotEmpty() },
                            )
                        } else it.addedBefore,
                    )
                }
                if (warn) save()
                // Retries go through the stage guards of preview()/confirm(), so a later edit blocks a stale write.
                retryAction = if (dryRun || mayHaveWritten) ::preview else ::confirm
                // A refusal that names a field is shown at the field and as a line of the preview, a wrong parent at its
                // field and a partial write by the "may have been added" notice: none of them needs a second line.
                if (problem.isEmpty() && !badParent && !(warn && created.isNotEmpty())) showError(err)
                if (!dryRun) _finished.tryEmit(false)
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

    /** After a tag conflict: forget the tag and try again without it (a tag change always needs a new preview). */
    fun dropTagAndRetry() {
        if (_state.value.error?.canDropTag != true) return
        retryAction = null
        _state.update { it.copy(tag = null).invalidated() }
        save()
        if (_state.value.items.isNotEmpty()) preview() else read()
    }

    fun dismissError() {
        retryAction = null
        _state.update { it.copy(error = null) }
    }

    /** A call was answered: a "no longer paired" or "certificate changed" notice from before is no longer true. */
    private fun hubOk() = _state.update { if (it.error?.pairAgain == true) it.copy(error = null) else it }

    /** After Done: start a fresh flow (no draft until the next photo). */
    fun startOver() {
        draft = null
        readResult = null
        failedReadId = null
        retryAction = null
        cancelProposals()
        parentsLoadedAt.clear() // the next read loads the parent lists again (a PC sync may have added presets)
        _state.update {
            if (it.manual) {
                AddUiState(
                    stage = Stage.Review, manual = true, locations = it.locations, vendors = it.vendors,
                    filamentQuery = it.filamentQuery, generation = it.generation + 1,
                )
            } else AddUiState(locations = it.locations, generation = it.generation + 1)
        }
        if (manual) findFilaments(_state.value.filamentQuery) // spool counts changed
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

    /** The saved draft: its photos, choices, read result and edited items come back as they were. */
    private fun applyDraft(d: Draft) {
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
                stage = if (manual || items != null) Stage.Review else Stage.Capture,
                draftId = d.id, photos = d.photos, hint = d.hint, tag = d.tag ?: it.tag, weight = d.weightGrams,
                sealed = d.sealed, questions = res?.questions.orEmpty(), items = items.orEmpty(),
                readInfo = res?.let(ReaderTexts::info),
                addedBefore = d.addedBefore?.let { ids -> AddedBefore(ids) },
                generation = it.generation + 1,
            )
        }
        loadParentsForItems()
    }

    companion object {
        const val MAX_PHOTOS = 8
        internal const val PROPOSE_DEBOUNCE_MS = 500L
        internal const val PARENTS_MAX_AGE_MS = 5 * 60_000L
        /** App-only item key (kept in the draft, never sent): the user picked this item's Bambu parent. */
        internal const val PICKED = "app_parent_picked"
        /** App-only item keys (never sent): the Spoolman filament a manual pick came from, and its spool count. */
        internal const val FROM_FILAMENT = "app_filament_id"
        internal const val FROM_SPOOLS = "app_filament_spools"
        internal const val FILAMENT_DEBOUNCE_MS = 300L
        private val LINE_KEYS = listOf("vendor", "line", "material")
        private val REQUIRED_TEXT = setOf("vendor", "name", "material")
        private val BUSY = setOf(Stage.Reading, Stage.Previewing, Stage.Adding)
        /** App-only item key (never sent): the fields the person has edited (their confidence mark is gone). */
        internal const val TOUCHED = "app_touched"
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
): Pair<List<JsonObject>, List<AddText>> {
    if (sealed) return items.map { JsonObject(it + ("sealed" to JsonPrimitive(true)) - "gross") } to emptyList()
    if (weight == null) return items to emptyList()
    val one = items.singleOrNull()
    val opened = one != null && one["count"]?.jsonPrimitive?.intOrNull == 1 &&
        one["sealed"]?.jsonPrimitive?.booleanOrNull == false
    return if (opened) {
        listOf(JsonObject(one + ("gross" to number(weight)))) to emptyList()
    } else {
        items to listOf(AddText.of(R.string.add_review_weight_unused, grams(weight)))
    }
}

/**
 * An item as sent to `add`: without the app's marker, and with `bambu_parent` only when the user picked it (a parent
 * the server proposed is its own choice already; sending it back would pin it as the user's).
 */
internal fun forAdd(item: JsonObject): JsonObject {
    val picked = (item[AddViewModel.PICKED] as? JsonPrimitive)?.booleanOrNull == true
    val sent = item.filterKeys { !it.startsWith(APP_KEY) }
    return JsonObject(if (picked) sent else sent - "bambu_parent")
}

/** Item keys the app keeps for itself start with this; [forAdd] never sends them. */
private const val APP_KEY = "app_"

/** The usual density (g/cm³) for a material's family (`PLA+` and `PLA-CF` count as PLA); null when unknown. */
fun defaultDensity(material: String?): Double? =
    DENSITIES[material.orEmpty().trim().uppercase().takeWhile { it.isLetter() }]

private val DENSITIES = mapOf("PLA" to 1.24, "PETG" to 1.27, "ABS" to 1.04, "ASA" to 1.07, "TPU" to 1.21)

/**
 * What a manual add item still needs (item keys): vendor, name, material, net, tare and density (unless the
 * material has a usual one), and a spool count. Empty when complete.
 */
internal fun missingFields(item: JsonObject, needDensity: Boolean = true): List<String> = buildList {
    for (k in listOf("vendor", "name", "material")) if (item.text(k).isNullOrBlank()) add(k)
    for (k in listOf("net", "tare")) if (item.num(k)?.let(::isValidWeight) != true) add(k)
    if (needDensity && item.num("density")?.let(::isValidWeight) != true && defaultDensity(item.text("material")) == null) add("density")
    if (((item["count"] as? JsonPrimitive)?.intOrNull ?: 0) < 1) add("count")
}

/** A 400 from `add` that names one item's field: [index] into the items, [key] the field, [text] what is wrong. */
internal data class FieldError(val index: Int, val key: String, val text: String)

/**
 * Reads the server's `"<vendor> <name>: <field> must be ..."` (or `missing <field>`) message. The item is the one
 * with that vendor and name (or the only item); null when the message names no known field.
 */
internal fun fieldError(message: String, items: List<JsonObject>): FieldError? {
    val split = message.indexOf(": ")
    if (split < 0) return null
    val label = message.substring(0, split)
    val text = message.substring(split + 2).trim()
    val words = text.split(' ')
    val key = (if (words.firstOrNull() == "missing") words.getOrNull(1) else words.firstOrNull()) ?: return null
    if (key !in FIELD_KEYS) return null
    val index = items.indexOfFirst { "${it.text("vendor")} ${it.text("name")}" == label }
        .takeIf { it >= 0 } ?: if (items.size == 1) 0 else return null
    return FieldError(index, key, text.replaceFirstChar { it.uppercase() })
}

private val FIELD_KEYS = setOf(
    "vendor", "name", "material", "net", "tare", "density", "count", "gross", "location", "color_hex", "line",
    "bambu_parent", "nozzle", "bed", "lot", "note",
)

/** The Hub's rule for intake `line` and `bambu_parent` text (at most 100 characters, no `@`). */
sealed interface TextProblem {
    data object TooLong : TextProblem
    data object HasAt : TextProblem
}

fun intakeTextProblem(value: String): TextProblem? = when {
    value.length > 100 -> TextProblem.TooLong
    '@' in value -> TextProblem.HasAt
    else -> null
}

/** A text value of an item (null when missing, JSON null or not a string). */
private fun JsonObject.text(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content

/**
 * [key] was edited by the person: its confidence mark is gone (it leaves the read's `estimates` and joins the
 * app-only [AddViewModel.TOUCHED] list, which is never sent).
 */
private fun JsonObject.touched(key: String?): JsonObject {
    if (key == null) return this
    val keys = (this[AddViewModel.TOUCHED] as? JsonArray).orEmpty()
    val estimates = this["estimates"] as? JsonArray
    var o = this
    if (keys.none { (it as? JsonPrimitive)?.contentOrNull == key }) {
        o = JsonObject(o + (AddViewModel.TOUCHED to JsonArray(keys + JsonPrimitive(key))))
    }
    if (estimates != null && estimates.any { (it as? JsonPrimitive)?.contentOrNull == key }) {
        o = JsonObject(o + ("estimates" to JsonArray(estimates.filterNot { (it as? JsonPrimitive)?.contentOrNull == key })))
    }
    return o
}

/** Whole numbers stay integers in the JSON (and on screen). */
internal fun number(v: Double): JsonPrimitive =
    if (v == Math.floor(v) && !v.isInfinite() && kotlin.math.abs(v) < 1e15) JsonPrimitive(v.toLong()) else JsonPrimitive(v)

internal fun grams(v: Double): String = number(v).content

/** The ids of spools a failed `spoolman_error` add had already created. */
internal fun partialIds(e: ApiError): List<Long> = (e.extra["partial_spool_ids"] as? JsonArray).orEmpty()
    .mapNotNull { (it as? JsonPrimitive)?.longOrNull }

/** The words for a failure (05-android-app 3.5, 6.2): from the real [ApiError] shapes and the Hub's own message. */
internal fun describe(e: Exception): AddError = when (e) {
    is FingerprintMismatch -> AddError(
        AddText.of(R.string.common_cert_changed_notice),
        pairAgain = true, expectedFingerprint = e.expected, actualFingerprint = e.actual,
    )
    is ApiError -> describeApi(e)
    else -> AddError(AddText.of(R.string.common_hub_answer_unknown))
}

private fun describeApi(e: ApiError): AddError {
    val again = { text: AddText, byHand: Boolean -> AddError(text, canRetry = true, canAddByHand = byHand) }
    val unreadable = AddText.of(R.string.add_read_unreadable)
    // the local reader's own failures: busy is busy; every other kind is "could not read" to the person
    if (e.code == "local_busy") return again(AddText.of(R.string.add_read_busy), false)
    if (e.code.startsWith("local_")) return again(unreadable, true)
    return when {
        e.code == "offline" && e.status == 0 -> again(AddText.of(R.string.common_hub_unreachable), false)
        e.code == "local_network" -> AddError(AddText.hub(LOCAL_NETWORK_MESSAGE), canRetry = true)
        e.code == "unauthorized" -> AddError(AddText.of(R.string.common_not_paired_notice), pairAgain = true)
        e.code == "daily_cap" -> AddError(AddText.of(R.string.add_read_limit), canAddByHand = true)
        e.code == "bad_key" -> again(AddText.of(R.string.add_read_key_refused), false)
        e.code == "rate_limited" -> again(AddText.of(R.string.add_read_busy), false)
        e.code == "unreachable" -> again(AddText.of(R.string.add_read_cloud), false)
        e.code == "refused" || e.code == "truncated" || e.code == "api_error" -> again(unreadable, true)
        e.code == "not_found" -> again(AddText.of(R.string.add_read_photos_gone), false)
        e.code == "spoolman_unreachable" -> again(AddText.of(R.string.common_spoolman_unreachable), false)
        e.code == "bad_photo" -> AddError(AddText.of(R.string.add_read_photo_unusable))
        e.code == "tag_conflict" -> AddError(AddText.of(R.string.add_read_tag_linked), canDropTag = true)
        e.code == "module_off" -> AddError(AddText.of(R.string.home_label_reader_off), canAddByHand = true)
        // the Hub's own message goes through as given, unless it is not the Hub speaking
        e.code == ApiError.BAD_RESPONSE || e.notFromHub -> AddError(AddText.of(R.string.common_hub_answer_unknown))
        else -> AddError(AddText.hub(e.message), canRetry = e.code != "bad_request" && e.code != "unknown_parent")
    }
}
