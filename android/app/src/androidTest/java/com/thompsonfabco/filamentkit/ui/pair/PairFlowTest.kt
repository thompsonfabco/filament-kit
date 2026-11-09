package com.thompsonfabco.filamentkit.ui.pair

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.thompsonfabco.filamentkit.data.ServerConfig
import com.thompsonfabco.filamentkit.data.SettingsStore
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.ServerInfo
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

private const val FP = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

@RunWith(AndroidJUnit4::class)
class PairFlowTest {
    @get:Rule val rule = createComposeRule()

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
            ServerInfo("Workshop server", "1", 1)
        override suspend fun claim(host: String, port: Int, fingerprint: String, token: String) = Unit
    }

    @Test fun aChangedCertificateOffersTrustBesidePairAgain() {
        val vm = PairViewModel(Store(), Backend(), CoroutineScope(Dispatchers.Main.immediate))
        vm.showMismatch(FP, "f".repeat(64))
        val trusted = mutableListOf<Mismatch>()
        var canTrust by mutableStateOf(true)
        rule.setContent {
            MaterialTheme {
                PairScreen(vm, emptyList(), onPaired = {}, canTrust = { canTrust }, onTrust = { trusted += it })
            }
        }

        rule.onNodeWithText(groupFingerprint("f".repeat(64))).assertIsDisplayed()
        rule.onNodeWithText(groupFingerprint(FP)).assertDoesNotExist()
        rule.onNodeWithText("Pair again").assertIsDisplayed()
        rule.onNodeWithText("Trust the new certificate").performClick()
        assertEquals(listOf(Mismatch(FP, "f".repeat(64))), trusted)

        // Nothing paired to keep: only Pair again.
        canTrust = false
        rule.onNodeWithText("Trust the new certificate").assertDoesNotExist()
        rule.onNodeWithText("Pair again").performClick()
        assertEquals(null, vm.state.value.mismatch)
    }

    @Test fun manualFlowShowsFingerprintFirstThenCodeThenPairs() {
        val store = Store()
        val backend = Backend()
        val vm = PairViewModel(store, backend, CoroutineScope(Dispatchers.Main.immediate))
        var paired = false
        rule.setContent {
            MaterialTheme { PairScreen(vm, emptyList(), onPaired = { paired = true }) }
        }

        rule.onNodeWithText("Enter address").performClick()
        rule.onNodeWithText("Host name or IP address").performTextInput("10.0.0.2")
        rule.onNodeWithText("Connect").performClick()

        // Fingerprint is on screen, in 4-character groups, and no code has been sent.
        rule.waitUntil(5_000) { vm.state.value.step == Step.Confirm }
        rule.onNodeWithText(groupFingerprint(FP)).assertIsDisplayed()
        assertTrue(backend.codes.isEmpty())

        rule.onNodeWithText("It matches").performClick()
        rule.onNodeWithText("6-digit code").performTextInput("000000")
        rule.onNodeWithText("Pair").performClick()
        rule.waitUntil(5_000) { vm.state.value.error != null }
        rule.onNodeWithText("That code is wrong or has expired").assertIsDisplayed()
        assertFalse(paired)

        rule.onNodeWithText("6-digit code").performTextClearance()
        rule.onNodeWithText("6-digit code").performTextInput("123456")
        rule.onNodeWithText("Pair").performClick()
        rule.waitUntil(5_000) { paired }
        assertEquals(FP, store.saved?.fingerprint)
        assertEquals(listOf("10.0.0.2"), store.saved?.endpoints)
        assertEquals(listOf("000000", "123456"), backend.codes)
    }

    @Test fun withTheCheckSkippedTheAddressGoesStraightToTheCode() {
        val store = Store().apply { skip = true }
        val backend = Backend().apply { wrongOnce = false }
        val vm = PairViewModel(store, backend, CoroutineScope(Dispatchers.Main.immediate))
        var paired = false
        rule.setContent {
            MaterialTheme { PairScreen(vm, emptyList(), onPaired = { paired = true }) }
        }

        rule.onNodeWithText("Enter address").performClick()
        rule.onNodeWithText("Host name or IP address").performTextInput("10.0.0.2")
        rule.onNodeWithText("Connect").performClick()

        rule.waitUntil(5_000) { vm.state.value.step == Step.Code }
        rule.onNodeWithText("It matches").assertDoesNotExist()
        rule.onNodeWithText("6-digit code").performTextInput("123456")
        rule.onNodeWithText("Pair").performClick()
        rule.waitUntil(5_000) { paired }
        assertEquals(FP, store.saved?.fingerprint)
    }
}
