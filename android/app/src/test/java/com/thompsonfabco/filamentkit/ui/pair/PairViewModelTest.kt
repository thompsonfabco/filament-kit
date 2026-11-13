package com.thompsonfabco.filamentkit.ui.pair

import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.data.SettingsStore
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
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
    var skip = false
    override suspend fun skipsFingerprintCheck() = skip
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
    private val vm = PairViewModel(settings, backend, CoroutineScope(UnconfinedTestDispatcher()))
    private val ui get() = vm.state.value

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
        vm.confirmFingerprint()
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

    @Test fun declineReturnsToTheFirstScreenWithoutSendingACode() {
        vm.submitAddress("10.0.0.2", "9000")
        vm.rejectFingerprint()
        assertEquals(Step.Choose, ui.step)
        assertNull(ui.fingerprint)
        assertEquals(PairMessage.Res(R.string.pair_fingerprint_rejected), ui.error)
        assertNull("no field: the notice sits under the button", ui.errorField)
        assertFalse(backend.calls.any { it.startsWith("pair") })
    }

    @Test fun connectingAgainAfterDecliningClearsTheSentence() {
        vm.submitAddress("10.0.0.2", "9000")
        vm.rejectFingerprint()
        vm.submitAddress("10.0.0.3", "9000")
        assertEquals(Step.Confirm, ui.step)
        assertNull(ui.error)
    }

    @Test fun withTheCheckSkippedAddressGoesStraightToTheCodeAndPinsTheProbedCertificate() {
        settings.skip = true
        vm.submitAddress("10.0.0.2", "9000")
        assertEquals(Step.Code, ui.step)
        assertEquals(FP, ui.fingerprint)
        assertFalse(backend.calls.any { it.startsWith("pair") })
        vm.submitCode("123456")
        assertEquals(Step.Done, ui.step)
        assertEquals(ServerConfig(listOf("10.0.0.2"), 9000, FP, "token-1", "Workshop server"), settings.saved)
    }

    @Test fun withTheCheckSkippedAFoundServerGoesStraightToTheCode() {
        settings.skip = true
        vm.connectDiscovered("10.0.0.2", 8710)
        assertEquals(Step.Code, ui.step)
    }

    @Test fun skippingTheCheckStillStopsOnACertificateChangedBeforeTheCode() {
        settings.skip = true
        backend.pairResult = { throw FingerprintMismatch(FP, "other") }
        vm.submitAddress("10.0.0.2", "")
        vm.submitCode("123456")
        assertEquals(MismatchSource.MANUAL, ui.mismatch?.source)
        assertNull(settings.saved)
    }

    @Test fun skippingTheCheckDoesNotCoverAScannedCode() {
        settings.skip = true
        backend.infoResult = { throw FingerprintMismatch(FP, "other") }
        vm.onQrScanned(qr())
        assertEquals(MismatchSource.QR, ui.mismatch?.source)
        assertNull(settings.saved)
    }

    @Test fun wrongCodeShowsTheServersMessageAndAllowsRetry() {
        backend.pairResult = { throw ApiError(401, "unauthorized", "That code is wrong or has expired") }
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint()
        vm.submitCode("000000")
        assertEquals(Step.Code, ui.step)
        assertEquals(PairMessage.Res(R.string.pair_error_refused), ui.error)
        assertFalse(ui.busy)
        assertNull(settings.saved)
        backend.pairResult = { "token-2" }
        vm.submitCode("123456")
        assertEquals(Step.Done, ui.step)
        assertNull(ui.error)
    }

    @Test fun malformedCodeIsRejectedLocally() {
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint()
        vm.submitCode("12ab")
        assertEquals(Step.Code, ui.step)
        assertNotNull(ui.error)
        assertFalse(backend.calls.any { it.startsWith("pair") })
    }

    @Test fun successSavesConfigWithTheProbedFingerprintAndTypedHost() {
        vm.submitAddress(" 10.0.0.2 ", "9000")
        vm.confirmFingerprint()
        vm.submitCode("123456")
        assertEquals(ServerConfig(listOf("10.0.0.2"), 9000, FP, "token-1", "Workshop server"), settings.saved)
        assertEquals(Step.Done, ui.step)
    }

    @Test fun nameFallsBackToHostWhenInfoFails() {
        backend.infoResult = { _ -> throw ApiError(0, "offline", "x") }
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint()
        vm.submitCode("123456")
        assertEquals("10.0.0.2", settings.saved?.name)
        assertEquals(Step.Done, ui.step)
    }

    @Test fun unreachableHostShowsPlainError() {
        backend.probeResult = { throw IOException("boom") }
        vm.submitAddress("10.0.0.2", "")
        assertEquals(Step.Address, ui.step)
        assertEquals(PairMessage.Res(R.string.common_hub_unreachable), ui.error)
        assertNull("a connection failure belongs under the button", ui.errorField)
    }

    @Test fun badPortIsRejectedUnderThePortField() {
        vm.submitAddress("10.0.0.2", "99999")
        assertEquals(Step.Address, ui.step)
        assertEquals(PairMessage.Res(R.string.pair_address_error_port), ui.error)
        assertEquals(PairField.Port, ui.errorField)
        assertTrue(backend.calls.isEmpty())
    }

    @Test fun anEmptyAddressIsRejectedUnderTheAddressField() {
        vm.submitAddress("  ", "")
        assertEquals(PairMessage.Res(R.string.pair_address_error_empty), ui.error)
        assertEquals(PairField.Address, ui.errorField)
        assertTrue(backend.calls.isEmpty())
    }

    @Test fun somethingThatIsNotAHubIsNamedAsSuch() {
        backend.pairResult = { throw ApiError(404, "not_found", "Not Found") }
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint()
        vm.submitCode("123456")
        assertEquals(PairMessage.Res(R.string.pair_error_not_hub), ui.error)
    }

    @Test fun anErrorPageWithNoHubMessageIsNotAHub() {
        // the shape Api.errorFor gives a non-JSON error page
        val page = ApiError(502, "internal", "The server returned an error (502)", noHubMessage = true)
        backend.pairResult = { throw page }
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint()
        vm.submitCode("123456")
        assertEquals(PairMessage.Res(R.string.pair_error_not_hub), ui.error)
    }

    @Test fun aNonJsonUnauthorizedPageIsNotAHubEither() {
        backend.pairResult = { throw ApiError(401, "unauthorized", "The server returned an error (401)", noHubMessage = true) }
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint()
        vm.submitCode("123456")
        assertEquals(PairMessage.Res(R.string.pair_error_not_hub), ui.error)
    }

    @Test fun aServiceThatDoesNotSpeakTlsOnTheProbeIsNotAHub() {
        backend.probeResult = { throw javax.net.ssl.SSLException("Unable to parse TLS packet header") }
        vm.submitAddress("10.0.0.2", "")
        assertEquals(PairMessage.Res(R.string.pair_error_not_hub), ui.error)
        backend.probeResult = { throw javax.net.ssl.SSLHandshakeException("handshake failure") }
        vm.submitAddress("10.0.0.2", "")
        assertEquals(PairMessage.Res(R.string.pair_error_not_hub), ui.error)
    }

    @Test fun aTimeoutOnTheProbeIsStillUnreachable() {
        backend.probeResult = { throw java.net.SocketTimeoutException("timeout") }
        vm.submitAddress("10.0.0.2", "")
        assertEquals(PairMessage.Res(R.string.common_hub_unreachable), ui.error)
    }

    @Test fun whatTheHubSaysItselfIsShownWhenTheTableHasNoRowForIt() {
        backend.pairResult = { throw ApiError(429, "rate_limited", "Too many tries. Wait a minute.") }
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint()
        vm.submitCode("123456")
        assertEquals(PairMessage.Raw("Too many tries. Wait a minute."), ui.error)
    }

    @Test fun unexpectedExceptionDoesNotCrash() {
        backend.pairResult = { throw IllegalStateException("weird") }
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint()
        vm.submitCode("123456")
        assertEquals(PairMessage.Res(R.string.pair_error_not_hub), ui.error)
        assertFalse(ui.busy)
    }

    @Test fun certificateChangedDuringPairingShowsBothFingerprints() {
        backend.pairResult = { throw FingerprintMismatch(FP, "f".repeat(64)) }
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint()
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
        assertEquals(PairMessage.Res(R.string.pair_error_expired), ui.error)
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
        assertEquals(PairMessage.LocalNetwork, blocked.state.value.error)
        blocked.localNetworkGranted()
        assertNull("the notice is over once access is granted", blocked.state.value.error)
    }

    @Test fun qrParseErrorIsAFixedMessage() {
        vm.onQrScanned("fkit://pair?h=x")
        assertEquals(PairMessage.Res(R.string.pair_error_not_code), ui.error)
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

    @Test fun fingerprintLinesHoldFourGroupsEach() {
        val lines = fingerprintLines(FP)
        assertEquals(4, lines.size)
        assertEquals("0123 4567 89ab cdef", lines[0])
        assertEquals(FP, lines.joinToString(" ").replace(" ", ""))
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

    @Test fun discoveredServerThatDoesNotAnswerStaysOnTheFirstScreenAndSaysWhy() {
        backend.probeResult = { throw IOException("refused") }
        vm.connectDiscovered("kit.local", 8443)
        assertEquals(Step.Choose, ui.step)
        assertEquals(PairMessage.Res(R.string.common_hub_unreachable), ui.error)
        assertFalse(ui.busy)
    }

    @Test fun backFromTheCheckOfAFoundHubReturnsToTheFirstScreen() {
        vm.connectDiscovered("kit.local", 8443)
        assertEquals(Step.Confirm, ui.step)
        vm.back()
        assertEquals(PairUi(), ui)
    }

    @Test fun backFromTheCodeOfAFoundHubReturnsToTheFirstScreenToo() {
        settings.skip = true
        vm.connectDiscovered("kit.local", 8443)
        assertEquals(Step.Code, ui.step)
        vm.back()
        assertEquals(PairUi(), ui)
    }

    @Test fun startManualCanBePrefilled() {
        vm.startManual("kit.local", 8443)
        assertEquals(Step.Address, ui.step)
        assertEquals("kit.local", ui.host)
        assertEquals(8443, ui.port)
    }

    @Test fun backFromTheFingerprintCheckKeepsTheAddress() {
        vm.submitAddress("10.0.0.2", "8443")
        assertEquals(Step.Confirm, ui.step)
        vm.back()
        assertEquals(Step.Address, ui.step)
        assertEquals("10.0.0.2", ui.host)
        assertEquals(8443, ui.port)
        assertNull(ui.fingerprint)
    }

    @Test fun backFromTheCodeKeepsTheAddressAndForgetsTheCheck() {
        vm.submitAddress("10.0.0.2", "8443")
        vm.confirmFingerprint()
        assertEquals(Step.Code, ui.step)
        vm.back()
        assertEquals(Step.Address, ui.step)
        assertEquals("10.0.0.2", ui.host)
        vm.submitAddress("10.0.0.2", "8443")
        assertEquals("the check is made again", Step.Confirm, ui.step)
    }

    @Test fun backFromTheAddressGoesToTheFirstScreen() {
        vm.startManual("kit.local", 8443)
        vm.back()
        assertEquals(PairUi(), ui)
    }

    @Test fun backFromAMismatchDuringPairingStartsOver() {
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint()
        backend.pairResult = { throw FingerprintMismatch(FP, "f".repeat(64)) }
        vm.submitCode("123456")
        assertEquals(MismatchSource.MANUAL, ui.mismatch?.source)
        vm.back()
        assertEquals(PairUi(), ui)
    }

    @Test fun showMismatchFromElsewhereShowsBothFingerprintsAndPairAgainClearsIt() {
        vm.showMismatch("old", "new")
        assertEquals(Mismatch("old", "new", MismatchSource.STORED), ui.mismatch)
        assertEquals(Step.Choose, ui.step)
        vm.pairAgain()
        assertNull(ui.mismatch)
    }
}
