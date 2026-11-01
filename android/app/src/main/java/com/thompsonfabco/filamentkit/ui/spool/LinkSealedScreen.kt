package com.thompsonfabco.filamentkit.ui.spool

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp

/** The link-to-sealed flow: search sealed spools, preview the link, confirm; or resolve a tag conflict. */
@Composable
fun LinkSealedScreen(state: SpoolUiState, vm: SpoolViewModel) {
    var query by remember { mutableStateOf("") }
    var gross by remember { mutableStateOf("") }
    val grossInvalid = gross.isNotBlank() && gross.trim().toDoubleOrNull() == null
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        when (state) {
            is SpoolUiState.LinkSearch -> {
                Text("Link to a sealed spool", style = MaterialTheme.typography.titleMedium)
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    label = { Text("Search (brand, name, colour)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = gross,
                    onValueChange = { gross = it },
                    label = { Text("Gross weight (g), optional") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    singleLine = true,
                    isError = grossInvalid,
                    supportingText = { if (grossInvalid) Text("Enter a number, or leave this empty") },
                    modifier = Modifier.fillMaxWidth(),
                )
                state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { vm.search(query) }) { Text(if (state.error != null) "Retry" else "Search") }
                    TextButton(onClick = vm::backToChoice) { Text("Back") }
                }
                if (state.searched && state.results.isEmpty()) Text("No sealed spools found.")
                state.results.forEach { spool ->
                    Column(
                        Modifier.fillMaxWidth()
                            .clickable(enabled = !grossInvalid) { vm.pick(spool.id, gross.trim().toDoubleOrNull()) }
                            .padding(vertical = 6.dp),
                    ) { SpoolSummaryRow(spool) }
                }
            }
            is SpoolUiState.LinkPreview -> {
                Text("Link this tag to:", style = MaterialTheme.typography.titleMedium)
                SpoolSummaryRow(state.spool)
                state.gross?.let { Text("Gross weight will be recorded as ${it.toInt()} g.") }
                state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = vm::confirmLink) { Text(if (state.error != null) "Retry" else "Confirm link") }
                    TextButton(onClick = vm::startLink) { Text("Back") }
                }
            }
            is SpoolUiState.Conflict -> {
                Text("Tag already in use", style = MaterialTheme.typography.titleMedium)
                Text(state.message)
                state.otherSpool?.let { SpoolSummaryRow(it) }
                state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = vm::moveTagHere) {
                        Text(
                            when (state.reason) {
                                ConflictReason.TagOnOtherSpool -> "Move tag here"
                                ConflictReason.SpoolHasOtherTag -> "Move tag here (replace its current tag)"
                            },
                        )
                    }
                    OutlinedButton(onClick = vm::backToChoice) { Text("Cancel") }
                }
            }
            else -> Unit
        }
    }
}
