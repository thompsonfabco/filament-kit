package com.thompsonfabco.filamentkit

import android.app.UiModeManager
import android.graphics.Color as AndroidColor
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.LocalOnBackPressedDispatcherOwner
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.TextButton
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.createSavedStateHandle
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavDestination
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.navigation
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import com.thompsonfabco.filamentkit.nav.AddProfileRoute
import com.thompsonfabco.filamentkit.nav.AddProfileTitle
import com.thompsonfabco.filamentkit.nav.AddOpened
import com.thompsonfabco.filamentkit.nav.AddRoute
import com.thompsonfabco.filamentkit.nav.HomeGraph
import com.thompsonfabco.filamentkit.nav.HomeRoute
import com.thompsonfabco.filamentkit.nav.LicencesRoute
import com.thompsonfabco.filamentkit.nav.PairGraph
import com.thompsonfabco.filamentkit.nav.PairAddressRoute
import com.thompsonfabco.filamentkit.nav.PairCertificateRoute
import com.thompsonfabco.filamentkit.nav.PairCodeRoute
import com.thompsonfabco.filamentkit.nav.PairFingerprintRoute
import com.thompsonfabco.filamentkit.nav.PairNetworkAccessRoute
import com.thompsonfabco.filamentkit.nav.PairRoute
import com.thompsonfabco.filamentkit.nav.PairScanRoute
import com.thompsonfabco.filamentkit.nav.PrinterMapRoute
import com.thompsonfabco.filamentkit.nav.PrinterRoute
import com.thompsonfabco.filamentkit.nav.PrintersGraph
import com.thompsonfabco.filamentkit.nav.PrintersRoute
import com.thompsonfabco.filamentkit.nav.RecentGraph
import com.thompsonfabco.filamentkit.nav.RecentRoute
import com.thompsonfabco.filamentkit.nav.RecordEditRoute
import com.thompsonfabco.filamentkit.nav.RecordPhotoRoute
import com.thompsonfabco.filamentkit.nav.RecordRoute
import com.thompsonfabco.filamentkit.nav.SettingsAppearanceRoute
import com.thompsonfabco.filamentkit.nav.SettingsDeveloperRoute
import com.thompsonfabco.filamentkit.nav.SettingsGraph
import com.thompsonfabco.filamentkit.nav.SettingsHubRoute
import com.thompsonfabco.filamentkit.nav.SettingsRoute
import com.thompsonfabco.filamentkit.nav.SettingsUpdatesRoute
import com.thompsonfabco.filamentkit.nav.SpoolLoadPreviewRoute
import com.thompsonfabco.filamentkit.nav.SpoolLoadRoute
import com.thompsonfabco.filamentkit.nav.SpoolLoadSlotRoute
import com.thompsonfabco.filamentkit.nav.SpoolRoute
import com.thompsonfabco.filamentkit.nav.TagLinkPreviewRoute
import com.thompsonfabco.filamentkit.nav.TagLinkRoute
import com.thompsonfabco.filamentkit.nav.TagRoute
import com.thompsonfabco.filamentkit.nav.SpoolsGraph
import com.thompsonfabco.filamentkit.nav.SpoolsRoute
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.nav.TabTap
import com.thompsonfabco.filamentkit.nav.clearSavedStacks
import com.thompsonfabco.filamentkit.nav.hubAddress
import com.thompsonfabco.filamentkit.nav.hubIdentity
import com.thompsonfabco.filamentkit.nav.hubState
import com.thompsonfabco.filamentkit.nav.inPairing
import com.thompsonfabco.filamentkit.nav.isTabRoot
import com.thompsonfabco.filamentkit.nav.keepLastKnown
import com.thompsonfabco.filamentkit.nav.openAdd
import com.thompsonfabco.filamentkit.nav.replaceAdd
import com.thompsonfabco.filamentkit.nav.popToRootThrough
import com.thompsonfabco.filamentkit.nav.selectTab
import com.thompsonfabco.filamentkit.nav.showsBackArrow
import com.thompsonfabco.filamentkit.nav.tab
import com.thompsonfabco.filamentkit.nav.tabTap
import com.thompsonfabco.filamentkit.nav.tapIsForTheOpenTag
import com.thompsonfabco.filamentkit.net.Api
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.net.ServerInfo
import com.thompsonfabco.filamentkit.session.CONNECTION_POLL_MS
import com.thompsonfabco.filamentkit.session.AppViewModel
import com.thompsonfabco.filamentkit.session.Connection
import com.thompsonfabco.filamentkit.session.PairNotice
import com.thompsonfabco.filamentkit.session.canTrust
import com.thompsonfabco.filamentkit.session.isPaired
import com.thompsonfabco.filamentkit.tags.TagEvents
import com.thompsonfabco.filamentkit.tags.disableTagReader
import com.thompsonfabco.filamentkit.tags.enableTagReader
import com.thompsonfabco.filamentkit.ui.rememberLocalNetworkAccess
import com.thompsonfabco.filamentkit.ui.add.AddSpoolsScreen
import com.thompsonfabco.filamentkit.ui.add.AddViewModel
import com.thompsonfabco.filamentkit.ui.add.addReplaceOf
import com.thompsonfabco.filamentkit.ui.add.DebugPhotos
import com.thompsonfabco.filamentkit.ui.add.IntakeApi
import com.thompsonfabco.filamentkit.ui.add.TagTaps
import com.thompsonfabco.filamentkit.ui.components.AppearanceMenu
import com.thompsonfabco.filamentkit.ui.components.HubFacts
import com.thompsonfabco.filamentkit.ui.components.HubNotice
import com.thompsonfabco.filamentkit.ui.components.HubNoticeKind
import com.thompsonfabco.filamentkit.ui.components.HubSheet
import com.thompsonfabco.filamentkit.ui.components.HubSheetActions
import com.thompsonfabco.filamentkit.ui.components.LocalNetworkNotice
import com.thompsonfabco.filamentkit.ui.components.LocalToast
import com.thompsonfabco.filamentkit.ui.components.LocalTopBarActions
import com.thompsonfabco.filamentkit.ui.components.TopBarActions
import com.thompsonfabco.filamentkit.ui.components.SwAction
import com.thompsonfabco.filamentkit.ui.components.SwButtonKind
import com.thompsonfabco.filamentkit.ui.components.SwConnectionChip
import com.thompsonfabco.filamentkit.ui.components.SwDialog
import com.thompsonfabco.filamentkit.ui.components.SwDialogButton
import com.thompsonfabco.filamentkit.ui.components.SwNav
import com.thompsonfabco.filamentkit.ui.components.SwToastHost
import com.thompsonfabco.filamentkit.ui.components.SwToastState
import com.thompsonfabco.filamentkit.ui.components.SwTopBar
import com.thompsonfabco.filamentkit.ui.history.HistoryEditEntry
import com.thompsonfabco.filamentkit.ui.history.HistoryListEntry
import com.thompsonfabco.filamentkit.ui.history.HistoryPhotoEntry
import com.thompsonfabco.filamentkit.ui.history.HistoryRecordEntry
import com.thompsonfabco.filamentkit.ui.home.HomePrintersViewModel
import com.thompsonfabco.filamentkit.ui.home.HomeScreen
import com.thompsonfabco.filamentkit.ui.home.VersionLine
import com.thompsonfabco.filamentkit.ui.home.labelReaderOff
import com.thompsonfabco.filamentkit.ui.home.showLabelPhotos
import com.thompsonfabco.filamentkit.ui.home.versionLine
import com.thompsonfabco.filamentkit.ui.pair.MismatchSource
import com.thompsonfabco.filamentkit.ui.pair.PairAddressScreen
import com.thompsonfabco.filamentkit.ui.pair.PairCertificateScreen
import com.thompsonfabco.filamentkit.ui.pair.PairCodeScreen
import com.thompsonfabco.filamentkit.ui.pair.PairFingerprintScreen
import com.thompsonfabco.filamentkit.ui.pair.PairNetworkAccessScreen
import com.thompsonfabco.filamentkit.ui.pair.PairRouteSync
import com.thompsonfabco.filamentkit.ui.pair.PairStartScreen
import com.thompsonfabco.filamentkit.ui.pair.QrScanner
import com.thompsonfabco.filamentkit.ui.pair.pairViewModel
import com.thompsonfabco.filamentkit.ui.pair.routeSource
import com.thompsonfabco.filamentkit.ui.printers.ManualMapEntry
import com.thompsonfabco.filamentkit.ui.printers.PrinterEntry
import com.thompsonfabco.filamentkit.ui.printers.PrintersListEntry
import com.thompsonfabco.filamentkit.ui.printers.TrustAction
import com.thompsonfabco.filamentkit.ui.profile.AddProfileScreen
import com.thompsonfabco.filamentkit.ui.profile.AddProfileViewModel
import com.thompsonfabco.filamentkit.ui.profile.ProfileApi
import com.thompsonfabco.filamentkit.ui.search.SearchScreen
import com.thompsonfabco.filamentkit.ui.search.SearchViewModel
import com.thompsonfabco.filamentkit.ui.settings.HubPage
import com.thompsonfabco.filamentkit.ui.settings.SettingsActions
import com.thompsonfabco.filamentkit.ui.settings.SettingsFacts
import com.thompsonfabco.filamentkit.ui.settings.SettingsGroup
import com.thompsonfabco.filamentkit.ui.settings.SettingsGroupPage
import com.thompsonfabco.filamentkit.ui.settings.SettingsHub
import com.thompsonfabco.filamentkit.ui.settings.SettingsScreen
import com.thompsonfabco.filamentkit.ui.settings.UpdateActions
import com.thompsonfabco.filamentkit.ui.spool.LinkFindScreen
import com.thompsonfabco.filamentkit.ui.spool.LinkFindViewModel
import com.thompsonfabco.filamentkit.ui.spool.LinkPreviewScreen
import com.thompsonfabco.filamentkit.ui.spool.LinkPreviewViewModel
import com.thompsonfabco.filamentkit.ui.spool.LoadBackend
import com.thompsonfabco.filamentkit.ui.spool.LoadPreviewScreen
import com.thompsonfabco.filamentkit.ui.spool.LoadPreviewViewModel
import com.thompsonfabco.filamentkit.ui.spool.LoadPrintersScreen
import com.thompsonfabco.filamentkit.ui.spool.LoadPrintersViewModel
import com.thompsonfabco.filamentkit.ui.spool.LoadSlotsScreen
import com.thompsonfabco.filamentkit.ui.spool.LoadSlotsViewModel
import com.thompsonfabco.filamentkit.ui.spool.SpoolBackend
import com.thompsonfabco.filamentkit.ui.spool.SpoolResult
import com.thompsonfabco.filamentkit.ui.spool.SpoolCache
import com.thompsonfabco.filamentkit.ui.spool.SpoolScreen
import com.thompsonfabco.filamentkit.ui.spool.SpoolSummary
import com.thompsonfabco.filamentkit.ui.spool.SpoolViewModel
import com.thompsonfabco.filamentkit.ui.spool.TagScreen
import com.thompsonfabco.filamentkit.ui.spool.TagViewModel
import com.thompsonfabco.filamentkit.ui.parseWeight
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass
import com.thompsonfabco.filamentkit.ui.theme.resolveDark
import com.thompsonfabco.filamentkit.update.UpdateUi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val app: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        // The system splash stays on the --bg ground until the stored pairing and appearance are read (05 2.1).
        val splash = installSplashScreen()
        super.onCreate(savedInstanceState)
        splash.setKeepOnScreenCondition { app.startup.value == null }
        appEdgeToEdge()
        setContent {
            val startup by app.startup.collectAsStateWithLifecycle()
            // Nothing is drawn (the splash shows) until the stored pairing and appearance have been read.
            startup?.let { start ->
                val appearance by app.settings.appearance.collectAsStateWithLifecycle(initialValue = start.appearance)
                val dark = resolveDark(appearance, isSystemInDarkTheme())
                // The bars follow the resolved appearance; the phone's own flip is keyed too (API 29/30 handle uiMode).
                val systemDark = isSystemInDarkTheme()
                LaunchedEffect(appearance, systemDark) { appEdgeToEdge(if (dark) Appearance.Dark else Appearance.Light) }
                // The next launch follows the choice.
                LaunchedEffect(appearance) { applyNightMode(appearance) }
                // the shell's toast queue: screens reach it through LocalToast
                val toast = remember { SwToastState() }
                val topBarActions = remember { TopBarActions() }
                AppFrame(appearance, handleInsets = false) {
                    CompositionLocalProvider(LocalToast provides toast, LocalTopBarActions provides topBarActions) {
                        FilamentKitApp(app, start.paired, appearance, toast, topBarActions)
                    }
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        enableTagReader()
    }

    override fun onPause() {
        disableTagReader()
        super.onPause()
    }
}

/**
 * Navigation for the whole app (05-android-app 2.1): the pairing graph, and the main graph with one stack per tab.
 * Start is the pairing graph when no Hub is stored ([paired] false), else Home.
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun FilamentKitApp(app: AppViewModel, paired: Boolean, appearance: Appearance, toast: SwToastState, topBarActions: TopBarActions) {
    // API 37: every LAN socket needs ACCESS_LOCAL_NETWORK. Asked once at start; the session waits for it.
    val localNetwork = rememberLocalNetworkAccess(autoRequest = true, onGranted = app.session::refresh)
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val destination = entry?.destination
    val inPairing = destination.inPairing()
    val tab = destination.tab()

    val api by app.session.api.collectAsStateWithLifecycle()
    val config by app.session.config.collectAsStateWithLifecycle()
    val skipFingerprintCheck by app.settings.skipFingerprintCheck.collectAsStateWithLifecycle(initialValue = false)
    val connection by app.session.connection.collectAsStateWithLifecycle()
    val notice by app.router.notice.collectAsStateWithLifecycle()

    // App-wide, one per Api (owned by AppViewModel; replaced when the pinned client changes).
    val updater by app.updater.current.collectAsStateWithLifecycle()
    val online = connection is Connection.Online
    LaunchedEffect(updater, online) {
        if (online) updater?.onOnline()
    }
    // Which modules are on (label reading is optional); read again whenever the server comes online.
    val info by produceState<ServerInfo?>(null, api, online) {
        val a = api
        value = if (a == null || !online) null else try {
            a.info()
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (_: Exception) {
            null
        }
    }
    val labelPhotos = showLabelPhotos(info)
    val version = versionLine(BuildConfig.VERSION_NAME, config.isPaired(), info?.version)
    // On screen: the chip follows the server, and is checked right away on return to the app. Not while pairing,
    // where nothing shows it.
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle, inPairing) {
        if (inPairing) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            while (true) {
                app.session.recheck()
                delay(CONNECTION_POLL_MS)
            }
        }
    }
    LaunchedEffect(lifecycle, updater) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) { updater?.onResumed() }
    }

    // the Hub that was paired when pairing was opened over the main graph
    var hubBefore by rememberSaveable { mutableStateOf<String?>(null) }
    // screens ask for the client at each call, so a trusted certificate or a re-pair reaches them with their state intact
    fun currentApi(): Api = app.session.api.value ?: throw ApiError(0, "offline", "No Hub is paired.")
    fun pushPairing() {
        hubBefore = hubIdentity(config)
        nav.navigate(PairGraph) { launchSingleTop = true }
    }
    val pairScope = rememberCoroutineScope()
    val context = LocalContext.current

    // The user asked to pair again (a screen's button, or the Hub sheet). A 401 or a changed certificate on its own
    // only changes the connection state (05 2.7): it never moves the user or clears a screen.
    val pairAgainRequests by app.router.pairAgainRequests.collectAsStateWithLifecycle()
    LaunchedEffect(pairAgainRequests) {
        if (pairAgainRequests > app.handledPairRequests) {
            app.handledPairRequests = pairAgainRequests
            if (!nav.currentDestination.inPairing()) pushPairing()
        }
    }

    // Pairing or trusting worked: back to the screen pairing was opened over, else (first start) to Home; the toast says so.
    fun finishPairing(sameHub: Boolean) {
        app.router.clear()
        pairScope.launch {
            // a read error keeps the stacks: it says nothing about which Hub is stored
            val saved = try { app.settings.server.first() } catch (e: java.io.IOException) { null }
            val hubNow = if (saved != null) hubIdentity(saved) else hubBefore
            val said = if (sameHub) {
                context.getString(R.string.pair_cert_stored_trusted)
            } else {
                context.getString(R.string.pair_done, saved?.name.orEmpty())
            }
            if (nav.previousBackStackEntry == null || (!sameHub && hubNow != hubBefore)) {
                // first start, or another Hub: nothing of the old one stays (stacks, saved stacks, their view models)
                nav.clearSavedStacks()
                nav.navigate(HomeGraph) {
                    popUpTo(nav.graph.id) { inclusive = true }
                    launchSingleTop = true
                }
            } else {
                nav.popBackStack<PairGraph>(inclusive = true)
            }
            launch { toast.show(said) }
        }
    }

    // The pairing destinations follow the pairing steps (05 4); done leaves through finishPairing.
    val pairOwner = if (inPairing) runCatching { nav.getBackStackEntry<PairGraph>() }.getOrNull() else null
    if (pairOwner != null) {
        PairRouteSync(
            nav, pairViewModel(pairOwner, app.settings), localNetwork.granted, notice,
            onPaired = { finishPairing(sameHub = false) },
        )
    }

    // A tag tap opens tag/{uid} on the stack of the selected tab (05 2.6), anywhere except pairing and the add flow (which
    // takes taps itself). While a load is being written it waits: the toast says so and the tag opens when the write ends.
    val adding = destination?.hasRoute(AddRoute::class) == true
    val tapsOn = destination != null && !inPairing && !adding
    val loadWriting by app.loadGate.writing.collectAsStateWithLifecycle()
    var queuedTag by rememberSaveable { mutableStateOf<String?>(null) }
    val tagWaits = stringResource(R.string.tag_read_wait)
    fun openTag(uid: String) {
        val here = nav.currentBackStackEntry
        val tagScreen = here?.let(::tagUidOf)
        // the tag whose spool screen is open: a tap of it does nothing (05 2.6)
        val spoolsTag = here?.takeIf { it.destination.hasRoute(SpoolRoute::class) }?.let {
            val route = it.toRoute<SpoolRoute>()
            route.tag ?: SpoolCache.get(route.id)?.tag
        }
        if (tapIsForTheOpenTag(uid, tagScreen, spoolsTag)) return
        // a different tag replaces the tag screen (and the link steps on it)
        if (tagScreen != null) nav.popBackStack<TagRoute>(inclusive = true)
        nav.navigate(TagRoute(uid))
    }
    // the tag that waited for a write to end opens now; once
    fun openQueued() {
        val uid = queuedTag ?: return
        queuedTag = null
        openTag(uid)
    }
    // a load or a link is being written, or its screen is still showing its answer
    val onWriteStep = destination?.hasRoute(SpoolLoadPreviewRoute::class) == true || destination?.hasRoute(TagLinkPreviewRoute::class) == true
    LaunchedEffect(tapsOn, lifecycle) {
        if (!tapsOn) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            TagEvents.taps.collect { uid ->
                if (app.loadGate.writing.value) {
                    queuedTag = uid
                    pairScope.launch { toast.show(tagWaits) }
                } else {
                    openTag(uid)
                }
            }
        }
    }
    // off the write's screen (its own result handling goes first), the waiting tag opens
    LaunchedEffect(loadWriting, tapsOn, onWriteStep) {
        if (!loadWriting && tapsOn && !onWriteStep) openQueued()
    }

    // The Hub connection chip and its sheet.
    val live = hubState(connection, notice, config)
    var shown by remember(config?.name, config?.token, config?.fingerprint) { mutableStateOf(live) }
    LaunchedEffect(live) { shown = keepLastKnown(shown, live) }
    var sheetOpen by rememberSaveable { mutableStateOf(false) }
    var leaveAddFor by remember { mutableStateOf<AddRoute?>(null) }

    val phone = SpoolwardenTheme.window == WindowClass.Phone
    val imeVisible = WindowInsets.isImeVisible
    val navVisible = !inPairing && destination != null && !(phone && imeVisible)
    val scroll = TopAppBarDefaults.pinnedScrollBehavior()
    val backDispatcher = LocalOnBackPressedDispatcherOwner.current?.onBackPressedDispatcher
    val pairingOverMain = remember(entry) { nav.previousBackStackEntry != null }
    val atPairStart = destination?.hasRoute(PairRoute::class) == true || destination?.hasRoute(PairNetworkAccessRoute::class) == true
    val showBack = showsBackArrow(destination.isTabRoot(), inPairing, pairingOverMain, atPairStart)
    val scanning = destination?.hasRoute(PairScanRoute::class) == true
    val storedCertificate = destination?.hasRoute(PairCertificateRoute::class) == true &&
        entry?.toRoute<PairCertificateRoute>()?.source == MismatchSource.STORED.routeSource()
    val update = updater?.state?.collectAsStateWithLifecycle()?.value ?: UpdateUi()

    val tabTapped: (Tab) -> Unit = { tapped ->
        val here = nav.currentDestination
        when (tabTap(here.tab(), tapped, here.isTabRoot())) {
            TabTap.Switch -> nav.selectTab(tapped)
            TabTap.PopToRoot -> nav.popToRootThrough { backDispatcher?.onBackPressed() }
            TabTap.Stay -> Unit
        }
    }

    // The spool screens and the tag screens (05 2.5, "Shared"): declared in the graph of every tab, so they open on the stack of
    // the tab that is selected and the bar keeps showing it.
    val sharedRoutes: NavGraphBuilder.() -> Unit = {
        composable<SpoolRoute> { e ->
            if (api == null) {
                HubNoticePage(::pushPairing)
                return@composable
            }
            val route = e.toRoute<SpoolRoute>()
            val spoolVm: SpoolViewModel = viewModel(factory = viewModelFactory {
                initializer {
                    SpoolViewModel(
                        route.id, SpoolBackend.of(::currentApi), SpoolCache.get(route.id), route.tag,
                        route.result?.let(SpoolResult::decode), createSavedStateHandle(),
                    )
                }
            })
            SpoolScreen(
                vm = spoolVm,
                onLoad = { nav.navigate(SpoolLoadRoute(route.id)) },
                onPairAgain = app.router::pairAgain,
                online = online,
                printersOn = info?.printersOn != false,
            )
        }

        composable<SpoolLoadRoute> { e ->
            if (api == null) {
                HubNoticePage(::pushPairing)
                return@composable
            }
            val route = e.toRoute<SpoolLoadRoute>()
            val vm: LoadPrintersViewModel = viewModel(factory = viewModelFactory {
                initializer { LoadPrintersViewModel(LoadBackend.of(::currentApi)) }
            })
            LoadPrintersScreen(
                vm = vm,
                spool = SpoolCache.get(route.id),
                onPick = { printer, skipped ->
                    nav.navigate(SpoolLoadSlotRoute(route.id, printer.id, skipped)) {
                        // a skipped step is not a step back: Back from the slots goes to the spool
                        if (skipped) popUpTo<SpoolLoadRoute> { inclusive = true }
                    }
                },
                onOpenPrinters = { tabTapped(Tab.Printers) },
                onPairAgain = app.router::pairAgain,
                online = online,
            )
        }

        composable<SpoolLoadSlotRoute> { e ->
            if (api == null) {
                HubNoticePage(::pushPairing)
                return@composable
            }
            val route = e.toRoute<SpoolLoadSlotRoute>()
            val vm: LoadSlotsViewModel = viewModel(factory = viewModelFactory {
                initializer { LoadSlotsViewModel(route.printerId, LoadBackend.of(::currentApi)) }
            })
            LoadSlotsScreen(
                vm = vm,
                spool = SpoolCache.get(route.id),
                skipped = route.skipped,
                onPick = { label -> nav.navigate(SpoolLoadPreviewRoute(route.id, route.printerId, label)) },
                onPairAgain = app.router::pairAgain,
                online = online,
            )
        }

        composable<SpoolLoadPreviewRoute> { e ->
            if (api == null) {
                HubNoticePage(::pushPairing)
                return@composable
            }
            val route = e.toRoute<SpoolLoadPreviewRoute>()
            val vm: LoadPreviewViewModel = viewModel(factory = viewModelFactory {
                initializer {
                    LoadPreviewViewModel(
                        SpoolCache.get(route.id) ?: SpoolSummary(route.id, "", "", "", null, null, null),
                        route.printerId, route.slot, LoadBackend.of(::currentApi), app.loadGate,
                    )
                }
            })
            LoadPreviewScreen(
                vm = vm,
                spool = SpoolCache.get(route.id),
                slot = route.slot,
                onBack = { nav.popBackStack() },
                onFinished = { result ->
                    // the spool screen under the load steps shows the result; it is put into that entry's saved state
                    runCatching { nav.getBackStackEntry<SpoolRoute>() }.getOrNull()?.savedStateHandle
                        ?.set(SpoolViewModel.RESULT_KEY, result.encode())
                    nav.popBackStack<SpoolRoute>(inclusive = false)
                    // a tag that waited for the load opens on top of the spool screen, after the steps have gone
                    openQueued()
                },
                onDone = { nav.popBackStack<SpoolRoute>(inclusive = false) },
                onOpenPrinter = {
                    // the Printers stack goes back to its root first, so Back from the printer lands on the list
                    nav.selectTab(Tab.Printers)
                    nav.popBackStack<PrintersRoute>(inclusive = false)
                    nav.navigate(PrinterRoute(route.printerId))
                },
                onPairAgain = app.router::pairAgain,
                online = online,
            )
        }

        composable<TagRoute> { e ->
            if (api == null) {
                HubNoticePage(::pushPairing)
                return@composable
            }
            val uid = e.toRoute<TagRoute>().uid
            val vm: TagViewModel = viewModel(factory = viewModelFactory {
                initializer { TagViewModel(uid, SpoolBackend.of(::currentApi)) }
            })
            TagScreen(
                vm = vm,
                uid = uid,
                // the tag screen is replaced by the spool it is linked to
                onLinked = { spool ->
                    nav.navigate(SpoolRoute(spool.id, tag = uid)) { popUpTo<TagRoute> { inclusive = true } }
                },
                onLink = { nav.navigate(TagLinkRoute(uid)) },
                onAddNew = {
                    nav.popBackStack<TagRoute>(inclusive = true)
                    // without label reading on the Hub the new spool is added by hand
                    val request = AddRoute(tag = uid, manual = !labelPhotos)
                    // an add already open follows the Back rules before a new one replaces it
                    if (nav.openAdd(request, ::addReplaceOf) == AddOpened.NeedsLeave) leaveAddFor = request
                },
                onPairAgain = app.router::pairAgain,
                online = online,
            )
        }

        composable<TagLinkRoute> { e ->
            if (api == null) {
                HubNoticePage(::pushPairing)
                return@composable
            }
            val uid = e.toRoute<TagLinkRoute>().uid
            val vm: LinkFindViewModel = viewModel(factory = viewModelFactory {
                initializer { LinkFindViewModel(SpoolBackend.of(::currentApi)) }
            })
            LinkFindScreen(
                vm = vm,
                uid = uid,
                onPick = { spool, gross ->
                    SpoolCache.put(spool)
                    nav.navigate(TagLinkPreviewRoute(uid, spool.id, gross))
                },
                onPairAgain = app.router::pairAgain,
                online = online,
            )
        }

        composable<TagLinkPreviewRoute> { e ->
            if (api == null) {
                HubNoticePage(::pushPairing)
                return@composable
            }
            val route = e.toRoute<TagLinkPreviewRoute>()
            val vm: LinkPreviewViewModel = viewModel(factory = viewModelFactory {
                initializer {
                    LinkPreviewViewModel(route.uid, route.spoolId, route.gross?.let(::parseWeight), SpoolBackend.of(::currentApi), app.loadGate)
                }
            })
            LinkPreviewScreen(
                vm = vm,
                uid = route.uid,
                onBack = { nav.popBackStack() },
                // the tag screens are replaced by the spool, which shows the result
                onDone = { result ->
                    nav.navigate(SpoolRoute(route.spoolId, tag = route.uid, result = result.encode())) {
                        popUpTo<TagRoute> { inclusive = true }
                    }
                    openQueued()
                },
                onPairAgain = app.router::pairAgain,
                online = online,
            )
        }
    }

    SwNav(
        selected = tab,
        visible = navVisible,
        onSelect = tabTapped,
        settingsUpdate = update.available != null,
    ) {
        Scaffold(
            modifier = Modifier.nestedScroll(scroll.nestedScrollConnection),
            topBar = {
                if (!scanning) SwTopBar(
                    title = placeTitle(destination, entry, storedCertificate),
                    subtitle = if (destination?.hasRoute(HomeRoute::class) == true) config?.name?.takeIf { it.isNotBlank() } else null,
                    onBack = if (showBack) ({ backDispatcher?.onBackPressed() }) else null,
                    scrollBehavior = scroll,
                ) {
                    if (!inPairing) SwConnectionChip(shown, onClick = { sheetOpen = true })
                    AppearanceMenu(appearance, app::setAppearance)
                    topBarActions.content?.invoke(this)
                }
            },
            snackbarHost = { SwToastHost(toast) },
            containerColor = SpoolwardenTheme.colors.bg,
            contentWindowInsets = when {
                scanning -> WindowInsets(0)
                !navVisible -> WindowInsets.safeDrawing
                phone -> WindowInsets.safeDrawing.only(WindowInsetsSides.Horizontal)
                else -> WindowInsets.safeDrawing.only(WindowInsetsSides.End + WindowInsetsSides.Bottom)
            },
        ) { padding ->
            NavHost(nav, startDestination = if (paired) HomeGraph else PairGraph, modifier = Modifier.padding(padding)) {
                navigation<PairGraph>(startDestination = PairRoute) {
                    composable<PairRoute> {
                        val pairVm = pairViewModel(remember(it) { nav.getBackStackEntry<PairGraph>() }, app.settings)
                        val ui by pairVm.state.collectAsStateWithLifecycle()
                        // no NSD browse until the local network permission is granted
                        val servers = remember(localNetwork.granted) { if (localNetwork.granted) app.discovery.servers() else flowOf(emptyList()) }
                        val discovered by servers.collectAsStateWithLifecycle(emptyList())
                        PairStartScreen(
                            ui = ui,
                            discovered = discovered,
                            appVersion = BuildConfig.VERSION_NAME,
                            onScan = { nav.navigate(PairScanRoute) },
                            onPick = { pairVm.connectDiscovered(it.host, it.port) },
                            onEnterAddress = { pairVm.startManual() },
                            unpairedBanner = notice is PairNotice.Unpaired || (config != null && !config.isPaired()),
                            access = localNetwork,
                        )
                    }
                    composable<PairNetworkAccessRoute> { PairNetworkAccessScreen(localNetwork, BuildConfig.VERSION_NAME) }
                    composable<PairScanRoute> {
                        val pairVm = pairViewModel(remember(it) { nav.getBackStackEntry<PairGraph>() }, app.settings)
                        // closing, a result and "enter the address" may arrive twice; only the entry on screen is popped
                        val leave = { nav.currentDestination?.hasRoute(PairScanRoute::class) == true && nav.popBackStack() }
                        QrScanner(
                            onResult = { text -> if (leave()) pairVm.onQrScanned(text) },
                            onClose = { leave() },
                            onEnterAddress = { if (leave()) pairVm.startManual() },
                        )
                    }
                    composable<PairAddressRoute> {
                        val pairVm = pairViewModel(remember(it) { nav.getBackStackEntry<PairGraph>() }, app.settings)
                        val ui by pairVm.state.collectAsStateWithLifecycle()
                        PairAddressScreen(ui, pairVm::submitAddress, pairVm::back, localNetwork)
                    }
                    composable<PairFingerprintRoute> {
                        val pairVm = pairViewModel(remember(it) { nav.getBackStackEntry<PairGraph>() }, app.settings)
                        val ui by pairVm.state.collectAsStateWithLifecycle()
                        PairFingerprintScreen(ui, pairVm::confirmFingerprint, pairVm::rejectFingerprint, pairVm::back)
                    }
                    composable<PairCodeRoute> {
                        val pairVm = pairViewModel(remember(it) { nav.getBackStackEntry<PairGraph>() }, app.settings)
                        val ui by pairVm.state.collectAsStateWithLifecycle()
                        PairCodeScreen(ui, pairVm::submitCode, pairVm::back, localNetwork)
                    }
                    composable<PairCertificateRoute> {
                        val pairVm = pairViewModel(remember(it) { nav.getBackStackEntry<PairGraph>() }, app.settings)
                        val ui by pairVm.state.collectAsStateWithLifecycle()
                        // gone while the screen leaves: nothing is asked then
                        ui.mismatch?.let { m ->
                            PairCertificateScreen(
                                mismatch = m,
                                canTrust = config.canTrust(m.expected),
                                onTrust = { app.trustCertificate(m.expected, m.actual) { finishPairing(sameHub = true) } },
                                onPairAgain = pairVm::pairAgain,
                                onBack = pairVm::back,
                            )
                        }
                    }
                }

                navigation<HomeGraph>(startDestination = HomeRoute) {
                    composable<HomeRoute> {
                        LaunchedEffect(Unit) { app.refreshDrafts() }
                        val drafts by app.draftList.collectAsStateWithLifecycle()
                        // Read each time Home is shown while online; null (card says "not available") when it cannot be read.
                        var presetsReload by remember { mutableIntStateOf(0) }
                        var buildingPresets by remember { mutableStateOf(false) }
                        var presetsNote by remember { mutableStateOf<String?>(null) }
                        var presetsNoteIsError by remember { mutableStateOf(false) }
                        val homeScope = rememberCoroutineScope()
                        val presets by produceState<ProfileStatus?>(null, api, online, presetsReload) {
                            val a = api
                            value = if (a == null || !online) null else try {
                                a.profileStatus()
                            } catch (e: kotlinx.coroutines.CancellationException) {
                                throw e
                            } catch (_: Exception) {
                                null
                            }
                        }
                        val presetUpdates = api?.let { a ->
                            viewModel(key = "preset-updates-${System.identityHashCode(a)}") {
                                com.thompsonfabco.filamentkit.ui.home.PresetUpdatesViewModel(
                                    com.thompsonfabco.filamentkit.ui.home.PresetUpdatesBackend.of(a),
                                )
                            }
                        }
                        val printersVm: HomePrintersViewModel = viewModel(factory = viewModelFactory {
                            initializer { HomePrintersViewModel(load = { currentApi().printers() }) }
                        })
                        val homePrinters by printersVm.state.collectAsStateWithLifecycle()
                        val showPrinters = info?.printersOn != false
                        // read again with each connection check, while Home is on screen
                        LaunchedEffect(lifecycle, online, showPrinters) {
                            if (!online || !showPrinters) return@LaunchedEffect
                            lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
                                while (true) {
                                    printersVm.refresh()
                                    delay(CONNECTION_POLL_MS)
                                }
                            }
                        }
                        HomeScreen(
                            connection = connection,
                            drafts = drafts,
                            update = update,
                            printers = homePrinters,
                            showPrinters = showPrinters,
                            onAddSpools = { nav.navigate(AddRoute()) },
                            onAddByHand = { nav.navigate(AddRoute(manual = true)) },
                            labelReaderOff = labelReaderOff(info),
                            onResumeDraft = { id -> nav.navigate(AddRoute(draft = id)) },
                            onDiscardDraft = app::discardDraft,
                            onOpenPrinter = { id ->
                                // the Printers stack goes back to its root first, so Back from the printer lands on the list
                                nav.selectTab(Tab.Printers)
                                nav.popBackStack<PrintersRoute>(inclusive = false)
                                nav.navigate(PrinterRoute(id))
                            },
                            onOpenPrinters = { tabTapped(Tab.Printers) },
                            onRefreshPrinters = printersVm::refresh,
                            onReviewCertificate = app.router::pairAgain,
                            onPairAgain = app.router::pairAgain,
                            onInstallUpdate = { updater?.install() },
                            onConfirmInstall = { updater?.confirmInstall() },
                            presets = presets,
                            showPresets = api != null,
                            onBuildPresets = {
                                val a = api
                                if (a != null && !buildingPresets) {
                                    buildingPresets = true
                                    presetsNote = null
                                    homeScope.launch {
                                        try {
                                            a.requestBuild()
                                            presetsNote = "A build was asked for. It finishes in a minute or two."
                                            presetsNoteIsError = false
                                            presetsReload++
                                        } catch (e: kotlinx.coroutines.CancellationException) {
                                            throw e
                                        } catch (e: Exception) {
                                            presetsNote = (e as? ApiError)?.message ?: "Could not ask the server for a build."
                                            presetsNoteIsError = true
                                        } finally {
                                            buildingPresets = false
                                        }
                                    }
                                }
                            },
                            buildingPresets = buildingPresets,
                            presetsNote = presetsNote,
                            presetsNoteIsError = presetsNoteIsError,
                            presetUpdates = presetUpdates,
                            onPresetsChanged = { presetsReload++ },
                            onAddCatalogLine = { nav.navigate(AddProfileRoute) },
                            localNetworkPanel = { LocalNetworkNotice(localNetwork) },
                            extra = { if (BuildConfig.DEBUG) SimulateTag() },
                        )
                    }

                    composable<AddRoute> { e ->
                        val a = api
                        if (a == null) {
                            HubNoticePage(::pushPairing)
                            return@composable
                        }
                        val route = e.toRoute<AddRoute>()
                        val addVm: AddViewModel = viewModel(factory = viewModelFactory {
                            initializer {
                                AddViewModel(
                                    IntakeApi.of(::currentApi), app.drafts, taps = emptyFlow(),
                                    draftId = route.draft, initialTag = route.tag, manual = route.manual,
                                )
                            }
                        })
                        TagTaps(addVm::onTag)
                        if (BuildConfig.DEBUG && !route.manual) LaunchedEffect(addVm) { DebugPhotos.photos.collect(addVm::addPhoto) }
                        AddSpoolsScreen(
                            vm = addVm,
                            onClose = { nav.popBackStack() },
                            onDone = { nav.popBackStack<HomeRoute>(inclusive = false) },
                            onPairAgain = app.router::pairAgain,
                        )
                    }

                    composable<AddProfileRoute> {
                        val profileVm: AddProfileViewModel = viewModel(factory = viewModelFactory {
                            initializer { AddProfileViewModel(ProfileApi.of(::currentApi)) }
                        })
                        val savedText = stringResource(R.string.catalog_saved)
                        AddProfileScreen(
                            vm = profileVm,
                            onBack = { nav.popBackStack() },
                            // back to the screen it came from; the toast outlives this screen, so it runs in the shell's scope
                            onSaved = {
                                nav.popBackStack()
                                pairScope.launch { toast.show(savedText) }
                            },
                            onPairAgain = app.router::pairAgain,
                            // no pairing: the form and its typing stay, the Hub notice sits inline (05 2.7)
                            paired = api != null,
                        )
                    }
                    sharedRoutes()
                }

                navigation<SpoolsGraph>(startDestination = SpoolsRoute) {
                    composable<SpoolsRoute> {
                        val a = api
                        if (a == null) {
                            HubNoticePage(::pushPairing)
                            return@composable
                        }
                        val searchVm: SearchViewModel = viewModel(factory = viewModelFactory {
                            initializer {
                                SearchViewModel { q, sealedOnly ->
                                    currentApi().search(q, sealedOnly)
                                }
                            }
                        })
                        SearchScreen(
                            vm = searchVm,
                            onOpenSpool = { spool ->
                                SpoolCache.put(spool)
                                nav.navigate(SpoolRoute(spool.id))
                            },
                            onPairAgain = app.router::pairAgain,
                            online = online,
                        )
                    }
                    sharedRoutes()
                }

                navigation<PrintersGraph>(startDestination = PrintersRoute) {
                    composable<PrintersRoute> {
                        val a = api
                        if (a == null) {
                            HubNoticePage(::pushPairing)
                            return@composable
                        }
                        PrintersListEntry(::currentApi, onOpen = { nav.navigate(PrinterRoute(it)) }, onPairAgain = app.router::pairAgain)
                    }

                    composable<PrinterRoute> { e ->
                        val a = api
                        if (a == null) {
                            HubNoticePage(::pushPairing)
                            return@composable
                        }
                        val id = e.toRoute<PrinterRoute>().id
                        val trustFailed by app.trustFailed.collectAsStateWithLifecycle()
                        val trust = TrustAction({ config.canTrust(it) }, { x, y -> app.trustCertificate(x, y) }, trustFailed, app::clearTrustFailed)
                        PrinterEntry(
                            a, id,
                            onBack = { nav.popBackStack() },
                            onManualMap = { nav.navigate(PrinterMapRoute(id)) },
                            onPairAgain = app.router::pairAgain,
                            trust = trust,
                        )
                    }

                    composable<PrinterMapRoute> { e ->
                        val a = api
                        if (a == null) {
                            HubNoticePage(::pushPairing)
                            return@composable
                        }
                        ManualMapEntry(a, e.toRoute<PrinterMapRoute>().id, onBack = { nav.popBackStack() }, onPairAgain = app.router::pairAgain)
                    }
                    sharedRoutes()
                }

                navigation<RecentGraph>(startDestination = RecentRoute) {
                    composable<RecentRoute> {
                        val a = api
                        if (a == null) {
                            HubNoticePage(::pushPairing)
                            return@composable
                        }
                        HistoryListEntry(
                            ::currentApi, a,
                            onOpen = { nav.navigate(RecordRoute(it)) },
                            onPairAgain = app.router::pairAgain,
                        )
                    }

                    composable<RecordRoute> { e ->
                        val a = api
                        if (a == null) {
                            HubNoticePage(::pushPairing)
                            return@composable
                        }
                        val list = remember(e) { nav.getBackStackEntry<RecentRoute>() }
                        HistoryRecordEntry(
                            ::currentApi, a, online, e.toRoute<RecordRoute>().hid, listOwner = list,
                            onBack = { if (nav.currentBackStackEntry?.id == e.id) nav.popBackStack() },
                            // Newer and Older record step through the list without going back
                            onOpenRecord = { hid -> nav.navigate(RecordRoute(hid)) { popUpTo<RecordRoute> { inclusive = true } } },
                            onEdit = { item -> nav.navigate(RecordEditRoute(e.toRoute<RecordRoute>().hid, item)) },
                            onOpenPhoto = { n -> nav.navigate(RecordPhotoRoute(e.toRoute<RecordRoute>().hid, n)) },
                            onOpenSpool = { spoolVm?.open(it) },
                            onPairAgain = app.router::pairAgain,
                        )
                    }

                    composable<RecordEditRoute> { e ->
                        val a = api
                        if (a == null) {
                            HubNoticePage(::pushPairing)
                            return@composable
                        }
                        val route = e.toRoute<RecordEditRoute>()
                        val record = remember(e) { nav.getBackStackEntry<RecordRoute>() }
                        HistoryEditEntry(
                            ::currentApi, a, online, route.hid, route.item, recordOwner = record,
                            // a late answer must not pop whatever is showing by then
                            onClose = { if (nav.currentBackStackEntry?.id == e.id) nav.popBackStack() },
                            onPairAgain = app.router::pairAgain,
                        )
                    }

                    composable<RecordPhotoRoute> { e ->
                        val a = api
                        if (a == null) {
                            HubNoticePage(::pushPairing)
                            return@composable
                        }
                        val route = e.toRoute<RecordPhotoRoute>()
                        val list = remember(e) { nav.getBackStackEntry<RecentRoute>() }
                        val record = remember(e) { nav.getBackStackEntry<RecordRoute>() }
                        HistoryPhotoEntry(
                            ::currentApi, route.hid, route.n, recordOwner = record, listOwner = list,
                            onClose = { if (nav.currentBackStackEntry?.id == e.id) nav.popBackStack() },
                        )
                    }

                    sharedRoutes()
                }

                navigation<SettingsGraph>(startDestination = SettingsRoute) {
                    val settingsFacts = SettingsFacts(
                        appearance = appearance,
                        hub = config?.let { SettingsHub(it.name, hubAddress(connection, it), it.fingerprint, info?.version) },
                        hubState = shown,
                        update = update,
                        appVersion = BuildConfig.VERSION_NAME,
                        developer = BuildConfig.DEBUG,
                    )
                    val settingsActions = SettingsActions(
                        onAppearance = app::setAppearance,
                        skipFingerprintCheck = skipFingerprintCheck,
                        onSkipFingerprintCheck = app::setSkipFingerprintCheck,
                        onPairAgain = app.router::pairAgain,
                        onForget = {
                            app.forget {
                                nav.clearSavedStacks()
                                nav.navigate(PairGraph) {
                                    popUpTo(nav.graph.id) { inclusive = true }
                                    launchSingleTop = true
                                }
                            }
                        },
                        setupUrl = { HubPage.url(app.session.baseUrl()) },
                        update = UpdateActions(
                            install = { updater?.install() },
                            cancel = { updater?.cancel() },
                            openSettings = { updater?.openPermissionSettings() },
                            tapToInstall = { updater?.confirmInstall() },
                            tryAgain = { updater?.checkNow() },
                        ),
                        onCheckForUpdates = { updater?.checkNow() },
                        onSimulateTag = TagEvents::emit,
                    )
                    composable<SettingsRoute> {
                        SettingsScreen(
                            facts = settingsFacts,
                            onOpen = { group ->
                                nav.navigate(
                                    when (group) {
                                        SettingsGroup.Appearance -> SettingsAppearanceRoute
                                        SettingsGroup.Hub -> SettingsHubRoute
                                        SettingsGroup.Updates -> SettingsUpdatesRoute
                                        SettingsGroup.Licences -> LicencesRoute
                                        SettingsGroup.Developer -> SettingsDeveloperRoute
                                    },
                                )
                            },
                            detail = { group -> SettingsGroupPage(group, settingsFacts, settingsActions) },
                        )
                    }
                    composable<SettingsAppearanceRoute> { SettingsGroupPage(SettingsGroup.Appearance, settingsFacts, settingsActions) }
                    composable<SettingsHubRoute> { SettingsGroupPage(SettingsGroup.Hub, settingsFacts, settingsActions) }
                    composable<SettingsUpdatesRoute> { SettingsGroupPage(SettingsGroup.Updates, settingsFacts, settingsActions) }
                    composable<LicencesRoute> { SettingsGroupPage(SettingsGroup.Licences, settingsFacts, settingsActions) }
                    composable<SettingsDeveloperRoute> { SettingsGroupPage(SettingsGroup.Developer, settingsFacts, settingsActions) }
                    sharedRoutes()
                }
            }
        }
    }

    if (sheetOpen && !inPairing) {
        HubSheet(
            state = shown,
            checking = connection is Connection.Checking,
            facts = HubFacts(config?.name.orEmpty(), hubAddress(connection, config), BuildConfig.VERSION_NAME, info?.version),
            showAppSettings = localNetwork.showSettings,
            actions = HubSheetActions(
                tryAgain = app.session::refresh,
                reviewCertificate = {
                    sheetOpen = false
                    app.router.pairAgain()
                },
                pairAgain = {
                    sheetOpen = false
                    app.router.pairAgain()
                },
                allow = localNetwork.request,
                openAppSettings = localNetwork.openSettings,
                hubSettings = {
                    sheetOpen = false
                    tabTapped(Tab.Settings)
                },
            ),
            onDismiss = { sheetOpen = false },
        )
    }

    leaveAddFor?.let { request ->
        SwDialog(
            title = stringResource(R.string.common_leave_title),
            onClose = { leaveAddFor = null },
            confirm = SwDialogButton(
                stringResource(R.string.common_leave_without_saving),
                onClick = {
                    leaveAddFor = null
                    nav.replaceAdd(request)
                },
                kind = SwButtonKind.DestructiveFilled,
            ),
            cancel = SwAction(stringResource(R.string.common_stay)) { leaveAddFor = null },
        ) {
            Text(stringResource(R.string.common_leave_body, stringResource(R.string.web_card_new_spool)))
        }
    }
}

/** The place the top bar names (05-android-app 2.2): the screen, not the product. */
@Composable
private fun placeTitle(destination: NavDestination?, entry: NavBackStackEntry?, storedCertificate: Boolean): String {
    // the thing's name: the spool's, or the tag's (05 2.2)
    when {
        destination?.hasRoute(SpoolRoute::class) == true -> {
            val id = entry!!.toRoute<SpoolRoute>().id
            return SpoolCache.title(id) ?: stringResource(R.string.web_spool_title, id.toString())
        }
        entry != null && tagUidOf(entry) != null -> return stringResource(R.string.common_tag, tagUidOf(entry).orEmpty())
    }
    return stringResource(
    when {
        destination?.hasRoute(SpoolLoadRoute::class) == true || destination?.hasRoute(SpoolLoadSlotRoute::class) == true ||
            destination?.hasRoute(SpoolLoadPreviewRoute::class) == true -> R.string.spool_load
        destination == null -> R.string.nav_home
        storedCertificate -> R.string.pair_cert_top_title
        destination.inPairing() -> R.string.pair_title
        destination.hasRoute(AddRoute::class) -> R.string.home_add_title
        destination.hasRoute(AddProfileRoute::class) -> AddProfileTitle
        destination.hasRoute(LicencesRoute::class) -> R.string.settings_licences_title
        destination.hasRoute(SettingsAppearanceRoute::class) -> R.string.appearance_title
        destination.hasRoute(SettingsHubRoute::class) -> R.string.settings_hub_title
        destination.hasRoute(SettingsUpdatesRoute::class) -> R.string.settings_updates_title
        destination.hasRoute(SettingsDeveloperRoute::class) -> R.string.settings_developer_title
        destination.tab() == Tab.Recent -> R.string.nav_recently_added
        else -> (destination.tab() ?: Tab.Home).label
    },
    )
}

/** The tag a tag screen (the lookup or a link step) is about; null on any other screen. */
private fun tagUidOf(entry: NavBackStackEntry): String? {
    val d = entry.destination
    return when {
        d.hasRoute(TagRoute::class) -> entry.toRoute<TagRoute>().uid
        d.hasRoute(TagLinkRoute::class) -> entry.toRoute<TagLinkRoute>().uid
        d.hasRoute(TagLinkPreviewRoute::class) -> entry.toRoute<TagLinkPreviewRoute>().uid
        else -> null
    }
}

/**
 * Android draws apps edge to edge (target SDK 35+). The status and navigation bars stay transparent over the app's own
 * background, with icons that follow the app's appearance (System follows the phone).
 */
internal fun ComponentActivity.appEdgeToEdge(appearance: Appearance = Appearance.System) {
    val transparent = AndroidColor.TRANSPARENT
    val style = when (appearance) {
        Appearance.Light -> SystemBarStyle.light(transparent, transparent)
        Appearance.Dark -> SystemBarStyle.dark(transparent)
        Appearance.System -> SystemBarStyle.auto(transparent, transparent)
    }
    enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
}

/**
 * Tells the system the app's night mode, so the next launch's splash and window background use it (Android 12+; older
 * versions have no such call). The activity handles the resulting `uiMode` change itself and is not recreated.
 */
internal fun ComponentActivity.applyNightMode(appearance: Appearance) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
    getSystemService(UiModeManager::class.java).setApplicationNightMode(
        when (appearance) {
            Appearance.Light -> UiModeManager.MODE_NIGHT_NO
            Appearance.Dark -> UiModeManager.MODE_NIGHT_YES
            Appearance.System -> UiModeManager.MODE_NIGHT_AUTO
        },
    )
}

