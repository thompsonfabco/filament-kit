package com.thompsonfabco.filamentkit.ui.spool

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.ui.parseWeight

/**
 * Everything shown after a tag tap. [onStartAdd] receives the tag when the user chooses "Add as new"
 * (Task 7's flow); [onPairAgain] is for a certificate mismatch.
 */
@Composable
fun SpoolHost(
    viewModel: SpoolViewModel,
    onStartAdd: (tag: String?) -> Unit,
    onPairAgain: () -> Unit,
    onClose: () -> Unit,
) {
    val state by viewModel.state.collectAsState()
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        when (val s = state) {
            SpoolUiState.Idle -> Unit
            SpoolUiState.Loading -> Text("Looking up tag…")
            is SpoolUiState.Card -> SpoolCard(s, viewModel, onClose)
            is SpoolUiState.UnknownTag -> UnknownTagChoice(
                onLink = viewModel::startLink,
                onAddNew = { onStartAdd(s.tag) },
                onClose = onClose,
            )
            is SpoolUiState.LinkSearch, is SpoolUiState.LinkPreview, is SpoolUiState.Conflict ->
                LinkSealedScreen(s, viewModel)
            is SpoolUiState.Failed -> {
                Text(s.message, color = MaterialTheme.colorScheme.error)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    s.retryTag?.let { t -> Button(onClick = { viewModel.onTag(t) }) { Text("Try again") } }
                    OutlinedButton(onClick = onClose) { Text("Close") }
                }
            }
            SpoolUiState.Unauthorized -> {
                Text("This phone is no longer paired with the server.", color = MaterialTheme.colorScheme.error)
                Button(onClick = onPairAgain) { Text("Pair again") }
            }
            is SpoolUiState.Mismatch -> {
                Text("The server's certificate changed.", style = MaterialTheme.typography.titleMedium)
                Text("Expected: ${s.expected}")
                Text("Got: ${s.actual}")
                Button(onClick = onPairAgain) { Text("Pair again") }
            }
        }
    }
}

@Composable
fun SpoolSummaryRow(spool: SpoolSummary) {
    Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Spacer(
            Modifier.size(32.dp).clip(CircleShape).background(parseHex(spool.colorHex)),
        )
        Column {
            Text("${spool.brand} ${spool.name}".trim(), style = MaterialTheme.typography.titleMedium)
            Text(
                listOfNotNull(
                    spool.material.ifBlank { null },
                    spool.location?.let { "Location: $it" },
                    spool.remaining?.let { "${it.toInt()} g left" },
                ).joinToString(" · "),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

private fun parseHex(hex: String?): Color {
    val clean = hex?.removePrefix("#")?.trim().orEmpty()
    val rgb = clean.takeIf { it.length == 6 }?.toLongOrNull(16) ?: return Color.Gray
    return Color(0xFF000000 or rgb)
}

@Composable
private fun SpoolCard(card: SpoolUiState.Card, vm: SpoolViewModel, onClose: () -> Unit) {
    var gross by remember(card.rev) { mutableStateOf("") }
    SpoolSummaryRow(card.spool)
    card.message?.let { Text(it, color = MaterialTheme.colorScheme.primary) }

    OutlinedTextField(
        value = gross,
        onValueChange = { gross = it },
        label = { Text("Gross weight (g)") },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
    )
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(
            onClick = { parseWeight(gross)?.let(vm::previewWeight) },
            enabled = parseWeight(gross) != null,
        ) { Text("Update weight") }
        OutlinedButton(onClick = vm::openMove) { Text("Move") }
        OutlinedButton(onClick = vm::askMarkEmpty) { Text("Mark empty") }
    }

    card.weightPreview?.let { p ->
        Text(
            "Remaining would change from ${card.spool.remaining?.toInt() ?: "?"} g to ${p.remaining?.toInt() ?: "?"} g.",
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = vm::confirmWeight) { Text("Confirm") }
            TextButton(onClick = vm::cancelWeight) { Text("Cancel") }
        }
    }

    card.locations?.let { locations ->
        Text("Move to", style = MaterialTheme.typography.titleSmall)
        locations.forEach { loc ->
            TextButton(onClick = { vm.move(loc) }, modifier = Modifier.fillMaxWidth()) { Text(loc) }
        }
        TextButton(onClick = vm::closeMove) { Text("Cancel") }
    }

    if (card.confirmEmpty) {
        AlertDialog(
            onDismissRequest = vm::cancelEmpty,
            title = { Text("Mark empty?") },
            text = { Text("${card.spool.brand} ${card.spool.name} will be marked as used up.") },
            confirmButton = { TextButton(onClick = vm::confirmEmpty) { Text("Mark empty") } },
            dismissButton = { TextButton(onClick = vm::cancelEmpty) { Text("Cancel") } },
        )
    }
    Spacer(Modifier.height(4.dp))
    TextButton(onClick = onClose) { Text("Done") }
}

@Composable
private fun UnknownTagChoice(onLink: () -> Unit, onAddNew: () -> Unit, onClose: () -> Unit) {
    Text("This tag is not linked to a spool yet.", style = MaterialTheme.typography.titleMedium)
    Button(onClick = onLink, modifier = Modifier.fillMaxWidth()) { Text("Link to a sealed spool") }
    OutlinedButton(onClick = onAddNew, modifier = Modifier.fillMaxWidth()) { Text("Add as new") }
    TextButton(onClick = onClose) { Text("Cancel") }
}
