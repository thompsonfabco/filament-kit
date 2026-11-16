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
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
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
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
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
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Step A (Workbench `DetailStyle.Card`): on wide windows a card expands in place, on phones it stays its own screen,
 * focus moves into the detail and back to the row on close, drafts survive window-size changes, and Console is unchanged.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w800dp-h900dp")
class DetailCardTest {
    @get:Rule val rule = createComposeRule()

    private var look by mutableStateOf(Look.Workbench)
    private var window by mutableStateOf(WindowClass.Tablet)
    private var inputMode: InputModeManager? = null

    @Test fun presentationChoosesCardOnWideWorkbenchAndScreenOnPhoneAndConsole() {
        assertEquals(DetailPresentation.Screen, detailPresentation(DetailStyle.Card, WindowClass.Phone))
        assertEquals(DetailPresentation.Card, detailPresentation(DetailStyle.Card, WindowClass.Tablet))
        assertEquals(DetailPresentation.Card, detailPresentation(DetailStyle.Card, WindowClass.Desktop))
        for (w in WindowClass.entries) {
            assertEquals(DetailPresentation.Screen, detailPresentation(DetailStyle.Inline, w))
        }
    }

    private fun showSpools(
        initialLook: Look = Look.Workbench,
        initialWindow: WindowClass = WindowClass.Tablet,
        onOpenedScreen: (Int) -> Unit = {},
    ) {
        look = initialLook
        window = initialWindow
        val backend = FakeSpoolBackend().apply {
            spools = listOf(
                spoolJson(214, remaining = 620.0, location = "Workshop X1 A1"),
                spoolJson(215, remaining = 450.0, location = "Shelf B"),
            )
        }
        val searchVm = SearchViewModel { q, sealed -> backend.search(q, sealed) }
        searchVm.setQuery("pla")
        searchVm.search()

        rule.setContent {
            // Keep keyboard mode so focus assertions observe FocusRequester moves.
            inputMode = LocalInputModeManager.current
            inputMode?.requestInputMode(InputMode.Keyboard)
            SpoolwardenTheme(look, Appearance.Light) {
                CompositionLocalProvider(LocalWindowClass provides window) {
                    val spoolVms = remember { mutableMapOf<Int, SpoolViewModel>() }
                    SearchScreen(
                        vm = searchVm,
                        onOpenSpool = { onOpenedScreen(it.id) },
                        onPairAgain = {},
                        spoolDetail = { spool, embedded, _ ->
                            val vm = spoolVms.getOrPut(spool.id) {
                                SpoolViewModel(spool.id, backend, spool, null, null, SavedStateHandle())
                            }
                            SpoolScreen(vm = vm, onLoad = {}, onPairAgain = {}, embedded = embedded)
                        },
                    )
                }
            }
        }
        rule.waitForIdle()
    }

    private val spool214Desc = "Polymaker PolyTerra PLA Charcoal Black, spool 214, PLA, Workshop X1 A1, 620 grams left"
    private val spool215Desc = "Polymaker PolyTerra PLA Charcoal Black, spool 215, PLA, Shelf B, 450 grams left"

    @Test fun onPhoneWorkbenchStaysItsOwnScreen() {
        val opened = mutableListOf<Int>()
        showSpools(Look.Workbench, WindowClass.Phone) { opened += it }
        rule.onNodeWithContentDescription(spool214Desc).performClick()
        rule.waitForIdle()
        assertEquals(listOf(214), opened)
        rule.onNodeWithText("Update weight").assertDoesNotExist()
    }

    @Test fun onTabletConsoleIsUnchangedAndOpensOwnScreen() {
        val opened = mutableListOf<Int>()
        showSpools(Look.Console, WindowClass.Tablet) { opened += it }
        rule.onNodeWithContentDescription(spool214Desc).performClick()
        rule.waitForIdle()
        assertEquals(listOf(214), opened)
        rule.onNodeWithText("Update weight").assertDoesNotExist()
    }

