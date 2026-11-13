package com.thompsonfabco.filamentkit.ui.theme

import androidx.compose.ui.unit.dp
import org.junit.Assert.assertEquals
import org.junit.Test

/** The control height is the phone height (44 dp in Console) at every window class. */
class SwDensityTest {
    @Test fun controlIsTheControlPhoneHeightAtEveryWindowClass() {
        for (look in Look.entries) {
            val sizes = SpoolwardenTokens.of(look).sizes
            assertEquals("$look", sizes.controlPhone, SwDensity(sizes).control)
        }
        assertEquals(44.dp, SwDensity(SpoolwardenTokens.of(Look.Console).sizes).control)
    }
}
