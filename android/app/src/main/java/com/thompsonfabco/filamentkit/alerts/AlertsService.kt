package com.thompsonfabco.filamentkit.alerts

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.data.Settings
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.Discovery
import com.thompsonfabco.filamentkit.net.Endpoints
import com.thompsonfabco.filamentkit.net.LocalNetwork
import com.thompsonfabco.filamentkit.net.pinnedClient
import com.thompsonfabco.filamentkit.session.isPaired
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChangedBy
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * The watching service (R80 section 4): while "Alerts on this phone" is on it keeps one waiting connection to the Hub
 * and shows a notification per alert, with the app closed. It is a foreground service of type `specialUse` (no system
 * time limit, unlike `dataSync`) with the permanent notification Android requires. It builds its own pinned client
 * from the stored pairing, because the app's session lives in the activity.
 *
 * It stops itself when the switch is turned off, the Hub is forgotten or the token is revoked (401, which also turns
 * the switch off).
 */
class AlertsService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var watching: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        LocalNetwork.install(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notifier = AlertNotifier(this)
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        try {
            ServiceCompat.startForeground(this, AlertNotifier.WATCHING_ID, notifier.watching(), type)
        } catch (e: RuntimeException) {
            // started where Android no longer allows a foreground service (ForegroundServiceStartNotAllowedException), or
            // without the permission: nothing to watch with
            stopSelf()
            return START_NOT_STICKY
        }
        running = true
        if (watching?.isActive != true) watching = scope.launch { watch(notifier) }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        scope.cancel()
        super.onDestroy()
    }

    private suspend fun watch(notifier: AlertNotifier) {
        val settings = Settings.create(this)
        val store = AlertsStore.create(this)
        combine(store.on, settings.server) { on, config -> config.takeIf { on && it.isPaired() } }
            .distinctUntilChangedBy { c -> c?.let { Triple(it.fingerprint, it.token, it.port) } }
            .collectLatest { config ->
                if (config == null) {
                    stopSelf()
                    return@collectLatest
                }
                val end = EventsLoop(
                    fetch = fetcher(config),
                    cursor = store,
                    deliver = { notifier.act(it) },
                ).run()
                // the switch going off ends this block through the flow above, so the write must not be cancelled half way
                if (end == LoopEnd.Revoked) withContext(NonCancellable) { store.setOn(false) }
            }
    }

    /** One pinned [Api] for [config]; a call that cannot reach the Hub looks for it again (address, name service). */
    private fun fetcher(config: ServerConfig): suspend (EventsQuery) -> EventsAnswer {
        val client = pinnedClient(config.fingerprint)
        val endpoints = Endpoints(config.endpoints, config.port)
        val discovery = Discovery(this)
        val host = java.util.concurrent.atomic.AtomicReference<String?>(null)
        val api = Api(
            client,
            baseUrl = {
                val h = host.get() ?: config.endpoints.firstOrNull() ?: "unpaired.invalid"
                "https://${if (':' in h) "[$h]" else h}:${config.port}"
            },
            token = { config.token },
        )
        return { query ->
            try {
                api.events(query)
            } catch (e: ApiError) {
                if (e.code == "offline") {
                    host.set(
                        try {
                            endpoints.firstReachable(client, discovery::hosts)
                        } catch (c: CancellationException) {
                            throw c
                        } catch (_: Exception) {
                            null
                        },
                    )
                }
                throw e
            }
        }
    }

    companion object {
        /** True from the service's start to its end; the app reads it to start the service again after it was stopped. */
        @Volatile var running = false
            private set
    }
}

/** Starting and stopping the watching service. Starting is only done from the person's switch, with the app showing, and by the boot receiver. */
object AlertsLauncher {
    /** False when Android refused (a foreground service may not start from here). */
    fun start(context: Context): Boolean = try {
        ContextCompat.startForegroundService(context, Intent(context, AlertsService::class.java))
        true
    } catch (e: RuntimeException) {
        // ForegroundServiceStartNotAllowedException (API 31+) and SecurityException are both runtime exceptions
        false
    }

    /**
     * Starts the service when the switch is on, a Hub is paired, notifications are allowed and it is not running. Called
     * when the app is opened (the person dismissed the notification or stopped it in Task Manager) and after a boot or
     * an update of the app.
     */
    suspend fun startIfNeeded(context: Context): Boolean {
        val on = AlertsStore.create(context).isOn()
        val paired = Settings.create(context).serverOrNull().isPaired()
        val allowed = AlertNotifier(context).allowed()
        return shouldStartWatching(on, paired, allowed, AlertsService.running) && start(context)
    }

    fun stop(context: Context) {
        context.stopService(Intent(context, AlertsService::class.java))
    }
}
