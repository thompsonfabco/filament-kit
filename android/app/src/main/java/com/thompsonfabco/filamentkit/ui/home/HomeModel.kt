package com.thompsonfabco.filamentkit.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.thompsonfabco.filamentkit.drafts.Draft
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.ui.printers.PrinterHelp
import com.thompsonfabco.filamentkit.update.UpdateUi
import java.time.Instant
import java.time.ZoneId
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The Printers panel shows at most this many rows, then "and N more" (05-android-app 5). */
internal const val HOME_PRINTER_ROWS = 4

/** How old a draft is, in the catalogue's words; a date once it is older than yesterday. */
internal sealed interface DraftAge {
    data class Seconds(val n: Long) : DraftAge
    data class Minutes(val n: Long) : DraftAge
    data class Hours(val n: Long) : DraftAge
    data object Yesterday : DraftAge
    data object Older : DraftAge
}

private const val MINUTE_MS = 60_000L
private const val HOUR_MS = 60 * MINUTE_MS
private const val DAY_MS = 24 * HOUR_MS

/** [created] seen from [now] (epoch millis); a clock set back reads as "0 s ago". [startOfToday] is local midnight. */
internal fun draftAge(created: Long, now: Long, startOfToday: Long): DraftAge {
    val age = (now - created).coerceAtLeast(0)
    return when {
        age < MINUTE_MS -> DraftAge.Seconds(age / 1000)
        age < HOUR_MS -> DraftAge.Minutes(age / MINUTE_MS)
        created >= startOfToday -> DraftAge.Hours(age / HOUR_MS)
        created >= startOfToday - DAY_MS -> DraftAge.Yesterday
        else -> DraftAge.Older
    }
}

/** The parts of a draft's supporting line that exist, in order: the note (the hint typed), the tag. */
internal class DraftParts(val photos: Int, val note: String?, val tag: String?)

internal fun draftParts(d: Draft) = DraftParts(d.photos.size, d.hint.trim().ifBlank { null }, d.tag?.trim()?.ifBlank { null })

/** What a printer row says about the printer: its shape and word. */
internal enum class HomePrinterStatus { Printing, Idle, Offline, NeedsLook, NotConfigured }

internal fun homePrinterStatus(p: Printer): HomePrinterStatus = when {
    !p.configured || p.state == Printer.STATE_NOT_CONFIGURED -> HomePrinterStatus.NotConfigured
    p.state == Printer.STATE_CONNECTED ->
        if (p.summary?.let { PrinterHelp.isPrinting(it.gcodeState) } == true) HomePrinterStatus.Printing else HomePrinterStatus.Idle
    p.state == Printer.STATE_OFFLINE -> HomePrinterStatus.Offline
    else -> HomePrinterStatus.NeedsLook // wrong Access Code, Developer Mode, a changed certificate
}

/** Local midnight of the day [now] falls in, in [zone] (the device's zone): where "today" starts for the draft ages. */
internal fun startOfDay(now: Long, zone: ZoneId = ZoneId.systemDefault()): Long =
    Instant.ofEpochMilli(now).atZone(zone).toLocalDate().atStartOfDay(zone).toInstant().toEpochMilli()

/** The rows shown and how many more there are. */
internal class PrinterRows(val shown: List<Printer>, val more: Int)

internal fun printerRows(all: List<Printer>) = PrinterRows(all.take(HOME_PRINTER_ROWS), (all.size - HOME_PRINTER_ROWS).coerceAtLeast(0))

/** The job of a printing printer: its percent and the time left (null when the Hub gave none). */
internal class PrinterJob(val percent: Int, val hours: Int, val minutes: Int)

internal fun printerJob(p: Printer): PrinterJob? {
    val s = p.summary ?: return null
    if (!PrinterHelp.isPrinting(s.gcodeState)) return null
    val left = s.remainingMin.coerceAtLeast(0)
    return PrinterJob(s.percent.coerceIn(0, 100), left / 60, left % 60)
}

/** What the update notice on Home shows. */
internal enum class UpdateNoticeKind { HubNewer, Ready, Downloaded }

/** The notice, or null when there is nothing to offer. A Hub newer than the app comes first: it is the warning. */
internal fun updateNotice(u: UpdateUi): UpdateNoticeKind? = when {
    u.serverTooNew -> UpdateNoticeKind.HubNewer
    u.confirmPending -> UpdateNoticeKind.Downloaded
    u.available != null -> UpdateNoticeKind.Ready
    else -> null
}

/** The Printers panel's data: null [printers] until the first answer; [message] is the Hub's own refusal, if any. */
data class HomePrintersState(
    val printers: List<Printer>? = null,
    val loading: Boolean = false,
    val failed: Boolean = false,
    val message: String? = null,
    /** When [printers] was read (epoch millis), for the offline notice. */
    val loadedAt: Long? = null,
)

/**
 * The printers of the Printers panel. [load] asks the Hub each time (it resolves the session's current client, so a
 * re-pair reaches it); a failed read keeps the rows already shown.
 */
class HomePrintersViewModel(
    private val load: suspend () -> List<Printer>,
    private val now: () -> Long = System::currentTimeMillis,
) : ViewModel() {
    private val _state = MutableStateFlow(HomePrintersState())
    val state: StateFlow<HomePrintersState> = _state.asStateFlow()

    fun refresh() {
        if (_state.value.loading) return
        _state.update { it.copy(loading = true) }
        viewModelScope.launch {
            try {
                val list = load()
                _state.update { HomePrintersState(printers = list, loadedAt = now()) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val refusal = (e as? ApiError)?.takeIf { it.status > 0 }?.message
                _state.update { it.copy(loading = false, failed = true, message = refusal) }
            }
        }
    }
}
