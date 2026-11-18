package com.thompsonfabco.filamentkit.net

import com.thompsonfabco.filamentkit.BuildConfig
import com.thompsonfabco.filamentkit.alerts.FakeHub
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** The calls and models of phase 3 (R83 10.1) against a fake Hub: the client header, clear, hub, catalog entries, spools. */
class ApiPhase3Test {
    private val hub = FakeHub()
    private val api = hub.api()

    private fun body(i: Int): JsonObject {
        val buffer = okio.Buffer()
        hub.requests[i].body!!.writeTo(buffer)
        return Json.parseToJsonElement(buffer.readUtf8()).jsonObject
    }

    @Test fun everyCallCarriesTheClientHeader() = runBlocking {
        hub.handler = { _ -> 200 to """{"printers": [], "spools": [], "entries": [], "name": "H", "version": "1", "api": 1}""" }
        api.printers()
        api.localLibrary()
        api.spools("", null)
        api.info()
        hub.requests.forEach { assertEquals("android/${BuildConfig.VERSION_NAME}", it.header("X-Spoolwarden-Client")) }
        assertEquals(4, hub.requests.size)
    }

    @Test fun theClientHeaderUsesTheVersionGiven() = runBlocking {
        hub.handler = { _ -> 200 to "{}" }
        hub.api(clientVersion = "9.8.7").hub()
        assertEquals("android/9.8.7", hub.requests.single().header("X-Spoolwarden-Client"))
    }

    @Test fun clearSlotSendsDryRunAndReadsEveryField() = runBlocking {
        hub.handler = { _ ->
            200 to """{"slot": "A1", "spool": {"id": 7, "location": "Shelf"}, "moved_back": "Shelf", "waiting_ended": true,
                "printer_cleared": true, "dry_run": false, "text": "Said.", "future": 1}"""
        }
        val r = api.clearSlot("p-3", "A1", dryRun = false)
        assertEquals("POST", hub.requests[0].method)
        assertEquals("/api/printers/p-3/slots/A1/clear", hub.requests[0].url.encodedPath)
        assertFalse(body(0)["dry_run"]!!.jsonPrimitive.content.toBoolean())
        assertEquals("A1", r.slot)
        assertEquals(7, r.spool!!["id"]!!.jsonPrimitive.content.toInt())
        assertEquals("Shelf", r.movedBack)
        assertTrue(r.waitingEnded)
        assertTrue(r.printerCleared)
        assertFalse(r.dryRun)
        assertEquals("Said.", r.text)
    }

    @Test fun clearSlotWithNoSpoolAndMissingFieldsReadsAsDefaults() = runBlocking {
        hub.handler = { _ -> 200 to """{"slot": "B2", "spool": null, "dry_run": true}""" }
        val r = api.clearSlot("p-3", "B2", dryRun = true)
        assertNull(r.spool)
        assertNull(r.movedBack)
        assertFalse(r.waitingEnded)
        assertFalse(r.printerCleared)
        assertNull(r.text)
        assertTrue(r.dryRun)
        assertTrue(body(0)["dry_run"]!!.jsonPrimitive.content.toBoolean())
    }

    @Test fun clearSlotErrorsMapToApiError() {
        hub.handler = { _ -> 404 to """{"error": "not_found", "message": "No such slot"}""" }
        val e = assertThrows(ApiError::class.java) { runBlocking { api.clearSlot("p-3", "Z9", dryRun = true) } }
        assertEquals(404, e.status)
        assertEquals("not_found", e.code)
    }

