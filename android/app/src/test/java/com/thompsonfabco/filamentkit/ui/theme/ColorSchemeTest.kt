package com.thompsonfabco.filamentkit.ui.theme

import androidx.compose.material3.ColorScheme
import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The Material scheme built from a theme holds only that theme's own colours: no Material baseline colour is left. */
class ColorSchemeTest {
    private fun roles(s: ColorScheme): Map<String, Color> = mapOf(
        "primary" to s.primary, "onPrimary" to s.onPrimary,
        "primaryContainer" to s.primaryContainer, "onPrimaryContainer" to s.onPrimaryContainer,
        "secondary" to s.secondary, "onSecondary" to s.onSecondary,
        "secondaryContainer" to s.secondaryContainer, "onSecondaryContainer" to s.onSecondaryContainer,
        "tertiary" to s.tertiary, "onTertiary" to s.onTertiary,
        "tertiaryContainer" to s.tertiaryContainer, "onTertiaryContainer" to s.onTertiaryContainer,
        "background" to s.background, "onBackground" to s.onBackground,
        "surface" to s.surface, "onSurface" to s.onSurface,
        "surfaceVariant" to s.surfaceVariant, "onSurfaceVariant" to s.onSurfaceVariant,
        "surfaceTint" to s.surfaceTint, "inverseSurface" to s.inverseSurface, "inverseOnSurface" to s.inverseOnSurface,
        "error" to s.error, "onError" to s.onError, "errorContainer" to s.errorContainer,
        "onErrorContainer" to s.onErrorContainer,
        "outline" to s.outline, "outlineVariant" to s.outlineVariant,
        "surfaceBright" to s.surfaceBright, "surfaceDim" to s.surfaceDim,
        "surfaceContainerLowest" to s.surfaceContainerLowest, "surfaceContainerLow" to s.surfaceContainerLow,
        "surfaceContainer" to s.surfaceContainer, "surfaceContainerHigh" to s.surfaceContainerHigh,
        "surfaceContainerHighest" to s.surfaceContainerHighest,
        "primaryFixed" to s.primaryFixed, "primaryFixedDim" to s.primaryFixedDim,
        "onPrimaryFixed" to s.onPrimaryFixed, "onPrimaryFixedVariant" to s.onPrimaryFixedVariant,
        "secondaryFixed" to s.secondaryFixed, "secondaryFixedDim" to s.secondaryFixedDim,
        "onSecondaryFixed" to s.onSecondaryFixed, "onSecondaryFixedVariant" to s.onSecondaryFixedVariant,
        "tertiaryFixed" to s.tertiaryFixed, "tertiaryFixedDim" to s.tertiaryFixedDim,
        "onTertiaryFixed" to s.onTertiaryFixed, "onTertiaryFixedVariant" to s.onTertiaryFixedVariant,
    )

    private fun values(c: SpoolwardenColors): Set<Color> = setOf(
        c.bg, c.surface, c.surface2, c.surface3, c.text, c.muted, c.border, c.borderStrong,
        c.accent, c.accentHover, c.onAccent, c.accentSoft, c.accentText, c.ok, c.okSoft, c.warn, c.warnSoft,
        c.bad, c.badSoft, c.onBad, c.info, c.infoSoft, c.focus, c.scrim, c.code,
    )

    @Test fun selectionUsesAccentTextAndAccentSoft() {
        for (look in Look.entries) for ((dark, c) in listOf(false to SpoolwardenTokens.of(look).light, true to SpoolwardenTokens.of(look).dark)) {
            val sel = c.toSelectionColors()
            assertEquals("$look dark=$dark: handle", c.accentText, sel.handleColor)
            assertEquals("$look dark=$dark: background", c.accentSoft, sel.backgroundColor)
        }
    }

    @Test fun appearanceResolvesToDarkOrLight() {
        assertEquals(false, resolveDark(Appearance.Light, systemDark = true))
        assertEquals(true, resolveDark(Appearance.Dark, systemDark = false))
        assertEquals(true, resolveDark(Appearance.System, systemDark = true))
        assertEquals(false, resolveDark(Appearance.System, systemDark = false))
    }

    @Test fun everyRoleIsAColourOfTheTheme() {
        for (look in Look.entries) {
            val t = SpoolwardenTokens.of(look)
            for ((name, c, other) in listOf(Triple("light", t.light, t.dark), Triple("dark", t.dark, t.light))) {
                val scheme = c.toColorScheme(inversePrimary = other.accentText)
                val allowed = values(c)
                for ((role, colour) in roles(scheme)) {
                    if (role == "scrim") continue
                    assertTrue("$look $name: $role is not a colour of the theme", colour in allowed)
                }
                assertTrue("$look $name: inversePrimary is not the other appearance's accentText",
                    scheme.inversePrimary == other.accentText)
                assertEquals("$look $name: scrim", c.scrim.copy(alpha = 1f), scheme.scrim)
                assertEquals("$look $name: primary", c.accentText, scheme.primary)
                assertEquals("$look $name: onPrimary", c.surface, scheme.onPrimary)
            }
        }
    }
}
