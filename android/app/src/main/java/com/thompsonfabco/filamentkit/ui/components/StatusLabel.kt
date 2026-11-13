package com.thompsonfabco.filamentkit.ui.components

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenColors
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** The words of the status badge vocabulary (02-components 7.1) the shell needs; S4.4 adds the rest. */
internal enum class StatusKind(
    @DrawableRes val shape: Int,
    @StringRes val word: Int,
    /** Triangle and octagon are drawn a little larger (08-platform-mapping 10.6). */
    val large: Boolean,
    private val pick: (SpoolwardenColors) -> Color,
) {
    Connected(R.drawable.sw_st_filled, R.string.status_connected, false, { it.ok }),
    Offline(R.drawable.sw_st_hollow, R.string.status_offline, false, { it.bad }),
    NeedsLook(R.drawable.sw_st_triangle, R.string.status_needs_look, true, { it.warn });

    fun colour(colors: SpoolwardenColors): Color = pick(colors)
}

/** A status badge: the shape and the word in the kind's colour. The shape is decoration; the word is what is read. */
@Composable
internal fun StatusLabel(kind: StatusKind, modifier: Modifier = Modifier, small: Boolean = false) {
    val colour = kind.colour(SpoolwardenTheme.colors)
    val space = SpoolwardenTheme.space
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(space.s1), verticalAlignment = Alignment.CenterVertically) {
        Icon(
            painterResource(kind.shape), contentDescription = null,
            modifier = Modifier.size(if (kind.large) space.s2 + space.s1 else space.s2),
            tint = colour,
        )
        Text(
            stringResource(kind.word), color = colour, maxLines = 1,
            style = if (small) MaterialTheme.typography.labelMedium else MaterialTheme.typography.labelLarge,
        )
    }
}
