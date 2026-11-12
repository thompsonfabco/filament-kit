package com.thompsonfabco.filamentkit.ui.spool

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.ui.printers.MismatchNotice
import com.thompsonfabco.filamentkit.ui.printers.PrinterHelp
import com.thompsonfabco.filamentkit.ui.printers.UnpairedNotice

/** "Load into printer", shown in the spool card. [onDone] gets the flow's final state (to refresh the card). */
@Composable
fun LoadFlow(state: LoadUiState, vm: LoadViewModel, onDone: (LoadUiState.Done) -> Unit, onPairAgain: () -> Unit) {
    when (state) {
        LoadUiState.Closed -> Unit
        is LoadUiState.PickPrinter -> {
            Text("Load into which printer?", style = MaterialTheme.typography.titleMedium)
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            val list = state.printers
            when {
                list == null -> Text("Loading printers…")
                list.isEmpty() && state.error == null -> Text("No printers are set up yet. Add one on the Printers screen.")
                else -> list.forEach { p ->
                    OutlinedButton(onClick = { vm.pickPrinter(p) }, modifier = Modifier.fillMaxWidth()) {
                        Text(listOfNotNull(p.name, p.shownModel, PrinterHelp.stateLabel(p.state)).joinToString(" · "))
                    }
                }
            }
            TextButton(onClick = vm::close) { Text("Cancel") }
        }
        is LoadUiState.PickSlot -> {
            Text("Which slot on ${state.printer.name}?", style = MaterialTheme.typography.titleMedium)
            PrinterHelp.fix(state.printer.state)?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            val slots = state.slots
            when {
                slots == null -> Text("Loading slots…")
                state.busy -> Text("Checking…")
                slots.isEmpty() && state.error == null -> Text("The printer reports no AMS slots.")
                else -> slots.forEach { s ->
                    OutlinedButton(onClick = { vm.pickSlot(s.label) }, modifier = Modifier.fillMaxWidth()) {
                        Text(LoadHelp.slotLine(s, state.units))
                    }
                }
            }
            TextButton(onClick = vm::back) { Text("Back") }
        }
        is LoadUiState.Preview -> {
            Text("Load into ${state.printer.name}?", style = MaterialTheme.typography.titleMedium)
            state.lines.forEach { Text(it) }
            Text("This sets the slot on the printer and moves the spool there in the inventory.",
                style = MaterialTheme.typography.bodySmall)
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = vm::confirm, enabled = !state.busy) { Text(if (state.busy) "Loading…" else "Load") }
                TextButton(onClick = vm::back, enabled = !state.busy) { Text("Back") }
            }
        }
        is LoadUiState.Done -> {
            state.lines.forEachIndexed { i, line ->
                Text(line, style = if (i == 0) MaterialTheme.typography.titleMedium else MaterialTheme.typography.bodyMedium)
            }
            Button(onClick = { onDone(state) }) { Text("OK") }
        }
        LoadUiState.Unauthorized -> UnpairedNotice(onPairAgain)
        is LoadUiState.Mismatch -> MismatchNotice(state.expected, state.actual, onPairAgain)
    }
}
