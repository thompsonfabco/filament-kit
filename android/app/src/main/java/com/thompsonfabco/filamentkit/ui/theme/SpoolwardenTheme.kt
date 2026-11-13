package com.thompsonfabco.filamentkit.ui.theme

import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.compose.animation.core.Easing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.LocalTextSelectionColors
import androidx.compose.foundation.text.selection.TextSelectionColors
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.adaptive.currentWindowAdaptiveInfoV2
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.em
import androidx.window.core.layout.WindowSizeClass

// The token holders SpoolwardenTokens.kt (generated from tokens/tokens.json) fills, and the theme composable that resolves them.
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

/** The person's choice of light or dark; the settings store holds it as text (see `Settings`). */
enum class Appearance { Light, Dark, System }

/** Phone is a compact window (below 600 dp), Tablet a medium one (600 to 839 dp), Desktop anything wider. */
internal enum class WindowClass { Phone, Tablet, Desktop }

private val NO_FONT_PADDING = PlatformTextStyle(includeFontPadding = false)
private val LINE_STYLE = LineHeightStyle(LineHeightStyle.Alignment.Center, LineHeightStyle.Trim.None)

/** The text styles Material has no role for; [input] depends on the window class. */
internal class SwType(private val tokens: SwTypeTokens, window: WindowClass) {
    private fun mono(size: TextUnit, weight: Int, line: Float) = TextStyle(
        fontFamily = tokens.mono, fontSize = size, fontWeight = FontWeight(weight), lineHeight = line.em,
        fontFeatureSettings = "tnum", platformStyle = NO_FONT_PADDING, lineHeightStyle = LINE_STYLE,
    )

    val data = mono(tokens.m, tokens.weightText, tokens.lineBody)
    val dataSmall = mono(tokens.s, tokens.weightText, tokens.lineBody)
    val number = mono(tokens.xxl, tokens.weightTitle, tokens.lineTitle)
    val tableHeader = TextStyle(
        fontFamily = tokens.sans, fontSize = tokens.xs, fontWeight = FontWeight(tokens.weightTitle),
        lineHeight = tokens.lineTitle.em, letterSpacing = 0.05.em,
        platformStyle = NO_FONT_PADDING, lineHeightStyle = LINE_STYLE,
    )
    val input = TextStyle(
        fontFamily = tokens.sans, fontSize = if (window == WindowClass.Phone) tokens.l else tokens.b,
        fontWeight = FontWeight(tokens.weightText), lineHeight = tokens.lineBody.em,
        platformStyle = NO_FONT_PADDING, lineHeightStyle = LINE_STYLE,
    )
}

/** Control height, row and gap of the theme; [control] is the phone height on a Phone window. */
internal class SwDensity(sizes: SwSizes, window: WindowClass) {
    val control: Dp = if (window == WindowClass.Phone) sizes.controlPhone else sizes.control
    val row: Dp = sizes.row
    val gap: Dp = sizes.gap
}

internal class SwShapes(radius: SwRadius) {
    val rS = RoundedCornerShape(radius.rS)
    val r = RoundedCornerShape(radius.r)
    val rL = RoundedCornerShape(radius.rL)
}

internal val LocalSpoolwardenColors = staticCompositionLocalOf<SpoolwardenColors> { throw IllegalStateException() }
internal val LocalSwType = staticCompositionLocalOf<SwType> { throw IllegalStateException() }
internal val LocalSpacing = staticCompositionLocalOf<Spacing> { throw IllegalStateException() }
internal val LocalSwSizes = staticCompositionLocalOf<SwSizes> { throw IllegalStateException() }
internal val LocalSwDensity = staticCompositionLocalOf<SwDensity> { throw IllegalStateException() }
internal val LocalSwShapes = staticCompositionLocalOf<SwShapes> { throw IllegalStateException() }
internal val LocalSwElevation = staticCompositionLocalOf<SwElevation> { throw IllegalStateException() }
internal val LocalSwMotion = staticCompositionLocalOf<SwMotion> { throw IllegalStateException() }
internal val LocalWindowClass = staticCompositionLocalOf<WindowClass> { throw IllegalStateException() }
internal val LocalNavStyle = staticCompositionLocalOf<NavStyle> { throw IllegalStateException() }
internal val LocalCollectionStyle = staticCompositionLocalOf<CollectionStyle> { throw IllegalStateException() }
internal val LocalDetailStyle = staticCompositionLocalOf<DetailStyle> { throw IllegalStateException() }

