package com.thompsonfabco.filamentkit.ui.spool

import androidx.activity.compose.BackHandler
import androidx.annotation.StringRes
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.AmsSlot
import com.thompsonfabco.filamentkit.net.AmsUnit
import com.thompsonfabco.filamentkit.net.LoadResult
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.StatusKind
import com.thompsonfabco.filamentkit.ui.components.StatusLabel
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.ScreenState
import com.thompsonfabco.filamentkit.ui.components.SwSkeletonRows
import com.thompsonfabco.filamentkit.ui.printers.PrinterHelp
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.launch

/** The page of one load step: scrolls, centred, at most `columnMax` wide, the spool's summary row pinned at the top. */
@Composable
private fun LoadPage(spool: SpoolSummary?, modifier: Modifier, content: @Composable () -> Unit) {
    val space = SpoolwardenTheme.space
    Column(modifier.fillMaxSize()) {
        Column(
            Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(space.s4),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Column(Modifier.widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(space.s3)) {
                spool?.let { SpoolRow(it) }
                content()
            }
        }
    }
}

@Composable
private fun Header(text: String) {
    Text(text, Modifier.semantics { heading() }, style = MaterialTheme.typography.titleLarge)
}

private fun statusOf(p: Printer): StatusKind = when (p.state) {
    Printer.STATE_CONNECTED -> StatusKind.Connected
    Printer.STATE_OFFLINE -> StatusKind.Offline
    else -> StatusKind.NeedsLook
}

/** What to do about a printer that is not connected, in the catalogue's words (05 9.1); null when nothing is wrong. */
@StringRes
internal fun fixText(state: String): Int? = when (state) {
    Printer.STATE_OFFLINE -> R.string.printers_fix_offline
    Printer.STATE_WRONG_CODE -> R.string.printers_fix_wrong_code
    Printer.STATE_NOT_CONFIGURED -> R.string.printers_fix_not_configured
    NEEDS_DEVELOPER_MODE -> R.string.printers_fix_developer_mode
    CERT_CHANGED -> R.string.printers_fix_cert_changed
    else -> null
}

private const val NEEDS_DEVELOPER_MODE = "needs_developer_mode"
private const val CERT_CHANGED = "cert_changed"

/**
 * Load into a printer, step 1 (05 7.6): the configured printers. One that cannot take a load now is shown off with the
 * reason. With exactly one that can, the step is skipped ([onPick] with `skipped` true replaces this step).
 */
@Composable
fun LoadPrintersScreen(
    vm: LoadPrintersViewModel,
    spool: SpoolSummary?,
    onPick: (Printer, Boolean) -> Unit,
    onOpenPrinters: () -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
    online: Boolean = true,
) {
    val ui by vm.state.collectAsStateWithLifecycle()
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val pick by rememberUpdatedState(onPick)
    val only = ui.only
    LaunchedEffect(only?.id) { only?.let { pick(it, true) } }
    LoadPage(spool, modifier) {
        Header(stringResource(R.string.spool_load_which_printer))
        HubNoticeOf(ui.failure, onPairAgain)
        val printers = ui.printers
        // the states every Hub screen has (05 3.2); the skeleton rows are the loading state of this list
        ScreenState(
            loaded = printers != null,
            loading = ui.loading,
            isEmpty = printers?.isEmpty() == true,
            empty = {
                Text(stringResource(R.string.spool_load_no_printers), style = MaterialTheme.typography.bodyLarge)
                SwButton(stringResource(R.string.spool_load_open_printers), onOpenPrinters, kind = SwButtonKind.Quiet)
            },
            error = ui.failure?.let { hubFailureText(it) },
            onTryAgain = vm::load,
            offline = !online,
            loadedSecondsAgo = secondsSince(ui.loadedAt),
            skeleton = {
                Text(stringResource(R.string.spool_load_loading_printers), style = MaterialTheme.typography.bodyMedium, color = colors.muted)
                SwSkeletonRows(SKELETON_ROWS)
            },
        ) {
            SpoolPanel {
                printers.orEmpty().forEachIndexed { i, p ->
                    if (i > 0) HorizontalDivider(color = colors.border, thickness = SpoolwardenTheme.sizes.hairline)
                    val can = canTakeLoad(p)
                    Row(
                        Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).clickable(enabled = can) { pick(p, false) },
                        horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f).padding(vertical = space.s2)) {
                            Text(p.name, style = MaterialTheme.typography.bodyLarge, color = if (can) colors.text else colors.muted)
                            StatusLabel(statusOf(p), small = true)
                            p.shownModel?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = colors.muted) }
                            // the reason it is off; Offline is said by its label
                            if (!can && p.state != Printer.STATE_OFFLINE) {
                                fixText(p.state)?.let { Text(stringResource(it), style = MaterialTheme.typography.bodySmall, color = colors.muted) }
                            }
                        }
                        if (can) SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted)
                    }
                }
            }
        }
    }
}

