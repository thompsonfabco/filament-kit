package com.thompsonfabco.filamentkit.ui.add

import com.thompsonfabco.filamentkit.drafts.DraftStore
import com.thompsonfabco.filamentkit.net.AddResult
import com.thompsonfabco.filamentkit.net.ReadResult
import java.io.File
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The adds the app holds (05-android-app 6): every add is a draft, and its work outlives the screen. */
@OptIn(ExperimentalCoroutinesApi::class)
class AddFlowsTest {
    private val dispatcher = StandardTestDispatcher()
    private lateinit var dir: File
    private lateinit var store: DraftStore
    private val api = FakeIntakeApi()

    @Before fun setUp() {
        Dispatchers.setMain(dispatcher)
        dir = kotlin.io.path.createTempDirectory("flows").toFile()
        store = DraftStore(dir)
    }

    @After fun tearDown() {
        appJob.cancel()
        Dispatchers.resetMain()
        dir.deleteRecursively()
    }

    private val appJob = kotlinx.coroutines.SupervisorJob()
    private val appScope = kotlinx.coroutines.CoroutineScope(dispatcher + appJob)

    private fun flows() = AddFlows(appScope, store, api, io = dispatcher, prepare = { it })

    private fun item() = buildJsonObject {
        put("vendor", "SUNLU"); put("name", "PLA+ Grey"); put("material", "PLA"); put("net", 1000); put("tare", 213)
        put("count", 1); put("sealed", true)
    }

    @Test fun everyAddIsADraftFromTheStartOnBothPaths() = runTest(dispatcher) {
        val flows = flows()
        val photo = flows.start(manual = false)
        val hand = flows.start(manual = true, tag = "04A1")
        advanceUntilIdle()
        assertFalse(store.get(photo)!!.manual)
        assertTrue(store.get(hand)!!.manual)
        assertEquals("a tapped tag is in the draft from the start", "04A1", store.get(hand)!!.tag)
        assertEquals(AddStep.Photos, flows.stepOf(photo))
        assertEquals(AddStep.Check, flows.stepOf(hand))
    }

    @Test fun aHandAddsTypingSurvivesTheAppBeingStopped() = runTest(dispatcher) {
        val first = flows()
        val id = first.start(manual = true)
        val vm = first.get(id)
        advanceUntilIdle()
        vm.newFilament()
        vm.setText(0, "vendor", "SUNLU")
        vm.setText(0, "name", "PETG Grey")
        advanceUntilIdle()
        assertTrue(store.get(id)!!.hasContent)

        // a new process: nothing open, the draft is read back
        val second = flows()
        val back = second.get(id)
        advanceUntilIdle()
        assertTrue(back.state.value.manual)
        assertEquals(Stage.Review, back.state.value.stage)
        assertEquals(1, back.state.value.items.size)
        assertEquals("PETG Grey", (back.state.value.items[0]["name"] as kotlinx.serialization.json.JsonPrimitive).content)
    }

    @Test fun aReadFinishesWhileNoScreenShowsItAndSaysSo() = runTest(dispatcher) {
        val flows = flows()
        val id = flows.start(manual = false)
        val vm = flows.get(id)
        advanceUntilIdle()
        api.readResults += ReadResult(JsonArray(listOf(item())), emptyList(), null, null, "r1")
        vm.addPhoto(byteArrayOf(1))
        advanceUntilIdle()
        api.gate = CompletableDeferred()
        var told: String? = null
        appScope.launch { told = flows.readFinished.first() }
        vm.read() // the screen is gone: only the app holds the flow
        advanceUntilIdle()
        assertNull(told)
        api.gate!!.complete(Unit)
        advanceUntilIdle()
        assertEquals(id, told)
        assertEquals(Stage.Review, vm.state.value.stage)
        assertEquals("kept in the draft", 1, store.get(id)!!.editedItems!!.size)
    }

    @Test fun anAddThatEndsAwayFromTheScreenSaysWhetherItWorked() = runTest(dispatcher) {
        val flows = flows()
        val id = flows.start(manual = true)
        val vm = flows.get(id)
        advanceUntilIdle()
        vm.newFilament()
        vm.setText(0, "vendor", "SUNLU"); vm.setText(0, "name", "PETG"); vm.setText(0, "material", "PETG")
        vm.setNumber(0, "net", 1000.0); vm.setNumber(0, "tare", 213.0)
        vm.preview()
        advanceUntilIdle()
        var told: Pair<String, Boolean>? = null
        appScope.launch { told = flows.addFinished.first() }
        api.addResults += AddResult(listOf(7), listOf("ok"), false)
        vm.confirm()
        advanceUntilIdle()
        assertEquals(id to true, told)
        assertNull("a real add deletes the draft", store.get(id))
    }

    @Test fun leavingAnAddWithNothingInItDropsTheDraftAndAnythingElseStays() = runTest(dispatcher) {
        val flows = flows()
        val empty = flows.start(manual = true)
        flows.leave(empty)
        assertNull(store.get(empty))
        val photo = flows.start(manual = false)
        flows.get(photo).addPhoto(byteArrayOf(1))
        advanceUntilIdle()
        flows.leave(photo)
        assertNotNull("a photo is worth keeping", store.get(photo))
        val typed = flows.start(manual = true)
        flows.get(typed).newFilament()
        advanceUntilIdle()
        flows.leave(typed)
        assertNotNull("a typed spool is worth keeping", store.get(typed))
    }

    @Test fun addMoreStartsANewDraftOnTheSamePath() = runTest(dispatcher) {
        val flows = flows()
        val id = flows.start(manual = true)
        flows.get(id)
        val next = flows.again(id)
        assertTrue(next != id)
        assertTrue(store.get(next)!!.manual)
    }

    @Test fun aDraftThatIsGoneIsNotThere() = runTest(dispatcher) {
        val flows = flows()
        assertFalse(flows.exists("nope"))
        val id = flows.start(manual = false)
        assertTrue(flows.exists(id))
        flows.release(id)
        store.delete(id)
        assertFalse(flows.exists(id))
    }

    @Test fun aWritingFlowKeepsTheCardsAddAway() = runTest(dispatcher) {
        val flows = flows()
        val id = flows.start(manual = false)
        assertEquals(AddReplace.Replace, flows.replaceRule(id))
    }
}
