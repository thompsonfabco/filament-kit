package com.thompsonfabco.filamentkit.ui.spool

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull

/** The server calls the VM needs; [ApiSpoolBackend] adapts [Api], tests pass a fake. */
interface SpoolBackend {
    suspend fun tag(uid: String): JsonObject?
    suspend fun link(spoolId: Int, tag: String, force: Boolean, dryRun: Boolean, gross: Double?): JsonObject
    suspend fun update(spoolId: Int, gross: Double?, location: String?, empty: Boolean, dryRun: Boolean): JsonObject
    suspend fun searchSealed(q: String): List<JsonObject>
    suspend fun locations(): List<String>
}

class ApiSpoolBackend(private val api: Api) : SpoolBackend {
    override suspend fun tag(uid: String) = api.tag(uid)
    override suspend fun link(spoolId: Int, tag: String, force: Boolean, dryRun: Boolean, gross: Double?) =
        api.link(spoolId, tag, force, dryRun, gross, null)

    override suspend fun update(spoolId: Int, gross: Double?, location: String?, empty: Boolean, dryRun: Boolean) =
        api.update(spoolId, gross, null, location, empty, dryRun)

    override suspend fun searchSealed(q: String) = api.search(q, sealedOnly = true)
    override suspend fun locations() = api.locations()
}

/** The fields of a Spoolman spool the card shows. */
data class SpoolSummary(
    val id: Int,
    val brand: String,
    val name: String,
    val material: String,
    val colorHex: String?,
    val location: String?,
    val remaining: Double?,
)

fun JsonObject.toSpoolSummary(): SpoolSummary {
    val filament = this["filament"] as? JsonObject
    val vendor = filament?.get("vendor") as? JsonObject
    fun JsonElement?.text(): String? = (this as? JsonPrimitive)?.contentOrNull
    return SpoolSummary(
        id = (this["id"] as? JsonPrimitive)?.intOrNull ?: 0,
        brand = vendor?.get("name").text().orEmpty(),
        name = filament?.get("name").text().orEmpty(),
        material = filament?.get("material").text().orEmpty(),
        colorHex = filament?.get("color_hex").text(),
        location = this["location"].text()?.ifBlank { null },
        remaining = (this["remaining_weight"] as? JsonPrimitive)?.doubleOrNull,
    )
}

enum class ConflictReason { TagOnOtherSpool, SpoolHasOtherTag }

sealed interface SpoolUiState {
    data object Idle : SpoolUiState
    data object Loading : SpoolUiState

    /**
     * [weightPreview] is the dry-run result of "Update weight"; [locations] is non-null while the Move list is open;
     * [rev] changes whenever a fresh card arrives (the UI resets its input fields on it).
     */
    data class Card(
        val spool: SpoolSummary,
        val weightPreview: SpoolSummary? = null,
        val pendingGross: Double? = null,
        val confirmEmpty: Boolean = false,
        val locations: List<String>? = null,
        val message: String? = null,
        val rev: Int = 0,
    ) : SpoolUiState

    data class UnknownTag(val tag: String) : SpoolUiState
    data class LinkSearch(
        val tag: String,
        val results: List<SpoolSummary> = emptyList(),
        val searched: Boolean = false,
        val error: String? = null,
    ) : SpoolUiState

    data class LinkPreview(val tag: String, val spool: SpoolSummary, val gross: Double?, val error: String? = null) : SpoolUiState
    data class Conflict(
        val tag: String,
        val spoolId: Int,
        val gross: Double?,
        val reason: ConflictReason,
        val otherSpool: SpoolSummary?,
        val message: String,
        val error: String? = null,
    ) : SpoolUiState

    /** A lookup failed; [retryTag] (when set) is offered as "Try again". */
    data class Failed(val message: String, val retryTag: String? = null) : SpoolUiState

