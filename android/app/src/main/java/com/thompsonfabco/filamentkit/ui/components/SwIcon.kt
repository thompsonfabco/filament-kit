package com.thompsonfabco.filamentkit.ui.components

import androidx.annotation.DrawableRes
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalContentColor
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

internal enum class SwIconSize { Small, Normal, Large }

/**
 * One of the generated `sw_ic_<name>` drawings (08-platform-mapping 11). The tint recolours the black drawing the way
 * `currentColor` does; a null [contentDescription] marks the icon as decoration beside a word.
 */
@Composable
internal fun SwIcon(
    @DrawableRes icon: Int,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    size: SwIconSize = SwIconSize.Normal,
    tint: Color = LocalContentColor.current,
) {
    val space = SpoolwardenTheme.space
    val side = when (size) {
        SwIconSize.Small -> space.s4
        SwIconSize.Normal -> space.s4 + space.s1
        SwIconSize.Large -> space.s5 + space.s1
    }
    Icon(painterResource(icon), contentDescription, modifier.size(side), tint)
}
