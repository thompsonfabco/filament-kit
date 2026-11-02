package com.thompsonfabco.filamentkit.net

import androidx.test.ext.junit.runners.AndroidJUnit4
import java.net.InetAddress
import java.security.MessageDigest
import javax.net.ssl.SSLContext
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.Request
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The pin check on Android's own TLS stack (Conscrypt), which wraps trust-manager failures differently from the JVM:
 * a changed server certificate must still reach callers as a bare [FingerprintMismatch] with both fingerprints.
 */
@RunWith(AndroidJUnit4::class)
class PinnedTlsDeviceTest {
    private val paired = cert()
    private val reinstalled = cert()
    private val server = MockWebServer()

    @After fun tearDown() = server.close()

    private fun cert(): HeldCertificate =
        HeldCertificate.Builder().commonName("kit.local").addSubjectAlternativeName("kit.local").build()

    /** Independent of the code under test: SHA-256 of the DER certificate, lowercase hex. */
    private fun HeldCertificate.fp(): String =
        MessageDigest.getInstance("SHA-256").digest(certificate.encoded).joinToString("") { "%02x".format(it) }

    private fun serve(cert: HeldCertificate) {
        server.useHttps(HandshakeCertificates.Builder().heldCertificate(cert).build().sslSocketFactory())
        repeat(3) {
            server.enqueue(MockResponse(code = 200, body = """{"name":"kit","version":"1","api":1,"apk_version":"1"}"""))
        }
        server.start(InetAddress.getByName("127.0.0.1"), 0)
    }

    private fun api(fingerprint: String) =
        Api(pinnedClient(fingerprint), { "https://127.0.0.1:${server.port}" }, { null })

    @Test fun runsOnConscrypt() {
        val provider = SSLContext.getInstance("TLS").provider.name
        assertTrue("TLS provider was $provider", provider.contains("Conscrypt") || provider == "AndroidOpenSSL")
    }

    @Test fun changedCertificateIsABareFingerprintMismatch() {
        serve(reinstalled)
        val client = pinnedClient(paired.fp())

        val e = assertThrows(FingerprintMismatch::class.java) {
            client.newCall(Request.Builder().url(server.url("/api/info")).build()).execute().close()
        }

        assertEquals(paired.fp(), e.expected)
        assertEquals(reinstalled.fp(), e.actual)
        assertEquals(0, server.requestCount)
    }

    @Test fun apiCallsSurfaceTheMismatchNotOffline() {
        serve(reinstalled)

        val e = assertThrows(FingerprintMismatch::class.java) { runBlocking { api(paired.fp()).info() } }

        assertEquals(paired.fp(), e.expected)
        assertEquals(reinstalled.fp(), e.actual)
    }

    @Test fun pairedCertificateIsTrustedByIpAddress() = runBlocking {
        serve(paired)

        val info = api(paired.fp()).info()

        assertEquals("kit", info.name)
        assertNull(server.takeRequest().headers["Authorization"])
    }
}
