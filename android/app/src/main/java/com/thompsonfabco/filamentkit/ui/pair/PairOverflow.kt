package com.thompsonfabco.filamentkit.ui.pair

import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.ScreenTopBarActions
import com.thompsonfabco.filamentkit.ui.components.SwIconButton
import com.thompsonfabco.filamentkit.ui.components.SwMenu
import com.thompsonfabco.filamentkit.ui.components.SwMenuItem

/**
 * The overflow of the pairing graph's top bar (05-android-app 4): "More actions" with "Settings", for the Hub
 * connection settings a person may need before a Hub is paired. [onSettings] opens the Settings screens over the
 * pairing step; Back returns to it.
 */
@Composable
internal fun PairTopBarOverflow(onSettings: () -> Unit) {
    ScreenTopBarActions {
        var open by remember { mutableStateOf(false) }
        Box {
            SwIconButton(R.drawable.sw_ic_more, stringResource(R.string.common_more_actions), { open = true })
            SwMenu(open, { open = false }) {
                SwMenuItem(stringResource(R.string.nav_settings), { open = false; onSettings() }, icon = R.drawable.sw_ic_settings)
            }
        }
    }
}
