package com.thompsonfabco.filamentkit.alerts

import com.thompsonfabco.filamentkit.net.ApiError
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class EventsLoopTest {
    private class MemoryCursor(var id: Long? = null) : CursorStore {
        override suspend fun lastSeen() = id
        override suspend fun setLastSeen(id: Long) {
            this.id = id
        }
    }

    private val start = AlertParsing.parseTime("2026-11-17T12:00:00Z")!!
    private var clock = start
    private val sleeps = mutableListOf<Long>()
    private val delivered = mutableListOf<List<NotifyAction>>()
    private val queries = mutableListOf<EventsQuery>()

    private fun answer(text: String) = AlertParsing.events(Json.parseToJsonElement(text))

    /** Runs the loop over [steps] (an answer or a failure each); after the last one the loop is cancelled. */
    private fun run(cursor: MemoryCursor, vararg steps: Any, waitS: Int = 55): LoopEnd? {
        val queue = ArrayDeque(steps.toList())
        val loop = EventsLoop(
            fetch = { q ->
                queries += q
                when (val step = if (queue.isEmpty()) throw CancellationException("done") else queue.removeFirst()) {
                    is EventsAnswer -> step
                    is Throwable -> throw step
                    else -> error("bad step")
                }
            },
            cursor = cursor,
            deliver = { delivered += it },
            clock = { clock },
            sleep = { sleeps += it; clock += it },
            waitS = waitS,
        )
        return try {
            runBlocking { loop.run() }
        } catch (_: CancellationException) {
            null
        }
    }

    @Test fun theFirstRunStartsFromNowAndLaterRunsFollowTheCursorWhichIsKept() {
        val cursor = MemoryCursor()
        run(
            cursor,
            answer("""{"events":[],"next":7}"""),
            answer(SAMPLE_EVENTS),
            answer("""{"events":[],"next":14}"""),
        )
        assertNull(queries[0].since)
        assertEquals("2026-11-17T12:00:00Z", queries[0].sinceAt)
        assertEquals(7L, queries[1].since)
        assertNull(queries[1].sinceAt)
        assertEquals(14L, queries[2].since)
        assertEquals(14L, cursor.id)
        assertEquals(55, queries[0].waitS)
        assertTrue(queries.all { it.alertOnly })
    }

    @Test fun aRestartContinuesFromTheStoredCursor() {
        val cursor = MemoryCursor(41)
        run(cursor, answer("""{"events":[],"next":41}"""))
        assertEquals(41L, queries[0].since)
        assertNull(queries[0].sinceAt)
    }

    @Test fun theNotificationsOfAnAnswerAreDeliveredOnce() {
        run(MemoryCursor(), answer(SAMPLE_EVENTS))
        assertEquals(1, delivered.size)
        val tags = delivered[0].map { it::class.simpleName to ((it as? NotifyAction.Show)?.tag ?: (it as? NotifyAction.Cancel)?.tag) }
        assertEquals(
            listOf(
                "Show" to "alert:print-paused:p-3", "Show" to "alert:event:13", "Cancel" to "alert:print-paused:p-3",
            ),
            tags,
        )
    }

    @Test fun aTestInTheAnswerIsDelivered() {
        run(MemoryCursor(), answer("""{"events":[],"next":1,"test":{"title":"Test alert","text":"It works."}}"""))
        assertEquals(listOf<List<NotifyAction>>(listOf(NotifyAction.ShowTest(AlertTest("Test alert", "It works.")))), delivered)
    }

    @Test fun aGapIsToleratedAndTheLoopGoesOn() {
        val cursor = MemoryCursor(5)
        run(cursor, answer("""{"events":[],"next":90,"oldest":80,"gap":true}"""), answer("""{"events":[],"next":90}"""))
        assertEquals(90L, queries[1].since)
        assertEquals(90L, cursor.id)
    }

    @Test fun offlineWaitsWithBackoffAndAGoodAnswerStartsTheBackoffAgain() {
        run(
            MemoryCursor(1),
            ApiError(0, "offline", "no"), ApiError(0, "offline", "no"), IOException("down"),
            answer("""{"events":[{"id":2}],"next":2}"""),
            ApiError(500, "internal", "boom"),
        )
        assertEquals(listOf(2_000L, 4_000L, 8_000L, 2_000L), sleeps)
        assertEquals("the failed asks are asked again from the same cursor", listOf<Long?>(1, 1, 1, 1, 2, 2), queries.map { it.since })
    }

    @Test fun anAnswerThatComesAtOnceWithNothingIsNotSpunOn() {
        run(MemoryCursor(1), answer("""{"events":[],"next":1}"""), answer("""{"events":[],"next":1}"""))
        assertEquals(listOf(1_000L, 1_000L), sleeps)
    }

    @Test fun aHubWithoutTheRouteIsAskedAgainOnlyEveryFiveMinutes() {
        run(MemoryCursor(), ApiError(404, "not_found", "no"), ApiError(404, "not_found", "no"))
        assertEquals(listOf(300_000L, 300_000L), sleeps)
    }

    @Test fun aRefusedTokenEndsTheLoop() {
        val end = run(MemoryCursor(), ApiError(401, "unauthorized", "no"), answer("""{"events":[]}"""))
        assertEquals(LoopEnd.Revoked, end)
        assertEquals(1, queries.size)
    }
}
