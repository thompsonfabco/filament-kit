package com.thompsonfabco.filamentkit

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.pm.PackageManager
import android.os.Build
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.assertIsDisplayed
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.thompsonfabco.filamentkit.net.LocalNetwork
import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * API 37: without `ACCESS_LOCAL_NETWORK` the app must not browse, probe or pair, and must explain the permission
 * instead of saying the server is unreachable. Runs with the permission NOT granted: connectedAndroidTest installs
 * the app fresh and nothing in the default run grants it (EndToEndTest grants it only when `fkPhase` is passed). To
 * rerun by hand after granting it: `adb shell pm revoke com.thompsonfabco.filamentkit android.permission.ACCESS_LOCAL_NETWORK`.
 */
@RunWith(AndroidJUnit4::class)
class LocalNetworkDeniedTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()

    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    @Test fun deniedShowsTheExplanationThenAllowThenAppSettings() {
        assumeTrue("ACCESS_LOCAL_NETWORK exists from API 37", Build.VERSION.SDK_INT >= LocalNetwork.FIRST_SDK)
        val app = instrumentation.targetContext
        assertEquals(
            "the permission must not be granted for this test",
            PackageManager.PERMISSION_DENIED,
            app.checkSelfPermission(LocalNetwork.PERMISSION),
        )

        // The app asks at start; the user says no.
        compose.waitForIdle() // the compose test clock runs the start-up effect (the request) only when synced
        denySystemDialog()
        compose.waitUntil(10_000) { exists("Allow local network access") }
        compose.onNodeWithText("Allow").assertIsDisplayed()
        // Nothing that needs the network is offered, and it is not reported as "offline".
        compose.onNodeWithText("Scan QR code").assertDoesNotExist()
        compose.onNodeWithText("Can't reach the server").assertDoesNotExist()

        // Asked again and refused again: Android stops showing its dialog, so the app offers its settings page.
        compose.onNodeWithText("Allow").performClick()
        denySystemDialog()
        compose.waitUntil(10_000) { exists("Open app settings") }
        compose.onNodeWithText("Open app settings").assertIsDisplayed()
        assertEquals(PackageManager.PERMISSION_DENIED, app.checkSelfPermission(LocalNetwork.PERMISSION))
    }

    private fun exists(text: String) =
        compose.onAllNodes(hasText(text, substring = true)).fetchSemanticsNodes().isNotEmpty()

    /** Taps the permission controller's "Don't allow" (first or "don't ask again" variant). */
    private fun denySystemDialog() {
        val deadline = SystemClock.uptimeMillis() + 15_000
        val ua = instrumentation.uiAutomation
        // View ids are only reported, and other apps' windows only listed, with these flags.
        ua.serviceInfo = ua.serviceInfo.apply {
            flags = flags or AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        while (SystemClock.uptimeMillis() < deadline) {
            val roots = ua.windows.mapNotNull { it.root } + listOfNotNull(ua.rootInActiveWindow)
            val button = roots.firstNotNullOfOrNull { root ->
                DENY_IDS.firstNotNullOfOrNull { id -> root.findAccessibilityNodeInfosByViewId(id).firstOrNull { it.isVisibleToUser } }
            }
            if (button != null) {
                button.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                instrumentation.waitForIdleSync()
                return
            }
            SystemClock.sleep(200)
        }
        error("the system permission dialog did not appear")
    }

    private companion object {
        val DENY_IDS = listOf(
            "com.android.permissioncontroller:id/permission_deny_and_dont_ask_again_button",
            "com.android.permissioncontroller:id/permission_deny_button",
        )
    }
}
