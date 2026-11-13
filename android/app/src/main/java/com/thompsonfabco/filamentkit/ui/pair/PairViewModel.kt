package com.thompsonfabco.filamentkit.ui.pair

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.data.SettingsStore
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LocalNetwork
import com.thompsonfabco.filamentkit.pairing.parsePairingUri
import java.io.IOException
import javax.net.ssl.SSLException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

const val DEFAULT_PORT = 8710

enum class Step { Choose, Address, Confirm, Code, Done }

/** Where the expected certificate came from: a saved pairing, a scanned code, or the check the user just made. */
enum class MismatchSource { STORED, QR, MANUAL }

/** The certificate that was expected ([expected]) and what the server presents ([actual]). */
data class Mismatch(val expected: String, val actual: String, val source: MismatchSource = MismatchSource.STORED)

/** A sentence pairing shows (05-android-app 4.9): a string of the catalogue with its fields, or the Hub's own words. */
sealed interface PairMessage {
    data class Res(@StringRes val id: Int, val args: List<String> = emptyList()) : PairMessage
    data class Raw(val text: String) : PairMessage

    /** The app may not use the local network: shown as the notice of 05 3.3, and gone once access is granted. */
    data object LocalNetwork : PairMessage
}

/** The field a message concerns; a message with none belongs under the step's button. */
enum class PairField { Address, Port }

data class PairUi(
    val step: Step = Step.Choose,
    val host: String = "",
    val port: Int = DEFAULT_PORT,
    /** Lowercase hex, no spaces; show it with [groupFingerprint]. */
    val fingerprint: String? = null,
    val busy: Boolean = false,
    val error: PairMessage? = null,
    val errorField: PairField? = null,
    val mismatch: Mismatch? = null,
)

/** `0123456789ab` -> `0123 4567 89ab`. */
fun groupFingerprint(fingerprint: String): String = fingerprint.chunked(4).joinToString(" ")

/** [groupFingerprint] with four groups to a line (05-android-app 4.6). */
fun fingerprintLines(fingerprint: String): List<String> = fingerprint.chunked(16).map(::groupFingerprint)

private val CODE = Regex("[0-9]{6}")

/** The scanned QR's token was not accepted when the app first used it. */
val QR_EXPIRED = PairMessage.Res(R.string.pair_error_expired)

/**
 * Pairing flows: QR scan, and manual entry (address, then the server's certificate fingerprint for the user to
 * confirm, then the 6-digit code). Nothing is sent to the server except the probe handshake until the user has
 * confirmed the fingerprint, or has turned that check off in Settings; the certificate is pinned either way.
 * [scope] defaults to the ViewModel's own; tests pass one. [localNetworkMissing] turns
 * "can't reach the server" into the local network permission message when that permission is the cause.
 */
