package com.thompsonfabco.filamentkit.ui.components

import androidx.annotation.DrawableRes
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.IconButton
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.Text
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipAnchorPosition
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.rememberTooltipState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * An icon button with its name as tooltip (long-press). 48 dp, Material's touch size; [contentDescription] is
 * required, as the web's `aria-label` is.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SwIconButton(
    @DrawableRes icon: Int,
    contentDescription: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    tint: Color = LocalContentColor.current,
    iconModifier: Modifier = Modifier,
) {
    val colors = SpoolwardenTheme.colors
    TooltipBox(
        positionProvider = TooltipDefaults.rememberTooltipPositionProvider(TooltipAnchorPosition.Below),
        tooltip = {
            PlainTooltip(containerColor = colors.text, contentColor = colors.surface, shape = SpoolwardenTheme.shapes.rS) {
                Text(contentDescription, style = MaterialTheme.typography.bodySmall)
            }
        },
        state = rememberTooltipState(),
    ) {
        IconButton(onClick, modifier) { SwIcon(icon, contentDescription, iconModifier, tint = tint) }
    }
}
