package com.thompsonfabco.filamentkit.nav

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.navigation.NavController
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavDestination
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavDestination.Companion.hierarchy
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.add.AddReplace
import kotlinx.serialization.Serializable

// The app's routes (05-android-app 2.5), one type per screen. A *Graph is a group: the pairing graph, or one tab's
// stack. The tab's own root is the *Route object of the same name.

@Serializable data object PairGraph
@Serializable data object PairRoute
@Serializable data object PairNetworkAccessRoute
@Serializable data object PairScanRoute
@Serializable data object PairAddressRoute
@Serializable data object PairFingerprintRoute
@Serializable data object PairCodeRoute

/** `pair/certificate/{source}`: [source] is `stored`, `qr` or `manual` (05-android-app 4.8). */
@Serializable data class PairCertificateRoute(val source: String)

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
@Serializable data object SettingsAppearanceRoute
@Serializable data object SettingsHubRoute
@Serializable data object SettingsUpdatesRoute
@Serializable data object SettingsDeveloperRoute

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
 * The top bar's back arrow (05-android-app 2.2): on every screen except the five roots and the first pairing screen
 * ([atPairStart]: `pair` or its network access step). Pairing opened over the main graph has one there too, because
 * Back returns to the screen it was opened from; the later pairing steps always have one (05 4).
 */
fun showsBackArrow(atTabRoot: Boolean, inPairing: Boolean, pairingOverMain: Boolean, atPairStart: Boolean = true): Boolean =
    !atTabRoot && (!inPairing || pairingOverMain || !atPairStart)

/** Goes to [tab], keeping every tab's stack as it was left (saved and restored). */
fun NavController.selectTab(tab: Tab) = navigate(tab.graph) {
    popUpTo<HomeRoute> { saveState = true }
    launchSingleTop = true
    restoreState = true
}

/** What [openAdd] did. */
enum class AddOpened {
    /** The new add is open. */
    Opened,

    /** The add that was open is writing: it is showing and the request is dropped. */
    KeptWriting,

    /** The add that was open holds typed fields that are not saved: it is showing; the caller asks, then [replaceAdd]. */
    NeedsLeave,
}

/**
 * Opens a NEW add flow on the Home stack, whichever tab is showing, so the bar and the stacks stay right. An add already
 * open on that stack is replaced as leaving it would be ([decide] gives the Back rule); a saved draft stays in the store
 * and is listed under Drafts on Home.
 */
fun NavController.openAdd(route: AddRoute, decide: (NavBackStackEntry) -> AddReplace = { AddReplace.Replace }): AddOpened {
    if (currentDestination.tab() != Tab.Home) selectTab(Tab.Home)
    val open = currentBackStackEntry
    if (open != null && currentDestination?.hasRoute(AddRoute::class) == true) {
        when (decide(open)) {
            AddReplace.KeepWriting -> return AddOpened.KeptWriting
            AddReplace.AskLeave -> return AddOpened.NeedsLeave
            AddReplace.Replace -> popBackStack()
        }
    }
    navigate(route)
    return AddOpened.Opened
}

/** The person chose to leave the add that holds typed fields: a new one takes its place. */
fun NavController.replaceAdd(route: AddRoute) {
    if (currentDestination?.hasRoute(AddRoute::class) == true) popBackStack()
    navigate(route)
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
