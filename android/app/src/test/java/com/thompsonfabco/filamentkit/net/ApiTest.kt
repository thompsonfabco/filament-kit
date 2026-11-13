package com.thompsonfabco.filamentkit.net

import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
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
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.net.InetAddress

class ApiTest {
    @get:Rule val tmp = TemporaryFolder()

    private val cert = serverCert()
    private val server = MockWebServer().also {
        it.useHttps(HandshakeCertificates.Builder().heldCertificate(cert).build().sslSocketFactory())
        it.start(InetAddress.getByName("127.0.0.1"), 0)
    }
    private var token: String? = "tok-123"
    private val api = Api(pinnedClient(cert.fingerprint()), { baseOf(server) }, { token })

    @After fun tearDown() = server.close()

    private fun baseOf(s: MockWebServer) = s.ipUrl("/").toString().trimEnd('/')

    private fun json(body: String, code: Int = 200) =
        server.enqueue(MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build())

    private fun take(): RecordedRequest = server.takeRequest()
    private fun RecordedRequest.bodyJson(): JsonObject = Json.parseToJsonElement(body!!.utf8()).jsonObject
    private fun RecordedRequest.path() = url.encodedPath
    private fun RecordedRequest.bearer() = headers["Authorization"]

    private fun failure(block: suspend () -> Unit): ApiError =
        assertThrows(ApiError::class.java) { runBlocking { block() } }

    @Test fun infoNeedsNoBearer() = runBlocking {
        json("""{"name":"Kit","version":"1.2","api":1,"apk_version":"7","extra":"ignored"}""")
        val info = api.info()
        assertEquals("Kit", info.name)
        assertEquals(1, info.api)
        assertEquals("7", info.apkVersion)
        val r = take()
        assertEquals("GET", r.method)
        assertEquals("/api/info", r.path())
        assertNull(r.bearer())
    }

    @Test fun infoApkVersionMayBeNull() = runBlocking {
        json("""{"name":"Kit","version":"1.2","api":1,"apk_version":null}""")
        assertNull(api.info().apkVersion)
    }

    @Test fun pairPostsCodeWithoutBearer() = runBlocking {
        json("""{"token":"abc"}""")
        assertEquals("abc", api.pair("123456"))
        val r = take()
        assertEquals("POST", r.method)
        assertEquals("/api/pair", r.path())
        assertNull(r.bearer())
        assertEquals("123456", r.bodyJson()["code"]!!.jsonPrimitive.content)
    }

