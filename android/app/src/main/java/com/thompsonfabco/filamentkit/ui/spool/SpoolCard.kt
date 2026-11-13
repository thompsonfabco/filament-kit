package com.thompsonfabco.filamentkit.ui.spool

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.parseWeight
import com.thompsonfabco.filamentkit.ui.printers.MismatchNotice
import com.thompsonfabco.filamentkit.ui.printers.UnpairedNotice
import com.thompsonfabco.filamentkit.ui.weightHint

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
    loadVm: LoadViewModel? = null,
) {
    val state by viewModel.state.collectAsState()
    val loadState = loadVm?.state?.collectAsState()?.value ?: LoadUiState.Closed
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        val s0 = state
        if (loadVm != null && loadState != LoadUiState.Closed && s0 is SpoolUiState.Card) {
            LoadFlow(
                state = loadState,
                vm = loadVm,
                onDone = { done ->
                    loadVm.close()
                    done.spoolJson?.let(viewModel::open)
                },
                onPairAgain = onPairAgain,
            )
            return@Column
        }
        when (val s = state) {
            SpoolUiState.Idle -> Unit
            SpoolUiState.Loading -> Text("Looking up tag…")
            is SpoolUiState.Card -> SpoolCard(s, viewModel, onClose, onLoad = loadVm?.let { vm -> { vm.start(s.spool) } })
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
            SpoolUiState.Unauthorized -> UnpairedNotice(onPairAgain)
            is SpoolUiState.Mismatch -> MismatchNotice(s.expected, s.actual, onPairAgain)
        }
    }
}

@Composable
fun SpoolSummaryRow(spool: SpoolSummary) {
    Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        ColorSwatch(spool.colorHex, 32.dp)
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

@Composable
private fun SpoolCard(card: SpoolUiState.Card, vm: SpoolViewModel, onClose: () -> Unit, onLoad: (() -> Unit)?) {
    var gross by remember(card.rev) { mutableStateOf("") }
    SpoolSummaryRow(card.spool)
    card.message?.let { Text(it, color = MaterialTheme.colorScheme.primary) }

    OutlinedTextField(
        value = gross,
        onValueChange = { gross = it },
        label = { Text("Gross weight (g)") },
        supportingText = weightHint(gross)?.let { hint -> { Text(hint) } },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
    )
    SpoolActions(
        canUpdate = parseWeight(gross) != null,
        onUpdate = { parseWeight(gross)?.let(vm::previewWeight) },
        onMove = vm::openMove,
        onMarkEmpty = vm::askMarkEmpty,
    )
    onLoad?.let { Button(onClick = it, modifier = Modifier.fillMaxWidth()) { Text("Load into printer") } }

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

/**
 * The card's three actions. They wrap onto a second line when the card is narrow (small phones, large font) and each
 * label stays on one line.
 */
@Composable
internal fun SpoolActions(canUpdate: Boolean, onUpdate: () -> Unit, onMove: () -> Unit, onMarkEmpty: () -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Button(onClick = onUpdate, enabled = canUpdate) { OneLine("Update weight") }
        OutlinedButton(onClick = onMove) { OneLine("Move") }
        OutlinedButton(onClick = onMarkEmpty) { OneLine("Mark empty") }
    }
}

@Composable
private fun OneLine(text: String) = Text(text, maxLines = 1, softWrap = false)

@Composable
private fun UnknownTagChoice(onLink: () -> Unit, onAddNew: () -> Unit, onClose: () -> Unit) {
    Text("This tag is not linked to a spool yet.", style = MaterialTheme.typography.titleMedium)
    Button(onClick = onLink, modifier = Modifier.fillMaxWidth()) { Text("Link to a sealed spool") }
    OutlinedButton(onClick = onAddNew, modifier = Modifier.fillMaxWidth()) { Text("Add as new") }
    TextButton(onClick = onClose) { Text("Cancel") }
}
