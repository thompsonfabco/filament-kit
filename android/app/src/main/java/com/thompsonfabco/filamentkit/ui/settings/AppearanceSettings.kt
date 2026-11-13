package com.thompsonfabco.filamentkit.ui.settings

import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.icon
import com.thompsonfabco.filamentkit.ui.components.label
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * Appearance (05-android-app 12.2): Light, Dark or System as a segmented control with icons and words, applied at
 * once. The Theme picker joins it with S6.3.
 */
@Composable
internal fun AppearanceSettings(current: Appearance, onChoose: (Appearance) -> Unit, modifier: Modifier = Modifier) {
    val colors = SpoolwardenTheme.colors
    SettingsPage(modifier) {
        GroupTitle(stringResource(R.string.appearance_title))
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            Appearance.entries.forEachIndexed { index, choice ->
                SegmentedButton(
                    selected = choice == current,
                    onClick = { onChoose(choice) },
                    shape = SegmentedButtonDefaults.itemShape(index, Appearance.entries.size),
                    modifier = Modifier.heightIn(min = SpoolwardenTheme.sizes.row),
                    colors = SegmentedButtonDefaults.colors(
                        activeContainerColor = colors.accent, activeContentColor = colors.onAccent,
                        activeBorderColor = colors.accent,
                        inactiveContainerColor = colors.surface, inactiveContentColor = colors.text,
                        inactiveBorderColor = colors.borderStrong,
                    ),
                    icon = { SwIcon(choice.icon, null) },
                    label = { Text(stringResource(choice.label), style = MaterialTheme.typography.labelLarge) },
                )
            }
        }
        Text(
            stringResource(R.string.appearance_note), color = colors.muted, style = MaterialTheme.typography.bodySmall,
        )
    }
}
