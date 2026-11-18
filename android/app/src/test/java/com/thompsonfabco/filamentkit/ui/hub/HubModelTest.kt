package com.thompsonfabco.filamentkit.ui.hub

import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.GettingStarted
import com.thompsonfabco.filamentkit.net.HubAnswer
import com.thompsonfabco.filamentkit.net.HubBackupFacts
import com.thompsonfabco.filamentkit.net.HubCatalogFacts
import com.thompsonfabco.filamentkit.net.HubCheck
import com.thompsonfabco.filamentkit.net.HubCheckState
import com.thompsonfabco.filamentkit.net.HubDevice
import com.thompsonfabco.filamentkit.net.HubFeature
import com.thompsonfabco.filamentkit.net.HubNewest
import com.thompsonfabco.filamentkit.net.HubReaderFacts
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.ZoneId
import java.util.Locale

private fun answer(
    gettingStarted: GettingStarted? = GettingStarted(4, 8, hidden = false, finished = false),
    full: Boolean = true,
) = HubAnswer(
    name = "Workshop Hub",
    version = "0.7.0",
    newest = if (full) HubNewest("0.8.0", "2026-11-17T08:00:00+00:00") else null,
    updateAvailable = full,
    checks = if (full) listOf(
        HubCheck("Hub", HubCheckState.Ok, "The Hub is running.", null),
        HubCheck("Backups", HubCheckState.Look, "No backup yet.", "Add a backup folder."),
    ) else emptyList(),
    gettingStarted = gettingStarted,
    features = if (full) listOf(HubFeature("alerts", "Alerts", true), HubFeature("camera", "Camera", false)) else emptyList(),
    catalog = if (full) HubCatalogFacts("1.4", "2026-11-17T07:00:00+00:00") else null,
    backup = if (full) HubBackupFacts(null, nightly = false) else null,
    reader = if (full) HubReaderFacts("local", keySet = false) else null,
    devices = if (full) listOf(
        HubDevice("My phone", "phone", "0.7.0", "2026-11-17T09:00:00+00:00", outOfDate = false, thisOne = true),
        HubDevice("Station", "station", null, null, outOfDate = true, thisOne = false),
    ) else emptyList(),
    recordsKept = if (full) 41L else null,
    spoolmanUrl = null,
    hubPage = if (full) "https://hub.local:8710/setup" else null,
)

class HubModelTest {
    private val time: (String?) -> String? = { it?.let { t -> "T($t)" } }

    @Test fun theGroupsComeInTheOrderOfTheRuling() {
        assertEquals(
            listOf(
                HubGroup.Status, HubGroup.GettingStarted, HubGroup.Version, HubGroup.Features, HubGroup.Catalog,
                HubGroup.Backups, HubGroup.LabelReader, HubGroup.Devices, HubGroup.RecentlyAdded,
            ),
            hubSections(answer(), time).map { it.group },
        )
        assertEquals(
            listOf("Status", "Getting started", "Version", "Features", "Filament Catalog", "Backups", "Label Reader", "Devices", "Recently added"),
            hubSections(answer(), time).map { it.group.title },
        )
    }

    @Test fun missingOptionalPartsLeaveTheirGroupOutAndVersionStays() {
        val sections = hubSections(answer(gettingStarted = null, full = false), time)
        assertEquals(listOf(HubGroup.Version), sections.map { it.group })
        assertEquals(listOf(HubLine.Field("Installed", "0.7.0")), sections.single().lines)
    }

    @Test fun gettingStartedShowsOnlyWhileStepsRemainAndNotHidden() {
        assertEquals("Getting started on the Hub: 4 of 8 done", gettingStartedLine(GettingStarted(4, 8, hidden = false, finished = false)))
        assertNull(gettingStartedLine(null))
        assertNull("hidden", gettingStartedLine(GettingStarted(4, 8, hidden = true, finished = false)))
        assertNull("finished", gettingStartedLine(GettingStarted(8, 8, hidden = false, finished = true)))
        assertNull("all done though not flagged", gettingStartedLine(GettingStarted(8, 8, hidden = false, finished = false)))
        assertNull("nothing to do", gettingStartedLine(GettingStarted(0, 0, hidden = false, finished = false)))
        assertFalse(gettingStartedShown(GettingStarted(2, 8, hidden = true, finished = true)))
        assertTrue(gettingStartedShown(GettingStarted(0, 8, hidden = false, finished = false)))
    }

