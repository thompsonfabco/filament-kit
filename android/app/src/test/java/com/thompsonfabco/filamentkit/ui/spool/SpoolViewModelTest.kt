package com.thompsonfabco.filamentkit.ui.spool

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import androidx.lifecycle.SavedStateHandle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SpoolViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val backend = FakeSpoolBackend()
    private val first = spoolJson(214).toSpoolSummary()

    @Before fun setUp() {
        Dispatchers.setMain(dispatcher)
        SpoolCache.clear()
    }

    @After fun tearDown() = Dispatchers.resetMain()

    private fun vm(initial: SpoolSummary? = first, tag: String? = null) = SpoolViewModel(214, backend, initial, tag)

    @Test fun itOpensWithTheSummaryItWasGivenAndAsksNothing() = runTest(dispatcher) {
        val vm = vm(tag = "04A1B2")
        runCurrent()
        assertEquals(first, vm.state.value.spool)
        assertEquals("04A1B2", vm.state.value.openedByTag)
        assertFalse(vm.state.value.loading)
        assertTrue(backend.calls.isEmpty())
    }

    @Test fun afterARestartItFindsTheSpoolAmongTheHubsSpools() = runTest(dispatcher) {
        backend.spools = listOf(spoolJson(7), spoolJson(214, remaining = 500.0))
        val vm = vm(initial = null)
        assertTrue(vm.state.value.loading)
        advanceUntilIdle()
        assertEquals(500.0, vm.state.value.spool!!.remaining!!, 0.0)
        assertFalse(vm.state.value.loading)
        assertEquals(listOf("spool:214"), backend.calls)
    }

    @Test fun refreshAsksForThisSpoolByItsNumberEvenWhenTheTagMovedAway() = runTest(dispatcher) {
        val tagged = spoolJson(214, tag = "04A1B2").toSpoolSummary()
        // the tag was moved to spool 300 meanwhile; spool 214 is still there
        backend.tagAnswer = spoolJson(300, tag = "04A1B2", remaining = 10.0)
        backend.spools = listOf(spoolJson(214, remaining = 480.0))
        val vm = vm(initial = tagged)
        vm.refresh()
        assertTrue(vm.state.value.loading)
        advanceUntilIdle()
        assertEquals(214, vm.state.value.spool!!.id)
        assertEquals(480.0, vm.state.value.spool!!.remaining!!, 0.0)
        assertEquals(listOf("spool:214"), backend.calls)
    }

    @Test fun aSpoolTheHubDoesNotHaveIsAFailureWithTryAgainNeverABlankScreen() = runTest(dispatcher) {
        val vm = vm(initial = null)
        advanceUntilIdle()
        assertNull(vm.state.value.spool)
        assertFalse(vm.state.value.loading)
        assertEquals(HubFailure.Message("spool 214 was not found"), vm.state.value.failure)
        assertEquals(Retry.Refresh, vm.state.value.retry)
        backend.spools = listOf(spoolJson(214))
        vm.retry()
        advanceUntilIdle()
        assertEquals(214, vm.state.value.spool!!.id)
        assertNull(vm.state.value.failure)
    }

    @Test fun aFailedRefreshKeepsTheSpoolAndSaysWhy() = runTest(dispatcher) {
        backend.failure = "spool" to ApiError(0, "offline", "no route")
        val vm = vm()
        vm.refresh()
        advanceUntilIdle()
        assertEquals(first, vm.state.value.spool)
        assertEquals(HubFailure.Unreachable, vm.state.value.failure)
        assertFalse(vm.state.value.loading)
    }

    // ---- Update weight ----

    @Test fun aValidWeightIsPreviewedAfter400msAndTypingAgainDropsThePreview() = runTest(dispatcher) {
        backend.updateAnswer = { gross, _, _, _ -> spoolJson(214, remaining = (gross ?: 0.0) - 140) }
        val vm = vm()
        vm.openWeight()
        vm.setWeight("622")
        runCurrent()
        assertTrue(vm.state.value.weight!!.previewing)
        advanceTimeBy(399)
        assertTrue(backend.calls.isEmpty())
        advanceTimeBy(2)
        runCurrent()
        val w = vm.state.value.weight!!
        assertEquals(482.0, w.preview!!.becomes!!, 0.0)
        assertEquals(620.0, w.preview!!.now!!, 0.0)
        assertTrue(w.canSave)
        assertEquals(listOf("update:214:gross=622.0:location=null:empty=false:dry=true"), backend.calls)

        vm.setWeight("6225")
        assertNull(vm.state.value.weight!!.preview)
        assertFalse(vm.state.value.weight!!.canSave)
    }

    @Test fun anInvalidWeightIsNeverSent() = runTest(dispatcher) {
        val vm = vm()
        vm.openWeight()
        for (bad in listOf("0", "-5", "abc", "1e400", "NaN")) {
            vm.setWeight(bad)
            advanceTimeBy(1_000)
        }
        assertTrue(backend.calls.isEmpty())
        assertTrue(vm.state.value.weight!!.invalid)
        vm.saveWeight()
        assertTrue(backend.calls.isEmpty())
    }

    @Test fun savingNeedsThePreviewFirst() = runTest(dispatcher) {
        val vm = vm()
        vm.openWeight()
        vm.setWeight("622")
        vm.saveWeight()
        advanceTimeBy(100)
        assertTrue("no save before the preview is shown", backend.calls.none { it.endsWith("dry=false") })
    }

    @Test fun savingWritesTheWeightClosesTheSheetAndSetsTheResultLine() = runTest(dispatcher) {
        backend.updateAnswer = { gross, _, _, dry -> spoolJson(214, remaining = if (dry) 482.0 else 481.5) }
        val vm = vm()
        vm.openWeight()
        vm.setWeight("622")
        advanceTimeBy(500)
        runCurrent()
        vm.saveWeight()
        assertTrue(vm.state.value.weight!!.saving)
        assertTrue("a save in flight is waited for", vm.state.value.writing)
        vm.closeWeight()
        assertNotNull("the sheet cannot be closed while it saves", vm.state.value.weight)
        advanceUntilIdle()
        assertNull(vm.state.value.weight)
        assertEquals(SpoolResult.WeightUpdated(481.5), vm.state.value.result)
        assertEquals(481.5, vm.state.value.spool!!.remaining!!, 0.0)
        assertTrue(backend.calls.last().endsWith("gross=622.0:location=null:empty=false:dry=false"))
    }

    @Test fun aRefusedSaveKeepsTheSheetAndTheTypedWeight() = runTest(dispatcher) {
        val vm = vm()
        vm.openWeight()
        vm.setWeight("100")
        advanceTimeBy(500)
        runCurrent()
        backend.failure = "update" to ApiError(400, "bad_request", "gross 100 g is below the spool tare 140 g - check the weight")
        vm.saveWeight()
        advanceUntilIdle()
        val w = vm.state.value.weight!!
        assertEquals("100", w.text)
        assertFalse(w.saving)
        assertEquals(HubFailure.Message("gross 100 g is below the spool tare 140 g - check the weight"), w.failure)
        assertNull(vm.state.value.result)
    }

    @Test fun closingWithoutATypedWeightJustCloses() = runTest(dispatcher) {
        val vm = vm()
        vm.openWeight()
        assertFalse(vm.state.value.weight!!.dirty)
        vm.closeWeight()
        assertNull(vm.state.value.weight)
    }

    // ---- Move ----

    @Test fun movingToAnotherLocationSavesAtOnceAndOffersUndo() = runTest(dispatcher) {
        backend.updateAnswer = { _, location, _, _ -> spoolJson(214, location = location) }
        val vm = vm()
        vm.openMove()
        advanceUntilIdle()
        assertEquals(listOf("Shelf B", "Workshop X1 A1", "Dry box 1"), vm.state.value.move!!.locations)
        vm.move("Shelf B")
        assertEquals("Shelf B", vm.state.value.move!!.movingTo)
        assertTrue(vm.state.value.writing)
        advanceUntilIdle()
        assertNull(vm.state.value.move)
        assertEquals("Shelf B", vm.state.value.spool!!.location)
        assertEquals(SpoolResult.Moved("Shelf B"), vm.state.value.result)
        assertEquals(MoveToast("Shelf B", previous = "Workshop X1 A1"), vm.state.value.moveToast)

        vm.toastShown()
        vm.undoMove("Workshop X1 A1")
        advanceUntilIdle()
        assertEquals("Workshop X1 A1", vm.state.value.spool!!.location)
        assertNull("undoing a move offers no second undo", vm.state.value.moveToast)
        assertEquals(
            listOf("locations", "update:214:gross=null:location=Shelf B:empty=false:dry=false", "update:214:gross=null:location=Workshop X1 A1:empty=false:dry=false"),
            backend.calls,
        )
    }

    @Test fun theCurrentLocationOnlyClosesTheSheet() = runTest(dispatcher) {
        val vm = vm()
        vm.openMove()
        advanceUntilIdle()
        vm.move("Workshop X1 A1")
        assertNull(vm.state.value.move)
        assertEquals(listOf("locations"), backend.calls)
    }

    @Test fun aFailedMoveStaysInTheSheetWithItsNotice() = runTest(dispatcher) {
        val vm = vm()
        vm.openMove()
        advanceUntilIdle()
        backend.failure = "update" to ApiError(0, "offline", "gone")
        vm.move("Shelf B")
        advanceUntilIdle()
        assertEquals(HubFailure.Unreachable, vm.state.value.move!!.failure)
        assertNull(vm.state.value.move!!.movingTo)
        assertEquals("Workshop X1 A1", vm.state.value.spool!!.location)
        assertNull(vm.state.value.result)
    }

    @Test fun noLocationsIsAnEmptyListNotAFailure() = runTest(dispatcher) {
        backend.locations = emptyList()
        val vm = vm()
        vm.openMove()
        advanceUntilIdle()
        assertEquals(emptyList<String>(), vm.state.value.move!!.locations)
        assertNull(vm.state.value.move!!.failure)
    }

    // ---- Mark empty ----

    @Test fun markingEmptyAsksThenWritesAndSetsTheResult() = runTest(dispatcher) {
        backend.updateAnswer = { _, _, empty, _ -> spoolJson(214, remaining = 0.0, archived = empty) }
        val vm = vm()
        vm.askMarkEmpty()
        assertTrue(vm.state.value.confirmEmpty)
        vm.cancelEmpty()
        assertFalse(vm.state.value.confirmEmpty)
        assertTrue(backend.calls.isEmpty())
        vm.askMarkEmpty()
        vm.confirmEmpty()
        assertTrue(vm.state.value.emptying)
        advanceUntilIdle()
        assertFalse(vm.state.value.confirmEmpty)
        assertEquals(SpoolState.Empty, vm.state.value.spool!!.state)
        assertEquals(SpoolResult.MarkedEmpty, vm.state.value.result)
        assertEquals(listOf("update:214:gross=null:location=null:empty=true:dry=false"), backend.calls)
    }

    // ---- Hub notices and results from other screens ----

    @Test fun aHubNoticeClearsAfterTheNextSuccessfulCall() = runTest(dispatcher) {
        backend.spools = listOf(spoolJson(214))
        val vm = vm()
        backend.failure = "spool" to ApiError(401, "unauthorized", "nope")
        vm.refresh()
        advanceUntilIdle()
        assertEquals(HubFailure.NotPaired, vm.state.value.failure)
        vm.refresh()
        advanceUntilIdle()
        assertNull(vm.state.value.failure)
    }

    @Test fun aChangedCertificateIsItsOwnNotice() = runTest(dispatcher) {
        val vm = vm()
        backend.failure = "spool" to FingerprintMismatch("aa", "bb")
        vm.refresh()
        advanceUntilIdle()
        assertEquals(HubFailure.CertificateChanged, vm.state.value.failure)
    }

    @Test fun aResultTheLoadStepsEndedWithIsShownAndTakenFromTheSavedState() = runTest(dispatcher) {
        val handle = SavedStateHandle()
        val vm = SpoolViewModel(214, backend, first, handle = handle)
        runCurrent()
        // what the load step does: the spool as the Hub has it now goes to the cache, the result to the entry's saved state
        SpoolCache.put(spoolJson(214, location = "Workshop X1 A2").toSpoolSummary())
        handle[SpoolViewModel.RESULT_KEY] = SpoolResult.Loaded("Workshop X1", "A2").encode()
        runCurrent()
        assertEquals(SpoolResult.Loaded("Workshop X1", "A2"), vm.state.value.result)
        assertEquals("Workshop X1 A2", vm.state.value.spool!!.location)
        assertNull("it is shown once", handle.get<String>(SpoolViewModel.RESULT_KEY))
    }

    @Test fun aResultTheLinkEndedWithIsThereFromTheStart() = runTest(dispatcher) {
        val vm = SpoolViewModel(214, backend, first, startResult = SpoolResult.TagLinked)
        assertEquals(SpoolResult.TagLinked, vm.state.value.result)
    }

    @Test fun theTopBarTitleIsTheSpoolsName() = runTest(dispatcher) {
        vm()
        advanceUntilIdle()
        assertNull(SpoolCache.title(214))
        SpoolCache.put(first)
        assertEquals("PolyTerra PLA Charcoal Black", SpoolCache.title(214))
    }

    @Test fun aRestoredSpoolWithNoAnswerShowsOnlyTheFailure() = runTest(dispatcher) {
        backend.failure = "spool" to ApiError(0, "offline", "gone")
        val vm = vm(initial = null)
        advanceUntilIdle()
        assertNull(vm.state.value.spool)
        assertFalse(vm.state.value.loading)
        assertEquals(HubFailure.Unreachable, vm.state.value.failure)
    }

    // ---- rotation, process death, Try again ----

    @Test fun aTypedWeightAndTheLeavingQuestionSurviveTheProcessBeingStopped() = runTest(dispatcher) {
        val handle = SavedStateHandle()
        backend.updateAnswer = { _, _, _, _ -> spoolJson(214, remaining = 482.0) }
        val vm = SpoolViewModel(214, backend, first, handle = handle)
        vm.openWeight()
        vm.setWeight("622")
        vm.askLeaveWeight()
        assertTrue(vm.state.value.weight!!.leaving)
        // a new process: a new view model over the saved state
        val again = SpoolViewModel(214, backend, first, handle = handle)
        assertEquals("622", again.state.value.weight!!.text)
        assertTrue(again.state.value.weight!!.leaving)
        advanceTimeBy(500)
        runCurrent()
        assertTrue("the preview is asked for again", again.state.value.weight!!.canSave)
        again.stayWeight()
        assertFalse(again.state.value.weight!!.leaving)
        assertFalse(SpoolViewModel(214, backend, first, handle = handle).state.value.weight!!.leaving)
    }

    @Test fun leavingDropsTheTextForGood() = runTest(dispatcher) {
        val handle = SavedStateHandle()
        val vm = SpoolViewModel(214, backend, first, handle = handle)
        vm.openWeight()
        vm.setWeight("622")
        vm.askLeaveWeight()
        vm.closeWeight()
        assertNull(vm.state.value.weight)
        assertNull(SpoolViewModel(214, backend, first, handle = handle).state.value.weight)
    }

    @Test fun backOnAnEmptySheetJustClosesItAndASaveInFlightIsWaitedFor() = runTest(dispatcher) {
        val vm = vm()
        vm.openWeight()
        vm.askLeaveWeight()
        assertNull(vm.state.value.weight)
        vm.openWeight()
        vm.setWeight("622")
        advanceTimeBy(500)
        runCurrent()
        vm.saveWeight()
        vm.askLeaveWeight()
        assertFalse("no question while it saves", vm.state.value.weight!!.leaving)
        advanceUntilIdle()
    }

    @Test fun tryAgainInTheWeightSheetRepeatsThePreviewOrTheSave() = runTest(dispatcher) {
        val vm = vm()
        vm.openWeight()
        backend.failure = "update" to ApiError(0, "offline", "gone")
        vm.setWeight("622")
        advanceTimeBy(500)
        runCurrent()
        assertEquals(HubFailure.Unreachable, vm.state.value.weight!!.failure)
        assertFalse(vm.state.value.weight!!.failedSave)
        vm.retryWeight()
        advanceTimeBy(500)
        runCurrent()
        assertTrue(vm.state.value.weight!!.canSave)
        backend.failure = "update" to ApiError(503, "spoolman_unreachable", "Spoolman is not reachable")
        vm.saveWeight()
        advanceUntilIdle()
        assertTrue(vm.state.value.weight!!.failedSave)
        vm.retryWeight()
        advanceUntilIdle()
        assertEquals(SpoolResult.WeightUpdated(620.0), vm.state.value.result)
        assertNull(vm.state.value.weight)
    }

    @Test fun tryAgainInTheMoveSheetReloadsTheListOrRepeatsTheMove() = runTest(dispatcher) {
        val vm = vm()
        backend.failure = "locations" to ApiError(0, "offline", "gone")
        vm.openMove()
        advanceUntilIdle()
        assertNull(vm.state.value.move!!.locations)
        vm.retryMove()
        advanceUntilIdle()
        assertEquals(3, vm.state.value.move!!.locations!!.size)
        backend.failure = "update" to ApiError(0, "offline", "gone")
        vm.move("Shelf B")
        advanceUntilIdle()
        assertEquals("Shelf B", vm.state.value.move!!.lastTry)
        vm.retryMove()
        advanceUntilIdle()
        assertEquals(SpoolResult.Moved("Shelf B"), vm.state.value.result)
    }

    @Test fun tryAgainRepeatsMarkEmptyAndTheUndo() = runTest(dispatcher) {
        backend.updateAnswer = { _, _, empty, _ -> spoolJson(214, archived = empty) }
        val vm = vm()
        backend.failure = "update" to ApiError(0, "offline", "gone")
        vm.askMarkEmpty()
        vm.confirmEmpty()
        advanceUntilIdle()
        assertEquals(Retry.MarkEmpty, vm.state.value.retry)
        vm.retry()
        advanceUntilIdle()
        assertEquals(SpoolResult.MarkedEmpty, vm.state.value.result)
        backend.failure = "update" to ApiError(0, "offline", "gone")
        vm.undoMove("Shelf B")
        advanceUntilIdle()
        assertEquals(Retry.UndoMove("Shelf B"), vm.state.value.retry)
    }
}
