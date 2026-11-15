package com.thompsonfabco.filamentkit.ui.home

import com.thompsonfabco.filamentkit.net.BuildAttempt
import com.thompsonfabco.filamentkit.net.BuildInfo
import com.thompsonfabco.filamentkit.net.InstalledInfo
import com.thompsonfabco.filamentkit.net.PcInfo
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.net.UpdatesInfo
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import java.util.TimeZone

@RunWith(RobolectricTestRunner::class)
class PresetsCardTest {
    private val res get() = RuntimeEnvironment.getApplication().resources

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
                PresetLine("Installed on your PC <2026-11-02T01:05:00Z>", mark = PresetMark.Installed, row = PresetRow.OnPc),
            ),
            presetLines(s, res, fmt),
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
                PresetLine("The last preset build failed: validation failed: x.json", error = true, row = PresetRow.LastBuild),
                PresetLine("Not installed on your PC yet", mark = PresetMark.NotYet, row = PresetRow.OnPc),
            ),
            presetLines(s, res, fmt),
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
                PresetLine("The last preset build failed: no system presets uploaded", error = true, row = PresetRow.LastBuild),
                PresetLine("Slicer Sync is not set up", mark = PresetMark.NotSetUp, row = PresetRow.OnPc),
            ),
            presetLines(s, res, fmt),
        )
    }

    @Test fun neverAttempted() {
        assertEquals(
            listOf(PresetLine("No presets built yet"), PresetLine("Slicer Sync is not set up", mark = PresetMark.NotSetUp, row = PresetRow.OnPc)),
            presetLines(ProfileStatus(), res, fmt),
        )
    }

    @Test fun aFailureWithoutTextStillSaysSo() {
        val s = ProfileStatus(lastAttempt = BuildAttempt("x", ok = false, error = null))
        assertEquals(PresetLine("The last preset build failed", error = true, row = PresetRow.LastBuild), presetLines(s, res, fmt)[0])
    }

    @Test fun oneLineAndOnePresetAreSingular() {
        val s = ProfileStatus(lines = 1, presets = 1, build = build.copy(presets = 1))
        assertEquals("1 preset for 1 line, built <2026-11-02T01:02:03Z>", presetLines(s, res, fmt)[0].text)
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

    @Test fun buildNowIsOfferedOnlyWhileNoPcSyncIsSetUp() {
        assertEquals(PresetActions(canBuild = true, hints = emptyList()), presetActions(ProfileStatus(), res))
        val withPc = presetActions(ProfileStatus(pc = PcInfo("pc-1", null)), res)
        assertEquals(false, withPc.canBuild)
        assertEquals(listOf("To build now, open the setup page (Settings, Open the setup page)."), withPc.hints)
    }

    @Test fun waitingUpdatesAreReviewedOnThePhoneAndAcceptedOnesAreNotCounted() {
        val a = presetActions(ProfileStatus(updates = UpdatesInfo(count = 3, lines = 2, accepted = 1)), res)
        assertEquals(listOf("2 presets in your slicers can be updated."), a.hints)
        assertEquals(2, a.waiting)
        assertEquals("Review 2 updates", updatesButton(a, res))
        val none = presetActions(ProfileStatus(updates = UpdatesInfo(count = 2, lines = 1, accepted = 2)), res)
        assertEquals(emptyList<String>(), none.hints)
        assertEquals("Updates", updatesButton(none, res))
        assertEquals("Review 1 update", updatesButton(presetActions(ProfileStatus(updates = UpdatesInfo(count = 1)), res), res))
    }

    @Test fun timesAreAgesForTwoDaysThenTheDate() {
        val built = stampMillis("2026-11-02T01:02:03Z")!!
        assertEquals("40 s ago", presetAge(res, "2026-11-02T01:02:03Z", built + 40_000))
        assertEquals("2 min ago", presetAge(res, "2026-11-02T01:02:03Z", built + 150_000))
        assertEquals("3 h ago", presetAge(res, "2026-11-02T01:02:03Z", built + 3 * 3_600_000 + 5_000))
        assertEquals(formatStamp("2026-11-02T01:02:03Z"), presetAge(res, "2026-11-02T01:02:03Z", built + 3 * 86_400_000L))
        assertEquals("soon", presetAge(res, "soon", built))
        assertEquals("unknown time", presetAge(res, null, built))
    }
}
