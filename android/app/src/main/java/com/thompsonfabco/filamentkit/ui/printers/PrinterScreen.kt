package com.thompsonfabco.filamentkit.ui.printers

import android.app.Activity
import android.content.pm.ActivityInfo
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.currentStateAsState
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.AmsSlot
import com.thompsonfabco.filamentkit.net.AmsUnit
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterStatus
import com.thompsonfabco.filamentkit.net.SlotSpool
import com.thompsonfabco.filamentkit.net.Temp
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.ScreenState
import com.thompsonfabco.filamentkit.ui.components.ScreenTopBarActions
import com.thompsonfabco.filamentkit.ui.components.StatusLabel
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwDialog
import com.thompsonfabco.filamentkit.ui.components.SwDialogButton
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwIconButton
import com.thompsonfabco.filamentkit.ui.components.SwMenu
import com.thompsonfabco.filamentkit.ui.components.SwMenuItem
import com.thompsonfabco.filamentkit.ui.components.SwProgress
import com.thompsonfabco.filamentkit.ui.components.SwSheet
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.delay
import okhttp3.OkHttpClient
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import kotlin.math.roundToInt

/** How long the answer to a command stays under the controls. */
private const val COMMAND_MESSAGE_MS = 6_000L

/** Where the camera streams come from: the app's pinned client, the stream URLs and the Bearer header. */
class CameraSource(
    val client: OkHttpClient,
    val hlsUrl: String,
    val mjpegUrl: String,
    val headers: Map<String, String>,
)

/**
 * One printer (05-android-app 9.4 to 9.10): the status and its controls, the camera, the slots, the slot mapping and
 * the filament used, in one scrolling column. Status is polled every 2 s only while this screen is visible, and the
 * camera is shown only while it is started, so the stream is closed when the app goes to the background. The
 * printer's name is the top bar's title (the shell reads it from [PrinterTitles]).
 */
