package com.thompsonfabco.filamentkit.ui

import android.os.Build
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toPixelMap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertIsNotSelected
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.height
import androidx.compose.ui.platform.testTag
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.ui.components.PillMore
import com.thompsonfabco.filamentkit.ui.components.SwCollection
import com.thompsonfabco.filamentkit.ui.components.SwLazyCollection
import com.thompsonfabco.filamentkit.ui.components.SwPills
import com.thompsonfabco.filamentkit.ui.components.SwTopBar
import com.thompsonfabco.filamentkit.ui.components.contentInsetSides
import com.thompsonfabco.filamentkit.ui.components.tileColumns
import com.thompsonfabco.filamentkit.ui.printers.PrinterTile
import com.thompsonfabco.filamentkit.ui.printers.SLOT_RING_TAG
import com.thompsonfabco.filamentkit.ui.printers.SlotLook
import com.thompsonfabco.filamentkit.ui.spool.SPOOL_RING_TAG
import com.thompsonfabco.filamentkit.ui.spool.SpoolSummary
import com.thompsonfabco.filamentkit.ui.spool.SpoolTile
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTokens
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
 * S6.7 rework: the Palette tile (spool ring, prio 1 fields with their names, full width action), the colours, insets and
 * More of the pills, the rem widths that follow the font scale, and the tile columns of the web grid's rule.
 */
@OptIn(ExperimentalMaterial3Api::class)
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h800dp")
class PaletteTilesAndPillsTest {
    @get:Rule val rule = createComposeRule()

    private var look by mutableStateOf(Look.Palette)
    private var dark by mutableStateOf(false)
    private var fontScale by mutableStateOf(1f)
    private var density = 1f

    private fun themed(content: @Composable () -> Unit) = rule.setContent {
        val base = LocalDensity.current
        density = base.density
        CompositionLocalProvider(LocalDensity provides Density(base.density, fontScale)) {
            SpoolwardenTheme(look, if (dark) Appearance.Dark else Appearance.Light, content)
        }
    }

    private fun string(id: Int) = RuntimeEnvironment.getApplication().getString(id)

    private val spool = SpoolSummary(
        id = 214, brand = "Polymaker", name = "PolyTerra Charcoal", material = "PLA", colorHex = "2B2B2E", location = "Shelf A",
        remaining = 620.0, total = 1000.0, lot = "LOT-9", tag = "04:77",
    )
    private val printer = Printer(id = "P1", name = "Workshop X1", serial = "P1", state = "connected", model = "X1C")
    private val slots = listOf(SlotLook("#2B2B2E", false), SlotLook("#E0A030", false), SlotLook("", true))

    private fun bounds(tag: String) = rule.onNodeWithTag(tag, useUnmergedTree = true).fetchSemanticsNode().boundsInRoot

    /** The bounds of the button named [name]: the whole control, not its word. */
    private fun button(name: String) = rule.onNode(hasText(name) and hasClickAction()).fetchSemanticsNode().boundsInRoot

    private fun styleOf(text: String) = rule.onNodeWithText(text, useUnmergedTree = true).fetchSemanticsNode().let { node ->
        val results = mutableListOf<TextLayoutResult>()
        node.config[SemanticsActions.GetTextLayoutResult].action?.invoke(results)
        results.first().layoutInput.style
    }

    private fun spoolTile() = themed {
        SwCollection(
            listOf(spool),
            tile = { _, s -> SpoolTile(s, onClick = {}) },
        ) { _, s -> Box(Modifier.testTag("plain")) { Text(s.title) } }
    }

    // ----- the tile (item 1)

