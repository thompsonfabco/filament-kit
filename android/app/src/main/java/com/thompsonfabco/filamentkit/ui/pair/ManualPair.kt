package com.thompsonfabco.filamentkit.ui.pair

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp

/** Manual pairing: address, then confirm the server's fingerprint, then the 6-digit code. */
@Composable
fun ManualPair(
    ui: PairUi,
    onSubmitAddress: (host: String, port: String) -> Unit,
    onConfirmFingerprint: () -> Unit,
    onRejectFingerprint: () -> Unit,
    onSubmitCode: (String) -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        when (ui.step) {
            Step.Address -> AddressStep(ui, onSubmitAddress, onBack)
            Step.Confirm -> ConfirmStep(ui, onConfirmFingerprint, onRejectFingerprint)
            Step.Code -> CodeStep(ui, onSubmitCode, onBack)
            else -> Unit
        }
        ui.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    }
}

@Composable
private fun AddressStep(ui: PairUi, onSubmit: (String, String) -> Unit, onBack: () -> Unit) {
    var host by rememberSaveable(ui.host) { mutableStateOf(ui.host) }
    var port by rememberSaveable(ui.port) { mutableStateOf(ui.port.toString()) }
    Text("Enter the server's address", style = MaterialTheme.typography.titleMedium)
    OutlinedTextField(
        value = host,
        onValueChange = { host = it },
        label = { Text("Host name or IP address") },
        singleLine = true,
        enabled = !ui.busy,
        modifier = Modifier.fillMaxWidth(),
    )
    OutlinedTextField(
        value = port,
        onValueChange = { port = it },
        label = { Text("Port") },
        singleLine = true,
        enabled = !ui.busy,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        modifier = Modifier.fillMaxWidth(),
    )
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = { onSubmit(host, port) }, enabled = !ui.busy) {
            Text(if (ui.busy) "Connecting..." else "Connect")
        }
        OutlinedButton(onClick = onBack, enabled = !ui.busy) { Text("Back") }
    }
}

@Composable
private fun ConfirmStep(ui: PairUi, onConfirm: () -> Unit, onReject: () -> Unit) {
    Text("Check the server's fingerprint", style = MaterialTheme.typography.titleMedium)
    Text(PairTexts.confirmIntro(ui.host))
    Text(groupFingerprint(ui.fingerprint.orEmpty()), fontFamily = FontFamily.Monospace)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = onConfirm) { Text("It matches") }
        OutlinedButton(onClick = onReject) { Text("It does not match") }
    }
}

@Composable
private fun CodeStep(ui: PairUi, onSubmit: (String) -> Unit, onBack: () -> Unit) {
    var code by remember { mutableStateOf("") } // not saved state: a secret, as the Access Code fields
    Text("Enter the pairing code", style = MaterialTheme.typography.titleMedium)
    Text(PairTexts.CODE_INTRO)
    OutlinedTextField(
        value = code,
        onValueChange = { code = it.filter(Char::isDigit).take(6) },
        label = { Text("6-digit code") },
        singleLine = true,
        enabled = !ui.busy,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
        modifier = Modifier.fillMaxWidth(),
    )
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = { onSubmit(code) }, enabled = !ui.busy) { Text(if (ui.busy) "Pairing..." else "Pair") }
        OutlinedButton(onClick = onBack, enabled = !ui.busy) { Text("Back") }
    }
}