@Composable
fun PrinterScreen(
    viewModel: PrinterViewModel,
    tools: PrinterToolsViewModel,
    camera: CameraSource,
    onPairAgain: () -> Unit,
    onOpenSettings: () -> Unit = {},
    onMapByLoading: () -> Unit = {},
    /** The slot's label: opens "Pick a spool for a slot" (9.6). */
    onPickSlot: (String) -> Unit = {},
    /** The spool a slot holds: opens it (7.2). */
    onOpenSpool: (SlotSpool) -> Unit = {},
    /** The camera panel's Hide / Show, remembered per printer on this phone. */
    cameraShown: Boolean = true,
    onCameraShown: (Boolean) -> Unit = {},
) {
    val state by viewModel.state.collectAsState()
    val toolsState by tools.state.collectAsState()
    LifecycleStartEffect(viewModel, tools) {
        viewModel.onHubOk = tools::clearHubNotice
        tools.onHubOk = viewModel::clearHubNotice
        viewModel.start()
        tools.start()
        onStopOrDispose {
            viewModel.stop()
            tools.stop()
        }
    }
    val lifecycle by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
    val visible = lifecycle.isAtLeast(Lifecycle.State.STARTED)
    val context = LocalContext.current

    // the printer's name is the top bar's title
    val name = state.printer?.name
    LaunchedEffect(name) { if (name != null) PrinterTitles.known(viewModel.printerId, name) }

    // a print that ends while the screen is open: the "Filament used" list (fetched once) picks up its entry
    var wasPrinting by remember { mutableStateOf(false) }
    LaunchedEffect(state.printing) {
        if (wasPrinting && !state.printing) tools.refreshUsage()
        wasPrinting = state.printing
    }
    // the answer to a command (Pause, Stop ...) would otherwise stay until the next one
    LaunchedEffect(state.commandNote) {
        if (state.commandNote != null) {
            delay(COMMAND_MESSAGE_MS)
            viewModel.dismissCommandMessage()
        }
    }
    // a fetched report goes straight to the share sheet
    val pending = toolsState.report
    val subject = stringResource(R.string.printer_report_subject)
    LaunchedEffect(pending) {
        if (pending != null) {
            tools.reportShown(
                when (shareReport(context, pending, subject)) {
                    ShareOutcome.Opened -> null
                    ShareOutcome.NoApp -> Say.Words(R.string.printer_report_no_app)
                    ShareOutcome.NotWritten -> Say.Words(R.string.common_hub_answer_unknown)
                },
            )
        }
    }
    // the slot sheet closes when the unload question opens
    var sheetSlot by rememberSaveable { mutableStateOf<String?>(null) }
    LaunchedEffect(state.unloadAsk) { if (state.unloadAsk != null) sheetSlot = null }

    ScreenTopBarActions {
        Overflow(
            onSettings = onOpenSettings,
            onReport = tools::collectReport,
            onRefresh = { viewModel.retry(); tools.refreshUsage() },
            reportEnabled = !toolsState.reportBusy && state.printer?.family != "klipper",
        )
    }

    val space = SpoolwardenTheme.space
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(space.s4),
        verticalArrangement = Arrangement.spacedBy(space.s3),
    ) {
        HubNotices(
            unauthorized = state.unauthorized || toolsState.unauthorized,
            mismatch = state.mismatch != null || toolsState.mismatch != null,
            onPairAgain = onPairAgain,
        )
        val printer = state.printer
        ScreenState(
            loaded = printer != null,
            loading = printer == null && state.problem == null,
            error = state.problem?.let { problemText(it) },
            onTryAgain = viewModel::retry,
            offline = false,
        ) {
            if (printer == null) return@ScreenState
            StatusPanel(printer, state, viewModel)
            CameraPanel(printer, camera, visible, cameraShown, onCameraShown, onPairAgain)
            SlotsPanel(printer, state, onSlot = { sheetSlot = it.label })
            MappingPanel(printer, state, toolsState, tools, onMapByLoading)
            UsagePanel(toolsState, tools)
            SettingsRow(onOpenSettings)
        }
    }

    // dialogs and sheets
    val printer = state.printer
    if (printer != null) {
        if (state.confirmStop) StopDialog(printer, state, viewModel)
        if (toolsState.confirmMap) MapDialog(printer, toolsState, tools)
        state.unloadAsk?.let { UnloadDialog(it, state, viewModel) }
        toolsState.undoTarget?.let { UndoDialog(it, toolsState, tools) }
        sheetSlot?.let { label ->
            val slot = state.status?.ams.orEmpty().flatMap { it.slots }.firstOrNull { it.label == label }
            if (slot == null) sheetSlot = null else SlotSheet(
                slot, printer, state,
                onDismiss = { sheetSlot = null },
                onUnload = { viewModel.askUnload(slot) },
                onLoad = { sheetSlot = null; onPickSlot(slot.label) },
                onOpenSpool = { sp -> sheetSlot = null; onOpenSpool(sp) },
            )
        }
    }
}

@Composable
private fun Overflow(onSettings: () -> Unit, onReport: () -> Unit, onRefresh: () -> Unit, reportEnabled: Boolean) {
    var open by remember { mutableStateOf(false) }
    Box {
        SwIconButton(R.drawable.sw_ic_more, stringResource(R.string.common_more_actions), { open = true })
        SwMenu(open, { open = false }) {
            SwMenuItem(stringResource(R.string.printer_settings_title), { open = false; onSettings() }, icon = R.drawable.sw_ic_settings)
            SwMenuItem(
                stringResource(R.string.printers_collect_report), { open = false; onReport() }, icon = R.drawable.sw_ic_download,
                enabled = reportEnabled,
            )
            SwMenuItem(stringResource(R.string.common_refresh), { open = false; onRefresh() }, icon = R.drawable.sw_ic_refresh)
        }
    }
}

// --- status ---

