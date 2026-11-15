package com.thompsonfabco.filamentkit.ui.presets

import android.os.Build
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.isRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.Density
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.ui.SemanticsAudit
import com.thompsonfabco.filamentkit.ui.components.LocalTopBarActions
import com.thompsonfabco.filamentkit.ui.components.MAIN_BUTTON_TAG
import com.thompsonfabco.filamentkit.ui.components.SwTopBar
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
import org.robolectric.annotation.Config

/**
 * AUT-8 (07-accessibility 15) for the Slicer presets screen (05-android-app 11.2) and its Product lines panel: light and
 * dark at font scale 1 and 2, with the states of the screen, the new-line form and the parent sheet open. Data is fake.
 */
@OptIn(ExperimentalMaterial3Api::class)
@RunWith(RobolectricTestRunner::class)
// a tall window, so nothing is scrolled out of view and every control has a touch area to measure
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class PresetsScreenTest {
    @get:Rule val rule = createComposeRule()

    private var dark by mutableStateOf(false)
    private var fontScale by mutableStateOf(1f)
    private var density = 1f
    private val actions = TopBarActions()
    private val title = "Slicer presets"
    private val api = FakePresets()
    private var openedHubPage = 0
    private var hubPage: String? = "https://192.0.2.10:8443/setup"
    private var catalog = 0

    private fun show(api: FakePresets = this.api): PresetsViewModel {
        val vm = PresetsViewModel(api)
        rule.setContent {
            val base = LocalDensity.current
            density = base.density
            CompositionLocalProvider(LocalDensity provides Density(base.density, fontScale)) {
                SpoolwardenTheme(Look.Console, if (dark) Appearance.Dark else Appearance.Light) {
                    CompositionLocalProvider(LocalTopBarActions provides actions) {
                        Column(Modifier.fillMaxSize()) {
                            SwTopBar(title = title) { actions.content?.invoke(this) }
                            Box(Modifier.weight(1f)) {
                                PresetsScreen(
                                    vm, onPairAgain = {}, onAddCatalogLine = { catalog++ },
                                    setupUrl = { openedHubPage++; hubPage }, nowMillis = NOW,
                                )
                            }
                        }
                    }
                }
            }
        }
        rule.waitForIdle()
        return vm
    }

    private fun audit(sections: List<String>): List<String> {
        rule.waitForIdle()
        val merged = rule.onRoot().fetchSemanticsNode()
        val unmerged = rule.onRoot(useUnmergedTree = true).fetchSemanticsNode()
        return SemanticsAudit.findings(merged, unmerged, density, title, sections)
    }

    private fun auditAllFour(shows: String, sections: List<String> = SECTIONS) {
        rule.waitForIdle()
        rule.onNodeWithText(shows).assertExists()
        assertTrue("the screen has controls to audit", SemanticsAudit.clickableCount(rule.onRoot().fetchSemanticsNode()) >= 1)
        for (isDark in listOf(false, true)) {
            for (scale in listOf(1f, 2f)) {
                dark = isDark
                fontScale = scale
                assertEquals("dark=$isDark fontScale=$scale", emptyList<String>(), audit(sections))
            }
        }
    }

    /** The controls rules on the sheet's own window root, in the same four settings. */
    private fun auditSheetAllFour(shows: String) {
        rule.waitForIdle()
        rule.onNodeWithText(shows).assertExists()
        for (isDark in listOf(false, true)) {
            for (scale in listOf(1f, 2f)) {
                dark = isDark
                fontScale = scale
                rule.waitForIdle()
                val merged = rule.onAllNodes(isRoot()).fetchSemanticsNodes()
                val unmerged = rule.onAllNodes(isRoot(), useUnmergedTree = true).fetchSemanticsNodes()
                assertTrue("the sheet is open", merged.size > 1)
                val found = merged.indices.drop(1).flatMap {
                    SemanticsAudit.findings(merged[it], unmerged[it], density, title, screenRoot = false)
                }
                assertEquals("dark=$isDark fontScale=$scale", emptyList<String>(), found)
            }
        }
    }

    @Test fun theScreenWithItsStatusFilamentsAndLines() {
        show()
        rule.onNodeWithText("Built").assertExists()
        rule.onNodeWithText("24 presets for 6 lines, built 4 h ago").assertExists()
        rule.onNodeWithText("Slicer Sync is not set up").assertExists()
        rule.onNodeWithText("Presets are built on the Hub and installed on your PC by Slicer Sync the next time the slicers are closed.").assertExists()
        rule.onNodeWithText("Missing a product line?").assertExists()
        rule.onNodeWithText("Example Filaments Silk").assertExists()
        rule.onNodeWithText("PLA · 4 presets").assertExists()
        rule.onNodeWithText("Bambu Studio parent: Generic PLA").assertExists()
        rule.onNodeWithText("Bambu Studio parent: none").assertExists()
        rule.onNodeWithText("Attach filaments to lines and build presets now on the Hub page or in the web app.").assertExists()
        auditAllFour("Build now")
    }

    @Test fun onlyBuildNowIsTheFilledButton() {
        show()
        assertEquals(1, rule.onAllNodes(hasTestTag(MAIN_BUTTON_TAG)).fetchSemanticsNodes().size)
        rule.onNodeWithText("Build now").performClick()
        rule.waitForIdle()
        assertEquals(1, api.builds)
        rule.onNodeWithText("Build requested. The Hub builds the presets within a minute or two.").assertExists()
        auditAllFour("Build requested. The Hub builds the presets within a minute or two.")
    }

    @Test fun theNewLineFormIsAudited() {
        api.parentLists["PLA"] = ParentList(listOf("Bambu PLA Basic", "Generic PLA"), synced = true)
        show()
        // the first filament has lines of its brand; its disclosure reads "Or start a new line"
        rule.onNodeWithText("Or start a new line").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Line name").assertExists()
        rule.onNodeWithText("Create line").assertExists()
        rule.onNodeWithText("Start a new line (new brand or product line)").assertExists()
        auditAllFour("Create line")
    }

    @Test fun addToLineAsksTheHubAndTheCardLeaves() {
        show()
        rule.onNodeWithText("Add to line").performClick()
        rule.waitForIdle()
        assertEquals(listOf("Example Filaments PolyTerra" to 7), api.added)
        assertEquals(0, rule.onAllNodesWithText("Add to line").fetchSemanticsNodes().size)
    }

    @Test fun theHubsFieldRefusalIsShownUnderTheNameField() {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        api.failure = ApiError(
            400, "bad_request", "a line named Example Filaments PolyTerra already exists",
            kotlinx.serialization.json.JsonObject(mapOf("field" to kotlinx.serialization.json.JsonPrimitive("name"))),
        )
        show()
        rule.onNodeWithText("Or start a new line").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Create line").performClick()
        rule.waitForIdle()
        rule.onAllNodesWithText("a line named Example Filaments PolyTerra already exists", substring = true).fetchSemanticsNodes().let {
            assertEquals("once, under the field", 1, it.size)
        }
        auditAllFour("Create line")
    }

    @Test fun changeParentOpensTheSheetAndSavesThePickedParent() {
        api.parentLists["PLA"] = ParentList(listOf("Bambu PLA Basic", "Generic PLA"), synced = true)
        show()
        rule.onAllNodesWithText("Change parent")[1].performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Bambu Studio parent of Example Filaments Silk").assertExists()
        rule.onNodeWithText("Find a parent").assertExists()
        auditSheetAllFour("Bambu Studio parent of Example Filaments Silk")
        rule.onNodeWithText("Bambu PLA Basic").performClick()
        rule.onNodeWithText("Save").performClick()
        rule.waitForIdle()
        assertEquals(listOf("example--silk" to "Bambu PLA Basic"), api.reparented)
        rule.onNodeWithText("Saved. A preset build was asked for.").assertExists()
        rule.onNodeWithText("Bambu Studio parent of Example Filaments Silk").assertDoesNotExist()
    }

    @Test fun noParentsReportedYetShowsOnlyClose() {
        show()
        rule.onAllNodesWithText("Change parent")[0].performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Slicer Sync has not reported any parents yet. It reports them when it runs.").assertExists()
        rule.onNodeWithText("Save").assertDoesNotExist()
        auditSheetAllFour("Slicer Sync has not reported any parents yet. It reports them when it runs.")
        rule.onNodeWithText("Close").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Bambu Studio parent of Example Filaments PolyTerra").assertDoesNotExist()
    }

    @Test fun anEmptyListAndNoFilamentsWithoutALine() {
        val empty = FakePresets().also { it.lines = emptyList(); it.uncoveredList = emptyList() }
        show(empty)
        rule.onNodeWithText("No lines yet. They are made from the filaments in Spoolman at the next build or when a spool is added.").assertExists()
        rule.onNodeWithText("Every filament has a preset line.").assertExists()
        auditAllFour("Build now")
    }

    @Test fun aListThatCannotBeReadSaysSoAndOffersTryAgain() {
        val broken = FakePresets().also {
            it.linesFailure = ApiError(0, "offline", "x")
            it.uncoveredFailure = ApiError(0, "offline", "x")
            it.statusFailure = ApiError(0, "offline", "x")
        }
        show(broken)
        rule.onNodeWithText("Slicer preset status is not available right now.").assertExists()
        assertEquals(2, rule.onAllNodesWithText("Try again").fetchSemanticsNodes().size)
        auditAllFour("Build now")
    }

    @Test fun theLinesAreLoadingThenListed() {
        val gate = kotlinx.coroutines.CompletableDeferred<Unit>()
        val slow = FakePresets().also { it.linesGate = gate }
        show(slow)
        rule.onNodeWithText("Product lines").assertExists()
        rule.onNodeWithText("Example Filaments Silk").assertDoesNotExist()
        auditAllFour("Build now")
        gate.complete(Unit)
        rule.waitForIdle()
        rule.onNodeWithText("Example Filaments Silk").assertExists()
    }

    @Test fun theMissingLineButtonOpensTheCatalogAndTheHubPageLinkOpensTheHubPage() {
        show()
        rule.onNodeWithText("Add a line to the Filament Catalog").performClick()
        assertEquals(1, catalog)
        rule.onNodeWithText("Open the Hub page").performClick()
        assertEquals(1, openedHubPage)
        hubPage = null
        rule.onNodeWithText("Open the Hub page").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("The Hub's address isn't known yet.").assertExists()
    }

    private companion object {
        val SECTIONS = listOf("Missing a product line?", "Filaments without a preset line", "Product lines")

        // 4 hours after the fake build (2026-11-02T01:02:03Z)
        const val NOW = 1_793_581_323_000L + 4 * 3_600_000L + 5_000L
    }
}
