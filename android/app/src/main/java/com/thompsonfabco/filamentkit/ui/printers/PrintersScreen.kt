package com.thompsonfabco.filamentkit.ui.printers

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.KlipperFound
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterSummary
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.components.HubNotice
import com.thompsonfabco.filamentkit.ui.components.HubNoticeKind
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.NeedsHubReason
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.ScreenState
import com.thompsonfabco.filamentkit.ui.components.ScreenTopBarActions
import com.thompsonfabco.filamentkit.ui.components.StatusKind
import com.thompsonfabco.filamentkit.ui.components.StatusLabel
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwDialog
import com.thompsonfabco.filamentkit.ui.components.SwDialogButton
import com.thompsonfabco.filamentkit.ui.components.SwEmptyState
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwIconButton
import com.thompsonfabco.filamentkit.ui.components.SwMenu
import com.thompsonfabco.filamentkit.ui.components.SwMenuItem
import com.thompsonfabco.filamentkit.ui.components.SwSheet
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.launch

/**
 * The printers the Hub knows (05-android-app 9.1): the set-up printers with status, job and slots, the printers it
 * found that are not set up, and the ways to add one. Tapping a set-up printer opens it with [onOpen].
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PrintersScreen(
    viewModel: PrintersViewModel,
    onOpen: (id: String) -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LifecycleStartEffect(viewModel) {
        viewModel.refresh()
        onStopOrDispose { }
    }
    val toast = LocalToast.current
    val scope = rememberCoroutineScope()
    val addedText = state.added?.let { stringResource(R.string.printer_add_done, it) }
        ?: state.replaced?.let { stringResource(R.string.printer_set_code_done, it) }
    LaunchedEffect(state.added, state.replaced) {
        if (addedText != null) {
            viewModel.addedShown()
            scope.launch { toast?.show(addedText) }
        }
    }
    val space = SpoolwardenTheme.space
    val offline = state.problem is Problem.Unreachable
    ScreenTopBarActions { Overflow(!offline, viewModel::refresh, viewModel::openFind, { viewModel.openAddKlipper() }) }
    // the progress line shows a refresh, so the pull gesture only starts one
    PullToRefreshBox(isRefreshing = false, onRefresh = viewModel::refresh, modifier = modifier.fillMaxSize()) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(space.s4),
            verticalArrangement = Arrangement.spacedBy(space.s3),
        ) {
            if (state.mismatch != null) HubNotice(HubNoticeKind.CertificateChanged, onPairAgain)
            if (state.unauthorized) HubNotice(HubNoticeKind.NoLongerPaired, onPairAgain)
            ScreenState(
                loaded = state.loaded,
                loading = state.loading,
                isEmpty = state.printers.isEmpty(),
                empty = {
                    SwEmptyState(
                        icon = R.drawable.sw_ic_printer,
                        title = stringResource(R.string.printers_empty_title),
                        text = stringResource(R.string.printer_list_empty_text),
                        primary = SwAction(stringResource(R.string.common_refresh), viewModel::refresh),
                        secondary = if (offline) null else SwAction(stringResource(R.string.printers_add_klipper)) { viewModel.openAddKlipper() },
                    )
                },
                error = state.problem?.takeUnless { offline }?.let { problemText(it) },
                onTryAgain = viewModel::refresh,
                offline = offline,
                loadedSecondsAgo = (System.currentTimeMillis() - state.loadedAt).coerceAtLeast(0) / MS_PER_S,
            ) {
                PrinterLists(state, offline, onOpen, onAdd = viewModel::openAdd, onAddKlipper = viewModel::openAddKlipper)
            }
        }
    }
    state.dialog?.let { AddBambuDialog(it, onPairAgain, viewModel) }
    state.klipper?.let { AddKlipperDialog(it, onPairAgain, viewModel) }
    state.find?.let { FindSheetContent(it, onPairAgain, viewModel) }
}

private const val MS_PER_S = 1000L

@Composable
private fun Overflow(online: Boolean, onRefresh: () -> Unit, onFind: () -> Unit, onAddKlipper: () -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        SwIconButton(R.drawable.sw_ic_more, stringResource(R.string.common_more_actions), { open = true })
        SwMenu(open, { open = false }) {
            SwMenuItem(stringResource(R.string.common_refresh), { open = false; onRefresh() }, icon = R.drawable.sw_ic_refresh)
            SwMenuItem(
                stringResource(R.string.printers_find_klipper), { open = false; onFind() }, icon = R.drawable.sw_ic_search,
                enabled = online,
            )
            SwMenuItem(
                stringResource(R.string.printers_add_klipper), { open = false; onAddKlipper() }, icon = R.drawable.sw_ic_plus,
                enabled = online,
            )
        }
    }
}

@Composable
private fun ColumnScope.PrinterLists(
    state: PrintersUiState,
    offline: Boolean,
    onOpen: (String) -> Unit,
    onAdd: (Printer) -> Unit,
    onAddKlipper: (host: String, port: Int) -> Unit,
) {
    val space = SpoolwardenTheme.space
    val configured = state.configured
    if (configured.isNotEmpty()) {
        Panel {
            configured.forEachIndexed { i, p ->
                if (i > 0) Divider()
                PrinterRow(p, state.swatches[p.id].orEmpty()) { if (p.state == "wrong_code") onAdd(p) else onOpen(p.id) }
            }
        }
    }
    val found = state.found
    if (found.isNotEmpty()) {
        Text(
            stringResource(R.string.printers_found_title).uppercase(),
            Modifier.padding(top = space.s2).semantics { heading() },
            style = MaterialTheme.typography.labelSmall,
            color = SpoolwardenTheme.colors.muted,
        )
        Panel(ground = SpoolwardenTheme.colors.accentSoft) {
            found.forEachIndexed { i, p ->
                if (i > 0) Divider()
                FoundRow(p, enabled = !offline, reason = offline && i == 0) {
                    if (p.family == "klipper") {
                        onAddKlipper(p.host ?: p.ip.orEmpty(), PrintersViewModel.DEFAULT_KLIPPER_PORT)
                    } else {
                        onAdd(p)
                    }
                }
            }
        }
    }
    Column {
        SwButton(
            stringResource(R.string.printers_add_klipper), { onAddKlipper("", PrintersViewModel.DEFAULT_KLIPPER_PORT) },
            kind = SwButtonKind.Plain, enabled = !offline,
        )
        if (offline && found.isEmpty()) NeedsHubReason()
    }
}

/** A panel (05-android-app 3.1): [ground], 1 dp `border`, `r` corners, no shadow; rows sit in it separated by dividers. */
@Composable
private fun Panel(ground: Color = SpoolwardenTheme.colors.surface, content: @Composable ColumnScope.() -> Unit) {
    val shape = SpoolwardenTheme.shapes.r
    Column(
        Modifier.fillMaxWidth().clip(shape).background(ground, shape)
            .border(SpoolwardenTheme.sizes.hairline, SpoolwardenTheme.colors.border, shape),
        content = content,
    )
}

