package com.thompsonfabco.filamentkit.session

import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.Endpoints
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.pinnedClient
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient

/** How the app currently reaches the paired server (the Home screen's connection dot). */
sealed interface Connection {
    data object Unpaired : Connection
    data object Checking : Connection
    data class Online(val host: String) : Connection
    data object Offline : Connection
    data class CertChanged(val expected: String, val actual: String) : Connection
}

/**
 * The app's one connection to the paired server.
 *
 * Exactly one pinned client is built per stored fingerprint ([clientFor]) and rebuilt only when the fingerprint
 * changes; [api] is one [Api] over it (its client adds [SessionWatcher] in front, sharing the pinned client's pool).
 * The base URL is the first reachable endpoint ([Endpoints.firstReachable], then [discover]), cached, persisted
 * (winner first) through [save], and re-resolved whenever a call cannot reach the server.
 */
class ServerSession(
    private val scope: CoroutineScope,
    configs: Flow<ServerConfig?>,
    private val save: suspend (ServerConfig) -> Unit,
    private val discover: suspend () -> List<String>,
    val router: PairRouter,
    private val clientFor: (fingerprint: String) -> OkHttpClient = { pinnedClient(it) },
) {
    private val _config = MutableStateFlow<ServerConfig?>(null)
    val config: StateFlow<ServerConfig?> = _config.asStateFlow()

    private val _api = MutableStateFlow<Api?>(null)
    val api: StateFlow<Api?> = _api.asStateFlow()

    private val _connection = MutableStateFlow<Connection>(Connection.Unpaired)
    val connection: StateFlow<Connection> = _connection.asStateFlow()

    private val lock = Any()
    @Volatile private var fingerprint: String? = null
    @Volatile private var pinned: OkHttpClient? = null
    @Volatile private var endpoints: Endpoints? = null
    @Volatile private var endpointsPort = 0
    /** A token the server rejected (401); never sent again and never written back by a later save. */
    @Volatile private var revokedToken: String? = null
    private var resolveJob: Job? = null
    @Volatile private var host: String? = null

    init {
        scope.launch { configs.collect(::apply) }
        scope.launch { router.notice.collect { if (it == PairNotice.Unpaired) forgetToken() } }
    }

    /** `https://<host>:<port>` of the server: the last reachable host, else the best stored one. */
    fun baseUrl(): String {
        val cfg = _config.value ?: return "https://unpaired.invalid"
        val h = host ?: cfg.endpoints.firstOrNull() ?: "unpaired.invalid"
        return "https://${if (':' in h) "[$h]" else h}:${cfg.port}"
    }

    /** The bearer token, or null (no Authorization header) when it is blank or was revoked. */
    private fun currentToken(): String? = _config.value?.token?.takeIf { it.isNotBlank() && it != revokedToken }

    /** Finds the server again (no-op while a search is already running). */
    fun refresh() {
        synchronized(lock) {
            if (resolveJob?.isActive == true) return
            val client = pinned ?: return
            val eps = endpoints ?: return
            _connection.value = Connection.Checking
            resolveJob = scope.launch { resolve(client, eps) }
        }
    }

    /** The token was revoked: keep the server (endpoints, fingerprint) but store a blank token so a cold start opens Pair. */
    private suspend fun forgetToken() {
        val cfg = _config.value ?: return
        if (cfg.token.isBlank()) return
        revokedToken = cfg.token
        save(cfg.copy(token = ""))
    }

    private fun apply(cfg: ServerConfig?) {
        var changed = false
        synchronized(lock) {
            _config.value = cfg
            if (cfg == null) {
                resolveJob?.cancel()
                fingerprint = null
                pinned = null
                endpoints = null
                host = null
                _api.value = null
                _connection.value = Connection.Unpaired
                return
            }
            if (cfg.fingerprint != fingerprint) {
                resolveJob?.cancel()
                val client = clientFor(cfg.fingerprint)
                val watched = client.newBuilder()
                    .apply { interceptors().add(0, SessionWatcher(router) { refresh() }) }
                    .build()
                fingerprint = cfg.fingerprint
                pinned = client
                _api.value = Api(watched, ::baseUrl, ::currentToken)
                endpoints = null
            }
            val eps = endpoints
            if (eps == null || endpointsPort != cfg.port || eps.hosts != cfg.endpoints) {
                resolveJob?.cancel()
                endpoints = Endpoints(cfg.endpoints, cfg.port)
                endpointsPort = cfg.port
                host = null
                changed = true
            }
        }
        if (changed) refresh()
    }

    private suspend fun resolve(client: OkHttpClient, eps: Endpoints) {
        try {
            val found = eps.firstReachable(client, discover)
            if (endpoints !== eps) return
            if (found == null) {
                _connection.value = Connection.Offline
                return
            }
            host = found
            _connection.value = Connection.Online(found)
            val cfg = _config.value
            if (cfg != null && endpoints === eps && cfg.endpoints != eps.hosts) {
                save(cfg.copy(endpoints = eps.hosts, token = if (cfg.token == revokedToken) "" else cfg.token))
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: FingerprintMismatch) {
            router.noteMismatch(e)
            _connection.value = Connection.CertChanged(e.expected, e.actual)
        } catch (_: Exception) {
            _connection.value = Connection.Offline
        }
    }
}

/** A server is stored and its token has not been revoked (a revoked token is stored blank). */
fun ServerConfig?.isPaired(): Boolean = this != null && token.isNotBlank()
