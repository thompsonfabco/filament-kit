package com.thompsonfabco.filamentkit.ui.presets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ProfileLine
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.net.UncoveredFilament
import com.thompsonfabco.filamentkit.ui.components.DetailPresentation
import com.thompsonfabco.filamentkit.ui.components.HubNotice
import com.thompsonfabco.filamentkit.ui.components.HubNoticeKind
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwCardDetail
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwIconSize
import com.thompsonfabco.filamentkit.ui.components.SwMenuItem
import com.thompsonfabco.filamentkit.ui.components.SwSheet
import com.thompsonfabco.filamentkit.ui.components.SwSkeletonRows
import com.thompsonfabco.filamentkit.ui.components.rememberDetailPresentation
import com.thompsonfabco.filamentkit.ui.components.requestDetailFocus
import com.thompsonfabco.filamentkit.ui.home.PresetMark
import com.thompsonfabco.filamentkit.ui.home.PresetRow
import com.thompsonfabco.filamentkit.ui.home.PresetUpdatesDialog
import com.thompsonfabco.filamentkit.ui.home.PresetUpdatesViewModel
import com.thompsonfabco.filamentkit.ui.home.presetActions
import com.thompsonfabco.filamentkit.ui.home.presetAge
import com.thompsonfabco.filamentkit.ui.home.presetLines
import com.thompsonfabco.filamentkit.ui.home.updatesButton
import com.thompsonfabco.filamentkit.ui.printers.FormField
import com.thompsonfabco.filamentkit.ui.profile.SaveFailure
import com.thompsonfabco.filamentkit.ui.settings.SettingsPanel
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * Slicer presets (05-android-app 11.2): the build status and Build presets now, the filaments without a preset line (add to
 * a line or start one), the Product lines panel with "Change parent", the Updates panel, and a way to the Filament Catalog.
 * The shell draws the top bar. [onAddCatalogLine] opens the catalog form (05 8). [updates] is the Updates list (null: no
 * Updates panel). [nowMillis] is the time ages count from (null: the clock). [pairing] is the session's pairing count: when
 * the phone pairs again (also with the same Hub) it is another one and the screen reads everything again.
 */
@Composable
fun PresetsScreen(
    vm: PresetsViewModel,
    onPairAgain: () -> Unit,
    onAddCatalogLine: () -> Unit,
    modifier: Modifier = Modifier,
    nowMillis: Long? = null,
    pairing: Any? = null,
    updates: PresetUpdatesViewModel? = null,
) {
    val s by vm.state.collectAsStateWithLifecycle()
    val space = SpoolwardenTheme.space
    val context = LocalContext.current
    val toast = LocalToast.current
    val done = s.done
    // the card has left the list, so its result is a toast (05-android-app 3.2)
    LaunchedEffect(done) {
        if (done != null) {
            vm.doneShown()
            toast?.show(context.getString(if (done.created) R.string.presets_created else R.string.presets_added, done.name))
        }
    }
    LaunchedEffect(pairing) { vm.pairedWith(pairing) }
    val now = remember(nowMillis) { nowMillis ?: System.currentTimeMillis() }
    val presentation = rememberDetailPresentation()
    val useCardDetail = presentation == DetailPresentation.Card
    val lineFocus = remember { mutableMapOf<String, FocusRequester>() }
    var returnFocusLineId by remember { mutableStateOf<String?>(null) }
    val view = LocalView.current
    LaunchedEffect(returnFocusLineId) {
        val id = returnFocusLineId ?: return@LaunchedEffect
        repeat(2) { withFrameNanos { } }
        lineFocus[id]?.let { requestDetailFocus(it, view) }
        returnFocusLineId = null
    }
    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(space.s4),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Column(
            Modifier.widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(space.s3),
        ) {
            StatusPanel(s, vm, now, onPairAgain)
            NoticeCard(NoticeKind.Info, stringResource(R.string.presets_info))
            SettingsPanel {
                SectionTitle(stringResource(R.string.presets_missing_title))
                Text(stringResource(R.string.presets_missing_text), style = MaterialTheme.typography.bodyMedium)
                SwButton(stringResource(R.string.catalog_add_line), onAddCatalogLine, Modifier.fillMaxWidth())
            }
            UncoveredPanel(s, vm, onPairAgain)
            LinesPanel(
                s, vm, onPairAgain,
                useCardDetail = useCardDetail,
                lineFocus = lineFocus,
                onCloseCard = { lineId ->
                    vm.closeParent()
                    returnFocusLineId = lineId
                },
            )
            if (updates != null) UpdatesPanel(s.status, updates, onChanged = vm::reload)
        }
    }
    if (!useCardDetail) {
        s.edit?.let { ParentSheet(it, vm, onPairAgain) }
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(text, Modifier.semantics { heading() }, style = MaterialTheme.typography.titleMedium)
}

