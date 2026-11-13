package com.thompsonfabco.filamentkit.ui.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LOCAL_NETWORK_MESSAGE
import com.thompsonfabco.filamentkit.net.LocalEntryResult
import com.thompsonfabco.filamentkit.net.ParentList
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/** The calls the Add profile form needs; [of] adapts the real [Api] (tests pass a fake). */
interface ProfileApi {
    suspend fun parents(material: String): ParentList
    suspend fun addLocalProfile(entry: JsonObject): LocalEntryResult

    companion object {
        fun of(api: Api): ProfileApi = object : ProfileApi {
            override suspend fun parents(material: String) = api.parents(material)
            override suspend fun addLocalProfile(entry: JsonObject) = api.addLocalProfile(entry)
        }
    }
}

/** The form's fields, in screen order; [required] ones must be filled to save. */
enum class ProfileField(val label: String, val required: Boolean = false, val number: Boolean = false) {
    Vendor("Vendor", required = true),
    Line("Product line", required = true),
    Material("Material", required = true),
    NozzleLow("Nozzle low (°C)", number = true),
    NozzleHigh("Nozzle high (°C)", number = true),
    Bed("Bed range (°C, like 55-65)"),
    Density("Density (g/cm³)", number = true),
    MaxVolumetric("Max volumetric speed (mm³/s)", number = true),
    Parent("Bambu Studio parent"),
    Notes("Notes"),
}

/**
 * [problems]: the server's list for an `invalid_entry` (shown one per line); [error]: any other failure;
 * [saved]: the success text. [parents] is the list for the current material (null until loaded).
 */
data class AddProfileUiState(
    val values: Map<ProfileField, String> = emptyMap(),
    val parents: ParentList? = null,
    val saving: Boolean = false,
    val saved: String? = null,
    val problems: List<String> = emptyList(),
    val error: String? = null,
    val pairAgain: Boolean = false,
) {
    /** The required fields are filled. */
    val filled: Boolean
        get() = ProfileField.entries.filter { it.required }.all { !values[it].isNullOrBlank() }

    /** Not again right after a save (a second tap would post the same entry); any edit clears [saved]. */
    val canSave: Boolean get() = !saving && saved == null && filled
}

/** "Add profile": the owner's own library entry for a product line, posted to `/api/library/local`. */
class AddProfileViewModel(private val api: ProfileApi) : ViewModel() {
    private val _state = MutableStateFlow(AddProfileUiState())
    val state: StateFlow<AddProfileUiState> = _state.asStateFlow()
    private var parentsJob: Job? = null

    fun set(field: ProfileField, value: String) {
        _state.update { it.copy(values = it.values + (field to value), problems = emptyList(), error = null, saved = null) }
        if (field == ProfileField.Material) loadParents(value.trim())
    }

    /** The entry the current form would post. */
    fun entry(): JsonObject = buildProfileEntry(_state.value.values)

    fun save() {
        val s = _state.value
        if (!s.canSave) return
        val entry = buildProfileEntry(s.values)
        _state.update { it.copy(saving = true, problems = emptyList(), error = null, saved = null) }
        viewModelScope.launch {
            try {
                api.addLocalProfile(entry)
                _state.update { it.copy(saving = false, saved = SAVED) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { failed(it.copy(saving = false), e) }
            }
        }
    }

    /** The material's parents after a pause (typing restarts it). A failure keeps the field free text. */
    private fun loadParents(material: String) {
        parentsJob?.cancel()
        _state.update { it.copy(parents = null) }
        if (material.isEmpty()) return
        parentsJob = viewModelScope.launch {
            delay(PARENTS_DEBOUNCE_MS)
            try {
                val list = api.parents(material)
                _state.update { it.copy(parents = list) }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
            }
        }
    }

    private fun failed(s: AddProfileUiState, e: Exception): AddProfileUiState = when {
        e is FingerprintMismatch -> s.copy(error = CERT_CHANGED, pairAgain = true)
        e !is ApiError -> s.copy(error = "Unexpected response from the server")
        e.code == "invalid_entry" -> {
            val list = (e.extra["problems"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
            s.copy(problems = list.ifEmpty { listOf(e.message) })
        }
        e.code == "offline" -> s.copy(error = OFFLINE)
        e.code == "local_network" -> s.copy(error = LOCAL_NETWORK_MESSAGE)
        e.code == "unauthorized" -> s.copy(error = "This phone is no longer paired with the server. Pair it again.", pairAgain = true)
        else -> s.copy(error = e.message)
    }

    companion object {
        const val SAVED = "Saved. Presets are rebuilt in a minute."
        internal const val PARENTS_DEBOUNCE_MS = 500L
        private const val CERT_CHANGED = "The server's certificate has changed. Pair again only if you reinstalled the server."
    }
}

internal const val OFFLINE = "Can't reach the server. Check that this phone is on the same network as the server, then try again."

/**
 * The library entry for a filled form (schema_version 1). Values are trimmed; empty fields are left out.
 * Numbers go into `fields` as one-element string arrays; the bed range and notes into `published_ranges`.
 */
internal fun buildProfileEntry(values: Map<ProfileField, String>): JsonObject {
    fun v(f: ProfileField): String? = values[f]?.trim()?.takeIf { it.isNotEmpty() }
    fun one(s: String) = JsonArray(listOf(JsonPrimitive(s)))
    val fields = listOfNotNull(
        v(ProfileField.NozzleLow)?.let { "nozzle_temperature_range_low" to one(it) },
        v(ProfileField.NozzleHigh)?.let { "nozzle_temperature_range_high" to one(it) },
        v(ProfileField.Density)?.let { "filament_density" to one(it) },
        v(ProfileField.MaxVolumetric)?.let { "filament_max_volumetric_speed" to one(it) },
    ).toMap()
    val ranges = listOfNotNull(
        v(ProfileField.Bed)?.let { "bed_all_plates" to JsonPrimitive(it) },
        v(ProfileField.Notes)?.let { "_notes" to JsonPrimitive(it) },
    ).toMap()
    val entry = linkedMapOf<String, JsonElement>(
        "schema_version" to JsonPrimitive(1),
        "vendor" to JsonPrimitive(v(ProfileField.Vendor).orEmpty()),
        "product" to JsonPrimitive(v(ProfileField.Line).orEmpty()),
        "material" to JsonPrimitive(v(ProfileField.Material).orEmpty()),
    )
    v(ProfileField.Parent)?.let { entry["bambu_parent"] = JsonPrimitive(it) }
    entry["fields"] = JsonObject(fields)
    if (ranges.isNotEmpty()) entry["published_ranges"] = JsonObject(ranges)
    return JsonObject(entry)
}
