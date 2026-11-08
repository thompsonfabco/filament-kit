package com.thompsonfabco.filamentkit.ui.pair

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp

/** Manual pairing: address, then type two groups of the server's fingerprint, then the 6-digit code. */
@Composable
fun ManualPair(
    ui: PairUi,
    onSubmitAddress: (host: String, port: String) -> Unit,
    onConfirmFingerprint: (List<String>) -> Unit,
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
private fun ConfirmStep(ui: PairUi, onConfirm: (List<String>) -> Unit, onReject: () -> Unit) {
    val asked = ui.askedGroups
    var first by rememberSaveable(asked) { mutableStateOf("") }
    var second by rememberSaveable(asked) { mutableStateOf("") }
    val prompt = fingerprintPrompt(ui.fingerprint.orEmpty(), asked)
    Text("Check the server's fingerprint", style = MaterialTheme.typography.titleMedium)
    Text(PairTexts.confirmIntro(ui.host))
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        itemVerticalAlignment = Alignment.CenterVertically,
        maxItemsInEachRow = 4,
    ) {
        prompt.forEachIndexed { i, group ->
            when {
                group != null -> Text(group, fontFamily = FontFamily.Monospace, modifier = Modifier.width(GROUP_WIDTH))
                i == asked.first() -> GroupField(first, { first = it }, i, prompt.size)
                else -> GroupField(second, { second = it }, i, prompt.size)
            }
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = { onConfirm(listOf(first, second)) }, enabled = first.length == 4 && second.length == 4) {
            Text("Continue")
        }
        OutlinedButton(onClick = onReject) { Text("It does not match") }
    }
}

private val GROUP_WIDTH = 64.dp

/** One missing group: four hex digits, in its place among the others so it can be found by its neighbours. */
@Composable
private fun GroupField(value: String, onChange: (String) -> Unit, index: Int, count: Int) {
    val colors = MaterialTheme.colorScheme
    BasicTextField(
        value = value,
        onValueChange = { typed -> onChange(typed.lowercase().filter { it in "0123456789abcdef" }.take(4)) },
        singleLine = true,
        textStyle = TextStyle(fontFamily = FontFamily.Monospace, fontSize = MaterialTheme.typography.bodyLarge.fontSize, color = colors.onSurface),
        cursorBrush = SolidColor(colors.primary),
        keyboardOptions = KeyboardOptions(
            capitalization = KeyboardCapitalization.None,
            autoCorrectEnabled = false,
            keyboardType = KeyboardType.Ascii,
            imeAction = ImeAction.Next,
        ),
        modifier = Modifier
            .width(GROUP_WIDTH)
            .border(1.dp, colors.primary, MaterialTheme.shapes.extraSmall)
            .padding(horizontal = 6.dp, vertical = 8.dp)
            .semantics { contentDescription = "Missing group ${index + 1} of $count" },
    )
}

@Composable
private fun CodeStep(ui: PairUi, onSubmit: (String) -> Unit, onBack: () -> Unit) {
    var code by rememberSaveable { mutableStateOf("") }
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
