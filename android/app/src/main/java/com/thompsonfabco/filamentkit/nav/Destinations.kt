package com.thompsonfabco.filamentkit.nav

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.navigation.NavController
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavDestination
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.toRoute
import com.thompsonfabco.filamentkit.R
import com.thompsonfabco.filamentkit.ui.add.AddReplace
import com.thompsonfabco.filamentkit.ui.add.AddStep
import com.thompsonfabco.filamentkit.ui.spool.SpoolCache
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

// The four steps of Add spools (05-android-app 2.5, 6): each a destination of its own, all of one draft.
@Serializable data class AddPhotosRoute(val draftId: String)
@Serializable data class AddReviewRoute(val draftId: String)
@Serializable data class AddPreviewRoute(val draftId: String)
@Serializable data class AddDoneRoute(val draftId: String)

@Serializable data object AddProfileRoute

/** The top bar's title on [AddProfileRoute] (05-android-app 8); the shell and the AUT-8 test both read it. */
@get:StringRes
internal val AddProfileTitle: Int get() = R.string.catalog_title

@Serializable data object SpoolsGraph
@Serializable data object SpoolsRoute

// The spool screens and the tag screens are in the graph of every tab (05-android-app 2.5, "Shared"): they open on the stack
// of the tab that is selected.
/** [result] is a [com.thompsonfabco.filamentkit.ui.spool.SpoolResult] already shown by the screen that led here (a link), as its text. */
@Serializable data class SpoolRoute(val id: Int, val tag: String? = null, val result: String? = null)
@Serializable data class SpoolLoadRoute(val id: Int)
@Serializable data class SpoolLoadSlotRoute(val id: Int, val printerId: String, val skipped: Boolean = false)
@Serializable data class SpoolLoadPreviewRoute(val id: Int, val printerId: String, val slot: String)
@Serializable data class TagRoute(val uid: String)
@Serializable data class TagLinkRoute(val uid: String)
@Serializable data class TagLinkPreviewRoute(val uid: String, val spoolId: Int, val gross: String? = null)

@Serializable data object PrintersGraph
@Serializable data object PrintersRoute
@Serializable data class PrinterRoute(val id: String)
@Serializable data class PrinterMapRoute(val id: String)

@Serializable data object RecentGraph
@Serializable data object RecentRoute
@Serializable data class RecordRoute(val hid: String)
@Serializable data class RecordEditRoute(val hid: String, val item: Int)
@Serializable data class RecordPhotoRoute(val hid: String, val n: Int)

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

/** The destination of a step of the draft [draftId]. */
internal fun addRoute(step: AddStep, draftId: String): Any = when (step) {
    AddStep.Photos -> AddPhotosRoute(draftId)
    AddStep.Check -> AddReviewRoute(draftId)
    AddStep.Preview -> AddPreviewRoute(draftId)
    AddStep.Done -> AddDoneRoute(draftId)
}

/** The screen is one of the four steps of Add spools. */
fun NavDestination?.inAdd(): Boolean = this != null && (
    hasRoute(AddPhotosRoute::class) || hasRoute(AddReviewRoute::class) ||
        hasRoute(AddPreviewRoute::class) || hasRoute(AddDoneRoute::class)
    )

/** The draft an Add spools entry belongs to; null for any other entry. */
fun NavBackStackEntry.addDraftId(): String? = when {
    destination.hasRoute(AddPhotosRoute::class) -> toRoute<AddPhotosRoute>().draftId
    destination.hasRoute(AddReviewRoute::class) -> toRoute<AddReviewRoute>().draftId
    destination.hasRoute(AddPreviewRoute::class) -> toRoute<AddPreviewRoute>().draftId
    destination.hasRoute(AddDoneRoute::class) -> toRoute<AddDoneRoute>().draftId
    else -> null
}

/** What [openAdd] did. */
enum class AddOpened {
    /** The new add is open. */
    Opened,

    /** The add that was open is writing: it is showing and the request is dropped. */
    KeptWriting,
}

/**
 * Opens a NEW add on the Home stack, whichever tab is showing, so the bar and the stacks stay right. An add already
 * open on that stack is replaced as leaving it would be ([decide] gives the Back rule for its draft); its draft stays in
 * the store and is listed under Drafts on Home. [first] makes the new add's first destination (and its draft) only when
 * the request goes ahead.
 */
fun NavController.openAdd(first: () -> Any, decide: (draftId: String) -> AddReplace = { AddReplace.Replace }): AddOpened {
    if (currentDestination.tab() != Tab.Home) selectTab(Tab.Home)
    val open = currentBackStackEntry?.addDraftId()
    if (open != null && decide(open) == AddReplace.KeepWriting) return AddOpened.KeptWriting
    closeAdd()
    navigate(first())
    return AddOpened.Opened
}

/** Takes every step of the add that is open off the stack (the stack is back where the add began). */
fun NavController.closeAdd() {
    repeat(MAX_STACK_DEPTH) { if (currentDestination.inAdd()) popBackStack() else return }
}

/**
 * The screen of step [mine] follows the flow: when the draft is on step [desired] the stack goes there. Forward pushes
 * the step; backward pops to it (or replaces this one when the stack under it is not that step, as after the app was
 * stopped and the stack came back with the flow reset to an earlier step).
 */
internal fun NavController.followStep(draftId: String, mine: AddStep, desired: AddStep) {
    if (desired == mine) return
    if (desired.ordinal > mine.ordinal) {
        navigate(addRoute(desired, draftId))
        return
    }
    val below = previousBackStackEntry
    val target = addRoute(desired, draftId)
    if (below != null && below.addDraftId() == draftId && below.destination.hasRoute(target::class)) {
        popBackStack()
    } else {
        navigate(target) { popUpTo(addRoute(mine, draftId)) { inclusive = true } }
    }
}

/**
 * A tag tap that does nothing (05 2.6): the tag of the tag screen that is open ([tagScreen]) or of the spool screen that is
 * open ([spoolsTag]) is tapped again.
 */
fun tapIsForTheOpenTag(uid: String, tagScreen: String?, spoolsTag: String?): Boolean =
    uid == tagScreen || uid.equals(spoolsTag, ignoreCase = true)

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
    // the spools seen belong to the old Hub too
    SpoolCache.clear()
}
