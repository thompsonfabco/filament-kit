package com.thompsonfabco.filamentkit.tags

import org.junit.Assert.assertEquals
import org.junit.Test

class TagUidTest {
    @Test
    fun formatsLowercaseHexWithoutPadding() {
        val uid = byteArrayOf(0x04, 0x77, 0x90.toByte(), 0x0E, 0x09, 0x22, 0x89.toByte())
        assertEquals("4:77:90:e:9:22:89", formatUid(uid))
    }
}
