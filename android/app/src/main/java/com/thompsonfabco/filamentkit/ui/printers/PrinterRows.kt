package com.thompsonfabco.filamentkit.ui.printers

import androidx.annotation.StringRes
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.components.StatusKind

// What a printer row says (05-android-app 9.1), kept apart from the drawing so tests can read it.

/** The job state that follows the badge as words, not as a badge. [progress]: the percentage and time left follow. */
internal enum class JobWord(@StringRes val word: Int, val progress: Boolean) {
    Printing(R.string.printer_job_printing, true),
    Paused(R.string.printer_job_paused, true),
    Preparing(R.string.printer_job_preparing, true),
    Slicing(R.string.printer_job_slicing, true),
    Finished(R.string.printer_job_finished, false),
    Failed(R.string.printer_job_failed, false),
    Idle(R.string.printer_job_idle, false),
}

/** The word for the printer's `gcode_state`; null when it is not one the Hub names (`UNKNOWN`). */
internal fun jobWord(gcodeState: String): JobWord? = when (gcodeState) {
    "RUNNING" -> JobWord.Printing
    "PAUSE" -> JobWord.Paused
    "PREPARE" -> JobWord.Preparing
    "SLICING" -> JobWord.Slicing
    "FINISH" -> JobWord.Finished
    "FAILED" -> JobWord.Failed
    "IDLE" -> JobWord.Idle
    else -> null
}

/** The badge for the Hub's printer `state` (the vocabulary table of 05-android-app 9.1). */
internal fun statusKind(state: String): StatusKind = when (state) {
    "connected" -> StatusKind.Connected
    "offline" -> StatusKind.Offline
    "not_configured" -> StatusKind.NotConfigured
    else -> StatusKind.NeedsLook
}

/** The sentence that follows a state that needs something; null when the state needs nothing. */
@StringRes
internal fun fixLine(state: String): Int? = when (state) {
    "offline" -> R.string.printers_fix_offline
    "wrong_code" -> R.string.printers_fix_wrong_code
    "needs_developer_mode" -> R.string.printers_fix_developer_mode
    "cert_changed" -> R.string.printers_fix_cert_changed
    "not_configured" -> R.string.printers_fix_not_configured
    else -> null
}

/** The slots a row draws as swatches before it says "+N". */
internal const val MAX_SWATCHES = 8

/** The first [MAX_SWATCHES] slots and how many more there are. */
internal fun shownSlots(slots: List<SlotLook>): Pair<List<SlotLook>, Int> =
    slots.take(MAX_SWATCHES) to (slots.size - MAX_SWATCHES).coerceAtLeast(0)

/** Whole hours and the minutes left over; hours are 0 under an hour. */
internal fun hoursAndMinutes(minutes: Int): Pair<Int, Int> = minutes / MINUTES_PER_HOUR to minutes % MINUTES_PER_HOUR

private const val MINUTES_PER_HOUR = 60
