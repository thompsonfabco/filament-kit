package com.thompsonfabco.filamentkit.ui.printers

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.LOCAL_NETWORK_MESSAGE
import com.thompsonfabco.filamentkit.ui.components.HubNotice
import com.thompsonfabco.filamentkit.ui.components.HubNoticeKind
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

// What the camera players say when there is no picture (05-android-app 9.4). The players pass a code: the Hub's error
// code, or one of these.

/** The Hub said 401: the Hub notice stands in place of the picture. */
internal const val CAMERA_UNAUTHORIZED = "unauthorized"

/** The app lacks the local network permission (API 37 and later). */
internal const val CAMERA_LOCAL_NETWORK = "local_network"

/** The stream broke off or ended with no code of the Hub's: the "any other code" row. */
internal const val CAMERA_INTERRUPTED = "interrupted"

/** "Waiting for the camera picture…", `muted`, centred. */
@Composable
internal fun CameraWaiting() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            stringResource(R.string.printer_camera_waiting), Modifier.padding(SpoolwardenTheme.space.s3),
            color = SpoolwardenTheme.colors.muted, textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyMedium,
        )
    }
}

/** The failure in place of the picture: a `Bad` notice with its text and "Try again", or the Hub notice for 401. */
@Composable
internal fun CameraFailure(code: String, onTryAgain: () -> Unit, onPairAgain: () -> Unit) {
    Box(Modifier.fillMaxSize().padding(SpoolwardenTheme.space.s2), contentAlignment = Alignment.Center) {
        when (code) {
            CAMERA_UNAUTHORIZED -> HubNotice(HubNoticeKind.NoLongerPaired, onPairAgain)
            CAMERA_LOCAL_NETWORK -> NoticeCard(
                NoticeKind.Bad, LOCAL_NETWORK_MESSAGE, actions = listOf(SwAction(stringResource(R.string.common_try_again), onTryAgain)),
            )
            else -> NoticeCard(
                NoticeKind.Bad, stringResource(cameraErrorText(code)),
                actions = listOf(SwAction(stringResource(R.string.common_try_again), onTryAgain)),
            )
        }
    }
}
