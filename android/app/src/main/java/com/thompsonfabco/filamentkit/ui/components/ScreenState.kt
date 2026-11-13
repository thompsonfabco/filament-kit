package com.thompsonfabco.filamentkit.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.delay

/** How long a first load may take before the screen says it is still waiting (05-android-app 3.2). */
internal const val STILL_WAITING_MS = 10_000L

/**
 * The states every Hub-backed screen has besides its content (05-android-app 3.2), in one place:
 *
 * - first load ([loaded] false, [loading] true): the [skeleton] where the data will be and the indeterminate
 *   progress line on top, directly under the top bar; "Still waiting for the Hub…" after 10 s;
 * - refreshing ([loading] true after a load): the data stays and the progress line runs;
 * - empty ([loaded] and [isEmpty]): [empty], normally a [SwEmptyState] with the screen's own words;
 * - error ([error] set): a `Bad` notice with "Try again" at the top, the data stays;
 * - offline ([offline]): the data stays under an `Info` notice naming its age; with nothing loaded yet the
 *   "Cannot reach the Hub" empty state with "Try again".
 *
 * Buttons that need the Hub are disabled while [offline]; the first one carries [NeedsHubReason] under it.
 */
@Composable
internal fun ScreenState(
    loaded: Boolean,
    loading: Boolean,
    modifier: Modifier = Modifier,
    isEmpty: Boolean = false,
    empty: (@Composable () -> Unit)? = null,
    error: String? = null,
    onTryAgain: () -> Unit = {},
    offline: Boolean = false,
    /** Seconds since the data on screen was loaded; used by the offline notice. */
    loadedSecondsAgo: Long = 0,
    skeleton: @Composable () -> Unit = { SwSkeletonRows() },
    content: @Composable ColumnScope.() -> Unit,
) {
    val space = SpoolwardenTheme.space
    val firstLoad = loading && !loaded
    var slow by remember { mutableStateOf(false) }
    LaunchedEffect(firstLoad) {
        slow = false
        if (firstLoad) {
            delay(STILL_WAITING_MS)
            slow = true
        }
    }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(space.s3)) {
        if (loading) SwProgress(null)
        if (firstLoad && slow) NoticeCard(NoticeKind.Info, stringResource(R.string.common_still_waiting))
        if (error != null) {
            NoticeCard(
                NoticeKind.Bad, error,
                actions = listOf(SwAction(stringResource(R.string.common_try_again), onTryAgain)),
            )
        }
        when {
            !loaded && offline -> SwEmptyState(
                icon = R.drawable.sw_st_hollow,
                title = stringResource(R.string.common_offline_title),
                text = stringResource(R.string.common_offline_text),
                primary = SwAction(stringResource(R.string.common_try_again), onTryAgain),
            )
            !loaded -> if (loading) skeleton()
            else -> {
                if (offline) {
                    NoticeCard(NoticeKind.Info, stringResource(R.string.common_offline_notice, ageWords(loadedSecondsAgo)))
                }
                if (isEmpty && empty != null) empty() else content()
            }
        }
    }
}

/** "Needs the Hub. Reconnecting…": under the first button that is disabled because the Hub cannot be reached. */
@Composable
internal fun NeedsHubReason(modifier: Modifier = Modifier) {
    Text(
        stringResource(R.string.common_needs_hub), modifier.padding(top = SpoolwardenTheme.space.s1).semantics {
            liveRegion = LiveRegionMode.Polite
        },
        color = SpoolwardenTheme.colors.muted, style = MaterialTheme.typography.bodySmall,
    )
}

/** An age in the catalogue's words: "40 s ago", "2 min ago", "3 h ago". */
@Composable
internal fun ageWords(seconds: Long): String = when {
    seconds < SECONDS_PER_MINUTE -> stringResource(R.string.common_age_seconds, seconds)
    seconds < SECONDS_PER_HOUR -> stringResource(R.string.common_age_minutes, seconds / SECONDS_PER_MINUTE)
    else -> stringResource(R.string.common_age_hours, seconds / SECONDS_PER_HOUR)
}

private const val SECONDS_PER_MINUTE = 60L
private const val SECONDS_PER_HOUR = 3600L
