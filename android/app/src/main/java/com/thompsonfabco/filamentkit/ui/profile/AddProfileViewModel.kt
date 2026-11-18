package com.thompsonfabco.filamentkit.ui.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.KitWire
import com.thompsonfabco.filamentkit.net.LOCAL_NETWORK_MESSAGE
import com.thompsonfabco.filamentkit.net.LocalEntry
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

/** The calls the catalog line form needs; [of] adapts the real [Api] (tests pass a fake). */
interface ProfileApi {
    suspend fun parents(material: String): ParentList

    /** The old way, kept for a Hub without the form route (404): the app builds the entry itself. */
    suspend fun addLocalProfile(entry: JsonObject): LocalEntryResult

    /** The form's values go to the Hub, which builds the entry (R83 section 4). A backend without it answers as an older Hub (404). */
    suspend fun addLocalEntryForm(values: JsonObject): LocalEntry = throw ApiError(NOT_FOUND, "not_found", "Not found")

    /** The owner's own entries; 404 from an older Hub. */
    suspend fun localLibrary(): List<LocalEntry> = throw ApiError(NOT_FOUND, "not_found", "Not found")

    /** Removes one of the owner's own entries; 404 when the Hub has no such entry. */
    suspend fun removeLocalEntry(id: String): Unit = throw ApiError(NOT_FOUND, "not_found", "Not found")

    companion object {
        const val NOT_FOUND = 404

        /** Calls go to whatever [current] returns at that moment (see `IntakeApi.of`). */
        fun of(current: () -> Api): ProfileApi = object : ProfileApi {
            private fun api() = current()
            override suspend fun parents(material: String) = api().parents(material)
            override suspend fun addLocalProfile(entry: JsonObject) = api().addLocalProfile(entry)
            override suspend fun addLocalEntryForm(values: JsonObject) = api().addLocalEntryForm(values)
            override suspend fun localLibrary() = api().localLibrary()
            override suspend fun removeLocalEntry(id: String) = api().removeLocalEntry(id)
        }

        fun of(api: Api): ProfileApi = of { api }
    }
}

/**
 * The form's fields, in screen order; [required] ones must be filled to add. The first three are the form, the rest
 * sit under the closed "More (optional)" ([optional]).
 */
enum class ProfileField(val required: Boolean = false, val number: Boolean = false, val optional: Boolean = true) {
    Vendor(required = true, optional = false),
    Line(required = true, optional = false),
    Material(required = true, optional = false),
    NozzleMin(number = true),
    NozzleMax(number = true),
    BedMin(number = true),
    BedMax(number = true),
    Density(number = true),
    MaxVolumetric(number = true),
    Parent,
    Notes,
}

/** Why a save did not go through, when it is not a refused entry; the screen words it (05 8, 3.4). */
enum class SaveFailure { CertificateChanged, NotPaired, Unreachable, Unknown, Message }

/**
 * [problems]: the Hub's problems that name no field of the form (one bullet each); [fieldProblems]: the ones that name
 * a field, shown under it. [failure] with [message]: any other failure. [added]: the Hub built the entry and the form
 * is empty again; [saved]: the old way was used and the screen leaves with the toast. [parents] is the list for the
 * current material (null until loaded). The rest is the list of the owner's own entries ([entries], null until read).
 */
