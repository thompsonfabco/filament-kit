package com.thompsonfabco.filamentkit.ui.settings

import android.Manifest
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.core.app.NotificationManagerCompat
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.alerts.AlertTexts
import com.thompsonfabco.filamentkit.alerts.SwitchStep
import com.thompsonfabco.filamentkit.alerts.switchStep
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.openAppSettings
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** What the Alerts group does; the app wires each to its owner. */
internal class AlertsActions(
    /** The switch, already allowed to change: turning on starts the watching service, off stops it. */
    val onSwitch: (Boolean) -> Unit = {},
    val onTest: () -> Unit = {},
    val onRecent: () -> Unit = {},
    /** Asks Android for the local network permission (API 37+). */
    val requestLocalNetwork: () -> Unit = {},
)

/** Which help the switch is showing after a refusal. */
private enum class Help { Notifications, LocalNetwork }

/**
 * Alerts (R80 section 8): the switch "Alerts on this phone", Send a test alert, and Recent alerts. Turning it on asks
 * for Android's notification permission (API 33+) and the local network permission; when one is refused the switch
 * stays off and the help says what to allow.
 */
@Composable
internal fun AlertsSettings(facts: AlertsFacts, actions: AlertsActions, modifier: Modifier = Modifier) {
    val space = SpoolwardenTheme.space
    val context = LocalContext.current
    var help by remember { mutableStateOf<Help?>(null) }
    var testSent by remember { mutableStateOf(false) }

    fun notificationsAllowed() = NotificationManagerCompat.from(context).areNotificationsEnabled()

    // The permission answer: allowed goes on to the next step; refused leaves the switch off with the help.
    fun turnOn(afterNotifications: Boolean = false, ask: () -> Unit = {}) {
        when (switchStep(notificationsAllowed(), facts.localNetworkGranted)) {
            SwitchStep.TurnOn -> {
                help = null
                actions.onSwitch(true)
            }
            SwitchStep.AskNotifications -> {
                help = Help.Notifications
                if (!afterNotifications) ask()
            }
            SwitchStep.AskLocalNetwork -> {
                help = Help.LocalNetwork
                actions.requestLocalNetwork()
            }
        }
    }
    val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { turnOn(afterNotifications = true) }
    val ask: () -> Unit = {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    SettingsPage(modifier) {
        if (!facts.available) NoticeCard(NoticeKind.Info, AlertTexts.UNAVAILABLE)
        SettingsPanel {
            AlertsSwitchRow(
                on = facts.on,
                onChange = { on ->
                    testSent = false
                    if (on) turnOn(ask = ask) else {
                        help = null
                        actions.onSwitch(false)
                    }
                },
            )
            val shown = help
            if (shown != null && !facts.on) {
                when (shown) {
                    Help.Notifications -> NoticeCard(
                        NoticeKind.Warn, AlertTexts.NOTIFICATIONS_DENIED_HELP,
                        actions = listOf(SwAction(stringResource(R.string.common_open_app_settings)) { context.openAppSettings() }),
                    )
                    Help.LocalNetwork -> NoticeCard(NoticeKind.Warn, AlertTexts.LOCAL_NETWORK_HELP)
                }
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
            SwButton(
                stringResource(R.string.settings_alerts_test),
                { testSent = true; actions.onTest() },
                Modifier.fillMaxWidth(), enabled = facts.on,
            )
            if (testSent) Text(stringResource(R.string.settings_alerts_sent), color = SpoolwardenTheme.colors.muted, style = MaterialTheme.typography.bodySmall)
        }
        SwButton(AlertTexts.RECENT_ALERTS, actions.onRecent, Modifier.fillMaxWidth())
    }
}

/** The switch row of 02-components 5.6: the label, the switch, the state word; the hint under it at body size. */
@Composable
private fun AlertsSwitchRow(on: Boolean, onChange: (Boolean) -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    Column(verticalArrangement = Arrangement.spacedBy(space.s1)) {
        Row(
            Modifier.fillMaxWidth().defaultMinSize(minHeight = SpoolwardenTheme.sizes.row)
                .toggleable(value = on, role = Role.Switch, onValueChange = onChange),
            horizontalArrangement = Arrangement.spacedBy(space.s3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(AlertTexts.SWITCH_TITLE, Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
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
        }
        Text(AlertTexts.SWITCH_HINT, color = colors.muted, style = MaterialTheme.typography.bodyMedium)
    }
}
