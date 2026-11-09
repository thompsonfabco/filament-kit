package com.thompsonfabco.filamentkit.ui.pair

import java.io.IOException
import java.net.ConnectException
import java.net.UnknownHostException

/** What the mismatch panel says, by [MismatchSource]. */
data class MismatchText(
    val title: String,
    val body: String,
    /** Null: only the certificate the server shows now is listed. */
    val expectedLabel: String?,
    val actualLabel: String,
    val button: String,
    /** The one-tap "keep this pairing" button; only a saved pairing has one. */
    val trustButton: String? = null,
    /** Where the fingerprint above can be compared. */
    val whereToCheck: String? = null,
)

/** Texts of the pairing screens. Where a pairing code comes from is said here, so it changes in one place. */
object PairTexts {
    const val SCAN_INTRO = "Show a pairing code on your server's setup page, or run \"sudo filament-kit pair\" on the " +
        "server. Then scan its QR code with this phone."
    const val CODE_INTRO = "Type the 6-digit code shown on the server."

    fun confirmIntro(host: String) = "$host presented this certificate fingerprint. Compare it with the fingerprint " +
        "shown with the pairing code on the server before you continue."

    const val FINGERPRINT_REJECTED = "The fingerprint didn't match, so something else may be answering at this address."

    const val NONE_FOUND = "Still looking. A VPN or a guest Wi-Fi can hide the server; you can enter its address below."
    const val EMPTY_HOST = "Type the server's name or IP address"

    /** Why the address could not be reached, as far as the phone can tell. */
    fun unreachable(e: IOException, host: String, port: Int): String = when {
        e is UnknownHostException ->
            "Could not find $host. Check the name, or use the server's IP address."
        e is ConnectException && e.message.orEmpty().contains("refused", ignoreCase = true) ->
            "$host answered, but not on port $port. Check the port; the kit's usual one is $DEFAULT_PORT."
        else -> "Could not reach $host on port $port. Check the address and that this phone is on the same network."
    }

    const val SKIP_CHECK_LABEL = "Skip the fingerprint check for new servers"
    const val SKIP_CHECK_HELP = "When you pair by address, the app trusts the certificate the server presents; a " +
        "scanned QR code is checked either way."

    fun mismatch(m: Mismatch, host: String): MismatchText = when (m.source) {
        MismatchSource.STORED -> MismatchText(
            title = "The server's certificate has changed",
            body = "If you didn't reinstall or move the server, another device may be answering at this address, and " +
                "trusting it gives that device this phone's access.",
            expectedLabel = null,
            actualLabel = "New fingerprint",
            button = "Pair again",
            trustButton = "Trust the new certificate",
            whereToCheck = "To check it, compare it with the fingerprint shown with a pairing code on the server.",
        )
        MismatchSource.QR -> MismatchText(
            title = "This pairing code doesn't match the server",
            body = "The server at $host shows a different certificate than this pairing code names. Make a new code " +
                "and scan that. If it still differs, something else may be answering at that address.",
            expectedLabel = "Fingerprint in the code",
            actualLabel = "Fingerprint the server shows",
            button = "Start again",
        )
        MismatchSource.MANUAL -> MismatchText(
            title = "The server's certificate changed while pairing",
            body = "Start again. If it happens again, something else may be answering at $host.",
            expectedLabel = "Fingerprint seen first",
            actualLabel = "Fingerprint now",
            button = "Start again",
        )
    }
}
