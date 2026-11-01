package com.thompsonfabco.filamentkit

import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
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
import androidx.lifecycle.compose.collectAsStateWithLifecycle
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
import com.thompsonfabco.filamentkit.session.AppViewModel
import com.thompsonfabco.filamentkit.session.Connection
import com.thompsonfabco.filamentkit.session.PairNotice
import com.thompsonfabco.filamentkit.session.UNPAIRED_MESSAGE
import com.thompsonfabco.filamentkit.session.isPaired
import com.thompsonfabco.filamentkit.tags.TagEvents
import com.thompsonfabco.filamentkit.tags.disableTagReader
import com.thompsonfabco.filamentkit.tags.enableTagReader
import com.thompsonfabco.filamentkit.ui.add.AddSpoolsScreen
import com.thompsonfabco.filamentkit.ui.add.AddViewModel
import com.thompsonfabco.filamentkit.ui.add.IntakeApi
import com.thompsonfabco.filamentkit.ui.home.HomeScreen
import com.thompsonfabco.filamentkit.ui.pair.NetPairingBackend
import com.thompsonfabco.filamentkit.ui.pair.PairScreen
import com.thompsonfabco.filamentkit.ui.pair.PairViewModel
import com.thompsonfabco.filamentkit.ui.printers.PrintersEntry
import com.thompsonfabco.filamentkit.ui.search.SearchScreen
import com.thompsonfabco.filamentkit.ui.search.SearchViewModel
import com.thompsonfabco.filamentkit.ui.settings.SettingsScreen
import com.thompsonfabco.filamentkit.ui.spool.ApiSpoolBackend
import com.thompsonfabco.filamentkit.ui.spool.SpoolHost
import com.thompsonfabco.filamentkit.ui.spool.SpoolUiState
import com.thompsonfabco.filamentkit.ui.spool.SpoolViewModel
import com.thompsonfabco.filamentkit.update.UpdateUi

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(Modifier.fillMaxSize()) { FilamentKitApp() }
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

private object Routes {
    const val PAIR = "pair"
    const val HOME = "home"
    const val SEARCH = "search"
    const val SETTINGS = "settings"
    const val PRINTERS = "printers"
    const val ADD = "add?tag={tag}&draft={draft}"

    fun add(tag: String? = null, draft: String? = null): String {
        val query = listOfNotNull(tag?.let { "tag=${Uri.encode(it)}" }, draft?.let { "draft=${Uri.encode(it)}" })
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
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val route = entry?.destination?.route

    val api by app.session.api.collectAsStateWithLifecycle()
    val config by app.session.config.collectAsStateWithLifecycle()
    val connection by app.session.connection.collectAsStateWithLifecycle()
    val fp = config?.fingerprint

    // App-wide, one per Api (owned by AppViewModel; replaced when the pinned client changes).
    val spoolVm by app.spool.current.collectAsStateWithLifecycle()
    val updater by app.updater.current.collectAsStateWithLifecycle()
    val online = connection is Connection.Online
    LaunchedEffect(updater, online) {
        if (online) updater?.onOnline()
    }

    // Global 401 / certificate change: go to Pair (once per request, also across rotation).
    val pairRequests by app.router.requests.collectAsStateWithLifecycle()
    LaunchedEffect(pairRequests) {
        if (pairRequests > app.handledPairRequests) {
            app.handledPairRequests = pairRequests
            spoolVm?.dismiss()
            if (nav.currentDestination?.route != Routes.PAIR) nav.navigateClearing(Routes.PAIR)
        }
    }

    // Tag taps open the spool card anywhere except pairing and the add flow (AddViewModel takes taps itself).
    val tapVm = spoolVm
    val tapsOn = tapVm != null && route != null && route != Routes.PAIR && route != Routes.ADD
    LaunchedEffect(tapVm, tapsOn) {
        if (tapsOn) TagEvents.taps.collect { tapVm.onTag(it) }
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
            val servers = remember { app.discovery.servers() }
            val discovered by servers.collectAsStateWithLifecycle(emptyList())
            Column(Modifier.fillMaxSize()) {
                if (notice == PairNotice.Unpaired || (config != null && !config.isPaired())) {
                    Text(
                        UNPAIRED_MESSAGE,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(start = 24.dp, end = 24.dp, top = 24.dp),
                    )
                }
                PairScreen(
                    viewModel = pairVm,
                    discovered = discovered,
                    onPaired = {
                        app.router.clear()
                        nav.navigateClearing(Routes.HOME)
                    },
                    modifier = Modifier.weight(1f),
                )
            }
        }

        composable(Routes.HOME) {
            LaunchedEffect(Unit) { app.refreshDrafts() }
            val drafts by app.draftList.collectAsStateWithLifecycle()
            val update = updater?.state?.collectAsStateWithLifecycle()?.value ?: UpdateUi()
            HomeScreen(
                serverName = config?.name.orEmpty(),
                connection = connection,
                drafts = drafts,
                update = update,
                onAddSpools = { nav.navigate(Routes.add()) },
                onSearch = { nav.navigate(Routes.SEARCH) },
                onPrinters = { nav.navigate(Routes.PRINTERS) },
                onSettings = { nav.navigate(Routes.SETTINGS) },
                onResumeDraft = { id -> nav.navigate(Routes.add(draft = id)) },
                onRetryConnection = app.session::refresh,
                onReviewCertificate = app.router::pairAgain,
                onInstallUpdate = { updater?.install() },
                onConfirmInstall = { updater?.confirmInstall() },
                extra = { if (BuildConfig.DEBUG) SimulateTag() },
            )
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
            ),
        ) { e ->
            val a = api
            if (a == null) {
                NotPaired { nav.navigateClearing(Routes.PAIR) }
                return@composable
            }
            val tag = e.arguments?.getString("tag")
            val draft = e.arguments?.getString("draft")
            val addVm: AddViewModel = viewModel(factory = viewModelFactory {
                initializer { AddViewModel(IntakeApi.of(a), app.drafts, draftId = draft, initialTag = tag) }
            })
            AddSpoolsScreen(
                vm = addVm,
                onClose = { nav.popBackStack() },
                onDone = { nav.popBackStack(Routes.HOME, inclusive = false) },
                onPairAgain = app.router::pairAgain,
            )
        }

        composable(Routes.SETTINGS) {
            SettingsScreen(
                config = config,
                onPairAgain = app.router::pairAgain,
                onForget = { app.forget { nav.navigateClearing(Routes.PAIR) } },
            )
        }

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
            Dialog(onDismissRequest = vm::dismiss) {
                Surface(shape = MaterialTheme.shapes.large, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.verticalScroll(rememberScrollState())) {
                        SpoolHost(
                            viewModel = vm,
                            onStartAdd = { tag ->
                                vm.dismiss()
                                nav.navigate(Routes.add(tag = tag))
                            },
                            onPairAgain = {
                                vm.dismiss()
                                app.router.pairAgain()
                            },
                            onClose = vm::dismiss,
                        )
                    }
                }
            }
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
