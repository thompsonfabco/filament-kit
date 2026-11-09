package com.thompsonfabco.filamentkit.ui.printers

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleStartEffect

/**
 * "Map by loading filament": one named position at a time. The server says what to load; once the printer shows a
 * settled load it asks whether that is the one, answered with Yes, "No, I loaded …" or Skip. A dual-nozzle printer
 * that does not say the nozzle gets the question first. A printer that reports no loads gets the by-hand list.
 * Leaving while the session is open asks first, as an open session holds off automatic mapping.
 */
@Composable
fun ManualMapScreen(viewModel: ManualMapViewModel, printerName: String?, onBack: () -> Unit, onPairAgain: () -> Unit) {
    val s by viewModel.state.collectAsState()
    LifecycleStartEffect(viewModel) {
        viewModel.start()
        onStopOrDispose { viewModel.stop() }
    }
    val leave = { if (s.open) viewModel.askStop() else onBack() }
    BackHandler(onBack = leave)

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = leave) { Text("Back") }
            Column {
                Text(ManualMapHelp.TITLE, style = MaterialTheme.typography.headlineSmall)
                printerName?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
            }
        }
        s.mismatch?.let { (expected, actual) ->
            MismatchNotice(expected, actual, onPairAgain)
            return@Column
        }
        if (s.unauthorized) {
            UnpairedNotice(onPairAgain)
            return@Column
        }
        val m = s.map
        if (m == null) {
            if (s.busy) Text(ManualMapHelp.STARTING)
            s.message?.let {
                Text(it, color = MaterialTheme.colorScheme.error)
                OutlinedButton(onClick = viewModel::retry, enabled = !s.busy) { Text("Try again") }
            }
            return@Column
        }
        val step = m.step
        if (m.open && step != null) {
            Text(step.say, style = MaterialTheme.typography.titleMedium)
            val seen = step.seen
            when {
                s.byHand -> {
                    Text(ManualMapHelp.BY_HAND)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        m.choices.forEachIndexed { i, c ->
                            OutlinedButton(onClick = { viewModel.pickByHand(i) }, enabled = !s.busy) { Text(c.label) }
                        }
                    }
                    Text(ManualMapHelp.BY_HAND_NOTE, style = MaterialTheme.typography.bodySmall)
                }
                seen != null && seen.settled && step.ask != null -> {
                    Text(step.ask)
                    if (m.dualNozzle && !seen.nozzleReported) {
                        Text(ManualMapHelp.WHICH_NOZZLE)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            listOf("left", "right").forEach { n ->
                                FilterChip(selected = s.nozzle == n, onClick = { viewModel.chooseNozzle(n) },
                                    label = { Text(ManualMapHelp.nozzleLabel(n)) })
                            }
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = viewModel::yes, enabled = s.canAnswer) { Text("Yes") }
                        OutlinedButton(onClick = viewModel::openOther, enabled = s.canAnswer) { Text("No, I loaded…") }
                    }
                }
                seen != null -> {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                    Text(ManualMapHelp.SETTLING, style = MaterialTheme.typography.bodySmall)
                }
                else -> {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                    Text(ManualMapHelp.WAITING, style = MaterialTheme.typography.bodySmall)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = viewModel::skip, enabled = !s.busy) { Text("Skip ${step.position.label}") }
                TextButton(onClick = viewModel::askStop, enabled = !s.busy) { Text("Stop") }
            }
        }
        s.message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Text(m.summary, style = if (m.open) MaterialTheme.typography.bodySmall else MaterialTheme.typography.bodyLarge)
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            m.positions.forEach { Text(ManualMapHelp.line(it, m.open), style = MaterialTheme.typography.bodySmall) }
        }
        if (!m.open) {
            if (m.offerReport) {
                Text(ManualMapHelp.OFFER_QUESTION)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { viewModel.offer(true) }, enabled = !s.busy) { Text("Yes, how do I share it?") }
                    TextButton(onClick = { viewModel.offer(false) }, enabled = !s.busy) { Text("No thanks") }
                }
            }
            s.note?.let { Text(it) }
            Button(onClick = onBack) { Text("Done") }
        }
    }

    if (s.pickingOther) {
        val current = s.map?.step?.position?.id
        AlertDialog(
            onDismissRequest = viewModel::closeOther,
            title = { Text(ManualMapHelp.PICK_OTHER) },
            text = {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    s.map?.positions.orEmpty().filter { it.id != current }.forEach { p ->
                        OutlinedButton(onClick = { viewModel.loadedOther(p.id) }) { Text(p.label) }
                    }
                }
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = viewModel::closeOther) { Text("Cancel") } },
        )
    }
    if (s.confirmStop) {
        AlertDialog(
            onDismissRequest = viewModel::cancelStop,
            title = { Text(ManualMapHelp.STOP_TITLE) },
            text = { Text(ManualMapHelp.STOP_TEXT) },
            confirmButton = { Button(onClick = viewModel::confirmStop) { Text("Stop mapping") } },
            dismissButton = { TextButton(onClick = viewModel::cancelStop) { Text("Keep going") } },
        )
    }
}
