package com.thompsonfabco.filamentkit.ui.search

import android.content.Context
import android.content.Intent
import android.nfc.NfcAdapter
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwIconButton
import com.thompsonfabco.filamentkit.ui.components.SwProgress
import com.thompsonfabco.filamentkit.ui.spool.HubFailure
import com.thompsonfabco.filamentkit.ui.spool.HubFailureNotice
import com.thompsonfabco.filamentkit.ui.spool.SpoolPanel
import com.thompsonfabco.filamentkit.ui.spool.SpoolRow
import com.thompsonfabco.filamentkit.ui.spool.SpoolSummary
import com.thompsonfabco.filamentkit.ui.spool.hubFailure
import com.thompsonfabco.filamentkit.ui.spool.toSpoolSummary
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

/**
 * Spools (05 7.1). [searched] is the query the [results] answer, for "No spools match "petg"."; [busy] is a search
 * running, while the results of the last one stay.
 */
data class SearchUi(
    val query: String = "",
    val sealedOnly: Boolean = false,
    val busy: Boolean = false,
    val searched: String? = null,
    val results: List<SpoolSummary> = emptyList(),
    val failure: HubFailure? = null,
)

/** Spool search; [search] is `api.search(q, sealedOnly)`, asked of the session's current client at each call. */
class SearchViewModel(
    private val pauseMs: Long = TYPING_PAUSE_MS,
    private val search: suspend (q: String, sealedOnly: Boolean) -> List<JsonObject>,
) : ViewModel() {
    private val _state = MutableStateFlow(SearchUi())
    val state: StateFlow<SearchUi> = _state.asStateFlow()
    private var job: Job? = null
    private var typing: Job? = null

    /** A pause in typing searches by itself once two letters are typed; clearing the box clears the results. */
    fun setQuery(q: String) {
        _state.update { it.copy(query = q) }
        typing?.cancel()
        if (q.isBlank()) {
            job?.cancel()
            _state.update { it.copy(busy = false, searched = null, results = emptyList(), failure = null) }
        } else if (q.trim().length >= MIN_TYPED) {
            typing = viewModelScope.launch {
                delay(pauseMs)
                search()
            }
        }
    }

    fun setSealedOnly(on: Boolean) {
        _state.update { it.copy(sealedOnly = on) }
        if (_state.value.query.isNotBlank()) search()
    }

    /** At once: the keyboard's search key, the chip, Try again. */
    fun search() {
        val s = _state.value
        val q = s.query.trim()
        if (q.isEmpty()) return
        typing?.cancel()
        job?.cancel()
        _state.update { it.copy(busy = true) }
        job = viewModelScope.launch {
            try {
                val found = search(q, s.sealedOnly).map { it.toSpoolSummary() }
                _state.update { it.copy(busy = false, searched = q, results = found, failure = null) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // the rows of the last answer stay under the notice
                _state.update { it.copy(busy = false, failure = hubFailure(e)) }
            }
        }
    }

    fun clear() = setQuery("")

    private companion object {
        const val MIN_TYPED = 2
        const val TYPING_PAUSE_MS = 300L
    }
}

/** Whether the phone can read tags, for the tag hint (05 7.1). */
enum class NfcState { Ready, Off, Missing }

internal fun nfcStateOf(context: Context): NfcState {
    val adapter = NfcAdapter.getDefaultAdapter(context) ?: return NfcState.Missing
    return if (adapter.isEnabled) NfcState.Ready else NfcState.Off
}

/** The phone's NFC state, read again whenever the screen is resumed (the person may switch NFC on in the system settings). */
@Composable
internal fun rememberNfcState(): NfcState {
    val context = LocalContext.current
    var state by remember { mutableStateOf(nfcStateOf(context)) }
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_RESUME) state = nfcStateOf(context) }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer) }
    }
    return state
}

