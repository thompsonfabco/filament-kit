package com.thompsonfabco.filamentkit.ui.components

import android.view.View
import android.view.accessibility.AccessibilityManager
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.ZeroCornerSize
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.BottomSheetDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.ModalBottomSheetProperties
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
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
    DetailStyle.Sheet -> DetailPresentation.Sheet
    // Panes: on phones drill-in stays its own screen; on Tablet (2 panes) and Desktop (3 panes) use Pane.
    DetailStyle.Pane -> if (window == WindowClass.Phone) DetailPresentation.Screen else DetailPresentation.Pane
}

/** Reads [LocalDetailStyle] and [SpoolwardenTheme.window] to return the active [DetailPresentation]. */
@Composable
internal fun rememberDetailPresentation(): DetailPresentation =
    detailPresentation(LocalDetailStyle.current, SpoolwardenTheme.window)

/**
 * Container for an expanded card's detail in Workbench (`DetailStyle.Card`).
 *
 * Moves focus into the detail when it opens; the caller returns focus to the row on close.
 */
@Composable
internal fun SwCardDetail(
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    canClose: Boolean = true,
    content: @Composable () -> Unit,
) {
    val space = SpoolwardenTheme.space
    val detailFocus = remember { FocusRequester() }
    val view = LocalView.current
    LaunchedEffect(Unit) {
        repeat(2) { withFrameNanos { } }
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
                { if (canClose) onClose() },
                modifier = Modifier.focusRequester(detailFocus).focusable(),
            )
        }
        Box(Modifier.fillMaxWidth()) {
            content()
        }
    }
}

/**
 * Full-height modal sheet for Palette (`DetailStyle.Sheet`).
 *
 * Opens fully expanded (`skipPartiallyExpanded = true`), moves focus into the detail, and closes on system Back
 * or the Close button.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SwSheetDetail(
    onClose: () -> Unit,
    gesturesEnabled: Boolean = true,
    content: @Composable () -> Unit,
) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val detailFocus = remember { FocusRequester() }
    val view = LocalView.current
    LaunchedEffect(state.currentValue) {
        if (state.currentValue == androidx.compose.material3.SheetValue.Expanded) {
            repeat(2) { withFrameNanos { } }
            requestDetailFocus(detailFocus, view)
        }
    }
    ModalBottomSheet(
        onDismissRequest = onClose,
        sheetGesturesEnabled = gesturesEnabled,
        sheetState = state,
        properties = ModalBottomSheetProperties(shouldDismissOnBackPress = gesturesEnabled),
        shape = SpoolwardenTheme.shapes.rL.copy(bottomStart = ZeroCornerSize, bottomEnd = ZeroCornerSize),
        containerColor = colors.surface,
        scrimColor = colors.scrim,
        tonalElevation = 0.dp,
        dragHandle = {
            BottomSheetDefaults.DragHandle(
                width = space.s6 + space.s1,
                height = space.s1,
                color = colors.borderStrong,
            )
        },
    ) {
        BackHandler(enabled = gesturesEnabled, onBack = onClose)
        Column(Modifier.fillMaxWidth().fillMaxHeight()) {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = space.s3),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                SwIconButton(
                    R.drawable.sw_ic_close,
                    stringResource(R.string.common_close),
                    { if (gesturesEnabled) onClose() },
                    modifier = Modifier.focusRequester(detailFocus).focusable(),
                )
            }
            HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = colors.border)
            Box(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState())) {
                content()
            }
        }
    }
}

/**
 * Whether a numbered step in a detail view shows its body: in `DetailPresentation.Sheet`, only the [current] step
 * is open and finished or later steps collapse to their title line (02-components 6.2).
 */
internal fun stepExpanded(presentation: DetailPresentation, current: Boolean): Boolean =
    presentation != DetailPresentation.Sheet || current

/** A step in a detail view: always shows [title], and shows [body] when [stepExpanded] is true. */
@Composable
internal fun SwDetailStep(
    title: String,
    current: Boolean,
    modifier: Modifier = Modifier,
    body: @Composable () -> Unit,
) {
    val presentation = rememberDetailPresentation()
    val space = SpoolwardenTheme.space
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(space.s2)) {
        Text(title, Modifier.semantics { heading() }, style = MaterialTheme.typography.titleMedium)
        if (stepExpanded(presentation, current)) {
            body()
        }
    }
}

internal const val EMPTY_PANE_TAG = "detail-empty-pane"

/**
 * Side-by-side detail layout for Panes (`DetailStyle.Pane`) on wide windows.
 *
 * On `Desktop` (three panes total with `SwNav`'s section list), shows the [list] pane beside the [detail] pane
 * (or the [emptyText] empty-pane state when [hasSelection] is false).
 * On `Tablet` (two panes total with `SwNav`'s section list), shows either the [list] or the active [detail]
 * with a Back button and system Back support.
 */
@Composable
internal fun SwPaneLayout(
    hasSelection: Boolean,
    emptyText: String,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    canClose: Boolean = true,
    list: @Composable () -> Unit,
    detail: @Composable () -> Unit,
) {
    val window = SpoolwardenTheme.window
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val detailFocus = remember { FocusRequester() }
    val view = LocalView.current

    if (hasSelection) {
        LaunchedEffect(Unit) {
            repeat(2) { withFrameNanos { } }
            requestDetailFocus(detailFocus, view)
        }
        BackHandler(enabled = canClose, onBack = onClose)
    }

    if (window == WindowClass.Desktop) {
        Row(modifier.fillMaxSize()) {
            Box(Modifier.weight(1f).fillMaxHeight()) {
                list()
            }
            Box(Modifier.width(SpoolwardenTheme.sizes.hairline).fillMaxHeight().background(colors.border))
            Column(Modifier.widthIn(min = SpoolwardenTheme.sizes.drawer).weight(1f).fillMaxHeight()) {
                if (hasSelection) {
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = space.s3),
                        horizontalArrangement = Arrangement.End,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        SwIconButton(
                            R.drawable.sw_ic_close,
                            stringResource(R.string.common_close),
                            { if (canClose) onClose() },
                            modifier = Modifier.focusRequester(detailFocus).focusable(),
                        )
                    }
                    HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = colors.border)
                    Box(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState())) {
                        detail()
                    }
                } else {
                    Box(
                        Modifier.fillMaxSize().padding(space.s4).testTag(EMPTY_PANE_TAG),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(emptyText, style = MaterialTheme.typography.bodyMedium, color = colors.muted)
                    }
                }
            }
        }
    } else {
        if (hasSelection) {
            Column(modifier.fillMaxSize()) {
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = space.s3),
                    horizontalArrangement = Arrangement.Start,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    SwIconButton(
                        R.drawable.sw_ic_chevron,
                        stringResource(R.string.common_back),
                        { if (canClose) onClose() },
                        modifier = Modifier.rotate(180f).focusRequester(detailFocus).focusable(),
                    )
                }
                HorizontalDivider(thickness = SpoolwardenTheme.sizes.hairline, color = colors.border)
                Box(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState())) {
                    detail()
                }
            }
        } else {
            Box(modifier.fillMaxSize()) {
                list()
            }
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
