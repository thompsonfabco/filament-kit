package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** True while the system's "Remove animations" is on: the theme then has 0 ms for every motion token. */
internal val reducedMotion: Boolean @Composable get() = SpoolwardenTheme.motion.base == 0

/**
 * The inline spinner (02-components 8.1): a 16 dp ring in the current content colour, inside the button that started
 * the work or beside the words that say what. With animations off it is the word "Working…" instead. The ring is
 * decoration; the words around it are what is read.
 */
@Composable
internal fun SwSpinner(modifier: Modifier = Modifier, color: Color = LocalContentColor.current) {
    val space = SpoolwardenTheme.space
    if (reducedMotion) {
        Text(stringResource(R.string.common_working), modifier, color = color, style = MaterialTheme.typography.labelMedium)
    } else {
        CircularProgressIndicator(
            modifier.size(space.s4).clearAndSetSemantics { },
            color = color,
            strokeWidth = space.s1 / 2,
            trackColor = Color.Transparent,
        )
    }
}
