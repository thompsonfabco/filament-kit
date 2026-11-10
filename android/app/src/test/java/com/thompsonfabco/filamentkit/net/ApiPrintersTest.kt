package com.thompsonfabco.filamentkit.net

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
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
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress

class ApiPrintersTest {
    private val cert = serverCert()
    private val server = MockWebServer().also {
        it.useHttps(HandshakeCertificates.Builder().heldCertificate(cert).build().sslSocketFactory())
        it.start(InetAddress.getByName("127.0.0.1"), 0)
    }
    private val client = pinnedClient(cert.fingerprint())
    private val api = Api(client, { server.ipUrl("/").toString().trimEnd('/') }, { "tok-123" })

    @After fun tearDown() = server.close()

    private fun json(body: String, code: Int = 200) =
        server.enqueue(MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build())

    private fun take(): RecordedRequest = server.takeRequest()
    private fun RecordedRequest.bodyJson(): JsonObject = Json.parseToJsonElement(body!!.utf8()).jsonObject

    private fun failure(block: suspend () -> Unit): ApiError =
        assertThrows(ApiError::class.java) { runBlocking { block() } }

    private val printerJson = """{"id":"0948AB","name":"Garage H2D","model":"H2D","serial":"0948AB","ip":"10.0.0.9",
        "configured":true,"state":"connected","camera":{"kind":"hls"},
        "summary":{"gcode_state":"RUNNING","percent":42,"remaining_min":31},"future":1}"""

    @Test fun editPrinterPatchesTheKeysAndReadsThePrinterBack() = runBlocking {
        json("""{"printer":$printerJson,"changed":["name","address"],"note":"this server does not reach it"}""")
        val changes = kotlinx.serialization.json.buildJsonObject {
            put("name", kotlinx.serialization.json.JsonPrimitive("Garage"))
            put("address", kotlinx.serialization.json.JsonPrimitive("10.0.0.9"))
        }
        val r = api.editPrinter("0948AB", changes)
        assertEquals("Garage H2D", r.printer.name)
        assertEquals(listOf("name", "address"), r.changed)
        assertEquals("this server does not reach it", r.note)
        val q = take()
        assertEquals("PATCH", q.method)
        assertEquals("/api/printers/0948AB", q.url.encodedPath)
        assertEquals("Bearer tok-123", q.headers["Authorization"])
        assertEquals(changes, q.bodyJson())
    }

    @Test fun editPrinterWithoutANoteHasNone() = runBlocking {
        json("""{"printer":$printerJson,"changed":["unpin"]}""")
        assertNull(api.editPrinter("0948AB", kotlinx.serialization.json.buildJsonObject { }).note)
    }

    @Test fun editPrinterRefusalsKeepTheServersSentence() {
        json("""{"error":"bad_request","message":"a Klipper printer has no Access Code"}""", 400)
        val e = failure { api.editPrinter("0948AB", kotlinx.serialization.json.buildJsonObject { }) }
        assertEquals("bad_request", e.code)
        assertEquals("a Klipper printer has no Access Code", e.message)
    }

    @Test fun removePrinterDeletes() = runBlocking {
        json("""{"ok":true,"id":"0948AB"}""")
        api.removePrinter("0948AB")
        val q = take()
        assertEquals("DELETE", q.method)
        assertEquals("/api/printers/0948AB", q.url.encodedPath)
        assertEquals("Bearer tok-123", q.headers["Authorization"])
    }

    @Test fun removePrinterNotFoundKeepsItsCode() {
        json("""{"error":"not_found","message":"no such printer"}""", 404)
        assertEquals("not_found", failure { api.removePrinter("0948AB") }.code)
    }

    @Test fun listsPrintersWithBearer() = runBlocking {
        json("""{"printers":[$printerJson,
            {"id":"01P","name":"01P","model":null,"serial":"01P","ip":null,"configured":false,"state":"not_configured",
             "camera":{"kind":null},"summary":{"gcode_state":"UNKNOWN","percent":0,"remaining_min":0}}]}""")
        val list = api.printers()
        assertEquals(2, list.size)
        val p = list[0]
        assertEquals("0948AB", p.id)
        assertEquals("Garage H2D", p.name)
        assertEquals("H2D", p.model)
        assertTrue(p.configured)
        assertEquals("connected", p.state)
        assertEquals("hls", p.camera.kind)
        assertEquals("RUNNING", p.summary!!.gcodeState)
        assertEquals(42, p.summary!!.percent)
        assertEquals(31, p.summary!!.remainingMin)
        assertNull(list[1].model)
        assertNull(list[1].camera.kind)
        assertFalse(list[1].configured)
        val r = take()
        assertEquals("GET", r.method)
        assertEquals("/api/printers", r.url.encodedPath)
        assertEquals("Bearer tok-123", r.headers["Authorization"])
    }

