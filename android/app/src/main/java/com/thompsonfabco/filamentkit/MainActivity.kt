package com.thompsonfabco.filamentkit

import android.graphics.Color as AndroidColor
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.activity.compose.setContent
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.thompsonfabco.filamentkit.net.ProfileStatus
import com.thompsonfabco.filamentkit.net.ServerInfo
import com.thompsonfabco.filamentkit.session.CONNECTION_POLL_MS
import com.thompsonfabco.filamentkit.ui.home.VersionLine
import com.thompsonfabco.filamentkit.ui.history.HistoryEntry
import com.thompsonfabco.filamentkit.ui.home.versionLine
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
import com.thompsonfabco.filamentkit.ui.home.HomeScreen
import com.thompsonfabco.filamentkit.ui.home.showLabelPhotos
import com.thompsonfabco.filamentkit.ui.pair.NetPairingBackend
import com.thompsonfabco.filamentkit.ui.pair.PairScreen
import com.thompsonfabco.filamentkit.ui.pair.PairViewModel
import com.thompsonfabco.filamentkit.ui.printers.PrintersEntry
import com.thompsonfabco.filamentkit.ui.profile.AddProfileScreen
import com.thompsonfabco.filamentkit.ui.profile.AddProfileViewModel
import com.thompsonfabco.filamentkit.ui.profile.ProfileApi
import com.thompsonfabco.filamentkit.ui.search.SearchScreen
import com.thompsonfabco.filamentkit.ui.search.SearchViewModel
import com.thompsonfabco.filamentkit.ui.settings.LicencesScreen
import com.thompsonfabco.filamentkit.ui.settings.SettingsScreen
import com.thompsonfabco.filamentkit.ui.settings.SetupPageTexts
import com.thompsonfabco.filamentkit.ui.spool.ApiSpoolBackend
import com.thompsonfabco.filamentkit.ui.spool.SpoolHost
import com.thompsonfabco.filamentkit.ui.spool.closeSpoolCard
import com.thompsonfabco.filamentkit.ui.spool.SpoolUiState
import com.thompsonfabco.filamentkit.ui.spool.SpoolViewModel
import com.thompsonfabco.filamentkit.update.UpdateUi
import kotlinx.coroutines.delay

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        appEdgeToEdge()
        setContent { AppFrame { FilamentKitApp() } }
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

private object Routes {
    const val PAIR = "pair"
    const val HOME = "home"
    const val SEARCH = "search"
    const val SETTINGS = "settings"
    const val LICENCES = "settings/licences"
    const val PRINTERS = "printers"
    const val HISTORY = "intake/history"
    const val ADD_PROFILE = "profile/add"
    const val ADD = "add?tag={tag}&draft={draft}&manual={manual}"

    /** [manual]: add by hand (no photos, no draft). */
    fun add(tag: String? = null, draft: String? = null, manual: Boolean = false): String {
        val query = listOfNotNull(
            tag?.let { "tag=${Uri.encode(it)}" }, draft?.let { "draft=${Uri.encode(it)}" }, "manual=true".takeIf { manual },
        )
        return if (query.isEmpty()) "add" else "add?" + query.joinToString("&")
    }
}

