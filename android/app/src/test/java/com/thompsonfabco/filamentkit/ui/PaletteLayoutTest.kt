package com.thompsonfabco.filamentkit.ui

import android.os.Build
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertWidthIsAtLeast
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.ui.components.SwCollection
import com.thompsonfabco.filamentkit.ui.components.SwLazyCollection
import com.thompsonfabco.filamentkit.ui.components.SwNav
import com.thompsonfabco.filamentkit.ui.components.SwPills
import com.thompsonfabco.filamentkit.ui.components.TILE_MIN_WIDTH
import com.thompsonfabco.filamentkit.ui.components.navLayout
import com.thompsonfabco.filamentkit.ui.components.tileColumns
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.CollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.DetailStyle
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.NavStyle
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTokens
import com.thompsonfabco.filamentkit.ui.theme.WindowClass
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/**
 * S6.7, the Palette on Android: its profile (`Pills`, `Tiles`, `Sheet`) and font, what the shell and the collections draw
 * for it at each window width, and that Console and Workbench are drawn as they were. The screens' own semantics run in
 * [PaletteScreenSemanticsTest] (AUT-8).
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h800dp")
class PaletteLayoutTest {
    @get:Rule val rule = createComposeRule()

    private var look by mutableStateOf(Look.Palette)
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

    @Test fun thePaletteProfileIsPillsTilesSheetInTheDefaultFont() {
        val tokens = SpoolwardenTokens.of(Look.Palette)
        val p = tokens.profile
        assertEquals(Triple(NavStyle.Pills, CollectionStyle.Tiles, DetailStyle.Sheet), Triple(p.nav, p.collection, p.detail))
        assertEquals("08 14: Android has no rounded system font, the default family stands in", FontFamily.Default, tokens.type.sans)
        val w = SpoolwardenTokens.of(Look.Workbench).profile
        assertEquals(Triple(NavStyle.Sidebar, CollectionStyle.Cards, DetailStyle.Card), Triple(w.nav, w.collection, w.detail))
    }

    @Test fun theNavigationFormFollowsTheProfileAndTheWindow() {
        // Pills: the bar on a phone; wider, no side navigation (the pill row stands in its place)
        assertEquals(NavigationSuiteType.NavigationBar, navLayout(true, WindowClass.Phone, NavStyle.Pills))
        assertEquals(NavigationSuiteType.None, navLayout(true, WindowClass.Tablet, NavStyle.Pills))
        assertEquals(NavigationSuiteType.None, navLayout(true, WindowClass.Desktop, NavStyle.Pills))
        assertEquals(NavigationSuiteType.None, navLayout(false, WindowClass.Phone, NavStyle.Pills))
        // Console's rail and Workbench's sidebar are as they were
        assertEquals(NavigationSuiteType.NavigationRail, navLayout(true, WindowClass.Desktop, NavStyle.Rail))
        assertEquals(NavigationSuiteType.NavigationRail, navLayout(true, WindowClass.Tablet, NavStyle.Sidebar))
        assertEquals(NavigationSuiteType.NavigationDrawer, navLayout(true, WindowClass.Desktop, NavStyle.Sidebar))
    }

    private fun pillsOnly(selected: Tab? = Tab.Spools, visible: Boolean = true) {
        themed {
            Column {
                SwPills(selected, visible, onSelect = {})
                Box(Modifier.fillMaxSize())
            }
        }
    }

    /** The five pills at 48 dp or more, the current one selected, and AUT-8's findings none, in light and dark at font scale 1 and 2. */
    private fun auditPills() {
        pillsOnly()
        for (isDark in listOf(false, true)) {
            for (scale in listOf(1f, 2f)) {
                dark = isDark
                fontScale = scale
                rule.waitForIdle()
                for (tab in Tab.entries) {
                    val item = rule.onNodeWithText(text(tab.label))
                    item.assertExists().assertHeightIsAtLeast(48.dp).assertWidthIsAtLeast(48.dp)
                    if (tab == Tab.Spools) item.assertIsSelected()
                }
                val findings = SemanticsAudit.findings(
                    rule.onRoot().fetchSemanticsNode(), rule.onRoot(useUnmergedTree = true).fetchSemanticsNode(), density, null,
                )
                assertEquals("dark=$isDark fontScale=$scale", emptyList<String>(), findings)
            }
        }
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun onATabletThePillsAreARowUnderTheTopBar() {
        auditPills()
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h700dp")
    @Test fun onExpandedWidthThePillsAreARowToo() {
        auditPills()
        val tops = Tab.entries.map { rule.onNodeWithText(text(it.label)).fetchSemanticsNode().boundsInRoot.top }
        assertEquals("one line of pills", 1, tops.distinct().size)
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun aPillIsAtLeastControlHigh() {
        pillsOnly()
        rule.waitForIdle()
        val control = SpoolwardenTokens.of(Look.Palette).sizes.control.value
        for (tab in Tab.entries) {
            val h = rule.onNodeWithText(text(tab.label)).fetchSemanticsNode().size.height / density
            assertTrue("${tab.name} is at least --ctl ($control dp) high: $h dp", h >= control - 0.5f)
        }
    }

    @Test fun onAPhoneThereAreNoPills() {
        pillsOnly()
        rule.waitForIdle()
        assertEquals("no pill row on a phone", 0, rule.onAllNodesWithText(text(Tab.Spools.label)).fetchSemanticsNodes().size)
    }

    @Test fun onAPhoneTheBottomBarIsTheNavigationInPalette() {
        themed { SwNav(selected = Tab.Spools, visible = true, onSelect = {}) { Box(Modifier.fillMaxSize()) } }
        rule.waitForIdle()
        val item = rule.onNodeWithText(text(Tab.Spools.label)).assertIsSelected().fetchSemanticsNode()
        assertTrue("a bar item, not a pill: ${item.size.width / density} dp", item.size.width / density < 200f)
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun onATabletTheShellHasNoRailInPaletteAndConsoleKeepsIt() {
        themed { SwNav(selected = Tab.Spools, visible = true, onSelect = {}) { Box(Modifier.fillMaxSize()) } }
        rule.waitForIdle()
        assertEquals("Palette: no rail beside the content", 0, rule.onAllNodesWithText(text(Tab.Spools.label)).fetchSemanticsNodes().size)
        look = Look.Console
        rule.waitForIdle()
        assertEquals("Console: its rail", 1, rule.onAllNodesWithText(text(Tab.Spools.label)).fetchSemanticsNodes().size)
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun pillsAreDrawnOnlyInPaletteAndOnlyWhileTheNavigationIsShown() {
        pillsOnly()
        rule.waitForIdle()
        assertEquals("Palette: the pills", 1, rule.onAllNodesWithText(text(Tab.Spools.label)).fetchSemanticsNodes().size)
        look = Look.Workbench
        rule.waitForIdle()
        assertEquals("Workbench: none", 0, rule.onAllNodesWithText(text(Tab.Spools.label)).fetchSemanticsNodes().size)
        look = Look.Console
        rule.waitForIdle()
        assertEquals("Console: none", 0, rule.onAllNodesWithText(text(Tab.Spools.label)).fetchSemanticsNodes().size)
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun pillsAreHiddenWhileTheNavigationIsHidden() {
        pillsOnly(selected = null, visible = false)
        rule.waitForIdle()
        assertEquals(0, rule.onAllNodesWithText(text(Tab.Spools.label)).fetchSemanticsNodes().size)
    }

    @Test fun tileColumnsFollowThePhoneRuleAndTheMinimumWidth() {
        val gap = 16.dp
        // a phone: one column below 420 dp, two from it
        assertEquals(1, tileColumns(411.dp, gap, WindowClass.Phone))
        assertEquals(1, tileColumns(419.dp, gap, WindowClass.Phone))
        assertEquals(2, tileColumns(420.dp, gap, WindowClass.Phone))
        assertEquals(2, tileColumns(599.dp, gap, WindowClass.Phone))
        // wider: as many of at least TILE_MIN_WIDTH as fit, one at the least
        assertEquals(1, tileColumns(200.dp, gap, WindowClass.Tablet))
        assertEquals(2, tileColumns(464.dp, gap, WindowClass.Tablet))
        assertEquals(2, tileColumns(479.dp, gap, WindowClass.Tablet))
        assertEquals(3, tileColumns(720.dp, gap, WindowClass.Tablet))
        assertEquals(4, tileColumns(1000.dp, gap, WindowClass.Desktop))
        assertEquals(224.dp, TILE_MIN_WIDTH)
    }

    private fun boundsOf(tag: String) = rule.onNodeWithTag(tag).fetchSemanticsNode().boundsInRoot

    /** Six items: how many sit on the first line. */
    private fun onTheFirstLine(): Int {
        val first = boundsOf("row0")
        return (0 until 6).count { boundsOf("row$it").top == first.top }
    }

    private fun sixTiles() = themed {
        SwCollection(List(6) { it }) { i, _ -> Box(Modifier.fillMaxWidth().height(rowHeight).testTag("row$i")) { Text("item $i") } }
    }

    private fun sixLazyTiles() {
        val names = List(6) { "n$it" }
        themed {
            SwLazyCollection(names, key = { it }) { Box(Modifier.fillMaxWidth().height(rowHeight).testTag("row${names.indexOf(it)}")) { Text(it) } }
        }
    }

    @Test fun onAPhoneBelow420TilesAreOneColumn() {
        sixTiles()
        rule.waitForIdle()
        assertEquals(1, onTheFirstLine())
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w480dp-h800dp")
    @Test fun onAWiderPhoneTilesAreTwoColumnsWhereWorkbenchCardsAreOne() {
        sixTiles()
        rule.waitForIdle()
        assertEquals(2, onTheFirstLine())
        look = Look.Workbench
        rule.waitForIdle()
        assertEquals("Workbench: one card to a line there", 1, onTheFirstLine())
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w800dp-h900dp")
    @Test fun onATabletTilesFillTheWidthWithColumnsOfTheMinimum() {
        sixTiles()
        rule.waitForIdle()
        val line = onTheFirstLine()
        assertEquals("three tiles of at least 224 dp fit 800 dp", 3, line)
        val width = boundsOf("row0").width / density
        assertTrue("a tile is at least ${TILE_MIN_WIDTH.value} dp wide: $width dp", width >= TILE_MIN_WIDTH.value)
        val across = (boundsOf("row1").left - boundsOf("row0").right) / density
        assertEquals("the theme's gap between the tiles", SpoolwardenTokens.of(Look.Palette).sizes.gap.value, across, 0.5f)
        look = Look.Console
        rule.waitForIdle()
        assertEquals("Console: one column", 1, onTheFirstLine())
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h700dp")
    @Test fun onExpandedWidthTilesAreMoreToALineThanWorkbenchCards() {
        sixTiles()
        rule.waitForIdle()
        val tiles = onTheFirstLine()
        look = Look.Workbench
        rule.waitForIdle()
        val cards = onTheFirstLine()
        assertTrue("more tiles ($tiles) than cards ($cards) to a line", tiles > cards)
    }

    @Test fun tilesAreSeparateAndTheTableIsOneBlock() {
        themed {
            SwCollection(listOf("a", "b", "c")) { i, _ -> Box(Modifier.fillMaxWidth().height(rowHeight).testTag("row$i")) { Text("item $i") } }
        }
        rule.waitForIdle()
        val gap = SpoolwardenTokens.of(Look.Palette).sizes.gap.value
        fun between() = (boundsOf("row1").top - boundsOf("row0").bottom) / density
        assertEquals("Palette: a tile of its own, the theme's gap apart", gap, between(), 0.5f)
        look = Look.Console
        rule.waitForIdle()
        assertEquals("Console: one block, a hairline between", 1f, between(), 0.5f)
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h700dp")
    @Test fun onExpandedWidthTheLongListIsAGridOfTilesToo() {
        sixLazyTiles()
        rule.waitForIdle()
        assertTrue("more than two tiles to a line: ${onTheFirstLine()}", onTheFirstLine() > 2)
        look = Look.Console
        rule.waitForIdle()
        assertEquals("Console: one column", 1, onTheFirstLine())
    }

    @Test fun theLongListIsOneColumnOnANarrowPhone() {
        sixLazyTiles()
        rule.waitForIdle()
        assertEquals(1, onTheFirstLine())
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w480dp-h800dp")
    @Test fun theLongListIsTwoColumnsOnAWiderPhone() {
        sixLazyTiles()
        rule.waitForIdle()
        assertEquals(2, onTheFirstLine())
    }
}
