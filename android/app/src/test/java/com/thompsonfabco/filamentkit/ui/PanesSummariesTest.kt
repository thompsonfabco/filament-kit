package com.thompsonfabco.filamentkit.ui

import android.os.Build
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.net.CommandResult
import com.thompsonfabco.filamentkit.net.HistoryRecord
import com.thompsonfabco.filamentkit.net.HistorySpool
import com.thompsonfabco.filamentkit.net.HistorySummary
import com.thompsonfabco.filamentkit.net.IntakeHistory
import com.thompsonfabco.filamentkit.net.KlipperFound
import com.thompsonfabco.filamentkit.net.LoadSlot
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.net.PrinterStatus
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.net.RevisionProposal
import com.thompsonfabco.filamentkit.net.UnloadResult
import com.thompsonfabco.filamentkit.ui.components.SwSectionList
import com.thompsonfabco.filamentkit.ui.components.presetsSummary
import com.thompsonfabco.filamentkit.ui.components.printersSummary
import com.thompsonfabco.filamentkit.ui.components.recentSummary
import com.thompsonfabco.filamentkit.ui.history.HistoryBackend
import com.thompsonfabco.filamentkit.ui.history.HistoryListScreen
import com.thompsonfabco.filamentkit.ui.history.HistoryListViewModel
import com.thompsonfabco.filamentkit.ui.presets.FakePresets
import com.thompsonfabco.filamentkit.ui.presets.PresetsScreen
import com.thompsonfabco.filamentkit.ui.presets.PresetsViewModel
import com.thompsonfabco.filamentkit.ui.printers.PrinterBackend
import com.thompsonfabco.filamentkit.ui.printers.PrintersScreen
import com.thompsonfabco.filamentkit.ui.printers.PrintersViewModel
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/**
 * Step D (Panes section list summaries): one-line summaries for Printers, Recently added and Slicer presets
 * built from data the app already holds, with no extra Hub calls.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w800dp-h900dp")
class PanesSummariesTest {
    @get:Rule val rule = createComposeRule()

    private val resources get() = RuntimeEnvironment.getApplication().resources

    @Test fun printersSummaryFormatsCountsFromHeldPrinters() {
        assertEquals("No printers yet", printersSummary(emptyList(), resources))
        val p1 = Printer(id = "p1", name = "Workshop X1", serial = "S1", configured = true, state = "connected")
        val p2 = Printer(id = "p2", name = "Study A1", serial = "S2", configured = true, state = "offline")
        val p3 = Printer(id = "p3", name = "Garage P1S", serial = "S3", configured = true, state = "wrong_code")
        val found = Printer(id = "p4", name = "Found P1S", serial = "S4", configured = false, state = "offline")
        assertEquals("1 connected", printersSummary(listOf(p1, found), resources))
        assertEquals("1 connected · 1 offline", printersSummary(listOf(p1, p2, found), resources))
        assertEquals("1 connected · 1 offline · 1 needs a look", printersSummary(listOf(p1, p2, p3, found), resources))
        assertEquals("1 offline", printersSummary(listOf(p2), resources))
    }

    @Test fun recentSummaryFormatsLatestRecordOrEmpty() {
        assertEquals("Nothing added yet", recentSummary(IntakeHistory(30, 0, 0L, true, emptyList()), resources))
        val spools = listOf(HistorySpool(214, 41, "Polymaker", "PolyTerra PLA Charcoal Black", "PLA", "2B2B2E"))
        val summary = HistorySummary(id = "a1", at = "2026-11-02T12:00:00Z", source = "label", photos = 0, spools = spools)
        assertEquals("Polymaker PolyTerra PLA Charcoal Black", recentSummary(IntakeHistory(30, 1, 0L, true, listOf(summary)), resources))
    }

    @Test fun presetsSummaryFormatsCountsOrNeverBuilt() {
        assertEquals("No presets built yet", presetsSummary(ProfileStatus(lines = 0, presets = 0), resources))
        assertEquals("24 presets for 6 lines", presetsSummary(ProfileStatus(lines = 6, presets = 24), resources))
    }

    @Test fun screensEmitSummariesWithoutExtraCallsAndSectionListRendersThem() {
        val printer = Printer(id = "p1", name = "Workshop X1", model = "X1C", serial = "X1A", configured = true, state = "connected")
        var printerCalls = 0
        val printerBackend = object : PrinterBackend {
            override suspend fun printers(): List<Printer> {
                printerCalls++
                return listOf(printer)
            }
            override suspend fun addPrinter(serial: String, accessCode: String, name: String?) = printer
            override suspend fun addKlipperPrinter(host: String, port: Int, name: String?) = printer
            override suspend fun scanKlipper(subnet: String?) = emptyList<KlipperFound>()
            override suspend fun setApiKey(id: String, key: String) = Unit
            override suspend fun printer(id: String) = PrinterDetail(printer, PrinterStatus())
            override suspend fun command(id: String, action: String) = CommandResult(true)
            override suspend fun unload(id: String, label: String, dryRun: Boolean) = UnloadResult(slot = LoadSlot(label), location = "")
        }
        val presetsBackend = FakePresets()

        var summaries by mutableStateOf<Map<Tab, String>>(emptyMap())
        val printersVm = PrintersViewModel(printerBackend)
        val presetsVm = PresetsViewModel(presetsBackend)

        rule.setContent {
            SpoolwardenTheme(Look.Panes, Appearance.Light) {
                PrintersScreen(printersVm, onOpen = {}, onPairAgain = {}, onSummary = { summaries = summaries + (Tab.Printers to it) })
                PresetsScreen(presetsVm, onPairAgain = {}, onAddCatalogLine = {}, pairing = Unit, onSummary = { summaries = summaries + (Tab.Home to it) })
                SwSectionList(selected = Tab.Printers, onSelect = {}, modifier = Modifier.fillMaxSize(), summaries = summaries)
            }
        }
        rule.waitForIdle()

        assertEquals(1, printerCalls)
        assertEquals(1, presetsBackend.statusCalls)
        rule.onNodeWithText("1 connected").assertExists()
        rule.onNodeWithText("24 presets for 6 lines").assertExists()
    }
}
