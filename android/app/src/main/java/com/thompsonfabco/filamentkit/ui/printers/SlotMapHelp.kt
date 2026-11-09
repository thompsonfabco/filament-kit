package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.net.MapStatus

enum class SlotMapOutcome { NONE, RUNNING, CONFIRMED, PARTIAL, STALE, SUSPECT, NOT_CONFIRMED, FAILED }

/**
 * What the section asks the owner to do next: [RETRY] map again (the printer or the kit was in the way), [MANUAL] map
 * by loading filament (the printer itself could not tell its slot numbers), [NONE] nothing.
 */
enum class MapAction { NONE, RETRY, MANUAL }

/**
 * What the "Slot mapping" section says about a [MapStatus]. Problems and notes are the server's words, with a capital
 * first letter; a line that only repeats what the app already says is left out.
 */
data class SlotMapView(
    val outcome: SlotMapOutcome,
    val headline: String? = null,
    val headlineIsError: Boolean = false,
    val detail: String? = null,
    val problemsHeading: String? = null,
    val problems: List<String> = emptyList(),
    val problemsAreError: Boolean = false,
    val notesHeading: String? = null,
    val notes: List<String> = emptyList(),
    val action: MapAction = MapAction.NONE,
    /** The headline already says filament use is only logged, so the separate notice would repeat it. */
    val saysObserve: Boolean = false,
)

/** Texts and rules for the "Slot mapping" section of the printer screen. */
object SlotMapHelp {
    private const val PROBLEMS = "Problems the server reported:"
    private const val LEFTOVERS = "Also reported during mapping:"
    private const val OLD_PROBLEMS = "From an earlier mapping, it may be fixed by now. Map the slots again to check:"
    private const val NOTES = "Not settled yet:"
    private const val REMAP = "A new mapping starts by itself when the printer is idle. If it does not, tap Map slots again."
    private const val TRY_AGAIN = "Tap Map slots again when the printer is idle."

    /** The server's line for what the app's "only logged" notice and the headline already say. */
    private const val OBSERVE_LINE = "slot numbering not confirmed:"

    /** The server's note for what the partial state's detail already says, in plain words. */
    private const val SCHEME_NOTE = "numbered alike"

    private val PLAIN_FIRST_WORD = Regex("^[a-z]+([ ,:]|$)")

    private fun sentence(line: String) =
        if (PLAIN_FIRST_WORD.containsMatchIn(line)) line.replaceFirstChar { it.uppercase() } else line

    /**
     * `done` only says the job ended and every slot was put back; `calibrated` says whether the numbering was proven.
     * `stale` and `suspect` outrank a finished job, because the map it made can no longer be called confirmed; only a
     * new job (`running`) or a failure of one says more. A stale map comes first, as in the server's own re-map step.
     * The scheme is open when the server says so; a server without `scheme_unsettled` has only its note to go by.
     * `problemsOld`: the result is from an earlier server run, so it is reported as history, not as today's fault.
     */
    fun view(m: MapStatus?): SlotMapView {
        val old = m?.problemsOld == true
        val server = fromServer(m)
        val base = server ?: when {
            m == null -> SlotMapView(SlotMapOutcome.NONE)
            m.state == "running" -> SlotMapView(SlotMapOutcome.RUNNING, headline = m.step.ifBlank { "Mapping slots…" })
            m.state != "failed" && m.stale -> SlotMapView(
                SlotMapOutcome.STALE,
                headline = "Layout changed: the map will be made again",
                detail = REMAP,
            )
            m.state != "failed" && m.suspect -> SlotMapView(
                SlotMapOutcome.SUSPECT,
                headline = "Recent prints disagreed with the map: map again",
                headlineIsError = true,
                detail = REMAP,
            )
            m.state == "done" && m.calibrated && (m.schemeUnsettled ?: m.notes.isNotEmpty()) -> SlotMapView(
                SlotMapOutcome.PARTIAL,
                headline = "Slots mapped: confirmed for the loaded slots",
                detail = "The numbering scheme is settled by mapping again once a second unit or an HT has a spool loaded.",
            )
            m.state == "done" && m.calibrated -> SlotMapView(
                SlotMapOutcome.CONFIRMED,
                headline = "Slots mapped (${m.slots.size})",
                detail = "The slot numbering is confirmed.",
            )
            m.state == "done" && old -> SlotMapView(
                SlotMapOutcome.NOT_CONFIRMED,
                headline = "The last slot mapping did not confirm the numbering",
            )
            m.state == "done" -> SlotMapView(
                SlotMapOutcome.NOT_CONFIRMED,
                headline = "Slot numbering not confirmed",
                headlineIsError = true,
                detail = "The calibration did not prove how this printer numbers its slots. $TRY_AGAIN",
            )
            m.state == "failed" && old -> SlotMapView(SlotMapOutcome.FAILED, headline = "The last slot mapping failed")
            // not the step: a finished job's step is only the server's end word, "Mapping failed"
            m.state == "failed" -> SlotMapView(
                SlotMapOutcome.FAILED,
                headline = "Slot mapping failed",
                headlineIsError = true,
                detail = TRY_AGAIN,
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
                else -> MapAction.NONE
            },
            problemsHeading = when {
                problems.isEmpty() -> null
                old -> OLD_PROBLEMS
                good -> LEFTOVERS
                else -> PROBLEMS
            },
            problems = problems,
            problemsAreError = problems.isNotEmpty() && !old && !good,
            notesHeading = if (notes.isEmpty()) null else NOTES,
            notes = notes,
        )
    }