    @Test fun theGettingStartedGroupIsLeftOutWhenHiddenOrFinished() {
        val hidden = hubSections(answer(GettingStarted(4, 8, hidden = true, finished = false)), time).map { it.group }
        val finished = hubSections(answer(GettingStarted(8, 8, hidden = false, finished = true)), time).map { it.group }
        assertFalse(HubGroup.GettingStarted in hidden)
        assertFalse(HubGroup.GettingStarted in finished)
        val shown = hubSections(answer(), time).first { it.group == HubGroup.GettingStarted }
        assertEquals(listOf(HubLine.Note("4 of 8 done")), shown.lines)
    }

    @Test fun statusKeepsTheHubsTextAndFix() {
        val status = hubSections(answer(), time).first { it.group == HubGroup.Status }
        assertEquals(
            listOf(
                HubLine.Check(HubCheckState.Ok, "The Hub is running.", null),
                HubLine.Check(HubCheckState.Look, "No backup yet.", "Add a backup folder."),
            ),
            status.lines,
        )
    }

    @Test fun versionSaysUpdateAvailableAndNewest() {
        val v = hubSections(answer(), time).first { it.group == HubGroup.Version }
        assertEquals(
            listOf(
                HubLine.Field("Installed", "0.7.0"),
                HubLine.Field("Newest", "0.8.0"),
                HubLine.Field("Last checked", "T(2026-11-17T08:00:00+00:00)"),
                HubLine.Note("Update available"),
            ),
            v.lines,
        )
    }

    @Test fun readerShowsKeySetOrNotSetNeverTheKey() {
        val r = hubSections(answer(), time).first { it.group == HubGroup.LabelReader }
        assertEquals(listOf(HubLine.Field("Engine", "local"), HubLine.Field("Key", "Not set")), r.lines)
    }

    @Test fun backupsAndCatalogSayNeverWhenNothingIsKnown() {
        val sections = hubSections(answer(), time)
        assertEquals(
            listOf(HubLine.Field("Last backup", "Never"), HubLine.Field("Nightly backup", "Off")),
            sections.first { it.group == HubGroup.Backups }.lines,
        )
        assertEquals(
            listOf(HubLine.Field("Version", "1.4"), HubLine.Field("Last checked", "T(2026-11-17T07:00:00+00:00)")),
            sections.first { it.group == HubGroup.Catalog }.lines,
        )
    }

    @Test fun devicesAreNamedWithKindVersionAndLastSeenAndTheThisOneIsMarked() {
        val d = hubSections(answer(), time).first { it.group == HubGroup.Devices }
        assertEquals(
            listOf(
                HubLine.Field("My phone (this device)", "Phone · 0.7.0 · last seen T(2026-11-17T09:00:00+00:00)"),
                HubLine.Field("Station", "Weigh Station · Version not known · Out of date"),
            ),
            d.lines,
        )
    }

    @Test fun aDeviceWithoutAKindShowsItsNameAndDetailsWithNoLeadingSeparator() {
        val d = hubSections(
            answer().copy(devices = listOf(HubDevice("Old box", "", "0.6.0", null, outOfDate = false, thisOne = false))),
            time,
        ).first { it.group == HubGroup.Devices }
        assertEquals(listOf(HubLine.Field("Old box", "0.6.0")), d.lines)
    }

    @Test fun anUnknownDeviceKindIsShownAsTheHubWroteIt() {
        assertEquals("gadget", deviceKindText("gadget"))
        assertEquals("Tag Reader", deviceKindText("reader"))
    }

    @Test fun recordsKeptIsTheNumber() {
        val r = hubSections(answer(), time).first { it.group == HubGroup.RecentlyAdded }
        assertEquals(listOf(HubLine.Field("Records kept", "41")), r.lines)
    }

