package com.thompsonfabco.filamentkit.ui.home

import com.thompsonfabco.filamentkit.net.BuildAttempt
import com.thompsonfabco.filamentkit.net.BuildInfo
import com.thompsonfabco.filamentkit.net.InstalledInfo
import com.thompsonfabco.filamentkit.net.PcInfo
import com.thompsonfabco.filamentkit.net.ProfileStatus
import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.TimeZone

class PresetsCardTest {
    /** Times shown as `<raw>` so the tests do not depend on the phone's locale. */
    private val fmt: (String?) -> String = { "<$it>" }

    private val build = BuildInfo("s1", "h", "2026-11-02T01:02:03Z", presets = 96, problems = 0)

    @Test fun builtAndInstalled() {
        val s = ProfileStatus(
            lines = 12, presets = 96, build = build, lastAttempt = BuildAttempt("2026-11-02T01:02:03Z", ok = true),
            installed = InstalledInfo("s1", "2026-11-02T01:05:00Z"), pc = PcInfo("pc-1", null),
        )
        assertEquals(
            listOf(
                PresetLine("96 presets for 12 lines, built <2026-11-02T01:02:03Z>"),
                PresetLine("Installed on your PC <2026-11-02T01:05:00Z>"),
            ),
            presetLines(s, fmt),
        )
    }

    @Test fun aFailedBuildShowsItsErrorInErrorColour() {
        val s = ProfileStatus(
            lines = 12, presets = 96, build = build,
            lastAttempt = BuildAttempt("2026-11-02T02:00:00Z", ok = false, error = "validation failed: x.json"),
            installed = null, pc = PcInfo("pc-1", "2026-11-02T01:59:00Z"),
        )
        assertEquals(
            listOf(
                PresetLine("96 presets for 12 lines, built <2026-11-02T01:02:03Z>"),
                PresetLine("The last preset build failed: validation failed: x.json", error = true),
                PresetLine("Not installed on your PC yet"),
            ),
            presetLines(s, fmt),
        )
    }

    @Test fun nothingBuiltAndNoPcSync() {
        val s = ProfileStatus(
            lines = 0, presets = 0, build = null,
            lastAttempt = BuildAttempt("2026-11-02T02:00:00Z", ok = false, error = "no system presets uploaded"),
            installed = null, pc = null,
        )
        assertEquals(
            listOf(
                PresetLine("The last preset build failed: no system presets uploaded", error = true),
                PresetLine("PC sync not set up"),
            ),
            presetLines(s, fmt),
        )
    }

    @Test fun neverAttempted() {
        assertEquals(
            listOf(PresetLine("No presets built yet"), PresetLine("PC sync not set up")),
            presetLines(ProfileStatus(), fmt),
        )
    }

    @Test fun aFailureWithoutTextStillSaysSo() {
        val s = ProfileStatus(lastAttempt = BuildAttempt("x", ok = false, error = null))
        assertEquals(PresetLine("The last preset build failed", error = true), presetLines(s, fmt)[0])
    }

    @Test fun oneLineAndOnePresetAreSingular() {
        val s = ProfileStatus(lines = 1, presets = 1, build = build.copy(presets = 1))
        assertEquals("1 preset for 1 line, built <2026-11-02T01:02:03Z>", presetLines(s, fmt)[0].text)
    }

    @Test fun timesFromTheServerAreReadAsIsoOrEpochSeconds() {
        val utc = TimeZone.getTimeZone("UTC")
        assertEquals(1793581323000L, stampMillis("2026-11-02T01:02:03Z"))
        assertEquals(1793581323000L, stampMillis("2026-11-02T01:02:03+00:00"))
        assertEquals(1793581323500L, stampMillis("1793581323.5"))
        assertEquals(null, stampMillis("soon"))
        assertEquals(null, stampMillis(null))
        assertEquals("soon", formatStamp("soon", utc))
        assertEquals("unknown time", formatStamp(null, utc))
    }
}