    @Test fun readSendsMultipartPhotosHintAndTag() = runBlocking {
        json("""{"items":[{"a":1}],"questions":["Which one?"],"tag":"4:77","usage":{"model":"m"},"read_id":"r1"}""")
        val res = api.read(listOf(byteArrayOf(1, 2, 3), byteArrayOf(4, 5)), "PLA box", "4:77")
        assertEquals("r1", res.readId)
        assertEquals(listOf("Which one?"), res.questions)
        assertEquals("4:77", res.tag)
        assertEquals(1, res.items.size)
        val r = take()
        assertEquals("POST", r.method)
        assertEquals("/api/intake/read", r.path())
        assertEquals("Bearer tok-123", r.bearer())
        assertTrue(r.headers["Content-Type"]!!.startsWith("multipart/form-data"))
        val body = r.body!!.utf8()
        assertEquals(2, Regex("""name="photo"""").findAll(body).count())
        assertEquals(2, Regex("""Content-Type: image/jpeg""").findAll(body).count())
        assertTrue(body.contains("""name="hint""""))
        assertTrue(body.contains("PLA box"))
        assertTrue(body.contains("""name="tag""""))
        assertTrue(body.contains("4:77"))
    }

    @Test fun readSaysWhichReaderAnsweredAndHowSure() = runBlocking {
        json("""{"items":[{"vendor":"SUNLU","confidence":0.86,"field_confidence":{"color":0.6},"color_name":"Charcoal",
            "color_family":"grey"}],"questions":[],"tag":null,"read_id":"r4","reader":"local","confidence":0.86,
            "unsure":false,"tier":"gpu","escalated":true,"note":"x","future":1}""")
        val res = api.read(listOf(byteArrayOf(1)), "", null)
        assertEquals("local", res.reader)
        assertEquals(0.86, res.confidence!!, 0.0)
        assertEquals("gpu", res.tier)
        assertTrue(res.escalated)
        assertTrue(!res.unsure)
        assertEquals("x", res.note)
        assertEquals("Charcoal", res.items[0].jsonObject["color_name"]!!.jsonPrimitive.content)
        take()
        json("""{"items":[],"questions":[],"tag":null,"read_id":"r5","reader":"cloud","confidence":null,"tier":null}""")
        val cloud = api.read(listOf(byteArrayOf(1)), "", null)
        assertEquals("cloud", cloud.reader)
        assertNull(cloud.confidence)
        take()
        Unit
    }

    @Test fun readOmitsTagWhenNull() = runBlocking {
        json("""{"items":[],"questions":[],"tag":null,"read_id":"r2"}""")
        val res = api.read(listOf(byteArrayOf(1)), "", null)
        assertNull(res.tag)
        assertTrue(!take().body!!.utf8().contains("""name="tag""""))
    }

    @Test fun readAcceptsTheServersTagObject() = runBlocking {
        // The real server echoes the tag as {"nfc_id": uid} (intake.read_labels), not as a bare string.
        json("""{"items":[],"questions":[],"tag":{"nfc_id":"4:77"},"usage":{"model":"m"},"read_id":"r3"}""")
        val res = api.read(listOf(byteArrayOf(1)), "", "4:77")
        assertEquals("4:77", res.tag)
        assertEquals("r3", res.readId)
    }

    @Test fun retryPostsToReadId() = runBlocking {
        json("""{"items":[],"questions":[],"tag":null,"read_id":"abc-1"}""")
        api.retry("abc-1")
        val r = take()
        assertEquals("POST", r.method)
        assertEquals("/api/intake/retry/abc-1", r.path())
        assertEquals("Bearer tok-123", r.bearer())
    }

    @Test fun addRoundTripsItemsWithUnknownFieldsUnchanged() = runBlocking {
        json("""{"spool_ids":[11,12],"lines":["a","b"],"dry":true}""")
        val items = Json.parseToJsonElement(
            """[{"vendor":"Acme","weird_field":{"deep":[1,2.5,null,"x"]},"qty":2,"flag":false}]""",
        ).jsonArray
        val res = api.add(items, dryRun = true, tag = "4:77")
        assertEquals(listOf(11, 12), res.spoolIds)
        assertEquals(listOf("a", "b"), res.lines)
        assertTrue(res.dry)
        val r = take()
        assertEquals("POST", r.method)
        assertEquals("/api/intake/add", r.path())
        assertEquals("Bearer tok-123", r.bearer())
        val sent = r.bodyJson()
        assertEquals(items, sent["items"])
        assertEquals(true, sent["dry_run"]!!.jsonPrimitive.boolean)
        assertEquals("4:77", sent["tag"]!!.jsonPrimitive.content)
    }

    @Test fun addSerializesDryRunFalseExplicitly() = runBlocking {
        json("""{"spool_ids":[1],"lines":[],"dry":false}""")
        api.add(JsonArray(emptyList()), dryRun = false, tag = null)
        val sent = take().bodyJson()
        assertEquals(false, sent["dry_run"]!!.jsonPrimitive.boolean)
        assertTrue("tag" !in sent)
    }

    @Test fun tagLookupFoundAndMissing() = runBlocking {
        json("""{"spool":{"id":5,"remaining_weight":100.5}}""")
        json("""{"spool":null}""")
        val found = api.tag("4:77:90:e")
        assertEquals(5, found!!["id"]!!.jsonPrimitive.content.toInt())
        val r = take()
        assertEquals("GET", r.method)
        assertEquals("/api/tags/4:77:90:e", r.path())
        assertEquals("Bearer tok-123", r.bearer())
        assertNull(api.tag("1:2"))
    }

    @Test fun linkBody() = runBlocking {
        json("""{"spool":{"id":9}}""")
        api.link(9, "4:77", force = true, dryRun = false, gross = 1234.5, location = "Shelf")
        val r = take()
        assertEquals("POST", r.method)
        assertEquals("/api/spools/9/link", r.path())
        assertEquals("Bearer tok-123", r.bearer())
        val b = r.bodyJson()
        assertEquals("4:77", b["tag"]!!.jsonPrimitive.content)
        assertEquals(true, b["force"]!!.jsonPrimitive.boolean)
        assertEquals(false, b["dry_run"]!!.jsonPrimitive.boolean)
        assertEquals(1234.5, b["gross"]!!.jsonPrimitive.content.toDouble(), 0.0)
        assertEquals("Shelf", b["location"]!!.jsonPrimitive.content)
    }

    @Test fun linkOmitsAbsentOptionals() = runBlocking {
        json("""{"spool":{"id":9}}""")
        api.link(9, "4:77", force = false, dryRun = true, gross = null, location = null)
        val b = take().bodyJson()
        assertEquals(setOf("tag", "force", "dry_run"), b.keys)
        assertEquals(true, b["dry_run"]!!.jsonPrimitive.boolean)
    }

    @Test fun updateBodyAndPatchMethod() = runBlocking {
        json("""{"spool":{"id":3}}""")
        api.update(3, gross = 900.0, remaining = null, location = "Box", empty = false, dryRun = true)
        val r = take()
        assertEquals("PATCH", r.method)
        assertEquals("/api/spools/3", r.path())
        assertEquals("Bearer tok-123", r.bearer())
        val b = r.bodyJson()
        assertEquals(setOf("gross", "location", "dry_run"), b.keys)
        assertEquals(true, b["dry_run"]!!.jsonPrimitive.boolean)
    }

    @Test fun updateEmptyIsSentWhenSet() = runBlocking {
        json("""{"spool":{"id":3}}""")
        api.update(3, gross = null, remaining = null, location = null, empty = true, dryRun = false)
        val b = take().bodyJson()
        assertEquals(true, b["empty"]!!.jsonPrimitive.boolean)
        assertEquals(false, b["dry_run"]!!.jsonPrimitive.boolean)
    }

    @Test fun searchQueryParams() = runBlocking {
        json("""{"spools":[{"id":1},{"id":2}]}""")
        json("""{"spools":[]}""")
        assertEquals(2, api.search("pla & red", sealedOnly = true).size)
        val r = take()
        assertEquals("GET", r.method)
        assertEquals("pla & red", r.url.queryParameter("q"))
        assertEquals("1", r.url.queryParameter("sealed"))
        assertEquals("Bearer tok-123", r.bearer())
        api.search("x", sealedOnly = false)
        assertNull(take().url.queryParameter("sealed"))
    }

    @Test fun locations() = runBlocking {
        json("""{"locations":["A","B"]}""")
        assertEquals(listOf("A", "B"), api.locations())
        val r = take()
        assertEquals("/api/locations", r.path())
        assertEquals("Bearer tok-123", r.bearer())
    }

    @Test fun downloadApkNeedsNoBearerAndWritesFile() = runBlocking {
        val bytes = ByteArray(5000) { it.toByte() }
        server.enqueue(MockResponse.Builder().code(200).body(okio.Buffer().write(bytes)).build())
        val f = tmp.newFile("a.apk")
        val seen = mutableListOf<Pair<Long, Long>>()
        api.downloadApk(f) { d, t -> seen += d to t }
        assertTrue(bytes.contentEquals(f.readBytes()))
        assertEquals(5000L to 5000L, seen.last())
        assertTrue(seen.all { it.second == 5000L })
        val r = take()
        assertEquals("/app.apk", r.path())
        assertNull(r.bearer())
    }

    @Test fun downloadApkErrorMapsToApiError() {
        json("""{"error":"not_found","message":"no app package"}""", 404)
        val f = tmp.newFile("b.apk")
        val e = failure { api.downloadApk(f) }
        assertEquals("not_found", e.code)
        assertEquals(0L, f.length())
    }

    @Test fun missingTokenSendsNoBearer() {
        token = null
        json("""{"error":"unauthorized","message":"pair first"}""", 401)
        val e = failure { api.locations() }
        assertEquals("unauthorized", e.code)
        assertNull(take().bearer())
    }

    @Test fun status401MapsToUnauthorized() {
        json("""{"error":"unauthorized","message":"revoked"}""", 401)
        val e = failure { api.locations() }
        assertEquals(401, e.status)
        assertEquals("unauthorized", e.code)
        assertEquals("revoked", e.message)
    }

    @Test fun status401WithNonJsonBodyIsStillUnauthorized() {
        server.enqueue(MockResponse.Builder().code(401).body("nope").build())
        assertEquals("unauthorized", failure { api.locations() }.code)
    }

    @Test fun tagConflictKeepsReasonAndOtherSpool() {
        json(
            """{"error":"tag_conflict","message":"already linked","reason":"other_spool","other_spool":{"id":4}}""",
            409,
        )
        val e = failure { api.link(1, "4:7", false, true, null, null) }
        assertEquals(409, e.status)
        assertEquals("tag_conflict", e.code)
        assertEquals("already linked", e.message)
        assertEquals("other_spool", e.extra["reason"]!!.jsonPrimitive.content)
        assertEquals(4, e.extra["other_spool"]!!.jsonObject["id"]!!.jsonPrimitive.content.toInt())
        assertTrue("error" !in e.extra && "message" !in e.extra)
    }

    @Test fun spoolmanErrorKeepsPartialSpoolIds() {
        json("""{"error":"spoolman_error","message":"boom","partial_spool_ids":[7,8]}""", 502)
        val e = failure { api.add(JsonArray(emptyList()), false, null) }
        assertEquals("spoolman_error", e.code)
        assertEquals(listOf("7", "8"), e.extra["partial_spool_ids"]!!.jsonArray.map { it.jsonPrimitive.content })
    }

    @Test fun readErrorsKeepReadId() {
        json("""{"error":"rate_limited","message":"slow down","read_id":"rid9"}""", 502)
        val e = failure { api.read(listOf(byteArrayOf(1)), "", null) }
        assertEquals("rate_limited", e.code)
        assertEquals("rid9", e.extra["read_id"]!!.jsonPrimitive.content)
    }

    @Test fun dailyCapAndUnreachableCodes() {
        json("""{"error":"daily_cap","message":"limit"}""", 429)
        assertEquals("daily_cap", failure { api.locations() }.code)
        json("""{"error":"spoolman_unreachable","message":"down"}""", 503)
        assertEquals("spoolman_unreachable", failure { api.locations() }.code)
    }

    @Test fun unparseableErrorBodyGetsGenericCode() {
        server.enqueue(MockResponse.Builder().code(500).body("<html>oops</html>").build())
        val e = failure { api.locations() }
        assertEquals(500, e.status)
        assertEquals("internal", e.code)
        assertTrue(e.message.isNotBlank())
    }

    @Test fun refusedConnectionIsOffline() {
        val port = server.port
        server.close()
        val offline = Api(pinnedClient(cert.fingerprint()), { "https://127.0.0.1:$port" }, { token })
        val e = failure { offline.locations() }
        assertEquals(0, e.status)
        assertEquals("offline", e.code)
    }

    @Test fun refusedConnectionWithoutTheLocalNetworkPermissionSaysSo() {
        val port = server.port
        server.close()
        val blocked = Api(pinnedClient(cert.fingerprint()), { "https://127.0.0.1:$port" }, { token }, localNetworkMissing = { true })
        val e = failure { blocked.locations() }
        assertEquals("local_network", e.code)
        assertEquals(LOCAL_NETWORK_MESSAGE, e.message)
    }

    @Test fun aCancelledDownloadStopsReadingAndLeavesNoFile() = runBlocking {
        server.enqueue(
            MockResponse.Builder().code(200).body(okio.Buffer().write(ByteArray(2_000_000)))
                .throttleBody(64 * 1024, 100, java.util.concurrent.TimeUnit.MILLISECONDS).build(),
        )
        val f = tmp.newFile("slow.apk")
        f.delete()
        var written = 0L
        val job = kotlinx.coroutines.GlobalScope.launch(kotlinx.coroutines.Dispatchers.Default) {
            api.downloadApk(f) { done, _ -> written = done }
        }
        while (written == 0L) kotlinx.coroutines.delay(10)
        kotlinx.coroutines.withTimeout(5_000) { job.cancelAndJoin() }
        assertTrue(job.isCancelled)
        assertTrue("it stopped well before the end", written < 2_000_000)
        assertFalse(f.exists())
        assertFalse(java.io.File(f.parentFile, f.name + ".part").exists())
    }

    @Test fun downloadApkWriteFailureIsNotOffline() {
        val bytes = ByteArray(5000) { it.toByte() }
        server.enqueue(MockResponse.Builder().code(200).body(okio.Buffer().write(bytes)).build())
        val blocker = tmp.newFile("not-a-dir")
        val e = failure { api.downloadApk(java.io.File(blocker, "c.apk")) }
        assertEquals("storage", e.code)
        assertTrue(e.message, "space" in e.message || "save" in e.message)
    }

    @Test fun fingerprintMismatchPropagatesUnwrapped() {
        val other = serverCert()
        val bad = Api(pinnedClient(other.fingerprint()), { baseOf(server) }, { token })
        val e = assertThrows(FingerprintMismatch::class.java) { runBlocking { bad.info() } }
        assertEquals(other.fingerprint(), e.expected)
        assertEquals(cert.fingerprint(), e.actual)
    }

    @Test fun baseUrlIsReadOnEveryCall() = runBlocking {
        json("""{"locations":[]}""")
        var base = "https://127.0.0.1:1"
        val dynamic = Api(pinnedClient(cert.fingerprint()), { base }, { token })
        assertEquals("offline", failure { dynamic.locations() }.code)
        base = baseOf(server)
        dynamic.locations()
        assertEquals(1, server.requestCount)
    }
}
