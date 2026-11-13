package com.thompsonfabco.filamentkit.ui.add

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.HubNotice
import com.thompsonfabco.filamentkit.ui.components.HubNoticeKind
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwProgress
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass

/** The four steps of the add flow (05-android-app 6.1); each is a page of its own under the top bar "Add spools". */
enum class AddStep(@StringRes val title: Int) {
    Photos(R.string.add_photos_title),
    Check(R.string.add_review_title),
    Preview(R.string.add_preview_title),
    Done(R.string.add_done_title),
}

/** The step the stage is on. */
internal fun stepOf(stage: Stage): AddStep = when (stage) {
    Stage.Capture, Stage.Reading -> AddStep.Photos
    Stage.Review -> AddStep.Check
    Stage.Previewing, Stage.Preview, Stage.Adding -> AddStep.Preview
    Stage.Done -> AddStep.Done
}

/** "Step 1 of 3" on the photo path (Photos, Check, Preview), "Step 1 of 2" on the hand path (Check, Preview). */
internal fun stepNumber(step: AddStep, manual: Boolean): Pair<Int, Int>? = when {
    step == AddStep.Done -> null
    manual -> (step.ordinal) to 2
    else -> (step.ordinal + 1) to 3
}

/**
 * One step of the flow (05-android-app 6.1): the page header with its step line, the draft's tags, the [content] in a
 * scrolling column, and the sticky [bar] above the navigation bar (`surface` with a top hairline). The content column
 * is at most `contentMax` wide and centred.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun AddPage(
    step: AddStep,
    state: AddUiState,
    modifier: Modifier = Modifier,
    bar: (@Composable ColumnScope.() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val space = SpoolwardenTheme.space
    val colors = SpoolwardenTheme.colors
    Column(modifier.fillMaxSize()) {
        Column(
            Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(space.s4),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Column(
                Modifier.widthIn(max = SpoolwardenTheme.sizes.contentMax).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(space.s3),
            ) {
                Column {
                    Text(stringResource(step.title), Modifier.semantics { heading() }, style = MaterialTheme.typography.titleLarge)
                    stepNumber(step, state.manual)?.let { (n, of) ->
                        Text(
                            stringResource(R.string.add_step, n, of),
                            style = MaterialTheme.typography.bodySmall, color = colors.muted,
                        )
                    }
                }
                if (step != AddStep.Done && (state.photos.isNotEmpty() || state.tag != null)) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalArrangement = Arrangement.spacedBy(space.s2)) {
                        if (state.photos.isNotEmpty()) {
                            DraftTag(pluralStringResource(R.plurals.home_draft_photos, state.photos.size, state.photos.size))
                        }
                        state.tag?.let { DraftTag(stringResource(R.string.common_tag, it), mono = true) }
                    }
                }
                content()
            }
        }
        if (bar != null) {
            Surface(Modifier.fillMaxWidth(), color = colors.surface) {
                Column(Modifier.fillMaxWidth()) {
                    HorizontalDivider(color = colors.border)
                    Column(
                        Modifier.fillMaxWidth().padding(horizontal = space.s4, vertical = space.s3),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Column(
                            Modifier.widthIn(max = SpoolwardenTheme.sizes.contentMax).fillMaxWidth(),
                            verticalArrangement = Arrangement.spacedBy(space.s2),
                            content = bar,
                        )
                    }
                }
            }
        }
    }
}

/** One of the draft's tags ("2 photos", "Tag 04A1B2"): information only. */
@Composable
private fun DraftTag(text: String, mono: Boolean = false) {
    val space = SpoolwardenTheme.space
    Text(
        text,
        Modifier.background(SpoolwardenTheme.colors.surface2, SpoolwardenTheme.shapes.rS)
            .padding(horizontal = space.s2, vertical = space.s1),
        style = if (mono) SpoolwardenTheme.type.dataSmall else MaterialTheme.typography.bodySmall,
    )
}

