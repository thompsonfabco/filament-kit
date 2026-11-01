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
import com.thompsonfabco.filamentkit.net.ReadResult
import com.thompsonfabco.filamentkit.tags.TagEvents
import java.io.File
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
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

    companion object {
        fun of(api: Api): IntakeApi = object : IntakeApi {
            override suspend fun read(photos: List<ByteArray>, hint: String, tag: String?) = api.read(photos, hint, tag)
            override suspend fun retry(readId: String) = api.retry(readId)
            override suspend fun add(items: JsonArray, dryRun: Boolean, tag: String?) = api.add(items, dryRun, tag)
            override suspend fun locations() = api.locations()
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
)

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
            _state.update { it.copy(photos = photos) }
        }
    }

    fun setHint(text: String) = edit { it.copy(hint = text) }

    /** Grams on the scale, spool included; only used for one opened spool. */
    fun setWeight(grams: Double?) = edit { it.copy(weight = grams, sealed = if (grams != null) false else it.sealed) }

    fun setSealed(sealed: Boolean) = edit { it.copy(sealed = sealed, weight = if (sealed) null else it.weight) }

    fun clearTag() = edit { it.copy(tag = null) }

    private fun setTag(uid: String) = edit { it.copy(tag = uid) }

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
                tag = res.tag ?: it.tag, previewLines = emptyList(), error = null, generation = it.generation + 1,
            )
        }
        save()
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
    }

    fun setNumber(index: Int, key: String, value: Double?) =
        editItem(index) { JsonObject(it + (key to (value?.let(::number) ?: JsonNull))) }

    fun setCount(index: Int, count: Int?) =
        editItem(index) { JsonObject(it + ("count" to (count?.let { c -> JsonPrimitive(c) } ?: JsonNull))) }

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
        if (index !in _state.value.items.indices) return
        _state.update { s ->
            s.copy(items = s.items.filterIndexed { i, _ -> i != index }, generation = s.generation + 1).unpreviewed()
        }
        save()
    }

    private fun editItem(index: Int, change: (JsonObject) -> JsonObject) {
        if (index !in _state.value.items.indices) return
        _state.update { s -> s.copy(items = s.items.mapIndexed { i, o -> if (i == index) change(o) else o }).unpreviewed() }
        save()
    }

    /** Any edit after a preview needs a new preview before Add. */
    private fun AddUiState.unpreviewed() =
        if (stage == Stage.Preview) copy(stage = Stage.Review, previewLines = emptyList()) else this

    fun preview() {
        val s = _state.value
        if (s.items.isEmpty() || s.stage != Stage.Review) return
        runAdd(dryRun = true)
    }

    fun confirm() {
        if (_state.value.stage != Stage.Preview) return
        runAdd(dryRun = false)
    }

    private fun runAdd(dryRun: Boolean) {
        val s = _state.value
        val back = if (dryRun) Stage.Review else Stage.Preview
        _state.update { it.copy(stage = if (dryRun) Stage.Previewing else Stage.Adding, error = null) }
        viewModelScope.launch {
            try {
                val res = api.add(JsonArray(s.items), dryRun, s.tag)
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
                val err = describe(e)
                // Spoolman failed part-way: spools may exist now, so a fresh preview is needed before adding again.
                val stage = if ((e as? ApiError)?.code == "spoolman_error") Stage.Review else back
                _state.update { it.copy(stage = stage, previewLines = if (stage == Stage.Review) emptyList() else it.previewLines) }
                retryAction = { runAdd(dryRun) }
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

    /** After a tag conflict: forget the tag and repeat the step without it. */
    fun dropTagAndRetry() {
        val action = retryAction ?: return
        retryAction = null
        _state.update { it.copy(tag = null, error = null) }
        save()
        action()
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
        _state.update { AddUiState(locations = it.locations, generation = it.generation + 1) }
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
                generation = it.generation + 1,
            )
        }
    }

    companion object {
        const val MAX_PHOTOS = 8
        private val REQUIRED_TEXT = setOf("vendor", "name", "material")
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

/** Whole numbers stay integers in the JSON (and on screen). */
internal fun number(v: Double): JsonPrimitive =
    if (v == Math.floor(v) && !v.isInfinite() && kotlin.math.abs(v) < 1e15) JsonPrimitive(v.toLong()) else JsonPrimitive(v)

internal fun grams(v: Double): String = number(v).content

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
            val ids = (e.extra["partial_spool_ids"] as? JsonArray).orEmpty()
                .mapNotNull { (it as? JsonPrimitive)?.longOrNull }
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