    @Test fun aSpoolTileHasTheLargeRingTheNamedFieldsAndAFullWidthAction() {
        spoolTile()
        rule.waitForIdle()
        val ring = bounds(SPOOL_RING_TAG)
        assertEquals("the large ring is --s7 x 2 (96 dp)", 96f, ring.width / density, 0.5f)
        rule.onNodeWithText("Material:", useUnmergedTree = true).assertExists()
        rule.onNodeWithText("PLA", useUnmergedTree = true).assertExists()
        rule.onNodeWithText("Location:", useUnmergedTree = true).assertExists()
        rule.onNodeWithText("Shelf A", useUnmergedTree = true).assertExists()
        rule.onNodeWithText("62 %", useUnmergedTree = true).assertExists()
        rule.onNodeWithText("Polymaker PolyTerra Charcoal", useUnmergedTree = true).assertExists()
        assertEquals("only the priority 1 fields: no lot, no tag", 0, rule.onAllNodesWithText("LOT-9", substring = true).fetchSemanticsNodes().size)
        val open = button("Open")
        val tile = rule.onNodeWithText("Polymaker PolyTerra Charcoal", useUnmergedTree = true).fetchSemanticsNode().boundsInRoot
        val pad = SpoolwardenTokens.of(Look.Palette).space.s4.value
        assertEquals("the action starts where the title does", tile.left, open.left, 1f)
        assertEquals("and runs to the tile's padding at the other side", rule.onRoot().fetchSemanticsNode().boundsInRoot.right - pad * density, open.right, 1f)
        assertTrue("the action is below the ring", open.top > ring.bottom)
    }

    @Test fun theTileTitleIsLargeAtTheLooksTitleWeight() {
        spoolTile()
        rule.waitForIdle()
        val tokens = SpoolwardenTokens.of(Look.Palette)
        val style = styleOf("Polymaker PolyTerra Charcoal")
        assertEquals(tokens.type.weightTitle, style.fontWeight?.weight)
        assertEquals("--fs-l", tokens.type.l, style.fontSize)
    }

    @Test fun anotherLookDrawsNoRingAndTheItemRow() {
        spoolTile()
        look = Look.Workbench
        rule.waitForIdle()
        assertEquals(0, rule.onAllNodesWithTag(SPOOL_RING_TAG, useUnmergedTree = true).fetchSemanticsNodes().size)
        rule.onNodeWithTag("plain").assertExists()
    }

    @Test fun aPrinterTileHasTheSlotRingsTheNamedFieldAndAFullWidthAction() {
        themed {
            SwCollection(listOf(printer), tile = { _, p -> PrinterTile(p, slots, onClick = {}) }) { _, _ -> Box(Modifier) {} }
        }
        rule.waitForIdle()
        assertEquals("one small ring per slot", 3, rule.onAllNodesWithTag(SLOT_RING_TAG, useUnmergedTree = true).fetchSemanticsNodes().size)
        assertEquals("small ring --s6", 32f, rule.onAllNodesWithTag(SLOT_RING_TAG, useUnmergedTree = true)[0].fetchSemanticsNode().boundsInRoot.width / density, 0.5f)
        rule.onNodeWithText("Slots:", useUnmergedTree = true).assertExists()
        rule.onNodeWithText("Workshop X1", useUnmergedTree = true).assertExists()
        val open = button("Open")
        val title = rule.onNodeWithText("Workshop X1", useUnmergedTree = true).fetchSemanticsNode().boundsInRoot
        val pad = SpoolwardenTokens.of(Look.Palette).space.s4.value
        assertEquals("the action starts where the title does", title.left, open.left, 1f)
        assertEquals("and runs to the tile's padding at the other side", rule.onRoot().fetchSemanticsNode().boundsInRoot.right - pad * density, open.right, 1f)
    }

    @Test fun theLazyGridDrawsTheTileToo() {
        themed { SwLazyCollection(listOf(spool), key = { it.id }, tile = { s -> SpoolTile(s, onClick = {}) }) { Box(Modifier) {} } }
        rule.waitForIdle()
        rule.onNodeWithTag(SPOOL_RING_TAG, useUnmergedTree = true).assertExists()
    }

    // ----- pill colours (item 2, 5)

    private fun pills(
        selected: Tab? = Tab.Spools, more: List<PillMore> = emptyList(), update: Boolean = false,
        insets: WindowInsets = WindowInsets(0, 0, 0, 0),
    ) = themed {
        Column(Modifier.fillMaxSize()) { SwPills(selected, true, onSelect = {}, settingsUpdate = update, more = more, insets = insets) }
    }

