package com.thompsonfabco.filamentkit.ui.settings

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SetupPageTest {
    @Test fun theSetupPageIsOnTheServersOwnAddress() {
        assertEquals("https://192.0.2.10:8710/setup", SetupPageTexts.url("https://192.0.2.10:8710"))
        assertEquals("https://kit.local:8710/setup", SetupPageTexts.url("https://kit.local:8710/"))
        assertEquals("https://[fd00::10]:8710/setup", SetupPageTexts.url("https://[fd00::10]:8710"))
    }

    @Test fun anUnpairedPhoneHasNoAddress() {
        assertNull(SetupPageTexts.url(null))
        assertNull(SetupPageTexts.url("https://unpaired.invalid"))
        assertNull(SetupPageTexts.url("http://192.0.2.10:8710"))
    }
}
