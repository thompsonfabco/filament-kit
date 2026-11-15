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
        assertEquals("the line's id, never its name", listOf("example--polyterra" to 7), api.added)
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
        assertEquals(listOf("example--silk" to 7), api.added)
    }

    @Test fun aLineThatTheHubsListLacksIsNotSentByName() = runTest(dispatcher) {
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.chooseLine(7, "Example Filaments Gone")
        vm.addToLine(vm.state.value.uncovered!!.first())
        advanceUntilIdle()
        assertTrue(api.added.isEmpty())
        assertEquals(SaveFailure.Unknown, vm.state.value.card(7).fail?.kind)
        assertNull(vm.state.value.card(7).busy)
    }

    @Test fun aRefusalWithoutAFieldIsKeptWithTheCardForTheNoticeLine() = runTest(dispatcher) {
        // the Hub's 400 today: `error` and `message` only
        api.failure = ApiError(400, "bad_request", "filament 7 is already in line Example Filaments PolyTerra")
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.addToLine(vm.state.value.uncovered!!.first())
        advanceUntilIdle()
        val card = vm.state.value.card(7)
        assertNull(card.busy)
        assertEquals(Fail(SaveFailure.Message, "filament 7 is already in line Example Filaments PolyTerra", null), card.fail)
        assertEquals(listOf(7, 9), vm.state.value.uncovered?.map { it.id })
    }

    @Test fun aRefusalOfAddThatNamesAFieldKeepsTheFieldAndTheCard() = runTest(dispatcher) {
        // a 400 that also carries the `field` it refused (the Hub may send it)
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

    @Test fun openingTheNewLineFormReadsTheOrcaParentsOfTheMaterialAndSendsTheChosenOne() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        api.orcaLists["PLA"] = listOf("Bambu PLA Basic @BBL X1C", "Generic PLA")
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val f = vm.state.value.uncovered!!.first()
        vm.toggleNewLine(f)
        assertNull("loading", vm.state.value.card(7).orcaParents)
        advanceUntilIdle()
        assertEquals(listOf("PLA"), api.orcaCalls)
        assertEquals(listOf("Bambu PLA Basic @BBL X1C", "Generic PLA"), vm.state.value.card(7).orcaParents)
        assertNull("optional: nothing is chosen", vm.state.value.card(7).orcaParent)
        vm.chooseOrcaParent(7, "Generic PLA")
        vm.createLine(f)
        advanceUntilIdle()
        assertEquals(listOf<String?>("Generic PLA"), api.createdOrca)
    }

    @Test fun withoutAChosenOrcaParentNothingIsSentForIt() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        api.orcaLists["PLA"] = listOf("Generic PLA")
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val f = vm.state.value.uncovered!!.first()
        vm.toggleNewLine(f)
        advanceUntilIdle()
        vm.chooseOrcaParent(7, "Generic PLA")
        vm.chooseOrcaParent(7, null)
        vm.createLine(f)
        advanceUntilIdle()
        assertEquals(listOf<String?>(null), api.createdOrca)
    }

    @Test fun anEmptyOrcaListMeansNoLibraryYetAndTheLineCanStillBeStarted() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val f = vm.state.value.uncovered!!.first()
        vm.toggleNewLine(f)
        advanceUntilIdle()
        assertEquals(emptyList<String>(), vm.state.value.card(7).orcaParents)
        assertNull(vm.state.value.card(7).fail)
        vm.createLine(f)
        advanceUntilIdle()
        assertEquals(1, api.created.size)
    }

    @Test fun theOrcaParentsAreReadOncePerCardEvenWhenTheFormIsReopened() = runTest(dispatcher) {
        api.orcaLists["PLA"] = listOf("Generic PLA")
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val f = vm.state.value.uncovered!!.first()
        vm.toggleNewLine(f)
        advanceUntilIdle()
        vm.toggleNewLine(f)
        vm.toggleNewLine(f)
        advanceUntilIdle()
        assertEquals(listOf("PLA"), api.orcaCalls)
    }

    @Test fun anUnpairedPhoneIsTheHubNoticeOnTheCardAndTheOrcaListIsEmpty() = runTest(dispatcher) {
        api.orcaFailure = ApiError(401, "unauthorized", "no token")
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.toggleNewLine(vm.state.value.uncovered!!.first())
        advanceUntilIdle()
        assertEquals(Fail(SaveFailure.NotPaired), vm.state.value.card(7).fail)
        assertEquals(emptyList<String>(), vm.state.value.card(7).orcaParents)
    }

    @Test fun aHubWithoutTheOrcaRouteIsTheEmptyListWithoutAFailure() = runTest(dispatcher) {
        api.orcaFailure = ApiError(404, "not_found", "no route")
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.toggleNewLine(vm.state.value.uncovered!!.first())
        advanceUntilIdle()
        assertEquals(emptyList<String>(), vm.state.value.card(7).orcaParents)
        assertNull(vm.state.value.card(7).fail)
    }

    @Test fun aRefusedOrcaParentNamesItsFieldAndTypingTheChoiceClearsIt() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        api.orcaLists["PLA"] = listOf("Generic PLA")
        api.failure = ApiError(400, "bad_request", "orca_parent is not an Orca Slicer preset", JsonObject(mapOf("field" to JsonPrimitive("orca_parent"))))
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val f = vm.state.value.uncovered!!.first()
        vm.toggleNewLine(f)
        advanceUntilIdle()
        vm.chooseOrcaParent(7, "Generic PLA")
        vm.createLine(f)
        advanceUntilIdle()
        assertEquals("orca_parent", vm.state.value.card(7).fail?.field)
        assertTrue(vm.state.value.card(7).newLineOpen)
        vm.chooseOrcaParent(7, null)
        assertNull(vm.state.value.card(7).fail)
    }

    @Test fun aLineNameIsStrippedAtBothEndsAsTheHubDoesAndInnerRunsStay() {
        fun line(vendor: String, product: String) = ProfileLine(lineId = "x", vendor = vendor, product = product, material = "PLA")
        assertEquals("Example Filaments PolyTerra", PresetsViewModel.lineName(line("Example Filaments", "PolyTerra")))
        // an empty product leaves the join's space at the end; the Hub strips it
        assertEquals("Example", PresetsViewModel.lineName(line("Example", "")))
        assertEquals("Silk", PresetsViewModel.lineName(line("", "Silk")))
        assertEquals("Example   Silk", PresetsViewModel.lineName(line(" Example ", " Silk ")))
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

    @Test fun aRefusedNewLineWithoutAFieldKeepsTheFormAndTheMessage() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        api.failure = ApiError(400, "bad_request", "a line named Example Filaments PolyTerra exists")
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val f = vm.state.value.uncovered!!.first()
        vm.toggleNewLine(f)
        advanceUntilIdle()
        vm.createLine(f)
        advanceUntilIdle()
        val card = vm.state.value.card(7)
        assertEquals(Fail(SaveFailure.Message, "a line named Example Filaments PolyTerra exists", null), card.fail)
        assertTrue(card.newLineOpen)
    }

    @Test fun aNewLineIsOfferedAtOnceOnTheOtherCardsOfItsBrand() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val f = vm.state.value.uncovered!!.first()
        vm.toggleNewLine(f)
        advanceUntilIdle()
        vm.setName(7, "Example Filaments Neon")
        vm.createLine(f)
        advanceUntilIdle()
        val other = vm.state.value.uncovered!!.single()
        assertEquals(9, other.id)
        assertEquals(listOf("Example Filaments Neon"), other.linesForVendor)
        // and the card adds to it by its id
        vm.addToLine(other)
        advanceUntilIdle()
        assertEquals(listOf("example-filaments-neon" to 9), api.added)
    }

    @Test fun aNewLineIsNotOfferedOnAnotherBrand() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Generic PLA"), synced = true)
        api.uncoveredList = api.uncoveredList.map { if (it.id == 9) it.copy(vendor = "Other Brand") else it }
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val f = vm.state.value.uncovered!!.first()
        vm.toggleNewLine(f)
        advanceUntilIdle()
        vm.createLine(f)
        advanceUntilIdle()
        assertEquals(emptyList<String>(), vm.state.value.uncovered!!.single().linesForVendor)
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
        assertEquals("the Hub's own summary", BuildNote.Asked("a build is requested"), vm.state.value.buildNote)
        assertEquals(before + 1, api.statusCalls)
    }

    @Test fun aBuildAnswerWithoutAnOutputKeepsNoSummary() = runTest(dispatcher) {
        api.buildOutput = "  "
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.build()
        advanceUntilIdle()
        assertEquals(BuildNote.Asked(""), vm.state.value.buildNote)
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

    @Test fun aHubWithoutTheBuildRouteIsRememberedUntilThePhonePairsAgain() = runTest(dispatcher) {
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.pairedWith(Any())
        api.failure = ApiError(404, "not_found", "Not Found")
        vm.build()
        advanceUntilIdle()
        assertTrue(vm.state.value.buildMissing)
        assertNull("no refusal notice besides the Hub-too-old line", vm.state.value.buildNote)
        vm.pairedWith(Any())
        assertFalse(vm.state.value.buildMissing)
    }

    @Test fun readingTheScreenAgainTriesTheBuildRouteAgain() = runTest(dispatcher) {
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        api.failure = ApiError(404, "not_found", "Not Found")
        vm.build()
        advanceUntilIdle()
        assertTrue(vm.state.value.buildMissing)
        vm.reload()
        assertFalse(vm.state.value.buildMissing)
    }

    @Test fun findAParentNarrowsTheTemplatesByEveryWordInAnyCase() {
        val list = listOf("Bambu PLA Basic", "Bambu PETG Basic", "Generic PLA")
        assertEquals(list, matchParents(list, ""))
        assertEquals(listOf("Bambu PLA Basic", "Generic PLA"), matchParents(list, "pla"))
        assertEquals(listOf("Bambu PETG Basic"), matchParents(list, "BAMBU  petg"))
        assertEquals(emptyList<String>(), matchParents(list, "silk"))
    }

    @Test fun anUnpairedPhoneAndAChangedCertificateAreTheHubNoticesNotMessages() {
        assertEquals(SaveFailure.NotPaired, failOf(ApiError(401, "unauthorized", "no")).kind)
        assertEquals(SaveFailure.CertificateChanged, failOf(FingerprintMismatch("a", "b")).kind)
        assertEquals(SaveFailure.Unknown, failOf(IllegalStateException()).kind)
    }

    // ---- pairing again --------------------------------------------------------------------------------------------

    @Test fun pairingAgainDropsTheOldNoticesAndReadsEverythingAgain() = runTest(dispatcher) {
        api.linesFailure = ApiError(0, "offline", "x")
        api.uncoveredFailure = ApiError(0, "offline", "x")
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        val first = Any()
        vm.pairedWith(first)
        vm.pairedWith(first)
        advanceUntilIdle()
        assertEquals("the same pairing reads nothing again", 1, api.linesCalls)
        api.failure = ApiError(401, "unauthorized", "no")
        vm.build()
        advanceUntilIdle()
        assertNotNull(vm.state.value.buildNote)
        assertNotNull(vm.state.value.linesFail)
        assertNotNull(vm.state.value.uncoveredFail)

        api.linesFailure = null
        api.uncoveredFailure = null
        api.failure = null
        val statusBefore = api.statusCalls
        vm.pairedWith(null)
        vm.pairedWith(Any())
        advanceUntilIdle()
        val s = vm.state.value
        assertNull(s.linesFail)
        assertNull(s.uncoveredFail)
        assertNull(s.buildNote)
        assertEquals(2, s.lines?.size)
        assertEquals(listOf(7, 9), s.uncovered?.map { it.id })
        assertEquals(statusBefore + 1, api.statusCalls)
    }

    @Test fun theOldNoticeOfACardGoesWhenThePhonePairsAgain() = runTest(dispatcher) {
        api.failure = ApiError(401, "unauthorized", "no")
        val vm = PresetsViewModel(api)
        advanceUntilIdle()
        vm.pairedWith(Any())
        vm.addToLine(vm.state.value.uncovered!!.first())
        advanceUntilIdle()
        assertEquals(SaveFailure.NotPaired, vm.state.value.card(7).fail?.kind)
        api.failure = null
        vm.pairedWith(Any())
        advanceUntilIdle()
        assertNull(vm.state.value.card(7).fail)
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
