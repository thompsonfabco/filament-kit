package com.thompsonfabco.filamentkit.ui.settings

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.thompsonfabco.filamentkit.ui.theme.Appearance

/** What the groups of Settings can do; the app wires each to its owner (05-android-app 12). */
internal class SettingsActions(
    val onAppearance: (Appearance) -> Unit,
    val skipFingerprintCheck: Boolean,
    val onSkipFingerprintCheck: (Boolean) -> Unit,
    val onPairAgain: () -> Unit,
    val onForget: () -> Unit,
    val setupUrl: () -> String?,
    val update: UpdateActions,
    val onCheckForUpdates: () -> Unit,
    val onSimulateTag: (String) -> Unit,
)

/** The page of one group: the route of a narrow window, and the right pane of a wide one. */
@Composable
internal fun SettingsGroupPage(group: SettingsGroup, facts: SettingsFacts, actions: SettingsActions, modifier: Modifier = Modifier) {
    when (group) {
        SettingsGroup.Appearance -> AppearanceSettings(facts.appearance, actions.onAppearance, modifier)
        SettingsGroup.Hub -> HubSettings(
            hub = facts.hub,
            state = facts.hubState,
            skipFingerprintCheck = actions.skipFingerprintCheck,
            onSkipFingerprintCheck = actions.onSkipFingerprintCheck,
            onPairAgain = actions.onPairAgain,
            onForget = actions.onForget,
            setupUrl = actions.setupUrl,
            modifier = modifier,
        )
        SettingsGroup.Updates -> UpdatesSettings(
            appVersion = facts.appVersion,
            hubVersion = facts.hub?.version,
            update = facts.update,
            actions = actions.update,
            onCheck = actions.onCheckForUpdates,
            paired = facts.hub != null,
            modifier = modifier,
        )
        SettingsGroup.Licences -> LicencesScreen(modifier)
        SettingsGroup.Developer -> if (facts.developer) DeveloperSettings(actions.onSimulateTag, modifier)
    }
}
