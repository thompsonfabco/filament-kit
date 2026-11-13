package com.thompsonfabco.filamentkit.ui.printers

import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.ui.res.stringResource
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavDestination
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.toRoute
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.nav.PrinterMapRoute
import com.thompsonfabco.filamentkit.nav.PrinterRoute
import com.thompsonfabco.filamentkit.nav.PrinterSettingsRoute

/**
 * The names of the printers the person has opened, so the top bar can title a printer's screen with its name
 * (05-android-app 9.4) before and while the screen loads it again. The shell reads it; the screens write it.
 */
internal object PrinterTitles {
    private val names = mutableStateMapOf<String, String>()

    fun known(id: String, name: String) {
        if (names[id] != name) names[id] = name
    }

    fun name(id: String): String? = names[id]
}

/**
 * The top bar's title on the printer routes (05-android-app 9.4, 9.8, 9.9): the printer's name, "Map by loading
 * filament", "Printer settings". Null for any other place (and for a printer whose name is not known yet), so the
 * shell uses its own title.
 */
@Composable
internal fun printerPlaceTitle(destination: NavDestination?, entry: NavBackStackEntry?): String? = when {
    destination == null -> null
    destination.hasRoute(PrinterRoute::class) -> entry?.toRoute<PrinterRoute>()?.id?.let { PrinterTitles.name(it) }
    destination.hasRoute(PrinterSettingsRoute::class) -> stringResource(R.string.printer_settings_title)
    destination.hasRoute(PrinterMapRoute::class) -> stringResource(R.string.printer_map_by_loading)
    else -> null
}
