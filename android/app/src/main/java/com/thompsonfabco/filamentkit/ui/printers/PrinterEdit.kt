package com.thompsonfabco.filamentkit.ui.printers

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
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

/** What one edit dialog changes. [secret]: typed hidden, never kept after the request. */
enum class EditField(val title: String, val button: String, val secret: Boolean = false) {
    NAME("Rename", "Rename"),
    ADDRESS("Change address", "Change address"),
    ACCESS_CODE("Replace Access Code", "Replace Access Code", secret = true),
    API_KEY("Moonraker API key", "Change API key", secret = true),
}

/** Texts of the printer's edit and remove section. */
object PrinterEditTexts {
    const val HEADING = "Printer settings"
    const val UNPIN = "Forget certificate"
    const val UNPIN_QUESTION = "Forget the certificate pinned for this printer? The next connection trusts whatever " +
        "answers at its address and pins that."
    const val REMOVE = "Remove printer"
    const val ADDRESS_HELP = "An IP address or a name; a name is kept as you type it."
    const val PORT_HELP = "Moonraker's port (empty: keep it)"
    const val API_KEY_HELP = "Empty: the printer needs none (clears the key)."
    const val NEED_NAME = "Give the printer a name."
    const val NEED_ADDRESS = "Enter the printer's address."
    const val BAD_PORT = "The port must be a number from 1 to 65535."
    const val NEED_CODE = "Enter the Access Code. ${PrinterHelp.ACCESS_CODE_HELP}."

    fun removeQuestion(p: Printer): String = "Remove ${p.name}? The server forgets it" +
        (if (p.family == "klipper") " and its API key." else " and its Access Code. A Bambu printer still on the " +
            "network shows up again in the list, not set up.")

    /** "Saved." plus the server's note, and what the new connection says when it is not connected. */
    fun saved(r: PrinterEditResult, reconnected: Boolean): String = listOfNotNull(
        "Saved.",
        r.note?.ifBlank { null }?.let { "$it." },
        if (reconnected && r.printer.state != "connected") PrinterHelp.fix(r.printer.state)
            ?: "Now: ${PrinterHelp.stateLabel(r.printer.state)}." else null,
    ).joinToString(" ")
}

data class EditDialog(val field: EditField, val busy: Boolean = false, val error: String? = null)

data class PrinterEditUiState(
    val dialog: EditDialog? = null,
    val confirmUnpin: Boolean = false,
    val confirmRemove: Boolean = false,
    val busy: Boolean = false,
    /** The last change's result, or why an unpin or remove failed. */
    val message: String? = null,
    val messageIsError: Boolean = false,
    /** The printer was removed: the screen goes back to the list. */
    val removed: Boolean = false,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
)

/**
 * Rename, address, Access Code / API key, forget certificate and remove for one printer. Secrets are only passed
 * through to the request body. [onChanged] gets the printer the server answered with (the screen shows it at once).
 */
