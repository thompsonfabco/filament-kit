package com.thompsonfabco.filamentkit.ui.settings

import android.os.Build
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.junit4.createComposeRule
import com.thompsonfabco.filamentkit.LookedAppFrame
import com.thompsonfabco.filamentkit.RememberHubLook
import com.thompsonfabco.filamentkit.data.Settings
import com.thompsonfabco.filamentkit.session.Startup
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.LocalNavStyle
import com.thompsonfabco.filamentkit.ui.theme.NavStyle
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** S6.3: the app's root wiring that MainActivity uses: the stored choice and the Hub's look reach the theme. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h800dp")
class LookedAppFrameTest {
    @get:Rule val rule = createComposeRule()
    private val all = Look.entries // every look counts as built, so the choice is visible in the theme

    private fun setUpFrame(start: Startup, choice: MutableStateFlow<Look?>, hub: MutableStateFlow<Look?>, seen: MutableList<Pair<Look, NavStyle>>) {
        rule.setContent {
            LookedAppFrame(Appearance.Light, start, choice, hub, built = all) { look -> seen += look to LocalNavStyle.current }
        }
        rule.waitForIdle()
    }

    @Test fun theLookReachesTheFrameThatDrawsTheTheme() {
        val seen = mutableListOf<Pair<Look, NavStyle>>()
        setUpFrame(Startup(Appearance.Light, true, Look.Palette, null), MutableStateFlow(Look.Palette), MutableStateFlow(null), seen)
        assertEquals(Look.Palette to NavStyle.Pills, seen.last())
    }

    @Test fun theStoredChoiceWinsAndTheHubLookIsTheFallback() {
        val seen = mutableListOf<Pair<Look, NavStyle>>()
        val choice = MutableStateFlow<Look?>(null)
        val hub = MutableStateFlow<Look?>(Look.Panes)
        setUpFrame(Startup(Appearance.Light, true, null, Look.Panes), choice, hub, seen)
        assertEquals("no choice: the Hub's look", Look.Panes, seen.last().first)
        choice.value = Look.Workbench
        rule.waitForIdle()
        assertEquals("the choice flow recomposes the theme", Look.Workbench, seen.last().first)
        assertEquals(NavStyle.Sidebar, seen.last().second)
        choice.value = null
        rule.waitForIdle()
        assertEquals(Look.Panes, seen.last().first)
    }

    @Test fun theHubsWorkbenchApplyWithNothingStoredAndAppliesTheProfile() {
        // the default `built` list, as MainActivity passes it: the Workbench is drawn, not turned into Console
        val seen = mutableListOf<Pair<Look, NavStyle>>()
        rule.setContent {
            LookedAppFrame(Appearance.Light, Startup(Appearance.Light, true, null, Look.Workbench), MutableStateFlow(null), MutableStateFlow(Look.Workbench)) { look ->
                seen += look to LocalNavStyle.current
            }
        }
        rule.waitForIdle()
        assertEquals(Look.Workbench to NavStyle.Sidebar, seen.last())
    }

    @Test fun neitherChoiceNorHubLookIsConsole() {
        val seen = mutableListOf<Pair<Look, NavStyle>>()
        setUpFrame(Startup(Appearance.Light, true), MutableStateFlow(null), MutableStateFlow(null), seen)
        assertEquals(Look.Console, seen.last().first)
    }

    @Test fun theHubsLookFromInfoIsRememberedForPhonesThatHaveNotChosen() {
        val remembered = mutableListOf<Look>()
        var wire by mutableStateOf<String?>(null)
        rule.setContent { RememberHubLook(wire) { remembered += it } }
        rule.waitForIdle()
        assertEquals("nothing known yet", emptyList<Look>(), remembered)
        wire = "palette"
        rule.waitForIdle()
        assertEquals(listOf(Look.Palette), remembered)
        wire = "no-such-look"
        rule.waitForIdle()
        assertEquals("an unknown name is ignored", listOf(Look.Palette), remembered)
    }

    @Test fun theChoiceStoredInSettingsFlowsToTheTheme() {
        val dir = kotlin.io.path.createTempDirectory("looked").toFile()
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        try {
            val settings = Settings(PreferenceDataStoreFactory.create(scope = scope) { File(dir, "s.preferences_pb") })
            val seen = mutableListOf<Look>()
            rule.setContent {
                LookedAppFrame(Appearance.Light, Startup(Appearance.Light, true), settings.lookChoice, settings.hubLook, built = all) { seen += it }
            }
            rule.waitForIdle()
            assertEquals(Look.Console, seen.last())
            runBlocking { settings.setHubLook(Look.Panes) }
            rule.waitUntil(5_000) { seen.last() == Look.Panes }
            runBlocking { settings.setLook(Look.Workbench) }
            rule.waitUntil(5_000) { seen.last() == Look.Workbench }
        } finally {
            scope.cancel()
            dir.deleteRecursively()
        }
    }
}
