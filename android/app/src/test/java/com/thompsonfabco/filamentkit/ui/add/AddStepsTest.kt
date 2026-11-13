package com.thompsonfabco.filamentkit.ui.add

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.net.AddResult
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.ReadResult
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.CompletableDeferred
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
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

/** The Add spools step logic of S4.7 (05-android-app 6): steps, marks, undo, the check's problems, the error words. */
@OptIn(ExperimentalCoroutinesApi::class)
class AddStepsTest {
    private val dispatcher = StandardTestDispatcher()
    private lateinit var dir: File
    private lateinit var store: DraftStore
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

    private fun vm() = AddViewModel(
        api = api, store = store, taps = MutableSharedFlow(), prepare = { it }, io = dispatcher,
    )

    private fun item(estimates: List<String> = listOf("tare"), name: String = "PLA+ Grey") = buildJsonObject {
        put("vendor", "SUNLU")
        put("name", name)
        put("material", "PLA")
        put("color_hex", "808080")
        put("net", 1000)
        put("tare", 213)
        put("count", 1)
        put("estimates", JsonArray(estimates.map(::JsonPrimitive)))
        put("sealed", true)
    }

    private fun TestScope.readOne(vm: AddViewModel, vararg items: JsonObject) {
        api.readResults += ReadResult(JsonArray(items.toList()), emptyList(), null, null, "r1")
        vm.addPhoto(byteArrayOf(1, 2, 3))
        advanceUntilIdle()
        vm.read()
        advanceUntilIdle()
    }

    @Test fun aNewPhotoDraftStartsSealedAndOnThePhotosStep() {
        val s = vm().state.value
        assertTrue(s.sealed)
        assertEquals(AddStep.Photos, stepOf(s.stage))
    }

    @Test fun everyStageBelongsToOneStepAndTheNumbersFollowThePath() {
        assertEquals(AddStep.Photos, stepOf(Stage.Reading))
        assertEquals(AddStep.Check, stepOf(Stage.Review))
        assertEquals(AddStep.Preview, stepOf(Stage.Previewing))
        assertEquals(AddStep.Preview, stepOf(Stage.Adding))
        assertEquals(AddStep.Done, stepOf(Stage.Done))
        assertEquals(1 to 3, stepNumber(AddStep.Photos, manual = false))
        assertEquals(3 to 3, stepNumber(AddStep.Preview, manual = false))
        assertEquals(1 to 2, stepNumber(AddStep.Check, manual = true))
        assertEquals(2 to 2, stepNumber(AddStep.Preview, manual = true))
        assertNull(stepNumber(AddStep.Done, manual = false))
    }

