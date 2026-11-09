package com.thompsonfabco.filamentkit.ui.pair

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PairTextsTest {
    private fun text(source: MismatchSource) = PairTexts.mismatch(Mismatch("a", "b", source), "kit.local")

    @Test fun aStoredPairingHasChanged() {
        val t = text(MismatchSource.STORED)
        assertEquals("The server's certificate has changed", t.title)
        assertEquals("Paired fingerprint", t.expectedLabel)
        assertEquals("Pair again", t.button)
    }

    /** Nothing is paired yet, so nothing can have "changed" and there is no "paired" fingerprint. */
    @Test fun aScannedCodeNamesTheCodeNotAPairing() {
        val t = text(MismatchSource.QR)
        assertEquals("This pairing code doesn't match the server", t.title)
        assertTrue(t.body, "kit.local" in t.body && "Make a new code" in t.body)
        assertEquals("Fingerprint in the code", t.expectedLabel)
        assertFalse(t.body, "reinstalled" in t.body)
    }

    @Test fun theManualPathNamesTheCheckJustMade() {
        val t = text(MismatchSource.MANUAL)
        assertEquals("The server's certificate changed while pairing", t.title)
        assertEquals("Fingerprint seen first", t.expectedLabel)
        assertTrue(t.body, "kit.local" in t.body)
        assertFalse("no code was named on this path", "code" in t.body)
    }

    @Test fun onlyAStoredPairingSaysPaired() {
        for (s in listOf(MismatchSource.QR, MismatchSource.MANUAL)) {
            val t = text(s)
            assertFalse(t.toString(), t.expectedLabel.contains("Paired") || t.title.contains("has changed"))
        }
    }

    @Test fun whereACodeComesFromIsNotOnlyTheCommand() {
        assertTrue("setup page" in PairTexts.SCAN_INTRO && "sudo filament-kit pair" in PairTexts.SCAN_INTRO)
        assertTrue("setup page" in QR_EXPIRED && "sudo filament-kit pair" in QR_EXPIRED)
        assertFalse("sudo" in PairTexts.CODE_INTRO)
        assertFalse("sudo" in PairTexts.confirmIntro("kit.local"))
    }
}
