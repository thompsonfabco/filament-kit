package com.thompsonfabco.filamentkit.net

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.tls.HandshakeCertificates
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress

/** `/api/info` modules, `/api/filaments`, `/api/vendors` and the additive slot/unit fields. */
class ApiManualAddTest {
    private val cert = serverCert()
    private val server = MockWebServer().also {
        it.useHttps(HandshakeCertificates.Builder().heldCertificate(cert).build().sslSocketFactory())
        it.start(InetAddress.getByName("127.0.0.1"), 0)
    }
    private val api = Api(pinnedClient(cert.fingerprint()), { server.ipUrl("/").toString().trimEnd('/') }, { "tok-123" })
    private val json = Json { ignoreUnknownKeys = true }

    @After fun tearDown() = server.close()

    private fun reply(body: String) =
        server.enqueue(MockResponse.Builder().code(200).addHeader("Content-Type", "application/json").body(body).build())

    @Test fun infoModulesGateLabelReading() = runBlocking {
        reply("""{"name":"W","version":"0.2.0","api":1,"apk_version":"7","modules":["backup","spoolman"]}""")
        val off = api.info()
        assertEquals(listOf("backup", "spoolman"), off.modules)
        assertFalse(off.labelReading)

        reply("""{"name":"W","version":"0.2.0","api":1,"modules":["ai_intake","spoolman"]}""")
        assertTrue(api.info().labelReading)
    }

    @Test fun anOlderServerWithoutModulesStillReadsLabels() = runBlocking {
        reply("""{"name":"W","version":"0.1.0","api":1}""")
        val info = api.info()
        assertNull(info.modules)
        assertTrue(info.labelReading)
    }

    @Test fun filamentsSendTheQueryAndKeepNulls() = runBlocking {
        reply("""{"filaments":[{"id":3,"vendor":"Elegoo","name":"PLA Red","material":"PLA","density":1.24,
            "net":1000,"tare":160,"color_hex":"cc0000","nozzle":210,"bed":60,"spools":2,"future":1},
            {"id":4,"vendor":"","name":"Mystery","material":"PETG","density":1.27,"net":null,"tare":null,
            "color_hex":null,"nozzle":null,"bed":null,"spools":0}]}""")
        val list = api.filaments("sunlu petg")
        val r = server.takeRequest()
        assertEquals("/api/filaments", r.url.encodedPath)
        assertEquals("sunlu petg", r.url.queryParameter("q"))
        assertEquals("Bearer tok-123", r.headers["Authorization"])
        assertEquals(2, list.size)
        assertEquals(FilamentChoice(3, "Elegoo", "PLA Red", "PLA", 1.24, 1000.0, 160.0, "cc0000", 210.0, 60.0, 2), list[0])
        assertNull(list[1].net)
        assertNull(list[1].tare)
    }

    @Test fun aBlankFilamentQueryIsLeftOut() = runBlocking {
        reply("""{"filaments":[]}""")
        assertTrue(api.filaments("  ").isEmpty())
        assertNull(server.takeRequest().url.queryParameter("q"))
    }

    @Test fun vendorsCarryTheirTare() = runBlocking {
        reply("""{"vendors":[{"id":1,"name":"Elegoo","tare":160},{"id":2,"name":"SUNLU","tare":null}]}""")
        assertEquals(listOf(VendorChoice(1, "Elegoo", 160.0), VendorChoice(2, "SUNLU", null)), api.vendors())
        assertEquals("/api/vendors", server.takeRequest().url.encodedPath)
    }

    @Test fun slotsAndUnitsParseWithTheNewFields() {
        val u = json.decodeFromString<AmsUnit>(
            """{"unit":254,"label":"Ext-L","kind":"ext","type_name":"External","say":["external","left"],
            "slots":[{"slot":0,"label":"Ext-L","say":["external","left"],"present":true,"reading":null,
            "type":"PLA","color_hex":"FFFFFF","preset_id":"GFA00","active":false,"spool":null}]}""",
        )
        assertEquals("External", u.typeName)
        assertEquals(listOf("external", "left"), u.say)
        val s = u.slots.single()
        assertEquals(listOf("external", "left"), s.say)
        assertEquals(true, s.present)
        assertNull(s.reading)
    }

    @Test fun slotsAndUnitsParseWithoutTheNewFields() {
        val u = json.decodeFromString<AmsUnit>(
            """{"unit":255,"label":"Ext","kind":"ext","slots":[{"slot":0,"label":"Ext","type":"","color_hex":""}]}""",
        )
        assertEquals("", u.typeName)
        assertTrue(u.say.isEmpty())
        val s = u.slots.single()
        assertTrue(s.say.isEmpty())
        assertNull(s.present)
        assertNull(s.reading)
    }

    @Test fun sayAsOneTextIsSplitIntoWords() {
        val s = json.decodeFromString<AmsSlot>("""{"slot":0,"label":"Ext-R","say":"external right","present":"x"}""")
        assertEquals(listOf("external", "right"), s.say)
        assertNull(s.present)
    }
}
