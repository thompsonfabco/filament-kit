package com.thompsonfabco.filamentkit.net

import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import java.net.InetAddress
import java.security.MessageDigest

internal fun serverCert(name: String = "pat.local"): HeldCertificate =
    HeldCertificate.Builder().commonName(name).addSubjectAlternativeName(name).build()

/** Computed independently of the code under test: SHA-256 of the DER certificate, lowercase hex. */
internal fun HeldCertificate.fingerprint(): String =
    MessageDigest.getInstance("SHA-256").digest(certificate.encoded).joinToString("") { "%02x".format(it) }

internal fun httpsServer(cert: HeldCertificate, address: String = "127.0.0.1", port: Int = 0): MockWebServer {
    val server = MockWebServer()
    server.useHttps(HandshakeCertificates.Builder().heldCertificate(cert).build().sslSocketFactory())
    repeat(4) { server.enqueue(MockResponse(code = 200, body = """{"name":"kit"}""")) }
    server.start(InetAddress.getByName(address), port)
    return server
}
