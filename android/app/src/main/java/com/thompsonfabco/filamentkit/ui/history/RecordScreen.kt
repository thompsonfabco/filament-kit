package com.thompsonfabco.filamentkit.ui.history

import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextDecoration
import kotlinx.coroutines.delay
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.HistoryRecord
import com.thompsonfabco.filamentkit.net.HistorySaved
import com.thompsonfabco.filamentkit.net.HistorySpool
import com.thompsonfabco.filamentkit.net.RevisionProposal
import com.thompsonfabco.filamentkit.net.HistoryRevision
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.components.HubNotice
import com.thompsonfabco.filamentkit.ui.components.HubNoticeKind
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NeedsHubReason
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
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
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass

/**
 * The record (05-android-app 10.2): its header with the Newer and Older steps, the photos, one Fields panel per saved
 * item, the Label Reader panel and the revisions. The top bar names the place (the shell's); the record's name is the
 * first line of the page.
 */
@Composable
internal fun RecordScreen(
    vm: RecordViewModel,
    list: HistoryListViewModel,
    client: Any?,
    onBack: () -> Unit,
    onOpenRecord: (String) -> Unit,
    onEdit: (Int) -> Unit,
    onOpenPhoto: (Int) -> Unit,
    onOpenSpool: (JsonObject) -> Unit,
    onPairAgain: () -> Unit,
) {
    val s by vm.state.collectAsState()
    val ls by list.state.collectAsState()
    // A record can open with no list loaded (restored after process death): load it for the Label Reader flag.
    LaunchedEffect(vm) {
        vm.ensureLoaded()
        list.ensureLoaded()
    }
    ReloadOnNewClient(client) {
        vm.load()
        list.refresh()
    }
    var note by rememberSaveable { mutableStateOf("") }
    val space = SpoolwardenTheme.space
    // out of reach: keep trying, the data on screen stays and what needs the Hub waits (05-android-app 3.2)
    LaunchedEffect(s.offline) {
        while (s.offline) {
            delay(RETRY_MS)
            vm.load()
        }
    }
    val r = s.record
    val failure = s.error
    val offline = failure == RecentFailure.Offline
    val ago = remember(s.loadedAt, s.error) { s.loadedAt?.let { (System.currentTimeMillis() - it) / MS_PER_S } ?: 0L }
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(space.s4),
        verticalArrangement = Arrangement.spacedBy(space.s3),
    ) {
        when {
            s.mismatch != null -> HubNotice(HubNoticeKind.CertificateChanged, onPairAgain)
            s.unauthorized -> HubNotice(HubNoticeKind.NoLongerPaired, onPairAgain)
        }
        ScreenState(
            loaded = r != null,
            loading = s.loading,
            error = if (failure != null && !offline) failureText(failure) else null,
            onTryAgain = vm::load,
            offline = offline,
            loadedSecondsAgo = ago,
        ) {
            if (r != null) {
                val records = ls.history?.records.orEmpty()
                val at = records.indexOfFirst { it.id == r.id }
                RecordHeader(
                    r,
                    newer = records.getOrNull(at - 1)?.takeIf { at > 0 }?.id,
                    older = records.getOrNull(at + 1)?.takeIf { at >= 0 }?.id,
                    onOpenRecord = onOpenRecord, onOpenSpool = { onOpenSpool(it.asSpoolJson()) },
                )
                PhotosPanel(r, list, onOpenPhoto)
                r.saved.forEach { item -> FieldsPanel(r, item, s.saved?.takeIf { it.item == item.item }, severalItems = r.saved.size > 1) { vm.beginEdit(item.item); onEdit(item.item) } }
                AskPanel(vm, s, ls.aiAvailable, note, onNote = { note = it; vm.noteTyped() })
                RevisionsPanel(vm, s, r)
            }
        }
    }
    if (s.undoAsk) UndoDialog(vm, s)
}

private const val MS_PER_S = 1000L