    @Test fun onTabletWorkbenchExpandsCardInPlaceMovesFocusAndReturnsFocusOnClose() {
        val opened = mutableListOf<Int>()
        showSpools(Look.Workbench, WindowClass.Tablet) { opened += it }
        rule.onNodeWithContentDescription(spool214Desc).performClick()
        rule.waitForIdle()
        assertEquals("no separate screen opened", emptyList<Int>(), opened)
        rule.onNodeWithText("Update weight").assertExists()
        rule.onNodeWithContentDescription("Close").assertIsFocused()

        // A second card can also expand at the same time.
        rule.onNodeWithContentDescription(spool215Desc).performScrollTo().performClick()
        rule.waitForIdle()
        assertEquals(2, rule.onAllNodes(androidx.compose.ui.test.hasContentDescription("Close")).fetchSemanticsNodes().size)

        // Closing the first returns focus to its row.
        rule.runOnUiThread { inputMode?.requestInputMode(InputMode.Keyboard) }
        rule.onAllNodes(androidx.compose.ui.test.hasContentDescription("Close"))[0].performScrollTo().performClick()
        rule.waitForIdle()
        rule.onNodeWithContentDescription(spool214Desc).assertIsFocused()
    }

    @Test fun openDetailAndDraftSurviveWindowClassSwitch() {
        val handedOff = mutableListOf<Int>()
        showSpools(Look.Workbench, WindowClass.Tablet) { handedOff += it }
        rule.onNodeWithContentDescription(spool214Desc).performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Update weight").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Weight with spool").performTextInput("750")
        rule.waitForIdle()

        // Switch Tablet -> Desktop -> Tablet: the expanded card and its typed draft survive.
        window = WindowClass.Desktop
        rule.waitForIdle()
        window = WindowClass.Tablet
        rule.waitForIdle()
        rule.mainClock.advanceTimeBy(500)
        rule.waitForIdle()
        rule.onNodeWithText("Weight with spool").assertExists()
        rule.onNodeWithText("750").assertExists()

