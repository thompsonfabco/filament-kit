package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.net.AmsSlot
import com.thompsonfabco.filamentkit.net.AmsUnit
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.CommandResult
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterCamera
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.net.PrinterStatus
import com.thompsonfabco.filamentkit.net.PrinterSummary
import com.thompsonfabco.filamentkit.net.LoadSlot
import com.thompsonfabco.filamentkit.net.MovedBack
import com.thompsonfabco.filamentkit.net.SlotSpool
import com.thompsonfabco.filamentkit.net.UnloadResult
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
class PrinterViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    private fun printer(state: String = "connected", configured: Boolean = true, name: String = "Garage H2D") =
        Printer(id = "0948AB", name = name, model = "H2D", serial = "0948AB", configured = configured, state = state,
            camera = PrinterCamera("hls"), summary = PrinterSummary("RUNNING", 42, 31))

    private fun status(gcode: String = "RUNNING", light: String? = "on") =
        PrinterStatus(gcodeState = gcode, job = "Benchy", percent = 42, light = light)

    private class FakeBackend(var detail: PrinterDetail) : PrinterBackend {
        var printerCalls = 0
        var detailError: Exception? = null
        val commands = mutableListOf<String>()
        var commandError: Exception? = null
        var commandResult = CommandResult(ok = true, reply = Json.parseToJsonElement(
            """{"ok":true,"reply":{"result":"success"}}""").jsonObject)
        var list: List<Printer> = emptyList()
        var listCalls = 0
        val added = mutableListOf<Triple<String, String, String?>>()
        var addResult: Printer? = null
        var addError: Exception? = null

        override suspend fun printers(): List<Printer> {
            listCalls++
            return list
        }
        override suspend fun addPrinter(serial: String, accessCode: String, name: String?): Printer {
            added += Triple(serial, accessCode, name)
            addError?.let { throw it }
            return addResult!!
        }
        val addedKlipper = mutableListOf<Triple<String, Int, String?>>()
        override suspend fun addKlipperPrinter(host: String, port: Int, name: String?): Printer {
            addedKlipper += Triple(host, port, name)
            addError?.let { throw it }
            return addResult!!
        }
        override suspend fun printer(id: String): PrinterDetail {
            printerCalls++
            detailError?.let { throw it }
            return detail
        }
        override suspend fun command(id: String, action: String): CommandResult {
            commands += action
            commandError?.let { throw it }
            return commandResult
        }
        val unloads = mutableListOf<Pair<String, Boolean>>()
        var unloadError: Exception? = null
        var unloadResult = UnloadResult(slot = LoadSlot("A1", 0, 0), location = "Shelf 2",
            movedBack = listOf(MovedBack(7, "Shelf 2")))
        override suspend fun unload(id: String, label: String, dryRun: Boolean): UnloadResult {
            unloads += label to dryRun
            unloadError?.let { throw it }
            return unloadResult
        }
    }

    private val backend = FakeBackend(PrinterDetail(printer(), status()))

    private fun vm() = PrinterViewModel(backend, "0948AB", pollMs = 2000)

    // --- polling ---

    @Test fun pollsEveryTwoSecondsOnlyWhileActive() = runTest(dispatcher) {
        val vm = vm()
        runCurrent()
        assertEquals("nothing is fetched before the screen is visible", 0, backend.printerCalls)
        vm.start()
        runCurrent()
        assertEquals(1, backend.printerCalls)
        assertEquals("Benchy", vm.state.value.status!!.job)
        advanceTimeBy(1999); runCurrent()
        assertEquals(1, backend.printerCalls)
        advanceTimeBy(1); runCurrent()
        assertEquals(2, backend.printerCalls)
        vm.stop()
        advanceTimeBy(60_000); runCurrent()
        assertEquals("no polling after the screen left", 2, backend.printerCalls)
        vm.start()
        runCurrent()
        assertEquals(3, backend.printerCalls)
        vm.stop()
    }

    @Test fun startingTwiceDoesNotPollTwice() = runTest(dispatcher) {
        val vm = vm()
        vm.start(); vm.start()
        runCurrent()
        advanceTimeBy(2000); runCurrent()
        assertEquals(2, backend.printerCalls)
        vm.stop()
    }

    @Test fun pollErrorsKeepPollingAndShowAMessage() = runTest(dispatcher) {
        backend.detailError = ApiError(0, "offline", "x")
        val vm = vm()
        vm.start(); runCurrent()
        assertTrue(vm.state.value.message!!.contains("Could not reach the server"))
        backend.detailError = null
        advanceTimeBy(2000); runCurrent()
        assertNull(vm.state.value.message)
        assertNotNull(vm.state.value.status)
        vm.stop()
    }

    @Test fun unauthorizedStopsPolling() = runTest(dispatcher) {
        backend.detailError = ApiError(401, "unauthorized", "no")
        val vm = vm()
        vm.start(); runCurrent()
        assertTrue(vm.state.value.unauthorized)
        advanceTimeBy(10_000); runCurrent()
        assertEquals(1, backend.printerCalls)
    }

    @Test fun fingerprintMismatchShowsBothAndStops() = runTest(dispatcher) {
        backend.detailError = FingerprintMismatch("aaa", "bbb")
        val vm = vm()
        vm.start(); runCurrent()
        assertEquals("aaa" to "bbb", vm.state.value.mismatch)
        advanceTimeBy(10_000); runCurrent()
        assertEquals(1, backend.printerCalls)
    }

    @Test fun anyOtherExceptionIsUnexpectedResponse() = runTest(dispatcher) {
        backend.detailError = IllegalStateException("boom")
        val vm = vm()
        vm.start(); runCurrent()
        assertEquals("Unexpected response from the server", vm.state.value.message)
        vm.stop()
    }

    // --- controls ---

    @Test fun stopNeedsTwoConfirmsNamingPrinterAndJob() = runTest(dispatcher) {
        val vm = vm()
        vm.start(); runCurrent()
        vm.askStop()
        assertEquals(StopStep.First, vm.state.value.stopStep)
        vm.confirmStop()
        runCurrent()
        assertEquals(StopStep.Second, vm.state.value.stopStep)
        assertTrue(backend.commands.isEmpty())
        val text = vm.state.value.stopQuestion!!
        assertTrue(text, text.contains("Garage H2D") && text.contains("Benchy"))
        vm.confirmStop()
        runCurrent()
        assertEquals(listOf("stop"), backend.commands)
        assertEquals(StopStep.None, vm.state.value.stopStep)
        vm.stop()
    }

    @Test fun cancellingStopSendsNothing() = runTest(dispatcher) {
        val vm = vm()
        vm.start(); runCurrent()
        vm.askStop(); vm.confirmStop(); vm.cancelStop()
        runCurrent()
        assertEquals(StopStep.None, vm.state.value.stopStep)
        vm.confirmStop(); runCurrent()
        assertTrue(backend.commands.isEmpty())
        vm.stop()
    }

    @Test fun offline409ShowsPrinterIsOffline() = runTest(dispatcher) {
        backend.commandError = ApiError(409, "printer_offline", "the printer is offline; check that it is on")
        val vm = vm()
        vm.start(); runCurrent()
        vm.pauseOrResume(); runCurrent()
        assertTrue(vm.state.value.commandMessage!!.contains("printer is offline"))
        assertFalse(vm.state.value.commandBusy)
        vm.stop()
    }

    @Test fun noReplyIsExplained() = runTest(dispatcher) {
        backend.commandError = ApiError(504, "no_reply", "x")
        val vm = vm()
        vm.start(); runCurrent()
        vm.toggleLight(); runCurrent()
        assertTrue(vm.state.value.commandMessage!!.contains("did not answer"))
        vm.stop()
    }

    @Test fun pauseOrResumeFollowsTheState() = runTest(dispatcher) {
        val vm = vm()
        vm.start(); runCurrent()
        vm.pauseOrResume(); runCurrent()
        backend.detail = PrinterDetail(printer(), status(gcode = "PAUSE"))
        advanceTimeBy(2000); runCurrent()
        vm.pauseOrResume(); runCurrent()
        assertEquals(listOf("pause", "resume"), backend.commands)
        vm.stop()
    }

    @Test fun lightToggleFollowsTheLight() = runTest(dispatcher) {
        val vm = vm()
        vm.start(); runCurrent()
        vm.toggleLight(); runCurrent()
        backend.detail = PrinterDetail(printer(), status(light = "off"))
        advanceTimeBy(2000); runCurrent()
        vm.toggleLight(); runCurrent()
        assertEquals(listOf("light_off", "light_on"), backend.commands)
        vm.stop()
    }

    @Test fun commandShowsThePrintersReply() = runTest(dispatcher) {
        val vm = vm()
        vm.start(); runCurrent()
        vm.pauseOrResume(); runCurrent()
        assertTrue(vm.state.value.commandMessage!!, vm.state.value.commandMessage!!.contains("success"))
        backend.commandResult = CommandResult(ok = true, reply = Json.parseToJsonElement(
            """{"ok":false,"reply":{"result":"failed","reason":"not allowed"}}""").jsonObject)
        vm.pauseOrResume(); runCurrent()
        val msg = vm.state.value.commandMessage!!
        assertTrue(msg, msg.contains("refused") && msg.contains("not allowed"))
        vm.stop()
    }

    @Test fun stateFixesAreInPlainWords() {
        assertTrue(PrinterHelp.fix("wrong_code")!!.contains("Access Code"))
        assertTrue(PrinterHelp.fix("needs_developer_mode")!!.contains("Developer Mode"))
        assertNull(PrinterHelp.fix("connected"))
        assertTrue(PrinterHelp.cameraFix("camera_unavailable").contains("Liveview"))
    }

    // --- list + add printer ---

    @Test fun listLoadsAndAddKeepsDialogOnWrongCode() = runTest(dispatcher) {
        backend.list = listOf(printer(state = "not_configured", configured = false, name = "0948AB"))
        val vm = PrintersViewModel(backend)
        vm.refresh(); runCurrent()
        assertEquals(1, vm.state.value.printers.size)
        vm.openAdd(vm.state.value.printers[0])
        assertEquals("0948AB", vm.state.value.dialog!!.serial)
        backend.addResult = printer(state = "wrong_code")
        vm.submitAdd("SECRET42", "Garage")
        runCurrent()
        assertEquals(Triple("0948AB", "SECRET42", "Garage"), backend.added.single())
        val d = vm.state.value.dialog!!
        assertTrue(d.error!!.contains("Access Code"))
        assertFalse("the Access Code is never kept in state", vm.state.value.toString().contains("SECRET42"))
    }

    @Test fun cancelAddReloadsTheList() = runTest(dispatcher) {
        backend.list = listOf(printer(state = "not_configured", configured = false))
        val vm = PrintersViewModel(backend)
        vm.refresh(); runCurrent()
        vm.openAdd(vm.state.value.printers[0])
        backend.list = listOf(printer(state = "wrong_code"))
        vm.cancelAdd(); runCurrent()
        assertNull(vm.state.value.dialog)
        assertEquals(2, backend.listCalls)
        assertEquals("wrong_code", vm.state.value.printers[0].state)
    }

    @Test fun onePrintingSetForListStatusAndControls() {
        for (g in listOf("RUNNING", "PAUSE", "PREPARE", "SLICING")) {
            assertTrue(g, PrinterHelp.isPrinting(g))
            assertTrue(g, PrinterUiState(printer = printer(), status = status(gcode = g)).printing)
            assertNotNull(g, PrinterHelp.jobLine(PrinterSummary(g, 10, 5, "Benchy")))
        }
        for (g in listOf("IDLE", "FINISH", "FAILED", "UNKNOWN")) {
            assertFalse(g, PrinterHelp.isPrinting(g))
            assertFalse(g, PrinterUiState(printer = printer(), status = status(gcode = g)).printing)
            assertNull(g, PrinterHelp.jobLine(PrinterSummary(g, 10, 5, "Benchy")))
        }
    }

    @Test fun listLineShowsJobPercentAndTimeLeft() {
        assertEquals("Benchy · 42% · 31 min left", PrinterHelp.jobLine(PrinterSummary("RUNNING", 42, 31, "Benchy")))
        assertEquals("Benchy · 42% · 1 h 5 min left · paused", PrinterHelp.jobLine(PrinterSummary("PAUSE", 42, 65, "Benchy")))
        assertEquals("42%", PrinterHelp.jobLine(PrinterSummary("RUNNING", 42, 0, null)))
        assertNull(PrinterHelp.jobLine(null)) // no summary: the row shows the state only
    }

    @Test fun addOfAPrinterNotSeenYetShowsTheServersMessage() = runTest(dispatcher) {
        backend.list = listOf(printer())
        val vm = PrintersViewModel(backend)
        vm.refresh(); runCurrent()
        vm.openAdd(vm.state.value.printers[0])
        backend.addError = ApiError(404, "not_found", "That printer hasn't been seen on the network yet")
        vm.submitAdd("1", "")
        runCurrent()
        assertEquals("That printer hasn't been seen on the network yet", vm.state.value.dialog!!.error)
    }

    @Test fun controlsOnlyWhenConnected() {
        assertTrue(PrinterUiState(printer = printer(state = "connected"), status = status()).controlsEnabled)
        for (s in listOf("needs_developer_mode", "offline", "wrong_code", "not_configured")) {
            assertFalse(s, PrinterUiState(printer = printer(state = s), status = status()).controlsEnabled)
        }
        assertFalse(PrinterUiState(printer = printer(), status = status(), commandBusy = true).controlsEnabled)
    }

    @Test fun addConnectedClosesDialogAndRefreshes() = runTest(dispatcher) {
        backend.list = listOf(printer(state = "not_configured", configured = false))
        val vm = PrintersViewModel(backend)
        vm.refresh(); runCurrent()
        vm.openAdd(vm.state.value.printers[0])
        backend.addResult = printer()
        backend.list = listOf(printer())
        vm.submitAdd("12345678", "")
        runCurrent()
        assertNull(vm.state.value.dialog)
        assertEquals(null, backend.added.single().third)
        assertEquals(2, backend.listCalls)
        assertEquals("connected", vm.state.value.printers[0].state)
    }

    @Test fun addExistsIsExplained() = runTest(dispatcher) {
        backend.list = listOf(printer())
        val vm = PrintersViewModel(backend)
        vm.refresh(); runCurrent()
        vm.openAdd(vm.state.value.printers[0])
        backend.addError = ApiError(409, "exists", "x")
        vm.submitAdd("1", "")
        runCurrent()
        assertTrue(vm.state.value.dialog!!.error!!.contains("already set up"))
    }

    @Test fun addKlipperSendsTrimmedAddressDefaultPortAndClosesTheDialog() = runTest(dispatcher) {
        val vm = PrintersViewModel(backend)
        vm.openAddKlipper()
        backend.addResult = printer()
        backend.list = listOf(printer())
        vm.submitAddKlipper(" printer.example.com ", " ", " Shed ")
        runCurrent()
        assertEquals(Triple("printer.example.com", 7125, "Shed" as String?), backend.addedKlipper.single())
        assertNull(vm.state.value.klipper)
        assertEquals(1, backend.listCalls)
        assertEquals(1, vm.state.value.printers.size)
    }

    @Test fun addKlipperOmitsABlankName() = runTest(dispatcher) {
        val vm = PrintersViewModel(backend)
        vm.openAddKlipper()
        backend.addResult = printer()
        vm.submitAddKlipper("192.0.2.10", "7126", "  ")
        runCurrent()
        assertEquals(Triple("192.0.2.10", 7126, null as String?), backend.addedKlipper.single())
    }

    @Test fun addKlipperChecksTheFieldsBeforeAskingTheServer() = runTest(dispatcher) {
        val vm = PrintersViewModel(backend)
        vm.openAddKlipper()
        vm.submitAddKlipper("  ", "7125", "")
        assertTrue(vm.state.value.klipper!!.error!!.contains("address"))
        for (bad in listOf("0", "65536", "abc", "-1", "71.25")) {
            vm.submitAddKlipper("192.0.2.10", bad, "")
            assertTrue(bad, vm.state.value.klipper!!.error!!.contains("between 1 and 65535"))
        }
        runCurrent()
        assertTrue(backend.addedKlipper.isEmpty())
        assertFalse(vm.state.value.klipper!!.busy)
    }

    @Test fun addKlipperKeepsTheDialogWithTheServersSentence() = runTest(dispatcher) {
        val vm = PrintersViewModel(backend)
        vm.openAddKlipper()
        backend.addError = ApiError(400, "bad_request", "a printer is already set up at 192.0.2.10")
        vm.submitAddKlipper("192.0.2.10", "7125", "")
        runCurrent()
        val d = vm.state.value.klipper!!
        assertEquals("a printer is already set up at 192.0.2.10", d.error)
        assertFalse(d.busy)
        backend.addError = ApiError(0, "offline", "x")
        vm.submitAddKlipper("192.0.2.10", "7125", "")
        runCurrent()
        assertTrue(vm.state.value.klipper!!.error!!.contains("Could not reach the server"))
    }

    @Test fun cancelAddKlipperClosesTheDialog() {
        val vm = PrintersViewModel(backend)
        vm.openAddKlipper()
        vm.cancelAddKlipper()
        assertNull(vm.state.value.klipper)
    }

    // --- unload ---

    private val a1 = AmsSlot(0, "A1", "PLA", "CC2222", spool = SlotSpool(7, "Acme Basic Black", "PLA", "cc2222", 812.0))
    private val ext = AmsSlot(0, "Ext", "PETG", "00FF00", spool = SlotSpool(5, "Acme PETG Green", "PETG", "00ff00", 300.0))

    private fun withSlots() {
        backend.detail = PrinterDetail(printer(), status(gcode = "IDLE").copy(ams = listOf(
            AmsUnit(0, "A", "ams", listOf(a1, AmsSlot(1, "A2"))),
            AmsUnit(254, "Ext", "ext", listOf(ext)),
        )))
    }

    @Test fun unloadAsksWithTheDryRunsLocationThenUnloads() = runTest(dispatcher) {
        withSlots()
        val vm = vm()
        vm.start(); runCurrent()
        vm.askUnload(a1)
        runCurrent()
        assertEquals(listOf("A1" to true), backend.unloads)
        assertEquals("Unload Acme Basic Black from slot A1? It goes back to Shelf 2.", vm.state.value.unloadAsk!!.question)
        val calls = backend.printerCalls
        vm.confirmUnload()
        runCurrent()
        assertEquals(listOf("A1" to true, "A1" to false), backend.unloads)
        assertNull(vm.state.value.unloadAsk)
        assertNull(vm.state.value.slotBusy)
        assertEquals(listOf("Unloaded Acme Basic Black from slot A1.", "Moved back: Acme Basic Black → Shelf 2"),
            vm.state.value.slotMessage)
        assertTrue("the status is fetched again", backend.printerCalls > calls)
        vm.stop()
    }

    @Test fun cancellingUnloadSendsOnlyTheDryRun() = runTest(dispatcher) {
        withSlots()
        val vm = vm()
        vm.start(); runCurrent()
        vm.askUnload(a1); runCurrent()
        vm.cancelUnload()
        vm.confirmUnload(); runCurrent()
        assertEquals(listOf("A1" to true), backend.unloads)
        assertNull(vm.state.value.unloadAsk)
        // an empty slot (no inventory spool) offers nothing
        vm.askUnload(AmsSlot(1, "A2"))
        runCurrent()
        assertEquals(1, backend.unloads.size)
        vm.stop()
    }

    @Test fun unloadErrorsUseTheServersWordsForNotFound() = runTest(dispatcher) {
        withSlots()
        backend.unloadError = ApiError(404, "not_found", "no spool is in Garage H2D slot A1")
        val vm = vm()
        vm.start(); runCurrent()
        vm.askUnload(a1); runCurrent()
        assertNull(vm.state.value.unloadAsk)
        assertEquals(listOf("no spool is in Garage H2D slot A1"), vm.state.value.slotMessage)
        assertNull(vm.state.value.slotBusy)
        backend.unloadError = ApiError(409, "already_running", "x")
        vm.askUnload(a1); runCurrent()
        assertEquals(listOf(PrinterHelp.message(ApiError(409, "already_running", ""))), vm.state.value.slotMessage)
        vm.stop()
    }

    @Test fun theExternalHolderUnloadsLikeASlot() = runTest(dispatcher) {
        withSlots()
        backend.unloadResult = UnloadResult(slot = LoadSlot("Ext", 254, 0), location = "Sealed stock",
            movedBack = listOf(MovedBack(5, "Sealed stock")))
        val vm = vm()
        vm.start(); runCurrent()
        vm.askUnload(ext); runCurrent()
        assertEquals("Unload Acme PETG Green from the external spool holder? It goes back to Sealed stock.",
            vm.state.value.unloadAsk!!.question)
        vm.confirmUnload(); runCurrent()
        assertEquals(listOf("Ext" to true, "Ext" to false), backend.unloads)
        assertEquals("Moved back: Acme PETG Green → Sealed stock", vm.state.value.slotMessage[1])
        vm.stop()
    }

    @Test fun unitTitlesAndSlotNames() {
        assertEquals("External spool holder", PrinterHelp.unitTitle(AmsUnit(254, "Ext", "ext")))
        assertEquals("AMS HT HT-A", PrinterHelp.unitTitle(AmsUnit(128, "HT-A", "ams_ht")))
        assertEquals("AMS A", PrinterHelp.unitTitle(AmsUnit(0, "A", "ams")))
        assertEquals("the external spool holder", PrinterHelp.slotName("Ext"))
        assertEquals("slot B3", PrinterHelp.slotName("B3"))
        assertEquals("Moved back: #3 → Shelf 1", PrinterHelp.movedBackLine(null, 3, "Shelf 1"))
        assertEquals("spool #9", PrinterHelp.spoolName(SlotSpool(9)))
    }

    @Test fun externalHoldersAreNamedFromSay() {
        val left = AmsSlot(0, "Ext-L", "PLA", say = listOf("external", "left"))
        val right = AmsSlot(0, "Ext-R", "", say = listOf("external", "right"))
        val units = listOf(
            AmsUnit(0, "A", "ams", listOf(AmsSlot(0, "A1")), typeName = "AMS 2 Pro"),
            AmsUnit(254, "Ext-L", "ext", listOf(left), say = listOf("external", "left")),
            AmsUnit(255, "Ext-R", "ext", listOf(right)),
        )
        assertEquals("the external left spool holder", PrinterHelp.slotName("Ext-L", units))
        assertEquals("the external right spool holder", PrinterHelp.slotName("Ext-R", units))
        assertEquals("slot A1", PrinterHelp.slotName("A1", units))
        assertEquals("External left spool holder", PrinterHelp.unitTitle(units[1]))
        assertEquals("from the slot's say", "External right spool holder", PrinterHelp.unitTitle(units[2]))
        assertEquals("AMS 2 Pro A", PrinterHelp.unitTitle(units[0]))
        assertEquals("Ext-L (external left spool holder)", PrinterHelp.slotLabel(left, units))
        // without the printer's units an Ext-… label still reads as an external holder
        assertEquals("the external spool holder Ext-R", PrinterHelp.slotName("Ext-R"))
        // any unit of kind ext is an external holder, whatever its label
        val odd = listOf(AmsUnit(254, "Spool rack", "ext", listOf(AmsSlot(0, "Spool rack"))))
        assertEquals("the external spool holder Spool rack", PrinterHelp.slotName("Spool rack", odd))
    }

    @Test fun anExternalUnloadUsesTheSayWords() = runTest(dispatcher) {
        val left = ext.copy(label = "Ext-L", say = listOf("external", "left"))
        backend.detail = PrinterDetail(printer(), status(gcode = "IDLE").copy(ams = listOf(
            AmsUnit(254, "Ext-L", "ext", listOf(left)),
        )))
        backend.unloadResult = UnloadResult(slot = LoadSlot("Ext-L", 254, 0), location = "Sealed stock")
        val vm = vm()
        vm.start(); runCurrent()
        vm.askUnload(left); runCurrent()
        assertEquals("Unload Acme PETG Green from the external left spool holder? It goes back to Sealed stock.",
            vm.state.value.unloadAsk!!.question)
        vm.confirmUnload(); runCurrent()
        assertEquals("Unloaded Acme PETG Green from the external left spool holder.", vm.state.value.slotMessage[0])
        vm.stop()
    }

    @Test fun blankCodeIsNotSent() = runTest(dispatcher) {
        backend.list = listOf(printer(state = "not_configured", configured = false))
        val vm = PrintersViewModel(backend)
        vm.refresh(); runCurrent()
        vm.openAdd(vm.state.value.printers[0])
        vm.submitAdd("  ", "")
        runCurrent()
        assertTrue(backend.added.isEmpty())
        assertNotNull(vm.state.value.dialog!!.error)
    }
}