private const val SKELETON_ROWS = 3

/** "PETG · Bambu Lab PETG HF Orange · in use": the parts the printer or the inventory gave. */
@Composable
private fun slotLine(s: AmsSlot): String = listOfNotNull(
    if (PrinterHelp.slotEmpty(s)) stringResource(R.string.printers_slot_empty) else s.type.ifBlank { null },
    s.spool?.name?.ifBlank { null }?.takeUnless { PrinterHelp.slotEmpty(s) },
    stringResource(R.string.spool_load_in_use).takeIf { s.active },
).joinToString(DOT)

/**
 * Load into a printer, step 2 (05 7.6): the slots the printer reports, grouped by unit. [skipped] says step 1 was
 * skipped, so the printer is named here.
 */
@Composable
fun LoadSlotsScreen(
    vm: LoadSlotsViewModel,
    spool: SpoolSummary?,
    skipped: Boolean,
    onPick: (String) -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
    online: Boolean = true,
) {
    val ui by vm.state.collectAsStateWithLifecycle()
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val printer = ui.printer
    LoadPage(spool, modifier) {
        if (printer != null) {
            Header(stringResource(R.string.spool_load_which_slot, printer.name))
            if (skipped) Text(stringResource(R.string.spool_load_printer, printer.name), style = MaterialTheme.typography.bodyMedium, color = colors.muted)
            fixText(printer.state)?.let { NoticeCard(NoticeKind.Warn, stringResource(it)) }
        }
        HubNoticeOf(ui.failure, onPairAgain)
        val slots = ui.slots
        ScreenState(
            loaded = slots != null,
            loading = ui.loading,
            isEmpty = slots?.isEmpty() == true,
            empty = { Text(stringResource(R.string.spool_load_no_slots), style = MaterialTheme.typography.bodyLarge) },
            error = ui.failure?.let { hubFailureText(it) },
            onTryAgain = vm::load,
            offline = !online,
            loadedSecondsAgo = secondsSince(ui.loadedAt),
            skeleton = {
                Text(stringResource(R.string.spool_load_loading_slots), style = MaterialTheme.typography.bodyMedium, color = colors.muted)
                SwSkeletonRows(SKELETON_ROWS)
            },
        ) {
            val can = printer?.let(::canTakeLoad) == true
            ui.units.filter { u -> u.slots.any { it.label.isNotBlank() } }.forEach { unit ->
                Text(
                    PrinterHelp.unitTitle(unit), Modifier.semantics { heading() },
                    style = MaterialTheme.typography.titleSmall, color = colors.muted,
                )
                SpoolPanel {
                    unit.slots.filter { it.label.isNotBlank() }.forEachIndexed { i, slot ->
                        if (i > 0) HorizontalDivider(color = colors.border, thickness = SpoolwardenTheme.sizes.hairline)
                        SlotRow(slot, ui.units, can) { onPick(slot.label) }
                    }
                }
            }
        }
    }
}

@Composable
private fun SlotRow(slot: AmsSlot, units: List<AmsUnit>, enabled: Boolean, onClick: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val empty = PrinterHelp.slotEmpty(slot)
    Row(
        Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).clickable(enabled = enabled, onClick = onClick),
        horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            PrinterHelp.slotLabel(slot, units), Modifier.widthIn(min = SpoolwardenTheme.sizes.slotLabel),
            style = SpoolwardenTheme.type.data, color = if (enabled) colors.text else colors.muted,
        )
        ColorSwatch(slot.colorHex.ifBlank { slot.spool?.colorHex }, empty = empty)
        Text(slotLine(slot), Modifier.weight(1f).padding(vertical = space.s2), style = MaterialTheme.typography.bodyMedium, color = if (enabled) colors.text else colors.muted)
        if (enabled) SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted)
    }
}

