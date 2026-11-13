package com.thompsonfabco.filamentkit.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlin.math.PI

private val HEX = Regex("[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?")
private val RING = 1.dp
private const val EMPTY_DASHES = 8

/** The colour in `RRGGBB` or `RRGGBBAA`, with or without `#` (the alpha is ignored); null when there is none. */
internal fun swatchColor(hex: String?): Color? =
    hex?.trim()?.removePrefix("#")?.takeIf { HEX.matches(it) }?.let { Color(0xFF000000 or it.take(6).toLong(16)) }

internal sealed interface SwatchLook {
    /** Filament of this colour: a black ring around the fill. */
    data class Filled(val color: Color) : SwatchLook

    /** Filament whose colour is not known: the black ring around nothing. */
    data object NoColour : SwatchLook

    /** Nothing there: a dashed ring around nothing. */
    data object Empty : SwatchLook
}

internal fun swatchLook(hex: String?, empty: Boolean = false): SwatchLook =
    if (empty) SwatchLook.Empty else swatchColor(hex)?.let { SwatchLook.Filled(it) } ?: SwatchLook.NoColour

/** A black ring vanishes on a dark surface, so there it gets a lighter one around it. */
internal fun swatchNeedsHalo(surface: Color): Boolean = surface.luminance() < 0.5f

/**
 * Every filament colour in the app. The ring keeps white and light filament from looking like an empty slot; [empty]
 * draws a dashed ring instead, so that the ring does not make an empty slot look loaded.
 */
@Composable
internal fun ColorSwatch(hex: String?, size: Dp, modifier: Modifier = Modifier, empty: Boolean = false) {
    val look = swatchLook(hex, empty)
    val outline = MaterialTheme.colorScheme.outline
    val halo = swatchNeedsHalo(MaterialTheme.colorScheme.surface)
    Canvas(modifier.size(size)) {
        val ring = RING.toPx()
        val outer = this.size.minDimension / 2
        if (look == SwatchLook.Empty) {
            val radius = outer - ring / 2
            val dash = PI.toFloat() * radius / EMPTY_DASHES
            drawCircle(outline, radius, style = Stroke(ring, pathEffect = PathEffect.dashPathEffect(floatArrayOf(dash, dash))))
            return@Canvas
        }
        val blackRadius = (if (halo) outer - ring else outer) - ring / 2
        if (look is SwatchLook.Filled) drawCircle(look.color, blackRadius)
        if (halo) drawCircle(outline, outer - ring / 2, style = Stroke(ring))
        drawCircle(outline, blackRadius, style = Stroke(ring))
    }
}
