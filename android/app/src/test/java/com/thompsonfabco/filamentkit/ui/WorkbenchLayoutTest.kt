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
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertWidthIsAtLeast
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.ui.components.SwCollection
import com.thompsonfabco.filamentkit.ui.components.SwLazyCollection
import com.thompsonfabco.filamentkit.ui.components.SwNav
import com.thompsonfabco.filamentkit.ui.components.navLayout
import com.thompsonfabco.filamentkit.ui.search.SearchScreen
import com.thompsonfabco.filamentkit.ui.search.SearchViewModel
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.CollectionStyle
import com.thompsonfabco.filamentkit.ui.theme.DetailStyle
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.NavStyle
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTokens
import com.thompsonfabco.filamentkit.ui.theme.WindowClass
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
    private fun auditNav() {
        themed { SwNav(selected = Tab.Spools, visible = true, onSelect = {}) { Box(Modifier.fillMaxSize()) } }
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
        auditNav()
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
}
