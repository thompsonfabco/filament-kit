package com.thompsonfabco.filamentkit.ui.home

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.Text
import androidx.compose.material3.TooltipAnchorPosition
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.rememberTooltipState
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
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.drafts.Draft
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.net.ServerInfo
import com.thompsonfabco.filamentkit.session.Connection
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
import com.thompsonfabco.filamentkit.ui.components.SwEmptyState
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwIconButton
import com.thompsonfabco.filamentkit.ui.components.SwMenu
import com.thompsonfabco.filamentkit.ui.components.SwMenuItem
import com.thompsonfabco.filamentkit.ui.components.SwSkeletonRows
import com.thompsonfabco.filamentkit.ui.components.ageWords
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass
import com.thompsonfabco.filamentkit.update.UpdateTexts
import com.thompsonfabco.filamentkit.update.UpdateUi
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date

/**
 * Home (05-android-app 5): the notices that apply (local network, Hub, offline, app update), then Add spools, Drafts,
 * Printers and the Slicer presets panel. One column on a phone; on a tablet or wider the left column holds Add spools
 * and Drafts, the right one Printers and Slicer presets. The title, the Hub's name and the connection chip are the
 * shell's top bar. [extra] is for debug tools.
 */
@Composable
internal fun HomeScreen(
    connection: Connection,
    drafts: List<Draft>,
    update: UpdateUi,
    /** The Printers panel's data ([HomePrintersViewModel]); [showPrinters] false (the Feature is off) hides the panel. */
    printers: HomePrintersState,
    onAddSpools: () -> Unit,
    onAddByHand: () -> Unit,
    onResumeDraft: (id: String) -> Unit,
    /** Delete an unfinished add and its photos (asked to confirm first). */
    onDiscardDraft: (id: String) -> Unit,
    onOpenPrinter: (id: String) -> Unit,
    /** Selects the Printers destination. */
    onOpenPrinters: () -> Unit,
    onRefreshPrinters: () -> Unit,
    onReviewCertificate: () -> Unit,
    onPairAgain: () -> Unit,
    onInstallUpdate: () -> Unit,
    onConfirmInstall: () -> Unit,
    modifier: Modifier = Modifier,
    showPrinters: Boolean = true,
    /** The Slicer presets panel; null while the status is unknown. [showPresets] false hides it (not paired yet). */
    presets: ProfileStatus? = null,
    showPresets: Boolean = true,
    /** The panel's Build now: [onBuildPresets], while [buildingPresets]; [presetsNote] is the outcome. */
    onBuildPresets: () -> Unit = {},
    buildingPresets: Boolean = false,
    presetsNote: String? = null,
    presetsNoteIsError: Boolean = false,
    /** The panel's Updates dialog; null: not offered (no server). [onPresetsChanged]: reload the panel. */
    presetUpdates: PresetUpdatesViewModel? = null,
    onPresetsChanged: () -> Unit = {},
    /** Opens the Filament Catalog's new-line form from the presets panel (until S4.14 moves it). */
    onAddCatalogLine: () -> Unit = {},
    /**
     * The Hub said its Label Reader is off ([labelReaderOff]): the photo button goes and "Add by hand" is the main one.
     * Unknown (cold start, offline) is not off: photos are kept on the phone and read when the Hub is back.
     */
    labelReaderOff: Boolean = false,
    /** Shown while [connection] is [Connection.NeedsLocalNetwork] (explanation, Allow, Open app settings). */
    localNetworkPanel: @Composable () -> Unit = {},
    /** The time the ages count from; null: the clock, read again every half minute. */
    nowMillis: Long? = null,
    extra: @Composable () -> Unit = {},
) {
    val space = SpoolwardenTheme.space
    val now = nowMillis ?: tickingNow()
    val toast = LocalToast.current
    val scope = rememberCoroutineScope()
    val discarded = stringResource(R.string.home_draft_discarded)
    val discard: (String) -> Unit = { id ->
        onDiscardDraft(id)
        // the row has left the screen, so the result is a toast (05-android-app 3.2)
        scope.launch { toast?.show(discarded) }
    }
    val left: @Composable ColumnScope.() -> Unit = {
        // while the local network notice asks for access, its "Allow" is the one filled button on the screen
        AddSpoolsPanel(labelReaderOff, connection != Connection.NeedsLocalNetwork, onAddSpools, onAddByHand)
        if (drafts.isNotEmpty()) DraftsPanel(drafts, now, onResumeDraft, discard)
    }
    val right: @Composable ColumnScope.() -> Unit = {
        if (showPrinters) {
            PrintersPanel(printers, connection, onOpenPrinter, onOpenPrinters, onRefreshPrinters, onReviewCertificate, onPairAgain)
        }
        if (showPresets) {
            var updatesOpen by remember { mutableStateOf(false) }
            PresetsCard(
                presets, onBuild = onBuildPresets, building = buildingPresets, buildNote = presetsNote,
                buildFailed = presetsNoteIsError, onAddLine = onAddCatalogLine,
                onUpdates = presetUpdates?.takeIf { presets != null }?.let { vm -> { vm.load(); updatesOpen = true } },
            )
            if (updatesOpen && presetUpdates != null) {
                PresetUpdatesDialog(presetUpdates, onClose = { updatesOpen = false; onPresetsChanged() })
            }
        }
    }
    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(space.s4),
        verticalArrangement = Arrangement.spacedBy(space.s3),
    ) {
        if (connection == Connection.NeedsLocalNetwork) localNetworkPanel()
        when (connection) {
            is Connection.CertChanged -> HubNotice(HubNoticeKind.CertificateChanged, onReviewCertificate)
            Connection.Unpaired -> HubNotice(HubNoticeKind.NoLongerPaired, onPairAgain)
            else -> Unit
        }
        val loadedAt = printers.loadedAt
        if (connection == Connection.Offline && loadedAt != null) {
            NoticeCard(
                NoticeKind.Info,
                stringResource(R.string.common_offline_notice, ageWords(((now - loadedAt) / MS_PER_SECOND).coerceAtLeast(0))),
            )
        }
        UpdateNotice(update, onInstallUpdate, onConfirmInstall)
        if (SpoolwardenTheme.window == WindowClass.Phone) {
            left()
            right()
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(space.s3)) {
                val columnMax = SpoolwardenTheme.sizes.columnMax
                Column(Modifier.weight(1f).widthIn(max = columnMax), Arrangement.spacedBy(space.s3), content = left)
                Column(Modifier.weight(1f).widthIn(max = columnMax), Arrangement.spacedBy(space.s3), content = right)
            }
        }
        extra()
    }
}