@Composable
private fun Divider() {
    HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = SpoolwardenTheme.colors.border)
}

/** "Bambu Lab X1 Carbon", "Voron 2.4 (Klipper)": what the printer is, in the model's own name. */
@Composable
private fun modelLine(p: Printer): String {
    val model = p.shownModel
    return if (p.family == "klipper") {
        if (model == null) stringResource(R.string.common_klipper) else stringResource(R.string.printer_list_model_klipper, model)
    } else {
        if (model == null) stringResource(R.string.common_bambu_lab) else stringResource(R.string.printer_list_model_bambu, model)
    }
}

@Composable
private fun PrinterRow(p: Printer, slots: List<SlotLook>, onClick: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val open = stringResource(R.string.a11y_action_open)
    Row(
        Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).clickable(onClickLabel = open, onClick = onClick)
            .padding(space.s3),
        horizontalArrangement = Arrangement.spacedBy(space.s3),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(space.s1)) {
            Text(p.name, style = MaterialTheme.typography.titleSmall)
            Text(modelLine(p), style = MaterialTheme.typography.bodySmall, color = colors.muted)
            Row(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically) {
                StatusLabel(statusKind(p.state), small = true)
                jobWord(p.summary?.gcodeState.orEmpty()).takeIf { p.state == "connected" }?.let { word ->
                    Text("·", style = MaterialTheme.typography.bodySmall, color = colors.muted)
                    Text(jobText(word, p.summary), style = MaterialTheme.typography.bodySmall)
                }
            }
            if (slots.isNotEmpty()) Swatches(slots)
            fixLine(p.state)?.let { fix ->
                Row(horizontalArrangement = Arrangement.spacedBy(space.s1)) {
                    Icon(
                        painterResource(NoticeKind.Warn.shape), contentDescription = null,
                        modifier = Modifier.padding(top = space.s1 / 2).size(NoticeKind.Warn.side(space)), tint = colors.warn,
                    )
                    Text(stringResource(fix), style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted)
    }
}

/** "Printing · 42 % · 1 h 12 min left", or just "Idle" for a state with no progress. */
@Composable
private fun jobText(word: JobWord, summary: PrinterSummary?): String {
    val state = stringResource(word.word)
    if (!word.progress || summary == null) return state
    if (summary.remainingMin <= 0) return stringResource(R.string.printer_list_job_percent, state, summary.percent)
    val (hours, minutes) = hoursAndMinutes(summary.remainingMin)
    val left = if (hours > 0) {
        stringResource(R.string.printer_time_hours, hours, minutes)
    } else {
        stringResource(R.string.printer_time_minutes, minutes)
    }
    return stringResource(R.string.printers_job_line, state, summary.percent, left)
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Swatches(slots: List<SlotLook>) {
    val space = SpoolwardenTheme.space
    val (shown, more) = shownSlots(slots)
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(space.s1), verticalArrangement = Arrangement.spacedBy(space.s1),
        itemVerticalAlignment = Alignment.CenterVertically,
    ) {
        shown.forEach { slot ->
            val words = if (slot.empty) {
                stringResource(R.string.a11y_swatch_empty)
            } else {
                stringResource(R.string.a11y_swatch, slot.hex.removePrefix("#").uppercase())
            }
            ColorSwatch(slot.hex, Modifier.semantics { contentDescription = words }, empty = slot.empty)
        }
        if (more > 0) {
            Text(stringResource(R.string.printers_slots_more, more), style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun FoundRow(p: Printer, enabled: Boolean, reason: Boolean, onAdd: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val address = (if (p.family == "klipper") p.host else null) ?: p.ip
    val model = modelLine(p)
    // one node for TalkBack: the model, the status, the address and the Add action
    Row(
        Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).semantics(mergeDescendants = true) { }
            .padding(space.s3),
        horizontalArrangement = Arrangement.spacedBy(space.s3),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(space.s1)) {
            Text(model, style = MaterialTheme.typography.titleSmall)
            Row(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically) {
                StatusLabel(StatusKind.NotConfigured, small = true)
                if (!address.isNullOrBlank()) {
                    Text("·", style = MaterialTheme.typography.bodySmall, color = colors.muted)
                    Text(address, style = SpoolwardenTheme.type.dataSmall)
                }
            }
        }
        Column {
            SwButton(stringResource(R.string.common_add), onAdd, kind = SwButtonKind.Plain, enabled = enabled)
            if (reason) NeedsHubReason()
        }
    }
}

/**
 * 9.2: asks for the Access Code of a printer the Hub found. For a printer that is set up and was refused its code
 * (9.9, "Replace Access Code") it asks again, with no name field. The code lives only in this form's memory.
 */
@Composable
private fun AddBambuDialog(d: AddDialog, onPairAgain: () -> Unit, viewModel: PrintersViewModel) {
    var code by remember(d.serial) { mutableStateOf("") }
    var name by remember(d.serial) { mutableStateOf(d.name) }
    val model = if (d.model == null) {
        stringResource(R.string.common_bambu_lab)
    } else {
        stringResource(R.string.printer_list_model_bambu, d.model)
    }
    val busyWords = if (d.rekey) R.string.printer_set_connecting else R.string.printer_add_connecting
    SwDialog(
        title = if (d.rekey) {
            stringResource(R.string.printer_set_code_title, d.printerName)
        } else {
            stringResource(R.string.printer_add_title, model)
        },
        onClose = { if (!d.busy) viewModel.cancelAdd() },
        confirm = SwDialogButton(
            label = stringResource(
                when {
                    d.busy -> busyWords
                    d.rekey -> R.string.printer_set_code_button
                    else -> R.string.printer_add_button
                },
            ),
            onClick = { viewModel.submitAdd(code, name) },
            kind = SwButtonKind.Main,
            enabled = code.isNotBlank(),
            busy = d.busy,
        ),
        cancel = SwAction(stringResource(R.string.common_cancel), viewModel::cancelAdd),
        cancelEnabled = !d.busy,
    ) {
        if (!d.rekey) {
            val facts = stringResource(R.string.printer_add_facts, model, d.serial)
            Text(withMono(facts, d.serial), style = MaterialTheme.typography.bodyMedium)
        }
        FormField(
            code, { code = it }, stringResource(R.string.common_access_code), secret = true, enabled = !d.busy,
            hint = stringResource(R.string.common_access_code_help),
            error = if (d.codeMissing) stringResource(R.string.printer_error_access_code) else null,
        )
        if (!d.rekey) {
            FormField(
                name, { name = it }, stringResource(R.string.common_name_optional), enabled = !d.busy,
                placeholder = stringResource(R.string.printer_add_name_placeholder),
            )
        }
        d.problem?.let { ProblemNotice(it, onPairAgain) }
        if (d.busy) BusyReason()
    }
}

/** 9.3: the address and port of a Klipper printer's Moonraker, its name and, if Moonraker asks for one, its API key. */
@Composable
private fun AddKlipperDialog(d: KlipperDialog, onPairAgain: () -> Unit, viewModel: PrintersViewModel) {
    var host by remember(d.host, d.port) { mutableStateOf(d.host) }
    var port by remember(d.host, d.port) { mutableStateOf(d.port.toString()) }
    var name by remember(d.host, d.port) { mutableStateOf("") }
    var key by remember(d.host, d.port) { mutableStateOf("") }
    // once the printer is added only the key is left to set
    val fixed = d.busy || d.createdId != null
    SwDialog(
        title = stringResource(R.string.printers_add_klipper),
        onClose = { if (!d.busy) viewModel.cancelAddKlipper() },
        confirm = SwDialogButton(
            label = stringResource(if (d.busy) R.string.printer_klipper_connecting else R.string.printer_add_button),
            onClick = { viewModel.submitAddKlipper(host, port, name, key) },
            kind = SwButtonKind.Main,
            busy = d.busy,
        ),
        cancel = SwAction(stringResource(R.string.common_cancel), viewModel::cancelAddKlipper),
        cancelEnabled = !d.busy,
    ) {
        FormField(
            host, { host = it }, stringResource(R.string.printer_field_address), enabled = !fixed, mono = true,
            placeholder = stringResource(R.string.printer_klipper_address_placeholder), keyboard = KeyboardType.Uri,
            error = if (d.addressMissing) stringResource(R.string.printer_error_address) else null,
        )
        FormField(
            port, { port = it }, stringResource(R.string.printer_field_port), enabled = !fixed, mono = true,
            keyboard = KeyboardType.Number,
            error = if (d.portInvalid) stringResource(R.string.printer_error_port) else null,
        )
        FormField(name, { name = it }, stringResource(R.string.common_name_optional), enabled = !fixed)
        FormField(
            key, { key = it }, stringResource(R.string.printer_field_moonraker_key_optional), secret = true,
            enabled = !d.busy, hint = stringResource(R.string.printer_moonraker_key_hint),
            error = d.keyProblem?.let { problemText(it) },
        )
        d.problem?.let { ProblemNotice(it, onPairAgain) }
        if (d.busy) BusyReason()
    }
}

/** Why Cancel is off while an add runs. */
@Composable
private fun BusyReason() {
    Text(
        stringResource(R.string.printer_add_wait), Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        style = MaterialTheme.typography.bodySmall, color = SpoolwardenTheme.colors.muted,
    )
}

/** 9.3: "Find Klipper printers", a sheet with the network to search and what answered. */
@Composable
private fun FindSheetContent(f: FindSheet, onPairAgain: () -> Unit, viewModel: PrintersViewModel) {
    val space = SpoolwardenTheme.space
    var network by remember { mutableStateOf("") }
    SwSheet(onDismiss = viewModel::closeFind) {
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = space.s4)
                .padding(bottom = space.s4),
            verticalArrangement = Arrangement.spacedBy(space.s3),
        ) {
            Text(
                stringResource(R.string.printers_find_klipper), Modifier.semantics { heading() },
                style = MaterialTheme.typography.titleMedium,
            )
            FormField(
                network, { network = it }, stringResource(R.string.printer_find_network), enabled = !f.searching,
                mono = true, placeholder = stringResource(R.string.printer_find_placeholder),
                hint = stringResource(R.string.printer_find_hint), keyboard = KeyboardType.Uri,
            )
            SwButton(
                stringResource(if (f.searching) R.string.printer_find_searching else R.string.printer_find_search),
                { viewModel.search(network) }, Modifier.fillMaxWidth(), kind = SwButtonKind.Main, busy = f.searching,
            )
            f.problem?.let { FindProblem(it, onPairAgain) }
            f.results?.let { results -> FindResults(results, f.network, viewModel) }
        }
    }
}

@Composable
private fun FindProblem(problem: Problem, onPairAgain: () -> Unit) {
    if (problem is Problem.FeatureOff) {
        val feature = if (problem.module == "klipper") stringResource(R.string.common_klipper) else problem.module
        NoticeCard(
            NoticeKind.Info, stringResource(R.string.common_feature_off_hint),
            title = stringResource(R.string.common_feature_off_title, feature),
        )
    } else {
        ProblemNotice(problem, onPairAgain)
    }
}

@Composable
private fun FindResults(results: List<KlipperFound>, network: String, viewModel: PrintersViewModel) {
    val space = SpoolwardenTheme.space
    if (results.isEmpty()) {
        Text(
            if (network.isEmpty()) stringResource(R.string.printer_find_none_own) else stringResource(R.string.printer_find_none, network),
            style = MaterialTheme.typography.bodyMedium, color = SpoolwardenTheme.colors.muted,
        )
        return
    }
    Panel {
        results.forEachIndexed { i, r ->
            if (i > 0) Divider()
            val address = "${r.host}:${r.port}"
            val addFor = stringResource(R.string.printer_find_add_for, address)
            Row(
                Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).padding(space.s3),
                horizontalArrangement = Arrangement.spacedBy(space.s3),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(address, Modifier.weight(1f), style = SpoolwardenTheme.type.data)
                SwButton(
                    stringResource(R.string.common_add), { viewModel.openAddKlipper(r.host, r.port) },
                    Modifier.semantics { contentDescription = addFor }, kind = SwButtonKind.Plain,
                )
            }
        }
    }
}
