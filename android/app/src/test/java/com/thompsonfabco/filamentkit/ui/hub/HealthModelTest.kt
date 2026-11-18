package com.thompsonfabco.filamentkit.ui.hub

import android.os.Build
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.Density
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.HealthAnswer
import com.thompsonfabco.filamentkit.net.HealthChange
import com.thompsonfabco.filamentkit.net.HealthCheck
import com.thompsonfabco.filamentkit.net.HubAnswer
import com.thompsonfabco.filamentkit.net.HubCheck
import com.thompsonfabco.filamentkit.net.HubCheckState
import com.thompsonfabco.filamentkit.ui.SemanticsAudit
import com.thompsonfabco.filamentkit.ui.components.SwTopBar
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.ZoneId
import java.util.Locale

private fun change(at: String, key: String, text: String, from: String, to: String) =
    HealthChange(at, runCatching { java.time.Instant.parse(at).toEpochMilli() }.getOrNull(), key, text, from, to)

private fun health(since: String? = null, changes: List<HealthChange> = emptyList()) =
    HealthAnswer("2026-11-11T00:00:00Z", "2026-11-18T00:00:00Z", since, listOf(HealthCheck("printer:p-3", "Printers", "Workshop X1", "ok")), changes)

/** The check history table of the Hub screen (R84 4.3): its rows, its footnote, its days. */
class HealthTableTest {
    private val utc = ZoneId.of("UTC")
    private val words = HealthWords(ok = "Fine", look = "Look")

    @Test fun rowsAreNewestFirstWithStatesAsWords() {
        val rows = HealthTable.rows(
            health(changes = listOf(
                change("2026-11-15T23:10:00Z", "printer:p-3", "Workshop X1", "ok", "bad"),
                change("2026-11-16T06:45:00Z", "printer:p-3", "Workshop X1", "bad", "ok"),
                change("2026-11-16T07:00:00Z", "check:backup", "", "ok", "look"),
            )),
            words, utc, Locale.US,
        )
        assertEquals(listOf("check:backup", "Workshop X1", "Workshop X1"), rows.map { it.check })
        assertEquals("Look", rows[0].to)
        assertEquals("Needs fixing", rows[2].to)
        assertEquals("Fine", rows[2].from)
        assertEquals("Nov 16, 2026, 7:00 AM", rows[0].time.replace(' ', ' '))
        assertEquals("Nov 15, 2026, 11:10 PM. Workshop X1: from Fine to Needs fixing", rows[2].spoken.replace(' ', ' '))
    }

    @Test fun aStateTheAppDoesNotKnowIsShownAsTheHubWroteIt() {
        assertEquals("paused", HealthTable.stateWord("paused", words))
    }

    @Test fun theFootnoteSaysWhenTheRecordStartsAndIsAbsentWithoutIt() {
        assertEquals("No history before Nov 14, 2026.", HealthTable.footnote(health(since = "2026-11-14T10:00:00Z"), utc, Locale.US))
        assertNull(HealthTable.footnote(health(), utc, Locale.US))
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class HealthViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)

    @After fun tearDown() = Dispatchers.resetMain()

    @Test fun itReadsSevenDaysAndThirtyOnRequest() {
        val asked = mutableListOf<Int>()
        val vm = HealthViewModel { days -> asked += days; health() }
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertEquals(listOf(7), asked)
        assertNotNull(vm.state.value.answer)
        vm.setDays(30)
        dispatcher.scheduler.runCurrent()
        assertEquals(listOf(7, 30), asked)
        assertEquals(30, vm.state.value.days)
        vm.setDays(30)
        dispatcher.scheduler.runCurrent()
        assertEquals("the same days are not read again", 2, asked.size)
    }

    @Test fun anOlderHubLeavesTheTableOut() {
        val vm = HealthViewModel { null }
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertTrue(vm.state.value.unavailable)
        assertNull(vm.state.value.answer)
    }

