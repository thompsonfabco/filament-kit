package com.thompsonfabco.filamentkit.ui.components

import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** The menu surface: `surface` ground, `r` corners, 1 dp `borderStrong`, the `e2` shadow, no tonal tint. */
@Composable
internal fun SwMenu(expanded: Boolean, onDismiss: () -> Unit, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val colors = SpoolwardenTheme.colors
    DropdownMenu(
        expanded = expanded,
        onDismissRequest = onDismiss,
        modifier = modifier,
        shape = SpoolwardenTheme.shapes.r,
        containerColor = colors.surface,
        tonalElevation = 0.dp,
        shadowElevation = SpoolwardenTheme.elevation.e2.depth,
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.borderStrong),
        content = content,
    )
}

/** One choice of a [SwMenu], at least 48 dp high; the current one carries the check mark in `accentText`. */
@Composable
internal fun SwMenuItem(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    @DrawableRes icon: Int? = null,
    checked: Boolean = false,
    enabled: Boolean = true,
) {
    val colors = SpoolwardenTheme.colors
    DropdownMenuItem(
        text = { Text(text, style = MaterialTheme.typography.bodyMedium) },
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.semantics { selected = checked },
        leadingIcon = icon?.let { { SwIcon(it, null) } },
        trailingIcon = if (checked) {
            { SwIcon(R.drawable.sw_ic_check, null, tint = colors.accentText) }
        } else {
            null
        },
        colors = MenuDefaults.itemColors(
            textColor = colors.text, disabledTextColor = colors.muted, leadingIconColor = colors.muted, trailingIconColor = colors.accentText,
        ),
    )
}
