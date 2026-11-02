package com.thompsonfabco.filamentkit.ui.printers

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.MapStatus
import com.thompsonfabco.filamentkit.net.UsageEntry
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.Locale

/** Slot mapping and filament-used calls; [ApiPrinterBackend] adapts the Api, tests pass a fake. */
interface PrinterToolsBackend {
    suspend fun startMap(id: String): String
    suspend fun mapStatus(id: String): MapStatus
    suspend fun usage(id: String, days: Int): List<UsageEntry>
    suspend fun undoUsage(entryId: String): UsageEntry
}

/** Texts for the "Filament used" list. */
object UsageHelp {
    const val OBSERVE_NOTICE = "Filament use is only being logged for this printer until slot mapping succeeds"

    /** Only a real deduction can be undone: not logged-only, not failed, not already undone. */
    fun canUndo(e: UsageEntry): Boolean = !e.observe && !e.undone && e.error == null && e.grams != null && e.spoolId != null

    /** "12.5 g · Benchy · A1". */
    fun line(e: UsageEntry): String = listOfNotNull(
        e.grams?.let { String.format(Locale.ROOT, "%.1f g", it) } ?: "? g",
        e.job?.ifBlank { null },
        e.slot?.ifBlank { null },
    ).joinToString(" · ")

    /** The entry's status, or null for a plain deduction. */
    fun note(e: UsageEntry): String? = when {
        e.undone -> "undone"
        e.error != null -> reason(e.error)
        e.observe -> "logged only"
        e.spoolId == null -> "no spool in that slot, nothing taken off"
        else -> null
    }

    /** The server's codes (route-contract addendum); an unknown one still gets a readable line. */
    private fun reason(code: String): String = "not taken off a spool: " + when (code) {
        "file_not_found" -> "print file not found on the printer"
        "no_slice_info" -> "the print file has no filament amounts"
        "plate_not_found" -> "the printed plate was not in the print file"
        "printer_unreachable" -> "the printer could not be reached"
        "cert_changed" -> "the printer's certificate changed"
        "spoolman_unreachable" -> "the inventory could not be reached"
        "spoolman_failed" -> "the inventory refused the change"
        "ambiguous_spool" -> "two spools are set to that slot"
        "no_mapping" -> "the printer didn't say which slots it used"
        "unmapped_slot" -> "that slot isn't in the slot map — run Map slots"
        else -> code.replace('_', ' ')
    }
}

data class ToolsUiState(
    val map: MapStatus? = null,
    /** The "Map slots" confirm dialog is open. */
    val confirmMap: Boolean = false,
    val mapBusy: Boolean = false,
    val mapMessage: String? = null,
    val usage: List<UsageEntry> = emptyList(),
    val usageLoaded: Boolean = false,
    val usageMessage: String? = null,
    /** The entry the Undo confirm dialog asks about. */
    val undoTarget: UsageEntry? = null,
    val undoBusy: Boolean = false,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
) {
    val mapRunning: Boolean get() = map?.state == "running"
    val observeNotice: String? get() = if (map?.observe == true) UsageHelp.OBSERVE_NOTICE else null
}

/**
 * "Map slots" and "Filament used" for one printer. [start] (screen visible) loads both and follows a running map
 * job; the job is polled every [pollMs] only while it is `running` and the screen is visible ([stop] ends it).
 */
