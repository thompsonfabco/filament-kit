package com.thompsonfabco.filamentkit.ui.history

import com.thompsonfabco.filamentkit.net.ActivityEvent
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.UndoAnswer
import com.thompsonfabco.filamentkit.net.UndoState
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The undo toast's rules (R84 3.3 to 3.5): which event, how long, and what each answer says. */
class UndoFlowTest {
    private val now = 1_800_000_000_000L

    private fun event(id: Long, kind: String, ageMs: Long = 1_000, possible: Boolean = true, undone: Boolean = false, subject: String = "spool:212") =
        ActivityEvent(id, "", now - ageMs, kind, "Pixel", "", subject, UndoState(possible, null, null), undone, null)

    private class Fake(var events: List<ActivityEvent> = emptyList()) : ActivityBackend {
        val asked = mutableListOf<String>()
        var undoAnswer: () -> UndoAnswer = { UndoAnswer(true, 9, null) }
        override suspend fun activity(subject: String, limit: Int): List<ActivityEvent> {
            asked += "$subject:$limit"
            return events.filter { it.subject == subject }
        }
        override suspend fun undoEvent(id: Long): UndoAnswer = undoAnswer()
    }

    private fun refusal(code: String, text: String?) = ApiError(
        409, code, "x", JsonObject(if (text == null) emptyMap() else mapOf("text" to JsonPrimitive(text))),
    )

    @Test fun theToastIsHeldTenSecondsOrWhatAccessibilityRecommendsIfLonger() {
        assertEquals(10_000L, UndoRules.holdMs(10_000))
        assertEquals(10_000L, UndoRules.holdMs(4_000))
        assertEquals(40_000L, UndoRules.holdMs(40_000))
    }

    @Test fun theNewestEventOfTheRightKindThatCanBeUndoneIsPicked() {
        val older = event(5, UndoKinds.MOVED)
        val newest = event(8, UndoKinds.MOVED)
        assertEquals(8L, UndoRules.pick(listOf(older, newest), setOf(UndoKinds.MOVED), now)!!.id)
        assertEquals(8L, UndoRules.pick(listOf(newest, older), setOf(UndoKinds.MOVED), now)!!.id)
    }

    @Test fun anEventThatIsNotTheActionsIsNeverPickedEvenIfAnOlderOneCouldBeUndone() {
        val older = event(5, UndoKinds.MOVED)
        val newest = event(8, UndoKinds.WEIGHED, possible = false)
        assertNull(UndoRules.pick(listOf(older, newest), setOf(UndoKinds.MOVED), now))
        assertNull("another kind", UndoRules.pick(listOf(event(8, UndoKinds.WEIGHED)), setOf(UndoKinds.MOVED), now))
        assertNull("the Hub offers no undo", UndoRules.pick(listOf(event(8, UndoKinds.MOVED, possible = false)), setOf(UndoKinds.MOVED), now))
        assertNull("already undone", UndoRules.pick(listOf(event(8, UndoKinds.MOVED, undone = true)), setOf(UndoKinds.MOVED), now))
        assertNull("too old to be the action just made", UndoRules.pick(listOf(event(8, UndoKinds.MOVED, ageMs = 600_000)), setOf(UndoKinds.MOVED), now))
        assertNull(UndoRules.pick(emptyList(), setOf(UndoKinds.MOVED), now))
    }

    @Test fun anEventWithoutATimeIsStillPicked() {
        val e = event(8, UndoKinds.MOVED).copy(atMillis = null)
        assertEquals(8L, UndoRules.pick(listOf(e), setOf(UndoKinds.MOVED), now)!!.id)
    }

    @Test fun findReadsTheSubjectsNewestEventsAndAFailedReadOffersNoUndo() = runBlocking {
        val hub = Fake(listOf(event(8, UndoKinds.MOVED), event(9, UndoKinds.MOVED, subject = "spool:99")))
        val flow = UndoFlow(hub) { now }
        val found = flow.find(UndoOffer(listOf("spool:212"), setOf(UndoKinds.MOVED)))
        assertEquals(8L, found!!.id)
        assertEquals(listOf("spool:212:3"), hub.asked)
        val broken = object : ActivityBackend {
            override suspend fun activity(subject: String, limit: Int): List<ActivityEvent> = throw ApiError(0, "offline", "no")
        }
        assertNull(UndoFlow(broken) { now }.find(UndoOffer(listOf("spool:212"), setOf(UndoKinds.MOVED))))
        // an older Hub: the default backend has no events
        assertNull(UndoFlow(object : ActivityBackend {}) { now }.find(UndoOffer(listOf("spool:212"), setOf(UndoKinds.MOVED))))
    }

    @Test fun undoSaysPutBackAndAddsTheHubsNoteForALoad() = runBlocking {
        val hub = Fake()
        val flow = UndoFlow(hub) { now }
        assertEquals(UndoOutcome.Done("Put back."), flow.undo(event(8, UndoKinds.MOVED)))
        hub.undoAnswer = { UndoAnswer(true, 9, "The printer still shows what it was set to.") }
        assertEquals(
            UndoOutcome.Done("Put back. The printer still shows what it was set to."),
            flow.undo(event(8, UndoKinds.LOADED)),
        )
    }

    @Test fun aRefusalShowsTheHubsTextElseOurWordsForItsReason() = runBlocking {
        val hub = Fake()
        val flow = UndoFlow(hub) { now }
        hub.undoAnswer = { throw refusal("changed_since", "The Hub's own sentence.") }
        assertEquals(UndoOutcome.Refused("The Hub's own sentence."), flow.undo(event(8, UndoKinds.MOVED)))
        hub.undoAnswer = { throw refusal("changed_since", null) }
        assertEquals("This changed again since, so it cannot be undone.", flow.undo(event(8, UndoKinds.MOVED)).text)
        hub.undoAnswer = { throw refusal("too_old", null) }
        assertEquals(HistoryTexts.UNDO_TOO_OLD, flow.undo(event(8, UndoKinds.MOVED)).text)
        hub.undoAnswer = { throw refusal("already_undone", null) }
        assertEquals(HistoryTexts.UNDO_ALREADY_UNDONE, flow.undo(event(8, UndoKinds.MOVED)).text)
        hub.undoAnswer = { throw refusal("not_undoable", null) }
        assertEquals(HistoryTexts.UNDO_NOT_UNDOABLE, flow.undo(event(8, UndoKinds.MOVED)).text)
        assertTrue(flow.undo(event(8, UndoKinds.MOVED)) is UndoOutcome.Refused)
    }

    @Test fun anOlderHubAndAnUnreachableHubHaveTheirOwnWords() = runBlocking {
        val hub = Fake()
        val flow = UndoFlow(hub) { now }
        hub.undoAnswer = { throw ApiError(404, "not_found", "The Hub returned an error (404)") }
        assertEquals(HistoryTexts.UNDO_UPDATE_HUB, flow.undo(event(8, UndoKinds.MOVED)).text)
        hub.undoAnswer = { throw ApiError(0, "offline", "Could not reach the Hub") }
        assertEquals(HistoryTexts.UNDO_FAILED, flow.undo(event(8, UndoKinds.MOVED)).text)
        hub.undoAnswer = { throw ApiError(500, "internal", "The Hub returned an error (500)") }
        assertEquals(HistoryTexts.UNDO_FAILED, flow.undo(event(8, UndoKinds.MOVED)).text)
    }
}
