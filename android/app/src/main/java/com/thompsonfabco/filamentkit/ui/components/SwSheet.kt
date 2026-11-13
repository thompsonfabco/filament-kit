package com.thompsonfabco.filamentkit.ui.components

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.ZeroCornerSize
import androidx.compose.material3.BottomSheetDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.ModalBottomSheetProperties
import androidx.compose.material3.SheetValue
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * A bottom sheet: `surface` ground, `rL` top corners, the theme's scrim, no tonal tint (08-platform-mapping 10.8).
 * With [gesturesEnabled] false the sheet holds work that cannot be taken back: Back, the scrim and a swipe do nothing.
 * With [onBlockedDismiss] they call it instead (it asks "Leave without saving?"); the screen takes the sheet away itself.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SwSheet(
    onDismiss: () -> Unit,
    gesturesEnabled: Boolean = true,
    onBlockedDismiss: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val blocked = rememberUpdatedState(onBlockedDismiss)
    val enabled = rememberUpdatedState(gesturesEnabled)
    val state = rememberModalBottomSheetState(
        confirmValueChange = { target ->
            when {
                target != SheetValue.Hidden -> true
                !enabled.value -> false
                blocked.value != null -> {
                    blocked.value?.invoke()
                    false
                }
                else -> true
            }
        },
    )
    val held = !gesturesEnabled || onBlockedDismiss != null
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        // a sheet that holds work which cannot be taken back is not swiped away
        sheetGesturesEnabled = gesturesEnabled,
        sheetState = state,
        properties = ModalBottomSheetProperties(shouldDismissOnBackPress = !held),
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
    ) {
        // the system Back button of the sheet's own window
        BackHandler(enabled = held) { if (gesturesEnabled) blocked.value?.invoke() }
        content()
    }
}
