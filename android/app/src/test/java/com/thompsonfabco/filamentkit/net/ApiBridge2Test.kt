package com.thompsonfabco.filamentkit.net

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import okhttp3.tls.HandshakeCertificates
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress

/** Bridge part 2 routes: slot mapping, loading, filament used (route-contract.md). */
class ApiBridge2Test {
    private val cert = serverCert()
    private val server = MockWebServer().also {
        it.useHttps(HandshakeCertificates.Builder().heldCertificate(cert).build().sslSocketFactory())
        it.start(InetAddress.getByName("127.0.0.1"), 0)
    }
    private val api = Api(pinnedClient(cert.fingerprint()), { server.ipUrl("/").toString().trimEnd('/') }, { "tok-123" })

    @After fun tearDown() = server.close()

    private fun json(body: String, code: Int = 200) =
        server.enqueue(MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build())

    private fun take(): RecordedRequest = server.takeRequest()
    private fun RecordedRequest.bodyJson(): JsonObject = Json.parseToJsonElement(body!!.utf8()).jsonObject

    private fun failure(block: suspend () -> Unit): ApiError =
        assertThrows(ApiError::class.java) { runBlocking { block() } }

    @Test fun startMapPostsAndReturnsJobId() = runBlocking {
        json("""{"job_id":"j-1"}""", 202)
        assertEquals("j-1", api.startMap("0948AB"))
        val r = take()
        assertEquals("POST", r.method)
        assertEquals("/api/printers/0948AB/map", r.url.encodedPath)
        assertEquals("Bearer tok-123", r.headers["Authorization"])
    }

    @Test fun startMapErrorsKeepTheirCodes() {
        for (code in listOf("already_running", "printer_busy", "printer_offline", "cert_changed")) {
            json("""{"error":"$code","message":"x"}""", 409)
            val e = failure { api.startMap("0948AB") }
            assertEquals(409, e.status)
            assertEquals(code, e.code)
        }
    }

    @Test fun mapStatusDecodes() = runBlocking {
        json("""{"state":"running","step":"Testing slot A2","slots":[{"label":"A1","ams_id":0,"tray_id":0,"global":0},
            {"label":"HT-A","ams_id":128,"tray_id":0,"global":512}],"calibrated":false,"observe":true,
            "problems":["A3: not confirmed"],"future":1}""")
        val m = api.mapStatus("0948AB")
        assertEquals("running", m.state)
        assertEquals("Testing slot A2", m.step)
        assertEquals(2, m.slots.size)
        assertEquals("HT-A", m.slots[1].label)
        assertEquals(128, m.slots[1].amsId)
        assertEquals(512, m.slots[1].global)
        assertFalse(m.calibrated)
        assertTrue(m.observe)
        assertEquals(listOf("A3: not confirmed"), m.problems)
        val r = take()
        assertEquals("GET", r.method)
        assertEquals("/api/printers/0948AB/map", r.url.encodedPath)
    }

    @Test fun mapStatusDecodesNotesAndAnOldResult() = runBlocking {
        json("""{"state":"done","problems":["Ext-L: the printer reported no slot"],"problems_old":true,
            "finished":1762600000.5,"notes":["numbered alike"]}""")
        val m = api.mapStatus("0948AB")
        assertTrue(m.problemsOld)
        assertEquals(1762600000.5, m.finished!!, 0.0)
        assertEquals(listOf("numbered alike"), m.notes)
    }

    @Test fun mapStatusFromAnOlderServerHasNoNotesAndIsNotOld() = runBlocking {
        json("""{"state":"failed","problems":["x"]}""")
        val m = api.mapStatus("0948AB")
        assertTrue(!m.problemsOld && m.notes.isEmpty() && m.finished == null)
        assertTrue(!m.stale && !m.suspect && m.schemeUnsettled == null)
    }

    @Test fun mapStatusDecodesStaleSuspectAndTheOpenScheme() = runBlocking {
        json("""{"state":"done","calibrated":true,"stale":true,"suspect":true,"scheme_unsettled":true}""")
        val m = api.mapStatus("0948AB")
        assertTrue(m.stale && m.suspect && m.schemeUnsettled == true)
    }

