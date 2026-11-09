package com.thompsonfabco.filamentkit.session

import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.ipUrl
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PairRouterTest {
    private val server = MockWebServer().apply { start() }

    @After fun tearDown() = server.close()

    private fun api(router: PairRouter, token: String? = "tok", onOffline: () -> Unit = {}): Api {
        val client = OkHttpClient.Builder().addInterceptor(SessionWatcher(router, onOffline = onOffline)).build()
        return Api(client, { server.ipUrl("/").toString().trimEnd('/') }, { token })
    }

    @Test fun unauthorizedApiErrorRoutesToPairWithMessage() {
        val router = PairRouter()
        router.report(ApiError(401, "unauthorized", "nope"))
        assertTrue(router.notice.value is PairNotice.Unpaired)
        assertEquals(UNPAIRED_MESSAGE, (router.notice.value as PairNotice.Unpaired).message)
        assertEquals(1, router.requests.value)
    }

    @Test fun mismatchRoutesToPairWithBothFingerprints() {
        val router = PairRouter()
        router.report(FingerprintMismatch("old", "new"))
        assertEquals(PairNotice.CertChanged("old", "new"), router.notice.value)
        assertEquals(1, router.requests.value)
    }

    @Test fun otherErrorsDoNotRoute() {
        val router = PairRouter()
        router.report(ApiError(0, "offline", "gone"))
        router.report(ApiError(503, "spoolman_unreachable", "down"))
        router.report(IllegalStateException("boom"))
        assertNull(router.notice.value)
        assertEquals(0, router.requests.value)
    }

    @Test fun pairAgainUsesTheLastRecordedMismatch() {
        val router = PairRouter()
        router.noteMismatch(FingerprintMismatch("old", "new"))
        assertEquals(0, router.requests.value)
        router.pairAgain()
        assertEquals(PairNotice.CertChanged("old", "new"), router.notice.value)
        assertEquals(1, router.requests.value)
    }

    @Test fun pairAgainWithoutAProblemHasNoNotice() {
        val router = PairRouter()
        router.pairAgain()
        assertNull(router.notice.value)
        assertEquals(1, router.requests.value)
    }

    @Test fun clearForgetsNoticeAndMismatch() {
        val router = PairRouter()
        router.noteMismatch(FingerprintMismatch("old", "new"))
        router.report(ApiError(401, "unauthorized", "nope"))
        router.clear()
        assertNull(router.notice.value)
        router.pairAgain()
        assertNull(router.notice.value)
    }

    @Test fun a401FromAnyAuthenticatedCallRoutesToPair() = runBlocking {
        val router = PairRouter()
        val api = api(router)
        server.enqueue(MockResponse(code = 401, body = """{"error":"unauthorized","message":"Token revoked"}"""))
        val e = assertThrows(ApiError::class.java) { runBlocking { api.search("grey", false) } }
        assertEquals("unauthorized", e.code)
        // the notice carries the token that call was sent with, so only that token is forgotten
        assertEquals(PairNotice.Unpaired("tok"), router.notice.value)
        assertEquals(1, router.requests.value)
    }

    @Test fun aReportedUnauthorizedKeepsTheTokenAlreadyNoted() {
        val router = PairRouter()
        router.unauthorized("tok")
        router.report(ApiError(401, "unauthorized", "nope"))
        assertEquals(PairNotice.Unpaired("tok"), router.notice.value)
        router.clear()
        router.report(ApiError(401, "unauthorized", "nope"))
        assertEquals(PairNotice.Unpaired(null), router.notice.value)
    }

    @Test fun aLate401ForTheOldTokenAfterRePairingDoesNotRoute() = runBlocking {
        val router = PairRouter()
        var current = "old"
        router.currentToken = { current }
        // the request goes out with the old token; re-pairing finishes before its 401 comes back
        val client = OkHttpClient.Builder()
            .addInterceptor(SessionWatcher(router) {})
            .addInterceptor { chain -> current = "new"; chain.proceed(chain.request()) }
            .build()
        val api = Api(client, { server.ipUrl("/").toString().trimEnd('/') }, { current })
        server.enqueue(MockResponse(code = 401, body = """{"error":"unauthorized","message":"Token revoked"}"""))
        val e = assertThrows(ApiError::class.java) { runBlocking { api.search("grey", false) } }
        assertEquals("old", e.sentToken)
        assertNull(router.notice.value)
        assertEquals(0, router.requests.value)
        // a screen reporting that same error does not route either
        router.report(e)
        assertNull(router.notice.value)
        assertEquals(0, router.requests.value)
    }

    @Test fun a401ForTheCurrentTokenStillRoutes() {
        val router = PairRouter()
        router.currentToken = { "new" }
        router.unauthorized("new")
        assertEquals(PairNotice.Unpaired("new"), router.notice.value)
        router.clear()
        router.report(ApiError(401, "unauthorized", "nope", sentToken = "new"))
        assertEquals(2, router.requests.value)
        // an error that did not say which token it was sent with still routes
        router.report(ApiError(401, "unauthorized", "nope"))
        assertEquals(3, router.requests.value)
        router.unauthorized("old")
        assertEquals(3, router.requests.value)
    }

    @Test fun a401FromAnUnauthenticatedCallDoesNotRoute() = runBlocking {
        val router = PairRouter()
        val api = api(router)
        server.enqueue(MockResponse(code = 401, body = """{"error":"unauthorized","message":"Wrong code"}"""))
        assertThrows(ApiError::class.java) { runBlocking { api.pair("123456") } }
        assertNull(router.notice.value)
        assertEquals(0, router.requests.value)
    }

    @Test fun connectionFailureReportsOffline() {
        val router = PairRouter()
        var offline = 0
        val api = api(router) { offline++ }
        server.close()
        val e = assertThrows(ApiError::class.java) { runBlocking { api.locations() } }
        assertEquals("offline", e.code)
        assertEquals(1, offline)
        assertNull(router.notice.value)
    }
}
