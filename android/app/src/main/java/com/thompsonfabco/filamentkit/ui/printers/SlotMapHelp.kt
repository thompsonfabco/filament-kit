package com.thompsonfabco.filamentkit.ui.printers

import com.thompsonfabco.filamentkit.net.MapStatus

enum class SlotMapOutcome { NONE, RUNNING, CONFIRMED, PARTIAL, NOT_CONFIRMED, FAILED }

/** What the "Slot mapping" section says about a [MapStatus]. Problems and notes are the server's text, unchanged. */
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
)

/** Texts and rules for the "Slot mapping" section of the printer screen. */
object SlotMapHelp {
    private const val PROBLEMS = "Problems the server reported:"
    private const val LEFTOVERS = "Also reported during mapping:"
    private const val OLD_PROBLEMS = "From an earlier mapping, it may be fixed by now. Map the slots again to check:"
    private const val NOTES = "Not settled yet:"

    /**
     * `done` only says the job ended and every slot was put back; `calibrated` says whether the numbering was proven.
     * Notes on a calibrated map mean the loaded slots fit more than one numbering scheme (the server's only notes).
     * `problemsOld`: the result is from an earlier server run, so it is reported as history, not as today's fault.
     */
    fun view(m: MapStatus?): SlotMapView {
        val old = m?.problemsOld == true
        val base = when {
            m == null -> SlotMapView(SlotMapOutcome.NONE)
            m.state == "running" -> SlotMapView(SlotMapOutcome.RUNNING, headline = m.step.ifBlank { "Mapping slots…" })
            m.state == "done" && m.calibrated && m.notes.isNotEmpty() -> SlotMapView(
                SlotMapOutcome.PARTIAL,
                headline = "Slots mapped: confirmed for the loaded slots",
                detail = "The numbering scheme is pinned down when a second unit or an HT is loaded.",
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
                detail = "The slots were tested, but the calibration job did not prove how this printer numbers them.",
            )
            m.state == "failed" && old -> SlotMapView(SlotMapOutcome.FAILED, headline = "The last slot mapping failed")
            m.state == "failed" -> SlotMapView(
                SlotMapOutcome.FAILED,
                headline = listOf("Slot mapping failed", m.step).filter { it.isNotBlank() }.joinToString(": "),
                headlineIsError = true,
            )
            else -> SlotMapView(SlotMapOutcome.NONE)
        }
        if (m == null) return base
        val good = base.outcome == SlotMapOutcome.CONFIRMED || base.outcome == SlotMapOutcome.PARTIAL
        return base.copy(
            problemsHeading = when {
                m.problems.isEmpty() -> null
                old -> OLD_PROBLEMS
                good -> LEFTOVERS
                else -> PROBLEMS
            },
            problems = m.problems,
            problemsAreError = m.problems.isNotEmpty() && !old && !good,
            notesHeading = if (m.notes.isEmpty()) null else NOTES,
            notes = m.notes,
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
