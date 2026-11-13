package com.thompsonfabco.filamentkit.ui.profile

import androidx.activity.compose.BackHandler
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.ui.components.HubNotice
import com.thompsonfabco.filamentkit.ui.components.HubNoticeKind
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwDialog
import com.thompsonfabco.filamentkit.ui.components.SwDialogButton
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwIconSize
import com.thompsonfabco.filamentkit.ui.components.SwMenu
import com.thompsonfabco.filamentkit.ui.components.SwMenuItem
import com.thompsonfabco.filamentkit.ui.components.SwSkeletonRows
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * "Add a line to the Filament Catalog" (05-android-app 8): the owner's own spec values for a product line, saved on
 * the Hub as a local library entry from which the slicer presets are rebuilt. Brand, line and material are needed.
 * [onBack] leaves without saving; [onSaved] leaves after a save (the shell shows the snackbar). Leaving with typing
 * asks first (2.5 rule 1).
 */
@Composable
fun AddProfileScreen(
    vm: AddProfileViewModel,
    onBack: () -> Unit,
    onSaved: () -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val space = SpoolwardenTheme.space
    var leaving by remember { mutableStateOf(false) }
    BackHandler(enabled = s.dirty) { leaving = true }
    val savedNow by rememberUpdatedState(onSaved)
    LaunchedEffect(s.saved) { if (s.saved) savedNow() }

    Column(modifier.fillMaxSize()) {
        Column(
            Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(space.s4),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Column(
                Modifier.widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(space.s3),
            ) {
                Text(stringResource(R.string.catalog_intro), style = MaterialTheme.typography.bodyMedium)
                Text(stringResource(R.string.catalog_required_note), style = MaterialTheme.typography.bodySmall)
                Group(R.string.catalog_group_line, s, vm, ProfileField.Vendor, ProfileField.Line, ProfileField.Material)
                Group(R.string.common_group_temperatures, s, vm, ProfileField.Nozzle, ProfileField.Bed)
                Group(R.string.catalog_group_material, s, vm, ProfileField.Density, ProfileField.MaxVolumetric)
                Group(R.string.catalog_group_slicer, s, vm, ProfileField.Parent)
                Group(R.string.catalog_group_notes, s, vm, ProfileField.Notes)
                ExistingLines(s, vm, onPairAgain)
                if (s.problems.isNotEmpty()) {
                    NoticeCard(
                        NoticeKind.Bad, s.problems.joinToString(System.lineSeparator()) { BULLET + it },
                        title = stringResource(R.string.catalog_refused),
                    )
                }
                FailureNotice(s.failure, s.message, onPairAgain)
            }
        }
        Column(
            Modifier.fillMaxWidth().padding(horizontal = space.s4, vertical = space.s3),
            verticalArrangement = Arrangement.spacedBy(space.s2),
        ) {
            if (!s.filled) Text(stringResource(R.string.catalog_fill), style = MaterialTheme.typography.bodySmall)
            SwButton(
                stringResource(if (s.saving) R.string.common_saving else R.string.catalog_save), vm::save,
                Modifier.fillMaxWidth(), kind = SwButtonKind.Main, enabled = s.canSave, busy = s.saving,
            )
        }
    }

    if (leaving) {
        val stay = { leaving = false }
        SwDialog(
            title = stringResource(R.string.common_leave_title),
            onClose = stay,
            confirm = SwDialogButton(
                stringResource(R.string.common_leave_without_saving),
                onClick = {
                    leaving = false
                    onBack()
                },
                kind = SwButtonKind.DestructiveFilled,
            ),
            cancel = SwAction(stringResource(R.string.common_stay), stay),
        ) {
            Text(stringResource(R.string.common_leave_body, stringResource(R.string.catalog_leave_thing)))
        }
    }
}

@Composable
private fun FailureNotice(failure: SaveFailure?, message: String?, onPairAgain: () -> Unit) {
    when (failure) {
        null -> Unit
        SaveFailure.CertificateChanged -> HubNotice(HubNoticeKind.CertificateChanged, onPairAgain)
        SaveFailure.NotPaired -> HubNotice(HubNoticeKind.NoLongerPaired, onPairAgain)
        SaveFailure.Unreachable -> NoticeCard(NoticeKind.Bad, stringResource(R.string.common_hub_unreachable))
        SaveFailure.Unknown -> NoticeCard(NoticeKind.Bad, stringResource(R.string.common_hub_answer_unknown))
        SaveFailure.Message -> NoticeCard(NoticeKind.Bad, message.orEmpty())
    }
}

