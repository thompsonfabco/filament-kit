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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.alerts.AlertTexts
import com.thompsonfabco.filamentkit.alerts.LowSpool
import com.thompsonfabco.filamentkit.ui.components.DetailPresentation
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwCardDetail
import com.thompsonfabco.filamentkit.ui.components.SwCollection
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwIconButton
import com.thompsonfabco.filamentkit.ui.components.SwPaneLayout
import com.thompsonfabco.filamentkit.ui.components.SwSheetDetail
import com.thompsonfabco.filamentkit.ui.components.ScreenState
import com.thompsonfabco.filamentkit.ui.components.rememberDetailPresentation
import com.thompsonfabco.filamentkit.ui.components.requestDetailFocus
import com.thompsonfabco.filamentkit.ui.spool.HubFailure
import com.thompsonfabco.filamentkit.ui.spool.HubNoticeOf
import com.thompsonfabco.filamentkit.ui.spool.hubFailureText
import com.thompsonfabco.filamentkit.ui.spool.secondsSince
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
import com.thompsonfabco.filamentkit.ui.spool.SpoolTile

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
    /** When the results were read (epoch millis), for the offline notice. */
    val loadedAt: Long? = null,
    /** The "Running low" filter (R80 section 7): the list of spools at or under the Hub's threshold replaces the search. */
    val lowOnly: Boolean = false,
    val low: List<LowSpool> = emptyList(),
    val lowLoaded: Boolean = false,
)

