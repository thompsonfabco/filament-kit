package com.thompsonfabco.filamentkit.ui.printers

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.CommandResult
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.net.PrinterStatus
import com.thompsonfabco.filamentkit.net.PrinterSummary
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull

/** The printer calls the view models need; [ApiPrinterBackend] adapts [Api], tests pass a fake. */
interface PrinterBackend {
    suspend fun printers(): List<Printer>
    suspend fun addPrinter(serial: String, accessCode: String, name: String?): Printer
    suspend fun printer(id: String): PrinterDetail
    suspend fun command(id: String, action: String): CommandResult
}

class ApiPrinterBackend(private val api: Api) : PrinterBackend, PrinterToolsBackend {
    override suspend fun printers() = api.printers()
    override suspend fun addPrinter(serial: String, accessCode: String, name: String?) = api.addPrinter(serial, accessCode, name)
    override suspend fun printer(id: String) = api.printer(id)
    override suspend fun command(id: String, action: String) = api.command(id, action)
    override suspend fun startMap(id: String) = api.startMap(id)
    override suspend fun mapStatus(id: String) = api.mapStatus(id)
    override suspend fun usage(id: String, days: Int) = api.usage(id, days)
    override suspend fun undoUsage(entryId: String) = api.undoUsage(entryId)
}

/** Plain-English texts for printer states and errors. */
object PrinterHelp {
    const val ACCESS_CODE_HELP = "On the printer: Settings → Network/LAN → Access Code"

    fun stateLabel(state: String): String = when (state) {
        "connected" -> "Connected"
        "offline" -> "Offline"
        "wrong_code" -> "Wrong Access Code"
        "needs_developer_mode" -> "Needs Developer Mode"
        "cert_changed" -> "Certificate changed"
        "not_configured" -> "Not set up"
        else -> state
    }

    /**
     * Deliberately does not push the user to re-add: re-adding while an impostor holds the printer's address would
     * trust the impostor's certificate.
     */
    const val CERT_CHANGED = "The printer's certificate changed. This usually clears by itself when the printer comes " +
        "back at its usual address. Add it again with its Access Code only if you expected this (factory reset or a " +
        "new mainboard)."

    /** What the user should do about [state], or null when nothing is wrong. */
    fun fix(state: String): String? = when (state) {
        "wrong_code" -> "The printer did not accept the Access Code. On the printer open Settings → Network/LAN → " +
            "Access Code, then tap the printer in the Printers list and enter that code again."
        "needs_developer_mode" -> "The printer refuses remote control. On the printer open Settings → Network/LAN, " +
            "turn on LAN Only mode and then Developer Mode, then try again."
        "offline" -> "The server cannot reach the printer. Check that the printer is turned on and connected to " +
            "the same network."
        "not_configured" -> "This printer is not set up yet. Tap it and enter its Access Code."
        "cert_changed" -> CERT_CHANGED
        else -> null
    }

    fun cameraFix(code: String): String = when (code) {
        "camera_unavailable" -> "The camera did not start. Check that the printer is on and that LAN Mode Liveview " +
            "is turned on in the printer's network settings (Settings → Network/LAN)."
        "not_configured" -> "Set up this printer first: enter its Access Code on the Printers screen."
        "not_found" -> "The server has no camera view for this printer."
        "unauthorized" -> "This phone is no longer paired with the server."
        else -> "The camera could not be shown right now. Leave this screen and come back to try again."
    }

    fun message(e: ApiError): String = when (e.code) {
        "offline" -> "Could not reach the server. Check that you are on the same network."
        "printer_offline" -> "The printer is offline. Check that it is turned on and on the network."
        "no_reply" -> "The printer did not answer in time. Try again."
        "not_found" -> "The server does not know this printer."
        "exists" -> "This printer is already set up."
        "printer_busy" -> "The printer is printing. Try again when it's idle."
        "cert_changed" -> CERT_CHANGED
        "needs_developer_mode" -> fix("needs_developer_mode")!!
        "no_preset" -> "No preset for this filament on this printer yet — profiles come next"
        "write_refused" -> "The printer refused the change"
        "already_running" -> "Slot mapping is already running."
        "too_old" -> "Older than 7 days, can't undo"
        "already_undone" -> "This one was already undone."
        "nothing_to_undo" -> "Nothing was taken off a spool for this one"
        else -> e.message
    }

    /** Errors of a slot or usage action: a 404 names what is missing (printer, slot, spool or entry) in its own words. */
    fun actionMessage(e: ApiError): String = if (e.code == "not_found") e.message else message(e)

