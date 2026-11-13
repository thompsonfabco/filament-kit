package com.thompsonfabco.filamentkit.ui.components

import androidx.annotation.DrawableRes
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.addOutline
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * The empty state (02-components 10.1): a soft disc with the section's [icon], a title, one sentence in `muted`, and
 * at most two buttons ([primary] filled, [secondary] plain). In a collection it sits in a panel with a dashed
 * `border` outline. The title is the heading below the screen's title.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun SwEmptyState(
    @DrawableRes icon: Int,
    title: String,
    text: String,
    modifier: Modifier = Modifier,
    primary: SwAction? = null,
    secondary: SwAction? = null,
    dashed: Boolean = true,
    /** The disc and icon of an error state: `badSoft` and `bad`. */
    problem: Boolean = false,
) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val sizes = SpoolwardenTheme.sizes
    val shape = SpoolwardenTheme.shapes.r
    val outline = if (dashed) {
        Modifier.drawBehind {
            val dash = space.s1.toPx()
            val width = sizes.hairline.toPx()
            drawPath(
                Path().apply { addOutline(shape.createOutline(size, layoutDirection, this@drawBehind)) }, colors.border,
                style = Stroke(width, pathEffect = PathEffect.dashPathEffect(floatArrayOf(dash, dash))),
            )
        }
    } else {
        Modifier
    }
    Column(
        modifier.fillMaxWidth().then(outline).padding(horizontal = space.s5, vertical = space.s7),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(space.s2),
    ) {
        Box(
            Modifier.size(sizes.emptyMark).background(if (problem) colors.badSoft else colors.accentSoft, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            SwIcon(icon, null, size = SwIconSize.Large, tint = if (problem) colors.bad else colors.accentText)
        }
        Text(
            title, style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center,
            modifier = Modifier.semantics { heading() },
        )
        Text(text, style = MaterialTheme.typography.bodyMedium, color = colors.muted, textAlign = TextAlign.Center)
        if (primary != null || secondary != null) {
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(space.s2, Alignment.CenterHorizontally),
                modifier = Modifier.heightIn(min = sizes.row),
            ) {
                secondary?.let { SwButton(it.label, it.onClick) }
                primary?.let { SwButton(it.label, it.onClick, kind = SwButtonKind.Main) }
            }
        }
    }
}
