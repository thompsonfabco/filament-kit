package com.thompsonfabco.filamentkit.ui

import android.os.Build
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.input.InputMode
import androidx.compose.ui.input.InputModeManager
import androidx.compose.ui.platform.LocalInputModeManager
import androidx.compose.ui.test.assertIsFocused
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.lifecycle.SavedStateHandle
import com.thompsonfabco.filamentkit.net.AmsSlot
import com.thompsonfabco.filamentkit.net.AmsUnit
import com.thompsonfabco.filamentkit.net.CommandResult
import com.thompsonfabco.filamentkit.net.HistoryRecord
import com.thompsonfabco.filamentkit.net.HistorySaved
import com.thompsonfabco.filamentkit.net.HistorySpool
import com.thompsonfabco.filamentkit.net.HistorySummary
import com.thompsonfabco.filamentkit.net.IntakeHistory
import com.thompsonfabco.filamentkit.net.KlipperFound
import com.thompsonfabco.filamentkit.net.LoadSlot
import com.thompsonfabco.filamentkit.net.MapStatus
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.net.PrinterReport
import com.thompsonfabco.filamentkit.net.PrinterStatus
import com.thompsonfabco.filamentkit.net.RevisionProposal
import com.thompsonfabco.filamentkit.net.UnloadResult
import com.thompsonfabco.filamentkit.net.UsageEntry
import com.thompsonfabco.filamentkit.ui.components.DetailPresentation
import com.thompsonfabco.filamentkit.ui.components.EMPTY_PANE_TAG
import com.thompsonfabco.filamentkit.ui.components.detailPresentation
import com.thompsonfabco.filamentkit.ui.history.HistoryBackend
import com.thompsonfabco.filamentkit.ui.history.HistoryListScreen
import com.thompsonfabco.filamentkit.ui.history.HistoryListViewModel
import com.thompsonfabco.filamentkit.ui.history.RecordScreen
import com.thompsonfabco.filamentkit.ui.history.RecordViewModel
import com.thompsonfabco.filamentkit.ui.presets.FakePresets
import com.thompsonfabco.filamentkit.ui.presets.PresetsScreen
import com.thompsonfabco.filamentkit.ui.presets.PresetsViewModel
import com.thompsonfabco.filamentkit.ui.printers.CameraSource
import com.thompsonfabco.filamentkit.ui.printers.PrinterBackend
import com.thompsonfabco.filamentkit.ui.printers.PrinterScreen
import com.thompsonfabco.filamentkit.ui.printers.PrinterToolsBackend
import com.thompsonfabco.filamentkit.ui.printers.PrinterToolsViewModel
import com.thompsonfabco.filamentkit.ui.printers.PrinterViewModel
import com.thompsonfabco.filamentkit.ui.printers.PrintersScreen
import com.thompsonfabco.filamentkit.ui.printers.PrintersViewModel
import com.thompsonfabco.filamentkit.ui.search.SearchScreen
import com.thompsonfabco.filamentkit.ui.search.SearchViewModel
import com.thompsonfabco.filamentkit.ui.spool.FakeSpoolBackend
import com.thompsonfabco.filamentkit.ui.spool.SpoolScreen
import com.thompsonfabco.filamentkit.ui.spool.SpoolViewModel
import com.thompsonfabco.filamentkit.ui.spool.spoolJson
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.DetailStyle
import com.thompsonfabco.filamentkit.ui.theme.LocalWindowClass
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Step C (Panes `DetailStyle.Pane`): two panes on Tablet (section list + active pane), three panes on Desktop
 * (with an empty-pane state), drill-in on Phone as today, focus moves and returns, and drafts survive resize.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h900dp")
class DetailPaneTest {
    @get:Rule val rule = createComposeRule()

    private var look by mutableStateOf(Look.Panes)
    private var window by mutableStateOf(WindowClass.Desktop)
    private var inputMode: InputModeManager? = null

