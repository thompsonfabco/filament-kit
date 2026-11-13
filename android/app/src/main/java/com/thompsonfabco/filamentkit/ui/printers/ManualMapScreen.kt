package com.thompsonfabco.filamentkit.ui.printers

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.LifecycleStartEffect
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ManualPosition
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwDialog
import com.thompsonfabco.filamentkit.ui.components.SwDialogButton
import com.thompsonfabco.filamentkit.ui.components.SwProgress
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * "Map by loading filament" (05-android-app 9.8): one named position at a time. The Hub says what to load; once the
 * printer shows a settled load it asks whether that is the one, answered with Yes, "No, I loaded another one" or Skip.
 * A dual-nozzle printer that does not say the nozzle gets the question first. A printer that reports no loads gets the
 * by-hand list. Leaving while the session is open asks first, as an open session holds off automatic mapping.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ManualMapScreen(viewModel: ManualMapViewModel, printerName: String?, onBack: () -> Unit, onPairAgain: () -> Unit) {
    val s by viewModel.state.collectAsState()
    LifecycleStartEffect(viewModel) {
        viewModel.start()
        onStopOrDispose { viewModel.stop() }
    }
    val leave = { if (s.open) viewModel.askStop() else onBack() }
    BackHandler(onBack = leave)
    val space = SpoolwardenTheme.space

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(space.s4),
        verticalArrangement = Arrangement.spacedBy(space.s3),
    ) {
        printerName?.let {
            Text(it, Modifier.semantics { heading() }, color = SpoolwardenTheme.colors.muted, style = MaterialTheme.typography.bodyLarge)
        }
        HubNotices(unauthorized = s.unauthorized, mismatch = s.mismatch != null, onPairAgain = onPairAgain)
        val m = s.map
        if (m == null) {
            if (s.busy) {
                SwProgress(null)
                Text(stringResource(R.string.printer_mbl_starting), style = MaterialTheme.typography.bodyMedium)
            }
            s.problem?.let {
                NoticeCard(
                    NoticeKind.Bad, problemText(it),
                    actions = listOf(SwAction(stringResource(R.string.common_try_again), viewModel::retry)),
                )
            }
            return@Column
        }
        val step = m.step
        if (m.open && step != null) {
            Text(step.say, style = MaterialTheme.typography.titleMedium)
            val seen = step.seen
            when {
                s.byHand -> {
                    Text(stringResource(R.string.printer_mbl_which_slot), style = MaterialTheme.typography.bodyMedium)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalArrangement = Arrangement.spacedBy(space.s2)) {
                        m.choices.forEachIndexed { i, c ->
                            SwButton(c.label, { viewModel.pickByHand(i) }, enabled = !s.busy)
                        }
                    }
                    Text(
                        stringResource(R.string.printer_mbl_by_hand_note), color = SpoolwardenTheme.colors.muted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                seen != null && seen.settled && step.ask != null -> {
                    Text(step.ask, style = MaterialTheme.typography.bodyLarge)
                    if (m.dualNozzle && !seen.nozzleReported) {
                        Text(stringResource(R.string.printer_mbl_which_nozzle), style = MaterialTheme.typography.bodyMedium)
                        Row(horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                            listOf("left" to R.string.printer_mbl_left_nozzle, "right" to R.string.printer_mbl_right_nozzle)
                                .forEach { (n, label) ->
                                    FilterChip(
                                        modifier = Modifier.heightIn(min = SpoolwardenTheme.sizes.row), selected = s.nozzle == n, onClick = { viewModel.chooseNozzle(n) },
                                        label = { Text(stringResource(label)) }, shape = SpoolwardenTheme.shapes.rS,
                                    )
                                }
                        }
                    }
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalArrangement = Arrangement.spacedBy(space.s2)) {
                        SwButton(stringResource(R.string.common_yes), viewModel::yes, kind = SwButtonKind.Main, enabled = s.canAnswer)
                        SwButton(stringResource(R.string.printer_mbl_no_other), viewModel::openOther, enabled = s.canAnswer)
                    }
                }
                seen != null -> {
                    SwProgress(null)
                    Text(stringResource(R.string.printer_mbl_settling), style = MaterialTheme.typography.bodyMedium)
                }
                else -> {
                    SwProgress(null)
                    Text(stringResource(R.string.printer_mbl_waiting), style = MaterialTheme.typography.bodyMedium)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                SwButton(
                    stringResource(R.string.printer_mbl_skip, step.position.label), viewModel::skip,
                    kind = SwButtonKind.Quiet, enabled = !s.busy,
                )
                SwButton(stringResource(R.string.printer_mbl_stop), viewModel::askStop, kind = SwButtonKind.Quiet, enabled = !s.busy)
            }
        }
        if (s.lost) NoticeCard(NoticeKind.Info, stringResource(R.string.printer_mbl_lost))
        s.problem?.let { NoticeCard(NoticeKind.Bad, problemText(it)) }
        if (!m.open) {
            Text(m.summary, style = MaterialTheme.typography.bodyLarge)
            if (m.offerReport) {
                Text(stringResource(R.string.printer_mbl_share), style = MaterialTheme.typography.bodyMedium)
                Row(horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                    SwButton(stringResource(R.string.printer_mbl_share_yes), { viewModel.offer(true) }, enabled = !s.busy)
                    SwButton(stringResource(R.string.printer_mbl_share_no), { viewModel.offer(false) }, kind = SwButtonKind.Quiet, enabled = !s.busy)
                }
            }
            s.note?.let { NoticeCard(NoticeKind.Info, it) }
        }
        PositionsPanel(m.positions, m.open)
        if (!m.open) SwButton(stringResource(R.string.common_done), onBack, Modifier.fillMaxWidth(), kind = SwButtonKind.Main)
    }

    if (s.pickingOther) {
        val current = s.map?.step?.position?.id
        SwDialog(
            title = stringResource(R.string.printer_mbl_which_one),
            onClose = viewModel::closeOther,
            // the dialog is the list of positions and Cancel: the only button of the footer is Cancel
            confirm = SwDialogButton(stringResource(R.string.common_cancel), viewModel::closeOther, kind = SwButtonKind.Plain),
        ) {
            s.map?.positions.orEmpty().filter { it.id != current }.forEach { p ->
                SwButton(p.label, { viewModel.loadedOther(p.id) }, Modifier.fillMaxWidth())
            }
        }
    }
    if (s.confirmStop) {
        SwDialog(
            title = stringResource(R.string.printer_mbl_stop_title, printerName.orEmpty()),
            onClose = viewModel::cancelStop,
            confirm = SwDialogButton(
                stringResource(R.string.printer_mbl_stop_confirm), viewModel::confirmStop, kind = SwButtonKind.DestructiveFilled,
            ),
            cancel = SwAction(stringResource(R.string.printer_mbl_stop_keep), viewModel::cancelStop),
        ) {
            Text(stringResource(R.string.printer_mbl_stop_body), style = MaterialTheme.typography.bodyMedium)
        }
    }
}

