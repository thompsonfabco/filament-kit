package com.thompsonfabco.filamentkit.ui.add

import android.Manifest
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.net.AddResult
import com.thompsonfabco.filamentkit.net.ReadResult
import java.io.File
import java.util.Collections
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AddFlowTest {
    @get:Rule val compose = createComposeRule()
    @get:Rule val camera: GrantPermissionRule = GrantPermissionRule.grant(Manifest.permission.CAMERA)

    private lateinit var dir: File
    private val taps = MutableSharedFlow<String>(extraBufferCapacity = 8)
    private val api = FakeApi()

    @Before fun setUp() {
        dir = File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir, "add-flow-test").apply {
            deleteRecursively()
            mkdirs()
        }
    }

    @After fun tearDown() {
        dir.deleteRecursively()
    }

    private fun field(label: String) = compose.onNode(hasText(label) and hasSetTextAction())

    private fun waitForText(text: String) =
        compose.waitUntil(10_000) { compose.onAllNodes(hasText(text, substring = true)).fetchSemanticsNodes().isNotEmpty() }

    @Test fun photosTagWeightReadEditPreviewAdd() {
        val store = DraftStore(dir)
        val vm = AddViewModel(api, store, taps = taps, prepare = { it })
        var done = false
        compose.setContent { AddSpoolsScreen(vm, onClose = {}, onDone = { done = true }, onPairAgain = {}) }

        compose.runOnIdle { vm.addPhoto(byteArrayOf(1, 2, 3)) }
        waitForText("Photos: 1 of 8")
        taps.tryEmit("4:77:90:e")
        waitForText("Tag 4:77:90:e")
        field("Weight on the scale, with spool (g)").performScrollTo().performTextInput("812.5")
        compose.onNodeWithText("Read labels").performScrollTo().performClick()

        waitForText("Claude asks")
        compose.onNodeWithText("• Is the colour grey or silver?").assertExists()
        compose.onNodeWithText("SUNLU PLA+ Grey").assertExists()
        field("Empty spool (g) (estimated)").assertExists()
        field("Name").performScrollTo().performTextClearance()
        field("Name").performTextInput("PLA+ Silver")
        compose.onNodeWithText("Preview").performScrollTo().performClick()

        waitForText("would link tag 4:77:90:e")
        compose.onNodeWithText("Add 1 spool").performScrollTo().performClick()
        waitForText("New spool: #41")

        assertEquals(listOf(true, false), api.adds.map { it.second })
        val sent = api.adds.last().first[0].jsonObject
        assertEquals("PLA+ Silver", sent["name"]!!.jsonPrimitive.content)
        assertEquals(812.5, sent["gross"]!!.jsonPrimitive.double, 0.0)
        assertEquals("keep me", sent["future_field"]!!.jsonPrimitive.content)
        assertEquals("4:77:90:e", api.reads.single())
        assertTrue(store.list().isEmpty())

        compose.onNodeWithText("Done").performClick()
        compose.runOnIdle { assertTrue(done) }
    }

    private class FakeApi : IntakeApi {
        val reads: MutableList<String?> = Collections.synchronizedList(mutableListOf())
        val adds: MutableList<Pair<JsonArray, Boolean>> = Collections.synchronizedList(mutableListOf())

        override suspend fun read(photos: List<ByteArray>, hint: String, tag: String?): ReadResult {
            reads += tag
            val item = Json.parseToJsonElement(
                """{"photos":[1],"existing_filament_id":null,"vendor":"SUNLU","name":"PLA+ Grey","material":"PLA",
                   "color_hex":"808080","net":1000,"tare":213,"density":1.24,"count":1,"nozzle":215,"bed":60,
                   "nozzle_range":"200-230","bed_range":"50-70","lot":null,"note":"","estimates":["tare"],
                   "sealed":false,"sealed_reason":"bare spool","match":"new filament","future_field":"keep me"}""",
            ) as JsonObject
            return ReadResult(JsonArray(listOf(item)), listOf("Is the colour grey or silver?"), tag, null, "r1")
        }

        override suspend fun retry(readId: String): ReadResult = error("not used")

        override suspend fun add(items: JsonArray, dryRun: Boolean, tag: String?): AddResult {
            adds += items to dryRun
            return if (dryRun) {
                AddResult(emptyList(), listOf("SUNLU PLA+ Silver (new filament): 1 spool(s)", "would link tag $tag"), true)
            } else {
                AddResult(listOf(41), listOf("linked tag $tag to spool 41"), false)
            }
        }

        override suspend fun locations(): List<String> = listOf("Shelf A")
    }
}