/** The panel under the top bar: the state, the progress of a print, temperatures, alerts and the controls. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun StatusPanel(printer: Printer, state: PrinterUiState, viewModel: PrinterViewModel) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val status = state.status
    PrinterPanel(title = null) {
        val kind = statusKind(printer.state)
        if (printer.state == "connected" && status != null) {
            val word = jobWord(status.gcodeState)
            val text = when {
                word == null -> stringResource(R.string.status_connected)
                status.job.isBlank() -> stringResource(word.word)
                else -> stringResource(R.string.printer_state_job, stringResource(word.word), status.job)
            }
            ShapeWords(R.drawable.sw_st_filled, colors.ok, false, text)
        } else {
            StatusLabel(kind)
            fixLine(printer.state)?.let { Text(stringResource(it), color = kind.colour(colors), style = MaterialTheme.typography.bodyMedium) }
        }
        if (status == null) {
            if (printer.state == "connected") Text(stringResource(R.string.printer_no_status), style = MaterialTheme.typography.bodyMedium)
            return@PrinterPanel
        }
        if (PrinterHelp.isPrinting(status.gcodeState)) PrintProgress(status)
        Text(temperatures(status), style = SpoolwardenTheme.type.data)
        status.hms.forEach { alert ->
            NoticeCard(
                NoticeKind.Bad,
                alert.text.ifBlank { stringResource(R.string.printer_alert_code, alert.code) },
            )
        }
        Controls(printer, state, viewModel)
    }
}

@Composable
private fun PrintProgress(s: PrinterStatus) {
    val space = SpoolwardenTheme.space
    val clock = s.eta?.let { formatClock(it) }
    val parts = listOfNotNull(
        if (s.layer != null && s.totalLayers != null) stringResource(R.string.printer_progress_layer, s.layer, s.totalLayers) else null,
        if (s.remainingMin > 0) stringResource(R.string.printer_progress_left, timeLeft(s.remainingMin)) else null,
        clock?.let { stringResource(R.string.printer_progress_done, it) },
    )
    val spoken = if (s.layer != null && s.totalLayers != null && s.remainingMin > 0) {
        stringResource(
            R.string.a11y_printer_progress, s.stage.ifBlank { stringResource(R.string.printer_job_printing) }, s.job,
            s.percent, s.layer, s.totalLayers, timeLeft(s.remainingMin),
        )
    } else {
        null
    }
    val percent = stringResource(R.string.printer_percent, s.percent)
    Column(
        Modifier.semantics(mergeDescendants = true) { if (spoken != null) contentDescription = spoken },
        verticalArrangement = Arrangement.spacedBy(space.s1),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.CenterVertically) {
            SwProgress(s.percent / PERCENT, Modifier.weight(1f))
            Text(percent, style = SpoolwardenTheme.type.data)
        }
        if (parts.isNotEmpty()) Text(parts.joinToString(SEPARATOR), style = SpoolwardenTheme.type.dataSmall)
    }
}

private const val PERCENT = 100f
private const val SEPARATOR = " · "

@Composable
private fun timeLeft(minutes: Int): String {
    val (hours, rest) = hoursAndMinutes(minutes)
    return if (hours > 0) stringResource(R.string.printer_time_hours, hours, rest) else stringResource(R.string.printer_time_minutes, rest)
}

@Composable
private fun temperatures(s: PrinterStatus): String {
    val t = s.temps
    val parts = buildList {
        t.nozzle.forEachIndexed { i, n ->
            add(
                if (t.nozzle.size > 1) stringResource(R.string.printer_temp_nozzle_n, i + 1, degrees(n.current), degrees(n.target))
                else stringResource(R.string.printer_temp_nozzle, degrees(n.current), degrees(n.target)),
            )
        }
        t.bed?.let { add(stringResource(R.string.printer_temp_bed, degrees(it.current), degrees(it.target))) }
        t.chamber?.let { add(stringResource(R.string.printer_temp_chamber, degrees(it.current))) }
    }
    return parts.joinToString(SEPARATOR)
}

/** A temperature in whole degrees; a dash when the printer does not say. */
internal fun degrees(value: Double?): String = value?.roundToInt()?.toString() ?: "–"

