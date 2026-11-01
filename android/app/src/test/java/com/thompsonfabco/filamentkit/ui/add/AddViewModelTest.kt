package com.thompsonfabco.filamentkit.ui.add

import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.net.AddResult
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.ReadResult
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class AddViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private lateinit var dir: File
    private lateinit var store: DraftStore
    private val taps = MutableSharedFlow<String>(extraBufferCapacity = 8)
    private val api = FakeIntakeApi()

    @Before fun setUp() {
        Dispatchers.setMain(dispatcher)
        dir = kotlin.io.path.createTempDirectory("drafts").toFile()
        store = DraftStore(dir)
    }

    @After fun tearDown() {
        Dispatchers.resetMain()
        dir.deleteRecursively()
    }

    private fun vm(draftId: String? = null, initialTag: String? = null) = AddViewModel(
        api = api, store = store, taps = taps, draftId = draftId, initialTag = initialTag,
        prepare = { it }, io = dispatcher,
    )

    private fun item(sealed: Boolean = false, count: Int = 1, vendor: String = "SUNLU") = buildJsonObject {
        put("photos", JsonArray(emptyList()))
        put("existing_filament_id", JsonNull)
        put("vendor", vendor)
        put("name", "PLA+ Grey")
        put("material", "PLA")
        put("color_hex", "808080")
        put("net", 1000)
        put("tare", 213)
        put("density", 1.24)
        put("count", count)
        put("estimates", JsonArray(listOf(Json.parseToJsonElement("\"tare\""))))
        put("sealed", sealed)
        put("sealed_reason", if (sealed) "in vacuum bag" else "bare spool")
        put("match", "new filament")
        put("future_field", "keep me")
    }

    private fun result(vararg items: JsonObject, questions: List<String> = emptyList(), tag: String? = null) =
        ReadResult(JsonArray(items.toList()), questions, tag, null, "r1")

    /** Adds one photo and reads, ending in Review. */
    private fun TestScope.readOne(vm: AddViewModel, vararg items: JsonObject) {
        api.readResults += result(*items)
        vm.addPhoto(byteArrayOf(1, 2, 3))
        advanceUntilIdle()
        vm.read()
        advanceUntilIdle()
    }

    private fun sentItem(call: Int = 0, index: Int = 0) = api.adds[call].items[index].jsonObject

    @Test fun readGoesToReviewAndIsSavedInTheDraft() = runTest(dispatcher) {
        val vm = vm()
        api.readResults += result(item(), questions = listOf("Is it PLA+ or PLA?"))
        vm.addPhoto(byteArrayOf(1, 2, 3))
        vm.addPhoto(byteArrayOf(4, 5))
        advanceUntilIdle()
        vm.setHint("grey one")
        vm.read()
        advanceUntilIdle()

        val s = vm.state.value
        assertEquals(Stage.Review, s.stage)
        assertEquals(listOf("Is it PLA+ or PLA?"), s.questions)
        assertEquals("SUNLU", s.items.single()["vendor"]!!.jsonPrimitive.content)
        assertNull(s.error)
        val call = api.reads.single()
        assertEquals(listOf(listOf<Byte>(1, 2, 3), listOf<Byte>(4, 5)), call.photos.map { it.toList() })
        assertEquals("grey one", call.hint)
        val draft = store.get(s.draftId!!)!!
        assertEquals(2, draft.photos.size)
        assertNotNull(draft.readResult)
        assertEquals(1, draft.editedItems!!.size)
    }

    @Test fun draftIsCreatedAtTheFirstPhotoOnly() = runTest(dispatcher) {
        val vm = vm()
        vm.setHint("x")
        advanceUntilIdle()
        assertTrue(store.list().isEmpty())
        vm.addPhoto(byteArrayOf(1))
        advanceUntilIdle()
        assertEquals(1, store.list().size)
        assertEquals("x", store.list().single().hint)
    }

    @Test fun photosAreLimitedToEightAndCanBeRemoved() = runTest(dispatcher) {
        val vm = vm()
        repeat(9) { vm.addPhoto(byteArrayOf(it.toByte())) ; advanceUntilIdle() }
        assertEquals(8, vm.state.value.photos.size)
        assertNotNull(vm.state.value.error)
        vm.dismissError()
        vm.removePhoto(0)
        advanceUntilIdle()
        assertEquals(7, vm.state.value.photos.size)
        assertEquals(7, store.get(vm.state.value.draftId!!)!!.photos.size)
    }

    @Test fun editedFieldsGoIntoAddWithUnknownFieldsKept() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        vm.setText(0, "vendor", "Sunlu Inc")
        vm.setCount(0, 2)
        vm.setNumber(0, "net", 750.0)
        vm.setText(0, "color_hex", "#ff0000")
        vm.setLocation(0, "Shelf A")
        vm.preview()
        advanceUntilIdle()

        val sent = sentItem()
        assertEquals("Sunlu Inc", sent["vendor"]!!.jsonPrimitive.content)
        assertEquals(2, sent["count"]!!.jsonPrimitive.int)
        assertEquals(750.0, sent["net"]!!.jsonPrimitive.double, 0.0)
        assertEquals("FF0000", sent["color_hex"]!!.jsonPrimitive.content)
        assertEquals("Shelf A", sent["location"]!!.jsonPrimitive.content)
        assertEquals("keep me", sent["future_field"]!!.jsonPrimitive.content)
        assertEquals("new filament", sent["match"]!!.jsonPrimitive.content)
        // the edits survive in the draft too
        val saved = store.get(vm.state.value.draftId!!)!!.editedItems!![0].jsonObject
        assertEquals("Sunlu Inc", saved["vendor"]!!.jsonPrimitive.content)
    }

    @Test fun blankLocationIsLeftToTheServer() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        vm.setLocation(0, "Shelf A")
        vm.setLocation(0, "  ")
        vm.preview()
        advanceUntilIdle()
        assertFalse("location" in sentItem())
    }

    @Test fun previewIsAlwaysDryAndConfirmIsReal() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        api.addResults += AddResult(emptyList(), listOf("SUNLU PLA+ Grey (new filament): 1 spool(s) @ Rack"), true)
        vm.preview()
        advanceUntilIdle()
        assertEquals(Stage.Preview, vm.state.value.stage)
        assertEquals(listOf("SUNLU PLA+ Grey (new filament): 1 spool(s) @ Rack"), vm.state.value.previewLines)

        api.addResults += AddResult(listOf(41), listOf("added"), false)
        val id = vm.state.value.draftId!!
        vm.confirm()
        advanceUntilIdle()

        assertEquals(listOf(true, false), api.adds.map { it.dryRun })
        assertEquals(api.adds[0].items, api.adds[1].items)
        val s = vm.state.value
        assertEquals(Stage.Done, s.stage)
        assertEquals(listOf(41), s.spoolIds)
        assertNull(store.get(id))
    }

    @Test fun confirmNeedsAFreshPreview() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        vm.confirm()
        advanceUntilIdle()
        assertTrue(api.adds.isEmpty())

        vm.preview()
        advanceUntilIdle()
        vm.setText(0, "name", "PLA+ Silver")
        assertEquals(Stage.Review, vm.state.value.stage)
        vm.confirm()
        advanceUntilIdle()
        assertEquals(listOf(true), api.adds.map { it.dryRun })
    }

    @Test fun offlineDuringAddKeepsTheDraftAndRetries() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        vm.setText(0, "name", "PLA+ Silver")
        vm.preview()
        advanceUntilIdle()
        api.addFailures += ApiError(0, "offline", "Could not reach the server")
        vm.confirm()
        advanceUntilIdle()

        val s = vm.state.value
        assertEquals("Can't reach the server. Check that this phone is on the same network as the server, then try again.", s.error!!.message)
        assertTrue(s.error.canRetry)
        val draft = store.get(s.draftId!!)!!
        assertEquals("PLA+ Silver", draft.editedItems!![0].jsonObject["name"]!!.jsonPrimitive.content)

        api.addResults += AddResult(listOf(7), listOf("added"), false)
        vm.retry()
        advanceUntilIdle()
        assertEquals(listOf(true, false, false), api.adds.map { it.dryRun })
        assertEquals(Stage.Done, vm.state.value.stage)
        assertNull(store.get(s.draftId))
    }

    @Test fun weightOnASingleOpenedSpoolBecomesGross() = runTest(dispatcher) {
        val vm = vm()
        vm.setWeight(812.5)
        readOne(vm, item(sealed = false))
        vm.preview()
        advanceUntilIdle()
        assertEquals(812.5, sentItem()["gross"]!!.jsonPrimitive.double, 0.0)
        assertEquals(812.5, store.get(vm.state.value.draftId!!)!!.weightGrams!!, 0.0)
    }

    @Test fun weightIsNotUsedForSeveralSpools() = runTest(dispatcher) {
        val vm = vm()
        vm.setWeight(812.5)
        readOne(vm, item(count = 2))
        vm.preview()
        advanceUntilIdle()
        assertFalse("gross" in sentItem())
        assertTrue(vm.state.value.notices.any { "only used for one opened spool" in it })
    }

    @Test fun sealedToggleMarksEveryItemSealed() = runTest(dispatcher) {
        val vm = vm()
        vm.setSealed(true)
        readOne(vm, item(sealed = false), item(sealed = false, vendor = "Bambu"))
        vm.preview()
        advanceUntilIdle()
        assertTrue(api.adds[0].items.all { it.jsonObject["sealed"]!!.jsonPrimitive.content == "true" })
        assertFalse(api.adds[0].items.any { "gross" in it.jsonObject })
    }

    @Test fun dailyCapHasAPlainMessageAndKeepsTheDraft() = runTest(dispatcher) {
        val vm = vm()
        api.readFailures += ApiError(429, "daily_cap", "daily limit of 30 label reads reached (reads_per_day)")
        vm.addPhoto(byteArrayOf(1))
        advanceUntilIdle()
        vm.read()
        advanceUntilIdle()
        val s = vm.state.value
        assertEquals(Stage.Capture, s.stage)
        assertEquals("Today's limit of label reads on the server is used up. Try again tomorrow.", s.error!!.message)
        assertFalse(s.error.canRetry)
        assertNotNull(store.get(s.draftId!!))
    }

    @Test fun claudeErrorRetriesWithTheReadId() = runTest(dispatcher) {
        val vm = vm()
        api.readFailures += ApiError(502, "rate_limited", "Anthropic rate limit",
            buildJsonObject { put("read_id", "abc123") })
        vm.addPhoto(byteArrayOf(1))
        advanceUntilIdle()
        vm.read()
        advanceUntilIdle()
        assertEquals("Claude is busy right now (rate limit). Wait a minute, then retry.", vm.state.value.error!!.message)
        assertTrue(vm.state.value.error!!.canRetry)

        api.readResults += result(item())
        vm.retry()
        advanceUntilIdle()
        assertEquals(listOf("abc123"), api.retries)
        assertEquals(1, api.reads.size)
        assertEquals(Stage.Review, vm.state.value.stage)
    }

    @Test fun tagTappedDuringTheFlowIsSentAndSaved() = runTest(dispatcher) {
        val vm = vm()
        advanceUntilIdle()
        vm.addPhoto(byteArrayOf(1))
        advanceUntilIdle()
        taps.emit("4:77:90:e")
        advanceUntilIdle()
        assertEquals("4:77:90:e", vm.state.value.tag)
        assertEquals("4:77:90:e", store.get(vm.state.value.draftId!!)!!.tag)

        api.readResults += result(item(), tag = "4:77:90:e")
        vm.read()
        advanceUntilIdle()
        assertEquals("4:77:90:e", api.reads.single().tag)
        vm.preview()
        advanceUntilIdle()
        assertEquals("4:77:90:e", api.adds.single().tag)
    }

    @Test fun presetTagIsUsedAndCanBeCleared() = runTest(dispatcher) {
        val vm = vm(initialTag = "1:2:3:4")
        assertEquals("1:2:3:4", vm.state.value.tag)
        vm.clearTag()
        readOne(vm, item())
        assertNull(api.reads.single().tag)
    }

    @Test fun spoolmanErrorShowsCreatedIdsAndKeepsTheDraft() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item(count = 3))
        vm.preview()
        advanceUntilIdle()
        api.addFailures += ApiError(502, "spoolman_error", "spoolman failed part-way",
            buildJsonObject { put("partial_spool_ids", JsonArray(listOf(Json.parseToJsonElement("12"), Json.parseToJsonElement("13")))) })
        vm.confirm()
        advanceUntilIdle()
        val s = vm.state.value
        assertTrue(s.error!!.message, "#12, #13" in s.error.message)
        assertFalse(s.error.canRetry)
        assertNotNull(store.get(s.draftId!!))
    }

    @Test fun spoolmanUnreachableIsPlainAndRetryable() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        api.addFailures += ApiError(503, "spoolman_unreachable", "can't reach Spoolman")
        vm.preview()
        advanceUntilIdle()
        assertEquals("The server can't reach Spoolman. Check that Spoolman is running, then try again.",
            vm.state.value.error!!.message)
        assertTrue(vm.state.value.error!!.canRetry)
    }

    @Test fun tagConflictOffersAddingWithoutTheTag() = runTest(dispatcher) {
        val vm = vm(initialTag = "4:77")
        readOne(vm, item())
        api.addFailures += ApiError(409, "tag_conflict", "tag 4:77 is already linked to spool 5 SUNLU PLA",
            buildJsonObject { put("reason", "linked") })
        vm.preview()
        advanceUntilIdle()
        assertTrue(vm.state.value.error!!.canDropTag)
        vm.dropTagAndRetry()
        advanceUntilIdle()
        assertNull(vm.state.value.tag)
        assertEquals(listOf("4:77", null), api.adds.map { it.tag })
        assertEquals(Stage.Preview, vm.state.value.stage)
    }

    @Test fun certificateChangeGetsItsOwnState() = runTest(dispatcher) {
        val vm = vm()
        api.readFailures += FingerprintMismatch("aaaa", "bbbb")
        vm.addPhoto(byteArrayOf(1))
        advanceUntilIdle()
        vm.read()
        advanceUntilIdle()
        val e = vm.state.value.error!!
        assertEquals("aaaa", e.expectedFingerprint)
        assertEquals("bbbb", e.actualFingerprint)
        assertTrue(e.pairAgain)
    }

    @Test fun anyOtherExceptionIsAnUnexpectedResponse() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        api.addFailures += IllegalStateException("boom")
        vm.preview()
        advanceUntilIdle()
        assertEquals("Unexpected response from the server", vm.state.value.error!!.message)
        assertEquals(Stage.Review, vm.state.value.stage)
    }

    @Test fun reopeningADraftRestoresTheReview() = runTest(dispatcher) {
        val first = vm()
        first.setWeight(900.0)
        readOne(first, item())
        first.setText(0, "name", "Edited")
        advanceUntilIdle()
        val id = first.state.value.draftId!!

        val again = vm(draftId = id)
        advanceUntilIdle()
        val s = again.state.value
        assertEquals(Stage.Review, s.stage)
        assertEquals("Edited", s.items.single()["name"]!!.jsonPrimitive.content)
        assertEquals(900.0, s.weight!!, 0.0)
        assertEquals(1, s.photos.size)
    }
}