/** The status lines of 11.1 as field rows (Built, Last build, On your PC), then Build now and its answer. */
@Composable
private fun StatusPanel(s: PresetsUiState, vm: PresetsViewModel, now: Long, onPairAgain: () -> Unit) {
    val resources = LocalContext.current.resources
    val colors = SpoolwardenTheme.colors
    SettingsPanel {
        val status = s.status
        when {
            !s.statusLoaded -> SwSkeletonRows(2)
            status == null ->
                Text(stringResource(R.string.presets_status_unavailable), style = MaterialTheme.typography.bodyMedium, color = colors.muted)
            else -> presetLines(status, resources) { presetAge(resources, it, now) }.forEach { line ->
                val label = stringResource(
                    when (line.row) {
                        PresetRow.Built -> R.string.presets_field_built
                        PresetRow.LastBuild -> R.string.presets_field_last_build
                        PresetRow.OnPc -> R.string.presets_field_on_pc
                    },
                )
                Column(Modifier.fillMaxWidth().semantics(mergeDescendants = true) {}) {
                    Text(label, color = colors.muted, style = MaterialTheme.typography.bodySmall)
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        line.mark?.let { mark ->
                            SwIcon(
                                mark.shape, null, size = SwIconSize.Small,
                                tint = when (mark) {
                                    PresetMark.NotYet -> colors.warn
                                    PresetMark.Installed -> colors.ok
                                    PresetMark.NotSetUp -> colors.muted
                                },
                            )
                        }
                        Text(line.text, style = MaterialTheme.typography.bodyMedium, color = if (line.error) colors.bad else colors.text)
                    }
                }
            }
        }
        if (s.buildMissing) {
            // a Hub without the build route: no button (05 11.2)
            NoticeCard(NoticeKind.Info, stringResource(R.string.presets_build_elsewhere))
        } else {
            SwButton(
                stringResource(if (s.building) R.string.presets_building else R.string.presets_build), vm::build,
                Modifier.fillMaxWidth(), kind = SwButtonKind.Main, busy = s.building,
            )
        }
        when (val note = s.buildNote) {
            null -> Unit
            is BuildNote.Asked -> Text(
                note.summary.ifBlank { stringResource(R.string.presets_result_build_requested) },
                Modifier.semantics { liveRegion = LiveRegionMode.Polite }, style = MaterialTheme.typography.bodyMedium,
            )
            is BuildNote.Failed -> FailureNotice(note.fail, onPairAgain)
        }
    }
}

/** A failed Hub call as a notice; [onTryAgain] adds the button to the ones that are about reaching the Hub. */
@Composable
private fun FailureNotice(fail: Fail, onPairAgain: () -> Unit, onTryAgain: (() -> Unit)? = null) {
    val again = onTryAgain?.let { listOf(SwAction(stringResource(R.string.common_try_again), it)) }.orEmpty()
    when (fail.kind) {
        SaveFailure.CertificateChanged -> HubNotice(HubNoticeKind.CertificateChanged, onPairAgain)
        SaveFailure.NotPaired -> HubNotice(HubNoticeKind.NoLongerPaired, onPairAgain)
        SaveFailure.Unreachable -> NoticeCard(NoticeKind.Bad, stringResource(R.string.common_hub_unreachable), actions = again)
        SaveFailure.Unknown -> NoticeCard(NoticeKind.Bad, stringResource(R.string.common_hub_answer_unknown), actions = again)
        SaveFailure.Message -> NoticeCard(NoticeKind.Bad, fail.message.orEmpty(), actions = again)
    }
}

// ---- filaments without a preset line ----------------------------------------------------------------------------

@Composable
private fun UncoveredPanel(s: PresetsUiState, vm: PresetsViewModel, onPairAgain: () -> Unit) {
    val list = s.uncovered
    SettingsPanel {
        val fail = s.uncoveredFail
        Row(horizontalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2), verticalAlignment = Alignment.CenterVertically) {
            SectionTitle(stringResource(R.string.presets_without_line))
            if (list != null && fail == null) {
                Text(list.size.toString(), style = MaterialTheme.typography.titleMedium, color = SpoolwardenTheme.colors.muted)
            }
        }
        when {
            list == null -> SwSkeletonRows(3)
            fail != null -> FailureNotice(fail, onPairAgain, vm::loadUncovered)
            list.isEmpty() -> Row(
                horizontalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2), verticalAlignment = Alignment.CenterVertically,
            ) {
                SwIcon(R.drawable.sw_st_filled, null, size = SwIconSize.Small, tint = SpoolwardenTheme.colors.ok)
                Text(stringResource(R.string.presets_all_done), style = MaterialTheme.typography.bodyMedium)
            }
            else -> list.forEachIndexed { i, f ->
                if (i > 0) HorizontalDivider(color = SpoolwardenTheme.colors.border, thickness = SpoolwardenTheme.sizes.hairline)
                FilamentCardView(f, s.card(f.id), vm, onPairAgain)
            }
        }
    }
}

