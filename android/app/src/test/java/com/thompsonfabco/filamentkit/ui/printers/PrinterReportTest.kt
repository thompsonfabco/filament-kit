package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.MapStatus
import com.thompsonfabco.filamentkit.net.PrinterReport
import com.thompsonfabco.filamentkit.net.UsageEntry
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
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

/** "Collect a report" on the printer screen: the call, the state the share sheet reads, the file name. */
@OptIn(ExperimentalCoroutinesApi::class)
class PrinterReportTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    private class Fake : PrinterToolsBackend {
        var calls = 0
        var gate: CompletableDeferred<Unit>? = null
        var error: Exception? = null
        val report = PrinterReport("report-N6.xml", "<printer-report/>")
        override suspend fun startMap(id: String) = "j-1"
        override suspend fun mapStatus(id: String) = MapStatus()
        override suspend fun report(id: String): PrinterReport {
            calls++
            gate?.await()
            error?.let { throw it }
            return report
        }
        override suspend fun usage(id: String, days: Int) = emptyList<UsageEntry>()
        override suspend fun undoUsage(entryId: String) = error("not used")
    }

    private val fake = Fake()
    private val vm = PrinterToolsViewModel(fake, "0948AB")

    @Test fun collectingHandsTheReportToTheScreenOnce() = runTest(dispatcher) {
        vm.collectReport()
        runCurrent()
        val s = vm.state.value
        assertEquals(fake.report, s.report)
        assertFalse(s.reportBusy)
        assertNull(s.reportMessage)
        vm.reportShown()
        assertNull(vm.state.value.report)
        assertEquals(1, fake.calls)
    }

    @Test fun aSecondTapWhileBusyDoesNotCallAgain() = runTest(dispatcher) {
        fake.gate = CompletableDeferred()
        vm.collectReport()
        runCurrent()
        assertTrue(vm.state.value.reportBusy)
        vm.collectReport()
        fake.gate!!.complete(Unit)
        runCurrent()
        assertEquals(1, fake.calls)
        assertFalse(vm.state.value.reportBusy)
    }

    @Test fun aRefusalIsShownAndNothingIsShared() = runTest(dispatcher) {
        fake.error = ApiError(409, "printer_offline", "The printer is offline")
        vm.collectReport()
        runCurrent()
        val s = vm.state.value
        assertNull(s.report)
        assertTrue(s.reportMessage!!.isNotBlank())
        assertFalse(s.reportBusy)
    }

    @Test fun aShareSheetProblemIsShown() = runTest(dispatcher) {
        vm.collectReport()
        runCurrent()
        vm.reportShown(ReportHelp.NO_APP)
        assertNull(vm.state.value.report)
        assertEquals(ReportHelp.NO_APP, vm.state.value.reportMessage)
    }

    @Test fun anUnpairedPhoneIsNotAnErrorLine() = runTest(dispatcher) {
        fake.error = ApiError(401, "unauthorized", "x")
        vm.collectReport()
        runCurrent()
        assertTrue(vm.state.value.unauthorized)
        assertNull(vm.state.value.reportMessage)
    }

    @Test fun theReasonShowsOnlyWhenTheServerAsks() {
        assertNull(ReportHelp.wanted(null))
        assertNull(ReportHelp.wanted(MapStatus()))
        assertEquals("Why.", ReportHelp.wanted(MapStatus(reportWanted = "no_scheme", reportWhy = "Why.")))
        assertEquals("A printer report would help.", ReportHelp.wanted(MapStatus(reportWanted = "new_code")))
    }

    @Test fun theFileNameIsTheServersWhenPlain() {
        assertEquals("report-N6-20261110-1530.xml", ReportHelp.fileName("report-N6-20261110-1530.xml"))
    }

    @Test fun theFileNameCannotLeaveTheReportFolder() {
        assertEquals("passwd.xml", ReportHelp.fileName("../../etc/passwd"))
        assertEquals("x.xml", ReportHelp.fileName("..\\..\\x.xml"))
        assertEquals("a_b_c.xml", ReportHelp.fileName("a b:c"))
        assertEquals("printer-report.xml", ReportHelp.fileName(""))
        assertEquals("printer-report.xml", ReportHelp.fileName("../"))
        assertEquals("hidden.xml", ReportHelp.fileName(".hidden"))
        assertTrue(ReportHelp.fileName("x".repeat(500)).length <= 100)
    }

    @Test fun thePrivacyLineNamesWhatIsNotInTheFile() {
        for (w in listOf("serial", "address", "name", "account id")) assertTrue(w, ReportHelp.PRIVACY.contains(w))
    }
}
