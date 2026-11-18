package com.thompsonfabco.filamentkit.ui.alerts

import android.os.Build
import androidx.compose.runtime.Composable
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.thompsonfabco.filamentkit.alerts.AlertAction
import com.thompsonfabco.filamentkit.alerts.AlertCondition
import com.thompsonfabco.filamentkit.alerts.AlertEvent
import com.thompsonfabco.filamentkit.alerts.AlertParsing
import com.thompsonfabco.filamentkit.alerts.AlertSeverity
import com.thompsonfabco.filamentkit.alerts.AlertTarget
import com.thompsonfabco.filamentkit.alerts.AlertsUi
import com.thompsonfabco.filamentkit.alerts.bannerState
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class AlertBannerTest {
    @get:Rule val rule = createComposeRule()

    private val now = AlertParsing.parseTime("2026-11-17T12:00:00Z")!!
    private val calls = mutableListOf<String>()

    private fun event(
        id: Long, title: String, severity: AlertSeverity = AlertSeverity.Warn, key: String? = null,
        place: String? = "printer", agoMs: Long = 180_000,
    ) = AlertEvent(
        id = id, atMillis = now - agoMs, kind = "k", severity = severity,
        condition = key?.let { AlertCondition(it, "raised") }, alert = true, title = title, text = "Sentence of $title.",
        action = AlertAction(place, "p-3"),
    )

    private val actions = AlertBannerActions(
        onAction = { calls += "action $it" }, onDismiss = { calls += "dismiss ${it.key}" }, onMore = { calls += "more" },
    )

    @Composable
    private fun Themed(content: @Composable () -> Unit) = SpoolwardenTheme(Look.Console, Appearance.Light) { content() }

    @Test fun aBannerHasTheBoldTitleTheSentenceTheAgeOneActionAndDismiss() {
        val state = bannerState(listOf(event(1, "Filament ran out on Workshop X1", key = "print-paused:p-3")), emptyList(), emptyMap(), now)
        rule.setContent { Themed { AlertBanners(state, now, actions) } }
        rule.onNodeWithText("Filament ran out on Workshop X1").assertExists()
        rule.onNodeWithText("Sentence of Filament ran out on Workshop X1. 3 min ago").assertExists()
        rule.onNodeWithText("Open the printer").performClick()
        rule.onNodeWithText("Dismiss").performClick()
        assertEquals(listOf("action Printer(id=p-3)", "dismiss print-paused:p-3"), calls)
    }

    @Test fun aPlaceTheAppHasNoScreenForOffersTheAlertsList() {
        val state = bannerState(listOf(event(1, "Storage on the Hub is almost full", key = "storage-low", place = "storage_use")), emptyList(), emptyMap(), now)
        rule.setContent { Themed { AlertBanners(state, now, actions) } }
        rule.onNodeWithText("Show alerts").performClick()
        assertEquals(listOf("action ${AlertTarget.AlertsList}"), calls)
    }

    @Test fun threeAlertsShowTwoAndOneMoreLineThatOpensTheList() {
        val state = bannerState(
            listOf(event(1, "A", key = "a"), event(2, "B", key = "b"), event(3, "C", severity = AlertSeverity.Bad, key = "c")),
            emptyList(), emptyMap(), now,
        )
        rule.setContent { Themed { AlertBanners(state, now, actions) } }
        rule.onNodeWithText("C").assertExists()
        rule.onNodeWithText("B").assertExists()
        rule.onAllNodesWithText("A").assertCountEquals(0)
        rule.onNodeWithText("1 more alert").performClick()
        assertEquals(listOf("more"), calls)
    }

    @Test fun theAlertsListShowsRaisedConditionsThenEventsOrTheEmptyLine() {
        val raised = event(10, "Raised one", key = "k")
        val past = event(4, "Past one", severity = AlertSeverity.Bad, agoMs = 2 * 24 * 3_600_000L)
        rule.setContent {
            Themed {
                AlertsScreen(AlertsUi(loaded = true, conditions = listOf(raised), events = listOf(past)), now, onAction = { calls += "to $it" })
            }
        }
        rule.onNodeWithText("Raised one").assertExists()
        rule.onNodeWithText("Past one").assertExists()
        rule.onAllNodesWithText("Open the printer")[0].performClick()
        assertEquals(1, calls.size)
    }

    @Test fun anEmptyListSaysSo() {
        rule.setContent { Themed { AlertsScreen(AlertsUi(loaded = true), now, onAction = {}) } }
        rule.onNodeWithText("No alerts in the last 7 days.").assertExists()
    }

    @Test fun anOlderHubWithoutAlertsSaysSo() {
        rule.setContent { Themed { AlertsScreen(AlertsUi(available = false, loaded = true), now, onAction = {}) } }
        rule.onNodeWithText("This Hub does not send alerts yet. Update the Hub to get them.").assertExists()
    }
}