    @Test fun unloadReadsWaitingEndedAndLoadReadsPending() = runBlocking {
        hub.handler = { _ ->
            200 to """{"spool": null, "slot": {"label": "A1"}, "location": "Shelf", "moved_back": [], "waiting_ended": true}"""
        }
        assertTrue(api.unload("p-3", "A1", dryRun = false).waitingEnded)
        hub.handler = { _ -> 200 to """{"spool": null, "slot": {"label": "A1"}, "pending": true}""" }
        assertTrue(api.load("p-3", "A1", 7, dryRun = false).pending)
        hub.handler = { _ -> 200 to """{"spool": null, "slot": {"label": "A1"}, "location": ""}""" }
        assertFalse(api.unload("p-3", "A1", dryRun = false).waitingEnded)
        hub.handler = { _ -> 200 to """{"spool": null, "slot": {"label": "A1"}, "pending": null}""" }
        assertFalse(api.load("p-3", "A1", 7, dryRun = false).pending)
    }

    @Test fun hubReadsEveryGroup() = runBlocking {
        hub.handler = { _ -> 200 to FULL_HUB }
        val h = api.hub()!!
        assertEquals("/api/hub", hub.requests[0].url.encodedPath)
        assertEquals("Workshop Hub", h.name)
        assertEquals("0.7.0", h.version)
        assertEquals("0.8.0", h.newest!!.version)
        assertEquals("2026-11-17T08:00:00+00:00", h.newest!!.checkedAt)
        assertTrue(h.updateAvailable)
        assertEquals(2, h.checks.size)
        assertEquals(HubCheckState.Look, h.checks[1].state)
        assertEquals("Add a backup folder.", h.checks[1].fix)
        assertNull(h.checks[0].fix)
        assertEquals(GettingStarted(4, 8, hidden = false, finished = false), h.gettingStarted)
        assertEquals(listOf("Alerts" to true, "Camera" to false), h.features.map { it.name to it.on })
        assertEquals("1.4", h.catalog!!.version)
        assertTrue(h.backup!!.nightly)
        assertEquals("2026-11-16T03:00:00+00:00", h.backup!!.lastAt)
        assertEquals(HubReaderFacts("local", keySet = true), h.reader)
        assertEquals(2, h.devices.size)
        assertTrue(h.devices[0].thisOne)
        assertTrue(h.devices[1].outOfDate)
        assertEquals(41L, h.recordsKept)
        assertEquals("http://hub.local:7912", h.spoolmanUrl)
        assertEquals("https://hub.local:8710/setup", h.hubPage)
    }

    @Test fun hubWithOptionalPartsMissingIsStillRead() = runBlocking {
        hub.handler = { _ ->
            200 to """{"name": "H", "version": "0.7.0", "update_available": false, "checks": [{"group": "Hub", "state": "weird", "text": "x"}],
                "getting_started": null, "future_key": [1, 2]}"""
        }
        val h = api.hub()!!
        assertNull(h.newest)
        assertNull(h.gettingStarted)
        assertNull(h.catalog)
        assertNull(h.backup)
        assertNull(h.reader)
        assertNull(h.recordsKept)
        assertNull(h.spoolmanUrl)
        assertNull(h.hubPage)
        assertTrue(h.features.isEmpty())
        assertTrue(h.devices.isEmpty())
        assertEquals(HubCheckState.Note, h.checks.single().state)
    }

    @Test fun hubIsNullFromAnOlderHub() = runBlocking {
        hub.handler = { _ -> 404 to """{"error": "not_found"}""" }
        assertNull(api.hub())
    }

    @Test fun hubOtherErrorsPropagate() {
        hub.handler = { _ -> 401 to """{"error": "unauthorized"}""" }
        val e = assertThrows(ApiError::class.java) { runBlocking { api.hub() } }
        assertEquals("unauthorized", e.code)
    }

    @Test fun localLibraryReadsEntriesAndSkipsOnesWithoutAnId() = runBlocking {
        hub.handler = { _ ->
            200 to """{"entries": [{"id": "a1", "brand": "Acme", "name": "Red", "material": "PLA", "added": "2026-11-01T10:00:00+00:00"},
                {"brand": "No id"}, {"id": "b2", "brand": "Acme", "name": "Blue", "material": "PETG"}]}"""
        }
        val library = api.localLibrary()
        val list = library.entries
        assertNull("an older Hub sends no materials", library.materials)
        assertEquals("/api/library/local", hub.requests[0].url.encodedPath)
        assertEquals(listOf("a1", "b2"), list.map { it.id })
        assertEquals("2026-11-01T10:00:00+00:00", list[0].added)
        assertNull(list[1].added)
    }

