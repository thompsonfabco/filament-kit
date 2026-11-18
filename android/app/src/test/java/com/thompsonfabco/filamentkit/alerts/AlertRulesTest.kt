package com.thompsonfabco.filamentkit.alerts

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AlertRulesTest {
    private val now = AlertParsing.parseTime("2026-11-17T12:00:00Z")!!
    private val minute = 60_000L

    private fun event(
        id: Long,
        severity: AlertSeverity = AlertSeverity.Warn,
        condition: AlertCondition? = null,
        alert: Boolean = true,
        agoMs: Long = 5 * minute,
        kind: String = "print.paused",
        data: JsonObject = JsonObject(emptyMap()),
        place: String? = "printer",
    ) = AlertEvent(
        id = id, atMillis = now - agoMs, kind = kind, severity = severity, condition = condition, alert = alert,
        title = "Title $id", text = "Text $id", action = AlertAction(place, "p-1"), data = data,
    )

    private fun answer(vararg events: AlertEvent, test: AlertTest? = null, next: Long? = null) =
        EventsAnswer(events.toList(), next, emptyList(), null, false, test)

    // ---- which events notify ----

    @Test fun oneNotificationPerAlertEventAndNoneForEventsNoAlertTypeCovers() {
        val actions = notifyActions(answer(event(1), event(2, alert = false), event(3, severity = AlertSeverity.Bad)), now)
        assertEquals(listOf("alert:event:1", "alert:event:3"), actions.map { (it as NotifyAction.Show).tag })
    }

    @Test fun aRaisedConditionNotifiesAndItsClearingRemovesTheNotificationWithoutSendingOne() {
        val raised = event(1, condition = AlertCondition("print-paused:p-1", "raised"))
        val cleared = event(2, severity = AlertSeverity.Ok, condition = AlertCondition("print-paused:p-1", "cleared"), alert = false)
        val actions = notifyActions(answer(raised, cleared), now)
        assertEquals(
            listOf(NotifyAction.Show("alert:print-paused:p-1", raised), NotifyAction.Cancel("alert:print-paused:p-1")),
            actions,
        )
    }

    @Test fun theSameConditionRaisedAgainReplacesItsNotificationByTheSameTag() {
        val a = event(1, condition = AlertCondition("storage-low", "raised"))
        val b = event(2, severity = AlertSeverity.Bad, condition = AlertCondition("storage-low", "raised"))
        val tags = notifyActions(answer(a, b), now).map { (it as NotifyAction.Show).tag }
        assertEquals(listOf("alert:storage-low", "alert:storage-low"), tags)
    }

    @Test fun aConditionClearedEventWithoutAConditionFieldCancelsTheKeyInItsData() {
        val e = event(4, kind = "condition.cleared", alert = false, data = JsonObject(mapOf("key" to JsonPrimitive("spool-low:7"))))
        assertEquals(listOf(NotifyAction.Cancel("alert:spool-low:7")), notifyActions(answer(e), now))
    }

    @Test fun anEventOlderThanADayDoesNotNotify() {
        val old = event(1, agoMs = 25 * 3_600_000L)
        assertTrue(notifyActions(answer(old), now).isEmpty())
    }

    @Test fun aTestObjectShowsOneTestNotification() {
        val test = AlertTest("Test alert", "It works.")
        assertEquals(listOf(NotifyAction.ShowTest(test)), notifyActions(answer(test = test), now))
    }

    @Test fun theRaisedConditionsListIsNotReadForNotifications() {
        val a = EventsAnswer(emptyList(), 3, listOf(event(9, condition = AlertCondition("k", "raised"))), null, false, null)
        assertTrue(notifyActions(a, now).isEmpty())
    }

    // ---- cursor, first run, gap ----

    @Test fun theFirstAskUsesTheTimeWatchingBeganAndLaterAsksTheCursor() {
        val first = nextQuery(null, now, 55)
        assertNull(first.since)
        assertEquals("2026-11-17T12:00:00Z", first.sinceAt)
        assertEquals(55, first.waitS)
        val later = nextQuery(41, now, 55)
        assertEquals(41L, later.since)
        assertNull(later.sinceAt)
    }

    @Test fun theCursorFollowsNextThenTheHighestIdAndNeverGoesBack() {
        assertEquals(14L, advance(10, answer(event(12), next = 14)))
        assertEquals(12L, advance(10, answer(event(12))))
        assertEquals("nothing new keeps it", 10L, advance(10, answer()))
        assertNull(advance(null, answer()))
        assertEquals(10L, advance(10, answer(next = 4)))
    }

    @Test fun aGapChangesNothingForTheCursor() {
        val gap = EventsAnswer(emptyList(), 50, emptyList(), 40, true, null)
        assertEquals(50L, advance(10, gap))
    }

    // ---- backoff ----

    @Test fun backoffDoublesToItsCapAndStartsAgainAfterReset() {
        val b = Backoff(2_000, 60_000)
        assertEquals(listOf(2_000L, 4_000L, 8_000L, 16_000L, 32_000L, 60_000L, 60_000L), List(7) { b.next() })
        b.reset()
        assertEquals(2_000L, b.next())
    }

    // ---- banners ----

    private fun dismissedOf(vararg pairs: Pair<String, Dismissed>) = mapOf(*pairs)

    @Test fun twoBannersAreShownMostSeriousFirstThenNewestAndTheRestIsOneLine() {
        val warnOld = event(1, condition = AlertCondition("a", "raised"))
        val warnNew = event(5, condition = AlertCondition("b", "raised"))
        val bad = event(3, severity = AlertSeverity.Bad, condition = AlertCondition("c", "raised"))
        val moment = event(4, severity = AlertSeverity.Bad, kind = "print.failed")
        val banners = bannerState(listOf(warnOld, warnNew, bad), listOf(moment), emptyMap(), now)
        assertEquals(listOf(4L, 3L), banners.shown.map { it.event.id })
        assertEquals(2, banners.more)
    }

    @Test fun oneBannerHasNoMoreLine() {
        val banners = bannerState(listOf(event(1, condition = AlertCondition("a", "raised"))), emptyList(), emptyMap(), now)
        assertEquals(1, banners.shown.size)
        assertEquals(0, banners.more)
    }

    @Test fun aMomentLeavesAfter24HoursAndInfoEventsNeverBanner() {
        val old = event(1, severity = AlertSeverity.Bad, agoMs = 25 * 3_600_000L)
        val fresh = event(2, severity = AlertSeverity.Bad, agoMs = 23 * 3_600_000L)
        val info = event(3, severity = AlertSeverity.Info)
        val notAlert = event(4, severity = AlertSeverity.Bad, alert = false)
        val banners = bannerState(emptyList(), listOf(old, fresh, info, notAlert), emptyMap(), now)
        assertEquals(listOf(2L), banners.shown.map { it.event.id })
    }

    @Test fun aDismissedBannerStaysAwayUntilWorseOrRaisedAgain() {
        val warn = event(5, condition = AlertCondition("storage-low", "raised"))
        val dismissed = dismissedOf("storage-low" to Dismissed(AlertSeverity.Warn, 5))
        assertTrue("still the same", bannerState(listOf(warn), emptyList(), dismissed, now).shown.isEmpty())
        val worse = event(5, severity = AlertSeverity.Bad, condition = AlertCondition("storage-low", "raised"))
        assertEquals("warn to bad comes back", 1, bannerState(listOf(worse), emptyList(), dismissed, now).shown.size)
        val again = event(9, condition = AlertCondition("storage-low", "raised"))
        assertEquals("raised again comes back", 1, bannerState(listOf(again), emptyList(), dismissed, now).shown.size)
        val other = event(6, condition = AlertCondition("print-paused:p-1", "raised"))
        assertEquals("another key is not hidden", 1, bannerState(listOf(other), emptyList(), dismissed, now).shown.size)
    }

    @Test fun aConditionThatAlsoCameAsAnEventIsOneBanner() {
        val c = event(1, condition = AlertCondition("a", "raised"))
        assertEquals(1, bannerState(listOf(c), listOf(c), emptyMap(), now).shown.size)
    }

    @Test fun theAlertsListHasRaisedConditionsFirstThenSevenDaysOfAlertEventsNewestFirst() {
        val raised = event(10, condition = AlertCondition("a", "raised"))
        val e3 = event(3, agoMs = 2 * 24 * 3_600_000L)
        val e4 = event(4, agoMs = 1 * 24 * 3_600_000L)
        val tooOld = event(2, agoMs = 8 * 24 * 3_600_000L)
        val quiet = event(5, alert = false)
        val list = alertsList(listOf(raised), listOf(e3, tooOld, e4, quiet), now)
        assertEquals(listOf(10L, 4L, 3L), list.map { it.event.id })
        assertTrue(alertsList(emptyList(), emptyList(), now).isEmpty())
    }

    // ---- where an action goes, the switch, the service ----

    @Test fun anActionOpensThePrinterTheRunningLowListOrElseTheAlertsList() {
        assertEquals(AlertTarget.Printer("p-3"), alertTarget("printer", "p-3"))
        assertEquals(AlertTarget.AlertsList, alertTarget("printer", ""))
        assertEquals(AlertTarget.RunningLow, alertTarget("running_low", null))
        for (place in listOf("storage_use", "devices", "backups", "something_new", null)) {
            assertEquals(AlertTarget.AlertsList, alertTarget(place, "x"))
        }
    }

    @Test fun theSwitchAsksNotificationsThenTheLocalNetworkAndThenTurnsOn() {
        assertEquals(SwitchStep.AskNotifications, switchStep(notificationsAllowed = false, localNetworkGranted = false))
        assertEquals(SwitchStep.AskLocalNetwork, switchStep(notificationsAllowed = true, localNetworkGranted = false))
        assertEquals(SwitchStep.TurnOn, switchStep(notificationsAllowed = true, localNetworkGranted = true))
    }

    @Test fun theServiceStartsOnlyWhenOnPairedAllowedAndNotRunning() {
        assertTrue(shouldStartWatching(on = true, paired = true, notificationsAllowed = true, running = false))
        assertFalse(shouldStartWatching(on = false, paired = true, notificationsAllowed = true, running = false))
        assertFalse(shouldStartWatching(on = true, paired = false, notificationsAllowed = true, running = false))
        assertFalse(shouldStartWatching(on = true, paired = true, notificationsAllowed = false, running = false))
        assertFalse(shouldStartWatching(on = true, paired = true, notificationsAllowed = true, running = true))
    }
}
