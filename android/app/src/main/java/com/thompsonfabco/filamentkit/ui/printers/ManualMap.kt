package com.thompsonfabco.filamentkit.ui.printers

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.ManualMapState
import com.thompsonfabco.filamentkit.net.ManualOfferAnswer
import com.thompsonfabco.filamentkit.net.ManualPosition
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

/** The manual-map calls; [ApiManualMapBackend] adapts the Api, tests pass a fake. */
interface ManualMapBackend {
    suspend fun start(id: String): ManualMapState
    suspend fun state(id: String): ManualMapState
    suspend fun confirm(id: String, session: String, position: String, reported: JsonObject, nozzle: String?,
                        byHand: Boolean): ManualMapState
    suspend fun skip(id: String, session: String, position: String): ManualMapState
    suspend fun stop(id: String, session: String): ManualMapState
    suspend fun offer(id: String, share: Boolean): ManualOfferAnswer
}

class ApiManualMapBackend(private val api: Api) : ManualMapBackend {
    override suspend fun start(id: String) = api.manualStart(id)
    override suspend fun state(id: String) = api.manualState(id)
    override suspend fun confirm(id: String, session: String, position: String, reported: JsonObject, nozzle: String?,
                                 byHand: Boolean) = api.manualConfirm(id, session, position, reported, nozzle, byHand)
    override suspend fun skip(id: String, session: String, position: String) = api.manualSkip(id, session, position)
    override suspend fun stop(id: String, session: String) = api.manualStop(id, session)
    override suspend fun offer(id: String, share: Boolean) = api.manualOffer(id, share)
}

/** Texts of "Map by loading filament"; the step's instruction and question are the server's own sentences. */
object ManualMapHelp {
    const val TITLE = "Map by loading filament"
    const val OFFER_LINE = "Or map the slots yourself, one at a time, by loading filament."
    const val STARTING = "Starting…"
    const val WAITING = "Waiting for the printer to show the load…"
    const val SETTLING = "The printer shows a change. Waiting a few seconds for it to settle…"
    const val WHICH_NOZZLE = "Which nozzle did you load it to?"
    const val PICK_OTHER = "Which one did you load?"
    const val BY_HAND = "Which slot is it in?"
    const val BY_HAND_NOTE = "Saved as you say: the printer can't check it."
    const val STOP_TITLE = "Stop mapping?"
    const val STOP_TEXT = "What you answered so far is kept. Slots you haven't answered stay unmapped."
    const val OFFER_QUESTION = "Share this map in a printer report, so other owners of this model benefit? " +
        "Nothing is sent unless you choose to."

    /** "A1: confirmed (A1, left nozzle)", the setup page's list line; [open] false: an unanswered one is not mapped. */
    fun line(p: ManualPosition, open: Boolean = true): String = "${p.label}: " + when (p.status) {
        "confirmed" -> "confirmed (" + listOfNotNull(p.reportedLabel, p.nozzle?.let { "$it nozzle" }).joinToString(", ") + ")"
        "by_hand" -> "entered by hand (${p.reportedLabel ?: "?"})"
        "skipped" -> "skipped"
        else -> if (open) "not answered yet" else "not mapped"
    }

    fun nozzleLabel(n: String): String = if (n == "left") "Left nozzle" else "Right nozzle"

    /** The kit API's errors here are the server's sentences; only the transport ones get the app's words. */
    fun message(e: ApiError): String = when (e.code) {
        "offline", "local_network", "cert_changed" -> PrinterHelp.message(e)
        else -> e.message.ifBlank { PrinterHelp.message(e) }
    }
}

data class ManualUiState(
    val map: ManualMapState? = null,
    val busy: Boolean = false,
    val message: String? = null,
    /** The answer to the share question, shown once. */
    val note: String? = null,
    /** The owner's nozzle choice for the load shown (dual-nozzle printers that don't report it). */
    val nozzle: String? = null,
    /** "No, I loaded …" is open: the list of positions to pick from. */
    val pickingOther: Boolean = false,
    val confirmStop: Boolean = false,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
) {
    val open: Boolean get() = map?.open == true

    /** The nozzle the printer reported, else the owner's choice, else null (single nozzle). */
    fun nozzleToSend(): String? {
        val m = map ?: return null
        val seen = m.step?.seen
        if (seen?.nozzleReported == true) return seen.nozzle
        return if (m.dualNozzle) nozzle else null
    }

    /** Yes and "No, I loaded" need a settled load, and on a dual-nozzle printer a nozzle. */
    val canAnswer: Boolean get() {
        val m = map ?: return false
        val seen = m.step?.seen ?: return false
        if (busy || !seen.settled || m.step.ask == null) return false
        return !m.dualNozzle || seen.nozzleReported || nozzle != null
    }

    /** The printer reports no loads: the owner picks the slot by hand. */
    val byHand: Boolean get() = map?.let { it.open && it.step != null && !it.reportsLoads } == true
}

/**
 * One manual-map session for printer [id]: [start] (screen visible) opens it or joins the open one, then polls every
 * [pollMs] while it is open and the screen is visible. A 409 `stale` means another device answered first: the state is
 * fetched again and nothing is shown.
 */