@Composable
private fun RecordHeader(r: HistoryRecord, newer: String?, older: String?, onOpenRecord: (String) -> Unit, onOpenSpool: (HistorySpool) -> Unit) {
    val space = SpoolwardenTheme.space
    val colors = SpoolwardenTheme.colors
    val ids = RecentValues.spoolIds(r.spools)
    val spools = if (ids.isEmpty()) {
        stringResource(R.string.recent_no_spools)
    } else {
        pluralStringResource(R.plurals.recent_spool_label, ids.size, RecentValues.idList(ids))
    }
    var menu by remember { mutableStateOf(false) }
    Row(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.Top) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(space.s1)) {
            Text(
                RecentValues.filaments(r.spools) ?: spools,
                Modifier.semantics { heading() }, style = MaterialTheme.typography.titleLarge,
            )
            Text(
                stringResource(R.string.recent_meta_line, RecentValues.time(r.at), sourceText(r.source, r.photos)),
                color = colors.muted, style = SpoolwardenTheme.type.dataSmall,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically) {
                IntakeStateLabel(r.state)
                Text(spools, color = colors.muted, style = SpoolwardenTheme.type.dataSmall)
            }
            val weighed = r.weight?.let {
                stringResource(
                    R.string.recent_weighed,
                    stringResource(R.string.recent_value_unit, RecentValues.text(JsonPrimitive(it)).orEmpty(), stringResource(R.string.unit_g)),
                )
            }
            val withTag = if (r.tag != null) stringResource(R.string.recent_tag_read) else null
            listOfNotNull(weighed, withTag).takeIf { it.isNotEmpty() }?.let {
                Text(it.joinToString(" · "), color = colors.muted, style = MaterialTheme.typography.bodySmall)
            }
        }
        StepButton(R.string.a11y_record_newer, flip = true, enabled = newer != null) { newer?.let(onOpenRecord) }
        StepButton(R.string.a11y_record_older, flip = false, enabled = older != null) { older?.let(onOpenRecord) }
        if (ids.isNotEmpty()) {
            Box {
                SwIconButton(R.drawable.sw_ic_more, stringResource(R.string.common_more_actions), { menu = true })
                SwMenu(menu, onDismiss = { menu = false }) {
                    r.spools.filter { it.spoolId != null }.distinctBy { it.spoolId }.forEach { spool ->
                        SwMenuItem(stringResource(R.string.recent_open_spool, spool.spoolId!!), { menu = false; onOpenSpool(spool) })
                    }
                }
            }
        }
    }
}

/** Newer or Older record: an icon button that is disabled at the end of the list. */
@Composable
private fun StepButton(@androidx.annotation.StringRes description: Int, flip: Boolean, enabled: Boolean, onClick: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    val name = stringResource(description)
    IconButton(onClick, enabled = enabled) {
        // the drawing points right; "newer" points left
        SwIcon(
            R.drawable.sw_ic_chevron, name, if (flip) Modifier.rotate(FLIP) else Modifier,
            tint = if (enabled) colors.text else colors.muted,
        )
    }
}

private const val FLIP = 180f

@Composable
private fun PhotosPanel(r: HistoryRecord, list: HistoryListViewModel, onOpenPhoto: (Int) -> Unit) {
    val space = SpoolwardenTheme.space
    val side = SpoolwardenTheme.sizes.thumb
    val shape = SpoolwardenTheme.shapes.rS
    RecentPanel(stringResource(R.string.recent_photos_title, r.photos)) {
        if (r.photos == 0) {
            Text(stringResource(R.string.recent_no_photo_hand), color = SpoolwardenTheme.colors.muted, style = MaterialTheme.typography.bodyMedium)
        } else {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                items((1..r.photos).toList()) { n ->
                    RecentPhoto(
                        list, r.id, n,
                        Modifier.size(side).clip(shape).clickable(role = Role.Button) { onOpenPhoto(n) },
                        description = stringResource(R.string.a11y_photo_record_open, n, r.photos),
                    )
                }
            }
        }
    }
}

@Composable
private fun FieldsPanel(r: HistoryRecord, item: HistorySaved, saved: SavedEdit?, severalItems: Boolean, onEdit: () -> Unit) {
    val ids = item.spoolIds
    val marks = remember(r, item) { RecentMarks.of(r, item) }
    val title = if (severalItems && ids.isNotEmpty()) {
        pluralStringResource(R.plurals.recent_spool_label, ids.size, RecentValues.idList(ids))
    } else {
        stringResource(R.string.recent_fields_title)
    }
    RecentPanel(
        title,
        actions = { IconTextButton(R.drawable.sw_ic_pencil, stringResource(R.string.recent_edit_title), onEdit) },
    ) {
        if (ids.size > 1) {
            val filament = r.spools.firstOrNull { it.spoolId in ids }?.filamentId
            Text(
                if (ids.size == 2 || filament == null) {
                    stringResource(R.string.recent_item_note)
                } else {
                    stringResource(R.string.recent_item_line, RecentValues.idList(ids), filament)
                },
                color = SpoolwardenTheme.colors.muted, style = MaterialTheme.typography.bodyMedium,
            )
        }
        ReadDetails.of(r, item.item)?.let {
            Text(readDetailsText(it), color = SpoolwardenTheme.colors.muted, style = MaterialTheme.typography.bodySmall)
        }
        RecentGroup.entries.forEach { group ->
            Text(stringResource(group.title), color = SpoolwardenTheme.colors.muted, style = SpoolwardenTheme.type.tableHeader)
            Column {
                RecentField.entries.filter { it.group == group }.forEachIndexed { i, field ->
                    if (i > 0) HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = SpoolwardenTheme.colors.border)
                    FieldRow(field, item.values[field.wire], marks[field])
                }
            }
        }
        if (saved != null) {
            val names = saved.fields.map { stringResource(it.label) }.joinToString(", ")
            NoticeCard(
                NoticeKind.Ok,
                pluralStringResource(R.plurals.recent_edit_saved, saved.fields.size, saved.fields.size, names),
            )
        }
    }
}

