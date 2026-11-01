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

    /** The server presents a certificate other than the paired one; never auto-accepted. */
    data class CertChanged(val expected: String, val actual: String) : PairNotice
}

/**
 * The app-wide "go to pairing" signal. Any 401 on an authenticated call, or a [report]ed `unauthorized` /
 * [FingerprintMismatch], bumps [requests] (the navigation host moves to the Pair screen) and sets [notice]
 * (what the Pair screen explains). [clear] after a successful pairing.
 */
class PairRouter {
    private val _notice = MutableStateFlow<PairNotice?>(null)
    val notice: StateFlow<PairNotice?> = _notice.asStateFlow()

    private val _requests = MutableStateFlow(0)
    /** Increases by one per request to show the Pair screen. */
    val requests: StateFlow<Int> = _requests.asStateFlow()

    @Volatile private var lastMismatch: FingerprintMismatch? = null

    /** Routes to Pair for `unauthorized` and a certificate change; anything else is the screen's to show. */
    fun report(e: Throwable) {
        when {
            e is FingerprintMismatch -> route(PairNotice.CertChanged(e.expected, e.actual))
            // Keep the token a call already reported (StateFlow conflation must not hide it from the session).
            e is ApiError && e.code == "unauthorized" -> route(PairNotice.Unpaired((_notice.value as? PairNotice.Unpaired)?.token))
        }
    }

    /** The server answered 401 to a request sent with [sentToken]. */
    fun unauthorized(sentToken: String) = route(PairNotice.Unpaired(sentToken))

    /** A call saw another certificate; remembered so a later [pairAgain] can show both fingerprints. */
    fun noteMismatch(e: FingerprintMismatch) {
        lastMismatch = e
    }

    /** A screen's "Pair again": explains the last certificate change if there was one. */
    fun pairAgain() {
        val m = lastMismatch
        route(m?.let { PairNotice.CertChanged(it.expected, it.actual) } ?: _notice.value)
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
class SessionWatcher(private val router: PairRouter, private val onOffline: () -> Unit) : Interceptor {
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
        val auth = request.header("Authorization")
        if (response.code == 401 && auth != null) router.unauthorized(auth.removePrefix("Bearer ").trim())
        return response
    }
}
