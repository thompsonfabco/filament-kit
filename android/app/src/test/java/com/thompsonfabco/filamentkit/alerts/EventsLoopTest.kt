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
    private class MemoryCursor(var id: Long? = null, var hub: String? = "hub-a", var dismissed: Set<String> = emptySet()) : CursorStore {
        override suspend fun lastSeen() = id
        override suspend fun setLastSeen(id: Long) {
            this.id = id
        }
        override suspend fun useHub(fingerprint: String) {
            if (hub != fingerprint) {
                hub = fingerprint
                id = null
                dismissed = emptySet()
            }
        }
        override suspend fun restart(next: Long) {
            id = next
            dismissed = emptySet()
        }
    }

    private val start = AlertParsing.parseTime("2026-11-17T12:00:00Z")!!
    private var clock = start
    private val sleeps = mutableListOf<Long>()
    private val delivered = mutableListOf<List<NotifyAction>>()
    private val queries = mutableListOf<EventsQuery>()

    private fun answer(text: String) = AlertParsing.events(Json.parseToJsonElement(text))

    /** Runs the loop over [steps] (an answer or a failure each); after the last one the loop is cancelled. */
    private fun run(cursor: MemoryCursor, vararg steps: Any, waitS: Int = 55, hub: String = "hub-a"): LoopEnd? {
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
            hub = hub,
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
        assertTrue("the loop reads clearing events too", queries.none { it.alertOnly })
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

    @Test fun aFilamentRanOutNotificationIsCancelledAfterThePrintResumed() {
        // a Hub fake that applies the contract: alert=1 returns only events of alert types that are on
        val stream = listOf(
            1L to """{"id":1,"kind":"spool.empty","severity":"bad","alert":true,"title":"Filament ran out","condition":{"key":"spool-empty","state":"raised"}}""",
            2L to """{"id":2,"kind":"print.resumed","severity":"info","alert":false,"condition":{"key":"spool-empty","state":"cleared"}}""",
        )
        val alertTypes = setOf(1L)
        var calls = 0
        val loop = EventsLoop(
            fetch = { q ->
                queries += q
                calls++
                if (calls > 3) throw CancellationException("done")
                val existing = stream.take(calls) // the Hub learns one more event before each ask
                val rows = existing.filter { (id, _) -> id > (q.since ?: 0) && (!q.alertOnly || id in alertTypes) }
                answer("""{"events":[${rows.joinToString(",") { it.second }}],"next":${existing.last().first}}""")
            },
            cursor = MemoryCursor(), hub = "hub-a", deliver = { delivered += it },
            clock = { clock }, sleep = { sleeps += it; clock += it },
        )
        try { runBlocking { loop.run() } } catch (_: CancellationException) {}
        val all = delivered.flatten()
        assertTrue(all.first() is NotifyAction.Show)
        assertEquals("alert:spool-empty", (all.first() as NotifyAction.Show).tag)
        assertEquals("the clearing event reaches the Cancel branch", NotifyAction.Cancel("alert:spool-empty"), all.last())
    }

    @Test fun aNewFingerprintForgetsTheCursorAndStartsFromNow() {
        val cursor = MemoryCursor(id = 500, hub = "hub-a", dismissed = setOf("x"))
        run(cursor, answer("""{"events":[],"next":3}"""), hub = "hub-b")
        assertNull(queries[0].since)
        assertEquals("2026-11-17T12:00:00Z", queries[0].sinceAt)
        assertEquals("hub-b", cursor.hub)
        assertTrue(cursor.dismissed.isEmpty())
    }

    @Test fun theSameHubKeepsItsCursorAndDismissals() {
        val cursor = MemoryCursor(id = 500, hub = "hub-a", dismissed = setOf("x"))
        run(cursor, answer("""{"events":[],"next":500}"""), hub = "hub-a")
        assertEquals(500L, queries[0].since)
        assertEquals(setOf("x"), cursor.dismissed)
    }

    @Test fun aLowerNextIsANewStoreAndOlderIdsStayQuiet() {
        val cursor = MemoryCursor(id = 500, dismissed = setOf("x"))
        run(
            cursor,
            answer("""{"events":[{"id":2,"alert":true,"severity":"bad","title":"old"}],"next":3}"""),
            answer("""{"events":[],"next":3}"""),
        )
        assertEquals(3L, cursor.id)
        assertEquals(3L, queries[1].since)
        assertTrue(cursor.dismissed.isEmpty())
        assertTrue("nothing shown for the new store's old ids", delivered.isEmpty())
    }
}
