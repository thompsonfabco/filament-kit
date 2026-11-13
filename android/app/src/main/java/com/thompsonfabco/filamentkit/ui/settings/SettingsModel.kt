package com.thompsonfabco.filamentkit.ui.settings

import com.thompsonfabco.filamentkit.nav.HubState
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.update.UpdateFailure
import com.thompsonfabco.filamentkit.update.UpdateUi

/** The groups of 05-android-app 12.1, in the order the list shows them. */
internal enum class SettingsGroup { Appearance, Hub, Updates, Licences, Developer }

/** The paired Hub as the Hub connection group shows it (12.3). */
internal class SettingsHub(val name: String, val address: String, val fingerprint: String, val version: String?)

/** What the list of 12.1 summarises, and what the pages of 12.2 to 12.6 are drawn from. */
internal class SettingsFacts(
    val appearance: Appearance,
    /** Null: no Hub is paired. */
    val hub: SettingsHub?,
    val hubState: HubState,
    val update: UpdateUi,
    val appVersion: String,
    /** Debug builds only: the Developer group exists. */
    val developer: Boolean,
)

/** The groups the list shows: Developer only in a debug build. */
internal fun settingsGroups(developer: Boolean): List<SettingsGroup> =
    SettingsGroup.entries.filter { developer || it != SettingsGroup.Developer }

/**
 * The fingerprint check switch is the old "skip" setting the other way round: on (the default) means the check runs,
 * so it is on exactly when skipping is off. Turning it off asks first; turning it on needs no question.
 */
internal fun fingerprintCheckOn(skipFingerprintCheck: Boolean): Boolean = !skipFingerprintCheck

internal fun needsSkipConfirmation(turnedOn: Boolean): Boolean = !turnedOn

/** What the Updates summary of 12.1 says. */
internal sealed interface UpdatesSummary {
    /** "Update ready: 0.5.3". */
    data class Ready(val version: String) : UpdatesSummary

    /** "App 0.5.2 · up to date": only once a check reached the Hub. */
    data object UpToDate : UpdatesSummary

    /** Not checked yet: just the app's version. */
    data object Unchecked : UpdatesSummary
}

internal fun updatesSummary(ui: UpdateUi): UpdatesSummary = when {
    ui.available != null -> UpdatesSummary.Ready(ui.offeredVersion?.takeIf { it.isNotBlank() } ?: ui.available.toString())
    ui.checked && !ui.serverTooNew -> UpdatesSummary.UpToDate
    else -> UpdatesSummary.Unchecked
}

/** The states of the update panel (05-android-app 13), one for each row of its table. */
internal sealed interface UpdatePanelState {
    /** Nothing is known yet (no check reached the Hub). */
    data object Unknown : UpdatePanelState
    data object UpToDate : UpdatePanelState
    data object Offered : UpdatePanelState

    /** The Hub speaks a newer API than the app understands. */
    data class HubNewer(val canInstall: Boolean) : UpdatePanelState
    data class Downloading(val percent: Int?) : UpdatePanelState
    data object NeedsPermission : UpdatePanelState
    data object Installing : UpdatePanelState
    data object Waiting : UpdatePanelState
    data class Failed(val failure: UpdateFailure, val canInstall: Boolean) : UpdatePanelState
}

/** The panel for [ui]; a download under way wins, then a failure, then the install steps, then the offer. */
internal fun updatePanel(ui: UpdateUi): UpdatePanelState = when {
    ui.busy -> UpdatePanelState.Downloading(ui.progress)
    ui.failure != null -> UpdatePanelState.Failed(ui.failure, canInstall = ui.available != null)
    ui.needsPermission -> UpdatePanelState.NeedsPermission
    ui.installing -> UpdatePanelState.Installing
    ui.confirmPending -> UpdatePanelState.Waiting
    ui.serverTooNew -> UpdatePanelState.HubNewer(canInstall = ui.available != null)
    ui.available != null -> UpdatePanelState.Offered
    ui.checked -> UpdatePanelState.UpToDate
    else -> UpdatePanelState.Unknown
}
