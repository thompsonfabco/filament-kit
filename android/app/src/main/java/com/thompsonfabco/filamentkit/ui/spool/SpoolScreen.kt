package com.thompsonfabco.filamentkit.ui.spool

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.NeedsHubReason
import com.thompsonfabco.filamentkit.ui.components.ScreenState
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
import com.thompsonfabco.filamentkit.ui.components.SwSkeletonRows
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

/**
 * The spool screen (05 7.2): who it is, what is left, the last change, the actions and the details. Update weight and
 * Move are sheets over it, Mark empty a dialog. [online] false disables the actions with the reason under the first;
 * [printersOn] false (the Feature is off on the Hub) leaves Load into a printer out.
 */
@Composable
fun SpoolScreen(
    vm: SpoolViewModel,
    onLoad: () -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
    online: Boolean = true,
    printersOn: Boolean = true,
) {
    val ui by vm.state.collectAsStateWithLifecycle()
    val space = SpoolwardenTheme.space
    val toast = LocalToast.current
    val scope = rememberCoroutineScope()
    val moved = ui.moveToast
    val undo = stringResource(R.string.common_undo)
    val movedText = moved?.let { stringResource(R.string.spool_result_moved, it.location) }
    // the result of a move is a notice line and, because the sheet has gone, a toast with Undo
    LaunchedEffect(moved) {
        if (moved == null || movedText == null) return@LaunchedEffect
        vm.toastShown()
        scope.launch {
            val answer = toast?.show(movedText, if (moved.previous != null) undo else null)
            if (answer == androidx.compose.material3.SnackbarResult.ActionPerformed && moved.previous != null) vm.undoMove(moved.previous)
        }
    }

    Column(modifier.fillMaxSize()) {
        Column(
            Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(space.s4),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Column(
                Modifier.widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(space.s4),
            ) {
                HubNoticeOf(ui.failure, onPairAgain)
                val spool = ui.spool
                // the states every Hub screen has (05 3.2): the progress line, the error card with Try again, offline
                ScreenState(
                    loaded = spool != null,
                    loading = ui.loading,
                    error = ui.failure?.let { hubFailureText(it) },
                    onTryAgain = vm::retry,
                    offline = !online,
                    loadedSecondsAgo = secondsSince(ui.loadedAt),
                ) {
                    if (spool != null) {
                        Header(spool, ui.openedByTag)
                        Remaining(spool)
                        ui.result?.let { ResultLine(it) }
                        Actions(vm, ui, online, printersOn, onLoad)
                        Details(spool)
                    }
                }
            }
        }
    }

    ui.weight?.let { WeightSheet(vm, it, ui.spool?.remaining, onPairAgain) }
    ui.move?.let { MoveSheet(vm, it, ui.spool?.location, onPairAgain) }
    if (ui.confirmEmpty) {
        val spool = ui.spool
        SwDialog(
            title = stringResource(R.string.spool_empty_title, spool?.id.toString()),
            onClose = vm::cancelEmpty,
            confirm = SwDialogButton(
                stringResource(R.string.spool_mark_empty), vm::confirmEmpty, kind = SwButtonKind.DestructiveFilled,
                busy = ui.emptying,
            ),
            cancel = SwAction(stringResource(R.string.common_cancel), vm::cancelEmpty),
        ) {
            Text(stringResource(R.string.spool_empty_body, spool?.title.orEmpty(), spool?.id.toString()))
        }
    }
}

private const val SKELETON_ROWS = 4

@Composable
private fun Header(spool: SpoolSummary, tag: String?) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val said = stringResource(
        R.string.a11y_spool_header, spool.title, spool.id.toString(), spool.material, spool.colorHex?.removePrefix("#").orEmpty(),
    )
    Row(
        Modifier.fillMaxWidth().semantics(mergeDescendants = true) { contentDescription = said },
        horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.Top,
    ) {
        ColorSwatch(spool.colorHex, head = true)
        Column(verticalArrangement = Arrangement.spacedBy(space.s1)) {
            if (spool.brand.isNotBlank()) Text(spool.brand, style = MaterialTheme.typography.bodyMedium, color = colors.muted)
            Text(spool.name.ifBlank { spool.title }, style = MaterialTheme.typography.titleLarge)
            val line = listOfNotNull(
                stringResource(R.string.spool_title, spool.id.toString()),
                spool.material.ifBlank { null },
                spool.colorHex?.removePrefix("#")?.uppercase()?.let { "#" + it },
            ).joinToString(DOT)
            Text(monoNumbers(line), style = MaterialTheme.typography.bodySmall, color = colors.muted)
            if (tag != null) {
                Text(stringResource(R.string.spool_opened_by_tag, tag), style = MaterialTheme.typography.bodySmall, color = colors.muted)
            }
        }
    }
}

