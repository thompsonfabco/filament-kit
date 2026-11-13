package com.thompsonfabco.filamentkit.ui.spool

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.ui.parseWeight
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

/** What the Hub says the spool's remaining weight becomes, from a dry run of the typed weight. */
data class WeightPreview(val becomes: Double?, val now: Double?)

/**
 * The Update weight sheet (05 7.3). [text] is what was typed; [preview] belongs to [previewOf] and is dropped when the
 * text changes. [failure] is a dry run or a save the Hub refused ([failedSave] says which, for Try again). [leaving] is
 * the "Leave without saving?" question being asked.
 */
data class WeightUi(
    val text: String = "",
    val preview: WeightPreview? = null,
    val previewOf: String? = null,
    val previewing: Boolean = false,
    val saving: Boolean = false,
    val failure: HubFailure? = null,
    val failedSave: Boolean = false,
    val leaving: Boolean = false,
) {
    val grams: Double? get() = parseWeight(text)

    /** Something was typed: leaving asks first (05 2.5 rule 1). */
    val dirty: Boolean get() = text.isNotBlank()

    /** Typed, but not grams above 0. */
    val invalid: Boolean get() = text.isNotBlank() && grams == null

    /** The weight can be saved: a valid one whose preview is on screen. */
    val canSave: Boolean get() = !saving && grams != null && preview != null && previewOf == text
}

/** The Move sheet (05 7.4): [locations] null while they load; [movingTo] is the row being saved, [lastTry] the one that failed. */
data class MoveUi(
    val locations: List<String>? = null,
    val movingTo: String? = null,
    val failure: HubFailure? = null,
    val lastTry: String? = null,
)

/** The toast of a move, with what Undo moves back to. */
data class MoveToast(val location: String, val previous: String?)

/** What Try again repeats after a failure on the spool screen itself. */
sealed interface Retry {
    data object Refresh : Retry
    data object MarkEmpty : Retry
    data class UndoMove(val to: String) : Retry
}

/**
 * The spool screen (05 7.2). It opens with the summary it was given ([initial]) and, with none (after a restart), asks
 * the Hub for it; after every change it shows the Hub's answer. [openedByTag] is the tag that led here, if one did.
 */
data class SpoolUi(
    val spool: SpoolSummary? = null,
    val openedByTag: String? = null,
    val loading: Boolean = false,
    /** When [spool] was last read from the Hub (epoch millis), for the offline notice. */
    val loadedAt: Long? = null,
    val result: SpoolResult? = null,
    val failure: HubFailure? = null,
    val retry: Retry? = null,
    val weight: WeightUi? = null,
    val move: MoveUi? = null,
    val confirmEmpty: Boolean = false,
    val emptying: Boolean = false,
    val moveToast: MoveToast? = null,
) {
    /** A write is in flight: Back, the scrim and Cancel wait for its answer. */
    val writing: Boolean get() = weight?.saving == true || move?.movingTo != null || emptying
}