    @Test fun presentationChoosesPaneOnWidePanesAndScreenOnPhone() {
        assertEquals(DetailPresentation.Screen, detailPresentation(DetailStyle.Pane, WindowClass.Phone))
        assertEquals(DetailPresentation.Pane, detailPresentation(DetailStyle.Pane, WindowClass.Tablet))
        assertEquals(DetailPresentation.Pane, detailPresentation(DetailStyle.Pane, WindowClass.Desktop))
    }

    private val spool214Desc = "Polymaker PolyTerra PLA Charcoal Black, spool 214, PLA, Workshop X1 A1, 620 grams left"

    @Test fun spoolsOnPanesDesktopShowsEmptyPaneThenDetailAndSurvivesResize() {
        look = Look.Panes
        window = WindowClass.Desktop
        val opened = mutableListOf<Int>()
        val backend = FakeSpoolBackend().apply {
            spools = listOf(spoolJson(214, remaining = 620.0, location = "Workshop X1 A1"))
        }
        val searchVm = SearchViewModel { q, sealed -> backend.search(q, sealed) }
        searchVm.setQuery("pla")
        searchVm.search()

        rule.setContent {
            inputMode = LocalInputModeManager.current
            inputMode?.requestInputMode(InputMode.Keyboard)
            SpoolwardenTheme(look, Appearance.Light) {
                CompositionLocalProvider(LocalWindowClass provides window) {
                    val vms = remember { mutableMapOf<Int, SpoolViewModel>() }
                    SearchScreen(
                        vm = searchVm,
                        onOpenSpool = { opened += it.id },
                        onPairAgain = {},
                        spoolDetail = { spool, embedded, _ ->
                            val vm = vms.getOrPut(spool.id) {
                                SpoolViewModel(spool.id, backend, spool, null, null, SavedStateHandle())
                            }
                            SpoolScreen(vm = vm, onLoad = {}, onPairAgain = {}, embedded = embedded)
                        },
                    )
                }
            }
        }
        rule.waitForIdle()

        // Desktop starts with the empty-pane state beside the list.
        rule.onNodeWithTag(EMPTY_PANE_TAG).assertExists()

        // Selecting a spool opens it in the right pane beside the list.
        rule.onNodeWithContentDescription(spool214Desc).performClick()
        rule.waitForIdle()
        assertEquals(emptyList<Int>(), opened)
        rule.onNodeWithTag(EMPTY_PANE_TAG).assertDoesNotExist()
        rule.onNodeWithText("Update weight").assertExists()
        rule.onNodeWithContentDescription("Close").assertIsFocused()

        // Start a draft in Update weight and resize Desktop -> Tablet -> Phone -> Desktop.
        rule.onNodeWithText("Update weight").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Weight with spool").performTextInput("710")
        rule.waitForIdle()
        window = WindowClass.Tablet
        rule.waitForIdle()
        window = WindowClass.Phone
        rule.waitForIdle()
        window = WindowClass.Desktop
        rule.waitForIdle()
        rule.mainClock.advanceTimeBy(500)
        rule.waitForIdle()
        rule.onNodeWithText("710").assertExists()
    }

    @Test fun spoolsOnPanesPhoneStaysDrillInScreen() {
        look = Look.Panes
        window = WindowClass.Phone
        val opened = mutableListOf<Int>()
        val backend = FakeSpoolBackend().apply {
            spools = listOf(spoolJson(214, remaining = 620.0, location = "Workshop X1 A1"))
        }
        val searchVm = SearchViewModel { q, sealed -> backend.search(q, sealed) }
        searchVm.setQuery("pla")
        searchVm.search()

        rule.setContent {
            SpoolwardenTheme(look, Appearance.Light) {
                CompositionLocalProvider(LocalWindowClass provides window) {
                    SearchScreen(
                        vm = searchVm,
                        onOpenSpool = { opened += it.id },
                        onPairAgain = {},
                        spoolDetail = { _, _, _ -> },
                    )
                }
            }
        }
        rule.waitForIdle()
        rule.onNodeWithContentDescription(spool214Desc).performClick()
        rule.waitForIdle()
        assertEquals(listOf(214), opened)
    }

