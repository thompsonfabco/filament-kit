package com.thompsonfabco.filamentkit.ui.spool

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwEmptyState
import com.thompsonfabco.filamentkit.ui.components.ScreenState
import com.thompsonfabco.filamentkit.ui.parseWeight
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** The one column the tag screens share: scrolls, centred, at most `columnMax` wide. */
@Composable
private fun TagPage(modifier: Modifier, content: @Composable () -> Unit) {
    val space = SpoolwardenTheme.space
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(space.s4), horizontalAlignment = Alignment.CenterHorizontally) {
        Column(Modifier.widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(space.s4)) {
            content()
        }
    }
}

@Composable
private fun PageHeader(text: String) {
    Text(text, Modifier.semantics { heading() }, style = MaterialTheme.typography.titleLarge)
}

/**
 * The tag screen (05 7.7). A tag linked to a spool replaces this screen with the spool screen ([onLinked]); one linked to
 * none offers [onLink] and [onAddNew]; a failed lookup says why with Try again.
 */
@Composable
fun TagScreen(
    vm: TagViewModel,
    uid: String,
    onLinked: (SpoolSummary) -> Unit,
    onLink: () -> Unit,
    onAddNew: () -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
    online: Boolean = true,
) {
    val ui by vm.state.collectAsStateWithLifecycle()
    val linked by rememberUpdatedState(onLinked)
    (ui as? TagUi.Linked)?.let { l -> LaunchedEffect(l) { linked(l.spool) } }
    TagPage(modifier) {
        if (ui !is TagUi.NotLinked) PageHeader(stringResource(R.string.common_tag, uid))
        if (ui is TagUi.Looking || ui is TagUi.Linked) {
            Text(stringResource(R.string.tag_looking), style = MaterialTheme.typography.bodyMedium)
        }
        val failure = (ui as? TagUi.Failed)?.failure
        HubNoticeOf(failure, onPairAgain)
        // the states every Hub screen has (05 3.2)
        ScreenState(
            loaded = ui is TagUi.NotLinked,
            loading = ui is TagUi.Looking || ui is TagUi.Linked,
            error = failure?.let { hubFailureText(it) },
            onTryAgain = vm::lookUp,
            offline = !online,
        ) {
            SwEmptyState(
                icon = R.drawable.sw_ic_tag,
                title = stringResource(R.string.tag_unlinked_title),
                text = stringResource(R.string.tag_unlinked_text),
                primary = SwAction(stringResource(R.string.tag_link_sealed), onLink),
                secondary = SwAction(stringResource(R.string.tag_add_new), onAddNew),
            )
        }
    }
}

/**
 * Link a tag to a sealed spool, find step (05 7.8): search sealed spools and, optionally, type the weight with the
 * spool. A row opens the preview with the typed weight ([onPick] gets the spool and the weight text).
 */
