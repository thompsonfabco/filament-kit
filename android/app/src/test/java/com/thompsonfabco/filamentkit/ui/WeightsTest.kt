package com.thompsonfabco.filamentkit.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WeightsTest {
    @Test fun acceptsOnlyFinitePositiveGrams() {
        assertEquals(812.0, parseWeight("812")!!, 0.0)
        assertEquals(12.5, parseWeight(" 12.5 ")!!, 0.0)
        for (bad in listOf("", " ", "abc", "0", "-1", "NaN", "Infinity", "-Infinity", "1e400")) {
            assertNull(bad, parseWeight(bad))
        }
    }

    @Test fun validWeightRejectsNonFiniteAndNonPositive() {
        assertTrue(isValidWeight(0.1))
        assertFalse(isValidWeight(0.0))
        assertFalse(isValidWeight(-2.0))
        assertFalse(isValidWeight(Double.NaN))
        assertFalse(isValidWeight(Double.POSITIVE_INFINITY))
    }
}
