package com.thompsonfabco.filamentkit.ui.add

import android.content.Context
import androidx.compose.foundation.clickable
import androidx.compose.ui.platform.LocalContext
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.FilamentChoice
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwEmptyState
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwProgress
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass

/**
 * Step 2, "Check the spools" (05-android-app 6.3): the summary in words, the Label Reader's questions and notices, one
 * panel per proposed spool that opens in place (one at a time on a phone, any number from medium width), and the
 * sticky bar with "Back to photos" and "Preview", the reason Preview is off above it. A hand add starts with the
 * filament picker (6.4) instead of photos. Nothing here asks before leaving: the draft is saved on every change.
 */
@Composable
fun ReviewScreen(
    state: AddUiState,
    vm: AddViewModel,
    onPairAgain: () -> Unit,
    onAddByHand: () -> Unit,
    onAddCatalogLine: (vendor: String, line: String, material: String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val space = SpoolwardenTheme.space
    val wide = SpoolwardenTheme.window != WindowClass.Phone
    // the open panels live in the flow, so they are as they were after a trip to the Preview step and back
    val open = state.openPanels ?: if (state.items.isEmpty()) emptySet() else setOf(0)
    val setOpen = vm::setOpenPanels
    var picker by rememberSaveable { mutableStateOf(true) }
    val missing = state.missing
    val firstMissing = missing.indexOfFirst { it.isNotEmpty() }
    // "Fix" and "Show" and a new or restored spool open their panel; a phone keeps only that one open
    LaunchedEffect(state.focus, state.reveal) {
        val target = state.focus?.first ?: state.reveal
        if (target != null) setOpen(if (wide) open + target else setOf(target))
        if (state.reveal != null) vm.revealDone()
    }
    AddPage(
        AddStep.Check, state, modifier,
        bar = {
            state.error?.let { AddErrorNotice(it, vm, onPairAgain, onAddByHand, kept = state.draftId != null) }
            Reasons(state, missing, firstMissing, vm)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                if (!state.manual) SwButton(stringResource(R.string.add_back_to_photos), vm::backToPhotos, Modifier.weight(1f))
                SwButton(
                    stringResource(R.string.common_preview), vm::preview, Modifier.weight(1f), kind = SwButtonKind.Main,
                    enabled = state.items.isNotEmpty() && state.countsValid && state.taresValid && state.complete,
                )
            }
        },
    ) {
        state.addedBefore?.let { before ->
            NoticeCard(NoticeKind.Warn, addedBeforeText(before))
        }
        // the Hub refused a Bambu Studio parent: its words at the top as well as at the field
        state.parentError?.let { NoticeCard(NoticeKind.Bad, it) }
        if (state.items.isNotEmpty()) Summary(state, missing)
        if (state.questions.isNotEmpty()) {
            NoticeCard(
                NoticeKind.Info, state.questions.joinToString(System.lineSeparator()) { BULLET + it },
                title = stringResource(R.string.add_review_questions),
            )
        }
        state.notices.forEach { NoticeCard(NoticeKind.Info, it.string()) }
        state.tag?.let { NoticeCard(NoticeKind.Info, stringResource(R.string.add_review_tag_note, it)) }
        if (state.manual) {
            FilamentPicker(state, vm, open = picker || state.items.isEmpty(), onOpen = { picker = true }) { picker = false }
        }
        if (state.items.isEmpty()) {
            if (state.manual) {
                Text(
                    stringResource(R.string.add_review_hand_empty), style = MaterialTheme.typography.bodyMedium,
                    color = SpoolwardenTheme.colors.muted,
                )
            } else {
                SwEmptyState(
                    icon = R.drawable.sw_ic_spool,
                    title = stringResource(R.string.add_review_empty_title),
                    text = stringResource(R.string.add_review_empty_text),
                    primary = SwAction(stringResource(R.string.add_back_to_photos), vm::backToPhotos),
                    secondary = SwAction(stringResource(R.string.home_add_by_hand), onAddByHand),
                )
            }
        }
        state.items.forEachIndexed { i, _ ->
            androidx.compose.runtime.key(state.generation, i) {
                SpoolPanel(
                    state, i, expanded = i in open,
                    onToggle = { setOpen(if (i in open) open - i else if (wide) open + i else setOf(i)) },
                    focusKey = state.focus?.takeIf { it.first == i }?.second,
                    onFocused = vm::focusDone,
                    vm = vm,
                    onRemove = {
                        // the open panels after the removed one move up
                        setOpen(open.filter { it != i }.map { if (it > i) it - 1 else it }.toSet())
                        vm.removeItem(i)
                    },
                    onAddCatalogLine = onAddCatalogLine,
                )
            }
        }
    }
}

