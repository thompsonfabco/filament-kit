package com.thompsonfabco.filamentkit.ui.home

import com.thompsonfabco.filamentkit.net.AcceptedUpdates
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.PresetUpdate
import com.thompsonfabco.filamentkit.net.PresetUpdates
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PresetUpdatesTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    private val a = PresetUpdate("A", "bambu_studio", "l1", listOf("nozzle_temperature", "bed_temperature"))
    private val b = PresetUpdate("B", "orca", null, emptyList())
    private val done = PresetUpdate("C", "bambu_studio", "l2", listOf("k"), accepted = true)

    private class Fake(var list: PresetUpdates) : PresetUpdatesBackend {
        var lists = 0
        val accepts = mutableListOf<Pair<String, List<String>>>()
        var restores = 0
        var error: Exception? = null
        override suspend fun list(): PresetUpdates { lists++; return list }
        override suspend fun accept(stamp: String, names: List<String>): AcceptedUpdates {
            accepts += stamp to names; error?.let { throw it }
            return AcceptedUpdates(stamp, names.map { JsonObject(emptyMap()) })
        }
        override suspend fun restoreDeleted() { restores++; error?.let { throw it } }
    }

    private val fake = Fake(PresetUpdates("s1", 3, 1, listOf(a, b, done), listOf("Mine")))

    private fun loaded() = PresetUpdatesViewModel(fake).also { it.load(); dispatcher.scheduler.runCurrent() }

    @Test fun acceptSendsExactlyTheWaitingNamesShownWithTheirStamp() = runTest(dispatcher) {
        val vm = loaded()
        vm.accept()
        runCurrent()
        assertEquals(listOf("s1" to listOf("A", "B")), fake.accepts)
        assertEquals(PresetUpdateTexts.accepted(2), vm.state.value.message)
        assertFalse(vm.state.value.messageIsError)
        assertEquals(2, fake.lists) // the list is loaded again after the accept
        assertFalse(vm.state.value.busy)
    }

    @Test fun aNewerBuildRefusesTheAcceptAndTheListIsLoadedAgain() = runTest(dispatcher) {
        val vm = loaded()
        fake.error = ApiError(409, "updates_changed", "the updates changed since this list: load them again")
        fake.list = PresetUpdates("s2", 1, 0, listOf(b))
        vm.accept()
        runCurrent()
        assertEquals(PresetUpdateTexts.CHANGED, vm.state.value.message)
        assertTrue(vm.state.value.messageIsError)
        assertEquals("s2", vm.state.value.list!!.stamp)
        assertEquals(listOf("B"), vm.state.value.list!!.waiting.map { it.name })
    }

    @Test fun nothingWaitingSendsNothing() = runTest(dispatcher) {
        fake.list = PresetUpdates("s1", 1, 1, listOf(done))
        val vm = loaded()
        vm.accept()
        runCurrent()
        assertTrue(fake.accepts.isEmpty())
    }

    @Test fun restoreAsksOnceAndSaysWhatHappens() = runTest(dispatcher) {
        val vm = loaded()
        vm.restoreDeleted()
        vm.restoreDeleted()
        runCurrent()
        assertEquals(1, fake.restores)
        assertEquals(PresetUpdateTexts.RESTORED, vm.state.value.message)
    }

    @Test fun anUnpairedPhoneIsToldAndRestoreIsOff() = runTest(dispatcher) {
        val vm = loaded()
        fake.error = ApiError(401, "unauthorized", "token not accepted")
        vm.restoreDeleted()
        runCurrent()
        assertTrue(vm.state.value.unauthorized)
        assertTrue(vm.state.value.messageIsError)
    }

    @Test fun rowsNameTheSlicerAndWhatChanges() {
        assertEquals("A (Bambu Studio): nozzle_temperature, bed_temperature", PresetUpdateTexts.row(a))
        assertEquals("B (OrcaSlicer): changed values", PresetUpdateTexts.row(b))
        assertEquals("Accept 1 update", PresetUpdateTexts.accept(1))
        assertEquals("The presets module is turned off on this server.",
            PresetUpdateTexts.error(ApiError(409, "module_off", "x")))
    }
}