/** The lines the Hub already has, each with "Change parent" (moves to the Slicer presets screen in S4.14). */
@Composable
private fun ExistingLines(s: AddProfileUiState, vm: AddProfileViewModel, onPairAgain: () -> Unit) {
    val lines = s.lines
    if (lines != null && lines.isEmpty()) return
    val space = SpoolwardenTheme.space
    val colors = SpoolwardenTheme.colors
    Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
        Text(
            stringResource(R.string.catalog_lines_title), Modifier.semantics { heading() },
            style = MaterialTheme.typography.titleSmall, color = colors.muted,
        )
        if (lines == null) {
            SwSkeletonRows(3)
            return@Column
        }
        FailureNotice(s.lineFailure, s.lineMessage, onPairAgain)
        lines.forEach { line ->
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        stringResource(R.string.catalog_line_name, line.vendor, line.product),
                        style = MaterialTheme.typography.bodyLarge,
                    )
                    Text(
                        stringResource(
                            R.string.catalog_line_material, line.material,
                            pluralStringResource(R.plurals.presets_built_presets, line.presets, line.presets),
                        ),
                        style = MaterialTheme.typography.bodySmall, color = colors.muted,
                    )
                    val parent = line.bambuParent
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(space.s1)) {
                        if (parent == null) SwIcon(R.drawable.sw_st_triangle, null, size = SwIconSize.Small, tint = colors.warn)
                        Text(
                            if (parent == null) stringResource(R.string.catalog_line_parent_none)
                            else stringResource(R.string.catalog_line_parent, parent),
                            style = MaterialTheme.typography.bodySmall, color = colors.muted,
                        )
                    }
                    if (s.parentSavedFor == line.lineId) {
                        Text(stringResource(R.string.catalog_parent_saved), style = MaterialTheme.typography.bodySmall)
                    }
                }
                Box {
                    SwButton(stringResource(R.string.catalog_change_parent), { vm.editParent(line) }, kind = SwButtonKind.Quiet)
                    val edit = s.editing?.takeIf { it.lineId == line.lineId }
                    SwMenu(expanded = edit != null, onDismiss = vm::cancelEditParent) {
                        val parents = edit?.parents
                        when {
                            parents == null -> SwMenuItem(stringResource(R.string.catalog_parent_loading), {}, modifier = Modifier.alpha(0.6f))
                            !parents.synced -> SwMenuItem(stringResource(R.string.catalog_parent_unsynced), vm::cancelEditParent)
                            else -> parents.parents.forEach { p ->
                                SwMenuItem(p, { vm.setLineParent(p) }, checked = p == line.bambuParent)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Group(@StringRes title: Int, s: AddProfileUiState, vm: AddProfileViewModel, vararg fields: ProfileField) {
    Column(verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2)) {
        Text(
            stringResource(title), Modifier.semantics { heading() },
            style = MaterialTheme.typography.titleSmall, color = SpoolwardenTheme.colors.muted,
        )
        fields.forEach { f ->
            val error = if (f in s.badRange) stringResource(R.string.catalog_error_range) else s.fieldProblems[f]
            if (f == ProfileField.Parent) {
                ParentField(
                    s.values[f].orEmpty(), s.parents, !s.saving, onPick = { vm.set(f, it) }, error = error,
                    appliesNote = true,
                )
            } else {
                OutlinedTextField(
                    value = s.values[f].orEmpty(),
                    onValueChange = { vm.set(f, it) },
                    enabled = !s.saving,
                    singleLine = f != ProfileField.Notes,
                    minLines = if (f == ProfileField.Notes) 3 else 1,
                    isError = error != null,
                    label = { Text(stringResource(f.label)) },
                    placeholder = placeholderOf(f)?.let { { Text(stringResource(it)) } },
                    supportingText = error?.let { { Text(it) } },
                    keyboardOptions = KeyboardOptions(
                        keyboardType = if (f.number) KeyboardType.Decimal else KeyboardType.Text,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

/** The bullet before each problem of the Hub's list. */
private const val BULLET = "• "

@StringRes
private fun placeholderOf(f: ProfileField): Int? = when (f) {
    ProfileField.Nozzle -> R.string.catalog_nozzle_placeholder
    ProfileField.Bed -> R.string.catalog_bed_placeholder
    else -> null
}

/**
 * The Bambu Studio parent (05-android-app 6.3): a drop-down with "Automatic" first once the Hub has the presets
 * ([ParentList.synced]); before that a plain text field, [onType] per keystroke and [onCommit] when it loses focus
 * or Done is pressed. [error] is shown under the field; [appliesNote] adds "Applies to every colour of this line."
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ParentField(
    value: String,
    parents: ParentList?,
    enabled: Boolean,
    onPick: (String) -> Unit,
    onType: (String) -> Unit = onPick,
    onCommit: () -> Unit = {},
    error: String? = null,
    appliesNote: Boolean = false,
) {
    val synced = parents?.synced == true
    val unsynced = stringResource(R.string.common_bambu_parent_unsynced)
    val leaveEmpty = stringResource(R.string.common_hint_leave_empty_auto)
    val applies = stringResource(R.string.common_bambu_parent_applies)
    val note = error ?: listOfNotNull(
        unsynced.takeIf { parents != null && !synced },
        leaveEmpty.takeIf { !synced },
        applies.takeIf { appliesNote },
    ).joinToString(" ").ifEmpty { null }
    val label: @Composable () -> Unit = { Text(stringResource(R.string.common_field_bambu_parent)) }
    val supporting: (@Composable () -> Unit)? = note?.let { { Text(it) } }
    if (!synced) {
        OutlinedTextField(
            value = value, onValueChange = onType, enabled = enabled, singleLine = true,
            isError = error != null, label = label, supportingText = supporting,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { onCommit() }),
            modifier = Modifier.fillMaxWidth().onFocusChanged { if (!it.isFocused) onCommit() },
        )
        return
    }
    var open by remember { mutableStateOf(false) }
    val automatic = stringResource(R.string.common_option_automatic)
    ExposedDropdownMenuBox(expanded = open && enabled, onExpandedChange = { open = it }) {
        OutlinedTextField(
            value = value.ifEmpty { automatic }, onValueChange = {}, readOnly = true, enabled = enabled,
            singleLine = true, isError = error != null, label = label, supportingText = supporting,
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
            modifier = Modifier.fillMaxWidth().menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable),
        )
        ExposedDropdownMenu(
            expanded = open && enabled, onDismissRequest = { open = false },
            containerColor = SpoolwardenTheme.colors.surface, shape = SpoolwardenTheme.shapes.r,
        ) {
            SwMenuItem(automatic, { onPick(""); open = false }, checked = value.isEmpty())
            parents.parents.forEach { p -> SwMenuItem(p, { onPick(p); open = false }, checked = p == value) }
        }
    }
}
