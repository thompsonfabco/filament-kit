package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
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
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

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
 * screen); a result with a control still on screen is a notice line next to it instead. Toasts show one at a time,
 * in the order asked for; each is held [TOAST_MS], or [TOAST_WITH_ACTION_MS] with an action, from the moment it is
 * shown, by a timer that dismisses only that toast.
 */
internal class SwToastState {
    internal val host = SnackbarHostState()
    private val turn = Mutex()

    /** Shows [message] and returns when it is gone; [SnackbarResult.ActionPerformed] when the action was pressed. */
    suspend fun show(message: String, actionLabel: String? = null, kind: NoticeKind? = null): SnackbarResult =
        turn.withLock {
            // the host is free now, so this toast is the one on screen as soon as showSnackbar runs
            coroutineScope {
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
}

/** The shell provides it to every screen. */
internal val LocalToast = staticCompositionLocalOf<SwToastState?> { null }

/**
 * The `Scaffold`'s snackbar host: each message on `surface` with a 1 dp `borderStrong` outline, one `e2` shadow,
 * `text` words and an `accentText` action, the kind's shape first when it has one.
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
    Surface(
        modifier = Modifier.padding(space.s3),
        shape = SpoolwardenTheme.shapes.r,
        color = colors.surface,
        contentColor = colors.text,
        tonalElevation = 0.dp,
        shadowElevation = SpoolwardenTheme.elevation.e2.depth,
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.borderStrong),
    ) {
        Row(Modifier.padding(start = space.s3), verticalAlignment = Alignment.CenterVertically) {
            if (kind != null) {
                Icon(
                    painterResource(kind.shape), contentDescription = null, tint = kind.colour(colors),
                    modifier = Modifier.padding(end = space.s2).size(kind.side(space)),
                )
            }
            Text(
                data.visuals.message, Modifier.weight(1f).padding(vertical = space.s3),
                style = MaterialTheme.typography.bodyMedium,
            )
            if (label != null) SwButton(label, { data.performAction() }, kind = SwButtonKind.Quiet)
        }
    }
}
