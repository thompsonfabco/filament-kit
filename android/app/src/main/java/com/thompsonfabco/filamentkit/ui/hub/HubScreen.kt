package com.thompsonfabco.filamentkit.ui.hub

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.semantics
import androidx.navigation.NavDestination
import androidx.navigation.NavDestination.Companion.hasRoute
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.HubCheckState
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.ScreenState
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.settings.FieldRow
import com.thompsonfabco.filamentkit.ui.settings.GroupTitle
import com.thompsonfabco.filamentkit.ui.settings.SettingsPanel
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * The Hub at a glance (R83 section 5): what the Hub says about itself, read-only, group by group. Each group ends with
 * "Change this on the Hub page." and, where the Hub gave an address for it, "Open the Hub page". [online] false keeps
 * what was read under the offline notice. An older Hub (404) says to update it.
 */
@Composable
internal fun HubScreen(
    ui: HubUi,
    online: Boolean,
    onTryAgain: () -> Unit,
    modifier: Modifier = Modifier,
    nowMillis: Long = System.currentTimeMillis(),
) {
    val space = SpoolwardenTheme.space
    val links = LocalUriHandler.current
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
        Column(
            Modifier.widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxWidth().verticalScroll(rememberScrollState())
                .padding(space.s4),
            verticalArrangement = Arrangement.spacedBy(space.s3),
        ) {
            val hub = ui.hub
            if (ui.unavailable) {
                Text(HubTexts.UNAVAILABLE, style = MaterialTheme.typography.bodyLarge)
            } else {
                ScreenState(
                    loaded = hub != null,
                    loading = ui.loading,
                    error = if (ui.failed && online) ui.message ?: stringResource(R.string.common_offline_text) else null,
                    onTryAgain = onTryAgain,
                    offline = !online,
                    loadedSecondsAgo = ui.loadedAt?.let { ((nowMillis - it) / MS_PER_SECOND).coerceAtLeast(0) } ?: 0,
                ) {
                    if (hub != null) {
                        var openProblem by remember { mutableStateOf(false) }
                        hubSections(hub).forEach { section ->
                            SettingsPanel {
                                GroupTitle(section.group.title)
                                section.lines.forEach { LineView(it) }
                                Text(
                                    HubTexts.CHANGE_ON_HUB_PAGE, color = SpoolwardenTheme.colors.muted,
                                    style = MaterialTheme.typography.bodySmall,
                                )
                                hub.hubPage?.let { page ->
                                    SwButton(stringResource(R.string.common_open_hub_page), {
                                        openProblem = runCatching { links.openUri(page) }.isFailure
                                    }, Modifier.fillMaxWidth())
                                }
                            }
                        }
                        if (openProblem) NoticeCard(NoticeKind.Bad, stringResource(R.string.settings_hub_page_error_browser))
                    }
                }
            }
        }
    }
}

@Composable
private fun LineView(line: HubLine) {
    when (line) {
        is HubLine.Field -> FieldRow(line.label, line.value)
        is HubLine.Note -> Text(line.text, style = MaterialTheme.typography.bodyMedium)
        is HubLine.Check -> CheckRow(line)
    }
}

/** A check: the state as shape and word (never colour alone), the Hub's text, and its fix line. */
@Composable
private fun CheckRow(check: HubLine.Check) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val (shape, word, colour) = when (check.state) {
        HubCheckState.Ok -> Triple(R.drawable.sw_st_filled, R.string.status_ok, colors.ok)
        HubCheckState.Look -> Triple(R.drawable.sw_st_triangle, R.string.status_needs_look, colors.warn)
        HubCheckState.Note -> Triple(R.drawable.sw_ic_info, R.string.status_note, colors.muted)
        HubCheckState.Off -> Triple(R.drawable.sw_st_hollow, R.string.status_off, colors.muted)
    }
    Column(Modifier.fillMaxWidth().semantics(mergeDescendants = true) { }, verticalArrangement = Arrangement.spacedBy(space.s1)) {
        Row(horizontalArrangement = Arrangement.spacedBy(space.s1), verticalAlignment = Alignment.CenterVertically) {
            StateShape(shape, colour)
            Text(stringResource(word), color = colour, maxLines = 1, style = MaterialTheme.typography.labelLarge)
        }
        Text(check.text, style = MaterialTheme.typography.bodyMedium)
        check.fix?.let { Text(it, color = colors.muted, style = MaterialTheme.typography.bodySmall) }
    }
}

@Composable
private fun StateShape(shape: Int, colour: Color) {
    Icon(painterResource(shape), contentDescription = null, modifier = Modifier.size(SpoolwardenTheme.space.s2 + SpoolwardenTheme.space.s1 / 2), tint = colour)
}

/** The top bar's title on the Hub screen, which has no catalogue text yet; null on any other screen. */
internal fun hubPlaceTitle(destination: NavDestination?): String? =
    if (destination != null && destination.hasRoute(HubGlanceRoute::class)) HubTexts.TITLE else null

private const val MS_PER_SECOND = 1000L
