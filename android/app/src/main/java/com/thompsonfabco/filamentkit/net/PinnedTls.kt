package com.thompsonfabco.filamentkit.net

import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.security.MessageDigest
import java.security.cert.Certificate
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLEngine
import javax.net.ssl.SSLSession
import javax.net.ssl.SSLSocket
import javax.net.ssl.X509ExtendedTrustManager

/**
 * The server presented a certificate other than the paired one (e.g. the server was reinstalled).
 * Never auto-accepted: the UI shows both fingerprints and asks the user to re-pair.
 */
class FingerprintMismatch(val expected: String, val actual: String) :
    IOException("The server's certificate changed: expected $expected, got $actual")

/** SHA-256 of the DER-encoded certificate as lowercase hex without colons (the server's `pairing.fingerprint`). */
fun certFingerprint(cert: Certificate): String =
    MessageDigest.getInstance("SHA-256").digest(cert.encoded).joinToString("") { "%02x".format(it) }

/**
 * A client that trusts exactly one certificate: the self-signed server leaf whose SHA-256 (DER) equals [fingerprint].
 * No CA store is consulted. The host-name check is skipped only for that pinned certificate, so the server can be
 * reached by mDNS name or any IP. A different certificate fails the handshake with [FingerprintMismatch].
 */
fun pinnedClient(fingerprint: String, base: OkHttpClient = OkHttpClient()): OkHttpClient {
    val expected = fingerprint.lowercase()
    val trustManager = PinnedTrustManager(expected)
    val context = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trustManager), null) }
    val hostnameVerifier = HostnameVerifier { _, session -> session.leafFingerprint() == expected }
    return base.newBuilder()
        .sslSocketFactory(context.socketFactory, trustManager)
        .hostnameVerifier(hostnameVerifier)
        .addInterceptor(MismatchUnwrapper)
        .build()
}

/**
 * Reads the fingerprint of the certificate a server presents, so the user can compare it with the one shown on the
 * server when pairing by manual entry. Uses a private trust-all context that is never exposed and never used for API
 * calls: the socket is closed right after the handshake, before any request is sent. Blocking; call off the main thread.
 */
fun probeFingerprint(host: String, port: Int): String {
    val context = SSLContext.getInstance("TLS").apply { init(null, arrayOf(AcceptAnyForProbe), null) }
    Socket().use { raw ->
        raw.connect(InetSocketAddress(host, port), PROBE_TIMEOUT_MS)
        raw.soTimeout = PROBE_TIMEOUT_MS
        (context.socketFactory.createSocket(raw, host, port, true) as SSLSocket).use { tls ->
            tls.startHandshake()
            val leaf = tls.session.peerCertificates.firstOrNull() ?: throw IOException("The server sent no certificate")
            return certFingerprint(leaf)
        }
    }
}

private const val PROBE_TIMEOUT_MS = 5_000

private fun SSLSession.leafFingerprint(): String? =
    try {
        peerCertificates.firstOrNull()?.let(::certFingerprint)
    } catch (_: IOException) {
        null
    }

/** Carries the mismatch through the TLS stack, which wraps trust-manager failures in SSLHandshakeException. */
private class PinMismatchException(val expected: String, val actual: String) :
    CertificateException("Certificate fingerprint $actual does not match pinned $expected")

private class PinnedTrustManager(private val expected: String) : X509ExtendedTrustManager() {
    private fun check(chain: Array<out X509Certificate>?) {
        // Self-signed server: only the leaf matters, no chain is built.
        val leaf = chain?.firstOrNull() ?: throw CertificateException("The server sent no certificate")
        val actual = certFingerprint(leaf)
        if (actual != expected) throw PinMismatchException(expected, actual)
    }

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) = check(chain)
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?, socket: Socket?) = check(chain)
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?, engine: SSLEngine?) = check(chain)

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) = rejectClient()
    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?, socket: Socket?) = rejectClient()
    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?, engine: SSLEngine?) = rejectClient()

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}

/** Accepts any server certificate. Only ever used inside [probeFingerprint]; never handed to an HTTP client. */
private object AcceptAnyForProbe : X509ExtendedTrustManager() {
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) = Unit
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?, socket: Socket?) = Unit
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?, engine: SSLEngine?) = Unit

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) = rejectClient()
    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?, socket: Socket?) = rejectClient()
    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?, engine: SSLEngine?) = rejectClient()

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}

private fun rejectClient(): Nothing = throw CertificateException("Client certificates are not accepted")

/** Rethrows a pin failure as a bare [FingerprintMismatch] so callers see both fingerprints, not a TLS wrapper. */
private object MismatchUnwrapper : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response =
        try {
            chain.proceed(chain.request())
        } catch (e: IOException) {
            if (e is FingerprintMismatch) throw e
            val pin = generateSequence<Throwable>(e) { it.cause }.take(10).filterIsInstance<PinMismatchException>().firstOrNull()
                ?: throw e
            throw FingerprintMismatch(pin.expected, pin.actual).apply { initCause(e) }
        }
}
