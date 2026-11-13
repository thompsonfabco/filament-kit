package com.thompsonfabco.filamentkit.nav

import android.os.Build
import androidx.compose.material3.Text
import androidx.navigation.NavHostController
import androidx.navigation.compose.ComposeNavigator
import androidx.navigation.compose.composable
import androidx.navigation.compose.navigation
import androidx.navigation.createGraph
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/** The five destinations, and the pure decisions of the bar, the rail and the top bar's back arrow. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class DestinationsTest {
    private val context = RuntimeEnvironment.getApplication()

    @Test fun fiveDestinationsInTheOrderOfTheSpec() {
        assertEquals(
            listOf("Home", "Spools", "Printers", "Recent", "Settings"),
            Tab.entries.map { context.getString(it.label) },
        )
        assertEquals("every destination has its own graph", 5, Tab.entries.map { it.graph::class }.toSet().size)
        assertEquals("every destination has its own root", 5, Tab.entries.map { it.root::class }.toSet().size)
        assertEquals("every destination has its own icon", 5, Tab.entries.map { it.icon }.toSet().size)
    }

    @Test fun pressingTheSelectedDestinationGoesToItsRootOnlyWhenDeeper() {
        assertEquals(TabTap.Switch, tabTap(current = Tab.Home, tapped = Tab.Printers, atRoot = true))
        assertEquals(TabTap.Switch, tabTap(current = Tab.Home, tapped = Tab.Printers, atRoot = false))
        assertEquals(TabTap.Switch, tabTap(current = null, tapped = Tab.Home, atRoot = false))
        assertEquals(TabTap.PopToRoot, tabTap(current = Tab.Printers, tapped = Tab.Printers, atRoot = false))
        assertEquals(TabTap.Stay, tabTap(current = Tab.Printers, tapped = Tab.Printers, atRoot = true))
    }

    @Test fun theBackArrowIsOnEveryScreenExceptTheRootsAndTheFirstPairingScreen() {
        assertFalse("a root", showsBackArrow(atTabRoot = true, inPairing = false, pairingOverMain = false))
        assertTrue("a screen inside a destination", showsBackArrow(atTabRoot = false, inPairing = false, pairingOverMain = true))
        assertFalse("the first pairing screen", showsBackArrow(atTabRoot = false, inPairing = true, pairingOverMain = false))
        assertTrue("pairing opened over a screen", showsBackArrow(atTabRoot = false, inPairing = true, pairingOverMain = true))
    }

    private fun controller(): NavHostController {
        val nav = NavHostController(context)
        nav.navigatorProvider.addNavigator(ComposeNavigator())
        nav.graph = nav.createGraph(startDestination = HomeGraph) {
            navigation<PairGraph>(startDestination = PairRoute) { composable<PairRoute> { Text("") } }
            navigation<HomeGraph>(startDestination = HomeRoute) {
                composable<HomeRoute> { Text("") }
                composable<AddRoute> { Text("") }
            }
            navigation<PrintersGraph>(startDestination = PrintersRoute) {
                composable<PrintersRoute> { Text("") }
                composable<PrinterRoute> { Text("") }
            }
            navigation<RecentGraph>(startDestination = RecentRoute) {
                composable<RecentRoute> { Text("") }
                composable<RecordRoute> { Text("") }
            }
        }
        return nav
    }

    @Test fun aDestinationKnowsItsTabAndWhetherItIsTheRoot() {
        val nav = controller()
        assertEquals(Tab.Home, nav.currentDestination.tab())
        assertTrue(nav.currentDestination.isTabRoot())
        assertFalse(nav.currentDestination.inPairing())

        nav.navigate(AddRoute(manual = true))
        assertEquals("Add belongs to Home", Tab.Home, nav.currentDestination.tab())
        assertFalse(nav.currentDestination.isTabRoot())

        nav.navigate(PrintersGraph)
        assertEquals(Tab.Printers, nav.currentDestination.tab())
        assertTrue(nav.currentDestination.isTabRoot())
        nav.navigate(PrinterRoute("p1"))
        assertEquals("a printer belongs to Printers", Tab.Printers, nav.currentDestination.tab())
        assertFalse(nav.currentDestination.isTabRoot())

        nav.navigate(RecentGraph)
        nav.navigate(RecordRoute("r1"))
        assertEquals("a record belongs to Recent", Tab.Recent, nav.currentDestination.tab())
    }

    @Test fun pairingOverTheMainGraphIsNotATabAndKeepsTheScreenBelowIt() {
        val nav = controller()
        nav.navigate(PrintersGraph)
        nav.navigate(PrinterRoute("p1"))
        nav.navigate(PairGraph)
        assertTrue(nav.currentDestination.inPairing())
        assertNull(nav.currentDestination.tab())
        assertNotNull("the screen it was opened from is still there", nav.previousBackStackEntry)

        assertTrue(nav.popBackStack<PairGraph>(inclusive = true))
        assertEquals("closing pairing returns to the printer", Tab.Printers, nav.currentDestination.tab())
        assertFalse(nav.currentDestination.isTabRoot())
    }
}
