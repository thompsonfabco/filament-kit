package com.thompsonfabco.filamentkit.ui.printers

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.currentStateAsState
import com.thompsonfabco.filamentkit.net.AmsSlot
import com.thompsonfabco.filamentkit.net.AmsUnit
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterStatus
import com.thompsonfabco.filamentkit.net.Temp
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import okhttp3.OkHttpClient
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import kotlin.math.roundToInt

/** Where the camera streams come from: the app's pinned client, the stream URLs and the Bearer header. */
class CameraSource(
    val client: OkHttpClient,
    val hlsUrl: String,
    val mjpegUrl: String,
    val headers: Map<String, String>,
)

/**
 * One printer: camera on top, live status below (polled every 2 s only while this screen is visible), controls.
 * The camera is shown only while the screen is started, so the stream is closed when the app goes to the background.
 */
@Composable
fun PrinterScreen(
    viewModel: PrinterViewModel,
    tools: PrinterToolsViewModel,
    camera: CameraSource,
    onBack: () -> Unit,
    onPairAgain: () -> Unit,
) {
    val state by viewModel.state.collectAsState()
    val toolsState by tools.state.collectAsState()
    LifecycleStartEffect(viewModel, tools) {
        viewModel.start()
        tools.start()
        onStopOrDispose {
            viewModel.stop()
            tools.stop()
        }
    }
    val lifecycle by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
    val visible = lifecycle.isAtLeast(Lifecycle.State.STARTED)

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onBack) { Text("Back") }
            Text(state.printer?.name ?: "Printer", style = MaterialTheme.typography.headlineSmall)
        }
        (state.mismatch ?: toolsState.mismatch)?.let { (expected, actual) ->
            MismatchNotice(expected, actual, onPairAgain)
            return@Column
        }
        if (state.unauthorized || toolsState.unauthorized) {
            UnpairedNotice(onPairAgain)
            return@Column
        }
        val printer = state.printer
        if (printer == null) {
            Text(state.message ?: "Loading…", color = if (state.message != null) MaterialTheme.colorScheme.error else Color.Unspecified)
            return@Column
        }

        CameraBox(printer, camera, visible)

        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Spacer(Modifier.size(12.dp).clip(CircleShape).background(stateColor(printer.state)))
            Text(listOfNotNull(printer.shownModel, PrinterHelp.stateLabel(printer.state)).joinToString(" · "))
        }
        PrinterHelp.fix(printer.state)?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        state.message?.let { Text(it, color = MaterialTheme.colorScheme.error) }

        val status = state.status
        if (status == null) {
            Text("No live status from the printer yet.")
        } else {
            StatusBlock(status, state, viewModel)
        }

        Controls(state, viewModel)

        SlotMapping(toolsState, tools, printer.state, state.printing)
        FilamentUsed(toolsState, tools)
    }

    if (toolsState.confirmMap) {
        AlertDialog(
            onDismissRequest = tools::cancelMap,
            title = { Text("Map slots?") },
            text = {
                Text("This briefly changes each AMS slot's colour on the printer, one slot at a time, and runs a " +
                    "short job that does not heat or move anything. Every slot is set back afterwards. The printer " +
                    "must be idle.")
            },
            confirmButton = { Button(onClick = tools::confirmMap) { Text("Map slots") } },
            dismissButton = { TextButton(onClick = tools::cancelMap) { Text("Cancel") } },
        )
    }
    state.unloadAsk?.let { ask ->
        AlertDialog(
            onDismissRequest = viewModel::cancelUnload,
            title = { Text("Unload?") },
            text = {
                Text(ask.question + " Only the inventory changes; the printer's slot setting stays as it is.")
            },
            confirmButton = { Button(onClick = viewModel::confirmUnload) { Text("Unload") } },
            dismissButton = { TextButton(onClick = viewModel::cancelUnload) { Text("Cancel") } },
        )
    }
    toolsState.undoTarget?.let { e ->
        AlertDialog(
            onDismissRequest = tools::cancelUndo,
            title = { Text("Undo this?") },
            text = { Text("${UsageHelp.line(e)} goes back onto the spool.") },
            confirmButton = { Button(onClick = tools::confirmUndo) { Text("Undo") } },
            dismissButton = { TextButton(onClick = tools::cancelUndo) { Text("Keep") } },
        )
    }

    when (state.stopStep) {
        StopStep.None -> Unit
        StopStep.First -> AlertDialog(
            onDismissRequest = viewModel::cancelStop,
            title = { Text("Stop the print?") },
            text = { Text("Stopping ends the print. It cannot be resumed.") },
            confirmButton = { Button(onClick = viewModel::confirmStop) { Text("Stop") } },
            dismissButton = { TextButton(onClick = viewModel::cancelStop) { Text("Keep printing") } },
        )
        StopStep.Second -> AlertDialog(
            onDismissRequest = viewModel::cancelStop,
            title = { Text("Are you sure?") },
            text = { Text(state.stopQuestion.orEmpty()) },
            confirmButton = {
                Button(
                    onClick = viewModel::confirmStop,
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                ) { Text("Yes, stop it") }
            },
            dismissButton = { TextButton(onClick = viewModel::cancelStop) { Text("Keep printing") } },
        )
    }
}