    /** The server rejected the token (401): offer "Pair again". */
    data object Unauthorized : SpoolUiState
    data class Mismatch(val expected: String, val actual: String) : SpoolUiState
}

class SpoolViewModel(private val backend: SpoolBackend) : ViewModel() {
    private val _state = MutableStateFlow<SpoolUiState>(SpoolUiState.Idle)
    val state: StateFlow<SpoolUiState> = _state.asStateFlow()

    private var tag: String? = null
    private var job: Job? = null
    private var rev = 0

    private fun card(spool: SpoolSummary, message: String? = null) = SpoolUiState.Card(spool, message = message, rev = ++rev)

    /** A tag was tapped; replaces whatever is open and cancels any lookup, search or link still in flight. */
    fun onTag(uid: String) {
        tag = uid
        _state.value = SpoolUiState.Loading
        op(onError = { SpoolUiState.Failed(it, retryTag = uid) }) {
            val spool = backend.tag(uid)
            _state.value = if (spool == null) SpoolUiState.UnknownTag(uid) else card(spool.toSpoolSummary())
        }
    }

    fun dismiss() {
        job?.cancel()
        _state.value = SpoolUiState.Idle
    }

    // --- known spool ---

    fun previewWeight(gross: Double) {
        val c = _state.value as? SpoolUiState.Card ?: return
        op(onError = { c.copy(message = it) }) {
            val preview = backend.update(c.spool.id, gross, null, empty = false, dryRun = true).toSpoolSummary()
            _state.value = c.copy(weightPreview = preview, pendingGross = gross, message = null)
        }
    }

    fun cancelWeight() {
        (_state.value as? SpoolUiState.Card)?.let { _state.value = it.copy(weightPreview = null, pendingGross = null) }
    }

    fun confirmWeight() {
        val c = _state.value as? SpoolUiState.Card ?: return
        val gross = c.pendingGross ?: return
        op(onError = { c.copy(message = it) }) {
            val updated = backend.update(c.spool.id, gross, null, empty = false, dryRun = false).toSpoolSummary()
            _state.value = card(updated, "Weight updated")
        }
    }

    fun openMove() {
        val c = _state.value as? SpoolUiState.Card ?: return
        op(onError = { c.copy(message = it) }) {
            _state.value = c.copy(locations = backend.locations(), message = null)
        }
    }

    fun closeMove() {
        (_state.value as? SpoolUiState.Card)?.let { _state.value = it.copy(locations = null) }
    }

    fun move(location: String) {
        val c = _state.value as? SpoolUiState.Card ?: return
        op(onError = { c.copy(message = it) }) {
            val updated = backend.update(c.spool.id, null, location, empty = false, dryRun = false).toSpoolSummary()
            _state.value = card(updated, "Moved to $location")
        }
    }

    fun askMarkEmpty() {
        (_state.value as? SpoolUiState.Card)?.let { _state.value = it.copy(confirmEmpty = true) }
    }

    fun cancelEmpty() {
        (_state.value as? SpoolUiState.Card)?.let { _state.value = it.copy(confirmEmpty = false) }
    }

    fun confirmEmpty() {
        val c = _state.value as? SpoolUiState.Card ?: return
        op(onError = { c.copy(confirmEmpty = false, message = it) }) {
            val updated = backend.update(c.spool.id, null, null, empty = true, dryRun = false).toSpoolSummary()
            _state.value = card(updated, "Marked empty")
        }
    }

    // --- unknown tag: link to a sealed spool ---

    fun startLink() {
        val t = tag ?: return
        job?.cancel()
        _state.value = SpoolUiState.LinkSearch(t)
    }

    fun search(q: String) {
        val s = _state.value as? SpoolUiState.LinkSearch ?: return
        op(onError = { s.copy(error = it) }) {
            val found = backend.searchSealed(q).map { it.toSpoolSummary() }
            _state.value = SpoolUiState.LinkSearch(s.tag, found, searched = true)
        }
    }