    /** Errors of "Add printer": a 404 means the server has not seen that printer on the network yet (its own words). */
    fun addMessage(e: ApiError): String = if (e.code == "not_found") e.message else message(e)

    const val UNEXPECTED = "Unexpected response from the server"

    /** gcode_state values during which a print is under way (the server's `status.ACTIVE`). */
    private val PRINTING = setOf("RUNNING", "PAUSE", "PREPARE", "SLICING")

    fun isPrinting(gcodeState: String): Boolean = gcodeState in PRINTING

    /** The list line while printing: "job · percent · time left" (", paused" when paused); null when idle. */
    fun jobLine(s: PrinterSummary?): String? {
        if (s == null) return null
        if (!isPrinting(s.gcodeState)) return null
        return listOfNotNull(
            s.job?.ifBlank { null },
            "${s.percent}%",
            if (s.remainingMin > 0) "${formatMinutes(s.remainingMin)} left" else null,
            if (s.gcodeState == "PAUSE") "paused" else null,
        ).joinToString(" · ")
    }

    fun formatMinutes(min: Int): String = if (min >= 60) "${min / 60} h ${min % 60} min" else "$min min"
}

enum class StopStep { None, First, Second }

data class PrinterUiState(
    val printer: Printer? = null,
    val status: PrinterStatus? = null,
    /** A problem fetching the status (polling continues). */
    val message: String? = null,
    val commandBusy: Boolean = false,
    /** The printer's reply to the last command, or why it failed. */
    val commandMessage: String? = null,
    val stopStep: StopStep = StopStep.None,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
) {
    val paused: Boolean get() = status?.gcodeState == "PAUSE"
    val printing: Boolean get() = status?.let { PrinterHelp.isPrinting(it.gcodeState) } == true
    val lightOn: Boolean get() = status?.light == "on"

    /** Commands are offered only to a connected printer, one at a time. */
    val controlsEnabled: Boolean get() = printer?.state == "connected" && !commandBusy

    /** The second Stop question, naming the printer and the job. */
    val stopQuestion: String?
        get() = if (stopStep != StopStep.Second) null else {
            val name = printer?.name ?: "this printer"
            val job = status?.job?.ifBlank { null }
            if (job != null) "Really stop \"$job\" on $name? The print cannot be resumed."
            else "Really stop the print on $name? It cannot be resumed."
        }
}

/**
 * One printer's live status and controls. Polls every [pollMs] between [start] and [stop] (the screen calls them
 * when it becomes visible / leaves), so nothing runs in the background.
 */
class PrinterViewModel(
    private val backend: PrinterBackend,
    private val id: String,
    private val pollMs: Long = 2000,
) : ViewModel() {
    private val _state = MutableStateFlow(PrinterUiState())
    val state: StateFlow<PrinterUiState> = _state.asStateFlow()

    private var poll: Job? = null

    fun start() {
        if (poll?.isActive == true) return
        poll = viewModelScope.launch {
            while (isActive) {
                if (!refresh()) break
                delay(pollMs)
            }
        }
    }

    fun stop() {
        poll?.cancel()
        poll = null
    }

    /** One fetch; false when polling must stop (unpaired or certificate changed). */
    private suspend fun refresh(): Boolean = guard(onError = { msg -> _state.update { it.copy(message = msg) } }) {
        val d = backend.printer(id)
        _state.update { it.copy(printer = d.printer, status = d.status, message = null) }
    }

    fun pauseOrResume() = send(if (_state.value.paused) "resume" else "pause")

    fun toggleLight() = send(if (_state.value.lightOn) "light_off" else "light_on")

    fun askStop() = _state.update { it.copy(stopStep = StopStep.First) }

    fun cancelStop() = _state.update { it.copy(stopStep = StopStep.None) }

    /** First confirm asks again (naming printer and job); the second sends `stop`. */
    fun confirmStop() {
        when (_state.value.stopStep) {
            StopStep.None -> Unit
            StopStep.First -> _state.update { it.copy(stopStep = StopStep.Second) }
            StopStep.Second -> {
                _state.update { it.copy(stopStep = StopStep.None) }
                send("stop")
            }
        }
    }

    fun dismissCommandMessage() = _state.update { it.copy(commandMessage = null) }

    private fun send(action: String) {
        if (_state.value.commandBusy) return
        _state.update { it.copy(commandBusy = true, commandMessage = null) }
        viewModelScope.launch {
            guard(onError = { msg -> _state.update { it.copy(commandMessage = msg) } }) {
                val r = backend.command(id, action)
                _state.update { it.copy(commandMessage = describe(action, r)) }
            }
            _state.update { it.copy(commandBusy = false) }
        }
    }

    private suspend fun guard(onError: (String) -> Unit, block: suspend () -> Unit): Boolean {
        try {
            block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: FingerprintMismatch) {
            _state.update { it.copy(mismatch = e.expected to e.actual) }
            stop()
            return false
        } catch (e: ApiError) {
            if (e.code == "unauthorized") {
                _state.update { it.copy(unauthorized = true) }
                stop()
                return false
            }
            onError(PrinterHelp.message(e))
        } catch (e: Exception) {
            onError(PrinterHelp.UNEXPECTED)
        }
        return true
    }

    companion object {
        private val DONE = mapOf(
            "pause" to "Pause", "resume" to "Resume", "stop" to "Stop", "light_on" to "Light on", "light_off" to "Light off",
        )

        /**
         * The server's command reply is `{ok, reply: {ok, reply: <printer's answer>}}`; the printer's answer carries
         * `result` (e.g. `success`) and, when refused, `reason`.
         */
        fun describe(action: String, r: CommandResult): String {
            val outer = r.reply as? JsonObject
            val ok = (outer?.get("ok") as? JsonPrimitive)?.booleanOrNull ?: r.ok
            val answer = outer?.get("reply") as? JsonObject ?: outer
            fun text(key: String) = (answer?.get(key) as? JsonPrimitive)?.contentOrNull?.ifBlank { null }
            val result = text("result")
            val label = DONE[action] ?: action
            return if (ok) "$label: the printer replied \"${result ?: "ok"}\"."
            else "$label: the printer refused (${text("reason") ?: result ?: "no reason given"})."
        }
    }
}