@Composable
fun LinkFindScreen(
    vm: LinkFindViewModel,
    uid: String,
    onPick: (SpoolSummary, String?) -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
    online: Boolean = true,
) {
    val ui by vm.state.collectAsStateWithLifecycle()
    val colors = SpoolwardenTheme.colors
    TagPage(modifier) {
        PageHeader(stringResource(R.string.tag_find_title, uid))
        OutlinedTextField(
            value = ui.query,
            onValueChange = vm::setQuery,
            label = { Text(stringResource(R.string.tag_find_search)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = androidx.compose.foundation.text.KeyboardActions(onSearch = { vm.search() }),
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = ui.weight,
            onValueChange = vm::setWeight,
            label = { Text(stringResource(R.string.common_weight_with_spool_optional)) },
            isError = ui.weightInvalid,
            supportingText = if (ui.weightInvalid) {
                { Text(stringResource(R.string.tag_find_weight_error)) }
            } else {
                null
            },
            singleLine = true,
            textStyle = SpoolwardenTheme.type.data,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            modifier = Modifier.fillMaxWidth(),
        )
        HubNoticeOf(ui.failure, onPairAgain)
        ScreenState(
            loaded = ui.searched,
            loading = ui.busy,
            isEmpty = ui.searched && ui.results.isEmpty(),
            empty = { Text(stringResource(R.string.tag_find_none), style = MaterialTheme.typography.bodyLarge) },
            error = ui.failure?.let { hubFailureText(it) },
            onTryAgain = { if (ui.query.isNotBlank()) vm.search() },
            offline = !online,
        ) {
            // the rows are off while the weight is wrong; the reason is above them
            if (ui.weightInvalid) Text(stringResource(R.string.tag_find_weight_error), style = MaterialTheme.typography.bodySmall, color = colors.muted)
            SpoolPanel {
                ui.results.forEachIndexed { i, spool ->
                    if (i > 0) HorizontalDivider(color = colors.border, thickness = SpoolwardenTheme.sizes.hairline)
                    SpoolRow(spool, enabled = !ui.weightInvalid, onClick = { onPick(spool, ui.weight.trim().ifEmpty { null }) })
                }
            }
        }
    }
}

/**
 * The link preview (05 7.8): the tag and the spool, "Link tag"; or, when the tag is in use, who has it and the button
 * that moves it. [onBack] returns to the find step; [onDone] runs once the link is written (the spool screen shows it).
 */
@Composable
fun LinkPreviewScreen(
    vm: LinkPreviewViewModel,
    uid: String,
    onBack: () -> Unit,
    onDone: (SpoolResult) -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
    online: Boolean = true,
) {
    val ui by vm.state.collectAsStateWithLifecycle()
    val done by rememberUpdatedState(onDone)
    LaunchedEffect(ui.finished) { ui.finished?.let { done(it) } }
    // the write is waited for: Back would drop its answer
    BackHandler(enabled = ui.linking) {}
    val space = SpoolwardenTheme.space
    TagPage(modifier) {
        val conflict = ui.conflict
        if (conflict != null) {
            // 05 7.8 "Tag already in use": the spool that has the tag, then the button that moves it
            if (ui.other != null) {
                NoticeCard(NoticeKind.Warn, stringResource(R.string.tag_in_use))
                SpoolRow(ui.other!!)
            }
            // the chosen spool has a tag of its own: moving the tag here replaces it
            val replaces = conflict == ConflictReason.SpoolHasOtherTag || ui.spool?.tag != null
            Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
                SwButton(
                    stringResource(
                        if (ui.linking) R.string.tag_link_linking else if (replaces) R.string.tag_move_replace else R.string.tag_move_here,
                    ),
                    vm::moveHere, Modifier.fillMaxWidth(), kind = SwButtonKind.Main, busy = ui.linking,
                )
                SwButton(stringResource(R.string.common_cancel), onBack, Modifier.fillMaxWidth(), kind = SwButtonKind.Quiet, enabled = !ui.linking)
            }
            return@TagPage
        }
        PageHeader(stringResource(R.string.tag_link_title))
        HubNoticeOf(ui.failure, onPairAgain)
        // the states every Hub screen has (05 3.2)
        ScreenState(
            loaded = !ui.checking,
            loading = ui.checking,
            error = ui.failure?.let { hubFailureText(it) },
            onTryAgain = vm::retry,
            offline = !online,
        ) {
            ui.spool?.let { SpoolRow(it) }
            Text(stringResource(R.string.tag_link_line, uid), style = MaterialTheme.typography.bodyMedium)
            vm.gross?.let {
                Text(monoNumbers(stringResource(R.string.tag_link_weight, formatGrams(it))), style = MaterialTheme.typography.bodyMedium)
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                SwButton(stringResource(R.string.common_back), onBack, enabled = !ui.linking)
                SwButton(
                    stringResource(if (ui.linking) R.string.tag_link_linking else R.string.tag_link_button), vm::link,
                    kind = SwButtonKind.Main, enabled = !ui.checking && ui.failure == null, busy = ui.linking,
                )
            }
        }
    }
}
