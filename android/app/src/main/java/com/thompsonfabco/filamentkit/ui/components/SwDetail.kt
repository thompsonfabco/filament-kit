package com.thompsonfabco.filamentkit.ui.components

import android.view.View
import android.view.accessibility.AccessibilityManager
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.theme.DetailStyle
import com.thompsonfabco.filamentkit.ui.theme.LocalDetailStyle
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass

/** How a list-detail screen opens one item's detail, chosen from [DetailStyle] and [WindowClass]. */
internal enum class DetailPresentation {
    /** Its own navigation destination (Console, and phones in Workbench/Panes). */
    Screen,

    /** Expands in place inside its card in the grid (Workbench on wide windows). */
    Card,

    /** Full-height modal sheet, one step at a time (Palette). */
    Sheet,

    /** Side-by-side detail pane (Panes on wide windows). */
    Pane,
}

/**
 * Chooses how a detail opens from the theme's [DetailStyle] and the window's [WindowClass].
 *
 * Workbench (`DetailStyle.Card`): on wide windows (`Tablet`, `Desktop`) a card expands in place;
 * on phones (`WindowClass.Phone`) the detail stays its own screen.
 */
internal fun detailPresentation(style: DetailStyle, window: WindowClass): DetailPresentation = when (style) {
    DetailStyle.Inline -> DetailPresentation.Screen
    DetailStyle.Card -> if (window == WindowClass.Phone) DetailPresentation.Screen else DetailPresentation.Card
    DetailStyle.Sheet -> DetailPresentation.Screen
    DetailStyle.Pane -> DetailPresentation.Screen
}

/** Reads [LocalDetailStyle] and [SpoolwardenTheme.window] to return the active [DetailPresentation]. */
@Composable
internal fun rememberDetailPresentation(): DetailPresentation =
    detailPresentation(LocalDetailStyle.current, SpoolwardenTheme.window)

/**
 * Container for an expanded card's detail in Workbench (`DetailStyle.Card`).
 *
 * Moves focus into the detail when it opens and returns focus to [returnFocusTo] when it closes.
 */
@Composable
internal fun SwCardDetail(
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val space = SpoolwardenTheme.space
    val detailFocus = remember { FocusRequester() }
    val view = LocalView.current
    LaunchedEffect(Unit) {
        requestDetailFocus(detailFocus, view)
    }
    Column(modifier.fillMaxWidth().padding(top = space.s3)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = space.s3),
            horizontalArrangement = Arrangement.End,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            SwIconButton(
                R.drawable.sw_ic_close,
                stringResource(R.string.common_close),
                onClose,
                modifier = Modifier.focusRequester(detailFocus).focusable(),
            )
        }
        Box(Modifier.fillMaxWidth()) {
            content()
        }
    }
}

/** Requests input focus on [requester] and accessibility focus when touch exploration is active. */
internal fun requestDetailFocus(requester: FocusRequester, view: View) {
    runCatching { requester.requestFocus() }
    val am = view.context.getSystemService(AccessibilityManager::class.java)
    if (am?.isTouchExplorationEnabled == true) {
        view.findFocus()?.performAccessibilityAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS, null)
    }
}