    @Test fun showsTheModelNameAndFallsBackToTheCode() = runBlocking {
        json("""{"printers":[
            {"id":"A","name":"Shop H2D","model":"O1D","model_name":"H2D","serial":"A","configured":true},
            {"id":"B","name":"Old server","model":"C12","serial":"B"},
            {"id":"C","name":"Unknown","model":"ZZ9","model_name":"ZZ9","serial":"C"},
            {"id":"D","name":"Nothing","model":null,"serial":"D"},
            {"id":"E","name":"Blank name","model":"N1","model_name":"","serial":"E"}]}""")
        val list = api.printers()
        assertEquals("O1D", list[0].model)
        assertEquals("H2D", list[0].shownModel)
        assertNull("an older server sends no model_name", list[1].modelName)
        assertEquals("C12", list[1].shownModel)
        assertEquals("ZZ9", list[2].shownModel)
        assertNull(list[3].shownModel)
        assertEquals("N1", list[4].shownModel)
    }

    @Test fun addPrinterPostsSerialCodeAndName() = runBlocking {
        json("""{"printer":$printerJson}""")
        val p = api.addPrinter("0948AB", "12345678", "Garage H2D")
        assertEquals("connected", p.state)
        val r = take()
        assertEquals("POST", r.method)
        assertEquals("/api/printers", r.url.encodedPath)
        val b = r.bodyJson()
        assertEquals("0948AB", b["serial"]!!.jsonPrimitive.content)
        assertEquals("12345678", b["access_code"]!!.jsonPrimitive.content)
        assertEquals("Garage H2D", b["name"]!!.jsonPrimitive.content)
    }

    @Test fun addPrinterOmitsBlankName() = runBlocking {
        json("""{"printer":$printerJson}""")
        api.addPrinter("0948AB", "12345678", null)
        assertFalse(take().bodyJson().containsKey("name"))
    }

    @Test fun addPrinterExistsIs409() {
        json("""{"error":"exists","message":"this printer is already set up"}""", 409)
        val e = failure { api.addPrinter("0948AB", "1", null) }
        assertEquals(409, e.status)
        assertEquals("exists", e.code)
    }

    @Test fun printerDetailDecodesFullStatus() = runBlocking {
        json("""{"printer":$printerJson,"status":{"gcode_state":"RUNNING","stage":"Printing","job":"Benchy",
            "percent":42,"layer":12,"total_layers":200,"remaining_min":31,"eta":"2026-11-01T14:10-05:00",
            "temps":{"nozzle":[{"current":220,"target":220},{"current":30,"target":0}],
                     "bed":{"current":60,"target":60},"chamber":null},
            "ams":[{"unit":0,"label":"A","kind":"ams","slots":[{"slot":0,"label":"A1","type":"PLA","color_hex":"FF0000",
                "active":true,"spool":{"id":7,"name":"SUNLU Red","material":"PLA","color_hex":"ff0000","remaining_weight":812.5}},
                {"slot":1,"label":"A2","type":"","color_hex":"","active":false,"spool":null}]},
              {"unit":128,"label":"HT-A","kind":"ams_ht","slots":[]}],
            "hms":[{"code":"0300_0100_0001_0007","text":"Printer alert HMS 0300_0100_0001_0007"}],
            "light":"on","updated":1761990000}}""")
        val d = api.printer("0948AB")
        assertEquals("Garage H2D", d.printer.name)
        val s = d.status!!
        assertEquals("Printing", s.stage)
        assertEquals("Benchy", s.job)
        assertEquals(12, s.layer)
        assertEquals(200, s.totalLayers)
        assertEquals("2026-11-01T14:10-05:00", s.eta)
        assertEquals(2, s.temps.nozzle.size)
        assertEquals(220.0, s.temps.nozzle[0].current!!, 0.001)
        assertEquals(60.0, s.temps.bed!!.target!!, 0.001)
        assertNull(s.temps.chamber)
        assertEquals("ams_ht", s.ams[1].kind)
        val slot = s.ams[0].slots[0]
        assertEquals("A1", slot.label)
        assertTrue(slot.active)
        assertEquals(812.5, slot.spool!!.remainingWeight!!, 0.001)
        assertNull(s.ams[0].slots[1].spool)
        assertEquals("0300_0100_0001_0007", s.hms[0].code)
        assertEquals("on", s.light)
        assertEquals(1761990000L, s.updated)
        assertEquals("/api/printers/0948AB", take().url.encodedPath)
    }

