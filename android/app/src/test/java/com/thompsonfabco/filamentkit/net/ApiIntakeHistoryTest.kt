package com.thompsonfabco.filamentkit.net

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import okhttp3.tls.HandshakeCertificates
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress

/** The intake history routes (2026-11-12-1031 handoff, API v1) and the add's read_id. */
class ApiIntakeHistoryTest {
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

    private val summary = """{"id":"a1b2c3d4e5f6","at":"2026-11-12T10:31:05-05:00","source":"phone","state":"detected",
        "photos":2,"undoable":false,"spools":[{"spool_id":41,"filament_id":12,"vendor":"SUNLU","name":"PLA+ Grey",
        "material":"PLA","color_hex":"8A8D8F"}]"""

    private val record = """$summary,"read":{"items":[{"vendor":"SUNLU"}],"hint":"grey"},
        "saved":[{"item":0,"spool_ids":[41,42],"values":{"vendor":"SUNLU","nozzle":210,"nozzle_range":[190,230]}}],
        "weight":1234.5,"tag":"04a1b2c3d4e5f6",
        "revisions":[{"n":1,"at":"2026-11-12T11:00:00-05:00","by":"ai","device":"Pixel","note":"brand is Polymaker",
        "changes":[{"spool_id":41,"field":"vendor","old":"SUNLU","new":"Polymaker"}],
        "filaments":{"from":12,"to":31,"created":true,"orphaned":[12]},"undone":false}],"future":1}"""

    @Test fun addSendsTheReadIdOnlyWhenGiven() = runBlocking {
        json("""{"spool_ids":[41],"lines":["ok"],"dry":false,"history_id":"a1b2"}""")
        val r = api.add(JsonArray(emptyList()), false, null, "r-9")
        assertEquals("a1b2", r.historyId)
        assertEquals(JsonPrimitive("r-9"), take().bodyJson()["read_id"])
        json("""{"spool_ids":[],"lines":[],"dry":true}""")
        assertNull(api.add(JsonArray(emptyList()), true, null).historyId)
        assertFalse("read_id" in take().bodyJson())
    }

    @Test fun historyListDecodes() = runBlocking {
        json("""{"keep":20,"count":1,"photo_bytes":3145728,"ai":true,"records":[$summary}]}""")
        val h = api.intakeHistory()
        assertEquals(20, h.keep)
        assertEquals(3145728L, h.photoBytes)
        assertTrue(h.ai)
        val r = h.records.single()
        assertEquals("a1b2c3d4e5f6", r.id)
        assertEquals(2, r.photos)
        assertEquals("SUNLU", r.spools.single().vendor)
        val q = take()
        assertEquals("GET", q.method)
        assertEquals("/api/intake/history", q.url.encodedPath)
        assertEquals("Bearer tok-123", q.headers["Authorization"])
    }

    @Test fun recordDecodesRevisionsAndALeftOverFilament() = runBlocking {
        json(record)
        val r = api.intakeRecord("a1b2c3d4e5f6")
        assertEquals(listOf(41, 42), r.saved.single().spoolIds)
        assertEquals(1234.5, r.weight!!, 0.0)
        val rev = r.revisions.single()
        assertEquals("brand is Polymaker", rev.note)
        assertEquals(JsonPrimitive("Polymaker"), rev.changes.single().new)
        assertEquals(listOf(12), rev.filaments!!.orphaned)
        assertTrue(rev.filaments!!.created)
        assertEquals("/api/intake/history/a1b2c3d4e5f6", take().url.encodedPath)
    }

    @Test fun aRecordSavedByHandHasNoReadOrWeight() = runBlocking {
        json("""{"id":"x","photos":0,"read":null,"saved":[],"weight":null,"tag":null,"revisions":[]}""")
        val r = api.intakeRecord("x")
        assertNull(r.read)
        assertNull(r.weight)
        assertNull(r.tag)
    }

    @Test fun photoComesBackAsBytes() = runBlocking {
        server.enqueue(MockResponse.Builder().code(200).addHeader("Content-Type", "image/jpeg").body("JPEGDATA").build())
        assertArrayEquals("JPEGDATA".toByteArray(), api.intakePhoto("a1b2", 2))
        val q = take()
        assertEquals("/api/intake/history/a1b2/photos/2", q.url.encodedPath)
        assertEquals("Bearer tok-123", q.headers["Authorization"])
    }

    @Test fun aMissingPhotoIsNotFound() {
        json("""{"error":"not_found","message":"no such photo"}""", 404)
        val e = assertThrows(ApiError::class.java) { runBlocking { api.intakePhoto("a1b2", 3) } }
        assertEquals("not_found", e.code)
    }

    @Test fun reviseSendsTheNoteAndReadsTheProposal() = runBlocking {
        json("""{"proposal":"p-7f3a","item":0,"before":{"vendor":"SUNLU"},"after":{"vendor":"Polymaker"},
            "changes":["vendor"],"no_photo":true}""")
        val p = api.reviseIntake("a1b2", "brand is Polymaker", null)
        assertEquals("p-7f3a", p.proposal)
        assertEquals(listOf("vendor"), p.changes)
        assertTrue(p.noPhoto)
        val q = take()
        assertEquals("POST", q.method)
        assertEquals("/api/intake/history/a1b2/revise", q.url.encodedPath)
        assertEquals(buildJsonObject { put("note", "brand is Polymaker") }, q.bodyJson())
    }

    @Test fun reviseRefusalsKeepTheirCodes() {
        for ((status, code) in listOf(409 to "ai_off", 429 to "daily_cap")) {
            json("""{"error":"$code","message":"x"}""", status)
            val e = assertThrows(ApiError::class.java) { runBlocking { api.reviseIntake("a1b2", "n", 0) } }
            assertEquals(code, e.code)
        }
    }

    @Test fun applyProposalAndValuesAndUndo() = runBlocking {
        val full = record
        json(full)
        api.applyProposal("a1b2", "p-7f3a")
        var q = take()
        assertEquals("/api/intake/history/a1b2/apply", q.url.encodedPath)
        assertEquals(buildJsonObject { put("proposal", "p-7f3a") }, q.bodyJson())

        json(full)
        api.applyValues("a1b2", 0, buildJsonObject { put("nozzle", 215) }, listOf(41))
        q = take()
        assertEquals(Json.parseToJsonElement("""{"item":0,"values":{"nozzle":215},"spool_ids":[41]}"""), q.bodyJson())

        json(full)
        api.undoIntake("a1b2", 1)
        q = take()
        assertEquals("/api/intake/history/a1b2/undo", q.url.encodedPath)
        assertEquals(buildJsonObject { put("revision", 1) }, q.bodyJson())
    }

    @Test fun aStaleProposalKeepsItsCode() {
        json("""{"error":"stale","message":"x"}""", 409)
        val e = assertThrows(ApiError::class.java) { runBlocking { api.applyProposal("a1b2", "p") } }
        assertEquals("stale", e.code)
    }
}
