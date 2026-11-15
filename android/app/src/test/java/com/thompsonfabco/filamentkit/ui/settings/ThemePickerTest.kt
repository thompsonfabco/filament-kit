package com.thompsonfabco.filamentkit.ui.settings

import android.os.Build
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsNotSelected
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.LocalNavStyle
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.NavStyle
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** S6.3: the Theme group of Settings > Appearance (05-android-app 12.2). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class ThemePickerTest {
    @get:Rule val rule = createComposeRule()

    private fun tile(name: String) = hasText(name) // the tile merges its words, so the name finds the radio
    private val radio = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.RadioButton)

    @Test fun consoleIsTheChosenTileAndTheOthersAreNotBuiltYet() {
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) { ThemePicker(Look.Console, dark = false, onChoose = {}) }
        }
        rule.onNodeWithText("Theme").assertExists()
        rule.onNode(tile("Console") and radio).assertIsSelected().assertIsEnabled()
        rule.onNodeWithText("Dense and technical").assertExists()
        for (other in listOf("Workbench", "Palette", "Panes")) {
            rule.onNode(tile(other) and radio).assertIsNotSelected().assertIsNotEnabled()
        }
        assertEquals(3, rule.onAllNodesWithTextCount("Not available yet"))
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
            SpoolwardenTheme(Look.Console, Appearance.Light) { ThemePicker(Look.Console, dark = false, onChoose = { chosen = it }) }
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

    private fun androidx.compose.ui.test.junit4.ComposeContentTestRule.onAllNodesWithTextCount(text: String) =
        onAllNodes(hasText(text)).fetchSemanticsNodes().size
}
