package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * The tile of `CollectionStyle.Tiles` (02-components 6.1, 08-platform-mapping 10.5): a `Card` of `surface` with a 1 dp
 * `border`, padded `--s4`. At the top the [visual] (the spool ring) centred, at least `--s7` x 2 high; then the [title]
 * in `--fs-l` at the title weight with its [subtitle] and [status]; then the priority 1 fields ([fields], each a
 * [TileField] with its name); at the foot the main action, [actionLabel], the full width of the tile. The tile is as high
 * as its line of tiles, the action at the bottom. The part above the action is one node for TalkBack ([description]) and
 * opens the item like the action does.
 */
@Composable
internal fun SwTile(
    title: String,
    description: String,
    actionLabel: String,
    onAction: () -> Unit,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    status: (@Composable () -> Unit)? = null,
    visual: (@Composable () -> Unit)? = null,
    enabled: Boolean = true,
    fields: @Composable ColumnScope.() -> Unit = {},
) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val open = stringResource(R.string.a11y_action_open)
    Card(
        modifier.fillMaxWidth().fillMaxHeight(),
        shape = SpoolwardenTheme.shapes.r,
        colors = CardDefaults.cardColors(containerColor = colors.surface, contentColor = colors.text),
        border = BorderStroke(SpoolwardenTheme.sizes.hairline, colors.border),
    ) {
        Column(Modifier.fillMaxHeight().padding(space.s4), verticalArrangement = Arrangement.spacedBy(space.s2)) {
            Column(
                Modifier.fillMaxWidth().clickable(enabled = enabled, onClickLabel = open, onClick = onAction)
                    .semantics(mergeDescendants = true) { contentDescription = description },
                verticalArrangement = Arrangement.spacedBy(space.s2),
            ) {
                if (visual != null) {
                    Box(Modifier.fillMaxWidth().heightIn(min = space.s7 * 2), contentAlignment = Alignment.Center) { visual() }
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.Top) {
                    Column(Modifier.weight(1f)) {
                        Text(title, style = MaterialTheme.typography.titleMedium, color = if (enabled) colors.text else colors.muted)
                        if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = colors.muted)
                    }
                    status?.invoke()
                }
                fields()
            }
            Spacer(Modifier.weight(1f))
            SwButton(actionLabel, onAction, Modifier.fillMaxWidth(), enabled = enabled)
        }
    }
}

/** One field of a tile, "Name: value": the name in `muted` (02-components 6.1, the key of a cell). */
@Composable
internal fun TileField(name: String, value: String, modifier: Modifier = Modifier) {
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s1)) {
        Text(stringResource(R.string.common_field_label, name), style = MaterialTheme.typography.bodyMedium, color = SpoolwardenTheme.colors.muted)
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}