    @Test fun localLibraryReadsTheMaterialsAndWholeSecondTimes() = runBlocking {
        hub.handler = { _ ->
            200 to """{"entries": [{"id": "a1", "brand": "Acme", "name": "Red", "material": "PLA", "added": 1794873600},
                {"id": "b2", "brand": "Acme", "name": "Blue", "material": "PETG", "added": null}],
                "materials": ["PLA", "Wood PLA", " ", 5, "PEEK"]}"""
        }
        val library = api.localLibrary()
        assertEquals(listOf("PLA", "Wood PLA", "PEEK"), library.materials)
        assertEquals("1794873600", library.entries[0].added)
        assertNull(library.entries[1].added)
        hub.handler = { _ -> 200 to """{"entries": [], "materials": []}""" }
        assertEquals("a catalog-less Hub's empty list is kept", emptyList<String>(), api.localLibrary().materials)
    }

    @Test fun hubTimesAsWholeSecondsAndAsIsoTextBothRead() = runBlocking {
        hub.handler = { _ ->
            200 to """{"name": "H", "version": "1", "newest": {"version": "2", "checked_at": 1794902400},
                "catalog": {"version": "1.4", "checked_at": 1794902400}, "backup": {"last_at": 1794816000, "nightly": true},
                "devices": [{"name": "P", "kind": "phone", "last_seen": 1794906000, "out_of_date": false, "this": true},
                            {"name": "Q", "kind": "pc", "last_seen": null, "out_of_date": false, "this": false}]}"""
        }
        val h = api.hub()!!
        assertEquals("1794902400", h.newest!!.checkedAt)
        assertEquals("1794902400", h.catalog!!.checkedAt)
        assertEquals("1794816000", h.backup!!.lastAt)
        assertEquals("1794906000", h.devices[0].lastSeen)
        assertNull(h.devices[1].lastSeen)
    }

    @Test fun addLocalEntryFormSendsValuesAndReadsTheEntry() = runBlocking {
        hub.handler = { _ -> 201 to """{"entry": {"id": "c3", "brand": "Acme", "name": "Green", "material": "ABS", "added": "2026-11-17T09:00:00+00:00"}}""" }
        val values = buildJsonObject {
            put("brand", "Acme")
            put("name", "Green")
            put("material", "ABS")
            put("nozzle_min", 240)
        }
        val e = api.addLocalEntryForm(values)
        assertEquals("POST", hub.requests[0].method)
        assertEquals("/api/library/local/form", hub.requests[0].url.encodedPath)
        assertEquals(values, body(0))
        assertEquals("c3", e.id)
        assertEquals("ABS", e.material)
    }

    @Test fun addLocalEntryFormMapsInvalidEntryToProblems() {
        hub.handler = { _ ->
            400 to """{"error": "invalid_entry", "message": "Not valid", "problems": [{"field": "brand", "text": "Brand is required."},
                {"field": "nozzle_max", "text": "Must be above the lowest."}, 5]}"""
        }
        val e = assertThrows(ApiError::class.java) {
            runBlocking { api.addLocalEntryForm(buildJsonObject { put("brand", "") }) }
        }
        assertEquals(400, e.status)
        assertEquals("invalid_entry", e.code)
        assertEquals(
            listOf(EntryProblem("brand", "Brand is required."), EntryProblem("nozzle_max", "Must be above the lowest.")),
            KitWire.problems(e),
        )
    }

    @Test fun theHubsExactProblemsShapeIsRead() {
        hub.handler = { _ ->
            400 to """{"error": "invalid_entry", "message": "The entry is not valid.",
                "problems": [{"field": "density", "text": "Density must be above 0."}, {"field": "material", "text": "Pick a material."}]}"""
        }
        val e = assertThrows(ApiError::class.java) {
            runBlocking { api.addLocalEntryForm(buildJsonObject { put("brand", "A") }) }
        }
        assertEquals(
            listOf(EntryProblem("density", "Density must be above 0."), EntryProblem("material", "Pick a material.")),
            KitWire.problems(e),
        )
    }

