package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * The progress line (02-components 8.3): 4 dp, track `surface3`, a solid `accentText` fill with no gap and no stop
 * mark. Determinate with a [value] from 0 to 1 (the Hub gave a number), indeterminate when [value] is null. A failed
 * task draws its fill in `bad`. [state] puts the value in words for TalkBack ("42 %").
 */
@Composable
internal fun SwProgress(value: Float?, modifier: Modifier = Modifier, failed: Boolean = false, state: String? = null) {
    val colors = SpoolwardenTheme.colors
    val fill = if (failed) colors.bad else colors.accentText
    val line = modifier.fillMaxWidth().height(SpoolwardenTheme.space.s1)
        .then(if (state != null) Modifier.semantics { stateDescription = state } else Modifier)
    if (value == null) {
        LinearProgressIndicator(modifier = line, color = fill, trackColor = colors.surface3, gapSize = 0.dp)
    } else {
        LinearProgressIndicator(
            progress = { value.coerceIn(0f, 1f) }, modifier = line, color = fill, trackColor = colors.surface3,
            gapSize = 0.dp, drawStopIndicator = {},
        )
    }
}