/** Pause / Resume (the main button while a print runs), the light, and Stop print apart at the right. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Controls(printer: Printer, state: PrinterUiState, viewModel: PrinterViewModel) {
    val space = SpoolwardenTheme.space
    val status = state.status
    val can = state.controlsEnabled
    val running = state.printing
    val showLight = status?.light != null
    if (running || showLight) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalArrangement = Arrangement.spacedBy(space.s2)) {
            if (running) {
                SwButton(
                    stringResource(if (state.paused) R.string.printer_resume else R.string.printer_pause),
                    viewModel::pauseOrResume, kind = SwButtonKind.Main, enabled = can,
                )
            }
            if (showLight) {
                SwButton(
                    stringResource(if (state.lightOn) R.string.printer_light_off else R.string.printer_light_on),
                    viewModel::toggleLight, enabled = can,
                )
            }
        }
        if (running) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                SwButton(stringResource(R.string.printer_stop), viewModel::askStop, kind = SwButtonKind.Destructive, enabled = can)
            }
        }
        when {
            printer.state != "connected" -> Reason(R.string.slot_load_disabled)
            state.commandBusy -> Reason(R.string.printer_waiting)
        }
    }
    state.commandNote?.let { ResultLine(it) }
}

@Composable
private fun Reason(@androidx.annotation.StringRes words: Int) {
    Text(
        stringResource(words), color = SpoolwardenTheme.colors.muted, style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun StopDialog(printer: Printer, state: PrinterUiState, viewModel: PrinterViewModel) {
    val job = state.status?.job?.ifBlank { null }
    SwDialog(
        title = stringResource(R.string.printer_stop_dialog_title),
        onClose = viewModel::cancelStop,
        confirm = SwDialogButton(stringResource(R.string.printer_stop), viewModel::confirmStop, kind = SwButtonKind.DestructiveFilled),
        cancel = SwAction(stringResource(R.string.printer_stop_keep), viewModel::cancelStop),
    ) {
        Text(
            stringResource(R.string.printer_stop_dialog_body, job ?: stringResource(R.string.printer_stop_this_print), printer.name),
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

// --- camera ---

@Composable
private fun CameraPanel(
    printer: Printer,
    camera: CameraSource,
    visible: Boolean,
    shown: Boolean,
    onShown: (Boolean) -> Unit,
    onPairAgain: () -> Unit,
) {
    if (!printer.configured) return
    var big by rememberSaveable { mutableStateOf(false) }
    val space = SpoolwardenTheme.space
    PrinterPanel(
        title = stringResource(R.string.printer_camera_title),
        action = {
            SwButton(
                stringResource(if (shown) R.string.common_hide else R.string.common_show), { onShown(!shown) },
                kind = SwButtonKind.Quiet,
            )
        },
    ) {
        if (!shown) return@PrinterPanel
        val kind = printer.camera.kind
        if (kind == null || (kind != "hls" && kind != "mjpeg")) {
            Text(
                stringResource(R.string.printer_camera_unsupported), color = SpoolwardenTheme.colors.muted,
                style = MaterialTheme.typography.bodyMedium,
            )
            return@PrinterPanel
        }
        val open = stringResource(R.string.a11y_action_open)
        val picture = Modifier.fillMaxWidth().aspectRatio(CAMERA_RATIO).clip(SpoolwardenTheme.shapes.r)
            .background(SpoolwardenTheme.colors.surface3)
        Box(picture.clickable(onClickLabel = open) { big = true }) {
            if (visible && !big) CameraPlayer(printer, camera, onPairAgain)
        }
    }
    if (big) {
        Dialog(
            onDismissRequest = { big = false },
            properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
        ) {
            Landscape()
            Box(Modifier.fillMaxSize().background(SpoolwardenTheme.colors.surface3)) {
                if (visible) CameraPlayer(printer, camera, onPairAgain)
                SwIconButton(
                    R.drawable.sw_ic_close, stringResource(R.string.common_close), { big = false },
                    modifier = Modifier.align(Alignment.TopEnd).padding(space.s2),
                )
            }
        }
    }
}

private const val CAMERA_RATIO = 16f / 9f

@Composable
private fun CameraPlayer(printer: Printer, camera: CameraSource, onPairAgain: () -> Unit) {
    val fill = Modifier.fillMaxSize()
    when (printer.camera.kind) {
        "hls" -> HlsPlayer(camera.client, camera.hlsUrl, camera.headers, printer.name, fill, onPairAgain)
        "mjpeg" -> MjpegView(camera.client, camera.mjpegUrl, camera.headers, printer.name, fill, onPairAgain)
    }
}

/**
 * The full-screen picture is shown in landscape; the phone's orientation is given back when it really closes. Turning
 * the phone restarts the activity (the effect is disposed and made again), so the orientation from before is kept in
 * saved state and is not restored then, or the two would fight each other in a loop.
 */