private class FakeIntakeApi : IntakeApi {
    data class Read(val photos: List<ByteArray>, val hint: String, val tag: String?)
    data class Add(val items: JsonArray, val dryRun: Boolean, val tag: String?)

    val reads = mutableListOf<Read>()
    val retries = mutableListOf<String>()
    val adds = mutableListOf<Add>()
    val readResults = ArrayDeque<ReadResult>()
    val readFailures = ArrayDeque<Exception>()
    val addResults = ArrayDeque<AddResult>()
    val addFailures = ArrayDeque<Exception>()

    override suspend fun read(photos: List<ByteArray>, hint: String, tag: String?): ReadResult {
        reads += Read(photos, hint, tag)
        readFailures.removeFirstOrNull()?.let { throw it }
        return readResults.removeFirst()
    }

    override suspend fun retry(readId: String): ReadResult {
        retries += readId
        readFailures.removeFirstOrNull()?.let { throw it }
        return readResults.removeFirst()
    }

    override suspend fun add(items: JsonArray, dryRun: Boolean, tag: String?): AddResult {
        adds += Add(items, dryRun, tag)
        addFailures.removeFirstOrNull()?.let { throw it }
        return addResults.removeFirstOrNull() ?: AddResult(emptyList(), listOf("ok"), dryRun)
    }

    override suspend fun locations(): List<String> = listOf("Shelf A", "Shelf B")
}
