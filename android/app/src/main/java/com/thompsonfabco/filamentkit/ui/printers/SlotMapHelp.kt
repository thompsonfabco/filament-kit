package com.thompsonfabco.filamentkit.ui.printers

import androidx.annotation.StringRes
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.MapStatus

enum class SlotMapOutcome { NONE, RUNNING, CONFIRMED, PARTIAL, STALE, SUSPECT, NOT_CONFIRMED, FAILED }

/**
 * What the section asks the owner to do next: [RETRY] map again (the printer or the Hub was in the way), [MANUAL] map
 * by loading filament (the printer itself could not tell its slot numbers), [NONE] nothing.
 */
enum class MapAction { NONE, RETRY, MANUAL }

/** The shape in front of the status words (05-android-app 9.7): the shape is never the only sign. */
enum class MapShape { Running, Filled, Triangle, Octagon }

/**
 * What the "Slot mapping" panel says about a [MapStatus]. Problems and notes are the Hub's words, with a capital first
 * letter; a line that only repeats what the screen already says is left out.
 */
data class SlotMapView(
    val outcome: SlotMapOutcome,
    val headline: Say? = null,
    val shape: MapShape? = null,
    /** The Hub's detail line (what to do next). */
    val detail: Say? = null,
    @StringRes val problemsHeading: Int? = null,
    val problems: List<String> = emptyList(),
    val problemsAreError: Boolean = false,
    val notes: List<String> = emptyList(),
    val action: MapAction = MapAction.NONE,
    /** The headline already says filament use is only logged, so the separate line would repeat it. */
    val saysObserve: Boolean = false,
)

/** Texts and rules for the "Slot mapping" panel of the printer screen. */
object SlotMapHelp {
    /** The Hub's line for what the "only logged" line and the headline already say. */
    private const val OBSERVE_LINE = "slot numbering not confirmed:"

    /** The Hub's note for what the partial state already says. */
    private const val SCHEME_NOTE = "numbered alike"

    private val PLAIN_FIRST_WORD = Regex("^[a-z]+([ ,:]|$)")

    private fun sentence(line: String) =
        if (PLAIN_FIRST_WORD.containsMatchIn(line)) line.replaceFirstChar { it.uppercase() } else line

    private fun words(@StringRes id: Int, vararg args: Any) = Say.Words(id, args.toList())

    /**
     * `done` only says the job ended and every slot was put back; `calibrated` says whether the numbering was proven.
     * `stale` and `suspect` outrank a finished job, because the map it made can no longer be called confirmed; only a
     * new job (`running`) or a failure of one says more. The scheme is open when the Hub says so; a Hub without
     * `scheme_unsettled` has only its note to go by. `problemsOld`: the result is from an earlier Hub run, so it is
     * reported as history, not as today's fault.
     */
    fun view(m: MapStatus?): SlotMapView {
        val old = m?.problemsOld == true
        val server = fromServer(m)
        val base = server ?: when {
            m == null -> SlotMapView(SlotMapOutcome.NONE)
            m.state == "running" -> SlotMapView(
                SlotMapOutcome.RUNNING,
                headline = m.step.ifBlank { null }?.let { Say.FromHub(it) } ?: words(R.string.printer_map_running),
                shape = MapShape.Running,
            )
            m.state != "failed" && m.stale -> SlotMapView(
                SlotMapOutcome.STALE, headline = words(R.string.printer_map_layout_changed), shape = MapShape.Triangle,
            )
            m.state != "failed" && m.suspect -> SlotMapView(
                SlotMapOutcome.SUSPECT, headline = words(R.string.printer_map_disagreed), shape = MapShape.Triangle,
            )
            m.state == "done" && m.calibrated && (m.schemeUnsettled ?: m.notes.isNotEmpty()) -> SlotMapView(
                SlotMapOutcome.PARTIAL, headline = words(R.string.printer_map_confirmed_loaded), shape = MapShape.Filled,
            )
            m.state == "done" && m.calibrated -> SlotMapView(
                SlotMapOutcome.CONFIRMED, headline = words(R.string.printer_map_mapped_count, m.slots.size),
                shape = MapShape.Filled,
                detail = words(R.string.printer_map_confirmed_text),
            )
            m.state == "done" && old -> SlotMapView(
                SlotMapOutcome.NOT_CONFIRMED, headline = words(R.string.printer_map_unconfirmed_last), shape = MapShape.Triangle,
            )
            m.state == "done" -> SlotMapView(
                SlotMapOutcome.NOT_CONFIRMED, headline = words(R.string.printer_map_unconfirmed), shape = MapShape.Triangle,
            )
            m.state == "failed" && old -> SlotMapView(
                SlotMapOutcome.FAILED, headline = words(R.string.printer_map_failed_last), shape = MapShape.Octagon,
            )
            m.state == "failed" -> SlotMapView(
                SlotMapOutcome.FAILED, headline = words(R.string.printer_map_failed), shape = MapShape.Octagon,
            )
            else -> SlotMapView(SlotMapOutcome.NONE)
        }
        if (m == null) return base
        // a calibrated map's problems did not stop it, whatever has happened to the map since
        val good = m.calibrated && base.outcome in setOf(
            SlotMapOutcome.CONFIRMED, SlotMapOutcome.PARTIAL, SlotMapOutcome.STALE, SlotMapOutcome.SUSPECT)
        val problems = m.problems.filterNot { it.startsWith(OBSERVE_LINE, ignoreCase = true) }.map(::sentence)
        val notes = m.notes
            .filterNot { base.outcome == SlotMapOutcome.PARTIAL && SCHEME_NOTE in it }
            .map(::sentence)
        return base.copy(
            action = if (server != null) base.action else when (base.outcome) {
                SlotMapOutcome.FAILED, SlotMapOutcome.NOT_CONFIRMED -> MapAction.RETRY
                SlotMapOutcome.STALE, SlotMapOutcome.SUSPECT -> MapAction.RETRY
                else -> MapAction.NONE
            },
            problemsHeading = when {
                problems.isEmpty() -> null
                old -> R.string.printer_map_problems_old
                good -> R.string.printer_map_problems_also
                else -> R.string.printer_map_problems
            },
            problems = problems,
            problemsAreError = problems.isNotEmpty() && !old && !good,
            notes = notes,
        )
    }

