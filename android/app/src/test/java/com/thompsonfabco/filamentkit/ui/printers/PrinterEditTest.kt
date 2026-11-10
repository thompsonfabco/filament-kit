package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterEditResult
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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PrinterEditTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    private val bambu = Printer(id = "0948AB", name = "Garage H2D", serial = "0948AB", ip = "10.0.0.9",
        configured = true, state = "connected")

    private class Fake(var reply: Printer) : PrinterEditBackend {
        val edits = mutableListOf<JsonObject>()
        var removed = 0
        var error: Exception? = null
        var note: String? = null
        override suspend fun editPrinter(id: String, changes: JsonObject): PrinterEditResult {
            edits += changes
            error?.let { throw it }
            return PrinterEditResult(reply, changes.keys.toList(), note)
        }
        override suspend fun removePrinter(id: String) {
            removed++
            error?.let { throw it }
        }
    }

    private val fake = Fake(bambu)
    private val shown = mutableListOf<Printer>()
    private fun vm(family: String = "bambu") = PrinterEditViewModel(fake, "0948AB", family) { shown += it }

    @Test fun aBambuPrinterGetsTheAccessCodeAndUnpin() {
        val v = vm()
        assertEquals(listOf(EditField.NAME, EditField.ADDRESS, EditField.ACCESS_CODE), v.fields)
        assertTrue(v.canUnpin)
    }

    @Test fun aKlipperPrinterGetsTheApiKeyAndNoUnpin() {
        val v = vm("klipper")
        assertEquals(listOf(EditField.NAME, EditField.ADDRESS, EditField.API_KEY), v.fields)
        assertFalse(v.canUnpin)
    }

    @Test fun renameSendsOnlyTheNameAndShowsThePrinter() = runTest(dispatcher) {
        val v = vm()
        v.open(EditField.NAME)
        v.submit("  Garage  ")
        runCurrent()
        assertEquals(listOf(buildJsonObject { put("name", "Garage") }), fake.edits)
        assertNull(v.state.value.dialog)
        assertEquals("Saved.", v.state.value.message)
        assertEquals(listOf(bambu), shown)
    }

    @Test fun anEmptyValueIsRefusedBeforeAnyRequest() = runTest(dispatcher) {
        val v = vm()
        for ((f, text) in listOf(EditField.NAME to PrinterEditTexts.NEED_NAME, EditField.ADDRESS to PrinterEditTexts.NEED_ADDRESS,
            EditField.ACCESS_CODE to PrinterEditTexts.NEED_CODE)) {
            v.open(f)
            v.submit("   ")
            runCurrent()
            assertEquals(text, v.state.value.dialog?.error)
        }
        assertTrue(fake.edits.isEmpty())
    }

    @Test fun anEmptyApiKeyClearsIt() = runTest(dispatcher) {
        val v = vm("klipper")
        v.open(EditField.API_KEY)
        v.submit("")
        runCurrent()
        assertEquals(listOf(buildJsonObject { put("api_key", "") }), fake.edits)
    }

    @Test fun aKlipperAddressCarriesThePortWhenGiven() = runTest(dispatcher) {
        val v = vm("klipper")
        v.open(EditField.ADDRESS)
        v.submit("voron.lan", "7125")
        runCurrent()
        assertEquals(buildJsonObject { put("address", "voron.lan"); put("port", 7125) }, fake.edits.single())
        v.open(EditField.ADDRESS)
        v.submit("voron.lan", "")
        runCurrent()
        assertEquals(buildJsonObject { put("address", "voron.lan") }, fake.edits[1])
    }

    @Test fun aBadPortIsRefused() = runTest(dispatcher) {
        val v = vm("klipper")
        v.open(EditField.ADDRESS)
        v.submit("voron.lan", "70000")
        runCurrent()
        assertEquals(PrinterEditTexts.BAD_PORT, v.state.value.dialog?.error)
        assertTrue(fake.edits.isEmpty())
    }

    @Test fun aBambuAddressNeverSendsAPort() = runTest(dispatcher) {
        val v = vm()
        v.open(EditField.ADDRESS)
        v.submit("10.0.0.10", "7125")
        runCurrent()
        assertEquals(buildJsonObject { put("address", "10.0.0.10") }, fake.edits.single())
    }

    @Test fun aNewCodeThatFailsSaysWhatToDo() = runTest(dispatcher) {
        fake.reply = bambu.copy(state = "wrong_code")
        val v = vm()
        v.open(EditField.ACCESS_CODE)
        v.submit("12345678")
        runCurrent()
        assertEquals(buildJsonObject { put("access_code", "12345678") }, fake.edits.single())
        assertEquals("Saved. " + PrinterHelp.fix("wrong_code"), v.state.value.message)
    }

    @Test fun theServersNoteIsShown() = runTest(dispatcher) {
        fake.note = "this server does not reach it"
        val v = vm()
        v.open(EditField.ADDRESS)
        v.submit("10.0.0.10")
        runCurrent()
        assertEquals("Saved. this server does not reach it.", v.state.value.message)
    }

    @Test fun aRefusalStaysInTheDialogInTheServersWords() = runTest(dispatcher) {
        fake.error = ApiError(400, "bad_request", "give the printer a name")
        val v = vm()
        v.open(EditField.NAME)
        v.submit("x")
        runCurrent()
        val d = v.state.value.dialog!!
        assertEquals("give the printer a name", d.error)
        assertFalse(d.busy)
        assertTrue(shown.isEmpty())
    }

    @Test fun unpinAsksFirstThenSendsUnpin() = runTest(dispatcher) {
        val v = vm()
        v.askUnpin()
        assertTrue(v.state.value.confirmUnpin)
        v.confirmUnpin()
        runCurrent()
        assertEquals(buildJsonObject { put("unpin", JsonPrimitive(true)) }, fake.edits.single())
        assertFalse(v.state.value.busy)
    }

    @Test fun removeAsksFirstThenGoesBack() = runTest(dispatcher) {
        val v = vm()
        v.askRemove()
        v.cancelRemove()
        assertEquals(0, fake.removed)
        v.askRemove()
        v.confirmRemove()
        runCurrent()
        assertEquals(1, fake.removed)
        assertTrue(v.state.value.removed)
    }

    @Test fun aFailedRemoveStaysAndSaysWhy() = runTest(dispatcher) {
        fake.error = ApiError(409, "module_off", "the printers module is off")
        val v = vm()
        v.askRemove()
        v.confirmRemove()
        runCurrent()
        assertFalse(v.state.value.removed)
        assertEquals("the printers module is off", v.state.value.message)
        assertTrue(v.state.value.messageIsError)
    }

    @Test fun anUnpairedPhoneClosesTheDialog() = runTest(dispatcher) {
        fake.error = ApiError(401, "unauthorized", "x")
        val v = vm()
        v.open(EditField.NAME)
        v.submit("Garage")
        runCurrent()
        assertTrue(v.state.value.unauthorized)
        assertNull(v.state.value.dialog)
    }

    @Test fun theRemoveQuestionNamesWhatIsForgotten() {
        assertTrue(PrinterEditTexts.removeQuestion(bambu).contains("Access Code"))
        assertTrue(PrinterEditTexts.removeQuestion(bambu.copy(family = "klipper")).contains("API key"))
    }
}
