package com.thompsonfabco.filamentkit.ui.add

import android.os.Build
import androidx.compose.material3.Text
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.navigation.compose.ComposeNavigator
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.navigation
import androidx.navigation.compose.rememberNavController
import androidx.navigation.NavHostController
import com.thompsonfabco.filamentkit.nav.AddPhotosRoute
import com.thompsonfabco.filamentkit.nav.HomeGraph
import com.thompsonfabco.filamentkit.nav.HomeRoute
import com.thompsonfabco.filamentkit.nav.PrintersGraph
import com.thompsonfabco.filamentkit.nav.PrintersRoute
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.nav.selectTab
import com.thompsonfabco.filamentkit.tags.TagEvents
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** A tag tap reaches the add screen only while that screen is showing (05-android-app 2.6). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S])
class TagTapsTest {
    @get:Rule val rule = createComposeRule()

    @Test fun aTapWhileAddSitsOnAHiddenTabChangesNothing() {
        val taken = mutableStateListOf<String>()
        lateinit var nav: NavHostController
        rule.setContent {
            nav = rememberNavController()
            NavHost(nav, startDestination = HomeGraph) {
                navigation<HomeGraph>(startDestination = HomeRoute) {
                    composable<HomeRoute> { Text("home") }
                    composable<AddPhotosRoute> {
                        TagTaps { taken += it }
                        Text("add")
                    }
                }
                navigation<PrintersGraph>(startDestination = PrintersRoute) { composable<PrintersRoute> { Text("printers") } }
            }
        }
        rule.runOnIdle { nav.navigate(AddPhotosRoute("d")) }
        rule.waitForIdle()
        TagEvents.emit("04:aa")
        rule.waitForIdle()
        assertEquals("shown: the add takes the tap", listOf("04:aa"), taken.toList())

        rule.runOnIdle { nav.selectTab(Tab.Printers) }
        rule.waitForIdle()
        TagEvents.emit("04:bb")
        rule.waitForIdle()
        assertEquals("hidden on another tab: nothing changes", listOf("04:aa"), taken.toList())

        rule.runOnIdle { nav.selectTab(Tab.Home) }
        rule.waitForIdle()
        TagEvents.emit("04:cc")
        rule.waitForIdle()
        assertEquals("back on screen: it takes taps again", listOf("04:aa", "04:cc"), taken.toList())
    }
}
