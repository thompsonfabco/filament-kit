package com.thompsonfabco.filamentkit.ui.components

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.theme.Appearance

@get:StringRes
internal val Appearance.label: Int
    get() = when (this) {
        Appearance.Light -> R.string.appearance_light
        Appearance.Dark -> R.string.appearance_dark
        Appearance.System -> R.string.appearance_system
    }

@get:DrawableRes
internal val Appearance.icon: Int
    get() = when (this) {
        Appearance.Light -> R.drawable.sw_ic_sun
        Appearance.Dark -> R.drawable.sw_ic_moon
        Appearance.System -> R.drawable.sw_ic_half_circle
    }

/**
 * The top bar's appearance control (05-android-app 2.2): an icon button showing the current choice, opening a menu of
 * Light, Dark and System with the current one checked. A choice applies at once.
 */
@Composable
internal fun AppearanceMenu(current: Appearance, onChoose: (Appearance) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        SwIconButton(current.icon, stringResource(R.string.a11y_appearance, stringResource(current.label)), { open = true })
        SwMenu(open, { open = false }) {
            Appearance.entries.forEach { choice ->
                SwMenuItem(
                    text = stringResource(choice.label),
                    onClick = {
                        open = false
                        onChoose(choice)
                    },
                    icon = choice.icon,
                    checked = choice == current,
                )
            }
        }
    }
}
