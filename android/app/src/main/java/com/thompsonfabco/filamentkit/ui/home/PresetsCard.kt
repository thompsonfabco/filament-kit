package com.thompsonfabco.filamentkit.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.thompsonfabco.filamentkit.net.ProfileStatus
import java.text.DateFormat
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException
import java.util.Date
import java.util.TimeZone

/** One line of the Presets card; [error] lines are shown in the error colour. */
data class PresetLine(val text: String, val error: Boolean = false)

/**
 * The Presets card text: the last good build (or "No presets built yet"), the last build's error when it failed, and
 * where the PC sync stands. [time] formats a server time.
 */
fun presetLines(s: ProfileStatus, time: (String?) -> String = { formatStamp(it) }): List<PresetLine> {
    val out = mutableListOf<PresetLine>()
    val build = s.build
    if (build != null) {
        out += PresetLine("${plural(s.presets, "preset")} for ${plural(s.lines, "line")}, built ${time(build.created)}")
    }
    val attempt = s.lastAttempt
    if (attempt != null && !attempt.ok) {
        out += PresetLine(
            "The last preset build failed" + (attempt.error?.takeIf { it.isNotBlank() }?.let { ": $it" } ?: ""),
            error = true,
        )
    } else if (build == null) {
        out += PresetLine("No presets built yet")
    }
    out += when {
        s.installed != null -> PresetLine("Installed on your PC ${time(s.installed.at)}")
        s.pc == null -> PresetLine("PC sync not set up")
        else -> PresetLine("Not installed on your PC yet")
    }
    return out
}

private fun plural(n: Int, word: String) = "$n $word${if (n == 1) "" else "s"}"

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

/** The Presets card on the home screen; [status] null while unknown (not loaded or not reachable). */
@Composable
fun PresetsCard(status: ProfileStatus?, modifier: Modifier = Modifier) {
    Card(modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("Presets", style = MaterialTheme.typography.titleMedium)
            if (status == null) {
                Text("Preset status is not available right now.", style = MaterialTheme.typography.bodySmall)
            } else {
                presetLines(status).forEach { line ->
                    Text(
                        line.text,
                        color = if (line.error) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }
        }
    }
}
