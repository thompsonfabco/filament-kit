package com.thompsonfabco.filamentkit.ui.settings

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.nav.HubState
import com.thompsonfabco.filamentkit.ui.components.label
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass

/**
 * Settings (05-android-app 12.1): a list of groups, each with an icon, a title, a one-line live summary and a chevron.
 * It works without a Hub connection. On an expanded window the list is the left pane and the chosen group, drawn by
 * [detail], the right pane; elsewhere (or without [detail]) a tap goes to [onOpen].
 */
@Composable
internal fun SettingsScreen(
    facts: SettingsFacts,
    onOpen: (SettingsGroup) -> Unit,
    modifier: Modifier = Modifier,
    detail: (@Composable (SettingsGroup) -> Unit)? = null,
) {
    val twoPanes = detail != null && SpoolwardenTheme.window == WindowClass.Desktop
    var chosen by rememberSaveable { mutableStateOf(SettingsGroup.Appearance) }
    if (!twoPanes) {
        SettingsList(facts, onOpen, modifier.fillMaxSize(), selected = null)
        return
    }
    Row(modifier.fillMaxSize()) {
        SettingsList(facts, { chosen = it }, Modifier.width(SpoolwardenTheme.sizes.listW).fillMaxHeight(), selected = chosen)
        VerticalDivider(color = SpoolwardenTheme.colors.border, thickness = SpoolwardenTheme.sizes.hairline)
        Box(Modifier.weight(1f).fillMaxHeight()) { detail(chosen) }
    }
}

@Composable
private fun SettingsList(facts: SettingsFacts, onOpen: (SettingsGroup) -> Unit, modifier: Modifier, selected: SettingsGroup?) {
    Column(modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.sizes.hairline)) {
        settingsGroups(facts.developer).forEach { group ->
            SettingsRow(
                icon = group.icon,
                title = stringResource(group.title),
                summary = summary(group, facts),
                onClick = { onOpen(group) },
                selected = group == selected,
                dot = group == SettingsGroup.Updates && facts.update.available != null,
            )
        }
    }
}

@get:DrawableRes
private val SettingsGroup.icon: Int
    get() = when (this) {
        SettingsGroup.Appearance -> R.drawable.sw_ic_half_circle
        SettingsGroup.Hub -> R.drawable.sw_ic_plug
        SettingsGroup.Updates -> R.drawable.sw_ic_updates
        SettingsGroup.Licences -> R.drawable.sw_ic_info
        SettingsGroup.Developer -> R.drawable.sw_ic_tag
    }

@get:StringRes
internal val SettingsGroup.title: Int
    get() = when (this) {
        SettingsGroup.Appearance -> R.string.appearance_title
        SettingsGroup.Hub -> R.string.hub_sheet_title
        SettingsGroup.Updates -> R.string.settings_updates_title
        SettingsGroup.Licences -> R.string.settings_licences_title
        SettingsGroup.Developer -> R.string.settings_developer_title
    }

/** The live summary under a group's title. */
@Composable
private fun summary(group: SettingsGroup, facts: SettingsFacts): String = when (group) {
    SettingsGroup.Appearance -> stringResource(
        R.string.settings_summary_appearance, stringResource(facts.appearance.label), stringResource(R.string.theme_console_name),
    )
    SettingsGroup.Hub -> facts.hub?.let { hub ->
        stringResource(R.string.settings_summary_hub, hub.name, stringResource(facts.hubState.word))
    } ?: stringResource(R.string.settings_hub_none)
    SettingsGroup.Updates -> when (val s = updatesSummary(facts.update)) {
        is UpdatesSummary.Ready -> stringResource(R.string.settings_updates_ready, s.version)
        UpdatesSummary.UpToDate -> stringResource(R.string.settings_updates_current, facts.appVersion)
        UpdatesSummary.Unchecked -> stringResource(R.string.settings_updates_unchecked, facts.appVersion)
    }
    SettingsGroup.Licences -> stringResource(R.string.settings_licences_summary)
    SettingsGroup.Developer -> stringResource(R.string.settings_developer_summary)
}

/** The word of a Hub state for a summary: the status word, or "Checking…" before the first answer. */
internal val HubState.word: Int
    @StringRes get() = badge?.word ?: R.string.common_checking

/** `https://<host>:<port>/setup` from the app's `https://<host>:<port>` (null: not paired). */
internal object HubPage {
    fun url(base: String?): String? =
        base?.takeIf { it.startsWith("https://") && !it.startsWith("https://unpaired.invalid") }?.trimEnd('/')?.plus("/setup")
}
