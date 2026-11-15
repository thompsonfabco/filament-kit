package com.thompsonfabco.filamentkit.ui

import android.os.Build
import androidx.compose.material3.ExperimentalMaterial3Api
import com.thompsonfabco.filamentkit.ui.theme.Look
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * AUT-8 in Workbench (09-implementation-order S6.5): every screen [ScreenSemanticsTest] audits for Console, drawn in the
 * Workbench look on the same phone window, in light and dark at font scale 1 and 2. Console's own run is unchanged.
 */
@OptIn(ExperimentalMaterial3Api::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class WorkbenchScreenSemanticsTest : ScreenSemanticsTest() {
    override val look: Look = Look.Workbench
}