/** One filament without a line: add it to a line of its brand, or start a new line from it. */
@Composable
private fun FilamentCardView(f: UncoveredFilament, card: FilamentCard, vm: PresetsViewModel, onPairAgain: () -> Unit) {
    val space = SpoolwardenTheme.space
    val idle = card.busy == null
    Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
        Text(stringResource(R.string.presets_filament_title, f.vendor, f.name), style = MaterialTheme.typography.bodyLarge)
        Text(
            stringResource(R.string.presets_filament_meta, f.material, f.id.toString()),
            style = MaterialTheme.typography.bodySmall, color = SpoolwardenTheme.colors.muted,
        )
        if (f.linesForVendor.isNotEmpty()) {
            PickField(
                stringResource(R.string.presets_add_select), card.line ?: f.linesForVendor.first(), f.linesForVendor, idle,
                onPick = { vm.chooseLine(f.id, it) },
            )
            SwButton(
                stringResource(R.string.presets_add_button), { vm.addToLine(f) }, Modifier.fillMaxWidth(),
                enabled = idle, busy = card.busy == CardBusy.Adding,
            )
        }
        SwButton(
            stringResource(if (f.linesForVendor.isNotEmpty()) R.string.presets_new_line_with_lines else R.string.presets_new_line_none),
            { vm.toggleNewLine(f) }, kind = SwButtonKind.Quiet, enabled = idle,
        )
        if (card.newLineOpen) NewLineForm(f, card, vm)
        // a refusal that names a field of the form is shown under that field
        val inline = card.newLineOpen && card.fail?.field in INLINE_FIELDS
        card.fail?.takeIf { !inline }?.let { FailureNotice(it, onPairAgain) }
    }
}

/** The fields a 400 may name that the form has: the line name and the parent (the Hub says `parent` or `orca_parent`). */
private const val NAME_FIELD = "name"
private const val ORCA_FIELD = "orca_parent"
private val PARENT_FIELDS = listOf("parent", ORCA_FIELD, "bs_template")
private val INLINE_FIELDS = listOf(NAME_FIELD) + PARENT_FIELDS

@Composable
private fun NewLineForm(f: UncoveredFilament, card: FilamentCard, vm: PresetsViewModel) {
    val idle = card.busy == null
    val templates = card.templates
    val fail = card.fail
    FormField(
        card.name, { vm.setName(f.id, it) }, stringResource(R.string.presets_line_name), enabled = idle,
        hint = stringResource(R.string.presets_line_name_help), error = fail?.takeIf { it.field == NAME_FIELD }?.message,
    )
    val orca = card.orcaParents
    // the Orca Slicer parent is optional; without its field a refusal that names it goes under the template field
    val orcaShown = !orca.isNullOrEmpty()
    if (templates?.synced == true) {
        FormField(card.find, { vm.findTemplate(f.id, it) }, stringResource(R.string.presets_parent), enabled = idle)
    }
    when {
        orca == null -> Text(stringResource(R.string.presets_parent_loading), style = MaterialTheme.typography.bodySmall)
        orca.isEmpty() -> Text(
            stringResource(R.string.presets_orca_none), style = MaterialTheme.typography.bodySmall,
            color = SpoolwardenTheme.colors.muted,
        )
        else -> {
            val unset = stringResource(R.string.presets_orca_unset)
            PickField(
                stringResource(R.string.presets_orca_parent), card.orcaParent ?: unset, listOf(unset) + orca, idle,
                onPick = { vm.chooseOrcaParent(f.id, it.takeIf { p -> p != unset }) },
                error = fail?.takeIf { it.field == ORCA_FIELD }?.message,
            )
        }
    }
    when {
        templates == null -> Text(stringResource(R.string.presets_parent_loading), style = MaterialTheme.typography.bodySmall)
        !templates.synced -> Text(
            stringResource(R.string.presets_templates_none), style = MaterialTheme.typography.bodySmall,
            color = SpoolwardenTheme.colors.muted,
        )
        else -> PickField(
            stringResource(R.string.presets_bs_template), card.template.orEmpty(), matchParents(templates.parents, card.find), idle,
            onPick = { vm.chooseTemplate(f.id, it) },
            error = fail?.takeIf { it.field in PARENT_FIELDS && (it.field != ORCA_FIELD || !orcaShown) }?.message,
        )
    }
    SwButton(
        stringResource(R.string.presets_create), { vm.createLine(f) }, Modifier.fillMaxWidth(),
        enabled = idle && card.template != null && card.name.isNotBlank(), busy = card.busy == CardBusy.Creating,
    )
}

