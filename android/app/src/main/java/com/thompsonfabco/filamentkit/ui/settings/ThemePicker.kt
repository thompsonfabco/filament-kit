package com.thompsonfabco.filamentkit.ui.settings

import androidx.annotation.StringRes
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwIconSize
import com.thompsonfabco.filamentkit.ui.theme.BUILT_LOOKS
import com.thompsonfabco.filamentkit.ui.theme.CollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.NavStyle
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenColors
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTokens
import com.thompsonfabco.filamentkit.ui.theme.ThemeTokens
import com.thompsonfabco.filamentkit.ui.theme.WindowClass

@get:StringRes
internal val Look.nameRes: Int
    get() = when (this) {
        Look.Console -> R.string.theme_console_name
        Look.Workbench -> R.string.theme_workbench_name
        Look.Palette -> R.string.theme_palette_name
        Look.Panes -> R.string.theme_panes_name
    }

@get:StringRes
internal val Look.lineRes: Int
    get() = when (this) {
        Look.Console -> R.string.theme_console_line
        Look.Workbench -> R.string.theme_workbench_line
        Look.Palette -> R.string.theme_palette_line
        Look.Panes -> R.string.theme_panes_line
    }

/** Tiles in a row: a 2 x 2 grid on compact and medium width, one row of four on expanded width (05-android-app 12.2). */
internal fun themeColumns(window: WindowClass): Int = if (window == WindowClass.Desktop) Look.entries.size else 2

/**
 * The Theme group of 05-android-app 12.2 (02-components 3.4): a radio group of tiles, each a small drawing of the theme
 * in its own colours (in the appearance now in use, [dark]), its name and its line. The chosen tile has the 2 dp
 * `accentText` outline and a check mark; a theme not built yet shows a hollow circle and "Not available yet" and
 * cannot be chosen. Choosing applies at once, with no save button.
 */
@Composable
internal fun ThemePicker(
    selected: Look, dark: Boolean, onChoose: (Look) -> Unit,
    modifier: Modifier = Modifier, built: List<Look> = BUILT_LOOKS,
) {
    val gap = SpoolwardenTheme.space.s3
    Column(modifier.selectableGroup(), verticalArrangement = Arrangement.spacedBy(gap)) {
        GroupTitle(stringResource(R.string.appearance_theme_title))
        Look.entries.chunked(themeColumns(SpoolwardenTheme.window)).forEach { rowLooks ->
            Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(gap)) {
                rowLooks.forEach { look ->
                    ThemeTile(
                        look, selected = look == selected, enabled = look in built, dark = dark,
                        onClick = { onChoose(look) }, modifier = Modifier.weight(1f).fillMaxHeight(),
                    )
                }
                // a short last row keeps the tiles the width of the others
                repeat(themeColumns(SpoolwardenTheme.window) - rowLooks.size) { Box(Modifier.weight(1f)) }
            }
        }
    }
}

@Composable
private fun ThemeTile(look: Look, selected: Boolean, enabled: Boolean, dark: Boolean, onClick: () -> Unit, modifier: Modifier) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val shape = SpoolwardenTheme.shapes.r
    val outline = if (selected) 2.dp else SpoolwardenTheme.sizes.hairline
    val said = if (selected) stringResource(R.string.a11y_theme_tile, stringResource(look.nameRes), stringResource(look.lineRes)) else null
    val mark = space.s4
    Box(
        modifier
            .clip(shape)
            .background(if (selected) colors.accentSoft else colors.surface)
            .border(outline, if (selected) colors.accentText else colors.borderStrong, shape)
            .selectable(selected = selected, enabled = enabled, role = Role.RadioButton, onClick = onClick)
            // the chosen tile is read as one phrase; the others read their own words
            .then(if (said != null) Modifier.clearAndSetSemantics { contentDescription = said } else Modifier)
            .padding(space.s3),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
            if (enabled) {
                val tokens = SpoolwardenTokens.of(look)
                LookPreview(tokens, if (dark) tokens.dark else tokens.light, Modifier.fillMaxWidth().aspectRatio(4f / 3f))
            }
            // the name wraps at a large font size, it is never cut; with no preview the mark sits beside it
            Text(
                stringResource(look.nameRes), Modifier.fillMaxWidth().padding(end = if (enabled) 0.dp else mark + space.s2),
                color = if (enabled) colors.text else colors.muted, style = MaterialTheme.typography.titleSmall,
            )
            Text(
                stringResource(if (enabled) look.lineRes else R.string.theme_unavailable_line),
                color = colors.muted, style = MaterialTheme.typography.bodySmall,
            )
        }
        // the check mark of the chosen tile, or the hollow circle of one not built, in the top right corner
        Box(Modifier.align(Alignment.TopEnd).testTag("theme-tile-mark")) {
            when {
                selected -> SwIcon(
                    R.drawable.sw_ic_check, null, size = SwIconSize.Small, tint = colors.accentText,
                    modifier = Modifier.background(colors.accentSoft, CircleShape),
                )
                !enabled -> Box(Modifier.size(mark).border(SpoolwardenTheme.sizes.hairline, colors.borderStrong, CircleShape))
            }
        }
    }
}

