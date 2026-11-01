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
        val events = Channel<Event>(Channel.UNLIMITED)

        // One consumer owns `found`; older Android allows one resolve at a time, so resolve sequentially.
        launch {
            for (event in events) {
                when (event) {
                    is Event.Found -> {
                        val resolved = withTimeoutOrNull(RESOLVE_TIMEOUT_MS) { resolve(event.info) } ?: continue
                        val host = resolved.addresses().firstOrNull() ?: continue
                        found[resolved.serviceName] = DiscoveredServer(resolved.serviceName, host, resolved.port)
                        trySend(found.values.toList())
                    }
                    is Event.Lost -> if (found.remove(event.name) != null) trySend(found.values.toList())
                }
            }
        }

        val listener = object : NsdManager.DiscoveryListener {
            override fun onServiceFound(serviceInfo: NsdServiceInfo) { events.trySend(Event.Found(serviceInfo)) }
            override fun onServiceLost(serviceInfo: NsdServiceInfo) { events.trySend(Event.Lost(serviceInfo.serviceName)) }
            override fun onDiscoveryStarted(serviceType: String) = Unit
            override fun onDiscoveryStopped(serviceType: String) = Unit
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) { close() }
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) = Unit
        }
        trySend(emptyList())
        nsd.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
        awaitClose {
            events.close()
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

    private sealed interface Event {
        class Found(val info: NsdServiceInfo) : Event
        class Lost(val name: String) : Event
    }

    @Suppress("DEPRECATION")
    private suspend fun resolve(info: NsdServiceInfo): NsdServiceInfo? = suspendCancellableCoroutine { cont ->
        val listener = object : NsdManager.ResolveListener {
            override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) { if (cont.isActive) cont.resume(null) }
            override fun onServiceResolved(serviceInfo: NsdServiceInfo) { if (cont.isActive) cont.resume(serviceInfo) }
        }
        cont.invokeOnCancellation {
            if (android.os.Build.VERSION.SDK_INT >= 34) {
                try {
                    nsd.stopServiceResolution(listener)
                } catch (_: RuntimeException) {
                    // not resolving any more
                }
            }
        }
        nsd.resolveService(info, listener)
    }

    @Suppress("DEPRECATION")
    private fun NsdServiceInfo.addresses(): List<String> {
        val all = if (android.os.Build.VERSION.SDK_INT >= 34) hostAddresses else listOfNotNull(host)
        return all.mapNotNull { it.hostAddress }.sortedBy { ':' in it } // IPv4 first
    }

    private companion object {
        const val SERVICE_TYPE = "_filamentkit._tcp"
        const val HOSTS_WAIT_MS = 3_000L
        const val RESOLVE_TIMEOUT_MS = 5_000L
    }
}
