package com.thompsonfabco.filamentkit.net

import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.HttpUrl
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import java.net.InetAddress
import java.security.MessageDigest

internal fun serverCert(name: String = "pat.local"): HeldCertificate =
    HeldCertificate.Builder().commonName(name).addSubjectAlternativeName(name).build()

/** Computed independently of the code under test: SHA-256 of the DER certificate, lowercase hex. */
internal fun HeldCertificate.fingerprint(): String =
    MessageDigest.getInstance("SHA-256").digest(certificate.encoded).joinToString("") { "%02x".format(it) }

/**
 * The server's URL with its IP as the host. `MockWebServer.url()` uses the reverse-resolved name, which on Linux
 * is `localhost`; that can resolve to ::1 first while the server listens on 127.0.0.1 only (refused on CI).
 */
internal fun MockWebServer.ipUrl(path: String, address: String = "127.0.0.1"): HttpUrl =
    url(path).newBuilder().host(address).build()

internal fun httpsServer(cert: HeldCertificate, address: String = "127.0.0.1", port: Int = 0): MockWebServer {
    val server = MockWebServer()
    server.useHttps(HandshakeCertificates.Builder().heldCertificate(cert).build().sslSocketFactory())
    repeat(4) { server.enqueue(MockResponse(code = 200, body = """{"name":"kit"}""")) }
    server.start(InetAddress.getByName(address), port)
    return server
}
