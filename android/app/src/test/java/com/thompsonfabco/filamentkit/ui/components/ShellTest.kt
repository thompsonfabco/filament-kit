package com.thompsonfabco.filamentkit.ui.components

import android.os.Build
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsNotSelected
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertTouchHeightIsEqualTo
import androidx.compose.ui.test.assertTouchWidthIsEqualTo
import androidx.compose.ui.test.assertWidthIsAtLeast
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.nav.HubState
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/** The shell's parts, drawn in the Console theme: the bar, the rail, the top bar and its two controls. */
@OptIn(ExperimentalMaterial3Api::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class ShellTest {
    @get:Rule val rule = createComposeRule()

    private val context = RuntimeEnvironment.getApplication()

    private fun themed(content: @Composable () -> Unit) = rule.setContent {
        SpoolwardenTheme(Look.Console, Appearance.Light, content)
    }

    private fun checkFiveDestinations() {
        var picked: Tab? = null
        themed { SwNav(selected = Tab.Spools, visible = true, onSelect = { picked = it }) { Box(Modifier.fillMaxSize()) } }
        for (tab in Tab.entries) {
            val item = rule.onNodeWithText(context.getString(tab.label))
            item.assertExists()
            item.assertHeightIsAtLeast(48.dp)
            item.assertWidthIsAtLeast(48.dp)
            if (tab == Tab.Spools) item.assertIsSelected() else item.assertIsNotSelected()
        }
        rule.onNodeWithText(context.getString(Tab.Printers.label)).performClick()
        assertEquals(Tab.Printers, picked)
    }

    @Test fun theBottomBarHasFiveLabelledDestinationsOf48dpOrMore() = checkFiveDestinations()

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h700dp")
    @Test fun theRailHasTheSameFiveDestinations() = checkFiveDestinations()

    @Test fun noBarIsDrawnWhilePairing() {
        themed { SwNav(selected = null, visible = false, onSelect = {}) { Box(Modifier.fillMaxSize()) } }
        rule.onNodeWithText(context.getString(Tab.Home.label)).assertDoesNotExist()
    }

    @Test fun anUpdateIsShownOnSettingsByADotWithAName() {
        themed { SwNav(selected = Tab.Home, visible = true, onSelect = {}, settingsUpdate = true) { Box(Modifier.fillMaxSize()) } }
        rule.onNodeWithContentDescription(context.getString(com.thompsonfabco.filamentkit.R.string.nav_settings_update)).assertExists()
    }

    @Test fun theAppearanceMenuAppliesAChoiceAndChecksTheCurrentOne() {
        var chosen: Appearance? = null
        themed { AppearanceMenu(current = Appearance.System, onChoose = { chosen = it }) }
        rule.onNodeWithContentDescription("Appearance: System").assertTouchHeightIsEqualTo(48.dp).performClick()
        for (appearance in Appearance.entries) {
            val item = rule.onNodeWithText(context.getString(appearance.label))
            item.assertHeightIsAtLeast(48.dp)
            if (appearance == Appearance.System) item.assertIsSelected() else item.assertIsNotSelected()
        }
        rule.onNodeWithText("Dark").performClick()
        assertEquals(Appearance.Dark, chosen)
        rule.onNodeWithText("Light").assertDoesNotExist()
    }

    @Test fun theChipSaysItsStateAsAWordAndOpensTheSheet() {
        var opened = 0
        var state by mutableStateOf(HubState.Connected)
        themed { SwConnectionChip(state, onClick = { opened++ }) }
        rule.onNodeWithText("Connected").assertExists()
        rule.onNodeWithContentDescription("Hub connection: Connected. Opens details.").performClick()
        assertEquals(1, opened)

        state = HubState.Offline
        rule.onNodeWithText("Offline").assertExists()
        state = HubState.NoLongerPaired
        rule.onNodeWithText("Needs a look").assertExists()
        state = HubState.Checking
        rule.onNodeWithContentDescription("Hub connection: checking").performClick()
        assertEquals(2, opened)
        assertNull(HubState.Checking.badge)
    }

    @Test fun theTopBarShowsBackOnlyWhenAskedFor() {
        var backs = 0
        var withBack by mutableStateOf(false)
        themed { SwTopBar(title = "Printers", onBack = if (withBack) ({ backs++ }) else null) }
        rule.onNodeWithText("Printers").assertExists()
        rule.onNodeWithContentDescription("Back").assertDoesNotExist()
        withBack = true
        rule.onNodeWithContentDescription("Back").assertTouchHeightIsEqualTo(48.dp).assertTouchWidthIsEqualTo(48.dp).performClick()
        assertEquals(1, backs)
    }
}