    @Test fun mapStatusDecodesTheOutcomeAndItsSentences() = runBlocking {
        json("""{"state":"failed","outcome":"failed","reason":"offline","outcome_text":"The last mapping failed.",
            "next_step":"Map again when the printer is on and online."}""")
        val m = api.mapStatus("0948AB")
        assertEquals("failed", m.outcome)
        assertEquals("offline", m.reason)
        assertEquals("The last mapping failed.", m.outcomeText)
        assertEquals("Map again when the printer is on and online.", m.nextStep)
    }

    @Test fun mapStatusFromAnOlderServerHasNoOutcome() = runBlocking {
        json("""{"state":"done"}""")
        val m = api.mapStatus("0948AB")
        assertNull(m.outcome)
        assertNull(m.reason)
        assertNull(m.outcomeText)
        assertNull(m.nextStep)
    }

    @Test fun mapStatusNoneHasDefaults() = runBlocking {
        json("""{"state":"none"}""")
        val m = api.mapStatus("0948AB")
        assertEquals("none", m.state)
        assertTrue(m.slots.isEmpty())
        assertTrue(m.problems.isEmpty())
    }

    private val loadJson = """{"spool":{"id":7,"location":"Garage H2D – AMS A1","filament":{"name":"Red","material":"PLA",
        "vendor":{"name":"SUNLU"}}},"slot":{"label":"A1","ams_id":0,"tray_id":0},
        "preset":{"filament_id":"P1234567","name":"SUNLU PLA Red @H2D 0.4"},"nozzle_mm":0.4,"nozzle_assumed":true,
        "confirmed":false,"problems":[]}"""

    @Test fun loadPostsSpoolAndDryRun() = runBlocking {
        json(loadJson)
        val r = api.load("0948AB", "A1", 7, dryRun = true)
        assertEquals("A1", r.slot.label)
        assertEquals("SUNLU PLA Red @H2D 0.4", r.preset!!.name)
        assertEquals("P1234567", r.preset!!.filamentId)
        assertEquals(0.4, r.nozzleMm!!, 0.0001)
        assertTrue(r.nozzleAssumed)
        assertFalse(r.confirmed)
        assertTrue(r.problems.isEmpty())
        assertEquals(7, r.spool!!["id"]!!.jsonPrimitive.int)
        val req = take()
        assertEquals("POST", req.method)
        assertEquals("/api/printers/0948AB/slots/A1/load", req.url.encodedPath)
        val b = req.bodyJson()
        assertEquals(7, b["spool_id"]!!.jsonPrimitive.int)
        assertTrue(b["dry_run"]!!.jsonPrimitive.boolean)
    }

    @Test fun loadDryRunToleratesNullConfirmedAndReadsMovedBack() = runBlocking {
        // the Task 6 server answers a dry run with "confirmed": null and lists the spools that go back
        json(loadJson.replace("\"confirmed\":false", "\"confirmed\":null")
            .replace("\"problems\":[]", "\"problems\":[],\"moved_back\":[{\"id\":3,\"location\":\"Shelf 1\"}]"))
        val r = api.load("0948AB", "A1", 7, dryRun = true)
        assertFalse(r.confirmed)
        assertEquals(listOf(MovedBack(3, "Shelf 1")), r.movedBack)
    }

    @Test fun loadConfirmSendsDryRunFalseAndReadsProblems() = runBlocking {
        json(loadJson.replace("\"confirmed\":false,\"problems\":[]", "\"confirmed\":false,\"problems\":[\"A1: not confirmed\"]"))
        val r = api.load("0948AB", "HT-A", 7, dryRun = false)
        assertEquals(listOf("A1: not confirmed"), r.problems)
        val req = take()
        assertEquals("/api/printers/0948AB/slots/HT-A/load", req.url.encodedPath)
        assertFalse(req.bodyJson()["dry_run"]!!.jsonPrimitive.boolean)
    }

    @Test fun loadErrorsKeepTheirCodes() {
        for (code in listOf("no_preset", "printer_busy", "printer_offline", "cert_changed", "needs_developer_mode", "write_refused")) {
            json("""{"error":"$code","message":"x"}""", 409)
            assertEquals(code, failure { api.load("0948AB", "A1", 7, dryRun = true) }.code)
        }
        json("""{"error":"not_found","message":"Garage H2D has no slot Z9"}""", 404)
        val e = failure { api.load("0948AB", "Z9", 7, dryRun = true) }
        assertEquals("not_found", e.code)
        assertEquals("Garage H2D has no slot Z9", e.message)
    }

