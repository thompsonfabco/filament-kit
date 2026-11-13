package com.thompsonfabco.filamentkit.ui.pair

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.data.SettingsStore
import com.thompsonfabco.filamentkit.nav.PairAddressRoute
import com.thompsonfabco.filamentkit.nav.PairCertificateRoute
import com.thompsonfabco.filamentkit.nav.PairCodeRoute
import com.thompsonfabco.filamentkit.nav.PairFingerprintRoute
import com.thompsonfabco.filamentkit.nav.PairRoute
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.ServerInfo
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

private const val FP = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

/** The pairing steps on a device: each screen of 05-android-app 4 shown as its destination would show it. */
@RunWith(AndroidJUnit4::class)
class PairFlowTest {
    @get:Rule val rule = createComposeRule()

    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private fun text(id: Int, vararg args: Any) = context.getString(id, *args)

    private class Store : SettingsStore {
        @Volatile var saved: ServerConfig? = null
        override suspend fun save(config: ServerConfig) { saved = config }
        override suspend fun clear() { saved = null }
        var skip = false
        override suspend fun skipsFingerprintCheck() = skip
    }

    private class Backend : PairingBackend {
        val codes = mutableListOf<String>()
        var wrongOnce = true
        override suspend fun probe(host: String, port: Int) = FP
        override suspend fun pair(host: String, port: Int, fingerprint: String, code: String): String {
            codes += code
            if (wrongOnce) {
                wrongOnce = false
                throw ApiError(401, "unauthorized", "That code is wrong or has expired")
            }
            return "tok"
        }
        override suspend fun info(host: String, port: Int, fingerprint: String, token: String?) =
            ServerInfo("Workshop Hub", "1", 1)
        override suspend fun claim(host: String, port: Int, fingerprint: String, token: String) = Unit
    }

    /** What the navigation host does: the screen of the destination the state is at. */
    @Composable
    private fun Steps(vm: PairViewModel, onPaired: () -> Unit = {}, canTrust: Boolean = false, onTrust: (Mismatch) -> Unit = {}) {
        val ui by vm.state.collectAsState()
        SpoolwardenTheme(Look.Console, Appearance.Light) {
            when (val route = pairRouteFor(ui, accessGranted = true)) {
                PairRoute -> PairStartScreen(
                    ui, emptyList(), "0.5.2", onScan = {}, onPick = {}, onEnterAddress = { vm.startManual() },
                )
                PairAddressRoute -> PairAddressScreen(ui, vm::submitAddress, vm::back)
                PairFingerprintRoute -> PairFingerprintScreen(ui, vm::confirmFingerprint, vm::rejectFingerprint, vm::back)
                PairCodeRoute -> PairCodeScreen(ui, vm::submitCode, vm::back)
                is PairCertificateRoute -> ui.mismatch?.let {
                    PairCertificateScreen(it, canTrust, { onTrust(it) }, vm::pairAgain, vm::back)
                }
                else -> error("no screen for $route")
            }
            LaunchedEffect(ui.step) { if (ui.step == Step.Done) onPaired() }
        }
    }

    @Test fun aChangedCertificateOffersTrustBesidePairAgain() {
        val vm = PairViewModel(Store(), Backend(), CoroutineScope(Dispatchers.Main.immediate))
        vm.showMismatch(FP, "f".repeat(64))
        val trusted = mutableListOf<Mismatch>()
        rule.setContent { Steps(vm, canTrust = true, onTrust = { trusted += it }) }

        rule.onNodeWithText(fingerprintLines("f".repeat(64)).joinToString("\n")).assertIsDisplayed()
        rule.onNodeWithText(fingerprintLines(FP).joinToString("\n")).assertIsDisplayed()
        rule.onNodeWithText(text(R.string.common_pair_again)).assertIsDisplayed()
        rule.onNodeWithText(text(R.string.pair_cert_stored_trust)).performClick()
        assertEquals(listOf(Mismatch(FP, "f".repeat(64))), trusted)

        rule.onNodeWithText(text(R.string.common_pair_again)).performClick()
        assertEquals(null, vm.state.value.mismatch)
    }

    @Test fun manualFlowShowsFingerprintFirstThenCodeThenPairs() {
        val store = Store()
        val backend = Backend()
        val vm = PairViewModel(store, backend, CoroutineScope(Dispatchers.Main.immediate))
        var paired = false
        rule.setContent { Steps(vm, onPaired = { paired = true }) }

        rule.onNodeWithText(text(R.string.pair_start_enter_address)).performClick()
        rule.onNodeWithText(text(R.string.pair_address_label)).performTextInput("10.0.0.2")
        rule.onNodeWithText(text(R.string.common_connect)).performClick()

        // The fingerprint is on screen, four groups to a line, and no code has been sent.
        rule.waitUntil(5_000) { vm.state.value.step == Step.Confirm }
        rule.onNodeWithText(fingerprintLines(FP).joinToString("\n")).assertIsDisplayed()
        assertTrue(backend.codes.isEmpty())

        rule.onNodeWithText(text(R.string.pair_fingerprint_matches)).performClick()
        rule.onNodeWithText(text(R.string.pair_code_label)).performTextInput("000000")
        rule.onNodeWithText(text(R.string.pair_code_pair)).performClick()
        rule.waitUntil(5_000) { vm.state.value.error != null }
        rule.onNodeWithText(text(R.string.pair_error_refused)).assertIsDisplayed()
        assertFalse(paired)

        assertEquals(listOf("000000"), backend.codes)
    }

    @Test fun withTheCheckSkippedTheAddressGoesStraightToTheCode() {
        val store = Store().apply { skip = true }
        val backend = Backend().apply { wrongOnce = false }
        val vm = PairViewModel(store, backend, CoroutineScope(Dispatchers.Main.immediate))
        var paired = false
        rule.setContent { Steps(vm, onPaired = { paired = true }) }

        rule.onNodeWithText(text(R.string.pair_start_enter_address)).performClick()
        rule.onNodeWithText(text(R.string.pair_address_label)).performTextInput("10.0.0.2")
        rule.onNodeWithText(text(R.string.common_connect)).performClick()

        rule.waitUntil(5_000) { vm.state.value.step == Step.Code }
        rule.onNodeWithText(text(R.string.pair_fingerprint_matches)).assertDoesNotExist()
        rule.onNodeWithText(text(R.string.pair_code_label)).performTextInput("123456")
        rule.onNodeWithText(text(R.string.pair_code_pair)).performClick()
        rule.waitUntil(5_000) { paired }
        assertEquals(FP, store.saved?.fingerprint)
    }
}
