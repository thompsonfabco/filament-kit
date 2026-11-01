package com.thompsonfabco.filamentkit.ui.spool

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive

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
    val filament = (this["filament"] as? JsonObject)
    val vendor = filament?.get("vendor") as? JsonObject
    fun JsonElement?.text(): String? = (this as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNull
    return SpoolSummary(
        id = this["id"]?.jsonPrimitive?.intOrNull ?: 0,
        brand = vendor?.get("name").text().orEmpty(),
        name = filament?.get("name").text().orEmpty(),
        material = filament?.get("material").text().orEmpty(),
        colorHex = filament?.get("color_hex").text(),
        location = this["location"].text()?.ifBlank { null },
        remaining = (this["remaining_weight"] as? kotlinx.serialization.json.JsonPrimitive)?.doubleOrNull,
    )
}

enum class ConflictReason { TagOnOtherSpool, SpoolHasOtherTag }

sealed interface SpoolUiState {
    data object Idle : SpoolUiState
    data object Loading : SpoolUiState

    /** [weightPreview] is the dry-run result of "Update weight"; [locations] is non-null while the Move list is open. */
    data class Card(
        val spool: SpoolSummary,
        val weightPreview: SpoolSummary? = null,
        val pendingGross: Double? = null,
        val confirmEmpty: Boolean = false,
        val locations: List<String>? = null,
        val message: String? = null,
    ) : SpoolUiState

    data class UnknownTag(val tag: String) : SpoolUiState
    data class LinkSearch(val tag: String, val results: List<SpoolSummary> = emptyList(), val searched: Boolean = false) : SpoolUiState
    data class LinkPreview(val tag: String, val spool: SpoolSummary, val gross: Double?) : SpoolUiState
    data class Conflict(
        val tag: String,
        val spoolId: Int,
        val gross: Double?,
        val reason: ConflictReason,
        val otherSpool: SpoolSummary?,
        val message: String,
    ) : SpoolUiState

    data class Failed(val message: String) : SpoolUiState
    data class Mismatch(val expected: String, val actual: String) : SpoolUiState
}

class SpoolViewModel(private val backend: SpoolBackend) : ViewModel() {
    private val _state = MutableStateFlow<SpoolUiState>(SpoolUiState.Idle)
    val state: StateFlow<SpoolUiState> = _state.asStateFlow()

    private var tag: String? = null

    /** A tag was tapped (also resets any open card). */
    fun onTag(uid: String) {
        tag = uid
        _state.value = SpoolUiState.Loading
        op {
            val spool = backend.tag(uid)
            _state.value = if (spool == null) SpoolUiState.UnknownTag(uid) else SpoolUiState.Card(spool.toSpoolSummary())
        }
    }

    fun dismiss() {
        _state.value = SpoolUiState.Idle
    }

    // --- known spool ---

    fun previewWeight(gross: Double) {
        val card = _state.value as? SpoolUiState.Card ?: return
        op(onFail = { card.copy(message = it) }) {
            val preview = backend.update(card.spool.id, gross, null, empty = false, dryRun = true).toSpoolSummary()
            _state.value = card.copy(weightPreview = preview, pendingGross = gross, message = null)
        }
    }

    fun cancelWeight() {
        (_state.value as? SpoolUiState.Card)?.let { _state.value = it.copy(weightPreview = null, pendingGross = null) }
    }

    fun confirmWeight() {
        val card = _state.value as? SpoolUiState.Card ?: return
        val gross = card.pendingGross ?: return
        op(onFail = { card.copy(message = it) }) {
            val updated = backend.update(card.spool.id, gross, null, empty = false, dryRun = false).toSpoolSummary()
            _state.value = SpoolUiState.Card(updated, message = "Weight updated")
        }
    }

    fun openMove() {
        val card = _state.value as? SpoolUiState.Card ?: return
        op(onFail = { card.copy(message = it) }) {
            _state.value = card.copy(locations = backend.locations(), message = null)
        }
    }

    fun closeMove() {
        (_state.value as? SpoolUiState.Card)?.let { _state.value = it.copy(locations = null) }
    }

    fun move(location: String) {
        val card = _state.value as? SpoolUiState.Card ?: return
        op(onFail = { card.copy(message = it) }) {
            val updated = backend.update(card.spool.id, null, location, empty = false, dryRun = false).toSpoolSummary()
            _state.value = SpoolUiState.Card(updated, message = "Moved to $location")
        }
    }

    fun askMarkEmpty() {
        (_state.value as? SpoolUiState.Card)?.let { _state.value = it.copy(confirmEmpty = true) }
    }