/** Opens the system's NFC settings. */
internal fun openNfcSettings(context: Context) {
    context.startActivity(Intent(Settings.ACTION_NFC_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
}

/**
 * The Spools screen (05 7.1): the search field, the Sealed only chip, the tag hint and the results. [onOpenSpool] opens
 * the spool screen with the row's summary. There is no search button: a search runs after a pause in typing and on
 * the keyboard's search key.
 */
@Composable
fun SearchScreen(
    vm: SearchViewModel,
    onOpenSpool: (SpoolSummary) -> Unit,
    onPairAgain: () -> Unit,
    modifier: Modifier = Modifier,
    nfc: NfcState = rememberNfcState(),
    onNfcSettings: (() -> Unit)? = null,
) {
    val ui by vm.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val space = SpoolwardenTheme.space
    val colors = SpoolwardenTheme.colors
    Column(modifier.fillMaxSize()) {
        // the progress line sits right under the field; the results stay while it runs
        Column(
            Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(space.s4),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Column(
                Modifier.widthIn(max = SpoolwardenTheme.sizes.columnMax).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(space.s3),
            ) {
                Column {
                    OutlinedTextField(
                        value = ui.query,
                        onValueChange = vm::setQuery,
                        label = { Text(stringResource(R.string.spools_search_label)) },
                        leadingIcon = { SwIcon(R.drawable.sw_ic_search, null, tint = colors.muted) },
                        trailingIcon = if (ui.query.isNotEmpty()) {
                            { SwIconButton(R.drawable.sw_ic_close, stringResource(R.string.common_clear_search), vm::clear) }
                        } else {
                            null
                        },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                        keyboardActions = KeyboardActions(onSearch = { vm.search() }),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    if (ui.busy) SwProgress(null, Modifier.padding(top = space.s1))
                }
                // the whole chip toggles
                FilterChip(
                    selected = ui.sealedOnly,
                    onClick = { vm.setSealedOnly(!ui.sealedOnly) },
                    label = { Text(stringResource(R.string.spools_sealed_only), style = MaterialTheme.typography.labelLarge) },
                    modifier = Modifier.heightIn(min = SpoolwardenTheme.sizes.row),
                    shape = SpoolwardenTheme.shapes.r,
                    leadingIcon = if (ui.sealedOnly) {
                        { SwIcon(R.drawable.sw_ic_check, null) }
                    } else {
                        null
                    },
                    colors = FilterChipDefaults.filterChipColors(
                        containerColor = colors.surface, labelColor = colors.text,
                        selectedContainerColor = colors.accentSoft, selectedLabelColor = colors.accentText,
                        selectedLeadingIconColor = colors.accentText,
                    ),
                    border = FilterChipDefaults.filterChipBorder(
                        enabled = true, selected = ui.sealedOnly, borderColor = colors.borderStrong,
                        selectedBorderColor = colors.accentText, borderWidth = SpoolwardenTheme.sizes.hairline,
                        selectedBorderWidth = SpoolwardenTheme.sizes.hairline,
                    ),
                )
                if (ui.query.isBlank()) TagHint(nfc, onNfcSettings ?: { openNfcSettings(context) })
                ui.failure?.let { HubFailureNotice(it, onPairAgain, onTryAgain = if (ui.query.isNotBlank()) vm::search else null) }
                val searched = ui.searched
                when {
                    searched != null && ui.results.isEmpty() && !ui.busy -> Column {
                        Text(stringResource(R.string.spools_empty, searched), style = MaterialTheme.typography.bodyLarge)
                        if (ui.sealedOnly) {
                            SwButton(stringResource(R.string.spools_clear_sealed), { vm.setSealedOnly(false) }, kind = SwButtonKind.Quiet)
                        }
                    }
                    ui.results.isNotEmpty() -> SpoolPanel {
                        ui.results.forEachIndexed { i, spool ->
                            if (i > 0) HorizontalDivider(color = colors.border, thickness = SpoolwardenTheme.sizes.hairline)
                            SpoolRow(spool, onClick = { onOpenSpool(spool) })
                        }
                    }
                }
            }
        }
    }
}

/** The line under the chip while nothing is typed: how to open a spool by its tag, or why the phone cannot. */
@Composable
private fun TagHint(nfc: NfcState, onNfcSettings: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    Row(horizontalArrangement = Arrangement.spacedBy(space.s3), verticalAlignment = Alignment.CenterVertically) {
        SwIcon(R.drawable.sw_ic_tag, null, tint = colors.muted)
        Column(Modifier.weight(1f)) {
            Text(
                stringResource(
                    when (nfc) {
                        NfcState.Ready -> R.string.spools_tag_hint
                        NfcState.Off -> R.string.spools_nfc_off
                        NfcState.Missing -> R.string.spools_no_nfc
                    },
                ),
                style = MaterialTheme.typography.bodyMedium, color = colors.muted,
            )
            if (nfc == NfcState.Off) SwButton(stringResource(R.string.spools_nfc_settings), onNfcSettings, kind = SwButtonKind.Quiet)
        }
    }
}
