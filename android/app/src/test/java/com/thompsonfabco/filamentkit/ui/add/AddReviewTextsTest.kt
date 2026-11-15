package com.thompsonfabco.filamentkit.ui.add

import android.os.Build
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.net.ReadResult
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The words of the review screen's text checks, as the person reads them. */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.S], qualifiers = "w411dp-h800dp")
class AddReviewTextsTest {
    @get:Rule val rule = createComposeRule()
    private val dispatcher = UnconfinedTestDispatcher()
    private lateinit var dir: File

    @Before fun setUp() {
        Dispatchers.setMain(dispatcher)
        dir = kotlin.io.path.createTempDirectory("drafts").toFile()
    }

    @After fun tearDown() {
        Dispatchers.resetMain()
        dir.deleteRecursively()
    }

    private fun item(parent: String) = buildJsonObject {
        put("photos", JsonArray(emptyList()))
        put("existing_filament_id", JsonNull)
        put("vendor", "SUNLU")
        put("name", "PLA+ Grey")
        put("material", "PLA")
        put("color_hex", "808080")
        put("net", 1000)
        put("tare", 213)
        put("density", 1.24)
        put("count", 1)
        put("sealed", false)
        put("bambu_parent", parent)
    }

    @Test fun aParentNameWithAnAtSignIsToldToLeaveOutTheAtAndThePrinterPart() = runTest(dispatcher) {
        val api = FakeIntakeApi()
        api.readResults += ReadResult(JsonArray(listOf(item("Generic PLA @BBL H2D"))), emptyList(), null, null, "r1")
        val vm = AddViewModel(
            api = api, store = DraftStore(dir), taps = MutableSharedFlow(extraBufferCapacity = 8), draftId = null, initialTag = null,
            prepare = { it }, io = dispatcher, clock = { 1_000_000L },
        )
        vm.addPhoto(byteArrayOf(1, 2, 3))
        vm.read()
        rule.setContent {
            SpoolwardenTheme(Look.Console, Appearance.Light) {
                ReviewScreen(vm.state.value, vm, onPairAgain = {}, onAddByHand = {}, onAddCatalogLine = { _, _, _ -> })
            }
        }
        rule.waitForIdle()
        // the hint is one text with the line that follows it
        rule.onNodeWithText("Leave out the @ and the printer part.", substring = true).assertExists()
    }
}
