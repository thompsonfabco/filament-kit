package com.thompsonfabco.filamentkit.ui.alerts

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.navigation.NavDestination
import androidx.navigation.NavDestination.Companion.hasRoute
import com.thompsonfabco.filamentkit.alerts.AlertTarget
import com.thompsonfabco.filamentkit.alerts.AlertsRoute
import com.thompsonfabco.filamentkit.alerts.SettingsAlertsRoute
import com.thompsonfabco.filamentkit.alerts.AlertTexts
import com.thompsonfabco.filamentkit.alerts.AlertsUi
import com.thompsonfabco.filamentkit.alerts.alertsList
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme

/**
 * The Alerts list (R80 section 5), opened from "<n> more alerts" and Settings > Alerts > Recent alerts: the raised
 * conditions first, then the alert events of the last 7 days, newest first, each with its icon (the notice's shape),
 * title, sentence, time and its action. A place the app has no screen for has no button here: this is that screen.
 */
@Composable
internal fun AlertsScreen(
    ui: AlertsUi,
    nowMillis: Long,
    onAction: (AlertTarget) -> Unit,
    modifier: Modifier = Modifier,
) {
    val space = SpoolwardenTheme.space
    val rows = alertsList(ui.conditions, ui.events, nowMillis, AlertsUi.LIST_DAYS)
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
        Column(
            Modifier.widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxWidth().verticalScroll(rememberScrollState())
                .padding(space.s4),
            verticalArrangement = Arrangement.spacedBy(space.s3),
        ) {
            when {
                !ui.available -> Text(AlertTexts.UNAVAILABLE, style = MaterialTheme.typography.bodyLarge)
                ui.loaded && rows.isEmpty() -> Text(AlertTexts.EMPTY, style = MaterialTheme.typography.bodyLarge)
                else -> rows.forEach { item ->
                    val target = item.target()
                    NoticeCard(
                        item.severity.noticeKind(), item.sentenceFor(nowMillis), title = item.event.title,
                        actions = if (target == AlertTarget.AlertsList) {
                            emptyList()
                        } else {
                            listOf(SwAction(AlertTexts.actionLabel(target)) { onAction(target) })
                        },
                    )
                }
            }
        }
    }
}

/** The top bar's title on the alert screens, which have no catalogue text yet; null on any other screen. */
internal fun alertsPlaceTitle(destination: NavDestination?): String? = when {
    destination == null -> null
    destination.hasRoute(AlertsRoute::class) -> AlertTexts.RECENT_ALERTS
    destination.hasRoute(SettingsAlertsRoute::class) -> AlertTexts.SETTINGS_TITLE
    else -> null
}
