package com.thompsonfabco.filamentkit.ui.alerts

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.alerts.AlertItem
import com.thompsonfabco.filamentkit.alerts.AlertSeverity
import com.thompsonfabco.filamentkit.alerts.AlertTarget
import com.thompsonfabco.filamentkit.alerts.BannerState
import com.thompsonfabco.filamentkit.alerts.alertTarget
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.ageWords
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/** What the alert banners can do: go to the fix, put one away on this phone, open the Alerts list. */
internal class AlertBannerActions(
    val onAction: (AlertTarget) -> Unit = {},
    val onDismiss: (AlertItem) -> Unit = {},
    val onMore: () -> Unit = {},
)

internal fun AlertSeverity.noticeKind(): NoticeKind = when (this) {
    AlertSeverity.Bad -> NoticeKind.Bad
    AlertSeverity.Warn -> NoticeKind.Warn
    AlertSeverity.Ok -> NoticeKind.Ok
    AlertSeverity.Info -> NoticeKind.Info
}

internal fun AlertItem.target(): AlertTarget = alertTarget(event.action.place, event.action.id)

/** The label of the one action of an alert, by where it goes. */
@StringRes
internal fun AlertTarget.labelRes(): Int = when (this) {
    is AlertTarget.Printer -> R.string.alert_open_printer
    AlertTarget.RunningLow -> R.string.alert_show_low
    AlertTarget.AlertsList -> R.string.alerts_action_list
}

/** The sentence and, after it, how long ago it was ("3 min ago"); [nowMillis] is the time ages count from. */
@Composable
internal fun AlertItem.sentenceFor(nowMillis: Long): String {
    val at = event.atMillis ?: return event.text
    val age = ageWords(((nowMillis - at) / MS_PER_SECOND).coerceAtLeast(0))
    return if (event.text.isBlank()) age else "${event.text} $age"
}

/**
 * The alert banner (R80 section 5; one component with one data shape): kind `warn` or `bad`, bold title, one sentence,
 * the time, one action that goes to the fix, and Dismiss. At most two are shown, then one line "<n> more alerts" that
 * opens the Alerts list.
 */
@Composable
internal fun AlertBanners(
    state: BannerState,
    nowMillis: Long,
    actions: AlertBannerActions,
    modifier: Modifier = Modifier,
) {
    if (state.shown.isEmpty()) return
    Column(modifier, verticalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2)) {
        state.shown.forEach { item ->
            val target = item.target()
            NoticeCard(
                item.severity.noticeKind(), item.sentenceFor(nowMillis), title = item.event.title,
                actions = listOf(
                    SwAction(stringResource(target.labelRes())) { actions.onAction(target) },
                    SwAction(stringResource(R.string.common_dismiss)) { actions.onDismiss(item) },
                ),
            )
        }
        if (state.more > 0) {
            SwButton(pluralStringResource(R.plurals.alert_more, state.more, state.more), actions.onMore, kind = SwButtonKind.Quiet)
        }
    }
}

private const val MS_PER_SECOND = 1000L
