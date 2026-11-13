package com.thompsonfabco.filamentkit.ui.spool

import android.os.Build
import androidx.activity.OnBackPressedDispatcher
import androidx.activity.compose.LocalOnBackPressedDispatcherOwner
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.net.AmsSlot
import com.thompsonfabco.filamentkit.net.AmsUnit
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LoadResult
import com.thompsonfabco.filamentkit.net.LoadSlot
import com.thompsonfabco.filamentkit.net.MovedBack
import com.thompsonfabco.filamentkit.net.PresetRef
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.net.PrinterStatus
import com.thompsonfabco.filamentkit.net.SlotSpool
import com.thompsonfabco.filamentkit.ui.SemanticsAudit
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.SwToastHost
import com.thompsonfabco.filamentkit.ui.components.SwToastState
import com.thompsonfabco.filamentkit.ui.components.SwTopBar
import com.thompsonfabco.filamentkit.ui.search.NfcState
import com.thompsonfabco.filamentkit.ui.search.SearchScreen
import com.thompsonfabco.filamentkit.ui.search.SearchViewModel
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.CompletableDeferred
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * AUT-8 (07-accessibility 15) for Spools and the spool screens of S4.8 (05 7): Spools, Spool with its sheets and
 * dialog, Tag, Link to a sealed spool, and the three steps of Load into a printer, drawn under the top bar that names
 * them, in light and dark at font scale 1 and 2. Data is fake (example spools, printers and tags).
 */