    private fun count(image: androidx.compose.ui.graphics.PixelMap, colour: Color): Int {
        var hits = 0
        for (x in 0 until image.width) for (y in 0 until image.height) if (image[x, y] == colour) hits++
        return hits
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun theCurrentPillIsTheSoftAccentNeverTheAccentFill() {
        pills()
        for (isDark in listOf(false, true)) {
            dark = isDark
            rule.waitForIdle()
            val tokens = SpoolwardenTokens.of(Look.Palette)
            val colors = if (isDark) tokens.dark else tokens.light
            val image = rule.onRoot().captureToImage().toPixelMap()
            assertTrue("dark=$isDark: the current pill is accentSoft", count(image, colors.accentSoft) > 0)
            assertEquals("dark=$isDark: accent is only the main button and a chosen segment", 0, count(image, colors.accent))
        }
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun theUnselectedIconsAreMutedAndTheLabelsTextAtTheLabelWeight() {
        pills(selected = Tab.Home)
        rule.waitForIdle()
        val colors = SpoolwardenTokens.of(Look.Palette).light
        val image = rule.onRoot().captureToImage().toPixelMap()
        assertTrue("an unselected icon is drawn in muted", count(image, colors.muted) > 0)
        val weight = SpoolwardenTokens.of(Look.Palette).type.weightLabel
        for (tab in Tab.entries) {
            assertEquals("${tab.name} label weight", weight, styleOf(string(tab.label)).fontWeight?.weight)
        }
    }

    // ----- insets (item 3)

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w900dp-h400dp")
    @Test fun thePillsKeepClearOfACutoutAtTheSides() {
        pills(insets = WindowInsets(left = 48.dp, top = 0.dp, right = 48.dp, bottom = 0.dp))
        rule.waitForIdle()
        val first = rule.onNodeWithText(string(Tab.Home.label)).fetchSemanticsNode().boundsInRoot
        assertTrue("the first pill starts after the 48 dp inset: ${first.left / density}", first.left >= 48f * density)
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun thePillRowSitsUnderTheTopBar() {
        themed {
            Column(Modifier.fillMaxSize()) {
                SwTopBar("Spools")
                SwPills(Tab.Spools, true, onSelect = {}, insets = WindowInsets(0, 0, 0, 0))
            }
        }
        rule.waitForIdle()
        val nodes = rule.onAllNodesWithText(string(Tab.Spools.label)).fetchSemanticsNodes()
        assertEquals("the top bar's title and the pill", 2, nodes.size)
        val (bar, pill) = nodes.map { it.boundsInRoot }.sortedBy { it.top }
        assertTrue("the pills are under the top bar", pill.top >= bar.bottom - 1f)
    }

    @Test fun theContentKeepsClearOfTheSidesOfTheDisplayWithPills() {
        val sides = WindowInsetsSides.Horizontal + WindowInsetsSides.Bottom
        assertEquals("pills on a tablet: no rail, so both sides and the bottom", sides, contentInsetSides(true, false, true))
        assertEquals("the rail takes the start", WindowInsetsSides.End + WindowInsetsSides.Bottom, contentInsetSides(true, false, false))
        assertEquals("a phone: the sides, the bar takes the bottom", WindowInsetsSides.Horizontal, contentInsetSides(true, true, true))
        assertEquals(
            "no navigation: every side", WindowInsetsSides.Horizontal + WindowInsetsSides.Vertical, contentInsetSides(false, false, true),
        )
    }

    // ----- More (item 4)

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun theMoreTabOpensTheMenuOfWhatTheRowDoesNotHold() {
        var opened = ""
        val more = listOf(
            PillMore("Appearance", com.thompsonfabco.filamentkit.R.drawable.sw_ic_half_circle, false) { opened = "Appearance" },
            PillMore("Updates", com.thompsonfabco.filamentkit.R.drawable.sw_ic_updates, false) { opened = "Updates" },
        )
        pills(more = more)
        rule.waitForIdle()
        rule.onNodeWithText("Updates").assertDoesNotExist()
        rule.onNodeWithText("More").assertExists().performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Appearance").assertExists()
        rule.onNodeWithText("Updates").performClick()
        assertEquals("Updates", opened)
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun whileAMoreEntryIsOpenMoreIsTheCurrentPillAndSaysWhich() {
        val more = listOf(PillMore("Appearance", com.thompsonfabco.filamentkit.R.drawable.sw_ic_half_circle, true) {})
        pills(selected = Tab.Settings, more = more)
        rule.waitForIdle()
        rule.onNodeWithContentDescription("More, current: Appearance").assertIsSelected()
        rule.onNodeWithText(string(Tab.Settings.label)).assertIsNotSelected()
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun withNothingForMoreThereIsNoMoreTab() {
        pills()
        rule.waitForIdle()
        assertEquals(0, rule.onAllNodesWithText("More").fetchSemanticsNodes().size)
    }

    // ----- the update dot (item 8)

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun theSettingsPillSaysWhenAnUpdateIsReady() {
        pills(update = true)
        rule.waitForIdle()
        rule.onNode(hasContentDescription(string(com.thompsonfabco.filamentkit.R.string.nav_settings_update))).assertExists()
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h900dp")
    @Test fun withNoUpdateTheSettingsPillIsJustSettings() {
        pills(update = false)
        rule.waitForIdle()
        rule.onNode(hasContentDescription(string(com.thompsonfabco.filamentkit.R.string.nav_settings_update))).assertDoesNotExist()
    }

    // ----- rem widths (item 6) and the column rule (item 7)

    private fun sixTiles() = themed {
        SwCollection(List(6) { it }) { i, _ -> Box(Modifier.testTag("row$i").height(48.dp).fillMaxWidth()) }
    }

    private fun onTheFirstLine(): Int {
        val first = bounds("row0")
        return (0 until 6).count { bounds("row$it").top == first.top }
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h900dp")
    @Test fun theTileWidthGrowsWithTheFontScale() {
        themed {
            SwCollection(List(6) { it }) { i, _ -> Box(Modifier.testTag("row$i").height(48.dp).fillMaxWidth()) }
        }
        rule.waitForIdle()
        assertEquals("1000 dp holds four 14 rem tiles at font scale 1", 4, onTheFirstLine())
        fontScale = 2f
        rule.waitForIdle()
        assertEquals("at font scale 2 a tile is 28 rem wide: two fit", 2, onTheFirstLine())
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h900dp")
    @Test fun theCardWidthGrowsWithTheFontScaleToo() {
        look = Look.Workbench
        themed {
            SwCollection(List(6) { it }) { i, _ -> Box(Modifier.testTag("row$i").height(48.dp).fillMaxWidth()) }
        }
        rule.waitForIdle()
        assertEquals("1000 dp holds three 18 rem cards at font scale 1", 3, onTheFirstLine())
        fontScale = 2f
        rule.waitForIdle()
        assertEquals("at font scale 2 only one 36 rem card fits", 1, onTheFirstLine())
    }

    @Test fun theLazyGridTileWidthGrowsWithTheFontScale() {
        themed {
            SwLazyCollection(List(6) { it }, key = { it }) { i -> Box(Modifier.testTag("row$i").height(48.dp).fillMaxWidth()) }
        }
        rule.waitForIdle()
        fontScale = 2f
        rule.waitForIdle()
        assertEquals("411 dp: one column at font scale 2", 1, onTheFirstLine())
    }

    @Test fun onAPhoneTwoTilesNeedTheirMinimumWidthBetween420And463() {
        val gap = 16.dp
        assertEquals(1, tileColumns(420.dp, gap))
        assertEquals(1, tileColumns(430.dp, gap))
        assertEquals(1, tileColumns(463.dp, gap))
        assertEquals(2, tileColumns(464.dp, gap))
    }

    @Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w440dp-h800dp")
    @Test fun at440DpTilesAreOneColumn() {
        sixTiles()
        rule.waitForIdle()
        assertEquals("a tile would be 212 dp, under 14 rem", 1, onTheFirstLine())
    }
}
