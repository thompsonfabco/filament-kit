package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarData
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.SnackbarVisuals
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.res.painterResource
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** How long a toast is held: 5 s, 10 s when it has an action (05-android-app 3.1; AND-10). */
internal const val TOAST_MS = 5_000L
internal const val TOAST_WITH_ACTION_MS = 10_000L

private class ToastVisuals(
    override val message: String,
    override val actionLabel: String?,
    val kind: NoticeKind?,
) : SnackbarVisuals {
    override val withDismissAction = false
    override val duration = SnackbarDuration.Indefinite
}

/**
 * The shell's toast queue. Screens use it for a result whose control has gone away (a closed sheet, a popped
 * screen); a result with a control still on screen is a notice line next to it instead. The host holds one toast at
 * a time for [TOAST_MS], or [TOAST_WITH_ACTION_MS] with an action, by its own timer.
 */
internal class SwToastState {
    internal val host = SnackbarHostState()

    /** Shows [message] and returns when it is gone; [SnackbarResult.ActionPerformed] when the action was pressed. */
    suspend fun show(message: String, actionLabel: String? = null, kind: NoticeKind? = null): SnackbarResult = coroutineScope {
        val timer = launch {
            delay(if (actionLabel != null) TOAST_WITH_ACTION_MS else TOAST_MS)
            host.currentSnackbarData?.dismiss()
        }
        try {
            host.showSnackbar(ToastVisuals(message, actionLabel, kind))
        } finally {
            timer.cancel()
        }
    }
}

/** The shell provides it to every screen. */
internal val LocalToast = staticCompositionLocalOf<SwToastState?> { null }

/**
 * The `Scaffold`'s snackbar host: each message as a `Snackbar` on `surface` with a 1 dp `borderStrong` outline, the
 * `e2` shadow, `text` words and an `accentText` action, the kind's shape first when it has one.
 */
@Composable
internal fun SwToastHost(state: SwToastState, modifier: Modifier = Modifier) {
    SnackbarHost(state.host, modifier) { data -> SwToast(data) }
}

@Composable
private fun SwToast(data: SnackbarData) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val kind = (data.visuals as? ToastVisuals)?.kind
    val label = data.visuals.actionLabel
    val action: (@Composable () -> Unit)? = if (label == null) null else {
        { SwButton(label, { data.performAction() }, kind = SwButtonKind.Quiet) }
    }
    val shape = SpoolwardenTheme.shapes.r
    Snackbar(
        modifier = Modifier.padding(space.s3).shadow(SpoolwardenTheme.elevation.e2.depth, shape)
            .border(SpoolwardenTheme.sizes.hairline, colors.borderStrong, shape),
        action = action,
        shape = shape,
        containerColor = colors.surface,
        contentColor = colors.text,
        actionContentColor = colors.accentText,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (kind != null) {
                Icon(
                    painterResource(kind.shape), contentDescription = null, tint = kind.colour(colors),
                    modifier = Modifier.padding(end = space.s2).size(space.s2 + space.s1),
                )
            }
            Text(data.visuals.message)
        }
    }
}