@Composable
private fun CameraBox(printer: Printer, camera: CameraSource, visible: Boolean) {
    val box = Modifier.fillMaxWidth().aspectRatio(16f / 9f).background(Color.Black)
    when {
        !printer.configured -> Unit
        printer.camera.kind == null -> Text("The app cannot show this printer model's camera.")
        !visible -> Box(box)
        printer.camera.kind == "hls" -> HlsPlayer(camera.client, camera.hlsUrl, camera.headers, box)
        printer.camera.kind == "mjpeg" -> MjpegView(camera.client, camera.mjpegUrl, camera.headers, box)
        else -> Text("The app cannot show this printer model's camera.")
    }
}

@Composable
private fun StatusBlock(s: PrinterStatus, state: PrinterUiState, viewModel: PrinterViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        val headline = listOf(s.stage.ifBlank { stateWord(s.gcodeState) }, s.job).filter { it.isNotBlank() }
        Text(headline.joinToString(" · "), style = MaterialTheme.typography.titleMedium)
        if (PrinterHelp.isPrinting(s.gcodeState)) {
            LinearProgressIndicator(progress = { s.percent / 100f }, modifier = Modifier.fillMaxWidth())
            Text(listOfNotNull(
                "${s.percent}%",
                if (s.layer != null && s.totalLayers != null) "layer ${s.layer} of ${s.totalLayers}" else null,
                if (s.remainingMin > 0) "${PrinterHelp.formatMinutes(s.remainingMin)} left" else null,
                s.eta?.let { formatEta(it) }?.let { "done about $it" },
            ).joinToString(" · "))
        }
        val t = s.temps
        Text(buildList {
            t.nozzle.forEachIndexed { i, n -> add((if (t.nozzle.size > 1) "Nozzle ${i + 1}" else "Nozzle") + " ${temp(n)}") }
            t.bed?.let { add("Bed ${temp(it)}") }
            t.chamber?.let { add("Chamber ${temp(it)}") }
        }.joinToString(" · "), style = MaterialTheme.typography.bodyMedium)
        s.ams.forEach { AmsBlock(it, state.slotBusy, onUnload = viewModel::askUnload) }
        state.slotMessage.forEach { Text(it) }
        s.hms.forEach { Text(it.text.ifBlank { "Printer alert ${it.code}" }, color = MaterialTheme.colorScheme.error) }
    }
}

@Composable
/** One AMS unit (or the external holder); a slot holding an inventory spool offers Unload. */
private fun AmsBlock(u: AmsUnit, busy: String?, onUnload: (AmsSlot) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(PrinterHelp.unitTitle(u), style = MaterialTheme.typography.titleSmall)
        u.slots.forEach { slot ->
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val empty = PrinterHelp.slotEmpty(slot)
                ColorSwatch(slot.colorHex, 16.dp, empty = empty)
                val spool = slot.spool
                Text(listOfNotNull(
                    slot.label,
                    if (empty) "empty" else slot.type.ifBlank { null },
                    spool?.name?.ifBlank { null },
                    spool?.remainingWeight?.let { "${it.toInt()} g left" },
                    if (slot.active) "in use" else null,
                ).joinToString(" · "), style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                if (spool != null) {
                    TextButton(onClick = { onUnload(slot) }, enabled = busy == null) {
                        Text(if (busy == slot.label) "Checking…" else "Unload")
                    }
                }
            }
        }
    }
}

