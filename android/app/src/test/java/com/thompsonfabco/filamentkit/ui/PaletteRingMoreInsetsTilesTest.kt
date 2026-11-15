package com.thompsonfabco.filamentkit.ui

import android.os.Build
import android.view.View
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PixelMap
import androidx.compose.ui.graphics.toPixelMap
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.core.view.WindowInsetsCompat
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.net.HistorySpool
import com.thompsonfabco.filamentkit.net.HistorySummary
import com.thompsonfabco.filamentkit.net.IntakeHistory
import com.thompsonfabco.filamentkit.net.LoadResult
import com.thompsonfabco.filamentkit.net.LoadSlot
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.ui.components.PillMore
import com.thompsonfabco.filamentkit.ui.components.RingSize
import com.thompsonfabco.filamentkit.ui.components.SpoolRing
import com.thompsonfabco.filamentkit.ui.components.SwPills
import com.thompsonfabco.filamentkit.ui.components.paletteMore
import com.thompsonfabco.filamentkit.ui.history.HistoryBackend
import com.thompsonfabco.filamentkit.ui.history.HistoryListScreen
import com.thompsonfabco.filamentkit.ui.history.HistoryListViewModel
import com.thompsonfabco.filamentkit.ui.printers.PrinterLists
import com.thompsonfabco.filamentkit.ui.printers.PrinterTile
import com.thompsonfabco.filamentkit.ui.printers.PrintersUiState
import com.thompsonfabco.filamentkit.ui.printers.SlotLook
import com.thompsonfabco.filamentkit.ui.spool.LoadBackend
import com.thompsonfabco.filamentkit.ui.spool.LoadPrintersScreen
import com.thompsonfabco.filamentkit.ui.spool.LoadPrintersViewModel
import com.thompsonfabco.filamentkit.ui.spool.SpoolSummary
import com.thompsonfabco.filamentkit.ui.spool.SpoolTile
import com.thompsonfabco.filamentkit.ui.components.SwCollection
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.serialization.json.JsonObject
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
 * S6.7 rework 2: the spool ring draws the spool's colour for the share left; More follows 02-components 2.3 (the System
 * group lives in More, its name when current, the menu semantics); the pills keep clear of a cutout with the default
 * insets the app uses; every collection 02 gives a Palette tile gets one, the printer tile reads its slots and fix line,
 * and a tile's action names its item.
 */
@OptIn(ExperimentalMaterial3Api::class)
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h800dp")
class PaletteRingMoreInsetsTilesTest {
    @get:Rule val rule = createComposeRule()

    private var density = 1f

    private fun themed(look: Look = Look.Palette, content: @Composable () -> Unit) = rule.setContent {
        density = androidx.compose.ui.platform.LocalDensity.current.density
        SpoolwardenTheme(look, Appearance.Light, content)
    }

    private fun string(id: Int, vararg args: Any) = RuntimeEnvironment.getApplication().getString(id, *args)

    private val red = Color(0xFFFF0000)

    private fun count(image: PixelMap, colour: Color): Int {
        var hits = 0
        for (x in 0 until image.width) for (y in 0 until image.height) if (image[x, y] == colour) hits++
        return hits
    }

    // ----- 1: the ring

    private var ringLevel by mutableStateOf<Float?>(1f)
    private var ringed by mutableStateOf<SpoolSummary?>(null)
    private var drawn = false

    private fun redOf(level: Float?): Int {
        ringLevel = level
        if (!drawn) {
            drawn = true
            themed { SpoolRing("FF0000", ringLevel, RingSize.Large) }
        }
        rule.waitForIdle()
        return count(rule.onRoot().captureToImage().toPixelMap(), red)
    }

    @Test fun theRingsArcIsTheSpoolsColourAndItsSweepFollowsTheShareLeft() {
        val full = redOf(1f)
        assertTrue("a full ring draws the colour: $full", full > 500)
        assertEquals("half the ring", 0.5f, redOf(0.5f) / full.toFloat(), 0.05f)
    }

