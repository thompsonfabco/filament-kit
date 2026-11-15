package com.thompsonfabco.filamentkit.ui.presets

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.BuildRequested
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LOCAL_NETWORK_MESSAGE
import com.thompsonfabco.filamentkit.net.ParentList
import com.thompsonfabco.filamentkit.net.ProfileLine
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.net.UncoveredFilament
import com.thompsonfabco.filamentkit.ui.profile.SaveFailure
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/** The calls the Slicer presets screen makes; [of] adapts the real [Api] (tests pass a fake). */
interface PresetsBackend {
    suspend fun status(): ProfileStatus
    suspend fun lines(): List<ProfileLine>
    suspend fun uncovered(): List<UncoveredFilament>
    suspend fun parents(material: String): ParentList
    suspend fun setLineParent(lineId: String, parent: String): ProfileLine
    suspend fun addToLine(line: String, id: Int): ProfileLine
    suspend fun newLine(name: String, vendor: String, id: Int, template: String): ProfileLine
    suspend fun build(): BuildRequested

    companion object {
        /** Calls go to whatever [current] returns at that moment (see `IntakeApi.of`). */
        fun of(current: () -> Api): PresetsBackend = object : PresetsBackend {
            override suspend fun status() = current().profileStatus()
            override suspend fun lines() = current().profileLines()
            override suspend fun uncovered() = current().uncoveredFilaments()
            override suspend fun parents(material: String) = current().parents(material)
            override suspend fun setLineParent(lineId: String, parent: String) = current().setLineParent(lineId, parent)
            override suspend fun addToLine(line: String, id: Int) = current().addFilamentsToLine(line, listOf(id))
            override suspend fun newLine(name: String, vendor: String, id: Int, template: String) =
                current().createLine(name, vendor, listOf(id), template)
            override suspend fun build() = current().buildPresets()
        }
    }
}

/** A failed Hub call: [kind] says how the screen words it; [message] is the Hub's own (kind Message); [field] the field a 400 names. */
data class Fail(val kind: SaveFailure, val message: String? = null, val field: String? = null)

internal fun failOf(e: Exception): Fail = when {
    e is FingerprintMismatch -> Fail(SaveFailure.CertificateChanged)
    e !is ApiError -> Fail(SaveFailure.Unknown)
    e.code == "offline" -> Fail(SaveFailure.Unreachable)
    e.code == "local_network" -> Fail(SaveFailure.Message, LOCAL_NETWORK_MESSAGE)
    e.code == "unauthorized" -> Fail(SaveFailure.NotPaired)
    else -> Fail(SaveFailure.Message, e.message, (e.extra["field"] as? JsonPrimitive)?.contentOrNull)
}

/** What a card of "Filaments without a preset line" is doing. */
enum class CardBusy { Adding, Creating }

/**
 * One filament's card. [line] is the line chosen to add to (null: the first of the brand's); the new-line form is [newLineOpen]
 * with [name], and [template] chosen from [templates] (null until they are read).
 */
data class FilamentCard(
    val line: String? = null,
    val newLineOpen: Boolean = false,
    val name: String = "",
    val template: String? = null,
    val templates: ParentList? = null,
    val busy: CardBusy? = null,
    val fail: Fail? = null,
)

/** The parent choice open for [lineId]: [parents] are the Bambu Studio parents of its material (null while loading). */
data class ParentEdit(
    val lineId: String,
    val line: String,
    val material: String,
    val current: String?,
    val parents: ParentList? = null,
    val query: String = "",
    val picked: String? = null,
    val saving: Boolean = false,
    val fail: Fail? = null,
) {
    /** The parents whose name has every word typed in "Find a parent". */
    val matches: List<String>
        get() {
            val words = query.lowercase().split(' ').filter { it.isNotEmpty() }
            return parents?.parents.orEmpty().filter { p -> words.all { it in p.lowercase() } }
        }
}

/** What happened that the screen tells in a toast, once (the card has left the list). */
data class Done(val created: Boolean, val name: String)

/** The answer to Build now. */
sealed interface BuildNote {
    data object Asked : BuildNote
    data class Failed(val fail: Fail) : BuildNote
}

