package com.thompsonfabco.filamentkit.ui.pair

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasContentDescription
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

    @Test fun manualFlowShowsFingerprintFirstThenCodeThenPairs() {
        val store = Store()
        val backend = Backend()
        val vm = PairViewModel(store, backend, CoroutineScope(Dispatchers.Main.immediate), pickGroups = { listOf(2, 9) })
        var paired = false
        rule.setContent {
            MaterialTheme { PairScreen(vm, emptyList(), onPaired = { paired = true }) }
        }

        rule.onNodeWithText("Enter address").performClick()
        rule.onNodeWithText("Host name or IP address").performTextInput("10.0.0.2")
        rule.onNodeWithText("Connect").performClick()

        // Two groups are blank and must be typed from the server; no code has been sent.
        rule.waitUntil(5_000) { vm.state.value.step == Step.Confirm }
        assertTrue(backend.codes.isEmpty())
        val groups = FP.chunked(4)
        rule.onNodeWithText("Continue").assertIsNotEnabled()
        rule.onNode(hasContentDescription("Missing group 3 of 16")).performTextInput(groups[2])
        rule.onNode(hasContentDescription("Missing group 10 of 16")).performTextInput("0000")
        rule.onNodeWithText("Continue").performClick()
        rule.onNodeWithText(PairTexts.FINGERPRINT_WRONG).assertIsDisplayed()
        assertEquals(Step.Confirm, vm.state.value.step)

        rule.onNode(hasContentDescription("Missing group 10 of 16")).performTextClearance()
        rule.onNode(hasContentDescription("Missing group 10 of 16")).performTextInput(groups[9].uppercase())
        rule.onNodeWithText("Continue").performClick()
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
}