@OptIn(ExperimentalMaterial3Api::class)
@RunWith(RobolectricTestRunner::class)
// a tall window, so nothing is scrolled out of view and every control has a touch area to measure
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class SpoolScreenSemanticsTest {
    @get:Rule val rule = createComposeRule()

    private var dark by mutableStateOf(false)
    private var fontScale by mutableStateOf(1f)
    private var density = 1f
    private var title = ""

    private fun host(title: String, screen: @Composable () -> Unit) {
        this.title = title
        rule.setContent {
            val base = LocalDensity.current
            density = base.density
            CompositionLocalProvider(LocalDensity provides Density(base.density, fontScale)) {
                SpoolwardenTheme(Look.Console, if (dark) Appearance.Dark else Appearance.Light) {
                    Column(Modifier.fillMaxSize()) {
                        SwTopBar(title = title)
                        Box(Modifier.weight(1f)) { screen() }
                    }
                }
            }
        }
    }

    private fun audit(sectionTitles: List<String>): List<String> {
        rule.waitForIdle()
        val merged = rule.onRoot().fetchSemanticsNode()
        val unmerged = rule.onRoot(useUnmergedTree = true).fetchSemanticsNode()
        return SemanticsAudit.findings(merged, unmerged, density, title, sectionTitles)
    }

    /** Light and dark, font scale 1 and 2, on the screen already shown: its words are there and it passes the audit. */
    private fun auditAllFour(shows: List<String>, sectionTitles: List<String> = emptyList(), hasControls: Boolean = true) {
        rule.waitForIdle()
        for (text in shows) {
            assertTrue("\"$text\" is on screen", rule.onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty())
        }
        if (hasControls) assertTrue("the screen has controls to audit", SemanticsAudit.clickableCount(rule.onRoot().fetchSemanticsNode()) >= 1)
        for (isDark in listOf(false, true)) {
            for (scale in listOf(1f, 2f)) {
                dark = isDark
                fontScale = scale
                assertEquals("dark=$isDark fontScale=$scale", emptyList<String>(), audit(sectionTitles))
            }
        }
    }

    /** A sheet or dialog that is open: its words are there at every look (the audit covers the screen behind it). */
    private fun overlayShows(vararg shown: String) {
        rule.waitForIdle()
        for (isDark in listOf(false, true)) for (scale in listOf(1f, 2f)) {
            dark = isDark
            fontScale = scale
            rule.waitForIdle()
            for (text in shown) {
                assertTrue("\"$text\" is on screen", rule.onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty())
            }
        }
    }

    private val backend = FakeSpoolBackend()
    private val polymaker = spoolJson(214, tag = "04A1B2", lot = "L-77")

    private fun spoolScreen(
        spool: SpoolSummary? = polymaker.toSpoolSummary(),
        online: Boolean = true,
        printersOn: Boolean = true,
        tag: String? = null,
    ): SpoolViewModel {
        SpoolCache.clear()
        val vm = SpoolViewModel(214, backend, spool, tag)
        host(spool?.title ?: "Spool 214") { SpoolScreen(vm, onLoad = {}, onPairAgain = {}, online = online, printersOn = printersOn) }
        return vm
    }

    // ---- Spools ----

    private val results = listOf(
        spoolJson(214, tag = "04A1B2"),
        spoolJson(212, remaining = 1000.0, location = "Dry box 1", sealed = true),
    )

    @Test fun spoolsIdleWithTheTagHint() {
        val vm = SearchViewModel { _, _ -> emptyList() }
        host("Spools") { SearchScreen(vm, onOpenSpool = {}, onPairAgain = {}, nfc = NfcState.Ready) }
        auditAllFour(listOf("Brand, material, colour…", "Sealed only", "Hold a spool's tag to the back of the phone to open it."))
    }

    @Test fun spoolsWithoutNfcOrWithNfcOff() {
        val vm = SearchViewModel { _, _ -> emptyList() }
        var nfc by mutableStateOf(NfcState.Missing)
        host("Spools") { SearchScreen(vm, onOpenSpool = {}, onPairAgain = {}, nfc = nfc, onNfcSettings = {}) }
        auditAllFour(listOf("This phone can't read tags. Search instead."))
        nfc = NfcState.Off
        auditAllFour(listOf("Turn on NFC to open spools by their tag.", "NFC settings"))
    }

    @Test fun spoolsResults() {
        val vm = SearchViewModel { _, _ -> results }
        host("Spools") { SearchScreen(vm, onOpenSpool = {}, onPairAgain = {}, nfc = NfcState.Ready) }
        vm.setQuery("poly")
        vm.search()
        rule.waitForIdle()
        auditAllFour(
            listOf(
                "Polymaker PolyTerra PLA Charcoal Black", "Spool 214", "620 g left", "Dry box 1", "sealed", "tagged",
            ),
        )
        rule.onNodeWithContentDescription("Clear search").assertExists()
    }

    @Test fun spoolsNoMatchWithTheSealedFilterOn() {
        val vm = SearchViewModel { _, _ -> emptyList() }
        host("Spools") { SearchScreen(vm, onOpenSpool = {}, onPairAgain = {}, nfc = NfcState.Ready) }
        vm.setSealedOnly(true)
        vm.setQuery("petg")
        vm.search()
        rule.waitForIdle()
        auditAllFour(listOf("No spools match \"petg\".", "Clear the Sealed only filter"))
    }

    @Test fun spoolsFailureAndHubNotices() {
        var failure: Exception = ApiError(0, "offline", "gone")
        val vm = SearchViewModel { _, _ -> throw failure }
        host("Spools") { SearchScreen(vm, onOpenSpool = {}, onPairAgain = {}, nfc = NfcState.Ready) }
        vm.setQuery("petg")
        vm.search()
        auditAllFour(listOf("Cannot reach the Hub. Check that this phone is on the home network.", "Try again"))
        failure = FingerprintMismatch("aa", "bb")
        vm.search()
        auditAllFour(listOf("The Hub's certificate has changed.", "Review the certificate"))
        failure = ApiError(401, "unauthorized", "no")
        vm.search()
        auditAllFour(listOf("This phone is no longer paired with the Hub.", "Pair again"))
    }

    // ---- Spool ----

    @Test fun spoolOpened() {
        spoolScreen()
        auditAllFour(
            listOf(
                "Polymaker", "PolyTerra PLA Charcoal Black", "620 g left", "of 1000 g", "62 % left", "Update weight",
                "Load into a printer", "Move", "Location", "Workshop X1 A1", "04A1B2", "Opened", "41", "140 g", "L-77",
            ),
            listOf("Details"),
        )
    }

    @Test fun spoolOpenedByATagSaysSo() {
        spoolScreen(tag = "04A1B2")
        auditAllFour(listOf("Opened by tag 04A1B2"), listOf("Details"))
    }

    @Test fun spoolSealedShowsNoBar() {
        spoolScreen(spoolJson(212, sealed = true, location = "Dry box 1", tag = null).toSpoolSummary())
        auditAllFour(listOf("Sealed · 1000 g", "Sealed"), listOf("Details"))
        rule.onNodeWithText("% left", substring = true).assertDoesNotExist()
    }

    @Test fun spoolLevelBarIsSpokenWithTheGramsLeft() {
        spoolScreen()
        rule.waitForIdle()
        rule.onNodeWithContentDescription("620 grams left of 1000, 62 percent").assertExists()
    }

    @Test fun spoolRowIsSpokenWithTheGramsLeftAndLeavesThemOutWhenUnknown() {
        host("Spools") {
            Column {
                SpoolRow(spoolJson(214, location = "Dry box 1").toSpoolSummary())
                SpoolRow(spoolJson(215, location = "Dry box 2", remaining = null).toSpoolSummary())
            }
        }
        rule.waitForIdle()
        rule.onNodeWithContentDescription("Polymaker PolyTerra PLA Charcoal Black, spool 214, PLA, Dry box 1, 620 grams left").assertExists()
        rule.onNodeWithContentDescription("Polymaker PolyTerra PLA Charcoal Black, spool 215, PLA, Dry box 2").assertExists()
    }

    @Test fun spoolEmptyShowsItsStatus() {
        spoolScreen(spoolJson(214, remaining = 0.0, archived = true).toSpoolSummary())
        auditAllFour(listOf("Empty"), listOf("Details"))
    }

    @Test fun spoolValuesTheHubDidNotSendAreLeftOut() {
        spoolScreen(spoolJson(214, location = null, total = null, remaining = null).toSpoolSummary())
        rule.waitForIdle()
        rule.onNodeWithText("Location").assertDoesNotExist()
        rule.onNodeWithText("Lot").assertDoesNotExist()
        rule.onNodeWithText("None").assertExists()
        auditAllFour(listOf("Details"), listOf("Details"))
    }

    @Test fun spoolWithoutThePrintersFeatureHasNoLoadButton() {
        spoolScreen(printersOn = false)
        rule.waitForIdle()
        rule.onNodeWithText("Load into a printer").assertDoesNotExist()
        auditAllFour(listOf("Update weight", "Move"), listOf("Details"))
    }

    @Test fun spoolOfflineDisablesTheActionsWithTheReason() {
        spoolScreen(online = false)
        auditAllFour(listOf("Needs the Hub. Reconnecting…"), listOf("Details"))
    }

    @Test fun spoolShowsItsResultLine() {
        val handle = androidx.lifecycle.SavedStateHandle()
        SpoolCache.clear()
        val vm = SpoolViewModel(214, backend, polymaker.toSpoolSummary(), null, handle = handle)
        host("Polymaker PolyTerra PLA Charcoal Black") { SpoolScreen(vm, onLoad = {}, onPairAgain = {}) }
        handle[SpoolViewModel.RESULT_KEY] = SpoolResult.Loaded("Workshop X1", "A2").encode()
        rule.waitForIdle()
        auditAllFour(listOf("Loaded into Workshop X1, slot A2."), listOf("Details"))
        handle[SpoolViewModel.RESULT_KEY] = SpoolResult.LoadedUnconfirmed("Workshop X1", "A2").encode()
        rule.waitForIdle()
        auditAllFour(listOf("The printer accepted it but hasn't shown the change yet."), listOf("Details"))
        assertTrue(vm.state.value.result is SpoolResult.LoadedUnconfirmed)
    }

    @Test fun spoolRestoredWithoutASummaryShowsTheFailureAndKeepsItsControlsOut() {
        backend.failure = "spool" to ApiError(0, "offline", "gone")
        spoolScreen(spool = null)
        auditAllFour(listOf("Cannot reach the Hub. Check that this phone is on the home network.", "Try again"))
    }

    @Test fun spoolHubNotices() {
        val vm = spoolScreen()
        backend.failure = "spool" to ApiError(401, "unauthorized", "no")
        vm.refresh()
        rule.waitForIdle()
        auditAllFour(listOf("This phone is no longer paired with the Hub.", "Pair again", "Update weight"), listOf("Details"))
    }

    @Test fun updateWeightSheet() {
        backend.updateAnswer = { _, _, _, _ -> spoolJson(214, remaining = 482.0) }
        val vm = spoolScreen()
        rule.waitForIdle()
        rule.onNodeWithText("Update weight").performClick()
        rule.waitForIdle()
        overlayShows("Weight with spool", "Put the spool on the scale and type what it shows.", "Save weight", "Cancel", "Enter the weight to see the result first.")
        vm.setWeight("622")
        org.robolectric.shadows.ShadowLooper.idleMainLooper(500, java.util.concurrent.TimeUnit.MILLISECONDS)
        rule.waitForIdle()
        overlayShows("Remaining becomes 482 g (now 620 g).")
        vm.setWeight("abc")
        rule.waitForIdle()
        overlayShows("Enter grams above 0.")
    }

    @Test fun moveSheet() {
        val vm = spoolScreen()
        vm.openMove()
        rule.waitForIdle()
        overlayShows("Move to", "Shelf B", "Workshop X1 A1", "Now here", "Dry box 1")
    }

    @Test fun moveSheetWithNoLocations() {
        backend.locations = emptyList()
        val vm = spoolScreen()
        vm.openMove()
        rule.waitForIdle()
        overlayShows("The Hub has no storage locations yet. Add them on the Hub page under Settings > Storage locations.")
    }

    @Test fun markEmptyDialog() {
        val vm = spoolScreen()
        vm.askMarkEmpty()
        rule.waitForIdle()
        overlayShows("Mark spool 214 empty?", "Polymaker PolyTerra PLA Charcoal Black (spool 214) will be marked as used up.", "Cancel", "Mark empty")
    }

    // ---- Tag ----

    @Test fun tagLooksUp() {
        SpoolCache.clear()
        backend.tagGate = CompletableDeferred()
        val vm = TagViewModel("04A1B2", backend)
        host("Tag 04A1B2") { TagScreen(vm, "04A1B2", onLinked = {}, onLink = {}, onAddNew = {}, onPairAgain = {}) }
        rule.waitForIdle()
        rule.onNodeWithText("Looking up the tag…").assertExists()
        assertEquals(2, rule.onAllNodesWithText("Tag 04A1B2").fetchSemanticsNodes().size)
    }

    @Test fun tagNotLinked() {
        SpoolCache.clear()
        val vm = TagViewModel("04A1B2", backend)
        host("Tag 04A1B2") { TagScreen(vm, "04A1B2", onLinked = {}, onLink = {}, onAddNew = {}, onPairAgain = {}) }
        auditAllFour(
            listOf(
                "This tag is not linked to a spool yet",
                "Link it to a sealed spool you are opening, or add the spool as new.",
                "Link to a sealed spool", "Add as a new spool",
            ),
        )
    }

    @Test fun tagLookupFailed() {
        SpoolCache.clear()
        backend.failure = "tag" to ApiError(0, "offline", "gone")
        val vm = TagViewModel("04A1B2", backend)
        host("Tag 04A1B2") { TagScreen(vm, "04A1B2", onLinked = {}, onLink = {}, onAddNew = {}, onPairAgain = {}) }
        auditAllFour(listOf("Cannot reach the Hub. Check that this phone is on the home network.", "Try again"))
    }

    @Test fun tagLinkedReplacesItself() {
        SpoolCache.clear()
        backend.tagAnswer = polymaker
        val vm = TagViewModel("04A1B2", backend)
        var opened: SpoolSummary? = null
        host("Tag 04A1B2") { TagScreen(vm, "04A1B2", onLinked = { opened = it }, onLink = {}, onAddNew = {}, onPairAgain = {}) }
        rule.waitForIdle()
        assertEquals(214, opened?.id)
    }

    // ---- Link to a sealed spool ----

    @Test fun linkFind() {
        SpoolCache.clear()
        backend.spools = listOf(spoolJson(212, sealed = true, location = "Dry box 1"))
        val vm = LinkFindViewModel(backend)
        host("Tag 04A1B2") { LinkFindScreen(vm, "04A1B2", onPick = { _, _ -> }, onPairAgain = {}) }
        vm.setQuery("poly")
        vm.search()
        rule.waitForIdle()
        auditAllFour(listOf("Link tag 04A1B2 to a sealed spool", "Brand, name or colour", "Weight with spool (optional)", "Dry box 1"))
        vm.setWeight("abc")
        auditAllFour(listOf("Enter grams above 0, or leave this empty."))
    }

    @Test fun linkFindWithNoMatch() {
        SpoolCache.clear()
        val vm = LinkFindViewModel(backend)
        host("Tag 04A1B2") { LinkFindScreen(vm, "04A1B2", onPick = { _, _ -> }, onPairAgain = {}) }
        vm.setQuery("zzz")
        vm.search()
        rule.waitForIdle()
        auditAllFour(listOf("No sealed spools match."))
    }

    @Test fun linkPreview() {
        SpoolCache.clear()
        SpoolCache.put(spoolJson(212, sealed = true).toSpoolSummary())
        val vm = LinkPreviewViewModel("04A1B2", 212, 1240.0, backend)
        host("Tag 04A1B2") { LinkPreviewScreen(vm, "04A1B2", onBack = {}, onDone = {}, onPairAgain = {}) }
        auditAllFour(listOf("Link this tag?", "Tag 04A1B2 is linked to this spool.", "Weight with spool is recorded as 1240 g.", "Link tag", "Back"))
    }

    @Test fun linkPreviewWithTheTagInUse() {
        SpoolCache.clear()
        SpoolCache.put(spoolJson(212, sealed = true).toSpoolSummary())
        backend.failure = "link" to ApiError(
            409, "tag_conflict", "in use",
            kotlinx.serialization.json.buildJsonObject {
                put("reason", kotlinx.serialization.json.JsonPrimitive("tag_on_other_spool"))
                put("other_spool", spoolJson(90, tag = "04A1B2"))
            },
        )
        val vm = LinkPreviewViewModel("04A1B2", 212, null, backend)
        host("Tag 04A1B2") { LinkPreviewScreen(vm, "04A1B2", onBack = {}, onDone = {}, onPairAgain = {}) }
        auditAllFour(listOf("This tag is already linked to another spool:", "Spool 90", "Move the tag to this spool", "Cancel"))
    }

    // ---- Load into a printer ----

    private val x1 = Printer(id = "X1A", name = "Workshop X1", model = "X1C", serial = "X1A", configured = true, state = "connected")
    private val voron = Printer(id = "V2", name = "Garage Voron", serial = "V2", configured = true, state = "offline", family = "klipper")
    private val locked = Printer(id = "P1", name = "Study P1S", model = "P1S", serial = "P1", configured = true, state = "wrong_code")
    private val status = PrinterStatus(
        ams = listOf(
            AmsUnit(
                0, "A", "ams",
                listOf(
                    AmsSlot(0, "A1", "PETG", "F28A2E", active = true, spool = SlotSpool(3, "Bambu Lab PETG HF Orange", "PETG", "F28A2E", 440.0)),
                    AmsSlot(1, "A2"),
                    AmsSlot(2, "A3", "PLA"),
                ),
            ),
            AmsUnit(254, "Ext", "ext", listOf(AmsSlot(0, "Ext", "TPU"))),
        ),
    )

    private class FakeLoad(var printers: List<Printer>, val detail: PrinterDetail, val plan: LoadResult) : LoadBackend {
        var gate: CompletableDeferred<Unit>? = null
        var failure: Exception? = null
        override suspend fun printers() = printers
        override suspend fun printer(id: String) = detail
        override suspend fun load(id: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult {
            if (!dryRun) {
                gate?.await()
                failure?.let { throw it }
            }
            return plan
        }
    }

    private val plan = LoadResult(
        slot = LoadSlot("A2", 0, 1), preset = PresetRef("P1", "Polymaker PLA @X1C 0.4"), nozzleMm = 0.4,
        movedBack = listOf(MovedBack(212, "Shelf B")), problems = listOf("The slot holds a spool of another material."),
    )

    @Test fun loadPrintersStep() {
        SpoolCache.clear()
        val vm = LoadPrintersViewModel(FakeLoad(listOf(x1, voron, locked, x1.copy(id = "X2", name = "Garage X1")), PrinterDetail(x1, status), plan))
        host("Load into a printer") {
            LoadPrintersScreen(vm, polymaker.toSpoolSummary(), onPick = { _, _ -> }, onOpenPrinters = {}, onPairAgain = {})
        }
        auditAllFour(
            listOf(
                "Polymaker PolyTerra PLA Charcoal Black", "Which printer?", "Workshop X1", "Garage Voron", "Study P1S",
                "Connected", "Offline", "Needs a look", "The printer did not accept the Access Code. Enter the Access Code again.",
            ),
        )
    }

    @Test fun loadPrintersStepWithNoPrinters() {
        SpoolCache.clear()
        val vm = LoadPrintersViewModel(FakeLoad(emptyList(), PrinterDetail(x1, status), plan))
        host("Load into a printer") {
            LoadPrintersScreen(vm, polymaker.toSpoolSummary(), onPick = { _, _ -> }, onOpenPrinters = {}, onPairAgain = {})
        }
        auditAllFour(listOf("No printers are set up yet. Add one under Printers.", "Open Printers"))
    }

    @Test fun loadPrintersStepWithOnePrinterThatCanTakeItIsSkipped() {
        SpoolCache.clear()
        val vm = LoadPrintersViewModel(FakeLoad(listOf(x1, voron), PrinterDetail(x1, status), plan))
        var picked: Pair<String, Boolean>? = null
        host("Load into a printer") {
            LoadPrintersScreen(vm, polymaker.toSpoolSummary(), onPick = { p, skipped -> picked = p.id to skipped }, onOpenPrinters = {}, onPairAgain = {})
        }
        rule.waitForIdle()
        assertEquals("X1A" to true, picked)
    }

    @Test fun loadSlotsStep() {
        SpoolCache.clear()
        val vm = LoadSlotsViewModel("X1A", FakeLoad(listOf(x1), PrinterDetail(x1, status), plan))
        host("Load into a printer") { LoadSlotsScreen(vm, polymaker.toSpoolSummary(), skipped = true, onPick = {}, onPairAgain = {}) }
        auditAllFour(
            listOf(
                "Which slot on Workshop X1?", "Printer: Workshop X1", "A1", "PETG · Bambu Lab PETG HF Orange · in use",
                "Empty", "PLA", "AMS A",
            ),
            listOf("AMS A"),
        )
    }

    @Test fun loadSlotsStepWithAPrinterProblem() {
        SpoolCache.clear()
        val vm = LoadSlotsViewModel("P1", FakeLoad(listOf(locked), PrinterDetail(locked, status), plan))
        host("Load into a printer") { LoadSlotsScreen(vm, polymaker.toSpoolSummary(), skipped = false, onPick = {}, onPairAgain = {}) }
        auditAllFour(listOf("The printer did not accept the Access Code. Enter the Access Code again."))
    }

    @Test fun loadSlotsStepWithNoSlots() {
        SpoolCache.clear()
        val vm = LoadSlotsViewModel("X1A", FakeLoad(listOf(x1), PrinterDetail(x1, null), plan))
        host("Load into a printer") { LoadSlotsScreen(vm, polymaker.toSpoolSummary(), skipped = false, onPick = {}, onPairAgain = {}) }
        auditAllFour(listOf("The printer reports no slots."), hasControls = false)
    }

    private fun previewScreen(load: FakeLoad, gate: LoadGate = LoadGate(), toast: SwToastState = SwToastState(), onBack: () -> Unit = {}): LoadPreviewViewModel {
        SpoolCache.clear()
        val vm = LoadPreviewViewModel(polymaker.toSpoolSummary(), "X1A", "A2", load, gate)
        host("Load into a printer") {
            CompositionLocalProvider(LocalToast provides toast) {
                Box {
                    LoadPreviewScreen(
                        vm, polymaker.toSpoolSummary(), "A2", onBack = onBack, onFinished = {}, onDone = {}, onOpenPrinter = {},
                        onPairAgain = {},
                    )
                    SwToastHost(toast, Modifier.align(Alignment.BottomCenter))
                }
            }
        }
        return vm
    }

    @Test fun loadPreviewStep() {
        previewScreen(FakeLoad(listOf(x1), PrinterDetail(x1, status), plan))
        auditAllFour(
            listOf(
                "Load into Workshop X1, slot A2?", "Preset: Polymaker PLA @X1C 0.4", "Nozzle: 0.4 mm",
                "Spool 212 now in A2 goes back to Shelf B", "The slot holds a spool of another material.",
                "This sets the slot on the printer and moves the spool there in the inventory.", "Back", "Load",
            ),
        )
    }

    @Test fun loadPreviewDroppedConnection() {
        val load = FakeLoad(listOf(x1), PrinterDetail(x1, status), plan)
        load.failure = ApiError(0, "offline", "lost")
        val vm = previewScreen(load)
        rule.waitForIdle()
        vm.load()
        auditAllFour(
            listOf(
                "The connection dropped while loading, so the app can't tell if it worked.", "Open the printer", "Done",
            ),
        )
    }

    @Test fun loadPreviewPairingRefused() {
        val load = FakeLoad(listOf(x1), PrinterDetail(x1, status), plan)
        load.failure = ApiError(401, "unauthorized", "no")
        val vm = previewScreen(load)
        rule.waitForIdle()
        vm.load()
        auditAllFour(listOf("Not loaded: the Hub did not accept this phone's pairing at that moment. Nothing was changed."))
    }

    @Test fun loadPreviewWhileTheLoadIsWrittenIgnoresBackAndSaysSo() {
        val hold = CompletableDeferred<Unit>()
        val load = FakeLoad(listOf(x1), PrinterDetail(x1, status), plan).also { it.gate = hold }
        val gate = LoadGate()
        var left = 0
        var dispatcher: OnBackPressedDispatcher? = null
        SpoolCache.clear()
        val toast = SwToastState()
        val vm = LoadPreviewViewModel(polymaker.toSpoolSummary(), "X1A", "A2", load, gate)
        host("Load into a printer") {
            dispatcher = LocalOnBackPressedDispatcherOwner.current?.onBackPressedDispatcher
            CompositionLocalProvider(LocalToast provides toast) {
                Box {
                    LoadPreviewScreen(
                        vm, polymaker.toSpoolSummary(), "A2", onBack = { left++ }, onFinished = {}, onDone = {}, onOpenPrinter = {},
                        onPairAgain = {},
                    )
                    SwToastHost(toast, Modifier.align(Alignment.BottomCenter))
                }
            }
        }
        rule.waitForIdle()
        vm.load()
        rule.waitForIdle()
        assertTrue("the app knows a load is being written", gate.writing.value)
        rule.runOnUiThread { dispatcher!!.onBackPressed() }
        rule.waitForIdle()
        rule.onNodeWithText("Loading into the printer… wait for its answer.").assertExists()
        assertEquals("Back does not leave while the load is written", 0, left)
        // Back and Load are off, Load says what it is doing
        rule.onNodeWithText("Back").assertHeightIsAtLeast(44.dp)
        hold.complete(Unit)
        rule.waitUntil { vm.state.value.finished != null }
        assertEquals(SpoolResult.LoadedUnconfirmed("Workshop X1", "A2"), vm.state.value.finished)
    }

    // ---- 05 3.2 states on the S4.8 screens ----

    @Test fun spoolsOfflineKeepsTheResultsUnderTheOfflineNotice() {
        val vm = SearchViewModel { _, _ -> results }
        var online by mutableStateOf(true)
        host("Spools") { SearchScreen(vm, onOpenSpool = {}, onPairAgain = {}, nfc = NfcState.Ready, online = online) }
        vm.setQuery("poly")
        vm.search()
        rule.waitForIdle()
        online = false
        auditAllFour(listOf("Offline. Showing what was loaded", "Polymaker PolyTerra PLA Charcoal Black"))
    }

    @Test fun spoolsOfflineWithNothingLoadedIsTheCannotReachTheHubState() {
        val vm = SearchViewModel { _, _ -> results }
        host("Spools") { SearchScreen(vm, onOpenSpool = {}, onPairAgain = {}, nfc = NfcState.Ready, online = false) }
        auditAllFour(listOf("Cannot reach the Hub", "Check that this phone is on the home network.", "Try again"))
    }

    @Test fun spoolOfflineShowsWhatWasLoadedAndItsAge() {
        spoolScreen(online = false)
        auditAllFour(listOf("Offline. Showing what was loaded", "Needs the Hub. Reconnecting…", "Polymaker"), listOf("Details"))
    }

    @Test fun tagOfflineWhileLookingUp() {
        SpoolCache.clear()
        backend.tagGate = CompletableDeferred()
        val vm = TagViewModel("04A1B2", backend)
        host("Tag 04A1B2") { TagScreen(vm, "04A1B2", onLinked = {}, onLink = {}, onAddNew = {}, onPairAgain = {}, online = false) }
        auditAllFour(listOf("Cannot reach the Hub", "Try again"))
    }

    @Test fun aSlowFirstLoadSaysItIsStillWaitingAfterTenSeconds() {
        SpoolCache.clear()
        backend.tagGate = CompletableDeferred()
        val vm = TagViewModel("04A1B2", backend)
        host("Tag 04A1B2") { TagScreen(vm, "04A1B2", onLinked = {}, onLink = {}, onAddNew = {}, onPairAgain = {}) }
        rule.waitForIdle()
        rule.onNodeWithText("Still waiting for the Hub…").assertDoesNotExist()
        rule.mainClock.advanceTimeBy(10_500)
        rule.waitForIdle()
        rule.onNodeWithText("Still waiting for the Hub…").assertExists()
    }

    @Test fun loadPrintersOfflineAfterTheyWereRead() {
        SpoolCache.clear()
        val vm = LoadPrintersViewModel(FakeLoad(listOf(x1, voron, locked), PrinterDetail(x1, status), plan))
        var online by mutableStateOf(true)
        host("Load into a printer") {
            LoadPrintersScreen(vm, polymaker.toSpoolSummary(), onPick = { _, _ -> }, onOpenPrinters = {}, onPairAgain = {}, online = online)
        }
        rule.waitForIdle()
        online = false
        auditAllFour(listOf("Offline. Showing what was loaded", "Workshop X1"))
    }

    @Test fun linkPreviewOffline() {
        SpoolCache.clear()
        SpoolCache.put(spoolJson(212, sealed = true).toSpoolSummary())
        val vm = LinkPreviewViewModel("04A1B2", 212, null, backend)
        var online by mutableStateOf(true)
        host("Tag 04A1B2") { LinkPreviewScreen(vm, "04A1B2", onBack = {}, onDone = {}, onPairAgain = {}, online = online) }
        rule.waitForIdle()
        online = false
        auditAllFour(listOf("Offline. Showing what was loaded"))
    }

    // ---- 05 7.8 tag already in use ----

    @Test fun aSpoolWithATagOfItsOwnOffersTheReplaceButton() {
        SpoolCache.clear()
        SpoolCache.put(spoolJson(212, sealed = true, tag = "04FFFF").toSpoolSummary())
        backend.failure = "link" to ApiError(
            409, "tag_conflict", "in use",
            kotlinx.serialization.json.buildJsonObject {
                put("reason", kotlinx.serialization.json.JsonPrimitive("tag_on_other_spool"))
                put("other_spool", spoolJson(90, tag = "04A1B2"))
            },
        )
        val vm = LinkPreviewViewModel("04A1B2", 212, null, backend)
        host("Tag 04A1B2") { LinkPreviewScreen(vm, "04A1B2", onBack = {}, onDone = {}, onPairAgain = {}) }
        auditAllFour(listOf("This tag is already linked to another spool:", "Spool 90", "Move the tag here and replace this spool's tag", "Cancel"))
        rule.onNodeWithText("Move the tag to this spool").assertDoesNotExist()
    }

    @Test fun aSpoolThatHasAnotherTagIsNotToldTheTagIsLinkedElsewhere() {
        SpoolCache.clear()
        SpoolCache.put(spoolJson(212, sealed = true).toSpoolSummary())
        backend.failure = "link" to ApiError(
            409, "tag_conflict", "has a tag",
            kotlinx.serialization.json.buildJsonObject { put("reason", kotlinx.serialization.json.JsonPrimitive("spool_has_other_tag")) },
        )
        val vm = LinkPreviewViewModel("04A1B2", 212, null, backend)
        host("Tag 04A1B2") { LinkPreviewScreen(vm, "04A1B2", onBack = {}, onDone = {}, onPairAgain = {}) }
        auditAllFour(listOf("Move the tag here and replace this spool's tag", "Cancel"))
        rule.onNodeWithText("This tag is already linked to another spool:").assertDoesNotExist()
    }

    // ---- the sheet's own window ----

    private fun sheetBack() {
        rule.runOnUiThread {
            (org.robolectric.shadows.ShadowDialog.getLatestDialog() as androidx.activity.ComponentDialog).onBackPressedDispatcher.onBackPressed()
        }
        rule.waitForIdle()
    }

    @Test fun systemBackOnTheWeightSheetClosesAnEmptyOneAndAsksWhenTyped() {
        backend.updateAnswer = { _, _, _, _ -> spoolJson(214, remaining = 482.0) }
        val vm = spoolScreen()
        rule.waitForIdle()
        rule.onNodeWithText("Update weight").performClick()
        rule.waitForIdle()
        // nothing typed: Back closes the sheet
        sheetBack()
        assertEquals(null, vm.state.value.weight)
        rule.onNodeWithText("Update weight").performClick()
        rule.waitForIdle()
        vm.setWeight("622")
        org.robolectric.shadows.ShadowLooper.idleMainLooper(500, java.util.concurrent.TimeUnit.MILLISECONDS)
        rule.waitForIdle()
        assertTrue(vm.state.value.weight!!.canSave)
        // typed: Back asks, Stay keeps it
        sheetBack()
        rule.onNodeWithText("Leave without saving?").assertExists()
        rule.onNodeWithText("Stay").performClick()
        rule.waitForIdle()
        assertEquals("622", vm.state.value.weight?.text)
    }

    @Test fun systemBackOnTheMoveSheetClosesIt() {
        val vm = spoolScreen()
        vm.openMove()
        rule.waitForIdle()
        sheetBack()
        assertEquals(null, vm.state.value.move)
    }

    @Test fun aRefusedLoadShowsTheHubsWordsWithNoTryAgain() {
        val load = FakeLoad(listOf(x1), PrinterDetail(x1, status), plan)
        load.failure = ApiError(409, "printer_busy", "The printer is printing; try again when it is idle.")
        val vm = previewScreen(load)
        rule.waitForIdle()
        vm.load()
        auditAllFour(listOf("The printer is printing; try again when it is idle.", "Load"))
        assertTrue(rule.onAllNodesWithText("Try again").fetchSemanticsNodes().isEmpty())
    }

    @Test fun anUnreadableAnswerToTheLoadSaysToCheckThePrinter() {
        val load = FakeLoad(listOf(x1), PrinterDetail(x1, status), plan)
        load.failure = ApiError(502, "internal", "The server returned an error (502)", noHubMessage = true)
        val vm = previewScreen(load)
        rule.waitForIdle()
        vm.load()
        auditAllFour(listOf("The connection dropped while loading, so the app can't tell if it worked.", "Open the printer"))
        assertTrue(rule.onAllNodesWithText("Try again").fetchSemanticsNodes().isEmpty())
    }

    @Test fun theLinkPreviewAfterAFailedDryRunHasOneBack() {
        SpoolCache.clear()
        backend.failure = "link" to ApiError(0, "offline", "gone")
        val vm = LinkPreviewViewModel("04A1B2", 212, null, backend)
        host("Tag 04A1B2") { LinkPreviewScreen(vm, "04A1B2", onBack = {}, onDone = {}, onPairAgain = {}) }
        auditAllFour(listOf("Cannot reach the Hub", "Try again"))
        assertEquals(1, rule.onAllNodesWithText("Back").fetchSemanticsNodes().size)
    }
}
