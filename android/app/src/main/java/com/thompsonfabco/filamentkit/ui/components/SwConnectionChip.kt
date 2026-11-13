package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.nav.HubState
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * The Hub connection as shape plus word (05-android-app 2.4); tapping it opens the Hub connection sheet. Before the
 * first check has an answer it is a skeleton of the badge's width, named "Hub connection: checking".
 */
@Composable
internal fun SwConnectionChip(state: HubState, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val colors = SpoolwardenTheme.colors
    val sizes = SpoolwardenTheme.sizes
    val badge = state.badge
    if (badge == null) {
        val name = stringResource(R.string.hub_chip_checking)
        Box(
            modifier.minimumInteractiveComponentSize().clickable(role = Role.Button, onClick = onClick)
                .semantics { contentDescription = name },
        ) {
            Box(
                Modifier.width(SpoolwardenTheme.space.s7 * 2).height(sizes.chip)
                    .background(colors.surface2, SpoolwardenTheme.shapes.rS),
            )
        }
        return
    }
    val name = stringResource(R.string.a11y_hub_chip, stringResource(badge.word))
    AssistChip(
        onClick = onClick,
        label = { StatusLabel(badge) },
        modifier = modifier.semantics { contentDescription = name },
        shape = SpoolwardenTheme.shapes.r,
        colors = AssistChipDefaults.assistChipColors(containerColor = colors.surface, labelColor = colors.text),
        border = AssistChipDefaults.assistChipBorder(
            enabled = true, borderColor = colors.borderStrong, borderWidth = sizes.hairline,
        ),
    )
}