    @Test fun aFailedReadKeepsTheAnswerAlreadyShownAndSaysWhy() {
        var fail = false
        val vm = HealthViewModel { if (fail) throw ApiError(0, "offline", "no route") else health(since = "2026-11-14T10:00:00Z") }
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        fail = true
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertTrue(vm.state.value.failed)
        assertNotNull(vm.state.value.answer)
        assertFalse(vm.state.value.loading)
    }

    @Test fun changingTheDaysWhileAReadRunsReadsAgainForTheNewDays() {
        val asked = mutableListOf<Int>()
        val vm = HealthViewModel { days -> asked += days; health() }
        vm.refresh()
        vm.setDays(30)
        dispatcher.scheduler.runCurrent()
        assertEquals(listOf(7, 30), asked)
        assertEquals(30, vm.state.value.days)
    }
}

/** The table on the Hub screen itself, in light and dark at font scale 1 and 2. */
@OptIn(ExperimentalMaterial3Api::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class HubScreenHealthTest {
    @get:Rule val rule = createComposeRule()

    private var dark by mutableStateOf(false)
    private var fontScale by mutableStateOf(1f)
    private var density = 1f
    private var ui by mutableStateOf(HealthUi(answer = health(
        since = "2026-11-14T10:00:00Z",
        changes = listOf(change("2026-11-15T23:10:00Z", "printer:p-3", "Workshop X1", "ok", "bad")),
    )))
    private val asked = mutableListOf<Int>()

    private val hub = HubAnswer(
        name = "Hub", version = "0.7.0", newest = null, updateAvailable = false,
        checks = listOf(HubCheck("Hub", HubCheckState.Ok, "The Hub is running.", null)),
        gettingStarted = null, features = emptyList(), catalog = null, backup = null, reader = null, devices = emptyList(),
        recordsKept = null, spoolmanUrl = null, hubPage = null,
    )

    private fun show(withHealth: Boolean = true) {
        rule.setContent {
            val base = LocalDensity.current
            density = base.density
            CompositionLocalProvider(LocalDensity provides Density(base.density, fontScale)) {
                SpoolwardenTheme(Look.Console, if (dark) Appearance.Dark else Appearance.Light) {
                    Column(Modifier.fillMaxSize()) {
                        SwTopBar(title = HubTexts.TITLE)
                        HubScreen(HubUi(hub = hub, loaded = true), online = true, onTryAgain = {}, health = if (withHealth) ui else null, onHealthDays = { asked += it })
                    }
                }
            }
        }
    }

    @Test fun theTableShowsTimeCheckFromToAndTheFootnoteAndPassesTheAudit() {
        show()
        rule.waitForIdle()
        assertTrue(rule.onAllNodesWithText("Check history").fetchSemanticsNodes().isNotEmpty())
        assertTrue(rule.onAllNodesWithText("Workshop X1").fetchSemanticsNodes().isNotEmpty())
        assertTrue(rule.onAllNodesWithText("OK → Needs fixing").fetchSemanticsNodes().isNotEmpty())
        assertTrue(rule.onAllNodesWithText("No history before", substring = true).fetchSemanticsNodes().isNotEmpty())
        for (isDark in listOf(false, true)) for (scale in listOf(1f, 2f)) {
            dark = isDark
            fontScale = scale
            rule.waitForIdle()
            val merged = rule.onRoot().fetchSemanticsNode()
            val unmerged = rule.onRoot(useUnmergedTree = true).fetchSemanticsNode()
            assertEquals("dark=$isDark fontScale=$scale", emptyList<String>(), SemanticsAudit.findings(merged, unmerged, density, HubTexts.TITLE))
        }
    }

    @Test fun showThirtyDaysAsksForThirtyAndAnOlderHubLeavesTheTableOut() {
        show()
        rule.waitForIdle()
        rule.onNodeWithText("Show 30 days").performClick()
        assertEquals(listOf(30), asked)
        ui = HealthUi(unavailable = true)
        rule.waitForIdle()
        assertEquals(0, rule.onAllNodesWithText("Check history").fetchSemanticsNodes().size)
    }

    @Test fun withoutAHealthStateTheScreenIsAsItWas() {
        show(false)
        rule.waitForIdle()
        assertEquals(0, rule.onAllNodesWithText("Check history").fetchSemanticsNodes().size)
    }
}
