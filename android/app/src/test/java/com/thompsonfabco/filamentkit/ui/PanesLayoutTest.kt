package com.thompsonfabco.filamentkit.ui

import android.os.Build
import androidx.activity.ComponentActivity
import androidx.annotation.StringRes
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.material3.Text
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteType
import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.saveable.SaverScope
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toPixelMap
import androidx.compose.ui.input.InputMode
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalInputModeManager
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsFocused
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.click
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.ui.components.ROW_DIVIDER_TAG
import com.thompsonfabco.filamentkit.ui.components.SECTION_DIVIDER_TAG
import com.thompsonfabco.filamentkit.ui.components.SECTION_DOT_TAG
import com.thompsonfabco.filamentkit.ui.components.SectionDrill
import com.thompsonfabco.filamentkit.ui.components.SECTION_ROW_TAG
import com.thompsonfabco.filamentkit.ui.components.SECTION_TILE_TAG
import com.thompsonfabco.filamentkit.ui.components.SwCollection
import com.thompsonfabco.filamentkit.ui.components.SwLazyCollection
import com.thompsonfabco.filamentkit.ui.components.SwNav
import com.thompsonfabco.filamentkit.ui.components.SwSectionDrill
import com.thompsonfabco.filamentkit.ui.components.SwSectionList
import com.thompsonfabco.filamentkit.ui.components.SwSectionPane
import com.thompsonfabco.filamentkit.ui.components.contentInsetSides
import com.thompsonfabco.filamentkit.ui.components.navLayout
import com.thompsonfabco.filamentkit.ui.components.rememberSectionDrill
import com.thompsonfabco.filamentkit.ui.components.sectionPaneWidth
import com.thompsonfabco.filamentkit.ui.components.underSectionList
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.CollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.DetailStyle
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.NavStyle
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTokens
import com.thompsonfabco.filamentkit.ui.theme.WindowClass
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.GraphicsMode

