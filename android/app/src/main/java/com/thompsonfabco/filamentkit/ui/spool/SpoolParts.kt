package com.thompsonfabco.filamentkit.ui.spool

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.withStyle
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.components.HubNotice
import com.thompsonfabco.filamentkit.ui.components.HubNoticeKind
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** The dot between the parts of a line. */
internal const val DOT = " · "

/** A panel (05-android-app 3.1): `surface` with a hairline `border`; [content] sits at `s4` from its edges. */
@Composable
internal fun SpoolPanel(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val colors = SpoolwardenTheme.colors
    OutlinedCard(
        modifier.fillMaxWidth(),
        shape = SpoolwardenTheme.shapes.r,
        colors = CardDefaults.outlinedCardColors(containerColor = colors.surface, contentColor = colors.text),
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.border),
    ) {
        Column(Modifier.padding(horizontal = SpoolwardenTheme.space.s4), content = content)
    }
}

private val NUMBER = Regex("[0-9][0-9.,]*")

/** [text] with its numbers in the mono face (05 7.1: "numbers `--mono`"). */
@Composable
internal fun monoNumbers(text: String): AnnotatedString {
    val mono = SpoolwardenTheme.type.data.fontFamily ?: FontFamily.Monospace
    return remember(text, mono) {
        buildAnnotatedString {
            var at = 0
            NUMBER.findAll(text).forEach { m ->
                append(text.substring(at, m.range.first))
                withStyle(SpanStyle(fontFamily = mono)) { append(m.value) }
                at = m.range.last + 1
            }
            append(text.substring(at))
        }
    }
}

/** "Spool 214 · PLA · Workshop X1 A1 · 620 g left", sealed and tagged added when true; a part the Hub did not send is left out. */
@Composable
internal fun spoolLine(s: SpoolSummary): String = listOfNotNull(
    stringResource(R.string.web_spool_title, s.id.toString()),
    s.material.ifBlank { null },
    s.location,
    s.remaining?.let { stringResource(R.string.spool_left, formatGrams(it)) },
    stringResource(R.string.spools_result_sealed).takeIf { s.state == SpoolState.Sealed },
    stringResource(R.string.spools_result_tagged).takeIf { s.tag != null },
).joinToString(DOT)

/** A spool as a row: the swatch, "Brand Name", and its line; with [onClick] it is a list row with a chevron. */
@Composable
internal fun SpoolRow(spool: SpoolSummary, modifier: Modifier = Modifier, onClick: (() -> Unit)? = null, enabled: Boolean = true) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val said = stringResource(
        R.string.a11y_spool_result, spool.title, spool.id.toString(), spool.material, spool.location.orEmpty(),
        spool.remaining?.let { formatGrams(it) }.orEmpty(),
    ).split(", ").filter { it.isNotBlank() && !it.startsWith(" ") }.joinToString(", ")
    val click = if (onClick != null) Modifier.clickable(enabled = enabled, onClick = onClick) else Modifier
    Row(
        modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).semantics(mergeDescendants = true) {
            contentDescription = said
        }.then(click),
        horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.CenterVertically,
    ) {
        ColorSwatch(spool.colorHex)
        Column(Modifier.weight(1f).padding(vertical = space.s2)) {
            Text(
                spool.title, style = MaterialTheme.typography.bodyLarge,
                color = if (enabled) colors.text else colors.muted,
            )
            Text(monoNumbers(spoolLine(spool)), style = MaterialTheme.typography.bodySmall, color = colors.muted)
        }
        if (onClick != null) SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted)
    }
}

/** A failed Hub call as its notice (05 3.4, 3.5); [onTryAgain] adds the button to the ones that are about reaching the Hub. */
@Composable
internal fun HubFailureNotice(
    failure: HubFailure,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
    onTryAgain: (() -> Unit)? = null,
) {
    val again = onTryAgain?.let { listOf(SwAction(stringResource(R.string.common_try_again), it)) }.orEmpty()
    when (failure) {
        HubFailure.CertificateChanged -> HubNotice(HubNoticeKind.CertificateChanged, onPairAgain, modifier)
        HubFailure.NotPaired -> HubNotice(HubNoticeKind.NoLongerPaired, onPairAgain, modifier)
        HubFailure.Unreachable -> NoticeCard(NoticeKind.Bad, stringResource(R.string.common_hub_unreachable), modifier, actions = again)
        HubFailure.Unexpected -> NoticeCard(NoticeKind.Bad, stringResource(R.string.common_hub_answer_unknown), modifier, actions = again)
        HubFailure.SpoolmanDown -> NoticeCard(NoticeKind.Bad, stringResource(R.string.common_spoolman_unreachable), modifier, actions = again)
        is HubFailure.Message -> NoticeCard(NoticeKind.Bad, failure.text, modifier, actions = again)
    }
}

/** The last change, as the notice line of 7.2: announced politely when it appears. */
@Composable
internal fun ResultLine(result: SpoolResult, modifier: Modifier = Modifier) {
    val text = when (result) {
        is SpoolResult.WeightUpdated ->
            stringResource(R.string.spool_result_weight, result.left?.let { formatGrams(it) } ?: stringResource(R.string.common_unknown))
        is SpoolResult.Moved -> stringResource(R.string.spool_result_moved, result.location)
        SpoolResult.MarkedEmpty -> stringResource(R.string.spool_result_empty)
        SpoolResult.TagLinked -> stringResource(R.string.spool_result_tag_linked)
        SpoolResult.TagMoved -> stringResource(R.string.spool_result_tag_moved)
        is SpoolResult.Loaded -> stringResource(R.string.spool_result_loaded, result.printer, result.slot)
        is SpoolResult.LoadedUnconfirmed -> stringResource(R.string.spool_load_unconfirmed)
    }
    NoticeCard(
        if (result is SpoolResult.LoadedUnconfirmed) NoticeKind.Warn else NoticeKind.Ok, text,
        modifier.semantics { liveRegion = LiveRegionMode.Polite },
    )
}
