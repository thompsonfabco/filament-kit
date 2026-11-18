package com.thompsonfabco.filamentkit.ui.profile

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.LocalEntry
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.ui.components.HubNotice
import com.thompsonfabco.filamentkit.ui.components.HubNoticeKind
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwDialog
import com.thompsonfabco.filamentkit.ui.components.SwDialogButton
import com.thompsonfabco.filamentkit.ui.components.SwMenuItem
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.launch

/**
 * "Add a line to the Filament Catalog" (05-android-app 8, R83 section 4): Brand, Name and Material, and under the
 * closed "More (optional)" the other values; the Hub builds the entry from them and the slicer presets are rebuilt
 * from it. "See custom entries" lists the owner's own entries, each with Remove (asks first). [onBack] leaves without
 * adding; [onSaved] leaves after an add through a Hub that has no form route (the shell shows the snackbar); an add
 * through the form stays here, empty, with "Added." Leaving with typing asks first (2.5 rule 1); while an add runs
 * Back does nothing but say why (rule 2). Without a pairing the form stays and the Hub notice sits where the result
 * would ([paired] false, 2.7).
 */
@Composable
fun AddProfileScreen(
    vm: AddProfileViewModel,
    onBack: () -> Unit,
    onSaved: () -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
    paired: Boolean = true,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val space = SpoolwardenTheme.space
    var leaving by remember { mutableStateOf(false) }
    val toast = LocalToast.current
    val scope = rememberCoroutineScope()
    val wait = stringResource(R.string.catalog_saving_wait)
    BackHandler(enabled = s.dirty) { leaving = true }
    // registered last, so it wins while a save runs
    BackHandler(enabled = s.saving) { scope.launch { toast?.show(wait) } }
    val savedNow by rememberUpdatedState(onSaved)
    LaunchedEffect(s.saved) { if (s.saved) savedNow() }

    // only the phone becoming paired clears an old failure; coming back to the screen does not
    var wasPaired by rememberSaveable { mutableStateOf(paired) }
    LaunchedEffect(paired) {
        if (paired && !wasPaired) vm.onPaired()
        wasPaired = paired
    }

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
                // the optional values stay closed until asked for, or until the Hub names one of them
                var more by rememberSaveable { mutableStateOf(false) }
                val named = s.fieldProblems.keys.any { it.optional }
                SwButton(
                    CatalogTexts.MORE, { more = !more }, Modifier.semantics { contentDescription = CatalogTexts.MORE },
                    kind = SwButtonKind.Quiet,
                )
                if (more || named) {
                    Group(R.string.common_group_temperatures, s, vm, ProfileField.NozzleMin, ProfileField.NozzleMax, ProfileField.BedMin, ProfileField.BedMax)
                    Group(R.string.catalog_group_material, s, vm, ProfileField.Density, ProfileField.MaxVolumetric)
                    Group(R.string.catalog_group_slicer, s, vm, ProfileField.Parent)
                    Group(R.string.catalog_group_notes, s, vm, ProfileField.Notes)
                }
                EntriesSection(s, vm, onPairAgain)
            }
        }
        // the action bar stays in view; what the save answered sits directly above it (05 8, 6.2)
        Column(
            Modifier.fillMaxWidth().padding(horizontal = space.s4, vertical = space.s3),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Column(
                Modifier.widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(space.s2),
            ) {
                Column(
                    Modifier.heightIn(max = SpoolwardenTheme.sizes.qr).verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(space.s2),
                ) {
                    if (s.problems.isNotEmpty()) {
                        NoticeCard(
                            NoticeKind.Bad, s.problems.joinToString(System.lineSeparator()) { BULLET + it },
                            title = stringResource(R.string.catalog_refused),
                        )
                    }
                    FailureNotice(s.failure, s.message, onPairAgain)
                    // an add through the form says so; the form is empty again for the next one
                    if (s.added) {
                        NoticeCard(NoticeKind.Ok, CatalogTexts.ADDED, Modifier.semantics { liveRegion = LiveRegionMode.Polite })
                    }
                    // the reason Save is off when the phone is not paired
                    if (!paired) HubNotice(HubNoticeKind.NoLongerPaired, onPairAgain)
                }
                if (!s.filled) Text(CatalogTexts.FILL, style = MaterialTheme.typography.bodySmall)
                SwButton(
                    if (s.saving) stringResource(R.string.common_saving) else CatalogTexts.ADD, vm::save,
                    Modifier.fillMaxWidth(), kind = SwButtonKind.Main, enabled = s.canSave && paired, busy = s.saving,
                )
            }
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
                enabled = !s.saving,
            ),
            cancel = SwAction(stringResource(R.string.common_stay), stay),
        ) {
            Text(stringResource(R.string.common_leave_body, stringResource(R.string.catalog_leave_thing)))
        }
    }
}

