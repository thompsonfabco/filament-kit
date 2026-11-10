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
    /** Bambu, pinned only: `unpin` with the Access Code in the same request (the server asks for both). */
    TRUST_CERT("Trust a new certificate", "Trust a new certificate", secret = true),
}

/** Texts of the printer's edit and remove section. */
object PrinterEditTexts {
    const val HEADING = "Printer settings"
    const val TRUST_HELP = "Only after you reset the printer or replaced its mainboard: the kit then trusts the " +
        "certificate the printer has now. Type its Access Code (${PrinterHelp.ACCESS_CODE_HELP})."
    const val CODE_FOR_ADDRESS = "This printer has never connected, so the move needs its Access Code too " +
        "(${PrinterHelp.ACCESS_CODE_HELP})."
    const val KEY_FOR_ADDRESS = "API key: only if the printer has one, type it again (the server asks for it when a " +
        "printer with a key moves). Empty: not sent."
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

/** [codeToo]: a Bambu address change on a printer with no certificate pinned, which needs the Access Code. */
data class EditDialog(
    val field: EditField,
    val busy: Boolean = false,
    val error: String? = null,
    val codeToo: Boolean = false,
)

data class PrinterEditUiState(
    val dialog: EditDialog? = null,
    val confirmRemove: Boolean = false,
    val busy: Boolean = false,
    /** The last change's result, or why a remove failed. */
    val message: String? = null,
    val messageIsError: Boolean = false,
    /** The printer was removed: the screen goes back to the list. */
    val removed: Boolean = false,
    val unauthorized: Boolean = false,
    val mismatch: Pair<String, String>? = null,
)

/**
 * Rename, address, Access Code / API key, trust a new certificate and remove for one printer. Secrets are only
 * passed through to the request body; the server never sends a stored one to a new host (version 2 of the routes): a
 * move of a printer with no pinned certificate, a new certificate, and a Klipper move with a stored key each carry the
 * secret in the same request. [onChanged] gets the printer the server answered with (the screen shows it at once).
 */
class PrinterEditViewModel(
    private val backend: PrinterEditBackend,
    private val id: String,
    private val family: String,
    private val onChanged: (Printer) -> Unit = {},
) : ViewModel() {
    private val _state = MutableStateFlow(PrinterEditUiState())
    val state: StateFlow<PrinterEditUiState> = _state.asStateFlow()

    /** The buttons [p] gets, in order: a new certificate only for a Bambu printer that has one pinned. */
    fun fields(p: Printer): List<EditField> =
        if (family == "klipper") listOf(EditField.NAME, EditField.ADDRESS, EditField.API_KEY)
        else listOfNotNull(EditField.NAME, EditField.ADDRESS, EditField.ACCESS_CODE, EditField.TRUST_CERT.takeIf { p.pinned })

    fun open(field: EditField, p: Printer) = _state.update {
        it.copy(dialog = EditDialog(field, codeToo = field == EditField.ADDRESS && family != "klipper" && !p.pinned), message = null)
    }

    fun close() = _state.update { if (it.dialog?.busy == true) it else it.copy(dialog = null) }

    /**
     * [value] is the dialog's text; [port] only for a Klipper address (blank: keep); [secret] is the second field of
     * an address dialog: the Access Code ([EditDialog.codeToo]) or a Klipper printer's API key (blank: not sent).
     */
    fun submit(value: String, port: String = "", secret: String = "") {
        val d = _state.value.dialog ?: return
        if (d.busy) return
        val v = value.trim()
        val problem = when (d.field) {
            EditField.NAME -> if (v.isEmpty()) PrinterEditTexts.NEED_NAME else null
            EditField.ADDRESS -> if (v.isEmpty()) PrinterEditTexts.NEED_ADDRESS
                else if (port.isNotBlank() && port.trim().toIntOrNull()?.takeIf { it in 1..65535 } == null) PrinterEditTexts.BAD_PORT
                else if (d.codeToo && secret.isBlank()) PrinterEditTexts.NEED_CODE
                else null
            EditField.ACCESS_CODE, EditField.TRUST_CERT -> if (v.isEmpty()) PrinterEditTexts.NEED_CODE else null
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
        edit.fields(printer).forEach { f ->
            OutlinedButton(onClick = { edit.open(f, printer) }, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
                Text(f.button)
            }
        }
        OutlinedButton(
            onClick = edit::askRemove, enabled = !s.busy, modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
        ) { Text(PrinterEditTexts.REMOVE) }
        s.message?.let { Text(it, color = if (s.messageIsError) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface) }
    }

    s.dialog?.let { d -> EditFieldDialog(printer, d, edit) }
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
    var second by remember(d.field) { mutableStateOf("") }      // a secret: never in saved state
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
                            EditField.ACCESS_CODE, EditField.TRUST_CERT -> "Access Code"
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
                        if (klipper || d.codeToo) {
                            Text(if (klipper) PrinterEditTexts.KEY_FOR_ADDRESS else PrinterEditTexts.CODE_FOR_ADDRESS,
                                style = MaterialTheme.typography.bodySmall)
                            OutlinedTextField(
                                value = second, onValueChange = { second = it }, singleLine = true, enabled = !d.busy,
                                label = { Text(if (klipper) "API key" else "Access Code") },
                                visualTransformation = PasswordVisualTransformation(),
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                    }
                    EditField.ACCESS_CODE -> Text("${PrinterHelp.ACCESS_CODE_HELP}.", style = MaterialTheme.typography.bodySmall)
                    EditField.API_KEY -> Text(PrinterEditTexts.API_KEY_HELP, style = MaterialTheme.typography.bodySmall)
                    EditField.TRUST_CERT -> Text(PrinterEditTexts.TRUST_HELP, style = MaterialTheme.typography.bodySmall)
                    EditField.NAME -> Unit
                }
                if (d.busy) Text(if (d.field == EditField.NAME) "Saving…" else "Saving and connecting…")
                d.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = { Button(onClick = { edit.submit(value, port, second) }, enabled = !d.busy) { Text("Save") } },
        dismissButton = { TextButton(onClick = edit::close, enabled = !d.busy) { Text("Cancel") } },
    )
}