data class AddProfileUiState(
    val values: Map<ProfileField, String> = emptyMap(),
    val parents: ParentList? = null,
    val saving: Boolean = false,
    val saved: Boolean = false,
    val added: Boolean = false,
    val problems: List<String> = emptyList(),
    val fieldProblems: Map<ProfileField, String> = emptyMap(),
    val failure: SaveFailure? = null,
    val message: String? = null,
    /** What the form was opened with (from a panel of Add spools): typing something else is what asks before leaving. */
    val opened: Map<ProfileField, String> = emptyMap(),
    val entriesOpen: Boolean = false,
    val entries: List<LocalEntry>? = null,
    val entriesLoading: Boolean = false,
    /** The Hub has no list of the owner's entries (404): "Update the Hub". */
    val entriesUnavailable: Boolean = false,
    val entriesFailure: SaveFailure? = null,
    val entriesMessage: String? = null,
    /** The entry the "Remove ... ?" question is about. */
    val removeAsk: LocalEntry? = null,
    val removing: Boolean = false,
) {
    /** The required fields are filled. */
    val filled: Boolean
        get() = ProfileField.entries.filter { it.required }.all { !values[it].isNullOrBlank() }

    /** Not again while saving or after the old way saved (a second tap would post the same entry). */
    val canSave: Boolean get() = !saving && !saved && filled

    /** Something was typed: leaving asks first (05 2.5 rule 1). */
    val dirty: Boolean get() = !saved && values.filterValues { it.isNotBlank() } != opened
}