@Composable
internal fun Landscape() {
    val activity = LocalContext.current as? Activity ?: return
    var before by rememberSaveable { mutableIntStateOf(NOT_SAVED) }
    DisposableEffect(activity) {
        if (before == NOT_SAVED) before = activity.requestedOrientation
        activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        onDispose { if (!activity.isChangingConfigurations) activity.requestedOrientation = before }
    }
}

private const val NOT_SAVED = Int.MIN_VALUE

// --- slots ---

@Composable
private fun SlotsPanel(printer: Printer, state: PrinterUiState, onSlot: (AmsSlot) -> Unit) {
    val units = state.status?.ams.orEmpty()
    PrinterPanel(title = stringResource(R.string.printers_col_slots), padded = false) {
        if (units.isEmpty()) {
            Text(
                stringResource(R.string.spool_load_no_slots), Modifier.padding(SpoolwardenTheme.space.s4),
                color = SpoolwardenTheme.colors.muted, style = MaterialTheme.typography.bodyMedium,
            )
        }
        units.forEach { unit -> UnitGroup(unit, onSlot) }
        state.slotNote?.let { Box(Modifier.padding(SpoolwardenTheme.space.s3)) { ResultLine(it) } }
    }
}

@Composable
private fun UnitGroup(unit: AmsUnit, onSlot: (AmsSlot) -> Unit) {
    val space = SpoolwardenTheme.space
    Text(
        PrinterHelp.unitTitle(unit), Modifier.padding(horizontal = space.s4, vertical = space.s2).semantics { heading() },
        color = SpoolwardenTheme.colors.muted, style = MaterialTheme.typography.labelLarge,
    )
    unit.slots.forEach { slot ->
        PanelDivider()
        SlotRow(slot) { onSlot(slot) }
    }
}

@Composable
private fun SlotRow(slot: AmsSlot, onClick: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val empty = PrinterHelp.slotEmpty(slot)
    val spool = slot.spool
    val material = slot.type.ifBlank { spool?.material.orEmpty() }
    val headline = if (empty) {
        stringResource(R.string.common_empty)
    } else {
        listOfNotNull(material.ifBlank { null }, spool?.name?.ifBlank { null }).joinToString(SEPARATOR)
    }
    val left = spool?.remainingWeight?.let { stringResource(R.string.printer_slot_left, it.roundToInt()) }
    val open = stringResource(R.string.a11y_action_open)
    Row(
        Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).clickable(onClickLabel = open, onClick = onClick)
            .padding(horizontal = space.s4, vertical = space.s2),
        horizontalArrangement = Arrangement.spacedBy(space.s3),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            slot.label, Modifier.width(SpoolwardenTheme.sizes.slotLabel),
            style = SpoolwardenTheme.type.data,
        )
        ColorSwatch(slot.colorHex.ifBlank { spool?.colorHex }, empty = empty)
        Column(Modifier.weight(1f)) {
            Text(headline, style = MaterialTheme.typography.bodyLarge)
            if (left != null) Text(left, color = colors.muted, style = SpoolwardenTheme.type.dataSmall)
        }
        if (slot.active) {
            Text(stringResource(R.string.slot_in_use), color = colors.accentText, style = MaterialTheme.typography.labelMedium)
        }
        SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted)
    }
}