    /** The printer could not say its slot numbers: loading filament by hand is the way to a map. */
    private val MANUAL_REASONS = setOf("job_refused", "no_mapping", "numbers_unfit")

    /** Something in the way that clears by itself or by a fix elsewhere: mapping again is the step. */
    private val RETRY_REASONS = setOf("developer_mode", "busy", "offline", "not_configured", "cert_changed",
        "job_failed", "interrupted", "restore_failed", "kit_error")

    /**
     * The action for a server's `outcome` and `reason`. A reason the app does not know acts as its outcome does: a
     * failed or unconfirmed map is mapped again, the rest needs nothing.
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
     * A v0.5.0 server's own reading: its outcome picks the state and its sentences are shown as they are (the
     * outcome as the headline, the next step under it). Null when the server does not say, or says an outcome this
     * app does not know: the flags decide then, as before.
     */
    private fun fromServer(m: MapStatus?): SlotMapView? {
        val code = m?.outcome ?: return null
        val text = m.outcomeText?.takeIf { it.isNotBlank() } ?: return null
        val outcome = SlotMapOutcome.entries.firstOrNull { it.name.equals(code, ignoreCase = true) } ?: return null
        if (outcome == SlotMapOutcome.NONE) return SlotMapView(SlotMapOutcome.NONE)
        val running = outcome == SlotMapOutcome.RUNNING
        return SlotMapView(
            outcome,
            headline = if (running) m.step.ifBlank { text } else text,
            headlineIsError = !m.problemsOld && outcome in setOf(
                SlotMapOutcome.FAILED, SlotMapOutcome.SUSPECT, SlotMapOutcome.NOT_CONFIRMED),
            detail = if (running) null else m.nextStep?.takeIf { it.isNotBlank() },
            action = actionFor(code, m.reason),
            saysObserve = outcome == SlotMapOutcome.NOT_CONFIRMED || outcome == SlotMapOutcome.SUSPECT,
        )
    }

    /** The printer's own state decides; a past result never does (the server re-checks when a job starts). */
    fun canStart(printerState: String, printing: Boolean): Boolean =
        printerState in STARTABLE && !printing

    /** Why [canStart] is false, for the line under the greyed button. */
    fun blockedReason(printerState: String, printing: Boolean): String? = when {
        printerState !in STARTABLE -> "Available when the printer is connected."
        printing -> "Available when the printer is idle."
        else -> null
    }

    fun buttonLabel(m: MapStatus?): String =
        if (m?.state == "done" || m?.state == "failed") "Map slots again" else "Map slots"

    /** A Developer Mode refusal never blocks mapping: the slot test finds out for itself and says so. */
    private val STARTABLE = setOf("connected", "needs_developer_mode")
}
