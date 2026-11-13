package com.thompsonfabco.filamentkit.ui.printers

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.KlipperFound
import com.thompsonfabco.filamentkit.net.Printer
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive

/**
 * Why a request of the Printers screen failed. The screen turns each into the catalogue's words (05-android-app 3.5);
 * [HubSaid] carries the Hub's own message, shown as given.
 */
sealed interface Problem {
    data object Unreachable : Problem
    data object Unexpected : Problem
    data class HubSaid(val text: String) : Problem

    /** The Hub's [module] (`klipper` or `bambu`) is switched off. */
    data class FeatureOff(val module: String) : Problem

    /** The printer was added but is in [state] (`wrong_code`, ...): the screen says what to do about it. */
    data class PrinterState(val state: String) : Problem

    /** The Hub no longer knows this phone, or its certificate changed: the screen shows the Hub notice (05-android-app 3.4). */
    data object NoLongerPaired : Problem
    data object CertificateChanged : Problem
}

/** The two Hub notices; a screen shows them as the notice, not as a text of its own. */
internal val Problem.isHubNotice: Boolean get() = this == Problem.NoLongerPaired || this == Problem.CertificateChanged

internal fun problemOf(e: ApiError): Problem = when (e.code) {
    "offline", "local_network" -> Problem.Unreachable
    "bad_response" -> Problem.Unexpected
    "module_off" -> Problem.FeatureOff(e.extra["module"]?.jsonPrimitive?.contentOrNull.orEmpty())
    else -> Problem.HubSaid(e.message)
}

/** One slot of a printer as the list's swatch row draws it. */
data class SlotLook(val hex: String, val empty: Boolean)

/** "Add Bambu Lab <model>": the form for a printer the Hub found. */
data class AddDialog(
    val serial: String,
    /** The model's name; null when the Hub does not know it. */
    val model: String?,
    /** The printer's name, for the re-key form's title. */
    val printerName: String,
    val name: String,
    /** The Access Code of a printer that is set up is entered again (it was refused), not a new printer added. */
    val rekey: Boolean = false,
    val busy: Boolean = false,
    val codeMissing: Boolean = false,
    val problem: Problem? = null,
)

/** The "Add a Klipper printer" form; the typed fields live in the form, only the outcome is kept here. */
data class KlipperDialog(
    val host: String = "",
    val port: Int = PrintersViewModel.DEFAULT_KLIPPER_PORT,
    val busy: Boolean = false,
    val addressMissing: Boolean = false,
    val portInvalid: Boolean = false,
    val problem: Problem? = null,
    /** The printer is added but its API key was refused: the form stays for the key only. */
    val createdId: String? = null,
    val createdName: String = "",
    val keyProblem: Problem? = null,
)

/** The "Find Klipper printers" sheet: [results] is null until a search has answered. */
data class FindSheet(
    val searching: Boolean = false,
    val results: List<KlipperFound>? = null,
    /** The network the results are for as typed; blank is the Hub's own. */
    val network: String = "",
    val problem: Problem? = null,
)

data class PrintersUiState(
    val printers: List<Printer> = emptyList(),
    val loaded: Boolean = false,
    val loading: Boolean = false,
    /** When the list on screen was loaded (epoch ms), for the offline notice. */
    val loadedAt: Long = 0,
    val problem: Problem? = null,
    val swatches: Map<String, List<SlotLook>> = emptyMap(),
    val dialog: AddDialog? = null,
    val klipper: KlipperDialog? = null,
    val find: FindSheet? = null,
    /** The name of a printer just added: the screen says so once. */
    val added: String? = null,

    /** The name of a printer whose Access Code was just replaced: the screen says so once. */
    val replaced: String? = null,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
) {
    /** Set up printers, in the Hub's order. */
    val configured: List<Printer> get() = printers.filter { it.configured }

    /** Printers the Hub sees that are not set up. */
    val found: List<Printer> get() = printers.filterNot { it.configured }
}

