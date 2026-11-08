package com.thompsonfabco.filamentkit.ui.pair

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.data.SettingsStore
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LOCAL_NETWORK_MESSAGE
import com.thompsonfabco.filamentkit.net.LocalNetwork
import com.thompsonfabco.filamentkit.pairing.parsePairingUri
import java.io.IOException
import java.security.SecureRandom
import java.util.Random
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

data class PairUi(
    val step: Step = Step.Choose,
    val host: String = "",
    val port: Int = DEFAULT_PORT,
    /** Lowercase hex, no spaces. On the Confirm step it is shown only through [fingerprintPrompt]. */
    val fingerprint: String? = null,
    /** Which groups of [fingerprint] the user must type from the server, 0-based; chosen once per probe. */
    val askedGroups: List<Int> = emptyList(),
    val busy: Boolean = false,
    val error: String? = null,
    val mismatch: Mismatch? = null,
)

/** `0123456789ab` -> `0123 4567 89ab`. */
fun groupFingerprint(fingerprint: String): String = fingerprint.chunked(4).joinToString(" ")

private const val GROUP_CHARS = 4
private const val ASKED_GROUPS = 2

/**
 * Two different groups, not one: at the cost of a few days' grinding a forged certificate can match two chosen groups of
 * the real fingerprint, which would pass a one-group check 1 time in 8 but a two-group check 1 time in 120.
 */
fun pickAskedGroups(groupCount: Int, random: Random = SecureRandom()): List<Int> =
    (0 until groupCount).shuffled(random).take(ASKED_GROUPS).sorted()

/** The fingerprint's groups in order, null where the user must type: an asked group is never on the phone's screen. */
fun fingerprintPrompt(fingerprint: String, asked: List<Int>): List<String?> =
    fingerprint.chunked(GROUP_CHARS).mapIndexed { i, group -> if (i in asked) null else group }

/** [typed] holds one entry per [asked] group, in the same order; case does not matter. */
fun askedGroupsMatch(fingerprint: String, asked: List<Int>, typed: List<String>): Boolean {
    val groups = fingerprint.chunked(GROUP_CHARS)
    return asked.isNotEmpty() && typed.size == asked.size &&
        asked.zip(typed).all { (i, t) -> groups.getOrNull(i) == t.trim().lowercase() }
}

private val CODE = Regex("[0-9]{6}")
private const val UNEXPECTED = "Unexpected response from the server"

/** The scanned QR's token was not accepted when the app first used it. */
const val QR_EXPIRED =
    "This pairing code has expired or was already used. Make a new one on your server's setup page, or run " +
        "\"sudo filament-kit pair\" on the server."

/**
 * Pairing flows: QR scan, and manual entry (address, then two groups of the server's certificate fingerprint for the
 * user to type from the server, then the 6-digit code). Nothing is sent to the server except the probe handshake until
 * they match. [pickGroups] chooses the groups from the group count. [scope] defaults to the ViewModel's own; tests pass one. [localNetworkMissing] turns
 * "can't reach the server" into the local network permission message when that permission is the cause.
 */