/** A read-only field that opens the list of [options] (a drop-down); [error] is shown under it. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PickField(
    label: String,
    value: String,
    options: List<String>,
    enabled: Boolean,
    onPick: (String) -> Unit,
    error: String? = null,
) {
    var open by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded = open && enabled, onExpandedChange = { open = it }) {
        OutlinedTextField(
            value = value, onValueChange = {}, readOnly = true, enabled = enabled, singleLine = true,
            isError = error != null, label = { Text(label) }, supportingText = error?.let { { Text(it) } },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) }, shape = SpoolwardenTheme.shapes.r,
            modifier = Modifier.fillMaxWidth().menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable),
        )
        ExposedDropdownMenu(
            expanded = open && enabled, onDismissRequest = { open = false },
            containerColor = SpoolwardenTheme.colors.surface, shape = SpoolwardenTheme.shapes.r,
        ) {
            options.forEach { o -> SwMenuItem(o, { onPick(o); open = false }, checked = o == value) }
        }
    }
}

// ---- product lines ----------------------------------------------------------------------------------------------

@Composable
private fun LinesPanel(
    s: PresetsUiState,
    vm: PresetsViewModel,
    onPairAgain: () -> Unit,
    useCardDetail: Boolean = false,
    lineFocus: MutableMap<String, FocusRequester> = mutableMapOf(),
    onCloseCard: (String) -> Unit = {},
) {
    val lines = s.lines
    SettingsPanel {
        SectionTitle(stringResource(R.string.presets_lines_title))
        if (lines == null) {
            SwSkeletonRows(3)
            return@SettingsPanel
        }
        s.linesFail?.let { FailureNotice(it, onPairAgain, vm::loadLines) }
        if (lines.isEmpty() && s.linesFail == null) {
            Text(stringResource(R.string.presets_lines_empty), style = MaterialTheme.typography.bodyMedium)
        }
        lines.take(s.shown).forEachIndexed { i, line ->
            if (i > 0) HorizontalDivider(color = SpoolwardenTheme.colors.border, thickness = SpoolwardenTheme.sizes.hairline)
            val requester = lineFocus.getOrPut(line.lineId) { FocusRequester() }
            val editing = useCardDetail && s.edit?.lineId == line.lineId
            LineRow(
                line, saved = s.savedFor == line.lineId,
                buttonModifier = Modifier.focusRequester(requester),
                onChange = {
                    if (editing) onCloseCard(line.lineId) else vm.editParent(line)
                },
            )
            if (editing) {
                val edit = s.edit
                HorizontalDivider(color = SpoolwardenTheme.colors.border, thickness = SpoolwardenTheme.sizes.hairline)
                SwCardDetail(onClose = { onCloseCard(line.lineId) }) {
                    ParentEditorBody(edit, vm, onPairAgain, onClose = { onCloseCard(line.lineId) })
                }
            }
        }
        if (lines.size > s.shown) SwButton(stringResource(R.string.presets_lines_more), vm::showMore, kind = SwButtonKind.Quiet)
    }
}

/** One product line: "<brand> <line>", "<material> · <n> presets", its Bambu Studio parent (a triangle when none), Change parent. */
@Composable
private fun LineRow(
    line: ProfileLine,
    saved: Boolean,
    buttonModifier: Modifier = Modifier,
    onChange: () -> Unit,
) {
    val space = SpoolwardenTheme.space
    val colors = SpoolwardenTheme.colors
    val name = stringResource(R.string.presets_line_title, line.vendor, line.product)
    val changeFor = stringResource(R.string.presets_change_parent_for, name)
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(name, style = MaterialTheme.typography.bodyLarge)
            Text(
                stringResource(
                    R.string.presets_line_material, line.material,
                    pluralStringResource(R.plurals.presets_built_presets, line.presets, line.presets),
                ),
                style = MaterialTheme.typography.bodySmall, color = colors.muted,
            )
            val parent = line.bambuParent
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(space.s1)) {
                if (parent == null) SwIcon(R.drawable.sw_st_triangle, null, size = SwIconSize.Small, tint = colors.warn)
                Text(
                    if (parent == null) stringResource(R.string.presets_line_parent_none)
                    else stringResource(R.string.presets_line_parent, parent),
                    style = MaterialTheme.typography.bodySmall, color = colors.muted,
                )
            }
            if (saved) {
                Text(
                    stringResource(R.string.presets_line_saved), Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
        SwButton(
            stringResource(R.string.presets_change_parent), onChange,
            buttonModifier.semantics { contentDescription = changeFor }, kind = SwButtonKind.Quiet,
        )
    }
}

