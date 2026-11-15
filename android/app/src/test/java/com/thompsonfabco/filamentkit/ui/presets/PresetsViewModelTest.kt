package com.thompsonfabco.filamentkit.ui.presets

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.BuildAttempt
import com.thompsonfabco.filamentkit.net.BuildInfo
import com.thompsonfabco.filamentkit.net.BuildRequested
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.net.ProfileLine
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.net.UncoveredFilament
import com.thompsonfabco.filamentkit.ui.profile.SaveFailure
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PresetsViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val api = FakePresets()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)

    @After fun tearDown() = Dispatchers.resetMain()

    // ---- loading --------------------------------------------------------------------------------------------------

    @Test fun loadsTheStatusTheLinesAndTheFilamentsWithoutALine() = runTest(dispatcher) {
        val vm = PresetsViewModel(api)
        assertNull("loading until the Hub answers", vm.state.value.lines)
        assertNull(vm.state.value.uncovered)
        advanceUntilIdle()
        val s = vm.state.value
        assertTrue(s.statusLoaded)
        assertEquals(24, s.status?.presets)
        assertEquals(listOf("example--polyterra", "example--silk"), s.lines?.map { it.lineId })
        assertEquals(listOf(7, 9), s.uncovered?.map { it.id })
        assertEquals("Example Filaments PolyTerra Neon", s.card(7).name)
        assertEquals("Example Filaments Matte", s.card(9).name)
    }

    @Test fun anUnreadStatusIsNotAvailableButTheRestStillLoads() = runTest(dispatcher) {
        api.statusFailure = ApiError(500, "bad_response", "x")
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        assertTrue(vm.state.value.statusLoaded)
        assertNull(vm.state.value.status)
        assertEquals(2, vm.state.value.lines?.size)
    }

    @Test fun aFailedLinesLoadLeavesAnEmptyListWithItsFailureAndTryAgainReloads() = runTest(dispatcher) {
        api.linesFailure = ApiError(0, "offline", "socket")
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        assertEquals(emptyList<ProfileLine>(), vm.state.value.lines)
        assertEquals(SaveFailure.Unreachable, vm.state.value.linesFail?.kind)

        api.linesFailure = null
        vm.loadLines()
        assertNull("loading again", vm.state.value.lines)
        advanceUntilIdle()
        assertEquals(2, vm.state.value.lines?.size)
        assertNull(vm.state.value.linesFail)
    }

    @Test fun theListIsPagedAtFifty() = runTest(dispatcher) {
        api.lines = List(120) { ProfileLine(lineId = "l$it", vendor = "Example", product = "P$it", material = "PLA") }
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        assertEquals(50, vm.state.value.shown)
        assertEquals(120, vm.state.value.lines?.size)
        vm.showMore()
        assertEquals(100, vm.state.value.shown)
    }

    // ---- add to a line --------------------------------------------------------------------------------------------

    @Test fun addingAFilamentToTheBrandsFirstLineSendsItsIdAndTheCardLeaves() = runTest(dispatcher) {
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.addToLine(vm.state.value.uncovered!!.first())
        assertEquals(CardBusy.Adding, vm.state.value.card(7).busy)
        advanceUntilIdle()
        assertEquals(listOf("Example Filaments PolyTerra" to 7), api.added)
        assertEquals(listOf(9), vm.state.value.uncovered?.map { it.id })
        assertEquals(Done(created = false, name = "Example Filaments PolyTerra"), vm.state.value.done)
        assertEquals("the lines are read again", 2, api.linesCalls)
        vm.doneShown()
        assertNull(vm.state.value.done)
    }

    @Test fun theChosenLineIsTheOneSent() = runTest(dispatcher) {
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.chooseLine(7, "Example Filaments Silk")
        vm.addToLine(vm.state.value.uncovered!!.first())
        advanceUntilIdle()
        assertEquals(listOf("Example Filaments Silk" to 7), api.added)
    }

    @Test fun aRefusalOfAddNamesTheFieldAndKeepsTheCard() = runTest(dispatcher) {
        // the Hub's real 400 shape: error, message and the field it refused
        api.failure = ApiError(400, "bad_request", "filament 7 is already in a line", JsonObject(mapOf("field" to JsonPrimitive("ids"))))
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.addToLine(vm.state.value.uncovered!!.first())
        advanceUntilIdle()
        val card = vm.state.value.card(7)
        assertNull(card.busy)
        assertEquals(Fail(SaveFailure.Message, "filament 7 is already in a line", "ids"), card.fail)
        assertEquals(listOf(7, 9), vm.state.value.uncovered?.map { it.id })
        assertNull(vm.state.value.done)
    }

    @Test fun aSecondTapWhileAddingSendsNothingMore() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        api.gate = gate
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val f = vm.state.value.uncovered!!.first()
        vm.addToLine(f)
        advanceUntilIdle()
        vm.addToLine(f)
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(1, api.added.size)
    }

    // ---- a new line -----------------------------------------------------------------------------------------------

    @Test fun openingTheNewLineFormReadsTheParentsAndPicksTheGenericOne() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Bambu PLA Basic", "Generic PLA"), synced = true)
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.toggleNewLine(vm.state.value.uncovered!!.first())
        advanceUntilIdle()
        val card = vm.state.value.card(7)
        assertTrue(card.newLineOpen)
        assertEquals("Generic PLA", card.template)
        assertEquals(listOf("PLA"), api.parentCalls)
    }

    @Test fun aNewLineIsCreatedWithTheNameAndTheTemplateOfItsCard() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Bambu PLA Basic", "Generic PLA"), synced = true)
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val f = vm.state.value.uncovered!!.first()
        vm.toggleNewLine(f)
        advanceUntilIdle()
        vm.setName(7, "  Example Filaments Neon  ")
        vm.chooseTemplate(7, "Bambu PLA Basic")
        vm.createLine(f)
        assertEquals(CardBusy.Creating, vm.state.value.card(7).busy)
        advanceUntilIdle()
        assertEquals(listOf(listOf("Example Filaments Neon", "Example Filaments", "7", "Bambu PLA Basic")), api.created)
        assertEquals(Done(created = true, name = "Example Filaments Neon"), vm.state.value.done)
        assertEquals(listOf(9), vm.state.value.uncovered?.map { it.id })
    }

    @Test fun aLineCannotBeStartedWithoutATemplateOrAName() = runTest(dispatcher) {
        // Slicer Sync has reported no parents: the template stays empty
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val f = vm.state.value.uncovered!!.first()
        vm.toggleNewLine(f)
        advanceUntilIdle()
        assertNull(vm.state.value.card(7).template)
        vm.createLine(f)
        advanceUntilIdle()
        assertTrue(api.created.isEmpty())

        api.parentCalls.clear()
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        val g = vm.state.value.uncovered!!.last()
        vm.toggleNewLine(g)
        advanceUntilIdle()
        vm.setName(9, "   ")
        vm.createLine(g)
        advanceUntilIdle()
        assertTrue(api.created.isEmpty())
    }

    @Test fun aRefusedNewLineKeepsTheFormAndNamesTheField() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        api.failure = ApiError(400, "bad_request", "a line named Example Filaments PolyTerra exists", JsonObject(mapOf("field" to JsonPrimitive("name"))))
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val f = vm.state.value.uncovered!!.first()
        vm.toggleNewLine(f)
        advanceUntilIdle()
        vm.createLine(f)
        advanceUntilIdle()
        val card = vm.state.value.card(7)
        assertEquals("name", card.fail?.field)
        assertTrue(card.newLineOpen)
        assertNull(card.busy)
        vm.setName(7, "Example Filaments Neon")
        assertNull("typing clears the refusal", vm.state.value.card(7).fail)
    }

    @Test fun theSuggestedNameDropsTheLastWordOfTheFilament() {
        val f = UncoveredFilament(1, "Overture", "TPU Blue", "TPU")
        assertEquals("Overture TPU", PresetsViewModel.suggestedName(f))
        assertEquals("Overture Blue", PresetsViewModel.suggestedName(f.copy(name = "Blue")))
    }

    // ---- build ----------------------------------------------------------------------------------------------------

    @Test fun buildNowAsksOnceAndReadsTheStatusAgain() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        api.gate = gate
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val before = api.statusCalls
        vm.build()
        vm.build()
        assertTrue(vm.state.value.building)
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(1, api.builds)
        assertFalse(vm.state.value.building)
        assertEquals(BuildNote.Asked, vm.state.value.buildNote)
        assertEquals(before + 1, api.statusCalls)
    }

    @Test fun aRefusedBuildShowsTheHubsWords() = runTest(dispatcher) {
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        api.failure = ApiError(409, "busy", "A build is already running.")
        vm.build()
        advanceUntilIdle()
        assertEquals(BuildNote.Failed(Fail(SaveFailure.Message, "A build is already running.")), vm.state.value.buildNote)
        assertFalse(vm.state.value.building)
    }

    @Test fun anUnpairedPhoneAndAChangedCertificateAreTheHubNoticesNotMessages() {
        assertEquals(SaveFailure.NotPaired, failOf(ApiError(401, "unauthorized", "no")).kind)
        assertEquals(SaveFailure.CertificateChanged, failOf(FingerprintMismatch("a", "b")).kind)
        assertEquals(SaveFailure.Unknown, failOf(IllegalStateException()).kind)
    }

    // ---- change parent --------------------------------------------------------------------------------------------

    @Test fun reparentingALineSavesThePickedParentAndTheRowSaysSo() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Bambu PLA Basic", "Generic PLA"), synced = true)
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val line = vm.state.value.lines!!.first()
        vm.editParent(line)
        assertEquals("Example Filaments PolyTerra", vm.state.value.edit?.line)
        advanceUntilIdle()
        assertEquals(listOf("Bambu PLA Basic", "Generic PLA"), vm.state.value.edit?.parents?.parents)

        vm.findParent("basic")
        assertEquals(listOf("Bambu PLA Basic"), vm.state.value.edit?.matches)
        vm.pickParent("Bambu PLA Basic")
        vm.saveParent()
        advanceUntilIdle()

        assertEquals(listOf("example--polyterra" to "Bambu PLA Basic"), api.reparented)
        val saved = vm.state.value.lines!!.first()
        assertEquals("Bambu PLA Basic", saved.bambuParent)
        assertEquals("the count of presets stays", 4, saved.presets)
        assertEquals("example--polyterra", vm.state.value.savedFor)
        assertNull(vm.state.value.edit)
    }

    @Test fun aRefusedParentStaysInTheSheetAsTheHubWordsIt() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.editParent(vm.state.value.lines!!.last())
        advanceUntilIdle()
        api.failure = ApiError(400, "unknown_parent", "Bambu Studio has no such preset")
        vm.pickParent("Generic PLA")
        vm.saveParent()
        advanceUntilIdle()
        val edit = vm.state.value.edit
        assertNotNull("the sheet stays open", edit)
        assertEquals(Fail(SaveFailure.Message, "Bambu Studio has no such preset"), edit?.fail)
        assertFalse(edit!!.saving)
        assertNull(vm.state.value.lines?.last()?.bambuParent)
        assertNull(vm.state.value.savedFor)
    }

    @Test fun noParentsReportedYetOffersNothingToSave() = runTest(dispatcher) {
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.editParent(vm.state.value.lines!!.first())
        advanceUntilIdle()
        assertFalse(vm.state.value.edit!!.parents!!.synced)
        vm.saveParent()
        advanceUntilIdle()
        assertTrue("nothing is sent before Slicer Sync has reported parents", api.reparented.isEmpty())
    }

    @Test fun theSheetCannotBeClosedWhileSaving() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        val gate = CompletableDeferred<Unit>()
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.editParent(vm.state.value.lines!!.last())
        advanceUntilIdle()
        api.gate = gate
        vm.pickParent("Generic PLA")
        vm.saveParent()
        vm.closeParent()
        assertNotNull(vm.state.value.edit)
        gate.complete(Unit)
        advanceUntilIdle()
        assertNull(vm.state.value.edit)
    }
}
