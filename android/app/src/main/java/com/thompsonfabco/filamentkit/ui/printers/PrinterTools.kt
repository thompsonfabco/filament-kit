package com.thompsonfabco.filamentkit.ui.printers

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.MapStatus
import com.thompsonfabco.filamentkit.net.PrinterReport
import com.thompsonfabco.filamentkit.net.UsageEntry
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Slot mapping and filament-used calls; [ApiPrinterBackend] adapts the Api, tests pass a fake. */
interface PrinterToolsBackend {
    suspend fun startMap(id: String): String
    suspend fun mapStatus(id: String): MapStatus
    suspend fun report(id: String): PrinterReport
    suspend fun usage(id: String, days: Int): List<UsageEntry>
    suspend fun undoUsage(entryId: String): UsageEntry
}

/** "Collect a report": what asks for one, and the file name the report is shared under. */
object ReportHelp {
    /** The server's own sentence for why a report would help; null when it gave none. */
    fun why(m: MapStatus?): String? = m?.reportWhy?.ifBlank { null }

    /** The Hub says a report would help: the button is the main one (when nothing before it in 05 9.7 is). */
    fun wanted(m: MapStatus?): Boolean = m?.reportWanted != null

    /**
     * The server's name reduced to one plain file name (no folder part, only letters, digits, `.`, `_`, `-`), so it
     * cannot point outside the app's report folder; ends in `.xml`.
     */
    fun fileName(server: String): String {
        val base = server.substringAfterLast('/').substringAfterLast('\\')
            .replace(Regex("[^A-Za-z0-9._-]"), "_").trimStart('.').take(96)
        val name = base.ifBlank { "printer-report.xml" }
        return if (name.endsWith(".xml", ignoreCase = true)) name else "$name.xml"
    }
}

/** Rules for the "Filament used" list. */
object UsageHelp {
    /** Only a real deduction can be undone: not logged-only, not failed, not already undone. */
    fun canUndo(e: UsageEntry): Boolean = !e.observe && !e.undone && e.error == null && e.grams != null && e.spoolId != null

    /** "12.4 g · benchy.3mf · A2": a part the Hub does not give reads as a dash. */
    fun headline(e: UsageEntry): Say = Say.Words(
        R.string.printer_usage_headline,
        listOf(grams(e.grams), e.job?.ifBlank { null } ?: DASH, e.slot?.ifBlank { null } ?: DASH),
    )

    private const val DASH = "–"
}

data class ToolsUiState(
    val map: MapStatus? = null,
    /** The "Map slots" question is open; it stays open while the start request is out. */
    val confirmMap: Boolean = false,
    val mapBusy: Boolean = false,
    val mapProblem: Problem? = null,
    val usage: List<UsageEntry> = emptyList(),
    val usageLoaded: Boolean = false,
    val usageProblem: Problem? = null,
    /** The line after an undo: "12.4 g put back on spool 214." */
    val undoneNote: Say? = null,
    /** The entry the "Put it back on the spool?" question asks about; it stays open while the undo is being written. */
    val undoTarget: UsageEntry? = null,
    val undoBusy: Boolean = false,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
    val reportBusy: Boolean = false,
    /** A report fetched and not handed to the share sheet yet ([PrinterToolsViewModel.reportShown] clears it). */
    val report: PrinterReport? = null,
    val reportProblem: Say? = null,
) {
    val mapRunning: Boolean get() = map?.state == "running"

    /** Greyed only by the printer ([canStart]) or a job under way or being started, never by a past result. */
    fun mapEnabled(canStart: Boolean): Boolean = canStart && !mapRunning && !mapBusy
}

/**
 * "Map slots" and "Filament used" for one printer. [start] (screen visible) loads both and follows a running map
 * job; the job is polled every [pollMs] only while it is `running` and the screen is visible ([stop] ends it). Every
 * request goes to the session's client of that moment; a Hub notice is cleared by the next request that succeeds.
 */
