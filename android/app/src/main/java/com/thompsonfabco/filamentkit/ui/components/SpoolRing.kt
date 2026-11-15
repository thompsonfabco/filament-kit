package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import com.thompsonfabco.filamentkit.ui.swatchColor
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** The three sizes of the spool ring (02-components 7.4): small `--s6`, medium `--s7` + `--s4`, large `--s7` x 2. */
internal enum class RingSize { Small, Medium, Large }

@Composable
internal fun ringSide(size: RingSize): Dp {
    val space = SpoolwardenTheme.space
    return when (size) {
        RingSize.Small -> space.s6
        RingSize.Medium -> space.s7 + space.s4
        RingSize.Large -> space.s7 * 2
    }
}

/**
 * One spool as a ring, the way it looks from the side (02-components 7.4): a track in `surface3`, an arc in the filament
 * colour from 12 o'clock clockwise for the [level] (0 to 1) left, a 1 dp `borderStrong` ring inside and outside the band
 * (pale colours stay visible) and a hub in `surface2`. The band is an eighth of the size. A null [level] is the full
 * track with no arc; an [empty] place is a dashed outline ring; a colour that is no colour draws the arc in `muted`. The
 * ring is decoration: the words that go with it say the same.
 */
@Composable
internal fun SpoolRing(hex: String?, level: Float?, size: RingSize, modifier: Modifier = Modifier, empty: Boolean = false) {
    val colors = SpoolwardenTheme.colors
    val side = ringSide(size)
    val hairline = SpoolwardenTheme.sizes.hairline
    val dash = SpoolwardenTheme.space.s1
    val fill = swatchColor(hex) ?: colors.muted
    Canvas(modifier.size(side)) {
        val line = hairline.toPx()
        val band = this.size.minDimension / RING_BAND
        val outer = this.size.minDimension / 2
        if (empty) {
            val r = outer - line / 2
            drawCircle(
                colors.borderStrong, r, center, style = Stroke(line, pathEffect = PathEffect.dashPathEffect(floatArrayOf(dash.toPx(), dash.toPx()))),
            )
            return@Canvas
        }
        val mid = outer - band / 2
        drawCircle(colors.surface3, mid, center, style = Stroke(band))
        if (level != null && level > 0f) {
            val arc = Size(mid * 2, mid * 2)
            drawArc(
                fill, START, SWEEP * level.coerceIn(0f, 1f), false, Offset(center.x - mid, center.y - mid), arc,
                style = Stroke(band, cap = StrokeCap.Butt),
            )
        }
        drawCircle(colors.borderStrong, outer - line / 2, center, style = Stroke(line))
        drawCircle(colors.borderStrong, outer - band + line / 2, center, style = Stroke(line))
        val hub = (outer - band) / 2
        drawCircle(colors.surface2, hub, center)
        drawCircle(colors.borderStrong, hub - line / 2, center, style = Stroke(line))
    }
}

/** The band is one eighth of the ring; the arc starts at 12 o'clock and runs clockwise. */
private const val RING_BAND = 8f
private const val START = -90f
private const val SWEEP = 360f
