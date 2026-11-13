package com.thompsonfabco.filamentkit.ui.components

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenColors
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** The four kinds of inline notice (02-components 8.8): each has its own shape, so colour is never the only sign. */
internal enum class NoticeKind(
    @DrawableRes val shape: Int,
    /** Triangle and octagon are drawn a little larger (08-platform-mapping 10.6). */
    val large: Boolean,
    private val strong: (SpoolwardenColors) -> Color,
    private val soft: (SpoolwardenColors) -> Color,
) {
    Ok(R.drawable.sw_st_filled, false, { it.ok }, { it.okSoft }),
    Warn(R.drawable.sw_st_triangle, true, { it.warn }, { it.warnSoft }),
    Bad(R.drawable.sw_st_octagon, true, { it.bad }, { it.badSoft }),
    Info(R.drawable.sw_ic_info, false, { it.info }, { it.infoSoft });

    fun colour(colors: SpoolwardenColors): Color = strong(colors)
    fun ground(colors: SpoolwardenColors): Color = soft(colors)
}

/**
 * A notice line (05-android-app 3.1, "Inline banner"): the kind's `-soft` ground without border, `r` corners, `s3`
 * padding, the shape in the kind's colour, the sentence in `text`, and quiet buttons for [actions]. A notice that
 * appears later is announced: assertively when it is a problem (`Bad`), politely otherwise.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun NoticeCard(
    kind: NoticeKind,
    text: String,
    modifier: Modifier = Modifier,
    title: String? = null,
    actions: List<SwAction> = emptyList(),
) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    Card(
        modifier.fillMaxWidth(),
        shape = SpoolwardenTheme.shapes.r,
        colors = CardDefaults.cardColors(containerColor = kind.ground(colors), contentColor = colors.text),
        elevation = CardDefaults.cardElevation(),
    ) {
        Row(Modifier.padding(space.s3), horizontalArrangement = Arrangement.spacedBy(space.s2)) {
            Icon(
                painterResource(kind.shape), contentDescription = null,
                modifier = Modifier.padding(top = space.s1).size(
                    when {
                        kind == NoticeKind.Info -> space.s3 + space.s1
                        kind.large -> space.s2 + space.s1
                        else -> space.s2
                    },
                ),
                tint = kind.colour(colors),
            )
            Column(Modifier.weight(1f)) {
                Column(
                    Modifier.semantics {
                        liveRegion = if (kind == NoticeKind.Bad) LiveRegionMode.Assertive else LiveRegionMode.Polite
                    },
                ) {
                    if (title != null) Text(title, style = MaterialTheme.typography.titleSmall)
                    Text(text, style = MaterialTheme.typography.bodyMedium)
                }
                if (actions.isNotEmpty()) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                        actions.forEach { SwButton(it.label, it.onClick, kind = SwButtonKind.Quiet) }
                    }
                }
            }
        }
    }
}

/** The two reasons a Hub request fails that are not about the request (05-android-app 3.4). */
internal enum class HubNoticeKind(@StringRes val text: Int, @StringRes val action: Int) {
    CertificateChanged(R.string.common_cert_changed_notice, R.string.common_review_certificate),
    NoLongerPaired(R.string.common_not_paired_notice, R.string.common_pair_again),
}

/**
 * The Hub notice: a `Bad` [NoticeCard] with fixed words and one button, used wherever a request fails for these two
 * reasons. It takes the place of that request's result and never replaces or clears the screen (05-android-app 2.7);
 * [onAction] opens the pairing graph. The fingerprints are not here: the certificate screen shows them.
 */
@Composable
internal fun HubNotice(kind: HubNoticeKind, onAction: () -> Unit, modifier: Modifier = Modifier) {
    NoticeCard(
        NoticeKind.Bad, stringResource(kind.text), modifier,
        actions = listOf(SwAction(stringResource(kind.action), onAction)),
    )
}
