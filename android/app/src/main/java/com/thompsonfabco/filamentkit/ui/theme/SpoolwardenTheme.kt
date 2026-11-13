package com.thompsonfabco.filamentkit.ui.theme

import androidx.compose.animation.core.Easing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit

// The token holders SpoolwardenTokens.kt (generated from tokens/tokens.json) fills. Resolved objects come with the theme composable.

internal enum class Look { Console, Workbench, Palette, Panes }

internal enum class NavStyle { Rail, Sidebar, Pills, List }

internal enum class CollectionStyle { Table, Cards, Tiles, Rows }

internal enum class DetailStyle { Inline, Card, Sheet, Pane }

/** A ring colour of an elevation level; one member per colour token, in the order of the colours below. */
internal enum class Ring {
    Bg, Surface, Surface2, Surface3, Text, Muted, Border, BorderStrong, Accent, AccentHover, OnAccent, AccentSoft,
    AccentText, Ok, OkSoft, Warn, WarnSoft, Bad, BadSoft, OnBad, Info, InfoSoft, Focus, Scrim, Code,
}

internal class SpoolwardenColors(
    val bg: Color, val surface: Color, val surface2: Color, val surface3: Color,
    val text: Color, val muted: Color, val border: Color, val borderStrong: Color,
    val accent: Color, val accentHover: Color, val onAccent: Color, val accentSoft: Color, val accentText: Color,
    val ok: Color, val okSoft: Color, val warn: Color, val warnSoft: Color,
    val bad: Color, val badSoft: Color, val onBad: Color, val info: Color, val infoSoft: Color,
    val focus: Color, val scrim: Color, val code: Color,
)

internal class SwTypeTokens(
    val sans: FontFamily, val mono: FontFamily,
    val xs: TextUnit, val s: TextUnit, val m: TextUnit, val b: TextUnit, val l: TextUnit, val xl: TextUnit, val xxl: TextUnit,
    val lineBody: Float, val lineTitle: Float, val weightText: Int, val weightLabel: Int, val weightTitle: Int,
)

internal class Spacing(
    val s1: Dp, val s2: Dp, val s3: Dp, val s4: Dp, val s5: Dp, val s6: Dp, val s7: Dp,
)

internal class SwSizes(
    val control: Dp, val controlPhone: Dp, val top: Dp, val rail: Dp, val tab: Dp, val row: Dp, val gap: Dp,
    val drawer: Dp, val hairline: Dp, val navMark: Dp, val thumb: Dp, val qr: Dp,
    val sideW: Dp, val listW: Dp, val contentMax: Dp,
    val labelCol: Dp, val thumbS: Dp, val swatchRowW: Dp, val swatchRowH: Dp, val swatchHead: Dp, val emptyMark: Dp,
    val chip: Dp, val slotLabel: Dp, val portField: Dp, val columnMax: Dp, val previewMax: Dp, val listPane: Dp,
)

internal class SwRadius(val rS: Dp, val r: Dp, val rL: Dp)

internal class SwShadow(val depth: Dp, val ring: Ring?)

internal class SwElevation(val e0: SwShadow, val e2: SwShadow)

internal class SwMotion(val fast: Int, val base: Int, val slow: Int, val easing: Easing) {
    companion object {
        /** Reduced motion: every duration 0. */
        val Off = SwMotion(fast = 0, base = 0, slow = 0, easing = LinearEasing)
    }
}

internal class LayoutProfile(val nav: NavStyle, val collection: CollectionStyle, val detail: DetailStyle)

internal class ThemeTokens(
    val light: SpoolwardenColors,
    val dark: SpoolwardenColors,
    val type: SwTypeTokens,
    val space: Spacing,
    val sizes: SwSizes,
    val radius: SwRadius,
    val elevationLight: SwElevation,
    val elevationDark: SwElevation,
    val motion: SwMotion,
    val profile: LayoutProfile,
)