    fun backToChoice() {
        job?.cancel()
        tag?.let { _state.value = SpoolUiState.UnknownTag(it) }
    }

    /** Previews linking tag to [spoolId] (dry run); [gross] is the optional gross weight to record. */
    fun pick(spoolId: Int, gross: Double?) {
        val t = tag ?: return
        val s = _state.value as? SpoolUiState.LinkSearch
        op(onError = { msg -> s?.copy(error = msg) ?: SpoolUiState.Failed(msg, retryTag = t) }, onConflict = { conflict(it, t, spoolId, gross) }) {
            val preview = backend.link(spoolId, t, force = false, dryRun = true, gross = gross).toSpoolSummary()
            _state.value = SpoolUiState.LinkPreview(t, preview.copy(id = spoolId), gross)
        }
    }

    fun confirmLink() {
        val p = _state.value as? SpoolUiState.LinkPreview ?: return
        op(onError = { p.copy(error = it) }, onConflict = { conflict(it, p.tag, p.spool.id, p.gross) }) {
            val linked = backend.link(p.spool.id, p.tag, force = false, dryRun = false, gross = p.gross).toSpoolSummary()
            _state.value = card(linked, "Tag linked")
        }
    }

    fun moveTagHere() {
        val c = _state.value as? SpoolUiState.Conflict ?: return
        op(onError = { c.copy(error = it) }, onConflict = { conflict(it, c.tag, c.spoolId, c.gross) }) {
            val linked = backend.link(c.spoolId, c.tag, force = true, dryRun = false, gross = c.gross).toSpoolSummary()
            _state.value = card(linked, "Tag moved")
        }
    }

    // --- plumbing ---

    private fun conflict(e: ApiError, tag: String, spoolId: Int, gross: Double?): SpoolUiState {
        val reason = when (e.extra["reason"]?.let { (it as? JsonPrimitive)?.contentOrNull }) {
            "spool_has_other_tag" -> ConflictReason.SpoolHasOtherTag
            else -> ConflictReason.TagOnOtherSpool
        }
        val other = (e.extra["other_spool"] as? JsonObject)?.toSpoolSummary()
        val message = when (reason) {
            ConflictReason.TagOnOtherSpool -> {
                val who = other?.let { "${it.brand} ${it.name} (spool #${it.id})".trim() } ?: "another spool"
                "This tag is already linked to $who. Moving it here unlinks it from there."
            }
            ConflictReason.SpoolHasOtherTag ->
                "This spool already has a different tag linked. Linking this tag replaces that spool's current tag."
        }
        return SpoolUiState.Conflict(tag, spoolId, gross, reason, other, message)
    }

    /**
     * Runs [block] on the VM scope, cancelling any operation still running. A `tag_conflict` goes to [onConflict]; a 401
     * always becomes [SpoolUiState.Unauthorized]; other [ApiError]s and any other exception become [onError]'s state
     * (so the screen the user is on stays put with an inline message); a [FingerprintMismatch] gets its own state.
     */
    private fun op(
        onError: (String) -> SpoolUiState,
        onConflict: ((ApiError) -> SpoolUiState)? = null,
        block: suspend () -> Unit,
    ) {
        job?.cancel()
        job = viewModelScope.launch {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: FingerprintMismatch) {
                _state.value = SpoolUiState.Mismatch(e.expected, e.actual)
            } catch (e: ApiError) {
                _state.value = when {
                    e.code == "unauthorized" -> SpoolUiState.Unauthorized
                    e.code == "tag_conflict" && onConflict != null -> onConflict(e)
                    else -> onError(messageFor(e))
                }
            } catch (e: Exception) {
                _state.value = onError("Unexpected response from the server")
            }
        }
    }

    private fun messageFor(e: ApiError): String = when (e.code) {
        "offline" -> "Could not reach the server. Check that you are on the same network."
        "not_found" -> "The server could not find that spool."
        else -> e.message
    }
}
