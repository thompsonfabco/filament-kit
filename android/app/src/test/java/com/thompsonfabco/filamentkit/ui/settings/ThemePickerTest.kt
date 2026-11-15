package com.thompsonfabco.filamentkit.ui.settings

import android.os.Build
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.isSelected
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.graphics.toPixelMap
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTokens
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertContentDescriptionEquals
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsNotSelected
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.CollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.DetailStyle
import com.thompsonfabco.filamentkit.ui.theme.LocalCollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.LocalDetailStyle
import com.thompsonfabco.filamentkit.ui.theme.LocalNavStyle
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.NavStyle
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** S6.3: the Theme group of Settings > Appearance (05-android-app 12.2). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class ThemePickerTest {
    @get:Rule val rule = createComposeRule()

    // the tile merges its words, so the name finds the radio; the chosen tile is one phrase (a11y_theme_tile)
    private fun tile(name: String) = hasText(name) or hasContentDescription("$name, ", substring = true)
    private val radio = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.RadioButton)

    @Test fun consoleIsTheChosenTileAndTheOtherThreeCanBeChosen() {
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) { ThemePicker(Look.Console, dark = false, onChoose = {}) }
        }
        rule.onNodeWithText("Theme").assertExists()
        rule.onNode(tile("Console") and radio).assertIsSelected().assertIsEnabled()
        rule.onNode(radio and isSelected()).assertContentDescriptionEquals("Console, Dense and technical, selected")
        rule.onNode(tile("Workbench") and radio).assertIsNotSelected().assertIsEnabled()
        rule.onNode(tile("Palette") and radio).assertIsNotSelected().assertIsEnabled()
        rule.onNode(tile("Panes") and radio).assertIsNotSelected().assertIsEnabled()
        assertEquals("every look is built", 0, rule.onAllNodesWithTextCount("Not available yet"))
    }

    @Test fun aLookNotInTheBuiltListShowsNotAvailableYetAndIsDisabled() {
        val three = listOf(Look.Console, Look.Workbench, Look.Palette)
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) { ThemePicker(Look.Console, dark = false, onChoose = {}, built = three) }
        }
        rule.onNode(tile("Panes") and radio).assertIsNotSelected().assertIsNotEnabled()
        assertEquals(1, rule.onAllNodesWithTextCount("Not available yet"))
    }

    @Test fun choosingThePanesTileAppliesItsProfileWithTheDefaultBuiltLooks() {
        var look by mutableStateOf(Look.Console)
        var seen: Triple<NavStyle, CollectionStyle, DetailStyle>? = null
        rule.setContent {
            SpoolwardenTheme(look, Appearance.Light) {
                seen = Triple(LocalNavStyle.current, LocalCollectionStyle.current, LocalDetailStyle.current)
                ThemePicker(look, dark = false, onChoose = { look = it })
            }
        }
        rule.onNode(tile("Panes") and radio).performClick()
        rule.waitForIdle()
        assertEquals(Look.Panes, look)
        assertEquals(Triple(NavStyle.List, CollectionStyle.Rows, DetailStyle.Pane), seen)
        rule.onNode(tile("Panes") and radio).assertIsSelected()
        rule.onNode(radio and isSelected()).assertContentDescriptionEquals("Panes, Simple lists, selected")
    }

    @Test fun choosingTheWorkbenchTileAppliesItsProfile() {
        var look by mutableStateOf(Look.Console)
        var navSeen: NavStyle? = null
        var collectionSeen: CollectionStyle? = null
        var detailSeen: DetailStyle? = null
        rule.setContent {
            SpoolwardenTheme(look, Appearance.Light) {
                navSeen = LocalNavStyle.current
                collectionSeen = LocalCollectionStyle.current
                detailSeen = LocalDetailStyle.current
                ThemePicker(look, dark = false, onChoose = { look = it })
            }
        }
        rule.onNode(tile("Workbench") and radio).performClick()
        rule.waitForIdle()
        assertEquals(Look.Workbench, look)
        assertEquals(Triple(NavStyle.Sidebar, CollectionStyle.Cards, DetailStyle.Card), Triple(navSeen, collectionSeen, detailSeen))
        rule.onNode(tile("Workbench") and radio).assertIsSelected()
    }

    @Test fun choosingThePaletteTileAppliesItsProfileWithTheDefaultBuiltLooks() {
        var look by mutableStateOf(Look.Console)
        var seen: Triple<NavStyle, CollectionStyle, DetailStyle>? = null
        rule.setContent {
            SpoolwardenTheme(look, Appearance.Light) {
                seen = Triple(LocalNavStyle.current, LocalCollectionStyle.current, LocalDetailStyle.current)
                ThemePicker(look, dark = false, onChoose = { look = it })
            }
        }
        rule.onNode(tile("Palette") and radio).performClick()
        rule.waitForIdle()
        assertEquals(Look.Palette, look)
        assertEquals(Triple(NavStyle.Pills, CollectionStyle.Tiles, DetailStyle.Sheet), seen)
        rule.onNode(tile("Palette") and radio).assertIsSelected()
        rule.onNode(radio and isSelected()).assertContentDescriptionEquals("Palette, Colourful and roomy, selected")
    }

    @Test fun choosingATileAppliesTheThemeAtOnceWithoutARestart() {
        var look by mutableStateOf(Look.Console)
        var navSeen: NavStyle? = null
        rule.setContent {
            SpoolwardenTheme(look, Appearance.Dark) {
                navSeen = LocalNavStyle.current
                ThemePicker(look, dark = true, onChoose = { look = it }, built = Look.entries)
            }
        }
        assertEquals(NavStyle.Rail, navSeen)
        rule.onNode(tile("Palette") and radio).assertIsNotSelected().performClick()
        rule.waitForIdle()
        assertEquals(Look.Palette, look)
        assertEquals("the profile locals follow the choice", NavStyle.Pills, navSeen)
        rule.onNode(tile("Palette") and radio).assertIsSelected()
        rule.onNode(tile("Console") and radio).assertIsNotSelected()
    }

    @Test fun aTileNotBuiltCannotBeChosen() {
        var chosen: Look? = null
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) {
                ThemePicker(Look.Console, dark = false, onChoose = { chosen = it }, built = listOf(Look.Console, Look.Workbench, Look.Palette))
            }
        }
        rule.onNode(tile("Panes") and radio).performClick()
        rule.waitForIdle()
        assertEquals(null, chosen)
    }

    @Test fun theGridIsTwoByTwoUnlessTheWindowIsExpanded() {
        assertEquals(2, themeColumns(com.thompsonfabco.filamentkit.ui.theme.WindowClass.Phone))
        assertEquals(2, themeColumns(com.thompsonfabco.filamentkit.ui.theme.WindowClass.Tablet))
        assertEquals(4, themeColumns(com.thompsonfabco.filamentkit.ui.theme.WindowClass.Desktop))
    }

    @Test fun theCheckMarkIsInTheTopRightCornerOfTheChosenTile() {
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) { ThemePicker(Look.Console, dark = false, onChoose = {}) }
        }
        val tile = rule.onNode(radio and isSelected()).fetchSemanticsNode().boundsInRoot
        val mark = rule.onNode(hasTestTag("theme-tile-mark") and hasAnyAncestor(radio and isSelected()), useUnmergedTree = true)
            .fetchSemanticsNode().boundsInRoot
        assertTrue("right of the tile's middle", mark.left > tile.center.x)
        assertTrue("in the top part of the tile", mark.bottom < tile.top + tile.height / 3)
        assertTrue("inside the tile", mark.right <= tile.right && mark.top >= tile.top)
    }

    @Test fun theNameWrapsAtLargeFontSizesAndIsNeverCut() {
        var overflowed: Boolean? = null
        rule.setContent {
            val d = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(d.density, fontScale = 2f)) {
                SpoolwardenTheme(Look.Console, Appearance.Light) {
                    // a narrow room: two tiles of about 90 dp
                    Box(Modifier.width(200.dp)) { ThemePicker(Look.Console, dark = false, onChoose = {}, built = Look.entries) }
                }
            }
        }
        rule.waitForIdle()
        val texts = rule.onAllNodes(hasText("Workbench"), useUnmergedTree = true).fetchSemanticsNodes()
        assertEquals(1, texts.size)
        val results = mutableListOf<androidx.compose.ui.text.TextLayoutResult>()
        texts.single().config[SemanticsActions.GetTextLayoutResult].action?.invoke(results)
        overflowed = results.first().hasVisualOverflow
        assertEquals("the name is not cut", false, overflowed)
        assertEquals("the name is shown in full", "Workbench", results.first().layoutInput.text.text)
    }

    @Test fun theMiniatureUsesNoAccentFill() {
        var shown by mutableStateOf(Look.Console to false)
        rule.setContent {
            val (look, dark) = shown
            val tokens = SpoolwardenTokens.of(look)
            SpoolwardenTheme(look, Appearance.Light) {
                LookPreview(tokens, if (dark) tokens.dark else tokens.light, Modifier.size(240.dp, 180.dp).testTag("preview"))
            }
        }
        for (dark in listOf(false, true)) {
            for (look in Look.entries) {
                shown = look to dark
                rule.waitForIdle()
                val tokens = SpoolwardenTokens.of(look)
                val colors = if (dark) tokens.dark else tokens.light
                val accent = colors.accent
                if (accent == colors.accentText) continue // the look's accent text is its accent: nothing to tell apart
                val image = rule.onNodeWithTag("preview").captureToImage().toPixelMap()
                var hits = 0
                for (x in 0 until image.width) for (y in 0 until image.height) if (image[x, y] == accent) hits++
                assertEquals("$look dark=$dark: pixels in the accent colour", 0, hits)
            }
        }
    }

    private fun androidx.compose.ui.test.junit4.ComposeContentTestRule.onAllNodesWithTextCount(text: String) =
        onAllNodes(hasText(text)).fetchSemanticsNodes().size
}
