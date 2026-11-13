package com.thompsonfabco.filamentkit.ui.add

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.net.AddResult
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FilamentChoice
import com.thompsonfabco.filamentkit.net.ServerInfo
import com.thompsonfabco.filamentkit.net.VendorChoice
import com.thompsonfabco.filamentkit.ui.home.showLabelPhotos
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Adding spools by hand: the filament picker, new filaments, Preview → Add, field errors, module gating. */
@OptIn(ExperimentalCoroutinesApi::class)
class ManualAddTest {
    private val dispatcher = StandardTestDispatcher()
    private lateinit var dir: File
    private lateinit var store: DraftStore
    private val taps = MutableSharedFlow<String>(extraBufferCapacity = 8)
    private val api = FakeIntakeApi()

    private val elegooRed = FilamentChoice(3, "Elegoo", "PLA Red", "PLA", 1.24, 1000.0, 160.0, "cc0000", 210.0, 60.0, 2)
    private val sunluGrey = FilamentChoice(4, "SUNLU", "PETG Grey", "PETG", 1.27, 1000.0, 213.0, null, null, null, 0)

    @Before fun setUp() {
        Dispatchers.setMain(dispatcher)
        dir = kotlin.io.path.createTempDirectory("drafts").toFile()
        store = DraftStore(dir)
        api.filamentList = { q -> listOf(elegooRed, sunluGrey).filter { f -> q.isBlank() || q.lowercase() in "${f.vendor} ${f.name}".lowercase() } }
        api.vendorList = listOf(VendorChoice(1, "Elegoo", 160.0), VendorChoice(2, "SUNLU", 213.0))
    }

    @After fun tearDown() {
        Dispatchers.resetMain()
        dir.deleteRecursively()
    }

    private fun vm(tag: String? = null) = AddViewModel(
        api = api, store = store, taps = taps, initialTag = tag, prepare = { it }, io = dispatcher, manual = true,
    )

    private fun sent(call: Int = 0, index: Int = 0) = api.adds[call].items[index].jsonObject
    private fun JsonObject.s(key: String) = this[key]?.jsonPrimitive?.content

    @Test fun startsAtReviewWithAllFilamentsAndTheVendors() = runTest(dispatcher) {
        val vm = vm()
        assertEquals(Stage.Review, vm.state.value.stage)
        advanceUntilIdle()
        val s = vm.state.value
        assertTrue(s.manual)
        assertEquals(listOf(""), api.filamentCalls)
        assertEquals(listOf(elegooRed, sunluGrey), s.filaments)
        assertFalse(s.filamentsLoading)
        assertEquals(2, s.vendors.size)
        assertTrue(s.items.isEmpty())
    }

    @Test fun theSearchWaitsForAPauseAndSendsTheLastText() = runTest(dispatcher) {
        val vm = vm()
        advanceUntilIdle()
        vm.setFilamentQuery("su")
        vm.setFilamentQuery("sunlu")
        advanceTimeBy(AddViewModel.FILAMENT_DEBOUNCE_MS - 1)
        runCurrent()
        assertEquals(listOf(""), api.filamentCalls)
        advanceUntilIdle()
        assertEquals(listOf("", "sunlu"), api.filamentCalls)
        assertEquals(listOf(sunluGrey), vm.state.value.filaments)
    }

    @Test fun aFailedSearchSaysWhy() = runTest(dispatcher) {
        api.filamentFailure = ApiError(503, "spoolman_unreachable", "down")
        val vm = vm()
        advanceUntilIdle()
        assertEquals(R.string.common_spoolman_unreachable, vm.state.value.filamentsError!!.res)
        assertTrue(vm.state.value.filaments.isEmpty())
    }