/** One field: its label, its value (data in mono; the colour with its swatch), and its mark. */
@Composable
private fun FieldRow(field: RecentField, value: kotlinx.serialization.json.JsonElement?, mark: FieldMark?) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val shown = fieldValue(field, value)
    val label = stringResource(field.label)
    val body: @Composable () -> Unit = {
        Column(verticalArrangement = Arrangement.spacedBy(space.s1)) {
            Row(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically) {
                if (field.kind == FieldKind.Colour && shown != null) ColorSwatch(shown)
                when {
                    shown == null -> Text(stringResource(R.string.recent_value_empty), color = colors.muted, style = MaterialTheme.typography.bodyMedium)
                    field.kind == FieldKind.Text -> Text(shown, style = MaterialTheme.typography.bodyMedium)
                    else -> Text(shown, style = SpoolwardenTheme.type.data)
                }
            }
            mark?.let { RecentStatusLine(it.shape, stringResource(it.word), if (it.warn) colors.warn else colors.muted, large = it.warn) }
        }
    }
    val rowModifier = Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).padding(vertical = space.s2).semantics(mergeDescendants = true) { }
    if (SpoolwardenTheme.window == WindowClass.Phone) {
        Column(rowModifier, verticalArrangement = Arrangement.spacedBy(space.s1)) {
            Text(label, color = colors.muted, style = MaterialTheme.typography.bodySmall)
            body()
        }
    } else {
        Row(rowModifier, horizontalArrangement = Arrangement.spacedBy(space.s3)) {
            Text(label, Modifier.width(SpoolwardenTheme.sizes.labelCol), color = colors.muted, style = MaterialTheme.typography.bodyMedium)
            body()
        }
    }
}

/** An outlined button with its icon before the words (the pencil of "Edit by hand", the arrow of "Undo revision"). */
@Composable
private fun IconTextButton(@DrawableRes icon: Int, text: String, onClick: () -> Unit, enabled: Boolean = true) {
    val colors = SpoolwardenTheme.colors
    OutlinedButton(
        onClick, Modifier.heightIn(min = SpoolwardenTheme.density.control), enabled = enabled, shape = SpoolwardenTheme.shapes.r,
        colors = ButtonDefaults.outlinedButtonColors(
            containerColor = colors.surface, contentColor = colors.text, disabledContainerColor = colors.surface2, disabledContentColor = colors.muted,
        ),
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, if (enabled) colors.borderStrong else colors.border),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = SpoolwardenTheme.space.s3),
    ) {
        SwIcon(icon, null)
        androidx.compose.foundation.layout.Spacer(Modifier.width(SpoolwardenTheme.space.s2))
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
}

