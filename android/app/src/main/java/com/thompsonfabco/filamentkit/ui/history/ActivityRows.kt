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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ActivityEvent
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.hub.hubTime
import com.thompsonfabco.filamentkit.ui.spool.DOT
import com.thompsonfabco.filamentkit.ui.spool.SpoolPanel
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** The first line of an activity row: the time in the phone's zone and language, then who did it. */
internal fun activityWhen(event: ActivityEvent): String =
    listOfNotNull(hubTime(event.at)?.takeIf { it.isNotBlank() }, event.who.takeIf { it.isNotBlank() }).joinToString(DOT)

/**
 * A list of what was done (R84 section 2): time and who, then what, the Hub's own sentence. A row the Hub still lets be
 * undone keeps **Undo**; [busy] is the event being undone. The section is left out when there are no [events] (an older
 * Hub sends none).
 */
@Composable
internal fun ActivityList(
    events: List<ActivityEvent>,
    busy: Long?,
    enabled: Boolean,
    onUndo: (ActivityEvent) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (events.isEmpty()) return
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    Column(modifier, verticalArrangement = Arrangement.spacedBy(space.s2)) {
        Text(
            HistoryTexts.ACTIVITY_TITLE, Modifier.semantics { heading() },
            style = MaterialTheme.typography.titleSmall, color = colors.muted,
        )
        SpoolPanel {
            events.forEachIndexed { i, event ->
                if (i > 0) HorizontalDivider(color = colors.border, thickness = SpoolwardenTheme.sizes.hairline)
                ActivityRow(event, busy == event.id, enabled, onUndo)
            }
        }
    }
}

@Composable
private fun ActivityRow(event: ActivityEvent, busy: Boolean, enabled: Boolean, onUndo: (ActivityEvent) -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val whenWho = activityWhen(event)
    Row(
        Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).padding(vertical = space.s2),
        horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            Modifier.weight(1f).semantics(mergeDescendants = true) { contentDescription = "$whenWho. ${event.text}" },
            verticalArrangement = Arrangement.spacedBy(space.s1),
        ) {
            Text(whenWho, style = MaterialTheme.typography.bodySmall, color = colors.muted)
            if (event.text.isNotBlank()) Text(event.text, style = MaterialTheme.typography.bodyMedium)
        }
        if (event.canUndo) {
            SwButton(stringResource(R.string.common_undo), { onUndo(event) }, kind = SwButtonKind.Quiet, enabled = enabled && !busy, busy = busy)
        }
    }
}
