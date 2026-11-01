package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.CommandResult
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterCamera
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.net.PrinterStatus
import com.thompsonfabco.filamentkit.net.PrinterSummary
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
