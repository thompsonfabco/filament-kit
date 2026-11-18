package com.thompsonfabco.filamentkit.alerts

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AlertsFeedTest {
    private val hub = FakeHub()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
    private val now = AlertParsing.parseTime("2026-11-17T12:00:00Z")!!
    private val tests = mutableListOf<AlertTest>()
    private val feed = AlertsFeed(scope, { hub.api() }, null, { now }, { tests += it })

    @After fun tearDown() = scope.cancel()

    @Test fun theBannerReadAsksADayBackAndTheListSevenDaysWithNoWait() = runBlocking {
        hub.handler = { 200 to SAMPLE_EVENTS }
        feed.refresh(AlertsUi.BANNER_DAYS)
        assertEquals("2026-11-16T12:00:00Z", hub.query(0, "since_at"))
        assertEquals("0", hub.query(0, "wait"))
        assertEquals("1", hub.query(0, "alert"))
        feed.refresh(AlertsUi.LIST_DAYS)
        assertEquals("2026-11-10T12:00:00Z", hub.query(1, "since_at"))
        val ui = feed.state.value
        assertTrue(ui.loaded)
        assertEquals(7, ui.days)
        assertEquals(3, ui.events.size)
    }

    @Test fun aTestInTheAnswerIsPassedOnOnce() = runBlocking {
        hub.handler = { 200 to """{"events":[],"next":1,"test":{"title":"Test alert","text":"It works."}}""" }
        feed.refresh(1)
        assertEquals(listOf(AlertTest("Test alert", "It works.")), tests)
    }

    @Test fun aHubWithoutAlertsIsUnavailableAndOfflineLeavesTheLastAnswer() = runBlocking {
        hub.handler = { 200 to SAMPLE_EVENTS }
        feed.refresh(1)
        hub.handler = { throw java.io.IOException("down") }
        feed.refresh(1)
        assertEquals("the last answer stays", 3, feed.state.value.events.size)
        assertTrue(feed.state.value.available)
        hub.handler = { 404 to """{"error":"not_found"}""" }
        feed.refresh(1)
        assertFalse(feed.state.value.available)
        assertTrue(feed.state.value.events.isEmpty())
    }

    @Test fun theRunningLowCountComesFromTheLowList() = runBlocking {
        hub.handler = { 200 to """{"threshold_g":150,"spools":[{"id":1},{"id":2}]}""" }
        feed.refreshLow()
        assertEquals(2, feed.state.value.lowCount)
        hub.handler = { 404 to "{}" }
        feed.refreshLow()
        assertNull(feed.state.value.lowCount)
    }

    @Test fun dismissingHidesTheBannerUntilItIsRaisedAgain() = runBlocking {
        hub.handler = { 200 to """{"events":[],"conditions":[{"id":5,"at":"2026-11-17T11:50:00Z","severity":"warn","alert":true,""" +
            """"condition":{"key":"storage-low","state":"raised"},"title":"Storage","text":"Almost full."}]}""" }
        feed.refresh(1)
        val ui = feed.state.value
        val shown = bannerState(ui.conditions, ui.events, ui.dismissed, now)
        assertEquals(1, shown.shown.size)
        feed.dismiss(shown.shown[0])
        val after = feed.state.value
        assertTrue(bannerState(after.conditions, after.events, after.dismissed, now).shown.isEmpty())
    }
}
