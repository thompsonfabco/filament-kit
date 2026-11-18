package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.net.ActivityEvent
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.LoadResult
import com.thompsonfabco.filamentkit.net.LoadSlot
import com.thompsonfabco.filamentkit.net.UndoAnswer
import com.thompsonfabco.filamentkit.net.UndoState
import com.thompsonfabco.filamentkit.ui.history.HistoryTexts
import com.thompsonfabco.filamentkit.ui.history.UndoFlow
import com.thompsonfabco.filamentkit.ui.history.UndoOutcome
import com.thompsonfabco.filamentkit.ui.spool.SpoolSummary
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The Undo toast of a load started from a printer slot (R84 3.3, 9.1). */
@OptIn(ExperimentalCoroutinesApi::class)
class PickSpoolUndoTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    private val now = 1_000_000L

    private class Fake : PickBackend {
        var events: List<ActivityEvent> = emptyList()
        var activityError: Exception? = null
        val asked = mutableListOf<String>()
        val undone = mutableListOf<Long>()
        var undoError: Exception? = null
        override suspend fun search(query: String, sealedOnly: Boolean): List<JsonObject> = emptyList()
        override suspend fun tag(uid: String): JsonObject? = null
        override suspend fun load(printerId: String, label: String, spoolId: Int, dryRun: Boolean) =
            LoadResult(slot = LoadSlot(label, 0, 0), confirmed = !dryRun)
        override suspend fun activity(subject: String, limit: Int): List<ActivityEvent> {
            asked += "$subject:$limit"
            activityError?.let { throw it }
            return events
        }
        override suspend fun undoEvent(id: Long): UndoAnswer {
            undone += id
            undoError?.let { throw it }
            return UndoAnswer(true, id + 1, "The printer still shows what it was set to.")
        }
    }

    private val fake = Fake()
    private fun vm() = PickSpoolViewModel(fake, "ABC123", "A4", undoFlow = UndoFlow(fake) { now })
    private fun spool(id: Int) = SpoolSummary(id, "Example", "PolyTerra $id", "PLA", "2B2B2E", null, 620.0)
    private fun event(id: Long, kind: String, possible: Boolean = true) =
        ActivityEvent(id, "", now - 1_000, kind, "Pixel", "", "spool:7", UndoState(possible, null, null), false, null)

    private fun PickSpoolViewModel.loadSpool(id: Int) {
        pick(spool(id)); dispatcher.scheduler.runCurrent()
        confirm(); dispatcher.scheduler.runCurrent()
    }

    @Test fun aLoadTheHubCanUndoCarriesItsEventToTheScreen() = runTest(dispatcher) {
        fake.events = listOf(event(5, "spool.weighed"), event(9, "spool.loaded"))
        val v = vm()
        v.loadSpool(7)
        assertEquals(listOf("spool:7:3"), fake.asked)
        assertEquals(true, v.state.value.loaded)
        assertEquals(9L, v.state.value.loadedEvent!!.id)
    }

    @Test fun noEventNoUndoAndTheLoadStillReports() = runTest(dispatcher) {
        fake.events = listOf(event(9, "spool.weighed"))
        val v = vm()
        v.loadSpool(7)
        assertEquals(true, v.state.value.loaded)
        assertNull(v.state.value.loadedEvent)
    }

    @Test fun anEventTheHubDoesNotOfferToUndoGivesNoUndo() = runTest(dispatcher) {
        fake.events = listOf(event(9, "spool.loaded", possible = false))
        val v = vm()
        v.loadSpool(7)
        assertNull(v.state.value.loadedEvent)
    }

    @Test fun anOlderHubOrAFailedReadStillReportsTheLoad() = runTest(dispatcher) {
        fake.activityError = ApiError(404, "not_found", "The Hub returned an error (404)")
        val v = vm()
        v.loadSpool(7)
        assertEquals(true, v.state.value.loaded)
        assertNull(v.state.value.loadedEvent)
    }

    @Test fun theEventIsNotLookedForWhenTheLoadFailed() = runTest(dispatcher) {
        val failing = object : PickBackend by fake {
            override suspend fun load(printerId: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult {
                if (!dryRun) throw ApiError(500, "internal", "boom")
                return fake.load(printerId, label, spoolId, dryRun)
            }
        }
        val v = PickSpoolViewModel(failing, "ABC123", "A4", undoFlow = UndoFlow(failing) { now })
        v.loadSpool(7)
        assertTrue(fake.asked.isEmpty())
        assertNull(v.state.value.loaded)
    }

    @Test fun undoingAnswersWithThePutBackNoteAndSurvivesTheScreen() = runTest(dispatcher) {
        fake.events = listOf(event(9, "spool.loaded"))
        val v = vm()
        v.loadSpool(7)
        val e = v.state.value.loadedEvent!!
        v.loadedShown()
        assertNull(v.state.value.loadedEvent)
        val outcome = v.undoLoad(e)
        assertEquals(listOf(9L), fake.undone)
        assertEquals(UndoOutcome.Done("Put back. The printer still shows what it was set to."), outcome)
    }

    @Test fun aRefusedUndoSaysWhy() = runTest(dispatcher) {
        fake.events = listOf(event(9, "spool.loaded"))
        val v = vm()
        v.loadSpool(7)
        fake.undoError = ApiError(409, "changed_since", "x")
        val outcome = v.undoLoad(v.state.value.loadedEvent!!)
        assertEquals(UndoOutcome.Refused(HistoryTexts.UNDO_CHANGED_SINCE), outcome)
    }
}
