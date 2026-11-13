package com.thompsonfabco.filamentkit.ui.pair

import android.os.Build
import androidx.compose.material3.Text
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.navigation
import androidx.navigation.compose.rememberNavController
import com.thompsonfabco.filamentkit.nav.HomeGraph
import com.thompsonfabco.filamentkit.nav.HomeRoute
import com.thompsonfabco.filamentkit.nav.PairAddressRoute
import com.thompsonfabco.filamentkit.nav.PairCertificateRoute
import com.thompsonfabco.filamentkit.nav.PairCodeRoute
import com.thompsonfabco.filamentkit.nav.PairFingerprintRoute
import com.thompsonfabco.filamentkit.nav.PairGraph
import com.thompsonfabco.filamentkit.nav.PairNetworkAccessRoute
import com.thompsonfabco.filamentkit.nav.PairRoute
import com.thompsonfabco.filamentkit.nav.PairScanRoute
import com.thompsonfabco.filamentkit.nav.PrintersGraph
import com.thompsonfabco.filamentkit.nav.PrintersRoute
import com.thompsonfabco.filamentkit.nav.SettingsGraph
import com.thompsonfabco.filamentkit.nav.SettingsHubRoute
import com.thompsonfabco.filamentkit.nav.SettingsRoute
import com.thompsonfabco.filamentkit.leaveSettingsForPairing
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The pairing graph's stack follows the pairing steps (05-android-app 4): onto a step, back to one, or replaced. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class PairNavTest {
    @get:Rule val rule = createComposeRule()

    private lateinit var nav: NavHostController

    /** Pairing opened over Home, as "Pair again" does. */
    private fun pairingOverHome() {
        rule.setContent {
            nav = rememberNavController()
            NavHost(nav, startDestination = HomeGraph) {
                navigation<HomeGraph>(startDestination = HomeRoute) { composable<HomeRoute> { Text("home") } }
                navigation<PairGraph>(startDestination = PairRoute) {
                    composable<PairRoute> { Text("pair") }
                    composable<PairNetworkAccessRoute> { Text("access") }
                    composable<PairScanRoute> { Text("scan") }
                    composable<PairAddressRoute> { Text("address") }
                    composable<PairFingerprintRoute> { Text("fingerprint") }
                    composable<PairCodeRoute> { Text("code") }
                    composable<PairCertificateRoute> { Text("certificate") }
                }
            }
        }
        rule.runOnUiThread { nav.navigate(PairGraph) }
        rule.waitForIdle()
    }

    private fun show(target: Any) {
        rule.runOnUiThread { nav.showPairStep(target) }
        rule.waitForIdle()
    }

    private fun back() {
        rule.runOnUiThread { nav.popBackStack() }
        rule.waitForIdle()
    }

    private inline fun <reified T : Any> assertAt() =
        assertTrue("at ${T::class.simpleName}, not ${nav.currentDestination?.route}", nav.currentDestination?.hasRoute(T::class) == true)

    @Test fun theStepsStackAndGoingBackToTheFirstClearsThem() {
        pairingOverHome()
        assertAt<PairRoute>()
        show(PairAddressRoute)
        assertAt<PairAddressRoute>()
        show(PairFingerprintRoute)
        show(PairCodeRoute)
        assertAt<PairCodeRoute>()
        show(PairAddressRoute) // Back from the code: the address is under it
        assertAt<PairAddressRoute>()
        show(PairRoute)
        assertAt<PairRoute>()
        back() // the graph was left: Home shows again
        assertAt<HomeRoute>()
    }

    @Test fun theFirstStepDoesNotCloseTheScanner() {
        pairingOverHome()
        rule.runOnUiThread { nav.navigate(PairScanRoute) }
        rule.waitForIdle()
        show(PairRoute) // the state is still the first step while the camera is open
        assertAt<PairScanRoute>()
        back()
        assertAt<PairRoute>()
    }

    @Test fun theChangeOfASavedPairingStandsAloneAndBackLeavesPairing() {
        pairingOverHome()
        show(PairCertificateRoute("stored"))
        assertAt<PairCertificateRoute>()
        back()
        assertAt<HomeRoute>()
    }

    @Test fun pairAgainAfterASavedPairingsChangeReplacesTheQuestion() {
        pairingOverHome()
        show(PairCertificateRoute("stored"))
        show(PairRoute)
        assertAt<PairRoute>()
        back()
        assertAt<HomeRoute>()
    }

    @Test fun aChangeSeenWhilePairingSitsOnTheStepAndStartAgainGoesBackToTheFirst() {
        pairingOverHome()
        show(PairAddressRoute)
        show(PairFingerprintRoute)
        show(PairCodeRoute)
        show(PairCertificateRoute("manual"))
        assertAt<PairCertificateRoute>()
        show(PairRoute)
        assertAt<PairRoute>()
    }

    @Test fun theAccessStepReplacesWhateverShowsAndTheFirstStepReplacesIt() {
        pairingOverHome()
        show(PairAddressRoute)
        show(PairNetworkAccessRoute)
        assertAt<PairNetworkAccessRoute>()
        show(PairRoute)
        assertAt<PairRoute>()
        back()
        assertEquals("nothing of the steps stayed under it", true, nav.currentDestination?.hasRoute(HomeRoute::class))
    }

    /** The app's graphs, with [start] as the start (PairGraph on the first start, HomeGraph when paired). */
    private fun appGraph(start: Any) {
        rule.setContent {
            nav = rememberNavController()
            NavHost(nav, startDestination = start) {
                navigation<HomeGraph>(startDestination = HomeRoute) { composable<HomeRoute> { Text("home") } }
                navigation<PrintersGraph>(startDestination = PrintersRoute) { composable<PrintersRoute> { Text("printers") } }
                navigation<PairGraph>(startDestination = PairRoute) {
                    composable<PairRoute> { Text("pair") }
                    composable<PairCodeRoute> { Text("code") }
                }
                navigation<SettingsGraph>(startDestination = SettingsRoute) {
                    composable<SettingsRoute> { Text("settings") }
                    composable<SettingsHubRoute> { Text("hub") }
                }
            }
        }
        rule.waitForIdle()
    }

    private fun go(target: Any) {
        rule.runOnUiThread { nav.navigate(target) }
        rule.waitForIdle()
    }

    private fun leaveSettings(): Boolean {
        var handled = false
        rule.runOnUiThread { handled = nav.leaveSettingsForPairing() }
        rule.waitForIdle()
        return handled
    }

    private fun stack() = nav.currentBackStack.value.mapNotNull { it.destination.route?.substringAfterLast('.') }

    @Test fun pairFromSettingsOnTheFirstStartGoesBackToTheStepBelowIt() {
        appGraph(PairGraph)
        go(PairCodeRoute)
        go(SettingsGraph)
        go(SettingsHubRoute)
        assertTrue("Settings is over the code step", leaveSettings())
        assertAt<PairCodeRoute>()
        assertEquals(listOf("PairGraph", "PairRoute", "PairCodeRoute"), stack().filter { it.startsWith("Pair") })
        assertTrue("no Settings entry is left", stack().none { it.startsWith("Settings") })
    }

    @Test fun pairAgainFromSettingsOverPairingOverPrintersKeepsPrintersBelowThePairingStep() {
        appGraph(HomeGraph)
        go(PrintersGraph)
        go(PairGraph)
        go(PairCodeRoute)
        go(SettingsGraph)
        assertTrue(leaveSettings())
        assertAt<PairCodeRoute>()
        assertTrue("no Settings entry is left", stack().none { it.startsWith("Settings") })
        back() // the step under the code is the first one, then Printers
        assertAt<PairRoute>()
        back()
        assertAt<PrintersRoute>()
    }

    @Test fun pairFromSettingsWithNoPairingBelowIsNotHandled() {
        appGraph(HomeGraph)
        go(SettingsGraph)
        assertEquals(false, leaveSettings())
        assertAt<SettingsRoute>()
    }
}