private const val MS_PER_SECOND = 1000L
private const val TICK_MS = 30 * MS_PER_SECOND

/** The clock, read again every [TICK_MS], so the draft ages and the day they are counted from keep up. */
@Composable
private fun tickingNow(): Long {
    var now by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(TICK_MS)
            now = System.currentTimeMillis()
        }
    }
    return now
}

/** A panel (05-android-app 3.1): `surface` with a hairline `border`, a header row of at least 48 dp with the title and an optional count and action. */
@Composable
private fun HomePanel(
    title: String,
    modifier: Modifier = Modifier,
    count: Int? = null,
    action: (@Composable () -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    OutlinedCard(
        modifier.fillMaxWidth(),
        shape = SpoolwardenTheme.shapes.r,
        colors = CardDefaults.outlinedCardColors(containerColor = colors.surface, contentColor = colors.text),
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.border),
    ) {
        Column(Modifier.padding(horizontal = space.s4).padding(bottom = space.s4)) {
            Row(Modifier.fillMaxWidth().heightIn(min = space.s7), verticalAlignment = Alignment.CenterVertically) {
                Row(
                    Modifier.weight(1f),
                    horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        title, style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.weight(1f, fill = false).semantics { heading() },
                    )
                    if (count != null) {
                        Text(
                            count.toString(), style = MaterialTheme.typography.labelMedium, color = colors.muted,
                            modifier = Modifier.background(colors.surface2, SpoolwardenTheme.shapes.rS)
                                .padding(horizontal = space.s2, vertical = space.s1),
                        )
                    }
                }
                action?.invoke()
            }
            Column(verticalArrangement = Arrangement.spacedBy(space.s2), content = content)
        }
    }
}

