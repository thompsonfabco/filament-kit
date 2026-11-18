package com.thompsonfabco.filamentkit.alerts

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/** After the phone starts or the app is updated, the watching service starts again when the switch is on and a Hub is paired. */
class AlertsBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                AlertsLauncher.startIfNeeded(context.applicationContext)
            } finally {
                pending.finish()
            }
        }
    }
}
