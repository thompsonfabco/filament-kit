package com.thompsonfabco.filamentkit.ui.add

import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.net.AddResult
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FilamentChoice
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.net.Proposal
import com.thompsonfabco.filamentkit.net.ReadResult
import com.thompsonfabco.filamentkit.net.VendorChoice
import java.io.File
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
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

    /** The view models' wall clock (parent list age). */
    private var clockMs = 1_000_000L

    private fun vm(draftId: String? = null, initialTag: String? = null) = AddViewModel(
        api = api, store = store, taps = taps, draftId = draftId, initialTag = initialTag,
        prepare = { it }, io = dispatcher, clock = { clockMs },
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

    @Test fun aTareOfZeroOrLessBlocksPreview() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, JsonObject(item() + ("tare" to JsonPrimitive(0))))
        assertFalse(vm.state.value.taresValid)
        vm.preview()
        advanceUntilIdle()
        assertTrue("nothing sent with a 0 g tare", api.adds.isEmpty())
        // typing 0 or a negative never replaces it; a real weight does
        vm.setNumber(0, "tare", -5.0)
        assertFalse(vm.state.value.taresValid)
        vm.setNumber(0, "tare", 213.0)
        assertTrue(vm.state.value.taresValid)
        // blank (unknown) stays allowed
        vm.setNumber(0, "tare", null)
        assertTrue(vm.state.value.taresValid)
        vm.setNumber(0, "tare", 213.0)
        vm.preview()
        advanceUntilIdle()
        assertEquals(213.0, sentItem()["tare"]!!.jsonPrimitive.double, 0.0)
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

    @Test fun aSaveAfterAReadNamesTheRead() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        vm.preview()
        advanceUntilIdle()
        vm.confirm()
        advanceUntilIdle()
        assertEquals(listOf("r1", "r1"), api.adds.map { it.readId })
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
        // the reply may have been lost after a write: warn, and retry with a fresh preview, never a blind write
        assertEquals(AddViewModel.ADD_REPLY_LOST, s.error!!.message)
        assertTrue(s.error.canRetry)
        assertEquals(Stage.Review, s.stage)
        val draft = store.get(s.draftId!!)!!
        assertEquals("PLA+ Silver", draft.editedItems!![0].jsonObject["name"]!!.jsonPrimitive.content)

        vm.retry()
        advanceUntilIdle()
        assertEquals(listOf(true, false, true), api.adds.map { it.dryRun })
        assertEquals(Stage.Preview, vm.state.value.stage)

        // the reply was lost, so the next real add needs an explicit "I checked" first
        assertEquals(AddedBefore(emptyList()), vm.state.value.addedBefore)
        api.addResults += AddResult(listOf(7), listOf("added"), false)
        vm.confirm()
        advanceUntilIdle()
        assertTrue(vm.state.value.askAddAgain)
        assertEquals(listOf(true, false, true), api.adds.map { it.dryRun })
        vm.addAgain()
        advanceUntilIdle()
        assertEquals(listOf(true, false, true, false), api.adds.map { it.dryRun })
        assertEquals(Stage.Done, vm.state.value.stage)
        assertNull(store.get(s.draftId))
    }

    @Test fun partialAddShowsTheIdsAndNeedsAnAcknowledgementBeforeAddingAgain() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item(count = 3))
        vm.preview()
        advanceUntilIdle()
        api.addFailures += ApiError(502, "spoolman_error", "spoolman failed part-way",
            buildJsonObject { put("partial_spool_ids", JsonArray(listOf(Json.parseToJsonElement("12"), Json.parseToJsonElement("13")))) })
        vm.confirm()
        advanceUntilIdle()
        assertEquals(AddedBefore(listOf(12L, 13L)), vm.state.value.addedBefore)
        assertEquals("Spools already added: #12, #13", vm.state.value.addedBefore!!.note)

        vm.preview()
        advanceUntilIdle()
        assertEquals(Stage.Preview, vm.state.value.stage)
        vm.confirm()
        advanceUntilIdle()
        assertTrue(vm.state.value.askAddAgain)
        vm.cancelAddAgain()
        assertFalse(vm.state.value.askAddAgain)
        assertEquals(listOf(true, false, true), api.adds.map { it.dryRun })

        // still remembered when the draft is reopened later
        val reopened = vm(draftId = vm.state.value.draftId)
        advanceUntilIdle()
        assertEquals(AddedBefore(listOf(12L, 13L)), reopened.state.value.addedBefore)

        vm.confirm()
        api.addResults += AddResult(listOf(14), listOf("added"), false)
        vm.addAgain()
        advanceUntilIdle()
        assertEquals(listOf(true, false, true, false), api.adds.map { it.dryRun })
        assertEquals(Stage.Done, vm.state.value.stage)
    }

    @Test fun addAgainWithoutTheDialogDoesNothing() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        vm.preview()
        advanceUntilIdle()
        vm.addAgain()
        advanceUntilIdle()
        assertEquals(listOf(true), api.adds.map { it.dryRun })
    }

    @Test fun nonFiniteOrNonPositiveWeightsNeverReachTheDraft() = runTest(dispatcher) {
        val vm = vm()
        vm.setWeight(500.0)
        for (bad in listOf(Double.NaN, Double.POSITIVE_INFINITY, 0.0, -4.0)) {
            vm.setWeight(bad)
            assertNull(vm.state.value.weight)
        }
        readOne(vm, item())
        for (bad in listOf(Double.NaN, Double.NEGATIVE_INFINITY, 0.0)) {
            vm.setNumber(0, "net", bad)
            vm.setNumber(0, "gross", bad)
        }
        assertEquals(1000, vm.state.value.items[0]["net"]!!.jsonPrimitive.int)
        assertFalse("gross" in vm.state.value.items[0])
        // later saves still reach the draft
        vm.setText(0, "name", "PLA+ Silver")
        advanceUntilIdle()
        val draft = store.get(vm.state.value.draftId!!)!!
        assertNull(draft.weightGrams)
        assertEquals("PLA+ Silver", draft.editedItems!![0].jsonObject["name"]!!.jsonPrimitive.content)
    }

    @Test fun retryAfterAFailedAddNeverWritesLaterEdits() = runTest(dispatcher) {
        for (failure in listOf(ApiError(503, "spoolman_unreachable", "down"), ApiError(0, "offline", "gone"))) {
            api.adds.clear()
            val vm = vm()
            readOne(vm, item())
            vm.preview()
            advanceUntilIdle()
            api.addFailures += failure
            vm.confirm()
            advanceUntilIdle()
            assertTrue(vm.state.value.error!!.canRetry)

            vm.setText(0, "name", "Edited after the failure")
            assertNull(vm.state.value.error)
            vm.retry()
            advanceUntilIdle()
            vm.confirm()
            advanceUntilIdle()
            assertEquals(failure.code, listOf(true, false), api.adds.map { it.dryRun })
        }
    }

    @Test fun realAddRetryRepeatsTheAddFromThePreview() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        vm.preview()
        advanceUntilIdle()
        api.addFailures += ApiError(503, "spoolman_unreachable", "down")
        vm.confirm()
        advanceUntilIdle()
        assertEquals(Stage.Preview, vm.state.value.stage)
        api.addResults += AddResult(listOf(9), listOf("added"), false)
        vm.retry()
        advanceUntilIdle()
        assertEquals(listOf(true, false, false), api.adds.map { it.dryRun })
        assertEquals(Stage.Done, vm.state.value.stage)
    }

    @Test fun aNewTagAfterThePreviewNeedsANewPreview() = runTest(dispatcher) {
        val vm = vm(initialTag = "1:1")
        readOne(vm, item())
        vm.preview()
        advanceUntilIdle()
        taps.emit("1:1") // the same tag again changes nothing
        advanceUntilIdle()
        assertEquals(Stage.Preview, vm.state.value.stage)
        taps.emit("2:2")
        advanceUntilIdle()
        assertEquals(Stage.Review, vm.state.value.stage)
        vm.confirm()
        advanceUntilIdle()
        assertEquals(listOf(true), api.adds.map { it.dryRun })

        vm.preview()
        advanceUntilIdle()
        vm.clearTag()
        assertEquals(Stage.Review, vm.state.value.stage)
    }

    @Test fun tapsWhileACallRunsAreIgnored() = runTest(dispatcher) {
        val vm = vm(initialTag = "1:1")
        advanceUntilIdle()
        api.readResults += result(item(), tag = "9:9")
        api.gate = CompletableDeferred()
        vm.addPhoto(byteArrayOf(1))
        advanceUntilIdle()
        vm.read()
        advanceUntilIdle()
        assertEquals(Stage.Reading, vm.state.value.stage)
        taps.emit("2:2")
        advanceUntilIdle()
        api.gate!!.complete(Unit)
        advanceUntilIdle()
        assertEquals(Stage.Review, vm.state.value.stage)
        assertEquals("1:1", vm.state.value.tag) // neither the tap during Reading nor the reply's tag replaced it

        api.gate = CompletableDeferred()
        vm.preview()
        advanceUntilIdle()
        taps.emit("3:3")
        advanceUntilIdle()
        api.gate!!.complete(Unit)
        advanceUntilIdle()
        assertEquals(Stage.Preview, vm.state.value.stage)
        assertEquals("1:1", vm.state.value.tag)
        assertEquals("1:1", api.adds.single().tag)
    }

    @Test fun changingTheCountDropsGross() = runTest(dispatcher) {
        val vm = vm()
        vm.setWeight(812.5)
        readOne(vm, item())
        assertTrue("gross" in vm.state.value.items.single())
        vm.setCount(0, 2)
        vm.preview()
        advanceUntilIdle()
        assertFalse("gross" in sentItem())
    }

    @Test fun previewIsBlockedWhileACountIsMissing() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        vm.setCount(0, null)
        assertFalse(vm.state.value.countsValid)
        vm.preview()
        advanceUntilIdle()
        assertTrue(api.adds.isEmpty())
        vm.setCount(0, 1)
        vm.preview()
        advanceUntilIdle()
        assertEquals(1, api.adds.size)
    }

    @Test fun changedPhotosOrHintForgetTheFailedRead() = runTest(dispatcher) {
        val vm = vm()
        vm.addPhoto(byteArrayOf(1))
        advanceUntilIdle()
        api.readFailures += ApiError(502, "rate_limited", "busy", buildJsonObject { put("read_id", "old") })
        vm.read()
        advanceUntilIdle()
        vm.addPhoto(byteArrayOf(2))
        advanceUntilIdle()
        assertNull(vm.state.value.error)
        vm.retry()
        advanceUntilIdle()
        assertTrue(api.retries.isEmpty())

        api.readFailures += ApiError(502, "rate_limited", "busy", buildJsonObject { put("read_id", "old2") })
        vm.read()
        advanceUntilIdle()
        vm.setHint("all grey")
        vm.retry()
        advanceUntilIdle()
        assertTrue(api.retries.isEmpty())
    }

    @Test fun dropTagNeedsATagConflict() = runTest(dispatcher) {
        val vm = vm(initialTag = "4:77")
        readOne(vm, item())
        api.addFailures += ApiError(503, "spoolman_unreachable", "down")
        vm.preview()
        advanceUntilIdle()
        vm.dropTagAndRetry()
        advanceUntilIdle()
        assertEquals("4:77", vm.state.value.tag)
        assertEquals(1, api.adds.size)
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

    // ---------- product line and Bambu parent (stage 4 Task 9) ----------

    private fun lineItem(parent: String? = "Generic PLA", exists: Boolean = false) = JsonObject(
        item() + mapOf(
            "line" to JsonPrimitive("PLA+"),
            "bambu_parent" to (parent?.let(::JsonPrimitive) ?: JsonNull),
            "parent_source" to JsonPrimitive("material"),
            "line_exists" to JsonPrimitive(exists),
        ),
    )

    private fun proposal(parent: String?, exists: Boolean = false, source: String = "material") =
        Proposal("sunlu--pla-plus", "PLA+", parent, source, exists)

    private fun JsonObject.text(key: String): String? = (this[key] as? JsonPrimitive)?.contentOrNull

    @Test fun parentsForEachMaterialAreLoadedAfterTheRead() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA", "SUNLU PLA+"), synced = true)
        val vm = vm()
        readOne(vm, lineItem())
        assertEquals(ParentList(listOf("Generic PLA", "SUNLU PLA+"), true), vm.state.value.parents["PLA"])
        assertEquals(listOf("PLA"), api.parentCalls)
    }

    @Test fun anEditReProposesAfterAPauseAndTakesTheProposedParent() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, lineItem())
        api.proposals += proposal("SUNLU PLA+ HS", exists = true, source = "brand")
        vm.setText(0, "line", "PLA+ H")
        advanceTimeBy(200)
        vm.setText(0, "line", "PLA+ HS")
        advanceTimeBy(400)
        assertTrue("debounced: nothing yet", api.proposeCalls.isEmpty())
        advanceUntilIdle()
        assertEquals(listOf(Triple("SUNLU", "PLA+ HS", "PLA")), api.proposeCalls)
        val it = vm.state.value.items.single()
        assertEquals("SUNLU PLA+ HS", it.text("bambu_parent"))
        assertEquals("brand", it.text("parent_source"))
        assertEquals("true", it.text("line_exists"))
        assertEquals("the typed line is kept", "PLA+ HS", it.text("line"))
    }

    @Test fun aPickedParentIsKeptWhenTheMaterialChangesTheProposal() = runTest(dispatcher) {
        api.parentLists["PETG"] = ParentList(listOf("Generic PETG"), synced = true)
        val vm = vm()
        readOne(vm, lineItem())
        vm.setParent(0, "SUNLU PLA+")
        advanceUntilIdle()
        api.proposeCalls.clear()
        api.proposals += proposal("Generic PETG")
        vm.setText(0, "material", "PETG")
        advanceUntilIdle()
        assertEquals(listOf(Triple("SUNLU", "PLA+", "PETG")), api.proposeCalls)
        assertEquals("SUNLU PLA+", vm.state.value.items.single().text("bambu_parent"))
        assertEquals("parents of the new material are loaded", listOf("Generic PETG"), vm.state.value.parents["PETG"]!!.parents)
    }

    @Test fun clearingThePickedParentLetsTheProposalChooseAgain() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, lineItem())
        vm.setParent(0, "SUNLU PLA+")
        api.proposals += proposal("Generic PLA")
        vm.setParent(0, "")
        advanceUntilIdle()
        assertEquals("Generic PLA", vm.state.value.items.single().text("bambu_parent"))
    }

    @Test fun aFailedProposalChangesNothing() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, lineItem())
        vm.setText(0, "material", "PLA Matte")
        advanceUntilIdle() // the fake has no proposal queued: it fails
        assertEquals(1, api.proposeCalls.size)
        assertEquals("Generic PLA", vm.state.value.items.single().text("bambu_parent"))
        assertNull(vm.state.value.error)
    }

    @Test fun aProposalForValuesThatChangedSinceIsDropped() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, lineItem())
        val gate = CompletableDeferred<Unit>()
        api.proposeGate = gate
        vm.setText(0, "material", "PETG")
        advanceUntilIdle() // propose is waiting on the gate
        api.proposeGate = null
        api.proposals += proposal("Generic ABS")
        vm.setText(0, "material", "ABS") // the PETG answer is now stale; this edit cancels it
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals("Generic ABS", vm.state.value.items.single().text("bambu_parent"))
    }

    @Test fun addSendsLineAndParentButNotTheAppMarker() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, lineItem())
        vm.setText(0, "line", "PLA+ 2.0")
        vm.setParent(0, "SUNLU PLA+ 2.0")
        api.proposals += proposal("Generic PLA")
        advanceUntilIdle()
        vm.preview()
        advanceUntilIdle()
        val sent = sentItem()
        assertEquals("PLA+ 2.0", sent.text("line"))
        assertEquals("SUNLU PLA+ 2.0", sent.text("bambu_parent"))
        assertFalse(sent.keys.any { it.startsWith("app_") })
        assertEquals("keep me", sent.text("future_field"))
    }

    @Test fun aPickSurvivesReopeningTheDraft() = runTest(dispatcher) {
        val first = vm()
        readOne(first, lineItem())
        first.setParent(0, "SUNLU PLA+")
        advanceUntilIdle()
        val again = vm(draftId = first.state.value.draftId!!)
        advanceUntilIdle()
        api.proposals += proposal("Generic PETG")
        again.setText(0, "material", "PETG")
        advanceUntilIdle()
        assertEquals("SUNLU PLA+", again.state.value.items.single().text("bambu_parent"))
    }

    // ---------- fix round 1 ----------

    private fun JsonObject.picked() = containsKey(AddViewModel.PICKED)

    @Test fun anUnpickedProposedParentIsNotSentButAPickedOneIs() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, lineItem(), lineItem())
        vm.setParent(1, "SUNLU PLA+")
        vm.preview()
        advanceUntilIdle()
        val unpicked = sentItem(index = 0)
        assertFalse("the server's own proposal is not sent back", unpicked.containsKey("bambu_parent"))
        assertEquals("PLA+", unpicked.text("line"))
        assertEquals("SUNLU PLA+", sentItem(index = 1).text("bambu_parent"))
        assertEquals("the screen still shows the proposal", "Generic PLA", vm.state.value.items[0].text("bambu_parent"))
    }

    @Test fun whenSyncedOnlyAListedParentOrBlankIsAccepted() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA", "SUNLU PLA+"), synced = true)
        val vm = vm()
        readOne(vm, lineItem())
        vm.setParent(0, "Made Up PLA")
        assertEquals("Generic PLA", vm.state.value.items.single().text("bambu_parent"))
        assertFalse(vm.state.value.items.single().picked())
        vm.typeParent(0, "Typed PLA")
        assertEquals("typing is ignored while synced", "Generic PLA", vm.state.value.items.single().text("bambu_parent"))
        vm.setParent(0, "SUNLU PLA+")
        assertEquals("SUNLU PLA+", vm.state.value.items.single().text("bambu_parent"))
        assertTrue(vm.state.value.items.single().picked())
        api.proposals += proposal("Generic PLA")
        vm.setParent(0, "") // Automatic
        advanceUntilIdle()
        assertFalse(vm.state.value.items.single().picked())
        assertEquals("Generic PLA", vm.state.value.items.single().text("bambu_parent"))
    }

    @Test fun freeTextTypingIsAPickOnlyWhenCommitted() = runTest(dispatcher) {
        val vm = vm() // parents not synced: free text
        readOne(vm, lineItem())
        vm.typeParent(0, "SUN")
        vm.typeParent(0, "SUNLU PLA+ HS")
        assertFalse("keystrokes are not picks", vm.state.value.items.single().picked())
        assertEquals("SUNLU PLA+ HS", vm.state.value.items.single().text("bambu_parent"))
        api.proposals += proposal("Generic PETG")
        vm.setText(0, "material", "PETG")
        advanceUntilIdle()
        assertEquals("a proposal does not overwrite text being typed", "SUNLU PLA+ HS", vm.state.value.items.single().text("bambu_parent"))
        vm.commitParent(0)
        assertTrue(vm.state.value.items.single().picked())
    }

    @Test fun previewCommitsTypedParentText() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, lineItem())
        vm.typeParent(0, "SUNLU PLA+ HS")
        vm.preview()
        advanceUntilIdle()
        assertEquals("SUNLU PLA+ HS", sentItem().text("bambu_parent"))
    }

    @Test fun committingBlankTypedTextIsNoPickAndProposesAgain() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, lineItem())
        vm.typeParent(0, "")
        api.proposals += proposal("Generic PLA")
        vm.commitParent(0)
        advanceUntilIdle()
        assertFalse(vm.state.value.items.single().picked())
        assertEquals("Generic PLA", vm.state.value.items.single().text("bambu_parent"))
    }

    @Test fun unknownParentOnAddIsAParentFieldError() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, lineItem())
        vm.setParent(0, "Foo PLA")
        api.addFailures += ApiError(400, "unknown_parent", "Bambu Studio has no preset named Foo PLA")
        vm.preview()
        advanceUntilIdle()
        val s = vm.state.value
        assertEquals(Stage.Review, s.stage)
        assertEquals(UNKNOWN_PARENT, s.parentError)
        assertEquals(UNKNOWN_PARENT, s.error!!.message)
        assertEquals("Bambu Studio has no preset named Foo PLA", s.error?.detail)
        vm.setParent(0, "Generic PLA")
        assertNull("an edit clears it", vm.state.value.parentError)
    }

    @Test fun intakeTextRuleHints() {
        assertNull(intakeTextProblem("SUNLU PLA+"))
        assertNull(intakeTextProblem(""))
        assertNull(intakeTextProblem("a".repeat(100)))
        assertEquals("At most 100 characters", intakeTextProblem("a".repeat(101)))
        assertEquals("No @ (leave out the printer part)", intakeTextProblem("Generic PLA @BBL H2D"))
    }

    @Test fun parentListsAreReloadedAfterStartOver() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, lineItem())
        vm.preview()
        advanceUntilIdle()
        vm.confirm()
        advanceUntilIdle()
        vm.startOver()
        readOne(vm, lineItem())
        assertEquals(listOf("PLA", "PLA"), api.parentCalls)
    }

    @Test fun parentListsOlderThanFiveMinutesAreReloaded() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, lineItem())
        assertEquals(listOf("PLA"), api.parentCalls)
        vm.setText(0, "line", "PLA+ 2")
        advanceUntilIdle()
        assertEquals("fresh: cached", listOf("PLA"), api.parentCalls)
        clockMs += 5 * 60_000L + 1
        vm.setText(0, "line", "PLA+ 3")
        advanceUntilIdle()
        assertEquals(listOf("PLA", "PLA"), api.parentCalls)
    }
}

