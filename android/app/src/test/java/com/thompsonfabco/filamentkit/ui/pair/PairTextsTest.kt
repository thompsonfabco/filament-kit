package com.thompsonfabco.filamentkit.ui.pair

import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PairTextsTest {
    private fun text(source: MismatchSource) = PairTexts.mismatch(Mismatch("a", "b", source), "kit.local")

    @Test fun aStoredPairingHasChanged() {
        val t = text(MismatchSource.STORED)
        assertEquals("The server's certificate has changed", t.title)
        assertNull("only the new fingerprint is listed", t.expectedLabel)
        assertEquals("New fingerprint", t.actualLabel)
        assertEquals("Pair again", t.button)
        assertEquals("Trust the new certificate", t.trustButton)
        assertEquals(t.body, 1, t.body.count { it == '.' }) // one sentence of risk
        assertTrue(t.body, "another device" in t.body && "this phone's access" in t.body)
        assertTrue("pairing code on the server" in t.whereToCheck!!)
    }

    @Test fun onlyASavedPairingCanBeTrusted() {
        assertNull(text(MismatchSource.QR).trustButton)
        assertNull(text(MismatchSource.MANUAL).trustButton)
        assertEquals("Start again", text(MismatchSource.QR).button)
        assertEquals("Start again", text(MismatchSource.MANUAL).button)
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
            assertFalse(t.toString(), t.expectedLabel.orEmpty().contains("Paired") || t.title.contains("has changed"))
        }
    }

    @Test fun anAddressThatCannotBeReachedSaysWhyWhenThePhoneCanTell() {
        val name = PairTexts.unreachable(UnknownHostException("kit.local"), "kit.local", 8443)
        assertTrue(name, "Could not find kit.local" in name && "IP address" in name)
        val port = PairTexts.unreachable(ConnectException("connect failed: ECONNREFUSED (Connection refused)"), "kit.local", 8443)
        assertTrue(port, "not on port 8443" in port && "8710" in port)
        val rest = PairTexts.unreachable(SocketTimeoutException("timeout"), "kit.local", 8443)
        assertEquals("Could not reach kit.local on port 8443. Check the address and that this phone is on the same network.", rest)
    }

    @Test fun whereACodeComesFromIsNotOnlyTheCommand() {
        assertTrue("setup page" in PairTexts.SCAN_INTRO && "sudo filament-kit pair" in PairTexts.SCAN_INTRO)
        assertTrue("setup page" in QR_EXPIRED && "sudo filament-kit pair" in QR_EXPIRED)
        assertFalse("sudo" in PairTexts.CODE_INTRO)
        assertFalse("sudo" in PairTexts.confirmIntro("kit.local"))
    }
}
