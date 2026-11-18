package com.thompsonfabco.filamentkit.ui.spool

import com.thompsonfabco.filamentkit.net.ActivityEvent
import com.thompsonfabco.filamentkit.net.UndoAnswer
import com.thompsonfabco.filamentkit.net.UndoState
import com.thompsonfabco.filamentkit.ui.history.UndoKinds
import com.thompsonfabco.filamentkit.ui.history.UndoOutcome
import com.thompsonfabco.filamentkit.ui.history.undoOfferFor
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

/** The spool screen's Undo toast (R84 3.3): which actions offer it, what it looks for, and what Undo does. */
@OptIn(ExperimentalCoroutinesApi::class)
class SpoolUndoOfferTest {
    private val dispatcher = StandardTestDispatcher()
    private val first = spoolJson(214).toSpoolSummary()
    private val now = 1_800_000_000_000L

    /** The usual fake for the spool calls, with the Hub's activity and undo added. */
    private class UndoBackend(val fake: FakeSpoolBackend = FakeSpoolBackend()) : SpoolBackend by fake {
        var events: List<ActivityEvent> = emptyList()
        val undone = mutableListOf<Long>()
        override suspend fun activity(subject: String, limit: Int) = events.filter { it.subject == subject }
        override suspend fun undoEvent(id: Long): UndoAnswer {
            undone += id
            return UndoAnswer(true, id + 1, null)
        }
    }

    private val backend = UndoBackend()

    @Before fun setUp() {
        Dispatchers.setMain(dispatcher)
        SpoolCache.clear()
    }

    @After fun tearDown() = Dispatchers.resetMain()

    private fun vm(start: SpoolResult? = null) = SpoolViewModel(214, backend, first, null, start, now = { now })

    private fun event(id: Long, kind: String) =
        ActivityEvent(id, "", now - 500, kind, "Pixel", "", "spool:214", UndoState(true, null, null), false, null)

    @Test fun savingAWeightOffersUndoForAWeighedEvent() = runTest(dispatcher) {
        backend.fake.updateAnswer = { gross, _, _, _ -> spoolJson(214, remaining = (gross ?: 0.0) - 140) }
        val vm = vm()
        vm.openWeight()
        vm.setWeight("622")
        advanceUntilIdle()
        vm.saveWeight()
        advanceUntilIdle()
        val offer = vm.state.value.undoOffer!!
        assertEquals(listOf("spool:214"), offer.subjects)
        assertEquals(setOf(UndoKinds.WEIGHED), offer.kinds)
    }

    @Test fun movingMarkingEmptyAndALoadResultOfferUndoOfTheirKinds() = runTest(dispatcher) {
        backend.fake.updateAnswer = { _, location, _, _ -> spoolJson(214, location = location) }
        val vm = vm()
        vm.openMove()
        advanceUntilIdle()
        vm.move("Shelf B")
        advanceUntilIdle()
        assertEquals(setOf(UndoKinds.MOVED), vm.state.value.undoOffer!!.kinds)
        vm.offerShown()
        assertNull(vm.state.value.undoOffer)
        vm.confirmEmpty()
        advanceUntilIdle()
        assertEquals(setOf(UndoKinds.EMPTIED), vm.state.value.undoOffer!!.kinds)

        val loaded = vm(SpoolResult.Loaded("Workshop X1", "A1"))
        assertEquals(setOf(UndoKinds.LOADED), loaded.state.value.undoOffer!!.kinds)
        assertNotNull(vm(SpoolResult.TagLinked).state.value.undoOffer)
    }

    @Test fun undoingAMoveWithTheScreensOwnUndoOffersNoSecondUndo() = runTest(dispatcher) {
        backend.fake.updateAnswer = { _, location, _, _ -> spoolJson(214, location = location) }
        val vm = vm()
        vm.undoMove("Shelf B")
        advanceUntilIdle()
        assertNull(vm.state.value.undoOffer)
    }

    @Test fun twoOffersOfTheSameActionAreNotEqualSoTheSecondToastShows() {
        assertNotEquals(undoOfferFor(214, SpoolResult.MarkedEmpty, 1), undoOfferFor(214, SpoolResult.MarkedEmpty, 2))
    }

    @Test fun undoOnTheHubClearsTheResultLineAndReadsTheSpoolAgain() = runTest(dispatcher) {
        backend.fake.spools = listOf(spoolJson(214))
        val vm = vm(SpoolResult.MarkedEmpty)
        assertNull("no event on the Hub yet", vm.findUndo(vm.state.value.undoOffer!!))
        backend.events = listOf(event(31, UndoKinds.EMPTIED))
        val e = vm.findUndo(vm.state.value.undoOffer!!)!!
        assertEquals(31L, e.id)
        assertEquals(UndoOutcome.Done("Put back."), vm.undoOnHub(e))
        advanceUntilIdle()
        assertEquals(listOf(31L), backend.undone)
        assertNull(vm.state.value.result)
    }
}
