package com.thompsonfabco.filamentkit.ui.history

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.Api
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
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.delay

/**
 * Edit by hand (05-android-app 10.3) on saved item [item] of record [id]. The form lives in the record's view model
 * ([recordOwner] is the record's own back stack entry), so the record shows the result line when this screen closes.
 */
@Composable
fun HistoryEditEntry(
    current: () -> Api,
    client: Any?,
    online: Boolean,
    id: String,
    item: Int,
    recordOwner: ViewModelStoreOwner,
    onClose: () -> Unit,
    onPairAgain: () -> Unit,
) {
    val vm = viewModel(viewModelStoreOwner = recordOwner, key = recordKey(id)) { RecordViewModel(HistoryBackend.of(current), id) }
    EditScreen(vm, item, onClose, onPairAgain, client, online)
}

@Composable
internal fun EditScreen(
    vm: RecordViewModel,
    item: Int,
    onClose: () -> Unit,
    onPairAgain: () -> Unit,
    client: Any? = null,
    online: Boolean = false,
) {
    val s by vm.state.collectAsState()
    val space = SpoolwardenTheme.space
    LaunchedEffect(vm) { vm.ensureLoaded() }
    ReloadOnNewClient(client, vm::clientSeen)
    LaunchedEffect(online) { if (online) vm.hubBack() }
    // out of reach: keep trying; the typing stays and Save comes back with the connection (05-android-app 3.2)
    LaunchedEffect(s.offline) {
        while (s.offline) {
            delay(RETRY_MS)
            vm.load()
        }
    }
    LaunchedEffect(vm, item, s.record) { vm.startEdit(item) }
    val e = s.edit
    var leaving by rememberSaveable { mutableStateOf(false) }
    // Back asks when a field changed (2.5 rule 1) and is ignored while the save runs (rule 2)
    BackHandler(enabled = e != null) {
        if (e != null && !e.busy) {
            if (e.dirty) leaving = true else leave(vm, onClose)
        }
    }
    val failure = s.error
    Column(Modifier.fillMaxSize()) {
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(space.s4),
            verticalArrangement = Arrangement.spacedBy(space.s3),
        ) {
            Text(stringResource(R.string.recent_edit_title), Modifier.semantics { heading() }, style = MaterialTheme.typography.titleLarge)
            ScreenState(
                loaded = e != null,
                loading = s.loading,
                error = if (failure != null && failure != RecentFailure.Offline) failureText(failure) else null,
                onTryAgain = vm::load,
                offline = failure == RecentFailure.Offline,
            ) {
                if (e != null) EditFields(vm, s, e)
            }
            // the form cannot be opened (it was just saved, or the item is gone): say so, with a way back
            if (e == null && s.editUnavailable) Closed(onClose)
        }
        if (e != null) {
            ActionBar(
                vm, e, s, onCancel = { if (e.dirty) leaving = true else leave(vm, onClose) }, onClose = onClose,
                onPairAgain = onPairAgain,
            )
        }
    }
    if (leaving) {
        SwDialog(
            title = stringResource(R.string.common_leave_title),
            onClose = { leaving = false },
            confirm = SwDialogButton(
                stringResource(R.string.common_leave_without_saving), { leaving = false; leave(vm, onClose) },
                kind = SwButtonKind.DestructiveFilled,
            ),
            cancel = SwAction(stringResource(R.string.common_stay)) { leaving = false },
        ) {
            Text(
                stringResource(R.string.common_leave_body, stringResource(R.string.recent_leave_thing)),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@Composable
private fun Closed(onClose: () -> Unit) {
    val space = SpoolwardenTheme.space
    Column(verticalArrangement = Arrangement.spacedBy(space.s3)) {
        NoticeCard(NoticeKind.Info, stringResource(R.string.recent_edit_gone))
        SwButton(stringResource(R.string.common_back), onClose)
    }
}

private fun leave(vm: RecordViewModel, onClose: () -> Unit) {
    vm.closeEdit()
    onClose()
}

/** The four groups as text fields, prefilled with the saved values; a mark stays under a field until it is changed. */
@Composable
private fun EditFields(vm: RecordViewModel, s: RecordState, e: EditUi) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val record = s.record
    val marks = remember(record, e.item) {
        record?.saved?.firstOrNull { it.item == e.item }?.let { RecentMarks.of(record, it) }.orEmpty()
    }
    e.failure?.let { NoticeCard(NoticeKind.Bad, failureText(it)) }
    RecentGroup.entries.forEach { group ->
        Text(stringResource(group.title), color = colors.muted, style = SpoolwardenTheme.type.tableHeader)
        Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
            RecentField.entries.filter { it.group == group }.forEach { field ->
                val text = e.texts[field].orEmpty()
                val error = e.errors[field]
                val mark = marks[field]?.takeIf { text.trim() == e.original[field].orEmpty().trim() }
                OutlinedTextField(
                    text, { vm.setText(field, it) }, Modifier.fillMaxWidth(),
                    enabled = !e.busy,
                    label = { Text(stringResource(field.label)) },
                    suffix = field.unit?.let { { Text(stringResource(it)) } },
                    isError = error != null,
                    singleLine = true,
                    shape = SpoolwardenTheme.shapes.r,
                    textStyle = if (field.kind == FieldKind.Text) MaterialTheme.typography.bodyLarge else SpoolwardenTheme.type.input.copy(
                        fontFamily = SpoolwardenTheme.type.data.fontFamily, fontFeatureSettings = SpoolwardenTheme.type.data.fontFeatureSettings,
                    ),
                    keyboardOptions = KeyboardOptions(keyboardType = if (field.kind == FieldKind.Positive) KeyboardType.Decimal else KeyboardType.Text),
                    supportingText = when {
                        error != null -> ({
                            RecentStatusLine(R.drawable.sw_st_octagon, stringResource(errorText(error, field)), colors.bad, large = true)
                        })
                        mark != null -> ({
                            RecentStatusLine(mark.shape, stringResource(mark.word), if (mark.warn) colors.warn else colors.muted, large = mark.warn)
                        })
                        field.kind == FieldKind.Colour -> ({ Text(stringResource(R.string.common_field_colour_hint)) })
                        else -> null
                    },
                )
            }
        }
        HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = colors.border)
    }
}

