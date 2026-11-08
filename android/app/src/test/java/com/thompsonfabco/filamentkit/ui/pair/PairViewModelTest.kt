package com.thompsonfabco.filamentkit.ui.pair

import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.data.SettingsStore
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LOCAL_NETWORK_MESSAGE
import com.thompsonfabco.filamentkit.net.ServerInfo
import java.io.IOException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private const val FP = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

private class FakeSettings : SettingsStore {
    var saved: ServerConfig? = null
    var saves = 0
    override suspend fun save(config: ServerConfig) { saved = config; saves++ }
    override suspend fun clear() { saved = null }
}

private class FakeBackend : PairingBackend {
    val calls = mutableListOf<String>()
    var probeResult: () -> String = { FP }
    var pairResult: (String) -> String = { "token-1" }
    var infoResult: (String) -> ServerInfo = { ServerInfo("Workshop server", "1", 1) }

    override suspend fun probe(host: String, port: Int): String {
        calls += "probe $host:$port"
        return probeResult()
    }

    override suspend fun pair(host: String, port: Int, fingerprint: String, code: String): String {
        calls += "pair $code"
        return pairResult(code)
    }

    override suspend fun info(host: String, port: Int, fingerprint: String, token: String?): ServerInfo {
        calls += "info"
        return infoResult(host)
    }

