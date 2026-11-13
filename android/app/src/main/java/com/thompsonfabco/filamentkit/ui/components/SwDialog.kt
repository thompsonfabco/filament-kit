package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.BasicAlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.paneTitle
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.DialogWindowProvider
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass

/** The confirming button of a [SwDialog]: Main, or DestructiveFilled in a danger dialog. */
internal class SwDialogButton(
    val label: String,
    val onClick: () -> Unit,
    val kind: SwButtonKind = SwButtonKind.Main,
    val enabled: Boolean = true,
    val busy: Boolean = false,
)

/**
 * A dialog (05-android-app 3.1, 08-platform-mapping 10.8). On a Phone window the same content is a bottom sheet with
 * the buttons full width and stacked, the confirming one on top; on Tablet and Desktop it is a centred panel (`rL`
 * corners, `surface`, 1 dp `borderStrong`, the `e2` shadow, the theme's scrim) at most 30 rem wide, with the buttons
 * at the bottom right and the confirming one last. [onClose] runs on the scrim, the system Back button and Cancel.
 * Long bodies scroll.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SwDialog(
    title: String,
    onClose: () -> Unit,
    confirm: SwDialogButton,
    modifier: Modifier = Modifier,
    cancel: SwAction? = null,
    /** The control that opened the dialog: it gets focus back when the dialog closes (AND-12). */
    returnFocusTo: FocusRequester? = null,
    body: @Composable ColumnScope.() -> Unit,
) {
    val space = SpoolwardenTheme.space
    DisposableEffect(returnFocusTo) {
        // the trigger may have left the screen meanwhile; then there is nothing to focus
        onDispose { returnFocusTo?.let { runCatching { it.requestFocus() } } }
    }
    if (SpoolwardenTheme.window == WindowClass.Phone) {
        SwSheet(onClose) {
            Column(
                modifier.fillMaxWidth().semantics { paneTitle = title }.verticalScroll(rememberScrollState())
                    .padding(horizontal = space.s4).navigationBarsPadding().padding(bottom = space.s4),
                verticalArrangement = Arrangement.spacedBy(space.s3),
            ) {
                DialogTitle(title)
                body()
                DialogButton(confirm, Modifier.fillMaxWidth())
                cancel?.let { SwButton(it.label, it.onClick, Modifier.fillMaxWidth(), kind = SwButtonKind.Quiet) }
            }
        }
        return
    }
    val colors = SpoolwardenTheme.colors
    BasicAlertDialog(
        onDismissRequest = onClose,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        // the window's own dim is off; the theme's scrim is drawn here instead
        val window = (LocalView.current.parent as? DialogWindowProvider)?.window
        SideEffect { window?.setDimAmount(0f) }
        val maxWidth = with(LocalDensity.current) { (DIALOG_REM * REM_SP).sp.toDp() }
        BoxWithConstraints(
            Modifier.fillMaxSize().background(colors.scrim).pointerInput(onClose) { detectTapGestures { onClose() } },
            contentAlignment = Alignment.Center,
        ) {
            Surface(
                modifier.padding(space.s4).widthIn(max = maxWidth).heightIn(max = this.maxHeight - space.s4 * 2)
                    .semantics { paneTitle = title }.pointerInput(Unit) { detectTapGestures { } },
                shape = SpoolwardenTheme.shapes.rL,
                color = colors.surface,
                contentColor = colors.text,
                tonalElevation = 0.dp,
                shadowElevation = SpoolwardenTheme.elevation.e2.depth,
                border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.borderStrong),
            ) {
                Column(Modifier.padding(space.s4), verticalArrangement = Arrangement.spacedBy(space.s3)) {
                    DialogTitle(title)
                    Column(
                        Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()),
                        verticalArrangement = Arrangement.spacedBy(space.s2),
                        content = body,
                    )
                    DialogButtons(cancel, confirm)
                }
            }
        }
    }
}

@Composable
private fun DialogTitle(title: String) {
    Text(title, Modifier.semantics { heading() }, style = MaterialTheme.typography.titleMedium)
}

@Composable
private fun DialogButton(button: SwDialogButton, modifier: Modifier = Modifier) {
    SwButton(button.label, button.onClick, modifier, kind = button.kind, enabled = button.enabled, busy = button.busy)
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DialogButtons(cancel: SwAction?, confirm: SwDialogButton) {
    FlowRow(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2, Alignment.End),
    ) {
        cancel?.let { SwButton(it.label, it.onClick, kind = SwButtonKind.Quiet) }
        DialogButton(confirm)
    }
}

/** 30 rem, the dialog's width limit (02-components 1.2); a rem is 16 sp so it follows the font-size setting. */
private const val DIALOG_REM = 30
private const val REM_SP = 16
