package com.thompsonfabco.filamentkit.ui

import android.os.Build
import androidx.activity.ComponentActivity
import androidx.compose.material3.Text
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.ui.input.InputMode
import androidx.compose.ui.platform.LocalInputModeManager
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertIsFocused
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.input.InputModeManager
import com.thompsonfabco.filamentkit.FilamentKitApp
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.session.AppViewModel
import com.thompsonfabco.filamentkit.ui.components.HubNoticeKind
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.LocalTopBarActions
import com.thompsonfabco.filamentkit.ui.components.SECTION_ROW_TAG
import com.thompsonfabco.filamentkit.ui.components.ScreenTopBarActions
import com.thompsonfabco.filamentkit.ui.components.SwToastState
import com.thompsonfabco.filamentkit.ui.components.TopBarActions
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * S6.9 rework: the whole shell ([FilamentKitApp]) in Panes at phone width. The list page is the only page (the screens under it
 * are out of reach and only the list's own top-bar actions show), a section opens with its Back arrow, and Back goes to the
 * list and then to the system. A screen's own top-bar action stands in for the Printers overflow (which needs a paired Hub).
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h800dp")
class PanesShellTest {
    @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

    private val actions = TopBarActions()
    private val toast = SwToastState()
    private var inputMode: InputModeManager? = null

    private fun text(id: Int) = RuntimeEnvironment.getApplication().getString(id)
    private fun rowOf(tab: Tab) = rule.onNode(hasText(text(tab.label)) and SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Tab))
    private val screenAction = "a screen's action"
    private val screenText get() = text(HubNoticeKind.NoLongerPaired.text)

    private fun shell() = rule.setContent {
        val app = remember { AppViewModel(RuntimeEnvironment.getApplication()) }
        inputMode = LocalInputModeManager.current
        SpoolwardenTheme(Look.Panes, Appearance.Light) {
            CompositionLocalProvider(LocalToast provides toast, LocalTopBarActions provides actions) {
                FilamentKitApp(app, true, Appearance.Light, Look.Panes, toast, actions)
                // what the Printers screen puts in the top bar, from a screen that is composed under the list
                ScreenTopBarActions { Text(screenAction) }
            }
        }
    }

    private fun pressBack() {
        rule.runOnUiThread { rule.activity.onBackPressedDispatcher.onBackPressed() }
        rule.waitForIdle()
    }

    private fun listIsThePage() {
        for (tab in Tab.entries) rowOf(tab).assertExists()
        rule.onNodeWithText(text(R.string.nav_label)).assertExists()
    }

    @Test fun thePhoneOpensOnTheListAloneNoScreenOrScreenActionUnderIt() {
        shell()
        rule.waitForIdle()
        listIsThePage()
        assertEquals("the screen under the list is out of reach of readers", 0, rule.onAllNodesWithText(screenText).fetchSemanticsNodes().size)
        assertEquals("only the list's own top-bar actions show", 0, rule.onAllNodesWithText(screenAction).fetchSemanticsNodes().size)
        assertEquals("no Back arrow on the list", 0, rule.onAllNodes(hasContentDescription(text(R.string.common_back))).fetchSemanticsNodes().size)
    }

    @Test fun aSectionOpensWithItsScreenItsActionsAndABackArrowAndBackReturnsToTheListFocusedOnItsRow() {
        shell()
        rule.waitForIdle()
        rowOf(Tab.Home).performClick()
        rule.waitForIdle()
        assertEquals("the list has gone", 0, rule.onAllNodesWithTag(SECTION_ROW_TAG).fetchSemanticsNodes().size)
        rule.onNodeWithText(screenText).assertExists()
        rule.onNodeWithText(screenAction).assertExists()
        rule.onNode(hasContentDescription(text(R.string.common_back))).assertExists()
        rule.runOnUiThread { inputMode!!.requestInputMode(InputMode.Keyboard) }
        rule.onNode(hasContentDescription(text(R.string.common_back))).performClick()
        rule.waitForIdle()
        listIsThePage()
        rowOf(Tab.Home).assertIsFocused()
        assertEquals(0, rule.onAllNodesWithText(screenText).fetchSemanticsNodes().size)
        assertEquals(0, rule.onAllNodesWithText(screenAction).fetchSemanticsNodes().size)
    }

    @Test fun backOnTheListGoesToTheSystem() {
        shell()
        rule.waitForIdle()
        assertTrue("on the list the app is still there", !rule.activity.isFinishing)
        pressBack()
        assertTrue("Back with no handler of the shell's own leaves, as at the first screen of the other looks", rule.activity.isFinishing)
    }
}
