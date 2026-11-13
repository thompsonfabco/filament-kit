package com.thompsonfabco.filamentkit.net

import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * The server's candidate addresses, best first: as stored (mDNS name, last good host, each pairing `ip=`), then any
 * found by discovery. The stored hosts are probed in parallel (so is the
 * discovered set when none of them answers); the first to answer wins. A host is reachable when `GET https://<host>:<port>/api/info` returns 200 over the pinned
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
            .callTimeout(PROBE_TIMEOUT_S * 2, TimeUnit.SECONDS)
            .build()
        val tried = mutableSetOf<String>()
        var mismatch: FingerprintMismatch? = null

        // Probes the untried candidates at once; the first that answers wins and the rest are cancelled, so a dead
        // address never delays a live one.
        suspend fun tryAll(candidates: List<String>): String? {
            val fresh = candidates.filter { tried.add(it) }
            if (fresh.isEmpty()) return null
            return coroutineScope {
                val results = Channel<Pair<String, Result<Boolean>>>(fresh.size)
                val probes = fresh.map { host ->
                    launch { results.send(host to runCatching { reachable(probeClient, host) }) }
                }
                val mismatches = mutableMapOf<String, FingerprintMismatch>()
                var winner: String? = null
                var received = 0
                while (winner == null && received < fresh.size) {
                    val (host, outcome) = results.receive()
                    received++
                    when (val e = outcome.exceptionOrNull()) {
                        null -> if (outcome.getOrThrow()) winner = host
                        is FingerprintMismatch -> mismatches[host] = e
                        else -> throw e
                    }
                }
                probes.forEach { it.cancel() }
                if (winner == null && mismatch == null) mismatch = fresh.firstNotNullOfOrNull { mismatches[it] }
                winner
            }
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

    private suspend fun reachable(client: OkHttpClient, host: String): Boolean {
        val url = try {
            HttpUrl.Builder().scheme("https").host(host).port(port).encodedPath("/api/info").build()
        } catch (_: IllegalArgumentException) {
            return false
        }
        val call = client.newCall(Request.Builder().url(url).build())
        // A losing probe is cancelled: abort its call instead of waiting out the timeout.
        return suspendCancellableCoroutine { cont ->
            cont.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onResponse(call: Call, response: Response) {
                    cont.resume(response.use { it.code == 200 })
                }

                override fun onFailure(call: Call, e: IOException) {
                    if (e is FingerprintMismatch) cont.resumeWithException(e) else cont.resume(false)
                }
            })
        }
    }

    private companion object {
        const val PROBE_TIMEOUT_S = 3L
    }
}
