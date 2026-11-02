package com.thompsonfabco.filamentkit.ui.pair

import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ServerInfo
import com.thompsonfabco.filamentkit.net.pinnedClient
import com.thompsonfabco.filamentkit.net.probeFingerprint
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** The network calls pairing needs. Real implementation: [NetPairingBackend]; tests pass a fake. */
interface PairingBackend {
    /** The SHA-256 fingerprint (lowercase hex) of the certificate [host]:[port] presents. */
    suspend fun probe(host: String, port: Int): String

    /** Sends the 6-digit [code] over a client pinned to [fingerprint]; returns the token. */
    suspend fun pair(host: String, port: Int, fingerprint: String, code: String): String

    /** `GET /api/info` over a client pinned to [fingerprint]. */
    suspend fun info(host: String, port: Int, fingerprint: String, token: String?): ServerInfo

    /**
     * One authenticated call (`GET /api/printers`) with a scanned QR [token]: the server marks the token claimed on
     * its first authenticated use and drops unclaimed QR tokens after 10 minutes. Throws [ApiError] `unauthorized`
     * when the server no longer accepts the token.
     */
    suspend fun claim(host: String, port: Int, fingerprint: String, token: String)
}

class NetPairingBackend : PairingBackend {
    override suspend fun probe(host: String, port: Int): String =
        withContext(Dispatchers.IO) { probeFingerprint(host, port) }

    override suspend fun pair(host: String, port: Int, fingerprint: String, code: String): String =
        api(host, port, fingerprint, null).pair(code)

    override suspend fun info(host: String, port: Int, fingerprint: String, token: String?): ServerInfo =
        api(host, port, fingerprint, token).info()

    override suspend fun claim(host: String, port: Int, fingerprint: String, token: String) {
        api(host, port, fingerprint, token).printers()
    }

    private fun api(host: String, port: Int, fingerprint: String, token: String?) =
        Api(pinnedClient(fingerprint), { "https://${if (':' in host) "[$host]" else host}:$port" }, { token })
}
