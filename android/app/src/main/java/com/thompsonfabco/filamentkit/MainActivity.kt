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
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.window.Dialog
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.NavDestination
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.navigation
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import com.thompsonfabco.filamentkit.nav.AddProfileRoute
import com.thompsonfabco.filamentkit.nav.AddRoute
import com.thompsonfabco.filamentkit.nav.HomeGraph
import com.thompsonfabco.filamentkit.nav.HomeRoute
import com.thompsonfabco.filamentkit.nav.LicencesRoute
import com.thompsonfabco.filamentkit.nav.PairGraph
import com.thompsonfabco.filamentkit.nav.PairRoute
import com.thompsonfabco.filamentkit.nav.PrinterMapRoute
import com.thompsonfabco.filamentkit.nav.PrinterRoute
import com.thompsonfabco.filamentkit.nav.PrintersGraph
import com.thompsonfabco.filamentkit.nav.PrintersRoute
import com.thompsonfabco.filamentkit.nav.RecentGraph
import com.thompsonfabco.filamentkit.nav.RecentRoute
import com.thompsonfabco.filamentkit.nav.RecordRoute
import com.thompsonfabco.filamentkit.nav.SettingsGraph
import com.thompsonfabco.filamentkit.nav.SettingsRoute
import com.thompsonfabco.filamentkit.nav.SpoolsGraph
import com.thompsonfabco.filamentkit.nav.SpoolsRoute
import com.thompsonfabco.filamentkit.nav.Tab
import com.thompsonfabco.filamentkit.nav.TabTap
import com.thompsonfabco.filamentkit.nav.clearSavedStacks
import com.thompsonfabco.filamentkit.nav.hubAddress
import com.thompsonfabco.filamentkit.nav.hubState
import com.thompsonfabco.filamentkit.nav.inPairing
import com.thompsonfabco.filamentkit.nav.isTabRoot
import com.thompsonfabco.filamentkit.nav.keepLastKnown
import com.thompsonfabco.filamentkit.nav.openAdd
import com.thompsonfabco.filamentkit.nav.popToRootThrough
import com.thompsonfabco.filamentkit.nav.selectTab
import com.thompsonfabco.filamentkit.nav.showsBackArrow
import com.thompsonfabco.filamentkit.nav.tab
import com.thompsonfabco.filamentkit.nav.tabTap
import com.thompsonfabco.filamentkit.net.ApiError
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.net.ServerInfo
import com.thompsonfabco.filamentkit.session.CONNECTION_POLL_MS
import com.thompsonfabco.filamentkit.session.AppViewModel
import com.thompsonfabco.filamentkit.session.Connection
import com.thompsonfabco.filamentkit.session.PairNotice
import com.thompsonfabco.filamentkit.session.UNPAIRED_MESSAGE
import com.thompsonfabco.filamentkit.session.canTrust
import com.thompsonfabco.filamentkit.session.isPaired
import com.thompsonfabco.filamentkit.tags.TagEvents
import com.thompsonfabco.filamentkit.tags.disableTagReader
import com.thompsonfabco.filamentkit.tags.enableTagReader
import com.thompsonfabco.filamentkit.ui.LocalNetworkPanel
import com.thompsonfabco.filamentkit.ui.rememberLocalNetworkAccess
import com.thompsonfabco.filamentkit.ui.add.AddSpoolsScreen
import com.thompsonfabco.filamentkit.ui.add.AddViewModel
import com.thompsonfabco.filamentkit.ui.add.DebugPhotos
import com.thompsonfabco.filamentkit.ui.add.IntakeApi
import com.thompsonfabco.filamentkit.ui.components.AppearanceMenu
import com.thompsonfabco.filamentkit.ui.components.HubFacts
import com.thompsonfabco.filamentkit.ui.components.HubSheet
import com.thompsonfabco.filamentkit.ui.components.HubSheetActions
import com.thompsonfabco.filamentkit.ui.components.SwConnectionChip
import com.thompsonfabco.filamentkit.ui.components.SwNav
import com.thompsonfabco.filamentkit.ui.components.SwTopBar
import com.thompsonfabco.filamentkit.ui.history.HistoryListEntry
import com.thompsonfabco.filamentkit.ui.history.HistoryRecordEntry
import com.thompsonfabco.filamentkit.ui.home.HomeScreen
import com.thompsonfabco.filamentkit.ui.home.VersionLine
import com.thompsonfabco.filamentkit.ui.home.showLabelPhotos
import com.thompsonfabco.filamentkit.ui.home.versionLine
import com.thompsonfabco.filamentkit.ui.pair.NetPairingBackend
import com.thompsonfabco.filamentkit.ui.pair.PairScreen
import com.thompsonfabco.filamentkit.ui.pair.PairViewModel
import com.thompsonfabco.filamentkit.ui.printers.ManualMapEntry
import com.thompsonfabco.filamentkit.ui.printers.PrinterEntry
import com.thompsonfabco.filamentkit.ui.printers.PrintersListEntry
import com.thompsonfabco.filamentkit.ui.printers.TrustAction
import com.thompsonfabco.filamentkit.ui.profile.AddProfileScreen
import com.thompsonfabco.filamentkit.ui.profile.AddProfileViewModel
import com.thompsonfabco.filamentkit.ui.profile.ProfileApi
import com.thompsonfabco.filamentkit.ui.search.SearchScreen
import com.thompsonfabco.filamentkit.ui.search.SearchViewModel
import com.thompsonfabco.filamentkit.ui.settings.LicencesScreen
import com.thompsonfabco.filamentkit.ui.settings.SettingsScreen
import com.thompsonfabco.filamentkit.ui.settings.SetupPageTexts
import com.thompsonfabco.filamentkit.ui.spool.SpoolHost
import com.thompsonfabco.filamentkit.ui.spool.SpoolUiState
import com.thompsonfabco.filamentkit.ui.spool.closeSpoolCard
import com.thompsonfabco.filamentkit.ui.theme.Appearance
import com.thompsonfabco.filamentkit.ui.theme.Look
import com.thompsonfabco.filamentkit.ui.theme.SpoolwardenTheme
import com.thompsonfabco.filamentkit.ui.theme.WindowClass
import com.thompsonfabco.filamentkit.ui.theme.resolveDark
import com.thompsonfabco.filamentkit.update.UpdateUi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
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
                AppFrame(appearance, handleInsets = false) { FilamentKitApp(app, start.paired, appearance) }
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
private fun FilamentKitApp(app: AppViewModel, paired: Boolean, appearance: Appearance) {
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
    val spoolVm by app.spool.current.collectAsStateWithLifecycle()
    val loadVm by app.load.current.collectAsStateWithLifecycle()
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
    val hubBefore = remember { arrayOfNulls<String>(1) }
    fun pushPairing() {
        hubBefore[0] = config?.name
        nav.navigate(PairGraph) { launchSingleTop = true }
    }
    val pairScope = rememberCoroutineScope()

    // The user asked to pair again (a screen's button, or the Hub sheet). A 401 or a changed certificate on its own
    // only changes the connection state (05 2.7): it never moves the user or clears a screen.
    val pairAgainRequests by app.router.pairAgainRequests.collectAsStateWithLifecycle()
    LaunchedEffect(pairAgainRequests) {
        if (pairAgainRequests > app.handledPairRequests) {
            app.handledPairRequests = pairAgainRequests
            // a load being written keeps its card: it shows the result once pairing is done
            closeSpoolCard(loadVm) { spoolVm?.dismiss() }
            if (!nav.currentDestination.inPairing()) pushPairing()
        }
    }

    // Pairing or trusting worked: back to the screen pairing was opened over, else (first start) to Home.
    val finishPairing: () -> Unit = {
        app.router.clear()
        pairScope.launch {
            val hubNow = app.settings.server.first()?.name
            if (nav.previousBackStackEntry == null || hubNow != hubBefore[0]) {
                // first start, or another Hub: nothing of the old one stays (stacks, saved stacks, their view models)
                nav.clearSavedStacks()
                nav.navigate(HomeGraph) {
                    popUpTo(nav.graph.id) { inclusive = true }
                    launchSingleTop = true
                }
            } else {
                nav.popBackStack<PairGraph>(inclusive = true)
            }
        }
        Unit
    }

    // Tag taps open the spool card anywhere except pairing and the add flow (AddViewModel takes taps itself).
    val tapVm = spoolVm
    val adding = destination?.hasRoute(AddRoute::class) == true
    val tapsOn = tapVm != null && destination != null && !inPairing && !adding
    LaunchedEffect(tapVm, loadVm, tapsOn) {
        if (tapsOn) TagEvents.taps.collect {
            // a new tap replaces the open card and any load flow on it, except while a load is being written:
            // then the tap is ignored so the user sees that write's result
            closeSpoolCard(loadVm) { tapVm.onTag(it) }
        }
    }

    // The Hub connection chip and its sheet.
    val live = hubState(connection, notice, config)
    var shown by remember(config?.name, config?.token, config?.fingerprint) { mutableStateOf(live) }
    LaunchedEffect(live) { shown = keepLastKnown(shown, live) }
    var sheetOpen by rememberSaveable { mutableStateOf(false) }

    val phone = SpoolwardenTheme.window == WindowClass.Phone
    val imeVisible = WindowInsets.isImeVisible
    val navVisible = !inPairing && destination != null && !(phone && imeVisible)
    val scroll = TopAppBarDefaults.pinnedScrollBehavior()
    val backDispatcher = LocalOnBackPressedDispatcherOwner.current?.onBackPressedDispatcher
    val pairingOverMain = remember(entry) { nav.previousBackStackEntry != null }
    val showBack = showsBackArrow(destination.isTabRoot(), inPairing, pairingOverMain)
    val update = updater?.state?.collectAsStateWithLifecycle()?.value ?: UpdateUi()

    val tabTapped: (Tab) -> Unit = { tapped ->
        val here = nav.currentDestination
        when (tabTap(here.tab(), tapped, here.isTabRoot())) {
            TabTap.Switch -> nav.selectTab(tapped)
            TabTap.PopToRoot -> nav.popToRootThrough { backDispatcher?.onBackPressed() }
            TabTap.Stay -> Unit
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
                SwTopBar(
                    title = placeTitle(destination),
                    subtitle = if (destination?.hasRoute(HomeRoute::class) == true) config?.name?.takeIf { it.isNotBlank() } else null,
                    onBack = if (showBack) ({ backDispatcher?.onBackPressed() }) else null,
                    scrollBehavior = scroll,
                ) {
                    if (!inPairing) SwConnectionChip(shown, onClick = { sheetOpen = true })
                    AppearanceMenu(appearance, app::setAppearance)
                }
            },
            containerColor = SpoolwardenTheme.colors.bg,
            contentWindowInsets = when {
                !navVisible -> WindowInsets.safeDrawing
                phone -> WindowInsets.safeDrawing.only(WindowInsetsSides.Horizontal)
                else -> WindowInsets.safeDrawing.only(WindowInsetsSides.End + WindowInsetsSides.Bottom)
            },
        ) { padding ->
            NavHost(nav, startDestination = if (paired) HomeGraph else PairGraph, modifier = Modifier.padding(padding)) {
                navigation<PairGraph>(startDestination = PairRoute) {
                    composable<PairRoute> {
                        val pairVm: PairViewModel = viewModel(factory = viewModelFactory {
                            initializer { PairViewModel(app.settings, NetPairingBackend()) }
                        })
                        var mismatchShown by rememberSaveable { mutableStateOf(false) }
                        LaunchedEffect(notice) {
                            val n = notice
                            if (n is PairNotice.CertChanged && !mismatchShown) {
                                mismatchShown = true
                                pairVm.showMismatch(n.expected, n.actual)
                            }
                        }
                        Column(Modifier.fillMaxSize()) {
                            if (notice is PairNotice.Unpaired || (config != null && !config.isPaired())) {
                                Text(
                                    UNPAIRED_MESSAGE,
                                    color = MaterialTheme.colorScheme.error,
                                    style = MaterialTheme.typography.titleMedium,
                                    modifier = Modifier.padding(start = 24.dp, end = 24.dp, top = 24.dp),
                                )
                            }
                            if (!localNetwork.granted) {
                                // No NSD browse, probe, verify or pair until the permission is granted.
                                Column(Modifier.weight(1f).padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                                    Column {
                                        Text("Pair with your server", style = MaterialTheme.typography.headlineSmall)
                                        VersionLine(version)
                                    }
                                    LocalNetworkPanel(localNetwork)
                                }
                            } else {
                                val servers = remember { app.discovery.servers() }
                                val discovered by servers.collectAsStateWithLifecycle(emptyList())
                                PairScreen(
                                    viewModel = pairVm,
                                    discovered = discovered,
                                    onPaired = finishPairing,
                                    modifier = Modifier.weight(1f),
                                    skipCheck = skipFingerprintCheck,
                                    onSkipCheck = app::setSkipFingerprintCheck,
                                    canTrust = { config.canTrust(it.expected) },
                                    onTrust = { m -> app.trustCertificate(m.expected, m.actual, finishPairing) },
                                    version = version,
                                )
                            }
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
                        HomeScreen(
                            serverName = config?.name.orEmpty(),
                            connection = connection,
                            drafts = drafts,
                            update = update,
                            version = version,
                            onAddSpools = { nav.navigate(AddRoute()) },
                            onAddByHand = { nav.navigate(AddRoute(manual = true)) },
                            labelPhotos = labelPhotos,
                            onAddProfile = { nav.navigate(AddProfileRoute) },
                            onSearch = { tabTapped(Tab.Spools) },
                            onPrinters = { tabTapped(Tab.Printers) },
                            onHistory = { tabTapped(Tab.Recent) },
                            onSettings = { tabTapped(Tab.Settings) },
                            onResumeDraft = { id -> nav.navigate(AddRoute(draft = id)) },
                            onDiscardDraft = app::discardDraft,
                            onRetryConnection = app.session::refresh,
                            onReviewCertificate = app.router::pairAgain,
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
                            localNetworkPanel = { LocalNetworkPanel(localNetwork) },
                            extra = { if (BuildConfig.DEBUG) SimulateTag() },
                        )
                    }

                    composable<AddRoute> { e ->
                        val a = api
                        if (a == null) {
                            NotPaired(::pushPairing)
                            return@composable
                        }
                        val route = e.toRoute<AddRoute>()
                        val addVm: AddViewModel = viewModel(key = System.identityHashCode(a).toString(), factory = viewModelFactory {
                            initializer {
                                AddViewModel(IntakeApi.of(a), app.drafts, draftId = route.draft, initialTag = route.tag, manual = route.manual)
                            }
                        })
                        if (BuildConfig.DEBUG && !route.manual) LaunchedEffect(addVm) { DebugPhotos.photos.collect(addVm::addPhoto) }
                        AddSpoolsScreen(
                            vm = addVm,
                            onClose = { nav.popBackStack() },
                            onDone = { nav.popBackStack<HomeRoute>(inclusive = false) },
                            onPairAgain = app.router::pairAgain,
                        )
                    }

                    composable<AddProfileRoute> {
                        val a = api
                        if (a == null) {
                            NotPaired(::pushPairing)
                            return@composable
                        }
                        val profileVm: AddProfileViewModel = viewModel(key = System.identityHashCode(a).toString(), factory = viewModelFactory {
                            initializer { AddProfileViewModel(ProfileApi.of(a)) }
                        })
                        AddProfileScreen(
                            vm = profileVm,
                            onBack = { nav.popBackStack() },
                            onPairAgain = app.router::pairAgain,
                        )
                    }
                }

                navigation<SpoolsGraph>(startDestination = SpoolsRoute) {
                    composable<SpoolsRoute> {
                        val a = api
                        if (a == null) {
                            NotPaired(::pushPairing)
                            return@composable
                        }
                        val searchVm: SearchViewModel = viewModel(key = System.identityHashCode(a).toString(), factory = viewModelFactory {
                            initializer { SearchViewModel { q, sealedOnly -> a.search(q, sealedOnly) } }
                        })
                        SearchScreen(
                            vm = searchVm,
                            onOpenSpool = { spoolVm?.open(it) },
                            onPairAgain = app.router::pairAgain,
                        )
                    }
                }

                navigation<PrintersGraph>(startDestination = PrintersRoute) {
                    composable<PrintersRoute> {
                        val a = api
                        if (a == null) {
                            NotPaired(::pushPairing)
                            return@composable
                        }
                        val trustFailed by app.trustFailed.collectAsStateWithLifecycle()
                        val trust = TrustAction({ config.canTrust(it) }, { x, y -> app.trustCertificate(x, y) }, trustFailed, app::clearTrustFailed)
                        PrintersListEntry(a, onOpen = { nav.navigate(PrinterRoute(it)) }, onPairAgain = app.router::pairAgain, trust = trust)
                    }

                    composable<PrinterRoute> { e ->
                        val a = api
                        if (a == null) {
                            NotPaired(::pushPairing)
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
                            NotPaired(::pushPairing)
                            return@composable
                        }
                        ManualMapEntry(a, e.toRoute<PrinterMapRoute>().id, onBack = { nav.popBackStack() }, onPairAgain = app.router::pairAgain)
                    }
                }

                navigation<RecentGraph>(startDestination = RecentRoute) {
                    composable<RecentRoute> {
                        val a = api
                        if (a == null) {
                            NotPaired(::pushPairing)
                            return@composable
                        }
                        HistoryListEntry(
                            a,
                            onOpen = { nav.navigate(RecordRoute(it)) },
                            onPairAgain = app.router::pairAgain,
                        )
                    }

                    composable<RecordRoute> { e ->
                        val a = api
                        if (a == null) {
                            NotPaired(::pushPairing)
                            return@composable
                        }
                        val list = remember(e) { nav.getBackStackEntry<RecentRoute>() }
                        HistoryRecordEntry(
                            a, e.toRoute<RecordRoute>().hid, listOwner = list,
                            onBack = { nav.popBackStack() },
                            onPairAgain = app.router::pairAgain,
                        )
                    }
                }

                navigation<SettingsGraph>(startDestination = SettingsRoute) {
                    composable<SettingsRoute> {
                        SettingsScreen(
                            config = config,
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
                            onLicences = { nav.navigate(LicencesRoute) },
                            skipFingerprintCheck = skipFingerprintCheck,
                            onSkipFingerprintCheck = app::setSkipFingerprintCheck,
                            setupUrl = { SetupPageTexts.url(app.session.baseUrl()) },
                        )
                    }

                    composable<LicencesRoute> { LicencesScreen() }
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

    // The spool card, over whatever screen is open (not over pairing or the add flow).
    spoolVm?.let { vm ->
        val spoolState by vm.state.collectAsStateWithLifecycle()
        if (spoolState != SpoolUiState.Idle && destination != null && !adding && !inPairing) {
            // Not while a load is being written: the dialog stays until the user has seen the result.
            val close = { closeSpoolCard(loadVm, vm::dismiss) }
            Dialog(onDismissRequest = close) {
                Surface(shape = MaterialTheme.shapes.large, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.verticalScroll(rememberScrollState())) {
                        SpoolHost(
                            viewModel = vm,
                            onStartAdd = { tag ->
                                close()
                                // without label reading on the server the new spool is added by hand
                                nav.openAdd(AddRoute(tag = tag, manual = !labelPhotos))
                            },
                            onPairAgain = {
                                close()
                                app.router.pairAgain()
                            },
                            onClose = close,
                            loadVm = loadVm,
                        )
                    }
                }
            }
        }
    }
}

/** The place the top bar names (05-android-app 2.2): the screen, not the product. */
@Composable
private fun placeTitle(destination: NavDestination?): String = stringResource(
    when {
        destination == null -> R.string.nav_home
        destination.hasRoute(PairRoute::class) -> R.string.pair_title
        destination.hasRoute(AddRoute::class) -> R.string.home_add_title
        destination.hasRoute(AddProfileRoute::class) -> R.string.catalog_add_line
        destination.hasRoute(LicencesRoute::class) -> R.string.settings_licences_title
        destination.tab() == Tab.Recent -> R.string.nav_recently_added
        else -> (destination.tab() ?: Tab.Home).label
    },
)

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

/** Shown instead of a screen that needs the server when no server is paired. */
@Composable
private fun NotPaired(onPair: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Not paired", style = MaterialTheme.typography.headlineSmall)
        Text("Pair this phone with your server first.")
        Button(onClick = onPair) { Text("Pair") }
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
