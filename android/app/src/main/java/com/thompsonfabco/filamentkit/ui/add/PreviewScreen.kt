package com.thompsonfabco.filamentkit.ui.add

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwDialog
import com.thompsonfabco.filamentkit.ui.components.SwDialogButton
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.serialization.json.JsonObject

/**
 * Step 3, "Preview" (05-android-app 6.5): the Hub's dry run runs on entry ("Checking with the Hub…"), then one row per
 * spool and "What the Hub will do" with the Hub's lines. Problems from the Hub are lines at the top, each with "Fix"
 * back to the field. "Add N spools" sends the real add ("Adding to Spoolman…"). A Hub that says these spools may have
 * been added before gets "Add these spools again?" first.
 */
@Composable
fun PreviewScreen(
    state: AddUiState,
    vm: AddViewModel,
    onPairAgain: () -> Unit,
    onAddByHand: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val space = SpoolwardenTheme.space
    val checking = state.stage == Stage.Previewing
    val adding = state.stage == Stage.Adding
    val total = state.items.sumOf { it.int("count") ?: 0 }
    AddPage(
        AddStep.Preview, state, modifier,
        bar = {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                SwButton(stringResource(R.string.add_back_to_check), vm::backToCheck, Modifier.weight(1f), enabled = !adding)
                SwButton(
                    pluralStringResource(R.plurals.add_preview_add, total, total), vm::confirm, Modifier.weight(1f),
                    kind = SwButtonKind.Main, enabled = state.stage == Stage.Preview && !state.previewFailed, busy = adding,
                )
            }
        },
    ) {
        Text(
            stringResource(R.string.add_preview_nothing_saved), style = MaterialTheme.typography.bodyMedium,
            color = SpoolwardenTheme.colors.muted,
        )
        state.addedBefore?.let { NoticeCard(NoticeKind.Warn, addedBeforeText(it)) }
        state.problems.forEach { p ->
            NoticeCard(
                NoticeKind.Bad, p.text,
                actions = listOf(
                    SwAction(stringResource(R.string.add_preview_fix)) {
                        if (p.index != null && p.key != null) vm.fixField(p.index, p.key) else vm.backToCheck()
                    },
                ),
            )
        }
        state.error?.let { AddErrorNotice(it, vm, onPairAgain, onAddByHand, kept = false) }
        when {
            checking -> AddBusy(stringResource(R.string.add_preview_checking))
            adding -> AddBusy(stringResource(R.string.add_preview_adding))
            state.stage == Stage.Preview && !state.previewFailed -> {
                AddPanel {
                    state.items.forEachIndexed { i, item ->
                        if (i > 0) HorizontalDivider(color = SpoolwardenTheme.colors.border)
                        // the Hub's own per-item answer when it gives one, else what the app holds
                        PreviewRow(item, state.previewItems.firstOrNull { it.int("index") == i } ?: state.previewItems.getOrNull(i))
                    }
                }
                if (state.previewLines.isNotEmpty()) {
                    AddPanel {
                        Column(Modifier.padding(space.s4), verticalArrangement = Arrangement.spacedBy(space.s2)) {
                            Text(
                                stringResource(R.string.add_preview_hub_does), Modifier.semantics { heading() },
                                style = MaterialTheme.typography.titleMedium,
                            )
                            // the Hub's own lines, as given
                            state.previewLines.forEach { Text(it, style = MaterialTheme.typography.bodyMedium) }
                        }
                    }
                }
            }
        }
    }
    if (state.askAddAgain) {
        SwDialog(
            title = stringResource(R.string.add_preview_again_title),
            onClose = vm::cancelAddAgain,
            confirm = SwDialogButton(
                stringResource(R.string.add_preview_again_confirm), vm::addAgain, kind = SwButtonKind.DestructiveFilled,
            ),
            cancel = SwAction(stringResource(R.string.common_cancel), vm::cancelAddAgain),
        ) {
            Text(
                stringResource(R.string.add_preview_again_body, state.addedBefore?.let { addedBeforeText(it) }.orEmpty()),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

/** One spool of the preview: swatch, name and count, where it goes, and whether the filament is new. */
@Composable
private fun PreviewRow(item: JsonObject, hub: JsonObject?) {
    val space = SpoolwardenTheme.space
    val name = "${item.str("vendor").orEmpty()} ${item.str("name").orEmpty()}".trim()
    val count = hub?.int("spools") ?: item.int("count")
    val existing = if (hub != null) {
        if (hub.str("filament") == "existing") hub.int("filament_id") else null
    } else item.int("existing_filament_id") ?: item.int(AddViewModel.FROM_FILAMENT)
    Row(
        Modifier.fillMaxWidth().defaultMinSize(minHeight = SpoolwardenTheme.sizes.row)
            .semantics(mergeDescendants = true) {}.padding(space.s3),
        verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(space.s3),
    ) {
        ColorSwatch(item.str("color_hex"))
        Column(Modifier.weight(1f)) {
            Row(horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                Text(
                    name.ifBlank { stringResource(R.string.add_new_filament) }, Modifier.weight(1f, fill = false),
                    style = MaterialTheme.typography.bodyLarge,
                )
                if (count != null && count > 1) {
                    Text(stringResource(R.string.add_review_count, count), style = SpoolwardenTheme.type.dataSmall)
                }
            }
            // where each spool goes: the Hub's placements, else the location the item names
            val places = (hub?.get("placements") as? kotlinx.serialization.json.JsonArray).orEmpty()
                .mapNotNull { (it as? JsonObject)?.str("location") }.distinct()
            val where = places.joinToString(", ").ifBlank { null } ?: hub?.str("location") ?: item.str("location")
            Text(
                listOfNotNull(
                    where,
                    if (existing != null) stringResource(R.string.add_existing_filament, existing)
                    else stringResource(R.string.add_new_filament),
                ).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = SpoolwardenTheme.colors.muted,
            )
        }
    }
}

/**
 * Step 4, "Spools added" (05-android-app 6.6): the status "Added", the new spool numbers (in `--mono`), the Hub's result
 * lines and, when a tag was sent for one spool, that it is linked. "Done" returns to Home; "Add more" starts a new draft
 * on the same path; "Open in Recently added" appears when the Hub kept a record.
 */
@Composable
fun DoneScreen(
    state: AddUiState,
    onDone: () -> Unit,
    onAddMore: () -> Unit,
    onOpenRecord: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val space = SpoolwardenTheme.space
    AddPage(
        AddStep.Done, state, modifier,
        bar = {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                SwButton(stringResource(R.string.add_done_more), onAddMore, Modifier.weight(1f))
                SwButton(stringResource(R.string.common_done), onDone, Modifier.weight(1f), kind = SwButtonKind.Main)
            }
            state.historyId?.let { hid ->
                SwButton(
                    stringResource(R.string.add_done_open_recent), { onOpenRecord(hid) }, Modifier.fillMaxWidth(),
                    kind = SwButtonKind.Quiet,
                )
            }
        },
    ) {
        AddStatusLine(AddStatus.Ok, stringResource(R.string.add_done_status))
        Text(
            if (state.spoolIds.isEmpty()) stringResource(R.string.add_done_none)
            else stringResource(R.string.add_done_new, spoolList(state.spoolIds)),
            style = if (state.spoolIds.isEmpty()) MaterialTheme.typography.bodyMedium else SpoolwardenTheme.type.data,
        )
        val tag = state.doneTag
        if (tag != null && state.spoolIds.size == 1) {
            Text(
                stringResource(R.string.add_done_tag_linked, tag, state.spoolIds.single()),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
        if (state.resultLines.isNotEmpty()) {
            AddPanel {
                Column(Modifier.padding(space.s4), verticalArrangement = Arrangement.spacedBy(space.s2)) {
                    // the Hub's own lines, as given
                    state.resultLines.forEach { Text(it, style = MaterialTheme.typography.bodyMedium) }
                }
            }
        }
    }
}
