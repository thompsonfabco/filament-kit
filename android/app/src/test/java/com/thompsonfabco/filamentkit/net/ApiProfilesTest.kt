package com.thompsonfabco.filamentkit.net

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
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

/** The profiles, library and sync-status routes of the stage 4 contract, over pinned TLS. */
class ApiProfilesTest {
    private val cert = serverCert()
    private val server = MockWebServer().also {
        it.useHttps(HandshakeCertificates.Builder().heldCertificate(cert).build().sslSocketFactory())
        it.start(InetAddress.getByName("127.0.0.1"), 0)
    }
    private val api = Api(pinnedClient(cert.fingerprint()), { server.ipUrl("/").toString().trimEnd('/') }, { "tok-9" })

    @After fun tearDown() = server.close()

    private fun json(body: String, code: Int = 200) =
        server.enqueue(MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build())

    private fun take(): RecordedRequest = server.takeRequest()
    private fun RecordedRequest.bodyJson(): JsonObject = Json.parseToJsonElement(body!!.utf8()).jsonObject

    private fun failure(block: suspend () -> Unit): ApiError =
        assertThrows(ApiError::class.java) { runBlocking { block() } }

    @Test fun profileStatusReadsEveryField() = runBlocking {
        json(
            """{"lines":12,"presets":96,
            "build":{"stamp":"20261102T010203000000Z","live_hash":"ab12","created":"2026-11-02T01:02:03Z","presets":96,"problems":2},
            "last_attempt":{"at":"2026-11-02T01:02:03Z","ok":true,"error":null},
            "installed":{"stamp":"20261102T010203000000Z","at":1762045323.5},
            "pc":{"device_id":"pc-1","last_upload":"2026-11-02T00:59:00Z"},
            "library":{"version":7,"source":"updated","local":3,"last_check":{"at":"2026-11-01T22:00:00Z","ok":false,"error":"HTTP 404"}},
            "stale":["Old PLA @BBL H2D 0.4 nozzle"],"problems":["SUNLU PLA Matte: no parent"],"future":1}""",
        )
        val s = api.profileStatus()
        assertEquals(12, s.lines)
        assertEquals(96, s.presets)
        val b = s.build!!
        assertEquals("20261102T010203000000Z", b.stamp)
        assertEquals("ab12", b.liveHash)
        assertEquals("2026-11-02T01:02:03Z", b.created)
        assertEquals(96, b.presets)
        assertEquals(2, b.problems)
        assertTrue(s.lastAttempt!!.ok)
        assertNull(s.lastAttempt!!.error)
        assertEquals("20261102T010203000000Z", s.installed!!.stamp)
        assertEquals("a number time is kept as text", "1762045323.5", s.installed!!.at)
        assertEquals("pc-1", s.pc!!.deviceId)
        assertEquals("2026-11-02T00:59:00Z", s.pc!!.lastUpload)
        val lib = s.library!!
        assertEquals("7", lib.version)
        assertEquals("updated", lib.source)
        assertEquals(3, lib.local)
        assertFalse(lib.lastCheck!!.ok)
        assertEquals("HTTP 404", lib.lastCheck!!.error)
        assertEquals(listOf("Old PLA @BBL H2D 0.4 nozzle"), s.stale)
        assertEquals(listOf("SUNLU PLA Matte: no parent"), s.problems)
        val r = take()
        assertEquals("GET", r.method)
        assertEquals("/api/profiles/status", r.url.encodedPath)
        assertEquals("Bearer tok-9", r.headers["Authorization"])
    }

    @Test fun profileStatusBeforeAnyBuildOrSync() = runBlocking {
        json(
            """{"lines":0,"presets":0,"build":null,"last_attempt":{"at":"2026-11-02T01:00:00Z","ok":false,
            "error":"no system presets uploaded"},"installed":null,"pc":null,
            "library":{"version":"3","source":"bundled","local":0,"last_check":null},"stale":[],"problems":[]}""",
        )
        val s = api.profileStatus()
        assertNull(s.build)
        assertNull(s.installed)
        assertNull(s.pc)
        assertFalse(s.lastAttempt!!.ok)
        assertEquals("no system presets uploaded", s.lastAttempt!!.error)
        assertEquals("3", s.library!!.version)
        assertNull(s.library!!.lastCheck)
    }

    @Test fun linesAreListed() = runBlocking {
        json(
            """{"lines":[{"line_id":"sunlu--pla-plus","vendor":"SUNLU","product":"PLA+","material":"PLA",
            "bambu_parent":"Generic PLA","parent_source":"material","spoolman_ids":[3,9],"presets":8},
            {"line_id":"x--y","vendor":"X","product":"Y","material":"ABS","bambu_parent":null,"parent_source":"none",
            "spoolman_ids":[],"presets":0}]}""",
        )
        val lines = api.profileLines()
        assertEquals(2, lines.size)
        assertEquals(ProfileLine("sunlu--pla-plus", "SUNLU", "PLA+", "PLA", "Generic PLA", "material", listOf(3, 9), 8), lines[0])
        assertNull(lines[1].bambuParent)
        assertEquals("/api/profiles/lines", take().url.encodedPath)
    }

