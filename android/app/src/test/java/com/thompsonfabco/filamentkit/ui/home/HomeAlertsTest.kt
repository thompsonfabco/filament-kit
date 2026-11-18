package com.thompsonfabco.filamentkit.ui.home

import android.os.Build
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.thompsonfabco.filamentkit.alerts.AlertAction
import com.thompsonfabco.filamentkit.alerts.AlertCondition
import com.thompsonfabco.filamentkit.alerts.AlertEvent
import com.thompsonfabco.filamentkit.alerts.AlertParsing
import com.thompsonfabco.filamentkit.alerts.AlertSeverity
import com.thompsonfabco.filamentkit.alerts.bannerState
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.session.Connection
import com.thompsonfabco.filamentkit.ui.alerts.AlertBannerActions
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.SwToastState
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.update.UpdateUi
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Home's alert banners and its "<n> spools running low" line (R80 sections 5 and 7). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class HomeAlertsTest {
    @get:Rule val rule = createComposeRule()

    private val now = AlertParsing.parseTime("2026-11-17T12:00:00Z")!!
    private val calls = mutableListOf<String>()

    private fun raised(id: Long, title: String, severity: AlertSeverity = AlertSeverity.Warn) = AlertEvent(
        id = id, atMillis = now - 60_000, kind = "k", severity = severity, condition = AlertCondition("c$id", "raised"),
        alert = true, title = title, text = "Sentence $id.", action = AlertAction("printer", "p-1"),
    )

    private fun show(conditions: List<AlertEvent>, lowCount: Int) {
        rule.setContent {
            CompositionLocalProvider(LocalToast provides SwToastState()) {
                SpoolwardenTheme(Look.Console, Appearance.Light) { Home(conditions, lowCount) }
            }
        }
    }

    @Composable
    private fun Home(conditions: List<AlertEvent>, lowCount: Int) {
        HomeScreen(
            connection = Connection.Online("192.0.2.10"), drafts = emptyList(), update = UpdateUi(),
            printers = HomePrintersState(printers = emptyList<Printer>(), loadedAt = now),
            onAddSpools = {}, onAddByHand = {}, onResumeDraft = {}, onDiscardDraft = {}, onOpenPrinter = {}, onOpenPrinters = {},
            onRefreshPrinters = {}, onReviewCertificate = {}, onPairAgain = {}, onInstallUpdate = {}, onConfirmInstall = {},
            nowMillis = now,
            alertBanner = bannerState(conditions, emptyList(), emptyMap(), now),
            alertActions = AlertBannerActions(
                onAction = { calls += "action" }, onDismiss = { calls += "dismiss ${it.key}" }, onMore = { calls += "more" },
            ),
            lowCount = lowCount, onOpenLow = { calls += "low" },
        )
    }

    @Test fun twoBannersThenMoreAlertsAreOnHome() {
        show(listOf(raised(1, "First"), raised(2, "Second"), raised(3, "Third", AlertSeverity.Bad)), lowCount = 0)
        rule.onNodeWithText("Third").assertExists()
        rule.onNodeWithText("Second").assertExists()
        rule.onNodeWithText("1 more alert").performClick()
        assertEquals(listOf("more"), calls)
    }

    @Test fun theRunningLowLineOpensTheFilterAndIsAbsentWithNone() {
        show(emptyList(), lowCount = 3)
        rule.onNodeWithText("3 spools running low").performClick()
        assertEquals(listOf("low"), calls)
    }

    @Test fun noLineAndNoBannerWhenNothingIsRaised() {
        show(emptyList(), lowCount = 0)
        rule.onNodeWithText("Add spools").assertExists()
        assertEquals(0, rule.onAllNodesWithTextCount("running low"))
    }

    private fun androidx.compose.ui.test.junit4.ComposeContentTestRule.onAllNodesWithTextCount(t: String) =
        onAllNodes(androidx.compose.ui.test.hasText(t, substring = true)).fetchSemanticsNodes().size
}