data class PresetsUiState(
    val status: ProfileStatus? = null,
    /** The status read failed or has not come: the rows say it is not available. */
    val statusLoaded: Boolean = false,
    val lines: List<ProfileLine>? = null,
    val linesFail: Fail? = null,
    /** How many lines are listed (the list is paged at [PAGE]). */
    val shown: Int = PAGE,
    val uncovered: List<UncoveredFilament>? = null,
    val uncoveredFail: Fail? = null,
    val cards: Map<Int, FilamentCard> = emptyMap(),
    val building: Boolean = false,
    val buildNote: BuildNote? = null,
    val edit: ParentEdit? = null,
    /** The line whose parent was just saved (its row says so). */
    val savedFor: String? = null,
    val done: Done? = null,
) {
    fun card(id: Int): FilamentCard = cards[id] ?: FilamentCard()

    companion object {
        const val PAGE = 50
    }
}

/** Slicer presets (05-android-app 11.2): build status, filaments without a line, Build now and the Product lines panel. */
class PresetsViewModel(private val api: PresetsBackend) : ViewModel() {
    private val _state = MutableStateFlow(PresetsUiState())
    val state: StateFlow<PresetsUiState> = _state.asStateFlow()

    /** The Bambu Studio parents already read, by material (a card and the sheet ask the same list); only a synced list is kept. */
    private val parentCache = mutableMapOf<String, ParentList>()

    init {
        reload()
    }

    /** Reads the status, the lines and the filaments without a line again. */
    fun reload() {
        loadStatus()
        loadLines()
        loadUncovered()
    }

    private fun loadStatus() {
        viewModelScope.launch {
            val status = try {
                api.status()
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                null
            }
            _state.update { it.copy(status = status, statusLoaded = true) }
        }
    }

    fun loadLines() {
        _state.update { it.copy(lines = null, linesFail = null) }
        refreshLines()
    }

    private fun refreshLines() {
        viewModelScope.launch {
            try {
                val lines = api.lines()
                _state.update { it.copy(lines = lines, linesFail = null) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(lines = it.lines ?: emptyList(), linesFail = failOf(e)) }
            }
        }
    }

    fun showMore() = _state.update { it.copy(shown = it.shown + PresetsUiState.PAGE) }

    fun loadUncovered() {
        _state.update { it.copy(uncovered = null, uncoveredFail = null) }
        viewModelScope.launch {
            try {
                val list = api.uncovered()
                _state.update { s ->
                    s.copy(
                        uncovered = list, uncoveredFail = null,
                        cards = list.associate { f -> f.id to (s.cards[f.id] ?: FilamentCard(name = suggestedName(f))) },
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(uncovered = emptyList(), uncoveredFail = failOf(e)) }
            }
        }
    }

    private fun updateCard(id: Int, change: (FilamentCard) -> FilamentCard) =
        _state.update { s -> s.copy(cards = s.cards + (id to change(s.card(id)))) }

    fun chooseLine(id: Int, line: String) = updateCard(id) { it.copy(line = line, fail = null) }

    fun setName(id: Int, name: String) = updateCard(id) { it.copy(name = name, fail = null) }

    fun chooseTemplate(id: Int, template: String) = updateCard(id) { it.copy(template = template, fail = null) }

    /** Opens or closes the new-line form of [filament]; opening reads the parents for its material. */
    fun toggleNewLine(filament: UncoveredFilament) {
        val open = !_state.value.card(filament.id).newLineOpen
        updateCard(filament.id) { it.copy(newLineOpen = open) }
        if (open && _state.value.card(filament.id).templates == null) {
            viewModelScope.launch {
                val list = try {
                    parentsFor(filament.material)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    updateCard(filament.id) { it.copy(fail = failOf(e)) }
                    return@launch
                }
                updateCard(filament.id) {
                    it.copy(templates = list, template = it.template ?: defaultTemplate(list, filament.material))
                }
            }
        }
    }

    private suspend fun parentsFor(material: String): ParentList =
        parentCache[material] ?: api.parents(material).also { if (it.synced) parentCache[material] = it }

    /** Adds [filament] to the line chosen on its card (the first of its brand's lines when none was chosen). */
    fun addToLine(filament: UncoveredFilament) {
        val card = _state.value.card(filament.id)
        val line = card.line ?: filament.linesForVendor.firstOrNull() ?: return
        if (card.busy != null) return
        updateCard(filament.id) { it.copy(busy = CardBusy.Adding, fail = null) }
        viewModelScope.launch {
            try {
                api.addToLine(line, filament.id)
                left(filament.id, Done(created = false, name = line))
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                updateCard(filament.id) { it.copy(busy = null, fail = failOf(e)) }
            }
        }
    }

    /** Starts a line named on the card from [filament], on the template chosen there. */
    fun createLine(filament: UncoveredFilament) {
        val card = _state.value.card(filament.id)
        val template = card.template ?: return
        val name = card.name.trim()
        if (card.busy != null || name.isEmpty()) return
        updateCard(filament.id) { it.copy(busy = CardBusy.Creating, fail = null) }
        viewModelScope.launch {
            try {
                api.newLine(name, filament.vendor, filament.id, template)
                left(filament.id, Done(created = true, name = name))
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                updateCard(filament.id) { it.copy(busy = null, fail = failOf(e)) }
            }
        }
    }

    /** The filament now has a line: its card goes, the toast is said once, and the lines and the status are read again. */
    private fun left(id: Int, done: Done) {
        _state.update { s -> s.copy(uncovered = s.uncovered?.filter { it.id != id }, cards = s.cards - id, done = done) }
        refreshLines()
        loadStatus()
    }

    /** The screen showed the toast. */
    fun doneShown() = _state.update { it.copy(done = null) }

    /** Asks the Hub for a build now. */
    fun build() {
        if (_state.value.building) return
        _state.update { it.copy(building = true, buildNote = null) }
        viewModelScope.launch {
            try {
                val asked = api.build()
                val note = if (asked.requested) BuildNote.Asked else BuildNote.Failed(Fail(SaveFailure.Message, asked.output))
                _state.update { it.copy(building = false, buildNote = note) }
                loadStatus()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(building = false, buildNote = BuildNote.Failed(failOf(e))) }
            }
        }
    }

