package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.MapSlot
import com.thompsonfabco.filamentkit.net.MapStatus
import com.thompsonfabco.filamentkit.net.UsageEntry
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
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PrinterLoadTest {
    private val dispatcher = StandardTestDispatcher()

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
        assertNull(vm.state.value.mapProblem)
        vm.stop()
    }

    @Test fun mapBusyShowsTheMessage() = runTest(dispatcher) {
        tools.startError = ApiError(409, "printer_busy", "The printer is printing.")
        val vm = toolsVm()
        vm.askMap()
        vm.confirmMap()
        runCurrent()
        assertEquals(com.thompsonfabco.filamentkit.ui.printers.Problem.HubSaid("The printer is printing."), vm.state.value.mapProblem)
        assertFalse("the question closes when the start request is over", vm.state.value.confirmMap)
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
        // the Hub's own message is shown as given
        for (code in listOf("too_old", "nothing_to_undo", "already_undone")) {
            tools.undoError = ApiError(409, code, "The Hub says $code.")
            vm.askUndo(tools.usage[0])
            vm.confirmUndo()
            runCurrent()
            assertEquals(com.thompsonfabco.filamentkit.ui.printers.Problem.HubSaid("The Hub says $code."), vm.state.value.usageProblem)
        }
        vm.stop()
    }

    @Test fun usageLinesMarkObserveErrorsAndUndo() {
        assertTrue(UsageHelp.canUndo(entry("a")))
        assertFalse(UsageHelp.canUndo(entry("a", observe = true)))
        assertFalse(UsageHelp.canUndo(entry("a", undone = true)))
        assertFalse(UsageHelp.canUndo(entry("a", error = "spoolman_failed")))
        assertEquals(
            com.thompsonfabco.filamentkit.ui.printers.Say.Words(R.string.printer_usage_headline, listOf("12.5", "Benchy", "A1")),
            UsageHelp.headline(entry("a")),
        )
        assertEquals(com.thompsonfabco.filamentkit.ui.printers.Say.Words(R.string.printer_usage_note_logged), usageNote(entry("a", observe = true)))
        assertEquals(com.thompsonfabco.filamentkit.ui.printers.Say.Words(R.string.printer_usage_note_undone), usageNote(entry("a", undone = true)))
        assertNull(usageNote(entry("a")))
        // every real code (route-contract addendum) has its own reason; an unknown one reads as its code with spaces
        val codes = listOf("file_not_found", "no_slice_info", "plate_not_found", "printer_unreachable", "cert_changed",
            "spoolman_unreachable", "spoolman_failed", "ambiguous_spool", "no_mapping", "unmapped_slot")
        for (c in codes) assertNotNull("$c has its own reason", usageReason(c))
        assertNull(usageReason("something_new"))
        assertEquals(
            com.thompsonfabco.filamentkit.ui.printers.Say.Words(
                R.string.printer_usage_note_not_taken,
                listOf(com.thompsonfabco.filamentkit.ui.printers.UsageReason.Other("something new")),
            ),
            usageNote(entry("a", error = "something_new")),
        )
    }

    @Test fun noSpoolInTheSlotSaysNothingWasTakenOff() {
        val e = entry("a").copy(spoolId = null)
        assertEquals(com.thompsonfabco.filamentkit.ui.printers.Say.Words(R.string.printer_usage_note_no_spool), usageNote(e))
        assertFalse(UsageHelp.canUndo(e))
        assertEquals(com.thompsonfabco.filamentkit.ui.printers.Say.Words(R.string.printer_usage_note_logged), usageNote(e.copy(observe = true)))
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
        assertNotNull(vm.state.value.mapProblem)
        assertTrue(vm.state.value.mapRunning)
        tools.mapErrors = 0
        tools.statuses.add(MapStatus(state = "done", calibrated = true))
        advanceTimeBy(30_001)
        assertEquals("done", vm.state.value.map!!.state)
        assertNull("the poll error clears once polling works again", vm.state.value.mapProblem)
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
