package com.thompsonfabco.filamentkit.alerts

import com.thompsonfabco.filamentkit.net.ApiError
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** The Api's events, alerts, spools/low and test calls against a Hub that answers from a fake. */
class EventsClientTest {
    private val hub = FakeHub()

    @Test fun theWaitingCallAsksTheCursorAndAlertOnlyAndWaitsLongerThanTheHub() = runBlocking {
        hub.handler = { 200 to SAMPLE_EVENTS }
        val answer = hub.api().events(EventsQuery(since = 11, sinceAt = null, waitS = 55))
        assertEquals(14L, answer.next)
        val r = hub.requests.single()
        assertEquals("GET", r.method)
        assertEquals("/api/events", r.url.encodedPath)
        assertEquals("11", hub.query(0, "since"))
        assertNull(hub.query(0, "since_at"))
        assertEquals("55", hub.query(0, "wait"))
        assertEquals("1", hub.query(0, "alert"))
        assertEquals("Bearer tok-123", r.header("Authorization"))
        assertTrue("read timeout is above the wait: ${hub.readTimeoutsMs[0]}", hub.readTimeoutsMs[0] >= 60_000)
    }

    @Test fun theBannerCallAsksATimeWithNoWait() = runBlocking {
        hub.handler = { 200 to """{"events":[],"next":3}""" }
        hub.api().events(EventsQuery(since = null, sinceAt = "2026-11-16T12:00:00Z", waitS = 0, limit = 200))
        assertEquals("2026-11-16T12:00:00Z", hub.query(0, "since_at"))
        assertNull(hub.query(0, "since"))
        assertEquals("0", hub.query(0, "wait"))
        assertEquals("200", hub.query(0, "limit"))
    }

    @Test fun anOlderHubAnswers404AndARevokedTokenAnswers401() {
        hub.handler = { 404 to """{"error":"not_found","message":"no"}""" }
        assertEquals(404, assertThrows(ApiError::class.java) { runBlocking { hub.api().events(EventsQuery(null, "x", 0)) } }.status)
        hub.handler = { 401 to """{"error":"x"}""" }
        assertEquals("unauthorized", assertThrows(ApiError::class.java) { runBlocking { hub.api().alertsConfig() } }.code)
    }

    @Test fun theAlertsTestAndLowSpoolsRoutes() = runBlocking {
        hub.handler = { r ->
            when (r.url.encodedPath) {
                "/api/alerts" -> 200 to """{"types":[{"key":"runout","title":"Filament ran out","on":true}],"running_low_g":150}"""
                "/api/spools/low" -> 200 to """{"threshold_g":150,"spools":[{"id":7,"filament":"PLA","remaining_g":90,"in_stock":0,"last_one":true}]}"""
                else -> 200 to "{}"
            }
        }
        val api = hub.api()
        assertEquals(150, api.alertsConfig().runningLowG)
        assertEquals(listOf(7), api.lowSpools().spools.map { it.id })
        api.sendTestAlert()
        val test = hub.requests.last()
        assertEquals("POST", test.method)
        assertEquals("/api/alerts/test", test.url.encodedPath)
    }
}