/** What is left: the weight and the level bar; "Sealed · 1000 g" and no bar for a sealed spool; "Empty" for a used up one. */
@Composable
private fun Remaining(spool: SpoolSummary) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    when (spool.state) {
        SpoolState.Empty -> Row(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically) {
            SwIcon(R.drawable.sw_st_hollow, null, tint = colors.muted)
            Text(stringResource(R.string.common_empty), style = MaterialTheme.typography.titleMedium)
        }
        SpoolState.Sealed -> Text(
            spool.total?.let { stringResource(R.string.spool_sealed_total, formatGrams(it)) } ?: stringResource(R.string.common_sealed),
            style = SpoolwardenTheme.type.number,
        )
        SpoolState.Opened -> {
            val left = spool.remaining ?: return
            val total = spool.total
            val percent = spool.percent
            val said = if (total != null && percent != null) {
                pluralStringResource(R.plurals.a11y_level_bar, left.roundToInt(), left.roundToInt(), formatGrams(total), percent.toString())
            } else {
                stringResource(R.string.spool_left_grams, formatGrams(left))
            }
            Column(
                Modifier.fillMaxWidth().semantics(mergeDescendants = true) { contentDescription = said },
                verticalArrangement = Arrangement.spacedBy(space.s2),
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.Bottom) {
                    Text(stringResource(R.string.spool_left_grams, formatGrams(left)), style = SpoolwardenTheme.type.number)
                    if (total != null) {
                        Text(
                            stringResource(R.string.spool_of_total, formatGrams(total)), style = SpoolwardenTheme.type.data,
                            color = colors.muted, modifier = Modifier.padding(bottom = space.s1),
                        )
                    }
                }
                if (percent != null) {
                    Row(horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.weight(1f)) { SwProgress(percent / PERCENT_FULL) }
                        Text(
                            stringResource(R.string.spool_left_percent, percent.toString()), style = SpoolwardenTheme.type.dataSmall,
                            color = colors.muted,
                        )
                    }
                }
            }
        }
    }
}

private const val PERCENT_FULL = 100f

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Actions(vm: SpoolViewModel, ui: SpoolUi, online: Boolean, printersOn: Boolean, onLoad: () -> Unit) {
    val space = SpoolwardenTheme.space
    val enabled = online && !ui.writing
    var menu by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
        SwButton(
            stringResource(R.string.spool_update_weight), vm::openWeight, Modifier.fillMaxWidth(),
            kind = SwButtonKind.Main, enabled = enabled,
        )
        if (!online) NeedsHubReason()
        FlowRow(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalArrangement = Arrangement.spacedBy(space.s2)) {
            if (printersOn) SwButton(stringResource(R.string.spool_load), onLoad, enabled = enabled)
            SwButton(stringResource(R.string.spool_move), vm::openMove, enabled = enabled)
            Box {
                SwIconButton(R.drawable.sw_ic_more, stringResource(R.string.common_more_actions), { menu = true })
                SwMenu(menu, { menu = false }) {
                    SwMenuItem(
                        stringResource(R.string.spool_mark_empty), { menu = false; vm.askMarkEmpty() },
                        enabled = enabled && ui.spool?.state != SpoolState.Empty,
                    )
                    SwMenuItem(stringResource(R.string.common_refresh), { menu = false; vm.refresh() }, enabled = online)
                }
            }
        }
    }
}

