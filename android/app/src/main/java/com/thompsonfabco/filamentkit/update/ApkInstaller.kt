package com.thompsonfabco.filamentkit.update

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.provider.Settings
import android.widget.Toast
import androidx.core.net.toUri
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext

/** Installs an APK through a [PackageInstaller] session; the system asks the user to confirm. */
class ApkInstaller(context: Context) : ApkInstall {
    private val context = context.applicationContext

    override fun canInstall(): Boolean = context.packageManager.canRequestPackageInstalls()

    override fun requestPermission() {
        val intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, "package:${context.packageName}".toUri())
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    override val confirmPending: Flow<Boolean> = PendingConfirm.intent.map { it != null }

    override fun showConfirm() {
        val confirm = PendingConfirm.intent.value ?: return
        context.startActivity(Intent(confirm).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    override suspend fun install(apk: File) = withContext(Dispatchers.IO) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
            .apply { setAppPackageName(context.packageName) }
        val id = installer.createSession(params)
        installer.openSession(id).use { session ->
            try {
                session.openWrite("filament-kit.apk", 0, apk.length()).use { out ->
                    apk.inputStream().use { it.copyTo(out) }
                    session.fsync(out)
                }
                val status = PendingIntent.getBroadcast(
                    context,
                    id,
                    Intent(context, InstallResultReceiver::class.java),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
                )
                session.commit(status.intentSender)
            } catch (e: Exception) {
                session.abandon()
                throw e
            }
        }
    }
}

/**
 * The system install confirmation, kept until the session reports a final status: starting it from the receiver can
 * fail (or be blocked while the app is in the background), so Home offers "Tap to install" while it is set.
 */
internal object PendingConfirm {
    val intent = MutableStateFlow<Intent?>(null)
}

/** Receives the install session's status: shows the system confirmation, or tells the user why it failed. */
class InstallResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION")
                val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT) ?: return
                PendingConfirm.intent.value = confirm
                try {
                    context.startActivity(Intent(confirm).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                } catch (_: RuntimeException) {
                    // not allowed from here; Home shows "Tap to install"
                }
            }
            PackageInstaller.STATUS_SUCCESS -> PendingConfirm.intent.value = null
            PackageInstaller.STATUS_FAILURE_ABORTED -> PendingConfirm.intent.value = null // the user cancelled
            else -> {
                PendingConfirm.intent.value = null
                val why = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)
                Toast.makeText(context, "The update could not be installed" + (why?.let { ": $it" } ?: ""), Toast.LENGTH_LONG).show()
            }
        }
    }
}
