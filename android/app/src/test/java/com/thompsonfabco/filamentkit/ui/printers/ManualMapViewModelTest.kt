package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.ManualChoice
import com.thompsonfabco.filamentkit.net.ManualMapState
import com.thompsonfabco.filamentkit.net.ManualOfferAnswer
import com.thompsonfabco.filamentkit.net.ManualPosition
import com.thompsonfabco.filamentkit.net.ManualSeen
import com.thompsonfabco.filamentkit.net.ManualStep
import com.thompsonfabco.filamentkit.net.ManualStepPosition
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ManualMapViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)

    @After fun tearDown() = Dispatchers.resetMain()

    private val a2 = JsonObject(mapOf("ams_id" to JsonPrimitive(0), "tray_id" to JsonPrimitive(1)))
    private val positions = listOf("A1", "A2", "A3").map { ManualPosition(it, it) }

    private fun state(
        step: String? = "A1",
        seen: ManualSeen? = null,
        ask: String? = null,
        open: Boolean = true,
        dual: Boolean = false,
        reports: Boolean = true,
        session: String = "s1",
    ) = ManualMapState(
        session = session, open = open, dualNozzle = dual, reportsLoads = reports,
        step = step?.let { ManualStep(ManualStepPosition(it, it), "Load $it to the nozzle, then wait.", seen, ask) },
        positions = positions, summary = "0 of 3 positions confirmed.",
        choices = if (reports) emptyList() else listOf(ManualChoice(a2, "A2")),
    )

    private val settled = ManualSeen(a2, "A2", settled = true)

    private class Fake : ManualMapBackend {
        var startResult: ManualMapState? = null
        var startError: Exception? = null
        var current: ManualMapState? = null
        var stateError: Exception? = null
        var answer: ManualMapState? = null
        var answerError: Exception? = null
        val confirms = mutableListOf<List<Any?>>()
        val skips = mutableListOf<Pair<String, String>>()
        val stops = mutableListOf<String>()
        var stateCalls = 0

        override suspend fun start(id: String): ManualMapState {
            startError?.let { throw it }
            return startResult!!
        }
        override suspend fun state(id: String): ManualMapState {
            stateCalls++
            stateError?.let { throw it }
            return current!!
        }
        override suspend fun confirm(id: String, session: String, position: String, reported: JsonObject,
                                     nozzle: String?, byHand: Boolean): ManualMapState {
            confirms += listOf(session, position, reported, nozzle, byHand)
            answerError?.let { throw it }
            return answer!!
        }
        override suspend fun skip(id: String, session: String, position: String): ManualMapState {
            skips += session to position
            return answer!!
        }
        override suspend fun stop(id: String, session: String): ManualMapState {
            stops += session
            return answer!!
        }
        override suspend fun offer(id: String, share: Boolean) = ManualOfferAnswer(share, if (share) "How" else "Noted")
    }

    private val backend = Fake()

    private val made = mutableListOf<ManualMapViewModel>()

    private fun vm() = ManualMapViewModel(backend, "P1", pollMs = 1000).also { made += it }

    /** The poll loop runs until the screen goes away; runTest would otherwise wait on it for ever. */
    private fun stopAll() = made.forEach { it.stop() }

    @Test fun startOpensTheSessionAndPollsWhileOpen() = runTest(dispatcher) {
        backend.startResult = state()
        backend.current = state(seen = ManualSeen(a2, "A2", settled = false))
        val vm = vm()
        vm.start(); runCurrent()
        assertEquals("s1", vm.state.value.map!!.session)
        advanceTimeBy(1001); runCurrent()
        assertEquals(1, backend.stateCalls)
        assertFalse(vm.state.value.canAnswer)       // not settled yet
        vm.stop()
        advanceTimeBy(5000); runCurrent()
        assertEquals("no poll while the screen is away", 1, backend.stateCalls)
        stopAll()
    }

    @Test fun aRefusedStartShowsTheServersSentenceAndCanBeRetried() = runTest(dispatcher) {
        backend.startError = ApiError(409, "map_running", "Slot mapping is running on this printer.")
        val vm = vm()
        vm.start(); runCurrent()
        assertNull(vm.state.value.map)
        assertEquals(Problem.HubSaid("Slot mapping is running on this printer."), vm.state.value.problem)
        backend.startError = null
        backend.startResult = state()
        vm.retry(); runCurrent()
        assertEquals("s1", vm.state.value.map!!.session)
        stopAll()
    }

    @Test fun yesConfirmsTheAskedPositionWithTheReportedLoad() = runTest(dispatcher) {
        backend.startResult = state(seen = settled, ask = "Is that the A1 you loaded?")
        backend.answer = state(step = "A2")
        val vm = vm()
        vm.start(); runCurrent()
        assertTrue(vm.state.value.canAnswer)
        vm.yes(); runCurrent()
        assertEquals(listOf("s1", "A1", a2, null, false), backend.confirms.single())
        assertEquals("A2", vm.state.value.map!!.step!!.position.id)
        stopAll()
    }

    @Test fun noILoadedSendsThePositionTheOwnerNames() = runTest(dispatcher) {
        backend.startResult = state(seen = settled, ask = "Is that the A1 you loaded?")
        backend.answer = state(step = "A2")
        val vm = vm()
        vm.start(); runCurrent()
        vm.openOther()
        assertTrue(vm.state.value.pickingOther)
        vm.loadedOther("A3"); runCurrent()
        assertFalse(vm.state.value.pickingOther)
        assertEquals(listOf("s1", "A3", a2, null, false), backend.confirms.single())
        stopAll()
    }

    @Test fun aDualNozzlePrinterAsksTheNozzleFirst() = runTest(dispatcher) {
        backend.startResult = state(seen = settled, ask = "Is that the A1 you loaded?", dual = true)
        backend.answer = state(step = "A2", dual = true)
        val vm = vm()
        vm.start(); runCurrent()
        assertFalse(vm.state.value.canAnswer)
        vm.yes(); runCurrent()
        assertTrue(backend.confirms.isEmpty())
        vm.chooseNozzle("left")
        vm.yes(); runCurrent()
        assertEquals("left", backend.confirms.single()[3])
        assertNull("the next position asks again", vm.state.value.nozzle)
        stopAll()
    }

    @Test fun aNozzleThePrinterReportsIsSentWithoutAsking() = runTest(dispatcher) {
        backend.startResult = state(seen = settled.copy(nozzle = "right", nozzleReported = true), ask = "?", dual = true)
        backend.answer = state(step = "A2", dual = true)
        val vm = vm()
        vm.start(); runCurrent()
        assertTrue(vm.state.value.canAnswer)
        vm.yes(); runCurrent()
        assertEquals("right", backend.confirms.single()[3])
        stopAll()
    }

    @Test fun aPrinterWithoutLoadReportsGetsTheByHandList() = runTest(dispatcher) {
        backend.startResult = state(reports = false)
        backend.answer = state(step = "A2", reports = false)
        val vm = vm()
        vm.start(); runCurrent()
        assertTrue(vm.state.value.byHand)
        vm.pickByHand(0); runCurrent()
        assertEquals(listOf("s1", "A1", a2, null, true), backend.confirms.single())
        stopAll()
    }

    @Test fun skipAndStopCarryTheSession() = runTest(dispatcher) {
        backend.startResult = state()
        backend.answer = state(step = "A2")
        val vm = vm()
        vm.start(); runCurrent()
        vm.skip(); runCurrent()
        assertEquals("s1" to "A1", backend.skips.single())
        backend.answer = state(step = null, open = false)
        vm.askStop()
        assertTrue(vm.state.value.confirmStop)
        vm.confirmStop(); runCurrent()
        assertEquals(listOf("s1"), backend.stops)
        assertFalse(vm.state.value.open)
        stopAll()
    }

    @Test fun anotherDeviceAnsweringFirstRefreshesQuietly() = runTest(dispatcher) {
        backend.startResult = state(seen = settled, ask = "?")
        backend.answerError = ApiError(409, "stale", "This manual mapping moved on or was restarted: show it again.")
        backend.current = state(step = "A2")
        val vm = vm()
        vm.start(); runCurrent()
        vm.yes(); runCurrent()
        assertNull(vm.state.value.problem)
        assertEquals("A2", vm.state.value.map!!.step!!.position.id)
        stopAll()
    }

    @Test fun aKlipperRefusalShowsItsSentence() = runTest(dispatcher) {
        backend.startResult = state(seen = settled, ask = "?")
        backend.answerError = ApiError(409, "taken", "C3 is already confirmed as C1 in this mapping.")
        val vm = vm()
        vm.start(); runCurrent()
        vm.yes(); runCurrent()
        assertEquals(Problem.HubSaid("C3 is already confirmed as C1 in this mapping."), vm.state.value.problem)
        stopAll()
    }

    @Test fun aSessionClosedElsewhereShowsAsEnded() = runTest(dispatcher) {
        backend.startResult = state()
        backend.stateError = ApiError(404, "none", "No manual mapping was started for this printer.")
        val vm = vm()
        vm.start(); runCurrent()
        advanceTimeBy(1001); runCurrent()
        assertFalse(vm.state.value.open)
        assertNull(vm.state.value.map!!.step)
        stopAll()
    }

    @Test fun aPollBlipIsShownMildlyAndClearsItself() = runTest(dispatcher) {
        backend.startResult = state()
        backend.stateError = ApiError(0, "offline", "x")
        val vm = vm()
        vm.start(); runCurrent()
        advanceTimeBy(1001); runCurrent()
        assertTrue(vm.state.value.lost)
        backend.stateError = null
        backend.current = state()
        advanceTimeBy(3000); runCurrent()
        assertFalse(vm.state.value.lost)
        stopAll()
    }

    @Test fun anUnpairedPhoneOrChangedCertificateStops() = runTest(dispatcher) {
        backend.startError = ApiError(401, "unauthorized", "x")
        val vm = vm()
        vm.start(); runCurrent()
        assertTrue(vm.state.value.unauthorized)
        val vm2 = vm()
        backend.startError = FingerprintMismatch("aa", "bb")
        vm2.start(); runCurrent()
        assertEquals("aa" to "bb", vm2.state.value.mismatch)
        stopAll()
    }

    @Test fun theShareQuestionIsAnsweredOnce() = runTest(dispatcher) {
        backend.startResult = state(step = null, open = false).copy(offerReport = true)
        val vm = vm()
        vm.start(); runCurrent()
        vm.offer(false); runCurrent()
        assertEquals("Noted", vm.state.value.note)
        assertFalse(vm.state.value.map!!.offerReport)
        stopAll()
    }

    @Test fun aHubNoticeClearsAfterTheNextSuccessfulRequest() = runTest(dispatcher) {
        backend.startResult = state()
        backend.stateError = ApiError(401, "unauthorized", "x")
        val vm = vm()
        vm.start(); runCurrent()
        advanceTimeBy(1001); runCurrent()
        assertTrue(vm.state.value.unauthorized)
        backend.stateError = null
        backend.current = state()
        vm.stop()
        vm.start(); runCurrent()
        advanceTimeBy(3000); runCurrent()
        assertFalse(vm.state.value.unauthorized)
        stopAll()
    }
}
