package com.thompsonfabco.filamentkit.ui.spool

import com.thompsonfabco.filamentkit.net.ApiError
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class TagViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val backend = FakeSpoolBackend()

    @Before fun setUp() {
        Dispatchers.setMain(dispatcher)
        SpoolCache.clear()
    }

    @After fun tearDown() = Dispatchers.resetMain()

    // ---- the tag screen ----

    @Test fun aLinkedTagFindsItsSpool() = runTest(dispatcher) {
        backend.tagAnswer = spoolJson(214, tag = "04A1B2")
        val gate = CompletableDeferred<Unit>()
        backend.tagGate = gate
        val vm = TagViewModel("04A1B2", backend)
        runCurrent()
        assertEquals(TagUi.Looking, vm.state.value)
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(214, (vm.state.value as TagUi.Linked).spool.id)
        assertEquals("the title and the next screen know the spool", 214, SpoolCache.get(214)!!.id)
    }

    @Test fun aTagLinkedToNothingSaysSo() = runTest(dispatcher) {
        val vm = TagViewModel("04A1B2", backend)
        advanceUntilIdle()
        assertEquals(TagUi.NotLinked, vm.state.value)
    }

    @Test fun aFailedLookupSaysWhyAndCanBeTriedAgain() = runTest(dispatcher) {
        backend.failure = "tag" to ApiError(0, "offline", "gone")
        val vm = TagViewModel("04A1B2", backend)
        advanceUntilIdle()
        assertEquals(TagUi.Failed(HubFailure.Unreachable), vm.state.value)
        backend.tagAnswer = spoolJson(214)
        vm.lookUp()
        advanceUntilIdle()
        assertTrue(vm.state.value is TagUi.Linked)
        assertEquals(listOf("tag:04A1B2", "tag:04A1B2"), backend.calls)
    }

    @Test fun aRefusedPairingIsTheHubNotice() = runTest(dispatcher) {
        backend.failure = "tag" to ApiError(401, "unauthorized", "no")
        val vm = TagViewModel("04A1B2", backend)
        advanceUntilIdle()
        assertEquals(TagUi.Failed(HubFailure.NotPaired), vm.state.value)
    }

    // ---- link: find ----

    @Test fun findSearchesSealedSpoolsAfterAPauseOnceTwoLettersAreTyped() = runTest(dispatcher) {
        backend.spools = listOf(spoolJson(212, sealed = true))
        val vm = LinkFindViewModel(backend)
        vm.setQuery("p")
        advanceTimeBy(1_000)
        assertTrue(backend.calls.isEmpty())
        vm.setQuery("poly")
        advanceTimeBy(299)
        assertTrue(backend.calls.isEmpty())
        advanceTimeBy(2)
        runCurrent()
        assertEquals(listOf("search:poly:true"), backend.calls)
        assertEquals(listOf(212), vm.state.value.results.map { it.id })
        assertTrue(vm.state.value.searched)
        assertEquals(SpoolState.Sealed, vm.state.value.results.single().state)
    }

    @Test fun clearingTheBoxClearsTheRows() = runTest(dispatcher) {
        backend.spools = listOf(spoolJson(212, sealed = true))
        val vm = LinkFindViewModel(backend)
        vm.setQuery("poly")
        vm.search()
        advanceUntilIdle()
        vm.setQuery("")
        assertTrue(vm.state.value.results.isEmpty())
        assertFalse(vm.state.value.searched)
    }

    @Test fun aWeightThatIsNotGramsAboveZeroTurnsTheRowsOff() {
        assertTrue(LinkFindUi(weight = "0").weightInvalid)
        assertTrue(LinkFindUi(weight = "-3").weightInvalid)
        assertTrue(LinkFindUi(weight = "heavy").weightInvalid)
        assertFalse(LinkFindUi(weight = "").weightInvalid)
        assertFalse(LinkFindUi(weight = "  ").weightInvalid)
        assertFalse(LinkFindUi(weight = "1240").weightInvalid)
    }

    @Test fun aFailedSearchKeepsTheRowsOfTheLastAnswer() = runTest(dispatcher) {
        backend.spools = listOf(spoolJson(212, sealed = true))
        val vm = LinkFindViewModel(backend)
        vm.setQuery("poly")
        vm.search()
        advanceUntilIdle()
        backend.failure = "search" to ApiError(0, "offline", "gone")
        vm.search()
        advanceUntilIdle()
        assertEquals(HubFailure.Unreachable, vm.state.value.failure)
        assertEquals(1, vm.state.value.results.size)
    }

    // ---- link: preview ----

    @Test fun thePreviewAsksForADryRunWithTheWeightOnEntry() = runTest(dispatcher) {
        val vm = LinkPreviewViewModel("04A1B2", 212, 1240.0, backend)
        assertTrue(vm.state.value.checking)
        advanceUntilIdle()
        assertFalse(vm.state.value.checking)
        assertEquals(212, vm.state.value.spool!!.id)
        assertEquals(listOf("link:212:04A1B2:force=false:dry=true:gross=1240.0"), backend.calls)
    }

    @Test fun linkingWritesTheLinkAndGivesTheSpoolScreenItsResult() = runTest(dispatcher) {
        val vm = LinkPreviewViewModel("04A1B2", 212, null, backend)
        advanceUntilIdle()
        vm.link()
        assertTrue(vm.state.value.linking)
        vm.link()
        advanceUntilIdle()
        assertEquals(SpoolResult.TagLinked, vm.state.value.finished)
        assertEquals("the spool as the Hub has it now is cached", 212, SpoolCache.get(212)!!.id)
        assertEquals("one write, not two", 1, backend.calls.count { it.endsWith("dry=false:gross=null") })
    }

    @Test fun aTagInUseAsksBeforeItIsMoved() = runTest(dispatcher) {
        backend.failure = "link" to ApiError(
            409, "tag_conflict", "tag is already linked",
            buildJsonObject {
                put("reason", JsonPrimitive("tag_on_other_spool"))
                put("other_spool", spoolJson(90, tag = "04A1B2"))
            },
        )
        val vm = LinkPreviewViewModel("04A1B2", 212, null, backend)
        advanceUntilIdle()
        assertEquals(ConflictReason.TagOnOtherSpool, vm.state.value.conflict)
        assertEquals(90, vm.state.value.other!!.id)
        assertNull(vm.state.value.failure)
        vm.moveHere()
        advanceUntilIdle()
        assertEquals(SpoolResult.TagMoved, vm.state.value.finished)
        assertTrue(backend.calls.last().contains("force=true:dry=false"))
    }

    @Test fun aSpoolThatHasAnotherTagIsItsOwnConflict() = runTest(dispatcher) {
        backend.failure = "link" to ApiError(
            409, "tag_conflict", "spool has a tag", buildJsonObject { put("reason", JsonPrimitive("spool_has_other_tag")) },
        )
        val vm = LinkPreviewViewModel("04A1B2", 212, null, backend)
        advanceUntilIdle()
        assertEquals(ConflictReason.SpoolHasOtherTag, vm.state.value.conflict)
        assertNull(vm.state.value.other)
    }

    @Test fun aFailedLinkStaysAndCanBeTriedAgain() = runTest(dispatcher) {
        val vm = LinkPreviewViewModel("04A1B2", 212, null, backend)
        advanceUntilIdle()
        backend.failure = "link" to ApiError(503, "spoolman_unreachable", "Spoolman is not reachable")
        vm.link()
        advanceUntilIdle()
        assertEquals(HubFailure.SpoolmanDown, vm.state.value.failure)
        assertNull(vm.state.value.finished)
        assertFalse(vm.state.value.linking)
        vm.link()
        advanceUntilIdle()
        assertEquals(SpoolResult.TagLinked, vm.state.value.finished)
        assertNull(vm.state.value.failure)
    }
}
