package com.thompsonfabco.filamentkit.ui.spool

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.ApiError
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
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/** The tag screen (05 7.7): the lookup, then the spool it is linked to, or nothing. */
sealed interface TagUi {
    data object Looking : TagUi

    /** Linked: the screen replaces itself with the spool screen. */
    data class Linked(val spool: SpoolSummary) : TagUi
    data object NotLinked : TagUi
    data class Failed(val failure: HubFailure) : TagUi
}

/** Looks up tag [uid] when it is made; [lookUp] asks again. */
class TagViewModel(private val uid: String, private val backend: SpoolBackend) : ViewModel() {
    private val _state = MutableStateFlow<TagUi>(TagUi.Looking)
    val state: StateFlow<TagUi> = _state.asStateFlow()

    init {
        lookUp()
    }

    fun lookUp() {
        _state.value = TagUi.Looking
        viewModelScope.launch {
            _state.value = try {
                backend.tag(uid)?.toSpoolSummary()?.let { SpoolCache.put(it); TagUi.Linked(it) } ?: TagUi.NotLinked
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                TagUi.Failed(hubFailure(e))
            }
        }
    }
}

/** Find a sealed spool for a tag (05 7.8): [query] and the optional [weight], the sealed spools found. */
data class LinkFindUi(
    val query: String = "",
    val weight: String = "",
    val busy: Boolean = false,
    val searched: Boolean = false,
    val results: List<SpoolSummary> = emptyList(),
    val failure: HubFailure? = null,
) {
    /** Typed, but not grams above 0: the rows are off until it is fixed or emptied. */
    val weightInvalid: Boolean get() = weight.isNotBlank() && parseWeight(weight) == null
}

class LinkFindViewModel(
    private val backend: SpoolBackend,
    private val pauseMs: Long = SEARCH_PAUSE_MS,
) : ViewModel() {
    private val _state = MutableStateFlow(LinkFindUi())
    val state: StateFlow<LinkFindUi> = _state.asStateFlow()
    private var typing: Job? = null
    private var searching: Job? = null

    /** The same rules as the Spools search: after a pause once two letters are typed, and a blank box clears the rows. */
    fun setQuery(q: String) {
        _state.update { it.copy(query = q) }
        typing?.cancel()
        if (q.isBlank()) {
            searching?.cancel()
            _state.update { it.copy(busy = false, searched = false, results = emptyList(), failure = null) }
        } else if (q.trim().length >= MIN_TYPED) {
            typing = viewModelScope.launch {
                delay(pauseMs)
                search()
            }
        }
    }

    fun setWeight(text: String) {
        _state.update { it.copy(weight = text) }
    }

    fun search() {
        val q = _state.value.query.trim()
        if (q.isEmpty()) return
        typing?.cancel()
        searching?.cancel()
        _state.update { it.copy(busy = true, failure = null) }
        searching = viewModelScope.launch {
            try {
                val found = backend.search(q, true).map { it.toSpoolSummary() }
                found.forEach(SpoolCache::put)
                _state.update { it.copy(busy = false, searched = true, results = found, failure = null) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(busy = false, failure = hubFailure(e)) }
            }
        }
    }

    companion object {
        const val MIN_TYPED = 2
        const val SEARCH_PAUSE_MS = 300L
    }
}

enum class ConflictReason { TagOnOtherSpool, SpoolHasOtherTag }

/** The link preview (05 7.8): a dry run, then the link; or the tag is already in use. */
data class LinkPreviewUi(
    val checking: Boolean = true,
    val spool: SpoolSummary? = null,
    /** The tag is linked elsewhere ([TagOnOtherSpool]) or the spool has another tag; [other] is the spool it is on. */
    val conflict: ConflictReason? = null,
    val other: SpoolSummary? = null,
    val linking: Boolean = false,
    val failure: HubFailure? = null,
    /** [failure] came from the write, not the dry run: Try again sends it again ([lastForce] as it was). */
    val failedWrite: Boolean = false,
    val lastForce: Boolean = false,
    /** The link was written; the screen goes to the spool screen, which shows this as its result line. */
    val finished: SpoolResult? = null,
)

/**
 * Previews linking tag [uid] to spool [spoolId] with the optional [gross] weight when it is made, then links it. A tag
 * already in use is asked about, and [moveHere] sends the same link with `force`.
 */
class LinkPreviewViewModel(
    private val uid: String,
    private val spoolId: Int,
    val gross: Double?,
    private val backend: SpoolBackend,
    private val gate: LoadGate = LoadGate(),
) : ViewModel() {
    private val _state = MutableStateFlow(LinkPreviewUi(spool = SpoolCache.get(spoolId)))
    val state: StateFlow<LinkPreviewUi> = _state.asStateFlow()

    init {
        check()
    }

    /** Try again: the write that failed, else the dry run. */
    fun retry() {
        val s = _state.value
        if (s.failedWrite) write(s.lastForce) else check()
    }

    fun check() {
        _state.update { it.copy(checking = true, failure = null, failedWrite = false, conflict = null, other = null) }
        viewModelScope.launch {
            try {
                val spool = backend.link(spoolId, uid, force = false, dryRun = true, gross = gross).toSpoolSummary()
                _state.update { it.copy(checking = false, spool = spool.copy(id = spoolId), failure = it.failure.afterSuccess()) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { failed(it.copy(checking = false), e) }
            }
        }
    }

    fun link() = write(force = false)

    fun moveHere() = write(force = true)

    private fun write(force: Boolean) {
        val s = _state.value
        if (s.linking || s.finished != null) return
        _state.update { it.copy(linking = true, failure = null, failedWrite = false, lastForce = force) }
        // a tag tapped meanwhile waits: the write is not cut short by another screen
        gate.set(true, link = true)
        viewModelScope.launch {
            try {
                val spool = backend.link(spoolId, uid, force = force, dryRun = false, gross = gross).toSpoolSummary().copy(id = spoolId)
                SpoolCache.put(spool)
                _state.update { it.copy(linking = false, finished = if (force) SpoolResult.TagMoved else SpoolResult.TagLinked) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { failed(it.copy(linking = false), e).let { f -> if (f.failure != null) f.copy(failedWrite = true) else f } }
            } finally {
                gate.set(false)
            }
        }
    }

    override fun onCleared() {
        gate.set(false)
    }

    private fun failed(s: LinkPreviewUi, e: Exception): LinkPreviewUi {
        if (e is ApiError && e.code == CONFLICT) {
            val reason = when ((e.extra[REASON] as? JsonPrimitive)?.contentOrNull) {
                OTHER_TAG -> ConflictReason.SpoolHasOtherTag
                else -> ConflictReason.TagOnOtherSpool
            }
            return s.copy(conflict = reason, other = (e.extra[OTHER] as? JsonObject)?.toSpoolSummary(), failure = null)
        }
        return s.copy(failure = hubFailure(e))
    }

    private companion object {
        const val CONFLICT = "tag_conflict"
        const val REASON = "reason"
        const val OTHER = "other_spool"
        const val OTHER_TAG = "spool_has_other_tag"
    }
}