class PairViewModel(
    private val settings: SettingsStore,
    private val backend: PairingBackend,
    scope: CoroutineScope? = null,
    private val localNetworkMissing: () -> Boolean = { LocalNetwork.missing() },
    private val pickGroups: (Int) -> List<Int> = { pickAskedGroups(it) },
) : ViewModel() {
    private val scope: CoroutineScope = scope ?: viewModelScope
    private val _state = MutableStateFlow(PairUi())
    val state: StateFlow<PairUi> = _state

    private var confirmed = false

    /** Open the manual flow, optionally prefilled. */
    fun startManual(host: String = "", port: Int = DEFAULT_PORT) {
        confirmed = false
        _state.value = PairUi(step = Step.Address, host = host, port = port)
    }

    /** A server found on the network: straight to its fingerprint check; if that fails, the address form says why. */
    fun connectDiscovered(host: String, port: Int) = submitAddress(host, port.toString())

    fun submitAddress(hostInput: String, portInput: String) {
        if (_state.value.busy) return
        val host = hostInput.trim()
        val port = if (portInput.isBlank()) DEFAULT_PORT else portInput.trim().toIntOrNull()
        if (host.isEmpty()) return fail(Step.Address, "Enter the server's address", host, DEFAULT_PORT)
        if (port == null || port !in 1..65535) {
            return fail(Step.Address, "The port must be a number from 1 to 65535", host, DEFAULT_PORT)
        }
        confirmed = false
        _state.value = PairUi(step = Step.Address, host = host, port = port, busy = true)
        scope.launch {
            try {
                val fp = backend.probe(host, port)
                val asked = pickGroups(fp.chunked(GROUP_CHARS).size)
                _state.value = PairUi(step = Step.Confirm, host = host, port = port, fingerprint = fp, askedGroups = asked)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val text = if (e is IOException && e !is FingerprintMismatch && !localNetworkMissing()) {
                    "Could not reach $host on port $port. Check the address and that this phone is on the same network."
                } else errorText(e)
                _state.value = PairUi(step = Step.Address, host = host, port = port, error = text)
            }
        }
    }

    /**
     * The user typed the asked groups from the server. A wrong entry keeps the same groups: a typo must not hand a
     * forged certificate another draw of the groups.
     */
    fun confirmFingerprint(typed: List<String>) {
        val s = _state.value
        val fp = s.fingerprint
        if (s.step != Step.Confirm || fp == null) return
        if (!askedGroupsMatch(fp, s.askedGroups, typed)) {
            _state.value = s.copy(error = PairTexts.FINGERPRINT_WRONG)
            return
        }
        confirmed = true
        _state.value = s.copy(step = Step.Code, error = null)
    }

    fun rejectFingerprint() {
        confirmed = false
        _state.update { it.copy(step = Step.Address, fingerprint = null, askedGroups = emptyList(), error = null) }
    }

    fun submitCode(codeInput: String) {
        val s = _state.value
        val fp = s.fingerprint
        if (!confirmed || s.step != Step.Code || fp == null || s.busy) return
        val code = codeInput.trim()
        if (!CODE.matches(code)) {
            _state.value = s.copy(error = "Enter the 6-digit code shown on the server")
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
            _state.value = PairUi(error = "That is not a filament-kit pairing code")
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

    /** Leave an error or mismatch and start over. */
    fun pairAgain() {
        confirmed = false
        _state.value = PairUi()
    }

    /** Another screen hit a changed server certificate: show both fingerprints until the user chooses "Pair again". */
    fun showMismatch(expected: String, actual: String) {
        confirmed = false
        _state.value = PairUi(mismatch = Mismatch(expected, actual))
    }

    private fun fail(step: Step, message: String, host: String, port: Int) {
        _state.value = PairUi(step = step, host = host, port = port, error = message)
    }

    private fun failure(base: PairUi, e: Exception, source: MismatchSource): PairUi =
        if (e is FingerprintMismatch) base.copy(mismatch = Mismatch(e.expected, e.actual, source), error = null)
        else base.copy(error = errorText(e))

    private fun errorText(e: Exception): String = when {
        e is ApiError && e.code == "local_network" -> LOCAL_NETWORK_MESSAGE
        (e is ApiError && e.code == "offline" || e is IOException && e !is FingerprintMismatch) && localNetworkMissing() ->
            LOCAL_NETWORK_MESSAGE
        e is ApiError && e.code == "offline" ->
            "Can't reach the server. Check that this phone is on the same network."
        e is ApiError -> e.message
        e is FingerprintMismatch -> "The server's certificate is not the one you paired with."
        e is IOException -> "Can't reach the server. Check that this phone is on the same network."
        else -> UNEXPECTED
    }
}
