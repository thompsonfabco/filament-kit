package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.AmsSlot
import com.thompsonfabco.filamentkit.net.AmsUnit
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.CommandResult
import com.thompsonfabco.filamentkit.net.KlipperFound
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.net.PrinterStatus
import com.thompsonfabco.filamentkit.net.PrinterSummary
import com.thompsonfabco.filamentkit.net.UnloadResult
import com.thompsonfabco.filamentkit.ui.components.StatusKind
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The Printers list (05-android-app 9.1 to 9.3): what a row says, the slots, the Klipper form and the search. */
@OptIn(ExperimentalCoroutinesApi::class)
class PrintersListTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    private class Fake : PrinterBackend {
        var list: List<Printer> = emptyList()
        var listError: Exception? = null
        var details = mutableMapOf<String, PrinterDetail>()
        val detailCalls = mutableListOf<String>()
        val added = mutableListOf<Triple<String, Int, String?>>()
        var addResult: Printer? = null
        var addError: Exception? = null
        val keys = mutableListOf<Pair<String, String>>()
        var keyError: Exception? = null
        val scans = mutableListOf<String?>()
        var scanResult: List<KlipperFound> = emptyList()
        var scanError: Exception? = null

        override suspend fun printers(): List<Printer> {
            listError?.let { throw it }
            return list
        }
        override suspend fun addPrinter(serial: String, accessCode: String, name: String?): Printer = error("not used")
        override suspend fun addKlipperPrinter(host: String, port: Int, name: String?): Printer {
            added += Triple(host, port, name)
            addError?.let { throw it }
            return addResult!!
        }
        override suspend fun scanKlipper(subnet: String?): List<KlipperFound> {
            scans += subnet
            scanError?.let { throw it }
            return scanResult
        }
        override suspend fun setApiKey(id: String, key: String) {
            keys += id to key
            keyError?.let { throw it }
        }
        override suspend fun printer(id: String): PrinterDetail {
            detailCalls += id
            return details[id] ?: throw ApiError(404, "not_found", "no such printer")
        }
        override suspend fun command(id: String, action: String): CommandResult = error("not used")
        override suspend fun unload(id: String, label: String, dryRun: Boolean): UnloadResult = error("not used")
    }

    private val backend = Fake()

    private fun printer(
        id: String = "01S00A",
        state: String = "connected",
        configured: Boolean = true,
        family: String = "bambu",
    ) = Printer(
        id = id, name = "Workshop X1", model = "X1C", serial = id, ip = "192.0.2.40", configured = configured,
        state = state, family = family, summary = PrinterSummary("RUNNING", 42, 72),
    )

    private fun detail(p: Printer, vararg slots: AmsSlot) =
        PrinterDetail(p, PrinterStatus(ams = listOf(AmsUnit(unit = 0, slots = slots.toList()))))

    // --- what a row says ---

    @Test fun everyStateOfTheVocabularyHasItsBadgeAndFix() {
        assertEquals(StatusKind.Connected, statusKind("connected"))
        assertEquals(StatusKind.Offline, statusKind("offline"))
        assertEquals(StatusKind.NotConfigured, statusKind("not_configured"))
        for (s in listOf("wrong_code", "needs_developer_mode", "cert_changed")) assertEquals(s, StatusKind.NeedsLook, statusKind(s))
        assertNull("a connected printer needs nothing", fixLine("connected"))
        assertEquals(R.string.printers_fix_offline, fixLine("offline"))
        assertEquals(R.string.printers_fix_wrong_code, fixLine("wrong_code"))
        assertEquals(R.string.printers_fix_developer_mode, fixLine("needs_developer_mode"))
        assertEquals(R.string.printers_fix_cert_changed, fixLine("cert_changed"))
        assertEquals(R.string.printers_fix_not_configured, fixLine("not_configured"))
    }

    @Test fun theJobWordFollowsTheGcodeState() {
        assertEquals(JobWord.Printing, jobWord("RUNNING"))
        assertEquals(JobWord.Paused, jobWord("PAUSE"))
        assertEquals(JobWord.Preparing, jobWord("PREPARE"))
        assertEquals(JobWord.Slicing, jobWord("SLICING"))
        assertEquals(JobWord.Finished, jobWord("FINISH"))
        assertEquals(JobWord.Failed, jobWord("FAILED"))
        assertEquals(JobWord.Idle, jobWord("IDLE"))
        assertNull(jobWord("UNKNOWN"))
        assertEquals(setOf("Printing", "Paused", "Preparing", "Slicing"), JobWord.entries.filter { it.progress }.map { it.name }.toSet())
    }

    @Test fun slotsShowUpToEightThenHowManyMore() {
        val twelve = List(12) { SlotLook("2B2B2E", empty = false) }
        val (shown, more) = shownSlots(twelve)
        assertEquals(8, shown.size)
        assertEquals(4, more)
        assertEquals(0, shownSlots(twelve.take(8)).second)
        assertEquals(0, shownSlots(emptyList()).second)
    }

    @Test fun timeLeftIsHoursAndMinutes() {
        assertEquals(1 to 12, hoursAndMinutes(72))
        assertEquals(0 to 31, hoursAndMinutes(31))
        assertEquals(2 to 0, hoursAndMinutes(120))
    }

    // --- the list ---

    @Test fun printersSplitIntoSetUpAndFoundOnTheNetwork() = runTest(dispatcher) {
        backend.list = listOf(printer("A"), printer("B", state = "not_configured", configured = false))
        val vm = PrintersViewModel(backend) { 5_000L }
        assertFalse(vm.state.value.loaded)
        vm.refresh(); runCurrent()
        val s = vm.state.value
        assertEquals(listOf("A"), s.configured.map { it.id })
        assertEquals(listOf("B"), s.found.map { it.id })
        assertTrue(s.loaded)
        assertFalse(s.loading)
        assertEquals(5_000L, s.loadedAt)
    }

    @Test fun slotSwatchesComeFromEachConnectedPrintersOwnScreenData() = runTest(dispatcher) {
        val up = printer("A")
        backend.list = listOf(up, printer("B", state = "offline"), printer("C", state = "not_configured", configured = false))
        backend.details["A"] = detail(
            up, AmsSlot(0, "A1", "PLA", "2B2B2E"), AmsSlot(1, "A2", "", "", present = false),
        )
        val vm = PrintersViewModel(backend)
        vm.refresh(); runCurrent()
        assertEquals(listOf("A"), backend.detailCalls)
        assertEquals(listOf(SlotLook("2B2B2E", false), SlotLook("", true)), vm.state.value.swatches["A"])
    }

    @Test fun aPrinterThatDoesNotAnswerHasNoSwatchesAndTheListStays() = runTest(dispatcher) {
        backend.list = listOf(printer("A"))
        val vm = PrintersViewModel(backend)
        vm.refresh(); runCurrent()
        assertEquals(1, vm.state.value.printers.size)
        assertTrue(vm.state.value.swatches.isEmpty())
        assertNull(vm.state.value.problem)
    }

    @Test fun failuresAreWordedBySortAndTheDataStays() = runTest(dispatcher) {
        backend.list = listOf(printer("A"))
        val vm = PrintersViewModel(backend)
        vm.refresh(); runCurrent()
        backend.listError = ApiError(0, "offline", "Could not reach the server: x")
        vm.refresh(); runCurrent()
        assertEquals(Problem.Unreachable, vm.state.value.problem)
        assertEquals("the printers already loaded stay", 1, vm.state.value.printers.size)
        backend.listError = ApiError(500, "boom", "The Hub's own words")
        vm.refresh(); runCurrent()
        assertEquals(Problem.HubSaid("The Hub's own words"), vm.state.value.problem)
        backend.listError = ApiError(200, "bad_response", "The server sent a reply the app could not read")
        vm.refresh(); runCurrent()
        assertEquals(Problem.Unexpected, vm.state.value.problem)
        backend.listError = null
        vm.refresh(); runCurrent()
        assertNull(vm.state.value.problem)
    }

    @Test fun anUnpairedPhoneIsAHubNoticeNotAProblemText() = runTest(dispatcher) {
        backend.listError = ApiError(401, "unauthorized", "x")
        val vm = PrintersViewModel(backend)
        vm.refresh(); runCurrent()
        assertTrue(vm.state.value.unauthorized)
        assertNull(vm.state.value.problem)
        assertFalse(vm.state.value.loading)
    }

    // --- Add a Klipper printer ---

    @Test fun theFormOpensWithAFoundAddressAndPort() {
        val vm = PrintersViewModel(backend)
        vm.openAddKlipper("192.0.2.57", 7126)
        assertEquals(KlipperDialog(host = "192.0.2.57", port = 7126), vm.state.value.klipper)
        vm.openAddKlipper()
        assertEquals(KlipperDialog(host = "", port = 7125), vm.state.value.klipper)
    }

    @Test fun theApiKeyIsSetOnTheNewPrinterBecauseTheHubsAddRouteTakesNone() = runTest(dispatcher) {
        backend.addResult = printer("K1", family = "klipper")
        val vm = PrintersViewModel(backend)
        vm.openAddKlipper()
        vm.submitAddKlipper("voron.example", "7125", "Voron", " s3cret ")
        runCurrent()
        assertEquals(listOf("K1" to "s3cret"), backend.keys)
        assertNull(vm.state.value.klipper)
        assertEquals("Workshop X1", vm.state.value.added)
        assertFalse("the key is never kept in state", vm.state.value.toString().contains("s3cret"))
    }

    @Test fun noKeyTypedMeansNoKeyRequest() = runTest(dispatcher) {
        backend.addResult = printer("K1", family = "klipper")
        val vm = PrintersViewModel(backend)
        vm.openAddKlipper()
        vm.submitAddKlipper("voron.example", "", "", "  ")
        runCurrent()
        assertTrue(backend.keys.isEmpty())
        assertEquals(Triple("voron.example", 7125, null as String?), backend.added.single())
    }

    @Test fun aRefusedKeyIsAResultOnTheListSinceThePrinterExistsNow() = runTest(dispatcher) {
        backend.addResult = printer("K1", family = "klipper")
        backend.keyError = ApiError(400, "bad_request", "That API key is not valid")
        val vm = PrintersViewModel(backend)
        vm.openAddKlipper()
        vm.submitAddKlipper("voron.example", "7125", "", "bad key")
        runCurrent()
        assertNull("the form is gone: a retry would find the printer already added", vm.state.value.klipper)
        assertEquals(Problem.HubSaid("That API key is not valid"), vm.state.value.problem)
    }

    @Test fun theKlipperFeatureBeingOffIsNamedByItsModule() = runTest(dispatcher) {
        backend.addError = ApiError(
            409, "module_off", "the klipper module is turned off on this server", buildJsonObject { put("module", "klipper") },
        )
        val vm = PrintersViewModel(backend)
        vm.openAddKlipper()
        vm.submitAddKlipper("voron.example", "7125", "")
        runCurrent()
        assertEquals(Problem.FeatureOff("klipper"), vm.state.value.klipper!!.problem)
    }

    // --- Find Klipper printers ---

    @Test fun searchSendsTheTypedNetworkOrNoneAndKeepsOnlyPrintersNotAddedYet() = runTest(dispatcher) {
        backend.scanResult = listOf(
            KlipperFound("a", "192.0.2.57", 7125, "voron"),
            KlipperFound("b", "192.0.2.58", 7125, "done", configured = true),
        )
        val vm = PrintersViewModel(backend)
        vm.openFind()
        vm.search(" 192.0.2.0/24 ")
        assertTrue(vm.state.value.find!!.searching)
        runCurrent()
        val f = vm.state.value.find!!
        assertFalse(f.searching)
        assertEquals(listOf<String?>("192.0.2.0/24"), backend.scans)
        assertEquals(listOf("192.0.2.57"), f.results!!.map { it.host })
        assertEquals("192.0.2.0/24", f.network)
        vm.search("  "); runCurrent()
        assertEquals(listOf<String?>("192.0.2.0/24", null), backend.scans)
        assertEquals("", vm.state.value.find!!.network)
    }

    @Test fun noAnswerIsAnEmptyListNotAProblem() = runTest(dispatcher) {
        val vm = PrintersViewModel(backend)
        vm.openFind()
        vm.search(""); runCurrent()
        assertEquals(emptyList<KlipperFound>(), vm.state.value.find!!.results)
        assertNull(vm.state.value.find!!.problem)
    }

    @Test fun theHubsRefusalOfASearchIsShownAsGiven() = runTest(dispatcher) {
        backend.scanError = ApiError(400, "bad_request", "scan at most a /24 (256 addresses)")
        val vm = PrintersViewModel(backend)
        vm.openFind()
        vm.search("192.0.2.0/16"); runCurrent()
        val f = vm.state.value.find!!
        assertEquals(Problem.HubSaid("scan at most a /24 (256 addresses)"), f.problem)
        assertFalse(f.searching)
        assertNull(f.results)
    }

    @Test fun addingAFoundPrinterOpensTheFormWithItsAddressAndClosesTheSheet() {
        val vm = PrintersViewModel(backend)
        vm.openFind()
        vm.openAddKlipper("192.0.2.57", 7125)
        assertNull(vm.state.value.find)
        assertEquals("192.0.2.57", vm.state.value.klipper!!.host)
    }
}
