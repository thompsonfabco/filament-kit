package com.thompsonfabco.filamentkit.ui.printers

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterEditResult
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** `PATCH` / `DELETE /api/printers/{id}`; [ApiPrinterBackend] adapts the Api, tests pass a fake. */
interface PrinterEditBackend {
    suspend fun editPrinter(id: String, changes: JsonObject): PrinterEditResult
    suspend fun removePrinter(id: String)
}

/** What one settings dialog changes (05-android-app 9.9). Secrets are typed hidden and never kept after the request. */
enum class EditField(val secret: Boolean = false) {
    NAME,
    ADDRESS,
    ACCESS_CODE(secret = true),
    API_KEY(secret = true),

    /** Bambu, pinned only: `unpin` with the Access Code in the same request (the Hub asks for both). */
    TRUST_CERT(secret = true),
}

/** The field a dialog's own check found empty or wrong: its words go under that field. */
enum class FieldError { Name, Address, Port, AccessCode }

/**
 * An open dialog. [codeToo]: a Bambu address change, which asks for the Access Code again. [problem] is the Hub's
 * refusal (or a Hub notice), shown in the dialog with what was typed kept.
 */
data class EditDialog(
    val field: EditField,
    val busy: Boolean = false,
    val error: FieldError? = null,
    val problem: Problem? = null,
    val codeToo: Boolean = false,
)

data class PrinterEditUiState(
    val dialog: EditDialog? = null,
    /** The "Forget <printer>?" question is open; it stays open while the request is out. */
    val confirmForget: Boolean = false,
    val busy: Boolean = false,
    /** The last change's result line, shown at the top of the screen. */
    val note: Note? = null,
    /** The Hub's own note about the change, as sent. */
    val hubNote: String? = null,
    /** The printer was forgotten: the screen goes back to the list. */
    val forgotten: Boolean = false,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
)

/**
 * Rename, address, Access Code / API key, forget the certificate and forget the printer. Secrets are only passed
 * through to the request body; the Hub never sends a stored one to a new host: a move of a printer with no pinned
 * certificate, a new certificate, and a Klipper move with a stored key each carry the secret in the same request.
 * [onChanged] gets the printer the Hub answered with (the screen shows it at once). Every request goes to the
 * session's client of that moment; a Hub notice is cleared by the next request that succeeds.
 */