@Composable
private fun AddSpoolsPanel(readerOff: Boolean, mainAllowed: Boolean, onAddSpools: () -> Unit, onAddByHand: () -> Unit) {
    fun kind(main: Boolean) = if (main && mainAllowed) SwButtonKind.Main else SwButtonKind.Plain
    HomePanel(stringResource(R.string.home_add_title)) {
        Text(stringResource(R.string.home_add_text), style = MaterialTheme.typography.bodyMedium)
        if (readerOff) {
            Text(
                stringResource(R.string.home_label_reader_off), style = MaterialTheme.typography.bodyMedium,
                color = SpoolwardenTheme.colors.muted,
            )
            SwButton(stringResource(R.string.home_add_by_hand), onAddByHand, Modifier.fillMaxWidth(), kind = kind(true))
        } else {
            SwButton(
                stringResource(R.string.home_add_from_photos), onAddSpools, Modifier.fillMaxWidth(), kind = kind(true),
                icon = R.drawable.sw_ic_camera,
            )
            SwButton(stringResource(R.string.home_add_by_hand), onAddByHand, Modifier.fillMaxWidth(), kind = kind(false))
        }
    }
}

/** The notice for an app update, or for a Hub newer than the app; the install steps stay on it until Settings has them. */
@Composable
private fun UpdateNotice(update: UpdateUi, onInstall: () -> Unit, onConfirm: () -> Unit) {
    val kind = updateNotice(update) ?: return
    val space = SpoolwardenTheme.space
    val refused = UpdateTexts.refused(update)
    val links = LocalUriHandler.current
    val installLabel = when {
        update.busy -> UpdateTexts.installLabel(update)
        refused -> stringResource(R.string.common_try_again)
        else -> stringResource(R.string.app_update_install)
    }
    val tapToInstall = stringResource(R.string.app_update_tap_install)
    val meaning = stringResource(R.string.app_update_signature_more)
    val actions = buildList {
        if (update.confirmPending) {
            add(SwAction(tapToInstall, onConfirm))
        } else if (update.available != null) {
            add(SwAction(installLabel) { if (!update.busy) onInstall() })
        }
        if (refused) {
            // no browser on the phone: the sentence above still says what to do
            add(SwAction(meaning) { runCatching { links.openUri(UpdateTexts.REFUSED_GUIDE_URL) } })
        }
    }
    Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
        when (kind) {
            UpdateNoticeKind.HubNewer -> NoticeCard(NoticeKind.Warn, stringResource(R.string.home_update_hub_newer), actions = actions)
            UpdateNoticeKind.Downloaded -> NoticeCard(NoticeKind.Info, stringResource(R.string.app_update_downloaded_home), actions = actions)
            UpdateNoticeKind.Ready -> {
                // the Hub always names its release; the offered build number is the fallback
                val version = update.offeredVersion?.trim()?.ifEmpty { null } ?: update.available.toString()
                NoticeCard(NoticeKind.Info, stringResource(R.string.home_update_ready, version), actions = actions)
            }
        }
        if (update.needsPermission) NoticeCard(NoticeKind.Warn, stringResource(R.string.app_update_permission))
        update.error?.let { NoticeCard(NoticeKind.Bad, it) }
    }
}

@Composable
private fun DraftsPanel(drafts: List<Draft>, now: Long, onResume: (String) -> Unit, onDiscard: (String) -> Unit) {
    // local midnight of the device's day: recomputed whenever the clock moves into a new day
    val startOfToday = startOfDay(now)
    HomePanel(stringResource(R.string.home_drafts_title), count = drafts.size) {
        drafts.forEachIndexed { i, d ->
            if (i > 0) HorizontalDivider(color = SpoolwardenTheme.colors.border, thickness = SpoolwardenTheme.sizes.hairline)
            DraftRow(d, now, startOfToday, onClick = { onResume(d.id) }, onDiscard = { onDiscard(d.id) })
        }
    }
}

@Composable
private fun draftAgeWords(created: Long, now: Long, startOfToday: Long): String = when (val age = draftAge(created, now, startOfToday)) {
    is DraftAge.Seconds -> stringResource(R.string.common_age_seconds, age.n)
    is DraftAge.Minutes -> stringResource(R.string.common_age_minutes, age.n)
    is DraftAge.Hours -> stringResource(R.string.common_age_hours, age.n)
    DraftAge.Yesterday -> stringResource(R.string.home_draft_yesterday)
    DraftAge.Older -> DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(created))
}

