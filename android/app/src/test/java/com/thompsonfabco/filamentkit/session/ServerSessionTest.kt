package com.thompsonfabco.filamentkit.session

import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.fingerprint
import com.thompsonfabco.filamentkit.net.httpsServer
import com.thompsonfabco.filamentkit.net.pinnedClient
import com.thompsonfabco.filamentkit.net.serverCert
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Test

class ServerSessionTest {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val servers = mutableListOf<MockWebServer>()
    private val cert = serverCert("pat.local")
    private val saved = mutableListOf<ServerConfig>()
    private val built = mutableListOf<String>()

    @After fun tearDown() {
        scope.cancel()
        servers.forEach { it.close() }
    }

    private fun config(endpoints: List<String>, port: Int, fp: String = cert.fingerprint(), token: String = "tok") =
        ServerConfig(endpoints, port, fp, token, "Workshop")

    private val router = PairRouter()

    @Volatile private var localNetwork = true

    private fun session(configs: MutableStateFlow<ServerConfig?>, discovered: List<String> = emptyList()) = ServerSession(
        scope = scope,
        configs = configs,
        save = { saved += it; configs.value = it },
        discover = { discovered },
        router = router,
        clientFor = { fp: String -> built += fp; pinnedClient(fp) },
        localNetworkGranted = { localNetwork },
    )

    @Test fun withoutTheLocalNetworkPermissionNothingIsResolvedAndItIsNotOffline() {
        val good = httpsServer(cert, "127.0.0.3").also { servers += it }
        localNetwork = false
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.3"), good.port))
        val s = session(configs)
        await { s.connection.first { it == Connection.NeedsLocalNetwork } }
        s.refresh()
        assertEquals(Connection.NeedsLocalNetwork, s.connection.value)
        assertEquals(0, good.requestCount)
        assertTrue(saved.isEmpty())

        localNetwork = true
        s.refresh()
        await { s.connection.first { it == Connection.Online("127.0.0.3") } }
    }

    @Test fun aLate401ForAnOldTokenDoesNotBlankTheNewOne() {
        val good = httpsServer(cert, "127.0.0.3").also { servers += it }
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.3"), good.port, token = "new"))
        val s = session(configs)
        await { s.connection.first { it is Connection.Online } }

        router.unauthorized("old")
        assertEquals(PairNotice.Unpaired("old"), router.notice.value)
        // give the session's collector time to act on it
        runBlocking { kotlinx.coroutines.delay(300) }
        assertEquals("new", s.config.value?.token)
        assertTrue(saved.none { it.token.isBlank() })

        runBlocking { s.api.value!!.locations() }
        var req = good.takeRequest()
        while (req.url.encodedPath != "/api/locations") req = good.takeRequest()
        assertEquals("Bearer new", req.headers["Authorization"])
    }

    private fun <T> await(block: suspend () -> T): T = runBlocking { withTimeout(15_000) { block() } }

    @Test fun buildsOneClientPerFingerprint() {
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.9"), 1))
        val s = session(configs)
        val first = await { s.api.first { it != null } }

        configs.value = config(listOf("127.0.0.8", "127.0.0.9"), 1, token = "tok2")
        await { s.config.first { it?.token == "tok2" } }
        assertSame(first, s.api.value)
        assertEquals(1, built.size)

        configs.value = config(listOf("127.0.0.9"), 1, fp = "ab".repeat(32))
        await { s.api.first { it != null && it !== first } }
        assertEquals(listOf(cert.fingerprint(), "ab".repeat(32)), built)
    }

    @Test fun noConfigMeansNoApi() {
        val configs = MutableStateFlow<ServerConfig?>(null)
        val s = session(configs)
        assertNull(s.api.value)
        assertEquals(Connection.Unpaired, s.connection.value)
    }

    @Test fun resolvesFirstReachableHostAndRemembersIt() {
        val good = httpsServer(cert, "127.0.0.3").also { servers += it }
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.4", "127.0.0.3"), good.port))
        val s = session(configs)

        await { s.connection.first { it is Connection.Online } }
        assertEquals(Connection.Online("127.0.0.3"), s.connection.value)
        assertEquals("https://127.0.0.3:${good.port}", s.baseUrl())
        assertEquals(listOf("127.0.0.3", "127.0.0.4"), saved.last().endpoints)
    }

    @Test fun offlineCallReResolvesThroughDiscovery() {
        val first = httpsServer(cert, "127.0.0.3").also { servers += it }
        val port = first.port
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.3"), port))
        val s = session(configs, discovered = listOf("127.0.0.6"))
        await { s.connection.first { it == Connection.Online("127.0.0.3") } }
        assertNotNull(s.api.value)

        first.close()
        httpsServer(cert, "127.0.0.6", port).also { servers += it } // the server's address changed
        val e = assertThrows(ApiError::class.java) { runBlocking { s.api.value!!.locations() } }
        assertEquals("offline", e.code)

        await { s.connection.first { it == Connection.Online("127.0.0.6") } }
        assertEquals("https://127.0.0.6:$port", s.baseUrl())
        assertEquals("127.0.0.6", saved.last().endpoints.first())
    }

    @Test fun otherCertificateEverywhereShowsBothFingerprints() {
        val other = serverCert("pat.local")
        val impostor = httpsServer(other, "127.0.0.3").also { servers += it }
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.3"), impostor.port))
        val s = session(configs)

        val state = await { s.connection.first { it is Connection.CertChanged } }
        assertEquals(Connection.CertChanged(cert.fingerprint(), other.fingerprint()), state)
    }

    @Test fun nothingReachableIsOffline() {
        val gone = httpsServer(cert, "127.0.0.3")
        val port = gone.port
        gone.close()
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.3"), port))
        val s = session(configs)
        await { s.connection.first { it == Connection.Offline } }
    }

    @Test fun unpairedNoticeStoresBlankTokenAndStopsSendingIt() {
        val good = httpsServer(cert, "127.0.0.3").also { servers += it }
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.3"), good.port, token = "revoked"))
        val s = session(configs)
        await { s.connection.first { it is Connection.Online } }
        assertTrue(configs.value.isPaired())

        router.unauthorized("revoked")

        val blanked = await { s.config.first { it?.token == "" } }!!
        assertEquals(listOf("127.0.0.3"), blanked.endpoints)
        assertEquals(cert.fingerprint(), blanked.fingerprint)
        assertEquals(good.port, blanked.port)
        assertFalse(blanked.isPaired()) // a cold start opens Pair

        runBlocking { s.api.value!!.locations() }
        var req = good.takeRequest()
        while (req.url.encodedPath != "/api/locations") req = good.takeRequest()
        assertNull(req.headers["Authorization"])
    }

    @Test fun isPairedNeedsAStoredNonBlankToken() {
        assertFalse((null as ServerConfig?).isPaired())
        assertFalse(config(listOf("h"), 1, token = " ").isPaired())
        assertTrue(config(listOf("h"), 1).isPaired())
    }
}
