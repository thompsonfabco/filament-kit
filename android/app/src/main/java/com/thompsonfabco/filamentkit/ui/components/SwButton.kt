package com.thompsonfabco.filamentkit.ui.components

import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** The five buttons of 02-components 4.1 and 08-platform-mapping 10.3. */
internal enum class SwButtonKind {
    /** Filled with `accent`: at most one enabled per screen, sheet or dialog. */
    Main,
    Plain,

    /** Text in `accentText`: "Cancel", "Not now", actions inside a notice. */
    Quiet,

    /** Outline and text in `bad`. */
    Destructive,

    /** Filled `bad`: only the confirming button of a destructive dialog. */
    DestructiveFilled,
}

/** Marks the filled main button for the one-filled-button tests (05-android-app 5). */
internal val MAIN_BUTTON_TAG = SwTag.MainButton.name

/** A label and what it does: the buttons of a notice or an empty state. */
internal class SwAction(val label: String, val onClick: () -> Unit)

/**
 * A button of one of the [SwButtonKind]s: `r` corners, at least `density.control` high (and 48 dp to touch), no
 * shadow. While [busy] it shows the spinner before its label (or only "Working…" with animations off) and does
 * nothing when pressed; disabled buttons are on `surface2` with `muted` words.
 */
@Composable
internal fun SwButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    kind: SwButtonKind = SwButtonKind.Plain,
    enabled: Boolean = true,
    busy: Boolean = false,
    /** A drawing before the words (decoration: the words name the button). */
    @DrawableRes icon: Int? = null,
) {
    val colors = SpoolwardenTheme.colors
    val shape = SpoolwardenTheme.shapes.r
    val active = enabled && !busy
    val sized = modifier.heightIn(min = SpoolwardenTheme.density.control)
    val padding = PaddingValues(horizontal = SpoolwardenTheme.space.s3)
    val line = SpoolwardenTheme.sizes.hairline
    val content: @Composable RowScope.() -> Unit = { ButtonLabel(text, busy, icon) }
    when (kind) {
        SwButtonKind.Main -> {
            val interaction = remember { MutableInteractionSource() }
            val pressed by interaction.collectIsPressedAsState()
            Button(
                onClick = onClick, modifier = sized.testTag(MAIN_BUTTON_TAG), enabled = active, shape = shape,
                contentPadding = padding, interactionSource = interaction,
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (pressed) colors.accentHover else colors.accent, contentColor = colors.onAccent,
                    disabledContainerColor = colors.surface2, disabledContentColor = colors.muted,
                ),
                elevation = flat(), content = content,
            )
        }
        SwButtonKind.DestructiveFilled -> Button(
            onClick = onClick, modifier = sized, enabled = active, shape = shape, contentPadding = padding,
            colors = ButtonDefaults.buttonColors(
                containerColor = colors.bad, contentColor = colors.onBad,
                disabledContainerColor = colors.surface2, disabledContentColor = colors.muted,
            ),
            elevation = flat(), content = content,
        )
        SwButtonKind.Plain, SwButtonKind.Destructive -> {
            val plain = kind == SwButtonKind.Plain
            OutlinedButton(
                onClick = onClick, modifier = sized, enabled = active, shape = shape, contentPadding = padding,
                colors = ButtonDefaults.outlinedButtonColors(
                    containerColor = if (plain) colors.surface else Color.Transparent,
                    contentColor = if (plain) colors.text else colors.bad,
                    disabledContainerColor = colors.surface2, disabledContentColor = colors.muted,
                ),
                border = BorderStroke(line, if (!active) colors.border else if (plain) colors.borderStrong else colors.bad),
                content = content,
            )
        }
        SwButtonKind.Quiet -> TextButton(
            onClick = onClick, modifier = sized, enabled = active, shape = shape, contentPadding = padding,
            colors = ButtonDefaults.textButtonColors(contentColor = colors.accentText, disabledContentColor = colors.muted),
            content = content,
        )
    }
}

@Composable
private fun flat() = ButtonDefaults.buttonElevation(0.dp, 0.dp, 0.dp, 0.dp, 0.dp)

@Composable
private fun RowScope.ButtonLabel(text: String, busy: Boolean, icon: Int?) {
    if (busy && reducedMotion) {
        Text(stringResource(R.string.common_working), style = MaterialTheme.typography.labelLarge)
        return
    }
    if (busy) {
        SwSpinner()
        Spacer(Modifier.width(SpoolwardenTheme.space.s2))
    }
    if (icon != null && !busy) {
        SwIcon(icon, null)
        Spacer(Modifier.width(SpoolwardenTheme.space.s2))
    }
    Text(text, style = MaterialTheme.typography.labelLarge)
}
