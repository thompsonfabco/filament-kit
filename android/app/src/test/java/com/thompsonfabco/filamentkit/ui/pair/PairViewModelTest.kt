package com.thompsonfabco.filamentkit.ui.pair

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
    override suspend fun save(config: ServerConfig) { saved = config }
    override suspend fun clear() { saved = null }
}

private class FakeBackend : PairingBackend {
    val calls = mutableListOf<String>()
    var probeResult: () -> String = { FP }
    var pairResult: (String) -> String = { "token-1" }
    var infoResult: () -> ServerInfo = { ServerInfo("Workshop server", "1", 1) }

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
        return infoResult()
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
        vm.confirmFingerprint()
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
        backend.infoResult = { throw ApiError(0, "offline", "x") }
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
        vm.confirmFingerprint()
        vm.submitCode("123456")
        assertEquals("Unexpected response from the server", ui.error)
        assertFalse(ui.busy)
    }

    @Test fun certificateChangedDuringPairingShowsBothFingerprints() {
        backend.pairResult = { throw FingerprintMismatch(FP, "f".repeat(64)) }
        vm.submitAddress("10.0.0.2", "")
        vm.confirmFingerprint()
        vm.submitCode("123456")
        assertEquals(Mismatch(FP, "f".repeat(64)), ui.mismatch)
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
        assertEquals(listOf("info"), backend.calls)
        assertEquals(Step.Done, ui.step)
    }

    @Test fun qrThatIsNotOursShowsError() {
        vm.onQrScanned("https://example.com")
        assertEquals(Step.Choose, ui.step)
        assertNotNull(ui.error)
        assertNull(settings.saved)
    }

    @Test fun qrVerifyFailureForgetsTheSavedConfig() {
        backend.infoResult = { throw ApiError(0, "offline", "Cannot reach") }
        vm.onQrScanned(qr())
        assertNull(settings.saved)
        assertEquals(Step.Choose, ui.step)
        assertNotNull(ui.error)
    }

    @Test fun qrVerifyMismatchShowsBothFingerprints() {
        backend.infoResult = { throw FingerprintMismatch(FP, "e".repeat(64)) }
        vm.onQrScanned(qr())
        assertEquals(Mismatch(FP, "e".repeat(64)), ui.mismatch)
        assertNull(settings.saved)
    }

    @Test fun fingerprintGroupsOfFour() {
        assertEquals("0123 4567 89ab", groupFingerprint("0123456789ab"))
    }

    @Test fun discoveredServerPrefillsManualFlow() {
        vm.startManual("kit.local", 8443)
        assertEquals(Step.Address, ui.step)
        assertEquals("kit.local", ui.host)
        assertEquals(8443, ui.port)
    }
}
