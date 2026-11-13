package com.thompsonfabco.filamentkit.nav

import android.os.Build
import androidx.compose.material3.Text
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavHostController
import androidx.navigation.compose.ComposeNavigator
import androidx.navigation.compose.composable
import androidx.navigation.compose.navigation
import androidx.navigation.createGraph
import androidx.navigation.toRoute
import com.thompsonfabco.filamentkit.ui.add.AddReplace
import com.thompsonfabco.filamentkit.ui.add.AddStep
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
        assertTrue("a later pairing step", showsBackArrow(atTabRoot = false, inPairing = true, pairingOverMain = false, atPairStart = false))
    }

    private fun controller(): NavHostController {
        val nav = NavHostController(context)
        nav.navigatorProvider.addNavigator(ComposeNavigator())
        nav.graph = nav.createGraph(startDestination = HomeGraph) {
            navigation<PairGraph>(startDestination = PairRoute) { composable<PairRoute> { Text("") } }
            navigation<HomeGraph>(startDestination = HomeRoute) {
                composable<HomeRoute> { Text("") }
                composable<AddPhotosRoute> { Text("") }
                composable<AddReviewRoute> { Text("") }
                composable<AddPreviewRoute> { Text("") }
                composable<AddDoneRoute> { Text("") }
            }
            navigation<PrintersGraph>(startDestination = PrintersRoute) {
                composable<PrintersRoute> { Text("") }
                composable<PrinterRoute> { Text("") }
            }
            navigation<SpoolsGraph>(startDestination = SpoolsRoute) { composable<SpoolsRoute> { Text("") } }
            navigation<RecentGraph>(startDestination = RecentRoute) {
                composable<RecentRoute> { Text("") }
                composable<RecordRoute> { Text("") }
            }
            navigation<SettingsGraph>(startDestination = SettingsRoute) { composable<SettingsRoute> { Text("") } }
        }
        return nav
    }

    @Test fun aDestinationKnowsItsTabAndWhetherItIsTheRoot() {
        val nav = controller()
        assertEquals(Tab.Home, nav.currentDestination.tab())
        assertTrue(nav.currentDestination.isTabRoot())
        assertFalse(nav.currentDestination.inPairing())

        nav.navigate(AddReviewRoute("d"))
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

    @Test fun addOpenedFromAnotherTabLandsOnTheHomeStack() {
        val nav = controller()
        nav.selectTab(Tab.Printers)
        nav.navigate(PrinterRoute("p1"))
        nav.openAdd(first = { AddReviewRoute("new") })
        assertEquals(Tab.Home, nav.currentDestination.tab())
        assertTrue(nav.currentDestination.inAdd())
        val graphs = nav.currentBackStack.value.count { it.destination.hasRoute(HomeGraph::class) }
        assertEquals("one Home graph on the stack, not two", 1, graphs)

        nav.selectTab(Tab.Printers)
        assertTrue("the printers stack was kept", nav.currentDestination?.hasRoute(PrinterRoute::class) == true)
    }

    @Test fun clearingSavedStacksLeavesNothingOfTheOldHub() {
        val nav = controller()
        nav.selectTab(Tab.Printers)
        nav.navigate(PrinterRoute("old-hub-printer"))
        nav.selectTab(Tab.Home)
        nav.navigate(AddPhotosRoute("old-draft"))
        nav.selectTab(Tab.Recent)
        nav.clearSavedStacks()
        nav.selectTab(Tab.Printers)
        assertTrue("Printers opens at its root", nav.currentDestination.isTabRoot())
        assertEquals(Tab.Printers, nav.currentDestination.tab())
        nav.selectTab(Tab.Home)
        assertTrue("Home opens at its root, without the old draft", nav.currentDestination.isTabRoot())
    }

    @Test fun withoutClearingTheOldStackComesBack() {
        val nav = controller()
        nav.selectTab(Tab.Printers)
        nav.navigate(PrinterRoute("old-hub-printer"))
        nav.selectTab(Tab.Home)
        nav.selectTab(Tab.Printers)
        assertFalse(nav.currentDestination.isTabRoot())

        nav.selectTab(Tab.Home)
        nav.navigate(AddPhotosRoute("old-draft"))
        nav.selectTab(Tab.Recent)
        nav.selectTab(Tab.Home)
        assertFalse("Home's saved stack comes back too", nav.currentDestination.isTabRoot())
    }

    @Test fun tappingTheSelectedTabGoesThroughBackSoScreensCanHoldIt() {
        val nav = controller()
        nav.selectTab(Tab.Printers)
        nav.navigate(PrinterRoute("p1"))
        var presses = 0
        nav.popToRootThrough { presses++ } // a screen that keeps Back (it asks first)
        assertEquals(1, presses)
        assertFalse("still on the printer", nav.currentDestination.isTabRoot())

        nav.popToRootThrough { nav.popBackStack() }
        assertTrue(nav.currentDestination.isTabRoot())
        assertEquals(Tab.Printers, nav.currentDestination.tab())
    }

    @Test fun anAddFromTheSpoolCardAlwaysStartsANewOneInPlaceOfTheOpenOne() {
        val nav = controller()
        nav.navigate(AddPhotosRoute("d1"))
        nav.navigate(AddReviewRoute("d1"))
        nav.selectTab(Tab.Printers)
        assertEquals(AddOpened.Opened, nav.openAdd(first = { AddPhotosRoute("d2") }))
        assertEquals(Tab.Home, nav.currentDestination.tab())
        assertEquals("one add, not two", 1, nav.currentBackStack.value.count { it.destination.inAdd() })
        assertEquals("the older draft is not reused", "d2", nav.currentBackStackEntry!!.addDraftId())
    }

    @Test fun anAddThatIsWritingStaysAndTheRequestIsDropped() {
        val nav = controller()
        nav.navigate(AddPreviewRoute("d1"))
        nav.selectTab(Tab.Printers)
        var made = 0
        val rule = { id: String -> if (id == "d1") AddReplace.KeepWriting else AddReplace.Replace }
        assertEquals(AddOpened.KeptWriting, nav.openAdd(first = { made++; AddPhotosRoute("d2") }, decide = rule))
        assertEquals("no draft is made for a request that is dropped", 0, made)
        assertEquals("the Home tab shows the add that was open", Tab.Home, nav.currentDestination.tab())
        assertEquals("d1", nav.currentBackStackEntry!!.addDraftId())
    }

    @Test fun theStackFollowsTheDraftForwardAndBack() {
        val nav = controller()
        nav.navigate(AddPhotosRoute("d1"))
        nav.followStep("d1", AddStep.Photos, AddStep.Check)
        assertTrue(nav.currentDestination?.hasRoute(AddReviewRoute::class) == true)
        nav.followStep("d1", AddStep.Check, AddStep.Preview)
        assertTrue(nav.currentDestination?.hasRoute(AddPreviewRoute::class) == true)
        nav.followStep("d1", AddStep.Preview, AddStep.Check)
        assertTrue("back pops to the step below", nav.currentDestination?.hasRoute(AddReviewRoute::class) == true)
        nav.followStep("d1", AddStep.Check, AddStep.Photos)
        assertTrue(nav.currentDestination?.hasRoute(AddPhotosRoute::class) == true)
        assertEquals("one step each, none left over", 1, nav.currentBackStack.value.count { it.destination.inAdd() })
    }

    @Test fun aStackThatCameBackAheadOfItsDraftIsReplacedNotPopped() {
        val nav = controller()
        // the app was stopped: the stack still says Preview, the draft was restored at the check
        nav.navigate(AddPreviewRoute("d1"))
        nav.followStep("d1", AddStep.Preview, AddStep.Check)
        assertTrue(nav.currentDestination?.hasRoute(AddReviewRoute::class) == true)
        assertEquals(1, nav.currentBackStack.value.count { it.destination.inAdd() })
    }

    @Test fun closingTheAddTakesEveryStepOffTheStack() {
        val nav = controller()
        nav.navigate(AddPhotosRoute("d1"))
        nav.navigate(AddReviewRoute("d1"))
        nav.navigate(AddPreviewRoute("d1"))
        nav.closeAdd()
        assertTrue(nav.currentDestination.isTabRoot())
    }

    @Test fun aTagTapIsTheDraftsTagOnPhotosAndCheckOnly() {
        val nav = controller()
        nav.navigate(AddPhotosRoute("d1"))
        assertTrue(nav.currentDestination.takesTagTaps())
        nav.navigate(AddReviewRoute("d1"))
        assertTrue(nav.currentDestination.takesTagTaps())
        nav.navigate(AddPreviewRoute("d1"))
        assertFalse("on Preview the tap opens the tag (05 2.6)", nav.currentDestination.takesTagTaps())
        nav.navigate(AddDoneRoute("d1"))
        assertFalse(nav.currentDestination.takesTagTaps())
    }

    @Test fun aStepThatWasAlreadyPoppedDoesNotMoveTheStackAgain() {
        val nav = controller()
        nav.navigate(AddPhotosRoute("d1"))
        nav.navigate(AddReviewRoute("d1"))
        nav.popBackStack() // system Back from Check
        nav.followStep("d1", AddStep.Check, AddStep.Photos) // the popped screen's late effect
        assertTrue(nav.currentDestination?.hasRoute(AddPhotosRoute::class) == true)
        assertEquals(1, nav.currentBackStack.value.count { it.destination.inAdd() })
    }

    @Test fun backFromCheckOrPreviewOpenedOnTopOfHomeGoesToTheStepTheTableNames() {
        // a resumed draft, the "Check" snackbar and the failed-add snackbar open a step straight on Home
        val nav = controller()
        nav.navigate(AddReviewRoute("d1"))
        nav.followStep("d1", AddStep.Check, AddStep.Photos)
        assertTrue("Check goes to Photos on the photo path", nav.currentDestination?.hasRoute(AddPhotosRoute::class) == true)
        assertEquals(1, nav.currentBackStack.value.count { it.destination.inAdd() })
        nav.closeAdd()
        assertTrue("and Back from Photos is Home", nav.currentDestination.isTabRoot())

        nav.navigate(AddPreviewRoute("d1"))
        nav.followStep("d1", AddStep.Preview, AddStep.Check)
        assertTrue("Preview goes to Check", nav.currentDestination?.hasRoute(AddReviewRoute::class) == true)
        assertEquals(1, nav.currentBackStack.value.count { it.destination.inAdd() })
    }

    @Test fun backFromAFullStackStillPopsToTheStepBelow() {
        val nav = controller()
        nav.navigate(AddPhotosRoute("d1"))
        nav.navigate(AddReviewRoute("d1"))
        nav.followStep("d1", AddStep.Check, AddStep.Photos)
        assertTrue(nav.currentDestination?.hasRoute(AddPhotosRoute::class) == true)
        assertEquals(1, nav.currentBackStack.value.count { it.destination.inAdd() })
    }
}
