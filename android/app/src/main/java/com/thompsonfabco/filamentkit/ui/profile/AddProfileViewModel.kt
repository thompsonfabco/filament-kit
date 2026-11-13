package com.thompsonfabco.filamentkit.ui.profile

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LOCAL_NETWORK_MESSAGE
import com.thompsonfabco.filamentkit.net.LocalEntryResult
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.net.ProfileLine
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

/** The calls the catalog line form needs; [of] adapts the real [Api] (tests pass a fake). */
interface ProfileApi {
    suspend fun parents(material: String): ParentList
    suspend fun addLocalProfile(entry: JsonObject): LocalEntryResult
    suspend fun profileLines(): List<ProfileLine>
    suspend fun setLineParent(lineId: String, parent: String): ProfileLine

    companion object {
        /** Calls go to whatever [current] returns at that moment (see `IntakeApi.of`). */
        fun of(current: () -> Api): ProfileApi = object : ProfileApi {
            private fun api() = current()
            override suspend fun parents(material: String) = api().parents(material)
            override suspend fun addLocalProfile(entry: JsonObject) = api().addLocalProfile(entry)
            override suspend fun profileLines() = api().profileLines()
            override suspend fun setLineParent(lineId: String, parent: String) = api().setLineParent(lineId, parent)
        }

        fun of(api: Api): ProfileApi = object : ProfileApi {
            override suspend fun parents(material: String) = api.parents(material)
            override suspend fun addLocalProfile(entry: JsonObject) = api.addLocalProfile(entry)
            override suspend fun profileLines() = api.profileLines()
            override suspend fun setLineParent(lineId: String, parent: String) = api.setLineParent(lineId, parent)
        }
    }
}

/** The form's fields, in screen order; [required] ones must be filled to save. [label] is the 05 8 text. */
enum class ProfileField(@StringRes val label: Int, val required: Boolean = false, val number: Boolean = false) {
    Vendor(R.string.catalog_field_brand, required = true),
    Line(R.string.catalog_field_line, required = true),
    Material(R.string.catalog_field_material, required = true),
    Nozzle(R.string.catalog_field_nozzle_range),
    Bed(R.string.catalog_field_bed_range),
    Density(R.string.catalog_field_density, number = true),
    MaxVolumetric(R.string.catalog_field_max_speed, number = true),
    Parent(R.string.common_field_bambu_parent),
    Notes(R.string.common_field_notes),
}

/** Why a save did not go through, when it is not a refused entry; the screen words it (05 8, 3.4). */
enum class SaveFailure { CertificateChanged, NotPaired, Unreachable, Unknown, Message }

/**
 * [problems]: the Hub's list for an `invalid_entry` (one bullet each); [fieldProblems]: the ones that name a field,
 * shown under it too; [badRange]: fields whose range text could not be read, caught before anything is sent.
 * [failure] with [message]: any other failure. [saved]: the line was saved and the screen leaves with the toast.
 * [parents] is the list for the current material (null until loaded).
 */
data class AddProfileUiState(
    val values: Map<ProfileField, String> = emptyMap(),
    val parents: ParentList? = null,
    val saving: Boolean = false,
    val saved: Boolean = false,
    val problems: List<String> = emptyList(),
    val fieldProblems: Map<ProfileField, String> = emptyMap(),
    val badRange: Set<ProfileField> = emptySet(),
    val failure: SaveFailure? = null,
    val message: String? = null,
    /** The lines the Hub already has (null until loaded; a failed load leaves it empty). */
    val lines: List<ProfileLine>? = null,
    val editing: LineParentEdit? = null,
    /** The line whose parent was just saved (its row says so), or the failure of a parent call. */
    val parentSavedFor: String? = null,
    val lineFailure: SaveFailure? = null,
    /** [lineFailure] came from loading the list (it offers Try again), not from a parent call. */
    val linesLoadFailed: Boolean = false,
    val lineMessage: String? = null,
) {
    /** The required fields are filled. */
    val filled: Boolean
        get() = ProfileField.entries.filter { it.required }.all { !values[it].isNullOrBlank() }

    /** Not again while saving or after a save (a second tap would post the same entry). */
    val canSave: Boolean get() = !saving && !saved && filled

    /** Something was typed: leaving asks first (05 2.5 rule 1). */
    val dirty: Boolean get() = !saved && values.values.any { it.isNotBlank() }
}

/** The parent choice open for [lineId]: the Bambu Studio parents for its material (null while loading). */
data class LineParentEdit(val lineId: String, val parents: ParentList? = null)

/** The catalog line form: the owner's own library entry for a product line, posted to `/api/library/local`. */
class AddProfileViewModel(private val api: ProfileApi) : ViewModel() {
    private val _state = MutableStateFlow(AddProfileUiState())
    val state: StateFlow<AddProfileUiState> = _state.asStateFlow()
    private var parentsJob: Job? = null

    init {
        loadLines()
    }

