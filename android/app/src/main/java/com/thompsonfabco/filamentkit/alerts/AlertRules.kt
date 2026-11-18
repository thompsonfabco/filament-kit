package com.thompsonfabco.filamentkit.alerts

// The rules of the alerts feature as plain functions, so they run in JVM tests: which events notify, which banners
// show, where an action goes, whether the switch may turn on, whether the watching service must be started.

private const val HOUR_MS = 3_600_000L

/** A notification older than this is not worth showing (the phone was off, or the Hub unreachable, for a long time). */
const val NOTIFY_MAX_AGE_MS = 24 * HOUR_MS

/** The banners show moments (an event without a condition) for at most this long (R80 section 5). */
const val MOMENT_BANNER_MS = 24 * HOUR_MS

/** At most this many banners at once; the rest become "<n> more alerts". */
const val BANNERS_SHOWN = 2

/** What the watching service does for the events of one answer. */
sealed interface NotifyAction {
    /** One Android notification, replacing any earlier one with the same [tag]. */
    data class Show(val tag: String, val event: AlertEvent) : NotifyAction

    /** A condition cleared: its notification goes. */
    data class Cancel(val tag: String) : NotifyAction

    data class ShowTest(val test: AlertTest) : NotifyAction
}

internal fun notificationTag(event: AlertEvent): String = "alert:${event.key}"

/**
 * Which events of [answer] notify: one notification per event with `alert` true (a condition raised notifies once,
 * when it is raised); a cleared condition removes its notification and sends nothing; a `test` shows one. Events older
 * than [NOTIFY_MAX_AGE_MS] are left out. Only the events are read, never `conditions` (what is raised now is for banners).
 */
fun notifyActions(answer: EventsAnswer, nowMillis: Long): List<NotifyAction> {
    val out = mutableListOf<NotifyAction>()
    for (e in answer.events) {
        val clearedKey = when {
            e.condition != null && !e.condition.raised -> e.condition.key
            e.kind == "condition.cleared" -> (e.data["key"] as? kotlinx.serialization.json.JsonPrimitive)?.content
            else -> null
        }
        if (clearedKey != null) {
            out += NotifyAction.Cancel("alert:$clearedKey")
            continue
        }
        if (!e.alert) continue
        if (e.atMillis != null && nowMillis - e.atMillis > NOTIFY_MAX_AGE_MS) continue
        out += NotifyAction.Show(notificationTag(e), e)
    }
    answer.test?.let { out += NotifyAction.ShowTest(it) }
    return out
}

/** What the watching service asks first and next: the stored cursor `since`, else the time it started watching. */
internal fun nextQuery(since: Long?, startedAtMillis: Long, waitS: Int): EventsQuery =
    if (since != null) EventsQuery(since = since, sinceAt = null, waitS = waitS)
    else EventsQuery(since = null, sinceAt = AlertParsing.formatTime(startedAtMillis), waitS = waitS)

/** The cursor after [answer]: its `next`, else the highest id it carried, else the one we had. A `gap` changes nothing. */
internal fun advance(since: Long?, answer: EventsAnswer): Long? {
    val seen = maxOf(answer.next ?: Long.MIN_VALUE, answer.events.maxOfOrNull { it.id } ?: Long.MIN_VALUE)
    return if (seen == Long.MIN_VALUE) since else maxOf(seen, since ?: Long.MIN_VALUE)
}

/** Waits between tries while the Hub cannot be reached: doubles from [baseMs] up to [capMs], and starts again after a good answer. */
class Backoff(private val baseMs: Long = 2_000, private val capMs: Long = 60_000) {
    private var current = 0L

    fun next(): Long {
        current = if (current == 0L) baseMs else minOf(current * 2, capMs)
        return current
    }

    fun reset() {
        current = 0L
    }
}

// ---- banners ----

/** What the banner and the Alerts list show for one event or condition. */
data class AlertItem(val event: AlertEvent) {
    val key: String get() = event.key
    val severity: AlertSeverity get() = event.severity
}

