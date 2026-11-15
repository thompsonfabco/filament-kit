package com.thompsonfabco.filamentkit.ui

import android.os.Build
import androidx.compose.material3.ExperimentalMaterial3Api
import com.thompsonfabco.filamentkit.ui.theme.Look
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * AUT-8 in Panes (09-implementation-order S6.9): every screen [ScreenSemanticsTest] audits for Console, drawn in the
 * Panes look on the same phone window, in light and dark at font scale 1 and 2. Console's own run is unchanged.
 */
@OptIn(ExperimentalMaterial3Api::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class PanesScreenSemanticsTest : ScreenSemanticsTest() {
    override val look: Look = Look.Panes
}

/** The same audit on a tablet window (600 to 839 dp wide), with no navigation around the screen. */
@OptIn(ExperimentalMaterial3Api::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w700dp-h8000dp")
class PanesTabletScreenSemanticsTest : ScreenSemanticsTest() {
    override val look: Look = Look.Panes
}

/** The same audit on expanded width (840 dp and wider). */
@OptIn(ExperimentalMaterial3Api::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w1000dp-h8000dp")
class PanesExpandedScreenSemanticsTest : ScreenSemanticsTest() {
    override val look: Look = Look.Panes
}