/** What a tap on a slot offers (05-android-app 9.5): its spool, or to load one. */
@Composable
private fun SlotSheet(
    slot: AmsSlot,
    printer: Printer,
    state: PrinterUiState,
    onDismiss: () -> Unit,
    onUnload: () -> Unit,
    onLoad: () -> Unit,
    onOpenSpool: (SlotSpool) -> Unit,
) {
    val space = SpoolwardenTheme.space
    val spool = slot.spool
    val empty = PrinterHelp.slotEmpty(slot)
    SwSheet(onDismiss = onDismiss, gesturesEnabled = state.slotBusy == null) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = space.s4).padding(bottom = space.s4),
            verticalArrangement = Arrangement.spacedBy(space.s3),
        ) {
            Text(
                stringResource(R.string.printer_slot_title, slot.label), Modifier.semantics { heading() },
                style = MaterialTheme.typography.titleMedium,
            )
            val connected = printer.state == "connected"
            when {
                spool != null -> {
                    Row(horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.CenterVertically) {
                        ColorSwatch(slot.colorHex.ifBlank { spool.colorHex }, empty = false)
                        Column {
                            Text(PrinterHelp.spoolName(spool), style = MaterialTheme.typography.bodyLarge)
                            spool.remainingWeight?.let {
                                Text(
                                    stringResource(R.string.printer_slot_left, it.roundToInt()),
                                    color = SpoolwardenTheme.colors.muted, style = SpoolwardenTheme.type.dataSmall,
                                )
                            }
                        }
                    }
                    SwButton(stringResource(R.string.printer_slot_open_spool), { onOpenSpool(spool) }, Modifier.fillMaxWidth(), kind = SwButtonKind.Main)
                    SwButton(
                        stringResource(R.string.common_unload), onUnload, Modifier.fillMaxWidth(),
                        enabled = state.slotBusy == null && !state.unloading, busy = state.slotBusy == slot.label,
                    )
                }
                else -> {
                    Text(
                        if (empty) stringResource(R.string.printer_slot_empty)
                        else stringResource(R.string.printer_slot_unlinked, slot.type),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    SwButton(stringResource(R.string.printer_slot_load), onLoad, Modifier.fillMaxWidth(), kind = SwButtonKind.Main, enabled = connected)
                    if (!connected) Reason(R.string.slot_load_disabled)
                }
            }
            state.slotNote?.takeIf { !it.ok }?.let { ResultLine(it) }
        }
    }
}

