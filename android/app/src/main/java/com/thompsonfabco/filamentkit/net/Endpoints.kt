package com.thompsonfabco.filamentkit.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * The server's candidate addresses, best first: as stored (mDNS name, last good host, each pairing `ip=`), then any
 * found by discovery. A host is reachable when `GET https://<host>:<port>/api/info` returns 200 over the pinned
 * client, i.e. it presents the paired certificate. The winner moves to the front of [hosts] so it is tried first
 * next time (callers persist [hosts]).
 */
class Endpoints(stored: List<String>, private val port: Int) {
    private val order = stored.filter { it.isNotBlank() }.distinct().toMutableList()

    val hosts: List<String> get() = synchronized(order) { order.toList() }

    /**
     * Returns the first reachable host, or null if none answers. Hosts presenting another certificate are skipped;
     * if no host is reachable but at least one presented another certificate, that [FingerprintMismatch] is thrown
     * so the user can be asked to re-pair (never auto-accepted).
     *
     * @param client a client from [pinnedClient].
     */
    suspend fun firstReachable(client: OkHttpClient, discovered: suspend () -> List<String>): String? {
        val probeClient = client.newBuilder()
            .connectTimeout(PROBE_TIMEOUT_S, TimeUnit.SECONDS)
            .readTimeout(PROBE_TIMEOUT_S, TimeUnit.SECONDS)
            .build()
        val tried = mutableSetOf<String>()
        var mismatch: FingerprintMismatch? = null

        suspend fun tryAll(candidates: List<String>): String? {
            for (host in candidates) {
                if (!tried.add(host)) continue
                try {
                    if (reachable(probeClient, host)) return host
                } catch (e: FingerprintMismatch) {
                    if (mismatch == null) mismatch = e
                }
            }
            return null
        }

        val found = tryAll(hosts) ?: tryAll(discovered().filter { it.isNotBlank() })
        if (found != null) {
            synchronized(order) {
                order.remove(found)
                order.add(0, found)
            }
            return found
        }
        mismatch?.let { throw it }
        return null
    }

    private suspend fun reachable(client: OkHttpClient, host: String): Boolean = withContext(Dispatchers.IO) {
        val url = try {
            HttpUrl.Builder().scheme("https").host(host).port(port).encodedPath("/api/info").build()
        } catch (_: IllegalArgumentException) {
            return@withContext false
        }
        try {
            client.newCall(Request.Builder().url(url).build()).execute().use { it.code == 200 }
        } catch (e: FingerprintMismatch) {
            throw e
        } catch (_: IOException) {
            false
        }
    }

    private companion object {
        const val PROBE_TIMEOUT_S = 3L
    }
}
