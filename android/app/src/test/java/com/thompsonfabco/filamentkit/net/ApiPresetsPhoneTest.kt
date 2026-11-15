package com.thompsonfabco.filamentkit.net

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import okhttp3.tls.HandshakeCertificates
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.net.InetAddress

/** The Slicer presets routes the phone calls since S4.13 (`/api/profiles/uncovered`, `lines`, `build`), over pinned TLS. */
class ApiPresetsPhoneTest {
    private val cert = serverCert()
    private val server = MockWebServer().also {
        it.useHttps(HandshakeCertificates.Builder().heldCertificate(cert).build().sslSocketFactory())
        it.start(InetAddress.getByName("127.0.0.1"), 0)
    }
    private val api = Api(pinnedClient(cert.fingerprint()), { server.ipUrl("/").toString().trimEnd('/') }, { "tok-9" })

    @After fun tearDown() = server.close()

    private fun json(body: String, code: Int = 200) =
        server.enqueue(MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build())

    private fun RecordedRequest.bodyJson(): JsonObject = Json.parseToJsonElement(body!!.utf8()).jsonObject

    private val lineView = """{"line":"Example Filaments PolyTerra","line_id":"example--polyterra","vendor":"Example Filaments",
        "product":"PolyTerra","material":"PLA","filament_ids":[7],"bambu_parent":"Generic PLA","parent_source":"user",
        "notes":[],"output":"ok"}"""

    @Test fun uncoveredFilamentsDecodeWithTheBrandsLines() = runBlocking {
        json("""{"uncovered_filaments":[{"id":7,"vendor":"Example Filaments","name":"PolyTerra Pink","material":"PLA",
            "lines_for_vendor":["Example Filaments PolyTerra"]},{"id":9,"vendor":"Other","name":"X","material":null,"lines_for_vendor":[]}]}""")
        val list = api.uncoveredFilaments()
        val r = server.takeRequest()
        assertEquals("GET", r.method)
        assertEquals("/api/profiles/uncovered", r.url.encodedPath)
        assertEquals("Bearer tok-9", r.headers["Authorization"])
        assertEquals(listOf(7, 9), list.map { it.id })
        assertEquals(listOf("Example Filaments PolyTerra"), list[0].linesForVendor)
        assertEquals("", list[1].material)
    }

    @Test fun addingToALinePostsTheIdsToThatLinesRoute() = runBlocking {
        json(lineView)
        val line = api.addFilamentsToLine("Example Filaments PolyTerra", listOf(7))
        val r = server.takeRequest()
        assertEquals("POST", r.method)
        // the line's name is one path segment, so its spaces are encoded
        assertEquals("/api/profiles/lines/Example%20Filaments%20PolyTerra/filaments", r.url.encodedPath)
        assertEquals(listOf(7), r.bodyJson()["ids"]!!.jsonArray.map { it.jsonPrimitive.content.toInt() })
        assertEquals("example--polyterra", line.lineId)
    }

    @Test fun startingALinePostsNameBrandIdsAndTemplate() = runBlocking {
        json(lineView, 200)
        api.createLine("Example Filaments PolyTerra", "Example Filaments", listOf(7), "Generic PLA")
        val r = server.takeRequest()
        assertEquals("POST", r.method)
        assertEquals("/api/profiles/lines", r.url.encodedPath)
        val body = r.bodyJson()
        assertEquals("Example Filaments PolyTerra", body["name"]!!.jsonPrimitive.content)
        assertEquals("Example Filaments", body["vendor"]!!.jsonPrimitive.content)
        assertEquals("Generic PLA", body["bs_template"]!!.jsonPrimitive.content)
        assertEquals(listOf(7), body["ids"]!!.jsonArray.map { it.jsonPrimitive.content.toInt() })
    }

    @Test fun startingALineWithAnOrcaParentSendsItAndWithoutOneSendsNoKey() = runBlocking {
        json(lineView, 200)
        api.createLine("Example Filaments PolyTerra", "Example Filaments", listOf(7), "Generic PLA", "Generic PLA @Orca")
        assertEquals("Generic PLA @Orca", server.takeRequest().bodyJson()["orca_parent"]!!.jsonPrimitive.content)
        json(lineView, 200)
        api.createLine("Example Filaments PolyTerra", "Example Filaments", listOf(7), "Generic PLA")
        assertEquals(false, server.takeRequest().bodyJson().containsKey("orca_parent"))
    }