class SpoolViewModel(
    private val id: Int,
    private val backend: SpoolBackend,
    initial: SpoolSummary? = null,
    openedByTag: String? = null,
    startResult: SpoolResult? = null,
    private val handle: SavedStateHandle = SavedStateHandle(),
    private val previewPauseMs: Long = PREVIEW_PAUSE_MS,
    private val now: () -> Long = System::currentTimeMillis,
) : ViewModel() {
    // a typed weight and the question about leaving it live in the saved state: they survive the process being stopped
    private val restoredWeight = handle.get<String>(WEIGHT_KEY)?.let { WeightUi(it, leaving = handle.get<Boolean>(LEAVING_KEY) == true) }
    private val _state = MutableStateFlow(
        SpoolUi(
            spool = initial, openedByTag = openedByTag, loading = initial == null, result = startResult,
            loadedAt = initial?.let { now() }, weight = restoredWeight,
        ),
    )
    val state: StateFlow<SpoolUi> = _state.asStateFlow()
    private var previewJob: Job? = null
    private var refreshing: Job? = null

    init {
        // a result the screen that was open over this one ended with (a load) is put into this entry's saved state
        viewModelScope.launch {
            handle.getStateFlow<String?>(RESULT_KEY, null).collect { text ->
                val result = text?.let(SpoolResult::decode) ?: return@collect
                handle[RESULT_KEY] = null
                // the Hub's answer to that change is in the cache
                _state.update {
                    it.copy(result = result, spool = SpoolCache.get(id) ?: it.spool, loadedAt = now(), failure = it.failure.afterSuccess())
                }
            }
        }
        restoredWeight?.let { if (parseWeight(it.text) != null) startPreview(it.text) }
        if (initial == null) refresh()
    }

    private fun shown(spool: SpoolSummary) = spool.also(SpoolCache::put)

    /** Asks the Hub for this spool again, by its number (`GET api/spools/{id}`): never another spool. */
    fun refresh() {
        if (refreshing?.isActive == true) return
        _state.update { it.copy(loading = true) }
        refreshing = run(onFailure = { f -> _state.update { it.copy(loading = false, failure = f, retry = Retry.Refresh) } }) {
            val found = backend.spool(id).toSpoolSummary()
            _state.update { s ->
                s.copy(loading = false, spool = shown(found), loadedAt = now(), failure = null, retry = null)
            }
        }
    }

    /** Try again: repeats what failed. */
    fun retry() {
        when (val r = _state.value.retry) {
            Retry.Refresh, null -> refresh()
            Retry.MarkEmpty -> confirmEmpty()
            is Retry.UndoMove -> undoMove(r.to)
        }
    }

    // --- Update weight ---

    fun openWeight() {
        handle[WEIGHT_KEY] = ""
        _state.update { it.copy(weight = WeightUi()) }
    }

    /** Typing again drops the preview; 400 ms after a valid weight the Hub is asked what it would become. */
    fun setWeight(text: String) {
        val w = _state.value.weight ?: return
        if (w.saving) return
        previewJob?.cancel()
        handle[WEIGHT_KEY] = text
        _state.update {
            it.copy(weight = w.copy(text = text, preview = null, previewOf = null, previewing = false, failure = null, failedSave = false))
        }
        if (parseWeight(text) != null) startPreview(text)
    }

    private fun startPreview(text: String) {
        val grams = parseWeight(text) ?: return
        _state.update { it.copy(weight = it.weight?.copy(previewing = true)) }
        previewJob = viewModelScope.launch {
            delay(previewPauseMs)
            try {
                val updated = backend.update(id, grams, null, empty = false, dryRun = true).toSpoolSummary()
                _state.update { s ->
                    s.copy(
                        weight = s.weight?.takeIf { it.text == text }?.copy(
                            previewing = false, preview = WeightPreview(updated.remaining, s.spool?.remaining), previewOf = text,
                        ) ?: s.weight,
                        failure = s.failure.afterSuccess(),
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { s ->
                    s.copy(weight = s.weight?.takeIf { it.text == text }?.copy(previewing = false, failure = hubFailure(e)) ?: s.weight)
                }
            }
        }
    }

    fun saveWeight() {
        val w = _state.value.weight?.takeIf { it.canSave } ?: return
        val grams = w.grams ?: return
        previewJob?.cancel()
        _state.update { it.copy(weight = w.copy(saving = true, failure = null, failedSave = false)) }
        run(onFailure = { f -> _state.update { it.copy(weight = it.weight?.copy(saving = false, failure = f, failedSave = true)) } }) {
            val updated = backend.update(id, grams, null, empty = false, dryRun = false).toSpoolSummary()
            clearWeightKeys()
            _state.update {
                it.copy(
                    spool = shown(updated), weight = null, loadedAt = now(), result = SpoolResult.WeightUpdated(updated.remaining),
                    failure = it.failure.afterSuccess(),
                )
            }
        }
    }

    /** Try again in the sheet: the save that failed (its preview is still the one the person saw), else the preview. */
    fun retryWeight() {
        val w = _state.value.weight ?: return
        if (w.failedSave) saveWeight() else setWeight(w.text)
    }

    /** Back, the scrim or Cancel on the sheet: typed text asks first (05 2.5 rule 1); a save in flight is waited for. */
    fun askLeaveWeight() {
        val w = _state.value.weight ?: return
        if (w.saving) return
        if (w.dirty) {
            handle[LEAVING_KEY] = true
            _state.update { it.copy(weight = w.copy(leaving = true)) }
        } else {
            closeWeight()
        }
    }

    /** "Stay": the question goes, the text stays. */
    fun stayWeight() {
        handle[LEAVING_KEY] = false
        _state.update { it.copy(weight = it.weight?.copy(leaving = false)) }
    }

    /** Closes the sheet and drops what was typed; not while the weight is being saved. */
    fun closeWeight() {
        if (_state.value.weight?.saving == true) return
        previewJob?.cancel()
        clearWeightKeys()
        _state.update { it.copy(weight = null) }
    }

    private fun clearWeightKeys() {
        handle.remove<String>(WEIGHT_KEY)
        handle.remove<Boolean>(LEAVING_KEY)
    }

    // --- Move ---

    fun openMove() {
        _state.update { it.copy(move = MoveUi()) }
        loadLocations()
    }

    private fun loadLocations() {
        run(onFailure = { f -> _state.update { it.copy(move = it.move?.copy(failure = f)) } }) {
            val all = backend.locations()
            _state.update { it.copy(move = it.move?.copy(locations = all, failure = null), failure = it.failure.afterSuccess()) }
        }
    }

    /** Try again in the sheet: the list, else the move that failed. */
    fun retryMove() {
        val m = _state.value.move ?: return
        val target = m.lastTry
        if (m.locations == null || target == null) {
            _state.update { it.copy(move = it.move?.copy(failure = null)) }
            loadLocations()
        } else {
            move(target)
        }
    }

    /** Saves a move at once; the current location only closes the sheet. */
    fun move(location: String) {
        val s = _state.value
        val m = s.move ?: return
        if (m.movingTo != null) return
        if (location == s.spool?.location) {
            _state.update { it.copy(move = null) }
            return
        }
        _state.update { it.copy(move = m.copy(movingTo = location, failure = null)) }
        moveTo(location, previous = s.spool?.location, fromSheet = true)
    }

    /** The toast's Undo: the same request back to where it was. */
    fun undoMove(previous: String) {
        moveTo(previous, previous = null, fromSheet = false)
    }

    private fun moveTo(location: String, previous: String?, fromSheet: Boolean) {
        run(
            onFailure = { f ->
                _state.update {
                    it.copy(
                        move = it.move?.copy(movingTo = null, failure = f, lastTry = location),
                        failure = if (fromSheet) it.failure else f,
                        retry = if (fromSheet) it.retry else Retry.UndoMove(location),
                    )
                }
            },
        ) {
            val updated = backend.update(id, null, location, empty = false, dryRun = false).toSpoolSummary()
            _state.update {
                it.copy(
                    spool = shown(updated), move = null, loadedAt = now(), result = SpoolResult.Moved(location),
                    moveToast = if (fromSheet) MoveToast(location, previous) else null, failure = it.failure.afterSuccess(),
                )
            }
        }
    }

    /** The toast was shown (or replaced); it is not shown again. */
    fun toastShown() {
        _state.update { it.copy(moveToast = null) }
    }

    /** Closes the sheet; not while a move is being saved. */
    fun closeMove() {
        if (_state.value.move?.movingTo != null) return
        _state.update { it.copy(move = null) }
    }

    // --- Mark empty ---

    fun askMarkEmpty() {
        _state.update { it.copy(confirmEmpty = true) }
    }

    fun cancelEmpty() {
        if (_state.value.emptying) return
        _state.update { it.copy(confirmEmpty = false) }
    }

    fun confirmEmpty() {
        if (_state.value.emptying) return
        _state.update { it.copy(emptying = true, failure = null) }
        run(onFailure = { f -> _state.update { it.copy(emptying = false, confirmEmpty = false, failure = f, retry = Retry.MarkEmpty) } }) {
            val updated = backend.update(id, null, null, empty = true, dryRun = false).toSpoolSummary()
            _state.update {
                it.copy(
                    spool = shown(updated), emptying = false, confirmEmpty = false, loadedAt = now(),
                    result = SpoolResult.MarkedEmpty, failure = it.failure.afterSuccess(),
                )
            }
        }
    }

    // --- plumbing ---

    private fun run(onFailure: (HubFailure) -> Unit, block: suspend () -> Unit): Job =
        viewModelScope.launch {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                onFailure(hubFailure(e))
            }
        }

    companion object {
        const val PREVIEW_PAUSE_MS = 400L

        /** The saved-state key a finished load puts its [SpoolResult.encode]d result under. */
        const val RESULT_KEY = "result"
        private const val WEIGHT_KEY = "weight"
        private const val LEAVING_KEY = "leaving"
    }
}

/** The spool summary a result carries: the spool JSON of a link or a load, when the Hub sent it. */
internal fun JsonObject?.asSummary(): SpoolSummary? = this?.toSpoolSummary()?.takeIf { it.id != 0 }