    @Test fun aQuarterAndAThreeQuarterRingDifferAndNoLevelDrawsNoArc() {
        val full = redOf(1f)
        assertEquals("a quarter", 0.25f, redOf(0.25f) / full.toFloat(), 0.05f)
        assertEquals("three quarters", 0.75f, redOf(0.75f) / full.toFloat(), 0.05f)
        assertEquals("no weight (02-components 7.4): the full track, no arc", 0, redOf(null))
    }

    private fun spool(remaining: Double?, total: Double? = 1000.0) = SpoolSummary(
        id = 214, brand = "Polymaker", name = "PolyTerra Charcoal", material = "PLA", colorHex = "FF0000", location = "Shelf A",
        remaining = remaining, total = total,
    )

    private fun redOfTile(spool: SpoolSummary): Int {
        val first = ringed == null
        ringed = spool
        if (first) themed { SwCollection(listOf(ringed!!), tile = { _, s -> SpoolTile(s, onClick = {}) }) { _, _ -> } }
        rule.waitForIdle()
        return count(rule.onRoot().captureToImage().toPixelMap(), red)
    }

    @Test fun aSpoolTilesRingShowsTheRemainingWeight() {
        val full = redOfTile(spool(1000.0))
        assertTrue("the spool's colour is in the ring: $full", full > 500)
        assertEquals("250 of 1000 g", 0.25f, redOfTile(spool(250.0)) / full.toFloat(), 0.05f)
    }

    @Test fun aSpoolWithNoWeightHasNoArc() {
        assertEquals(0, redOfTile(spool(remaining = null, total = null)))
    }

    // ----- 2: More

    private fun more(selected: Tab?, page: Boolean = false, update: Boolean = false, onSettings: () -> Unit = {}) = themed {
        val pages = listOf(
            PillMore("Appearance", R.drawable.sw_ic_half_circle, page, section = "Settings") {},
            PillMore("Updates", R.drawable.sw_ic_updates, false, section = "Settings") {},
        )
        Column(Modifier.fillMaxSize()) {
            SwPills(
                selected, true, onSelect = {}, settingsUpdate = update,
                more = paletteMore(selected, "Settings", pages, onSettings),
                insets = androidx.compose.foundation.layout.WindowInsets(0, 0, 0, 0),
            )
        }
    }