    /** Opens the parent sheet for [line], with the parents for its material. */
    fun editParent(line: ProfileLine) {
        val edit = ParentEdit(
            line.lineId, "${line.vendor} ${line.product}", line.material, line.bambuParent, picked = line.bambuParent,
        )
        _state.update { it.copy(edit = edit, savedFor = null) }
        viewModelScope.launch {
            try {
                val list = parentsFor(line.material)
                _state.update { s -> s.copy(edit = s.edit?.takeIf { it.lineId == line.lineId }?.copy(parents = list)) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { s -> s.copy(edit = s.edit?.takeIf { it.lineId == line.lineId }?.copy(fail = failOf(e))) }
            }
        }
    }

    fun findParent(query: String) = _state.update { it.copy(edit = it.edit?.copy(query = query, fail = null)) }

    fun pickParent(parent: String) = _state.update { it.copy(edit = it.edit?.copy(picked = parent, fail = null)) }

    fun closeParent() = _state.update { if (it.edit?.saving == true) it else it.copy(edit = null) }

    /** Saves the picked parent. The Hub's refusal stays in the sheet as given; a save closes it and the row says so. */
    fun saveParent() {
        val edit = _state.value.edit ?: return
        val parent = edit.picked?.takeIf { it.isNotBlank() && it != edit.current } ?: return
        // the Hub refuses a parent it has not reported, so nothing is sent before Slicer Sync has
        if (edit.saving || edit.parents?.synced != true) return
        _state.update { it.copy(edit = it.edit?.copy(saving = true, fail = null)) }
        viewModelScope.launch {
            try {
                val updated = api.setLineParent(edit.lineId, parent)
                _state.update { s ->
                    s.copy(
                        lines = s.lines?.map { if (it.lineId == edit.lineId) updated.copy(presets = it.presets) else it },
                        edit = null, savedFor = edit.lineId,
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(edit = it.edit?.copy(saving = false, fail = failOf(e))) }
            }
        }
    }

    companion object {
        /** "<Brand> <name without its last word>" (the web app's suggestion), the whole name when it has one word. */
        fun suggestedName(f: UncoveredFilament): String {
            val head = f.name.split(" ").dropLast(1).joinToString(" ")
            return "${f.vendor} ${head.ifEmpty { f.name }}"
        }

        /** "Generic <material>" when the Hub has it, else the first parent; null when it has none. */
        fun defaultTemplate(list: ParentList, material: String): String? =
            list.parents.firstOrNull { it == "Generic $material" } ?: list.parents.firstOrNull()
    }
}