/** The printers list, the "Add" forms and the Klipper search. The Access Code and API key are only passed through. */
class PrintersViewModel(
    private val backend: PrinterBackend,
    private val now: () -> Long = System::currentTimeMillis,
) : ViewModel() {
    private val _state = MutableStateFlow(PrintersUiState())
    private var findJob: Job? = null
    private var settleJob: Job? = null
    val state: StateFlow<PrintersUiState> = _state.asStateFlow()

    fun refresh() {
        _state.update { it.copy(loading = true) }
        viewModelScope.launch { load() }
    }

    private suspend fun load() {
        guard(onError = { p -> if (!p.isHubNotice) _state.update { it.copy(problem = p) } }) {
            val list = backend.printers()
            _state.update {
                it.copy(printers = list, problem = null, loaded = true, loadedAt = now(), unauthorized = false, mismatch = null,
                    dialog = it.dialog?.let { d -> if (d.problem?.isHubNotice == true) d.copy(problem = null) else d },
                    klipper = it.klipper?.let { k -> if (k.problem?.isHubNotice == true) k.copy(problem = null) else k },
                    find = it.find?.let { f -> if (f.problem?.isHubNotice == true) f.copy(problem = null) else f },
                )
            }
            _state.update { it.copy(loading = false) }
            val looks = slotLooks(list)
            _state.update { it.copy(swatches = looks) }
        }
        _state.update { it.copy(loading = false) }
    }

    /** The slots of every connected printer, from each one's own screen data; a printer that does not answer has none. */
    private suspend fun slotLooks(list: List<Printer>): Map<String, List<SlotLook>> = coroutineScope {
        list.filter { it.configured && it.state == "connected" }.map { p ->
            async {
                try {
                    val slots = backend.printer(p.id).status?.ams.orEmpty().flatMap { it.slots }
                    p.id to slots.map { SlotLook(it.colorHex, PrinterHelp.slotEmpty(it)) }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: FingerprintMismatch) {
                    p.id to emptyList()
                } catch (e: Exception) {
                    p.id to emptyList()
                }
            }
        }.awaitAll().filter { it.second.isNotEmpty() }.toMap()
    }

    fun openAdd(p: Printer) = _state.update {
        it.copy(
            dialog = AddDialog(
                serial = p.serial, model = p.shownModel, printerName = p.name,
                name = if (p.name == p.serial) "" else p.name,
                rekey = p.configured,
            ),
        )
    }

    /** Closes the form and reloads, since the printer's state may have changed meanwhile. */
    fun cancelAdd() {
        // an add that is running cannot be taken back: the Hub is connecting to the printer (05-android-app 2.5, rule 2)
        if (_state.value.dialog?.busy == true) return
        _state.update { it.copy(dialog = null) }
        refresh()
    }

    fun submitAdd(accessCode: String, name: String) {
        val d = _state.value.dialog ?: return
        if (d.busy) return
        val code = accessCode.trim()
        if (code.isEmpty()) {
            _state.update { it.copy(dialog = d.copy(codeMissing = true, problem = null)) }
            return
        }
        _state.update { it.copy(dialog = d.copy(name = name, busy = true, codeMissing = false, problem = null)) }
        viewModelScope.launch {
            guard(onError = { p -> _state.update { s -> s.copy(dialog = s.dialog?.copy(busy = false, problem = p)) } }) {
                val p = backend.addPrinter(d.serial, code, name.trim().ifBlank { null })
                settleLater()
                if (p.state == "connected") {
                    _state.update {
                        if (d.rekey) it.copy(dialog = null, replaced = p.name) else it.copy(dialog = null, added = p.name)
                    }
                    load()
                } else {
                    _state.update { s -> s.copy(dialog = s.dialog?.copy(busy = false, problem = Problem.PrinterState(p.state))) }
                }
            }
        }
    }

    /** Opens the Klipper form; [host] and [port] are filled in when it comes from a search result or a found row. */
    fun openAddKlipper(host: String = "", port: Int = DEFAULT_KLIPPER_PORT) = _state.update {
        it.copy(klipper = KlipperDialog(host = host, port = port), find = null)
    }

    fun cancelAddKlipper() {
        val k = _state.value.klipper
        if (k?.busy == true) return
        _state.update { it.copy(klipper = null) }
        if (k?.createdId != null) refresh()
    }

    /**
     * Adds a Klipper printer by its Moonraker address; [port] is the form's text, blank meaning the default 7125. The
     * Hub's add route takes no API key, so a typed [apiKey] is set on the new printer right after.
     */
    fun submitAddKlipper(host: String, port: String, name: String, apiKey: String = "") {
        val d = _state.value.klipper ?: return
        if (d.busy) return
        val key = apiKey.trim()
        val address = host.trim()
        val portNumber = port.trim().ifEmpty { DEFAULT_KLIPPER_PORT.toString() }.toIntOrNull()?.takeIf { it in 1..65535 }
        // once the printer is added only its key is left to set, so the address and port are no longer checked
        if (d.createdId == null && (address.isEmpty() || portNumber == null)) {
            _state.update {
                it.copy(klipper = d.copy(addressMissing = address.isEmpty(), portInvalid = portNumber == null, problem = null))
            }
            return
        }
        _state.update {
            it.copy(
                klipper = d.copy(busy = true, addressMissing = false, portInvalid = false, problem = null, keyProblem = null),
            )
        }
        viewModelScope.launch {
            guard(onError = { p -> _state.update { s -> s.copy(klipper = s.klipper?.copy(busy = false, problem = p)) } }) {
                val id: String
                val shown: String
                if (d.createdId != null) {
                    id = d.createdId
                    shown = d.createdName
                } else {
                    val p = backend.addKlipperPrinter(address, portNumber!!, name.trim().ifBlank { null })
                    id = p.id
                    shown = p.name
                    settleLater()
                    _state.update { it.copy(klipper = it.klipper?.copy(createdId = p.id, createdName = p.name)) }
                }
                if (key.isNotEmpty()) {
                    try {
                        backend.setApiKey(id, key)
                    } catch (e: ApiError) {
                        if (e.code == "unauthorized") throw e
                        // the printer exists now: the form stays for the key, with the Hub's reason under it
                        _state.update { it.copy(klipper = it.klipper?.copy(busy = false, keyProblem = problemOf(e))) }
                        load()
                        return@guard
                    }
                }
                _state.update { it.copy(klipper = null, added = shown) }
                load()
            }
        }
    }

    /** The Hub's first connection to a new printer takes a moment: the list is read again once it has settled. */
    private fun settleLater() {
        settleJob?.cancel()
        settleJob = viewModelScope.launch {
            delay(SETTLE_MS)
            load()
        }
    }

    fun openFind() = _state.update { it.copy(find = FindSheet()) }

    fun closeFind() {
        findJob?.cancel()
        _state.update { it.copy(find = null) }
    }

    /** Searches [network] (blank: the Hub's own) for Moonraker. */
    fun search(network: String) {
        val f = _state.value.find ?: return
        if (f.searching) return
        val typed = network.trim()
        _state.update { it.copy(find = f.copy(searching = true, problem = null)) }
        findJob = viewModelScope.launch {
            guard(onError = { p -> _state.update { s -> s.copy(find = s.find?.copy(searching = false, problem = p)) } }) {
                val found = backend.scanKlipper(typed.ifEmpty { null }).filterNot { it.configured }
                _state.update { it.copy(find = it.find?.copy(searching = false, results = found, network = typed)) }
                // the scan records what it found, so the list may have a new row
                load()
            }
        }
    }

    /** The screen showed the "Added" message. */
    fun addedShown() = _state.update { it.copy(added = null, replaced = null) }

    private suspend fun guard(onError: (Problem) -> Unit, block: suspend () -> Unit) {
        try {
            block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: FingerprintMismatch) {
            _state.update { it.copy(mismatch = e.expected to e.actual) }
            onError(Problem.CertificateChanged)
        } catch (e: ApiError) {
            if (e.code == "unauthorized") {
                _state.update { it.copy(unauthorized = true) }
                onError(Problem.NoLongerPaired)
            } else {
                onError(problemOf(e))
            }
        } catch (e: Exception) {
            onError(Problem.Unexpected)
        }
    }

    companion object {
        const val DEFAULT_KLIPPER_PORT = 7125

        /** How long after an add the list is read again. */
        const val SETTLE_MS = 10_000L
    }
}