/**
 * The app's root: the Console theme in the chosen appearance, the background fills the whole window, behind the bars
 * too. With [handleInsets] every screen is kept clear of the status bar, navigation bar, cutouts and keyboard, here
 * once; the app's shell passes false, because its top bar, bar or rail and scaffold each keep clear of them.
 */
@Composable
internal fun AppFrame(appearance: Appearance = Appearance.System, handleInsets: Boolean = true, content: @Composable () -> Unit) {
    SpoolwardenTheme(Look.Console, appearance) {
        Surface(Modifier.fillMaxSize(), color = SpoolwardenTheme.colors.bg) {
            Box(Modifier.fillMaxSize().then(if (handleInsets) Modifier.safeDrawingPadding() else Modifier)) { content() }
        }
    }
}

/** Shown instead of a screen that needs the Hub when no Hub is paired: the Hub notice of 05-android-app 3.4. */
@Composable
private fun HubNoticePage(onPair: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(SpoolwardenTheme.space.s4)) {
        HubNotice(HubNoticeKind.NoLongerPaired, onPair)
    }
}

/** Debug builds only: type a UID (e.g. `4:77:90:e`) and emit it as if the tag had been tapped. */
@Composable
private fun SimulateTag() {
    var uid by remember { mutableStateOf("4:77:90:e") }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(
            value = uid,
            onValueChange = { uid = it },
            label = { Text("Tag UID") },
            singleLine = true,
            modifier = Modifier.weight(1f),
        )
        Button(onClick = { TagEvents.emit(uid.trim()) }) { Text("Simulate tag") }
    }
}