@Composable
private fun Controls(state: PrinterUiState, viewModel: PrinterViewModel) {
    val can = state.controlsEnabled
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = viewModel::pauseOrResume, enabled = can && state.printing) {
            Text(if (state.paused) "Resume" else "Pause")
        }
        OutlinedButton(onClick = viewModel::askStop, enabled = can && state.printing) { Text("Stop") }
        OutlinedButton(onClick = viewModel::toggleLight, enabled = can && state.status?.light != null) {
            Text(if (state.lightOn) "Light off" else "Light on")
        }
    }
    if (state.commandBusy) Text("Waiting for the printer…")
    state.commandMessage?.let { Text(it) }
}

@Composable
private fun SlotMapping(s: ToolsUiState, tools: PrinterToolsViewModel, printerState: String, printing: Boolean) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("Slot mapping", style = MaterialTheme.typography.titleMedium)
        val v = SlotMapHelp.view(s.map)
        if (v.outcome == SlotMapOutcome.RUNNING) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        v.headline?.let {
            if (v.headlineIsError) Text(it, color = MaterialTheme.colorScheme.error) else Text(it)
        }
        v.detail?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
        if (!v.saysObserve) s.observeNotice?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
        v.problemsHeading?.let { heading ->
            Text(heading, style = MaterialTheme.typography.labelLarge)
            val color = if (v.problemsAreError) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant
            v.problems.forEach { Text(it, color = color, style = MaterialTheme.typography.bodySmall) }
        }
        v.notesHeading?.let { heading ->
            Text(heading, style = MaterialTheme.typography.labelLarge)
            v.notes.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
        }
        s.mapMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        val enabled = s.mapEnabled(SlotMapHelp.canStart(printerState, printing))
        // the step the server's reason calls for is the filled button
        if (v.action == MapAction.RETRY) {
            Button(onClick = tools::askMap, enabled = enabled) { Text(SlotMapHelp.buttonLabel(s.map)) }
        } else {
            OutlinedButton(onClick = tools::askMap, enabled = enabled) { Text(SlotMapHelp.buttonLabel(s.map)) }
        }
        SlotMapHelp.blockedReason(printerState, printing)?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
    }
}

@Composable
private fun FilamentUsed(s: ToolsUiState, tools: PrinterToolsViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("Filament used (last 7 days)", style = MaterialTheme.typography.titleMedium)
        s.usageMessage?.let { Text(it) }
        if (s.usageLoaded && s.usage.isEmpty()) Text("Nothing logged.")
        s.usage.forEach { e ->
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Column(Modifier.weight(1f)) {
                    Text(UsageHelp.line(e), style = MaterialTheme.typography.bodyMedium)
                    Text(listOfNotNull(formatWhen(e.at), UsageHelp.note(e)).joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall)
                }
                if (UsageHelp.canUndo(e)) {
                    TextButton(onClick = { tools.askUndo(e) }, enabled = !s.undoBusy) { Text("Undo") }
                }
            }
        }
    }
}

private fun formatWhen(iso: String): String? = try {
    OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault())
        .format(DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT))
} catch (_: Exception) {
    iso.ifBlank { null }
}

private fun stateWord(gcode: String) = when (gcode) {
    "IDLE" -> "Idle"
    "FINISH" -> "Finished"
    "FAILED" -> "Print failed"
    "RUNNING" -> "Printing"
    "PAUSE" -> "Paused"
    "PREPARE" -> "Preparing"
    "SLICING" -> "Slicing"
    else -> ""
}

private fun temp(t: Temp): String {
    val cur = t.current?.let { "${it.roundToInt()}°C" } ?: "–"
    val target = t.target?.roundToInt()
    return if (target != null && target > 0) "$cur → $target°C" else cur
}

private fun formatEta(iso: String): String? = try {
    OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault())
        .format(DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT))
} catch (_: Exception) {
    null
}
