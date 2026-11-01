package com.thompsonfabco.filamentkit.net

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume

/** A filament-kit server announced on this network. [host] is a resolved address. */
data class DiscoveredServer(val name: String, val host: String, val port: Int)

/** Finds servers advertising `_filamentkit._tcp` with NsdManager. Collecting [servers] runs the browse; cancelling stops it. */
class Discovery(context: Context) {
    private val nsd = context.applicationContext.getSystemService(Context.NSD_SERVICE) as NsdManager

    /** Live list of resolved servers, re-emitted whenever one appears or disappears. */
    fun servers(): Flow<List<DiscoveredServer>> = callbackFlow {
        val found = LinkedHashMap<String, DiscoveredServer>()
        val pending = Channel<NsdServiceInfo>(Channel.UNLIMITED)

        // Older Android allows one resolve at a time, so resolve sequentially.
        launch {
            for (info in pending) {
                val resolved = resolve(info) ?: continue
                val host = resolved.addresses().firstOrNull() ?: continue
                found[resolved.serviceName] = DiscoveredServer(resolved.serviceName, host, resolved.port)
                trySend(found.values.toList())
            }
        }

        val listener = object : NsdManager.DiscoveryListener {
            override fun onServiceFound(serviceInfo: NsdServiceInfo) { pending.trySend(serviceInfo) }
            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                if (found.remove(serviceInfo.serviceName) != null) trySend(found.values.toList())
            }
            override fun onDiscoveryStarted(serviceType: String) = Unit
            override fun onDiscoveryStopped(serviceType: String) = Unit
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) { close() }
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) = Unit
        }
        trySend(emptyList())
        nsd.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
        awaitClose {
            pending.close()
            try {
                nsd.stopServiceDiscovery(listener)
            } catch (_: IllegalArgumentException) {
                // discovery never started
            }
        }
    }

    /** Addresses of servers found within a few seconds; the fallback source for `Endpoints.firstReachable`. */
    suspend fun hosts(): List<String> =
        withTimeoutOrNull(HOSTS_WAIT_MS) { servers().first { it.isNotEmpty() } }?.map { it.host }.orEmpty()

    @Suppress("DEPRECATION")
    private suspend fun resolve(info: NsdServiceInfo): NsdServiceInfo? = suspendCancellableCoroutine { cont ->
        nsd.resolveService(info, object : NsdManager.ResolveListener {
            override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) { if (cont.isActive) cont.resume(null) }
            override fun onServiceResolved(serviceInfo: NsdServiceInfo) { if (cont.isActive) cont.resume(serviceInfo) }
        })
    }

    @Suppress("DEPRECATION")
    private fun NsdServiceInfo.addresses(): List<String> {
        val all = if (android.os.Build.VERSION.SDK_INT >= 34) hostAddresses else listOfNotNull(host)
        return all.mapNotNull { it.hostAddress }.sortedBy { ':' in it } // IPv4 first
    }

    private companion object {
        const val SERVICE_TYPE = "_filamentkit._tcp"
        const val HOSTS_WAIT_MS = 3_000L
    }
}
