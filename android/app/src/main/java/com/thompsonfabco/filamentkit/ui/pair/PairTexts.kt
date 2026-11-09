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

    fun confirmIntro(host: String) = "$host presented this certificate fingerprint. Compare it with the fingerprint " +
        "shown with the pairing code on the server before you continue."

    const val SKIP_CHECK_LABEL = "Skip the fingerprint check for new servers"
    const val SKIP_CHECK_HELP = "When you pair by address, the app trusts the certificate the server presents; a " +
        "scanned QR code is checked either way."

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
            expectedLabel = "Fingerprint seen first",
            actualLabel = "Fingerprint now",
            button = "Start again",
        )
    }
}
