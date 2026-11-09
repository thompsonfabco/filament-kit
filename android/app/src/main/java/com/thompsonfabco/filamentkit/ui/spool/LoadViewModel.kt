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
import com.thompsonfabco.filamentkit.ui.printers.PrinterHelp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import java.math.BigDecimal

/** The calls "Load into printer" needs; [ApiLoadBackend] adapts [Api], tests pass a fake. */
interface LoadBackend {
    suspend fun printers(): List<Printer>
    suspend fun printer(id: String): PrinterDetail
    suspend fun load(id: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult
}

class ApiLoadBackend(private val api: Api) : LoadBackend {
    override suspend fun printers() = api.printers()
    override suspend fun printer(id: String) = api.printer(id)
    override suspend fun load(id: String, label: String, spoolId: Int, dryRun: Boolean) = api.load(id, label, spoolId, dryRun)
}

sealed interface LoadUiState {
    data object Closed : LoadUiState

    /** [printers] is null while loading. */
    data class PickPrinter(val spool: SpoolSummary, val printers: List<Printer>? = null, val error: String? = null) : LoadUiState

    /** [slots] (every AMS slot the printer reports) is null while loading. */
    data class PickSlot(
        val spool: SpoolSummary,
        val printer: Printer,
        val slots: List<AmsSlot>? = null,
        val error: String? = null,
        val busy: Boolean = false,
        /** The printer's units, to name its external holders. */
        val units: List<AmsUnit> = emptyList(),
    ) : LoadUiState

    /** The dry run's answer, as [lines]; confirm sends the real load. */
    data class Preview(
        val spool: SpoolSummary,
        val printer: Printer,
        val label: String,
        val result: LoadResult,
        val lines: List<String>,
        val busy: Boolean = false,
        val error: String? = null,
    ) : LoadUiState

    /** [spool]/[spoolJson] are the spool as the server now has it (null if it did not say). */
    data class Done(
        val printer: Printer,
        val label: String,
        val lines: List<String>,
        val spool: SpoolSummary?,
        val spoolJson: JsonObject?,
    ) : LoadUiState

    data object Unauthorized : LoadUiState
    data class Mismatch(val expected: String, val actual: String) : LoadUiState
}

/**
 * Closing the spool card (its Done, a new tag tap, a trip to the Pair screen): closes the load flow [load] and then
 * calls [dismissCard], except while a real load is being written; then both stay so the user sees its result (also
 * when coming back from pairing again).
 */
fun closeSpoolCard(load: LoadViewModel?, dismissCard: () -> Unit) {
    if (load?.close() != false) dismissCard()
}

/** Texts of the load flow. */
object LoadHelp {
    const val NOT_CONFIRMED = "The printer accepted it but hasn't shown the change yet"

    /** The real load failed in a way that says nothing about whether it reached the printer. */
    const val CHECK_PRINTER = "The connection dropped while loading, so the app can't tell if it worked. Check the " +
        "printer's slot and the spool's location before trying again."

    /** A 401 to the real load: the server refused it before doing anything (e.g. the pairing changed meanwhile). */
    const val NOT_SENT_PAIRING = "Not loaded: the server did not accept this phone's pairing at that moment. " +
        "Nothing was changed. If you have paired again, tap Load to try again."

    /** [units] are the printer's units (they name its external holders). */
    fun previewLines(
        spool: SpoolSummary,
        printer: Printer,
        r: LoadResult,
        units: List<AmsUnit> = emptyList(),
    ): List<String> = buildList {
        add("Load ${spool.title()} into ${printer.name}, ${PrinterHelp.slotName(r.slot.label, units)}")
        add(r.preset?.name?.ifBlank { null }?.let { "Preset: $it" } ?: "Preset: none")
        val mm = r.nozzleMm?.let(::mm)
        when {
            r.nozzleAssumed -> add("Nozzle size not reported by the printer; assuming ${mm ?: "0.4"} mm")
            mm != null -> add("Nozzle: $mm mm")
        }
        r.movedBack.filter { it.id != spool.id }.forEach { m ->
            add("Spool #${m.id ?: "?"} now in ${r.slot.label} goes back to ${m.location.ifBlank { "its previous place" }}")
        }
        addAll(r.problems)
    }

    /**
     * The result. [loadedId] is the spool just loaded (never listed as moved back); [names] are spool names by id
     * (from the printer's slots) for the spools that went back to their previous place.
     */
    fun doneLines(
        printer: Printer,
        r: LoadResult,
        loadedId: Int? = null,
        names: Map<Int, String> = emptyMap(),
        units: List<AmsUnit> = emptyList(),
    ) =
        buildList {
            val where = PrinterHelp.slotName(r.slot.label, units)
            if (r.confirmed) {
                add("Loaded into ${printer.name}, $where")
            } else {
                add("Sent to ${printer.name}, $where")
                add(NOT_CONFIRMED)
            }
            r.movedBack.filter { it.id == null || it.id != loadedId }.forEach { m ->
                add(PrinterHelp.movedBackLine(m.id?.let(names::get), m.id, m.location))
            }
            addAll(r.problems)
        }

    fun slotLine(s: AmsSlot, units: List<AmsUnit> = emptyList()): String = listOfNotNull(
        PrinterHelp.slotLabel(s, units),
        if (PrinterHelp.slotEmpty(s)) "empty" else s.type.ifBlank { null },
        s.spool?.name?.ifBlank { null },
    ).joinToString(" · ")

    private fun SpoolSummary.title() = "$brand $name".trim().ifBlank { "spool #$id" }

