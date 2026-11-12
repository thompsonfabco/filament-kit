package com.thompsonfabco.filamentkit.ui

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import com.thompsonfabco.filamentkit.net.LocalNetwork

/**
 * The API 37 local network permission as seen by the UI. [granted] is always true below API 37. [showSettings] is
 * true once the system will no longer show its request dialog (asked before and no rationale any more), so the
 * only way left is the app's settings page.
 */
class LocalNetworkAccess(
    val granted: Boolean,
    val showSettings: Boolean,
    val request: () -> Unit,
    val openSettings: () -> Unit,
)

/**
 * Tracks and requests `ACCESS_LOCAL_NETWORK`. With [autoRequest] the system dialog opens once when this first
 * composes without the permission (at app start). [onGranted] runs when the permission turns granted (after the
 * dialog, or on returning from the app's settings page).
 */
@Composable
fun rememberLocalNetworkAccess(autoRequest: Boolean, onGranted: () -> Unit): LocalNetworkAccess {
    val context = LocalContext.current
    val currentOnGranted by rememberUpdatedState(onGranted)
    var granted by remember { mutableStateOf(LocalNetwork.granted(context)) }
    var asked by rememberSaveable { mutableStateOf(false) }
    var rationale by remember { mutableStateOf(false) }

    fun recheck() {
        val now = LocalNetwork.granted(context)
        rationale = context.findActivity()?.shouldShowRequestPermissionRationale(LocalNetwork.PERMISSION) == true
        if (now && !granted) {
            granted = true
            currentOnGranted()
        } else {
            granted = now
        }
    }

    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        asked = true
        recheck()
    }
    LaunchedEffect(Unit) {
        if (autoRequest && !granted && !asked) launcher.launch(LocalNetwork.PERMISSION)
    }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { recheck() }

    return LocalNetworkAccess(
        granted = granted,
        showSettings = asked && !granted && !rationale,
        request = { launcher.launch(LocalNetwork.PERMISSION) },
        openSettings = { context.openAppSettings() },
    )
}

/** Plain explanation with "Allow", replaced by "Open app settings" once the system stops asking. */
@Composable
fun LocalNetworkPanel(access: LocalNetworkAccess, modifier: Modifier = Modifier) {
    Card(modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Allow local network access", style = MaterialTheme.typography.titleMedium)
            Text(
                "filament-kit talks to your filament-kit server over your home Wi-Fi. Android asks you to allow " +
                    "that before the app can find the server, pair, show printers or download updates. It may call " +
                    "it \"Local network\" or \"Nearby devices\", and the app only uses it to find and reach your server.",
            )
            if (access.showSettings) {
                Text(
                    "Android will not ask again. Open the app settings, choose Permissions, and allow " +
                        "\"Local network\" (it may be listed under Nearby devices).",
                    style = MaterialTheme.typography.bodySmall,
                )
                Button(onClick = access.openSettings, modifier = Modifier.fillMaxWidth()) {
                    Text("Open app settings")
                }
            } else {
                Button(onClick = access.request, modifier = Modifier.fillMaxWidth()) { Text("Allow") }
            }
        }
    }
}

private fun Context.findActivity(): Activity? {
    var c: Context? = this
    while (c is ContextWrapper) {
        if (c is Activity) return c
        c = c.baseContext
    }
    return null
}

internal fun Context.openAppSettings() {
    startActivity(
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
    )
}
