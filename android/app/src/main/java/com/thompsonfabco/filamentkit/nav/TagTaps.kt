package com.thompsonfabco.filamentkit.nav

import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavController
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.toRoute
import com.thompsonfabco.filamentkit.ui.spool.SpoolCache

/** What [routeTagTap] did with a tap. */
enum class TagTapped {
    /** The screen takes the tap itself (photos, check): nothing is routed. */
    LeftToScreen,

    /** A load or a link is being written: the tap waits and the person is told. */
    Waits,

    /** The tag of the screen that is open was tapped again: nothing happens. */
    SameTag,

    /** tag/{uid} is open. */
    Opened,
}

/** The result of [routeTagTap]: what happened, and the tag that is still waiting for a write to end (null for none). */
data class TagTapResult(val what: TagTapped, val queued: String?)

/**
 * Routes a tag tap (05-android-app 2.6): the add steps that take taps themselves keep it; during a write ([writing]) it
 * waits; otherwise tag/{uid} opens on the current stack. A tap that is not waiting replaces the one that was ([queued]),
 * so a tag that waited through a failed write never opens on top of a later one.
 */
fun NavController.routeTagTap(uid: String, writing: Boolean, queued: String?): TagTapResult = when {
    currentDestination.takesTagTaps() -> TagTapResult(TagTapped.LeftToScreen, queued)
    writing -> TagTapResult(TagTapped.Waits, uid)
    else -> TagTapResult(if (openTag(uid)) TagTapped.Opened else TagTapped.SameTag, null)
}

/**
 * Opens tag/{uid}; a different tag replaces the tag screen (and the link steps on it). False when the tag of the tag
 * screen or of the spool screen that is open was tapped again (case does not matter: the Hub lowercases, the tag may not).
 */
fun NavController.openTag(uid: String): Boolean {
    val here = currentBackStackEntry
    val tagScreen = here?.let(::tagUidOf)
    val spoolsTag = here?.takeIf { it.destination.hasRoute(SpoolRoute::class) }?.let {
        val route = it.toRoute<SpoolRoute>()
        route.tag ?: SpoolCache.get(route.id)?.tag
    }
    if (uid.equals(tagScreen, ignoreCase = true) || uid.equals(spoolsTag, ignoreCase = true)) return false
    if (tagScreen != null) popBackStack<TagRoute>(inclusive = true)
    navigate(TagRoute(uid))
    return true
}

/** The tag a tag screen (the lookup or a link step) is about; null on any other screen. */
internal fun tagUidOf(entry: NavBackStackEntry): String? {
    val d = entry.destination
    return when {
        d.hasRoute(TagRoute::class) -> entry.toRoute<TagRoute>().uid
        d.hasRoute(TagLinkRoute::class) -> entry.toRoute<TagLinkRoute>().uid
        d.hasRoute(TagLinkPreviewRoute::class) -> entry.toRoute<TagLinkPreviewRoute>().uid
        else -> null
    }
}

/**
 * A new add from Home: nothing starts when an add step is already showing, so two quick taps make one draft. [first]
 * makes the draft and its first destination. True when it opened.
 */
fun NavController.openAddOnce(first: () -> Any): Boolean {
    if (currentDestination.inAdd()) return false
    navigate(first())
    return true
}