    @Test fun printersOnPanesTabletCoversListWithDetailAndBackRestoresFocus() {
        look = Look.Panes
        window = WindowClass.Tablet
        val opened = mutableListOf<String>()
        val printer = Printer(id = "p1", name = "Workshop X1", model = "X1C", serial = "X1A", configured = true, state = "connected")
        val status = PrinterStatus(
            gcodeState = "IDLE",
            ams = listOf(AmsUnit(0, slots = listOf(AmsSlot(slot = 0, label = "A1", type = "PLA", colorHex = "2B2B2E")))),
        )
        val backend = object : PrinterBackend {
            override suspend fun printers() = listOf(printer)
            override suspend fun addPrinter(serial: String, accessCode: String, name: String?) = printer
            override suspend fun addKlipperPrinter(host: String, port: Int, name: String?) = printer
            override suspend fun scanKlipper(subnet: String?) = emptyList<KlipperFound>()
            override suspend fun setApiKey(id: String, key: String) = Unit
            override suspend fun printer(id: String) = PrinterDetail(printer, status)
            override suspend fun command(id: String, action: String) = CommandResult(true)
            override suspend fun unload(id: String, label: String, dryRun: Boolean) = UnloadResult(slot = LoadSlot(label), location = "Shelf A")
        }
        val tools = object : PrinterToolsBackend {
            override suspend fun startMap(id: String) = "ok"
            override suspend fun mapStatus(id: String) = MapStatus("idle")
            override suspend fun usage(id: String, days: Int) = emptyList<UsageEntry>()
            override suspend fun undoUsage(entryId: String) = error("unused")
            override suspend fun report(id: String) = PrinterReport("r1", "")
        }
        val listVm = PrintersViewModel(backend)

        rule.setContent {
            inputMode = LocalInputModeManager.current
            inputMode?.requestInputMode(InputMode.Keyboard)
            SpoolwardenTheme(look, Appearance.Light) {
                CompositionLocalProvider(LocalWindowClass provides window) {
                    val vms = remember { mutableMapOf<String, Pair<PrinterViewModel, PrinterToolsViewModel>>() }
                    PrintersScreen(
                        viewModel = listVm,
                        onOpen = { opened += it },
                        onPairAgain = {},
                        printerDetail = { id, embedded, _ ->
                            val (pvm, tvm) = vms.getOrPut(id) {
                                PrinterViewModel(backend, id) to PrinterToolsViewModel(tools, id)
                            }
                            PrinterScreen(
                                viewModel = pvm, tools = tvm,
                                camera = CameraSource(okhttp3.OkHttpClient(), "", "", emptyMap()),
                                onPairAgain = {}, embedded = embedded,
                            )
                        },
                    )
                }
            }
        }
        rule.waitForIdle()
        rule.onNodeWithText("Workshop X1").performClick()
        rule.waitForIdle()
        assertEquals(emptyList<String>(), opened)
        // On Tablet, detail covers list and shows Back.
        rule.onNodeWithText("Workshop X1").assertDoesNotExist()
        rule.onNodeWithText("Slots").assertExists()
        rule.onNodeWithContentDescription("Back").assertIsFocused()

        rule.runOnUiThread { inputMode?.requestInputMode(InputMode.Keyboard) }
        rule.onNodeWithContentDescription("Back").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Workshop X1").assertIsFocused()
    }

