package com.thompsonfabco.filamentkit.alerts

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AlertParsingTest {
    private fun events(text: String) = AlertParsing.events(Json.parseToJsonElement(text))

    @Test fun anEventsAnswerIsReadWithItsConditionActionAndTimes() {
        val a = events(SAMPLE_EVENTS)
        assertEquals(listOf(12L, 13L, 14L), a.events.map { it.id })
        assertEquals(14L, a.next)
        assertEquals(1L, a.oldest)
        assertFalse(a.gap)
        assertNull(a.test)
        val runout = a.events[0]
        assertEquals("print.runout", runout.kind)
        assertEquals(AlertSeverity.Warn, runout.severity)
        assertEquals("print-paused:p-3", runout.condition?.key)
        assertTrue(runout.condition!!.raised)
        assertTrue(runout.alert)
        assertEquals("Filament ran out on Workshop X1", runout.title)
        assertEquals("printer", runout.action.place)
        assertEquals("p-3", runout.action.id)
        assertEquals(AlertParsing.parseTime("2026-11-17T04:12:09Z"), runout.atMillis)
        assertNull("a null condition is a moment", a.events[1].condition)
        assertFalse(a.events[2].condition!!.raised)
    }

    @Test fun missingFieldsAndUnknownKeysAreLenient() {
        val a = events("""{"events":[{"id":5},{"nope":1},"text",{"id":6,"alert":"yes","at":"not a time","severity":"loud"}],"extra":{}}""")
        assertEquals(listOf(5L, 6L), a.events.map { it.id })
        assertFalse(a.events[0].alert)
        assertEquals("", a.events[0].title)
        assertNull(a.events[1].atMillis)
        assertEquals(AlertSeverity.Info, a.events[1].severity)
        assertNull(a.next)
        assertTrue(a.conditions.isEmpty())
        assertFalse(a.gap)
    }

    @Test fun anAnswerThatIsNotAnObjectIsEmpty() {
        val a = AlertParsing.events(Json.parseToJsonElement("[1,2]"))
        assertTrue(a.events.isEmpty())
        assertNull(a.next)
    }

    @Test fun gapAndTestAreRead() {
        val a = events("""{"events":[],"next":40,"oldest":30,"gap":true,"test":{"title":"Test alert","text":"It works."}}""")
        assertTrue(a.gap)
        assertEquals(30L, a.oldest)
        assertEquals(AlertTest("Test alert", "It works."), a.test)
        assertNull(events("""{"test":{"title":"","text":""}}""").test)
    }

    @Test fun theAlertsAndLowSpoolsAnswersAreRead() {
        val c = AlertParsing.alerts(Json.parseToJsonElement(
            """{"types":[{"key":"runout","title":"Filament ran out","on":true},{"key":"finished","title":"x","on":false}],""" +
                """"last_spool_only":false,"running_low_g":150,"storage_warn_percent":85,"storage_bad_percent":95}""",
        ))
        assertEquals(listOf("runout" to true, "finished" to false), c.types.map { it.key to it.on })
        assertEquals(150, c.runningLowG)
        assertEquals(95, c.storageBadPercent)
        val low = AlertParsing.lowSpools(Json.parseToJsonElement(
            """{"threshold_g":150,"spools":[{"id":7,"filament":"Prusament PLA","material":"PLA","color":"ff8800","remaining_g":96.5,""" +
                """"location":"Shelf A","in_stock":2,"last_one":false},{"id":8,"filament":"x","last_one":true},{"filament":"no id"}]}""",
        ))
        assertEquals(150, low.thresholdG)
        assertEquals(listOf(7, 8), low.spools.map { it.id })
        assertEquals(96.5, low.spools[0].remainingG!!, 0.0)
        assertEquals("Shelf A", low.spools[0].location)
        assertTrue(low.spools[1].lastOne)
        assertNull(low.spools[1].color)
    }

    @Test fun theHubsTimeRoundTrips() {
        val millis = AlertParsing.parseTime("2026-11-17T04:12:09Z")!!
        assertEquals("2026-11-17T04:12:09Z", AlertParsing.formatTime(millis))
        assertEquals("fractions are cut", "2026-11-17T04:12:09Z", AlertParsing.formatTime(millis + 999))
        assertNull(AlertParsing.parseTime("yesterday"))
    }
}