/** The label of one field of the form. */
@Composable
private fun labelOf(f: ProfileField): String = when (f) {
    ProfileField.Vendor -> stringResource(R.string.catalog_field_brand)
    ProfileField.Line -> CatalogTexts.NAME
    ProfileField.Material -> CatalogTexts.MATERIAL
    ProfileField.NozzleMin -> CatalogTexts.NOZZLE_MIN
    ProfileField.NozzleMax -> CatalogTexts.NOZZLE_MAX
    ProfileField.BedMin -> CatalogTexts.BED_MIN
    ProfileField.BedMax -> CatalogTexts.BED_MAX
    ProfileField.Density -> stringResource(R.string.catalog_field_density)
    ProfileField.MaxVolumetric -> stringResource(R.string.catalog_field_max_speed)
    ProfileField.Parent -> stringResource(R.string.common_field_bambu_parent)
    ProfileField.Notes -> stringResource(R.string.common_field_notes)
}

/** "See custom entries": the list of the owner's own entries, each with Remove; Remove asks first. */
@Composable
private fun EntriesSection(s: AddProfileUiState, vm: AddProfileViewModel, onPairAgain: () -> Unit) {
    val space = SpoolwardenTheme.space
    val colors = SpoolwardenTheme.colors
    SwButton(
        if (s.entriesOpen) CatalogTexts.HIDE_ENTRIES else CatalogTexts.SEE_ENTRIES, vm::toggleEntries,
        kind = SwButtonKind.Quiet,
    )
    if (!s.entriesOpen) return
    Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
        FailureNotice(s.entriesFailure, s.entriesMessage, onPairAgain)
        val entries = s.entries
        when {
            s.entriesUnavailable -> Text(CatalogTexts.ENTRIES_UPDATE_HUB, style = MaterialTheme.typography.bodyMedium, color = colors.muted)
            entries == null -> if (s.entriesLoading) Text(CatalogTexts.ENTRIES_LOADING, style = MaterialTheme.typography.bodyMedium, color = colors.muted)
            entries.isEmpty() -> Text(CatalogTexts.ENTRIES_EMPTY, style = MaterialTheme.typography.bodyMedium, color = colors.muted)
            else -> entries.forEach { EntryRow(it, vm) }
        }
    }
    s.removeAsk?.let { RemoveDialog(it, s, vm) }
}

@Composable
private fun EntryRow(entry: LocalEntry, vm: AddProfileViewModel) {
    val space = SpoolwardenTheme.space
    val line = CatalogTexts.entryLine(entry.brand, entry.name)
    Row(
        Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row),
        horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(line, style = MaterialTheme.typography.bodyLarge)
            val detail = CatalogTexts.entryDetail(entry.material, entry.added)
            if (detail.isNotEmpty()) Text(detail, style = MaterialTheme.typography.bodySmall, color = SpoolwardenTheme.colors.muted)
        }
        SwButton(
            CatalogTexts.REMOVE, { vm.askRemove(entry) },
            Modifier.semantics { contentDescription = "${CatalogTexts.REMOVE} $line" }, kind = SwButtonKind.Plain,
        )
    }
}

@Composable
private fun RemoveDialog(entry: LocalEntry, s: AddProfileUiState, vm: AddProfileViewModel) {
    SwDialog(
        title = CatalogTexts.removeTitle(entry.brand, entry.name),
        onClose = vm::cancelRemove,
        confirm = SwDialogButton(CatalogTexts.REMOVE, vm::confirmRemove, kind = SwButtonKind.DestructiveFilled, busy = s.removing),
        cancel = SwAction(stringResource(R.string.common_cancel), vm::cancelRemove),
        cancelEnabled = !s.removing,
    ) {
        Text(CatalogTexts.removeQuestion(entry.brand, entry.name), style = MaterialTheme.typography.bodyMedium)
    }
}

/** A failed Hub call as a notice. */
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