/** One unfinished add: opens where it stopped; "Discard" is in the row's overflow and a TalkBack action; long-press gives the exact time. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DraftRow(draft: Draft, now: Long, startOfToday: Long, onClick: () -> Unit, onDiscard: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    var menuOpen by remember { mutableStateOf(false) }
    var confirming by remember { mutableStateOf(false) }
    val opener = remember { FocusRequester() }
    val age = draftAgeWords(draft.created, now, startOfToday)
    val exact = remember(draft.created) {
        DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(draft.created))
    }
    val parts = draftParts(draft)
    val detail = listOfNotNull(
        if (parts.photos > 0) pluralStringResource(R.plurals.home_draft_photos, parts.photos, parts.photos) else null,
        parts.note?.let { stringResource(R.string.home_draft_note, it) },
        parts.tag?.let { stringResource(R.string.home_draft_tag, it) },
    ).joinToString(" · ")
    val discard = stringResource(R.string.common_discard)
    TooltipBox(
        positionProvider = TooltipDefaults.rememberTooltipPositionProvider(TooltipAnchorPosition.Below),
        tooltip = {
            PlainTooltip(containerColor = colors.text, contentColor = colors.surface, shape = SpoolwardenTheme.shapes.rS) {
                Text(exact, style = MaterialTheme.typography.bodySmall)
            }
        },
        state = rememberTooltipState(),
    ) {
        Row(
            Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row)
                .semantics(mergeDescendants = true) {
                    customActions = listOf(CustomAccessibilityAction(discard) { confirming = true; true })
                }
                .clickable(onClick = onClick),
            horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f).padding(vertical = space.s2)) {
                Text(age, style = MaterialTheme.typography.bodyLarge)
                if (detail.isNotEmpty()) Text(detail, style = MaterialTheme.typography.bodySmall, color = colors.muted)
            }
            Row {
                SwIconButton(
                    R.drawable.sw_ic_more, stringResource(R.string.a11y_more_for, age), { menuOpen = true },
                    Modifier.focusRequester(opener),
                )
                SwMenu(menuOpen, { menuOpen = false }) {
                    SwMenuItem(discard, { menuOpen = false; confirming = true })
                }
            }
            SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted)
        }
    }
    if (confirming) {
        SwDialog(
            title = stringResource(R.string.home_draft_discard_title),
            onClose = { confirming = false },
            confirm = SwDialogButton(discard, onClick = { confirming = false; onDiscard() }, kind = SwButtonKind.DestructiveFilled),
            cancel = SwAction(stringResource(R.string.common_keep)) { confirming = false },
            returnFocusTo = opener,
        ) {
            Text(stringResource(R.string.home_draft_discard_body))
        }
    }
}

@Composable
private fun PrintersPanel(
    state: HomePrintersState,
    connection: Connection,
    onOpenPrinter: (String) -> Unit,
    onOpenAll: () -> Unit,
    onRefresh: () -> Unit,
    onReviewCertificate: () -> Unit,
    onPairAgain: () -> Unit,
) {
    // the Hub lists the printers it has found too; the panel shows the configured ones
    val list = state.printers?.filter { it.configured }
    val offline = connection == Connection.Offline
    HomePanel(
        stringResource(R.string.home_printers_title),
        count = list?.size,
        action = { SwButton(stringResource(R.string.home_printers_all), onOpenAll, kind = SwButtonKind.Quiet) },
    ) {
        when {
            // nothing loaded: say why by state (05 3.3, 3.4, 3.2)
            list == null && connection is Connection.CertChanged -> HubNotice(HubNoticeKind.CertificateChanged, onReviewCertificate)
            list == null && connection == Connection.Unpaired -> HubNotice(HubNoticeKind.NoLongerPaired, onPairAgain)
            // the local network notice already stands in for the content
            list == null && connection == Connection.NeedsLocalNetwork -> Unit
            list == null && offline -> SwEmptyState(
                icon = R.drawable.sw_st_hollow, title = stringResource(R.string.common_offline_title),
                text = stringResource(R.string.common_offline_text), dashed = false,
                secondary = SwAction(stringResource(R.string.common_try_again), onRefresh),
            )
            list == null && state.failed -> NoticeCard(
                NoticeKind.Bad, state.message ?: stringResource(R.string.common_hub_no_answer),
                actions = listOf(SwAction(stringResource(R.string.common_try_again), onRefresh)),
            )
            list == null -> SwSkeletonRows(PRINTER_SKELETON_ROWS)
            else -> {
                // the data stays when a read fails; while the Hub is simply offline the top notice says so
                if (state.failed && !offline && connection !is Connection.CertChanged && connection != Connection.Unpaired) {
                    NoticeCard(
                        NoticeKind.Bad, state.message ?: stringResource(R.string.common_hub_unreachable),
                        actions = listOf(SwAction(stringResource(R.string.common_try_again), onRefresh)),
                    )
                }
                if (list.isEmpty()) {
                    Text(stringResource(R.string.home_printers_empty), style = MaterialTheme.typography.bodyMedium)
                    SwButton(stringResource(R.string.home_printers_add), onOpenAll, kind = SwButtonKind.Quiet)
                } else {
                    val rows = printerRows(list)
                    rows.shown.forEachIndexed { i, p ->
                        if (i > 0) HorizontalDivider(color = SpoolwardenTheme.colors.border, thickness = SpoolwardenTheme.sizes.hairline)
                        PrinterRow(p, onClick = { onOpenPrinter(p.id) })
                    }
                    if (rows.more > 0) {
                        Text(
                            stringResource(R.string.home_printers_more, rows.more), style = MaterialTheme.typography.bodySmall,
                            color = SpoolwardenTheme.colors.muted,
                        )
                    }
                }
            }
        }
    }
}

private const val PRINTER_SKELETON_ROWS = 2

/** One printer: its name, then its status shape and word or, while printing, the job line. */
@Composable
private fun PrinterRow(p: Printer, onClick: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val status = homePrinterStatus(p)
    val (shape, tint, word) = when (status) {
        HomePrinterStatus.Printing -> Triple(R.drawable.sw_st_filled, colors.ok, stringResource(R.string.printer_job_printing))
        HomePrinterStatus.Idle -> Triple(R.drawable.sw_st_filled, colors.ok, stringResource(R.string.printer_job_idle))
        HomePrinterStatus.Offline -> Triple(R.drawable.sw_st_hollow, colors.bad, stringResource(R.string.status_offline))
        HomePrinterStatus.NeedsLook -> Triple(R.drawable.sw_st_triangle, colors.warn, stringResource(R.string.status_needs_look))
        HomePrinterStatus.NotConfigured -> Triple(R.drawable.sw_st_hollow, colors.muted, stringResource(R.string.status_not_configured))
    }
    val job = printerJob(p)
    val line = when {
        job == null -> word
        job.hours == 0 && job.minutes == 0 -> stringResource(R.string.home_printer_job, word, job.percent.toString())
        else -> stringResource(
            R.string.printers_job_line, word, job.percent.toString(),
            if (job.hours > 0) stringResource(R.string.home_printer_left_hours, job.hours.toString(), job.minutes.toString())
            else stringResource(R.string.home_printer_left_minutes, job.minutes.toString()),
        )
    }
    Row(
        Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).clickable(onClick = onClick),
        horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f).padding(vertical = space.s2)) {
            Text(p.name, style = MaterialTheme.typography.bodyLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(space.s1), verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    painterResource(shape), contentDescription = null, tint = tint,
                    modifier = Modifier.size(if (status == HomePrinterStatus.NeedsLook) space.s2 + space.s1 / 2 else space.s2),
                )
                Text(line, style = MaterialTheme.typography.bodySmall, color = if (job == null) tint else colors.muted)
            }
        }
        SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted)
    }
}

/** The label-photo add flow is offered only when the server says its `ai_intake` module is on ([info] null: unknown). */
fun showLabelPhotos(info: ServerInfo?): Boolean = info?.labelReading == true

/** Home hides the photo button only when the Hub said so: unknown ([info] null) is not off. */
fun labelReaderOff(info: ServerInfo?): Boolean = info?.labelReading == false
