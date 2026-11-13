package com.thompsonfabco.filamentkit.ui.profile

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LocalEntryResult
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Bed
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Density
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Line
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Material
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.MaxVolumetric
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.Notes
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.NozzleHigh
import com.thompsonfabco.filamentkit.ui.profile.ProfileField.NozzleLow
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
        vm.set(NozzleLow, "205")
        vm.set(NozzleHigh, "230")
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

    @Test fun onlyTheGivenRangeKeysAreSent() {
        val entry = buildProfileEntry(mapOf(Vendor to "A", Line to "B", Material to "PETG", NozzleHigh to "250", Notes to "dry first"))
        assertEquals(
            Json.parseToJsonElement("""{"nozzle_temperature_range_high":["250"]}"""),
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

    @Test fun successSaysPresetsAreRebuilt() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        filled(vm)
        vm.save()
        advanceUntilIdle()
        val s = vm.state.value
        assertEquals("Saved. Presets are rebuilt in a minute.", s.saved)
        assertTrue(s.problems.isEmpty())
        assertNull(s.error)
        assertFalse(s.saving)
    }

    @Test fun saveIsOffAfterASuccessUntilTheFormIsEdited() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        filled(vm)
        vm.save()
        advanceUntilIdle()
        assertFalse(vm.state.value.canSave)
        vm.save()
        advanceUntilIdle()
        assertEquals(1, api.posted.size)
        vm.set(Density, "1.2")
        assertTrue(vm.state.value.canSave)
    }

    @Test fun invalidEntryProblemsBecomeTheFieldErrorsList() = runTest(dispatcher) {
        val problems = listOf("fields.filament_density '9' is outside 0.5-3.0 g/cm3", "nozzle range low 240 is above high 230")
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
        assertNull(s.saved)
        assertNull("problems are shown instead of a general error", s.error)
        vm.set(Density, "1.2")
        assertTrue("an edit clears them", vm.state.value.problems.isEmpty())
    }

    @Test fun invalidEntryWithoutProblemsShowsTheMessage() = runTest(dispatcher) {
        api.failure = ApiError(400, "invalid_entry", "the entry is not valid")
        val vm = AddProfileViewModel(api)
        filled(vm)
        vm.save()
        advanceUntilIdle()
        assertEquals(listOf("the entry is not valid"), vm.state.value.problems)
    }

    @Test fun otherErrorsShowAPlainMessageOrTheServerText() = runTest(dispatcher) {
        val vm = AddProfileViewModel(api)
        filled(vm)
        api.failure = ApiError(0, "offline", "socket")
        vm.save()
        advanceUntilIdle()
        assertEquals(OFFLINE, vm.state.value.error)
        api.failure = ApiError(500, "weird_code", "library store is locked")
        vm.save()
        advanceUntilIdle()
        assertEquals("library store is locked", vm.state.value.error)
        api.failure = ApiError(401, "unauthorized", "x")
        vm.save()
        advanceUntilIdle()
        assertTrue(vm.state.value.pairAgain)
    }

    @Test fun aChangedCertificateAsksForPairing() = runTest(dispatcher) {
        api.failure = FingerprintMismatch("aa", "bb")
        val vm = AddProfileViewModel(api)
        filled(vm)
        vm.save()
        advanceUntilIdle()
        assertTrue(vm.state.value.pairAgain)
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

    override suspend fun addLocalProfile(entry: JsonObject): LocalEntryResult {
        posted += entry
        failure?.let { throw it }
        return LocalEntryResult(entry, "sunlu--pla-plus-2-0")
    }
}
