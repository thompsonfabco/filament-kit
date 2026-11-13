package com.thompsonfabco.filamentkit.session

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import java.io.IOException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import okhttp3.Interceptor
import okhttp3.Response

const val UNPAIRED_MESSAGE = "This phone was unpaired from the server"

/** Why the app sent the user to the pairing screen. */
sealed interface PairNotice {
    /**
     * The server rejected the token (401). [token] is the token that request was sent with (null when only a screen
     * reported the error); the session forgets the stored token only if it is still that one, so a late 401 from
     * before a re-pair never blanks the new token.
     */
    data class Unpaired(val token: String? = null) : PairNotice {
        val message: String get() = UNPAIRED_MESSAGE

        override fun toString() = "Unpaired" // never log the token
    }

    /** The server presents a certificate other than the paired one; never accepted without the user's tap. */
    data class CertChanged(val expected: String, val actual: String) : PairNotice
}

/**
 * The app-wide pairing signals. Any 401 on an authenticated call, or a [report]ed `unauthorized` /
 * [FingerprintMismatch], bumps [requests] and sets [notice] (what the Pair screen explains, and what the connection
 * chip says); the app never moves the user for it (05-android-app 2.7). The user's own "Pair again" or "Review the
 * certificate" ([pairAgain]) also bumps [pairAgainRequests], and the navigation host then opens the pairing graph.
 * [clear] after a successful pairing.
 *
 * A 401 routes only when the token its request was sent with is still [currentToken]: a late answer to a request
 * sent before a re-pair finished is stale and ignored.
 */
class PairRouter {
    /** The token requests are sent with now (the session sets it); null = no check (every 401 routes). */
    @Volatile var currentToken: (() -> String?)? = null

    /** The fingerprint pinned now (the session sets it); null = no check (every mismatch counts). */
    @Volatile var currentFingerprint: (() -> String?)? = null

    private val _notice = MutableStateFlow<PairNotice?>(null)
    val notice: StateFlow<PairNotice?> = _notice.asStateFlow()

    private val _requests = MutableStateFlow(0)
    /** Increases by one per reason to pair (a 401, a changed certificate, a screen asking); nothing navigates by it. */
    val requests: StateFlow<Int> = _requests.asStateFlow()

    private val _pairAgainRequests = MutableStateFlow(0)
    /** Increases by one each time the user asks to pair again; the only signal that opens the pairing graph. */
    val pairAgainRequests: StateFlow<Int> = _pairAgainRequests.asStateFlow()

    @Volatile private var lastMismatch: FingerprintMismatch? = null

    /** Routes to Pair for `unauthorized` and a certificate change; anything else is the screen's to show. */
    fun report(e: Throwable) {
        when {
            e is FingerprintMismatch -> if (!stale(e)) route(PairNotice.CertChanged(e.expected, e.actual))
            // Keep the token a call already reported (StateFlow conflation must not hide it from the session).
            e is ApiError && e.code == "unauthorized" && !stale(e.sentToken) ->
                route(PairNotice.Unpaired((_notice.value as? PairNotice.Unpaired)?.token))
        }
    }

    /** The server answered 401 to a request sent with [sentToken]; ignored when that is no longer the token. */
    fun unauthorized(sentToken: String) {
        if (!stale(sentToken)) route(PairNotice.Unpaired(sentToken))
    }

    /** [sent] is a token other than the current one (a re-pair replaced it, or it was already revoked). */
    private fun stale(sent: String?): Boolean {
        val current = currentToken ?: return false
        return sent != null && sent != current()
    }

    /** A late answer from before the pin changed (trusting a new certificate, a re-pair) says nothing about it now. */
    private fun stale(e: FingerprintMismatch): Boolean {
        val pinned = currentFingerprint?.invoke() ?: return false
        return !pinned.equals(e.expected, ignoreCase = true)
    }

    /** A call saw another certificate; remembered so a later [pairAgain] can show it. */
    fun noteMismatch(e: FingerprintMismatch) {
        if (!stale(e)) lastMismatch = e
    }

    /** A screen's "Pair again": explains the last certificate change if there was one. */
    fun pairAgain() {
        val m = lastMismatch
        route(m?.let { PairNotice.CertChanged(it.expected, it.actual) } ?: _notice.value)
        _pairAgainRequests.update { it + 1 }
    }

    fun clear() {
        lastMismatch = null
        _notice.value = null
    }

    private fun route(notice: PairNotice?) {
        _notice.value = notice
        _requests.update { it + 1 }
    }
}

/**
 * Sits outermost on the API client: a 401 on a request that carried a bearer token routes to pairing; a connection
 * failure calls [onOffline] (the session re-resolves the server's address); a certificate change is remembered.
 */
class SessionWatcher(
    private val router: PairRouter,
    private val onAnswer: () -> Unit = {},
    private val onOffline: () -> Unit,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val response = try {
            chain.proceed(request)
        } catch (e: FingerprintMismatch) {
            router.noteMismatch(e)
            onOffline()
            throw e
        } catch (e: IOException) {
            if (!chain.call().isCanceled()) onOffline()
            throw e
        }
        onAnswer()
        val auth = request.header("Authorization")
        if (response.code == 401 && auth != null) router.unauthorized(auth.removePrefix("Bearer ").trim())
        return response
    }
}
