package com.thompsonfabco.filamentkit.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwDialog
import com.thompsonfabco.filamentkit.ui.components.SwDialogButton
import com.thompsonfabco.filamentkit.ui.components.SwProgress
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.update.UpdateFailure
import com.thompsonfabco.filamentkit.update.UpdateUi

/** What the buttons of the update panel do. */
internal class UpdateActions(
    val install: () -> Unit,
    val cancel: () -> Unit,
    val openSettings: () -> Unit,
    val tapToInstall: () -> Unit,
    val tryAgain: () -> Unit,
)

/**
 * App updates (05-android-app 12.4): the app's and the Hub's version, the update panel of section 13 and the
 * "Check for updates" button.
 */
@Composable
internal fun UpdatesSettings(
    appVersion: String,
    hubVersion: String?,
    update: UpdateUi,
    actions: UpdateActions,
    onCheck: () -> Unit,
    modifier: Modifier = Modifier,
    /** False: no Hub is paired, so there is nobody to ask. */
    paired: Boolean = true,
) {
    SettingsPage(modifier) {
        SettingsPanel {
            FieldRow(stringResource(R.string.settings_updates_this_app), appVersion, mono = true)
            hubVersion?.let { FieldRow(stringResource(R.string.settings_updates_on_hub), it, mono = true) }
        }
        UpdatePanel(update, appVersion, actions)
        SwButton(
            stringResource(if (update.checking) R.string.common_checking else R.string.settings_updates_check), onCheck,
            Modifier.fillMaxWidth(), kind = SwButtonKind.Quiet, enabled = paired && !update.checking && !update.busy,
        )
        if (!paired) {
            Text(
                stringResource(R.string.settings_updates_check_unpaired), color = SpoolwardenTheme.colors.muted,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

/**
 * The update panel (section 13): the notice for the state [updatePanel] names, with its button. The same panel serves
 * Home's one-line notice link once that screen is rebuilt.
 */
@Composable
internal fun UpdatePanel(update: UpdateUi, appVersion: String, actions: UpdateActions, modifier: Modifier = Modifier) {
    val space = SpoolwardenTheme.space
    var explain by remember { mutableStateOf(false) }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(space.s3)) {
        when (val panel = updatePanel(update)) {
            UpdatePanelState.Unknown -> Unit
            UpdatePanelState.UpToDate -> NoticeCard(NoticeKind.Ok, stringResource(R.string.settings_updates_up_to_date))
            UpdatePanelState.Offered -> {
                NoticeCard(NoticeKind.Info, offered(update, appVersion))
                InstallButton(actions.install)
            }
            is UpdatePanelState.HubNewer -> {
                NoticeCard(NoticeKind.Warn, stringResource(R.string.app_update_hub_newer))
                if (panel.canInstall) InstallButton(actions.install)
            }
            is UpdatePanelState.Downloading -> {
                val words = panel.percent?.let { stringResource(R.string.app_update_downloading, it) }
                    ?: stringResource(R.string.app_update_downloading_unknown)
                SwProgress(panel.percent?.let { it / PERCENT }, state = words)
                Text(
                    words, Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                    style = MaterialTheme.typography.bodyMedium,
                )
                SwButton(stringResource(R.string.common_cancel), actions.cancel, kind = SwButtonKind.Quiet, enabled = !panel.writing)
                if (panel.writing) {
                    Text(
                        stringResource(R.string.app_update_cancel_writing), color = SpoolwardenTheme.colors.muted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            UpdatePanelState.NeedsPermission -> {
                NoticeCard(NoticeKind.Warn, stringResource(R.string.app_update_permission))
                SwButton(stringResource(R.string.common_open_settings), actions.openSettings)
            }
            is UpdatePanelState.Installing -> {
                Text(
                    stringResource(R.string.app_update_installing), Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                    style = MaterialTheme.typography.bodyMedium,
                )
                if (panel.canReopen) SwButton(stringResource(R.string.app_update_tap_install), actions.tapToInstall)
            }
            UpdatePanelState.Waiting -> {
                NoticeCard(NoticeKind.Info, stringResource(R.string.app_update_downloaded))
                SwButton(stringResource(R.string.app_update_tap_install), actions.tapToInstall, kind = SwButtonKind.Main)
            }
            is UpdatePanelState.Failed -> {
                val signature = panel.failure == UpdateFailure.Signature
                NoticeCard(
                    NoticeKind.Bad, stringResource(panel.failure.text),
                    actions = if (signature) listOf(SwAction(stringResource(R.string.app_update_signature_more)) { explain = true }) else emptyList(),
                )
                SwButton(
                    stringResource(R.string.common_try_again), if (panel.canInstall) actions.install else actions.tryAgain,
                    kind = if (signature) SwButtonKind.Plain else SwButtonKind.Main,
                )
            }
        }
    }
    if (explain) {
        SwDialog(
            title = stringResource(R.string.app_update_signature_title),
            onClose = { explain = false },
            confirm = SwDialogButton(stringResource(R.string.common_close), { explain = false }),
        ) { Text(stringResource(R.string.app_update_signature_body), style = MaterialTheme.typography.bodyMedium) }
    }
}

@Composable
private fun InstallButton(onClick: () -> Unit) {
    SwButton(stringResource(R.string.app_update_install), onClick, kind = SwButtonKind.Main)
}

/** "<product> 0.5.3 is on your Hub. This app is 0.5.2." with the Hub's release as the update comes with. */
@Composable
private fun offered(update: UpdateUi, appVersion: String): String =
    stringResource(R.string.app_update_offered, update.offeredVersion.orEmpty(), appVersion)

private const val PERCENT = 100f
