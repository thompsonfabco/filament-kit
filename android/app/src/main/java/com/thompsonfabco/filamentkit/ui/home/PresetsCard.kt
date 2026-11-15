package com.thompsonfabco.filamentkit.ui.home

import android.content.res.Resources
import androidx.annotation.DrawableRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.ui.components.SwButton
import com.thompsonfabco.filamentkit.ui.components.SwIcon
import com.thompsonfabco.filamentkit.ui.components.SwIconSize
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import java.text.DateFormat
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException
import java.util.Date
import java.util.TimeZone

/** The row of the Slicer presets screen a line belongs to (05-android-app 11.2: Built, Last build, On your PC). */
enum class PresetRow { Built, LastBuild, OnPc }

/** The shape before "Installed on your PC" and its two other cases (05-android-app 11.1). */
enum class PresetMark(@DrawableRes val shape: Int) {
    Installed(R.drawable.sw_st_filled),
    NotSetUp(R.drawable.sw_st_hollow),
    NotYet(R.drawable.sw_st_triangle),
}

/** One line of the Slicer presets panel; [error] lines are shown in the error colour. */
data class PresetLine(
    val text: String,
    val error: Boolean = false,
    val mark: PresetMark? = null,
    val row: PresetRow = PresetRow.Built,
)

/**
 * The Slicer presets panel text (05-android-app 11.1): the last good build (or "No presets built yet"), the last build's
 * error when it failed, and where Slicer Sync stands. [time] formats a server time.
 */
fun presetLines(s: ProfileStatus, r: Resources, time: (String?) -> String): List<PresetLine> {
    val out = mutableListOf<PresetLine>()
    val build = s.build
    if (build != null) {
        out += PresetLine(
            r.getString(
                R.string.presets_built, r.getQuantityString(R.plurals.presets_built_presets, s.presets, s.presets),
                r.getQuantityString(R.plurals.presets_built_lines, s.lines, s.lines), time(build.created),
            ),
        )
    }
    val attempt = s.lastAttempt
    if (attempt != null && !attempt.ok) {
        val why = attempt.error?.takeIf { it.isNotBlank() }
        out += PresetLine(
            if (why != null) r.getString(R.string.presets_build_failed, why) else r.getString(R.string.presets_build_failed_plain),
            error = true, row = PresetRow.LastBuild,
        )
    } else if (build == null) {
        out += PresetLine(r.getString(R.string.presets_never_built))
    }
    out += when {
        s.installed != null ->
            PresetLine(r.getString(R.string.presets_installed, time(s.installed.at)), mark = PresetMark.Installed, row = PresetRow.OnPc)
        s.pc == null -> PresetLine(r.getString(R.string.presets_sync_not_set_up), mark = PresetMark.NotSetUp, row = PresetRow.OnPc)
        else -> PresetLine(r.getString(R.string.presets_not_installed), mark = PresetMark.NotYet, row = PresetRow.OnPc)
    }
    return out
}

/**
 * What the panel offers beyond the status. [canBuild]: the phone may ask for a build here, which the Hub refuses while
 * another paired PC is the sync PC (`other_pc`), so it is offered only while no Slicer Sync is set up (the Slicer presets
 * screen's Build now has no such rule). [hints] say where to do the rest. [waiting]: updates not accepted yet; the
 * panel's Updates button opens the list (accept, restore deleted).
 */
data class PresetActions(val canBuild: Boolean, val hints: List<String>, val waiting: Int = 0)

fun presetActions(s: ProfileStatus, r: Resources): PresetActions {
    val hints = mutableListOf<String>()
    val waiting = (s.updates?.let { it.count - it.accepted } ?: 0).coerceAtLeast(0)
    if (waiting > 0) hints += r.getQuantityString(R.plurals.presets_updates_waiting, waiting, waiting)
    val canBuild = s.pc == null
    if (!canBuild) hints += r.getString(R.string.presets_build_elsewhere)
    return PresetActions(canBuild, hints, waiting)
}

/** The panel's button that opens the Updates dialog. */
fun updatesButton(a: PresetActions, r: Resources): String =
    if (a.waiting > 0) r.getQuantityString(R.plurals.presets_updates_review, a.waiting, a.waiting) else r.getString(R.string.presets_updates_title)

