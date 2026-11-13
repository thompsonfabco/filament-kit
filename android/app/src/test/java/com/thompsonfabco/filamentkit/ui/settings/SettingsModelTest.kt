package com.thompsonfabco.filamentkit.ui.settings

import com.thompsonfabco.filamentkit.update.UpdateFailure
import com.thompsonfabco.filamentkit.update.UpdateUi
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SettingsModelTest {
    @Test fun developerIsOnlyInDebugBuilds() {
        assertEquals(
            listOf(SettingsGroup.Appearance, SettingsGroup.Hub, SettingsGroup.Updates, SettingsGroup.Licences),
            settingsGroups(developer = false),
        )
        assertEquals(SettingsGroup.Developer, settingsGroups(developer = true).last())
    }

    /** The switch says "check"; the stored setting still says "skip", so the old meaning is kept. */
    @Test fun theFingerprintCheckIsTheSkipSettingTheOtherWayRound() {
        assertTrue("on by default: skip is off", fingerprintCheckOn(skipFingerprintCheck = false))
        assertFalse(fingerprintCheckOn(skipFingerprintCheck = true))
    }

    @Test fun onlyTurningTheCheckOffAsksFirst() {
        assertTrue(needsSkipConfirmation(turnedOn = false))
        assertFalse(needsSkipConfirmation(turnedOn = true))
    }

    @Test fun theUpdatesSummaryNamesTheReadyReleaseOrTheAppVersion() {
        assertEquals(UpdatesSummary.Ready("0.5.3"), updatesSummary(UpdateUi(available = 7, offeredVersion = "0.5.3")))
        assertEquals(UpdatesSummary.Ready("7"), updatesSummary(UpdateUi(available = 7, offeredVersion = " ")))
        assertEquals(UpdatesSummary.UpToDate, updatesSummary(UpdateUi(checked = true)))
        assertEquals("not claimed before a check reached the Hub", UpdatesSummary.Unchecked, updatesSummary(UpdateUi()))
        assertEquals(UpdatesSummary.Unchecked, updatesSummary(UpdateUi(checked = true, serverTooNew = true)))
    }

    @Test fun thePanelFollowsTheTableOfSection13() {
        assertEquals(UpdatePanelState.Unknown, updatePanel(UpdateUi()))
        assertEquals(UpdatePanelState.UpToDate, updatePanel(UpdateUi(checked = true)))
        assertEquals(UpdatePanelState.Offered, updatePanel(UpdateUi(available = 7, checked = true)))
        assertEquals(
            UpdatePanelState.HubNewer(canInstall = true),
            updatePanel(UpdateUi(available = 7, serverTooNew = true, checked = true)),
        )
        assertEquals(UpdatePanelState.HubNewer(canInstall = false), updatePanel(UpdateUi(serverTooNew = true, checked = true)))
        assertEquals(UpdatePanelState.Downloading(42), updatePanel(UpdateUi(available = 7, busy = true, progress = 42)))
        assertEquals(UpdatePanelState.Downloading(null), updatePanel(UpdateUi(available = 7, busy = true)))
        assertEquals(UpdatePanelState.NeedsPermission, updatePanel(UpdateUi(available = 7, needsPermission = true)))
        assertEquals(
            UpdatePanelState.Installing(canReopen = true),
            updatePanel(UpdateUi(available = 7, installing = true, confirmPending = true)),
        )
        assertEquals(UpdatePanelState.Installing(canReopen = false), updatePanel(UpdateUi(available = 7, installing = true)))
        assertEquals(
            UpdatePanelState.Downloading(null, writing = true),
            updatePanel(UpdateUi(available = 7, busy = true, writing = true)),
        )
        assertEquals(UpdatePanelState.Waiting, updatePanel(UpdateUi(available = 7, confirmPending = true)))
    }

    @Test fun aFailureShowsWithTryAgainThatInstallsOnlyWhenThereIsSomethingToInstall() {
        assertEquals(
            UpdatePanelState.Failed(UpdateFailure.Storage, canInstall = true),
            updatePanel(UpdateUi(available = 7, failure = UpdateFailure.Storage)),
        )
        assertEquals(
            UpdatePanelState.Failed(UpdateFailure.HubUnreachable, canInstall = false),
            updatePanel(UpdateUi(failure = UpdateFailure.HubUnreachable)),
        )
    }

    @Test fun aDownloadUnderWayHidesAnOldFailure() {
        assertEquals(
            UpdatePanelState.Downloading(10),
            updatePanel(UpdateUi(available = 7, busy = true, progress = 10, failure = UpdateFailure.Signature)),
        )
    }

    @Test fun everyFailureHasItsOwnLine() {
        assertEquals(UpdateFailure.entries.size, UpdateFailure.entries.map { it.text }.toSet().size)
    }
}
