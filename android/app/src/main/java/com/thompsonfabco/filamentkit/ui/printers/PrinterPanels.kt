package com.thompsonfabco.filamentkit.ui.printers

import androidx.activity.compose.BackHandler
import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.HubNotice
import com.thompsonfabco.filamentkit.ui.components.HubNoticeKind
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.launch

/**
 * A panel of the printer screens (05-android-app 3.1): `surface` ground, 1 dp `border`, `r` corners, no shadow. The
 * header row is at least 48 dp: the [title] (a heading), and [action] at the right. The body has `s4` padding.
 */
@Composable
internal fun PrinterPanel(
    title: String?,
    modifier: Modifier = Modifier,
    action: (@Composable () -> Unit)? = null,
    padded: Boolean = true,
    content: @Composable ColumnScope.() -> Unit,
) {
    val space = SpoolwardenTheme.space
    val shape = SpoolwardenTheme.shapes.r
    Column(
        modifier.fillMaxWidth().clip(shape).background(SpoolwardenTheme.colors.surface, shape)
            .border(SpoolwardenTheme.sizes.hairline, SpoolwardenTheme.colors.border, shape),
    ) {
        if (title != null) {
            Row(
                Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).padding(start = space.s4, end = if (action == null) space.s4 else space.s2),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    title, Modifier.weight(1f).semantics { heading() },
                    style = MaterialTheme.typography.titleMedium,
                )
                action?.invoke()
            }
        }
        if (padded) {
            Column(
                Modifier.fillMaxWidth().padding(start = space.s4, end = space.s4, bottom = space.s4)
                    .then(if (title == null) Modifier.padding(top = space.s4) else Modifier),
                verticalArrangement = Arrangement.spacedBy(space.s2),
                content = content,
            )
        } else {
            content()
        }
    }
}

@Composable
internal fun PanelDivider() {
    HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = SpoolwardenTheme.colors.border)
}

/** A result line under the control that caused it: good news is `ok`, a refusal or failure `bad` (05-android-app 3.2). */
@Composable
internal fun ResultLine(note: Note, modifier: Modifier = Modifier) {
    NoticeCard(if (note.ok) NoticeKind.Ok else NoticeKind.Bad, sayText(note.say), modifier)
}

/** The Hub notices of 3.4 for a screen's view models: shown inline where the result would be, never in place of the screen. */
@Composable
internal fun HubNotices(unauthorized: Boolean, mismatch: Boolean, onPairAgain: () -> Unit) {
    if (mismatch) HubNotice(HubNoticeKind.CertificateChanged, onPairAgain)
    if (unauthorized) HubNotice(HubNoticeKind.NoLongerPaired, onPairAgain)
}

/** A shape and words in one colour: the status of the slot mapping (05-android-app 9.7). The shape is decoration. */
@Composable
internal fun ShapeWords(@DrawableRes shape: Int, colour: Color, large: Boolean, text: String, modifier: Modifier = Modifier) {
    val space = SpoolwardenTheme.space
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically) {
        Icon(
            painterResource(shape), contentDescription = null,
            modifier = Modifier.size(if (large) space.s2 + space.s1 / 2 else space.s2), tint = colour,
        )
        Text(text, color = colour, style = MaterialTheme.typography.labelLarge)
    }
}

/** The drawing and colour of a [MapShape]. */
@Composable
internal fun mapShapeLook(shape: MapShape): Triple<Int, Color, Boolean> {
    val colors = SpoolwardenTheme.colors
    return when (shape) {
        MapShape.Running -> Triple(R.drawable.sw_st_half, colors.info, false)
        MapShape.Filled -> Triple(R.drawable.sw_st_filled, colors.ok, false)
        MapShape.Triangle -> Triple(R.drawable.sw_st_triangle, colors.warn, true)
        MapShape.Octagon -> Triple(R.drawable.sw_st_octagon, colors.bad, true)
    }
}

/**
 * A write the person cannot safely abandon is in flight (05-android-app 2.5 rule 2): Back, the scrim and a swipe do
 * nothing, and the snackbar [words] says why. Returns what to run instead of leaving; compose [BusyBack] inside the
 * dialog so its Back button is caught.
 */
@Composable
internal fun rememberBusySay(@StringRes words: Int = R.string.common_working): () -> Unit {
    val toast = LocalToast.current
    val scope = rememberCoroutineScope()
    val text = stringResource(words)
    return { scope.launch { toast?.show(text) } }
}

/** Catches Back while [busy] and runs [say]; call it inside the dialog or sheet body. */
@Composable
internal fun BusyBack(busy: Boolean, say: () -> Unit) {
    BackHandler(enabled = busy, onBack = say)
}
