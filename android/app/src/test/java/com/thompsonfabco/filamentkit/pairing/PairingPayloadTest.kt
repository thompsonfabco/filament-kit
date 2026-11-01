package com.thompsonfabco.filamentkit.pairing

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class PairingPayloadTest {
    private val fp = "0f".repeat(32)

    @Test
    fun parsesServerFormatWithTwoIpsAndEncodedValues() {
        // What server/filament_kit/pairing.py issue() emits via urlencode(..., doseq=True)
        // for the token "Ab-_x+y/z=" (quote_plus encoding).
        val uri = "fkit://pair?h=kit.local&p=8443&t=Ab-_x%2By%2Fz%3D&fp=$fp&ip=192.168.1.20&ip=10.0.0.5"

        val p = parsePairingUri(uri)

        assertEquals(PairingPayload("kit.local", 8443, "Ab-_x+y/z=", fp, listOf("192.168.1.20", "10.0.0.5")), p)
    }

    @Test
    fun ipIsOptional() {
        val p = parsePairingUri("fkit://pair?h=kit.local&p=8443&t=tok&fp=$fp")
        assertEquals(emptyList<String>(), p.ips)
    }

    @Test
    fun uppercaseFingerprintIsNormalisedToLowercase() {
        val p = parsePairingUri("fkit://pair?h=kit.local&p=8443&t=tok&fp=${fp.uppercase()}")
        assertEquals(fp, p.fingerprint)
    }

    @Test
    fun rejectsWrongScheme() {
        assertBad("http://pair?h=kit.local&p=8443&t=tok&fp=$fp")
        assertBad("https://kit.local/pair?h=kit.local&p=8443&t=tok&fp=$fp")
        assertBad("fkit://other?h=kit.local&p=8443&t=tok&fp=$fp")
        assertBad("not a uri at all")
    }

    @Test
    fun rejectsMissingFields() {
        assertBad("fkit://pair?p=8443&t=tok&fp=$fp")
        assertBad("fkit://pair?h=kit.local&t=tok&fp=$fp")
        assertBad("fkit://pair?h=kit.local&p=8443&fp=$fp")
        assertBad("fkit://pair?h=kit.local&p=8443&t=tok")
        assertBad("fkit://pair?h=kit.local&p=8443&t=&fp=$fp")
        assertBad("fkit://pair")
    }

    @Test
    fun rejectsBadPortAndFingerprint() {
        assertBad("fkit://pair?h=kit.local&p=abc&t=tok&fp=$fp")
        assertBad("fkit://pair?h=kit.local&p=70000&t=tok&fp=$fp")
        assertBad("fkit://pair?h=kit.local&p=8443&t=tok&fp=${fp.dropLast(1)}")
        assertBad("fkit://pair?h=kit.local&p=8443&t=tok&fp=${fp.dropLast(1)}g")
        assertBad("fkit://pair?h=kit.local&p=8443&t=tok&fp=${"0f:".repeat(31)}0f")
    }

    @Test
    fun rejectsDuplicateSingleValuedFields() {
        assertBad("fkit://pair?h=kit.local&p=8443&t=tok&fp=$fp&fp=${"ab".repeat(32)}")
    }

    private fun assertBad(uri: String) {
        assertThrows(uri, IllegalArgumentException::class.java) { parsePairingUri(uri) }
    }
}