class PrinterToolsViewModel(
    private val backend: PrinterToolsBackend,
    private val id: String,
    private val pollMs: Long = 2000,
) : ViewModel() {
    private val _state = MutableStateFlow(ToolsUiState())
    val state: StateFlow<ToolsUiState> = _state.asStateFlow()

    private var poll: Job? = null
    private var visible = false
    /** Bumped when a map job is started: a poll begun before that (e.g. the screen's first one) never writes state. */
    private var generation = 0

    fun start() {
        visible = true
        viewModelScope.launch { loadUsage() }
        follow()
    }

    fun stop() {
        visible = false
        poll?.cancel()
        poll = null
    }

    // --- map slots ---

    fun askMap() = _state.update { it.copy(confirmMap = true, mapMessage = null) }

    fun cancelMap() = _state.update { it.copy(confirmMap = false) }

    fun confirmMap() {
        if (_state.value.mapBusy) return
        _state.update { it.copy(confirmMap = false, mapBusy = true, mapMessage = null) }
        // an older poll still in flight would report the state from before this job (and then stop polling)
        generation++
        poll?.cancel()
        poll = null
        viewModelScope.launch {
            var started = false
            guard(onError = { msg -> _state.update { it.copy(mapMessage = msg) } }) {
                try {
                    backend.startMap(id)
                } catch (e: ApiError) {
                    if (e.code != "already_running") throw e // one is under way: follow it
                }
                started = true
            }
            _state.update { it.copy(mapBusy = false) }
            if (started) follow(force = true)
        }
    }

    /**
     * Fetches the map state; keeps polling while it is running and the screen is visible. A failed fetch (network
     * blip) is retried with a doubling wait capped at [MAX_BACKOFF_MS], so a short outage mid-job does not leave the
     * screen stuck on "running"; an unpaired phone or a changed server certificate stops it. [start] re-arms it.
     * [force] (after starting a job) replaces any poll already running, and that older poll's answer is dropped.
     */
    private fun follow(force: Boolean = false) {
        if (!visible && !force) return
        if (force) {      // a job was just started: whatever poll runs now began before it
            generation++
            poll?.cancel()
        } else if (poll?.isActive == true) return
        val mine = generation
        poll = viewModelScope.launch {
            var failures = 0
            var pollError: String? = null
            while (true) {
                var keep = false
                var stale = false
                val ok = guard(onError = { msg ->
                    if (mine == generation) {
                        pollError = msg
                        _state.update { it.copy(mapMessage = msg) }
                    }
                }) {
                    val m = backend.mapStatus(id)
                    if (mine != generation) {
                        stale = true
                        return@guard
                    }
                    _state.update { s ->
                        // clear only a message this loop's own failure put there
                        s.copy(map = m, mapMessage = if (pollError != null && s.mapMessage == pollError) null else s.mapMessage)
                    }
                    pollError = null
                    keep = m.state == "running"
                }
                val s = _state.value
                if (stale || mine != generation || s.unauthorized || s.mismatch != null || !visible) break
                if (ok) {
                    if (!keep) break
                    failures = 0
                    delay(pollMs)
                } else {
                    failures++
                    delay(minOf(pollMs shl minOf(failures, 10), MAX_BACKOFF_MS))
                }
            }
        }
    }

    // --- filament used ---

    fun refreshUsage() {
        viewModelScope.launch { loadUsage() }
    }

    private suspend fun loadUsage() {
        guard(onError = { msg -> _state.update { it.copy(usageMessage = msg) } }) {
            val list = backend.usage(id, DAYS)
            _state.update { it.copy(usage = list, usageLoaded = true) }
        }
    }

    fun askUndo(entry: UsageEntry) {
        if (!UsageHelp.canUndo(entry)) return
        _state.update { it.copy(undoTarget = entry, usageMessage = null) }
    }

    fun cancelUndo() = _state.update { it.copy(undoTarget = null) }

    fun confirmUndo() {
        val target = _state.value.undoTarget ?: return
        if (_state.value.undoBusy) return
        _state.update { it.copy(undoTarget = null, undoBusy = true) }
        viewModelScope.launch {
            val ok = guard(onError = { msg -> _state.update { it.copy(usageMessage = msg) } }) {
                backend.undoUsage(target.id)
                _state.update { it.copy(usageMessage = "Undone: ${UsageHelp.line(target)}") }
            }
            if (ok) loadUsage()
            _state.update { it.copy(undoBusy = false) }
        }
    }

    /** False after an error (shown through [onError]) or when the phone was unpaired / the certificate changed. */
    private suspend fun guard(onError: (String) -> Unit, block: suspend () -> Unit): Boolean {
        try {
            block()
            return true
        } catch (e: CancellationException) {
            throw e
        } catch (e: FingerprintMismatch) {
            _state.update { it.copy(mismatch = e.expected to e.actual) }
        } catch (e: ApiError) {
            if (e.code == "unauthorized") _state.update { it.copy(unauthorized = true) } else onError(PrinterHelp.actionMessage(e))
        } catch (e: Exception) {
            onError(PrinterHelp.UNEXPECTED)
        }
        return false
    }

    private companion object {
        const val DAYS = 7
        const val MAX_BACKOFF_MS = 30_000L
    }
}