/** What a person dismissed on this phone: the key and how bad and which event it was then. */
data class Dismissed(val severity: AlertSeverity, val eventId: Long)

/**
 * A dismissed banner stays away until it gets worse (warn to bad) or is raised again (a newer event for the same key).
 */
fun isDismissed(item: AlertItem, dismissed: Map<String, Dismissed>): Boolean {
    val was = dismissed[item.key] ?: return false
    return item.severity <= was.severity && item.event.id <= was.eventId
}

private val seriousFirst = compareByDescending<AlertItem> { it.severity }.thenByDescending { it.event.id }

private fun AlertEvent.isBannerKind() = severity == AlertSeverity.Warn || severity == AlertSeverity.Bad

/** The banners: [shown] (at most [BANNERS_SHOWN], most serious first, then newest) and how many more there are. */
data class BannerState(val shown: List<AlertItem>, val more: Int) {
    companion object {
        val None = BannerState(emptyList(), 0)
    }
}

/**
 * Banners from the raised [conditions] and the moments among [events] (alert events without a condition, warn or bad,
 * not older than [MOMENT_BANNER_MS]), minus what was dismissed.
 */
fun bannerState(
    conditions: List<AlertEvent>,
    events: List<AlertEvent>,
    dismissed: Map<String, Dismissed>,
    nowMillis: Long,
    max: Int = BANNERS_SHOWN,
): BannerState {
    val raised = conditions.filter { it.isBannerKind() && it.condition?.raised != false }
    val moments = events.filter {
        it.alert && it.condition == null && it.isBannerKind() &&
            (it.atMillis == null || nowMillis - it.atMillis <= MOMENT_BANNER_MS)
    }
    val all = (raised + moments).map(::AlertItem).distinctBy { it.key }
        .filterNot { isDismissed(it, dismissed) }
        .sortedWith(seriousFirst)
    return BannerState(all.take(max), (all.size - max).coerceAtLeast(0))
}

/** The Alerts list: the raised conditions first, then the alert events of [days] days, newest first. */
fun alertsList(conditions: List<AlertEvent>, events: List<AlertEvent>, nowMillis: Long, days: Int = 7): List<AlertItem> {
    val raised = conditions.filter { it.condition?.raised != false }.map(::AlertItem).sortedWith(seriousFirst)
    val since = nowMillis - days * 24 * HOUR_MS
    val past = events.filter { it.alert && (it.atMillis == null || it.atMillis >= since) }
        .sortedByDescending { it.id }.map(::AlertItem)
    return raised + past
}

// ---- where an action goes ----

/** Where an alert's action opens in the app (R80 17:00 ruling: a place the app has no screen for opens the Alerts list). */
sealed interface AlertTarget {
    data class Printer(val id: String) : AlertTarget
    data object RunningLow : AlertTarget
    data object AlertsList : AlertTarget
}

fun alertTarget(place: String?, id: String?): AlertTarget = when (place) {
    "printer" -> id?.takeIf { it.isNotBlank() }?.let { AlertTarget.Printer(it) } ?: AlertTarget.AlertsList
    "running_low" -> AlertTarget.RunningLow
    else -> AlertTarget.AlertsList
}

// ---- the switch and the service ----

/** What turning "Alerts on this phone" on needs first. */
enum class SwitchStep { TurnOn, AskNotifications, AskLocalNetwork }

fun switchStep(notificationsAllowed: Boolean, localNetworkGranted: Boolean): SwitchStep = when {
    !notificationsAllowed -> SwitchStep.AskNotifications
    !localNetworkGranted -> SwitchStep.AskLocalNetwork
    else -> SwitchStep.TurnOn
}

/**
 * The watching service is started when the switch is on, a Hub is paired, notifications are allowed and it is not
 * running already: after the app is opened (the service was dismissed or stopped) and after a boot or an update.
 */
fun shouldStartWatching(on: Boolean, paired: Boolean, notificationsAllowed: Boolean, running: Boolean): Boolean =
    on && paired && notificationsAllowed && !running
