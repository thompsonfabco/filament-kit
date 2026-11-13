package com.thompsonfabco.filamentkit.ui.spool

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.AmsSlot
import com.thompsonfabco.filamentkit.net.AmsUnit
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LoadResult
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterDetail
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The calls "Load into a printer" needs; [of] adapts the real [Api] at each call, tests pass a fake. */
interface LoadBackend {
    suspend fun printers(): List<Printer>
    suspend fun printer(id: String): PrinterDetail
    suspend fun load(id: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult

    companion object {
        fun of(current: () -> Api): LoadBackend = object : LoadBackend {
            override suspend fun printers() = current().printers()
            override suspend fun printer(id: String) = current().printer(id)
            override suspend fun load(id: String, label: String, spoolId: Int, dryRun: Boolean) =
                current().load(id, label, spoolId, dryRun)
        }
    }
}

/**
 * Whether a load is being written, for the whole app: a tag tapped meanwhile waits (05 2.6) and the load screen ignores
 * Back (2.5 rule 2). The load's own screen sets it; it is one value because only one load runs at a time.
 */
class LoadGate {
    private val _writing = MutableStateFlow(false)
    val writing: StateFlow<Boolean> = _writing.asStateFlow()

    internal fun set(on: Boolean) {
        _writing.value = on
    }
}

/** The printers that can take a load now: set up and connected (05 7.6). */
internal fun canTakeLoad(p: Printer): Boolean = p.configured && p.state == Printer.STATE_CONNECTED

/** Step 1: the printers; [printers] is null while they load. */
data class LoadPrintersUi(
    val printers: List<Printer>? = null,
    val loading: Boolean = true,
    val failure: HubFailure? = null,
    val loadedAt: Long? = null,
) {
    /** The only printer that can take the load, when there is exactly one: the step is skipped. */
    val only: Printer? get() = printers?.filter(::canTakeLoad)?.singleOrNull()
}

class LoadPrintersViewModel(private val backend: LoadBackend) : ViewModel() {
    private val _state = MutableStateFlow(LoadPrintersUi())
    val state: StateFlow<LoadPrintersUi> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        _state.update { it.copy(loading = true, failure = null) }
        viewModelScope.launch {
            try {
                val list = backend.printers().filter { it.configured }
                _state.update { LoadPrintersUi(list, loading = false, loadedAt = System.currentTimeMillis()) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(loading = false, failure = hubFailure(e)) }
            }
        }
    }
}

/** Step 2: the slots of one printer, as the printer reports them; [slots] is null while they load. */
data class LoadSlotsUi(
    val printer: Printer? = null,
    val units: List<AmsUnit> = emptyList(),
    val slots: List<AmsSlot>? = null,
    val loading: Boolean = true,
    val failure: HubFailure? = null,
    val loadedAt: Long? = null,
)

class LoadSlotsViewModel(private val printerId: String, private val backend: LoadBackend) : ViewModel() {
    private val _state = MutableStateFlow(LoadSlotsUi())
    val state: StateFlow<LoadSlotsUi> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        _state.update { it.copy(loading = true, failure = null) }
        viewModelScope.launch {
            try {
                val d = backend.printer(printerId)
                val units = d.status?.ams.orEmpty()
                val slots = units.flatMap { it.slots }.filter { it.label.isNotBlank() }
                _state.update { LoadSlotsUi(d.printer, units, slots, loading = false, loadedAt = System.currentTimeMillis()) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(loading = false, failure = hubFailure(e)) }
            }
        }
    }
}

/**
 * Step 3 (05 7.6): [plan] is the dry run's answer; while [writing] the load is being sent. [finished] is the result the
 * spool screen shows once it is back on screen; [dropped] and [pairingRefused] are the two writes that end on this step.
 */
data class LoadPreviewUi(
    val printer: Printer? = null,
    val units: List<AmsUnit> = emptyList(),
    val checking: Boolean = true,
    val plan: LoadResult? = null,
    val writing: Boolean = false,
    val failure: HubFailure? = null,
    val pairingRefused: Boolean = false,
    val dropped: Boolean = false,
    val finished: SpoolResult? = null,
)

/**
 * The preview of loading [spool] into slot [label] of printer [printerId], asked for when it is made, and the load
 * itself. The write is not stopped by leaving the screen: Back waits for its answer ([writing], [gate]).
 */
class LoadPreviewViewModel(
    private val spool: SpoolSummary,
    private val printerId: String,
    private val label: String,
    private val backend: LoadBackend,
    private val gate: LoadGate = LoadGate(),
) : ViewModel() {
    private val _state = MutableStateFlow(LoadPreviewUi())
    val state: StateFlow<LoadPreviewUi> = _state.asStateFlow()

    init {
        check()
    }

    fun check() {
        _state.update { it.copy(checking = true, failure = null, dropped = false, pairingRefused = false) }
        viewModelScope.launch {
            try {
                val d = backend.printer(printerId)
                val plan = backend.load(printerId, label, spool.id, dryRun = true)
                _state.update {
                    it.copy(
                        printer = d.printer, units = d.status?.ams.orEmpty(), checking = false, plan = plan,
                        failure = it.failure.afterSuccess(),
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(checking = false, failure = hubFailure(e)) }
            }
        }
    }

    /** Sends the load. Once sent it is not cancelled: the screen waits for the answer. */
    fun load() {
        val s = _state.value
        val printer = s.printer ?: return
        if (s.writing || s.checking || s.plan == null) return
        gate.set(true)
        _state.update { it.copy(writing = true, failure = null, pairingRefused = false, dropped = false) }
        viewModelScope.launch {
            try {
                val r = backend.load(printerId, label, spool.id, dryRun = false)
                val result = if (r.confirmed) SpoolResult.Loaded(printer.name, label) else SpoolResult.LoadedUnconfirmed(printer.name, label)
                // the spool as the Hub has it now, for the spool screen that is shown next
                r.spool.asSummary()?.let(SpoolCache::put)
                _state.update { it.copy(writing = false, finished = result) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: FingerprintMismatch) {
                _state.update { it.copy(writing = false, failure = HubFailure.CertificateChanged) }
            } catch (e: ApiError) {
                _state.update {
                    when {
                        // the Hub refused the pairing before doing anything
                        e.code == UNAUTHORIZED -> it.copy(writing = false, pairingRefused = true)
                        // no route: the request may or may not have reached the printer
                        e.status == 0 -> it.copy(writing = false, dropped = true)
                        else -> it.copy(writing = false, failure = hubFailure(e))
                    }
                }
            } catch (e: Exception) {
                _state.update { it.copy(writing = false, dropped = true) }
            } finally {
                gate.set(false)
            }
        }
    }

    override fun onCleared() {
        gate.set(false)
    }

    private companion object {
        const val UNAUTHORIZED = "unauthorized"
    }
}
