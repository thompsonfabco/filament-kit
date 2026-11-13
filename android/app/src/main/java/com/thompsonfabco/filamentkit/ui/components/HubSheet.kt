package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.nav.HubState
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** What the Hub connection sheet shows about the Hub (05-android-app 2.4). */
internal class HubFacts(val name: String, val address: String, val appVersion: String, val hubVersion: String?)

/** What its one button does, by state. */
internal class HubSheetActions(
    val tryAgain: () -> Unit,
    val reviewCertificate: () -> Unit,
    val pairAgain: () -> Unit,
    val allow: () -> Unit,
    val openAppSettings: () -> Unit,
    val hubSettings: () -> Unit,
)

/**
 * The Hub connection sheet: the state in a sentence, the Hub's name and address, the versions, and one button by state.
 * [state] is the last known one; [checking] is true while a new check runs. [showAppSettings] is true once Android no
 * longer shows its permission dialog. The "last answer" row is not here: the session does not keep that time yet.
 */
@Composable
internal fun HubSheet(
    state: HubState,
    checking: Boolean,
    facts: HubFacts,
    showAppSettings: Boolean,
    actions: HubSheetActions,
    onDismiss: () -> Unit,
) {
    val space = SpoolwardenTheme.space
    SwSheet(onDismiss) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = space.s4).navigationBarsPadding().padding(bottom = space.s4),
            verticalArrangement = Arrangement.spacedBy(space.s3),
        ) {
            Text(stringResource(R.string.hub_sheet_title), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(state.sentence, facts.name, facts.address), style = MaterialTheme.typography.bodyMedium)
            Column {
                Text(facts.name, style = MaterialTheme.typography.titleMedium)
                Text(facts.address, style = SpoolwardenTheme.type.data, color = SpoolwardenTheme.colors.muted)
            }
            Text(
                if (facts.hubVersion != null) {
                    stringResource(R.string.hub_sheet_versions, facts.appVersion, facts.hubVersion)
                } else {
                    stringResource(R.string.hub_sheet_version_unknown)
                },
                style = SpoolwardenTheme.type.dataSmall,
            )
            when (state) {
                HubState.Offline -> SheetButton(
                    stringResource(if (checking) R.string.common_checking else R.string.common_try_again),
                    actions.tryAgain, enabled = !checking, spinning = checking,
                )
                HubState.CertificateChanged -> SheetButton(stringResource(R.string.common_review_certificate), actions.reviewCertificate)
                HubState.NoLongerPaired -> SheetButton(stringResource(R.string.common_pair_again), actions.pairAgain)
                HubState.NeedsLocalNetwork -> if (showAppSettings) {
                    SheetButton(stringResource(R.string.common_open_app_settings), actions.openAppSettings)
                } else {
                    SheetButton(stringResource(R.string.common_allow), actions.allow)
                }
                HubState.Connected -> TextButton(
                    onClick = actions.hubSettings,
                    colors = ButtonDefaults.textButtonColors(contentColor = SpoolwardenTheme.colors.accentText),
                ) { Text(stringResource(R.string.hub_sheet_settings), style = MaterialTheme.typography.labelLarge) }
                HubState.Checking -> Unit
            }
        }
    }
}

/** The filled main button of the sheet. */
@Composable
private fun SheetButton(text: String, onClick: () -> Unit, enabled: Boolean = true, spinning: Boolean = false) {
    val colors = SpoolwardenTheme.colors
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = SpoolwardenTheme.density.control),
        shape = SpoolwardenTheme.shapes.r,
        elevation = null,
        colors = ButtonDefaults.buttonColors(
            containerColor = colors.accent, contentColor = colors.onAccent,
            disabledContainerColor = colors.accent, disabledContentColor = colors.onAccent,
        ),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2), verticalAlignment = Alignment.CenterVertically) {
            if (spinning) {
                CircularProgressIndicator(
                    Modifier.size(SpoolwardenTheme.space.s4), color = colors.onAccent, strokeWidth = SpoolwardenTheme.space.s1 / 2,
                )
            }
            Text(text, style = MaterialTheme.typography.labelLarge)
        }
    }
}
