package com.thompsonfabco.filamentkit.update

import android.content.pm.PackageInstaller
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import com.thompsonfabco.filamentkit.R

@RunWith(RobolectricTestRunner::class)
class UpdateTextsTest {
    private val signatureMessage = "INSTALL_FAILED_UPDATE_INCOMPATIBLE: Existing package com.thompsonfabco.filamentkit " +
        "signatures do not match newer version; ignoring!"

    @Test fun bannerNamesTheServersRelease() {
        assertEquals("Update available (filament-kit 0.5.0)", UpdateTexts.bannerTitle("0.5.0"))
        assertEquals("Update available", UpdateTexts.bannerTitle(null))
        assertEquals("Update available", UpdateTexts.bannerTitle(" "))
    }

    /** That paragraph, unlike the page's "App not installed" line, doesn't tell the user to uninstall. */
    @Test fun theRefusalLinksToItsOwnGuideParagraph() {
        assertTrue(UpdateTexts.REFUSED_GUIDE_URL.endsWith("docs/install-android-app.md#update-refused"))
        assertTrue(UpdateTexts.REFUSED_GUIDE_URL.startsWith("https://"))
    }

    @Test fun afterARefusalTheButtonDoesNotSayInstall() {
        val refused = UpdateUi(available = 7, failure = UpdateFailure.Signature)
        assertTrue(UpdateTexts.refused(refused))
        assertEquals("Try again", UpdateTexts.installLabel(refused))
    }

    @Test fun anyOtherFailureKeepsThePlainButton() {
        val other = UpdateUi(available = 7, failure = UpdateFailure.Storage)
        assertFalse(UpdateTexts.refused(other))
        assertEquals("Install", UpdateTexts.installLabel(other))
        assertEquals("Install", UpdateTexts.installLabel(UpdateUi(available = 7)))
        assertEquals("Downloading…", UpdateTexts.installLabel(UpdateUi(available = 7, busy = true)))
        assertEquals("Downloading… 42%", UpdateTexts.installLabel(UpdateUi(available = 7, busy = true, progress = 42)))
        assertEquals("Downloading…", UpdateTexts.installLabel(UpdateUi(available = 7, busy = true)))
    }

    @Test fun aRetryUnderWaySaysDownloading() {
        val retry = UpdateUi(available = 7, busy = true, failure = UpdateFailure.Signature)
        assertEquals("Downloading…", UpdateTexts.installLabel(retry))
    }

    @Test fun nothingToSayWhenItWorkedWaitsOrWasCancelled() {
        for (s in listOf(PackageInstaller.STATUS_SUCCESS, PackageInstaller.STATUS_PENDING_USER_ACTION,
            PackageInstaller.STATUS_FAILURE_ABORTED)) {
            assertNull(UpdateTexts.installFailure(s, "whatever"))
        }
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

    @Test fun aDifferentSigningKeySaysAndroidRefused() {
        val t = UpdateTexts.failureOf(PackageInstaller.STATUS_FAILURE_CONFLICT, signatureMessage)
        assertEquals(UpdateFailure.Signature, t)
    }

    /** Whichever status a future Android files it under: the system's own words decide. */
    @Test fun theSigningCaseFollowsTheMessageNotTheStatus() {
        assertEquals(UpdateFailure.Signature, UpdateTexts.failureOf(PackageInstaller.STATUS_FAILURE, signatureMessage))
        assertEquals(UpdateFailure.Signature, UpdateTexts.failureOf(PackageInstaller.STATUS_FAILURE_INCOMPATIBLE, signatureMessage))
    }

    @Test fun aConflictThatIsNotAboutTheKeyIsNotCalledUnsigned() {
        val t = UpdateTexts.failureOf(PackageInstaller.STATUS_FAILURE_CONFLICT, "INSTALL_FAILED_CONFLICTING_PROVIDER: x")
        assertEquals(UpdateFailure.Generic, t)
    }

    @Test fun aDowngradeSaysSo() {
        assertEquals(UpdateFailure.NewerInstalled,
            UpdateTexts.failureOf(PackageInstaller.STATUS_FAILURE_CONFLICT, "INSTALL_FAILED_VERSION_DOWNGRADE: x"))
    }

    @Test fun eachStatusHasItsFailure() {
        assertEquals(UpdateFailure.Damaged,
            UpdateTexts.failureOf(PackageInstaller.STATUS_FAILURE_INVALID, "INSTALL_PARSE_FAILED_NO_CERTIFICATES: x"))
        assertEquals(UpdateFailure.Storage, UpdateTexts.failureOf(PackageInstaller.STATUS_FAILURE_STORAGE, null))
        assertEquals(UpdateFailure.Blocked, UpdateTexts.failureOf(PackageInstaller.STATUS_FAILURE_BLOCKED, null))
        assertEquals(UpdateFailure.AndroidVersion, UpdateTexts.failureOf(PackageInstaller.STATUS_FAILURE_INCOMPATIBLE, null))
        assertEquals(UpdateFailure.TimedOut, UpdateTexts.failureOf(PackageInstaller.STATUS_FAILURE_TIMEOUT, null))
        assertEquals(UpdateFailure.Generic, UpdateTexts.failureOf(PackageInstaller.STATUS_FAILURE, null))
    }

    /** The catalogue's words (what the screen shows) are the ones the rule above is checked on, and none says uninstall. */
    @Test fun theCatalogueSaysWhatTheRuleChecks() {
        val app = RuntimeEnvironment.getApplication()
        for (f in UpdateFailure.entries) {
            assertEquals(f.name, f.english, app.getString(f.text))
            assertFalse(f.name, "uninstall" in app.getString(f.text).lowercase())
        }
        assertFalse("uninstall" in app.getString(R.string.app_update_signature_body).lowercase())
        assertEquals("An update signed with a different key", app.getString(R.string.app_update_signature_title))
    }
}
