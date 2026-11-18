package com.thompsonfabco.filamentkit.alerts

import com.thompsonfabco.filamentkit.net.ApiError
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay

/** Where the watching loop keeps the last event it has seen, so a restart goes on from there. */
interface CursorStore {
    suspend fun lastSeen(): Long?
    suspend fun setLastSeen(id: Long)

    /** The cursor belongs to one Hub: with another [fingerprint] than the stored one, the cursor and the dismissed banners are forgotten. */
    suspend fun useHub(fingerprint: String)

    /** The Hub's store started again (its ids went down): the cursor becomes [next] and the dismissed banners are forgotten. */
    suspend fun restart(next: Long)
}

/** Why [EventsLoop.run] ended (it never ends by itself otherwise; cancelling it throws). */
enum class LoopEnd {
    /** The Hub refused the token (401): the pairing is gone. */
    Revoked,
}

/**
 * The watching loop: one waiting `GET api/events?since=<cursor>&wait=55` (no `alert` filter) after another, from the last event seen (the first
 * time ever: from the time watching began, so no old alerts flood in). [fetch] asks the Hub, [deliver] shows the
 * notifications, [sleep] and [clock] are injected for tests. Offline and other failures wait with [Backoff]; a Hub that
 * has no events route (404, an older Hub) is asked again only every [UNAVAILABLE_WAIT_MS].
 */
class EventsLoop(
    private val fetch: suspend (EventsQuery) -> EventsAnswer,
    private val cursor: CursorStore,
    private val hub: String,
    private val deliver: suspend (List<NotifyAction>) -> Unit,
    private val clock: () -> Long = System::currentTimeMillis,
    private val sleep: suspend (Long) -> Unit = { delay(it) },
    private val backoff: Backoff = Backoff(),
    private val waitS: Int = WAIT_S,
) {
    /** Runs until the token is refused; cancel the coroutine to stop it. */
    suspend fun run(): LoopEnd {
        val startedAt = clock()
        cursor.useHub(hub)
        var since = cursor.lastSeen()
        while (true) {
            val asked = clock()
            val answer = try {
                fetch(nextQuery(since, startedAt, waitS))
            } catch (e: CancellationException) {
                throw e
            } catch (e: ApiError) {
                if (e.status == 401) return LoopEnd.Revoked
                sleep(if (e.status == 404) UNAVAILABLE_WAIT_MS else backoff.next())
                continue
            } catch (_: Exception) {
                sleep(backoff.next())
                continue
            }
            backoff.reset()
            if (isNewStore(since, answer)) {
                // a new or restored Hub store: its ids start again; older ids are not news, so only a test is shown
                since = answer.next
                cursor.restart(answer.next!!)
                val test = notifyActions(answer.copy(events = emptyList()), clock())
                if (test.isNotEmpty()) deliver(test)
                continue
            }
            val actions = notifyActions(answer, clock())
            if (actions.isNotEmpty()) deliver(actions)
            val after = advance(since, answer)
            if (after != null && after != since) {
                since = after
                cursor.setLastSeen(after)
            }
            // a Hub that answers at once with nothing is not waited on: do not spin
            if (answer.events.isEmpty() && clock() - asked < MIN_ROUND_MS) sleep(MIN_ROUND_MS)
        }
    }

    companion object {
        /** The longest the Hub waits (R80 E4: at most 55 s). */
        const val WAIT_S = 55
        const val UNAVAILABLE_WAIT_MS = 5 * 60_000L
        const val MIN_ROUND_MS = 1_000L

        /** The read timeout of the waiting call: longer than the wait. */
        const val READ_TIMEOUT_S = 65L
    }
}
