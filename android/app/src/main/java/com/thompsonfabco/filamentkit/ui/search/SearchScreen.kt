package com.thompsonfabco.filamentkit.ui.search

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.ui.spool.SpoolSummaryRow
import com.thompsonfabco.filamentkit.ui.spool.toSpoolSummary
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

data class SearchUi(
    val query: String = "",
    val sealedOnly: Boolean = false,
    val busy: Boolean = false,
    val searched: Boolean = false,
    val results: List<JsonObject> = emptyList(),
    val error: String? = null,
    /** Expected and presented certificate fingerprints when the server's certificate changed. */
    val mismatch: Pair<String, String>? = null,
    val unauthorized: Boolean = false,
)

/** Spool search; [search] is `api.search(q, sealedOnly)`. */
class SearchViewModel(private val search: suspend (q: String, sealedOnly: Boolean) -> List<JsonObject>) : ViewModel() {
    private val _state = MutableStateFlow(SearchUi())
    val state: StateFlow<SearchUi> = _state.asStateFlow()
    private var job: Job? = null
    private var typing: Job? = null

    /** A pause in typing searches by itself; clearing the box clears the results. */
    fun setQuery(q: String) {
        _state.update { it.copy(query = q) }
        typing?.cancel()
        if (q.isBlank()) {
            job?.cancel()
            _state.update { it.copy(busy = false, searched = false, results = emptyList()) }
        } else if (q.trim().length >= MIN_TYPED) {
            typing = viewModelScope.launch {
                delay(TYPING_PAUSE_MS)
                search()
            }
        }
    }

    fun setSealedOnly(on: Boolean) {
        _state.update { it.copy(sealedOnly = on) }
        if (_state.value.searched) search()
    }

    fun search() {
        val s = _state.value
        val q = s.query.trim()
        if (q.isEmpty()) return
        typing?.cancel()
        job?.cancel()
        _state.value = s.copy(busy = true, error = null, mismatch = null, unauthorized = false)
        job = viewModelScope.launch {
            _state.value = try {
                _state.value.copy(busy = false, searched = true, results = search(q, s.sealedOnly))
            } catch (e: CancellationException) {
                throw e
            } catch (e: FingerprintMismatch) {
                _state.value.copy(busy = false, results = emptyList(), mismatch = e.expected to e.actual)
            } catch (e: ApiError) {
                when (e.code) {
                    "unauthorized" -> _state.value.copy(busy = false, results = emptyList(), unauthorized = true)
                    "offline" -> _state.value.copy(busy = false, error = "Could not reach the server. Check that you are on the same network.")
                    else -> _state.value.copy(busy = false, error = e.message)
                }
            } catch (_: Exception) {
                _state.value.copy(busy = false, error = "Unexpected response from the server")
            }
        }
    }

    private companion object {
        const val MIN_TYPED = 2
        const val TYPING_PAUSE_MS = 400L
    }
}

/** Query box and results; tapping a result calls [onOpenSpool] with the spool (it opens the spool card). */
@Composable
fun SearchScreen(
    vm: SearchViewModel,
    onOpenSpool: (JsonObject) -> Unit,
    onPairAgain: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val ui by vm.state.collectAsStateWithLifecycle()
    Column(modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onBack) { Text("Back") }
            Text("Search spools", style = MaterialTheme.typography.headlineSmall)
        }
        OutlinedTextField(
            value = ui.query,
            onValueChange = vm::setQuery,
            label = { Text("Brand, material, colour…") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = KeyboardActions(onSearch = { vm.search() }),
            modifier = Modifier.fillMaxWidth(),
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = ui.sealedOnly, onCheckedChange = vm::setSealedOnly)
            Text("Sealed spools only")
        }
        Button(onClick = vm::search, enabled = !ui.busy && ui.query.isNotBlank()) {
            Text(if (ui.busy) "Searching…" else "Search")
        }
        ui.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        ui.mismatch?.let { (expected, actual) ->
            Text("The server's certificate changed.", style = MaterialTheme.typography.titleMedium)
            Text("Expected: $expected")
            Text("Got: $actual")
            Button(onClick = onPairAgain) { Text("Pair again") }
        }
        if (ui.unauthorized) {
            Text("This phone is no longer paired with the server.", color = MaterialTheme.colorScheme.error)
            Button(onClick = onPairAgain) { Text("Pair again") }
        }
        if (ui.searched && ui.results.isEmpty() && ui.error == null) Text("No spools found.")
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(ui.results) { spool ->
                Column(Modifier.fillMaxWidth().clickable { onOpenSpool(spool) }.padding(vertical = 8.dp)) {
                    SpoolSummaryRow(spool.toSpoolSummary())
                }
            }
        }
    }
}