    @Test fun recentOnPanesDesktopShowsEmptyPaneAndOpensRecordBesideList() {
        look = Look.Panes
        window = WindowClass.Desktop
        val spools = listOf(HistorySpool(214, 41, "Polymaker", "PolyTerra PLA Charcoal Black", "PLA", "2B2B2E"))
        val summary = HistorySummary(id = "a1", at = "2026-11-02T12:00:00Z", source = "label", photos = 0, spools = spools)
        val record = HistoryRecord(
            id = "a1", at = "2026-11-02T12:00:00Z", source = "label", photos = 0, spools = spools,
            saved = listOf(HistorySaved(0, listOf(214), buildJsonObject { put("vendor", "Polymaker") })),
        )
        val backend = object : HistoryBackend {
            override suspend fun list() = IntakeHistory(30, 1, 0L, true, listOf(summary))
            override suspend fun record(id: String) = record
            override suspend fun photo(id: String, n: Int) = ByteArray(0)
            override suspend fun revise(id: String, note: String, item: Int?) =
                RevisionProposal("p1", 0, buildJsonObject {}, buildJsonObject {}, emptyList())
            override suspend fun applyProposal(id: String, proposal: String) = record
            override suspend fun applyValues(id: String, item: Int, values: JsonObject) = record
            override suspend fun undo(id: String, revision: Int) = record
        }
        val listVm = HistoryListViewModel(backend)

        rule.setContent {
            inputMode = LocalInputModeManager.current
            inputMode?.requestInputMode(InputMode.Keyboard)
            SpoolwardenTheme(look, Appearance.Light) {
                CompositionLocalProvider(LocalWindowClass provides window) {
                    val vms = remember { mutableMapOf<String, RecordViewModel>() }
                    HistoryListScreen(
                        vm = listVm, client = null, onOpen = {}, onPairAgain = {},
                        recordDetail = { hid, embedded, onClose ->
                            val rvm = vms.getOrPut(hid) { RecordViewModel(backend, hid) }
                            RecordScreen(
                                vm = rvm, list = listVm, client = null, onBack = onClose, onOpenRecord = {},
                                onEdit = {}, onOpenPhoto = {}, onOpenSpool = {}, onPairAgain = {}, embedded = embedded,
                            )
                        },
                    )
                }
            }
        }
        rule.waitForIdle()
        rule.onNodeWithTag(EMPTY_PANE_TAG).assertExists()

        rule.onNodeWithText("Polymaker PolyTerra PLA Charcoal Black").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag(EMPTY_PANE_TAG).assertDoesNotExist()
        rule.onNodeWithText("Fields").assertExists()

        rule.runOnUiThread { inputMode?.requestInputMode(InputMode.Keyboard) }
        rule.onNodeWithContentDescription("Close").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag(EMPTY_PANE_TAG).assertExists()
        rule.onNodeWithText("Polymaker PolyTerra PLA Charcoal Black").assertIsFocused()
    }

    @Test fun presetsOnPanesDesktopShowsEmptyPaneAndOpensEditorInRightPane() {
        look = Look.Panes
        window = WindowClass.Desktop
        val backend = FakePresets().apply {
            parentLists["PLA"] = ParentList(synced = true, parents = listOf("Generic PLA", "Polymaker PLA"))
        }
        val vm = PresetsViewModel(backend)

        rule.setContent {
            inputMode = LocalInputModeManager.current
            inputMode?.requestInputMode(InputMode.Keyboard)
            SpoolwardenTheme(look, Appearance.Light) {
                CompositionLocalProvider(LocalWindowClass provides window) {
                    PresetsScreen(vm = vm, onPairAgain = {}, onAddCatalogLine = {}, pairing = Unit)
                }
            }
        }
        rule.waitForIdle()
        rule.onNodeWithTag(EMPTY_PANE_TAG).assertExists()

        rule.onNodeWithContentDescription("Change parent of Example Filaments PolyTerra").performScrollTo().performClick()
        rule.waitForIdle()
        rule.onNodeWithTag(EMPTY_PANE_TAG).assertDoesNotExist()
        rule.onNodeWithText("Bambu Studio parent of Example Filaments PolyTerra").assertExists()

        rule.runOnUiThread { inputMode?.requestInputMode(InputMode.Keyboard) }
        rule.onNodeWithContentDescription("Close").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag(EMPTY_PANE_TAG).assertExists()
        rule.onNodeWithContentDescription("Change parent of Example Filaments PolyTerra").assertIsFocused()
    }
}
