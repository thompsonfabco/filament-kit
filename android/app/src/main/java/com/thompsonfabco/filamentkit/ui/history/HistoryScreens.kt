package com.thompsonfabco.filamentkit.ui.history

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.viewmodel.compose.viewModel
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.HistorySummary
import com.thompsonfabco.filamentkit.ui.components.HubNotice
import com.thompsonfabco.filamentkit.ui.components.HubNoticeKind
import com.thompsonfabco.filamentkit.ui.components.ScreenState
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwEmptyState
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.delay
import kotlinx.serialization.json.JsonObject

/** Recently added (05-android-app 10.1): the list of intake records. */
@Composable
fun HistoryListEntry(current: () -> Api, client: Any?, onOpen: (String) -> Unit, onPairAgain: () -> Unit) {
    val list = viewModel { HistoryListViewModel(HistoryBackend.of(current)) }
    HistoryListScreen(list, client, onOpen = onOpen, onPairAgain = onPairAgain)
}

/**
 * The record behind [id] (10.2). The list's view model belongs to [listOwner] (the list's own back stack entry), so the
 * record shares the list's data and photos and the list refreshes when the person comes back.
 */
@Composable
fun HistoryRecordEntry(
    current: () -> Api,
    client: Any?,
    online: Boolean,
    id: String,
    listOwner: ViewModelStoreOwner,
    onBack: () -> Unit,
    onOpenRecord: (String) -> Unit,
    onEdit: (Int) -> Unit,
    onOpenPhoto: (Int) -> Unit,
    onOpenSpool: (JsonObject) -> Unit,
    onPairAgain: () -> Unit,
) {
    val list = viewModel(viewModelStoreOwner = listOwner) { HistoryListViewModel(HistoryBackend.of(current)) }
    val vm = viewModel(key = recordKey(id)) { RecordViewModel(HistoryBackend.of(current), id) }
    RecordScreen(
        vm, list, client, online = online, onBack = { list.refresh(); onBack() }, onOpenRecord = onOpenRecord, onEdit = onEdit,
        onOpenPhoto = onOpenPhoto, onOpenSpool = onOpenSpool, onPairAgain = onPairAgain,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun HistoryListScreen(vm: HistoryListViewModel, client: Any?, onOpen: (String) -> Unit, onPairAgain: () -> Unit) {
    val s by vm.state.collectAsState()
    LifecycleStartEffect(vm) {
        vm.refresh()
        onStopOrDispose { }
    }
    ReloadOnNewClient(client, vm::clientSeen)
    val space = SpoolwardenTheme.space
    val h = s.history
    val failure = s.error
    // out of reach: keep trying, the data on screen stays (05-android-app 3.2)
    LaunchedEffect(s.offline) {
        while (s.offline) {
            delay(RETRY_MS)
            vm.refresh()
        }
    }
    PullToRefreshBox(isRefreshing = s.loading && h != null, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().padding(space.s4), verticalArrangement = Arrangement.spacedBy(space.s3)) {
            when {
                s.mismatch != null -> HubNotice(HubNoticeKind.CertificateChanged, onPairAgain)
                s.unauthorized -> HubNotice(HubNoticeKind.NoLongerPaired, onPairAgain)
            }
            val offline = failure == RecentFailure.Offline
            val ago = remember(s.loadedAt, s.error) { s.loadedAt?.let { (System.currentTimeMillis() - it) / MS_PER_S } ?: 0L }
            ScreenState(
                loaded = h != null,
                loading = s.loading,
                modifier = Modifier.weight(1f),
                error = if (failure != null && !offline) failureText(failure) else null,
                onTryAgain = vm::refresh,
                offline = offline,
                loadedSecondsAgo = ago,
            ) {
                if (h != null) {
                    if (h.keep > 0) {
                        Text(
                            pluralStringResource(R.plurals.recent_facts, h.keep, h.keep, RecentValues.megabytes(h.photoBytes ?: 0L)),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                    if (!h.ai) ReaderOffLine()
                    if (h.records.isEmpty()) {
                        SwEmptyState(
                            icon = R.drawable.sw_ic_clock,
                            title = stringResource(R.string.recent_empty_title),
                            text = stringResource(if (h.keep == 0) R.string.recent_keep_none else R.string.recent_empty_text),
                        )
                    } else {
                        Box(
                            Modifier.weight(1f, fill = false).fillMaxWidth()
                                .border(BorderStroke(SpoolwardenTheme.sizes.hairline, SpoolwardenTheme.colors.border), SpoolwardenTheme.shapes.r)
                                .clip(SpoolwardenTheme.shapes.r).background(SpoolwardenTheme.colors.surface),
                        ) {
                            LazyColumn {
                                items(h.records, key = { it.id }) { r ->
                                    RecordRow(r, vm) { onOpen(r.id) }
                                    if (r !== h.records.last()) {
                                        HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = SpoolwardenTheme.colors.border)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

private const val MS_PER_S = 1000L
internal const val RETRY_MS = 10_000L

/** The hollow circle and "The Label Reader is switched off. ..." (10.1, 10.4). */
@Composable
internal fun ReaderOffLine(modifier: Modifier = Modifier) {
    RecentStatusLine(
        R.drawable.sw_st_hollow, stringResource(R.string.recent_reader_off), SpoolwardenTheme.colors.muted, modifier,
    )
}

/** One record (10.1): thumbnail with its photo count, the filaments, when and which spools, the state and the source. */
@Composable
private fun RecordRow(r: HistorySummary, vm: HistoryListViewModel, onClick: () -> Unit) {
    val space = SpoolwardenTheme.space
    val colors = SpoolwardenTheme.colors
    val ids = RecentValues.spoolIds(r.spools)
    val spools = if (ids.isEmpty()) {
        stringResource(R.string.recent_no_spools)
    } else {
        pluralStringResource(R.plurals.recent_spool_label, ids.size, RecentValues.idList(ids))
    }
    Row(
        Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).clickable(role = Role.Button, onClick = onClick)
            .padding(space.s3),
        horizontalArrangement = Arrangement.spacedBy(space.s3),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Thumb(vm, r)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(space.s1)) {
            Row(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    RecentValues.filaments(r.spools) ?: spools, Modifier.weight(1f, fill = false),
                    style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis,
                )
                if (ids.size > 1) {
                    Text(stringResource(R.string.recent_times, ids.size), color = colors.muted, style = SpoolwardenTheme.type.dataSmall)
                }
            }
            Text(
                stringResource(R.string.recent_row_meta, RecentValues.time(r.at), spools),
                color = colors.muted, style = SpoolwardenTheme.type.dataSmall,
            )
            IntakeStateLabel(r.state)
            Text(sourceText(r.source, r.photos), color = colors.muted, style = MaterialTheme.typography.bodySmall)
        }
        SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted)
    }
}

/** The first photo with the photo count in a small badge, or a dashed box standing for "No photo". */
@Composable
private fun Thumb(vm: HistoryListViewModel, r: HistorySummary) {
    val side = SpoolwardenTheme.sizes.thumbS
    val colors = SpoolwardenTheme.colors
    val shape = SpoolwardenTheme.shapes.rS
    if (r.photos == 0) {
        val none = stringResource(R.string.photo_none)
        Box(
            Modifier.size(side).dashedOutline(colors.borderStrong, shape, SpoolwardenTheme.space.s1, SpoolwardenTheme.sizes.hairline)
                .semantics { contentDescription = none },
        )
        return
    }
    Box(Modifier.size(side)) {
        RecentPhoto(vm, r.id, 1, Modifier.size(side).clip(shape), description = null)
        Text(
            r.photos.toString(),
            Modifier.align(Alignment.BottomEnd).background(colors.surface, shape).padding(horizontal = SpoolwardenTheme.space.s1),
            color = colors.text, style = SpoolwardenTheme.type.dataSmall,
        )
    }
}