    @Test fun parentsAreAskedPerMaterial() = runBlocking {
        json("""{"parents":["Generic PLA","Bambu PLA Basic"],"synced":true}""")
        val p = api.parents("PLA+ CF")
        assertEquals(ParentList(listOf("Generic PLA", "Bambu PLA Basic"), true), p)
        val r = take()
        assertEquals("GET", r.method)
        assertEquals("/api/profiles/parents", r.url.encodedPath)
        assertEquals("PLA+ CF", r.url.queryParameter("material"))
    }

    @Test fun parentsBeforeTheFirstSync() = runBlocking {
        json("""{"parents":["Generic PLA"],"synced":false}""")
        assertFalse(api.parents("PLA").synced)
    }

    @Test fun proposeSendsVendorLineMaterial() = runBlocking {
        json("""{"line_id":"sunlu--pla-plus","line":"PLA+","bambu_parent":"SUNLU PLA+","parent_source":"brand","exists":true}""")
        val p = api.propose("SUNLU", "PLA+", "PLA")
        assertEquals(Proposal("sunlu--pla-plus", "PLA+", "SUNLU PLA+", "brand", true), p)
        val r = take()
        assertEquals("POST", r.method)
        assertEquals("/api/profiles/propose", r.url.encodedPath)
        val b = r.bodyJson()
        assertEquals("SUNLU", b["vendor"]!!.jsonPrimitive.content)
        assertEquals("PLA+", b["line"]!!.jsonPrimitive.content)
        assertEquals("PLA", b["material"]!!.jsonPrimitive.content)
    }

    @Test fun proposeWithNoParent() = runBlocking {
        json("""{"line_id":"x--y","line":"Y","bambu_parent":null,"parent_source":"none","exists":false}""")
        val p = api.propose("X", "Y", "Unobtainium")
        assertNull(p.bambuParent)
        assertFalse(p.exists)
    }

    @Test fun proposeBadRequestKeepsTheServerMessage() {
        json("""{"error":"bad_request","message":"vendor is required"}""", 400)
        val e = failure { api.propose("", "Y", "PLA") }
        assertEquals("bad_request", e.code)
        assertEquals("vendor is required", e.message)
    }

    @Test fun setLineParentPatchesTheLine() = runBlocking {
        json(
            """{"line":{"line_id":"sunlu--pla-plus","vendor":"SUNLU","product":"PLA+","material":"PLA",
            "bambu_parent":"SUNLU PLA+","parent_source":"user","spoolman_ids":[3],"presets":8}}""",
        )
        val line = api.setLineParent("sunlu--pla-plus", "SUNLU PLA+")
        assertEquals("user", line.parentSource)
        assertEquals("SUNLU PLA+", line.bambuParent)
        val r = take()
        assertEquals("PATCH", r.method)
        assertEquals("/api/profiles/lines/sunlu--pla-plus", r.url.encodedPath)
        assertEquals("SUNLU PLA+", r.bodyJson()["bambu_parent"]!!.jsonPrimitive.content)
    }

    @Test fun setLineParentErrors() {
        json("""{"error":"unknown_parent","message":"Bambu Studio has no preset named Foo"}""", 400)
        val e = failure { api.setLineParent("a--b", "Foo") }
        assertEquals("unknown_parent", e.code)
        assertEquals("Bambu Studio has no preset named Foo", e.message)
        json("""{"error":"not_found","message":"no line a--b"}""", 404)
        assertEquals("not_found", failure { api.setLineParent("a--b", "Generic PLA") }.code)
    }

    @Test fun addLocalProfilePostsTheEntryAsIs() = runBlocking {
        val entry = buildJsonObject {
            put("schema_version", 1)
            put("vendor", "SUNLU")
            put("product", "PLA+")
            put("material", "PLA")
            put("fields", buildJsonObject { put("filament_density", JsonArray(listOf(Json.parseToJsonElement("\"1.24\"")))) })
        }
        json("""{"entry":$entry,"line_id":"sunlu--pla-plus"}""", 201)
        val res = api.addLocalProfile(entry)
        assertEquals("sunlu--pla-plus", res.lineId)
        assertEquals(entry, res.entry)
        val r = take()
        assertEquals("POST", r.method)
        assertEquals("/api/library/local", r.url.encodedPath)
        assertEquals(entry, r.bodyJson())
    }

    @Test fun invalidEntryCarriesTheProblems() {
        json(
            """{"error":"invalid_entry","message":"the entry is not valid",
            "problems":["fields.filament_density '9' is outside 0.5-3.0 g/cm3","missing required key 'material'"]}""",
            400,
        )
        val e = failure { api.addLocalProfile(JsonObject(emptyMap())) }
        assertEquals("invalid_entry", e.code)
        assertEquals(
            listOf("fields.filament_density '9' is outside 0.5-3.0 g/cm3", "missing required key 'material'"),
            e.extra["problems"]!!.jsonArray.map { it.jsonPrimitive.content },
        )
    }
}