/** The rows of the Hub's preview: the preset, the nozzle, where the spool now in the slot goes back to, and its problems. */
@Composable
private fun PlanRows(plan: LoadResult) {
    val none = stringResource(R.string.web_load_plan_preset_none)
    val lines = buildList {
        add(stringResource(R.string.web_load_plan_preset, plan.preset?.name?.ifBlank { null } ?: none))
        val mm = plan.nozzleMm?.let { java.math.BigDecimal.valueOf(it).stripTrailingZeros().toPlainString() }
        when {
            plan.nozzleAssumed -> add(stringResource(R.string.web_load_plan_nozzle_assumed, mm ?: DEFAULT_NOZZLE_MM))
            mm != null -> add(stringResource(R.string.web_load_plan_nozzle, mm))
        }
        plan.movedBack.forEach { m ->
            add(
                stringResource(
                    R.string.web_load_plan_goes_back, m.id?.toString() ?: stringResource(R.string.common_unknown), plan.slot.label,
                    m.location.ifBlank { stringResource(R.string.web_load_previous_place) },
                ),
            )
        }
        addAll(plan.problems)
    }
    SpoolPanel {
        lines.forEachIndexed { i, line ->
            if (i > 0) HorizontalDivider(color = SpoolwardenTheme.colors.border, thickness = SpoolwardenTheme.sizes.hairline)
            Text(monoNumbers(line), Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).padding(vertical = SpoolwardenTheme.space.s3), style = MaterialTheme.typography.bodyMedium)
        }
    }
}

private const val DEFAULT_NOZZLE_MM = "0.4"

/**
 * Load into a printer, step 3 (05 7.6): the Hub's preview, then the load. While it is written Back, the back arrow and
 * every other way out are ignored with the toast of 2.5 rule 2. [onFinished] runs once it is written (the spool
 * screen shows the result); [onDone] leaves after the connection dropped; [onOpenPrinter] opens the printer's screen.
 */
@Composable
fun LoadPreviewScreen(
    vm: LoadPreviewViewModel,
    spool: SpoolSummary?,
    slot: String,
    onBack: () -> Unit,
    onFinished: (SpoolResult) -> Unit,
    onDone: () -> Unit,
    onOpenPrinter: () -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
    online: Boolean = true,
) {
    val ui by vm.state.collectAsStateWithLifecycle()
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val toast = LocalToast.current
    val scope = rememberCoroutineScope()
    val wait = stringResource(R.string.common_load_wait)
    BackHandler(enabled = ui.writing) { scope.launch { toast?.show(wait) } }
    val finished by rememberUpdatedState(onFinished)
    LaunchedEffect(ui.finished) { ui.finished?.let { finished(it) } }
    LoadPage(spool, modifier) {
        val printer = ui.printer
        if (printer != null) Header(stringResource(R.string.spool_load_confirm_title, printer.name, slot))
        if (ui.checking) Text(stringResource(R.string.common_checking), style = MaterialTheme.typography.bodyMedium, color = colors.muted)
        HubNoticeOf(ui.failure, onPairAgain)
        // the states every Hub screen has (05 3.2); Try again asks the preview again, or sends the load again
        ScreenState(
            loaded = ui.plan != null,
            loading = ui.checking,
            error = ui.failure?.let { hubFailureText(it) },
            onTryAgain = if (ui.plan == null) vm::check else vm::load,
            offline = !online,
        ) {
            ui.plan?.let { plan ->
                PlanRows(plan)
                Text(stringResource(R.string.spool_load_confirm_text), style = MaterialTheme.typography.bodyMedium, color = colors.muted)
            }
        }
        if (ui.pairingRefused) NoticeCard(NoticeKind.Bad, stringResource(R.string.spool_load_pairing_refused))
        if (ui.dropped) {
            NoticeCard(
                NoticeKind.Bad, stringResource(R.string.spool_load_dropped),
                actions = listOf(
                    SwAction(stringResource(R.string.spool_load_open_printer), onOpenPrinter),
                    SwAction(stringResource(R.string.common_done), onDone),
                ),
            )
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(space.s2)) {
            SwButton(stringResource(R.string.common_back), onBack, enabled = !ui.writing)
            SwButton(
                stringResource(if (ui.writing) R.string.spool_load_loading else R.string.spool_load_button), vm::load,
                kind = SwButtonKind.Main, enabled = ui.plan != null && !ui.checking && !ui.dropped, busy = ui.writing,
            )
        }
    }
}
