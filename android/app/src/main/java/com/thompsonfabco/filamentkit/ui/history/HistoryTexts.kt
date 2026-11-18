package com.thompsonfabco.filamentkit.ui.history

/**
 * Every text of the history and data features (HD9) that is not in the string catalogue yet. Only the catalogue step
 * (HD2) opens `strings/en.json`; each text here has a proposed key in the report and in the contract requests, and
 * moves there with it. "Undo" is the catalogue's `common_undo`; the Hub's own sentences (an event's text, a refusal's
 * text, a health check's text) are shown as the Hub sent them and never built here.
 */
object HistoryTexts {
    /** What an undo answers (R84 3.3); "Put back." is followed by the Hub's note when it sends one. */
    const val PUT_BACK = "Put back."

    /** The refusals, used only when a 409 carries no `text` of its own (R84 3.3 gives the first). */
    const val UNDO_CHANGED_SINCE = "This changed again since, so it cannot be undone."
    const val UNDO_TOO_OLD = "This is older than 7 days, so it cannot be undone."
    const val UNDO_ALREADY_UNDONE = "This was already undone."
    const val UNDO_NOT_UNDOABLE = "This cannot be undone."

    /** A Hub without the undo route (404). */
    const val UNDO_UPDATE_HUB = "Update the Hub to use Undo."

    /** Undo did not reach the Hub, or the Hub failed without saying why. */
    const val UNDO_FAILED = "Nothing was undone. Try again."

    /** The title of a spool's last events (R84 section 2). */
    const val ACTIVITY_TITLE = "Recent activity"

    /** The Filament used panel's other view (R84 5.7) and the way back to the list. */
    const val BY_MONTH = "By month"
    const val LAST_DAYS = "Last 7 days"

    /** "Download as CSV" (R84 6.5): the printer's filament used, through the phone's share sheet. */
    const val DOWNLOAD_CSV = "Download as CSV"
    const val DOWNLOADING = "Downloading…"

    /** The month table's empty state, and an older Hub. */
    const val NO_MONTHS = "No months to show yet."
    const val MONTHS_UPDATE_HUB = "Update the Hub to see filament used by month."

    /** A download that the Hub does not have, or the phone could not keep. */
    const val CSV_UPDATE_HUB = "Update the Hub to download this file."
    const val CSV_NOT_SAVED = "The file could not be saved on this phone. Is there enough free space?"

    /** The month table's words: "15 prints", "2 did not finish", "Most used: PA6". */
    fun prints(n: Int) = if (n == 1) "1 print" else "$n prints"
    fun unfinished(n: Int) = "$n did not finish"
    fun mostUsed(material: String) = "Most used: $material"
}
