package com.thompsonfabco.filamentkit.ui.settings

import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.compose.runtime.Composable
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class AlertsSettingsTest {
    @get:Rule val rule = createComposeRule()

    private val calls = mutableListOf<String>()
    private val actions = AlertsActions(
        onSwitch = { calls += "switch $it" }, onTest = { calls += "test" }, onRecent = { calls += "recent" },
        requestLocalNetwork = { calls += "local network" },
    )

    @Composable
    private fun Themed(content: @Composable () -> Unit) = SpoolwardenTheme(Look.Console, Appearance.Light) { content() }

    private fun show(facts: AlertsFacts) {
        rule.setContent { Themed { AlertsSettings(facts, actions) } }
    }

    @Test fun theGroupShowsTheSwitchItsHintTheTestAndRecentAlerts() {
        show(AlertsFacts(on = true))
        rule.onNodeWithText("Alerts on this phone").assertExists()
        rule.onNodeWithText("Android shows a small permanent notification while Spoolwarden watches the Hub.").assertExists()
        rule.onNodeWithText("On").assertExists()
        rule.onNodeWithText("Send a test alert").performClick()
        rule.onNodeWithText("Sent.").assertExists()
        rule.onNodeWithText("Recent alerts").performClick()
        assertEquals(listOf("test", "recent"), calls)
    }

    @Test fun theTestIsOffWhileTheSwitchIsOff() {
        show(AlertsFacts(on = false))
        rule.onNodeWithText("Off").assertExists()
        rule.onNodeWithText("Send a test alert").performClick()
        assertEquals("a disabled button does nothing", emptyList<String>(), calls)
    }

    @Test fun turningOnWithEverythingAllowedTurnsItOn() {
        show(AlertsFacts(on = false))
        rule.onNodeWithText("Alerts on this phone").performClick()
        assertEquals(listOf("switch true"), calls)
    }

    @Test fun turningOffTurnsItOff() {
        show(AlertsFacts(on = true))
        rule.onNodeWithText("Alerts on this phone").performClick()
        assertEquals(listOf("switch false"), calls)
    }

    @Test fun withoutTheLocalNetworkPermissionTheSwitchStaysOffAndTheHelpSaysWhy() {
        show(AlertsFacts(on = false, localNetworkGranted = false))
        rule.onNodeWithText("Alerts on this phone").performClick()
        assertEquals(listOf("local network"), calls)
        rule.onNodeWithText("Spoolwarden needs the Local network permission to watch the Hub. Allow it, then turn this on.").assertExists()
    }

    @Test fun withNotificationsBlockedTheSwitchStaysOffAndTheHelpOffersTheAppSettings() {
        val manager = RuntimeEnvironment.getApplication().getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        shadowOf(manager).setNotificationsEnabled(false)
        show(AlertsFacts(on = false))
        rule.onNodeWithText("Alerts on this phone").performClick()
        assertEquals("nothing is turned on", emptyList<String>(), calls)
        rule.onNodeWithText("Open app settings").assertExists()
    }

    @Test fun anOlderHubSaysItHasNoAlerts() {
        show(AlertsFacts(on = false, available = false))
        rule.onNodeWithText("This Hub does not send alerts yet. Update the Hub to get them.").assertExists()
    }
}