/** The catalog form: the owner's own library entry for a product line, sent to the Hub as values to build the entry from. */
class AddProfileViewModel(
    private val api: ProfileApi,
    /** Fields the form opens with (Add spools' "Add this line to the Filament Catalog" fills brand, line and material). */
    initial: Map<ProfileField, String> = emptyMap(),
) : ViewModel() {
    private val _state = MutableStateFlow(
        initial.filterValues { it.isNotBlank() }.let { AddProfileUiState(values = it, opened = it) },
    )
    val state: StateFlow<AddProfileUiState> = _state.asStateFlow()
    private var parentsJob: Job? = null

    init {
        _state.value.values[ProfileField.Material]?.let { loadParents(it.trim()) }
    }

    /** A client appeared (the phone was paired): an old failure goes. */
    fun onPaired() {
        _state.update { it.copy(failure = null, message = null) }
    }

    fun set(field: ProfileField, value: String) {
        _state.update {
            it.copy(
                values = it.values + (field to value), problems = emptyList(), fieldProblems = emptyMap(),
                failure = null, message = null, added = false,
            )
        }
        if (field == ProfileField.Material) loadParents(value.trim())
    }

    /** The values the form sends to the Hub. */
    fun values(): JsonObject = formValues(_state.value.values)

    /** The entry the old way would post (a Hub without the form route). */
    fun entry(): JsonObject = buildProfileEntry(_state.value.values)

    fun save() {
        val s = _state.value
        if (!s.canSave) return
        val values = s.values
        _state.update {
            it.copy(saving = true, added = false, problems = emptyList(), fieldProblems = emptyMap(), failure = null, message = null)
        }
        viewModelScope.launch {
            try {
                try {
                    api.addLocalEntryForm(formValues(values))
                    // the form is empty again, so a second tap cannot add the same entry twice
                    _state.update {
                        AddProfileUiState(
                            added = true, entriesOpen = it.entriesOpen, entries = it.entries,
                            entriesUnavailable = it.entriesUnavailable,
                        )
                    }
                    if (_state.value.entriesOpen) loadEntries()
                } catch (e: ApiError) {
                    if (e.status != ProfileApi.NOT_FOUND) throw e
                    // an older Hub has no form route: the app builds the entry itself, as it always did
                    api.addLocalProfile(buildProfileEntry(values))
                    _state.value = AddProfileUiState(saved = true)
                }
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

    // --- See custom entries ---

    /** "See custom entries" opens and closes the list; the first opening reads it. */
    fun toggleEntries() {
        val open = !_state.value.entriesOpen
        _state.update { it.copy(entriesOpen = open) }
        if (open && _state.value.entries == null) loadEntries()
    }

    fun loadEntries() {
        _state.update { it.copy(entriesLoading = true, entriesFailure = null, entriesMessage = null) }
        viewModelScope.launch {
            try {
                val list = api.localLibrary()
                _state.update { it.copy(entries = list, entriesLoading = false, entriesUnavailable = false) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: ApiError) {
                if (e.status == ProfileApi.NOT_FOUND) {
                    _state.update { it.copy(entriesLoading = false, entriesUnavailable = true) }
                } else {
                    _state.update { entriesFailed(it.copy(entriesLoading = false), e) }
                }
            } catch (e: Exception) {
                _state.update { entriesFailed(it.copy(entriesLoading = false), e) }
            }
        }
    }

    fun askRemove(entry: LocalEntry) = _state.update { if (it.removing) it else it.copy(removeAsk = entry) }

    /** Leaving the question is refused while the removal is being written. */
    fun cancelRemove() = _state.update { if (it.removing) it else it.copy(removeAsk = null) }

    fun confirmRemove() {
        val ask = _state.value.removeAsk ?: return
        if (_state.value.removing) return
        _state.update { it.copy(removing = true, entriesFailure = null, entriesMessage = null) }
        viewModelScope.launch {
            try {
                api.removeLocalEntry(ask.id)
            } catch (e: CancellationException) {
                throw e
            } catch (e: ApiError) {
                // 404: it is gone already, which is what was asked for
                if (e.status != ProfileApi.NOT_FOUND) _state.update { entriesFailed(it, e) }
            } catch (e: Exception) {
                _state.update { entriesFailed(it, e) }
            }
            _state.update { it.copy(removing = false, removeAsk = null) }
            loadEntries()
        }
    }

    private fun entriesFailed(s: AddProfileUiState, e: Exception): AddProfileUiState {
        val (failure, message) = failureOf(e)
        return s.copy(entriesFailure = failure, entriesMessage = message)
    }

    private fun failureOf(e: Exception): Pair<SaveFailure, String?> = when {
        e is FingerprintMismatch -> SaveFailure.CertificateChanged to null
        e !is ApiError -> SaveFailure.Unknown to null
        e.code == "offline" -> SaveFailure.Unreachable to null
        e.code == "local_network" -> SaveFailure.Message to LOCAL_NETWORK_MESSAGE
        e.code == "unauthorized" -> SaveFailure.NotPaired to null
        else -> SaveFailure.Message to e.message
    }

    private fun failed(s: AddProfileUiState, e: Exception): AddProfileUiState {
        if (e is ApiError && e.code == "invalid_entry") {
            // the Hub names the fields of the form it refused: each is shown under its field
            val named = KitWire.problems(e)
            if (named.isNotEmpty()) {
                val byField = named.mapNotNull { p -> fieldOfKey(p.field)?.let { it to p.text } }.toMap()
                val rest = named.filter { fieldOfKey(it.field) == null }.map { it.text }.filter { it.isNotBlank() }
                return s.copy(problems = rest, fieldProblems = byField)
            }
            // the old way's problems are one text each
            val list = (e.extra["problems"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
                .ifEmpty { listOf(e.message) }
            return s.copy(problems = list, fieldProblems = list.mapNotNull { p -> fieldOf(p)?.let { it to p } }.toMap())
        }
        val (failure, message) = failureOf(e)
        return s.copy(failure = failure, message = message)
    }

    companion object {
        internal const val PARENTS_DEBOUNCE_MS = 500L
    }
}

/** The field a problem of the form's answer names (`{field, text}`); null when it names none of the form's. */
internal fun fieldOfKey(key: String): ProfileField? = when (key.trim().lowercase()) {
    "brand", "vendor" -> ProfileField.Vendor
    "name", "product", "line" -> ProfileField.Line
    "material" -> ProfileField.Material
    "nozzle_min" -> ProfileField.NozzleMin
    "nozzle_max" -> ProfileField.NozzleMax
    "bed_min" -> ProfileField.BedMin
    "bed_max" -> ProfileField.BedMax
    "density" -> ProfileField.Density
    "max_volumetric_speed" -> ProfileField.MaxVolumetric
    "bambu_parent" -> ProfileField.Parent
    "notes" -> ProfileField.Notes
    else -> null
}

/** The field an old-way problem text names, by the entry key it quotes (`fields.filament_density ...`); null when it names none. */
internal fun fieldOf(problem: String): ProfileField? {
    val p = problem.lowercase()
    return when {
        "volumetric" in p -> ProfileField.MaxVolumetric
        "density" in p -> ProfileField.Density
        "nozzle" in p -> ProfileField.NozzleMin
        "bed" in p -> ProfileField.BedMin
        "parent" in p -> ProfileField.Parent
        "notes" in p -> ProfileField.Notes
        "vendor" in p -> ProfileField.Vendor
        "product" in p -> ProfileField.Line
        "material" in p -> ProfileField.Material
        else -> null
    }
}

/**
 * The values the form sends (R83 section 10.1): brand, name and material, and each optional one that was typed. A
 * number goes as a number when it reads as one; anything else goes as typed, so the Hub says what is wrong with it.
 * The app never builds the entry's text.
 */
internal fun formValues(values: Map<ProfileField, String>): JsonObject {
    fun v(f: ProfileField): String? = values[f]?.trim()?.takeIf { it.isNotEmpty() }
    fun number(f: ProfileField): JsonPrimitive? = v(f)?.let { t -> t.toBigDecimalOrNull()?.let { JsonPrimitive(it) } ?: JsonPrimitive(t) }
    val out = linkedMapOf<String, JsonElement>(
        "brand" to JsonPrimitive(v(ProfileField.Vendor).orEmpty()),
        "name" to JsonPrimitive(v(ProfileField.Line).orEmpty()),
        "material" to JsonPrimitive(v(ProfileField.Material).orEmpty()),
    )
    number(ProfileField.NozzleMin)?.let { out["nozzle_min"] = it }
    number(ProfileField.NozzleMax)?.let { out["nozzle_max"] = it }
    number(ProfileField.BedMin)?.let { out["bed_min"] = it }
    number(ProfileField.BedMax)?.let { out["bed_max"] = it }
    number(ProfileField.Density)?.let { out["density"] = it }
    number(ProfileField.MaxVolumetric)?.let { out["max_volumetric_speed"] = it }
    v(ProfileField.Parent)?.let { out["bambu_parent"] = JsonPrimitive(it) }
    v(ProfileField.Notes)?.let { out["notes"] = JsonPrimitive(it) }
    return JsonObject(out)
}

/**
 * The library entry the old way posts (a Hub without the form route; schema_version 1). Values are trimmed; empty fields
 * are left out. Numbers go into `fields` as one-element string arrays (the nozzle range as its low and high ends, one
 * typed end standing for both); the bed range and notes into `published_ranges`.
 */
internal fun buildProfileEntry(values: Map<ProfileField, String>): JsonObject {
    fun v(f: ProfileField): String? = values[f]?.trim()?.takeIf { it.isNotEmpty() }
    fun one(s: String) = JsonArray(listOf(JsonPrimitive(s)))
    val nozzleLow = v(ProfileField.NozzleMin) ?: v(ProfileField.NozzleMax)
    val nozzleHigh = v(ProfileField.NozzleMax) ?: v(ProfileField.NozzleMin)
    val bedLow = v(ProfileField.BedMin) ?: v(ProfileField.BedMax)
    val bedHigh = v(ProfileField.BedMax) ?: v(ProfileField.BedMin)
    val fields = listOfNotNull(
        nozzleLow?.let { "nozzle_temperature_range_low" to one(it) },
        nozzleHigh?.let { "nozzle_temperature_range_high" to one(it) },
        v(ProfileField.Density)?.let { "filament_density" to one(it) },
        v(ProfileField.MaxVolumetric)?.let { "filament_max_volumetric_speed" to one(it) },
    ).toMap()
    val ranges = listOfNotNull(
        bedLow?.let { low -> "bed_all_plates" to JsonPrimitive(if (low == bedHigh) low else "$low-$bedHigh") },
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