class PrinterEditViewModel(
    private val backend: PrinterEditBackend,
    private val id: String,
    private val family: String,
    private val onChanged: (Printer) -> Unit = {},
) : ViewModel() {
    private val _state = MutableStateFlow(PrinterEditUiState())
    val state: StateFlow<PrinterEditUiState> = _state.asStateFlow()

    /** Runs after any request succeeded, so the screen's other view models drop their Hub notice too. */
    var onHubOk: () -> Unit = {}

    fun clearHubNotice() = _state.update { it.copy(unauthorized = false, mismatch = null) }

    /** The rows [p] gets, in order: the certificate only for a Bambu printer that has one pinned. */
    fun fields(p: Printer): List<EditField> =
        if (family == "klipper") listOf(EditField.NAME, EditField.ADDRESS, EditField.API_KEY)
        else listOfNotNull(EditField.NAME, EditField.ADDRESS, EditField.ACCESS_CODE, EditField.TRUST_CERT.takeIf { p.pinned })

    fun open(field: EditField) = _state.update {
        it.copy(dialog = EditDialog(field, codeToo = field == EditField.ADDRESS && family != "klipper"), note = null, hubNote = null)
    }

    /** A dialog is left by its Cancel, Back or scrim, and not while its request is out. */
    fun close() = _state.update { if (it.dialog?.busy == true) it else it.copy(dialog = null) }

    /**
     * [value] is the dialog's text; [port] only for a Klipper address (blank: keep); [secret] is the second field of an
     * address dialog: the Access Code of a Bambu printer, or a Klipper printer's API key (blank: not sent).
     */
    fun submit(value: String, port: String = "", secret: String = "") {
        val d = _state.value.dialog ?: return
        if (d.busy) return
        val v = value.trim()
        val problem = when (d.field) {
            EditField.NAME -> if (v.isEmpty()) FieldError.Name else null
            EditField.ADDRESS -> if (v.isEmpty()) FieldError.Address
                else if (port.isNotBlank() && port.trim().toIntOrNull()?.takeIf { it in 1..65535 } == null) FieldError.Port
                else if (d.codeToo && secret.isBlank()) FieldError.AccessCode
                else null
            EditField.ACCESS_CODE, EditField.TRUST_CERT -> if (v.isEmpty()) FieldError.AccessCode else null
            EditField.API_KEY -> null
        }
        if (problem != null) {
            _state.update { it.copy(dialog = d.copy(error = problem, problem = null)) }
            return
        }
        val body = buildJsonObject {
            when (d.field) {
                EditField.NAME -> put("name", v)
                EditField.ADDRESS -> {
                    put("address", v)
                    if (family == "klipper") {
                        if (port.isNotBlank()) put("port", port.trim().toInt())
                        if (secret.isNotBlank()) put("api_key", secret.trim())
                    } else if (d.codeToo) {
                        put("access_code", secret.trim())
                    }
                }
                EditField.ACCESS_CODE -> put("access_code", v)
                EditField.API_KEY -> put("api_key", v)
                EditField.TRUST_CERT -> {
                    put("unpin", true)
                    put("access_code", v)
                }
            }
        }
        _state.update { it.copy(dialog = d.copy(busy = true, error = null, problem = null)) }
        viewModelScope.launch {
            guard(onError = { p -> _state.update { s -> s.copy(dialog = s.dialog?.copy(busy = false, problem = p)) } }) {
                val r = backend.editPrinter(id, body)
                onChanged(r.printer)
                _state.update {
                    it.copy(dialog = null, note = saved(d.field, v, r), hubNote = r.note?.ifBlank { null })
                }
            }
        }
    }

    fun askForget() = _state.update { it.copy(confirmForget = true, note = null, hubNote = null) }

    /** The question cannot be left while the request is out. */
    fun cancelForget() = _state.update { if (it.busy) it else it.copy(confirmForget = false) }

    fun confirmForget() {
        if (_state.value.busy) return
        _state.update { it.copy(busy = true) }
        viewModelScope.launch {
            guard(onError = { p -> _state.update { it.copy(note = Note(p.say(), ok = false)) } }) {
                backend.removePrinter(id)
                _state.update { it.copy(forgotten = true) }
            }
            _state.update { it.copy(busy = false, confirmForget = false) }
        }
    }

    /** What the line at the top of the screen says after a change (05-android-app 9.9); a printer that does not answer says what to do. */
    private fun saved(field: EditField, value: String, r: PrinterEditResult): Note {
        val connected = r.printer.state == "connected"
        return when (field) {
            EditField.NAME -> Note(Say.Words(R.string.printer_set_renamed, listOf(r.printer.name.ifBlank { value })))
            EditField.ADDRESS ->
                if (connected) Note(Say.Words(R.string.printer_set_address_done))
                else fixLine(r.printer.state)?.let { Note(Say.Words(it), ok = false) } ?: Note(Say.Words(R.string.printer_set_saved))
            EditField.ACCESS_CODE ->
                if (connected || fixLine(r.printer.state) == null) Note(Say.Words(R.string.printer_set_code_done, listOf(r.printer.name)))
                else Note(Say.Words(fixLine(r.printer.state)!!), ok = false)
            EditField.API_KEY, EditField.TRUST_CERT -> Note(Say.Words(R.string.printer_set_saved))
        }
    }

    private suspend fun guard(onError: (Problem) -> Unit, block: suspend () -> Unit) {
        try {
            block()
            if (_state.value.unauthorized || _state.value.mismatch != null) clearHubNotice()
            onHubOk()
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
                onError(printerProblem(e))
            }
        } catch (e: Exception) {
            onError(UNREADABLE)
        }
    }
}