    @Test fun pickedFilamentPreviewsThenAddsAndShowsTheIds() = runTest(dispatcher) {
        val vm = vm()
        advanceUntilIdle()
        vm.pickFilament(elegooRed)
        vm.setCount(0, 2)
        vm.preview()
        advanceUntilIdle()
        assertEquals(Stage.Preview, vm.state.value.stage)
        val dry = api.adds.single()
        assertTrue(dry.dryRun)
        val item = sent()
        assertEquals("Elegoo", item.s("vendor"))
        assertEquals("PLA Red", item.s("name"))
        assertEquals("PLA", item.s("material"))
        assertEquals("1.24", item.s("density"))
        assertEquals("1000", item.s("net"))
        assertEquals("160", item.s("tare"))
        assertEquals("CC0000", item.s("color_hex"))
        assertEquals("2", item.s("count"))
        assertEquals("true", item.s("sealed"))
        assertTrue("app keys are never sent", item.keys.none { it.startsWith("app_") })

        api.addResults += AddResult(listOf(41, 42), listOf("F3 Elegoo PLA Red (existing filament): 2 spool(s) [41, 42]"), false)
        vm.confirm()
        advanceUntilIdle()
        val s = vm.state.value
        assertEquals(Stage.Done, s.stage)
        assertEquals(listOf(41, 42), s.spoolIds)
        assertFalse(api.adds[1].dryRun)
        assertTrue("a manual add keeps no draft", store.list().isEmpty())

        vm.startOver()
        advanceUntilIdle()
        assertEquals(Stage.Review, vm.state.value.stage)
        assertTrue(vm.state.value.manual)
        assertTrue(vm.state.value.items.isEmpty())
        assertEquals(2, vm.state.value.vendors.size)
    }

    @Test fun aNewFilamentNeedsItsFieldsAndGetsVendorTareAndDensityDefaults() = runTest(dispatcher) {
        val vm = vm()
        advanceUntilIdle()
        vm.newFilament()
        assertFalse(vm.state.value.complete)
        assertEquals(listOf("vendor", "name", "material", "net", "tare", "density"), vm.state.value.missing.single())
        vm.preview()
        advanceUntilIdle()
        assertTrue("incomplete: nothing sent", api.adds.isEmpty())

        vm.pickVendor(0, VendorChoice(2, "SUNLU", 213.0))
        vm.setText(0, "name", "PLA+ Grey")
        vm.setText(0, "material", "PLA+")
        vm.setNumber(0, "net", 1000.0)
        assertTrue(vm.state.value.complete)
        vm.setItemSealed(0, false)
        vm.setNumber(0, "gross", 1100.0)
        vm.preview()
        advanceUntilIdle()
        val item = sent()
        assertEquals("SUNLU", item.s("vendor"))
        assertEquals("213", item.s("tare"))
        assertEquals("1.24", item.s("density"))
        assertEquals("false", item.s("sealed"))
        assertEquals("1100", item.s("gross"))
        assertEquals("1.24", vm.state.value.items[0].s("density"))
    }

    @Test fun aPickedVendorKeepsATypedTare() = runTest(dispatcher) {
        val vm = vm()
        advanceUntilIdle()
        vm.newFilament()
        vm.setNumber(0, "tare", 250.0)
        vm.pickVendor(0, VendorChoice(2, "SUNLU", 213.0))
        assertEquals("250", vm.state.value.items[0].s("tare"))
    }

    @Test fun anUnknownMaterialNeedsATypedDensity() = runTest(dispatcher) {
        val vm = vm()
        advanceUntilIdle()
        vm.newFilament()
        listOf("vendor" to "Acme", "name" to "Nylon Black", "material" to "PA12").forEach { (k, v) -> vm.setText(0, k, v) }
        vm.setNumber(0, "net", 1000.0)
        vm.setNumber(0, "tare", 200.0)
        assertEquals(listOf("density"), vm.state.value.missing.single())
        vm.setNumber(0, "density", 1.01)
        assertTrue(vm.state.value.complete)
    }