    /** The printer could not say its slot numbers: loading filament by hand is the way to a map. */
    private val MANUAL_REASONS = setOf("job_refused", "no_mapping", "numbers_unfit")

    /** Something in the way that clears by itself or by a fix elsewhere: mapping again is the step. */
    private val RETRY_REASONS = setOf("developer_mode", "busy", "offline", "not_configured", "cert_changed",
        "job_failed", "interrupted", "restore_failed", "kit_error")

    /**
     * The action for a Hub `outcome` and `reason`. A reason the app does not know acts as its outcome does: a failed
     * or unconfirmed map is mapped again, the rest needs nothing.
     */
    fun actionFor(outcome: String?, reason: String?): MapAction = when {
        outcome in setOf("confirmed", "running", "none", "partial") -> MapAction.NONE
        reason in MANUAL_REASONS -> MapAction.MANUAL
        reason in RETRY_REASONS -> MapAction.RETRY
        outcome == "not_confirmed" -> MapAction.MANUAL      // calibration ran and still proved nothing
        outcome in setOf("failed", "stale", "suspect") -> MapAction.RETRY
        else -> MapAction.NONE
    }

    /**
     * A v0.5.0 Hub's own reading: its outcome picks the state and its sentences are shown as they are (the outcome as
     * the headline, the next step under it). Null when the Hub does not say, or says an outcome this app does not
     * know: the flags decide then, as before.
     */
    private fun fromServer(m: MapStatus?): SlotMapView? {
        val code = m?.outcome ?: return null
        val text = m.outcomeText?.takeIf { it.isNotBlank() } ?: return null
        val outcome = SlotMapOutcome.entries.firstOrNull { it.name.equals(code, ignoreCase = true) } ?: return null
        if (outcome == SlotMapOutcome.NONE) return SlotMapView(SlotMapOutcome.NONE)
        val running = outcome == SlotMapOutcome.RUNNING
        return SlotMapView(
            outcome,
            headline = Say.FromHub(if (running) m.step.ifBlank { text } else text),
            shape = when (outcome) {
                SlotMapOutcome.RUNNING -> MapShape.Running
                SlotMapOutcome.CONFIRMED, SlotMapOutcome.PARTIAL -> MapShape.Filled
                SlotMapOutcome.FAILED -> MapShape.Octagon
                else -> MapShape.Triangle
            },
            detail = if (running) null else m.nextStep?.takeIf { it.isNotBlank() }?.let { Say.FromHub(it) },
            action = actionFor(code, m.reason),
            saysObserve = outcome == SlotMapOutcome.NOT_CONFIRMED || outcome == SlotMapOutcome.SUSPECT,
        )
    }

    /** The printer's own state decides; a past result never does (the Hub re-checks when a job starts). */
    fun canStart(printerState: String, printing: Boolean): Boolean =
        printerState in STARTABLE && !printing

    /** Why [canStart] is false, for the line under the greyed button. */
    @StringRes
    fun blockedReason(printerState: String, printing: Boolean): Int? = when {
        printerState !in STARTABLE -> R.string.printer_available_connected
        printing -> R.string.printer_available_idle
        else -> null
    }

    @StringRes
    fun buttonLabel(m: MapStatus?): Int =
        if (m?.state == "done" || m?.state == "failed") R.string.printer_map_slots_again else R.string.printer_map_slots

    /** A Developer Mode refusal never blocks mapping: the slot test finds out for itself and says so. */
    private val STARTABLE = setOf("connected", "needs_developer_mode")
}

/** The one filled button of the printer screen (05-android-app 9.7, F1.2). */
enum class MainButton { None, PauseResume, MapByLoading, MapSlots, Report }

/**
 * Which button is filled when several could be, in the order of 05 9.7: Pause / Resume while a print runs or is
 * paused, "Map by loading filament" when automatic mapping can't confirm the numbering, "Map slots" / "Map slots
 * again" when the Hub's reason calls for a new mapping, "Collect a report" when the Hub says it would help. A button
 * that is disabled never counts.
 */
fun mainButton(
    pauseEnabled: Boolean,
    action: MapAction,
    mapEnabled: Boolean,
    manualEnabled: Boolean,
    reportWanted: Boolean,
    reportEnabled: Boolean,
): MainButton = when {
    pauseEnabled -> MainButton.PauseResume
    action == MapAction.MANUAL && manualEnabled -> MainButton.MapByLoading
    action == MapAction.RETRY && mapEnabled -> MainButton.MapSlots
    reportWanted && reportEnabled -> MainButton.Report
    else -> MainButton.None
}