    @Test fun unloadPostsDryRun() = runBlocking {
        json("""{"spool":{"id":7},"slot":{"label":"A1","ams_id":0,"tray_id":0},"location":"Shelf 2",
            "moved_back":[{"id":7,"location":"Shelf 2"}]}""")
        val r = api.unload("0948AB", "A1", dryRun = true)
        assertEquals("Shelf 2", r.location)
        assertEquals("A1", r.slot.label)
        assertEquals(listOf(MovedBack(7, "Shelf 2")), r.movedBack)
        val req = take()
        assertEquals("/api/printers/0948AB/slots/A1/unload", req.url.encodedPath)
        assertTrue(req.bodyJson()["dry_run"]!!.jsonPrimitive.boolean)
    }

    @Test fun usageListsEntries() = runBlocking {
        json("""{"entries":[{"id":"e2","at":"2026-11-01T14:10:00-05:00","job":"Benchy","grams":12.5,"spool_id":7,
            "slot":"A1","observe":false,"undone":false},
            {"id":17,"at":"2026-10-31T09:00:00-05:00","job":"Cube","grams":null,"spool_id":null,"slot":null,
            "observe":true,"undone":false,"error":"ambiguous_spool"}]}""")
        val list = api.usage("0948AB", days = 7)
        assertEquals(2, list.size)
        assertEquals("e2", list[0].id)
        assertEquals(12.5, list[0].grams!!, 0.0001)
        assertEquals(7, list[0].spoolId)
        assertEquals("A1", list[0].slot)
        assertNull(list[0].error)
        assertEquals("17", list[1].id)
        assertNull(list[1].grams)
        assertNull(list[1].spoolId)
        assertTrue(list[1].observe)
        assertEquals("ambiguous_spool", list[1].error)
        val req = take()
        assertEquals("GET", req.method)
        assertEquals("/api/printers/0948AB/usage", req.url.encodedPath)
        assertEquals("7", req.url.queryParameter("days"))
    }

    @Test fun undoPostsAndReturnsTheEntry() = runBlocking {
        json("""{"entry":{"id":"e2","at":"2026-11-01T14:10:00-05:00","job":"Benchy","grams":12.5,"spool_id":7,
            "slot":"A1","observe":false,"undone":true}}""")
        val e = api.undoUsage("e2")
        assertTrue(e.undone)
        val req = take()
        assertEquals("POST", req.method)
        assertEquals("/api/usage/e2/undo", req.url.encodedPath)
    }

    @Test fun undoErrorsKeepTheirCodes() {
        for (code in listOf("too_old", "already_undone", "nothing_to_undo")) {
            json("""{"error":"$code","message":"x"}""", 409)
            assertEquals(code, failure { api.undoUsage("e2") }.code)
        }
    }

    @Test fun printerStateMayBeCertChanged() = runBlocking {
        json("""{"printers":[{"id":"A","name":"A","serial":"A","configured":true,"state":"cert_changed"}]}""")
        assertEquals("cert_changed", api.printers()[0].state)
    }

    // ---- map by loading filament ----

    private val manualState = """{"session":"s1","open":true,"dual_nozzle":true,"reports_loads":true,
        "step":{"position":{"id":"A2","label":"A2"},"say":"Load A2 to the nozzle, then wait.",
          "seen":{"reported":{"ams_id":0,"tray_id":1},"reported_label":"A2","nozzle":"left","nozzle_reported":true,"settled":true},
          "ask":"The printer now reports A2 loaded. Is that the A2 you loaded?"},
        "positions":[{"id":"A1","label":"A1","status":"confirmed","reported_label":"A1","nozzle":null,"at":"x"},
          {"id":"A2","label":"A2","status":"pending","reported_label":null,"nozzle":null,"at":null}],
        "summary":"1 of 2 positions confirmed.","offer_report":false}"""