    @Test fun aServerFieldErrorIsShownAtThatFieldUntilAnEdit() = runTest(dispatcher) {
        val vm = vm()
        advanceUntilIdle()
        vm.pickFilament(sunluGrey)
        api.addFailures += ApiError(400, "bad_request", "SUNLU PETG Grey: tare must be a positive number")
        vm.preview()
        advanceUntilIdle()
        val s = vm.state.value
        // the Hub's check stays on the Preview step: a line with "Fix" and the complaint at the field
        assertEquals(Stage.Preview, s.stage)
        assertTrue(s.previewFailed)
        assertEquals(mapOf(0 to mapOf("tare" to "Tare must be a positive number")), s.fieldErrors)
        assertEquals(listOf(PreviewProblem("SUNLU PETG Grey: tare must be a positive number", 0, "tare")), s.problems)
        assertNull(s.error)
        vm.setNumber(0, "tare", 213.0)
        assertTrue(vm.state.value.fieldErrors.isEmpty())
        assertNull(vm.state.value.error)
    }

    @Test fun fieldErrorsAreReadFromTheServersMessages() {
        val a = JsonObject(mapOf("vendor" to JsonPrimitive("Elegoo"), "name" to JsonPrimitive("PLA Red")))
        val b = JsonObject(mapOf("vendor" to JsonPrimitive("SUNLU"), "name" to JsonPrimitive("PETG Grey")))
        assertEquals(FieldError(1, "net", "Missing net"), fieldError("SUNLU PETG Grey: missing net", listOf(a, b)))
        assertEquals(
            FieldError(0, "gross", "Gross 100 g needs count 1 and a weight above the spool"),
            fieldError("Elegoo PLA Red: gross 100 g needs count 1 and a weight above the spool", listOf(a, b)),
        )
        assertEquals("one item: always that one", 0, fieldError("x y: count must be a whole number", listOf(a))!!.index)
        assertNull("unknown item among several", fieldError("x y: count must be a whole number", listOf(a, b)))
        assertNull("no field named", fieldError("no items to add", listOf(a)))
        assertNull("not an item field", fieldError("Elegoo PLA Red: something else", listOf(a)))
    }

    @Test fun aTagIsSentWithTheAdd() = runTest(dispatcher) {
        val vm = vm(tag = "4:77:90:e")
        advanceUntilIdle()
        vm.pickFilament(elegooRed)
        vm.setItemSealed(0, false)
        vm.preview()
        advanceUntilIdle()
        assertEquals("4:77:90:e", api.adds.single().tag)
    }

    @Test fun thereAreNoPhotosToGoBackTo() = runTest(dispatcher) {
        val vm = vm()
        advanceUntilIdle()
        vm.backToPhotos()
        assertEquals(Stage.Review, vm.state.value.stage)
    }

    @Test fun densityDefaultsByMaterialFamily() {
        assertEquals(1.24, defaultDensity("PLA+")!!, 0.0)
        assertEquals(1.27, defaultDensity("petg-cf")!!, 0.0)
        assertEquals(1.21, defaultDensity("TPU 95A")!!, 0.0)
        assertNull(defaultDensity("PA12"))
        assertNull(defaultDensity(null))
    }

    @Test fun labelPhotosAreOfferedOnlyWithAiIntake() {
        assertFalse("unknown (offline)", showLabelPhotos(null))
        assertFalse(showLabelPhotos(ServerInfo("W", "0.2.0", 1, modules = listOf("backup", "spoolman"))))
        assertTrue(showLabelPhotos(ServerInfo("W", "0.2.0", 1, modules = listOf("ai_intake", "spoolman"))))
        assertTrue("an older server always reads labels", showLabelPhotos(ServerInfo("W", "0.1.0", 1)))
    }

    @Test fun aReadWithTheModuleOffSaysToAddByHand() {
        val e = describe(ApiError(409, "module_off", "the ai_intake module is turned off on this server"))
        assertEquals(R.string.home_label_reader_off, e.message.res)
        assertTrue(e.canAddByHand)
    }
}