data class AddDialog(
    val serial: String,
    val name: String,
    val busy: Boolean = false,
    val error: String? = null,
)

data class PrintersUiState(
    val printers: List<Printer> = emptyList(),
    val loading: Boolean = false,
    val message: String? = null,
    val dialog: AddDialog? = null,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
)

/** The printers list and the "Add printer" dialog. The Access Code is only passed through, never kept. */
class PrintersViewModel(private val backend: PrinterBackend) : ViewModel() {
    private val _state = MutableStateFlow(PrintersUiState())
    val state: StateFlow<PrintersUiState> = _state.asStateFlow()

    fun refresh() {
        _state.update { it.copy(loading = true) }
        viewModelScope.launch { load() }
    }

    private suspend fun load() {
        guard(onError = { msg -> _state.update { it.copy(message = msg) } }) {
            val list = backend.printers()
            _state.update { it.copy(printers = list, message = null) }
        }
        _state.update { it.copy(loading = false) }
    }

    fun openAdd(p: Printer) = _state.update {
        it.copy(dialog = AddDialog(serial = p.serial, name = if (p.name == p.serial) "" else p.name))
    }

    /** Closes the dialog and reloads, since the printer's state may have changed meanwhile. */
    fun cancelAdd() {
        _state.update { it.copy(dialog = null) }
        refresh()
    }

    fun submitAdd(accessCode: String, name: String) {
        val d = _state.value.dialog ?: return
        if (d.busy) return
        val code = accessCode.trim()
        if (code.isEmpty()) {
            _state.update { it.copy(dialog = d.copy(error = "Enter the Access Code. ${PrinterHelp.ACCESS_CODE_HELP}.")) }
            return
        }
        _state.update { it.copy(dialog = d.copy(name = name, busy = true, error = null)) }
        viewModelScope.launch {
            guard(
                onError = { msg -> _state.update { s -> s.copy(dialog = s.dialog?.copy(busy = false, error = msg)) } },
                describe = PrinterHelp::addMessage,
            ) {
                val p = backend.addPrinter(d.serial, code, name.trim().ifBlank { null })
                val problem = if (p.state == "connected") null else PrinterHelp.fix(p.state)
                if (problem == null) {
                    _state.update { it.copy(dialog = null) }
                    load()
                } else {
                    _state.update { s -> s.copy(dialog = s.dialog?.copy(busy = false, error = problem)) }
                }
            }
        }
    }

    private suspend fun guard(
        onError: (String) -> Unit,
        describe: (ApiError) -> String = PrinterHelp::message,
        block: suspend () -> Unit,
    ) {
        try {
            block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: FingerprintMismatch) {
            _state.update { it.copy(mismatch = e.expected to e.actual) }
        } catch (e: ApiError) {
            if (e.code == "unauthorized") _state.update { it.copy(unauthorized = true) } else onError(describe(e))
        } catch (e: Exception) {
            onError(PrinterHelp.UNEXPECTED)
        }
    }
}
