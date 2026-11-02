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
import com.thompsonfabco.filamentkit.net.UsageEntry
import com.thompsonfabco.filamentkit.ui.printers.PrinterHelp
import com.thompsonfabco.filamentkit.ui.printers.PrinterToolsBackend
import com.thompsonfabco.filamentkit.ui.printers.PrinterToolsViewModel
import com.thompsonfabco.filamentkit.ui.printers.UsageHelp
import kotlinx.coroutines.Dispatchers
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
        AmsUnit(0, "A", "ams", listOf(AmsSlot(0, "A1", "PLA", "FFFFFF"), AmsSlot(1, "A2"))),
        AmsUnit(128, "HT-A", "ams_ht", listOf(AmsSlot(0, "HT-A", "PETG"))),
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
        var printers = listOf(detail.printer, Printer(id = "X", name = "X", serial = "X", configured = false))
        override suspend fun printers() = printers
        override suspend fun printer(id: String) = detail
        override suspend fun load(id: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult {
            loads += Triple(label, spoolId, dryRun)
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
        assertEquals(listOf("A1", "A2", "HT-A"), slots.slots!!.map { it.label })
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
        assertEquals("No preset for this filament on this printer yet — profiles come next", s.error)
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

    @Test fun certChangedErrorExplainsWithoutPushingReAdd() = runTest(dispatcher) {
        load.loadError = ApiError(409, "cert_changed", "x")
        val vm = loadVm()
        vm.toPreview()
        val msg = (vm.state.value as LoadUiState.PickSlot).error!!
        assertTrue(msg.startsWith("The printer's certificate changed."))
        assertTrue(msg.contains("only if you expected this"))
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
        override suspend fun mapStatus(id: String): MapStatus {
            mapCalls++
            if (statuses.isNotEmpty()) last = statuses.removeFirst()
            return last
        }
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
        assertEquals("Filament use is only being logged for this printer until slot mapping succeeds",
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
        assertFalse(UsageHelp.canUndo(entry("a", error = "no_spool")))
        assertEquals("12.5 g · Benchy · A1", UsageHelp.line(entry("a")))
        assertEquals("logged only", UsageHelp.note(entry("a", observe = true)))
        assertEquals("undone", UsageHelp.note(entry("a", undone = true)))
        assertNotNull(UsageHelp.note(entry("a", error = "no_spool")))
        assertNull(UsageHelp.note(entry("a")))
    }

    // ---- printer state text ---------------------------------------------------------------------------

    @Test fun certChangedStateText() {
        assertEquals("Certificate changed", PrinterHelp.stateLabel("cert_changed"))
        assertEquals(
            "The printer's certificate changed. This usually clears by itself when the printer comes back at its " +
                "usual address. Add it again with its Access Code only if you expected this (factory reset or a new " +
                "mainboard).",
            PrinterHelp.fix("cert_changed"),
        )
        assertEquals(PrinterHelp.fix("cert_changed"), PrinterHelp.message(ApiError(409, "cert_changed", "x")))
        assertEquals(PrinterHelp.fix("needs_developer_mode"), PrinterHelp.message(ApiError(409, "needs_developer_mode", "x")))
    }
}