// ---- Ask the Label Reader (10.4) ----

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AskPanel(vm: RecordViewModel, s: RecordState, ai: Boolean?, note: String, onNote: (String) -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val off = ai == false
    val waiting = s.ask == Ask.Waiting
    val needsHub = s.offline
    RecentPanel(stringResource(R.string.recent_ask_title)) {
        if (off) ReaderOffLine()
        OutlinedTextField(
            note, onNote, Modifier.fillMaxWidth(),
            enabled = !off && !waiting,
            label = { Text(stringResource(R.string.recent_ask_label)) },
            placeholder = { Text(stringResource(R.string.recent_ask_placeholder)) },
            isError = s.noteMissing,
            maxLines = ASK_LINES,
            shape = SpoolwardenTheme.shapes.r,
            supportingText = {
                when {
                    s.noteMissing -> RecentStatusLine(R.drawable.sw_st_octagon, stringResource(R.string.recent_ask_error_empty), colors.bad, large = true)
                    !off -> Text(stringResource(R.string.recent_ask_hint))
                }
            },
        )
        SwButton(stringResource(R.string.recent_ask_button), { vm.ask(note) }, enabled = !off && !waiting && !needsHub)
        if (needsHub) NeedsHubReason()
        when (val ask = s.ask) {
            Ask.Idle -> Unit
            Ask.Waiting -> Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
                SwProgress(null)
                Text(
                    stringResource(R.string.recent_ask_waiting), color = colors.muted, style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                )
            }
            is Ask.Proposal -> ProposalBox(vm, s, ask.proposal, needsHub)
            Ask.NoChange -> Text(stringResource(R.string.recent_ask_no_change), style = MaterialTheme.typography.bodyMedium)
            is Ask.Accepted -> NoticeCard(
                NoticeKind.Ok,
                pluralStringResource(R.plurals.recent_ask_accepted, ask.count, ask.count, ask.revision),
            )
            Ask.Discarded -> RecentStatusLine(R.drawable.sw_st_hollow, stringResource(R.string.recent_ask_discarded), colors.muted)
            is Ask.Failed -> {
                // a failed accept keeps its proposal on screen; "Try again" accepts it again
                ask.proposal?.let { ProposalBox(vm, s, it, needsHub, decided = true) }
                NoticeCard(
                    NoticeKind.Bad, failureText(ask.failure),
                    actions = listOf(SwAction(stringResource(R.string.common_try_again), vm::retry)),
                )
            }
        }
    }
}

private const val ASK_LINES = 3