/**
 * S6.9, Panes on Android: its profile (`List`, `Rows`, `Pane`), the section list and its drill-in on a phone, the pane
 * beside the content wider, the rows collection, and that the other looks are drawn as they were. The screens' own
 * semantics run in [PanesScreenSemanticsTest] (AUT-8); the section list's own AUT-8 run is here.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h800dp")
class PanesLayoutTest {
    @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

    private var look by mutableStateOf(Look.Panes)
    private var dark by mutableStateOf(false)
    private var fontScale by mutableStateOf(1f)
    private var density = 1f

    private fun text(@StringRes id: Int) = RuntimeEnvironment.getApplication().getString(id)

    private fun themed(content: @Composable () -> Unit) = rule.setContent {
        val base = LocalDensity.current
        density = base.density
        CompositionLocalProvider(LocalDensity provides Density(base.density, fontScale)) {
            SpoolwardenTheme(look, if (dark) Appearance.Dark else Appearance.Light, content)
        }
    }

    private val tokens = SpoolwardenTokens.of(Look.Panes)
    private fun colors() = if (dark) tokens.dark else tokens.light
    private fun bounds(tag: String) = rule.onNodeWithTag(tag, useUnmergedTree = true).fetchSemanticsNode().boundsInRoot

    private fun rowOf(tab: Tab) = rule.onNode(hasText(text(tab.label)) and SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Tab))

    @Test fun thePanesProfileIsListRowsPaneAndTheOtherLooksAreAsTheyWere() {
        val p = tokens.profile
        assertEquals(Triple(NavStyle.List, CollectionStyle.Rows, DetailStyle.Pane), Triple(p.nav, p.collection, p.detail))
        val c = SpoolwardenTokens.of(Look.Console).profile
        assertEquals(Triple(NavStyle.Rail, CollectionStyle.Table, DetailStyle.Inline), Triple(c.nav, c.collection, c.detail))
        val w = SpoolwardenTokens.of(Look.Workbench).profile
        assertEquals(Triple(NavStyle.Sidebar, CollectionStyle.Cards, DetailStyle.Card), Triple(w.nav, w.collection, w.detail))
        val l = SpoolwardenTokens.of(Look.Palette).profile
        assertEquals(Triple(NavStyle.Pills, CollectionStyle.Tiles, DetailStyle.Sheet), Triple(l.nav, l.collection, l.detail))
    }

    @Test fun theListIsTheNavigationSoNoBarRailOrDrawerIsDrawnAtAnyWidth() {
        for (window in WindowClass.entries) {
            assertEquals("Panes $window", NavigationSuiteType.None, navLayout(true, window, NavStyle.List))
        }
        assertEquals(NavigationSuiteType.None, navLayout(false, WindowClass.Phone, NavStyle.List))
        // the other looks are as they were
        assertEquals(NavigationSuiteType.NavigationBar, navLayout(true, WindowClass.Phone, NavStyle.Rail))
        assertEquals(NavigationSuiteType.NavigationBar, navLayout(true, WindowClass.Phone, NavStyle.Sidebar))
        assertEquals(NavigationSuiteType.NavigationBar, navLayout(true, WindowClass.Phone, NavStyle.Pills))
        assertEquals(NavigationSuiteType.NavigationRail, navLayout(true, WindowClass.Tablet, NavStyle.Rail))
        assertEquals(NavigationSuiteType.NavigationDrawer, navLayout(true, WindowClass.Desktop, NavStyle.Sidebar))
        assertEquals(NavigationSuiteType.None, navLayout(true, WindowClass.Desktop, NavStyle.Pills))
    }

    @Test fun aPhoneInPanesKeepsTheBottomInsetBecauseNoBarTakesIt() {
        assertEquals(
            WindowInsetsSides.Horizontal + WindowInsetsSides.Bottom,
            contentInsetSides(navVisible = true, phone = true, pills = false, list = true),
        )
        assertEquals(WindowInsetsSides.Horizontal, contentInsetSides(navVisible = true, phone = true, pills = false))
        assertEquals("a wider window: the pane takes the start", WindowInsetsSides.End + WindowInsetsSides.Bottom,
            contentInsetSides(navVisible = true, phone = false, pills = false, list = true))
    }

    @Test fun thePaneIsListWideOrFortyPercentOfTheWindowWhicheverIsLess() {
        assertEquals(240.dp, sectionPaneWidth(360.dp, 600.dp))
        assertEquals(280.dp, sectionPaneWidth(360.dp, 700.dp))
        assertEquals(360.dp, sectionPaneWidth(360.dp, 900.dp))
        assertEquals(360.dp, sectionPaneWidth(360.dp, 1000.dp))
        assertEquals("--list-w of Panes", 360f, tokens.sizes.listW.value)
    }

    // ----- the section list

    private fun sectionList(
        selected: Tab? = Tab.Spools, summaries: Map<Tab, String> = emptyMap(), update: Boolean = false, onSelect: (Tab) -> Unit = {},
    ) = themed {
        SwSectionList(selected, onSelect, Modifier.fillMaxSize(), summaries, update)
    }

    @Test fun theListHasTheTwoGroupsAndARowForEverySection() {
        sectionList()
        rule.waitForIdle()
        rule.onNodeWithText("EVERYDAY").assertExists()
        rule.onNodeWithText("SYSTEM").assertExists()
        for (tab in Tab.entries) rowOf(tab).assertExists()
        assertEquals(5, rule.onAllNodesWithTag(SECTION_ROW_TAG).fetchSemanticsNodes().size)
        rowOf(Tab.Spools).assertIsSelected()
        for (tab in Tab.entries - Tab.Spools) assertFalse(tab.name, rowOf(tab).fetchSemanticsNode().config[SemanticsProperties.Selected])
    }

    @Test fun aRowIsAtLeastFiftyTwoDpHighAtEveryFontScaleAndTheTileIsTwentyEight() {
        sectionList(summaries = mapOf(Tab.Printers to "2 connected"))
        for (scale in listOf(1f, 2f)) {
            fontScale = scale
            rule.waitForIdle()
            for (tab in Tab.entries) rowOf(tab).assertHeightIsAtLeast(52.dp)
        }
        val tile = rule.onAllNodesWithTag(SECTION_TILE_TAG, useUnmergedTree = true).fetchSemanticsNodes().first().boundsInRoot
        assertEquals("--s5 + --s1 wide", 28f, tile.width / density, 0.5f)
        assertEquals("--s5 + --s1 high", 28f, tile.height / density, 0.5f)
    }

    @Test fun theSummaryLineIsShownInTheRowAndIsPartOfItsName() {
        sectionList(summaries = mapOf(Tab.Printers to "2 connected · 1 offline"))
        rule.waitForIdle()
        rule.onNodeWithText("2 connected · 1 offline").assertExists()
        val node = rowOf(Tab.Printers).fetchSemanticsNode()
        val said = node.config[SemanticsProperties.Text].joinToString(" ") { it.text }
        assertTrue("the row reads its summary: $said", said.contains("2 connected · 1 offline"))
        assertEquals("a section with no summary draws no line", 1, rule.onAllNodesWithText("connected", substring = true).fetchSemanticsNodes().size)
    }

    @Test fun theUpdateDotNamesTheSettingsRow() {
        sectionList(update = true)
        rule.waitForIdle()
        rule.onNode(androidx.compose.ui.test.hasContentDescription(text(com.thompsonfabco.filamentkit.R.string.nav_settings_update))).assertExists()
    }

    @Test fun choosingARowSelectsThatSection() {
        var chosen: Tab? = null
        sectionList(onSelect = { chosen = it })
        rule.waitForIdle()
        rowOf(Tab.Printers).performClick()
        assertEquals(Tab.Printers, chosen)
    }

    private fun pixel(tag: String, x: Int, y: Int): Color =
        rule.onNodeWithTag(tag, useUnmergedTree = true).captureToImage().toPixelMap()[x, y]

    @Test fun theCurrentRowIsSurface3AndItsTileIsAccentWithTheOthersSurface3Tiles() {
        sectionList(selected = Tab.Spools)
        for (isDark in listOf(false, true)) {
            dark = isDark
            rule.waitForIdle()
            val c = colors()
            val image = rule.onRoot().captureToImage().toPixelMap()
            val rows = rule.onAllNodesWithTag(SECTION_ROW_TAG).fetchSemanticsNodes().sortedBy { it.boundsInRoot.top }
            val tiles = rule.onAllNodesWithTag(SECTION_TILE_TAG, useUnmergedTree = true).fetchSemanticsNodes().sortedBy { it.boundsInRoot.top }
            assertEquals(5, tiles.size)
            fun at(b: androidx.compose.ui.geometry.Rect, dx: Float, dy: Float) = image[(b.left + dx).toInt(), (b.top + dy).toInt()]
            // the row's own ground, in its top padding right of the name
            assertEquals("dark=$isDark: the current row", c.surface3, at(rows[1].boundsInRoot, rows[1].boundsInRoot.width / 2, 2f))
            assertEquals("dark=$isDark: another row", c.surface, at(rows[0].boundsInRoot, rows[0].boundsInRoot.width / 2, 2f))
            // the tile's ground at its left edge, clear of the icon
            assertEquals("dark=$isDark: the current tile", c.accent, at(tiles[1].boundsInRoot, 1f, tiles[1].boundsInRoot.height / 2))
            assertEquals("dark=$isDark: another tile", c.surface3, at(tiles[0].boundsInRoot, 1f, tiles[0].boundsInRoot.height / 2))
            assertEquals("dark=$isDark: the ground of the list", c.bg, image[2, image.height - 2])
        }
    }

    @Test fun theUpdateDotIsSeenOnTheCurrentAccentTileAndOnAPlainOne() {
        sectionList(selected = Tab.Settings, update = true)
        for (isDark in listOf(false, true)) {
            dark = isDark
            rule.waitForIdle()
            val c = colors()
            val dot = rule.onNodeWithTag(SECTION_DOT_TAG, useUnmergedTree = true).fetchSemanticsNode().boundsInRoot
            val image = rule.onRoot().captureToImage().toPixelMap()
            assertEquals("dark=$isDark: onAccent, ringed in accent, where the dot sits on the accent tile", c.onAccent,
                image[dot.center.x.toInt(), dot.center.y.toInt()])
        }
    }

    @Test fun theUpdateDotOnAnotherRowIsAccentText() {
        sectionList(selected = Tab.Spools, update = true)
        rule.waitForIdle()
        val dot = rule.onNodeWithTag(SECTION_DOT_TAG, useUnmergedTree = true).fetchSemanticsNode().boundsInRoot
        val image = rule.onRoot().captureToImage().toPixelMap()
        assertEquals(colors().accentText, image[dot.center.x.toInt(), dot.center.y.toInt()])
    }

    @Test fun theNameIsAtTheLabelWeightInTheBodySizeAndTheSummaryIsSmallAndMuted() {
        sectionList(summaries = mapOf(Tab.Printers to "2 connected"))
        rule.waitForIdle()
        fun style(t: String) = rule.onNodeWithText(t, useUnmergedTree = true).fetchSemanticsNode().let { n ->
            val r = mutableListOf<TextLayoutResult>()
            n.config[SemanticsActions.GetTextLayoutResult].action?.invoke(r)
            r.first().layoutInput.style
        }
        assertEquals("--fs-b", tokens.type.b, style("Spools").fontSize)
        assertEquals(tokens.type.weightLabel, style("Spools").fontWeight?.weight)
        assertEquals("--fs-s", tokens.type.s, style("2 connected").fontSize)
        assertEquals(tokens.light.muted, style("2 connected").color)
        assertEquals("--fs-xs", tokens.type.xs, style("EVERYDAY").fontSize)
        assertEquals(tokens.light.muted, style("EVERYDAY").color)
    }

    @Test fun theHairlinesStartWhereTheNameStarts() {
        sectionList()
        rule.waitForIdle()
        val dividers = rule.onAllNodesWithTag(SECTION_DIVIDER_TAG).fetchSemanticsNodes().sortedBy { it.boundsInRoot.top }
        assertEquals("three between the four rows of Everyday, none in System", 3, dividers.size)
        val name = rule.onNodeWithText(text(Tab.Spools.label), useUnmergedTree = true).fetchSemanticsNode().boundsInRoot
        assertEquals(name.left, dividers[0].boundsInRoot.left, 1f)
        assertEquals("a hairline is 1 dp", 1f, dividers[0].boundsInRoot.height / density, 0.5f)
    }

    @Test fun theGroupHeadingsAreHeadingsForReaders() {
        sectionList()
        rule.waitForIdle()
        for (name in listOf("EVERYDAY", "SYSTEM")) {
            assertTrue(name, rule.onNodeWithText(name, useUnmergedTree = true).fetchSemanticsNode().config.contains(SemanticsProperties.Heading))
        }
    }

    /** AUT-8 on the list: every row 48 dp or more, named, and nothing the audit finds, in light and dark at font scale 1 and 2. */
    private fun auditList() {
        sectionList(summaries = mapOf(Tab.Home to "All checks OK", Tab.Printers to "2 connected · 1 offline"))
        for (isDark in listOf(false, true)) {
            for (scale in listOf(1f, 2f)) {
                dark = isDark
                fontScale = scale
                rule.waitForIdle()
                for (tab in Tab.entries) rowOf(tab).assertExists().assertHeightIsAtLeast(48.dp)
                val findings = SemanticsAudit.findings(
                    rule.onRoot().fetchSemanticsNode(), rule.onRoot(useUnmergedTree = true).fetchSemanticsNode(), density, null,
                )
                assertEquals("dark=$isDark fontScale=$scale", emptyList<String>(), findings)
            }
        }
    }

    @Test fun aut8TheListOnAPhone() = auditList()

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun aut8TheListOnATablet() = auditList()

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h700dp")
    @Test fun aut8TheListOnExpandedWidth() = auditList()

    // ----- the shell

    private fun shell(selected: Tab? = Tab.Spools, onSelect: (Tab) -> Unit = {}) = themed {
        SwNav(selected, visible = true, onSelect = onSelect) { Box(Modifier.fillMaxSize().testTag("page")) { Text("the page") } }
    }

    @Test fun onAPhoneTheShellDrawsNoBarInPanes() {
        shell()
        rule.waitForIdle()
        assertEquals("no bottom bar: the list is a page of the shell's caller", 0, rule.onAllNodesWithText(text(Tab.Spools.label)).fetchSemanticsNodes().size)
        rule.onNodeWithText("the page").assertExists()
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun onATabletTheListIsAPaneBesideThePageAtFortyPercent() {
        shell()
        rule.waitForIdle()
        val page = bounds("page")
        val list = rule.onNodeWithText("EVERYDAY").fetchSemanticsNode().boundsInRoot
        assertTrue("the list is left of the page", list.right <= page.left + 1f)
        val root = rule.onRoot().fetchSemanticsNode().boundsInRoot
        val pane = sectionPaneWidth(tokens.sizes.listW, (root.width / density).dp)
        assertEquals("the page starts after the pane and its 1 dp edge", pane.value + 1f, page.left / density, 1f)
        assertEquals("700 dp: 40% is 280 dp", 280f, pane.value, 0.5f)
        for (tab in Tab.entries) rowOf(tab).assertExists()
        rowOf(Tab.Spools).assertIsSelected()
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h700dp")
    @Test fun onExpandedWidthThePaneIsListWideAndChoosingARowSelects() {
        var chosen: Tab? = null
        shell(onSelect = { chosen = it })
        rule.waitForIdle()
        val page = bounds("page")
        assertEquals("--list-w plus the 1 dp edge", tokens.sizes.listW.value + 1f, page.left / density, 1f)
        rowOf(Tab.Recent).performClick()
        assertEquals(Tab.Recent, chosen)
    }

    private fun pane(insets: WindowInsets) = themed {
        SwSectionPane(Tab.Spools, {}, insets = insets) { Box(Modifier.fillMaxSize()) }
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun thePaneGroundIsBgEvenWhereTheBarsPadItAndItsEdgeIsOneDpOfBorder() {
        pane(WindowInsets(bottom = 40.dp))
        for (isDark in listOf(false, true)) {
            dark = isDark
            rule.waitForIdle()
            val c = colors()
            val image = rule.onRoot().captureToImage().toPixelMap()
            val edge = (sectionPaneWidth(tokens.sizes.listW, 700.dp).value * density).toInt()
            val y = image.height - 5
            assertEquals("dark=$isDark: the pane's ground under the list, in the bottom inset", c.bg, image[edge / 2, y])
            assertEquals("dark=$isDark: the edge", c.border, image[edge + (density / 2).toInt(), y])
            assertEquals("dark=$isDark: the pane just before its edge", c.bg, image[edge - 1, y])
            assertTrue("dark=$isDark: the edge is not the pane's ground", image[edge + (density / 2).toInt(), y] != image[edge - 1, y])
        }
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun otherLooksKeepTheirNavigationAndDrawNoPane() {
        shell()
        look = Look.Console
        rule.waitForIdle()
        assertEquals("Console: its rail, no section headings", 0, rule.onAllNodesWithText("EVERYDAY").fetchSemanticsNodes().size)
        assertEquals(1, rule.onAllNodesWithText(text(Tab.Spools.label)).fetchSemanticsNodes().size)
        look = Look.Workbench
        rule.waitForIdle()
        assertEquals(0, rule.onAllNodesWithText("EVERYDAY").fetchSemanticsNodes().size)
        look = Look.Palette
        rule.waitForIdle()
        assertEquals(0, rule.onAllNodesWithText("EVERYDAY").fetchSemanticsNodes().size)
    }

    // ----- the drill-in on a phone

    private var behind = 0
    private var tabNow by mutableStateOf(Tab.Home)
    private var atRoot by mutableStateOf(true)
    private var active by mutableStateOf(true)
    private var inputMode: androidx.compose.ui.input.InputModeManager? = null
    private var view: android.view.View? = null
    private var taps = 0

    /** The screens (a node of the section shown), then the drill-in over them as the shell composes it. */
    private fun drillShell() = themed {
        inputMode = LocalInputModeManager.current
        view = LocalView.current
        val drill = rememberSectionDrill()
        BackHandler { behind++ }
        Box(Modifier.fillMaxSize()) {
            Box(Modifier.fillMaxSize().clickable { taps++ }.underSectionList(drill.showsPage(active, atRoot))) { Text("screen ${tabNow.name}") }
            SwSectionDrill(drill, active, atRoot, tabNow, { tabNow = it; drill.enter() })
        }
    }

    private fun pressBack() {
        rule.runOnUiThread { rule.activity.onBackPressedDispatcher.onBackPressed() }
        rule.waitForIdle()
    }

    @Test fun aPhoneOpensOnTheListWithTheScreensOutOfReach() {
        drillShell()
        rule.waitForIdle()
        for (tab in Tab.entries) rowOf(tab).assertExists()
        assertEquals("the screen under the list is hidden from touch, focus and readers", 0, rule.onAllNodesWithText("screen Home").fetchSemanticsNodes().size)
    }

    @Test fun choosingASectionDrillsInAndBackReturnsToTheListWithFocusOnItsRow() {
        drillShell()
        rule.waitForIdle()
        rowOf(Tab.Spools).performClick()
        rule.waitForIdle()
        assertEquals(Tab.Spools, tabNow)
        rule.onNodeWithText("screen Spools").assertExists()
        assertEquals("the list has gone", 0, rule.onAllNodesWithTag(SECTION_ROW_TAG).fetchSemanticsNodes().size)
        // focus is what a keyboard or switch user moves: the keyboard input mode
        rule.runOnUiThread { inputMode!!.requestInputMode(InputMode.Keyboard) }
        pressBack()
        for (tab in Tab.entries) rowOf(tab).assertExists()
        rowOf(Tab.Spools).assertIsFocused()
        assertEquals("the screens under it did not get Back", 0, behind)
    }

    @Test fun backOnTheListIsNotHandledByTheListSoItGoesOnToTheSystem() {
        drillShell()
        rule.waitForIdle()
        pressBack()
        // the list has no callback of its own: Back reaches whatever is next (in the app the NavHost, then the system)
        assertEquals(1, behind)
        for (tab in Tab.entries) rowOf(tab).assertExists()
    }

    @Test fun aTouchOnTheListNeverReachesTheScreenUnderIt() {
        drillShell()
        rule.waitForIdle()
        // below the last row, where nothing of the list is
        rule.onRoot().performTouchInput { click(Offset(width / 2f, height - 20f)) }
        rule.waitForIdle()
        assertEquals(0, taps)
        rowOf(Tab.Home).assertExists()
        // the same touch, with the list gone, reaches the screen: the test can see a tap
        active = false
        rule.waitForIdle()
        rule.onRoot().performTouchInput { click(Offset(width / 2f, height - 20f)) }
        rule.waitForIdle()
        assertEquals(1, taps)
    }

    private fun readerFocusAfterBack(touchExploration: Boolean): Boolean {
        val manager = shadowOf(RuntimeEnvironment.getApplication().getSystemService(android.view.accessibility.AccessibilityManager::class.java))
        manager.setEnabled(true)
        manager.setTouchExplorationEnabled(touchExploration)
        drillShell()
        rule.waitForIdle()
        rowOf(Tab.Spools).performClick()
        rule.waitForIdle()
        pressBack()
        rule.waitForIdle()
        val id = rowOf(Tab.Spools).fetchSemanticsNode().id
        return view!!.accessibilityNodeProvider!!.createAccessibilityNodeInfo(id)!!.isAccessibilityFocused
    }

    @Test fun afterBackTheRowGetsAccessibilityFocusWithAScreenReader() {
        assertTrue(readerFocusAfterBack(touchExploration = true))
    }

    @Test fun withoutAScreenReaderBackLeavesNoAccessibilityFocus() {
        assertFalse(readerFocusAfterBack(touchExploration = false))
    }

    @Test fun theDrillIsKeptAcrossARecreation() {
        val saver = SectionDrill.Saver
        val scope = SaverScope { true }
        for (open in listOf(true, false)) {
            val saved = with(saver) { scope.save(SectionDrill(open)) }
            assertEquals("open=$open", open, saver.restore(saved!!)!!.open)
        }
    }

    @Test fun backDeeperInASectionIsTheScreensOwn() {
        drillShell()
        rule.waitForIdle()
        rowOf(Tab.Printers).performClick()
        rule.waitForIdle()
        atRoot = false
        rule.waitForIdle()
        pressBack()
        assertEquals("a screen inside the section keeps its Back", 1, behind)
        assertEquals(0, rule.onAllNodesWithTag(SECTION_ROW_TAG).fetchSemanticsNodes().size)
    }

    @Test fun theDrillDoesNothingInAnotherLookOrAWiderWindow() {
        active = false
        drillShell()
        rule.waitForIdle()
        assertEquals(0, rule.onAllNodesWithTag(SECTION_ROW_TAG).fetchSemanticsNodes().size)
        rule.onNodeWithText("screen Home").assertExists()
        pressBack()
        assertEquals("Back is the screens'", 1, behind)
    }

    // ----- the rows collection

    private val rowHeight = 20.dp

    private fun threeRows(visual: androidx.compose.ui.unit.Dp = 0.dp) = themed {
        Box(Modifier.testTag("coll")) {
            SwCollection(listOf("a", "b", "c"), visual = visual) { i, _ ->
                Box(Modifier.padding(tokens.space.s3)) { Box(Modifier.fillMaxWidth().height(rowHeight).testTag("row$i")) { Text("item $i") } }
            }
        }
    }

    @Test fun rowsAreOneBlockEachAtLeastTheRowHeightWithAHairlineBetween() {
        threeRows()
        rule.waitForIdle()
        val min = tokens.sizes.row.value
        val rows = (0..2).map { bounds("row$it") }
        // the item's own padding (2 x --s3) is above and below it: 48 dp is the row, the rest is the hairline
        assertEquals("a row is --row high: 48 dp from one item's top to the next's, less the item and the hairline", min + 1f, (rows[1].top - rows[0].top) / density, 1.5f)
        assertEquals("a hairline between each pair", 2, rule.onAllNodesWithTag(ROW_DIVIDER_TAG).fetchSemanticsNodes().size)
        look = Look.Console
        rule.waitForIdle()
        val consoleStep = (bounds("row1").top - bounds("row0").top) / density
        assertTrue("Console has no minimum row height: step $consoleStep dp", consoleStep < min)
        assertEquals("Console draws no row hairlines", 0, rule.onAllNodesWithTag(ROW_DIVIDER_TAG).fetchSemanticsNodes().size)
    }

    @Test fun theContentIsSixteenDpFromTheEdgeAndTheHairlineStartsAtIt() {
        threeRows()
        rule.waitForIdle()
        val frame = bounds("coll")
        val s4 = tokens.space.s4.value
        assertEquals("--s4 from the block's edge", s4, (bounds("row0").left - frame.left) / density, 0.5f)
        val line = rule.onAllNodesWithTag(ROW_DIVIDER_TAG).fetchSemanticsNodes().first().boundsInRoot
        assertEquals("the hairline starts at the content", s4, (line.left - frame.left) / density, 0.5f)
    }

    @Test fun theHairlineIsInsetByTheVisualsWidth() {
        val visual = tokens.sizes.thumbS + tokens.space.s3
        threeRows(visual)
        rule.waitForIdle()
        val frame = bounds("coll")
        val line = rule.onAllNodesWithTag(ROW_DIVIDER_TAG).fetchSemanticsNodes().first().boundsInRoot
        assertEquals("--s4 and the visual", tokens.space.s4.value + visual.value, (line.left - frame.left) / density, 0.5f)
    }

    @Test fun theBlockIsSurfaceWithABorderLineInLightAndDark() {
        threeRows()
        for (isDark in listOf(false, true)) {
            dark = isDark
            rule.waitForIdle()
            val c = colors()
            val image = rule.onNodeWithTag("coll").captureToImage().toPixelMap()
            assertEquals("dark=$isDark: the block's ground", c.surface, image[image.width / 2, 1 + 2])
            val hairlines = rule.onAllNodesWithTag(ROW_DIVIDER_TAG).fetchSemanticsNodes().first().boundsInRoot
            val frame = bounds("coll")
            val full = rule.onRoot().captureToImage().toPixelMap()
            assertEquals("dark=$isDark: the hairline", c.border, full[(hairlines.left + 8).toInt(), (hairlines.top + hairlines.height / 2).toInt()])
            assertEquals("dark=$isDark: the block's border", c.border, full[(frame.left + frame.width / 2).toInt(), frame.top.toInt()])
        }
    }

    @Test fun theLongListIsRowsToo() {
        val names = List(3) { "n$it" }
        themed {
            Box(Modifier.testTag("coll")) {
                SwLazyCollection(names, key = { it }, visual = tokens.space.s5) {
                    Box(Modifier.fillMaxWidth().height(rowHeight).testTag("row${names.indexOf(it)}")) { Text(it) }
                }
            }
        }
        rule.waitForIdle()
        assertEquals(2, rule.onAllNodesWithTag(ROW_DIVIDER_TAG).fetchSemanticsNodes().size)
        val step = (bounds("row1").top - bounds("row0").top) / density
        assertTrue("a row is at least --row: step $step dp", step >= tokens.sizes.row.value)
        val line = rule.onAllNodesWithTag(ROW_DIVIDER_TAG).fetchSemanticsNodes().first().boundsInRoot
        assertEquals("the hairline is inset by --s4 and the visual", tokens.space.s4.value + tokens.space.s5.value, (line.left - bounds("coll").left) / density, 0.5f)
    }
}