    @Test fun manualStartPostsAndDecodesTheState() = runBlocking {
        json(manualState)
        val m = api.manualStart("0948AB")
        val r = take()
        assertEquals("POST", r.method)
        assertEquals("/api/printers/0948AB/manual-map/start", r.url.encodedPath)
        assertEquals("s1", m.session)
        assertTrue(m.open && m.dualNozzle && m.reportsLoads)
        val seen = m.step!!.seen!!
        assertEquals("A2", seen.reportedLabel)
        assertTrue(seen.settled && seen.nozzleReported)
        assertEquals("left", seen.nozzle)
        assertEquals(0, seen.reported["ams_id"]!!.jsonPrimitive.int)
        assertEquals("confirmed", m.positions[0].status)
        assertTrue(m.choices.isEmpty())
    }

    @Test fun manualStateGetsAndA404IsNone() = runBlocking {
        json(manualState)
        api.manualState("0948AB")
        val r = take()
        assertEquals("GET", r.method)
        assertEquals("/api/printers/0948AB/manual-map", r.url.encodedPath)
        json("""{"error":"none","message":"No manual mapping was started for this printer."}""", 404)
        assertEquals("none", failure { api.manualState("0948AB") }.code)
    }

    @Test fun manualConfirmSendsTheReportedLoadUnchanged() = runBlocking {
        json(manualState)
        val reported = JsonObject(mapOf("label" to kotlinx.serialization.json.JsonPrimitive("lane2")))
        api.manualConfirm("0948AB", "s1", "C1", reported, null, byHand = false)
        val r = take()
        assertEquals("/api/printers/0948AB/manual-map/confirm", r.url.encodedPath)
        val b = r.bodyJson()
        assertEquals("s1", b["session"]!!.jsonPrimitive.content)
        assertEquals("C1", b["position"]!!.jsonPrimitive.content)
        assertEquals(reported, b["reported"])
        assertEquals(kotlinx.serialization.json.JsonNull, b["nozzle"])
        assertFalse("by_hand" in b)
    }

    @Test fun manualConfirmByHandAndWithANozzle() = runBlocking {
        json(manualState)
        api.manualConfirm("0948AB", "s1", "A1", JsonObject(emptyMap()), "right", byHand = true)
        val b = take().bodyJson()
        assertEquals("right", b["nozzle"]!!.jsonPrimitive.content)
        assertTrue(b["by_hand"]!!.jsonPrimitive.boolean)
    }

    @Test fun manualSkipStopAndOffer() = runBlocking {
        json(manualState)
        api.manualSkip("0948AB", "s1", "A2")
        var r = take()
        assertEquals("/api/printers/0948AB/manual-map/skip", r.url.encodedPath)
        assertEquals("A2", r.bodyJson()["position"]!!.jsonPrimitive.content)
        json(manualState.replace("\"open\":true", "\"open\":false"))
        assertFalse(api.manualStop("0948AB", "s1").open)
        r = take()
        assertEquals("/api/printers/0948AB/manual-map/stop", r.url.encodedPath)
        assertEquals("s1", r.bodyJson()["session"]!!.jsonPrimitive.content)
        json("""{"share":false,"message":"Noted: this map is not shared."}""")
        assertEquals("Noted: this map is not shared.", api.manualOffer("0948AB", false).message)
        r = take()
        assertEquals("/api/printers/0948AB/manual-map/offer", r.url.encodedPath)
        assertFalse(r.bodyJson()["share"]!!.jsonPrimitive.boolean)
    }

    @Test fun manualStateWithoutLoadReportsHasChoices() = runBlocking {
        json("""{"session":"s1","open":true,"dual_nozzle":false,"reports_loads":false,"step":{"position":{"id":"A1",
            "label":"A1"},"say":"x","seen":null,"ask":null},"positions":[],"summary":"","offer_report":false,
            "choices":[{"reported":{"ams_id":0,"tray_id":0},"label":"A1"}]}""")
        val m = api.manualState("0948AB")
        assertFalse(m.reportsLoads)
        assertEquals("A1", m.choices.single().label)
        assertNull(m.step!!.seen)
    }

    @Test fun printerFamilyDefaultsToBambu() {
        val j = Json { ignoreUnknownKeys = true }
        assertEquals("bambu", j.decodeFromString(Printer.serializer(), """{"id":"a","name":"n","serial":"s"}""").family)
        assertEquals("klipper",
            j.decodeFromString(Printer.serializer(), """{"id":"a","name":"n","serial":"s","family":"klipper"}""").family)
    }
}
