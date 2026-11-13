package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterEditResult
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Printer settings (05-android-app 9.9): the rows, the dialogs' checks and requests, and Forget printer. */
@OptIn(ExperimentalCoroutinesApi::class)
class PrinterEditTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    private val bambu = Printer(id = "0948AB", name = "Garage H2D", serial = "0948AB", ip = "192.0.2.9",
        configured = true, state = "connected", pinned = true)
    private val klipper = bambu.copy(family = "klipper", pinned = false)

    private class Fake(var reply: Printer) : PrinterEditBackend {
        val edits = mutableListOf<JsonObject>()
        var removed = 0
        var error: Exception? = null
        var note: String? = null
        var gate: CompletableDeferred<Unit>? = null
        override suspend fun editPrinter(id: String, changes: JsonObject): PrinterEditResult {
            edits += changes
            gate?.await()
            error?.let { throw it }
            return PrinterEditResult(reply, changes.keys.toList(), note)
        }
        override suspend fun removePrinter(id: String) {
            removed++
            gate?.await()
            error?.let { throw it }
        }
    }

    private val fake = Fake(bambu)
    private val shown = mutableListOf<Printer>()
    private fun vm(family: String = "bambu") = PrinterEditViewModel(fake, "0948AB", family) { shown += it }

    @Test fun aPinnedBambuPrinterGetsTheAccessCodeAndTheCertificate() {
        assertEquals(listOf(EditField.NAME, EditField.ADDRESS, EditField.ACCESS_CODE, EditField.TRUST_CERT), vm().fields(bambu))
    }

    @Test fun anUnpinnedBambuPrinterHasNoCertificateRow() {
        assertEquals(listOf(EditField.NAME, EditField.ADDRESS, EditField.ACCESS_CODE), vm().fields(bambu.copy(pinned = false)))
    }

    @Test fun aKlipperPrinterGetsTheApiKey() {
        assertEquals(listOf(EditField.NAME, EditField.ADDRESS, EditField.API_KEY), vm("klipper").fields(klipper))
    }

    @Test fun renameSendsOnlyTheNameAndSaysRenamed() = runTest(dispatcher) {
        fake.reply = bambu.copy(name = "Garage")
        val v = vm()
        v.open(EditField.NAME)
        v.submit("  Garage  ")
        runCurrent()
        assertEquals(listOf(buildJsonObject { put("name", "Garage") }), fake.edits)
        assertNull(v.state.value.dialog)
        assertEquals(Note(Say.Words(R.string.printer_set_renamed, listOf("Garage"))), v.state.value.note)
        assertEquals(listOf(fake.reply), shown)
    }

    @Test fun anEmptyValueIsRefusedUnderItsFieldBeforeAnyRequest() = runTest(dispatcher) {
        val v = vm()
        for ((f, error) in listOf(EditField.NAME to FieldError.Name, EditField.ADDRESS to FieldError.Address,
            EditField.ACCESS_CODE to FieldError.AccessCode, EditField.TRUST_CERT to FieldError.AccessCode)) {
            v.open(f)
            v.submit("   ")
            runCurrent()
            assertEquals(error, v.state.value.dialog?.error)
        }
        assertTrue(fake.edits.isEmpty())
    }

    @Test fun anEmptyApiKeyClearsIt() = runTest(dispatcher) {
        val v = vm("klipper")
        v.open(EditField.API_KEY)
        v.submit("")
        runCurrent()
        assertEquals(listOf(buildJsonObject { put("api_key", "") }), fake.edits)
        assertEquals(Note(Say.Words(R.string.printer_set_saved)), v.state.value.note)
    }

    @Test fun aKlipperAddressCarriesThePortWhenGiven() = runTest(dispatcher) {
        fake.reply = klipper
        val v = vm("klipper")
        v.open(EditField.ADDRESS)
        v.submit("voron.example", "7125")
        runCurrent()
        assertEquals(buildJsonObject { put("address", "voron.example"); put("port", 7125) }, fake.edits.single())
        v.open(EditField.ADDRESS)
        v.submit("voron.example", "")
        runCurrent()
        assertEquals(buildJsonObject { put("address", "voron.example") }, fake.edits[1])
        assertEquals(Note(Say.Words(R.string.printer_set_address_done)), v.state.value.note)
    }

    @Test fun aKlipperMoveCarriesTheKeyOnlyWhenTyped() = runTest(dispatcher) {
        val v = vm("klipper")
        v.open(EditField.ADDRESS)
        assertFalse(v.state.value.dialog!!.codeToo)
        v.submit("voron.example", "", " k3y ")
        runCurrent()
        assertEquals(buildJsonObject { put("address", "voron.example"); put("api_key", "k3y") }, fake.edits.single())
    }

    @Test fun aBadPortIsRefusedUnderThePortField() = runTest(dispatcher) {
        val v = vm("klipper")
        v.open(EditField.ADDRESS)
        v.submit("voron.example", "70000")
        runCurrent()
        assertEquals(FieldError.Port, v.state.value.dialog?.error)
        assertTrue(fake.edits.isEmpty())
    }

    @Test fun aBambuAddressAlwaysAsksForTheAccessCodeAgain() = runTest(dispatcher) {
        val v = vm()
        v.open(EditField.ADDRESS)
        assertTrue(v.state.value.dialog!!.codeToo)
        v.submit("192.0.2.10", "", " ")
        runCurrent()
        assertEquals(FieldError.AccessCode, v.state.value.dialog?.error)
        assertTrue(fake.edits.isEmpty())
        v.submit("192.0.2.10", "7125", "12345678")
        runCurrent()
        // no port for a Bambu printer; the code goes in the same request
        assertEquals(buildJsonObject { put("address", "192.0.2.10"); put("access_code", "12345678") }, fake.edits.single())
    }

    @Test fun aNewCodeThatFailsSaysWhatToDo() = runTest(dispatcher) {
        fake.reply = bambu.copy(state = "wrong_code")
        val v = vm()
        v.open(EditField.ACCESS_CODE)
        v.submit("12345678")
        runCurrent()
        assertEquals(buildJsonObject { put("access_code", "12345678") }, fake.edits.single())
        assertEquals(Note(Say.Words(R.string.printers_fix_wrong_code), ok = false), v.state.value.note)
    }

    @Test fun aNewCodeThatWorksSaysSo() = runTest(dispatcher) {
        val v = vm()
        v.open(EditField.ACCESS_CODE)
        v.submit("12345678")
        runCurrent()
        assertEquals(Note(Say.Words(R.string.printer_set_code_done, listOf("Garage H2D"))), v.state.value.note)
    }

    @Test fun theHubsNoteIsKeptForTheScreen() = runTest(dispatcher) {
        fake.note = "this Hub does not reach it"
        val v = vm()
        v.open(EditField.ADDRESS)
        v.submit("192.0.2.10", "", "12345678")
        runCurrent()
        assertEquals("this Hub does not reach it", v.state.value.hubNote)
    }

    @Test fun aRefusalStaysInTheDialogInTheHubsWords() = runTest(dispatcher) {
        fake.error = ApiError(400, "bad_request", "give the printer a name")
        val v = vm()
        v.open(EditField.NAME)
        v.submit("x")
        runCurrent()
        val d = v.state.value.dialog!!
        assertEquals(Problem.HubSaid("give the printer a name"), d.problem)
        assertFalse(d.busy)
        assertTrue(shown.isEmpty())
    }

    @Test fun noAnswerAtAllIsCannotReachTheHub() = runTest(dispatcher) {
        fake.error = ApiError(0, "offline", "x")
        val v = vm()
        v.open(EditField.NAME)
        v.submit("x")
        runCurrent()
        assertEquals(Problem.Unreachable, v.state.value.dialog?.problem)
    }

    @Test fun aNewCertificateIsTrustedOnlyWithTheAccessCode() = runTest(dispatcher) {
        val v = vm()
        v.open(EditField.TRUST_CERT)
        v.submit(" 12345678 ")
        runCurrent()
        assertEquals(buildJsonObject { put("unpin", JsonPrimitive(true)); put("access_code", "12345678") }, fake.edits.single())
        assertNull(v.state.value.dialog)
    }

    @Test fun forgetAsksFirstThenGoesBack() = runTest(dispatcher) {
        val v = vm()
        v.askForget()
        v.cancelForget()
        assertEquals(0, fake.removed)
        v.askForget()
        v.confirmForget()
        runCurrent()
        assertEquals(1, fake.removed)
        assertTrue(v.state.value.forgotten)
    }

    @Test fun aFailedForgetStaysAndSaysWhy() = runTest(dispatcher) {
        fake.error = ApiError(409, "module_off", "the printers module is off")
        val v = vm()
        v.askForget()
        v.confirmForget()
        runCurrent()
        assertFalse(v.state.value.forgotten)
        assertEquals(Note(Say.FromHub("the printers module is off"), ok = false), v.state.value.note)
    }

    @Test fun aDialogWhoseRequestIsOutCannotBeLeft() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        fake.gate = gate
        val v = vm()
        v.open(EditField.NAME)
        v.submit("Garage")
        runCurrent()
        assertTrue(v.state.value.dialog!!.busy)
        v.close()
        assertNotNull("Cancel, Back and the scrim do nothing while it is saving", v.state.value.dialog)
        gate.complete(Unit)
        runCurrent()
        assertNull(v.state.value.dialog)
    }

    @Test fun theForgetQuestionCannotBeLeftWhileTheRequestIsOut() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        fake.gate = gate
        val v = vm()
        v.askForget()
        v.confirmForget()
        runCurrent()
        v.cancelForget()
        assertTrue(v.state.value.confirmForget)
        gate.complete(Unit)
        runCurrent()
        assertFalse(v.state.value.confirmForget)
    }

    @Test fun aHubNoticeStaysInTheDialogWithWhatWasTypedAndClearsAfterASuccess() = runTest(dispatcher) {
        fake.error = ApiError(401, "unauthorized", "x")
        val v = vm()
        v.open(EditField.NAME)
        v.submit("Garage")
        runCurrent()
        assertTrue(v.state.value.unauthorized)
        assertEquals(Problem.NoLongerPaired, v.state.value.dialog?.problem)
        fake.error = FingerprintMismatch("aaa", "bbb")
        v.submit("Garage")
        runCurrent()
        assertEquals("aaa" to "bbb", v.state.value.mismatch)
        assertEquals(Problem.CertificateChanged, v.state.value.dialog?.problem)
        fake.error = null
        var told = 0
        v.onHubOk = { told++ }
        v.submit("Garage")
        runCurrent()
        assertFalse(v.state.value.unauthorized)
        assertNull(v.state.value.mismatch)
        assertEquals(1, told)
    }
}
