package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.layout.RowScope
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf

/**
 * What the screen on show adds to the end of the top bar (05-android-app 2.2: "Overflow: only where a screen names
 * one"). The shell owns one, provides it as [LocalTopBarActions] and draws [content] after its own controls.
 */
internal class TopBarActions {
    var content: (@Composable RowScope.() -> Unit)? by mutableStateOf(null)
}

internal val LocalTopBarActions = staticCompositionLocalOf<TopBarActions?> { null }

/** A screen's own top-bar actions, shown while the screen is in the composition and gone when it leaves. */
@Composable
internal fun ScreenTopBarActions(content: @Composable RowScope.() -> Unit) {
    val holder = LocalTopBarActions.current ?: return
    val latest by rememberUpdatedState(content)
    DisposableEffect(holder) {
        val mine: @Composable RowScope.() -> Unit = { latest() }
        holder.content = mine
        onDispose { if (holder.content === mine) holder.content = null }
    }
}