@Composable
private fun UnloadDialog(ask: UnloadAsk, state: PrinterUiState, viewModel: PrinterViewModel) {
    val say = rememberBusySay()
    SwDialog(
        title = stringResource(R.string.printer_unload_title, ask.label),
        onClose = { if (state.unloading) say() else viewModel.cancelUnload() },
        confirm = SwDialogButton(
            stringResource(R.string.common_unload), viewModel::confirmUnload, kind = SwButtonKind.Main, busy = state.unloading,
        ),
        cancel = SwAction(stringResource(R.string.common_cancel), viewModel::cancelUnload),
        cancelEnabled = !state.unloading,
    ) {
        BusyBack(state.unloading, say)
        Text(
            stringResource(
                R.string.printer_unload_body, ask.spool, ask.label,
                ask.location.ifBlank { stringResource(R.string.printer_unload_previous_place) },
            ),
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

// --- slot mapping ---

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MappingPanel(
    printer: Printer,
    state: PrinterUiState,
    s: ToolsUiState,
    tools: PrinterToolsViewModel,
    onMapByLoading: () -> Unit,
) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val klipper = printer.family == "klipper"
    val canStart = SlotMapHelp.canStart(printer.state, state.printing)
    val v = SlotMapHelp.view(s.map)
    val mapEnabled = !klipper && s.mapEnabled(canStart)
    val manualEnabled = canStart && !s.mapRunning
    val main = mainButton(
        pauseEnabled = state.printing && state.controlsEnabled,
        action = if (klipper) MapAction.NONE else v.action,
        mapEnabled = mapEnabled,
        manualEnabled = manualEnabled,
        reportWanted = ReportHelp.wanted(s.map),
        reportEnabled = !s.reportBusy,
    )
    PrinterPanel(title = stringResource(if (klipper) R.string.printer_map_title_klipper else R.string.printer_map_title_bambu)) {
        if (!klipper) {
            v.headline?.let { headline ->
                val (shape, colour, large) = mapShapeLook(v.shape ?: MapShape.Filled)
                ShapeWords(shape, colour, large, sayText(headline))
            }
            if (v.outcome == SlotMapOutcome.RUNNING) SwProgress(null)
            v.detail?.let { Text(sayText(it), color = colors.muted, style = MaterialTheme.typography.bodySmall) }
            if (s.map?.observe == true && !v.saysObserve) {
                NoticeCard(NoticeKind.Info, stringResource(R.string.printer_map_not_counted))
            }
            v.problemsHeading?.let { heading ->
                Text(stringResource(heading), style = MaterialTheme.typography.labelLarge)
                val colour = if (v.problemsAreError) colors.bad else colors.muted
                v.problems.forEach { Text(it, color = colour, style = MaterialTheme.typography.bodySmall) }
            }
            if (v.notes.isNotEmpty()) {
                Text(stringResource(R.string.printer_map_notes), style = MaterialTheme.typography.labelLarge)
                v.notes.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
            }
            s.mapProblem?.let { NoticeCard(NoticeKind.Bad, problemText(it)) }
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalArrangement = Arrangement.spacedBy(space.s2)) {
            if (!klipper) {
                SwButton(
                    stringResource(SlotMapHelp.buttonLabel(s.map)), tools::askMap,
                    kind = if (main == MainButton.MapSlots) SwButtonKind.Main else SwButtonKind.Plain, enabled = mapEnabled,
                )
            }
            SwButton(
                stringResource(R.string.printers_map_loading), onMapByLoading,
                kind = if (main == MainButton.MapByLoading) SwButtonKind.Main else SwButtonKind.Plain, enabled = manualEnabled,
            )
        }
        SlotMapHelp.blockedReason(printer.state, state.printing)?.let { Reason(it) }
        if (!klipper) CollectReport(s, tools, main == MainButton.Report)
    }
}

/** "Collect a report": the Hub builds reports for Bambu printers only; the file goes straight to the share sheet. */
@Composable
private fun CollectReport(s: ToolsUiState, tools: PrinterToolsViewModel, filled: Boolean) {
    val space = SpoolwardenTheme.space
    ReportHelp.why(s.map)?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
    SwButton(
        stringResource(if (s.reportBusy) R.string.printer_report_collecting else R.string.printers_collect_report),
        tools::collectReport,
        kind = if (filled) SwButtonKind.Main else SwButtonKind.Plain, enabled = !s.reportBusy,
    )
    Text(
        stringResource(R.string.printer_map_report_note), Modifier.padding(top = space.s1),
        color = SpoolwardenTheme.colors.muted, style = MaterialTheme.typography.bodySmall,
    )
    s.reportProblem?.let {
        NoticeCard(
            NoticeKind.Bad, sayText(it),
            actions = listOf(SwAction(stringResource(R.string.common_try_again), tools::collectReport)),
        )
    }
}

@Composable
private fun MapDialog(printer: Printer, s: ToolsUiState, tools: PrinterToolsViewModel) {
    val say = rememberBusySay()
    SwDialog(
        title = stringResource(R.string.printers_map_title, printer.name),
        onClose = { if (s.mapBusy) say() else tools.cancelMap() },
        confirm = SwDialogButton(stringResource(R.string.printers_map_slots), tools::confirmMap, kind = SwButtonKind.Main, busy = s.mapBusy),
        cancel = SwAction(stringResource(R.string.common_cancel), tools::cancelMap),
        cancelEnabled = !s.mapBusy,
    ) {
        BusyBack(s.mapBusy, say)
        Text(stringResource(R.string.printers_map_body), style = MaterialTheme.typography.bodyMedium)
    }
}

// --- filament used ---

@Composable
private fun UsagePanel(s: ToolsUiState, tools: PrinterToolsViewModel) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    PrinterPanel(title = stringResource(R.string.printer_usage_title), padded = false) {
        Column(Modifier.padding(horizontal = space.s4), verticalArrangement = Arrangement.spacedBy(space.s2)) {
            s.usageProblem?.let {
                NoticeCard(
                    NoticeKind.Bad, problemText(it),
                    actions = listOf(SwAction(stringResource(R.string.common_try_again), tools::refreshUsage)),
                )
            }
            s.undoneNote?.let { ResultLine(Note(it)) }
        }
        if (s.usageLoaded && s.usage.isEmpty()) {
            Text(
                stringResource(R.string.printer_usage_empty), Modifier.padding(space.s4),
                color = colors.muted, style = MaterialTheme.typography.bodyMedium,
            )
        }
        s.usage.forEach { e ->
            PanelDivider()
            Row(
                Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).padding(start = space.s4, end = space.s2, top = space.s2, bottom = space.s2),
                horizontalArrangement = Arrangement.spacedBy(space.s2),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(sayText(UsageHelp.headline(e)), style = SpoolwardenTheme.type.data)
                    val note = usageNote(e)
                    Text(
                        listOfNotNull(formatWhen(e.at), note?.let { sayText(it) }).joinToString(SEPARATOR),
                        color = colors.muted, style = SpoolwardenTheme.type.dataSmall,
                    )
                }
                if (UsageHelp.canUndo(e)) {
                    SwButton(stringResource(R.string.common_undo), { tools.askUndo(e) }, kind = SwButtonKind.Quiet, enabled = !s.undoBusy)
                }
            }
        }
    }
}