/** The resolved theme, read by every Spoolwarden composable. */
internal object SpoolwardenTheme {
    val colors: SpoolwardenColors @Composable @ReadOnlyComposable get() = LocalSpoolwardenColors.current
    val type: SwType @Composable @ReadOnlyComposable get() = LocalSwType.current
    val space: Spacing @Composable @ReadOnlyComposable get() = LocalSpacing.current
    val sizes: SwSizes @Composable @ReadOnlyComposable get() = LocalSwSizes.current
    val density: SwDensity @Composable @ReadOnlyComposable get() = LocalSwDensity.current
    val shapes: SwShapes @Composable @ReadOnlyComposable get() = LocalSwShapes.current
    val elevation: SwElevation @Composable @ReadOnlyComposable get() = LocalSwElevation.current
    val motion: SwMotion @Composable @ReadOnlyComposable get() = LocalSwMotion.current
    val window: WindowClass @Composable @ReadOnlyComposable get() = LocalWindowClass.current
}

/** True when [appearance] resolves to dark; System follows the phone. */
@Composable
internal fun isDark(appearance: Appearance): Boolean = resolveDark(appearance, isSystemInDarkTheme())

internal fun resolveDark(appearance: Appearance, systemDark: Boolean): Boolean = when (appearance) {
    Appearance.Light -> false
    Appearance.Dark -> true
    Appearance.System -> systemDark
}

@Composable
internal fun SpoolwardenTheme(look: Look, appearance: Appearance, content: @Composable () -> Unit) {
    val t = SpoolwardenTokens.of(look)
    val dark = isDark(appearance)
    val colors = if (dark) t.dark else t.light
    val other = if (dark) t.light else t.dark
    val window = rememberWindowClass()
    val reduceMotion = rememberReduceMotion()

    CompositionLocalProvider(
        LocalSpoolwardenColors provides colors,
        LocalSwType provides SwType(t.type, window),
        LocalSpacing provides t.space,
        LocalSwSizes provides t.sizes,
        LocalSwDensity provides SwDensity(t.sizes, window),
        LocalSwShapes provides SwShapes(t.radius),
        LocalSwElevation provides if (dark) t.elevationDark else t.elevationLight,
        LocalSwMotion provides if (reduceMotion) SwMotion.Off else t.motion,
        LocalWindowClass provides window,
        LocalNavStyle provides t.profile.nav,
        LocalCollectionStyle provides t.profile.collection,
        LocalDetailStyle provides t.profile.detail,
    ) {
        MaterialTheme(
            colorScheme = colors.toColorScheme(inversePrimary = other.accentText),
            typography = t.type.toTypography(),
            shapes = t.radius.toShapes(),
        ) {
            CompositionLocalProvider(
                LocalContentColor provides colors.text,
                LocalTextSelectionColors provides TextSelectionColors(colors.accent, colors.accentSoft),
                content = content,
            )
        }
    }
}

/** The window's class, from its own width (so split screen and freeform windows get the layout their width calls for). */
@Composable
private fun rememberWindowClass(): WindowClass {
    val sizeClass = currentWindowAdaptiveInfoV2().windowSizeClass
    return when {
        sizeClass.isWidthAtLeastBreakpoint(WindowSizeClass.WIDTH_DP_EXPANDED_LOWER_BOUND) -> WindowClass.Desktop
        sizeClass.isWidthAtLeastBreakpoint(WindowSizeClass.WIDTH_DP_MEDIUM_LOWER_BOUND) -> WindowClass.Tablet
        else -> WindowClass.Phone
    }
}

