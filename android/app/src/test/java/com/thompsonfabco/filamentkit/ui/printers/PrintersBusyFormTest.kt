package com.thompsonfabco.filamentkit.ui.printers

import android.os.Build
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.isDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeDown
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.CommandResult
import com.thompsonfabco.filamentkit.net.KlipperFound
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.PrinterDetail
import com.thompsonfabco.filamentkit.net.UnloadResult
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.CompletableDeferred
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** An add that is running cannot be abandoned (05-android-app 2.5, rule 2): the form on a phone, held busy. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h800dp")
class PrintersBusyFormTest {
    @get:Rule val rule = createComposeRule()

    private val unset = Printer(id = "DEF456", name = "Spare P1S", model = "P1S", serial = "DEF456", ip = "192.0.2.41")
    private val wrongCode = Printer(
        id = "GHI789", name = "Study A1 mini", model = "A1 mini", serial = "GHI789", configured = true, state = "wrong_code",
    )
    private val gate = CompletableDeferred<Unit>()

    private inner class Backend : PrinterBackend {
        override suspend fun printers() = listOf(unset, wrongCode)
        override suspend fun addPrinter(serial: String, accessCode: String, name: String?): Printer {
            gate.await()
            return unset
        }
        override suspend fun addKlipperPrinter(host: String, port: Int, name: String?): Printer = error("not used")
        override suspend fun scanKlipper(subnet: String?) = emptyList<KlipperFound>()
        override suspend fun setApiKey(id: String, key: String) = Unit
        override suspend fun printer(id: String): PrinterDetail = throw ApiError(404, "not_found", "x")
        override suspend fun command(id: String, action: String): CommandResult = error("not used")
        override suspend fun unload(id: String, label: String, dryRun: Boolean): UnloadResult = error("not used")
    }

    private fun shown(vm: PrintersViewModel) = rule.setContent {
        SpoolwardenTheme(Look.Console, Appearance.Light) { PrintersScreen(vm, onOpen = {}, onPairAgain = {}) }
    }

    @Test fun aBusyAddHasCancelOffTheReasonAndSurvivesASwipe() {
        val vm = PrintersViewModel(Backend())
        shown(vm)
        rule.waitForIdle()
        vm.openAdd(unset)
        rule.waitForIdle()
        vm.submitAdd("12345678", "")
        rule.waitForIdle()
        rule.onNodeWithText("Cancel").assertIsNotEnabled()
        rule.onNodeWithText("The Hub is adding the printer. Wait for its answer.").assertExists()
        rule.onNodeWithText("Add Bambu Lab P1S").performTouchInput { swipeDown() }
        rule.waitForIdle()
        assertNotNull("the form is still open", vm.state.value.dialog)
        assertTrue("and still shown", rule.onNodeWithText("The Hub is adding the printer. Wait for its answer.").isDisplayed())
        gate.completeExceptionally(ApiError(400, "bad_request", "Refused by the Hub"))
        rule.waitForIdle()
        assertTrue("the later refusal is shown", rule.onNodeWithText("Refused by the Hub").isDisplayed())
    }

    @Test fun theReKeyHasItsOwnWaitText() {
        val vm = PrintersViewModel(Backend())
        shown(vm)
        rule.waitForIdle()
        vm.openAdd(wrongCode)
        rule.waitForIdle()
        vm.submitAdd("12345678", "")
        rule.waitForIdle()
        rule.onNodeWithText("Cancel").assertIsNotEnabled()
        rule.onNodeWithText("The Hub is saving the Access Code. Wait for its answer.").assertExists()
    }
}