    fun cancelEmpty() {
        (_state.value as? SpoolUiState.Card)?.let { _state.value = it.copy(confirmEmpty = false) }
    }

    fun confirmEmpty() {
        val card = _state.value as? SpoolUiState.Card ?: return
        op(onFail = { card.copy(confirmEmpty = false, message = it) }) {
            val updated = backend.update(card.spool.id, null, null, empty = true, dryRun = false).toSpoolSummary()
            _state.value = SpoolUiState.Card(updated, message = "Marked empty")
        }
    }

    // --- unknown tag: link to a sealed spool ---

    fun startLink() {
        val t = tag ?: return
        _state.value = SpoolUiState.LinkSearch(t)
    }

    fun search(q: String) {
        val t = tag ?: return
        op {
            val found = backend.searchSealed(q).map { it.toSpoolSummary() }
            _state.value = SpoolUiState.LinkSearch(t, found, searched = true)
        }
    }

    fun backToChoice() {
        tag?.let { _state.value = SpoolUiState.UnknownTag(it) }
    }

    /** Previews linking tag to [spoolId] (dry run); [gross] is the optional gross weight to record. */
    fun pick(spoolId: Int, gross: Double?) {
        val t = tag ?: return
        op(onError = { conflictOr(it, t, spoolId, gross) }) {
            val preview = backend.link(spoolId, t, force = false, dryRun = true, gross = gross).toSpoolSummary()
            _state.value = SpoolUiState.LinkPreview(t, preview.copy(id = spoolId), gross)
        }
    }

    fun confirmLink() {
        val p = _state.value as? SpoolUiState.LinkPreview ?: return
        op(onError = { conflictOr(it, p.tag, p.spool.id, p.gross) }) {
            val linked = backend.link(p.spool.id, p.tag, force = false, dryRun = false, gross = p.gross).toSpoolSummary()
            _state.value = SpoolUiState.Card(linked, message = "Tag linked")
        }
    }

    fun moveTagHere() {
        val c = _state.value as? SpoolUiState.Conflict ?: return
        op {
            val linked = backend.link(c.spoolId, c.tag, force = true, dryRun = false, gross = c.gross).toSpoolSummary()
            _state.value = SpoolUiState.Card(linked, message = "Tag moved")
        }
    }

    // --- plumbing ---

    private fun conflictOr(e: ApiError, tag: String, spoolId: Int, gross: Double?): SpoolUiState {
        if (e.code != "tag_conflict") return SpoolUiState.Failed(messageFor(e))
        val reason = when (e.extra["reason"]?.jsonPrimitive?.contentOrNull) {
            "spool_has_other_tag" -> ConflictReason.SpoolHasOtherTag
            else -> ConflictReason.TagOnOtherSpool
        }
        val other = (e.extra["other_spool"] as? JsonObject)?.toSpoolSummary()
        val message = when (reason) {
            ConflictReason.TagOnOtherSpool -> {
                val who = other?.let { "${it.brand} ${it.name} (spool #${it.id})".trim() } ?: "another spool"
                "This tag is already linked to $who."
            }
            ConflictReason.SpoolHasOtherTag -> "This spool already has a different tag linked."
        }
        return SpoolUiState.Conflict(tag, spoolId, gross, reason, other, message)
    }

    /**
     * Runs [block] on the VM scope. An [ApiError] becomes [onError]'s state, any other exception the generic message;
     * a [FingerprintMismatch] gets its own state.
     */
    private fun op(
        onError: (ApiError) -> SpoolUiState = { SpoolUiState.Failed(messageFor(it)) },
        onFail: ((String) -> SpoolUiState)? = null,
        block: suspend () -> Unit,
    ) {
        viewModelScope.launch {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: FingerprintMismatch) {
                _state.value = SpoolUiState.Mismatch(e.expected, e.actual)
            } catch (e: ApiError) {
                _state.value = if (onFail != null && e.code != "tag_conflict") onFail(messageFor(e)) else onError(e)
            } catch (e: Exception) {
                val msg = "Unexpected response from the server"
                _state.value = onFail?.invoke(msg) ?: SpoolUiState.Failed(msg)
            }
        }
    }

    private fun messageFor(e: ApiError): String = when (e.code) {
        "offline" -> "Could not reach the server. Check that you are on the same network."
        "unauthorized" -> "This phone is no longer paired with the server. Pair again."
        "not_found" -> "The server could not find that spool."
        else -> e.message
    }
}
