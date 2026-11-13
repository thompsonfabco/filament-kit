package com.thompsonfabco.filamentkit.nav

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.navigation.NavController
import androidx.navigation.NavDestination
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavDestination.Companion.hierarchy
import com.thompsonfabco.filamentkit.R
import kotlinx.serialization.Serializable

// The app's routes (05-android-app 2.5), one type per screen. A *Graph is a group: the pairing graph, or one tab's
// stack. The tab's own root is the *Route object of the same name.

@Serializable data object PairGraph
@Serializable data object PairRoute

@Serializable data object HomeGraph
@Serializable data object HomeRoute
@Serializable data class AddRoute(val tag: String? = null, val draft: String? = null, val manual: Boolean = false)
@Serializable data object AddProfileRoute

@Serializable data object SpoolsGraph
@Serializable data object SpoolsRoute

@Serializable data object PrintersGraph
@Serializable data object PrintersRoute
@Serializable data class PrinterRoute(val id: String)
@Serializable data class PrinterMapRoute(val id: String)

@Serializable data object RecentGraph
@Serializable data object RecentRoute
@Serializable data class RecordRoute(val hid: String)

@Serializable data object SettingsGraph
@Serializable data object SettingsRoute
@Serializable data object LicencesRoute

/** The five destinations of the bottom bar and the rail, in their order (05-android-app 2.3). */
enum class Tab(
    val graph: Any,
    val root: Any,
    @StringRes val label: Int,
    @DrawableRes val icon: Int,
) {
    Home(HomeGraph, HomeRoute, R.string.nav_home, R.drawable.sw_ic_overview),
    Spools(SpoolsGraph, SpoolsRoute, R.string.nav_spools, R.drawable.sw_ic_spool),
    Printers(PrintersGraph, PrintersRoute, R.string.nav_printers, R.drawable.sw_ic_printer),
    Recent(RecentGraph, RecentRoute, R.string.nav_recent, R.drawable.sw_ic_clock),
    Settings(SettingsGraph, SettingsRoute, R.string.nav_settings, R.drawable.sw_ic_settings),
}

/** The tab whose graph [this] belongs to; null on the pairing graph. */
fun NavDestination?.tab(): Tab? = this?.let { d -> Tab.entries.firstOrNull { t -> d.hierarchy.any { it.hasRoute(t.graph::class) } } }

/** The pairing graph is showing (first start, or pushed over the main graph). */
fun NavDestination?.inPairing(): Boolean = this?.hierarchy?.any { it.hasRoute(PairGraph::class) } == true

/** The screen is the root of its tab. */
fun NavDestination?.isTabRoot(): Boolean = this != null && Tab.entries.any { hasRoute(it.root::class) }

/** What pressing a bar or rail item does (05-android-app 2.3). */
enum class TabTap {
    /** Another destination: go there, with its own stack as it was left. */
    Switch,

    /** The selected destination, deeper in it: back to its root. */
    PopToRoot,

    /** The selected destination, already at its root (it scrolls to the top where the screen can; none can yet). */
    Stay,
}

fun tabTap(current: Tab?, tapped: Tab, atRoot: Boolean): TabTap = when {
    current != tapped -> TabTap.Switch
    atRoot -> TabTap.Stay
    else -> TabTap.PopToRoot
}

/**
 * The top bar's back arrow (05-android-app 2.2): on every screen except the five roots and the first pairing screen.
 * Pairing opened over the main graph has one, because Back returns to the screen it was opened from.
 */
fun showsBackArrow(atTabRoot: Boolean, inPairing: Boolean, pairingOverMain: Boolean): Boolean =
    !atTabRoot && (!inPairing || pairingOverMain)

/** Goes to [tab], keeping every tab's stack as it was left (saved and restored). */
fun NavController.selectTab(tab: Tab) = navigate(tab.graph) {
    popUpTo<HomeRoute> { saveState = true }
    launchSingleTop = true
    restoreState = true
}

/**
 * Opens the add flow on the Home stack, whichever tab is showing, so the bar and the stacks stay right. An add already
 * open on that stack is kept, not covered by a second one; returns true then (the caller hands it the tag).
 */
fun NavController.openAdd(route: AddRoute): Boolean {
    if (currentDestination.tab() != Tab.Home) selectTab(Tab.Home)
    if (currentDestination?.hasRoute(AddRoute::class) == true) return true
    navigate(route)
    return false
}

private const val MAX_STACK_DEPTH = 32

/**
 * Back to the current tab's root by pressing system Back ([back]) one screen at a time, so each screen's own rules
 * (unsaved typing, work that must finish) run as they do for Back. It stops as soon as a screen keeps Back.
 */
fun NavController.popToRootThrough(back: () -> Unit) {
    repeat(MAX_STACK_DEPTH) {
        if (currentDestination.isTabRoot()) return
        val before = currentBackStackEntry
        back()
        if (currentBackStackEntry === before) return
    }
}

/** Drops every stack saved by switching tabs, with its view models (another Hub, or none: nothing of the old one stays). */
fun NavController.clearSavedStacks() {
    Tab.entries.forEach { tab -> runCatching { clearBackStack(tab.graph) } }
}