    var claimResult: (String) -> Unit = {}
    override suspend fun claim(host: String, port: Int, fingerprint: String, token: String) {
        calls += "claim $host $token"
        claimResult(host)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class PairViewModelTest {
    private val settings = FakeSettings()
    private val backend = FakeBackend()
    private val vm = PairViewModel(settings, backend, CoroutineScope(UnconfinedTestDispatcher()), pickGroups = { listOf(1, 14) })
    private val ui get() = vm.state.value

    /** Group 1 of FP is 4567, group 14 is 89ab. */
    private fun confirm() = vm.confirmFingerprint(listOf("4567", "89ab"))

    private fun qr(vararg ips: String) =
        "fkit://pair?h=kit.local&p=8443&t=qr-token&fp=$FP" + ips.joinToString("") { "&ip=$it" }

    @Test fun fingerprintIsShownBeforeAnyCodeIsSent() {
        vm.startManual("")
        vm.submitAddress("10.0.0.2", "")
        assertEquals(Step.Confirm, ui.step)
        assertEquals(FP, ui.fingerprint)
        assertEquals(8710, ui.port)
        assertEquals(listOf("probe 10.0.0.2:8710"), backend.calls)
        assertNull(settings.saved)
    }

    @Test fun codeIsOnlySentAfterConfirmAndEntry() {
        vm.submitAddress("10.0.0.2", "")
        confirm()
        assertEquals(Step.Code, ui.step)
        assertFalse(backend.calls.any { it.startsWith("pair") })
        vm.submitCode("123456")
        assertEquals(Step.Done, ui.step)
    }

    @Test fun submittingACodeWithoutConfirmingDoesNothing() {
        vm.submitAddress("10.0.0.2", "")
        vm.submitCode("123456")
        assertEquals(Step.Confirm, ui.step)
        assertFalse(backend.calls.any { it.startsWith("pair") })
    }

    @Test fun theProbeChoosesTheGroups() {
        vm.submitAddress("10.0.0.2", "")
        assertEquals(listOf(1, 14), ui.askedGroups)
    }

    @Test fun wrongGroupsStayOnTheCheckWithTheSameGroupsAndSendNothing() {
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint(listOf("4567", "0000"))
        assertEquals(Step.Confirm, ui.step)
        assertEquals(PairTexts.FINGERPRINT_WRONG, ui.error)
        assertEquals(listOf(1, 14), ui.askedGroups)
        vm.submitCode("123456")
        assertFalse(backend.calls.any { it.startsWith("pair") })
    }

    @Test fun oneRightGroupIsNotEnough() {
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint(listOf("0000", "89ab"))
        assertEquals(Step.Confirm, ui.step)
        vm.confirmFingerprint(listOf("4567"))
        assertEquals(Step.Confirm, ui.step)
        vm.confirmFingerprint(emptyList())
        assertEquals(Step.Confirm, ui.step)
    }

    @Test fun rightGroupsAfterAWrongTryContinueAndClearTheError() {
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint(listOf("0000", "0000"))
        confirm()
        assertEquals(Step.Code, ui.step)
        assertNull(ui.error)
    }

    @Test fun anotherProbeDrawsAgainAndForgetsTheOldGroups() {
        var draw = 0
        val drawing = PairViewModel(settings, backend, CoroutineScope(UnconfinedTestDispatcher()),
            pickGroups = { if (draw++ == 0) listOf(1, 14) else listOf(2, 3) })
        drawing.submitAddress("10.0.0.2", "")
        drawing.rejectFingerprint()
        assertEquals(emptyList<Int>(), drawing.state.value.askedGroups)
        drawing.submitAddress("10.0.0.2", "")
        assertEquals(listOf(2, 3), drawing.state.value.askedGroups)
    }

    @Test fun declineReturnsToAddressWithoutSendingACode() {
        vm.submitAddress("10.0.0.2", "9000")
        vm.rejectFingerprint()
        assertEquals(Step.Address, ui.step)
        assertNull(ui.fingerprint)
        assertFalse(backend.calls.any { it.startsWith("pair") })
    }

    @Test fun wrongCodeShowsTheServersMessageAndAllowsRetry() {
        backend.pairResult = { throw ApiError(401, "unauthorized", "That code is wrong or has expired") }
        vm.submitAddress("10.0.0.2", "")
        confirm()
        vm.submitCode("000000")
        assertEquals(Step.Code, ui.step)
        assertEquals("That code is wrong or has expired", ui.error)
        assertFalse(ui.busy)
        assertNull(settings.saved)
        backend.pairResult = { "token-2" }
        vm.submitCode("123456")
        assertEquals(Step.Done, ui.step)
        assertNull(ui.error)
    }

    @Test fun malformedCodeIsRejectedLocally() {
        vm.submitAddress("10.0.0.2", "")
        confirm()
        vm.submitCode("12ab")
        assertEquals(Step.Code, ui.step)
        assertNotNull(ui.error)
        assertFalse(backend.calls.any { it.startsWith("pair") })
    }

    @Test fun successSavesConfigWithTheProbedFingerprintAndTypedHost() {
        vm.submitAddress(" 10.0.0.2 ", "9000")
        confirm()
        vm.submitCode("123456")
        assertEquals(ServerConfig(listOf("10.0.0.2"), 9000, FP, "token-1", "Workshop server"), settings.saved)
        assertEquals(Step.Done, ui.step)
    }

    @Test fun nameFallsBackToHostWhenInfoFails() {
        backend.infoResult = { _ -> throw ApiError(0, "offline", "x") }
        vm.submitAddress("10.0.0.2", "")
        confirm()
        vm.submitCode("123456")
        assertEquals("10.0.0.2", settings.saved?.name)
        assertEquals(Step.Done, ui.step)
    }

    @Test fun unreachableHostShowsPlainError() {
        backend.probeResult = { throw IOException("boom") }
        vm.submitAddress("10.0.0.2", "")
        assertEquals(Step.Address, ui.step)
        assertTrue(ui.error!!.contains("10.0.0.2"))
    }

    @Test fun badPortIsRejected() {
        vm.submitAddress("10.0.0.2", "99999")
        assertEquals(Step.Address, ui.step)
        assertNotNull(ui.error)
        assertTrue(backend.calls.isEmpty())
    }

    @Test fun unexpectedExceptionDoesNotCrash() {
        backend.pairResult = { throw IllegalStateException("weird") }
        vm.submitAddress("10.0.0.2", "")
        confirm()
        vm.submitCode("123456")
        assertEquals("Unexpected response from the server", ui.error)
        assertFalse(ui.busy)
    }

    @Test fun certificateChangedDuringPairingShowsBothFingerprints() {
        backend.pairResult = { throw FingerprintMismatch(FP, "f".repeat(64)) }
        vm.submitAddress("10.0.0.2", "")
        confirm()
        vm.submitCode("123456")
        assertEquals(Mismatch(FP, "f".repeat(64), MismatchSource.MANUAL), ui.mismatch)
        vm.pairAgain()
        assertNull(ui.mismatch)
        assertEquals(Step.Choose, ui.step)
    }

    @Test fun qrSavesEndpointsHostThenIpsAndVerifiesWithInfo() {
        vm.onQrScanned(qr("192.168.1.5", "10.0.0.9"))
        assertEquals(
            ServerConfig(listOf("kit.local", "192.168.1.5", "10.0.0.9"), 8443, FP, "qr-token", "Workshop server"),
            settings.saved,
        )
        assertEquals(listOf("info", "claim kit.local qr-token"), backend.calls)
        assertEquals(1, settings.saves)
        assertEquals(Step.Done, ui.step)
    }

    @Test fun qrThatIsNotOursShowsError() {
        vm.onQrScanned("https://example.com")
        assertEquals(Step.Choose, ui.step)
        assertNotNull(ui.error)
        assertNull(settings.saved)
    }

    @Test fun qrVerifyFailureLeavesAnExistingConfigUntouchedAndSavesNothing() {
        val existing = ServerConfig(listOf("old.local"), 8710, "a".repeat(64), "old-token", "Old")
        settings.saved = existing
        backend.infoResult = { _ -> throw ApiError(0, "offline", "Cannot reach") }
        vm.onQrScanned(qr("192.168.1.5"))
        assertEquals(existing, settings.saved)
        assertEquals(0, settings.saves)
        assertEquals(Step.Choose, ui.step)
        assertNotNull(ui.error)
    }

    @Test fun qrFallsBackToAnIpWhenTheNameFailsAndRemembersItFirst() {
        backend.infoResult = { h -> if (h == "kit.local") throw ApiError(0, "offline", "x") else ServerInfo("Workshop server", "1", 1) }
        vm.onQrScanned(qr("192.168.1.5", "10.0.0.9"))
        assertEquals(listOf("info", "info", "claim 192.168.1.5 qr-token"), backend.calls)
        assertEquals(listOf("192.168.1.5", "kit.local", "10.0.0.9"), settings.saved?.endpoints)
        assertEquals(1, settings.saves)
        assertEquals(Step.Done, ui.step)
    }

    @Test fun qrTokenTheServerNoLongerAcceptsSavesNothing() {
        backend.claimResult = { throw ApiError(401, "unauthorized", "missing or revoked token") }
        vm.onQrScanned(qr("192.168.1.5"))
        assertNull(settings.saved)
        assertEquals(0, settings.saves)
        assertEquals(Step.Choose, ui.step)
        assertEquals(QR_EXPIRED, ui.error)
        assertTrue(ui.error!!.contains("sudo filament-kit pair"))
    }

    @Test fun qrClaimAnsweredWithAnotherServerErrorStillCountsAsClaimed() {
        backend.claimResult = { throw ApiError(502, "printer_error", "printer lookup failed") }
        vm.onQrScanned(qr())
        assertEquals("qr-token", settings.saved?.token)
        assertEquals(Step.Done, ui.step)
    }

    @Test fun qrClaimThatCannotReachTheServerSavesNothing() {
        backend.claimResult = { throw ApiError(0, "offline", "gone") }
        vm.onQrScanned(qr())
        assertNull(settings.saved)
        assertEquals(Step.Choose, ui.step)
        assertNotNull(ui.error)
    }

    @Test fun localNetworkMissingExplainsThePermissionInsteadOfOffline() {
        val blocked = PairViewModel(settings, backend, CoroutineScope(UnconfinedTestDispatcher()), localNetworkMissing = { true })
        backend.probeResult = { throw IOException("EPERM") }
        blocked.submitAddress("10.0.0.2", "")
        assertEquals(LOCAL_NETWORK_MESSAGE, blocked.state.value.error)
    }

    @Test fun qrParseErrorIsAFixedMessage() {
        vm.onQrScanned("fkit://pair?h=x")
        assertEquals("That is not a filament-kit pairing code", ui.error)
    }

    @Test fun qrVerifyMismatchShowsBothFingerprints() {
        backend.infoResult = { _ -> throw FingerprintMismatch(FP, "e".repeat(64)) }
        vm.onQrScanned(qr())
        assertEquals(Mismatch(FP, "e".repeat(64), MismatchSource.QR), ui.mismatch)
        assertNull(settings.saved)
    }

    @Test fun fingerprintGroupsOfFour() {
        assertEquals("0123 4567 89ab", groupFingerprint("0123456789ab"))
    }

    @Test fun discoveredServerGoesStraightToTheFingerprintCheck() {
        vm.connectDiscovered("kit.local", 8443)
        assertEquals(listOf("probe kit.local:8443"), backend.calls)
        assertEquals(Step.Confirm, ui.step)
        assertEquals(FP, ui.fingerprint)
        assertNull("no code or token yet", settings.saved)
    }

    @Test fun discoveredServerStillNeedsTheCheckBeforeACode() {
        vm.connectDiscovered("kit.local", 8443)
        vm.submitCode("123456")
        assertFalse(backend.calls.any { it.startsWith("pair") })
        assertEquals(Step.Confirm, ui.step)
    }

    @Test fun discoveredServerThatDoesNotAnswerLandsOnTheFilledAddressForm() {
        backend.probeResult = { throw IOException("refused") }
        vm.connectDiscovered("kit.local", 8443)
        assertEquals(Step.Address, ui.step)
        assertEquals("kit.local", ui.host)
        assertEquals(8443, ui.port)
        assertEquals("Could not reach kit.local on port 8443. Check the address and that this phone is on the same network.",
            ui.error)
    }

    @Test fun startManualCanBePrefilled() {
        vm.startManual("kit.local", 8443)
        assertEquals(Step.Address, ui.step)
        assertEquals("kit.local", ui.host)
        assertEquals(8443, ui.port)
    }

    @Test fun showMismatchFromElsewhereShowsBothFingerprintsAndPairAgainClearsIt() {
        vm.showMismatch("old", "new")
        assertEquals(Mismatch("old", "new", MismatchSource.STORED), ui.mismatch)
        assertEquals(Step.Choose, ui.step)
        vm.pairAgain()
        assertNull(ui.mismatch)
    }
}