/** A server time as the catalogue's age ("40 s ago", "3 h ago"), or the phone's date after two days; unreadable text as sent. */
fun presetAge(r: Resources, raw: String?, nowMillis: Long): String {
    val ms = stampMillis(raw) ?: return raw?.takeIf { it.isNotBlank() } ?: r.getString(R.string.presets_unknown_time)
    val seconds = ((nowMillis - ms) / MS_PER_SECOND).coerceAtLeast(0)
    return when {
        seconds < SECONDS_PER_MINUTE -> r.getString(R.string.common_age_seconds, seconds)
        seconds < SECONDS_PER_HOUR -> r.getString(R.string.common_age_minutes, seconds / SECONDS_PER_MINUTE)
        seconds < SECONDS_PER_TWO_DAYS -> r.getString(R.string.common_age_hours, seconds / SECONDS_PER_HOUR)
        else -> formatStamp(raw)
    }
}

private const val MS_PER_SECOND = 1000L
private const val SECONDS_PER_MINUTE = 60L
private const val SECONDS_PER_HOUR = 3600L
private const val SECONDS_PER_TWO_DAYS = 172_800L

/** A server time as epoch millis: ISO-8601 with an offset, or epoch seconds (the PC sync's `at`). Null if unreadable. */
internal fun stampMillis(raw: String?): Long? {
    if (raw.isNullOrBlank()) return null
    raw.toDoubleOrNull()?.takeIf { it.isFinite() && it > 0 }?.let { return (it * 1000).toLong() }
    return try {
        OffsetDateTime.parse(raw.replace(" ", "T")).toInstant().toEpochMilli()
    } catch (_: DateTimeParseException) {
        null
    }
}

/** A server time in the phone's format; unreadable text is shown as sent. */
internal fun formatStamp(raw: String?, zone: TimeZone = TimeZone.getDefault()): String {
    val ms = stampMillis(raw) ?: return raw?.takeIf { it.isNotBlank() } ?: "unknown time"
    val f = DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT)
    f.timeZone = zone
    return f.format(Date(ms))
}

/**
 * The Slicer presets panel on the home screen (05-android-app 11.1); [status] null while unknown (not loaded or not
 * reachable). The whole header opens the Slicer presets screen ([onOpen]). [onBuild] asks for a build; [buildNote] is
 * its outcome (an error when [buildFailed]), [building] while it runs.
 */
@Composable
internal fun PresetsCard(
    status: ProfileStatus?,
    resources: Resources,
    nowMillis: Long,
    modifier: Modifier = Modifier,
    onOpen: (() -> Unit)? = null,
    onBuild: () -> Unit = {},
    building: Boolean = false,
    buildNote: String? = null,
    buildFailed: Boolean = false,
    /** Opens the Updates dialog (accept updates, restore deleted presets); null: not offered. */
    onUpdates: (() -> Unit)? = null,
) {
    val colors = SpoolwardenTheme.colors
    HomePanel(stringResource(R.string.nav_slicer_presets), modifier, onHeaderClick = onOpen) {
        if (status == null) {
            Text(stringResource(R.string.presets_status_unavailable), style = MaterialTheme.typography.bodyMedium, color = colors.muted)
            return@HomePanel
        }
        presetLines(status, resources) { presetAge(resources, it, nowMillis) }.forEach { line ->
            Row(horizontalArrangement = Arrangement.spacedBy(SpoolwardenTheme.space.s2), verticalAlignment = Alignment.CenterVertically) {
                line.mark?.let { mark ->
                    SwIcon(
                        mark.shape, null, size = SwIconSize.Small,
                        tint = when (mark) {
                            PresetMark.NotYet -> colors.warn
                            PresetMark.Installed -> colors.ok
                            PresetMark.NotSetUp -> colors.muted
                        },
                    )
                }
                Text(line.text, style = MaterialTheme.typography.bodyMedium, color = if (line.error) colors.bad else colors.text)
            }
        }
        val actions = presetActions(status, resources)
        actions.hints.forEach { Text(it, style = MaterialTheme.typography.bodySmall, color = colors.muted) }
        if (actions.canBuild) {
            SwButton(stringResource(R.string.presets_build_now), onBuild, busy = building)
        }
        onUpdates?.let { SwButton(updatesButton(actions, resources), it) }
        buildNote?.let {
            Text(it, color = if (buildFailed) colors.bad else colors.text, style = MaterialTheme.typography.bodySmall)
        }
    }
}
