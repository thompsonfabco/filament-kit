package com.thompsonfabco.filamentkit.ui.pair

import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.LocalNetworkAccess
import com.thompsonfabco.filamentkit.ui.components.LocalNetworkNotice
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind

/** What the certificate question says (05-android-app 4.8), by [MismatchSource]. */
internal class MismatchText(
    val title: String,
    val body: String,
    /** Null: no earlier fingerprint is listed. */
    val expectedLabel: String?,
    val actualLabel: String,
    /** The fingerprints are listed under their labels; false when the question is about the check just made. */
    val showsFingerprints: Boolean,
    val button: String,
    /** The one-tap "keep this pairing" button; only a saved pairing has one. */
    val trustButton: String? = null,
    /** Where the fingerprints above can be compared. */
    val whereToCheck: String? = null,
)

@Composable
internal fun mismatchText(source: MismatchSource): MismatchText = when (source) {
    MismatchSource.STORED -> MismatchText(
        title = stringResource(R.string.pair_cert_stored_title),
        body = stringResource(R.string.pair_cert_stored_body),
        expectedLabel = stringResource(R.string.pair_cert_stored_paired_with),
        actualLabel = stringResource(R.string.pair_cert_stored_now_shows),
        showsFingerprints = true,
        button = stringResource(R.string.common_pair_again),
        trustButton = stringResource(R.string.pair_cert_stored_trust),
        whereToCheck = stringResource(R.string.pair_cert_stored_hint),
    )
    MismatchSource.QR -> MismatchText(
        title = stringResource(R.string.pair_cert_qr_title),
        body = stringResource(R.string.pair_cert_qr_body),
        expectedLabel = stringResource(R.string.pair_cert_qr_expects),
        actualLabel = stringResource(R.string.pair_cert_qr_shows),
        showsFingerprints = true,
        button = stringResource(R.string.pair_cert_start_again),
    )
    MismatchSource.MANUAL -> MismatchText(
        title = stringResource(R.string.pair_cert_manual_title),
        body = stringResource(R.string.pair_cert_manual_body),
        expectedLabel = null,
        actualLabel = "",
        showsFingerprints = false,
        button = stringResource(R.string.pair_cert_start_again),
    )
}

/** The sentence of a [PairMessage] (05-android-app 4.9). */
@Composable
internal fun PairMessage.text(): String = when (this) {
    is PairMessage.Res -> stringResource(id, *args.toTypedArray())
    is PairMessage.Raw -> text
    PairMessage.LocalNetwork -> stringResource(R.string.network_text)
}

/** A failure under a step's button: the notice line, or for a missing local network permission the panel of 05 3.3. */
@Composable
internal fun PairErrorLine(message: PairMessage, access: LocalNetworkAccess?) {
    if (message == PairMessage.LocalNetwork && access != null) {
        LocalNetworkNotice(access)
    } else {
        NoticeCard(NoticeKind.Bad, message.text())
    }
}