class PairViewModel(
    private val settings: SettingsStore,
    private val backend: PairingBackend,
    scope: CoroutineScope? = null,
    private val localNetworkMissing: () -> Boolean = { LocalNetwork.missing() },
) : ViewModel() {
    private val scope: CoroutineScope = scope ?: viewModelScope
    private val _state = MutableStateFlow(PairUi())
    val state: StateFlow<PairUi> = _state

    private var confirmed = false

    /** The check began on a Hub picked from the found list, so Back from it returns to the list, not to the address. */
    private var fromList = false

    /** Open the manual flow, optionally prefilled. */
    fun startManual(host: String = "", port: Int = DEFAULT_PORT) {
        confirmed = false
        fromList = false
        _state.value = PairUi(step = Step.Address, host = host, port = port)
    }

    /** A Hub found on the network: straight to its fingerprint check; if that fails, the first screen says why. */
    fun connectDiscovered(host: String, port: Int) = probe(host, port, Step.Choose)

    fun submitAddress(hostInput: String, portInput: String) {
        if (_state.value.busy) return
        val host = hostInput.trim()
        val port = if (portInput.isBlank()) DEFAULT_PORT else portInput.trim().toIntOrNull()
        if (host.isEmpty()) return fail(host, DEFAULT_PORT, R.string.pair_address_error_empty, PairField.Address)
        if (port == null || port !in 1..65535) {
            return fail(host, DEFAULT_PORT, R.string.pair_address_error_port, PairField.Port)
        }
        probe(host, port, Step.Address)
    }

    /** Reads the certificate [host]:[port] presents; the screen it was asked from ([from]) shows a failure. */
    private fun probe(host: String, port: Int, from: Step) {
        if (_state.value.busy) return
        confirmed = false
        fromList = from == Step.Choose
        _state.value = PairUi(step = from, host = host, port = port, busy = true)
        scope.launch {
            try {
                val fp = backend.probe(host, port)
                confirmed = settings.skipsFingerprintCheck()
                val next = if (confirmed) Step.Code else Step.Confirm
                _state.value = PairUi(step = next, host = host, port = port, fingerprint = fp)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.value = PairUi(step = from, host = host, port = port, error = errorText(e))
            }
        }
    }

    /** The user compared the fingerprint with the one on the server and it matches. */
    fun confirmFingerprint() {
        val s = _state.value
        if (s.step != Step.Confirm || s.fingerprint == null) return
        confirmed = true
        _state.value = s.copy(step = Step.Code, error = null)
    }

    /** "It does not match": nothing was paired, and the first screen says so. */
    fun rejectFingerprint() {
        confirmed = false
        fromList = false
        _state.value = PairUi(error = PairMessage.Res(R.string.pair_fingerprint_rejected))
    }

    fun submitCode(codeInput: String) {
        val s = _state.value
        val fp = s.fingerprint
        if (!confirmed || s.step != Step.Code || fp == null || s.busy) return
        val code = codeInput.trim()
        if (!CODE.matches(code)) {
            _state.value = s.copy(error = PairMessage.Res(R.string.pair_code_error_length))
            return
        }
        _state.value = s.copy(busy = true, error = null)
        scope.launch {
            try {
                val token = backend.pair(s.host, s.port, fp, code)
                val name = try {
                    backend.info(s.host, s.port, fp, token).name
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                    s.host
                }
                settings.save(ServerConfig(listOf(s.host), s.port, fp, token, name))
                _state.value = s.copy(step = Step.Done, busy = false, error = null)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.value = failure(s.copy(busy = false), e, MismatchSource.MANUAL)
            }
        }
    }

    /** A pairing QR was scanned: verify the addresses in order with `info()`, then save once; nothing is saved or cleared on failure. */
    fun onQrScanned(text: String) {
        if (_state.value.busy) return
        val payload = try {
            parsePairingUri(text)
        } catch (e: IllegalArgumentException) {
            _state.value = PairUi(error = PairMessage.Res(R.string.pair_error_not_code))
            return
        }
        confirmed = false
        val host = payload.host
        _state.value = PairUi(step = Step.Choose, host = host, port = payload.port, busy = true)
        scope.launch {
            try {
                val endpoints = (listOf(host) + payload.ips).distinct()
                var mismatch: FingerprintMismatch? = null
                var lastError: Exception? = null
                var winner: String? = null
                var name = host
                for (candidate in endpoints) {
                    try {
                        name = backend.info(candidate, payload.port, payload.fingerprint, payload.token).name
                        winner = candidate
                        break
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: FingerprintMismatch) {
                        if (mismatch == null) mismatch = e
                    } catch (e: Exception) {
                        lastError = e
                    }
                }
                if (winner == null) throw (mismatch ?: lastError ?: IOException("No address answered"))
                // `info` needs no token; claim it now, before saving, or the server drops it after 10 minutes.
                try {
                    backend.claim(winner, payload.port, payload.fingerprint, payload.token)
                } catch (e: ApiError) {
                    if (e.code == "unauthorized") {
                        _state.value = PairUi(step = Step.Choose, host = host, port = payload.port, error = QR_EXPIRED)
                        return@launch
                    }
                    // Any other answer from the server means the token passed its check (and is now claimed).
                    if (e.status <= 0) throw e
                }
                val ordered = listOf(winner) + endpoints.filter { it != winner }
                settings.save(ServerConfig(ordered, payload.port, payload.fingerprint, payload.token, name))
                _state.value = PairUi(step = Step.Done, host = host, port = payload.port)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.value = failure(PairUi(step = Step.Choose, host = host, port = payload.port), e, MismatchSource.QR)
            }
        }
    }

    /** Local network access was granted: the notice that asked for it is over. */
    fun localNetworkGranted() {
        _state.update { if (it.error == PairMessage.LocalNetwork) it.copy(error = null) else it }
    }

    /** Leave an error or mismatch and start over. */
    fun pairAgain() {
        confirmed = false
        fromList = false
        _state.value = PairUi()
    }

    /**
     * One step back, for the system Back and the on-screen Back alike. The fingerprint check and the code go back to
     * the address with it filled in (to the first screen when the Hub was picked from the found list); the address and
     * a stopped pairing go back to the first screen.
     */
    fun back() {
        val s = _state.value
        if (s.busy) return
        confirmed = false
        val toAddress = s.mismatch == null && !fromList && (s.step == Step.Confirm || s.step == Step.Code)
        fromList = false
        _state.value = if (toAddress) PairUi(step = Step.Address, host = s.host, port = s.port) else PairUi()
    }

    /** Another screen hit a changed server certificate: show both fingerprints until the user chooses "Pair again". */
    fun showMismatch(expected: String, actual: String) {
        confirmed = false
        _state.value = PairUi(mismatch = Mismatch(expected, actual))
    }

    private fun fail(host: String, port: Int, @StringRes message: Int, field: PairField) {
        _state.value = PairUi(step = Step.Address, host = host, port = port, error = PairMessage.Res(message), errorField = field)
    }

    private fun failure(base: PairUi, e: Exception, source: MismatchSource): PairUi =
        if (e is FingerprintMismatch) base.copy(mismatch = Mismatch(e.expected, e.actual, source), error = null)
        else base.copy(error = errorText(e))

    /** The sentence for a failure (05-android-app 4.9); the Hub's own words when the table has no row for what it said. */
    private fun errorText(e: Exception): PairMessage {
        val unreachable = e is ApiError && e.code == "offline" || e is IOException && e !is FingerprintMismatch
        return when {
            e is ApiError && e.code == "local_network" -> PairMessage.LocalNetwork
            unreachable && localNetworkMissing() -> PairMessage.LocalNetwork
            // a service that does not speak TLS, or whose handshake fails: something answers, but not a Hub
            e is SSLException && e !is FingerprintMismatch -> PairMessage.Res(R.string.pair_error_not_hub)
            unreachable -> PairMessage.Res(R.string.common_hub_unreachable)
            // an error page of another service (no Hub message): not a Hub, whatever the status
            e is ApiError && e.noHubMessage && e.status > 0 -> PairMessage.Res(R.string.pair_error_not_hub)
            e is ApiError && e.code == "unauthorized" -> PairMessage.Res(R.string.pair_error_refused)
            e is ApiError && (e.code == "bad_response" || e.status == 404 || e.status == 405) ->
                PairMessage.Res(R.string.pair_error_not_hub)
            e is ApiError -> PairMessage.Raw(e.message)
            else -> PairMessage.Res(R.string.pair_error_not_hub)
        }
    }
}
