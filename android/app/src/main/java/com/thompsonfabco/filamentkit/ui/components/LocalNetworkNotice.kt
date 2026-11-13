package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.LocalNetworkAccess
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * The local network access notice (05-android-app 3.3), shown in place of the content of a Hub-backed screen on
 * Android 17 and later until access is granted: a panel with the title, the reason, and "Allow". When Android will
 * not ask again the text adds where to allow it and the button is "Open app settings".
 */
@Composable
internal fun LocalNetworkNotice(access: LocalNetworkAccess, modifier: Modifier = Modifier) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    OutlinedCard(
        modifier.fillMaxWidth(),
        shape = SpoolwardenTheme.shapes.r,
        colors = CardDefaults.outlinedCardColors(containerColor = colors.surface, contentColor = colors.text),
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.border),
    ) {
        Column(Modifier.padding(space.s4), verticalArrangement = Arrangement.spacedBy(space.s2)) {
            Text(
                stringResource(R.string.network_title), style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.semantics { heading() },
            )
            Text(stringResource(R.string.network_text), style = MaterialTheme.typography.bodyMedium)
            if (access.showSettings) {
                Text(stringResource(R.string.network_no_ask), style = MaterialTheme.typography.bodyMedium)
                SwButton(
                    stringResource(R.string.common_open_app_settings), access.openSettings,
                    Modifier.fillMaxWidth(), kind = SwButtonKind.Main,
                )
            } else {
                SwButton(stringResource(R.string.common_allow), access.request, Modifier.fillMaxWidth(), kind = SwButtonKind.Main)
            }
        }
    }
}