/** The summary in words: "3 spools · 2 values estimated · 1 spool needs fields" (a part that is zero is left out). */
@Composable
private fun Summary(state: AddUiState, missing: List<List<String>>) {
    val estimated = state.items.sumOf { marksOf(it, state.manual).values.count { m -> m == Mark.Estimated || m == Mark.Medium } }
    val needing = missing.count { it.isNotEmpty() }
    val spools = pluralStringResource(R.plurals.add_review_summary_spools, state.items.size, state.items.size)
    val values = if (estimated > 0) pluralStringResource(R.plurals.add_review_summary_estimated, estimated, estimated) else null
    val fields = if (needing > 0) pluralStringResource(R.plurals.add_review_summary_missing, needing, needing) else null
    Text(
        if (values != null && fields != null) stringResource(R.string.add_review_summary, spools, values, fields)
        else listOfNotNull(spools, values, fields).joinToString(" · "),
        style = MaterialTheme.typography.bodyMedium, color = SpoolwardenTheme.colors.muted,
    )
}

/** Why "Preview" is off, above the bar (never below the button), with "Show" for the spool that still needs fields. */
@Composable
private fun Reasons(state: AddUiState, missing: List<List<String>>, firstMissing: Int, vm: AddViewModel) {
    val style = MaterialTheme.typography.bodySmall
    val muted = SpoolwardenTheme.colors.muted
    when {
        state.items.isEmpty() && state.manual ->
            Text(stringResource(R.string.add_review_hand_empty), style = style, color = muted)
        !state.countsValid -> Text(stringResource(R.string.add_review_blocked_count), style = style, color = muted)
        !state.taresValid -> Text(stringResource(R.string.common_error_grams), style = style, color = muted)
        firstMissing >= 0 -> {
            val keys = missing[firstMissing]
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    stringResource(R.string.add_review_blocked_fields, firstMissing + 1, fieldNames(keys)),
                    Modifier.weight(1f), style = style, color = muted,
                )
                SwButton(stringResource(R.string.common_show), { vm.fixField(firstMissing, keys.first()) }, kind = SwButtonKind.Quiet)
            }
        }
    }
}

/** The warning that spools may exist already: the Hub's partial-failure words, or the lost reply's note. */
@Composable
internal fun addedBeforeText(before: AddedBefore): String = before.text(LocalContext.current)

/** [addedBeforeText] for a place with no composition (a snackbar of the shell). */
internal fun AddedBefore.text(context: Context): String {
    val ids = spoolIds.map { it.toInt() }
    return when {
        ids.isNotEmpty() && hubMessage != null ->
            context.resources.getQuantityString(R.plurals.add_done_partial, ids.size, hubMessage, spoolNumbersOf(ids))
        ids.isNotEmpty() -> context.getString(R.string.add_review_added_before, spoolListOf(context, ids))
        else -> context.getString(R.string.add_review_added_before, context.getString(R.string.add_review_lost_note))
    }
}

/** "212 and 213": the numbers, set in the phone's language. */
internal fun spoolNumbersOf(ids: List<Int>): String = android.icu.text.ListFormatter.getInstance().format(ids.map { it.toString() })

/** "spool 212 and spool 213". */
internal fun spoolListOf(context: Context, ids: List<Int>): String =
    android.icu.text.ListFormatter.getInstance().format(ids.map { context.getString(R.string.add_done_spool, it) })

@Composable
internal fun spoolList(ids: List<Int>): String = spoolListOf(LocalContext.current, ids)

private const val BULLET = "• "