    @Test fun theOrcaParentsOfAMaterialAreReadFromTheOrcaParentsRoute() = runBlocking {
        json("""{"orca_parents":["Bambu PLA Basic @BBL X1C","Generic PLA"]}""")
        val list = api.orcaParents("PLA")
        val r = server.takeRequest()
        assertEquals("GET", r.method)
        assertEquals("/api/profiles/orca-parents", r.url.encodedPath)
        assertEquals("PLA", r.url.queryParameter("material"))
        assertEquals("Bearer tok-9", r.headers["Authorization"])
        assertEquals(listOf("Bambu PLA Basic @BBL X1C", "Generic PLA"), list.parents)
    }

    @Test fun noOrcaLibraryYetIsAnEmptyList() = runBlocking {
        json("""{"orca_parents":[]}""")
        assertEquals(emptyList<String>(), api.orcaParents("").parents)
    }

    @Test fun anUnpairedPhoneIsRefusedWith401OnTheOrcaParentsRoute() {
        json("""{"error":"unauthorized","message":"no token"}""", 401)
        val e = assertThrows(ApiError::class.java) { runBlocking { api.orcaParents("PLA") } }
        assertEquals(401, e.status)
    }

    @Test fun aTooLongMaterialIsA400NamingTheMaterialField() {
        json("""{"error":"bad_request","message":"material is too long","field":"material"}""", 400)
        val e = assertThrows(ApiError::class.java) { runBlocking { api.orcaParents("x".repeat(101)) } }
        assertEquals("bad_request", e.code)
        assertEquals("material", e.extra["field"]!!.jsonPrimitive.content)
    }

    @Test fun aRefusedOrcaParentOfANewLineNamesItsField() {
        json("""{"error":"bad_request","message":"orca_parent is not in the Orca library","field":"orca_parent"}""", 400)
        val e = assertThrows(ApiError::class.java) { runBlocking { api.createLine("X", "V", listOf(1), "Generic PLA", "Nope") } }
        assertEquals("orca_parent", e.extra["field"]!!.jsonPrimitive.content)
    }

    @Test fun aRefusalCarriesTheHubsMessageAndTheField() {
        json("""{"error":"bad_request","message":"a line named X already exists","field":"name"}""", 400)
        val e = assertThrows(ApiError::class.java) { runBlocking { api.createLine("X", "V", listOf(1), "Generic PLA") } }
        assertEquals("bad_request", e.code)
        assertEquals("a line named X already exists", e.message)
        assertEquals("name", e.extra["field"]!!.jsonPrimitive.content)
    }

    @Test fun theBackendAsksTheCurrentApiOnEveryCall() = runBlocking {
        val second = Api(pinnedClient(cert.fingerprint()), { server.ipUrl("/").toString().trimEnd('/') }, { "tok-10" })
        var current = api
        val backend = com.thompsonfabco.filamentkit.ui.presets.PresetsBackend.of { current }
        json("""{"requested":true,"last_build":"s1","output":"x"}""")
        backend.build()
        assertEquals("Bearer tok-9", server.takeRequest().headers["Authorization"])
        current = second
        json("""{"requested":true,"last_build":"s2","output":"x"}""")
        backend.build()
        assertEquals("Bearer tok-10", server.takeRequest().headers["Authorization"])
    }

    @Test fun buildNowPostsAnEmptyObjectToTheProfilesBuildRoute() = runBlocking {
        json("""{"requested":true,"last_build":"s1","output":"a build is requested"}""")
        val asked = api.buildPresets()
        val r = server.takeRequest()
        assertEquals("POST", r.method)
        assertEquals("/api/profiles/build", r.url.encodedPath)
        assertEquals(JsonObject(emptyMap()), r.bodyJson())
        assertEquals(true, asked.requested)
    }
}
