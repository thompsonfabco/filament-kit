package com.thompsonfabco.filamentkit.alerts

/**
 * Every text the alerts feature shows that is not in the string catalogue yet (EA8). Only the catalogue step (EA3)
 * opens `strings/en.json`; each text here has a proposed key in the report and moves there with it. The titles and
 * sentences of events are the Hub's own (`title`, `text`) and are never built here. "Dismiss", "Send a test alert",
 * "Sent.", "On", "Off" and "Open app settings" are catalogue texts already.
 */
object AlertTexts {
    /** The permanent notification of the watching service. */
    const val WATCHING_TITLE = "Watching the Hub for alerts"

    const val CHANNEL_ALERTS = "Alerts"
    const val CHANNEL_WATCHING = "Watching the Hub"

    /** The Settings group, the switch, its hint and the list link. */
    const val SETTINGS_TITLE = "Alerts"
    const val SWITCH_TITLE = "Alerts on this phone"
    const val SWITCH_HINT = "Android shows a small permanent notification while Spoolwarden watches the Hub."
    const val RECENT_ALERTS = "Recent alerts"
    const val NOTIFICATIONS_DENIED_HELP =
        "Android is not allowing notifications for Spoolwarden. Allow them in the phone's settings, then turn this on."
    const val LOCAL_NETWORK_HELP =
        "Spoolwarden needs the Local network permission to watch the Hub. Allow it, then turn this on."
    const val UNAVAILABLE = "This Hub does not send alerts yet. Update the Hub to get them."

    const val EMPTY = "No alerts in the last 7 days."
    const val LAST_ONE = "Last one"

    /** The actions of a banner or a list row. */
    const val OPEN_PRINTER = "Open the printer"
    const val SHOW_RUNNING_LOW = "Show running low"
    const val SHOW_ALERTS = "Show alerts"

    fun moreAlerts(n: Int): String = if (n == 1) "1 more alert" else "$n more alerts"

    fun spoolsRunningLow(n: Int): String = if (n == 1) "1 spool running low" else "$n spools running low"

    fun runningLowChip(n: Int): String = "Running low ($n)"

    fun moreInStock(n: Int): String = "$n more in stock"

    /** The label of the one action of an alert, by where it goes. */
    fun actionLabel(target: AlertTarget): String = when (target) {
        is AlertTarget.Printer -> OPEN_PRINTER
        AlertTarget.RunningLow -> SHOW_RUNNING_LOW
        AlertTarget.AlertsList -> SHOW_ALERTS
    }
}