/**
 * Hand path (05-android-app 6.4): "Find the filament" with a search that answers 300 ms after typing stops, the rows
 * of what Spoolman has (at most 20), and "New filament". After a pick it folds into "Add another filament".
 */
@Composable
private fun FilamentPicker(state: AddUiState, vm: AddViewModel, open: Boolean, onOpen: () -> Unit, onPicked: () -> Unit) {
    val space = SpoolwardenTheme.space
    val colors = SpoolwardenTheme.colors
    val enabled = state.stage == Stage.Review
    AddPanel {
        if (!open) {
            Row(
                Modifier.fillMaxWidth().defaultMinSize(minHeight = SpoolwardenTheme.sizes.row)
                    .clickable(role = Role.Button, onClick = onOpen).padding(horizontal = space.s3),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(space.s2),
            ) {
                SwIcon(R.drawable.sw_ic_plus, null, tint = colors.accentText)
                Text(stringResource(R.string.add_picker_another), style = MaterialTheme.typography.labelLarge, color = colors.accentText)
            }
            return@AddPanel
        }
        Column(Modifier.padding(space.s4), verticalArrangement = Arrangement.spacedBy(space.s3)) {
            Text(
                stringResource(R.string.add_picker_title), Modifier.semantics { heading() },
                style = MaterialTheme.typography.titleMedium,
            )
            if (state.filamentsLoading) {
                SwProgress(null)
                Text(stringResource(R.string.add_picker_looking), style = MaterialTheme.typography.bodySmall, color = colors.muted)
            }
            OutlinedTextField(
                value = state.filamentQuery, onValueChange = vm::setFilamentQuery, enabled = enabled, singleLine = true,
                label = { Text(stringResource(R.string.add_picker_label)) },
                placeholder = { Text(stringResource(R.string.add_picker_placeholder)) },
                leadingIcon = { SwIcon(R.drawable.sw_ic_search, null) },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                modifier = Modifier.fillMaxWidth(),
            )
            state.filamentsError?.let { NoticeCard(NoticeKind.Bad, it.string()) }
            if (state.filamentsError == null && !state.filamentsLoading && state.filaments.isEmpty()) {
                Text(stringResource(R.string.add_picker_none), style = MaterialTheme.typography.bodyMedium, color = colors.muted)
            }
            Column {
                state.filaments.take(AddViewModel.FILAMENTS_SHOWN).forEachIndexed { i, f ->
                    if (i > 0) HorizontalDivider(color = colors.border)
                    FilamentRow(f, enabled) {
                        vm.pickFilament(f)
                        onPicked()
                    }
                }
            }
            val shown = minOf(state.filaments.size, AddViewModel.FILAMENTS_SHOWN)
            if (state.filamentsTotal > shown) {
                Text(
                    stringResource(R.string.add_picker_more, state.filamentsTotal - shown),
                    style = MaterialTheme.typography.bodySmall, color = colors.muted,
                )
            }
            SwButton(
                stringResource(R.string.add_new_filament), { vm.newFilament(); onPicked() }, Modifier.fillMaxWidth(),
                enabled = enabled,
            )
        }
    }
}

/** A filament Spoolman has: swatch, "<brand> <name>", and "<material> · 3 spools". */
@Composable
private fun FilamentRow(f: FilamentChoice, enabled: Boolean, onPick: () -> Unit) {
    val space = SpoolwardenTheme.space
    Row(
        Modifier.fillMaxWidth().defaultMinSize(minHeight = SpoolwardenTheme.sizes.row)
            .clickable(enabled = enabled, role = Role.Button, onClick = onPick).padding(vertical = space.s2),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(space.s3),
    ) {
        ColorSwatch(f.colorHex)
        Column(Modifier.weight(1f)) {
            Text("${f.vendor} ${f.name.orEmpty()}".trim(), style = MaterialTheme.typography.bodyLarge)
            Text(
                pluralStringResource(R.plurals.add_picker_result, f.spools, f.material.orEmpty(), f.spools),
                style = MaterialTheme.typography.bodySmall, color = SpoolwardenTheme.colors.muted,
            )
        }
    }
}
