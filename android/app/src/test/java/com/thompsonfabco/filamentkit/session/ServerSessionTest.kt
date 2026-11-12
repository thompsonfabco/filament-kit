package com.thompsonfabco.filamentkit.session

import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
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
import kotlinx.coroutines.launch
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
    private val cert = serverCert("kit.local")
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

    @Volatile private var found: List<String> = emptyList()

    private fun session(configs: MutableStateFlow<ServerConfig?>, discovered: List<String> = emptyList()) =
        session(configs) { discovered }

    private fun session(configs: MutableStateFlow<ServerConfig?>, discover: () -> List<String>) = ServerSession(
        scope = scope,
        configs = configs,
        save = { saved += it; configs.value = it },
        discover = { discover() },
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
        // stale: the session's current token is "new", so there is no notice and no trip to the Pair screen
        assertEquals(null, router.notice.value)
        assertEquals(0, router.requests.value)
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
        val other = serverCert("kit.local")
        val impostor = httpsServer(other, "127.0.0.3").also { servers += it }
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.3"), impostor.port))
        val s = session(configs)

        val state = await { s.connection.first { it is Connection.CertChanged } }
        assertEquals(Connection.CertChanged(cert.fingerprint(), other.fingerprint()), state)
    }

    @Test fun trustingTheNewCertificateKeepsThePairingAndUsesTheToken() {
        val other = serverCert("kit.local")
        val server = httpsServer(other, "127.0.0.3").also { servers += it }
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.3"), server.port, token = "keep"))
        val s = session(configs)
        await { s.connection.first { it is Connection.CertChanged } }
        val before = s.api.value

        assertTrue(await { s.trustCertificate(cert.fingerprint(), other.fingerprint()) })

        await { s.connection.first { it == Connection.Online("127.0.0.3") } }
        assertEquals(config(listOf("127.0.0.3"), server.port, fp = other.fingerprint(), token = "keep"), configs.value)
        assertTrue(s.api.value !== before)
        runBlocking { s.api.value!!.locations() }
        var req = server.takeRequest()
        while (req.url.encodedPath != "/api/locations") req = server.takeRequest()
        assertEquals("Bearer keep", req.headers["Authorization"])
    }

    /** What was on screen is what gets pinned: if the certificate moved on again, the app says so again. */
    @Test fun trustPinsTheCertificateShownNotWhateverAnswersNow() {
        val shown = serverCert("kit.local")
        val answering = serverCert("kit.local")
        val server = httpsServer(answering, "127.0.0.3").also { servers += it }
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.3"), server.port))
        val s = session(configs)
        await { s.connection.first { it is Connection.CertChanged } }

        assertTrue(await { s.trustCertificate(cert.fingerprint(), shown.fingerprint()) })

        assertEquals(shown.fingerprint(), configs.value?.fingerprint)
        await { s.connection.first { it == Connection.CertChanged(shown.fingerprint(), answering.fingerprint()) } }
    }

    @Test fun trustGivesUpWhenTheStoredConfigNeverShowsTheNewPin() {
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.9"), 1))
        val s = ServerSession(
            scope = scope,
            configs = configs,
            save = { saved += it }, // a write that never reaches the config flow
            discover = { emptyList() },
            router = router,
            clientFor = { fp: String -> pinnedClient(fp) },
            trustWaitMs = 200,
        )
        await { s.config.first { it != null } }

        assertFalse(await { s.trustCertificate(cert.fingerprint(), "cd".repeat(32)) })

        assertEquals(1, saved.size)
    }

    @Test fun trustSavesNothingWhenThePairingNoLongerPinsThatCertificate() {
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.9"), 1))
        val s = session(configs)
        await { s.config.first { it != null } }

        assertFalse(await { s.trustCertificate("ab".repeat(32), "cd".repeat(32)) })

        assertTrue(saved.isEmpty())
    }

    @Test fun trustSavesNothingForARevokedToken() {
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.9"), 1, token = ""))
        val s = session(configs)
        await { s.config.first { it != null } }

        assertFalse(await { s.trustCertificate(cert.fingerprint(), "cd".repeat(32)) })

        assertTrue(saved.isEmpty())
    }

    @Test fun aLateMismatchFromBeforeTheTrustIsIgnored() {
        val configs = MutableStateFlow<ServerConfig?>(config(listOf("127.0.0.9"), 1))
        val s = session(configs)
        await { s.config.first { it != null } }
        val newFp = "cd".repeat(32)
        assertTrue(await { s.trustCertificate(cert.fingerprint(), newFp) })

        router.report(FingerprintMismatch(cert.fingerprint(), newFp))
        router.noteMismatch(FingerprintMismatch(cert.fingerprint(), newFp))
        router.pairAgain()

        assertNull(router.notice.value)
        // A mismatch against the pin in use still counts.
        router.report(FingerprintMismatch(newFp, "ef".repeat(32)))
        assertEquals(PairNotice.CertChanged(newFp, "ef".repeat(32)), router.notice.value)
    }

    @Test fun canTrustNeedsAUsablePairingOnThatCertificate() {
        assertFalse((null as ServerConfig?).canTrust("ab"))
        assertFalse(config(listOf("h"), 1, fp = "ab", token = "").canTrust("ab"))
        assertFalse(config(listOf("h"), 1, fp = "ab").canTrust("cd"))
        assertTrue(config(listOf("h"), 1, fp = "ab").canTrust("AB"))
    }

    @Test fun aRecheckNoticesTheServerGoneWithoutShowingConnecting() {
        val good = httpsServer(cert, "127.0.0.3").also { servers += it }
        val s = session(MutableStateFlow(config(listOf("127.0.0.3"), good.port)))
        await { s.connection.first { it is Connection.Online } }
        val seen = java.util.Collections.synchronizedList(mutableListOf<Connection>())
        val watching = scope.launch { s.connection.collect { seen += it } }
        good.close()
        s.recheck()
        await { s.connection.first { it == Connection.Offline } }
        watching.cancel()
        assertFalse(seen.toString(), Connection.Checking in seen)
    }

    @Test fun aRecheckNoticesTheServerBack() {
        val good = httpsServer(cert, "127.0.0.3").also { servers += it }
        found = emptyList()
        val s = session(MutableStateFlow(config(listOf("127.0.0.9"), good.port))) { found }
        await { s.connection.first { it == Connection.Offline } }
        found = listOf("127.0.0.3")
        s.recheck()
        await { s.connection.first { it == Connection.Online("127.0.0.3") } }
    }

    @Test fun anAnswerToAnyCallEndsOfflineAndChangesNothingOtherwise() {
        val good = httpsServer(cert, "127.0.0.3").also { servers += it }
        found = emptyList()
        val s = session(MutableStateFlow(config(listOf("127.0.0.9"), good.port))) { found }
        await { s.connection.first { it == Connection.Offline } }
        found = listOf("127.0.0.3")
        s.onServerAnswered()
        await { s.connection.first { it == Connection.Online("127.0.0.3") } }
        val before = good.requestCount
        s.onServerAnswered()
        Thread.sleep(200)
        assertEquals(before, good.requestCount)
    }

    @Test fun aRecheckKeepsAChangedCertificateAndDoesNotOpenPair() {
        val other = serverCert("kit.local")
        val answering = httpsServer(other, "127.0.0.3").also { servers += it }
        val s = session(MutableStateFlow(config(listOf("127.0.0.3"), answering.port)))
        await { s.connection.first { it is Connection.CertChanged } }
        val requests = router.requests.value
        s.recheck()
        Thread.sleep(200)
        assertTrue(s.connection.value is Connection.CertChanged)
        assertEquals(requests, router.requests.value)
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
