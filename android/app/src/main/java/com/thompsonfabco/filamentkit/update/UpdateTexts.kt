package com.thompsonfabco.filamentkit.update

import android.content.pm.PackageInstaller

/** Texts of the update banner and of a failed install. */
object UpdateTexts {
    /** Complete on its own: the guide is one more tap and needs the internet, and this must work on a server's LAN. */
    const val NOT_SIGNED_LIKE_YOUR_APP = "Don't install this update: it is not signed like your app. " +
        "Check who runs your server and where its app came from."
    const val REFUSED_GUIDE_LABEL = "What this means"
    const val REFUSED_GUIDE_URL = "https://github.com/thompsonfabco/filament-kit/blob/main/docs/install-android-app.md#update-refused"
    private const val GENERIC = "The update could not be installed."

    /** The banner is showing the refusal of a differently signed update. */
    fun refused(ui: UpdateUi): Boolean = ui.error == NOT_SIGNED_LIKE_YOUR_APP

    /** Trying again is how a corrected server copy gets picked up, so it stays, but it must not read as "go ahead". */
    fun installLabel(ui: UpdateUi): String = when {
        ui.busy -> "Downloading…"
        refused(ui) -> "Try again after fixing the server"
        else -> "Install"
    }

    /** `version` is the server's release, the one the update comes with; the APK's own name is always "1.0". */
    fun bannerTitle(version: String?): String =
        version?.trim()?.ifBlank { null }?.let { "Update available (filament-kit $it)" } ?: "Update available"

    /**
     * What to tell the user about a finished install session, or null when there is nothing to say (it worked, it is
     * waiting for the user, or the user cancelled). The system's own [message] decides the signing case, because
     * [status] alone is not specific enough: Android folds several causes into one status. It is never told to
     * uninstall: a different key inside the in-app updater is the one sign of a forged APK.
     */
    fun installFailure(status: Int, message: String?): String? {
        val m = message.orEmpty()
        return when {
            status == PackageInstaller.STATUS_SUCCESS || status == PackageInstaller.STATUS_PENDING_USER_ACTION ||
                status == PackageInstaller.STATUS_FAILURE_ABORTED -> null
            "UPDATE_INCOMPATIBLE" in m || "signatures do not match" in m -> NOT_SIGNED_LIKE_YOUR_APP
            "VERSION_DOWNGRADE" in m -> "This phone already has a newer version of the app."
            status == PackageInstaller.STATUS_FAILURE_INVALID -> "The download is damaged. Tap Install to try again."
            status == PackageInstaller.STATUS_FAILURE_STORAGE -> "Not enough storage on this phone to install the update."
            status == PackageInstaller.STATUS_FAILURE_BLOCKED -> "This phone's settings or another app blocked the update."
            status == PackageInstaller.STATUS_FAILURE_INCOMPATIBLE -> "This update does not work on this phone's Android version."
            status == PackageInstaller.STATUS_FAILURE_TIMEOUT -> "The install took too long. Tap Install to try again."
            m.isNotBlank() -> "$GENERIC ($m)"
            else -> GENERIC
        }
    }
}