/** Spool search; [search] is `api.search(q, sealedOnly)`, asked of the session's current client at each call. */
class SearchViewModel(
    private val pauseMs: Long = TYPING_PAUSE_MS,
    /** `api.lowSpools()`; null: the Hub has no running-low list, so there is no filter. */
    private val loadLow: (suspend () -> List<LowSpool>)? = null,
    private val search: suspend (q: String, sealedOnly: Boolean) -> List<JsonObject>,
) : ViewModel() {
    private val _state = MutableStateFlow(SearchUi())
    val state: StateFlow<SearchUi> = _state.asStateFlow()
    private var job: Job? = null
    private var typing: Job? = null
    private var lowJob: Job? = null

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
                _state.update { it.copy(busy = false, searched = q, results = found, failure = null, loadedAt = System.currentTimeMillis()) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // the rows of the last answer stay under the notice
                _state.update { it.copy(busy = false, failure = hubFailure(e)) }
            }
        }
    }

    fun clear() = setQuery("")

    /** The "Running low" chip: shows the list of low spools (least first, as the Hub gives it) instead of the search. */
    fun setLowOnly(on: Boolean) {
        _state.update { it.copy(lowOnly = on, failure = if (on) null else it.failure) }
        if (on) loadLowSpools()
    }

    /** Reads the running-low list again (the chip, Try again). */
    fun loadLowSpools() {
        val load = loadLow ?: return
        _state.update { it.copy(busy = true) }
        lowJob?.cancel()
        lowJob = viewModelScope.launch {
            try {
                val spools = load()
                _state.update { it.copy(busy = false, low = spools, lowLoaded = true, failure = null, loadedAt = System.currentTimeMillis()) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(busy = false, failure = hubFailure(e)) }
            }
        }
    }

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
    online: Boolean = true,
    /** How many spools are running low, for the chip "Running low (n)"; null: no chip (the Hub has no such list). */
    lowCount: Int? = null,
    onNfcSettings: (() -> Unit)? = null,
    spoolDetail: (@Composable (spool: SpoolSummary, embedded: Boolean, onClose: () -> Unit) -> Unit)? = null,
) {
    val ui by vm.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val space = SpoolwardenTheme.space
    val colors = SpoolwardenTheme.colors
    val presentation = rememberDetailPresentation()
    val useCardDetail = presentation == DetailPresentation.Card && spoolDetail != null
    val useSheetDetail = presentation == DetailPresentation.Sheet && spoolDetail != null
    val usePaneDetail = presentation == DetailPresentation.Pane && spoolDetail != null
    var expandedIds by rememberSaveable { mutableStateOf(emptyList<Int>()) }
    var sheetSpoolId by rememberSaveable { mutableStateOf<Int?>(null) }
    var cachedSpool by remember { mutableStateOf<SpoolSummary?>(null) }
    val rowFocus = remember { mutableMapOf<Int, FocusRequester>() }
    var returnFocusId by remember { mutableStateOf<Int?>(null) }
    val view = LocalView.current
    LaunchedEffect(returnFocusId) {
        val id = returnFocusId ?: return@LaunchedEffect
        // Wait for the collapsed card row to re-enter the layout and focus tree.
        repeat(2) { withFrameNanos { } }
        rowFocus[id]?.let { requestDetailFocus(it, view) }
        returnFocusId = null
    }
    LaunchedEffect(presentation) {
        if (presentation == DetailPresentation.Screen && spoolDetail != null) {
            val activeId = sheetSpoolId ?: expandedIds.lastOrNull()
            if (activeId != null) {
                val target = ui.results.firstOrNull { it.id == activeId }
                    ?: cachedSpool?.takeIf { it.id == activeId }
                    ?: com.thompsonfabco.filamentkit.ui.spool.SpoolCache.get(activeId)
                sheetSpoolId = null
                expandedIds = emptyList()
                if (target != null) onOpenSpool(target)
            }
        }
    }
    val listBody: @Composable (Modifier) -> Unit = { listModifier ->
        Column(listModifier.fillMaxSize()) {
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
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(space.s2)) {
                        ToggleChip(stringResource(R.string.spools_sealed_only), ui.sealedOnly) { vm.setSealedOnly(!ui.sealedOnly) }
                        // the Hub's running-low list (R80 section 7); no chip for a Hub that has none
                        if (lowCount != null || ui.lowOnly) {
                            ToggleChip(AlertTexts.runningLowChip(lowCount ?: ui.low.size), ui.lowOnly) { vm.setLowOnly(!ui.lowOnly) }
                        }
                    }
                    val openOrToggle: (SpoolSummary) -> Unit = { spool ->
                        when {
                            useCardDetail -> {
                                cachedSpool = spool
                                com.thompsonfabco.filamentkit.ui.spool.SpoolCache.put(spool)
                                expandedIds = if (spool.id in expandedIds) expandedIds - spool.id else expandedIds + spool.id
                            }
                            useSheetDetail || usePaneDetail -> {
                                cachedSpool = spool
                                com.thompsonfabco.filamentkit.ui.spool.SpoolCache.put(spool)
                                sheetSpoolId = spool.id
                            }
                            else -> onOpenSpool(spool)
                        }
                    }
                    if (ui.query.isBlank() && !ui.lowOnly) TagHint(nfc, onNfcSettings ?: { openNfcSettings(context) })
                    HubNoticeOf(ui.failure, onPairAgain)
                    if (ui.lowOnly) LowSpoolsList(ui, openOrToggle, online, onTryAgain = vm::loadLowSpools)
                    val searched = ui.searched
                    // the states every Hub screen has (05 3.2): the progress line, the error card, offline
                    if (!ui.lowOnly) ScreenState(
                        loaded = searched != null,
                        loading = ui.busy,
                        isEmpty = searched != null && ui.results.isEmpty(),
                        empty = {
                            Column {
                                Text(stringResource(R.string.spools_empty, searched.orEmpty()), style = MaterialTheme.typography.bodyLarge)
                                if (ui.sealedOnly) {
                                    SwButton(stringResource(R.string.spools_clear_sealed), { vm.setSealedOnly(false) }, kind = SwButtonKind.Quiet)
                                }
                            }
                        },
                        error = ui.failure?.let { hubFailureText(it) },
                        onTryAgain = { if (ui.query.isNotBlank()) vm.search() },
                        offline = !online,
                        loadedSecondsAgo = secondsSince(ui.loadedAt),
                    ) {
                        SwCollection(
                            ui.results, inset = SpoolwardenTheme.space.s4, surface = true, visual = SpoolwardenTheme.sizes.swatchRowW + SpoolwardenTheme.space.s3,
                            tile = { _, spool ->
                                val requester = rowFocus.getOrPut(spool.id) { FocusRequester() }
                                SpoolTile(spool, Modifier.focusRequester(requester), onClick = { openOrToggle(spool) })
                            },
                            isExpanded = if (useCardDetail) ({ it.id in expandedIds }) else null,
                            detail = if (useCardDetail) {
                                { _, spool ->
                                    val close = {
                                        expandedIds = expandedIds - spool.id
                                        returnFocusId = spool.id
                                    }
                                    SwCardDetail(onClose = close) {
                                        spoolDetail(spool, true, close)
                                    }
                                }
                            } else {
                                null
                            },
                        ) { _, spool ->
                            val requester = rowFocus.getOrPut(spool.id) { FocusRequester() }
                            SpoolRow(
                                spool,
                                modifier = Modifier.focusRequester(requester),
                                onClick = { openOrToggle(spool) },
                            )
                        }
                    }
                }
            }
        }
    }
    val openSpool = sheetSpoolId?.let { id ->
        ui.results.firstOrNull { it.id == id }
            ?: cachedSpool?.takeIf { it.id == id }
            ?: com.thompsonfabco.filamentkit.ui.spool.SpoolCache.get(id)
    }
    if (usePaneDetail) {
        val close = {
            returnFocusId = openSpool?.id
            sheetSpoolId = null
        }
        SwPaneLayout(
            hasSelection = openSpool != null,
            emptyText = stringResource(R.string.detail_pane_empty_spool),
            onClose = close,
            modifier = modifier,
            list = { listBody(Modifier) },
            detail = { openSpool?.let { spoolDetail(it, true, close) } },
        )
    } else {
        listBody(modifier)
        if (useSheetDetail && openSpool != null) {
            val close = {
                returnFocusId = openSpool.id
                sheetSpoolId = null
            }
            SwSheetDetail(onClose = close) {
                spoolDetail(openSpool, true, close)
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

/** A filter chip: the whole chip toggles, no check icon (08 10.3). */
@Composable
private fun ToggleChip(label: String, selected: Boolean, onClick: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = { Text(label, style = MaterialTheme.typography.labelLarge) },
        modifier = Modifier.heightIn(min = SpoolwardenTheme.sizes.row),
        shape = SpoolwardenTheme.shapes.rS,
        colors = FilterChipDefaults.filterChipColors(
            containerColor = colors.surface, labelColor = colors.text,
            selectedContainerColor = colors.accentSoft, selectedLabelColor = colors.accentText,
        ),
        border = FilterChipDefaults.filterChipBorder(
            enabled = true, selected = selected, borderColor = colors.border, selectedBorderColor = colors.border,
            borderWidth = SpoolwardenTheme.sizes.hairline, selectedBorderWidth = SpoolwardenTheme.sizes.hairline,
        ),
    )
}

/** The spool a running-low row stands for, as the Spools list shows it. */
internal fun LowSpool.toSummary(): SpoolSummary = SpoolSummary(
    id = id, brand = "", name = filament, material = material, colorHex = color, location = location, remaining = remainingG,
)

/** The running-low list (R80 section 7): least filament first, each row with "Last one" or "<n> more in stock" under it. */
@Composable
private fun LowSpoolsList(ui: SearchUi, onOpen: (SpoolSummary) -> Unit, online: Boolean, onTryAgain: () -> Unit) {
    val space = SpoolwardenTheme.space
    val colors = SpoolwardenTheme.colors
    ScreenState(
        loaded = ui.lowLoaded,
        loading = ui.busy,
        isEmpty = ui.lowLoaded && ui.low.isEmpty(),
        empty = { Text(AlertTexts.spoolsRunningLow(0), style = MaterialTheme.typography.bodyLarge) },
        error = ui.failure?.let { hubFailureText(it) },
        onTryAgain = onTryAgain,
        offline = !online,
        loadedSecondsAgo = secondsSince(ui.loadedAt),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(space.s2)) {
            ui.low.forEach { spool ->
                Column {
                    SpoolRow(spool.toSummary(), onClick = { onOpen(spool.toSummary()) })
                    Text(
                        if (spool.lastOne) AlertTexts.LAST_ONE else AlertTexts.moreInStock(spool.inStock),
                        color = if (spool.lastOne) colors.warn else colors.muted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
    }
}