/** True while the system setting "Remove animations" is on (animator duration scale 0). */
@Composable
private fun rememberReduceMotion(): Boolean {
    val resolver = LocalContext.current.contentResolver
    fun read() = Settings.Global.getFloat(resolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    var reduce by remember { mutableStateOf(read()) }
    DisposableEffect(resolver) {
        val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) { reduce = read() }
        }
        resolver.registerContentObserver(Settings.Global.getUriFor(Settings.Global.ANIMATOR_DURATION_SCALE), false, observer)
        onDispose { resolver.unregisterContentObserver(observer) }
    }
    return reduce
}

/**
 * Every role of the Material scheme, set from the theme's own colours (08-platform-mapping 4.1), so no Material
 * baseline colour is left. The scrim keeps its colour at full opacity.
 */
internal fun SpoolwardenColors.toColorScheme(inversePrimary: Color) = ColorScheme(
    primary = accentText, onPrimary = surface, primaryContainer = accentSoft, onPrimaryContainer = accentText,
    inversePrimary = inversePrimary,
    secondary = accentText, onSecondary = surface, secondaryContainer = accentSoft, onSecondaryContainer = accentText,
    tertiary = accentText, onTertiary = surface, tertiaryContainer = accentSoft, onTertiaryContainer = accentText,
    background = bg, onBackground = text,
    surface = surface, onSurface = text, surfaceVariant = surface2, onSurfaceVariant = muted,
    surfaceTint = surface, inverseSurface = text, inverseOnSurface = surface,
    error = bad, onError = onBad, errorContainer = badSoft, onErrorContainer = bad,
    outline = borderStrong, outlineVariant = border, scrim = scrim.copy(alpha = 1f),
    surfaceBright = surface, surfaceDim = bg,
    surfaceContainerLowest = surface, surfaceContainerLow = surface, surfaceContainer = surface,
    surfaceContainerHigh = surface, surfaceContainerHighest = surface2,
    primaryFixed = accentSoft, primaryFixedDim = accentSoft, onPrimaryFixed = accentText, onPrimaryFixedVariant = accentText,
    secondaryFixed = accentSoft, secondaryFixedDim = accentSoft, onSecondaryFixed = accentText, onSecondaryFixedVariant = accentText,
    tertiaryFixed = accentSoft, tertiaryFixedDim = accentSoft, onTertiaryFixed = accentText, onTertiaryFixedVariant = accentText,
)

/** One style per Material role (08-platform-mapping 5.1); the larger display and headline roles repeat the 2xl style. */
internal fun SwTypeTokens.toTypography(): Typography {
    fun style(size: TextUnit, weight: Int, line: Float) = TextStyle(
        fontFamily = sans, fontSize = size, fontWeight = FontWeight(weight), lineHeight = line.em,
        platformStyle = NO_FONT_PADDING, lineHeightStyle = LINE_STYLE,
    )
    val big = style(xxl, weightTitle, lineTitle)
    return Typography(
        displayLarge = big, displayMedium = big, displaySmall = big,
        headlineLarge = big, headlineMedium = big, headlineSmall = big,
        titleLarge = style(xl, weightTitle, lineTitle),
        titleMedium = style(l, weightTitle, lineTitle),
        titleSmall = style(b, weightTitle, lineTitle),
        bodyLarge = style(b, weightText, lineBody),
        bodyMedium = style(m, weightText, lineBody),
        bodySmall = style(s, weightText, lineBody),
        labelLarge = style(m, weightLabel, lineTitle),
        labelMedium = style(s, weightLabel, lineTitle),
        labelSmall = style(xs, weightLabel, lineTitle),
    )
}

internal fun SwRadius.toShapes() = Shapes(
    extraSmall = RoundedCornerShape(rS), small = RoundedCornerShape(r), medium = RoundedCornerShape(r),
    large = RoundedCornerShape(rL), extraLarge = RoundedCornerShape(rL),
)