    @Test fun featuresShowOnOrOff() {
        val f = hubSections(answer(), time).first { it.group == HubGroup.Features }
        assertEquals(listOf(HubLine.Field("Alerts", "On"), HubLine.Field("Camera", "Off")), f.lines)
    }

    @Test fun theHubsTimeIsShownInThePhonesZoneAndATextThatIsNotATimeStaysAsItIs() {
        assertEquals("Nov 17, 2026, 4:00 AM", hubTime("2026-11-17T09:00:00+00:00", ZoneId.of("America/New_York"), Locale.US)
            ?.replace(' ', ' '))
        assertEquals("yesterday", hubTime("yesterday", ZoneId.of("UTC"), Locale.US))
        assertEquals("Nov 17, 2026, 4:00 AM", hubTime("1794906000", ZoneId.of("America/New_York"), Locale.US)?.replace(' ', ' '))
        assertEquals("Nov 17, 2026, 4:00 AM", hubTime("1794906000.0", ZoneId.of("America/New_York"), Locale.US)?.replace(' ', ' '))
        assertEquals("Nov 17, 2026", hubDay("1794906000", ZoneId.of("America/New_York"), Locale.US))
        assertEquals("Nov 1, 2026", hubDay("2026-11-01", ZoneId.of("UTC"), Locale.US))
        assertEquals("Nov 1, 2026", hubDay("2026-11-01T10:00:00+00:00", ZoneId.of("UTC"), Locale.US))
        assertNull(hubDay(null))
        assertNull(hubTime(null))
        assertNull(hubTime(" "))
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class HubViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)

    @After fun tearDown() = Dispatchers.resetMain()

    @Test fun beforeTheFirstReadThereIsNothing() {
        val vm = HubViewModel({ answer() })
        assertNull(vm.state.value.hub)
        assertFalse(vm.state.value.loaded)
    }

    @Test fun refreshReadsTheHubAndNotesWhen() {
        val vm = HubViewModel({ answer() }, now = { 99L })
        vm.refresh()
        assertTrue(vm.state.value.loading)
        dispatcher.scheduler.runCurrent()
        assertEquals("Workshop Hub", vm.state.value.hub!!.name)
        assertEquals(99L, vm.state.value.loadedAt)
        assertTrue(vm.state.value.loaded)
        assertFalse(vm.state.value.loading)
        assertFalse(vm.state.value.unavailable)
    }

    @Test fun anOlderHubWithNoCallIsUnavailableNotAnError() {
        val vm = HubViewModel({ null })
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertTrue(vm.state.value.unavailable)
        assertTrue(vm.state.value.loaded)
        assertFalse(vm.state.value.failed)
        assertNull(vm.state.value.hub)
        assertNull("no Getting started line from an older Hub", gettingStartedLine(vm.state.value.hub?.gettingStarted))
    }

    @Test fun aFailedReadKeepsTheAnswerAlreadyShown() {
        var fail = false
        val vm = HubViewModel({ if (fail) throw ApiError(0, "offline", "no route") else answer() }, now = { 5L })
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        fail = true
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertEquals("Workshop Hub", vm.state.value.hub!!.name)
        assertEquals(5L, vm.state.value.loadedAt)
        assertTrue(vm.state.value.failed)
        assertNull(vm.state.value.message)
        assertFalse(vm.state.value.loading)
    }

    @Test fun theHubsOwnRefusalIsKeptAsTheMessage() {
        val vm = HubViewModel({ throw ApiError(500, "internal", "The Hub could not build this.") })
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertEquals("The Hub could not build this.", vm.state.value.message)
        assertTrue(vm.state.value.failed)
    }

    @Test fun aSecondRefreshWhileOneRunsIsDropped() {
        var calls = 0
        val vm = HubViewModel({ calls++; answer() })
        vm.refresh()
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertEquals(1, calls)
    }

    @Test fun homesLineFollowsTheAnswer() {
        val vm = HubViewModel({ answer() })
        vm.refresh()
        dispatcher.scheduler.runCurrent()
        assertEquals("Getting started on the Hub: 4 of 8 done", gettingStartedLine(vm.state.value.hub?.gettingStarted))
    }
}
