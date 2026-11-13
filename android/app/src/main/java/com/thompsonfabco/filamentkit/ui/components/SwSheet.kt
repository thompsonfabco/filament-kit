package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.ZeroCornerSize
import androidx.compose.material3.BottomSheetDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** A bottom sheet: `surface` ground, `rL` top corners, the theme's scrim, no tonal tint (08-platform-mapping 10.8). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SwSheet(onDismiss: () -> Unit, content: @Composable ColumnScope.() -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        shape = SpoolwardenTheme.shapes.rL.copy(bottomStart = ZeroCornerSize, bottomEnd = ZeroCornerSize),
        containerColor = colors.surface,
        scrimColor = colors.scrim,
        tonalElevation = 0.dp,
        dragHandle = {
            BottomSheetDefaults.DragHandle(
                modifier = Modifier.widthIn(min = space.s7), width = space.s6 + space.s1, height = space.s1,
                color = colors.borderStrong,
            )
        },
        content = content,
    )
}
