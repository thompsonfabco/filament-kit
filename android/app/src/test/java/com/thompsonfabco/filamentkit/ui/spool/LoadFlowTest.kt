package com.thompsonfabco.filamentkit.ui.spool

import com.thompsonfabco.filamentkit.net.AmsSlot
import com.thompsonfabco.filamentkit.net.AmsUnit
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LoadResult
import com.thompsonfabco.filamentkit.net.LoadSlot
import com.thompsonfabco.filamentkit.net.MapSlot
import com.thompsonfabco.filamentkit.net.MapStatus
import com.thompsonfabco.filamentkit.net.MovedBack
import com.thompsonfabco.filamentkit.net.PresetRef
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.net.PrinterStatus
import com.thompsonfabco.filamentkit.net.SlotSpool
import com.thompsonfabco.filamentkit.net.UsageEntry
import com.thompsonfabco.filamentkit.ui.printers.PrinterHelp
import com.thompsonfabco.filamentkit.ui.printers.PrinterToolsBackend
import com.thompsonfabco.filamentkit.ui.printers.PrinterToolsViewModel
import com.thompsonfabco.filamentkit.ui.printers.UsageHelp
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class LoadFlowTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    // ---- load into printer ---------------------------------------------------------------------------

    private val spool = SpoolSummary(7, "SUNLU", "Red", "PLA", "FF0000", "Shelf 2", 812.0)
    private val printer = Printer(id = "0948AB", name = "Garage H2D", model = "H2D", serial = "0948AB",
        configured = true, state = "connected")
    private val detail = PrinterDetail(printer, PrinterStatus(gcodeState = "IDLE", ams = listOf(
        AmsUnit(0, "A", "ams", listOf(
            AmsSlot(0, "A1", "PLA", "FFFFFF", spool = SlotSpool(3, "Acme Basic Black", "PLA", "111111", 400.0)),
            AmsSlot(1, "A2"),
        )),
        AmsUnit(128, "HT-A", "ams_ht", listOf(AmsSlot(0, "HT-A", "PETG"))),
        AmsUnit(254, "Ext", "ext", listOf(AmsSlot(0, "Ext", "TPU"))),
    )))

    private fun result(confirmed: Boolean = false, assumed: Boolean = true, problems: List<String> = emptyList()) =
        LoadResult(
            spool = Json.parseToJsonElement("""{"id":7,"location":"Garage H2D – AMS A1","filament":{"name":"Red"}}""").jsonObject,
            slot = LoadSlot("A1", 0, 0),
            preset = PresetRef("P1234567", "SUNLU PLA Red @H2D 0.4"),
            nozzleMm = 0.4, nozzleAssumed = assumed, confirmed = confirmed, problems = problems,
        )

    private class FakeLoad(val detail: PrinterDetail, var preview: LoadResult, var real: LoadResult) : LoadBackend {
        val loads = mutableListOf<Triple<String, Int, Boolean>>()
        var loadError: Exception? = null
        /** When set, a real load waits for it (the write is in flight). */
        var gate: CompletableDeferred<Unit>? = null
        var printers = listOf(detail.printer, Printer(id = "X", name = "X", serial = "X", configured = false))
        override suspend fun printers() = printers
        override suspend fun printer(id: String) = detail
        override suspend fun load(id: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult {
            loads += Triple(label, spoolId, dryRun)
            if (!dryRun) gate?.await()
            loadError?.let { throw it }
            return if (dryRun) preview else real
        }
    }

    private val load = FakeLoad(detail, result(), result(confirmed = true))

    private fun loadVm() = LoadViewModel(load)

    private fun LoadViewModel.toPreview() {
        start(spool)
        dispatcher.scheduler.runCurrent()
        pickPrinter(printer)
        dispatcher.scheduler.runCurrent()
        pickSlot("A1")
        dispatcher.scheduler.runCurrent()
    }

    @Test fun loadListsConfiguredPrintersThenTheirSlots() = runTest(dispatcher) {
        val vm = loadVm()
        vm.start(spool)
        runCurrent()
        val pick = vm.state.value as LoadUiState.PickPrinter
        assertEquals(listOf("0948AB"), pick.printers!!.map { it.id })
        vm.pickPrinter(printer)
        runCurrent()
        val slots = vm.state.value as LoadUiState.PickSlot
        assertEquals(listOf("A1", "A2", "HT-A", "Ext"), slots.slots!!.map { it.label })
    }

    @Test fun theExternalHolderCanBePickedLikeASlot() = runTest(dispatcher) {
        load.preview = result().copy(slot = LoadSlot("Ext", 254, 0))
        load.real = result(confirmed = true).copy(slot = LoadSlot("Ext", 254, 0))
        val vm = loadVm()
        vm.start(spool); runCurrent()
        vm.pickPrinter(printer); runCurrent()
        val ext = (vm.state.value as LoadUiState.PickSlot).slots!!.last()
        assertEquals("Ext (external spool holder) · TPU", LoadHelp.slotLine(ext))
        vm.pickSlot(ext.label); runCurrent()
        assertEquals(Triple("Ext", 7, true), load.loads.last())
        assertTrue((vm.state.value as LoadUiState.Preview).lines[0].endsWith("the external spool holder"))
        vm.confirm(); runCurrent()
        assertEquals(Triple("Ext", 7, false), load.loads.last())
        assertEquals("Loaded into Garage H2D, the external spool holder", (vm.state.value as LoadUiState.Done).lines[0])
    }

    @Test fun twoExternalHoldersAreNamedFromSay() = runTest(dispatcher) {
        val two = PrinterDetail(printer, PrinterStatus(gcodeState = "IDLE", ams = listOf(
            AmsUnit(254, "Ext-L", "ext", listOf(AmsSlot(0, "Ext-L", "TPU", say = listOf("external", "left")))),
            AmsUnit(255, "Ext-R", "ext", listOf(AmsSlot(0, "Ext-R", say = listOf("external", "right")))),
        )))
        val l = LoadSlot("Ext-L", 254, 0)
        val fake = FakeLoad(two, result().copy(slot = l), result(confirmed = true).copy(slot = l))
        val vm = LoadViewModel(fake)
        vm.start(spool); runCurrent()
        vm.pickPrinter(printer); runCurrent()
        val pick = vm.state.value as LoadUiState.PickSlot
        assertEquals(
            listOf("Ext-L (external left spool holder) · TPU", "Ext-R (external right spool holder) · empty"),
            pick.slots!!.map { LoadHelp.slotLine(it, pick.units) },
        )
        vm.pickSlot("Ext-L"); runCurrent()
        assertTrue((vm.state.value as LoadUiState.Preview).lines[0].endsWith("the external left spool holder"))
        vm.back(); runCurrent()
        assertEquals("units survive going back", 2, (vm.state.value as LoadUiState.PickSlot).units.size)
        vm.pickSlot("Ext-L"); runCurrent()
        vm.confirm(); runCurrent()
        assertEquals("Loaded into Garage H2D, the external left spool holder", (vm.state.value as LoadUiState.Done).lines[0])
    }

    @Test fun doneListsTheSpoolsMovedBack() = runTest(dispatcher) {
        load.real = result(confirmed = true).copy(movedBack = listOf(MovedBack(3, "Shelf 1"), MovedBack(9, ""),
            MovedBack(7, "Garage H2D – AMS A1")))
        val vm = loadVm()
        vm.toPreview()
        vm.confirm(); runCurrent()
        val d = vm.state.value as LoadUiState.Done
        // by name when the slot showed it, else by number; the spool just loaded is not listed
        assertEquals(listOf("Loaded into Garage H2D, slot A1", "Moved back: Acme Basic Black → Shelf 1",
            "Moved back: #9 → its previous place"), d.lines)
    }

    @Test fun loadPreviewsWithDryRunThenConfirms() = runTest(dispatcher) {
        val vm = loadVm()
        vm.toPreview()
        val p = vm.state.value as LoadUiState.Preview
        assertEquals(listOf(Triple("A1", 7, true)), load.loads)
        assertTrue(p.lines.any { "SUNLU PLA Red @H2D 0.4" in it })
        assertTrue(p.lines.any { "A1" in it })
        assertTrue(p.lines.contains("Nozzle size not reported by the printer; assuming 0.4 mm"))
        vm.confirm()
        runCurrent()
        assertEquals(Triple("A1", 7, false), load.loads[1])
        val d = vm.state.value as LoadUiState.Done
        assertTrue(d.lines.first().contains("Loaded"))
        assertEquals(7, d.spool!!.id)
    }

    @Test fun previewNamesTheSpoolThatGoesBack() = runTest(dispatcher) {
        load.preview = result().copy(movedBack = listOf(MovedBack(3, "Shelf 1")))
        val vm = loadVm()
        vm.toPreview()
        val p = vm.state.value as LoadUiState.Preview
        assertTrue(p.lines.contains("Spool #3 now in A1 goes back to Shelf 1"))
    }

    @Test fun previewWithReportedNozzleHasNoAssumedLine() = runTest(dispatcher) {
        load.preview = result(assumed = false)
        val vm = loadVm()
        vm.toPreview()
        val p = vm.state.value as LoadUiState.Preview
        assertFalse(p.lines.any { "assuming" in it })
        assertTrue(p.lines.any { "0.4 mm" in it })
    }

    @Test fun unconfirmedLoadSaysSoAndShowsProblems() = runTest(dispatcher) {
        load.real = result(confirmed = false, problems = listOf("A1: not confirmed within 10 s"))
        val vm = loadVm()
        vm.toPreview()
        vm.confirm()
        runCurrent()
        val d = vm.state.value as LoadUiState.Done
        assertTrue(d.lines.contains("The printer accepted it but hasn't shown the change yet"))
        assertTrue(d.lines.contains("A1: not confirmed within 10 s"))
    }

    @Test fun noPresetShowsTheProfilesMessage() = runTest(dispatcher) {
        load.loadError = ApiError(409, "no_preset", "no preset for SUNLU PLA on H2D 0.4")
        val vm = loadVm()
        vm.toPreview()
        val s = vm.state.value as LoadUiState.PickSlot
        assertEquals(
            "No preset for this filament on this printer yet. It is made at the next preset build; see Presets on the home screen.",
            s.error,
        )
    }

    @Test fun busyPrinterSaysTryWhenIdle() = runTest(dispatcher) {
        load.loadError = ApiError(409, "printer_busy", "printing")
        val vm = loadVm()
        vm.toPreview()
        val s = vm.state.value as LoadUiState.PickSlot
        assertEquals(PrinterHelp.message(ApiError(409, "printer_busy", "")), s.error)
        assertTrue(s.error!!.contains("printing"))
        assertTrue(s.error!!.contains("idle"))
    }

    @Test fun confirmFailureStaysOnPreviewWithTheMessage() = runTest(dispatcher) {
        val vm = loadVm()
        vm.toPreview()
        load.loadError = ApiError(409, "write_refused", "x")
        vm.confirm()
        runCurrent()
        val p = vm.state.value as LoadUiState.Preview
        assertEquals("The printer refused the change", p.error)
        assertFalse(p.busy)
    }

    @Test fun certChangedErrorSaysWhenToReAddAndWhenToCheckTheIp() = runTest(dispatcher) {
        load.loadError = ApiError(409, "cert_changed", "x")
        val vm = loadVm()
        vm.toPreview()
        val msg = (vm.state.value as LoadUiState.PickSlot).error!!
        assertTrue(msg.startsWith("The printer's certificate changed."))
        assertTrue(msg.contains("If you reset the printer or its mainboard was replaced"))
        assertTrue(msg.contains("check the printer's IP before re-adding"))
    }

    @Test fun loadMismatchAndUnauthorized() = runTest(dispatcher) {
        load.loadError = FingerprintMismatch("aa", "bb")
        val vm = loadVm()
        vm.toPreview()
        assertEquals(LoadUiState.Mismatch("aa", "bb"), vm.state.value)
        load.loadError = ApiError(401, "unauthorized", "x")
        vm.toPreview()
        assertEquals(LoadUiState.Unauthorized, vm.state.value)
    }

    @Test fun closeIsIgnoredWhileARealLoadIsInFlight() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        load.gate = gate
        val vm = loadVm()
        vm.toPreview()
        assertFalse(vm.writing)
        vm.confirm()
        runCurrent()
        assertTrue(vm.writing)
        assertFalse("dismiss refused while writing", vm.close())
        vm.back()
        assertTrue((vm.state.value as LoadUiState.Preview).busy)
        gate.complete(Unit)
        runCurrent()
        assertTrue("the user sees the write's result", vm.state.value is LoadUiState.Done)
        assertFalse(vm.writing)
        assertTrue(vm.close())
        assertEquals(LoadUiState.Closed, vm.state.value)
    }

    @Test fun pairingAgainDuringARealLoadKeepsTheCardForTheResult() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        load.gate = gate
        val vm = loadVm()
        vm.toPreview()
        vm.confirm(); runCurrent()
        var cardDismissed = false
        closeSpoolCard(vm) { cardDismissed = true } // what the app does on a trip to the Pair screen
        assertFalse("the card stays while the load is written", cardDismissed)
        assertTrue(vm.writing)
        gate.complete(Unit); runCurrent()
        assertTrue("the result shows once it arrives", vm.state.value is LoadUiState.Done)
        closeSpoolCard(vm) { cardDismissed = true }
        assertTrue(cardDismissed)
        assertEquals(LoadUiState.Closed, vm.state.value)
        // with no load flow at all the card just closes
        var closed = false
        closeSpoolCard(null) { closed = true }
        assertTrue(closed)
    }

    @Test fun aRealLoadRefusedFor401StaysOnThePreviewSayingNothingChanged() = runTest(dispatcher) {
        val vm = loadVm()
        vm.toPreview()
        load.loadError = ApiError(401, "unauthorized", "Token revoked")
        vm.confirm(); runCurrent()
        val p = vm.state.value as LoadUiState.Preview
        assertEquals(LoadHelp.NOT_SENT_PAIRING, p.error)
        assertFalse(p.busy)
        // after pairing again, Load works from the same preview
        load.loadError = null
        vm.confirm(); runCurrent()
        assertTrue(vm.state.value is LoadUiState.Done)
    }

    @Test fun aRealLoadCutOffSaysToCheckThePrinter() = runTest(dispatcher) {
        val vm = loadVm()
        vm.toPreview()
        load.loadError = ApiError(0, "offline", "The connection to the server was lost")
        vm.confirm(); runCurrent()
        val p = vm.state.value as LoadUiState.Preview
        assertEquals(LoadHelp.CHECK_PRINTER, p.error)
        assertTrue(p.error!!.contains("Check the printer"))
    }

    @Test fun closeDuringTheDryRunStillCancels() = runTest(dispatcher) {
        val vm = loadVm()
        vm.start(spool)
        runCurrent()
        vm.pickPrinter(printer)
        runCurrent()
        vm.pickSlot("A1")
        assertTrue(vm.close())
        runCurrent()
        assertEquals(LoadUiState.Closed, vm.state.value)
    }

    @Test fun backAndClose() = runTest(dispatcher) {
        val vm = loadVm()
        vm.toPreview()
        vm.back()
        assertTrue(vm.state.value is LoadUiState.PickSlot)
        vm.back()
        assertTrue(vm.state.value is LoadUiState.PickPrinter)
        vm.close()
        assertEquals(LoadUiState.Closed, vm.state.value)
    }

    // ---- map slots + filament used --------------------------------------------------------------------

    private class FakeTools : PrinterToolsBackend {
        var statuses = ArrayDeque<MapStatus>()
        var last = MapStatus(state = "none")
        var mapCalls = 0
        var starts = 0
        var startError: Exception? = null
        var usage = listOf<UsageEntry>()
        var usageCalls = 0
        val undos = mutableListOf<String>()
        var undoError: Exception? = null

        override suspend fun startMap(id: String): String {
            starts++
            startError?.let { throw it }
            return "j-1"
        }
        var mapErrors = 0
        /** When set, the next map fetch is held (and cannot be cancelled, like a blocking read) until it completes. */
        var mapGate: CompletableDeferred<Unit>? = null
        override suspend fun mapStatus(id: String): MapStatus {
            mapCalls++
            mapGate?.let { g ->
                mapGate = null
                val answer = last
                withContext(NonCancellable) { g.await() }
                return answer // what the printer said when this fetch was sent
            }
            if (mapErrors > 0) {
                mapErrors--
                throw ApiError(0, "offline", "x")
            }
            if (statuses.isNotEmpty()) last = statuses.removeFirst()
            return last
        }
        override suspend fun report(id: String) = error("not used here")
        override suspend fun usage(id: String, days: Int): List<UsageEntry> {
            usageCalls++
            return usage
        }
        override suspend fun undoUsage(entryId: String): UsageEntry {
            undos += entryId
            undoError?.let { throw it }
            return usage.first { it.id == entryId }.copy(undone = true)
        }
    }

    private val tools = FakeTools()
    private fun toolsVm() = PrinterToolsViewModel(tools, "0948AB", pollMs = 2000)

    private fun running(step: String) = MapStatus(state = "running", step = step)

    @Test fun mapNeedsConfirmThenPollsUntilDone() = runTest(dispatcher) {
        val vm = toolsVm()
        vm.start()
        runCurrent()
        assertEquals(1, tools.mapCalls)
        vm.askMap()
        assertTrue(vm.state.value.confirmMap)
        assertEquals(0, tools.starts)
        tools.statuses.addAll(listOf(running("Testing A1"), running("Testing A2"),
            MapStatus(state = "done", slots = listOf(MapSlot("A1", 0, 0, 0)), calibrated = true, problems = listOf("A3: not confirmed"))))
        vm.confirmMap()
        runCurrent()
        assertFalse(vm.state.value.confirmMap)
        assertEquals(1, tools.starts)
        assertEquals("Testing A1", vm.state.value.map!!.step)
        advanceTimeBy(2001)
        assertEquals("Testing A2", vm.state.value.map!!.step)
        advanceTimeBy(2001)
        assertEquals("done", vm.state.value.map!!.state)
        assertEquals(listOf("A3: not confirmed"), vm.state.value.map!!.problems)
        val calls = tools.mapCalls
        advanceTimeBy(10_000)
        assertEquals("polling stops when done", calls, tools.mapCalls)
        vm.stop()
    }

    @Test fun anOldPollAnsweringAfterConfirmDoesNotHideTheNewJob() = runTest(dispatcher) {
        // the screen's first poll is still out (it will say the last job is done) when the user confirms a new map
        tools.last = MapStatus(state = "done", calibrated = true)
        val gate = CompletableDeferred<Unit>()
        tools.mapGate = gate
        val vm = toolsVm()
        vm.start()
        runCurrent()
        assertEquals(1, tools.mapCalls)
        vm.askMap()
        tools.last = running("Testing A1")
        vm.confirmMap()
        runCurrent()
        assertEquals(1, tools.starts)
        assertEquals("Testing A1", vm.state.value.map!!.step)
        gate.complete(Unit) // the old answer arrives late
        runCurrent()
        assertEquals("the stale 'done' is dropped", "running", vm.state.value.map!!.state)
        val calls = tools.mapCalls
        advanceTimeBy(2001)
        assertTrue("the new job is still followed", tools.mapCalls > calls)
        tools.statuses.add(MapStatus(state = "done", calibrated = true))
        advanceTimeBy(2001)
        assertEquals("done", vm.state.value.map!!.state)
        vm.stop()
    }

    @Test fun mapPollingStopsWhenTheScreenLeaves() = runTest(dispatcher) {
        tools.last = running("Testing A1")
        val vm = toolsVm()
        vm.start()
        runCurrent()
        advanceTimeBy(2001)
        assertEquals(2, tools.mapCalls)
        vm.stop()
        advanceTimeBy(10_000)
        assertEquals(2, tools.mapCalls)
    }

    @Test fun mapAlreadyRunningJustFollowsIt() = runTest(dispatcher) {
        tools.startError = ApiError(409, "already_running", "x")
        tools.last = running("Testing B1")
        val vm = toolsVm()
        vm.askMap()
        vm.confirmMap()
        runCurrent()
        assertEquals("Testing B1", vm.state.value.map!!.step)
        assertNull(vm.state.value.mapMessage)
        vm.stop()
    }

    @Test fun mapBusyShowsTheMessage() = runTest(dispatcher) {
        tools.startError = ApiError(409, "printer_busy", "x")
        val vm = toolsVm()
        vm.askMap()
        vm.confirmMap()
        runCurrent()
        assertEquals(PrinterHelp.message(ApiError(409, "printer_busy", "")), vm.state.value.mapMessage)
    }

    @Test fun observeModeShowsTheNotice() = runTest(dispatcher) {
        tools.last = MapStatus(state = "none", observe = true)
        val vm = toolsVm()
        vm.start()
        runCurrent()
        assertEquals("Filament use is only logged for this printer, not taken off spools, until slot mapping succeeds",
            vm.state.value.observeNotice)
        vm.stop()
    }

    private fun entry(id: String, observe: Boolean = false, undone: Boolean = false, error: String? = null) =
        UsageEntry(id = id, at = "2026-11-01T14:10:00-05:00", job = "Benchy", grams = 12.5, spoolId = 7, slot = "A1",
            observe = observe, undone = undone, error = error)

    @Test fun undoConfirmsThenRefreshesTheList() = runTest(dispatcher) {
        tools.usage = listOf(entry("e2"), entry("e1"))
        val vm = toolsVm()
        vm.start()
        runCurrent()
        assertEquals(listOf("e2", "e1"), vm.state.value.usage.map { it.id })
        vm.askUndo(tools.usage[0])
        assertEquals("e2", vm.state.value.undoTarget!!.id)
        assertTrue(tools.undos.isEmpty())
        tools.usage = listOf(entry("e2", undone = true), entry("e1"))
        val before = tools.usageCalls
        vm.confirmUndo()
        runCurrent()
        assertEquals(listOf("e2"), tools.undos)
        assertNull(vm.state.value.undoTarget)
        assertEquals(before + 1, tools.usageCalls)
        assertTrue(vm.state.value.usage[0].undone)
        vm.stop()
    }

    @Test fun undoErrorsUseThePlainMessages() = runTest(dispatcher) {
        tools.usage = listOf(entry("e2"))
        val vm = toolsVm()
        vm.start()
        runCurrent()
        for ((code, text) in listOf(
            "too_old" to "Older than 7 days, can't undo",
            "nothing_to_undo" to "Nothing was taken off a spool for this one",
        )) {
            tools.undoError = ApiError(409, code, "x")
            vm.askUndo(tools.usage[0])
            vm.confirmUndo()
            runCurrent()
            assertEquals(text, vm.state.value.usageMessage)
        }
        tools.undoError = ApiError(409, "already_undone", "x")
        vm.askUndo(tools.usage[0])
        vm.confirmUndo()
        runCurrent()
        assertTrue(vm.state.value.usageMessage!!.contains("already undone"))
        vm.stop()
    }

    @Test fun usageLinesMarkObserveErrorsAndUndo() {
        assertTrue(UsageHelp.canUndo(entry("a")))
        assertFalse(UsageHelp.canUndo(entry("a", observe = true)))
        assertFalse(UsageHelp.canUndo(entry("a", undone = true)))
        assertFalse(UsageHelp.canUndo(entry("a", error = "spoolman_failed")))
        assertEquals("12.5 g · Benchy · A1", UsageHelp.line(entry("a")))
        assertEquals("logged only", UsageHelp.note(entry("a", observe = true)))
        assertEquals("undone", UsageHelp.note(entry("a", undone = true)))
        assertNull(UsageHelp.note(entry("a")))
        // every real code (route-contract addendum) has its own short reason, not the generic fallback
        val codes = listOf("file_not_found", "no_slice_info", "plate_not_found", "printer_unreachable", "cert_changed",
            "spoolman_unreachable", "spoolman_failed", "ambiguous_spool", "no_mapping", "unmapped_slot")
        val generic = UsageHelp.note(entry("a", error = "something_new"))!!
        assertTrue(generic.contains("something new"))
        for (c in codes) {
            val n = UsageHelp.note(entry("a", error = c))
            assertNotNull(n)
            assertFalse("$c has its own reason", n == generic.replace("something new", c.replace('_', ' ')))
        }
        assertTrue(UsageHelp.note(entry("a", error = "ambiguous_spool"))!!.contains("two spools are set to that slot"))
        assertTrue(UsageHelp.note(entry("a", error = "file_not_found"))!!.contains("print file not found on the printer"))
        assertTrue(UsageHelp.note(entry("a", error = "no_mapping"))!!.contains("the printer didn't say which slots it used"))
        assertTrue(UsageHelp.note(entry("a", error = "unmapped_slot"))!!
            .contains("that slot isn't in the slot map — run Map slots"))
    }

    @Test fun noSpoolInTheSlotSaysNothingWasTakenOff() {
        val e = entry("a").copy(spoolId = null)
        assertEquals("no spool in that slot, nothing taken off", UsageHelp.note(e))
        assertFalse(UsageHelp.canUndo(e))
        assertEquals("logged only", UsageHelp.note(e.copy(observe = true)))
    }

    @Test fun mapPollRetriesWithCappedBackoffAfterAnError() = runTest(dispatcher) {
        tools.last = running("Testing A1")
        val vm = toolsVm()
        vm.start()
        runCurrent()
        assertEquals(1, tools.mapCalls)
        tools.mapErrors = 100 // the network drops for a long while
        advanceTimeBy(120_000)
        val during = tools.mapCalls - 1
        // backoff 2, 4, 8, 16, 30, 30 ... s: a handful of calls in two minutes, never a tight loop
        assertTrue("retried ($during)", during in 4..9)
        assertNotNull(vm.state.value.mapMessage)
        assertTrue(vm.state.value.mapRunning)
        tools.mapErrors = 0
        tools.statuses.add(MapStatus(state = "done", calibrated = true))
        advanceTimeBy(30_001)
        assertEquals("done", vm.state.value.map!!.state)
        assertNull("the poll error clears once polling works again", vm.state.value.mapMessage)
        vm.stop()
    }

    @Test fun mapPollingReArmsOnTheNextStart() = runTest(dispatcher) {
        tools.last = running("Testing A1")
        val vm = toolsVm()
        vm.start()
        runCurrent()
        vm.stop()
        tools.statuses.add(MapStatus(state = "done"))
        vm.start()
        runCurrent()
        assertEquals("done", vm.state.value.map!!.state)
        vm.stop()
    }

    // ---- printer state text ---------------------------------------------------------------------------

    @Test fun certChangedStateText() {
        assertEquals("Certificate changed", PrinterHelp.stateLabel("cert_changed"))
        assertEquals(
            "The printer's certificate changed. If you reset the printer or its mainboard was replaced, add it again " +
                "with its Access Code. If not, something else may be answering at the printer's address — check the " +
                "printer's IP before re-adding.",
            PrinterHelp.fix("cert_changed"),
        )
        assertFalse(PrinterHelp.CERT_CHANGED.contains("usually clears"))
        // M4: the camera says the same, not the generic "could not be shown"
        assertEquals(PrinterHelp.CERT_CHANGED, PrinterHelp.cameraFix("cert_changed"))
        assertEquals(PrinterHelp.fix("cert_changed"), PrinterHelp.message(ApiError(409, "cert_changed", "x")))
        assertEquals(PrinterHelp.fix("needs_developer_mode"), PrinterHelp.message(ApiError(409, "needs_developer_mode", "x")))
    }
}