/** The Details panel: a field row for every value the Hub sent; a missing one is left out. */
@Composable
private fun Details(spool: SpoolSummary) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val rows = buildList {
        spool.location?.let { add(stringResource(R.string.common_field_location) to it) }
        add(stringResource(R.string.spool_field_tag) to (spool.tag ?: stringResource(R.string.common_none)))
        add(
            stringResource(R.string.common_field_state) to stringResource(
                when (spool.state) {
                    SpoolState.Sealed -> R.string.common_sealed
                    SpoolState.Opened -> R.string.spool_state_opened
                    SpoolState.Empty -> R.string.common_empty
                },
            ),
        )
        spool.filamentId?.let { add(stringResource(R.string.recent_col_filament) to it.toString()) }
        spool.emptyWeight?.let { add(stringResource(R.string.common_field_empty_spool_weight) to stringResource(R.string.common_grams, formatGrams(it))) }
        spool.lot?.let { add(stringResource(R.string.common_field_lot) to it) }
    }
    Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
        Text(
            stringResource(R.string.common_details), Modifier.semantics { heading() },
            style = MaterialTheme.typography.titleSmall, color = colors.muted,
        )
        SpoolPanel {
            rows.forEachIndexed { i, (label, value) ->
                if (i > 0) HorizontalDivider(color = colors.border, thickness = SpoolwardenTheme.sizes.hairline)
                Row(
                    Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).semantics(mergeDescendants = true) {},
                    horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(label, Modifier.widthIn(min = SpoolwardenTheme.sizes.labelCol), style = MaterialTheme.typography.bodyMedium, color = colors.muted)
                    Text(monoNumbers(value), Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }
}

/** Update weight (05 7.3): type what the scale shows, see what the Hub makes of it, then save. */
@Composable
private fun WeightSheet(vm: SpoolViewModel, w: WeightUi, now: Double?, onPairAgain: () -> Unit) {
    val space = SpoolwardenTheme.space
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    SwSheet(
        onDismiss = vm::closeWeight,
        // a save in flight is waited for; typed weight: Back, the scrim and a swipe ask first (2.5 rule 1)
        gesturesEnabled = !w.saving,
        onBlockedDismiss = if (w.dirty) vm::askLeaveWeight else null,
    ) {
        Column(Modifier.fillMaxWidth().padding(horizontal = space.s4).padding(bottom = space.s4), verticalArrangement = Arrangement.spacedBy(space.s3)) {
            Text(stringResource(R.string.spool_update_weight), Modifier.semantics { heading() }, style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = w.text,
                onValueChange = vm::setWeight,
                enabled = !w.saving,
                label = { Text(stringResource(R.string.common_field_weight_with_spool)) },
                isError = w.invalid,
                supportingText = {
                    Text(stringResource(if (w.invalid) R.string.common_error_grams else R.string.spool_weight_hint))
                },
                singleLine = true,
                textStyle = SpoolwardenTheme.type.data,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.fillMaxWidth().focusRequester(focus),
            )
            if (w.previewing) SwProgress(null)
            w.preview?.takeIf { w.previewOf == w.text }?.let { p ->
                Text(
                    monoNumbers(
                        stringResource(
                            R.string.spool_weight_preview, p.becomes?.let { formatGrams(it) } ?: stringResource(R.string.common_unknown),
                            (p.now ?: now)?.let { formatGrams(it) } ?: stringResource(R.string.common_unknown),
                        ),
                    ),
                    Modifier.semantics { liveRegion = LiveRegionMode.Polite }, style = MaterialTheme.typography.bodyMedium,
                )
            }
            w.failure?.let { HubFailureNotice(it, onPairAgain, onTryAgain = vm::retryWeight) }
            if (!w.canSave && !w.saving && !w.invalid && w.failure == null) {
                Text(stringResource(R.string.spool_weight_need_preview), style = MaterialTheme.typography.bodySmall, color = SpoolwardenTheme.colors.muted)
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(space.s2, Alignment.End)) {
                SwButton(
                    stringResource(R.string.common_cancel), vm::askLeaveWeight,
                    kind = SwButtonKind.Quiet, enabled = !w.saving,
                )
                SwButton(
                    stringResource(if (w.saving) R.string.common_saving else R.string.spool_weight_save), vm::saveWeight,
                    kind = SwButtonKind.Main, enabled = w.canSave, busy = w.saving,
                )
            }
        }
    }
    if (w.leaving) {
        SwDialog(
            title = stringResource(R.string.common_leave_title),
            onClose = vm::stayWeight,
            confirm = SwDialogButton(
                stringResource(R.string.common_leave_without_saving),
                onClick = vm::closeWeight,
                kind = SwButtonKind.DestructiveFilled,
                enabled = !w.saving,
            ),
            cancel = SwAction(stringResource(R.string.common_stay), vm::stayWeight),
        ) {
            Text(stringResource(R.string.common_leave_body, stringResource(R.string.spool_weight_thing)))
        }
    }
}

/** Move to (05 7.4): the Hub's locations as radio rows; a tap saves at once. */
@Composable
private fun MoveSheet(vm: SpoolViewModel, m: MoveUi, current: String?, onPairAgain: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    SwSheet(onDismiss = vm::closeMove, gesturesEnabled = m.movingTo == null) {
        Column(Modifier.fillMaxWidth().padding(horizontal = space.s4).padding(bottom = space.s4), verticalArrangement = Arrangement.spacedBy(space.s2)) {
            Text(stringResource(R.string.spool_move_title), Modifier.semantics { heading() }, style = MaterialTheme.typography.titleMedium)
            m.failure?.let { HubFailureNotice(it, onPairAgain, onTryAgain = vm::retryMove) }
            val locations = m.locations
            when {
                locations == null -> if (m.failure == null) SwSkeletonRows(SKELETON_ROWS)
                locations.isEmpty() -> Text(stringResource(R.string.spool_move_none), style = MaterialTheme.typography.bodyMedium, color = colors.muted)
                else -> Column(Modifier.verticalScroll(rememberScrollState())) {
                    locations.forEach { name ->
                        val here = name == current
                        Row(
                            Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row)
                                .selectable(selected = here, enabled = m.movingTo == null, role = Role.RadioButton) { vm.move(name) },
                            horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(
                                selected = here, onClick = null,
                                colors = RadioButtonDefaults.colors(selectedColor = colors.accentText, unselectedColor = colors.borderStrong),
                            )
                            Column(Modifier.weight(1f).padding(vertical = space.s2)) {
                                Text(name, style = MaterialTheme.typography.bodyLarge)
                                when {
                                    m.movingTo == name -> Text(stringResource(R.string.spool_move_moving), style = MaterialTheme.typography.bodySmall, color = colors.muted)
                                    here -> Text(stringResource(R.string.spool_move_here), style = MaterialTheme.typography.bodySmall, color = colors.muted)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