/** A form group of the design (02 5.11, "panel"): `surface` ground, 1 dp `border`, `r` corners, no elevation. */
@Composable
internal fun AddPanel(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val colors = SpoolwardenTheme.colors
    OutlinedCard(
        modifier.fillMaxWidth(),
        shape = SpoolwardenTheme.shapes.r,
        colors = CardDefaults.outlinedCardColors(containerColor = colors.surface, contentColor = colors.text),
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.border),
        content = content,
    )
}

/** The kinds of status the add flow shows (shape and word, never the shape alone, F10). */
internal enum class AddStatus(@DrawableRes val shape: Int, val large: Boolean) {
    Ok(R.drawable.sw_st_filled, false),
    Warn(R.drawable.sw_st_triangle, true),
    Bad(R.drawable.sw_st_octagon, true),
    Muted(R.drawable.sw_st_hollow, false),
}

/** A status: its shape (decoration) and the [text] in the status colour, at `--fs-s`. */
@Composable
internal fun AddStatusLine(status: AddStatus, text: String, modifier: Modifier = Modifier) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val colour = when (status) {
        AddStatus.Ok -> colors.ok
        AddStatus.Warn -> colors.warn
        AddStatus.Bad -> colors.bad
        AddStatus.Muted -> colors.muted
    }
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(space.s1), verticalAlignment = Alignment.CenterVertically) {
        Icon(
            painterResource(status.shape), contentDescription = null, tint = colour,
            modifier = Modifier.size(if (status.large) space.s2 + space.s1 / 2 else space.s2),
        )
        Text(text, style = MaterialTheme.typography.labelMedium, color = colour)
    }
}

/** A progress line with the words of what is under way; the words are a polite live region (14.4). */
@Composable
internal fun AddBusy(text: String, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2)) {
        SwProgress(null)
        Text(text, Modifier.semantics { liveRegion = LiveRegionMode.Polite }, style = MaterialTheme.typography.bodyMedium)
    }
}

/**
 * The current problem as a notice line with the actions that fit it (05-android-app 6.2). A changed certificate and a
 * lost pairing are the Hub notices of 3.4 (the fingerprints are shown on the certificate screen, not here). The notice
 * stays until the next action ("OK" is gone); [kept] adds that the photos and edits are kept.
 */
@Composable
internal fun AddErrorNotice(
    error: AddError,
    vm: AddViewModel,
    onPairAgain: () -> Unit,
    onAddByHand: () -> Unit,
    kept: Boolean,
    modifier: Modifier = Modifier,
) {
    val hub = when {
        error.expectedFingerprint != null && error.actualFingerprint != null -> HubNoticeKind.CertificateChanged
        error.pairAgain -> HubNoticeKind.NoLongerPaired
        else -> null
    }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s1)) {
        if (hub != null) {
            HubNotice(hub, onPairAgain)
        } else {
            val actions = buildList {
                if (error.canRetry) add(SwAction(stringResource(R.string.common_try_again), vm::retry))
                if (error.canDropTag) add(SwAction(stringResource(R.string.add_read_without_tag), vm::dropTagAndRetry))
                if (error.canAddByHand) add(SwAction(stringResource(R.string.home_add_by_hand), onAddByHand))
            }
            NoticeCard(NoticeKind.Bad, error.message.string(), actions = actions)
        }
        if (kept) Text(stringResource(R.string.add_read_kept), style = MaterialTheme.typography.bodySmall)
    }
}

/** The group title: `--fs-xs`, uppercase, `--muted`, 0.05em letter spacing (06-android 6.3); a heading for TalkBack. */
@Composable
internal fun GroupTitle(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(), modifier.semantics { heading() },
        style = SpoolwardenTheme.type.tableHeader, color = SpoolwardenTheme.colors.muted,
    )
}

/** Two fields side by side from medium width on, one under the other on a phone. */
@Composable
internal fun FieldPair(first: @Composable () -> Unit, second: (@Composable () -> Unit)?) {
    val space = SpoolwardenTheme.space
    if (second != null && SpoolwardenTheme.window != WindowClass.Phone) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(space.s3)) {
            Box(Modifier.weight(1f)) { first() }
            Box(Modifier.weight(1f)) { second() }
        }
    } else {
        first()
        second?.invoke()
    }
}