/** The sheet "Bambu Studio parent of <line>" (05-android-app 11.2): find a parent, pick one, Save or Cancel. */
@Composable
private fun ParentSheet(edit: ParentEdit, vm: PresetsViewModel, onPairAgain: () -> Unit) {
    SwSheet(onDismiss = vm::closeParent, gesturesEnabled = !edit.saving) {
        ParentEditorBody(edit, vm, onPairAgain, onClose = vm::closeParent)
    }
}

@Composable
private fun ParentEditorBody(
    edit: ParentEdit,
    vm: PresetsViewModel,
    onPairAgain: () -> Unit,
    onClose: () -> Unit,
) {
    val space = SpoolwardenTheme.space
    Column(
        Modifier.fillMaxWidth().padding(horizontal = space.s4).padding(bottom = space.s4),
        verticalArrangement = Arrangement.spacedBy(space.s3),
    ) {
        SectionTitle(stringResource(R.string.presets_parent_sheet_title, edit.line))
        val parents = edit.parents
        val fail = edit.fail
        when {
            parents == null && fail != null -> {
                FailureNotice(fail, onPairAgain)
                SwButton(stringResource(R.string.common_close), onClose, Modifier.fillMaxWidth())
            }
            parents == null -> Text(stringResource(R.string.presets_parent_loading), style = MaterialTheme.typography.bodyMedium)
            !parents.synced -> {
                Text(stringResource(R.string.presets_parent_unreported), style = MaterialTheme.typography.bodyMedium)
                SwButton(stringResource(R.string.common_close), onClose, Modifier.fillMaxWidth())
            }
            else -> {
                FormField(edit.query, vm::findParent, stringResource(R.string.presets_parent), enabled = !edit.saving)
                val matches = edit.matches
                Column(Modifier.heightIn(max = SpoolwardenTheme.sizes.qr).verticalScroll(rememberScrollState())) {
                    if (matches.isEmpty()) {
                        Text(stringResource(R.string.presets_parent_no_match), style = MaterialTheme.typography.bodyMedium)
                    }
                    matches.take(MATCH_CAP).forEach { p ->
                        val picked = p == edit.picked
                        Row(
                            Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row)
                                .selectable(picked, enabled = !edit.saving, role = Role.RadioButton) { vm.pickParent(p) },
                            horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(picked, onClick = null)
                            Text(p, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
                fail?.let { FailureNotice(it, onPairAgain) }
                SwButton(
                    stringResource(R.string.presets_sheet_save), vm::saveParent, Modifier.fillMaxWidth(),
                    kind = SwButtonKind.Main, enabled = edit.picked != null && edit.picked != edit.current,
                    busy = edit.saving,
                )
                SwButton(
                    stringResource(R.string.common_cancel), onClose, Modifier.fillMaxWidth(),
                    kind = SwButtonKind.Quiet, enabled = !edit.saving,
                )
            }
        }
    }
}

/** The matches listed at once; typing in "Find a parent" narrows the rest. */
private const val MATCH_CAP = 50

// ---- updates ----------------------------------------------------------------------------------------------------

/** The last panel: how many updates wait and the button that opens the Updates list (accept, restore deleted presets). */
@Composable
private fun UpdatesPanel(status: ProfileStatus?, updates: PresetUpdatesViewModel, onChanged: () -> Unit) {
    val resources = LocalContext.current.resources
    var open by remember { mutableStateOf(false) }
    SettingsPanel {
        SectionTitle(stringResource(R.string.presets_updates_title))
        val actions = status?.let { presetActions(it, resources) }
        actions?.hints?.forEach { Text(it, style = MaterialTheme.typography.bodyMedium) }
        SwButton(
            actions?.let { updatesButton(it, resources) } ?: stringResource(R.string.presets_updates_title),
            { updates.load(); open = true }, Modifier.fillMaxWidth(), kind = SwButtonKind.Quiet,
        )
    }
    if (open) PresetUpdatesDialog(updates, onClose = { open = false; onChanged() })
}