@Composable
private fun UndoDialog(e: com.thompsonfabco.filamentkit.net.UsageEntry, s: ToolsUiState, tools: PrinterToolsViewModel) {
    val say = rememberBusySay()
    SwDialog(
        title = stringResource(R.string.printer_usage_undo_title),
        onClose = { if (s.undoBusy) say() else tools.cancelUndo() },
        confirm = SwDialogButton(
            stringResource(R.string.printer_usage_undo_confirm), tools::confirmUndo, kind = SwButtonKind.Main, busy = s.undoBusy,
        ),
        cancel = SwAction(stringResource(R.string.common_keep), tools::cancelUndo),
        cancelEnabled = !s.undoBusy,
    ) {
        BusyBack(s.undoBusy, say)
        Text(
            stringResource(
                R.string.printer_usage_undo_body, grams(e.grams), e.job?.ifBlank { null } ?: "–", e.slot?.ifBlank { null } ?: "–",
                formatWhen(e.at) ?: e.at,
            ),
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

/** The last row: "Printer settings" with a chevron opens 9.9. */
@Composable
private fun SettingsRow(onOpen: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val open = stringResource(R.string.a11y_action_open)
    PrinterPanel(title = null, padded = false) {
        Row(
            Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).clickable(onClickLabel = open, onClick = onOpen)
                .padding(horizontal = space.s4),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(stringResource(R.string.printer_settings_title), style = MaterialTheme.typography.bodyLarge)
            SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted)
        }
    }
}

private val WHEN = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")

/** "2026-11-12 14:05" in the phone's time zone; null when the Hub gives no time. */
internal fun formatWhen(iso: String): String? = try {
    OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault()).format(WHEN)
} catch (_: Exception) {
    iso.ifBlank { null }
}

private fun formatClock(iso: String): String? = try {
    OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault())
        .format(DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT))
} catch (_: Exception) {
    null
}