    @Test fun aFieldInTheEstimatesListIsMarkedUntilItIsEdited() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item(estimates = listOf("tare", "net")))
        assertEquals(mapOf("tare" to Mark.Estimated, "net" to Mark.Estimated), marksOf(vm.state.value.items[0], manual = false).filterValues { it == Mark.Estimated })
        vm.setNumber(0, "tare", 200.0)
        val marks = marksOf(vm.state.value.items[0], manual = false)
        assertNull("editing removes the mark", marks["tare"])
        assertEquals(Mark.Estimated, marks["net"])
    }

    @Test fun aFieldTheReaderLeftEmptyIsNotOnTheLabelUntilTyped() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item(estimates = emptyList()))
        assertEquals(Mark.NotOnLabel, marksOf(vm.state.value.items[0], manual = false)["line"])
        vm.setText(0, "line", "PLA+")
        assertNull(marksOf(vm.state.value.items[0], manual = false)["line"])
        vm.setText(0, "line", "")
        assertNull("emptied by the person: not the reader's doing", marksOf(vm.state.value.items[0], manual = false)["line"])
        assertTrue("a hand add has no marks", marksOf(vm.state.value.items[0], manual = true).isEmpty())
    }

    @Test fun theAppsOwnKeysAreNeverSent() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        vm.setNumber(0, "tare", 200.0)
        vm.preview()
        advanceUntilIdle()
        val sent = api.adds[0].items[0] as JsonObject
        assertFalse(sent.keys.any { it.startsWith("app_") })
    }

    @Test fun aRemovedPhotoComesBackWithUndo() = runTest(dispatcher) {
        val vm = vm()
        vm.addPhoto(byteArrayOf(1))
        vm.addPhoto(byteArrayOf(2, 2))
        advanceUntilIdle()
        vm.removePhoto(0)
        advanceUntilIdle()
        assertEquals(AddEvent.PhotoRemoved, vm.events.first())
        assertEquals(1, vm.state.value.photos.size)
        vm.undoPhoto()
        advanceUntilIdle()
        assertEquals(2, vm.state.value.photos.size)
        assertEquals(2, store.get(vm.state.value.draftId!!)!!.photos.size)
    }

    @Test fun aRemovedSpoolComesBackWhereItWasAndIsRevealed() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item(name = "A"), item(name = "B"), item(name = "C"))
        vm.removeItem(1)
        assertEquals(AddEvent.SpoolRemoved, vm.events.first())
        assertEquals(listOf("A", "C"), vm.state.value.items.map { (it["name"] as JsonPrimitive).content })
        vm.undoRemoveItem()
        assertEquals(listOf("A", "B", "C"), vm.state.value.items.map { (it["name"] as JsonPrimitive).content })
        assertEquals(1, vm.state.value.reveal)
        vm.revealDone()
        assertNull(vm.state.value.reveal)
    }

    @Test fun theHubsComplaintAboutAFieldStaysOnThePreviewStepWithAFix() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        api.addFailures += ApiError(400, "bad_request", "SUNLU PLA+ Grey: net must be a positive number")
        vm.preview()
        advanceUntilIdle()
        var s = vm.state.value
        assertEquals(Stage.Preview, s.stage)
        assertTrue(s.previewFailed)
        assertEquals(PreviewProblem("SUNLU PLA+ Grey: net must be a positive number", 0, "net"), s.problems.single())
        // Add is off while the check failed
        vm.confirm()
        assertEquals(1, api.adds.size)
        vm.fixField(0, "net")
        s = vm.state.value
        assertEquals(Stage.Review, s.stage)
        assertEquals(0 to "net", s.focus)
        assertTrue(s.problems.isEmpty())
        vm.focusDone()
        assertNull(vm.state.value.focus)
    }

    @Test fun backToTheCheckLeavesThePreviewButNotWhileAdding() = runTest(dispatcher) {
        val vm = vm()
        readOne(vm, item())
        vm.preview()
        advanceUntilIdle()
        assertEquals(Stage.Preview, vm.state.value.stage)
        api.gate = CompletableDeferred()
        vm.confirm()
        advanceUntilIdle()
        assertEquals(Stage.Adding, vm.state.value.stage)
        vm.backToCheck()
        assertEquals("the add is running: nothing happens", Stage.Adding, vm.state.value.stage)
        api.gate!!.complete(Unit)
        advanceUntilIdle()
        assertEquals(Stage.Done, vm.state.value.stage)
    }

    @Test fun theDoneStepKeepsTheHubsRecordAndTheTagThatWasSent() = runTest(dispatcher) {
        val vm = vm()
        vm.onTag("04A1")
        readOne(vm, item())
        vm.preview()
        advanceUntilIdle()
        api.addResults += AddResult(listOf(212), listOf("added"), false, "h-9")
        vm.confirm()
        advanceUntilIdle()
        val s = vm.state.value
        assertEquals(Stage.Done, s.stage)
        assertEquals("h-9", s.historyId)
        assertEquals("04A1", s.doneTag)
        assertEquals(listOf(212), s.spoolIds)
    }

    @Test fun aNoLongerPairedNoticeGoesWhenTheHubAnswersAgain() = runTest(dispatcher) {
        val vm = vm()
        api.readFailures += ApiError(401, "unauthorized", "no")
        vm.addPhoto(byteArrayOf(1))
        advanceUntilIdle()
        vm.read()
        advanceUntilIdle()
        assertTrue(vm.state.value.error!!.pairAgain)
        api.readResults += ReadResult(JsonArray(listOf(item())), emptyList(), null, null, "r1")
        vm.read()
        advanceUntilIdle()
        assertNull(vm.state.value.error)
        assertEquals(Stage.Review, vm.state.value.stage)
    }

    @Test fun cancellingTheReadKeepsTheDraftAndThePhotos() = runTest(dispatcher) {
        val vm = vm()
        vm.addPhoto(byteArrayOf(1))
        advanceUntilIdle()
        api.gate = CompletableDeferred()
        api.readResults += ReadResult(JsonArray(listOf(item())), emptyList(), null, null, "r1")
        vm.read()
        advanceUntilIdle()
        assertEquals(Stage.Reading, vm.state.value.stage)
        vm.cancelRead()
        api.gate!!.complete(Unit)
        advanceUntilIdle()
        assertEquals(Stage.Capture, vm.state.value.stage)
        assertEquals(1, store.get(vm.state.value.draftId!!)!!.photos.size)
        assertTrue("the answer that came late was not used", vm.state.value.items.isEmpty())
    }

    @Test fun errorWordsFollowTheRealApiErrorShapes() {
        // no route to the Hub
        assertEquals(R.string.common_hub_unreachable, describe(ApiError(0, "offline", "x")).message.res)
        // not the Hub speaking: unreadable, or an error page without the Hub's own message
        assertEquals(R.string.common_hub_answer_unknown, describe(ApiError(502, ApiError.BAD_RESPONSE, "x")).message.res)
        assertEquals(R.string.common_hub_answer_unknown, describe(ApiError(500, "other", "The server returned an error (500)")).message.res)
        // the Hub's own message goes through as given
        val own = describe(ApiError(409, "conflict", "The Hub says no"))
        assertEquals("The Hub says no", own.message.verbatim)
        assertEquals(R.string.add_read_busy, describe(ApiError(429, "rate_limited", "x")).message.res)
        assertEquals(R.string.add_read_busy, describe(ApiError(502, "local_busy", "x")).message.res)
        assertTrue(describe(ApiError(402, "daily_cap", "x")).canAddByHand)
        assertTrue(describe(FingerprintMismatch("aa", "bb")).pairAgain)
        assertEquals(R.string.common_hub_answer_unknown, describe(IllegalStateException("x")).message.res)
    }

    @Test fun aReadThatCannotReachTheHubKeepsThePhotosAndSaysSo() = runTest(dispatcher) {
        val vm = vm()
        api.readFailures += ApiError(0, "offline", "x")
        vm.addPhoto(byteArrayOf(1))
        advanceUntilIdle()
        vm.read()
        advanceUntilIdle()
        assertEquals(R.string.add_read_offline, vm.state.value.error!!.message.res)
        assertEquals(1, vm.state.value.photos.size)
    }

    @Test fun whatAPanelStillNeedsIsListedInOrder() {
        val s = AddUiState(stage = Stage.Review, items = listOf(JsonObject(mapOf("vendor" to JsonPrimitive("A"), "name" to JsonPrimitive("n"), "material" to JsonNull))))
        assertEquals(listOf(listOf("material", "net", "tare", "count")), s.missing)
        assertFalse(s.complete)
    }
}
