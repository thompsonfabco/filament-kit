package com.thompsonfabco.filamentkit.ui.settings

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SetupPageTest {
    @Test fun theSetupPageIsOnTheServersOwnAddress() {
        assertEquals("https://192.0.2.10:8710/setup", HubPage.url("https://192.0.2.10:8710"))
        assertEquals("https://kit.local:8710/setup", HubPage.url("https://kit.local:8710/"))
        assertEquals("https://[fd00::10]:8710/setup", HubPage.url("https://[fd00::10]:8710"))
    }

    @Test fun anUnpairedPhoneHasNoAddress() {
        assertNull(HubPage.url(null))
        assertNull(HubPage.url("https://unpaired.invalid"))
        assertNull(HubPage.url("http://192.0.2.10:8710"))
    }
}
