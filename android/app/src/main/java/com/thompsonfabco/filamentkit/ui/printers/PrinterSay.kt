package com.thompsonfabco.filamentkit.ui.printers

import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.UsageEntry
import java.util.Locale

/**
 * What a result line says, without the words themselves: a catalogue text and its arguments, or words the Hub sent
 * and the app shows as given. The view models hold these so their tests need no resources; the screen turns one into
 * text with [sayText].
 */
sealed interface Say {
    data class Words(@StringRes val id: Int, val args: List<Any> = emptyList()) : Say
    data class FromHub(val text: String) : Say
}

@Composable
internal fun sayText(say: Say): String = when (say) {
    is Say.Words -> stringResource(
        say.id,
        *say.args.map { arg ->
            when (arg) {
                is UsageReason.Known -> stringResource(arg.id)
                is UsageReason.Other -> arg.text
                else -> arg
            }
        }.toTypedArray(),
    )
    is Say.FromHub -> say.text
}

/**
 * The words for a failed request of this screen (05-android-app 3.5): no answer at all (status 0) is "Cannot reach the
 * Hub"; an answer that is not the Hub speaking (unreadable, or an error page without the Hub's own message) is "The
 * Hub sent an answer this app does not understand"; the Hub's own message is shown as given.
 */
internal fun printerProblem(e: ApiError): Problem = when {
    e.status == 0 && e.code != "storage" -> Problem.Unreachable
    e.notFromHub -> Problem.Unexpected
    else -> Problem.HubSaid(e.message)
}

/** [Problem] as a result line: the catalogue's words, or the Hub's message as it came. */
internal fun Problem.say(): Say = when (this) {
    Problem.Unreachable -> Say.Words(R.string.common_hub_unreachable)
    is Problem.HubSaid -> Say.FromHub(text)
    Problem.NoLongerPaired -> Say.Words(R.string.common_not_paired_notice)
    Problem.CertificateChanged -> Say.Words(R.string.common_cert_changed_notice)
    else -> Say.Words(R.string.common_hub_answer_unknown)
}

/** A request failed with an error that is not an [ApiError] (a reply the app could not read). */
internal val UNREADABLE: Problem = Problem.Unexpected

/** The catalogue text for the Hub's camera error [code] (05-android-app 9.4); unknown codes get the last row. */
@StringRes
internal fun cameraErrorText(code: String): Int = when (code) {
    "camera_unavailable" -> R.string.printer_camera_error_unavailable
    "not_configured" -> R.string.printer_camera_error_not_configured
    "not_found" -> R.string.printer_camera_error_not_found
    "cert_changed" -> R.string.printer_camera_error_cert_changed
    else -> R.string.printer_camera_error_other
}

/** The reason a usage entry was not taken off a spool, from the Hub's error code (05-android-app 9.10). */
@StringRes
internal fun usageReason(code: String): Int? = when (code) {
    "file_not_found" -> R.string.printer_usage_reason_file_not_found
    "no_slice_info" -> R.string.printer_usage_reason_no_slice_info
    "plate_not_found" -> R.string.printer_usage_reason_plate_not_found
    "printer_unreachable" -> R.string.printer_usage_reason_printer_unreachable
    "cert_changed" -> R.string.printer_usage_reason_cert_changed
    "spoolman_unreachable" -> R.string.printer_usage_reason_spoolman_unreachable
    "spoolman_failed" -> R.string.printer_usage_reason_spoolman_failed
    "ambiguous_spool" -> R.string.printer_usage_reason_ambiguous_spool
    "no_mapping" -> R.string.printer_usage_reason_no_mapping
    "unmapped_slot" -> R.string.printer_usage_reason_unmapped_slot
    else -> null
}

/** The note after a usage entry's time: "undone", "logged only", ... ; null for a plain deduction. */
internal fun usageNote(e: UsageEntry): Say? = when {
    e.undone -> Say.Words(R.string.printer_usage_note_undone)
    e.error != null -> Say.Words(
        R.string.printer_usage_note_not_taken,
        listOf(usageReason(e.error)?.let { UsageReason.Known(it) } ?: UsageReason.Other(e.error.replace('_', ' '))),
    )
    e.observe -> Say.Words(R.string.printer_usage_note_logged)
    e.spoolId == null -> Say.Words(R.string.printer_usage_note_no_spool)
    else -> null
}

/** The reason inside a note: a catalogue text, or the Hub's code with underscores as spaces. */
internal sealed interface UsageReason {
    data class Known(@StringRes val id: Int) : UsageReason
    data class Other(val text: String) : UsageReason
}

/** Grams as the screen writes them: one decimal, a point. */
internal fun grams(value: Double?): String = value?.let { String.format(Locale.ROOT, "%.1f", it) } ?: "?"