internal class FakeIntakeApi : IntakeApi {
    data class Read(val photos: List<ByteArray>, val hint: String, val tag: String?)
    data class Add(val items: JsonArray, val dryRun: Boolean, val tag: String?, val readId: String? = null)

    val reads = mutableListOf<Read>()
    val retries = mutableListOf<String>()
    val adds = mutableListOf<Add>()
    val readResults = ArrayDeque<ReadResult>()
    val readFailures = ArrayDeque<Exception>()
    val addResults = ArrayDeque<AddResult>()
    val addFailures = ArrayDeque<Exception>()
    /** When set, read/add wait for it (to act while a call is running). */
    var gate: CompletableDeferred<Unit>? = null

    override suspend fun read(photos: List<ByteArray>, hint: String, tag: String?): ReadResult {
        reads += Read(photos, hint, tag)
        gate?.await()
        readFailures.removeFirstOrNull()?.let { throw it }
        return readResults.removeFirst()
    }

    override suspend fun retry(readId: String): ReadResult {
        retries += readId
        readFailures.removeFirstOrNull()?.let { throw it }
        return readResults.removeFirst()
    }

    override suspend fun add(items: JsonArray, dryRun: Boolean, tag: String?, readId: String?): AddResult {
        adds += Add(items, dryRun, tag, readId)
        gate?.await()
        addFailures.removeFirstOrNull()?.let { throw it }
        return addResults.removeFirstOrNull() ?: AddResult(emptyList(), listOf("ok"), dryRun)
    }

    override suspend fun locations(): List<String> = listOf("Shelf A", "Shelf B")

    val proposeCalls = mutableListOf<Triple<String, String, String>>()
    val proposals = ArrayDeque<Proposal>()
    var proposeGate: CompletableDeferred<Unit>? = null
    val parentLists = mutableMapOf<String, ParentList>()
    val parentCalls = mutableListOf<String>()

    override suspend fun propose(vendor: String, line: String, material: String): Proposal {
        proposeCalls += Triple(vendor, line, material)
        proposeGate?.await()
        return proposals.removeFirstOrNull() ?: throw ApiError(0, "offline", "down")
    }

    override suspend fun parents(material: String): ParentList {
        parentCalls += material
        return parentLists[material] ?: ParentList(emptyList(), synced = false)
    }

    val filamentCalls = mutableListOf<String>()
    var filamentList: (String) -> List<FilamentChoice> = { emptyList() }
    var filamentFailure: Exception? = null
    var vendorList = emptyList<VendorChoice>()

    override suspend fun filaments(q: String): List<FilamentChoice> {
        filamentCalls += q
        filamentFailure?.let { throw it }
        return filamentList(q)
    }

    override suspend fun vendors(): List<VendorChoice> = vendorList
}