    /** The product lines already on the Hub. A failure leaves the list empty with its notice (the form still works). */
    private fun loadLines() {
        viewModelScope.launch {
            try {
                val lines = api.profileLines()
                _state.update { it.copy(lines = lines) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { lineFailed(it.copy(lines = emptyList(), linesLoadFailed = true), e) }
            }
        }
    }

    /** Try again after the list did not load. */
    fun retryLines() {
        _state.update { it.copy(lines = null, lineFailure = null, lineMessage = null, linesLoadFailed = false) }
        loadLines()
    }

    /** Opens the parent choice for [line], with the parents for its material. */
    fun editParent(line: ProfileLine) {
        _state.update { it.copy(editing = LineParentEdit(line.lineId), parentSavedFor = null, lineFailure = null) }
        viewModelScope.launch {
            try {
                val list = api.parents(line.material)
                _state.update { s -> s.copy(editing = s.editing?.takeIf { it.lineId == line.lineId }?.copy(parents = list)) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { lineFailed(it.copy(editing = null), e) }
            }
        }
    }

    fun cancelEditParent() = _state.update { it.copy(editing = null) }

    /** Sets [parent] on the line being edited (the Hub refuses a blank one, so nothing is sent for it). */
    fun setLineParent(parent: String) {
        val lineId = _state.value.editing?.lineId ?: return
        if (parent.isBlank()) return
        viewModelScope.launch {
            try {
                val updated = api.setLineParent(lineId, parent)
                _state.update { s ->
                    s.copy(
                        lines = s.lines?.map { if (it.lineId == lineId) updated else it }, editing = null,
                        parentSavedFor = lineId, lineFailure = null, lineMessage = null,
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { lineFailed(it.copy(editing = null), e) }
            }
        }
    }

    private fun lineFailed(s: AddProfileUiState, e: Exception): AddProfileUiState = when {
        e is FingerprintMismatch -> s.copy(lineFailure = SaveFailure.CertificateChanged)
        e !is ApiError -> s.copy(lineFailure = SaveFailure.Unknown)
        e.code == "offline" -> s.copy(lineFailure = SaveFailure.Unreachable)
        e.code == "local_network" -> s.copy(lineFailure = SaveFailure.Message, lineMessage = LOCAL_NETWORK_MESSAGE)
        e.code == "unauthorized" -> s.copy(lineFailure = SaveFailure.NotPaired)
        else -> s.copy(lineFailure = SaveFailure.Message, lineMessage = e.message)
    }

    fun set(field: ProfileField, value: String) {
        _state.update {
            it.copy(
                values = it.values + (field to value), problems = emptyList(), fieldProblems = emptyMap(),
                badRange = it.badRange - field, failure = null, message = null,
            )
        }
        if (field == ProfileField.Material) loadParents(value.trim())
    }

    /** The entry the current form would post. */
    fun entry(): JsonObject = buildProfileEntry(_state.value.values)

    fun save() {
        val s = _state.value
        if (!s.canSave) return
        val nozzle = s.values[ProfileField.Nozzle]
        if (!nozzle.isNullOrBlank() && readRange(nozzle) == null) {
            _state.update { it.copy(badRange = setOf(ProfileField.Nozzle)) }
            return
        }
        val entry = buildProfileEntry(s.values)
        _state.update { it.copy(saving = true, problems = emptyList(), fieldProblems = emptyMap(), failure = null, message = null) }
        viewModelScope.launch {
            try {
                api.addLocalProfile(entry)
                // the form is gone with its values, so a second tap cannot save the same line twice
                _state.value = AddProfileUiState(saved = true)
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
        e is FingerprintMismatch -> s.copy(failure = SaveFailure.CertificateChanged)
        e !is ApiError -> s.copy(failure = SaveFailure.Unknown)
        e.code == "invalid_entry" -> {
            val list = (e.extra["problems"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
                .ifEmpty { listOf(e.message) }
            val named = list.mapNotNull { p -> fieldOf(p)?.let { it to p } }.toMap()
            s.copy(problems = list, fieldProblems = named)
        }
        e.code == "offline" -> s.copy(failure = SaveFailure.Unreachable)
        e.code == "local_network" -> s.copy(failure = SaveFailure.Message, message = LOCAL_NETWORK_MESSAGE)
        e.code == "unauthorized" -> s.copy(failure = SaveFailure.NotPaired)
        else -> s.copy(failure = SaveFailure.Message, message = e.message)
    }

    companion object {
        internal const val PARENTS_DEBOUNCE_MS = 500L
    }
}

/** The field a Hub problem names, by the entry key it quotes (`fields.filament_density ...`); null when it names none. */
internal fun fieldOf(problem: String): ProfileField? {
    val p = problem.lowercase()
    return when {
        "volumetric" in p -> ProfileField.MaxVolumetric
        "density" in p -> ProfileField.Density
        "nozzle" in p -> ProfileField.Nozzle
        "bed" in p -> ProfileField.Bed
        "parent" in p -> ProfileField.Parent
        "notes" in p -> ProfileField.Notes
        "vendor" in p -> ProfileField.Vendor
        "product" in p -> ProfileField.Line
        "material" in p -> ProfileField.Material
        else -> null
    }
}

private val RANGE = Regex("""^(\d+(?:\.\d+)?)\s*(?:[-–—]\s*(\d+(?:\.\d+)?))?$""")

/** "190-220" as (190, 220); a single number is both ends; null when the text is neither. */
internal fun readRange(text: String): Pair<String, String>? {
    val m = RANGE.matchEntire(text.trim()) ?: return null
    val low = m.groupValues[1]
    return low to m.groupValues[2].ifEmpty { low }
}

/**
 * The library entry for a filled form (schema_version 1). Values are trimmed; empty fields are left out.
 * Numbers go into `fields` as one-element string arrays (the nozzle range as its low and high ends); the bed range
 * and notes into `published_ranges`.
 */
internal fun buildProfileEntry(values: Map<ProfileField, String>): JsonObject {
    fun v(f: ProfileField): String? = values[f]?.trim()?.takeIf { it.isNotEmpty() }
    fun one(s: String) = JsonArray(listOf(JsonPrimitive(s)))
    val nozzle = v(ProfileField.Nozzle)?.let(::readRange)
    val fields = listOfNotNull(
        nozzle?.let { "nozzle_temperature_range_low" to one(it.first) },
        nozzle?.let { "nozzle_temperature_range_high" to one(it.second) },
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