/** Navigation for the whole app; start is Pair when no server is stored, else Home. */
@Composable
private fun FilamentKitApp(app: AppViewModel = viewModel()) {
    val paired by produceState<Boolean?>(null) { value = app.isPaired() }
    val start = when (paired) {
        null -> return // settings not read yet
        true -> Routes.HOME
        false -> Routes.PAIR
    }
    // API 37: every LAN socket needs ACCESS_LOCAL_NETWORK. Asked once at start; the session waits for it.
    val localNetwork = rememberLocalNetworkAccess(autoRequest = true, onGranted = app.session::refresh)
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val route = entry?.destination?.route

    val api by app.session.api.collectAsStateWithLifecycle()
    val config by app.session.config.collectAsStateWithLifecycle()
    val skipFingerprintCheck by app.settings.skipFingerprintCheck.collectAsStateWithLifecycle(initialValue = false)
    val connection by app.session.connection.collectAsStateWithLifecycle()
    val fp = config?.fingerprint

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
    // On screen: the dot follows the server, and is checked right away on return to the app. Not while pairing, where
    // nothing shows it.
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val pairing = route == Routes.PAIR
    LaunchedEffect(lifecycle, pairing) {
        if (pairing) return@LaunchedEffect
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

    // Global 401 / certificate change: go to Pair (once per request, also across rotation).
    val pairRequests by app.router.requests.collectAsStateWithLifecycle()
    LaunchedEffect(pairRequests) {
        if (pairRequests > app.handledPairRequests) {
            app.handledPairRequests = pairRequests
            // a load being written keeps its card: it shows the result once pairing is done
            closeSpoolCard(loadVm) { spoolVm?.dismiss() }
            if (nav.currentDestination?.route != Routes.PAIR) nav.navigateClearing(Routes.PAIR)
        }
    }

    // Tag taps open the spool card anywhere except pairing and the add flow (AddViewModel takes taps itself).
    val tapVm = spoolVm
    val tapsOn = tapVm != null && route != null && route != Routes.PAIR && route != Routes.ADD
    LaunchedEffect(tapVm, loadVm, tapsOn) {
        if (tapsOn) TagEvents.taps.collect {
            // a new tap replaces the open card and any load flow on it, except while a load is being written:
            // then the tap is ignored so the user sees that write's result
            closeSpoolCard(loadVm) { tapVm.onTag(it) }
        }
    }

    NavHost(nav, startDestination = start) {
        composable(Routes.PAIR) {
            val pairVm: PairViewModel = viewModel(factory = viewModelFactory {
                initializer { PairViewModel(app.settings, NetPairingBackend()) }
            })
            val notice by app.router.notice.collectAsStateWithLifecycle()
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
                        onPaired = {
                            app.router.clear()
                            nav.navigateClearing(Routes.HOME)
                        },
                        modifier = Modifier.weight(1f),
                        skipCheck = skipFingerprintCheck,
                        onSkipCheck = app::setSkipFingerprintCheck,
                        canTrust = { config.canTrust(it.expected) },
                        onTrust = { m -> app.trustCertificate(m.expected, m.actual) { nav.navigateClearing(Routes.HOME) } },
                        version = version,
                    )
                }
            }
        }

        composable(Routes.HOME) {
            LaunchedEffect(Unit) { app.refreshDrafts() }
            val drafts by app.draftList.collectAsStateWithLifecycle()
            val update = updater?.state?.collectAsStateWithLifecycle()?.value ?: UpdateUi()
            // Read each time Home is shown while online; null (card says "not available") when it cannot be read.
            val presets by produceState<ProfileStatus?>(null, api, online) {
                val a = api
                value = if (a == null || !online) null else try {
                    a.profileStatus()
                } catch (e: kotlinx.coroutines.CancellationException) {
                    throw e
                } catch (_: Exception) {
                    null
                }
            }
            HomeScreen(
                serverName = config?.name.orEmpty(),
                connection = connection,
                drafts = drafts,
                update = update,
                version = version,
                onAddSpools = { nav.navigate(Routes.add()) },
                onAddByHand = { nav.navigate(Routes.add(manual = true)) },
                labelPhotos = labelPhotos,
                onAddProfile = { nav.navigate(Routes.ADD_PROFILE) },
                onSearch = { nav.navigate(Routes.SEARCH) },
                onPrinters = { nav.navigate(Routes.PRINTERS) },
                onHistory = { nav.navigate(Routes.HISTORY) },
                onSettings = { nav.navigate(Routes.SETTINGS) },
                onResumeDraft = { id -> nav.navigate(Routes.add(draft = id)) },
                onRetryConnection = app.session::refresh,
                onReviewCertificate = app.router::pairAgain,
                onInstallUpdate = { updater?.install() },
                onConfirmInstall = { updater?.confirmInstall() },
                presets = presets,
                showPresets = api != null,
                localNetworkPanel = { LocalNetworkPanel(localNetwork) },
                extra = { if (BuildConfig.DEBUG) SimulateTag() },
            )
        }

        composable(Routes.HISTORY) {
            val a = api
            if (a == null) {
                NotPaired { nav.navigateClearing(Routes.PAIR) }
                return@composable
            }
            HistoryEntry(a, onBack = { nav.popBackStack() }, onPairAgain = app.router::pairAgain)
        }

        composable(Routes.SEARCH) {
            val a = api
            if (a == null) {
                NotPaired { nav.navigateClearing(Routes.PAIR) }
                return@composable
            }
            val searchVm: SearchViewModel = viewModel(factory = viewModelFactory {
                initializer { SearchViewModel { q, sealedOnly -> a.search(q, sealedOnly) } }
            })
            SearchScreen(
                vm = searchVm,
                onOpenSpool = { spoolVm?.open(it) },
                onPairAgain = app.router::pairAgain,
                onBack = { nav.popBackStack() },
            )
        }

        composable(
            Routes.ADD,
            arguments = listOf(
                navArgument("tag") { type = NavType.StringType; nullable = true; defaultValue = null },
                navArgument("draft") { type = NavType.StringType; nullable = true; defaultValue = null },
                navArgument("manual") { type = NavType.BoolType; defaultValue = false },
            ),
        ) { e ->
            val a = api
            if (a == null) {
                NotPaired { nav.navigateClearing(Routes.PAIR) }
                return@composable
            }
            val tag = e.arguments?.getString("tag")
            val draft = e.arguments?.getString("draft")
            val manual = e.arguments?.getBoolean("manual") == true
            val addVm: AddViewModel = viewModel(factory = viewModelFactory {
                initializer { AddViewModel(IntakeApi.of(a), app.drafts, draftId = draft, initialTag = tag, manual = manual) }
            })
            if (BuildConfig.DEBUG && !manual) LaunchedEffect(addVm) { DebugPhotos.photos.collect(addVm::addPhoto) }
            AddSpoolsScreen(
                vm = addVm,
                onClose = { nav.popBackStack() },
                onDone = { nav.popBackStack(Routes.HOME, inclusive = false) },
                onPairAgain = app.router::pairAgain,
            )
        }

        composable(Routes.ADD_PROFILE) {
            val a = api
            if (a == null) {
                NotPaired { nav.navigateClearing(Routes.PAIR) }
                return@composable
            }
            val profileVm: AddProfileViewModel = viewModel(factory = viewModelFactory {
                initializer { AddProfileViewModel(ProfileApi.of(a)) }
            })
            AddProfileScreen(
                vm = profileVm,
                onBack = { nav.popBackStack() },
                onPairAgain = app.router::pairAgain,
            )
        }

        composable(Routes.SETTINGS) {
            SettingsScreen(
                config = config,
                onPairAgain = app.router::pairAgain,
                onForget = { app.forget { nav.navigateClearing(Routes.PAIR) } },
                onLicences = { nav.navigate(Routes.LICENCES) },
                skipFingerprintCheck = skipFingerprintCheck,
                onSkipFingerprintCheck = app::setSkipFingerprintCheck,
                setupUrl = { SetupPageTexts.url(app.session.baseUrl()) },
            )
        }

        composable(Routes.LICENCES) { LicencesScreen() }

        composable(Routes.PRINTERS) {
            val a = api
            if (a == null) {
                NotPaired { nav.navigateClearing(Routes.PAIR) }
                return@composable
            }
            PrintersEntry(a, onPairAgain = app.router::pairAgain)
        }
    }

    // The spool card, over whatever screen is open (not over pairing or the add flow).
    spoolVm?.let { vm ->
        val spoolState by vm.state.collectAsStateWithLifecycle()
        if (spoolState != SpoolUiState.Idle && route != Routes.ADD && route != Routes.PAIR) {
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
                                nav.navigate(Routes.add(tag = tag, manual = !labelPhotos))
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

/**
 * Android draws apps edge to edge (target SDK 35+). The status and navigation bars stay transparent over the app's own
 * background, with icons that follow the phone's light or dark setting as the app does.
 */
internal fun ComponentActivity.appEdgeToEdge() = enableEdgeToEdge(
    statusBarStyle = SystemBarStyle.auto(AndroidColor.TRANSPARENT, AndroidColor.TRANSPARENT),
    navigationBarStyle = SystemBarStyle.auto(AndroidColor.TRANSPARENT, AndroidColor.TRANSPARENT),
)

/**
 * The app's root: light or dark as the phone is set, the background fills the whole window, behind the bars too, and
 * every screen is kept clear of the status bar, navigation bar, cutouts and keyboard, here once.
 */
@Composable
internal fun AppFrame(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()) {
        Surface(Modifier.fillMaxSize()) {
            Box(Modifier.fillMaxSize().safeDrawingPadding()) { content() }
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

/** Navigates to [route] as the only screen on the back stack. */
private fun NavHostController.navigateClearing(route: String) = navigate(route) {
    popUpTo(graph.id) { inclusive = true }
    launchSingleTop = true
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
