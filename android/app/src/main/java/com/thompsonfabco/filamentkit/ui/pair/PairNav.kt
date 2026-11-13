package com.thompsonfabco.filamentkit.ui.pair

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.NavController
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.toRoute
import com.thompsonfabco.filamentkit.data.SettingsStore
import com.thompsonfabco.filamentkit.nav.PairAddressRoute
import com.thompsonfabco.filamentkit.nav.PairCertificateRoute
import com.thompsonfabco.filamentkit.nav.PairCodeRoute
import com.thompsonfabco.filamentkit.nav.PairFingerprintRoute
import com.thompsonfabco.filamentkit.nav.PairGraph
import com.thompsonfabco.filamentkit.nav.PairNetworkAccessRoute
import com.thompsonfabco.filamentkit.nav.PairRoute
import com.thompsonfabco.filamentkit.nav.PairScanRoute
import com.thompsonfabco.filamentkit.session.PairNotice

/** The route name of a certificate question, from where the expected certificate came from. */
internal fun MismatchSource.routeSource(): String = name.lowercase()

/**
 * The destination pairing is at (05-android-app 4): one per step. Without local network access it is the access step
 * whatever the step is; a certificate question comes before the step it interrupted.
 */
internal fun pairRouteFor(ui: PairUi, accessGranted: Boolean): Any = when {
    !accessGranted -> PairNetworkAccessRoute
    ui.mismatch != null -> PairCertificateRoute(ui.mismatch.source.routeSource())
    else -> when (ui.step) {
        Step.Choose, Step.Done -> PairRoute
        Step.Address -> PairAddressRoute
        Step.Confirm -> PairFingerprintRoute
        Step.Code -> PairCodeRoute
    }
}

/** The saved pairing's certificate question and the access step stand alone, with no step under them. */
private fun replacesGraph(route: Any): Boolean =
    route is PairNetworkAccessRoute || route is PairCertificateRoute && route.source == MismatchSource.STORED.routeSource()

private fun NavController.showing(target: Any): Boolean {
    val here = currentDestination ?: return false
    return when (target) {
        is PairNetworkAccessRoute -> here.hasRoute(PairNetworkAccessRoute::class)
        // the scanner is a screen of its own that the first step opens: the first step does not close it
        is PairRoute -> here.hasRoute(PairRoute::class) || here.hasRoute(PairScanRoute::class)
        is PairAddressRoute -> here.hasRoute(PairAddressRoute::class)
        is PairFingerprintRoute -> here.hasRoute(PairFingerprintRoute::class)
        is PairCodeRoute -> here.hasRoute(PairCodeRoute::class)
        is PairCertificateRoute ->
            here.hasRoute(PairCertificateRoute::class) && currentBackStackEntry?.toRoute<PairCertificateRoute>() == target
        else -> false
    }
}

/** Moves the pairing graph's stack to [target]: back to it when it is already under the screen shown, else onto it. */
internal fun NavController.showPairStep(target: Any) {
    if (showing(target)) return
    val here = currentDestination ?: return
    val standalone = here.hasRoute(PairNetworkAccessRoute::class) || here.hasRoute(PairCertificateRoute::class)
    when {
        runCatching { getBackStackEntry(target) }.isSuccess -> popBackStack(target, inclusive = false)
        replacesGraph(target) || standalone -> navigate(target) {
            popUpTo<PairGraph> { inclusive = false }
            launchSingleTop = true
        }
        else -> navigate(target) { launchSingleTop = true }
    }
}

/**
 * Keeps the destination in step with [vm]: composed once while pairing is open. A changed certificate that another
 * screen found ([notice]) is shown once as the question of a saved pairing.
 */
@Composable
internal fun PairRouteSync(
    nav: NavController,
    vm: PairViewModel,
    accessGranted: Boolean,
    notice: PairNotice?,
    onPaired: () -> Unit,
) {
    val ui by vm.state.collectAsStateWithLifecycle()
    val paired by rememberUpdatedState(onPaired)
    LaunchedEffect(ui.step) { if (ui.step == Step.Done) paired() }
    var mismatchShown by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(notice) {
        if (notice is PairNotice.CertChanged && !mismatchShown) {
            mismatchShown = true
            vm.showMismatch(notice.expected, notice.actual)
        }
    }
    val target = pairRouteFor(ui, accessGranted)
    // Done leaves through the caller's finishing step, not by a destination of its own.
    LaunchedEffect(target, ui.step == Step.Done) { if (ui.step != Step.Done) nav.showPairStep(target) }
}

/** The pairing view model, shared by every pairing destination: it belongs to the pairing graph's entry [owner]. */
@Composable
internal fun pairViewModel(owner: ViewModelStoreOwner, settings: SettingsStore): PairViewModel =
    viewModel(owner, factory = viewModelFactory { initializer { PairViewModel(settings, NetPairingBackend()) } })
