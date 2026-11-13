package com.thompsonfabco.filamentkit.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.addOutline
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

private val HEX = Regex("[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?")

/** The colour in `RRGGBB` or `RRGGBBAA`, with or without `#` (the alpha is ignored); null when there is none. */
internal fun swatchColor(hex: String?): Color? =
    hex?.trim()?.removePrefix("#")?.takeIf { HEX.matches(it) }?.let { Color(0xFF000000 or it.take(6).toLong(16)) }

internal sealed interface SwatchLook {
    /** Filament of this colour: a 1 dp outline around the fill. */
    data class Filled(val color: Color) : SwatchLook

    /** Filament whose colour is not known: the outline around nothing. */
    data object NoColour : SwatchLook

    /** Nothing there: a dashed ring around nothing. */
    data object Empty : SwatchLook
}

internal fun swatchLook(hex: String?, empty: Boolean = false): SwatchLook =
    if (empty) SwatchLook.Empty else swatchColor(hex)?.let { SwatchLook.Filled(it) } ?: SwatchLook.NoColour

/**
 * Every filament colour in the app (05-android-app 3.1, "Swatch"): a rectangle of `swatchRowW` by `swatchRowH` in
 * rows, or the `swatchHead` square of a spool's header when [head], with `rS` corners and a 1 dp `borderStrong`
 * outline that keeps white and light filament from looking like an empty slot. When there is no fill to draw (no
 * [empty] slot or no colour known) it is a dashed `borderStrong` outline with no fill.
 */
@Composable
internal fun ColorSwatch(hex: String?, modifier: Modifier = Modifier, head: Boolean = false, empty: Boolean = false) {
    val look = swatchLook(hex, empty)
    val outline = SpoolwardenTheme.colors.borderStrong
    val sizes = SpoolwardenTheme.sizes
    val shape = SpoolwardenTheme.shapes.rS
    val dashLength = SpoolwardenTheme.space.s1
    val box = if (head) Modifier.size(sizes.swatchHead) else Modifier.size(sizes.swatchRowW, sizes.swatchRowH)
    Canvas(modifier.then(box)) {
        val ring = sizes.hairline.toPx()
        // the stroke is centred on the path, so the path is inset by half of it: the whole 1 dp outline is inside the box
        val inset = Size(this.size.width - ring, this.size.height - ring)
        val path = Path().apply {
            addOutline(shape.createOutline(inset, layoutDirection, this@Canvas))
            translate(Offset(ring / 2, ring / 2))
        }
        if (look is SwatchLook.Filled) {
            drawPath(path, look.color)
            drawPath(path, outline, style = Stroke(ring))
        } else {
            val dash = dashLength.toPx()
            drawPath(path, outline, style = Stroke(ring, pathEffect = PathEffect.dashPathEffect(floatArrayOf(dash, dash))))
        }
    }
}