    @Test fun problemsOfAnotherErrorAreEmpty() {
        assertTrue(KitWire.problems(ApiError(500, "internal", "x")).isEmpty())
    }

    @Test fun removeLocalEntryDeletesByIdAndAnUnknownIdIs404() {
        hub.handler = { _ -> 200 to """{"removed": true}""" }
        runBlocking { api.removeLocalEntry("a 1") }
        assertEquals("DELETE", hub.requests[0].method)
        assertEquals("/api/library/local/a%201", hub.requests[0].url.encodedPath)
        hub.handler = { _ -> 404 to """{"error": "not_found", "message": "No such entry"}""" }
        val e = assertThrows(ApiError::class.java) { runBlocking { api.removeLocalEntry("zz") } }
        assertEquals(404, e.status)
    }

    @Test fun spoolsAsksWithFilterAndReadsLoadedLowAndSpoolmanUrl() = runBlocking {
        hub.handler = { _ ->
            200 to """{"spoolman_url": "http://hub.local:7912", "spools": [
                {"id": 1, "view": {"id": 1, "loaded": {"printer_id": "p-3", "printer": "Workshop", "slot": "A1"}, "low": true}},
                {"id": 2, "loaded": null, "low": false},
                {"id": 3}]}"""
        }
        val a = api.spools(" pla ", SpoolFilter.LOADED)
        assertEquals("pla", hub.query(0, "q"))
        assertEquals("loaded", hub.query(0, "filter"))
        assertEquals("http://hub.local:7912", a.spoolmanUrl)
        assertEquals(SpoolLoaded("p-3", "Workshop", "A1"), KitWire.spoolLoaded(a.spools[0]))
        assertTrue(KitWire.spoolLow(a.spools[0]))
        assertNull(KitWire.spoolLoaded(a.spools[1]))
        assertFalse(KitWire.spoolLow(a.spools[1]))
        assertNull(KitWire.spoolLoaded(a.spools[2]))
        assertFalse(KitWire.spoolLow(a.spools[2]))
    }

    @Test fun spoolsWithoutFilterOrQueryAsksForNeither() = runBlocking {
        hub.handler = { _ -> 200 to """{"spools": []}""" }
        val a = api.spools("", null)
        assertNull(hub.query(0, "q"))
        assertNull(hub.query(0, "filter"))
        assertNull(a.spoolmanUrl)
        assertNotNull(a.spools)
    }

    private companion object {
        const val FULL_HUB = """{
          "name": "Workshop Hub", "version": "0.7.0",
          "newest": {"version": "0.8.0", "checked_at": "2026-11-17T08:00:00+00:00"}, "update_available": true,
          "checks": [{"group": "Hub", "state": "ok", "text": "The Hub is running."},
                     {"group": "Backups", "state": "look", "text": "No backup yet.", "fix": "Add a backup folder."}],
          "getting_started": {"done": 4, "total": 8, "hidden": false, "finished": false},
          "features": [{"id": "alerts", "name": "Alerts", "on": true}, {"id": "camera", "name": "Camera", "on": false}],
          "catalog": {"version": "1.4", "checked_at": "2026-11-17T07:00:00+00:00"},
          "backup": {"last_at": "2026-11-16T03:00:00+00:00", "nightly": true},
          "reader": {"engine": "local", "key_set": true},
          "devices": [{"name": "My phone", "kind": "phone", "version": "0.7.0", "last_seen": "2026-11-17T09:00:00+00:00", "out_of_date": false, "this": true},
                      {"name": "Station", "kind": "station", "out_of_date": true, "this": false}],
          "records_kept": 41, "spoolman_url": "http://hub.local:7912", "hub_page": "https://hub.local:8710/setup"
        }"""
    }
}
