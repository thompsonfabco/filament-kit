package com.thompsonfabco.filamentkit.ui.pair

/** What the mismatch panel says, by [MismatchSource]. */
data class MismatchText(
    val title: String,
    val body: String,
    val expectedLabel: String,
    val actualLabel: String,
    val button: String,
)

/** Texts of the pairing screens. Where a pairing code comes from is said here, so it changes in one place. */
object PairTexts {
    const val SCAN_INTRO = "Show a pairing code on your server's setup page, or run \"sudo filament-kit pair\" on the " +
        "server. Then scan its QR code with this phone."
    const val CODE_INTRO = "Type the 6-digit code shown on the server."

    const val FINGERPRINT_WRONG = "Those groups don't match the fingerprint this server presented. Check them against " +
        "the server. If they really differ, tap It does not match: something else may be answering at this address."

    fun confirmIntro(host: String) = "$host presented a certificate. Find the fingerprint shown with the pairing code " +
        "on the server, and type the two missing groups from it."

    fun mismatch(m: Mismatch, host: String): MismatchText = when (m.source) {
        MismatchSource.STORED -> MismatchText(
            title = "The server's certificate has changed",
            body = "This can happen if the server was reinstalled. If you did not expect that, do not continue.",
            expectedLabel = "Paired fingerprint",
            actualLabel = "Fingerprint now",
            button = "Pair again",
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
            expectedLabel = "Fingerprint you checked",
            actualLabel = "Fingerprint now",
            button = "Start again",
        )
    }
}