    @Test fun printerDetailAcceptsDecimalAndStringNumbers() = runBlocking {
        // Bambu reports carry decimals (bed_temper 64.0, 25.5) and numeric strings; none may fail the status
        json("""{"printer":$printerJson,"status":{"gcode_state":"RUNNING","percent":42.0,"layer":12.0,
            "total_layers":"200","remaining_min":31.0,"updated":1761990000.5,
            "temps":{"nozzle":[{"current":25.5,"target":0}],"bed":{"current":64.0,"target":60},
                     "chamber":{"current":"28.5","target":null}},
            "ams":[{"unit":0.0,"label":"A","kind":"ams","slots":[{"slot":1.0,"label":"A2","type":"PLA","color_hex":"",
                "active":false,"spool":{"id":7.0,"name":"x","material":"PLA","color_hex":"","remaining_weight":"812.5"}}]}]}}""")
        val s = api.printer("0948AB").status!!
        assertEquals(25.5, s.temps.nozzle[0].current!!, 0.001)
        assertEquals(0.0, s.temps.nozzle[0].target!!, 0.001)
        assertEquals(64.0, s.temps.bed!!.current!!, 0.001)
        assertEquals(60.0, s.temps.bed.target!!, 0.001)
        assertEquals(28.5, s.temps.chamber!!.current!!, 0.001)
        assertNull(s.temps.chamber.target)
        assertEquals(42, s.percent)
        assertEquals(12, s.layer)
        assertEquals(200, s.totalLayers)
        assertEquals(31, s.remainingMin)
        assertEquals(1, s.ams[0].slots[0].slot)
        assertEquals(7, s.ams[0].slots[0].spool!!.id)
        assertEquals(812.5, s.ams[0].slots[0].spool!!.remainingWeight!!, 0.001)
    }

    @Test fun listSummaryCarriesTheJob() = runBlocking {
        json("""{"printers":[{"id":"A","name":"A","serial":"A","configured":true,"state":"connected",
            "camera":{"kind":"hls"},"summary":{"gcode_state":"RUNNING","percent":42.0,"remaining_min":31,"job":"Benchy"}},
            {"id":"B","name":"B","serial":"B","summary":{"gcode_state":"IDLE","percent":0,"remaining_min":0,"job":null}}]}""")
        val list = api.printers()
        assertEquals("Benchy", list[0].summary!!.job)
        assertEquals(42, list[0].summary!!.percent)
        assertNull(list[1].summary!!.job)
    }

    @Test fun aPrinterWithoutASummaryDoesNotBreakTheList() = runBlocking {
        json("""{"printers":[{"id":"A","name":"A","serial":"A","configured":true,"state":"connected","summary":null},
            {"id":"B","name":"B","serial":"B","summary":{"gcode_state":"IDLE","percent":0,"remaining_min":0}}]}""")
        val list = api.printers()
        assertEquals(2, list.size)
        assertNull(list[0].summary)
        assertEquals("connected", list[0].state)
        assertEquals("IDLE", list[1].summary!!.gcodeState)
        json("""{"printer":{"id":"A","name":"A","serial":"A","state":"connected","summary":null}}""")
        assertNull(api.addPrinter("A", "12345678", null).summary)
    }

    @Test fun printerDetailStatusMayBeNull() = runBlocking {
        json("""{"printer":$printerJson,"status":null}""")
        assertNull(api.printer("0948AB").status)
    }

    @Test fun printerUnknownIs404() {
        json("""{"error":"not_found","message":"no such printer"}""", 404)
        assertEquals("not_found", failure { api.printer("nope") }.code)
    }

    @Test fun commandPostsAction() = runBlocking {
        json("""{"ok":true,"reply":{"ok":true,"reply":{"result":"success","command":"pause"}}}""")
        val r = api.command("0948AB", "pause")
        assertTrue(r.ok)
        val req = take()
        assertEquals("POST", req.method)
        assertEquals("/api/printers/0948AB/command", req.url.encodedPath)
        assertEquals("pause", req.bodyJson()["action"]!!.jsonPrimitive.content)
        assertEquals("Bearer tok-123", req.headers["Authorization"])
    }

    @Test fun commandOfflineIs409AndNoReplyIs504() {
        json("""{"error":"printer_offline","message":"the printer is offline"}""", 409)
        val off = failure { api.command("0948AB", "stop") }
        assertEquals(409, off.status)
        assertEquals("printer_offline", off.code)
        json("""{"error":"no_reply","message":"the printer did not answer in time"}""", 504)
        assertEquals("no_reply", failure { api.command("0948AB", "stop") }.code)
    }

    @Test fun cameraUrlsAndHeaders() {
        val base = server.ipUrl("/").toString().trimEnd('/')
        assertEquals("$base/api/printers/0948AB/camera/index.m3u8", api.cameraHlsUrl("0948AB"))
        assertEquals("$base/api/printers/0948AB/camera.mjpeg", api.cameraMjpegUrl("0948AB"))
        assertEquals(mapOf("Authorization" to "Bearer tok-123"), api.authHeaders())
        assertSame(client, api.client)
    }
}
