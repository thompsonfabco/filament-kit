package com.thompsonfabco.filamentkit.ui.pair

import java.util.Random
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FingerprintCheckTest {
    /** Every group different, so a group cannot be found on screen by accident. */
    private val fp = (0 until 16).joinToString("") { "%04x".format(0xa000 + it) }

    @Test fun twoDifferentGroupsInRangeInOrder() {
        val r = Random(1)
        repeat(500) {
            val asked = pickAskedGroups(16, r)
            assertEquals(2, asked.size)
            assertTrue(asked.toString(), asked[0] < asked[1])
            assertTrue(asked.toString(), asked.all { i -> i in 0 until 16 })
        }
    }

    @Test fun everyGroupAndEveryPairCanComeUp() {
        val r = Random(2)
        val seen = (0 until 20_000).map { pickAskedGroups(16, r) }.toSet()
        assertEquals("all 120 pairs of 16 groups", 120, seen.size)
    }

    @Test fun anAskedGroupIsNeverOnTheScreen() {
        val prompt = fingerprintPrompt(fp, listOf(2, 9))
        assertEquals(16, prompt.size)
        assertNull(prompt[2])
        assertNull(prompt[9])
        val shown = prompt.filterNotNull()
        assertEquals(14, shown.size)
        assertFalse(fp.chunked(4)[2] in shown)
        assertFalse(fp.chunked(4)[9] in shown)
    }

    @Test fun theOtherGroupsKeepTheirPlaces() {
        val prompt = fingerprintPrompt(fp, listOf(2, 9))
        fp.chunked(4).forEachIndexed { i, group -> if (i != 2 && i != 9) assertEquals(group, prompt[i]) }
    }

    @Test fun bothGroupsMustMatchEitherCase() {
        val g = fp.chunked(4)
        assertTrue(askedGroupsMatch(fp, listOf(2, 9), listOf(g[2], g[9])))
        assertTrue(askedGroupsMatch(fp, listOf(2, 9), listOf(g[2].uppercase(), " ${g[9]} ")))
        assertFalse(askedGroupsMatch(fp, listOf(2, 9), listOf(g[2], g[8])))
        assertFalse(askedGroupsMatch(fp, listOf(2, 9), listOf(g[8], g[9])))
        assertFalse("the order is the fields' order", askedGroupsMatch(fp, listOf(2, 9), listOf(g[9], g[2])))
    }

    @Test fun nothingAskedOrTooFewEntriesNeverMatches() {
        val g = fp.chunked(4)
        assertFalse(askedGroupsMatch(fp, emptyList(), emptyList()))
        assertFalse(askedGroupsMatch(fp, listOf(2, 9), listOf(g[2])))
        assertFalse(askedGroupsMatch(fp, listOf(99), listOf("")))
    }
}
