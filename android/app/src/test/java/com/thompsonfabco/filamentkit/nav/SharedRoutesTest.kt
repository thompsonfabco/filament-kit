package com.thompsonfabco.filamentkit.nav

import android.os.Build
import androidx.compose.material3.Text
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.navigation
import androidx.navigation.compose.rememberNavController
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * The spool and tag screens are declared in the graph of every tab (05-android-app 2.5, "Shared"). A route that is
 * declared in several graphs must open on the stack of the tab that is selected, keep that tab on the bar, and come
 * back in that tab's graph after another tab was visited.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class SharedRoutesTest {
    @get:Rule val rule = createComposeRule()

    private lateinit var nav: NavHostController

    private fun shared(): NavGraphBuilder.() -> Unit = {
        composable<SpoolRoute> { Text("spool") }
        composable<TagRoute> { Text("tag") }
        composable<TagLinkRoute> { Text("link") }
    }

    private fun show() {
        rule.setContent {
            nav = rememberNavController()
            val sharedRoutes = shared()
            NavHost(nav, startDestination = HomeGraph) {
                navigation<HomeGraph>(startDestination = HomeRoute) {
                    composable<HomeRoute> { Text("home") }
                    sharedRoutes()
                }
                navigation<SpoolsGraph>(startDestination = SpoolsRoute) {
                    composable<SpoolsRoute> { Text("spools") }
                    sharedRoutes()
                }
                navigation<PrintersGraph>(startDestination = PrintersRoute) {
                    composable<PrintersRoute> { Text("printers") }
                    sharedRoutes()
                }
            }
        }
        rule.waitForIdle()
    }

    private fun onUi(block: () -> Unit) {
        rule.runOnUiThread(block)
        rule.waitForIdle()
    }

    @Test fun aTagOpensOnTheStackOfTheSelectedTab() {
        show()
        for (tab in listOf(Tab.Spools, Tab.Printers, Tab.Home)) {
            onUi { nav.selectTab(tab) }
            onUi { nav.navigate(TagRoute("04A1B2")) }
            assertTrue("${tab.name}: the tag screen is on ${tab.name}'s stack", nav.currentDestination.tab() == tab)
            assertTrue(nav.currentDestination?.hasRoute(TagRoute::class) == true)
        }
    }

    @Test fun theTabKeepsItsTagScreenWhenAnotherTabWasVisited() {
        show()
        onUi { nav.selectTab(Tab.Spools) }
        onUi { nav.navigate(TagRoute("04A1B2")) }
        onUi { nav.selectTab(Tab.Printers) }
        onUi { nav.navigate(TagRoute("04A1B2")) }
        onUi { nav.selectTab(Tab.Spools) }
        assertEquals(Tab.Spools, nav.currentDestination.tab())
        assertTrue("the Spools stack came back with its tag screen", nav.currentDestination?.hasRoute(TagRoute::class) == true)
        onUi { nav.selectTab(Tab.Printers) }
        assertEquals(Tab.Printers, nav.currentDestination.tab())
        assertTrue(nav.currentDestination?.hasRoute(TagRoute::class) == true)
    }

    @Test fun theTagScreenIsReplacedBySpoolInPlace() {
        show()
        onUi { nav.selectTab(Tab.Spools) }
        onUi { nav.navigate(TagRoute("04A1B2")) }
        onUi { nav.navigate(TagLinkRoute("04A1B2")) }
        onUi { nav.navigate(SpoolRoute(214, tag = "04A1B2")) { popUpTo<TagRoute> { inclusive = true } } }
        assertEquals(Tab.Spools, nav.currentDestination.tab())
        assertTrue(nav.currentDestination?.hasRoute(SpoolRoute::class) == true)
        onUi { nav.popBackStack() }
        assertTrue("Back from the spool lands on Spools", nav.currentDestination?.hasRoute(SpoolsRoute::class) == true)
    }

    @Test fun aDifferentTagReplacesTheTagScreen() {
        show()
        onUi { nav.selectTab(Tab.Printers) }
        onUi { nav.navigate(TagRoute("04A1B2")) }
        onUi { nav.popBackStack<TagRoute>(inclusive = true) }
        onUi { nav.navigate(TagRoute("04FFEE")) }
        assertEquals(Tab.Printers, nav.currentDestination.tab())
        onUi { nav.popBackStack() }
        assertTrue("one Back returns to the screen that was open", nav.currentDestination?.hasRoute(PrintersRoute::class) == true)
    }
}

class TagTapTest {
    @org.junit.Test fun aRepeatedTapOfTheOpenTagDoesNothingButAnotherTagDoes() {
        org.junit.Assert.assertTrue(tapIsForTheOpenTag("4:a1:b2:c3", "4:a1:b2:c3", null))
        org.junit.Assert.assertTrue("the spool screen of that tag", tapIsForTheOpenTag("4:a1:b2:c3", null, "4:A1:B2:C3"))
        org.junit.Assert.assertFalse(tapIsForTheOpenTag("4:a1:b2:c3", "4:ff:ee:dd", "4:11:22:33"))
        org.junit.Assert.assertFalse(tapIsForTheOpenTag("4:a1:b2:c3", null, null))
    }
}
