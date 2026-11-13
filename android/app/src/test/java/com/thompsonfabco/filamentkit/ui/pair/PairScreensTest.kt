package com.thompsonfabco.filamentkit.ui.pair

import android.os.Build
import androidx.compose.runtime.Composable
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.DiscoveredServer
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/** What the pairing screens show and do (05-android-app 4.1 to 4.9); the texts are the catalogue's own. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h8000dp")
class PairScreensTest {
    @get:Rule val rule = createComposeRule()

    private val fp = "0123456789abcdef".repeat(4)
    private val context = RuntimeEnvironment.getApplication()
    private fun text(id: Int, vararg args: Any) = context.getString(id, *args)

    private fun show(content: @Composable () -> Unit) = rule.setContent {
        SpoolwardenTheme(Look.Console, Appearance.Light) { content() }
    }

    @Test fun theBannerShowsOnlyWhenThePhoneWasUnpaired() {
        var banner = false
        val hub = DiscoveredServer("Workshop Hub", "192.0.2.10", 8710)
        show { PairStartScreen(PairUi(), listOf(hub), "0.5.2", {}, {}, {}, unpairedBanner = banner) }
        rule.onNodeWithText(text(R.string.pair_banner_unpaired)).assertDoesNotExist()
        rule.onNodeWithText("Workshop Hub").assertExists()
        rule.onNodeWithText("192.0.2.10").assertExists()
        rule.onNodeWithText(text(R.string.pair_version, "0.5.2")).assertExists()
    }

    @Test fun theBannerSitsAtTheTopWhenAskedFor() {
        show { PairStartScreen(PairUi(), emptyList(), "0.5.2", {}, {}, {}, unpairedBanner = true) }
        rule.onNodeWithText(text(R.string.pair_banner_unpaired)).assertExists()
        rule.onNodeWithText(text(R.string.pair_start_found_looking)).assertExists()
    }

    @Test fun pickingAFoundHubAsksForIt() {
        val picked = mutableListOf<DiscoveredServer>()
        val hub = DiscoveredServer("Workshop Hub", "192.0.2.10", 8710)
        show { PairStartScreen(PairUi(), listOf(hub), "0.5.2", {}, { picked += it }, {}) }
        rule.onNodeWithText("Workshop Hub").performClick()
        assertEquals(listOf(hub), picked)
    }

    @Test fun whileConnectingTheScanButtonSaysSoAndNothingElseCanBePressed() {
        var pressed = 0
        val hub = DiscoveredServer("Workshop Hub", "192.0.2.10", 8710)
        show { PairStartScreen(PairUi(busy = true), listOf(hub), "0.5.2", { pressed++ }, { pressed++ }, { pressed++ }) }
        rule.onNodeWithText(text(R.string.common_connecting)).assertExists()
        rule.onNodeWithText("Workshop Hub").performClick()
        rule.onNodeWithText(text(R.string.pair_start_enter_address)).assertIsNotEnabled()
        assertEquals(0, pressed)
    }

    @Test fun theResultLineIsUnderTheScanButton() {
        show { PairStartScreen(PairUi(error = PairMessage.Res(R.string.pair_error_expired)), emptyList(), "0.5.2", {}, {}, {}) }
        rule.onNodeWithText(text(R.string.pair_error_expired)).assertExists()
    }

    @Test fun anAddressErrorSitsUnderItsField() {
        show {
            PairAddressScreen(
                PairUi(step = Step.Address, error = PairMessage.Res(R.string.pair_address_error_empty), errorField = PairField.Address),
                { _, _ -> }, {},
            )
        }
        rule.onNodeWithText(text(R.string.pair_address_error_empty)).assertExists()
        rule.onNodeWithText(text(R.string.pair_address_connect)).assertIsEnabled()
    }

    @Test fun theAddressFormSubmitsWhatWasTypedWithThePrefilledPort() {
        val sent = mutableListOf<Pair<String, String>>()
        show { PairAddressScreen(PairUi(step = Step.Address), { h, p -> sent += h to p }, {}) }
        rule.onNodeWithText(text(R.string.pair_address_label)).performTextInput("hub.example")
        rule.onNodeWithText(text(R.string.pair_address_connect)).performClick()
        assertEquals(listOf("hub.example" to "8710"), sent)
    }

    @Test fun theFingerprintIsShownFourGroupsToALine() {
        show { PairFingerprintScreen(PairUi(step = Step.Confirm, host = "hub.example", fingerprint = fp), {}, {}, {}) }
        rule.onNodeWithText(text(R.string.pair_fingerprint_text, "hub.example")).assertExists()
        rule.onNodeWithText(fingerprintLines(fp).joinToString("\n")).assertExists()
        assertEquals(4, fingerprintLines(fp).size)
    }

    @Test fun theTwoFingerprintButtonsDoWhatTheySay() {
        val log = mutableListOf<String>()
        show { PairFingerprintScreen(PairUi(step = Step.Confirm, fingerprint = fp), { log += "yes" }, { log += "no" }, {}) }
        rule.onNodeWithText(text(R.string.pair_fingerprint_matches)).performClick()
        rule.onNodeWithText(text(R.string.pair_fingerprint_differs)).performClick()
        assertEquals(listOf("yes", "no"), log)
    }

    @Test fun thePairButtonWaitsForSixDigitsAndSaysWhy() {
        val sent = mutableListOf<String>()
        show { PairCodeScreen(PairUi(step = Step.Code), { sent += it }, {}) }
        rule.onNodeWithText(text(R.string.pair_code_pair)).assertIsNotEnabled()
        rule.onNodeWithText(text(R.string.pair_code_error_length)).assertExists()
        rule.onNodeWithText(text(R.string.pair_code_label)).performTextInput("12345")
        rule.onNodeWithText(text(R.string.pair_code_pair)).assertIsNotEnabled()
        assertTrue("the fifth digit sends nothing", sent.isEmpty())
        rule.onNodeWithText(text(R.string.pair_code_label)).performTextInput("6")
        assertTrue("the sixth digit does not submit by itself", sent.isEmpty())
        rule.onNodeWithText(text(R.string.pair_code_pair)).assertIsEnabled().performClick()
        assertEquals(listOf("123456"), sent)
        rule.onNodeWithText(text(R.string.pair_code_error_length)).assertDoesNotExist()
    }

    @Test fun onlyDigitsAreTakenAndNoMoreThanSix() {
        show { PairCodeScreen(PairUi(step = Step.Code), {}, {}) }
        rule.onNodeWithText(text(R.string.pair_code_label)).performTextInput("1a2b3c4d5e6f7g8")
        rule.onNodeWithText(text(R.string.pair_code_pair)).assertIsEnabled()
        rule.onNodeWithText("123456").assertExists()
    }

    @Test fun whilePairingTheButtonSaysSo() {
        show { PairCodeScreen(PairUi(step = Step.Code, busy = true), {}, {}) }
        rule.onNodeWithText(text(R.string.pair_code_pairing)).assertExists()
    }

    @Test fun aSavedPairingOffersTrustBesidePairAgainWhenItCanBeKept() {
        val log = mutableListOf<String>()
        show {
            PairCertificateScreen(Mismatch(fp, "f".repeat(64), MismatchSource.STORED), true, { log += "trust" }, { log += "again" }, {})
        }
        rule.onNodeWithText(text(R.string.pair_cert_stored_paired_with)).assertExists()
        rule.onNodeWithText(text(R.string.pair_cert_stored_now_shows)).assertExists()
        rule.onNodeWithText(text(R.string.pair_cert_stored_hint)).assertExists()
        rule.onNodeWithText(fingerprintLines(fp).joinToString("\n")).assertExists()
        rule.onNodeWithText(fingerprintLines("f".repeat(64)).joinToString("\n")).assertExists()
        rule.onNodeWithText(text(R.string.pair_cert_stored_trust)).performClick()
        rule.onNodeWithText(text(R.string.common_pair_again)).performClick()
        assertEquals(listOf("trust", "again"), log)
    }

    @Test fun withNothingToKeepPairAgainIsTheOnlyButton() {
        show { PairCertificateScreen(Mismatch(fp, "f".repeat(64), MismatchSource.STORED), false, {}, {}, {}) }
        rule.onNodeWithText(text(R.string.pair_cert_stored_trust)).assertDoesNotExist()
        rule.onNodeWithText(text(R.string.common_pair_again)).assertExists()
    }

    @Test fun aScannedCodeThatNamesAnotherCertificateOffersStartAgainOnly() {
        show { PairCertificateScreen(Mismatch(fp, "f".repeat(64), MismatchSource.QR), true, {}, {}, {}) }
        rule.onNodeWithText(text(R.string.pair_cert_qr_expects)).assertExists()
        rule.onNodeWithText(text(R.string.pair_cert_qr_shows)).assertExists()
        rule.onNodeWithText(text(R.string.pair_cert_start_again)).assertExists()
        rule.onNodeWithText(text(R.string.pair_cert_stored_trust)).assertDoesNotExist()
    }

    @Test fun aCertificateThatChangedWhilePairingListsNoFingerprints() {
        show { PairCertificateScreen(Mismatch(fp, "f".repeat(64), MismatchSource.MANUAL), false, {}, {}, {}) }
        rule.onNodeWithText(text(R.string.pair_cert_manual_body)).assertExists()
        rule.onNodeWithText(fingerprintLines(fp).joinToString("\n")).assertDoesNotExist()
    }
}