class PrinterToolsViewModel(
    private val backend: PrinterToolsBackend,
    private val id: String,
    private val pollMs: Long = 2000,
) : ViewModel() {
    private val _state = MutableStateFlow(ToolsUiState())
    val state: StateFlow<ToolsUiState> = _state.asStateFlow()

    /** Runs after any request succeeded, so the screen's other view models drop their Hub notice too. */
    var onHubOk: () -> Unit = {}

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

    /** The Hub notice goes away; the next request puts it back if the problem is still there. */
    fun clearHubNotice() = _state.update { it.copy(unauthorized = false, mismatch = null) }

    // --- map slots ---

    fun askMap() = _state.update { it.copy(confirmMap = true, mapProblem = null) }

    /** The question cannot be left while the start request is out: the job may already be starting. */
    fun cancelMap() = _state.update { if (it.mapBusy) it else it.copy(confirmMap = false) }

    fun confirmMap() {
        if (_state.value.mapBusy) return
        _state.update { it.copy(mapBusy = true, mapProblem = null) }
        // an older poll still in flight would report the state from before this job (and then stop polling)
        generation++
        poll?.cancel()
        poll = null
        viewModelScope.launch {
            var started = false
            guard(onError = { p -> _state.update { it.copy(mapProblem = p) } }) {
                try {
                    backend.startMap(id)
                } catch (e: ApiError) {
                    if (e.code != "already_running") throw e // one is under way: follow it
                }
                started = true
            }
            _state.update { it.copy(mapBusy = false, confirmMap = false) }
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
            var pollError: Problem? = null
            while (true) {
                var keep = false
                var stale = false
                val ok = guard(onError = { p ->
                    if (mine == generation) {
                        pollError = p
                        _state.update { it.copy(mapProblem = p) }
                    }
                }) {
                    val m = backend.mapStatus(id)
                    if (mine != generation) {
                        stale = true
                        return@guard
                    }
                    _state.update { s ->
                        // clear only a problem this loop's own failure put there
                        s.copy(map = m, mapProblem = if (pollError != null && s.mapProblem == pollError) null else s.mapProblem)
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

    // --- printer report ---

    /** Asks the server for a report; the screen offers it through the share sheet, then calls [reportShown]. */
    fun collectReport() {
        if (_state.value.reportBusy) return
        _state.update { it.copy(reportBusy = true, reportProblem = null, report = null) }
        viewModelScope.launch {
            guard(onError = { p -> _state.update { it.copy(reportProblem = p.say()) } }) {
                val r = backend.report(id)
                _state.update { it.copy(report = r) }
            }
            _state.update { it.copy(reportBusy = false) }
        }
    }

    /** The share sheet was opened ([problem] null) or could not be ([problem] says why). */
    fun reportShown(problem: Say? = null) = _state.update { it.copy(report = null, reportProblem = problem) }

    // --- filament used ---

    fun refreshUsage() {
        viewModelScope.launch { loadUsage() }
    }

    private suspend fun loadUsage() {
        guard(onError = { p -> _state.update { it.copy(usageProblem = p) } }) {
            val list = backend.usage(id, DAYS)
            _state.update { it.copy(usage = list, usageLoaded = true, usageProblem = null) }
        }
    }

    fun askUndo(entry: UsageEntry) {
        if (!UsageHelp.canUndo(entry)) return
        _state.update { it.copy(undoTarget = entry, undoneNote = null, usageProblem = null) }
    }

    /** The question cannot be left while the undo is being written. */
    fun cancelUndo() = _state.update { if (it.undoBusy) it else it.copy(undoTarget = null) }

    fun confirmUndo() {
        val target = _state.value.undoTarget ?: return
        if (_state.value.undoBusy) return
        _state.update { it.copy(undoBusy = true) }
        viewModelScope.launch {
            val ok = guard(onError = { p -> _state.update { it.copy(usageProblem = p) } }) {
                backend.undoUsage(target.id)
                _state.update {
                    it.copy(undoneNote = Say.Words(R.string.printer_usage_undone, listOf(grams(target.grams), target.spoolId ?: "?")))
                }
            }
            _state.update { it.copy(undoBusy = false, undoTarget = null) }
            if (ok) loadUsage()
        }
    }

    /** False after an error (shown through [onError]) or when the phone was unpaired / the certificate changed. */
    private suspend fun guard(onError: (Problem) -> Unit, block: suspend () -> Unit): Boolean {
        try {
            block()
            if (_state.value.unauthorized || _state.value.mismatch != null) clearHubNotice()
            onHubOk()
            return true
        } catch (e: CancellationException) {
            throw e
        } catch (e: FingerprintMismatch) {
            _state.update { it.copy(mismatch = e.expected to e.actual) }
        } catch (e: ApiError) {
            if (e.code == "unauthorized") _state.update { it.copy(unauthorized = true) } else onError(printerProblem(e))
        } catch (e: Exception) {
            onError(UNREADABLE)
        }
        return false
    }

    private companion object {
        const val DAYS = 7
        const val MAX_BACKOFF_MS = 30_000L
    }
}