    private fun mm(v: Double): String = BigDecimal.valueOf(v).stripTrailingZeros().toPlainString()
}

/**
 * "Load into printer" from the spool card: [start] → printer list → [pickPrinter] → slot list → [pickSlot] (dry run)
 * → [confirm] (real load). Errors keep the user on the step they were on, with a message.
 */
class LoadViewModel(private val backend: LoadBackend) : ViewModel() {
    private val _state = MutableStateFlow<LoadUiState>(LoadUiState.Closed)
    val state: StateFlow<LoadUiState> = _state.asStateFlow()

    private var job: Job? = null
    private var printers: List<Printer>? = null
    private var slots: List<AmsSlot>? = null
    private var units: List<AmsUnit> = emptyList()

    fun start(spool: SpoolSummary) {
        printers = null
        slots = null
        units = emptyList()
        _state.value = LoadUiState.PickPrinter(spool)
        op(onError = { LoadUiState.PickPrinter(spool, emptyList(), it) }) {
            val list = backend.printers().filter { it.configured }
            printers = list
            _state.value = LoadUiState.PickPrinter(spool, list)
        }
    }

    fun pickPrinter(printer: Printer) {
        val spool = spoolOf(_state.value) ?: return
        slots = null
        units = emptyList()
        _state.value = LoadUiState.PickSlot(spool, printer)
        op(onError = { LoadUiState.PickSlot(spool, printer, emptyList(), it) }) {
            val d = backend.printer(printer.id)
            val ams = d.status?.ams.orEmpty()
            val all = ams.flatMap { it.slots }.filter { it.label.isNotBlank() }
            slots = all
            units = ams
            _state.value = LoadUiState.PickSlot(spool, d.printer, all,
                error = if (d.status == null) "No live status from the printer yet, so its slots aren't known." else null,
                units = ams)
        }
    }

    /** Previews loading into [label] (dry run). */
    fun pickSlot(label: String) {
        val s = _state.value as? LoadUiState.PickSlot ?: return
        if (s.busy) return
        _state.value = s.copy(busy = true, error = null)
        op(onError = { s.copy(busy = false, error = it) }) {
            val r = backend.load(s.printer.id, label, s.spool.id, dryRun = true)
            _state.value = LoadUiState.Preview(s.spool, s.printer, label, r,
                LoadHelp.previewLines(s.spool, s.printer, r, s.units))
        }
    }

    /**
     * The real load. It is not cancelled by [close] / [back] or a re-pair: the flow stays open and shows the result.
     * A 401 here (e.g. the pairing changed meanwhile) stays on the preview with [LoadHelp.NOT_SENT_PAIRING] instead
     * of the "no longer paired" screen; a dropped connection says to check the printer ([LoadHelp.CHECK_PRINTER]).
     */
    fun confirm() {
        val p = _state.value as? LoadUiState.Preview ?: return
        if (p.busy) return
        _state.value = p.copy(busy = true, error = null)
        val names = slots.orEmpty().mapNotNull { s -> s.spool?.let { sp -> sp.id?.let { it to sp.name } } }.toMap()
        op(
            onError = { p.copy(busy = false, error = it) },
            describe = { e ->
                when (e.code) {
                    "unauthorized" -> LoadHelp.NOT_SENT_PAIRING
                    "offline", "local_network" -> LoadHelp.CHECK_PRINTER
                    else -> PrinterHelp.actionMessage(e)
                }
            },
            unauthorizedIsError = true,
        ) {
            val r = backend.load(p.printer.id, p.label, p.spool.id, dryRun = false)
            _state.value = LoadUiState.Done(p.printer, p.label, LoadHelp.doneLines(p.printer, r, p.spool.id, names, units),
                r.spool?.toSpoolSummary(), r.spool)
        }
    }

    /** One step back: preview → slots → printers. */
    fun back() {
        if (writing) return
        job?.cancel()
        when (val s = _state.value) {
            is LoadUiState.Preview -> _state.value = LoadUiState.PickSlot(s.spool, s.printer, slots ?: emptyList(), units = units)
            is LoadUiState.PickSlot -> _state.value = LoadUiState.PickPrinter(s.spool, printers ?: emptyList())
            else -> close()
        }
    }

    /**
     * True while the real (non-dry-run) load is in flight. The POST may already have reached the server, so the
     * flow is not cancelled then: [close] and [back] are ignored and the user gets to see the result.
     */
    val writing: Boolean get() = (_state.value as? LoadUiState.Preview)?.busy == true

    /** Closes the flow; returns false (and does nothing) while [writing]. */
    fun close(): Boolean {
        if (writing) return false
        job?.cancel()
        _state.value = LoadUiState.Closed
        return true
    }

    private fun spoolOf(s: LoadUiState): SpoolSummary? = when (s) {
        is LoadUiState.PickPrinter -> s.spool
        is LoadUiState.PickSlot -> s.spool
        is LoadUiState.Preview -> s.spool
        else -> null
    }

    /** [unauthorizedIsError]: a 401 goes to [onError] (with [describe]'s text) instead of [LoadUiState.Unauthorized]. */
    private fun op(
        onError: (String) -> LoadUiState,
        describe: (ApiError) -> String = PrinterHelp::actionMessage,
        unauthorizedIsError: Boolean = false,
        block: suspend () -> Unit,
    ) {
        job?.cancel()
        job = viewModelScope.launch {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: FingerprintMismatch) {
                _state.value = LoadUiState.Mismatch(e.expected, e.actual)
            } catch (e: ApiError) {
                _state.value = if (e.code == "unauthorized" && !unauthorizedIsError) LoadUiState.Unauthorized
                else onError(describe(e))
            } catch (e: Exception) {
                _state.value = onError(PrinterHelp.UNEXPECTED)
            }
        }
    }
}