class PrinterEditViewModel(
    private val backend: PrinterEditBackend,
    private val id: String,
    private val family: String,
    private val onChanged: (Printer) -> Unit = {},
) : ViewModel() {
    private val _state = MutableStateFlow(PrinterEditUiState())
    val state: StateFlow<PrinterEditUiState> = _state.asStateFlow()

    /** The buttons this printer gets, in order. */
    val fields: List<EditField> =
        if (family == "klipper") listOf(EditField.NAME, EditField.ADDRESS, EditField.API_KEY)
        else listOf(EditField.NAME, EditField.ADDRESS, EditField.ACCESS_CODE)
    val canUnpin: Boolean get() = family != "klipper"

    fun open(field: EditField) = _state.update { it.copy(dialog = EditDialog(field), message = null) }

    fun close() = _state.update { if (it.dialog?.busy == true) it else it.copy(dialog = null) }

    /** [value] is the dialog's text; [port] only for a Klipper address (blank: keep). */
    fun submit(value: String, port: String = "") {
        val d = _state.value.dialog ?: return
        if (d.busy) return
        val v = value.trim()
        val problem = when (d.field) {
            EditField.NAME -> if (v.isEmpty()) PrinterEditTexts.NEED_NAME else null
            EditField.ADDRESS -> if (v.isEmpty()) PrinterEditTexts.NEED_ADDRESS
                else if (port.isNotBlank() && port.trim().toIntOrNull()?.takeIf { it in 1..65535 } == null) PrinterEditTexts.BAD_PORT
                else null
            EditField.ACCESS_CODE -> if (v.isEmpty()) PrinterEditTexts.NEED_CODE else null
            EditField.API_KEY -> null
        }
        if (problem != null) {
            _state.update { it.copy(dialog = d.copy(error = problem)) }
            return
        }
        val body = buildJsonObject {
            when (d.field) {
                EditField.NAME -> put("name", v)
                EditField.ADDRESS -> {
                    put("address", v)
                    if (family == "klipper" && port.isNotBlank()) put("port", port.trim().toInt())
                }
                EditField.ACCESS_CODE -> put("access_code", v)
                EditField.API_KEY -> put("api_key", v)
            }
        }
        _state.update { it.copy(dialog = d.copy(busy = true, error = null)) }
        viewModelScope.launch {
            guard(onError = { msg -> _state.update { s -> s.copy(dialog = s.dialog?.copy(busy = false, error = msg)) } }) {
                val r = backend.editPrinter(id, body)
                onChanged(r.printer)
                _state.update {
                    it.copy(dialog = null, message = PrinterEditTexts.saved(r, d.field != EditField.NAME), messageIsError = false)
                }
            }
        }
    }

    fun askUnpin() = _state.update { it.copy(confirmUnpin = true, message = null) }
    fun cancelUnpin() = _state.update { it.copy(confirmUnpin = false) }

    fun confirmUnpin() {
        if (_state.value.busy) return
        _state.update { it.copy(confirmUnpin = false, busy = true) }
        viewModelScope.launch {
            guard(onError = ::fail) {
                val r = backend.editPrinter(id, buildJsonObject { put("unpin", true) })
                onChanged(r.printer)
                _state.update { it.copy(message = PrinterEditTexts.saved(r, true), messageIsError = false) }
            }
            _state.update { it.copy(busy = false) }
        }
    }

    fun askRemove() = _state.update { it.copy(confirmRemove = true, message = null) }
    fun cancelRemove() = _state.update { it.copy(confirmRemove = false) }

    fun confirmRemove() {
        if (_state.value.busy) return
        _state.update { it.copy(confirmRemove = false, busy = true) }
        viewModelScope.launch {
            guard(onError = ::fail) {
                backend.removePrinter(id)
                _state.update { it.copy(removed = true) }
            }
            _state.update { it.copy(busy = false) }
        }
    }

    private fun fail(msg: String) = _state.update { it.copy(message = msg, messageIsError = true) }

    private suspend fun guard(onError: (String) -> Unit, block: suspend () -> Unit) {
        try {
            block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: FingerprintMismatch) {
            _state.update { it.copy(mismatch = e.expected to e.actual, dialog = null) }
        } catch (e: ApiError) {
            when (e.code) {
                "unauthorized" -> _state.update { it.copy(unauthorized = true, dialog = null) }
                // the server's own sentence (the setup page's) says what is wrong with the value or the name
                "bad_request", "exists", "not_found", "module_off" -> onError(e.message)
                else -> onError(PrinterHelp.message(e))
            }
        } catch (e: Exception) {
            onError(PrinterHelp.UNEXPECTED)
        }
    }
}

