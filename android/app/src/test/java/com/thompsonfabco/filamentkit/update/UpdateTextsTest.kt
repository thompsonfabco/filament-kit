package com.thompsonfabco.filamentkit.update

import android.content.pm.PackageInstaller
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateTextsTest {
    private val signatureMessage = "INSTALL_FAILED_UPDATE_INCOMPATIBLE: Existing package com.thompsonfabco.filamentkit " +
        "signatures do not match newer version; ignoring!"

    @Test fun bannerNamesTheServersRelease() {
        assertEquals("Update available (filament-kit 0.5.0)", UpdateTexts.bannerTitle("0.5.0"))
        assertEquals("Update available", UpdateTexts.bannerTitle(null))
        assertEquals("Update available", UpdateTexts.bannerTitle(" "))
    }

    @Test fun nothingToSayWhenItWorkedWaitsOrWasCancelled() {
        for (s in listOf(PackageInstaller.STATUS_SUCCESS, PackageInstaller.STATUS_PENDING_USER_ACTION,
            PackageInstaller.STATUS_FAILURE_ABORTED)) {
            assertNull(UpdateTexts.installFailure(s, "whatever"))
        }
    }

    @Test fun aDifferentSigningKeySaysDoNotInstall() {
        val t = UpdateTexts.installFailure(PackageInstaller.STATUS_FAILURE_CONFLICT, signatureMessage)
        assertEquals(UpdateTexts.NOT_SIGNED_LIKE_YOUR_APP, t)
    }

    /** Whichever status a future Android files it under: the system's own words decide. */
    @Test fun theSigningCaseFollowsTheMessageNotTheStatus() {
        assertEquals(UpdateTexts.NOT_SIGNED_LIKE_YOUR_APP,
            UpdateTexts.installFailure(PackageInstaller.STATUS_FAILURE, signatureMessage))
        assertEquals(UpdateTexts.NOT_SIGNED_LIKE_YOUR_APP,
            UpdateTexts.installFailure(PackageInstaller.STATUS_FAILURE_INCOMPATIBLE, signatureMessage))
    }

    /** "Uninstall first" would coach the user past the one protection against a forged APK. */
    @Test fun neverSuggestsUninstalling() {
        val statuses = listOf(
            PackageInstaller.STATUS_FAILURE, PackageInstaller.STATUS_FAILURE_BLOCKED, PackageInstaller.STATUS_FAILURE_CONFLICT,
            PackageInstaller.STATUS_FAILURE_INCOMPATIBLE, PackageInstaller.STATUS_FAILURE_INVALID,
            PackageInstaller.STATUS_FAILURE_STORAGE, PackageInstaller.STATUS_FAILURE_TIMEOUT,
        )
        for (s in statuses) for (m in listOf(null, signatureMessage, "INSTALL_FAILED_VERSION_DOWNGRADE")) {
            val t = UpdateTexts.installFailure(s, m)!!
            assertFalse(t, "uninstall" in t.lowercase())
        }
    }

    @Test fun aConflictThatIsNotAboutTheKeyIsNotCalledUnsigned() {
        val t = UpdateTexts.installFailure(PackageInstaller.STATUS_FAILURE_CONFLICT, "INSTALL_FAILED_CONFLICTING_PROVIDER: x")!!
        assertFalse(t, "signed" in t)
        assertTrue(t, "INSTALL_FAILED_CONFLICTING_PROVIDER" in t)
    }

    @Test fun aDowngradeSaysSo() {
        assertEquals("This phone already has a newer version of the app.",
            UpdateTexts.installFailure(PackageInstaller.STATUS_FAILURE_CONFLICT, "INSTALL_FAILED_VERSION_DOWNGRADE: x"))
    }

    @Test fun eachStatusHasASentence() {
        assertEquals("The download is damaged. Tap Install to try again.",
            UpdateTexts.installFailure(PackageInstaller.STATUS_FAILURE_INVALID, "INSTALL_PARSE_FAILED_NO_CERTIFICATES: x"))
        assertEquals("Not enough storage on this phone to install the update.",
            UpdateTexts.installFailure(PackageInstaller.STATUS_FAILURE_STORAGE, null))
        assertEquals("This phone's settings or another app blocked the update.",
            UpdateTexts.installFailure(PackageInstaller.STATUS_FAILURE_BLOCKED, null))
        assertEquals("This update does not work on this phone's Android version.",
            UpdateTexts.installFailure(PackageInstaller.STATUS_FAILURE_INCOMPATIBLE, null))
        assertEquals("The install took too long. Tap Install to try again.",
            UpdateTexts.installFailure(PackageInstaller.STATUS_FAILURE_TIMEOUT, null))
        assertEquals("The update could not be installed.", UpdateTexts.installFailure(PackageInstaller.STATUS_FAILURE, null))
    }
}
