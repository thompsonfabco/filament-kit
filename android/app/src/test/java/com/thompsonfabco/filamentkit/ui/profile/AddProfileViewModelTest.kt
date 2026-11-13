package com.thompsonfabco.filamentkit.ui.profile

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LocalEntryResult
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.net.ProfileLine
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Bed
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Density
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Line
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Material
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.MaxVolumetric
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Notes
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Nozzle
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Parent
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Vendor
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
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
class AddProfileViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val api = FakeProfileApi()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)

    @After fun tearDown() = Dispatchers.resetMain()

    private fun filled(vm: AddProfileViewModel) {
        vm.set(Vendor, " SUNLU ")
        vm.set(Line, "PLA+ 2.0")
        vm.set(Material, "PLA")
        vm.set(Nozzle, "205-230")
        vm.set(Bed, "55-65")
        vm.set(Density, "1.24")
        vm.set(MaxVolumetric, "21")
        vm.set(Parent, "SUNLU PLA+ 2.0")
        vm.set(Notes, "From the box label")
    }

    @Test fun aFilledFormBuildsTheExactEntry() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        filled(vm)
        val expected = Json.parseToJsonElement(
            """{"schema_version":1,"vendor":"SUNLU","product":"PLA+ 2.0","material":"PLA",
            "bambu_parent":"SUNLU PLA+ 2.0",
            "fields":{"nozzle_temperature_range_low":["205"],"nozzle_temperature_range_high":["230"],
              "filament_density":["1.24"],"filament_max_volumetric_speed":["21"]},
            "published_ranges":{"bed_all_plates":"55-65","_notes":"From the box label"}}""",
        )
        assertEquals(expected, vm.entry())
        vm.save()
        advanceUntilIdle()
        assertEquals(listOf(expected), api.posted)
    }

    @Test fun emptyFieldsAreLeftOut() {
        val entry = buildProfileEntry(mapOf(Vendor to "SUNLU", Line to "PLA+", Material to "PLA", Density to "  ", Notes to ""))
        val expected = buildJsonObject {
            put("schema_version", 1)
            put("vendor", "SUNLU")
            put("product", "PLA+")
            put("material", "PLA")
            put("fields", JsonObject(emptyMap()))
        }
        assertEquals(expected, entry)
    }

    @Test fun aSingleNozzleTemperatureIsBothEndsOfTheRange() {
        val entry = buildProfileEntry(mapOf(Vendor to "A", Line to "B", Material to "PETG", Nozzle to "250", Notes to "dry first"))
        assertEquals(
            Json.parseToJsonElement("""{"nozzle_temperature_range_low":["250"],"nozzle_temperature_range_high":["250"]}"""),
            entry["fields"],
        )
        assertEquals(Json.parseToJsonElement("""{"_notes":"dry first"}"""), entry["published_ranges"])
        assertFalse(entry.containsKey("bambu_parent"))
    }

    @Test fun saveNeedsVendorLineAndMaterial() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        vm.set(Vendor, "SUNLU")
        vm.set(Material, "PLA")
        assertFalse(vm.state.value.canSave)
        vm.save()
        advanceUntilIdle()
        assertTrue(api.posted.isEmpty())
        vm.set(Line, "PLA+")
        assertTrue(vm.state.value.canSave)
    }

    @Test fun successLeavesAnEmptyFormAndSaysSaved() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        filled(vm)
        vm.save()
        advanceUntilIdle()
        val s = vm.state.value
        assertTrue(s.saved)
        assertTrue("the form is gone with its values", s.values.isEmpty())
        assertTrue(s.problems.isEmpty())
        assertNull(s.failure)
        assertFalse(s.saving)
        assertFalse("leaving after a save does not ask", s.dirty)
    }

    @Test fun saveIsOffWhileSavingAndAfterASuccess() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        filled(vm)
        vm.save()
        vm.save() // ignored: the first is still running
        advanceUntilIdle()
        vm.save()
        advanceUntilIdle()
        assertEquals(1, api.posted.size)
        assertFalse(vm.state.value.canSave)
    }

    @Test fun typingMakesTheFormDirty() {
        val vm = AddProfileViewModel(api)
        assertFalse(vm.state.value.dirty)
        vm.set(Notes, "  ")
        assertFalse(vm.state.value.dirty)
        vm.set(Notes, "dry first")
        assertTrue(vm.state.value.dirty)
    }

    @Test fun readsRanges() {
        assertEquals("190" to "220", readRange("190-220"))
        assertEquals("190" to "220", readRange(" 190 – 220 "))
        assertEquals("205" to "205", readRange("205"))
        assertEquals("55.5" to "65", readRange("55.5-65"))
        assertNull(readRange("hot"))
        assertNull(readRange("190-"))
    }

    @Test fun anUnreadableNozzleRangeIsCaughtBeforeSending() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        filled(vm)
        vm.set(Nozzle, "hot")
        vm.save()
        advanceUntilIdle()
        assertTrue(api.posted.isEmpty())
        assertEquals(setOf(Nozzle), vm.state.value.badRange)
        vm.set(Nozzle, "190-220")
        assertTrue(vm.state.value.badRange.isEmpty())
    }

    @Test fun invalidEntryProblemsAreListedAndNamedFieldsGetThemToo() = runTest(dispatcher) {
        val problems = listOf(
            "fields.filament_density '9' is outside 0.5-3.0 g/cm3", "nozzle range low 240 is above high 230",
            "the entry has no meaning",
        )
        api.failure = ApiError(
            400, "invalid_entry", "the entry is not valid",
            JsonObject(mapOf("problems" to JsonArray(problems.map(::JsonPrimitive)))),
        )
        val vm = AddProfileViewModel(api)
        filled(vm)
        vm.save()
        advanceUntilIdle()
        val s = vm.state.value
        assertEquals(problems, s.problems)
        assertEquals(setOf(Density, Nozzle), s.fieldProblems.keys)
        assertEquals(problems[0], s.fieldProblems[Density])
        assertFalse(s.saved)
        assertNull("problems are shown instead of a general failure", s.failure)
        assertEquals("the typing is kept", "1.24", s.values[Density])
        vm.set(Density, "1.2")
        assertTrue("an edit clears them", vm.state.value.problems.isEmpty() && vm.state.value.fieldProblems.isEmpty())
    }

    @Test fun problemsNameTheirField() {
        assertEquals(ProfileField.MaxVolumetric, fieldOf("fields.filament_max_volumetric_speed 'x' is not a number"))
        assertEquals(ProfileField.Parent, fieldOf("bambu_parent 'Foo' is not a Bambu Studio preset"))
        assertEquals(ProfileField.Bed, fieldOf("bed range 70-60 is reversed"))
        assertEquals(ProfileField.Vendor, fieldOf("vendor is empty"))
        assertNull(fieldOf("schema_version must be 1"))
    }

    @Test fun invalidEntryWithoutProblemsShowsTheMessage() = runTest(dispatcher) {
        api.failure = ApiError(400, "invalid_entry", "the entry is not valid")
        val vm = AddProfileViewModel(api)
        filled(vm)
        vm.save()
        advanceUntilIdle()
        assertEquals(listOf("the entry is not valid"), vm.state.value.problems)
    }

    @Test fun otherFailuresAreNamedForTheScreen() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        filled(vm)
        api.failure = ApiError(0, "offline", "socket")
        vm.save()
        advanceUntilIdle()
        assertEquals(SaveFailure.Unreachable, vm.state.value.failure)
        api.failure = ApiError(500, "weird_code", "library store is locked")
        vm.save()
        advanceUntilIdle()
        assertEquals(SaveFailure.Message, vm.state.value.failure)
        assertEquals("library store is locked", vm.state.value.message)
        api.failure = ApiError(401, "unauthorized", "x")
        vm.save()
        advanceUntilIdle()
        assertEquals(SaveFailure.NotPaired, vm.state.value.failure)
        api.failure = FingerprintMismatch("aa", "bb")
        vm.save()
        advanceUntilIdle()
        assertEquals(SaveFailure.CertificateChanged, vm.state.value.failure)
        api.failure = IllegalStateException("odd")
        vm.save()
        advanceUntilIdle()
        assertEquals(SaveFailure.Unknown, vm.state.value.failure)
    }

    @Test fun theFailureGoesOnEditAndOnSuccess() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        filled(vm)
        api.failure = FingerprintMismatch("aa", "bb")
        vm.save()
        advanceUntilIdle()
        vm.set(Notes, "edited")
        assertNull(vm.state.value.failure)
        vm.save()
        advanceUntilIdle()
        api.failure = null
        vm.save()
        advanceUntilIdle()
        assertNull(vm.state.value.failure)
        assertTrue(vm.state.value.saved)
    }

    @Test fun listsTheHubsLinesAndReparentsOne() = runTest(dispatcher) {
        api.parentLists["PLA"] = ParentList(listOf("Bambu PLA Basic"), synced = true)
        val vm = AddProfileViewModel(api)
        assertNull("loading until the Hub answers", vm.state.value.lines)
        advanceUntilIdle()
        assertEquals(listOf("example--pla"), vm.state.value.lines?.map { it.lineId })

        vm.editParent(vm.state.value.lines!!.single())
        advanceUntilIdle()
        assertEquals(listOf("Bambu PLA Basic"), vm.state.value.editing?.parents?.parents)

        vm.setLineParent("Bambu PLA Basic")
        advanceUntilIdle()

        assertEquals(listOf("example--pla" to "Bambu PLA Basic"), api.reparented)
        assertEquals("Bambu PLA Basic", vm.state.value.lines?.single()?.bambuParent)
        assertEquals("example--pla", vm.state.value.parentSavedFor)
        assertNull(vm.state.value.editing)
    }

    @Test fun aBlankParentIsNeverSent() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        advanceUntilIdle()
        vm.editParent(vm.state.value.lines!!.single())
        advanceUntilIdle()
        vm.setLineParent(" ")
        advanceUntilIdle()
        assertTrue(api.reparented.isEmpty())
    }

    @Test fun aRefusedParentShowsTheHubsMessageAndKeepsTheLine() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        advanceUntilIdle()
        vm.editParent(vm.state.value.lines!!.single())
        advanceUntilIdle()
        api.failure = ApiError(400, "unknown_parent", "Bambu Studio has no such preset")
        vm.setLineParent("Nope")
        advanceUntilIdle()
        assertEquals(SaveFailure.Message, vm.state.value.lineFailure)
        assertEquals("Bambu Studio has no such preset", vm.state.value.lineMessage)
        assertNull(vm.state.value.lines?.single()?.bambuParent)
        assertNull(vm.state.value.parentSavedFor)
    }

    @Test fun aFailedLoadLeavesAnEmptyList() = runTest(dispatcher) {
        api.linesFailure = ApiError(0, "offline", "socket")
        val vm = AddProfileViewModel(api)
        advanceUntilIdle()
        assertEquals(emptyList<ProfileLine>(), vm.state.value.lines)
        assertEquals(SaveFailure.Unreachable, vm.state.value.lineFailure)
        assertTrue(vm.state.value.linesLoadFailed)

        api.linesFailure = null
        vm.retryLines()
        assertNull("loading again", vm.state.value.lines)
        advanceUntilIdle()
        assertEquals(listOf("example--pla"), vm.state.value.lines?.map { it.lineId })
        assertNull(vm.state.value.lineFailure)
        assertFalse(vm.state.value.linesLoadFailed)
    }

    @Test fun parentsAreLoadedForTheMaterialAfterAPause() = runTest(dispatcher) {
        api.parentLists["PETG"] = ParentList(listOf("Generic PETG", "SUNLU PETG"), synced = true)
        val vm = AddProfileViewModel(api)
        vm.set(Material, "PE")
        advanceTimeBy(100)
        vm.set(Material, "PETG")
        advanceUntilIdle()
        assertEquals(listOf("PETG"), api.parentCalls)
        assertEquals(ParentList(listOf("Generic PETG", "SUNLU PETG"), true), vm.state.value.parents)
    }
}

private class FakeProfileApi : ProfileApi {
    val posted = mutableListOf<JsonObject>()
    var failure: Exception? = null
    val parentLists = mutableMapOf<String, ParentList>()
    val parentCalls = mutableListOf<String>()

    override suspend fun parents(material: String): ParentList {
        parentCalls += material
        return parentLists[material] ?: ParentList(emptyList(), synced = false)
    }

    var linesFailure: Exception? = null
    var lines = listOf(ProfileLine(lineId = "example--pla", vendor = "Example", product = "PLA", material = "PLA"))
    val reparented = mutableListOf<Pair<String, String>>()

    override suspend fun profileLines(): List<ProfileLine> {
        linesFailure?.let { throw it }
        return lines
    }

    override suspend fun setLineParent(lineId: String, parent: String): ProfileLine {
        reparented += lineId to parent
        failure?.let { throw it }
        return lines.first { it.lineId == lineId }.copy(bambuParent = parent, parentSource = "user")
    }

    override suspend fun addLocalProfile(entry: JsonObject): LocalEntryResult {
        posted += entry
        failure?.let { throw it }
        return LocalEntryResult(entry, "sunlu--pla-plus-2-0")
    }
}
