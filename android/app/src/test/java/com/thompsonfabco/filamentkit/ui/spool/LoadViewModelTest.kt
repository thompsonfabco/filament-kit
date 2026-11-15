package com.thompsonfabco.filamentkit.ui.spool

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
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class LoadViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val spool = spoolJson(214).toSpoolSummary()

    private val x1 = Printer(id = "X1A", name = "Workshop X1", model = "X1C", serial = "X1A", configured = true, state = "connected")
    private val voron = Printer(id = "V2", name = "Garage Voron", serial = "V2", configured = true, state = "offline", family = "klipper")
    private val found = Printer(id = "NEW", name = "Found", serial = "NEW", configured = false, state = "not_configured")
    private val detail = PrinterDetail(
        x1,
        PrinterStatus(
            ams = listOf(
                AmsUnit(0, "A", "ams", listOf(AmsSlot(0, "A1", "PETG", "F28A2E"), AmsSlot(1, "A2"))),
                AmsUnit(254, "Ext", "ext", listOf(AmsSlot(0, "Ext", "TPU"))),
            ),
        ),
    )

    private fun plan(confirmed: Boolean = false) = LoadResult(
        slot = LoadSlot("A2", 0, 1), preset = PresetRef("P1", "Polymaker PLA @X1C 0.4"), nozzleMm = 0.4, nozzleAssumed = false,
        confirmed = confirmed, movedBack = listOf(MovedBack(212, "Shelf B")),
    )

    private class FakeLoad(val detail: PrinterDetail, val printerList: List<Printer>, var dry: LoadResult, var real: LoadResult) : LoadBackend {
        val calls = mutableListOf<String>()
        var failure: Pair<String, Exception>? = null
        var gate: CompletableDeferred<Unit>? = null

        private fun check(name: String) {
            val f = failure
            if (f != null && f.first == name) {
                failure = null
                throw f.second
            }
        }

        override suspend fun printers(): List<Printer> {
            calls += "printers"
            check("printers")
            return printerList
        }

        override suspend fun printer(id: String): PrinterDetail {
            calls += "printer:$id"
            check("printer")
            return detail
        }

        override suspend fun load(id: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult {
            calls += "load:$id:$label:$spoolId:dry=$dryRun"
            if (!dryRun) gate?.await()
            check(if (dryRun) "dry" else "load")
            return if (dryRun) dry else real
        }
    }

    private lateinit var backend: FakeLoad

    @Before fun setUp() {
        Dispatchers.setMain(dispatcher)
        SpoolCache.clear()
        backend = FakeLoad(detail, listOf(x1, voron, found), plan(), plan(confirmed = true))
    }

    @After fun tearDown() = Dispatchers.resetMain()

    @Test fun theConfiguredPrintersAreListedAndOnlyConnectedOnesCanTakeTheLoad() = runTest(dispatcher) {
        val vm = LoadPrintersViewModel(backend)
        advanceUntilIdle()
        val ui = vm.state.value
        assertEquals(listOf("X1A", "V2"), ui.printers!!.map { it.id })
        assertTrue(canTakeLoad(x1))
        assertFalse(canTakeLoad(voron))
        assertEquals("the one printer that can take it", "X1A", ui.only!!.id)
    }

    @Test fun withTwoPrintersThatCanTakeItTheStepIsNotSkipped() = runTest(dispatcher) {
        backend = FakeLoad(detail, listOf(x1, voron.copy(state = "connected")), plan(), plan())
        val vm = LoadPrintersViewModel(backend)
        advanceUntilIdle()
        assertNull(vm.state.value.only)
    }

    @Test fun noPrintersIsAnEmptyListAndAFailureKeepsNoList() = runTest(dispatcher) {
        backend = FakeLoad(detail, emptyList(), plan(), plan())
        val empty = LoadPrintersViewModel(backend)
        advanceUntilIdle()
        assertEquals(emptyList<Printer>(), empty.state.value.printers)

        backend = FakeLoad(detail, listOf(x1), plan(), plan())
        backend.failure = "printers" to ApiError(0, "offline", "gone")
        val failed = LoadPrintersViewModel(backend)
        advanceUntilIdle()
        assertNull(failed.state.value.printers)
        assertEquals(HubFailure.Unreachable, failed.state.value.failure)
        failed.load()
        advanceUntilIdle()
        assertEquals(1, failed.state.value.printers!!.size)
        assertNull(failed.state.value.failure)
    }

    @Test fun theSlotsComeFromThePrintersUnits() = runTest(dispatcher) {
        val vm = LoadSlotsViewModel("X1A", backend)
        advanceUntilIdle()
        val ui = vm.state.value
        assertEquals("Workshop X1", ui.printer!!.name)
        assertEquals(listOf("A1", "A2", "Ext"), ui.slots!!.map { it.label })
        assertEquals(2, ui.units.size)
    }

    @Test fun aPrinterWithNoLiveStatusHasNoSlots() = runTest(dispatcher) {
        backend = FakeLoad(PrinterDetail(x1, null), listOf(x1), plan(), plan())
        val vm = LoadSlotsViewModel("X1A", backend)
        advanceUntilIdle()
        assertEquals(emptyList<AmsSlot>(), vm.state.value.slots)
    }

    @Test fun thePreviewAsksForADryRunOnEntry() = runTest(dispatcher) {
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend)
        assertTrue(vm.state.value.checking)
        advanceUntilIdle()
        val ui = vm.state.value
        assertFalse(ui.checking)
        assertEquals("Workshop X1", ui.printer!!.name)
        assertEquals("Polymaker PLA @X1C 0.4", ui.plan!!.preset!!.name)
        assertEquals(listOf("printer:X1A", "load:X1A:A2:214:dry=true"), backend.calls)
    }

    @Test fun loadingIsOneWriteAndTheGateSaysItIsBeingWritten() = runTest(dispatcher) {
        val gate = LoadGate()
        val hold = CompletableDeferred<Unit>()
        backend.gate = hold
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend, gate)
        advanceUntilIdle()
        vm.load()
        runCurrent()
        assertTrue(vm.state.value.writing)
        assertTrue("a tag tapped now waits", gate.writing.value)
        vm.load()
        runCurrent()
        hold.complete(Unit)
        advanceUntilIdle()
        assertFalse(gate.writing.value)
        assertEquals("one write, not two", 1, backend.calls.count { it.endsWith("dry=false") })
        assertEquals(SpoolResult.Loaded("Workshop X1", "A2"), vm.state.value.finished)
    }

    @Test fun aLoadThePrinterHasNotShownYetIsAWarnResult() = runTest(dispatcher) {
        backend.real = plan(confirmed = false)
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend)
        advanceUntilIdle()
        vm.load()
        advanceUntilIdle()
        assertEquals(SpoolResult.LoadedUnconfirmed("Workshop X1", "A2"), vm.state.value.finished)
    }

    @Test fun theSpoolTheHubReturnsReachesTheSpoolScreen() = runTest(dispatcher) {
        backend.real = plan(confirmed = true).copy(spool = spoolJson(214, location = "Workshop X1 A2"))
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend)
        advanceUntilIdle()
        vm.load()
        advanceUntilIdle()
        assertEquals("Workshop X1 A2", SpoolCache.get(214)!!.location)
    }

    @Test fun aDroppedConnectionDuringTheWriteSaysItCannotTellAndStaysOpen() = runTest(dispatcher) {
        val gate = LoadGate()
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend, gate)
        advanceUntilIdle()
        backend.failure = "load" to ApiError(0, "offline", "The connection was lost")
        vm.load()
        advanceUntilIdle()
        assertTrue(vm.state.value.dropped)
        assertNull(vm.state.value.finished)
        assertFalse(vm.state.value.writing)
        assertFalse(gate.writing.value)
    }

    @Test fun aRefusedPairingMeansNothingWasChanged() = runTest(dispatcher) {
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend)
        advanceUntilIdle()
        backend.failure = "load" to ApiError(401, "unauthorized", "no")
        vm.load()
        advanceUntilIdle()
        assertTrue(vm.state.value.pairingRefused)
        assertNull("the Hub notice is not shown for it", vm.state.value.failure)
        // trying again works once paired again
        vm.load()
        advanceUntilIdle()
        assertFalse(vm.state.value.pairingRefused)
        assertTrue(vm.state.value.finished is SpoolResult.Loaded)
    }

    @Test fun aRefusalCarriesTheHubsOwnWords() = runTest(dispatcher) {
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend)
        advanceUntilIdle()
        backend.failure = "load" to ApiError(409, "printer_busy", "The printer is printing; try again when it is idle.")
        vm.load()
        advanceUntilIdle()
        assertEquals(HubFailure.Message("The printer is printing; try again when it is idle."), vm.state.value.failure)
        assertFalse(vm.state.value.dropped)
    }

    @Test fun aChangedCertificateAtTheWriteIsTheHubNotice() = runTest(dispatcher) {
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend)
        advanceUntilIdle()
        backend.failure = "load" to FingerprintMismatch("aa", "bb")
        vm.load()
        advanceUntilIdle()
        assertEquals(HubFailure.CertificateChanged, vm.state.value.failure)
    }

    @Test fun aFailedPreviewCanBeAskedAgainAndTheNoticeClears() = runTest(dispatcher) {
        backend.failure = "dry" to ApiError(401, "unauthorized", "no")
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend)
        advanceUntilIdle()
        assertEquals(HubFailure.NotPaired, vm.state.value.failure)
        assertNull(vm.state.value.plan)
        vm.check()
        advanceUntilIdle()
        assertNull(vm.state.value.failure)
        assertTrue(vm.state.value.plan != null)
    }

    @Test fun theGateIsClearedWhenTheScreenGoes() = runTest(dispatcher) {
        val gate = LoadGate()
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend, gate)
        advanceUntilIdle()
        gate.set(true)
        // what the framework does when the screen's entry goes
        val clear = androidx.lifecycle.ViewModel::class.java.getDeclaredMethod("onCleared")
        clear.isAccessible = true
        clear.invoke(vm)
        assertFalse(gate.writing.value)
    }

    // 05 7.6 withholds "Try again" after a refusal (failedWrite), not Load: a refusal changed nothing, so Load sends again
    @Test fun aRefusedLoadIsMarkedAsAWriteFailureAndLoadSendsItAgainOnlyWhenPressed() = runTest(dispatcher) {
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend)
        advanceUntilIdle()
        backend.failure = "load" to ApiError(409, "printer_busy", "The printer is printing.")
        vm.load()
        advanceUntilIdle()
        assertTrue(vm.state.value.failedWrite)
        assertEquals("nothing resends by itself", 1, backend.calls.count { it.endsWith("dry=false") })
        vm.check()
        advanceUntilIdle()
        assertEquals("Try again asks for the preview, not the write", 1, backend.calls.count { it.endsWith("dry=false") })
        vm.load()
        advanceUntilIdle()
        assertEquals(2, backend.calls.count { it.endsWith("dry=false") })
        assertFalse(vm.state.value.failedWrite)
        assertTrue(vm.state.value.finished != null)
    }

    @Test fun anAnswerTheAppCannotReadIsAnUnknownOutcomeNotARefusal() = runTest(dispatcher) {
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend)
        advanceUntilIdle()
        backend.failure = "load" to ApiError(502, "internal", "The server returned an error (502)", noHubMessage = true)
        vm.load()
        advanceUntilIdle()
        assertTrue(vm.state.value.dropped)
        assertNull(vm.state.value.failure)
        assertFalse(vm.state.value.failedWrite)
    }

    @Test fun theGateSaysWhetherALoadOrALinkIsWritten() = runTest(dispatcher) {
        val gate = LoadGate()
        val hold = CompletableDeferred<Unit>()
        backend.gate = hold
        val vm = LoadPreviewViewModel(spool, "X1A", "A2", backend, gate)
        advanceUntilIdle()
        vm.load()
        runCurrent()
        assertTrue(gate.writing.value)
        assertFalse(gate.forLink)
        hold.complete(Unit)
        advanceUntilIdle()
    }
}
