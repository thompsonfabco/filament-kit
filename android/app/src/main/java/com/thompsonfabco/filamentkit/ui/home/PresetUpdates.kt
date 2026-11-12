package com.thompsonfabco.filamentkit.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.AcceptedUpdates
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.PresetUpdate
import com.thompsonfabco.filamentkit.net.PresetUpdates
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The server calls the Updates dialog needs (FB-041); [of] wraps the paired [Api]. */
interface PresetUpdatesBackend {
    suspend fun list(): PresetUpdates
    suspend fun accept(stamp: String, names: List<String>): AcceptedUpdates
    suspend fun restoreDeleted()

    companion object {
        fun of(api: Api): PresetUpdatesBackend = object : PresetUpdatesBackend {
            override suspend fun list() = api.presetUpdates()
            override suspend fun accept(stamp: String, names: List<String>) = api.acceptPresetUpdates(stamp, names)
            override suspend fun restoreDeleted() = api.restoreDeletedPresets()
        }
    }
}

object PresetUpdateTexts {
    const val TITLE = "Preset updates"
    const val INTRO = "A newer build would change these presets already in your slicers. Nothing is written over until you accept."
    const val NONE = "No preset in your slicers needs an update."
    const val RESTORE = "Restore presets deleted in Bambu Studio"
    const val RESTORED = "The next build brings them back; your PC installs it at its next sync."
    const val CHANGED = "The updates changed since this list (a newer build came). Nothing was accepted; check the new list."
    const val LOADING = "Loading updates…"

    fun accept(n: Int) = "Accept $n update${if (n == 1) "" else "s"}"
    fun nothingWaiting(accepted: Int) = "Nothing waiting; $accepted accepted, written at the next PC sync."
    fun accepted(n: Int) = "$n accepted: your PC writes them over the presets at its next sync."
    fun slicer(target: String) = when (target) {
        "bambu_studio", "bambu" -> "Bambu Studio"
        "orca_slicer", "orca" -> "OrcaSlicer"
        else -> target
    }
    fun row(u: PresetUpdate) = "${u.name} (${slicer(u.target)}): " + u.keys.joinToString(", ").ifEmpty { "changed values" }
    fun yours(names: List<String>) = "Never written over (your own preset of that name): ${names.joinToString(", ")}"
    fun error(e: Exception): String = when {
        e is ApiError && e.code == "updates_changed" -> CHANGED
        e is ApiError && e.code == "module_off" -> "The presets module is turned off on this server."
        e is ApiError && e.code == "offline" -> "Could not reach the server. Check that you are on the same network."
        e is ApiError -> e.message
        else -> "Unexpected response from the server"
    }
}

data class PresetUpdatesState(
    val list: PresetUpdates? = null,
    val loading: Boolean = false,
    val busy: Boolean = false,
    val message: String? = null,
    val messageIsError: Boolean = false,
    val unauthorized: Boolean = false,
)

/** The Updates dialog: the list, Accept (exactly the names shown), Restore deleted presets. */
class PresetUpdatesViewModel(private val backend: PresetUpdatesBackend) : ViewModel() {
    private val _state = MutableStateFlow(PresetUpdatesState())
    val state: StateFlow<PresetUpdatesState> = _state.asStateFlow()

    /** Loads the list again; [keepMessage] keeps the outcome of the action that asked for the reload. */
    fun load(keepMessage: Boolean = false) {
        _state.update { it.copy(loading = true, message = if (keepMessage) it.message else null) }
        viewModelScope.launch {
            run({ _state.update { it.copy(loading = false) } }) {
                val l = backend.list()
                _state.update { it.copy(list = l) }
            }
        }
    }

    /** Accepts the updates now shown, and nothing else; a refused list (a newer build) is loaded again. */
    fun accept() {
        val s = _state.value
        val l = s.list ?: return
        val stamp = l.stamp ?: return
        val names = l.waiting.map { it.name }
        if (names.isEmpty() || s.busy) return
        _state.update { it.copy(busy = true, message = null) }
        viewModelScope.launch {
            run({ _state.update { it.copy(busy = false) }; load(keepMessage = true) }) {
                val r = backend.accept(stamp, names)
                _state.update { it.copy(message = PresetUpdateTexts.accepted(r.accepted.size), messageIsError = false) }
            }
        }
    }

    fun restoreDeleted() {
        if (_state.value.busy) return
        _state.update { it.copy(busy = true, message = null) }
        viewModelScope.launch {
            run({ _state.update { it.copy(busy = false) } }) {
                backend.restoreDeleted()
                _state.update { it.copy(message = PresetUpdateTexts.RESTORED, messageIsError = false) }
            }
        }
    }

    private suspend fun run(finally: () -> Unit, block: suspend () -> Unit) {
        try {
            block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            val unauthorized = e is ApiError && e.code == "unauthorized"
            _state.update {
                it.copy(message = PresetUpdateTexts.error(e), messageIsError = true, unauthorized = it.unauthorized || unauthorized)
            }
        } finally {
            finally()
        }
    }
}

@Composable
fun PresetUpdatesDialog(vm: PresetUpdatesViewModel, onClose: () -> Unit) {
    val s by vm.state.collectAsState()
    val l = s.list
    AlertDialog(
        onDismissRequest = { if (!s.busy) onClose() },
        title = { Text(PresetUpdateTexts.TITLE) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                when {
                    l == null && s.loading -> Text(PresetUpdateTexts.LOADING)
                    l == null -> Unit
                    l.waiting.isEmpty() -> Text(
                        if (l.accepted > 0) PresetUpdateTexts.nothingWaiting(l.accepted) else PresetUpdateTexts.NONE,
                        style = MaterialTheme.typography.bodySmall,
                    )
                    else -> {
                        Text(PresetUpdateTexts.INTRO, style = MaterialTheme.typography.bodySmall)
                        l.waiting.forEach { Text("• " + PresetUpdateTexts.row(it)) }
                        Button(onClick = vm::accept, enabled = !s.busy && !s.loading) {
                            Text(if (s.busy) "Accepting…" else PresetUpdateTexts.accept(l.waiting.size))
                        }
                    }
                }
                if (l != null && l.yours.isNotEmpty()) {
                    Text(PresetUpdateTexts.yours(l.yours), style = MaterialTheme.typography.bodySmall)
                }
                s.message?.let { Text(it, color = if (s.messageIsError) MaterialTheme.colorScheme.error else Color.Unspecified) }
                OutlinedButton(onClick = vm::restoreDeleted, enabled = !s.busy && !s.unauthorized) {
                    Text(PresetUpdateTexts.RESTORE)
                }
            }
        },
        confirmButton = { TextButton(onClick = onClose, enabled = !s.busy) { Text("Close") } },
    )
}
