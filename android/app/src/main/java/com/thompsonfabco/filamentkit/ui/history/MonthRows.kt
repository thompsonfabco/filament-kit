package com.thompsonfabco.filamentkit.ui.history

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.ui.spool.DOT
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * The By month table of a printer's Filament used (R84 5.7): a row per month, newest first. The month and the grams
 * come first, then the prints, those that did not finish and the most used material. The panel around it is the caller's.
 */
@Composable
internal fun MonthRows(lines: List<MonthLine>, modifier: Modifier = Modifier) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    Column(modifier) {
        lines.forEachIndexed { i, line ->
            if (i > 0) HorizontalDivider(color = colors.border, thickness = SpoolwardenTheme.sizes.hairline)
            Column(
                Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).padding(horizontal = space.s4, vertical = space.s2)
                    .semantics(mergeDescendants = true) { contentDescription = line.spoken },
                verticalArrangement = Arrangement.spacedBy(space.s1),
            ) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text(line.month, style = MaterialTheme.typography.bodyMedium)
                    Text(line.grams, style = SpoolwardenTheme.type.data)
                }
                Text(
                    listOfNotNull(line.prints, line.unfinished, line.material).joinToString(DOT),
                    color = colors.muted, style = SpoolwardenTheme.type.dataSmall,
                )
            }
        }
    }
}