/**
 * A miniature of the shell in [tokens]' own [colors]: the bar, the navigation form of its `nav` profile and the
 * collection form of its `collection` profile. Decoration only; the tile's words carry the meaning.
 */
@Composable
internal fun LookPreview(tokens: ThemeTokens, colors: SpoolwardenColors, modifier: Modifier) {
    val rS = tokens.radius.rS
    val hairline = SpoolwardenTheme.sizes.hairline
    Canvas(modifier.clip(RoundedCornerShape(rS)).border(hairline, colors.border, RoundedCornerShape(rS))) {
        drawLookPreview(tokens, colors, rS)
    }
}

private fun DrawScope.drawLookPreview(tokens: ThemeTokens, c: SpoolwardenColors, rS: Dp) {
    val w = size.width
    val h = size.height
    val r = rS.toPx()
    val line = 1.dp.toPx()
    fun block(x: Float, y: Float, bw: Float, bh: Float, color: Color, outline: Color? = null) {
        drawRoundRect(color, Offset(x, y), Size(bw, bh), CornerRadius(r))
        if (outline != null) drawRoundRect(outline, Offset(x, y), Size(bw, bh), CornerRadius(r), style = Stroke(line))
    }
    drawRect(c.bg)
    // the bar: a mark of the app and a few controls
    val bar = h * 0.14f
    drawRect(c.surface, Offset.Zero, Size(w, bar))
    drawRect(c.border, Offset(0f, bar - line), Size(w, line))
    block(w * 0.04f, bar * 0.3f, w * 0.12f, bar * 0.4f, c.accentText)
    block(w * 0.8f, bar * 0.3f, w * 0.16f, bar * 0.4f, c.surface3)

    // the navigation form
    var left = 0f
    var top = bar
    when (tokens.profile.nav) {
        NavStyle.Rail, NavStyle.Sidebar -> {
            val side = if (tokens.profile.nav == NavStyle.Rail) w * 0.12f else w * 0.24f
            drawRect(c.surface, Offset(0f, bar), Size(side, h - bar))
            drawRect(c.border, Offset(side - line, bar), Size(line, h - bar))
            repeat(3) { i ->
                block(side * 0.18f, bar + h * (0.06f + 0.1f * i), side * 0.64f, h * 0.06f, if (i == 0) c.accentSoft else c.surface3)
            }
            left = side
        }
        NavStyle.Pills -> {
            repeat(3) { i ->
                block(w * (0.05f + 0.2f * i), bar + h * 0.04f, w * 0.17f, h * 0.07f, if (i == 0) c.accentSoft else c.surface3)
            }
            top = bar + h * 0.15f
        }
        NavStyle.List -> Unit
    }

    // the collection form, in the room that is left
    val x = left + w * 0.04f
    val y = top + h * 0.05f
    val room = w - x - w * 0.04f
    val tall = h - y - h * 0.05f
    when (tokens.profile.collection) {
        CollectionStyle.Table -> repeat(4) { i ->
            val ry = y + tall * 0.25f * i
            drawRect(if (i == 0) c.surface3 else c.surface, Offset(x, ry), Size(room, tall * 0.2f))
            drawRect(c.border, Offset(x, ry + tall * 0.2f - line), Size(room, line))
            block(x + room * 0.05f, ry + tall * 0.07f, room * 0.3f, tall * 0.07f, c.muted)
        }
        CollectionStyle.Cards, CollectionStyle.Tiles -> {
            val tiles = tokens.profile.collection == CollectionStyle.Tiles
            repeat(4) { i ->
                val cx = x + (room * 0.52f) * (i % 2)
                val cy = y + (tall * 0.52f) * (i / 2)
                block(cx, cy, room * 0.48f, tall * 0.46f, c.surface, c.border)
                block(cx + room * 0.04f, cy + tall * 0.06f, room * 0.2f, tall * 0.1f, if (tiles) c.accentSoft else c.muted)
            }
        }
        CollectionStyle.Rows -> repeat(4) { i ->
            val ry = y + tall * 0.25f * i
            drawRect(c.border, Offset(x, ry + tall * 0.2f), Size(room, line))
            drawCircle(c.accentText, tall * 0.05f, Offset(x + room * 0.04f, ry + tall * 0.1f))
            block(x + room * 0.12f, ry + tall * 0.07f, room * 0.4f, tall * 0.07f, c.muted)
        }
    }
}