/** The section at the bottom of a printer's screen, and its dialogs. [onRemoved] goes back to the list. */
@Composable
internal fun PrinterEditSection(printer: Printer, edit: PrinterEditViewModel, onRemoved: () -> Unit) {
    val s by edit.state.collectAsState()
    LaunchedEffect(s.removed) { if (s.removed) onRemoved() }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(PrinterEditTexts.HEADING, style = MaterialTheme.typography.titleMedium)
        edit.fields.forEach { f ->
            OutlinedButton(onClick = { edit.open(f) }, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) { Text(f.button) }
        }
        if (edit.canUnpin) {
            OutlinedButton(onClick = edit::askUnpin, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
                Text(PrinterEditTexts.UNPIN)
            }
        }
        OutlinedButton(
            onClick = edit::askRemove, enabled = !s.busy, modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
        ) { Text(PrinterEditTexts.REMOVE) }
        s.message?.let { Text(it, color = if (s.messageIsError) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface) }
    }

    s.dialog?.let { d -> EditFieldDialog(printer, d, edit) }
    if (s.confirmUnpin) {
        AlertDialog(
            onDismissRequest = edit::cancelUnpin,
            title = { Text("${PrinterEditTexts.UNPIN}?") },
            text = { Text(PrinterEditTexts.UNPIN_QUESTION) },
            confirmButton = { Button(onClick = edit::confirmUnpin) { Text(PrinterEditTexts.UNPIN) } },
            dismissButton = { TextButton(onClick = edit::cancelUnpin) { Text("Cancel") } },
        )
    }
    if (s.confirmRemove) {
        AlertDialog(
            onDismissRequest = edit::cancelRemove,
            title = { Text("${PrinterEditTexts.REMOVE}?") },
            text = { Text(PrinterEditTexts.removeQuestion(printer)) },
            confirmButton = {
                Button(
                    onClick = edit::confirmRemove,
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                ) { Text("Remove") }
            },
            dismissButton = { TextButton(onClick = edit::cancelRemove) { Text("Keep") } },
        )
    }
}

@Composable
private fun EditFieldDialog(printer: Printer, d: EditDialog, edit: PrinterEditViewModel) {
    // a secret starts empty and is not saved across rotation; the others start from what the printer has now
    val start = when (d.field) {
        EditField.NAME -> printer.name
        EditField.ADDRESS -> printer.ip.orEmpty()
        else -> ""
    }
    var value by if (d.field.secret) remember(d.field) { mutableStateOf("") }
    else rememberSaveable(d.field) { mutableStateOf(start) }
    var port by rememberSaveable(d.field) { mutableStateOf("") }
    val klipper = printer.family == "klipper"
    AlertDialog(
        onDismissRequest = edit::close,
        title = { Text(d.field.title) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = value, onValueChange = { value = it }, singleLine = true, enabled = !d.busy,
                    label = {
                        Text(when (d.field) {
                            EditField.NAME -> "Name"
                            EditField.ADDRESS -> "Address"
                            EditField.ACCESS_CODE -> "Access Code"
                            EditField.API_KEY -> "API key"
                        })
                    },
                    visualTransformation = if (d.field.secret) PasswordVisualTransformation() else VisualTransformation.None,
                    keyboardOptions = if (d.field.secret) KeyboardOptions(keyboardType = KeyboardType.Password) else KeyboardOptions.Default,
                    modifier = Modifier.fillMaxWidth(),
                )
                when (d.field) {
                    EditField.ADDRESS -> {
                        Text(PrinterEditTexts.ADDRESS_HELP, style = MaterialTheme.typography.bodySmall)
                        if (klipper) {
                            OutlinedTextField(
                                value = port, onValueChange = { port = it.filter(Char::isDigit).take(5) }, singleLine = true,
                                enabled = !d.busy, label = { Text(PrinterEditTexts.PORT_HELP) },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                    }
                    EditField.ACCESS_CODE -> Text("${PrinterHelp.ACCESS_CODE_HELP}.", style = MaterialTheme.typography.bodySmall)
                    EditField.API_KEY -> Text(PrinterEditTexts.API_KEY_HELP, style = MaterialTheme.typography.bodySmall)
                    EditField.NAME -> Unit
                }
                if (d.busy) Text(if (d.field == EditField.NAME) "Saving…" else "Saving and connecting…")
                d.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = { Button(onClick = { edit.submit(value, port) }, enabled = !d.busy) { Text("Save") } },
        dismissButton = { TextButton(onClick = edit::close, enabled = !d.busy) { Text("Cancel") } },
    )
}