/** What each complaint says: the rule, in the words of 05-android-app 6.3 where it has them. */
private fun errorText(error: FieldError, field: RecentField): Int = when (error) {
    FieldError.Required -> when (field) {
        RecentField.Vendor -> R.string.recent_error_brand
        RecentField.Material -> R.string.recent_error_material
        else -> R.string.common_error_name
    }
    FieldError.Whole -> R.string.add_review_error_whole
    FieldError.Degrees -> R.string.add_review_error_degrees
    FieldError.DegreesMax -> R.string.recent_error_degrees_max
    FieldError.Grams -> R.string.common_error_grams
    FieldError.Density -> R.string.add_review_error_density
    FieldError.Price -> R.string.recent_error_price
    FieldError.Range -> R.string.recent_error_range
    FieldError.Colour -> R.string.recent_error_colour
}

/** "Cancel" and "Save changes" (the screen's one filled button); "Nothing changed." beside them when nothing was. */
@Composable
private fun ActionBar(
    vm: RecordViewModel,
    e: EditUi,
    s: RecordState,
    onCancel: () -> Unit,
    onClose: () -> Unit,
    onPairAgain: () -> Unit,
) {
    val space = SpoolwardenTheme.space
    Column {
        HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = SpoolwardenTheme.colors.border)
        // where the result would appear: a 401 or a changed certificate keeps the typing and says so here
        Column(Modifier.padding(horizontal = space.s3).padding(top = space.s3)) {
            when {
                s.mismatch != null -> HubNotice(HubNoticeKind.CertificateChanged, onPairAgain)
                s.unauthorized -> HubNotice(HubNoticeKind.NoLongerPaired, onPairAgain)
            }
        }
        Row(
            Modifier.fillMaxWidth().padding(space.s3),
            horizontalArrangement = Arrangement.spacedBy(space.s2, Alignment.End),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (e.nothingChanged) {
                Text(
                    stringResource(R.string.recent_edit_nothing), Modifier.weight(1f),
                    color = SpoolwardenTheme.colors.muted, style = MaterialTheme.typography.bodyMedium,
                )
            }
            SwButton(stringResource(R.string.common_cancel), onCancel, kind = SwButtonKind.Quiet, enabled = !e.busy)
            SwButton(
                stringResource(if (e.busy) R.string.common_saving else R.string.recent_edit_save), { vm.saveEdit(onClose) },
                kind = SwButtonKind.Main, busy = e.busy, enabled = !s.offline,
            )
        }
        if (s.offline) NeedsHubReason(Modifier.padding(horizontal = space.s3).padding(bottom = space.s3))
    }
}
