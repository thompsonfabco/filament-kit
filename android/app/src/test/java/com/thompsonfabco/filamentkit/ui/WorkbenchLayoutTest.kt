package com.thompsonfabco.filamentkit.ui

import android.os.Build
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Text
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteType
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsNode
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertWidthIsAtLeast
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.hasAnyDescendant
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.net.LoadResult
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.ui.components.CARD_MIN_WIDTH
import com.thompsonfabco.filamentkit.ui.components.SwCollection
import com.thompsonfabco.filamentkit.ui.components.SwLazyCollection
import com.thompsonfabco.filamentkit.ui.components.SwNav
import com.thompsonfabco.filamentkit.ui.components.cardColumns
import com.thompsonfabco.filamentkit.ui.components.navLayout
import com.thompsonfabco.filamentkit.ui.printers.PickBackend
import com.thompsonfabco.filamentkit.ui.printers.PickSpoolScreen
import com.thompsonfabco.filamentkit.ui.printers.PickSpoolViewModel
import com.thompsonfabco.filamentkit.ui.search.SearchScreen
import com.thompsonfabco.filamentkit.ui.search.SearchViewModel
import com.thompsonfabco.filamentkit.ui.spool.FakeSpoolBackend
import com.thompsonfabco.filamentkit.ui.spool.LinkFindScreen
import com.thompsonfabco.filamentkit.ui.spool.LinkFindViewModel
import com.thompsonfabco.filamentkit.ui.spool.LoadBackend
import com.thompsonfabco.filamentkit.ui.spool.LoadPrintersScreen
import com.thompsonfabco.filamentkit.ui.spool.LoadPrintersViewModel
import com.thompsonfabco.filamentkit.ui.spool.spoolJson
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.CollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.DetailStyle
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.NavStyle
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTokens
import com.thompsonfabco.filamentkit.ui.theme.WindowClass
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/**
 * S6.5, the Workbench on Android: its profile (`Sidebar`, `Cards`, `Card`), what the shell and the collections draw for it
 * at each window width, and that Console is drawn as it was. The screens' own semantics run in
 * [WorkbenchScreenSemanticsTest] (AUT-8).
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h800dp")
class WorkbenchLayoutTest {
    @get:Rule val rule = createComposeRule()

    private var look by mutableStateOf(Look.Workbench)
    private var dark by mutableStateOf(false)
    private var fontScale by mutableStateOf(1f)
    private var density = 1f
    private val rowHeight = 48.dp

    private fun text(@StringRes id: Int) = RuntimeEnvironment.getApplication().getString(id)

    private fun themed(content: @Composable () -> Unit) = rule.setContent {
        val base = LocalDensity.current
        density = base.density
        CompositionLocalProvider(LocalDensity provides Density(base.density, fontScale)) {
            SpoolwardenTheme(look, if (dark) Appearance.Dark else Appearance.Light, content)
        }
    }

    @Test fun theWorkbenchProfileIsSidebarCardsCard() {
        val p = SpoolwardenTokens.of(Look.Workbench).profile
        assertEquals(Triple(NavStyle.Sidebar, CollectionStyle.Cards, DetailStyle.Card), Triple(p.nav, p.collection, p.detail))
        val c = SpoolwardenTokens.of(Look.Console).profile
        assertEquals(Triple(NavStyle.Rail, CollectionStyle.Table, DetailStyle.Inline), Triple(c.nav, c.collection, c.detail))
    }

    @Test fun theNavigationFormFollowsTheProfileAndTheWindow() {
        // Sidebar: bar on a phone, rail on a tablet, drawer on expanded width
        assertEquals(NavigationSuiteType.NavigationBar, navLayout(true, WindowClass.Phone, NavStyle.Sidebar))
        assertEquals(NavigationSuiteType.NavigationRail, navLayout(true, WindowClass.Tablet, NavStyle.Sidebar))
        assertEquals(NavigationSuiteType.NavigationDrawer, navLayout(true, WindowClass.Desktop, NavStyle.Sidebar))
        // Console's rail is the rail at every wide width, as before
        assertEquals(NavigationSuiteType.NavigationBar, navLayout(true, WindowClass.Phone, NavStyle.Rail))
        assertEquals(NavigationSuiteType.NavigationRail, navLayout(true, WindowClass.Tablet, NavStyle.Rail))
        assertEquals(NavigationSuiteType.NavigationRail, navLayout(true, WindowClass.Desktop, NavStyle.Rail))
        assertEquals(NavigationSuiteType.None, navLayout(false, WindowClass.Desktop, NavStyle.Sidebar))
    }

    /** The five destinations at 48 dp or more, the current one selected, and AUT-8's findings none, in all four forms. */
    private fun auditNav(itemHeight: Dp = 48.dp) {
        themed { SwNav(selected = Tab.Spools, visible = true, onSelect = {}) { Box(Modifier.fillMaxSize()) } }
        for (isDark in listOf(false, true)) {
            for (scale in listOf(1f, 2f)) {
                dark = isDark
                fontScale = scale
                rule.waitForIdle()
                for (tab in Tab.entries) {
                    val item = rule.onNodeWithText(text(tab.label))
                    item.assertExists().assertHeightIsAtLeast(itemHeight).assertWidthIsAtLeast(48.dp)
                    if (tab == Tab.Spools) item.assertIsSelected()
                }
                val findings = SemanticsAudit.findings(
                    rule.onRoot().fetchSemanticsNode(), rule.onRoot(useUnmergedTree = true).fetchSemanticsNode(), density, null,
                )
                assertEquals("dark=$isDark fontScale=$scale", emptyList<String>(), findings)
            }
        }
    }

    private fun spoolsItemWidthDp(): Float = rule.onNodeWithText(text(Tab.Spools.label)).fetchSemanticsNode().size.width / density

    @Test fun onAPhoneTheWorkbenchHasTheBottomBar() {
        auditNav()
        assertTrue("a bar item is not a drawer row: ${spoolsItemWidthDp()} dp", spoolsItemWidthDp() < 200f)
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun onATabletTheWorkbenchHasTheRail() {
        auditNav()
        assertTrue("a rail item, not a drawer row: ${spoolsItemWidthDp()} dp", spoolsItemWidthDp() < 120f)
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h700dp")
    @Test fun onExpandedWidthTheWorkbenchHasTheSidebarDrawer() {
        // `--ctl` (44 dp) high: the audit accepts it as it does Material's 44 dp controls, in a 48 dp slot
        auditNav(itemHeight = SpoolwardenTokens.of(Look.Workbench).sizes.control)
        val side = SpoolwardenTokens.of(Look.Workbench).sizes.sideW.value
        val width = spoolsItemWidthDp()
        assertTrue("a drawer row nearly as wide as the sidebar ($side dp): $width dp", width > side - 40f && width <= side)
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h700dp")
    @Test fun onExpandedWidthConsoleKeepsItsRail() {
        look = Look.Console
        auditNav()
        assertTrue("Console's rail item: ${spoolsItemWidthDp()} dp", spoolsItemWidthDp() < 120f)
    }

    private fun gapBetweenRowsDp(): Float {
        val first = rule.onNodeWithTag("row0").fetchSemanticsNode().boundsInRoot
        val second = rule.onNodeWithTag("row1").fetchSemanticsNode().boundsInRoot
        return (second.top - first.bottom) / density
    }

    @Test fun cardsAreSeparateCardsAndTheTableIsOneBlock() {
        themed {
            SwCollection(listOf("a", "b", "c")) { i, _ -> Box(Modifier.fillMaxWidth().height(rowHeight).testTag("row$i")) { Text("item $i") } }
        }
        rule.waitForIdle()
        val gap = SpoolwardenTokens.of(Look.Workbench).sizes.gap.value
        assertEquals("Workbench: a card of its own, the theme's gap apart", gap, gapBetweenRowsDp(), 0.5f)
        look = Look.Console
        rule.waitForIdle()
        assertEquals("Console: one block, a hairline between", 1f, gapBetweenRowsDp(), 0.5f)
    }

    @Test fun theLongListFollowsTheSameTwoForms() {
        val names = listOf("a", "b", "c")
        themed {
            SwLazyCollection(names, key = { it }) { Box(Modifier.fillMaxWidth().height(rowHeight).testTag("row${names.indexOf(it)}")) { Text(it) } }
        }
        rule.waitForIdle()
        assertEquals(SpoolwardenTokens.of(Look.Workbench).sizes.gap.value, gapBetweenRowsDp(), 0.5f)
        look = Look.Console
        rule.waitForIdle()
        assertEquals(1f, gapBetweenRowsDp(), 0.5f)
    }

    @Test fun theSpoolResultsAreCardsInTheWorkbench() {
        fun spool(id: Int, name: String) = buildJsonObject {
            put("id", id)
            put("remaining_weight", 640.0)
            put("filament", buildJsonObject {
                put("name", name)
                put("material", "PLA")
                put("color_hex", "2B2B2E")
                put("vendor", buildJsonObject { put("name", "Example Filaments") })
            })
        }
        val vm = SearchViewModel { _, _ -> listOf(spool(1, "PolyTerra Charcoal"), spool(2, "PolyTerra Sage")) }
        themed { SearchScreen(vm, onOpenSpool = {}, onPairAgain = {}) }
        vm.setQuery("pla")
        vm.search()
        rule.waitForIdle()
        fun distanceDp(): Float {
            val a = rule.onNodeWithText("Example Filaments PolyTerra Charcoal").fetchSemanticsNode().boundsInRoot
            val b = rule.onNodeWithText("Example Filaments PolyTerra Sage").fetchSemanticsNode().boundsInRoot
            return (b.top - a.top) / density
        }
        val workbench = distanceDp()
        look = Look.Console
        rule.waitForIdle()
        val console = distanceDp()
        val gap = SpoolwardenTokens.of(Look.Workbench).sizes.gap.value
        assertTrue("Workbench rows are a gap apart ($workbench dp), Console's a hairline ($console dp)", workbench - console >= gap - 2f)
    }

    private fun labelStyle(tab: Tab) = rule.onNodeWithText(text(tab.label)).fetchSemanticsNode().let { node ->
        val results = mutableListOf<TextLayoutResult>()
        node.config[SemanticsActions.GetTextLayoutResult].action?.invoke(results)
        results.first().layoutInput.style
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h700dp")
    @Test fun theDrawerItemsAreControlHighWithTextLabelsOfWeight600() {
        themed { SwNav(selected = Tab.Spools, visible = true, onSelect = {}) { Box(Modifier.fillMaxSize()) } }
        rule.waitForIdle()
        val tokens = SpoolwardenTokens.of(Look.Workbench)
        for (tab in Tab.entries) {
            val item = rule.onNodeWithText(text(tab.label)).fetchSemanticsNode()
            assertEquals("${tab.name} is --ctl high", tokens.sizes.control.value, item.size.height / density, 0.5f)
        }
        val unselected = labelStyle(Tab.Printers)
        assertEquals("an unselected label is --text, not muted", tokens.light.text, unselected.color)
        assertEquals("--fs-m", tokens.type.m, unselected.fontSize)
        assertEquals("weight 600", FontWeight(600), unselected.fontWeight)
        assertEquals("the current label is --accent-text", tokens.light.accentText, labelStyle(Tab.Spools).color)
    }

    @Test fun cardColumnsFitTheMinimumWidthAndNeverFewerThanOne() {
        val gap = 16.dp
        assertEquals(1, cardColumns(200.dp, gap))
        assertEquals(1, cardColumns(411.dp, gap))
        assertEquals(1, cardColumns(591.dp, gap))
        assertEquals(2, cardColumns(592.dp, gap))
        assertEquals(3, cardColumns(1000.dp, gap))
    }

    private fun boundsOf(tag: String) = rule.onNodeWithTag(tag).fetchSemanticsNode().boundsInRoot

    /** Six cards: how many sit on the first line. */
    private fun cardsOnTheFirstLine(): Int {
        val first = boundsOf("row0")
        return (0 until 6).count { boundsOf("row$it").top == first.top }
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h700dp")
    @Test fun onExpandedWidthTheCardsAreAGridOfSeveralToALine() {
        themed {
            SwCollection(List(6) { it }) { i, _ -> Box(Modifier.fillMaxWidth().height(rowHeight).testTag("row$i")) { Text("item $i") } }
        }
        rule.waitForIdle()
        val line = cardsOnTheFirstLine()
        assertTrue("more than one card to a line: $line", line > 1)
        val width = boundsOf("row0").width / density
        assertTrue("a card is at least ${CARD_MIN_WIDTH.value} dp wide: $width dp", width >= CARD_MIN_WIDTH.value)
        assertTrue("the second line is below the first", boundsOf("row$line").top > boundsOf("row0").bottom)
        val across = (boundsOf("row1").left - boundsOf("row0").right) / density
        assertEquals("the theme's gap between the cards of a line", SpoolwardenTokens.of(Look.Workbench).sizes.gap.value, across, 0.5f)
        look = Look.Console
        rule.waitForIdle()
        assertEquals("Console: one column", 1, cardsOnTheFirstLine())
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h700dp")
    @Test fun onExpandedWidthTheLongListIsAGridToo() {
        val names = List(6) { "n$it" }
        themed {
            SwLazyCollection(names, key = { it }) { Box(Modifier.fillMaxWidth().height(rowHeight).testTag("row${names.indexOf(it)}")) { Text(it) } }
        }
        rule.waitForIdle()
        assertTrue("more than one card to a line: ${cardsOnTheFirstLine()}", cardsOnTheFirstLine() > 1)
        look = Look.Console
        rule.waitForIdle()
        assertEquals("Console: one column", 1, cardsOnTheFirstLine())
    }

    @Test fun onAPhoneTheCardsAreOneColumn() {
        themed {
            SwCollection(List(6) { it }) { i, _ -> Box(Modifier.fillMaxWidth().height(rowHeight).testTag("row$i")) { Text("item $i") } }
        }
        rule.waitForIdle()
        assertEquals(1, cardsOnTheFirstLine())
    }

    private fun spoolOf(id: Int, name: String) = buildJsonObject {
        put("id", id)
        put("remaining_weight", 640.0)
        put("filament", buildJsonObject {
            put("name", name)
            put("material", "PLA")
            put("color_hex", "2B2B2E")
            put("vendor", buildJsonObject { put("name", "Example Filaments") })
        })
    }

    /** The distance, in dp, from the top of the first of the two nodes with [text] to the top of the second. */
    private fun distanceBetween(text: String): Float {
        val nodes = rule.onAllNodesWithText(text, substring = true).fetchSemanticsNodes()
        assertTrue("two rows with \"$text\"", nodes.size >= 2)
        return (nodes[1].boundsInRoot.top - nodes[0].boundsInRoot.top) / density
    }

    /** Workbench: a card each, the theme's gap apart; Console: one block, a hairline between. */
    private fun assertCardsInWorkbenchAndBlockInConsole(text: String) {
        rule.waitForIdle()
        val workbench = distanceBetween(text)
        look = Look.Console
        rule.waitForIdle()
        val console = distanceBetween(text)
        val gap = SpoolwardenTokens.of(Look.Workbench).sizes.gap.value
        assertTrue("Workbench rows are a gap apart ($workbench dp), Console's a hairline ($console dp)", workbench - console >= gap - 2f)
    }

    @Test fun theLinkATagResultsAreCardsInTheWorkbench() {
        val backend = FakeSpoolBackend()
        backend.spools = listOf(spoolJson(212, sealed = true), spoolJson(213, sealed = true))
        val vm = LinkFindViewModel(backend)
        themed { LinkFindScreen(vm, "04A1B2", onPick = { _, _ -> }, onPairAgain = {}) }
        vm.setQuery("poly")
        vm.search()
        assertCardsInWorkbenchAndBlockInConsole("PolyTerra")
    }

    @Test fun thePickASpoolResultsAreCardsInTheWorkbench() {
        val backend = object : PickBackend {
            override suspend fun tag(uid: String): JsonObject? = null
            override suspend fun search(query: String, sealedOnly: Boolean) = listOf(spoolOf(1, "PolyTerra Charcoal"), spoolOf(2, "PolyTerra Sage"))
            override suspend fun load(printerId: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult = error("not used")
        }
        val vm = PickSpoolViewModel(backend, "ABC123", "A4")
        themed { PickSpoolScreen(vm, "Workshop X1", "A4", onLoaded = {}, onPairAgain = {}) }
        vm.setQuery("poly")
        vm.search()
        assertCardsInWorkbenchAndBlockInConsole("PolyTerra")
    }

    @Test fun theLoadIntoAPrinterListIsCardsInTheWorkbench() {
        val x1 = Printer(id = "X1A", name = "Workshop X1", model = "X1C", serial = "X1A", configured = true, state = "connected")
        val backend = object : LoadBackend {
            override suspend fun printers() = listOf(x1, x1.copy(id = "X1B", name = "Garage X1"), x1.copy(id = "X1C", name = "Study X1"))
            override suspend fun printer(id: String): PrinterDetail = error("not used")
            override suspend fun load(id: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult = error("not used")
        }
        val vm = LoadPrintersViewModel(backend)
        themed { LoadPrintersScreen(vm, null, onPick = { _, _ -> }, onOpenPrinters = {}, onPairAgain = {}) }
        assertCardsInWorkbenchAndBlockInConsole("X1")
    }

    /** The nearest ancestor of [node] that is a container: what a Surface (a card) makes of itself. */
    private fun surfaceOf(node: SemanticsNode): SemanticsNode? {
        var up = node.parent
        while (up != null) {
            if (up.config.any { it.key.name == "IsContainer" }) return up
            up = up.parent
        }
        return null
    }

    @Test fun consoleSearchResultsStayOneSurfaceAndWorkbenchGivesEachItsOwn() {
        val vm = SearchViewModel { _, _ -> listOf(spoolOf(1, "PolyTerra Charcoal"), spoolOf(2, "PolyTerra Sage")) }
        themed { SearchScreen(vm, onOpenSpool = {}, onPairAgain = {}) }
        vm.setQuery("pla")
        vm.search()
        rule.waitForIdle()
        fun groups(): Pair<SemanticsNode?, SemanticsNode?> {
            val a = rule.onNodeWithText("Example Filaments PolyTerra Charcoal").fetchSemanticsNode()
            val b = rule.onNodeWithText("Example Filaments PolyTerra Sage").fetchSemanticsNode()
            val field = rule.onNode(hasSetTextAction()).fetchSemanticsNode()
            val ga = surfaceOf(a)
            assertTrue("a result is in a surface of its own, below the search field", ga != null && ga.boundsInRoot.top >= field.boundsInRoot.bottom)
            return ga to surfaceOf(b)
        }
        val (a, b) = groups()
        assertTrue("Workbench: a surface for each card", a!!.id != b!!.id)
        look = Look.Console
        rule.waitForIdle()
        val (ca, cb) = groups()
        assertEquals("Console: one surface holds the results", ca!!.id, cb!!.id)
    }
}
