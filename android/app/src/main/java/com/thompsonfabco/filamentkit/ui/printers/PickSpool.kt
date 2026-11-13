package com.thompsonfabco.filamentkit.ui.printers

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.FingerprintMismatch
import com.thompsonfabco.filamentkit.net.LoadResult
import com.thompsonfabco.filamentkit.ui.ColorSwatch
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.NoticeCard
import com.thompsonfabco.filamentkit.ui.components.NoticeKind
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwDialog
import com.thompsonfabco.filamentkit.ui.components.SwDialogButton
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwProgress
import com.thompsonfabco.filamentkit.ui.spool.SpoolSummary
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
import java.math.BigDecimal

/** The calls "Pick a spool for a slot" makes; [ApiPickBackend] adapts the Api, tests pass a fake. */
interface PickBackend {
    suspend fun search(query: String, sealedOnly: Boolean): List<JsonObject>
    suspend fun load(printerId: String, label: String, spoolId: Int, dryRun: Boolean): LoadResult
}

/** Each call goes to the session's client of that moment, so a screen never holds an old one. */
class ApiPickBackend(private val current: () -> Api) : PickBackend {
    override suspend fun search(query: String, sealedOnly: Boolean) = current().search(query, sealedOnly)
    override suspend fun load(printerId: String, label: String, spoolId: Int, dryRun: Boolean) =
        current().load(printerId, label, spoolId, dryRun)
}

/** The dry run of a load into this slot: what the Hub says it would do, before the real load. */
data class LoadPreview(
    val spool: SpoolSummary,
    val result: LoadResult? = null,
    /** The real load is being written: nothing can leave the preview. */
    val writing: Boolean = false,
    val problem: Say? = null,
    val hubNotice: Problem? = null,
)

data class PickUiState(
    val query: String = "",
    val sealedOnly: Boolean = false,
    val busy: Boolean = false,
    val searched: Boolean = false,
    val results: List<SpoolSummary> = emptyList(),
    val problem: Problem? = null,
    val preview: LoadPreview? = null,
    /** The load went through: [confirmed] is whether the printer already shows it. */
    val loaded: Boolean? = null,
)

/**
 * Pick a spool for slot [slot] of printer [printerId] (05-android-app 9.6): the Spools search, then the preview step of
 * the load (a dry run, then the real one). A load being written cannot be left; its result goes back to the screen
 * through [PickUiState.loaded].
 */