@Composable
private fun Group(@androidx.annotation.StringRes title: Int, s: AddProfileUiState, vm: AddProfileViewModel, vararg fields: ProfileField) {
    Column(verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2)) {
        Text(
            stringResource(title), Modifier.semantics { heading() },
            style = MaterialTheme.typography.titleSmall, color = SpoolwardenTheme.colors.muted,
        )
        fields.forEach { f ->
            val error = s.fieldProblems[f]
            if (f == ProfileField.Parent) {
                CatalogParentField(s.values[f].orEmpty(), s.parents, !s.saving, onPick = { vm.set(f, it) }, error = error)
            } else if (f == ProfileField.Material) {
                MaterialField(s.values[f].orEmpty(), s.materials ?: CatalogTexts.MATERIALS, !s.saving, onPick = { vm.set(f, it) }, error = error)
            } else {
                OutlinedTextField(
                    value = s.values[f].orEmpty(),
                    onValueChange = { vm.set(f, it) },
                    enabled = !s.saving,
                    singleLine = f != ProfileField.Notes,
                    minLines = if (f == ProfileField.Notes) 3 else 1,
                    isError = error != null,
                    label = { Text(labelOf(f)) },
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

/**
 * Material is a choice from the materials the form offers, with "Other" and a text field under it for anything else
 * (R83 section 4.1). What is chosen or typed is the field's value; [error] shows under whichever is on screen.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MaterialField(value: String, materials: List<String>, enabled: Boolean, onPick: (String) -> Unit, error: String?) {
    var other by rememberSaveable { mutableStateOf(value.isNotBlank() && value !in materials) }
    var open by remember { mutableStateOf(false) }
    val shown = if (other) CatalogTexts.MATERIAL_OTHER else value
    ExposedDropdownMenuBox(expanded = open && enabled, onExpandedChange = { open = it }) {
        OutlinedTextField(
            value = shown, onValueChange = {}, readOnly = true, enabled = enabled, singleLine = true,
            isError = error != null && !other, label = { Text(CatalogTexts.MATERIAL) },
            supportingText = error?.takeIf { !other }?.let { { Text(it) } },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
            modifier = Modifier.fillMaxWidth().menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable),
        )
        ExposedDropdownMenu(
            expanded = open && enabled, onDismissRequest = { open = false },
            containerColor = SpoolwardenTheme.colors.surface, shape = SpoolwardenTheme.shapes.r,
        ) {
            materials.forEach { m ->
                SwMenuItem(m, { other = false; onPick(m); open = false }, checked = !other && m == value)
            }
            SwMenuItem(CatalogTexts.MATERIAL_OTHER, { if (!other) onPick(""); other = true; open = false }, checked = other)
        }
    }
    if (other) {
        OutlinedTextField(
            value = value, onValueChange = onPick, enabled = enabled, singleLine = true,
            isError = error != null, label = { Text(CatalogTexts.MATERIAL_OTHER_FIELD) },
            supportingText = error?.let { { Text(it) } },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

/**
 * The catalog screen's Bambu Studio parent (05-android-app 6.3): a drop-down with "Automatic" first once the Hub has
 * the presets ([ParentList.synced]); before that a plain text field. [error] is shown under the field, and "Applies
 * to every colour of this line." stays under it either way.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CatalogParentField(
    value: String,
    parents: ParentList?,
    enabled: Boolean,
    onPick: (String) -> Unit,
    error: String? = null,
) {
    val synced = parents?.synced == true
    val unsynced = stringResource(R.string.common_bambu_parent_unsynced)
    val leaveEmpty = stringResource(R.string.common_hint_leave_empty_auto)
    val applies = stringResource(R.string.common_bambu_parent_applies)
    val note = listOfNotNull(
        error,
        unsynced.takeIf { error == null && parents != null && !synced },
        leaveEmpty.takeIf { error == null && !synced },
        applies,
    ).joinToString(" ")
    val label: @Composable () -> Unit = { Text(stringResource(R.string.common_field_bambu_parent)) }
    val supporting: @Composable () -> Unit = { Text(note) }
    if (!synced) {
        OutlinedTextField(
            value = value, onValueChange = onPick, enabled = enabled, singleLine = true,
            isError = error != null, label = label, supportingText = supporting,
            modifier = Modifier.fillMaxWidth(),
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
            parents?.parents.orEmpty().forEach { p -> SwMenuItem(p, { onPick(p); open = false }, checked = p == value) }
        }
    }
}