class ManualMapViewModel(
    private val backend: ManualMapBackend,
    private val id: String,
    private val pollMs: Long = 2000,
) : ViewModel() {
    private val _state = MutableStateFlow(ManualUiState())
    val state: StateFlow<ManualUiState> = _state.asStateFlow()

    private var poll: Job? = null
    private var visible = false
    private var started = false

    fun start() {
        visible = true
        if (!started) {
            started = true
            viewModelScope.launch {
                _state.update { it.copy(busy = true) }
                val ok = guard { set(backend.start(id)) }
                _state.update { it.copy(busy = false) }
                if (ok) follow() else started = false
            }
        } else follow()
    }

    fun stop() {
        visible = false
        poll?.cancel()
        poll = null
    }

    /** Try again after a failed start. */
    fun retry() {
        if (started || _state.value.busy) return
        start()
    }

    private fun set(m: ManualMapState) = _state.update { s ->
        val sameStep = s.map?.step?.position?.id == m.step?.position?.id && s.map?.session == m.session
        s.copy(map = m, nozzle = if (sameStep) s.nozzle else null, pickingOther = s.pickingOther && sameStep)
    }

    private fun follow() {
        if (!visible || poll?.isActive == true || !_state.value.open) return
        poll = viewModelScope.launch {
            var failures = 0
            while (visible && _state.value.open) {
                delay(if (failures == 0) pollMs else minOf(pollMs shl minOf(failures, 4), MAX_BACKOFF_MS))
                if (_state.value.busy) continue        // an answer is under way; its reply is the newer state
                val ok = guard(quiet = true) { set(backend.state(id)) }
                val s = _state.value
                if (s.unauthorized || s.mismatch != null) break
                failures = if (ok) 0 else failures + 1
            }
        }
    }

    fun chooseNozzle(n: String) = _state.update { it.copy(nozzle = n) }

    fun yes() {
        val m = _state.value.map ?: return
        val step = m.step ?: return
        val seen = step.seen ?: return
        if (!_state.value.canAnswer) return
        send { backend.confirm(id, m.session, step.position.id, seen.reported, _state.value.nozzleToSend(), false) }
    }

    fun openOther() = _state.update { it.copy(pickingOther = true) }

    fun closeOther() = _state.update { it.copy(pickingOther = false) }

    /** "No, I loaded [position]": the load the printer shows is recorded for the position the owner names. */
    fun loadedOther(position: String) {
        val m = _state.value.map ?: return
        val seen = m.step?.seen ?: return
        if (!_state.value.canAnswer) return
        _state.update { it.copy(pickingOther = false) }
        send { backend.confirm(id, m.session, position, seen.reported, _state.value.nozzleToSend(), false) }
    }

    /** By hand: the printer reports nothing, so the owner's pick is saved unverified. */
    fun pickByHand(choice: Int) {
        val m = _state.value.map ?: return
        val step = m.step ?: return
        val c = m.choices.getOrNull(choice) ?: return
        if (_state.value.busy) return
        send { backend.confirm(id, m.session, step.position.id, c.reported, null, true) }
    }

    fun skip() {
        val m = _state.value.map ?: return
        val step = m.step ?: return
        if (_state.value.busy) return
        send { backend.skip(id, m.session, step.position.id) }
    }

    fun askStop() = _state.update { it.copy(confirmStop = true) }

    fun cancelStop() = _state.update { it.copy(confirmStop = false) }

    fun confirmStop() {
        val m = _state.value.map ?: return
        _state.update { it.copy(confirmStop = false) }
        if (!m.open) return
        send { backend.stop(id, m.session) }
    }

    fun offer(share: Boolean) {
        if (_state.value.busy) return
        viewModelScope.launch {
            _state.update { it.copy(busy = true, message = null) }
            guard {
                val r = backend.offer(id, share)
                _state.update { s -> s.copy(note = r.message, map = s.map?.copy(offerReport = false)) }
            }
            _state.update { it.copy(busy = false) }
        }
    }

    private fun send(call: suspend () -> ManualMapState) {
        if (_state.value.busy) return
        viewModelScope.launch {
            _state.update { it.copy(busy = true, message = null) }
            guard { set(call()) }
            _state.update { it.copy(busy = false) }
            follow()
        }
    }

    /**
     * False after an error. A 409 `stale` refetches the state instead of showing anything; [quiet] (a poll) keeps a
     * network blip off the screen, but still stops on an unpaired phone or a changed certificate.
     */
    private suspend fun guard(quiet: Boolean = false, block: suspend () -> Unit): Boolean {
        try {
            block()
            if (quiet && _state.value.message == POLL_FAILED) _state.update { it.copy(message = null) }
            return true
        } catch (e: CancellationException) {
            throw e
        } catch (e: FingerprintMismatch) {
            _state.update { it.copy(mismatch = e.expected to e.actual) }
        } catch (e: ApiError) {
            when {
                e.code == "unauthorized" -> _state.update { it.copy(unauthorized = true) }
                e.code == "stale" -> runCatching { set(backend.state(id)) }
                // the session was closed elsewhere (or the server restarted): show it as ended
                e.code == "none" -> _state.update { s -> s.copy(map = s.map?.copy(open = false, step = null)) }
                quiet -> _state.update { it.copy(message = POLL_FAILED) }
                else -> _state.update { it.copy(message = ManualMapHelp.message(e)) }
            }
        } catch (e: Exception) {
            _state.update { it.copy(message = if (quiet) POLL_FAILED else PrinterHelp.UNEXPECTED) }
        }
        return false
    }

    companion object {
        const val POLL_FAILED = "Lost touch with the server for a moment; still trying…"
        private const val MAX_BACKOFF_MS = 30_000L
    }
}
