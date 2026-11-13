package com.thompsonfabco.filamentkit.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.nav.HubState
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.StatusKind
import com.thompsonfabco.filamentkit.ui.components.StatusLabel
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwDialog
import com.thompsonfabco.filamentkit.ui.components.SwDialogButton
import com.thompsonfabco.filamentkit.ui.pair.groupFingerprint
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * Hub connection (05-android-app 12.3): the connection state, the Hub's fields, the Hub page, pairing again, the
 * fingerprint check and forgetting the Hub. [setupUrl] gives the Hub page's address at the moment it is opened (the
 * host the app reaches it on now). [onPairAgain] opens pairing; [onForget] clears the pairing and opens it too.
 */
@Composable
internal fun HubSettings(
    hub: SettingsHub?,
    state: HubState,
    skipFingerprintCheck: Boolean,
    onSkipFingerprintCheck: (Boolean) -> Unit,
    onPairAgain: () -> Unit,
    onForget: () -> Unit,
    setupUrl: () -> String?,
    modifier: Modifier = Modifier,
) {
    val space = SpoolwardenTheme.space
    var confirmForget by remember { mutableStateOf(false) }
    var confirmSkip by remember { mutableStateOf(false) }
    var openProblem by remember { mutableStateOf<Int?>(null) }
    val links = LocalUriHandler.current
    val forgetButton = remember { FocusRequester() }
    val skipSwitch = remember { FocusRequester() }
    SettingsPage(modifier) {
        SettingsPanel {
            if (hub == null) {
                Text(stringResource(R.string.settings_hub_none), style = MaterialTheme.typography.bodyMedium)
                SwButton(stringResource(R.string.settings_hub_pair), onPairAgain, Modifier.fillMaxWidth(), kind = SwButtonKind.Main)
            } else {
                val badge = state.badge
                if (badge != null) StatusLabel(badge) else Text(stringResource(R.string.common_checking))
                FieldRow(stringResource(R.string.settings_hub_field_hub), hub.name)
                FieldRow(stringResource(R.string.settings_hub_field_address), hub.address, mono = true)
                FieldRow(
                    stringResource(R.string.settings_hub_field_fingerprint), groupFingerprint(hub.fingerprint),
                    mono = true, selectable = true,
                )
                hub.version?.let { FieldRow(stringResource(R.string.settings_hub_field_version), it, mono = true) }
            }
        }
        if (hub != null) {
            Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
                SwButton(stringResource(R.string.common_open_hub_page), {
                    val url = setupUrl()
                    openProblem = when {
                        url == null -> R.string.settings_hub_page_error_address
                        runCatching { links.openUri(url) }.isSuccess -> null
                        else -> R.string.settings_hub_page_error_browser
                    }
                }, Modifier.fillMaxWidth())
                Text(
                    stringResource(R.string.settings_hub_page_line), color = SpoolwardenTheme.colors.muted,
                    style = MaterialTheme.typography.bodySmall,
                )
                openProblem?.let { NoticeCard(NoticeKind.Bad, stringResource(it)) }
            }
            SwButton(stringResource(R.string.common_pair_again), onPairAgain, Modifier.fillMaxWidth())
        }
        GroupTitle(stringResource(R.string.settings_hub_security_title))
        FingerprintCheckRow(
            on = fingerprintCheckOn(skipFingerprintCheck),
            onChange = { on -> if (needsSkipConfirmation(on)) confirmSkip = true else onSkipFingerprintCheck(false) },
            modifier = Modifier.focusRequester(skipSwitch),
        )
        if (hub != null) {
            SettingsDivider()
            SwButton(
                stringResource(R.string.settings_hub_forget), { confirmForget = true },
                Modifier.fillMaxWidth().focusRequester(forgetButton), kind = SwButtonKind.Destructive,
            )
        }
    }
    if (confirmSkip) {
        SwDialog(
            title = stringResource(R.string.settings_hub_skip_title),
            onClose = { confirmSkip = false },
            confirm = SwDialogButton(
                stringResource(R.string.settings_hub_skip_confirm), { confirmSkip = false; onSkipFingerprintCheck(true) },
                kind = SwButtonKind.DestructiveFilled,
            ),
            cancel = SwAction(stringResource(R.string.common_cancel)) { confirmSkip = false },
            returnFocusTo = skipSwitch,
        ) { Text(stringResource(R.string.settings_hub_skip_body), style = MaterialTheme.typography.bodyMedium) }
    }
    if (confirmForget && hub != null) {
        SwDialog(
            title = stringResource(R.string.settings_hub_forget_title, hub.name),
            onClose = { confirmForget = false },
            confirm = SwDialogButton(
                stringResource(R.string.common_forget), { confirmForget = false; onForget() }, kind = SwButtonKind.DestructiveFilled,
            ),
            cancel = SwAction(stringResource(R.string.common_cancel)) { confirmForget = false },
            returnFocusTo = forgetButton,
        ) { Text(stringResource(R.string.settings_hub_forget_body), style = MaterialTheme.typography.bodyMedium) }
    }
}

/**
 * The switch row of 02-components 5.6 for a toggle that guards security: the label, the switch, the state word after it
 * ("On" is the safe position) and, while it is off, the Needs a look badge; the hint under it at body size.
 */
@Composable
private fun FingerprintCheckRow(on: Boolean, onChange: (Boolean) -> Unit, modifier: Modifier = Modifier) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    Column(verticalArrangement = Arrangement.spacedBy(space.s1)) {
        Row(
            modifier.fillMaxWidth().defaultMinSize(minHeight = SpoolwardenTheme.sizes.row)
                .toggleable(value = on, role = Role.Switch, onValueChange = onChange),
            horizontalArrangement = Arrangement.spacedBy(space.s3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(stringResource(R.string.settings_hub_check_title), Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
            Switch(
                checked = on, onCheckedChange = null,
                colors = SwitchDefaults.colors(
                    checkedTrackColor = colors.accentText, checkedThumbColor = colors.surface, checkedBorderColor = colors.accentText,
                    uncheckedTrackColor = colors.surface3, uncheckedThumbColor = colors.muted, uncheckedBorderColor = colors.borderStrong,
                ),
            )
            Text(
                stringResource(if (on) R.string.settings_hub_check_on else R.string.settings_hub_check_off),
                color = if (on) colors.accentText else colors.muted, style = SpoolwardenTheme.type.dataSmall,
            )
            if (!on) StatusLabel(StatusKind.NeedsLook, small = true)
        }
        Text(stringResource(R.string.settings_hub_check_help), color = colors.muted, style = MaterialTheme.typography.bodyMedium)
    }
}
