package com.thompsonfabco.filamentkit.ui.components

import android.content.res.Resources
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.IntakeHistory
import com.thompsonfabco.filamentkit.net.Printer
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.ui.history.RecentValues

/** One-line summary for the Printers row in the Panes section list, from printers the app already holds. */
internal fun printersSummary(printers: List<Printer>, resources: Resources): String {
    val configured = printers.filter { it.configured }
    if (configured.isEmpty()) return resources.getString(R.string.printers_empty_title)
    val connected = configured.count { it.state == "connected" }
    val offline = configured.count { it.state == "offline" }
    val attention = configured.size - connected - offline
    val parts = buildList {
        if (connected > 0) add(resources.getString(R.string.section_printers_connected, connected))
        if (offline > 0) add(resources.getString(R.string.section_printers_offline, offline))
        if (attention > 0) add(resources.getQuantityString(R.plurals.section_printers_attention, attention, attention))
    }
    return parts.reduce { acc, next ->
        resources.getString(R.string.section_printers_summary_pair, acc, next)
    }
}

/** One-line summary for the Recently added row in the Panes section list, from history the app already holds. */
internal fun recentSummary(history: IntakeHistory, resources: Resources): String {
    val latest = history.records.firstOrNull() ?: return resources.getString(R.string.recent_empty_title)
    return RecentValues.filaments(latest.spools) ?: RecentValues.time(latest.at)
}

/** One-line summary for Slicer presets in the Panes section list, from status the app already holds. */
internal fun presetsSummary(status: ProfileStatus, resources: Resources): String {
    if (status.presets <= 0) return resources.getString(R.string.presets_never_built)
    val presetsCount = resources.getQuantityString(R.plurals.presets_built_presets, status.presets, status.presets)
    val linesCount = resources.getQuantityString(R.plurals.presets_built_lines, status.lines, status.lines)
    return resources.getString(R.string.presets_built_no_time, presetsCount, linesCount)
}
