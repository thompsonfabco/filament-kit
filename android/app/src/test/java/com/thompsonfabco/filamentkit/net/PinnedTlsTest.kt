package com.thompsonfabco.filamentkit.net

import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.time.Duration

class PinnedTlsTest {
    private val servers = mutableListOf<MockWebServer>()

    @After
    fun tearDown() = servers.forEach { it.close() }

    private fun start(cert: HeldCertificate) = httpsServer(cert).also { servers += it }

    @Test
    fun pinnedCertIsTrustedEvenThoughHostNameDiffers() {
        val cert = serverCert("pat.local")
        val server = start(cert)
        // URL host is 127.0.0.1 but the cert only names pat.local: the host check is skipped for the pinned cert.
        val url = server.url("/api/info")
        assertEquals("127.0.0.1", url.host)

        pinnedClient(cert.fingerprint()).newCall(Request.Builder().url(url).build()).execute().use {
            assertEquals(200, it.code)
            assertEquals("""{"name":"kit"}""", it.body.string())
        }
    }

    @Test
    fun differentCertRaisesFingerprintMismatchWithBothFingerprints() {
        val pinned = serverCert("pat.local")
        val other = serverCert("pat.local")
        val server = start(other)

        val e = assertThrows(FingerprintMismatch::class.java) {
            pinnedClient(pinned.fingerprint()).newCall(Request.Builder().url(server.url("/api/info")).build()).execute()
        }

        assertEquals(pinned.fingerprint(), e.expected)
        assertEquals(other.fingerprint(), e.actual)
        assertNotEquals(e.expected, e.actual)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun fingerprintMismatchIsAnIOException() {
        assertTrue(IOException::class.java.isAssignableFrom(FingerprintMismatch::class.java))
    }

    @Test
    fun pinnedClientKeepsBaseClientSettings() {
        val base = OkHttpClient.Builder().connectTimeout(Duration.ofSeconds(2)).build()
        val client = pinnedClient("ab".repeat(32), base)
        assertEquals(2_000, client.connectTimeoutMillis)
    }

    @Test
    fun probeFingerprintReadsThePresentedCert() {
        val cert = serverCert("pat.local")
        val server = start(cert)

        assertEquals(cert.fingerprint(), probeFingerprint("127.0.0.1", server.port))
    }
}
