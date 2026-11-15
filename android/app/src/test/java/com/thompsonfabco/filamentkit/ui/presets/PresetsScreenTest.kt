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
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.isRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.Density
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.AcceptedUpdates
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.net.PresetUpdates
import com.thompsonfabco.filamentkit.net.UpdatesInfo
import com.thompsonfabco.filamentkit.ui.home.PresetUpdatesBackend
import com.thompsonfabco.filamentkit.ui.home.PresetUpdatesViewModel
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
    private var catalog = 0
    private var pairing by mutableStateOf<Any?>(null)

    private fun show(api: FakePresets = this.api, updates: PresetUpdatesViewModel? = null): PresetsViewModel {
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
                                    updates = updates, nowMillis = NOW, pairing = pairing,
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
        rule.onNodeWithText("Attach filaments to lines and build presets now on the Hub page or in the web app.").assertDoesNotExist()
        auditAllFour("Build presets now")
    }

    @Test fun onlyBuildNowIsTheFilledButton() {
        show()
        // the one filled button is "Build presets now" (not the Hub page's "Build now")
        assertEquals(1, rule.onAllNodes(hasTestTag(MAIN_BUTTON_TAG)).fetchSemanticsNodes().size)
        rule.onNode(hasTestTag(MAIN_BUTTON_TAG) and hasText("Build presets now")).assertExists()
        rule.onNodeWithText("Build now").assertDoesNotExist()
        rule.onNodeWithText("Build presets now").performClick()
        rule.waitForIdle()
        assertEquals(1, api.builds)
        // the Hub's own summary, not a fixed text
        rule.onNodeWithText("a build is requested").assertExists()
        rule.onNodeWithText("Build requested. The Hub builds the presets within a minute or two.").assertDoesNotExist()
        auditAllFour("a build is requested")
        // and still the one filled button afterwards
        assertEquals(1, rule.onAllNodes(hasTestTag(MAIN_BUTTON_TAG)).fetchSemanticsNodes().size)
    }

    @Test fun aBuildAnswerWithoutAnOutputShowsTheFixedText() {
        api.buildOutput = ""
        show()
        rule.onNodeWithText("Build presets now").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Build requested. The Hub builds the presets within a minute or two.").assertExists()
    }

    @Test fun theTitleOfTheFilamentsPanelCarriesTheirCountAndTheEmptyStateKeepsItsTextWithACount() {
        show()
        // the title stays one heading of its own; the count is the text next to it
        rule.onNode(hasText("Filaments without a preset line") and SemanticsMatcher.keyIsDefined(SemanticsProperties.Heading)).assertExists()
        rule.onNodeWithText("2").assertExists()
        val title = rule.onNodeWithText("Filaments without a preset line").fetchSemanticsNode().boundsInRoot
        val count = rule.onNodeWithText("2").fetchSemanticsNode().boundsInRoot
        assertTrue("beside the title", count.left >= title.right && count.top < title.bottom)
    }

    @Test fun findAParentNarrowsTheTemplatesOfTheNewLineForm() {
        api.parentLists["PLA"] = ParentList(listOf("Bambu PLA Basic", "Generic PLA", "Bambu PETG Basic"), synced = true)
        val vm = show()
        rule.onNodeWithText("Or start a new line").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Find a parent").assertExists()
        rule.onNodeWithText("Find a parent").performTextInput("petg")
        rule.waitForIdle()
        assertEquals("petg", vm.state.value.card(7).find)
        rule.onNodeWithText("Bambu Studio template").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Bambu PETG Basic").assertExists()
        rule.onNodeWithText("Bambu PLA Basic").assertDoesNotExist()
    }

    @Test fun whileItRunsTheButtonSaysBuildingPresets() {
        val gate = kotlinx.coroutines.CompletableDeferred<Unit>()
        api.gate = gate
        show()
        rule.onNodeWithText("Build presets now").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Building presets… (a minute or two)").assertExists()
        gate.complete(Unit)
        rule.waitForIdle()
        rule.onNodeWithText("Building presets… (a minute or two)").assertDoesNotExist()
    }

    @Test fun aHubWithoutTheBuildRouteShowsNoButtonAndSaysSo() {
        api.failure = ApiError(404, "not_found", "Not Found")
        show()
        rule.onNodeWithText("Build presets now").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Building from the phone needs a newer Hub. Update the Hub, or build on the Hub page.").assertExists()
        rule.onNodeWithText("Build presets now").assertDoesNotExist()
        assertEquals(0, rule.onAllNodes(hasTestTag(MAIN_BUTTON_TAG)).fetchSemanticsNodes().size)
    }

    @Test fun theUpdatesPanelIsTheLastAndSaysHowManyWait() {
        api.updatesInfo = UpdatesInfo(count = 3, lines = 2, accepted = 0)
        val updates = PresetUpdatesViewModel(object : PresetUpdatesBackend {
            override suspend fun list() = PresetUpdates()
            override suspend fun accept(stamp: String, names: List<String>) = AcceptedUpdates()
            override suspend fun restoreDeleted() = Unit
        })
        show(updates = updates)
        rule.onNodeWithText("3 updates are waiting.").assertExists()
        rule.onNodeWithText("Review 3 updates").assertExists()
        val top = { text: String -> rule.onNodeWithText(text).fetchSemanticsNode().boundsInRoot.top }
        assertTrue(top("Product lines") < top("3 updates are waiting."))
        assertTrue(top("Filaments without a preset line") < top("Product lines"))
        auditAllFour("Review 3 updates")
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

    @Test fun theNewLineFormHasTheOrcaSlicerParentSelectAndSendsTheChosenOne() {
        api.parentLists["PLA"] = ParentList(listOf("Bambu PLA Basic", "Generic PLA"), synced = true)
        api.orcaLists["PLA"] = listOf("Bambu PLA Basic @BBL X1C", "Generic PLA")
        val vm = show()
        rule.onNodeWithText("Or start a new line").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Orca Slicer parent").assertExists()
        // optional: the Hub chooses until one is picked
        rule.onNodeWithText("Let the Hub choose").assertExists()
        rule.onNodeWithText("Orca Slicer parent").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Bambu PLA Basic @BBL X1C").performClick()
        rule.waitForIdle()
        assertEquals("Bambu PLA Basic @BBL X1C", vm.state.value.card(7).orcaParent)
        // between "Find a parent" and "Bambu Studio template", as in the spec
        val find = rule.onNodeWithText("Find a parent").fetchSemanticsNode().boundsInRoot.top
        val orca = rule.onNodeWithText("Orca Slicer parent").fetchSemanticsNode().boundsInRoot.top
        val template = rule.onNodeWithText("Bambu Studio template").fetchSemanticsNode().boundsInRoot.top
        assertTrue("Find a parent, Orca Slicer parent, template", find < orca && orca < template)
        auditAllFour("Create line")
        rule.onNodeWithText("Create line").performClick()
        rule.waitForIdle()
        assertEquals(listOf<String?>("Bambu PLA Basic @BBL X1C"), api.createdOrca)
    }

    @Test fun withoutAnOrcaLibraryTheFormSaysSoAndIsAudited() {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        show()
        rule.onNodeWithText("Or start a new line").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("No Orca Slicer library has been uploaded yet", substring = true).assertExists()
        auditAllFour("Create line")
    }

    @Test fun anOrcaParentRefusalIsUnderTheOrcaSelectWhenItIsShown() {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        api.orcaLists["PLA"] = listOf("Generic PLA")
        api.failure = ApiError(
            400, "bad_request", "orca_parent is not in the Orca library",
            kotlinx.serialization.json.JsonObject(mapOf("field" to kotlinx.serialization.json.JsonPrimitive("orca_parent"))),
        )
        show()
        rule.onNodeWithText("Or start a new line").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Create line").performClick()
        rule.waitForIdle()
        assertEquals(1, rule.onAllNodesWithText("orca_parent is not in the Orca library", substring = true).fetchSemanticsNodes().size)
        val message = rule.onNodeWithText("orca_parent is not in the Orca library", substring = true).fetchSemanticsNode()
        val template = rule.onNodeWithText("Bambu Studio template").fetchSemanticsNode()
        assertTrue("under the Orca select, above the template", message.boundsInRoot.bottom <= template.boundsInRoot.top)
        auditAllFour("Create line")
    }

    @Test fun addToLineAsksTheHubAndTheCardLeaves() {
        show()
        rule.onNodeWithText("Add to line").performClick()
        rule.waitForIdle()
        assertEquals(listOf("example--polyterra" to 7), api.added)
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
        // under the Line name field, so above the Create line button (a notice would sit below it)
        val message = rule.onNodeWithText("a line named Example Filaments PolyTerra already exists", substring = true).fetchSemanticsNode()
        val create = rule.onNodeWithText("Create line").fetchSemanticsNode()
        assertTrue("under the field", message.boundsInRoot.bottom <= create.boundsInRoot.top)
        auditAllFour("Create line")
    }

    private fun parentRefusalIsUnderTheTemplateField(field: String) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        api.failure = ApiError(
            400, "unknown_parent", "Bambu Studio has no preset Generic PLA",
            kotlinx.serialization.json.JsonObject(mapOf("field" to kotlinx.serialization.json.JsonPrimitive(field))),
        )
        show()
        rule.onNodeWithText("Or start a new line").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Create line").performClick()
        rule.waitForIdle()
        assertEquals(1, rule.onAllNodesWithText("Bambu Studio has no preset Generic PLA", substring = true).fetchSemanticsNodes().size)
        val message = rule.onNodeWithText("Bambu Studio has no preset Generic PLA", substring = true).fetchSemanticsNode()
        val create = rule.onNodeWithText("Create line").fetchSemanticsNode()
        assertTrue("under the template field", message.boundsInRoot.bottom <= create.boundsInRoot.top)
    }

    @Test fun aParentRefusalIsUnderTheTemplateField() = parentRefusalIsUnderTheTemplateField("parent")

    @Test fun anOrcaParentRefusalIsUnderTheTemplateFieldToo() = parentRefusalIsUnderTheTemplateField("orca_parent")

    @Test fun aRefusalWithoutAFieldIsTheNoticeLineBelowTheForm() {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        api.failure = ApiError(400, "bad_request", "a line named Example Filaments PolyTerra already exists")
        show()
        rule.onNodeWithText("Or start a new line").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Create line").performClick()
        rule.waitForIdle()
        rule.onAllNodesWithText("a line named Example Filaments PolyTerra already exists", substring = true).fetchSemanticsNodes().let {
            assertEquals("once, in the notice line", 1, it.size)
        }
        val message = rule.onNodeWithText("a line named Example Filaments PolyTerra already exists", substring = true).fetchSemanticsNode()
        val create = rule.onNodeWithText("Create line").fetchSemanticsNode()
        assertTrue("below the form", message.boundsInRoot.top >= create.boundsInRoot.bottom)
        auditAllFour("Create line")
    }

    @Test fun aFieldTheFormLacksIsTheNoticeLineToo() {
        api.failure = ApiError(
            400, "bad_request", "filament 7 is already in a line",
            kotlinx.serialization.json.JsonObject(mapOf("field" to kotlinx.serialization.json.JsonPrimitive("ids"))),
        )
        show()
        rule.onNodeWithText("Add to line").performClick()
        rule.waitForIdle()
        assertEquals(1, rule.onAllNodesWithText("filament 7 is already in a line").fetchSemanticsNodes().size)
        rule.onNodeWithText("Add to line").assertExists()
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
        auditAllFour("Build presets now")
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
        auditAllFour("Build presets now")
    }

    @Test fun theLinesAreLoadingThenListed() {
        val gate = kotlinx.coroutines.CompletableDeferred<Unit>()
        val slow = FakePresets().also { it.linesGate = gate }
        show(slow)
        rule.onNodeWithText("Product lines").assertExists()
        rule.onNodeWithText("Example Filaments Silk").assertDoesNotExist()
        auditAllFour("Build presets now")
        gate.complete(Unit)
        rule.waitForIdle()
        rule.onNodeWithText("Example Filaments Silk").assertExists()
    }

    @Test fun theMissingLineButtonOpensTheCatalog() {
        show()
        rule.onNodeWithText("Add a line to the Filament Catalog").performClick()
        assertEquals(1, catalog)
        rule.onNodeWithText("Open the Hub page").assertDoesNotExist()
    }

    @Test fun pairingAgainReadsTheScreenAgain() {
        pairing = Any()
        show()
        val before = api.statusCalls
        pairing = Any()
        rule.waitForIdle()
        assertEquals(before + 1, api.statusCalls)
    }

    private companion object {
        val SECTIONS = listOf("Missing a product line?", "Filaments without a preset line", "Product lines")

        // 4 hours after the fake build (2026-11-02T01:02:03Z)
        const val NOW = 1_793_581_323_000L + 4 * 3_600_000L + 5_000L
    }
}
