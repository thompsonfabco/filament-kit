package com.thompsonfabco.filamentkit.alerts

import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** What the banner, the Alerts list, the Home line and the Spools chip read while the app is open. */
data class AlertsUi(
    /** False once the Hub answered that it has no alerts (404, an older Hub); the screens then say so. */
    val available: Boolean = true,
    val loaded: Boolean = false,
    /** The raised conditions of the last answer. */
    val conditions: List<AlertEvent> = emptyList(),
    /** The alert events of the last answer ([days] days back). */
    val events: List<AlertEvent> = emptyList(),
    val days: Int = BANNER_DAYS,
    val dismissed: Map<String, Dismissed> = emptyMap(),
    /** How many spools are running low; null while unknown or when the Hub cannot say. */
    val lowCount: Int? = null,
    val loadedAt: Long? = null,
) {
    companion object {
        const val BANNER_DAYS = 1
        const val LIST_DAYS = 7
    }
}

/**
 * The app's own reading of the events while it is open (R80 section 4: "one request style for all"): the same
 * `GET api/events?alert=1`, with `wait=0` and `since_at` a day back for the banners, seven days back for the list.
 * It shows nothing as an Android notification except the test alert the Hub hands out ([onTest]); alerts are
 * the watching service's. [api] is asked at each call, so a re-pair needs no new feed.
 */
class AlertsFeed(
    private val scope: CoroutineScope,
    private val api: () -> Api?,
    private val store: AlertsStore? = null,
    private val clock: () -> Long = System::currentTimeMillis,
    private val onTest: (AlertTest) -> Unit = {},
    /** The fingerprint of the paired Hub (null while none): the stored cursor and dismissals belong to one Hub, switch on or off. */
    hub: Flow<String?> = emptyFlow(),
) {
    private val _state = MutableStateFlow(AlertsUi())
    val state: StateFlow<AlertsUi> = _state.asStateFlow()

    init {
        store?.let { s ->
            scope.launch { hub.filterNotNull().distinctUntilChanged().collect { s.useHub(it) } }
            scope.launch { s.dismissed.collect { d -> _state.update { it.copy(dismissed = d) } } }
        }
    }

    /** Reads the last [days] days. Failures other than "no such route" leave the last answer on screen. */
    suspend fun refresh(days: Int) {
        val a = api() ?: return
        val since = AlertParsing.formatTime(clock() - days * DAY_MS)
        try {
            val answer = a.events(EventsQuery(since = null, sinceAt = since, waitS = 0, alertOnly = true, limit = LIMIT))
            answer.test?.let(onTest)
            _state.update {
                it.copy(
                    available = true, loaded = true, conditions = answer.conditions, events = answer.events,
                    days = days, loadedAt = clock(),
                )
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: ApiError) {
            if (e.status == 404) _state.update { it.copy(available = false, loaded = true, conditions = emptyList(), events = emptyList()) }
        } catch (_: Exception) {
            // offline or unreadable: the last answer stays
        }
    }

    /** The running-low count (`GET api/spools/low`); null when the Hub has no such route. */
    suspend fun refreshLow() {
        val a = api() ?: return
        try {
            val low = a.lowSpools()
            _state.update { it.copy(lowCount = low.spools.size) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: ApiError) {
            if (e.status == 404) _state.update { it.copy(lowCount = null) }
        } catch (_: Exception) {
        }
    }

    /** Hides [item] on this phone; it comes back when it is worse or raised again ([isDismissed]). */
    fun dismiss(item: AlertItem) {
        val entry = Dismissed(item.severity, item.event.id)
        _state.update { it.copy(dismissed = it.dismissed + (item.key to entry)) }
        store?.let { s -> scope.launch { s.dismiss(item.key, item.severity, item.event.id) } }
    }

    /** Another Hub, or none: nothing of the old one stays. */
    fun clear() {
        _state.update { AlertsUi(dismissed = it.dismissed) }
    }

    private companion object {
        const val DAY_MS = 24 * 3_600_000L
        const val LIMIT = 200
    }
}
