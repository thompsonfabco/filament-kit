package com.thompsonfabco.filamentkit.net

import com.thompsonfabco.filamentkit.alerts.FakeHub
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The calls and models of HD9 (R84 section 9) against a fake Hub: activity, undo, health, usage by month, CSV download. */
class ApiHistoryTest {
    private val hub = FakeHub()
    private val api = hub.api()

    private val activityBody = """
        {"events": [
          {"id": 40, "at": "2026-11-17T04:00:00Z", "kind": "spool.moved", "subject": {"type": "spool", "id": "212"},
           "actor": {"type": "device", "id": "d1", "name": "Pixel"}, "title": "Moved", "text": "Moved to Shelf B.",
           "undo": {"possible": true, "until": "2026-11-24T04:00:00Z"}, "undone": false, "future": 1},
          {"id": 42, "at": "2026-11-17T05:00:00Z", "kind": "spool.weighed", "subject": {"type": "spool", "id": "212"},
           "actor": {"type": "page", "name": ""}, "title": "Weighed", "text": "",
           "undo": {"possible": false, "why_not": "changed_since"}, "undone": false},
          {"id": 41, "at": "2026-11-17T04:30:00Z", "kind": "spool.moved", "subject": {"type": "spool", "id": "99"},
           "actor": {"type": "hub"}, "text": "Other spool."}
        ]}"""

    @Test fun activityAsksForTheSpoolsActivityAndKeepsOnlyThatSpoolNewestFirst() = runBlocking {
        hub.handler = { _ -> 200 to activityBody }
        val rows = api.activity("spool:212", 10)
        assertEquals("/api/events", hub.requests[0].url.encodedPath)
        assertEquals("1", hub.query(0, "activity"))
        assertEquals("spool:212", hub.query(0, "subject"))
        assertEquals("10", hub.query(0, "limit"))
        assertEquals(listOf(42L, 40L), rows.map { it.id })
        assertEquals("Pixel", rows[1].who)
        assertEquals("page", rows[0].who)
        assertEquals("Moved to Shelf B.", rows[1].text)
        assertEquals("Weighed", rows[0].title())
        assertTrue(rows[1].canUndo)
        assertEquals("2026-11-24T04:00:00Z", rows[1].undo!!.until)
        assertFalse(rows[0].canUndo)
        assertEquals("changed_since", rows[0].undo!!.whyNot)
    }

    private fun ActivityEvent.title() = kind.removePrefix("spool.").replaceFirstChar { it.uppercase() }

    @Test fun anOlderHubsEventsHaveNoUndo() = runBlocking {
        hub.handler = { _ -> 200 to """{"events": [{"id": 1, "kind": "spool.moved", "subject": {"type": "spool", "id": "5"}, "text": "x"}]}""" }
        val row = api.activity("spool:5", 10).single()
        assertNull(row.undo)
        assertFalse(row.canUndo)
    }

    @Test fun anUndoneEventKeepsNoUndo() {
        val e = HistoryWire.event(kotlinx.serialization.json.Json.parseToJsonElement(
            """{"id": 3, "undo": {"possible": true}, "undone": true, "undo_of": 2}"""))!!
        assertFalse(e.canUndo)
        assertEquals(2L, e.undoOf)
    }

    @Test fun undoPostsAndReadsTheNewEventAndNote() = runBlocking {
        hub.handler = { _ -> 200 to """{"undone": true, "event": {"id": 51}, "note": "The printer still shows what it was set to."}""" }
        val r = api.undoEvent(40)
        assertEquals("POST", hub.requests[0].method)
        assertEquals("/api/events/40/undo", hub.requests[0].url.encodedPath)
        assertTrue(r.undone)
        assertEquals(51L, r.eventId)
        assertEquals("The printer still shows what it was set to.", r.note)
    }

    @Test fun anUndoRefusalIsAnApiErrorWithTheWhyNotAndTheHubsText() = runBlocking {
        hub.handler = { _ -> 409 to """{"error": "changed_since", "text": "This changed again since, so it cannot be undone."}""" }
        val e = assertThrows(ApiError::class.java) { runBlocking { api.undoEvent(40) } }
        assertEquals(409, e.status)
        assertEquals("changed_since", e.code)
        assertEquals("This changed again since, so it cannot be undone.", e.extra["text"]?.let { (it as kotlinx.serialization.json.JsonPrimitive).content })
    }

    @Test fun healthReadsTheTableAndSince() = runBlocking {
        hub.handler = { _ ->
            200 to """{"from": "2026-11-11T00:00:00Z", "to": "2026-11-18T00:00:00Z", "since": "2026-11-14T10:00:00Z",
              "checks": [{"key": "printer:p-3", "group": "Printers", "text": "Workshop X1", "now": "look", "spans": []}],
              "changes": [{"at": "2026-11-15T23:10:00Z", "key": "printer:p-3", "text": "Workshop X1", "from": "ok", "to": "bad"}]}"""
        }
        val h = api.health(30)!!
        assertEquals("/api/health", hub.requests[0].url.encodedPath)
        assertEquals("30", hub.query(0, "days"))
        assertEquals("2026-11-14T10:00:00Z", h.since)
        assertEquals("look", h.checks.single().now)
        val c = h.changes.single()
        assertEquals("ok", c.from)
        assertEquals("bad", c.to)
        assertNotNull(c.atMillis)
    }

    @Test fun healthIsNullOnAnOlderHub() = runBlocking {
        hub.handler = { _ -> 404 to """{"error": "not_found"}""" }
        assertNull(api.health(7))
    }

    @Test fun usageByMonthReadsMonthsNewestFirstAndIsNullWithoutThem() = runBlocking {
        hub.handler = { _ ->
            200 to """{"months": [{"month": "2026-10", "grams": 1520.5, "prints": 12, "unfinished_prints": 1},
              {"month": "2026-11", "grams": 1840, "prints": 15, "unfinished_prints": 0, "top_material": "PA6"}]}"""
        }
        val m = api.usageByMonth("p-3")!!
        assertEquals("by=month", hub.requests[0].url.query)
        assertEquals(listOf("2026-11", "2026-10"), m.map { it.month })
        assertEquals("PA6", m[0].topMaterial)
        assertNull(m[1].topMaterial)
        assertEquals(1520.5, m[1].grams, 0.001)
        hub.handler = { _ -> 200 to """{"entries": []}""" }
        assertNull(api.usageByMonth("p-3"))
    }

    @Test fun exportCsvWritesTheFileOnlyWhenWholeAndPassesTheQuery() = runBlocking {
        val dir = java.nio.file.Files.createTempDirectory("csv").toFile()
        hub.handler = { _ -> 200 to "time,grams\n2026-11-01,5\n" }
        val to = File(dir, "usage.csv")
        api.exportCsv("usage", to, days = 30, printer = "p-3")
        assertEquals("/api/export/usage.csv", hub.requests[0].url.encodedPath)
        assertEquals("30", hub.query(0, "days"))
        assertEquals("p-3", hub.query(0, "printer"))
        assertEquals("Bearer tok-123", hub.requests[0].header("Authorization"))
        assertEquals("time,grams\n2026-11-01,5\n", to.readText())
        assertFalse(File(dir, "usage.csv.part").exists())
        hub.handler = { _ -> 404 to """{"error": "not_found"}""" }
        val e = assertThrows(ApiError::class.java) { runBlocking { api.exportCsv("recent", File(dir, "recent.csv")) } }
        assertEquals(404, e.status)
        assertFalse(File(dir, "recent.csv").exists())
        dir.deleteRecursively()
        Unit
    }
}
