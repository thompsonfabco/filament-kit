package com.thompsonfabco.filamentkit.ui.pair

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.StatusKind
import com.thompsonfabco.filamentkit.ui.components.StatusLabel
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwDialog
import com.thompsonfabco.filamentkit.ui.components.SwDialogButton
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * The fingerprint-check switch as 02-components 5.6 words a toggle that guards security: under the heading
 * "Security", "Check the fingerprint when pairing by address", On (the safe position) by default, with the risk of Off
 * in full beneath. Turning it off asks first ("Skip the fingerprint check?"); while it is off the row carries the Needs
 * a look badge. Pairing no longer shows it (05-android-app 4.3); Settings does. [skip] is the stored choice: true means
 * the check is not made.
 */
@Composable
internal fun SkipCheckSwitch(skip: Boolean, onSkip: (Boolean) -> Unit) {
    val space = SpoolwardenTheme.space
    var asking by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(space.s1)) {
        Text(
            stringResource(R.string.settings_hub_security_title), style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.semantics { heading() },
        )
        Row(
            Modifier.fillMaxWidth().defaultMinSize(minHeight = SpoolwardenTheme.density.row)
                .toggleable(value = !skip, role = Role.Switch) { on -> if (on) onSkip(false) else asking = true },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(stringResource(R.string.settings_hub_check_title), Modifier.weight(1f).padding(end = space.s3))
            if (skip) StatusLabel(StatusKind.NeedsLook, Modifier.padding(end = space.s2), small = true)
            Text(
                stringResource(if (skip) R.string.status_off else R.string.status_on),
                style = SpoolwardenTheme.type.dataSmall,
                color = if (skip) SpoolwardenTheme.colors.muted else SpoolwardenTheme.colors.accentText,
                modifier = Modifier.padding(end = space.s2),
            )
            Switch(checked = !skip, onCheckedChange = null)
        }
        Text(stringResource(R.string.settings_hub_check_help), style = MaterialTheme.typography.bodyMedium)
    }
    if (asking) {
        SwDialog(
            title = stringResource(R.string.settings_hub_skip_title),
            onClose = { asking = false },
            confirm = SwDialogButton(
                stringResource(R.string.settings_hub_skip_confirm),
                { asking = false; onSkip(true) },
                kind = SwButtonKind.DestructiveFilled,
            ),
            cancel = SwAction(stringResource(R.string.common_cancel)) { asking = false },
        ) {
            Text(stringResource(R.string.settings_hub_skip_body), style = MaterialTheme.typography.bodyMedium)
        }
    }
}