/** The panel "Slots": one row per position with its status ("A1: confirmed (A1, left nozzle)"). */
@Composable
private fun PositionsPanel(positions: List<ManualPosition>, open: Boolean) {
    val space = SpoolwardenTheme.space
    PrinterPanel(title = stringResource(R.string.printer_slots_title), padded = false) {
        positions.forEachIndexed { i, p ->
            if (i > 0) PanelDivider()
            Row(
                Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).padding(horizontal = space.s4, vertical = space.s2),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(positionLine(p, open), style = SpoolwardenTheme.type.data)
            }
        }
    }
}

/** "A1: confirmed (A1, left nozzle)", "A2: entered by hand (A2)", "A3: skipped", "A4: not answered yet" / "not mapped". */
@Composable
private fun positionLine(p: ManualPosition, open: Boolean): String {
    if (p.status == "confirmed") {
        val where = listOfNotNull(
            p.reportedLabel, p.nozzle?.let { stringResource(R.string.printer_mbl_nozzle_where, it) },
        ).joinToString(WHERE_SEPARATOR)
        return stringResource(R.string.printer_mbl_row_confirmed, p.label, where)
    }
    val status = when (p.status) {
        "by_hand" -> stringResource(R.string.printer_mbl_row_by_hand, p.reportedLabel ?: "?")
        "skipped" -> stringResource(R.string.printer_mbl_row_skipped)
        else -> stringResource(if (open) R.string.printer_mbl_row_unanswered else R.string.printer_mbl_row_unmapped)
    }
    return stringResource(R.string.printer_mbl_row_other, p.label, status)
}

private const val WHERE_SEPARATOR = ", "
