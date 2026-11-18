package com.thompsonfabco.filamentkit.ui.profile

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LocalEntry
import com.thompsonfabco.filamentkit.net.LocalEntryResult
import com.thompsonfabco.filamentkit.net.LocalLibrary
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.BedMax
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.BedMin
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Density
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Line
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Material
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.MaxVolumetric
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Notes
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.NozzleMax
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.NozzleMin
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
        vm.set(NozzleMin, "205")
        vm.set(NozzleMax, "230")
        vm.set(BedMin, "55")
        vm.set(BedMax, "65")
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
        val entry = buildProfileEntry(mapOf(Vendor to "A", Line to "B", Material to "PETG", NozzleMin to "250", Notes to "dry first"))
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
        assertEquals(setOf(Density, NozzleMin), s.fieldProblems.keys)
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
        assertEquals(ProfileField.BedMin, fieldOf("bed range 70-60 is reversed"))
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

    @Test fun pairingClearsAStaleFailure() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        filled(vm)
        api.failure = ApiError(0, "offline", "No Hub is paired.")
        vm.save()
        advanceUntilIdle()
        assertEquals(SaveFailure.Unreachable, vm.state.value.failure)

        api.failure = null
        vm.onPaired()
        advanceUntilIdle()

        assertNull(vm.state.value.failure)
    }

    // --- the Hub builds the entry (R83 section 4) ---

    @Test fun theFormSendsValuesAndTheHubBuildsTheEntry() = runTest(dispatcher) {
        api.formEnabled = true
        val vm = AddProfileViewModel(api)
        filled(vm)
        val expected = Json.parseToJsonElement(
            """{"brand":"SUNLU","name":"PLA+ 2.0","material":"PLA","nozzle_min":205,"nozzle_max":230,"bed_min":55,"bed_max":65,
            "density":1.24,"max_volumetric_speed":21,"bambu_parent":"SUNLU PLA+ 2.0","notes":"From the box label"}""",
        )
        assertEquals(expected, vm.values())
        vm.save()
        advanceUntilIdle()
        assertEquals(listOf(expected), api.forms)
        assertTrue("the app built no entry itself", api.posted.isEmpty())
        val s = vm.state.value
        assertTrue(s.added)
        assertFalse(s.saved)
        assertTrue("the form is empty for the next one", s.values.isEmpty())
        assertFalse(s.dirty)
        vm.set(Notes, "x")
        assertFalse("typing again drops the Added line", vm.state.value.added)
    }

    @Test fun onlyTheThreeFieldsAreSentWhenNothingElseWasTyped() {
        assertEquals(
            Json.parseToJsonElement("""{"brand":"A","name":"B","material":"PETG"}"""),
            formValues(mapOf(Vendor to " A ", Line to "B", Material to "PETG", Notes to " ", Density to "")),
        )
        assertEquals("a word that is not a number goes as typed", JsonPrimitive("hot"), formValues(mapOf(Density to "hot"))["density"])
    }

    @Test fun anOlderHubWithoutTheFormRouteGetsTheOldPath() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api) // formEnabled is false: the form route answers 404
        filled(vm)
        vm.save()
        advanceUntilIdle()
        assertEquals(1, api.posted.size)
        assertTrue(vm.state.value.saved)
        assertFalse(vm.state.value.added)
    }

    @Test fun refusedFieldsAreShownUnderTheirFieldsAndTheRestAsBullets() = runTest(dispatcher) {
        api.formEnabled = true
        api.failure = ApiError(
            400, "invalid_entry", "not valid",
            JsonObject(
                mapOf(
                    "problems" to JsonArray(
                        listOf(
                            buildJsonObject { put("field", "density"); put("text", "Density must be 0.5 to 3") },
                            buildJsonObject { put("field", "nozzle_max"); put("text", "Nozzle to is below from") },
                            buildJsonObject { put("field", "other"); put("text", "Something else") },
                        ),
                    ),
                ),
            ),
        )
        val vm = AddProfileViewModel(api)
        filled(vm)
        vm.save()
        advanceUntilIdle()
        val s = vm.state.value
        assertEquals(mapOf(Density to "Density must be 0.5 to 3", NozzleMax to "Nozzle to is below from"), s.fieldProblems)
        assertEquals(listOf("Something else"), s.problems)
        assertFalse(s.added)
        assertEquals("the typing is kept", "1.24", s.values[Density])
    }

    @Test fun theMaterialChoiceComesFromTheHubAndTheFixedListIsTheFallback() = runTest(dispatcher) {
        api.materials = listOf("PLA", "Wood PLA", "PEEK")
        val vm = AddProfileViewModel(api)
        advanceUntilIdle()
        assertEquals(listOf("PLA", "Wood PLA", "PEEK"), vm.state.value.materials)
        val older = FakeProfileApi()
        val old = AddProfileViewModel(older)
        advanceUntilIdle()
        assertNull("an older Hub sends none: the screen uses CatalogTexts.MATERIALS", old.state.value.materials)
        val missing = FakeProfileApi().apply { entriesError = ApiError(404, "not_found", "Not found") }
        val m = AddProfileViewModel(missing)
        advanceUntilIdle()
        assertNull(m.state.value.materials)
    }

    @Test fun theListOpensReadsOnceAndRemoveAsksFirst() = runTest(dispatcher) {
        api.entries = mutableListOf(LocalEntry("a", "SUNLU", "PLA+", "PLA", "2026-11-01"), LocalEntry("b", "Eryone", "Silk", "PLA", null))
        val vm = AddProfileViewModel(api)
        vm.toggleEntries()
        advanceUntilIdle()
        assertEquals(listOf("a", "b"), vm.state.value.entries!!.map { it.id })
        vm.toggleEntries()
        vm.toggleEntries()
        advanceUntilIdle()
        assertEquals("one read for the form's materials, one for the list; closing and opening again adds none", 2, api.listCalls)
        vm.askRemove(vm.state.value.entries!![0])
        assertEquals("Remove SUNLU PLA+ from your own entries? Slicer presets are rebuilt.", CatalogTexts.removeQuestion("SUNLU", "PLA+"))
        assertTrue("nothing is removed until asked", api.removed.isEmpty())
        vm.cancelRemove()
        vm.confirmRemove()
        advanceUntilIdle()
        assertTrue(api.removed.isEmpty())
        vm.askRemove(vm.state.value.entries!![0])
        vm.confirmRemove()
        advanceUntilIdle()
        assertEquals(listOf("a"), api.removed)
        assertEquals(listOf("b"), vm.state.value.entries!!.map { it.id })
        assertNull(vm.state.value.removeAsk)
    }

    @Test fun anEntryThatIsGoneAlreadyIsNotAnError() = runTest(dispatcher) {
        api.entries = mutableListOf(LocalEntry("a", "SUNLU", "PLA+", "PLA", null))
        api.removeError = ApiError(404, "not_found", "no such entry")
        val vm = AddProfileViewModel(api)
        vm.toggleEntries(); advanceUntilIdle()
        vm.askRemove(vm.state.value.entries!![0])
        vm.confirmRemove(); advanceUntilIdle()
        assertNull(vm.state.value.entriesFailure)
        assertNull(vm.state.value.removeAsk)
    }

    @Test fun anOlderHubHasNoListAndSaysSo() = runTest(dispatcher) {
        api.entriesError = ApiError(404, "not_found", "Not found")
        val vm = AddProfileViewModel(api)
        vm.toggleEntries(); advanceUntilIdle()
        assertTrue(vm.state.value.entriesUnavailable)
        assertNull(vm.state.value.entriesFailure)
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

    var formEnabled = false
    val forms = mutableListOf<JsonObject>()
    var entries = mutableListOf<LocalEntry>()
    var entriesError: Exception? = null
    var listCalls = 0
    val removed = mutableListOf<String>()
    var removeError: Exception? = null

    override suspend fun addLocalEntryForm(values: JsonObject): LocalEntry {
        if (!formEnabled) throw ApiError(404, "not_found", "Not found")
        forms += values
        failure?.let { throw it }
        return LocalEntry("new", "", "", "", null)
    }

    var materials: List<String>? = null

    override suspend fun localLibrary(): LocalLibrary {
        listCalls++
        entriesError?.let { throw it }
        return LocalLibrary(entries.toList(), materials)
    }

    override suspend fun removeLocalEntry(id: String) {
        removed += id
        entries.removeAll { it.id == id }
        removeError?.let { throw it }
    }

    override suspend fun addLocalProfile(entry: JsonObject): LocalEntryResult {
        posted += entry
        failure?.let { throw it }
        return LocalEntryResult(entry, "sunlu--pla-plus-2-0")
    }
}
