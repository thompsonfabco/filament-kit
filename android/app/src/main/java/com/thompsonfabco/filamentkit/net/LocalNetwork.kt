package com.thompsonfabco.filamentkit.net

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat

/** Shown wherever a LAN connection failed because the app may not use the local network (API 37+). */
const val LOCAL_NETWORK_MESSAGE =
    "filament-kit is not allowed to use the local network, so it can't reach your server. " +
        "Allow \"Local network\" access for filament-kit, then try again."

/**
 * The API 37 `ACCESS_LOCAL_NETWORK` runtime permission. It governs every LAN socket the app opens (API calls, the
 * certificate probe, camera streams, the APK download and NSD browsing). On older Android it does not exist and
 * counts as granted.
 */
object LocalNetwork {
    const val PERMISSION = "android.permission.ACCESS_LOCAL_NETWORK"
    const val FIRST_SDK = 37

    fun required(sdk: Int = Build.VERSION.SDK_INT): Boolean = sdk >= FIRST_SDK

    fun granted(context: Context): Boolean =
        !required() || ContextCompat.checkSelfPermission(context, PERMISSION) == PackageManager.PERMISSION_GRANTED

    /**
     * True when the permission is required and not granted. Error paths call this before saying "can't reach the
     * server". It answers false until [install] runs (JVM tests, or before the app starts).
     */
    @Volatile var missing: () -> Boolean = { false }
        private set

    /** Called once at app start. */
    fun install(context: Context) {
        val app = context.applicationContext
        missing = { !granted(app) }
    }
}