    private fun settingsIsInMoreNotAPill(selected: Tab, page: Boolean) {
        more(selected, page)
        rule.waitForIdle()
        assertEquals("Settings is no pill", 0, rule.onAllNodesWithText("Settings").fetchSemanticsNodes().size)
        rule.onNodeWithText(string(Tab.Home.label)).assertExists()
        rule.onNodeWithText("More").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Settings").assertExists()
        rule.onNodeWithText("Appearance").assertExists()
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun settingsIsInMoreAndNotAPillOnAnotherSection() = settingsIsInMoreNotAPill(Tab.Home, false)

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun settingsIsInMoreAndNotAPillOnItsRoot() = settingsIsInMoreNotAPill(Tab.Settings, false)

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun settingsIsInMoreAndNotAPillOnOneOfItsPages() = settingsIsInMoreNotAPill(Tab.Settings, true)

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun whileOnSettingsMoreIsCurrentAndNamesTheSection() {
        more(Tab.Settings)
        rule.waitForIdle()
        rule.onNodeWithContentDescription("More, current: Settings").assertIsSelected()
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun onAPageOfSettingsMoreStillNamesTheSection() {
        more(Tab.Settings, page = true)
        rule.waitForIdle()
        rule.onNodeWithContentDescription("More, current: Settings").assertIsSelected()
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun onAnotherSectionMoreIsJustMoreAndNotSelected() {
        more(Tab.Printers)
        rule.waitForIdle()
        rule.onNodeWithContentDescription("More").assert(SemanticsMatcher.expectValue(SemanticsProperties.Selected, false))
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun moreSaysItOpensAMenuAndWhetherItIsOpen() {
        more(Tab.Home)
        rule.waitForIdle()
        val button = rule.onNodeWithContentDescription("More")
        button.assert(SemanticsMatcher.keyIsDefined(SemanticsActions.Expand))
        button.assert(SemanticsMatcher.keyNotDefined(SemanticsActions.Collapse))
        button.assert(SemanticsMatcher.expectValue(SemanticsProperties.StateDescription, string(R.string.nav_more_collapsed)))
        button.performClick()
        rule.waitForIdle()
        val open = rule.onNodeWithContentDescription("More")
        open.assert(SemanticsMatcher.keyIsDefined(SemanticsActions.Collapse))
        open.assert(SemanticsMatcher.expectValue(SemanticsProperties.StateDescription, string(R.string.nav_more_expanded)))
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun theUpdateDotMovesToMoreWithSettings() {
        more(Tab.Home, update = true)
        rule.waitForIdle()
        rule.onNodeWithContentDescription(string(R.string.nav_more_update)).assertExists()
        assertEquals(0, rule.onAllNodesWithContentDescription(string(R.string.nav_settings_update)).fetchSemanticsNodes().size)
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun theUpdateDotAndTheCurrentSectionAreBothSaid() {
        more(Tab.Settings, update = true)
        rule.waitForIdle()
        rule.onNodeWithContentDescription(string(R.string.nav_more_current_update, "Settings")).assertIsSelected()
    }

    // ----- 3: the default insets, as MainActivity passes none

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w900dp-h400dp")
    @Test fun withTheDefaultInsetsThePillsKeepClearOfACutoutInLandscape() {
        var view: View? = null
        themed {
            view = LocalView.current
            Column(Modifier.fillMaxSize()) { SwPills(Tab.Home, true, onSelect = {}) }
        }
        rule.waitForIdle()
        val cutout = (48 * density).toInt()
        val before = rule.onNodeWithText(string(Tab.Home.label)).fetchSemanticsNode().boundsInRoot.left
        rule.runOnUiThread {
            val insets = WindowInsetsCompat.Builder()
                .setInsets(WindowInsetsCompat.Type.displayCutout(), androidx.core.graphics.Insets.of(cutout, 0, cutout, 0))
                .build().toWindowInsets()!!
            view!!.dispatchApplyWindowInsets(insets)
        }
        rule.waitForIdle()
        val after = rule.onNodeWithText(string(Tab.Home.label)).fetchSemanticsNode().boundsInRoot.left
        assertTrue("the first pill moved in by the cutout: $before -> $after", after >= before + cutout - 1f)
    }

    // ----- 4: the printer tile's TalkBack text

    @Test fun thePrinterTileReadsItsSlotsAndTheFixLine() {
        val printer = Printer(id = "P1", name = "Study P1S", serial = "P1", configured = true, state = "wrong_code", model = "P1S")
        val slots = listOf(SlotLook("#2B2B2E", false), SlotLook("", true))
        themed { SwCollection(listOf(printer), tile = { _, p -> PrinterTile(p, slots) {} }) { _, _ -> } }
        rule.waitForIdle()
        val said = rule.onNode(SemanticsMatcher("the tile's description") {
            it.config.getOrNull(SemanticsProperties.ContentDescription)?.any { d -> d.startsWith("Study P1S") } == true
        }).fetchSemanticsNode().config[SemanticsProperties.ContentDescription].first()
        assertTrue("slots: $said", said.contains("Slots:") && said.contains("Colour 2B2B2E") && said.contains("Empty slot"))
        assertTrue(
            "the fix line: $said",
            said.contains("The printer did not accept the Access Code. Enter the Access Code again."),
        )
    }

    // ----- 5, 6: tiles everywhere, with the item in the action's name

    private fun printersState() = PrintersUiState(
        printers = listOf(
            Printer(id = "X1A", name = "Workshop X1", serial = "X1A", configured = true, state = "connected", model = "X1C"),
            Printer(id = "DEF456", name = "Spare P1S", serial = "DEF456", model = "P1S", ip = "192.0.2.41"),
        ),
        loaded = true,
    )

    @Test fun foundPrintersAreTilesWithAnAddThatNamesThePrinter() {
        themed { Column { PrinterLists(printersState(), false, {}, {}, {}, { _, _ -> }) } }
        rule.waitForIdle()
        rule.onNodeWithContentDescription("Open Workshop X1").assertExists()
        rule.onNodeWithContentDescription("Add Bambu Lab P1S").assertExists()
    }

    @Test fun foundPrintersStayRowsInAnotherLook() {
        themed(Look.Console) { Column { PrinterLists(printersState(), false, {}, {}, {}, { _, _ -> }) } }
        rule.waitForIdle()
        assertEquals(0, rule.onAllNodesWithContentDescription("Add Bambu Lab P1S").fetchSemanticsNodes().size)
    }

    private class FakeLoad(val printers: List<Printer>) : LoadBackend {
        override suspend fun printers() = printers
        override suspend fun printer(id: String) = PrinterDetail(printers.first { it.id == id })
        override suspend fun load(id: String, label: String, spoolId: Int, dryRun: Boolean) = LoadResult(slot = LoadSlot("A2", 0, 1))
    }

    @Test fun theLoadPrintersAreTilesAndANamedChoice() {
        val x1 = Printer(id = "X1A", name = "Workshop X1", model = "X1C", serial = "X1A", configured = true, state = "connected")
        val vm = LoadPrintersViewModel(
            FakeLoad(listOf(x1, x1.copy(id = "X2", name = "Garage X1"), Printer(id = "V2", name = "Garage Voron", serial = "V2", configured = true, state = "offline", family = "klipper"))),
        )
        themed { LoadPrintersScreen(vm, null, onPick = { _, _ -> }, onOpenPrinters = {}, onPairAgain = {}) }
        rule.waitForIdle()
        rule.onNodeWithContentDescription("Choose Workshop X1").assertExists()
        rule.onNodeWithContentDescription("Choose Garage X1").assertExists()
        // the one that cannot take the load is a dimmed tile, not a button that works
        rule.onNodeWithContentDescription("Choose Garage Voron").assertExists()
    }

    private class FakeHistory(val records: List<HistorySummary>) : HistoryBackend {
        override suspend fun list() = IntakeHistory(20, records.size, null, true, records)
        override suspend fun record(id: String) = error("not used")
        override suspend fun photo(id: String, n: Int): ByteArray = error("not used")
        override suspend fun revise(id: String, note: String, item: Int?) = error("not used")
        override suspend fun applyProposal(id: String, proposal: String) = error("not used")
        override suspend fun applyValues(id: String, item: Int, values: JsonObject) = error("not used")
        override suspend fun undo(id: String, revision: Int) = error("not used")
    }

    private fun history() {
        val record = HistorySummary(
            id = "a1", at = "2026-11-15T10:00:00Z", source = "web", photos = 0,
            spools = listOf(HistorySpool(214, 41, "Polymaker", "PolyTerra Charcoal", "PLA")),
        )
        val vm = HistoryListViewModel(FakeHistory(listOf(record)))
        themed { HistoryListScreen(vm, null, onOpen = {}, onPairAgain = {}) }
        rule.waitForIdle()
    }

    @Test fun theRecordsAreTilesInPalette() {
        history()
        rule.onNode(SemanticsMatcher("an Open button that names its record") {
            it.config.getOrNull(SemanticsProperties.ContentDescription)?.any { d -> d.startsWith("Open ") && d.contains("Polymaker") } == true
        }).assertExists()
    }

    @Test fun theRecordsAreRowsInAnotherLook() {
        val vm = HistoryListViewModel(
            FakeHistory(listOf(HistorySummary(id = "a1", spools = listOf(HistorySpool(214, 41, "Polymaker", "PolyTerra Charcoal", "PLA"))))),
        )
        themed(Look.Console) { HistoryListScreen(vm, null, onOpen = {}, onPairAgain = {}) }
        rule.waitForIdle()
        assertEquals(
            0,
            rule.onAllNodes(SemanticsMatcher("an Open button") {
                it.config.getOrNull(SemanticsProperties.ContentDescription)?.any { d -> d.startsWith("Open ") } == true
            }).fetchSemanticsNodes().size,
        )
    }

    @Test fun everyTileButtonNamesItsItem() {
        val spool = spool(620.0)
        themed { SwCollection(listOf(spool), tile = { _, s -> SpoolTile(s, onClick = {}) }) { _, _ -> } }
        rule.waitForIdle()
        rule.onNodeWithContentDescription("Open Polymaker PolyTerra Charcoal").assertExists()
    }
}