/** The before-and-after list (02-components 7.9): `accentSoft` ground, a 1 dp `accentText` outline. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ProposalBox(vm: RecordViewModel, s: RecordState, p: RevisionProposal, needsHub: Boolean, decided: Boolean = false) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    Column(
        Modifier.fillMaxWidth().background(colors.accentSoft, SpoolwardenTheme.shapes.r)
            .border(BorderStroke(SpoolwardenTheme.sizes.hairline, colors.accentText), SpoolwardenTheme.shapes.r).padding(space.s3),
        verticalArrangement = Arrangement.spacedBy(space.s2),
    ) {
        Text(
            pluralStringResource(R.plurals.recent_ask_proposal, p.changes.size, p.changes.size),
            Modifier.semantics { heading() }, style = MaterialTheme.typography.titleSmall,
        )
        rereadText(p.reader, p.confidence)?.let { Text(it, color = colors.muted, style = MaterialTheme.typography.bodySmall) }
        p.note?.takeIf { it.isNotBlank() }?.let { Text(it, color = colors.muted, style = MaterialTheme.typography.bodySmall) }
        if (p.noPhoto) Text(stringResource(R.string.recent_ask_no_photo), style = MaterialTheme.typography.bodyMedium)
        p.changes.forEach { wire ->
            val field = RecentField.of(wire)
            val name = fieldName(wire)
            val empty = stringResource(R.string.recent_value_empty)
            val old = fieldValue(field, p.before[wire]) ?: empty
            val new = fieldValue(field, p.after[wire]) ?: empty
            val said = stringResource(R.string.a11y_proposal_change, name, old, new)
            Column(Modifier.clearAndSetSemantics { contentDescription = said }) {
                Text(name, color = colors.muted, style = MaterialTheme.typography.bodySmall)
                Row(horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                    Text(old, color = colors.muted, textDecoration = TextDecoration.LineThrough, style = SpoolwardenTheme.type.data)
                    Text(stringResource(R.string.recent_arrow), color = colors.muted, style = MaterialTheme.typography.bodyMedium)
                    Text(new, style = SpoolwardenTheme.type.data, fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold)
                }
            }
        }
        if (!decided) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                SwButton(stringResource(R.string.recent_ask_accept), vm::accept, kind = SwButtonKind.Main, busy = s.applyBusy, enabled = !needsHub)
                SwButton(stringResource(R.string.common_discard), vm::discard, enabled = !s.applyBusy)
            }
        }
    }
}

// ---- Revisions ----

@Composable
private fun RevisionsPanel(vm: RecordViewModel, s: RecordState, r: HistoryRecord) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    RecentPanel(stringResource(R.string.recent_revisions_title, r.revisions.size)) {
        if (r.revisions.isEmpty()) {
            Text(stringResource(R.string.recent_revisions_none), color = colors.muted, style = MaterialTheme.typography.bodyMedium)
        }
        r.revisions.asReversed().forEach { rev -> RevisionLine(rev) }
        s.undoTarget?.let { t ->
            IconTextButton(R.drawable.sw_ic_undo, stringResource(R.string.recent_undo, t.n), vm::askUndo, enabled = !s.undoBusy && !s.offline)
            if (s.offline && !s.undoBusy) NeedsHubReason()
        }
        s.undone?.let { UndoneLines(it) }
        s.undoFailure?.let {
            NoticeCard(NoticeKind.Bad, failureText(it), actions = listOf(SwAction(stringResource(R.string.common_try_again), vm::askUndo)))
        }
    }
}

/** "Revision 1, 2026-11-12 14:09, by hand: Empty spool weight 150 → 140 g", struck through when undone. */
@Composable
private fun RevisionLine(rev: HistoryRevision) {
    val colors = SpoolwardenTheme.colors
    val changes = rev.changes.map { changeText(it.field, it.old, it.new) }.joinToString("; ")
    val time = RecentValues.time(rev.at)
    val line = stringResource(if (rev.by == READER) R.string.recent_revision_reader else R.string.recent_revision_by_hand, rev.n, time, changes)
    Column(verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s1)) {
        Row(horizontalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2)) {
            Text(
                line, Modifier.weight(1f, fill = false), style = SpoolwardenTheme.type.dataSmall,
                color = if (rev.undone) colors.muted else colors.text,
                textDecoration = if (rev.undone) TextDecoration.LineThrough else null,
            )
            if (rev.undone) Text(stringResource(R.string.recent_revision_undone), color = colors.muted, style = MaterialTheme.typography.bodySmall)
        }
        val extra = listOfNotNull(
            rev.note?.takeIf { it.isNotBlank() }?.let { stringResource(R.string.recent_revision_note, it) },
            rev.device?.takeIf { it.isNotBlank() }?.let { stringResource(R.string.recent_revision_device, it) },
        )
        if (extra.isNotEmpty()) Text(extra.joinToString(" · "), color = colors.muted, style = MaterialTheme.typography.bodySmall)
        // what the revision did to the filaments: a re-link, and a filament left without spools (kept, not deleted)
        val f = rev.filaments
        if (f != null && !rev.undone) {
            val to = f.to
            if (to != null && to != f.from) {
                Text(
                    stringResource(if (f.created) R.string.recent_undo_filament_new else R.string.recent_relink_other, to),
                    color = colors.muted, style = MaterialTheme.typography.bodySmall,
                )
            }
            f.orphaned.forEach {
                Text(stringResource(R.string.recent_undo_filament_empty, it), color = colors.muted, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

private const val READER = "ai"

/** "Revision 1 undone. Empty spool weight is 150 g again." and what became of the filaments. */
@Composable
private fun UndoneLines(rev: HistoryRevision) {
    val space = SpoolwardenTheme.space
    val empty = stringResource(R.string.recent_value_empty)
    val first = rev.changes.firstOrNull()
    Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
        if (first == null) {
            NoticeCard(NoticeKind.Ok, stringResource(R.string.recent_result_undone, rev.n))
        } else {
            val line = stringResource(R.string.recent_undo_done, rev.n, fieldName(first.field), fieldValue(RecentField.of(first.field), first.old) ?: empty)
            val more = rev.changes.drop(1).map {
                stringResource(R.string.recent_undo_again, fieldName(it.field), fieldValue(RecentField.of(it.field), it.old) ?: empty)
            }
            NoticeCard(NoticeKind.Ok, line)
            more.forEach { NoticeCard(NoticeKind.Ok, it) }
        }
        // what the undo itself did (undo_to, orphaned_by_undo), not what the revision did before
        val f = rev.filaments
        if (f != null) {
            f.undoTo?.let { NoticeCard(NoticeKind.Info, stringResource(R.string.recent_undo_filament_new, it)) }
            f.orphanedByUndo.forEach { NoticeCard(NoticeKind.Info, stringResource(R.string.recent_undo_filament_empty, it)) }
        }
    }
}

@Composable
private fun UndoDialog(vm: RecordViewModel, s: RecordState) {
    val t = s.undoTarget ?: return
    val empty = stringResource(R.string.recent_value_empty)
    SwDialog(
        title = stringResource(R.string.recent_undo_title, t.n),
        onClose = vm::cancelUndo,
        confirm = SwDialogButton(stringResource(R.string.common_undo), vm::undo, busy = s.undoBusy),
        cancel = SwAction(stringResource(R.string.common_cancel), vm::cancelUndo),
    ) {
        t.changes.forEach {
            Text(
                stringResource(R.string.recent_undo_body, fieldName(it.field), fieldValue(RecentField.of(it.field), it.old) ?: empty),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}
