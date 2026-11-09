package com.thompsonfabco.filamentkit

import android.content.res.Configuration
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * MainActivity's window setup ([appEdgeToEdge]) and root ([AppFrame]): a screen whose first and last texts sit
 * at the very top and bottom must still show them clear of the status bar and the navigation bar, and the bars
 * must use icons that show on the background, light or dark. Runs on the plain test activity, because MainActivity asks for the
 * local network permission at start (see LocalNetworkDeniedTest).
 */
@RunWith(AndroidJUnit4::class)
class SystemBarsTest {
    @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

    @Test
    fun contentStaysClearOfTheBarsAndTheIconsFollowTheTheme() {
        rule.runOnUiThread { rule.activity.appEdgeToEdge() }
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
        val night = rule.activity.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK ==
            Configuration.UI_MODE_NIGHT_YES
        assertEquals("dark icons on a light screen", !night, controller.isAppearanceLightStatusBars)
        assertEquals("dark icons on a light screen", !night, controller.isAppearanceLightNavigationBars)
    }

    @Test
    fun theColoursFollowThePhonesSetting() {
        var lightBackground = Color.Unspecified
        var darkBackground = Color.Unspecified
        val base = rule.activity.resources.configuration
        fun mode(night: Int) = Configuration(base).apply {
            uiMode = (base.uiMode and Configuration.UI_MODE_NIGHT_MASK.inv()) or night
        }
        rule.setContent {
            CompositionLocalProvider(LocalConfiguration provides mode(Configuration.UI_MODE_NIGHT_NO)) {
                AppFrame { lightBackground = MaterialTheme.colorScheme.surface }
            }
            CompositionLocalProvider(LocalConfiguration provides mode(Configuration.UI_MODE_NIGHT_YES)) {
                AppFrame { darkBackground = MaterialTheme.colorScheme.surface }
            }
        }
        rule.waitForIdle()
        assertTrue("light: $lightBackground", lightBackground.luminance() > 0.5f)
        assertTrue("dark: $darkBackground", darkBackground.luminance() < 0.5f)
    }
}