        // Switch Tablet -> Phone: the open detail hands off to its own screen instead of vanishing.
        window = WindowClass.Phone
        rule.waitForIdle()
        assertEquals(listOf(214), handedOff)
    }

    // ---- Printers / One printer ----

    private fun fakePrinterBackend(): Pair<PrinterBackend, PrinterToolsBackend> {
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
        return backend to tools
    }

    private fun showPrinters(
        initialLook: Look = Look.Workbench,
        initialWindow: WindowClass = WindowClass.Tablet,
        onOpenedScreen: (String) -> Unit = {},
    ) {
        look = initialLook
        window = initialWindow
        val (backend, toolsBackend) = fakePrinterBackend()
        val listVm = PrintersViewModel(backend)
        rule.setContent {
            inputMode = LocalInputModeManager.current
            inputMode?.requestInputMode(InputMode.Keyboard)
            SpoolwardenTheme(look, Appearance.Light) {
                CompositionLocalProvider(LocalWindowClass provides window) {
                    val vms = remember { mutableMapOf<String, Pair<PrinterViewModel, PrinterToolsViewModel>>() }
                    PrintersScreen(
                        viewModel = listVm,
                        onOpen = { onOpenedScreen(it) },
                        onPairAgain = {},
                        printerDetail = { id, embedded, _ ->
                            val (pvm, tvm) = vms.getOrPut(id) {
                                PrinterViewModel(backend, id) to PrinterToolsViewModel(toolsBackend, id)
                            }
                            PrinterScreen(
                                viewModel = pvm,
                                tools = tvm,
                                camera = CameraSource(okhttp3.OkHttpClient(), "", "", emptyMap()),
                                onPairAgain = {},
                                embedded = embedded,
                            )
                        },
                    )
                }
            }
        }
        rule.waitForIdle()
    }

    @Test fun printersOnPhoneWorkbenchOpensOwnScreen() {
        val opened = mutableListOf<String>()
        showPrinters(Look.Workbench, WindowClass.Phone) { opened += it }
        rule.onNodeWithText("Workshop X1").performClick()
        rule.waitForIdle()
        assertEquals(listOf("p1"), opened)
        rule.onNodeWithText("Slots").assertDoesNotExist()
    }

    @Test fun printersOnTabletConsoleIsUnchanged() {
        val opened = mutableListOf<String>()
        showPrinters(Look.Console, WindowClass.Tablet) { opened += it }
        rule.onNodeWithText("Workshop X1").performClick()
        rule.waitForIdle()
        assertEquals(listOf("p1"), opened)
        rule.onNodeWithText("Slots").assertDoesNotExist()
    }

    @Test fun printersOnTabletWorkbenchExpandsCardAndReturnsFocusOnClose() {
        val opened = mutableListOf<String>()
        showPrinters(Look.Workbench, WindowClass.Tablet) { opened += it }
        rule.onNodeWithText("Workshop X1").performClick()
        rule.waitForIdle()
        assertEquals(emptyList<String>(), opened)
        rule.onNodeWithText("Slots").assertExists()
        rule.onNodeWithContentDescription("Close").assertIsFocused()

        rule.runOnUiThread { inputMode?.requestInputMode(InputMode.Keyboard) }
        rule.onNodeWithContentDescription("Close").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Workshop X1").assertIsFocused()
    }

    // ---- Recently added ----

    private fun fakeHistoryBackend(): HistoryBackend {
        val spools = listOf(HistorySpool(214, 41, "Polymaker", "PolyTerra PLA Charcoal Black", "PLA", "2B2B2E"))
        val summary = HistorySummary(
            id = "a1",
            at = "2026-11-02T12:00:00Z",
            source = "label",
            photos = 0,
            spools = spools,
        )
        val record = HistoryRecord(
            id = "a1",
            at = "2026-11-02T12:00:00Z",
            source = "label",
            photos = 0,
            spools = spools,
            saved = listOf(HistorySaved(0, listOf(214), buildJsonObject { put("vendor", "Polymaker") })),
        )
        return object : HistoryBackend {
            override suspend fun list() = IntakeHistory(30, 1, 0L, true, listOf(summary))
            override suspend fun record(id: String) = record
            override suspend fun photo(id: String, n: Int) = ByteArray(0)
            override suspend fun revise(id: String, note: String, item: Int?) =
                RevisionProposal("p1", 0, buildJsonObject {}, buildJsonObject {}, emptyList())
            override suspend fun applyProposal(id: String, proposal: String) = record
            override suspend fun applyValues(id: String, item: Int, values: JsonObject) = record
            override suspend fun undo(id: String, revision: Int) = record
        }
    }

    private fun showRecent(
        initialLook: Look = Look.Workbench,
        initialWindow: WindowClass = WindowClass.Tablet,
        onOpenedScreen: (String) -> Unit = {},
    ) {
        look = initialLook
        window = initialWindow
        val backend = fakeHistoryBackend()
        val listVm = HistoryListViewModel(backend)
        rule.setContent {
            inputMode = LocalInputModeManager.current
            inputMode?.requestInputMode(InputMode.Keyboard)
            SpoolwardenTheme(look, Appearance.Light) {
                CompositionLocalProvider(LocalWindowClass provides window) {
                    val vms = remember { mutableMapOf<String, RecordViewModel>() }
                    HistoryListScreen(
                        vm = listVm,
                        client = null,
                        onOpen = { onOpenedScreen(it) },
                        onPairAgain = {},
                        recordDetail = { hid, embedded, onClose ->
                            val rvm = vms.getOrPut(hid) { RecordViewModel(backend, hid) }
                            RecordScreen(
                                vm = rvm,
                                list = listVm,
                                client = null,
                                onBack = onClose,
                                onOpenRecord = {},
                                onEdit = {},
                                onOpenPhoto = {},
                                onOpenSpool = {},
                                onPairAgain = {},
                                embedded = embedded,
                            )
                        },
                    )
                }
            }
        }
        rule.waitForIdle()
    }

    @Test fun recentOnPhoneWorkbenchOpensOwnScreen() {
        val opened = mutableListOf<String>()
        showRecent(Look.Workbench, WindowClass.Phone) { opened += it }
        rule.onNodeWithText("Polymaker PolyTerra PLA Charcoal Black").performClick()
        rule.waitForIdle()
        assertEquals(listOf("a1"), opened)
        rule.onNodeWithText("Fields").assertDoesNotExist()
    }

    @Test fun recentOnTabletConsoleIsUnchanged() {
        val opened = mutableListOf<String>()
        showRecent(Look.Console, WindowClass.Tablet) { opened += it }
        rule.onNodeWithText("Polymaker PolyTerra PLA Charcoal Black").performClick()
        rule.waitForIdle()
        assertEquals(listOf("a1"), opened)
        rule.onNodeWithText("Fields").assertDoesNotExist()
    }

    @Test fun recentOnTabletWorkbenchExpandsCardAndReturnsFocusOnClose() {
        val opened = mutableListOf<String>()
        showRecent(Look.Workbench, WindowClass.Tablet) { opened += it }
        rule.onNodeWithText("Polymaker PolyTerra PLA Charcoal Black").performClick()
        rule.waitForIdle()
        assertEquals(emptyList<String>(), opened)
        rule.onNodeWithText("Fields").assertExists()
        rule.onNodeWithContentDescription("Close").assertIsFocused()

        rule.runOnUiThread { inputMode?.requestInputMode(InputMode.Keyboard) }
        rule.onNodeWithContentDescription("Close").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Polymaker PolyTerra PLA Charcoal Black").assertIsFocused()
    }

    // ---- Slicer presets ----

    private fun showPresets(
        initialLook: Look = Look.Workbench,
        initialWindow: WindowClass = WindowClass.Tablet,
    ) {
        look = initialLook
        window = initialWindow
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
    }

    @Test fun presetsOnTabletWorkbenchExpandsParentEditorInCardAndSurvivesResize() {
        showPresets(Look.Workbench, WindowClass.Tablet)
        rule.onNodeWithContentDescription("Change parent of Example Filaments PolyTerra").performScrollTo().performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Bambu Studio parent of Example Filaments PolyTerra").assertExists()
        rule.onNodeWithContentDescription("Close").assertIsFocused()

        // Type a filter query and switch Tablet -> Phone -> Tablet: the draft survives.
        rule.onNodeWithText("Find a parent").performScrollTo().performTextInput("Poly")
        rule.waitForIdle()
        window = WindowClass.Phone
        rule.waitForIdle()
        window = WindowClass.Tablet
        rule.waitForIdle()
        rule.onNodeWithText("Poly").assertExists()

        // Closing returns focus to the Change parent button.
        rule.runOnUiThread { inputMode?.requestInputMode(InputMode.Keyboard) }
        rule.onNodeWithContentDescription("Close").performScrollTo().performClick()
        rule.waitForIdle()
        rule.onNodeWithContentDescription("Change parent of Example Filaments PolyTerra").assertIsFocused()
    }

    @Test fun presetsOnTabletConsoleKeepsParentSheet() {
        showPresets(Look.Console, WindowClass.Tablet)
        rule.onNodeWithContentDescription("Change parent of Example Filaments PolyTerra").performScrollTo().performClick()
        rule.waitForIdle()
        // Console uses the modal sheet, not an inline card with a Close icon button.
        rule.onNodeWithText("Bambu Studio parent of Example Filaments PolyTerra").assertExists()
        rule.onNodeWithContentDescription("Close").assertDoesNotExist()
    }
}
