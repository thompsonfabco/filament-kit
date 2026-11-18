package com.thompsonfabco.filamentkit.ui.hub

/**
 * Every text the Hub screen and the Getting started line show that is not in the string catalogue yet (EV7a). Only the
 * catalogue step (EV2) opens `strings/en.json`; each text here has a proposed key in the report and moves there with
 * it. The checks' texts and fix lines, the device names and the versions are the Hub's own and are never built here.
 * "Open the Hub page", "Try again" and the words OK, Note, Off and Needs a look are catalogue texts already.
 */
object HubTexts {
    /** The screen's title and the entry points. */
    const val TITLE = "The Hub at a glance"
    const val OPEN_SCREEN = "The Hub at a glance"

    /** The group titles, in the order the screen shows them (R83 section 5.1). */
    const val GROUP_STATUS = "Status"
    const val GROUP_GETTING_STARTED = "Getting started"
    const val GROUP_VERSION = "Version"
    const val GROUP_FEATURES = "Features"
    const val GROUP_CATALOG = "Filament Catalog"
    const val GROUP_BACKUPS = "Backups"
    const val GROUP_LABEL_READER = "Label Reader"
    const val GROUP_DEVICES = "Devices"
    const val GROUP_RECENTLY_ADDED = "Recently added"

    /** The line that ends every group. */
    const val CHANGE_ON_HUB_PAGE = "Change this on the Hub page."

    /** Field labels and words. */
    const val INSTALLED = "Installed"
    const val NEWEST = "Newest"
    const val LAST_CHECKED = "Last checked"
    const val UPDATE_AVAILABLE = "Update available"
    const val CATALOG_VERSION = "Version"
    const val LAST_BACKUP = "Last backup"
    const val NIGHTLY_BACKUP = "Nightly backup"
    const val ENGINE = "Engine"
    const val KEY = "Key"
    const val KEY_SET = "Set"
    const val KEY_NOT_SET = "Not set"
    const val RECORDS_KEPT = "Records kept"
    const val ON = "On"
    const val OFF = "Off"
    const val NEVER = "Never"
    const val NOT_KNOWN = "Not known"
    const val VERSION_NOT_KNOWN = "Version not known"
    const val LAST_SEEN = "last seen"
    const val THIS_DEVICE = "this device"
    const val OUT_OF_DATE = "Out of date"

    /** The kinds of device (`kind`); a kind the app does not know is shown as the Hub wrote it. */
    const val KIND_PHONE = "Phone"
    const val KIND_PC = "Slicer Sync PC"
    const val KIND_STATION = "Weigh Station"
    const val KIND_WEB = "Web app"
    const val KIND_READER = "Tag Reader"
    const val KIND_BUILTIN = "Built-in"

    /** An older Hub: no `GET api/hub` (404). */
    const val UNAVAILABLE = "This Hub cannot show this yet. Update the Hub to see it here."

    fun stepsDone(done: Int, total: Int): String = "$done of $total done"

    /** The quiet line on Home that opens the Hub screen. */
    fun gettingStartedLine(done: Int, total: Int): String = "Getting started on the Hub: ${stepsDone(done, total)}"

    /** The health history table under the Status group (R84 4.3): the table only, the strip is on the Hub page. */
    const val HEALTH_TITLE = "Check history"
    const val HEALTH_SHOW_30 = "Show 30 days"
    const val HEALTH_SHOW_7 = "Show 7 days"
    const val HEALTH_NO_CHANGES = "No checks changed in this time."

    /** The state word of a check that failed; the other two are the catalogue's OK and Needs a look (`status_ok`, `status_needs_look`). */
    const val STATE_BAD = "Needs fixing"

    /** "No history before Nov 14, 2026." (R84 4.4): the table starts when the Hub's record did. */
    fun noHistoryBefore(date: String): String = "No history before $date."

    /** One row for a screen reader: "Nov 15, 04:10. Workshop X1: from OK to Needs fixing". */
    fun healthRowSpoken(time: String, check: String, from: String, to: String): String = "$time. $check: from $from to $to"
}
