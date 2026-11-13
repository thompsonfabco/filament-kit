package com.thompsonfabco.filamentkit.ui.printers

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleStartEffect
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.ui.pair.Mismatch
import com.thompsonfabco.filamentkit.ui.pair.PairTexts
import com.thompsonfabco.filamentkit.ui.pair.groupFingerprint

/** The printers the server knows; tapping a set-up printer opens it, an unset one asks for its Access Code. */
@Composable
fun PrintersScreen(viewModel: PrintersViewModel, onOpen: (id: String) -> Unit, onPairAgain: () -> Unit) {
    val state by viewModel.state.collectAsState()
    LifecycleStartEffect(viewModel) {
        viewModel.refresh()
        onStopOrDispose { }
    }
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Printers", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
            OutlinedButton(onClick = viewModel::refresh, enabled = !state.loading) { Text("Refresh") }
        }
        state.mismatch?.let { (expected, actual) ->
            MismatchNotice(expected, actual, onPairAgain)
            return@Column
        }
        if (state.unauthorized) {
            UnpairedNotice(onPairAgain)
            return@Column
        }
        state.message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (state.printers.isEmpty() && !state.loading && state.message == null) {
            Text("No printers found yet. The server finds Bambu printers on its network by itself; make sure the " +
                "printer is turned on, then tap Refresh. A Klipper printer is added by its address.")
            Button(onClick = viewModel::openAddKlipper) { Text("Add a Klipper printer") }
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(state.printers, key = { it.id }) { p ->
                PrinterRow(p) {
                    if (!p.configured || p.state == "wrong_code") viewModel.openAdd(p) else onOpen(p.id)
                }
            }
            if (state.printers.isNotEmpty()) item {
                OutlinedButton(onClick = viewModel::openAddKlipper) { Text("Add a Klipper printer") }
            }
        }
    }
    state.dialog?.let { AddPrinterDialog(it, viewModel) }
    state.klipper?.let { AddKlipperDialog(it, viewModel) }
}

@Composable
private fun PrinterRow(p: Printer, onClick: () -> Unit) {
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Spacer(Modifier.size(14.dp).clip(CircleShape).background(stateColor(p.state)))
            Column(Modifier.weight(1f)) {
                Text(p.name, style = MaterialTheme.typography.titleMedium)
                Text(listOfNotNull(p.shownModel, PrinterHelp.stateLabel(p.state)).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall)
                PrinterHelp.jobLine(p.summary)?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
                if (!p.configured) Text("Tap to add this printer", color = MaterialTheme.colorScheme.primary)
                else if (p.state == "wrong_code") Text("Tap to enter the Access Code again", color = MaterialTheme.colorScheme.primary)
            }
        }
    }
}


internal fun stateColor(state: String): Color = when (state) {
    "connected" -> Color(0xFF2E7D32)
    "wrong_code", "cert_changed" -> Color(0xFFC62828)
    "needs_developer_mode" -> Color(0xFFF9A825)
    else -> Color(0xFF9E9E9E)
}

/** Asks for the Access Code. The code lives only in this dialog's memory and goes straight to the server. */
@Composable
private fun AddPrinterDialog(d: AddDialog, viewModel: PrintersViewModel) {
    var code by remember(d.serial) { mutableStateOf("") }
    var name by remember(d.serial) { mutableStateOf(d.name) }
    AlertDialog(
        onDismissRequest = { if (!d.busy) viewModel.cancelAdd() },
        title = { Text("Add printer") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Serial: ${d.serial}", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(name, { name = it }, label = { Text("Name (optional)") }, singleLine = true,
                    enabled = !d.busy)
                OutlinedTextField(
                    value = code,
                    onValueChange = { code = it },
                    label = { Text("Access Code") },
                    singleLine = true,
                    enabled = !d.busy,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false),
                )
                Text(PrinterHelp.ACCESS_CODE_HELP, style = MaterialTheme.typography.bodySmall)
                if (d.busy) Text("Connecting to the printer…")
                d.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = {
            Button(onClick = { viewModel.submitAdd(code, name) }, enabled = !d.busy) { Text("Add") }
        },
        dismissButton = {
            TextButton(onClick = viewModel::cancelAdd, enabled = !d.busy) { Text("Cancel") }
        },
    )
}

/** Asks for a Klipper printer's name and the address of its Moonraker (the API key, if it needs one, is set later). */
@Composable
private fun AddKlipperDialog(d: KlipperDialog, viewModel: PrintersViewModel) {
    var name by remember { mutableStateOf("") }
    var host by remember { mutableStateOf("") }
    var port by remember { mutableStateOf(PrintersViewModel.DEFAULT_KLIPPER_PORT.toString()) }
    AlertDialog(
        onDismissRequest = { if (!d.busy) viewModel.cancelAddKlipper() },
        title = { Text("Add a Klipper printer") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text("Name (optional)") }, singleLine = true,
                    enabled = !d.busy)
                OutlinedTextField(host, { host = it }, label = { Text("Address") }, singleLine = true,
                    enabled = !d.busy, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, autoCorrectEnabled = false))
                OutlinedTextField(port, { port = it }, label = { Text("Port") }, singleLine = true, enabled = !d.busy,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                Text("The IP address or host name of the printer's Moonraker, and its port (usually 7125).",
                    style = MaterialTheme.typography.bodySmall)
                if (d.busy) Text("Connecting to the printer…")
                d.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = {
            Button(onClick = { viewModel.submitAddKlipper(host, port, name) }, enabled = !d.busy) { Text("Add") }
        },
        dismissButton = {
            TextButton(onClick = viewModel::cancelAddKlipper, enabled = !d.busy) { Text("Cancel") }
        },
    )
}

@Composable
internal fun MismatchNotice(expected: String, actual: String, onPairAgain: () -> Unit) {
    // the Pair screen's words and grouped fingerprint, for a saved pairing whose certificate changed
    val text = PairTexts.mismatch(Mismatch(expected, actual), host = "")
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(text.title, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.error)
        Text(text.body)
        Text(text.actualLabel)
        Text(groupFingerprint(actual), fontFamily = FontFamily.Monospace)
        text.whereToCheck?.let { Text(it) }
        Button(onClick = onPairAgain) { Text(text.button) }
    }
}

@Composable
internal fun UnpairedNotice(onPairAgain: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("This phone is no longer paired with the server.", color = MaterialTheme.colorScheme.error)
        Button(onClick = onPairAgain) { Text("Pair again") }
    }
}
