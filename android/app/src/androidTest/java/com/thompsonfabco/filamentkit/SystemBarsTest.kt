package com.thompsonfabco.filamentkit

import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * MainActivity's window setup ([lightEdgeToEdge]) and root ([AppFrame]): a screen whose first and last texts sit
 * at the very top and bottom must still show them clear of the status bar and the navigation bar, and the bars
 * must use dark icons on the light background. Runs on the plain test activity, because MainActivity asks for the
 * local network permission at start (see LocalNetworkDeniedTest).
 */
@RunWith(AndroidJUnit4::class)
class SystemBarsTest {
    @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

    @Test
    fun contentStaysClearOfTheBarsAndTheIconsAreDark() {
        rule.runOnUiThread { rule.activity.lightEdgeToEdge() }
        rule.setContent {
            AppFrame {
                Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.SpaceBetween) {
                    Text("Screen title")
                    Text("Bottom button")
                }
            }
        }
        rule.waitForIdle()

        val window = rule.activity.window
        val view = window.decorView
        val bars = ViewCompat.getRootWindowInsets(view)!!.getInsets(WindowInsetsCompat.Type.systemBars())
        assertTrue("the status bar has a height", bars.top > 0)
        assertTrue("the navigation bar has a height", bars.bottom > 0)

        val title = rule.onNodeWithText("Screen title").fetchSemanticsNode().boundsInWindow
        val bottom = rule.onNodeWithText("Bottom button").fetchSemanticsNode().boundsInWindow
        assertTrue("title at ${title.top}, under the status bar (${bars.top})", title.top >= bars.top)
        val navTop = view.height - bars.bottom
        assertTrue("bottom text ends at ${bottom.bottom}, under the navigation bar ($navTop)", bottom.bottom <= navTop)

        val controller = WindowCompat.getInsetsController(window, view)
        assertTrue("dark status bar icons", controller.isAppearanceLightStatusBars)
        assertTrue("dark navigation bar icons", controller.isAppearanceLightNavigationBars)
    }
}
