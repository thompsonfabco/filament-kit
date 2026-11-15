package com.thompsonfabco.filamentkit.nav

import android.os.Build
import androidx.compose.material3.Text
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** A tag tap routed on a real back stack (05-android-app 2.6), as the app's tap handler does it. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class TagTapsTest {
    @get:Rule val rule = createComposeRule()

    private lateinit var nav: NavHostController

    private fun graph() {
        rule.setContent {
            nav = rememberNavController()
            NavHost(nav, startDestination = HomeRoute) {
                composable<HomeRoute> { Text("home") }
                composable<AddPhotosRoute> { Text("photos") }
                composable<AddReviewRoute> { Text("check") }
                composable<AddPreviewRoute> { Text("preview") }
                composable<SpoolRoute> { Text("spool") }
                composable<TagRoute> { Text("tag") }
                composable<TagLinkRoute> { Text("link") }
            }
        }
        rule.waitForIdle()
    }

    private fun go(target: Any) {
        rule.runOnUiThread { nav.navigate(target) }
        rule.waitForIdle()
    }

    private fun tap(uid: String, writing: Boolean = false, queued: String? = null): TagTapResult {
        var r: TagTapResult? = null
        rule.runOnUiThread { r = nav.routeTagTap(uid, writing, queued) }
        rule.waitForIdle()
        return r!!
    }

    private fun openTagUid(): String? =
        nav.currentBackStackEntry?.takeIf { it.destination.hasRoute(TagRoute::class) }?.toRoute<TagRoute>()?.uid

    @Test fun photosAndCheckTakeTheTapThemselves() {
        graph()
        go(AddPhotosRoute("d1"))
        assertEquals(TagTapped.LeftToScreen, tap("04:a1").what)
        assertTrue(nav.currentDestination!!.hasRoute(AddPhotosRoute::class))
        go(AddReviewRoute("d1"))
        assertEquals(TagTapped.LeftToScreen, tap("04:a1").what)
        assertTrue(nav.currentDestination!!.hasRoute(AddReviewRoute::class))
    }

    @Test fun anyOtherScreenOpensTheTag() {
        graph()
        assertEquals(TagTapped.Opened, tap("04:a1").what)
        assertEquals("04:a1", openTagUid())
        go(AddPreviewRoute("d1"))
        assertEquals("Preview and Done do not take it (05 2.6)", TagTapped.Opened, tap("04:b2").what)
        assertEquals("04:b2", openTagUid())
    }

    @Test fun aTapDuringAWriteWaitsAndTheLatestOneIsTheOneThatWaits() {
        graph()
        val first = tap("04:a1", writing = true)
        assertEquals(TagTapped.Waits, first.what)
        assertEquals("04:a1", first.queued)
        assertNull("nothing opened", openTagUid())
        assertEquals("04:b2", tap("04:b2", writing = true, queued = first.queued).queued)
    }

    @Test fun aTagThatWaitedThroughAFailedWriteDoesNotOpenOverALaterTap() {
        graph()
        val waiting = tap("04:a1", writing = true)
        // the write failed, the person taps another tag
        val later = tap("04:b2", writing = false, queued = waiting.queued)
        assertEquals(TagTapped.Opened, later.what)
        assertNull("the old tag is forgotten", later.queued)
    }

    @Test fun theSameTagAgainDoesNothingWhateverItsCase() {
        graph()
        tap("04:a1:b2")
        val depth = nav.currentBackStack.value.size
        assertEquals(TagTapped.SameTag, tap("04:A1:B2").what)
        assertEquals(depth, nav.currentBackStack.value.size)
        go(SpoolRoute(5, tag = "04:C3:D4"))
        assertEquals("the spool screen of that tag", TagTapped.SameTag, tap("04:c3:d4").what)
        assertFalse(openTagUid() != null)
    }

    @Test fun aDifferentTagReplacesTheTagScreen() {
        graph()
        tap("04:a1")
        go(TagLinkRoute("04:a1"))
        assertEquals(TagTapped.Opened, tap("04:b2").what)
        assertEquals("04:b2", openTagUid())
        assertEquals(1, nav.currentBackStack.value.count { it.destination.hasRoute(TagRoute::class) })
        assertTrue(nav.currentBackStack.value.none { it.destination.hasRoute(TagLinkRoute::class) })
    }

    @Test fun twoQuickTapsOfAddMakeOneDraft() {
        graph()
        var started = 0
        rule.runOnUiThread {
            repeat(2) { nav.openAddOnce { started++; AddPhotosRoute("d$started") } }
        }
        rule.waitForIdle()
        assertEquals(1, started)
        assertEquals(1, nav.currentBackStack.value.count { it.destination.hasRoute(AddPhotosRoute::class) })
    }
}
