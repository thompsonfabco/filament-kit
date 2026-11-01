package com.thompsonfabco.filamentkit

import org.junit.Assert.assertEquals
import org.junit.Test

class SmokeTest {
    @Test
    fun applicationIdIsFilamentKit() {
        assertEquals("com.thompsonfabco.filamentkit", BuildConfig.APPLICATION_ID)
    }
}