class PickSpoolViewModel(
    private val backend: PickBackend,
    private val printerId: String,
    private val slot: String,
) : ViewModel() {
    private val _state = MutableStateFlow(PickUiState())
    val state: StateFlow<PickUiState> = _state.asStateFlow()
    private var job: Job? = null
    private var typing: Job? = null

    /** A pause in typing searches by itself; clearing the box clears the results. */
    fun setQuery(q: String) {
        _state.update { it.copy(query = q) }
        typing?.cancel()
        if (q.isBlank()) {
            job?.cancel()
            _state.update { it.copy(busy = false, searched = false, results = emptyList(), problem = null) }
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
        _state.update { it.copy(busy = true, problem = null) }
        job = viewModelScope.launch {
            try {
                val found = backend.search(q, s.sealedOnly).map { it.toSpoolSummary() }
                _state.update { it.copy(busy = false, searched = true, results = found, problem = null) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: FingerprintMismatch) {
                _state.update { it.copy(busy = false, problem = Problem.CertificateChanged) }
            } catch (e: ApiError) {
                _state.update { it.copy(busy = false, problem = if (e.code == "unauthorized") Problem.NoLongerPaired else printerProblem(e)) }
            } catch (_: Exception) {
                _state.update { it.copy(busy = false, problem = UNREADABLE) }
            }
        }
    }

    /** Picks [spool]: asks the Hub what loading it here would do (a dry run) and shows the preview. */
    fun pick(spool: SpoolSummary) {
        if (_state.value.preview?.writing == true) return
        _state.update { it.copy(preview = LoadPreview(spool)) }
        viewModelScope.launch {
            try {
                val r = backend.load(printerId, slot, spool.id, dryRun = true)
                _state.update { it.copy(preview = it.preview?.copy(result = r, problem = null, hubNotice = null)) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val p = previewProblem(e)
                _state.update { it.copy(preview = it.preview?.copy(problem = p.first, hubNotice = p.second)) }
            }
        }
    }

    /** Back from the preview to the results; refused while the real load is being written. */
    fun back() = _state.update { if (it.preview?.writing == true) it else it.copy(preview = null) }

    val writing: Boolean get() = _state.value.preview?.writing == true

    /** The real load. It is not cancelled by leaving: the screen stays and shows the result. */
    fun confirm() {
        val p = _state.value.preview ?: return
        val r = p.result ?: return
        if (p.writing) return
        _state.update { it.copy(preview = p.copy(writing = true, problem = null, hubNotice = null)) }
        viewModelScope.launch {
            try {
                val done = backend.load(printerId, slot, p.spool.id, dryRun = false)
                _state.update { it.copy(preview = null, loaded = done.confirmed) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val problem = previewProblem(e, writing = true)
                _state.update { it.copy(preview = it.preview?.copy(writing = false, problem = problem.first, hubNotice = problem.second)) }
            }
        }
    }

    /** The screen has said how the load went. */
    fun loadedShown() = _state.update { it.copy(loaded = null) }

    /**
     * Words for a failed dry run or load. A 401 to the real load is the Hub refusing before it did anything; a lost
     * connection says to check the printer (the write may have reached it); a Hub notice shows as one.
     */
    private fun previewProblem(e: Exception, writing: Boolean = false): Pair<Say?, Problem?> = when {
        e is FingerprintMismatch -> null to Problem.CertificateChanged
        e is ApiError && e.code == "unauthorized" ->
            if (writing) Say.Words(R.string.spool_load_pairing_refused) to null else null to Problem.NoLongerPaired
        e is ApiError && writing && e.status == 0 && e.code != "storage" -> Say.Words(R.string.spool_load_dropped) to null
        e is ApiError -> printerProblem(e).say() to null
        else -> UNREADABLE.say() to null
    }

    private companion object {
        const val MIN_TYPED = 2
        const val TYPING_PAUSE_MS = 400L
    }
}

/**
 * Pick a spool for a slot (05-android-app 9.6): the header "Load into Workshop X1, slot A4", the Spools search, and
 * after a pick the preview of the load. After loading, [onLoaded] returns to the printer screen.
 */
@Composable
fun PickSpoolScreen(
    viewModel: PickSpoolViewModel,
    printerName: String?,
    slot: String,
    onLoaded: (confirmed: Boolean) -> Unit,
    onPairAgain: () -> Unit,
) {
    val s by viewModel.state.collectAsState()
    val toast = LocalToast.current
    val wait = stringResource(R.string.common_load_wait)
    // the load being written ignores Back and says why (05-android-app 2.5 rule 2)
    val scope = rememberCoroutineScope()
    BackHandler(enabled = s.preview?.writing == true) { scope.launch { toast?.show(wait) } }
    LaunchedEffect(s.loaded) {
        s.loaded?.let {
            viewModel.loadedShown()
            onLoaded(it)
        }
    }
    val space = SpoolwardenTheme.space
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(space.s4),
        verticalArrangement = Arrangement.spacedBy(space.s3),
    ) {
        Text(
            stringResource(R.string.printer_pick_title, printerName.orEmpty(), slot), Modifier.semantics { heading() },
            style = MaterialTheme.typography.titleMedium,
        )
        FormField(s.query, viewModel::setQuery, stringResource(R.string.spools_search_label))
        FilterChip(
            selected = s.sealedOnly, onClick = { viewModel.setSealedOnly(!s.sealedOnly) },
            label = { Text(stringResource(R.string.spools_sealed_only)) }, shape = SpoolwardenTheme.shapes.rS,
        )
        if (s.query.isBlank()) {
            Row(horizontalArrangement = Arrangement.spacedBy(space.s2), verticalAlignment = Alignment.CenterVertically) {
                SwIcon(R.drawable.sw_ic_tag, null, tint = SpoolwardenTheme.colors.muted)
                Text(
                    stringResource(R.string.printer_pick_tag_hint), color = SpoolwardenTheme.colors.muted,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
        if (s.busy) SwProgress(null)
        s.problem?.let {
            if (it.isHubNotice) ProblemNotice(it, onPairAgain) else NoticeCard(
                NoticeKind.Bad, problemText(it),
                actions = listOf(SwAction(stringResource(R.string.common_try_again), viewModel::search)),
            )
        }
        if (s.searched && s.results.isEmpty() && s.problem == null) {
            Text(
                stringResource(R.string.spools_empty, s.query.trim()), color = SpoolwardenTheme.colors.muted,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
        if (s.results.isNotEmpty()) {
            PrinterPanel(title = null, padded = false) {
                s.results.forEachIndexed { i, spool ->
                    if (i > 0) PanelDivider()
                    SpoolRow(spool) { viewModel.pick(spool) }
                }
            }
        }
    }
    s.preview?.let { PreviewDialog(it, printerName.orEmpty(), slot, viewModel, onPairAgain) }
}

@Composable
private fun SpoolRow(spool: SpoolSummary, onClick: () -> Unit) {
    val colors = SpoolwardenTheme.colors
    val space = SpoolwardenTheme.space
    val open = stringResource(R.string.a11y_action_open)
    val dash = "–"
    Row(
        Modifier.fillMaxWidth().heightIn(min = SpoolwardenTheme.sizes.row).clickable(onClickLabel = open, onClick = onClick)
            .padding(horizontal = space.s4, vertical = space.s2),
        horizontalArrangement = Arrangement.spacedBy(space.s3),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ColorSwatch(spool.colorHex)
        Column(Modifier.weight(1f)) {
            Text("${spool.brand} ${spool.name}".trim(), style = MaterialTheme.typography.bodyLarge)
            Text(
                stringResource(
                    R.string.spools_result_line, spool.id, spool.material.ifBlank { dash }, spool.location ?: dash,
                    spool.remaining?.let { grams(it).removeSuffix(".0") } ?: dash,
                ),
                color = colors.muted, style = SpoolwardenTheme.type.dataSmall,
            )
        }
        SwIcon(R.drawable.sw_ic_chevron, null, tint = colors.muted)
    }
}

/** The preview step of 7.6 for this slot: the Hub's dry run as rows, then "Back" and "Load". */
@Composable
private fun PreviewDialog(p: LoadPreview, printerName: String, slot: String, viewModel: PickSpoolViewModel, onPairAgain: () -> Unit) {
    val r = p.result
    SwDialog(
        title = stringResource(R.string.spool_load_confirm_title, printerName, slot),
        onClose = viewModel::back,
        confirm = SwDialogButton(
            stringResource(if (p.writing) R.string.spool_load_loading else R.string.spool_load_button),
            viewModel::confirm, kind = SwButtonKind.Main, enabled = r != null && !p.writing, busy = p.writing,
        ),
        cancel = SwAction(stringResource(R.string.common_back), viewModel::back),
        cancelEnabled = !p.writing,
    ) {
        if (r == null && p.problem == null && p.hubNotice == null) {
            SwProgress(null)
            Text(stringResource(R.string.common_checking), style = MaterialTheme.typography.bodyMedium)
        }
        if (r != null) {
            Text(
                if (r.preset?.name.isNullOrBlank()) stringResource(R.string.printer_load_no_preset)
                else stringResource(R.string.printer_load_preset, r.preset!!.name),
                style = MaterialTheme.typography.bodyMedium,
            )
            val mm = r.nozzleMm?.let { BigDecimal.valueOf(it).stripTrailingZeros().toPlainString() }
            when {
                r.nozzleAssumed -> Text(
                    stringResource(R.string.printer_load_nozzle_assumed, mm ?: DEFAULT_NOZZLE_MM),
                    style = MaterialTheme.typography.bodyMedium,
                )
                mm != null -> Text(stringResource(R.string.printer_load_nozzle, mm), style = MaterialTheme.typography.bodyMedium)
            }
            r.movedBack.filter { it.id != p.spool.id }.forEach { m ->
                Text(
                    stringResource(
                        R.string.printer_load_moved_back, m.id ?: "?", slot,
                        m.location.ifBlank { stringResource(R.string.printer_unload_previous_place) },
                    ),
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            r.problems.forEach { Text(it, style = MaterialTheme.typography.bodyMedium) }
            Text(
                stringResource(R.string.spool_load_confirm_text), color = SpoolwardenTheme.colors.muted,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        p.problem?.let { NoticeCard(NoticeKind.Bad, sayText(it)) }
        p.hubNotice?.let { ProblemNotice(it, onPairAgain) }
    }
}

private const val DEFAULT_NOZZLE_MM = "0.4"
